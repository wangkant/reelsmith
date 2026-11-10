import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from reelsmith import cli, media
from reelsmith import resolve as R
from reelsmith import tools
from reelsmith.watch import presence as P
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
    assert set(rows[1]) == {"ts", "tool", "ok", "seconds", "summary", "batch", "files", "text"}
    assert all(len(r["summary"]) <= 300 and "\n" not in r["summary"] for r in rows)
    assert rows[2]["text"] == str(bad) and rows[2]["text"].startswith(rows[2]["summary"]) and rows[2]["files"] == []
    assert not (demo / ".history" / "running.json").exists()


def test_a_row_names_the_pictures_the_result_names(demo):
    stills = demo / "build" / "stills"
    stills.mkdir(parents=True)
    for i in range(14):
        (stills / f"still_{i:04d}.png").write_bytes(b"png")
    (stills / "contact.png").write_bytes(b"png")
    root = tools._project(str(demo))
    text = "\n".join([f"- {i}.00s (frame {i}): {stills / f'still_{i:04d}.png'}" for i in range(2)]
                     + [f"contact sheet (dark bands): {(stills / 'contact.png').as_posix()}",
                        "Drew 'photo': assets/photo.png, 1080x1920.", "gone: build/stills/nothing.png",
                        f"outside: {root.parent / 'build' / 'x.png'}", "not a picture: assets/clip.mp4"])
    assert tools.named_files(root, text) == ["build/stills/still_0000.png", "build/stills/still_0001.png",
                                             "build/stills/contact.png", "assets/photo.png"]
    many = "\n".join(str(stills / f"still_{i:04d}.png") for i in range(14)) + f"\n{stills / 'contact.png'}"
    got = tools.named_files(root, many)
    assert len(got) == 12 and got[-1] == "build/stills/contact.png" and got[0] == "build/stills/still_0000.png"
    assert tools.named_files(root, "x", ["assets/photo.png"]) == ["assets/photo.png"]      # an animated clip's source


def test_a_key_in_a_result_is_masked_before_it_is_logged(demo):
    key, token = "sk-" + "a1B2c3D4e5" * 4, "abcDEF123456ghiJKL"
    result = tools.ToolResult(f"provider said {key} was refused\nretry with Bearer {token} later", False)
    tools._log_activity(str(demo), "draw", result, 0.5, None)
    raw = (demo / ".history" / "activity.jsonl").read_text(encoding="utf-8")
    row = S.activity_of(demo)[-1]
    assert key not in raw and token not in raw
    assert row["summary"] == "provider said [redacted] was refused" and "Bearer [redacted]" in row["text"]


def test_a_long_result_keeps_its_first_4000_characters(demo):
    tools._log_activity(str(demo), "check", tools.ToolResult("x" * 5000), 0.1, None)
    row = S.activity_of(demo)[-1]
    assert len(row["text"]) == 4000 and len(row["summary"]) == 300


# ------------------------------------------------------------------ the call at work
def test_a_call_says_it_is_running_until_it_ends(demo):
    seen = []

    def slow(project):
        seen.append(json.loads((demo / ".history" / "running.json").read_text(encoding="utf-8")))
        tools._progress("film", 0.5)
        seen.append(P.running(demo))
        tools._progress("film", 0.51)                  # progress alone waits a moment before it is written
        seen.append(P.running(demo))
        return "done"
    assert tools.tool(slow)(str(demo)) == "done"
    assert set(seen[0]) == {"tool", "since", "pid", "stage", "progress"}
    assert seen[0]["tool"] == "slow" and seen[0]["pid"] == os.getpid() and seen[0]["stage"] is None
    assert seen[1]["stage"] == "film" and seen[1]["progress"] == 0.5 and seen[1]["seconds"] >= 0
    assert seen[2]["progress"] == 0.5
    assert not (demo / ".history" / "running.json").exists() and P.running(demo) is None
    assert S.activity_of(demo)[-1]["tool"] == "slow"


def test_a_dead_or_old_call_is_not_running(demo):
    path = demo / ".history" / "running.json"
    path.parent.mkdir(exist_ok=True)
    row = {"tool": "render", "since": "2026-01-01T10:00:00", "pid": os.getpid(), "stage": "film", "progress": 0.2}
    path.write_text(json.dumps(row), encoding="utf-8")
    assert P.running(demo) is None                                  # over three hours old
    now = int(time.time())
    path.write_text(json.dumps({**row, "since": S._iso(now - 30)}), encoding="utf-8")
    got = P.running(demo, now)
    assert got == {"tool": "render", "since": S._iso(now - 30), "seconds": 30.0, "stage": "film", "progress": 0.2}
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    path.write_text(json.dumps({**row, "since": S._iso(now), "pid": dead.pid}), encoding="utf-8")
    assert P.running(demo) is None and not P.pid_alive(0)


def test_run_tree_hears_each_line_as_it_comes():
    heard = []
    rc, out, _, timed = media.run_tree([sys.executable, "-c", "print('render 5% (1/20 frames)'); print('done')"],
                                       on_line=heard.append)
    assert rc == 0 and not timed and heard == ["render 5% (1/20 frames)", "done"] and out.splitlines() == heard
    steps = []
    listen = W.R._film_listener(lambda stage, p: steps.append((stage, p)))
    for line in ("bundle 50%", "render 45% (9/20 frames)", "render 100% (20/20 frames)"):
        listen(line)
    assert steps == [("film", 0.45), ("film", 1.0)]


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


def _event(r, kinds=("change",)) -> str:
    """The data of the next event of one of `kinds` on an event stream."""
    kind = None
    while True:
        line = r.fp.readline().decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: ") and kind in kinds:
            return line[6:]


def test_events_announce_a_running_call(served, demo):
    path = demo / ".history" / "running.json"
    path.parent.mkdir(exist_ok=True)
    row = {"tool": "render", "since": S._iso(time.time()), "pid": os.getpid(), "stage": "layout", "progress": 0.1}
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=20)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    assert json.loads(_event(r))["running"] is None
    path.write_text(json.dumps(row), encoding="utf-8")
    got = json.loads(_event(r, ("running",)))
    assert got["tool"] == "render" and got["stage"] == "layout" and got["progress"] == 0.1
    st = json.loads(get(served, "/api/state")[2])
    assert st["running"]["stage"] == "layout" and st["running"]["seconds"] >= 0
    path.write_text(json.dumps({**row, "stage": "film", "progress": 0.0}), encoding="utf-8")
    assert json.loads(_event(r, ("running",)))["stage"] == "film"            # a new stage: at once
    t0 = time.monotonic()
    path.write_text(json.dumps({**row, "stage": "film", "progress": 0.3}), encoding="utf-8")
    assert json.loads(_event(r, ("running",)))["progress"] == 0.3
    assert time.monotonic() - t0 >= W.RUNNING_PUSH_S - 0.6                  # progress alone: at most once a second
    path.unlink()
    assert json.loads(_event(r, ("running",))) is None
    assert json.loads(get(served, "/api/state")[2])["running"] is None
    conn.close()


def test_the_summary_at_a_glance(demo):
    st = S.build_state(demo)
    sm = st["summary"]
    assert set(sm) == {"clips", "tracks", "narrated_s", "covered", "errors", "warnings", "batches"}
    assert sm["tracks"] == len(st["tracks"]) and sm["clips"] == sum(len(t["clips"]) for t in st["tracks"])
    assert sm["errors"] == sum(i["level"] == "error" for i in st["issues"]) and sm["batches"] == 0
    assert 0 < sm["narrated_s"] <= st["voice"]["duration"] and 0 < sm["covered"] <= 1
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    assert S.build_state(demo)["summary"]["batches"] == 1
    film = {"tracks": [{"kind": "visual", "hidden": False, "clips": [{"start": 0, "end": 4}, {"start": 2, "end": 6}]},
                       {"kind": "visual", "hidden": True, "clips": [{"start": 6, "end": 10}]},
                       {"kind": "audio", "hidden": False, "clips": [{"start": 0, "end": 10}]}],
            "duration": 10.0, "voice": None, "issues": [], "history": []}
    assert S.summary_of(film)["covered"] == 0.6 and S.summary_of(film)["narrated_s"] == 0


def test_the_window_icon_is_served(served):
    code, head, body = get(served, "/favicon.ico")
    assert code == 200 and body[:4] == b"\x00\x00\x01\x00"
    assert get(served, "/static/favicon.svg")[1]["Content-Type"] == "image/svg+xml"


# ------------------------------------------------------------------ opening by itself
@pytest.fixture
def opener(monkeypatch):
    """Auto-open allowed in this test, the window available, and launches recorded instead of made."""
    from reelsmith.watch import window
    monkeypatch.setattr(P, "ALLOW_UNDER_PYTEST", True)
    monkeypatch.setattr(P, "_DECIDED", set())
    monkeypatch.setattr(window, "available", lambda: True)
    monkeypatch.delenv(P.WATCH_ENV, raising=False)
    launched = []
    monkeypatch.setattr(P, "launch", launched.append)
    return launched


def test_the_first_call_opens_the_window_when_asked(demo, opener, monkeypatch):
    assert P.OPENED_LINE not in tools.check(str(demo)) and opener == []           # nobody asked
    monkeypatch.setattr(P, "_DECIDED", set())
    monkeypatch.setenv(P.WATCH_ENV, "1")
    first = tools.check(str(demo))
    assert str(first).endswith("\n" + P.OPENED_LINE) and not first.ok and opener == [demo.resolve()]
    assert P.OPENED_LINE not in tools.check(str(demo)) and len(opener) == 1     # once per project per process
    fresh = demo.parent / "fresh"
    made = tools.new_project(str(fresh))
    assert made.ok and str(made).endswith(P.OPENED_LINE) and opener[-1] == fresh.resolve()
    assert S.activity_of(fresh)[-1]["text"].endswith(P.OPENED_LINE)


def test_a_workspace_can_ask_for_the_window(demo, opener):
    (demo.parent.parent / "workspace.json").write_text('{"watch": true}', encoding="utf-8")
    assert str(tools.check(str(demo))).endswith(P.OPENED_LINE) and len(opener) == 1


def test_no_second_window_and_never_under_pytest(demo, opener, monkeypatch):
    monkeypatch.setenv(P.WATCH_ENV, "1")
    P.record_window(demo, "http://127.0.0.1:1/")                 # this process is alive: a window is open
    assert P.OPENED_LINE not in tools.check(str(demo)) and opener == []
    P.forget_window(demo)
    monkeypatch.setattr(P, "_DECIDED", set())
    monkeypatch.setattr(P, "ALLOW_UNDER_PYTEST", False)
    assert P.OPENED_LINE not in tools.check(str(demo)) and opener == []
    monkeypatch.setattr(P, "ALLOW_UNDER_PYTEST", True)
    from reelsmith.watch import window
    monkeypatch.setattr(window, "available", lambda: False)      # no desktop window: never a browser tab
    assert P.OPENED_LINE not in tools.check(str(demo)) and opener == []


def test_a_launch_that_fails_never_fails_the_tool(demo, opener, monkeypatch):
    monkeypatch.setenv(P.WATCH_ENV, "1")
    monkeypatch.setattr(P, "launch", lambda root: (_ for _ in ()).throw(OSError("no python")))
    res = tools.check(str(demo))
    assert "BLOCKED" in res and P.OPENED_LINE not in res


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
        if threading.current_thread() is threading.main_thread():
            raise KeyboardInterrupt
    monkeypatch.setattr(W.WatchServer, "serve_forever", fake_forever)
    opened = []
    monkeypatch.setattr(W.webbrowser, "open", opened.append)
    from reelsmith.watch import window
    shown = []
    monkeypatch.setattr(window, "open_window", lambda url, title, ready=None: shown.append((url, title)))
    monkeypatch.setattr(W.WatchServer, "shutdown", lambda self: None)
    assert cli.main(["watch", str(demo), "--no-open"]) == 0
    assert started["url"] in capsys.readouterr().out and opened == [] and shown == []
    monkeypatch.setattr(window, "available", lambda: True)          # the app extra is installed: a desktop window
    assert cli.main(["watch", str(demo)]) == 0 and opened == []
    assert shown[0][0].startswith("http://127.0.0.1:") and shown[0][1].startswith("reelsmith · ")
    assert cli.main(["watch", str(demo), "--browser"]) == 0 and len(opened) == 1 and len(shown) == 1
    monkeypatch.setattr(window, "available", lambda: False)         # without it: the browser, and how to get the window
    assert cli.main(["watch", str(demo)]) == 0 and len(opened) == 2
    assert 'pip install "reelsmith[app]"' in capsys.readouterr().out
    assert cli.main(["watch", str(demo / "assets")]) == 2
    assert cli.command_parser("watch").parse_args([str(demo), "--port", "0"]).port == 0


def test_one_window_per_project(monkeypatch, demo, capsys):
    from reelsmith.watch import window
    monkeypatch.setattr(window, "available", lambda: True)
    monkeypatch.setattr(W.WatchServer, "shutdown", lambda self: None)
    monkeypatch.setattr(W.WatchServer, "serve_forever", lambda self: None)
    seen = []
    monkeypatch.setattr(window, "open_window", lambda url, title, ready=None: seen.append(P.window_of(demo)))
    assert cli.main(["watch", str(demo)]) == 0
    assert seen[0]["pid"] == os.getpid() and seen[0]["url"].startswith("http://127.0.0.1:")    # recorded while open
    assert P.window_of(demo) is None and not (demo / P.WINDOW).exists()                        # and gone after
    P.record_window(demo, "http://127.0.0.1:9/")                       # another window on it is open
    capsys.readouterr()
    assert cli.main(["watch", str(demo / "project.json")]) == 0 and len(seen) == 1
    assert "already open (http://127.0.0.1:9/" in capsys.readouterr().out
    opened = []
    monkeypatch.setattr(W.webbrowser, "open", opened.append)
    monkeypatch.setattr(W.WatchServer, "serve_forever", lambda self: (_ for _ in ()).throw(KeyboardInterrupt))
    assert cli.main(["watch", str(demo), "--browser"]) == 0 and len(opened) == 1             # as asked
    assert P.window_of(demo)["url"] == "http://127.0.0.1:9/"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (demo / P.WINDOW).write_text(json.dumps({"pid": dead.pid, "url": "x"}), encoding="utf-8")
    assert P.window_of(demo) is None
    monkeypatch.setattr(W.WatchServer, "serve_forever", lambda self: None)
    assert cli.main(["watch", str(demo)]) == 0 and len(seen) == 2                            # a dead one is ignored


def test_the_feed_has_a_row_for_every_batch_the_log_missed():
    history = [{"n": 1, "at": "2026-01-01T10:00:00", "summary": "added clip a"},
               {"n": 2, "at": "2026-01-01T10:05:00", "summary": "moved clip a"}]
    logged = [{"ts": "2026-01-01T10:05:00", "tool": "edit", "ok": True, "seconds": 0.2, "summary": "applied", "batch": 2},
              {"ts": "2026-01-01T10:06:00", "tool": "check", "ok": True, "seconds": 0.1, "summary": "OK", "batch": None}]
    feed = S.with_batches(logged, history)
    assert [(r["tool"], r["batch"]) for r in feed] == [("edit", 1), ("edit", 2), ("check", None)]
    assert feed[0]["summary"] == "added clip a" and S.with_batches(logged, history[1:]) is logged
