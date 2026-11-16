"""Twins: a redrawn variant of a cut-out (mouth closed, eyes shut) laid onto the original's canvas so the two swap
without a jump. Pillow only: a uniform scale and a shift from the alpha masks' areas and centroids, then a search."""
from __future__ import annotations

import math
import os
import uuid
from pathlib import Path

WORK_SIDE = 480                 # the coarse search runs on pictures this long
SAME_POSE_MAX = 0.08            # share of the silhouettes that may differ after registration for a "same drawing"
NEAR_SHARE = 0.06               # changed regions this close (share of the long side) belong to the asked-for change


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


def regions(d, cell: int) -> list[tuple[float, tuple[int, int, int, int]]]:
    """Connected regions of a binary L image on a grid of `cell` px (8-neighbours): [(area px, box)], largest first."""
    from PIL import Image
    gw, gh = -(-d.width // cell), -(-d.height // cell)
    g = d.resize((gw, gh), Image.BOX).tobytes()
    seen = bytearray(gw * gh)
    out = []
    for start in range(gw * gh):
        if not g[start] or seen[start]:
            continue
        seen[start] = 1
        stack, area, x0, y0, x1, y1 = [start], 0.0, gw, gh, 0, 0
        while stack:
            k = stack.pop()
            x, y = k % gw, k // gw
            area += g[k] * cell * cell / 255
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    j = ny * gw + nx
                    if 0 <= nx < gw and 0 <= ny < gh and g[j] and not seen[j]:
                        seen[j] = 1
                        stack.append(j)
        out.append((area, (x0 * cell, y0 * cell, min(d.width, (x1 + 1) * cell), min(d.height, (y1 + 1) * cell))))
    return sorted(out, key=lambda r: -r[0])


def _gap(a, b) -> int:
    return max(0, a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])


def change_mask(base, placed, open_px: int = 9, grow_px: int = 31):
    """(soft L mask, left-out boxes): where the twin really differs, only the largest changed region and those near
    it (the change asked for); regions further off (a tail redrawn by the way) stay the base's. (None, []) when
    nothing differs."""
    from PIL import Image, ImageChops, ImageFilter
    d = ImageChops.difference(_flat(base), _flat(placed)).point(lambda v: 255 if v > 48 else 0)
    d = d.filter(ImageFilter.MinFilter(open_px)).filter(ImageFilter.MaxFilter(open_px))
    if d.getbbox() is None:
        return None, []
    regs = regions(d, max(4, round(max(d.size) / 120)))
    keep, rest = [regs[0][1]], [r[1] for r in regs[1:]]
    # eyes: two regions about one eye's size apart
    near = max(round(NEAR_SHARE * max(d.size)), max(keep[0][2] - keep[0][0], keep[0][3] - keep[0][1]))
    grew = True
    while grew:
        grew = False
        for box in list(rest):
            if any(_gap(box, k) <= near for k in keep):
                keep.append(box)
                rest.remove(box)
                grew = True
    if rest:
        sel = Image.new("L", d.size, 0)
        for box in keep:
            sel.paste(255, box)
        d = ImageChops.multiply(d, sel)
    k = grow_px | 1
    soft = d.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.GaussianBlur(1.5))   # a soft edge across a moved line ghosts
    return soft, sorted(rest)


def residual(base, placed) -> tuple[float, tuple[int, int, int, int] | None]:
    """(share of the two silhouettes' union where only one of them is, the box where the pictures differ)."""
    from PIL import ImageChops
    a, b = _mask(base), _mask(placed)
    union = ImageChops.logical_or(a, b).convert("L").histogram()[255]
    xor = ImageChops.logical_xor(a, b).convert("L").histogram()[255]
    diff = ImageChops.difference(_flat(base), _flat(placed)).point(lambda v: 255 if v > 48 else 0)
    return (xor / union if union else 1.0), diff.getbbox()


def register(base_path: Path, twin_path: Path, out_path: Path, patch: bool = True) -> dict:
    """Lay the twin onto the base's canvas (same pixel size) and save it to out_path; with patch, only the asked-for
    change, the base everywhere else. Not the same pose: nothing is written. {scale, dx, dy, residual, changed (box
    in base px or None), left (boxes kept from the base), same (bool), width, height (the base's)}."""
    from PIL import Image
    with Image.open(base_path) as im:
        base = im.convert("RGBA")
    with Image.open(twin_path) as im:
        twin = im.convert("RGBA")
    f = fit(base, twin)
    placed = _place(twin, base.size, f["scale"], f["dx"], f["dy"])
    res, _ = residual(base, placed)
    same = res <= SAME_POSE_MAX
    mask, left = change_mask(base, placed) if patch and same else (None, [])
    box = mask.point(lambda v: 255 if v > 128 else 0).getbbox() if mask else None
    if mask is not None:
        # outside the change the base's own pixels: the drawing does not boil when the two swap
        placed = Image.composite(placed, base, mask)
    out_path = Path(out_path)
    part = out_path.with_name(f".{out_path.stem}.{uuid.uuid4().hex[:6]}.part.png")
    try:
        if same:
            placed.save(part, "PNG")
            os.replace(part, out_path)
    finally:
        part.unlink(missing_ok=True)
    return {**f, "residual": round(res, 4), "changed": box, "left": left, "same": same,
            "width": base.width, "height": base.height}


def report(base_id: str, r: dict) -> str:
    """One to three sentences for the tool's text."""
    fit = (f"scale {r['scale']:.3f}, shift {r['dx']:+.0f} {r['dy']:+.0f} px, {r['residual']:.1%} of the silhouettes "
           "differ")
    if not r["same"]:
        return (f" NOT A TWIN of {base_id!r}: at the best fit ({fit}) that is more than {SAME_POSE_MAX:.0%}, so it is "
                "another pose and swapping the two would jump; it is left as drawn, on its own canvas. Draw it "
                f"again with twin_of={base_id!r}, or use it as a pose of its own and draw its own twins from it.")
    box = r.get("changed")
    where = (f"; the change sits in x {box[0]}-{box[2]}, y {box[1]}-{box[3]} (outside it the base's own pixels are "
             "kept)" if box else "; no visible difference")
    head = f" Registered onto {base_id!r}'s canvas ({r['width']}x{r['height']}): {fit}{where}."
    left = [f"x {b[0]}-{b[2]} y {b[1]}-{b[3]}" for b in r.get("left") or []]
    if left:
        head += f" Also redrawn at {'; '.join(left)}: kept from the base (not the asked-for change)."
    return head
