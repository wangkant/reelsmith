"""The application over a workspace: films, requests at once, folders, media, library, settings, entry, window."""
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pytest

from reelsmith import cli, tools
from reelsmith.watch import app as A
from reelsmith.watch import chat as C
from reelsmith.watch import entry
from reelsmith.watch import presence as P
from reelsmith.watch import server as W
from reelsmith.watch import state as S
from reelsmith.watch import window

FIXTURE = Path(__file__).parent / "fixtures" / "demo"
OBJ = {"type": "object", "properties": {}}
needs_renderer = pytest.mark.skipif(not (shutil.which("node") and shutil.which("ffmpeg")
                                         and (W.R.RENDERER / "node_modules").is_dir()), reason="node or ffmpeg missing")


# ------------------------------------------------------------------ helpers
def get(srv, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    try:
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def jget(srv, path):
    code, _, body = get(srv, path)
    assert code == 200, (path, code, body[:300])
    return json.loads(body)


def send(srv, method, path, body=b"", headers=None, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=60)
    hdrs = {"Origin": f"http://127.0.0.1:{srv.port}"}
    if token:
        hdrs[W.TOKEN_HEADER] = srv.token
    hdrs.update(headers or {})
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        conn.request(method, path, body=data, headers={"Content-Type": "application/json", **hdrs})
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b"null")
    finally:
        conn.close()


def post(srv, path, body=None, **kw):
    return send(srv, "POST", path, {} if body is None else body, **kw)


def wait_for(check, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(0.05)
    return False


def event(r, kinds):
    """(kind, data) of the next event of one of `kinds` on an event stream."""
    kind = None
    while True:
        line = r.fp.readline().decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            kind = line[7:]
        elif line.startswith("data: ") and kind in kinds:
            return kind, json.loads(line[6:])


class Client:
    """One scripted model step per call."""

    def __init__(self, *script):
        self.script = list(script)

    def complete(self, messages, tools):
        step = self.script.pop(0)
        return step(messages) if callable(step) else step


def reply(text=None, calls=(), cost=0.01):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    return {"message": msg, "finish_reason": "tool_calls" if calls else "stop",
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost_usd": cost}}


def broken(messages):
    raise RuntimeError("the provider is down")


class Holds:
    """A "hold" tool per film: it says when it starts and waits until that film is released."""

    def __init__(self):
        self.entered = defaultdict(threading.Event)
        self.released = defaultdict(threading.Event)
        self.times: dict[str, list] = {}

    def __call__(self, project, ws, scope, web):
        name = Path(project).name

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
            self.times[name] = [time.monotonic()]
            self.entered[name].set()
            self.released[name].wait(30)
            self.times[name].append(time.monotonic())
            return Result("held")
        return [Tool("hold", "waits", OBJ, hold)]


def only_api(engine, ws):
    return (True, "fake") if engine == "api" else (False, f"{engine} is not here")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A workspace of three films (the demo and two empty ones), a fake key and room for two requests at once."""
    for name in ("OPENROUTER_API_KEY", "REELSMITH_PROXY", "REELSMITH_ROOT"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE, root / "projects" / "demo", ignore=shutil.ignore_patterns("build", ".history"))
    (root / "library" / "components").mkdir(parents=True)
    (root / "workspace.json").write_text(json.dumps({"runner": {"engine": "api", "budget_usd": 1},
                                                     "watch": {"parallel": 2}}), encoding="utf-8")
    (root / ".env").write_text("# my keys\nOPENROUTER_API_KEY=sk-or-test-1234567\n", encoding="utf-8")
    for name in ("b", "c"):
        assert tools.new_project(str(root / "projects" / name)).ok
    return root


@pytest.fixture
def served(ws):
    holds = Holds()

    def client(settings):
        return Client(reply("Working.", [("hold", {})]), reply("All done."))
    srv = W.serve(ws, chat_options={"client_factory": client, "tools_factory": holds, "engines_fn": only_api})
    srv.holds = holds
    yield srv
    for ev in list(holds.released.values()):
        ev.set()
    srv.stop()


def film(srv, name):
    return next(f for f in jget(srv, "/api/app")["films"] if f["name"] == name)


# ------------------------------------------------------------------ the gate
def test_the_gate_lets_the_limit_through_and_queues_the_rest(tmp_path):
    moves = []
    gate = A.Gate(2, lambda: moves.append(1))
    stop = {n: threading.Event() for n in "abc"}
    t = {n: gate.ticket(tmp_path / n, 1) for n in "abc"}
    assert gate.position(t["a"]) is None and gate.position(t["c"]) == 1        # a and b would start now
    assert gate.enter(t["a"], stop["a"]) and gate.enter(t["b"], stop["b"])
    assert gate.position(t["c"]) == 1 and gate.state() == {"limit": 2, "running": 2, "queued": 1}
    entered = threading.Event()
    threading.Thread(target=lambda: gate.enter(t["c"], stop["c"]) and entered.set(), daemon=True).start()
    time.sleep(0.4)
    assert not entered.is_set()
    gate.leave(t["a"])
    assert entered.wait(5) and gate.position(t["c"]) is None
    # a stopped ticket leaves the queue at once
    d = gate.ticket(tmp_path / "d", 1)
    stop_d = threading.Event()
    left = threading.Event()
    threading.Thread(target=lambda: gate.enter(d, stop_d) or left.set(), daemon=True).start()
    time.sleep(0.2)
    began = time.monotonic()
    stop_d.set()
    gate.poke()
    assert left.wait(2) and time.monotonic() - began < 1 and gate.position(d) is None
    gate.set_limit(99)
    assert gate.limit == 8 and moves
    assert A.parallel_of({"watch": True}) == 3 and A.parallel_of({"watch": {"parallel": 0}}) == 1


def test_requests_in_two_films_run_at_once_and_a_third_waits(served, ws):
    srv, holds = served, served.holds
    assert post(srv, "/p/demo/api/chat", {"message": "Tighten the opening."}) == (202, {"turn": 1})
    assert post(srv, "/p/b/api/chat", {"message": "Add a title."}) == (202, {"turn": 1})
    assert holds.entered["demo"].wait(10) and holds.entered["b"].wait(10)
    # both hold at the same time: neither was released before the other began
    assert not holds.released["demo"].is_set() and not holds.released["b"].is_set()
    assert post(srv, "/p/c/api/chat", {"message": "Draft the narration."}) == (202, {"turn": 1})
    assert wait_for(lambda: film(srv, "c")["status"] == "queued")
    c = film(srv, "c")
    assert c["queue"] == 1 and film(srv, "demo")["status"] == "working"
    app = jget(srv, "/api/app")
    assert app["counts"]["working"] == 2 and app["counts"]["queued"] == 1
    assert app["parallel"] == {"limit": 2, "running": 2, "queued": 1}
    chat = jget(srv, "/p/c/api/chat")
    assert chat["busy"] is True and chat["queued"] == 1
    st = jget(srv, "/p/c/api/state")
    assert st["queue"]["position"] == 1 and st["queue"]["code"] == "queue.waiting"
    assert not holds.entered["c"].is_set()
    holds.released["demo"].set()                        # one ends: the third starts
    assert holds.entered["c"].wait(10)
    assert srv.sites["demo"].chat.wait(10)
    assert film(srv, "c")["status"] == "working" and film(srv, "c")["queue"] is None
    for name in ("b", "c"):
        holds.released[name].set()
        assert srv.sites[name].chat.wait(10)
    assert [film(srv, n)["last"]["role"] for n in ("demo", "b", "c")] == ["note", "note", "note"]


def test_an_edit_in_one_film_completes_while_a_slow_tool_runs_in_another(ws):
    from reelsmith.agent import tools as AT
    entered, release = threading.Event(), threading.Event()

    @tools.tool
    def slow(project: str) -> str:
        """Waits until the test releases it."""
        entered.set()
        release.wait(30)
        return "slow done"

    def toolbox(project, ws_, scope, web):
        if Path(project).name == "demo":
            return [AT.reelsmith_tool("slow", slow, Path(project), scope)]
        return [AT.reelsmith_tool("edit", tools.TOOLS["edit"], Path(project), scope)]

    def client(settings):
        return Client(reply("Working.", [("slow", {})]), reply("Done."))
    srv = W.serve(ws, chat_options={"client_factory": client, "tools_factory": toolbox, "engines_fn": only_api})
    try:
        post(srv, "/p/demo/api/chat", {"message": "Render the draft."})
        assert entered.wait(10)
        srv.site("b").chat.seams["client_factory"] = lambda s: Client(
            reply("Editing.", [("edit", {"ops": [{"op": "set", "path": "meta.title", "value": "Film B"}]})]),
            reply("Done."))
        post(srv, "/p/b/api/chat", {"message": "Title it Film B."})
        assert srv.sites["b"].chat.wait(10) and not release.is_set()     # the slow tool in demo still runs
        rows = jget(srv, "/p/b/api/chat")["messages"]
        assert rows[-1]["kind"] == "end" and any(r.get("tool") == "edit" and r["ok"] for r in rows)
        assert A.title_of(ws / "projects" / "b") == "Film B"
        assert jget(srv, "/p/demo/api/chat")["busy"] is True
    finally:
        release.set()
        srv.stop()


def test_a_turn_that_cannot_start_leaves_the_queue(ws):
    gate = A.Gate(1)
    chat = C.Chat(ws / "projects" / "b", gate=gate, engines_fn=only_api)

    def fail(row):
        raise OSError("disk full")
    chat._write = fail
    with pytest.raises(OSError):
        chat.send("Add a title.")
    assert chat.busy is None and chat.queued is None and chat.rows == []
    assert gate.state() == {"limit": 1, "running": 0, "queued": 0}
    other = gate.ticket(ws / "projects" / "c", 1)            # the next film is not held behind it
    assert gate.enter(other, threading.Event())
    gate.leave(other)
    del chat._write
    holds = Holds()
    holds.released["b"].set()
    chat.seams.update(client_factory=lambda s: Client(reply("Working.", [("hold", {})]), reply("Done.")),
                      tools_factory=holds)
    assert chat.send("Add a title.") == 2 and chat.wait(10) and chat.rows[-1]["kind"] == "end"


def test_stopping_a_queued_request_ends_it_at_once(served):
    srv, holds = served, served.holds
    post(srv, "/p/demo/api/chat", {"message": "one"})
    post(srv, "/p/b/api/chat", {"message": "two"})
    assert holds.entered["demo"].wait(10) and holds.entered["b"].wait(10)
    post(srv, "/p/c/api/chat", {"message": "three"})
    assert wait_for(lambda: jget(srv, "/p/c/api/chat")["queued"] == 1)
    began = time.monotonic()
    assert post(srv, "/p/c/api/chat/stop") == (200, {"stopped": True})
    assert srv.sites["c"].chat.wait(5) and time.monotonic() - began < 2
    rows = jget(srv, "/p/c/api/chat")["messages"]
    assert rows[-1]["kind"] == "stopped" and not holds.entered["c"].is_set()
    assert jget(srv, "/api/app")["parallel"]["queued"] == 0
    for name in ("demo", "b"):
        holds.released[name].set()


def test_a_failure_in_one_film_leaves_the_other_running(ws):
    holds = Holds()

    def client(settings):
        return Client(reply("Working.", [("hold", {})]), reply("Done."))
    srv = W.serve(ws, chat_options={"client_factory": client, "tools_factory": holds, "engines_fn": only_api})
    try:
        post(srv, "/p/demo/api/chat", {"message": "go"})
        assert holds.entered["demo"].wait(10)
        srv.site("b").chat.seams["client_factory"] = lambda s: Client(broken)
        post(srv, "/p/b/api/chat", {"message": "go"})
        assert srv.sites["b"].chat.wait(10)
        note = jget(srv, "/p/b/api/chat")["messages"][-1]
        assert note["kind"] == "error" and "the provider is down" in note["text"]
        assert jget(srv, "/p/demo/api/chat")["busy"] is True and not holds.released["demo"].is_set()
        b = film(srv, "b")
        assert b["status"] == "attention" and {"code": "attention.failed", "params": {}} in b["attention"]
        holds.released["demo"].set()
        assert srv.sites["demo"].chat.wait(10)
        assert jget(srv, "/p/demo/api/chat")["messages"][-1]["kind"] == "end"
    finally:
        holds.released["demo"].set()
        srv.stop()


def test_a_request_that_ends_is_unread_until_seen(served, ws):
    srv, holds = served, served.holds
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    conn.request("GET", "/api/app/events")
    r = conn.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    kind, first = event(r, ("films",))
    assert {f["name"] for f in first["films"]} == {"demo", "b", "c"} and "counts" in first
    holds.released["b"].set()
    post(srv, "/p/b/api/chat", {"message": "Add a title."})
    _, ended = event(r, ("ended",))
    assert ended == {"name": "b", "turn": 1, "outcome": "done", "title": None}
    conn.close()
    b = film(srv, "b")
    assert b["unread"] is True and b["last"]["role"] == "note" and len(b["last"]["text"]) <= 160
    assert post(srv, "/api/app/seen", {"name": "b"}) == (200, {"seen": True})
    assert film(srv, "b")["unread"] is False
    # remembered across a restart, and cleared when the film's own page asks for its state
    srv.marks.ended("c", 1, "done")
    again = W.serve(ws)
    try:
        assert film(again, "c")["unread"] is True
        assert get(again, "/p/c/api/state")[0] == 200
        assert film(again, "c")["unread"] is False
    finally:
        again.stop()
    assert post(srv, "/api/app/seen", {"name": "../x"})[1]["code"] == "film.unknown"


def test_the_application_document(served, ws):
    app = jget(served, "/api/app")
    assert app["workspace"] == {"name": "ws", "path": ws.resolve().as_posix()} and app["desktop"] is False
    assert app["engine"]["id"] == "api" and app["engine"]["available"] is True and app["version"]
    demo = next(f for f in app["films"] if f["name"] == "demo")
    assert demo["status"] == "attention" and demo["attention"][0]["code"] == "attention.issues"
    assert demo["attention"][0]["params"]["n"] >= 1 and demo["queue"] is None and demo["last"] is None
    for key in ("name", "path", "url", "title", "duration", "valid", "empty", "canvas", "result", "poster",
                "revision", "modified", "working", "status", "queue", "unread", "attention", "last"):
        assert key in demo, key
    assert served.sites == {}                      # listing makes no site
    # every page is its own file inside the frame: the sidebar and the main area, and the page it says it is
    for page, name in (("/", "films"), ("/new", "new"), ("/library", "library"), ("/settings", "settings"),
                       ("/p/demo/", "film")):
        code, head, body = get(served, page)
        text = body.decode("utf-8")
        assert code == 200 and head["Content-Type"].startswith("text/html"), page
        assert f'data-page="{name}"' in text and 'id="side"' in text and 'id="main"' in text, page
    assert get(served, "/api/app", {"Origin": "http://evil.example"})[0] == 403


def test_attention_codes():
    facts = {"result": {"state": "current", "accepted": None}, "errors": 0}
    quiet = {"last": None, "ended": None, "asked": False}
    assert A.attention_of(facts, quiet, False) == [{"code": "attention.to_accept", "params": {}}]
    asked = A.chat_facts([{"id": 1, "role": "user", "text": "hi", "turn": 1},
                          {"id": 2, "role": "assistant", "text": "Which ending do you prefer?", "turn": 1},
                          {"id": 3, "role": "note", "kind": "end", "text": "done", "turn": 1, "ts": "x"}])
    assert asked["asked"] and asked["ended"] == "end"
    refused = {"result": {"state": "refused"}, "errors": 2}
    codes = [a["code"] for a in A.attention_of(refused, {**asked, "ended": "error"}, True)]
    assert codes == ["attention.failed", "attention.reply", "attention.refused", "attention.issues"]
    later = A.chat_facts([{"id": 3, "role": "note", "kind": "error", "turn": 1},
                          {"id": 4, "role": "user", "text": "again", "turn": 2}])
    assert later["ended"] is None and later["last"]["role"] == "user"
    assert all(c in S.TEXTS for c in ("attention.reply", "attention.failed", "attention.refused",
                                      "attention.issues", "attention.to_accept"))


def test_a_render_waiting_for_the_renderer_says_so(ws):
    held, done = threading.Event(), threading.Event()

    def holder():
        with W.R._NODE_LOCK:
            held.set()
            done.wait(10)
    threading.Thread(target=holder, daemon=True).start()
    assert held.wait(5)
    try:
        assert W.waits_for_renderer({"tool": "render", "stage": None})
        assert not W.waits_for_renderer({"tool": "render", "stage": "film"})
        assert not W.waits_for_renderer({"tool": "edit", "stage": None})
        view = S.running_view({"tool": "render", "stage": None, "progress": None}, "chat", True)
        assert view["stage_code"] == "stage.renderer_wait" and view["text"].endswith("waiting for the renderer")
        mark = P.Running(ws / "projects" / "b", "render").start()
        srv = W.serve(ws)
        try:
            assert film(srv, "b")["working"]["stage_code"] == "stage.renderer_wait"
        finally:
            mark.end()
            srv.stop()
    finally:
        done.set()
    assert wait_for(lambda: not W.renderer_held(), 5)
    assert not W.waits_for_renderer({"tool": "render", "stage": None})


# ------------------------------------------------------------------ the films' folders
def test_names_and_formats(served, ws):
    from reelsmith.workspace import Workspace
    name = jget(served, "/api/films/suggest?text=Harbor%20lights%20at%20night")["name"]
    assert name.endswith("-harbor-lights-at-night") and len(name.split("-")[0]) == 4
    formats = jget(served, "/api/formats")
    ids = {f["id"]: f for f in formats["formats"]}
    assert formats["default"] == "landscape" and ids["douyin"]["platform"] and not ids["square"]["platform"]
    assert ids["vertical"]["width"] == 1080 and ids["vertical"]["height"] == 1920
    # one list of names Windows refuses: the suggestion avoids them and the pages are given the same list
    assert A.free_name([], "con") == "con-2" and A.free_name(["COM1-2"], "com1") == "com1-3"
    assert jget(served, "/api/app")["names"]["reserved"] == sorted(A.RESERVED)
    # a trailing newline is not part of a name
    assert post(served, "/api/app/seen", {"name": "b\n"})[1]["code"] == "film.unknown"
    assert post(served, "/api/films", {"name": "fresh\n"})[1]["code"] == "create.chars"
    tid = post(served, "/api/films/c/trash")[1]["id"]
    assert A.trashed(Workspace.load(ws), tid).is_dir()
    with pytest.raises(A.Refusal):
        A.trashed(Workspace.load(ws), tid + "\n")


def test_a_new_film_with_a_first_request(served, ws):
    srv, holds = served, served.holds
    code, body = post(srv, "/api/films", {"description": "A short film about the harbor", "format": "vertical",
                                          "locale": "en", "start": True})
    assert code == 201 and body["turn"] == 1 and body["queued"] is False and body["url"] == f"/p/{body['name']}/"
    made = ws / "projects" / body["name"]
    assert json.loads((made / "project.json").read_text("utf-8")).get("locale") == "en"
    assert jget(srv, f"/p/{body['name']}/api/state")["canvas"]["profile"] == "vertical"
    assert holds.entered[body["name"]].wait(10)
    holds.released[body["name"]].set()
    assert srv.sites[body["name"]].chat.wait(10)
    assert jget(srv, f"/p/{body['name']}/api/chat")["messages"][0]["text"] == "A short film about the harbor"
    code, body = post(srv, "/api/films", {"name": "quiet_one"})
    assert (code, body["turn"], body["queued"]) == (201, None, False)
    for bad, why in (({"format": "imax"}, "create.format"), ({"locale": "not a tag"}, "create.locale"),
                     ({"engine": "gpt"}, "create.engine"), ({"description": "x" * 8001}, "create.description"),
                     ({"name": "../up"}, "create.chars"), ({"name": "quiet_one"}, "create.taken")):
        code, got = post(srv, "/api/films", bad)
        assert code in (400, 409) and got["code"] == why and got["error"] == S.say(why, **got["params"])["text"], bad
    assert post(srv, "/api/projects", {"name": "old_way"})[0] == 201          # the home's route still works


def test_title_duplicate_reveal(served, ws, monkeypatch):
    srv = served
    assert post(srv, "/api/films/b/title", {"title": "  The harbor  "}) == (200, {"name": "b", "title": "The harbor"})
    assert film(srv, "b")["title"] == "The harbor"
    assert post(srv, "/api/films/b/title", {"title": "a\nb"})[1]["code"] == "title.invalid"
    assert post(srv, "/api/films/b/title", {"title": "x" * 121})[1]["params"] == {"max": 120}
    assert post(srv, "/api/films/nope/title", {"title": "x"})[0] == 404
    demo = ws / "projects" / "demo"
    for sub in ("build", "out", ".history"):
        (demo / sub).mkdir(exist_ok=True)
        (demo / sub / "x.txt").write_text("x", encoding="utf-8")
    code, body = post(srv, "/api/films/demo/duplicate")
    assert code == 201 and body == {"name": "demo-copy", "url": "/p/demo-copy/"}
    copy = ws / "projects" / "demo-copy"
    assert (copy / "project.json").is_file() and (copy / "assets" / "photo.png").is_file()
    assert not any((copy / sub).exists() for sub in ("build", "out", ".history"))
    assert post(srv, "/api/films/demo/duplicate")[1]["name"] == "demo-copy-2"
    assert post(srv, "/api/films/demo/duplicate", {"name": "B"})[1]["code"] == "create.taken"
    media = ws / "media.bin"                        # media imported as a hard link stays a link in the copy
    media.write_bytes(b"x" * 64)
    os.link(media, demo / "assets" / "linked.bin")
    assert post(srv, "/api/films/demo/duplicate", {"name": "linked"})[0] == 201
    assert os.path.samefile(media, ws / "projects" / "linked" / "assets" / "linked.bin")
    assert not os.path.samefile(demo / "project.json", ws / "projects" / "linked" / "project.json")
    shown = []
    monkeypatch.setattr(W, "open_folder", shown.append)
    assert post(srv, "/api/films/demo/reveal", {"what": "folder"}) == (200, {"revealed": True, "what": "folder"})
    assert post(srv, "/api/films/demo/reveal", {"what": "out"})[0] == 200
    assert post(srv, "/api/films/b/reveal", {"what": "out"})[1]["code"] == "reveal.no_film"
    assert post(srv, "/api/films/b/reveal", {"what": "desktop"})[1]["code"] == "reveal.what"
    assert shown == [demo.resolve(), demo.resolve() / "out"]


def test_the_trash(served, ws):
    srv, holds = served, served.holds
    post(srv, "/p/b/api/chat", {"message": "go"})
    assert holds.entered["b"].wait(10)
    code, body = post(srv, "/api/films/b/trash")
    assert (code, body["code"]) == (409, "film.busy")
    holds.released["b"].set()
    assert srv.sites["b"].chat.wait(10)
    code, body = post(srv, "/api/films/b/trash")
    assert code == 200 and body["name"] == "b" and not (ws / "projects" / "b").exists()
    assert "b" not in srv.sites and "b" not in {f["name"] for f in jget(srv, "/api/app")["films"]}
    rows = jget(srv, "/api/trash")
    assert [r["name"] for r in rows] == ["b"] and rows[0]["id"] == body["id"] and rows[0]["size_bytes"] > 0
    assert (ws / ".trash" / body["id"] / "project.json").is_file()
    assert post(srv, "/api/films", {"name": "b"})[0] == 201                  # the name is free again
    code, back = post(srv, f"/api/trash/{body['id']}/restore")
    assert code == 200 and back == {"name": "b-2", "url": "/p/b-2/"}
    back_dir = ws / "projects" / "b-2"
    assert (back_dir / "project.json").is_file() and not (back_dir / "trash.json").exists()
    assert jget(srv, "/api/trash") == []
    assert post(srv, "/api/films/c/trash")[0] == 200
    tid = jget(srv, "/api/trash")[0]["id"]
    assert post(srv, f"/api/trash/{tid}/delete") == (200, {"deleted": True, "id": tid})
    assert not (ws / ".trash" / tid).exists()
    for bad in ("..%2Fprojects", "nope-20260101-000000", "x"):
        code, got = post(srv, f"/api/trash/{bad}/restore")
        assert code in (404,) and got["code"] == "trash.unknown", bad
    assert post(srv, "/api/films/b/trash", token=False)[0] == 403


# ------------------------------------------------------------------ media from the window
def test_adding_media_by_path_and_by_upload(served, ws, tmp_path):
    srv = served
    pic = tmp_path / "Harbor Photo.png"
    shutil.copy(FIXTURE / "assets" / "photo.png", pic)
    junk = tmp_path / "notes.txt"
    junk.write_text("x", encoding="utf-8")
    code, got = post(srv, "/p/b/api/import", {"paths": [str(pic), str(junk), "relative.png", str(tmp_path / "no.png")]})
    assert code == 200
    assert got["assets"] == [{"id": "harbor_photo", "kind": "image", "path": "assets/harbor_photo.png"}]
    assert [(r["name"], r["code"]) for r in got["refused"]] == [
        ("notes.txt", "import.kind"), ("relative.png", "import.not_absolute"), ("no.png", "import.missing")]
    assert (ws / "projects" / "b" / "assets" / "harbor_photo.png").is_file()
    code, got = post(srv, "/p/b/api/import", {"paths": [str(pic)]})
    assert got["assets"][0]["id"] == "harbor_photo_2"
    assert post(srv, "/p/b/api/import", {"paths": []})[1]["code"] == "import.empty"
    data = (FIXTURE / "assets" / "photo.png").read_bytes()
    code, got = send(srv, "PUT", "/p/b/api/upload?name=dropped.png", data, {"Content-Type": "image/png"})
    assert code == 200 and got["assets"][0]["id"] == "dropped" and got["refused"] == []
    assert (ws / "projects" / "b" / "assets" / "dropped.png").read_bytes() == data
    assert not any((ws / "projects" / "b" / "build" / "watch" / "uploads").iterdir())
    assert send(srv, "PUT", "/p/b/api/upload?name=evil.exe", data)[1]["code"] == "upload.name"
    assert send(srv, "PUT", "/p/b/api/upload?name=..%2F..%2Fx.png", data)[0] == 200      # the last part only
    assert send(srv, "PUT", "/p/b/api/upload?name=x.png", data, token=False)[0] == 403
    assert send(srv, "PUT", "/p/b/api/upload?name=x.png", data, {"Origin": "http://evil.example"})[0] == 403


# ------------------------------------------------------------------ the library
def test_the_library(served, ws):
    comp = ws / "library" / "components"
    (comp / "Badge.tsx").write_text("export default function Badge() { return null; }\n", encoding="utf-8")
    (comp / "Badge.meta.json").write_text(json.dumps({
        "name": "Badge", "description": "A small badge.", "example": {"text": "New"},
        "props": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string", "description": "the word"}, "tone": {"enum": ["a", "b"]}}}}), encoding="utf-8")
    (ws / "library" / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    lib = jget(served, "/api/library")
    rows = {c["name"]: c for c in lib["components"]}
    assert rows["Arrow"]["origin"] == "built-in" and rows["Arrow"]["example"] and rows["Arrow"]["props"]
    badge = rows["Badge"]
    assert badge["origin"] == "workspace" and badge["about"] == "A small badge."
    assert badge["props"] == [{"name": "text", "type": "string", "required": True, "about": "the word"},
                              {"name": "tone", "type": '"a" | "b"', "required": False, "about": ""}]
    assert badge["preview"] == "/api/library/preview?name=Badge&theme=light"
    assert lib["notes"]["text"] == "# Notes\n" and set(lib["rules"]) == {"hard", "advice"}
    assert all({"key", "value"} == set(r) for r in lib["rules"]["hard"])
    code, _, body = get(served, "/api/library/preview?name=Nope&theme=light")
    assert code == 404 and json.loads(body)["code"] == "library.unknown"
    assert json.loads(get(served, "/api/library/preview?name=Arrow&theme=sepia")[2])["code"] == "library.theme"


def test_previews_are_queued_drawn_once_and_cached(ws, monkeypatch):
    srv = W.serve(ws)
    drawn = []

    def fake(self, key, name, theme):
        drawn.append((name, theme))
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{key}.jpg").write_bytes(b"\xff\xd8 not a real picture")
    monkeypatch.setattr(A.Previews, "draw", fake)
    try:
        code, _, body = get(srv, "/api/library/preview?name=Arrow&theme=dark")
        assert code in (200, 202)
        assert wait_for(lambda: get(srv, "/api/library/preview?name=Arrow&theme=dark")[0] == 200)
        assert get(srv, "/api/library/preview?name=Arrow&theme=dark")[2].startswith(b"\xff\xd8")
        assert drawn == [("Arrow", "dark")]
        comp = ws / "library" / "components"            # a workspace component that changes is drawn again
        (comp / "Arrow.tsx").write_text("export default () => null;\n", encoding="utf-8")
        (comp / "Arrow.meta.json").write_text(json.dumps({"name": "Arrow", "example": {}}), encoding="utf-8")
        assert wait_for(lambda: get(srv, "/api/library/preview?name=Arrow&theme=dark")[0] == 200)
        assert drawn == [("Arrow", "dark"), ("Arrow", "dark")]
    finally:
        srv.stop()


@needs_renderer
def test_a_preview_of_a_built_in_component(ws):
    srv = W.serve(ws)
    try:
        assert wait_for(lambda: get(srv, "/api/library/preview?name=CountUp&theme=light")[0] != 202, 240)
        code, head, body = get(srv, "/api/library/preview?name=CountUp&theme=light")
        assert code == 200 and head["Content-Type"] == "image/jpeg" and body[:2] == b"\xff\xd8", body[:300]
        assert list((ws / ".cache" / "watch" / "library").glob("CountUp-light-*.jpg"))
        assert not any((ws / ".cache" / "watch" / "library-work").iterdir())
    finally:
        srv.stop()


# ------------------------------------------------------------------ settings
@pytest.fixture
def checked(monkeypatch):
    from reelsmith import doctor
    runs = []

    def fake(workspace=None, cwd=None, os_name=None):
        runs.append(workspace)
        return {"checks": [{"name": "node", "ok": True, "required": True, "detail": "v22", "fix": "", "enables": ""}]}
    monkeypatch.setattr(doctor, "run_checks", fake)
    return runs


def test_the_settings_page(served, ws, checked):
    from reelsmith.providers.ledger import Ledger
    month = time.strftime("%Y-%m", time.gmtime())
    led = Ledger(ws / "ledger.jsonl")
    led.append({"id": "a", "project": "demo", "tool": "speak", "status": "ok", "cost_usd": 0.25})
    led.append({"id": "b", "project": "demo", "tool": "speak", "status": "ok", "cost_usd": 0.5})
    led.append({"id": "c", "project": "demo", "tool": "draw", "status": "reserved", "est_usd": 0.1})
    with (ws / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2001-01-01T00:00:00+00:00", "id": "old", "tool": "draw", "cost_usd": 9}) + "\n")
    st = jget(served, "/api/settings")
    assert [e["id"] for e in st["engines"]] == list(C.ENGINE_ORDER) and st["default_engine"] == "api"
    assert st["parallel"] == 2 and st["budgets"] == {"request_usd": 1.0, "project_usd": 1.0, "min_balance_usd": 5.0}
    keys = {k["name"]: k for k in st["keys"]}
    assert keys["OPENROUTER_API_KEY"]["present"] is True and keys["OPENROUTER_API_KEY"]["where"] == "env_file"
    assert keys["ANTHROPIC_API_KEY"]["present"] is False and keys["DEEPSEEK_API_KEY"]["used_for"]
    assert "sk-or-test" not in json.dumps(st)
    assert st["spend"] == {"month_usd": 0.85, "by_tool": [{"tool": "speak", "usd": 0.75, "calls": 2},
                                                           {"tool": "draw", "usd": 0.1, "calls": 1}]}
    assert month and st["checks"] == [{"name": "node", "ok": True, "required": True, "detail": "v22", "fix": ""}]
    assert st["env_path"].endswith("/.env") and st["version"] and st["licence"] and st["workspace_path"]
    assert len(checked) == 1
    jget(served, "/api/settings")
    assert len(checked) == 1 and post(served, "/api/settings/checks")[0] == 200 and len(checked) == 2


def test_saving_settings(served, ws, checked):
    (ws / "workspace.json").write_text(json.dumps({"watch": True, "runner": {"engine": "api", "budget_usd": 1},
                                                   "profile": "vertical"}), encoding="utf-8")
    code, st = post(served, "/api/settings", {"parallel": 4, "budgets": {"request_usd": 2.5, "min_balance_usd": 0}})
    assert code == 200 and st["parallel"] == 4 and served.gate.limit == 4
    assert st["budgets"] == {"request_usd": 2.5, "project_usd": 1.0, "min_balance_usd": 0.0}
    saved = json.loads((ws / "workspace.json").read_text("utf-8"))
    assert saved["watch"] == {"open": True, "parallel": 4} and saved["profile"] == "vertical"
    assert saved["runner"] == {"engine": "api", "budget_usd": 2.5} and saved["budget"] == {"min_balance_usd": 0.0}
    assert P.wanted(ws / "projects" / "demo")                         # the window still opens by itself
    assert post(served, "/api/settings", {"default_engine": "codex"})[1]["default_engine"] == "api"   # not here
    assert json.loads((ws / "workspace.json").read_text("utf-8"))["runner"]["engine"] == "codex"
    for bad, why in (({"parallel": 9}, "settings.parallel"), ({"parallel": "3"}, "settings.parallel"),
                     ({"default_engine": "gpt"}, "settings.engine"),
                     ({"budgets": {"request_usd": 0}}, "settings.budget"),
                     ({"budgets": {"project_usd": -1}}, "settings.budget"), ({"colour": "red"}, "settings.unknown")):
        code, got = post(served, "/api/settings", bad)
        assert code == 400 and got["code"] == why and got["error"] == S.say(why, **got["params"])["text"], bad
    assert json.loads((ws / "workspace.json").read_text("utf-8"))["watch"]["parallel"] == 4


def test_keys_are_written_by_name_and_never_shown(served, ws):
    env = ws / ".env"
    env.write_text("# my keys\n# DEEPSEEK_API_KEY=\nOPENROUTER_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    code, got = post(served, "/api/settings/key", {"name": "OPENROUTER_API_KEY", "value": "sk-new value"})
    assert (code, got) == (200, {"name": "OPENROUTER_API_KEY", "present": True})
    assert post(served, "/api/settings/key", {"name": "DEEPSEEK_API_KEY", "value": "ds-1"})[0] == 200
    assert env.read_text("utf-8") == "# my keys\nDEEPSEEK_API_KEY='ds-1'\nOPENROUTER_API_KEY='sk-new value'\nOTHER=1\n"
    assert post(served, "/api/settings/key/delete", {"name": "DEEPSEEK_API_KEY"}) == (
        200, {"name": "DEEPSEEK_API_KEY", "present": False})
    assert env.read_text("utf-8") == "# my keys\nOPENROUTER_API_KEY='sk-new value'\nOTHER=1\n"
    from reelsmith.workspace import Workspace
    assert Workspace.load(ws).keys["OPENROUTER_API_KEY"] == "sk-new value"
    for bad, why in (({"name": "OTHER", "value": "x"}, "key.unknown"), ({"name": "PATH", "value": "x"}, "key.unknown"),
                     ({"name": "OPENAI_API_KEY", "value": "a\nb"}, "key.value"),
                     ({"name": "OPENAI_API_KEY\n", "value": "y"}, "key.unknown"),
                     ({"name": "OPENAI_API_KEY", "value": ""}, "key.value")):
        code, got = post(served, "/api/settings/key", bad)
        assert code == 400 and got["code"] == why and "x" not in json.dumps(got.get("params")), bad
    env.unlink()
    assert post(served, "/api/settings/key", {"name": "OPENAI_API_KEY", "value": "sk-o"})[0] == 200
    text = env.read_text("utf-8")
    assert text.startswith("# Keys for reelsmith") and text.endswith("OPENAI_API_KEY='sk-o'\n")
    assert post(served, "/api/settings/key", {"name": "OPENAI_API_KEY", "value": "x"}, token=False)[0] == 403


def test_a_key_is_read_back_as_written_or_refused(ws):
    from reelsmith.workspace import Workspace
    stored = []
    for value in ("C:\\keys\\a", "back\\slash\\", 'dq"inside', "it's", "it's \"both\"", "it's\\", "x\\\"y'z", "'",
                  "a # not a comment", "  padded  "):
        try:
            A.write_key(Workspace.load(ws), "OPENAI_API_KEY", value)
        except A.Refusal as exc:
            assert exc.code == "key.value" and "'" in value, value      # only a value the reader cannot take back
            continue
        stored.append(value)
        assert Workspace.load(ws).keys["OPENAI_API_KEY"] == value.strip(), value
    assert len(stored) >= 8
    with pytest.raises(A.Refusal):
        A.write_key(Workspace.load(ws), "OPENAI_API_KEY", "two\nlines")
    # one read-modify-write at a time: every key written at once is kept
    names = ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"]
    threads = [threading.Thread(target=A.write_key, args=(Workspace.load(ws), n, f"v-{n}")) for n in names * 3]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    keys = Workspace.load(ws).keys
    assert all(keys[n] == f"v-{n}" for n in names) and not list(ws.glob(".*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes and symbolic links")
def test_the_key_file_is_private_and_a_link_is_followed(ws, tmp_path):
    from reelsmith.workspace import Workspace
    real = tmp_path / "secrets.env"
    real.write_text("OTHER=1\n", encoding="utf-8")
    (ws / ".env").unlink()
    (ws / ".env").symlink_to(real)
    A.write_key(Workspace.load(ws), "OPENAI_API_KEY", "sk-o")
    assert (ws / ".env").is_symlink() and real.read_text("utf-8") == "OTHER=1\nOPENAI_API_KEY='sk-o'\n"
    assert real.stat().st_mode & 0o777 == 0o600


# ------------------------------------------------------------------ one application per workspace, the entry point
def test_a_second_start_brings_the_first_forward(ws, monkeypatch, capsys):
    srv = W.serve(ws)
    raised = []
    srv.raise_window = lambda: raised.append(1)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        A.instance_path(ws).parent.mkdir(parents=True, exist_ok=True)
        A.instance_path(ws).write_text(json.dumps({"pid": other.pid, "url": srv.url, "token": srv.token}),
                                       encoding="utf-8")
        assert A.running_instance(ws)["pid"] == other.pid
        monkeypatch.setattr(window, "available", lambda: True)
        assert entry.main([str(ws / "projects" / "demo")]) == 0
        out = capsys.readouterr().out
        assert raised == [1] and "already running" in out and "brought forward" in out and out.count("\n") == 1
        opened = []
        monkeypatch.setattr(entry.webbrowser, "open", opened.append)
        assert entry.main([str(ws), "--browser"]) == 0 and opened == [srv.url]
        other.kill()
        other.wait()
        assert A.running_instance(ws) is None                       # its process is gone: a stale record
    finally:
        other.kill()
        srv.stop()
    srv2 = W.serve(ws)
    try:
        assert post(srv2, "/api/app/raise") == (200, {"raised": False})        # a browser tab has no window
    finally:
        srv2.stop()


def test_a_record_of_a_pid_another_program_has_does_not_block_a_start(ws, monkeypatch, capsys):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    started = []

    def fake_forever(self, poll_interval=0.5):
        started.append(self.url)
        assert json.loads(A.instance_path(ws).read_text("utf-8"))["pid"] == os.getpid()
        raise KeyboardInterrupt
    try:
        A.instance_path(ws).parent.mkdir(parents=True, exist_ok=True)
        A.instance_path(ws).write_text(json.dumps({"pid": other.pid, "url": "http://127.0.0.1:9/", "token": "t"}),
                                       encoding="utf-8")
        monkeypatch.setattr(W.WatchServer, "serve_forever", fake_forever)
        monkeypatch.setattr(window, "available", lambda: False)
        assert entry.main([str(ws), "--no-open"]) == 0 and len(started) == 1
        assert "already running" not in capsys.readouterr().out and not A.instance_path(ws).exists()
    finally:
        other.kill()


def test_two_starts_at_once_record_one_application(ws, monkeypatch):
    monkeypatch.setattr(A, "answers", lambda row: True)            # whoever recorded first answers
    results = []
    barrier = threading.Barrier(6)

    def claim(i):
        barrier.wait()
        results.append(A.claim_instance(ws, f"http://127.0.0.1:{1000 + i}/", f"t{i}"))
    threads = [threading.Thread(target=claim, args=(i,)) for i in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    winners = [r for r in results if r is None]
    rows = [r for r in results if r is not None]
    kept = json.loads(A.instance_path(ws).read_text("utf-8"))
    assert len(winners) == 1 and len(rows) == 5 and all(r == kept for r in rows)
    assert not list(A.instance_path(ws).parent.glob("*.tmp"))


def test_the_app_command(ws, monkeypatch, capsys):
    served_urls, opened, shown = [], [], []

    def fake_forever(self, poll_interval=0.5):
        served_urls.append(self.url)
        assert A.running_instance(ws) is None and json.loads(A.instance_path(ws).read_text("utf-8"))["url"] == self.url
        raise KeyboardInterrupt
    monkeypatch.setattr(W.WatchServer, "serve_forever", fake_forever)
    monkeypatch.setattr(entry.webbrowser, "open", opened.append)
    monkeypatch.setattr(window, "available", lambda: False)
    assert cli.main(["app", str(ws / "projects" / "demo" / "assets"), "--lang", "ja"]) == 0
    out = capsys.readouterr().out
    assert opened == [f"{served_urls[0]}p/demo/?lang=ja"] and 'pip install "reelsmith[app]"' in out
    assert not A.instance_path(ws).exists()
    assert cli.main(["app", str(ws), "--no-open"]) == 0 and len(opened) == 1
    monkeypatch.setattr(window, "available", lambda: True)
    monkeypatch.setattr(W.WatchServer, "serve_forever", lambda self, poll_interval=0.5: None)

    def fake_window(url, title, ready=None, geometry=None, hooks=None, frame="frameless"):
        shown.append((url, title, geometry, frame))
        hooks["raise"] = lambda: shown.append("raised")
    monkeypatch.setattr(window, "open_window", fake_window)
    assert cli.main(["app", str(ws)]) == 0
    assert shown[0][0].startswith("http://127.0.0.1:") and shown[0][1] == "reelsmith · ws"
    assert shown[0][2] == ws.resolve() / ".cache" / "watch" / "window.json"
    assert shown[0][3] == ("frameless" if os.name == "nt" else "native")     # Windows: the window draws its own
    assert "desktop window" in capsys.readouterr().out
    assert cli.main(["app", str(ws), "--native-frame"]) == 0 and shown[-1][3] == "native"
    cfg = json.loads((ws / "workspace.json").read_text("utf-8"))
    (ws / "workspace.json").write_text(json.dumps({**cfg, "watch": {"frame": "native"}}), encoding="utf-8")
    assert cli.main(["app", str(ws)]) == 0 and shown[-1][3] == "native"
    assert cli.command_parser("app").parse_args(["--port", "0"]).port == 0


def test_a_folder_outside_any_workspace(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setattr(entry, "_terminal", lambda: False)
    assert entry.main([str(bare)]) == 2 and "not inside a workspace" in capsys.readouterr().err
    monkeypatch.setattr(entry, "_terminal", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "n")
    assert entry.main([str(bare)]) == 1 and not (bare / "workspace.json").exists()
    monkeypatch.setattr("builtins.input", lambda q: "y")
    monkeypatch.setattr(W.WatchServer, "serve_forever", lambda self, poll_interval=0.5: None)
    monkeypatch.setattr(window, "available", lambda: False)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: None)
    assert entry.main([str(bare), "--lang", "de"]) == 0
    assert json.loads((bare / "workspace.json").read_text("utf-8"))["locale"] == "de"
    assert (bare / "projects").is_dir() and "created a workspace" in capsys.readouterr().out


# ------------------------------------------------------------------ the desktop window
class FakeWindow:
    def __init__(self, picked=None):
        self.picked, self.titles, self.shown, self.restored = picked, [], 0, 0
        self.calls = []

    def minimize(self):
        self.calls.append("minimize")

    def maximize(self):
        self.calls.append("maximize")

    def destroy(self):
        self.calls.append("destroy")

    def create_file_dialog(self, kind, allow_multiple=False):
        self.kind = (kind, allow_multiple)
        return self.picked

    def set_title(self, text):
        self.titles.append(text)

    def show(self):
        self.shown += 1

    def restore(self):
        self.restored += 1


@pytest.mark.skipif(not window.has_pywebview(), reason="pywebview is not installed")
def test_the_bridge_the_page_may_call():
    w = FakeWindow(("C:/a.png", "C:/b.mp4"))
    api = {fn.__name__: fn for fn in window.bridge(w)}
    assert set(api) == {"set_theme", "pick_files", "pick_folder", "attention", "set_title", "window_state", "minimise",
                        "toggle_maximise", "close", "start_resize", "start_drag"}
    assert api["pick_files"]() == ["C:/a.png", "C:/b.mp4"] and w.kind[1] is True
    assert api["pick_folder"]() == "C:/a.png" and w.kind[1] is False
    w.picked = None
    assert api["pick_files"]() == [] and api["pick_folder"]() is None
    assert api["set_title"]("reelsmith · ws · demo") is True and w.titles == ["reelsmith · ws · demo"]
    assert api["attention"]() is False                  # no native window to flash
    api["set_theme"]("dark")                            # no native window: nothing happens, nothing fails
    window.bring_forward(w)
    assert (w.shown, w.restored) == (1, 1)


def test_the_window_controls_the_page_draws(monkeypatch):
    monkeypatch.setattr(window, "_win32", lambda: None)             # as on macOS or Linux: no native calls
    w, frame = FakeWindow(), window.Frame("frameless")
    api = {fn.__name__: fn for fn in window.bridge(w, frame)}
    assert api["window_state"]() == {"frame": "frameless", "maximised": False}
    assert api["toggle_maximise"]() == {"frame": "frameless", "maximised": True} and w.calls == ["maximize"]
    assert api["window_state"]()["maximised"] is True
    assert api["toggle_maximise"]()["maximised"] is False and w.restored == 1
    assert api["minimise"]() is True and api["close"]() is True and w.calls[-2:] == ["minimize", "destroy"]
    # the top edge is the page's to pass on; with no native window nothing starts, and nothing fails
    assert api["start_resize"]("top") is False and api["start_resize"]("bottom") is False
    assert api["start_drag"]() is False
    assert window.bridge(w)[5]() == {"frame": "native", "maximised": False}    # no frame given: the system's


def test_the_frame_is_frameless_on_windows_unless_asked(monkeypatch):
    assert window.frame_for(system="nt") == "frameless"
    assert window.frame_for(True, system="nt") == "native"                              # --native-frame
    assert window.frame_for(False, {"watch": {"frame": "native", "parallel": 2}}, "nt") == "native"
    assert window.frame_for(False, {"watch": {"frame": "frameless"}}, "nt") == "frameless"
    assert window.frame_for(False, {"watch": True}, "nt") == "frameless"
    assert window.frame_for(system="posix") == "native"                     # macOS and Linux keep their own
    assert entry.parser().parse_args(["--native-frame"]).native_frame is True
    # off Windows (or before the window exists) every native call is a no-op
    monkeypatch.setattr(window, "_win32", lambda: None)
    f = window.Frame("frameless")
    assert f.install(1234) is False and f.grab("top") is False and f.show_restored() is False
    assert f.state() == "normal" and not f.restores_maximised()
    f.maximised = True
    assert f.state() == "maximised" and f.restores_maximised()
    assert window.Frame("other").kind == "native"
    window._frame_theme(FakeWindow(), "dark")                                 # nothing to colour, nothing fails
    assert window._dwm_int(1234, window.DWMWA_WINDOW_CORNER_PREFERENCE, 2) is False


def test_the_caption_gives_its_room_to_the_page():
    assert window.client_top(100, 92, 100, maximised=False) == 100          # flush with the window's top
    assert window.client_top(-8, -8, 0, maximised=True) == 0                # maximised: inset like the sides


class FakeUser32:
    def __init__(self, down):
        self.down, self.calls = down, []

    def GetSystemMetrics(self, i):
        return 0

    def GetAsyncKeyState(self, vk):
        return -32768 if self.down else 0

    def IsZoomed(self, h):
        return False

    def GetCursorPos(self, p):
        p._obj.x, p._obj.y = 300, 20

    def ReleaseCapture(self):
        self.calls.append("release")

    def DefWindowProcW(self, *a):
        self.calls.append(a)


def test_a_move_or_resize_starts_only_while_the_button_is_held():
    f = window.Frame("frameless")
    f.hwnd = 7
    up = FakeUser32(False)
    assert f._grab_now(up, window.HT["top"]) == 0 and up.calls == []          # released before it arrived
    down = FakeUser32(True)
    assert f._grab_now(down, window.HT["top"]) == 1
    assert down.calls == ["release", (7, window.WM_NCLBUTTONDOWN, window.HT["top"], 20 << 16 | 300)]


def test_the_window_remembers_it_was_maximised(tmp_path):
    path = tmp_path / "window.json"
    window.save_geometry(path, {"width": 1300, "height": 800, "x": 40, "y": 30, "maximised": True})
    assert window.load_geometry(path, [])["maximised"] is True
    window.save_geometry(path, {"width": 1300, "height": 800, "x": 40, "y": 30})
    assert window.load_geometry(path, [])["maximised"] is False

    class Events:
        def __init__(self):
            self.handlers = {}

        def __getattr__(self, name):
            return Hook(self.handlers.setdefault(name, []))

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value) if name == "handlers" else None

    class Hook:
        def __init__(self, items):
            self.items = items

        def __iadd__(self, fn):
            self.items.append(fn)
            return self

    w = FakeWindow()
    w.events = Events()
    frame, place = window.Frame("native"), {"width": 1300, "height": 800, "x": 40, "y": 30}
    window.track_place(w, frame, place, path)
    fire = lambda name, *a: [fn(*a) for fn in w.events.handlers[name]]      # noqa: E731
    fire("maximized")
    fire("resized", 2560, 1392)                                 # a maximised size is never kept as the window's size
    fire("moved", -8, -8)
    assert place == {"width": 1300, "height": 800, "x": 40, "y": 30}
    fire("closing")
    assert json.loads(path.read_text("utf-8")) == {"width": 1300, "height": 800, "x": 40, "y": 30, "maximised": True}
    fire("restored")
    fire("resized", 1200, 760)
    fire("moved", 60, 50)
    fire("closing")
    assert json.loads(path.read_text("utf-8")) == {"width": 1200, "height": 760, "x": 60, "y": 50, "maximised": False}


def test_the_window_keeps_its_size_and_place(tmp_path):
    @dataclass
    class Screen:
        width: int = 1920
        height: int = 1080
        x: int = 0
        y: int = 0
    path = tmp_path / "w" / "window.json"
    window.save_geometry(path, {"width": 1300, "height": 800, "x": 40, "y": 30})
    assert window.load_geometry(path, [Screen()]) == {"width": 1300, "height": 800, "x": 40, "y": 30,
                                                     "maximised": False}
    window.save_geometry(path, {"width": 1300, "height": 800, "x": 4000, "y": 30})
    assert window.load_geometry(path, [Screen()]) == {"width": 1300, "height": 800, "maximised": False}  # off it
    window.save_geometry(path, {"width": 300, "height": 200, "x": 0, "y": 0})
    assert window.load_geometry(path, [Screen()]) is None                               # under the minimum
    window.save_geometry(path, {"width": None, "height": 800, "x": 0, "y": 0})          # not saved
    assert window.load_geometry(tmp_path / "missing.json", []) is None


def test_presence_reads_the_new_watch_setting(ws):
    (ws / "workspace.json").write_text(json.dumps({"watch": {"open": True, "parallel": 2}}), encoding="utf-8")
    assert P.wanted(ws / "projects" / "demo")
    (ws / "workspace.json").write_text(json.dumps({"watch": {"parallel": 2}}), encoding="utf-8")
    assert not P.wanted(ws / "projects" / "demo")


def test_an_empty_film_asks_for_nothing(served):
    assert film(served, "b")["empty"] and film(served, "b")["attention"] == [] and film(served, "b")["status"] == "idle"


def test_the_workspace_folders_the_pages_show(served, ws, monkeypatch):
    shown = []
    monkeypatch.setattr(W, "open_folder", shown.append)
    (ws / "library" / "NOTES.md").write_text("# notes", encoding="utf-8")
    for what in ("workspace", "env", "notes"):
        assert post(served, "/api/reveal", {"what": what}) == (200, {"revealed": True, "what": what})
    assert shown == [ws.resolve(), ws.resolve(), (ws / "library").resolve()]
    assert post(served, "/api/reveal", {"what": "desktop"})[1]["code"] == "reveal.what"
    (ws / ".env").unlink()
    code, body = post(served, "/api/reveal", {"what": "env"})
    assert code == 404 and body["code"] == "reveal.missing" and body["params"]["path"].endswith(".env")


def test_a_trashed_film_leaves_no_folder_behind(served, ws):
    site = served.site("demo")
    assert site._cached("frames", "x.jpg").parent.is_dir()
    assert post(served, "/api/films/demo/trash")[0] == 200
    assert site.gone and "demo" not in served.sites
    # a frame still queued, or a poster asked for a moment later, never recreates the folder
    with pytest.raises(W.HTTPError):
        site._cached("frames", "y.jpg")
    assert site._render_frames(b"{}", "k", [0], []) is None
    assert not (ws / "projects" / "demo").exists()
    assert get(served, "/p/demo/api/frame?t=1&h=90")[0] == 404 and not (ws / "projects" / "demo").exists()
