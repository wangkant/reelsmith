"""Where a terminal session starts (a project, a workspace or neither), new project names and a new workspace."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..workspace import PROJECT_FILE, WORKSPACE_FILE, RULES_FILE, ENV_FILE, Workspace, find_workspace

_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
SLUG_WORDS = 4
SLUG_CHARS = 28


@dataclass
class Place:
    kind: str                       # "project", "workspace" or "none"
    path: Path
    workspace: Workspace | None = None
    project: Path | None = None

    @property
    def listed(self) -> bool:
        """The project lies in the workspace's projects folder, so the workspace server can open it."""
        return (self.workspace is not None and self.project is not None
                and self.project.parent.resolve() == self.workspace.projects_dir.resolve()
                and bool(_NAME.match(self.project.name)))


def locate(path: str | Path) -> Place:
    """The project at or above `path` (not above its workspace), else the workspace, else neither. A workspace.json
    that does not load raises WorkspaceError."""
    start = Path(path).expanduser().resolve()
    if start.name == PROJECT_FILE and start.is_file():
        start = start.parent
    ws = find_workspace(start) if start.is_dir() else None
    stop = ws.root if ws else None
    for folder in (start, *start.parents):
        if (folder / PROJECT_FILE).is_file():
            return Place("project", start, ws, folder)
        if folder == stop:
            break
    if ws is not None:
        return Place("workspace", start, ws)
    return Place("none", start)


# ------------------------------------------------------------------ new projects and workspaces
def slug(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:SLUG_WORDS]
    out = "-".join(words)[:SLUG_CHARS].strip("-")
    return out or "film"


def new_name(ws: Workspace, text: str = "", today: date | None = None) -> str:
    """<today>-<slug of text>, unique in the workspace's projects folder."""
    base = f"{(today or date.today()).isoformat()}-{slug(text)}"
    name, n = base, 2
    while (ws.projects_dir / name).exists():
        name, n = f"{base}-{n}", n + 1
    return name


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


NOTES = """# Notes

The agent's notes for this workspace: read at the start of work (`notes`), added to as it learns (`note`).
Keep each entry one or two lines, dated, with the project it came from.

## What works

## What flopped

## House style
"""

ENV = """# Optional keys for reelsmith. Add the value after =, save, and never paste it into a chat.
# OPENROUTER_API_KEY=
# OPENAI_API_KEY=
# DEEPSEEK_API_KEY=
# ANTHROPIC_API_KEY=
"""


def create_workspace(root: Path, locale: str = "en") -> Workspace:
    """A minimal workspace: workspace.json, rules.json, library/ with NOTES.md, projects/ and a .env of comments.
    Files that exist are left as they are."""
    root = Path(root).resolve()
    (root / "library" / "components").mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(exist_ok=True)
    files = {WORKSPACE_FILE: json.dumps({"profile": "landscape", "locale": locale}, indent=2) + "\n",
             RULES_FILE: json.dumps({"hard": {}, "advice": {}}) + "\n",
             "library/NOTES.md": NOTES, ENV_FILE: ENV}
    for rel, text in files.items():
        path = root / rel
        if not path.exists():
            path.write_text(text, encoding="utf-8", newline="\n")
    return Workspace.load(root)


def film_locale(lang: str) -> str:
    """The film language a new workspace starts with, from the interface language."""
    return lang if lang in ("en", "zh-CN", "zh-TW", "ja", "ko", "es", "fr", "de") else "en"


def now_ts() -> float:
    return datetime.now().timestamp()
