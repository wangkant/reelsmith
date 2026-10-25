"""speak: one TTS call per line, joined into voice/voice.wav and timed in voice/voice.json.

Each line is cached by everything that shapes its audio (provider, model, voice, style, pace, emotion, text), so
re-speaking a script only pays for the lines that changed. Every line is trimmed of the TTS's own padding and
brought to the same loudness before the lines are joined with fixed gaps.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import locales
from .config import (Context, ProviderError, VOICE_JSON, context, exe, number, patient, project_locale, rel, run_tree,
                     safe_tool, set_voice_if_unset, tail, write_json)
from .openrouter import KEY_NAME, ZH_VOICE, OpenRouter, synthesize

PACE = {"slower": 1.10, "normal": 1.25, "faster": 1.35}
PACE_FACTOR = (0.5, 2.0)
DEFAULT_GAP_S = 0.22
MAX_GAP_S = 1.5
SAMPLE_RATE = 48000
EDGE_KEEP_S = 0.06          # the TTS pads each line with ~0.3 s; keep a breath of it so gaps stay short
GAIN_LIMITS = (-12.0, 18.0)
WORKERS = 4
MAX_LINES = 200
MAX_LINE_CHARS = 400
MAX_EMOTION_CHARS = 20
CACHE_VERSION = "1"
PROCESS_VERSION = "p4"
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


class TTSEngine:
    """What speak needs from a TTS provider. Override identity, synth and (when the account has one) balance."""
    name = "tts"
    has_balance = False

    def identity(self) -> str:
        raise NotImplementedError

    def check(self) -> None:
        """Raise ProviderError when the engine cannot run (e.g. no key); called before anything is reserved."""

    def synth(self, text: str, speed: float, emotion: str) -> bytes:
        """mp3 (or any ffmpeg-readable) bytes for one line; raise ProviderError on failure. The bytes may carry a
        `cost` attribute (USD the provider reported for this line); without it the line is priced at the estimate."""
        raise NotImplementedError

    def balance(self) -> float:
        raise NotImplementedError


class OpenRouterTTS(TTSEngine):
    name = "openrouter"
    has_balance = True

    def __init__(self, cfg: dict, key: str, client: OpenRouter | None = None):
        self.cfg, self.key, self._client = dict(cfg), key, client

    @property
    def client(self) -> OpenRouter:
        if self._client is None:
            self._client = OpenRouter(self.key)       # raises an actionable error when the key is missing
        return self._client

    def identity(self) -> str:
        c = self.cfg
        parts = ["openrouter", str(c.get("model")), str(c.get("voice")), str(c.get("speed_scale") or 1),
                 str(c.get("instructions") or "")]
        if not locales.is_chinese(c.get("locale") or "zh"):
            parts.append(locales.language(c["locale"]))         # its pace and mood words are not Chinese
        return "|".join(parts)

    def check(self) -> None:
        _ = self.client

    def synth(self, text: str, speed: float, emotion: str) -> bytes:
        return synthesize(self.client, text, self.cfg, speed, emotion)

    def balance(self) -> float:
        return self.client.balance()


ENGINES = {"openrouter": lambda ctx, cfg: OpenRouterTTS(cfg, ctx.key(KEY_NAME))}


def default_voice(cfg: dict, locale: str) -> str:
    """providers.tts.voice, else the default model's Mandarin voice for a Chinese locale; ProviderError otherwise."""
    if cfg.get("voice"):
        return str(cfg["voice"])
    if locales.is_chinese(locale):
        return ZH_VOICE
    raise ProviderError(f"no voice for locale {locale}: the default voice ({ZH_VOICE}) speaks Mandarin; set "
                        f"providers.tts.voice in workspace.json to a voice of {cfg.get('model')} that speaks {locale} "
                        "(or set the project's locale if the film is in Chinese)")


def make_engine(ctx: Context) -> TTSEngine:
    cfg = ctx.providers["tts"]
    name = str(cfg.get("provider") or "openrouter")
    if name not in ENGINES:
        raise ProviderError(f"TTS provider {name!r} is not available (workspace.json providers.tts.provider); "
                            f"available: {', '.join(ENGINES)}")
    return ENGINES[name](ctx, cfg)


# ------------------------------------------------------------------ lines
def line_spec(item, n: int) -> dict:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        raise ProviderError(f"line {n}: give a string or {{text, pace?, emotion?}} (got {type(item).__name__})")
    unknown = set(item) - {"text", "pace", "emotion"}
    if unknown:
        raise ProviderError(f"line {n}: unknown field(s) {sorted(unknown)}; a line takes text, pace, emotion")
    text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
    if not text:
        raise ProviderError(f"line {n} is empty")
    if len(text) > MAX_LINE_CHARS:
        raise ProviderError(f"line {n} has {len(text)} characters; split it (at most {MAX_LINE_CHARS} per line)")
    emotion = str(item.get("emotion") or "").strip()
    if len(emotion) > MAX_EMOTION_CHARS:
        raise ProviderError(f"line {n}: emotion is a word or two (at most {MAX_EMOTION_CHARS} characters)")
    return {"text": text, "speed": _speed(item.get("pace"), n), "emotion": emotion}


def _speed(pace, n: int) -> float:
    """A named pace, or a number relative to normal (0.9 = a little slower)."""
    if pace in (None, ""):
        return PACE["normal"]
    if isinstance(pace, str) and pace in PACE:
        return PACE[pace]
    if isinstance(pace, (int, float)) and not isinstance(pace, bool) and PACE_FACTOR[0] <= pace <= PACE_FACTOR[1]:
        return round(PACE["normal"] * float(pace), 3)
    raise ProviderError(f"line {n}: pace must be one of {', '.join(PACE)} or a number {PACE_FACTOR[0]}-"
                        f"{PACE_FACTOR[1]} relative to normal (got {pace!r})")


def cache_key(engine: TTSEngine, spec: dict) -> str:
    blob = "|".join([CACHE_VERSION, engine.identity(), str(spec["speed"]), spec["emotion"], spec["text"]])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ------------------------------------------------------------------ audio
def loudness(path: Path) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBTP); None where ffmpeg gives no reading."""
    _, _, err, _ = run_tree([exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-af",
                             "ebur128=peak=true", "-f", "null", "-"], timeout=300)
    i = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", err or "")
    p = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", err or "")
    return (float(i[-1]) if i and i[-1] != "-inf" else None, float(p[-1]) if p and p[-1] != "-inf" else None)


def process_line(src: Path, wav: Path, target_lufs: float) -> None:
    """Trim the TTS's own leading/trailing silence, bring the line to target_lufs, keep peaks under -1.5 dBFS."""
    tag = uuid.uuid4().hex[:8]
    trimmed = wav.with_name(f".{wav.stem}.{tag}.trim.wav")
    edge = f"silenceremove=start_periods=1:start_threshold=-50dB:start_silence={EDGE_KEEP_S}"
    try:
        rc, _, err, _ = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
                                  f"{edge},areverse,{edge},areverse", "-ar", str(SAMPLE_RATE), "-ac", "1",
                                  str(trimmed)], timeout=120)
        if rc != 0 or not trimmed.is_file():
            raise ProviderError(f"ffmpeg could not trim a line: {tail(err)}")
        lufs, _ = loudness(trimmed)
        gain = 0.0 if lufs is None else max(GAIN_LIMITS[0], min(GAIN_LIMITS[1], target_lufs - lufs))
        part = wav.with_name(f".{wav.stem}.{tag}.part.wav")
        rc, _, err, _ = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(trimmed),
                                  "-af", f"volume={gain:.2f}dB,alimiter=limit=0.84:attack=5:release=50:level=0",
                                  "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(part)], timeout=120)
        if rc != 0 or not part.is_file():
            part.unlink(missing_ok=True)
            raise ProviderError(f"ffmpeg could not level a line: {tail(err)}")
        os.replace(part, wav)
    finally:
        trimmed.unlink(missing_ok=True)


def _join(wavs: list[Path], specs: list[dict], gap_s: float, out: Path) -> tuple[list[dict], float]:
    gap = int(round(gap_s * SAMPLE_RATE))
    lines, frames = [], 0
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f".{out.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with wave.open(str(part), "wb") as dst:
            dst.setnchannels(1)
            dst.setsampwidth(2)
            dst.setframerate(SAMPLE_RATE)
            for i, (wav, spec) in enumerate(zip(wavs, specs)):
                with wave.open(str(wav), "rb") as src:
                    if (src.getnchannels(), src.getsampwidth(), src.getframerate()) != (1, 2, SAMPLE_RATE):
                        raise ProviderError(f"line {i + 1}: cached audio has an unexpected format; delete {wav}")
                    data = src.readframes(src.getnframes())
                t0 = frames / SAMPLE_RATE
                dst.writeframes(data)
                frames += len(data) // 2
                lines.append({"i": i + 1, "text": spec["text"], "t0": round(t0, 3),
                              "t1": round(frames / SAMPLE_RATE, 3)})
                if i < len(specs) - 1 and gap:
                    dst.writeframes(b"\x00\x00" * gap)
                    frames += gap
        patient(lambda: os.replace(part, out))       # a player may hold the old take open
    finally:
        part.unlink(missing_ok=True)
    return lines, round(frames / SAMPLE_RATE, 3)


# ------------------------------------------------------------------ speak
def _project_lock(ctx: Context) -> threading.Lock:
    with _GUARD:
        return _PROJECT_LOCKS.setdefault(str(ctx.project).lower(), threading.Lock())


def _synth_fresh(engine: TTSEngine, fresh: dict[str, dict], cache: Path) -> tuple[dict[str, str], dict[str, float]]:
    """Synthesize every fresh line into the cache; ({key: why} for the lines that failed, {key: USD} for the lines
    whose cost the provider reported)."""
    def one(item):
        key, spec = item
        mp3 = cache / f"{key}.mp3"
        part = cache / f".{key}.{uuid.uuid4().hex[:8]}.part"
        try:
            data = engine.synth(spec["text"], spec["speed"], spec["emotion"])
            if not data:
                raise ProviderError("the TTS returned no audio")
            part.write_bytes(data)
            os.replace(part, mp3)
            return key, "", getattr(data, "cost", None)
        except Exception as exc:  # noqa: BLE001 — one line's failure must not lose the others
            part.unlink(missing_ok=True)
            return key, str(exc) if isinstance(exc, ProviderError) else f"{type(exc).__name__}: {exc}", None

    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(fresh)))) as pool:
        done = list(pool.map(one, fresh.items()))
    failed = {k: why for k, why, _ in done if why}
    costs = {k: float(c) for k, why, c in done if not why and isinstance(c, (int, float)) and not isinstance(c, bool)}
    return failed, costs


def _processed(keys: list[str], cache: Path, target: float) -> list[Path]:
    wavs = [cache / f"{k}.{PROCESS_VERSION}{target:+.1f}.wav" for k in keys]
    todo = {k: w for k, w in zip(keys, wavs) if not w.is_file()}
    with ThreadPoolExecutor(max_workers=min(WORKERS, max(1, len(todo)))) as pool:
        list(pool.map(lambda kw: process_line(cache / f"{kw[0]}.mp3", kw[1], target), todo.items()))
    return wavs


def _estimate(cfg: dict, chars: int) -> float:
    rate = cfg.get("usd_per_1k_chars")
    rate = 0.0 if rate is None else number(rate, 0, 100, "providers.tts.usd_per_1k_chars")
    return round(chars / 1000.0 * rate, 6)


@safe_tool
def speak(project, lines, gap_s=DEFAULT_GAP_S, *, engine: TTSEngine | None = None):
    """(text, is_error): narrate `lines` into voice/voice.wav + voice/voice.json.

    Each line is a string or {"text", "pace"?, "emotion"?}:
    - pace: how fast the line is read, as a speed factor relative to the normal reading: a number 0.5-2.0 (1.0 =
      normal, 0.9 = 10% slower, 1.1 = 10% faster) or "slower" (0.88), "normal" (1.0, the default), "faster" (1.08).
      A voice that takes a numeric speed gets the factor itself (times providers.tts.speed_scale). The default Qwen
      voice takes words instead, so for it pace only picks one of three readings: below 0.944 slow and deliberate,
      0.944 up to 1.04 brisk (the normal reading), 1.04 and up faster.
    - emotion: free words (at most 20 characters, e.g. "惊讶", "严肃", "轻松地笑") passed to the TTS model as the line's
      style ("这一句的情绪：…"); models with an emotion field also get them there. There is no fixed list and no
      guarantee of effect: listen to the line. Changing pace or emotion re-synthesizes (and pays for) that line.
    gap_s: silence between lines, 0-1.5 s (default 0.22)."""
    ctx = context(project)
    if not isinstance(lines, list) or not lines:
        return "lines must be a non-empty list of strings or {text, pace?, emotion?}", True
    if len(lines) > MAX_LINES:
        return f"{len(lines)} lines is too many for one narration (at most {MAX_LINES})", True
    specs = [line_spec(x, n) for n, x in enumerate(lines, 1)]
    gap = number(gap_s, 0, MAX_GAP_S, "gap_s")
    cfg = ctx.providers["tts"]
    target = number(cfg.get("line_lufs", -12.0), -30, -6, "providers.tts.line_lufs")
    if engine is None:
        locale = project_locale(ctx)
        cfg.update(voice=default_voice(cfg, locale), locale=locale)
        engine = make_engine(ctx)
    cache = ctx.cache_dir / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    with _project_lock(ctx):
        keys = [cache_key(engine, s) for s in specs]
        fresh = {k: s for k, s in zip(keys, specs) if not (cache / f"{k}.mp3").is_file()}
        spent_note = ""
        if fresh:
            engine.check()
            failed, spent_note = _pay_and_synth(ctx, engine, cfg, fresh, cache)
            if failed:
                bad = [n for n, k in enumerate(keys, 1) if k in failed]
                why = next(iter(failed.values()))
                return (f"speak: {len(failed)} of {len(fresh)} new lines failed (line {', '.join(map(str, bad))}): "
                        f"{why}. The lines that worked are cached; call speak again with the same lines to retry "
                        "only the failed ones."), True
        wavs = _processed(keys, cache, target)
        out = ctx.voice_dir / "voice.wav"
        timed, duration = _join(wavs, specs, gap, out)
        lufs, peak = loudness(out)
        manifest = {"file": rel(ctx, out), "duration_s": duration, "lufs": lufs, "true_peak_db": peak,
                    "gap_s": round(gap, 3), "lines": timed}
        write_json(ctx.project / VOICE_JSON, manifest)
        note = set_voice_if_unset(ctx)
    return _speak_text(manifest, len(fresh), len(set(keys)) - len(fresh), spent_note, note), False


def _pay_and_synth(ctx: Context, engine: TTSEngine, cfg: dict, fresh: dict, cache: Path) -> tuple[dict, str]:
    chars = sum(len(s["text"]) for s in fresh.values())
    est = _estimate(cfg, chars)
    ledger = ctx.ledger()
    res = ledger.reserve(project=ctx.project_key, tool="speak", provider=engine.name, est_usd=est,
                         budget_usd=ctx.budget["per_project_usd"], min_balance_usd=ctx.budget["min_balance_usd"],
                         balance=engine.balance if engine.has_balance else None, model=cfg.get("model"),
                         lines=len(fresh), chars=chars)
    failed: dict[str, str] = {}
    reported: dict[str, float] = {}
    try:
        failed, reported = _synth_fresh(engine, fresh, cache)
    finally:
        done = [k for k in fresh if k not in failed]
        guessed = sum(_estimate(cfg, len(fresh[k]["text"])) for k in done if k not in reported)
        cost = sum(reported.values()) + guessed
        source = "estimate" if not reported else "provider+estimate" if guessed else "provider"
        status = "success" if not failed else ("partial" if done else "failed")
        ledger.settle(res, status, cost, cost_source=source, estimated_usd=round(guessed, 6),
                      error=ctx.redact(next(iter(failed.values())))[:200] if failed else None)
    return failed, f" (${cost:.4f} as the provider reported)" if source == "provider" else f" (est. ${cost:.4f})"


def _speak_text(manifest: dict, fresh: int, cached: int, spent: str, note: str) -> str:
    lufs = "?" if manifest["lufs"] is None else f"{manifest['lufs']:.1f}"
    peak = "?" if manifest["true_peak_db"] is None else f"{manifest['true_peak_db']:.1f}"
    head = [f"Narration written: {manifest['file']}, {manifest['duration_s']:.2f} s, {lufs} LUFS, peak {peak} dBTP; "
            f"{VOICE_JSON} has the line times.",
            f"{fresh} line(s) newly synthesized{spent}, {cached} from cache (unchanged lines cost nothing).{note}",
            'Lines (refer to them as Times "line:N" and "line:N.end"):']
    rows = [f"[{ln['i']}] {ln['t0']:.2f}-{ln['t1']:.2f} {ln['text']}" for ln in manifest["lines"]]
    return "\n".join(head + rows)
