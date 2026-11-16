"""tween and parallax with a fake interpolator and a fake depth estimator; the model fetch with local fakes; one run
with the real models when a folder holding them is given in REELSMITH_TEST_MODELS."""
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
from PIL import Image  # noqa: E402

from reelsmith import cli, motion, tools  # noqa: E402
from reelsmith.providers.config import ProviderError  # noqa: E402

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg/ffprobe not on PATH")
W, H = 64, 96


def picture(path: Path, colour, size=(W, H)) -> None:
    a = np.zeros((size[1], size[0], 3), np.uint8)
    a[:] = colour
    a[size[1] // 3: size[1] // 2, size[0] // 4: size[0] // 2] = (250, 250, 250)
    Image.fromarray(a).save(path)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "ws"
    project = root / "projects" / "m"
    (project / "assets").mkdir(parents=True)
    (root / "workspace.json").write_text("{}", encoding="utf-8")
    picture(project / "assets" / "a.png", (200, 40, 40))
    picture(project / "assets" / "b.png", (40, 40, 200))
    picture(project / "assets" / "c.png", (40, 200, 40))
    picture(project / "assets" / "big.png", (90, 90, 90), (W * 2, H * 2))
    picture(project / "assets" / "wide.png", (90, 90, 90), (H, W))
    assets = {n: {"path": f"assets/{n}.png", "kind": "image"} for n in ("a", "b", "c", "big", "wide")}
    assets["song"] = {"path": "assets/song.wav", "kind": "audio"}
    (project / "project.json").write_text(json.dumps({"version": 2, "profile": "douyin", "assets": assets,
                                                      "tracks": []}), encoding="utf-8")
    return project


def video(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames,width,height,r_frame_rate,codec_name", "-show_entries",
                          "format=nb_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    return {**data["streams"][0], "streams": data["format"]["nb_streams"]}


def assets_of(project: Path) -> dict:
    return json.loads((project / "project.json").read_text(encoding="utf-8"))["assets"]


# ------------------------------------------------------------------ tween
def test_tween_plan_asks_each_time_directly_and_holds_keys():
    plan = motion.tween_plan([0, 1], 10)
    assert len(plan) == 11 and plan[0] == (0, None) and plan[-1] == (1, None)
    assert [t for _, t in plan[1:-1]] == [round(k / 10, 6) for k in range(1, 10)]
    held = motion.tween_plan([0, 0.5, 1.5], 10, hold_first=0.3, hold_last=0.2)
    assert len(held) == 21
    assert held[:4] == [(0, None)] * 4 and held[-3:] == [(2, None)] * 3
    assert held[8] == (1, None) and held[9] == (1, 0.1)


def test_tween_fills_between_keys_and_registers_a_video(ws):
    asked = []

    def fake(a, b, t):
        asked.append(t)
        return a * (1 - t) + b * t
    text, err = motion.tween(ws, "act", ["a", "b", "c"], [0, 0.5, 1.0], fps=10, hold_last=0.3, interpolate=fake)
    assert not err, text
    assert "11 frames" not in text and "14 frames" in text and "8 made between 3 key pictures" in text
    assert sorted(asked) == sorted([0.2, 0.4, 0.6, 0.8] * 2)
    info = video(ws / "assets" / "act.mp4")
    assert (int(info["nb_read_frames"]), info["width"], info["height"]) == (14, W, H)
    assert info["r_frame_rate"] == "10/1" and info["codec_name"] == "h264" and info["streams"] == 1
    entry = assets_of(ws)["act"]
    assert entry["kind"] == "video" and entry["path"] == "assets/act.mp4"
    assert "a@0, b@0.5, c@1" in entry["note"] and "hold 0/0.3" in entry["note"]


@pytest.mark.parametrize("frames, seconds, why", [
    (["a"], [0], "2-6 image asset ids"),
    (["a", "song"], [0, 1], "'song' is not an image asset"),
    (["a", "nope"], [0, 1], "'nope' is not an image asset"),
    (["a", "b"], [0], "one time for each key picture"),
    (["a", "b"], [0.5, 1], "start at 0 and rise strictly"),
    (["a", "b", "c"], [0, 1, 1], "start at 0 and rise strictly"),
    (["a", "b"], [0, 12.5], "from 0 to 12"),
    (["a", "big"], [0, 1], "'big' is 128x192 but 'a' is 64x96 (a different size)"),
    (["a", "wide"], [0, 1], "'wide' is 96x64 but 'a' is 64x96 (a different aspect)"),
])
def test_tween_refuses_in_a_plain_sentence(ws, frames, seconds, why):
    r = tools.tween(str(ws), "act", frames, seconds)
    assert not r.ok and why in r, r
    assert not (ws / "assets" / "act.mp4").exists()


def test_tween_refuses_a_clip_over_twelve_seconds(ws):
    r = tools.tween(str(ws), "act", ["a", "b"], [0, 10], hold_first=1.5, hold_last=1)
    assert not r.ok and "12.5 s; at most 12 s" in r


def test_both_tools_name_the_extra_when_it_is_missing(ws, monkeypatch):
    real = motion.importlib.util.find_spec
    monkeypatch.setattr(motion.importlib.util, "find_spec",
                        lambda name, *a: None if name == "onnxruntime" else real(name, *a))
    for r in (tools.tween(str(ws), "act", ["a", "b"], [0, 1]),
              tools.parallax(str(ws), "cam", "a", 2, {"dolly": 0.05})):
        assert not r.ok and r.count(".") <= 2 and 'pip install "reelsmith[motion]"' in r, r


def test_cli_reads_keys_as_frame_at_seconds(ws, capsys):
    assert cli.main(["tween", str(ws), "act", "a", "b@1"]) != 0
    assert "frame@seconds" in capsys.readouterr().out
    assert cli.main(["tween", str(ws), "act", "a@0", "b@1", "c@0.5"]) != 0
    assert "rise strictly" in capsys.readouterr().out


# ------------------------------------------------------------------ parallax
def step_depth(img):
    """Near on the left third, far elsewhere: one hard depth edge."""
    d = np.zeros(img.shape[:2], np.float32)
    d[:, : img.shape[1] // 3] = 1.0
    return d


def test_parallax_renders_reuses_depth_and_registers(ws):
    calls = []

    def fake(img):
        calls.append(img.shape)
        return np.tile(np.linspace(0, 1, img.shape[0], dtype=np.float32)[:, None], (1, img.shape[1]))
    text, err = motion.parallax(ws, "cam", "a", 1.5, {"dolly": 0.08, "truck": 0.01}, fps=10, estimate_depth=fake)
    assert not err, text
    assert calls == [(H, W, 3)] and "depth estimated" in text and "s a frame" in text
    assert "uncovered strip" not in text and "filled from the far side (at most " in text, text
    assert re.search(r"enlarged (\d+%|under 1%) so no border shows|needed no enlargement to keep the border out", text), text
    assert (ws / "assets" / "a.depth.png").is_file()
    info = video(ws / "assets" / "cam.mp4")
    assert (int(info["nb_read_frames"]), info["width"], info["height"]) == (15, W, H)
    entry = assets_of(ws)["cam"]
    assert entry["kind"] == "video" and "parallax of a: dolly 0.08, truck 0.01, in-out" in entry["note"]
    text, err = motion.parallax(ws, "cam2", "a", 1, {"pedestal": 0.02, "ease": "linear"}, fps=10,
                                estimate_depth=fake)
    assert not err and calls == [(H, W, 3)] and "depth reused from assets/a.depth.png" in text


@pytest.mark.parametrize("move, why", [
    ({}, "dolly, truck and/or pedestal"),
    ({"dolly": 0}, "all zero"),
    ({"dolly": 0.5}, "move.dolly must be from -0.3 to 0.3"),
    ({"truck": 0.02, "ease": "bounce"}, 'move.ease must be "in-out" or "linear"'),
    ({"truck": 0.02, "zoom": 1}, "not zoom"),
    ({"truck": 0.15}, "uncovers strips"),
    ({"dolly": -0.3}, "enlargement, at most 20%"),
])
def test_parallax_refuses_moves_it_cannot_make_clean(ws, move, why):
    depth = step_depth if "truck" in move else (lambda img: np.ones(img.shape[:2], np.float32))
    text, err = motion.parallax(ws, "cam", "a", 2, move, fps=10, estimate_depth=depth)
    assert err and why in text, text
    if why in ("uncovers strips", "enlargement, at most 20%"):
        assert "Scale it by 0." in text and suggestion(text), text


def suggestion(text: str) -> dict:
    tail = text.split("or less: ")[-1] if "or less: " in text else ""
    return {k: float(v) for k, v in re.findall(r"(dolly|truck|pedestal) (-?\d+(?:\.\d+)?)", tail)}


def flat(img):
    return np.ones(img.shape[:2], np.float32)


def ramp(img):
    return np.tile(np.linspace(0, 1, img.shape[1], dtype=np.float32)[None], (img.shape[0], 1))


@pytest.mark.parametrize("depth, move", [
    (step_depth, {"truck": 0.15}),
    (step_depth, {"truck": 0.12, "pedestal": 0.1}),
    (step_depth, {"dolly": 0.3, "truck": -0.15}),
    (flat, {"dolly": -0.3}),
    (flat, {"dolly": -0.3, "truck": 0.15}),
    (flat, {"dolly": -0.198}),
    (ramp, {"dolly": -0.3, "pedestal": -0.15}),
    (ramp, {"dolly": 0.3, "truck": 0.15, "pedestal": 0.15}),
])
def test_following_the_first_suggestion_is_accepted(ws, depth, move):
    text, err = motion.parallax(ws, "cam", "a", 0.5, move, fps=2, estimate_depth=depth)
    assert err and suggestion(text), text
    smaller = suggestion(text)
    assert set(smaller) <= set(move) and all(abs(smaller[k]) < abs(move[k]) for k in smaller), text
    text, err = motion.parallax(ws, "cam", "a", 0.5, smaller, fps=2, estimate_depth=depth)
    assert not err, (smaller, text)


def test_warp_moves_near_things_further_and_leaves_no_hole_or_border():
    img = np.full((H, W, 3), 0.5, np.float32)
    img[40:56, 8:16] = 1.0                                     # a near patch at the left
    near = step_depth(img)
    z = motion.distance(near)
    cam = motion.Camera(W, H, truck=0.06)
    window = motion.crop_for(cam, z)
    assert 1.0 <= window[2] < motion.MAX_OVERSCAN
    warp = motion.Warper(img, z, cam, window)
    first, last = warp.frame(0.0), warp.frame(1.0)
    assert np.isfinite(last).all() and last.min() >= 0.5 - 1e-3          # no black hole and no border
    cols = lambda f: np.nonzero(f[48, :, 0] > 0.9)[0]               # noqa: E731
    near_shift = cols(first).mean() - cols(last).mean()
    assert near_shift > W * 0.06 * window[2] * 0.8                     # the near patch moved left by about truck
    assert abs(near_shift) > 3 * abs(motion.Camera(W, H, truck=0.06).moved(32.0, 48.0, motion.FAR_Z, 1.0)[0] - 32)


def test_the_nearest_splat_wins():
    img = np.zeros((H, W, 3), np.float32)
    img[:, : W // 3] = 1.0
    z = motion.distance(step_depth(img))
    cam = motion.Camera(W, H, truck=-0.05)                     # near things move right, over the far ones
    frame = motion.Warper(img, z, cam, (0.0, 0.0, 1.0)).frame(1.0)
    edge = np.nonzero(frame[H // 2, :, 0] > 0.5)[0].max()
    assert edge >= W // 3 + 2                                  # the near edge covers far pixels that land there too


# ------------------------------------------------------------------ models
def pinned(monkeypatch, name, payload: bytes, member: bytes | None = None):
    spec = motion.MODELS[name]
    fake = dataclasses.replace(spec, url="https://example.invalid/m.bin" if member is None else
                               "https://example.invalid/m.7z", size=len(payload),
                               sha256=hashlib.sha256(payload).hexdigest(),
                               member_size=len(member) if member else 0,
                               member_sha256=hashlib.sha256(member).hexdigest() if member else "")
    monkeypatch.setitem(motion.MODELS, name, fake)
    return fake


def serving(data: bytes, seen: list):
    def download(url, dest, say):
        seen.append(url)
        dest.write_bytes(data)
    return download


def test_model_fetch_checks_size_and_hash(tmp_path, monkeypatch):
    pinned(monkeypatch, "depth", b"the real model")
    seen, said = [], []
    with pytest.raises(ProviderError) as bad:
        motion.ensure_model(tmp_path, "depth", serving(b"the evil model", seen), said.append)
    assert "is not the pinned" in str(bad.value) and "SHA-256" in str(bad.value)
    assert "save it as" in str(bad.value) and not list((tmp_path / "models").iterdir())
    path = motion.ensure_model(tmp_path, "depth", serving(b"the real model", seen), said.append)
    assert path.read_bytes() == b"the real model" and any("fetching" in s for s in said)
    assert motion.ensure_model(tmp_path, "depth", serving(b"", seen), said.append) == path and len(seen) == 2


def test_model_fetch_unpacks_only_the_one_file(tmp_path, monkeypatch):
    py7zr = pytest.importorskip("py7zr")
    inner = b"onnx bytes"
    (tmp_path / "src" / "rife_v2").mkdir(parents=True)
    (tmp_path / "src" / "rife_v2" / "rife_v4.25.onnx").write_bytes(inner)
    (tmp_path / "src" / "other.onnx").write_bytes(b"x")
    archive = tmp_path / "a.7z"
    with py7zr.SevenZipFile(archive, "w") as z:
        z.writeall(tmp_path / "src", arcname="")
    pinned(monkeypatch, "rife", archive.read_bytes(), inner)
    cache = tmp_path / "cache"
    path = motion.ensure_model(cache, "rife", serving(archive.read_bytes(), []), lambda s: None)
    assert path.read_bytes() == inner
    assert sorted(p.name for p in (cache / "models").iterdir()) == ["rife-v4.25.onnx", "rife-v4.25.onnx.sha256"]


def test_model_fetch_failure_says_where_to_put_the_file(tmp_path, monkeypatch):
    spec = pinned(monkeypatch, "depth", b"m")

    def offline(url, dest, say):
        raise OSError("no route to host")
    with pytest.raises(ProviderError) as bad:
        motion.ensure_model(tmp_path, "depth", offline, lambda s: None)
    msg = str(bad.value)
    assert spec.url in msg and "no route to host" in msg and str(tmp_path / "models" / spec.file) in msg


def test_two_fetches_at_once_both_succeed(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 256
    pinned(monkeypatch, "depth", payload)

    def slow(url, dest, say):
        with open(dest, "wb") as fh:
            for i in range(0, len(payload), 4096):
                fh.write(payload[i:i + 4096])
                fh.flush()
                time.sleep(0.005)
    for run in range(3):
        cache, got, errors = tmp_path / str(run), [], []

        def fetch():
            try:
                got.append(motion.ensure_model(cache, "depth", slow, lambda s: None))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=fetch) for _ in range(2)]
        threads[0].start()
        time.sleep(0.03)
        threads[1].start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert len(got) == 2 and got[0] == got[1] and got[0].read_bytes() == payload
        assert sorted(p.name for p in (cache / "models").iterdir()) == [got[0].name, got[0].name + ".sha256"]


def test_a_fetch_uses_the_model_another_call_put_in_place(tmp_path, monkeypatch):
    payload = b"the real model"
    spec = pinned(monkeypatch, "depth", payload)
    target = tmp_path / "models" / spec.file
    real_replace = os.replace

    def download(url, dest, say):
        dest.write_bytes(payload)
        target.write_bytes(payload)                 # another process finished first and holds it open

    def busy(src, dst):
        if Path(dst) == target:
            raise PermissionError(32, "in use")
        real_replace(src, dst)
    monkeypatch.setattr(motion.os, "replace", busy)
    assert motion.ensure_model(tmp_path, "depth", download, lambda s: None) == target
    assert sorted(p.name for p in target.parent.iterdir()) == [spec.file, spec.file + ".sha256"]


# ------------------------------------------------------------------ colour, transparency, unreadable pictures
def test_clips_are_tagged_bt709_and_flat_colours_round_trip(tmp_path):
    colours = [(230, 26, 26), (26, 204, 51), (242, 191, 51), (128, 128, 128)]
    frame = np.zeros((64, 64 * len(colours), 3), np.float32)
    for i, c in enumerate(colours):
        frame[:, i * 64:(i + 1) * 64] = np.array(c, np.float32) / 255
    out = tmp_path / "flat.mp4"
    motion._encode(out, frame.shape[1], frame.shape[0], 10, [frame, frame])
    tags = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=color_space,color_primaries,color_transfer,color_range", "-of", "json", str(out)],
        capture_output=True, text=True, check=True).stdout)["streams"][0]
    assert tags == {"color_space": "bt709", "color_primaries": "bt709", "color_transfer": "bt709",
                    "color_range": "tv"}
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-frames:v", "1", "-vf",
                          "scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    got = np.frombuffer(raw, np.uint8).reshape(64, -1, 3).astype(int)
    for i, c in enumerate(colours):
        assert np.abs(got[32, i * 64 + 32] - c).max() <= 3, (c, got[32, i * 64 + 32])


def add_picture(project: Path, name: str, rgba) -> None:
    Image.fromarray(rgba).save(project / "assets" / f"{name}.png")
    data = json.loads((project / "project.json").read_text(encoding="utf-8"))
    data["assets"][name] = {"path": f"assets/{name}.png", "kind": "image"}
    (project / "project.json").write_text(json.dumps(data), encoding="utf-8")


def test_both_tools_refuse_transparent_pictures_and_take_opaque_rgba(ws):
    cut = np.full((H, W, 4), 255, np.uint8)
    cut[:10, :10, 3] = 0
    add_picture(ws, "cut", cut)
    add_picture(ws, "solid", np.full((H, W, 4), 200, np.uint8) | np.array([0, 0, 0, 255], np.uint8))
    for r in (tools.tween(str(ws), "act", ["a", "cut"], [0, 1]),
              tools.parallax(str(ws), "cam", "cut", 1, {"dolly": 0.05})):
        assert not r.ok and "'cut' has transparent pixels" in r and "without cutout" in r and "Photo" in r, r
        assert r.count(". ") == 0, r
    text, err = motion.tween(ws, "act", ["a", "solid"], [0, 0.2], fps=10, interpolate=lambda a, b, t: a)
    assert not err, text


def test_unreadable_pictures_give_a_sentence(ws):
    (ws / "assets" / "b.png").write_bytes(b"not a picture")
    for r in (tools.tween(str(ws), "act", ["a", "b"], [0, 1]), tools.tween(str(ws), "act", ["b", "a"], [0, 1]),
              tools.parallax(str(ws), "cam", "b", 1, {"dolly": 0.05})):
        assert not r.ok and "'b'" in r and "cannot be read" in r and "Error" not in r, r


def test_tool_docs_say_no_transparency_and_where_the_models_go():
    for fn in (tools.tween, tools.parallax):
        doc = " ".join(fn.__doc__.split())
        assert "no transparency" in doc and "<workspace>/.cache/models" in doc, doc
        assert "RIFE about 23 MB" in doc and "Depth Anything V2 Small about 99 MB" in doc, doc


# ------------------------------------------------------------------ the real models
REAL = os.environ.get("REELSMITH_TEST_MODELS", "")


@pytest.mark.skipif(not (REAL and all((Path(REAL) / motion.MODELS[n].file).is_file() for n in motion.MODELS)),
                    reason="REELSMITH_TEST_MODELS does not name a folder holding both models")
def test_real_models_run_each_tool_once(ws):
    models = ws.parent.parent / ".cache" / "models"
    models.mkdir(parents=True)
    for n in motion.MODELS:
        shutil.copyfile(Path(REAL) / motion.MODELS[n].file, models / motion.MODELS[n].file)
    r = tools.tween(str(ws), "act", ["a", "b"], [0, 0.3], fps=10)
    assert r.ok and "4 frames" in r, r
    r = tools.parallax(str(ws), "cam", "a", 0.5, {"dolly": 0.05}, fps=10)
    assert r.ok and "5 frames" in r and (ws / "assets" / "a.depth.png").is_file(), r


def test_a_clip_keeps_what_a_plate_needs_to_cover_the_canvas():
    class Ctx:
        pass
    from reelsmith import motion as M
    sizes = {}
    for canvas in ((1080, 1920), (1920, 1080)):
        prof = type("P", (), {"width": canvas[0], "height": canvas[1]})()
        orig = M.project_profile
        M.project_profile = lambda ctx, prof=prof: prof
        try:
            sizes[canvas] = [M._out_size(Ctx(), w, h) for w, h in ((1620, 1080), (1080, 1920), (4096, 4096), (601, 401))]
        finally:
            M.project_profile = orig
    # a wide plate on a tall canvas keeps its own size: a pan runs across its width at full height
    assert sizes[(1080, 1920)] == [(1620, 1080), (1080, 1920), (1920, 1920), (600, 400)]
    assert sizes[(1920, 1080)] == [(1620, 1080), (1080, 1920), (1920, 1920), (600, 400)]
