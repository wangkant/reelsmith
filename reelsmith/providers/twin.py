"""Twins: a redrawn variant of a cut-out (mouth closed, eyes shut) laid onto the original's canvas so the two swap
without a jump. Pillow only: a uniform scale and a shift from the alpha masks' areas and centroids, then a search;
then only the asked-for part is patched in, whole, lined up on its own surroundings."""
from __future__ import annotations

import math
import os
import uuid
from pathlib import Path

WORK_SIDE = 480                 # the coarse search runs on pictures this long
SAME_POSE_MAX = 0.08            # silhouette share that may differ when the whole twin replaces the base (patch=False)
POSE_SANITY_MAX = 0.2           # patching: beyond this share of differing silhouette it is another pose outright
THICK_SHARE = 0.0075            # erosion radius (share of the long side) that a redrawn outline band does not survive
JOIN_SHARE = 0.012              # changed pieces this close (share of the long side) to a kept part are part of it
PAIR_LIKE = 0.3                 # two eyes: the smaller's area at least this share of the larger's
PART_MAX = 0.15                 # a mouth or an eye spans at most this share of the figure's long side
ONE_WAY_MIN = 0.35              # below this a change is a wobble or a shifted limb, not a part redrawn
PARENT_MIN = 0.25               # a piece split off a change at least this one-way as a whole may be a part
JOIN_ONE_WAY = 0.2              # a piece beside the part changed at least this much the same way is part of it
MARGIN = 0.15                   # the patch reaches this share of the part's long side beyond its box
SHIFT_SHARE = 0.012             # the local line-up searches this share of the long side each way
FACE_MAX = 28.0                 # mean grey-level difference around the part, lined up, for the same drawing
TINT_MAX = 24                   # the patch's colour is evened to its surroundings by at most this per channel


def _moments(alpha) -> tuple[float, float, float]:
    """(area, cx, cy) of an alpha band, area in fully opaque pixels."""
    from PIL import Image, ImageStat
    w, h = alpha.size
    area = ImageStat.Stat(alpha).sum[0] / 255
    if area <= 0:
        raise ValueError("the picture has no visible pixels")
    cols = alpha.resize((w, 1), Image.BOX).tobytes()
    rows = alpha.resize((1, h), Image.BOX).tobytes()
    cx = sum((x + 0.5) * v for x, v in enumerate(cols)) / max(1e-9, sum(cols))
    cy = sum((y + 0.5) * v for y, v in enumerate(rows)) / max(1e-9, sum(rows))
    return area, cx, cy


def _place(twin, size: tuple[int, int], s: float, dx: float, dy: float, fine: bool = True):
    from PIL import Image
    t = twin.resize((max(1, round(twin.width * s)), max(1, round(twin.height * s))),
                    Image.LANCZOS if fine else Image.BILINEAR)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(t, (round(dx), round(dy)))         # onto a clear canvas a plain copy keeps the alpha as it is
    return out


def _flat(img):
    """Luminance over mid grey: the silhouette and the lines inside it both count."""
    from PIL import Image
    g = Image.new("RGBA", img.size, (128, 128, 128, 255))
    g.alpha_composite(img)
    return g.convert("L")


def _score(base_flat, cand) -> float:
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(base_flat, _flat(cand))).mean[0]


def _mask(img):
    return img.getchannel("A").point(lambda v: 255 if v >= 128 else 0).convert("1")


def fit(base, twin) -> dict:
    """{scale, dx, dy}: where `twin` (RGBA) sits on `base`'s canvas, in base pixels."""
    from PIL import Image
    ab, bx, by = _moments(base.getchannel("A"))
    at, tx, ty = _moments(twin.getchannel("A"))
    s0 = math.sqrt(ab / at)
    r = min(1.0, WORK_SIDE / max(base.size))
    small_size = (max(1, round(base.width * r)), max(1, round(base.height * r)))
    base_small = _flat(base.resize(small_size, Image.BILINEAR))
    twin_small = twin.resize((max(1, round(twin.width * r)), max(1, round(twin.height * r))), Image.BILINEAR)
    best = None
    for i in range(-4, 5):
        s = s0 * (1 + 0.006 * i)
        x0, y0 = (bx - s * tx) * r, (by - s * ty) * r
        for ox in range(-5, 6):
            for oy in range(-5, 6):
                sc = _score(base_small, _place(twin_small, small_size, s, x0 + ox, y0 + oy, fine=False))
                if best is None or sc < best[0]:
                    best = (sc, s, (x0 + ox) / r, (y0 + oy) / r)
    _, s, dx, dy = best
    base_flat = _flat(base)
    step = max(1, round(0.5 / r))
    fine = None
    for ds in (-0.002, 0.0, 0.002):
        for ox in range(-step, step + 1):
            for oy in range(-step, step + 1):
                sc = _score(base_flat, _place(twin, base.size, s + ds, dx + ox, dy + oy))
                if fine is None or sc < fine[0]:
                    fine = (sc, s + ds, dx + ox, dy + oy)
    return {"scale": fine[1], "dx": float(round(fine[2])), "dy": float(round(fine[3]))}



def _label(d, cell: int, sums: dict | None = None) -> list[dict]:
    """Connected regions of a binary L image on a grid of `cell` px (8-neighbours), largest first: {area px, box,
    cells, grid, n (cells)} plus, per name in `sums`, that L map's total inside the region (px at full value)."""
    from PIL import Image
    gw, gh = -(-d.width // cell), -(-d.height // cell)
    g = d.resize((gw, gh), Image.BOX).tobytes()
    maps = {k: m.resize((gw, gh), Image.BOX).tobytes() for k, m in (sums or {}).items()}
    seen = bytearray(gw * gh)
    out = []
    for start in range(gw * gh):
        if not g[start] or seen[start]:
            continue
        seen[start] = 1
        stack, cells, x0, y0, x1, y1 = [start], [], gw, gh, 0, 0
        while stack:
            k = stack.pop()
            cells.append(k)
            x, y = k % gw, k // gw
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    j = ny * gw + nx
                    if 0 <= nx < gw and 0 <= ny < gh and g[j] and not seen[j]:
                        seen[j] = 1
                        stack.append(j)
        box = (x0 * cell, y0 * cell, min(d.width, (x1 + 1) * cell), min(d.height, (y1 + 1) * cell))
        r = {"area": sum(g[k] for k in cells) * cell * cell / 255, "box": box, "cells": cells, "grid": (gw, cell),
             "n": len(cells)}
        r.update({k: sum(m[c] for c in cells) * cell * cell / 255 for k, m in maps.items()})
        out.append(r)
    return sorted(out, key=lambda r: -r["area"])


def regions(d, cell: int) -> list[tuple[float, tuple[int, int, int, int]]]:
    """Connected regions of a binary L image on a grid of `cell` px (8-neighbours): [(area px, box)], largest first."""
    return [(r["area"], r["box"]) for r in _label(d, cell)]


def _erode(d, radius: int):
    from PIL import ImageFilter
    for _ in range(radius):
        d = d.filter(ImageFilter.MinFilter(3))
    return d


def _gap(a, b) -> int:
    return max(0, a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])


def _near(piece, part, join: float) -> bool:
    """A piece of `part`: within `join` px of it and no bigger than it (not an outline running round it)."""
    return _gap(piece, part) <= join and piece[2] - piece[0] <= 2 * (part[2] - part[0]) and \
        piece[3] - piece[1] <= 2 * (part[3] - part[1])


def _pair(a: dict, b: dict) -> bool:
    """Two eyes: alike in size, side by side, a few eyes' size apart at most."""
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["box"], b["box"]
    over = min(ay1, by1) - max(ay0, by0)
    return min(a["area"], b["area"]) >= PAIR_LIKE * max(a["area"], b["area"]) and \
        over >= 0.4 * min(ay1 - ay0, by1 - by0) and (ax1 <= bx0 or bx1 <= ax0) and \
        _gap(a["box"], b["box"]) <= 3 * max(ax1 - ax0, bx1 - bx0, ay1 - ay0, by1 - by0)


def part_of(prompt: str) -> str | None:
    """"mouth" or "eyes", whichever a twin's prompt names first; None when it names neither."""
    import re
    hits = [(m.start(), k) for k, pat in (("mouth", r"mouth|lips|jaw|嘴|口"), ("eyes", r"eye|blink|眼|眨"))
            for m in [re.search(pat, prompt or "", re.I)] if m]
    return min(hits)[1] if hits else None


def _region_mask(r: dict, size):
    from PIL import Image
    m = Image.new("L", size, 0)
    gw, cell = r["grid"]
    for c in r["cells"]:
        x, y = (c % gw) * cell, (c // gw) * cell
        m.paste(255, (x, y, x + cell, y + cell))
    return m


def _over_grey(img):
    from PIL import Image
    g = Image.new("RGBA", img.size, (128, 128, 128, 255))
    g.alpha_composite(img)
    return g.convert("RGB")


def _colour_diff(base, placed):
    """Per pixel the largest channel difference over mid grey: a pink mouth on cream fur differs in colour more
    than in luminance."""
    from PIL import ImageChops
    return _max_band(ImageChops.difference(_over_grey(base), _over_grey(placed)))


def _max_band(rgb):
    from PIL import ImageChops
    r, g, b = rgb.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def _ink(img):
    """Darkness and saturation together: an open mouth or eye is inkier than the fur that replaces it."""
    from PIL import ImageChops
    c = _over_grey(img)
    return ImageChops.add(ImageChops.invert(c.convert("L")), c.convert("HSV").getchannel("S"), scale=2)


def _aligned(base, placed, tile: int = 64, reach: int = 12):
    """The placed twin with each tile slid (up to `reach` px) to where it best matches the base: a painted redraw's
    whiskers and fur a few px off do not count as changed; a mouth closed still does."""
    from PIL import Image, ImageChops, ImageStat
    h = 2                                                       # searched at half size
    small = (-(-base.width // h), -(-base.height // h))
    fb, fp = _flat(base.resize(small, Image.BILINEAR)), _flat(placed.resize(small, Image.BILINEAR))
    on = ImageChops.lighter(base.getchannel("A"), placed.getchannel("A")).resize(small, Image.BOX)
    out = placed.copy()
    t, r = tile // h, reach // h
    for y in range(0, small[1], t):
        for x in range(0, small[0], t):
            box = (x, y, min(small[0], x + t), min(small[1], y + t))
            if ImageStat.Stat(on.crop(box)).mean[0] < 8:
                continue
            ref = fb.crop(box)
            best = min((ImageStat.Stat(ImageChops.difference(ref, fp.crop((box[0] - ox, box[1] - oy, box[2] - ox,
                                                                            box[3] - oy)))).mean[0]
                        + 0.15 * (abs(ox) + abs(oy)), ox, oy) for ox in range(-r, r + 1) for oy in range(-r, r + 1))
            _, ox, oy = best
            if ox or oy:
                fx, fy = box[0] * h, box[1] * h
                fw, fh = (box[2] - box[0]) * h, (box[3] - box[1]) * h
                out.paste(placed.crop((fx - ox * h, fy - oy * h, fx - ox * h + fw, fy - oy * h + fh)), (fx, fy))
    return out


def _oneway(r: dict) -> float:
    mag, lines = r["lit"] + r["dark"], r["eb"] + r["ep"]
    return max(abs(r["dark"] - r["lit"]) / mag if mag else 0.0, abs(r["eb"] - r["ep"]) / lines if lines else 0.0)


def _candidates(base, placed, open_px: int = 9) -> tuple[list[dict], float, object]:
    """(changed regions with a part-likeness `score`, the figure's long side, an L mask of lines only one of the two
    draws). Scored up: a one-way change (an open
    mouth or eye turned to fur, or the reverse), inside the figure, compact and small; a shifted limb or a wobbling
    outline changes both ways and cancels."""
    from PIL import Image, ImageChops, ImageFilter
    placed = _aligned(base, placed)
    solid = ImageChops.darker(base.getchannel("A"), placed.getchannel("A")).point(lambda v: 255 if v >= 250 else 0)
    # only where both are drawn: a silhouette that grew a little is not a part redrawn
    hard = ImageChops.multiply(_colour_diff(base, placed).point(lambda v: 255 if v > 40 else 0), solid)
    # close first: a painted mouth's change is speckled, and opening alone would wear it away
    d = hard.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    d = d.filter(ImageFilter.MinFilter(open_px)).filter(ImageFilter.MaxFilter(open_px))
    ib, ip = _ink(base), _ink(placed)
    box = base.getchannel("A").getbbox()
    fig = max(box[2] - box[0], box[3] - box[1]) if box else max(base.size)
    if d.getbbox() is None:
        return [], fig, None
    side = max(d.size)
    both = ImageChops.darker(base.getchannel("A"), placed.getchannel("A"))
    q = 4                                                       # the interior is eroded at a quarter size
    small = both.resize((-(-both.width // q), -(-both.height // q)), Image.BOX).point(lambda v: 255 if v >= 250 else 0)
    small = small.filter(ImageFilter.MinFilter(2 * max(1, round(0.012 * side / q)) + 1))
    inside = small.resize(both.size, Image.NEAREST)
    maps = {"inside": inside,
            "lit": ImageChops.multiply(ImageChops.subtract(ip, ib), hard),
            "dark": ImageChops.multiply(ImageChops.subtract(ib, ip), hard),
            "eb": ImageChops.multiply(_flat(base).filter(ImageFilter.FIND_EDGES), d),
            "ep": ImageChops.multiply(_flat(placed).filter(ImageFilter.FIND_EDGES), d)}
    cell, k = max(4, round(side / 120)), max(2, round(THICK_SHARE * side))
    regs = []
    for r in _label(d, cell, maps):
        x0, y0, x1, y1 = r["box"]
        if r["area"] < (0.015 * fig) ** 2:
            regs.append(r)
            continue
        # split where it is thin: eyes, a mouth and a nudged nose often touch; thin wobble alone falls away
        pad = (max(0, x0 - k), max(0, y0 - k), min(d.width, x1 + k), min(d.height, y1 + k))
        piece = ImageChops.multiply(d, _region_mask(r, d.size)).crop(pad)
        grown = _erode(piece, k).filter(ImageFilter.MaxFilter(2 * k + 1))
        split = Image.new("L", d.size, 0)
        split.paste(ImageChops.multiply(grown, piece), pad[:2])
        subs = _label(split, cell, maps)
        if not subs:
            regs.append(r)
            continue
        # the thin rest stays as pieces of their own: a mouth's thin corner is joined back to it below
        thin = Image.new("L", d.size, 0)
        thin.paste(ImageChops.subtract(piece, grown), pad[:2])
        # pieces of a change that went both ways as a whole are a moved limb or sleeve cut up, not a part
        whole = _oneway(r)
        for sub in subs + _label(thin, cell, maps):
            sub["parent"] = whole
            regs.append(sub)
    for r in regs:
        x0, y0, x1, y1 = r["box"]
        cell = r["grid"][1]
        mag = r["lit"] + r["dark"]
        lines = r["eb"] + r["ep"]
        # an open mouth or eye is inkier, or at least busier with lines, than what closes it
        r["ink"] = (r["dark"] - r["lit"]) / mag if mag else 0.0
        r["busy"] = (r["eb"] - r["ep"]) / lines if lines else 0.0
        r["oneway"] = _oneway(r)
        r["inside_share"] = r["inside"] / (r["n"] * cell * cell)
        r["span"] = max(x1 - x0, y1 - y0) / fig
        fill = r["area"] / max(1, (x1 - x0) * (y1 - y0))
        size = 1.0 if r["span"] <= PART_MAX else (PART_MAX / r["span"]) ** 4
        r["score"] = (mag * r["oneway"] ** 2 * (0.3 + 0.7 * r["inside_share"]) * (0.5 + 0.5 * min(1.0, fill / 0.5))
                      * size)
        r["part"] = r["oneway"] >= ONE_WAY_MIN and r.get("parent", 1.0) >= PARENT_MIN and r["span"] <= 1.5 * PART_MAX and r["area"] >= (0.015 * fig) ** 2
    # a bit beside a much bigger change that went both ways is the end of a moved limb, not a part
    join = JOIN_SHARE * side
    moved = [m for m in regs if m["oneway"] < JOIN_ONE_WAY]
    for r in regs:
        if r["part"] and any(m["area"] > 3 * r["area"] and _gap(m["box"], r["box"]) <= 3 * join for m in moved):
            r["part"] = False
    # strong ink changes only (an outline gone or drawn), not painted fur a shade off: the part's thin rim;
    # a line only one of them has with no line of the other close by: not a nose or whisker drawn a few px off
    gone = ImageChops.multiply(ImageChops.subtract(ib, ip).point(lambda v: 255 if v > 60 else 0), solid)
    drawn = ImageChops.multiply(ImageChops.subtract(ip, ib).point(lambda v: 255 if v > 60 else 0), solid)
    reach = 2 * max(2, round(0.008 * side)) + 1
    lone = ImageChops.lighter(ImageChops.subtract(gone, drawn.filter(ImageFilter.MaxFilter(reach))),
                              ImageChops.subtract(drawn, gone.filter(ImageFilter.MaxFilter(reach))))
    return regs, fig, lone


def _choose(regs: list[dict], part: str | None) -> list[list[dict]]:
    """The asked-for part as groups of regions patched together: [[mouth]] or [[eye], [eye]]; [] when nothing changed
    looks like a part."""
    parts = sorted([r for r in regs if r["part"]], key=lambda r: -r["score"])
    if not parts:
        return []
    pairs = sorted(((a["score"] + b["score"], i, j) for i, a in enumerate(parts) for j, b in enumerate(parts)
                    if i < j and _pair(a, b)), reverse=True)
    paired = {k for _, i, j in pairs for k in (i, j)}
    if part == "eyes":
        return [[parts[pairs[0][1]]], [parts[pairs[0][2]]]] if pairs else [[parts[0]]]
    if part == "mouth":
        best = max(range(len(parts)), key=lambda i: parts[i]["score"] * (0.5 if i in paired else 1.0))
        return [[parts[best]]]
    if pairs and pairs[0][0] > parts[0]["score"]:
        return [[parts[pairs[0][1]]], [parts[pairs[0][2]]]]
    return [[parts[0]]]


def _union(boxes) -> tuple[int, int, int, int]:
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _shape(size, box, side: int):
    """A soft-edged rounded box over a part's box with a margin, fully the twin across the part."""
    from PIL import Image, ImageDraw, ImageFilter
    x0, y0, x1, y1 = box
    g = max(MARGIN * max(x1 - x0, y1 - y0), 0.01 * side)
    r = (round(x0 - g), round(y0 - g), round(x1 + g), round(y1 + g))
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(r, radius=round(min(r[2] - r[0], r[3] - r[1]) / 2), fill=255)
    return m.filter(ImageFilter.GaussianBlur(max(1.0, g / 3)))


def _alike(piece: dict, part: dict) -> bool:
    """A piece changed the same way as the part (both turned inkier, or both lost lines), inside the figure: a
    nudged nose or a redrawn ear edge does not."""
    key = "ink" if abs(part["ink"]) >= abs(part["busy"]) else "busy"
    return piece[key] * part[key] > 0 and abs(piece[key]) >= JOIN_ONE_WAY and piece["inside_share"] >= 0.6


def _find(base, placed, part: str | None, open_px: int = 9) -> dict:
    """{groups ([{box, change (L mask of its regions)}], one per patch: a mouth, or each eye), left (boxes kept from
    the base), keep (their L mask), kept, why (a refusal: nothing changed looks like a part)}."""
    from PIL import Image, ImageChops, ImageFilter
    regs, fig, lone = _candidates(base, placed, open_px)
    out = {"groups": [], "left": [], "keep": None, "kept": 0, "why": None}
    if not regs:
        return out
    groups = _choose(regs, part)
    if not groups:
        b = regs[0]["box"]
        out["left"] = sorted(r["box"] for r in regs)
        out["why"] = (f"found {len(regs)} changed region(s), the largest at x {b[0]}-{b[2]} y {b[1]}-{b[3]}, and none is a "
                      f"compact change inside the figure such as {'an eye' if part == 'eyes' else 'a mouth'} closing "
                      f"(they change both ways, sit on the outline or span over {PART_MAX:.0%} of the figure)")
        return out
    join = JOIN_SHARE * max(base.size)
    taken = [r for g in groups for r in g]
    for g in groups:
        # a closed mouth's line splits the open one's change: pieces a line away changed alike are the same part
        for r in regs:
            if any(r is t for t in taken) or not _alike(r, g[0]) or \
                    not any(_near(r["box"], k["box"], join) for k in g):
                continue
            u = _union([k["box"] for k in g] + [r["box"]])
            if max(u[2] - u[0], u[3] - u[1]) <= 1.2 * PART_MAX * fig:
                g.append(r)
                taken.append(r)
    keep = Image.new("L", base.size, 0)
    rest = [r for r in regs if not any(r is t for t in taken)]
    for r in rest:
        keep = ImageChops.lighter(keep, _region_mask(r, base.size))
    out.update(kept=len(groups), left=sorted(r["box"] for r in rest), keep=keep,
               groups=[_whole(g, lone, max(base.size)) for g in groups])
    return out


def _whole(group: list[dict], hard, side: int) -> dict:
    """{box, change}: the part's regions plus every thin changed line joined to them (the old mouth's outline and
    lip curves, which the opening wore away), within reach: all of it is patched, so no rim of the old part is left."""
    from PIL import Image, ImageChops, ImageFilter
    core = _union_mask(group, hard.size)
    x0, y0, x1, y1 = _union([r["box"] for r in group])
    k = max(2, round(THICK_SHARE * side))
    g = max(2 * k, round(0.4 * max(x1 - x0, y1 - y0)))
    pad = (max(0, x0 - g), max(0, y0 - g), min(hard.width, x1 + g), min(hard.height, y1 + g))
    lines = hard.crop(pad).filter(ImageFilter.MaxFilter(3))
    seed = core.crop(pad).filter(ImageFilter.MaxFilter(2 * k + 1))
    joined = Image.new("L", lines.size, 0)
    for r in _label(lines, 3, {"seed": seed}):
        if r["seed"] > 0:
            joined = ImageChops.lighter(joined, _region_mask(r, lines.size))
    change = core.copy()
    change.paste(ImageChops.lighter(core.crop(pad), ImageChops.multiply(joined, lines)), pad[:2])
    change = change.filter(ImageFilter.MaxFilter(5))
    return {"box": change.getbbox(), "change": change}


def _union_mask(regs, size):
    from PIL import Image, ImageChops
    m = Image.new("L", size, 0)
    for r in regs:
        m = ImageChops.lighter(m, _region_mask(r, size))
    return m


def change_mask(base, placed, open_px: int = 9, grow_px: int = 31, part: str | None = None):
    """(soft L mask, left-out boxes, kept count): the patch over the asked-for part(s), a soft-edged shape covering
    each whole with a margin; other changed regions stay the base's. (None, left, 0) when nothing differs or nothing
    changed looks like a part. `grow_px` is kept for callers; the margin follows the part's size."""
    from PIL import Image, ImageChops
    found = _find(base, placed, part, open_px)
    if not found["groups"]:
        return None, found["left"], 0
    m = Image.new("L", base.size, 0)
    for g in found["groups"]:
        m = ImageChops.lighter(m, _shape(base.size, g["box"], max(base.size)))
    return m, found["left"], found["kept"]


def _line_up(base, placed, mask, change) -> tuple[int, int, float]:
    """(dx, dy, mean grey difference): the shift of the twin that best matches the base around the part (the patch
    area and a band beyond it, outside the change, on the figure)."""
    from PIL import ImageChops, ImageStat
    side = max(base.size)
    w = max(6, round(0.02 * side))
    x0, y0, x1, y1 = mask.getbbox()
    box = (max(0, x0 - w), max(0, y0 - w), min(base.width, x1 + w), min(base.height, y1 + w))
    on = base.getchannel("A").crop(box).point(lambda v: 255 if v >= 128 else 0)
    ring = ImageChops.subtract(on, change.crop(box))
    if ImageStat.Stat(ring).sum[0] < 255 * 50:
        ring = on
    fb, fp = _flat(base).crop(box), _flat(placed)
    def cost(ox, oy):
        c = fp.crop((box[0] - ox, box[1] - oy, box[2] - ox, box[3] - oy))
        return ImageStat.Stat(ImageChops.difference(fb, c), ring).mean[0]
    r = max(2, round(SHIFT_SHARE * side))
    best = min((cost(ox, oy), ox, oy) for ox in range(-r, r + 1, 2) for oy in range(-r, r + 1, 2))
    best = min((cost(best[1] + i, best[2] + j), best[1] + i, best[2] + j) for i in (-1, 0, 1) for j in (-1, 0, 1))
    return best[1], best[2], best[0]


def _even(base, shifted, mask, change):
    """The twin's colour evened to the base's around the part (a painted redraw is often a shade off)."""
    from PIL import Image, ImageChops, ImageStat
    ring = ImageChops.subtract(mask.point(lambda v: 255 if v > 8 else 0), change)
    ring = ImageChops.multiply(ring, ImageChops.darker(base.getchannel("A"), shifted.getchannel("A"))
                               .point(lambda v: 255 if v >= 250 else 0))
    if ImageStat.Stat(ring).sum[0] < 255 * 50:
        return shifted
    mb = ImageStat.Stat(base.convert("RGB"), ring).median
    ms = ImageStat.Stat(shifted.convert("RGB"), ring).median
    bands = shifted.split()
    tuned = [b.point(lambda v, k=max(-TINT_MAX, min(TINT_MAX, mb[i] - ms[i])): max(0, min(255, v + k)))
             for i, b in enumerate(bands[:3])]
    return Image.merge("RGBA", (*tuned, bands[3]))


def _settle(base, twin, mask, change, others=None):
    """The patch's edge moved off the lines: a line that base and twin draw differently and that the soft edge would
    blend (a nose or a mouth corner a few px off, an egg's rim) is taken from the twin whole when it ends near the
    patch, or kept from the base whole when it runs on or meets another change (`others`, an L mask); outside the
    part nothing is half one and half the other."""
    from PIL import Image, ImageChops, ImageFilter
    inner = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    if inner is None:
        return mask
    w, h = inner[2] - inner[0], inner[3] - inner[1]
    g = round(0.2 * max(w, h))
    box = (max(0, inner[0] - g), max(0, inner[1] - g), min(mask.width, inner[2] + g), min(mask.height, inner[3] + g))
    m, b, t = mask.crop(box), base.crop(box), twin.crop(box)
    near = change.crop(box).filter(ImageFilter.MaxFilter(5))
    # lines only (an outline, a nose's rim): painted fur a shade off is left to the soft edge
    hard = ImageChops.subtract(ImageChops.difference(_ink(b), _ink(t)).point(lambda v: 255 if v > 60 else 0), near)
    blobs = hard.filter(ImageFilter.MaxFilter(11))              # a line and its shifted copy are one blob
    soft = m.point(lambda v: 255 if 8 < v < 250 else 0)
    on = m.point(lambda v: 255 if v > 8 else 0)
    rim = Image.new("L", m.size, 255)
    rim.paste(0, (2, 2, m.width - 2, m.height - 2))
    keep, take = Image.new("L", m.size, 0), Image.new("L", m.size, 0)
    other = others.crop(box) if others is not None else Image.new("L", m.size, 0)
    for r in _label(blobs, 3, {"soft": soft, "rim": rim, "other": other, "on": on}):
        if r["soft"] <= 0 or r["area"] < 40:
            continue
        shape = ImageChops.multiply(_region_mask(r, m.size), blobs)
        # runs on, lies mostly outside the patch, or is another change (an eye, the mouth): the base's
        if r["rim"] > 0 or r["other"] > 0 or r["on"] < 0.5 * r["n"] * 9:
            keep = ImageChops.lighter(keep, shape)
        else:
            take = ImageChops.lighter(take, shape)
    out = ImageChops.lighter(m, take.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2.5)))
    out = ImageChops.subtract(out, keep.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(2)))
    out = ImageChops.lighter(out, ImageChops.multiply(m, near))      # the part itself is always the twin's
    full = mask.copy()
    full.paste(out, box[:2])
    return full


def residual(base, placed) -> tuple[float, tuple[int, int, int, int] | None]:
    """(share of the two silhouettes' union where only one of them is, the box where the pictures differ)."""
    from PIL import ImageChops
    a, b = _mask(base), _mask(placed)
    union = ImageChops.logical_or(a, b).convert("L").histogram()[255]
    xor = ImageChops.logical_xor(a, b).convert("L").histogram()[255]
    diff = ImageChops.difference(_flat(base), _flat(placed)).point(lambda v: 255 if v > 48 else 0)
    return (xor / union if union else 1.0), diff.getbbox()


def register(base_path: Path, twin_path: Path, out_path: Path, patch: bool = True, part: str | None = None) -> dict:
    """Lay the twin onto the base's canvas (same pixel size) and save it to out_path; with patch, only the asked-for
    part, lined up locally, the base everywhere else. Not the same drawing: nothing is written. {scale, dx, dy,
    residual, changed (the patch's box in base px or None), left (boxes kept from the base), kept (parts patched),
    local (the patch's own shift on top of dx, dy), face (grey-level difference around the part after it), same,
    why (what was refused), width, height (the base's)}; `part` "mouth" | "eyes" | None as part_of gives it."""
    from PIL import Image
    with Image.open(base_path) as im:
        base = im.convert("RGBA")
    with Image.open(twin_path) as im:
        twin = im.convert("RGBA")
    f = fit(base, twin)
    placed = _place(twin, base.size, f["scale"], f["dx"], f["dy"])
    res, _ = residual(base, placed)
    r = {**f, "residual": round(res, 4), "changed": None, "left": [], "kept": 0, "local": None, "face": None,
         "same": True, "why": None, "part": part, "width": base.width, "height": base.height}
    result = placed
    if not patch:
        r["same"] = res <= SAME_POSE_MAX
        r["why"] = None if r["same"] else "pose"
    elif res > POSE_SANITY_MAX:
        r.update(same=False, why="pose")
    else:
        found = _find(base, placed, part)
        r["left"] = found["left"]
        if found["why"]:
            r.update(same=False, why=found["why"])
        elif not found["groups"]:
            r.update(same=False, why="found no change inside the figure at all (at most its outline moved)")
        else:
            result, boxes, local, faces = base, [], [], []
            for g in found["groups"]:                       # each eye is lined up on its own
                mask = _shape(base.size, g["box"], max(base.size))
                lx, ly, face = _line_up(base, placed, mask, g["change"])
                shifted = Image.new("RGBA", base.size, (0, 0, 0, 0))
                shifted.paste(placed, (lx, ly))
                # outside the patch the base's own pixels: the drawing does not boil when the two swap
                shifted = _even(base, shifted, mask, g["change"])
                mask = _settle(base, shifted, mask, g["change"], found["keep"])
                result = Image.composite(shifted, result, mask)
                boxes.append(mask.point(lambda v: 255 if v > 128 else 0).getbbox())
                local.append((lx, ly))
                faces.append(face)
            fig = base.getchannel("A").getbbox()
            u = _union(boxes)
            r.update(local=local, face=round(max(faces), 1), kept=found["kept"], changed=u,
                     down=round(((u[1] + u[3]) / 2 - fig[1]) / max(1, fig[3] - fig[1]), 2))
            if r["face"] > FACE_MAX:
                r.update(same=False, why="face", changed=None)
    out_path = Path(out_path)
    tmp = out_path.with_name(f".{out_path.stem}.{uuid.uuid4().hex[:6]}.part.png")
    try:
        if r["same"]:
            result.save(tmp, "PNG")
            os.replace(tmp, out_path)
    finally:
        tmp.unlink(missing_ok=True)
    return r


def _shifts(local) -> str:
    return " and ".join(f"{x:+d} {y:+d} px" for x, y in local)


def report(base_id: str, r: dict) -> str:
    """One to four sentences for the tool's text."""
    fit = (f"scale {r['scale']:.3f}, shift {r['dx']:+.0f} {r['dy']:+.0f} px, {r['residual']:.1%} of the silhouettes "
           "differ")
    again = (f"Draw it again with twin_of={base_id!r}, or use it as a pose of its own and draw its own twins from it.")
    why = r.get("why")
    if not r["same"]:
        if why == "face":
            return (f" NOT A TWIN of {base_id!r}: at the best fit ({fit}) and lined up at the changed part "
                    f"(local shift {_shifts(r['local'])}) its surroundings still differ by "
                    f"{r['face']:.1f} grey levels (limit {FACE_MAX:.0f}), so the face is drawn differently and a "
                    f"patch would show a seam; it is left as drawn, on its own canvas. {again}")
        if why and why != "pose":
            return (f" NOT A TWIN of {base_id!r}: at the best fit ({fit}) it {why}; nothing was patched and it "
                    f"is left as drawn, on its own canvas. {again}")
        limit = POSE_SANITY_MAX if r["residual"] > POSE_SANITY_MAX else SAME_POSE_MAX
        return (f" NOT A TWIN of {base_id!r}: at the best fit ({fit}) that is more than {limit:.0%}, so it is "
                f"another pose and swapping the two would jump; it is left as drawn, on its own canvas. {again}")
    box = r.get("changed")
    head = f" Registered onto {base_id!r}'s canvas ({r['width']}x{r['height']}): {fit}"
    what = {"mouth": "the mouth", "eyes": "the eyes"}.get(r.get("part"), f"{r.get('kept', 1)} changed part(s)")
    head += (f". Patched in {what} as a whole from the twin, x {box[0]}-{box[2]} y {box[1]}-{box[3]} (its middle "
             f"{r['down']:.0%} of the way down the figure), lined up "
             f"locally by {_shifts(r['local'])} (around it the two then differ by {r['face']:.1f} "
             "grey levels); outside it the base's own pixels are kept.")
    boxes = r.get("left") or []
    left = [f"x {b[0]}-{b[2]} y {b[1]}-{b[3]}" for b in boxes[:4]] + (["..."] if len(boxes) > 4 else [])
    if left:
        head += f" {len(boxes)} other changed region(s) left as the base: {'; '.join(left)}."
    if r.get("part") and r["down"] > 0.6:
        head += " That is low for a face: look at the twin before using it."
    return head
