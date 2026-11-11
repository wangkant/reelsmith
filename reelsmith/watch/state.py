"""The watch window's state: one JSON document built from a project folder with the engine's own readers (document,
resolve, checks), cached by the mtimes of the files it reads. Nothing here renders or writes the project."""
from __future__ import annotations

import hashlib
import json
import re
import sys
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
from . import presence
from .presence import SERVED

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
            "muted": c.type == "video" and RS._muted(c, a, self.root),
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
               "note": a.note or None, "site": a.site or None,
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
    coded = layout_code(m.group("msg"))
    if coded:
        issue.update(code=coded["code"], params=coded["params"], message=coded["text"])
    return issue


# ------------------------------------------------------------------ strings as codes
# English fallbacks of every code the server composes from known parts; the page translates by code.
TEXTS = {
    "result.none": "No film has been delivered",
    "result.current": "The delivered film matches the current cut",
    "result.stale": "The delivered film predates the current cut",
    "render.refused": "The last render was refused: {error}",
    "render.refused.check": "The last render was refused: the project has errors",
    "render.refused.layout": "The last render was refused: text lies where it cannot be read",
    "render.refused.film_check": "The last render was refused: the film failed its delivery checks",
    "render.refused.component": "The last render was refused: a component failed",
    "render.refused.infra": "The last render was refused: the renderer failed",
    "layout.cut_by_edge": "Text \"{text}\" is cut by the {side} edge of the canvas ({px} px)",
    "layout.outside_safe": "Text \"{text}\" lies {px} px outside the safe area ({side})",
    "layout.text_tiny": "Text \"{text}\" is {px} px high, below the minimum of {min} px",
    "layout.text_small": "Text \"{text}\" is {px} px high, below the recommended {min} px",
    "layout.overlap": "Text \"{text}\" overlaps {other}",
    "layout.cut_by_card": "Text \"{text}\" is partly hidden by its own card ({share} %)",
    "layout.low_contrast": "Text \"{text}\" has a contrast of {ratio}:1 against its background",
    "layout.overflow_box": "Text \"{text}\" overflows its box by {px} px ({side})",
    "busy.action": "Another action is running",
    "busy.chat": "The agent is working on a request",
    "busy.render": "A render or preview of this project is running",
    "project.invalid": "The project does not load",
    "render.current": "The delivered film already matches the current cut",
    "undo.empty": "There is no change to undo",
    "redo.empty": "There is no undone change to restore",
    "stop.idle": "Nothing is running",
    "stop.pending": "The request is being stopped",
    "stop.unsupported": "A render started from the window cannot be interrupted; it ends by itself",
    "accept.not_current": "Only a delivered film that matches the current cut can be accepted",
    "reveal.no_film": "No film has been delivered",
    "frame.failed": "The frame could not be rendered: {error}",
    "action.unknown": "Unknown action \"{action}\"; use render, check, undo, redo or stop",
    "action.render.ok": "The film was rendered and delivered",
    "action.render.failed": "The render was refused",
    "action.check.ok": "The check found no errors",
    "action.check.failed": "The check found errors",
    "action.undo.ok": "The last change was undone",
    "action.undo.failed": "Nothing was undone",
    "action.redo.ok": "The undone change was restored",
    "action.redo.failed": "Nothing was restored",
    "create.empty": "Enter a name for the film",
    "create.long": "A name can be at most 64 characters long",
    "create.chars": "A name can use only the letters A–Z, digits, hyphens and underscores, and cannot begin with a hyphen",
    "create.reserved": "\"{name}\" is reserved by the operating system",
    "create.taken": "A film named \"{name}\" already exists in this workspace",
    "create.failed": "The film could not be created: {error}",
    "owner.elsewhere": "This film is open in another window ({url}). Requests and actions are available only there "
                       "until that window is closed.",
}
STAGES = {"check": ("stage.check", "checking the project"), "layout": ("stage.layout", "measuring layout"),
          "film": ("stage.film", "rendering frames"), "master": ("stage.master", "mastering loudness"),
          "film check": ("stage.film_check", "checking the film"), "sweep": ("stage.sweep", "measuring the whole film"),
          "stills": ("stage.stills", "rendering stills")}
VERBS = {"render": "rendering the film", "preview": "rendering stills", "check": "checking the project",
         "edit": "editing the cut", "undo": "undoing the last change", "redo": "restoring the undone change",
         "review": "reviewing the film", "speak": "recording the narration", "draw": "generating a picture",
         "animate": "animating a picture", "capture": "capturing a web page", "transcribe": "transcribing audio",
         "import_asset": "importing an asset", "frames": "extracting frames", "scenes": "finding scene changes",
         "silences": "finding silences", "typecheck": "checking the components", "new_project": "creating the project",
         "export_captions": "exporting the captions", "probe": "inspecting a file", "note": "recording a note"}


def say(code: str, english: str | None = None, /, **params) -> dict:
    """{"code", "params", "text"}: the English is TEXTS[code] filled in, unless given."""
    return {"code": code, "params": params, "text": english if english is not None else TEXTS[code].format(**params)}


def running_view(row: dict | None, by: str) -> dict | None:
    """presence.running's row with what it means: by "window" (an action of this window), "chat" (its agent) or
    "agent" (any other caller); a code, its parameters and the English sentence."""
    if row is None:
        return None
    tool = str(row.get("tool") or "")
    verb = VERBS.get(tool, f"running {tool}")
    stage = STAGES.get(row.get("stage") or "")
    pct = None if row.get("progress") is None else round(row["progress"] * 100)
    text = verb[0].upper() + verb[1:] if by == "window" else f"The agent is {verb}"
    if stage:
        text += f": {stage[1]}"
    if pct is not None:
        text += f" ({pct} %)"
    params = {"tool": tool, "by": by, "stage": stage[0] if stage else None, "percent": pct}
    return {**row, "by": by, "code": f"running.{tool}" if tool in VERBS else "running.tool",
            "stage_code": params["stage"], "percent": pct, "params": params, "text": text}


_QUOTE = r'^text(?: "(?P<text>.*?)")? '
_ALSO = re.compile(r"\(also at ([^)]*)\)")
_LAYOUT_CODES = (
    ("layout.cut_by_edge", re.compile(_QUOTE + r"is cut by the canvas edge \((?P<side>\w+), (?P<px>\d+) px\)", re.S)),
    ("layout.outside_safe", re.compile(_QUOTE + r"sits (?P<px>\d+) px outside the safe area \((?P<side>\w+)\)", re.S)),
    ("layout.text_size", re.compile(_QUOTE + r"is (?P<px>[\d.]+) px.*?: under (?P<min>[\d.]+) px is hard to read",
                                    re.S)),
    ("layout.cut_by_card", re.compile(_QUOTE + r"is cut by its own card: (?P<share>\d+)% of it", re.S)),
    ("layout.low_contrast", re.compile(_QUOTE + r"\((?P<color>[^)]*)\) on a background of about (?P<bg>\S+) has "
                                                r"contrast (?P<ratio>[\d.]+):1", re.S)),
    ("layout.overflow_box", re.compile(_QUOTE + r"overflows its clip box by (?P<px>\d+) px \((?P<side>\w+)\)", re.S)),
    ("layout.overlap", re.compile(_QUOTE + r"overlaps (?P<other>.+?)(?: \(also at [^)]*\))?: move one", re.S)),
)


def layout_code(msg: str) -> dict | None:
    """A layout row's message (checks._layout_issue) as a code with its parameters; None for any other text."""
    for code, pattern in _LAYOUT_CODES:
        m = pattern.match(msg)
        if not m:
            continue
        params = {k: v for k, v in m.groupdict().items()}
        params["text"] = params.get("text") or ""
        for key in ("px", "min", "share", "ratio"):
            if params.get(key) is not None:
                params[key] = float(params[key]) if "." in params[key] else int(params[key])
        if code == "layout.text_size":
            code = "layout.text_tiny" if "render refuses" in msg else "layout.text_small"
        also = _ALSO.search(msg)
        params["also"] = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)s", also.group(1))] if also else []
        return say(code, **params)
    return None


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


def spend_of(root: Path) -> dict:
    """The project's provider spend and the chat's model spend, each against its own budget (null when unknown)."""
    from .. import runner
    out = {"project_usd": None, "project_budget_usd": None, "chat_usd": None, "chat_budget_usd": None}
    try:
        from ..providers.config import context
        ctx = context(root)
        out.update(project_usd=ctx.ledger().spent(ctx.project_key),
                   project_budget_usd=ctx.budget.get("per_project_usd"))
    except Exception:  # noqa: BLE001 - spend is a side panel; a bad workspace config shows as no spend
        pass
    chat = runner.read_json(root / runner.CHAT_STATE_FILE, {}) or {}
    out["chat_usd"] = round(float(chat.get("cost_usd") or 0), 4)
    try:
        out["chat_budget_usd"] = runner.settings_for(find_workspace(root)).budget_usd
    except WorkspaceError:
        pass
    return out


def result_of(root: Path, render: dict, cut: str | None, film: Film | None, base: str = "") -> dict:
    """The film's standing: none, current, stale (delivered from another cut) or refused (the last render of this
    cut stopped), with the reason as a code."""
    delivered = render["delivered"]
    out = {"state": "none", "reason_code": "result.none", "params": {}, "reason": TEXTS["result.none"], "stage": None,
           "t": None, "clip": None, "beat": None, "film": delivered, "frame": None, "accepted": None}
    path = root / "build" / "report.json"
    rep = _read_json(path)
    film_mtime = (root / "out" / "film.mp4").stat().st_mtime if delivered else 0
    if (isinstance(rep, dict) and not rep.get("ok") and cut and (rep.get("inputs") or {}).get("cut") == cut
            and path.stat().st_mtime >= film_mtime):
        stage = str(rep.get("stage") or "")
        coded = None
        if stage == "layout":
            rows = [_row_issue(r, "layout", film) for r in rep.get("layout") or []]
            first = next((r for r in rows if r["level"] == "error"), rows[0] if rows else None)
            if first is not None:
                out.update(t=first["t"], clip=first["clip"])
                coded = say(first["code"], **first["params"]) if first.get("code") else None
        key = f"render.refused.{stage.replace(' ', '_')}"
        coded = coded or (say(key) if key in TEXTS else say("render.refused", error=str(rep.get("error") or "")))
        out.update(state="refused", stage=stage, reason_code=coded["code"], params=coded["params"],
                   reason=coded["text"])
        for shot in rep.get("layout_frames") or []:
            rel = str(shot).replace("\\", "/")
            rel = "build/" + rel.split("/build/", 1)[1] if "/build/" in rel else rel
            out["frame"] = project_url(root, rel, base)
            break
    elif delivered:
        current = delivered.get("matches_cut") is True
        code = "result.current" if current else "result.stale"
        out.update(state="current" if current else "stale", reason_code=code, reason=TEXTS[code])
        mark = _read_json(root / "out" / "accepted.json")
        if current and isinstance(mark, dict) and mark.get("cut") == cut:
            out["accepted"] = {"at": mark.get("at")}
    return out


def summary_of(state: dict) -> dict:
    """A few facts at a glance, from the state itself."""
    tracks = state["tracks"]
    clips = [c for t in tracks for c in t["clips"]]
    voice = state["voice"]
    narrated = sum(max(0.0, ln["end"] - ln["start"]) for ln in voice["lines"]) if voice else 0.0
    covered = None
    if state["duration"]:
        spans = sorted((max(0.0, c["start"]), min(state["duration"], c["end"])) for t in tracks
                       if t["kind"] == "visual" and not t["hidden"] for c in t["clips"]
                       if c["start"] is not None and c["end"] is not None)
        total, reach = 0.0, 0.0
        for a, b in spans:
            a = max(a, reach)
            if b > a:
                total, reach = total + b - a, b
        covered = round(min(1.0, total / state["duration"]), 3)
    levels = [i["level"] for i in state["issues"]]
    return {"clips": len(clips), "tracks": len(tracks), "narrated_s": round(narrated, 1), "covered": covered,
            "errors": levels.count("error"), "warnings": levels.count("warning"), "batches": len(state["history"])}


# ------------------------------------------------------------------ beats: the film told line by line
EPS = 0.05                          # an overlap shorter than this does not carry a clip into the next beat
PAUSE_S = 0.3                       # without narration: a caption pause this long, or a cut this near, ends a beat
GROUP_S = 8.0                       # and a caption group this long ends at its next phrase
PRESETS = {   # built-in components: (kind, name code, English name)
    "StoryBeats": ("card", "card.steps", "Step-by-step card"),
    "CountUp": ("figure", "figure.count", "Large figure"),
    "BarCompare": ("figure", "figure.bars", "Bar chart"),
    "DotGrid": ("figure", "figure.dots", "Dot grid"),
    "Versus": ("card", "card.versus", "Comparison"),
    "Seesaw": ("card", "card.seesaw", "Gains and losses"),
    "Receipt": ("card", "card.receipt", "Itemised receipt"),
    "QuoteCard": ("card", "card.quote", "Quotation card"),
    "NewsBrief": ("card", "card.news", "News summary card"),
    "Parties": ("card", "card.parties", "Parties diagram"),
    "TimelineRule": ("card", "card.timeline", "Timeline"),
    "Stamp": ("card", "card.stamp", "Verdict stamp"),
    "EvidenceCard": ("evidence", "evidence.card", "Evidence card"),
    "Arrow": ("shape", "shape.arrow", "Arrow"),
    "Highlighter": ("shape", "shape.highlight", "Highlight stroke"),
}
SHAPES = {"ellipse": ("shape.circle", "Circle mark"), "line": ("shape.line", "Line"), "arrow": ("shape.arrow", "Arrow"),
          "path": ("shape.path", "Drawn mark")}
SHOTS = {"shot.footage": "Footage", "shot.still": "Still image", "shot.inset": "Inset picture"}
SOUNDS = {"sound.bed": "Sound bed", "sound.effect": "Sound effect"}
MOTIONS = {"push": "slow push-in", "pull": "slow pull-out", "pan_left": "pan left", "pan_right": "pan right",
           "rise": "rise"}
_READABLE = ("title", "header", "headline", "quote", "who", "role", "name", "when", "text", "label", "display",
             "source", "date", "label_lit", "label_rest")
_SENTENCE_END = tuple(".?!。？！…")


def element_name(c: dict, canvas: dict | None) -> tuple[str, str, str]:
    """(kind, name code, English name) of a visual clip that is not a picture."""
    raw = c["raw"]
    if c["type"] == "component":
        return PRESETS.get(c["label"]) or ("component", "component.custom", c["label"])
    if c["type"] == "evidence":
        return "evidence", "evidence.card", "Evidence card"
    if c["type"] == "shape":
        shape = raw.get("shape") or "rect"
        if shape == "rect":
            return ("shape", "shape.plate", "Backing plate") if raw.get("fill") else ("shape", "shape.frame", "Frame")
        return ("shape", *SHAPES.get(shape, ("shape.path", "Drawn mark")))
    size = (raw.get("style") or {}).get("size") if isinstance(raw.get("style"), dict) else None
    big = size == "fit" or (isinstance(size, (int, float)) and canvas and size >= 0.06 * canvas["height"])
    return ("title", "text.title", "Title") if big else ("text", "text.overlay", "Overlay text")


def _props_words(value) -> list[str]:
    """What a person reads in a component's props, in their order (lists of bare values are positions or word
    lists to highlight, not words to read)."""
    if isinstance(value, dict):
        own = [value[k].strip() for k in _READABLE if isinstance(value.get(k), str) and value[k].strip()]
        if isinstance(value.get("value"), (int, float, str)) and not isinstance(value["value"], bool):
            figure = f"{value.get('prefix') or ''}{value['value']}{value.get('suffix') or ''}"
            # a figure with its unit leads ("¥5 gross margin"); a row's value follows its label ("Tea ¥2.5")
            own = [figure, *own] if value.get("prefix") or value.get("suffix") else [*own, figure]
        rest = [w for v in value.values() if isinstance(v, (dict, list)) for w in _props_words(v)]
        return ([" ".join(own)] if own else []) + rest
    if isinstance(value, list):
        return [w for v in value if isinstance(v, (dict, list)) for w in _props_words(v)][:12]
    return []


def _one_line(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def element_summary(c: dict, assets: dict) -> str | None:
    if c["type"] == "text":
        return _one_line(c["label"]) or None
    if c["type"] == "component":
        words = _props_words(c["raw"].get("props") or {})
        return _one_line(" · ".join(w for w in words if w)) or None
    if c["type"] == "evidence":
        a = assets.get(c["asset"]) or {}
        return _one_line(a.get("note") or a.get("site") or c["asset"]) or None
    return None


def picture_subject(note: str) -> str | None:
    """A short subject from an asset's note (often a generation prompt): its first clause."""
    note = re.sub(r"^from [\w.-]+:\s*", "", str(note or "").strip())
    first = re.split(r"[.,;:|。，；：]", note, maxsplit=1)[0].strip()
    return _one_line(first, 60) or None


def shot_notes(c: dict) -> list[dict]:
    raw, out = c["raw"], []
    rate = c.get("rate")
    if isinstance(rate, (int, float)) and rate != 1:
        out.append(say("shot.speed", f"{rate:g}x speed", rate=rate))
    if c.get("reverse"):
        out.append(say("shot.reversed", "reversed"))
    if c.get("hold") is not None:
        out.append(say("shot.held", "held frame"))
    if c.get("loop"):
        out.append(say("shot.looped", "looped"))
    if c.get("transition"):
        kind = c["transition"]["type"]
        out.append(say("shot.transition_in", f"{kind.replace('_', ' ')} in", type=kind))
    if raw.get("motion") in MOTIONS:
        out.append(say("shot.motion", MOTIONS[raw["motion"]], motion=raw["motion"]))
    return out


def _source_t(c: dict, at: float) -> float:
    """The asset second a video clip shows at film second `at` (thumbnails only: loops and reverse are ignored)."""
    if c.get("hold") is not None:
        return float(c["hold"])
    rate = c.get("rate") or 1.0
    return round(float(c["raw"].get("trim_in") or 0) + max(0.0, at - c["start"]) * rate, 2)


def beat_windows(state: dict) -> list[dict]:
    """[{start, end, line, line_i, kind}]: one per voice line (to the next line's start; the first from 0, the last
    to the end); without narration one per caption phrase group, else one per full-frame shot."""
    end = state["duration"]
    if not end:
        return []
    voice = state["voice"]
    if voice and voice["lines"]:
        lines = sorted((ln for ln in voice["lines"] if ln["start"] < end), key=lambda ln: ln["start"])
        starts = [0.0] + [ln["start"] for ln in lines[1:]]
        return [{"start": round(a, _ROUND), "end": round(b, _ROUND), "line": ln["text"], "line_i": ln["i"],
                 "kind": "line"} for ln, a, b in zip(lines, starts, starts[1:] + [end])]
    starts, cuts = [], []
    for c in sorted(_visible(state, ("image", "video")), key=lambda c: c["start"]):
        if c["box"] == "full" and (not cuts or c["start"] - cuts[-1] > EPS):
            cuts.append(c["start"])
    phrases = _phrases(state)
    if phrases:
        # a group of phrases ends at a pause, a sentence's end, a cut to another shot since the last phrase began,
        # or once GROUP_S long
        prev = None
        for p in phrases:
            if (prev is None or p["start"] - prev["end"] > PAUSE_S or prev["text"].rstrip().endswith(_SENTENCE_END)
                    or any(prev["start"] + PAUSE_S < cut <= p["start"] + PAUSE_S for cut in cuts)
                    or p["start"] - starts[-1] >= GROUP_S):
                starts.append(p["start"])
            prev = p
        kind = "phrase"
    else:
        starts, kind = cuts, "shot"
    starts = [0.0] + [s for s in starts if EPS < s < end] if starts else [0.0]
    return [{"start": round(a, _ROUND), "end": round(b, _ROUND), "line": None, "line_i": None, "kind": kind}
            for a, b in zip(starts, starts[1:] + [end])]


def _phrases(state: dict) -> list[dict]:
    cap = next((t for t in state["tracks"] if t["kind"] == "captions" and not t["hidden"]), None)
    return [i for i in (cap or {}).get("items") or [] if i["end"] > i["start"]]


def _visible(state: dict, types: tuple) -> list[dict]:
    return [c for t in state["tracks"] if t["kind"] != "captions" and not t["hidden"] for c in t["clips"]
            if c["type"] in types and c["start"] is not None and c["end"] is not None]


def _home(windows: list[dict], t: float) -> int:
    for i, w in enumerate(windows):
        if t < w["end"]:
            return i
    return len(windows) - 1


def _spread(windows: list[dict], start: float, end: float) -> list[tuple[int, bool]]:
    """(window index, continues) for a span: its home window, then every later one it reaches into."""
    home = _home(windows, start)
    out = [(home, False)]
    for i in range(home + 1, len(windows)):
        if end - windows[i]["start"] <= EPS:
            break
        out.append((i, True))
    return out


def beats_of(state: dict, base: str = "") -> list[dict]:
    windows = beat_windows(state)
    if not windows:
        return []
    beats = [{"n": i + 1, "start": w["start"], "end": w["end"], "line": w["line"], "line_i": w["line_i"],
              "kind": w["kind"], "phrases": [], "shots": [], "elements": [], "sound": [], "issues": [],
              "changed": False, "frame": f"{base}/api/frame?t={round((w['start'] + w['end']) / 2, 3):g}&h=180"}
             for i, w in enumerate(windows)]
    by_line = {w["line_i"]: i for i, w in enumerate(windows) if w["line_i"] is not None}
    for p in _phrases(state):
        i = by_line.get(p.get("line"), _home(windows, p["start"]))      # a phrase belongs to its own line's beat
        beats[i]["phrases"].append({"start": p["start"], "end": p["end"], "text": p["text"]})
    assets = {a["id"]: a for a in state["assets"]}
    canvas = state["canvas"]
    for c in sorted(_visible(state, ("image", "video", "text", "shape", "evidence", "component", "audio")),
                    key=lambda c: (c["start"], c["end"])):
        if c["type"] in ("image", "video"):
            code = "shot.inset" if c["box"] != "full" else "shot.footage" if c["type"] == "video" else "shot.still"
            notes = shot_notes(c)
            row = {"clip": c["id"], "asset": c["asset"], "start": c["start"], "end": c["end"], "name_code": code,
                   "name": SHOTS[code], "subject": picture_subject((assets.get(c["asset"]) or {}).get("note")),
                   "notes": [n["text"] for n in notes], "note_codes": [{k: n[k] for k in ("code", "params")}
                                                                       for n in notes]}
            group = "shots"
        elif c["type"] == "audio":
            long = c.get("loop") or (c["end"] - c["start"]) >= 0.5 * state["duration"]
            code = "sound.bed" if long else "sound.effect"
            row = {"clip": c["id"], "asset": c["asset"], "start": c["start"], "end": c["end"], "name_code": code,
                   "name": SOUNDS[code]}
            group = "sound"
        else:
            kind, code, name = element_name(c, canvas)
            row = {"clip": c["id"], "kind": kind, "name_code": code, "name": name,
                   "summary": element_summary(c, assets), "start": c["start"], "end": c["end"]}
            group = "elements"
        for i, cont in _spread(windows, max(0.0, c["start"]), c["end"]):
            item = dict(row, continues=cont)
            if group == "shots":
                mid = (max(c["start"], windows[i]["start"]) + min(c["end"], windows[i]["end"])) / 2
                item["thumb"] = None if c["thumb"] is None else c["thumb"] + (
                    f"&t={_source_t(c, mid):g}" if c["type"] == "video" else "")
            beats[i][group].append(item)
    for k, issue in enumerate(state["issues"]):
        issue["beat"] = n = beat_of(beats, issue.get("clip"), issue.get("t"))
        if n is not None:
            beats[n - 1]["issues"].append(k)
    return beats


def beat_of(beats: list[dict], clip: str | None, t: float | None) -> int | None:
    """The beat a problem belongs to: of the beats its clip is in, the one at t (times in messages are rounded to
    0.1 s, so a clip's own beats win over a neighbour); else the beat at t."""
    if not beats:
        return None
    mine = [b["n"] for b in beats if clip and any(c["clip"] == clip for g in ("shots", "elements", "sound")
                                                  for c in b[g])]
    at = _home(beats, t) + 1 if t is not None else None
    if mine:
        return at if at in mine else mine[0]
    return at


# ------------------------------------------------------------------ what each batch touched
_TOUCHED: dict[tuple, dict] = {}


def _clip_index(raw) -> tuple[dict, dict]:
    """({clip id: (track id, canonical json)}, {track id: canonical json without its clips})."""
    clips, tracks = {}, {}
    for t in (raw or {}).get("tracks") or [] if isinstance(raw, dict) else []:
        if not isinstance(t, dict):
            continue
        tracks[t.get("id")] = json.dumps({k: v for k, v in t.items() if k != "clips"}, sort_keys=True)
        for c in t.get("clips") or []:
            if isinstance(c, dict):
                clips[c.get("id")] = (t.get("id"), json.dumps(c, sort_keys=True))
    return clips, tracks


def _spans(root: Path, raw, ids: set) -> list[tuple[float, float]]:
    try:
        film = Film(root, raw)
    except Exception:  # noqa: BLE001 - an old snapshot may not fit today's format: no times from it
        return []
    out = []
    for _, c in D.clips_of(film.doc):
        if c.id in ids:
            span = film.span(c)
            if span:
                out.append((_sec(span[0], film.fps), _sec(span[1], film.fps)))
    return out


def batch_changes(root: Path, n: int) -> dict | None:
    """{"clips", "tracks", "spans"} that batch n changed: its snapshot (the cut before it) against the next one (or
    project.json for the last); None once its snapshot is gone."""
    from ..ops import snapshots
    files = dict(snapshots(root))
    if n not in files:
        return None
    later = [k for k in files if k > n]
    after_path = files[min(later)] if later else root / D.PROJECT_FILE
    key = (str(root), n, _stamp(files[n]), str(after_path), _stamp(after_path))
    if key not in _TOUCHED:
        before, after = _read_json(files[n]), _read_json(after_path)
        (bc, bt), (ac, at) = _clip_index(before), _clip_index(after)
        tracks = sorted(str(t) for t in set(bt) | set(at) if bt.get(t) != at.get(t))
        clips = {c for c in set(bc) | set(ac) if bc.get(c) != ac.get(c)}
        clips |= {c for c, (t, _) in list(bc.items()) + list(ac.items()) if str(t) in tracks}
        spans = _spans(root, before, clips) + _spans(root, after, clips) if clips else []
        _TOUCHED[key] = {"clips": sorted(str(c) for c in clips), "tracks": tracks, "spans": spans}
        if len(_TOUCHED) > 2000:
            _TOUCHED.pop(next(iter(_TOUCHED)))
    return _TOUCHED[key]


def touched_beats(windows: list[dict], spans: list[tuple[float, float]]) -> list[int]:
    found = set()
    for a, b in spans:
        found |= {i + 1 for i, _ in _spread(windows, max(0.0, a), max(b, a + EPS))}
    return sorted(found)


def with_touched(activity: list[dict], root: Path, beats: list[dict]) -> int | None:
    """Every row with a batch gains "touched": {"clips", "tracks", "beats"}; the latest batch's beats are marked
    changed. Returns that batch's number."""
    windows = [{"start": b["start"], "end": b["end"]} for b in beats]
    latest = None
    for row in activity:
        n = row.get("batch")
        if not isinstance(n, int) or isinstance(n, bool):
            continue
        got = batch_changes(root, n)
        if got is None:
            row["touched"] = None
            continue
        row["touched"] = {"clips": got["clips"], "tracks": got["tracks"],
                          "beats": touched_beats(windows, got["spans"]) if windows else []}
        latest = row if latest is None or n >= latest["batch"] else latest
    if latest is not None:
        for n in latest["touched"]["beats"]:
            beats[n - 1]["changed"] = True
    return latest["batch"] if latest else None


def tidier(root: Path):
    """text -> text for the window: the project's own path read relative to it, the workspace's and the home folder
    named, keys masked (rows logged before tools masked them, or that name other folders)."""
    from ..providers import config
    try:
        ws = find_workspace(root)
    except WorkspaceError:
        ws = None
    try:
        redact = config.context(root).redact
    except Exception:  # noqa: BLE001 - a workspace whose keys cannot be read: the shape-based masking still runs
        redact = config.redact
    fold = str.lower if sys.platform.startswith("win") else str
    names: dict[str, str] = {}
    for folder, name in ((Path.home(), "~"), (ws.root if ws else None, "<workspace>"), (root, ".")):
        for form in ({str(folder), folder.as_posix(), str(folder).replace("\\", "\\\\")} if folder else ()):
            names[fold(form)] = name
    forms = sorted(names, key=len, reverse=True)
    # a folder followed by a separator, or ending there (not the start of a longer name: projects/sea2)
    pattern = re.compile(f"({'|'.join(re.escape(f) for f in forms)})(?:([\\\\/]+)|(?![\\w.-]))",
                         re.I if fold is str.lower else 0)

    def swap(m: re.Match) -> str:
        name = names[fold(m.group(1))]
        if name == ".":
            return "" if m.group(2) else "."
        return name + ("/" if m.group(2) else "")

    def tidy(text) -> str:
        return redact(pattern.sub(swap, str(text or "")))
    return tidy


def activity_of(root: Path, limit: int = ACTIVITY_SHOWN) -> list[dict]:
    path = root / ".history" / ACTIVITY
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=limit)
    except OSError:
        return []
    tidy = tidier(root)
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            for key in ("summary", "text"):
                if isinstance(row.get(key), str):
                    row[key] = tidy(row[key])
            out.append(row)
    return out


def with_batches(activity: list[dict], history: list[dict], limit: int = ACTIVITY_SHOWN) -> list[dict]:
    """The feed with a row for every recorded batch the activity log does not have (edits made before the log
    existed, or by hand through the Python API), in time order, at most `limit` rows. When the log itself was cut
    to `limit`, only batches newer than its oldest row shown are added."""
    logged = {row.get("batch") for row in activity}
    since = min((str(r.get("ts") or "") for r in activity), default="") if len(activity) >= limit else ""
    extra = [{"ts": h["at"], "tool": "edit", "ok": True, "seconds": None, "summary": h["summary"], "batch": h["n"],
              "files": [], "text": h["summary"]} for h in history
             if h["n"] not in logged and str(h["at"] or "") >= since]
    if not extra:
        return activity
    return sorted(activity + extra, key=lambda row: str(row.get("ts") or ""))[-limit:]


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
    body = {k: v for k, v in state.items() if k not in ("revision", "running")}
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
    state["history"] = history_of(root)
    state["activity"] = with_batches(activity_of(root), state["history"])
    state["beats"] = beats_of(state, base) if film is not None else []
    state["latest_batch"] = with_touched(state["activity"], root, state["beats"])
    state["result"] = result_of(root, state["render"], cut, film, base)
    state["result"]["beat"] = beat_of(state["beats"], state["result"]["clip"], state["result"]["t"])
    state["cut"] = cut
    state["can_undo"] = bool(state["history"])
    state["can_redo"] = (root / ".history" / "redo.json").is_file()
    state["summary"] = summary_of(state)
    # the components draw the picture: an edit to one is a change the window must hear of
    parts = sorted(p for p in ws.components_dir.rglob("*") if p.is_file()) if ws and ws.components_dir.is_dir() else []
    state["library"] = hashlib.sha1("".join(f"{p}|{_stamp(p)}\n" for p in parts).encode()).hexdigest()[:12]
    state["running"] = presence.running(root)          # moves on its own: not part of the revision
    state["revision"] = digest(state)
    return state


def watched(root: Path) -> list[Path]:
    """The files whose change can change the state (the events stream polls these)."""
    try:
        ws = find_workspace(root)
    except WorkspaceError:
        ws = None
    # not the .history folder itself: running.json comes and goes there on every tool call
    files = [root / D.PROJECT_FILE, root / "voice" / "voice.json", root / "voice", root / "assets",
             root / ".history" / "log.jsonl", root / ".history" / ACTIVITY,
             root / "build" / "report.json", root / "out" / "report.json", root / "out" / "film.mp4",
             root / "out" / "accepted.json", root / "build" / "draft.mp4", root / "build" / "chat_state.json",
             root / ".history" / "redo.json", root / "ledger.jsonl"]
    if ws is not None:
        files += [ws.ledger_path, ws.root / "workspace.json", ws.root / "rules.json", ws.components_dir]
        if ws.components_dir.is_dir():     # a component edited in place changes the picture, not the folder
            files += sorted(p for p in ws.components_dir.rglob("*") if p.is_file())
    return files


def signature(root: Path) -> tuple:
    from ..ops import snapshots
    return tuple(_stamp(p) for p in watched(root)) + (tuple(n for n, _ in snapshots(root)),)


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
