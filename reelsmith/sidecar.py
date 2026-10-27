"""A delivery's side files: every captions track as SubRip (.srt) and WebVTT (.vtt) in out/captions/, and the
project's chapters as YouTube description lines (out/chapters.txt) and as mp4 chapter marks (ffmpeg metadata)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import document as D
from . import timeexpr as T
from .workspace import PROJECT_FILE, locale_for, project_root

YOUTUBE_MIN_CHAPTERS = 3
YOUTUBE_MIN_CHAPTER_S = 10


# ------------------------------------------------------------------ captions
def _text(item: dict) -> str:
    return " ".join("".join(str(r.get("text") or "") for r in item.get("runs") or []).split())


def stamp(seconds: float, sep: str = ",") -> str:
    """HH:MM:SS,mmm (SubRip) or with "." (WebVTT)."""
    ms = max(0, round(seconds * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def cues(track: dict, fps: float, frames: int) -> list[tuple[float, float, str]]:
    """(start, end, text) of a resolved captions track's items, inside the film, accents dropped."""
    out = []
    for it in track.get("items") or []:
        a, b, text = max(0, int(it.get("from") or 0)), min(frames, int(it.get("to") or 0)), _text(it)
        if b > a and text:
            out.append((a / fps, b / fps, text))
    return out


def srt(rows: list[tuple[float, float, str]]) -> str:
    return "".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n" for n, (a, b, text) in enumerate(rows, 1))


def vtt(rows: list[tuple[float, float, str]], language: str | None = None) -> str:
    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    head = "WEBVTT\n" + (f"Language: {language}\n" if language else "") + "\n"
    return head + "".join(f"{stamp(a, '.')} --> {stamp(b, '.')}\n{esc(text)}\n\n" for a, b, text in rows)


def _languages(root: Path) -> dict[str, str]:
    data = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8-sig"))
    return {t["id"]: t["language"] for t in data.get("tracks") or [] if t.get("language")}


def write_captions(project, resolved: dict, folder: Path, only: str | None = None) -> list[dict]:
    """out/captions/<track>.srt and .vtt for every captions track (hidden ones too: a hidden track is a sidecar-only
    language), or the one named; the folder is emptied first when all are written. One row per track."""
    root = project_root(project)
    fps = float(resolved.get("fps") or 30)
    frames = int(resolved.get("durationInFrames") or 0)
    tracks = [t for t in resolved.get("tracks") or [] if t.get("kind") == "captions"]
    if only:
        tracks = [t for t in tracks if t.get("id") == only]
    elif folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    if not tracks:
        return []
    default = locale_for(root)
    langs = _languages(root)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for t in tracks:
        rows = cues(t, fps, frames)
        lang = langs.get(t["id"]) or default
        files = {"srt": folder / f"{t['id']}.srt", "vtt": folder / f"{t['id']}.vtt"}
        files["srt"].write_text(srt(rows), encoding="utf-8", newline="\n")
        files["vtt"].write_text(vtt(rows, lang), encoding="utf-8", newline="\n")
        out.append({"track": t["id"], "language": lang, "hidden": bool(t.get("hidden")), "cues": len(rows),
                    "srt": str(files["srt"]), "vtt": str(files["vtt"])})
    return out


# ------------------------------------------------------------------ chapters
def chapters(project, fps: float) -> list[tuple[float, str]]:
    """(seconds on a frame, title) of project.json "chapters", in time order."""
    root = project_root(project)
    doc = D.load(root)
    if not doc.chapters:
        return []
    voice, _ = D.load_voice(root, doc.voice)
    sched = D.schedule(doc, voice)
    out = []
    for ch in doc.chapters:
        t = T.resolve(ch.at, sched)
        out.append((T.to_frame(t, fps) / fps, " ".join(ch.title.split())))
    return sorted(out, key=lambda x: x[0])


def _clock(seconds: float, hours: bool) -> str:
    s = int(seconds)                    # a chapter starts on its whole second or before it, never after
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if hours else f"{m}:{s:02d}"


def youtube(rows: list[tuple[float, str]], duration: float) -> tuple[str, list[str]]:
    """The description lines ("0:00 Intro") and what keeps YouTube from showing them as chapters."""
    hours = duration >= 3600
    text = "".join(f"{_clock(t, hours)} {title}\n" for t, title in rows)
    notes = []
    if rows and int(rows[0][0]) != 0:
        notes.append("the first chapter does not start at 0:00")
    if len(rows) < YOUTUBE_MIN_CHAPTERS:
        notes.append(f"fewer than {YOUTUBE_MIN_CHAPTERS} chapters")
    ends = [t for t, _ in rows[1:]] + [duration]
    short = [title for (t, title), end in zip(rows, ends) if end - t < YOUTUBE_MIN_CHAPTER_S]
    if short:
        notes.append(f"chapters under {YOUTUBE_MIN_CHAPTER_S} s: {', '.join(short[:5])}")
    return text, notes


def ffmetadata(rows: list[tuple[float, str]], duration: float) -> str:
    """ffmpeg's metadata file with one [CHAPTER] per row (milliseconds), for -map_chapters."""
    def esc(t: str) -> str:
        return "".join("\\" + ch if ch in "=;#\\\n" else ch for ch in t)
    ends = [t for t, _ in rows[1:]] + [duration]
    body = "".join(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(t * 1000)}\nEND={max(round(t * 1000) + 1, round(e * 1000))}\n"
                   f"title={esc(title)}\n" for (t, title), e in zip(rows, ends))
    return ";FFMETADATA1\n" + body
