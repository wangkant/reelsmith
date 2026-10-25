"""Function tools for the api engine: the reelsmith tools, file tools fenced by guard.py, and the web.

Each Tool carries a JSON Schema for its arguments and a run(args) -> ToolResult that never raises. The reelsmith tools
get the schemas the MCP server publishes (derived from their signatures and docstrings) and the same guard checks the
Claude engine's hook applies; the file tools are checked as Read, Write, Edit, Glob and Grep.
"""
from __future__ import annotations

import contextlib
import fnmatch
import inspect
import itertools
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import guard
from .. import tools as rtools
from ..workspace import locale_for
from . import web as W

log = logging.getLogger(__name__)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MEDIA_EXT = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga",
             ".opus", ".flac"}
READ_LINES = 2000
LINE_CHARS = 2000
READ_CHARS = 100_000
RESULT_CHARS = 100_000
GLOB_SHOWN = 200
GLOB_SCAN = 5000
GREP_SHOWN = 200
GREP_FILES = 5000
GREP_FILE_BYTES = 2 << 20
LIST_SHOWN = 500
_PRUNE_DIRS = {".git", "node_modules", "__pycache__"}
_ROOT_LOCK = threading.RLock()


@dataclass
class ToolResult:
    text: str
    images: list[Path] = field(default_factory=list)
    error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], ToolResult]

    def spec(self) -> dict:
        """The tool as a Chat Completions `tools` entry."""
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class Toolbox(list):
    """list[Tool] in the order the model sees them; `notes` say what was left out and why."""

    def __init__(self, tools=(), notes=()):
        super().__init__(tools)
        self.notes: list[str] = list(notes)

    def get(self, name: str) -> Tool | None:
        return next((t for t in self if t.name == name), None)


def _fail(text: str) -> ToolResult:
    return ToolResult(text, error=True)


def _safe(name: str, run: Callable[[dict], ToolResult]) -> Callable[[dict], ToolResult]:
    """No tool raises: a crash and a non-ToolResult come back as text."""
    def call(args) -> ToolResult:
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                return _fail(f"{name}: the arguments are not valid JSON: {args[:200]}")
        if not isinstance(args, dict):
            return _fail(f"{name}: the arguments must be a JSON object")
        try:
            result = run(args)
        except Exception as exc:  # noqa: BLE001 - the loop must get text, never an exception
            return _fail(f"{name} failed: {type(exc).__name__}: {exc}")
        if isinstance(result, ToolResult):
            return result
        return ToolResult(str(result))
    return call


def _cap(text: str, limit: int = RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [cut: {len(text) - limit} more characters]"


def _arg(args: dict, *names, default=None):
    """The first present argument of names (models used to other tool sets send file_path, old_string ...)."""
    for n in names:
        if n in args and args[n] is not None:
            return args[n]
    return default


def _int(value, what: str, default: int | None, low: int = 1) -> int | None:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number") from None
    if isinstance(value, float) and value != number:
        raise ValueError(f"{what} must be a whole number")
    if number < low:
        raise ValueError(f"{what} must be >= {low}")
    return number


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _show(path: Path, project: Path) -> str:
    try:
        return path.relative_to(project).as_posix() or "."
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ reelsmith tools
@contextlib.contextmanager
def _confined(root: Path):
    """REELSMITH_ROOT for the call, as the runner gives the MCP server: projects and imports stay inside it."""
    with _ROOT_LOCK:
        old = os.environ.get("REELSMITH_ROOT")
        os.environ["REELSMITH_ROOT"] = str(root)
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("REELSMITH_ROOT", None)
            else:
                os.environ["REELSMITH_ROOT"] = old


def _validation_text(exc) -> str:
    try:
        rows = [f"{'.'.join(str(x) for x in e.get('loc') or ()) or 'arguments'}: {e.get('msg')}"
                for e in exc.errors()]
    except Exception:  # noqa: BLE001
        rows = [str(exc)]
    return "; ".join(rows[:8])


def reelsmith_tool(name: str, fn, project: Path, scope: guard.Scope) -> Tool:
    """One reelsmith tool with the schema the MCP server publishes for it."""
    from mcp.server.mcpserver.tools import Tool as McpTool
    meta = McpTool.from_function(fn, name=name, description=inspect.cleandoc(fn.__doc__ or name),
                                 structured_output=False)
    takes_project = "project" in inspect.signature(fn).parameters

    def run(args: dict) -> ToolResult:
        args = dict(args)
        if takes_project and not args.get("project"):
            args["project"] = str(project)          # one project per run: a forgotten one is that project
        allowed, why = guard.decide(guard.MCP_PREFIX + name, args, scope)
        if not allowed:
            return _fail(why)
        if takes_project:
            args["project"] = str(project)          # the guard saw the same project: "." must not mean our cwd
        try:
            kwargs = meta.fn_metadata.validate_arguments(args)
        except Exception as exc:  # noqa: BLE001 - pydantic's ValidationError and kin
            return _fail(f"{name}: invalid arguments: {_validation_text(exc)}")
        with _confined(scope.home):
            result = fn(**kwargs)
        return ToolResult(_cap(str(result)), error=not getattr(result, "ok", True))
    return Tool(name, meta.description, meta.parameters, _safe(name, run))


def reelsmith_tools(project: Path, scope: guard.Scope) -> list[Tool]:
    return [reelsmith_tool(name, fn, project, scope) for name, fn in rtools.TOOLS.items()]


# ------------------------------------------------------------------ file tools
def _checked(scope: guard.Scope, tool: str, inp: dict) -> str:
    allowed, why = guard.decide(tool, inp, scope)
    return "" if allowed else why


def _resolve(token: str, scope: guard.Scope) -> Path:
    path = guard.resolve_token(token, scope.cwd)
    if path is None:                    # the guard refuses these first; kept as a backstop
        raise ValueError(f"not a path inside the workspace: {token}")
    return path


def _readable(path: Path, scope: guard.Scope) -> bool:
    return guard.check_path(str(path), scope, "read") == ""


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_file_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        token = str(_arg(args, "path", "file_path", default="") or "")
        why = _checked(scope, "Read", {"file_path": token})
        if why:
            return _fail(why)
        offset = _int(_arg(args, "offset"), "offset", 1)
        limit = _int(_arg(args, "limit"), "limit", READ_LINES)
        path = _resolve(token, scope)
        show = _show(path, project)
        if path.is_dir():
            return _fail(f"{show} is a folder: use list_dir or glob")
        if not path.is_file():
            return _fail(f"{show} does not exist")
        ext = path.suffix.lower()
        if ext in IMAGE_EXT:
            from PIL import Image
            try:
                with Image.open(path) as im:
                    w, h = im.size
            except Exception:  # noqa: BLE001
                return _fail(f"{show} is not a readable image")
            return ToolResult(f"{show}: a {w}x{h} image, attached to the next message", images=[path])
        if ext in MEDIA_EXT:
            return _fail(f"{show} is a video or audio file: look at a film's frames with preview or review, "
                         "and list media with assets")
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            return _fail(f"{show} is a binary file ({len(raw)} bytes), not text")
        text = _decode(raw)
        if not text:
            return ToolResult(f"{show} is empty")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        total = len(lines)
        if offset > total:
            return _fail(f"{show} has {total} line(s); offset {offset} is past the end")
        rows, size, last = [], 0, offset - 1
        for n in range(offset, min(total, offset - 1 + limit) + 1):
            line = lines[n - 1].rstrip("\r")
            if len(line) > LINE_CHARS:
                line = line[:LINE_CHARS] + f"… [{len(line) - LINE_CHARS} more characters]"
            row = f"{n:>6}\t{line}"
            if size + len(row) > READ_CHARS and rows:
                break
            rows.append(row)
            size += len(row) + 1
            last = n
        if last < total:
            rows.append(f"... {total - last} more line(s) of {total}: read on with offset={last + 1}")
        return ToolResult("\n".join(rows))

    return Tool("read_file", (
        "Read a file: text comes back with line numbers (a number, a tab, then the line; the numbers are not part "
        "of the file), at most 2000 lines from `offset`. An image file (png, jpg, gif, webp) is shown to you as a "
        "picture: use it to look at preview stills, contact sheets and review frames. Relative paths are inside the "
        "project. Reads stay inside the workspace, the manual and the renderer source."),
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "the file; relative to the project folder or absolute"},
            "offset": {"type": "integer", "minimum": 1, "description": "first line to read (1-based, default 1)"},
            "limit": {"type": "integer", "minimum": 1, "description": "how many lines (default 2000)"}},
         "required": ["path"]}, _safe("read_file", run))


def write_file_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        token = str(_arg(args, "path", "file_path", default="") or "")
        content = _arg(args, "content")
        why = _checked(scope, "Write", {"file_path": token})
        if why:
            return _fail(why)
        if not isinstance(content, str):
            return _fail("content must be the file's text")
        path = _resolve(token, scope)
        if path.is_dir():
            return _fail(f"{_show(path, project)} is a folder")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        existed = path.exists()
        path.write_bytes(data)
        return ToolResult(f"{'overwrote' if existed else 'created'} {_show(path, project)} ({len(data)} bytes)")

    return Tool("write_file", (
        "Create a file or replace its whole content (UTF-8, written exactly as given). For a change inside an "
        "existing file use edit_file. Writes go to the project and the workspace library only, never to build/, "
        "out/ or .history/ (the reelsmith tools write those), never scripts or executables."),
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "the file; relative to the project folder or absolute"},
            "content": {"type": "string", "description": "the whole new content"}},
         "required": ["path", "content"]}, _safe("write_file", run))


def edit_file_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        token = str(_arg(args, "path", "file_path", default="") or "")
        old = _arg(args, "old", "old_string")
        new = _arg(args, "new", "new_string")
        replace_all = _bool(_arg(args, "replace_all", default=False))
        why = _checked(scope, "Edit", {"file_path": token})
        if why:
            return _fail(why)
        if not isinstance(old, str) or not isinstance(new, str):
            return _fail("old and new must both be text")
        if old == "":
            return _fail("old is empty: to create or overwrite a whole file use write_file")
        if old == new:
            return _fail("old and new are the same: nothing would change")
        path = _resolve(token, scope)
        show = _show(path, project)
        if not path.is_file():
            return _fail(f"{show} does not exist: create it with write_file")
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw[3 if bom else 0:].decode("utf-8")
        except UnicodeDecodeError:
            return _fail(f"{show} is not UTF-8 text: rewrite it with write_file")
        count = text.count(old)
        if count == 0 and "\r\n" in text and "\n" in old and "\r\n" not in old:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")     # the file has Windows line ends
            count = text.count(old)
        if count == 0:
            return _fail(f"old was not found in {show}: copy it exactly from read_file's output, without the line "
                         "numbers and the tab after them (spaces and line breaks count)")
        if count > 1 and not replace_all:
            return _fail(f"old matches {count} places in {show}: include more of the surrounding lines so it "
                         "matches one, or pass replace_all=true to change every one")
        text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return ToolResult(f"edited {show}: {count if replace_all else 1} replacement(s)")

    return Tool("edit_file", (
        "Replace exact text in a file: `old` must match the file exactly once (copy it from read_file without the "
        "line numbers; include enough surrounding lines to make it unique), or pass replace_all=true to change "
        "every match. Fails, changing nothing, when old is not found or matches more than once."),
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "the file; relative to the project folder or absolute"},
            "old": {"type": "string", "description": "the exact text to replace"},
            "new": {"type": "string", "description": "the text to put in its place"},
            "replace_all": {"type": "boolean", "description": "replace every match (default false)"}},
         "required": ["path", "old", "new"]}, _safe("edit_file", run))


def _braces(pattern: str) -> list[str]:
    """a{b,c}d -> [abd, acd]; nested groups are left as they are."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", pattern)
    if not m:
        return [pattern]
    head, tail = pattern[:m.start()], pattern[m.end():]
    return list(itertools.chain.from_iterable(_braces(head + alt + tail) for alt in m.group(1).split(",")))


def _glob_root(pattern: str, base: str, scope: guard.Scope) -> tuple[Path | None, str]:
    """(folder to search, pattern below it), split the way guard.check_glob splits it."""
    segs = re.split(r"[\\/]", pattern)
    first = next((i for i, s in enumerate(segs) if re.search(r"[*?\[\]{}]", s)), None)
    if first is None:
        target = pattern if re.match(r"^([A-Za-z]:|[\\/]|~)", pattern) else os.path.join(base, pattern)
        return guard.resolve_token(target, scope.cwd), ""
    lead = "/".join(segs[:first])
    if re.match(r"^([A-Za-z]:|[\\/]|~)", pattern):
        root = guard.resolve_token(lead or "/", scope.cwd)
    else:
        root = guard.resolve_token(os.path.join(base, lead) if lead else base, scope.cwd)
    return root, "/".join(segs[first:])


def glob_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        pattern = str(_arg(args, "pattern", default="") or "")
        base = str(_arg(args, "path", default="") or "")
        why = _checked(scope, "Glob", {"pattern": pattern, **({"path": base} if base else {})})
        if why:
            return _fail(why)
        root, rest = _glob_root(pattern, base or ".", scope)
        if root is None:
            return _fail(f"cannot search there: {pattern}")
        if not rest:                    # no wildcard: one named file
            return ToolResult(_show(root, project) if root.exists() else f"no match for {pattern}")
        if not root.is_dir():
            return _fail(f"{_show(root, project)} is not a folder")
        found: dict[Path, None] = {}
        for pat in _braces(rest):
            for p in root.glob(pat):
                found.setdefault(p)
                if len(found) >= GLOB_SCAN:
                    break

        def mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0
        rows = []
        for p in sorted(found, key=mtime, reverse=True):
            if _readable(p, scope):
                rows.append(_show(p, project) + ("/" if p.is_dir() else ""))
                if len(rows) >= GLOB_SHOWN:
                    break
        if not rows:
            return ToolResult(f"no match for {pattern}" + (f" in {_show(root, project)}" if base else ""))
        more = " (the first ones; narrow the pattern for the rest)" if len(rows) >= GLOB_SHOWN else ""
        return ToolResult(f"{len(rows)} match(es), newest first{more}:\n" + "\n".join(rows))

    return Tool("glob", (
        "Find files by name pattern: * matches within a folder, ** across folders, {a,b} either (e.g. "
        "\"**/*.tsx\", \"assets/*.{png,jpg}\"). Newest first, at most 200. `path` is the folder to search "
        "(default the project)."),
        {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "the name pattern"},
            "path": {"type": "string", "description": "folder to search in (default the project folder)"}},
         "required": ["pattern"]}, _safe("glob", run))


def grep_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        pattern = str(_arg(args, "pattern", default="") or "")
        target = str(_arg(args, "path", default="") or "")
        name_glob = str(_arg(args, "glob", default="") or "")
        if not pattern:
            return _fail("pattern is empty")
        why = _checked(scope, "Grep", {"pattern": pattern, **({"path": target} if target else {}),
                                       **({"glob": name_glob} if name_glob else {})})
        if why:
            return _fail(why)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return _fail(f"not a valid regular expression ({exc}): {pattern}")
        root = _resolve(target or ".", scope)
        globs = _braces(name_glob) if name_glob else []
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = []
            for folder, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in _PRUNE_DIRS and _readable(Path(folder) / d, scope))
                for n in sorted(names):
                    if not globs or any(fnmatch.fnmatch(n, g) for g in globs):
                        files.append(Path(folder) / n)
                if len(files) >= GREP_FILES:
                    break
        else:
            return _fail(f"{_show(root, project)} does not exist")
        rows, hits = [], 0
        for f in files[:GREP_FILES]:
            try:
                if f.suffix.lower() in IMAGE_EXT | MEDIA_EXT or f.stat().st_size > GREP_FILE_BYTES:
                    continue
                if not _readable(f, scope):
                    continue
                raw = f.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:8192]:
                continue
            for n, line in enumerate(_decode(raw).split("\n"), 1):
                if rx.search(line):
                    hits += 1
                    if len(rows) < GREP_SHOWN:
                        line = line.rstrip("\r")
                        rows.append(f"{_show(f, project)}:{n}: {line[:300]}" + ("…" if len(line) > 300 else ""))
        if not rows:
            return ToolResult(f"no matches for {pattern}")
        if hits > len(rows):
            rows.append(f"... {hits - len(rows)} more match(es): narrow the pattern, path or glob")
        return ToolResult("\n".join(rows))

    return Tool("grep", (
        "Search file contents with a Python regular expression (add (?i) for any case); lines come back as "
        "path:line: text, at most 200. `path` is a file or a folder (default the project), `glob` filters file "
        "names (e.g. \"*.tsx\" or \"*.{md,json}\"). Images, media and files over 2 MB are skipped."),
        {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "the regular expression"},
            "path": {"type": "string", "description": "file or folder to search (default the project folder)"},
            "glob": {"type": "string", "description": "only files whose names match this pattern"}},
         "required": ["pattern"]}, _safe("grep", run))


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def list_dir_tool(project: Path, scope: guard.Scope) -> Tool:
    def run(args: dict) -> ToolResult:
        token = str(_arg(args, "path", default="") or "") or "."
        why = _checked(scope, "Glob", {"pattern": "*", "path": token})
        if why:
            return _fail(why)
        root = _resolve(token, scope)
        show = _show(root, project)
        if root.is_file():
            return _fail(f"{show} is a file: use read_file")
        if not root.is_dir():
            return _fail(f"{show} does not exist")
        dirs, files = [], []
        for p in sorted(root.iterdir(), key=lambda q: q.name.lower()):
            if not _readable(p, scope):
                continue
            if p.is_dir():
                dirs.append(p.name + "/")
            else:
                try:
                    files.append(f"{p.name}  {_size(p.stat().st_size)}")
                except OSError:
                    files.append(p.name)
        rows = dirs + files
        if not rows:
            return ToolResult(f"{show} is empty")
        more = f"\n... {len(rows) - LIST_SHOWN} more" if len(rows) > LIST_SHOWN else ""
        return ToolResult(f"{show}:\n" + "\n".join(rows[:LIST_SHOWN]) + more)

    return Tool("list_dir", (
        "List a folder: subfolders (ending in /) first, then files with their sizes. Default the project folder."),
        {"type": "object", "properties": {
            "path": {"type": "string", "description": "the folder; relative to the project folder or absolute"}},
         "required": []}, _safe("list_dir", run))


def file_tools(project: Path, scope: guard.Scope) -> list[Tool]:
    return [make(project, scope) for make in (read_file_tool, write_file_tool, edit_file_tool, glob_tool, grep_tool,
                                              list_dir_tool)]


# ------------------------------------------------------------------ web tools
def web_fetch_tool(web: dict) -> Tool:
    hooks = {k: web[k] for k in ("resolve", "trusted", "connect") if web.get(k) is not None}

    def run(args: dict) -> ToolResult:
        max_chars = _int(_arg(args, "max_chars"), "max_chars", W.DEFAULT_CHARS)
        text, failed = W.fetch(str(_arg(args, "url", default="") or ""), max_chars, proxy=web.get("proxy"),
                               timeout=float(web.get("timeout_s") or W.FETCH_TIMEOUT_S),
                               locale=web.get("locale") or "en", **hooks)
        return ToolResult(text, error=failed)

    return Tool("web_fetch", (
        "Fetch a public web page (http or https) and read it as text: title, address, then the page's text with "
        "links as [text](url). Local and private network addresses are refused. Cut at max_chars (default 20000)."),
        {"type": "object", "properties": {
            "url": {"type": "string", "description": "the page's http(s) address"},
            "max_chars": {"type": "integer", "minimum": W.MIN_CHARS, "maximum": W.MAX_CHARS,
                          "description": "how much text to return (default 20000)"}},
         "required": ["url"]}, _safe("web_fetch", run))


def web_search_tool(search: W.Search) -> Tool:
    def run(args: dict) -> ToolResult:
        query = str(_arg(args, "query", default="") or "").strip()
        if not query:
            return _fail("query is empty")
        n = min(20, _int(_arg(args, "n"), "n", 8))
        recent = str(_arg(args, "recent", default="") or "").strip().lower()
        if recent and recent not in W.RECENT:
            return _fail(f"recent must be one of {', '.join(W.RECENT)} (or left out)")
        try:
            rows = search(query, n, recent)
        except Exception as exc:  # noqa: BLE001 - network, quota and parse failures alike
            return _fail(f"the search failed ({type(exc).__name__}: {str(exc)[:300]}); try again, rephrase, or "
                         "web_fetch a site you know")
        text = W.format_results(list(rows or []), n)
        return ToolResult(text or f"no results for {query!r}: rephrase or broaden it")

    return Tool("web_search", (
        "Search the web: up to n results (default 8, at most 20) as title, address and snippet. `recent` limits "
        "them to the past day, week, month or year. Read a result in full with web_fetch."),
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "what to search for"},
            "n": {"type": "integer", "minimum": 1, "maximum": 20, "description": "how many results (default 8)"},
            "recent": {"type": "string", "enum": list(W.RECENT), "description": "only results from the past day, "
                       "week, month or year"}},
         "required": ["query"]}, _safe("web_search", run))


# ------------------------------------------------------------------ the toolbox
def toolbox(project: Path, ws, scope: guard.Scope, web: dict | None = None,
            extra: list[Tool] | None = None) -> list[Tool]:
    """Every tool of one run: the reelsmith tools, file tools, web_fetch and web_search, then `extra`.

    web (all optional): "fetch" False leaves web_fetch out; "search" picks the backend ("auto" default, "ddgs",
    "tavily", "none" or a callable search(query, n, recent) -> [{"title", "url", "snippet"}]); "proxy" the outbound
    http:// proxy (None: the environment's, "": direct); "region" for ddgs; "tavily_key" over TAVILY_API_KEY;
    "timeout_s"; "locale" for web_fetch's Accept-Language (default: the project's); "resolve", "trusted", "connect"
    are netcheck's hooks (tests). A tool left out says why in the result's `notes` and the log."""
    project = Path(project)
    web = dict(web or {})
    if not web.get("locale"):
        try:
            web["locale"] = locale_for(project)
        except ValueError:
            web["locale"] = "en"                # check reports a malformed locale
    notes: list[str] = []
    tools = reelsmith_tools(project, scope) + file_tools(project, scope)
    if web.get("fetch", True):
        tools.append(web_fetch_tool(web))
    else:
        notes.append("web_fetch is left out: turned off (web.fetch)")
    keys = getattr(ws, "keys", None) if ws is not None else None
    search, why = W.search_backend(web, keys)
    if search is not None:
        tools.append(web_search_tool(search))
    else:
        notes.append(why)
    for t in extra or []:
        if not isinstance(t, Tool):
            raise TypeError(f"extra tools must be agent.tools.Tool, got {type(t).__name__}")
        tools.append(Tool(t.name, t.description, t.parameters, _safe(t.name, t.run)))
    seen = set()
    for t in tools:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", t.name):
            raise ValueError(f"tool name {t.name!r} must be 1-64 letters, digits, _ or -")
        if t.name in seen:
            raise ValueError(f"two tools are named {t.name!r}")
        seen.add(t.name)
    for n in notes:
        log.info("toolbox: %s", n)
    return Toolbox(tools, notes)
