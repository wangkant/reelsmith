"""The runner's PreToolUse guard: file tools stay inside the workspace, there is no shell, secrets stay unreadable.

decide(tool_name, tool_input, scope) -> (allowed, reason) touches the file system only to look (realpath, samefile),
so it is tested with a table; make_hook(scope) wraps it for the Claude Agent SDK.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

MCP_PREFIX = "mcp__reelsmith__"

# Never read, never written, in any folder: keys, credentials, tool configs, the spend ledger.
_SECRET_PART = re.compile(r"^(\.env.*|\.ssh|\.aws|\.git|\.npmrc|\.pypirc|\.netrc|\.codex|\.claude|credentials.*"
                          r"|auth\.json|.*\.pem|.*\.key|ledger\.jsonl)$", re.I)
_GLOB = re.compile(r"[*?\[\]{}]")
_CONTROL = re.compile(r"[\x00-\x1f]")
# Names Windows opens as a device: CON, NUL.txt, COM1 ...
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|COM[0-9\u00b9\u00b2\u00b3]|LPT[0-9\u00b9\u00b2\u00b3])$",
                     re.I)
# Nothing the session writes may be something a later process runs (the MCP server, node, a shell).
_SCRIPT_EXT = (".py", ".pyc", ".pyw", ".pth", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".exe", ".dll", ".pyd", ".so", ".sh",
               ".lnk", ".url", ".reg", ".scr", ".com", ".msi", ".cpl", ".hta", ".jar")
_SCRIPT_NAMES = {"package.json", "package-lock.json", "node_modules"}
_PLATFORM_DIRS = (".history", "build", "out")
_OWNER_FILES = ("workspace.json", "rules.json")
# find_workspace takes the nearest folder holding workspace.json: one written into the project would replace the
# owner's rules, budget and ledger, so these names are refused anywhere the session writes
_OWNER_NAMES = re.compile(r"^(workspace\.json|rules\.json|\.env.*|ledger\.jsonl.*)$", re.I)

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SESSION_TOOLS = {"WebSearch", "TodoWrite", "ToolSearch"}
SHELL_TOOLS = {"Bash", "PowerShell", "BashOutput", "KillShell", "KillBash", "TaskOutput", "TaskStop", "Monitor"}
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode", "EnterPlanMode"}
# MCP argument keys whose string values may name files or URLs (asset ids, Times and dotted paths have no slash)
_PATH_KEYS = {"path", "file", "file_path", "source", "src", "dir", "folder", "out", "output", "out_dir"}
_URL_KEYS = {"url", "href"}

NO_SHELL = ("There is no shell in this run. Render, preview, check and type-check with the reelsmith tools; "
            "read and change files with Read/Write/Edit/Glob/Grep.")
NOBODY = "Nobody is online to answer: decide yourself and write the reason in script.md."
SECRET = "Keys, credentials and the spend ledger are off limits"


def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _real(path) -> str:
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return _norm(path)


def inside(path, dirs, strict: bool = False) -> bool:
    """path is one of dirs (unless strict) or below one of them, compared as normalized strings."""
    if path is None:
        return False
    p = _norm(path)
    for d in dirs:
        d = _norm(d)
        if (p == d and not strict) or p.startswith(d.rstrip("\\/") + os.sep):
            return True
    return False


def _contained(path, roots, strict: bool = False) -> bool:
    """Inside by name and by real location, so a symlink or junction cannot lead out."""
    return inside(path, roots, strict) and inside(_real(path), [_real(r) for r in roots], strict)


def _below(path, root) -> str | None:
    """path relative to root ('' for root itself), or None when it is not under root."""
    p, r = _norm(path), _norm(root)
    if p == r:
        return ""
    prefix = r.rstrip("\\/") + os.sep
    return p[len(prefix):] if p.startswith(prefix) else None


def _secret(text) -> bool:
    return any(_SECRET_PART.match(part) for part in re.split(r"[\\/]", str(text)) if part)


def _is_absolute_like(text: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:|[\\/]|~)", str(text)))


@dataclass
class Scope:
    """What one run may touch. Writes: the project and the workspace library. Reads: the workspace, the reelsmith
    manual and renderer source, and the CLI's spill files for long tool results."""
    project: Path
    workspace: Path | None = None
    library: list[Path] = field(default_factory=list)
    ledger: Path | None = None
    extra_read: list[Path] = field(default_factory=list)
    spill: Path | None = None

    @property
    def cwd(self) -> Path:
        return self.project

    @property
    def home(self) -> Path:
        return self.workspace or self.project

    @property
    def write_roots(self) -> list[Path]:
        return [self.project, *self.library]

    @property
    def read_roots(self) -> list[Path]:
        return [self.home, *self.library, *self.extra_read]

    @property
    def platform_dirs(self) -> list[Path]:
        return [self.project / d for d in _PLATFORM_DIRS]

    @property
    def owner_files(self) -> list[Path]:
        return [self.home / f for f in _OWNER_FILES] + [self.home / ".cache"]

    def _roots(self) -> list[Path]:
        return [*self.read_roots, *self.write_roots, *([self.spill] if self.spill else [])]

    def secret_in_scope(self, path) -> bool:
        """A secret name below any of our roots, by the path as given or by its real location."""
        roots = self._roots()
        for candidate, rts in ((path, roots), (_real(path), [_real(r) for r in roots])):
            for root in rts:
                rel = _below(candidate, root)
                if rel and _secret(rel):
                    return True
        return False

    def hidden_files(self) -> list[Path]:
        """Existing secret files near the work, compared by identity (a hard link has another name)."""
        found = {self.ledger} if self.ledger else set()
        for base in {self.home, self.project, *self.library}:
            try:
                found.update(p for p in Path(base).glob(".env*") if p.is_file())
            except OSError:
                pass
            found.add(Path(base) / "ledger.jsonl")
        return [p for p in found if p is not None and p.is_file()]

    def is_hidden(self, path) -> bool:
        try:
            if not Path(path).is_file():
                return False
            return any(os.path.samefile(path, h) for h in self.hidden_files())
        except OSError:
            return True

    def covers_hidden(self, root) -> bool:
        """A recursive search under root would read a secret file."""
        return any(inside(h, [root], strict=True) or inside(_real(h), [_real(root)], strict=True)
                   for h in self.hidden_files())

    def readable(self, path) -> bool:
        if path is None:
            return False
        cache = self.home / ".cache"           # draw.log holds Codex's raw words; caches are not the session's
        if inside(path, [cache]) or inside(_real(path), [_real(cache)]):
            return False
        if _contained(path, self.read_roots):
            return True
        # the CLI spills a long tool result to <projects>/<cwd key>/<session>/tool-results/<file> and asks for a Read
        if self.spill is not None and _contained(path, [self.spill], strict=True):
            rest = _below(path, self.spill).split(os.sep)
            return len(rest) >= 3 and rest[1] == "tool-results"
        return False

    def describe_reads(self) -> str:
        return ", ".join(str(r) for r in self.read_roots)

    def describe_writes(self) -> str:
        return ", ".join(str(r) for r in self.write_roots)


def scope_for(project, workspace=None, extra_read=(), spill=None) -> Scope:
    """The Scope of a run on project, given a Workspace (or None for a project outside any workspace)."""
    project = Path(os.path.abspath(project))
    extra = [Path(os.path.abspath(p)) for p in extra_read]
    if workspace is None:
        return Scope(project, extra_read=extra, spill=spill)
    root = Path(os.path.abspath(workspace.root))
    library = [root / "library"]
    own = getattr(workspace, "library_dir", None)
    if own and not inside(own, library):
        library.append(Path(os.path.abspath(own)))
    ledger = getattr(workspace, "ledger_path", None) or root / "ledger.jsonl"
    return Scope(project, root, library, Path(os.path.abspath(ledger)), extra, spill)


def resolve_token(token, cwd) -> Path | None:
    """An absolute normalized path, or None for places that are never ours (~user, C:rel, a leading backslash, and
    on Windows driveless roots and UNC)."""
    p = str(token)
    if p.startswith("~"):
        if p != "~" and not p.startswith(("~/", "~\\")):
            return None
        p = os.path.expanduser(p)
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(?:/(.*))?$", p)      # an MSYS path: /c/work is C:/work
        if m:
            p = f"{m.group(1).upper()}:/{m.group(2) or ''}"
        elif p.startswith(("/", "\\")):
            return None
    elif p.startswith("\\"):
        return None
    path = Path(p)
    if not path.is_absolute():
        if re.match(r"^[A-Za-z]:", p):                   # C:foo is relative to drive C's own cwd
            return None
        path = Path(cwd) / path
    return Path(os.path.normpath(str(path)))


def alias_name(text) -> str:
    """The first path component Windows would not take at face value ('x.', 'x ', 'x::$DATA', NUL, PROGRA~1), or ''."""
    text = str(text)
    drive = re.match(r"^[A-Za-z]:(?=[\\/]|$)", text)
    rest = text[drive.end():] if drive else text
    for part in re.split(r"[\\/]", rest):
        if part in ("", ".", ".."):
            continue
        if ":" in part or part[-1] in ". " or _DEVICE.match(part.split(".")[0].rstrip(" ")) \
                or re.search(r"~\d", part):
            return part
    return ""


def _script(path: Path) -> bool:
    name = path.name.lower()
    return (name.endswith(_SCRIPT_EXT) or name in _SCRIPT_NAMES
            or any(part.lower() == "node_modules" for part in path.parts))


def _plain(tok: str) -> str:
    """'' when the token is a plain path string, else the reason."""
    if _CONTROL.search(tok):
        return f"Control characters in the path: {tok!r}"
    if not _is_absolute_like(tok) and _secret(tok):
        return f"{SECRET}: {tok}"
    if _GLOB.search(tok):
        return f"No wildcards or brackets in a path (use Glob to find files): {tok}"
    bad = alias_name(tok)
    if bad:
        return (f"'{bad}' is not a plain file name (colons, a trailing dot or space, device names like CON/NUL "
                f"and ~1 short names are refused): {tok}")
    return ""


def check_path(tok, scope: Scope, mode: str) -> str:
    """'' when the session may `mode` ('read' or 'write') the path, else the reason."""
    tok = str(tok or "")
    if not tok.strip():
        return "Missing path."
    why = _plain(tok)
    if why:
        return why
    path = resolve_token(tok, scope.cwd)
    if path is None:
        return f"Only paths inside the workspace ({scope.describe_reads()}): {tok}"
    if scope.secret_in_scope(path) or scope.is_hidden(path):
        return f"{SECRET}: {tok}"
    if mode == "write":
        return _check_write(tok, path, scope)
    if not scope.readable(path):
        return f"Cannot read {tok}: reads stay inside {scope.describe_reads()}."
    return ""


def _check_write(tok: str, path: Path, scope: Scope) -> str:
    if not _contained(path, scope.write_roots, strict=True):
        return f"Writes go to the project or the workspace library only ({scope.describe_writes()}): {tok}"
    if inside(path, scope.platform_dirs) or inside(_real(path), [_real(d) for d in scope.platform_dirs]):
        return (f"{tok} is written by reelsmith itself (.history by edit/undo, build/ and out/ by preview/render "
                "and the runner): use the tools.")
    if inside(path, scope.owner_files) or inside(_real(path), [_real(f) for f in scope.owner_files]) \
            or _OWNER_NAMES.match(path.name):
        return f"{tok} holds the owner's settings and rules: it is read-only for the session."
    if _script(path):
        return (f"Scripts, executables and package files cannot be written: {tok}. Write media, text, JSON and "
                "components (.tsx/.ts) only.")
    return ""


def check_url(url) -> str:
    """'' for a public http(s) URL; local and private network addresses are refused."""
    u = str(url or "").strip()
    if not u:
        return "Missing url."
    try:
        parts = urlsplit(u)
        host = (parts.hostname or "").rstrip(".").lower()
    except ValueError:
        return f"Not a valid URL: {u}"
    if parts.scheme.lower() not in ("http", "https"):
        return f"Only http(s) URLs: {u}"
    if parts.username or parts.password:
        return f"No credentials in URLs: {u}"
    if not host:
        return f"No host in the URL: {u}"
    if (host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
            or ("." not in host and ":" not in host)):
        return f"Local network addresses are off limits: {u}"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if all(re.fullmatch(r"0x[0-9a-f]*|[0-9]+", label) for label in host.split(".")):
            return f"Numeric hosts must be a plain public IP: {u}"
        return ""
    mapped = getattr(ip, "ipv4_mapped", None)
    if not ip.is_global or (mapped is not None and not mapped.is_global):
        return f"Local network addresses are off limits: {u}"
    return ""


def _searchable(root, scope: Scope) -> str:
    if root is None or not _contained(root, scope.read_roots):
        return f"Cannot search there: {root}. Search inside {scope.describe_reads()}."
    if scope.secret_in_scope(root):
        return f"{SECRET}: {root}"
    return ""


def check_glob(inp: dict, scope: Scope) -> str:
    pattern = str(inp.get("pattern") or "")
    if not pattern:
        return "Missing pattern."
    if _CONTROL.search(pattern):
        return f"Control characters in the pattern: {pattern!r}"
    base = str(inp.get("path") or "") or "."
    if inp.get("path"):
        why = _plain(base)
        if why:
            return f"path must be a plain folder: {why}"
    segs = re.split(r"[\\/]", pattern)
    first = next((i for i, s in enumerate(segs) if _GLOB.search(s)), None)
    if first is None:                   # no wildcard: the pattern names one file
        return check_path(pattern if _is_absolute_like(pattern) else os.path.join(base, pattern), scope, "read")
    if _secret("/".join(segs[first:])):
        return f"{SECRET}: {pattern}"
    if alias_name("/".join(segs[:first])):
        return f"The pattern has a part that is not a plain file name: {pattern}"
    if ".." in segs[first:]:
        return f"No .. after a wildcard: {pattern}"
    lead = "/".join(segs[:first])
    if not _is_absolute_like(pattern) and _secret(lead):
        return f"{SECRET}: {pattern}"
    if _is_absolute_like(pattern):
        root = resolve_token(lead or "/", scope.cwd)
    else:
        root = resolve_token(os.path.join(base, lead) if lead else base, scope.cwd)
    return _searchable(root, scope)


def check_grep(inp: dict, scope: Scope) -> str:
    target = str(inp.get("path") or "") or "."
    why = _plain(target)
    if why:
        return why
    path = resolve_token(target, scope.cwd)
    why = check_path(target, scope, "read") if path is not None and path.is_file() else _searchable(path, scope)
    if why:
        return why
    cache = scope.home / ".cache"
    if scope.covers_hidden(path) or (cache.exists() and (inside(cache, [path]) or inside(path, [cache]))):
        return (f"{target} holds files that are off limits (.env, ledger.jsonl, .cache): grep the project, its "
                "subfolders or the library instead.")
    glob = str(inp.get("glob") or "")
    if glob and (".." in re.split(r"[\\/]", glob) or _is_absolute_like(glob)):
        return f"glob filters file names only (like *.tsx): {glob}"
    if glob and _secret(glob):
        return f"{SECRET}: {glob}"
    return ""


def _strings(value, key=""):
    """(key, string) for every string under value, at any depth; a JSON string holding a list or object is opened."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str):
        text = value.strip()
        if text[:1] in ("[", "{"):
            try:
                yield from _strings(json.loads(text), key)
                return
            except ValueError:
                pass
        yield key, value


def _same_project(value, scope: Scope) -> bool:
    if not isinstance(value, str) or not value.strip() or _CONTROL.search(value) or alias_name(value):
        return False
    path = resolve_token(value, scope.cwd)
    return path is not None and (_norm(path) == _norm(scope.project) or _real(path) == _real(scope.project))


def _check_mcp_value(key: str, value: str, scope: Scope) -> str:
    k, v = key.lower(), value.strip()
    if not v:                           # an empty optional field (an evidence asset's url); the tool validates it
        return ""
    if k in _URL_KEYS:
        return check_url(v)
    if k not in _PATH_KEYS:
        return ""
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]+):", v)     # one letter before ':' is a drive, not a scheme
    if scheme:
        if scheme.group(1).lower() in ("http", "https"):
            return check_url(v)
        return f"Only http(s) URLs or files inside the workspace: {v}"
    if "/" in v or "\\" in v or _is_absolute_like(v) or v == "..":
        return check_path(v, scope, "read")
    return ""


def check_mcp(inp: dict, scope: Scope) -> str:
    """reelsmith tools take paths and URLs too: the same limits apply, and every call works on this run's project."""
    if "project" in inp and not _same_project(inp.get("project"), scope):
        return f"This run works on one project: pass project={scope.project}"
    for key, value in _strings({k: v for k, v in inp.items() if k != "project"}):
        why = _check_mcp_value(key, value, scope)
        if why:
            return f"{key}: {why}"
    return ""


def decide(tool_name: str, tool_input, scope: Scope) -> tuple[bool, str]:
    """(allowed, reason). Default deny: a tool this function does not know is refused."""
    name = str(tool_name or "")
    inp = tool_input if isinstance(tool_input, dict) else {}
    if name.startswith(MCP_PREFIX):
        why = check_mcp(inp, scope)
    elif name in SESSION_TOOLS:
        why = ""
    elif name == "WebFetch":
        why = check_url(inp.get("url"))
    elif name in WRITE_TOOLS:
        target = inp.get("file_path") or inp.get("notebook_path")
        why = check_path(target, scope, "write") if target else "Missing file_path."
    elif name == "Read":
        why = check_path(inp.get("file_path"), scope, "read") if inp.get("file_path") else "Missing file_path."
    elif name == "Glob":
        why = check_glob(inp, scope)
    elif name == "Grep":
        why = check_grep(inp, scope)
    elif name in SHELL_TOOLS:
        why = NO_SHELL
    elif name in ASK_TOOLS:
        why = NOBODY
    elif name.startswith("mcp__"):
        why = "Only the reelsmith MCP server is connected in this run."
    else:
        why = (f"{name or 'This tool'} is not available in this run: use the reelsmith tools, "
               "Read/Write/Edit/Glob/Grep and WebSearch/WebFetch.")
    return not why, why


def brief_input(name: str, inp) -> str:
    """One short line naming what a tool call touched, for logs."""
    inp = inp if isinstance(inp, dict) else {}
    for key in ("file_path", "notebook_path", "url", "query", "pattern", "path", "id", "project"):
        if inp.get(key):
            return str(inp[key])[:160]
    return json.dumps(inp, ensure_ascii=False, default=str)[:160]


def make_hook(scope: Scope, on_deny=None):
    """The SDK PreToolUse callback. It fails closed: an error inside the guard denies the call."""
    async def hook(input_data, tool_use_id, context):
        data = input_data if isinstance(input_data, dict) else {}
        name = str(data.get("tool_name") or "")
        inp = data.get("tool_input") or {}
        try:
            allowed, why = decide(name, inp, scope)
        except Exception as exc:  # noqa: BLE001
            allowed, why = False, f"The guard failed on this call ({type(exc).__name__}): try another way."
        if not allowed and on_deny is not None:
            on_deny(name, brief_input(name, inp), why)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "allow" if allowed else "deny",
                                       "permissionDecisionReason": "reelsmith guard" if allowed else why}}
    return hook
