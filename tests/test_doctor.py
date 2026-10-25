"""reelsmith doctor on a faked machine: PATH, versions, modules and the renderer folder are all stand-ins."""
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from reelsmith import agentconf, cli, doctor

draw = importlib.import_module("reelsmith.providers.draw")   # the package exports a draw() too

ROOT = Path(__file__).resolve().parent.parent
SECRET = "sk-or-v1-doctorsecret0123456789"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """Everything required present (Linux with apt), every optional tool present but the Remotion browser."""
    m = types.SimpleNamespace(
        os="linux", calls=[], modules={"playwright", "faster_whisper"}, browsers=["Google Chrome (/opt/google/chrome)"],
        codex=Path("/usr/bin/codex"), python=(3, 12, 1),
        paths={name: f"/usr/bin/{name}" for name in ("node", "npm", "ffmpeg", "ffprobe", "apt-get", "reelsmith-mcp")},
        versions={"node": "v22.11.0", "ffmpeg": "ffmpeg version 7.1 Copyright (c) the FFmpeg developers",
                  "ffprobe": "ffprobe version 7.1 Copyright (c) the FFmpeg developers"})

    def first_line(cmd):
        m.calls.append(cmd)
        out = m.versions.get(Path(cmd[0]).stem)
        return (0, out) if out else (1, "not runnable")

    monkeypatch.setattr(doctor, "which", lambda name: m.paths.get(name))
    monkeypatch.setattr(doctor, "first_line", first_line)
    monkeypatch.setattr(doctor, "python_version", lambda: m.python)
    monkeypatch.setattr(doctor, "has_module", lambda name: name in m.modules)
    monkeypatch.setattr(doctor, "chromium_browsers", lambda os_name: list(m.browsers))
    monkeypatch.setattr(doctor, "system", lambda: m.os)
    monkeypatch.setattr(draw, "find_codex", lambda: m.codex)
    for name in doctor.KEYS:
        monkeypatch.delenv(name, raising=False)
    m.renderer = tmp_path / "renderer"
    modules = m.renderer / "node_modules"
    for name in ("@remotion/renderer", "@remotion/bundler", "remotion"):
        (modules / name).mkdir(parents=True)
    (m.renderer / "package.json").write_text(json.dumps({"dependencies": {"remotion": "4.0.532"}}), encoding="utf-8")
    (modules / "remotion" / "package.json").write_text(json.dumps({"version": "4.0.532"}), encoding="utf-8")
    monkeypatch.setenv("REELSMITH_RENDERER", str(m.renderer))
    m.cwd = tmp_path / "here"
    m.cwd.mkdir()
    monkeypatch.chdir(m.cwd)
    return m


def rows(report):
    return {c["name"]: c for c in report["checks"]}


def run(capsys, *argv):
    code = cli.main(["doctor", *argv])
    return code, capsys.readouterr().out


def test_a_ready_machine_passes_and_reports_json(machine, capsys):
    code, out = run(capsys, "--json")
    report = json.loads(out)
    assert code == 0 and report["ok"] is True and report["system"] == "linux"
    assert report["renderer"] == str(machine.renderer) and report["checkout"] == str(ROOT)
    for c in report["checks"]:
        assert set(c) == {"name", "ok", "required", "detail", "fix", "enables"}
        assert c["fix"] == "" or not c["ok"]
    got = rows(report)
    required = {name for name, c in got.items() if c["required"]}
    assert required == {"python", "reelsmith", "node", "renderer", "ffmpeg", "ffprobe"}
    assert all(got[name]["ok"] for name in required)
    assert "22.11.0" in got["node"]["detail"] and "7.1" in got["ffmpeg"]["detail"]
    assert got["capture"]["ok"] and got["codex"]["ok"] and got["faster-whisper"]["ok"] and got["on-path"]["ok"]
    assert not got["remotion-browser"]["ok"] and "remotion browser ensure" in got["remotion-browser"]["fix"]
    assert all(not c["ok"] and c["enables"] for name, c in got.items() if name.startswith("key:"))
    assert {cmd[1] for cmd in machine.calls} <= {"--version", "-version"}      # versions only, nothing else runs


def test_the_table_and_its_exit_status(machine, capsys):
    code, out = run(capsys)
    assert code == 0 and out.rstrip().endswith("All required checks pass.")
    assert "  ok    node" in out and "  -     remotion-browser" in out
    machine.paths.pop("ffprobe")
    code, out = run(capsys)
    assert code == 1 and "FAIL  ffprobe" in out and "fix: sudo apt-get install -y ffmpeg" in out
    assert "1 required check(s) failed: ffprobe" in out


@pytest.mark.parametrize("os_name, paths, fix", [
    ("windows", {"winget": "winget.exe"}, "winget install -e --accept-package-agreements --accept-source-agreements "
                                          "--id OpenJS.NodeJS.LTS"),
    ("macos", {"brew": "/opt/homebrew/bin/brew"}, "brew install node"),
    ("macos", {}, "install Homebrew (https://brew.sh), then: brew install node"),
    ("linux", {"apt-get": "/usr/bin/apt-get"}, "https://deb.nodesource.com/setup_22.x"),
    ("linux", {"pacman": "/usr/bin/pacman"}, "sudo pacman -S --needed nodejs npm"),
    ("linux", {"zypper": "/usr/bin/zypper"}, "install it from https://nodejs.org/en/download"),
])
def test_a_missing_tool_gets_this_systems_install_command(machine, os_name, paths, fix):
    machine.os = os_name
    machine.paths = {"ffmpeg": "/x/ffmpeg", "ffprobe": "/x/ffprobe", **paths}
    report = doctor.run_checks()
    node = rows(report)["node"]
    assert not report["ok"] and not node["ok"] and node["required"] and fix in node["fix"]


def test_old_versions_fail(machine):
    machine.versions["node"] = "v18.19.0"
    machine.python = (3, 9, 18)
    got = rows(doctor.run_checks())
    assert not got["node"]["ok"] and "18.19.0" in got["node"]["detail"] and "20+" in got["node"]["detail"]
    assert not got["python"]["ok"] and "3.9.18" in got["python"]["detail"]
    assert got["python"]["fix"] == "sudo apt-get install -y python3 python3-venv python3-pip"


def test_renderer_packages_missing_or_stale(machine):
    modules = machine.renderer / "node_modules"
    (modules / "remotion" / "package.json").write_text(json.dumps({"version": "4.0.400"}), encoding="utf-8")
    got = rows(doctor.run_checks())["renderer"]
    assert not got["ok"] and "4.0.400" in got["detail"] and "4.0.532" in got["detail"]
    assert got["fix"] == f"cd {doctor.quote(machine.renderer, 'linux')} && npm ci"
    (modules / "remotion" / "package.json").unlink()
    assert "not installed" in rows(doctor.run_checks())["renderer"]["detail"]
    machine.os = "windows"
    fix = rows(doctor.run_checks())["renderer"]["fix"]
    assert fix == f"cd '{machine.renderer}'; npm.cmd ci"


def test_remotion_browser_found(machine):
    shell = (machine.renderer / "node_modules" / ".remotion" / "chrome-headless-shell" / "linux64"
             / "chrome-headless-shell-linux64" / "chrome-headless-shell")
    shell.parent.mkdir(parents=True)
    shell.write_bytes(b"")
    (shell.parents[2] / "VERSION").write_text("149.0.7790.0", encoding="utf-8")
    got = rows(doctor.run_checks())["remotion-browser"]
    assert got["ok"] and "149.0.7790.0" in got["detail"] and got["fix"] == ""


def test_optional_tools_missing_never_fail_the_run(machine):
    machine.modules = set()
    machine.codex = None
    machine.paths.pop("reelsmith-mcp")
    report = doctor.run_checks()
    got = rows(report)
    assert report["ok"]
    for name, extra in (("capture", "[capture]"), ("faster-whisper", "[transcribe]")):
        assert not got[name]["ok"] and not got[name]["required"] and f"{ROOT}{extra}" in got[name]["fix"]
        assert got[name]["fix"].startswith(doctor.quote(sys.executable, "linux") + " -m pip install -e")
    assert got["codex"]["fix"] == "npm install -g @openai/codex && codex login"
    assert not got["on-path"]["ok"]
    machine.modules = {"playwright"}
    machine.browsers = []
    assert rows(doctor.run_checks())["capture"]["fix"].endswith("-m playwright install chromium")


def test_keys_report_where_they_are_never_their_values(machine, tmp_path, monkeypatch, capsys):
    ws = tmp_path / "studio"
    ws.mkdir()
    (ws / "workspace.json").write_text(json.dumps({"providers": {"tts": {"provider": "openai",
                                                                         "key_env": "MY_TTS_KEY"}}}),
                                       encoding="utf-8")
    (ws / ".env").write_text(f"OPENROUTER_API_KEY={SECRET}\n# OPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-environment-secret")
    for argv in (["--json", "--workspace", str(ws)], ["--workspace", str(ws)]):
        code, out = run(capsys, *argv)
        assert code == 0 and SECRET not in out and "sk-deepseek-environment-secret" not in out
    got = rows(json.loads(run(capsys, "--json", "--workspace", str(ws))[1]))
    assert got["workspace"]["ok"] and got["workspace"]["required"] and "a .env" in got["workspace"]["detail"]
    assert got["key:OPENROUTER_API_KEY"]["ok"] and str(ws / ".env") in got["key:OPENROUTER_API_KEY"]["detail"]
    assert not got["key:OPENAI_API_KEY"]["ok"] and str(ws / ".env") in got["key:OPENAI_API_KEY"]["fix"]
    assert got["key:DEEPSEEK_API_KEY"]["ok"] and "environment" in got["key:DEEPSEEK_API_KEY"]["detail"]
    assert not got["key:MY_TTS_KEY"]["ok"] and "providers.tts.key_env" in got["key:MY_TTS_KEY"]["enables"]


def test_a_named_workspace_must_exist_and_load(machine, tmp_path, capsys):
    empty = tmp_path / "empty"
    code, out = run(capsys, "--json", "--workspace", str(empty))
    got = rows(json.loads(out))["workspace"]
    assert code == 1 and got["required"] and not got["ok"]
    src = doctor.quote(f"{ROOT / 'examples' / 'workspace'}/.", "linux")
    assert got["fix"] == f"mkdir -p {doctor.quote(empty, 'linux')} && cp -R {src} {doctor.quote(f'{empty}/', 'linux')}"
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "workspace.json").write_text('{"locale": 5}', encoding="utf-8")
    code, out = run(capsys, "--json", "--workspace", str(tmp_path / "bad"))
    assert code == 1 and "locale" in rows(json.loads(out))["workspace"]["detail"]
    code, out = run(capsys, "--json")                    # none named, none found: optional
    got = rows(json.loads(out))["workspace"]
    assert code == 0 and not got["required"] and not got["ok"]


def test_agents_set_up_in_this_folder(machine):
    cwd = machine.cwd
    spec = agentconf.server_spec()
    (cwd / ".mcp.json").write_text(json.dumps({"mcpServers": {"reelsmith": {"type": "stdio", **spec}}}),
                                   encoding="utf-8")
    (cwd / ".codex").mkdir()
    (cwd / ".codex" / "config.toml").write_text('model = "x"\n\n' + agentconf.codex_table(agentconf.codex_server(spec)),
                                                encoding="utf-8")
    (cwd / ".dsh").mkdir()
    (cwd / ".dsh" / "reelsmith.cordis.yml").write_text(agentconf.dsh_rows(spec), encoding="utf-8")
    got = rows(doctor.run_checks())["agents"]
    assert got["ok"] and all(f"{a} (" in got["detail"] for a in ("claude-code", "codex", "dsh"))
    assert "cursor" not in got["detail"]
    (cwd / ".cursor").mkdir()
    gone = str(Path(cwd, "old-venv", "python"))
    (cwd / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"reelsmith": {**spec, "command": gone}}}),
                                              encoding="utf-8")
    got = rows(doctor.run_checks())["agents"]
    assert not got["ok"] and gone in got["detail"] and got["fix"].endswith(" setup cursor")


def test_no_agent_set_up_points_at_setup(machine):
    got = rows(doctor.run_checks())["agents"]
    assert not got["ok"] and not got["required"] and got["fix"].endswith(" setup <agent>")


def test_commands_are_quoted_for_each_shell():
    assert doctor.program("C:/Program Files/py/python.exe", ["-m", "pip"], "windows") == \
        "& 'C:/Program Files/py/python.exe' -m pip"
    assert doctor.quote("it's", "windows") == "'it''s'"
    assert doctor.program("/opt/my py/python", ["-V"], "linux") == "'/opt/my py/python' -V"
    assert doctor.in_folder("/a b", "npm ci", "macos") == "cd '/a b' && npm ci"
    assert doctor.copy_starter("C:/studio", "windows").startswith("New-Item -ItemType Directory -Force 'C:/studio'")
