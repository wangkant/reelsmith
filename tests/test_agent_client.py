import json
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from reelsmith.agent.client import ApiError, ChatClient, normalise_usage
from reelsmith.agent.loop import Agent

KEY = "sk-test-not-a-real-key-123"
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy",
              "no_proxy")


class _Quiet(ThreadingHTTPServer):
    block_on_close = False

    def handle_error(self, request, client_address):     # a client that timed out leaves a broken pipe
        pass


class Server:
    """A local chat-completions endpoint that plays a script: (status, body[, headers]), "reset" or ("sleep", s, step)."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                server.requests.append({"path": self.path, "headers": dict(self.headers),
                                        "body": json.loads(raw or b"null")})
                step = server.steps.pop(0) if server.steps else (500, {"error": {"message": "script ran out"}})
                if isinstance(step, tuple) and step[0] == "sleep":
                    time.sleep(step[1])
                    step = step[2]
                if step == "reset":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                status, body, headers = (list(step) + [{}])[:3]
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        self.httpd = _Quiet(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(autouse=True)
def no_proxy_env(monkeypatch):
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def serve():
    servers = []

    def make(*steps):
        s = Server(*steps)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def ok(message=None, usage=None, finish="stop", **extra):
    body = {"id": "gen-1", "model": "deepseek/deepseek-v4.1-flash", "provider": "DeepSeek",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": message or {"role": "assistant", "content": "hello"}}],
            "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
    body.update(extra)
    return 200, body


def client_for(server, sleeps=None, **kw):
    kw.setdefault("retries", 4)
    return ChatClient(server.base + "/api/v1", KEY, "deepseek/deepseek-v4.1-flash",
                      sleep=(sleeps.append if sleeps is not None else (lambda s: None)), **kw)


TOOLS = [{"type": "function", "function": {"name": "describe", "description": "d",
                                           "parameters": {"type": "object", "properties": {}}}}]


# ------------------------------------------------------------------ the request and the answer
def test_complete_posts_openai_shape_and_keeps_the_message(serve):
    msg = {"role": "assistant", "content": None, "reasoning": "think", "reasoning_details": [{"type": "x", "text": "t"}],
           "tool_calls": [{"id": "call_1", "type": "function",
                           "function": {"name": "describe", "arguments": "{\"project\": \"p\"}"}}]}
    usage = {"prompt_tokens": 1200, "completion_tokens": 80, "cost": 0.00123,
             "prompt_tokens_details": {"cached_tokens": 1000}, "completion_tokens_details": {"reasoning_tokens": 30}}
    s = serve(ok(msg, usage, finish="tool_calls"))
    c = client_for(s, headers={"X-Title": "reelsmith"},
                   extra_body={"usage": {"include": True}, "provider": {"require_parameters": True}})
    out = c.complete([{"role": "user", "content": "hi"}], TOOLS)
    req = s.requests[0]
    assert req["path"] == "/api/v1/chat/completions"
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert req["headers"]["X-Title"] == "reelsmith"
    assert req["body"] == {"usage": {"include": True}, "provider": {"require_parameters": True},
                           "model": "deepseek/deepseek-v4.1-flash", "messages": [{"role": "user", "content": "hi"}],
                           "tools": TOOLS}
    assert out["message"] == msg
    assert out["usage"] == {"prompt_tokens": 1200, "completion_tokens": 80, "cached_tokens": 1000,
                            "reasoning_tokens": 30, "cost_usd": 0.00123}
    assert out["finish_reason"] == "tool_calls" and out["provider"] == "DeepSeek"


def test_no_tools_sends_no_tools_key(serve):
    s = serve(ok())
    client_for(s).complete([{"role": "user", "content": "hi"}], [])
    assert "tools" not in s.requests[0]["body"]


def test_usage_spellings():
    ds = normalise_usage({"prompt_tokens": 500, "completion_tokens": 9, "prompt_cache_hit_tokens": 400,
                          "prompt_cache_miss_tokens": 100})
    assert ds == {"prompt_tokens": 500, "completion_tokens": 9, "cached_tokens": 400, "reasoning_tokens": 0,
                  "cost_usd": None}
    byok = normalise_usage({"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.001, "is_byok": True,
                            "cost_details": {"upstream_inference_cost": 0.02}})
    assert byok["cost_usd"] == pytest.approx(0.021)
    assert normalise_usage(None)["cost_usd"] is None
    assert normalise_usage({"input_tokens": 7, "output_tokens": 3})["prompt_tokens"] == 7


def test_repr_hides_the_key():
    assert KEY not in repr(ChatClient("https://openrouter.ai/api/v1", KEY, "m"))


# ------------------------------------------------------------------ retries
def test_retries_429_and_5xx_then_succeeds(serve):
    s = serve((429, {"error": {"message": "rate limited", "code": 429}}, {"Retry-After": "3"}),
              (502, {"error": {"message": "bad gateway"}}), (503, b"busy"), ok())
    sleeps = []
    retries = []
    c = client_for(s, sleeps, on_retry=lambda n, wait, why: retries.append((n, why)))
    assert c.complete([{"role": "user", "content": "x"}], [])["message"]["content"] == "hello"
    assert len(s.requests) == 4
    assert sleeps[0] == 3.0                     # Retry-After wins
    assert all(0 < w <= 30 for w in sleeps[1:]) and len(sleeps) == 3
    assert [n for n, _ in retries] == [1, 2, 3] and "HTTP 429" in retries[0][1]


def test_a_long_retry_after_is_capped(serve):
    s = serve((503, {"error": {"message": "later"}}, {"Retry-After": "3600"}), ok())
    sleeps, told = [], []
    client_for(s, sleeps, on_retry=lambda n, wait, why: told.append(wait)).complete(
        [{"role": "user", "content": "x"}], [])
    assert sleeps == told == [120.0]


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_client_errors_are_not_retried(serve, status):
    s = serve((status, {"error": {"message": "No auth credentials found", "code": status,
                                  "metadata": {"provider_name": "DeepSeek", "raw": "upstream said no"}}}))
    sleeps = []
    with pytest.raises(ApiError) as info:
        client_for(s, sleeps).complete([{"role": "user", "content": "x"}], [])
    assert len(s.requests) == 1 and sleeps == []
    text = str(info.value)
    assert info.value.status == status and f"HTTP {status}" in text and "127.0.0.1" in text
    assert "No auth credentials found" in text and "DeepSeek" in text and "upstream said no" in text
    assert KEY not in text


def test_gives_up_after_the_retries(serve):
    s = serve(*[(500, {"error": {"message": "boom"}})] * 3)
    with pytest.raises(ApiError) as info:
        client_for(s, retries=2).complete([{"role": "user", "content": "x"}], [])
    assert len(s.requests) == 3
    assert info.value.status == 500 and "gave up after 3 attempts" in str(info.value)


def test_timeout_is_retried(serve):
    s = serve(("sleep", 1.0, ok()), ok())
    sleeps = []
    out = client_for(s, sleeps, timeout_s=0.3).complete([{"role": "user", "content": "x"}], [])
    assert out["message"]["content"] == "hello" and len(sleeps) == 1


def test_connection_reset_is_retried(serve):
    s = serve("reset", ok())
    sleeps = []
    assert client_for(s, sleeps).complete([{"role": "user", "content": "x"}], [])["usage"]["prompt_tokens"] == 10
    assert len(s.requests) == 2 and len(sleeps) == 1


def test_connection_refused_is_a_retryable_transport_error():
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    addr = port.getsockname()[1]
    port.close()                                # nothing listens there now (Windows takes ~2 s to refuse)
    c = ChatClient(f"http://127.0.0.1:{addr}/v1", KEY, "m", retries=0, timeout_s=5)
    with pytest.raises(ApiError) as info:
        c.complete([{"role": "user", "content": "x"}], [])
    assert "cannot connect" in str(info.value) and info.value.status is None and info.value.retryable


def test_errors_inside_a_200_body(serve):
    upstream = (200, {"error": {"message": "Provider returned error", "code": 502}})
    mid = (200, {"choices": [{"finish_reason": "error", "error": {"code": 503, "message": "overloaded"},
                              "message": {"role": "assistant", "content": ""}}]})
    s = serve(upstream, mid, (200, b"<html>gateway</html>"), (200, {"choices": []}), ok())
    sleeps = []
    assert client_for(s, sleeps).complete([{"role": "user", "content": "x"}], [])["message"]["content"] == "hello"
    assert len(s.requests) == 5 and len(sleeps) == 4


def test_a_400_inside_a_200_body_is_final(serve):
    s = serve((200, {"error": {"message": "tools are not supported by this model", "code": 400}}))
    with pytest.raises(ApiError, match="tools are not supported"):
        client_for(s).complete([{"role": "user", "content": "x"}], TOOLS)
    assert len(s.requests) == 1


# ------------------------------------------------------------------ proxies
def test_proxy_from_the_environment_is_used(serve, monkeypatch):
    proxy = serve(ok())
    monkeypatch.setenv("HTTP_PROXY", proxy.base)
    c = ChatClient("http://api.example.test/v1", KEY, "m", sleep=lambda s: None, retries=0)
    assert c.complete([{"role": "user", "content": "x"}], [])["message"]["content"] == "hello"
    # a proxy gets the absolute URL
    assert proxy.requests[0]["path"] == "http://api.example.test/v1/chat/completions"


def test_an_explicit_proxy_replaces_the_environment(serve, monkeypatch):
    proxy = serve(ok())
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    c = ChatClient("http://api.example.test/v1", KEY, "m", sleep=lambda s: None, retries=0, proxy=proxy.base)
    assert c.complete([{"role": "user", "content": "x"}], [])["message"]["content"] == "hello"
    assert proxy.requests[0]["path"] == "http://api.example.test/v1/chat/completions"


def test_a_local_server_skips_the_proxy(serve, monkeypatch):
    s = serve(ok())
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")     # nothing there: going through it would fail
    assert client_for(s, retries=0).complete([{"role": "user", "content": "x"}], [])["message"]["content"] == "hello"
    assert s.requests[0]["path"] == "/api/v1/chat/completions"


# ------------------------------------------------------------------ the loop over the real client
@dataclass
class Res:
    text: str
    images: list = field(default_factory=list)
    error: bool = False


@dataclass
class T:
    name: str
    run: object
    description: str = "a tool"
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {"n": {"type": "integer"}}})


def test_agent_over_http(serve, tmp_path):
    from PIL import Image
    still = tmp_path / "still.png"
    Image.new("RGB", (1080, 1920), (20, 40, 60)).save(still)
    call = {"role": "assistant", "content": "", "reasoning_details": [{"type": "reasoning.text", "text": "plan"}],
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "snap", "arguments": "{\"n\": 2}"}}]}
    s = serve(ok(call, {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.01}, finish="tool_calls"),
              ok({"role": "assistant", "content": "done"}, {"prompt_tokens": 900, "completion_tokens": 5, "cost": 0.02}))
    seen = []
    agent = Agent(client_for(s), [T("snap", lambda a: seen.append(a) or Res("1 still", [still]))], "system words",
                  {"max_turns": 5})
    out = agent.run("make it")
    assert out["result"] == "done" and out["error"] is None and out["turns"] == 2
    assert out["cost_usd"] == pytest.approx(0.03) and not out["cost_estimated"]
    assert seen == [{"n": 2}]
    second = s.requests[1]["body"]
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]
    assert second["messages"][2]["reasoning_details"] == [{"type": "reasoning.text", "text": "plan"}]
    assert second["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "1 still"}
    parts = second["messages"][4]["content"]
    assert parts[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert second["tools"][0]["function"]["name"] == "snap"
