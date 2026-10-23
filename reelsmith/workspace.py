"""The workspace around a project (config, owner rules, keys, library, ledger) and a project's standard paths."""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .profiles import Profile, get_profile

WORKSPACE_FILE = "workspace.json"
RULES_FILE = "rules.json"
ENV_FILE = ".env"
PROJECT_FILE = "project.json"

DEFAULT_RULES: dict = {
    "hard": {"max_title": 24, "max_title_numbers": 2, "min_sources": 1, "banned": []},
    # target_s None: the profile's target
    "advice": {"hook_seconds": 2, "max_same_visual_s": 8, "target_s": None},
}

_KEY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class WorkspaceError(ValueError):
    """A workspace file the owner or the agent must fix."""


class Keys(dict):
    """Provider keys: .env first, the environment as fallback. Values never show in repr."""

    def __missing__(self, key: str) -> str:
        value = os.environ.get(key)
        if not value:
            raise KeyError(key)
        return value

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        return dict.__contains__(self, key) or bool(isinstance(key, str) and os.environ.get(key))

    def __repr__(self) -> str:
        return f"Keys({sorted(dict.keys(self))})"

    __str__ = __repr__


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=VALUE lines; `export`, comments, quotes and inline ` #` comments handled; empty values dropped."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY_NAME.match(key):
            continue
        value = _dotenv_value(value.strip())
        if value:
            out[key] = value
    return out


def _dotenv_value(value: str) -> str:
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        while quote == '"' and end > 0 and value[end - 1] == "\\":
            end = value.find(quote, end + 1)
        inner = value[1:end] if end > 0 else value[1:]
        if quote == '"':
            inner = inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _read_json(path: Path, what: str) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"{path}: not valid JSON ({exc}); fix the file") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"{path}: must be a JSON object ({what})")
    return data


def merge_rules(found: dict) -> dict:
    """DEFAULT_RULES with rules.json's sections laid over them, type-checked."""
    rules = copy.deepcopy(DEFAULT_RULES)
    for section in ("hard", "advice"):
        part = found.get(section, {})
        if not isinstance(part, dict):
            raise WorkspaceError(f"rules.json: {section!r} must be an object")
        rules[section].update(part)
    for key, value in found.items():
        if key not in rules:
            rules[key] = value
    _check_rules(rules)
    return rules


def _check_rules(rules: dict) -> None:
    hard, advice = rules["hard"], rules["advice"]
    for key in ("max_title", "max_title_numbers", "min_sources"):
        v = hard.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
            raise WorkspaceError(f"rules.json: hard.{key} must be a whole number >= 0 (got {v!r})")
    banned = hard.get("banned")
    if banned is not None and (not isinstance(banned, list) or not all(isinstance(w, str) for w in banned)):
        raise WorkspaceError("rules.json: hard.banned must be a list of strings")
    for key in ("hook_seconds", "max_same_visual_s"):
        v = advice.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
            raise WorkspaceError(f"rules.json: advice.{key} must be a positive number (got {v!r})")
    target = advice.get("target_s")
    if target is not None and not (isinstance(target, list) and len(target) == 2
                                   and all(isinstance(t, (int, float)) for t in target) and target[0] <= target[1]):
        raise WorkspaceError("rules.json: advice.target_s must be [min, max] seconds")


def default_rules() -> dict:
    return copy.deepcopy(DEFAULT_RULES)


@dataclass
class Workspace:
    root: Path
    config: dict = field(default_factory=dict)
    rules: dict = field(default_factory=default_rules)
    keys: Keys = field(default_factory=Keys, repr=False)

    @classmethod
    def load(cls, root: str | Path) -> "Workspace":
        root = Path(root).expanduser().resolve()
        config = _read_json(root / WORKSPACE_FILE, "workspace config")
        rules = merge_rules(_read_json(root / RULES_FILE, "owner rules"))
        env = root / ENV_FILE
        try:
            keys = Keys(parse_dotenv(env.read_text(encoding="utf-8-sig"))) if env.is_file() else Keys()
        except OSError as exc:
            raise WorkspaceError(f"{env}: unreadable ({exc})") from exc
        return cls(root, config, rules, keys)

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def components_dir(self) -> Path:
        return self.library_dir / "components"

    @property
    def notes_path(self) -> Path:
        return self.library_dir / "NOTES.md"

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"


def project_root(project: str | Path) -> Path:
    """The project folder as an absolute path; a path to project.json means its folder."""
    p = Path(project).expanduser().resolve()
    return p.parent if p.name == PROJECT_FILE and p.is_file() else p


def find_workspace(project_dir: str | Path) -> Workspace | None:
    """The nearest folder at or above `project_dir` holding workspace.json, loaded; None outside any workspace."""
    start = project_root(project_dir)
    for d in (start, *start.parents):
        if (d / WORKSPACE_FILE).is_file():
            return Workspace.load(d)
    return None


def rules_for(project: str | Path) -> dict:
    ws = find_workspace(project)
    return ws.rules if ws else default_rules()


def keys_for(project: str | Path) -> Keys:
    ws = find_workspace(project)
    return ws.keys if ws else Keys()


def profile_for(project: str | Path, ws: Workspace | None = None) -> Profile:
    """project.json "profile", else workspace.json "profile", else douyin. Unknown names raise ValueError."""
    p = project_root(project)
    name = None
    try:
        data = json.loads((p / PROJECT_FILE).read_text(encoding="utf-8-sig"))
        name = data.get("profile") if isinstance(data, dict) else None
    except (OSError, ValueError):
        pass
    if not name:
        ws = ws or find_workspace(p)
        name = (ws.config.get("profile") if ws else None) or None
    return get_profile(name)


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    project_json: Path
    script: Path
    voice_dir: Path
    voice_json: Path
    voice_wav: Path
    assets: Path
    build: Path
    resolved: Path
    stills: Path
    inspect: Path
    review: Path
    out: Path
    film: Path
    meta: Path
    report: Path
    history: Path

    def __getitem__(self, key: str) -> Path:
        return getattr(self, key)

    def to_json(self) -> dict:
        return {k: str(v) for k, v in asdict(self).items()}


def project_paths(project: str | Path) -> ProjectPaths:
    root = project_root(project)
    build, out, voice = root / "build", root / "out", root / "voice"
    return ProjectPaths(
        root=root, project_json=root / PROJECT_FILE, script=root / "script.md",
        voice_dir=voice, voice_json=voice / "voice.json", voice_wav=voice / "voice.wav",
        assets=root / "assets", build=build, resolved=build / "resolved.json", stills=build / "stills",
        inspect=build / "inspect", review=build / "review", out=out, film=out / "film.mp4",
        meta=out / "meta.json", report=out / "report.json", history=root / ".history")
