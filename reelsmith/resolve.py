"""project.json -> resolved.json (spec 7, shaped as renderer/src/types.ts reads it), and describe (spec 8).

Times become frames (round(s x fps)); motion sugar becomes zoom/pan keyframes; captions are phrase-split and timed;
component props get frames for their Times and asset refs for their asset ids. resolve() skips clips it cannot time
(validation reports them); render and preview validate before they resolve.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

from . import document as D
from . import library, locales
from . import timeexpr as T
from .issues import Issue
from .workspace import WorkspaceError, find_workspace, project_paths, project_root

PHRASE_MIN = 4
_BREAK = re.compile(r"(?:[，。！？；：、!?;:…\n]|(?<!\d)[.,]|[.,](?!\d))+")
_CLOSERS = "”’」』）》】〕〉)]}"               # stay with the text before them
_OPENERS = "“‘「『（《【〔〈([{"               # stay with the text after them
_NUMERAL = "零〇一二三四五六七八九十百千万亿两"
_NUMBER = re.compile(rf"\d+(?:[.,]\d+)*[{_NUMERAL}]*|[{_NUMERAL}](?:[{_NUMERAL}点]*[{_NUMERAL}])?")
_UNITS = ("块钱", "元钱", "美元", "港元", "日元", "欧元", "英镑", "平方米", "平米", "公里", "千米", "厘米", "毫米",
          "公斤", "千克", "毫升", "小时", "分钟", "个月", "%", "‰", "℃", "元", "块", "角", "毛", "分", "号", "个", "只",
          "条", "张", "件", "位", "名", "人", "次", "倍", "成", "年", "月", "日", "天", "周", "岁", "吨", "斤", "克",
          "升", "米", "亩", "套", "台", "辆", "部", "家", "所", "款", "项", "杯", "瓶", "箱", "包", "页", "层", "楼",
          "度", "秒", "折", "股", "份", "篇", "本", "批", "颗", "粒", "口", "碗", "盒", "袋", "点")
_UNIT = re.compile(r"\s?[多余几]?[十百千万亿]*(?:" + "|".join(map(re.escape, _UNITS)) + ")?")
_LATIN = re.compile(r"[A-Za-z0-9]")
_ENDERS = set("的了着过吗呢吧啊呀么")                     # a phrase may end on these, never start with them
_STARTERS = set("是和与及而但却把被在从对向给让就都也还又再或跟比按为因由将到于很太最更不没这那")
_START_WORDS = ("所以", "因为", "如果", "然后", "但是", "可是", "不过", "而且", "并且", "或者", "其实", "结果")
_FUNCTION = _ENDERS | _STARTERS
# English words that lead into what follows them: a phrase does not end on one
_LATIN_LEADS = {"a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "but", "with", "from", "by",
                "into", "than"}
TEXT_DEFAULTS = {"font": "sans", "size": 64, "max_size": 160, "min_size": 28, "weight": 700, "color": None,
                 "accent": None, "align": "left", "valign": "top", "line_height": 1.15, "letter_spacing": 0,
                 "wrap": True, "balance": False, "stroke": None, "shadow": False, "bg": None}
NULLABLE = {"stroke", "bg", "color", "accent"}      # null means "none" here; elsewhere it means the default
SPRING = {"damping": 12.0, "stiffness": 140.0, "mass": 0.9}


class ResolveError(ValueError):
    """The project cannot be turned into a film description; the message says why."""


# ------------------------------------------------------------------ keyframe math (renderer/src/keyframes.ts)
def _spring_state(frame: float, fps: float, damping: float, stiffness: float, mass: float) -> float:
    """remotion springCalculation: position after `frame` frames, stepped one frame at a time."""
    current, velocity, last = 0.0, 0.0, 0.0
    frame = max(0.0, frame)

    def advance(now: float) -> None:
        nonlocal current, velocity, last
        dt = min(now - last, 64.0)
        c, m, k = damping, mass, stiffness
        v0, x0 = -velocity, 1.0 - current
        zeta = c / (2 * math.sqrt(k * m))
        w0 = math.sqrt(k / m)
        w1 = w0 * math.sqrt(1 - zeta ** 2) if zeta < 1 else 0.0
        t = dt / 1000
        if zeta < 1:
            env = math.exp(-zeta * w0 * t)
            frag = env * (math.sin(w1 * t) * ((v0 + zeta * w0 * x0) / w1) + x0 * math.cos(w1 * t))
            pos = 1.0 - frag
            vel = zeta * w0 * frag - env * (math.cos(w1 * t) * (v0 + zeta * w0 * x0) - w1 * x0 * math.sin(w1 * t))
        else:
            env = math.exp(-w0 * t)
            pos = 1.0 - env * (x0 + (v0 + w0 * x0) * t)
            vel = env * (v0 * (t * w0 - 1) + t * x0 * w0 * w0)
        current, velocity, last = pos, vel, now

    for f in range(int(math.floor(frame)) + 1):
        advance(f / fps * 1000)
    if frame % 1 > 0:
        advance(frame / fps * 1000)
    return current


_NATURAL: dict[tuple, int] = {}


def _spring_natural(fps: float, threshold: float = 0.005) -> int:
    """remotion measureSpring for SPRING."""
    key = (fps, threshold)
    if key in _NATURAL:
        return _NATURAL[key]
    pos = lambda fr: _spring_state(fr, fps, **SPRING)  # noqa: E731
    frame = 0
    while abs(pos(frame) - 1) >= threshold:
        frame += 1
    finished = frame
    i = 0
    while i < 20:
        frame += 1
        if abs(pos(frame) - 1) >= threshold:
            i = 0
            finished = frame + 1
        i += 1
    _NATURAL[key] = finished
    return finished


def spring_at(t: float, length: float, fps: float) -> float:
    """remotion spring({frame: t, fps, config: SPRING, durationInFrames: length})."""
    scaled = t / (length / _spring_natural(fps))
    if t > length:
        return 1.0
    return _spring_state(scaled, fps, **SPRING)


def _cubic(t: float) -> float:
    return t * t * t


CURVES = {
    "linear": lambda t: t,
    "in": _cubic,
    "out": lambda t: 1 - _cubic(1 - t),
    "inOut": lambda t: _cubic(t * 2) / 2 if t < 0.5 else 1 - _cubic((1 - t) * 2) / 2,
}


def ease_at(ease: str | None, t: float, length: float, fps: float) -> float:
    """Progress 0..1 (spring may overshoot) of a segment `length` frames long, `t` frames in (easeAt)."""
    if length <= 0:
        return 1.0
    if ease == "step":
        return 1.0 if t >= length else 0.0
    if ease == "spring":
        return 0.0 if t <= 0 else 1.0 if t >= length else spring_at(t, length, fps)
    curve = CURVES.get(ease or "linear", CURVES["linear"])
    return curve(min(1.0, max(0.0, t / length)))


def value_at(frames: list[dict], f: float, fps: float) -> float | None:
    """The keyframed value at frame f ({"f", "v", "ease"} items, frames from the clip start); holds outside the
    range; the move into keyframe k is shaped by k's ease (valueAt)."""
    k = sorted((x for x in frames if math.isfinite(x["f"]) and math.isfinite(x["v"])), key=lambda x: x["f"])
    if not k:
        return None
    if f <= k[0]["f"]:
        return k[0]["v"]
    if f >= k[-1]["f"]:
        return k[-1]["v"]
    i = 1
    while i < len(k) and k[i]["f"] <= f:
        i += 1
    a, b = k[i - 1], k[i]
    return a["v"] + (b["v"] - a["v"]) * ease_at(b.get("ease"), f - a["f"], b["f"] - a["f"], fps)


def motion_keyframes(motion: str | None, seconds: float, w: float, h: float) -> dict[str, list[dict]]:
    """Ken Burns sugar as project keyframes ({"t" seconds from the clip start, "v", "ease"}); pan in box pixels."""
    end = round(max(seconds, 0.001), 3)

    def move(a: float, b: float) -> list[dict]:
        return [{"t": 0, "v": a}, {"t": end, "v": b, "ease": "linear"}]

    def hold(v: float) -> list[dict]:
        return [{"t": 0, "v": v}]
    if motion == "push":
        return {"zoom": move(1.02, 1.12)}
    if motion == "pull":
        return {"zoom": move(1.12, 1.02)}
    if motion == "pan_left":
        return {"zoom": hold(1.14), "pan_x": move(round(0.034 * w, 1), round(-0.034 * w, 1))}
    if motion == "pan_right":
        return {"zoom": hold(1.14), "pan_x": move(round(-0.034 * w, 1), round(0.034 * w, 1))}
    if motion == "rise":
        return {"zoom": hold(1.1), "pan_y": move(round(0.022 * h, 1), round(-0.022 * h, 1))}
    return {}


# ------------------------------------------------------------------ media facts
_SIZES: dict[tuple, tuple[int, int] | None] = {}
_DURATIONS: dict[tuple, float | None] = {}


def _stamp(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return str(path), st.st_mtime_ns, st.st_size


def image_size(path: Path) -> tuple[int, int] | None:
    """(w, h) from a PNG, JPEG, WebP or GIF header; None when unreadable."""
    key = _stamp(path)
    if key is None:
        return None
    if key not in _SIZES:
        _SIZES[key] = _header_size(path)
    return _SIZES[key]


def _header_size(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _webp(head)
            if head[:2] == b"\xff\xd8":
                return _jpeg(f)
    except (OSError, struct.error):
        return None
    return None


def _webp(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        b = head[21:25]
        return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
    if chunk == b"VP8X":
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    return None


def _jpeg(f) -> tuple[int, int] | None:
    f.seek(2)
    while True:
        marker = f.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
            continue
        size = struct.unpack(">H", f.read(2))[0]
        if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            f.read(1)
            h, w = struct.unpack(">HH", f.read(4))
            return w, h
        f.seek(size - 2, 1)


def media_duration(path: Path) -> float | None:
    """Seconds of a video or audio file (ffprobe); None when it cannot be measured."""
    key = _stamp(path)
    if key is None:
        return None
    if key not in _DURATIONS:
        try:
            from . import media
            _DURATIONS[key] = media.duration(path)
        except Exception:  # noqa: BLE001 - no ffprobe, odd file: the renderer copes without it
            _DURATIONS[key] = None
    return _DURATIONS[key]


# ------------------------------------------------------------------ captions
def _segments(text: str) -> list[tuple[int, int]]:
    """Spans of `text` between break punctuation, whitespace trimmed."""
    out, pos = [], 0
    for m in list(_BREAK.finditer(text)) + [None]:
        a, b = pos, (m.start() if m else len(text))
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
        if m:
            pos = m.end()
    return out


# words: segment.mjs (Intl.Segmenter in the project's locale) once per resolve, cached; characters without node
_WORDS: dict[tuple[str, str], list[int]] = {}   # (locale, plain text) -> word lengths in code points
_NODE = {"hung": False}                         # a node call timed out once: do not wait on it again
SEGMENT_CACHE = "segments.json"                 # in the project's build/: {"version", "words": {sha1: lengths}}
SEGMENT_VERSION = 2                             # 2: keyed by locale and text
SEGMENT_CACHE_MAX = 4000
_CHAR_WORD = re.compile(r"[A-Za-z0-9]+(?:[.,'’-][A-Za-z0-9]+)*|\s+|.", re.S)


def char_words(text: str) -> list[int]:
    """The fallback words: Latin/digit runs, whitespace runs, and every other character on its own."""
    return [len(m.group()) for m in _CHAR_WORD.finditer(text)]


def _fits(text: str, lengths) -> bool:
    return (isinstance(lengths, list) and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in lengths)
            and sum(lengths) == len(text))


def _node_words(texts: list[str], locale: str = locales.DEFAULT_LOCALE) -> list[list[int]] | None:
    """Word lengths per text from renderer/scripts/segment.mjs in one node call; None when node cannot be used."""
    node = shutil.which("node")
    script = library.renderer_dir() / "scripts" / "segment.mjs"
    if _NODE["hung"] or not node or not script.is_file():
        return None
    from .media import NO_WINDOW
    payload = json.dumps({"texts": texts, "locale": locale}, ensure_ascii=False).encode()
    try:
        proc = subprocess.run([node, str(script)], input=payload, capture_output=True, timeout=30,
                              creationflags=NO_WINDOW)
        words = json.loads(proc.stdout.decode("utf-8"))["words"]
    except subprocess.TimeoutExpired:
        _NODE["hung"] = True
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if proc.returncode != 0 or not isinstance(words, list) or len(words) != len(texts):
        return None
    return words if all(_fits(t, w) for t, w in zip(texts, words)) else None


def _key(text: str, locale: str = locales.DEFAULT_LOCALE) -> str:
    return hashlib.sha1(f"{locale}\n{text}".encode("utf-8")).hexdigest()


def _read_segment_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ok = isinstance(data, dict) and data.get("version") == SEGMENT_VERSION
    words = data.get("words") if ok else None
    return words if isinstance(words, dict) else {}


def word_breaks(texts, cache_dir: Path | None = None,
                locale: str = locales.DEFAULT_LOCALE) -> dict[str, list[int] | None]:
    """{text: word lengths} for caption texts in `locale`: from memory, then <cache_dir>/segments.json, then one node
    call for the rest; None for texts node could not segment (the phrase splitter then works on characters)."""
    want = [t for t in dict.fromkeys(texts) if t]
    out: dict[str, list[int] | None] = {t: _WORDS[(locale, t)] for t in want if (locale, t) in _WORDS}
    missing = [t for t in want if t not in out]
    path = Path(cache_dir) / SEGMENT_CACHE if cache_dir is not None else None
    disk = _read_segment_cache(path) if missing and path else {}
    for t in missing:
        if _fits(t, disk.get(_key(t, locale))):
            out[t] = _WORDS[(locale, t)] = disk[_key(t, locale)]
    missing = [t for t in missing if t not in out]
    if not missing:
        return out
    words = _node_words(missing, locale)
    for n, t in enumerate(missing):
        out[t] = words[n] if words is not None else None
        if words is not None:
            _WORDS[(locale, t)] = words[n]
    if words is not None and path is not None:
        disk.update({_key(t, locale): w for t, w in zip(missing, words)})
        if len(disk) > SEGMENT_CACHE_MAX:
            disk = {_key(t, locale): out[t] for t in want if out.get(t) is not None}
        try:
            D.write_json(path, {"version": SEGMENT_VERSION, "words": disk})
        except OSError:
            pass                                # read-only project: the memo still holds them
    return out


def _numbers(text: str) -> list[tuple[int, int]]:
    """Spans of numbers with their unit: 0.725, 34230元, 3.1%, 九千三百七十一块钱, 六成, 8999 元."""
    out = []
    for m in _NUMBER.finditer(text):
        a, b = m.span()
        u = _UNIT.match(text, b)
        unit = u.group() if u and u.group().strip() else ""
        if b - a == 1 and text[a] in _NUMERAL and not unit:
            continue                            # a lone numeral (one, two) is a number only before a unit
        out.append((a, b + len(unit)))
    return out


def _cut_rules(text: str) -> tuple[list[bool], list[bool]]:
    """(locked, number): locked[i] when a cut before text[i] would split a number from itself or its unit, start a
    line with a closing mark or end one with an opening mark; number[i] when text[i] belongs to a number."""
    locked, number = [False] * (len(text) + 1), [False] * (len(text) + 1)
    for a, b in _numbers(text):
        for i in range(a, b):
            number[i] = True
            locked[i] = locked[i] or i > a
    for i in range(1, len(text)):
        if text[i] in _CLOSERS or text[i - 1] in _OPENERS:
            locked[i] = True
    return locked, number


def _kind(text: str, tok: tuple[int, int], number: list[bool]) -> str:
    a, b = tok
    if any(number[a:b]):
        return "num"
    if _LATIN.match(text[a]):
        return "latin"
    return "cjk" if text[a].isalpha() else "sym"


def _cost(text: str, left: list, right: list, number: list[bool]) -> int:
    """How bad a cut between the words `left` and `right` is: 0 a clean break ... 3 never if avoidable."""
    L, R = left[-1], right[0]
    ls, rs = text[L[0]:L[1]], text[R[0]:R[1]]
    kl, kr = _kind(text, L, number), _kind(text, R, number)
    if kr == "cjk" and rs in _ENDERS:
        return 3                                # particles (_ENDERS) end a phrase, they never start one
    if kl == "cjk" and ls in _STARTERS:
        return 2                                # a lone preposition or adverb (_STARTERS) leads into what follows it
    if kl != kr and "cjk" in (kl, kr):
        return 0                                # Chinese next to a number or Latin
    if kl == "latin" and ls.lower() in _LATIN_LEADS:
        return 2
    if kl != "cjk" or kr != "cjk":
        return 1                                # between Latin words or numbers: keeps "iPhone 17 Pro" together
    if ls in _ENDERS or rs in _STARTERS or rs.startswith(_START_WORDS):
        return 0
    if len(ls) == 1 or len(rs) == 1:
        return 1 + (len(ls) == 1 and len(rs) == 1)

    def lone(tok) -> bool:                      # a single-character word next to the cut: the segmenter may be wrong
        s = text[tok[0]:tok[1]]
        return len(s) == 1 and _kind(text, tok, number) == "cjk" and s not in _FUNCTION
    return int((len(left) > 1 and lone(left[-2])) or (len(right) > 1 and lone(right[1])))


def _best_cut(text: str, toks: list, a: int, b: int, want: int, lo: int, hi: int, locked: list[bool],
              number: list[bool]) -> int | None:
    """The cut between words inside (a, b) closest to `want`, preferring clean breaks and cuts in [lo, hi]."""
    words = [t for t in toks if not text[t[0]:t[1]].isspace()]
    found = []
    for j in range(1, len(words)):
        c = words[j][0]
        if a < c < b and not locked[c]:
            found.append((c, _cost(text, words[:j], words[j:], number)))
    if not found:
        return None
    inside = [f for f in found if lo <= f[0] <= hi] or found
    return min(inside, key=lambda f: (f[1] * 4 + abs(f[0] - want), abs(f[0] - want), f[0]))[0]


def phrase_spans(text: str, max_chars: int = 14, words: list[int] | None = None) -> list[list[tuple[int, int]]]:
    """Caption phrases as spans of `text`: cut at punctuation, long parts halved (or cut at max_chars) between words,
    never inside a word, a number or a number and its unit; short ones merged forward; a closing quote or bracket
    stays with the text before it. Each phrase is one or more spans (merged parts). `words`: word lengths
    (segment.mjs); None looks them up (word_breaks)."""
    if words is None or not _fits(text, words):
        words = word_breaks([text]).get(text) or char_words(text)
    toks, pos = [], 0
    for n in words:
        toks.append((pos, pos + n))
        pos += n
    locked, number = _cut_rules(text)
    parts: list[tuple[int, int]] = []
    for a, b in _segments(text):
        seg = [(max(x, a), min(y, b)) for x, y in toks if x < b and y > a]
        while b - a > max_chars:
            if b - a <= 2 * max_chars:
                want, lo, hi = a + (b - a) // 2, b - max_chars, a + max_chars
            else:
                want, lo, hi = a + max_chars, a + max_chars // 2, a + max_chars
            c = _best_cut(text, seg, a, b, want, lo, hi, locked, number)
            if c is None:
                break                           # one long word: it stays whole
            end = c
            while end > a and text[end - 1].isspace():
                end -= 1
            parts.append((a, end))
            a = c
            while a < b and text[a].isspace():
                a += 1
        if b > a:
            parts.append((a, b))
    merged: list[list[tuple[int, int]]] = []
    for a, b in parts:
        k = a
        while k < b and text[k] in _CLOSERS:
            k += 1
        if k > a and merged:                    # a closing quote or bracket after a cut stays with the phrase before
            merged[-1].append((a, k))
            a = k
            while a < b and text[a].isspace():
                a += 1
        if a >= b:
            continue
        n = b - a
        prev = sum(y - x for x, y in merged[-1]) if merged else 0
        least = max(PHRASE_MIN, max_chars // 4)       # a lone short word ("Well,") joins its neighbour
        if merged and (prev < least or n < least) and prev + n <= max_chars:
            merged[-1].append((a, b))
        else:
            merged.append([(a, b)])
    return merged


def _join(text: str, spans: list[tuple[int, int]]) -> list[int | None]:
    """Character indices of a phrase; None marks a space between Latin/digit parts."""
    out: list[int | None] = []
    for a, b in spans:
        if out and out[-1] is not None and re.match(r"[A-Za-z0-9]", text[out[-1]]) and re.match(r"[A-Za-z0-9]",
                                                                                                text[a]):
            out.append(None)
        out.extend(range(a, b))
    return out


def phrases(text: str, max_chars: int = 14, words: list[int] | None = None) -> list[str]:
    """A spoken line cut into caption phrases."""
    return ["".join(" " if i is None else text[i] for i in _join(text, s))
            for s in phrase_spans(text, max_chars, words)]


def _plain(text: str) -> tuple[str, list[bool]]:
    """Markup-free text and a per-character accent flag."""
    chars, flags = [], []
    for part, accent in D.markup_runs(text):
        chars.append(part)
        flags += [accent] * len(part)
    return "".join(chars), flags


def _emphasis(text: str, words: list[str]) -> list[bool]:
    flags = [False] * len(text)
    taken: list[tuple[int, int]] = []
    for w in sorted({w for w in words if w}, key=len, reverse=True):
        for m in re.finditer(re.escape(w), text):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                taken.append((m.start(), m.end()))
                flags[m.start():m.end()] = [True] * (m.end() - m.start())
    return flags


def _runs(chars: list[tuple[str, bool]]) -> list[dict]:
    runs: list[dict] = []
    for ch, accent in chars:
        if runs and runs[-1]["accent"] == accent:
            runs[-1]["text"] += ch
        else:
            runs.append({"text": ch, "accent": accent})
    return runs


def text_runs(text: str, emphasis: list[str] | None = None) -> list[dict]:
    """Runs [{text, accent}] from **markup** and emphasis words."""
    plain, flags = _plain(text)
    emph = _emphasis(plain, emphasis or [])
    return _runs([(c, f or e) for c, f, e in zip(plain, flags, emph)])


def line_phrases(text: str, max_chars: int, emphasis: list[str],
                 words: list[int] | None = None) -> list[tuple[list[dict], int]]:
    """[(runs, length)] for one voice line: phrases with their accents and character counts."""
    plain, flags = _plain(text)
    emph = _emphasis(plain, emphasis)
    out = []
    for spans in phrase_spans(plain, max_chars, words):
        idx = _join(plain, spans)
        chars = [(" ", False) if i is None else (plain[i], flags[i] or emph[i]) for i in idx]
        out.append((_runs(chars), sum(1 for i in idx if i is not None)))
    return out


def caption_track(track: D.CaptionsTrack, locale: str) -> D.CaptionsTrack:
    """The track with max_chars filled: unset, it is the locale's default (14 for CJK, 32 otherwise)."""
    return track if track.max_chars else track.model_copy(update={"max_chars": locales.caption_chars(locale)})


def caption_texts(voice: D.Voice | None, track: D.CaptionsTrack) -> list[str]:
    """The markup-free text of each voice line as the track captions it (overrides applied)."""
    if voice is None or track.items is not None:
        return []
    overrides = {o.line: o.text for o in track.overrides}
    return [_plain(overrides.get(ln.i, ln.text))[0] for ln in voice.lines]


def _voice_items(voice: D.Voice, track: D.CaptionsTrack, fps: float, words: dict | None) -> list[dict]:
    overrides = {o.line: o.text for o in track.overrides}
    if words is None:
        words = word_breaks(caption_texts(voice, track))
    out: list[dict] = []
    for ln in voice.lines:
        text = overrides.get(ln.i, ln.text)
        plain = _plain(text)[0]
        chars = track.max_chars or locales.CJK_CAPTION_CHARS
        parts = line_phrases(text, chars, track.emphasis, words.get(plain) or char_words(plain))
        total = sum(n for _, n in parts) or 1
        acc = 0
        for runs, n in parts:
            a = ln.t0 + (ln.t1 - ln.t0) * acc / total
            acc += n
            b = ln.t0 + (ln.t1 - ln.t0) * acc / total
            out.append({"from": T.to_frame(a, fps), "to": T.to_frame(b, fps), "runs": runs, "line": ln.i})
    for i in range(len(out) - 1):
        out[i]["to"] = max(out[i]["to"], out[i + 1]["from"])
    return [it for it in out if it["to"] > it["from"]]


def voice_captions(voice: D.Voice, track: D.CaptionsTrack, fps: float, words: dict | None = None) -> list[dict]:
    """Caption items from the voice lines: phrase-split between words, timed by characters within each line, each
    held until the next one starts (no flicker). `words`: word_breaks() of caption_texts(); None looks them up."""
    return [{k: v for k, v in it.items() if k != "line"} for it in _voice_items(voice, track, fps, words)]


def caption_items(track: D.CaptionsTrack, voice: D.Voice | None, sched: T.Schedule, fps: float,
                  words: dict | None = None) -> list[dict]:
    """The track's items in frames: given items as written, else from the voice."""
    if track.items is None:
        return voice_captions(voice, track, fps, words) if voice else []
    items = []
    for it in track.items:
        try:
            a = T.to_frame(T.resolve(it.start, sched), fps)
            b = T.to_frame(T.resolve(it.end, sched), fps)
        except T.TimeError:
            continue
        if b > a:
            items.append({"from": a, "to": b, "runs": text_runs(it.text, track.emphasis)})
    return items


# ------------------------------------------------------------------ captions from a transcript
PAUSE_S = 0.5                   # a pause this long between words ends a phrase
HOLD_S = 1.0                    # a phrase stays up until the next one across a gap shorter than this
TAIL_S = 0.3                    # ... else this long after its last word
_SENTENCE_END = tuple(".?!…。？！")
_CLAUSE_END = tuple(",;:，；：、")
_NO_SPACE_BEFORE = set(",.!?;:%)]}'’”…。，！？；：、）】」』")
_NO_SPACE_AFTER = set("([{‘“（【「『")


def _unspaced(ch: str) -> bool:
    """Scripts written without spaces between words: CJK, kana, Thai, Lao, Khmer, Myanmar, fullwidth forms."""
    o = ord(ch)
    return (0x3000 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0xFF00 <= o <= 0xFFEF or 0x0E00 <= o <= 0x0EFF or 0x1780 <= o <= 0x17FF or 0x1000 <= o <= 0x109F)


def join_words(words: list[str]) -> str:
    """Transcript words as text: spaced between words of spaced scripts, not around CJK or punctuation."""
    out = ""
    for w in words:
        if out and not (w[0] in _NO_SPACE_BEFORE or out[-1] in _NO_SPACE_AFTER or _unspaced(out[-1])
                        or _unspaced(w[0])):
            out += " "
        out += w
    return out


def transcript_phrases(words: list[dict], max_chars: int) -> list[list[dict]]:
    """Words ({"word", "a", "b"} film seconds) grouped into caption phrases by their timing: a pause, the end of a
    sentence, a clause end past half the length, or max_chars ends one; a short phrase joins the one before it."""
    phrases: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            prev = cur[-1]
            long = len(join_words([x["word"] for x in cur + [w]])) > max_chars
            said = len(join_words([x["word"] for x in cur]))
            if (w["a"] - prev["b"] >= PAUSE_S or long or prev["word"].endswith(_SENTENCE_END)
                    or (prev["word"].endswith(_CLAUSE_END) and said >= max_chars // 2)):
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    merged: list[list[dict]] = []
    for ph in phrases:
        text = join_words([x["word"] for x in ph])
        if merged:
            last = merged[-1]
            both = join_words([x["word"] for x in last + ph])
            if (len(text) < PHRASE_MIN and len(both) <= max_chars and ph[0]["a"] - last[-1]["b"] < PAUSE_S
                    and not last[-1]["word"].endswith(_SENTENCE_END)):
                last.extend(ph)
                continue
        merged.append(ph)
    return merged


def transcript_clips(doc: D.Document, track: D.CaptionsTrack) -> tuple[list, D.Asset | None]:
    """The clips a "clip:<id>" captions track follows: that clip and every other clip on its track playing the same
    asset with sound (the pieces an edit cut it into; a muted reuse is not heard), with the asset."""
    cid = track.source[5:] if track.source.startswith("clip:") else ""
    for t in doc.tracks:
        for c in getattr(t, "clips", None) or []:
            if c.id == cid and c.type in D.SOUNDING:
                same = [x for x in t.clips if x.type == c.type and x.asset == c.asset and not getattr(x, "loop", False)
                        and (x is c or sounds(x))]
                return same, doc.assets.get(c.asset)
    return [], None


def transcript_items(root, doc: D.Document, track: D.CaptionsTrack, sched: T.Schedule, fps: float) -> list[dict]:
    """Caption items from the transcript of the track's source clip: each word placed through the clip that plays it
    (start, trim_in, rate; words its trim cuts away are dropped), phrase-split by timing."""
    clips, asset = transcript_clips(doc, track)
    transcript = D.load_transcript(root, asset) if asset is not None else None
    if not clips or transcript is None:
        return []
    words = []
    for c in clips:
        try:
            a, b = sched.span(c.id)
        except T.TimeError:
            continue
        rate = float(getattr(c, "rate", 1.0) or 1.0)
        trim = float(c.trim_in or 0.0)
        out = trim + (b - a) * rate
        for w in transcript["words"]:
            mid = (w["start"] + w["end"]) / 2
            if trim <= mid <= out:
                words.append({"word": w["word"], "a": a + (max(w["start"], trim) - trim) / rate,
                              "b": a + (min(w["end"], out) - trim) / rate, "clip_end": b})
    words.sort(key=lambda w: w["a"])
    items = []
    phrases = transcript_phrases(words, track.max_chars)
    for n, ph in enumerate(phrases):
        start, end, stop = ph[0]["a"], ph[-1]["b"], ph[-1]["clip_end"]
        nxt = phrases[n + 1][0]["a"] if n + 1 < len(phrases) else None
        if nxt is not None and nxt - end < HOLD_S:
            end = nxt
        else:
            end = min(end + TAIL_S, nxt if nxt is not None else end + TAIL_S)
        end = min(end, stop)
        fa, fb = T.to_frame(start, fps), T.to_frame(end, fps)
        if fb > fa:
            items.append({"from": fa, "to": fb, "runs": text_runs(join_words([w["word"] for w in ph]),
                                                                  track.emphasis)})
    return items


# ------------------------------------------------------------------ sound: volume curves, crossfades, ducking
def sounds(clip) -> bool:
    """A clip that makes sound: an audio clip, or a video clip with volume or volume keyframes above 0."""
    if clip.type == "audio":
        return True
    if clip.type != "video":
        return False
    keys = clip.keyframes.get("volume") or []
    return clip.volume > 0 or any(k.v > 0 for k in keys)


def _merge(ranges: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def duck_ranges(doc: D.Document, voice: D.Voice | None, sched: T.Schedule, under: str,
                fade: float) -> list[tuple[float, float]]:
    """Film seconds where the duck's target makes sound: the narration's lines, or the extents of a track's sounding
    clips (an approximation: a clip counts as sound from its start to its end). Gaps up to 2 x fade are bridged so a
    bed does not pump between phrases."""
    ranges = []
    if under == "voice":
        ranges = [(ln.t0, ln.t1) for ln in voice.lines] if voice else []
    else:
        target = next((t for t in doc.tracks if t.id == under), None)
        if target is None or target.hidden:
            return []
        for c in getattr(target, "clips", None) or []:
            if sounds(c):
                try:
                    ranges.append(sched.span(c.id))
                except T.TimeError:
                    continue
    return _merge([r for r in ranges if r[1] > r[0]], 2 * fade)


# ------------------------------------------------------------------ resolving
class _Resolver:
    def __init__(self, project):
        self.root = project_root(project)
        self.doc = D.load(self.root)
        try:
            self.profile = D.profile_of(self.root, self.doc)
            self.locale = D.locale_of(self.root, self.doc)
        except ValueError as exc:
            raise ResolveError(str(exc)) from None
        self.fps = self.profile.fps
        self.voice, _ = D.load_voice(self.root, self.doc.voice)
        self.sched = D.schedule(self.doc, self.voice)
        try:
            self.end = self.sched.film_end()
        except T.TimeError as exc:
            raise ResolveError(f"the film's length: {exc}") from None
        self.frames = max(1, T.to_frame(self.end, self.fps))

    def frame(self, seconds: float) -> int:
        return T.to_frame(seconds, self.fps)

    def box(self, value) -> dict:
        p = self.profile
        if value is None or value == "full":
            return {"x": 0, "y": 0, "w": p.width, "h": p.height}
        if value == "safe":
            s = p.safe
            return {"x": s.x, "y": s.y, "w": s.w, "h": s.h}
        return D._ints({"x": value.x, "y": value.y, "w": value.w, "h": value.h})

    def asset_ref(self, aid: str) -> dict | None:
        a = self.doc.assets.get(aid)
        if a is None:
            return None
        path = self.root / a.path
        ref = {"src": Path(a.path).as_posix(), "kind": a.kind}
        if a.kind in ("image", "evidence"):
            size = image_size(path)
            ref["size"] = list(size) if size else None
        if a.kind == "evidence":
            ref["box"] = list(a.box) if a.box else None
            ref["site"] = a.site
        if a.kind in ("video", "audio"):
            ref["duration"] = media_duration(path)
        return ref

    def run(self) -> dict:
        p = self.profile
        tracks, audio = [], []
        texts = [t for track in self.doc.tracks if track.kind == "captions" for t in caption_texts(self.voice, track)]
        self.words = word_breaks(texts, project_paths(self.root).build, self.locale) if texts else {}
        if self.voice and self.voice.audio_rel:
            audio.append({"id": "voice", "src": self.voice.audio_rel, "from": 0,
                          "dur": max(1, self.frame(self.voice.duration or self.voice.end)), "trimIn": 0, "volume": 1,
                          "fadeIn": 0, "fadeOut": 0, "loop": False})
        for track in self.doc.tracks:
            if track.kind == "visual":
                clips = [rc for c in track.clips if (rc := self.clip(track, c)) is not None]
                self.cuts(track, clips)
                tracks.append({"id": track.id, "kind": "visual", "hidden": track.hidden, "clips": clips})
            elif track.kind == "captions":
                tracks.append(self.captions(track))
            else:
                tracks.append({"id": track.id, "kind": "audio", "hidden": track.hidden})
                if not track.hidden:
                    items = [a for c in track.clips if (a := self.audio_clip(c)) is not None]
                    self.cuts(track, items)
                    audio += items
        return {"version": 2, "fps": self.fps, "width": p.width, "height": p.height,
                "durationInFrames": self.frames, "safe": {"x": p.safe.x, "y": p.safe.y, "w": p.safe.w, "h": p.safe.h},
                "theme": D.theme_of(self.root, self.doc), "fonts": project_fonts(self.root), "tracks": tracks,
                "audio": audio, "inspect": False}

    def span(self, c) -> tuple[int, int] | None:
        try:
            a, b = self.sched.span(c.id)
        except T.TimeError:
            return None
        fa, fb = self.frame(a), self.frame(b)
        return (fa, fb - fa) if fb > fa else None

    def clip(self, track, c) -> dict | None:
        span = self.span(c)
        if span is None:
            return None
        start, dur = span
        content = self.content(c, start)
        if content is None:
            return None
        box = self.box(c.box)
        style = {"opacity": c.opacity, "rotate": c.rotate, "scale": c.scale, "origin": c.origin, "radius": c.radius,
                 "blend": c.blend, "filter": c.filter.model_dump(exclude_none=True) if c.filter else None,
                 "shadow": c.shadow}
        return {"id": c.id, "type": c.type, "track": track.id, "from": start, "dur": dur, "box": box,
                "style": D._ints(style), "keyframes": self.keyframes(c, start, dur, box),
                "enter": self.transition(c.enter), "exit": self.transition(c.exit), "content": D._ints(content),
                "transition": None, "transitionOut": None}

    def transition(self, t) -> dict | None:
        return {"preset": t.preset, "dur": max(1, self.frame(t.dur))} if t else None

    def rel_frame(self, value, start: int) -> int | None:
        """A Time inside a clip starting at frame `start` as frames from that start (numbers count from it)."""
        try:
            return T.clip_frame(value, start, self.fps, self.sched)
        except T.TimeError:
            return None

    def keyframes(self, c, start: int, dur: int, box: dict) -> dict:
        out: dict[str, list[dict]] = {}
        motion = getattr(c, "motion", None)
        if motion:
            for prop, frames in motion_keyframes(motion, dur / self.fps, box["w"], box["h"]).items():
                out[prop] = [{"f": 0 if k["t"] == 0 else max(1, dur - 1), "v": k["v"], "ease": k.get("ease") or "linear"}
                             for k in frames]
        for prop, frames in c.keyframes.items():
            if prop == "volume":                # a sound curve, not a picture property: content.volumeKeys
                continue
            rows = self.frame_keys(frames, start)
            if rows:
                out[prop] = rows
        return D._ints(out)

    def frame_keys(self, frames, start: int) -> list[dict]:
        rows = []
        for k in frames:
            f = self.rel_frame(k.t, start)
            if f is not None:
                rows.append({"f": f, "v": k.v, "ease": k.ease or "linear"})
        return sorted(rows, key=lambda r: r["f"])

    def content(self, c, start: int) -> dict | None:
        if c.type in ("image", "video", "evidence"):
            ref = self.asset_ref(c.asset)
            if ref is None:
                return None
        if c.type == "image":
            return {"src": ref["src"], "size": ref.get("size"), "fit": c.fit, "focus": c.focus}
        if c.type == "video":
            out = {"src": ref["src"], "duration": ref.get("duration"), "trimIn": self.frame(c.trim_in),
                   "rate": c.rate, "loop": c.loop, "fit": c.fit, "focus": c.focus, "volume": c.volume}
            if c.keyframes.get("volume"):
                out["volumeKeys"] = D._ints(self.frame_keys(c.keyframes["volume"], start))
            return out
        if c.type == "text":
            reveal = {"mode": c.reveal.mode, "dur": c.reveal.dur} if c.reveal else None
            return {"runs": text_runs(c.text), "style": text_style(c.style, self.profile.scale), "reveal": reveal}
        if c.type == "shape":
            return {"shape": c.shape, "fill": c.fill, "stroke": c.stroke, "stroke_width": c.stroke_width, "d": c.d,
                    "draw": c.draw}
        if c.type == "evidence":
            hl = None
            if c.highlight:
                at = self.rel_frame(c.highlight.at, start) if c.highlight.at is not None else None
                hl = {"at": at, "dur": max(1, self.frame(c.highlight.dur)), "color": c.highlight.color}
            return {"src": ref["src"], "size": ref.get("size"), "box": ref.get("box"), "site": ref.get("site", ""),
                    "highlight": hl}
        return {"name": c.name, "props": self.props(c.props, start)}

    def props(self, value, start: int, key: str = ""):
        if isinstance(value, dict):
            return {k: self.props(v, start, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.props(v, start) for v in value]
        if value is not None and key and D.TIME_KEY.match(key):
            f = self.rel_frame(value, start)
            return f if f is not None else value
        if isinstance(value, str) and key and D.ASSET_KEY.match(key):
            ref = self.asset_ref(value)
            return ref if ref is not None else value
        return copy.deepcopy(value)

    def captions(self, track: D.CaptionsTrack) -> dict:
        c = self.profile.captions
        box = self.box(track.box) if track.box is not None else {"x": c.x, "y": c.y, "w": c.w, "h": c.h}
        track = caption_track(track, self.locale)
        if track.items is None and track.source != "voice":
            items = transcript_items(self.root, self.doc, track, self.sched, self.fps)
        else:
            items = caption_items(track, self.voice, self.sched, self.fps, self.words)
        return {"id": track.id, "kind": "captions", "hidden": track.hidden, "box": box,
                "style": caption_style(track.style), "items": items}

    def audio_clip(self, c: D.AudioClip) -> dict | None:
        span = self.span(c)
        ref = self.asset_ref(c.asset)
        if span is None or ref is None:
            return None
        out = {"id": c.id, "src": ref["src"], "from": span[0], "dur": span[1], "trimIn": self.frame(c.trim_in),
               "volume": D._ints(c.volume), "fadeIn": self.frame(c.fade_in), "fadeOut": self.frame(c.fade_out),
               "loop": c.loop}
        if c.keyframes.get("volume"):
            out["volumeKeys"] = D._ints(self.frame_keys(c.keyframes["volume"], span[0]))
        if c.duck is not None:
            out["duck"] = self.duck(c.duck, span)
        return out

    def duck(self, duck: D.Duck, span: tuple[int, int]) -> list[dict]:
        """The duck's ranges in frames from the item's start, kept where they reach it (fades included)."""
        fade = self.frame(duck.fade)
        out = []
        for a, b in duck_ranges(self.doc, self.voice, self.sched, duck.under, duck.fade):
            fa, fb = self.frame(a) - span[0], self.frame(b) - span[0]
            if fb + fade > 0 and fa - fade < span[1]:
                out.append({"start": fa, "end": fb, "level": D._ints(duck.to), "fade": fade})
        return out

    def cuts(self, track, items: list[dict]) -> None:
        """Transitions between neighbours on one track: the incoming clip (visual) gets `transition`, the clip it
        comes from `transitionOut` where they overlap; sound crossfades (audio items, and video clips with sound)
        through fadeIn / fadeOut over the same frames."""
        models = {c.id: c for c in track.clips}
        rows = sorted(items, key=lambda r: (r["from"], r["dur"]))
        for prev, cur in zip([None] + rows[:-1], rows):
            tr = models[cur["id"]].transition
            if tr is None:
                continue
            dur = max(1, self.frame(tr.dur))
            over = prev["from"] + prev["dur"] - cur["from"] if prev is not None else 0
            if track.kind == "visual":
                cur["transition"] = {"type": tr.type, "dur": dur, "from": prev["id"] if prev is not None else None}
                if over > 0:
                    prev["transitionOut"] = {"type": tr.type, "dur": dur, "at": cur["from"] - prev["from"],
                                             "to": cur["id"]}
                sound_in = cur["content"] if sounds(models[cur["id"]]) else None
                sound_out = prev["content"] if prev is not None and over > 0 and sounds(models[prev["id"]]) else None
            else:
                sound_in, sound_out = cur, (prev if over > 0 else None)
            if sound_in is not None:
                sound_in["fadeIn"] = max(int(sound_in.get("fadeIn") or 0), dur)
            if sound_out is not None:
                sound_out["fadeOut"] = max(int(sound_out.get("fadeOut") or 0), min(over, prev["dur"]))


def _style_value(v):
    return v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v


def text_style(style: D.TextStyle | None, scale: float = 1.0) -> dict:
    """TextStyle with the renderer's defaults filled (Text.tsx TEXT_DEFAULTS); default sizes follow the canvas
    (`scale`: its short side / 1080)."""
    out = dict(TEXT_DEFAULTS)
    if scale != 1:
        out.update({k: round(out[k] * scale) for k in ("size", "max_size", "min_size")})
    if style is not None:
        for k in style.model_fields_set:
            v = getattr(style, k)
            if v is None:
                if k in NULLABLE:
                    out[k] = None
                continue
            out[k] = _style_value(v)
    return D._ints(out)


def caption_style(style: D.TextStyle | None) -> dict | None:
    """Only what the track sets: the renderer lays it over its caption defaults."""
    if style is None:
        return None
    out = {}
    for k in style.model_fields_set:
        v = getattr(style, k)
        if v is None and k not in NULLABLE:
            continue
        out[k] = _style_value(v)
    return D._ints(out)


FONTS_DIR = "fonts"                 # in build/: the workspace's fonts, served from the project folder


def _same_file(a: Path, b: Path) -> bool:
    try:
        x, y = a.stat(), b.stat()
    except OSError:
        return False
    return x.st_size == y.st_size and (x.st_mtime_ns == y.st_mtime_ns or os.path.samefile(a, b))


def project_fonts(project) -> list[dict]:
    """The workspace's fonts as the renderer loads them: [{family, src (project-relative), weight?, style?}]. The
    renderer serves only the project folder, so each file is linked (or copied) into build/fonts/ once."""
    root = project_root(project)
    try:
        ws = find_workspace(root)
        fonts = ws.fonts if ws else {}
    except WorkspaceError:
        return []
    out, taken = [], set()
    folder = project_paths(root).build / FONTS_DIR
    for family, faces in fonts.items():
        for face in faces:
            src = Path(face["path"])
            name = src.name
            while name.lower() in taken:
                name = f"_{name}"
            taken.add(name.lower())
            dst = folder / name
            if not _same_file(src, dst):
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    dst.unlink(missing_ok=True)
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                except OSError:
                    continue
            row = {"family": family, "src": f"build/{FONTS_DIR}/{name}"}
            row.update({k: face[k] for k in ("weight", "style") if face.get(k)})
            out.append(row)
    return out


def resolve(project) -> dict:
    """resolved.json for the project (also written to build/resolved.json). Raises DocumentError for a project
    that does not fit the schema and ResolveError when the film has no length or an unknown profile."""
    resolved = _Resolver(project).run()
    path = project_paths(project).resolved
    try:
        D.write_json(path, resolved)
    except OSError:
        pass                                # read-only project: the dict is what callers use
    return resolved


def time_of(project, value) -> float:
    """A Time (seconds, "line:N[.end]", "clip:ID[.end]", "end", +/- seconds) as seconds from the film start, read
    against the project: its voice lines, every clip on every track (audio too) and the film's end. The one Time
    reader for tools (preview, describe at); timeexpr.TimeError says what is wrong."""
    e = T.parse(value)
    if e.anchor == "abs":
        return e.offset
    root = project_root(project)
    try:
        doc = D.load(root)
    except FileNotFoundError:
        raise T.TimeError(f"{value!r} needs the project, and there is no project.json in {root}") from None
    except json.JSONDecodeError as exc:
        raise T.TimeError(f"{value!r} cannot be read: project.json is not valid JSON (line {exc.lineno}: {exc.msg})") \
            from None
    except D.DocumentError as exc:
        raise T.TimeError(f"{value!r} cannot be read: project.json does not fit the format ({exc})") from None
    voice, _ = D.load_voice(root, doc.voice)
    try:
        return T.resolve(e, D.schedule(doc, voice))
    except T.TimeError as exc:
        msg = str(exc)
        raise T.TimeError(msg if str(e) in msg else f"{value}: {msg}") from None


# ------------------------------------------------------------------ describe
def _fmt_box(value, profile) -> str:
    if value is None or value == "full":
        return "full"
    if value == "safe":
        return "safe"
    return f"{value.x:g},{value.y:g} {value.w:g}x{value.h:g}"


def _short(text: str, n: int = 24) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _written(value) -> str:
    return "" if value is None or T.is_number(value) else str(value)


def _clip_summary(c, doc: D.Document) -> str:
    bits: list[str] = []
    if c.type in ("image", "video", "evidence", "audio"):
        a = doc.assets.get(c.asset)
        bits.append(f"asset {c.asset}" + ("" if a else " (missing!)"))
    if c.type == "image":
        bits += [c.fit] + ([f"motion {c.motion}"] if c.motion else [])
    elif c.type == "video":
        bits += [c.fit] + ([f"trim {c.trim_in:g}s"] if c.trim_in else []) + (["loop"] if c.loop else []) \
            + ([f"rate {c.rate:g}"] if c.rate != 1 else []) + ([f"vol {c.volume:g}"] if c.volume else []) \
            + ([f"motion {c.motion}"] if c.motion else [])
    elif c.type == "text":
        bits.append(f"\"{_short(c.text, 28)}\"")
        s = c.style
        if s is not None and s.size is not None:
            bits.append(f"size {s.size}")
        if c.reveal and c.reveal.mode != "none":
            bits.append(f"reveal {c.reveal.mode}")
    elif c.type == "shape":
        bits.append(c.shape + (" draw" if c.draw else ""))
        bits += [f"{k} {v}" for k, v in (("fill", c.fill), ("stroke", c.stroke)) if v]
    elif c.type == "evidence":
        a = doc.assets.get(c.asset)
        if a is not None and a.site:
            bits.append(f"site {a.site}")
        if c.highlight:
            at = c.highlight.at
            bits.append("highlight" + ("" if at is None else f" at +{at:g}s" if T.is_number(at) else f" at {at}"))
    elif c.type == "component":
        bits.append(c.name + " " + _short(json.dumps(c.props, ensure_ascii=False, separators=(",", ":")), 60))
    elif c.type == "audio":
        bits.append(f"vol {c.volume:g}" + (" loop" if c.loop else ""))
        bits += [f"{k} {v:g}s" for k, v in (("fade_in", c.fade_in), ("fade_out", c.fade_out)) if v]
        if c.trim_in:
            bits.append(f"trim {c.trim_in:g}s")
        if c.keyframes.get("volume"):
            bits.append(f"vol kf({len(c.keyframes['volume'])})")
        if c.duck is not None:
            bits.append(f"ducks under {c.duck.under} to {c.duck.to:g} (fade {c.duck.fade:g}s)")
    if getattr(c, "transition", None) is not None:
        bits.append(f"transition {c.transition.type} {c.transition.dur:g}s")
    if c.type != "audio":
        if c.opacity != 1:
            bits.append(f"opacity {c.opacity:g}")
        if c.keyframes:
            bits.append("kf " + " ".join(f"{p}({len(v)})" for p, v in c.keyframes.items()))
        if c.enter:
            bits.append(f"enter {c.enter.preset} {c.enter.dur:g}s")
        if c.exit:
            bits.append(f"exit {c.exit.preset} {c.exit.dur:g}s")
    return " ".join(bits)


class _Window:
    def __init__(self, project):
        self.root = project_root(project)
        self.doc = D.load(self.root)
        try:
            self.profile = D.profile_of(self.root, self.doc)
        except ValueError:
            from .profiles import get_profile
            self.profile = get_profile(None)
        try:
            self.locale = D.locale_of(self.root, self.doc)
        except ValueError:
            self.locale = locales.DEFAULT_LOCALE
        self.fps = self.profile.fps
        self.voice, _ = D.load_voice(self.root, self.doc.voice)
        self.sched = D.schedule(self.doc, self.voice)
        try:
            self.end: float | None = self.sched.film_end()
        except T.TimeError:
            self.end = None
        self._words: dict | None = None

    @property
    def words(self) -> dict:
        if self._words is None:
            texts = [t for tr in self.doc.tracks if tr.kind == "captions" for t in caption_texts(self.voice, tr)]
            self._words = word_breaks(texts, project_paths(self.root).build, self.locale) if texts else {}
        return self._words

    def box_px(self, value) -> tuple[float, float, float, float]:
        p = self.profile
        if value is None or value == "full":
            return 0, 0, p.width, p.height
        if value == "safe":
            return p.safe.x, p.safe.y, p.safe.w, p.safe.h
        return value.x, value.y, value.w, value.h

    def span(self, c) -> tuple[float, float] | str:
        try:
            return self.sched.span(c.id)
        except T.TimeError as exc:
            return str(exc)

    def clip_row(self, c) -> str:
        span = self.span(c)
        if isinstance(span, str):
            when = f"?-? ({_short(span, 70)})"
        else:
            written = [_written(c.start), _written(c.end)]
            note = f" ({written[0] or f'{span[0]:g}'} -> {written[1] or ('dur ' + format(c.dur, 'g') if c.dur else '')})" \
                if any(written) else ""
            when = f"{span[0]:.2f}-{span[1]:.2f}{note}"
        box = "" if c.type == "audio" else f"  [{_fmt_box(c.box, self.profile)}]"
        return f"{c.id} {c.type} {when}{box}  {_clip_summary(c, self.doc)}".rstrip()

    def header(self) -> list[str]:
        p, s = self.profile, self.profile.safe
        what = "the platform's UI covers the rest" if p.ui else "a title-safe margin"
        rows = [f"project {self.root.name}: {p.name} {p.width}x{p.height} {p.fps} fps, {p.orientation}; safe area x "
                f"{s.x}-{s.x + s.w}, y {s.y}-{s.y + s.h} ({what}); locale {self.locale}"]
        if self.end is not None:
            rows.append(f"duration {self.end:.2f} s ({T.to_frame(self.end, self.fps)} frames, "
                        f"{self.sched.film_end_source()})")
        else:
            rows.append("duration: unknown (see issues)")
        meta = self.doc.meta
        rows.append(f"title \"{meta.title}\" ({len(meta.title)} chars); {len(meta.sources)} source(s)")
        theme = D.theme_of(self.root, self.doc)
        rows.append(f"theme {theme.get('name', 'paper')} (a colour may name a token): "
                    + ", ".join(f"{k} {theme[k]}" for k in D.THEME_TOKENS if k in theme))
        if self.doc.markers:
            rows.append("markers (\"mark:NAME\"): " + ", ".join(self.marker(k, v) for k, v in self.doc.markers.items()))
        return rows

    def marker(self, name: str, value) -> str:
        try:
            t = f"{T.resolve(value, self.sched):.2f}"
        except T.TimeError:
            t = "?"
        return f"{name} {t}" + ("" if T.is_number(value) else f" ({value})")

    def voice_rows(self) -> list[str]:
        if not self.doc.voice:
            return ["voice: none (speak writes one)"]
        if self.voice is None:
            return [f"voice {self.doc.voice}: unreadable (see issues)"]
        rows = [f"voice {self.doc.voice}: {len(self.voice.lines)} lines, {self.voice.duration:.2f} s"]
        rows += [f"  [{ln.i}] {ln.t0:.2f}-{ln.t1:.2f} {ln.text}" for ln in self.voice.lines]
        return rows

    def track_rows(self) -> list[str]:
        rows = ["tracks, bottom to top:"]
        if not self.doc.tracks:
            rows.append("  (none yet: add_track)")
        for t in self.doc.tracks:
            hidden = ", hidden" if t.hidden else ""
            if t.kind == "captions":
                rows.append(f"  {t.id} (captions{hidden}) {self.caption_summary(t)}")
                rows += [f"    {r}" for r in self.caption_rows(t)]
                continue
            rows.append(f"  {t.id} ({t.kind}{hidden}, {len(t.clips)} clip{'s' if len(t.clips) != 1 else ''})")
            clips = sorted(t.clips, key=lambda c: s[0] if isinstance(s := self.span(c), tuple) else 1e9)
            rows += [f"    {self.clip_row(c)}" for c in clips]
        return rows

    def caption_summary(self, t: D.CaptionsTrack) -> str:
        t = caption_track(t, self.locale)
        bits = []
        if t.items is not None:
            bits.append(f"{len(t.items)} item(s) given")
        elif t.source != "voice":
            clips, asset = transcript_clips(self.doc, t)
            n = len(transcript_items(self.root, self.doc, t, self.sched, self.fps))
            via = ", ".join(c.id for c in clips) or "no clip"
            bits.append(f"from the transcript of {clips[0].asset if clips else '?'} through {via}, {n} phrase(s), "
                        f"max {t.max_chars} chars")
        else:
            n = len(voice_captions(self.voice, t, self.fps, self.words)) if self.voice else 0
            bits.append(f"from the voice, {n} phrase(s), max {t.max_chars} chars")
        if t.emphasis:
            bits.append("emphasis " + ", ".join(t.emphasis))
        if t.overrides:
            bits.append(f"{len(t.overrides)} override(s)")
        if t.box is None:
            c = self.profile.captions
            x, y, w, h = c.x, c.y, c.w, c.h
            how = f" (default: {self.profile.name}'s captions band)"
        else:
            (x, y, w, h), how = self.box_px(t.box), "" if isinstance(t.box, D.Box) else f" ({t.box})"
        bits.append(f"box {x:g},{y:g} {w:g}x{h:g}, y {y:g}-{y + h:g}{how}")
        return "; ".join(bits)

    def caption_rows(self, t: D.CaptionsTrack) -> list[str]:
        """One line per phrase: [voice line] from-to text, **accent** marked."""
        t = caption_track(t, self.locale)
        if t.items is None and t.source != "voice":
            items = transcript_items(self.root, self.doc, t, self.sched, self.fps)
        elif t.items is None and self.voice:
            items = _voice_items(self.voice, t, self.fps, self.words)
        else:
            items = caption_items(t, self.voice, self.sched, self.fps)
        rows = []
        for it in items:
            text = "".join(f"**{r['text']}**" if r.get("accent") else r["text"] for r in it["runs"])
            line = f"[{it['line']}] " if "line" in it else ""
            rows.append(f"{line}{it['from'] / self.fps:.2f}-{it['to'] / self.fps:.2f} {text}")
        return rows

    def asset_rows(self) -> list[str]:
        rows = [f"assets ({len(self.doc.assets)}):"]
        for aid, a in self.doc.assets.items():
            path = self.root / a.path
            facts = []
            if not path.is_file():
                facts.append("FILE MISSING")
            elif a.kind in ("image", "evidence"):
                size = image_size(path)
                if size:
                    facts.append(f"{size[0]}x{size[1]}")
            elif a.kind in ("video", "audio"):
                d = media_duration(path)
                if d:
                    facts.append(f"{d:.2f} s")
            if a.kind == "evidence":
                facts += [f"box {a.box}" if a.box else "no box", a.site]
            if a.transcript:
                tr = D.load_transcript(self.root, a)
                facts.append(f"transcript {len(tr['words'])} words" if tr else "transcript MISSING")
            used = [c.id for _, c in D.clips_of(self.doc) if getattr(c, "asset", None) == aid
                    or (c.type == "component" and any(k == "asset" and v == aid for _, k, v in D.prop_refs(c.props)))]
            facts.append(f"used by {', '.join(used)}" if used else "unused")
            rows.append(f"  {aid} {a.kind} {a.path} " + " ".join(f for f in facts if f))
        return rows

    def at_rows(self, at: float) -> list[str]:
        f = T.to_frame(at, self.fps)
        end = f"{self.end:.2f} s" if self.end is not None else "?"
        rows = [f"at {at:.2f} s (frame {f}) of {end}"]
        if self.voice:
            ln = next((x for x in self.voice.lines if x.t0 <= at < x.t1), None)
            rows.append(f"voice: [{ln.i}] {ln.t0:.2f}-{ln.t1:.2f} {ln.text}" if ln else "voice: (between lines)")
        rows.append("on screen, bottom to top:")
        shown = 0
        for t in self.doc.tracks:
            if t.hidden:
                continue
            if t.kind == "captions":
                cap = self.caption_at(t, f)
                if cap:
                    rows.append(f"  {t.id}: caption \"{cap}\"")
                    shown += 1
                continue
            for c in t.clips:
                span = self.span(c)
                if isinstance(span, str):
                    continue
                a, b = T.to_frame(span[0], self.fps), T.to_frame(span[1], self.fps)
                if a <= f < b:
                    kind = "plays" if t.kind == "audio" else "shows"
                    rows.append(f"  {t.id}: {self.clip_row(c)}{self.values_at(c, f - a, b - a)}")
                    shown += kind == "shows"
        if not shown:
            rows.append("  (nothing visible: a black frame)")
        return rows

    def caption_at(self, t: D.CaptionsTrack, f: int) -> str:
        t = caption_track(t, self.locale)
        if t.items is None and t.source != "voice":
            items = transcript_items(self.root, self.doc, t, self.sched, self.fps)
        else:
            items = caption_items(t, self.voice, self.sched, self.fps, self.words)
        it = next((x for x in items if x["from"] <= f < x["to"]), None)
        return "".join(r["text"] for r in it["runs"]) if it else ""

    def values_at(self, c, f: int, dur: int) -> str:
        if c.type == "audio":
            start = T.to_frame(self.sched.start(c.id), self.fps)
            rows = [{"f": T.clip_frame(k.t, start, self.fps, self.sched), "v": k.v, "ease": k.ease}
                    for k in c.keyframes.get("volume") or []]
            v = value_at(rows, f, self.fps) if rows else None
            return f"  now: volume {v:.3g}" if v is not None else ""
        vals = []
        start = T.to_frame(self.sched.start(c.id), self.fps)
        _, _, w, h = self.box_px(c.box)
        motion = motion_keyframes(getattr(c, "motion", None), dur / self.fps, w, h)
        props = {p: [{"f": 0 if k["t"] == 0 else max(1, dur - 1), "v": k["v"], "ease": k.get("ease")} for k in ks]
                 for p, ks in motion.items()}
        for p, ks in c.keyframes.items():
            rows = []
            for k in ks:
                try:
                    rows.append({"f": T.clip_frame(k.t, start, self.fps, self.sched), "v": k.v, "ease": k.ease})
                except T.TimeError:
                    pass
            if rows:
                props[p] = rows
        for p, rows in props.items():
            v = value_at(rows, f, self.fps)
            if v is not None:
                vals.append(f"{p} {v:.3g}")
        return f"  now: {', '.join(vals)}" if vals else ""


def describe(project, at=None) -> str:
    """The editor's window as text: canvas, theme, duration, voice lines, tracks bottom to top with their clips (and
    every caption phrase), assets and validation issues; with `at` (a Time), only what is on screen then."""
    root = project_root(project)
    try:
        w = _Window(root)
    except FileNotFoundError:
        return f"no project.json in {root}: create it (new_project)"
    except json.JSONDecodeError as exc:
        return f"project.json is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}): fix it by hand"
    except D.DocumentError as exc:
        return "project.json does not fit the format; fix these first:\n" + "\n".join(f"  {i}" for i in exc.issues)
    if at is not None:
        try:
            rows = w.at_rows(time_of(root, at))
        except T.TimeError as exc:
            return f"cannot read the time: {exc}"
    else:
        rows = w.header() + w.voice_rows() + w.track_rows() + w.asset_rows()
    issues: list[Issue] = D.validate(root, w.doc)
    if issues:
        rows.append(f"issues ({len(issues)}):")
        rows += [f"  {i}" for i in issues[:40]] + ([f"  ... and {len(issues) - 40} more"] if len(issues) > 40 else [])
    else:
        rows.append("issues: none")
    return "\n".join(rows)
