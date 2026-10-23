import asyncio
import io
import json
import os
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

from reelsmith import guard, runner
from reelsmith.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    (root / "library" / "components").mkdir(parents=True)
    (root / "library" / "NOTES.md").write_text("# notes\n", encoding="utf-8")
    (root / "workspace.json").write_text(json.dumps({"profile": "douyin", "runner": {"budget_usd": 3}}),
                                         encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test-123456\nANTHROPIC_WORKSPACE_ID=wrkspc_1\n",
                               encoding="utf-8")
    (root / "ledger.jsonl").write_text("", encoding="utf-8")
    project = root / "projects" / "p1"
    (project / "assets").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"version": 2, "meta": {"title": "t"}, "tracks": []}),
                                          encoding="utf-8")
    return Workspace.load(root), project


def result(cost=0.5, turns=3, sid="s1", subtype="success"):
    return ResultMessage(subtype=subtype, duration_ms=10, duration_api_ms=10, is_error=subtype != "success",
                         num_turns=turns, session_id=sid, total_cost_usd=cost)


def fake_query(*scripts, calls=None):
    """Each call to query() plays the next script: a list of messages, or a callable(project) run first."""
    queue = list(scripts)

    async def query(prompt, options):
        calls.append({"prompt": prompt, "options": options}) if calls is not None else None
        script = queue.pop(0)
        for msg in script:
            if callable(msg):
                msg(Path(options.cwd))
                continue
            if isinstance(msg, BaseException):
                raise msg
            await asyncio.sleep(0)
            yield msg
    return query


def init(sid="s1"):
    return SystemMessage(subtype="init", data={"session_id": sid, "model": "claude-opus-5-5", "tools": [],
                                               "mcp_servers": [{"name": "reelsmith", "status": "connected"}]})


def deliver(project: Path):
    (project / "out").mkdir(exist_ok=True)
    (project / "out" / "film.mp4").write_bytes(b"x")
    (project / "out" / "report.json").write_text('{"ok": true}', encoding="utf-8")


@pytest.fixture
def no_checks(monkeypatch):
    monkeypatch.setattr("reelsmith.checks.check_project", lambda project: [])


def go(project, query, **kw):
    return runner.run(project, query_fn=query, out=io.StringIO(), **kw)


# ------------------------------------------------------------------ settings and options
def test_settings_precedence(ws):
    w, _ = ws
    s = runner.settings_for(w)
    assert s.budget_usd == 3 and s.model == "claude-opus-5-5"
    s = runner.settings_for(w, model="claude-sonnet-5-5", budget_usd=1.5, max_minutes=10)
    assert (s.model, s.budget_usd, s.max_minutes) == ("claude-sonnet-5-5", 1.5, 10)
    with pytest.raises(runner.WorkspaceError):
        runner.settings_for(w, budget_usd=0)


def test_options(ws):
    w, project = ws
    s = runner.settings_for(w)
    log = runner.SessionLog(project, io.StringIO())
    scope = guard.scope_for(project, w)
    o = runner.build_options(project, w, s, scope, log, resume="abc", budget_left=1.234)
    log.close()
    assert o.model == "claude-opus-5-5" and o.resume == "abc" and o.max_budget_usd == 1.23
    assert o.cwd == str(project) and o.setting_sources == [] and o.permission_mode == "dontAsk"
    assert "Bash" not in o.tools and "mcp__reelsmith__render" in o.allowed_tools
    assert "mcp__reelsmith__edit" in o.allowed_tools
    server = o.mcp_servers["reelsmith"]
    assert server["args"] == ["-m", "reelsmith.mcp_server"]
    assert server["env"]["REELSMITH_ROOT"] == str(w.root)
    assert o.env["ANTHROPIC_API_KEY"] == "sk-ant-test-123456"
    assert o.env["ANTHROPIC_CUSTOM_HEADERS"] == "anthropic-workspace-id: wrkspc_1"
    assert "manual.md" in o.system_prompt["append"] and "NOTES.md" in o.system_prompt["append"]
    assert o.hooks["PreToolUse"][0].hooks


def test_missing_key(ws, monkeypatch):
    w, project = ws
    (w.root / ".env").write_text("", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    w = Workspace.load(w.root)
    log = runner.SessionLog(project, io.StringIO())
    with pytest.raises(runner.WorkspaceError, match="ANTHROPIC_API_KEY"):
        runner.build_options(project, w, runner.settings_for(w), guard.scope_for(project, w), log)
    log.close()


# ------------------------------------------------------------------ runs
def test_delivered_run(ws, no_checks):
    _, project = ws
    calls = []
    q = fake_query([init(), AssistantMessage(content=[TextBlock("ok"), ToolUseBlock("1", "mcp__reelsmith__render",
                                                                                    {"project": str(project)})],
                                               model="claude-opus-5-5"), deliver, result(0.8, 12)], calls=calls)
    rep = go(project, q, brief="一吨汽油值多少钱")
    assert rep["delivered"] and rep["cost_usd"] == 0.8 and rep["turns"] == 12 and rep["stop"] == "finished"
    assert "一吨汽油值多少钱" in calls[0]["prompt"] and calls[0]["options"].resume is None
    saved = json.loads((project / "out" / "run_report.json").read_text(encoding="utf-8"))
    assert saved["delivered"] and saved["sessions"][0]["session_id"] == "s1"
    state = json.loads((project / "build" / "run_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"


def test_new_run_needs_a_brief(ws):
    _, project = ws
    with pytest.raises(runner.WorkspaceError, match="brief"):
        go(project, fake_query())


def test_fixup_then_delivered(ws, no_checks):
    _, project = ws
    calls = []
    q = fake_query([init(), result(0.5, 5)], [deliver, result(0.2, 2)], calls=calls)
    rep = go(project, q, brief="b")
    assert rep["delivered"] and rep["cost_usd"] == 0.7 and len(rep["sessions"]) == 2
    assert calls[1]["options"].resume == "s1" and "out/film.mp4 does not exist" in calls[1]["prompt"]
    assert calls[1]["options"].max_budget_usd == 2.5


def test_fixups_are_capped(ws, no_checks):
    _, project = ws
    q = fake_query([init(), result(0.1)], [result(0.1)], [result(0.1)], [result(0.1)])
    rep = go(project, q, brief="b")
    assert not rep["delivered"] and len(rep["sessions"]) == 3


def test_budget_stops_fixups(ws, no_checks):
    _, project = ws
    q = fake_query([init(), result(2.99)])
    rep = go(project, q, brief="b")
    assert not rep["delivered"] and any("budget" in p for p in rep["problems"])


def test_crash_resumes_in_process(ws, no_checks):
    _, project = ws
    calls = []
    q = fake_query([init("s9"), AssistantMessage(content=[TextBlock("hi")], model="claude-opus-5-5",
                                                  usage={"input_tokens": 1000, "output_tokens": 100},
                                                  message_id="m1"),
                    RuntimeError("connection lost")],
                   [deliver, result(0.3, 4, sid="s9")], calls=calls)
    rep = go(project, q, brief="b")
    assert rep["delivered"] and calls[1]["options"].resume == "s9"
    assert "Resuming" in calls[1]["prompt"] and "connection lost" in calls[1]["prompt"]
    first = rep["sessions"][0]
    assert first["cost_estimated"] and first["cost_usd"] > 0     # no ResultMessage: estimated, still counted
    assert rep["cost_usd"] == pytest.approx(first["cost_usd"] + 0.3)


def test_killed_process_resumes_next_time(ws, no_checks):
    _, project = ws
    (project / "build").mkdir()
    (project / "build" / "run_state.json").write_text(json.dumps(
        {"status": "running", "session_id": "s7", "cost_usd": 0.4, "brief": "b",
         "last_stop": "the process was interrupted"}), encoding="utf-8")
    calls = []
    rep = go(project, fake_query([deliver, result(0.3, 4, sid="s7")], calls=calls))   # no brief: it resumes
    assert rep["delivered"] and calls[0]["options"].resume == "s7" and "interrupted" in calls[0]["prompt"]
    assert rep["cost_usd"] == pytest.approx(0.7)


def test_fresh_ignores_old_state(ws, no_checks):
    _, project = ws
    go(project, fake_query([init("old"), result(0.1)], [result(0.1)], [result(0.1)]), brief="b")
    calls = []
    go(project, fake_query([init("new"), deliver, result(0.1, sid="new")], calls=calls), brief="b2", fresh=True)
    assert calls[0]["options"].resume is None and "b2" in calls[0]["prompt"]


def test_spent_budget_refuses_to_start(ws, no_checks):
    _, project = ws
    (project / "build").mkdir()
    (project / "build" / "run_state.json").write_text(json.dumps({"status": "stopped", "session_id": "s1",
                                                                   "cost_usd": 3.0}), encoding="utf-8")
    calls = []
    rep = go(project, fake_query(calls=calls))
    assert not rep["delivered"] and not calls and any("already spent" in p for p in rep["problems"])


def _age(path: Path, seconds: float) -> None:
    t = path.stat().st_mtime - seconds
    os.utime(path, (t, t))


def test_stale_film_is_not_delivered(ws, no_checks):
    _, project = ws
    deliver(project)
    _age(project / "out" / "film.mp4", 100)
    ok, problems, _ = runner.delivery(project)
    assert not ok and "project.json changed after the last render" in problems[0]


def test_a_changed_asset_or_component_makes_the_film_stale(ws, no_checks):
    w, project = ws
    deliver(project)
    for p in (project / "project.json", project / "out" / "film.mp4"):
        _age(p, 100)
    (project / "assets" / "pic.png").write_bytes(b"png")
    ok, problems, _ = runner.delivery(project)
    assert not ok and "assets/pic.png changed" in problems[0]
    _age(project / "assets" / "pic.png", 200)
    (w.components_dir / "Tag.tsx").write_text("export default () => null;", encoding="utf-8")
    ok, problems, _ = runner.delivery(project)
    assert not ok and "Tag.tsx changed" in problems[0]


def _rendered(project: Path, components=None) -> None:
    """A delivered film whose report records the inputs the way render() does."""
    from reelsmith.render import film_inputs
    deliver(project)
    inputs = film_inputs(project)
    if components is not None:
        inputs["components"] = components
    (project / "out" / "report.json").write_text(json.dumps({"ok": True, "inputs": inputs}), encoding="utf-8")
    for p in (project / "project.json", project / "out" / "film.mp4", project / "out" / "report.json"):
        _age(p, 100)


def test_a_meta_only_edit_keeps_the_film_delivered(ws, no_checks):
    _, project = ws
    _rendered(project)
    doc = json.loads((project / "project.json").read_text(encoding="utf-8"))
    doc["meta"] = {"title": "a better title", "sources": [{"title": "s", "url": "https://example.org/a"}]}
    (project / "project.json").write_text(json.dumps(doc), encoding="utf-8")
    assert runner.delivery(project)[0]
    doc["tracks"] = [{"id": "v1", "kind": "visual", "clips": []}]
    (project / "project.json").write_text(json.dumps(doc), encoding="utf-8")
    ok, problems, _ = runner.delivery(project)
    assert not ok and "project.json changed" in problems[0]


def test_only_components_the_film_uses_make_it_stale(ws, no_checks):
    w, project = ws
    _rendered(project, components=["Used"])
    lib = w.components_dir
    (lib / "Other.meta.json").write_text("{}", encoding="utf-8")
    (lib / "Other.tsx").write_text("export default () => null;", encoding="utf-8")
    assert runner.delivery(project)[0]
    (lib / "helpers.ts").write_text("export const x = 1;", encoding="utf-8")     # no meta: any component may import it
    ok, problems, _ = runner.delivery(project)
    assert not ok and "helpers.ts changed" in problems[0]
    _age(lib / "helpers.ts", 200)
    (lib / "Used.meta.json").write_text("{}", encoding="utf-8")
    (lib / "Used.tsx").write_text("export default () => null;", encoding="utf-8")
    ok, problems, _ = runner.delivery(project)
    assert not ok and "Used." in problems[0]


def test_a_failed_rerender_is_not_delivered(ws, no_checks):
    # render writes failures to build/report.json and keeps the previous good film and out/report.json
    _, project = ws
    deliver(project)
    _age(project / "out" / "report.json", 50)
    (project / "build").mkdir(exist_ok=True)
    (project / "build" / "report.json").write_text(json.dumps({"ok": False, "stage": "layout",
                                                                 "error": "hook @ 1.0s outside"}), encoding="utf-8")
    ok, problems, _ = runner.delivery(project)
    assert not ok and "latest render failed at layout" in problems[0] and "older film" in problems[0]


def test_stall_aborts(ws, no_checks):
    _, project = ws

    async def stuck(prompt, options):
        yield init()
        await asyncio.sleep(30)

    log = runner.SessionLog(project, io.StringIO())
    out = asyncio.run(runner.run_session(None, "p", log, query_fn=stuck, stall_s=0.2, wall_s=60))
    log.close()
    assert out["aborted"] and out["session_id"] == "s1"


def test_denials_reach_the_report(ws, no_checks):
    w, project = ws
    hook = guard.make_hook(guard.scope_for(project, w), runner.SessionLog(project, io.StringIO()).denied)
    res = asyncio.run(hook({"tool_name": "Bash", "tool_input": {"command": "dir"}}, "t", None))
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"


# ------------------------------------------------------------------ the guard, as a table
@pytest.mark.parametrize("tool,inp,allowed", [
    ("Read", {"file_path": "project.json"}, True),
    ("Read", {"file_path": "../../library/NOTES.md"}, True),
    ("Read", {"file_path": "../../.env"}, False),
    ("Read", {"file_path": "../../ledger.jsonl"}, False),
    ("Read", {"file_path": "C:/Windows/win.ini"}, False),
    ("Read", {"file_path": "project.json::$DATA"}, False),
    ("Read", {"file_path": "NUL"}, False),
    ("Read", {"file_path": "script.md."}, False),
    ("Read", {"file_path": "//server/share/x"}, False),
    ("Write", {"file_path": "script.md"}, True),
    ("Write", {"file_path": "../../library/components/Tag.tsx"}, True),
    ("Write", {"file_path": ".history/0001.json"}, False),
    ("Write", {"file_path": "out/film.mp4"}, False),
    ("Write", {"file_path": "../../workspace.json"}, False),
    ("Write", {"file_path": "run.py"}, False),
    ("Write", {"file_path": "../other/x.md"}, False),
    ("Edit", {"file_path": "project.json"}, True),
    ("Glob", {"pattern": "assets/*.png"}, True),
    ("Glob", {"pattern": "**/.env*"}, False),
    ("Grep", {"pattern": "x", "path": "../.."}, False),
    ("Grep", {"pattern": "x", "path": "."}, True),
    ("Bash", {"command": "ls"}, False),
    ("WebFetch", {"url": "https://example.com/a"}, True),
    ("WebFetch", {"url": "http://127.0.0.1:8080/"}, False),
    ("WebFetch", {"url": "file:///C:/x"}, False),
    ("WebSearch", {"query": "油价"}, True),
    ("mcp__reelsmith__render", {"project": "."}, True),
    ("mcp__reelsmith__render", {"project": "../other"}, False),
    ("mcp__reelsmith__import_asset", {"project": ".", "id": "a", "source": "C:/Users/x/secret.png"}, False),
    ("mcp__reelsmith__capture", {"project": ".", "id": "a", "url": "http://localhost/"}, False),
    ("mcp__other__x", {}, False),
    ("AskUserQuestion", {}, False),
    # a workspace.json or rules.json in the project would become the nearest workspace and replace the owner's
    ("Write", {"file_path": "workspace.json"}, False),
    ("Write", {"file_path": "rules.json"}, False),
    ("Write", {"file_path": "assets/sub/WORKSPACE.JSON"}, False),
    ("Write", {"file_path": "../../library/components/rules.json"}, False),
    ("Write", {"file_path": ".env.local"}, False),
    ("Write", {"file_path": "ledger.jsonl"}, False),
    ("Read", {"file_path": "../../.cache/draw.log"}, False),
    ("Grep", {"pattern": "x", "path": "../../.cache"}, False),
])
def test_guard_table(ws, tool, inp, allowed):
    w, project = ws
    (w.root / ".cache").mkdir(exist_ok=True)
    (w.root / ".cache" / "draw.log").write_text("codex said", encoding="utf-8")
    ok, why = guard.decide(tool, inp, guard.scope_for(project, w))
    assert ok == allowed, why


def test_resolve_token_reads_posix_paths_as_they_are(monkeypatch):
    import posixpath
    import types
    from pathlib import PurePosixPath
    monkeypatch.setattr(guard, "os", types.SimpleNamespace(name="posix", path=posixpath, sep="/"))
    monkeypatch.setattr(guard, "Path", PurePosixPath)
    monkeypatch.setenv("HOME", "/home/u")
    cwd = "/home/u/ws/projects/p1"
    assert guard.resolve_token("/home/u/ws/projects/p1/script.md", cwd) == PurePosixPath(cwd, "script.md")
    assert guard.resolve_token("assets/../script.md", cwd) == PurePosixPath(cwd, "script.md")
    assert guard.resolve_token("/c/work/x.md", cwd) == PurePosixPath("/c/work/x.md")      # a folder, not a drive
    assert guard.resolve_token("~/ws/library", cwd) == PurePosixPath("/home/u/ws/library")
    for never in ("C:/x", "C:x", "\\\\server\\share", "~other/x"):
        assert guard.resolve_token(never, cwd) is None, never


@pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows paths")
def test_resolve_token_reads_msys_paths_as_drives(tmp_path):
    assert guard.resolve_token("/c/work/x.md", tmp_path) == Path("C:/work/x.md")
    assert guard.resolve_token("/work/x.md", tmp_path) is None and guard.resolve_token("//srv/share", tmp_path) is None


def test_grep_over_the_workspace_skips_the_cache(ws):
    w, project = ws
    (w.root / ".cache").mkdir(exist_ok=True)
    ok, why = guard.decide("Grep", {"pattern": "x", "path": "../.."}, guard.scope_for(project, w))
    assert not ok and ".cache" in why
