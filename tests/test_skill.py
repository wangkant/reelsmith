"""The reelsmith Agent Skill, its copy in the CC plugin, and the plugin and marketplace manifests."""
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "reelsmith" / "SKILL.md"


def _frontmatter(text: str) -> dict:
    head = text.split("---", 2)[1]
    out = {}
    for line in head.strip().splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_skill_follows_the_agent_skills_format():
    text = SKILL.read_text(encoding="utf-8")
    meta = _frontmatter(text)
    assert meta["name"] == SKILL.parent.name == "reelsmith"
    assert 0 < len(meta["description"]) <= 1024 and "video" in meta["description"]
    assert len(text.splitlines()) < 120 and "`manual`" in text


def test_agent_guides_cover_footage_and_what_costs_money():
    # the skill, setup's instructions block and the MCP server's instructions: both ways in, the same paid list
    from reelsmith import agentconf, mcp_server, runner
    for text in (SKILL.read_text(encoding="utf-8"), agentconf.INSTRUCTIONS, mcp_server.INSTRUCTIONS):
        plain = text.replace("`", "")
        for word in ("probe", "frames", "scenes", "silences", "transcribe", "ripple_delete", "src:<clip>@", "speak",
                     "locale"):
            assert word in plain, word
        assert "speak, animate and transcribe cost money" in plain and "draw spends" in plain
    brief = runner.first_prompt(Path("p"), "Trim my recording to 60 s.")
    assert "Edit the material it names" in brief and "silences" in brief and "research and script" in brief


def test_plugin_copies_match_the_skill():
    sys.path.insert(0, str(ROOT / "integrations"))
    try:
        import sync_skills
    finally:
        sys.path.pop(0)
    assert sync_skills.drifted() == [], "run python integrations/sync_skills.py"


def test_plugin_and_marketplace_manifests():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    (entry,) = market["plugins"]
    plugin_dir = ROOT / entry["source"]
    plugin = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert entry["source"].startswith("./") and entry["name"] == plugin["name"] == market["name"] == "reelsmith"
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert plugin["version"] == pyproject["project"]["version"]
    # PyPI's summary says what the plugin says: an editing harness, no canvas or genre
    summary = pyproject["project"]["description"]
    assert summary.startswith("A video editing harness for AI coding agents") and "vertical" not in summary
    command = plugin["mcpServers"]["reelsmith"]["command"]
    assert command in pyproject["project"]["scripts"]
    assert (plugin_dir / "skills" / "reelsmith" / "SKILL.md").is_file()
