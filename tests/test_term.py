import http.client
import io
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from reelsmith import cli
from reelsmith import render as R
from reelsmith.term import i18n, places
from reelsmith.term import console as TC
from reelsmith.term.session import Session, cells
from reelsmith.term.views import PlainView, table_lines
from reelsmith.watch import presence as P
from reelsmith.watch import server as W

FIXTURE = Path(__file__).parent / "fixtures" / "demo"
TODAY = date(2026, 11, 11)
OBJ = {"type": "object", "properties": {}}


# ------------------------------------------------------------------ fakes: the chat seams, never a real model
class FakeClient:
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


class Tools:
    def __init__(self, extra=()):
        self.entered = threading.Event()
        self.stop = None
        self.extra = list(extra)

    def __call__(self, project, ws, scope, web):
        def hold(args):
            self.entered.set()
            for _ in range(200):
                if self.stop is not None and self.stop.is_set():
                    break
                time.sleep(0.05)
            return Result("held")
        return [Tool("edit", "edits", OBJ, lambda a: Result("edited")), Tool("hold", "waits", OBJ, hold),
                Tool("broken", "fails", OBJ, lambda a: Result("error: it broke", True)), *self.extra]


def only_api(engine, ws):
    return (True, "fake model") if engine == "api" else (False, f"{engine} is not here: install it")


def no_engine(engine, ws):
    return False, f"{engine} needs a sign-in"


def drain(session, timeout: float = 5.0) -> None:
    """Wait until every payload the session heard is shown."""
    until = time.monotonic() + timeout
    while (not session.events.empty() or session._pumping) and time.monotonic() < until:
        time.sleep(0.02)
    time.sleep(0.05)


class Script:
    """The person at the keyboard: each line in turn (a callable gets the session first); EOF when done."""

    def __init__(self, *lines):
        self.lines, self.prompts = list(lines), []

    def __call__(self, prompt, session):
        if session.srv is not None:
            drain(session)
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        item = self.lines.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        return item(session) if callable(item) else item


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "REELSMITH_PROXY", "REELSMITH_ROOT", "REELSMITH_WATCH", i18n.LANG_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(i18n.CONFIG_ENV, str(tmp_path / "config"))
    monkeypatch.setattr(i18n, "system_tag", lambda: None)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE, root / "projects" / "demo", ignore=shutil.ignore_patterns("build", ".history"))
    (root / "workspace.json").write_text(json.dumps({"runner": {"engine": "api", "budget_usd": 1}}), encoding="utf-8")
    (root / "library" / "components").mkdir(parents=True)
    (root / ".env").write_text("OPENROUTER_API_KEY=sk-or-test-1234567\n", encoding="utf-8")
    return root


def run(start, *lines, client=None, tools=None, engines=only_api, lang="en", **kw):
    out = io.StringIO()
    script = Script(*lines)
    opts = {"client_factory": lambda s: client or FakeClient(), "tools_factory": tools or Tools(),
            "engines_fn": engines}
    session = Session(start, PlainView(out), script, lang=lang, chat_options=opts, today=TODAY,
                      open_window=kw.pop("open_window", None), window_ok=kw.pop("window_ok", lambda: False), **kw)
    code = session.run()
    return code, out.getvalue(), session, script


# ------------------------------------------------------------------ where it starts
def test_a_project_opens_with_its_workspace_as_home(ws):
    code, out, s, script = run(ws / "projects" / "demo" / "assets", "/projects")
    assert code == 0
    assert "Workspace  " + str(ws) in out and "Engine     API · fake model" in out and "English" in out
    assert script.prompts[0] == "demo › " and script.prompts[1] == "reelsmith › "
    assert "Films in ws" in out and "demo" in out
    assert not (ws / "projects" / "demo" / "build" / "watch" / "window.json").exists()      # forgotten on leaving


def test_a_workspace_folder_opens_the_home(ws):
    (ws / "notes").mkdir()
    code, out, s, script = run(ws / "notes")
    assert code == 0 and "Films in ws" in out and script.prompts == ["reelsmith › "]


def test_neither_offers_a_workspace(tmp_path):
    empty = tmp_path / "plain"
    empty.mkdir()
    code, out, *_ = run(empty, "n")
    assert code == 1 and "is neither a project nor a workspace" in out and not (empty / "workspace.json").exists()
    code, out, s, script = run(empty, "y")
    assert code == 0 and "A workspace was created" in out
    assert json.loads((empty / "workspace.json").read_text("utf-8"))["locale"] == "en"
    assert (empty / "projects").is_dir() and (empty / "library" / "NOTES.md").is_file()
    assert "OPENROUTER_API_KEY=" in (empty / ".env").read_text("utf-8") and script.prompts[-1] == "reelsmith › "


def test_a_project_outside_a_workspace_has_no_home(tmp_path):
    p = tmp_path / "alone"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    code, out, s, script = run(p, "/projects", "/new x")
    assert code == 0 and script.prompts[0] == "alone › "
    assert "there is no list of films" in out and "A new film requires a workspace" in out


# ------------------------------------------------------------------ the home
def test_the_home_table_aligns_cjk_and_lists_newest_first(ws):
    other = ws / "projects" / "zh"
    shutil.copytree(ws / "projects" / "demo", other)
    data = json.loads((other / "project.json").read_text("utf-8"))
    data.setdefault("meta", {})["title"] = "潮汐的秘密"
    (other / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    old = time.time() - 7200
    for f in (ws / "projects" / "demo").rglob("*"):
        os.utime(f, (old, old))
    code, out, s, _ = run(ws)
    lines = out.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith("#  Name"))
    rows = lines[head:head + 3]
    assert rows[1].split()[:2] == ["1", "zh"] and rows[2].split()[:2] == ["2", "demo"]
    assert "潮汐的秘密" in rows[1] and "2 h ago" in rows[2] and "just now" in rows[1]
    film_col = [cells(r[:r.index(w)]) for r, w in zip(rows, ("Film", "none", "none"))]
    assert len(set(film_col)) == 1                     # the Film column starts at the same cell on every row
    assert table_lines(["a", "b"], [["潮汐", "x"], ["ab", "y"]]) == ["a     b", "潮汐  x", "ab    y"]


def test_opening_by_number_and_by_name(ws):
    shutil.copytree(ws / "projects" / "demo", ws / "projects" / "second")
    code, out, s, script = run(ws, "2", "/projects", "DEMO", "/open 1", "/open nothing", "/open")
    names = [p for p in script.prompts]
    assert names[1].endswith(" › ") and names[1] != "reelsmith › "
    assert names[3] == "demo › " and names[4].endswith(" › ")
    assert 'There is no project "nothing"' in out and "/open NUMBER" in out


def test_text_at_home_starts_a_new_film(ws):
    client = FakeClient(reply("Starting the film.", [("edit", {"project": "x", "ops": "[]"})]), reply("Done."))
    code, out, s, script = run(ws, "Make a short film about Tides, please!", "", client=client)
    name = "2026-11-11-make-a-short-film"
    assert (ws / "projects" / name / "project.json").is_file()
    assert f"Create the film {name} and send this text as its first request? [Y/n] " in script.prompts
    assert f"The film {name} was created." in out and script.prompts[-1] == f"{name} › "
    assert client.calls[0][-1]["content"].endswith("Make a short film about Tides, please!")
    assert "Starting the film." in out and "[ok] Edit" in out and "Completed in" in out
    code, out, s, script = run(ws, "/new", "/projects", "/new custom_name", "/new bad name!")
    assert (ws / "projects" / "2026-11-11-film").is_dir() and (ws / "projects" / "custom_name").is_dir()
    assert "A name can use only the letters A–Z" in out
    assert places.new_name(s.ws or places.locate(ws).workspace, "Make a short film about tides", TODAY) == \
        name + "-2"
    assert places.slug("潮汐") == "film"


# ------------------------------------------------------------------ a request
def test_a_turn_streams_tool_rows_and_ends_with_a_summary(ws):
    client = FakeClient(reply("Looking at it.", [("edit", {"project": "p", "ops": "[]"}), ("broken", {})]),
                        reply("**Nothing** needed changing."))
    code, out, *_ = run(ws / "projects" / "demo", "What is at 10 s?", client=client)
    lines = out.splitlines()
    i = lines.index("Looking at it.")
    assert lines[i + 1].startswith("  [ok] Edit") and lines[i + 1].endswith("s)")
    assert lines[i + 2].startswith("  [failed] Tool broken") and "it broke" in lines[i + 3]
    assert lines[i + 4] == "**Nothing** needed changing."
    assert lines[i + 5].startswith("Completed in ") and "this request $0.02" in lines[i + 5]
    assert "$0.02 of $1.00 spent" in lines[i + 5]
    assert "What is at 10 s?" not in out.replace("demo › ", "")        # the terminal's own message is not echoed


def test_ctrl_c_stops_the_turn(ws):
    tools = Tools()
    client = FakeClient(reply("Working.", [("hold", {})]), reply("Back."))
    pressed = []

    def setup(session):
        tools.stop = session.site(session.current).chat._stop
        real = session.wait_once

        def wait_once():
            if tools.entered.is_set() and len(pressed) < 2:
                pressed.append(1)
                raise KeyboardInterrupt
            real()
        session.wait_once = wait_once
        return "do it"
    code, out, *_ = run(ws / "projects" / "demo", setup, "again", client=client, tools=tools)
    assert "Stopping: the agent completes its current step first." in out
    assert "The request is being stopped." in out and "Stopped after" in out
    assert out.index("Stopped after") < out.index("Back.") and out.count("Completed in") == 1


def test_a_used_up_budget_and_an_engine_failure_say_what_to_do(ws):
    p = ws / "projects" / "demo"
    (p / "build").mkdir(exist_ok=True)
    (p / "build" / "chat_state.json").write_text(json.dumps({"cost_usd": 0.99}), encoding="utf-8")
    code, out, *_ = run(p, "anything")
    assert "The agent budget of $1.00 is used up ($0.99 spent)" in out and "runner.budget_usd" in out
    (p / "build" / "chat_state.json").unlink()

    def boom(messages):
        raise RuntimeError("the provider is down")
    code, out, *_ = run(p, "anything", client=FakeClient(boom))
    assert "The request failed:" in out and "the provider is down" in out and "reelsmith doctor" in out


def test_a_refused_render_says_why_and_what_next(ws):
    p = ws / "projects" / "demo"

    def refuse(args):
        (p / "build").mkdir(exist_ok=True)
        (p / "build" / "report.json").write_text(json.dumps(
            {"ok": False, "stage": "check", "error": "errors", "inputs": {"cut": R.film_inputs(p)["cut"]}}),
            encoding="utf-8")
        return Result("REFUSED: the project has errors", True)
    tools = Tools([Tool("render", "renders", OBJ, refuse)])
    code, out, *_ = run(p, "Render it.", client=FakeClient(reply(None, [("render", {})]), reply("It was refused.")),
                        tools=tools)
    assert "[failed] Render" in out and "The render was refused: the project has errors" in out
    assert "/check to list the issues" in out


def test_a_message_from_the_window_shows_in_the_terminal(ws):
    client = FakeClient(reply("Answered for the window."))

    def from_window(session):
        srv = session.srv
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
        conn.request("POST", "/p/demo/api/chat", body=json.dumps({"message": "Sent from the window"}).encode(),
                     headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{srv.port}",
                              W.TOKEN_HEADER: srv.token})
        assert conn.getresponse().status == 202
        conn.close()
        assert session.site("demo").chat.wait(20)
        return "/status"
    code, out, *_ = run(ws / "projects" / "demo", from_window, client=client)
    assert "From the window: Sent from the window" in out and "Answered for the window." in out
    assert "Completed in" in out


def test_a_request_on_another_project_is_reported_in_one_line(ws):
    client = FakeClient(reply("Answered elsewhere."))

    def elsewhere(session):
        site = session.site("demo")
        site.send_chat("From the window, while the terminal is at home", None, None)
        assert site.chat.wait(20)
        return "/projects"
    code, out, *_ = run(ws, elsewhere, client=client)
    assert "demo: the request is complete. /open demo shows it." in out and "Answered elsewhere." not in out


def test_another_process_window_keeps_the_project(ws):
    p = ws / "projects" / "demo"
    (p / "build" / "watch").mkdir(parents=True)
    (p / "build" / "watch" / "window.json").write_text(json.dumps({"pid": os.getppid(), "url": "http://x/"}),
                                                       encoding="utf-8")
    assert P.window_of(p)
    code, out, s, script = run(p)
    assert "A watch window of another process is open on demo" in out and "Close that window first" in out
    assert script.prompts == ["reelsmith › "]


def test_another_process_taking_the_project_refuses_requests_and_actions(ws):
    p = ws / "projects" / "demo"

    def taken(session):
        (p / "build" / "watch" / "window.json").write_text(json.dumps({"pid": os.getppid(), "url": "http://x/"}),
                                                           encoding="utf-8")
        return "Do something."
    client = FakeClient()
    code, out, *_ = run(p, taken, "/check", client=client)
    assert out.count("This film is open in another window (http://x/).") == 2 and client.calls == []


def test_a_turn_that_ends_before_send_returns_does_not_hang(ws):
    def boom(messages):
        raise RuntimeError("the provider is down")

    def slow_return(session):
        site = session.site(session.current)
        real = site.send_chat

        def send_chat(*a):
            turn = real(*a)
            assert site.chat.wait(10)
            drain(session)                      # the end note is shown before send_chat returns
            return turn
        site.send_chat = send_chat
        return "anything"
    began = time.monotonic()
    code, out, s, script = run(ws / "projects" / "demo", slow_return, "/status", client=FakeClient(boom))
    assert "The request failed:" in out and "Beats" in out and time.monotonic() - began < 30
    assert script.prompts.count("demo › ") == 3


def test_text_at_home_never_starts_a_request_by_accident(ws):
    client = FakeClient()
    code, out, s, script = run(ws, "7", "help", "tides", "A film about tides", "n", "exit", "never", client=client)
    assert "There is no film number 7." in out and "Commands" in out
    assert 'There is no film named "tides". /new tides creates it.' in out and "No film was created." in out
    assert script.lines == ["never"] and client.calls == []
    assert sorted(p.name for p in (ws / "projects").iterdir()) == ["demo"]
    code, out, s, script = run(ws, "帮助", "退出", "never", lang="zh-CN")
    assert "命令" in out and script.lines == ["never"]
    code, out, s, script = run(ws, "q", "never")
    assert script.lines == ["never"]


def test_new_films_go_through_the_server(ws, monkeypatch):
    asked = []
    real = W.WatchServer.create_project

    def create(self, name):
        asked.append(name)
        return real(self, name)
    monkeypatch.setattr(W.WatchServer, "create_project", create)
    code, out, s, script = run(ws, "/new Demo", "/new con", "/new fresh", "/projects", "/new")
    assert asked == ["Demo", "con", "fresh", "2026-11-11-film"]
    assert 'A film named "Demo" already exists in this workspace.' in out
    assert '"con" is reserved by the operating system.' in out
    assert "The film fresh was created." in out and script.prompts[3] == "fresh › "


def test_the_home_lists_the_servers_films(ws):
    shutil.copytree(ws / "projects" / "demo", ws / "projects" / "second")
    code, out, s, _ = run(ws)
    s.srv = W.serve(ws, chat_options={"engines_fn": only_api})
    try:
        assert [f["name"] for f in s.films()] == [r["name"] for r in s.srv.projects()]
    finally:
        s.srv.stop()
    assert not hasattr(places, "projects") and not hasattr(places, "project_row")


def test_the_window_child_has_its_own_process_group(monkeypatch):
    import subprocess
    from reelsmith.term import window as TW
    seen = {}
    monkeypatch.setattr(TW.subprocess, "Popen", lambda cmd, **kw: seen.update(kw) or "proc")
    assert TW.launch("http://127.0.0.1:1/", "t") == "proc"
    if os.name == "nt":
        assert seen["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert seen["start_new_session"] is True


def test_ctrl_c_during_a_stop_and_while_closing(ws):
    import signal
    tools = Tools()
    client = FakeClient(reply("Working.", [("hold", {})]), reply("Back."))
    opened = []

    class Proc:
        def poll(self):
            return None

        def terminate(self):
            opened.append("closed")

    def setup(session):
        site = session.site(session.current)
        tools.stop = site.chat._stop
        real_act, real_wait = site.act, session.wait_once
        pressed = []

        def act(name):
            got = real_act(name)
            if name == "stop" and not pressed:
                pressed.append("during the stop")
                raise KeyboardInterrupt
            return got

        def wait_once():
            if tools.entered.is_set() and not pressed:
                raise KeyboardInterrupt
            real_wait()
        site.act, session.wait_once = act, wait_once
        return "do it"

    def presses_while_closing(session):
        srv, real_stop = session.srv, session.srv.stop

        def stop():
            signal.raise_signal(signal.SIGINT)
            signal.raise_signal(signal.SIGINT)
            real_stop()
        srv.stop = stop
        session.window = Proc()
        return "/status"
    code, out, s, script = run(ws / "projects" / "demo", setup, presses_while_closing, client=client, tools=tools)
    assert code == 0 and "The request is being stopped." in out and "Stopped after" in out, out
    assert out.count("The session is closing.") == 1 and opened == ["closed"] and s.srv is None


def test_stop_ends_a_request_started_in_the_window(ws):
    tools = Tools()
    client = FakeClient(reply("Working.", [("hold", {})]))

    def window_turn(session):
        site = session.site("demo")
        tools.stop = site.chat._stop
        site.send_chat("Sent from the window", None, None)
        assert tools.entered.wait(10)
        return "/stop"

    def later(session):
        assert session.site("demo").chat.wait(20)
        return "/stop"
    code, out, *_ = run(ws / "projects" / "demo", window_turn, later, client=client, tools=tools)
    assert "From the window: Sent from the window" in out
    assert "Stopping: the agent completes its current step first." in out and "Stopped after" in out
    assert out.index("Stopped after") < out.index("Nothing is running.")


def test_a_long_action_returns_to_the_prompt_on_a_second_ctrl_c(ws, monkeypatch):
    real = W.ACTIONS["check"]

    def slow(root):
        time.sleep(1.5)
        return real(root)
    monkeypatch.setitem(W.ACTIONS, "check", slow)
    still = []

    def setup(session):
        presses = iter([KeyboardInterrupt, KeyboardInterrupt])

        def pause():
            exc = next(presses, None)
            if exc is not None:
                raise exc
            time.sleep(0.1)
        session.pause = pause
        return "/check"

    def later(session):
        site = session.site("demo")
        still.append(bool(site.action))
        assert site.wait_action(10)
        time.sleep(0.8)
        return "/status"
    code, out, *_ = run(ws / "projects" / "demo", setup, later)
    assert still == [True]
    assert "This action cannot be interrupted." in out and "The action continues" in out
    end = out.index("The action continues")
    assert "The check found" in out[end:] and out[end:].index("The check found") < out[end:].index("Beats")


def test_an_action_started_in_the_window_is_reported_in_one_line(ws):
    def from_window(session):
        site = session.site("demo")
        site.act("check")
        assert site.wait_action(10)
        time.sleep(0.8)
        return "/projects"

    def elsewhere(session):
        site = session.site("demo")
        site.act("check")
        assert site.wait_action(10)
        time.sleep(0.8)
        return "/help"
    code, out, *_ = run(ws / "projects" / "demo", from_window, elsewhere)
    assert "] The check found" in out and "demo: The check found" in out and out.count("The check found") == 2


def test_engine_reasons_sides_and_punctuation_follow_the_language(ws):
    def probe(engine, ws):
        if engine == "api":
            return {"available": True, "why": "OpenRouter m1", "code": "engine.api_ready",
                    "params": {"provider": "OpenRouter", "model": "m1"}}
        return {"available": False, "why": "OPENROUTER_API_KEY is missing", "code": "engine.key_missing",
                "params": {"key": "OPENROUTER_API_KEY"}}
    code, out, s, _ = run(ws / "projects" / "demo", "/engine", "/engine codex", "/engine gpt", lang="zh-CN",
                          engines=probe)
    assert "API · OpenRouter m1" in out and "缺少 OPENROUTER_API_KEY：请将其添加到工作区的 .env 文件" in out
    assert "agent-sdk、codex、dsh、api" in out and "codex 引擎无法在此运行：缺少 OPENROUTER_API_KEY" in out
    assert "左" in s.say_code("code.layout.cut_by_edge", {"text": "x", "side": "left", "px": 3})
    refused = W.HTTPError(400, {"code": "chat.engine_unavailable", "params": {"engine": "dsh", "why": "English"}})
    assert "缺少 OPENROUTER_API_KEY" in s.refusal(refused) and "English" not in s.refusal(refused)
    assert s.view.marks == (s.t("mark.ok"), s.t("mark.failed")) and s.t("who.says", who="你") == "你："


def test_the_cli_decides_without_the_session_stack():
    import subprocess
    import sys
    probe = ("import sys, reelsmith.cli as c, reelsmith.tools, reelsmith.mcp_server; c._terminal(); "
             "print(sorted(m for m in sys.modules if m.split('.')[0] == 'prompt_toolkit' "
             "or m.startswith('reelsmith.term') or m == 'reelsmith.watch.server'))")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    got = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120)
    assert got.returncode == 0 and got.stdout.strip() == "[]", got.stderr
    probe = "import sys, reelsmith.cli, reelsmith.tools; print('rich' in sys.modules)"
    got = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120)
    assert got.stdout.strip() == "False", got.stderr


# ------------------------------------------------------------------ commands
def test_each_command(ws):
    opened = []

    def window(url, title):
        opened.append((url, title))

        class Proc:
            def poll(self):
                return None

            def terminate(self):
                opened.append("closed")
        return Proc()
    code, out, s, script = run(
        ws / "projects" / "demo", "/help", "/status", "/stop", "/check", "/undo", "/redo", "/accept", "/render",
        "/window",
        "/window", "/engine", "/engine codex", "/engine api", "/engine gpt", "/lang", "/lang xx", "/stauts", "/nope",
        "/quit", "never read", open_window=window, window_ok=lambda: True)
    assert code == 0 and script.lines == ["never read"]
    for c in ("/help", "/projects", "/open N|NAME", "/new [NAME]", "/status", "/stop", "/check", "/render", "/undo",
              "/redo", "/accept", "/window", "/engine [ID]", "/lang [CODE]", "/quit"):
        assert f"  {c} " in out
    assert "Beats" in out and "Agent spend" in out and "Provider spend" in out and "Nothing is running." in out
    assert "The check found" in out
    assert "There is no change to undo." in out and "There is no undone change to restore." in out
    assert "Only a delivered film that matches the current cut can be accepted." in out
    assert opened[0][0].endswith("/p/demo/") and opened[0][1] == "reelsmith · demo"
    assert "The window is already open" in out and opened[-1] == "closed"
    assert " * api" in out and "The codex engine cannot run here" in out and "The next requests go to API." in out
    assert 'Unknown engine "gpt"' in out and " * en" in out and 'Unknown language "xx"' in out
    assert "Unknown command /stauts. Did you mean /status?" in out and "Unknown command /nope." in out
    assert any(r in out for r in ("The render was refused", "The project does not load", "already matches"))


def test_actions_go_through_the_window_lock(ws):
    p = ws / "projects" / "demo"
    seen = []

    def watch(session):
        site = session.site("demo")
        real = site.act

        def act(name):
            seen.append(name)
            return real(name)
        site.act = act
        return "/check"
    code, out, *_ = run(p, watch, "/undo")
    assert seen == ["check", "undo"]


def test_the_window_falls_back_to_a_browser_address(ws):
    code, out, s, _ = run(ws, "/window", window_ok=lambda: False)
    assert "Open this address in a browser: http://127.0.0.1:" in out


def test_completion_offers_commands_names_engines_and_languages(ws):
    code, out, s, _ = run(ws)
    s.srv = W.serve(ws, chat_options={"engines_fn": only_api})
    try:
        assert ("/render", "Render and deliver the film") in s.completions("/re")
        assert [c for c, _ in s.completions("/open d")] == ["/open demo"]
        assert [c for c, _ in s.completions("/engine c")] == ["/engine codex"]
        assert [c for c, _ in s.completions("/lang z")] == [f"/lang {c}" for c in i18n.available() if c.startswith("z")]
        assert s.completions("hello") == []
    finally:
        s.srv.stop()
    assert s.history_path() == ws / ".cache" / "term" / "history"


def test_no_engine_says_why_and_how(ws):
    code, out, *_ = run(ws / "projects" / "demo", "Do something.", engines=no_engine)
    assert "Engine     None available" in out and "No agent engine can run on this computer" in out
    for e in ("agent-sdk", "codex", "dsh", "api"):
        assert f"{e} needs a sign-in" in out


def test_quitting_with_ctrl_c_twice_and_ctrl_d(ws):
    code, out, s, script = run(ws, KeyboardInterrupt, "", KeyboardInterrupt, KeyboardInterrupt, "never")
    assert code == 0 and "Press Ctrl+C again to leave" in out and script.lines == ["never"]
    code, out, s, script = run(ws, EOFError, "never")
    assert code == 0 and script.lines == ["never"]


# ------------------------------------------------------------------ languages
def test_the_language_choice_and_saving(ws, monkeypatch, tmp_path):
    assert i18n.choose() == "en"
    monkeypatch.setattr(i18n, "system_tag", lambda: "zh_CN.UTF-8")
    assert i18n.choose() == "zh-CN"
    monkeypatch.setattr(i18n, "system_tag", lambda: "Chinese (Simplified)_China")
    assert i18n.choose() == "zh-CN"
    i18n.save_setting("lang", "en")
    assert i18n.choose() == "en"                                 # the saved choice before the system's
    monkeypatch.setenv(i18n.LANG_ENV, "zh-CN")
    assert i18n.choose() == "zh-CN" and i18n.choose("en") == "en"   # the flag first, then the environment
    monkeypatch.delenv(i18n.LANG_ENV)
    code, out, s, _ = run(ws, "/lang zh-CN", "/help", lang=None)
    assert "界面语言已设为简体中文。" in out and "列出命令和按键" in out
    assert json.loads((tmp_path / "config" / "term.json").read_text("utf-8")) == {"lang": "zh-CN"}
    code, out, *_ = run(ws, lang=None)
    assert "ws 中的影片" in out and "语言" in out
    assert i18n.match("ja-JP") == ("ja" if "ja" in i18n.available() else None)


def test_every_language_has_the_english_keys_and_placeholders():
    import re
    en = i18n.load("en")
    for code in i18n.available():
        own = i18n.load(code)
        if code in ("en", "zh-CN"):
            assert set(own) == set(en), code
        for key, text in own.items():
            assert key in en, (code, key)
            assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", en[key])), (code, key)
            assert "!" not in text and "！" not in text, (code, key)


# ------------------------------------------------------------------ the command line
def test_bare_reelsmith_without_a_terminal_keeps_the_usage(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_terminal", lambda: False)
    with pytest.raises(SystemExit) as stop:
        cli.main([])
    assert stop.value.code == 2 and "usage: reelsmith" in capsys.readouterr().err
    help_text = cli._parser().format_help()
    first = help_text.split("  command", 1)[1].split()[:2]
    assert first == ["app", "Open"] and "\n    chat " in help_text


def test_bare_reelsmith_in_a_terminal_opens_the_application(monkeypatch):
    from reelsmith.watch import entry
    started, opened = [], []
    monkeypatch.setattr(cli, "_terminal", lambda: True)
    monkeypatch.setattr(TC, "main", lambda argv: started.append(argv) or 0)
    monkeypatch.setattr(entry, "main", lambda argv: opened.append(argv) or 0)
    assert cli.main([]) == 0 and cli.main(["chat", "x", "--plain"]) == 0 and cli.main(["app", "y"]) == 0
    assert opened == [[], ["y"]] and started == [["x", "--plain"]]


def test_plain_mode_from_the_command_line(ws, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("/engine\n/quit\n"))
    assert cli.main(["chat", str(ws), "--plain", "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "Films in ws" in out and "Agent engines" in out and "\x1b[" not in out
    assert cli.command_parser("chat").parse_args([str(ws), "--engine", "api"]).engine == "api"


# ------------------------------------------------------------------ the terminal parts, without a terminal
def test_the_prompt_completes_keeps_history_and_clears_on_ctrl_c(ws):
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    code, out, s, _ = run(ws)
    s.srv = W.serve(ws, chat_options={"engines_fn": only_api})
    try:
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
            reader = TC.PromptReader(input=pipe, output=DummyOutput())
            got = []
            import contextvars
            here = contextvars.copy_context()                 # the app session lives in a context variable
            typing = threading.Thread(target=lambda: got.append(here.run(reader, "reelsmith › ", s)))
            typing.start()
            for keys in ("/stat", "\t", "\r"):                # completion runs while the person types
                time.sleep(0.4)
                pipe.send_text(keys)
            typing.join(10)
            assert got == ["/status"]
            pipe.send_text("draft text\x03/quit\r")        # Ctrl+C clears the line that has text
            assert reader("reelsmith › ", s) == "/quit"
            pipe.send_text("\x03")                         # and is passed on at an empty one
            with pytest.raises(KeyboardInterrupt):
                reader("reelsmith › ", s)
            pipe.send_text("\x04")
            with pytest.raises(EOFError):
                reader("reelsmith › ", s)
    finally:
        s.srv.stop()
    history = (ws / ".cache" / "term" / "history").read_text("utf-8")
    assert "/status" in history and "/quit" in history


def test_the_rich_view_draws_the_same_session():
    from rich.console import Console
    from reelsmith.term.views import RichView
    buf = io.StringIO()
    v = RichView(Console(file=buf, force_terminal=True, width=80, color_system=None))
    v.header("reelsmith 0.1.0", [("Workspace", "D:/ws"), ("Language", "简体中文")])
    v.table(["#", "Name", "Title"], [["1", "zh", "潮汐的秘密"], ["2", "demo", "Demo"]], right=(0,),
            states=["current", "none"])
    v.begin_wait("Processing the request")
    v.status("Rendering the film: rendering frames (40 %)")
    v.say("**Done**:\n\n- one")
    v.tool(True, "Edit", "title", "2.1 s", "")
    v.tool(False, "Render", "", "12 s", "REFUSED: errors")
    v.end_wait()
    v.summary("Completed in 14 s · this request $0.02", "end")
    text = buf.getvalue()
    assert "1  zh    潮汐的秘密" in text and "✓ Edit · title  2.1 s" in text and "✗ Render  12 s" in text
    assert "Done:" in text and "**" not in text and "Completed in 14 s" in text


def test_latest_messages_fit_the_width_without_markdown(ws):
    long = "## The opening\n\n- The delta shot holds for **1.9 s**, then `river` takes over. " + "More words. " * 20
    run(ws / "projects" / "demo", "Describe the opening.", client=FakeClient(reply(long)))
    code, out, *_ = run(ws / "projects" / "demo")
    recent = [ln for ln in out.splitlines() if ln.startswith("  Agent: ")]
    assert recent and all(cells(ln) < 100 for ln in recent)
    assert recent[-1].startswith("  Agent: The opening The delta shot holds for 1.9 s, then river takes over.")
    assert "**" not in recent[-1] and "`" not in recent[-1] and recent[-1].endswith("…")


def test_a_long_detail_counts_the_lines_left_out():
    from reelsmith.term.views import DETAIL_LINES, detail_lines
    out = io.StringIO()
    PlainView(out).detail("\n".join(f"[error] line {i}" for i in range(16)))
    lines = out.getvalue().splitlines()
    assert len(lines) == DETAIL_LINES and lines[-1] == "    … (+5)" and lines[-2] == "    [error] line 10"
    assert detail_lines("a\nb") == ["a", "b"]


def test_the_plain_reader_shows_piped_input():
    out = io.StringIO()
    reader = TC.PlainReader(io.StringIO("/status\n"), out)
    assert reader("demo › ", None) == "/status"
    with pytest.raises(EOFError):
        reader("demo › ", None)
    assert out.getvalue() == "demo › /status\ndemo › \n"


def test_plain_output_from_another_thread_keeps_the_prompt():
    out = io.StringIO()
    view = PlainView(out)
    view.prompting("demo › ")
    for text in ("A", "B"):
        writer = threading.Thread(target=view.line, args=(text,))
        writer.start()
        writer.join()
    time.sleep(0.4)
    assert out.getvalue() == "demo › \nA\nB\ndemo › "
    view.answered("typed elsewhere")
    assert out.getvalue().endswith("demo › typed elsewhere\n")

    class Holder:
        pass
    holder = Holder()
    holder.view = PlainView(io.StringIO())
    assert TC.PlainReader(io.StringIO("y\n"))("p › ", holder) == "y"
    assert holder.view.out.getvalue() == "p › y\n"


def test_piped_input_is_read_as_utf8(ws, monkeypatch, capsys):
    stdin = io.TextIOWrapper(io.BytesIO("/open 潮汐\n/quit\n".encode("utf-8")), encoding="latin-1")
    monkeypatch.setattr("sys.stdin", stdin)
    assert cli.main(["chat", str(ws), "--plain", "--lang", "en", "--engine", "api"]) == 0
    assert 'There is no project "潮汐"' in capsys.readouterr().out


def test_the_rich_view_reads_on_light_and_dark_grounds():
    from rich.console import Console
    from reelsmith.term.views import RichView
    buf = io.StringIO()
    v = RichView(Console(file=buf, force_terminal=True, width=80, color_system="standard"))
    v.header("reelsmith 0.1.0", [("Workspace", "D:/ws")])
    v.tool(True, "Edit", "title", "2.1 s", "")
    v.say("# Opening\n\nThe delta shot holds.")
    text = buf.getvalue()
    assert "\x1b[2m" not in text.split("D:/ws")[0]               # the label is not dimmed
    lines = re.sub(r"\x1b\[[0-9;]*m", "", text).splitlines()
    i = next(n for n, ln in enumerate(lines) if "✓ Edit" in ln)
    assert lines[i + 1] == "" and lines[i + 2].startswith("Opening")   # a blank line, a heading on the left
    assert "\x1b[35m" not in text and "\x1b[4m" not in text           # no magenta, no underline
