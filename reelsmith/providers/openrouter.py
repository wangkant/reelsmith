"""OpenRouter over plain urllib: /audio/speech (TTS), /videos (image-to-video), /credits (the account balance).

The key goes only to OpenRouter's own host: a polling or download URL on any other host is fetched without it,
and every error text is scrubbed of it.
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import ProviderError, redact

API = "https://openrouter.ai/api/v1"
MIN_AUDIO_BYTES = 512
KEY_NAME = "OPENROUTER_API_KEY"
# /audio/speech answers with raw audio and no usage body; a cost header is used when one is sent
COST_HEADERS = ("x-openrouter-cost", "openrouter-cost", "x-cost-usd", "x-cost")


class Speech(bytes):
    """Audio bytes plus the cost in USD the provider reported for them (None: it reported none)."""
    cost: float | None = None


def reported_cost(headers) -> float | None:
    if not headers:
        return None
    for name in COST_HEADERS:
        value = headers.get(name)
        if value is None:
            continue
        try:
            cost = float(str(value).strip())
        except ValueError:
            continue
        if cost == cost and cost >= 0:
            return cost
    return None


class ApiError(ProviderError):
    def __init__(self, code: int, text: str):
        super().__init__(f"HTTP {code}: {text[:200]}")
        self.code, self.text = code, text


class Unreachable(ProviderError):
    """No usable answer; `maybe_sent` when the server may have acted on the request anyway."""

    def __init__(self, text: str, maybe_sent: bool = False):
        super().__init__(text)
        self.maybe_sent = maybe_sent


class OpenRouter:
    def __init__(self, key: str, base: str = API, timeout: float = 120, opener=None):
        if not key:
            raise ProviderError(f"no {KEY_NAME}: put it in the workspace .env (or the environment)")
        self.key = key
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _url(self, path: str) -> str:
        return path if path.startswith(("http://", "https://")) else self.base + path

    def _ours(self, url: str) -> bool:
        a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(self.base)
        return (a.scheme, a.hostname) == (b.scheme, b.hostname)

    def request(self, path: str, body=None, raw: bool = False, auth: bool = True, timeout: float | None = None,
                headers_out: dict | None = None):
        """The answer as JSON (raw: bytes); headers_out, when given, receives the answer's headers (lower-case)."""
        url = self._url(path)
        if not url.startswith(("http://", "https://")):
            raise ProviderError("OpenRouter returned a non-http URL")
        headers = {"Content-Type": "application/json", "User-Agent": "reelsmith"}
        if auth and self._ours(url):
            headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self._open(req, timeout=timeout or self.timeout) as resp:
                payload = resp.read()
                if headers_out is not None:
                    got = getattr(resp, "headers", None)
                    headers_out.update({str(k).lower(): str(v) for k, v in (got.items() if got else ())})
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                text = ""
            raise ApiError(exc.code, redact(text, [self.key])) from None
        except urllib.error.URLError as exc:
            maybe_sent = isinstance(exc.reason, (socket.timeout, TimeoutError))
            raise Unreachable(f"cannot reach {urllib.parse.urlsplit(url).hostname}: "
                              f"{redact(exc.reason, [self.key])}", maybe_sent) from None
        if raw:
            return payload
        try:
            return json.loads(payload)
        except ValueError:
            raise Unreachable(f"{urllib.parse.urlsplit(url).hostname} answered with something that is not JSON",
                              maybe_sent=True) from None

    def balance(self) -> float:
        d = self.request("/credits", timeout=30)["data"]
        return float(d["total_credits"]) - float(d["total_usage"])

    def speech(self, body: dict) -> bytes:
        headers: dict = {}
        audio = Speech(self.request("/audio/speech", body, raw=True, headers_out=headers))
        audio.cost = reported_cost(headers)
        return audio

    def submit_video(self, body: dict) -> dict:
        return self.request("/videos", body)

    def poll_video(self, job: str, polling_url: str | None = None) -> dict:
        return self.request(polling_url or f"/videos/{urllib.parse.quote(job)}", timeout=60)

    def fetch_video(self, job: str, done: dict) -> bytes:
        url = (done.get("unsigned_urls") or [None])[0]
        if url:
            try:
                return self.request(url, raw=True, auth=False, timeout=300)
            except (ProviderError, OSError):
                pass
        return self.request(f"/videos/{urllib.parse.quote(job)}/content?index=0", raw=True, timeout=300)


# ------------------------------------------------------------------ speech
# Qwen TTS rejects a numeric `speed` (HTTP 400): its pace is steered by words instead.
QWEN_SLOW_BELOW = 1.18
QWEN_FAST_FROM = 1.30


def qwen_pace(speed: float) -> str:
    if speed < QWEN_SLOW_BELOW:
        return "这一句语速放慢，每个字咬清楚，重音落稳"
    if speed >= QWEN_FAST_FROM:
        return "语速更快一点，一口气带过"
    return "语速快一些，干脆利落"


def speech_body(text: str, cfg: dict, speed: float, emotion: str = "") -> dict:
    body = {"model": cfg.get("model") or "qwen/qwen-audio-3.0-tts-plus", "input": text,
            "voice": cfg.get("voice") or "longanlufeng", "response_format": "mp3"}
    instructions = str(cfg.get("instructions") or "").strip()
    sp = float(speed or 1.0)
    if body["model"].startswith("qwen/"):
        if abs(sp - 1.0) > 0.01:
            instructions = (instructions + "；" + qwen_pace(sp)).strip("；")
    else:
        # speed_scale maps the Qwen-calibrated pace onto a voice that takes a numeric speed
        scaled = round(min(2.0, sp * float(cfg.get("speed_scale") or 1.0)), 3)
        if abs(scaled - 1.0) > 0.01:
            body["speed"] = scaled
    if emotion:
        body["emotion"] = emotion           # MiniMax reads it; the others get it as an instruction
        instructions = (instructions + f"；这一句的情绪：{emotion}").strip("；")
    if instructions:
        body["instructions"] = instructions
    return body


def synthesize(client: OpenRouter, text: str, cfg: dict, speed: float, emotion: str = "",
               attempts: int = 2, sleep=time.sleep) -> bytes:
    """mp3 bytes of one line; ProviderError (no key inside) after the retries."""
    body = speech_body(text, cfg, speed, emotion)
    last, tries = "", 0
    while tries < attempts:
        tries += 1
        try:
            data = client.speech(body)
        except ApiError as exc:
            last = str(exc)
            if exc.code == 400 and "emotion" in body:
                body.pop("emotion")             # a model without the knob; the words stay
                tries -= 1
                continue
            if 400 <= exc.code < 500 and exc.code not in (408, 409, 429):
                break                           # a bad request or a bad key does not heal on retry
        except (ProviderError, OSError, ValueError, http.client.HTTPException) as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if len(data or b"") >= MIN_AUDIO_BYTES:
                return data
            last = f"empty audio ({len(data or b'')} bytes)"
        if tries < attempts:
            sleep(3)
    raise ProviderError(f"TTS failed: {redact(last, [client.key])}")
