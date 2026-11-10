"""The watch window's chat: the person talks to an agent about the project they are watching. One Chat per project
holds its transcript (.history/chat.jsonl), runs one turn at a time on a worker thread (runner.Conversation) and
knows which engines can run on this machine."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .. import backends, cli_engines, guard, runner
from . import presence
from ..workspace import WorkspaceError, find_workspace

TRANSCRIPT = Path(".history") / "chat.jsonl"
SHOWN = 200                 # rows GET /api/chat returns
KEPT = 500                  # rows held in memory
COMPACT_AT = 4000           # transcript lines past which it is rewritten without superseded rows
MAX_MESSAGE = 8000
ENGINE_ORDER = ("agent-sdk", "codex", "dsh", "api")
LABELS = {"agent-sdk": "Claude (Agent SDK)", "codex": "Codex", "dsh": "DeepSeek Harness", "api": "API"}
ENGINES_TTL_S = 15.0
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")


class ChatError(Exception):
    """`code` the HTTP status; `key` and `params` the message as a code the window translates."""

    def __init__(self, code: int, message: str, key: str = "chat.error", **params):
        super().__init__(message)
        self.code, self.key, self.params = code, key, params


# ------------------------------------------------------------------ which engines can run here
def claude_cli() -> str | None:
    """The claude CLI the Agent SDK would start: its bundled one, else claude on PATH, else the native installer's."""
    spec = importlib.util.find_spec("claude_agent_sdk")
    if spec and spec.origin:
        for name in ("claude.exe", "claude"):
            bundled = Path(spec.origin).parent / "_bundled" / name
            if bundled.is_file():
                return str(bundled)
    found = shutil.which("claude")
    if found:
        return found
    native = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(native) if native.is_file() else None


def claude_signed_in() -> bool:
    """A sign-in the claude CLI can use; on macOS it lives in the keychain, which is not read here."""
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or sys.platform == "darwin":
        return True
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return (home / ".credentials.json").is_file()


def can_run(engine: str, ws) -> tuple[bool, str]:
    """(available, why): what it runs on when it can, what is missing when it cannot."""
    try:
        s = runner.settings_for(ws, engine=engine)
    except WorkspaceError as exc:
        return False, str(exc)
    if engine == "agent-sdk":
        if importlib.util.find_spec("claude_agent_sdk") is None:
            return False, 'the Claude Agent SDK is not installed: pip install "reelsmith[runner]"'
        if not claude_cli():
            return False, "the claude CLI was not found (neither bundled with the SDK nor on PATH)"
        b = backends.get(s.backend)
        if runner.key_for(ws, b.key):
            return True, f"{b.name} {s.model}, on {b.key}"
        if b.base_url:
            return False, f"{b.key} is missing: put it in the workspace .env"
        if claude_signed_in():
            return True, f"{s.model}, on the claude CLI's sign-in"
        return False, (f"no {b.key} and the claude CLI is not signed in: run claude once and sign in, or put "
                       f"{b.key} in the workspace .env")
    if engine == "codex":
        from ..doctor import check_codex, system
        found = check_codex(system())
        return found.ok, (f"{s.model or 'its default model'}, on the Codex sign-in" if found.ok else found.detail)
    if engine == "dsh":
        exe = cli_engines.find_dsh()
        if not exe:
            return False, f"DeepSeek Harness was not found: install Node.js (for npx {cli_engines.DSH_PACKAGE})"
        if not runner.key_for(ws, "DEEPSEEK_API_KEY"):
            return False, "DEEPSEEK_API_KEY is missing: put it in the workspace .env"
        return True, f"{s.model}" + (" (npx fetches dsh on first use)" if len(exe) > 1 else "")
    prov = s.api
    if prov.key and not runner.key_for(ws, prov.key):
        return False, f"{prov.key} is missing: put it in the workspace .env"
    return True, f"{prov.name} {s.model}"


def default_engine(rows: list[dict], ws) -> str | None:
    """workspace.json runner.engine when it can run here, else the first that can."""
    own = (ws.config.get("runner") if ws is not None else None) or {}
    named = own.get("engine") if isinstance(own, dict) else None
    ok = [r["id"] for r in rows if r["available"]]
    if named in ok:
        return named
    return ok[0] if ok else None


# ------------------------------------------------------------------ the chat
def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(float(value), 3)


def clean_context(context) -> dict | None:
    """The window's selection, kept only where it is well formed."""
    if context is None:
        return None
    if not isinstance(context, dict):
        raise ChatError(400, "context must be an object: {clip, start, end, playhead}", "chat.bad_context")
    out = {}
    if isinstance(context.get("clip"), str) and _ID.match(context["clip"]):
        out["clip"] = context["clip"]
    for key in ("start", "end", "playhead"):
        if _number(context.get(key)) is not None:
            out[key] = _number(context[key])
    beat = context.get("beat")
    if isinstance(beat, int) and not isinstance(beat, bool) and 0 < beat < 10000:
        out["beat"] = beat
    return out or None


def beat_line(context: dict | None) -> str:
    """The selected beat, said to the agent (the runner's own line covers the clip and the playhead)."""
    if not context or "beat" not in context or "clip" in context:
        return ""
    span = f" ({context['start']:.2f}-{context['end']:.2f} s)" if "start" in context and "end" in context else ""
    return f"[selected beat {context['beat']}{span}]\n"


def short_tool(name: str) -> str:
    return str(name or "?").removeprefix(guard.MCP_PREFIX)


class Chat:
    """One project's chat. notify(payload) hears every new or changed row ({"rows", "busy", "turn", "stopping"})."""

    def __init__(self, root: Path, notify=None, *, query_fn=None, client_factory=None, tools_factory=None,
                 engines_fn=None):
        self.root = Path(root)
        self.path = self.root / TRANSCRIPT
        self.notify = notify
        self.seams = {"query_fn": query_fn, "client_factory": client_factory, "tools_factory": tools_factory}
        self.engines_fn = engines_fn or can_run
        self._lock = threading.RLock()
        self.rows: list[dict] = self._load()
        self._next = max((int(r.get("id") or 0) for r in self.rows), default=0) + 1
        self.turn = max((int(r.get("turn") or 0) for r in self.rows), default=0)
        self.busy: int | None = None
        self.engine: str | None = None          # of the turn that runs
        self._stop = threading.Event()
        self._calls: dict = {}                  # the running turn's call ids -> its tool rows
        self._claimed: set = set()              # (turn, batch) already shown on a tool row
        self._origin: dict = {}
        self._thread: threading.Thread | None = None
        self._engines: tuple[float, list[dict]] | None = None

    # ---- the transcript
    def _load(self) -> list[dict]:
        try:
            with self.path.open(encoding="utf-8", errors="replace") as f:
                lines = deque(f, maxlen=COMPACT_AT * 2)
        except OSError:
            return []
        rows: dict[int, dict] = {}          # an id written again (a tool row that finished) keeps its place
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("id"), int):
                rows[row["id"]] = row
        out = list(rows.values())
        if len(lines) > COMPACT_AT:
            tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out[-COMPACT_AT // 2:]),
                           encoding="utf-8", newline="\n")
            os.replace(tmp, self.path)
        return out[-KEPT:]

    def _write(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _add(self, role: str, text: str, turn: int, **extra) -> dict:
        with self._lock:
            row = {"id": self._next, "ts": datetime.now().isoformat(timespec="seconds"), "role": role,
                   "text": text, "tool": None, "ok": None, "turn": turn, **extra}
            self._next += 1
            self.rows.append(row)
            del self.rows[:-KEPT]
            self._write(row)
        self._tell([row])
        return row

    def _update(self, row: dict, **changes) -> None:
        with self._lock:
            row.update(changes)
            self._write(row)
        self._tell([row])

    def _tell(self, rows: list[dict]) -> None:
        if self.notify is not None:
            self.notify({"rows": [dict(r) for r in rows], "busy": self.busy is not None, "turn": self.busy,
                         "stopping": self._stop.is_set()})

    # ---- what the page reads
    def engines(self) -> list[dict]:
        if self._engines and time.monotonic() - self._engines[0] < ENGINES_TTL_S:
            return self._engines[1]
        ws = self._workspace()
        rows = []
        for eid in ENGINE_ORDER:
            try:
                ok, why = self.engines_fn(eid, ws)
            except Exception as exc:  # noqa: BLE001 - one engine's probe failing leaves the others
                ok, why = False, f"{type(exc).__name__}: {exc}"
            rows.append({"id": eid, "label": LABELS[eid], "available": bool(ok), "why": why})
        self._engines = (time.monotonic(), rows)
        return rows

    def _workspace(self):
        try:
            return find_workspace(self.root)
        except WorkspaceError:
            return None

    def status(self) -> dict:
        ws = self._workspace()
        rows = self.engines()
        state = runner.read_json(self.root / runner.CHAT_STATE_FILE, {}) or {}
        try:
            budget = runner.settings_for(ws).budget_usd
        except WorkspaceError:
            budget = None
        with self._lock:
            return {"busy": self.busy is not None, "turn": self.busy, "stopping": self._stop.is_set(),
                    "engine": self.engine if self.busy is not None else default_engine(rows, ws),
                    "session_engine": state.get("engine") if state.get("session_id") else None,
                    "engines": rows, "spent_usd": round(float(state.get("cost_usd") or 0), 4), "budget_usd": budget,
                    "messages": [dict(r) for r in self.rows[-SHOWN:]]}

    # ---- a turn
    def send(self, message, engine: str | None = None, context=None) -> int:
        if not isinstance(message, str) or not message.strip():
            raise ChatError(400, "the message is empty", "chat.empty")
        if len(message) > MAX_MESSAGE:
            raise ChatError(400, f"the message is {len(message)} characters; the most is {MAX_MESSAGE}",
                            "chat.too_long", chars=len(message), max=MAX_MESSAGE)
        context = clean_context(context)
        rows = self.engines()
        ws = self._workspace()
        if engine is None:
            engine = default_engine(rows, ws)
            if engine is None:
                raise ChatError(400, "no engine can run here: " + "; ".join(f"{r['id']}: {r['why']}" for r in rows),
                                "chat.no_engine")
        row = next((r for r in rows if r["id"] == engine), None)
        if row is None:
            raise ChatError(400, f'unknown engine "{engine}": use {", ".join(ENGINE_ORDER)}', "chat.unknown_engine",
                            engine=engine)
        if not row["available"]:
            raise ChatError(400, f"the {engine} engine cannot run here: {row['why']}", "chat.engine_unavailable",
                            engine=engine, why=row["why"])
        hidden = guard.shadowed_workspace(self.root)
        if hidden is not None:
            raise ChatError(400, f"{self.root / 'workspace.json'} hides the workspace at {hidden}: move it out of "
                                 "the project first", "chat.workspace_hidden")
        with self._lock:
            if self.busy is not None:
                raise ChatError(409, f"turn {self.busy} is still running: wait for it or stop it", "busy.chat",
                                turn=self.busy)
            self.turn += 1
            turn = self.busy = self.turn
            self.engine = engine
            self._stop.clear()
            self._calls = {}
        self._add("user", message.strip(), turn, context=context, engine=engine)
        self._thread = threading.Thread(target=self._work, args=(turn, message, engine, context),
                                        name=f"reelsmith-chat-{turn}", daemon=True)
        self._thread.start()
        return turn

    def stop(self) -> bool:
        with self._lock:
            if self.busy is None:
                return False
            self._stop.set()
        self._tell([])
        return True

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """True once no turn runs (tests and shutdown)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return self.busy is None

    def _work(self, turn: int, message: str, engine: str, context: dict | None) -> None:
        self._origin = presence.set_origin(self.root, turn=turn)
        try:
            ws = self._workspace()
            settings = runner.settings_for(ws, engine=engine)
            conv = runner.Conversation(self.root, settings, ws, listener=lambda kind, data: self._heard(turn, kind,
                                                                                                         data),
                                       stop=self._stop, **self.seams)
            row = asyncio.run(conv.turn(beat_line(context) + message, context))
        except Exception as exc:  # noqa: BLE001 - the window says why the turn failed
            row = {"error": str(exc) if isinstance(exc, WorkspaceError) else f"{type(exc).__name__}: {exc}",
                   "cost_usd": 0.0}
        self._finish(turn, row)

    def _heard(self, turn: int, kind: str, data: dict) -> None:
        if kind == "say":
            self._add("assistant", data["text"], turn)
        elif kind == "call":
            row = self._add("tool", data.get("brief") or "", turn, tool=short_tool(data.get("name")))
            if data.get("id") is not None:
                self._calls[data["id"]] = row
        elif kind == "result":
            row = self._calls.pop(data.get("id"), None) if data.get("id") is not None else None
            if row is not None:
                batch = self._batch_of(turn, row["tool"]) if data["ok"] else None
                self._update(row, ok=data["ok"], **({"detail": self._masked(data["text"])} if data.get("text") else {}),
                             **({"batch": batch} if batch is not None else {}))
            elif not data["ok"]:               # a call the engine refused before it ran (an unknown tool, bad input)
                self._add("tool", "", turn, tool=short_tool(data.get("name")), ok=False,
                          detail=self._masked(data.get("text") or ""))

    def _batch_of(self, turn: int, tool: str) -> int | None:
        """The edit batch the call just made: the newest activity row of this turn and tool that names one not yet
        given to another row (the tool wrote it before its result came back, in whichever process it ran)."""
        try:
            with (self.root / ".history" / "activity.jsonl").open(encoding="utf-8", errors="replace") as f:
                tail = deque(f, maxlen=40)
        except OSError:
            return None
        for line in reversed(tail):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            n = row.get("batch") if isinstance(row, dict) else None
            if (isinstance(n, int) and row.get("turn") == turn and row.get("tool") == tool
                    and (turn, n) not in self._claimed):
                self._claimed.add((turn, n))
                return n
        return None

    def _masked(self, text: str) -> str:
        from ..providers import config
        try:
            return config.context(self.root).redact(text)
        except Exception:  # noqa: BLE001 - a workspace whose keys cannot be read: the shape-based masking still runs
            return config.redact(text)

    def _finish(self, turn: int, row: dict) -> None:
        stopped = row.get("aborted") == runner.STOPPED
        for open_row in list(self._calls.values()):         # calls the turn left without an answer
            self._update(open_row, ok=not (stopped or row.get("error") or row.get("aborted")),
                         **({"detail": "stopped"} if stopped else {}))
        self._calls = {}
        cost = round(float(row.get("cost_usd") or 0), 4)
        spent, budget = row.get("spent_usd"), row.get("budget_usd")
        note = {"cost_usd": cost, "spent_usd": spent, "budget_usd": budget}
        params: dict = {"cost_usd": cost}
        if row.get("refused") == "budget":
            kind, params = "budget", {"budget_usd": budget, "spent_usd": spent}
            text = (f"The chat's ${budget:.2f} budget is used up (${spent:.2f} spent). Raise runner.budget_usd in "
                    "workspace.json to continue.")
        elif stopped:
            kind, text = "stopped", f"The request was stopped. Cost of this turn: ${cost:.2f}."
        elif row.get("error"):
            kind, params = "error", {"error": self._masked(row["error"])}
            text = f"The request failed: {params['error']}"
        elif row.get("aborted"):
            kind, params = "aborted", {"reason": str(row["aborted"]), "cost_usd": cost}
            text = f"The request ended early: {row['aborted']}. Cost of this turn: ${cost:.2f}."
        else:
            kind, text = "end", f"The request is complete. Cost of this turn: ${cost:.2f}."
        if row.get("budget_used_up") and kind != "budget":
            text += (f" The ${budget:.2f} budget is now used up. Raise runner.budget_usd in workspace.json to "
                     "continue.")
            note["budget_used_up"] = params["budget_used_up"] = True
            params["budget_usd"] = budget
        with self._lock:
            self.busy = None
            self.engine = None
            self._stop.clear()
        presence.clear_origin(self.root, self._origin)
        self._add("note", text, turn, kind=kind, code=f"chat.{kind}", params=params, **note)
