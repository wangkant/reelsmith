"""MCP server: every reelsmith tool for Claude Code, Codex, DeepSeek Harness, Cursor, the runner or any MCP client.

Each tool is tools.py's function as is: same parameters, its docstring as the description, its text as the result
(flagged is_error when the call failed or found blocking problems). stdio by default; `--http` serves streamable HTTP
on a loopback address, or on any address with --allow-remote and a bearer token.
"""
import argparse
import hmac
import inspect
import ipaddress
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from . import __version__, tools

INSTRUCTIONS = """reelsmith is your video editing app. You write the script, gather the assets (speak, capture, draw,
animate, import_asset) and edit an NLE-style project (tracks, clips, keyframes, text, shapes, components) with edit;
reelsmith renders, measures layout and enforces delivery. There is no fixed order and no template.
Start with manual (once) and notes. Every tool takes `project` = the folder holding project.json (new_project
makes one). Loop: edit -> check -> preview (look at the stills; sweep=true measures the whole film's layout as render
would) -> fix -> render -> review. To edit recordings, look first (probe, frames, scenes, silences, transcribe), then
cut with ripple_delete at "src:<clip>@<seconds>" Times. Paid tools (speak, draw, animate, transcribe) estimate first
and refuse over budget. Failures come back as text that says what to do."""

ROOT = Path(__file__).resolve().parent.parent
TOKEN_ENV = "REELSMITH_MCP_TOKEN"
GUARD_ENV = "REELSMITH_GUARD_PROJECT"
DEFAULT_PORT = 8765
MIN_TOKEN = 16

mcp = MCPServer("reelsmith", instructions=INSTRUCTIONS, version=__version__)


def guard_scope():
    """With REELSMITH_GUARD_PROJECT set (the runner's codex and dsh engines), every call is held to that project, its
    workspace and the runner guard's rules for paths and URLs, as on the other engines."""
    project = os.environ.get(GUARD_ENV)
    if not project:
        return None
    from . import guard
    from .workspace import WORKSPACE_FILE, Workspace, find_workspace, project_root
    root = project_root(project)
    # the runner sets REELSMITH_ROOT to the workspace it started with: a workspace.json the agent wrote into the
    # project since then (its sandbox may write there) must not become a later session's workspace
    fence = os.environ.get("REELSMITH_ROOT")
    home = Path(fence).expanduser().resolve() if fence else None
    if home is not None and (home == root or home in root.parents) and (home / WORKSPACE_FILE).is_file():
        ws = Workspace.load(home)
    else:
        ws = find_workspace(root)
    return guard.scope_for(root, ws, extra_read=[ROOT / "docs", ROOT / "renderer" / "src"])


GUARD = guard_scope()


def _refusal(kwargs: dict) -> str:
    if GUARD is None:
        return ""
    from . import guard
    try:
        return guard.check_mcp(kwargs, GUARD)
    except Exception as exc:  # noqa: BLE001 - fail closed, like the runner's hook
        return f"The guard failed on this call ({type(exc).__name__}): try another way."


def _expose(fn) -> None:
    """Register `fn` under its own name with its own signature and docstring; results become text content."""
    def call(**kwargs) -> CallToolResult:
        why = _refusal(kwargs)
        if why:
            return CallToolResult(content=[TextContent(type="text", text=f"Refused by the run's guard: {why}")],
                                  is_error=True)
        result = fn(**kwargs)
        return CallToolResult(content=[TextContent(type="text", text=str(result))],
                              is_error=not getattr(result, "ok", True))

    call.__signature__ = inspect.signature(fn).replace(return_annotation=CallToolResult)
    call.__name__ = call.__qualname__ = fn.__name__
    mcp.add_tool(call, name=fn.__name__, description=inspect.cleandoc(fn.__doc__ or fn.__name__))


for _fn in tools.TOOLS.values():
    _expose(_fn)


# ------------------------------------------------------------------ HTTP
def loopback(host: str) -> bool:
    if str(host).strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        return False


class BearerAuth:
    """ASGI wrapper: every HTTP request must carry `Authorization: Bearer <token>`."""

    def __init__(self, app, token: str):
        self.app, self.expected = app, b"Bearer " + token.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            got = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"error": "a bearer token is required"}'})
                return
        await self.app(scope, receive, send)


def http_app(host: str, token: str = ""):
    """The streamable HTTP app at /mcp; the SDK turns DNS-rebinding protection on for loopback hosts."""
    app = mcp.streamable_http_app(host=host)
    return BearerAuth(app, token) if token else app


def check_http(host: str, allow_remote: bool, token: str, token_env: str = TOKEN_ENV) -> str:
    """'' when serving on host is allowed, else why not."""
    if loopback(host):
        return ""
    if not allow_remote:
        return (f"{host} is not a loopback address: the tools read and write files on this machine, so bind "
                "127.0.0.1 (the default), or pass --allow-remote with a bearer token")
    if len(token) < MIN_TOKEN:
        return (f"--allow-remote needs a bearer token of at least {MIN_TOKEN} characters in ${token_env}; clients "
                "send it as `Authorization: Bearer <token>`")
    return ""


def serve_http(host: str = "127.0.0.1", port: int = DEFAULT_PORT, allow_remote: bool = False,
               token_env: str = TOKEN_ENV) -> int:
    token = os.environ.get(token_env) or ""
    why = check_http(host, allow_remote, token, token_env)
    if why:
        print(f"reelsmith mcp: {why}", file=sys.stderr)
        return 2
    import uvicorn
    shown = f"[{host}]" if ":" in host else host
    print(f"reelsmith MCP server: http://{shown}:{port}/mcp" + (" (bearer token required)" if token else ""),
          file=sys.stderr, flush=True)
    uvicorn.run(http_app(host, token), host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reelsmith mcp", description="Serve the reelsmith tools over MCP: stdio by "
                                 "default, or streamable HTTP with --http.")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP at http://HOST:PORT/mcp")
    ap.add_argument("--host", default="127.0.0.1", help="the address to bind (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"the port (default {DEFAULT_PORT})")
    ap.add_argument("--allow-remote", action="store_true",
                    help=f"allow a non-loopback --host; requires a bearer token in ${TOKEN_ENV} (or --token-env)")
    ap.add_argument("--token-env", default=TOKEN_ENV,
                    help="the environment variable holding the bearer token; when it is set, every request needs it")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.http:
        if args.allow_remote or args.host != "127.0.0.1" or args.port != DEFAULT_PORT:
            print("reelsmith mcp: --host, --port and --allow-remote go with --http", file=sys.stderr)
            return 2
        mcp.run("stdio")
        return 0
    return serve_http(args.host, args.port, args.allow_remote, args.token_env)


if __name__ == "__main__":
    sys.exit(main())
