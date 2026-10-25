"""reelsmith setup: every target merges into its agent's config in a temporary cwd and home, never the real ones."""
import json
import os
import sys
from pathlib import Path

import pytest

from reelsmith import agentconf, cli

try:
    import tomllib
except ImportError:                 # Python 3.10: setup merges Codex configs unchecked there
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
needs_toml = pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """A project folder and a fake home; Path.home() and the agents' home variables point there too."""
    cwd, home = tmp_path / "proj", tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for name in ("CODEX_HOME", "DSH_HOME", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(cwd)
    return cwd, home


def setup(target, cwd, home, env=None, run=None, **kw):
    p = agentconf.plan(target, cwd=cwd, home=home, env=env or {}, **kw)
    return agentconf.apply(p, cwd=cwd, home=home, run=run or (lambda c: (0, "")))


def test_server_spec_is_absolute(tmp_path):
    spec = agentconf.server_spec(root="studio")
    assert spec["command"] == os.path.abspath(sys.executable) and Path(spec["command"]).is_absolute()
    assert spec["args"] == ["-m", "reelsmith.mcp_server"]
    assert Path(spec["env"]["REELSMITH_ROOT"]).is_absolute() and spec["env"]["PYTHONSAFEPATH"] == "1"
    assert "REELSMITH_ROOT" not in agentconf.server_spec()["env"]


def test_claude_code_project(dirs):
    cwd, home = dirs
    (cwd / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "extra": 1}),
                                   encoding="utf-8")
    lines = setup("claude-code", cwd, home, root="studio")
    doc = json.loads((cwd / ".mcp.json").read_text(encoding="utf-8"))
    assert doc["extra"] == 1 and doc["mcpServers"]["other"] == {"command": "x"}
    server = doc["mcpServers"]["reelsmith"]
    assert server["type"] == "stdio" and server["args"] == ["-m", "reelsmith.mcp_server"]
    assert server["env"]["REELSMITH_ROOT"] == str(cwd / "studio")
    skill = cwd / ".claude" / "skills" / "reelsmith" / "SKILL.md"
    assert skill.read_text(encoding="utf-8") == agentconf.skill_text()
    assert any("approve" in ln for ln in lines)
    assert setup("claude-code", cwd, home, root="studio")[0] == "nothing to change: already set up"
    setup("claude-code", cwd, home, uninstall=True)
    assert json.loads((cwd / ".mcp.json").read_text(encoding="utf-8")) == {"mcpServers": {"other": {"command": "x"}},
                                                                           "extra": 1}
    assert not (cwd / ".claude").exists()                  # the folders setup made are gone again
    assert setup("claude-code", cwd, home, uninstall=True)[0].startswith("nothing to remove")


def test_a_config_that_only_held_reelsmith_is_removed(dirs):
    cwd, home = dirs
    setup("cursor", cwd, home)
    assert json.loads((cwd / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["reelsmith"]
    assert (cwd / ".cursor" / "skills" / "reelsmith" / "SKILL.md").is_file()
    setup("cursor", cwd, home, uninstall=True)
    assert not (cwd / ".cursor").exists()


def test_invalid_json_is_left_alone(dirs):
    cwd, home = dirs
    (cwd / ".mcp.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(agentconf.SetupError, match="not valid JSON"):
        agentconf.plan("claude-code", cwd=cwd, home=home, env={})
    assert (cwd / ".mcp.json").read_text(encoding="utf-8") == "{not json"


def test_claude_code_user_runs_the_cli(dirs, monkeypatch):
    cwd, home = dirs
    monkeypatch.setattr(agentconf, "_claude_exe", lambda: "claude")
    ran = []
    setup("claude-code", cwd, home, user=True, run=lambda c: ran.append(c) or (0, ""))
    assert ran[0] == ["claude", "mcp", "remove", "--scope", "user", "reelsmith"]
    assert ran[1][:6] == ["claude", "mcp", "add-json", "--scope", "user", "reelsmith"]
    assert json.loads(ran[1][6])["args"] == ["-m", "reelsmith.mcp_server"]
    assert (home / ".claude" / "skills" / "reelsmith" / "SKILL.md").is_file() and not (cwd / ".mcp.json").exists()
    failed = agentconf.apply(agentconf.plan("claude-code", cwd=cwd, home=home, env={}, user=True), cwd=cwd,
                             home=home, run=lambda c: (1, "boom") if "add-json" in c else (1, "not found"))
    assert any(ln.startswith("FAILED (1)") and "boom" in ln for ln in failed)


def test_claude_code_user_follows_claude_config_dir(dirs, tmp_path, monkeypatch):
    cwd, home = dirs
    monkeypatch.setattr(agentconf, "_claude_exe", lambda: "claude")
    config_dir = tmp_path / "claudeconf"
    lines = setup("claude-code", cwd, home, env={"CLAUDE_CONFIG_DIR": str(config_dir)}, user=True)
    assert (config_dir / "skills" / "reelsmith" / "SKILL.md").is_file() and not (home / ".claude").exists()
    assert any("$CLAUDE_CONFIG_DIR/.claude.json" in ln for ln in lines)
    setup("claude-code", cwd, home, env={"CLAUDE_CONFIG_DIR": str(config_dir)}, user=True, uninstall=True)
    assert not (config_dir / "skills" / "reelsmith" / "SKILL.md").exists()


def link_dir(link: Path, target: Path) -> None:
    """A directory symlink, or a junction where symlinks need a privilege (Windows)."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


def test_setup_writes_through_a_fresh_temp_file(dirs, tmp_path):
    cwd, home = dirs
    victim = tmp_path / "victim.txt"
    victim.write_text("precious\n", encoding="utf-8")
    (cwd / ".codex").mkdir()
    for name in ("config.toml.reelsmith-tmp", ".config.toml.reelsmith-tmp"):   # a link planted at a guessable name
        os.link(victim, cwd / ".codex" / name)
    setup("codex", cwd, home)
    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert "[mcp_servers.reelsmith]" in (cwd / ".codex" / "config.toml").read_text(encoding="utf-8")
    left = {p.name for p in (cwd / ".codex").iterdir()}
    assert left == {"config.toml", "config.toml.reelsmith-tmp", ".config.toml.reelsmith-tmp"}   # no temp file of ours


def test_project_setup_refuses_a_linked_config_folder(dirs, tmp_path):
    cwd, home = dirs
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "config.toml").write_text('model = "mine"\n', encoding="utf-8")
    link_dir(cwd / ".codex", outside)
    with pytest.raises(agentconf.SetupError, match="leads through a link"):
        agentconf.plan("codex", cwd=cwd, home=home, env={})
    with pytest.raises(agentconf.SetupError, match="leads through a link"):
        agentconf.plan("codex", cwd=cwd, home=home, env={}, uninstall=True)
    assert (outside / "config.toml").read_text(encoding="utf-8") == 'model = "mine"\n'
    (cwd / ".claude").mkdir()
    link_dir(cwd / ".claude" / "skills", outside)                  # the skill folder too
    with pytest.raises(agentconf.SetupError, match="leads through a link"):
        agentconf.plan("claude-code", cwd=cwd, home=home, env={})
    assert sorted(p.name for p in outside.iterdir()) == ["config.toml"]
    link_dir(home / ".cursor", outside)                            # the user's own home may link its dotfiles
    setup("cursor", cwd, home, user=True)
    assert (outside / "mcp.json").is_file()


CODEX_BEFORE = """# my settings
model = "gpt-5.5-codex"

[mcp_servers.other]
command = "other"

[mcp_servers.reelsmith]
command = "old-python"

[mcp_servers.reelsmith.env]
OLD = "1"

[projects."/x"]
trust_level = "trusted"
"""


@needs_toml
def test_codex_project_merges_toml(dirs):
    cwd, home = dirs
    config = cwd / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(CODEX_BEFORE, encoding="utf-8")
    lines = setup("codex", cwd, home)
    text = config.read_text(encoding="utf-8")
    doc = tomllib.loads(text)
    assert text.startswith("# my settings") and doc["model"] == "gpt-5.5-codex"
    assert doc["mcp_servers"]["other"] == {"command": "other"} and doc["projects"]["/x"]["trust_level"] == "trusted"
    server = doc["mcp_servers"]["reelsmith"]
    assert server["command"] == os.path.abspath(sys.executable) and "OLD" not in server["env"]
    assert server["tool_timeout_sec"] == 3600 and "OPENROUTER_API_KEY" in server["env_vars"]
    assert "OPENAI_API_KEY" in server["env_vars"]                  # transcribe's default key
    assert (cwd / ".agents" / "skills" / "reelsmith" / "SKILL.md").is_file()
    assert any("trusted project" in ln for ln in lines)
    assert setup("codex", cwd, home)[0] == "nothing to change: already set up"
    setup("codex", cwd, home, uninstall=True)
    doc = tomllib.loads(config.read_text(encoding="utf-8"))
    assert "reelsmith" not in doc["mcp_servers"] and doc["mcp_servers"]["other"] and doc["model"]


@needs_toml
def test_codex_user_follows_codex_home(dirs, tmp_path):
    cwd, home = dirs
    codex_home = tmp_path / "codexhome"
    setup("codex", cwd, home, env={"CODEX_HOME": str(codex_home)}, user=True)
    assert tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]["reelsmith"]
    assert (home / ".agents" / "skills" / "reelsmith" / "SKILL.md").is_file() and not (cwd / ".codex").exists()
    setup("codex", cwd, home, env={"CODEX_HOME": str(codex_home)}, user=True, uninstall=True)
    assert not (codex_home / "config.toml").exists()


@needs_toml
def test_codex_refuses_forms_it_cannot_edit(dirs):
    cwd, home = dirs
    config = cwd / ".codex" / "config.toml"
    config.parent.mkdir()
    for text in ('mcp_servers = { reelsmith = { command = "x" } }\n', '[mcp_servers]\nreelsmith.command = "x"\n'):
        config.write_text(text, encoding="utf-8")
        with pytest.raises(agentconf.SetupError, match="does not edit"):
            agentconf.plan("codex", cwd=cwd, home=home, env={})
    config.write_text("model = \n", encoding="utf-8")
    with pytest.raises(agentconf.SetupError, match="not valid TOML"):
        agentconf.plan("codex", cwd=cwd, home=home, env={})


@needs_toml
def test_toml_values_round_trip():
    value = {"command": "C:\\Program Files\\py\\python.exe", "args": ["-m", "x"], "env": {"A B": "\"q\"", "Z": "中"},
             "n": 3, "t": True}
    assert tomllib.loads(f"v = {agentconf.toml_value(value)}")["v"] == value


DSH_BEFORE = "# my overrides\n- id: hmr\n  disabled: true\n"


def test_dsh_user_appends_a_managed_block(dirs):
    cwd, home = dirs
    patch = home / ".dsh" / "cordis.patch.yml"
    patch.parent.mkdir()
    patch.write_text(DSH_BEFORE, encoding="utf-8")
    setup("dsh", cwd, home, user=True)
    text = patch.read_text(encoding="utf-8")
    assert text.startswith(DSH_BEFORE) and agentconf.DSH_BEGIN in text and text.rstrip().endswith(agentconf.DSH_END)
    assert "name: '@deepseek-ai/dsh-mcp-client'" in text and "toolCallTimeoutMs: 3600000" in text
    assert json.dumps(os.path.abspath(sys.executable), ensure_ascii=False) in text
    assert (home / ".dsh" / "skills" / "reelsmith" / "SKILL.md").is_file()
    assert setup("dsh", cwd, home, user=True)[0] == "nothing to change: already set up"
    setup("dsh", cwd, home, user=True, uninstall=True)
    assert patch.read_text(encoding="utf-8").rstrip("\n") == DSH_BEFORE.rstrip("\n")


def test_dsh_user_follows_dsh_home_and_checks_the_file(dirs, tmp_path):
    cwd, home = dirs
    dsh_home = tmp_path / "dshhome"
    dsh_home.mkdir()
    (dsh_home / "cordis.patch.yml").write_text("[]\n", encoding="utf-8")
    setup("dsh", cwd, home, env={"DSH_HOME": str(dsh_home)}, user=True)
    text = (dsh_home / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "[]" not in text and text.startswith(agentconf.DSH_BEGIN)
    (dsh_home / "cordis.patch.yml").write_text("plugins: {}\n", encoding="utf-8")
    with pytest.raises(agentconf.SetupError, match="not a YAML list"):
        agentconf.plan("dsh", cwd=cwd, home=home, env={"DSH_HOME": str(dsh_home)}, user=True)


def test_dsh_project_writes_a_patch_and_skills_at_the_git_root(dirs):
    cwd, home = dirs
    (cwd / ".git").mkdir()
    sub = cwd / "videos"
    sub.mkdir()
    lines = setup("dsh", sub, home)
    patch = sub / ".dsh" / "reelsmith.cordis.yml"
    assert "serverName: reelsmith" in patch.read_text(encoding="utf-8")
    assert (cwd / ".dsh" / "skills" / "reelsmith" / "SKILL.md").is_file()
    # `dsh <profile>` must come first: `dsh --patch <file> web` stops with "--profile <name> is required"
    assert any(f"`dsh web --patch {patch}`" in ln and "integrations/dsh" in ln for ln in lines)
    assert patch.read_text(encoding="utf-8").startswith("# Mounts the reelsmith MCP server: dsh <profile> --patch")
    setup("dsh", sub, home, uninstall=True)
    assert not patch.exists() and not (cwd / ".dsh").exists()


def test_generic_writes_nothing(dirs):
    cwd, home = dirs
    p = agentconf.plan("generic", cwd=cwd, home=home, env={})
    assert not p.changes
    text = "\n".join(agentconf.show(p))
    assert "## Video editing with reelsmith" in text and '"mcpServers"' in text and "SKILL.md" in text
    assert json.loads(text[text.index("{"):text.index("\n}") + 2])["mcpServers"]["reelsmith"]["args"]
    assert list(cwd.iterdir()) == [] and list(home.iterdir()) == []


def test_cli_print_writes_nothing(dirs, capsys):
    cwd, home = dirs
    assert cli.main(["setup", "codex", "--print", "--root", "studio"]) == 0
    out = capsys.readouterr().out
    assert "would write" in out and "[mcp_servers.reelsmith]" in out and "SKILL.md" in out
    assert '"OPENAI_API_KEY"' in out                                # forwarded to the server for transcribe
    assert list(cwd.iterdir()) == [] and list(home.iterdir()) == []
    assert cli.main(["setup", "cursor"]) == 0
    assert (cwd / ".cursor" / "mcp.json").is_file()
    assert cli.main(["setup", "cursor", "--uninstall"]) == 0 and not (cwd / ".cursor").exists()
    (cwd / ".mcp.json").write_text("[1, 2]", encoding="utf-8")
    assert cli.main(["setup", "claude-code"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["setup", "vim"])
