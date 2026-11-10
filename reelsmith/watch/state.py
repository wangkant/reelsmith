"""The watch window's state: one JSON document built from a project folder with the engine's own readers (document,
resolve, checks), cached by the mtimes of the files it reads. Nothing here renders or writes the project."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from .. import document as D
from .. import locales
from .. import resolve as RS
from .. import timeexpr as T
from ..checks import check_project
from ..media import probe
from ..workspace import WorkspaceError, find_workspace, profile_for, project_file

SERVED = ("assets", "voice", "out", "build")          # the only project folders the server hands out
ACTIVITY = "activity.jsonl"
ACTIVITY_SHOWN = 300
_ROUND = 4
_LAYOUT_ROW = re.compile(r"^\[(?P<level>\w+)\] (?P<where>.+?)(?: @ (?P<t>\d+(?:\.\d+)?)s)?: (?P<msg>.*)$", re.S)
_CLIP_WHERE = re.compile(r"^(?:clip )?(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*)(?: @ (?P<t>\d+(?:\.\d+)?)s)?(?:[.\s]|$)")
_VIDEO_SIZE: dict[tuple, tuple[int, int] | None] = {}


def _sec(frames: int, fps: float) -> float:
    return round(frames / fps, _ROUND)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _stamp(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def project_url(root: Path, rel: str, base: str = "") -> str | None:
    """/project/<rel> when rel is a file the server will hand out, else None."""
    rel = str(rel or "").replace("\\", "/")
    if rel.split("/", 1)[0] not in SERVED or project_file(root, rel) is None:
        return None
    return f"{base}/project/{rel}"


def video_size(path: Path) -> tuple[int, int] | None:
    key = (str(path), _stamp(path))
    if key not in _VIDEO_SIZE:
        try:
            v = next(s for s in probe(path).get("streams") or [] if s.get("codec_type") == "video")
            _VIDEO_SIZE[key] = (int(v["width"]), int(v["height"]))
        except (RuntimeError, StopIteration, KeyError, ValueError):
            _VIDEO_SIZE[key] = None
    return _VIDEO_SIZE[key]


# ------------------------------------------------------------------ the film as an editor shows it
class Film:
    """A parsed project (current or a history snapshot) with its schedule: tracks top to bottom in film seconds,
    timed exactly as resolve places them (frames from the schedule's spans)."""

    def __init__(self, root: Path, raw: dict, base: str = ""):
        self.root, self.raw, self.base = root, raw, base
        self.doc = D.parse(raw)
        self.profile = D.profile_of(root, self.doc)
        try:
            self.locale = D.locale_of(root, self.doc)
        except ValueError:
            self.locale = locales.DEFAULT_LOCALE
        self.fps = float(self.profile.fps)
        self.voice, _ = D.load_voice(root, self.doc.voice)
        self.sched = D.schedule(self.doc, self.voice)
        self.end = self.sched.film_end()           # TimeError: the film has no length
        self.frames = max(1, T.to_frame(self.end, self.fps))
        self._words: dict | None = None

    @property
    def duration(self) -> float:
        return _sec(self.frames, self.fps)

    @property
    def words(self) -> dict:
        if self._words is None:
            texts = [t for tr in self.doc.tracks if tr.kind == "captions" for t in RS.caption_texts(self.voice, tr)]
            build = self.root / "build"
            self._words = RS.word_breaks(texts, build if build.is_dir() else None, self.locale) if texts else {}
        return self._words

    def span(self, c) -> tuple[int, int] | None:
        """(from, to) in frames, as resolve.span places the clip; None when it cannot be timed."""
        try:
            a, b = self.sched.span(c.id)
        except T.TimeError:
            return None
        fa, fb = T.to_frame(a, self.fps), T.to_frame(b, self.fps)
        return (fa, fb) if fb > fa else None

    def box_px(self, value) -> dict | str:
        if value is None or value == "full":
            return "full"
        if value == "safe":
            s = self.profile.safe
            return {"x": s.x, "y": s.y, "w": s.w, "h": s.h}
        return D._ints({"x": value.x, "y": value.y, "w": value.w, "h": value.h})

    def raw_clips(self) -> dict[str, dict]:
        return {c.get("id"): c for t in self.raw.get("tracks") or [] if isinstance(t, dict)
                for c in t.get("clips") or [] if isinstance(c, dict)}

    def tracks(self) -> list[dict]:
        """Top to bottom: captions tracks, then visual tracks topmost first, then audio tracks in project order."""
        raw = self.raw_clips()
        order = [t for t in reversed(self.doc.tracks) if t.kind == "captions"] + \
            [t for t in reversed(self.doc.tracks) if t.kind == "visual"] + \
            [t for t in self.doc.tracks if t.kind == "audio"]
        out = []
        for t in order:
            row = {"id": t.id, "kind": t.kind, "hidden": t.hidden, "clips": []}
            if t.kind == "captions":
                row["items"] = self.caption_items(t)
            else:
                clips = [c for c in (self.clip(c, raw.get(c.id) or {}) for c in t.clips)]
                row["clips"] = sorted(clips, key=lambda c: (c["start"] is None, c["start"] or 0))
            out.append(row)
        return out

    def caption_items(self, t) -> list[dict]:
        t = RS.caption_track(t, self.locale)
        if t.items is None and t.source != "voice":
            items = RS.transcript_items(self.root, self.doc, t, self.sched, self.fps)
        elif t.items is None and self.voice:
            items = RS._voice_items(self.voice, t, self.fps, self.words)
        else:
            items = RS.caption_items(t, self.voice, self.sched, self.fps)
        return [{"start": _sec(it["from"], self.fps), "end": _sec(it["to"], self.fps),
                 "text": "".join(r["text"] for r in it["runs"]), "line": it.get("line")} for it in items]

    def label(self, c) -> str:
        if c.type == "text":
            return " ".join(RS._plain(c.text)[0].split())
        if c.type == "component":
            return c.name
        if c.type == "shape":
            return c.shape
        return c.asset

    def keyframes(self, c, span: tuple[int, int] | None) -> dict[str, list[float]]:
        if span is None:
            return {}
        start, dur = span[0], span[1] - span[0]
        out: dict[str, list[float]] = {}
        motion = getattr(c, "motion", None)
        if motion:
            for prop in RS.motion_keyframes(motion, dur / self.fps, 100, 100):
                out[prop] = [_sec(start, self.fps), _sec(start + max(1, dur - 1), self.fps)]
        for prop, keys in c.keyframes.items():
            times = []
            for k in keys:
                try:
                    times.append(_sec(start + T.clip_frame(k.t, start, self.fps, self.sched), self.fps))
                except T.TimeError:
                    pass
            if times:
                out[prop] = sorted(times)
        return out

    def clip(self, c, raw: dict) -> dict:
        span = self.span(c)
        asset = getattr(c, "asset", None)
        a = self.doc.assets.get(asset) if asset else None
        cut = getattr(c, "transition", None)
        written_end = raw.get("end") if raw.get("end") is not None else (f"dur {c.dur:g}" if c.dur else None)
        thumb = f"{self.base}/api/thumb?asset={asset}" if a is not None and a.kind in ("image", "video", "evidence") \
            else None
        return {
            "id": c.id, "type": c.type,
            "start": _sec(span[0], self.fps) if span else None, "end": _sec(span[1], self.fps) if span else None,
            "label": self.label(c),
            "written": {"start": str(raw.get("start", c.start)), "end": None if written_end is None else str(written_end)},
            "asset": asset, "asset_kind": a.kind if a is not None else None, "thumb": thumb,
            "transition": {"type": cut.type, "dur": cut.dur} if cut is not None else None,
            "enter": _move(getattr(c, "enter", None)), "exit": _move(getattr(c, "exit", None)),
            "keyframes": self.keyframes(c, span),
            "rate": getattr(c, "rate", None), "reverse": bool(getattr(c, "reverse", False)),
            "hold": getattr(c, "hold", None), "volume": getattr(c, "volume", None),
            "loop": bool(getattr(c, "loop", False)),
            "box": None if c.type == "audio" else self.box_px(c.box),
            "raw": raw,
        }

    def at(self, value) -> float | None:
        try:
            return round(T.resolve(value, self.sched), _ROUND)
        except T.TimeError:
            return None


def _move(t) -> dict | None:
    return {"preset": t.preset, "dur": t.dur} if t is not None else None


# ------------------------------------------------------------------ the parts around the timeline
def assets_of(root: Path, doc: D.Document, base: str) -> list[dict]:
    out = []
    for aid, a in doc.assets.items():
        path = project_file(root, a.path)
        row = {"id": aid, "kind": a.kind, "path": a.path, "url": project_url(root, a.path, base),
               "width": None, "height": None, "duration": None, "missing": path is None or not path.is_file()}
        if not row["missing"]:
            if a.kind in ("image", "evidence"):
                size = RS.image_size(path)
            elif a.kind == "video":
                size = video_size(path)
            else:
                size = None
            if size:
                row["width"], row["height"] = size
            if a.kind in ("video", "audio"):
                d = RS.media_duration(path)
                row["duration"] = round(d, _ROUND) if d else None
        row["used_by"] = [c.id for _, c in D.clips_of(doc) if getattr(c, "asset", None) == aid
                          or (c.type == "component" and any(k == "asset" and v == aid
                                                            for _, k, v in D.prop_refs(c.props)))]
        out.append(row)
    return out


def _issue(level: str, where: str, msg: str, source: str, film: Film | None, t: float | None = None) -> dict:
    clip = None
    m = _CLIP_WHERE.match(where or "")
    known = film.raw_clips() if film is not None else {}
    if m and m.group("id") in known:
        clip = m.group("id")
        if t is None and m.group("t"):
            t = float(m.group("t"))
        if t is None and film is not None:
            model = next((c for _, c in D.clips_of(film.doc) if c.id == clip), None)
            span = film.span(model) if model is not None else None
            t = _sec(span[0], film.fps) if span else None
    return {"level": level, "source": source, "clip": clip, "t": t, "text": f"{where}: {msg}" if where else msg}


def _row_issue(row: str, source: str, film: Film | None) -> dict:
    m = _LAYOUT_ROW.match(str(row))
    if not m:
        return {"level": "warning", "source": source, "clip": None, "t": None, "text": str(row)}
    t = float(m.group("t")) if m.group("t") else None
    where = m.group("where") + (f" @ {m.group('t')}s" if t is not None else "")
    issue = _issue(m.group("level"), m.group("where"), m.group("msg"), source, film, t)
    issue["text"] = f"{where}: {m.group('msg')}"
    return issue


def issues_of(root: Path, film: Film | None, cut: str | None) -> list[dict]:
    rows = [_issue(i.level, i.where, i.msg, "check", film) for i in check_project(root)]
    rep = _read_json(root / "build" / "report.json")
    if isinstance(rep, dict) and cut and (rep.get("inputs") or {}).get("cut") == cut:
        rows += [_row_issue(r, "layout", film) for r in rep.get("layout") or []]
        rows += [{"level": "error", "source": "film", "clip": None, "t": None, "text": str(p)}
                 for p in (rep.get("film_check") or {}).get("problems") or []]
    return rows


def render_of(root: Path, base: str, cut: str | None) -> dict:
    from ..tools import _render_text
    out: dict = {"delivered": None, "draft": None, "last": None}
    film = root / "out" / "film.mp4"
    if film.is_file():
        rep = _read_json(root / "out" / "report.json") or {}
        fc = rep.get("film_check") or {}
        made = (rep.get("inputs") or {}).get("cut")
        st = film.stat()
        out["delivered"] = {"url": f"{base}/project/out/film.mp4", "at": _iso(st.st_mtime),
                            "duration": fc.get("duration_s"), "lufs": fc.get("lufs"), "bytes": st.st_size,
                            "matches_cut": (made == cut) if made and cut else None}
    draft = root / "build" / "draft.mp4"
    if draft.is_file():
        out["draft"] = {"url": f"{base}/project/build/draft.mp4", "at": _iso(draft.stat().st_mtime)}
    path = root / "build" / "report.json"
    rep = _read_json(path)
    if isinstance(rep, dict):
        out["last"] = {"at": _iso(path.stat().st_mtime), "ok": bool(rep.get("ok")), "stage": rep.get("stage"),
                       "text": str(_render_text(rep)).split("\n", 1)[0]}
    return out


def spend_of(root: Path) -> dict | None:
    try:
        from ..providers.config import context
        ctx = context(root)
        return {"project_usd": ctx.ledger().spent(ctx.project_key), "budget_usd": ctx.budget.get("per_project_usd")}
    except Exception:  # noqa: BLE001 - spend is a side panel; a bad workspace config shows as no spend
        return None


def activity_of(root: Path, limit: int = ACTIVITY_SHOWN) -> list[dict]:
    path = root / ".history" / ACTIVITY
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=limit)
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def history_of(root: Path) -> list[dict]:
    """Recorded batches that still have their snapshot, oldest first; a number reused after an undo shows its latest
    batch."""
    from ..ops import snapshots
    have = {n for n, _ in snapshots(root)}
    rows: dict[int, dict] = {}
    try:
        lines = (root / ".history" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
            n = int(row["n"])
        except (ValueError, KeyError, TypeError):
            continue
        if n in have:
            rows[n] = {"n": n, "at": row.get("at"), "summary": str(row.get("summary") or "")}
    return [rows[n] for n in sorted(rows)]


def history_cut(root: Path, n: int) -> tuple[dict, dict] | None:
    """(log row, project.json as it was right after batch n); n=0 is the cut before the first recorded batch."""
    from ..ops import snapshots
    files = dict(snapshots(root))
    rows = {r["n"]: r for r in history_of(root)}
    if n == 0 and files:
        first = min(files)
        return {"n": 0, "at": None, "summary": "before the first recorded edit"}, _read_json(files[first])
    if n not in rows:
        return None
    later = [k for k in files if k > n]
    data = _read_json(files[min(later)]) if later else _read_json(root / D.PROJECT_FILE)
    return rows[n], data


def history_state(root: Path, n: int, base: str = "") -> dict | None:
    got = history_cut(root, n)
    if got is None:
        return None
    row, data = got
    out = {"n": row["n"], "at": row["at"], "summary": row["summary"], "duration": None, "tracks": [], "error": None}
    try:
        film = Film(root, data, base)
        out.update(duration=film.duration, tracks=film.tracks())
    except Exception as exc:  # noqa: BLE001 - an old snapshot may not fit today's format
        out["error"] = _error_text(exc)
    return out


# ------------------------------------------------------------------ the whole state
def _error_text(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "no project.json"
    if isinstance(exc, json.JSONDecodeError):
        return f"project.json is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})"
    if isinstance(exc, D.DocumentError):
        return "project.json does not fit the format: " + "; ".join(str(i) for i in exc.issues[:5])
    if isinstance(exc, T.TimeError):
        return f"the film's length: {exc}"
    return f"{type(exc).__name__}: {exc}"


def digest(state: dict) -> str:
    body = {k: v for k, v in state.items() if k != "revision"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def build_state(root: str | Path, base: str = "") -> dict:
    """The /api/state document. A project that does not load or resolve still gives one: valid false, the error,
    and what could be read."""
    root = Path(root).resolve()
    try:
        ws = find_workspace(root)
    except WorkspaceError:
        ws = None
    raw = _read_json(root / D.PROJECT_FILE)
    meta = (raw or {}).get("meta") if isinstance(raw, dict) else None
    state: dict = {
        "revision": "",
        "project": {"name": root.name, "path": root.as_posix(),
                    "title": (meta or {}).get("title") if isinstance(meta, dict) else None,
                    "workspace": ws.root.as_posix() if ws else None},
        "canvas": None, "duration": None, "frames": None, "valid": False, "error": None, "voice": None,
        "tracks": [], "markers": [], "chapters": [], "assets": [], "issues": [],
    }
    film = None
    try:
        film = Film(root, D.read_raw(root), base)
        state["valid"] = True
    except Exception as exc:  # noqa: BLE001 - the window shows why instead of failing
        state["error"] = _error_text(exc)
    try:
        profile = film.profile if film else profile_for(root, ws)
        s = profile.safe
        state["canvas"] = {"profile": profile.name, "width": profile.width, "height": profile.height,
                           "fps": profile.fps, "safe": {"x": s.x, "y": s.y, "w": s.w, "h": s.h},
                           "locale": film.locale if film else (raw or {}).get("locale") or locales.DEFAULT_LOCALE}
    except (ValueError, WorkspaceError):
        pass
    if film is not None:
        doc = film.doc
        state.update(duration=film.duration, frames=film.frames, tracks=film.tracks(),
                     markers=[{"id": k, "t": film.at(v)} for k, v in doc.markers.items()],
                     chapters=[{"t": film.at(ch.at), "title": ch.title} for ch in doc.chapters],
                     assets=assets_of(root, doc, base))
        if film.voice is not None:
            v = film.voice
            state["voice"] = {"asset": "voice", "duration": round(v.duration, _ROUND),
                              "url": project_url(root, v.audio_rel, base) if v.audio_rel else None,
                              "lines": [{"i": ln.i, "text": ln.text, "start": ln.t0, "end": ln.t1} for ln in v.lines]}
    from ..render import film_inputs
    cut = film_inputs(root).get("cut")
    state["issues"] = issues_of(root, film, cut)
    if not state["valid"] and state["error"] is None:
        state["error"] = "project.json cannot be read"
    state["render"] = render_of(root, base, cut)
    state["spend"] = spend_of(root)
    state["activity"] = activity_of(root)
    state["history"] = history_of(root)
    state["revision"] = digest(state)
    return state


def watched(root: Path) -> list[Path]:
    """The files whose change can change the state (the events stream polls these)."""
    try:
        ws = find_workspace(root)
    except WorkspaceError:
        ws = None
    files = [root / D.PROJECT_FILE, root / "voice" / "voice.json", root / "voice", root / "assets",
             root / ".history", root / ".history" / "log.jsonl", root / ".history" / ACTIVITY,
             root / "build" / "report.json", root / "out" / "report.json", root / "out" / "film.mp4",
             root / "build" / "draft.mp4", root / "ledger.jsonl"]
    if ws is not None:
        files += [ws.ledger_path, ws.root / "workspace.json", ws.root / "rules.json", ws.components_dir]
    return files


def signature(root: Path) -> tuple:
    return tuple(_stamp(p) for p in watched(root))


class StateCache:
    """build_state, rebuilt only when a watched file changed."""

    def __init__(self, root: Path, base: str = ""):
        self.root, self.base = Path(root).resolve(), base
        self._lock = threading.Lock()
        self._sig: tuple | None = None
        self._state: dict | None = None

    def get(self) -> dict:
        with self._lock:
            sig = signature(self.root)
            if self._state is None or sig != self._sig:
                self._state = build_state(self.root, self.base)
                self._sig = sig
            return self._state
