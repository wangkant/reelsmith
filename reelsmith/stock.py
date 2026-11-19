"""A workspace's stock pictures (library/stock: poses with their twins, sets in layers, props) that every film can
take, and the shipped catalogue of standard items, drawn in the workspace's own look (stock/look.json) when taken.
A film's own character (a cast member) gets a model sheet and catalogue poses that stay in the project."""
from __future__ import annotations

import filecmp
import functools
import importlib
import json
import os
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from .providers.config import context, image_size, read_project, register_asset
from .workspace import find_workspace, project_file

D = importlib.import_module(f"{__package__}.providers.draw")     # the package re-exports a draw function

CATALOGUE = Path(__file__).with_name("stock_catalogue.json")
KINDS = {"pose": "poses", "set": "sets", "prop": "props"}
LOOK_FILE = "look.json"
LOOK_KEYS = ("character", "set", "prop")        # "sheet" and "who" are optional
TWINS = {"shut": "shut", "half": "half", "blink": "blink", "blink_open": "blinkOpen"}    # file suffix -> Pose key
SHUT_PROMPT = "the mouth is closed; the expression is otherwise the same"
BLINK_PROMPT = "the eyes are shut"
SHEET_ASSET = "look_sheet"
POSE_FRAME = ("Seen from the {view}, the whole figure from head to feet, alone, nothing else in the picture, no ground, "
              "no shadow. {mouth}; the hands stay below the top of the head.")
MOUTH_OPEN, MOUTH_SHUT = "The mouth is open as if speaking", "The mouth is closed unless the pose says otherwise"
PLATE_FLOOR = ("Straight-on view at standing eye height. The lower third is clear, empty floor with nothing standing on "
               "it, where a figure will stand. No people or animals.")
PIECE_FRAME = "seen straight on from the front at standing eye height, whole, alone"
PICTURES = (".png", ".webp", ".jpg", ".jpeg")
ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,47}$")
LOOK_HELP = ('write <workspace>/library/stock/look.json first: {"character": "<style sentence for characters>", '
             '"set": "<style sentence for places>", "prop": "<style sentence for things>", "sheet": "<optional: a '
             'picture file in library/stock that shows the look, sent as the style reference>", "who": "<optional, '
             'for a workspace with one fixed character: how every pose names it and its outfit; sheet is then its '
             'model sheet>", "blink": <optional, false: poses get no blink twin (small faces)>, "mouth": <optional, "shut": '
             'poses are drawn with the mouth closed and get no closed-mouth twin (narrated films)>}')
CAST_HELP = ('cast="<a short id for one character of this film, like granny>" with who="<what it is and wears, one '
             'sentence, the same words in every call>"')
CAST_ID = re.compile(r"^[a-z][a-z0-9]{0,15}$")
CAST_SHEET = ("Character model sheet of one original character: {who}. Four full-body views of the same character "
              "standing in a row on a plain white background: front view, front view talking with the mouth open, "
              "side view, back view. The same face, build, outfit and proportions in all four. No text, no labels.")
CAST_WHO = "The same character as the reference model sheet ({who})"


class StockError(ValueError):
    """The call cannot be done as asked; the message says what to do."""


@functools.lru_cache(maxsize=1)
def catalogue() -> dict[str, dict[str, dict]]:
    """{"pose": {id: entry}, "set": ..., "prop": ...} from the shipped catalogue."""
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return {kind: {e["id"]: e for e in data[plural]} for kind, plural in KINDS.items()}


def stock_of(root: Path) -> Path:
    ws = find_workspace(root)
    if ws is None:
        raise StockError(f"{root} is outside a workspace (no workspace.json above it): stock belongs to a workspace")
    return ws.stock_dir


def kind_of(value) -> str:
    text = str(value or "").strip().lower()
    for kind, plural in KINDS.items():
        if text in (kind, plural):
            return kind
    raise StockError(f"kind must be one of {', '.join(KINDS)} (got {value!r})")


def read_look(stock: Path) -> tuple[dict | None, str]:
    """(look, '') or (None, why it cannot be used)."""
    path = stock / LOOK_FILE
    if not path.is_file():
        return None, f"missing: {LOOK_HELP}"
    try:
        look = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"{LOOK_FILE} is not valid JSON ({exc}): {LOOK_HELP}"
    missing = [k for k in LOOK_KEYS if not isinstance(look, dict) or not str(look.get(k) or "").strip()]
    if missing:
        return None, f"{LOOK_FILE} lacks {', '.join(missing)}: {LOOK_HELP}"
    return look, ""


def items(stock: Path, kind: str) -> dict[str, dict]:
    """{id: meta} of one kind in stock; a meta that does not parse is skipped."""
    folder, found = stock / KINDS[kind], {}
    for meta in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(meta.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id") == meta.stem:
            found[meta.stem] = data
    return found


def parse_ref(ref, stock: Path) -> tuple[str, str]:
    """"pose:shrug" -> ("pose", "shrug"); a bare id is looked up in stock, then the catalogue."""
    text = str(ref or "").strip()
    if ":" in text:
        kind, _, item_id = text.partition(":")
        return kind_of(kind), item_id.strip().lower()
    hits = [k for k in KINDS if text.lower() in items(stock, k)] or [k for k in KINDS if text.lower() in catalogue()[k]]
    if len(hits) != 1:
        raise StockError(f"{text!r} names {'nothing in stock or the catalogue' if not hits else 'more than one kind'}: "
                         'write it as "pose:<id>", "set:<id>" or "prop:<id>"')
    return hits[0], text.lower()


def files_of(meta: dict) -> list[tuple[str, dict]]:
    """(asset id, file entry) of an item, in its layer or twin order."""
    if meta["kind"] == "set":
        return [(f"{meta['id']}_{layer['name']}", layer) for layer in meta.get("layers") or []]
    if meta["kind"] == "pose":
        out = [(meta["id"], meta["files"]["src"])]
        return out + [(f"{meta['id']}_{t}", meta["files"][t]) for t in TWINS if t in meta["files"]]
    return [(meta["id"], meta["file"])]


# ------------------------------------------------------------------ the catalogue's recipes
def cast_of(value) -> dict | None:
    """{"id", "who"} of a film's own character, or None when no cast is given."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict) or set(value) - {"id", "who"}:
        raise StockError(CAST_HELP)
    cid, who = str(value.get("id") or "").strip().lower(), " ".join(str(value.get("who") or "").split())
    if not CAST_ID.match(cid) or cast_sheet({"id": cid}) == SHEET_ASSET:
        raise StockError(f"cast id {value.get('id')!r} must be 1-16 lowercase letters or digits, starting with a "
                         f"letter, and not \"look\" ({SHEET_ASSET} is the workspace's sheet); {CAST_HELP}")
    if not 8 <= len(who) <= 400:
        raise StockError(f"cast who must say in 8-400 characters what the character is and wears; {CAST_HELP}")
    return {"id": cid, "who": who.rstrip(".")}


def cast_sheet(cast: dict) -> str:
    return f"{cast['id']}_sheet"


def sheet_picture(cast: dict, look: dict, sheet: bool) -> dict:
    """The draw that fixes a cast member's design, in the look."""
    return {"id": cast_sheet(cast), "size": "3:2", **({"style_ref_asset": SHEET_ASSET} if sheet else {}),
            "prompt": f"{CAST_SHEET.format(who=cast['who'])} {look['character']}"}


def pictures_for(kind: str, entry: dict, look: dict, sheet: bool, cast: dict | None = None) -> list[dict]:
    """The draw_many items that make one catalogue entry in the look, in the order they depend on each other. With
    cast, a pose is that character's: named <cast>_<pose> and drawn from its own model sheet."""
    ref = {"style_ref_asset": SHEET_ASSET} if sheet else {}
    if kind == "pose":
        eid, who = entry["id"], look.get("who", "")
        if cast:
            eid, who = f"{cast['id']}_{eid}", CAST_WHO.format(who=cast["who"])
            ref = {"style_ref_asset": cast_sheet(cast)}
        shut = look.get("mouth") == "shut"      # nobody speaks on screen: the pose itself is the closed mouth
        frame = POSE_FRAME.format(view=entry["view"], mouth=MOUTH_SHUT if shut else MOUTH_OPEN)
        base = {"id": eid, "cutout": True, "size": "2:3", **ref,
                "prompt": f"{who}, {entry['pose']}. {frame} {look['character']}"}
        out = [base] if shut else [base, {"id": f"{eid}_shut", "prompt": SHUT_PROMPT, "twin_of": eid}]
        if entry.get("blink", True) and look.get("blink", True) is not False:
            out.append({"id": f"{eid}_blink", "prompt": BLINK_PROMPT, "twin_of": eid if shut else f"{eid}_shut"})
        return out
    if kind == "set":
        plate, *pieces = entry["layers"]
        pid = f"{entry['id']}_{plate['name']}"
        out = [{"id": pid, "prompt": f"{plate['description']}. {PLATE_FLOOR} {look['set']}", **ref}]
        return out + [{"id": f"{entry['id']}_{p['name']}", "cutout": True, "match_asset": pid,
                       "prompt": f"{p['description']}, {PIECE_FRAME}. {look['set']}"} for p in pieces]
    return [{"id": entry["id"], "cutout": True, **ref,
             "prompt": f"{entry['description']}, {PIECE_FRAME}. {look['prop']}"}]


# ------------------------------------------------------------------ stock(project, kind, name)
def listing(root: Path, kind: str = "", name: str = "") -> str:
    stock = stock_of(root)
    if name:
        return _one(stock, *parse_ref(name if ":" in name or not kind else f"{kind}:{name}", stock))
    kinds = [kind_of(kind)] if kind else list(KINDS)
    look, why = read_look(stock)
    rows = [f"Stock in {stock} ({LOOK_FILE}: {'set' if look else why})"]
    missing_rows = []
    for k in kinds:
        held = items(stock, k)
        rows.append(f"{KINDS[k]} in stock ({len(held)}):" + ("" if held else " none"))
        rows += [f"- {k}:{i} {_short(m)}" for i, m in held.items()]
        left = [e for i, e in catalogue()[k].items() if i not in held]
        if kind:
            missing_rows += [f"- {k}:{e['id']}: {e['what']}" for e in left]
        elif left:
            missing_rows.append(f"{KINDS[k]} ({len(left)}): {', '.join(e['id'] for e in left)}")
    if missing_rows:
        rows += ["Catalogue, not yet in stock (take draws them in the look and keeps them):", *missing_rows]
    if look and not look.get("who") and "pose" in kinds:
        rows.append('This workspace has no fixed character: a catalogue pose is drawn for a character of this film, '
                    'take(project, ["pose:<id>"], cast="granny", who="<what it is and wears>"), as '
                    "<cast>_<pose> with its twins, from the model sheet <cast>_sheet (drawn first when the project "
                    "has none). They stay in the project.")
    rows.append('stock(project, name="pose:<id>") shows one in full; take(project, ["pose:<id>", "set:<id>", '
                '"prop:<id>"]) brings them into this project; keep saves your own drawings to stock.')
    return "\n".join(rows)


def _short(meta: dict) -> str:
    if meta["kind"] == "pose":
        twins = [t for t in TWINS if t in (meta.get("files") or {})]
        feet = f"; feet {meta['feet']:.2f}" if isinstance(meta.get("feet"), (int, float)) else ""
        return f"[{' '.join(twins) or 'no twins'}{feet}] {meta.get('what', '')}"
    if meta["kind"] == "set":
        return f"[{', '.join(layer['name'] for layer in meta.get('layers') or [])}] {meta.get('what', '')}"
    return meta.get("what", "")


def _one(stock: Path, kind: str, item_id: str) -> str:
    meta = items(stock, kind).get(item_id)
    if meta is not None:
        folder = stock / KINDS[kind]
        files = [f"- {aid}: {folder / f['file']} ({f.get('width')}x{f.get('height')}"
                 f"{', cut-out' if f.get('alpha') else ''})" for aid, f in files_of(meta)]
        return "\n".join([f"{kind}:{item_id} in stock: {meta.get('what', '')}", "files (asset ids take gives them):",
                          *files, "meta:", json.dumps(meta, ensure_ascii=False, indent=1)])
    entry = catalogue()[kind].get(item_id)
    if entry is None:
        near = [i for i in (*items(stock, kind), *catalogue()[kind]) if item_id[:3] in i][:8]
        raise StockError(f"no {kind} {item_id!r} in stock or the catalogue" + (f"; near: {', '.join(near)}" if near
                                                                                  else ""))
    look, why = read_look(stock)
    rows = [f"{kind}:{item_id} is in the catalogue, not in stock: {entry['what']}"]
    if not look:
        return "\n".join(rows + [f"take cannot draw it yet: {why}", json.dumps(entry, ensure_ascii=False)])
    cast = {"id": "<cast>", "who": "<who>"} if kind == "pose" and not look.get("who") else None
    pics = pictures_for(kind, entry, look, bool(look.get("sheet")), cast)
    rows.append(f"take draws it in {len(pics)} picture(s), in this order"
                + (" (for the cast member you name; its model sheet first if the project has none):" if cast else ":"))
    rows += [f"- {json.dumps(p, ensure_ascii=False)}" for p in pics]
    return "\n".join(rows)


# ------------------------------------------------------------------ files
def picture_facts(path: Path) -> dict:
    from PIL import Image
    with Image.open(path) as im:
        alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        return {"width": im.width, "height": im.height, "alpha": alpha}


def _copy(src: Path, dst: Path) -> None:
    if dst.exists() and os.path.samefile(src, dst):
        return
    part = dst.with_name(f".{dst.stem}.{uuid.uuid4().hex[:6]}.part{dst.suffix}")
    try:
        shutil.copyfile(src, part)
        os.replace(part, dst)
    finally:
        part.unlink(missing_ok=True)


def save_item(stock: Path, kind: str, item_id: str, parts: list[tuple[str, Path]], meta: dict,
              replace: bool = False) -> dict:
    """Copy an item's pictures into stock and write its <id>.json; parts are (role, file): a pose's "src" and twin
    suffixes, a set's layer names back to front, a prop's "file"."""
    if not ID.match(item_id):
        raise StockError(f"stock id {item_id!r} must be 1-48 lowercase letters, digits or _, starting with a letter "
                         "or digit")
    folder = stock / KINDS[kind]
    meta_path = folder / f"{item_id}.json"
    old = items(stock, kind).get(item_id)
    if (old is not None or meta_path.exists()) and not replace:
        raise StockError(f"{kind}:{item_id} is already in stock: pass replace=true to overwrite it, or keep it under "
                         "another name")
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for role, src in parts:
        aid = item_id if role in ("src", "file") else f"{item_id}_{role}"
        dst = folder / f"{aid}{src.suffix.lower()}"
        _copy(src, dst)
        entries.append((role, {"file": dst.name, **picture_facts(dst)}))
    if old is not None:
        kept = {e["file"] for _, e in entries}
        for _, f in files_of(old):
            if f.get("file") not in kept:
                (folder / str(f.get("file"))).unlink(missing_ok=True)
    front = set(meta.pop("front", ()))
    first = entries[0][1]
    meta = {"id": item_id, "kind": kind, **meta, "width": first["width"], "height": first["height"],
            "made": date.today().isoformat()}
    if kind == "pose":
        meta["files"] = dict(entries)
        meta["twins"] = [r for r, _ in entries[1:]]
        meta["feet"] = D.feet_of(folder / first["file"])
    elif kind == "set":
        meta["layers"] = [{"name": r, **e, "front": r in front} for r, e in entries]
    else:
        meta["file"] = first
        meta.setdefault("anchor", None)
    part = meta_path.with_name(f".{meta_path.stem}.{uuid.uuid4().hex[:6]}.part")
    try:
        part.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(part, meta_path)
    finally:
        part.unlink(missing_ok=True)
    return meta


def _project_picture(root: Path, assets: dict, aid: str) -> Path:
    entry = assets.get(aid)
    if not isinstance(entry, dict) or entry.get("kind") != "image":
        raise StockError(f"{aid!r} is not an image asset of this project (see assets)")
    path = project_file(root, entry.get("path"))
    if path is None or not path.is_file() or path.suffix.lower() not in PICTURES:
        raise StockError(f"asset {aid!r}: its file {entry.get('path')!r} is missing or not a picture")
    return path


def _put(ctx, assets: dict, kind: str, meta: dict, folder: Path) -> list[str]:
    """Copy an item's pictures into the project's assets and register them; refused whole, before any copy, when an
    asset id already holds another picture."""
    plan = []
    for aid, f in files_of(meta):
        src = folder / f["file"]
        if not src.is_file():
            raise StockError(f"its file {src.name} is missing from stock: keep it again or delete {meta['id']}.json")
        old = assets.get(aid)
        here = project_file(ctx.project, old.get("path")) if isinstance(old, dict) else None
        if old is not None and not (here is not None and here.is_file() and filecmp.cmp(here, src, shallow=False)):
            raise StockError(f"asset {aid!r} already holds another picture in this project: keep it to stock, or "
                             "remove_asset it, then take again")
        plan.append((aid, f, src))
    ctx.assets_dir.mkdir(parents=True, exist_ok=True)
    for aid, f, src in plan:
        rel = f"assets/{aid}{src.suffix.lower()}"
        _copy(src, ctx.project / rel)
        note = f"stock {kind}:{meta['id']}" + (f" (feet {meta['feet']:.2f})" if aid == meta["id"] and
                                              isinstance(meta.get("feet"), (int, float)) else "")
        register_asset(ctx, aid, {"path": rel, "kind": "image", "alpha": True if f.get("alpha") else None,
                                  "width": f.get("width"), "height": f.get("height"), "note": note})
    return [aid for aid, _, _ in plan]


# ------------------------------------------------------------------ take(project, items)
def take(root: Path, refs, cast=None, provider=None) -> tuple[str, bool]:
    """(text, is_error): stock items into the project; catalogue items not in stock drawn in the look first. With
    cast, every pose asked for is drawn for that character of the film and stays in the project."""
    stock = stock_of(root)
    refs = [refs] if isinstance(refs, str) else refs
    if not isinstance(refs, list) or not 1 <= len(refs) <= 24:
        raise StockError('items must be a list of 1-24 names like ["pose:shrug", "set:kitchen", "prop:coin"]')
    cast = cast_of(cast)
    wanted = list(dict.fromkeys(parse_ref(r, stock) for r in refs))
    ctx = context(root)
    assets = read_project(ctx).get("assets") or {}
    look, why = read_look(stock)
    sheet = project_file(stock, look["sheet"]) if look and look.get("sheet") else None
    sheet = sheet if sheet is not None and sheet.is_file() and sheet.suffix.lower() in PICTURES else None
    said, to_draw, own = {}, [], {}
    for kind, iid in wanted:
        mine = cast if kind == "pose" else None
        if mine is None and iid in items(stock, kind):
            continue
        entry = catalogue()[kind].get(iid)
        if entry is None and mine:
            said[(kind, iid)] = ("failed: not in the catalogue (stock(project, kind='pose') lists it): draw this pose "
                                 f"yourself with style_ref_asset={cast_sheet(mine)!r}")
        elif entry is None:
            said[(kind, iid)] = f"failed: not in stock or the catalogue (stock(project, kind={kind!r}) lists both)"
        elif look is None:
            said[(kind, iid)] = (f"failed: {'drawing it' if mine else 'not in stock, and drawing it'} needs the "
                                 f"workspace's look: {why}")
        elif kind == "pose" and mine is None and not look.get("who"):
            said[(kind, iid)] = ('failed: this workspace has no fixed character (look.json has no "who"): pass cast '
                                 f"and the pose is drawn for that character of this film; {CAST_HELP}")
        elif kind == "pose" and mine is None and sheet is None:
            said[(kind, iid)] = (f"failed: look.json's sheet {look.get('sheet')!r} is not a picture in {stock}: poses "
                                 "are drawn in the style of the character's model sheet")
        else:
            pics = pictures_for(kind, entry, look, sheet is not None, mine)
            held = [p["id"] for p in pics if p["id"] in assets]
            if mine and pics[0]["id"] in held:
                own[(kind, iid)] = pics                     # this character's pose is already in the project
                said[(kind, iid)] = f"already in this project as {mine['id']}'s"
            elif held:
                said[(kind, iid)] = (f"failed: the project already has asset(s) {', '.join(held)}: "
                                     + ("" if mine else "keep them to stock or ") + "remove_asset them, then take again")
            else:
                to_draw.append((kind, iid, entry, pics))
    reports = []
    if cast and any(t[0] == "pose" for t in to_draw) and cast_sheet(cast) not in assets:
        reports.append(_draw_sheet(root, ctx, sheet, sheet_picture(cast, look, sheet is not None), provider))
        if not re.search(rf"^1\. {cast_sheet(cast)}: ok,", reports[-1], re.M):
            for kind, iid, *_ in [t for t in to_draw if t[0] == "pose"]:
                said[(kind, iid)] = f"failed: {cast['id']}'s model sheet {cast_sheet(cast)} was not drawn (see below)"
            to_draw = [t for t in to_draw if t[0] != "pose"]
    reports += _draw_all(root, ctx, sheet, to_draw, provider) if to_draw else []
    drawn_ok = {m for text in reports for m in re.findall(r"^\d+\. (\S+): ok,", text, re.M)}
    drawn_ok -= _misplaced_blinks(reports)
    for kind, iid, entry, pics in to_draw:
        if kind == "pose" and cast:
            if pics[0]["id"] in drawn_ok:
                lost = [p["id"] for p in pics if p["id"] not in drawn_ok]
                own[(kind, iid)] = [p for p in pics if p["id"] in drawn_ok]
                said[(kind, iid)] = f"drawn for {cast['id']} from {cast_sheet(cast)}" + (
                    f"; without {', '.join(lost)} (failed or not a twin: usable without it)" if lost else "")
            else:
                said[(kind, iid)] = f"failed: {pics[0]['id']} was not drawn (see the draw report below)"
            continue
        try:
            said[(kind, iid)] = _keep_drawn(root, stock, kind, entry, pics, drawn_ok)
        except StockError as exc:
            said[(kind, iid)] = f"failed: drawn, but not kept: {exc}"
    taken, rows = [], []
    for kind, iid in wanted:
        line = said.get((kind, iid), "")
        if (kind, iid) in own:
            meta = _own_pose(root, own[(kind, iid)])
            line = f"{line}: assets {', '.join(aid for aid, _ in files_of(meta))}"
            taken.append(meta)
        elif not line.startswith("failed"):
            meta = items(stock, kind)[iid]
            try:
                ids = _put(ctx, read_project(ctx).get("assets") or {}, kind, meta, stock / KINDS[kind])
                line = f"{line or 'from stock'}: assets {', '.join(ids)}"
                taken.append(meta)
            except StockError as exc:
                line = f"failed: {exc}"
        rows.append(f"- {kind}:{iid}: {line}")
    head = f"Took {len(taken)} of {len(wanted)} item(s) into this project."
    if cast and own:
        head += (f" {cast['id']}'s poses are drawn from the model sheet {cast_sheet(cast)}: look at it and at one pose "
                 "beside it before taking more. A wrong design: remove_asset the sheet and its poses, then take with "
                 "a clearer who.")
    text = "\n".join([head, *rows, *(["Drawing:", *reports] if reports else []), *_for_components(taken)])
    return text, not taken


def _misplaced_blinks(reports: list[str]) -> set[str]:
    """Blink twins the draw patched at or below their pose's mouth: the wrong part (a hand, a shoe), not the eyes."""
    down = {aid: int(pct) for text in reports for aid, pct in
            re.findall(r"^\d+\. (\S+): ok,.*?its middle (\d+)% of the way down", text, re.M)}
    return {aid for aid, pct in down.items() if aid.endswith("_blink")
            and pct >= down.get(f"{aid[:-len('_blink')]}_shut", 101)}


def _own_pose(root: Path, pics: list[dict]) -> dict:
    """A stock-shaped meta for a cast member's pose that lives in the project's assets: the twins asked for that
    sit on the pose's own canvas (a redraw that was not a twin has another size)."""
    assets = read_project(context(root)).get("assets") or {}
    base = pics[0]["id"]
    size = lambda aid: (assets[aid].get("width"), assets[aid].get("height"))  # noqa: E731
    files = {"src": {"file": base}}
    files.update({t: {"file": f"{base}_{t}"} for t in TWINS if f"{base}_{t}" in {p["id"] for p in pics}
                  and isinstance(assets.get(f"{base}_{t}"), dict) and size(f"{base}_{t}") == size(base)})
    meta = {"id": base, "kind": "pose", "files": files}
    try:
        meta["feet"] = D.feet_of(_project_picture(root, assets, base))
    except (StockError, OSError, ValueError):
        pass
    return meta


def _register_sheet(ctx, sheet: Path) -> None:
    ctx.assets_dir.mkdir(parents=True, exist_ok=True)
    rel = f"assets/{SHEET_ASSET}{sheet.suffix.lower()}"
    _copy(sheet, ctx.project / rel)
    facts = picture_facts(ctx.project / rel)
    register_asset(ctx, SHEET_ASSET, {"path": rel, "kind": "image", "alpha": True if facts["alpha"] else None,
                                      "width": facts["width"], "height": facts["height"],
                                      "note": "the workspace's look sheet (stock look.json)"})


def _draw_sheet(root: Path, ctx, sheet, picture: dict, provider) -> str:
    if sheet is not None:
        _register_sheet(ctx, sheet)
    return str(D.draw_many(root, pictures=[picture], provider=provider)[0])


def _draw_all(root: Path, ctx, sheet, to_draw, provider) -> list[str]:
    """draw_many in batches of whole items, so a twin never waits on a picture of another batch."""
    if sheet is not None:
        _register_sheet(ctx, sheet)
    batches, batch = [], []
    for _, _, _, pics in to_draw:
        if batch and len(batch) + len(pics) > D.BATCH_MAX:
            batches.append(batch)
            batch = []
        batch += pics
    batches.append(batch)
    return [str(D.draw_many(root, pictures=b, provider=provider)[0]) for b in batches]


def _keep_drawn(root: Path, stock: Path, kind: str, entry: dict, pics: list[dict], ok: set[str]) -> str:
    first = pics[0]["id"]
    if first not in ok:
        return f"failed: {first} was not drawn (see the draw report below)"
    assets = read_project(context(root)).get("assets") or {}
    parts, lost = [], []
    for p in pics:
        role = "src" if p["id"] == entry["id"] else "file" if kind == "prop" else p["id"][len(entry["id"]) + 1:]
        # a blink drawn on a shut twin that failed would sit on another canvas
        if p["id"] in ok and not (role == "blink" and f"{entry['id']}_shut" in lost):
            parts.append((role, _project_picture(root, assets, p["id"])))
        else:
            lost.append(p["id"])
    meta = {"what": entry["what"], "tags": [entry.get("group", "")], "prompt": pics[0]["prompt"]}
    if kind == "pose":
        meta["view"] = entry.get("view")
    if kind == "set":
        meta["front"] = [layer["name"] for layer in entry["layers"][1:]]
    save_item(stock, kind, entry["id"], parts, meta)
    without = f"; without {', '.join(lost)} (failed or not a twin: usable without it)" if lost else ""
    return f"drawn in the look and kept in stock{without}"


def _js_key(name: str) -> str:
    return name if re.match(r"^[a-z_][a-z0-9_]*$", name) else json.dumps(name)


def _for_components(taken: list[dict]) -> list[str]:
    """What a component needs: the poses manifest, the sets' layer order, the clip's pics."""
    rows, poses, pics = [], [], {}
    for meta in taken:
        for aid, _ in files_of(meta):
            pics[f"{aid}_asset"] = aid
        if meta["kind"] == "pose":
            parts = [f"src: a.{meta['id']}_asset"] + [f"{TWINS[t]}: a.{meta['id']}_{t}_asset" for t in TWINS
                                                      if t in meta.get("files", {})]
            if isinstance(meta.get("feet"), (int, float)):
                parts.append(f"feet: {meta['feet']:.2f}")
            poses.append(f"{_js_key(meta['id'])}: {{ {', '.join(parts)} }}")
        elif meta["kind"] == "set":
            back = [f"{meta['id']}_{x['name']}" for x in meta["layers"] if not x.get("front")]
            front = [f"{meta['id']}_{x['name']}" for x in meta["layers"] if x.get("front")]
            rows.append(f"set {meta['id']} back to front: {', '.join(back)}, the figure"
                        + (f", {', '.join(front)} (a cut-out at its own size: place it at the plate's scale, the "
                           "figure standing behind it)" if front else ""))
    if poses:
        rows.insert(0, "const poses = { " + ", ".join(poses) + " };")
    if pics:
        rows.append('clip props: "pics": ' + json.dumps(pics, ensure_ascii=False))
    return ["For the component:", *rows] if rows else []


# ------------------------------------------------------------------ keep(project, ids, kind)
def keep(root: Path, ids, kind, what: str = "", name: str = "", replace: bool = False) -> str:
    stock = stock_of(root)
    kind = kind_of(kind)
    ids = [ids] if isinstance(ids, str) else ids
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip() for i in ids):
        raise StockError("ids must be a non-empty list of the project's image asset ids")
    ids = [i.strip() for i in ids]
    assets = read_project(context(root)).get("assets") or {}
    tags = lambda iid: [catalogue()[kind][iid].get("group", "")] if iid in catalogue()[kind] else []  # noqa: E731
    what_of = lambda iid, aid: (what.strip() or catalogue()[kind].get(iid, {}).get("what")  # noqa: E731
                                or str(assets[aid].get("note") or aid)[:80])
    if kind == "set":
        sid = (name or _common_prefix(ids)).strip().lower()
        if not sid:
            raise StockError('the layers share no "<set>_" prefix: pass name, the set\'s stock id')
        layers = [(i[len(sid) + 1:].lower() if i.lower().startswith(sid + "_") else i.lower(),
                   _project_picture(root, assets, i)) for i in ids]
        front = [n for n, p in layers[1:] if picture_facts(p)["alpha"]]
        meta = save_item(stock, kind, sid, layers, {"what": what_of(sid, ids[0]), "tags": tags(sid),
                                                    "prompt": str(assets[ids[0]].get("note") or ""), "front": front},
                         replace)
        return f"Kept set:{sid} in {stock / KINDS[kind]}: layers back to front {', '.join(n for n, _ in layers)}."
    rows = []
    for aid in ids:
        iid = aid.lower()
        parts = [("src" if kind == "pose" else "file", _project_picture(root, assets, aid))]
        if kind == "pose":
            parts += [(t, _project_picture(root, assets, f"{aid}_{t}")) for t in TWINS if f"{aid}_{t}" in assets]
        meta = save_item(stock, kind, iid, parts, {"what": what_of(iid, aid), "tags": tags(iid),
                                                   "prompt": str(assets[aid].get("note") or "")}, replace)
        twins = ""
        if kind == "pose":
            twins = f" with {', '.join(meta['twins'])}" if meta["twins"] else " (no twins found by name)"
            if isinstance(meta.get("feet"), float):
                twins += f", feet {meta['feet']:.2f}"
        rows.append(f"- {kind}:{iid}{twins}")
    return f"Kept {len(rows)} {KINDS[kind]} in {stock / KINDS[kind]}:\n" + "\n".join(rows)


def _common_prefix(ids: list[str]) -> str:
    heads = {i.rsplit("_", 1)[0].lower() for i in ids if "_" in i}
    return heads.pop() if len(heads) == 1 and all("_" in i for i in ids) else ""
