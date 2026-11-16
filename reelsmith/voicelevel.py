"""The narration's loudness a frame at a time (0..1), for mouths that open on the voice."""
from __future__ import annotations

import array
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

RATE = 16000
REF_PERCENTILE = 0.95           # loudest stretches reach 1; one shout does not flatten the rest
NOISE_FLOOR = 64                # RMS of 16-bit samples, about -54 dBFS: under it a frame is silence
CACHE_VERSION = 2


def envelope(samples, rate: int, fps: float) -> list[float]:
    """RMS of each frame's window of 16-bit samples, scaled so the REF_PERCENTILE frame of those above the noise
    floor is 1, clipped to 0..1."""
    n = len(samples)
    if n == 0 or fps <= 0:
        return []
    per = rate / fps
    frames = max(1, math.ceil(n / per))
    rms = []
    for k in range(frames):
        a, b = int(round(k * per)), min(n, int(round((k + 1) * per)))
        chunk = samples[a:b]
        rms.append(math.sqrt(sum(x * x for x in chunk) / len(chunk)) if len(chunk) else 0.0)
    # only frames with voice in them: a short line in a long silent file still reaches 1
    loud = sorted(v for v in rms if v > NOISE_FLOOR)
    if not loud:
        return [0.0] * frames
    ref = loud[min(len(loud) - 1, int(REF_PERCENTILE * len(loud)))]
    return [round(min(1.0, v / ref), 3) for v in rms]


def decode(path: Path, rate: int = RATE) -> array.array:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not on PATH")
    out = subprocess.run([exe, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg could not read {path.name}: {out.stderr.decode('utf-8', 'replace')[-300:]}")
    data = array.array("h")
    data.frombytes(out.stdout[: len(out.stdout) // 2 * 2])
    if sys.byteorder == "big":
        data.byteswap()
    return data


def voice_level(audio: Path, fps: float, cache_dir: Path | None = None) -> list[float]:
    """The envelope of `audio` at `fps`, cached under cache_dir by the file's size and modification time."""
    st = audio.stat()
    stamp = {"v": CACHE_VERSION, "file": audio.name, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "fps": fps}
    cache = cache_dir / "voice-level.json" if cache_dir else None
    if cache and cache.is_file():
        try:
            held = json.loads(cache.read_text(encoding="utf-8"))
            if held.get("stamp") == stamp:
                return list(held["level"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    level = envelope(decode(audio), RATE, fps)
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            part = cache.with_name(f".{cache.stem}.{uuid.uuid4().hex[:6]}.part")
            part.write_text(json.dumps({"stamp": stamp, "level": level}), encoding="utf-8")
            os.replace(part, cache)
        except OSError:
            pass                 # a cache that cannot be written only costs a decode next time
    return level
