"""What a running process tells a watch window: the tool call working on a project right now (.history/running.json)
and the window open on it (build/watch/window.json); and opening that window by itself when the user asked for it.
Standard library only: the tools import this on every call."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

SERVED = ("assets", "voice", "out", "build")          # the only project folders the window is handed
RUNNING = Path(".history") / "running.json"
ORIGIN = Path(".history") / "origin.json"
WINDOW = Path("build") / "watch" / "window.json"
RUNNING_STALE_S = 3 * 3600          # a call this old has died without saying so
WRITE_EVERY_S = 0.25                # progress alone is written at most this often
WATCH_ENV = "REELSMITH_WATCH"
OPENED_LINE = "(a window showing this project was opened for the user: reelsmith watch)"
ALLOW_UNDER_PYTEST = False          # tests that open a window on purpose lift this
_DECIDED: set[str] = set()          # projects this process already considered opening a window on
_DECIDED_LOCK = threading.Lock()


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) would terminate the process on Windows
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5                 # access denied: it exists
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ the call at work
class Running:
    """One tool call's running.json: written when it starts, kept up to date by `update`, removed when it ends.
    Never raises: the file is for watching, the call matters more."""

    def __init__(self, root: Path, tool: str):
        self.path = Path(root) / RUNNING
        self.row = {"tool": tool, "since": datetime.now().isoformat(timespec="milliseconds"), "pid": os.getpid(),
                    "stage": None, "progress": None}
        self._written = 0.0
        self._lock = threading.Lock()

    def start(self) -> Running:
        self._save()
        return self

    def update(self, stage: str | None = None, progress: float | None = None) -> None:
        """A new stage is written at once; progress within a stage at most every WRITE_EVERY_S."""
        progress = None if progress is None else round(min(1.0, max(0.0, float(progress))), 3)
        with self._lock:
            moved = stage != self.row["stage"]
            if not moved and progress == self.row["progress"]:
                return
            self.row.update(stage=stage, progress=progress)
            if not moved and time.monotonic() - self._written < WRITE_EVERY_S:
                return
        self._save()

    def end(self) -> None:
        mine = {k: self.row[k] for k in ("tool", "since", "pid")}
        try:
            row = _read(self.path) or {}
            if {k: row.get(k) for k in mine} == mine:       # a later call's file stays
                self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def _save(self) -> None:
        with self._lock:
            row = dict(self.row)
            self._written = time.monotonic()
        try:
            _write(self.path, row)
        except OSError:
            pass


def running(root: Path, now: float | None = None) -> dict | None:
    """{tool, since, seconds, stage, progress} of the call working on the project, or None: no file, a file whose
    process is gone, or one older than RUNNING_STALE_S."""
    row = _read(Path(root) / RUNNING)
    if not row or not pid_alive(row.get("pid")):
        return None
    try:
        seconds = (now or time.time()) - datetime.fromisoformat(str(row.get("since"))).timestamp()
    except ValueError:
        return None
    if seconds > RUNNING_STALE_S:
        return None
    progress = row.get("progress")
    return {"tool": row.get("tool"), "since": row.get("since"), "seconds": round(max(0.0, seconds), 1),
            "stage": row.get("stage"), "progress": progress if isinstance(progress, (int, float)) else None}


# ------------------------------------------------------------------ who asked: a chat turn or a window action
def set_origin(root: Path, **what) -> dict:
    """Mark the calls on the project from now on as asked by `what` ({"turn": n} or {"action": name}) until
    clear_origin; the activity log copies it onto their rows. Tools in another process read it the same way."""
    row = {"pid": os.getpid(), "since": datetime.now().isoformat(timespec="milliseconds"), **what}
    try:
        _write(Path(root) / ORIGIN, row)
    except OSError:
        pass
    return row


def clear_origin(root: Path, row: dict) -> None:
    path = Path(root) / ORIGIN
    try:
        if _read(path) == row:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def origin(root: Path) -> dict | None:
    row = _read(Path(root) / ORIGIN)
    return row if row and pid_alive(row.get("pid")) else None


# ------------------------------------------------------------------ the window on a project
def window_of(root: Path) -> dict | None:
    """{pid, url} of a live window on the project; None when there is none or its process is gone."""
    row = _read(Path(root) / WINDOW)
    return row if row and pid_alive(row.get("pid")) else None


def record_window(root: Path, url: str) -> None:
    _write(Path(root) / WINDOW, {"pid": os.getpid(), "url": url})


def forget_window(root: Path) -> None:
    path = Path(root) / WINDOW
    if (_read(path) or {}).get("pid") == os.getpid():
        path.unlink(missing_ok=True)


# ------------------------------------------------------------------ opening it by itself
def wanted(root: Path) -> bool:
    """REELSMITH_WATCH=1, or "watch": true in the workspace's workspace.json."""
    if os.environ.get(WATCH_ENV, "").strip() == "1":
        return True
    from ..workspace import WorkspaceError, find_workspace
    try:
        ws = find_workspace(root)
    except WorkspaceError:
        return False
    return bool(ws and ws.config.get("watch") is True)


def maybe_open(root: Path) -> bool:
    """Start `reelsmith watch <root>` as a process of its own, once per project per process, when the user asked for
    it, the desktop window can open and none is open on the project. True when it was started; never waits."""
    if "pytest" in sys.modules and not ALLOW_UNDER_PYTEST:
        return False
    key = os.path.normcase(str(root))
    with _DECIDED_LOCK:
        if key in _DECIDED:
            return False
        _DECIDED.add(key)
    try:
        from . import window
        if not wanted(root) or not window.available() or window_of(root):
            return False
        launch(root)
    except Exception:  # noqa: BLE001 - the window is a courtesy; the tool's result matters more
        return False
    return True


def launch(root: Path) -> None:
    cmd = [sys.executable, "-c", "import sys; from reelsmith.cli import main; sys.exit(main())", "watch", str(root)]
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
             "cwd": str(Path(__file__).resolve().parents[2]), "close_fds": True}
    if os.name != "nt":
        subprocess.Popen(cmd, start_new_session=True, **quiet)
        return
    detached = 0x00000008 | 0x00000200                  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        # out of the agent's job object, so the window outlives a tool call's process tree being killed
        subprocess.Popen(cmd, creationflags=detached | 0x01000000, **quiet)     # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(cmd, creationflags=detached, **quiet)
