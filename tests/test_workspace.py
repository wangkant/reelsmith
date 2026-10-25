import json
from pathlib import Path

import pytest

from reelsmith import workspace as W
from reelsmith.profiles import DOUYIN, LANDSCAPE, TIKTOK

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "workspace"


def make_ws(root: Path, config=None, rules=None, env: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace.json").write_text(json.dumps(config or {}), encoding="utf-8")
    if rules is not None:
        (root / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    if env is not None:
        (root / ".env").write_text(env, encoding="utf-8")
    return root


def test_find_workspace_nearest_ancestor(tmp_path):
    outer = make_ws(tmp_path / "outer", {"profile": "tiktok"})
    inner = make_ws(outer / "projects" / "inner", {"profile": "shorts"})
    project = inner / "projects" / "p1"
    project.mkdir(parents=True)
    ws = W.find_workspace(project)
    assert ws.root == inner.resolve()
    assert W.find_workspace(outer / "projects" / "other").root == outer.resolve()


def test_find_workspace_accepts_project_json_path_and_missing_folder(tmp_path):
    root = make_ws(tmp_path / "ws")
    p = root / "projects" / "a"
    p.mkdir(parents=True)
    (p / "project.json").write_text("{}", encoding="utf-8")
    assert W.find_workspace(p / "project.json").root == root.resolve()
    assert W.find_workspace(root / "projects" / "not-yet").root == root.resolve()


def test_outside_any_workspace(tmp_path):
    assert W.find_workspace(tmp_path / "lonely") is None
    assert W.rules_for(tmp_path / "lonely") == W.DEFAULT_RULES
    assert W.profile_for(tmp_path / "lonely") is LANDSCAPE
    assert W.locale_for(tmp_path / "lonely") == "en"


def test_workspace_paths(tmp_path):
    ws = W.Workspace.load(make_ws(tmp_path / "ws"))
    root = (tmp_path / "ws").resolve()
    assert ws.library_dir == root / "library"
    assert ws.components_dir == root / "library" / "components"
    assert ws.notes_path == root / "library" / "NOTES.md"
    assert ws.ledger_path == root / "ledger.jsonl"
    assert ws.cache_dir == root / ".cache"


def test_rules_merge_defaults(tmp_path):
    ws = W.Workspace.load(make_ws(tmp_path / "ws", rules={"hard": {"max_title": 18, "banned": ["x"]},
                                                          "advice": {"hook_seconds": 3}, "custom": 1}))
    assert ws.rules["hard"] == {"max_title": 18, "banned": ["x"]}          # nothing the owner did not set
    assert ws.rules["advice"] == {"hook_seconds": 3}
    assert ws.rules["custom"] == 1
    assert W.DEFAULT_RULES == {"hard": {}, "advice": {}}       # defaults untouched
    assert W.merge_rules({"advice": {"target_s": True}})["advice"]["target_s"] is True


@pytest.mark.parametrize("rules, fragment", [
    ({"hard": {"max_title": "24"}}, "hard.max_title"),
    ({"hard": {"max_title": True}}, "hard.max_title"),
    ({"hard": {"banned": "word"}}, "hard.banned"),
    ({"advice": {"hook_seconds": 0}}, "advice.hook_seconds"),
    ({"advice": {"target_s": [80, 40]}}, "advice.target_s"),
    ({"hard": []}, "'hard' must be an object"),
])
def test_bad_rules_raise_actionable(tmp_path, rules, fragment):
    root = make_ws(tmp_path / "ws", rules=rules)
    with pytest.raises(W.WorkspaceError, match=fragment.replace(".", r"\.").replace("'", "'")):
        W.Workspace.load(root)


def test_bad_json_names_the_file(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "workspace.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(W.WorkspaceError, match="workspace.json"):
        W.find_workspace(root)
    (root / "workspace.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(W.WorkspaceError, match="JSON object"):
        W.find_workspace(root)


def test_parse_dotenv():
    text = "﻿# comment\nexport A=1\nB = 'two words' # c\nC=\"x\\\"y\\ny\"\nD=plain # tail\nE=\nbad line\n9X=no\nF=a=b\n"
    env = W.parse_dotenv(text.lstrip("﻿"))
    assert env == {"A": "1", "B": "two words", "C": 'x"y\ny', "D": "plain", "F": "a=b"}


def test_keys_dotenv_first_then_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    monkeypatch.setenv("ONLY_ENV", "env-value")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    ws = W.Workspace.load(make_ws(tmp_path / "ws", env="OPENROUTER_API_KEY=from-dotenv\nEMPTY=\n"))
    assert ws.keys["OPENROUTER_API_KEY"] == "from-dotenv"
    assert ws.keys.get("ONLY_ENV") == "env-value"
    assert "ONLY_ENV" in ws.keys and "MISSING_KEY" not in ws.keys
    assert ws.keys.get("MISSING_KEY", "d") == "d"
    with pytest.raises(KeyError):
        ws.keys["MISSING_KEY"]
    assert list(ws.keys) == ["OPENROUTER_API_KEY"]           # iteration: .env only, never the whole environment
    assert "from-dotenv" not in repr(ws.keys) and "from-dotenv" not in repr(ws)
    assert W.keys_for(tmp_path / "elsewhere").get("ONLY_ENV") == "env-value"


def test_profile_for_precedence(tmp_path):
    root = make_ws(tmp_path / "ws", {"profile": "tiktok"})
    p = root / "projects" / "a"
    p.mkdir(parents=True)
    assert W.profile_for(p) is TIKTOK
    (p / "project.json").write_text(json.dumps({"version": 2, "profile": "douyin"}), encoding="utf-8")
    assert W.profile_for(p) is DOUYIN
    (p / "project.json").write_text(json.dumps({"version": 2, "profile": "vine"}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown profile 'vine'"):
        W.profile_for(p)


def test_project_paths(tmp_path):
    p = tmp_path / "proj"
    paths = W.project_paths(p)
    root = p.resolve()
    assert paths.root == root
    assert paths.project_json == root / "project.json"
    assert paths.voice_json == root / "voice" / "voice.json"
    assert paths.voice_wav == root / "voice" / "voice.wav"
    assert paths.resolved == root / "build" / "resolved.json"
    assert paths.film == root / "out" / "film.mp4"
    assert paths.meta == root / "out" / "meta.json"
    assert paths.report == root / "out" / "report.json"
    assert paths.history == root / ".history"
    assert paths["stills"] == root / "build" / "stills"
    assert set(paths.to_json()) >= {"assets", "inspect", "review", "script"}


def test_profile_caption_band_is_the_renderers_default():
    # Captions.tsx draws captions without a box in the safe area's bottom 200 px; the manual quotes this band
    from reelsmith.profiles import PROFILES
    for p in PROFILES.values():
        c, s = p.captions, p.safe
        assert (c.x, c.w, c.h, c.y + c.h) == (s.x, s.w, 200, s.y + s.h), p.name


def test_example_workspace_matches_spec():
    # the starter is neutral: the default canvas and language, no owner rules, the voice chosen by the locale
    ws = W.Workspace.load(EXAMPLE)
    assert (ws.config["profile"], ws.locale) == ("landscape", "en")
    assert ws.config["providers"]["tts"] == {"provider": "openrouter", "model": "qwen/qwen-audio-3.0-tts-plus"}
    assert ws.config["providers"]["image"]["provider"] == "codex"
    assert ws.config["providers"]["video"] == {"provider": "openrouter", "model": "bytedance/seedance-1-5-pro",
                                               "resolution": "720p"}
    assert ws.config["providers"]["transcribe"]["provider"] == "openai"
    assert ws.config["budget"] == {"per_project_usd": 1.0, "min_balance_usd": 5.0}
    assert ws.rules == {"hard": {}, "advice": {}}
    # one owner's setup, kept as a separate example
    news = W.Workspace.load(EXAMPLE.parent / "news-explainer-zh")
    assert (news.config["profile"], news.locale) == ("douyin", "zh-CN")
    assert news.config["providers"]["tts"]["voice"] == "longanlufeng"
    hard = news.rules["hard"]
    assert (hard["max_title"], hard["max_title_numbers"], hard["min_sources"]) == (24, 2, 1)


def test_the_starter_delivers_any_short_film(tmp_path, monkeypatch):
    # a copy of the starter with one 6 s clip and no sources passes check: nothing in it assumes a platform or a genre
    import shutil
    from reelsmith import tools
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    ws = tmp_path / "studio"
    shutil.copytree(EXAMPLE, ws)
    p = ws / "projects" / "first-film"
    made = tools.new_project(str(p), title="My first film")
    assert made.ok and "landscape 1920x1080" in made, made
    ops = [{"op": "add_track", "track": {"id": "v1", "kind": "visual", "clips": [
        {"id": "t", "type": "text", "text": "Hello", "start": 0, "dur": 6, "box": "safe"}]}}]
    assert tools.edit(str(p), ops).ok
    checked = tools.check(str(p))
    assert checked.ok and "[error]" not in checked, checked
