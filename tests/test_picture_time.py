"""What a clip can do to its picture and time: focus keyframes (reframing), flips, filters, animated images, hold,
speed curves, reverse, and fractional frame rates."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from reelsmith import checks as C
from reelsmith import document as D
from reelsmith import media as M
from reelsmith import ops
from reelsmith import render as RN
from reelsmith import resolve as R
from reelsmith import timeexpr as T

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg/ffprobe not on PATH")
needs_renderer = pytest.mark.skipif(not (shutil.which("node") and shutil.which("ffmpeg")
                                         and (RN.RENDERER / "node_modules" / "remotion").is_dir()),
                                    reason="node, ffmpeg or the renderer's packages missing")
_MEDIA: dict = {}
FF = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
# 2 s at 30 fps whose frame n is grey level 4n; a 1 kHz tone for the first second, then silence
COUNTER = ["-f", "lavfi", "-i", "color=black:s=64x64:r=30:d=2,format=gray,geq=lum=N*4", "-f", "lavfi", "-i",
           "aevalsrc='if(lt(t,1),sin(2*PI*1000*t),0)':d=2:s=48000", "-c:v", "libx264", "-crf", "8", "-g", "30",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
GIFS = {
    "anim.gif": ["-f", "lavfi", "-i", "color=red:s=40x40:d=1:r=10", "-f", "lavfi", "-i", "color=blue:s=40x40:d=1:r=10",
                 "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-loop", "0"],
    "still.gif": ["-f", "lavfi", "-i", "color=red:s=40x40", "-frames:v", "1"],
    "still.png": ["-f", "lavfi", "-i", "color=red:s=40x40", "-frames:v", "1"],
}


def _make(tmp_path_factory, name: str, args: list) -> bytes:
    if name not in _MEDIA:
        out = tmp_path_factory.mktemp("pt") / name
        subprocess.run(FF + args + [str(out)], check=True, capture_output=True)
        _MEDIA[name] = out.read_bytes()
    return _MEDIA[name]


def write(p: Path, data: dict) -> None:
    (p / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def raw(p: Path) -> dict:
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


def clip_of(data: dict, cid: str) -> dict:
    return next(c for t in data["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def rclip(resolved: dict, cid: str) -> dict:
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def issues(p: Path, level: str = "error") -> list[str]:
    return [str(i) for i in D.check_data(p, raw(p))[1] if i.level == level]


def apply(p: Path, *batch) -> str:
    good, found, summary = ops.apply(p, list(batch))
    assert good, [str(i) for i in found] + [summary]
    return summary


def level(video: Path, n: int) -> float:
    """Mean grey of the middle of frame n."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{n}),crop=8:8:28:28",
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    return sum(r.stdout) / max(1, len(r.stdout))


def loudness(video: Path, start: float, length: float) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(video), "-vn", "-af",
                        "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    line = next((ln for ln in r.stderr.splitlines() if "mean_volume" in ln), "mean_volume: -99 dB")
    return float(line.split("mean_volume:")[1].split()[0])


@pytest.fixture
def proj(tmp_path, tmp_path_factory, monkeypatch):
    """A project with the counter video as asset `n`; tracks are set per test."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not on PATH")
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "p"
    (p / "assets").mkdir(parents=True)
    (p / "assets" / "n.mp4").write_bytes(_make(tmp_path_factory, "n.mp4", COUNTER))
    return p


def project(p: Path, clips: list, **extra) -> None:
    write(p, {"version": 2, "duration": 2, "assets": {"n": {"path": "assets/n.mp4", "kind": "video"}},
              "tracks": [{"id": "v", "kind": "visual", "clips": clips}], **extra})


# ------------------------------------------------------------------ focus keyframes, flips, filters
def test_focus_keyframes_flips_and_filters_validate_and_resolve(proj):
    project(proj, [{"id": "a", "type": "video", "asset": "n", "start": 0, "dur": 2, "flip_x": True,
                    "filter": {"hue_rotate": 90, "sepia": 0.4, "invert": 0.1},
                    "keyframes": {"focus_x": [{"t": 0, "v": 0.2}, {"t": 1.5, "v": 0.8, "ease": "inOut"}],
                                  "contrast": [{"t": 0, "v": 0}, {"t": 1, "v": 1.2}],
                                  "hue_rotate": [{"t": 0, "v": -30}, {"t": 1, "v": 400}]}}])
    assert issues(proj) == []
    res = R.resolve(proj)
    a = rclip(res, "a")
    assert a["style"]["flipX"] is True and a["style"]["flipY"] is False
    assert a["style"]["filter"] == {"hue_rotate": 90, "sepia": 0.4, "invert": 0.1}
    assert [k["v"] for k in a["keyframes"]["focus_x"]] == [0.2, 0.8] and a["keyframes"]["focus_x"][1]["f"] == 45
    assert set(a["keyframes"]) == {"focus_x", "contrast", "hue_rotate"}
    assert "flip x" in R.describe(proj)


@pytest.mark.parametrize("clip, fragment", [
    ({"type": "text", "text": "hi", "keyframes": {"focus_x": [{"t": 0, "v": 0.5}]}},
     "focus_x moves the picture inside an image or video clip's box (a text clip has none)"),
    ({"type": "video", "asset": "n", "keyframes": {"focus_y": [{"t": 0, "v": 1.5}]}}, "focus_y keyframes take values 0 to 1"),
    ({"type": "video", "asset": "n", "keyframes": {"grayscale": [{"t": 0, "v": 2}]}}, "grayscale keyframes take values 0 to 1"),
    ({"type": "shape", "keyframes": {"contrast": [{"t": 0, "v": -1}]}}, "contrast keyframes take values 0 or more"),
    ({"type": "shape", "keyframes": {"rate": [{"t": 0, "v": 2}]}}, "rate keyframes are a video clip's speed curve"),
    ({"type": "video", "asset": "n", "keyframes": {"rate": [{"t": 0, "v": 20}]}}, "rate keyframes take values 0 to 16"),
    ({"type": "video", "asset": "n", "loop": True, "keyframes": {"rate": [{"t": 0, "v": 2}]}},
     "a clip that has a speed curve cannot loop"),
    ({"type": "video", "asset": "n", "loop": True, "reverse": True}, "a clip that plays backwards cannot loop"),
])
def test_picture_and_time_mistakes_are_errors(proj, clip, fragment):
    project(proj, [{"id": "a", "start": 0, "dur": 2, **clip}])
    found = issues(proj)
    assert any(fragment in row for row in found), found


def test_new_filter_fields_are_checked_by_the_schema(proj):
    project(proj, [{"id": "a", "type": "shape", "start": 0, "dur": 2, "filter": {"sepia": 1.5}}])
    with pytest.raises(D.DocumentError, match="sepia"):
        D.load(proj)


# ------------------------------------------------------------------ hold and speed curves
def test_source_frames_sum_a_speed_curve_frame_by_frame():
    assert R.source_frames(1.5, None, 20, 30) == 30
    keys = [{"f": 0, "v": 1, "ease": "linear"}, {"f": 20, "v": 3, "ease": "step"}]
    assert R.source_frames(1, keys, 20, 30) == 20 and R.source_frames(1, keys, 30, 30) == 20 + 10 * 3
    ramp = [{"f": 0, "v": 0, "ease": "linear"}, {"f": 10, "v": 1, "ease": "linear"}]
    assert R.source_frames(1, ramp, 11, 30) == pytest.approx(sum(f / 10 for f in range(11)))


def test_hold_and_a_speed_curve_resolve_to_frames_and_play_silent(proj):
    project(proj, [
        {"id": "h", "type": "video", "asset": "n", "start": 0, "dur": 1, "hold": 0.5, "volume": 1},
        {"id": "s", "type": "video", "asset": "n", "start": 1, "dur": 1, "trim_in": 0.2,
         "keyframes": {"rate": [{"t": 0, "v": 0.5}, {"t": 0.5, "v": 2}]}}],
        markers={"bad": "src:h@0.5"})
    errors = issues(proj)
    assert any("src:h@0.5: clip h holds one frame (hold), so source seconds are not film times" in e for e in errors)
    assert any("a held clip plays the picture only: its sound is silent" in w for w in issues(proj, "warning"))
    data = raw(proj)
    data["markers"] = {}
    write(proj, data)
    assert issues(proj) == []
    res = R.resolve(proj)
    h, s = rclip(res, "h")["content"], rclip(res, "s")["content"]
    assert h["hold"] == 15 and h["loop"] is False
    assert s["rateKeys"] == [{"f": 0, "v": 0.5, "ease": "linear"}, {"f": 15, "v": 2, "ease": "linear"}]
    assert s["trimIn"] == 6 and "rate" not in rclip(res, "s")["keyframes"]
    doc = D.load(proj)
    assert not any(R.sounds(c) for _, c in D.clips_of(doc))     # neither ducks a bed nor crossfades sound
    assert "hold 0.5s" in R.describe(proj)


def test_hold_with_reverse_or_loop_warns(proj):
    project(proj, [{"id": "h", "type": "video", "asset": "n", "start": 0, "dur": 1, "hold": 0.5, "reverse": True,
                    "loop": True}])
    assert any("hold shows one frame for the whole clip: reverse, loop do nothing" in w
               for w in issues(proj, "warning"))


def test_transcript_captions_refuse_a_retimed_clip(proj):
    words = {"words": [{"word": "hi", "start": 0.1, "end": 0.4}]}
    (proj / "assets" / "n.transcript.json").write_text(json.dumps(words), encoding="utf-8")
    write(proj, {"version": 2, "duration": 2,
                 "assets": {"n": {"path": "assets/n.mp4", "kind": "video", "transcript": "assets/n.transcript.json"}},
                 "tracks": [{"id": "v", "kind": "visual", "clips": [
                     {"id": "a", "type": "video", "asset": "n", "start": 0, "dur": 2, "volume": 1, "reverse": True}]},
                     {"id": "cap", "kind": "captions", "source": "clip:a"}]})
    assert any("clip a plays backwards (reverse): captions from a transcript need a clip that plays its source "
               "forward at one rate" in e for e in issues(proj))


def test_split_carries_a_speed_curve_and_a_reverse_over(proj):
    project(proj, [
        {"id": "s", "type": "video", "asset": "n", "start": 0, "dur": 2, "trim_in": 0.1,
         "keyframes": {"rate": [{"t": 0, "v": 1}, {"t": 1, "v": 3, "ease": "step"}]}},
    ])
    apply(proj, {"op": "split_clip", "id": "s", "at": 1.5, "new_id": "s2"})
    data = raw(proj)
    # 30 frames at 1, then 15 at 3: the source has moved on 75 frames (2.5 s) at the cut
    assert clip_of(data, "s2")["trim_in"] == pytest.approx(0.1 + 2.5) and clip_of(data, "s")["trim_in"] == 0.1
    project(proj, [{"id": "r", "type": "video", "asset": "n", "start": 0, "dur": 2, "trim_in": 0.5, "rate": 0.5,
                    "reverse": True}])
    apply(proj, {"op": "split_clip", "id": "r", "at": 0.5, "new_id": "r2"})
    data = raw(proj)
    # span 0.5-1.5 s backwards: the first half shows 1.25-1.5, the second 0.5-1.25
    assert clip_of(data, "r")["trim_in"] == pytest.approx(1.25) and clip_of(data, "r2")["trim_in"] == 0.5


def test_trim_clip_refuses_a_retimed_clip(proj):
    project(proj, [{"id": "r", "type": "video", "asset": "n", "start": 0, "dur": 2, "reverse": True}])
    good, found, _ = ops.apply(proj, [{"op": "trim_clip", "id": "r", "in": 0.5}])
    assert not good and "clip r plays backwards (reverse), so its source seconds are not in film order" in " ".join(
        str(i) for i in found)


# ------------------------------------------------------------------ reverse
@needs_ffmpeg
def test_reverse_plays_a_cached_proxy_of_the_span_backwards(proj, monkeypatch):
    project(proj, [{"id": "r", "type": "video", "asset": "n", "start": 0, "dur": 1, "trim_in": 0.5, "reverse": True,
                    "volume": 1}])
    stale = proj / "build" / "proxies" / "n-rev-000000000000.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    os.utime(stale, (time.time() - 2 * R.PROXY_KEEP_S, time.time() - 2 * R.PROXY_KEEP_S))
    made = []
    real = M.reverse_span
    monkeypatch.setattr(M, "reverse_span", lambda *a, **k: (made.append(a), real(*a, **k))[1])
    content = rclip(R.resolve(proj), "r")["content"]
    assert content["src"].startswith("build/proxies/n-rev-") and content["reversed"] is True
    assert content["trimIn"] == 0 and 1.0 < content["duration"] < 1.2 and not stale.exists()
    proxy = proj / content["src"]
    # the forward clip would show source frames 15..44 (grey 4n): backwards, then two frames of margin
    assert [round(level(proxy, n) / 4) for n in (0, 14, 29, 31)] == [44, 30, 15, 13]
    assert loudness(proxy, 0.05, 0.35) < -60 and loudness(proxy, 0.6, 0.3) > -30     # the tone comes back at the end
    assert rclip(R.resolve(proj), "r")["content"]["src"] == content["src"] and len(made) == 1


@needs_ffmpeg
def test_reverse_in_pieces_keeps_every_frame_in_order(proj, monkeypatch):
    monkeypatch.setattr(M, "REVERSE_BUDGET", 64 * 64 * 1.5 * 7)          # seven 64x64 frames a piece
    out = proj / "rev.mp4"
    M.reverse_span(proj / "assets" / "n.mp4", 0.5, 1.5, out)
    got = [level(out, n) for n in range(0, 30, 3)]
    want = [4 * (44 - n) for n in range(0, 30, 3)]
    assert all(abs(g - w) < 8 for g, w in zip(got, want)), (got, want)
    assert abs(M.duration(out) - 1.0) < 0.1


# ------------------------------------------------------------------ animated images
@needs_ffmpeg
def test_animated_images_are_marked_to_play(proj, tmp_path_factory):
    for name, args in GIFS.items():
        (proj / "assets" / name).write_bytes(_make(tmp_path_factory, name, args))
    apng = proj / "assets" / "anim.apng.png"
    subprocess.run(FF + ["-i", str(proj / "assets" / "anim.gif"), "-plays", "0", "-f", "apng", str(apng)], check=True)
    assert [R.image_animated(proj / "assets" / n) for n in ("anim.gif", "still.gif", "still.png", "anim.apng.png")] == [
        True, False, False, True]
    write(proj, {"version": 2, "duration": 2,
                 "assets": {"g": {"path": "assets/anim.gif", "kind": "image"},
                            "s": {"path": "assets/still.gif", "kind": "image"}},
                 "tracks": [{"id": "v", "kind": "visual", "clips": [
                     {"id": "a", "type": "image", "asset": "g", "start": 0, "dur": 1},
                     {"id": "b", "type": "image", "asset": "s", "start": 1, "dur": 1}]}]})
    res = R.resolve(proj)
    assert rclip(res, "a")["content"]["animated"] is True and "animated" not in rclip(res, "b")["content"]


# ------------------------------------------------------------------ fractional frame rates
@needs_ffmpeg
def test_film_check_takes_an_ntsc_rate(tmp_path):
    from reelsmith import profiles as P
    ntsc = P.make_profile({"width": 160, "height": 90, "fps": "30000/1001"}, name="ntsc")
    film = tmp_path / "f.mp4"
    subprocess.run(FF + ["-f", "lavfi", "-i", "testsrc2=s=160x90:r=30000/1001:d=1", "-c:v", "libx264", "-pix_fmt",
                         "yuv420p", str(film)], check=True)
    out = C.check_film(film, ntsc)
    assert out["ok"] and out["fps"] == 29.97, out
    assert "29.97 fps; want 30" in C.check_film(film, P.make_profile({"width": 160, "height": 90}))["why"]


@needs_renderer
def test_a_29_97_film_renders_at_30000_1001_and_plays_a_reversed_clip(proj):
    project(proj, [{"id": "a", "type": "video", "asset": "n", "start": 0, "dur": 1, "trim_in": 0.5, "reverse": True}],
            profile={"width": 160, "height": 90, "fps": 29.97})
    data = raw(proj)
    data["duration"] = 1
    write(proj, data)
    assert R.describe(proj).startswith("project p: custom 160x90 29.97 fps")
    report = RN.render(proj)
    assert report["ok"], report.get("error")
    film = proj / "out" / "film.mp4"
    stream = next(s for s in M.probe(film)["streams"] if s["codec_type"] == "video")
    assert stream["r_frame_rate"] == "30000/1001" and stream["avg_frame_rate"] == "30000/1001"
    assert report["film_check"]["fps"] == 29.97 and int(stream["nb_frames"]) == 30
    # the proxy served from build/proxies: source frames 44 down to 15
    assert abs(level(film, 0) - 176) < 10 and abs(level(film, 15) - 116) < 10 and abs(level(film, 29) - 60) < 10
