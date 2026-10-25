"""transcribe: word-level timing of what is said in a video or audio asset, saved as assets/<id>.transcript.json and
referenced from the asset (Asset.transcript), so captions can follow the speech and cuts can follow the words.

Providers (workspace.json providers.transcribe.provider):
- "openai": any OpenAI-compatible POST {base_url}/audio/transcriptions (OpenAI, Groq, a local whisper server) asked
  for verbose_json with word timestamps. The sound is sent as 16 kHz mono MP3, in pieces cut at silences when it
  is over max_mb; each piece's times are moved back to the source's clock. Paid: estimated from usd_per_min and
  booked in the ledger first.
- "local": faster-whisper in this process (the `transcribe` extra), free.
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import (Context, EditRefused, ProviderError, _apply_or_write, check_id, context, exe, number, read_project,
                     redact, rel, run_tree, safe_tool, tail, write_json)
from .footage import asset_file, facts, silent_ranges

SAMPLE_RATE = 16000
MP3_RATE = "32k"                # speech at 16 kHz: about 14 MB an hour
MAX_ROWS = 80
SPLIT_SEARCH = 0.5              # a piece ends at a silence in the last half of its allowed length, else hard
_MODELS: dict = {}              # faster-whisper models loaded in this process


class Engine:
    """What transcribe needs from a provider: check() before anything is spent, run(audio, language, prompt)."""
    name = "engine"
    paid = False
    suffix = ".wav"
    max_bytes: int | None = None

    def identity(self) -> str:
        return self.name

    def check(self) -> None:
        """Raise ProviderError when it cannot run (no key, a missing package)."""

    def run(self, audio: Path, language: str, prompt: str) -> dict:
        """{"words": [{"word", "start", "end"}], "segments": [{"start", "end", "text"}], "text", "language"}."""
        raise NotImplementedError


class OpenAIEngine(Engine):
    name = "openai"
    paid = True
    suffix = ".mp3"

    def __init__(self, cfg: dict, key: str, opener=None, sleep=time.sleep):
        self.cfg, self.key = dict(cfg), key
        self.base = str(cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = str(cfg.get("model") or "whisper-1")
        self.key_env = cfg.get("key_env")
        self.timeout = number(cfg.get("timeout_s") or 600, 10, 7200, "providers.transcribe.timeout_s")
        self.max_bytes = int(number(cfg.get("max_mb") or 24, 0.001, 1000, "providers.transcribe.max_mb") * (1 << 20))
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def identity(self) -> str:
        return f"openai|{self.base}|{self.model}"

    def check(self) -> None:
        if not self.base.startswith(("http://", "https://")):
            raise ProviderError("providers.transcribe.base_url must be an http(s) address")
        if self.key_env and not self.key:
            raise ProviderError(f"no {self.key_env}: put it in the workspace .env (or the environment), or point "
                                "providers.transcribe at a server that needs no key (key_env null) or at the local "
                                "provider")

    def _body(self, audio: Path, language: str, prompt: str) -> tuple[bytes, str]:
        boundary = f"----reelsmith{uuid.uuid4().hex}"
        fields = [("model", self.model), ("response_format", "verbose_json"),
                  ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
        fields += [("language", language)] if language else []
        fields += [("prompt", prompt)] if prompt else []
        parts = []
        for name, value in fields:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
                         .encode("utf-8"))
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{audio.name}\"\r\n"
                     "Content-Type: audio/mpeg\r\n\r\n".encode("utf-8") + audio.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    def run(self, audio: Path, language: str, prompt: str) -> dict:
        body, ctype = self._body(audio, language, prompt)
        headers = {"Content-Type": ctype, "User-Agent": "reelsmith"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        url = self.base + "/audio/transcriptions"
        last = ""
        for attempt in range(3):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    payload = resp.read()
                return parse_response(json.loads(payload))
            except urllib.error.HTTPError as exc:
                try:
                    text = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    text = ""
                last = f"HTTP {exc.code}: {redact(text, [self.key])[:300]}"
                if exc.code not in (408, 409, 425, 429) and exc.code < 500:
                    break                       # a bad request or a bad key does not heal on retry
            except urllib.error.URLError as exc:
                last = f"cannot reach {urllib.parse.urlsplit(url).hostname}: {redact(exc.reason, [self.key])}"
            except (ValueError, TypeError, KeyError) as exc:
                last = f"the answer is not a transcript ({type(exc).__name__}: {exc})"
                break
            if attempt < 2:
                self._sleep(2 * (attempt + 1))
        raise ProviderError(f"transcription failed: {last}")


class LocalEngine(Engine):
    name = "local"

    def __init__(self, cfg: dict):
        self.cfg = dict(cfg)
        self.model = str(cfg.get("local_model") or "small")

    def identity(self) -> str:
        return f"local|{self.model}"

    def check(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            raise ProviderError("the local transcriber needs faster-whisper: pip install -e \".[transcribe]\" (or set "
                                "providers.transcribe.provider to \"openai\" with an endpoint)") from None

    def run(self, audio: Path, language: str, prompt: str) -> dict:
        from faster_whisper import WhisperModel
        key = (self.model, self.cfg.get("device") or "auto", self.cfg.get("compute_type") or "default")
        if key not in _MODELS:
            _MODELS[key] = WhisperModel(key[0], device=key[1], compute_type=key[2])
        segments, info = _MODELS[key].transcribe(str(audio), language=language or None,
                                                 initial_prompt=prompt or None, word_timestamps=True)
        segs, words = [], []
        for s in segments:
            segs.append({"start": float(s.start), "end": float(s.end), "text": str(s.text).strip()})
            words += [{"word": str(w.word), "start": float(w.start), "end": float(w.end)} for w in (s.words or [])]
        return parse_response({"words": words, "segments": segs, "language": getattr(info, "language", None),
                               "text": " ".join(s["text"] for s in segs)})


def _openai(ctx: Context, cfg: dict) -> OpenAIEngine:
    key_env = cfg.get("key_env")
    return OpenAIEngine(cfg, ctx.key(str(key_env)) if key_env else "")


ENGINES = {"openai": _openai, "local": lambda ctx, cfg: LocalEngine(cfg)}


def make_engine(ctx: Context) -> Engine:
    cfg = ctx.providers["transcribe"]
    name = str(cfg.get("provider") or "openai")
    if name not in ENGINES:
        raise ProviderError(f"transcription provider {name!r} is not available (workspace.json "
                            f"providers.transcribe.provider); available: {', '.join(ENGINES)}")
    return ENGINES[name](ctx, cfg)


# ------------------------------------------------------------------ the answer
def _time(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and v >= 0 else None


def parse_response(data: dict) -> dict:
    """Words and segments from a verbose_json answer (top-level words, or words inside segments)."""
    if not isinstance(data, dict):
        raise ValueError("not an object")
    raw = data.get("words")
    if not isinstance(raw, list):
        raw = [w for s in data.get("segments") or [] if isinstance(s, dict) for w in s.get("words") or []]
    words = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        text = str(w.get("word") if w.get("word") is not None else w.get("text") or "").strip()
        a, b = _time(w.get("start")), _time(w.get("end"))
        if text and a is not None and b is not None:
            words.append({"word": text, "start": round(a, 3), "end": round(max(a, b), 3)})
    segments = []
    for s in data.get("segments") or []:
        if isinstance(s, dict) and _time(s.get("start")) is not None and _time(s.get("end")) is not None:
            segments.append({"start": round(_time(s["start"]), 3), "end": round(_time(s["end"]), 3),
                             "text": str(s.get("text") or "").strip()})
    return {"words": words, "segments": segments, "text": str(data.get("text") or "").strip(),
            "language": data.get("language")}


# ------------------------------------------------------------------ the sound
def extract(src: Path, out: Path) -> None:
    """Mono 16 kHz sound of `src`: MP3 for an endpoint (small), WAV for the local model."""
    codec = ["-c:a", "libmp3lame", "-b:a", MP3_RATE] if out.suffix == ".mp3" else ["-c:a", "pcm_s16le"]
    rc, _, err, timed = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn",
                                  "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE), *codec, str(out)], timeout=3600)
    if timed or rc != 0 or not out.is_file() or out.stat().st_size == 0:
        raise ProviderError(f"ffmpeg could not take the sound out of {src.name}: {tail(err)}")


def pieces(dur: float, size: int, max_bytes: int | None, quiet: list[dict]) -> list[tuple[float, float]]:
    """(start, end) pieces of a `dur`-second file of `size` bytes, each under max_bytes, cut in silences."""
    if not max_bytes or size <= max_bytes or dur <= 0:
        return [(0.0, dur)]
    longest = max(1.0, dur * max_bytes / size * 0.9)
    out, a = [], 0.0
    while dur - a > longest:
        lo, hi = a + longest * SPLIT_SEARCH, a + longest
        mids = [(s["start"] + s["end"]) / 2 for s in quiet if lo <= (s["start"] + s["end"]) / 2 <= hi]
        b = round(max(mids) if mids else hi, 3)
        out.append((a, b))
        a = b
    out.append((a, dur))
    return out


def cut(src: Path, a: float, b: float, out: Path) -> None:
    codec = ["-c:a", "libmp3lame", "-b:a", MP3_RATE] if out.suffix == ".mp3" else ["-c:a", "pcm_s16le"]
    rc, _, err, _ = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.3f}", "-to",
                              f"{b:.3f}", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), *codec, str(out)],
                             timeout=1800)
    if rc != 0 or not out.is_file():
        raise ProviderError(f"ffmpeg could not cut the sound at {a:.2f}-{b:.2f} s: {tail(err)}")


def stitch(parts: list[tuple[float, dict]]) -> dict:
    """Pieces' answers on the source's clock: each piece's times move by its start."""
    words, segments, texts, language = [], [], [], None
    for offset, res in parts:
        words += [{**w, "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)}
                  for w in res["words"]]
        segments += [{**s, "start": round(s["start"] + offset, 3), "end": round(s["end"] + offset, 3)}
                     for s in res["segments"]]
        texts += [res["text"]] if res.get("text") else []
        language = language or res.get("language")
    return {"words": words, "segments": segments, "text": " ".join(texts), "language": language}


# ------------------------------------------------------------------ the tool
def _asset(ctx: Context, asset_id) -> tuple[str, dict, Path]:
    assets = read_project(ctx).get("assets")
    assets = assets if isinstance(assets, dict) else {}
    aid = str(asset_id or "").strip()
    entry = assets.get(aid)
    if not isinstance(entry, dict):
        known = ", ".join(sorted(assets)) or "none yet"
        raise ProviderError(f"no asset {aid!r} (assets: {known}): import_asset the recording first")
    if entry.get("kind") not in ("video", "audio"):
        raise ProviderError(f"asset {aid!r} is {entry.get('kind')}: only video and audio assets can be transcribed")
    check_id(aid, "asset id")
    return aid, entry, asset_file(ctx, aid, entry)


def _estimate(cfg: dict, seconds: float) -> float:
    rate = cfg.get("usd_per_min")
    rate = 0.0 if rate is None else number(rate, 0, 100, "providers.transcribe.usd_per_min")
    return round(seconds / 60.0 * rate, 6)


def _run(ctx: Context, engine: Engine, cfg: dict, audio: Path, dur: float, work: Path, language: str,
         prompt: str) -> tuple[dict, str]:
    quiet = silent_ranges(audio, 0.3, -35, dur) if engine.max_bytes and audio.stat().st_size > engine.max_bytes else []
    plan = pieces(dur, audio.stat().st_size, engine.max_bytes, quiet)
    res = None
    if engine.paid:
        res = ctx.ledger().reserve(project=ctx.project_key, tool="transcribe", provider=engine.name,
                                   est_usd=_estimate(cfg, dur), budget_usd=ctx.budget["per_project_usd"],
                                   model=getattr(engine, "model", None), seconds=round(dur, 1), pieces=len(plan))
    done, answers, error = 0.0, [], None
    try:
        for n, (a, b) in enumerate(plan):
            piece = audio
            if len(plan) > 1:
                piece = work / f"piece{n:03d}{audio.suffix}"
                cut(audio, a, b, piece)
            answers.append((a, engine.run(piece, language, prompt)))
            done += b - a
    except Exception as exc:  # noqa: BLE001 - settled below, then raised as it was
        error = exc
        raise
    finally:
        if res is not None:
            status = "failed" if error is not None and not answers else "partial" if error is not None else "success"
            ctx.ledger().settle(res, status, _estimate(cfg, done), cost_source="estimate",
                                estimated_usd=_estimate(cfg, done),
                                error=ctx.redact(str(error))[:200] if error is not None else None)
    spent = f" (est. ${_estimate(cfg, done):.4f})" if engine.paid else " (local, free)"
    note = f" in {len(plan)} pieces cut at silences" if len(plan) > 1 else ""
    return stitch(answers), spent + note


def set_transcript(ctx: Context, aid: str, path: str) -> str:
    """Point the asset's transcript at path ('' or a note)."""
    op = {"op": "update_asset", "id": aid, "set": {"transcript": path}}

    def direct(data: dict) -> None:
        data.setdefault("assets", {}).setdefault(aid, {})["transcript"] = path
    try:
        return _apply_or_write(ctx, [op], direct)
    except EditRefused as exc:
        return (f" project.json did not take the transcript ({exc.why}); set it with edit "
                f"{json.dumps([op], ensure_ascii=False)}.")


@safe_tool
def transcribe(project, asset, language=None, prompt=None, *, engine: Engine | None = None):
    """(text, is_error): word timing of a video or audio asset into assets/<id>.transcript.json."""
    ctx = context(project)
    aid, entry, path = _asset(ctx, asset)
    f = facts(path)
    if not f.get("audio"):
        return f"asset {aid!r} ({entry.get('path')}) has no sound to transcribe", True
    dur = float(f.get("duration_s") or 0.0)
    language = str(language or ctx.providers["transcribe"].get("language") or "").strip()
    prompt = str(prompt or "").strip()
    if len(prompt) > 800:
        return "prompt is a hint of names and words (at most 800 characters)", True
    cfg = ctx.providers["transcribe"]
    engine = engine or make_engine(ctx)
    engine.check()
    work = ctx.cache_dir / "transcribe" / uuid.uuid4().hex[:12]
    work.mkdir(parents=True, exist_ok=True)
    try:
        audio = work / f"sound{engine.suffix}"
        extract(path, audio)
        result, spent = _run(ctx, engine, cfg, audio, dur, work, language, prompt)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = ctx.assets_dir / f"{aid}.transcript.json"
    transcript = {"version": 1, "asset": aid, "source": entry.get("path"), "duration_s": round(dur, 3),
                  "language": result["language"] or language or None, "provider": engine.identity(),
                  "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "text": result["text"],
                  "words": result["words"], "segments": result["segments"]}
    write_json(out, transcript)
    note = set_transcript(ctx, aid, rel(ctx, out))
    return _text(aid, entry, transcript, rel(ctx, out), spent, note), False


def _text(aid: str, entry: dict, t: dict, out: str, spent: str, note: str) -> str:
    lang = f", {t['language']}" if t.get("language") else ""
    rows = [f"Transcribed asset {aid!r} ({entry.get('path')}, {t['duration_s']:.2f} s{lang}): {len(t['words'])} "
            f"words, {len(t['segments'])} segment(s) -> {out}{spent}.{note}"]
    if not t["words"]:
        rows.append("No words were heard: is the sound speech? Try language or a prompt with the names said.")
        return "\n".join(rows)
    lines = t["segments"] or [{"start": w["start"], "end": w["end"], "text": w["word"]} for w in t["words"]]
    rows.append('What is said, in source seconds (on the timeline "src:<clip>@<seconds>"; every word with its time '
                "is in the file):")
    rows += [f"  [{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in lines[:MAX_ROWS]]
    if len(lines) > MAX_ROWS:
        rows.append(f"  ... {len(lines) - MAX_ROWS} more in {out}")
    rows.append(f'Captions that follow the speech: a captions track with "source": "clip:<a clip playing {aid}>".')
    return "\n".join(rows)
