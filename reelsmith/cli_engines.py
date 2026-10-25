"""The runner's codex and dsh engines: an installed coding agent's headless mode drives the session, with the reelsmith
MCP server attached and held to the run's guard (REELSMITH_GUARD_PROJECT).

codex: `codex exec --json` (OpenAI Codex CLI). The host's config.toml and rules are ignored; the sandbox is
workspace-write rooted at the project with the workspace library writable too; commands get no network and no
inherited secrets; approval is never; the server comes in as `-c mcp_servers.reelsmith.*` overrides. Codex reports
its token usage once, when the turn ends.
dsh: `dsh --profile headless --json` (DeepSeek Harness 0.2.1-rc.3), in its own DSH_HOME, with a --patch overlay that
mounts the server, picks the model, pins a workspace-write / approval-never permission preset and turns session-log
upload and session titles off. It reports usage per model call, so a session stops at the budget and at max_turns.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import agentconf, backends, guard
from .providers.config import NO_WINDOW, _kill_tree

ENGINES = ("codex", "dsh")
DSH_VERSION = "0.2.1-rc.3"         # the dsh this engine is tested with: its CLI and events change between releases
DSH_PACKAGE = f"@deepseek-ai/dsh@{DSH_VERSION}"
DSH_PRESET = "reelsmith-run"
DSH_PROVIDER = "deepseek-official"
DSH_DEFAULT_MODEL = "deepseek-flash"
DSH_EFFORTS = ("off", "low", "high", "max")
CODEX_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
# everything but the shell and file edits: no apps, plugins, browsers, subagents or hooks of the host's
CODEX_FEATURES_OFF = ("apps", "plugins", "remote_plugin", "browser_use", "browser_use_external", "in_app_browser",
                      "computer_use", "multi_agent", "hooks", "goals", "tool_suggest", "skill_mcp_dependency_install")
STARTUP_TIMEOUT_S = 60
_LIVE: set = set()          # running agent processes: a runner stopped with Ctrl+C takes them along


@atexit.register
def _kill_live() -> None:
    for proc in list(_LIVE):
        if proc.poll() is None:
            _kill_tree(proc)


# ------------------------------------------------------------------ binaries
def find_codex() -> list[str] | None:
    """CODEX_EXE, else the Windows desktop app's bundled CLI, else codex on PATH (as draw finds it)."""
    from .providers.draw import find_codex as locate
    found = locate()
    return [str(found)] if found else None


def find_dsh(env=None) -> list[str] | None:
    """DSH_EXE, else dsh on PATH, else `npx -y @deepseek-ai/dsh@<DSH_VERSION>`."""
    env = os.environ if env is None else env
    pinned = env.get("DSH_EXE")
    if pinned:
        return [pinned] if Path(pinned).is_file() else None
    on_path = shutil.which("dsh")
    if on_path:
        return [on_path]
    npx = shutil.which("npx")
    return [npx, "-y", DSH_PACKAGE] if npx else None


def codex_user_model(env=None) -> str:
    """The owner's model in CODEX_HOME/config.toml: --ignore-user-config drops the rest of that file."""
    env = os.environ if env is None else env
    home = Path(env.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        import tomllib
        return str(tomllib.loads((home / "config.toml").read_text(encoding="utf-8")).get("model") or "")
    except (ImportError, OSError, ValueError):
        return ""


def server(scope: guard.Scope, python=None) -> dict:
    """The reelsmith MCP server of one run: REELSMITH_ROOT is the workspace, the guard holds it to the project."""
    return {"command": os.path.abspath(str(python or sys.executable)), "args": ["-m", "reelsmith.mcp_server"],
            "env": {"REELSMITH_ROOT": str(scope.home), "REELSMITH_GUARD_PROJECT": str(scope.project),
                    "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONSAFEPATH": "1"}}


def _writable(scope: guard.Scope) -> list[str]:
    return [str(p) for p in scope.library if Path(p).is_dir()]


# ------------------------------------------------------------------ codex
def codex_command(exe: list[str], project: Path, scope: guard.Scope, srv: dict, model: str = "",
                  effort: str | None = None, tool_timeout_s: float = 3600, resume: str | None = None) -> list[str]:
    overrides = {
        "sandbox_mode": "workspace-write",
        "sandbox_workspace_write.writable_roots": _writable(scope),
        "sandbox_workspace_write.network_access": False,
        "approval_policy": "never",
        "shell_environment_policy.inherit": "core",
        "web_search": "live",
        "project_doc_max_bytes": 0,                 # no AGENTS.md of the host's above the project
        "features.respect_system_proxy": True,      # Codex's websocket ignores HTTPS_PROXY without it
        "suppress_unstable_features_warning": True,
        **{f"features.{f}": False for f in CODEX_FEATURES_OFF},
        "mcp_servers.reelsmith.command": srv["command"],
        "mcp_servers.reelsmith.args": srv["args"],
        "mcp_servers.reelsmith.env": srv["env"],
        "mcp_servers.reelsmith.env_vars": agentconf.CODEX_ENV_VARS,
        "mcp_servers.reelsmith.startup_timeout_sec": STARTUP_TIMEOUT_S,
        "mcp_servers.reelsmith.tool_timeout_sec": int(tool_timeout_s),
    }
    if effort:
        overrides["model_reasoning_effort"] = effort
    args = [*exe, "exec", *(["resume"] if resume else []), "--json", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules"]
    if not resume:
        args += ["-C", str(project)]
    for key, value in overrides.items():
        args += ["-c", f"{key}={agentconf.toml_value(value)}"]
    if model:
        args += ["-m", model]
    return args + ([resume] if resume else []) + ["-"]


def codex_env(proxy: str | None = None, base=None) -> dict:
    env = dict(os.environ if base is None else base)
    if proxy:
        env.update(HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="localhost,127.0.0.1")
    return env


# ------------------------------------------------------------------ dsh
def dsh_patch(srv: dict, model: str, effort: str | None = None, tool_timeout_s: float = 3600) -> str:
    """The overlay of one run: the reelsmith server, the model, the permission preset, no session-log upload."""
    j = lambda v: json.dumps(v, ensure_ascii=False)   # noqa: E731
    rows = ["# written by `reelsmith run` for the dsh engine; rewritten every session",
            agentconf.dsh_rows(srv, tool_timeout_s).rstrip("\n"),
            "- id: agent-default-model", "  config:", f"    provider: {DSH_PROVIDER}", f"    model: {j(model)}"]
    if effort:
        rows.append(f"    reasoningEffort: {j(effort)}")
    # headless dsh takes no permission flags: pin the base rows, which otherwise follow DSH_PERMISSION_MODE
    rows += ["- id: sandbox-policy", "  config:", "    mode: workspace-write",
             "- id: approval", "  config:", "    policy: never",
             "- id: permission", "  config:", "    presets:", f"      {DSH_PRESET}:", "        sandbox: workspace-write",
             "        approval: never", f"    defaultPreset: {DSH_PRESET}",
             "- id: session-log-deepseek", "  disabled: true",
             "- id: session-title-llm", "  disabled: true"]       # a paid model call per session nobody reads
    return "\n".join(rows) + "\n"


def dsh_command(exe: list[str], patch: Path, resume: str | None = None) -> list[str]:
    return [*exe, "--patch", str(patch), "--profile", "headless", "--json",
            *(["--session-id", resume] if resume else []), "-"]


def dsh_version(exe: list[str]) -> str:
    """`dsh --version`, or "" when it does not answer."""
    try:
        done = subprocess.run([*exe, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = (done.stdout or "").strip().splitlines()
    return lines[-1].strip() if done.returncode == 0 and lines else ""


def dsh_env(key: str, dsh_home: Path, proxy: str | None = None, base=None) -> dict:
    env = dict(os.environ if base is None else base)
    env.update(DEEPSEEK_API_KEY=key, DSH_HOME=str(dsh_home), DSH_TELEMETRY_MODE="DISABLED",
               DSH_TELEMETRY_DISABLED="1")
    if proxy:
        env.update(HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="localhost,127.0.0.1")
    return env


# ------------------------------------------------------------------ prices
def price_for(model: str, table: dict | None, fallback: dict | None = None) -> backends.Price | None:
    """runner.prices first, then the fallback table (DeepSeek's for dsh, where an unlisted model costs the dearest)."""
    found = {backends.plain(k).lower(): v for k, v in (table or {}).items()}.get(backends.plain(model).lower())
    if found or not fallback:
        return found
    return backends.price(backends.Backend("dsh", DSH_DEFAULT_MODEL, "", fallback, cli_cost=False), model)


def _n(row: dict, key: str) -> int:
    try:
        return max(0, int((row or {}).get(key) or 0))
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------ event streams
def _flat(text, limit=200) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


class Stream:
    """Folds one engine's JSON events into an outcome and logs them."""
    engine = ""

    def __init__(self, log, price: backends.Price | None = None, on_progress=None):
        self.log, self.price, self.on_progress = log, price, on_progress
        self.outcome = {"session_id": None, "result": None, "error": None, "aborted": None, "done": False,
                        "turns": 0, "tool_calls": 0, "usage": {}, "cost_usd": 0.0, "cost_known": price is not None,
                        "exit_code": None, "errors": []}

    def feed(self, event: dict) -> None:
        self.log.event("cli", engine=self.engine, data=event)
        self.handle(event)

    def handle(self, event: dict) -> None:
        raise NotImplementedError

    def session(self, sid) -> None:
        if sid and sid != self.outcome["session_id"]:
            self.outcome["session_id"] = str(sid)
            self.log.line(f"session {sid} on {self.engine}")
            if self.on_progress:
                self.on_progress(self.outcome)

    def add_usage(self, usage: dict) -> None:
        total = self.outcome["usage"]
        for key, value in (usage or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
        self.outcome["cost_usd"] = round(self.cost(total), 6) if self.price else 0.0
        if self.on_progress:
            self.on_progress(self.outcome)

    def cost(self, total: dict) -> float:
        raise NotImplementedError


class CodexStream(Stream):
    """`codex exec --json`: thread.started, turn.completed {usage}, turn.failed, item.*, error."""
    engine = "codex"

    def handle(self, ev: dict) -> None:
        kind, item = ev.get("type"), ev.get("item") if isinstance(ev.get("item"), dict) else {}
        if kind == "thread.started":
            self.session(ev.get("thread_id"))
        elif kind == "turn.completed":
            self.outcome["turns"] += 1
            self.outcome["done"] = True
            self.add_usage(ev.get("usage") if isinstance(ev.get("usage"), dict) else {})
        elif kind == "turn.failed":
            self.outcome["error"] = _flat((ev.get("error") or {}).get("message") or "the turn failed", 400)
            self.log.line(f"session error {self.outcome['error']}")
        elif kind == "error":
            self.outcome["errors"].append(_flat(ev.get("message"), 400))
            self.log.line(f"codex: {_flat(ev.get('message'))}")
        elif kind == "item.started" and item.get("type") == "mcp_tool_call":
            self.log.line(f"-> {item.get('tool')} {guard.brief_input(item.get('tool'), item.get('arguments'))}")
        elif kind == "item.completed":
            self.item(item)

    def item(self, item: dict) -> None:
        kind = item.get("type")
        if kind == "agent_message":
            self.outcome["result"] = str(item.get("text") or "")
            if self.outcome["result"].strip():
                self.log.line("say " + _flat(self.outcome["result"]))
        elif kind == "mcp_tool_call":
            self.outcome["tool_calls"] += 1
            if item.get("status") == "failed" or item.get("error"):
                why = (item.get("error") or {}).get("message") if isinstance(item.get("error"), dict) else ""
                self.log.line(f"<- error {item.get('tool')} {_flat(why)}")
        elif kind == "command_execution":
            self.outcome["tool_calls"] += 1
            self.log.line(f"$ {_flat(item.get('command'), 160)} (exit {item.get('exit_code')})")
        elif kind == "file_change":
            self.outcome["tool_calls"] += 1
            paths = ", ".join(str(c.get("path")) for c in item.get("changes") or [] if isinstance(c, dict))
            self.log.line(f"edit {_flat(paths, 160)}")
        elif kind == "web_search":
            self.outcome["tool_calls"] += 1
            self.log.line(f"search {_flat(item.get('query'), 160)}")
        elif kind == "error":
            self.log.line(f"codex: {_flat(item.get('message'))}")

    def cost(self, t: dict) -> float:
        # OpenAI counts cached input inside input_tokens and reasoning inside output_tokens
        p, inp = self.price, _n(t, "input_tokens")
        cached = min(_n(t, "cached_input_tokens"), inp)
        return ((inp - cached) * p.miss + cached * p.hit + _n(t, "output_tokens") * p.out) / 1e6


class DshStream(Stream):
    """`dsh --profile headless --json` (0.2.1-rc.3): session, status (step_end carries usage, turn_end the turn's
    reason), text, thinking, tool_call, tool_result, final {text}, error (a failure outside a turn)."""
    engine = "dsh"

    def __init__(self, log, price=None, on_progress=None, max_turns: int | None = None):
        super().__init__(log, price, on_progress)
        self.max_turns = max_turns
        self.turn_failed = False

    def handle(self, ev: dict) -> None:
        kind, phase = ev.get("type"), ev.get("phase")
        if kind == "session":
            self.session(ev.get("sessionId"))
        elif kind == "status" and phase == "turn_start":
            # the last turn decides, as it does dsh's exit status
            if self.turn_failed:
                self.outcome["error"] = None
            self.outcome["done"] = self.turn_failed = False
        elif kind == "status" and phase == "turn_end":
            self.turn_end(ev.get("reason") if isinstance(ev.get("reason"), dict) else {})
        elif kind == "status" and phase == "step_end":
            self.outcome["turns"] += 1
            if isinstance(ev.get("usage"), dict):
                self.add_usage(ev["usage"])
            if self.max_turns and self.outcome["turns"] >= self.max_turns and not self.outcome["aborted"]:
                self.outcome["aborted"] = f"max_turns ({self.max_turns}) reached"
        elif kind == "text" and str(ev.get("text") or "").strip():
            self.outcome["result"] = str(ev["text"])
            self.log.line("say " + _flat(ev["text"]))
        elif kind == "tool_call":
            self.outcome["tool_calls"] += 1
            self.log.line(f"-> {ev.get('tool')} {guard.brief_input(str(ev.get('tool')), ev.get('input'))}")
        elif kind == "tool_result" and ev.get("status") == "error":
            self.log.line("<- error " + _flat(ev.get("result") or (ev.get("error") or {}).get("reason")))
        elif kind == "final":
            if str(ev.get("text") or "").strip():
                self.outcome["result"] = str(ev["text"])
        elif kind == "error":
            self.outcome["error"] = _flat(ev.get("message") or "dsh failed", 400)
            self.log.line(f"session error {self.outcome['error']}")

    def turn_end(self, reason: dict) -> None:
        if reason.get("kind") == "completed":
            self.outcome["done"] = True
            return
        self.turn_failed = True
        if reason.get("kind") == "error":
            err = reason.get("error") if isinstance(reason.get("error"), dict) else {}
            self.outcome["error"] = _flat(err.get("message") or err.get("code") or "the turn failed", 400)
        else:
            self.outcome["error"] = f"the turn ended: {reason.get('kind') or 'without a reason'}"
        self.log.line(f"session error {self.outcome['error']}")

    def cost(self, t: dict) -> float:
        # DSH counts disjoint buckets: uncached input, cache reads, cache writes, output
        p = self.price
        return (_n(t, "inputTokens") * p.miss + _n(t, "cacheReadTokens") * p.hit + _n(t, "cacheWriteTokens") * p.write
                + _n(t, "outputTokens") * p.out) / 1e6


# ------------------------------------------------------------------ the process
def drive(cmd: list[str], cwd: Path, env: dict, prompt: str, stream: Stream, stall_s: float = 3600,
          wall_s: float = 7200, budget_usd: float | None = None, stderr_path: Path | None = None) -> dict:
    """Run one headless session to its end and fold its events. Never raises: the outcome says what happened. A
    stall, the wall clock, the budget (when the stream prices its usage) or the stream's own limit kills the tree."""
    out = stream.outcome
    try:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW,
                                start_new_session=os.name != "nt")
    except OSError as exc:
        out["error"] = f"{Path(str(cmd[0])).name} did not start: {exc}"
        stream.log.line(f"session error {out['error']}")
        return out
    _LIVE.add(proc)
    lines: queue.Queue = queue.Queue()
    tail: list[str] = []

    def pump():
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    def drain():
        fh = open(stderr_path, "a", encoding="utf-8") if stderr_path else None
        try:
            for raw in proc.stderr:
                text = raw.decode("utf-8", "replace").rstrip("\r\n")
                tail.append(text)
                del tail[:-40]
                if fh:
                    fh.write(text + "\n")
                    fh.flush()
        finally:
            if fh:
                fh.close()
    threading.Thread(target=pump, daemon=True).start()
    threading.Thread(target=drain, daemon=True).start()
    try:
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()
    except OSError:
        pass
    started = last = time.monotonic()
    try:
        while True:
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                raw = b""
            if raw is None:
                break
            now = time.monotonic()
            if raw:
                last = now
                text = raw.decode("utf-8", "replace").strip()
                if text.startswith("{"):
                    try:
                        event = json.loads(text)
                    except ValueError:
                        event = None
                    if isinstance(event, dict):
                        stream.feed(event)
            if not out["aborted"]:
                if now - last > stall_s:
                    out["aborted"] = f"no event for {int(now - last)} s"
                elif now - started > wall_s:
                    out["aborted"] = f"over the {wall_s / 60:g} minute limit"
                elif (budget_usd is not None and out["cost_known"] and not out["done"]
                      and out["cost_usd"] >= budget_usd):
                    out["aborted"] = f"the estimated ${out['cost_usd']:.2f} reached the ${budget_usd:.2f} budget"
            if out["aborted"]:
                stream.log.line(f"abort: {out['aborted']}")
                _kill_tree(proc)
                break
    except BaseException:
        _kill_tree(proc)            # Ctrl+C: the agent and its MCP server go with the runner
        raise
    try:
        out["exit_code"] = proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out["exit_code"] = proc.wait()
    _LIVE.discard(proc)
    if out["exit_code"] and not out["aborted"] and not out["error"]:
        why = (out["errors"][-1] if out["errors"] else "") or "; ".join(t for t in tail[-3:] if t.strip())
        out["error"] = f"exit {out['exit_code']}" + (f": {why[:400]}" if why else "")
        stream.log.line(f"session error {out['error']}")
    elif not out["done"] and not out["aborted"] and not out["error"]:
        out["error"] = "the session ended without finishing its turn"
    return out


def summary(outcome: dict) -> dict:
    """One session's row for run_state.json and the report."""
    done = outcome.get("done") and not outcome.get("error") and not outcome.get("aborted")
    answer = outcome.get("result")
    return {"session_id": outcome.get("session_id"), "aborted": outcome.get("aborted"), "error": outcome.get("error"),
            "subtype": "success" if done else None, "turns": int(outcome.get("turns") or 0),
            "tool_calls": int(outcome.get("tool_calls") or 0), "cost_usd": round(float(outcome.get("cost_usd") or 0), 6),
            "cost_estimated": True, "cost_known": bool(outcome.get("cost_known")), "usage": outcome.get("usage") or {},
            "exit_code": outcome.get("exit_code"), "answer": answer[:1000] if isinstance(answer, str) else None}
