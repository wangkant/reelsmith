"""Drawn-pose animation's tool side: twins registered onto their base drawing (draw's twin_of) and the narration's
loudness a frame at a time for mouth flaps (useVoiceLevel)."""
import importlib
import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from reelsmith import providers as P
from reelsmith import resolve as R
from reelsmith import voicelevel as V
from reelsmith.providers import twin as TW

D = importlib.import_module("reelsmith.providers.draw")
ROOT = Path(__file__).resolve().parent.parent
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")


def figure(size, s=1.0, shift=(0, 0), mouth="open", pose="stand", stripe=False):
    """A drawn cut-out: a body, a head with eyes and a mouth, outlined, on a clear canvas; `stripe` redraws a mark
    on the belly, far from the mouth."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox, oy = shift
    p = lambda x, y: (ox + x * s, oy + y * s)  # noqa: E731
    box = lambda a, b, c, e: [*p(a, b), *p(c, e)]  # noqa: E731
    line, w = (40, 20, 10, 255), max(2, round(6 * s))
    if pose == "stand":
        d.rounded_rectangle(box(70, 200, 230, 460), radius=round(40 * s), fill=(230, 140, 50, 255), outline=line, width=w)
    else:
        d.polygon([p(20, 230), p(280, 210), p(250, 300), p(40, 320)], fill=(230, 140, 50, 255), outline=line, width=w)
    d.ellipse(box(60, 40, 240, 220), fill=(240, 160, 70, 255), outline=line, width=w)
    for ex in (110, 190):
        d.ellipse(box(ex - 10, 100, ex + 10, 125), fill=line)
    if mouth == "open":
        d.ellipse(box(125, 150, 175, 195), fill=(120, 30, 30, 255), outline=line, width=w)
    else:
        d.line([p(125, 170), p(175, 170)], fill=line, width=w)
    if stripe:
        d.rectangle(box(100, 400, 125, 425), fill=(20, 40, 120, 255))
    return img


def test_a_twin_is_laid_onto_its_base_canvas_with_the_scale_and_shift_recovered(tmp_path):
    base = figure((300, 500))
    twin = figure((340, 560), s=1.08, shift=(14, 9), mouth="shut")        # redrawn bigger, off-centre
    base.save(tmp_path / "a.png")
    twin.save(tmp_path / "a_shut.png")
    r = TW.register(tmp_path / "a.png", tmp_path / "a_shut.png", tmp_path / "out.png")
    assert abs(r["scale"] - 1 / 1.08) < 0.01, r
    assert abs(r["dx"] + 14 / 1.08) <= 2 and abs(r["dy"] + 9 / 1.08) <= 2, r
    assert r["same"] and r["residual"] < 0.03 and (r["width"], r["height"]) == (300, 500)
    out = Image.open(tmp_path / "out.png")
    assert out.size == base.size and out.mode == "RGBA"
    x0, y0, x1, y1 = r["changed"]                                         # the change is found at the mouth
    assert 100 <= x0 and x1 <= 200 and 130 <= y0 and y1 <= 215, r["changed"]
    # outside the change the base's own pixels: nothing boils when the two swap
    assert out.getpixel((150, 350)) == base.getpixel((150, 350)) and out.getpixel((75, 300)) == base.getpixel((75, 300))
    assert "Registered onto 'a'" in TW.report("a", r) and "not the same pose" not in TW.report("a", r)


def test_only_the_asked_for_change_is_patched_in(tmp_path):
    base = figure((300, 500))
    base.save(tmp_path / "a.png")
    figure((300, 500), mouth="shut", stripe=True).save(tmp_path / "a_shut.png")   # also redrew the belly
    r = TW.register(tmp_path / "a.png", tmp_path / "a_shut.png", tmp_path / "out.png")
    out = Image.open(tmp_path / "out.png")
    assert out.getpixel((112, 412)) == base.getpixel((112, 412))          # the stray change stays the base's
    assert out.getpixel((150, 172)) != base.getpixel((150, 172))          # the mouth is the twin's
    assert len(r["left"]) == 1 and r["left"][0][0] <= 105 and r["left"][0][3] >= 420, r["left"]
    assert r["changed"][3] < 260, r["changed"]
    text = TW.report("a", r)
    assert "Also redrawn at x" in text and "kept from the base" in text, text


def test_close_regions_are_one_change():
    from PIL import Image as I
    d = I.new("L", (500, 500), 0)
    for box in ((100, 100, 140, 140), (190, 100, 230, 140), (400, 420, 440, 460)):   # two eyes and a far mark
        d.paste(255, box)
    regs = TW.regions(d, 4)
    assert len(regs) == 3 and regs[0][0] == pytest.approx(1600, rel=0.1)


def test_a_different_pose_is_not_a_twin_and_is_left_as_drawn(tmp_path):
    figure((300, 500)).save(tmp_path / "a.png")
    figure((300, 500), pose="lean").save(tmp_path / "b.png")
    r = TW.register(tmp_path / "a.png", tmp_path / "b.png", tmp_path / "out.png")
    assert not r["same"] and r["residual"] > TW.SAME_POSE_MAX, r
    assert not (tmp_path / "out.png").exists() and r["changed"] is None
    text = TW.report("a", r)
    assert "NOT A TWIN of 'a'" in text and "pose of its own" in text and "draw it again" in text.lower()
    assert "kept" not in text.replace("left as drawn", ""), text


def test_feet_are_the_middle_of_the_lowest_rows(tmp_path):
    img = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((150, 50, 330, 560), fill=(200, 100, 50, 255))           # body
    d.rectangle((170, 560, 210, 590), fill=(200, 100, 50, 255))          # left foot
    d.rectangle((290, 560, 330, 585), fill=(200, 100, 50, 255))          # right foot, a little higher
    img.save(tmp_path / "f.png")
    assert D.feet_of(tmp_path / "f.png") == pytest.approx(250 / 400, abs=0.01)
    Image.new("RGBA", (10, 10)).save(tmp_path / "clear.png")
    assert D.feet_of(tmp_path / "clear.png") is None


# ------------------------------------------------------------------ draw's twin_of
class TwinPainter:
    """Returns a redrawn twin of the base (bigger, shifted, mouth shut) as the provider's picture."""
    name = "fake"

    def __init__(self, tmp, pose="stand"):
        self.tmp, self.calls, self.pose = Path(tmp), [], pose

    def draw(self, prompt, gen_size, workdir, ref, timeout, **kw):
        self.calls.append(dict(prompt=prompt, gen=gen_size, ref=ref, **kw))
        out = self.tmp / f"gen-{len(self.calls)}.png"
        big = Image.new("RGBA", (1024, 1536), (0, 0, 0, 0))
        big.paste(figure((340, 560), s=1.08, shift=(14, 9), mouth="shut", pose=self.pose), (300, 400))
        big.resize((1024, 1536)).save(out)
        return D.Shot("ok", out, 1.0, detail="done", thread="t")

    def forget(self, shot):
        pass


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    monkeypatch.setattr(D, "_BLOCKED", {})
    ws = tmp_path / "ws"
    (ws / "projects" / "cat" / "assets").mkdir(parents=True)
    (ws / "workspace.json").write_text('{"profile": "douyin"}', encoding="utf-8")
    project = ws / "projects" / "cat"
    figure((300, 500)).save(project / "assets" / "pose.png")
    Image.new("RGB", (300, 500), (200, 200, 200)).save(project / "assets" / "plate.png")
    (project / "project.json").write_text(
        '{"version": 2, "meta": {"title": "t"}, "tracks": [], "assets": {'
        '"pose": {"path": "assets/pose.png", "kind": "image", "alpha": true, "width": 300, "height": 500},'
        '"plate": {"path": "assets/plate.png", "kind": "image"}}}', encoding="utf-8")
    return project


def test_twin_of_draws_with_the_base_as_reference_and_registers_onto_it(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_ref_jpeg", lambda ref, workdir: ref)
    painter = TwinPainter(tmp_path)
    text, err = P.draw(proj, id="pose_shut", prompt="the mouth is closed", twin_of="pose", provider=painter)
    assert not err, text
    call = painter.calls[0]
    assert call["prompt"].startswith(D.TWIN_PREFIX + "the mouth is closed") and call["prompt"].endswith(D.CUTOUT_NOTE)
    assert call["ref_note"] == D.TWIN_NOTE and Path(call["ref"]).name == "pose.png"
    assert Image.open(proj / "assets" / "pose_shut.png").size == (300, 500)
    assert "Registered onto 'pose'" in text and "300x500" in text and "NOT A TWIN" not in text
    assert "It stands at feet 0.5" in text, text
    assert "(feet 0.5" in json.loads((proj / "project.json").read_text(encoding="utf-8"))["assets"]["pose_shut"]["note"]


def test_draw_many_says_plainly_when_a_twin_is_another_pose(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_ref_jpeg", lambda ref, workdir: ref)
    text, err = D.draw_many(proj, pictures=[{"id": "pose_shut", "prompt": "the mouth is closed", "twin_of": "pose"}],
                            provider=TwinPainter(tmp_path, pose="lean"))
    assert "1. pose_shut: drawn but NOT A TWIN of 'pose'" in text and ": ok," not in text, text
    assert "pose of its own" in text and "outside it the base's own pixels are kept" not in text


@pytest.mark.parametrize("kwargs, says", [
    (dict(twin_of="pose", match_asset="plate"), "leave style_ref_asset and match_asset out"),
    (dict(twin_of="pose", style_ref_asset="plate"), "leave style_ref_asset and match_asset out"),
    (dict(twin_of="pose", size="9:16"), "leave size out"),
    (dict(twin_of="plate"), "must be a cut-out"),
    (dict(twin_of="ghost"), "twin_of 'ghost' must be an image asset"),
])
def test_twin_of_refusals(proj, tmp_path, kwargs, says):
    painter = TwinPainter(tmp_path)
    text, err = P.draw(proj, id="x", prompt="the eyes are shut", provider=painter, **kwargs)
    assert err and says in text and painter.calls == [], text
    text, err = P.draw(proj, id="pose", prompt="the eyes are shut", twin_of="pose", provider=painter)
    assert err and "must name another asset" in text


def test_draw_many_accepts_twin_of_and_waits_for_its_base(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_ref_jpeg", lambda ref, workdir: ref)
    text, err = D.draw_many(proj, pictures=[{"id": "pose_blink", "prompt": "the eyes are shut", "twin_of": "pose"}],
                            provider=TwinPainter(tmp_path))
    assert not err and "1. pose_blink: ok" in text and "Registered onto 'pose'" in text, text
    from reelsmith import tools as T
    assert "twin_of" in T.draw.__doc__ and len(T.draw.__doc__) < 1024


# ------------------------------------------------------------------ the voice's level
def tone(path, parts, rate=16000):
    """A mono wav of (seconds, amplitude 0..1) parts of a 220 Hz tone."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        n = 0
        for secs, amp in parts:
            for _ in range(int(secs * rate)):
                frames += struct.pack("<h", int(amp * 32000 * math.sin(2 * math.pi * 220 * n / rate)))
                n += 1
        w.writeframes(bytes(frames))


@needs_ffmpeg
def test_voice_level_is_loud_then_quiet_one_value_a_frame_and_cached(tmp_path, monkeypatch):
    wav = tmp_path / "voice.wav"
    tone(wav, [(1, 0.5), (1, 0.02)])
    level = V.voice_level(wav, 30, tmp_path / "build")
    assert len(level) == 60 and all(0 <= v <= 1 for v in level)
    assert min(level[2:28]) > 0.9 and max(level[32:58]) < 0.1, level
    monkeypatch.setattr(V, "decode", lambda *a: (_ for _ in ()).throw(AssertionError("decoded again")))
    assert V.voice_level(wav, 30, tmp_path / "build") == level              # from the cache
    with pytest.raises(AssertionError):
        V.voice_level(wav, 25, tmp_path / "build")                          # another fps is another envelope


def test_silence_gives_a_flat_zero():
    assert V.envelope([0] * 3200, 16000, 30) == [0.0] * 6
    assert V.envelope([], 16000, 30) == []
    assert V.envelope([20, -20] * 8000, 16000, 30) == [0.0] * 30          # hiss under the noise floor


def test_one_short_line_in_a_long_silent_file_still_opens_the_mouth():
    rate, line = 16000, [int(16000 * math.sin(2 * math.pi * 220 * n / 16000)) for n in range(int(0.4 * 16000))]
    samples = [0] * (10 * rate) + line + [0] * (10 * rate)                # 0.4 s of voice in 20.4 s
    level = V.envelope(samples, rate, 30)
    spoken = level[300:312]
    assert min(spoken[1:-1]) > 0.9 and max(level[:298] + level[314:]) == 0, spoken


@needs_ffmpeg
def test_a_component_clip_hears_the_voice_level(tmp_path):
    shutil.copytree(ROOT / "examples" / "performance", tmp_path / "performance",
                    ignore=shutil.ignore_patterns("build", "out", ".history"))
    salt = tmp_path / "performance" / "projects" / "salt"
    comps = lambda: [c for t in R.resolve(salt)["tracks"] for c in t.get("clips") or []  # noqa: E731
                     if c["type"] == "component"]
    assert comps() and not any("level" in c["content"] for c in comps())     # the example's voice is silent
    tone(salt / "voice" / "voice.m4a", [(3.3, 0.5), (0.22, 0), (4.38, 0.5), (0.22, 0), (4.48, 0.5)])
    for c in comps():
        level = c["content"]["level"]
        assert 0 < len(level) <= c["dur"] and max(level) > 0.9 and all(0 <= v <= 1 for v in level), c["id"]
