"""Asset providers, offline: every network, browser and model call is a fake injected through a seam."""
import importlib
import inspect
import io
import ipaddress
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import wave
import zlib
from pathlib import Path

import pytest

from reelsmith import netcheck as N
from reelsmith import providers as P
from reelsmith.providers.ledger import BudgetRefused, Ledger

# the package exports the tool functions under the module names (tools.py's getattr contract): reach the modules here
A, C, CFG, D, I, OR, TTS = (importlib.import_module(f"reelsmith.providers.{m}") for m in
                            ("animate", "capture", "config", "draw", "importer", "openrouter", "tts"))

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg/ffprobe not on PATH")
KEY = "sk-or-v1-" + "0123456789abcdef" * 4
TTS_RATE = 10.0                 # $ per 1k chars: an estimate big enough to see in the ledger


# ------------------------------------------------------------------ helpers
def write_png(path: Path, w=64, h=96, rgb=(200, 60, 40)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def png_bytes(w=64, h=96) -> bytes:
    tmp = Path(tempfile.gettempdir()) / f"rs-test-{os.getpid()}-{threading.get_ident()}.png"
    try:
        return write_png(tmp, w, h).read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


_MEDIA: dict = {}
_MEDIA_LOCK = threading.Lock()


def _ffmpeg_bytes(key: str, args: list[str], suffix: str) -> bytes:
    with _MEDIA_LOCK:
        if key not in _MEDIA:
            out = Path(tempfile.gettempdir()) / f"rs-test-media-{os.getpid()}-{len(_MEDIA)}{suffix}"
            try:
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, str(out)], check=True,
                               capture_output=True)
                _MEDIA[key] = out.read_bytes()
            finally:
                out.unlink(missing_ok=True)
        return _MEDIA[key]


def tone_mp3(seconds=0.5, freq=440) -> bytes:
    return _ffmpeg_bytes(f"mp3-{seconds}-{freq}", ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                                                   "-c:a", "libmp3lame", "-b:a", "64k"], ".mp3")


def clip_mp4(seconds=1) -> bytes:
    return _ffmpeg_bytes(f"mp4-{seconds}", ["-f", "lavfi", "-i", f"testsrc2=s=96x160:r=24:d={seconds}",
                                            "-c:v", "libx264", "-pix_fmt", "yuv420p"], ".mp4")


def audio_m4a(seconds=1) -> bytes:
    return _ffmpeg_bytes(f"m4a-{seconds}", ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                                            "-c:a", "aac"], ".m4a")


def read_project(project: Path) -> dict:
    return json.loads((project / "project.json").read_text(encoding="utf-8"))


def ledger_rows(ws: Path) -> list[dict]:
    path = ws / "ledger.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def everything_written(ws: Path) -> str:
    """Every text file under the workspace except .env: where a leaked key would land."""
    out = []
    for f in ws.rglob("*"):
        if f.is_file() and f.name != ".env" and f.suffix in (".json", ".jsonl", ".log", ".md", ""):
            out.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


class Env(types.SimpleNamespace):
    def config(self, **parts):
        cfg = json.loads((self.ws / "workspace.json").read_text(encoding="utf-8"))
        for k, v in parts.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and isinstance(cfg[k].get(kk), dict):
                        cfg[k][kk].update(vv)
                    else:
                        cfg[k][kk] = vv
            else:
                cfg[k] = v
        (self.ws / "workspace.json").write_text(json.dumps(cfg), encoding="utf-8")

    def set_project(self, **fields):
        data = read_project(self.project)
        data.update(fields)
        (self.project / "project.json").write_text(json.dumps(data), encoding="utf-8")


PUBLIC_IP = "93.184.216.34"
PRIVATE_NAMES = {"localtest.me": "127.0.0.1", "intranet.example": "10.0.0.5",
                 "169.254.169.254.nip.io": "169.254.169.254"}


def offline_resolve(host, port):
    """Every name is a public host except the private ones above and nope.example (no such host)."""
    if host == "nope.example":
        raise socket.gaierror(11001, "getaddrinfo failed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return [PRIVATE_NAMES.get(host, PUBLIC_IP)]
    return [host]


class OfflineNet:
    """netcheck's way out in these tests: an address in `refuse` is down; anything else answers like a web server
    (and like a proxy when it is asked to CONNECT)."""

    def __init__(self):
        self.refuse, self.dialed, self._keep = set(), [], []

    def __call__(self, address, timeout=None):
        address = (str(address[0]), int(address[1]))
        self.dialed.append(address)
        if address in self.refuse:
            raise ConnectionRefusedError(10061, "refused")
        mine, theirs = socket.socketpair()
        self._keep.append(theirs)
        threading.Thread(target=self._answer, args=(theirs,), daemon=True).start()
        return mine

    @staticmethod
    def _answer(sock):
        try:
            head = sock.recv(4096)
            if head.startswith(b"CONNECT"):
                sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            while sock.recv(4096):
                pass
        except OSError:
            pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A workspace with a key in .env and one empty project; reelsmith.ops absent (the direct-write path); the network
    replaced by offline_resolve and OfflineNet."""
    for name in ("REELSMITH_ROOT", "REELSMITH_BUDGET_USD", "REELSMITH_MIN_BALANCE_USD", "OPENROUTER_API_KEY",
                 "REELSMITH_PROXY", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY",
                 "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(sys.modules, "reelsmith.ops", None)
    monkeypatch.setattr(D, "_BLOCKED", {})
    net = OfflineNet()
    monkeypatch.setattr(N, "system_resolve", offline_resolve)
    monkeypatch.setattr(N, "doh_resolver", lambda proxy, **k: offline_resolve)
    monkeypatch.setattr(N, "open_connection", net)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.json").write_text(json.dumps({
        "profile": "douyin", "locale": "zh-CN",
        "providers": {"tts": {"provider": "openrouter", "usd_per_1k_chars": TTS_RATE},
                      "image": {"provider": "codex", "max_draws": 30},
                      "video": {"provider": "openrouter", "resolution": "720p"}},
        "budget": {"per_project_usd": 1.0, "min_balance_usd": 5.0}}), encoding="utf-8")
    (ws / ".env").write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")
    project = ws / "projects" / "oil"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"version": 2, "meta": {"title": "t"}, "assets": {},
                                                      "tracks": []}), encoding="utf-8")
    return Env(ws=ws, project=project, tmp=tmp_path, net=net)


# ------------------------------------------------------------------ the contract with tools.py
def test_every_provider_takes_the_keywords_tools_sends():
    calls = {
        "speak": dict(lines=["一"], gap_s=0.22),
        "capture": dict(url="https://example.com", match="x", id="ev1"),
        "draw": dict(id="a", prompt="p", style_ref_asset="b", size="9:16"),
        "animate": dict(id="a", image_asset="b", motion="m", seconds=4.0, camera="push"),
        "import_asset": dict(id="a", source="x.png", kind="image"),
        "assets": {},
    }
    for name, kwargs in calls.items():
        fn = getattr(P, name)
        inspect.signature(fn).bind(Path("."), **kwargs)          # raises TypeError on a mismatch
    # tools.py drops None values: every optional keyword needs a default
    inspect.signature(P.capture).bind(Path("."), url="https://e.com", id="ev1")
    inspect.signature(P.animate).bind(Path("."), id="a", image_asset="b", motion="m", seconds=4)


def test_tools_return_text_and_error_flag_and_never_raise(env):
    text, err = P.import_asset(env.project, id="../evil", source="x.png")
    assert err and "must be 1-64" in text
    text, err = P.speak(env.tmp / "no-such-project", lines=["一"])
    assert err and "does not exist" in text
    text, err = P.assets(env.project)
    assert not err and "none yet" in text


def test_check_id_rules():
    for good in ("ev_01", "Hero-2", "a", "x" * 64):
        assert CFG.check_id(good) == good
    for bad in ("", "../x", "a b", "-lead", "x" * 65, None, 5, "a/b", "ä"):
        with pytest.raises(P.ProviderError):
            CFG.check_id(bad)


def test_redact_removes_known_values_and_key_shapes(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "tok-1234567890")
    text = (f"a {KEY} b Bearer abcdefghijklmnop c mysecretvalue123 d sk-ant-api03-abcdefghijk e tok-1234567890 "
            "f sk-proj-abcdefghijklmnopqrstuvwxyz")
    out = P.redact(text, ["mysecretvalue123"])
    for leaked in (KEY, "abcdefghijklmnop", "mysecretvalue123", "sk-ant-api03", "tok-1234567890", "sk-proj-abc"):
        assert leaked not in out
    assert out.count("[redacted]") == 6 and out.startswith("a [redacted] b Bearer [redacted]")


def test_context_budget_from_workspace_and_env_override(env, monkeypatch):
    ctx = P.context(env.project)
    assert ctx.budget == {"per_project_usd": 1.0, "min_balance_usd": 5.0}
    assert ctx.ledger_path == env.ws / "ledger.jsonl" and ctx.cache_dir == env.ws / ".cache"
    assert ctx.project_key == "projects/oil" and ctx.key("OPENROUTER_API_KEY") == KEY
    assert ctx.providers["tts"]["model"] == "qwen/qwen-audio-3.0-tts-plus"   # defaults fill what workspace.json leaves
    assert ctx.providers["tts"]["voice"] is None                    # out; the voice follows the locale (speak)
    monkeypatch.setenv("REELSMITH_BUDGET_USD", "0.25")
    assert P.context(env.project).budget["per_project_usd"] == 0.25
    monkeypatch.setenv("REELSMITH_BUDGET_USD", "lots")
    text, err = P.speak(env.project, lines=["一"])
    assert err and "REELSMITH_BUDGET_USD" in text
    monkeypatch.delenv("REELSMITH_BUDGET_USD")
    env.config(budget={"per_project_usd": -1})
    text, err = P.assets(env.project)
    assert err and "budget.per_project_usd" in text


def test_project_outside_a_workspace_keeps_its_own_ledger(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "reelsmith.ops", None)
    p = tmp_path / "loose"
    p.mkdir()
    ctx = P.context(p)
    assert ctx.workspace is None and ctx.ledger_path == p / "ledger.jsonl" and ctx.cache_dir == p / ".cache"
    assert ctx.budget["per_project_usd"] == 1.0


# ------------------------------------------------------------------ ledger
def test_ledger_counts_pending_calls_at_estimate_and_settled_ones_at_cost(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    a = led.reserve(project="p", tool="animate", provider="x", est_usd=0.11, budget_usd=1.0)
    assert led.spent("p") == 0.11
    led.mark(a, "submitted", job="j1")
    assert led.spent("p") == 0.11 and led.in_flight() == 0.11
    led.settle(a, "success", 0.09)
    b = led.reserve(project="p", tool="speak", provider="x", est_usd=0.05, budget_usd=1.0)
    led.settle(b, "failed", 0.0)
    led.reserve(project="other", tool="speak", provider="x", est_usd=0.3, budget_usd=1.0)
    assert led.spent("p") == 0.09 and led.spent("other") == 0.3 and led.in_flight() == 0.3
    (tmp_path / "ledger.jsonl").open("a", encoding="utf-8").write("not json\n[1]\n")
    assert led.spent("p") == 0.09                                   # a torn line is skipped, not fatal


def test_ledger_refuses_over_budget_and_records_it(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.reserve(project="p", tool="animate", provider="x", est_usd=0.6, budget_usd=1.0)
    with pytest.raises(BudgetRefused) as exc:
        led.reserve(project="p", tool="animate", provider="x", est_usd=0.6, budget_usd=1.0)
    assert "budget of $1.00" in str(exc.value) and "per_project_usd" in str(exc.value)
    last = led.rows()[-1]
    assert last["status"] == "refused" and last["cost_usd"] == 0.0 and led.spent("p") == 0.6


def test_ledger_balance_floor_counts_money_still_in_flight(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    kw = dict(project="p", tool="animate", provider="x", est_usd=0.2, budget_usd=10.0, min_balance_usd=5.0,
              balance=lambda: 5.5)
    led.reserve(**kw)                       # 5.5 - 0.0 - 0.2 = 5.3
    led.reserve(**kw)                       # 5.5 - 0.2 - 0.2 = 5.1
    with pytest.raises(BudgetRefused) as exc:
        led.reserve(**kw)                   # 5.5 - 0.4 - 0.2 = 4.9 < 5
    assert "$5.00 floor" in str(exc.value) and "in flight" in str(exc.value)


def test_ledger_refuses_when_the_balance_cannot_be_read(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")

    def broken():
        raise OSError("dns")

    def bad_key():
        raise OR.ApiError(401, "No auth credentials found")
    with pytest.raises(BudgetRefused, match="try again in a minute"):
        led.reserve(project="p", tool="t", provider="x", est_usd=0.1, budget_usd=1, min_balance_usd=5,
                    balance=broken)
    with pytest.raises(BudgetRefused, match="check the provider key"):
        led.reserve(project="p", tool="t", provider="x", est_usd=0.1, budget_usd=1, min_balance_usd=5,
                    balance=bad_key)
    assert led.spent("p") == 0.0


def test_ledger_parallel_reservations_never_pass_the_budget(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    results = []

    def one():
        try:
            led.reserve(project="p", tool="animate", provider="x", est_usd=0.1, budget_usd=0.55)
            results.append("ok")
        except BudgetRefused:
            results.append("refused")
    threads = [threading.Thread(target=one) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 5 and results.count("refused") == 15
    assert led.spent("p") == 0.5


def test_ledger_lock_holds_across_processes(tmp_path):
    script = tmp_path / "reserve.py"
    script.write_text(
        "import sys\nfrom reelsmith.providers.ledger import Ledger, BudgetRefused\n"
        "led = Ledger(sys.argv[1]); n = 0\n"
        "for _ in range(6):\n"
        "    try:\n"
        "        led.reserve(project='p', tool='t', provider='x', est_usd=0.1, budget_usd=0.85); n += 1\n"
        "    except BudgetRefused:\n"
        "        pass\n"
        "print(n)\n", encoding="utf-8")
    path = tmp_path / "ledger.jsonl"
    procs = [subprocess.Popen([sys.executable, str(script), str(path)], stdout=subprocess.PIPE, text=True)
             for _ in range(3)]
    made = sum(int(p.communicate(timeout=60)[0].strip()) for p in procs)
    assert made == 8 and Ledger(path).spent("p") == 0.8


# ------------------------------------------------------------------ processes
def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259                        # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_run_tree_timeout_kills_the_children_too(tmp_path):
    pidfile = tmp_path / "child.pid"
    tree = ("import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "open(sys.argv[1], 'w').write(str(c.pid))\n"
            "time.sleep(120)\n")
    started = time.monotonic()
    _, _, _, timed = CFG.run_tree([sys.executable, "-c", tree, str(pidfile)], timeout=4)
    assert timed and time.monotonic() - started < 25          # nothing left holding the pipes open
    child = int(pidfile.read_text())
    end = time.monotonic() + 20
    while alive(child) and time.monotonic() < end:
        time.sleep(0.1)
    assert not alive(child)


# ------------------------------------------------------------------ OpenRouter client
class FakeHTTP:
    """urlopen stand-in: answers by path, records what was sent."""

    def __init__(self, routes):
        self.routes, self.sent = routes, []

    def __call__(self, req, timeout=None):
        self.sent.append(req)
        answer = self.routes[req.full_url]
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(answer if isinstance(answer, bytes) else json.dumps(answer).encode())


def http_error(url, code, body: str):
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(body.encode()))


def test_openrouter_sends_the_key_only_to_its_own_host_and_scrubs_errors():
    base = OR.API
    fake = FakeHTTP({base + "/credits": {"data": {"total_credits": 20, "total_usage": 7.5}},
                     "https://cdn.example.com/v.mp4": b"bytes",
                     base + "/audio/speech": http_error(base + "/audio/speech", 401, f'{{"error": "bad key {KEY}"}}'),
                     base + "/videos": urllib.error.URLError(socket.timeout("timed out"))})
    client = OR.OpenRouter(KEY, opener=fake)
    assert client.balance() == 12.5
    assert fake.sent[-1].get_header("Authorization") == "Bearer " + KEY
    assert client.request("https://cdn.example.com/v.mp4", raw=True) == b"bytes"
    assert fake.sent[-1].get_header("Authorization") is None
    with pytest.raises(OR.ApiError) as exc:
        client.speech({"input": "x"})
    assert exc.value.code == 401 and KEY not in str(exc.value) and "[redacted]" in str(exc.value)
    with pytest.raises(OR.Unreachable) as exc:
        client.submit_video({})
    assert exc.value.maybe_sent and A.maybe_accepted(exc.value)
    with pytest.raises(P.ProviderError, match="no OPENROUTER_API_KEY"):
        OR.OpenRouter("")


def test_maybe_accepted_only_when_the_job_may_have_been_taken():
    assert A.maybe_accepted(OR.ApiError(504, "gateway timeout"))
    assert not A.maybe_accepted(OR.ApiError(502, "bad gateway"))
    assert not A.maybe_accepted(OR.ApiError(400, "bad request"))
    assert not A.maybe_accepted(OR.Unreachable("dns", maybe_sent=False))
    assert A.maybe_accepted(TimeoutError()) and A.maybe_accepted(ConnectionResetError())
    assert not A.maybe_accepted(ConnectionRefusedError())


def test_speech_body_steers_qwen_with_words_and_others_with_numbers():
    qwen = OR.speech_body("一句话", {"model": "qwen/qwen-audio-3.0-tts-plus", "voice": "v"}, 1.10)
    assert "speed" not in qwen and "放慢" in qwen["instructions"] and qwen["voice"] == "v"
    assert "instructions" not in OR.speech_body("x", {"model": "qwen/q"}, 1.0)
    mm = OR.speech_body("x", {"model": "minimax/speech-2.8", "speed_scale": 0.8}, 1.25, emotion="happy")
    assert "speed" not in mm                                        # 1.25 * 0.8 = 1.0: no knob needed
    assert mm["emotion"] == "happy" and "happy" in mm["instructions"]
    assert OR.speech_body("x", {"model": "minimax/speech-2.8"}, 1.35)["speed"] == 1.35


def test_synthesize_drops_an_unknown_emotion_and_does_not_retry_a_bad_key():
    class Client:
        key = KEY

        def __init__(self, answers):
            self.answers, self.bodies = list(answers), []

        def speech(self, body):
            self.bodies.append(dict(body))
            answer = self.answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
    ok = Client([OR.ApiError(400, "unknown field emotion"), b"x" * 600])
    assert OR.synthesize(ok, "hi", {"model": "minimax/m"}, 1.0, "sad", sleep=lambda s: None) == b"x" * 600
    assert "emotion" in ok.bodies[0] and "emotion" not in ok.bodies[1]
    bad = Client([OR.ApiError(401, f"bad {KEY}"), b"x" * 600])
    with pytest.raises(P.ProviderError) as exc:
        OR.synthesize(bad, "hi", {"model": "qwen/q"}, 1.0, sleep=lambda s: None)
    assert len(bad.bodies) == 1 and KEY not in str(exc.value)
    flaky = Client([OR.ApiError(429, "slow down"), b"short", b"x" * 600])
    with pytest.raises(P.ProviderError, match="empty audio"):
        OR.synthesize(flaky, "hi", {"model": "qwen/q"}, 1.0, sleep=lambda s: None)
    assert len(flaky.bodies) == 2


# ------------------------------------------------------------------ speak
class FakeTTS(TTS.TTSEngine):
    name = "fake"

    def __init__(self, fail=(), balance=None, leak="", identity="fake|v1", costs=None):
        self.calls, self.fail, self.leak, self._identity = [], set(fail), leak, identity
        self.has_balance, self._balance = balance is not None, balance
        self.costs = costs or {}

    def identity(self):
        return self._identity

    def synth(self, text, speed, emotion):
        self.calls.append((text, speed, emotion))
        if text in self.fail:
            raise P.ProviderError(f"the TTS refused {text!r} {self.leak}")
        audio = OR.Speech(tone_mp3(0.4 + 0.1 * (len(text) % 3), 300 + 40 * len(text)))
        audio.cost = self.costs.get(text)
        return audio

    def balance(self):
        return self._balance


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


@needs_ffmpeg
def test_speak_writes_voice_json_and_sets_the_project_voice(env):
    engine = FakeTTS()
    text, err = P.speak(env.project, lines=["第一句话。", {"text": "第二句", "pace": "slower", "emotion": "惊讶"},
                                            {"text": "三", "pace": 0.9}], gap_s=0.3, engine=engine)
    assert not err, text
    voice = json.loads((env.project / "voice" / "voice.json").read_text(encoding="utf-8"))
    assert voice["file"] == "voice/voice.wav" and (env.project / "voice" / "voice.wav").is_file()
    assert [ln["i"] for ln in voice["lines"]] == [1, 2, 3]
    assert [ln["text"] for ln in voice["lines"]] == ["第一句话。", "第二句", "三"]
    assert set(voice["lines"][0]) == {"i", "text", "t0", "t1"}
    first, second, third = voice["lines"]
    assert first["t0"] == 0.0 and first["t1"] > 0.25
    assert second["t0"] == pytest.approx(first["t1"] + 0.3, abs=0.002)
    assert third["t0"] == pytest.approx(second["t1"] + 0.3, abs=0.002)
    assert voice["duration_s"] == third["t1"] == pytest.approx(wav_seconds(env.project / "voice" / "voice.wav"),
                                                               abs=0.002)
    assert voice["lufs"] is not None and abs(voice["lufs"] - (-12.0)) < 2.5      # every line levelled
    assert read_project(env.project)["voice"] == "voice/voice.json"
    assert sorted(c[1] for c in engine.calls) == sorted([TTS.PACE["normal"], TTS.PACE["slower"],
                                                         round(TTS.PACE["normal"] * 0.9, 3)])
    assert ("第二句", TTS.PACE["slower"], "惊讶") in engine.calls
    assert '[2] ' in text and "line:N" in text and "3 line(s) newly synthesized" in text
    rows = ledger_rows(env.ws)
    assert [r["status"] for r in rows] == ["reserved", "success"]
    chars = len("第一句话。") + len("第二句") + len("三")
    assert rows[-1]["cost_usd"] == pytest.approx(chars / 1000 * TTS_RATE) and rows[-1]["tool"] == "speak"
    assert rows[-1]["project"] == "projects/oil"


@needs_ffmpeg
def test_speak_cache_hits_cost_nothing_and_only_changed_lines_pay(env):
    lines = ["油价又涨了。", "这次涨多少？", "每升一毛五。"]
    first = FakeTTS()
    assert not P.speak(env.project, lines=lines, engine=first)[1]
    rows_after_first = ledger_rows(env.ws)
    again = FakeTTS()
    text, err = P.speak(env.project, lines=lines, engine=again)
    assert not err and again.calls == [] and "0 line(s) newly synthesized" in text and "3 from cache" in text
    assert ledger_rows(env.ws) == rows_after_first                  # nothing reserved, nothing spent
    changed = FakeTTS()
    text, err = P.speak(env.project, lines=[lines[0], "这次涨了多少钱？", lines[2]], engine=changed)
    assert not err and [c[0] for c in changed.calls] == ["这次涨了多少钱？"]
    assert ledger_rows(env.ws)[-1]["chars"] == len("这次涨了多少钱？")
    paced = FakeTTS()
    assert not P.speak(env.project, lines=[lines[0], lines[1], {"text": lines[2], "pace": "faster"}],
                       engine=paced)[1]
    assert [c[0] for c in paced.calls] == [lines[2]]                 # a new pace is a new line
    voiced = FakeTTS(identity="fake|other-voice")
    assert not P.speak(env.project, lines=lines[:1], engine=voiced)[1]
    assert len(voiced.calls) == 1                                    # a new voice is new audio


@needs_ffmpeg
def test_speak_keeps_a_voice_the_project_already_points_at(env):
    env.set_project(voice="voice/take2.json")
    text, err = P.speak(env.project, lines=["一句。"], engine=FakeTTS())
    assert not err and "still points at 'voice/take2.json'" in text
    assert read_project(env.project)["voice"] == "voice/take2.json"


@needs_ffmpeg
def test_speak_refuses_over_budget_before_any_call(env):
    env.config(budget={"per_project_usd": 0.01})
    engine = FakeTTS()
    text, err = P.speak(env.project, lines=["这一句有十个字左右吧。"], engine=engine)
    assert err and "budget" in text and engine.calls == []
    assert not (env.project / "voice" / "voice.wav").exists()
    assert ledger_rows(env.ws)[-1]["status"] == "refused"


@needs_ffmpeg
def test_speak_refuses_under_the_balance_floor(env):
    engine = FakeTTS(balance=5.05)
    text, err = P.speak(env.project, lines=["这一句有十个字左右吧。"], engine=engine)   # est $0.11
    assert err and "floor" in text and engine.calls == []
    assert P.speak(env.project, lines=["短"], engine=FakeTTS(balance=5.05))[1] is False   # est $0.01 fits


@needs_ffmpeg
def test_speak_failed_line_is_reported_and_the_rest_stay_cached(env):
    engine = FakeTTS(fail={"坏句子"})
    text, err = P.speak(env.project, lines=["好句子一", "坏句子", "好句子二"], engine=engine)
    assert err and "1 of 3 new lines failed (line 2)" in text and "retry" in text
    assert not (env.project / "voice" / "voice.json").exists()
    last = ledger_rows(env.ws)[-1]
    assert last["status"] == "partial" and last["cost_usd"] == pytest.approx(8 / 1000 * TTS_RATE)
    retry = FakeTTS()
    assert not P.speak(env.project, lines=["好句子一", "坏句子", "好句子二"], engine=retry)[1]
    assert [c[0] for c in retry.calls] == ["坏句子"]


@pytest.mark.parametrize("lines, gap, says", [
    ([], 0.2, "non-empty list"),
    ("一句", 0.2, "non-empty list"),
    (["  "], 0.2, "line 1 is empty"),
    (["ok", {"text": "x", "speed": 1.2}], 0.2, "unknown field"),
    ([{"text": "x", "pace": "fast"}], 0.2, "pace must be"),
    ([{"text": "x", "pace": 3}], 0.2, "pace must be"),
    (["x" * 401], 0.2, "split it"),
    ([42], 0.2, "give a string"),
    (["ok"], -0.1, "gap_s must be between"),
    (["ok"], "0.2", "gap_s must be a number"),
    (["x"] * 201, 0.2, "too many"),
])
def test_speak_validates_its_input(env, lines, gap, says):
    engine = FakeTTS()
    text, err = P.speak(env.project, lines=lines, gap_s=gap, engine=engine)
    assert err and says in text and engine.calls == []


@needs_ffmpeg
def test_speak_never_shows_the_key(env, monkeypatch):
    engine = FakeTTS(fail={"一"}, leak=f"(sent with {KEY})")
    text, err = P.speak(env.project, lines=["一"], engine=engine)
    assert err and KEY not in text and "[redacted]" in text
    assert KEY not in everything_written(env.ws)

    def answers(req, timeout=None):                                 # the real client, a fake network
        if req.full_url.endswith("/credits"):
            return io.BytesIO(json.dumps({"data": {"total_credits": 50, "total_usage": 1}}).encode())
        raise http_error(req.full_url, 401, json.dumps({"error": "invalid key " + req.get_header("Authorization")}))
    monkeypatch.setitem(TTS.ENGINES, "openrouter", lambda ctx, cfg: TTS.OpenRouterTTS(
        cfg, ctx.key(OR.KEY_NAME), client=OR.OpenRouter(ctx.key(OR.KEY_NAME), opener=answers)))
    text, err = P.speak(env.project, lines=["二"])
    assert err and "HTTP 401" in text and KEY not in text
    assert KEY not in everything_written(env.ws)


@needs_ffmpeg
def test_speak_through_the_agent_tool(env, monkeypatch):
    from reelsmith import tools as T
    engine = FakeTTS()
    monkeypatch.setitem(TTS.ENGINES, "openrouter", lambda ctx, cfg: engine)
    r = T.speak(str(env.project), '["一。", {"text": "二", "pace": 0.95}]')
    assert r.ok, r
    assert sorted(c[0] for c in engine.calls) == ["一。", "二"]       # synthesized in parallel
    assert read_project(env.project)["voice"] == "voice/voice.json"


@needs_ffmpeg
def test_speak_records_a_reported_cost_and_marks_estimates(env):
    """The ledger must not record the estimate as if it were the cost."""
    text, err = P.speak(env.project, lines=["一句。", "两句。"], engine=FakeTTS(costs={"一句。": 0.0021, "两句。": 0.0019}))
    assert not err and "$0.0040 as the provider reported" in text
    row = ledger_rows(env.ws)[-1]
    assert row["cost_source"] == "provider" and row["cost_usd"] == pytest.approx(0.004)
    text, err = P.speak(env.project, lines=["一句。", "三句话。"], engine=FakeTTS(costs={}))
    assert not err and "(est. $0.0400)" in text                      # 4 chars at $10 per 1k
    row = ledger_rows(env.ws)[-1]
    assert row["cost_source"] == "estimate" and row["cost_usd"] == pytest.approx(0.04)
    P.speak(env.project, lines=["四", "五"], engine=FakeTTS(costs={"四": 0.001}))
    row = ledger_rows(env.ws)[-1]
    assert row["cost_source"] == "provider+estimate" and row["cost_usd"] == pytest.approx(0.011)
    listing, _ = P.assets(env.project)
    assert "$0.055 of the $1.00" in listing and "$0.050 of it is an estimate" in listing
    assert "usd_per_1k_chars" in listing


def test_openrouter_speech_reads_a_cost_header_when_there_is_one():
    class Answer(io.BytesIO):
        def __init__(self, body, headers):
            super().__init__(body)
            self.headers = headers
    sent = []

    def opener(req, timeout=None):
        sent.append(req)
        return Answer(b"x" * 600, {"Content-Type": "audio/mpeg", "X-OpenRouter-Cost": "0.00042"} if len(sent) == 1
                      else {"Content-Type": "audio/mpeg"})
    client = OR.OpenRouter(KEY, opener=opener)
    audio = client.speech({"input": "x"})
    assert audio == b"x" * 600 and audio.cost == pytest.approx(0.00042)
    assert client.speech({"input": "y"}).cost is None
    assert OR.reported_cost({"x-cost": "nan"}) is None and OR.reported_cost({"x-cost": "-1"}) is None


# ------------------------------------------------------------------ capture
FOUND = {"found": True, "title": "示例日报：汽油每吨上调 205 元", "site": "示例日报", "excerpt": "汽油每吨上调 205 元，柴油…",
         "sentence": "汽油每吨上调 205 元，柴油每吨上调 195 元。", "font_px": 16,
         "crop": {"x": 0, "y": 300.5, "width": 430, "height": 260},
         "match": {"x": 20.4, "y": 101.2, "width": 180.3, "height": 24.0}}


def through(proxy: str, url: str) -> bytes:
    """What a browser does first: ask its proxy for a tunnel to url's host. The proxy's status line."""
    parts = urllib.parse.urlsplit(url)
    host, port = urllib.parse.urlsplit(proxy).hostname, urllib.parse.urlsplit(proxy).port
    with socket.create_connection((host, port), timeout=5) as s:
        target = f"{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}"
        s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        return s.recv(4096).split(b"\r\n")[0]


class FakeBrowserWorld:
    """sync_playwright stand-in: records the launch, context and screenshot; scripts each browser session. Like a
    browser, every address the page opens (the page, where it lands, `loads`) goes through the launch proxy."""

    def __init__(self, info=None, status=200, landed=None, loads=(), missing=(), launch_error=None):
        self.info, self.status, self.landed, self.loads = info or FOUND, status, landed, list(loads)
        self.launches, self.contexts, self.shots, self.closed, self.evaluated = [], [], [], 0, []
        self.answers = []
        self.missing, self.launch_error, self.tried = set(missing), launch_error, []

    def __call__(self):
        world = self

        class Page:
            url = ""

            def set_default_timeout(self, ms):
                pass

            def goto(self, url, wait_until=None, timeout=None):
                proxy = world.launches[-1]["proxy"]["server"]
                for hop in [url] + ([world.landed] if world.landed else []):
                    said = through(proxy, hop)
                    world.answers.append((hop, said))
                    if not said.endswith(b" 200 Connection established"):
                        raise RuntimeError(f"net::ERR_TUNNEL_CONNECTION_FAILED at {hop}")
                for extra in world.loads:                  # subresources: a refusal does not stop the page
                    world.answers.append((extra, through(proxy, extra)))
                self.url = world.landed or url
                return types.SimpleNamespace(status=world.status)

            def wait_for_load_state(self, *a, **k):
                raise TimeoutError("never idle")

            def wait_for_timeout(self, ms):
                pass

            def evaluate(self, js, arg=None):
                if arg is None:
                    return True
                world.evaluated.append(arg)
                return json.loads(json.dumps(world.info))

            def screenshot(self, path, clip, full_page, animations):
                world.shots.append(dict(clip=clip, full_page=full_page))
                write_png(Path(path), round(clip["width"] * 3), round(clip["height"] * 3))

        class Browser:
            def new_context(self, **kw):
                world.contexts.append(kw)
                return types.SimpleNamespace(new_page=Page)

            def close(self):
                world.closed += 1

        class Chromium:
            def launch(self, channel=None, headless=None, proxy=None, args=None):
                world.tried.append(channel)
                if world.launch_error:
                    raise RuntimeError(world.launch_error)
                if channel in world.missing:            # Playwright's own words for a browser that is not there
                    raise RuntimeError(
                        f"BrowserType.launch: Chromium distribution '{channel}' is not found at /opt/{channel}\n"
                        f'Run "playwright install {channel}"' if channel else
                        "BrowserType.launch: Executable doesn't exist at /ms-playwright/chromium/chrome")
                world.launches.append({"channel": channel, "headless": headless, "proxy": proxy, "args": args})
                return Browser()

        class Manager:
            def __enter__(self):
                return types.SimpleNamespace(chromium=Chromium())

            def __exit__(self, *exc):
                return False
        return Manager()


def test_box_in_pixels_scales_css_to_png_pixels_and_stays_inside():
    info = {"match": {"x": 10.2, "y": 5.0, "width": 100.0, "height": 20.0}}
    assert C.box_in_pixels(info, (1290, 780)) == [31, 15, 300, 60]
    over = {"match": {"x": 400.0, "y": 250.0, "width": 100.0, "height": 40.0}}
    assert C.box_in_pixels(over, (1290, 780)) == [1200, 750, 90, 30]          # clipped at the image edge
    neg = {"match": {"x": -5.0, "y": -2.0, "width": 10.0, "height": 4.0}}
    assert C.box_in_pixels(neg, (100, 100)) == [0, 0, 15, 6]


def test_readable_width_is_where_the_text_reaches_40_px():
    assert C.readable_width(16, 1152) == 960                     # 16 CSS px at 3x = 48 px; 48 * 960 / 1152 = 40
    assert C.readable_width(0, 1152) is None and C.readable_width(16, 0) is None


def test_capture_on_a_fake_page_registers_evidence_with_the_box(env):
    world = FakeBrowserWorld()
    text, err = P.capture(env.project, url="https://www.example.org/x", match="汽油每吨上调 205 元", id="ev_price",
                          sync_playwright=world, proxy=None)
    assert not err, text
    launch = world.launches[0]
    assert launch["channel"] == "msedge" and launch["headless"] and world.closed == 1
    assert launch["proxy"]["server"].startswith("http://127.0.0.1:")              # always behind the guard
    assert C.LAUNCH_ARGS == launch["args"] and "disable_non_proxied_udp" in " ".join(launch["args"])
    ctxkw = world.contexts[0]
    # a 430 px layout: mobile emulation laid unfitted pages out at 980 px and the crops came out ~630 px wide
    assert ctxkw["viewport"]["width"] == 430 and ctxkw["device_scale_factor"] == 3 and ctxkw["is_mobile"] is False
    assert "Mobile" in ctxkw["user_agent"]
    assert world.evaluated == [["汽油每吨上调 205 元", C.PAD_CSS, C.MAX_BOX_LINES]]
    assert world.answers == [("https://www.example.org/x", b"HTTP/1.1 200 Connection established")]
    assert env.net.dialed == [(PUBLIC_IP, 443)]
    assert world.shots[0]["clip"] == FOUND["crop"] and world.shots[0]["full_page"]
    png = env.project / "assets" / "ev_price.png"
    assert CFG.header_size(png) == (1290, 780)
    entry = read_project(env.project)["assets"]["ev_price"]
    assert entry["kind"] == "evidence" and entry["path"] == "assets/ev_price.png"
    assert entry["box"] == [61, 304, 541, 72]                       # match x3, rounded
    assert entry["site"] == "示例日报" and entry["url"] == "https://www.example.org/x"
    assert "[61, 304, 541, 72]" in text and "meta.sources" in text
    assert "the sentence that holds the match" in text and "whole lines" in text
    assert "at least 451 px wide" in text                           # 40 * 541 / 48
    assert "Blocked" not in text
    assert not list((env.project / "assets").glob(".*"))            # no part file left behind


def test_capture_without_an_id_numbers_the_evidence(env):
    for n in (1, 2):
        text, err = P.capture(env.project, url="https://e.com/a", sync_playwright=FakeBrowserWorld(), proxy=None)
        assert not err and f"ev_0{n}" in text
    assert set(read_project(env.project)["assets"]) == {"ev_01", "ev_02"}


def test_capture_reports_a_miss_a_block_and_a_hidden_match(env):
    miss = {"found": False, "title": "Access denied", "site": "x.com", "heads": ["Sorry"],
            "text": "verify you are human"}
    text, err = P.capture(env.project, url="https://x.com/a", match="不存在的句子", id="ev1",
                          sync_playwright=FakeBrowserWorld(info=miss), proxy=None)
    assert err and "Did not find '不存在的句子'" in text and "Access denied" in text and "another source" in text
    text, err = P.capture(env.project, url="https://x.com/a", id="ev1", sync_playwright=FakeBrowserWorld(status=403),
                          proxy=None)
    assert err and "HTTP 403" in text
    hidden = dict(FOUND, crop={"x": 0, "y": 0, "width": 430, "height": 0})
    text, err = P.capture(env.project, url="https://x.com/a", id="ev1", sync_playwright=FakeBrowserWorld(info=hidden),
                          proxy=None)
    assert err and "no visible area" in text
    assert "ev1" not in read_project(env.project)["assets"] and not (env.project / "assets" / "ev1.png").exists()


def test_capture_goes_direct_when_the_proxy_is_down(env):
    env.net.refuse.add(("127.0.0.1", 3128))
    world = FakeBrowserWorld(landed="https://e.com/b")
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world,
                          proxy="http://127.0.0.1:3128")
    assert not err, text
    assert len(world.launches) == 2 and world.closed == 2 and "landed on https://e.com/b" in text
    assert world.answers[0] == ("https://e.com/a", b"HTTP/1.1 502 Bad Gateway")
    assert env.net.dialed == [("127.0.0.1", 3128), (PUBLIC_IP, 443), (PUBLIC_IP, 443)]


def test_capture_needs_an_http_outbound_proxy(env):
    world = FakeBrowserWorld()
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world,
                          proxy="socks5://127.0.0.1:1080")
    assert err and "http:// proxy" in text and "REELSMITH_PROXY" in text and world.launches == []


def test_capture_turns_browser_failures_into_advice(env):
    env.net.refuse.add((PUBLIC_IP, 443))
    text, err = P.capture(env.project, url="https://down.example/a", id="ev1", sync_playwright=FakeBrowserWorld(),
                          proxy=None)
    assert err and "ERR_TUNNEL_CONNECTION_FAILED" in text and "down.example" in text and "another source" in text


@pytest.mark.parametrize("missing, used", [({"msedge"}, "chrome"), ({"msedge", "chrome"}, None)])
def test_capture_falls_back_from_edge_to_chrome_to_playwrights_chromium(env, missing, used):
    world = FakeBrowserWorld(missing=missing)
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world, proxy=None)
    assert not err, text
    assert world.tried == list(C.CHANNELS[:C.CHANNELS.index(used) + 1])
    launch = world.launches[0]
    assert launch["channel"] == used and launch["headless"] and launch["args"] == C.LAUNCH_ARGS
    assert launch["proxy"]["server"].startswith("http://127.0.0.1:")              # still behind the guard
    assert world.contexts[0]["viewport"]["width"] == 430 and world.contexts[0]["device_scale_factor"] == 3
    assert "ev1" in read_project(env.project)["assets"]


def test_capture_without_any_browser_names_the_install_command(env):
    world = FakeBrowserWorld(missing={"msedge", "chrome", None})
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world, proxy=None)
    assert err and "python -m playwright install chromium" in text and "Edge" in text and "Chrome" in text
    assert world.tried == ["msedge", "chrome", None] and world.launches == [] and world.answers == []
    assert "ev1" not in read_project(env.project)["assets"]


def test_capture_does_not_skip_a_browser_that_fails_for_another_reason(env):
    world = FakeBrowserWorld(launch_error="BrowserType.launch: Target page, context or browser has been closed")
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world, proxy=None)
    assert err and "has been closed" in text and world.tried == ["msedge"]


@pytest.mark.parametrize("url, says", [("file:///etc/passwd", "http"), ("javascript:alert(1)", "http"),
                                       ("https://", "http"), ("", "http"),
                                       ("http://localtest.me/admin", "resolves to 127.0.0.1"),
                                       ("http://169.254.169.254.nip.io/latest/meta-data/", "169.254.169.254"),
                                       ("http://127.0.0.1:8000/", "local or private"),
                                       ("http://localhost:3000/", "this machine"),
                                       ("https://user:pw@e.com/", "user name or password"),
                                       ("https://nope.example/", "does not resolve")])
def test_capture_refuses_non_web_and_non_public_addresses_before_any_browser(env, url, says):
    world = FakeBrowserWorld()
    text, err = P.capture(env.project, url=url, id="ev1", sync_playwright=world, proxy=None)
    assert err and says in text and world.launches == [] and env.net.dialed == []


def test_capture_refuses_a_page_that_lands_on_a_private_address(env):
    world = FakeBrowserWorld(landed="http://intranet.example/admin")
    text, err = P.capture(env.project, url="https://e.com/go", id="ev1", sync_playwright=world, proxy=None)
    assert err and "refuses" in text and "intranet.example resolves to 10.0.0.5" in text
    assert ("10.0.0.5", 80) not in env.net.dialed and world.shots == []
    assert "ev1" not in read_project(env.project)["assets"]


def test_capture_blocks_what_a_page_loads_from_private_addresses(env):
    world = FakeBrowserWorld(loads=["http://127.0.0.1:9090/configs", "https://localtest.me/x.png",
                                    "https://cdn.example.com/a.css"])
    text, err = P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world, proxy=None)
    assert not err, text
    said = dict(world.answers)
    assert said["http://127.0.0.1:9090/configs"].startswith(b"HTTP/1.1 403")
    assert said["https://localtest.me/x.png"].startswith(b"HTTP/1.1 403")
    assert said["https://cdn.example.com/a.css"].endswith(b"200 Connection established")
    assert "Blocked while loading" in text and "127.0.0.1" in text and "localtest.me" in text
    assert all(addr == (PUBLIC_IP, 443) for addr in env.net.dialed)


def test_capture_will_not_overwrite_another_kind_of_asset(env):
    env.set_project(assets={"pump": {"path": "assets/pump.png", "kind": "image"}})
    world = FakeBrowserWorld()
    text, err = P.capture(env.project, url="https://e.com", id="pump", sync_playwright=world, proxy=None)
    assert err and "already names an image" in text and world.launches == []
    text, err = P.capture(env.project, url="https://e.com", id="Pump", sync_playwright=world, proxy=None)
    assert err and "only by case" in text


def test_speak_without_a_key_says_where_to_put_it(env):
    (env.ws / ".env").write_text("", encoding="utf-8")
    text, err = P.speak(env.project, lines=["一"])
    assert err and "OPENROUTER_API_KEY" in text and ".env" in text


# ------------------------------------------------------------------ draw
class FakePainter(D.ImageProvider):
    name = "fakepaint"

    def __init__(self, tmp: Path, kinds=("ok",), size=(1024, 1536), leak=""):
        self.tmp, self.kinds, self.size, self.leak = tmp, list(kinds), size, leak
        self.calls, self.forgot = [], []

    def draw(self, prompt, gen_size, workdir, ref, timeout):
        self.calls.append(dict(prompt=prompt, gen=gen_size, ref=ref, workdir=Path(workdir), timeout=timeout))
        kind = self.kinds.pop(0) if self.kinds else "ok"
        if kind != "ok":
            return D.Shot(kind, detail=f"codex said no {self.leak}", thread="t-" + kind)
        png = write_png(self.tmp / f"gen-{len(self.calls)}.png", *self.size)
        return D.Shot("ok", png, 1.5, detail=f"done {self.leak}", thread="t-ok", events="{}")

    def forget(self, shot):
        self.forgot.append(shot.thread)


@needs_ffmpeg
def test_draw_fits_the_picture_and_registers_an_image(env):
    painter = FakePainter(env.tmp, leak=KEY)
    text, err = P.draw(env.project, id="pump", prompt="加油枪特写，黄昏", size="9:16", provider=painter)
    assert not err, text
    assert CFG.header_size(env.project / "assets" / "pump.png") == (1080, 1920)
    entry = read_project(env.project)["assets"]["pump"]
    assert entry == {"path": "assets/pump.png", "kind": "image", "note": "加油枪特写，黄昏"}
    call = painter.calls[0]
    assert call["gen"] == (1024, 1536) and call["ref"] is None and not call["workdir"].exists()
    assert painter.forgot == ["t-ok"]
    rows = [r for r in ledger_rows(env.ws) if r["tool"] == "draw"]
    assert [r["status"] for r in rows] == ["reserved", "ok"] and rows[0]["id"] == rows[1]["id"]
    assert sum(r["cost_usd"] for r in rows) == 0.0
    log = (env.ws / ".cache" / "draw.log").read_text(encoding="utf-8")
    assert "done" in log and KEY not in log
    assert KEY not in text and "codex said" not in text


@needs_ffmpeg
def test_draw_with_a_style_reference_and_a_custom_size(env):
    write_png(env.project / "assets" / "host.png", 512, 768)
    env.set_project(assets={"host": {"path": "assets/host.png", "kind": "image"}})
    painter = FakePainter(env.tmp, size=(1536, 1024))
    text, err = P.draw(env.project, id="wide", prompt="同一画风的街景", style_ref_asset="host", size=[1600, 900],
                       provider=painter)
    assert not err, text
    assert painter.calls[0]["gen"] == (1536, 1024) and painter.calls[0]["ref"] is not None
    assert CFG.header_size(env.project / "assets" / "wide.png") == (1600, 900)


def test_draw_retries_a_blank_once_and_hides_the_providers_words(env):
    painter = FakePainter(env.tmp, kinds=("noimage", "noimage"), leak=KEY)
    text, err = P.draw(env.project, id="pump", prompt="x", provider=painter)
    assert err and len(painter.calls) == 2 and "no picture came out" in text
    assert "codex said" not in text and KEY not in text
    assert "pump" not in read_project(env.project)["assets"]


def test_draw_stops_trying_once_the_provider_is_logged_out(env):
    painter = FakePainter(env.tmp, kinds=("auth",))
    text, err = P.draw(env.project, id="a", prompt="x", provider=painter)
    assert err and len(painter.calls) == 1 and "logged out" in text
    text, err = P.draw(env.project, id="b", prompt="x", provider=painter)
    assert err and len(painter.calls) == 1 and "cannot draw right now" in text and "editor" in text


@needs_ffmpeg
def test_draw_counts_tries_against_max_draws(env):
    env.config(providers={"image": {"max_draws": 3}})
    painter = FakePainter(env.tmp, kinds=("noimage", "noimage", "ok", "ok"))
    assert P.draw(env.project, id="a", prompt="x", provider=painter)[1]            # 2 tries
    assert not P.draw(env.project, id="b", prompt="x", provider=painter)[1]        # the 3rd
    text, err = P.draw(env.project, id="c", prompt="x", provider=painter)
    assert err and "used its 3 drawing tries" in text and len(painter.calls) == 3


@pytest.mark.parametrize("kwargs, says", [
    (dict(id="a", prompt=""), "prompt must describe"),
    (dict(id="a", prompt="x" * 2001), "prompt must describe"),
    (dict(id="a", prompt="x", size="7:5"), "size must be"),
    (dict(id="a", prompt="x", size=[100, 100]), "size must be"),
    (dict(id="a", prompt="x", style_ref_asset="ghost"), "must be an image asset"),
    (dict(id="a b", prompt="x"), "must be 1-64"),
])
def test_draw_validates_before_any_try(env, kwargs, says):
    painter = FakePainter(env.tmp)
    text, err = P.draw(env.project, provider=painter, **kwargs)
    assert err and says in text and painter.calls == []


def test_parse_size_aspects_and_pixels():
    assert D.parse_size(None) == ((1024, 1536), (1080, 1920))
    assert D.parse_size("1:1") == ((1024, 1024), (1080, 1080))
    assert D.parse_size("1200x800") == ((1536, 1024), (1200, 800))
    assert D.parse_size([720, 1280]) == ((1024, 1536), (720, 1280))


def test_codex_runs_locked_down_and_only_its_own_original_counts(tmp_path):
    home = tmp_path / "codex-home"
    thread = "0b0b0b0b-1111-2222-3333-444455556666"
    seen = {}

    def run(cmd, cwd=None, timeout=None, stdin=None, no_window=False):
        seen.update(cmd=cmd, cwd=cwd, stdin=stdin.decode("utf-8"))
        write_png(home / "generated_images" / thread / "img.png", 1024, 1536)
        write_png(Path(cwd) / "not-ours.png", 2000, 2000)
        events = [{"type": "thread.started", "thread_id": thread},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}]
        return 0, "\n".join(json.dumps(e) for e in events), "", False
    codex = D.Codex(exe_path=tmp_path / "codex.exe", home=home, run=run, model="gpt-x")
    ref = tmp_path / "ref.jpg"
    shot = codex.draw("一只猫", (1024, 1536), tmp_path / "work", ref, 60)
    assert shot.kind == "ok" and shot.png == home / "generated_images" / thread / "img.png"
    cmd = seen["cmd"]
    assert cmd[1] == "exec" and "--ignore-user-config" in cmd and cmd[cmd.index("-s") + 1] == "read-only"
    assert 'web_search="disabled"' in cmd and "features.shell_tool=false" in cmd and "--ephemeral" in cmd
    assert cmd.index("-") < cmd.index("-i") and cmd[-1] == str(ref) and cmd[cmd.index("-m") + 1] == "gpt-x"
    assert "一只猫" in seen["stdin"] and "image_gen" in seen["stdin"] and D.STYLE_REF_NOTE in seen["stdin"]
    codex.forget(shot)
    assert not (home / "generated_images" / thread).exists()


def test_draw_prompt_wraps_any_description_in_english():
    # the wrapper is ours, the description the agent's, in whatever language the film is in
    text = D.draw_prompt("a cat on a windowsill, photo", (1536, 1024), ref=True)
    assert text.isascii() and "one landscape image (1536x1024)" in text and "image_gen" in text
    assert "Picture:\na cat on a windowsill, photo" in text and text.rstrip().endswith(D.STYLE_REF_NOTE)
    assert "portrait image" in D.draw_prompt("x", (1024, 1536)) and "square image" in D.draw_prompt("x", (1024, 1024))
    zh = D.draw_prompt("一只猫", (1024, 1024))
    assert zh.replace("一只猫", "").isascii() and D.STYLE_REF_NOTE not in zh


def test_codex_failures_are_classified(tmp_path):
    def answering(final):
        def run(cmd, cwd=None, timeout=None, stdin=None, no_window=False):
            return 1, json.dumps({"type": "turn.failed", "error": {"message": final}}), "", False
        return run
    for final, kind in (("401 Unauthorized: please log in again", "auth"), ("You've hit your usage limit", "quota"),
                        ("I could not draw that", "noimage")):
        codex = D.Codex(exe_path=tmp_path / "codex.exe", home=tmp_path, run=answering(final), model="")
        assert codex.draw("x", (1024, 1024), tmp_path / "w", None, 60).kind == kind
    slow = D.Codex(exe_path=tmp_path / "codex.exe", home=tmp_path, model="",
                   run=lambda cmd, **kw: (None, "", "", True))
    assert slow.draw("x", (1024, 1024), tmp_path / "w", None, 1).kind == "timeout"


def test_codex_missing_is_a_kind_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "find_codex", lambda: None)              # never the real codex.exe from a test
    never = lambda *a, **k: pytest.fail("ran a process")             # noqa: E731
    assert D.Codex(home=tmp_path, run=never).draw("x", (1024, 1024), tmp_path, None, 1).kind == "missing"


# ------------------------------------------------------------------ animate
class Killed(BaseException):
    """The process dying mid-call: no handler in the provider may swallow it."""


class FakeVideo(A.VideoAPI):
    name = "openrouter"

    def __init__(self, balance=50.0, statuses=("completed",), cost=0.104, submit_error=None, job="job-1",
                 hold=None):
        self.bal, self.statuses, self.cost, self.submit_error = balance, list(statuses), cost, submit_error
        self.job, self.hold = job, hold
        self.submits, self.polls, self.fetches = [], [], []
        self.submitting = threading.Event()

    def balance(self):
        return self.bal

    def submit(self, body):
        self.submits.append(body)
        self.submitting.set()
        if self.hold:
            self.hold.wait(10)
        if self.submit_error:
            raise self.submit_error
        return {"id": self.job, "polling_url": f"https://openrouter.ai/api/v1/videos/{self.job}"}

    def poll(self, job, polling_url):
        self.polls.append((job, polling_url))
        status = self.statuses.pop(0) if self.statuses else "in_progress"
        if isinstance(status, BaseException):
            raise status
        st = {"status": status}
        if status == "completed":
            st["usage"] = {"cost": self.cost}
            st["unsigned_urls"] = ["https://cdn.example.com/out.mp4"]
        return st

    def fetch(self, job, done):
        self.fetches.append(job)
        return clip_mp4()


@pytest.fixture
def picture(env):
    write_png(env.project / "assets" / "pump.png", 360, 640)
    env.set_project(assets={"pump": {"path": "assets/pump.png", "kind": "image"}})
    return env


def animate_rows(ws):
    return [r for r in ledger_rows(ws) if r["tool"] == "animate"]


def no_sleep(s):
    pass


@needs_ffmpeg
def test_animate_reserves_submits_and_registers_a_silent_clip(picture):
    api = FakeVideo(statuses=("pending", "in_progress", "completed"))
    text, err = P.animate(picture.project, id="pump_v", image_asset="pump", motion="油从枪口滴落", seconds=4,
                          camera="pull", api=api, sleep=no_sleep)
    assert not err, text
    body = api.submits[0]
    assert body["model"] == "bytedance/seedance-1-5-pro" and body["duration"] == 4 and body["resolution"] == "720p"
    assert body["aspect_ratio"] == "9:16" and body["generate_audio"] is False
    assert body["frame_images"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "油从枪口滴落" in body["prompt"] and A.CAMERA["pull"] in body["prompt"]
    assert len(api.polls) == 3 and api.polls[0] == ("job-1", "https://openrouter.ai/api/v1/videos/job-1")
    out = picture.project / "assets" / "pump_v.mp4"
    probe = CFG.probe(out)
    assert [s["codec_type"] for s in probe["streams"]] == ["video"]   # audio stripped
    assert read_project(picture.project)["assets"]["pump_v"]["kind"] == "video"
    rows = animate_rows(picture.ws)
    assert [r["status"] for r in rows] == ["reserved", "submitted", "success"] and len({r["id"] for r in rows}) == 1
    assert rows[0]["est_usd"] == pytest.approx(0.11) and rows[-1]["cost_usd"] == pytest.approx(0.104)
    assert rows[1]["job"] == "job-1" and "$0.104" in text
    assert not list((picture.ws / ".cache" / "animate").glob("*/*"))  # the first-frame work folder is gone


@needs_ffmpeg
def test_animate_the_same_request_again_costs_nothing(picture):
    first = FakeVideo()
    assert not P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=first, sleep=no_sleep)[1]
    again = FakeVideo(submit_error=AssertionError("bought twice"))
    text, err = P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=again, sleep=no_sleep)
    assert not err and "no new charge" in text and again.submits == [] and again.polls == []
    text, err = P.animate(picture.project, id="pump_copy", image_asset="pump", motion="m", api=again, sleep=no_sleep)
    assert not err and "a copy of 'pump_v'" in text and again.submits == []
    assert (picture.project / "assets" / "pump_copy.mp4").read_bytes() == \
        (picture.project / "assets" / "pump_v.mp4").read_bytes()
    assert P.spent_usd(picture.project) == pytest.approx(0.104)
    other = FakeVideo(job="job-2")                                    # a new motion is a new clip
    assert not P.animate(picture.project, id="pump_v", image_asset="pump", motion="m2", api=other, sleep=no_sleep)[1]
    assert len(other.submits) == 1


@needs_ffmpeg
def test_animate_resumes_a_job_a_killed_call_left_instead_of_buying_again(picture):
    dying = FakeVideo(statuses=("in_progress", Killed()))
    with pytest.raises(Killed):
        P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=dying, sleep=no_sleep)
    assert [r["status"] for r in animate_rows(picture.ws)] == ["reserved", "submitted"]
    assert P.spent_usd(picture.project) == pytest.approx(0.11)           # counted at its estimate meanwhile
    later = FakeVideo(submit_error=AssertionError("bought twice"), statuses=("completed",))
    text, err = P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=later, sleep=no_sleep)
    assert not err, text
    assert later.submits == [] and later.polls[0][0] == "job-1" and later.fetches == ["job-1"]
    rows = animate_rows(picture.ws)
    assert [r["status"] for r in rows] == ["reserved", "submitted", "success"] and len({r["id"] for r in rows}) == 1
    assert P.spent_usd(picture.project) == pytest.approx(0.104)


@needs_ffmpeg
def test_animate_still_running_after_the_timeout_is_collected_later(picture):
    slow = FakeVideo(statuses=("in_progress",))
    text, err = P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=slow, sleep=no_sleep,
                          timeout_s=0)
    assert err and "still generating" in text and "no new charge" in text
    later = FakeVideo(submit_error=AssertionError("bought twice"))
    assert not P.animate(picture.project, id="pump_v", image_asset="pump", motion="m", api=later, sleep=no_sleep)[1]
    assert later.submits == []


@needs_ffmpeg
def test_animate_refuses_over_budget_or_under_the_floor_before_submitting(picture):
    picture.config(budget={"per_project_usd": 0.1})
    api = FakeVideo()
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert err and "budget" in text and api.submits == []
    picture.config(budget={"per_project_usd": 1.0})
    api = FakeVideo(balance=5.05)
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert err and "$5.00 floor" in text and api.submits == []

    class NoBalance(FakeVideo):
        def balance(self):
            raise OR.Unreachable("cannot reach openrouter.ai: timed out")
    api = NoBalance()
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert err and "balance could not be read" in text and api.submits == []
    assert P.spent_usd(picture.project) == 0.0
    assert {r["status"] for r in animate_rows(picture.ws)} == {"refused"}


@needs_ffmpeg
def test_animate_a_submit_that_may_have_been_taken_counts_and_is_not_resumed(picture):
    lost = FakeVideo(submit_error=TimeoutError("read timed out"))
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=lost, sleep=no_sleep)
    assert err and "may have been taken" in text
    assert P.spent_usd(picture.project) == pytest.approx(0.11)
    refused = FakeVideo(submit_error=OR.ApiError(400, "bad image"))
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=refused, sleep=no_sleep)
    assert err and "refused the job" in text and len(refused.submits) == 1    # a fresh purchase, not a resume
    assert P.spent_usd(picture.project) == pytest.approx(0.11)                 # the refusal cost nothing


@needs_ffmpeg
def test_animate_parallel_identical_calls_buy_one_clip(picture):
    release = threading.Event()
    api = FakeVideo(hold=release)
    results = {}
    worker = threading.Thread(target=lambda: results.update(first=P.animate(
        picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)))
    worker.start()
    try:
        assert api.submitting.wait(10)
        text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
        assert err and "being submitted right now" in text
    finally:
        release.set()
        worker.join(30)
    assert not results["first"][1] and len(api.submits) == 1


@needs_ffmpeg
def test_animate_failed_job_settles_and_says_what_to_do(picture):
    api = FakeVideo(statuses=("failed",))
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert err and "no clip" in text and "keyframes" in text
    assert animate_rows(picture.ws)[-1]["status"] == "failed" and P.spent_usd(picture.project) == 0.0


class FlakyDownload(FakeVideo):
    """The job completes (and is paid); the first download breaks off."""

    def __init__(self, broken=1, **kw):
        super().__init__(**kw)
        self.broken = broken

    def fetch(self, job, done):
        self.fetches.append(job)
        if len(self.fetches) <= self.broken:
            raise OR.Unreachable("cannot reach cdn.example.com: timed out")
        return clip_mp4()


@needs_ffmpeg
def test_animate_a_paid_clip_that_failed_to_download_is_collected_not_bought_again(picture):
    """A retry must not submit (and pay for) a second job."""
    api = FlakyDownload(statuses=("completed", "completed"))
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert err and "made and paid for ($0.104)" in text and "call animate again with the same arguments" in text
    assert "no new charge" in text and "Move the still" not in text
    assert [r["status"] for r in animate_rows(picture.ws)] == ["reserved", "submitted", "collect"]
    assert P.spent_usd(picture.project) == pytest.approx(0.104)
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)
    assert not err, text
    assert len(api.submits) == 1 and api.fetches == ["job-1", "job-1"]
    rows = animate_rows(picture.ws)
    assert [r["status"] for r in rows] == ["reserved", "submitted", "collect", "success"]
    assert len({r["id"] for r in rows}) == 1 and P.spent_usd(picture.project) == pytest.approx(0.104)
    assert (picture.project / "assets" / "v.mp4").is_file()
    assert read_project(picture.project)["assets"]["v"]["kind"] == "video"


@needs_ffmpeg
def test_animate_a_collect_whose_job_is_gone_keeps_the_real_cost(picture):
    api = FlakyDownload(statuses=("completed",), cost=0.0487)
    assert P.animate(picture.project, id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep)[1]

    class Gone(FakeVideo):
        def poll(self, job, polling_url):
            self.polls.append(job)
            raise OR.ApiError(404, "no such job")
    gone = Gone(submit_error=AssertionError("bought twice"))
    text, err = P.animate(picture.project, id="v", image_asset="pump", motion="m", api=gone, sleep=no_sleep)
    assert err and "gone" in text and gone.polls == ["job-1"] and gone.submits == []
    assert P.spent_usd(picture.project) == pytest.approx(0.0487)          # not the 0.11 estimate


@pytest.mark.parametrize("kwargs, says", [
    (dict(image_asset="ghost"), "must be an image asset"),
    (dict(motion=""), "motion must say"),
    (dict(seconds=1), "seconds must be 2-12"),
    (dict(seconds=4.5), "whole number"),
    (dict(seconds=True), "whole number"),
    (dict(camera="zoom"), "camera must be one of"),
    (dict(id="pump"), "already names an image"),
])
def test_animate_validates_before_spending(picture, kwargs, says):
    api = FakeVideo()
    args = dict(id="v", image_asset="pump", motion="m", api=api, sleep=no_sleep) | kwargs
    text, err = P.animate(picture.project, **args)
    assert err and says in text and api.submits == [] and animate_rows(picture.ws) == []


def test_animate_estimate_follows_resolution_or_an_explicit_rate():
    assert A.estimate({"resolution": "480p"}, 4) == pytest.approx(0.05)
    assert A.estimate({"resolution": "720p", "usd_per_s": 0.03}, 5) == pytest.approx(0.15)
    with pytest.raises(P.ProviderError, match="usd_per_s"):
        A.estimate({"resolution": "4k"}, 4)


# ------------------------------------------------------------------ import_asset and assets
class FakeResponse:
    def __init__(self, body: bytes, ctype="image/png", length=True, url="https://cdn.example.com/a.png"):
        self._body, self.url = io.BytesIO(body), url
        self.headers = {"Content-Type": ctype}
        if length:
            self.headers["Content-Length"] = str(len(body))

    def read(self, n=-1):
        return self._body.read(n)

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(response):
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        if isinstance(response, BaseException):
            raise response
        return response
    opener.seen = seen
    return opener


def test_import_a_local_image_sniffs_its_real_type(env):
    src = write_png(env.tmp / "photo.jpg", 120, 80)                 # a PNG with the wrong name
    text, err = P.import_asset(env.project, id="photo", source=str(src))
    assert not err, text
    assert (env.project / "assets" / "photo.png").is_file() and "120x80" in text
    assert read_project(env.project)["assets"]["photo"] == {"path": "assets/photo.png", "kind": "image",
                                                           "note": "from photo.jpg"}


def test_import_a_relative_path_from_the_project_folder(env):
    write_png(env.project / "assets" / "loose.png")
    text, err = P.import_asset(env.project, id="loose", source="assets/loose.png")
    assert not err and read_project(env.project)["assets"]["loose"]["path"] == "assets/loose.png"


@pytest.mark.parametrize("source", ["file:///C:/Windows/win.ini", "ftp://example.com/a.png", "data:image/png;base64,AA",
                                    "javascript:alert(1)", "smb://server/share/a.png"])
def test_import_refuses_other_schemes(env, source):
    opener = opener_for(FakeResponse(png_bytes()))
    text, err = P.import_asset(env.project, id="a", source=source, opener=opener)
    assert err and "not allowed" in text and opener.seen == []


def test_import_refuses_what_is_not_media(env):
    (env.tmp / "notes.png").write_text("just text", encoding="utf-8")
    text, err = P.import_asset(env.project, id="a", source=str(env.tmp / "notes.png"))
    assert err and "not an image, video or audio" in text
    text, err = P.import_asset(env.project, id="a", source=str(env.tmp / "missing.png"))
    assert err and "no file at" in text
    assert not list((env.project / "assets").glob("*"))             # no part file left


def test_import_enforces_the_size_cap(env):
    env.config(providers={"import": {"max_mb": 1}})
    big = env.tmp / "big.png"
    big.write_bytes(png_bytes() + b"\0" * (1 << 20))
    text, err = P.import_asset(env.project, id="a", source=str(big))
    assert err and "over the 1 MB import limit" in text
    declared_big = FakeResponse(png_bytes())
    declared_big.headers["Content-Length"] = str(5 << 20)
    text, err = P.import_asset(env.project, id="a", source="https://cdn.example.com/a.png",
                               opener=opener_for(declared_big))
    assert err and "5 MB, over the 1 MB" in text
    streamed = FakeResponse(png_bytes() + b"\0" * (2 << 20), length=False)          # no length header: counted
    text, err = P.import_asset(env.project, id="a", source="https://cdn.example.com/a.png",
                               opener=opener_for(streamed))
    assert err and "over the 1 MB import limit" in text
    assert not list((env.project / "assets").glob("*"))             # no part file left


def test_import_a_download_checks_type_and_records_the_source(env):
    page = FakeResponse(b"<html></html>", ctype="text/html; charset=utf-8")
    text, err = P.import_asset(env.project, id="a", source="https://news.example.com/story", opener=opener_for(page))
    assert err and "text/html" in text and "capture" in text
    gone = urllib.error.HTTPError("https://cdn.example.com/x.png", 404, "nf", {}, io.BytesIO(b""))
    text, err = P.import_asset(env.project, id="a", source="https://cdn.example.com/x.png", opener=opener_for(gone))
    assert err and "HTTP 404" in text
    ok = opener_for(FakeResponse(png_bytes(200, 100), ctype="application/octet-stream"))
    text, err = P.import_asset(env.project, id="chart", source="https://cdn.example.com/chart", opener=ok)
    assert not err, text
    assert ok.seen[0].get_header("User-agent").startswith("Mozilla/5.0")
    entry = read_project(env.project)["assets"]["chart"]
    assert entry["path"] == "assets/chart.png" and entry["note"] == "from https://cdn.example.com/chart"


def test_import_redirect_hops_must_be_public_http(env):
    handler = I._SafeRedirect(offline_resolve)
    req = urllib.request.Request("https://a.example.com/x.png")
    with pytest.raises(P.ProviderError, match="only http"):
        handler.redirect_request(req, None, 302, "Found", {}, "file:///etc/passwd")
    for hop in ("http://127.0.0.1:8080/internal/admin.png", "http://localtest.me/x.png",
                "http://169.254.169.254.nip.io/latest/meta-data/", "http://[::1]/x"):
        with pytest.raises(P.ProviderError, match="local or private|this machine"):
            handler.redirect_request(req, None, 302, "Found", {}, hop)
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://b.example.com/x.png") is not None


@pytest.mark.parametrize("source, says", [("http://127.0.0.1:8000/x.png", "local or private"),
                                          ("http://localtest.me/x.png", "resolves to 127.0.0.1"),
                                          ("http://intranet.example/x.png", "10.0.0.5"),
                                          ("http://169.254.169.254.nip.io/latest", "169.254.169.254"),
                                          ("https://user:pw@cdn.example.com/a.png", "user name or password"),
                                          ("http://localhost:3000/a.png", "this machine")])
def test_import_refuses_local_and_private_addresses_before_any_request(env, source, says):
    opener = opener_for(FakeResponse(png_bytes()))
    text, err = P.import_asset(env.project, id="a", source=source, opener=opener)
    assert err and says in text and opener.seen == []
    assert not list((env.project / "assets").glob("*"))


def test_import_follows_no_redirect_into_the_local_network(env):
    """The real urllib opener and a local server: the first address passes (trusted here), its redirect to a
    loopback name does not, and the internal file is never requested."""
    import http.server
    hits = []

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/public-looking":
                self.send_response(302)
                self.send_header("Location", f"http://localtest.me:{srv.server_port}/internal/admin.png")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(png_bytes())

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    dst = env.tmp / "dl.part"
    try:
        with pytest.raises(P.ProviderError, match="redirected to http://localtest.me.*resolves to 127.0.0.1"):
            I.download(f"http://127.0.0.1:{srv.server_port}/public-looking", dst, 10 << 20,
                       resolve=offline_resolve, trusted=("127.0.0.1",))
        assert I.download(f"http://127.0.0.1:{srv.server_port}/fine.png", dst, 10 << 20, resolve=offline_resolve,
                          trusted=("127.0.0.1",)).endswith("/fine.png")
    finally:
        srv.shutdown()
    assert hits == ["/public-looking", "/fine.png"]


def gif_bytes(w=20, h=10) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00" + b"\x3b"


def avif_bytes() -> bytes:
    return b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 200


def test_import_refuses_files_the_project_format_cannot_use(env):
    (env.tmp / "shot.gif").write_bytes(gif_bytes())
    text, err = P.import_asset(env.project, id="ev2", source=str(env.tmp / "shot.gif"), kind="evidence")
    assert err and "GIF files cannot be evidence assets" in text and "PNG" in text and "WEBP" in text
    assert not (env.project / "assets").exists() or not list((env.project / "assets").glob("*"))   # nothing copied
    (env.tmp / "shot.avif").write_bytes(avif_bytes())
    for kind in ("evidence", None):
        text, err = P.import_asset(env.project, id="ev2", source=str(env.tmp / "shot.avif"), kind=kind)
        assert err and "AVIF files cannot be" in text and "convert" in text
    gif = opener_for(FakeResponse(gif_bytes(), ctype="image/gif"))
    text, err = P.import_asset(env.project, id="ev3", source="https://cdn.example.com/a.gif", kind="evidence",
                               opener=gif)
    assert err and "image/gif" in text and "PNG, JPG or WebP" in text
    assert read_project(env.project)["assets"] == {}
    assert not list((env.project / "assets").glob("*"))
    text, err = P.import_asset(env.project, id="anim", source=str(env.tmp / "shot.gif"))
    assert not err and read_project(env.project)["assets"]["anim"]["kind"] == "image"     # a GIF image is fine


def test_import_kind_must_match_and_evidence_gets_a_full_box(env):
    src = write_png(env.tmp / "shot.png", 300, 500)
    text, err = P.import_asset(env.project, id="a", source=str(src), kind="video")
    assert err and "is an image file, not video" in text
    text, err = P.import_asset(env.project, id="a", source=str(src), kind="photo")
    assert err and "kind must be one of" in text
    text, err = P.import_asset(env.project, id="shot", source=str(src), kind="evidence")
    assert not err, text
    entry = read_project(env.project)["assets"]["shot"]
    assert entry["kind"] == "evidence" and entry["box"] == [0, 0, 300, 500]
    assert entry["site"] == "" and entry["url"] == ""
    web = opener_for(FakeResponse(png_bytes(100, 50)))
    text, err = P.import_asset(env.project, id="web", source="https://www.gov.cn/x.png", kind="evidence", opener=web)
    entry = read_project(env.project)["assets"]["web"]
    assert not err and entry["site"] == "www.gov.cn" and entry["url"] == "https://www.gov.cn/x.png"


@needs_ffmpeg
def test_import_video_and_audio_are_probed(env):
    (env.tmp / "road.mp4").write_bytes(clip_mp4(1))
    (env.tmp / "bed.m4a").write_bytes(audio_m4a(1))
    (env.tmp / "beep.mp3").write_bytes(tone_mp3(0.5))
    text, err = P.import_asset(env.project, id="road", source=str(env.tmp / "road.mp4"))
    assert not err and "(video, 1.00 s" in text
    text, err = P.import_asset(env.project, id="bed", source=str(env.tmp / "bed.m4a"))
    assert not err and "(audio" in text and (env.project / "assets" / "bed.m4a").is_file()
    text, err = P.import_asset(env.project, id="beep", source=str(env.tmp / "beep.mp3"), kind="audio")
    assert not err and (env.project / "assets" / "beep.mp3").is_file()
    kinds = {k: v["kind"] for k, v in read_project(env.project)["assets"].items()}
    assert kinds == {"road": "video", "bed": "audio", "beep": "audio"}
    (env.tmp / "cut.mp4").write_bytes(clip_mp4(1)[:400])
    text, err = P.import_asset(env.project, id="cut", source=str(env.tmp / "cut.mp4"))
    assert err and ("cannot read" in text or "no video" in text)


def test_import_respects_the_reelsmith_root_fence(env, monkeypatch):
    outside = write_png(env.tmp / "outside.png")
    monkeypatch.setenv("REELSMITH_ROOT", str(env.ws))
    text, err = P.import_asset(env.project, id="a", source=str(outside))
    assert err and "outside" in text
    inside = write_png(env.ws / "shared" / "in.png")
    assert not P.import_asset(env.project, id="b", source=str(inside))[1]


@needs_ffmpeg
def test_assets_lists_kinds_sizes_durations_use_and_spend(env):
    write_png(env.project / "assets" / "pump.png", 108, 192)
    (env.project / "assets" / "road.mp4").write_bytes(clip_mp4(1))
    write_png(env.project / "assets" / "stray.png")
    env.set_project(assets={"pump": {"path": "assets/pump.png", "kind": "image", "note": "nozzle"},
                            "road": {"path": "assets/road.mp4", "kind": "video"},
                            "ev": {"path": "assets/ev.png", "kind": "evidence", "box": [1, 2, 3, 4]}},
                    tracks=[{"id": "v1", "kind": "visual", "clips": [{"id": "c1", "type": "image", "asset": "pump"}]}])
    Ledger(env.ws / "ledger.jsonl").reserve(project="projects/oil", tool="animate", provider="x", est_usd=0.11,
                                            budget_usd=1)
    text, err = P.assets(env.project)
    assert not err
    assert "pump  image  assets/pump.png  108x192" in text and "used 1x" in text and "nozzle" in text
    assert "road  video  assets/road.mp4  1.00 s" in text and "unused" in text
    assert "ev  evidence  assets/ev.png  MISSING" in text
    assert "not registered" in text and "assets/stray.png" in text
    assert "Narration: none" in text and "$0.110 of the $1.00" in text


# ------------------------------------------------------------------ registration through the edit ops
def fake_ops(monkeypatch, ok=True, issues=()):
    seen = []

    def apply(project, ops):
        seen.append((Path(project), ops))
        if not ok:
            return False, list(issues), "refused"
        data = json.loads((Path(project) / "project.json").read_text(encoding="utf-8"))
        for op in ops:
            if op["op"] == "add_asset":
                data.setdefault("assets", {})[op["id"]] = op["asset"]
            elif op["op"] == "set":
                data[op["path"]] = op["value"]
        (Path(project) / "project.json").write_text(json.dumps(data), encoding="utf-8")
        return True, [], "applied"
    mod = types.ModuleType("reelsmith.ops")
    mod.apply = apply
    monkeypatch.setitem(sys.modules, "reelsmith.ops", mod)
    return seen


def test_assets_are_registered_through_ops_when_it_is_there(env, monkeypatch):
    seen = fake_ops(monkeypatch)
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "p.png")))
    assert not err and "directly" not in text
    assert seen == [(env.project, [{"op": "add_asset", "id": "pic",
                                    "asset": {"path": "assets/pic.png", "kind": "image", "note": "from p.png"}}])]
    assert read_project(env.project)["assets"]["pic"]["kind"] == "image"
    assert P.import_asset(env.project, id="pic", source=str(env.tmp / "p.png"))[1] is False
    assert len(seen) == 1                                            # the same entry again: nothing to apply


@needs_ffmpeg
def test_speak_sets_the_voice_through_ops(env, monkeypatch):
    seen = fake_ops(monkeypatch)
    assert not P.speak(env.project, lines=["一"], engine=FakeTTS())[1]
    assert seen[-1][1] == [{"op": "set", "path": "voice", "value": "voice/voice.json"}]


def test_a_refusing_ops_leaves_project_json_alone_and_says_how_to_register(env, monkeypatch):
    """A refused entry is never written behind the editor's back (unvalidated, without a snapshot)."""
    before = (env.project / "project.json").read_bytes()
    fake_ops(monkeypatch, ok=False, issues=["[error] assets.pic: box should be [x, y, w, h] with w and h > 0"])
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "p.png")))
    assert err and "did not take asset 'pic'" in text and "w and h > 0" in text and "unchanged" in text
    assert '"op": "add_asset"' in text and '"path": "assets/pic.png"' in text      # the op to register it later
    assert (env.project / "project.json").read_bytes() == before
    assert (env.project / "assets" / "pic.png").is_file()                           # the file is kept


def test_a_broken_ops_module_is_an_error_not_a_direct_write(env, monkeypatch):
    before = (env.project / "project.json").read_bytes()
    mod = types.ModuleType("reelsmith.ops")

    def apply(project, ops):
        raise RuntimeError("half-written")
    mod.apply = apply
    monkeypatch.setitem(sys.modules, "reelsmith.ops", mod)
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "p.png")))
    assert err and "half-written" in text and (env.project / "project.json").read_bytes() == before


def test_without_the_ops_module_the_entry_is_written_directly(env):
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "p.png")))
    assert not err and "written to project.json directly" in text
    assert read_project(env.project)["assets"]["pic"]["path"] == "assets/pic.png"
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "q.png", 10, 10)))
    assert not err and "replaced the earlier entry" in text


@needs_ffmpeg
def test_a_refused_voice_setting_is_a_note_not_a_lost_narration(env, monkeypatch):
    fake_ops(monkeypatch, ok=False, issues=["[error] voice: nope"])
    text, err = P.speak(env.project, lines=["一"], engine=FakeTTS())
    assert not err and "voice was NOT set" in text and "nope" in text
    assert (env.project / "voice" / "voice.wav").is_file()
    assert "voice" not in read_project(env.project)


def test_parallel_registrations_all_land(env):
    srcs = [write_png(env.tmp / f"p{n}.png", 10 + n, 10) for n in range(12)]
    results = []
    threads = [threading.Thread(target=lambda n=n: results.append(
        P.import_asset(env.project, id=f"pic{n}", source=str(srcs[n])))) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(not err for _, err in results)
    assert set(read_project(env.project)["assets"]) == {f"pic{n}" for n in range(12)}


def test_the_real_ops_accepts_what_providers_register(env, monkeypatch):
    monkeypatch.delitem(sys.modules, "reelsmith.ops")
    try:
        ops = importlib.import_module("reelsmith.ops")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"reelsmith.ops not available yet ({type(exc).__name__})")
    if not callable(getattr(ops, "apply", None)):
        pytest.skip("reelsmith.ops has no apply()")
    text, err = P.import_asset(env.project, id="pic", source=str(write_png(env.tmp / "p.png", 1080, 1920)))
    assert not err and "directly" not in text, text
    shot = write_png(env.tmp / "shot.png", 300, 500)
    text, err = P.import_asset(env.project, id="ev1", source=str(shot), kind="evidence")
    assert not err and "directly" not in text, text
    (env.tmp / "shot.gif").write_bytes(gif_bytes())
    (env.tmp / "shot.avif").write_bytes(avif_bytes())
    assert P.import_asset(env.project, id="ev2", source=str(env.tmp / "shot.gif"), kind="evidence")[1]
    assert P.import_asset(env.project, id="ev3", source=str(env.tmp / "shot.avif"), kind="evidence")[1]
    document = importlib.import_module("reelsmith.document")
    _, issues = document.check_data(env.project, read_project(env.project))
    bad = [i for i in issues if i.level == "error" and "duration" not in i.where]    # (the fixture sets no length)
    assert not bad and set(read_project(env.project)["assets"]) == {"pic", "ev1"}


# ------------------------------------------------------------------ opt-in: the real browser on a local page
REAL_OPEN = N.open_connection
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>油价调整通知</title>
<meta property="og:site_name" content="测试站"><style>
body{margin:0;font:18px/1.6 sans-serif} header{position:fixed;top:0;left:0;right:0;height:120px;background:#00f}
main{padding:140px 16px 2000px} .hit{background:#f00;color:#f00} .wide{width:900px}</style></head>
<body><header>浮动导航</header><main><h1>示例公司通知</h1><p>前面有很多铺垫的文字。</p>
<div class="wide"><p>按照现行成品油价格形成机制，根据近期国际市场油价变化情况，这次价格调整如下：根据机制，
<span class="hit">汽油每吨上调205元</span>，柴油每吨上调195元。<img src="/hop.png" width="120" height="40">
</p></div></main></body></html>"""


def pixels(png: Path, box=None) -> bytes:
    crop = ["-vf", "crop={2}:{3}:{0}:{1}".format(*box)] if box else []
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(png), *crop, "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout


def count(raw: bytes, test) -> int:
    return sum(1 for i in range(0, len(raw) - 2, 3) if test(raw[i], raw[i + 1], raw[i + 2]))


@pytest.mark.skipif(os.environ.get("REELSMITH_TEST_BROWSER") != "1",
                    reason="set REELSMITH_TEST_BROWSER=1 (launches the installed browser)")
@needs_ffmpeg
def test_capture_in_a_real_browser_boxes_the_sentence_and_keeps_the_page_off_the_local_network(env, monkeypatch):
    """The page is served on 127.0.0.1 (trusted here); its picture redirects to a loopback name, which the guard
    refuses, so the 'secret' never reaches the screenshot. Its 900 px column is reflowed to the phone width."""
    import http.server
    monkeypatch.setattr(N, "open_connection", REAL_OPEN)
    site = env.tmp / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    write_png(site / "secret.png", 120, 40, rgb=(0, 255, 0))
    hits = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def do_GET(self):
            hits.append(self.path)
            if self.path == "/hop.png":
                self.send_response(302)
                self.send_header("Location", f"http://localtest.me:{server.server_address[1]}/secret.png")
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        text, err = P.capture(env.project, url=url, match="汽油每吨上调205元", id="ev_price", proxy=None,
                              trusted=("127.0.0.1",))
    finally:
        server.shutdown()
    assert not err, text
    assert "/hop.png" in hits and "/secret.png" not in hits
    assert "Blocked while loading" in text and "localtest.me" in text
    entry = read_project(env.project)["assets"]["ev_price"]
    png = env.project / entry["path"]
    w, h = CFG.header_size(png)
    assert w <= 430 * 3                                             # the 900 px column came back at phone width
    x, y, bw, bh = entry["box"]
    assert 0 <= x and x + bw <= w and 0 <= y and y + bh <= h
    assert bw > 0.8 * w and 40 < bh < 400                           # whole lines of the column
    assert count(pixels(png, entry["box"]), lambda r, g, b: r > 200 and g < 60 and b < 60) > 500   # the match
    assert count(pixels(png), lambda r, g, b: g > 200 and r < 60 and b < 60) == 0                  # no secret
    assert count(pixels(png, [0, 0, w, min(h, 60)]), lambda r, g, b: b > 200 and r < 60) == 0      # header hidden
    assert entry["site"] == "测试站" and "柴油每吨上调195元。" in text and "the sentence that holds" in text


# ------------------------------------------------------------------ canvas and locale
def test_capture_viewport_follows_the_canvas_and_the_locale(env):
    world = FakeBrowserWorld()
    assert not P.capture(env.project, url="https://e.com/a", id="ev1", sync_playwright=world, proxy=None)[1]
    phone = world.contexts[-1]                                      # douyin, zh-CN: a Chinese phone
    assert phone["viewport"]["width"] == 430 and phone["device_scale_factor"] == 3 and phone["has_touch"]
    assert phone["locale"] == "zh-CN" and phone["timezone_id"] == "Asia/Shanghai"
    env.config(profile="landscape", locale="en-GB")
    text, err = P.capture(env.project, url="https://e.com/a", id="ev2", sync_playwright=world, proxy=None)
    assert not err, text
    desk = world.contexts[-1]
    assert desk["viewport"]["width"] == 1440 and desk["device_scale_factor"] == 2 and not desk["has_touch"]
    assert "Mobile" not in desk["user_agent"] and desk["locale"] == "en-GB" and "timezone_id" not in desk
    assert "(desktop viewport)" in text
    assert read_project(env.project)["assets"]["ev2"]["box"] == [41, 202, 361, 48]   # FOUND's match x2
    assert "at 1728 px wide, the safe area's width" in text
    assert not P.capture(env.project, url="https://e.com/a", id="ev3", viewport="phone", sync_playwright=world,
                         proxy=None)[1]
    assert world.contexts[-1]["viewport"]["width"] == 430
    text, err = P.capture(env.project, url="https://e.com/a", id="ev4", viewport="tablet", sync_playwright=world,
                          proxy=None)
    assert err and "viewport must be one of phone, desktop" in text
    env.config(profile="square")
    assert C.default_viewport(CFG.project_profile(CFG.context(env.project))) == "desktop"
    env.config(profile="portrait")
    assert C.default_viewport(CFG.project_profile(CFG.context(env.project))) == "phone"


@needs_ffmpeg
def test_draw_defaults_to_the_canvas_aspect(env):
    env.config(profile="landscape")
    painter = FakePainter(env.tmp, size=(1536, 1024))
    text, err = P.draw(env.project, id="wide", prompt="a street at dusk", provider=painter)
    assert not err, text
    assert painter.calls[0]["gen"] == (1536, 1024)
    assert CFG.header_size(env.project / "assets" / "wide.png") == (1920, 1080)
    env.set_project(profile={"base": "square", "width": 1080, "height": 1350})
    painter = FakePainter(env.tmp)
    assert not P.draw(env.project, id="tall", prompt="a portrait", provider=painter)[1]
    assert CFG.header_size(env.project / "assets" / "tall.png") == (1080, 1350)       # 4:5
    assert [D.nearest_aspect(w, h) for w, h in ((1920, 1080), (1080, 1920), (1080, 1080), (2560, 1080),
                                                (1000, 1400))] == ["16:9", "9:16", "1:1", "16:9", "3:4"]


def test_speak_picks_the_voice_by_locale(env, monkeypatch):
    seen = []

    class Engine(TTS.OpenRouterTTS):
        def check(self):
            seen.append(dict(self.cfg))
            raise P.ProviderError("stop here")
    monkeypatch.setitem(TTS.ENGINES, "openrouter", lambda ctx, cfg: Engine(cfg, "k"))
    text, err = P.speak(env.project, lines=["一句话"])                 # zh-CN: the Mandarin default voice
    assert err and "stop here" in text and seen[-1]["voice"] == "longanlufeng" and seen[-1]["locale"] == "zh-CN"
    env.config(locale="en")
    text, err = P.speak(env.project, lines=["One line."])
    assert err and "no voice for locale en" in text and "providers.tts.voice" in text and len(seen) == 1
    env.config(providers={"tts": {"voice": "Cherry"}})
    text, err = P.speak(env.project, lines=["One line."])
    assert err and "stop here" in text and seen[-1]["voice"] == "Cherry"
    english = Engine({"model": "qwen/q", "voice": "Cherry", "locale": "en"}, "k")
    chinese = Engine({"model": "qwen/q", "voice": "Cherry", "locale": "zh-CN"}, "k")
    assert english.identity().endswith("|en") and not chinese.identity().endswith("|zh")
    assert chinese.identity() == Engine({"model": "qwen/q", "voice": "Cherry"}, "k").identity()   # caches kept


def test_speech_body_speaks_the_locales_language_to_the_model():
    en = OR.speech_body("One line.", {"model": "qwen/qwen-audio-3.0-tts-plus", "voice": "v", "locale": "en"}, 1.10,
                        emotion="surprised")
    assert en["instructions"] == "Read this line slower, every word clear, the stress steady; The mood of this " \
                                 "line: surprised"
    zh = OR.speech_body("一句话", {"model": "qwen/qwen-audio-3.0-tts-plus", "voice": "v", "locale": "zh-CN"}, 1.10)
    assert "放慢" in zh["instructions"]
