"""Edit ops (spec 5): a batch applies atomically to project.json, is validated, and is undoable.

A batch is refused (file untouched) when it fails, or when the result has validation errors the project did not
have before it: errors that were already there do not block edits that leave them alone (or fix others).
Before each write the previous project.json is kept as .history/NNNN.json; undo puts one back.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import document as D
from . import timeexpr as T
from .issues import Issue
from .workspace import project_root

HISTORY = ".history"
HISTORY_KEEP = 500
SNAPSHOT = re.compile(r"^(\d{4,})\.json$")
DRAW_DEFAULT_S = 0.6                # the shape draw-on length the renderer uses without progress keyframes
HIGHLIGHT_DEFAULT_S = 0.3           # where the evidence sweep starts without highlight.at
SHARING_TRIES = 20                  # ~4 s of backoff while Windows reports project.json held open by another program

OPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {   # op: (required, optional)
    "add_track": (("track",), ("index",)),
    "update_track": (("id", "set"), ()),
    "remove_track": (("id",), ()),
    "add_clip": (("track", "clip"), ()),
    "update_clip": (("id", "set"), ()),
    "remove_clip": (("id",), ()),
    "move_clip": (("id",), ("start", "end", "dur", "track")),
    "split_clip": (("id", "at", "new_id"), ()),
    "set_keyframes": (("id", "prop", "frames"), ()),
    "add_asset": (("id", "asset"), ()),
    "update_asset": (("id", "set"), ()),
    "remove_asset": (("id",), ()),
    "set": (("path", "value"), ()),
    "ripple_delete": (("start", "end"), ("tracks",)),
    "insert_gap": (("at", "dur"), ("tracks",)),
    "trim_clip": (("id",), ("in", "out", "ripple")),
}

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class OpError(ValueError):
    """An op that cannot be applied as written; the message says what to change."""


def _lock(root: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(root).lower(), threading.Lock())


# ------------------------------------------------------------------ finding things
def _tracks(data: dict) -> list:
    tracks = data.setdefault("tracks", [])
    if not isinstance(tracks, list):
        raise OpError("project.json \"tracks\" is not a list: fix the file by hand")
    return tracks


def _track_ids(data: dict) -> list[str]:
    return [t.get("id") for t in _tracks(data) if isinstance(t, dict)]


def _find_track(data: dict, tid) -> tuple[int, dict]:
    for n, t in enumerate(_tracks(data)):
        if isinstance(t, dict) and t.get("id") == tid:
            return n, t
    raise OpError(f"no track {tid!r}; tracks: {', '.join(map(str, _track_ids(data))) or 'none yet (add_track)'}")


def _clip_lists(data: dict):
    for t in _tracks(data):
        clips = t.get("clips") if isinstance(t, dict) else None
        if isinstance(clips, list):
            yield t, clips


def _find_clip(data: dict, cid) -> tuple[dict, int, dict]:
    for t, clips in _clip_lists(data):
        for n, c in enumerate(clips):
            if isinstance(c, dict) and c.get("id") == cid:
                return t, n, c
    known = [c.get("id") for _, cl in _clip_lists(data) for c in cl if isinstance(c, dict)]
    shown = ", ".join(map(str, known[:30])) + (" ..." if len(known) > 30 else "")
    raise OpError(f"no clip {cid!r}; clips: {shown or 'none yet (add_clip)'}")


def _used_ids(data: dict) -> set:
    ids = set(_track_ids(data))
    ids |= {c.get("id") for _, cl in _clip_lists(data) for c in cl if isinstance(c, dict)}
    return ids


def _new_id(data: dict, ident, what: str) -> str:
    if not isinstance(ident, str) or not D.ID.match(ident):
        raise OpError(f"{what} id {ident!r}: use 1-64 letters, digits, _ or - (no spaces or dots)")
    if ident in _used_ids(data):
        raise OpError(f"id {ident!r} is taken (clips and tracks share one set of ids): pick another")
    return ident


def _obj(op: dict, key: str) -> dict:
    value = op.get(key)
    if not isinstance(value, dict):
        raise OpError(f"{key} must be an object {{...}}")
    return value


# ------------------------------------------------------------------ merging and times in raw data
def merge(dst: dict, src: dict, path: str = "") -> list[str]:
    """Deep-merge src into dst (null removes a key; lists and other values replace); the changed paths."""
    changed: list[str] = []
    for k, v in src.items():
        p = f"{path}.{k}" if path else str(k)
        if v is None:
            if k in dst:
                dst.pop(k)
                changed.append(f"{p} (removed)")
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            changed += merge(dst[k], v, p)
        else:
            dst[k] = copy.deepcopy(v)
            changed.append(p)
    return changed


def _time_slots(data: dict):
    """(container, key) for every place a Time string may sit in the raw project."""
    if "duration" in data:
        yield data, "duration"
    markers = data.get("markers")
    if isinstance(markers, dict):
        yield from ((markers, k) for k in markers)
    chapters = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    yield from ((ch, "at") for ch in chapters if isinstance(ch, dict) and "at" in ch)
    for t in _tracks(data):
        if not isinstance(t, dict):
            continue
        items = t.get("items") if isinstance(t.get("items"), list) else []
        for it in items:
            if isinstance(it, dict):
                yield from ((it, k) for k in ("start", "end") if k in it)
        clips = t.get("clips") if isinstance(t.get("clips"), list) else []
        for c in clips:
            if isinstance(c, dict):
                yield from _clip_slots(c)


def _clip_slots(c: dict):
    yield from ((c, k) for k in ("start", "end") if k in c)
    kf = c.get("keyframes")
    if isinstance(kf, dict):
        for frames in kf.values():
            for k in frames if isinstance(frames, list) else []:
                if isinstance(k, dict) and "t" in k:
                    yield k, "t"
    hl = c.get("highlight")
    if isinstance(hl, dict) and "at" in hl:
        yield hl, "at"
    yield from _prop_slots(c.get("props"))


def _prop_slots(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and D.TIME_KEY.match(k) and isinstance(v, str):
                yield value, k
            else:
                yield from _prop_slots(v)
    elif isinstance(value, list):
        for v in value:
            yield from _prop_slots(v)


def retarget(data: dict, old: str, new: str, end_only: bool = False, skip: tuple = ()) -> int:
    """Point Time strings at clip `old` (only its .end with end_only) to clip `new`; how many changed."""
    count = 0
    for holder, key in _time_slots(data):
        if any(holder is s for s in skip):
            continue
        value = holder.get(key)
        if not isinstance(value, str):
            continue
        try:
            e = T.parse(value)
        except T.TimeError:
            continue
        if e.anchor == "clip" and e.ref == old and (e.at_end or not end_only):
            holder[key] = str(T.TimeExpr("clip", new, e.at_end, e.offset))
            count += 1
        elif e.anchor == "src" and e.ref == old and not end_only:
            holder[key] = str(T.TimeExpr("src", new, False, e.offset, e.at))
            count += 1
    return count


def _refers_to(value, cid: str) -> bool:
    try:
        e = T.parse(value)
    except T.TimeError:
        return False
    return e.anchor == "clip" and e.ref == cid


# ------------------------------------------------------------------ timing the current state
class _Now:
    """The project as it stands mid-batch: its document, schedule and fps."""

    def __init__(self, root: Path, data: dict, why: str):
        try:
            self.doc = D.parse(data)
        except D.DocumentError as exc:
            raise OpError(f"{why} needs a project that fits the format first: {exc}") from None
        voice, _ = D.load_voice(root, self.doc.voice)
        self.sched = D.schedule(self.doc, voice)
        try:
            self.profile = D.profile_of(root, self.doc)
        except ValueError as exc:
            raise OpError(str(exc)) from None
        self.fps = self.profile.fps

    def span(self, cid: str) -> tuple[float, float]:
        try:
            return self.sched.span(cid)
        except T.TimeError as exc:
            raise OpError(f"clip {cid} cannot be timed: {exc}") from None

    def time(self, value, what: str) -> float:
        try:
            return T.resolve(value, self.sched)
        except T.TimeError as exc:
            raise OpError(f"{what}: {exc}") from None

    def frame(self, seconds: float) -> int:
        return T.to_frame(seconds, self.fps)

    def box_size(self, clip: dict) -> tuple[float, float]:
        box = clip.get("box", "full")
        if isinstance(box, dict):
            return float(box.get("w") or 0), float(box.get("h") or 0)
        if box == "safe":
            return float(self.profile.safe.w), float(self.profile.safe.h)
        return float(self.profile.width), float(self.profile.height)


# ------------------------------------------------------------------ the ops
def _add_track(root, data, op) -> tuple[str, list]:
    track = copy.deepcopy(_obj(op, "track"))
    tid = _new_id(data, track.get("id"), "track")
    kind = track.get("kind")
    if kind not in D.TRACK_KINDS:
        raise OpError(f"track kind {kind!r}: one of {', '.join(D.TRACK_KINDS)}")
    if kind != "captions":
        track.setdefault("clips", [])
    tracks = _tracks(data)
    index = op.get("index")
    if index is None:
        tracks.append(track)
        where = "on top"
    else:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= len(tracks):
            raise OpError(f"index {index!r}: a position 0-{len(tracks)} (0 = bottom, {len(tracks)} = top)")
        tracks.insert(index, track)
        where = f"at position {index}"
    return f"added {kind} track {tid} {where}", [c.get("id") for c in track.get("clips") or [] if isinstance(c, dict)]


def _update_track(root, data, op) -> tuple[str, list]:
    _, track = _find_track(data, op["id"])
    changes = _obj(op, "set")
    if "id" in changes and changes["id"] != track.get("id"):
        _new_id(data, changes["id"], "track")
    changed = merge(track, changes)
    return f"updated track {op['id']}: {', '.join(changed) or 'no change'}", []


def _remove_track(root, data, op) -> tuple[str, list]:
    n, track = _find_track(data, op["id"])
    _tracks(data).pop(n)
    clips = [c.get("id") for c in track.get("clips") or [] if isinstance(c, dict)]
    with_clips = f" with {len(clips)} clip(s): {', '.join(map(str, clips))}" if clips else ""
    return f"removed track {op['id']}{with_clips}", []


def _add_clip(root, data, op) -> tuple[str, list]:
    _, track = _find_track(data, op["track"])
    if track.get("kind") == "captions":
        raise OpError(f"track {op['track']} is a captions track: clips go on visual or audio tracks")
    clip = copy.deepcopy(_obj(op, "clip"))
    cid = _new_id(data, clip.get("id"), "clip")
    if track.get("kind") == "audio" and clip.get("type", "audio") != "audio":
        raise OpError(f"track {op['track']} is an audio track: a {clip.get('type')} clip goes on a visual track")
    if track.get("kind") == "visual" and clip.get("type") == "audio":
        raise OpError(f"track {op['track']} is a visual track: audio clips go on an audio track")
    clips = track.setdefault("clips", [])
    if not isinstance(clips, list):
        raise OpError(f"track {op['track']} \"clips\" is not a list: fix the file by hand")
    clips.append(clip)
    return f"added {clip.get('type', '?')} clip {cid} to {op['track']}", [cid]


def _length_rule(clip: dict, changes: dict) -> None:
    """end and dur exclude each other: setting one drops the other."""
    if changes.get("end") is not None and "dur" not in changes:
        clip.pop("dur", None)
    if changes.get("dur") is not None and "end" not in changes:
        clip.pop("end", None)


def _update_clip(root, data, op) -> tuple[str, list]:
    _, _, clip = _find_clip(data, op["id"])
    changes = _obj(op, "set")
    old = clip.get("id")
    new = changes.get("id", old)
    if new != old:
        _new_id(data, new, "clip")
    _length_rule(clip, changes)
    changed = merge(clip, changes)
    text = f"updated clip {old}: {', '.join(changed) or 'no change'}"
    if new != old:
        moved = retarget(data, old, new)
        text += f" (renamed to {new}" + (f"; {moved} Time reference(s) follow it)" if moved else ")")
    return text, [new]


def _remove_clip(root, data, op) -> tuple[str, list]:
    track, n, clip = _find_clip(data, op["id"])
    track["clips"].pop(n)
    return f"removed {clip.get('type', '?')} clip {op['id']} from {track.get('id')}", []


def _move_clip(root, data, op) -> tuple[str, list]:
    cid = op["id"]
    track, n, clip = _find_clip(data, cid)
    keys = [k for k in ("start", "end", "dur", "track") if op.get(k) is not None]
    if not keys:
        raise OpError("nothing to move: give start, end, dur and/or track")
    if op.get("end") is not None and op.get("dur") is not None:
        raise OpError("give end or dur, not both")
    bits = []
    if op.get("start") is not None and op.get("end") is None and op.get("dur") is None and "end" in clip:
        a, b = _Now(root, data, "moving a clip").span(cid)     # keep its length
        clip.pop("end")
        clip["dur"] = round(b - a, 3)
        bits.append(f"length kept: dur {clip['dur']:g} s")
    for k in ("start", "end", "dur"):
        if op.get(k) is not None:
            clip[k] = copy.deepcopy(op[k])
    _length_rule(clip, {k: op.get(k) for k in ("end", "dur") if op.get(k) is not None})
    if op.get("track") is not None and op["track"] != track.get("id"):
        _, dest = _find_track(data, op["track"])
        want = "audio" if clip.get("type") == "audio" else "visual"
        if dest.get("kind") != want:
            raise OpError(f"track {op['track']} is a {dest.get('kind')} track: a {clip.get('type')} clip needs a "
                          f"{want} track")
        track["clips"].pop(n)
        dest.setdefault("clips", []).append(clip)
        bits.append(f"to track {op['track']}")
    what = ", ".join(f"{k} {op[k]}" for k in ("start", "end", "dur") if op.get(k) is not None)
    return f"moved clip {cid}" + (f": {what}" if what else "") + (f" ({'; '.join(bits)})" if bits else ""), [cid]


def _set_keyframes(root, data, op) -> tuple[str, list]:
    _, _, clip = _find_clip(data, op["id"])
    prop, frames = op["prop"], op["frames"]
    if prop not in D.KEYFRAME_PROPS:
        raise OpError(f"prop {prop!r}: one of {', '.join(D.KEYFRAME_PROPS)}")
    if clip.get("type") == "audio" and prop != "volume":
        raise OpError("audio clips have no keyframes except volume (and volume, fade_in, fade_out)")
    if not isinstance(frames, list) or not all(isinstance(k, dict) for k in frames):
        raise OpError('frames must be a list like [{"t": 0, "v": 1}, {"t": 1.5, "v": 1.2, "ease": "inOut"}]')
    kf = clip.get("keyframes")
    if not isinstance(kf, dict):
        kf = clip["keyframes"] = {}
    if frames:
        kf[prop] = copy.deepcopy(frames)
        text = f"set {len(frames)} keyframe(s) for {prop} on {op['id']}"
    else:
        kf.pop(prop, None)
        text = f"removed the {prop} keyframes of {op['id']}"
    if not kf:
        clip.pop("keyframes")
    return text, [op["id"]]


def _asset_users(data: dict, aid: str) -> list[str]:
    users = []
    for _, clips in _clip_lists(data):
        for c in clips:
            if not isinstance(c, dict):
                continue
            props = c.get("props") if isinstance(c.get("props"), dict) else {}
            if c.get("asset") == aid or any(k == "asset" and v == aid for _, k, v in D.prop_refs(props)):
                users.append(str(c.get("id")))
    return users


def _add_asset(root, data, op) -> tuple[str, list]:
    aid = op["id"]
    if not isinstance(aid, str) or not D.ID.match(aid):
        raise OpError(f"asset id {aid!r}: use 1-64 letters, digits, _ or -")
    asset = copy.deepcopy(_obj(op, "asset"))
    assets = data.setdefault("assets", {})
    if not isinstance(assets, dict):
        raise OpError("project.json \"assets\" is not an object: fix the file by hand")
    verb = "replaced" if aid in assets else "added"
    assets[aid] = asset
    return f"{verb} asset {aid} ({asset.get('kind', '?')} {asset.get('path', '?')})", []


def _find_asset(data: dict, aid) -> dict:
    assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    if not isinstance(aid, str) or aid not in assets:
        raise OpError(f"no asset {aid!r}; assets: {', '.join(assets) or 'none'}")
    return assets


def _update_asset(root, data, op) -> tuple[str, list]:
    aid = op["id"]
    asset = _find_asset(data, aid)[aid]
    changes = _obj(op, "set")
    if not isinstance(asset, dict):
        raise OpError(f"asset {aid!r} is not an object in project.json: replace it with add_asset")
    if "id" in changes:
        raise OpError("an asset's id is its key: add_asset under the new id, point the clips at it, then remove_asset")
    if "kind" in changes and changes["kind"] != asset.get("kind"):
        users = _asset_users(data, aid)
        if users:
            raise OpError(f"asset {aid!r} is used by clip(s) {', '.join(users)}: its kind cannot change from "
                          f"{asset.get('kind')!r} to {changes['kind']!r} while they use it")
    changed = merge(asset, changes)
    return f"updated asset {aid}: {', '.join(changed) or 'no change'}", []


def _remove_asset(root, data, op) -> tuple[str, list]:
    aid = op["id"]
    assets = _find_asset(data, aid)
    users = _asset_users(data, aid)
    if users:
        raise OpError(f"asset {aid!r} is used by clip(s) {', '.join(users)}: remove or change them first")
    assets.pop(aid)
    return f"removed asset {aid} (the file stays in the project folder)", []


def _set(root, data, op) -> tuple[str, list]:
    path = op["path"]
    if not isinstance(path, str) or not path.strip():
        raise OpError('path must be a dotted path like "meta.title"')
    parts = path.strip().split(".")
    if parts[0] in ("tracks", "assets"):
        raise OpError(f"set does not edit {parts[0]}: use the track, clip and asset ops")
    if any(not p for p in parts):
        raise OpError(f"path {path!r} has an empty part")
    node = data
    for p in parts[:-1]:
        node = _step(node, p, path)
    last, value = parts[-1], op["value"]
    if not isinstance(node, (dict, list)):
        raise OpError(f"{path}: {parts[-2]!r} holds a value, not an object: set {'.'.join(parts[:-1])} itself")
    if isinstance(node, list):
        i = _index(node, last, path, allow_end=value is not None)
        if value is None:
            node.pop(i)
        elif i == len(node):
            node.append(copy.deepcopy(value))
        else:
            node[i] = copy.deepcopy(value)
    elif value is None:
        if last not in node:
            return f"{path} was not set (no change)", []
        node.pop(last)
    else:
        node[last] = copy.deepcopy(value)
    shown = json.dumps(value, ensure_ascii=False)
    return (f"removed {path}" if value is None else f"set {path} = {shown[:60]}{'...' if len(shown) > 60 else ''}"), []


def _step(node, part: str, path: str):
    if isinstance(node, list):
        return node[_index(node, part, path)]
    if not isinstance(node, dict):
        raise OpError(f"{path}: {part!r} is inside a value that is not an object")
    if part not in node or node[part] is None:
        node[part] = {}
    return node[part]


def _index(node: list, part: str, path: str, allow_end: bool = False) -> int:
    if not (part.isascii() and part.isdigit()) or int(part) > len(node) - (0 if allow_end else 1):
        raise OpError(f"{path}: {part!r} is not a position in a list of {len(node)}")
    return int(part)


# ------------------------------------------------------------------ split
def _keyframe_frames(now: _Now, ks: list, start_f: int, cid: str, prop: str) -> list[dict]:
    rows = []
    for k in ks:
        try:
            f = T.clip_frame(k.get("t"), start_f, now.fps, now.sched)
        except T.TimeError as exc:
            raise OpError(f"clip {cid} keyframes.{prop}: {exc}") from None
        rows.append({"f": f, "v": float(k.get("v", 0)), "ease": k.get("ease"), "raw": k})
    return sorted(rows, key=lambda r: r["f"])


def split_keyframes(ks: list[dict], cut_f: int, fps: float) -> tuple[list[dict], list[dict]]:
    """Keyframes in frames ({"f", "v", "ease", "raw"}) cut at frame cut_f into two halves of project keyframes that
    render the same value on every frame as the uncut clip (valueAt). Numbers in the second half count from the cut.
    A cut inside an eased move (in, out, inOut, spring) bakes that move into one linear key per frame: an ease
    re-applied to two shorter spans would bend differently."""
    from .resolve import value_at
    value = value_at(ks, cut_f, fps)
    before = [k for k in ks if k["f"] <= cut_f]
    after = [k for k in ks if k["f"] > cut_f]
    first = [copy.deepcopy(k["raw"]) for k in before]
    second = [{"t": 0, "v": _num(value)}]
    within = bool(before and after) and before[-1]["f"] < cut_f
    ease = after[0]["ease"] if within else None
    if within and ease not in (None, "linear", "step"):
        a, b = before[-1]["f"], after[0]["f"]
        first += [{"t": round(f / fps, 4), "v": _num(value_at(ks, f, fps))} for f in range(a + 1, cut_f + 1)]
        second += [{"t": round((f - cut_f) / fps, 4), "v": _num(value_at(ks, f, fps))} for f in range(cut_f + 1, b)]
    elif not before or before[-1]["f"] < cut_f:
        cut = {"t": round(cut_f / fps, 4), "v": _num(value)}
        if ease:
            cut["ease"] = ease                  # linear and step cut exactly
        first.append(cut)
    for k in after:
        raw = copy.deepcopy(k["raw"])
        if T.counts_from_clip(raw.get("t")):
            raw["t"] = _seconds_for(T.parse(raw["t"]).offset - cut_f / fps, k["f"] - cut_f, fps)
        second.append(raw)
    return first, second


def _seconds_for(t: float, frame: int, fps: float):
    """t rounded for project.json, still landing on `frame` (a half-frame time may round to its neighbour)."""
    r = round(t, 4)
    return _num(r if T.to_frame(r, fps) == frame else round(frame / fps, 4))


def _num(v: float):
    v = round(float(v), 6)
    return int(v) if v.is_integer() else v


def _split_clip(root, data, op) -> tuple[str, list]:
    cid = op["id"]
    track, n, clip = _find_clip(data, cid)
    new = _new_id(data, op["new_id"], "clip")
    now = _Now(root, data, "split_clip")
    a, b = now.span(cid)
    at = op["at"]
    cut = now.time(at, "at")
    start_f, cut_f, end_f = now.frame(a), now.frame(cut), now.frame(b)
    if not start_f < cut_f < end_f:
        raise OpError(f"at {at!r} is {cut:.2f} s, not inside clip {cid} ({a:.2f}-{b:.2f} s)")
    at_expr = round(cut, 3) if _refers_to(at, cid) else copy.deepcopy(at)
    rel = cut_f - start_f
    had_end = "end" in clip
    notes = []

    first = clip
    motion = clip.get("motion") if clip.get("type") in ("image", "video") else None
    # the renderer's motion reaches its last value on the clip's last frame
    if _bake_motion(now, first, max(1, end_f - start_f - 1) / now.fps):
        notes.append(f"motion {motion!r} became zoom/pan keyframes on both halves (to give a half its own motion, "
                     "remove its zoom/pan keyframes first)")
    second = copy.deepcopy(first)
    kf = first.get("keyframes") or {}
    halves: tuple[dict, dict] = ({}, {})
    for prop, ks in kf.items():
        if not isinstance(ks, list) or not ks:
            continue
        rows = _keyframe_frames(now, ks, start_f, cid, prop)
        one, two = split_keyframes(rows, rel, now.fps)
        halves[0][prop], halves[1][prop] = one, two
    for half, k in zip((first, second), halves):
        if k:
            half["keyframes"] = k

    first.pop("dur", None)
    first["end"] = at_expr
    first.pop("exit", None)
    first.pop("fade_out", None)                 # the fades belong to the clip's own ends, not the cut
    second["id"] = new
    second["start"] = copy.deepcopy(at_expr)
    if not had_end:
        second.pop("end", None)
        second["dur"] = round(b - cut, 3)
    for key in ("enter", "transition", "fade_in"):
        second.pop(key, None)
    if second.get("type") in ("video", "audio"):
        rate = float(second.get("rate") or 1) if second.get("type") == "video" else 1.0
        trim = float(second.get("trim_in") or 0)
        second["trim_in"] = round(trim + rel / now.fps * rate, 3)
        source = _source_seconds(root, data, second.get("asset")) if second.get("loop") else None
        if source:                              # where the renderer's loop is at the cut (Media.tsx, AudioTrack.tsx)
            src_f, trim_f = math.floor(source * now.fps), T.to_frame(trim, now.fps)
            loop_f = math.floor((src_f - trim_f - 1) / rate if second["type"] == "video" else src_f - trim_f)
            if loop_f >= 1:
                second["trim_in"] = round((trim_f + rel % loop_f * rate) / now.fps, 3)
        if second.get("loop"):
            notes.append(f"{new} starts where the loop was at the cut and loops from there")
    if second.get("type") == "text" and second.pop("reveal", None) is not None:
        notes.append(f"{new} shows its text without the reveal")
    if second.get("type") == "shape" and second.get("draw") and "progress" not in (second.get("keyframes") or {}):
        n = max(1, T.to_frame(DRAW_DEFAULT_S, now.fps))
        if rel >= n:
            second["draw"] = False
        else:                                   # mid draw-on: the second half continues it frame by frame
            curve = [{"t": round(k / now.fps, 4), "v": _num(1 - (1 - (rel + k) / n) ** 3)} for k in range(n - rel + 1)]
            second.setdefault("keyframes", {})["progress"] = curve
    hl = second.get("highlight")
    if second.get("type") == "evidence" and isinstance(hl, dict) and hl.get("at") is None:
        hl["at"] = HIGHLIGHT_DEFAULT_S          # where the first half's sweep starts; shifted below
    for holder, key in _clip_time_slots(second):
        holder[key] = _after_cut(holder[key], rel, now.fps, cid)
    if second.get("type") == "component":
        notes.append(f"component props without their own at/*_at times start over in {new}")
    track["clips"].insert(n + 1, second)
    moved = retarget(data, cid, new, end_only=True, skip=(first,))
    if moved:
        notes.append(f"{moved} reference(s) to clip:{cid}.end now point at {new}")
    if second.get("type") in ("video", "audio") and not second.get("loop"):
        moved = _retarget_source(data, cid, new, float(second.get("trim_in") or 0))
        if moved:
            notes.append(f"{moved} src:{cid}@... reference(s) past the cut now name {new}")
    text = f"split clip {cid} at {cut:.2f} s into {cid} and {new}" + (f" ({'; '.join(notes)})" if notes else "")
    return text, [cid, new]


def _bake_motion(now: _Now, clip: dict, seconds: float) -> bool:
    """Turn motion into explicit keyframes (so both halves continue the same move); True when it did."""
    motion = clip.get("motion")
    if not motion or clip.get("type") not in ("image", "video"):
        return False
    from .resolve import motion_keyframes
    w, h = now.box_size(clip)
    kf = clip.get("keyframes") if isinstance(clip.get("keyframes"), dict) else {}
    made = motion_keyframes(motion, seconds, w, h)
    for prop, frames in made.items():
        if not kf.get(prop):
            kf[prop] = frames
    clip.pop("motion")
    if kf:
        clip["keyframes"] = kf
    return bool(made)


def _source_seconds(root: Path, data: dict, aid) -> float | None:
    assets = data.get("assets")
    asset = assets.get(aid) if isinstance(assets, dict) and isinstance(aid, str) else None
    if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
        return None
    from .resolve import media_duration
    return media_duration(root / asset["path"])


def _clip_time_slots(clip: dict):
    """(holder, key) for the Times inside a clip besides keyframes: highlight.at and component at / *_at props."""
    hl = clip.get("highlight")
    if isinstance(hl, dict) and hl.get("at") is not None:
        yield hl, "at"
    yield from _prop_time_slots(clip.get("props"))


def _prop_time_slots(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and D.TIME_KEY.match(k) and v is not None and not isinstance(v, (dict, list)):
                yield value, k
            else:
                yield from _prop_time_slots(v)
    elif isinstance(value, list):
        for v in value:
            yield from _prop_time_slots(v)


def _after_cut(value, rel: int, fps: float, first_id: str):
    """A Time inside the first half as the second half (starting `rel` frames later) reads it: numbers count from
    the cut; a moment already past is anchored on the first half ("clip:<id>+s"); Time strings stay."""
    if not T.counts_from_clip(value):
        return value
    t = T.parse(value).offset
    frame = T.to_frame(t, fps) - rel
    if frame >= 0:
        return _seconds_for(t - rel / fps, frame, fps)
    return str(T.TimeExpr("clip", first_id, False, round(t, 4)))


def _retarget_source(data: dict, old: str, new: str, from_s: float) -> int:
    """src:<old>@S Times with S at or after from_s (the second half's in point) name <new>."""
    count = 0
    for holder, key in _time_slots(data):
        value = holder.get(key)
        try:
            e = T.parse(value) if isinstance(value, str) else None
        except T.TimeError:
            continue
        if e is not None and e.anchor == "src" and e.ref == old and e.at >= from_s - 1e-6:
            holder[key] = str(T.TimeExpr("src", new, False, e.offset, e.at))
            count += 1
    return count


# ------------------------------------------------------------------ ripple edits (spec 5)
# A ripple edit moves Times that are written as anchors ("line:4", "clip:a.end", "mark:x"). Every Time is measured
# before the edit, moved to where the edit wants it and written as a number; an anchor is then put back wherever it
# still lands on the same frame. So anchors stay where they stay true, and nothing silently drifts.
def _inner_slots(clip: dict):
    """(holder, key) for the Times inside a clip: keyframe t, highlight.at, component at / *_at."""
    kf = clip.get("keyframes")
    if isinstance(kf, dict):
        for frames in kf.values():
            for k in frames if isinstance(frames, list) else []:
                if isinstance(k, dict) and "t" in k:
                    yield k, "t"
    yield from _clip_time_slots(clip)


def _clip_index(data: dict) -> dict[str, tuple[dict, dict]]:
    return {c["id"]: (t, c) for t, cl in _clip_lists(data) for c in cl if isinstance(c, dict)
            and isinstance(c.get("id"), str)}


def _measure(now: _Now, data: dict) -> dict:
    """Every Time of the project in seconds as it stands: clip spans, markers, the duration, caption items, and the
    anchored Times inside clips. Items and inner Times are keyed by object identity, which survives removals."""
    m: dict = {"clips": {}, "markers": {}, "duration": None, "items": {}, "inner": {}}
    for cid, (_, c) in _clip_index(data).items():
        m["clips"][cid] = now.span(cid)
        for holder, key in _inner_slots(c):
            v = holder.get(key)
            if isinstance(v, str) and not T.counts_from_clip(v):
                m["inner"][(id(holder), key)] = (holder, key, now.time(v, f"clip {cid} {key}"), cid)
    markers = data.get("markers")
    if isinstance(markers, dict):
        m["markers"] = {k: now.time(v, f"markers.{k}") for k, v in markers.items()}
    if data.get("duration") is not None:
        m["duration"] = now.time(data["duration"], "duration")
    for t in _tracks(data):
        items = t.get("items") if isinstance(t, dict) else None
        for n, it in enumerate(items if isinstance(items, list) else []):
            if isinstance(it, dict):
                where = f"track {t.get('id')}.items[{n}]"
                m["items"][id(it)] = (it, now.time(it.get("start"), f"{where}.start"),
                                      now.time(it.get("end"), f"{where}.end"))
    return m


def _write_times(root: Path, data: dict, before: dict, want: dict, why: str) -> None:
    """Put every Time where `want` says ({"clips": {id: (a, b)}, "markers", "duration", "items": {key: (item, a,
    b)}}; inner Times keep their place in their clip), as numbers, then restore each anchor that still lands."""
    written = []                                # (holder, key, original, wanted seconds)

    def put(holder, key, seconds, value=None):
        orig = holder.get(key)
        if value is None and T.is_number(orig) and abs(orig - seconds) < 1e-6:
            return
        holder[key] = _num(round(seconds, 3)) if value is None else value
        written.append((holder, key, orig, seconds))
    index = _clip_index(data)
    for cid, (a, b) in want["clips"].items():
        if cid not in index:
            continue
        c = index[cid][1]
        put(c, "start", a)
        if "end" in c:
            put(c, "end", b)
        elif T.is_number(c.get("dur")) and abs(c["dur"] - (b - a)) > 1e-6:
            c["dur"] = _num(round(b - a, 3))
    for name, t in want.get("markers", {}).items():
        put(data["markers"], name, t)
    if want.get("duration") is not None:
        put(data, "duration", want["duration"])
    for item, a, b in want.get("items", {}).values():
        put(item, "start", a)
        put(item, "end", b)
    for holder, key, t, cid in before["inner"].values():
        if cid not in want["clips"] or cid not in index:
            continue
        rel = t - before["clips"][cid][0]
        moved = want["clips"][cid][0] + rel
        put(holder, key, moved, _num(round(rel, 4)) if rel >= 0 else str(T.TimeExpr("clip", cid, False, round(rel, 4))))
    if not written:
        return
    now = _Now(root, data, why)
    restored = []
    for holder, key, orig, seconds in written:
        if not isinstance(orig, str):
            continue
        try:
            t = T.resolve(orig, now.sched)
        except T.TimeError:
            continue
        if now.frame(t) == now.frame(seconds):
            restored.append((holder, key, holder[key]))
            holder[key] = orig
    if restored and not _lands(root, data, want, why):
        for holder, key, value in restored:
            holder[key] = value


def _lands(root: Path, data: dict, want: dict, why: str) -> bool:
    try:
        now = _Now(root, data, why)
        for cid, (a, b) in want["clips"].items():
            fa, fb = (now.frame(x) for x in now.span(cid))
            if (fa, fb) != (now.frame(a), now.frame(b)):
                return False
        return all(now.frame(now.time(data["markers"][k], k)) == now.frame(t)
                   for k, t in want.get("markers", {}).items())
    except OpError:
        return False


def _ripple_tracks(data: dict, ids) -> list[dict]:
    """The tracks a ripple edit works on: those named, else every visual and audio track and every captions track
    with items."""
    if ids is None:
        return [t for t in _tracks(data) if isinstance(t, dict)
                and (t.get("kind") in ("visual", "audio") or isinstance(t.get("items"), list))]
    if isinstance(ids, str):
        ids = [ids]
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise OpError('tracks must be a list of track ids, e.g. ["v1", "a1"] (left out: every track)')
    return [_find_track(data, i)[1] for i in dict.fromkeys(ids)]


def _fresh_id(data: dict, base: str) -> str:
    used = _used_ids(data)
    stem = re.sub(r"(?:_\d+|-\d+)$", "", str(base))[:58] or "clip"
    n = 2
    while f"{stem}_{n}" in used:
        n += 1
    return f"{stem}_{n}"


def _cut_at(root: Path, data: dict, cid: str, seconds: float, notes: list) -> str:
    """Split clip cid at `seconds` (a frame inside it); the id of the part after the cut."""
    new = _fresh_id(data, cid)
    text, _ = _split_clip(root, data, {"op": "split_clip", "id": cid, "at": round(seconds, 3), "new_id": new})
    m = re.search(r" \((.*)\)$", text)
    if m:
        notes.extend(n for n in m.group(1).split("; ") if n not in notes and "reference" not in n)
    return new


def _seconds_arg(value, what: str, low: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < low:
        raise OpError(f"{what} must be a number of seconds >= {low:g} (got {value!r})")
    return float(value)


def _moved_items(data: dict, tracks: list[dict], before: dict, start, end, fps: float) -> dict:
    """Caption items of the edited tracks, moved; an item squeezed under a frame is removed."""
    want = {}
    on = {id(t) for t in tracks}
    for t in _tracks(data):
        items = t.get("items") if isinstance(t, dict) else None
        if not isinstance(items, list):
            continue
        keep = []
        for it in items:
            key = id(it)
            if key not in before["items"]:
                keep.append(it)
                continue
            _, a, b = before["items"][key]
            if id(t) in on:
                a, b = start(a), end(b)
                if T.to_frame(b, fps) <= T.to_frame(a, fps):
                    continue
            want[key] = (it, a, b)
            keep.append(it)
        t["items"] = keep
    return want


def _voice_note(now: _Now, at: float, shift: float) -> list[str]:
    end = now.sched.voice_end
    if end is None or at >= end:
        return []
    return [f"the narration is not cut: it still plays from 0 s, so what it says after {at:.2f} s now falls "
            f"{abs(shift):.2f} s {'later' if shift < 0 else 'earlier'} against the picture"]


def _ripple_delete(root, data, op) -> tuple[str, list]:
    now = _Now(root, data, "ripple_delete")
    s_t, e_t = now.time(op["start"], "start"), now.time(op["end"], "end")
    sf, ef = now.frame(s_t), now.frame(e_t)
    if ef <= sf:
        raise OpError(f"end ({e_t:.2f} s) must come at least a frame after start ({s_t:.2f} s)")
    cut_s, cut_e = sf / now.fps, ef / now.fps
    gone = cut_e - cut_s
    tracks = _ripple_tracks(data, op.get("tracks"))
    notes: list[str] = []
    split = []
    for t in tracks:
        for c in [c for c in t.get("clips") or [] if isinstance(c, dict)]:
            a, b = now.span(c.get("id"))
            af, bf = now.frame(a), now.frame(b)
            piece = c["id"]
            if af < sf < bf:
                piece = _cut_at(root, data, piece, cut_s, notes)
            if af < ef < bf:
                _cut_at(root, data, piece, cut_e, notes)
            if af < sf < bf or af < ef < bf:
                split.append(c["id"])
    now = _Now(root, data, "ripple_delete")
    before = _measure(now, data)
    removed = []
    for t in tracks:
        if isinstance(t.get("clips"), list):
            keep = []
            for c in t["clips"]:
                a, b = before["clips"].get(c.get("id"), (None, None))
                if a is not None and now.frame(a) >= sf and now.frame(b) <= ef:
                    removed.append(c["id"])
                else:
                    keep.append(c)
            t["clips"] = keep

    def mv(x: float) -> float:
        return x if x <= cut_s + 1e-9 else cut_s if x < cut_e - 1e-9 else x - gone
    on = {id(t) for t in tracks}
    index = _clip_index(data)
    want: dict = {"clips": {}, "markers": {k: mv(v) for k, v in before["markers"].items()}}
    for cid, (a, b) in before["clips"].items():
        if cid in index:
            want["clips"][cid] = (mv(a), mv(b)) if id(index[cid][0]) in on else (a, b)
    if before["duration"] is not None:
        want["duration"] = mv(before["duration"])
    want["items"] = _moved_items(data, tracks, before, mv, mv, now.fps)
    _write_times(root, data, before, want, "ripple_delete")
    notes += _voice_note(now, cut_s, -gone)
    text = (f"ripple-deleted {cut_s:.2f}-{cut_e:.2f} s ({gone:.2f} s) on {', '.join(str(t.get('id')) for t in tracks)}"
            + (f"; removed {', '.join(removed)}" if removed else "")
            + (f"; split {', '.join(split)}" if split else "")
            + f"; what followed moved {gone:.2f} s earlier")
    near = [cid for cid, (a, b) in want["clips"].items() if abs(a - cut_s) < 1e-6 or abs(b - cut_s) < 1e-6]
    return text + (f" ({'; '.join(notes)})" if notes else ""), near[:8]


def _insert_gap(root, data, op) -> tuple[str, list]:
    now = _Now(root, data, "insert_gap")
    at_f = now.frame(now.time(op["at"], "at"))
    gap_f = now.frame(_seconds_arg(op["dur"], "dur"))
    if gap_f < 1:
        raise OpError("dur is under one frame")
    at, gap = at_f / now.fps, gap_f / now.fps
    tracks = _ripple_tracks(data, op.get("tracks"))
    notes: list[str] = []
    split = []
    for t in tracks:
        for c in [c for c in t.get("clips") or [] if isinstance(c, dict)]:
            a, b = now.span(c.get("id"))
            if now.frame(a) < at_f < now.frame(b):
                _cut_at(root, data, c["id"], at, notes)
                split.append(c["id"])
    now = _Now(root, data, "insert_gap")
    before = _measure(now, data)

    def first(x: float) -> float:              # a start at the point moves; an end there stays
        return x + gap if x >= at - 1e-9 else x

    def last(x: float) -> float:
        return x + gap if x > at + 1e-9 else x
    on = {id(t) for t in tracks}
    index = _clip_index(data)
    want: dict = {"clips": {}, "markers": {k: first(v) for k, v in before["markers"].items()}}
    for cid, (a, b) in before["clips"].items():
        want["clips"][cid] = (first(a), last(b)) if id(index[cid][0]) in on else (a, b)
    if before["duration"] is not None:
        want["duration"] = first(before["duration"])
    want["items"] = _moved_items(data, tracks, before, first, last, now.fps)
    _write_times(root, data, before, want, "insert_gap")
    notes += _voice_note(now, at, gap)
    text = (f"inserted {gap:.2f} s at {at:.2f} s on {', '.join(str(t.get('id')) for t in tracks)}"
            + (f"; split {', '.join(split)}" if split else "") + f"; what followed moved {gap:.2f} s later")
    near = [cid for cid, (a, b) in want["clips"].items() if abs(a - at - gap) < 1e-6 or abs(b - at) < 1e-6]
    return text + (f" ({'; '.join(notes)})" if notes else ""), near[:8]


def _trim_clip(root, data, op) -> tuple[str, list]:
    cid = op["id"]
    track, _, clip = _find_clip(data, cid)
    if op.get("in") is None and op.get("out") is None:
        raise OpError("give in and/or out: for a video or audio clip, seconds of its source; for any other clip, "
                      "Times of its new start and end")
    ripple = op.get("ripple", False)
    if not isinstance(ripple, bool):
        raise OpError("ripple is true (later clips on the track follow) or false")
    now = _Now(root, data, "trim_clip")
    fps = now.fps
    a, b = now.span(cid)
    kind = clip.get("type")
    media = kind in ("video", "audio")
    rate = float(clip.get("rate") or 1) if kind == "video" else 1.0
    trim = float(clip.get("trim_in") or 0) if media else 0.0
    if media:
        src_in = _seconds_arg(op["in"], "in") if op.get("in") is not None else trim
        src_out = _seconds_arg(op["out"], "out") if op.get("out") is not None else trim + (b - a) * rate
        if src_out <= src_in + 1e-9:
            raise OpError(f"out ({src_out:g} s) must come after in ({src_in:g} s): both are seconds of the source")
        length = _source_seconds(root, data, clip.get("asset"))
        if length and src_in >= length:
            raise OpError(f"in {src_in:g} s is past the end of the source ({length:.2f} s)")
        if length and not clip.get("loop") and src_out > length + 0.5 / fps * rate:
            raise OpError(f"out {src_out:g} s is past the end of the source ({length:.2f} s); loop the clip to repeat "
                          "it")
        new_a, new_b = a + (src_in - trim) / rate, a + (src_out - trim) / rate
    else:
        new_a = now.time(op["in"], "in") if op.get("in") is not None else a
        new_b = now.time(op["out"], "out") if op.get("out") is not None else b
    f0, fend = now.frame(a), now.frame(b)
    head = T.to_frame(new_a - a, fps)           # frames taken off (+) or added (-) at the start
    fa, fb = f0 + head, f0 + T.to_frame(new_b - a, fps)
    if fb <= fa:
        raise OpError(f"the clip would last {(fb - fa) / fps:.3f} s: in must come before out")
    if fa < 0 and not ripple:
        raise OpError(f"that in point would start the clip {-fa / fps:.2f} s before the film starts: use ripple, or "
                      "move the clip later first")
    before = _measure(now, data)
    placed: dict = {}                           # only this clip and, with ripple, the ones after it move
    notes: list[str] = []
    if head > 0:
        # cut the head off a scratch copy (split_clip carries keyframes, motion, loops and inner Times over)
        scratch = copy.deepcopy(data)
        sc = _find_clip(scratch, cid)[2]
        if fa >= fend:                          # the new in lies past the current out: reach it first
            sc.pop("dur", None)
            sc["end"] = fb / fps
        new = _fresh_id(scratch, cid)
        text, _ = _split_clip(root, scratch, {"op": "split_clip", "id": cid, "at": round(fa / fps, 3), "new_id": new})
        piece = _find_clip(scratch, new)[2]
        keep = {k: clip[k] for k in ("id", "start", "end", "dur", "enter", "transition", "fade_in") if k in clip}
        clip.clear()
        clip.update({k: v for k, v in piece.items() if k not in ("id", "start", "end", "dur")})
        clip.update(keep)
        m = re.search(r" \((.*)\)$", text)
        notes += [x for x in (m.group(1).split("; ") if m else []) if "reference" not in x and new not in x]
    elif head < 0:
        if media:
            clip["trim_in"] = _num(max(0.0, round(trim + head / fps * rate, 3)))
        _rebase(clip, -head / fps)
    # the trimmed clip's content sits at fa..fb before it is placed; its anchored inner Times read as they did
    before["clips"][cid] = (fa / fps, fb / fps)
    before["inner"] = {k: v for k, v in before["inner"].items() if v[3] != cid}
    for holder, key in _inner_slots(clip):
        v = holder.get(key)
        if isinstance(v, str) and not T.counts_from_clip(v):
            before["inner"][(id(holder), key)] = (holder, key, now.time(v, f"clip {cid} {key}"), cid)
    span = (fb - fa) / fps
    start = a if ripple else fa / fps
    want: dict = {"clips": placed}
    placed[cid] = (start, start + span)
    shift = start + span - b
    followers = []
    if ripple and abs(shift) > 1e-9:
        for oid, (oa, ob) in before["clips"].items():
            if oid != cid and _clip_index(data)[oid][0] is track and oa >= b - 1e-6:
                placed[oid] = (oa + shift, ob + shift)
                followers.append(oid)
    _write_times(root, data, before, want, "trim_clip")
    source = ""
    if media:
        source = f" (source {trim + head / fps * rate:.2f}-{trim + (fb - f0) / fps * rate:.2f} s)"
    text = f"trimmed clip {cid} to {start:.2f}-{start + span:.2f} s{source}"
    if followers:
        text += f"; {len(followers)} later clip(s) on {track.get('id')} moved {shift:+.2f} s"
    return text + (f" ({'; '.join(notes)})" if notes else ""), [cid]


def _rebase(clip: dict, seconds: float) -> None:
    """Numbers inside a clip (they count from its start) after its start moved `seconds` earlier."""
    for holder, key in _inner_slots(clip):
        if T.counts_from_clip(holder.get(key)):
            holder[key] = _num(round(T.parse(holder[key]).offset + seconds, 4))


HANDLERS = {"add_track": _add_track, "update_track": _update_track, "remove_track": _remove_track,
            "add_clip": _add_clip, "update_clip": _update_clip, "remove_clip": _remove_clip, "move_clip": _move_clip,
            "split_clip": _split_clip, "set_keyframes": _set_keyframes, "add_asset": _add_asset,
            "update_asset": _update_asset, "remove_asset": _remove_asset, "set": _set,
            "ripple_delete": _ripple_delete, "insert_gap": _insert_gap, "trim_clip": _trim_clip}


def _apply_one(root: Path, data: dict, op) -> tuple[str, list]:
    if not isinstance(op, dict) or not isinstance(op.get("op"), str):
        raise OpError('each op is an object with an "op" name, e.g. {"op": "remove_clip", "id": "c3"}')
    name = op["op"]
    if name not in OPS:
        raise OpError(f"unknown op {name!r}; ops: {', '.join(OPS)}")
    required, optional = OPS[name]
    missing = [k for k in required if k not in op]
    extra = sorted(set(op) - {"op", *required, *optional})
    if missing or extra:
        rows = ([f"needs {', '.join(missing)}"] if missing else []) + \
            ([f"has unknown field(s) {', '.join(extra)}"] if extra else [])
        hint = (' (the changes go inside "set": {"set": {"' + extra[0] + '": ...}})'
                if extra and "set" in required else "")
        raise OpError(f"{name} {' and '.join(rows)}; its fields: {', '.join(required + optional)}{hint}")
    return HANDLERS[name](root, data, op)


# ------------------------------------------------------------------ history
def history_dir(project) -> Path:
    return project_root(project) / HISTORY


def snapshots(project) -> list[tuple[int, Path]]:
    folder = history_dir(project)
    if not folder.is_dir():
        return []
    found = [(int(m.group(1)), p) for p in folder.iterdir() if (m := SNAPSHOT.match(p.name))]
    return sorted(found)


def _log_path(project) -> Path:
    return history_dir(project) / "log.jsonl"


def _read_log(project) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for line in _log_path(project).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                out[int(row["n"])] = str(row.get("summary") or "")
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return out


def _snapshot(root: Path, content: bytes, summary: str) -> int:
    folder = history_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    snaps = snapshots(root)
    n = (snaps[-1][0] + 1) if snaps else 1
    (folder / f"{n:04d}.json").write_bytes(content)
    with _log_path(root).open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"n": n, "at": datetime.now().isoformat(timespec="seconds"), "summary": summary},
                           ensure_ascii=False) + "\n")
    for _, old in snaps[: max(0, len(snaps) + 1 - HISTORY_KEEP)]:
        old.unlink(missing_ok=True)
    return n


def _patient(fn):
    """fn(), retried while Windows refuses it because another program holds the file (a sharing violation)."""
    for n in range(SHARING_TRIES):
        try:
            return fn()
        except PermissionError:
            if n == SHARING_TRIES - 1:
                raise
            time.sleep(0.02 * (n + 1))


def _write_bytes(path: Path, content: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(content)
        _patient(lambda: os.replace(tmp, path))
    finally:
        tmp.unlink(missing_ok=True)


def _held(exc: OSError) -> str:
    return f"cannot be written ({exc.strerror or exc}): another program holds it open; close it, then send the " \
        "batch again"


# ------------------------------------------------------------------ public API
def _key(i: Issue) -> tuple:
    return i.level, i.where, i.msg


def _times(root: Path, doc: D.Document | None, ids: list) -> str:
    if doc is None or not ids:
        return ""
    voice, _ = D.load_voice(root, doc.voice)
    sched = D.schedule(doc, voice)
    rows = []
    for cid in dict.fromkeys(ids):
        try:
            a, b = sched.span(cid)
            rows.append(f"{cid} {a:.2f}-{b:.2f} s")
        except (T.TimeError, KeyError):
            continue
    return f" [{', '.join(rows)}]" if rows else ""


def apply(project, ops) -> tuple[bool, list[Issue], str]:
    """Apply a batch of ops to project.json: all or nothing. (ok, issues, summary): on success the result's issues
    and what changed; refused, the problems and "nothing changed"."""
    root = project_root(project)
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        return False, [Issue("error", "ops", "give a non-empty list of ops")], "nothing changed"
    with _lock(root):
        path = root / D.PROJECT_FILE
        try:
            content = _patient(path.read_bytes)
            raw = json.loads(content.decode("utf-8-sig"))
        except FileNotFoundError:
            return False, [Issue("error", D.PROJECT_FILE, f"not found in {root}: create the project first "
                                                          "(new_project)")], "nothing changed"
        except (OSError, ValueError) as exc:
            return False, [Issue("error", D.PROJECT_FILE, f"cannot be read ({exc}): fix the file by hand, or undo")], \
                "nothing changed"
        if not isinstance(raw, dict):
            return False, [Issue("error", D.PROJECT_FILE, "must hold a JSON object: fix the file by hand, or undo")], \
                "nothing changed"
        before = {_key(i) for i in D.check_data(root, raw)[1] if i.level == "error"}
        data = copy.deepcopy(raw)
        notes, touched = [], []
        for n, op in enumerate(ops):
            name = op.get("op") if isinstance(op, dict) else None
            try:
                note, ids = _apply_one(root, data, op)
            except OpError as exc:
                return False, [Issue("error", f"ops[{n}]" + (f" {name}" if name else ""), str(exc))], \
                    "nothing changed"
            notes.append(note)
            touched += ids
        doc, after = D.check_data(root, data)
        new = [i for i in after if i.level == "error" and _key(i) not in before]
        if new:
            return False, new, "nothing changed: the result would not validate (fix the ops and send the batch again)"
        summary = (f"{len(ops)} ops: " if len(ops) > 1 else "") + "; ".join(notes)
        if data == raw:
            return True, after, summary + " (the project is unchanged)"
        summary += _times(root, doc, [i for i in touched if i])
        try:
            _write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        except OSError as exc:
            return False, [Issue("error", D.PROJECT_FILE, _held(exc))], "nothing changed"
        try:                                    # only a batch that was written gets a history entry
            _snapshot(root, content, summary)
        except OSError as exc:
            summary += f" (no undo snapshot: .history could not be written: {exc})"
        return True, after, summary


def undo(project, steps: int = 1) -> tuple[bool, str]:
    """Put project.json back as it was before the last `steps` batches. The state it replaces is kept in
    .history/redo.json."""
    root = project_root(project)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        return False, "steps must be a whole number >= 1"
    with _lock(root):
        snaps = snapshots(root)
        if not snaps:
            return False, "nothing to undo: no edit batch has been recorded for this project"
        if steps > len(snaps):
            return False, f"only {len(snaps)} batch(es) can be undone; nothing changed"
        n, target = snaps[-steps]
        path = root / D.PROJECT_FILE
        try:
            if path.is_file():
                _write_bytes(history_dir(root) / "redo.json", _patient(path.read_bytes))
            _write_bytes(path, target.read_bytes())
        except OSError as exc:
            return False, f"project.json {_held(exc)}".replace("send the batch", "undo") + "; nothing changed"
        log = _read_log(root)
        undone = [log.get(k, "") for k, _ in snaps[-steps:]]
        for _, p in snaps[-steps:]:
            p.unlink(missing_ok=True)
    rows = [f"undid {steps} batch(es); project.json is back to its state before batch {n} (the replaced version is "
            f"in .history/redo.json)"]
    rows += [f"  undone: {u}" for u in reversed(undone) if u]
    errors = _error_count(root)
    if errors:
        rows.append(f"  the restored project has {errors} error(s): run check")
    return True, "\n".join(rows)


def _error_count(root: Path) -> int:
    try:
        _, issues = D.check_data(root, D.read_raw(root))
    except (OSError, ValueError):
        return 0
    return sum(1 for i in issues if i.level == "error")
