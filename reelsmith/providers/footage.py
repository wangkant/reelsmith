"""Looking at footage: probe (streams, codecs, loudness), frames (stills of a source at source times), scenes (shot
cuts) and silences (quiet ranges and the speech between them). Times here are SOURCE seconds; a clip's
"src:<clip>@<seconds>" Time puts one on the timeline. Stills go to build/footage/<name>/ (regenerable)."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import media as M
from ..workspace import project_file
from .config import Context, ProviderError, check_id, context, exe, number, probe as ffprobe, read_project, \
    run_tree, safe_tool, tail

MAX_STILLS = 24
DEFAULT_STILLS = 12
STILL_EDGE = 960                # px: the long edge of a still, enough to read and cheap to look at
TILE_EDGE = 360                 # px: the long edge of a contact sheet tile
MAX_SHEET = 48                  # first-frame tiles in one scene sheet
MAX_ROWS = 200                  # rows of a range list in the text (the JSON keeps them all)
SCENE_SCALE = 240               # px wide while scoring cuts: faster, and enough to see a cut
MIN_SHOT_S = 0.1                # cuts closer than this are one flash, not two shots
_HMS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
HDR_TRANSFERS = {"smpte2084": "PQ", "arib-std-b67": "HLG"}
HDR_NOTE = ("the film is SDR (BT.709) and the renderer does not tone-map: its highlights clip and its colours look "
            "different next to SDR shots; convert it to SDR first if they must match")


@dataclass
class Media:
    path: Path
    rel: str                    # project-relative, as shown
    name: str                   # asset id, else the file stem: the stills folder
    asset: str | None           # asset id when one was named


def _name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text)[:64] or "file"


def asset_file(ctx: Context, asset_id: str, entry: dict) -> Path:
    """The file of a project.json asset: inside the project folder (as check requires) and present."""
    path = project_file(ctx.project, entry.get("path"))
    if path is None:
        raise ProviderError(f"asset {asset_id!r} points at {entry.get('path')!r}, outside the project folder: "
                            "import_asset copies a file in")
    if not path.is_file():
        raise ProviderError(f"asset {asset_id!r} points at {entry.get('path')}, which is missing")
    return path


def _resolve(ctx: Context, source) -> Media:
    """An asset id, or a file inside the project folder."""
    text = str(source or "").strip()
    if not text:
        raise ProviderError("name an asset id (see assets) or a file inside the project folder")
    assets = read_project(ctx).get("assets") or {}
    entry = assets.get(text)
    if entry is not None:
        check_id(text, "asset id")
        return Media(asset_file(ctx, text, entry), entry["path"], _name(text), text)
    root = ctx.project.resolve()
    rel = Path(text)
    if rel.is_absolute():               # by name first: nothing outside is opened
        try:
            rel = rel.relative_to(root)
        except ValueError:
            rel = None
    path = project_file(root, rel) if rel is not None else None
    if path is None:
        raise ProviderError(f"{text} is outside the project folder: import_asset it first")
    if not path.is_file():
        known = ", ".join(sorted(assets)) or "none yet"
        raise ProviderError(f"no asset or file {text!r} (assets: {known})")
    return Media(path, path.relative_to(root).as_posix(), _name(path.stem), None)


def _rate(text) -> float:
    rate = M.frame_rate(text)
    return round(rate, 3) if 0 < rate < 1000 else 0.0


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if isinstance(side, dict) and "rotation" in side:
            try:
                return int(round(float(side["rotation"]))) % 360
            except (TypeError, ValueError):
                pass
    try:
        return int((stream.get("tags") or {}).get("rotate") or 0) % 360
    except (TypeError, ValueError):
        return 0


def _num(value, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def hdr_of(stream: dict) -> str | None:
    """"PQ", "HLG" or "Dolby Vision" (with its fallback transfer) for an HDR picture stream; None for SDR."""
    base = HDR_TRANSFERS.get(str(stream.get("color_transfer") or ""))
    dovi = any(isinstance(s, dict) and "dovi" in str(s.get("side_data_type") or "").lower()
               for s in stream.get("side_data_list") or [])
    if dovi:
        return f"Dolby Vision, {base}" if base else "Dolby Vision"
    return base


def hdr_of_file(path: Path) -> str | None:
    """hdr_of the file's first picture stream (ffprobe); ProviderError when it cannot be read."""
    for s in ffprobe(path).get("streams") or []:
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic"):
            return hdr_of(s)
    return None


def facts(path: Path) -> dict:
    """ffprobe's answer as plain facts: duration, the first picture stream, the first sound stream."""
    info = ffprobe(path)
    fmt = info.get("format") or {}
    streams = [s for s in info.get("streams") or [] if isinstance(s, dict)]
    pictures = [s for s in streams if s.get("codec_type") == "video"
                and not (s.get("disposition") or {}).get("attached_pic")]
    sounds = [s for s in streams if s.get("codec_type") == "audio"]
    out: dict = {"container": fmt.get("format_name"), "duration_s": _num(fmt.get("duration")),
                 "size_bytes": _num(fmt.get("size"), int), "bit_rate": _num(fmt.get("bit_rate"), int),
                 "video": None, "audio": None, "streams": len(streams)}
    if out["duration_s"] is not None:
        out["duration_s"] = round(out["duration_s"], 3)
    if pictures:
        v = pictures[0]
        w, h, rot = _num(v.get("width"), int), _num(v.get("height"), int), _rotation(v)
        still = (v.get("codec_name") in ("png", "mjpeg", "webp", "gif", "bmp") and not out["duration_s"]) \
            or _rate(v.get("avg_frame_rate")) == 0
        out["video"] = {"codec": v.get("codec_name"), "width": w, "height": h, "rotation": rot,
                        "display": [h, w] if rot in (90, 270) else [w, h],
                        "fps": _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")),
                        "pix_fmt": v.get("pix_fmt"), "frames": _num(v.get("nb_frames"), int),
                        "bit_rate": _num(v.get("bit_rate"), int), "still": bool(still),
                        "color": {"primaries": v.get("color_primaries"), "transfer": v.get("color_transfer"),
                                  "space": v.get("color_space"), "range": v.get("color_range")},
                        "hdr": hdr_of(v)}
    if sounds:
        a = sounds[0]
        out["audio"] = {"codec": a.get("codec_name"), "channels": _num(a.get("channels"), int),
                        "layout": a.get("channel_layout"), "sample_rate": _num(a.get("sample_rate"), int),
                        "bit_rate": _num(a.get("bit_rate"), int), "streams": len(sounds)}
    return out


def loudness(path: Path) -> dict:
    """Integrated loudness, loudness range and true peak of the whole file (ffmpeg ebur128)."""
    _, _, err, timed = run_tree([exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                                 "ebur128=peak=true", "-f", "null", "-"], timeout=900)
    if timed:
        return {}

    def last(pattern: str):
        found = re.findall(pattern, err or "")
        return float(found[-1]) if found and found[-1] != "-inf" else None
    return {"lufs": last(r"I:\s+(-?[\d.]+|-inf) LUFS"), "lra": last(r"LRA:\s+(-?[\d.]+|-inf) LU"),
            "true_peak_db": last(r"Peak:\s+(-?[\d.]+|-inf) dBFS")}


def _secs(t: float) -> str:
    return f"{t:.2f}s"


def _clock(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}" if m else f"{s:.2f}s"


# ------------------------------------------------------------------ probe
@safe_tool
def probe(project, source):
    """(text, is_error): what a media file holds, as text and JSON (an HDR picture is flagged)."""
    ctx = context(project)
    m = _resolve(ctx, source)
    f = facts(m.path)
    if f.get("audio"):
        f["audio"].update(loudness(m.path))
    f["path"] = m.rel
    if m.asset:
        f["asset"] = m.asset
    rows = [f"{m.rel}" + (f" (asset {m.asset})" if m.asset else "") + f": {f.get('container') or '?'}"
            + (f", {f['duration_s']:.3f} s" if f.get("duration_s") else "")
            + (f", {f['size_bytes'] / (1 << 20):.1f} MB" if f.get("size_bytes") else "")]
    v, a = f.get("video"), f.get("audio")
    if v:
        turn = f", rotated {v['rotation']} (shows {v['display'][0]}x{v['display'][1]})" if v["rotation"] else ""
        what = "picture" if v["still"] else f"{v['fps']:g} fps" + (f", {v['frames']} frames" if v["frames"] else "")
        col = v["color"]
        tags = "/".join(x for x in (col["primaries"], col["transfer"], col["space"]) if x and x != "unknown")
        rows.append(f"  video: {v['codec']} {v['width']}x{v['height']}{turn}, {what}, {v['pix_fmt']}"
                    + (f", colour {tags}" if tags else ""))
        if v["hdr"]:
            rows.append(f"  HDR ({v['hdr']}): {HDR_NOTE}")
    else:
        rows.append("  video: none")
    if a:
        loud = ", ".join(x for x in (
            f"{a['lufs']:.1f} LUFS" if a.get("lufs") is not None else "silent or unmeasured",
            f"LRA {a['lra']:.1f} LU" if a.get("lra") is not None else "",
            f"true peak {a['true_peak_db']:.1f} dBTP" if a.get("true_peak_db") is not None else "") if x)
        rows.append(f"  audio: {a['codec']} {a['channels']} ch ({a.get('layout') or '?'}), {a['sample_rate']} Hz; "
                    f"{loud}")
    else:
        rows.append("  audio: none")
    rows.append("JSON: " + json.dumps(f, ensure_ascii=False))
    return "\n".join(rows), False


# ------------------------------------------------------------------ stills
def _when(value, what: str) -> float:
    if isinstance(value, str):
        text = value.strip().rstrip("s")
        hms = _HMS.match(text)
        if hms:
            return int(hms.group(1) or 0) * 3600 + int(hms.group(2)) * 60 + float(hms.group(3))
        try:
            value = float(text)
        except ValueError:
            raise ProviderError(f"{what} {value!r}: give source seconds (12.5) or m:ss (1:02.5)") from None
    return number(value, 0, 1e7, what)


def _folder(ctx: Context, m: Media, sub: str) -> Path:
    out = project_file(ctx.project, Path("build", "footage", m.name, sub))
    if out is None:                     # a link under build/ would make the rmtree below delete someone else's files
        raise ProviderError("build/footage leads outside the project folder (a link?): delete it, then call again")
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _still(src: Path, t: float, out: Path) -> bool:
    scale = f"scale='if(gte(iw,ih),min({STILL_EDGE},iw),-2)':'if(gte(iw,ih),-2,min({STILL_EDGE},ih))'"
    rc, _, _, _ = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i",
                            str(src), "-frames:v", "1", "-vf", scale, str(out)], timeout=120)
    return rc == 0 and out.is_file()


def _tile(w: int, h: int) -> tuple[int, int]:
    if not (w and h):
        return TILE_EDGE, TILE_EDGE
    if w >= h:
        return TILE_EDGE, max(80, int(TILE_EDGE * h / w) // 2 * 2)
    return max(80, int(TILE_EDGE * w / h) // 2 * 2), TILE_EDGE


def _sheet(pngs: list[Path], labels: list[str], out: Path, size: tuple[int, int]) -> Path | None:
    if not pngs:
        return None
    try:
        return M.contact_sheet(pngs, out, [], size, _tile(*size), labels=labels)
    except RuntimeError:
        return None


def _video_facts(m: Media) -> tuple[float, float, tuple[int, int]]:
    f = facts(m.path)
    v = f.get("video")
    if not v or v.get("still"):
        raise ProviderError(f"{m.rel} has no moving picture to take stills from"
                            + (" (it is audio only)" if not v else " (it is a still image: Read it)"))
    dur = f.get("duration_s") or 0.0
    if dur <= 0:
        raise ProviderError(f"{m.rel} has no readable duration")
    disp = v.get("display") or [v.get("width") or 0, v.get("height") or 0]
    return dur, v.get("fps") or 30.0, (int(disp[0] or 0), int(disp[1] or 0))


@safe_tool
def frames(project, asset, times=None, every=None, n=None):
    """(text, is_error): stills of a source at source seconds, and a contact sheet with the times burned in."""
    ctx = context(project)
    m = _resolve(ctx, asset)
    dur, fps, size = _video_facts(m)
    last = max(0.0, dur - 1.0 / fps)
    if times:
        wanted = [_when(t, "times") for t in (times if isinstance(times, list) else [times])]
        if len(wanted) > MAX_STILLS:
            return f"{len(wanted)} times; at most {MAX_STILLS} per call: split the request", True
        late = [t for t in wanted if t > dur + 1e-6]
        if late:
            return f"{', '.join(_secs(t) for t in late)} past the end of {m.rel} ({dur:.2f} s)", True
    elif every:
        step = number(every, 0.04, 1e6, "every")
        count = int((dur - 1e-6) / step) + 1          # stills before the end, from 0
        if count > MAX_STILLS:
            return (f"every {step:g} s over {dur:.1f} s is {count} stills; at most {MAX_STILLS} per call: use a larger "
                    f"every (at least {dur / (MAX_STILLS - 1):.1f}), n, or times"), True
        wanted = [i * step for i in range(count)]
    else:
        count = int(number(n if n else DEFAULT_STILLS, 1, MAX_STILLS, "n"))
        wanted = [dur * (i + 0.5) / count for i in range(count)]
    wanted = sorted({round(min(last, t), 3) for t in wanted})
    out = _folder(ctx, m, "frames")
    shots = [(t, out / f"frame_{t:09.3f}s.png") for t in wanted]
    shots = [(t, p) for t, p in shots if _still(m.path, t, p)]
    if not shots:
        return f"ffmpeg could not take a still from {m.rel}", True
    sheet = _sheet([p for _, p in shots], [_clock(t) for t, _ in shots], out / "contact.png", size)
    rows = [f"{len(shots)} still(s) of {m.rel} ({dur:.2f} s, {size[0]}x{size[1]}) at source times (look with Read):"]
    rows += [f"- {_secs(t)}: {p}" for t, p in shots]
    if sheet:
        rows.append(f"contact sheet (source times burned in): {sheet}")
    return "\n".join(rows), False


# ------------------------------------------------------------------ scenes
def cut_times(path: Path, threshold: float) -> list[float]:
    """Source seconds where the picture changes by more than `threshold` (ffmpeg's scene score, 0..1)."""
    vf = f"scale={SCENE_SCALE}:-2,select='gt(scene\\,{threshold:g})',showinfo"
    rc, _, err, timed = run_tree([exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-an", "-sn", "-dn",
                                  "-vf", vf, "-f", "null", "-"], timeout=1800)
    if timed:
        raise ProviderError("scene detection ran over 30 minutes and was stopped")
    if rc != 0:
        raise ProviderError(f"ffmpeg could not scan {path.name}: {tail(err)}")
    return [float(x) for x in re.findall(r"pts_time:\s*([\d.]+)", err or "")]


def shots_of(cuts: list[float], dur: float) -> list[dict]:
    starts = [0.0]
    for t in sorted(cuts):
        if MIN_SHOT_S <= t <= dur - MIN_SHOT_S and t - starts[-1] >= MIN_SHOT_S:
            starts.append(round(t, 3))
    ends = starts[1:] + [round(dur, 3)]
    return [{"i": i + 1, "start": a, "end": b, "dur": round(b - a, 3)} for i, (a, b) in enumerate(zip(starts, ends))]


@safe_tool
def scenes(project, asset, threshold=0.3):
    """(text, is_error): shot cuts of a video in source seconds, and a sheet of each shot's first frame."""
    ctx = context(project)
    m = _resolve(ctx, asset)
    thr = number(threshold if threshold is not None else 0.3, 0.01, 0.99, "threshold")
    dur, fps, size = _video_facts(m)
    shots = shots_of(cut_times(m.path, thr), dur)
    out = _folder(ctx, m, "scenes")
    firsts = []
    for s in shots[:MAX_SHEET]:
        png = out / f"shot_{s['i']:03d}.png"
        if _still(m.path, min(max(0.0, dur - 1.0 / fps), s["start"] + 0.5 / fps), png):
            firsts.append((s, png))
    sheet = _sheet([p for _, p in firsts], [f"#{s['i']} {_clock(s['start'])}" for s, _ in firsts],
                   out / "contact.png", size)
    rows = [f"{len(shots)} shot(s) in {m.rel} ({dur:.2f} s; a cut where the scene score passes {thr:g}), source "
            "seconds:"]
    rows += [f"  #{s['i']} {s['start']:.2f}-{s['end']:.2f} ({s['dur']:.2f} s)" for s in shots[:MAX_ROWS]]
    if len(shots) > MAX_ROWS:
        rows.append(f"  ... {len(shots) - MAX_ROWS} more (in the JSON)")
    if sheet:
        more = f" (the first {MAX_SHEET})" if len(shots) > MAX_SHEET else ""
        rows.append(f"first frames{more}, look with Read: {sheet}")
    if len(shots) == 1:
        rows.append("one continuous shot: try a lower threshold (0.15) if you expected cuts")
    rows.append("JSON: " + json.dumps({"path": m.rel, "duration_s": dur, "threshold": thr, "shots": shots}))
    return "\n".join(rows), False


# ------------------------------------------------------------------ silences
def silent_ranges(path: Path, min_s: float, noise_db: float, dur: float) -> list[dict]:
    rc, _, err, timed = run_tree([exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-sn", "-dn",
                                  "-af", f"silencedetect=noise={noise_db:g}dB:d={min_s:g}", "-f", "null", "-"],
                                 timeout=1800)
    if timed:
        raise ProviderError("silence detection ran over 30 minutes and was stopped")
    if rc != 0:
        raise ProviderError(f"ffmpeg could not scan {path.name}: {tail(err)}")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", err or "")]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", err or "")]
    out = []
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else dur          # silent to the end: ffmpeg prints no end
        a, b = max(0.0, a), min(dur, b)
        if b - a > 1e-3:
            out.append({"start": round(a, 3), "end": round(b, 3), "dur": round(b - a, 3)})
    return out


def speech_ranges(silent: list[dict], dur: float) -> list[dict]:
    out, pos = [], 0.0
    for s in silent:
        if s["start"] - pos > 1e-3:
            out.append({"start": round(pos, 3), "end": s["start"], "dur": round(s["start"] - pos, 3)})
        pos = max(pos, s["end"])
    if dur - pos > 1e-3:
        out.append({"start": round(pos, 3), "end": round(dur, 3), "dur": round(dur - pos, 3)})
    return out


@safe_tool
def silences(project, asset, min_s=0.5, noise_db=-35):
    """(text, is_error): quiet ranges of a source in source seconds, and the sound between them."""
    ctx = context(project)
    m = _resolve(ctx, asset)
    least = number(min_s if min_s is not None else 0.5, 0.05, 60, "min_s")
    floor = number(noise_db if noise_db is not None else -35, -90, -5, "noise_db")
    f = facts(m.path)
    if not f.get("audio"):
        return f"{m.rel} has no sound to scan", True
    dur = f.get("duration_s") or 0.0
    quiet = silent_ranges(m.path, least, floor, dur)
    sound = speech_ranges(quiet, dur)

    def listed(items: list[dict]) -> list[str]:
        rows = [f"  {i}. {r['start']:.2f}-{r['end']:.2f} ({r['dur']:.2f} s)" for i, r in enumerate(items[:MAX_ROWS], 1)]
        return rows + ([f"  ... {len(items) - MAX_ROWS} more (in the JSON)"] if len(items) > MAX_ROWS else [])
    rows = [f"{len(quiet)} silence(s) in {m.rel} ({dur:.2f} s; under {floor:g} dB for {least:g} s or more), "
            f"{sum(r['dur'] for r in quiet):.2f} s in all, source seconds:"] + listed(quiet)
    rows += [f"sound between them: {len(sound)} range(s), {sum(r['dur'] for r in sound):.2f} s:"] + listed(sound)
    rows.append('On the timeline, source second S of clip C plays at "src:C@S": a jump cut is ripple_delete '
                '{"start": "src:C@<silence start + 0.1>", "end": "src:C@<silence end - 0.1>"} (cut from the last '
                "silence back, so the earlier times stay put).")
    rows.append("JSON: " + json.dumps({"path": m.rel, "duration_s": dur, "min_s": least, "noise_db": floor,
                                       "silences": quiet, "sound": sound}))
    return "\n".join(rows), False
