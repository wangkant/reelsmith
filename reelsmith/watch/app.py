"""The application over a workspace: its films, requests at once, folders, media, library, settings and instance."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..workspace import ENV_FILE, PROJECT_FILE, WORKSPACE_FILE, Workspace, WorkspaceError, parse_dotenv
from . import presence as P

PARALLEL_DEFAULT = 3
PARALLEL_RANGE = (1, 8)
TRASH = ".trash"
TRASH_RECORD = "trash.json"
NOT_COPIED = ("build", "out", ".history")
LAST_TEXT = 160
TITLE_MAX = 120
IMPORT_MAX = 50
UPLOAD_MAX = 8 * 1024 ** 3
VALUE_MAX = 4096
PREVIEW_W = 640
PREVIEW_AT_S = 2.5                  # past every built-in component's entrance
PREVIEW_CLIP_S = 4.0
PREVIEW_THEME = {"light": {"paper": "#FFFFFF"}, "dark": {}}    # the page's white, not the films' warm paper
LICENCE = "PolyForm Noncommercial 1.0.0"
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
_TRASH_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}-\d{8}-\d{6}(?:-\d+)?$")
_KEY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# names Windows will not give a folder, whatever the case
RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                      *(f"lpt{i}" for i in range(1, 10))})
_FILES_LOCK = threading.Lock()      # workspace.json and .env: one read-modify-write at a time
_ASSET_SAFE = re.compile(r"[^a-z0-9_]+")


class Refusal(Exception):
    """A refusal the server answers with: status, a code of state.TEXTS and its parameters."""

    def __init__(self, status: int, code: str, **params):
        super().__init__(code)
        self.status, self.code, self.params = status, code, params


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def clamp_parallel(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return PARALLEL_DEFAULT
    return min(max(n, PARALLEL_RANGE[0]), PARALLEL_RANGE[1])


def parallel_of(config: dict) -> int:
    """workspace.json "watch": {"parallel": N}; the default when it is absent or "watch" is the older true."""
    watch = config.get("watch") if isinstance(config, dict) else None
    if isinstance(watch, dict) and watch.get("parallel") is not None:
        return clamp_parallel(watch["parallel"])
    return PARALLEL_DEFAULT


# ------------------------------------------------------------------ requests at once
class Ticket:
    __slots__ = ("root", "turn")

    def __init__(self, root: Path, turn: int):
        self.root, self.turn = Path(root), turn


class Gate:
    """At most `limit` chat turns run at once; the rest wait in order and a stopped one leaves at once."""

    def __init__(self, limit: int = PARALLEL_DEFAULT, on_change=None):
        self._cond = threading.Condition()
        self.limit = clamp_parallel(limit)
        self._waiting: list[Ticket] = []
        self._running: list[Ticket] = []
        self.on_change = on_change

    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - a listener never stops a turn
                pass

    def ticket(self, root: Path, turn: int) -> Ticket:
        t = Ticket(root, turn)
        with self._cond:
            self._waiting.append(t)
        self._changed()
        return t

    def enter(self, t: Ticket, stop: threading.Event) -> bool:
        """Wait for a free place; False when stopped first (the ticket is gone then)."""
        while True:
            with self._cond:
                if stop.is_set():
                    if t in self._waiting:
                        self._waiting.remove(t)
                    self._cond.notify_all()
                    entered = False
                    break
                if self._waiting and self._waiting[0] is t and len(self._running) < self.limit:
                    self._waiting.pop(0)
                    self._running.append(t)
                    self._cond.notify_all()
                    entered = True
                    break
                self._cond.wait(0.25)
        self._changed()
        return entered

    def leave(self, t: Ticket) -> None:
        with self._cond:
            for queue in (self._running, self._waiting):
                if t in queue:
                    queue.remove(t)
            self._cond.notify_all()
        self._changed()

    def poke(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def position(self, t: Ticket | None) -> int | None:
        """1 for the next to start; None for a turn that runs or would start now."""
        with self._cond:
            if t is None or t not in self._waiting:
                return None
            pos = self._waiting.index(t) + 1 - max(0, self.limit - len(self._running))
            return pos if pos > 0 else None

    def set_limit(self, n: int) -> None:
        with self._cond:
            self.limit = clamp_parallel(n)
            self._cond.notify_all()
        self._changed()

    def state(self) -> dict:
        with self._cond:
            free = max(0, self.limit - len(self._running))
            return {"limit": self.limit, "running": len(self._running),
                    "queued": max(0, len(self._waiting) - free)}


# ------------------------------------------------------------------ unread and the last request's end
class Marks:
    """Per film: unread since a request ended, and how it ended; kept in .cache/watch/app.json."""

    def __init__(self, ws: Workspace):
        self.path = ws.cache_dir / "watch" / "app.json"
        self._lock = threading.Lock()
        self.films: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """What is on disk now: a terminal session on the same workspace writes the same file."""
        data = _read_json(self.path)
        films = data.get("films") if isinstance(data, dict) else None
        self.films = {k: v for k, v in (films or {}).items() if isinstance(v, dict)}

    def _save(self) -> None:
        try:
            _write_json(self.path, {"films": self.films})
        except OSError:
            pass

    def ended(self, name: str, turn: int, outcome: str) -> None:
        with self._lock:
            self._load()
            self.films[name] = {"unread": True, "turn": turn, "outcome": outcome, "at": _now()}
            self._save()

    def seen(self, name: str) -> bool:
        """True when it was unread."""
        with self._lock:
            row = self.films.get(name)
            if not row or not row.get("unread"):        # cheap and common: nothing to clear
                return False
            self._load()
            row = self.films.get(name)
            if not row or not row.get("unread"):
                return False
            row["unread"] = False
            self._save()
            return True

    def get(self, name: str) -> dict:
        with self._lock:
            return dict(self.films.get(name) or {})

    def rename(self, old: str, new: str | None) -> None:
        with self._lock:
            self._load()
            row = self.films.pop(old, None)
            if new is not None and row is not None:
                self.films[new] = row
            self._save()


OUTCOMES = {"end": "done", "stopped": "stopped", "error": "failed", "aborted": "failed", "budget": "refused"}


def last_rows(root: Path, size: int = 32 * 1024) -> list[dict]:
    """The chat transcript's last rows, the latest copy of each, oldest first."""
    path = root / ".history" / "chat.jsonl"
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows: dict[int, dict] = {}
    for line in raw.splitlines()[1 if end > size else 0:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), int):
            rows[row["id"]] = row
    return [rows[k] for k in sorted(rows)]


def plain(text: str, limit: int = LAST_TEXT) -> str:
    text = re.sub(r"```.*?```", " ", str(text or ""), flags=re.S)
    text = re.sub(r"[`*_#>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chat_facts(rows: list[dict]) -> dict:
    """{"last": the last row in brief, "ended": the last turn's note kind, "asked": it ended on a question}."""
    last = next((r for r in reversed(rows) if r.get("role") in ("user", "assistant", "note")), None)
    note = next((r for r in reversed(rows) if r.get("role") == "note"), None)
    turn = note.get("turn") if note else None
    said = next((r for r in reversed(rows) if r.get("role") == "assistant" and r.get("turn") == turn), None)
    question = str((said or {}).get("text") or "").rstrip().endswith(("?", "？"))
    asked = bool(note and note.get("kind") == "end" and question)
    later = bool(note and any(r.get("role") == "user" and (r.get("turn") or 0) > (turn or 0) for r in rows))
    return {"last": {"role": last["role"], "text": plain(last.get("text")), "at": last.get("ts")} if last else None,
            "ended": None if note is None or later else note.get("kind"), "asked": asked and not later}


def attention_of(facts: dict, chat: dict, unread: bool) -> list[dict]:
    """What the film asks of the person, most pressing first."""
    out = []
    if chat["ended"] in ("error", "aborted", "budget"):
        out.append({"code": "attention.failed", "params": {}})
    if chat["asked"] and unread:
        out.append({"code": "attention.reply", "params": {}})
    result = facts.get("result") or {}
    if result.get("state") == "refused":
        out.append({"code": "attention.refused", "params": {}})
    if facts.get("errors") and not facts.get("empty"):     # a new film has nothing to fix yet
        out.append({"code": "attention.issues", "params": {"n": facts["errors"]}})
    if result.get("state") == "current" and not result.get("accepted"):
        out.append({"code": "attention.to_accept", "params": {}})
    return out


# ------------------------------------------------------------------ names, folders, the trash
def free_name(taken, base: str) -> str:
    """base, else base-2, base-3 ... that no folder takes (case-blind) and Windows allows."""
    lower = {n.lower() for n in taken} | RESERVED
    base = base[:60].rstrip("-") or "film"
    name, n = base, 2
    while name.lower() in lower:
        name, n = f"{base[:60 - len(str(n))].rstrip('-')}-{n}", n + 1
    return name


def folder_names(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir()] if folder.is_dir() else []


def suggest(ws: Workspace, text: str) -> str:
    from ..term.places import new_name
    return free_name(folder_names(ws.projects_dir), new_name(ws, text or ""))


def size_of(folder: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(folder):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def _rmtree(path: Path) -> None:
    def retry(fn, p, *_):
        os.chmod(p, 0o700)          # a read-only file (git, some media tools) on Windows
        fn(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def title_of(root: Path) -> str | None:
    meta = (_read_json(root / PROJECT_FILE) or {}).get("meta")
    return (meta or {}).get("title") or None if isinstance(meta, dict) else None


def trash_dir(ws: Workspace) -> Path:
    return ws.root / TRASH


def trash(ws: Workspace, root: Path) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = trash_dir(ws)
    tid, n = f"{root.name}-{stamp}", 2
    while (base / tid).exists():
        tid, n = f"{root.name}-{stamp}-{n}", n + 1
    record = {"name": root.name, "title": title_of(root), "trashed_at": _now()}
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(root, base / tid)
    except OSError as exc:
        raise Refusal(409, "trash.failed", error=str(exc.strerror or exc)) from None
    _write_json(base / tid / TRASH_RECORD, record)
    return {"id": tid, **record}


def trash_rows(ws: Workspace) -> list[dict]:
    base = trash_dir(ws)
    rows = []
    for p in sorted(base.iterdir()) if base.is_dir() else []:
        if not p.is_dir() or not _TRASH_ID.fullmatch(p.name):
            continue
        rec = _read_json(p / TRASH_RECORD) or {}
        rows.append({"id": p.name, "name": str(rec.get("name") or p.name.rsplit("-", 2)[0]), "title": rec.get("title"),
                     "trashed_at": rec.get("trashed_at"), "size_bytes": size_of(p)})
    return sorted(rows, key=lambda r: r["trashed_at"] or "", reverse=True)


def trashed(ws: Workspace, tid: str) -> Path:
    path = trash_dir(ws) / str(tid)
    if not isinstance(tid, str) or not _TRASH_ID.fullmatch(tid) or not (path / PROJECT_FILE).is_file():
        raise Refusal(404, "trash.unknown", id=str(tid)[:80])
    return path


def restore(ws: Workspace, tid: str) -> str:
    path = trashed(ws, tid)
    rec = _read_json(path / TRASH_RECORD) or {}
    want = str(rec.get("name") or "")
    name = free_name(folder_names(ws.projects_dir), want if _ID.fullmatch(want) else "restored")
    ws.projects_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(path, ws.projects_dir / name)
    except OSError as exc:
        raise Refusal(409, "trash.failed", error=str(exc.strerror or exc)) from None
    (ws.projects_dir / name / TRASH_RECORD).unlink(missing_ok=True)
    return name


def delete_trashed(ws: Workspace, tid: str) -> None:
    path = trashed(ws, tid)
    try:
        _rmtree(path)
    except OSError as exc:
        raise Refusal(409, "trash.failed", error=str(exc.strerror or exc)) from None


def duplicate(src: Path, dest: Path) -> None:
    """A copy of the film into dest (already made, so the name is held); linked media stay links."""
    def skip(folder, names):
        return [n for n in names if Path(folder) == src and n in NOT_COPIED]

    def copy(s, d):
        try:
            if os.stat(s).st_nlink > 1:     # media imported as a hard link: a second link, not a second copy
                os.link(s, d)
                return d
        except OSError:
            pass
        return shutil.copy2(s, d)
    try:
        shutil.copytree(src, dest, ignore=skip, copy_function=copy, dirs_exist_ok=True)
    except OSError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise Refusal(500, "duplicate.failed", error=str(getattr(exc, "strerror", None) or exc)) from None


# ------------------------------------------------------------------ media from the window
def asset_id(stem: str, taken) -> str:
    base = _ASSET_SAFE.sub("_", stem.lower()).strip("_")[:40] or "media"
    if not re.match(r"^[a-z_]", base):
        base = "m_" + base
    name, n = base, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    return name


def media_kind(path: Path) -> str | None:
    from ..document import EXTENSIONS
    ext = path.suffix.lower()
    return next((k for k in ("image", "video", "audio") if ext in EXTENSIONS[k]), None)


def import_files(root: Path, paths: list) -> dict:
    """Each file imported as an asset of its own (import_asset: a hard link on the same drive, else a copy)."""
    from .. import tools
    if not isinstance(paths, list) or not paths:
        raise Refusal(400, "import.empty")
    if len(paths) > IMPORT_MAX:
        raise Refusal(400, "import.too_many", max=IMPORT_MAX)
    done, refused = [], []
    for raw in paths:
        name = Path(str(raw)).name if isinstance(raw, str) else ""
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            refused.append({"name": name, "code": "import.not_absolute", "params": {}})
            continue
        path = Path(raw)
        if not path.is_file():
            refused.append({"name": name, "code": "import.missing", "params": {}})
            continue
        kind = media_kind(path)
        if kind is None:
            refused.append({"name": name, "code": "import.kind", "params": {"ext": path.suffix.lower() or "-"}})
            continue
        raw_doc = _read_json(root / PROJECT_FILE) or {}
        aid = asset_id(path.stem, set((raw_doc.get("assets") or {})))
        try:
            res = tools.import_asset(str(root), aid, str(path), kind)
            ok, text = bool(getattr(res, "ok", True)), str(res)
        except Exception as exc:  # noqa: BLE001 - one file failing leaves the others
            ok, text = False, f"{type(exc).__name__}: {exc}"
        row = ((_read_json(root / PROJECT_FILE) or {}).get("assets") or {}).get(aid) if ok else None
        if not ok or not isinstance(row, dict):
            refused.append({"name": name, "code": "import.failed", "params": {"error": text.split("\n", 1)[0][:300]}})
            continue
        done.append({"id": aid, "kind": row.get("kind") or kind, "path": row.get("path")})
    return {"assets": done, "refused": refused}


def upload_name(name) -> str:
    """A file name from the page: its last part, no control or path characters."""
    if not isinstance(name, str):
        raise Refusal(400, "upload.name")
    base = re.split(r"[\\/]", name)[-1].strip()
    if (not base or base in (".", "..") or len(base) > 200 or re.search(r"[\x00-\x1f<>:\"|?*]", base)
            or media_kind(Path(base)) is None):
        raise Refusal(400, "upload.name")
    return base


# ------------------------------------------------------------------ the library
def _prop_rows(schema: dict) -> list[dict]:
    props = schema.get("properties") if isinstance(schema, dict) else None
    need = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    rows = []
    for name, spec in (props or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        kind = spec.get("type")
        if isinstance(kind, list):
            kind = " | ".join(map(str, kind))
        elif kind is None and "enum" in spec:
            kind = " | ".join(json.dumps(v, ensure_ascii=False) for v in spec["enum"])
        rows.append({"name": name, "type": str(kind or "any"), "required": name in need,
                     "about": str(spec.get("description") or "")})
    return rows


def components(ws: Workspace) -> dict:
    from .. import library as L
    found = {n: ("built-in", c) for n, c in L._scan(L.presets_dir(), "preset").items()}
    found.update({n: ("workspace", c) for n, c in L._scan(ws.components_dir, "library").items()})
    return dict(sorted(found.items()))


def library(ws: Workspace) -> dict:
    rows = []
    for name, (origin, c) in components(ws).items():
        rows.append({"name": name, "origin": origin, "about": c.description, "props": _prop_rows(c.schema),
                     "example": c.example, "problem": c.problem or None,
                     "preview": None if c.problem else f"/api/library/preview?name={name}&theme=light"})
    notes = None
    if ws.notes_path.is_file():
        try:
            notes = {"path": ws.notes_path.as_posix(), "text": ws.notes_path.read_text(encoding="utf-8-sig"),
                     "modified": datetime.fromtimestamp(ws.notes_path.stat().st_mtime).isoformat(timespec="seconds")}
        except OSError:
            notes = None
    rules = {part: [{"key": k, "value": v} for k, v in sorted((ws.rules.get(part) or {}).items())]
             for part in ("hard", "advice")}
    fonts = [{"name": family, "path": str(entry.get("path") or "")}
             for family, entries in sorted(ws.fonts.items()) for entry in entries[:1]]
    return {"components": rows, "notes": notes, "rules": rules, "fonts": fonts}


class Previews:
    """One still per component and theme, drawn one at a time and cached under .cache/watch/library/."""

    def __init__(self, ws: Workspace, version=lambda: ""):
        self.ws, self.version = ws, version
        self.folder = ws.cache_dir / "watch" / "library"
        self._lock = threading.Lock()
        self._queue: list[tuple[str, str, str]] = []
        self._thread: threading.Thread | None = None
        self.failed: dict[str, str] = {}
        self.drawing: str | None = None             # the key the renderer draws now

    def key(self, name: str, theme: str) -> tuple[str, object]:
        comps = components(self.ws)
        if name not in comps:
            raise Refusal(404, "library.unknown", name=str(name)[:64])
        _, c = comps[name]
        if c.problem:
            raise Refusal(409, "library.unusable", name=name, error=c.problem)
        h = hashlib.sha1(f"{name}|{theme}|{PREVIEW_THEME[theme]}|{self.version()}|"
                         f"{json.dumps(c.example, sort_keys=True)}".encode())
        for p in (c.path, c.meta_path):
            if p is not None:
                try:
                    st = p.stat()
                    h.update(f"|{p}|{st.st_mtime_ns}|{st.st_size}".encode())
                except OSError:
                    pass
        return f"{name}-{theme}-{h.hexdigest()[:12]}", c

    def get(self, name, theme) -> Path | None:
        """The JPEG, or None while it is queued or drawn."""
        if theme not in ("light", "dark"):
            raise Refusal(400, "library.theme")
        key, c = self.key(str(name), theme)
        out = self.folder / f"{key}.jpg"
        if out.is_file():
            return out
        if key in self.failed:
            raise Refusal(503, "library.preview_failed", name=name, error=self.failed[key])
        with self._lock:
            if key != self.drawing and all(q[0] != key for q in self._queue):
                self._queue.append((key, c.name, theme))
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="reelsmith-library", daemon=True)
                self._thread.start()
        return None

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    return
                key, name, theme = self._queue.pop(0)
                self.drawing = key
            try:
                if not (self.folder / f"{key}.jpg").is_file():
                    self.draw(key, name, theme)
            except Exception as exc:  # noqa: BLE001 - the page shows why
                self.failed[key] = str(exc).split("\n", 1)[0][:300]
            finally:
                with self._lock:
                    self.drawing = None

    def draw(self, key: str, name: str, theme: str) -> None:
        from .. import render as R
        from .. import resolve as RS
        from ..profiles import get_profile
        comps = components(self.ws)
        comp = comps[name][1]
        props = dict(comp.example) if isinstance(comp.example, dict) else {}
        if "ground" in ((comp.schema or {}).get("properties") or {}):
            props.setdefault("ground", theme)          # a component that adapts to the ground it sits on
        profile = get_profile("landscape")
        work = self.ws.cache_dir / "watch" / "library-work" / key
        shutil.rmtree(work, ignore_errors=True)
        (work / "stills").mkdir(parents=True)
        try:
            box = {"x": profile.width // 12, "y": profile.height // 12, "w": profile.width * 5 // 6,
                   "h": profile.height * 5 // 6}
            doc = {"version": 2, "profile": "landscape", "theme": dict(PREVIEW_THEME[theme]),
                   "meta": {"title": name}, "assets": {},
                   "tracks": [{"id": "ground", "kind": "visual",       # the page's own ground under the component
                               "clips": [{"id": "ground", "type": "shape", "shape": "rect",
                                          "fill": "night" if theme == "dark" else "paper",
                                          "start": 0, "end": PREVIEW_CLIP_S, "box": "full"}]},
                              {"id": "main", "kind": "visual",
                               "clips": [{"id": "preview", "type": "component", "name": name, "start": 0,
                                          "end": PREVIEW_CLIP_S, "box": box,
                                          "props": props}]}]}
            (work / PROJECT_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            data = RS._Resolver(work).run()
            src = work / "resolved.json"
            src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            frame = min(int(PREVIEW_AT_S * profile.fps), int(data.get("durationInFrames") or 1) - 1)
            res = R.run_node("stills", src, work, work / "stills", [max(0, frame)])
            pngs = [Path(p) for p in res.get("files") or []] if res.get("ok") else []
            if not pngs or not pngs[0].is_file():
                raise RuntimeError(R.failure_text(res) if not res.get("ok") else "no still was written")
            self.folder.mkdir(parents=True, exist_ok=True)
            out = self.folder / f"{key}.jpg"
            from .server import _ffmpeg
            r = _ffmpeg(["-y", "-i", str(pngs[0]), "-vf", f"scale={PREVIEW_W}:-2", "-q:v", "3", str(out)])
            if r.returncode != 0 or not out.is_file():
                raise RuntimeError("ffmpeg could not scale the still")
            stem = key.rsplit("-", 1)[0]
            for old in self.folder.glob(f"{stem}-*.jpg"):       # an older version of the same component
                if old != out:
                    old.unlink(missing_ok=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ settings
def known_keys(ws: Workspace) -> dict[str, str]:
    """Every key name the code reads, with what it is used for."""
    from .. import backends, doctor
    from ..agent.providers import PROVIDERS
    names = dict(doctor.key_names(ws.root))
    for b in backends.BACKENDS.values():
        names.setdefault(b.key, f"the {b.name} backend of the Agent SDK engine")
    for p in PROVIDERS.values():
        if p.key:
            names.setdefault(p.key, f"the {p.name} provider of the API engine")
    return names


def key_rows(ws: Workspace) -> list[dict]:
    env = ws.root / ENV_FILE
    stored = parse_dotenv(env.read_text(encoding="utf-8-sig")) if env.is_file() else {}
    return [{"name": n, "present": bool(stored.get(n) or os.environ.get(n)),
             "where": "env_file" if stored.get(n) else "environment" if os.environ.get(n) else None, "used_for": why}
            for n, why in known_keys(ws).items()]


ENV_HEADER = ("# Keys for reelsmith, one NAME=value per line. Written by the reelsmith application or by hand;\n"
              "# never paste a key into a chat.\n")


def _env_value(name: str, value: str) -> str | None:
    """The value as written to .env, or None when the engine's reader would not read it back unchanged."""
    if "\n" in value or "\r" in value:
        return None
    if "'" not in value:
        out = f"'{value}'"                  # single quotes: the reader takes everything up to the next one
    else:
        out = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return out if parse_dotenv(f"{name}={out}\n").get(name) == value else None


def _key_line(line: str, name: str) -> bool:
    body = line.strip()
    if body.startswith("export "):
        body = body[len("export "):].lstrip()
    return body.split("=", 1)[0].strip() == name and "=" in body and not body.startswith("#")


def write_key(ws: Workspace, name, value) -> None:
    if not isinstance(name, str) or not _KEY_NAME.fullmatch(name) or name not in known_keys(ws):
        raise Refusal(400, "key.unknown", name=str(name)[:64] if isinstance(name, str) else "")
    if (not isinstance(value, str) or not value.strip() or len(value) > VALUE_MAX
            or re.search(r"[\x00-\x1f\x7f]", value)):
        raise Refusal(400, "key.value", name=name)
    quoted = _env_value(name, value.strip())
    if quoted is None:
        raise Refusal(400, "key.value", name=name)
    new = f"{name}={quoted}"
    with _FILES_LOCK:
        path = _env_path(ws)
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else ENV_HEADER.splitlines()
        at = next((i for i, ln in enumerate(lines) if _key_line(ln, name)), None)
        if at is None:      # the starter file's commented placeholder for this key
            at = next((i for i, ln in enumerate(lines) if re.fullmatch(rf"#\s*{name}=\s*", ln.strip())), None)
        if at is None:
            lines.append(new)
        else:
            lines[at] = new
            lines = [ln for i, ln in enumerate(lines) if i == at or not _key_line(ln, name)]
        _write_text(path, "\n".join(lines) + "\n", private=True)


def delete_key(ws: Workspace, name) -> None:
    if not isinstance(name, str) or not _KEY_NAME.fullmatch(name) or name not in known_keys(ws):
        raise Refusal(400, "key.unknown", name=str(name)[:64] if isinstance(name, str) else "")
    with _FILES_LOCK:
        path = _env_path(ws)
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        _write_text(path, "\n".join(ln for ln in lines if not _key_line(ln, name)) + "\n", private=True)


def _env_path(ws: Workspace) -> Path:
    # a symlinked .env is written through to its target, not replaced by a file
    path = ws.root / ENV_FILE
    return Path(os.path.realpath(path)) if path.is_symlink() else path


def _write_text(path: Path, text: str, private: bool = False) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o666)
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def month_spend(ws: Workspace) -> dict:
    """The ledger's paid calls this calendar month (UTC), by tool."""
    from ..providers.ledger import Ledger, row_cost
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    by: dict[str, list] = {}
    for rows in Ledger(ws.ledger_path).calls().values():
        if not str(rows[0].get("ts") or "").startswith(month):
            continue
        tool = str(rows[0].get("tool") or "other")
        got = by.setdefault(tool, [0.0, 0])
        got[0] += row_cost(rows[-1])
        got[1] += 1
    tools = [{"tool": t, "usd": round(v[0], 4), "calls": v[1]} for t, v in sorted(by.items(), key=lambda x: -x[1][0])]
    return {"month_usd": round(sum(t["usd"] for t in tools), 4), "by_tool": tools}


def budgets(ws: Workspace) -> dict:
    from .. import runner
    from ..providers.config import _budget
    try:
        request = runner.settings_for(ws).budget_usd
    except WorkspaceError:
        request = None
    try:
        b = _budget(ws.config.get("budget"))
    except Exception:  # noqa: BLE001 - a bad budget section shows as unknown
        b = {}
    return {"request_usd": request, "project_usd": b.get("per_project_usd"),
            "min_balance_usd": b.get("min_balance_usd")}


def check_rows(report: dict) -> list[dict]:
    return [{k: c.get(k) for k in ("name", "ok", "required", "detail", "fix")} for c in report.get("checks") or []]


def _money(key: str, value, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0 or (
            positive and value == 0) or value > 100000:
        raise Refusal(400, "settings.budget", key=key)
    return float(value)


def _update_settings(ws: Workspace, data: dict, engines: tuple) -> dict:
    unknown = sorted(set(data) - {"default_engine", "parallel", "budgets"})
    if unknown:
        raise Refusal(400, "settings.unknown", key=str(unknown[0])[:64])
    path = ws.root / WORKSPACE_FILE
    config = _read_json(path)
    if not isinstance(config, dict):
        raise Refusal(409, "settings.workspace", error=f"{WORKSPACE_FILE} cannot be read")
    if "default_engine" in data:
        eng = data["default_engine"]
        if eng is not None and eng not in engines:
            raise Refusal(400, "settings.engine", engine=str(eng)[:40])
        runner_cfg = dict(config.get("runner") or {}) if isinstance(config.get("runner"), dict) else {}
        if eng is None:
            runner_cfg.pop("engine", None)
        else:
            runner_cfg["engine"] = eng
        config["runner"] = runner_cfg
    if "parallel" in data:
        n = data["parallel"]
        if isinstance(n, bool) or not isinstance(n, int) or not PARALLEL_RANGE[0] <= n <= PARALLEL_RANGE[1]:
            raise Refusal(400, "settings.parallel", min=PARALLEL_RANGE[0], max=PARALLEL_RANGE[1])
        watch = config.get("watch")
        watch = dict(watch) if isinstance(watch, dict) else {"open": True} if watch is True else {}
        watch["parallel"] = n
        config["watch"] = watch
    if "budgets" in data:
        b = data["budgets"]
        if not isinstance(b, dict) or set(b) - {"request_usd", "project_usd", "min_balance_usd"}:
            raise Refusal(400, "settings.budget", key=",".join(sorted(set(b) if isinstance(b, dict) else []))[:64]
                          or "budgets")
        if "request_usd" in b:
            runner_cfg = dict(config.get("runner") or {}) if isinstance(config.get("runner"), dict) else {}
            runner_cfg["budget_usd"] = _money("request_usd", b["request_usd"], True)
            config["runner"] = runner_cfg
        for key, field in (("project_usd", "per_project_usd"), ("min_balance_usd", "min_balance_usd")):
            if key in b:
                part = dict(config.get("budget") or {}) if isinstance(config.get("budget"), dict) else {}
                part[field] = _money(key, b[key], False)
                config["budget"] = part
    try:
        Workspace(ws.root, config)          # the parts that check themselves on load
        from .. import runner
        runner.settings_for(Workspace(ws.root, config))
    except (WorkspaceError, ValueError) as exc:
        raise Refusal(400, "settings.workspace", error=str(exc)[:300]) from None
    _write_text(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return config


def update_settings(ws: Workspace, data: dict, engines: tuple) -> dict:
    """The new workspace.json (only the keys asked for changed), checked to load before it is written."""
    with _FILES_LOCK:
        return _update_settings(ws, data, engines)


def version_facts() -> dict:
    return {"version": __version__, "licence": LICENCE}


# ------------------------------------------------------------------ one application per workspace
def instance_path(ws_root: Path) -> Path:
    return Path(ws_root) / ".cache" / "watch" / "instance.json"


def running_instance(ws_root: Path) -> dict | None:
    """{pid, url, token} of the application another live process runs on the workspace."""
    row = _read_json(instance_path(ws_root))
    if not isinstance(row, dict) or row.get("pid") == os.getpid() or not P.pid_alive(row.get("pid")):
        return None
    return row


def claim_instance(ws_root: Path, url: str, token: str) -> dict | None:
    """Record this process as the workspace's application; the live one's row instead when another holds it."""
    path = instance_path(ws_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": os.getpid(), "url": url, "token": token, "since": _now()}, indent=2) + "\n"
    for _ in range(5):
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(body, encoding="utf-8", newline="\n")
        try:
            os.link(tmp, path)              # atomic, and refused when the record exists: two starts, one wins
            return None
        except FileExistsError:
            pass
        except OSError:                     # a file system without hard links
            try:
                with open(path, "x", encoding="utf-8", newline="\n") as f:
                    f.write(body)
                return None
            except FileExistsError:
                pass
        finally:
            tmp.unlink(missing_ok=True)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        row = _read_json(path)
        if isinstance(row, dict) and P.pid_alive(row.get("pid")) and answers(row):
            return row
        try:                                # stale: its process is gone or the pid is another program's now
            if path.read_text(encoding="utf-8") == raw:
                path.unlink()
        except OSError:
            pass
    _write_json(path, json.loads(body))
    return None


def forget_instance(ws_root: Path) -> None:
    path = instance_path(ws_root)
    if (_read_json(path) or {}).get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def _ask(row: dict, method: str, route: str, timeout: float):
    """(status, JSON body) of a request to the recorded application, or None when nothing answers there."""
    import http.client
    from urllib.parse import urlsplit
    url = urlsplit(str(row.get("url") or ""))
    if url.hostname not in ("127.0.0.1", "localhost") or not url.port:
        return None
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    try:
        conn.request(method, route, body=b"{}" if method == "POST" else None, headers={
            "Content-Type": "application/json", "Origin": f"http://{url.hostname}:{url.port}",
            "X-Reelsmith-Token": str(row.get("token") or "")})
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b"null")
    except (OSError, ValueError):
        return None
    finally:
        conn.close()


def answers(row: dict, timeout: float = 5.0) -> bool:
    """True when the recorded address is a reelsmith application on this workspace's films."""
    got = _ask(row, "GET", "/api/app", timeout)
    return bool(got and got[0] == 200 and isinstance(got[1], dict) and "films" in got[1])


def ask_to_raise(row: dict, timeout: float = 5.0) -> bool:
    """True when the running application's window came forward."""
    got = _ask(row, "POST", "/api/app/raise", timeout)
    return bool(got and got[0] == 200 and isinstance(got[1], dict) and got[1].get("raised"))
