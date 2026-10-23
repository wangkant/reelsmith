"""Draws assets/evidence.png: a made-up 1290x960 notice whose proving line sits at the box the test timelines use.

    python renderer/test/assets/make_evidence.py

The full line is [56, 446, 1060, 66]; its part 票价下调五毛钱 is [358, 446, 330, 66] (layout.resolved.json).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fixtures", HERE.parent / "presets-preview" / "fixtures.py")
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)

W, H = 1290, 960
LINE = "示例公交公告：票价下调五毛钱，月卡价格不变。"   # 22 glyphs x 48 px from x 56
BOLD = range(7, 14)


def main():
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    fx.run(d, 56, 110, "示例日报  EXAMPLE DAILY", 54, 800, fx.BLUE)
    d.rectangle([56, 150, W - 56, 155], fill=fx.RULE)
    fx.run(d, 56, 250, "公交票价调整说明", 66, 700, fx.INK)
    fx.run(d, 56, 330, "本报讯  示例城市交通局", 40, 400, fx.GREY)
    fx.run(d, 56, 410, "自下月一日起，全市公交统一执行新票价。", 44, 400, fx.INK)
    x = 56
    for i, ch in enumerate(LINE):
        f = fx.font_for(ch, 48, 700 if i in BOLD else 400)
        d.text((x, 497), ch, font=f, fill=fx.INK, anchor="ls")
        x += 48
    fx.run(d, 56, 590, "乘客可在站台和官方网站查询详细线路。", 44, 400, fx.INK)
    fx._photo(d, 56, 650, W - 112, 260)
    out = HERE / "evidence.png"
    img.save(out, optimize=True)
    print(f"{out.name}: {img.size}")


if __name__ == "__main__":
    main()
