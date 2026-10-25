"""Time values (spec 3.1): seconds, or a string anchored on a voice line, a clip, a marker, a source second of a
clip or the film end, +/- seconds.

`parse` checks the grammar; `resolve` turns a Time into seconds against a context (voice lines, clip times, film
end). `Schedule` is that context for a whole project: it times every clip lazily and reports reference cycles.
Inside a clip (keyframe t, highlight.at, component at / *_at) a number counts from the clip's start and a Time
string stays absolute: `clip_seconds` / `clip_frame`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

HINT = ('a Time is seconds (12.5) or "line:N", "line:N.end", "clip:ID", "clip:ID.end", "mark:NAME", '
        '"src:CLIP@SECONDS" or "end", optionally +/- seconds ("line:5+0.3", "clip:c2.end-0.5", "end-2")')
TAIL_S = 0.6                    # a breath after the narration before the film ends

_NUMBER = re.compile(r"^\d+(?:\.\d+)?$|^\.\d+$")
_EXPR = re.compile(
    r"^(?:(?i:line):(?P<n>\d+)(?P<lend>\.(?i:end))?"
    r"|(?i:clip):(?P<id>[A-Za-z0-9_][A-Za-z0-9_-]*?)(?P<cend>\.(?i:end))?"
    r"|(?i:mark):(?P<mark>[A-Za-z0-9_][A-Za-z0-9_-]*?)"
    r"|(?i:src):(?P<sid>[A-Za-z0-9_][A-Za-z0-9_-]*?)@(?P<ss>\d+(?:\.\d+)?|\.\d+)"
    r"|(?P<end>(?i:end)))"
    r"(?:\s*(?P<sign>[+-])\s*(?P<off>\d+(?:\.\d+)?|\.\d+))?$")


class TimeError(ValueError):
    """A Time that does not parse or cannot be resolved; the message says how to fix it."""


class CycleError(TimeError):
    """Times that refer to each other in a loop; the message shows the loop."""


@dataclass(frozen=True)
class TimeExpr:
    anchor: str                 # "abs" | "line" | "clip" | "mark" | "src" | "end"
    ref: int | str | None       # line number, clip id or marker name
    at_end: bool                # "line:N.end" / "clip:ID.end"
    offset: float               # seconds added (the whole value for "abs")
    at: float | None = None     # "src:ID@S": the source second S

    def __str__(self) -> str:
        if self.anchor == "abs":
            return f"{self.offset:g}"
        if self.anchor == "end":
            base = "end"
        elif self.anchor == "src":
            base = f"src:{self.ref}@{self.at:g}"
        else:
            base = f"{self.anchor}:{self.ref}{'.end' if self.at_end else ''}"
        if not self.offset:
            return base
        return f"{base}{'+' if self.offset > 0 else '-'}{abs(self.offset):g}"

    @property
    def clip(self) -> str | None:
        return self.ref if self.anchor == "clip" else None  # type: ignore[return-value]


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse(value) -> TimeExpr:
    """A Time (number or string) as a TimeExpr; TimeError with the grammar when it does not parse."""
    if is_number(value):
        if not math.isfinite(value):
            raise TimeError(f"{value!r} is not a finite number of seconds")
        if value < 0:
            raise TimeError(f"{value:g} s is before the film starts: times count from 0")
        return TimeExpr("abs", None, False, float(value))
    if not isinstance(value, str):
        raise TimeError(f"{value!r} is not a Time: {HINT}")
    s = value.strip()
    if not s:
        raise TimeError(f"empty Time: {HINT}")
    if _NUMBER.match(s):
        return TimeExpr("abs", None, False, float(s))
    m = _EXPR.match(s)
    if not m:
        raise TimeError(f"cannot read the Time {value!r}{_why(s)}: {HINT}")
    off = float(m["off"]) * (-1 if m["sign"] == "-" else 1) if m["off"] else 0.0
    if m["n"] is not None:
        n = int(m["n"])
        if n < 1:
            raise TimeError(f"{value!r}: voice lines count from 1")
        return TimeExpr("line", n, bool(m["lend"]), off)
    if m["id"] is not None:
        return TimeExpr("clip", m["id"], bool(m["cend"]), off)
    if m["mark"] is not None:
        return TimeExpr("mark", m["mark"], False, off)
    if m["sid"] is not None:
        return TimeExpr("src", m["sid"], False, off, float(m["ss"]))
    return TimeExpr("end", None, False, off)


def _why(s: str) -> str:
    low = s.lower()
    if low.startswith("line") and not re.match(r"^line:\d", low):
        return " (a voice line is line:N with N a whole number from 1)"
    if low.startswith("clip") and not re.match(r"^clip:[a-z0-9_]", low):
        return " (a clip is clip:ID with the clip's id)"
    if low.startswith("src") and not re.match(r"^src:[a-z0-9_][a-z0-9_-]*@[\d.]", low):
        return " (a source second is src:CLIP@SECONDS, e.g. src:c1@12.5)"
    if low.startswith("mark") and not re.match(r"^mark:[a-z0-9_]", low):
        return " (a marker is mark:NAME with the marker's name)"
    if low in ("start", "begin", "0s"):
        return " (the film start is 0)"
    if re.match(r"^-\d", s):
        return " (times count from 0; negative seconds are before the film)"
    if re.search(r"\d\s*(s|sec|ms)$", low):
        return " (write plain seconds, without a unit)"
    return ""


def check(value) -> str | None:
    """None when `value` parses, else the reason."""
    try:
        parse(value)
    except TimeError as exc:
        return str(exc)
    return None


class TimeContext(Protocol):
    def line(self, n: int, at_end: bool) -> float: ...
    def clip(self, clip_id: str, at_end: bool) -> float: ...
    def mark(self, name: str) -> float: ...
    def source(self, clip_id: str, seconds: float) -> float: ...
    def film_end(self) -> float: ...


def resolve(value, ctx: TimeContext) -> float:
    """`value` (a Time or a TimeExpr) in seconds from the film start."""
    e = value if isinstance(value, TimeExpr) else parse(value)
    if e.anchor == "abs":
        return e.offset
    if e.anchor == "line":
        base = ctx.line(int(e.ref), e.at_end)  # type: ignore[arg-type]
    elif e.anchor == "clip":
        base = ctx.clip(str(e.ref), e.at_end)
    elif e.anchor == "mark":
        base = ctx.mark(str(e.ref))
    elif e.anchor == "src":
        base = ctx.source(str(e.ref), float(e.at or 0.0))
    else:
        base = ctx.film_end()
    t = base + e.offset
    if t < -1e-9:
        raise TimeError(f"{value} is {t:.2f} s: before the film starts")
    return max(0.0, t)


def to_frame(seconds: float, fps: float) -> int:
    """round(s x fps), halves up as the renderer's Math.round does."""
    return int(math.floor(seconds * fps + 0.5))


# ------------------------------------------------------------------ Times inside a clip
def counts_from_clip(value) -> bool:
    """True for a Time that, inside a clip (keyframe t, highlight.at, component at / *_at), counts from the clip's
    start: a number (or a numeric string). Anchored strings ("line:5", "clip:x.end-1", "end") are absolute."""
    try:
        return parse(value).anchor == "abs"
    except TimeError:
        return False


def clip_seconds(value, clip_start: float, ctx: TimeContext) -> float:
    """A Time inside a clip as seconds from the film start (numbers count from `clip_start`)."""
    e = value if isinstance(value, TimeExpr) else parse(value)
    return clip_start + e.offset if e.anchor == "abs" else resolve(e, ctx)


def clip_frame(value, start_frame: int, fps: float, ctx: TimeContext) -> int:
    """A Time inside a clip as frames from the clip's start (the renderer's unit)."""
    e = value if isinstance(value, TimeExpr) else parse(value)
    return to_frame(e.offset, fps) if e.anchor == "abs" else to_frame(resolve(e, ctx), fps) - start_frame


# ------------------------------------------------------------------ project timing
@dataclass(frozen=True)
class ClipTiming:
    start: object               # a Time
    end: object = None          # a Time, or None with dur
    dur: float | None = None    # seconds
    counts: bool = True         # counts towards the film length when no voice or duration sets it
    kind: str = ""              # the clip type; "src:" takes video and audio ("" = untyped, as in tests)
    trim_in: float = 0.0        # source seconds skipped at its start
    rate: float = 1.0           # source seconds per film second
    loop: bool = False
    retimed: str = ""           # why source seconds do not map to film time (document.retimed), or ""


class _NeedsEnd(Exception):
    """Raised inside the clip-based film length when a clip itself depends on the film end."""


class Schedule:
    """Times every clip (seconds) and the film end on demand, with cycle detection.

    lines: [(t0, t1)] of the voice; clips: {id: ClipTiming}; duration: the project's Time or None;
    voice_end: the narration's end in seconds or None (the film then lasts voice_end + TAIL_S); markers: {name: Time}.
    """

    def __init__(self, lines: Iterable[tuple[float, float]], clips: dict[str, ClipTiming],
                 duration=None, voice_end: float | None = None, markers: dict | None = None):
        self.lines = [(float(a), float(b)) for a, b in lines]
        self.clips = clips
        self.duration = duration
        self.voice_end = voice_end
        self.markers = dict(markers or {})
        self._memo: dict[tuple, float | TimeError] = {}
        self._stack: list[tuple] = []
        self._auto_end = False

    # TimeContext
    def line(self, n: int, at_end: bool) -> float:
        if not self.lines:
            raise TimeError(f"line:{n} needs the narration: the project has no voice (or it has no lines)")
        if not 1 <= n <= len(self.lines):
            raise TimeError(f"line:{n} is past the voice: it has {len(self.lines)} line(s)")
        return self.lines[n - 1][1 if at_end else 0]

    def clip(self, clip_id: str, at_end: bool) -> float:
        if clip_id not in self.clips:
            raise TimeError(f"clip:{clip_id}: there is no clip {clip_id!r}")
        return self._get(("clip", clip_id, "end" if at_end else "start"))

    def mark(self, name: str) -> float:
        if name not in self.markers:
            known = ", ".join(sorted(self.markers)) or "none yet"
            raise TimeError(f"mark:{name}: there is no marker {name!r} (markers: {known})")
        return self._get(("mark", name))

    def source(self, clip_id: str, seconds: float) -> float:
        """The film time at which source second `seconds` of a video or audio clip plays."""
        where = f"src:{clip_id}@{seconds:g}"
        if clip_id not in self.clips:
            raise TimeError(f"{where}: there is no clip {clip_id!r}")
        c = self.clips[clip_id]
        if c.kind and c.kind not in ("video", "audio"):
            raise TimeError(f"{where}: clip {clip_id} is a {c.kind} clip; src: takes a video or audio clip")
        if c.loop:
            raise TimeError(f"{where}: clip {clip_id} loops, so a source second plays more than once; use "
                            f"clip:{clip_id}+seconds")
        if c.retimed:
            raise TimeError(f"{where}: clip {clip_id} {c.retimed}, so source seconds are not film times; use "
                            f"clip:{clip_id}+seconds")
        if seconds < c.trim_in - 1e-6:
            raise TimeError(f"{where} is before clip {clip_id}'s in point (trim_in {c.trim_in:g} s): that part of the "
                            "source is cut away")
        return self.start(clip_id) + (seconds - c.trim_in) / (c.rate or 1.0)

    def film_end(self) -> float:
        if self._auto_end and ("film",) in self._stack:
            raise _NeedsEnd()
        return self._get(("film",))

    # public helpers
    def start(self, clip_id: str) -> float:
        return self.clip(clip_id, False)

    def end(self, clip_id: str) -> float:
        return self.clip(clip_id, True)

    def span(self, clip_id: str) -> tuple[float, float]:
        return self.start(clip_id), self.end(clip_id)

    def film_end_source(self) -> str:
        if self.duration is not None:
            return "set by duration"
        if self.voice_end is not None:
            return f"voice end + {TAIL_S:g} s"
        return "last clip end"

    # internals
    def _get(self, key: tuple) -> float:
        known = self._memo.get(key)
        if isinstance(known, TimeError):
            raise known
        if known is not None:
            return known
        if key in self._stack:
            raise CycleError(f"these times refer to each other in a cycle: {self._cycle(key)}; "
                             "anchor one of them on a number, a voice line or another clip")
        self._stack.append(key)
        try:
            value = self._compute(key)
        except TimeError as exc:
            self._memo[key] = exc
            raise
        finally:
            self._stack.pop()
        self._memo[key] = value
        return value

    def _cycle(self, key: tuple) -> str:
        loop = self._stack[self._stack.index(key):] + [key]
        return " -> ".join(_name(k) for k in loop)

    def _compute(self, key: tuple) -> float:
        if key == ("film",):
            return self._film()
        if key[0] == "mark":
            return _at(self.markers[key[1]], self, f"marker {key[1]}")
        _, cid, edge = key
        c = self.clips[cid]
        if edge == "start":
            return _at(c.start, self, f"clip {cid} start")
        if c.end is not None:
            return _at(c.end, self, f"clip {cid} end")
        if c.dur is None:
            raise TimeError(f"clip {cid} needs end (a Time) or dur (seconds)")
        return self.start(cid) + float(c.dur)

    def _film(self) -> float:
        if self.duration is not None:
            t = _at(self.duration, self, "duration")
            if t <= 0:
                raise TimeError("duration must be more than 0 s")
            return t
        if self.voice_end is not None:
            return self.voice_end + TAIL_S
        ends = []
        self._auto_end = True
        try:
            for cid, c in self.clips.items():
                if not c.counts:
                    continue
                try:
                    ends.append(self.end(cid))
                except (_NeedsEnd, TimeError):
                    continue
        finally:
            self._auto_end = False
        if not ends:
            raise TimeError("the film has no length: set duration, add a voice, or give a clip a fixed end")
        return max(ends)


def _at(value, sched: Schedule, what: str) -> float:
    try:
        return resolve(value, sched)
    except _NeedsEnd:
        raise
    except CycleError:
        raise                               # the loop itself says where
    except TimeError as exc:
        msg = str(exc)
        if msg.startswith(what):
            raise
        raise TimeError(f"{what} {value!r}: {msg}") from None


def _name(key: tuple) -> str:
    if key == ("film",):
        return "end"
    if key[0] == "mark":
        return f"mark:{key[1]}"
    _, cid, edge = key
    return f"clip:{cid}{'.end' if edge == 'end' else ''}"


def simple_context(lines=(), clips: dict[str, tuple[float, float]] | None = None,
                   end: float | Callable[[], float] | None = None) -> TimeContext:
    """A fixed context (tests, tools): voice lines [(t0, t1)], clip spans {id: (start, end)}, film end."""
    clips = dict(clips or {})
    sched = Schedule(lines, {k: ClipTiming(a, b) for k, (a, b) in clips.items()},
                     duration=(end() if callable(end) else end))
    return sched
