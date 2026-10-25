"""Checks: the project (validation, owner rules, advice), the layout (from inspect.json) and the delivered film."""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

from . import media
from .issues import Issue
from .profiles import REFERENCE_SIDE, Profile
from .workspace import PROJECT_FILE, WorkspaceError, default_rules, find_workspace, profile_for, project_root

TITLE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
HTTP_URL = re.compile(r"^https?://\S+$", re.I)
LEVEL_ORDER = {"error": 0, "warning": 1, "advice": 2}
STILL_TYPES = {"image", "evidence"}     # videos and components move by themselves
VISIBLE_OPACITY = 0.1          # fainter text is decoration, not something to read
# px thresholds below are for a canvas whose short side is 1080 px; each canvas scales them (Profile.scale)
SMALL_TEXT_PX = 28             # the renderer's own min_size for fitted text
TINY_TEXT_PX = 20
MIN_CONTRAST = 3.0             # WCAG's floor for large text
LOW_CONTRAST = 2.0             # between the two, a clearly different hue still reads
DISTINCT_DELTA_E = 50.0
STEADY_OPACITY = 0.75          # text fading in or out is judged where it is whole
OVERLAP_OPACITY = 0.35         # fainter text under other text is a backdrop, not a collision
EVIDENCE_MIN_PX = 40           # the house minimum for anything a viewer must read
INK_PER_EM = 0.85              # a CJK glyph's ink is about this much of its font size
SILENT_LUFS = -45.0
LUFS_TOLERANCE = 3.0
MAX_LIST = 25


def _mod(name: str):
    # neighbours are imported late so a broken one fails the call that needs it, not the whole package
    return importlib.import_module(f"{__package__}.{name}")


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: LEVEL_ORDER.get(i.level, 9))


# ------------------------------------------------------------------ project
def describe_load_error(exc: Exception) -> list[str]:
    """A load failure as short, fixable lines (pydantic errors one per line)."""
    if isinstance(exc, FileNotFoundError):
        return [f"{PROJECT_FILE} not found: write it (see the manual's project example)"]
    if isinstance(exc, json.JSONDecodeError):
        return [f"not valid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"]
    errs = getattr(exc, "errors", None)
    if callable(errs):
        try:
            rows = [f"{'.'.join(map(str, e.get('loc', ()))) or '(root)'}: {e.get('msg')}" for e in errs()]
        except Exception:  # noqa: BLE001 - fall back to the plain text
            rows = []
        if rows:
            more = [f"... and {len(rows) - MAX_LIST} more"] if len(rows) > MAX_LIST else []
            return rows[:MAX_LIST] + more
    return [str(exc) or type(exc).__name__]


def load_and_validate(project: str | Path):
    """(doc | None, issues) from document.load + document.validate; a project that will not load becomes issues."""
    document = _mod("document")
    try:
        doc = document.load(project)
    except Exception as exc:  # noqa: BLE001 - every load failure is the agent's to fix
        return None, [Issue("error", PROJECT_FILE, m) for m in describe_load_error(exc)]
    try:
        issues = list(document.validate(project, doc))
    except Exception as exc:  # noqa: BLE001
        issues = [Issue("error", "validate", f"validation stopped: {exc}")]
    return doc, issues


def project_meta(doc, project: str | Path) -> dict:
    """meta as a plain dict, from the loaded document or, failing that, the file."""
    meta = getattr(doc, "meta", None)
    if hasattr(meta, "model_dump"):
        return meta.model_dump()
    if isinstance(meta, dict):
        return meta
    try:
        data = json.loads((project_root(project) / PROJECT_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return (data.get("meta") or {}) if isinstance(data, dict) else {}


def _source_ok(s) -> bool:
    if hasattr(s, "model_dump"):
        s = s.model_dump()
    return isinstance(s, dict) and bool(HTTP_URL.match(str(s.get("url") or "").strip()))


def rule_issues(meta: dict, rules: dict) -> list[Issue]:
    """The owner's hard rules on the post (title, sources, banned words): errors block delivery. An empty title is
    a warning only where the owner rules on titles (max_title or max_title_numbers)."""
    hard = rules.get("hard") or {}
    out: list[Issue] = []
    title = str(meta.get("title") or "").strip()
    if not title and (hard.get("max_title") is not None or hard.get("max_title_numbers") is not None):
        out.append(Issue("warning", "meta.title", "empty: the post needs a title (edit op set, path meta.title)"))
    max_title = hard.get("max_title")
    if max_title is not None and len(title) > max_title:
        out.append(Issue("error", "meta.title", f"{len(title)} characters; the owner's limit is {max_title}"))
    max_numbers = hard.get("max_title_numbers")
    numbers = TITLE_NUMBER.findall(title)
    if max_numbers is not None and len(numbers) > max_numbers:
        out.append(Issue("error", "meta.title", f"{len(numbers)} numbers ({', '.join(numbers)}); the owner allows "
                                                f"{max_numbers}: keep the numbers for the film itself"))
    sources = meta.get("sources") or []
    good = [s for s in sources if _source_ok(s)] if isinstance(sources, list) else []
    min_sources = hard.get("min_sources")
    if min_sources and len(good) < min_sources:
        out.append(Issue("error", "meta.sources", f"{len(good)} source(s) with an http(s) url; at least {min_sources} "
                                                  "needed, each {\"title\": ..., \"url\": \"https://...\"}"))
    fields = {k: str(meta.get(k) or "") for k in ("title", "desc", "topic")}
    for word in hard.get("banned") or []:
        if not word:
            continue
        hits = [k for k, v in fields.items() if word.lower() in v.lower()]
        if hits:
            out.append(Issue("error", "meta." + "/".join(hits), f"contains the banned word {word!r}: reword it"))
    return out


def _fps(resolved: dict) -> float:
    return float(resolved.get("fps") or 30)


def _scale(resolved: dict) -> float:
    """The canvas's short side / 1080: what px thresholds are multiplied by."""
    w, h = resolved.get("width"), resolved.get("height")
    ok = all(isinstance(v, (int, float)) and v > 0 for v in (w, h))
    return min(w, h) / REFERENCE_SIDE if ok else 1.0


def target_of(rules: dict, profile: Profile):
    """advice target_s as [min, max]: as set, the profile's for true, None when unset (or the profile has none)."""
    target = (rules.get("advice") or {}).get("target_s")
    if target is True:
        return list(profile.target_s) if profile.target_s else None
    return target if isinstance(target, list) else None


def _visual_clips(resolved: dict) -> list[dict]:
    return [c for t in resolved.get("tracks") or [] if t.get("kind") == "visual" and not t.get("hidden")
            for c in t.get("clips") or [] if _visible(c)]


def _visible(clip: dict) -> bool:
    op = (clip.get("style") or {}).get("opacity", 1)
    return not isinstance(op, (int, float)) or op > 0


def _has_words(clip: dict) -> bool:
    content = clip.get("content") or {}
    if clip.get("type") == "text":
        return any(str(r.get("text") or "").strip() for r in content.get("runs") or [])
    if clip.get("type") == "evidence":
        return True
    if clip.get("type") == "component":
        return _any_words(content.get("props"))
    return False


def _any_words(value) -> bool:
    if isinstance(value, str):
        return len(value.strip()) >= 2
    if isinstance(value, dict):
        # asset refs carry src strings, not words
        return "src" not in value and any(_any_words(v) for v in value.values())
    if isinstance(value, list):
        return any(_any_words(v) for v in value)
    return False


def advice_issues(resolved: dict, rules: dict, profile: Profile) -> list[Issue]:
    """Information for the editor (never blocks): the hook, long single visuals, length against the target."""
    advice = rules.get("advice") or {}
    fps = _fps(resolved)
    total = (resolved.get("durationInFrames") or 0) / fps
    clips = _visual_clips(resolved)
    out: list[Issue] = []

    hook = float(advice.get("hook_seconds") or 0)
    if hook > 0:
        hook_f = hook * fps
        if not any((c.get("from") or 0) <= 0 < (c.get("from") or 0) + (c.get("dur") or 0) for c in clips):
            out.append(Issue("advice", "hook", "nothing on screen at 0.0 s: the film opens on an empty frame"))
        words = any((c.get("from") or 0) < hook_f and _has_words(c) for c in clips)
        captions = any((it.get("from") or 0) < hook_f for t in resolved.get("tracks") or []
                       if t.get("kind") == "captions" and not t.get("hidden") for it in t.get("items") or [])
        if not words and not captions:
            out.append(Issue("advice", "hook", f"no words on screen in the first {hook:g} s, where viewers decide: "
                                               "put the hook in a text clip (or captions) from 0 s"))

    max_same = advice.get("max_same_visual_s")
    if max_same:
        for c in clips:
            secs = (c.get("dur") or 0) / fps
            if c.get("type") in STILL_TYPES and secs > max_same and not _moves(c):
                out.append(Issue("advice", f"{c.get('id')} @ {(c.get('from') or 0) / fps:.1f}s",
                                 f"one still {c.get('type')} on screen for {secs:.1f} s with nothing moving it "
                                 f"(advice: <= {max_same:g} s): split it, cut to another visual, cover part of it "
                                 "or move it (motion, keyframes)"))

    target = target_of(rules, profile)
    if target and total and not target[0] <= total <= target[1]:
        out.append(Issue("advice", "duration", f"{total:.1f} s; the target is {target[0]:g}-{target[1]:g} s"))
    return out


def _moves(clip: dict) -> bool:
    """Any keyframed value that changes (motion sugar arrives as zoom/pan keyframes)."""
    return any(len({k.get("v") for k in frames or []}) > 1 for frames in (clip.get("keyframes") or {}).values())


def _value_at_start(frames: list | None, default: float) -> float:
    ks = sorted((k for k in frames or [] if isinstance(k.get("v"), (int, float))), key=lambda k: k.get("f") or 0)
    return float(ks[0]["v"]) if ks else default


def _cover_problem(clip: dict) -> str:
    """Why the clip's words are not readable on its first frame ("" when they are)."""
    if clip.get("enter"):
        return f"it enters ({clip['enter'].get('preset')})"
    reveal = (clip.get("content") or {}).get("reveal") or {}
    if clip.get("type") == "text" and reveal.get("mode") not in (None, "none"):
        return f"it is revealed by {reveal.get('mode')}, so it starts half-typed"
    kf = clip.get("keyframes") or {}
    style = clip.get("style") or {}
    base = style.get("opacity", 1) if isinstance(style.get("opacity", 1), (int, float)) else 1
    if _value_at_start(kf.get("opacity"), base) < 0.5:
        return "it fades in (opacity keyframes)"
    if _value_at_start(kf.get("scale"), 1) < 0.5:
        return "it grows in (scale keyframes)"
    return ""


def cover_issues(resolved: dict) -> list[Issue]:
    """Frame 0 is the cover: words on it should be whole, not mid-animation."""
    clips = [c for c in _visual_clips(resolved) if (c.get("from") or 0) <= 0 < (c.get("from") or 0) + (c.get("dur") or 0)]
    if not clips:
        return []                           # the hook advice already says the frame is empty
    out, readable = [], False
    for c in clips:
        if not _has_words(c):
            continue
        why = _cover_problem(c)
        if why:
            out.append(Issue("warning", f"{c.get('id')} @ 0.0s", f"{why}: frame 0 is the cover, and there it is not "
                                                                  "readable yet; start it whole at 0 s or start the "
                                                                  "animation later"))
        else:
            readable = True
    captions = any((it.get("from") or 0) <= 0 < (it.get("to") or 0) for t in resolved.get("tracks") or []
                   if t.get("kind") == "captions" and not t.get("hidden") for it in t.get("items") or [])
    if not readable and not captions:
        out.append(Issue("warning", "cover", "nothing readable on screen at 0.0 s: frame 0 is the cover; put the "
                                             "hook's words there from the first frame (no enter, no reveal)"))
    return out


# ------------------------------------------------------------------ evidence legibility
_INK: dict[tuple, float | None] = {}


def ink_line_px(path: Path, box) -> float | None:
    """The tallest text line inside `box` (capture px) of a picture, measured from its ink; None when unreadable."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size, tuple(box))
    if key not in _INK:
        _INK[key] = _measure_ink(path, box)
    return _INK[key]


def _measure_ink(path: Path, box) -> float | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            gray = im.convert("L")
    except Exception:  # noqa: BLE001 - no Pillow or an odd file: no estimate
        return None
    x, y, w, h = (float(v) for v in box)
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(gray.width, int(x + w)), min(gray.height, int(y + h))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = gray.crop((x0, y0, x1, y1))
    hist = crop.histogram()
    bg = max(range(256), key=hist.__getitem__)
    ink = crop.point([255 if abs(v - bg) > 60 else 0 for v in range(256)])
    column = ink.resize((1, ink.height), Image.BOX)                     # each row's share of ink, 0..255
    rows = list(getattr(column, "get_flattened_data", column.getdata)())
    runs, cur = [], 0
    for v in rows + [0]:
        if v >= 3:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    return float(max(runs)) if runs else None


def _evidence_scale(clip_type: str, w: float, h: float, bw: float, bh: float) -> float:
    """Capture px -> screen px as the kit's evidenceLayout fits the sentence (plus a fading margin) to the window;
    a component (EvidenceCard and the like) loses its card padding and source line first."""
    margin = max(10.0, min(40.0, 0.35 * bh))
    if clip_type != "evidence":
        pad = max(10.0, min(36.0, 0.045 * w))
        w, h = w - 2 * pad, h - 2 * pad - 50
    return max(0.0, min(w / (bw + 2 * margin), max(10.0, h) / bh, 2.0))


def _evidence_refs(value, key: str = ""):
    """Evidence asset refs in resolved component props, at any depth."""
    if isinstance(value, dict):
        if value.get("kind") == "evidence" and isinstance(value.get("src"), str) and re.match(r"^(asset|.+_asset)$",
                                                                                             key or ""):
            yield value
            return
        for k, v in value.items():
            yield from _evidence_refs(v, str(k))
    elif isinstance(value, list):
        for v in value:
            yield from _evidence_refs(v, key)


def evidence_issues(resolved: dict, root: Path) -> list[Issue]:
    """Evidence whose proving sentence will read small (estimated from the capture and the clip box)."""
    fps = _fps(resolved)
    least = EVIDENCE_MIN_PX * _scale(resolved)
    out: list[Issue] = []
    for c in _visual_clips(resolved):
        content = c.get("content") or {}
        refs = [content] if c.get("type") == "evidence" else \
            list(_evidence_refs(content.get("props"))) if c.get("type") == "component" else []
        box = c.get("box") or {}
        scale = (c.get("style") or {}).get("scale", 1)
        scale = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
        w, h = float(box.get("w") or 0) * scale, float(box.get("h") or 0) * scale
        for ref in refs:
            cap, size = ref.get("box"), ref.get("size")
            if not (isinstance(cap, list) and len(cap) == 4 and w > 0 and h > 0):
                continue
            line = ink_line_px(root / str(ref.get("src") or content.get("src") or ""), cap)
            if line is None or (size and line > 0.9 * min(cap[3], size[1]) and cap[3] > 200):
                continue                    # no text lines found, or a picture rather than lines
            px = line * _evidence_scale(c.get("type"), w, h, float(cap[2]), float(cap[3])) / INK_PER_EM
            if px < least:
                name = Path(str(ref.get("src") or "")).stem
                out.append(Issue("warning", f"{c.get('id')} @ {(c.get('from') or 0) / fps:.1f}s",
                                 f"the proving sentence of {name} will read at about {px:.0f} px (under "
                                 f"{least:.0f} px is hard to read on this canvas): its box {cap} is "
                                 f"{cap[2]:g} capture px wide for a {w:.0f} px clip; box a shorter span (capture "
                                 "again with a shorter match, one line), capture at phone width, or give the clip "
                                 "a wider box"))
    return out


def length_limits(profile: Profile) -> str:
    lo, hi = profile.min_s, profile.max_s
    if lo is not None and hi is not None:
        return f"{lo:g}-{hi:g} s"
    return f"at least {lo:g} s" if lo is not None else f"at most {hi:g} s" if hi is not None else "any length"


def outside_length(profile: Profile, seconds: float) -> bool:
    return (profile.min_s is not None and seconds < profile.min_s) or \
        (profile.max_s is not None and seconds > profile.max_s)


def duration_issues(resolved: dict, profile: Profile) -> list[Issue]:
    """The profile's length limits: the film check would refuse the film, so they block before a render is spent."""
    total = (resolved.get("durationInFrames") or 0) / _fps(resolved)
    if total and outside_length(profile, total):
        return [Issue("error", "duration", f"{total:.1f} s; {profile.name} takes {length_limits(profile)}")]
    return []


def check_project(project: str | Path) -> list[Issue]:
    """document validation + the owner's hard rules (errors) + advice; errors first."""
    root = project_root(project)
    try:
        ws = find_workspace(root)
    except WorkspaceError as exc:
        return [Issue("error", "workspace", str(exc))]
    rules = ws.rules if ws else default_rules()
    doc, issues = load_and_validate(root)
    if doc is None:
        return sort_issues(issues)
    issues += rule_issues(project_meta(doc, root), rules)
    if any(i.level == "error" and not i.where.startswith("meta") for i in issues):
        return sort_issues(issues)          # advice needs a project that resolves
    try:
        profile = profile_for(root, ws)
    except ValueError as exc:
        return sort_issues(issues + [Issue("error", "profile", str(exc))])
    try:
        resolved = _mod("resolve").resolve(root)
    except Exception as exc:  # noqa: BLE001 - a render would stop at the same place
        return sort_issues(issues + [Issue("error", "resolve", f"the project does not resolve: {exc}")])
    issues += duration_issues(resolved, profile) + advice_issues(resolved, rules, profile)
    issues += cover_issues(resolved) + evidence_issues(resolved, root)
    return sort_issues(issues)


# ------------------------------------------------------------------ layout (spec 12)
def _rect(value) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict) and all(k in value for k in "xywh"):
        value = [value["x"], value["y"], value["w"], value["h"]]
    if isinstance(value, (list, tuple)) and len(value) == 4 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        x, y, w, h = map(float, value)
        return (x, y, w, h) if w > 0 and h > 0 else None
    return None


def _sticks_out(rect, area) -> tuple[float, str]:
    """How far `rect` sticks out of `area` (px) and on which side."""
    x, y, w, h = rect
    ax, ay, aw, ah = area
    sides = {"left": ax - x, "right": x + w - (ax + aw), "top": ay - y, "bottom": y + h - (ay + ah)}
    side = max(sides, key=sides.get)
    return max(0.0, sides[side]), side


def _overlaps(rect, area) -> bool:
    x, y, w, h = rect
    ax, ay, aw, ah = area
    return x < ax + aw and x + w > ax and y < ay + ah and y + h > ay


def _tolerance(rect) -> float:
    # Range rects are line boxes: taller than the ink by part of the line height
    return min(20.0, max(6.0, 0.08 * rect[3]))


def transition_windows(resolved: dict | None) -> dict:
    """{clip id: [(from, to) frames]} of enter/exit animations, where a clip may sit off its place on purpose."""
    out: dict = {}
    for t in (resolved or {}).get("tracks") or []:
        for c in t.get("clips") or []:
            start, dur = c.get("from") or 0, c.get("dur") or 0
            spans = []
            if c.get("enter"):
                spans.append((start, start + (c["enter"].get("dur") or 0)))
            if c.get("exit"):
                spans.append((start + dur - (c["exit"].get("dur") or 0), start + dur))
            if c.get("transition"):             # transitions between clips on a track move them on purpose too
                spans.append((start, start + (c["transition"].get("dur") or 0)))
            leaving = c.get("transitionOut")
            if leaving:
                at = start + (leaving.get("at") or 0)
                spans.append((at, at + (leaving.get("dur") or 0)))
            if spans:
                out[c.get("id")] = spans
    return out


def _intersection(a, b) -> tuple[float, float]:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, w), max(0.0, h)


def _collide(a, b) -> bool:
    """Two text rects overlapping by more than line boxes touching."""
    w, h = _intersection(a, b)
    return w >= max(6.0, 0.3 * min(a[2], b[2])) and h >= max(6.0, 0.3 * min(a[3], b[3]))


# ------------------------------------------------------------------ contrast (sampled from the still)
_RGB = re.compile(r"^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+)(%?))?\s*\)$")
_BIN_LUT = [v & 0xE0 for v in range(256)] * 3


def parse_color(value) -> tuple[float, float, float, float] | None:
    """(r, g, b, alpha) of a computed CSS colour ("rgb(…)", "rgba(…)", "#rrggbb"); None for anything else."""
    s = str(value or "").strip().lower()
    m = _RGB.match(s)
    if m:
        a = 1.0 if m.group(4) is None else float(m.group(4)) / (100 if m.group(5) else 1)
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), max(0.0, min(1.0, a))
    if re.match(r"^#[0-9a-f]{6}$", s):
        return float(int(s[1:3], 16)), float(int(s[3:5], 16)), float(int(s[5:7], 16)), 1.0
    if re.match(r"^#[0-9a-f]{3}$", s):
        return float(int(s[1] * 2, 16)), float(int(s[2] * 2, 16)), float(int(s[3] * 2, 16)), 1.0
    return None


def _luminance(rgb) -> float:
    def lin(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a, b) -> float:
    """WCAG contrast of two colours (1..21)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _lab(rgb) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb[:3])
    xyz = ((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.9505, 0.2126 * r + 0.7152 * g + 0.0722 * b,
           (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.089)
    fx, fy, fz = (v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116 for v in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def color_distance(a, b) -> float:
    """CIE76 delta E: how different two colours look, hue and saturation included."""
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


def background_under(img, rect, scale: float, text_rgb) -> tuple[float, float, float] | None:
    """What the text has to stand out against: of the darkest and the lightest part of the rect (its 15th and
    85th luminance percentiles: the glyphs' own pixels sit at one end), the one further from the text colour.
    A rect all of the text's colour gives that colour back: text on its own colour."""
    x, y, w, h = rect
    box = (max(0, int(x * scale)), max(0, int(y * scale)), min(img.width, int((x + w) * scale)),
           min(img.height, int((y + h) * scale)))
    if box[2] - box[0] < 3 or box[3] - box[1] < 3:
        return None
    crop = img.crop(box)
    if crop.width * crop.height > 20000:           # nearest keeps real pixels; blending would invent colours
        k = (20000 / (crop.width * crop.height)) ** 0.5
        crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))), 0)
    total = crop.width * crop.height
    # 8 levels a channel, counted in C, ordered by luminance
    bins = sorted(((_luminance([v + 16 for v in rgb]), n, tuple(v + 16 for v in rgb))
                   for n, rgb in crop.point(_BIN_LUT).getcolors(total) or []))
    picks = []
    for want in (0.15, 0.85):
        acc = 0
        for _, n, rgb in bins:
            acc += n
            if acc >= want * total:
                picks.append(rgb)
                break
    return max(picks, key=lambda c: contrast_ratio(c, text_rgb)) if picks else None


class _Stills:
    """Each frame's still, opened once and only when a contrast check needs it."""

    def __init__(self, width: int):
        self.width, self.png, self.img = width, None, None

    def get(self, png):
        if png != self.png:
            self.png, self.img = png, None
            try:
                from PIL import Image
                with Image.open(png) as im:
                    self.img = im.convert("RGB")
            except Exception:  # noqa: BLE001 - no still, no Pillow: no contrast check
                self.img = None
        return self.img


def _text_contrast(stills: _Stills, png, rect, it) -> tuple[float, float, tuple] | None:
    """(WCAG ratio, delta E, background) of a text item against its still; None when it cannot be judged."""
    color = parse_color(it.get("color"))
    opacity = it.get("opacity", 1)
    if color is None or not png or color[3] < 0.2:
        return None
    if isinstance(opacity, (int, float)) and opacity < STEADY_OPACITY:
        return None                         # mid-fade: judged on the frames where it is whole
    img = stills.get(png)
    if img is None:
        return None
    bg = background_under(img, rect, img.width / stills.width, color)
    if bg is None:
        return None
    seen = tuple(color[3] * color[i] + (1 - color[3]) * bg[i] for i in range(3))
    return contrast_ratio(seen, bg), color_distance(seen, bg), bg


def hard_to_read(ratio: float, delta_e: float) -> bool:
    # saturated colours (red on near-black) read better than their luminance contrast says
    return ratio < MIN_CONTRAST and not (ratio >= LOW_CONTRAST and delta_e >= DISTINCT_DELTA_E)


def check_layout(inspect: dict, profile: Profile, resolved: dict | None = None,
                 ignore: set | None = None) -> list[Issue]:
    """Visible text outside the safe area or cut by the canvas edge (errors), text overflowing its clip box
    (warning), text under 28 px (warning; under 20 px an error; both at a 1080 px short side, scaled to the canvas),
    text of one clip over text of another (warning)
    and text on a background of about its own brightness (warning, sampled from the frame's still); one issue per
    clip and problem. With `resolved`, frames inside enter/exit animations are skipped; `ignore` = clip ids not
    measured (a crashed component's error box)."""
    canvas = (0.0, 0.0, float(profile.width), float(profile.height))
    s = profile.safe
    safe = (float(s.x), float(s.y), float(s.w), float(s.h))
    small, tiny = profile.px(SMALL_TEXT_PX), profile.px(TINY_TEXT_PX)
    transitions = transition_windows(resolved)
    ignore = set(ignore or ())
    stills = _Stills(profile.width)
    found: dict[tuple[str, str], dict] = {}

    def note(kind, who, frame, px, side, text, worst=max, **extra):
        entry = found.setdefault((kind, who), {"frames": [], "px": px, "side": side, "text": text, **extra})
        entry["frames"].append(frame)
        if worst(px, entry["px"]) != entry["px"] or not entry["text"]:
            entry.update(px=px, side=side, text=text or entry["text"], **extra)

    for fr in (inspect or {}).get("frames") or []:
        frame = fr.get("frame") or 0
        items = fr.get("items") or []
        boxes = {it.get("clip"): _rect(it.get("rect")) for it in items if it.get("kind") == "clip"}
        texts = []
        for it in items:
            rect = _rect(it.get("rect"))
            if it.get("kind") != "text" or rect is None or not _overlaps(rect, canvas):
                continue                        # wholly off canvas: nobody sees it
            opacity = it.get("opacity", 1)
            if isinstance(opacity, (int, float)) and opacity < VISIBLE_OPACITY:
                continue
            clip = it.get("clip")
            if clip in ignore or any(a <= frame < b for a, b in transitions.get(clip, ())):
                continue
            who, text, tol = str(clip or it.get("track") or "?"), str(it.get("text") or "").strip(), _tolerance(rect)
            texts.append((who, text, rect, it))
            px, side = _sticks_out(rect, canvas)
            if px > tol:
                note("cut", who, frame, px, side, text)
            else:
                px, side = _sticks_out(rect, safe)
                if px > tol:
                    note("unsafe", who, frame, px, side, text)
            box = boxes.get(clip)
            if box is not None:
                px, side = _sticks_out(rect, box)
                if px > tol:
                    note("overflow", who, frame, px, side, text)
            size = it.get("size")
            if isinstance(size, (int, float)) and 0 < size < small:
                note("tiny" if size < tiny else "small", who, frame, size, "", text, worst=min)
            judged = _text_contrast(stills, fr.get("png"), rect, it)
            if judged and hard_to_read(judged[0], judged[1]):
                note("contrast", who, frame, judged[0], "", text, worst=min, color=str(it.get("color")),
                     bg="#%02X%02X%02X" % tuple(min(255, round(v)) for v in judged[2]))
        for i, (a, ta, ra, ia) in enumerate(texts):
            for b, tb, rb, ib in texts[i + 1:]:
                if a == b or min(ia.get("opacity", 1), ib.get("opacity", 1)) < OVERLAP_OPACITY:
                    continue
                if _collide(ra, rb):
                    note(f"overlap:{b}", a, frame, 0.0, "", ta, other=b, other_text=tb)
    return sort_issues([_layout_issue(kind, who, e, profile) for (kind, who), e in found.items()])


def _layout_issue(kind: str, who: str, e: dict, profile: Profile) -> Issue:
    fps, s = profile.fps, profile.safe
    frames = sorted(set(e["frames"]))
    where = f"{who} @ {frames[0] / fps:.1f}s"
    also = ""
    if len(frames) > 1:
        also = f" (also at {', '.join(f'{f / fps:.1f}s' for f in frames[1:6])}{' ...' if len(frames) > 6 else ''})"
    quote = f"text \"{e['text']}\"" if e["text"] else "text"
    px, side = round(e["px"]), e["side"]
    if kind == "cut":
        return Issue("error", where, f"{quote} is cut by the canvas edge ({side}, {px} px){also}: move it in or "
                                     "make it smaller")
    if kind == "unsafe":
        why = "the platform's UI covers it there" if profile.ui else "that is the title-safe margin"
        return Issue("error", where, f"{quote} sits {px} px outside the safe area ({side}){also}: {why}; keep words "
                                     f"inside x {s.x}-{s.x + s.w}, y {s.y}-{s.y + s.h}")
    if kind in ("tiny", "small"):
        level = "error" if kind == "tiny" else "warning"
        small, tiny = f"{profile.px(SMALL_TEXT_PX):.4g}", f"{profile.px(TINY_TEXT_PX):.4g}"
        return Issue(level, where, f"{quote} is {e['px']:g} px{also}: under {small} px is hard to read on this "
                                   f"{profile.width}x{profile.height} canvas"
                                   f"{' and render refuses under ' + tiny if kind == 'tiny' else ''}"
                                   "; give it a bigger box or a bigger size, or say less")
    if kind.startswith("overlap"):
        other = f"text \"{e['other_text']}\" of {e['other']}" if e.get("other_text") else e["other"]
        return Issue("warning", where, f"{quote} overlaps {other}{also}: move one of them (captions sit at the bottom "
                                       "of the safe area) or keep them apart in time")
    if kind == "contrast":
        return Issue("warning", where, f"{quote} ({e['color']}) on a background of about {e['bg']} has contrast "
                                       f"{e['px']:.1f}:1{also} (aim for {MIN_CONTRAST:g}:1 or more): change the text "
                                       "colour, add a stroke or a bg plate, or darken/lighten what is behind it")
    return Issue("warning", where, f"{quote} overflows its clip box by {px} px ({side}){also}: make the box bigger, "
                                   "the text smaller, or use size \"fit\"")


# ------------------------------------------------------------------ the delivered film
def check_film(path: str | Path, profile: Profile) -> dict:
    """Delivery checks on a rendered film: frame, fps, codecs, length, size, loudness, black and frozen stretches."""
    path = Path(path)
    out: dict = {"ok": False, "path": str(path), "problems": [], "notes": []}
    problems = out["problems"]
    if not path.is_file() or path.stat().st_size == 0:
        problems.append(f"no film at {path}")
        out["why"] = problems[0]
        return out
    try:
        info = media.probe(path)
    except Exception as exc:  # noqa: BLE001 - unreadable is not passed
        problems.append(f"unreadable: {exc}")
        out["why"] = problems[0]
        return out
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        length = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        length = 0.0
    out.update(duration_s=round(length, 2), size_mb=round(path.stat().st_size / 1e6, 1))
    if video:
        _check_video(video, profile, out)
    else:
        problems.append("no video stream")
    if audio:
        _check_audio(path, audio, profile, out)
    elif profile.require_audio:
        problems.append("no audio stream")
    else:
        out["notes"].append("a silent film (this profile allows one)")
    if outside_length(profile, length):
        problems.append(f"{length:.1f} s long; {profile.name} takes {length_limits(profile)}")
    if profile.max_mb is not None and out["size_mb"] > profile.max_mb:
        problems.append(f"{out['size_mb']:.0f} MB; the upload limit is {profile.max_mb:g} MB (a shorter film, or less "
                        "noise and grain in the picture)")
    if video and length > 0:
        _check_motion(path, length, profile, out)
    out["ok"] = not problems
    out["why"] = "; ".join(problems)
    return out


def _check_video(video: dict, profile: Profile, out: dict) -> None:
    fps = media.frame_rate(video.get("avg_frame_rate")) or media.frame_rate(video.get("r_frame_rate"))
    out.update(width=video.get("width"), height=video.get("height"), fps=round(fps, 3),
               vcodec=video.get("codec_name"), pix_fmt=video.get("pix_fmt"))
    if (video.get("width"), video.get("height")) != (profile.width, profile.height):
        out["problems"].append(f"{video.get('width')}x{video.get('height')}; want {profile.width}x{profile.height}")
    if abs(fps - profile.fps) > 0.01:
        out["problems"].append(f"{fps:g} fps; want {profile.fps}")
    if video.get("codec_name") != profile.vcodec:
        out["problems"].append(f"video codec {video.get('codec_name')}; want {profile.vcodec}")


def _check_audio(path: Path, audio: dict, profile: Profile, out: dict) -> None:
    out["acodec"] = audio.get("codec_name")
    if audio.get("codec_name") != profile.acodec:
        out["problems"].append(f"audio codec {audio.get('codec_name')}; want {profile.acodec}")
    try:
        lufs, peak = media.loudness(path)
    except Exception:  # noqa: BLE001 - reported as unmeasured below
        lufs, peak = None, None
    out.update(lufs=lufs, peak_db=peak)
    if lufs is None or lufs < SILENT_LUFS:
        if profile.require_audio:
            out["problems"].append("the audio is near silent")
        else:
            out["notes"].append("the audio is silent (this profile allows a silent film)")
    elif abs(lufs - profile.lufs) > LUFS_TOLERANCE:
        out["notes"].append(f"loudness {lufs:.1f} LUFS; mastered for {profile.lufs:g}")


def _check_motion(path: Path, length: float, profile: Profile, out: dict) -> None:
    try:
        found = media.scan(path, length)
    except Exception as exc:  # noqa: BLE001 - unmeasured is not passed
        out["problems"].append(f"black/still scan failed: {exc}")
        return
    out.update(found)
    if found["black_ratio"] > profile.max_black_ratio:
        out["problems"].append(f"{found['black_s']} s of black ({found['black_ratio']:.0%}; max "
                               f"{profile.max_black_ratio:.0%})")
    if profile.max_still_s is not None and found["longest_still_s"] > profile.max_still_s:
        out["problems"].append(f"{found['longest_still_s']} s without any motion (max {profile.max_still_s:g} s): "
                               "move something in that stretch (keyframes, motion, a reveal)")
