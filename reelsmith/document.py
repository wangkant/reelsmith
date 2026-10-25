"""project.json (spec 3): pydantic models, load/save, and validation into Issues.

`load` raises DocumentError (schema problems, with readable paths); `validate` checks everything a schema cannot:
unique ids, references (assets, clips, components, voice lines), Time resolution, cycles, overlaps, files.
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, PlainValidator, Tag, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from . import library, locales
from . import timeexpr as T
from .issues import Issue
from .profiles import THEMES, Profile, choose
from .workspace import BUILTIN_FONTS, PROJECT_FILE, WorkspaceError, find_workspace, project_root

KEYFRAME_PROPS = ("x", "y", "w", "h", "opacity", "rotate", "scale", "blur", "brightness", "zoom", "pan_x", "pan_y",
                  "progress", "volume")
EASES = ("linear", "in", "out", "inOut", "spring", "step")
PRESETS = ("fade", "rise", "drop", "pop", "wipe_left", "wipe_up", "zoom")
CUTS = ("crossfade", "dip_black", "dip_white", "wipe_left", "wipe_right", "wipe_up", "slide_left", "zoom")
SOUNDING = ("video", "audio")       # clip types with a sound of their own
MOTIONS = ("push", "pull", "pan_left", "pan_right", "rise", "still")
BLENDS = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn", "hard-light",
          "soft-light", "difference", "exclusion", "hue", "saturation", "color", "luminosity", "plus-lighter")
CLIP_TYPES = ("image", "video", "text", "shape", "evidence", "component")
TRACK_KINDS = ("visual", "audio", "captions")
ASSET_KINDS = ("image", "video", "audio", "evidence")
THEME_TOKENS = ("paper", "ink", "night", "snow", "accent", "gold", "good", "bad", "muted")
FONTS = BUILTIN_FONTS            # display = Smiley Sans; zcool = ZCOOL QingKe HuangYou; workspace fonts add more
ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
OFFSET_LIKE = re.compile(r"-\d+(?:\.\d+)?$")       # "clip:c-1" would read as clip c minus 1 s
EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "evidence": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".m4v", ".mov", ".webm", ".mkv"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac"},
}
ASSET_FOR = {"image": ("image", "evidence"), "video": ("video",), "evidence": ("evidence",), "audio": ("audio", "video")}
TIME_KEY = re.compile(r"^(at|.+_at)$")
ASSET_KEY = re.compile(r"^(asset|.+_asset)$")


# ------------------------------------------------------------------ value types
def _time(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise PydanticCustomError("time_type", 'should be seconds (a number) or a Time string like "line:3"')
    if isinstance(v, float) and not math.isfinite(v):
        raise PydanticCustomError("time_type", "should be a finite number of seconds")
    return v


def _size(v):
    if v == "fit":
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
        raise PydanticCustomError("size_type", 'should be a size in px (a number > 0) or "fit"')
    return v


def _shadow(v):
    if v is None or isinstance(v, (bool, str)):
        return v
    raise PydanticCustomError("shadow_type", "should be true/false or a CSS shadow string")


def _quad(v):
    ok = isinstance(v, list) and len(v) == 4 and all(isinstance(n, (int, float)) and not isinstance(n, bool)
                                                       for n in v)
    if not ok or v[2] <= 0 or v[3] <= 0:
        raise PydanticCustomError("box_type", "should be [x, y, w, h] in the image's pixels, with w and h > 0")
    return v


def _box_tag(v):
    return "name" if isinstance(v, str) else "box"


def _caption_source(v):
    if v == "voice" or (isinstance(v, str) and v.startswith("clip:") and ID.match(v[5:])):
        return v
    raise PydanticCustomError("source_type", 'should be "voice" or "clip:<id>" (a video or audio clip with a '
                                             'transcript)')


Time = Annotated[Union[float, str], PlainValidator(_time)]
Size = Annotated[Union[float, str], PlainValidator(_size)]
Shadow = Annotated[Optional[Union[bool, str]], PlainValidator(_shadow)]
Quad = Annotated[list, PlainValidator(_quad)]
Unit = Annotated[float, Field(ge=0, le=1)]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Box(_M):
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)


BoxValue = Annotated[Union[Annotated[Box, Tag("box")], Annotated[Literal["full", "safe"], Tag("name")]],
                     Discriminator(_box_tag)]


class Source(_M):
    title: str = ""
    url: str = ""


class Meta(_M):
    title: str = ""
    desc: str = ""
    topic: str = ""
    shape: str = ""
    sources: list[Source] = Field(default_factory=list)


class Asset(_M):
    path: str = Field(min_length=1)
    kind: Literal["image", "video", "audio", "evidence"]
    box: Optional[Quad] = None
    site: str = ""
    url: str = ""
    note: str = ""
    transcript: Optional[str] = None        # assets/<id>.transcript.json (transcribe)


class Filter(_M):
    blur: Optional[float] = Field(None, ge=0)
    brightness: Optional[float] = Field(None, ge=0)
    contrast: Optional[float] = Field(None, ge=0)
    saturate: Optional[float] = Field(None, ge=0)
    grayscale: Optional[float] = Field(None, ge=0, le=1)


class Transition(_M):
    preset: Literal["fade", "rise", "drop", "pop", "wipe_left", "wipe_up", "zoom"]
    dur: float = Field(0.4, gt=0, le=10)


class Cut(_M):
    """A clip's transition in from the clip before it on the same track (spec 3.2)."""
    type: Literal["crossfade", "dip_black", "dip_white", "wipe_left", "wipe_right", "wipe_up", "slide_left", "zoom"]
    dur: float = Field(0.5, gt=0, le=10)


class Duck(_M):
    under: str = Field(min_length=1)    # a track id, or "voice"
    to: float = Field(0.25, ge=0, le=1)
    fade: float = Field(0.3, ge=0, le=5)


class Keyframe(_M):
    t: Time
    v: float
    ease: Optional[Literal["linear", "in", "out", "inOut", "spring", "step"]] = None


KeyframeProp = Literal["x", "y", "w", "h", "opacity", "rotate", "scale", "blur", "brightness", "zoom", "pan_x", "pan_y",
                       "progress", "volume"]


class Stroke(_M):
    color: Optional[str] = None
    width: Optional[float] = Field(None, ge=0)


class Bg(_M):
    color: Optional[str] = None
    radius: Optional[float] = Field(None, ge=0)
    pad: Optional[float] = Field(None, ge=0)


class TextStyle(_M):
    font: Optional[str] = Field(None, min_length=1)          # a built-in name or a workspace font (validate)
    size: Optional[Size] = None
    max_size: Optional[float] = Field(None, gt=0)
    min_size: Optional[float] = Field(None, gt=0)
    weight: Optional[int] = Field(None, ge=100, le=900)
    color: Optional[str] = None
    accent: Optional[str] = None
    align: Optional[Literal["left", "center", "right"]] = None
    valign: Optional[Literal["top", "middle", "bottom"]] = None
    line_height: Optional[float] = Field(None, gt=0)
    letter_spacing: Optional[float] = None
    wrap: Optional[bool] = None
    balance: Optional[bool] = None
    stroke: Optional[Stroke] = None
    shadow: Shadow = None
    bg: Optional[Bg] = None


class Reveal(_M):
    mode: Literal["chars", "words", "lines", "none"] = "chars"
    dur: Optional[float] = Field(None, gt=0, le=30)


class Highlight(_M):
    at: Optional[Time] = None
    dur: float = Field(0.8, gt=0, le=10)
    color: Optional[str] = None


class _Timed(_M):
    id: str
    start: Time
    end: Optional[Time] = None
    dur: Optional[float] = Field(None, gt=0)

    @model_validator(mode="after")
    def _end_or_dur(self):
        if self.end is not None and self.dur is not None:
            raise ValueError("give end or dur, not both")
        if self.end is None and self.dur is None:
            raise ValueError("needs end (a Time) or dur (seconds)")
        return self


class _Visual(_Timed):
    box: BoxValue = "full"
    opacity: float = Field(1, ge=0, le=1)
    rotate: float = 0
    scale: float = 1
    origin: str = "center"
    radius: float = Field(0, ge=0)
    blend: Literal[BLENDS] = "normal"  # type: ignore[valid-type]
    filter: Optional[Filter] = None
    shadow: Shadow = None
    enter: Optional[Transition] = None
    exit: Optional[Transition] = None
    transition: Optional[Cut] = None
    keyframes: dict[KeyframeProp, list[Keyframe]] = Field(default_factory=dict)


class ImageClip(_Visual):
    type: Literal["image"]
    asset: str
    fit: Literal["cover", "contain"] = "cover"
    focus: Optional[Annotated[list[Unit], Field(min_length=2, max_length=2)]] = None
    motion: Optional[Literal["push", "pull", "pan_left", "pan_right", "rise", "still"]] = None


class VideoClip(_Visual):
    type: Literal["video"]
    asset: str
    trim_in: float = Field(0, ge=0)
    rate: float = Field(1, gt=0, le=16)
    loop: bool = False
    fit: Literal["cover", "contain"] = "cover"
    focus: Optional[Annotated[list[Unit], Field(min_length=2, max_length=2)]] = None
    volume: float = Field(0, ge=0)
    motion: Optional[Literal["push", "pull", "pan_left", "pan_right", "rise", "still"]] = None


class TextClip(_Visual):
    type: Literal["text"]
    text: str
    style: Optional[TextStyle] = None
    reveal: Optional[Reveal] = None


class ShapeClip(_Visual):
    type: Literal["shape"]
    shape: Literal["rect", "ellipse", "line", "arrow", "path"] = "rect"
    fill: Optional[str] = None
    stroke: Optional[str] = None
    stroke_width: Optional[float] = Field(None, ge=0)
    d: Optional[str] = None
    draw: bool = False


class EvidenceClip(_Visual):
    type: Literal["evidence"]
    asset: str
    highlight: Optional[Highlight] = None


class ComponentClip(_Visual):
    type: Literal["component"]
    name: str = Field(min_length=1)
    props: dict[str, Any] = Field(default_factory=dict)


VisualClip = Annotated[Union[ImageClip, VideoClip, TextClip, ShapeClip, EvidenceClip, ComponentClip],
                       Field(discriminator="type")]


class AudioClip(_Timed):
    type: Literal["audio"]
    asset: str
    trim_in: float = Field(0, ge=0)
    loop: bool = False
    volume: float = Field(1, ge=0)
    fade_in: float = Field(0, ge=0)
    fade_out: float = Field(0, ge=0)
    transition: Optional[Cut] = None
    keyframes: dict[Literal["volume"], list[Keyframe]] = Field(default_factory=dict)
    duck: Optional[Duck] = None


class Override(_M):
    line: int = Field(ge=1)
    text: str


class CaptionItem(_M):
    start: Time
    end: Time
    text: str


class VisualTrack(_M):
    id: str
    kind: Literal["visual"]
    hidden: bool = False
    clips: list[VisualClip] = Field(default_factory=list)


class AudioTrack(_M):
    id: str
    kind: Literal["audio"]
    hidden: bool = False
    clips: list[AudioClip] = Field(default_factory=list)


class CaptionsTrack(_M):
    id: str
    kind: Literal["captions"]
    hidden: bool = False
    source: Annotated[str, PlainValidator(_caption_source)] = "voice"
    box: Optional[BoxValue] = None
    style: Optional[TextStyle] = None
    emphasis: list[str] = Field(default_factory=list)
    max_chars: Optional[int] = Field(None, ge=4, le=60)       # default: by the locale (locales.caption_chars)
    overrides: list[Override] = Field(default_factory=list)
    items: Optional[list[CaptionItem]] = None


Track = Annotated[Union[VisualTrack, AudioTrack, CaptionsTrack], Field(discriminator="kind")]
Clip = Union[ImageClip, VideoClip, TextClip, ShapeClip, EvidenceClip, ComponentClip, AudioClip]


class Document(_M):
    version: Literal[2] = 2
    profile: Optional[Union[str, dict[str, Any]]] = None        # a name or an inline profile (profiles.make_profile)
    locale: Optional[str] = None
    theme: dict[str, str] = Field(default_factory=dict)
    meta: Meta = Field(default_factory=Meta)
    voice: Optional[str] = None
    duration: Optional[Time] = None
    markers: dict[str, Time] = Field(default_factory=dict)
    assets: dict[str, Asset] = Field(default_factory=dict)
    tracks: list[Track] = Field(default_factory=list)


CLIP_MODELS = {"image": ImageClip, "video": VideoClip, "text": TextClip, "shape": ShapeClip,
               "evidence": EvidenceClip, "component": ComponentClip, "audio": AudioClip}
TRACK_MODELS = {"visual": VisualTrack, "audio": AudioTrack, "captions": CaptionsTrack}
KEY_MODELS = {"style": TextStyle, "enter": Transition, "exit": Transition, "filter": Filter, "highlight": Highlight,
              "transition": Cut, "duck": Duck,
              "reveal": Reveal, "stroke": Stroke, "bg": Bg, "meta": Meta, "box": Box}
ITEM_MODELS = {"sources": Source, "overrides": Override, "items": CaptionItem, **{p: Keyframe for p in KEYFRAME_PROPS}}


# ------------------------------------------------------------------ schema errors
class DocumentError(ValueError):
    """project.json does not fit the schema; `issues` lists every problem with its path."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("; ".join(f"{i.where}: {i.msg}" for i in issues[:5]) or "invalid project")

    def errors(self) -> list[dict]:
        # the shape checks.describe_load_error reads
        return [{"loc": (i.where,), "msg": i.msg} for i in self.issues]


def _walk(loc: tuple, data) -> tuple[str, type | None]:
    """The readable place of a pydantic error location ("clip c2.style.size") and the model holding its last key.
    Pydantic puts the union tag (track kind, clip type, box form) after a list item or a box: skipped here."""
    node, model, parent_key = data, Document, None
    head, path, skip, track_kind = "", "", (), None
    for n, seg in enumerate(loc):
        last = n == len(loc) - 1
        if skip and seg in skip:
            skip = ()
            continue
        skip = ()
        if seg == "[key]":
            path += " (key)"
            continue
        if isinstance(seg, int):
            item = node[seg] if isinstance(node, list) and 0 <= seg < len(node) else None
            ident = item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), str) else ""
            if parent_key == "tracks" and not head:
                head, path, skip = (f"track {ident}" if ident else f"tracks[{seg}]"), "", TRACK_KINDS
                track_kind = item.get("kind") if isinstance(item, dict) else None
                model = TRACK_MODELS.get(track_kind)
            elif parent_key == "clips":
                head, path = (f"clip {ident}" if ident else f"{head}.clips[{seg}]"), ""
                skip = CLIP_TYPES if track_kind == "visual" else ()
                if track_kind == "audio":
                    model = AudioClip
                else:
                    model = CLIP_MODELS.get(item.get("type")) if isinstance(item, dict) else None
            else:
                path += f"[{seg}]"
                model = ITEM_MODELS.get(parent_key, model)
            node, parent_key = item, None
            continue
        path = f"{path}.{seg}" if path else str(seg)
        if last:
            break
        if parent_key == "assets":
            model = Asset
        elif seg in KEY_MODELS and not (seg == "box" and parent_key == "assets"):
            model = KEY_MODELS[seg]
        if seg == "box":
            skip = ("box", "name")
        node = node.get(seg) if isinstance(node, dict) else None
        parent_key = seg
    if head and path:
        return f"{head}{'' if path.startswith('[') else '.'}{path}", model
    return head or path or "(project)", model


def _fields_of(model) -> str:
    if model is None or not hasattr(model, "model_fields"):
        return ""
    names = list(model.model_fields)
    first = [n for n in ("id", "type", "kind") if n in names]
    return ", ".join(first + [n for n in names if n not in first])


def _got(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return f" (got {text[:40]}{'...' if len(text) > 40 else ''})"


def _message(err: dict, model) -> str:
    kind, msg, ctx = err.get("type", ""), str(err.get("msg", "")), err.get("ctx") or {}
    last = err["loc"][-1] if err.get("loc") else ""
    if kind == "extra_forbidden":
        allowed = _fields_of(model)
        return f"unknown field {last!r}" + (f"; allowed here: {allowed}" if allowed else "")
    if kind == "missing":
        return f"{last} is required" if isinstance(last, str) else "is required"
    if kind == "union_tag_not_found":
        disc = str(ctx.get("discriminator", "")).strip("'")
        choices = ", ".join(CLIP_TYPES if disc == "type" else TRACK_KINDS if disc == "kind" else ())
        return f"missing {disc!r}" + (f" (one of {choices})" if choices else "")
    if kind == "union_tag_invalid":
        disc = str(ctx.get("discriminator", "")).strip("'")
        return f"{disc} {ctx.get('tag')!r} is not known; one of {ctx.get('expected_tags')}"
    if kind == "literal_error" and last == "type" and str(ctx.get("expected", "")) == "'audio'":
        return "audio tracks hold only audio clips (type \"audio\"); put visual clips on a visual track"
    if kind == "literal_error" and last == "version":
        return "version must be 2 (this is the v2 project format)"
    if kind == "value_error":
        return msg.removeprefix("Value error, ")
    if kind in ("model_type", "model_attributes_type", "dict_type"):
        return "should be an object {...}" + _got(err.get("input"))
    msg = msg.replace("Input should be", "should be")
    if kind.endswith("_type") or kind in ("literal_error", "greater_than", "greater_than_equal", "less_than_equal",
                                          "less_than", "too_short", "too_long", "string_too_short"):
        msg += _got(err.get("input"))
    return msg


def schema_issues(exc: ValidationError, data) -> list[Issue]:
    out, seen = [], set()
    for err in exc.errors():
        where, model = _walk(tuple(err.get("loc") or ()), data)
        msg = _message(err, model)
        if (where, msg) not in seen:
            seen.add((where, msg))
            out.append(Issue("error", where, msg))
    return out


# ------------------------------------------------------------------ files
def project_file(project) -> Path:
    return project_root(project) / PROJECT_FILE


def read_raw(project) -> dict:
    """project.json as a dict. FileNotFoundError / json.JSONDecodeError pass through; a non-object raises."""
    data = json.loads(project_file(project).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise DocumentError([Issue("error", "(project)", "project.json must hold a JSON object {...}")])
    return data


def parse(data: dict) -> Document:
    """A Document from a dict; DocumentError listing every schema problem."""
    if not isinstance(data, dict):
        raise DocumentError([Issue("error", "(project)", "project.json must hold a JSON object {...}")])
    try:
        return Document.model_validate(data, strict=True)
    except ValidationError as exc:
        raise DocumentError(schema_issues(exc, data)) from None


def load(project) -> Document:
    return parse(read_raw(project))


def _ints(value):
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    if isinstance(value, dict):
        return {k: _ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ints(v) for v in value]
    return value


def dump(doc: Document | dict) -> dict:
    """The JSON object to write: what was set, integral floats as integers."""
    if isinstance(doc, BaseModel):
        return _ints(doc.model_dump(mode="json", exclude_unset=True))
    return doc


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))   # LF on every OS
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)             # gone after a replace; left only when the replace failed


def save(project, doc: Document | dict) -> Path:
    """Write project.json (UTF-8, indent 1) atomically; returns its path."""
    path = project_file(project)
    write_json(path, dump(doc))
    return path


# ------------------------------------------------------------------ the voice
@dataclass(frozen=True)
class VoiceLine:
    i: int
    text: str
    t0: float
    t1: float


@dataclass
class Voice:
    ref: str                        # as written in project.json
    path: Path                      # voice.json
    lines: list[VoiceLine]
    duration: float                 # seconds of narration audio
    audio: Path | None              # the audio file, when found
    audio_rel: str | None           # its path relative to the project (what the renderer serves)

    @property
    def end(self) -> float:
        return max([self.duration] + [ln.t1 for ln in self.lines])


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def load_voice(project, ref: str | None) -> tuple[Voice | None, list[Issue]]:
    """The narration timing file and its audio; issues say what is wrong with them."""
    if not ref:
        return None, []
    root = project_root(project)
    path = (root / ref)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, [Issue("error", "voice", f"{ref} not found: run speak, or fix the path in project voice")]
    except (OSError, ValueError) as exc:
        return None, [Issue("error", "voice", f"{ref} is not readable JSON ({exc}): run speak again")]
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return None, [Issue("error", "voice", f"{ref} needs \"lines\": [{{i, text, t0, t1}}, ...]")]
    issues: list[Issue] = []
    lines: list[VoiceLine] = []
    for n, ln in enumerate(data["lines"], 1):
        if not isinstance(ln, dict) or not _num(ln.get("t0")) or not _num(ln.get("t1")):
            issues.append(Issue("error", f"voice line {n}", f"needs numeric t0 and t1 seconds in {ref}"))
            continue
        t0, t1 = float(ln["t0"]), float(ln["t1"])
        if t0 < 0 or t1 < t0:
            issues.append(Issue("error", f"voice line {n}", f"t0 {t0:g} / t1 {t1:g}: needs 0 <= t0 <= t1"))
        if lines and t0 < lines[-1].t0:
            issues.append(Issue("warning", f"voice line {n}", f"starts before line {n - 1}: lines out of order"))
        lines.append(VoiceLine(n, str(ln.get("text") or ""), t0, t1))
    if not lines and not issues:
        issues.append(Issue("error", "voice", f"{ref} has no lines"))
    duration = float(data["duration_s"]) if _num(data.get("duration_s")) else (lines[-1].t1 if lines else 0.0)
    audio, audio_rel = _voice_audio(root, path, data.get("file"))
    if audio is None:
        named = data.get("file") or "voice.wav"
        issues.append(Issue("error", "voice", f"the narration audio {named} (from {ref}) is missing: run speak again"))
    voice = Voice(ref, path, lines, duration, audio, audio_rel)
    return voice, issues


def _voice_audio(root: Path, voice_json: Path, name) -> tuple[Path | None, str | None]:
    # "file" is project-relative (speak writes voice/voice.wav); next to voice.json is the fallback
    names = [str(name)] if isinstance(name, str) and name else []
    candidates = [root / n for n in names] + [voice_json.parent / n for n in names] + [voice_json.parent / "voice.wav"]
    for c in candidates:
        if c.is_file():
            try:
                rel = c.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            return c, rel
    return None, None


# ------------------------------------------------------------------ transcripts
_TRANSCRIPTS: dict[tuple, dict | None] = {}


def load_transcript(project, asset: Asset) -> dict | None:
    """The asset's transcript ({"words": [{"word", "start", "end"}], "language", ...}, source seconds); None when the
    asset has none or the file is missing or unreadable."""
    if not asset.transcript:
        return None
    root = project_root(project)
    path = (root / asset.transcript).resolve()
    if root.resolve() not in path.parents:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _TRANSCRIPTS:
        _TRANSCRIPTS[key] = _read_transcript(path)
    return _TRANSCRIPTS[key]


def _read_transcript(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        return None
    words = []
    for w in data["words"]:
        if isinstance(w, dict) and isinstance(w.get("word"), str) and _num(w.get("start")) and _num(w.get("end")) \
                and w["word"].strip() and 0 <= w["start"] <= w["end"]:
            words.append({"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])})
    return {**data, "words": sorted(words, key=lambda w: w["start"])}


# ------------------------------------------------------------------ profile, theme, timing
def profile_of(project, doc: Document) -> Profile:
    """project profile (a name or inline), else the workspace's, else landscape; ValueError for a bad one."""
    ws = find_workspace(project)
    return choose(doc.profile, ws.config.get("profile") if ws else None, ws.profiles if ws else None)


def locale_of(project, doc: Document) -> str:
    """project locale, else the workspace's, else "en"; ValueError for a malformed tag."""
    if doc.locale is not None:
        return locales.check(doc.locale)
    ws = find_workspace(project)
    return (ws.locale if ws else None) or locales.DEFAULT_LOCALE


def font_names(project) -> tuple[str, ...]:
    """The fonts a TextStyle may name: the built-in ones, then the workspace's families."""
    ws = find_workspace(project)
    return (*BUILTIN_FONTS, *(ws.fonts if ws else {}))


def theme_of(project, doc: Document) -> dict:
    """The base theme (paper, or theme "name") with workspace.json theme, then project theme, over it."""
    ws = find_workspace(project)
    over: dict = {}
    if ws and isinstance(ws.config.get("theme"), dict):
        over.update({k: v for k, v in ws.config["theme"].items() if isinstance(v, str)})
    over.update(doc.theme)
    base = THEMES.get(over.get("name") or "paper") or THEMES["paper"]
    out = {k: getattr(base, k) for k in THEME_TOKENS}
    out.update({k: v for k, v in over.items() if k in THEME_TOKENS})
    out["name"] = base.name
    return out


def clips_of(doc: Document) -> Iterator[tuple[Any, Clip]]:
    """(track, clip) for every clip, tracks bottom to top."""
    for track in doc.tracks:
        for clip in getattr(track, "clips", None) or []:
            yield track, clip


def schedule(doc: Document, voice: Voice | None) -> T.Schedule:
    clips = {}
    for track, c in clips_of(doc):
        clips.setdefault(c.id, T.ClipTiming(c.start, c.end, c.dur, counts=not track.hidden, kind=c.type,
                                            trim_in=float(getattr(c, "trim_in", 0.0) or 0.0),
                                            rate=float(getattr(c, "rate", 1.0) or 1.0),
                                            loop=bool(getattr(c, "loop", False))))
    lines = [(ln.t0, ln.t1) for ln in voice.lines] if voice else []
    return T.Schedule(lines, clips, duration=doc.duration, voice_end=voice.end if voice else None,
                      markers=doc.markers)


def prop_refs(value, path: str = "props") -> Iterator[tuple[str, str, Any]]:
    """(path, "time" | "asset", value) for every Time and asset id in component props, at any depth."""
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}"
            if v is not None and isinstance(k, str) and TIME_KEY.match(k) and not isinstance(v, (dict, list)):
                yield p, "time", v
            elif v is not None and isinstance(k, str) and ASSET_KEY.match(k) and not isinstance(v, (dict, list)):
                yield p, "asset", v
            else:
                yield from prop_refs(v, p)
    elif isinstance(value, list):
        for n, v in enumerate(value):
            yield from prop_refs(v, f"{path}[{n}]")


def markup_runs(text: str) -> list[tuple[str, bool]]:
    """**x** markup as (text, accent) runs; an unpaired ** stays as text."""
    parts = text.split("**")
    if len(parts) % 2 == 0:                      # odd number of markers: the last one is literal
        parts = parts[:-2] + [parts[-2] + "**" + parts[-1]]
    return [(p, n % 2 == 1) for n, p in enumerate(parts) if p]


# ------------------------------------------------------------------ validation
class _Check:
    def __init__(self, project, doc: Document):
        self.root = project_root(project)
        self.doc = doc
        self.issues: list[Issue] = []
        self.voice: Voice | None = None
        self.fps = 30
        self.sched: T.Schedule | None = None
        self.film_end: float | None = None
        self.comps: dict | None = None
        self.fonts: tuple | None = None

    def add(self, level: str, where: str, msg: str) -> None:
        self.issues.append(Issue(level, where, msg))

    def run(self) -> list[Issue]:
        self.profile()
        self.locale()
        self.theme()
        self.ids()
        self.voice, issues = load_voice(self.root, self.doc.voice)
        self.issues += issues
        self.assets()
        self.sched = schedule(self.doc, self.voice)
        self.by_id = {c.id: c for _, c in clips_of(self.doc)}
        try:
            self.film_end = self.sched.film_end()
        except T.TimeError as exc:
            self.add("error", "duration", str(exc))
        self.markers()
        for track in self.doc.tracks:
            if track.kind == "captions":
                self.captions(track)
                continue
            spans = [self.clip(track, c) for c in track.clips]
            self.overlaps(track, [s for s in spans if s])
        return self.issues

    # project level
    def profile(self) -> None:
        try:
            p = profile_of(self.root, self.doc)
            self.fps = p.fps
        except WorkspaceError as exc:
            self.add("error", "workspace", str(exc))
        except ValueError as exc:
            self.add("error", "profile", str(exc))

    def locale(self) -> None:
        if self.doc.locale is not None:
            try:
                locales.check(self.doc.locale)
            except ValueError as exc:
                self.add("error", "locale", str(exc))

    def font(self, style, where: str) -> None:
        if style is None or style.font is None:
            return
        if self.fonts is None:
            try:
                self.fonts = font_names(self.root)
            except WorkspaceError:
                self.fonts = FONTS          # reported under "workspace" already
        if style.font not in self.fonts:
            extra = [f for f in self.fonts if f not in FONTS]
            self.add("error", f"{where}.style.font", f"unknown font {style.font!r}: built-in {', '.join(FONTS)}"
                     + (f"; the workspace's {', '.join(extra)}" if extra else "; a workspace adds its own as "
                        "library/fonts/<Family>.woff2 (or .woff, .ttf, .otf)"))

    def theme(self) -> None:
        for k, v in self.doc.theme.items():
            if k == "name":
                if v not in THEMES:
                    self.add("error", "theme.name", f"unknown theme {v!r}; one of {', '.join(THEMES)}")
            elif k not in THEME_TOKENS:
                self.add("warning", f"theme.{k}", f"not a theme token (ignored); tokens: {', '.join(THEME_TOKENS)}")

    def ids(self) -> None:
        seen: dict[str, str] = {}
        for n, track in enumerate(self.doc.tracks):
            self.one_id(track.id, f"track {track.id}" if track.id else f"tracks[{n}]", "track", seen)
            for c in getattr(track, "clips", None) or []:
                self.one_id(c.id, f"clip {c.id}" if c.id else f"track {track.id}.clips", "clip", seen)
        for aid in self.doc.assets:
            if not ID.match(aid):
                self.add("error", f"assets.{aid}", "asset ids are 1-64 letters, digits, _ or -")

    def one_id(self, ident: str, where: str, what: str, seen: dict) -> None:
        if not ID.match(ident or ""):
            self.add("error", where, f"{what} id {ident!r}: use 1-64 letters, digits, _ or - (no spaces or dots)")
            return
        if what == "clip" and OFFSET_LIKE.search(ident):
            self.add("error", where, f"clip id {ident!r} ends like a time offset (\"clip:{ident}\" would read as "
                                     f"minus seconds): rename it, e.g. {ident.replace('-', '_')}")
        if ident in seen:
            self.add("error", where, f"id {ident!r} is used twice ({seen[ident]} and {what}); clips and tracks "
                                     "share one set of ids")
        else:
            seen[ident] = what

    def assets(self) -> None:
        root = self.root.resolve()
        for aid, a in self.doc.assets.items():
            where = f"assets.{aid}"
            p = Path(a.path)
            if p.is_absolute() or a.path.startswith(("/", "\\")):
                self.add("error", where, f"path {a.path!r} must be relative to the project folder (assets/...): "
                                         "import_asset copies a file in")
                continue
            full = (self.root / p).resolve()
            if full != root and root not in full.parents:
                self.add("error", where, f"path {a.path!r} leaves the project folder; the renderer only serves files "
                                         "inside it: import_asset copies it in")
                continue
            if not full.is_file():
                self.add("error", where, f"file missing: {a.path}")
            ext = p.suffix.lower()
            fits = {k for k, exts in EXTENSIONS.items() if ext in exts}
            if fits and a.kind not in fits:
                self.add("error", where, f"{a.path} is not a{'n' if a.kind[0] in 'aeiou' else ''} {a.kind} file "
                                         f"({ext}); kind should be {' or '.join(sorted(fits))}")
            elif not fits:
                self.add("warning", where, f"unusual file type {ext or '(none)'} for a {a.kind}")
            if a.kind != "evidence" and (a.box or a.site or a.url):
                self.add("warning", where, "box, site and url only mean something on evidence assets")
            self.transcript_file(aid, a)

    def transcript_file(self, aid: str, a) -> None:
        if a.transcript is None:
            return
        where = f"assets.{aid}.transcript"
        if a.kind not in ("video", "audio"):
            self.add("warning", where, f"a transcript only means something on video and audio assets ({aid} is "
                                       f"{a.kind})")
        if load_transcript(self.root, a) is None:
            self.add("warning", where, f"{a.transcript} is missing or unreadable: transcribe {aid} again")

    def markers(self) -> None:
        for name, value in self.doc.markers.items():
            where = f"markers.{name}"
            if not ID.match(name):
                self.add("error", where, "marker names are 1-64 letters, digits, _ or - (no spaces or dots)")
                continue
            if OFFSET_LIKE.search(name):
                self.add("error", where, f"marker name {name!r} ends like a time offset (\"mark:{name}\" would read as "
                                         "minus seconds): rename it")
            self.time(value, where)

    # times
    def time(self, value, where: str) -> float | None:
        try:
            t = T.resolve(value, self.sched)
        except T.TimeError as exc:
            self.add("error", where, str(exc))
            return None
        self.src_bounds(value, where)
        return t

    def src_bounds(self, value, where: str) -> None:
        """A src: Time whose source second the clip does not reach: it resolves, but nothing of it is on screen."""
        if not isinstance(value, str):
            return
        try:
            e = T.parse(value)
        except T.TimeError:
            return
        c = self.by_id.get(e.ref) if e.anchor == "src" else None
        if c is None or c.type not in SOUNDING or getattr(c, "loop", False):
            return
        try:
            a, b = self.sched.span(c.id)
        except T.TimeError:
            return
        rate = float(getattr(c, "rate", 1.0) or 1.0)
        out = c.trim_in + (b - a) * rate
        if e.at > out + 0.5 / self.fps * rate:
            self.add("warning", where, f"{value}: source second {e.at:g} is after clip {c.id} ends (it shows source "
                                       f"{c.trim_in:.2f}-{out:.2f} s): that moment is not in the film; a clip split "
                                       "or cut by an edit continues under another id")

    def frame(self, seconds: float) -> int:
        return T.to_frame(seconds, self.fps)

    # clips
    def clip(self, track, c) -> tuple | None:
        where = f"clip {c.id}"
        span = self.span(c, where)
        self.refs(c, where)
        if c.type == "component":
            self.component(c, where, span)
        elif c.type == "text":
            self.text(c, where)
        elif c.type == "shape":
            self.shape(c, where)
        elif c.type == "evidence" and c.highlight is not None and c.highlight.at is not None:
            self.in_clip(c.highlight.at, span, f"{where}.highlight.at")
        elif c.type == "audio" and span and c.fade_in + c.fade_out > span[1] - span[0] + 1e-6:
            self.add("warning", where, f"fade_in + fade_out ({c.fade_in + c.fade_out:g} s) are longer than the clip")
        self.keyframes(c, where, span)
        self.cut(c, where, span)
        if c.type == "audio" and c.duck is not None:
            self.duck(track, c, where)
        return (c, *span) if span else None

    def cut(self, c, where: str, span) -> None:
        tr = c.transition
        if tr is None:
            return
        if c.type == "audio" and tr.type != "crossfade":
            self.add("error", f"{where}.transition", f"audio clips crossfade only (type \"crossfade\"), not "
                                                     f"{tr.type!r}")
        if span and tr.dur > span[1] - span[0] + 1e-6:
            self.add("error", f"{where}.transition", f"the transition ({tr.dur:g} s) is longer than the clip "
                                                     f"({span[1] - span[0]:.2f} s)")
        if getattr(c, "enter", None) is not None:
            self.add("warning", where, "enter and transition both animate its start: the transition is enough")

    def duck(self, track, c, where: str) -> None:
        under = c.duck.under
        if under == "voice":
            if not self.doc.voice:
                self.add("error", f"{where}.duck.under", "\"voice\" ducks under the narration, and the project has "
                                                         "none")
            return
        target = next((t for t in self.doc.tracks if t.id == under), None)
        if target is None:
            known = ", ".join(t.id for t in self.doc.tracks if t.kind != "captions")
            self.add("error", f"{where}.duck.under", f"no track {under!r}; duck under a track ({known}) or \"voice\"")
        elif target is track:
            self.add("error", f"{where}.duck.under", "a clip cannot duck under its own track")
        elif target.kind == "captions":
            self.add("error", f"{where}.duck.under", f"{under} is a captions track and makes no sound")

    def span(self, c, where: str) -> tuple[float, float] | None:
        try:
            a, b = self.sched.span(c.id)
        except T.TimeError as exc:
            self.add("error", where, str(exc))
            return None
        self.src_bounds(c.start, f"{where}.start")
        self.src_bounds(c.end, f"{where}.end")
        if b <= a + 1e-9:
            self.add("error", where, f"ends at {b:.2f} s, not after its start ({a:.2f} s): end must be later than "
                                     "start")
            return None
        if self.frame(b) <= self.frame(a):
            self.add("error", where, f"{b - a:.3f} s is shorter than one frame")
            return None
        if self.film_end is not None:
            if a >= self.film_end - 1e-9:
                self.add("warning", where, f"starts at {a:.2f} s, at or after the film's end ({self.film_end:.2f} s): "
                                           "it never shows")
            elif b > self.film_end + 0.5 / self.fps:
                self.add("warning", where, f"ends at {b:.2f} s, after the film's end ({self.film_end:.2f} s): the rest "
                                           "is cut")
        return a, b

    def refs(self, c, where: str) -> None:
        aid = getattr(c, "asset", None)
        if aid is None:
            return
        a = self.doc.assets.get(aid)
        if a is None:
            known = ", ".join(sorted(self.doc.assets)) or "none yet"
            self.add("error", f"{where}.asset", f"no asset {aid!r} (assets: {known}): add it first")
            return
        allowed = ASSET_FOR[c.type]
        if a.kind not in allowed:
            self.add("error", f"{where}.asset", f"{c.type} clips take {' or '.join(allowed)} assets; {aid!r} is "
                                                f"{a.kind}")

    def inside(self, t: float | None, span, where: str) -> None:
        if t is None or not span:
            return
        a, b = span
        if t > b + 1e-6:
            self.add("warning", where, f"{t:.2f} s is after the clip ends ({b:.2f} s): it never happens on screen")
        elif t < a - 1e-6:
            self.add("advice", where, f"{t:.2f} s is before the clip starts ({a:.2f} s): it shows as already done")

    def in_clip(self, value, span, where: str) -> None:
        """A Time inside a clip: a number counts from the clip's start, a Time string is absolute."""
        if T.is_number(value) and value < 0:
            self.add("error", where, f"{value:g}: a number here is seconds from the clip's start (>= 0); for a moment "
                                     "before the clip use a Time string such as \"line:3\"")
            return
        try:
            e = T.parse(value)
        except T.TimeError as exc:
            self.add("error", where, str(exc))
            return
        if e.anchor != "abs":
            self.inside(self.time(e, where), span, where)
        elif span and e.offset > span[1] - span[0] + 1e-6:
            self.add("warning", where, f"{e.offset:g} s from the clip's start is after it ends (it lasts "
                                       f"{span[1] - span[0]:.2f} s): numbers here count from the clip's start, so "
                                       "it never happens on screen; a Time string like \"line:5+0.3\" is absolute")

    def keyframes(self, c, where: str, span) -> None:
        for prop, frames in c.keyframes.items():
            if prop == "volume" and c.type not in SOUNDING:
                self.add("error", f"{where}.keyframes.volume", f"volume keyframes are for video and audio clips (a "
                                                               f"{c.type} clip makes no sound)")
            elif prop == "volume" and any(k.v < 0 for k in frames):
                self.add("error", f"{where}.keyframes.volume", "a volume is 0 (silent) or more")
            for n, k in enumerate(frames):
                self.in_clip(k.t, span, f"{where}.keyframes.{prop}[{n}]")
        motion = getattr(c, "motion", None)
        moved = [p for p in ("zoom", "pan_x", "pan_y") if c.keyframes.get(p)]
        if motion and motion != "still" and moved:
            self.add("warning", where, f"motion {motion!r} and keyframes on {', '.join(moved)}: the keyframes win for "
                                       "those props")

    def text(self, c, where: str) -> None:
        self.font(c.style, where)
        if not c.text.strip():
            self.add("warning", where, "the text is empty")
        elif c.text.count("**") % 2:
            self.add("warning", where, "odd number of ** markers: the last one shows as text")

    def shape(self, c, where: str) -> None:
        if c.shape == "path" and not (c.d or "").strip():
            self.add("error", where, "a path shape needs d (an SVG path in box coordinates)")
        elif c.d and c.shape in ("rect", "ellipse"):
            self.add("warning", where, f"d is ignored for a {c.shape}")

    def component(self, c, where: str, span) -> None:
        if self.comps is None:
            self.comps = library.components(self.root)
        comp = self.comps.get(c.name)
        if comp is None:
            names = ", ".join(self.comps) or "none"
            self.add("error", f"{where}.name", f"no component {c.name!r}; there are: {names}")
        else:
            for row in library.validate_props(comp, c.props):
                self.add("error", where, row)
        for path, kind, value in prop_refs(c.props):
            w = f"{where}.{path}"
            if kind == "time":
                self.in_clip(value, span, w)
            elif not isinstance(value, str) or value not in self.doc.assets:
                known = ", ".join(sorted(self.doc.assets)) or "none yet"
                self.add("error", w, f"no asset {value!r} (assets: {known})")

    # tracks
    def overlaps(self, track, spans: list[tuple]) -> None:
        """Clips on a track must not overlap, except a clip with a transition over the clip just before it, by at most
        the transition's dur."""
        rows = sorted(((self.frame(a), self.frame(b), c, a, b) for c, a, b in spans), key=lambda r: (r[0], r[1]))
        for i, row in enumerate(rows):
            _, fb2, c2, a2, b2 = row
            tr = c2.transition
            if i and tr is not None:
                fa1, fb1, c1, a1, b1 = rows[i - 1]
                if fb1 >= row[0] and tr.dur > b1 - a1 + 1e-6:
                    self.add("error", f"clip {c2.id}.transition", f"the transition ({tr.dur:g} s) is longer than clip "
                                                                  f"{c1.id} it comes from ({b1 - a1:.2f} s)")
            for j, prev in enumerate(rows[:i]):
                fa1, fb1, c1, a1, b1 = prev
                if fb1 <= row[0]:
                    continue
                over = min(b1, b2) - a2
                if j == i - 1 and tr is not None and fb2 > fb1:
                    if over > tr.dur + 0.5 / self.fps:
                        self.add("error", f"track {track.id}",
                                 f"clips {c1.id} ({a1:.2f}-{b1:.2f} s) and {c2.id} ({a2:.2f}-{b2:.2f} s) overlap by "
                                 f"{over:.2f} s, more than {c2.id}'s transition ({tr.dur:g} s): a clip may overlap "
                                 "the clip before it by at most its transition's dur")
                    continue
                self.add("error", f"track {track.id}",
                         f"clips {c1.id} ({a1:.2f}-{b1:.2f} s) and {c2.id} ({a2:.2f}-{b2:.2f} s) overlap by "
                         f"{over:.2f} s: clips on one track must not overlap; trim or move one, or put it "
                         "on another track")

    def captions(self, track) -> None:
        where = f"track {track.id}"
        self.font(track.style, where)
        if track.items is None and track.source != "voice":
            self.transcript_source(track, where)
            return
        if track.items is not None:
            for n, it in enumerate(track.items):
                w = f"{where}.items[{n}]"
                a, b = self.time(it.start, f"{w}.start"), self.time(it.end, f"{w}.end")
                if a is not None and b is not None and b <= a:
                    self.add("error", w, f"ends at {b:.2f} s, not after its start ({a:.2f} s)")
                if not it.text.strip():
                    self.add("warning", w, "empty caption text")
            return
        if self.voice is None:
            if not self.doc.voice:
                self.add("error", where, "captions come from the voice, and the project has none: speak first, or "
                                         "give items [{start, end, text}]")
            return
        count = len(self.voice.lines)
        lines_seen = set()
        for n, o in enumerate(track.overrides):
            w = f"{where}.overrides[{n}]"
            if o.line > count:
                self.add("error", w, f"line {o.line} is past the voice: it has {count} line(s)")
            if o.line in lines_seen:
                self.add("warning", w, f"line {o.line} is overridden twice; the last one wins")
            lines_seen.add(o.line)


    def transcript_source(self, track, where: str) -> None:
        cid = track.source[5:]
        c = self.by_id.get(cid)
        if c is None:
            self.add("error", f"{where}.source", f"no clip {cid!r}: captions from a transcript name the video or audio "
                                                 "clip that plays it")
            return
        if c.type not in SOUNDING:
            self.add("error", f"{where}.source", f"clip {cid} is a {c.type} clip; captions follow the transcript of a "
                                                 "video or audio clip")
            return
        if getattr(c, "loop", False):
            self.add("error", f"{where}.source", f"clip {cid} loops, so its words would repeat: captions from a "
                                                 "transcript need a clip that plays its source once")
        a = self.doc.assets.get(c.asset)
        if a is None:
            return                              # the clip's own asset error says it
        if not a.transcript:
            self.add("error", f"{where}.source", f"asset {c.asset} (played by clip {cid}) has no transcript: "
                                                 f"transcribe {c.asset} first")
        elif load_transcript(self.root, a) is None:
            self.add("error", f"{where}.source", f"the transcript of asset {c.asset} ({a.transcript}) is missing or "
                                                 f"unreadable: transcribe {c.asset} again")
        if track.overrides:
            self.add("warning", f"{where}.overrides", "overrides change voice lines; captions from a transcript take "
                                                      "none (give items to write them by hand)")


def validate(project, doc: Document | dict) -> list[Issue]:
    """Every problem with the project, errors first in file order; [] when it is clean."""
    if isinstance(doc, dict):
        return check_data(project, doc)[1]
    issues = _Check(project, doc).run()
    order = {"error": 0, "warning": 1, "advice": 2}
    return sorted(issues, key=lambda i: order.get(i.level, 9))


def check_data(project, data: dict) -> tuple[Document | None, list[Issue]]:
    """(Document, issues) for a project dict; (None, schema issues) when it does not fit the schema."""
    try:
        doc = parse(data)
    except DocumentError as exc:
        return None, exc.issues
    return doc, validate(project, doc)
