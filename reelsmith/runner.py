"""reelsmith run: a self-hosted Claude Agent SDK session that makes one film in one project with the reelsmith tools.

The session gets the reelsmith MCP server, file tools fenced by guard.py and web search; no shell. The model is served
by Anthropic or DeepSeek (backends.py). Its state lives in <project>/build/run_state.json, so an interrupted run
resumes its own session; out/run_report.json says how it ended.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import backends, guard
from .workspace import PROJECT_FILE, WorkspaceError, find_workspace, project_root

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "docs" / "manual.md"
RENDERER_SRC = ROOT / "renderer" / "src"
STATE_FILE = Path("build") / "run_state.json"
REPORT_FILE = Path("out") / "run_report.json"
# the model defaults to the backend's own (backends.py)
DEFAULTS = {"backend": "anthropic", "effort": "medium", "budget_usd": 5.0, "max_minutes": 120,
            "stall_minutes": 60, "max_turns": None, "fixups": 2}  # a full render may take 55 min in one call
BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"]
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
# the CLI prices a non-Anthropic backend with its Claude table: its own cap only backs up the runner's estimate
CLI_BUDGET_FACTOR = 1000


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def sanitized(path) -> str:
    """How Claude Code names a cwd's folder under ~/.claude/projects."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


# ------------------------------------------------------------------ settings
@dataclasses.dataclass
class Settings:
    model: str
    effort: str | None
    budget_usd: float
    max_minutes: float
    stall_minutes: float
    max_turns: int | None
    fixups: int
    proxy: str | None = None
    backend: str = "anthropic"


def settings_for(ws, model=None, budget_usd=None, max_minutes=None, max_turns=None, backend=None) -> Settings:
    """CLI flags over workspace.json "runner" over the defaults. The workspace's model goes with the workspace's
    backend: a --backend that switches away from it starts from the new backend's default model."""
    cfg = dict(DEFAULTS)
    own = (ws.config.get("runner") if ws is not None else None) or {}
    if not isinstance(own, dict):
        raise WorkspaceError('workspace.json "runner" must be an object')
    cfg.update({k: v for k, v in own.items() if v is not None})
    for key, value in (("budget_usd", budget_usd), ("max_minutes", max_minutes), ("max_turns", max_turns)):
        if value is not None:
            cfg[key] = value
    own_backend = backends.get(cfg["backend"])
    chosen = backends.get(backend) if backend else own_backend
    if not model:
        model = own.get("model") if chosen is own_backend and own.get("model") else chosen.model
    s = Settings(model=str(model), effort=cfg.get("effort") or None, budget_usd=float(cfg["budget_usd"]),
                 max_minutes=float(cfg["max_minutes"]), stall_minutes=float(cfg["stall_minutes"]),
                 max_turns=int(cfg["max_turns"]) if cfg.get("max_turns") else None, fixups=int(cfg["fixups"]),
                 proxy=cfg.get("proxy") or os.environ.get("REELSMITH_PROXY") or None, backend=chosen.name)
    if s.budget_usd <= 0 or s.max_minutes <= 0 or s.stall_minutes <= 0:
        raise WorkspaceError("budget_usd, max_minutes and stall_minutes must be > 0")
    return s


def key_for(ws, name: str) -> str:
    """A key from the workspace .env, else the environment; "" when neither has it."""
    keys = ws.keys if ws is not None else {}
    value = keys.get(name) if hasattr(keys, "get") else None
    return value or os.environ.get(name) or ""


# ------------------------------------------------------------------ prompts
def system_append(project: Path, ws) -> str:
    notes = ws.notes_path if ws is not None else None
    rows = [
        "You are making a vertical short in this project with the reelsmith tools. Nobody is online: every choice "
        "is yours (topic angle, script, voice, pictures, edit); write your reasons in script.md.",
        f"Read the manual first ({MANUAL}, or the manual tool), then the notes"
        + (f" ({notes})" if notes else "") + " for what worked before.",
        f"Project: {project}. Pass it as `project` to every reelsmith tool.",
        "Look at what you make: preview and read the stills before you render, review the film after.",
    ]
    return "\n".join(rows)


def first_prompt(project: Path, brief: str) -> str:
    return (f"{brief.strip()}\n\nProject: {project}\n"
            "The project is yours: research, write the script, gather assets, edit, preview, render. Finish when "
            "out/film.mp4 passes the render checks and you would publish it, then note what you learned.")


def resume_prompt(why: str, state: dict) -> str:
    return (f"(runner) Resuming: the last run stopped ({why}). Look at what is in the project (describe, check) "
            f"and carry on until out/film.mp4 passes. Spent so far: ${state.get('cost_usd', 0):.2f}.")


def fixup_prompt(problems: list[str]) -> str:
    return ("(runner) The film is not delivered yet: " + "; ".join(problems)
            + ". Fix exactly these, render again, and finish.")


# ------------------------------------------------------------------ options
def build_options(project: Path, ws, settings: Settings, scope: guard.Scope, log, resume: str | None = None,
                  budget_left: float | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
    backend = backends.get(settings.backend)
    key = key_for(ws, backend.key)
    if not key:
        raise WorkspaceError(f"{backend.key} is missing: put it in the workspace .env or the environment")
    stall_ms = int(settings.stall_minutes * 60 * 1000)
    env = {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        # nothing of the host's own Claude Code setup reaches the session
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1", "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
        "CLAUDE_CODE_DISABLE_CRON": "1", "CLAUDE_CODE_DISABLE_WORKFLOWS": "1",
        "MCP_TOOL_TIMEOUT": str(stall_ms),          # a render can take many minutes in one call
        "CLAUDE_AGENT_SDK_CLIENT_APP": "reelsmith-runner/1",
    }
    workspace_id = key_for(ws, "ANTHROPIC_WORKSPACE_ID") if backend.name == "anthropic" else ""
    env.update(backends.cli_env(backend, settings.model, key, workspace_id))
    if settings.proxy:
        env.update(HTTPS_PROXY=settings.proxy, HTTP_PROXY=settings.proxy, NO_PROXY="localhost,127.0.0.1")
    server = {"type": "stdio", "command": sys.executable, "args": ["-m", "reelsmith.mcp_server"],
              "env": {"REELSMITH_ROOT": str(scope.home), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                      "PYTHONSAFEPATH": "1"}}
    from .tools import TOOLS
    mcp_tools = [f"{guard.MCP_PREFIX}{name}" for name in TOOLS]
    stderr_path = project / "build" / "runner-cli.log"

    def stderr(line: str) -> None:
        with open(stderr_path, "a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")

    budget = max(0.01, settings.budget_usd if budget_left is None else budget_left)
    if not backend.cli_cost:
        budget *= CLI_BUDGET_FACTOR                # run_session enforces the real budget
    return ClaudeAgentOptions(
        model=backends.cli_model(backend, settings.model), effort=settings.effort, thinking={"type": "adaptive"},
        max_budget_usd=round(budget, 2), max_turns=settings.max_turns,
        system_prompt={"type": "preset", "preset": "claude_code", "append": system_append(project, ws)},
        tools=BUILTIN_TOOLS, allowed_tools=BUILTIN_TOOLS + mcp_tools, permission_mode="dontAsk",
        setting_sources=[], cwd=str(project), mcp_servers={"reelsmith": server}, strict_mcp_config=True,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard.make_hook(scope, log.denied)], timeout=30)]},
        env=env, resume=resume, stderr=stderr, max_buffer_size=MAX_MESSAGE_BYTES)


# ------------------------------------------------------------------ the session
def _clip(value, limit=4000):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [{len(value) - limit} more]"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    return value


class SessionLog:
    """build/runner.jsonl gets every message; stdout gets one readable line per step."""

    def __init__(self, project: Path, out=None):
        self.path = project / "build" / "runner.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a", encoding="utf-8")
        self.out = out or sys.stdout
        self.denials: list[dict] = []
        self.cli_cost = True        # False: the CLI's cost figure is not this backend's

    def event(self, kind: str, **data) -> None:
        row = {"t": now_iso(), "kind": kind, **data}
        self.fh.write(json.dumps(_clip(row), ensure_ascii=False, default=str) + "\n")
        self.fh.flush()

    def line(self, text: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {text}", file=self.out, flush=True)

    def denied(self, tool: str, what: str, why: str) -> None:
        self.denials.append({"tool": tool, "input": what, "reason": why})
        self.event("denied", tool=tool, input=what, reason=why)
        self.line(f"DENY {tool} {what} -- {why}")

    def message(self, msg) -> None:
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, UserMessage
        try:
            data = dataclasses.asdict(msg) if dataclasses.is_dataclass(msg) else {"repr": repr(msg)}
        except Exception:  # noqa: BLE001
            data = {"repr": repr(msg)[:2000]}
        self.event("message", type=type(msg).__name__, data=data)
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            d = msg.data or {}
            servers = ", ".join(f"{s.get('name')}:{s.get('status')}" for s in d.get("mcp_servers") or [])
            self.line(f"session {d.get('session_id')} model={d.get('model')} tools={len(d.get('tools') or [])} "
                      f"mcp=[{servers}]")
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                kind = type(block).__name__
                if kind == "TextBlock" and block.text.strip():
                    self.line("say " + re.sub(r"\s+", " ", block.text.strip())[:200])
                elif kind == "ToolUseBlock":
                    self.line(f"-> {block.name} {guard.brief_input(block.name, block.input)}")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if type(block).__name__ == "ToolResultBlock" and block.is_error:
                    text = block.content if isinstance(block.content, str) else json.dumps(block.content,
                                                                                           ensure_ascii=False)
                    self.line("<- error " + re.sub(r"\s+", " ", str(text))[:200])
        elif isinstance(msg, ResultMessage):
            cost = (f"cost=${msg.total_cost_usd or 0:.2f}" if self.cli_cost
                    else f"cli-priced=${msg.total_cost_usd or 0:.2f} (Claude prices, not used)")
            self.line(f"result {msg.subtype} turns={msg.num_turns} {cost}")

    def close(self) -> None:
        self.fh.close()


def merge_usage(dst: dict, src: dict) -> dict:
    """One API message arrives as several AssistantMessages: keep each counter's largest value."""
    for key, value in (src or {}).items():
        if isinstance(value, dict):
            merge_usage(dst.setdefault(key, {}), value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            dst[key] = max(dst.get(key) or 0, value)
    return dst


def estimate_cost(seen: dict, model: str, backend: str = "anthropic") -> float:
    """$ for streamed usage rows at the backend's prices (DeepSeek's at peak)."""
    return round(backends.cost(backends.get(backend), seen, model), 4)


async def run_session(options, prompt: str, log: SessionLog, query_fn=None, on_session=None,
                      stall_s: float = 1800, wall_s: float = 7200, cost_fn=None,
                      budget_usd: float | None = None) -> dict:
    """Drive one query. Never raises: the outcome says what happened. With cost_fn (usage rows -> $) and budget_usd,
    the session stops once the spend estimated from its streamed usage reaches the budget."""
    if query_fn is None:
        from claude_agent_sdk import query as query_fn
    from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage
    outcome = {"session_id": None, "result": None, "error": None, "aborted": None, "messages": 0, "usage": {}}
    started = last = time.monotonic()
    row_cost: dict = {}
    spent = 0.0

    async def consume():
        nonlocal last, spent
        async for msg in query_fn(prompt=prompt, options=options):
            last = time.monotonic()
            outcome["messages"] += 1
            log.message(msg)
            if isinstance(msg, AssistantMessage) and isinstance(getattr(msg, "usage", None), dict):
                key = getattr(msg, "message_id", None) or getattr(msg, "uuid", None) or f"#{outcome['messages']}"
                row = outcome["usage"].setdefault(key, {"model": getattr(msg, "model", None), "usage": {}})
                merge_usage(row["usage"], msg.usage)
                if cost_fn is not None:
                    now_cost = cost_fn({key: row})
                    spent += now_cost - row_cost.get(key, 0.0)
                    row_cost[key] = now_cost
                    if budget_usd is not None and spent >= budget_usd and not outcome["aborted"]:
                        outcome["aborted"] = f"the estimated ${spent:.2f} reached the ${budget_usd:.2f} budget"
                        log.line(f"abort: {outcome['aborted']}")
                        asyncio.current_task().cancel()     # lands in the SDK's next await, like the watchdog's
            sid = getattr(msg, "session_id", None)
            if isinstance(msg, SystemMessage) and isinstance(msg.data, dict):
                sid = sid or msg.data.get("session_id")
            if sid and sid != outcome["session_id"]:
                outcome["session_id"] = sid
                if on_session:
                    on_session(sid)
            if isinstance(msg, ResultMessage):
                outcome["result"] = msg

    task = asyncio.create_task(consume())
    while not task.done():
        await asyncio.wait({task}, timeout=min(30.0, max(0.05, stall_s / 4)))
        now = time.monotonic()
        if task.done():
            break
        if not outcome["aborted"]:
            if now - last > stall_s:
                outcome["aborted"] = f"no message for {int(now - last)} s"
            elif now - started > wall_s:
                outcome["aborted"] = f"over the {wall_s / 60:g} minute limit"
            if outcome["aborted"]:
                log.line(f"abort: {outcome['aborted']}")
        if outcome["aborted"]:
            task.cancel()
    try:
        await task
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 - the SDK's task groups wrap a cancel in an exception group
        if outcome["aborted"]:
            pass
        elif isinstance(exc, asyncio.CancelledError):
            raise
        else:
            outcome["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
            log.line(f"session error {outcome['error']}")
    return outcome


def summary(outcome: dict, model: str, backend: str = "anthropic") -> dict:
    """One session's row. Its cost is the CLI's figure when the CLI prices the backend right, else an estimate from
    the usage (the larger of the streamed messages' and the CLI's per-model totals, which add background calls)."""
    b = backends.get(backend)
    r = outcome.get("result")
    row = {"session_id": outcome.get("session_id"), "aborted": outcome.get("aborted"), "error": outcome.get("error")}
    streamed = estimate_cost(outcome.get("usage") or {}, model, b.name)
    if r is not None:
        row.update(subtype=r.subtype, is_error=r.is_error, turns=r.num_turns or 0, cost_usd=r.total_cost_usd or 0.0,
                   stop_reason=getattr(r, "stop_reason", None))
        if not b.cli_cost:
            totals = backends.model_usage_rows(getattr(r, "model_usage", None))
            if not totals and isinstance(getattr(r, "usage", None), dict):
                totals = {"result": {"model": model, "usage": r.usage}}
            row.update(cost_usd=max(streamed, estimate_cost(totals, model, b.name)), cost_estimated=True,
                       cli_cost_usd=r.total_cost_usd or 0.0)
    else:
        row.update(turns=0, cost_usd=streamed, cost_estimated=True)
    return row


def stop_reason(row: dict) -> str:
    if row.get("aborted"):
        return row["aborted"]
    if row.get("error"):
        return row["error"]
    if row.get("subtype") and row.get("subtype") != "success":
        return row["subtype"]
    return "finished"


# ------------------------------------------------------------------ delivery
def delivery(project: Path) -> tuple[bool, list[str], dict]:
    """(delivered, problems, check summary): out/film.mp4 exists, render's report says ok, and check has no errors."""
    from .checks import check_project
    problems = []
    try:
        issues = check_project(project)
    except Exception as exc:  # noqa: BLE001
        issues = []
        problems.append(f"check failed to run: {exc}")
    errors = [str(i) for i in issues if i.level == "error"]
    problems += errors[:10]
    counts = {lvl: sum(1 for i in issues if i.level == lvl) for lvl in ("error", "warning", "advice")}
    film = project / "out" / "film.mp4"
    good, failed = project / "out" / "report.json", project / "build" / "report.json"
    if not film.is_file():
        problems.append("out/film.mp4 does not exist: render it")
    elif (read_json(good, {}) or {}).get("ok") is not True:
        problems.append("out/report.json does not say the film passed: render again")
    elif failed.is_file() and failed.stat().st_mtime > good.stat().st_mtime:
        last = read_json(failed, {}) or {}
        if last.get("ok") is False:
            why = str(last.get("error") or "").strip().splitlines()[:1]
            problems.append(f"the latest render failed at {last.get('stage') or '?'}"
                            + (f" ({why[0][:200]})" if why else "") + "; out/film.mp4 is an older film")
    if film.is_file() and not problems:
        newer = changed_since(project, film.stat().st_mtime)
        if newer:
            problems.append(f"{newer} changed after the last render: render again")
    return not problems, problems, {"counts": counts, "errors": errors[:10]}


def changed_since(project: Path, when: float) -> str | None:
    """The first input of the film (project.json, voice, assets, library components) modified after `when`. With the
    render's recorded inputs, an edit to project.json's meta alone and a component the film does not use are not
    changes to the film."""
    from .render import cut_digest
    inputs = (read_json(project / "out" / "report.json", {}) or {}).get("inputs") or {}
    ws = find_workspace(project)
    roots = [project / "voice", project / "assets"]
    files = [p for r in roots if r.is_dir() for p in r.rglob("*") if p.is_file()]
    if ws is not None and ws.components_dir.is_dir():
        parts = [p for p in ws.components_dir.rglob("*") if p.is_file()]
        used = inputs.get("components")
        if isinstance(used, list):
            # a component is its <Name>.meta.json and siblings; helpers without one may be imported by any
            named = {p.name[:-len(".meta.json")] for p in parts if p.name.endswith(".meta.json")}
            parts = [p for p in parts if p.name.split(".")[0] not in named or p.name.split(".")[0] in used]
        files += parts
    doc = project / PROJECT_FILE
    try:
        if doc.stat().st_mtime > when + 1:
            data = read_json(doc, None)
            if not (inputs.get("cut") and isinstance(data, dict) and cut_digest(data) == inputs["cut"]):
                return PROJECT_FILE
    except OSError:
        pass
    for p in files:
        try:
            if p.stat().st_mtime > when + 1:
                return p.relative_to(project).as_posix() if p.is_relative_to(project) else p.name
        except OSError:
            continue
    return None


# ------------------------------------------------------------------ the run
class Run:
    def __init__(self, project, brief: str | None, settings: Settings, ws=None, query_fn=None, fresh=False,
                 out=None):
        self.project = Path(project)
        self.brief = (brief or "").strip()
        self.settings, self.ws, self.query_fn = settings, ws, query_fn
        self.state_path = self.project / STATE_FILE
        self.state = {} if fresh else (read_json(self.state_path, {}) or {})
        self.backend = backends.get(settings.backend)
        self.log = SessionLog(self.project, out)
        self.log.cli_cost = self.backend.cli_cost
        self.started = time.monotonic()
        self.started_at = now_iso()

    def save(self, **changes) -> None:
        self.state.update(changes, updated_at=now_iso())
        write_json(self.state_path, self.state)

    def spent(self) -> float:
        return round(float(self.state.get("cost_usd") or 0), 4)

    def scope(self) -> guard.Scope:
        spill = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects" / sanitized(
            self.project)
        return guard.scope_for(self.project, self.ws, extra_read=[MANUAL.parent, RENDERER_SRC], spill=spill)

    def wall_left(self) -> float:
        return self.settings.max_minutes * 60 - (time.monotonic() - self.started)

    async def session(self, prompt: str, kind: str, resume: str | None = None) -> dict:
        budget_left = self.settings.budget_usd - self.spent()
        options = build_options(self.project, self.ws, self.settings, self.scope(), self.log, resume=resume,
                                budget_left=budget_left)
        model, b = self.settings.model, self.backend
        self.log.event("run", session=kind, resume=resume, prompt=prompt, backend=b.name, model=model)
        self.log.line(f"{kind} session{' ' + resume if resume else ''} on {b.name} {model} "
                      f"(budget left ${budget_left:.2f}{'' if b.cli_cost else ', estimated at peak prices'})")
        if not backends.can_see(b, model):
            self.log.line(f"warning: {model} takes no images; reading a still will fail")
        self.save(status="running", last_stop="the process was interrupted")

        def remember(sid):
            self.save(session_id=sid)
        own_budget = {} if b.cli_cost else {
            "cost_fn": lambda rows: backends.cost(b, rows, model), "budget_usd": budget_left}
        outcome = await run_session(options, prompt, self.log, query_fn=self.query_fn, on_session=remember,
                                    stall_s=self.settings.stall_minutes * 60, wall_s=max(60.0, self.wall_left()),
                                    **own_budget)
        row = summary(outcome, model, b.name)
        row.update(kind=kind, ended_at=now_iso())
        if not b.cli_cost:
            self.log.line(f"session spend ~${row['cost_usd']:.2f} (estimated at {b.name} peak prices)")
        runs = (self.state.get("runs") or []) + [row]
        self.save(cost_usd=round(self.spent() + float(row.get("cost_usd") or 0), 4),
                  turns=int(self.state.get("turns") or 0) + int(row.get("turns") or 0),
                  runs=runs[-30:], last_stop=stop_reason(row),
                  session_id=row.get("session_id") or self.state.get("session_id"))
        return row

    def plan(self) -> tuple[str, str, str | None]:
        """(kind, prompt, resume id) for the first session of this process."""
        sid = self.state.get("session_id")
        if sid and self.state.get("status") not in ("done", None):
            made_on = self.state.get("backend") or "anthropic"
            if made_on != self.backend.name:
                raise WorkspaceError(f"the unfinished run's session is on {made_on}: resume it with --backend "
                                     f"{made_on}, or start over with --fresh")
            return "resume", resume_prompt(self.state.get("last_stop") or "unknown", self.state), sid
        if not self.brief:
            raise WorkspaceError("a brief is needed for a new run (--brief \"...\")")
        self.save(status="new", brief=self.brief, started_at=self.started_at, session_id=None, cost_usd=0.0,
                  turns=0, runs=[], backend=self.backend.name, model=self.settings.model)
        return "new", first_prompt(self.project, self.brief), None

    async def go(self) -> dict:
        kind, prompt, resume = self.plan()
        fixups = 0
        row: dict = {}
        delivered, problems, check = False, [], {}
        if self.spent() >= self.settings.budget_usd - 0.05:
            delivered, problems, check = delivery(self.project)
            if self.settings.budget_usd <= 0.05:
                problems.append(f"a ${self.settings.budget_usd:.2f} budget leaves nothing above the $0.05 reserve: "
                                "raise --budget-usd")
            else:
                problems.append(f"${self.spent():.2f} of the ${self.settings.budget_usd:.2f} budget is already spent: "
                                "raise --budget-usd to go on, or --fresh to start over")
            self.save(status="stopped", delivered=delivered)
            return self.report(delivered, problems, check, row)
        while True:
            row = await self.session(prompt, kind, resume)
            delivered, problems, check = delivery(self.project)
            if delivered:
                break
            if row.get("error") and not row.get("session_id"):
                break                                   # never got going: retrying would fail the same way
            if self.spent() >= self.settings.budget_usd - 0.05:
                problems.append(f"the ${self.settings.budget_usd:.2f} budget is used up")
                break
            if self.wall_left() < 120:
                problems.append(f"the {self.settings.max_minutes:g} minute limit is reached")
                break
            if fixups >= self.settings.fixups or not self.state.get("session_id"):
                break
            fixups += 1
            resume = self.state.get("session_id")
            if row.get("error") or row.get("aborted"):      # dropped mid-work: pick it up, not a fix-up
                kind, prompt = "resume", resume_prompt(stop_reason(row), self.state)
            else:
                kind, prompt = "fixup", fixup_prompt(problems)
        status = "done" if delivered else "stopped"
        self.save(status=status, delivered=delivered)
        return self.report(delivered, problems, check, row)

    def report(self, delivered: bool, problems: list[str], check: dict, last: dict) -> dict:
        out = {
            "project": str(self.project), "brief": self.state.get("brief"), "backend": self.backend.name,
            "model": self.settings.model, "delivered": delivered, "problems": problems, "check": check,
            "film": str(self.project / "out" / "film.mp4") if (self.project / "out" / "film.mp4").is_file() else None,
            "cost_usd": self.spent(), "cost_estimated": not self.backend.cli_cost,
            "turns": int(self.state.get("turns") or 0),
            "wall_s": round(time.monotonic() - self.started, 1), "started_at": self.started_at,
            "finished_at": now_iso(), "stop": stop_reason(last) if last else None,
            "sessions": self.state.get("runs") or [], "denied": self.log.denials[-50:],
        }
        write_json(self.project / REPORT_FILE, out)
        self.log.line(f"{'DELIVERED' if delivered else 'NOT DELIVERED'} cost=${out['cost_usd']:.2f} "
                      f"turns={out['turns']} wall={out['wall_s'] / 60:.1f} min"
                      + ("" if delivered else " -- " + "; ".join(problems)[:300]))
        self.log.close()
        return out


def run(project, brief: str | None = None, model: str | None = None, budget_usd: float | None = None,
        max_minutes: float | None = None, query_fn=None, fresh: bool = False, max_turns: int | None = None,
        out=None, backend: str | None = None) -> dict:
    root = project_root(project)
    if not (root / PROJECT_FILE).is_file():
        raise WorkspaceError(f"no project at {root} ({PROJECT_FILE} missing): create it with `reelsmith new`")
    ws = find_workspace(root)
    settings = settings_for(ws, model, budget_usd, max_minutes, max_turns, backend)
    return asyncio.run(Run(root, brief, settings, ws, query_fn=query_fn, fresh=fresh, out=out).go())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reelsmith run", description="Let an agent make the film in a project.")
    ap.add_argument("project", help="the project folder (reelsmith new makes one)")
    ap.add_argument("--brief", help="what the film is about; needed unless an unfinished run resumes")
    ap.add_argument("--backend", choices=sorted(backends.BACKENDS),
                    help=f"who serves the model; default {DEFAULTS['backend']} or workspace.json runner.backend")
    ap.add_argument("--model", help="default " + ", ".join(f"{b.model} ({b.name})" for b in backends.BACKENDS.values())
                    + ", or workspace.json runner.model")
    ap.add_argument("--budget-usd", type=float, help="cap on this run's model spend")
    ap.add_argument("--max-minutes", type=float, help="wall-clock cap for this process")
    ap.add_argument("--max-turns", type=int, help="turn cap per session")
    ap.add_argument("--fresh", action="store_true", help="ignore an unfinished run and start a new session")
    args = ap.parse_args(argv)
    try:
        report = run(args.project, args.brief, args.model, args.budget_usd, args.max_minutes, fresh=args.fresh,
                     max_turns=args.max_turns, backend=args.backend)
    except WorkspaceError as exc:
        print(f"reelsmith run: {exc}", file=sys.stderr)
        return 2
    return 0 if report["delivered"] else 1


if __name__ == "__main__":
    sys.exit(main())
