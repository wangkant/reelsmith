"""`reelsmith watch`: a local editor window over a project (or a workspace of projects) while an agent edits it, with
a chat that asks an agent for changes. Standard library only; binds 127.0.0.1. Reading needs a same-origin (or
address-bar) request; a POST also needs the server's token, which only its own page can read."""
from __future__ import annotations

import argparse
import array
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .. import document as D
from .. import media
from .. import render as R
from .. import resolve as RS
from .. import timeexpr as T
from .. import tools as TL
from ..workspace import PROJECT_FILE, WORKSPACE_FILE, Workspace, WorkspaceError, find_workspace, project_file
from . import app as A
from . import chat as C
from . import presence as P
from . import state as S

HOST = "127.0.0.1"
STATIC = Path(__file__).resolve().parent / "static"
PLACEHOLDER = b"<!doctype html><meta charset=utf-8><title>reelsmith watch</title><p>reelsmith watch: the window is " \
              b"not built yet; <a href=api/state>api/state</a> works.</p>"
POLL_S = 0.5
RUNNING_PUSH_S = 1.0                # progress alone is announced at most this often
KEEPALIVE_S = 15
STILL_W = 960
STILL_TIMEOUT_S = 180
KEEP_CACHED = 400                   # files per cache folder under build/watch/
WAVE_RATE = 8000
WAVE_PER_S = 100
WAVE_MAX = 4000
PLAYER_BUILD_S = 600
PLAYER_KEEP_S = 1800                # another window may still serve an older build this long
CHUNK = 256 * 1024
MAX_BODY = 128 * 1024
MAX_T = 24 * 3600.0
CHAT_EVENTS = 256                   # chat payloads an events stream can catch up on
PUSHED_EVENTS = 64                  # frames and action payloads an events stream can catch up on
FRAME_BATCH = 12                    # frames one renderer run may take
FRAME_QUEUE = 240
ACTIONS = {"render": TL.render, "check": TL.check, "undo": TL.undo, "redo": TL.redo}
TOKEN_HEADER = "X-Reelsmith-Token"
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
         ".ttf": "font/ttf", ".otf": "font/otf", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
         ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".vtt": "text/vtt; charset=utf-8", ".srt": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
         ".map": "application/json"}
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
POSTER_H = 360
PASSIVE = ("/api/frame", "/api/still", "/api/thumb", "/api/wave", "/favicon.ico", "/api/upload")
RENDER_TOOLS = ("render", "preview", "review")      # the tools that take the renderer (render._NODE_LOCK)
APP_PUSH_S = 0.25                   # the application's films event at most this often
APP_PAGES = {"/new": "new.html", "/library": "library.html", "/settings": "settings.html"}
ENGINES_TTL_S = 15.0
UPLOAD_CHUNK = 1024 * 1024
HOME_SCAN_S = 2.0                   # projects no page has opened are looked at this often, while a home is open
# a project's last change: the latest of these files' times
LAST_CHANGE = ("project.json", ".history/activity.jsonl", ".history/log.jsonl", "out/film.mp4", "build/report.json",
               "voice/voice.json", "build/chat_state.json")


class HTTPError(Exception):
    def __init__(self, code: int, body: dict):
        super().__init__(body.get("error"))
        self.code, self.body = code, body


def refused(status: int, code: str, **params) -> HTTPError:
    """An error whose reason is one of state.TEXTS: {"error" (English), "code", "params"}."""
    return HTTPError(status, {"error": S.say(code, **params)["text"], "code": code, "params": params})


def open_folder(folder: Path) -> None:
    """The system's file manager on `folder`."""
    if sys.platform.startswith("win"):
        os.startfile(str(folder))                   # noqa: S606 - a folder of the project, never a program
        return
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], **quiet)


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def fenced(root: Path, rel: str) -> Path | None:
    """A file under one of the served project folders; anything else (.., absolute, a link leading out) is None."""
    rel = unquote(rel).replace("\\", "/")
    parts = rel.split("/")
    if (not rel or parts[0] not in S.SERVED or any(p in ("", ".", "..") for p in parts) or ":" in rel
            or "\x00" in rel):
        return None
    full = project_file(root, rel)
    if full is None or not inside(full, (root / parts[0]).resolve()) or not full.is_file():
        return None
    return full


def _stamp_s(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def render_busy(root: Path) -> bool:
    """A render, preview or draft of this project holds its lock (render.project_lock) in some process. Probing
    takes the lock for an instant only when nobody holds it."""
    lock = root / "build" / "render.lock"
    if not lock.is_file():
        return False
    try:
        fh = open(lock, "a+b")
    except OSError:
        return False
    with fh:
        if R._try_os_lock(fh):
            R._os_unlock(fh)
            return False
        return True


def renderer_held() -> bool:
    """Some thread of this process draws with the renderer now (one job at a time)."""
    if R._NODE_LOCK.acquire(blocking=False):
        R._NODE_LOCK.release()
        return False
    return True


def waits_for_renderer(run: dict | None) -> bool:
    """A renderer call with no stage yet while the renderer is held elsewhere: it waits its turn."""
    return bool(run and run.get("tool") in RENDER_TOOLS and not run.get("stage") and renderer_held())


def _prune(folder: Path, keep: int = KEEP_CACHED) -> None:
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def card_facts(st: dict, base: str) -> dict:
    """What a home card shows of a project's state."""
    poster = None
    canvas = st["canvas"] or {}
    # a project with nothing on it yet has no length: a film waiting for its first clip, not a broken one
    empty = not st["tracks"] and (st["valid"] or "has no length" in (st["error"] or ""))
    if st["valid"] and st["duration"] and not empty:
        delivered = st["render"]["delivered"] or {}
        length = delivered.get("duration") if delivered.get("matches_cut") else None
        t = round((length or st["duration"]) * 0.3, 2)     # past the opening fade, inside the first beat or two
        poster = f"{base}/api/frame?t={t}&h={POSTER_H}&v={st['revision'][:12]}"
    return {"title": st["project"]["title"], "duration": st["duration"], "valid": st["valid"], "empty": empty,
            "canvas": {"width": canvas.get("width"), "height": canvas.get("height")} if canvas else None,
            "result": {"state": st["result"]["state"], "accepted": st["result"]["accepted"]}, "poster": poster,
            "revision": st["revision"], "errors": (st.get("summary") or {}).get("errors") or 0}


def opens(path: str) -> bool:
    """A request that means someone looks at the project (its page, state, events, chat); a poster, a still, a
    media file or a static file does not."""
    return not (path in PASSIVE or path.startswith(("/project/", "/player/", "/static/")))


def _ffmpeg(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise HTTPError(503, {"error": "ffmpeg is not on PATH"})
    return subprocess.run([exe, "-hide_banner", "-v", "error", *args], capture_output=True, timeout=timeout,
                          creationflags=media.NO_WINDOW)


# ------------------------------------------------------------------ the live player bundle
class Player:
    """renderer/scripts/player.mjs's bundle, built in the background into <cache>/<stamp>/ and rebuilt when the
    renderer's sources or the workspace's components change; the last good build is served meanwhile."""

    def __init__(self, cache: Path, library: Path | None):
        self.cache, self.library = cache, library
        self.script = R.RENDERER / "scripts" / "player.mjs"
        self._lock = threading.Lock()
        self._checked = 0.0
        self._stamp = ""
        self.ready: Path | None = None
        self.building = False
        self.error: str | None = None

    def stamp(self) -> str:
        h = hashlib.sha1()
        for folder in (R.RENDERER / "src", self.library):
            if folder is None or not folder.is_dir():
                continue
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    st = p.stat()
                    h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        if self.script.is_file():
            h.update(str(self.script.stat().st_mtime_ns).encode())
        return h.hexdigest()[:16]

    def version(self) -> str:
        """The stamp of the renderer and components the window currently draws with."""
        self.current()
        return self._stamp

    def current(self) -> Path | None:
        """The folder to serve from (starting a build when the sources moved), or None while there is none."""
        with self._lock:
            now = time.monotonic()
            if now - self._checked > 2 or not self._stamp:
                self._checked, self._stamp = now, self.stamp()
                built = self.cache / self._stamp
                if (built / "index.html").is_file():
                    self.ready, self.error = built, None
                elif not self.building and self.script.is_file():
                    self.building, self.error = True, None
                    threading.Thread(target=self._build, args=(self._stamp,), daemon=True).start()
                elif not self.script.is_file():
                    self.error = f"{self.script} is missing"
            return self.ready

    def _build(self, stamp: str) -> None:
        out = self.cache / stamp
        try:
            node = shutil.which("node")
            if not node:
                raise RuntimeError("node is not on PATH")
            cmd = [node, str(self.script), str(out), "--library", str(self.library or "")]
            rc, stdout, stderr, timed = media.run_tree(cmd, cwd=R.RENDERER, timeout=PLAYER_BUILD_S)
            res = R._last_json(stdout) or {}
            if timed or not res.get("ok") or not (out / "index.html").is_file():
                why = res.get("error") or ("timed out" if timed else media.tail(stdout + "\n" + stderr, 15, 1500))
                raise RuntimeError(f"the player did not build: {why}")
            with self._lock:
                self.ready, self.error = out, None
            self._tidy(out)
        except Exception as exc:  # noqa: BLE001 - shown in the 503 and the window falls back to stills
            with self._lock:
                self.error = str(exc)
                self._checked = time.monotonic() + 30       # wait a little before trying again
        finally:
            self.building = False

    def _tidy(self, keep: Path) -> None:
        """The cache is shared by every window on the workspace: an older build goes only once another window has
        had ample time to move to a newer one (it looks every 2 s), and another process's build in progress
        (<stamp>.build-*) only once it has long outlived its timeout."""
        now = time.time()
        for old in self.cache.iterdir():
            if not old.is_dir() or old == keep:
                continue
            limit = 2 * PLAYER_BUILD_S if ".build-" in old.name else PLAYER_KEEP_S
            try:
                age = now - old.stat().st_mtime
            except OSError:
                continue
            if age > limit:
                shutil.rmtree(old, ignore_errors=True)


# ------------------------------------------------------------------ one project
class Site:
    """One project the server shows. `opened`: a page or the terminal opened it (only those are polled); a site
    made for a poster alone is not. Its chat is made on first use."""

    def __init__(self, root: Path, base: str, player: Player, chat_options: dict | None = None, url: str = "",
                 opened: bool = True):
        self.root, self.base, self.player = root, base, player
        self.url = url                              # where this server shows the project, for presence
        self.opened = opened
        self.gone = False                           # moved to the trash: its workers stop
        self._owned = False                         # this server recorded itself as the project's window
        self.cache = S.StateCache(root, base)
        self.changed = threading.Condition()
        self.revision: str | None = None
        self._sig: tuple | None = None
        self.running: dict | None = None            # as last announced
        self.running_seq = 0                        # moves whenever the running call is announced
        self.waiting = False                        # the running call waits for the renderer
        self._running_at = 0.0
        self.chat_seq = 0                           # moves with every chat payload
        self.chat_events: deque = deque(maxlen=CHAT_EVENTS)
        self._chat_options = chat_options or {}
        self._chat: C.Chat | None = None
        self._chat_lock = threading.Lock()
        self._still = threading.Lock()
        self._media = threading.BoundedSemaphore(2)
        self._resolved: tuple[tuple, bytes, str] | None = None
        self._resolved_lock = threading.Lock()
        self.watch_dir = root / "build" / "watch"
        self.pushed_seq = 0                         # moves with every frames or action payload
        self.pushed: deque = deque(maxlen=PUSHED_EVENTS)
        self._frames_lock = threading.Lock()
        self._frame_queue: list[dict] = []          # {"key", "frame", "h", "t"} waiting for the renderer
        self._frames_out: set[tuple] = set()        # (key, frame, h) the renderer is drawing now
        self._frame_thread: threading.Thread | None = None
        self._frame_failed: dict[tuple, str] = {}   # (still key, frame) -> why it could not be rendered
        self._action_lock = threading.Lock()
        self.action: dict | None = None             # the window's action at work: {"action", "since"}
        self.last_action: dict | None = None
        self.on_chat = None                         # the workspace server hears every chat payload

    @property
    def chat(self) -> C.Chat:
        with self._chat_lock:
            if self._chat is None:
                self._chat = C.Chat(self.root, self.chat_changed, **self._chat_options)
            return self._chat

    @property
    def chat_busy(self) -> int | None:
        """The running chat turn, without making a chat for a project nobody talked to."""
        chat = self._chat
        return chat.busy if chat is not None else None

    # ---- one window per project, across processes
    def claim(self) -> None:
        """Refuse a change while another process's window holds the project; nobody holding it, this server does
        from now on (until it stops)."""
        other, recorded = P.claim_window(self.root, self.url or f"{self.base}/")
        if other is not None:
            raise refused(409, "owner.elsewhere", url=str(other.get("url") or ""), pid=other.get("pid"))
        self._owned = self._owned or recorded

    def release(self) -> None:
        if self._owned:
            try:
                P.forget_window(self.root)
            except OSError:
                pass
            self._owned = False

    def poll(self) -> None:
        self.poll_running()
        sig = S.signature(self.root)
        if sig == self._sig:
            return
        self._sig = sig
        rev = self.cache.get()["revision"]
        if rev != self.revision:
            with self.changed:
                self.revision = rev
                self.changed.notify_all()

    def poll_running(self) -> None:
        """Announce a call that starts, moves to another stage or ends at once; its progress alone at most every
        RUNNING_PUSH_S."""
        now, was = P.running(self.root), self.running
        waiting = waits_for_renderer(now)
        key = lambda r: r and (r["tool"], r["since"], r["stage"])  # noqa: E731
        if key(now) == key(was) and waiting == self.waiting and (
                now is None or now["progress"] == was["progress"]
                or time.monotonic() - self._running_at < RUNNING_PUSH_S):
            return
        with self.changed:
            self.running, self._running_at, self.waiting = now, time.monotonic(), waiting
            self.running_seq += 1
            self.changed.notify_all()

    def chat_changed(self, payload: dict) -> None:
        with self.changed:
            self.chat_seq += 1
            self.chat_events.append((self.chat_seq, payload))
            self.changed.notify_all()
        if self.on_chat is not None:
            self.on_chat(self, payload)

    @property
    def queued(self) -> int | None:
        """The chat turn's place in the workspace's queue while it waits for a free place."""
        chat = self._chat
        return chat.queued if chat is not None else None

    def chat_since(self, seq: int) -> tuple[list[dict], bool]:
        """(payloads after seq, whether some were already dropped); call with self.changed held."""
        pending = [p for s, p in self.chat_events if s > seq]
        lost = self.chat_seq - seq > len(pending)
        return pending, lost

    def pushed_since(self, seq: int) -> tuple[list[tuple], bool]:
        """([(name, payload)] after seq, whether some were already dropped); call with self.changed held."""
        pending = [(n, p) for s, n, p in self.pushed if s > seq]
        return pending, self.pushed_seq - seq > len(pending)

    def push(self, name: str, payload: dict) -> None:
        """A "frames" or "action" event for every open events stream."""
        with self.changed:
            self.pushed_seq += 1
            self.pushed.append((self.pushed_seq, name, payload))
            self.changed.notify_all()

    def state(self) -> dict:
        st = self.cache.get()
        if st["revision"] != self.revision:
            with self.changed:
                self.revision = st["revision"]
                self.changed.notify_all()
        run = P.running(self.root)
        running = S.running_view(run, self.running_by(), waits_for_renderer(run))
        pos = self.queued
        queue = {"position": pos, **S.say("queue.waiting", position=pos)} if pos is not None else None
        return {**st, "running": running, "can": self.can(st), "action": self.action,
                "last_action": self.last_action, "queue": queue}

    def running_by(self) -> str:
        return "window" if self.action else "chat" if self.chat_busy is not None else "agent"

    def rendering(self) -> bool:
        return render_busy(self.root) or bool(self.action and self.action["action"] == "render")

    def can(self, st: dict) -> dict:
        """{"render", "check", "undo", "redo", "stop": bool, "why": {name: {"code", "params", "text"}}}: the
        actions the window offers, and the reason of each one that cannot run now."""
        busy = "busy.action" if self.action else "busy.chat" if self.chat_busy is not None else None
        reasons = {
            "render": busy or ("busy.render" if self.rendering() else None)
            or ("project.invalid" if not st["valid"] else None)
            or ("render.current" if st["result"]["state"] == "current" else None),
            "check": busy,
            "undo": busy or (None if st["can_undo"] else "undo.empty"),
            "redo": busy or (None if st["can_redo"] else "redo.empty"),
            "stop": ("stop.pending" if self.chat.stopping else None) if self.chat_busy is not None else (
                "stop.unsupported" if self.action else "stop.idle"),
        }
        out: dict = {name: why is None for name, why in reasons.items()}
        out["why"] = {name: S.say(why) for name, why in reasons.items() if why is not None}
        return out

    def send_chat(self, message, engine: str | None, context) -> int:
        """A chat turn, never beside an action (the action lock makes the two checks one)."""
        with self._action_lock:
            if self.action:
                raise refused(409, "busy.action")
            self.claim()
            try:
                return self.chat.send(message, engine, context)
            except C.ChatError as exc:
                raise HTTPError(exc.code, {"error": str(exc), "code": exc.key, "params": exc.params}) from None

    # ---- actions without typing
    def act(self, name) -> tuple[int, dict]:
        if name == "stop":                      # stopping this server's own turn is never refused
            if self._chat is not None and self._chat.stop():
                return 200, {"stopped": True, "what": "chat"}
            why = "stop.unsupported" if self.action else "stop.idle"
            return 200, {"stopped": False, "code": why, "params": {}, "error": S.TEXTS[why]}
        if name not in ACTIONS:
            raise refused(400, "action.unknown", action=str(name)[:40])
        with self._action_lock:
            self.claim()
            why = self.can(self.cache.get())["why"].get(name)
            if why is not None:
                raise refused(409, why["code"])
            self.action = {"action": name, "since": S.datetime.now().isoformat(timespec="seconds")}
            started = dict(self.action, state="running")
        threading.Thread(target=self._act, args=(name,), name=f"reelsmith-action-{name}", daemon=True).start()
        self.push("action", started)
        return 202, {"action": name, "started": True}

    def _act(self, name: str) -> None:
        mark = P.set_origin(self.root, action=name)
        try:
            result = ACTIONS[name](str(self.root))
            ok, text = bool(result.ok), str(result)
        except Exception as exc:  # noqa: BLE001 - tools never raise; this is the last word if one does
            ok, text = False, f"{type(exc).__name__}: {exc}"
        finally:
            P.clear_origin(self.root, mark)
        said = S.say(f"action.{name}.{'ok' if ok else 'failed'}")
        done = {"action": name, "state": "done" if ok else "failed", "ok": ok, "code": said["code"], "params": {},
                "text": said["text"], "detail": S.tidier(self.root)(text)[:2000],
                "at": S.datetime.now().isoformat(timespec="seconds")}
        with self._action_lock:
            self.action, self.last_action = None, done
        self.push("action", done)

    def wait_action(self, timeout: float = 30) -> bool:
        """True once no action runs (tests and shutdown)."""
        until = time.monotonic() + timeout
        while self.action and time.monotonic() < until:
            time.sleep(0.05)
        return self.action is None

    def accept(self) -> dict:
        self.claim()
        st = self.cache.get()
        if st["result"]["state"] != "current":
            raise refused(409, "accept.not_current")
        row = {"at": S.datetime.now().isoformat(timespec="seconds"), "cut": st["cut"]}
        out = self.root / "out" / "accepted.json"
        tmp = out.with_name(f".accepted.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(row), encoding="utf-8")
        os.replace(tmp, out)
        return {"accepted": {"at": row["at"]}}

    def reveal(self) -> dict:
        film = self.root / "out" / "film.mp4"
        if not film.is_file():
            raise refused(404, "reveal.no_film")
        open_folder(film.parent)
        return {"revealed": True, "folder": "out"}

    # ---- frames of the film as it stands
    def frame(self, t: float, h: int | None, src: str = "auto", w: int | None = None) -> tuple[Path | None, str]:
        """(the JPEG, "film" or "cut"); the JPEG is None while the engine has yet to render it (it is queued). The
        size is a height, or a width read as the height of the canvas's shape."""
        if src not in ("auto", "film", "cut"):
            raise HTTPError(400, {"error": "src must be auto, film or cut"})
        st = self.cache.get()
        if not st["valid"]:
            raise HTTPError(503, {"error": st["error"], "code": "project.invalid", "params": {}})
        canvas = st["canvas"]
        if h is None:
            h = round(w * canvas["height"] / canvas["width"]) if w is not None else 180
        h = int(min(max(32, h), canvas["height"]))
        frame = min(max(0, T.to_frame(min(max(0.0, t), st["duration"]), canvas["fps"])), st["frames"] - 1)
        delivered = st["render"]["delivered"]
        if src == "film" or (src == "auto" and delivered and delivered["matches_cut"] is True):
            if not delivered:
                raise refused(404, "reveal.no_film")
            return self.film_frame(frame / canvas["fps"], frame, h), "film"
        _, key = self.resolved()
        skey = self.still_key(st, key)
        out = self._cached("frames", f"cut_{skey}_{frame}_{h}.jpg")
        if out.is_file():
            return out, "cut"
        failed = self._frame_failed.get((skey, frame))
        if failed:
            raise refused(503, "frame.failed", error=failed)
        self.queue_frame({"key": skey, "frame": frame, "h": h, "t": t})
        return None, "cut"

    def film_frame(self, sec: float, frame: int, h: int) -> Path:
        film = self.root / "out" / "film.mp4"
        stamp = hashlib.sha1(f"{film}|{S._stamp(film)}".encode()).hexdigest()[:10]
        out = self._cached("frames", f"film_{stamp}_{frame}_{h}.jpg")
        if out.is_file():
            return out
        with self._media:
            for at in (sec, max(0.0, sec - 0.1)):          # the very last frame can sit past the stream's end
                _ffmpeg(["-y", "-ss", f"{at:.3f}", "-i", str(film), "-frames:v", "1", "-vf", f"scale=-2:{h}",
                         "-q:v", "4", str(out)])
                if out.is_file():
                    _prune(out.parent)
                    return out
        raise HTTPError(404, {"error": f"no picture in the delivered film at {sec:g} s"})

    def queue_frame(self, item: dict) -> None:
        with self._frames_lock:
            ident = (item["key"], item["frame"], item["h"])
            if ident not in self._frames_out and not any((q["key"], q["frame"], q["h"]) == ident
                                                         for q in self._frame_queue):
                self._frame_queue.append(item)
                del self._frame_queue[:-FRAME_QUEUE]
            if self._frame_thread is None:
                self._frame_thread = threading.Thread(target=self._frame_work, name="reelsmith-frames", daemon=True)
                self._frame_thread.start()

    def _frame_work(self) -> None:
        """Renders the queue, at most FRAME_BATCH frames per renderer run and never while a render or preview
        holds the project; frames of a cut that has changed since are dropped (the page asks again)."""
        while True:
            with self._frames_lock:
                if not self._frame_queue or self.gone:
                    self._frame_queue.clear()
                    self._frame_thread = None
                    return
            if self.rendering():
                time.sleep(1.0)
                continue
            try:
                st = self.cache.get()
                body, key = self.resolved()
                skey = self.still_key(st, key)
            except HTTPError as exc:
                with self._frames_lock:
                    failed, self._frame_queue = self._frame_queue, []
                self.push("frames", {"ready": [], "failed": [self._frame_row(q) for q in failed], "stale": [],
                                     "error": exc.body.get("error")})
                continue
            with self._frames_lock:
                todo = [q for q in self._frame_queue if q["key"] == skey]
                stale = [self._frame_row(q) for q in self._frame_queue if q["key"] != skey]
                # asked again between its check and a batch that has since drawn it
                drawn = [q for q in todo if self._cut_frame(q).is_file()]
                todo = [q for q in todo if q not in drawn]
                frames = list(dict.fromkeys(q["frame"] for q in todo))[:FRAME_BATCH]
                batch = [q for q in todo if q["frame"] in frames]
                self._frame_queue = [q for q in todo if q["frame"] not in frames]
                self._frames_out = {(q["key"], q["frame"], q["h"]) for q in batch}
            if stale or drawn:                  # stale: the cut changed while they waited, the page asks again
                self.push("frames", {"ready": [self._frame_row(q) for q in drawn], "failed": [], "stale": stale,
                                     "error": None})
            if batch:
                done = self._render_frames(body, skey, frames, batch)
                with self._frames_lock:
                    self._frames_out = set()
                    if done is None:            # a render took the project meanwhile: wait for it
                        self._frame_queue[:0] = batch
                if done is None:
                    time.sleep(1.0)
                else:
                    self.push("frames", done)

    def _cut_frame(self, q: dict) -> Path:
        return self._cached("frames", f"cut_{q['key']}_{q['frame']}_{q['h']}.jpg")

    def _frame_row(self, q: dict) -> dict:
        return {"t": q["t"], "h": q["h"], "frame": q["frame"],
                "url": f"{self.base}/api/frame?t={q['t']:g}&h={q['h']}"}

    def _render_frames(self, body: bytes, skey: str, frames: list[int], batch: list[dict]) -> dict | None:
        """The frames event for the batch; None, rendering nothing, when a render holds the project by now."""
        ready, failed, error = [], [], None
        with self._still:                       # one renderer at a time, /api/still included
            if self.rendering() or self.gone or not self.root.is_dir():
                return None
            work = self.watch_dir / "frames-work"
            try:
                shutil.rmtree(work, ignore_errors=True)
                work.mkdir(parents=True)
                src = self.watch_dir / "resolved.frames.json"
                src.write_bytes(body)
                res = R.run_node("stills", src, self.root, work, frames, timeout=STILL_TIMEOUT_S)
                pngs = {int(s["frame"]): Path(s["png"]) for s in res.get("stills") or []} if res.get("ok") else {}
                if not res.get("ok"):
                    error = R.failure_text(res).splitlines()[0]
                for q in batch:
                    png = pngs.get(q["frame"])
                    out = self._cut_frame(q)
                    if png is not None and png.is_file():
                        _ffmpeg(["-y", "-i", str(png), "-vf", f"scale=-2:{q['h']}", "-q:v", "4", str(out)])
                    if out.is_file():
                        ready.append(self._frame_row(q))
                    else:
                        self._frame_failed[(skey, q["frame"])] = error or "no still was written"
                        failed.append(self._frame_row(q))
                _prune(self.watch_dir / "frames")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        if len(self._frame_failed) > 1000:
            self._frame_failed.clear()
        return {"ready": ready, "failed": failed, "stale": [], "error": error}

    def resolved(self) -> tuple[bytes, str]:
        """The film exactly as render hands it to render.mjs, and its digest (the stills' cache key)."""
        with self._resolved_lock:
            sig = S.signature(self.root)
            if self._resolved is None or self._resolved[0] != sig:
                try:
                    data = RS._Resolver(self.root).run()
                except Exception as exc:  # noqa: BLE001 - the window says why
                    raise HTTPError(503, {"error": f"the project does not resolve: {S._error_text(exc)}"}) from None
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self._resolved = (sig, body, hashlib.sha1(body).hexdigest()[:16])
            return self._resolved[1], self._resolved[2]

    def asset(self, aid: str, kinds: tuple) -> tuple[Path, dict]:
        st = self.cache.get()
        row = next((a for a in st["assets"] if a["id"] == aid), None)
        if row is None or row["kind"] not in kinds:
            raise HTTPError(404, {"error": f"no {' or '.join(kinds)} asset {aid!r}"})
        path = fenced(self.root, row["path"])
        if path is None:
            raise HTTPError(404, {"error": f"asset {aid} has no file the window may read"})
        return path, row

    def _cached(self, sub: str, key: str) -> Path:
        if self.gone or not self.root.is_dir():     # moved to the trash: never leave an empty folder behind
            raise refused(404, "film.unknown", name=self.root.name)
        folder = self.watch_dir / sub
        folder.mkdir(parents=True, exist_ok=True)
        return folder / key

    def still_key(self, st: dict, film_key: str) -> str:
        """The film as resolved, the renderer and components that draw it, and the files it shows: an edit to a
        component or an asset replaced in place makes a new still."""
        h = hashlib.sha1(f"{film_key}|{self.player.version()}".encode())
        rels = [a["path"] for a in st["assets"]] + ([st["voice"]["url"].split("/project/", 1)[-1]]
                                                     if st.get("voice") and st["voice"].get("url") else [])
        for rel in rels:
            path = project_file(self.root, rel)
            h.update(f"|{rel}|{S._stamp(path) if path is not None else None}".encode())
        return h.hexdigest()[:16]

    def still(self, t: float, w: int) -> Path:
        st = self.cache.get()
        if not st["valid"]:
            raise HTTPError(503, {"error": st["error"]})
        fps, frames = st["canvas"]["fps"], st["frames"]
        t = min(max(0.0, t), st["duration"] or 0.0)
        frame = min(max(0, T.to_frame(t, fps)), frames - 1)
        w = min(max(64, w), st["canvas"]["width"])
        body, key = self.resolved()
        out = self._cached("stills", f"{self.still_key(st, key)}_{frame}_{w}.jpg")
        if out.is_file():
            return out
        if render_busy(self.root):
            raise HTTPError(202, {"error": "a render of this project is running; stills wait for it", "busy": True,
                                  "pending": True})
        if not self._still.acquire(blocking=False):
            raise HTTPError(202, {"error": "the renderer is busy with another still", "busy": True, "pending": True})
        try:
            work = self.watch_dir / "still"
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            src = self.watch_dir / "resolved.still.json"
            src.write_bytes(body)
            res = R.run_node("stills", src, self.root, work, [frame], timeout=STILL_TIMEOUT_S)
            pngs = [Path(p) for p in res.get("files") or []] if res.get("ok") else []
            if not pngs or not pngs[0].is_file():
                raise HTTPError(503, {"error": R.failure_text(res) if not res.get("ok") else "no still was written"})
            r = _ffmpeg(["-y", "-i", str(pngs[0]), "-vf", f"scale={w}:-2", "-q:v", "3", str(out)])
            if r.returncode != 0 or not out.is_file():
                raise HTTPError(503, {"error": "ffmpeg could not scale the still"})
            _prune(out.parent)
            return out
        finally:
            shutil.rmtree(self.watch_dir / "still", ignore_errors=True)
            self._still.release()

    def thumb(self, aid: str, t: float, h: int) -> Path:
        path, row = self.asset(aid, ("image", "video", "evidence"))
        kind = row["kind"]
        h = min(max(16, h), 480)
        t = min(max(0.0, t), row.get("duration") or MAX_T) if kind == "video" else 0.0
        stamp = hashlib.sha1(f"{path}|{S._stamp(path)}".encode()).hexdigest()[:10]
        out = self._cached("thumbs", f"{aid}_{stamp}_{t:.2f}_{h}.jpg")
        if out.is_file():
            return out
        with self._media:
            for at in ([t, 0.0] if t > 0 else [0.0]):
                seek = ["-ss", f"{at:.3f}"] if kind == "video" else []
                _ffmpeg(["-y", *seek, "-i", str(path), "-frames:v", "1", "-vf", f"scale=-2:{h}", "-q:v", "5", str(out)])
                if out.is_file():
                    _prune(out.parent)
                    return out
        raise HTTPError(404, {"error": f"no picture in asset {aid} at {t:g} s"})

    def wave(self, aid: str) -> Path:
        if aid == "voice":
            raw = S._read_json(self.root / PROJECT_FILE) or {}
            voice, _ = D.load_voice(self.root, raw.get("voice") if isinstance(raw, dict) else None)
            if voice is None or voice.audio is None:
                raise HTTPError(404, {"error": "the project has no narration"})
            path = voice.audio.resolve()
            if not inside(path, self.root):
                raise HTTPError(404, {"error": "the narration is outside the project"})
        else:
            path, _ = self.asset(aid, ("audio", "video"))
        stamp = hashlib.sha1(f"{path}|{S._stamp(path)}".encode()).hexdigest()[:10]
        out = self._cached("waves", f"{aid}_{stamp}.json")
        if out.is_file():
            return out
        with self._media:
            r = _ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", str(WAVE_RATE), "-f", "s16le", "-"], 300)
        samples = array.array("h")
        if r.returncode == 0:
            samples.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
            if sys.byteorder == "big":
                samples.byteswap()
        duration = len(samples) / WAVE_RATE if samples else (RS.media_duration(path) or 0.0)
        peaks = []
        if samples:
            n = min(WAVE_MAX, max(1, math.ceil(duration * WAVE_PER_S)))
            step = len(samples) / n
            for i in range(n):
                part = samples[int(i * step): max(int(i * step) + 1, int((i + 1) * step))]
                peaks.append(round(max(max(part), -min(part)) / 32768, 3))
        out.write_text(json.dumps({"duration": round(duration, 3), "peaks": peaks}), encoding="utf-8")
        _prune(out.parent)
        return out


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server: "WatchServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):         # quiet: the window is the output
        pass

    def send_response(self, code, message=None):
        self.started = True
        super().send_response(code, message)

    def end_headers(self):
        # nothing here is for other sites: no CORS header ever, and no embedding of a response elsewhere
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head: bool = False):
        self.head = head
        self.answer(lambda url: self.route(url.path))

    def do_POST(self):
        self.head = False
        self.answer(self.post)

    def do_PUT(self):
        self.head = False
        self.answer(self.put)

    def answer(self, handle) -> None:
        """Run one request; whatever goes wrong, the client gets a JSON answer unless the reply has begun."""
        self.started = False
        try:
            if not self.server.host_ok(self.headers.get("Host", "")):
                raise HTTPError(403, {"error": "unexpected Host header"})
            url = urlsplit(self.path)
            self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            handle(url)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:  # noqa: BLE001 - a bad request must not drop the connection or print a traceback
            if isinstance(exc, A.Refusal):
                exc = refused(exc.status, exc.code, **exc.params)
            if isinstance(exc, HTTPError):
                code, body = exc.code, exc.body
            elif isinstance(exc, ValueError):
                code, body = 400, {"error": f"bad request: {exc}"}
            else:
                code, body = 500, {"error": f"the server failed on this request ({type(exc).__name__}: {exc})"}
            if self.started:
                self.close_connection = True
                return
            try:
                self.send_json(body, code)
            except OSError:
                self.close_connection = True

    def cross_site(self) -> bool:
        """A request another site's page made (a link from elsewhere counts too): refused on everything but the
        page itself. An address-bar visit sends Sec-Fetch-Site none; old clients send neither header."""
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return True
        origin = self.headers.get("Origin")
        return origin is not None and not self.server.own_origin(origin)

    def refuse_cross_site(self) -> None:
        if self.cross_site():
            raise HTTPError(403, {"error": "refused: this request came from another site"})

    def route(self, path: str) -> None:
        srv = self.server
        if srv.workspace is not None:
            if path.startswith(("/api/app", "/api/films", "/api/formats", "/api/trash", "/api/library",
                                "/api/settings")):
                self.refuse_cross_site()
                return self.app_get(path)
            if path in APP_PAGES:
                # a page not built yet: the films page, whose frame reaches every other page
                return self.static(APP_PAGES[path] if (STATIC / APP_PAGES[path]).is_file() else "home.html")
            if path in ("/api/projects", "/api/home", "/api/home/events", "/api/session"):
                self.refuse_cross_site()
                if path == "/api/session":
                    return self.send_json({"token": srv.token})
                if path == "/api/home/events":
                    return self.home_events()
                return self.send_json(srv.home() if path == "/api/home" else srv.projects())
            m = re.match(r"^/p/([^/]+)(/.*)?$", path)
            if m:
                if m.group(2) is None:
                    return self.redirect(f"/p/{m.group(1)}/")
                site = srv.site(unquote(m.group(1)), opens(m.group(2)))
                if m.group(2) == "/api/state":
                    srv.mark_seen(site.root.name)           # the film's own page has looked
                return self.site_route(site, m.group(2))
            if path in ("/", "/index.html"):
                return self.static("home.html")
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            # a project page asking by absolute path ("/api/state"): its Referer says which project
            m = re.match(r"^/p/([^/]+)/", urlsplit(self.headers.get("Referer", "")).path)
            if m:
                if path.startswith("/player/"):
                    return self.redirect(f"/p/{m.group(1)}{path}")      # its own fetches then carry the project
                site = srv.site(unquote(m.group(1)), opens(path))
                if path == "/api/state":
                    srv.mark_seen(site.root.name)
                return self.site_route(site, path)
            raise HTTPError(404, {"error": "not found"})
        return self.site_route(srv.site(None), path)

    def site_route(self, site: Site, path: str) -> None:
        q = self.query
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path == "/favicon.ico":
            return self.static("icon.ico")
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        self.refuse_cross_site()
        if path == "/api/session":
            return self.send_json({"token": self.server.token})
        if path == "/api/state":
            return self.send_json(site.state())
        if path == "/api/chat":
            return self.send_json(site.chat.status())
        if path == "/api/events":
            return self.events(site)
        m = re.match(r"^/api/history/(\d+)$", path)
        if m:
            got = S.history_state(site.root, int(m.group(1)), site.base)
            if got is None:
                raise HTTPError(404, {"error": f"no history entry {m.group(1)}"})
            return self.send_json(got)
        if path == "/api/resolved":
            body, _ = site.resolved()
            return self.send_bytes(body, "application/json")
        if path == "/api/still":
            return self.send_file(site.still(self.num("t", 0.0), int(self.num("w", STILL_W))))
        if path == "/api/frame":
            size = {k: int(self.num(k, 0)) if k in q else None for k in ("h", "w")}
            got, source = site.frame(self.num("t", 0.0), size["h"], self.query.get("src", "auto"), size["w"])
            if got is None:
                return self.send_json({"pending": True}, 202)
            return self.send_file(got, headers={"X-Frame-Source": source})
        if path == "/api/thumb":
            return self.send_file(site.thumb(self.asset_id(), self.num("t", 0.0), int(self.num("h", 72))))
        if path == "/api/wave":
            return self.send_file(site.wave(self.asset_id()), "application/json")
        if path.startswith("/project/"):
            full = fenced(site.root, path[len("/project/"):])
            if full is None:
                raise HTTPError(404, {"error": "not found"})
            return self.send_file(full, ranged=True)
        if path.startswith("/player/"):
            return self.player(site.player, path[len("/player/"):])
        raise HTTPError(404, {"error": "not found"})

    # ---- the application's pages ask
    def app_get(self, path: str) -> None:
        srv, q = self.server, self.query
        if path == "/api/app":
            return self.send_json(srv.app())
        if path == "/api/app/events":
            return self.app_events()
        if path == "/api/films/suggest":
            return self.send_json({"name": A.suggest(srv.ws_now(), str(q.get("text", ""))[:400])})
        if path == "/api/formats":
            return self.send_json(srv.formats())
        if path == "/api/trash":
            return self.send_json(A.trash_rows(srv.workspace))
        if path == "/api/library":
            return self.send_json(A.library(srv.ws_now()))
        if path == "/api/library/preview":
            got = srv.previews.get(q.get("name", ""), q.get("theme", "light"))
            if got is None:
                return self.send_json({"pending": True}, 202)
            return self.send_file(got)
        if path == "/api/settings":
            return self.send_json(srv.settings())
        raise HTTPError(404, {"error": "not found"})

    def app_post(self, path: str, body: bytes) -> bool:
        """The application's changes over the workspace; False for a path that is not one."""
        srv = self.server
        if path == "/api/projects":
            name = self.json_body(body, '{"name": "..."}').get("name")
            self.send_json(srv.create_project(name), 201)
        elif path == "/api/films":
            self.send_json(srv.create_film(self.json_body(body, '{"description": "...", "start": true}')), 201)
        elif path == "/api/app/seen":
            name = self.json_body(body, '{"name": "..."}').get("name")
            srv.mark_seen(srv.project_dir(name).name)
            self.send_json({"seen": True})
        elif path == "/api/app/raise":
            self.send_json(srv.raise_app())
        elif path == "/api/settings":
            self.send_json(srv.save_settings(self.json_body(body, '{"parallel": 3}')))
        elif path == "/api/settings/key":
            data = self.json_body(body, '{"name": "...", "value": "..."}')
            A.write_key(srv.ws_now(), data.get("name"), data.get("value"))
            srv.forget_engines()
            self.send_json({"name": data["name"], "present": True})
        elif path == "/api/settings/key/delete":
            name = self.json_body(body, '{"name": "..."}').get("name")
            A.delete_key(srv.ws_now(), name)
            srv.forget_engines()
            self.send_json({"name": name, "present": bool(os.environ.get(name))})
        elif path == "/api/settings/checks":
            self.send_json({"checks": srv.checks(fresh=True)})
        elif path == "/api/reveal":
            self.send_json(srv.reveal_place(self.json_body(body, '{"what": "workspace"}').get("what")))
        else:
            m = re.match(r"^/api/films/([^/]+)/(title|duplicate|trash|reveal)$", path)
            t = re.match(r"^/api/trash/([^/]+)/(restore|delete)$", path)
            if m:
                name, op = unquote(m.group(1)), m.group(2)
                data = self.json_body(body, "{}")
                if op == "title":
                    self.send_json(srv.retitle(name, data.get("title")))
                elif op == "duplicate":
                    self.send_json(srv.duplicate(name, data.get("name")), 201)
                elif op == "trash":
                    self.send_json(srv.trash_film(name))
                else:
                    self.send_json(srv.reveal_film(name, data.get("what")))
            elif t:
                tid = unquote(t.group(1))
                if t.group(2) == "restore":
                    self.send_json(srv.restore(tid))
                else:
                    A.delete_trashed(srv.workspace, tid)
                    srv.bump_home()
                    self.send_json({"deleted": True, "id": tid})
            else:
                return False
        return True

    # ---- changes
    def check_change(self) -> None:
        """A change comes from this server's own page: its Origin and its token."""
        origin = self.headers.get("Origin")
        if not origin or not self.server.own_origin(origin) or self.headers.get("Sec-Fetch-Site") in (
                "cross-site", "same-site"):
            raise HTTPError(403, {"error": "refused: a change must come from this window's own page"})
        if not hmac.compare_digest(self.headers.get(TOKEN_HEADER, "").encode(), self.server.token.encode()):
            raise HTTPError(403, {"error": f"refused: the {TOKEN_HEADER} header is missing or wrong (GET api/session "
                                           "gives it)"})

    def put(self, url) -> None:
        """PUT .../api/upload?name=<file name>: the file is the body, streamed to disk, then added as an asset."""
        size = self.headers.get("Content-Length")
        try:
            self.check_change()
            site, path = self.post_site(url.path)
            if path != "/api/upload":
                raise HTTPError(404, {"error": "not found"})
            name = A.upload_name(self.query.get("name"))
            if size is None or not size.isdigit() or int(size) > A.UPLOAD_MAX:
                raise refused(413 if size and size.isdigit() else 411, "upload.size", max_gb=A.UPLOAD_MAX // 1024 ** 3)
            site.claim()
        except BaseException:
            self.close_connection = True            # the unread body would be taken for the next request
            raise
        left = int(size)
        folder = site.watch_dir / "uploads" / secrets.token_hex(8)
        folder.mkdir(parents=True)
        try:
            with (folder / name).open("wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left > 0:
                self.close_connection = True
                raise refused(400, "upload.incomplete")
            got = A.import_files(site.root, [str(folder / name)])
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.server.bump_home()
        self.send_json(got)

    def post(self, url) -> None:
        body = self.body()
        self.check_change()
        if self.server.workspace is not None and self.app_post(url.path, body):
            return
        site, path = self.post_site(url.path)
        if path == "/api/import":
            return self.send_json(self.server.import_into(site, self.json_body(body, '{"paths": ["..."]}').get(
                "paths")))
        if path == "/api/chat":
            data = self.json_body(body, '{"message": "..."}')
            engine = data.get("engine")
            if engine is not None and not isinstance(engine, str):
                raise HTTPError(400, {"error": "engine must be a string"})
            return self.send_json({"turn": site.send_chat(data.get("message"), engine or None, data.get("context"))},
                                  202)
        if path == "/api/chat/stop":
            return self.send_json({"stopped": site._chat is not None and site._chat.stop()})
        if path == "/api/action":
            code, answer = site.act(self.json_body(body, '{"action": "render"}').get("action"))
            return self.send_json(answer, code)
        if path == "/api/accept":
            return self.send_json(site.accept())
        if path == "/api/reveal":
            return self.send_json(site.reveal())
        raise HTTPError(404, {"error": "not found"})

    def json_body(self, body: bytes, shape: str) -> dict:
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            raise HTTPError(400, {"error": f"the body must be JSON: {shape}"}) from None
        if not isinstance(data, dict):
            raise HTTPError(400, {"error": "the body must be a JSON object"})
        return data

    def post_site(self, path: str) -> tuple[Site, str]:
        srv = self.server
        if srv.workspace is None:
            return srv.site(None), path
        m = re.match(r"^/p/([^/]+)(/.*)$", path)
        if not m:
            raise HTTPError(404, {"error": "not found: a change goes to /p/<project>/api/..."})
        return srv.site(unquote(m.group(1))), m.group(2)

    def body(self) -> bytes:
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if size < 0 or size > MAX_BODY:
            self.close_connection = True            # the unread body would be taken for the next request
            raise HTTPError(413 if size > 0 else 400, {"error": f"the body must have a Content-Length of at most "
                                                                f"{MAX_BODY} bytes"})
        return self.rfile.read(size) if size else b""

    # ---- helpers
    def num(self, key: str, default: float) -> float:
        try:
            value = float(self.query.get(key, default))
        except ValueError:
            raise HTTPError(400, {"error": f"{key} must be a number"}) from None
        if not math.isfinite(value):
            raise HTTPError(400, {"error": f"{key} must be a number"})
        return value

    def asset_id(self) -> str:
        aid = self.query.get("asset", "")
        if not _ID.fullmatch(aid):
            raise HTTPError(400, {"error": "asset must be an asset id"})
        return aid

    def static(self, rel: str) -> None:
        rel = unquote(rel)
        full = (STATIC / rel).resolve()
        if rel == "index.html" and not full.is_file():
            return self.send_bytes(PLACEHOLDER, "text/html; charset=utf-8")
        if not inside(full, STATIC.resolve()) or not full.is_file():
            raise HTTPError(404, {"error": "not found"})
        self.send_file(full)

    def player(self, player: Player, rel: str) -> None:
        ready = player.current()
        if ready is None:
            raise HTTPError(503, {"error": player.error or "the player is being built", "building": player.building})
        full = (ready / (unquote(rel) or "index.html")).resolve()
        if not inside(full, ready.resolve()) or not full.is_file():
            raise HTTPError(404, {"error": "not found"})
        self.send_file(full)

    def redirect(self, to: str) -> None:
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, data, code: int = 200) -> None:
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

    def send_bytes(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not self.head:
            self.wfile.write(body)

    def send_file(self, path: Path, ctype: str | None = None, ranged: bool = False,
                  headers: dict | None = None) -> None:
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range") if ranged else None
        if rng:
            m = _RANGE.match(rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                return self.unsatisfiable(size)
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start >= size or start > end:
                return self.unsatisfiable(size)
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype or content_type(path))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        if ranged:
            self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.head:
            return
        with path.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def unsatisfiable(self, size: int) -> None:
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def events(self, site: Site) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        sent, seq, chat_seq, push_seq = None, site.running_seq, site.chat_seq, site.pushed_seq
        stop = self.server.stopping
        while not stop.is_set():
            with site.changed:
                if (site.revision == sent and site.running_seq == seq and site.chat_seq == chat_seq
                        and site.pushed_seq == push_seq):
                    site.changed.wait(timeout=KEEPALIVE_S)
                rev, now_seq, running = site.revision, site.running_seq, site.running
                chats, lost = site.chat_since(chat_seq)
                chat_seq = site.chat_seq
                pushed, _ = site.pushed_since(push_seq)
                push_seq = site.pushed_seq
            if stop.is_set():
                break
            out = []
            if rev is not None and rev != sent:
                out.append(("change", {"revision": rev, "running": S.running_view(running, site.running_by(),
                                                                                   site.waiting)}))
                sent, seq = rev, now_seq
            elif now_seq != seq:
                out.append(("running", S.running_view(running, site.running_by(), site.waiting)))
                seq = now_seq
            if lost:                    # this stream fell too far behind: the page refetches api/chat
                last = chats[-1] if chats else {}
                out.append(("chat", {"rows": [], "busy": last.get("busy"), "turn": last.get("turn"),
                                     "stopping": last.get("stopping"), "resync": True}))
            else:
                out += [("chat", payload) for payload in chats]
            out += pushed
            if not out:
                self.wfile.write(b": keepalive\n\n")
            for name, data in out:
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

    def app_events(self) -> None:
        """Events: "films" when the list reads differently (at most every APP_PUSH_S), "ended" when a request ends."""
        srv = self.server
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        with srv.home_changed:
            srv.home_watchers += 1
            seq, ended_seq = srv.home_seq, srv.ended_seq
        sent, quiet_since = None, time.monotonic()
        try:
            while not srv.stopping.is_set():
                films = json.dumps(srv.app_films(), ensure_ascii=False)
                with srv.home_changed:
                    ended = [e for n, e in srv.ended if n > ended_seq]
                    ended_seq = srv.ended_seq
                out = [("films", films)] if films != sent else []
                sent = films
                out += [("ended", json.dumps(e, ensure_ascii=False)) for e in ended]
                for name, data in out:
                    self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode())
                if out:
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since >= KEEPALIVE_S:
                    self.wfile.write(b": keepalive\n\n")
                    quiet_since = time.monotonic()
                self.wfile.flush()
                with srv.home_changed:
                    if srv.home_seq == seq and srv.ended_seq == ended_seq:
                        srv.home_changed.wait(timeout=KEEPALIVE_S)
                    seq = srv.home_seq
                if not srv.stopping.is_set():
                    time.sleep(APP_PUSH_S)              # changes that come together go out together
        finally:
            with srv.home_changed:
                srv.home_watchers -= 1

    def home_events(self) -> None:
        """A "projects" event whenever the list would read differently: a project added, a change, work starting or
        ending. The page refetches api/home."""
        srv = self.server
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        with srv.home_changed:
            srv.home_watchers += 1
            seq = srv.home_seq
        try:
            while not srv.stopping.is_set():
                with srv.home_changed:
                    if srv.home_seq == seq:
                        srv.home_changed.wait(timeout=KEEPALIVE_S)
                    now = srv.home_seq
                if srv.stopping.is_set():
                    break
                if now != seq:
                    seq = now
                    self.wfile.write(f"event: projects\ndata: {json.dumps({'seq': seq})}\n\n".encode())
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        finally:
            with srv.home_changed:
                srv.home_watchers -= 1


class WatchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, target: str | Path, port: int = 0, chat_options: dict | None = None):
        """chat_options: the chat's seams (query_fn, client_factory, tools_factory, engines_fn), for tests."""
        target = Path(target).expanduser().resolve()
        self.token = secrets.token_urlsafe(24)
        self.chat_options = chat_options
        if target.name == PROJECT_FILE and target.is_file():
            target = target.parent
        self.target = target
        self.workspace = None
        if not (target / PROJECT_FILE).is_file():
            if not (target / WORKSPACE_FILE).is_file():
                raise ValueError(f"{target} holds neither {PROJECT_FILE} (a project) nor {WORKSPACE_FILE} (a workspace)")
            self.workspace = find_workspace(target)
        try:
            ws = self.workspace or find_workspace(target)
        except WorkspaceError:
            ws = None
        cache = ws.cache_dir / "watch" / "player" if ws else target / "build" / "watch" / "player"
        lib = ws.components_dir if ws and ws.components_dir.is_dir() else None
        self.player = Player(cache, lib)
        self.desktop = False                        # a desktop window shows it (main sets this)
        self.raise_window = None                    # brings that window forward (main sets this)
        self.gate = A.Gate(A.parallel_of(ws.config if ws else {}), self.gate_moved)
        self.chat_options = {**(chat_options or {}), "gate": self.gate}
        self.marks = A.Marks(self.workspace) if self.workspace is not None else None
        self.previews = A.Previews(self.workspace, self.player.version) if self.workspace is not None else None
        self.ended: deque = deque(maxlen=PUSHED_EVENTS)     # (seq, "ended" payload) of requests that ended
        self.ended_seq = 0
        self._chat_facts: dict[str, tuple] = {}     # project -> (transcript stamp, app.chat_facts)
        self._engines: tuple[float, list] | None = None
        self._checks: list | None = None
        self.sites: dict[str | None, Site] = {}
        self._sites_lock = threading.Lock()
        self.stopping = threading.Event()
        self.serving = False
        self._create_lock = threading.Lock()
        self.home_changed = threading.Condition()
        self.home_seq = 0                           # moves whenever the home's list would read differently
        self.home_watchers = 0                      # open home event streams; the list is watched only for them
        self._home_lock = threading.Lock()
        self._home_facts: dict[str, tuple] = {}     # project -> (signature, card facts) for projects without a Site
        self._home_scan: dict[str, tuple] = {}      # project -> its last cheap reading for the home signature
        super().__init__((HOST, port), Handler)
        self.port = self.server_address[1]
        self._poller = threading.Thread(target=self._poll, daemon=True)
        self._poller.start()

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def host_ok(self, host: str) -> bool:
        # a page from elsewhere reaching this port through a rebound DNS name sends its own name
        return host in (f"{HOST}:{self.port}", f"localhost:{self.port}", HOST, "localhost")

    def own_origin(self, origin: str) -> bool:
        return origin in (f"http://{HOST}:{self.port}", f"http://localhost:{self.port}")

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):        # a browser dropping a video read is normal
            super().handle_error(request, client_address)

    def site(self, name: str | None, opened: bool = True) -> Site:
        """The project's Site, made on first use; `opened` False for a request that only fetches a picture."""
        with self._sites_lock:
            site = self.sites.get(name)
            if site is None:
                if name is None:
                    site = Site(self.target, "", self.player, self.chat_options, self.url, opened)
                else:
                    root = self.project_dir(name)
                    site = Site(root, f"/p/{name}", self.player, self.chat_options, f"{self.url}p/{name}/", opened)
                site.on_chat = self.chat_heard
                self.sites[name] = site
            elif opened and not site.opened:
                site.opened = True
            return site

    def project_dir(self, name: str) -> Path:
        base = self.workspace.projects_dir.resolve()
        if not isinstance(name, str) or not _ID.fullmatch(name) or name.lower() in A.RESERVED:
            raise refused(404, "film.unknown", name=str(name)[:64])
        root = (base / name).resolve()
        if root.parent != base or not (root / PROJECT_FILE).is_file():
            raise refused(404, "film.unknown", name=name)
        return root

    def project_dirs(self) -> list[Path]:
        base = self.workspace.projects_dir
        return [p for p in (sorted(base.iterdir()) if base.is_dir() else [])
                if p.is_dir() and _ID.fullmatch(p.name) and (p / PROJECT_FILE).is_file()]

    def projects(self) -> list[dict]:
        """One row per project, the most recently changed first: what the home's cards show. Listing makes no Site:
        a project without one is read through a small cache of its card's facts."""
        rows, dirs = [], self.project_dirs()
        with self._home_lock:
            for gone in set(self._home_facts) - {p.name for p in dirs}:
                del self._home_facts[gone]
        for p in dirs:
            try:
                rows.append(self.project_row(p))
            except Exception:  # noqa: BLE001, S112 - a project removed while it was read: the next list drops it
                continue
        return sorted(rows, key=lambda r: r["modified"] or "", reverse=True)

    def _facts(self, root: Path, base: str) -> dict:
        """The part of a project's state its card shows, rebuilt only when a watched file changed."""
        site = self.sites.get(root.name)
        if site is not None:
            return card_facts(site.cache.get(), base)
        sig = S.signature(root)
        with self._home_lock:
            known = self._home_facts.get(root.name)
        if known is not None and known[0] == sig:
            return known[1]
        facts = card_facts(S.build_state(root, base), base)
        with self._home_lock:
            self._home_facts[root.name] = (sig, facts)
        return facts

    def project_row(self, root: Path) -> dict:
        root = root.resolve()
        name = root.name
        base = f"/p/{name}"
        site = self.sites.get(name)
        facts = self._facts(root, base)
        stamps = [_stamp_s(root / rel) for rel in LAST_CHANGE]
        working = None
        run = P.running(root)
        view = S.running_view(run, site.running_by() if site else "agent", waits_for_renderer(run))
        if view is not None:
            working = {"by": view["by"], "tool": view["tool"], "code": view["code"], "percent": view["percent"],
                       "stage_code": view["stage_code"], "text": view["text"]}
        elif site is not None and site.chat_busy is not None and site.queued is None:
            working = {"by": "chat", "tool": None, "code": "busy.chat", "percent": None, "text": S.TEXTS["busy.chat"]}
        elif site.rendering() if site is not None else render_busy(root):
            working = {"by": "agent", "tool": "render", "code": "busy.render", "percent": None,
                       "text": S.TEXTS["busy.render"]}
        return {"name": name, "path": root.as_posix(), "url": f"{base}/", **facts,
                "modified": S._iso(max(stamps)) if any(stamps) else None, "working": working}

    def home(self) -> dict:
        return {"workspace": {"name": self.workspace.root.name, "path": self.workspace.root.as_posix()},
                "projects": self.projects(),
                "names": {"pattern": _ID.pattern, "max": 64, "reserved": sorted(A.RESERVED)}}

    def name_problem(self, name) -> tuple[int, str] | None:
        """(status, code) of why a new project cannot take this folder name; None when it can."""
        if not isinstance(name, str) or not name:
            return 400, "create.empty"
        if len(name) > 64:
            return 400, "create.long"
        if not _ID.fullmatch(name):
            return 400, "create.chars"
        if name.lower() in A.RESERVED:
            return 400, "create.reserved"
        base = self.workspace.projects_dir
        # case-blind: on Windows and macOS "Sea" is the folder "sea"
        if base.is_dir() and any(p.name.lower() == name.lower() for p in base.iterdir()):
            return 409, "create.taken"
        return None

    def create_project(self, name, profile: str = "", locale: str = "") -> dict:
        """A new project in the workspace's projects folder, on the workspace's profile unless one is named."""
        with self._create_lock:
            problem = self.name_problem(name)
            if problem is not None:
                raise refused(problem[0], problem[1], name=str(name)[:64] if isinstance(name, str) else "")
            base = self.workspace.projects_dir.resolve()
            root = (base / name).resolve()
            if root.parent != base:
                raise refused(400, "create.chars", name=name)
            # the window that asked is open already: the tool must not start another on the new project
            P.skip_auto_open(root)
            try:
                base.mkdir(parents=True, exist_ok=True)
                result = TL.new_project(str(root), profile, "", "", locale)
                ok, text = bool(getattr(result, "ok", True)), str(result)
            except Exception as exc:  # noqa: BLE001 - the page says why instead of a bare 500
                ok, text = False, f"{type(exc).__name__}: {exc}"
            if not ok or not (root / PROJECT_FILE).is_file():
                raise refused(500, "create.failed", error=S.tidier(base)(text).split("\n", 1)[0][:300])
        self.bump_home()
        return {"name": name, "url": f"/p/{name}/", "path": root.as_posix()}

    def bump_home(self) -> None:
        with self.home_changed:
            self.home_seq += 1
            self.home_changed.notify_all()

    def home_signature(self, scan: bool = True) -> tuple:
        """What the home's list depends on. An opened site answers from what its poll already knows; any other
        project from a few file times and its running.json, re-read only when `scan` (else the last reading)."""
        rows = []
        for p in self.project_dirs():
            site = self.sites.get(p.name)
            if site is not None and site.opened:
                run = site.running
                rows.append((p.name, site.revision, run and (run["tool"], run["since"], run["stage"]),
                             site.chat_busy, bool(site.action), site.waiting))
                continue
            if scan or p.name not in self._home_scan:
                run = P.running(p)
                self._home_scan[p.name] = (tuple(_stamp_s(p / rel) for rel in LAST_CHANGE),
                                           run and (run["tool"], run["since"], run["stage"]))
            rows.append((p.name, *self._home_scan[p.name]))
        return tuple(rows)

    def _poll(self) -> None:
        home_sig, scanned = None, 0.0
        while not self.stopping.wait(POLL_S):
            for site in [s for s in list(self.sites.values()) if s.opened]:
                try:
                    site.poll()
                except Exception:  # noqa: BLE001, S112 - a half-written file: the next poll reads it whole
                    continue
            if self.workspace is None or not self.home_watchers:
                home_sig = None
                continue
            scan = time.monotonic() - scanned >= HOME_SCAN_S
            try:
                sig = self.home_signature(scan)
            except Exception:  # noqa: BLE001, S112 - a folder that moved mid-listing: the next poll reads it
                continue
            if scan:
                scanned = time.monotonic()
            if home_sig is not None and sig != home_sig:
                self.bump_home()
            home_sig = sig

    # ---- the application over the workspace
    def ws_now(self):
        """The workspace as its files say now (settings change while the application runs)."""
        try:
            return Workspace.load(self.workspace.root)
        except WorkspaceError:
            return self.workspace

    def engine_rows(self, fresh: bool = False) -> list[dict]:
        if fresh or self._engines is None or time.monotonic() - self._engines[0] > ENGINES_TTL_S:
            self._engines = (time.monotonic(), C.engine_rows(self.ws_now(), self.chat_options.get("engines_fn")))
        return self._engines[1]

    def forget_engines(self) -> None:
        self._engines = None
        for site in list(self.sites.values()):
            if site._chat is not None:
                site._chat._engines = None

    def chat_heard(self, site: Site, payload: dict) -> None:
        """Every chat payload of every film: a request that ended marks the film unread and is announced."""
        for row in payload.get("rows") or []:
            if row.get("role") != "note" or row.get("kind") not in A.OUTCOMES:
                continue
            name = site.root.name
            outcome = A.OUTCOMES[row["kind"]]
            if self.marks is not None:
                self.marks.ended(name, row.get("turn"), outcome)
            with self.home_changed:
                self.ended_seq += 1
                self.ended.append((self.ended_seq, {"name": name, "turn": row.get("turn"), "outcome": outcome,
                                                    "title": A.title_of(site.root)}))
        self.bump_home()

    def gate_moved(self) -> None:
        """A turn entered, left or moved up the queue: every busy chat says its place again."""
        for site in list(self.sites.values()):
            chat = site._chat
            if chat is not None and chat.busy is not None:
                chat._tell([])
        self.bump_home()

    def mark_seen(self, name: str) -> None:
        if self.marks is not None and self.marks.seen(name):
            self.bump_home()

    def chat_facts(self, root: Path) -> dict:
        path = root / ".history" / "chat.jsonl"
        stamp = S._stamp(path)
        known = self._chat_facts.get(root.name)
        if known is None or known[0] != stamp:
            known = (stamp, A.chat_facts(A.last_rows(root)))
            self._chat_facts[root.name] = known
        return known[1]

    def app_row(self, root: Path) -> dict:
        row = self.project_row(root)
        name = row["name"]
        site = self.sites.get(name)
        queue = site.queued if site is not None else None
        unread = bool(self.marks.get(name).get("unread")) if self.marks is not None else False
        chat = self.chat_facts(root.resolve())
        attention = A.attention_of(row, chat, unread)
        status = "working" if row["working"] else "queued" if queue is not None else (
            "attention" if attention else "idle")
        return {**row, "status": status, "queue": queue, "unread": unread, "attention": attention,
                "last": chat["last"]}

    def app_films(self) -> dict:
        rows = []
        dirs = self.project_dirs()
        for gone in set(self._chat_facts) - {p.name for p in dirs}:
            self._chat_facts.pop(gone, None)
        for p in dirs:
            try:
                rows.append(self.app_row(p))
            except Exception:  # noqa: BLE001, S112 - a film moved while it was read: the next list drops it
                continue
        rows.sort(key=lambda r: r["modified"] or "", reverse=True)
        counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("working", "queued", "attention")}
        return {"films": rows, "counts": counts, "parallel": self.gate.state()}

    def app(self) -> dict:
        rows = self.engine_rows()
        ws = self.ws_now()
        chosen = C.default_engine(rows, ws)
        engine = next((r for r in rows if r["id"] == chosen), None)
        if engine is None:
            engine = {"id": None, "label": None, "available": False, "code": "chat.no_engine", "params": {}}
        return {"workspace": {"name": self.workspace.root.name, "path": self.workspace.root.as_posix()},
                "version": A.version_facts()["version"], "desktop": self.desktop, **self.app_films(),
                "names": {"pattern": _ID.pattern, "max": 64, "reserved": sorted(A.RESERVED)},
                "engine": {k: engine.get(k) for k in ("id", "label", "available", "code", "params")}}

    def formats(self) -> dict:
        from ..profiles import PLAYBOOKS, PROFILES
        ws = self.ws_now()
        try:
            own = ws.profiles
        except WorkspaceError:
            own = {}
        rows = [{"id": n, "width": p.width, "height": p.height, "fps": round(float(p.fps), 3),
                 "platform": n in PLAYBOOKS, "origin": "workspace" if n in own else "built-in"}
                for n, p in {**PROFILES, **own}.items()]
        default = ws.config.get("profile") if isinstance(ws.config.get("profile"), str) else "landscape"
        return {"default": default, "formats": rows}

    def create_film(self, data: dict) -> dict:
        from .. import locales
        desc = data.get("description")
        if desc is not None and not isinstance(desc, str):
            raise refused(400, "create.description", max=C.MAX_MESSAGE)
        desc = (desc or "").strip()
        if len(desc) > C.MAX_MESSAGE:
            raise refused(400, "create.description", max=C.MAX_MESSAGE)
        fmt = data.get("format") or ""
        if fmt and (not isinstance(fmt, str) or fmt not in {f["id"] for f in self.formats()["formats"]}):
            raise refused(400, "create.format", format=str(fmt)[:40])
        locale = data.get("locale") or ""
        if locale:
            try:
                locale = locales.check(locale)
            except (ValueError, TypeError):
                raise refused(400, "create.locale", locale=str(locale)[:40]) from None
        engine = data.get("engine")
        if engine is not None and engine not in C.ENGINE_ORDER:
            raise refused(400, "create.engine", engine=str(engine)[:40])
        name = data.get("name")
        if name is None or name == "":
            name = A.suggest(self.ws_now(), desc)
        made = self.create_project(name, fmt, locale)
        out = {"name": made["name"], "url": made["url"], "turn": None, "queued": False}
        if data.get("start") and desc:
            site = self.site(made["name"])
            try:
                out["turn"] = site.send_chat(desc, engine, None)
                out["queued"] = site.queued is not None
            except HTTPError as exc:
                out["refused"] = exc.body
        return out

    def film_busy(self, root: Path) -> bool:
        site = self.sites.get(root.name)
        if site is not None and (site.chat_busy is not None or site.action):
            return True
        return P.running(root) is not None or render_busy(root)

    def retitle(self, name: str, title) -> dict:
        root = self.project_dir(name)
        if (not isinstance(title, str) or len(title.strip()) > A.TITLE_MAX
                or re.search(r"[\x00-\x1f\x7f]", title)):
            raise refused(400, "title.invalid", max=A.TITLE_MAX)
        other = P.owner_elsewhere(root)
        if other is not None:
            raise refused(409, "owner.elsewhere", url=str(other.get("url") or ""), pid=other.get("pid"))
        result = TL.edit(str(root), [{"op": "set", "path": "meta.title", "value": title.strip()}])
        if not getattr(result, "ok", True):
            raise refused(409, "title.failed", error=str(result).split("\n", 1)[0][:300])
        self.bump_home()
        return {"name": name, "title": title.strip()}

    def duplicate(self, name: str, new) -> dict:
        root = self.project_dir(name)
        with self._create_lock:
            if new is None or new == "":
                new = A.free_name(A.folder_names(self.workspace.projects_dir), f"{name}-copy")
            problem = self.name_problem(new)
            if problem is not None:
                raise refused(problem[0], problem[1], name=str(new)[:64] if isinstance(new, str) else "")
            dest = (self.workspace.projects_dir.resolve() / new).resolve()
            if dest.parent != self.workspace.projects_dir.resolve():
                raise refused(400, "create.chars", name=new)
            P.skip_auto_open(dest)
            try:
                dest.mkdir(parents=True)        # holds the name while the copy runs outside the lock
            except OSError as exc:
                raise refused(409, "duplicate.failed", error=str(exc.strerror or exc)) from None
        A.duplicate(root, dest)
        self.bump_home()
        return {"name": new, "url": f"/p/{new}/"}

    def drop_site(self, name: str) -> None:
        with self._sites_lock:
            site = self.sites.pop(name, None)
        if site is not None:
            site.gone = True
            if site._still.acquire(timeout=STILL_TIMEOUT_S):    # a frame still being drawn finishes first
                site._still.release()
            site.release()
            with site.changed:
                site.changed.notify_all()
        with self._home_lock:
            self._home_facts.pop(name, None)
        self._home_scan.pop(name, None)
        self._chat_facts.pop(name, None)

    def trash_film(self, name: str) -> dict:
        root = self.project_dir(name)
        if self.film_busy(root):
            raise refused(409, "film.busy", name=name)
        other = P.owner_elsewhere(root)
        if other is not None:
            raise refused(409, "owner.elsewhere", url=str(other.get("url") or ""), pid=other.get("pid"))
        self.drop_site(name)
        row = A.trash(self.workspace, root)
        if self.marks is not None:
            self.marks.rename(name, None)
        self.bump_home()
        return {"id": row["id"], "name": name}

    def restore(self, tid: str) -> dict:
        with self._create_lock:
            name = A.restore(self.workspace, tid)
        self.bump_home()
        return {"name": name, "url": f"/p/{name}/"}

    def reveal_film(self, name: str, what) -> dict:
        root = self.project_dir(name)
        if what not in ("folder", "out"):
            raise refused(400, "reveal.what")
        folder = root if what == "folder" else root / "out"
        if not folder.is_dir():
            raise refused(404, "reveal.no_film")
        open_folder(folder)
        return {"revealed": True, "what": what}

    def reveal_place(self, what) -> dict:
        """The Library and Settings pages' folders: the notes, the .env and the workspace itself."""
        ws = self.ws_now()
        places = {"workspace": self.workspace.root, "env": self.workspace.root / ".env", "notes": ws.notes_path}
        if what not in places:
            raise refused(400, "reveal.what")
        target = places[what]
        if not target.exists():
            raise refused(404, "reveal.missing", path=target.as_posix())
        open_folder(target if target.is_dir() else target.parent)
        return {"revealed": True, "what": what}

    def checks(self, fresh: bool = False) -> list:
        from .. import doctor
        if fresh or self._checks is None:
            root = str(self.workspace.root)
            self._checks = A.check_rows(doctor.run_checks(workspace=root, cwd=root))
        return self._checks

    def settings(self) -> dict:
        ws = self.ws_now()
        rows = self.engine_rows()
        return {"engines": [{k: r[k] for k in ("id", "label", "available", "code", "params", "why")} for r in rows],
                "default_engine": C.default_engine(rows, ws), "parallel": self.gate.limit,
                "parallel_range": list(A.PARALLEL_RANGE), "budgets": A.budgets(ws), "keys": A.key_rows(ws),
                "env_path": (ws.root / ".env").as_posix(), "spend": A.month_spend(ws), "checks": self.checks(),
                **A.version_facts(), "workspace_path": ws.root.as_posix()}

    def save_settings(self, data: dict) -> dict:
        config = A.update_settings(self.ws_now(), data, C.ENGINE_ORDER)
        if "parallel" in data:
            self.gate.set_limit(A.parallel_of(config))
        self.forget_engines()
        return self.settings()

    def import_into(self, site: Site, paths) -> dict:
        site.claim()
        got = A.import_files(site.root, paths)
        self.bump_home()
        return got

    def raise_app(self) -> dict:
        fn = self.raise_window
        if fn is None:
            return {"raised": False}
        try:
            fn()
        except Exception:  # noqa: BLE001 - a window that cannot come forward still runs
            return {"raised": False}
        return {"raised": True}

    def stop_chats(self, wait_s: float = 15) -> None:
        """A closing window takes its chat's agent along (a CLI child would outlive it otherwise)."""
        sites = list(self.sites.values())
        for site in sites:
            if site._chat is not None:
                site._chat.stop()
        for site in sites:
            if site._chat is not None:
                site._chat.wait(wait_s)
            site.wait_action(wait_s)

    def release(self) -> None:
        """Drop this server's claims on its projects (presence)."""
        for site in list(self.sites.values()):
            site.release()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self.serving = True
        super().serve_forever(poll_interval)

    def stop_quietly(self) -> None:
        """The end of a command: every request stopped, claims dropped, the socket closed, whichever thread served."""
        self.stopping.set()
        self.stop_chats()
        self.release()
        for site in list(self.sites.values()):
            with site.changed:
                site.changed.notify_all()
        with self.home_changed:
            self.home_changed.notify_all()
        if self.serving:
            self.shutdown()
        self.server_close()

    def stop(self) -> None:
        self.stopping.set()
        self.stop_chats()
        self.release()
        for site in list(self.sites.values()):
            with site.changed:
                site.changed.notify_all()
        with self.home_changed:
            self.home_changed.notify_all()
        self.shutdown()
        self.server_close()


def serve(target: str | Path, port: int = 0, chat_options: dict | None = None) -> WatchServer:
    """A started server (in a background thread); stop it with .stop()."""
    srv = WatchServer(target, port, chat_options)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ command line
def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith watch",
                                 description="Open an editor window on a project (or a workspace of projects): watch "
                                             "an agent edit it, and ask an agent for changes in its chat. A desktop "
                                             "window when the `app` extra is installed, else a browser tab. Local "
                                             "only.")
    ap.add_argument("project", help="a project folder, or a workspace folder for all its projects")
    ap.add_argument("--port", type=int, default=0, help="the port on 127.0.0.1 (default: a free one)")
    ap.add_argument("--browser", action="store_true", help="open it in the browser instead of a desktop window")
    ap.add_argument("--no-open", action="store_true", help="serve and print the URL without opening anything")
    return ap


def _title(srv: WatchServer) -> str:
    if srv.workspace is not None:
        return f"reelsmith · {srv.workspace.root.name}"
    state = srv.site(None).state()
    return f"reelsmith · {state['project'].get('title') or state['project']['name']}"


def main(argv: list[str] | None = None) -> int:
    from . import window
    args = parser().parse_args(argv)
    as_app = not args.no_open and not args.browser and window.available()
    target = Path(args.project).expanduser().resolve()
    target = target.parent if target.name == PROJECT_FILE else target
    open_on = P.window_of(target) if as_app and (target / PROJECT_FILE).is_file() else None
    if open_on:
        print(f"reelsmith watch: a window on {target.name} is already open ({open_on.get('url')}, process "
              f"{open_on.get('pid')}); --browser serves another view in the browser", flush=True)
        return 0
    try:
        srv = WatchServer(args.project, args.port)
    except (ValueError, WorkspaceError, OSError) as exc:
        print(f"reelsmith watch: {exc}", file=sys.stderr)
        return 2
    print(f"reelsmith watch: {srv.url}  (local; {'closing the window' if as_app else 'Ctrl+C'} stops it and any "
          "chat turn it runs)", flush=True)
    recorded = as_app and srv.workspace is None
    try:
        if as_app:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            if recorded:
                P.record_window(srv.target, srv.url)
            window.open_window(srv.url, _title(srv))
            srv.shutdown()
        else:
            if not args.no_open:
                if not args.browser:
                    print('reelsmith watch: for a desktop window instead of a browser tab: pip install "reelsmith[app]"',
                          flush=True)
                webbrowser.open(srv.url)
            srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if recorded:
            P.forget_window(srv.target)
        srv.stopping.set()
        srv.stop_chats()
        srv.release()
        srv.server_close()
    return 0
