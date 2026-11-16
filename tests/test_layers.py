"""The layered-photographs example (examples/layers): it checks clean, its one world hears every line and cues only
on words said, its pictures arrive with their sizes, stay small and the cut-outs carry alpha, and its traced points
lie on the pictures."""
import json
import re
import shutil
from pathlib import Path

import pytest

from reelsmith import library as L
from reelsmith import resolve as R
from reelsmith import tools

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "layers"
COMPONENTS = EXAMPLE / "library" / "components"
ASSETS = EXAMPLE / "projects" / "balloon" / "assets"
SIZES = {"valley": [1024, 1536], "inside": [1024, 1536], "balloon": [560, 807], "flame": [300, 1043]}


@pytest.fixture
def balloon(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "layers", ignore=shutil.ignore_patterns("build", "out", ".history"))
    return tmp_path / "layers" / "projects" / "balloon"


def world(resolved):
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == "w1")


def test_example_checks_clean(balloon):
    out = tools.check(str(balloon))
    assert out.ok and out.startswith("OK: no issues"), out


def test_library_lists_the_world_not_its_scene_files(balloon):
    lib = {n: c for n, c in L.components(balloon).items() if c.source == "library"}
    assert set(lib) == {"Balloon"} and not lib["Balloon"].problem


def test_world_hears_every_line_and_cues_only_on_words_said(balloon):
    voice = json.loads((balloon / "voice" / "voice.json").read_text(encoding="utf-8"))
    lines = world(R.resolve(balloon))["content"]["lines"]
    assert [ln["i"] for ln in lines] == [1, 2, 3] and lines[0]["from"] == 0
    text = " ".join(ln["text"] for ln in voice["lines"])
    words = [w for p in COMPONENTS.rglob("*.tsx") for w in re.findall(r'\bT\("([^"]+)"', p.read_text(encoding="utf-8"))]
    assert words and not [w for w in words if w not in text]


def test_pictures_arrive_with_their_sizes(balloon):
    props = world(R.resolve(balloon))["content"]["props"]
    for key, name in (("valley_asset", "valley"), ("balloon_asset", "balloon"), ("inside_asset", "inside"),
                      ("flame_asset", "flame")):
        ref = props[key]
        assert ref["kind"] == "image" and list(ref["size"]) == SIZES[name], key


def _webp_has_alpha(path):
    head = path.read_bytes()[:32]
    assert head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return head[12:16] == b"VP8X" and bool(head[20] & 0x10)


def test_pictures_are_small_and_cut_outs_carry_alpha():
    files = sorted(ASSETS.iterdir())
    assert [p.name for p in files] == ["balloon.webp", "flame.webp", "inside.webp", "valley.webp"]
    assert all(p.stat().st_size < 400_000 for p in files)
    assert _webp_has_alpha(ASSETS / "balloon.webp") and _webp_has_alpha(ASSETS / "flame.webp")
    assert not _webp_has_alpha(ASSETS / "valley.webp")


def test_traced_points_lie_on_their_pictures():
    src = (COMPONENTS / "balloon" / "trace.ts").read_text(encoding="utf-8")
    trees = re.search(r"TREES: Pt\[\] = \[(.*?)\];", src, re.S).group(1)
    pts = [(int(x), int(y)) for x, y in re.findall(r"\[(\d+), (\d+)\]", trees)]
    assert len(pts) >= 10 and all(0 <= x <= 1024 and 0 <= y <= 1536 for x, y in pts)
    for name in ("ENVELOPE", "CROWN", "MOUTH"):
        x, y = map(int, re.search(name + r": Pt = \[(\d+), (\d+)\]", src).groups())
        assert 0 <= x <= 560 and 0 <= y <= 807, name


def test_example_stays_light():
    shipped = [p for p in EXAMPLE.rglob("*")
               if p.is_file() and not {"build", "out", ".cache", ".history"} & set(p.relative_to(EXAMPLE).parts)]
    assert sum(p.stat().st_size for p in shipped) < 1_200_000
