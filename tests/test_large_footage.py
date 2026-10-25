"""Real-world footage: local files of any size (hard-linked into the project, copied across volumes) and HDR sources
(probe and import say what they are)."""
import importlib
import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from reelsmith import tools as T

I = importlib.import_module("reelsmith.providers.importer")
F = importlib.import_module("reelsmith.providers.footage")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="no ffmpeg")


def write_png(path: Path, w=16, h=9):
    raw = b"".join(b"\x00" + bytes((90, 120, 150)) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def tagged_clip(path: Path, primaries: str, transfer: str, space: str) -> Path:
    """A 1 s clip whose stream carries these colour tags (as a phone's HLG recording does)."""
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=s=64x36:r=30:d=1", "-vf",
                    f"setparams=color_primaries={primaries}:color_trc={transfer}:colorspace={space}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "film"
    assert T.new_project(str(root), locale="en").ok
    return root


# ------------------------------------------------------------------ #21 local files of any size
def test_import_links_a_local_file_instead_of_copying_it(project, tmp_path):
    src = write_png(tmp_path / "raw" / "frame.png")
    r = T.import_asset(str(project), "still", str(src))
    assert r.ok and "hard-linked to the original, not copied" in r, r
    assert os.path.samefile(src, project / "assets" / "still.png")      # one file on disk, two names
    assert T.import_asset(str(project), "still2", str(src), "video").ok is False
    assert src.is_file() and not [p for p in (project / "assets").iterdir() if p.name.startswith(".")]


def test_import_copies_across_volumes_and_checks_the_room(project, tmp_path, monkeypatch):
    src = write_png(tmp_path / "raw" / "frame.png")

    def other_volume(a, b):
        raise OSError(18, "Invalid cross-device link")
    monkeypatch.setattr(I.os, "link", other_volume)
    r = T.import_asset(str(project), "still", str(src))
    assert r.ok and "hard-linked" not in r and not os.path.samefile(src, project / "assets" / "still.png")
    monkeypatch.setattr(I.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10 << 30, 10 << 30, 100 << 20))
    r = T.import_asset(str(project), "again", str(src))
    assert not r.ok and "the project's disk has 100.0 MB free" in r
    assert not [p for p in (project / "assets").iterdir() if p.name.startswith(".")]


# ------------------------------------------------------------------ #31 HDR sources
@needs_ffmpeg
def test_probe_and_import_flag_an_hdr_source(project, tmp_path):
    hlg = tagged_clip(tmp_path / "phone.mp4", "bt2020", "arib-std-b67", "bt2020nc")
    sdr = tagged_clip(tmp_path / "screen.mp4", "bt709", "bt709", "bt709")
    r = T.import_asset(str(project), "phone", str(hlg))
    assert r.ok and "HDR (HLG)" in r and "not tone-map" in r, r
    assert T.import_asset(str(project), "screen", str(sdr)).ok
    r = T.probe(str(project), "phone")
    facts = json.loads(r.split("JSON: ", 1)[1])
    assert facts["video"]["hdr"] == "HLG" and facts["video"]["color"]["transfer"] == "arib-std-b67"
    assert "colour bt2020/arib-std-b67/bt2020nc" in r and "HDR (HLG)" in r
    r = T.probe(str(project), "screen")
    assert json.loads(r.split("JSON: ", 1)[1])["video"]["hdr"] is None and "HDR" not in r
    assert F.hdr_of({"color_transfer": "smpte2084"}) == "PQ"
    assert F.hdr_of({"color_transfer": "arib-std-b67",
                     "side_data_list": [{"side_data_type": "DOVI configuration record"}]}) == "Dolby Vision, HLG"
    assert F.hdr_of({"color_transfer": "bt709"}) is None
