"""reelsmith <command> ...: the agent tools for scripts and people, plus `run` (the self-hosted agent), `mcp` (the
MCP server), `setup` (attach the server and skill to a coding agent) and `doctor` (check this machine)."""
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
    ap = argparse.ArgumentParser(prog="reelsmith",
                                 description="A video editing harness for AI coding agents (and the people who run them).")
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
    p.add_argument("--profile", default="", help="a profile name (default: the workspace's, else landscape)")
    p.add_argument("--title", default="")
    p.add_argument("--canvas", default="", help="WIDTHxHEIGHT[@FPS] for a canvas of your own, e.g. 1920x1080@25")
    p.add_argument("--locale", default="", help="the film's language, a BCP-47 tag (en, zh-CN, ja)")
    proj(cmd("edit", tools.edit)).add_argument("ops", help="JSON list of ops, @file.json, or - for stdin")
    proj(cmd("undo", tools.undo)).add_argument("--steps", type=int, default=1)
    proj(cmd("check", tools.check))
    proj(cmd("library", tools.library)).add_argument("name", nargs="?", default="")
    p = proj(cmd("preview", tools.preview))
    p.add_argument("times", nargs="*", help="seconds or Times (line:3, clip:c2+0.5)")
    p.add_argument("--sweep", action="store_true", help="also measure the whole film as render does")
    p = proj(cmd("render", tools.render))
    p.add_argument("--draft", action="store_true", help="a quick low-quality look to build/draft.mp4 instead")
    p.add_argument("--start", default="", help="draft only: where to begin (seconds or a Time)")
    p.add_argument("--end", default="", help="draft only: where to end (seconds or a Time)")
    p.add_argument("--scale", type=float, default=0.5, help="draft only: 0.1-1 of the canvas (default 0.5)")
    p = proj(cmd("review", tools.review))
    p.add_argument("-n", type=int, default=0, help="only n evenly spaced frames on one sheet (default: watch it all)")
    p.add_argument("--every", type=float, default=1.0, help="seconds between watched frames (default 1)")
    p = proj(cmd("captions", tools.export_captions, "export_captions"))
    p.add_argument("--track", default="", help="one captions track (default: all)")
    p = proj(cmd("speak", tools.speak))
    p.add_argument("lines", help="JSON list, @file (JSON, or one line per line), or - for stdin")
    p.add_argument("--gap", type=float, default=0.22, dest="gap_s")
    p = proj(cmd("capture", tools.capture))
    p.add_argument("url")
    p.add_argument("id")
    p.add_argument("--match", default="")
    p.add_argument("--viewport", default="", choices=["", "phone", "desktop"],
                   help="default: phone for vertical and portrait canvases, desktop for landscape and square")
    p = proj(cmd("draw", tools.draw))
    p.add_argument("id")
    p.add_argument("prompt")
    p.add_argument("--style-ref", default="", dest="style_ref_asset")
    p.add_argument("--size", default="", help="9:16, 2:3, 3:4, 4:5, 1:1, 4:3, 3:2, 16:9 or WxH pixels "
                                              "(default: the aspect nearest the canvas)")
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
    proj(cmd("probe", tools.probe)).add_argument("source", help="an asset id or a file inside the project")
    p = proj(cmd("frames", tools.frames))
    p.add_argument("asset")
    p.add_argument("times", nargs="*", help="source seconds or m:ss")
    p.add_argument("--every", type=float, default=0)
    p.add_argument("-n", type=int, default=0)
    p = proj(cmd("scenes", tools.scenes))
    p.add_argument("asset")
    p.add_argument("--threshold", type=float, default=0.3)
    p = proj(cmd("silences", tools.silences))
    p.add_argument("asset")
    p.add_argument("--min-s", type=float, default=0.5, dest="min_s")
    p.add_argument("--noise-db", type=float, default=-35, dest="noise_db")
    p = proj(cmd("transcribe", tools.transcribe))
    p.add_argument("asset")
    p.add_argument("--language", default="")
    p.add_argument("--prompt", default="")
    proj(cmd("notes", tools.notes))
    proj(cmd("note", tools.note)).add_argument("text", help="the note, @file, or - for stdin")
    proj(cmd("typecheck", tools.typecheck))
    sub.add_parser("run", help="run the self-hosted agent on a project (reelsmith run <project> --brief ...)",
                   add_help=False)
    sub.add_parser("mcp", help="serve the tools over MCP: stdio, or streamable HTTP with --http", add_help=False)
    sub.add_parser("setup", help="attach the MCP server and skill to claude-code, codex, dsh, cursor or generic",
                   add_help=False)
    sub.add_parser("doctor", help="check what reelsmith and its optional tools need on this machine (local, free)",
                   add_help=False)
    return ap


def command_parser(name: str) -> argparse.ArgumentParser:
    """The parser that reads `reelsmith <name> ...`: run, mcp, setup and doctor have their own."""
    if name == "run":
        from .runner import parser
    elif name == "mcp":
        from .mcp_server import parser
    elif name == "setup":
        from .agentconf import parser
    elif name == "doctor":
        from .doctor import parser
    else:
        return _parser()
    return parser()


def _call(args) -> tools.ToolResult:
    c = args.cmd
    if c == "manual":
        return tools.manual()
    if c == "describe":
        return tools.describe(args.project, args.at)
    if c in ("new", "new_project"):
        return tools.new_project(args.project, args.profile, args.title, args.canvas, args.locale)
    if c == "edit":
        return tools.edit(args.project, _text_arg(args.ops))
    if c == "undo":
        return tools.undo(args.project, args.steps)
    if c == "library":
        return tools.library(args.project, args.name)
    if c == "preview":
        return tools.preview(args.project, args.times, args.sweep)
    if c == "review":
        return tools.review(args.project, args.n, args.every)
    if c == "render":
        return tools.render(args.project, args.draft, args.start, args.end, args.scale)
    if c in ("captions", "export_captions"):
        return tools.export_captions(args.project, args.track)
    if c == "speak":
        return tools.speak(args.project, _lines_arg(args.lines), args.gap_s)
    if c == "capture":
        return tools.capture(args.project, args.url, args.id, args.match, args.viewport)
    if c == "draw":
        return tools.draw(args.project, args.id, args.prompt, args.style_ref_asset, args.size)
    if c == "animate":
        return tools.animate(args.project, args.id, args.image_asset, args.motion, args.seconds, args.camera)
    if c in ("import", "import_asset"):
        return tools.import_asset(args.project, args.id, args.source, args.kind)
    if c == "note":
        return tools.note(args.project, _text_arg(args.text))
    if c == "probe":
        return tools.probe(args.project, args.source)
    if c == "frames":
        return tools.frames(args.project, args.asset, args.times, args.every, args.n)
    if c == "scenes":
        return tools.scenes(args.project, args.asset, args.threshold)
    if c == "silences":
        return tools.silences(args.project, args.asset, args.min_s, args.noise_db)
    if c == "transcribe":
        return tools.transcribe(args.project, args.asset, args.language, args.prompt)
    return tools.TOOLS[c](args.project)            # check, assets, notes, typecheck


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
    if argv[:1] == ["doctor"]:
        from .doctor import main as doctor
        return doctor(argv[1:])
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
