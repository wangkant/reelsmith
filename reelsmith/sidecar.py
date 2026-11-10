"""A delivery's side files: every captions track as SubRip (.srt) and WebVTT (.vtt) in out/captions/, the
project's chapters as YouTube description lines (out/chapters.txt) and as mp4 chapter marks (ffmpeg metadata), the
profile's covers (out/<name>.png, frame 0 cut to each crop) and a platform project's handover.md skeleton."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import document as D
from . import media
from . import timeexpr as T
from .workspace import PROJECT_FILE, locale_for, project_root

YOUTUBE_MIN_CHAPTERS = 3
YOUTUBE_MIN_CHAPTER_S = 10
HANDOVER_FILE = "handover.md"
TODO = "TODO:"
_AI = "AI-generated content: yes or no, and what was generated (voice, pictures, clips, music)"
# Each playbook's "Hand over" bullet as headings, one line saying what goes there; the playbook stays the authority.
HANDOVER = {
    "douyin": [("Title", "as meta.title, or the post's title if it differs"),
               ("Description and #话题", "as meta.desc: 1-3 sentences, 3-5 #话题, no links"),
               ("Declarations", f"{_AI}; fiction; time and place or source"),
               ("Cover", "out/cover.png is frame 0 cut 3:4; say what it shows"),
               ("合集", "the collection and episode, or none for a one-off"),
               ("Pinned comment", "the comment to pin"),
               ("Domain", "finance, medical, legal, or none")],
    "bilibili": [("Title", "as meta.title (< 80 characters)"),
                 ("简介, tags and 分区", "简介 as meta.desc (< 250 characters); tags (>= 1, < 200 characters in all); "
                                      "the 分区"),
                 ("Declarations", f"自制 or 转载 with its source; the 创作者声明 to tick; {_AI}"),
                 ("Cover", "out/cover.png (16:9) and out/cover-4x3.png are frame 0; say what they show"),
                 ("Pinned comment", "the 置顶评论, with the sources"),
                 ("Chapters", "out/chapters.txt, or none under about 5 min")],
    "youtube": [("Title", "as meta.title (<= 100 characters)"),
                ("Description and tags", "as meta.desc (<= 5 000 bytes); the tags"),
                ("Declarations", "\"AI use\" yes or no and why; madeForKids; music and footage licences"),
                ("Cover", "long-form: out/cover.png (frame 0) or a designed thumbnail; Shorts: the cover frame's time"),
                ("Chapters", "out/chapters.txt, or none"),
                ("End screen and mid-rolls", "the end-screen start and the mid-roll points, or none")],
    "tiktok": [("Title", "as meta.title: the caption's first line"),
               ("Description and hashtags", "as meta.desc (<= 2 200 characters), 3-5 specific hashtags"),
               ("Declarations", "AI label yes or no and why; branded or self-promotional content; C2PA metadata "
                                "present or not; music source and licence, or none"),
               ("Cover", "the cover frame's time (default 0 s)")],
    "reels": [("Title", "as meta.title: the opening line"),
              ("Description and hashtags", "as meta.desc (<= 2 200 characters, <= 5 hashtags)"),
              ("Declarations", "AI disclosure yes or no and why; C2PA metadata present or not; music source and "
                               "licence, or none"),
              ("Cover", "out/cover.png (9:16) and out/cover-3x4.png (the grid's crop) are frame 0; say what they "
                        "show")],
    "xiaohongshu": [("Title", "as meta.title (<= 20 characters)"),
                    ("Description and #话题", "as meta.desc: 100-500 characters with the steps, 3-8 #话题"),
                    ("Declarations", f"{_AI}; 声明原创 only if every asset is owned; a finance risk line, or none; "
                                     "the music source"),
                    ("Cover", "out/cover.png is frame 0 cut 3:4 (1080x1440); say what it shows"),
                    ("合集", "the collection and episode, or none")],
    "channels": [("Title", "as meta.title: the 短标题, 6-50 characters"),
                 ("Description and #话题", "as meta.desc (<= 1 000 characters, inline #话题)"),
                 ("Declarations", f"{_AI}; 声明原创 only if every asset is owned; 风险提示 for money topics, or none; "
                                  "the music source or \"use the in-app library\""),
                 ("Cover", "out/cover.png (9:16) and out/cover-3x4.png (the grid's crop) are frame 0; say what they "
                           "show"),
                 ("合集", "the collection and episode, or none")],
}


# ------------------------------------------------------------------ handover.md
def handover_skeleton(book: str, title: str = "") -> str:
    """handover.md for a film on the playbook `book`: its "Hand over" items as headings, each with a TODO line."""
    head = f"# Handover{': ' + title if title else ''}\n\nWhat docs/platforms/{book}.md asks to hand over besides " \
           f"the film and meta.title, meta.desc and meta.sources. Replace every {TODO} line.\n"
    return head + "".join(f"\n## {h}\n\n{TODO} {line}\n" for h, line in HANDOVER[book])


def handover_todo(project) -> int:
    """TODO lines left in the project's handover.md (0 when it has none or there is no file)."""
    path = project_root(project) / HANDOVER_FILE
    if not path.is_file():
        return 0
    return sum(ln.lstrip().startswith(TODO) for ln in path.read_text(encoding="utf-8-sig").splitlines())


# ------------------------------------------------------------------ covers
def write_covers(film: Path, profile, folder: Path) -> list[dict]:
    """out/<name>.png for each of the profile's covers: frame 0 of `film` cut to its crop (old covers removed)."""
    for old in folder.glob("cover*.png"):
        old.unlink()
    out = []
    for c in profile.cover:
        w, h, x, y = c.crop
        png = folder / f"{c.name}.png"
        crop = [] if c.crop == (profile.width, profile.height, 0, 0) else ["-vf", f"crop={w}:{h}:{x}:{y}"]
        r = media.run([media._exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(film),
                       "-frames:v", "1", *crop, str(png)], 120)
        if r.returncode != 0 or not png.is_file():
            raise RuntimeError(f"ffmpeg could not cut {png.name} from {Path(film).name}: "
                               f"{media.tail(r.stderr or '', 5, 300)}")
        out.append({"name": c.name, "png": str(png), "crop": list(c.crop),
                    "label": c.label(profile.width, profile.height)})
    return out


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
