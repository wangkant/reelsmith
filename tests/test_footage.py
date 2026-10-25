"""Looking at footage (probe, frames, scenes, silences) and transcribe, on media ffmpeg makes here; every
transcription call goes to a fake local server or a fake faster-whisper."""
import http.server
import importlib
import json
import shutil
import subprocess
import sys
import threading
import types
import urllib.request
from pathlib import Path

import pytest

from reelsmith import cli
from reelsmith import providers as P
from reelsmith import tools

F = importlib.import_module("reelsmith.providers.footage")
TR = importlib.import_module("reelsmith.providers.transcribe")
pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg/ffprobe not on PATH")
# a tone with a silence 1.2-2.4 s: one silence, two sounds
TONE = "aevalsrc='if(between(t\\,1.2\\,2.4)\\,0\\,0.5*sin(2*PI*440*t))':s=16000:d=4"
_MEDIA: dict = {}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True,
                   capture_output=True)


def media(tmp_path_factory, name: str) -> bytes:
    if name not in _MEDIA:
        out = tmp_path_factory.mktemp("media") / name
        if name == "talk.wav":
            ffmpeg("-f", "lavfi", "-i", TONE, out)
        elif name == "two.mp4":       # red 0-1.5 s, blue 1.5-3 s, the tone underneath
            ffmpeg("-f", "lavfi", "-i", "color=c=red:s=160x90:r=25:d=1.5", "-f", "lavfi", "-i",
                   "color=c=blue:s=160x90:r=25:d=1.5", "-f", "lavfi", "-i", TONE.replace("d=4", "d=3"),
                   "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out)
        elif name == "silent.mp4":
            ffmpeg("-f", "lavfi", "-i", "testsrc2=s=90x160:r=25:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", out)
        _MEDIA[name] = out.read_bytes()
    return _MEDIA[name]


@pytest.fixture
def ws(tmp_path, tmp_path_factory, monkeypatch):
    for name in ("REELSMITH_ROOT", "REELSMITH_BUDGET_USD", "REELSMITH_MIN_BALANCE_USD", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "ws"
    project = root / "projects" / "cut"
    (project / "assets").mkdir(parents=True)
    (root / "workspace.json").write_text(json.dumps({"budget": {"per_project_usd": 1.0}}), encoding="utf-8")
    (root / ".env").write_text("OPENAI_API_KEY=sk-test-0123456789abcdefghij\n", encoding="utf-8")
    for name in ("talk.wav", "two.mp4", "silent.mp4"):
        (project / "assets" / name).write_bytes(media(tmp_path_factory, name))
    (project / "project.json").write_text(json.dumps({
        "version": 2, "assets": {"talk": {"path": "assets/talk.wav", "kind": "audio"},
                                 "two": {"path": "assets/two.mp4", "kind": "video"},
                                 "mute": {"path": "assets/silent.mp4", "kind": "video"}},
        "tracks": []}), encoding="utf-8")
    return types.SimpleNamespace(root=root, project=project)


def as_json(text: str) -> dict:
    return json.loads(text.split("JSON: ", 1)[1])


def raw(project: Path) -> dict:
    return json.loads((project / "project.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ probe
def test_probe_reports_streams_and_loudness(ws):
    r = tools.probe(str(ws.project), "two")
    assert r.ok, r
    f = as_json(r)
    assert f["asset"] == "two" and f["path"] == "assets/two.mp4" and f["duration_s"] == pytest.approx(3, abs=0.1)
    assert f["video"]["codec"] == "h264" and (f["video"]["width"], f["video"]["height"]) == (160, 90)
    assert f["video"]["fps"] == 25 and f["video"]["rotation"] == 0 and f["video"]["display"] == [160, 90]
    assert f["audio"]["codec"] == "aac" and f["audio"]["channels"] == 1
    assert f["audio"]["lufs"] is not None and f["audio"]["true_peak_db"] < 0
    assert "video: h264 160x90, 25 fps" in r and "LUFS" in r


def test_probe_takes_a_project_file_and_refuses_outside_files(ws, tmp_path):
    r = tools.probe(str(ws.project), "assets/talk.wav")
    assert r.ok and as_json(r)["video"] is None and as_json(r)["audio"]["sample_rate"] == 16000
    outside = tmp_path / "x.wav"
    outside.write_bytes(b"x")
    r = tools.probe(str(ws.project), str(outside))
    assert not r.ok and "outside the project folder" in r
    r = tools.probe(str(ws.project), "nope")
    assert not r.ok and "no asset or file 'nope'" in r and "two" in r


# ------------------------------------------------------------------ frames
def test_frames_at_source_times_with_a_contact_sheet(ws):
    r = tools.frames(str(ws.project), "two", [0.5, "0:02.0"])
    assert r.ok, r
    pngs = [Path(line.split(": ", 1)[1]) for line in r.splitlines() if line.startswith("- ")]
    assert len(pngs) == 2 and all(p.is_file() for p in pngs)
    assert "build" in pngs[0].parts and "footage" in pngs[0].parts
    from PIL import Image
    red, blue = (Image.open(p).convert("RGB").getpixel((80, 45)) for p in pngs)
    assert red[0] > 200 and red[2] < 60 and blue[2] > 200 and blue[0] < 60     # source times, not film times
    sheet = Path(r.split("contact sheet (source times burned in): ")[1].strip())
    assert sheet.is_file()


def test_frames_evenly_or_every_and_its_limits(ws):
    r = tools.frames(str(ws.project), "two", n=4)
    assert r.ok and "4 still(s)" in r
    r = tools.frames(str(ws.project), "two", every=1)
    assert r.ok and "3 still(s)" in r and "- 0.00s" in r and "- 2.00s" in r
    assert not tools.frames(str(ws.project), "two", every=0.05).ok
    assert "past the end" in tools.frames(str(ws.project), "two", [9])
    assert "no moving picture" in tools.frames(str(ws.project), "talk")


# ------------------------------------------------------------------ scenes
def test_scenes_finds_the_cut_and_shows_first_frames(ws):
    r = tools.scenes(str(ws.project), "two")
    assert r.ok, r
    shots = as_json(r)["shots"]
    assert len(shots) == 2 and shots[1]["start"] == pytest.approx(1.5, abs=0.05)
    assert shots[0]["start"] == 0 and shots[-1]["end"] == pytest.approx(3, abs=0.1)
    assert "first frames" in r and Path(r.split("look with Read: ")[1].splitlines()[0]).is_file()


def test_shots_merge_flashes_and_drop_cuts_at_the_edges():
    shots = F.shots_of([0.02, 1.0, 1.05, 2.98], 3.0)
    assert [s["start"] for s in shots] == [0.0, 1.0] and shots[-1]["end"] == 3.0


# ------------------------------------------------------------------ silences
def test_silences_and_the_sound_between(ws):
    r = tools.silences(str(ws.project), "talk")
    assert r.ok, r
    d = as_json(r)
    assert len(d["silences"]) == 1
    s = d["silences"][0]
    assert s["start"] == pytest.approx(1.2, abs=0.05) and s["end"] == pytest.approx(2.4, abs=0.05)
    assert [round(x["start"], 1) for x in d["sound"]] == [0.0, 2.4] and d["sound"][-1]["end"] == pytest.approx(4)
    assert "src:C@S" in r
    assert "no sound" in tools.silences(str(ws.project), "mute")
    assert not tools.silences(str(ws.project), "talk", min_s=0).ok


def test_speech_is_the_complement_of_silence():
    quiet = [{"start": 0.0, "end": 0.5, "dur": 0.5}, {"start": 2.0, "end": 3.0, "dur": 1.0}]
    assert F.speech_ranges(quiet, 3.0) == [{"start": 0.5, "end": 2.0, "dur": 1.5}]


def test_footage_tools_through_the_cli_and_mcp(ws, capsys):
    assert cli.main(["silences", str(ws.project), "talk", "--min-s", "0.4"]) == 0
    assert "1 silence(s)" in capsys.readouterr().out
    assert cli.main(["frames", str(ws.project), "two", "0.5"]) == 0
    from reelsmith.mcp_server import mcp
    import asyncio
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"probe", "frames", "scenes", "silences", "transcribe"} <= names


# ------------------------------------------------------------------ transcribe
class FakeWhisper(http.server.BaseHTTPRequestHandler):
    """An OpenAI-compatible /audio/transcriptions: two words per piece, 0.1-0.5 and 0.6-0.9 s into it."""
    seen: list = []
    status = 200

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeWhisper.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if FakeWhisper.status != 200:
            self.send_response(FakeWhisper.status)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "bad key sk-test-0123456789abcdefghij"}}')
            return
        n = len(FakeWhisper.seen)
        answer = {"text": f"hello world {n}", "language": "english",
                  "words": [{"word": "Hello", "start": 0.1, "end": 0.5}, {"word": f"world{n}", "start": 0.6,
                                                                         "end": 0.9}],
                  "segments": [{"id": 0, "start": 0.1, "end": 0.9, "text": f" Hello world{n}"}]}
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def whisper(ws, monkeypatch):
    FakeWhisper.seen, FakeWhisper.status = [], 200
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeWhisper)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    monkeypatch.setattr(urllib.request, "urlopen", direct)
    cfg = json.loads((ws.root / "workspace.json").read_text(encoding="utf-8"))
    cfg["providers"] = {"transcribe": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "usd_per_min": 0.6}}
    (ws.root / "workspace.json").write_text(json.dumps(cfg), encoding="utf-8")
    yield server
    server.shutdown()


def test_transcribe_saves_words_links_the_asset_and_books_the_cost(ws, whisper):
    r = tools.transcribe(str(ws.project), "talk", language="en", prompt="Kant")
    assert r.ok, r
    assert len(FakeWhisper.seen) == 1
    call = FakeWhisper.seen[0]
    assert call["path"] == "/v1/audio/transcriptions" and call["auth"] == "Bearer sk-test-0123456789abcdefghij"
    for part in (b'name="model"\r\n\r\nwhisper-1', b'name="response_format"\r\n\r\nverbose_json',
                 b'name="timestamp_granularities[]"\r\n\r\nword', b'name="language"\r\n\r\nen',
                 b'name="prompt"\r\n\r\nKant', b'filename="sound.mp3"'):
        assert part in call["body"]
    t = json.loads((ws.project / "assets" / "talk.transcript.json").read_text(encoding="utf-8"))
    assert t["asset"] == "talk" and t["source"] == "assets/talk.wav" and t["language"] == "english"
    assert t["words"] == [{"word": "Hello", "start": 0.1, "end": 0.5}, {"word": "world1", "start": 0.6, "end": 0.9}]
    assert raw(ws.project)["assets"]["talk"]["transcript"] == "assets/talk.transcript.json"
    rows = [json.loads(x) for x in (ws.root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["status"] for x in rows] == ["reserved", "success"] and rows[-1]["tool"] == "transcribe"
    assert rows[-1]["cost_usd"] == pytest.approx(0.04, abs=0.002)          # 4 s at $0.60 a minute
    assert "[0.10-0.90] Hello world1" in r and "clip:<a clip playing talk>" in r


def test_transcribe_cuts_long_sound_at_silences_and_stitches_the_clock(ws, whisper):
    cfg = json.loads((ws.root / "workspace.json").read_text(encoding="utf-8"))
    cfg["providers"]["transcribe"]["max_mb"] = 0.012               # ~3 s of 32 kbps MP3: two pieces
    (ws.root / "workspace.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = tools.transcribe(str(ws.project), "talk")
    assert r.ok, r
    assert len(FakeWhisper.seen) == 2 and "in 2 pieces" in r
    words = json.loads((ws.project / "assets" / "talk.transcript.json").read_text(encoding="utf-8"))["words"]
    second = [w for w in words if w["word"] == "world2"][0]
    assert 1.2 + 0.6 <= second["start"] <= 2.4 + 0.6               # the cut sits in the silence; times moved back


def test_transcribe_refuses_over_budget_and_without_a_key(ws, whisper):
    cfg = json.loads((ws.root / "workspace.json").read_text(encoding="utf-8"))
    cfg["providers"]["transcribe"]["usd_per_min"] = 100
    (ws.root / "workspace.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = tools.transcribe(str(ws.project), "talk")
    assert not r.ok and "budget" in r and FakeWhisper.seen == []
    (ws.root / ".env").write_text("", encoding="utf-8")
    r = tools.transcribe(str(ws.project), "talk")
    assert not r.ok and "no OPENAI_API_KEY" in r


def test_transcribe_errors_are_scrubbed_and_not_retried_on_a_bad_key(ws, whisper):
    FakeWhisper.status = 401
    r = tools.transcribe(str(ws.project), "talk")
    assert not r.ok and "HTTP 401" in r and "sk-test-0123456789abcdefghij" not in r
    assert len(FakeWhisper.seen) == 1
    rows = [json.loads(x) for x in (ws.root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["status"] == "failed" and rows[-1]["cost_usd"] == 0


def test_transcribe_refuses_what_has_no_speech_to_hear(ws, whisper):
    assert "no sound" in tools.transcribe(str(ws.project), "mute")
    assert "no asset 'nope'" in tools.transcribe(str(ws.project), "nope")


def test_transcribe_with_the_local_model(ws, monkeypatch):
    seg = types.SimpleNamespace(start=0.0, end=1.0, text=" 你好世界",
                                words=[types.SimpleNamespace(word="你好", start=0.0, end=0.4),
                                       types.SimpleNamespace(word="世界", start=0.5, end=1.0)])

    class Model:
        def __init__(self, name, device, compute_type):
            self.name = name

        def transcribe(self, path, language, initial_prompt, word_timestamps):
            assert Path(path).suffix == ".wav" and word_timestamps
            return iter([seg]), types.SimpleNamespace(language="zh")
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(TR, "_MODELS", {})
    cfg = {"providers": {"transcribe": {"provider": "local"}}}
    (ws.root / "workspace.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = tools.transcribe(str(ws.project), "two")
    assert r.ok and "(local, free)" in r, r
    t = json.loads((ws.project / "assets" / "two.transcript.json").read_text(encoding="utf-8"))
    assert [w["word"] for w in t["words"]] == ["你好", "世界"] and t["language"] == "zh"
    assert not (ws.root / "ledger.jsonl").exists()


def test_local_transcriber_missing_says_how_to_install(ws, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    (ws.root / "workspace.json").write_text(json.dumps({"providers": {"transcribe": {"provider": "local"}}}),
                                            encoding="utf-8")
    r = tools.transcribe(str(ws.project), "talk")
    assert not r.ok and "[transcribe]" in r


def test_parse_response_takes_words_inside_segments():
    out = TR.parse_response({"segments": [{"start": 0, "end": 1, "text": " a b",
                                           "words": [{"word": " a", "start": 0, "end": 0.4},
                                                     {"word": "b", "start": 0.5, "end": "x"}]}]})
    assert out["words"] == [{"word": "a", "start": 0.0, "end": 0.4}] and out["segments"][0]["text"] == "a b"


def test_pieces_cut_in_the_latest_silence_that_fits():
    quiet = [{"start": 4.0, "end": 5.0}, {"start": 7.0, "end": 7.4}]
    assert TR.pieces(10, 100, 200, quiet) == [(0.0, 10)]
    plan = TR.pieces(10, 1000, 900, quiet)          # 8.1 s at most per piece
    assert plan[0] == (0.0, 7.2) and plan[-1][1] == 10


def test_provider_signatures_take_what_tools_sends():
    import inspect
    calls = {"probe": dict(source="a"), "frames": dict(asset="a", times=[1], every=1.0, n=2),
             "scenes": dict(asset="a", threshold=0.3), "silences": dict(asset="a", min_s=0.5, noise_db=-35),
             "transcribe": dict(asset="a", language="en", prompt="p")}
    for name, kwargs in calls.items():
        inspect.signature(getattr(P, name)).bind(Path("."), **kwargs)
