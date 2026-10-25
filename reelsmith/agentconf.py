"""reelsmith setup <target>: attach the reelsmith MCP server and the reelsmith skill to a coding agent's own config.

Each target plans its changes first (plan() -> Plan), so `--print` shows exactly what a run would write. Config files
are merged, never replaced: other servers, keys and comments stay as they are, and running setup twice changes
nothing. Formats (checked against each agent's docs, 2026-10): Claude Code `.mcp.json` / `.claude/skills`; Codex
`.codex/config.toml` `[mcp_servers.*]` / `.agents/skills`; DeepSeek Harness cordis patch rows of
`@deepseek-ai/dsh-mcp-client` / `.dsh/skills`; Cursor `.cursor/mcp.json` / `.cursor/skills`.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_SOURCE = ROOT / "skills" / "reelsmith" / "SKILL.md"
NAME = "reelsmith"
TARGETS = ("claude-code", "codex", "dsh", "cursor", "generic")
TOOL_TIMEOUT_S = 3600           # one render call may take many minutes
STARTUP_TIMEOUT_S = 60
# Codex hands an MCP server a minimal environment: the names the tools read from it are forwarded
CODEX_ENV_VARS = ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "REELSMITH_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
                  "CODEX_EXE", "CODEX_HOME", "REELSMITH_BUDGET_USD", "REELSMITH_MIN_BALANCE_USD", "REELSMITH_RENDERER"]
DSH_BEGIN = "# >>> reelsmith (managed by `reelsmith setup dsh`)"
DSH_END = "# <<< reelsmith"
DSH_PROJECT_PATCH = Path(".dsh") / "reelsmith.cordis.yml"

INSTRUCTIONS = """## Video editing with reelsmith

For any request to make or edit a video, use the reelsmith MCP tools (manual, notes, new_project, describe, edit,
check, preview, render, review, speak, import_asset, capture, draw, animate). reelsmith is an editor you drive, not
a text-to-video model: build the film clip by clip on its timeline and look at what you make.

- Call `manual` once before the first edit: it is the full contract (project format, Times, edit ops, components,
  what blocks delivery). Every tool takes `project` = the folder holding project.json.
- Loop: notes -> new_project -> script.md and assets -> edit -> check -> preview (read the PNG stills) -> fix ->
  preview with sweep=true -> render -> review -> note what you learned.
- speak, draw and animate may cost money; they estimate first and refuse over the budget.
"""


class SetupError(Exception):
    """A config that setup cannot merge into safely; nothing was changed."""


@dataclass
class Change:
    path: Path | None
    action: str                         # write | remove | run
    content: str | None = None
    command: list[str] | None = None
    allow_fail: bool = False
    what: str = ""


@dataclass
class Plan:
    target: str
    uninstall: bool = False
    changes: list[Change] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def idle(self) -> list[str]:
        """The line for a plan with nothing to do."""
        if self.changes or self.target == "generic":
            return []
        return ["nothing to remove: reelsmith is not set up here" if self.uninstall
                else "nothing to change: already set up"]


def server_spec(root=None, python=None) -> dict:
    """The stdio server every target gets: this interpreter (not resolved: a venv's python is often a symlink)
    running the reelsmith MCP server, kept off the agent's cwd for imports."""
    env = {"PYTHONSAFEPATH": "1"}
    if root:
        env["REELSMITH_ROOT"] = os.path.abspath(str(root))
    return {"command": os.path.abspath(str(python or sys.executable)), "args": ["-m", "reelsmith.mcp_server"],
            "env": env}


def skill_text() -> str:
    try:
        return SKILL_SOURCE.read_text(encoding="utf-8")
    except OSError as exc:
        raise SetupError(f"the reelsmith skill is missing ({SKILL_SOURCE}): reinstall reelsmith from its checkout "
                         f"({exc})") from None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SetupError(f"cannot read {path}: {exc}") from None


def _write_change(path: Path, new: str, what: str) -> Change | None:
    """A write when the file would change, else None (setup is idempotent)."""
    return None if _read(path) == new else Change(path, "write", new, what=what)


# ------------------------------------------------------------------ skill
def skill_changes(base: Path, uninstall: bool) -> list[Change]:
    target = base / NAME / "SKILL.md"
    if uninstall:
        return [Change(target, "remove", what="the reelsmith skill")] if target.exists() else []
    change = _write_change(target, skill_text(), "the reelsmith skill")
    return [change] if change else []


# ------------------------------------------------------------------ JSON (.mcp.json, .cursor/mcp.json)
def _json_doc(path: Path) -> dict:
    text = _read(path)
    if text is None or not text.strip():
        return {}
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc}): fix or move it, then run setup again") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("mcpServers") or {}, dict):
        raise SetupError(f'{path} is not an object with an "mcpServers" object: fix or move it')
    return doc


def json_server_change(path: Path, entry: dict, uninstall: bool) -> Change | None:
    """Set or drop mcpServers.reelsmith, keeping every other key and server."""
    doc = _json_doc(path)
    servers = dict(doc.get("mcpServers") or {})
    if uninstall:
        if NAME not in servers:
            return None
        servers.pop(NAME)
        doc["mcpServers"] = servers
        if not servers and set(doc) == {"mcpServers"}:
            return Change(path, "remove", what="the MCP config (reelsmith was its only server)")
        return Change(path, "write", json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                      what="the MCP config without reelsmith")
    servers[NAME] = entry
    doc["mcpServers"] = servers
    return _write_change(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "the MCP config")


# ------------------------------------------------------------------ TOML (Codex config.toml)
_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def toml_value(value) -> str:
    """A TOML literal for a str, bool, number, list or dict (an inline table)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)       # a JSON string is a TOML basic string
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"no TOML form for {type(value).__name__}")


def toml_key(key) -> str:
    key = str(key)
    return key if _BARE.match(key) else json.dumps(key, ensure_ascii=False)


def codex_server(spec: dict) -> dict:
    return {"command": spec["command"], "args": spec["args"], "env": spec["env"], "env_vars": CODEX_ENV_VARS,
            "startup_timeout_sec": STARTUP_TIMEOUT_S, "tool_timeout_sec": TOOL_TIMEOUT_S}


def codex_table(server: dict) -> str:
    return "\n".join([f"[mcp_servers.{NAME}]", *(f"{toml_key(k)} = {toml_value(v)}" for k, v in server.items())]) + "\n"


_HEADER = re.compile(r"^\s*\[(?!\[)(?P<name>[^\]]*)\]\s*(#.*)?$")


def _table_path(name: str) -> list[str]:
    return [p.strip().strip("\"'") for p in name.split(".")]


def strip_codex_table(text: str) -> str:
    """text without the [mcp_servers.reelsmith] table and its sub-tables."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        m = _HEADER.match(line)
        if m or line.lstrip().startswith("[["):
            parts = _table_path(m.group("name")) if m else []
            skipping = parts[:2] == ["mcp_servers", NAME]
        if not skipping:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


def _toml_load(text: str, path: Path):
    try:
        import tomllib
    except ImportError:                             # Python 3.10: merge unchecked
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f"{path} is not valid TOML ({exc}): fix or move it, then run setup again") from None


def toml_server_change(path: Path, server: dict, uninstall: bool) -> Change | None:
    text = _read(path) or ""
    _toml_load(text, path)
    rest = strip_codex_table(text)
    left = _toml_load(rest, path)
    if left is not None and NAME in (left.get("mcp_servers") or {}):
        raise SetupError(f"{path} defines mcp_servers.{NAME} in a form setup does not edit (dotted keys or an inline "
                         f"table): remove it by hand, then run setup again")
    if uninstall:
        if rest == text:
            return None
        if not rest.strip():
            return Change(path, "remove", what="the Codex config (reelsmith was all it held)")
        return Change(path, "write", rest, what="the Codex config without reelsmith")
    body = rest.rstrip("\n")
    new = (body + "\n\n" if body else "") + codex_table(server)
    merged = _toml_load(new, path)
    if merged is not None and (merged.get("mcp_servers") or {}).get(NAME) != server:
        raise SetupError(f"{path}: the merged config does not read back as written; nothing was changed")
    return _write_change(path, new, "the Codex config")


# ------------------------------------------------------------------ YAML (DSH cordis patch)
def dsh_rows(spec: dict, timeout_s: int = TOOL_TIMEOUT_S) -> str:
    """The patch rows that mount the reelsmith server through dsh-mcp-client (JSON scalars are YAML)."""
    j = lambda v: json.dumps(v, ensure_ascii=False)   # noqa: E731
    return "\n".join([
        "- insert:",
        "    - id: mcp-reelsmith",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        f"        serverName: {NAME}",
        "        transport: stdio",
        f"        command: {j(spec['command'])}",
        f"        args: {j(spec['args'])}",
        f"        env: {j(spec['env'])}",
        f"        toolCallTimeoutMs: {int(timeout_s * 1000)}",
    ]) + "\n"


def strip_dsh_block(text: str) -> str:
    out, inside = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == DSH_BEGIN:
            inside = True
            continue
        if inside:
            inside = line.strip() != DSH_END
            continue
        out.append(line)
    return "".join(out)


def _yaml_list_ok(text: str) -> bool:
    """The patch file is empty, comments only, or a block list of rows (what cordis patches are)."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return not lines or lines[0].startswith("-") or (len(lines) == 1 and lines[0].strip() == "[]")


def yaml_block_change(path: Path, rows: str, uninstall: bool) -> Change | None:
    text = _read(path) or ""
    rest = strip_dsh_block(text)
    if uninstall:
        if rest == text:
            return None
        if not rest.strip():
            return Change(path, "remove", what="the DSH patch (reelsmith was all it held)")
        return Change(path, "write", rest, what="the DSH patch without reelsmith")
    if not _yaml_list_ok(rest):
        raise SetupError(f"{path} is not a YAML list of patch rows: add the reelsmith rows by hand "
                         "(reelsmith setup dsh --print shows them)")
    if [ln.strip() for ln in rest.splitlines() if ln.strip() and not ln.lstrip().startswith("#")] == ["[]"]:
        rest = re.sub(r"(?m)^\s*\[\]\s*$\n?", "", rest)
    body = rest.rstrip("\n")
    new = (body + "\n\n" if body else "") + f"{DSH_BEGIN}\n{rows}{DSH_END}\n"
    return _write_change(path, new, "the DSH patch")


# ------------------------------------------------------------------ targets
def _git_root(start: Path) -> Path:
    """The nearest folder at or above start holding .git (DSH resolves project skills there), else start."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return start


def _claude_exe() -> str | None:
    return shutil.which("claude")


def _fence(base: Path, *paths: Path) -> None:
    """Refuse a project-level path that a symlink or junction below base sends elsewhere: a checkout can carry
    one (.codex -> ~/.codex), and setup would then write or remove the file it leads to."""
    real_base = os.path.realpath(base)
    for path in paths:
        try:
            parts = path.relative_to(base).parts
        except ValueError:
            raise SetupError(f"{path} is outside {base}") from None
        real = os.path.realpath(path)
        if os.path.normcase(real) != os.path.normcase(os.path.join(real_base, *parts)):
            raise SetupError(f"{path} leads through a link to {real}: setup writes only inside {base}; remove the "
                             "link (or set the agent up by hand), then run setup again")


def plan(target: str, cwd=None, home=None, env=None, user: bool = False, uninstall: bool = False, root=None,
         python=None) -> Plan:
    """What `reelsmith setup <target>` would change. cwd, home and env default to the process's own."""
    target = str(target or "").strip().lower()
    if target not in TARGETS:
        raise SetupError(f'unknown target "{target}": use {", ".join(TARGETS)}')
    cwd = Path(os.path.abspath(cwd or os.getcwd()))
    home = Path(home or Path.home())
    env = os.environ if env is None else env
    spec = server_spec(root, python)
    p = Plan(target, uninstall)

    def add(*changes):
        p.changes.extend(c for c in changes if c is not None)

    def skill_dir(base: Path, *parts: str) -> Path:
        folder = base.joinpath(*parts)
        if not user:
            _fence(base, folder / NAME / "SKILL.md")
        return folder

    if target == "claude-code":
        entry = {"type": "stdio", **spec}
        if user:
            # Claude Code keeps its user config, skills included, in CLAUDE_CONFIG_DIR when that is set
            config_dir = env.get("CLAUDE_CONFIG_DIR")
            add(*skill_changes(Path(config_dir or home / ".claude") / "skills", uninstall))
            exe = _claude_exe() or "claude"
            remove = [exe, "mcp", "remove", "--scope", "user", NAME]
            add(Change(None, "run", command=remove, allow_fail=True, what="drop a previous user-scope reelsmith"))
            if not uninstall:
                add(Change(None, "run", command=[exe, "mcp", "add-json", "--scope", "user", NAME,
                                                 json.dumps(entry, ensure_ascii=False)],
                           what="add reelsmith to the user's MCP servers "
                                f"({'$CLAUDE_CONFIG_DIR' if config_dir else '~'}/.claude.json)"))
        else:
            _fence(cwd, cwd / ".mcp.json")
            add(json_server_change(cwd / ".mcp.json", entry, uninstall),
                *skill_changes(skill_dir(cwd, ".claude", "skills"), uninstall))
            if not uninstall:
                p.notes.append("Claude Code asks once to approve the project's .mcp.json servers; render can run "
                               "for minutes, so raise MCP_TOOL_TIMEOUT (ms) if its calls time out.")
    elif target == "codex":
        codex_home = Path(env.get("CODEX_HOME") or home / ".codex")
        config = codex_home / "config.toml" if user else cwd / ".codex" / "config.toml"
        if not user:
            _fence(cwd, config)
        skills = skill_dir(home if user else cwd, ".agents", "skills")
        add(toml_server_change(config, codex_server(spec), uninstall), *skill_changes(skills, uninstall))
        if not uninstall and not user:
            p.notes.append("Codex reads .codex/config.toml only in a trusted project: trust this folder when Codex "
                           "asks (or run setup with --user for every project).")
    elif target == "dsh":
        dsh_home = Path(env.get("DSH_HOME") or home / ".dsh")
        rows = dsh_rows(spec)
        if user:
            add(yaml_block_change(dsh_home / "cordis.patch.yml", rows, uninstall),
                *skill_changes(dsh_home / "skills", uninstall))
        else:
            patch = cwd / DSH_PROJECT_PATCH
            _fence(cwd, patch)
            if uninstall:
                add(Change(patch, "remove", what="the reelsmith DSH patch") if patch.exists() else None)
            else:
                # the launcher reads `dsh <profile>` only as its first word: the profile goes before --patch
                add(_write_change(patch, "# Mounts the reelsmith MCP server: dsh <profile> --patch <this file>\n"
                                  + rows, "the reelsmith DSH patch"))
                p.notes.append(f"DSH has no per-project MCP config: start it with `dsh web --patch {patch}` (or "
                               "any profile), or run `reelsmith setup dsh --user` to mount reelsmith in every profile. "
                               "The reelsmith DSH plugin package (integrations/dsh) is the richer option.")
            add(*skill_changes(skill_dir(_git_root(cwd), ".dsh", "skills"), uninstall))
    elif target == "cursor":
        base = home if user else cwd
        if not user:
            _fence(cwd, base / ".cursor" / "mcp.json")
        add(json_server_change(base / ".cursor" / "mcp.json", {"type": "stdio", **spec}, uninstall),
            *skill_changes(skill_dir(base, ".cursor", "skills"), uninstall))
    else:                                           # generic: nothing to write, everything to paste
        p.notes.append(generic_text(spec))
    return p


def generic_text(spec: dict) -> str:
    server = json.dumps({"mcpServers": {NAME: spec}}, indent=2, ensure_ascii=False)
    return (f"Paste this into your agent's instructions file:\n\n{INSTRUCTIONS}\n"
            f"MCP server (stdio; most clients take this JSON):\n\n{server}\n\n"
            f"The skill is {SKILL_SOURCE}: copy its folder to wherever your agent loads Agent Skills "
            f"(often .agents/skills/{NAME}/).")


# ------------------------------------------------------------------ apply / show
def _prune(path: Path, stop: Path) -> None:
    """Remove the empty folders setup left behind, from path up to (not including) stop."""
    for folder in path.parents:
        if folder == stop or stop not in folder.parents:
            return
        try:
            folder.rmdir()
        except OSError:
            return


def _write_atomic(path: Path, content: str) -> None:
    """Write through a fresh, exclusively created temp file (a planted link at a fixed name would be followed), then
    rename it over path, keeping an existing file's permission bits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mode = 0o666 & ~_umask()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".reelsmith-tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _umask() -> int:
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def _run(command: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def apply(p: Plan, cwd=None, home=None, run=_run) -> list[str]:
    """Carry out a plan; returns one line per change."""
    cwd = Path(os.path.abspath(cwd or os.getcwd()))
    home = Path(home or Path.home())
    lines = []
    for c in p.changes:
        if c.action == "write":
            _write_atomic(c.path, c.content)
            lines.append(f"wrote {c.path} ({c.what})")
        elif c.action == "remove":
            try:
                c.path.unlink()
            except FileNotFoundError:
                pass
            for stop in (cwd, _git_root(cwd), home):
                if stop in c.path.parents:
                    _prune(c.path, stop)
                    break
            lines.append(f"removed {c.path} ({c.what})")
        else:
            code, out = run(c.command)
            if code and not c.allow_fail:
                lines.append(f"FAILED ({code}): {_shell(c.command)}\n  {out[-500:]}\n  run it yourself once the "
                             "problem is fixed")
            elif not code:
                lines.append(f"ran {_shell(c.command)} ({c.what})")
    return lines + p.idle() + p.notes


def _shell(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else " ".join(_quote(a) for a in command)


def _quote(arg: str) -> str:
    return arg if re.fullmatch(r"[A-Za-z0-9_./:=@%+-]+", arg) else "'" + arg.replace("'", "'\"'\"'") + "'"


def show(p: Plan) -> list[str]:
    """What apply would do, file by file, without doing it."""
    lines = []
    for c in p.changes:
        if c.action == "write" and c.path.name == "SKILL.md":
            lines.append(f"would write {c.path} ({c.what}: a copy of {SKILL_SOURCE}, {len(c.content)} characters)")
        elif c.action == "write":
            lines.append(f"would write {c.path} ({c.what}):\n{c.content.rstrip()}\n")
        elif c.action == "remove":
            lines.append(f"would remove {c.path} ({c.what})")
        else:
            lines.append(f"would run {_shell(c.command)} ({c.what})")
    return lines + p.idle() + p.notes


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="reelsmith setup", description=(
        "Attach the reelsmith MCP server and skill to a coding agent. Project-level config in the current folder by "
        "default; --user for the agent's user-level config."))
    ap.add_argument("target", choices=TARGETS)
    ap.add_argument("--user", action="store_true", help="the agent's user-level config instead of this folder's")
    ap.add_argument("--print", action="store_true", dest="dry", help="show what would be written; write nothing")
    ap.add_argument("--uninstall", action="store_true", help="remove what setup added")
    ap.add_argument("--root", help="set REELSMITH_ROOT: the tools refuse projects outside this folder")
    args = ap.parse_args(argv)
    try:
        p = plan(args.target, user=args.user, uninstall=args.uninstall, root=args.root)
        lines = show(p) if args.dry else apply(p)
    except SetupError as exc:
        print(f"reelsmith setup: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 1 if any(ln.startswith("FAILED") for ln in lines) else 0
