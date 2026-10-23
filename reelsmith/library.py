"""Components a component clip can use: the built-in presets overlaid by the workspace library (library wins)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .workspace import WorkspaceError, find_workspace

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^[A-Za-z0-9_]+$")         # what render.mjs bundles (componentNames)
MAX_ERRORS = 8


def renderer_dir() -> Path:
    return Path(os.environ.get("REELSMITH_RENDERER") or ROOT / "renderer")


def presets_dir() -> Path:
    return renderer_dir() / "src" / "presets"


@dataclass(frozen=True)
class Component:
    name: str
    description: str
    schema: dict                    # the meta's "props" JSON Schema ({} when the meta has none)
    source: str                     # "preset" | "library"
    path: Path                      # the .tsx file
    meta_path: Path | None = None
    example: object = None
    problem: str = ""               # why it cannot be used as it stands ("" when fine)


def _read_meta(meta: Path) -> tuple[dict, str]:
    try:
        data = json.loads(meta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {}, f"{meta.name} is not valid JSON ({exc}): fix it"
    if not isinstance(data, dict):
        return {}, f"{meta.name} must be a JSON object"
    return data, ""


def _schema_problem(schema) -> str:
    if not isinstance(schema, dict):
        return "its meta.json \"props\" must be a JSON Schema object"
    try:
        jsonschema.validators.validator_for(schema).check_schema(schema)
    except jsonschema.SchemaError as exc:
        return f"its props schema is not valid JSON Schema: {exc.message}"
    return ""


def _from_meta(meta: Path, source: str) -> Component:
    name = meta.name[: -len(".meta.json")]
    tsx = meta.with_name(f"{name}.tsx")
    data, problem = _read_meta(meta)
    schema = data.get("props", {}) if not problem else {}
    problem = problem or _schema_problem(schema)
    if not problem and data.get("name") not in (None, name):
        problem = f"its meta.json says name {data.get('name')!r} but the file is {name}: make them match"
    if not problem and not tsx.is_file():
        problem = f"{tsx.name} is missing next to its meta.json"
    return Component(name=name, description=str(data.get("description") or ""),
                     schema=schema if isinstance(schema, dict) else {}, source=source, path=tsx, meta_path=meta,
                     example=data.get("example"), problem=problem)


def _scan(folder: Path, source: str) -> dict[str, Component]:
    out: dict[str, Component] = {}
    if not folder.is_dir():
        return out
    for meta in sorted(folder.glob("*.meta.json")):
        name = meta.name[: -len(".meta.json")]
        if NAME.match(name):
            out[name] = _from_meta(meta, source)
    for tsx in sorted(folder.glob("*.tsx")):
        if NAME.match(tsx.stem) and tsx.stem not in out:
            # renders fine; its props are just not checked
            out[tsx.stem] = Component(name=tsx.stem, description="(no meta.json: props are not checked)", schema={},
                                      source=source, path=tsx)
    return out


def library_dir(project) -> Path | None:
    """<workspace>/library/components for the project, or None outside a workspace."""
    try:
        ws = find_workspace(project)
    except WorkspaceError:
        return None
    return ws.components_dir if ws else None


def components(project) -> dict[str, Component]:
    """{name: Component}: presets from renderer/src/presets, then the workspace library over them."""
    found = _scan(presets_dir(), "preset")
    lib = library_dir(project)
    if lib is not None:
        found.update(_scan(lib, "library"))
    return dict(sorted(found.items()))


def _path_text(path) -> str:
    out = "props"
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def _message(err: jsonschema.ValidationError) -> str:
    v, kind = err.validator, err.validator_value
    if v == "additionalProperties" and isinstance(err.instance, dict):
        allowed = sorted((err.schema.get("properties") or {}).keys())
        extra = sorted(set(err.instance) - set(allowed))
        return f"unknown prop(s) {', '.join(extra)}; allowed: {', '.join(allowed) or 'none'}"
    if v == "required":
        return err.message.replace("is a required property", "is required")
    if v in ("maxLength", "minLength") and isinstance(err.instance, str):
        return f"{len(err.instance)} characters; {'at most' if v == 'maxLength' else 'at least'} {kind}"
    if v == "enum":
        return f"{err.instance!r} is not one of {', '.join(map(repr, kind))}"
    return err.message


def validate_props(component: Component, props) -> list[str]:
    """Problems with `props` as the agent writes them (Times and asset ids still as written); [] when fine."""
    if component.problem:
        return [f"component {component.name} cannot be used: {component.problem}"]
    if not isinstance(props, dict):
        return ["props must be an object"]
    schema = component.schema or {}
    if not schema:
        return []
    cls = jsonschema.validators.validator_for(schema)
    errors = sorted(cls(schema).iter_errors(props), key=lambda e: (len(e.path), list(map(str, e.path))))
    rows = [f"{_path_text(e.absolute_path)}: {_message(e)}" for e in errors]
    if len(rows) > MAX_ERRORS:
        rows = rows[:MAX_ERRORS] + [f"... and {len(rows) - MAX_ERRORS} more"]
    return rows
