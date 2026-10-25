"""import_asset: a local file or an http(s) download (image, video, audio, evidence) copied into assets/ and
registered; assets: what the project holds.

Only media the project format takes gets in: the bytes are sniffed (and video/audio probed) whatever the name or the
server says, the size is capped, and a download goes only to public http(s) hosts, every redirect hop included.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .. import netcheck
from ..workspace import project_file
from .config import (Context, ProviderError, check_id, check_replaceable, context, header_size, number, probe,
                     read_project, register_asset, rel, safe_tool)

KINDS = ("image", "video", "audio")
CHUNK = 1 << 16
TIMEOUT_S = 60
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
MEDIA_TYPES = ("image/", "video/", "audio/")
GENERIC_TYPES = ("application/octet-stream", "binary/octet-stream", "application/mp4", "application/ogg", "")
FORMATS = "PNG, JPEG, GIF, WebP, MP4, MOV, WebM, MKV, MP3, WAV, M4A, AAC, OGG, Opus, FLAC"
# what project.json validation takes per kind (reelsmith.document.EXTENSIONS; this copy only when it cannot load)
_EXTENSIONS = {"image": {".png", ".jpg", ".jpeg", ".webp", ".gif"}, "evidence": {".png", ".jpg", ".jpeg", ".webp"},
               "video": {".mp4", ".m4v", ".mov", ".webm", ".mkv"},
               "audio": {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac"}}
EVIDENCE_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")
_URL_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]+):")     # 2+ letters: "C:" is a drive, not a scheme


# ------------------------------------------------------------------ sniffing
def sniff(head: bytes) -> tuple[str, str] | None:
    """(kind, extension) from a file's first bytes; None when it is not media we take.
    kind "av" means video or audio: ffprobe decides."""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", ".png"
    if head[:3] == b"\xff\xd8\xff":
        return "image", ".jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", ".gif"
    if head[:4] == b"RIFF":
        return {b"WEBP": ("image", ".webp"), b"WAVE": ("audio", ".wav"), b"AVI ": ("video", ".avi")}.get(head[8:12])
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "image", ".avif"
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
            return None                              # browsers cannot show HEIC
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio", ".m4a"
        return "av", ".mov" if brand == b"qt  " else ".mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "av", ".webm" if b"webm" in head[:64] else ".mkv"
    if head[:4] == b"OggS":
        return "av", ".ogg"
    if head[:4] == b"fLaC":
        return "audio", ".flac"
    if head[:3] == b"ID3":
        return "audio", ".mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "audio", ".aac"                       # ADTS
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        return "audio", ".mp3"                       # MPEG audio frame sync
    return None


def _streams(path: Path) -> tuple[bool, bool, float | None]:
    """(has video, has audio, duration) by ffprobe; ProviderError when it cannot read the file."""
    info = probe(path)
    kinds = {s.get("codec_type") for s in info.get("streams") or []
             if not (s.get("disposition") or {}).get("attached_pic")}
    try:
        dur = float((info.get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError):
        dur = None
    return "video" in kinds, "audio" in kinds, dur


def classify(path: Path) -> tuple[str, str, str]:
    """(kind, extension, facts) of a downloaded or copied file, or ProviderError."""
    with open(path, "rb") as fh:
        head = fh.read(64)
    found = sniff(head)
    if not found:
        raise ProviderError(f"not an image, video or audio file this platform takes ({FORMATS})")
    kind, ext = found
    if kind == "image":
        size = header_size(path)
        return kind, ext, f"{size[0]}x{size[1]}" if size else ""
    if not shutil.which("ffprobe"):
        if kind == "av":
            kind = "audio" if ext == ".ogg" else "video"
        return kind, ext, ""
    try:
        video, audio, dur = _streams(path)
    except ProviderError:
        raise ProviderError("the file looks like media but ffprobe cannot read it (damaged or cut off)") from None
    if kind in ("video", "av") and video:
        kind = "video"
    elif kind in ("audio", "av") and audio and not video:
        kind = "audio"
    else:
        raise ProviderError(f"the file has no {'video' if kind == 'video' else 'playable'} stream")
    if kind == "audio" and ext in (".mp4", ".mov", ".mkv"):
        ext = ".m4a" if ext != ".mkv" else ".mka"
    return kind, ext, f"{dur:.2f} s" if dur else ""


def accepted(kind: str) -> set[str]:
    """File extensions an asset of `kind` may have."""
    try:
        table = importlib.import_module("reelsmith.document").EXTENSIONS
    except Exception:  # noqa: BLE001 — a half-written neighbour must not take the tool down
        table = _EXTENSIONS
    return set(table.get(kind) or _EXTENSIONS.get(kind) or ())


def _type_refusal(kind: str, ext: str) -> str:
    """'' when an `ext` file can be a `kind` asset, else what to do about it."""
    allowed = accepted(kind)
    if ext in allowed:
        return ""
    names = ", ".join(sorted({e.lstrip(".").upper().replace("JPEG", "JPG") for e in allowed}))
    return f"{ext.lstrip('.').upper()} files cannot be {kind} assets (they take {names}); convert it first"


# ------------------------------------------------------------------ fetching
class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Every hop is checked like the first address: http(s) to a public host only."""

    def __init__(self, resolve=None, trusted=()):
        super().__init__()
        self.resolve, self.trusted = resolve, trusted

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = netcheck.public_url(newurl, self.resolve, self.trusted)
        if why:
            raise ProviderError(f"the download redirected to {newurl[:100]}, which is refused: {why}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HttpOnlyRedirect = _SafeRedirect           # the old name


def _default_opener(resolve=None, trusted=()):
    return urllib.request.build_opener(_SafeRedirect(resolve, trusted)).open


def _copy_capped(read, dst: Path, cap: int) -> int:
    total = 0
    with open(dst, "wb") as fh:
        while True:
            chunk = read(CHUNK)
            if not chunk:
                return total
            total += len(chunk)
            if total > cap:
                raise ProviderError(f"the file is over the {cap // (1 << 20)} MB import limit "
                                    "(providers.import.max_mb)")
            fh.write(chunk)


def download(url: str, dst: Path, cap: int, opener=None, *, resolve=None, trusted=(), evidence: bool = False) -> str:
    """Fetch url into dst under the cap; the final URL. url and every redirect hop must be public http(s)."""
    if resolve is None and opener is None:
        resolve = netcheck.env_resolver(url)      # urllib sends it through the environment's proxy, if any
    why = netcheck.public_url(url, resolve, trusted)
    if why:
        raise ProviderError(f"cannot import {url[:120]}: {why}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,video/*,audio/*,*/*;q=0.5"})
    try:
        resp = (opener or _default_opener(resolve, trusted))(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"the download answered HTTP {exc.code}; check the address") from None
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {urllib.parse.urlsplit(url).hostname}: {exc.reason}") from None
    with resp:
        final = resp.geturl() if hasattr(resp, "geturl") else url
        ctype = str(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not (ctype.startswith(MEDIA_TYPES) or ctype in GENERIC_TYPES):
            hint = " Use capture for a web page, or find the file's direct address." if "html" in ctype else ""
            raise ProviderError(f"that address serves {ctype}, not an image, video or audio file.{hint}")
        if evidence and ctype.startswith("image/") and ctype not in EVIDENCE_TYPES:
            raise ProviderError(f"that address serves {ctype}; evidence must be a PNG, JPG or WebP picture")
        length = resp.headers.get("Content-Length")
        if length and str(length).isdigit() and int(length) > cap:
            raise ProviderError(f"the file is {int(length) / (1 << 20):.0f} MB, over the {cap // (1 << 20)} MB "
                                "import limit (providers.import.max_mb)")
        _copy_capped(resp.read, dst, cap)
    return final


def _local_source(ctx: Context, source: str) -> Path:
    p = Path(source).expanduser()
    p = (p if p.is_absolute() else ctx.project / p).resolve()
    # the same fence tools._project puts around projects: a confined agent cannot pull files from elsewhere
    fence = os.environ.get("REELSMITH_ROOT")
    if fence:
        base = Path(fence).expanduser().resolve()
        if p != base and base not in p.parents:
            raise ProviderError(f"{p} is outside {base}; only files inside it can be imported (or give an http(s) "
                                "URL)")
    if not p.is_file():
        raise ProviderError(f"no file at {p}; give an existing file path or an http(s) URL")
    return p


# ------------------------------------------------------------------ tools
@safe_tool
def import_asset(project, id, source, kind=None, *, opener=None, resolve=None):
    """(text, is_error): copy a local file, or download one from a public http(s) address, into assets/ and register
    it as asset `id`.

    kind: "image", "video", "audio" or "evidence" (a screenshot that proves something: PNG, JPG or WebP only; its box
    starts as the whole picture); left out, it is detected from the file. Files the project format cannot use (e.g.
    AVIF, AVI, a GIF as evidence) are refused with what to convert them to."""
    ctx = context(project)
    asset_id = check_id(id)
    if kind not in (None, "") and kind not in (*KINDS, "evidence"):
        return f"kind must be one of {', '.join(KINDS)}, evidence (or left out to detect it); got {kind!r}", True
    source = str(source or "").strip()
    if not source:
        return "source must be a local file path or an http(s) URL", True
    if kind:
        check_replaceable(ctx, asset_id, kind)          # before the download: a clash wastes nothing
    cap = int(number(ctx.providers["import"].get("max_mb", 200), 1, 4096, "providers.import.max_mb") * (1 << 20))
    scheme = _URL_SCHEME.match(source)
    src = None
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        return f"source scheme {scheme.group(1)!r} is not allowed: give a local file path or an http(s) URL", True
    if not scheme:
        src = _local_source(ctx, source)
        if src.stat().st_size > cap:
            return f"{src.name} is over the {cap // (1 << 20)} MB import limit (providers.import.max_mb)", True
        if kind == "evidence":                          # refused before anything is copied
            with open(src, "rb") as fh:
                sniffed = sniff(fh.read(64))
            why = _type_refusal("evidence", sniffed[1]) if sniffed and sniffed[0] == "image" else ""
            if why:
                return f"{source}: {why}", True
    ctx.assets_dir.mkdir(parents=True, exist_ok=True)
    part = ctx.assets_dir / f".{asset_id}.{uuid.uuid4().hex[:8]}.import"
    try:
        if src is None:
            origin = download(source, part, cap, opener, resolve=resolve, evidence=kind == "evidence")
        else:
            with open(src, "rb") as fh:
                _copy_capped(fh.read, part, cap)
            origin = str(src)
        found, ext, facts = classify(part)
        want = "image" if kind == "evidence" else kind
        if want and found != want:
            return f"{source} is {'an' if found[0] in 'aeiou' else 'a'} {found} file, not {want}", True
        final = "evidence" if kind == "evidence" else found
        why = _type_refusal(final, ext)
        if why:
            return f"{source}: {why}", True
        check_replaceable(ctx, asset_id, final)
        w, h = header_size(part) or (0, 0)
        if final == "evidence" and not (w and h):
            return f"{source}: the picture's size cannot be read, so it cannot be evidence", True
        dest = ctx.assets_dir / f"{asset_id}{ext}"
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    entry = {"path": rel(ctx, dest), "kind": final,
             "note": f"from {source}"[:200] if scheme else f"from {Path(origin).name}"[:200]}
    if final == "evidence":
        # a screenshot taken elsewhere: the whole picture is the proof until the agent narrows the box
        entry.update(box=[0, 0, w, h], site=urllib.parse.urlsplit(source).hostname or "" if scheme else "",
                     url=source if scheme else "")
    reg = register_asset(ctx, asset_id, entry)
    facts = ", ".join(x for x in (facts, _human(dest.stat().st_size)) if x)
    return f"Imported {asset_id!r}: {rel(ctx, dest)} ({final}, {facts}).{reg}", False


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _uses(tracks, asset_id: str) -> int:
    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, dict):
            for k, v in node.items():
                if (k == "asset" or k.endswith("_asset")) and v == asset_id:
                    count += 1
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(tracks)
    return count


def _describe(ctx: Context, asset_id: str, entry: dict, tracks) -> str:
    path = project_file(ctx.project, entry.get("path"))
    kind = entry.get("kind", "?")
    head = f"{asset_id}  {kind}  {entry.get('path')}"
    if path is None:
        return head + "  OUTSIDE the project folder (import_asset copies a file in, then point the asset at it)"
    if not path.is_file():
        return head + "  MISSING (the file is gone: re-make it or remove_asset)"
    facts = []
    if kind in ("image", "evidence"):
        size = header_size(path)
        if size:
            facts.append(f"{size[0]}x{size[1]}")
    elif kind in ("video", "audio") and shutil.which("ffprobe"):
        try:
            _, _, dur = _streams(path)
            if dur:
                facts.append(f"{dur:.2f} s")
        except ProviderError:
            facts.append("unreadable")
    facts.append(_human(path.stat().st_size))
    if kind == "evidence":
        facts.append(f"box {entry.get('box')}")
        if entry.get("site"):
            facts.append(f"site {entry['site']}")
    uses = _uses(tracks, asset_id)
    facts.append(f"used {uses}x" if uses else "unused")
    note = str(entry.get("note") or "")
    return head + "  " + ", ".join(facts) + (f"  - {note[:80]}" if note else "")


@safe_tool
def assets(project):
    """(text, is_error): the project's assets with kinds, sizes and durations; files not registered; spend."""
    ctx = context(project)
    data = read_project(ctx)
    entries = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    tracks = data.get("tracks") or []
    rows = [f"Assets ({len(entries)}):"] + [f"  {_describe(ctx, k, v if isinstance(v, dict) else {}, tracks)}"
                                            for k, v in sorted(entries.items())]
    if not entries:
        rows = ["Assets: none yet (speak, capture, draw, animate, import_asset add them)."]
    known = {str((v or {}).get("path") or "").lower() for v in entries.values() if isinstance(v, dict)}
    loose = sorted(rel(ctx, f) for f in ctx.assets_dir.glob("*")
                   if f.is_file() and not f.name.startswith(".") and rel(ctx, f).lower() not in known) \
        if ctx.assets_dir.is_dir() else []
    if loose:
        rows.append("In assets/ but not registered (import_asset them to use): " + ", ".join(loose[:30]))
    rows.append(_voice_line(ctx, data))
    rows.append(_spend_line(ctx))
    return "\n".join(rows), False


def _voice_line(ctx: Context, data: dict) -> str:
    ref = data.get("voice")
    if not ref:
        return "Narration: none (speak writes voice/voice.wav and voice/voice.json)."
    try:
        v = json.loads((ctx.project / str(ref)).read_text(encoding="utf-8"))
        wav = ctx.project / str(v.get("file") or "")
        ok = "" if wav.is_file() else f", but {v.get('file')} is missing"
        return f"Narration: {ref}, {float(v.get('duration_s') or 0):.2f} s, {len(v.get('lines') or [])} lines{ok}."
    except (OSError, ValueError, TypeError, AttributeError):
        return f"Narration: {ref} cannot be read."


def _spend_line(ctx: Context) -> str:
    ledger = ctx.ledger()
    spent, guessed = ledger.spent(ctx.project_key), ledger.estimated(ctx.project_key)
    line = (f"Paid spend: ${spent:.3f} of the ${ctx.budget['per_project_usd']:.2f} project budget "
            f"(balance floor ${ctx.budget['min_balance_usd']:.2f}).")
    if guessed > 0:
        line += (f" ${guessed:.3f} of it is an estimate (cost_source \"estimate\": speech answers carry no cost, so "
                 "it is priced from providers.tts.usd_per_1k_chars).")
    return line
