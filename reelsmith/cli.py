"""reelsmith <command> ...: the agent tools for scripts and people, plus `run` (the self-hosted agent), `mcp` (the
MCP server) and `setup` (attach the server and skill to a coding agent)."""
import argparse
import inspect
import re
import sys
from pathlib import Path

from . import tools


def _text_arg(value: str) -> str:
    """A literal, "@file" for a file's contents, or "-" for stdin."""
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8-sig")
    return value


def _lines_arg(value: str):
    """speak's lines: a JSON list, or a text file with one voice line per non-empty line."""
    text = _text_arg(value)
    if text.lstrip().startswith("["):
        return text
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reelsmith", description="A video editor for AI agents (and their operators).")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    def cmd(name: str, fn, *aliases: str):
        para = inspect.cleandoc(fn.__doc__ or "").split("\n\n")[0].replace("\n", " ")
        doc = re.split(r"(?<=[.:;])\s", para, maxsplit=1)[0].rstrip(".:;")
        return sub.add_parser(name, help=doc, description=inspect.cleandoc(fn.__doc__ or ""), aliases=list(aliases))

    def proj(p):
        p.add_argument("project", help="the project folder (holding project.json)")
        return p

    cmd("manual", tools.manual)
    proj(cmd("describe", tools.describe)).add_argument("--at", help="seconds or a Time, e.g. line:3")
    p = proj(cmd("new", tools.new_project, "new_project"))
    p.add_argument("--profile", default="")
    p.add_argument("--title", default="")
    proj(cmd("edit", tools.edit)).add_argument("ops", help="JSON list of ops, @file.json, or - for stdin")
    proj(cmd("undo", tools.undo)).add_argument("--steps", type=int, default=1)
    proj(cmd("check", tools.check))
    proj(cmd("library", tools.library)).add_argument("name", nargs="?", default="")
    p = proj(cmd("preview", tools.preview))
    p.add_argument("times", nargs="*", help="seconds or Times (line:3, clip:c2+0.5)")
    p.add_argument("--sweep", action="store_true", help="also measure a still every second of the whole film")
    proj(cmd("render", tools.render))
    proj(cmd("review", tools.review)).add_argument("-n", type=int, default=12)
    p = proj(cmd("speak", tools.speak))
    p.add_argument("lines", help="JSON list, @file (JSON, or one line per line), or - for stdin")
    p.add_argument("--gap", type=float, default=0.22, dest="gap_s")
    p = proj(cmd("capture", tools.capture))
    p.add_argument("url")
    p.add_argument("id")
    p.add_argument("--match", default="")
    p = proj(cmd("draw", tools.draw))
    p.add_argument("id")
    p.add_argument("prompt")
    p.add_argument("--style-ref", default="", dest="style_ref_asset")
    p.add_argument("--size", default="", help="9:16 (default), 2:3, 3:4, 4:5, 1:1, 4:3, 3:2, 16:9 or WxH pixels")
    p = proj(cmd("animate", tools.animate))
    p.add_argument("id")
    p.add_argument("image_asset")
    p.add_argument("motion")
    p.add_argument("--seconds", type=float, default=4)
    p.add_argument("--camera", default="", choices=["", "push", "pull", "pan_left", "pan_right", "rise", "still"])
    p = proj(cmd("import", tools.import_asset, "import_asset"))
    p.add_argument("id")
    p.add_argument("source")
    p.add_argument("kind", nargs="?", default="", help="image, video, audio or evidence (default: detect)")
    proj(cmd("assets", tools.assets))
    proj(cmd("notes", tools.notes))
    proj(cmd("note", tools.note)).add_argument("text", help="the note, @file, or - for stdin")
    proj(cmd("typecheck", tools.typecheck))
    sub.add_parser("run", help="run the self-hosted agent on a project (reelsmith run <project> --brief ...)",
                   add_help=False)
    sub.add_parser("mcp", help="serve the tools over MCP: stdio, or streamable HTTP with --http", add_help=False)
    sub.add_parser("setup", help="attach the MCP server and skill to claude-code, codex, dsh, cursor or generic",
                   add_help=False)
    return ap


def _call(args) -> tools.ToolResult:
    c = args.cmd
    if c == "manual":
        return tools.manual()
    if c == "describe":
        return tools.describe(args.project, args.at)
    if c in ("new", "new_project"):
        return tools.new_project(args.project, args.profile, args.title)
    if c == "edit":
        return tools.edit(args.project, _text_arg(args.ops))
    if c == "undo":
        return tools.undo(args.project, args.steps)
    if c == "library":
        return tools.library(args.project, args.name)
    if c == "preview":
        return tools.preview(args.project, args.times, args.sweep)
    if c == "review":
        return tools.review(args.project, args.n)
    if c == "speak":
        return tools.speak(args.project, _lines_arg(args.lines), args.gap_s)
    if c == "capture":
        return tools.capture(args.project, args.url, args.id, args.match)
    if c == "draw":
        return tools.draw(args.project, args.id, args.prompt, args.style_ref_asset, args.size)
    if c == "animate":
        return tools.animate(args.project, args.id, args.image_asset, args.motion, args.seconds, args.camera)
    if c in ("import", "import_asset"):
        return tools.import_asset(args.project, args.id, args.source, args.kind)
    if c == "note":
        return tools.note(args.project, _text_arg(args.text))
    return tools.TOOLS[c](args.project)            # check, render, assets, notes, typecheck


def _run_agent(rest: list[str]) -> int:
    try:
        from . import runner
    except ModuleNotFoundError as exc:
        print(f"reelsmith run is unavailable: {exc}", file=sys.stderr)
        return 2
    params = inspect.signature(runner.main).parameters
    if params:
        code = runner.main(rest)
    else:
        sys.argv = ["reelsmith run", *rest]
        code = runner.main()
    return int(code or 0)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:
        return _run_agent(argv[1:])
    if argv[:1] == ["mcp"]:
        from .mcp_server import main as serve
        return int(serve(argv[1:]) or 0)
    if argv[:1] == ["setup"]:
        from .agentconf import main as setup
        return setup(argv[1:])
    args = _parser().parse_args(argv)
    try:
        result = _call(args)
    except OSError as exc:                      # an @file that cannot be read
        print(f"cannot read the argument: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0 if getattr(result, "ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
