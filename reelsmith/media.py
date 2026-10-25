"""ffmpeg/ffprobe helpers: probe, loudness, mastering, black/freeze scan, contact sheets, frames; process trees."""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path

BLACK_FILTER = "blackdetect=d=0.2:pic_th=0.98:pix_th=0.05"  # 0.10 calls the night ground (#16130F, luma ~33) black
FREEZE_FILTER = "freezedetect=n=-60dB:d=2"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROGRESS = re.compile(r"^(Rendered|Encoded|Bundling|Getting composition|Copying public dir|render)\b.*\d+(/\d+|%)")
_LIVE: set[subprocess.Popen] = set()
_LIVE_LOCK = threading.Lock()
_JOB = None


def _exe(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise RuntimeError(f"{name} is not on PATH")
    return exe


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def kill_tree(proc: subprocess.Popen) -> None:
    # node leaves headless Chrome behind: killing only the parent keeps it (and the pipes) alive
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)         # its own session: the whole group
        except OSError:
            proc.kill()


def _windows_job():
    """A job object that kills every process in it when this process exits, however it exits (Windows)."""
    global _JOB
    if _JOB is not None or os.name != "nt":
        return _JOB
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        _JOB = (k32, wintypes.HANDLE(job))
    except (OSError, AttributeError, ValueError):
        return None
    return _JOB


def _adopt(proc: subprocess.Popen) -> None:
    job = _windows_job()
    if job:
        k32, handle = job
        import ctypes
        k32.AssignProcessToJobObject(handle, ctypes.c_void_p(int(proc._handle)))  # noqa: SLF001
    with _LIVE_LOCK:
        _LIVE.add(proc)


def _release(proc: subprocess.Popen) -> None:
    with _LIVE_LOCK:
        _LIVE.discard(proc)


@atexit.register
def kill_live_trees() -> None:
    """Every process tree run_tree started and still running (an MCP server that exits mid-render)."""
    with _LIVE_LOCK:
        live = list(_LIVE)
    for proc in live:
        if proc.poll() is None:
            kill_tree(proc)


def run_tree(cmd: list, cwd: str | Path | None = None, env: dict | None = None,
             timeout: float = 600) -> tuple[int, str, str, bool]:
    """(returncode, stdout, stderr, timed_out) of a fixed argument list. A timeout, an interrupt (KeyboardInterrupt,
    SystemExit) or this process exiting kills the whole process tree, so no node or browser is left behind."""
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW, start_new_session=os.name != "nt")
    _adopt(proc)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    except BaseException:
        kill_tree(proc)
        raise
    finally:
        _release(proc)
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), timed_out


def tail(text: str, lines: int = 40, chars: int = 3500) -> str:
    """The end of a log without colour codes and progress counters (they say nothing about what broke)."""
    rows = [r.rstrip() for r in _ANSI.sub("", text or "").replace("\r", "\n").splitlines() if r.strip()]
    rows = [r for r in rows if not _PROGRESS.match(r)]
    return "\n".join(rows[-lines:])[-chars:]


def frame_rate(text: str | None) -> float:
    """ffprobe's "30000/1001" as a number; 0.0 when unreadable."""
    try:
        num, _, den = str(text or "").partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> dict:
    r = run([_exe("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], 120)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe: {(r.stderr or '').strip()[-200:]}")
    return json.loads(r.stdout or "{}")


def duration(path: Path) -> float | None:
    try:
        return float(probe(path).get("format", {}).get("duration") or 0) or None
    except (RuntimeError, ValueError):
        return None


def scaled_timeout(length_s: float, floor: float = 600, per_s: float = 1.0) -> float:
    """A timeout for an ffmpeg pass over `length_s` seconds of film: `floor`, or longer for a long film."""
    return max(floor, per_s * max(0.0, float(length_s or 0)))


def loudness(path: Path, timeout: float = 600) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBFS) of the whole file; None where it cannot be measured."""
    r = run([_exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true",
             "-f", "null", "-"], timeout)
    err = r.stderr or ""
    i = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err)
    p = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err)
    return (float(i[-1]) if i and i[-1] != "-inf" else None, float(p[-1]) if p and p[-1] != "-inf" else None)


class SilentAudio(RuntimeError):
    """The mix has an audio stream with nothing in it."""


def master(src: Path, dst: Path, lufs: float, peak: float = -1.0, timeout: float = 600) -> None:
    """Two-pass loudnorm of the whole mix to `lufs`; the picture is copied."""
    target = f"loudnorm=I={lufs}:TP={peak}:LRA=11"
    first = run([_exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af",
                 f"{target}:print_format=json", "-f", "null", "-"], timeout)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", first.stderr or "")
    if first.returncode != 0 or not m:
        raise RuntimeError(f"loudness measure failed: {tail(first.stderr or '', 5, 300)}")
    s = json.loads(m.group(0))
    if s.get("input_i") in ("-inf", None):
        raise SilentAudio("the audio is silent: nothing to master (is the narration missing?)")
    measured = (f"measured_I={s['input_i']}:measured_TP={s['input_tp']}:measured_LRA={s['input_lra']}:"
                f"measured_thresh={s['input_thresh']}:offset={s['target_offset']}:linear=true")
    r = run([_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-map",
             "0:a:0", "-c:v", "copy", "-af", f"{target}:{measured}", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(dst)], timeout)
    if r.returncode != 0 or not Path(dst).is_file() or Path(dst).stat().st_size == 0:
        raise RuntimeError(f"mastering failed: {tail(r.stderr or '', 5, 300)}")


def add_chapters(path: Path, meta: str, timeout: float = 600) -> None:
    """Chapter marks (the text of an ffmpeg metadata file) into an mp4, in place; the streams are copied."""
    path = Path(path)
    meta_file, tmp = path.with_name(path.name + ".chapters.txt"), path.with_name(path.name + ".chapters.mp4")
    meta_file.write_text(meta, encoding="utf-8", newline="\n")
    try:
        r = run([_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "ffmetadata",
                 "-i", str(meta_file), "-map", "0", "-map_metadata", "0", "-map_chapters", "1", "-c", "copy",
                 "-movflags", "+faststart", str(tmp)], timeout)
        if r.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError(f"ffmpeg: {tail(r.stderr or '', 3, 300) or 'no output'}")
        os.replace(tmp, path)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg ran over {timeout:.0f} s") from None
    finally:
        meta_file.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


def scan(path: Path, length: float) -> dict:
    """Seconds of near-black and the longest stretch without any change, from one decode."""
    r = run([_exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-an",
             "-vf", f"{BLACK_FILTER},{FREEZE_FILTER}", "-f", "null", "-"], scaled_timeout(length, 900))
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode the film: {tail(r.stderr or '', 5, 300)}")
    err = r.stderr or ""
    black = sum(float(x) for x in re.findall(r"black_duration:\s*([\d.]+)", err))
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", err)]
    lens = [float(x) for x in re.findall(r"freeze_duration:\s*([\d.]+)", err)]
    if len(starts) > len(lens):         # still frozen at the end: ffmpeg prints no end for it
        lens.append(max(0.0, length - starts[-1]))
    return {"black_s": round(black, 2), "black_ratio": round(black / length, 3) if length else 0.0,
            "longest_still_s": round(max(lens, default=0.0), 2)}


def _label_tiles(sheet: Path, labels: list[str], cols: int, tile: tuple[int, int]) -> None:
    """Each tile's label (its time) in its top-left corner, on a dark chip."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    try:
        font = ImageFont.load_default(size=max(14, tile[1] // 22))
    except TypeError:                               # Pillow before 10.1: fixed bitmap font
        font = ImageFont.load_default()
    with Image.open(sheet) as im:
        im = im.convert("RGB")
        draw = ImageDraw.Draw(im)
        for i, text in enumerate(labels):
            if not text:
                continue
            x, y = (i % cols) * tile[0] + 6, (i // cols) * tile[1] + 6
            l, t, r, b = draw.textbbox((x + 5, y + 3), text, font=font)
            draw.rectangle((x, y, r + 5, b + 4), fill=(0, 0, 0))
            draw.text((x + 5, y + 3), text, fill=(255, 255, 255), font=font)
        im.save(sheet)


def contact_sheet(pngs: list[Path], out: Path, ui_boxes: list[tuple[int, int, int, int]], frame=(1080, 1920),
                  tile=(270, 480), outline: tuple[int, int, int, int] | None = None,
                  labels: list[str] | None = None, cols: int = 6) -> Path | None:
    """All pictures in one PNG at a glance size, `ui_boxes` (frame pixels) darkened on each and `outline` (the safe
    area) traced, so the boundary shows on dark frames too; `labels` (e.g. times) mark the tiles; up to `cols` a
    row."""
    pngs = [Path(p) for p in pngs]
    if not pngs:
        return None
    w, h = tile
    fw, fh = frame
    cols = max(1, min(cols, len(pngs)))
    ui = "".join(f"drawbox=x={x}*iw/{fw}:y={y}*ih/{fh}:w={bw}*iw/{fw}:h={bh}*ih/{fh}:color=black@0.55:t=fill,"
                 for x, y, bw, bh in ui_boxes)
    if outline:
        x, y, bw, bh = outline
        ui += f"drawbox=x={x}*iw/{fw}:y={y}*ih/{fh}:w={bw}*iw/{fw}:h={bh}*ih/{fh}:color=0xFFD34D@0.7:t=4,"
    scale = [f"[{i}:v]{ui}scale={w - 8}:{h - 8}:force_original_aspect_ratio=decrease,"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x6e6e6e[s{i}]" for i in range(len(pngs))]
    if len(pngs) == 1:
        graph = scale[0].replace("[s0]", "[out]")
    else:
        layout = "|".join(f"{(i % cols) * w}_{(i // cols) * h}" for i in range(len(pngs)))
        graph = ";".join(scale) + ";" + "".join(f"[s{i}]" for i in range(len(pngs))) + \
            f"xstack=inputs={len(pngs)}:layout={layout}:fill=0x6e6e6e[out]"
    cmd = [_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error"]
    for p in pngs:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", str(out)]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    r = run(cmd, 120)
    if r.returncode != 0 or not Path(out).is_file():
        return None
    if labels:
        _label_tiles(Path(out), labels, cols, tile)
    return Path(out)


def frames_at(video: Path, times: list[float], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for t in times:
        f = out_dir / f"frame_{t:07.2f}s.png"
        r = run([_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
                 "-frames:v", "1", str(f)], 120)
        if r.returncode == 0 and f.is_file():
            files.append(f)
    return files
