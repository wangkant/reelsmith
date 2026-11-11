"""The desktop window a terminal session opens on its own watch server, in a process of its own (the window owns
its thread until it is closed): python -m reelsmith.term.window URL TITLE."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def detached() -> dict:
    """Popen options that keep the terminal's Ctrl+C away from the child; the session terminates it on quit."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def launch(url: str, title: str) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "reelsmith.term.window", url, title]
    return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            cwd=str(Path(__file__).resolve().parents[2]), close_fds=True, **detached())


if __name__ == "__main__":
    from reelsmith.watch.window import open_window
    open_window(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "reelsmith")
