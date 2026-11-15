"""The performance example (examples/performance): it checks clean, every scene hears its own line and every word
it cues on is in that line; the AssetGrid preset's meta; and the stage kit's unit tests (renderer/test/stage.test.mjs)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from reelsmith import library as L
from reelsmith import resolve as R
from reelsmith import tools

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "performance"
COMPONENTS = EXAMPLE / "library" / "components"
RENDERER = ROOT / "renderer"
SCENES = {"s1": "SaltRiver", "s2": "SaltSun", "s3": "SaltGlass"}


@pytest.fixture
def salt(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "performance", ignore=shutil.ignore_patterns("build", "out", ".history"))
    return tmp_path / "performance" / "projects" / "salt"


def clip(resolved, cid):
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def cued_words(name):
    return re.findall(r'\bT\("([^"]+)"', (COMPONENTS / f"{name}.tsx").read_text(encoding="utf-8"))


def test_example_checks_clean(salt):
    out = tools.check(str(salt))
    assert out.ok and out.startswith("OK: no issues"), out


def test_example_library_lists_scenes_not_helpers(salt):
    lib = {n: c for n, c in L.components(salt).items() if c.source == "library"}
    assert set(lib) == {"SaltGround", *SCENES.values()}
    assert all(not c.problem for c in lib.values())


def test_each_scene_hears_its_own_line(salt):
    voice = json.loads((salt / "voice" / "voice.json").read_text(encoding="utf-8"))
    resolved = R.resolve(salt)
    fps = resolved["fps"]
    for n, (cid, name) in enumerate(SCENES.items(), 1):
        lines = clip(resolved, cid)["content"]["lines"]
        assert [ln["i"] for ln in lines] == [n], cid
        line = voice["lines"][n - 1]
        assert lines[0]["text"] == line["text"]
        assert lines[0]["from"] == 0 and lines[0]["to"] == round((line["t1"] - line["t0"]) * fps)
    assert [ln["i"] for ln in clip(resolved, "g")["content"]["lines"]] == [1, 2, 3]


def test_every_cued_word_is_said_in_its_scene(salt):
    resolved = R.resolve(salt)
    for cid, name in SCENES.items():
        text = " ".join(ln["text"] for ln in clip(resolved, cid)["content"]["lines"])
        words = cued_words(name)
        assert words, name
        missing = [w for w in words if w not in text]
        assert not missing, f"{name} cues on words its line does not say: {missing}"


def test_cut_out_picture_arrives_with_its_size(salt):
    ref = clip(R.resolve(salt), "s3")["content"]["props"]["photo_asset"]
    assert ref["kind"] == "image" and list(ref["size"]) == [232, 338]


def test_example_ships_no_large_binaries():
    shipped = [p for p in EXAMPLE.rglob("*")
               if p.is_file() and not {"build", "out"} & set(p.relative_to(EXAMPLE).parts)]
    big = [p for p in shipped if p.suffix in {".jpg", ".png", ".m4a", ".wav"} and p.stat().st_size > 300_000]
    assert not big


def test_asset_grid_meta():
    meta = json.loads((ROOT / "renderer" / "src" / "presets" / "AssetGrid.meta.json").read_text(encoding="utf-8"))
    props = meta["props"]
    assert meta["name"] == "AssetGrid" and props["required"] == ["asset"] and props["additionalProperties"] is False
    for key in ("cols", "rows"):
        assert props["properties"][key] == {**props["properties"][key], "type": "integer", "minimum": 2,
                                            "maximum": 40, "default": 10}
    assert meta["example"]["asset"]


def test_every_stage_export_is_documented():
    index = (RENDERER / "src" / "kit" / "stage" / "index.ts").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "kit.md").read_text(encoding="utf-8")
    blocks = re.findall(r"export (?:type )?\{([^}]*)\}", index)
    names = {n.strip() for block in blocks for n in block.split(",")} - {""}

    def said(n):
        return re.search(r"\b" + re.escape(n) + r"\b", doc)

    # a props type counts as documented with its component (kit.md says every component exports <Name>Props)
    missing = [n for n in sorted(names) if not (said(n) or (n.endswith("Props") and said(n[:-5])))]
    assert names and not missing


@pytest.mark.skipif(not (shutil.which("node") and (RENDERER / "node_modules" / "esbuild").is_dir()),
                    reason="node or the renderer's esbuild missing")
def test_stage_kit_unit_tests():
    out = subprocess.run(["node", "test/stage.test.mjs"], cwd=RENDERER, capture_output=True, text=True,
                         encoding="utf-8", timeout=120)
    assert out.returncode == 0 and "all passed" in out.stdout, out.stdout + out.stderr
