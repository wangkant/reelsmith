"""The runner's codex and dsh engines, driven against a fake CLI that plays recorded event streams."""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from reelsmith import backends, cli_engines, guard, mcp_server, runner
from reelsmith.workspace import Workspace

try:
    import tomllib
except ImportError:                 # Python 3.10
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
FAKE = Path(__file__).parent / "fixtures" / "fake_agent_cli.py"
MOCK_LLM = Path(__file__).parent / "fixtures" / "dsh_mock_llm.mjs"
DSH_MODULES = ROOT / "integrations" / "dsh" / "node_modules" / "@deepseek-ai"
DS_KEY = "sk-ds-test-abcdef123456"
needs_toml = pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "REELSMITH_PROXY", "DSH_EXE", "CODEX_EXE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli_engines, "codex_user_model", lambda env=None: "")
    root = tmp_path / "ws"
    (root / "library" / "components").mkdir(parents=True)
    (root / "library" / "NOTES.md").write_text("# notes\n", encoding="utf-8")
    project = root / "projects" / "p1"
    (project / "assets").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"version": 2, "meta": {"title": "t"}, "tracks": []}),
                                          encoding="utf-8")
    return configure(root, {}), project


def configure(root: Path, runner_cfg: dict, env: str = f"DEEPSEEK_API_KEY={DS_KEY}\n") -> Workspace:
    (root / "workspace.json").write_text(json.dumps({"profile": "douyin", "runner": {"budget_usd": 3, **runner_cfg}}),
                                         encoding="utf-8")
    (root / ".env").write_text(env, encoding="utf-8")
    return Workspace.load(root)


@pytest.fixture
def no_checks(monkeypatch):
    monkeypatch.setattr("reelsmith.checks.check_project", lambda project: [])


def fake(monkeypatch, tmp_path, *runs, engine="codex", env_keys=()):
    """Point the engine at the fake CLI playing `runs`; returns a function that reads the recorded calls."""
    script = tmp_path / "fake.json"
    script.write_text(json.dumps({"runs": list(runs), "env_keys": list(env_keys)}), encoding="utf-8")
    monkeypatch.setenv("FAKE_CLI_SCRIPT", str(script))
    cmd = [sys.executable, str(FAKE)]
    if engine == "codex":
        monkeypatch.setattr(cli_engines, "find_codex", lambda: cmd)
    else:
        monkeypatch.setattr(cli_engines, "find_dsh", lambda env=None: cmd)
    calls = tmp_path / "fake.calls.jsonl"
    return lambda: [json.loads(ln) for ln in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []


def go(project, **kw):
    out = io.StringIO()
    report = runner.run(project, out=out, **kw)
    return report, out.getvalue()


def codex_turn(sid="th-1", usage=None, text="done", deliver=True):
    usage = usage or {"input_tokens": 12000, "cached_input_tokens": 2000, "output_tokens": 800,
                      "reasoning_output_tokens": 300}
    return {"events": [
        {"type": "thread.started", "thread_id": sid}, {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "i1", "type": "mcp_tool_call", "server": "reelsmith",
                                          "tool": "render", "arguments": {"project": "p"}, "status": "in_progress"}},
        *(["deliver"] if deliver else []),
        {"type": "item.completed", "item": {"id": "i1", "type": "mcp_tool_call", "server": "reelsmith",
                                            "tool": "render", "arguments": {}, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "i2", "type": "command_execution", "command": "ls",
                                            "aggregated_output": "", "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": usage}]}


def dsh_steps(sid="session-1", steps=2, usage=None, deliver=True, reason=None, tail=()):
    """A `dsh --profile headless --json` stream in the 0.2.1-rc.3 shapes (RC3_DONE): the turn's outcome is on the
    turn_end status, final carries only the answer, and the exit status is 0 only for a completed turn."""
    usage = usage or {"inputTokens": 1000, "outputTokens": 500, "cacheReadTokens": 4000}
    reason = reason or {"kind": "completed"}
    events = [{"type": "session", "sessionId": sid, "cwd": "x"}, {"type": "status", "phase": "turn_start", "turn": 1}]
    for i in range(steps):
        events += [{"type": "status", "phase": "step_start", "turn": 1, "step": i + 1},
                   {"type": "tool_call", "callId": f"c{i}", "tool": "mcp__reelsmith__check", "input": {"project": "p"}},
                   {"type": "tool_result", "callId": f"c{i}", "status": "completed", "result": "ok"},
                   {"type": "status", "phase": "step_end", "turn": 1, "step": i + 1, "usage": usage}]
    events += list(tail)
    if deliver:
        events.append("deliver")
    done = reason["kind"] == "completed"
    events += [*([{"type": "text", "text": "film rendered"}] if done else []),
               {"type": "status", "phase": "turn_end", "turn": 1, "reason": reason},
               {"type": "final", "text": "film rendered" if done else ""}]
    return {"events": events, "exit": 0 if done else 1}


# captured from dsh 0.2.1-rc.3 (`--profile headless --json`) against DSH's mock model, paths shortened
RC3_DONE = [
    {"type": "session", "sessionId": "session-058a9a98-0c78-4076-b85d-d60fa4145306", "cwd": "C:\\ws\\projects\\p1"},
    {"type": "status", "phase": "turn_start", "turn": 1},
    {"type": "status", "phase": "step_start", "turn": 1, "step": 1},
    {"type": "text", "text": "film rendered"},
    {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
     "usage": {"inputTokens": 3, "outputTokens": 13, "totalTokens": 16}},
    {"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}},
    {"type": "final", "text": "film rendered"}]
RC3_FAILED = [
    {"type": "session", "sessionId": "session-e9cadbc4-de4a-442b-899c-4ccd433fc9d9", "cwd": "C:\\ws\\projects\\p1"},
    {"type": "status", "phase": "turn_start", "turn": 1},
    {"type": "status", "phase": "step_start", "turn": 1, "step": 1},
    {"type": "tool_call", "callId": "mock-call-1", "tool": "mcp__reelsmith__describe", "input": {"project": "."}},
    {"type": "tool_result", "callId": "mock-call-1", "status": "completed", "result": "project p1: landscape ..."},
    {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
     "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5}},
    {"type": "status", "phase": "step_start", "turn": 1, "step": 2},
    {"type": "status", "phase": "step_end", "turn": 1, "step": 2},
    {"type": "status", "phase": "turn_end", "turn": 1,
     "reason": {"kind": "error", "error": {"message": "mock script exhausted", "code": "SERVER", "status": 500}}},
    {"type": "final", "text": ""}]


class Log:
    def __init__(self):
        self.lines = []

    def event(self, kind, **data):
        pass

    def line(self, text):
        self.lines.append(text)


# ------------------------------------------------------------------ settings
def test_codex_and_dsh_settings(ws, monkeypatch):
    w, _ = ws
    s = runner.settings_for(w, engine="codex")
    assert (s.engine, s.model, s.effort, s.provider, s.api) == ("codex", "", "medium", None, None)
    monkeypatch.setattr(cli_engines, "codex_user_model", lambda env=None: "gpt-5.5-codex")
    assert runner.settings_for(w, engine="codex").model == "gpt-5.5-codex"    # the owner's Codex model
    assert runner.settings_for(w, engine="codex", model="o9", effort="high").model == "o9"
    s = runner.settings_for(w, engine="dsh")
    assert (s.engine, s.model, s.effort) == ("dsh", "deepseek-flash", None)    # DSH keeps its own default effort
    assert runner.settings_for(w, engine="dsh", effort="max").effort == "max"
    w2 = configure(w.root, {"engine": "dsh", "model": "deepseek-v4-pro", "effort": "low",
                            "prices": {"deepseek-v4-pro": [2, 4, 0.1]}})
    s = runner.settings_for(w2)
    assert (s.engine, s.model, s.effort) == ("dsh", "deepseek-v4-pro", "low")
    assert s.prices["deepseek-v4-pro"] == backends.Price(miss=2, hit=0.1, write=2, out=4)
    assert runner.settings_for(w2, engine="codex").model == "gpt-5.5-codex"  # the workspace model went with dsh
    for bad in ({"engine": "codex", "backend": "deepseek"}, {"engine": "dsh", "provider": "openrouter"}):
        with pytest.raises(runner.WorkspaceError, match="not for the"):
            runner.settings_for(w, **bad)
    with pytest.raises(runner.WorkspaceError, match="effort of"):
        runner.settings_for(w, engine="dsh", effort="medium")
    with pytest.raises(runner.WorkspaceError, match="api engine takes"):
        runner.settings_for(w, effort="high")
    assert runner.settings_for(w, engine="agent-sdk", effort="high").effort == "high"


def test_effort_and_engine_flags_reach_the_run(ws, monkeypatch):
    _, project = ws
    seen = {}
    monkeypatch.setattr(runner, "run", lambda *a, **k: seen.update(k) or {"delivered": True})
    assert runner.main([str(project), "--brief", "b", "--engine", "dsh", "--effort", "max"]) == 0
    assert (seen["engine"], seen["effort"]) == ("dsh", "max")


# ------------------------------------------------------------------ commands
@needs_toml
def test_codex_command(ws):
    w, project = ws
    scope = guard.scope_for(project, w)
    srv = cli_engines.server(scope)
    cmd = cli_engines.codex_command(["codex"], project, scope, srv, "gpt-x", "high", 1800)
    assert cmd[:3] == ["codex", "exec", "--json"] and cmd[-1] == "-"
    assert {"--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"} <= set(cmd)
    assert cmd[cmd.index("-C") + 1] == str(project) and cmd[cmd.index("-m") + 1] == "gpt-x"
    sets = dict(cmd[i + 1].split("=", 1) for i, a in enumerate(cmd) if a == "-c")
    values = {k: tomllib.loads(f"v = {v}")["v"] for k, v in sets.items()}       # every override is TOML
    assert values["sandbox_mode"] == "workspace-write" and values["approval_policy"] == "never"
    assert values["sandbox_workspace_write.network_access"] is False
    assert values["sandbox_workspace_write.writable_roots"] == [str(w.root / "library")]
    assert values["shell_environment_policy.inherit"] == "core" and values["model_reasoning_effort"] == "high"
    assert values["mcp_servers.reelsmith.command"] == srv["command"]
    assert values["mcp_servers.reelsmith.args"] == ["-m", "reelsmith.mcp_server"]
    assert values["mcp_servers.reelsmith.env"]["REELSMITH_GUARD_PROJECT"] == str(project)
    assert values["mcp_servers.reelsmith.env"]["REELSMITH_ROOT"] == str(w.root)
    assert values["mcp_servers.reelsmith.tool_timeout_sec"] == 1800 and "features.shell_tool" not in values
    resumed = cli_engines.codex_command(["codex"], project, scope, srv, "", None, 1800, resume="th-9")
    assert resumed[:4] == ["codex", "exec", "resume", "--json"] and resumed[-2:] == ["th-9", "-"]
    assert "-C" not in resumed and "-m" not in resumed and not any("model_reasoning" in a for a in resumed)


def test_dsh_command_and_patch(ws):
    w, project = ws
    scope = guard.scope_for(project, w)
    srv = cli_engines.server(scope)
    patch = project / "build" / "p.yml"
    # dsh 0.2.1-rc.3 headless takes --json, --session-id and the task; any other flag stops it before it starts
    assert cli_engines.dsh_command(["dsh"], patch) == ["dsh", "--patch", str(patch), "--profile", "headless",
                                                      "--json", "-"]
    resumed = cli_engines.dsh_command(["dsh"], patch, resume="session-7")
    assert resumed[-3:] == ["--session-id", "session-7", "-"]
    text = cli_engines.dsh_patch(srv, "deepseek-v4-pro", "max", 600)
    assert "name: '@deepseek-ai/dsh-mcp-client'" in text and "toolCallTimeoutMs: 600000" in text
    assert 'model: "deepseek-v4-pro"' in text and 'reasoningEffort: "max"' in text
    assert "- id: sandbox-policy\n  config:\n    mode: workspace-write\n" in text
    assert "- id: approval\n  config:\n    policy: never\n" in text
    assert ("- id: permission\n  config:\n    presets:\n      reelsmith-run:\n        sandbox: workspace-write\n"
            "        approval: never\n    defaultPreset: reelsmith-run\n") in text
    assert "- id: session-log-deepseek\n  disabled: true" in text and "- id: session-title-llm\n  disabled: true" in text
    assert json.dumps(str(project), ensure_ascii=False) in text    # REELSMITH_GUARD_PROJECT, as a JSON scalar
    assert "reasoningEffort" not in cli_engines.dsh_patch(srv, "deepseek-flash")
    env = cli_engines.dsh_env("k", w.root / ".cache" / "dsh", "http://127.0.0.1:7890", base={"PATH": "x"})
    assert env["DEEPSEEK_API_KEY"] == "k" and env["DSH_HOME"].endswith("dsh") and env["HTTPS_PROXY"]
    assert env["DSH_TELEMETRY_MODE"] == "DISABLED" and env["DSH_TELEMETRY_DISABLED"] == "1"


def test_find_dsh(tmp_path, monkeypatch):
    exe = tmp_path / "dsh.cmd"
    exe.write_text("", encoding="utf-8")
    assert cli_engines.find_dsh({"DSH_EXE": str(exe)}) == [str(exe)]
    assert cli_engines.find_dsh({"DSH_EXE": str(tmp_path / "missing")}) is None
    monkeypatch.setattr(cli_engines.shutil, "which", lambda name: {"npx": "/bin/npx"}.get(name))
    assert cli_engines.find_dsh({}) == ["/bin/npx", "-y", "@deepseek-ai/dsh@0.2.1-rc.3"]    # the tested dsh
    monkeypatch.setattr(cli_engines.shutil, "which", lambda name: "/bin/" + name)
    assert cli_engines.find_dsh({}) == ["/bin/dsh"]


@needs_toml
def test_codex_user_model(tmp_path):
    (tmp_path / "config.toml").write_text('model = "gpt-5.5-codex"\n[other]\nx = 1\n', encoding="utf-8")
    assert cli_engines.codex_user_model({"CODEX_HOME": str(tmp_path)}) == "gpt-5.5-codex"
    assert cli_engines.codex_user_model({"CODEX_HOME": str(tmp_path / "none")}) == ""


# ------------------------------------------------------------------ codex runs
def test_codex_run_delivers(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    calls = fake(monkeypatch, tmp_path, codex_turn())
    report, out = go(project, brief="A film about tea", engine="codex", model="gpt-x")
    assert report["delivered"] and report["engine"] == "codex" and report["backend"] is None
    assert report["cost_known"] is False and report["cost_usd"] == 0
    assert report["usage"]["input_tokens"] == 12000 and report["usage"]["output_tokens"] == 800
    session = report["sessions"][0]
    assert session["session_id"] == "th-1" and session["subtype"] == "success" and session["tool_calls"] == 2
    (call,) = calls()
    assert Path(call["cwd"]) == project and call["argv"][:2] == ["exec", "--json"]
    assert "A film about tea" in call["prompt"] and "manual" in call["prompt"] and "Nobody will answer" in call["prompt"]
    assert "-> render" in out and "say done" in out and "no price" in out
    state = json.loads((project / "build" / "run_state.json").read_text(encoding="utf-8"))
    assert (state["engine"], state["model"], state["status"], state["inflight"]) == ("codex", "gpt-x", "done", None)
    assert "runner.jsonl" in {p.name for p in (project / "build").iterdir()}


def test_codex_fixup_resumes_the_thread(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    calls = fake(monkeypatch, tmp_path, codex_turn(deliver=False), codex_turn())
    report, _ = go(project, brief="b", engine="codex")
    assert report["delivered"] and [s["kind"] for s in report["sessions"]] == ["new", "fixup"]
    first, second = calls()
    assert "-m" not in first["argv"]                       # no model: Codex's own default
    assert second["argv"][:3] == ["exec", "resume", "--json"] and second["argv"][-2:] == ["th-1", "-"]
    assert second["prompt"].startswith("(runner) The film is not delivered yet")


def test_codex_priced_from_the_workspace(ws, tmp_path, monkeypatch, no_checks):
    w, project = ws
    configure(w.root, {"engine": "codex", "model": "gpt-x", "prices": {"gpt-x": [1.0, 10.0, 0.1]}})
    fake(monkeypatch, tmp_path, codex_turn())
    report, _ = go(project, brief="b")
    # (12000 - 2000) x $1 + 2000 x $0.1 + 800 x $10 per million
    assert report["cost_known"] is True and report["cost_usd"] == pytest.approx(0.0182)


def test_codex_failed_turn(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    fake(monkeypatch, tmp_path, {"events": [{"type": "thread.started", "thread_id": "th-2"},
                                            {"type": "turn.failed", "error": {"message": "401 Unauthorized"}}],
                                 "exit": 1})
    report, out = go(project, brief="b", engine="codex", max_minutes=5)
    assert not report["delivered"] and report["sessions"][0]["error"] == "401 Unauthorized"
    assert "401 Unauthorized" in out


def test_codex_missing_is_a_setup_problem(ws, monkeypatch):
    _, project = ws
    monkeypatch.setattr(cli_engines, "find_codex", lambda: None)
    with pytest.raises(runner.WorkspaceError, match="Codex CLI is not installed"):
        go(project, brief="b", engine="codex")


def test_codex_stall_kills_the_session(ws, tmp_path, monkeypatch, no_checks):
    w, project = ws
    configure(w.root, {"engine": "codex", "stall_minutes": 0.02, "fixups": 0})
    fake(monkeypatch, tmp_path, {"events": [{"type": "thread.started", "thread_id": "th-3"}, {"sleep": 20}]})
    report, _ = go(project, brief="b")
    assert not report["delivered"] and report["sessions"][0]["aborted"].startswith("no event for")


def test_a_cli_run_resumes_only_on_its_model(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    fake(monkeypatch, tmp_path, codex_turn(deliver=False))
    go(project, brief="b", engine="codex", model="gpt-x", max_minutes=5)
    with pytest.raises(runner.WorkspaceError, match="on codex gpt-x"):
        go(project, engine="codex", model="gpt-y")
    with pytest.raises(runner.WorkspaceError, match="on the codex engine"):
        go(project, engine="dsh")


# ------------------------------------------------------------------ dsh runs
def test_dsh_run_delivers(ws, tmp_path, monkeypatch, no_checks):
    w, project = ws
    calls = fake(monkeypatch, tmp_path, dsh_steps(), engine="dsh", env_keys=["DEEPSEEK_API_KEY", "DSH_HOME"])
    report, out = go(project, brief="b", engine="dsh")
    assert report["delivered"] and report["engine"] == "dsh" and report["model"] == "deepseek-flash"
    flash = backends.BACKENDS["deepseek"].prices["deepseek-flash"]
    want = 2 * (1000 * flash.miss + 4000 * flash.hit + 500 * flash.out) / 1e6
    assert report["cost_known"] and report["cost_usd"] == pytest.approx(want, abs=1e-4)
    assert report["sessions"][0]["turns"] == 2 and report["usage"]["inputTokens"] == 2000
    assert report["sessions"][0]["subtype"] == "success" and report["sessions"][0]["error"] is None
    (call,) = calls()
    assert call["env"]["DEEPSEEK_API_KEY"] == DS_KEY
    assert Path(call["env"]["DSH_HOME"]) == w.root / ".cache" / "dsh"
    assert call["argv"][call["argv"].index("--patch") + 1] == str(project / "build" / "dsh-patch.yml")
    assert 'model: "deepseek-flash"' in (project / "build" / "dsh-patch.yml").read_text(encoding="utf-8")
    assert "-> mcp__reelsmith__check" in out and DS_KEY not in out


def test_dsh_needs_the_deepseek_key(ws, monkeypatch):
    w, project = ws
    configure(w.root, {}, env="")
    with pytest.raises(runner.WorkspaceError, match="DEEPSEEK_API_KEY"):
        go(project, brief="b", engine="dsh")


def test_dsh_stops_at_the_budget(ws, tmp_path, monkeypatch, no_checks):
    w, project = ws
    configure(w.root, {"engine": "dsh", "budget_usd": 0.5, "fixups": 0})
    big = {"inputTokens": 1_000_000, "outputTokens": 200_000}
    fake(monkeypatch, tmp_path, dsh_steps(steps=1, usage=big, deliver=False, tail=[{"sleep": 20}]), engine="dsh")
    report, _ = go(project, brief="b")
    assert not report["delivered"] and "budget" in report["sessions"][0]["aborted"]
    assert report["cost_usd"] >= 0.5


def test_dsh_stops_at_max_turns(ws, tmp_path, monkeypatch, no_checks):
    w, project = ws
    configure(w.root, {"engine": "dsh", "fixups": 0})
    fake(monkeypatch, tmp_path, dsh_steps(steps=3, deliver=False, tail=[{"sleep": 20}]), engine="dsh")
    report, _ = go(project, brief="b", max_turns=2)
    assert report["sessions"][0]["aborted"] == "max_turns (2) reached" and report["sessions"][0]["turns"] == 2


def test_dsh_error_turn_then_resume(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    failed = dsh_steps(steps=1, deliver=False,
                       reason={"kind": "error", "error": {"message": "rate limited", "code": "RATE_LIMIT", "status": 429}})
    calls = fake(monkeypatch, tmp_path, failed, dsh_steps(), engine="dsh")
    report, _ = go(project, brief="b", engine="dsh")
    assert report["delivered"] and report["sessions"][0]["error"] == "rate limited"
    assert report["sessions"][1]["kind"] == "resume"
    assert calls()[1]["argv"][-3:] == ["--session-id", "session-1", "-"]


def test_dsh_stream_reads_the_real_event_shapes():
    def fold(events):
        stream = cli_engines.DshStream(Log())
        for ev in events:
            stream.feed(ev)
        return stream.outcome
    done = fold(RC3_DONE)
    assert done["done"] and done["error"] is None and done["result"] == "film rendered" and done["turns"] == 1
    assert done["session_id"] == "session-058a9a98-0c78-4076-b85d-d60fa4145306" and done["usage"]["inputTokens"] == 3
    failed = fold(RC3_FAILED)
    assert not failed["done"] and failed["error"] == "mock script exhausted" and failed["tool_calls"] == 1
    # the last turn decides: a later completed turn clears an earlier turn's failure, an open one does not finish
    again = fold(RC3_FAILED[:-1] + [{"type": "status", "phase": "turn_start", "turn": 2}, *RC3_DONE[2:]])
    assert again["done"] and again["error"] is None
    assert not fold(RC3_DONE[:-2] + [{"type": "status", "phase": "turn_start", "turn": 2}])["done"]
    aborted = fold(RC3_DONE[:5] + [{"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "aborted"}}])
    assert not aborted["done"] and aborted["error"] == "the turn ended: aborted"


def test_dsh_version_reaches_the_run_log(ws, tmp_path, monkeypatch, no_checks):
    _, project = ws
    fake(monkeypatch, tmp_path, dsh_steps(), engine="dsh")
    assert cli_engines.dsh_version([sys.executable, str(FAKE)]) == "0.2.1-rc.3"
    assert cli_engines.dsh_version([str(tmp_path / "missing")]) == ""
    _, out = go(project, brief="b", engine="dsh")
    assert f"dsh 0.2.1-rc.3: {sys.executable}" in out and "tested with" not in out
    monkeypatch.setenv("FAKE_CLI_VERSION", "0.3.0")
    _, out = go(project, brief="b", engine="dsh", fresh=True)
    assert "dsh 0.3.0: " in out and "(tested with 0.2.1-rc.3)" in out


@pytest.mark.skipif(not (shutil.which("node") and (DSH_MODULES / "dsh" / "lib" / "bin.js").is_file()
                         and (DSH_MODULES / "dsh-llm-mock-server").is_dir()),
                    reason="needs Node.js and `npm ci` in integrations/dsh")
def test_the_real_dsh_runs_the_runner_command(ws):
    """dsh 0.2.1-rc.3 boots the runner's command and overlay against DSH's scripted mock model (no key, no network)
    and calls a reelsmith tool through the server the overlay mounts."""
    w, project = ws
    node = shutil.which("node")
    exe = [node, str(DSH_MODULES / "dsh" / "lib" / "bin.js")]
    assert cli_engines.dsh_version(exe) == cli_engines.DSH_VERSION
    srv = cli_engines.server(guard.scope_for(project, w))
    srv["env"]["PYTHONPATH"] = str(ROOT)                        # the server of this checkout
    patch = project / "build" / "dsh-patch.yml"
    patch.parent.mkdir(exist_ok=True)
    patch.write_text(cli_engines.dsh_patch(srv, "deepseek-flash"), encoding="utf-8")
    script = {"sequence": ["tool_call_success", "success"], "toolName": "mcp__reelsmith__describe",
              "toolArguments": json.dumps({"project": "."}), "successText": "film rendered"}
    mock = subprocess.Popen([node, str(MOCK_LLM), str(DSH_MODULES / "dsh-llm-mock-server"), json.dumps(script)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        base_url = json.loads(mock.stdout.readline())["baseURL"]
        base = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper()}
        env = cli_engines.dsh_env("mock-key", w.root / ".cache" / "dsh", base=base)
        # the overlay's preset must win over the owner's DSH_PERMISSION_MODE
        env.update(DEEPSEEK_BASE_URL=base_url, DSH_PERMISSION_MODE="danger-full-access")
        log = Log()
        out = cli_engines.drive(cli_engines.dsh_command(exe, patch), project, env, "Describe the project.",
                                cli_engines.DshStream(log), stall_s=240, wall_s=300)
    finally:
        mock.stdin.close()
        line = mock.stdout.readline()
        mock.wait(30)
    requests = json.loads(line)["requests"]
    assert out["exit_code"] == 0 and out["done"] and out["error"] is None, (out, log.lines)
    assert out["session_id"].startswith("session-") and out["result"] == "film rendered" and out["tool_calls"] == 1
    assert cli_engines.summary(out)["subtype"] == "success"
    assert len(requests) == 2                                   # the agent's two steps; no session-title call
    first, second = requests
    assert "mcp__reelsmith__describe" in first["tools"]
    assert "file policy: workspace-write" in first["messages"] and "Approval prompts are disabled" in first["messages"]
    assert '"is_error":false' in second["messages"] and "project p1" in second["messages"]


# ------------------------------------------------------------------ the MCP server's guard
def test_mcp_guard_holds_calls_to_the_project(ws, monkeypatch):
    w, project = ws
    monkeypatch.setenv(mcp_server.GUARD_ENV, str(project))
    scope = mcp_server.guard_scope()
    assert scope.project == project and scope.workspace == w.root
    monkeypatch.setattr(mcp_server, "GUARD", scope)
    assert "one project" in mcp_server._refusal({"project": str(w.root / "projects" / "other")})
    assert "off limits" in mcp_server._refusal({"project": str(project), "id": "k", "source": str(w.root / ".env")})
    assert mcp_server._refusal({"project": str(project)}) == ""
    monkeypatch.setattr(mcp_server, "GUARD", None)
    assert mcp_server._refusal({"project": "/anywhere"}) == ""


def test_mcp_guard_refuses_through_the_server(ws, monkeypatch):
    import asyncio

    from mcp import Client
    w, project = ws
    monkeypatch.setattr(mcp_server, "GUARD", guard.scope_for(project, w))

    async def call():
        async with Client(mcp_server.mcp) as c:
            return await c.call_tool("describe", {"project": str(w.root / "projects" / "other")})
    result = asyncio.run(call())
    assert result.is_error and "Refused by the run's guard" in result.content[0].text
