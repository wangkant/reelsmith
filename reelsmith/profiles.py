"""Output profiles (canvas, safe area, delivery limits) and visual themes.

Generic canvases (landscape, vertical, square, portrait) keep words inside a title-safe margin and set no delivery
limits; platform profiles (douyin, douyin-long, tiktok, shorts, reels, youtube) carry the platform's UI-safe area,
length and size limits and loudness. workspace.json `profiles` adds named custom profiles and a project's `profile`
may be one inline: {"base": name, field: value, ...}.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction

REFERENCE_SIDE = 1080           # pixel thresholds (text sizes, legibility) are written for this short side
TITLE_SAFE = 0.05               # generic canvases: words stay 5 % in from every edge
CAPTION_BAND_PX = 200           # the default captions band at REFERENCE_SIDE (Captions.tsx)
SIDES = (64, 4096)
FPS = (1, 120)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Profile:
    name: str
    width: int
    height: int
    fps: float                      # whole (30) or an NTSC rate (30000/1001 = 29.97...)
    safe: Box                       # every glyph stays inside; backgrounds may bleed
    captions: Box                   # where a captions track without a box sits
    min_s: float | None             # delivery limits; None: no limit
    max_s: float | None
    target_s: tuple[float, float] | None
    max_mb: float | None
    lufs: float
    peak_db: float = -1.0
    max_still_s: float | None = 5.0     # longest stretch without any motion; None: not checked
    max_black_ratio: float = 0.10
    vcodec: str = "h264"
    acodec: str = "aac"
    require_audio: bool = True          # False: a silent film is delivered as it is
    ui: bool = True                     # outside the safe area is the platform's UI (False: a title-safe margin)

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def scale(self) -> float:
        """Pixel thresholds are written for a 1080 px short side; this canvas's factor."""
        return min(self.width, self.height) / REFERENCE_SIDE

    def px(self, value: float) -> float:
        return value * self.scale

    @property
    def orientation(self) -> str:
        return "landscape" if self.width > self.height else "portrait" if self.height > self.width else "square"

    def outside_safe(self) -> list[tuple[int, int, int, int]]:
        """The four bands around the safe area (x, y, w, h): the platform's UI, or the title-safe margin."""
        s, W, H = self.safe, self.width, self.height
        bands = [(0, 0, W, s.y), (0, s.y + s.h, W, H - s.y - s.h),
                 (0, s.y, s.x, s.h), (s.x + s.w, s.y, W - s.x - s.w, s.h)]
        return [b for b in bands if b[2] > 0 and b[3] > 0]


def title_safe(width: int, height: int, margin: float = TITLE_SAFE) -> Box:
    mx, my = round(width * margin), round(height * margin)
    return Box(mx, my, width - 2 * mx, height - 2 * my)


def caption_band(safe: Box, width: int, height: int) -> Box:
    """The safe area's bottom band, 200 px at a 1080 px short side."""
    band = min(safe.h, max(1, round(CAPTION_BAND_PX * min(width, height) / REFERENCE_SIDE)))
    return Box(safe.x, safe.y + safe.h - band, safe.w, band)


def _generic(name: str, width: int, height: int) -> Profile:
    safe = title_safe(width, height)
    return Profile(name, width, height, 30, safe, caption_band(safe, width, height), None, None, None, None, -14.0,
                   max_still_s=None, require_audio=False, ui=False)


LANDSCAPE = _generic("landscape", 1920, 1080)
VERTICAL = _generic("vertical", 1080, 1920)
SQUARE = _generic("square", 1080, 1080)
PORTRAIT = _generic("portrait", 1080, 1350)
# YouTube normalises playback to about -14 LUFS; its own caps (12 h, 256 GB) are past anything rendered here.
YOUTUBE = replace(LANDSCAPE, name="youtube", require_audio=True)
# Douyin on a phone covers the top ~200 px, the right rail (x >= 920, y 720-1640) and the bottom bar (y >= 1480).
DOUYIN = Profile("douyin", 1080, 1920, 30, Box(40, 220, 840, 1240), Box(40, 1260, 840, 200),
                 20, 90, (45, 75), 80, -10.0)
# Douyin's longer explainers (a how-to, a checklist worth saving): the same screen, more time.
DOUYIN_LONG = replace(DOUYIN, name="douyin-long", min_s=60, max_s=300, target_s=(90, 180), max_mb=250)
# TikTok and Shorts lay their chrome out much the same; the right rail sits a little lower on Shorts.
TIKTOK = Profile("tiktok", 1080, 1920, 30, Box(60, 200, 820, 1260), Box(60, 1260, 820, 200),
                 15, 180, (30, 75), 250, -14.0)
SHORTS = Profile("shorts", 1080, 1920, 30, Box(60, 180, 820, 1300), Box(60, 1280, 820, 200),
                 15, 180, (30, 60), 250, -14.0)
# Instagram Reels: Meta's safe zone keeps the top 14 % and bottom 35 % free (profile, caption, audio, buttons) and
# 6 % at the sides; the action rail on the right takes more. Reels run 3-180 s; uploads stop at 4 GB.
REELS = Profile("reels", 1080, 1920, 30, Box(66, 250, 884, 1000), Box(66, 1050, 884, 200),
                3, 180, (15, 60), 4000, -14.0)

PROFILES = {p.name: p for p in (LANDSCAPE, VERTICAL, SQUARE, PORTRAIT, YOUTUBE, DOUYIN, DOUYIN_LONG, TIKTOK, SHORTS,
                                REELS)}
DEFAULT_PROFILE = "landscape"
FIELDS = ("width", "height", "fps", "safe", "captions", "min_s", "max_s", "target_s", "max_mb", "lufs", "peak_db",
          "max_still_s", "max_black_ratio", "require_audio", "ui")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CANVAS = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*(?:@\s*(\d+(?:\.\d+)?(?:/\d+)?)\s*)?$")
NTSC = Fraction(1000, 1001)


class ProfileError(ValueError):
    """A profile that cannot be used; the message names the field."""


def get_profile(name: str | None = None, custom: dict | None = None) -> Profile:
    """A built-in profile or one of `custom` (workspace.json profiles, built) by name; default landscape."""
    key = name or DEFAULT_PROFILE
    if custom and key in custom:
        return custom[key]
    if key not in PROFILES:
        raise ProfileError(f"unknown profile {key!r}; one of {', '.join([*PROFILES, *(custom or {})])}")
    return PROFILES[key]


def choose(value, fallback=None, custom: dict | None = None, where: str = "project.json profile") -> Profile:
    """A project's profile: its own value (a name or an inline object), else `fallback` (workspace.json's)."""
    if value in (None, "", {}):
        value, where = fallback, "workspace.json profile"
    if isinstance(value, dict):
        return make_profile(value, custom, where=where)
    if value is not None and not isinstance(value, str):
        raise ProfileError(f"{where} must be a profile name or an object {{\"base\": ..., \"width\": ...}}")
    return get_profile(value or None, custom)


def build_profiles(specs) -> dict[str, Profile]:
    """workspace.json `profiles` ({name: {base?, field: value}}) built and checked; ProfileError names the bad one."""
    if specs is None:
        return {}
    if not isinstance(specs, dict):
        raise ProfileError("workspace.json profiles must be an object {name: {\"base\": ..., \"width\": ...}}")
    out: dict[str, Profile] = {}

    def build(name: str, chain: tuple) -> Profile:
        if name in out:
            return out[name]
        where = f"workspace.json profiles.{name}"
        if name in chain:
            raise ProfileError(f"{where}: base profiles loop ({' -> '.join((*chain, name))})")
        if name in PROFILES:
            raise ProfileError(f"{where}: {name!r} is a built-in profile; give yours another name with "
                               f"\"base\": \"{name}\"")
        if not NAME.match(name):
            raise ProfileError(f"{where}: a profile name is 1-64 letters, digits, _ or -")

        def base_of(b: str) -> Profile:
            return build(b, (*chain, name)) if b in specs and b not in PROFILES else get_profile(b, out)
        out[name] = make_profile(specs[name], name=name, where=where, base_of=base_of)
        return out[name]

    for n in specs:
        build(n, ())
    return out


def parse_canvas(text: str) -> dict:
    """ "1920x1080", "1920x1080@25" or "1920x1080@29.97" as profile fields {width, height, fps?}."""
    m = _CANVAS.match(str(text or ""))
    if not m:
        raise ProfileError(f"canvas {text!r} must look like 1920x1080 or 1920x1080@25 (width x height @ fps)")
    out = {"width": int(m.group(1)), "height": int(m.group(2))}
    if m.group(3):
        fps = parse_fps(m.group(3), f"canvas {text!r} fps")
        out["fps"] = fps if isinstance(fps, int) else fps_ratio(fps)    # exact in project.json
    return out


def parse_fps(value, where: str = "fps") -> float:
    """A frame rate: a whole number 1-120, a ratio "30000/1001", or a decimal; 23.976, 29.97, 59.94 (and any rate
    within 0.002 of n x 1000/1001) mean the exact NTSC rate. Whole rates come back as ints."""
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError
        text = str(value).strip()
        num, slash, den = text.partition("/")
        rate = Fraction(int(num), int(den)) if slash else Fraction(text)
    except (ValueError, ZeroDivisionError):
        rate = None
    if rate is not None and rate.denominator != 1:
        ntsc = round(rate / NTSC) * NTSC
        if ntsc.denominator != 1 and abs(rate - ntsc) <= Fraction(2, 1000):
            rate = ntsc
    if rate is None or not FPS[0] <= rate <= FPS[1]:
        raise ProfileError(f"{where} must be a frame rate {FPS[0]}-{FPS[1]}: a whole number (25, 30), an NTSC rate "
                           f"(23.976, 29.97, 59.94) or a ratio such as \"30000/1001\" (got {value!r})")
    return int(rate) if rate.denominator == 1 else float(rate)


def fps_ratio(fps: float) -> str:
    """ffmpeg's form of a rate: "30" or "30000/1001"."""
    r = Fraction(fps).limit_denominator(1001)
    return str(r.numerator) if r.denominator == 1 else f"{r.numerator}/{r.denominator}"


def fps_label(fps: float) -> str:
    """A rate as people write it: 30, 29.97, 23.976."""
    return str(int(fps)) if float(fps).is_integer() else f"{fps:.3f}".rstrip("0").rstrip(".")


def make_profile(spec, custom: dict | None = None, name: str = "custom", where: str = "project.json profile",
                 base_of=None) -> Profile:
    """A profile from {base?, field: value}: the base (default landscape) with the fields laid over it. A new canvas
    size without a safe area scales the base's; without captions they take the new safe area's bottom band."""
    if not isinstance(spec, dict):
        raise ProfileError(f"{where} must be an object {{\"base\": ..., \"width\": ..., ...}}")
    unknown = sorted(set(spec) - {"base", *FIELDS})
    if unknown:
        raise ProfileError(f"{where}: unknown field(s) {', '.join(unknown)}; allowed: base, {', '.join(FIELDS)}")
    b = spec.get("base")
    if b is not None and not isinstance(b, str):
        raise ProfileError(f"{where}.base must be a profile name")
    try:
        base = (base_of or (lambda n: get_profile(n, custom)))(b) if b else PROFILES[DEFAULT_PROFILE]
    except ProfileError as exc:
        if str(exc).startswith(("workspace.json", "project.json")):
            raise                                   # a broken base profile names itself
        raise ProfileError(f"{where}.base: {exc}") from None
    w = _whole(spec, "width", base.width, SIDES, where, even=True)
    h = _whole(spec, "height", base.height, SIDES, where, even=True)
    fps = parse_fps(spec["fps"], f"{where}.fps") if "fps" in spec else base.fps
    sized = (w, h) != (base.width, base.height)
    if "safe" in spec:
        safe = _box(spec["safe"], w, h, f"{where}.safe")
    else:
        safe = _scaled(base.safe, base, w, h) if sized else base.safe
    if "captions" in spec:
        captions = _box(spec["captions"], w, h, f"{where}.captions")
    else:
        captions = caption_band(safe, w, h) if sized or "safe" in spec else base.captions
    values = {k: _limit(spec, k, getattr(base, k), where) for k in ("min_s", "max_s", "max_mb", "max_still_s")}
    if values["min_s"] is not None and values["max_s"] is not None and values["min_s"] > values["max_s"]:
        raise ProfileError(f"{where}: min_s {values['min_s']:g} is over max_s {values['max_s']:g}")
    return replace(base, name=name, width=w, height=h, fps=fps, safe=safe, captions=captions,
                   target_s=_target(spec, base.target_s, where), lufs=_number(spec, "lufs", base.lufs, -70, -1, where),
                   peak_db=_number(spec, "peak_db", base.peak_db, -12, 0, where),
                   max_black_ratio=_number(spec, "max_black_ratio", base.max_black_ratio, 0, 1, where),
                   require_audio=_flag(spec, "require_audio", base.require_audio, where),
                   ui=_flag(spec, "ui", base.ui, where), **values)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _whole(spec: dict, key: str, default: int, span: tuple, where: str, even: bool = False) -> int:
    v = spec.get(key, default)
    ok = _is_num(v) and float(v).is_integer() and span[0] <= v <= span[1] and (not even or int(v) % 2 == 0)
    if not ok:
        kind = "an even whole number" if even else "a whole number"
        why = " (h264 needs even sides)" if even else ""
        raise ProfileError(f"{where}.{key} must be {kind} {span[0]}-{span[1]}{why} (got {v!r})")
    return int(v)


def _number(spec: dict, key: str, default: float, lo: float, hi: float, where: str) -> float:
    v = spec.get(key, default)
    if not _is_num(v) or not lo <= v <= hi:
        raise ProfileError(f"{where}.{key} must be a number {lo:g} to {hi:g} (got {v!r})")
    return float(v)


def _limit(spec: dict, key: str, default, where: str):
    v = spec.get(key, default)
    if v is None:
        return None
    if not _is_num(v) or v <= 0:
        raise ProfileError(f"{where}.{key} must be a number > 0, or null for no limit (got {v!r})")
    return v


def _flag(spec: dict, key: str, default: bool, where: str) -> bool:
    v = spec.get(key, default)
    if not isinstance(v, bool):
        raise ProfileError(f"{where}.{key} must be true or false (got {v!r})")
    return v


def _target(spec: dict, default, where: str):
    v = spec.get("target_s", default)
    if v is None:
        return None
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_num(t) and t > 0 for t in v) and v[0] <= v[1]):
        raise ProfileError(f"{where}.target_s must be [min, max] seconds, or null (got {v!r})")
    return (v[0], v[1])


def _box(value, width: int, height: int, where: str) -> Box:
    if isinstance(value, dict) and set(value) == {"x", "y", "w", "h"}:
        value = [value["x"], value["y"], value["w"], value["h"]]
    if not (isinstance(value, (list, tuple)) and len(value) == 4 and all(_is_num(v) for v in value)):
        raise ProfileError(f"{where} must be {{\"x\", \"y\", \"w\", \"h\"}} or [x, y, w, h] in canvas pixels "
                           f"(got {value!r})")
    x, y, w, h = (int(round(v)) for v in value)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ProfileError(f"{where} [{x}, {y}, {w}, {h}] must lie inside the {width}x{height} canvas with w and h "
                           "> 0")
    return Box(x, y, w, h)


def _scaled(box: Box, base: Profile, width: int, height: int) -> Box:
    sx, sy = width / base.width, height / base.height
    x, y = round(box.x * sx), round(box.y * sy)
    return Box(x, y, min(width - x, round(box.w * sx)), min(height - y, round(box.h * sy)))


@dataclass(frozen=True)
class Theme:
    name: str
    paper: str          # light ground
    ink: str            # text on paper
    night: str          # dark ground
    snow: str           # text on night
    accent: str         # the one number that matters, the stamp
    gold: str
    good: str
    bad: str
    muted: str
    fonts: dict = field(default_factory=lambda: {"sans": "sans", "display": "display", "serif": "serif"})

    def to_json(self) -> dict:
        return asdict(self)


PAPER = Theme("paper", "#F3EBDD", "#1E1A16", "#16130F", "#F7F1E6", "#C8372D", "#D9A441", "#2E8B57", "#C8372D",
              "#7A6F62")
NIGHT = Theme("night", "#E9EEF3", "#10151C", "#0E1319", "#F2F5F8", "#FF5A3C", "#FFC24B", "#3BC48A", "#FF5A3C",
              "#8A96A3")

THEMES = {t.name: t for t in (PAPER, NIGHT)}
