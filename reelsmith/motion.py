"""Motion baked into video on this machine: tween fills the frames between key pictures of one shot (RIFE), parallax
moves a camera through one still by its estimated depth (Depth Anything V2). Both write silent H.264 video assets.
numpy, onnxruntime and py7zr come with the "motion" extra; the two models are fetched once into the workspace cache."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .providers.config import (NO_WINDOW, ProviderError, check_id, check_replaceable, context, exe, existing_asset,
                               project_profile, register_asset, rel, safe_tool, tail)

EXTRA = 'pip install "reelsmith[motion]"'
MAX_CLIP_S = 12.0
KEYS = (2, 6)
MAX_OVERSCAN = 1.2          # past this the picture softens visibly
MAX_GAP = 0.05              # widest uncovered strip (of the width) before the background fill smears visibly
EDGE_GROW = 0.002           # near side of depth edges grown by this share of the width: no fringe left behind
NEAR_Z, FAR_Z = 1.0, 10.0   # nearness 1 sits at distance 1, nearness 0 at 10
CRF = "16"


@dataclass(frozen=True)
class Model:
    label: str
    file: str               # its name under <cache>/models/
    url: str
    size: int               # of what the url serves
    sha256: str
    member: str = ""        # inside an archive: the one file kept
    member_size: int = 0
    member_sha256: str = ""


MODELS = {
    "depth": Model("Depth Anything V2 Small (Apache-2.0)", "depth-anything-v2-small.onnx",
                   "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
                   99060839, "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c"),
    "rife": Model("RIFE 4.25 (MIT)", "rife-v4.25.onnx",
                  "https://github.com/AmusementClub/vs-mlrt/releases/download/external-models/rife_v4.25.7z",
                  21026388, "172fe975c1775134bb87108e4ec6d1a89e861cc5d3be2ac23bf08afe5ed626b8",
                  "rife_v2/rife_v4.25.onnx", 22748049,
                  "65c57a5e4abb17ad67faf35054291ac53affab0506d509d2e66698f6ecd75584"),
}
_SESSIONS: dict = {}
_LOCK = threading.Lock()


def _say(text: str) -> None:
    print(f"reelsmith: {text}", file=sys.stderr, flush=True)


def _need(tool: str, modules=("numpy", "onnxruntime", "py7zr")) -> None:
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing:
        raise ProviderError(f"{tool} needs the motion extra ({', '.join(missing)} missing): {EXTRA}")


# ------------------------------------------------------------------ models
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _matches(path: Path, size: int, sha: str) -> str:
    """'' when the file is the pinned one, else why not."""
    got = path.stat().st_size
    if got != size:
        return f"it is {got} bytes, not {size}"
    digest = _sha256(path)
    return "" if digest == sha else f"its SHA-256 is {digest}, not {sha}"


def _download(url: str, dest: Path, say) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "reelsmith"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
        total, got, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        while chunk := r.read(1 << 20):
            fh.write(chunk)
            got += len(chunk)
            step = int(got * 4 / total) if total else -1
            if step != shown and step >= 0:
                shown = step
                say(f"downloading {Path(url).name}: {got >> 20} of {total >> 20} MB")


def _unique(folder: Path, name: str, suffix: str) -> Path:
    """A new empty file in `folder`: concurrent calls never share a temporary name."""
    fd, path = tempfile.mkstemp(prefix=f".{name}.", suffix=suffix, dir=folder)
    os.close(fd)
    return Path(path)


def _stamped(stamp: Path, sha: str) -> bool:
    try:
        return stamp.read_text(encoding="utf-8").strip() == sha
    except OSError:
        return False


def _stamp(stamp: Path, sha: str) -> None:
    tmp = _unique(stamp.parent, stamp.name, ".part")
    try:
        tmp.write_text(sha, encoding="utf-8")
        os.replace(tmp, stamp)
    except OSError:
        pass                # the stamp only saves a re-hash; another call may be reading it
    finally:
        tmp.unlink(missing_ok=True)


def _place(src: Path, target: Path, size: int, sha: str) -> None:
    try:
        os.replace(src, target)
    except OSError as exc:
        # another call put the model there first and may still be reading it
        if not (target.is_file() and not _matches(target, size, sha)):
            raise ProviderError(f"could not put the model in place as {target} ({exc.strerror or exc}); "
                                "try again") from None


def ensure_model(cache_dir: Path, name: str, download=_download, say=_say) -> Path:
    """The model's file in <cache>/models/, fetched and checked by size and SHA-256 the first time."""
    spec = MODELS[name]
    folder = Path(cache_dir) / "models"
    target = folder / spec.file
    size, sha = (spec.member_size, spec.member_sha256) if spec.member else (spec.size, spec.sha256)
    stamp = target.with_name(target.name + ".sha256")
    if target.is_file() and target.stat().st_size == size and _stamped(stamp, sha):
        return target
    by_hand = (f"Put it there by hand: download {spec.url}"
               + (f", take {spec.member} out of the archive" if spec.member else "") + f" and save it as {target}")
    if target.is_file():
        why = _matches(target, size, sha)
        if not why:
            _stamp(stamp, sha)
            return target
        raise ProviderError(f"{target} is not the {spec.label} model: {why}. Delete it to fetch it again. "
                            f"{by_hand}")
    folder.mkdir(parents=True, exist_ok=True)
    part = _unique(folder, Path(spec.url).name, ".part")
    member = _unique(folder, spec.file, ".part") if spec.member else part
    say(f"fetching the {spec.label} model once ({spec.size >> 20} MB) from {spec.url} into {folder}")
    try:
        try:
            download(spec.url, part, say)
        except Exception as exc:  # noqa: BLE001 - any network failure gets the same instructions
            raise ProviderError(f"could not download the {spec.label} model from {spec.url}: "
                                f"{type(exc).__name__}: {exc}. {by_hand}") from None
        why = _matches(part, spec.size, spec.sha256)
        if why:
            raise ProviderError(f"the download from {spec.url} is not the pinned {spec.label} model: {why}. "
                                f"{by_hand}")
        if spec.member:
            _unpack(part, spec.member, member, by_hand)
            why = _matches(member, size, sha)
            if why:
                raise ProviderError(f"{spec.member} in {spec.url} is not the pinned model: {why}. {by_hand}")
        _place(member, target, size, sha)
    finally:
        part.unlink(missing_ok=True)
        member.unlink(missing_ok=True)
    _stamp(stamp, sha)
    say(f"{spec.label} model ready: {target}")
    return target


def _unpack(archive: Path, member: str, dest: Path, by_hand: str) -> None:
    import py7zr
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        try:
            with py7zr.SevenZipFile(archive) as z:
                z.extract(path=tmp, targets=[member])
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"cannot unpack {archive.name}: {type(exc).__name__}: {exc}. {by_hand}") from None
        got = Path(tmp) / member
        if not got.is_file():
            raise ProviderError(f"{archive.name} holds no {member}. {by_hand}")
        os.replace(got, dest)


def _session(path: Path):
    with _LOCK:
        key = str(path)
        if key not in _SESSIONS:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
            _SESSIONS[key] = ort.InferenceSession(key, so, providers=["CPUExecutionProvider"])
        return _SESSIONS[key]


def rife(cache_dir: Path):
    """interpolate(a, b, t): the picture at time t (0..1) between HxWx3 float pictures a and b."""
    import numpy as np
    sess = _session(ensure_model(cache_dir, "rife"))
    name = sess.get_inputs()[0].name

    def interpolate(a, b, t):
        h, w = a.shape[:2]
        x = np.concatenate([a.transpose(2, 0, 1), b.transpose(2, 0, 1),
                            np.full((1, h, w), t, dtype=np.float32)])[None].astype(np.float32)
        y = sess.run(None, {name: x})[0]
        return np.clip(y[0, :, :h, :w], 0, 1).transpose(1, 2, 0)
    return interpolate


def depth_anything(cache_dir: Path):
    """estimate(img): HxW nearness 0..1 (larger is nearer) of an HxWx3 float picture."""
    import numpy as np
    from PIL import Image
    sess = _session(ensure_model(cache_dir, "depth"))
    name = sess.get_inputs()[0].name
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def estimate(img):
        h, w = img.shape[:2]
        k = 518 / min(h, w)
        ih, iw = max(14, round(h * k / 14) * 14), max(14, round(w * k / 14) * 14)
        pic = Image.fromarray((img * 255 + 0.5).astype(np.uint8)).resize((iw, ih), Image.BICUBIC)
        x = ((np.asarray(pic, dtype=np.float32) / 255 - mean) / std).transpose(2, 0, 1)[None]
        d = np.squeeze(sess.run(None, {name: x.astype(np.float32)})[0]).astype(np.float32)
        lo, hi = np.percentile(d, [1, 99.5])
        d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        return np.asarray(Image.fromarray(d).resize((w, h), Image.BICUBIC), dtype=np.float32).clip(0, 1)
    return estimate


# ------------------------------------------------------------------ shared
def _image_asset(ctx, asset_id, what: str) -> Path:
    if not isinstance(asset_id, str) or not asset_id:
        raise ProviderError(f"{what} must be an image asset id of this project (see assets)")
    entry = existing_asset(ctx, asset_id)
    if entry is None or entry.get("kind") != "image":
        raise ProviderError(f"{what} {asset_id!r} is not an image asset of this project (draw or import it first; "
                            "see assets)")
    path = (ctx.project / str(entry.get("path") or "")).resolve()
    if not path.is_file() or ctx.project not in path.parents:
        raise ProviderError(f"{what} {asset_id!r}: its file {entry.get('path')!r} is missing")
    return path


def _number(value, what: str, low: float, high: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ProviderError(f"{what} must be a number from {low:g} to {high:g} (got {value!r})") from None
    if not (low <= v <= high) or math.isnan(v):
        raise ProviderError(f"{what} must be from {low:g} to {high:g} (got {v:g})")
    return v


def _fps(ctx, fps) -> float:
    if fps in (None, "", 0):
        return float(project_profile(ctx).fps)
    return _number(fps, "fps", 1, 60)


def _still(path: Path, asset_id: str, what: str, tool: str, fix: str) -> tuple[int, int]:
    """(w, h) of an opaque picture this tool can read; else a sentence saying what to do."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            size = im.size
            alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            low = im.convert("RGBA").getchannel("A").getextrema()[0] if alpha else 255
    except Exception:  # noqa: BLE001 - any decoder failure means the same thing here
        raise ProviderError(f"{what} {asset_id!r} cannot be read as a picture; draw or import it again") from None
    if not (size[0] > 0 and size[1] > 0):
        raise ProviderError(f"{what} {asset_id!r} cannot be read as a picture (it has no size); draw or import "
                            "it again")
    if low < 255:
        raise ProviderError(f"{what} {asset_id!r} has transparent pixels, but {tool} makes opaque video with no "
                            f"transparency: {fix}")
    return size


def _out_size(ctx, w: int, h: int) -> tuple[int, int]:
    """The picture's own size, no larger than it needs to cover the canvas (a wide plate keeps the width a pan
    runs across), even sides (H.264 4:2:0)."""
    prof = project_profile(ctx)
    k = min(1.0, max(prof.width / w, prof.height / h))
    return max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)


def _load(path: Path, size: tuple[int, int]):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 255


class _Encoder:
    """Raw RGB frames into an H.264 mp4 through ffmpeg's stdin, written to a temporary file first."""

    def __init__(self, out: Path, w: int, h: int, fps: float):
        self.out, self.part = out, out.with_name(out.stem + ".part.mp4")
        self.err = tempfile.TemporaryFile()
        rate = Fraction(fps).limit_denominator(1001)
        self.proc = subprocess.Popen(
            [exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{w}x{h}", "-r", f"{rate.numerator}/{rate.denominator}", "-i", "-", "-an",
             # swscale defaults to BT.601; HD players read untagged video as BT.709
             # ffmpeg 8 takes the tags from the frames, so setparams, not only the output flags
             "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:"
             "color_trc=bt709:colorspace=bt709:range=tv", "-c:v", "libx264",
             "-preset", "medium", "-crf", CRF, "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries",
             "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(self.part)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.err, creationflags=NO_WINDOW)
        self.frames = 0

    def write(self, frame) -> None:
        import numpy as np
        self.proc.stdin.write((np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        self.frames += 1

    def close(self) -> None:
        self.proc.stdin.close()
        rc = self.proc.wait(timeout=600)
        self.err.seek(0)
        err = self.err.read().decode("utf-8", "replace")
        self.err.close()
        if rc != 0 or not self.part.is_file():
            self.part.unlink(missing_ok=True)
            raise ProviderError(f"ffmpeg could not encode {self.out.name}: {tail(err)}")
        os.replace(self.part, self.out)

    def abort(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()
        self.err.close()
        self.part.unlink(missing_ok=True)


def _encode(out: Path, w: int, h: int, fps: float, frames) -> int:
    enc = _Encoder(out, w, h, fps)
    try:
        for f in frames:
            enc.write(f)
    except BaseException:
        enc.abort()
        raise
    enc.close()
    return enc.frames


# ------------------------------------------------------------------ tween
def tween_plan(seconds: list[float], fps: float, hold_first: float = 0, hold_last: float = 0) -> list[tuple]:
    """One item a frame: (i, None) shows key i as drawn, (i, t) the picture at t between keys i and i+1."""
    total = hold_first + seconds[-1] + hold_last
    plan = []
    for k in range(max(2, round(total * fps) + 1)):
        s = min(max(k / fps - hold_first, 0.0), seconds[-1])
        i = next(j for j in range(len(seconds) - 1) if s <= seconds[j + 1] + 1e-9)
        t = (s - seconds[i]) / (seconds[i + 1] - seconds[i])
        if t < 1e-6:
            plan.append((i, None))
        elif t > 1 - 1e-6:
            plan.append((i + 1, None))
        else:
            plan.append((i, round(t, 6)))
    return plan


def _tween_args(ctx, frames, seconds, hold_first, hold_last) -> tuple[list[Path], list[float], float, float, tuple]:
    if not isinstance(frames, list) or not (KEYS[0] <= len(frames) <= KEYS[1]):
        raise ProviderError(f"frames must be a list of {KEYS[0]}-{KEYS[1]} image asset ids, the key pictures of "
                            "one shot in order")
    paths = [_image_asset(ctx, f, "frame") for f in frames]
    if not isinstance(seconds, list) or len(seconds) != len(frames):
        raise ProviderError(f"seconds must give one time for each key picture ({len(frames)} numbers, the first 0)")
    times = [_number(s, "each of seconds", 0, MAX_CLIP_S) for s in seconds]
    if times[0] != 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ProviderError(f"seconds must start at 0 and rise strictly (got {times}): each is when its key picture "
                            "is reached")
    hf = _number(hold_first, "hold_first", 0, MAX_CLIP_S)
    hl = _number(hold_last, "hold_last", 0, MAX_CLIP_S)
    if hf + times[-1] + hl > MAX_CLIP_S:
        raise ProviderError(f"the clip would last {hf + times[-1] + hl:g} s; at most {MAX_CLIP_S:g} s: make several "
                            "clips")
    sizes = [_still(p, f, "frame", "tween", "draw the poses on their full background without cutout, or use a "
                    "Photo for the cut-out") for p, f in zip(paths, frames)]
    for f, s in zip(frames, sizes):
        if s != sizes[0]:
            shape = "aspect" if abs(s[0] / s[1] - sizes[0][0] / sizes[0][1]) > 0.005 else "size"
            raise ProviderError(f"{f!r} is {s[0]}x{s[1]} but {frames[0]!r} is {sizes[0][0]}x{sizes[0][1]} (a "
                                f"different {shape}): key pictures must be the same shot at the same size; draw it "
                                f"with match_asset={frames[0]!r}")
    return paths, times, hf, hl, sizes[0]


@safe_tool
def tween(project, id, frames, seconds, fps=0, hold_first=0.0, hold_last=0.0, *, interpolate=None, progress=None):
    """(text, is_error): assets/<id>.mp4 moving through key pictures of one shot at their times."""
    started = time.monotonic()
    _need("tween", ("numpy",) if interpolate else ("numpy", "onnxruntime", "py7zr"))
    ctx = context(project)
    asset_id = check_id(id)
    paths, times, hf, hl, size = _tween_args(ctx, frames, seconds, hold_first, hold_last)
    check_replaceable(ctx, asset_id, "video")
    rate = _fps(ctx, fps)
    w, h = _out_size(ctx, *size)
    interpolate = interpolate or rife(ctx.cache_dir)
    keys = [_load(p, (w, h)) for p in paths]
    plan = tween_plan(times, rate, hf, hl)
    todo = sum(1 for _, t in plan if t is not None)

    def pictures():
        done = 0
        for i, t in plan:
            if t is None:
                yield keys[i]
                continue
            yield interpolate(keys[i], keys[i + 1], t)
            done += 1
            if progress:
                progress("tween", done / todo)
    out = ctx.assets_dir / f"{asset_id}.mp4"
    n = _encode(out, w, h, rate, pictures())
    keyed = ", ".join(f"{f}@{t:g}" for f, t in zip(frames, times))
    note = f"tween {keyed}; hold {hf:g}/{hl:g} s; {rate:g} fps"
    reg = register_asset(ctx, asset_id, {"path": rel(ctx, out), "kind": "video", "note": note,
                                         "width": w, "height": h})
    return (f"Tweened {asset_id!r}: {n} frames ({todo} made between {len(frames)} key pictures) at {w}x{h}, "
            f"{rate:g} fps, {n / rate:.2f} s, in {time.monotonic() - started:.1f} s -> {rel(ctx, out)}.{reg}"), False


# ------------------------------------------------------------------ parallax
def sample(img, x, y):
    """Bilinear lookup of img (HxW or HxWxC) at float pixel coordinates, clamped to the picture."""
    import numpy as np
    h, w = img.shape[:2]
    x = np.clip(x, 0, w - 1.0001)
    y = np.clip(y, 0, h - 1.0001)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    flat = img.reshape(h * w, -1)
    i = y0 * w + x0
    a, b = flat.take(i, axis=0), flat.take(i + 1, axis=0)
    c, d = flat.take(i + w, axis=0), flat.take(i + w + 1, axis=0)
    if img.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    else:
        a, b, c, d = a[..., 0], b[..., 0], c[..., 0], d[..., 0]
    top = a + (b - a) * fx
    return top + (c + (d - c) * fx - top) * fy


def _shifted_max(a, r: int, axis: int):
    import numpy as np
    out = a.copy()
    n = a.shape[axis]
    for k in range(1, r + 1):
        lo = [slice(None)] * 2
        hi = [slice(None)] * 2
        lo[axis], hi[axis] = slice(0, n - k), slice(k, n)
        np.maximum(out[tuple(lo)], a[tuple(hi)], out=out[tuple(lo)])
        np.maximum(out[tuple(hi)], a[tuple(lo)], out=out[tuple(hi)])
    return out


def _box(a, r: int, axis: int):
    import numpy as np
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    return ((np.take(c, np.arange(2 * r + 1, n + 2 * r + 1), axis=axis)
             - np.take(c, np.arange(0, n), axis=axis)) / (2 * r + 1)).astype(np.float32)


def soften(near, radius: int):
    """Grow the near side of every depth edge by `radius` and blur it: the stretch falls on the background, not on a
    foreground edge."""
    if radius < 1:
        return near
    grown = _shifted_max(_shifted_max(near, radius, 0), radius, 1)
    return _box(_box(grown, radius, 0), radius, 1)


def distance(near):
    return 1.0 / (1.0 / FAR_Z + (1.0 / NEAR_Z - 1.0 / FAR_Z) * near)


@dataclass
class Camera:
    w: int
    h: int
    dolly: float = 0.0
    truck: float = 0.0
    pedestal: float = 0.0

    @property
    def f(self) -> float:
        return float(max(self.w, self.h))       # about a 53 degree view across the long side

    def offset(self, p: float) -> tuple[float, float, float]:
        """(tx, ty, tz) at progress p: the nearest thing shifts truck/pedestal of the width at the end."""
        return (self.truck * self.w / self.f * p, -self.pedestal * self.w / self.f * p, self.dolly * NEAR_Z * p)

    def moved(self, u, v, z, p: float):
        """Where a pixel at (u, v) with distance z lands in the frame at progress p."""
        tx, ty, tz = self.offset(p)
        cx, cy, f = (self.w - 1) / 2, (self.h - 1) / 2, self.f
        k = z / (z - tz)
        return cx + (u - cx) * k - f * tx / (z - tz), cy + (v - cy) * k - f * ty / (z - tz)


def _edges(cam: Camera, z, steps=(0.25, 0.5, 0.75, 1.0)) -> tuple[float, float, float, float]:
    """How far inside the frame each side of the picture comes at worst: (left, top, right, bottom) pixels."""
    import numpy as np
    w, h = cam.w, cam.h
    ys, xs = np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32)
    left = right = top = bottom = 0.0
    for p in steps:
        u, _ = cam.moved(np.zeros(h, np.float32), ys, z[:, 0], p)
        left = max(left, float(u.max()))
        u, _ = cam.moved(np.full(h, w - 1, np.float32), ys, z[:, -1], p)
        right = max(right, float((w - 1 - u).max()))
        _, v = cam.moved(xs, np.zeros(w, np.float32), z[0], p)
        top = max(top, float(v.max()))
        _, v = cam.moved(xs, np.full(w, h - 1, np.float32), z[-1], p)
        bottom = max(bottom, float((h - 1 - v).max()))
    return left + 1, top + 1, right + 1, bottom + 1


def crop_for(cam: Camera, z) -> tuple[float, float, float]:
    """(x0, y0, scale): the fixed window of the picture the frame shows, inside every side the move uncovers."""
    l, t, r, b = _edges(cam, z)
    ww, wh = (cam.w - 1) - l - r, (cam.h - 1) - t - b
    if ww <= 0 or wh <= 0:
        return 0.0, 0.0, math.inf
    s = max((cam.w - 1) / ww, (cam.h - 1) / wh, 1.0)
    cw, ch = (cam.w - 1) / s, (cam.h - 1) / s
    return l + (ww - cw) / 2, t + (wh - ch) / 2, s


def gap_of(cam: Camera, z, reach: int = 12) -> float:
    """The widest strip the move uncovers behind an edge (the jump in shift across `reach` pixels), as a share of the
    width: what has to be filled from the background."""
    import numpy as np
    step = reach // 3
    zs = z[::step, ::step]
    vs, us = np.mgrid[0:cam.h:step, 0:cam.w:step].astype(np.float32)
    worst = 0.0
    for p in (0.5, 1.0):
        u1, v1 = cam.moved(us, vs, zs, p)
        du, dv = u1 - us, v1 - vs
        for a in (0, 1):
            jump = np.hypot(np.diff(du[:, ::3] if a else du[::3], axis=a),
                            np.diff(dv[:, ::3] if a else dv[::3], axis=a))
            worst = max(worst, float(jump.max()) if jump.size else 0.0)
    return worst / cam.w


def fill(values, weight):
    """Holes (weight 0) of each HxW array filled by weighted averages of the nearest known values (pull-push)."""
    import numpy as np
    levels = []
    wt, vs = weight.astype(np.float32), [v * weight for v in values]
    while min(wt.shape) > 1:
        levels.append((wt, vs))
        h, w = wt.shape
        pad = ((0, h % 2), (0, w % 2))
        down = (lambda a: np.pad(a, pad).reshape((h + h % 2) // 2, 2, (w + w % 2) // 2, 2).sum(axis=(1, 3)))
        wt, vs = down(wt), [down(v) for v in vs]
    est = [v / np.maximum(wt, 1e-12) for v in vs]
    for wt, vs in reversed(levels):
        h, w = wt.shape
        up = [np.repeat(np.repeat(e, 2, axis=0), 2, axis=1)[:h, :w] for e in est]
        known = wt > 0
        est = [np.where(known, v / np.maximum(wt, 1e-12), u) for v, u in zip(vs, up)]
    return est


class Warper:
    """One still's depth turned into frames: depth is forward-splatted with a z-buffer (the nearest wins), then each
    output pixel is looked up backwards with the depth found there; uncovered strips take the background beside
    them."""

    def __init__(self, img, z, cam: Camera, window: tuple[float, float, float]):
        import numpy as np
        self.img, self.cam, self.window = img, cam, window
        h, w = z.shape
        order = np.argsort(-z.ravel(), kind="stable")      # far first: nearer pixels are written last and win
        self.z = z.ravel()[order]
        self.u = (order % w).astype(np.float32)
        self.v = (order // w).astype(np.float32)
        vs, us = np.mgrid[0:h, 0:w].astype(np.float32)
        x0, y0, s = window
        self.qx, self.qy = x0 + us / s, y0 + vs / s

    def frame(self, p: float):
        import numpy as np
        cam, (x0, y0, s) = self.cam, self.window
        h, w = cam.h, cam.w
        tu, tv = cam.moved(self.u, self.v, self.z, p)
        ox, oy = (tu - x0) * s, (tv - y0) * s
        fx, fy = np.floor(ox).astype(np.int32), np.floor(oy).astype(np.int32)
        corners = []
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            cx_, cy_ = fx + dx, fy + dy
            inside = (cx_ >= 0) & (cx_ < w) & (cy_ >= 0) & (cy_ < h)
            corners.append(np.where(inside, cy_ * w + cx_, h * w))
        zbuf = np.full(h * w + 1, np.inf, dtype=np.float32)
        zbuf[np.stack(corners, axis=1).ravel()] = np.repeat(self.z, 4)     # sequential: the last (nearest) stays
        zt = zbuf[:-1].reshape(h, w)
        known = np.isfinite(zt)
        zk = np.where(known, zt, 1.0)
        tx, ty, tz = cam.offset(p)
        cx, cy, f = (w - 1) / 2, (h - 1) / 2, cam.f
        su = cx + ((self.qx - cx) * (zk - tz) + f * tx) / zk
        sv = cy + ((self.qy - cy) * (zk - tz) + f * ty) / zk
        if not known.all():
            weight = np.where(known, zk, 0.0) ** 4             # the far side of an edge is what was behind it
            fu, fv = fill([su, sv], weight)
            su, sv = np.where(known, su, fu), np.where(known, sv, fv)
        return sample(self.img, su, sv)


def _ease(p: float, ease: str) -> float:
    return p if ease == "linear" else 0.5 - 0.5 * math.cos(math.pi * p)


def _move_arg(move) -> tuple[dict, str]:
    if isinstance(move, str):
        import json
        try:
            move = json.loads(move)
        except ValueError:
            move = None
    if not isinstance(move, dict) or not ({"dolly", "truck", "pedestal"} & set(move)):
        raise ProviderError('move must be an object with dolly, truck and/or pedestal, e.g. {"dolly": 0.08, '
                            '"truck": 0.02}')
    extra = set(move) - {"dolly", "truck", "pedestal", "ease"}
    if extra:
        raise ProviderError(f"move takes dolly, truck, pedestal and ease, not {', '.join(sorted(extra))}")
    ease = move.get("ease", "in-out")
    if ease not in ("in-out", "linear"):
        raise ProviderError(f'move.ease must be "in-out" or "linear" (got {ease!r})')
    return {"dolly": _number(move.get("dolly", 0), "move.dolly", -0.3, 0.3),
            "truck": _number(move.get("truck", 0), "move.truck", -0.15, 0.15),
            "pedestal": _number(move.get("pedestal", 0), "move.pedestal", -0.15, 0.15)}, ease


def _depth(path: Path, estimate, img_full) -> tuple:
    """(nearness at the picture's own size, reused?): <asset>.depth.png beside the picture is kept for later calls."""
    import numpy as np
    from PIL import Image
    saved = path.with_name(path.stem + ".depth.png")
    h, w = img_full.shape[:2]
    if saved.is_file() and saved.stat().st_mtime >= path.stat().st_mtime:
        with Image.open(saved) as im:
            if im.size == (w, h):
                return np.asarray(im, dtype=np.float32) / 65535, True, saved
    near = np.clip(np.asarray(estimate(img_full), dtype=np.float32), 0, 1)
    if near.shape != (h, w):
        raise ProviderError(f"the depth estimate came back {near.shape[1]}x{near.shape[0]}, not {w}x{h}")
    q = (near * 65535 + 0.5).astype(np.uint16)
    tmp = _unique(saved.parent, saved.stem, ".part.png")
    try:
        Image.fromarray(q).save(tmp, format="PNG")
        os.replace(tmp, saved)
    except OSError:
        pass                # the saved depth is only a cache; another call may be reading it
    finally:
        tmp.unlink(missing_ok=True)
    # as saved: a retry that reuses the file decides exactly as this call did
    return q.astype(np.float32) / 65535, False, saved


def _fits(w: int, h: int, z, move: dict) -> tuple[float, tuple]:
    """(widest uncovered strip, crop window) of `move`, and whether both are within the limits."""
    cam = Camera(w, h, **move)
    gap = gap_of(cam, z)
    window = crop_for(cam, z) if gap <= MAX_GAP else (0.0, 0.0, math.inf)
    return gap, window


def _ok(fit) -> bool:
    return fit[0] <= MAX_GAP and fit[1][2] <= MAX_OVERSCAN


def _smaller(w: int, h: int, z, move: dict) -> tuple[float, dict]:
    """(k, move scaled by k): the largest scale that fits, with a margin, each value rounded toward zero to the
    thousandth and checked, so that following it once is accepted."""
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _ok(_fits(w, h, z, {n: v * mid for n, v in move.items()})) else (lo, mid)
    k = lo * 0.95
    while k >= 0.001:
        out = {n: math.trunc(v * k * 1000) / 1000 for n, v in move.items()}
        if any(out.values()) and _ok(_fits(w, h, z, out)):
            return k, out
        k *= 0.9
    return 0.0, {}


@safe_tool
def parallax(project, id, asset, seconds, move, fps=0, *, estimate_depth=None, progress=None):
    """(text, is_error): assets/<id>.mp4, a camera moving through image asset `asset` by its depth."""
    started = time.monotonic()
    _need("parallax", ("numpy",) if estimate_depth else ("numpy", "onnxruntime", "py7zr"))
    import numpy as np
    from PIL import Image
    ctx = context(project)
    asset_id = check_id(id)
    path = _image_asset(ctx, asset, "asset")
    secs = _number(seconds, "seconds", 0.5, MAX_CLIP_S)
    m, ease = _move_arg(move)
    if not any(m.values()):
        raise ProviderError("move is all zero: give dolly, truck or pedestal")
    check_replaceable(ctx, asset_id, "video")
    rate = _fps(ctx, fps)
    _still(path, asset, "asset", "parallax", "draw the picture on its full background without cutout, or use a "
           "Photo for the cut-out")
    with Image.open(path) as im:
        full = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
    fh, fw = full.shape[:2]
    w, h = _out_size(ctx, fw, fh)
    t0 = time.monotonic()
    near, reused, saved = _depth(path, estimate_depth or (lambda img: depth_anything(ctx.cache_dir)(img)), full)
    depth_s = time.monotonic() - t0
    img = _load(path, (w, h))
    near = np.asarray(Image.fromarray(near).resize((w, h), Image.BILINEAR), dtype=np.float32)
    z = distance(soften(near, max(1, round(w * EDGE_GROW)))).astype(np.float32)
    cam = Camera(w, h, **m)
    gap = gap_of(cam, z)
    window = crop_for(cam, z) if gap <= MAX_GAP else None
    if window is None or window[2] > MAX_OVERSCAN:
        if window is None:
            why = (f"this move uncovers strips {gap:.1%} of the width wide behind near edges; past {MAX_GAP:.0%} "
                   "the filled background smears visibly")
        else:
            over = "the whole picture" if math.isinf(window[2]) else f"{window[2] - 1:.0%}"
            why = (f"this move uncovers the picture's border: hiding it takes a {over} enlargement, at most "
                   f"{MAX_OVERSCAN - 1:.0%}")
        k, smaller = _smaller(w, h, z, m)
        if not smaller:
            raise ProviderError(f"{why}. No smaller version of this move fits this picture: try another direction")
        values = ", ".join(f"{name} {v:g}" for name, v in smaller.items() if v)
        raise ProviderError(f"{why}. Scale it by {max(math.floor(k * 100) / 100, 0.01):.2f} or less: {values}")
    n = max(2, round(secs * rate))
    ticks = []
    warp = Warper(img, z, cam, window)

    def pictures():
        for k in range(n):
            a = time.monotonic()
            yield warp.frame(_ease(k / (n - 1), ease))
            ticks.append(time.monotonic() - a)
            if progress:
                progress("parallax", (k + 1) / n)
    out = ctx.assets_dir / f"{asset_id}.mp4"
    made = _encode(out, w, h, rate, pictures())
    moves = ", ".join(f"{k} {v:g}" for k, v in m.items() if v)
    note = f"parallax of {asset}: {moves}, {ease}; {secs:g} s; {rate:g} fps"
    reg = register_asset(ctx, asset_id, {"path": rel(ctx, out), "kind": "video", "note": note,
                                         "width": w, "height": h})
    depth = f"depth reused from {rel(ctx, saved)}" if reused else f"depth estimated in {depth_s:.1f} s -> " \
                                                                  f"{rel(ctx, saved)}"
    grow = (window[2] - 1) * 100
    border = "the frame needed no enlargement to keep the border out of sight" if grow < 1e-6 else \
        f"the frame was enlarged {f'{grow:.0f}%' if grow >= 0.5 else 'under 1%'} so no border shows"
    return (f"Parallax {asset_id!r}: {made} frames at {w}x{h}, {rate:g} fps, {made / rate:.2f} s ({moves}); "
            f"{depth}; {sum(ticks) / max(len(ticks), 1):.2f} s a frame, {time.monotonic() - started:.1f} s in all; "
            f"strips the move uncovers behind near edges filled from the far side (at most {gap:.1%} of the "
            f"width); {border} -> {rel(ctx, out)}.{reg}"), False
