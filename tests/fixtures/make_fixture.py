"""Regenerates the binary files of the demo fixture project (stdlib only; ffmpeg for the tiny video).

    python tests/fixtures/make_fixture.py
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
import zlib
from pathlib import Path

DEMO = Path(__file__).resolve().parent / "demo"
RATE = 8000
LINES = [
    ("一杯十八块的奶茶，成本到底多少钱？", 0.00, 3.20),
    ("我们把账单拆开来算。", 3.42, 5.40),
    ("茶底加奶，大约两块五。", 5.62, 8.00),
    ("杯子、吸管和封口膜，差不多一块钱。", 8.22, 11.40),
    ("真正的大头，是房租和人工，占了六成。", 11.62, 15.00),
    ("所以算下来，一杯的毛利不到五块。", 15.22, 18.30),
    ("下次再嫌贵，想想这张账单。", 18.52, 21.00),
]
VOICE_S = 21.2


def png(path: Path, w: int, h: int, pixel) -> None:
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def photo(x: int, y: int) -> tuple[int, int, int]:
    # a warm diagonal gradient with soft bands, so zoom and pan show
    t = (x + y) / (270 + 480)
    band = 18 if (y // 40) % 2 else 0
    return int(60 + 150 * t) + band // 2, int(40 + 90 * t), int(90 + 60 * (1 - t)) + band


def page(x: int, y: int) -> tuple[int, int, int]:
    # a white page with grey "text lines"; the proving sentence (y 420-470) is darker
    margin = 40 <= x < 500
    if 420 <= y < 470 and margin:
        return (40, 40, 48) if (y - 420) % 25 < 16 and (x // 9) % 7 else (255, 255, 255)
    if margin and (y - 60) % 50 < 18 and y > 60 and (x // 9) % 6:
        return (170, 170, 175)
    return (255, 255, 255)


def tone(path: Path, seconds: float, spans: list[tuple[float, float]], freq: float, amp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * RATE)
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        on = any(a <= t < b for a, b in spans)
        v = amp * math.sin(2 * math.pi * freq * t) if on else 0.0
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


def video(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is needed for the tiny video")
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=180x320:r=30:d=2", "-c:v", "libx264", "-crf", "32", "-pix_fmt", "yuv420p", "-an",
                    str(path)], check=True)


def main() -> None:
    png(DEMO / "assets" / "photo.png", 270, 480, photo)
    png(DEMO / "assets" / "evidence.png", 540, 900, page)
    video(DEMO / "assets" / "clip.mp4")
    tone(DEMO / "assets" / "bed.wav", 2.0, [(0.0, 2.0)], 220.0, 0.2)
    tone(DEMO / "voice" / "voice.wav", VOICE_S, [(a, b) for _, a, b in LINES], 330.0, 0.3)
    voice = {"file": "voice/voice.wav", "duration_s": VOICE_S,
             "lines": [{"i": n, "text": text, "t0": a, "t1": b} for n, (text, a, b) in enumerate(LINES, 1)]}
    (DEMO / "voice" / "voice.json").write_text(json.dumps(voice, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")


if __name__ == "__main__":
    main()
