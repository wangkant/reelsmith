"""Checks every preset's .meta.json (and the example library's) against contract section 6.

    .venv/Scripts/python.exe renderer/test/presets-preview/check_meta.py [extra component folder ...]

Each Name.tsx has a Name.meta.json and back; name = file stem; a one-line description; props is a valid object schema
(Draft 2020-12 and Draft 7) that refuses unknown keys; every default validates against its property; Time keys
(`at`, `*_at`) take a number or a string; asset keys (`asset`, `*_asset`) take an id string; the example validates.
Exits 1 on any problem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator, Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FOLDERS = [REPO / "renderer" / "src" / "presets", REPO / "examples" / "workspace" / "library" / "components"]


def walk(schema: dict, where: str):
    """(where, key, property schema) for every property at any depth."""
    for key, sub in (schema.get("properties") or {}).items():
        yield f"{where}.{key}", key, sub
        yield from walk(sub, f"{where}.{key}")
    items = schema.get("items")
    if isinstance(items, dict):
        yield from walk(items, f"{where}[]")


def check_meta(path: Path) -> list[str]:
    problems: list[str] = []
    say = problems.append
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return [f"{path.name}: not JSON: {err}"]
    stem = path.name[: -len(".meta.json")]
    if meta.get("name") != stem:
        say(f"{path.name}: name {meta.get('name')!r} != file name {stem!r}")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip() or "\n" in desc:
        say(f"{path.name}: description must be one non-empty line")
    props = meta.get("props")
    if not isinstance(props, dict) or props.get("type") != "object":
        return problems + [f"{path.name}: props must be an object schema"]
    for cls in (Draft202012Validator, Draft7Validator):
        try:
            cls.check_schema(props)
        except Exception as err:  # SchemaError carries the path
            say(f"{path.name}: props is not a valid {cls.__name__} schema: {err.message}")
    if props.get("additionalProperties") is not False:
        say(f"{path.name}: props should refuse unknown keys (additionalProperties: false)")
    for where, key, sub in walk(props, "props"):
        types = sub.get("type")
        types = set(types) if isinstance(types, list) else {types}
        if key == "at" or key.endswith("_at"):
            if types != {"number", "string"}:
                say(f"{path.name}: {where} is a Time, so its type must be [number, string]")
        if key == "asset" or key.endswith("_asset"):
            if types != {"string"}:
                say(f"{path.name}: {where} is an asset id, so its type must be string")
        if "default" in sub:
            errs = list(Draft202012Validator(sub).iter_errors(sub["default"]))
            if errs:
                say(f"{path.name}: {where} default {sub['default']!r} fails its own schema: {errs[0].message}")
    if "example" not in meta:
        say(f"{path.name}: no example")
    else:
        for err in Draft202012Validator(props).iter_errors(meta["example"]):
            say(f"{path.name}: example fails at {'/'.join(map(str, err.path)) or '(top)'}: {err.message}")
    return problems


def check_folder(folder: Path) -> list[str]:
    problems: list[str] = []
    tsx = {p.stem for p in folder.glob("*.tsx")}
    metas = {p.name[: -len(".meta.json")] for p in folder.glob("*.meta.json")}
    for name in sorted(tsx - metas):
        problems.append(f"{folder.name}/{name}.tsx has no {name}.meta.json")
    for name in sorted(metas - tsx):
        problems.append(f"{folder.name}/{name}.meta.json has no {name}.tsx")
    for path in sorted(folder.glob("*.meta.json")):
        problems += check_meta(path)
    return problems


def main(argv: list[str]) -> int:
    folders = FOLDERS + [Path(a) for a in argv]
    problems: list[str] = []
    count = 0
    for folder in folders:
        if not folder.is_dir():
            problems.append(f"not a folder: {folder}")
            continue
        count += len(list(folder.glob("*.meta.json")))
        problems += check_folder(folder)
    for p in problems:
        print(p)
    print(f"{count} components checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
