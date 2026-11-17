"""sound: every kind renders at the length asked, audible, under the peak ceiling, beds loop without a jump; seeds
repeat; the tool registers the asset; mastering a voice over a ducked bed keeps the target and the voice on top."""
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from reelsmith import cli, media, sound, tools

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg/ffprobe not on PATH")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "ws"
    project = root / "projects" / "s"
    (project / "assets").mkdir(parents=True)
    (root / "workspace.json").write_text("{}", encoding="utf-8")
    (project / "project.json").write_text(json.dumps({"version": 2, "profile": "douyin", "assets": {},
                                                      "tracks": []}), encoding="utf-8")
    return project


def frames_of(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), w.getnchannels(), w.getframerate()


@pytest.mark.parametrize("kind", list(sound.KINDS))
def test_every_kind_renders(kind, tmp_path):
    bed = sound.KINDS[kind].bed
    secs = 3.0 if bed else 0.6
    out = tmp_path / f"{kind}.wav"
    info = sound.make(out, kind, secs, 11)
    n, ch, rate = frames_of(out)
    assert rate == 48000 and n == round(secs * 48000) and ch == (2 if bed else 1)
    assert info["peak"] is not None and info["peak"] > -30, "silent"
    assert info["peak"] <= sound.CEILING + 0.2, "clips"
    assert sum(info["bands"].values()) >= 98
    if bed:
        assert info["lufs"] == pytest.approx(sound.BED_LUFS, abs=1.0) or info["peak"] > sound.CEILING - 1
        assert info["seam"]["jump"] < 3, info["seam"]           # the joint is an ordinary step, not a click
        wide = sound.seam(out, ms=500)
        assert wide["diff_db"] < 4, wide


def test_seed_repeats_and_differs(tmp_path):
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    sound.make(a, "rain", 2, 5)
    sound.make(b, "rain", 2, 5)
    sound.make(c, "rain", 2, 6)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


@pytest.mark.parametrize("kind", list(sound.KINDS))
def test_every_kind_repeats_for_the_same_seed(kind, tmp_path):
    secs = 2.0 if sound.KINDS[kind].bed else 0.3
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    sound.make(a, kind, secs, 7)
    sound.make(b, kind, secs, 7)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("kind,secs", [("type", 0.05), ("footsteps", 0.05), ("heartbeat", 0.05), ("coin", 0.05),
                                       ("type", 8), ("badum", 8), ("cymbal", 8)])
def test_event_kinds_survive_extreme_lengths(kind, secs, tmp_path):
    info = sound.make(tmp_path / "x.wav", kind, secs, 2)
    assert info["peak"] is not None and info["peak"] > -30


@pytest.mark.parametrize("kind,band,share", [("ding", "high", 60), ("sparkle", "high", 80), ("cymbal", "high", 80),
                                             ("coin", "high", 80), ("heartbeat", "low", 80), ("footsteps", "low", 60),
                                             ("knock", "low", 50), ("chime", "mid", 70), ("slide_up", "mid", 70)])
def test_energy_sits_where_the_sound_lives(kind, band, share, tmp_path):
    info = sound.make(tmp_path / "x.wav", kind, 1.0, 11)
    assert info["bands"][band] >= share, info["bands"]


@pytest.mark.parametrize("kind", ["buzz", "slide_up", "slide_down"])
def test_held_tones_are_trimmed_to_the_loudness_of_hits(kind, tmp_path):
    info = sound.make(tmp_path / "x.wav", kind, 0.8, 11)
    assert info["lufs"] is not None and info["lufs"] <= -13, info


def test_gain_never_passes_the_ceiling(tmp_path):
    info = sound.make(tmp_path / "x.wav", "clink", 0.5, 1, gain_db=12)
    assert info["peak"] <= sound.CEILING + 0.2


def test_tool_registers_an_audio_asset(ws):
    r = tools.sound(str(ws), "bed", "room", 2.5, seed=3)
    assert r.ok, str(r)
    assert "LUFS" in str(r) and "loop" in str(r)
    asset = json.loads((ws / "project.json").read_text(encoding="utf-8"))["assets"]["bed"]
    assert asset["kind"] == "audio" and asset["path"] == "assets/bed.wav"
    assert "seed 3" in asset["note"]
    r = tools.sound(str(ws), "hit", "thump", 0.4)
    assert r.ok and "one-shot" in str(r)
    assert frames_of(ws / "assets" / "hit.wav")[1] == 1


def printed_clip(text: str) -> dict:
    return json.JSONDecoder().raw_decode(text[text.index('{"id"'):])[0]


@pytest.mark.parametrize("voiced", [True, False])
def test_printed_placements_are_accepted_by_edit(tmp_path, monkeypatch, voiced):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    project = tmp_path / "ws" / "projects" / "demo"
    shutil.copytree(Path(__file__).parent / "fixtures" / "demo", project)
    (tmp_path / "ws" / "workspace.json").write_text("{}", encoding="utf-8")
    if not voiced:
        doc = json.loads((project / "project.json").read_text(encoding="utf-8"))
        doc.pop("voice")
        doc["duration"] = 6
        (project / "project.json").write_text(json.dumps(doc), encoding="utf-8")
    bed, hit = tools.sound(str(project), "amb", "street", 4), tools.sound(str(project), "hit", "thump", 0.45)
    assert bed.ok and hit.ok, (bed, hit)
    one = printed_clip(str(hit))
    assert one["dur"] == 0.45
    ops = [{"op": "add_track", "track": {"id": "amb_t", "kind": "audio", "clips": [printed_clip(str(bed))]}},
           {"op": "add_track", "track": {"id": "fx", "kind": "audio", "clips": [one]}}]
    r = tools.edit(str(project), ops)
    assert "REFUSED" not in str(r), r
    assert ("duck" in str(bed)) == voiced and ("With no voice" in str(hit)) == (not voiced)


@pytest.mark.parametrize("kind,seconds,needle", [("bells", 2, "unknown kind"), ("rain", 0.5, "2-120"),
                                                 ("pop", 30, "0.05-8")])
def test_tool_refuses(ws, kind, seconds, needle):
    r = tools.sound(str(ws), "x", kind, seconds)
    assert not r.ok and needle in str(r)


def test_cli_runs_sound(ws, capsys):
    code = cli.main(["sound", str(ws), "tick1", "tick", "0.3", "--seed", "2"])
    assert code in (0, None)
    assert (ws / "assets" / "tick1.wav").is_file()


def test_description_lists_every_kind():
    doc = " ".join(tools.sound.__doc__.split())
    for name, k in sound.KINDS.items():
        assert re.search(rf"\b{name}\b", doc), name       # names only: descriptions are capped at 1024 characters
        assert f"{name} ({k.blurb})" in sound.kinds_text()
        assert len(k.blurb.replace(",", " ").split()) == 3, name


def test_mastering_keeps_target_with_a_ducked_bed(tmp_path):
    bed = tmp_path / "bed.wav"
    sound.make(bed, "street", 10, 4)
    film = tmp_path / "raw.mp4"
    # a voice-like tone in 1 s lines with 1 s gaps; the bed at 0.25, ducked to 0.5 while a line plays
    voice = ("aevalsrc=exprs='0.5*(sin(2*PI*180*t)+0.5*sin(2*PI*360*t)+0.3*sin(2*PI*720*t))"
             "*lt(mod(t,2),1)*(0.6+0.4*sin(2*PI*4*t))':s=48000:d=10")
    duck = "volume='0.25*if(lt(mod(t,2),1),0.5,1)':eval=frame"
    r = media.run([shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=30:d=10", "-f", "lavfi", "-i", voice,
                   "-i", str(bed), "-filter_complex",
                   f"[1:a]aformat=channel_layouts=stereo[v];[2:a]{duck}[b];[v][b]amix=inputs=2:normalize=0[a]",
                   "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(film)])
    assert r.returncode == 0, r.stderr
    out = tmp_path / "mastered.mp4"
    media.master(film, out, -14, -1.0)
    lufs, peak = media.loudness(out)
    assert lufs == pytest.approx(-14, abs=1.0)
    assert peak <= -1.0 + 0.3

    def level(start: float) -> float:
        rr = media.run([shutil.which("ffmpeg"), "-hide_banner", "-nostats", "-ss", str(start), "-t", "0.8",
                        "-i", str(out), "-vn", "-af", "volumedetect", "-f", "null", "-"])
        return float(rr.stderr.split("mean_volume:")[1].split("dB")[0])
    lines = sum(level(s + 0.1) for s in (0, 2, 4, 6)) / 4
    gaps = sum(level(s + 1.1) for s in (0, 2, 4, 6)) / 4
    assert lines - gaps > 15, (lines, gaps)         # the voice stays far above the bed after mastering


def temporal_diff(path: Path) -> float:
    r = media.run([shutil.which("ffmpeg"), "-hide_banner", "-i", str(path), "-vf",
                   "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                   "-an", "-f", "null", "-"])
    vals = [float(x.split("=")[1]) for x in r.stdout.splitlines() if "YAVG" in x]
    return sum(vals) / len(vals)


def test_grain_moves_keeps_colour_sound_and_length(tmp_path):
    src = tmp_path / "still.mp4"
    r = media.run([shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   "color=c=0x3060c0:s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=300:d=2", "-c:v", "libx264",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)])
    assert r.returncode == 0, r.stderr
    out = tmp_path / "grain.mp4"
    media.add_grain(src, out, 0.5)
    info = media.probe(out)
    kinds = sorted(s["codec_type"] for s in info["streams"])
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert kinds == ["audio", "video"] and (v["width"], v["height"]) == (320, 180)
    assert float(v["duration"]) == pytest.approx(2, abs=0.1)
    assert temporal_diff(src) < 0.1 < 0.5 < temporal_diff(out)
    frame = tmp_path / "f.png"
    media.run([shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", str(out),
               "-frames:v", "1", str(frame)])
    from PIL import Image
    with Image.open(frame) as im:
        r_, g_, b_ = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
    assert b_ > r_ + 80, (r_, g_, b_)                    # still blue: grain touches only the luma


def test_grain_profile_field():
    from reelsmith.profiles import ProfileError, get_profile, make_profile
    assert get_profile("douyin").grain == 0
    assert make_profile({"base": "douyin", "grain": 0.4}).grain == 0.4
    with pytest.raises(ProfileError, match="grain"):
        make_profile({"base": "douyin", "grain": 1.5})


def test_render_with_grain_still_catches_a_frozen_picture(tmp_path, monkeypatch):
    from reelsmith import render as R
    from reelsmith import tools as T
    import test_delivery as TD
    profile = {**TD.SMALL, "max_still_s": 1, "grain": 0.6}
    root = TD.make_project(tmp_path, monkeypatch, duration=3, profile=profile, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end",
                                                  "keyframes": {"x": [{"t": 0, "v": 0}, {"t": 3, "v": 40}]}}]}])
    node = TD.Node()

    def frozen(mode, resolved, project, out, frames=None, **kw):
        if mode != "film":
            return node(mode, resolved, project, out, frames, **kw)
        TD.ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=192x108:r=30:d=3", "-f", "lavfi", "-i", "sine=f=330:d=3",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out)
        return {"ok": True, "bundleMs": 10}
    monkeypatch.setattr(R, "run_node", frozen)
    r = T.render(str(root))
    assert not r.ok and "without any motion" in r, r
    assert not (root / "build" / "film.clean.mp4").exists()
    rejected = root / "build" / "film.rejected.mp4"
    assert temporal_diff(rejected) > 0.3                 # the grain is on the film all the same


def moving_project(tmp_path, monkeypatch, **profile):
    import test_delivery as TD
    return TD.make_project(tmp_path, monkeypatch, duration=3, profile={**TD.SMALL, **profile}, tracks=[
        {"id": "v0", "kind": "visual", "clips": [{"id": "bg", "type": "shape", "start": 0, "end": "end",
                                                  "keyframes": {"x": [{"t": 0, "v": 0}, {"t": 3, "v": 40}]}}]},
        {"id": "a0", "kind": "audio", "clips": []}]), TD


def ffmpeg_times_out(monkeypatch):
    real = media.run

    def run(cmd, timeout=600):
        if "ffmpeg" in Path(cmd[0]).name.lower():
            raise subprocess.TimeoutExpired(cmd, timeout)
        return real(cmd, timeout)
    monkeypatch.setattr(media, "run", run)


def test_grain_timeout_is_a_runtime_error_and_leaves_no_file(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    media.run([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=64x64:d=1",
               "-pix_fmt", "yuv420p", str(src)])
    dst = tmp_path / "dst.mp4"
    dst.write_bytes(b"partial")
    ffmpeg_times_out(monkeypatch)
    with pytest.raises(RuntimeError, match="ran over 7 s"):
        media.add_grain(src, dst, 0.3, timeout=7)
    assert not dst.exists()


def run_grained(tmp_path, monkeypatch, fake_grain, **profile):
    from reelsmith import render as R
    root, TD = moving_project(tmp_path, monkeypatch, grain=0.5, **profile)
    monkeypatch.setattr(R, "run_node", TD.Node())
    monkeypatch.setattr(R.media, "add_grain", fake_grain)
    r = tools.render(str(root))
    rep = json.loads((root / "out" / "report.json").read_text(encoding="utf-8")) if r.ok else {}
    return r, root, rep


def test_render_delivers_clean_film_when_grain_times_out(tmp_path, monkeypatch):
    real = media.add_grain

    def slow(*a, **kw):
        with pytest.MonkeyPatch.context() as m:
            ffmpeg_times_out(m)
            return real(*a, **kw)
    r, root, rep = run_grained(tmp_path, monkeypatch, slow)
    assert r.ok and "grain could not be added" in str(r) and "ran over" in str(r), r
    assert "grain" not in rep
    assert sorted(p.name for p in (root / "build").glob("film.*.mp4")) == []


def test_render_delivers_clean_film_when_only_grain_breaks_the_size_limit(tmp_path, monkeypatch):
    def fat(src, dst, grain, timeout=600, max_mb=None):
        shutil.copyfile(src, dst)
        with open(dst, "ab") as f:
            f.write(b"\0" * 2_000_000)
    r, root, rep = run_grained(tmp_path, monkeypatch, fat, max_mb=1)
    assert r.ok and "upload limit" in str(r) and "without it" in str(r), r
    assert "grain" not in rep and rep["film_check"]["size_mb"] <= 1
    assert not (root / "build" / "film.clean.mp4").exists()


@pytest.mark.parametrize("peak,noted", [(1.4, True), (-0.2, False)])
def test_a_peak_over_the_ceiling_is_a_note_not_a_problem(tmp_path, monkeypatch, peak, noted):
    from reelsmith import checks as C
    import test_checks as TC
    film = TC.make_film(tmp_path / "f.mp4")
    monkeypatch.setattr(C.media, "loudness", lambda path, timeout=600: (-16.0, peak))
    res = C.check_film(film, TC.TINY)
    assert res["ok"], res["problems"]
    hits = [n for n in res["notes"] if "true peak" in n]
    assert bool(hits) == noted, res["notes"]
    if noted:
        assert "+1.4 dBTP" in hits[0] and "no voice" in hits[0]


def test_grain_cap_keeps_a_long_film_inside_max_mb():
    from reelsmith.profiles import get_profile
    p = get_profile("channels")
    info = {"streams": [{"codec_type": "video", "width": p.width, "height": p.height, "r_frame_rate": "30/1",
                         "duration": str(p.max_s)}, {"codec_type": "audio", "bit_rate": "192000"}]}
    bpp = round(media.GRAIN_BPP * p.width * p.height * 30)
    assert media.grain_cap(info) == bpp
    cap = media.grain_cap(info, p.max_mb)
    assert cap < bpp and (cap + 192000) * p.max_s / 8e6 <= 0.9 * p.max_mb + 1
    info["streams"][0]["duration"] = "20"
    assert media.grain_cap(info, p.max_mb) == bpp            # a short film keeps the pixel cap
    with pytest.raises(RuntimeError, match="no room"):
        media.grain_cap(info, 0.001)
