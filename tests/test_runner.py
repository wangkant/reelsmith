import asyncio
import copy
import dataclasses
import io
import json
import os
import threading
import urllib.request
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

from reelsmith import backends, guard, runner
from reelsmith.agent import providers
from reelsmith.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    (root / "library" / "components").mkdir(parents=True)
    (root / "library" / "NOTES.md").write_text("# notes\n", encoding="utf-8")
    # the agent-sdk engine: the api engine (the default) has its own fixture below
    (root / "workspace.json").write_text(json.dumps({"profile": "douyin", "runner": {"budget_usd": 3,
                                                                                      "engine": "agent-sdk"}}),
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
    assert o.env["ANTHROPIC_BASE_URL"] == "" == o.env["ANTHROPIC_AUTH_TOKEN"]     # a host's other endpoint is not used
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


# ------------------------------------------------------------------ the DeepSeek backend
DS_KEY = "sk-ds-test-777"


def configure(w, runner_cfg: dict, env: str | None = None, engine: str | None = "agent-sdk") -> Workspace:
    """Rewrite the workspace's runner settings (and .env), and load it again; engine None leaves it unset."""
    runner_cfg = {"engine": engine, **runner_cfg} if engine else dict(runner_cfg)
    (w.root / "workspace.json").write_text(json.dumps({"profile": "douyin", "runner": runner_cfg}), encoding="utf-8")
    if env is not None:
        (w.root / ".env").write_text(env, encoding="utf-8")
    return Workspace.load(w.root)


def deepseek(w, **extra) -> Workspace:
    return configure(w, {"budget_usd": 3, "backend": "deepseek", **extra},
                     "ANTHROPIC_API_KEY=sk-ant-test-123456\nANTHROPIC_WORKSPACE_ID=wrkspc_1\n"
                     f"DEEPSEEK_API_KEY={DS_KEY}\n")


def test_backend_settings_precedence(ws):
    w, _ = ws
    s = runner.settings_for(w)
    assert (s.backend, s.model) == ("anthropic", "claude-opus-5-5")
    s = runner.settings_for(w, backend="deepseek")
    assert (s.backend, s.model, s.budget_usd) == ("deepseek", "deepseek-flash", 3)
    s = runner.settings_for(w, backend="deepseek", model="deepseek-v4-pro")
    assert (s.backend, s.model) == ("deepseek", "deepseek-v4-pro")
    w2 = configure(w, {"backend": "deepseek", "model": "deepseek-v4-pro"})
    assert (runner.settings_for(w2).backend, runner.settings_for(w2).model) == ("deepseek", "deepseek-v4-pro")
    assert runner.settings_for(w2, backend="deepseek").model == "deepseek-v4-pro"
    s = runner.settings_for(w2, backend="anthropic")        # the workspace's model went with its backend
    assert (s.backend, s.model) == ("anthropic", "claude-opus-5-5")
    w3 = configure(w, {"model": "claude-sonnet-5-5"})
    assert runner.settings_for(w3).model == "claude-sonnet-5-5"
    assert runner.settings_for(w3, backend="deepseek").model == "deepseek-flash"
    with pytest.raises(runner.WorkspaceError, match="unknown runner backend"):
        runner.settings_for(w, backend="openai")
    with pytest.raises(runner.WorkspaceError, match="unknown runner backend"):
        runner.settings_for(configure(w, {"backend": "nope"}))


def test_backend_flag_reaches_the_run(ws, monkeypatch):
    _, project = ws
    seen = {}
    monkeypatch.setattr(runner, "run", lambda *a, **k: seen.update(k) or {"delivered": True})
    assert runner.main([str(project), "--brief", "b", "--backend", "deepseek"]) == 0
    assert seen["backend"] == "deepseek"
    with pytest.raises(SystemExit):
        runner.main([str(project), "--backend", "nope"])


def test_deepseek_options_carry_only_the_deepseek_key(ws, monkeypatch):
    w, project = ws
    host = {"ANTHROPIC_API_KEY": "sk-ant-host-999", "ANTHROPIC_WORKSPACE_ID": "wrkspc_host",
            "ANTHROPIC_CUSTOM_HEADERS": "anthropic-workspace-id: wrkspc_host",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-9"}
    for name, value in host.items():
        monkeypatch.setenv(name, value)
    w = deepseek(w)
    s = runner.settings_for(w)
    log = runner.SessionLog(project, io.StringIO())
    o = runner.build_options(project, w, s, guard.scope_for(project, w), log, budget_left=2.5)
    log.close()
    env = o.env
    assert o.model == "deepseek-flash[1m]"
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == DS_KEY and env["ANTHROPIC_API_KEY"] == DS_KEY
    for name in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"):
        assert env[name] == "deepseek-flash[1m]", name
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "deepseek-flash" == env["CLAUDE_CODE_SUBAGENT_MODEL"]
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "786432"
    # the CLI gets the host env under options.env: no Anthropic key, token or workspace header survives
    cli_env = {**host, **env}
    assert not [k for k, v in cli_env.items() if "sk-ant" in v or "wrkspc" in v]
    assert sorted(k for k, v in env.items() if v == DS_KEY) == ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
    assert o.max_budget_usd >= 2.5 * 100                    # the runner's own estimate enforces the budget
    # everything else is the same session
    assert o.mcp_servers["reelsmith"]["args"] == ["-m", "reelsmith.mcp_server"] and "Bash" not in o.tools
    assert "mcp__reelsmith__render" in o.allowed_tools and o.hooks["PreToolUse"][0].hooks
    assert "manual.md" in o.system_prompt["append"] and o.permission_mode == "dontAsk"


def test_deepseek_pro_model(ws):
    w, project = ws
    w = deepseek(w, model="deepseek-v4-pro")
    log = runner.SessionLog(project, io.StringIO())
    o = runner.build_options(project, w, runner.settings_for(w), guard.scope_for(project, w), log)
    log.close()
    assert o.model == "deepseek-v4-pro[1m]" and o.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deepseek-v4-pro[1m]"
    assert o.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "deepseek-flash"
    b = backends.get("deepseek")
    assert not backends.can_see(b, "deepseek-v4-pro") and backends.can_see(b, "deepseek-flash[1m]")
    assert backends.cli_model(b, "deepseek-flash[1m]") == "deepseek-flash[1m]"
    assert backends.cli_model(b, "deepseek-other") == "deepseek-other"


def test_deepseek_key_lookup(ws, monkeypatch):
    w, project = ws
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    w = configure(w, {"backend": "deepseek"}, "ANTHROPIC_API_KEY=sk-ant-test-123456\n")
    log = runner.SessionLog(project, io.StringIO())
    with pytest.raises(runner.WorkspaceError, match="DEEPSEEK_API_KEY is missing"):
        runner.build_options(project, w, runner.settings_for(w), guard.scope_for(project, w), log)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-from-env")       # the environment is the fallback
    o = runner.build_options(project, w, runner.settings_for(w), guard.scope_for(project, w), log)
    log.close()
    assert o.env["ANTHROPIC_AUTH_TOKEN"] == "sk-ds-from-env"
    assert runner.key_for(deepseek(w), "DEEPSEEK_API_KEY") == DS_KEY      # the workspace .env comes first


def test_deepseek_price_estimate():
    b = backends.get("deepseek")
    million = {"input_tokens": 10 ** 6, "cache_creation_input_tokens": 10 ** 6, "cache_read_input_tokens": 10 ** 6,
               "output_tokens": 10 ** 6, "server_tool_use": {"web_search_requests": 1000}}
    assert backends.cost(b, {"a": {"model": "deepseek-flash[1m]", "usage": million}}, "deepseek-flash") \
        == pytest.approx(0.30 + 0.30 + 0.006 + 1.20 + 0.75)
    assert backends.cost(b, {"a": {"model": "deepseek-v4-pro", "usage": million}}, "deepseek-flash") \
        == pytest.approx(1.32 + 1.32 + 0.044 + 3.96 + 0.75)
    # an unknown name in the reply falls back to the session's model, then to the dearest
    assert backends.cost(b, {"a": {"model": "deepseek-v4.1-flash", "usage": million}}, "deepseek-flash") \
        == pytest.approx(2.556)
    assert backends.cost(b, {"a": {"model": None, "usage": million}}, "mystery") == pytest.approx(7.394)
    assert runner.estimate_cost({"m": {"model": "claude-opus-5-5", "usage": {"input_tokens": 1000,
                                                                            "output_tokens": 100}}},
                                "claude-opus-5-5") == pytest.approx(0.006)


def test_deepseek_summary_estimates_over_the_cli_figure():
    r = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=4,
                      session_id="s1", total_cost_usd=9.99, model_usage={
                          "deepseek-flash[1m]": {"inputTokens": 100_000, "outputTokens": 10_000,
                                                 "cacheReadInputTokens": 1_000_000, "cacheCreationInputTokens": 0,
                                                 "webSearchRequests": 0, "costUSD": 9.0},
                          "deepseek-flash": {"inputTokens": 200_000, "outputTokens": 5_000,
                                             "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
                                             "webSearchRequests": 0, "costUSD": 0.99}})
    row = runner.summary({"result": r, "usage": {}}, "deepseek-flash", "deepseek")
    assert row["cost_usd"] == pytest.approx(0.048 + 0.066) and row["cost_estimated"]
    assert row["cli_cost_usd"] == 9.99
    row = runner.summary({"result": r, "usage": {}}, "claude-opus-5-5", "anthropic")
    assert row["cost_usd"] == 9.99 and "cli_cost_usd" not in row


def test_deepseek_run_report(ws, no_checks):
    w, project = ws
    deepseek(w)
    r = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=7,
                      session_id="s1", total_cost_usd=7.5, model_usage={
                          "deepseek-flash[1m]": {"inputTokens": 100_000, "outputTokens": 10_000,
                                                 "cacheReadInputTokens": 1_000_000, "cacheCreationInputTokens": 0,
                                                 "webSearchRequests": 0, "costUSD": 7.5}})
    calls = []
    q = fake_query([init(), AssistantMessage(content=[TextBlock("ok")], model="deepseek-flash",
                                              usage={"input_tokens": 100_000, "output_tokens": 10_000,
                                                     "cache_read_input_tokens": 1_000_000}, message_id="m1"),
                    deliver, r], calls=calls)
    out = io.StringIO()
    rep = runner.run(project, "b", query_fn=q, out=out)
    assert rep["delivered"] and rep["backend"] == "deepseek" and rep["model"] == "deepseek-flash"
    assert rep["cost_estimated"] and rep["cost_usd"] == pytest.approx(0.048)
    assert rep["sessions"][0]["cli_cost_usd"] == 7.5 and rep["sessions"][0]["cost_usd"] == pytest.approx(0.048)
    assert calls[0]["options"].env["ANTHROPIC_AUTH_TOKEN"] == DS_KEY
    saved = json.loads((project / "out" / "run_report.json").read_text(encoding="utf-8"))
    assert (saved["backend"], saved["model"], saved["cost_usd"]) == ("deepseek", "deepseek-flash", rep["cost_usd"])
    state = json.loads((project / "build" / "run_state.json").read_text(encoding="utf-8"))
    assert state["backend"] == "deepseek"
    assert "on deepseek deepseek-flash" in out.getvalue() and "Claude prices, not used" in out.getvalue()


def test_deepseek_session_stops_at_the_budget(ws, no_checks):
    w, project = ws
    deepseek(w)                                                # budget $3
    calls = []
    over = AssistantMessage(content=[TextBlock("thinking hard")], model="deepseek-flash", message_id="m1",
                            usage={"input_tokens": 7_000_000, "output_tokens": 1_000_000})   # $2.10 + $1.20
    q = fake_query([init(), over, AssistantMessage(content=[TextBlock("never seen")], model="deepseek-flash"),
                    deliver, result(0.01)], calls=calls)
    out = io.StringIO()
    rep = runner.run(project, "b", query_fn=q, out=out)
    assert not rep["delivered"] and len(calls) == 1 and not (project / "out" / "film.mp4").exists()
    first = rep["sessions"][0]
    assert "budget" in first["aborted"] and first["cost_estimated"] and first["cost_usd"] == pytest.approx(3.3)
    assert rep["cost_usd"] == pytest.approx(3.3) and "budget" in rep["stop"]
    assert any("budget is used up" in p for p in rep["problems"])
    assert "never seen" not in out.getvalue()


def test_under_budget_streaming_does_not_stop(ws):
    _, project = ws
    msgs = [AssistantMessage(content=[TextBlock(f"m{i}")], model="deepseek-flash", message_id=f"m{i}",
                             usage={"input_tokens": 100_000}) for i in range(5)]

    async def q(prompt, options):
        for m in msgs:
            await asyncio.sleep(0)
            yield m
    log = runner.SessionLog(project, io.StringIO())
    cost = lambda rows: backends.cost(backends.get("deepseek"), rows, "deepseek-flash")   # noqa: E731
    out = asyncio.run(runner.run_session(None, "p", log, query_fn=q, cost_fn=cost, budget_usd=0.2))
    assert out["aborted"] is None and out["messages"] == 5          # 5 x $0.03 = $0.15
    out = asyncio.run(runner.run_session(None, "p", log, query_fn=q, cost_fn=cost, budget_usd=0.1))
    log.close()
    assert out["aborted"] and out["messages"] == 4                  # stopped at the 4th: $0.12


def test_deepseek_pro_warns_it_cannot_see(ws, no_checks):
    w, project = ws
    deepseek(w, model="deepseek-v4-pro")
    out = io.StringIO()
    runner.run(project, "b", query_fn=fake_query([init(), deliver, result(0.1)]), out=out)
    assert "deepseek-v4-pro takes no images" in out.getvalue()


def test_a_session_resumes_only_on_its_own_backend(ws, no_checks):
    _, project = ws
    (project / "build").mkdir()
    (project / "build" / "run_state.json").write_text(json.dumps(
        {"status": "running", "session_id": "s7", "cost_usd": 0.4, "brief": "b"}), encoding="utf-8")
    with pytest.raises(runner.WorkspaceError, match="--backend anthropic"):
        go(project, fake_query(), backend="deepseek")


# ------------------------------------------------------------------ runs
def test_delivered_run(ws, no_checks):
    _, project = ws
    calls = []
    q = fake_query([init(), AssistantMessage(content=[TextBlock("ok"), ToolUseBlock("1", "mcp__reelsmith__render",
                                                                                    {"project": str(project)})],
                                               model="claude-opus-5-5"), deliver, result(0.8, 12)], calls=calls)
    rep = go(project, q, brief="一吨汽油值多少钱")
    assert rep["delivered"] and rep["cost_usd"] == 0.8 and rep["turns"] == 12 and rep["stop"] == "finished"
    assert rep["backend"] == "anthropic" and rep["model"] == "claude-opus-5-5" and not rep["cost_estimated"]
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


# ------------------------------------------------------------------ the api engine
OR_KEY = "sk-or-test-555"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
OBJ = {"type": "object", "properties": {}}


@dataclasses.dataclass
class FakeResult:
    text: str
    images: list = dataclasses.field(default_factory=list)
    error: bool = False


@dataclasses.dataclass
class FakeTool:
    name: str
    description: str
    parameters: dict
    run: object


class FakeClient:
    """Plays one scripted step per complete() call: a reply, a callable(messages) -> reply, or an exception."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.on_retry = None

    def complete(self, messages, tools):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        step = self.script.pop(0)
        if callable(step):
            step = step(messages)
        if isinstance(step, BaseException):
            raise step
        return step


def reply(text=None, calls=(), cost=0.01, prompt=1000, completion=100, cached=0):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [{"id": f"call{i}", "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args)}}
                             for i, (name, args) in enumerate(calls)]
    return {"message": msg, "finish_reason": "tool_calls" if calls else "stop",
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "cached_tokens": cached,
                      "cost_usd": cost}}


def fake_tools(seen: dict | None = None):
    """render delivers the film; look returns a still; noop does nothing."""
    def factory(project, ws, scope, web):
        if seen is not None:
            seen.update(project=project, ws=ws, scope=scope, web=web)

        def render(args):
            deliver(project)
            return FakeResult("film rendered")

        def look(args):
            from PIL import Image
            still = project / "build" / "still.png"
            still.parent.mkdir(exist_ok=True)
            Image.new("RGB", (64, 64), "red").save(still)
            return FakeResult("one still", images=[still])
        return [FakeTool("render", "render the film", OBJ, render), FakeTool("look", "a still", OBJ, look),
                FakeTool("noop", "nothing", OBJ, lambda args: FakeResult("nothing changed"))]
    return factory


@pytest.fixture
def api_ws(ws, monkeypatch):
    w, project = ws
    for name in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "REELSMITH_PROXY"):
        monkeypatch.delenv(name, raising=False)
    return configure(w, {"budget_usd": 3}, f"OPENROUTER_API_KEY={OR_KEY}\nDEEPSEEK_API_KEY={DS_KEY}\n",
                     engine=None), project


def go_api(project, client, tools=None, out=None, **kw):
    return runner.run(project, client_factory=lambda s: client, tools_factory=tools or fake_tools(),
                      out=out or io.StringIO(), **kw)


def _state(project: Path) -> dict:
    return json.loads((project / "build" / "run_state.json").read_text(encoding="utf-8"))


def test_api_is_the_default_engine(api_ws):
    w, _ = api_ws
    s = runner.settings_for(w)
    assert (s.engine, s.provider, s.model, s.budget_usd) == ("api", "openrouter", DEFAULT_MODEL, 3)
    assert s.api.base_url == "https://openrouter.ai/api/v1" and s.reasoning is None and s.web is None
    assert runner.settings_for(None).engine == "api"                    # a project outside any workspace
    s = runner.settings_for(w, provider="deepseek")
    assert (s.engine, s.provider, s.model) == ("api", "deepseek", "deepseek-flash")
    assert runner.settings_for(w, provider="deepseek", model="deepseek-v4-pro").model == "deepseek-v4-pro"
    s = runner.settings_for(w, backend="deepseek")                     # --backend picks the agent-sdk engine
    assert (s.engine, s.backend, s.model, s.api, s.provider) == ("agent-sdk", "deepseek", "deepseek-flash", None, None)
    s = runner.settings_for(w, engine="agent-sdk")
    assert (s.engine, s.backend, s.model) == ("agent-sdk", "anthropic", "claude-opus-5-5")


def test_api_settings_precedence(api_ws):
    w, _ = api_ws
    w2 = configure(w, {"provider": "deepseek", "model": "deepseek-v4-pro", "reasoning": "HIGH",
                       "web": {"search": "ddgs"}, "images": False, "context_tokens": 64000}, engine="api")
    s = runner.settings_for(w2)
    assert (s.provider, s.model, s.reasoning, s.web) == ("deepseek", "deepseek-v4-pro", "high", {"search": "ddgs"})
    assert (s.images, s.context_tokens, s.max_image_edge) == (False, 64000, 1280)
    assert runner.settings_for(w2, model="deepseek-flash").model == "deepseek-flash"
    s = runner.settings_for(w2, provider="openrouter")                # the workspace's model went with its provider
    assert (s.provider, s.model) == ("openrouter", DEFAULT_MODEL)
    s = runner.settings_for(w2, engine="agent-sdk")                    # ... and with its engine
    assert (s.engine, s.model) == ("agent-sdk", "claude-opus-5-5")
    # a workspace that names a backend and no engine predates the api engine
    legacy = configure(w, {"backend": "deepseek", "model": "deepseek-v4-pro"}, engine=None)
    assert (runner.settings_for(legacy).engine, runner.settings_for(legacy).model) == ("agent-sdk", "deepseek-v4-pro")
    s = runner.settings_for(legacy, provider="openrouter")
    assert (s.engine, s.model) == ("api", DEFAULT_MODEL)
    assert runner.settings_for(configure(w, {"engine": "api", "backend": "deepseek"}, engine=None)).engine == "api"
    for kw, match in (({"backend": "deepseek", "provider": "openrouter"}, "pass one"),
                      ({"engine": "api", "backend": "deepseek"}, "--backend is for"),
                      ({"engine": "agent-sdk", "provider": "deepseek"}, "--provider is for"),
                      ({"engine": "cloud"}, "unknown runner engine"),
                      ({"provider": "nope"}, "unknown runner provider"),
                      ({"provider": "openai"}, "no default model"),
                      ({"provider": "custom"}, "runner.base_url")):
        with pytest.raises(runner.WorkspaceError, match=match):
            runner.settings_for(w, **kw)
    assert runner.settings_for(w, provider="openai", model="gpt-x").model == "gpt-x"
    for bad, match in (({"reasoning": "max"}, "runner.reasoning"), ({"web": "ddgs"}, "runner.web"),
                       ({"images": "yes"}, "runner.images"), ({"context_tokens": 100}, "context_tokens"),
                       ({"max_image_edge": "big"}, "wrong type"), ({"engine": "nope"}, "unknown runner engine")):
        with pytest.raises(runner.WorkspaceError, match=match):
            runner.settings_for(configure(w, bad, engine=None))


def test_builtin_providers():
    o = providers.get("openrouter")
    assert (o.base_url, o.key, o.default_model) == ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", DEFAULT_MODEL)
    assert o.reports_cost and o.pricer(DEFAULT_MODEL) is None and o.headers["X-Title"] == "reelsmith"
    body = o.body("high")
    assert body == {"usage": {"include": True}, "provider": {"require_parameters": True}, "reasoning": {"effort": "high"}}
    assert "reasoning" not in o.body() and "reasoning" not in o.extra_body       # body() works on a copy
    assert o.can_see(DEFAULT_MODEL) and o.can_see("deepseek/deepseek-v4-pro") is False
    assert o.can_see("vendor/unknown") is None
    d = providers.get("DeepSeek")
    assert (d.base_url, d.key, d.default_model) == ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-flash")
    assert not d.reports_cost and d.body("low") == {"reasoning_effort": "low"} and d.body() == {}
    m = 10 ** 6
    assert d.price("deepseek-flash", {"prompt_tokens": 2 * m, "cached_tokens": m, "completion_tokens": m}) \
        == pytest.approx(0.30 + 0.006 + 1.20)
    assert d.price("deepseek-v4-pro", {"prompt_tokens": m, "completion_tokens": m}) == pytest.approx(1.32 + 3.96)
    assert d.price("deepseek-next", {"prompt_tokens": m}) == pytest.approx(1.32)      # unlisted: the dearest
    assert d.pricer("deepseek-flash")({"completion_tokens": m, "cached_tokens": "x"}) == pytest.approx(1.20)
    assert d.can_see("deepseek-flash") and d.can_see("deepseek-v4-pro") is False
    a = providers.get("openai")
    assert (a.base_url, a.key, a.default_model) == ("https://api.openai.com/v1", "OPENAI_API_KEY", None)
    assert a.pricer("gpt-x") is None and a.body("medium") == {"reasoning_effort": "medium"}
    with pytest.raises(runner.WorkspaceError, match="unknown runner provider"):
        providers.get("anthropic")


def test_custom_provider_and_workspace_prices():
    c = providers.get("custom", {"base_url": "http://localhost:8000/v1/", "key_env": "LOCAL_KEY",
                                 "prices": {"qwen-local": [0.1, 0.4, 0.01], "glm": [1, 2]},
                                 "extra_body": {"top_k": 20}})
    assert (c.base_url, c.key, c.default_model, c.reports_cost) == ("http://localhost:8000/v1", "LOCAL_KEY", None, False)
    m = 10 ** 6
    assert c.price("qwen-local", {"prompt_tokens": 2 * m, "cached_tokens": m, "completion_tokens": m}) \
        == pytest.approx(0.1 + 0.01 + 0.4)
    assert c.price("GLM", {"prompt_tokens": m, "cached_tokens": m}) == pytest.approx(1.0)   # cached at the input price
    assert c.price("other", {"prompt_tokens": m}) is None and c.pricer("other") is None
    assert c.body("low") == {"top_k": 20, "reasoning_effort": "low"}
    assert providers.get("custom", {"base_url": "http://127.0.0.1:1234/v1"}).key is None    # a local server: no key
    # extra_body merges into a built-in's own; workspace prices price the calls that report no cost
    o = providers.get("openrouter", {"extra_body": {"provider": {"order": ["deepseek"]}},
                                     "prices": {DEFAULT_MODEL: [0.2, 0.8]}, "base_url": "http://ignored/v1"})
    assert o.body() == {"usage": {"include": True}, "provider": {"require_parameters": True, "order": ["deepseek"]}}
    assert o.pricer(DEFAULT_MODEL)({"prompt_tokens": m}) == pytest.approx(0.2) and o.base_url.startswith("https://openrouter")
    assert providers.PROVIDERS["openrouter"].prices is None
    assert providers.PROVIDERS["openrouter"].extra_body["provider"] == {"require_parameters": True}
    for cfg, match in (({}, "runner.base_url"), ({"base_url": "localhost:8000"}, "runner.base_url"),
                       ({"base_url": "http://h/v1", "key_env": "MY KEY"}, "key_env"),
                       ({"base_url": "http://h/v1", "prices": {"m": [1]}}, "runner.prices"),
                       ({"base_url": "http://h/v1", "prices": {"m": [1, -2]}}, "runner.prices"),
                       ({"base_url": "http://h/v1", "prices": [1, 2]}, "runner.prices"),
                       ({"base_url": "http://h/v1", "extra_body": "x"}, "extra_body")):
        with pytest.raises(runner.WorkspaceError, match=match):
            providers.get("custom", cfg)


def test_api_client_and_keys(api_ws, monkeypatch):
    w, project = api_ws
    w = configure(w, {"reasoning": "low"}, f"OPENROUTER_API_KEY={OR_KEY}\n", engine=None)
    c = runner.api_client(w, runner.settings_for(w))
    assert c.url == "https://openrouter.ai/api/v1/chat/completions" and c.model == DEFAULT_MODEL
    assert c._headers["Authorization"] == f"Bearer {OR_KEY}" and c._headers["X-Title"] == "reelsmith"
    body = c.body([], [])
    assert body["reasoning"] == {"effort": "low"} and body["usage"] == {"include": True}
    assert OR_KEY not in repr(c)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")             # the workspace .env comes first
    assert runner.api_client(w, runner.settings_for(w))._headers["Authorization"] == f"Bearer {OR_KEY}"
    w = configure(w, {}, "", engine=None)                              # the environment is the fallback
    assert runner.api_client(w, runner.settings_for(w))._headers["Authorization"] == "Bearer sk-or-env"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(runner.WorkspaceError, match="OPENROUTER_API_KEY is missing"):
        runner.api_client(w, runner.settings_for(w))
    with pytest.raises(runner.WorkspaceError, match="DEEPSEEK_API_KEY is missing"):
        runner.api_client(w, runner.settings_for(w, provider="deepseek"))
    local = configure(w, {"provider": "custom", "base_url": "http://127.0.0.1:8000/v1", "model": "qwen3"}, "",
                      engine=None)
    c = runner.api_client(local, runner.settings_for(local))
    assert c.url == "http://127.0.0.1:8000/v1/chat/completions" and "Authorization" not in c._headers
    keyed = configure(w, {"provider": "custom", "base_url": "https://gw.example.com/v1", "key_env": "GW_KEY",
                          "model": "glm", "proxy": "http://proxy.example.com:3128"}, "GW_KEY=gw-1\n", engine=None)
    c = runner.api_client(keyed, runner.settings_for(keyed))
    assert c._headers["Authorization"] == "Bearer gw-1" and c.model == "glm"
    proxies = [h.proxies for h in c._opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies == [{"http": "http://proxy.example.com:3128", "https": "http://proxy.example.com:3128"}]
    with pytest.raises(runner.WorkspaceError, match="GW_KEY is missing"):
        runner.api_client(configure(w, {"provider": "custom", "base_url": "https://gw.example.com/v1",
                                        "key_env": "GW_KEY", "model": "glm"}, "", engine=None),
                          runner.settings_for(keyed))
    assert runner.main([str(project), "--brief", "b"]) == 2           # a missing key is a setup problem


def test_api_run_delivers(api_ws, no_checks):
    w, project = api_ws
    seen, mid = {}, {}

    def peek(messages):
        mid.update(state=_state(project), saved=(project / runner.MESSAGES_FILE).is_file(),
                   daemon=threading.current_thread().daemon)
        return reply("Done: the film is rendered.", cost=0.01)
    client = FakeClient(reply("Research first.", [("noop", {}), ("render", {"project": str(project)})], cost=0.02),
                        peek)
    out = io.StringIO()
    rep = go_api(project, client, fake_tools(seen), out=out, brief="一吨汽油值多少钱")
    assert rep["delivered"] and rep["stop"] == "finished"
    assert (rep["engine"], rep["provider"], rep["backend"], rep["model"]) == ("api", "openrouter", None, DEFAULT_MODEL)
    assert rep["cost_usd"] == pytest.approx(0.03) and not rep["cost_estimated"] and rep["turns"] == 2
    first = client.calls[0]
    system, user = first["messages"]
    assert system["role"] == "system" and "manual.md" in system["content"] and "NOTES.md" in system["content"]
    assert "Today is" in system["content"] and "no shell" in system["content"]
    assert user["role"] == "user" and "一吨汽油值多少钱" in user["content"]
    assert [t["function"]["name"] for t in first["tools"]] == ["render", "look", "noop"]
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second[2:]] == ["assistant", "tool", "tool"] and second[-1]["content"] == "film rendered"
    assert seen["project"] == project and seen["web"] is None and seen["scope"].spill is None
    assert runner.MANUAL.parent in seen["scope"].extra_read
    # mid-session the state already holds the turn's spend and the conversation is on disk
    assert mid["saved"] and mid["state"]["inflight"]["cost_usd"] == pytest.approx(0.02)
    assert mid["state"]["status"] == "running" and mid["state"]["session_id"]
    assert mid["daemon"]                                                # Ctrl+C does not wait for the agent
    saved = json.loads((project / "out" / "run_report.json").read_text(encoding="utf-8"))
    assert (saved["engine"], saved["provider"], saved["model"], saved["turns"]) == ("api", "openrouter", DEFAULT_MODEL, 2)
    row = saved["sessions"][0]
    assert row["kind"] == "new" and row["answer"].startswith("Done") and row["usage"]["prompt_tokens"] == 2000
    state = _state(project)
    assert (state["status"], state["engine"], state["provider"], state["backend"]) == ("done", "api", "openrouter", None)
    assert state["inflight"] is None and state["session_id"] == row["session_id"]
    convo = json.loads((project / runner.MESSAGES_FILE).read_text(encoding="utf-8"))
    assert convo["session_id"] == row["session_id"] and convo["messages"][-1]["content"].startswith("Done")
    log = out.getvalue()
    assert f"new session on openrouter {DEFAULT_MODEL}" in log and "-> render" in log and "DELIVERED" in log


def test_api_fixup_continues_the_conversation(api_ws, no_checks):
    _, project = api_ws
    client = FakeClient(reply("All done.", cost=0.5), reply(None, [("render", {})], cost=0.2),
                        reply("Rendered now.", cost=0.1))
    rep = go_api(project, client, brief="b")
    assert rep["delivered"] and [s["kind"] for s in rep["sessions"]] == ["new", "fixup"]
    assert rep["cost_usd"] == pytest.approx(0.8) and rep["turns"] == 3
    fix = client.calls[1]["messages"]
    assert fix[2] == {"role": "assistant", "content": "All done."}
    assert fix[-1]["role"] == "user" and "out/film.mp4 does not exist" in fix[-1]["content"]
    assert rep["sessions"][0]["session_id"] == rep["sessions"][1]["session_id"]


def test_api_fixups_are_capped(api_ws, no_checks):
    _, project = api_ws
    client = FakeClient(*[reply("All done.") for _ in range(5)])
    rep = go_api(project, client, brief="b")
    assert not rep["delivered"] and len(rep["sessions"]) == 3 and len(client.calls) == 3


def test_api_crash_resumes_in_process(api_ws, no_checks):
    _, project = api_ws
    client = FakeClient(reply(None, [("noop", {})], cost=0.1), RuntimeError("HTTP 502 from openrouter.ai"),
                        reply(None, [("render", {})], cost=0.1), reply("ok", cost=0.1))
    rep = go_api(project, client, brief="b")
    assert rep["delivered"] and [s["kind"] for s in rep["sessions"]] == ["new", "resume"]
    assert "HTTP 502" in rep["sessions"][0]["error"] and rep["sessions"][0]["turns"] == 1
    again = client.calls[2]["messages"]
    assert "Resuming" in again[-1]["content"] and "HTTP 502" in again[-1]["content"]
    assert [m["role"] for m in again[1:4]] == ["user", "assistant", "tool"]
    assert rep["cost_usd"] == pytest.approx(0.3)


def test_api_failure_before_any_turn_does_not_retry(api_ws, no_checks):
    _, project = api_ws
    client = FakeClient(RuntimeError("HTTP 401 from openrouter.ai: no such key"))
    rep = go_api(project, client, brief="b")
    assert not rep["delivered"] and len(rep["sessions"]) == 1 and len(client.calls) == 1
    assert "401" in rep["stop"] and rep["sessions"][0]["session_id"] is None


def test_api_budget_stops_the_session_and_the_run(api_ws, no_checks):
    _, project = api_ws                                                 # budget $3
    client = FakeClient(*[reply(None, [("noop", {})], cost=1.6) for _ in range(5)])
    rep = go_api(project, client, brief="b")
    assert not rep["delivered"] and len(client.calls) == 2
    assert "budget" in rep["sessions"][0]["aborted"] and rep["cost_usd"] == pytest.approx(3.2)
    assert any("budget is used up" in p for p in rep["problems"])


def test_api_on_deepseek_prices_from_the_table(api_ws, no_checks):
    _, project = api_ws
    m = 10 ** 6
    client = FakeClient({**reply(None, [("render", {})]), "usage": {"prompt_tokens": m, "completion_tokens": 0}},
                        {**reply("done"), "usage": {"prompt_tokens": m, "cached_tokens": m, "completion_tokens": m}})
    out = io.StringIO()
    rep = go_api(project, client, out=out, brief="b", provider="deepseek")
    assert rep["delivered"] and (rep["provider"], rep["model"]) == ("deepseek", "deepseek-flash")
    assert rep["cost_estimated"] and rep["cost_usd"] == pytest.approx(0.30 + 0.006 + 1.20)
    assert "priced from a table" in out.getvalue()


def test_api_unpriced_model_warns(api_ws, no_checks):
    _, project = api_ws
    out = io.StringIO()
    rep = go_api(project, FakeClient({**reply(None, [("render", {})]), "usage": {"prompt_tokens": 10}},
                                     reply("done", cost=None)), out=out, brief="b", provider="openai", model="gpt-x")
    assert rep["delivered"] and rep["cost_usd"] == 0 and rep["cost_estimated"]
    assert "no price for gpt-x" in out.getvalue()


def test_api_blind_model_gets_no_images(api_ws, no_checks):
    _, project = api_ws
    client = FakeClient(reply(None, [("look", {})]), reply(None, [("render", {})]), reply("done"))
    out = io.StringIO()
    rep = go_api(project, client, out=out, brief="b", provider="deepseek", model="deepseek-v4-pro")
    assert rep["delivered"] and "deepseek-v4-pro takes no images" in out.getvalue()
    sent = client.calls[1]["messages"]
    assert "image_url" not in json.dumps(sent) and "not shown" in sent[-1]["content"]
    # a model that sees gets the still as an image part; the saved conversation keeps no image data
    client = FakeClient(reply(None, [("look", {})]), reply(None, [("render", {})]), reply("done"))
    go_api(project, client, brief="b", fresh=True)
    assert '"image_url"' in json.dumps(client.calls[1]["messages"])
    saved = (project / runner.MESSAGES_FILE).read_text(encoding="utf-8")
    assert "image_url" not in saved and "image not kept" in saved


def _killed_run(project: Path, **state) -> list[dict]:
    """The state and saved conversation of a run whose process died mid-session."""
    (project / "build").mkdir(exist_ok=True)
    history = [{"role": "system", "content": "old system"}, {"role": "user", "content": "the brief"},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "c1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c1", "content": "nothing changed"}]
    (project / runner.MESSAGES_FILE).write_text(json.dumps({"engine": "api", "session_id": "sess1",
                                                             "messages": history}), encoding="utf-8")
    (project / "build" / "run_state.json").write_text(json.dumps({
        "status": "running", "engine": "api", "provider": "openrouter", "model": DEFAULT_MODEL, "session_id": "sess1",
        "cost_usd": 0.4, "turns": 2, "brief": "b", "last_stop": "the process was interrupted",
        "inflight": {"session_id": "sess1", "cost_usd": 0.25, "turns": 3}, **state}), encoding="utf-8")
    return history


def test_api_resumes_a_killed_run_from_saved_messages(api_ws, no_checks):
    _, project = api_ws
    history = _killed_run(project)
    client = FakeClient(reply(None, [("render", {})], cost=0.1), reply("done", cost=0.1))
    rep = go_api(project, client)                                       # no brief: it resumes
    assert rep["delivered"]
    sent = client.calls[0]["messages"]
    assert sent[:4] == history and "Resuming" in sent[4]["content"] and "interrupted" in sent[4]["content"]
    assert [s["kind"] for s in rep["sessions"]] == ["interrupted", "resume"]
    assert rep["cost_usd"] == pytest.approx(0.4 + 0.25 + 0.2) and rep["turns"] == 2 + 3 + 2
    assert rep["sessions"][1]["session_id"] == "sess1"


def test_api_resume_without_saved_messages_starts_over(api_ws, no_checks):
    _, project = api_ws
    _killed_run(project, brief="the brief", inflight=None)
    (project / runner.MESSAGES_FILE).unlink()
    client = FakeClient(reply(None, [("render", {})]), reply("done"))
    out = io.StringIO()
    rep = go_api(project, client, out=out)
    first = client.calls[0]["messages"]
    assert len(first) == 2 and "the brief" in first[1]["content"] and "Resuming" in first[1]["content"]
    assert "no saved conversation" in out.getvalue() and rep["delivered"]


def test_api_resume_needs_the_same_engine_provider_and_model(api_ws, no_checks):
    _, project = api_ws
    _killed_run(project, provider="deepseek", model="deepseek-flash")
    with pytest.raises(runner.WorkspaceError, match="--provider deepseek --model deepseek-flash, or start over"):
        go_api(project, FakeClient())
    with pytest.raises(runner.WorkspaceError, match="--engine api"):
        go(project, fake_query(), engine="agent-sdk")
    (project / "build" / "run_state.json").write_text(json.dumps(
        {"status": "running", "session_id": "s7", "brief": "b"}), encoding="utf-8")       # an agent-sdk run
    with pytest.raises(runner.WorkspaceError, match="--engine agent-sdk"):
        go_api(project, FakeClient())
    rep = go_api(project, FakeClient(reply(None, [("render", {})]), reply("done")), brief="b2", fresh=True)
    assert rep["delivered"] and rep["sessions"][0]["kind"] == "new"


def test_api_web_settings_reach_the_toolbox(api_ws, no_checks):
    w, project = api_ws
    configure(w, {"budget_usd": 3, "proxy": "http://proxy.example.com:3128", "web": {"search": "none"}}, None,
              engine=None)
    seen = {}

    def tools(project, ws, scope, web):
        made = fake_tools(seen)(project, ws, scope, web)
        return type("Box", (list,), {"notes": ["web_search is left out: turned off"]})(made)
    out = io.StringIO()
    rep = go_api(project, FakeClient(reply(None, [("render", {})]), reply("done")), tools, out=out, brief="b")
    assert rep["delivered"] and seen["web"] == {"search": "none", "proxy": "http://proxy.example.com:3128"}
    assert seen["ws"].root == w.root and "note: web_search is left out" in out.getvalue()


def test_in_thread_returns_and_raises():
    assert asyncio.run(runner.in_thread(lambda a, b: a + b, 2, 3)) == 5

    def boom():
        raise ValueError("nope")
    with pytest.raises(ValueError, match="nope"):
        asyncio.run(runner.in_thread(boom))


def test_engine_and_provider_flags_reach_the_run(api_ws, monkeypatch):
    _, project = api_ws
    seen = {}
    monkeypatch.setattr(runner, "run", lambda *a, **k: seen.update(k) or {"delivered": False})
    assert runner.main([str(project), "--brief", "b", "--engine", "api", "--provider", "deepseek"]) == 1
    assert (seen["engine"], seen["provider"], seen["backend"]) == ("api", "deepseek", None)
    for bad in (["--engine", "cloud"], ["--provider", "nope"]):
        with pytest.raises(SystemExit):
            runner.main([str(project), *bad])


def test_api_run_with_the_real_toolbox(api_ws, no_checks):
    pytest.importorskip("reelsmith.agent.tools")
    from reelsmith.tools import TOOLS
    w, project = api_ws
    configure(w, {"budget_usd": 3, "fixups": 0, "web": None}, None, engine=None)
    client = FakeClient(reply("I would start with the manual.", cost=0.01))
    rep = runner.run(project, "b", client_factory=lambda s: client, out=io.StringIO())
    specs = client.calls[0]["tools"]
    names = {t["function"]["name"] for t in specs}
    assert all(t["type"] == "function" and t["function"]["parameters"].get("type") == "object" for t in specs)
    assert {"render", "check", "preview"} <= names and set(TOOLS) & names
    assert not rep["delivered"] and rep["engine"] == "api" and len(rep["sessions"]) == 1
