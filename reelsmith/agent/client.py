"""A minimal OpenAI-compatible Chat Completions client (stdlib only): one non-streaming POST per model turn.

OpenRouter, DeepSeek, OpenAI, Qwen/GLM gateways and local servers all speak this shape. Usage comes back normalised
to prompt/completion/cached tokens and the provider's own dollar cost when it reports one.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

RETRY_STATUS = {408, 409, 425, 429}          # plus every 5xx
MAX_BACKOFF_S = 30.0
MAX_RETRY_AFTER_S = 120.0


class ApiError(RuntimeError):
    """A request that failed for good: `status` is the HTTP status (None for a transport failure)."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False,
                 wait_s: float | None = None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.wait_s = wait_s                    # the server's Retry-After, when it gave one


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _money(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalise_usage(usage) -> dict:
    """Provider usage -> {prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens, cost_usd}."""
    u = usage if isinstance(usage, dict) else {}
    details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    out_details = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
    cached = (details.get("cached_tokens") if isinstance(details, dict) else None)
    for key in ("prompt_cache_hit_tokens", "cached_tokens", "cache_read_input_tokens"):
        if not cached:
            cached = u.get(key)
    cost = _money(u.get("cost"))
    if cost is not None and u.get("is_byok"):
        # BYOK: OpenRouter's fee is `cost`, the provider bills the inference itself
        cost += _money((u.get("cost_details") or {}).get("upstream_inference_cost")) or 0.0
    return {
        "prompt_tokens": _num(u.get("prompt_tokens") if u.get("prompt_tokens") is not None else u.get("input_tokens")),
        "completion_tokens": _num(u.get("completion_tokens") if u.get("completion_tokens") is not None
                                  else u.get("output_tokens")),
        "cached_tokens": _num(cached),
        "reasoning_tokens": _num(out_details.get("reasoning_tokens") if isinstance(out_details, dict) else 0),
        "cost_usd": cost,
    }


def _loopback(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _retry_after(headers) -> float | None:
    value = (headers.get("Retry-After") or "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _error_text(raw: bytes, limit: int = 600) -> str:
    """The provider's own words from an error body (OpenAI shape, OpenRouter's upstream metadata, or plain text)."""
    text = raw.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text[:limit] or "(empty body)"
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, str):
        return err[:limit]
    if not isinstance(err, dict):
        return (data.get("message") if isinstance(data, dict) and data.get("message") else text)[:limit]
    words = str(err.get("message") or err.get("code") or "error")
    meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    if meta.get("provider_name"):
        words += f" (provider {meta['provider_name']})"
    raw_up = meta.get("raw")
    if raw_up:
        words += ": " + (raw_up if isinstance(raw_up, str) else json.dumps(raw_up, ensure_ascii=False))
    return words[:limit]


def _retryable_code(code) -> bool:
    """An error code inside a 200 body (OpenRouter reports upstream failures this way)."""
    n = _num(code) if not isinstance(code, bool) else 0
    return n == 0 or n in RETRY_STATUS or n >= 500


class ChatClient:
    """POST {base_url}/chat/completions. complete() returns the assistant message as the provider sent it, so its
    tool_calls and reasoning fields can go back in the next request."""

    def __init__(self, base_url: str, api_key: str, model: str, headers: dict | None = None,
                 extra_body: dict | None = None, timeout_s: float = 600, retries: int = 4, *, sleep=None,
                 on_retry=None, proxy: str | None = None):
        self.base_url = str(base_url).rstrip("/")
        self.url = self.base_url + "/chat/completions"
        self.model = model
        self.extra_body = dict(extra_body or {})
        self.timeout_s = float(timeout_s)
        self.retries = max(0, int(retries))
        self.sleep = sleep or time.sleep
        self.on_retry = on_retry            # (attempt, wait_s, reason) -> None
        self.host = urlsplit(self.url).hostname or self.base_url
        self._headers = {"Content-Type": "application/json", "Accept": "application/json",
                         "User-Agent": "reelsmith-runner/1"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._headers.update(headers or {})
        # a local model server is never reached through a proxy; anything else takes `proxy`, else HTTP(S)_PROXY
        if _loopback(self.host):
            handler = urllib.request.ProxyHandler({})
        elif proxy:
            handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        else:
            handler = urllib.request.ProxyHandler()
        self._opener = urllib.request.build_opener(handler)

    def __repr__(self) -> str:                  # never the key
        return f"ChatClient({self.base_url!r}, model={self.model!r})"

    def body(self, messages: list[dict], tools: list[dict]) -> dict:
        body = dict(self.extra_body)
        body.update(model=self.model, messages=messages)
        if tools:
            body["tools"] = tools
        return body

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        data = json.dumps(self.body(messages, tools), ensure_ascii=False).encode("utf-8")
        attempt = 0
        while True:
            try:
                return self._once(data)
            except ApiError as exc:
                if not exc.retryable or attempt >= self.retries:
                    if exc.retryable and self.retries:
                        raise ApiError(f"{exc} (gave up after {attempt + 1} attempts)", exc.status) from exc
                    raise
                wait = exc.wait_s
                if wait is None:
                    wait = min(MAX_BACKOFF_S, 2.0 ** attempt) * random.uniform(0.75, 1.25)
                wait = min(wait, MAX_RETRY_AFTER_S)
                attempt += 1
                if self.on_retry is not None:
                    self.on_retry(attempt, wait, str(exc))
                self.sleep(wait)

    def _once(self, data: bytes) -> dict:
        req = urllib.request.Request(self.url, data=data, headers=self._headers, method="POST")
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                status, headers, raw = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            status, headers = exc.code, exc.headers
            try:
                raw = exc.read()
            except (OSError, http.client.HTTPException):
                raw = b""
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ApiError(f"{self.host}: TLS certificate rejected ({reason})") from exc
            raise ApiError(f"{self.host}: cannot connect ({type(reason).__name__}: {reason})",
                           retryable=True) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ApiError(f"{self.host}: no answer within {self.timeout_s:g} s", retryable=True) from exc
        except (OSError, http.client.HTTPException) as exc:
            # connection reset, remote disconnected, incomplete read, TLS EOF through a proxy
            raise ApiError(f"{self.host}: connection dropped ({type(exc).__name__}: {exc})", retryable=True) from exc
        if status >= 300:
            retryable = status in RETRY_STATUS or status >= 500
            raise ApiError(f"HTTP {status} from {self.host}: {_error_text(raw)}", status, retryable,
                           _retry_after(headers) if retryable else None)
        return self._parse(status, raw)

    def _parse(self, status: int, raw: bytes) -> dict:
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            snippet = raw[:200].decode("utf-8", "replace")
            raise ApiError(f"HTTP {status} from {self.host} is not JSON: {snippet!r}", status, retryable=True)
        if not isinstance(data, dict):
            raise ApiError(f"HTTP {status} from {self.host}: unexpected body {str(data)[:200]}", status,
                           retryable=True)
        choices = data.get("choices")
        err = data.get("error")
        if not choices and err:
            code = err.get("code") if isinstance(err, dict) else None
            raise ApiError(f"{self.host} reported an error: {_error_text(raw)}", status,
                           retryable=_retryable_code(code))
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ApiError(f"{self.host} answered with no choices", status, retryable=True)
        choice = choices[0]
        if choice.get("error"):
            cerr = choice["error"]
            words = cerr.get("message") if isinstance(cerr, dict) else cerr
            code = cerr.get("code") if isinstance(cerr, dict) else None
            raise ApiError(f"{self.host} failed mid-answer: {str(words)[:400]}", status,
                           retryable=_retryable_code(code))
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ApiError(f"{self.host} answered with no message", status, retryable=True)
        message = dict(message)
        message.setdefault("role", "assistant")
        return {"message": message, "usage": normalise_usage(data.get("usage")),
                "finish_reason": str(choice.get("finish_reason") or choice.get("native_finish_reason") or ""),
                "model": data.get("model"), "provider": data.get("provider"), "id": data.get("id")}
