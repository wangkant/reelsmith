"""reelsmith doctor: what this machine has of what reelsmith needs, and of what each optional tool needs.

Local checks only: no network, no model calls, nothing installed or downloaded. Every check that fails says the exact
command that fixes it on this OS (PowerShell syntax on Windows). Key values are never read out: only whether a key is
there and where.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path

from . import __version__
from .workspace import ENV_FILE, WORKSPACE_FILE, Workspace, WorkspaceError, parse_dotenv

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/wangkant/reelsmith"
MIN_PYTHON = (3, 10)
MIN_NODE = 20
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CHECKOUT_FILES = ("pyproject.toml", "docs/manual.md", "skills/reelsmith/SKILL.md")
REMOTION_SHELLS = {"chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell"}
INSTALLERS = {"windows": ("winget",), "macos": ("brew",), "linux": ("apt-get", "dnf", "pacman", "zypper")}
WINGET = "winget install -e --accept-package-agreements --accept-source-agreements --id "
INSTALL = {
    "python": {"winget": WINGET + "Python.Python.3.12", "brew": "brew install python@3.12",
               "apt-get": "sudo apt-get install -y python3 python3-venv python3-pip",
               "dnf": "sudo dnf install -y python3 python3-pip", "pacman": "sudo pacman -S --needed python python-pip",
               "zypper": "sudo zypper install -y python3 python3-pip"},
    # distro Node packages are often older than 20: NodeSource for apt
    "node": {"winget": WINGET + "OpenJS.NodeJS.LTS", "brew": "brew install node",
             "apt-get": "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && "
                        "sudo apt-get install -y nodejs",
             "dnf": "sudo dnf install -y nodejs npm", "pacman": "sudo pacman -S --needed nodejs npm"},
    # Fedora's own ffmpeg-free has no libx264, which reverse and animate encode with
    "ffmpeg": {"winget": WINGET + "Gyan.FFmpeg", "brew": "brew install ffmpeg",
               "apt-get": "sudo apt-get install -y ffmpeg",
               "dnf": "sudo dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-"
                      "$(rpm -E %fedora).noarch.rpm && sudo dnf install -y --allowerasing ffmpeg",
               "pacman": "sudo pacman -S --needed ffmpeg"},
    "git": {"winget": WINGET + "Git.Git", "brew": "brew install git",
            "apt-get": "sudo apt-get install -y git", "dnf": "sudo dnf install -y git",
            "pacman": "sudo pacman -S --needed git", "zypper": "sudo zypper install -y git"},
}
DOWNLOAD = {"python": "https://www.python.org/downloads/", "node": "https://nodejs.org/en/download",
            "ffmpeg": "https://ffmpeg.org/download.html", "git": "https://git-scm.com/downloads"}
KEYS = {
    "OPENROUTER_API_KEY": "speak (narration) and animate (image-to-video); reelsmith run on OpenRouter",
    "OPENAI_API_KEY": "transcribe through OpenAI (the default endpoint); reelsmith run --provider openai",
    "DEEPSEEK_API_KEY": "reelsmith run on DeepSeek (--provider deepseek, --engine dsh)",
    "ANTHROPIC_API_KEY": "reelsmith run --engine agent-sdk on Anthropic",
    "TAVILY_API_KEY": "web search for reelsmith run when the web extra (ddgs) is not installed",
}
AGENT_CONFIGS = (("claude-code", ".mcp.json"), ("codex", ".codex/config.toml"),
                 ("dsh", ".dsh/reelsmith.cordis.yml"), ("cursor", ".cursor/mcp.json"))


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    detail: str
    fix: str = ""
    enables: str = ""


# ------------------------------------------------------------------ the machine (patched in tests)
def system() -> str:
    return "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"


def which(name: str) -> str | None:
    return shutil.which(name)


def python_version() -> tuple[int, int, int]:
    return tuple(sys.version_info[:3])


def first_line(cmd: list[str]) -> tuple[int, str]:
    """Exit status and the first line a version command prints."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    lines = (done.stdout.strip() or done.stderr.strip()).splitlines()
    return done.returncode, lines[0].strip() if lines else ""


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def renderer_dir() -> Path:
    return Path(os.environ.get("REELSMITH_RENDERER") or ROOT / "renderer")


# ------------------------------------------------------------------ commands for this OS
def quote(arg, os_name: str) -> str:
    if os_name == "windows":                         # PowerShell literal string
        return "'" + str(arg).replace("'", "''") + "'"
    return shlex.quote(str(arg))


def program(path, args: list[str], os_name: str) -> str:
    """A command line that runs the program at `path` (PowerShell needs & before a quoted path)."""
    head = quote(path, os_name)
    return " ".join(["&", head, *args] if os_name == "windows" else [head, *args])


def then(os_name: str) -> str:
    return "; " if os_name == "windows" else " && "


def in_folder(folder, command: str, os_name: str) -> str:
    if os_name == "windows":                         # `;` runs on after a failed cd; -ErrorAction Stop does not
        return f"Set-Location -LiteralPath {quote(folder, os_name)} -ErrorAction Stop; {command}"
    return f"cd {quote(folder, os_name)} && {command}"


def npm(os_name: str, name: str = "npm") -> str:
    """npm.cmd on Windows: PowerShell's execution policy often blocks npm.ps1."""
    return f"{name}.cmd" if os_name == "windows" else name


def installer(os_name: str) -> str | None:
    return next((name for name in INSTALLERS.get(os_name, ()) if which(name)), None)


def install(tool: str, os_name: str) -> str:
    """The package-manager command that installs a system tool here, else where to download it."""
    via = installer(os_name)
    command = INSTALL[tool].get(via) if via else None
    if command:
        return command
    if os_name == "macos" and tool in INSTALL:
        return f"install Homebrew (https://brew.sh), then: {INSTALL[tool]['brew']}"
    return f"install it from {DOWNLOAD[tool]}"


def pip_extra(extra: str, os_name: str) -> str:
    return program(sys.executable, ["-m", "pip", "install", "-e", quote(f"{ROOT}[{extra}]", os_name)], os_name)


def reelsmith_command(os_name: str) -> str:
    """How to run this install's reelsmith: plain when PATH finds it, else by its full path."""
    scripts = Path(sysconfig.get_path("scripts"))
    exe = scripts / ("reelsmith.exe" if os_name == "windows" else "reelsmith")
    found = which("reelsmith")
    if found and os.path.normcase(os.path.dirname(os.path.abspath(found))) == os.path.normcase(str(scripts)):
        return "reelsmith"
    return program(exe, [], os_name)


def _numbers(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(g) for g in m.groups() if g is not None) if m else ()


# ------------------------------------------------------------------ required
def check_python(os_name: str) -> Check:
    ver = python_version()
    shown = ".".join(map(str, ver))
    if ver[:2] >= MIN_PYTHON:
        return Check("python", True, True, f"Python {shown} ({sys.executable})")
    return Check("python", False, True, f"Python {shown} ({sys.executable}): reelsmith needs 3.10 or newer",
                 install("python", os_name))


def check_checkout(os_name: str) -> Check:
    missing = [rel for rel in CHECKOUT_FILES if not (ROOT / rel).is_file()]
    if not missing:
        return Check("reelsmith", True, True, f"reelsmith {__version__}, editable checkout {ROOT}")
    clone = then(os_name).join([f"git clone {REPO}", "cd reelsmith", "python -m venv .venv",
                                program(Path(".venv", "Scripts" if os_name == "windows" else "bin", "python"),
                                        ["-m", "pip", "install", "-e", quote(".[capture,web]", os_name)], os_name)])
    return Check("reelsmith", False, True,
                 f"reelsmith {__version__} at {ROOT} is not an editable checkout ({', '.join(missing)} missing): it "
                 "reads its manual, skill and renderer from the checkout", clone)


def check_node(os_name: str) -> Check:
    node = which("node")
    if not node:
        return Check("node", False, True, f"node is not on PATH: the renderer needs Node.js {MIN_NODE}+",
                     install("node", os_name))
    code, out = first_line([node, "--version"])
    ver = _numbers(out)
    if code or not ver or ver[0] < MIN_NODE:
        return Check("node", False, True, f"node {out or '(no version)'} at {node}: the renderer needs Node.js "
                                          f"{MIN_NODE}+", install("node", os_name))
    no_npm = "" if which("npm") else "; npm is not on PATH (installing the renderer needs it)"
    return Check("node", True, True, f"node {out.lstrip('v')} ({node}){no_npm}")


def check_renderer(os_name: str) -> Check:
    folder = renderer_dir()
    fix = f"{npm(os_name)} ci --prefix {quote(folder, os_name)}"
    try:
        pinned = json.loads((folder / "package.json").read_text(encoding="utf-8"))["dependencies"]["remotion"]
    except (OSError, ValueError, KeyError, TypeError):
        return Check("renderer", False, True, f"{folder / 'package.json'} is missing or unreadable: the renderer is "
                                              "part of the checkout (or set REELSMITH_RENDERER to it)",
                     check_checkout(os_name).fix or f"git -C {quote(ROOT, os_name)} checkout -- renderer")
    modules = folder / "node_modules"
    try:
        got = json.loads((modules / "remotion" / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return Check("renderer", False, True, f"the renderer's packages are not installed ({modules / 'remotion'} "
                                              "missing)", fix)
    if re.fullmatch(r"\d+\.\d+\.\d+", str(pinned)) and pinned != got:
        return Check("renderer", False, True, f"remotion {got} is installed but package.json pins {pinned}: "
                                              "reinstall the renderer's packages", fix)
    gone = [name for name in ("@remotion/renderer", "@remotion/bundler") if not (modules / name).is_dir()]
    if gone:
        return Check("renderer", False, True, f"{', '.join(gone)} missing from {modules}", fix)
    return Check("renderer", True, True, f"remotion {got} installed in {modules}")


def check_ffmpeg(name: str, os_name: str) -> Check:
    exe = which(name)
    if not exe:
        return Check(name, False, True, f"{name} is not on PATH: probing, mastering and the footage tools need it",
                     install("ffmpeg", os_name))
    code, out = first_line([exe, "-version"])
    if code:
        return Check(name, False, True, f"{exe} -version failed: {out[:200]}", install("ffmpeg", os_name))
    m = re.search(r"version\s+(\S+)", out)
    return Check(name, True, True, f"{name} {m.group(1) if m else out[:60]} ({exe})")


# ------------------------------------------------------------------ optional
def check_remotion_browser(os_name: str) -> Check:
    enables = "preview and render without a one-time browser download on first use"
    base = renderer_dir() / "node_modules" / ".remotion"
    found = sorted(p for p in base.glob("*/*/*/*") if p.name in REMOTION_SHELLS) if base.is_dir() else []
    if found:
        try:
            version = " " + (found[0].parents[2] / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            version = ""
        return Check("remotion-browser", True, False, f"Chrome Headless Shell{version} ({found[0]})", enables=enables)
    return Check("remotion-browser", False, False, "not downloaded yet: the first preview or render downloads it "
                                                   "(a few hundred MB unpacked)",
                 in_folder(renderer_dir(), f"{npm(os_name, 'npx')} remotion browser ensure", os_name), enables)


def chromium_browsers(os_name: str) -> list[str]:
    """Browsers capture can drive (its Playwright channels: msedge, chrome, then Playwright's own Chromium)."""
    env = os.environ
    home = Path.home()
    if os_name == "windows":
        bases = [env.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        places = {"Microsoft Edge": [Path(b, "Microsoft", "Edge", "Application", "msedge.exe") for b in bases if b],
                  "Google Chrome": [Path(b, "Google", "Chrome", "Application", "chrome.exe") for b in bases if b]}
        cache = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "ms-playwright"
    elif os_name == "macos":
        apps = [Path("/Applications"), home / "Applications"]
        places = {"Microsoft Edge": [a / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge" for a in apps],
                  "Google Chrome": [a / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome" for a in apps]}
        cache = home / "Library" / "Caches" / "ms-playwright"
    else:
        places = {"Microsoft Edge": [Path("/opt/microsoft/msedge/msedge")],
                  "Google Chrome": [Path("/opt/google/chrome/chrome")]}
        cache = Path(env.get("XDG_CACHE_HOME") or home / ".cache") / "ms-playwright"
    found = [f"{name} ({path})" for name, paths in places.items() for path in paths if path.is_file()]
    pinned = env.get("PLAYWRIGHT_BROWSERS_PATH")
    if pinned and pinned != "0":
        cache = Path(pinned)
    if cache.is_dir() and any(cache.glob("chromium*-*")):
        found.append(f"Playwright's Chromium ({cache})")
    return found


def check_capture(os_name: str) -> Check:
    enables = "capture: screenshots of web pages as evidence, the proving sentence boxed"
    if not has_module("playwright"):
        return Check("capture", False, False, "the capture extra (playwright) is not installed",
                     pip_extra("capture", os_name), enables)
    try:
        version = metadata.version("playwright")
    except metadata.PackageNotFoundError:
        version = "?"
    browsers = chromium_browsers(os_name)
    if not browsers:
        return Check("capture", False, False, f"playwright {version}, but no Edge, Chrome or Playwright Chromium found",
                     program(sys.executable, ["-m", "playwright", "install", "chromium"], os_name), enables)
    return Check("capture", True, False, f"playwright {version}; {browsers[0]}", enables=enables)


def check_codex(os_name: str) -> Check:
    enables = "draw: original pictures through Codex image generation, on the user's Codex sign-in"
    from .providers.draw import find_codex
    path = find_codex()
    if path:
        return Check("codex", True, False, f"Codex CLI at {path} (the user signs in once with `codex login`)",
                     enables=enables)
    return Check("codex", False, False, "the Codex CLI was not found (CODEX_EXE, the desktop app, PATH); after the "
                                        "install the user signs in once with `codex login` (it opens a browser)",
                 f"{npm(os_name)} install -g @openai/codex", enables)


def check_whisper(os_name: str) -> Check:
    enables = ('transcribe on this machine, free (workspace.json providers.transcribe.provider "local"; the first '
               "run downloads a model); without it transcribe uses an API endpoint")
    if has_module("faster_whisper"):
        return Check("faster-whisper", True, False, "faster-whisper is installed", enables=enables)
    return Check("faster-whisper", False, False, "the transcribe extra (faster-whisper) is not installed",
                 pip_extra("transcribe", os_name), enables)


def check_on_path(os_name: str) -> Check:
    enables = "the Claude Code and DSH plugins, which start reelsmith-mcp from PATH (reelsmith setup does not need it)"
    found = which("reelsmith-mcp")
    if found:
        return Check("on-path", True, False, f"reelsmith-mcp on PATH ({found})", enables=enables)
    scripts = Path(sysconfig.get_path("scripts"))
    return Check("on-path", False, False, f"reelsmith-mcp is not on PATH (it is in {scripts}): the fix adds that "
                                          "folder to the user's PATH (ask first); the agent sees it once restarted "
                                          "from a new terminal", add_to_path(scripts, os_name), enables)


def add_to_path(folder, os_name: str) -> str:
    """A user-level PATH change: no admin rights, no execution policy, and it outlives this shell (activating a venv
    in the agent's own shell reaches neither the running agent nor the next one)."""
    if os_name == "windows":
        return ("[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') "
                f"+ {quote(';' + str(folder), os_name)}, 'User')")
    shell = Path(os.environ.get("SHELL", "")).name
    rc = {"zsh": "~/.zshrc", "bash": "~/.bash_profile" if os_name == "macos" else "~/.bashrc"}.get(shell)
    if not rc:
        return f"add {folder} to PATH in the shell's startup file"
    line = f'export PATH={shlex.quote(str(folder))}:"$PATH"'
    return f"echo {shlex.quote(line)} >> {rc}"


# ------------------------------------------------------------------ workspace, keys, agents
def find_workspace_root(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / WORKSPACE_FILE).is_file():
            return folder
    return None


def copy_starter(dest, os_name: str) -> str:
    src = ROOT / "examples" / "workspace"
    if os_name == "windows":
        return (f"New-Item -ItemType Directory -Force {quote(dest, os_name)} | Out-Null; "
                f"Copy-Item -Recurse -Force {quote(src / '*', os_name)} {quote(dest, os_name)}")
    return f"mkdir -p {quote(dest, os_name)} && cp -R {quote(f'{src}/.', os_name)} {quote(f'{dest}/', os_name)}"


def check_workspace(ws: Path | None, named: bool, cwd: Path, os_name: str) -> Check:
    if ws is None or not (ws / WORKSPACE_FILE).is_file():
        where = ws if ws is not None else "<folder>"
        detail = (f"{ws} holds no {WORKSPACE_FILE}" if ws is not None
                  else f"no {WORKSPACE_FILE} at or above {cwd}; pass --workspace DIR to check one")
        return Check("workspace", False, named, detail, copy_starter(where, os_name),
                     "" if named else "projects with the workspace's settings, rules, keys, library and notes")
    try:
        loaded = Workspace.load(ws)
    except WorkspaceError as exc:
        return Check("workspace", False, named, f"{ws}: {exc}", f"fix {ws / WORKSPACE_FILE} (or rules.json) as "
                                                                "the message says")
    env = "a .env" if (ws / ENV_FILE).is_file() else "no .env yet (keys are optional)"
    profile = loaded.config.get("profile") or "landscape"
    return Check("workspace", True, named, f"{ws}: profile {profile if isinstance(profile, str) else 'custom'}, "
                                           f"locale {loaded.locale or 'en'}, {env}",
                 enables="" if named else "projects with the workspace's settings, rules, keys, library and notes")


def key_names(ws: Path | None) -> dict[str, str]:
    """The keys reelsmith reads, plus any the workspace names in a key_env setting."""
    names = dict(KEYS)
    try:
        config = json.loads((ws / WORKSPACE_FILE).read_text(encoding="utf-8-sig")) if ws else {}
    except (OSError, ValueError):
        config = {}
    providers = config.get("providers") if isinstance(config, dict) else None
    sources = [(f"providers.{k}", v) for k, v in (providers or {}).items() if isinstance(v, dict)]
    runner = config.get("runner") if isinstance(config, dict) else None
    if isinstance(runner, dict):
        sources.append(("runner", runner))
    for where, section in sources:
        name = section.get("key_env")
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name not in names:
            names[name] = f"named by workspace.json {where}.key_env"
    return names


def check_keys(ws: Path | None, os_name: str) -> list[Check]:
    dotenv = ws / ENV_FILE if ws else None
    stored = parse_dotenv(dotenv.read_text(encoding="utf-8-sig")) if dotenv and dotenv.is_file() else {}
    rows = []
    for name, enables in key_names(ws).items():
        if stored.get(name):
            rows.append(Check(f"key:{name}", True, False, f"set in {dotenv}", enables=enables))
        elif os.environ.get(name):
            rows.append(Check(f"key:{name}", True, False, "set in the environment only (some agents do not pass it "
                                                          "to MCP servers: the workspace .env is safer)",
                              enables=enables))
        else:
            target = dotenv or Path("<workspace>", ENV_FILE)
            rows.append(Check(f"key:{name}", False, False, "absent (optional)",
                              f"the user adds the line {name}=<key> to {target} (never through the chat)", enables))
    return rows


def _agent_command(path: Path) -> str | None:
    """The command of the reelsmith server an agent config holds; None when it holds none."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    if path.suffix == ".json":
        try:
            server = (json.loads(text).get("mcpServers") or {}).get("reelsmith")
        except (ValueError, AttributeError):
            return None
        return str(server.get("command") or "") if isinstance(server, dict) else None
    if path.suffix == ".toml":
        m = re.search(r"(?ms)^\s*\[mcp_servers\.\"?reelsmith\"?\]\s*$(.*?)(?=^\s*\[|\Z)", text)
        if not m:
            return None
        cmd = re.search(r'(?m)^\s*command\s*=\s*("(?:[^"\\]|\\.)*")', m.group(1))
        return json.loads(cmd.group(1)) if cmd else ""
    cmd = re.search(r'(?m)^\s*command:\s*("(?:[^"\\]|\\.)*")', text)
    return json.loads(cmd.group(1)) if cmd else ""


def check_agents(folders: list[Path], os_name: str) -> Check:
    """Agent configs in this folder and in the workspace folder (where the setup guide attaches the agent)."""
    enables = "the reelsmith tools inside a coding agent started in the folder it is set up in"
    setup = reelsmith_command(os_name)
    found, broken, fixes = [], [], []
    for folder in folders:
        good = []
        for agent, rel in AGENT_CONFIGS:
            command = _agent_command(folder / rel)
            if command is None:
                continue
            if command and (os.path.isfile(command) or which(command)):
                same = os.path.normcase(os.path.abspath(command)) == os.path.normcase(os.path.abspath(sys.executable))
                good.append(f"{agent} ({rel})" + ("" if same or not os.path.isabs(command) else f", runs {command}"))
            else:
                broken.append(f"{agent} ({folder / rel}) runs {command or '(no command)'}, which is missing")
                fixes.append(in_folder(folder, f"{setup} setup {agent}", os_name))
        if good:
            found.append(f"set up in {folder}: {', '.join(good)}")
    if broken:
        return Check("agents", False, False, "; ".join([*found, *broken]), then(os_name).join(fixes), enables)
    if found:
        return Check("agents", True, False, "; ".join(found), enables=enables)
    return Check("agents", False, False, f"no coding agent in {' or '.join(map(str, folders))} has reelsmith set up "
                                         "(<agent>: claude-code, codex, dsh, cursor or generic; run it in the folder "
                                         "the agent starts in)", f"{setup} setup <agent>", enables)


# ------------------------------------------------------------------ report
def run_checks(workspace=None, cwd=None, os_name: str | None = None) -> dict:
    """Every check, as one JSON-ready report; `ok` is True when every required check passes."""
    os_name = os_name or system()
    cwd = Path(os.path.abspath(cwd or os.getcwd()))
    named = workspace is not None and str(workspace).strip() != ""
    ws = Path(os.path.abspath(cwd / Path(workspace).expanduser())) if named else find_workspace_root(cwd)
    folders = [cwd]
    if ws is not None and ws.is_dir() and os.path.normcase(str(ws)) != os.path.normcase(str(cwd)):
        folders.append(ws)
    checks = [check_python(os_name), check_checkout(os_name), check_node(os_name), check_renderer(os_name),
              check_ffmpeg("ffmpeg", os_name), check_ffmpeg("ffprobe", os_name),
              check_workspace(ws, named, cwd, os_name),
              check_remotion_browser(os_name), check_capture(os_name), check_codex(os_name), check_whisper(os_name),
              *check_keys(ws if ws is not None and (ws / WORKSPACE_FILE).is_file() else None, os_name),
              check_agents(folders, os_name), check_on_path(os_name)]
    return {"ok": all(c.ok for c in checks if c.required), "reelsmith": __version__, "system": os_name,
            "python": sys.executable, "checkout": str(ROOT), "renderer": str(renderer_dir()),
            "workspace": str(ws) if ws is not None else None, "cwd": str(cwd),
            "checks": [asdict(c) for c in checks]}


def table(report: dict) -> str:
    rows = report["checks"]
    width = max(len(r["name"]) for r in rows)
    lines = [f"reelsmith doctor: {report['system']}, reelsmith {report['reelsmith']}, checkout {report['checkout']}"]
    for r in rows:
        mark = "ok" if r["ok"] else "FAIL" if r["required"] else "-"
        lines.append(f"  {mark:<4}  {r['name']:<{width}}  {r['detail']}")
        if not r["ok"] and r["enables"]:
            lines.append(f"        {'':<{width}}  enables: {r['enables']}")
        if not r["ok"] and r["fix"]:
            lines.append(f"        {'':<{width}}  fix: {r['fix']}")
    failed = [r["name"] for r in rows if r["required"] and not r["ok"]]
    lines.append("All required checks pass." if not failed else
                 f"{len(failed)} required check(s) failed: {', '.join(failed)}. Run each fix, then reelsmith doctor "
                 "again.")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith doctor", description=(
        "Check what reelsmith needs on this machine and what each optional tool needs. Local checks only: no network, "
        "no model calls, nothing installed. Exit status 0 when every required check passes, 1 otherwise."))
    ap.add_argument("--json", action="store_true", help="one JSON object instead of the table")
    ap.add_argument("--workspace", help="the workspace folder to check (default: the nearest workspace.json at or "
                                        "above this folder)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = run_checks(args.workspace)
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else table(report))
    return 0 if report["ok"] else 1
