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
from reelsmith.watch import chat as C
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
    assert st["spend"] == {"project_usd": 0, "project_budget_usd": 1.0, "chat_usd": 0.0, "chat_budget_usd": 5.0}
    assert st["activity"] == [] and st["history"] == []
    assert st["result"]["state"] == "none" and st["result"]["reason_code"] == "result.none"
    assert st["can_undo"] is False and st["can_redo"] is False and st["latest_batch"] is None


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


def test_a_render_s_frame_progress_reaches_running_json(demo, monkeypatch):
    # render.mjs's lines are heard on run_tree's reader thread, not on the tool call's own
    seen = []

    def fake_render(root, progress):
        progress("film", 0.0)
        script = "import time; time.sleep(0.4); print('render 40% (8/20 frames)', flush=True); time.sleep(0.6)"
        media.run_tree([sys.executable, "-c", script], on_line=W.R._film_listener(progress))
        seen.append(json.loads((demo / ".history" / "running.json").read_text(encoding="utf-8")))
        return {"ok": False, "stage": "infra", "error": "stopped by the test"}
    monkeypatch.setattr(tools.R, "render", fake_render)
    tools.render(str(demo))
    assert seen and seen[0]["stage"] == "film" and seen[0]["progress"] == 0.4


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
    with W.R.project_lock(demo / "build"):
        assert W.render_busy(demo)
        code, _, body = get(served, "/api/still?t=1")
    assert code == 202 and json.loads(body)["busy"] is True        # pending, not a failure: the page asks again
    assert not W.render_busy(demo)


def test_a_copied_project_is_not_rendering(demo):
    # copy order leaves the resolved film newer than the report, and a raw film behind: no lock is held
    build = demo / "build"
    build.mkdir(exist_ok=True)
    (build / "report.json").write_text("{}", encoding="utf-8")
    (build / "film.raw.mp4").write_bytes(b"")
    (build / "resolved.film.json").write_text("{}", encoding="utf-8")
    (build / "render.lock").write_bytes(b"")
    assert not W.render_busy(demo)


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
        code, head, body = get(srv, "/")
        assert code == 200 and head["Content-Type"].startswith("text/html") and b"home.js" in body
        page = {"Referer": f"{srv.url}p/demo/"}              # the window asks by absolute path
        assert json.loads(get(srv, "/api/state", page)[2])["project"]["name"] == "demo"
        code, head, _ = get(srv, "/player/index.html", page)
        assert code == 302 and head["Location"] == "/p/demo/player/index.html"
        assert get(srv, "/api/state")[0] == 404
    finally:
        srv.stop()


@pytest.fixture
def ws_served(demo):
    srv = W.serve(demo.parent.parent)
    yield srv, demo.parent.parent
    srv.stop()


def test_the_home_lists_every_project_newest_first(ws_served, demo):
    srv, ws = ws_served
    assert tools.new_project(str(ws / "projects" / "fresh")).ok
    old = time.time() - 3600
    for f in demo.rglob("*"):
        os.utime(f, (old, old))
    home = json.loads(get(srv, "/api/home")[2])
    assert home["workspace"] == {"name": ws.name, "path": ws.resolve().as_posix()}
    assert [p["name"] for p in home["projects"]] == ["fresh", "demo"]
    fresh, d = home["projects"]
    # a project with nothing on it yet waits for its first clip; it is not broken and has no poster
    assert fresh["empty"] is True and fresh["poster"] is None and fresh["result"]["state"] == "none"
    assert d["empty"] is False and d["valid"] and d["title"] == "一杯奶茶的成本" and d["duration"]
    assert d["url"] == "/p/demo/" and d["canvas"]["width"] and d["working"] is None
    assert d["poster"].startswith("/p/demo/api/frame?t=") and f"v={d['revision'][:12]}" in d["poster"]
    assert d["modified"] < fresh["modified"]
    assert home["names"]["max"] == 64 and "con" in home["names"]["reserved"]
    assert [p["name"] for p in json.loads(get(srv, "/api/projects")[2])] == ["fresh", "demo"]
    assert get(srv, "/api/home", {"Origin": "http://evil.example"})[0] == 403


def test_the_home_says_where_work_is_running(ws_served, demo):
    srv, _ = ws_served
    mark = P.Running(demo, "render").start()
    try:
        d = json.loads(get(srv, "/api/home")[2])["projects"][0]
        assert d["working"]["tool"] == "render" and d["working"]["by"] == "agent"
    finally:
        mark.end()
    assert json.loads(get(srv, "/api/home")[2])["projects"][0]["working"] is None


def test_a_new_film_from_the_home(ws_served, demo):
    srv, ws = ws_served
    (ws / "workspace.json").write_text('{"profile": "vertical"}', encoding="utf-8")
    code, body = post(srv, "/api/projects", {"name": "harbor_2"})
    assert code == 201 and body["url"] == "/p/harbor_2/"
    made = ws / "projects" / "harbor_2"
    assert (made / "project.json").is_file()
    assert json.loads(get(srv, "/p/harbor_2/api/state")[2])["canvas"]["profile"] == "vertical"
    assert "harbor_2" in [p["name"] for p in json.loads(get(srv, "/api/home")[2])["projects"]]
    for name, status, why in [("../escape", 400, "create.chars"), ("a/b", 400, "create.chars"),
                              ("-dash", 400, "create.chars"), ("", 400, "create.empty"), (None, 400, "create.empty"),
                              ("x" * 65, 400, "create.long"), ("nul", 400, "create.reserved"),
                              ("DEMO", 409, "create.taken"), ("harbor_2", 409, "create.taken")]:
        code, body = post(srv, "/api/projects", {"name": name})
        assert (code, body["code"]) == (status, why), name
        assert body["error"] == W.S.say(why, name=name or "")["text"]
    assert sorted(p.name for p in (ws / "projects").iterdir()) == ["demo", "harbor_2"]
    assert not (ws / "escape").exists()


def test_a_new_film_needs_the_token_and_this_origin(ws_served):
    srv, ws = ws_served
    assert post(srv, "/api/projects", {"name": "a1"}, token=False)[0] == 403
    assert post(srv, "/api/projects", {"name": "a2"}, headers={W.TOKEN_HEADER: "not-the-token"})[0] == 403
    assert post(srv, "/api/projects", {"name": "a3"}, origin=False)[0] == 403
    assert post(srv, "/api/projects", {"name": "a4"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert post(srv, "/api/projects", {"name": "a5"}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert post(srv, "/api/projects", b"not json")[0] == 400
    assert sorted(p.name for p in (ws / "projects").iterdir()) == ["demo"]
    assert json.loads(get(srv, "/api/session")[2])["token"] == srv.token


def test_the_home_hears_of_a_new_project(ws_served):
    srv, ws = ws_served
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
    conn.request("GET", "/api/home/events")
    r = conn.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    threading.Timer(1.2, lambda: tools.new_project(str(ws / "projects" / "outside_the_window"))).start()
    assert json.loads(_event(r, ("projects",)))["seq"] >= 1
    assert "outside_the_window" in [p["name"] for p in json.loads(get(srv, "/api/home")[2])["projects"]]
    conn.close()


def test_listing_the_home_makes_no_site(ws_served, demo, monkeypatch):
    srv, ws = ws_served
    assert tools.new_project(str(ws / "projects" / "fresh")).ok
    probed = []
    real = W.render_busy
    monkeypatch.setattr(W, "render_busy", lambda root: probed.append(root) or real(root))
    rows = json.loads(get(srv, "/api/home")[2])["projects"]
    assert {r["name"] for r in rows} == {"demo", "fresh"} and srv.sites == {}
    probed.clear()
    srv.home_signature(), srv.home_signature(scan=False)
    assert probed == [] and srv.sites == {}
    # a picture alone makes a site that is not polled and has no chat; its page opens it
    assert get(srv, "/p/demo/project/assets/photo.png")[0] == 200
    site = srv.sites["demo"]
    assert site.opened is False and site._chat is None
    polled = []
    monkeypatch.setattr(W.Site, "poll", lambda self: polled.append(self.root.name))
    time.sleep(W.POLL_S * 3)
    assert polled == []
    assert get(srv, "/p/demo/api/state")[0] == 200
    assert site.opened is True and site._chat is None
    _wait_for(lambda: "demo" in polled, 5)
    assert "fresh" not in srv.sites


def test_the_home_hears_of_work_on_a_project_nobody_opened(ws_served, demo):
    srv, _ = ws_served
    before = srv.home_signature()
    mark = P.Running(demo, "render").start()
    try:
        assert srv.home_signature(scan=False) == before          # between scans the last reading stands
        assert srv.home_signature() != before
        assert json.loads(get(srv, "/api/home")[2])["projects"][0]["working"]["tool"] == "render"
    finally:
        mark.end()
    assert srv.home_signature() == before and srv.sites == {}


def test_an_empty_film_has_no_poster():
    st = {"canvas": {"width": 1080, "height": 1920}, "tracks": [], "valid": True, "error": None, "duration": 3.0,
          "render": {"delivered": None}, "project": {"title": None}, "result": {"state": "none", "accepted": None},
          "revision": "abc"}
    facts = W.card_facts(st, "/p/x")
    assert facts["empty"] is True and facts["poster"] is None


def _another_process():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_a_film_held_by_another_process_refuses_changes(demo):
    srv = W.serve(demo)
    other = _another_process()
    record = demo / "build" / "watch" / "window.json"
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"pid": other.pid, "url": "http://127.0.0.1:9/"}), encoding="utf-8")
        held = {"code": "owner.elsewhere", "params": {"url": "http://127.0.0.1:9/", "pid": other.pid},
                "error": S.say("owner.elsewhere", url="http://127.0.0.1:9/")["text"]}
        assert post(srv, "/api/chat", {"message": "Shorten the opening."}) == (409, held)
        assert post(srv, "/api/action", {"action": "check"}) == (409, held)
        assert post(srv, "/api/accept", {}) == (409, held)
        code, body = post(srv, "/api/action", {"action": "stop"})       # its own turn can always be stopped
        assert code == 200 and body["stopped"] is False
        assert srv.sites[None]._chat is None
        other.kill()
        other.wait()
        # nobody holds it now: the first change records this server, and stopping the server forgets it
        assert post(srv, "/api/action", {"action": "check"})[0] == 202
        assert json.loads(record.read_text(encoding="utf-8")) == {"pid": os.getpid(), "url": srv.url}
        assert srv.sites[None].wait_action(30)
    finally:
        other.kill()
        srv.stop()
    assert not record.exists()


def test_the_same_process_keeps_its_own_film(demo):
    # the terminal session records the film for its process; its own server's page goes on working
    P.record_window(demo, "http://127.0.0.1:1/p/demo/")
    srv = W.serve(demo.parent.parent)
    try:
        assert post(srv, "/p/demo/api/action", {"action": "check"})[0] == 202
        assert srv.sites["demo"].wait_action(30)
        assert P.window_of(demo)["url"] == "http://127.0.0.1:1/p/demo/"      # not taken over
    finally:
        srv.stop()
    assert P.window_of(demo) is not None                                   # the session forgets its own record
    P.forget_window(demo)


def test_a_film_made_in_the_window_opens_no_second_window(ws_served):
    srv, ws = ws_served
    assert post(srv, "/api/projects", {"name": "harbor_3"})[0] == 201
    assert os.path.normcase(str((ws / "projects" / "harbor_3").resolve())) in P._DECIDED
    P.skip_auto_open(ws / "projects" / "other")
    assert os.path.normcase(str(ws / "projects" / "other")) in P._DECIDED


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


def test_the_feed_is_capped_however_many_batches_there_are():
    history = [{"n": n, "at": f"2026-01-01T10:{n:02d}:00", "summary": f"batch {n}"} for n in range(1, 50)]
    logged = [{"ts": f"2026-01-01T10:{m:02d}:30", "tool": "check", "ok": True, "batch": None} for m in range(40, 45)]
    feed = S.with_batches(logged, history, limit=5)
    # the log was cut to the limit: only batches since its oldest row join, and the feed stays at the limit
    assert len(feed) == 5 and feed[-1]["ts"] == "2026-01-01T10:49:00"
    assert all(r["ts"] >= "2026-01-01T10:40:30" for r in feed)
    short = S.with_batches(logged[:2], history, limit=300)
    assert len(short) == 51                       # a log that was not cut still gets every batch it missed


def test_the_feed_reads_paths_relative_and_masks_keys(demo):
    ws = demo.parent.parent
    key = "sk-" + "Zz9Yy8Xx7W" * 4
    row = {"ts": "2026-01-01T10:00:00", "tool": "new_project", "ok": False, "seconds": 0.1, "batch": None,
           "summary": f"created {demo / 'project.json'} in workspace {ws}",
           "text": f"failed: {demo.as_posix()}/assets/a.png and {(demo.parent / 'demo2').as_posix()} with {key}",
           "files": []}
    log = demo / ".history" / "activity.jsonl"
    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps(row) + "\n", encoding="utf-8")
    got = S.activity_of(demo)[-1]
    assert got["summary"] == "created project.json in workspace <workspace>"
    assert got["text"] == "failed: assets/a.png and <workspace>/projects/demo2 with [redacted]"
    assert S.build_state(demo)["activity"][-1]["text"] == got["text"]
    # and what a tool call writes has no folder of the machine in it to begin with
    tools._log_activity(str(demo), "new_project", tools.ToolResult(row["summary"], True), 0.1, None)
    raw = log.read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(raw)["text"] == "created project.json in workspace <workspace>" and str(ws) not in raw


# ------------------------------------------------------------------ requests from elsewhere, bad requests
def test_requests_from_another_site_are_refused(served):
    assert get(served, "/api/state", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert get(served, "/api/state", {"Sec-Fetch-Site": "same-site"})[0] == 403      # another port on this host
    assert get(served, "/api/state", {"Origin": "http://evil.example"})[0] == 403
    assert get(served, "/project/assets/clip.mp4", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert get(served, "/api/still?t=1", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert get(served, "/api/session", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    # the page itself, an address-bar visit and the page's own requests
    assert get(served, "/", {"Sec-Fetch-Site": "cross-site"})[0] == 200
    assert get(served, "/api/state", {"Sec-Fetch-Site": "none"})[0] == 200
    own = f"http://127.0.0.1:{served.port}"
    code, head, _ = get(served, "/api/state", {"Sec-Fetch-Site": "same-origin", "Origin": own})
    assert code == 200 and head["Cross-Origin-Resource-Policy"] == "same-origin"
    assert not any(k.lower().startswith("access-control-") for k in head)


def test_bad_requests_get_an_answer(served):
    assert get(served, "/project/assets/photo.png%00.txt")[0] == 404
    assert get(served, "/api/still?t=nan")[0] == 400
    code, _, body = get(served, "/api/still?t=1e308&w=1e308")
    assert code in (200, 503) and (code == 200 or json.loads(body)["error"])
    assert get(served, "/api/thumb?asset=clip&t=1e308&h=1e308")[0] in (200, 404, 503)
    assert get(served, "/api/history/99999999999999999999999")[0] == 404


def test_a_still_is_cached_by_what_draws_it(served, demo):
    site = served.site(None)
    st = site.cache.get()
    first = site.still_key(st, "film")
    assert site.still_key(st, "film") == first
    photo = demo / "assets" / "photo.png"
    os.utime(photo, (time.time() + 5, time.time() + 5))         # replaced in place
    assert site.still_key(st, "film") != first
    second = site.still_key(st, "film")
    (demo.parent.parent / "library" / "components" / "Card.tsx").write_text("export default () => null;\n",
                                                                           encoding="utf-8")
    served.player._checked = 0.0
    assert site.still_key(st, "film") != second
    assert S.build_state(demo)["library"] != st["library"]    # and the window hears of a component edit


def test_a_player_build_leaves_other_windows_their_builds(tmp_path):
    player = W.Player(tmp_path / "player", None)
    (tmp_path / "player").mkdir()
    now = time.time()
    folders = {}
    for name, age in (("new", 0), ("recent", 60), ("old", W.PLAYER_KEEP_S + 60),
                      ("busy.build-1", W.PLAYER_BUILD_S + 60), ("dead.build-2", 2 * W.PLAYER_BUILD_S + 60)):
        folders[name] = tmp_path / "player" / name
        folders[name].mkdir()
        os.utime(folders[name], (now - age, now - age))
    player._tidy(folders["new"])
    # another window's build in progress and a build it may still serve stay
    assert sorted(p.name for p in (tmp_path / "player").iterdir()) == ["busy.build-1", "new", "recent"]


# ------------------------------------------------------------------ the chat
OBJ = {"type": "object", "properties": {}}


class FakeClient:
    """One scripted step per model call: a reply dict, or a callable(messages) -> reply."""

    def __init__(self, *script):
        self.script, self.calls, self.on_retry = list(script), [], None

    def complete(self, messages, tools):
        self.calls.append(json.loads(json.dumps(messages)))
        step = self.script.pop(0)
        return step(messages) if callable(step) else step


def reply(text=None, calls=(), cost=0.01):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    return {"message": msg, "finish_reason": "tool_calls" if calls else "stop",
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost_usd": cost}}


class Tools:
    """noop answers; hold waits until the turn is stopped; broken fails."""

    def __init__(self):
        self.entered = threading.Event()
        self.stop = None

    def __call__(self, project, ws, scope, web):
        from dataclasses import dataclass

        @dataclass
        class Result:
            text: str
            error: bool = False
            images: tuple = ()

        @dataclass
        class Tool:
            name: str
            description: str
            parameters: dict
            run: object

        def hold(args):
            self.entered.set()
            for _ in range(200):
                if self.stop is not None and self.stop.is_set():
                    break
                time.sleep(0.05)
            return Result("held")
        return [Tool("noop", "nothing", OBJ, lambda a: Result("nothing changed")), Tool("hold", "waits", OBJ, hold),
                Tool("broken", "fails", OBJ, lambda a: Result("error: it broke", True))]


@pytest.fixture
def chat_demo(demo, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "REELSMITH_PROXY"):
        monkeypatch.delenv(name, raising=False)
    ws = demo.parent.parent
    (ws / "workspace.json").write_text(json.dumps({"runner": {"engine": "api", "budget_usd": 1}}), encoding="utf-8")
    (ws / ".env").write_text("OPENROUTER_API_KEY=sk-or-test-1234567\n", encoding="utf-8")
    return demo


def only_api(engine, ws):
    return (True, "fake") if engine == "api" else (False, f"{engine} is not here")


def make_chat(root, client, tools=None):
    heard = []
    chat = C.Chat(root, heard.append, client_factory=lambda s: client, tools_factory=tools or Tools(),
                  engines_fn=only_api)
    return chat, heard


def roles(rows):
    return [(r["role"], r.get("tool") or r.get("kind") or r["text"]) for r in rows]


def test_a_turn_streams_its_rows_in_order(chat_demo):
    client = FakeClient(reply("Looking at it.", [("noop", {"project": str(chat_demo), "id": "sb"}), ("broken", {})]),
                        reply("Nothing needed changing."))
    chat, heard = make_chat(chat_demo, client)
    assert chat.send("What is at 10 s?", context={"clip": "sb", "start": 7.6, "end": 16.81, "playhead": 13.4,
                                                  "junk": "x"}) == 1
    assert chat.wait(20)
    rows = chat.status()["messages"]
    assert roles(rows) == [("user", "What is at 10 s?"), ("assistant", "Looking at it."), ("tool", "noop"),
                           ("tool", "broken"), ("assistant", "Nothing needed changing."), ("note", "end")]
    assert rows[0]["context"] == {"clip": "sb", "start": 7.6, "end": 16.81, "playhead": 13.4}
    assert rows[2]["text"] == "sb" and rows[2]["ok"] is True                     # the project is left out
    assert rows[3]["ok"] is False and "it broke" in rows[3]["detail"]
    assert rows[-1]["cost_usd"] == 0.02 and "$0.02" in rows[-1]["text"] and all(r["turn"] == 1 for r in rows)
    # the window heard each row as it came (a tool row once when called and again when answered)
    seen = [(r["id"], r["ok"]) for p in heard for r in p["rows"]]
    assert seen.index((3, None)) < seen.index((3, True)) < seen.index((5, None))
    assert heard[-1]["busy"] is False and heard[0]["busy"] is True
    first = client.calls[0]
    assert "talking to you" in first[0]["content"] and "Nobody is online" not in first[0]["content"]
    assert first[1]["content"].startswith("(reelsmith watch)")
    assert "[selected clip sb (7.60-16.81 s); playhead at 13.40 s]\nWhat is at 10 s?" in first[1]["content"]
    on_disk = [json.loads(ln) for ln in (chat_demo / ".history" / "chat.jsonl").read_text("utf-8").splitlines()]
    assert {r["id"]: r for r in on_disk}[3]["ok"] is True                         # the last copy of a row wins
    assert roles(C.Chat(chat_demo).status()["messages"]) == roles(rows)          # and it reloads the same
    assert not (chat_demo / "build" / "run_state.json").exists()                 # a headless run's state is untouched


def test_a_selected_beat_goes_with_the_message(chat_demo):
    client = FakeClient(reply("Noted."))
    chat, _ = make_chat(chat_demo, client)
    chat.send("Shorten this.", context={"beat": 3, "start": 5.62, "end": 8.22, "playhead": 6.0})
    assert chat.wait(20)
    assert chat.status()["messages"][0]["context"] == {"beat": 3, "start": 5.62, "end": 8.22, "playhead": 6.0}
    assert "[selected beat 3 (5.62-8.22 s)]\nShorten this." in client.calls[0][1]["content"]


def test_the_next_message_resumes_the_same_session(chat_demo):
    client = FakeClient(reply("One."), reply("Two."))
    chat, _ = make_chat(chat_demo, client)
    chat.send("first")
    chat.wait(20)
    sid = json.loads((chat_demo / "build" / "chat_state.json").read_text("utf-8"))["session_id"]
    chat.send("second")
    chat.wait(20)
    state = json.loads((chat_demo / "build" / "chat_state.json").read_text("utf-8"))
    assert sid and state["session_id"] == sid and state["cost_usd"] == 0.02
    again = client.calls[1]
    assert [m["role"] for m in again] == ["system", "user", "assistant", "user"] and again[-1]["content"] == "second"
    assert chat.status()["spent_usd"] == 0.02 and chat.status()["budget_usd"] == 1


def test_stop_ends_a_turn_and_the_next_message_works(chat_demo):
    tools = Tools()
    client = FakeClient(reply("Working.", [("hold", {})]), reply("Back again."))
    chat, heard = make_chat(chat_demo, client, tools)
    tools.stop = chat._stop
    assert chat.stop() is False                                     # nothing runs
    chat.send("do it")
    assert tools.entered.wait(10)
    with pytest.raises(C.ChatError) as busy:
        chat.send("and this")
    assert busy.value.code == 409
    assert chat.status()["busy"] and chat.stop() is True and heard[-1]["stopping"] is True
    assert chat.wait(10) and not chat.status()["busy"]
    rows = chat.status()["messages"]
    assert rows[-1]["role"] == "note" and rows[-1]["kind"] == "stopped" and len(client.calls) == 1
    assert json.loads((chat_demo / "build" / "chat_state.json").read_text("utf-8"))["status"] == "stopped"
    chat.send("again")
    chat.wait(20)
    assert chat.status()["messages"][-1]["kind"] == "end"
    assert client.calls[1][-1]["content"] == "again" and client.calls[1][1]["content"].startswith("(reelsmith watch)")


def test_a_used_up_budget_is_said_and_runs_nothing(chat_demo):
    (chat_demo / "build").mkdir(exist_ok=True)
    (chat_demo / "build" / "chat_state.json").write_text(json.dumps({"cost_usd": 0.99}), encoding="utf-8")
    client = FakeClient()
    chat, _ = make_chat(chat_demo, client)
    chat.send("anything")
    chat.wait(20)
    note = chat.status()["messages"][-1]
    assert note["kind"] == "budget" and "$1.00 budget is used up" in note["text"] and client.calls == []


def test_what_a_message_may_be(chat_demo):
    chat, _ = make_chat(chat_demo, FakeClient())
    for bad, code in (("", 400), ("   ", 400), ("x" * 8001, 400), (None, 400)):
        with pytest.raises(C.ChatError) as err:
            chat.send(bad)
        assert err.value.code == code
    with pytest.raises(C.ChatError, match="codex is not here"):
        chat.send("hi", engine="codex")
    with pytest.raises(C.ChatError, match="unknown engine"):
        chat.send("hi", engine="gpt")
    status = chat.status()
    assert status["engine"] == "api" and [e["id"] for e in status["engines"]] == ["agent-sdk", "codex", "dsh", "api"]
    assert status["messages"] == [] and status["busy"] is False


def test_which_engine_is_the_default(chat_demo):
    from reelsmith.workspace import Workspace
    ws = Workspace.load(chat_demo.parent.parent)
    rows = [{"id": e, "available": e in ("codex", "api")} for e in C.ENGINE_ORDER]
    assert C.default_engine(rows, ws) == "api"                          # the workspace's, since it can run
    (chat_demo.parent.parent / "workspace.json").write_text('{"runner": {"engine": "dsh"}}', encoding="utf-8")
    assert C.default_engine(rows, Workspace.load(chat_demo.parent.parent)) == "codex"     # else the first that can
    assert C.default_engine([{"id": "api", "available": False}], ws) is None
    ok, why = C.can_run("api", ws)
    assert ok and "openrouter" in why
    (chat_demo.parent.parent / ".env").write_text("", encoding="utf-8")
    ok, why = C.can_run("api", Workspace.load(chat_demo.parent.parent))
    assert not ok and "OPENROUTER_API_KEY is missing" in why



def test_every_engine_reason_is_a_code(chat_demo):
    from reelsmith.workspace import Workspace
    ws = Workspace.load(chat_demo.parent.parent)
    got = C.reason("api", ws)
    assert got["available"] and got["code"] == "engine.api_ready" and set(got["params"]) == {"provider", "model"}
    assert got["why"] == C.REASONS["engine.api_ready"].format(**got["params"])
    rows = C.engine_rows(ws)
    assert [r["id"] for r in rows] == list(C.ENGINE_ORDER)
    assert all(r["code"] in C.REASONS and r["why"] == C.REASONS[r["code"]].format(**r["params"]) for r in rows)
    (chat_demo.parent.parent / ".env").write_text("", encoding="utf-8")
    got = C.reason("api", Workspace.load(chat_demo.parent.parent))
    assert not got["available"] and (got["code"], got["params"]) == ("engine.key_missing", {"key": "OPENROUTER_API_KEY"})
    # a seam answering (available, why), and one that fails
    row = C.engine_row("dsh", ws, only_api)
    assert (row["available"], row["code"], row["params"]) == (False, "engine.other", {"why": "dsh is not here"})
    row = C.engine_row("api", ws, lambda e, w: 1 / 0)
    assert row["code"] == "engine.probe_failed" and "ZeroDivisionError" in row["params"]["error"]
    chat = C.Chat(chat_demo, engines_fn=only_api)
    assert {r["code"] for r in chat.status()["engines"]} == {"engine.other"}


def post(srv, path, body, headers=None, token=True, origin=True):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    hdrs = {"Content-Type": "application/json"}
    if origin:
        hdrs["Origin"] = f"http://127.0.0.1:{srv.port}"
    if token:
        hdrs[W.TOKEN_HEADER] = srv.token
    hdrs.update(headers or {})
    try:
        conn.request("POST", path, body=body if isinstance(body, bytes) else json.dumps(body).encode(), headers=hdrs)
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b"null")
    finally:
        conn.close()


@pytest.fixture
def chat_served(chat_demo):
    tools = Tools()
    client = FakeClient(reply("Working.", [("hold", {})]), reply("All done."))
    srv = W.serve(chat_demo, chat_options={"client_factory": lambda s: client, "tools_factory": tools,
                                           "engines_fn": only_api})
    tools.stop = srv.site(None).chat._stop
    yield srv, tools
    srv.stop()


def test_the_chat_over_http(chat_served):
    srv, tools = chat_served
    token = json.loads(get(srv, "/api/session")[2])["token"]
    assert token == srv.token and len(token) >= 24
    status = json.loads(get(srv, "/api/chat")[2])
    assert status["busy"] is False and status["engine"] == "api" and status["budget_usd"] == 1
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
    conn.request("GET", "/api/events")
    events = conn.getresponse()
    _event(events)
    assert post(srv, "/api/chat", {"message": "hello", "engine": "api"}) == (202, {"turn": 1})
    assert tools.entered.wait(10)
    code, body = post(srv, "/api/chat", {"message": "more"})
    assert code == 409 and "still running" in body["error"]
    assert json.loads(get(srv, "/api/chat")[2])["busy"] is True
    assert post(srv, "/api/chat/stop", {}) == (200, {"stopped": True})
    rows = []
    while not rows or rows[-1]["role"] != "note":
        rows += json.loads(_event(events, ("chat",)))["rows"]
    assert rows[0]["role"] == "user" and rows[-1]["kind"] == "stopped"
    conn.close()
    assert srv.site(None).chat.wait(10)
    assert post(srv, "/api/chat/stop", {}) == (200, {"stopped": False})
    assert post(srv, "/api/chat", {"message": ""})[0] == 400
    assert post(srv, "/api/chat", {"message": "x" * 8001})[0] == 400
    assert post(srv, "/api/chat", {"message": "hi", "engine": "codex"})[0] == 400
    assert post(srv, "/api/chat", b"{not json")[0] == 400
    assert post(srv, "/api/chat", b"x" * (W.MAX_BODY + 1))[0] == 413
    assert post(srv, "/api/nothing", {})[0] == 404


def test_a_change_needs_the_token_and_this_origin(chat_served):
    srv, _ = chat_served
    msg = {"message": "hello"}
    assert post(srv, "/api/chat", msg, token=False)[0] == 403
    assert post(srv, "/api/chat", msg, {W.TOKEN_HEADER: "guess"})[0] == 403
    assert post(srv, "/api/chat", msg, origin=False)[0] == 403
    assert post(srv, "/api/chat", msg, {"Origin": "http://evil.example"})[0] == 403
    assert post(srv, "/api/chat", msg, {"Origin": f"http://127.0.0.1:{srv.port + 1}"})[0] == 403
    assert post(srv, "/api/chat/stop", {}, {"Origin": "null"})[0] == 403
    assert json.loads(get(srv, "/api/chat")[2])["messages"] == []          # none of them reached the chat
    assert post(srv, "/api/chat", msg, {"Origin": f"http://localhost:{srv.port}"})[0] == 202
    for path, body in (("/api/action", {"action": "check"}), ("/api/accept", {}), ("/api/reveal", {})):
        assert post(srv, path, body, token=False)[0] == 403
        assert post(srv, path, body, {"Origin": "http://evil.example"})[0] == 403


def test_chat_refusals_carry_codes(chat_served):
    srv, tools = chat_served
    assert post(srv, "/api/chat", {"message": "go"})[0] == 202
    assert tools.entered.wait(10)
    code, body = post(srv, "/api/chat", {"message": "more"})
    assert code == 409 and body["code"] == "busy.chat" and body["params"] == {"turn": 1}
    srv.site(None).chat.stop()
    assert srv.site(None).chat.wait(10)
    code, body = post(srv, "/api/chat", {"message": "x" * 8001})
    assert body["code"] == "chat.too_long" and body["params"] == {"chars": 8001, "max": 8000}
    assert post(srv, "/api/chat", {"message": "hi", "engine": "gpt"})[1]["code"] == "chat.unknown_engine"
    note = json.loads(get(srv, "/api/chat")[2])["messages"][-1]
    assert note["code"] == "chat.stopped" and note["params"] == {"cost_usd": 0.01}


# ------------------------------------------------------------------ beats
def test_beats_follow_the_narration(demo):
    st = S.build_state(demo)
    beats, lines = st["beats"], st["voice"]["lines"]
    assert [b["line"] for b in beats] == [ln["text"] for ln in lines]
    assert beats[0]["start"] == 0.0 and beats[-1]["end"] == st["duration"]
    assert all(a["end"] == b["start"] == ln["start"] for a, b, ln in zip(beats, beats[1:], lines[1:]))
    one, two = beats[0], beats[1]
    assert one["frame"] == f"/api/frame?t={round(one['end'] / 2, 3):g}&h=180"
    assert [p["text"] for p in one["phrases"]] == [i["text"] for i in st["tracks"][0]["items"] if i["line"] == 1]
    shot = one["shots"][0]
    assert shot["clip"] == "open" and shot["name_code"] == "shot.still" and shot["notes"] == ["slow push-in"]
    assert shot["note_codes"] == [{"code": "shot.motion", "params": {"motion": "push"}}]
    assert shot["thumb"] == "/api/thumb?asset=photo" and shot["continues"] is False
    assert two["shots"][0]["clip"] == "open" and two["shots"][0]["continues"] is True        # it spans two beats
    hook = one["elements"][0]
    assert (hook["clip"], hook["kind"], hook["name_code"], hook["name"]) == ("hook", "title", "text.title", "Title")
    assert hook["summary"] == "一杯奶茶，成本多少？" and two["elements"][0]["continues"] is True
    assert one["sound"] == [{"clip": "bed1", "asset": "bed", "start": 0.0, "end": 2.0, "name_code": "sound.effect",
                             "name": "Sound effect", "continues": False}]
    named = {e["clip"]: e for b in beats for e in b["elements"] if not e["continues"]}
    assert named["bill"]["name"] == "Itemised receipt" and "茶底和奶 ¥2.5" in named["bill"]["summary"]
    assert named["count"]["kind"] == "figure" and named["count"]["summary"] == "¥5 毛利不到"
    assert named["proof"]["kind"] == "evidence" and named["arrow"]["name_code"] == "shape.arrow"
    assert named["ring"]["name"] == "Circle mark" and named["verdict"]["name"] == "Verdict stamp"
    assert "todo" not in named                                                   # a hidden track
    video = next(s for b in beats for s in b["shots"] if s["clip"] == "shop" and not s["continues"])
    assert video["notes"] == ["looped"] and video["thumb"].startswith("/api/thumb?asset=clip&t=")
    proof = next(k for k, i in enumerate(st["issues"]) if i["clip"] == "proof")
    assert st["issues"][proof]["beat"] == 5 and proof in beats[4]["issues"]       # its own beat, not the one at 11.6
    assert not any(b["changed"] for b in beats)


def test_plain_names_and_summaries():
    def clip(type_, label="", **raw):
        return {"type": type_, "label": label, "raw": raw, "asset": raw.get("asset")}
    canvas = {"height": 1080}
    assert S.element_name(clip("component", "StoryBeats"), canvas) == ("card", "card.steps", "Step-by-step card")
    assert S.element_name(clip("component", "PriceTag"), canvas) == ("component", "component.custom", "PriceTag")
    assert S.element_name(clip("shape", shape="rect", fill="#000"), canvas)[2] == "Backing plate"
    assert S.element_name(clip("text", "x", style={"size": 40}), canvas)[2] == "Overlay text"
    assert S.element_name(clip("text", "x", style={"size": 90}), canvas)[2] == "Title"
    beats = clip("component", "StoryBeats", props={"beats": [{"when": "Day 1", "text": "Rain"}, {"text": "Sea"}],
                                                   "color": "accent"})
    assert S.element_summary(beats, {}) == "Day 1 Rain · Sea"
    count = clip("component", "CountUp", props={"value": 35, "suffix": "g", "label": "of salt", "at": "line:4"})
    assert S.element_summary(count, {}) == "35g of salt"
    assert S.picture_subject("from delta: The pale river water flows, slowly") == "The pale river water flows"
    assert S.picture_subject("") is None
    shot = {"raw": {}, "rate": 2, "reverse": True, "hold": 1.5, "loop": False,
            "transition": {"type": "crossfade", "dur": 0.4}}
    assert [n["text"] for n in S.shot_notes(shot)] == ["2x speed", "reversed", "held frame", "crossfade in"]


def test_beats_without_narration(demo):
    raw = json.loads((demo / "project.json").read_text("utf-8"))
    raw.pop("voice")
    raw["tracks"] = [
        {"id": "bg", "kind": "visual", "clips": [
            {"id": "s1", "type": "image", "asset": "photo", "start": 0, "dur": 2},
            {"id": "s2", "type": "image", "asset": "photo", "start": 2, "dur": 2},
            {"id": "pip", "type": "image", "asset": "photo", "start": 2.5, "dur": 0.5,
             "box": {"x": 0, "y": 0, "w": 200, "h": 200}},
            {"id": "s3", "type": "video", "asset": "clip", "start": 4, "dur": 2}]},
        {"id": "fg", "kind": "visual", "clips": [
            {"id": "t1", "type": "text", "text": "across", "start": 1, "end": 3}]}]
    (demo / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    st = S.build_state(demo)
    beats = st["beats"]
    assert [(b["start"], b["end"], b["line"], b["kind"]) for b in beats] == [
        (0.0, 2.0, None, "shot"), (2.0, 4.0, None, "shot"), (4.0, 6.0, None, "shot")]
    assert [s["clip"] for s in beats[1]["shots"]] == ["s2", "pip"] and beats[1]["shots"][1]["name"] == "Inset picture"
    assert [(e["clip"], e["continues"]) for b in beats for e in b["elements"]] == [("t1", False), ("t1", True)]


def test_each_batch_says_what_it_touched(demo):
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    edit(demo, {"op": "remove_clip", "id": "ring"})
    st = S.build_state(demo)
    rows = [r for r in st["activity"] if r.get("batch")]
    assert rows[0]["touched"] == {"clips": ["arrow"], "tracks": [], "beats": [4, 5]}
    assert rows[1]["touched"] == {"clips": ["ring"], "tracks": [], "beats": [6]}    # gone now: its old time counts
    assert st["latest_batch"] == 2 and [b["n"] for b in st["beats"] if b["changed"]] == [6]
    tools.undo(str(demo))
    st = S.build_state(demo)
    assert st["latest_batch"] == 1 and [b["n"] for b in st["beats"] if b["changed"]] == [4, 5]
    assert st["can_redo"] is True and st["can_undo"] is True


def test_rows_say_which_turn_or_action_made_them(demo):
    mark = P.set_origin(demo, turn=3)
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    P.clear_origin(demo, mark)
    mark = P.set_origin(demo, action="check")
    tools.check(str(demo))
    P.clear_origin(demo, mark)
    tools.check(str(demo))
    rows = S.activity_of(demo)
    assert [(r.get("turn"), r.get("action")) for r in rows] == [(3, None), (None, "check"), (None, None)]
    (demo / ".history" / "origin.json").write_text(json.dumps({"pid": 999999999, "turn": 9}), encoding="utf-8")
    assert P.origin(demo) is None                                   # its process is gone


def test_a_chat_tool_row_names_the_batch_it_made(chat_demo):
    class EditTools(Tools):
        def __call__(self, project, ws, scope, web):
            made = super().__call__(project, ws, scope, web)
            run = made[0]

            def do_edit(args):
                res = tools.edit(str(chat_demo), [{"op": "update_clip", "id": "arrow",
                                                   "set": {"start": "line:4", "end": "line:5.end"}}])
                return type(run.run({}))(str(res))
            return made + [type(run)("edit", "edits", OBJ, do_edit)]
    client = FakeClient(reply("Editing.", [("edit", {}), ("noop", {})]), reply("Done."))
    chat, _ = make_chat(chat_demo, client, EditTools())
    chat.send("lengthen the arrow")
    assert chat.wait(20)
    rows = chat.status()["messages"]
    tool_rows = {r["tool"]: r for r in rows if r["role"] == "tool"}
    assert tool_rows["edit"]["batch"] == 1 and "batch" not in tool_rows["noop"]
    logged = S.activity_of(chat_demo)
    assert logged[-1]["turn"] == 1 and logged[-1]["batch"] == 1
    assert not (chat_demo / ".history" / "origin.json").exists()
    assert rows[-1]["code"] == "chat.end" and rows[-1]["params"] == {"cost_usd": 0.02}


# ------------------------------------------------------------------ the result
def deliver(root: Path, cut: str | None = None, film: bytes = b"not a real film") -> None:
    from reelsmith.render import film_inputs
    out = root / "out"
    out.mkdir(exist_ok=True)
    (out / "film.mp4").write_bytes(film)
    report = {"ok": True, "inputs": {"cut": cut or film_inputs(root)["cut"]}, "film_check": {"duration_s": 21.8}}
    (out / "report.json").write_text(json.dumps(report), encoding="utf-8")


def test_the_result_as_a_state(demo):
    from reelsmith.render import film_inputs
    deliver(demo)
    res = S.build_state(demo)["result"]
    assert res["state"] == "current" and res["reason_code"] == "result.current" and res["accepted"] is None
    assert res["film"]["url"] == "/project/out/film.mp4" and res["film"]["matches_cut"] is True
    cut = film_inputs(demo)["cut"]
    (demo / "out" / "accepted.json").write_text(json.dumps({"at": "2026-11-10T12:00:00", "cut": cut}), "utf-8")
    assert S.build_state(demo)["result"]["accepted"] == {"at": "2026-11-10T12:00:00"}
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    res = S.build_state(demo)["result"]
    assert res["state"] == "stale" and res["reason"] == "The delivered film predates the current cut"
    assert res["accepted"] is None                                  # accepted for another cut
    build = demo / "build"
    build.mkdir(exist_ok=True)
    row = ('[error] verdict @ 19.0s: text "不贵" is cut by the canvas edge (right, 66 px) (also at 19.5s): move it '
           'in or make it smaller')
    (build / "report.json").write_text(json.dumps({
        "ok": False, "stage": "layout", "inputs": {"cut": film_inputs(demo)["cut"]}, "layout": [row],
        "layout_frames": ["C:\\elsewhere\\demo\\build\\inspect\\still_00570.png"], "kept_previous": True,
        "error": "words sit where the viewer cannot read them"}), encoding="utf-8")
    (build / "inspect").mkdir()
    (build / "inspect" / "still_00570.png").write_bytes(b"png")
    st = S.build_state(demo)
    res = st["result"]
    assert res["state"] == "refused" and res["stage"] == "layout" and res["reason_code"] == "layout.cut_by_edge"
    assert res["params"] == {"text": "不贵", "side": "right", "px": 66, "also": [19.5]}
    assert res["reason"] == 'Text "不贵" is cut by the right edge of the canvas (66 px)'
    assert (res["clip"], res["t"], res["beat"]) == ("verdict", 19.0, 7)
    assert res["frame"] == "/project/build/inspect/still_00570.png" and res["film"]["matches_cut"] is False
    issue = next(i for i in st["issues"] if i["source"] == "layout")
    assert issue["code"] == "layout.cut_by_edge" and issue["params"]["px"] == 66 and issue["beat"] == 7
    assert 0 <= st["issues"].index(issue) and st["issues"].index(issue) in st["beats"][6]["issues"]


def test_layout_messages_as_codes():
    cases = {
        'text "a b" sits 12 px outside the safe area (top): the platform\'s UI covers it there; keep words inside x '
        '0-1, y 0-1': ("layout.outside_safe", {"px": 12, "side": "top"}),
        'text "a" is 18 px: under 28 px is hard to read on this 1080x1920 canvas and render refuses under 20; give':
            ("layout.text_tiny", {"px": 18, "min": 28}),
        'text "a" is 24.5 px (also at 3.0s): under 28 px is hard to read on this 1080x1920 canvas; give it':
            ("layout.text_small", {"px": 24.5, "min": 28, "also": [3.0]}),
        'text "a" overlaps text "b" of cap (also at 2.0s): move one of them (captions sit at the bottom)':
            ("layout.overlap", {"other": 'text "b" of cap'}),
        'text "a" is cut by its own card: 40% of it stays hidden': ("layout.cut_by_card", {"share": 40}),
        'text "a" (#777777) on a background of about #808080 has contrast 1.1:1 (aim for 4.5:1 or more): change':
            ("layout.low_contrast", {"ratio": 1.1, "bg": "#808080"}),
        'text overflows its clip box by 9 px (bottom): make the box bigger': ("layout.overflow_box",
                                                                              {"px": 9, "text": ""}),
    }
    for msg, (code, params) in cases.items():
        got = S.layout_code(msg)
        assert got["code"] == code, msg
        assert {k: got["params"][k] for k in params} == params, msg
    assert S.layout_code("something else entirely") is None


def test_what_is_running_in_words():
    row = {"tool": "render", "since": "x", "seconds": 3.0, "stage": "layout", "progress": 0.4}
    got = S.running_view(row, "chat")
    assert got["text"] == "The agent is rendering the film: measuring layout (40 %)"
    assert (got["code"], got["stage_code"], got["percent"]) == ("running.render", "stage.layout", 40)
    assert got["params"] == {"tool": "render", "by": "chat", "stage": "stage.layout", "percent": 40}
    assert S.running_view({**row, "stage": None, "progress": None}, "window")["text"] == "Rendering the film"
    assert S.running_view({**row, "tool": "mystery"}, "agent")["code"] == "running.tool"
    assert S.running_view(None, "agent") is None


# ------------------------------------------------------------------ actions, acceptance, frames
def _wait_for(check, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_actions_run_a_tool_without_typing(chat_served, monkeypatch):
    srv, tools_ = chat_served
    site = srv.site(None)
    st = json.loads(get(srv, "/api/state")[2])
    assert st["can"]["check"] is True and st["can"]["undo"] is False and st["can"]["stop"] is False
    assert st["can"]["why"]["undo"]["code"] == "undo.empty" and st["can"]["why"]["stop"]["code"] == "stop.idle"
    assert post(srv, "/api/action", {"action": "undo"}) == (409, {"error": "There is no change to undo",
                                                                  "code": "undo.empty", "params": {}})
    assert post(srv, "/api/action", {"action": "dance"})[1]["code"] == "action.unknown"
    assert post(srv, "/api/action", {"action": "stop"})[1] == {"stopped": False, "code": "stop.idle", "params": {},
                                                               "error": "Nothing is running"}
    assert post(srv, "/api/action", {"action": "check"}) == (202, {"action": "check", "started": True})
    assert site.wait_action(20)
    st = json.loads(get(srv, "/api/state")[2])
    assert st["last_action"]["code"] == "action.check.failed" and st["last_action"]["ok"] is False   # demo has an error
    assert st["activity"][-1]["tool"] == "check" and st["activity"][-1]["action"] == "check"
    # one at a time, and never beside a chat turn
    gate = threading.Event()
    monkeypatch.setitem(W.ACTIONS, "check", lambda project: (gate.wait(10), tools.ToolResult("ok"))[1])
    assert post(srv, "/api/action", {"action": "check"})[0] == 202
    assert post(srv, "/api/action", {"action": "check"})[1]["code"] == "busy.action"
    assert post(srv, "/api/chat", {"message": "hi"})[1]["code"] == "busy.action"
    stop = post(srv, "/api/action", {"action": "stop"})[1]
    assert stop["stopped"] is False and stop["code"] == "stop.unsupported"
    st = json.loads(get(srv, "/api/state")[2])
    assert st["action"]["action"] == "check" and st["can"]["render"] is False
    assert st["can"]["why"]["render"]["code"] == "busy.action"
    gate.set()
    assert site.wait_action(10)
    assert post(srv, "/api/chat", {"message": "go"})[0] == 202
    assert tools_.entered.wait(10)
    assert post(srv, "/api/action", {"action": "check"})[1]["code"] == "busy.chat"
    st = json.loads(get(srv, "/api/state")[2])
    assert st["can"]["stop"] is True and st["can"]["why"]["check"]["code"] == "busy.chat"
    assert post(srv, "/api/action", {"action": "stop"}) == (200, {"stopped": True, "what": "chat"})
    assert site.chat.wait(10)


def test_an_action_is_announced_and_undo_works(served, demo):
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=20)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    _event(r)
    assert post(served, "/api/action", {"action": "undo"})[0] == 202
    assert json.loads(_event(r, ("action",)))["state"] == "running"
    done = json.loads(_event(r, ("action",)))
    assert done["state"] == "done" and done["code"] == "action.undo.ok" and "undid 1 batch" in done["detail"]
    conn.close()
    assert _wait_for(lambda: json.loads(get(served, "/api/state")[2])["can"]["redo"] is True)
    assert post(served, "/api/action", {"action": "redo"})[0] == 202
    assert served.site(None).wait_action(20)


def test_accept_and_reveal(served, demo, monkeypatch):
    opened = []
    monkeypatch.setattr(W, "open_folder", opened.append)
    assert post(served, "/api/accept", {})[1]["code"] == "accept.not_current"
    assert post(served, "/api/reveal", {}) == (404, {"error": "No film has been delivered", "code": "reveal.no_film",
                                                     "params": {}})
    deliver(demo)
    assert _wait_for(lambda: json.loads(get(served, "/api/state")[2])["result"]["state"] == "current")
    code, body = post(served, "/api/accept", {})
    assert code == 200 and body["accepted"]["at"]
    mark = json.loads((demo / "out" / "accepted.json").read_text("utf-8"))
    assert _wait_for(lambda: json.loads(get(served, "/api/state")[2])["result"]["accepted"] == body["accepted"])
    assert mark["cut"] == json.loads(get(served, "/api/state")[2])["cut"]
    assert post(served, "/api/reveal", {}) == (200, {"revealed": True, "folder": "out"})
    assert opened == [demo / "out"]


def test_open_folder_per_platform(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(W.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(W.os, "startfile", lambda p: calls.append(["startfile", p]), raising=False)
    for platform, first in (("win32", "startfile"), ("darwin", "open"), ("linux", "xdg-open")):
        monkeypatch.setattr(W.sys, "platform", platform)
        W.open_folder(tmp_path)
        assert calls[-1] == [first, str(tmp_path)]


def _png(path: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=108x192",
                    "-frames:v", "1", str(path)], check=True, capture_output=True)


@needs_ffmpeg
def test_frames_of_the_cut_are_queued_and_batched(served, demo, monkeypatch):
    runs = []

    def fake(mode, src, project, out, frames, timeout=0, **kw):
        runs.append(list(frames))
        stills = []
        for f in frames:
            _png(Path(out) / f"still_{f:05d}.png")
            stills.append({"frame": f, "png": str(Path(out) / f"still_{f:05d}.png")})
        return {"ok": True, "stills": stills}
    monkeypatch.setattr(W.R, "run_node", fake)
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=30)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    _event(r)
    with W.R.project_lock(demo / "build"):          # never beside a render: the queue waits
        for i in range(14):
            code, _, body = get(served, f"/api/frame?t={i}&h=90")
            assert code == 202 and json.loads(body) == {"pending": True}
        time.sleep(1.5)
        assert runs == []
    ready = []
    while len(ready) < 14:
        ready += json.loads(_event(r, ("frames",)))["ready"]
    conn.close()
    assert [len(x) for x in runs] == [12, 2] and ready[0]["url"] == "/api/frame?t=0&h=90"
    code, head, body = get(served, "/api/frame?t=3&h=90")
    assert code == 200 and head["X-Frame-Source"] == "cut" and body[:2] == b"\xff\xd8"
    beat = json.loads(get(served, "/api/state")[2])["beats"][0]
    assert beat["frame"].startswith("/api/frame?t=") and beat["frame"].endswith("&h=180")


def test_frames_of_an_older_cut_are_dropped(served, demo, monkeypatch):
    runs = []
    monkeypatch.setattr(W.R, "run_node", lambda mode, src, project, out, frames, **kw: runs.append(frames) or {
        "ok": False, "error": "unused"})
    conn = http.client.HTTPConnection("127.0.0.1", served.port, timeout=30)
    conn.request("GET", "/api/events")
    r = conn.getresponse()
    _event(r)
    with W.R.project_lock(demo / "build"):
        assert get(served, "/api/frame?t=2&h=90")[0] == 202
        edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    got = json.loads(_event(r, ("frames",)))
    conn.close()
    assert got["stale"] == [{"t": 2.0, "h": 90, "frame": 60, "url": "/api/frame?t=2&h=90"}]
    assert got["ready"] == [] and runs == []


@needs_ffmpeg
def test_a_failed_frame_says_why(served, monkeypatch):
    monkeypatch.setattr(W.R, "run_node", lambda *a, **kw: {"ok": False, "stage": "render", "error": "it broke"})
    assert get(served, "/api/frame?t=1&h=90")[0] == 202
    assert _wait_for(lambda: get(served, "/api/frame?t=1&h=90")[0] == 503)
    body = json.loads(get(served, "/api/frame?t=1&h=90")[2])
    assert body["code"] == "frame.failed" and "it broke" in body["params"]["error"]


@needs_ffmpeg
def test_frames_of_a_delivered_film_come_from_it(served, demo):
    film = demo / "out" / "film.mp4"
    film.parent.mkdir()
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3",
                    "-pix_fmt", "yuv420p", str(film)], check=True, capture_output=True)
    deliver(demo, film=film.read_bytes())
    assert _wait_for(lambda: json.loads(get(served, "/api/state")[2])["result"]["state"] == "current")
    code, head, body = get(served, "/api/frame?t=1&h=96")
    assert code == 200 and head["X-Frame-Source"] == "film" and body[:2] == b"\xff\xd8"
    assert get(served, "/api/frame?t=1&h=96&src=nope")[0] == 400
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    assert get(served, "/api/frame?t=1&h=96&src=film")[1]["X-Frame-Source"] == "film"    # asked for explicitly


def _fake_stills(runs, delay=0.0, guard=None, live=None):
    """run_node for "stills": writes a picture per frame and notes each run (frames, a render held the lock)."""
    def fake(mode, src, project, out, frames, timeout=0, **kw):
        with guard or threading.Lock():
            if live is not None:
                live[0] += 1
                live[1] = max(live[1], live[0])
            runs.append((list(frames), W.render_busy(Path(project))))
        time.sleep(delay)
        stills = []
        for f in frames:
            _png(Path(out) / f"still_{f:05d}.png")
            stills.append({"frame": f, "png": str(Path(out) / f"still_{f:05d}.png")})
        if live is not None:
            with guard:
                live[0] -= 1
        return {"ok": True, "stills": stills}
    return fake


@needs_ffmpeg
def test_twenty_frames_asked_at_once(served, demo, monkeypatch):
    runs, live, guard = [], [0, 0], threading.Lock()
    monkeypatch.setattr(W.R, "run_node", _fake_stills(runs, 0.3, guard, live))
    ts = [round(0.2 + i, 2) for i in range(20)]
    codes = []
    with W.R.project_lock(demo / "build"):          # a render holds the project: nothing starts
        asks = [threading.Thread(target=lambda t=t: codes.append(get(served, f"/api/frame?t={t}&h=90")[0]))
                for t in ts]
        for a in asks:
            a.start()
        for a in asks:
            a.join()
        assert codes == [202] * 20
        time.sleep(1.5)
        assert runs == []
    assert _wait_for(lambda: all(get(served, f"/api/frame?t={t}&h=90")[0] == 200 for t in ts), 60)
    drawn = [f for frames, _ in runs for f in frames]
    assert live[1] == 1 and all(len(frames) <= W.FRAME_BATCH for frames, _ in runs)
    assert not any(busy for _, busy in runs) and len(drawn) == len(set(drawn)) == 20    # each frame drawn once


@needs_ffmpeg
def test_a_render_that_begins_meanwhile_holds_back_the_frames(served, demo, monkeypatch):
    site, runs = served.site(None), []
    answers = iter([False, True])                   # the worker finds the project free; by the renderer it is not
    monkeypatch.setattr(site, "rendering", lambda: next(answers, False))
    monkeypatch.setattr(W.R, "run_node", _fake_stills(runs))
    canvas = json.loads(get(served, "/api/state")[2])["canvas"]
    h = round(54 * canvas["height"] / canvas["width"])
    assert get(served, "/api/frame?t=1&w=54")[0] == 202          # a width is read as the canvas's shape
    assert _wait_for(lambda: get(served, f"/api/frame?t=1&h={h}")[0] == 200)
    assert len(runs) == 1 and get(served, "/api/frame?t=1&w=54")[0] == 200


def test_beats_from_caption_groups(demo):
    raw = json.loads((demo / "project.json").read_text("utf-8"))
    raw.pop("voice")
    raw["tracks"] = [
        {"id": "bg", "kind": "visual", "clips": [
            {"id": "s1", "type": "image", "asset": "photo", "start": 0, "dur": 3},
            {"id": "s2", "type": "image", "asset": "photo", "start": 3, "dur": 9.5}]},
        {"id": "cap", "kind": "captions", "items": [
            {"start": 0, "end": 1, "text": "One two"}, {"start": 1.1, "end": 2, "text": "three four."},
            {"start": 2.1, "end": 2.9, "text": "Five"}, {"start": 3.0, "end": 4, "text": "six seven"},
            {"start": 4.1, "end": 5, "text": "eight"}, {"start": 5.1, "end": 10.9, "text": "nine"},
            {"start": 11.0, "end": 12.5, "text": "ten"}]}]
    (demo / "project.json").write_text(json.dumps(raw), encoding="utf-8")
    st = S.build_state(demo)
    assert st["valid"], st["error"]
    beats = st["beats"]
    # a sentence's end, a cut to s2, and a group over GROUP_S long each start a beat
    assert [(b["start"], b["end"], b["kind"]) for b in beats] == [
        (0.0, 2.1, "phrase"), (2.1, 3.0, "phrase"), (3.0, 11.0, "phrase"), (11.0, 12.5, "phrase")]
    assert [p["text"] for p in beats[2]["phrases"]] == ["six seven", "eight", "nine"]
    assert [(s["clip"], s["continues"]) for b in beats for s in b["shots"]] == [
        ("s1", False), ("s1", True), ("s2", False), ("s2", True)]
    assert all(b["line"] is None for b in beats)


def test_an_acceptance_holds_only_for_its_cut(served, demo):
    state = lambda: json.loads(get(served, "/api/state")[2])["result"]       # noqa: E731
    deliver(demo)
    assert _wait_for(lambda: state()["state"] == "current")
    code, body = post(served, "/api/accept", {})
    assert code == 200 and _wait_for(lambda: state()["accepted"] == body["accepted"])
    edit(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "line:4", "end": "line:5.end"}})
    assert _wait_for(lambda: state()["state"] == "stale")
    assert state()["accepted"] is None
    assert post(served, "/api/accept", {}) == (409, {"error": S.TEXTS["accept.not_current"],
                                                     "code": "accept.not_current", "params": {}})
    tools.undo(str(demo))                           # the accepted cut again: its acceptance stands again
    assert _wait_for(lambda: state()["state"] == "current")
    assert state()["accepted"] == body["accepted"]


def test_a_chat_turn_and_an_action_never_start_together(chat_served, monkeypatch):
    srv, tools_ = chat_served
    site = srv.site(None)
    send = site.chat.send

    def slow(*a, **kw):
        time.sleep(0.5)                             # the action is asked for meanwhile
        return send(*a, **kw)
    monkeypatch.setattr(site.chat, "send", slow)
    got = {}
    asking = threading.Thread(target=lambda: got.update(chat=post(srv, "/api/chat", {"message": "go"})))
    asking.start()
    time.sleep(0.15)
    got["action"] = post(srv, "/api/action", {"action": "check"})
    asking.join()
    assert got["chat"] == (202, {"turn": 1}) and got["action"][0] == 409 and got["action"][1]["code"] == "busy.chat"
    assert tools_.entered.wait(10)
    site.chat.stop()
    assert site.chat.wait(10)


def test_every_code_the_page_translates_has_its_parameters():
    import re
    # the dictionary has two parts: the frame and films pages, and the Library and Settings pages
    en = "".join((W.STATIC / "i18n" / part).read_text("utf-8") for part in ("en.js", "pages/en.js")
                 if (W.STATIC / "i18n" / part).is_file())
    page = {k: set(re.findall(r"\{(\w+)\}", v)) for k, v in re.findall(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', en,
                                                                       re.M)}
    sent = {code: set(re.findall(r"\{(\w+)\}", text)) for code, text in S.TEXTS.items()}
    sent.update({code: set(re.findall(r"\{(\w+)\}", text)) for code, text in C.REASONS.items()})
    sent.update({code: set() for code, _ in S.STAGES.values()})
    sent.update({code: set() for _, code, _ in S.PRESETS.values()})
    sent.update({code: set() for code, _ in S.SHAPES.values()})
    sent.update({code: set() for code in [*S.SHOTS, *S.SOUNDS, "shape.plate", "shape.frame", "text.title",
                                          "text.overlay", "evidence.card", "component.custom", "shot.reversed",
                                          "shot.held", "shot.looped"]})
    sent.update({"shot.speed": {"rate"}, "shot.motion": {"motion"}, "shot.transition_in": {"type"},
                 "chat.too_long": {"chars", "max"}, "chat.unknown_engine": {"engine"},
                 "chat.engine_unavailable": {"engine", "why"}, "busy.chat": {"turn"}, "chat.empty": set(),
                 "chat.bad_context": set(), "chat.no_engine": set(), "chat.workspace_hidden": set(),
                 "chat.error": {"error"}, "chat.stopped": {"cost_usd"},
                 "chat.aborted": {"reason", "cost_usd"}})
    sent.update({f"motion.{m}": set() for m in S.MOTIONS})
    sent.update({f"side.{s}": set() for s in ("left", "right", "top", "bottom")})
    assert sorted(c for c in sent if c not in page) == []
    assert {c: page[c] - p for c, p in sent.items() if page[c] - p} == {}
