import http.client
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from reelsmith import cli
from reelsmith import resolve as R
from reelsmith import tools
from reelsmith.watch import server as W
from reelsmith.watch import state as S

FIXTURE = Path(__file__).parent / "fixtures" / "demo"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
needs_renderer = pytest.mark.skipif(not (shutil.which("node") and shutil.which("ffmpeg")
                                         and (W.R.RENDERER / "node_modules").is_dir()), reason="node or ffmpeg missing")


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """The demo project in a workspace that has a .env and a ledger, neither of which the server may hand out."""
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    ws = tmp_path / "ws"
    p = ws / "projects" / "demo"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    (ws / "workspace.json").write_text("{}", encoding="utf-8")
    (ws / "library" / "components").mkdir(parents=True)
    (ws / ".env").write_text("FAKE_KEY=not-a-real-key\n", encoding="utf-8")
    (ws / "ledger.jsonl").write_text("", encoding="utf-8")
    return p


@pytest.fixture
def served(demo):
    srv = W.serve(demo)
    yield srv
    srv.stop()


def get(srv, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def edit(p, *ops):
    res = tools.edit(str(p), list(ops))
    assert res.ok, res
    return res


# ------------------------------------------------------------------ state
def test_state_of_the_demo(demo):
    st = S.build_state(demo)
    resolved = R.resolve(demo)
    fps = resolved["fps"]
    assert st["valid"] and st["error"] is None
    assert st["canvas"]["width"] == 1080 and st["canvas"]["fps"] == fps and st["canvas"]["locale"] == "zh-CN"
    assert st["frames"] == resolved["durationInFrames"] and st["duration"] == round(st["frames"] / fps, 4)
    # top to bottom: captions, then visual topmost first, then audio
    assert [t["id"] for t in st["tracks"]] == ["cap", "notes", "fg", "mid", "bg", "music"]
    placed = {c["id"]: c for t in resolved["tracks"] for c in t.get("clips") or []}
    placed |= {a["id"]: a for a in resolved["audio"]}
    clips = {c["id"]: c for t in st["tracks"] for c in t["clips"]}
    assert set(clips) == set(placed) - {"voice"}
    for cid, c in clips.items():
        assert (c["start"], c["end"]) == (round(placed[cid]["from"] / fps, 4),
                                          round((placed[cid]["from"] + placed[cid]["dur"]) / fps, 4)), cid
    hook = clips["hook"]
    assert hook["label"] == "一杯奶茶，成本多少？" and hook["written"] == {"start": "0", "end": "line:2.end"}
    assert hook["keyframes"]["scale"] == [0.0, 0.5] and hook["box"] == {"x": 60, "y": 300, "w": 800, "h": 260}
    assert clips["arrow"]["written"]["end"] == "dur 1.5" and clips["open"]["box"] == "full"
    assert clips["shop"]["asset_kind"] == "video" and clips["shop"]["thumb"] == "/api/thumb?asset=clip"
    assert clips["bill"]["label"] == "Receipt" and clips["bill"]["enter"] == {"preset": "rise", "dur": 0.4}
    assert clips["bed1"]["type"] == "audio" and clips["bed1"]["volume"] == 0.1 and clips["bed1"]["thumb"] is None
    assert clips["open"]["raw"]["motion"] == "push" and clips["open"]["keyframes"]["zoom"][0] == 0.0
    assert next(t for t in st["tracks"] if t["id"] == "notes")["hidden"] is True
    cap = st["tracks"][0]
    shown = next(t for t in resolved["tracks"] if t["id"] == "cap")["items"]
    assert [i["start"] for i in cap["items"]] == [round(i["from"] / fps, 4) for i in shown]
    assert cap["items"][0]["line"] == 1 and cap["items"][-1]["line"] == len(st["voice"]["lines"])
    assert "2.5元" in "".join(i["text"] for i in cap["items"] if i["line"] == 3)       # the override, markup gone
    assert st["voice"]["lines"][0]["start"] == 0.0 and st["voice"]["asset"] == "voice"
    assets = {a["id"]: a for a in st["assets"]}
    assert assets["photo"]["used_by"] == ["open", "close"] and assets["photo"]["url"] == "/project/assets/photo.png"
    assert assets["photo"]["width"] == 270
    proof = next(i for i in st["issues"] if i["clip"] == "proof")
    assert proof["level"] == "error" and proof["source"] == "check" and proof["t"] == 11.6
    assert st["render"] == {"delivered": None, "draft": None, "last": None}
    assert st["spend"] == {"project_usd": 0, "budget_usd": 1.0}
    assert st["activity"] == [] and st["history"] == []


def test_revision_is_stable_and_moves_with_an_edit(demo):
    first, again = S.build_state(demo), S.build_state(demo)
    assert first["revision"] == again["revision"]
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    after = S.build_state(demo)
    assert after["revision"] != first["revision"]
    assert after["history"][-1]["n"] == 1 and "arrow" in after["history"][-1]["summary"]


def test_a_broken_project_still_has_a_state(demo):
    (demo / "project.json").write_text('{"version": 2, "tracks": [', encoding="utf-8")
    st = S.build_state(demo)
    assert st["valid"] is False and "not valid JSON" in st["error"]
    assert st["tracks"] == [] and st["revision"]
    (demo / "project.json").write_text(json.dumps({"version": 2, "tracks": [{"id": "x", "kind": "nope"}]}),
                                       encoding="utf-8")
    st = S.build_state(demo)
    assert st["valid"] is False and "does not fit the format" in st["error"] and st["issues"]


def test_the_cache_rebuilds_only_on_a_change(demo, monkeypatch):
    cache = S.StateCache(demo)
    built = []
    real = S.build_state
    monkeypatch.setattr(S, "build_state", lambda root, base="": built.append(1) or real(root, base))
    cache.get(), cache.get()
    assert len(built) == 1
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    cache.get()
    assert len(built) == 2


def test_history_replays_the_cut_after_each_batch(demo):
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    edit(demo, {"op": "remove_clip", "id": "ring"})
    h1, h2 = S.history_state(demo, 1), S.history_state(demo, 2)
    fg = lambda h: {c["id"]: c for c in next(t for t in h["tracks"] if t["id"] == "fg")["clips"]}   # noqa: E731
    assert fg(h1)["arrow"]["written"]["end"] == "line:5.end" and "ring" in fg(h1)
    assert "ring" not in fg(h2) and h2["summary"].startswith("removed")
    assert fg(S.history_state(demo, 0))["arrow"]["written"]["end"] == "dur 1.5"       # before the first batch
    assert S.history_state(demo, 3) is None


# ------------------------------------------------------------------ the activity log
def test_tool_calls_leave_an_activity_line(demo):
    tools.check(str(demo))
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    tools.describe(str(demo))                       # read-only chatter: not logged
    bad = tools.edit(str(demo), [{"op": "remove_clip", "id": "nope"}])
    rows = S.activity_of(demo)
    assert [r["tool"] for r in rows] == ["check", "edit", "edit"]
    assert rows[0]["batch"] is None and rows[0]["ok"] is False          # the demo has an error
    assert rows[1]["ok"] and rows[1]["batch"] == 1 and rows[1]["summary"].startswith("applied: ")
    assert rows[2]["ok"] is False and rows[2]["batch"] is None and not bad.ok
    assert set(rows[1]) == {"ts", "tool", "ok", "seconds", "summary", "batch"}
    assert all(len(r["summary"]) <= 300 and "\n" not in r["summary"] for r in rows)


def test_the_activity_log_is_capped_and_never_fails_a_tool(demo, monkeypatch):
    monkeypatch.setattr(tools, "ACTIVITY_KEEP", 5)
    for _ in range(8):
        tools.check(str(demo))
    log = demo / ".history" / "activity.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 5
    shutil.rmtree(demo / ".history")
    (demo / ".history").write_text("not a folder", encoding="utf-8")
    res = tools.check(str(demo))
    assert "BLOCKED" in res and (demo / ".history").is_file()


def test_calls_without_a_project_are_not_logged(demo):
    assert tools.manual().ok
    assert not tools.check("").ok
    assert not (demo / ".history").exists()


# ------------------------------------------------------------------ the server
def test_state_and_history_over_http(served, demo):
    code, head, body = get(served, "/api/state")
    st = json.loads(body)
    assert code == 200 and head["Content-Type"].startswith("application/json") and st["project"]["name"] == "demo"
    assert st["project"]["workspace"] == demo.parent.parent.resolve().as_posix()
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    code, _, body = get(served, "/api/history/1")
    assert code == 200 and json.loads(body)["n"] == 1 and json.loads(body)["tracks"]
    assert get(served, "/api/history/7")[0] == 404
    assert json.loads(get(served, "/api/state")[2])["revision"] != st["revision"]
    code, _, body = get(served, "/api/resolved")
    assert code == 200 and json.loads(body)["durationInFrames"] == st["frames"] and not json.loads(body)["inspect"]


def test_the_index_is_served_or_a_placeholder(served):
    code, head, body = get(served, "/")
    assert code == 200 and head["Content-Type"].startswith("text/html") and body
    assert get(served, "/static/../server.py")[0] == 404


@pytest.mark.parametrize("path", ["/project/project.json", "/project/../project.json", "/project/assets/../project.json",
                                  "/project/assets/%2e%2e/project.json", "/project/../../.env", "/project/.env",
                                  "/project/../../ledger.jsonl", "/project/C:/Windows/win.ini", "/project//etc/passwd",
                                  "/project/assets", "/project/assets/nothing.png", "/project/.history/log.jsonl"])
def test_the_path_fence(served, path):
    assert get(served, path)[0] == 404


def test_a_link_leaving_the_project_is_refused(served, demo, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    try:
        os.symlink(secret, demo / "assets" / "leak.txt")
    except OSError:
        pytest.skip("this system does not let the test make a symlink")
    assert get(served, "/project/assets/leak.txt")[0] == 404


def test_range_requests(served, demo):
    size = (demo / "assets" / "clip.mp4").stat().st_size
    whole = (demo / "assets" / "clip.mp4").read_bytes()
    code, head, body = get(served, "/project/assets/clip.mp4")
    assert code == 200 and body == whole and head["Accept-Ranges"] == "bytes" and head["Content-Type"] == "video/mp4"
    code, head, body = get(served, "/project/assets/clip.mp4", {"Range": "bytes=10-19"})
    assert code == 206 and body == whole[10:20] and head["Content-Range"] == f"bytes 10-19/{size}"
    code, _, body = get(served, "/project/assets/clip.mp4", {"Range": "bytes=-5"})
    assert code == 206 and body == whole[-5:]
    code, _, body = get(served, "/project/assets/clip.mp4", {"Range": f"bytes={size - 3}-"})
    assert code == 206 and body == whole[-3:]
    assert get(served, "/project/assets/clip.mp4", {"Range": f"bytes={size}-"})[0] == 416


def test_a_foreign_host_is_refused(served):
    assert get(served, "/api/state", {"Host": "evil.example:80"})[0] == 403


def test_events_announce_a_change(served, demo):
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=20)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    first = json.loads(_event(r))
    threading.Timer(0.3, lambda: edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})).start()
    second = json.loads(_event(r))
    assert second["revision"] != first["revision"]
    assert second["revision"] == json.loads(get(served, "/api/state")[2])["revision"]
    conn.close()


def _event(r) -> str:
    """The data of the next "change" event on an event stream."""
    kind = None
    while True:
        line = r.fp.readline().decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: ") and kind == "change":
            return line[6:]


def test_the_player_waits_for_its_bundle(served, monkeypatch):
    monkeypatch.setattr(served.player, "script", Path("no-such-player.mjs"))
    code, _, body = get(served, "/player/index.html")
    assert code == 503 and json.loads(body)["building"] is False and "missing" in json.loads(body)["error"]


def test_still_refuses_while_a_render_runs(served, demo):
    (demo / "build").mkdir(exist_ok=True)
    (demo / "build" / "film.raw.mp4").write_bytes(b"")
    code, _, body = get(served, "/api/still?t=1")
    assert code == 503 and json.loads(body)["busy"] is True


@needs_ffmpeg
def test_thumbs_and_waves(served, demo):
    code, head, body = get(served, "/api/thumb?asset=clip&t=0.5&h=48")
    assert code == 200 and head["Content-Type"] == "image/jpeg" and body[:2] == b"\xff\xd8"
    assert get(served, "/api/thumb?asset=photo")[0] == 200
    assert list((demo / "build" / "watch" / "thumbs").iterdir())
    assert get(served, "/api/thumb?asset=bed")[0] == 404 and get(served, "/api/thumb?asset=../x")[0] == 400
    wave = json.loads(get(served, "/api/wave?asset=voice")[2])
    assert wave["duration"] > 1 and 0 < len(wave["peaks"]) <= 4000 and max(wave["peaks"]) <= 1
    assert abs(len(wave["peaks"]) - wave["duration"] * 100) <= 1
    assert json.loads(get(served, "/api/wave?asset=bed")[2])["peaks"]


@needs_renderer
def test_a_still_of_the_film(served):
    code, head, body = get(served, "/api/still?t=1&w=320")
    assert code == 200 and head["Content-Type"] == "image/jpeg" and body[:2] == b"\xff\xd8"
    t0 = time.time()
    assert get(served, "/api/still?t=1&w=320")[2] == body and time.time() - t0 < 2      # cached


def test_a_workspace_lists_its_projects(demo):
    srv = W.serve(demo.parent.parent)
    try:
        rows = json.loads(get(srv, "/api/projects")[2])
        assert [r["name"] for r in rows] == ["demo"] and rows[0]["title"] == "一杯奶茶的成本" and rows[0]["duration"]
        code, _, body = get(srv, "/p/demo/api/state")
        st = json.loads(body)
        assert code == 200 and st["project"]["name"] == "demo"
        assert next(a for a in st["assets"] if a["id"] == "photo")["url"] == "/p/demo/project/assets/photo.png"
        assert get(srv, "/p/demo/project/assets/photo.png")[0] == 200
        assert get(srv, "/p/nope/api/state")[0] == 404 and get(srv, "/p/../api/state")[0] == 404
        assert b"demo" in get(srv, "/")[2]
        page = {"Referer": f"{srv.url}p/demo/"}              # the window asks by absolute path
        assert json.loads(get(srv, "/api/state", page)[2])["project"]["name"] == "demo"
        code, head, _ = get(srv, "/player/index.html", page)
        assert code == 302 and head["Location"] == "/p/demo/player/index.html"
        assert get(srv, "/api/state")[0] == 404
    finally:
        srv.stop()


def test_the_watch_command(monkeypatch, demo, capsys):
    started = {}

    def fake_forever(self):
        started["url"] = self.url
        raise KeyboardInterrupt
    monkeypatch.setattr(W.WatchServer, "serve_forever", fake_forever)
    opened = []
    monkeypatch.setattr(W.webbrowser, "open", opened.append)
    assert cli.main(["watch", str(demo), "--no-open"]) == 0
    assert started["url"] in capsys.readouterr().out and opened == []
    assert cli.main(["watch", str(demo)]) == 0 and opened
    assert cli.main(["watch", str(demo / "assets")]) == 2
    assert cli.command_parser("watch").parse_args([str(demo), "--port", "0"]).port == 0
