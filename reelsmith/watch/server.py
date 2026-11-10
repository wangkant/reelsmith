"""`reelsmith watch`: a local, read-only editor window over a project (or a workspace of projects) while an agent
edits it. Standard library only; binds 127.0.0.1."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .. import document as D
from .. import media
from .. import render as R
from .. import resolve as RS
from .. import timeexpr as T
from ..workspace import PROJECT_FILE, WORKSPACE_FILE, WorkspaceError, find_workspace, project_file
from . import state as S

HOST = "127.0.0.1"
STATIC = Path(__file__).resolve().parent / "static"
PLACEHOLDER = b"<!doctype html><meta charset=utf-8><title>reelsmith watch</title><p>reelsmith watch: the window is " \
              b"not built yet; <a href=api/state>api/state</a> works.</p>"
POLL_S = 0.5
KEEPALIVE_S = 15
STILL_W = 960
STILL_TIMEOUT_S = 180
KEEP_CACHED = 400                   # files per cache folder under build/watch/
WAVE_RATE = 8000
WAVE_PER_S = 100
WAVE_MAX = 4000
RENDER_STALE_S = 3600               # a render that left its marks this long ago has died, not run
PLAYER_BUILD_S = 600
CHUNK = 256 * 1024
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
         ".ttf": "font/ttf", ".otf": "font/otf", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
         ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".vtt": "text/vtt; charset=utf-8", ".srt": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
         ".map": "application/json"}
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")


class HTTPError(Exception):
    def __init__(self, code: int, body: dict):
        super().__init__(body.get("error"))
        self.code, self.body = code, body


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def fenced(root: Path, rel: str) -> Path | None:
    """A file under one of the served project folders; anything else (.., absolute, a link leading out) is None."""
    rel = unquote(rel).replace("\\", "/")
    parts = rel.split("/")
    if not rel or parts[0] not in S.SERVED or any(p in ("", ".", "..") for p in parts) or ":" in rel:
        return None
    full = project_file(root, rel)
    if full is None or not inside(full, (root / parts[0]).resolve()) or not full.is_file():
        return None
    return full


def render_busy(root: Path) -> bool:
    """A render of this project is running in some process: it writes resolved.film.json first and report.json
    last, and keeps film.raw.mp4 / film.mastered.mp4 only while it runs."""
    build = root / "build"
    now = time.time()
    for name in ("film.raw.mp4", "film.mastered.mp4"):
        p = build / name
        if p.is_file() and now - p.stat().st_mtime < RENDER_STALE_S:
            return True
    try:
        started = (build / "resolved.film.json").stat().st_mtime
    except OSError:
        return False
    try:
        finished = (build / "report.json").stat().st_mtime
    except OSError:
        finished = 0.0
    return started > finished and now - started < RENDER_STALE_S


def _prune(folder: Path, keep: int = KEEP_CACHED) -> None:
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


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
            for old in self.cache.iterdir():
                if old.is_dir() and old != out:
                    shutil.rmtree(old, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - shown in the 503 and the window falls back to stills
            with self._lock:
                self.error = str(exc)
                self._checked = time.monotonic() + 30       # wait a little before trying again
        finally:
            self.building = False


# ------------------------------------------------------------------ one project
class Site:
    def __init__(self, root: Path, base: str, player: Player):
        self.root, self.base, self.player = root, base, player
        self.cache = S.StateCache(root, base)
        self.changed = threading.Condition()
        self.revision: str | None = None
        self._sig: tuple | None = None
        self._still = threading.Lock()
        self._media = threading.BoundedSemaphore(2)
        self._resolved: tuple[tuple, bytes, str] | None = None
        self._resolved_lock = threading.Lock()
        self.watch_dir = root / "build" / "watch"

    def poll(self) -> None:
        sig = S.signature(self.root)
        if sig == self._sig:
            return
        self._sig = sig
        rev = self.cache.get()["revision"]
        if rev != self.revision:
            with self.changed:
                self.revision = rev
                self.changed.notify_all()

    def state(self) -> dict:
        st = self.cache.get()
        if st["revision"] != self.revision:
            with self.changed:
                self.revision = st["revision"]
                self.changed.notify_all()
        return st

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

    def asset(self, aid: str, kinds: tuple) -> tuple[Path, str]:
        st = self.cache.get()
        row = next((a for a in st["assets"] if a["id"] == aid), None)
        if row is None or row["kind"] not in kinds:
            raise HTTPError(404, {"error": f"no {' or '.join(kinds)} asset {aid!r}"})
        path = fenced(self.root, row["path"])
        if path is None:
            raise HTTPError(404, {"error": f"asset {aid} has no file the window may read"})
        return path, row["kind"]

    def _cached(self, sub: str, key: str) -> Path:
        folder = self.watch_dir / sub
        folder.mkdir(parents=True, exist_ok=True)
        return folder / key

    def still(self, t: float, w: int) -> Path:
        st = self.cache.get()
        if not st["valid"]:
            raise HTTPError(503, {"error": st["error"]})
        fps, frames = st["canvas"]["fps"], st["frames"]
        frame = min(max(0, T.to_frame(max(0.0, t), fps)), frames - 1)
        w = min(max(64, w), st["canvas"]["width"])
        body, key = self.resolved()
        out = self._cached("stills", f"{key}_{frame}_{w}.jpg")
        if out.is_file():
            return out
        if render_busy(self.root):
            raise HTTPError(503, {"error": "a render of this project is running; stills wait for it", "busy": True})
        if not self._still.acquire(blocking=False):
            raise HTTPError(503, {"error": "the renderer is busy with another still", "busy": True})
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
        path, kind = self.asset(aid, ("image", "video", "evidence"))
        h = min(max(16, h), 480)
        t = max(0.0, t) if kind == "video" else 0.0
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

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head: bool = False):
        self.head = head
        try:
            if not self.server.host_ok(self.headers.get("Host", "")):
                raise HTTPError(403, {"error": "unexpected Host header"})
            url = urlsplit(self.path)
            self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            self.route(url.path)
        except HTTPError as exc:
            self.send_json(exc.body, exc.code)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def route(self, path: str) -> None:
        srv = self.server
        if srv.workspace is not None:
            if path == "/api/projects":
                return self.send_json(srv.projects())
            m = re.match(r"^/p/([^/]+)(/.*)?$", path)
            if m:
                if m.group(2) is None:
                    return self.redirect(f"/p/{m.group(1)}/")
                return self.site_route(srv.site(unquote(m.group(1))), m.group(2))
            if path == "/":
                return self.send_bytes(srv.index_page(), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            # a project page asking by absolute path ("/api/state"): its Referer says which project
            m = re.match(r"^/p/([^/]+)/", urlsplit(self.headers.get("Referer", "")).path)
            if m:
                if path.startswith("/player/"):
                    return self.redirect(f"/p/{m.group(1)}{path}")      # its own fetches then carry the project
                return self.site_route(srv.site(unquote(m.group(1))), path)
            raise HTTPError(404, {"error": "not found"})
        return self.site_route(srv.site(None), path)

    def site_route(self, site: Site, path: str) -> None:
        q = self.query
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        if path == "/api/state":
            return self.send_json(site.state())
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
        if not _ID.match(aid):
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

    def send_file(self, path: Path, ctype: str | None = None, ranged: bool = False) -> None:
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
        sent = None
        stop = self.server.stopping
        while not stop.is_set():
            with site.changed:
                if site.revision == sent:
                    site.changed.wait(timeout=KEEPALIVE_S)
                rev = site.revision
            if stop.is_set():
                break
            if rev is not None and rev != sent:
                self.wfile.write(f"event: change\ndata: {json.dumps({'revision': rev})}\n\n".encode())
                sent = rev
            else:
                self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()


class WatchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, target: str | Path, port: int = 0):
        target = Path(target).expanduser().resolve()
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
        self.sites: dict[str | None, Site] = {}
        self._sites_lock = threading.Lock()
        self.stopping = threading.Event()
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

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):        # a browser dropping a video read is normal
            super().handle_error(request, client_address)

    def site(self, name: str | None) -> Site:
        with self._sites_lock:
            if name in self.sites:
                return self.sites[name]
            if name is None:
                site = Site(self.target, "", self.player)
            else:
                root = self.project_dir(name)
                site = Site(root, f"/p/{name}", self.player)
            self.sites[name] = site
            return site

    def project_dir(self, name: str) -> Path:
        base = self.workspace.projects_dir.resolve()
        root = (base / name).resolve()
        if not _ID.match(name) or root.parent != base or not (root / PROJECT_FILE).is_file():
            raise HTTPError(404, {"error": f"no project {name!r} in {base}"})
        return root

    def projects(self) -> list[dict]:
        base = self.workspace.projects_dir
        rows = []
        for p in sorted(base.iterdir()) if base.is_dir() else []:
            pj = p / PROJECT_FILE
            if not (p.is_dir() and pj.is_file() and _ID.match(p.name)):
                continue
            raw = S._read_json(pj)
            meta = raw.get("meta") if isinstance(raw, dict) else None
            try:
                duration = S.Film(p.resolve(), raw).duration
            except Exception:  # noqa: BLE001 - a broken project still lists
                duration = None
            rows.append({"name": p.name, "path": p.resolve().as_posix(),
                         "title": meta.get("title") if isinstance(meta, dict) else None, "duration": duration,
                         "modified": S._iso(pj.stat().st_mtime)})
        return rows

    def index_page(self) -> bytes:
        rows = ""
        for p in self.projects():
            length = "" if p["duration"] is None else f" · {p['duration']:.1f} s"
            rows += (f'<li><a href="p/{p["name"]}/">{_esc(p["title"] or p["name"])}</a> '
                     f'<small>{_esc(p["name"])}{length}</small></li>')
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<title>reelsmith watch</title><style>body{font:15px system-ui,sans-serif;margin:2rem;"
                "background:#fff;color:#222}a{color:inherit}li{margin:.4rem 0}small{color:#777}</style>"
                f"<h1>{_esc(self.workspace.root.name)}</h1><ul>{rows or '<li>no projects yet</li>'}</ul>").encode()

    def _poll(self) -> None:
        while not self.stopping.wait(POLL_S):
            for site in list(self.sites.values()):
                try:
                    site.poll()
                except Exception:  # noqa: BLE001, S112 - a half-written file: the next poll reads it whole
                    continue

    def stop(self) -> None:
        self.stopping.set()
        for site in list(self.sites.values()):
            with site.changed:
                site.changed.notify_all()
        self.shutdown()
        self.server_close()


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def serve(target: str | Path, port: int = 0) -> WatchServer:
    """A started server (in a background thread); stop it with .stop()."""
    srv = WatchServer(target, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ command line
def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith watch",
                                 description="Open a read-only editor window on a project (or a workspace of "
                                             "projects), to watch an agent edit it: a desktop window when the `app` "
                                             "extra is installed, else a browser tab. Local only.")
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
    try:
        srv = WatchServer(args.project, args.port)
    except (ValueError, WorkspaceError, OSError) as exc:
        print(f"reelsmith watch: {exc}", file=sys.stderr)
        return 2
    as_app = not args.no_open and not args.browser and window.available()
    print(f"reelsmith watch: {srv.url}  (read-only, local; "
          f"{'closing the window' if as_app else 'Ctrl+C'} stops it)", flush=True)
    try:
        if as_app:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
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
        srv.stopping.set()
        srv.server_close()
    return 0
