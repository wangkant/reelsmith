"""Delivery at real-world scale: long films (a batched, sparse layout pass and scaled timeouts), sidecar captions,
chapters, draft renders and the HDR warning. render.mjs is faked here (renderer/test/selftest.mjs covers the real
one; test_the_real_renderer_measures_a_fifteen_minute_film runs it with REELSMITH_SLOW_TESTS=1)."""
import importlib
import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from reelsmith import cli, media, sidecar
from reelsmith import render as R
from reelsmith import tools as T
from reelsmith.checks import LayoutCheck
from reelsmith.profiles import LANDSCAPE

F = importlib.import_module("reelsmith.providers.footage")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="no ffmpeg")
SMALL = {"base": "landscape", "width": 192, "height": 108}       # a landscape canvas small enough to encode fast


def write_png(path: Path, w=16, h=9):
    raw = b"".join(b"\x00" + bytes((90, 120, 150)) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True,
                   capture_output=True)


def make_project(tmp_path, monkeypatch, **fields) -> Path:
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "film"
    assert T.new_project(str(root), locale="en").ok
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    data.update({"profile": SMALL, **fields})
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    return root


class Node:
    """render.mjs stand-in: refuses more than 600 frames a call (as render.mjs does), writes stills and inspect.json,
    and films of the canvas's size (scaled and cut for a draft)."""

    def __init__(self, items_for=None, film_ok=True):
        self.calls, self.items_for, self.film_ok = [], items_for or (lambda f: []), film_ok
        self.stills_waiting = []                 # stills already in the folder when each inspect call starts

    def __call__(self, mode, resolved, project, out, frames=None, timeout=None, extra=None):
        data = json.loads(Path(resolved).read_text(encoding="utf-8"))
        frames, extra, out = list(frames or []), list(extra or []), Path(out)
        self.calls.append({"mode": mode, "frames": frames, "timeout": timeout, "extra": extra,
                           "resolved": Path(resolved).name})
        if mode == "inspect":
            if len(frames) > 600:
                return {"ok": False, "stage": "args", "error": f"{len(frames)} frames asked; at most 600 per call"}
            out.mkdir(parents=True, exist_ok=True)
            self.stills_waiting.append(len(list(out.glob("still_*.png"))))
            rows = []
            for f in frames:
                write_png(out / f"still_{f:05d}.png")
                rows.append({"frame": f, "png": f"still_{f:05d}.png", "items": self.items_for(f)})
            (out / "inspect.json").write_text(json.dumps({"frames": rows}), encoding="utf-8")
            return {"ok": True, "bundleMs": 10}
        if not self.film_ok:
            return {"ok": False, "stage": "render", "error": "stopped here on purpose"}
        opts = dict(x[2:].split("=", 1) if "=" in x else (x[2:], "") for x in extra)
        scale = float(opts.get("scale") or 1)
        a, b = map(int, opts["range"].split("-")) if "range" in opts else (0, data["durationInFrames"] - 1)
        w, h = (2 * round(data[k] * scale / 2) for k in ("width", "height"))
        secs = (b - a + 1) / data["fps"]
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r={data['fps']}:d={secs}", "-f", "lavfi", "-i",
               f"sine=frequency=330:duration={secs}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-shortest", out)
        return {"ok": True, "bundleMs": 10}


def text_item(clip, rect, words="hello"):
    return {"clip": clip, "track": "v1", "kind": "text", "rect": rect, "opacity": 1, "text": words}


# ------------------------------------------------------------------ #20 long films
def long_resolved(seconds=900, fps=30, extra_clips=(), items=()):
    total = seconds * fps
    clips = [{"id": "title", "type": "text", "track": "v1", "from": 30, "dur": total - 60, "enter": None, "exit": None},
             *extra_clips]
    return {"fps": fps, "durationInFrames": total,
            "tracks": [{"id": "v1", "kind": "visual", "clips": clips},
                       {"id": "cap", "kind": "captions", "items": list(items)},
                       {"id": "ghost", "kind": "captions", "hidden": True, "items": [{"from": 9001, "to": 9005}]}]}


def test_layout_frames_space_out_past_ten_minutes_and_measure_every_text_once():
    short = long_resolved(seconds=60)
    assert R.layout_step(short) == 30 and R.layout_frames(short)[:3] == [0, 30, 60]     # a still a second, as before
    blip = {"id": "blip", "type": "text", "track": "v1", "from": 3003, "dur": 9, "enter": None, "exit": None}
    faded = {"id": "faded", "type": "component", "track": "v1", "from": 6000, "dur": 60, "enter": {"dur": 46},
             "exit": None}
    film = long_resolved(extra_clips=[blip, faded], items=[{"from": 4501, "to": 4510}])
    frames = R.layout_frames(film)
    step = R.layout_step(film)
    assert step == 45                                           # 27000 frames: 600 grid stills, 1.5 s apart
    grid = set(range(0, 27000, step)) | {26999}
    assert 3007 in frames and 4505 in frames                    # a short text and a caption between grid stills
    assert 6052 in frames                                       # measured after its enter (6046-6059), not on 6030
    assert 9003 not in frames                                   # a hidden track is never rendered
    assert set(frames) - grid == {3007, 4505, 6052} and len(frames) == len(grid) + 3


def test_render_measures_a_long_film_in_batches_and_keeps_only_flagged_stills(tmp_path, monkeypatch):
    # a 15 min film: before, one render.mjs call of 901 stills was refused ("at most 600 per call")
    root = make_project(tmp_path, monkeypatch, duration=900, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end"}]},
        {"id": "v1", "kind": "visual", "clips": [
            {"id": "title", "type": "text", "text": "A long talk", "start": 1, "end": "end-1",
             "box": {"x": 20, "y": 20, "w": 150, "h": 30}}]},
        {"id": "v2", "kind": "visual", "clips": [
            {"id": "blip", "type": "text", "text": "!", "start": 100.1, "end": 100.4,
             "box": {"x": 20, "y": 60, "w": 50, "h": 30}}]}])
    flagged = 9000                                              # one frame shows text outside the safe area
    node = Node(items_for=lambda f: [text_item("title", [0, 0, 150, 30], "A long talk")] if f == flagged else [],
                film_ok=False)
    monkeypatch.setattr(R, "run_node", node)
    rep = R.render(root)
    inspects = [c for c in node.calls if c["mode"] == "inspect"]
    resolved = json.loads((root / "build" / "resolved.film.json").read_text(encoding="utf-8"))
    asked = sorted(f for c in inspects for f in c["frames"])
    assert asked == R.layout_frames(resolved) and 3007 in asked and rep["layout_measured"] == len(asked)
    assert len(inspects) >= 3 and all(len(c["frames"]) <= R.LAYOUT_BATCH for c in inspects)
    assert max(node.stills_waiting) <= 1                        # each batch's clean stills are gone before the next
    assert rep["stage"] == "layout" and "title @ 300.0s" in rep["layout"][0]
    assert rep["layout_frames"] == [str(root / "build" / "inspect" / f"still_{flagged:05d}.png")]
    assert sorted(p.name for p in (root / "build" / "inspect").glob("*.png")) == [f"still_{flagged:05d}.png"]
    assert all(c["timeout"] >= R.STILLS_TIMEOUT_S for c in inspects)
    node.items_for = lambda f: []                               # fixed: on to the film, whose timeout scales
    rep = R.render(root)
    film = [c for c in node.calls if c["mode"] == "film"][-1]
    assert rep["stage"] == "film" and film["timeout"] == pytest.approx(0.25 * 27000)


def test_preview_sweep_of_a_long_film_is_batched_too(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=700, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end"}]}])
    node = Node()
    monkeypatch.setattr(R, "run_node", node)
    r = T.preview(str(root), [12], sweep=True)
    assert r.ok, r
    assert all(len(c["frames"]) <= R.LAYOUT_BATCH for c in node.calls) and len(node.calls) >= 3
    # 21000 frames: 600 grid stills 35 frames apart, the last frame and the asked one
    assert "sweep: measured 602 still(s), one every 1.17 s" in r and "kept 1 (asked or flagged)" in r


@pytest.mark.skipif(not os.environ.get("REELSMITH_SLOW_TESTS"), reason="slow: set REELSMITH_SLOW_TESTS=1 (minutes)")
def test_the_real_renderer_measures_a_fifteen_minute_film(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=900, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end",
                                                  "fill": "night"}]},
        {"id": "v1", "kind": "visual", "clips": [
            {"id": f"t{n}", "type": "text", "text": f"Part {n}", "start": n * 60 + 1, "dur": 0.4,
             "box": {"x": 20, "y": 20, "w": 150, "h": 40}} for n in range(15)]}])
    res = R.preview(root, [], sweep=True)
    assert res["ok"], res
    assert res["sweep"]["measured"] == len(R.layout_frames(json.loads(
        (root / "build" / "resolved.preview.json").read_text(encoding="utf-8")))) > 600
    assert res["layout"] == [] and res["sweep"]["kept"] == 0
    assert list((root / "build" / "stills").glob("still_*.png")) == []


def test_timeouts_scale_with_the_film():
    assert R.film_timeout(30 * 60) == R.FILM_TIMEOUT_S                # a minute: the floor
    assert R.film_timeout(30 * 3600) == pytest.approx(0.25 * 108000)  # an hour at 30 fps: 7.5 h before "hung"
    assert media.scaled_timeout(10) == 600 and media.scaled_timeout(7200) == 7200
    assert media.scaled_timeout(7200, 600, 0.5) == 3600


def test_layout_check_in_batches_drops_a_clip_found_crashed_later():
    check = LayoutCheck(LANDSCAPE)
    check.add({"frames": [{"frame": 0, "items": [text_item("k", [0, 0, 300, 40], "ZzThrow: boom")]}]})
    check.add({"frames": [{"frame": 30, "items": [text_item("t", [0, 0, 300, 40], "edge")]}]})
    assert {i.where for i in check.issues()} == {"k @ 0.0s", "t @ 1.0s"} and check.first_frames() == {0, 30}
    check.ignore.add("k")
    assert [i.where for i in check.issues()] == ["t @ 1.0s"] and check.first_frames() == {30}


# ------------------------------------------------------------------ #23 sidecar captions
def test_srt_and_vtt_formats():
    rows = sidecar.cues({"items": [{"from": 0, "to": 45, "runs": [{"text": "Hello "}, {"text": "world", "accent": True}]},
                                   {"from": 3600 * 30 + 15, "to": 3600 * 30 + 99999, "runs": [{"text": "a < b & c"}]},
                                   {"from": 50, "to": 50, "runs": [{"text": "empty span"}]},
                                   {"from": 60, "to": 90, "runs": [{"text": "  "}]}]},
                        30, 3600 * 30 + 60)
    assert rows == [(0.0, 1.5, "Hello world"), (3600.5, 3602.0, "a < b & c")]       # clamped to the film's end
    assert sidecar.srt(rows) == ("1\n00:00:00,000 --> 00:00:01,500\nHello world\n\n"
                                 "2\n01:00:00,500 --> 01:00:02,000\na < b & c\n\n")
    assert sidecar.vtt(rows, "es") == ("WEBVTT\nLanguage: es\n\n00:00:00.000 --> 00:00:01.500\nHello world\n\n"
                                       "01:00:00.500 --> 01:00:02.000\na &lt; b &amp; c\n\n")
    assert sidecar.vtt([], None) == "WEBVTT\n\n"


def captions_tracks():
    return [{"id": "cap", "kind": "captions", "items": [{"start": 0, "end": 1.5, "text": "Hello **there**"},
                                                        {"start": 1.5, "end": 2.9, "text": "and welcome"}]},
            {"id": "cap_es", "kind": "captions", "hidden": True, "language": "es",
             "items": [{"start": 0, "end": 1.5, "text": "Hola"}, {"start": 1.5, "end": 2.9, "text": "y bienvenidos"}]}]


def test_export_captions_writes_every_track_without_rendering(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=3, tracks=captions_tracks())
    r = T.export_captions(str(root))
    assert r.ok, r
    folder = root / "out" / "captions"
    assert (folder / "cap.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello there\n\n2\n00:00:01,500 --> 00:00:02,900\nand welcome\n\n")
    vtt = (folder / "cap_es.vtt").read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT\nLanguage: es\n\n") and "y bienvenidos" in vtt
    assert (folder / "cap.vtt").read_text(encoding="utf-8").startswith("WEBVTT\nLanguage: en\n")
    assert "cap (en, 2 cue(s))" in r and "cap_es (es, hidden, 2 cue(s))" in r
    assert not (root / "out" / "film.mp4").exists()
    (folder / "cap.srt").unlink()
    assert T.export_captions(str(root), "cap_es").ok and not (folder / "cap.srt").exists()     # one track alone
    r = T.export_captions(str(root), "nope")
    assert not r.ok and "no captions track 'nope'" in r and "cap, cap_es" in r
    assert cli.main(["captions", str(root), "--track", "cap"]) == 0 and (folder / "cap.srt").is_file()


def test_captions_language_is_validated_and_a_project_without_captions_says_so(tmp_path, monkeypatch):
    tracks = captions_tracks()
    tracks[1]["language"] = "not a tag!"
    root = make_project(tmp_path, monkeypatch, duration=3, tracks=tracks)
    r = T.check(str(root))
    assert not r.ok and "track cap_es.language" in r
    r = T.export_captions(str(root))
    assert not r.ok and "does not validate" in r
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    data["tracks"] = []
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    r = T.export_captions(str(root))
    assert not r.ok and "no captions track" in r


# ------------------------------------------------------------------ #33 chapters and drafts
def test_chapters_validate_and_format_for_youtube(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=30, markers={"m": 12},
                        chapters=[{"at": 0, "title": "Intro"}, {"at": "mark:m", "title": "The = part; #2"},
                                  {"at": 12, "title": "Same frame"}, {"at": 31, "title": "Too late"}])
    r = T.check(str(root))
    assert not r.ok and "chapters[3].at: 31.00 s is not inside the film" in r
    assert "chapters[2].at: starts on the same frame as chapters[1]" in r
    rows = sidecar.chapters(root, 30)
    assert rows[:2] == [(0.0, "Intro"), (12.0, "The = part; #2")]
    text, why = sidecar.youtube(rows[:2], 30)
    assert text == "0:00 Intro\n0:12 The = part; #2\n" and why == ["fewer than 3 chapters"]
    text, why = sidecar.youtube([(5.0, "A"), (3725.9, "B"), (3729.0, "C")], 4000)
    assert text == "0:00:05 A\n1:02:05 B\n1:02:09 C\n"
    assert why == ["the first chapter does not start at 0:00", "chapters under 10 s: B"]
    meta = sidecar.ffmetadata(rows[:2], 30)
    assert meta == (";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=12000\ntitle=Intro\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=12000\nEND=30000\ntitle=The \\= part\\; \\#2\n")
    assert "chapters: \"Intro\" 0.00; \"The = part; #2\" 12.00 (mark:m)" in T.describe(str(root))


@needs_ffmpeg
def test_render_delivers_captions_files_and_chapters(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=3, markers={"end_part": 2},
                        chapters=[{"at": 1, "title": "Middle"}, {"at": 0, "title": "Intro"},
                                  {"at": "mark:end_part", "title": "End"}],
                        tracks=[{"id": "v0", "kind": "visual", "clips": [
                            {"id": "bg", "type": "shape", "start": 0, "end": "end"}]}, *captions_tracks()])
    (root / "out" / "captions").mkdir(parents=True)
    (root / "out" / "captions" / "stale.srt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(R, "run_node", Node())
    r = T.render(str(root))
    assert r.ok, r
    out = root / "out"
    assert sorted(p.name for p in (out / "captions").iterdir()) == ["cap.srt", "cap.vtt", "cap_es.srt", "cap_es.vtt"]
    assert (out / "chapters.txt").read_text(encoding="utf-8") == "0:00 Intro\n0:01 Middle\n0:02 End\n"
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(out / "film.mp4")],
                           capture_output=True, text=True, encoding="utf-8")
    marks = json.loads(probe.stdout)["chapters"]
    assert [c["tags"]["title"] for c in marks] == ["Intro", "Middle", "End"]
    assert [round(float(c["start_time"]), 2) for c in marks] == [0, 1, 2]
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["captions"][1] == {"track": "cap_es", "language": "es", "srt": "captions/cap_es.srt",
                                   "vtt": "captions/cap_es.vtt"}
    assert meta["chapters"][0] == {"t": 0.0, "title": "Intro"} and meta["chapters_file"] == "chapters.txt"
    assert "captions cap_es (es, hidden: file only, 2 cue(s))" in r and "chapters (3, also in the mp4)" in r
    assert "YouTube shows chapters only when" in r and "chapters under 10 s" in r


@needs_ffmpeg
def test_draft_renders_a_part_small_and_leaves_the_delivery_alone(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=3, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end"}]}])
    node = Node()
    monkeypatch.setattr(R, "run_node", node)
    r = T.render(str(root), draft=True, start=1, end="clip:bg.end")
    assert r.ok, r
    call = node.calls[-1]
    assert call["mode"] == "film" and call["resolved"] == "resolved.draft.json"
    assert call["extra"] == ["--draft", "--scale=0.5", "--range=30-89"] and not [c for c in node.calls if
                                                                                 c["mode"] == "inspect"]
    assert r.startswith("DRAFT (not delivered):") and "96x54, 1.00-3.00 s" in r
    assert (root / "build" / "draft.mp4").is_file() and not (root / "out").exists()
    assert not (root / "build" / "report.json").exists()               # the runner's "latest attempt" stays put
    assert cli.main(["render", str(root), "--draft", "--scale", "0.25"]) == 0
    assert node.calls[-1]["extra"] == ["--draft", "--scale=0.25"]           # the whole film: no range
    assert "end (1.00 s) must come after start" in T.render(str(root), draft=True, start=2, end=1)
    assert "scale must be 0.1-1" in T.render(str(root), draft=True, scale=2)
    r = T.render(str(root), start=1)
    assert not r.ok and "draft=true" in r


# ------------------------------------------------------------------ #31 HDR sources
@needs_ffmpeg
def test_render_warns_for_the_hdr_videos_the_film_shows(tmp_path, monkeypatch):
    root = make_project(tmp_path, monkeypatch, duration=1)
    hlg, sdr = tmp_path / "phone.mp4", tmp_path / "screen.mp4"
    for out, (prim, trc, space) in ((hlg, ("bt2020", "arib-std-b67", "bt2020nc")), (sdr, ("bt709",) * 3)):
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=64x36:r=30:d=1", "-vf",
               f"setparams=color_primaries={prim}:color_trc={trc}:colorspace={space}", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", out)
    assert T.import_asset(str(root), "phone", str(hlg)).ok and T.import_asset(str(root), "screen", str(sdr)).ok
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    data["tracks"] = [{"id": "v1", "kind": "visual", "clips": [
                          {"id": "a", "type": "video", "asset": "phone", "start": 0, "end": 1},
                          {"id": "b", "type": "video", "asset": "screen", "start": 1, "end": 2}]},
                      {"id": "v2", "kind": "visual", "hidden": True, "clips": [
                          {"id": "c", "type": "video", "asset": "phone", "start": 0, "end": 1}]}]
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    assert R.hdr_sources(root) == [f"[warning] assets.phone: HDR video (HLG): {F.HDR_NOTE}"]
    monkeypatch.setattr(R, "run_node", Node(film_ok=False))
    rep = R.render(root)                                   # the warning is in the report (rendering stops later)
    assert rep["issues"][-1].startswith("[warning] assets.phone: HDR video (HLG)")
