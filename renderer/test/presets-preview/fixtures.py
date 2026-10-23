"""Draws the preview's evidence captures (made-up phone pages, 3x like a capture) into public/assets.

    python renderer/test/presets-preview/fixtures.py

Uses the renderer's bundled Noto Sans SC slices; prints each file's size and its proving sentence's box for Root.tsx.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
NOTO = HERE.parents[1] / "node_modules" / "@fontsource-variable" / "noto-sans-sc"
OUT = HERE / "public" / "assets"
K = 3                     # capture scale
WIDTH = 430 * K           # a phone page
MARGIN = 22 * K
INK, GREY, RULE, BLUE = "#1A1A1A", "#8A8A8A", "#E3E3E3", "#1F4E8C"


def _slices() -> list[tuple[list[tuple[int, int]], Path]]:
    out = []
    for key, ranges in json.loads((NOTO / "unicode.json").read_text(encoding="utf-8")).items():
        spans = []
        for part in ranges.split(","):
            lo, _, hi = part.strip()[2:].partition("-")
            spans.append((int(lo, 16), int(hi or lo, 16)))
        out.append((spans, NOTO / "files" / f"noto-sans-sc-{key.strip('[]')}-wght-normal.woff2"))
    return out


SLICES = _slices()


@lru_cache(maxsize=None)
def font_for(ch: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    cp = ord(ch)
    path = next((p for spans, p in SLICES if any(lo <= cp <= hi for lo, hi in spans)), SLICES[-1][1])
    return _font(path, size, weight)


@lru_cache(maxsize=None)
def _font(path: Path, size: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), size)
    f.set_variation_by_axes([weight])
    return f


def run(draw: ImageDraw.ImageDraw, x: float, baseline: float, text: str, size: int, weight: int, fill: str) -> float:
    """Draws text glyph by glyph (each from its own slice) on a baseline; returns the x it ends at."""
    for ch in text:
        f = font_for(ch, size, weight)
        if not ch.isspace():
            draw.text((x, baseline), ch, font=f, fill=fill, anchor="ls")
        x += f.getlength(ch)
    return x


def page(path: Path, blocks: list[tuple]) -> list[int] | None:
    """blocks: ("rule",) | ("gap", px) | ("photo", h) | (size, weight, fill, line_height, [(text, mark), ...]) per line.
    Returns [x, y, w, h] of the run marked True (the proving sentence)."""
    height = MARGIN
    for b in blocks:
        height += b[1] if b[0] in ("gap", "photo") else 2 * K if b[0] == "rule" else round(b[0] * b[3])
    img = Image.new("RGB", (WIDTH, height + MARGIN), "white")
    draw = ImageDraw.Draw(img)
    y, box = MARGIN, None
    for b in blocks:
        if b[0] == "rule":
            draw.rectangle([MARGIN, y, WIDTH - MARGIN, y + 2 * K - 1], fill=RULE)
            y += 2 * K
        elif b[0] == "gap":
            y += b[1]
        elif b[0] == "photo":
            _photo(draw, MARGIN, y, WIDTH - 2 * MARGIN, b[1])
            y += b[1]
        else:
            size, weight, fill, lh, runs = b
            line_h = round(size * lh)
            baseline = y + (line_h + size * 0.76) / 2
            x = MARGIN
            for text, mark in runs:
                end = run(draw, x, baseline, text, size, weight + (300 if mark else 0), fill)
                if mark:
                    box = [round(x), round(baseline - size * 0.98), round(end - x), round(size * 1.3)]
                x = end
            y += line_h
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print(f"{path.name}: size {list(img.size)} box {box}")
    return box


def _photo(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int):
    """A plain flat illustration: sky, sun, two hills."""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8 * K, fill="#CFE3F1")
    draw.ellipse([x + w * 0.70, y + h * 0.16, x + w * 0.70 + h * 0.30, y + h * 0.46], fill="#F2C14E")
    draw.polygon([(x, y + h), (x, y + h * 0.62), (x + w * 0.38, y + h * 0.36), (x + w * 0.80, y + h)], fill="#7FB383")
    draw.polygon([(x + w * 0.30, y + h), (x + w * 0.68, y + h * 0.50), (x + w, y + h * 0.70), (x + w, y + h)], fill="#5C9A6A")


def body(*runs, size=17 * K, weight=400, fill=INK, lh=1.85):
    return (size, weight, fill, lh, [(r, False) if isinstance(r, str) else r for r in runs])


def main():
    page(OUT / "ev_article.png", [
        (22 * K, 800, BLUE, 1.5, [("示例日报", False), ("  EXAMPLE DAILY", False)]),
        ("rule",), ("gap", 8 * K),
        (24 * K, 700, INK, 1.5, [("抽中一台笔记本，到手还剩多少", False)]),
        body("本报记者  示例", size=14 * K, fill=GREY, lh=1.8),
        body("市民小王参加商场的百日打卡活动，全勤"),
        body("100天后进入抽奖池，抽中一台标价11714"),
        body("元的笔记本电脑。按照规定，"),
        body(("中奖需按20%缴纳个税，到手约9371元。", True)),
        body("工作人员表示，奖品可在活动结束后七个"),
        body("工作日内到店领取。"),
        ("gap", 10 * K), ("photo", 150 * K),
    ])
    page(OUT / "ev_notice.png", [
        (20 * K, 700, INK, 1.6, [("百日打卡活动规则", False)]),
        body("示例商场  会员中心", size=14 * K, fill=GREY, lh=1.8),
        ("rule",), ("gap", 6 * K),
        body("一、活动时间为报名之日起连续100天，"),
        body("每天到店打卡一次，中断即视为放弃。"),
        body("二、全勤会员自动进入抽奖池，奖品包括"),
        body("笔记本电脑、咖啡月卡等。"),
        body("三、", ("奖品税费由中奖者承担。", True)),
        body("四、本规则的解释权归示例商场所有。"),
    ])


if __name__ == "__main__":
    main()
