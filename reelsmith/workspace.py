"""The workspace around a project (config, owner rules, keys, library, ledger) and a project's standard paths."""
from __future__ import annotations

import copy
import functools
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import locales
from .profiles import Profile, ProfileError, build_profiles, choose

WORKSPACE_FILE = "workspace.json"
RULES_FILE = "rules.json"
ENV_FILE = ".env"
PROJECT_FILE = "project.json"

# No rule and no advice unless rules.json sets it; advice target_s true means the profile's target.
DEFAULT_RULES: dict = {"hard": {}, "advice": {}}
BUILTIN_FONTS = ("sans", "serif", "display", "zcool")
FONT_EXTS = (".woff2", ".woff", ".ttf", ".otf")
FONT_FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")

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
    if target not in (None, True, False) and not (
            isinstance(target, list) and len(target) == 2 and all(isinstance(t, (int, float)) for t in target)
            and target[0] <= target[1]):
        raise WorkspaceError("rules.json: advice.target_s must be [min, max] seconds, or true for the profile's "
                             "target")


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
        ws = cls(root, config, rules, keys)
        _ = ws.profiles, ws.locale, ws.fonts                # a bad entry is the owner's to fix: say so now
        return ws

    @functools.cached_property
    def profiles(self) -> dict[str, Profile]:
        """workspace.json `profiles`, built: {name: Profile}."""
        try:
            return build_profiles(self.config.get("profiles"))
        except ProfileError as exc:
            raise WorkspaceError(str(exc)) from None

    @functools.cached_property
    def locale(self) -> str | None:
        value = self.config.get("locale")
        if value is None:
            return None
        try:
            return locales.check(value)
        except ValueError as exc:
            raise WorkspaceError(f"workspace.json: {exc}") from None

    @functools.cached_property
    def fonts(self) -> dict[str, list[dict]]:
        """{family: [{"path", "weight", "style"}]}: library/fonts/* by file stem, then workspace.json `fonts`."""
        return workspace_fonts(self.root, self.fonts_dir, self.config.get("fonts"))

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    @property
    def components_dir(self) -> Path:
        return self.library_dir / "components"

    @property
    def fonts_dir(self) -> Path:
        return self.library_dir / "fonts"

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


def _project_value(project: Path, key: str):
    try:
        data = json.loads((project / PROJECT_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data.get(key) if isinstance(data, dict) else None


def profile_for(project: str | Path, ws: Workspace | None = None) -> Profile:
    """project.json "profile" (a name or an inline object), else workspace.json "profile", else landscape; custom
    names come from workspace.json "profiles". A bad or unknown profile raises ValueError."""
    p = project_root(project)
    ws = ws or find_workspace(p)
    return choose(_project_value(p, "profile"), ws.config.get("profile") if ws else None,
                  ws.profiles if ws else None)


def locale_for(project: str | Path, ws: Workspace | None = None) -> str:
    """project.json "locale", else workspace.json "locale", else "en"; ValueError for a malformed tag."""
    p = project_root(project)
    value = _project_value(p, "locale")
    if value is not None:
        return locales.check(value)
    ws = ws or find_workspace(p)
    return (ws.locale if ws else None) or locales.DEFAULT_LOCALE


def _font_entry(root: Path, value, where: str) -> dict:
    if isinstance(value, str):
        value = {"src": value}
    if not isinstance(value, dict) or not isinstance(value.get("src"), str) or set(value) - {"src", "weight", "style"}:
        raise WorkspaceError(f'{where} must be a file path or {{"src", "weight"?, "style"?}}')
    path = (root / value["src"]).resolve()
    if root != path and root not in path.parents:
        raise WorkspaceError(f"{where}: {value['src']} must be inside the workspace (library/fonts/...)")
    if path.suffix.lower() not in FONT_EXTS or not path.is_file():
        raise WorkspaceError(f"{where}: {value['src']} is not a {'/'.join(FONT_EXTS)} file in the workspace")
    weight, style = value.get("weight"), value.get("style")
    if weight is not None and not re.fullmatch(r"\d{3}(?: \d{3})?", str(weight)):
        raise WorkspaceError(f'{where}.weight must be like "400", or "100 900" for a variable font')
    if style is not None and style not in ("normal", "italic", "oblique"):
        raise WorkspaceError(f"{where}.style must be normal, italic or oblique")
    return {"path": path, "weight": None if weight is None else str(weight), "style": style}


def workspace_fonts(root: Path, folder: Path, mapping=None) -> dict[str, list[dict]]:
    """Font files of the workspace by family: every library/fonts/*.woff2|woff|ttf|otf under its file stem (a stem
    that is not a usable family name is skipped), then the `fonts` map {family: path | {src, weight?, style?} |
    [...]} over them."""
    out: dict[str, list[dict]] = {}
    base = Path(root).resolve()
    if folder.is_dir():
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in FONT_EXTS and FONT_FAMILY.match(f.stem) \
                    and f.stem not in BUILTIN_FONTS:
                path = f.resolve()
                if base in path.parents:        # a link out of the workspace would be served from build/fonts
                    out.setdefault(f.stem, []).append({"path": path, "weight": None, "style": None})
    if mapping is None:
        return out
    if not isinstance(mapping, dict):
        raise WorkspaceError('workspace.json fonts must be an object {family: "library/fonts/file.woff2"}')
    for family, value in mapping.items():
        where = f"workspace.json fonts.{family}"
        if not FONT_FAMILY.match(str(family)) or family in BUILTIN_FONTS:
            raise WorkspaceError(f"{where}: a family name is 1-64 letters, digits, spaces, _ or - and not one of "
                                 f"{', '.join(BUILTIN_FONTS)}")
        items = value if isinstance(value, list) and value else [value]
        out[family] = [_font_entry(root.resolve(), v, where) for v in items]
    return out


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


def project_file(root: str | Path, rel) -> Path | None:
    """The real path of `rel` (a path from project.json) when it stays inside the project folder `root`, else None.
    Absolute, drive and UNC paths are refused before anything is opened (a UNC path would reach the network)."""
    text = str(rel or "")
    p = Path(text)
    if not text.strip() or p.is_absolute() or p.drive or p.root or text.startswith(("/", "\\")):
        return None
    base = Path(root).resolve()
    full = (base / p).resolve()
    return full if base in full.parents else None


def project_paths(project: str | Path) -> ProjectPaths:
    root = project_root(project)
    build, out, voice = root / "build", root / "out", root / "voice"
    return ProjectPaths(
        root=root, project_json=root / PROJECT_FILE, script=root / "script.md",
        voice_dir=voice, voice_json=voice / "voice.json", voice_wav=voice / "voice.wav",
        assets=root / "assets", build=build, resolved=build / "resolved.json", stills=build / "stills",
        inspect=build / "inspect", review=build / "review", out=out, film=out / "film.mp4",
        meta=out / "meta.json", report=out / "report.json", history=root / ".history")
