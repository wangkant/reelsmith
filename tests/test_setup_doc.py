"""The setup guide for agents and the README name only commands and flags the real CLI parser accepts. Nothing runs:
each `reelsmith ...` line is parsed, as is the guide's smoke-test ops batch (applied to a scratch project)."""
import contextlib
import io
import json
import re
import shlex
from pathlib import Path

import pytest

from reelsmith import cli, tools

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "setup-for-agents.md"
README = ROOT / "README.md"
RAW_URL = "https://raw.githubusercontent.com/wangkant/reelsmith/main/docs/setup-for-agents.md"
PLACEHOLDER = re.compile(r"<([A-Za-z][\w-]*)>")
SAMPLES = {"agent": "claude-code"}          # a placeholder that must be a valid choice
SPAN = re.compile(r"`([^`]+)`")


def snippets(text: str):
    """(line number, text, is_span) for every line of a fenced block (JSON blocks aside) and every inline code
    span."""
    prose, fence, lang = [], None, ""
    for n, line in enumerate(text.splitlines(), 1):
        mark = line.strip()
        if mark.startswith("```"):
            fence, lang = (None, "") if fence else (n, mark[3:].strip())
            prose.append("")
            continue
        if fence:
            if lang != "json":
                yield n, line, False
            prose.append("")
        else:
            prose.append(line)
    flat = "\n".join(prose)
    for m in SPAN.finditer(flat):
        yield flat.count("\n", 0, m.start()) + 1, " ".join(m.group(1).split()), True


def reelsmith_argvs(snippet: str):
    """The argument lists of the reelsmith commands in a shell snippet (separators `;`, `&&`, `|`, `&` split it)."""
    text = PLACEHOLDER.sub(lambda m: SAMPLES.get(m.group(1), "x"), snippet)
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:
        assert "reelsmith " not in snippet, f"cannot split: {snippet}"
        return
    segment = []
    for tok in [*tokens, ";"]:
        if tok and set(tok) <= set(";&|"):
            if segment and re.split(r"[\\/]", segment[0])[-1].lower().removesuffix(".exe") == "reelsmith":
                if segment[1:]:
                    yield segment[1:]
            segment = []
        else:
            segment.append(tok)


def parse_error(argv: list[str]) -> str:
    """'' when the real CLI parses argv (`reelsmith` dropped), else argparse's complaint."""
    parser = cli.command_parser(argv[0])
    rest = argv if parser.prog == "reelsmith" else argv[1:]
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(rest)
    except SystemExit as exc:
        return "" if exc.code == 0 else err.getvalue().strip() or f"exit {exc.code}"
    return ""


def commands(path: Path) -> list[tuple[int, list[str]]]:
    """Every reelsmith command line; an inline span that only names a command (`reelsmith run` in prose) is checked
    for the command alone."""
    found = []
    for n, text, is_span in snippets(path.read_text(encoding="utf-8")):
        for argv in reelsmith_argvs(text):
            found.append((n, [*argv, "--help"] if is_span and len(argv) == 1 else argv))
    return found


@pytest.mark.parametrize("path", [GUIDE, README], ids=lambda p: p.name)
def test_every_reelsmith_command_parses(path):
    found = commands(path)
    bad = [f"{path.name}:{n}: reelsmith {' '.join(argv)}: {why}" for n, argv in found if (why := parse_error(argv))]
    assert bad == []
    names = {argv[0] for _, argv in found}
    if path == GUIDE:
        assert {"doctor", "setup", "new", "edit", "preview", "render"} <= names, names


def test_the_checker_catches_a_wrong_command():
    assert parse_error(["setup", "vscode"]) and parse_error(["doctor", "--jsno"]) and parse_error(["previews", "p"])
    assert parse_error(["new", "p", "--canvas"]) and not parse_error(["new", "p", "--canvas", "1920x1080"])
    assert not parse_error(["run", "--help"]) and parse_error(["runs", "--help"])
    assert list(reelsmith_argvs('cd "<workspace>"; & "<install>\\.venv\\Scripts\\reelsmith.exe" setup <agent>')) == \
        [["setup", "claude-code"]]
    assert list(reelsmith_argvs("git clone https://github.com/wangkant/reelsmith reelsmith")) == []


def test_readme_prompt_names_the_raw_guide():
    text = README.read_text(encoding="utf-8")
    section = text.split("## Let your coding agent set it up", 1)[1].split("\n## ", 1)[0]
    assert RAW_URL in section
    assert text.index("## Let your coding agent set it up") > text.index("## Quick start")
    assert "setup-for-agents.md" in (ROOT / "docs" / "agents.md").read_text(encoding="utf-8")


def test_the_guides_smoke_test_ops_apply(tmp_path):
    text = GUIDE.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, re.S)
    assert len(blocks) == 1
    ops = json.loads(blocks[0])
    project = tmp_path / "studio" / "projects" / "hello"
    assert tools.new_project(str(project)).ok
    result = tools.edit(str(project), json.dumps(ops))
    assert result.ok, result
    assert tools.check(str(project)).ok
