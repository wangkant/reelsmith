"""MCP server (stdio): every reelsmith tool for Claude Code, Codex, the runner or any MCP client.

Each tool is tools.py's function as is: same parameters, its docstring as the description, its text as the result
(flagged is_error when the call failed or found blocking problems).
"""
import inspect

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from . import __version__, tools

INSTRUCTIONS = """reelsmith is your video editing app. You write the script, gather the assets (speak, capture, draw,
animate, import_asset) and edit an NLE-style project (tracks, clips, keyframes, text, shapes, components) with edit;
reelsmith renders, measures layout and enforces delivery. There is no fixed order and no template.
Start with manual (once) and notes. Every tool takes `project` = the folder holding project.json (new_project
makes one). Loop: edit -> check -> preview (look at the stills; sweep=true measures the whole film's layout as render
would) -> fix -> render -> review. Paid tools (speak, draw, animate) estimate first and refuse over budget. Failures
come back as text that says what to do."""

mcp = MCPServer("reelsmith", instructions=INSTRUCTIONS, version=__version__)


def _expose(fn) -> None:
    """Register `fn` under its own name with its own signature and docstring; results become text content."""
    def call(**kwargs) -> CallToolResult:
        result = fn(**kwargs)
        return CallToolResult(content=[TextContent(type="text", text=str(result))],
                              is_error=not getattr(result, "ok", True))

    call.__signature__ = inspect.signature(fn).replace(return_annotation=CallToolResult)
    call.__name__ = call.__qualname__ = fn.__name__
    mcp.add_tool(call, name=fn.__name__, description=inspect.cleandoc(fn.__doc__ or fn.__name__))


for _fn in tools.TOOLS.values():
    _expose(_fn)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
