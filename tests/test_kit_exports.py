"""docs/kit.md's Exports block is generated from the kit's sources (renderer/scripts/kit-exports.mjs) and kept current."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "renderer"

needs_ts = pytest.mark.skipif(not (shutil.which("node") and (RENDERER / "node_modules" / "typescript").is_dir()),
                              reason="node or the renderer's typescript missing")


def run(*args):
    return subprocess.run(["node", "scripts/kit-exports.mjs", *args], cwd=RENDERER, capture_output=True, text=True,
                          encoding="utf-8", timeout=180)


@needs_ts
def test_exports_block_is_current():
    out = run("--check")
    assert out.returncode == 0, out.stdout + out.stderr


@needs_ts
def test_exports_block_names_every_export_with_its_signature():
    block = run().stdout
    assert 3000 < len(block) < 20000
    for line in ("lookAt(pt: Pt, depth, w, h) → { x: number; y: number }", "<Vapor x, y, ", "<Surface quad: Pt[], ",
                 "useClip() → ClipCtx", "...PhotoProps"):
        assert line in block, line
    doc = (ROOT / "docs" / "kit.md").read_text(encoding="utf-8")
    assert doc.index("exports:begin") < doc.index("## A component")
