"""Editing footage on the timeline: markers and source-time anchors, ripple_delete, insert_gap, trim_clip and split on
video/audio clips, transitions, volume keyframes and ducking, captions from a transcript."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reelsmith import document as D
from reelsmith import ops
from reelsmith import resolve as R
from reelsmith import timeexpr as T
from reelsmith.timeexpr import ClipTiming, Schedule, TimeError, TimeExpr

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg/ffprobe not on PATH")
_MEDIA: dict = {}


def _make(tmp_path_factory, name: str) -> bytes:
    if name not in _MEDIA:
        out = tmp_path_factory.mktemp("tl") / name
        args = {"v.mp4": ["-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=12", "-f", "lavfi", "-i",
                          "sine=f=330:d=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
                "m.wav": ["-f", "lavfi", "-i", "sine=f=220:d=12"]}[name]
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, str(out)], check=True,
                       capture_output=True)
        _MEDIA[name] = out.read_bytes()
    return _MEDIA[name]


BASE = {
    "version": 2, "duration": 9, "markers": {"hit": 4.5, "late": "clip:c2+1"},
    "assets": {"v": {"path": "assets/v.mp4", "kind": "video"}, "m": {"path": "assets/m.wav", "kind": "audio"}},
    "tracks": [
        {"id": "v1", "kind": "visual", "clips": [
            {"id": "c1", "type": "video", "asset": "v", "start": 0, "dur": 6, "trim_in": 2, "volume": 1},
            {"id": "c2", "type": "video", "asset": "v", "start": 6, "end": 9, "rate": 2}]},
        {"id": "t1", "kind": "visual", "clips": [
            {"id": "note", "type": "text", "text": "hi", "start": 1, "end": 2},
            {"id": "title", "type": "text", "text": "two", "start": "clip:c2", "end": "clip:c2.end",
             "keyframes": {"opacity": [{"t": 0, "v": 0}, {"t": "clip:c2+0.5", "v": 1}]}}]},
        {"id": "a1", "kind": "audio", "clips": [
            {"id": "m1", "type": "audio", "asset": "m", "start": 0, "end": 9, "fade_in": 0.5, "fade_out": 1}]},
        {"id": "cap", "kind": "captions", "items": [{"start": 0.5, "end": 1.5, "text": "a"},
                                                   {"start": 3, "end": 4, "text": "b"},
                                                   {"start": 7, "end": 8, "text": "c"}]}]}


@pytest.fixture
def cut(tmp_path, tmp_path_factory, monkeypatch):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not on PATH")
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "cut"
    (p / "assets").mkdir(parents=True)
    for name in ("v.mp4", "m.wav"):
        (p / "assets" / name).write_bytes(_make(tmp_path_factory, name))
    write(p, BASE)
    return p


def raw(p):
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


def write(p, data):
    (p / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def clip(data, cid):
    return next(c for t in data["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def track(data, tid):
    return next(t for t in data["tracks"] if t["id"] == tid)


def spans(p) -> dict:
    doc = D.load(p)
    voice, _ = D.load_voice(p, doc.voice)
    sched = D.schedule(doc, voice)
    return {c.id: tuple(round(x, 3) for x in sched.span(c.id)) for _, c in D.clips_of(doc)}


def ok(p, *batch):
    good, issues, summary = ops.apply(p, list(batch))
    assert good, [str(i) for i in issues] + [summary]
    return summary


def refused(p, *batch):
    good, issues, summary = ops.apply(p, list(batch))
    assert not good
    return " ".join(str(i) for i in issues)


def errors(p):
    return [str(i) for i in D.check_data(p, raw(p))[1] if i.level == "error"]


# ------------------------------------------------------------------ the Time grammar
@pytest.mark.parametrize("value, expr", [
    ("mark:intro", TimeExpr("mark", "intro", False, 0.0)),
    ("mark:a-b+1", TimeExpr("mark", "a-b", False, 1.0)),
    ("Mark:x - 0.5", TimeExpr("mark", "x", False, -0.5)),
    ("src:c1@12.5", TimeExpr("src", "c1", False, 0.0, 12.5)),
    ("src:c1@12.5-0.2", TimeExpr("src", "c1", False, -0.2, 12.5)),
    ("src:a-b@3", TimeExpr("src", "a-b", False, 0.0, 3.0)),
    ("SRC:v@.5", TimeExpr("src", "v", False, 0.0, 0.5)),
])
def test_parse_marks_and_source_seconds(value, expr):
    assert T.parse(value) == expr
    assert T.parse(str(expr)) == expr


@pytest.mark.parametrize("value, hint", [("src:c1", "src:CLIP@SECONDS"), ("src:@3", "src:CLIP@SECONDS"),
                                         ("mark:", "mark:NAME"), ("src:c1@-2", "src:CLIP@SECONDS")])
def test_parse_explains_bad_marks_and_sources(value, hint):
    with pytest.raises(TimeError, match="cannot read"):
        T.parse(value)
    assert hint in T.check(value)


def test_markers_and_source_seconds_resolve_with_cycles_caught():
    clips = {"v": ClipTiming(10, 20, kind="video", trim_in=4, rate=2), "t": ClipTiming(0, 1, kind="text"),
             "lp": ClipTiming(0, 5, kind="audio", loop=True), "self": ClipTiming("src:self@3", dur=2, kind="video")}
    s = Schedule([], clips, markers={"a": "src:v@8", "b": "mark:a+1", "x": "mark:y", "y": "mark:x"})
    assert T.resolve("src:v@8", s) == 12              # 10 + (8 - 4) / 2
    assert T.resolve("src:v@4+0.5", s) == 10.5
    assert T.resolve("mark:b", s) == 13
    with pytest.raises(T.CycleError, match="mark:x -> mark:y -> mark:x"):
        T.resolve("mark:x", s)
    with pytest.raises(T.CycleError):
        s.start("self")
    with pytest.raises(TimeError, match="text clip"):
        T.resolve("src:t@0", s)
    with pytest.raises(TimeError, match="loops"):
        T.resolve("src:lp@1", s)
    with pytest.raises(TimeError, match="before clip v's in point"):
        T.resolve("src:v@3", s)
    with pytest.raises(TimeError, match="no marker 'nope'"):
        T.resolve("mark:nope", s)


def test_document_checks_markers_and_source_times(cut):
    data = raw(cut)
    data["markers"].update({"bad name": 1, "x-1": 2, "gone": "src:nope@1"})
    clip(data, "note")["end"] = "src:c1@11"                 # c1 shows source 2-8
    issues = [str(i) for i in D.check_data(cut, data)[1]]
    assert any("markers.bad name: marker names" in i for i in issues)
    assert any("markers.x-1" in i and "time offset" in i for i in issues)
    assert any("[error] markers.gone" in i and "no clip 'nope'" in i for i in issues)
    assert any("[warning] clip note.end: src:c1@11: source second 11 is after clip c1 ends" in i for i in issues)


def test_time_of_reads_marks_and_source_seconds(cut):
    assert R.time_of(cut, "mark:late") == 7
    assert R.time_of(cut, "src:c2@2") == 7                  # rate 2: source 2 s is 1 s in
    assert R.time_of(cut, "src:c1@5+0.25") == 3.25


# ------------------------------------------------------------------ ripple_delete
def test_ripple_delete_splits_removes_and_closes_the_gap(cut):
    s = ok(cut, {"op": "ripple_delete", "start": 3, "end": 4})
    assert "ripple-deleted 3.00-4.00 s (1.00 s)" in s and "removed c1_2, m1_2" in s and "split c1, m1" in s
    d = raw(cut)
    assert spans(cut) == {"c1": (0, 3), "c1_3": (3, 5), "c2": (5, 8), "note": (1, 2), "title": (5, 8),
                          "m1": (0, 3), "m1_3": (3, 8)}
    assert clip(d, "c1_3")["trim_in"] == 6 and clip(d, "m1_3")["trim_in"] == 4      # source moved past the cut
    assert clip(d, "title")["start"] == "clip:c2" and clip(d, "title")["end"] == "clip:c2.end"     # still true
    assert clip(d, "title")["keyframes"]["opacity"][1]["t"] == "clip:c2+0.5"
    assert d["markers"] == {"hit": 3.5, "late": "clip:c2+1"} and d["duration"] == 8
    assert [(i["start"], i["end"], i["text"]) for i in track(d, "cap")["items"]] == [(0.5, 1.5, "a"), (6, 7, "c")]
    assert "fade_out" not in clip(d, "m1") and clip(d, "m1_3")["fade_out"] == 1 and "fade_in" not in clip(d, "m1_3")
    assert errors(cut) == []
    ok_, text = ops.undo(cut)
    assert ok_ and raw(cut) == json.loads(json.dumps(BASE))


def test_ripple_delete_from_source_seconds_and_back_to_front(cut):
    # the jump-cut recipe: silences at source 4-5 and 6.5-7 of c1 (film 2-3 and 4.5-5), cut from the last back
    ok(cut, {"op": "ripple_delete", "start": "src:c1@6.5", "end": "src:c1@7"},
       {"op": "ripple_delete", "start": "src:c1@4", "end": "src:c1@5"})
    sp = spans(cut)
    assert sp["c1"] == (0, 2) and sp["c2"] == (4.5, 7.5)
    d = raw(cut)
    pieces = sorted((v, k) for k, v in sp.items() if k.startswith("c1"))
    assert [clip(d, k).get("trim_in") for _, k in pieces] == [2, 5, 7]
    assert errors(cut) == []


def test_ripple_delete_on_some_tracks_leaves_the_rest_in_place(cut):
    s = ok(cut, {"op": "ripple_delete", "start": 3, "end": 4, "tracks": ["v1"]})
    assert "on v1" in s
    sp = spans(cut)
    assert sp["c2"] == (5, 8) and sp["title"] == (6, 9) and sp["m1"] == (0, 9)
    d = raw(cut)
    assert clip(d, "title")["start"] == 6 and clip(d, "title")["end"] == 9        # its anchor moved: pinned
    assert clip(d, "title")["keyframes"]["opacity"][1]["t"] == 0.5                 # still 0.5 s into the title
    assert errors(cut) == []
    assert "no track 'zz'" in refused(cut, {"op": "ripple_delete", "start": 1, "end": 2, "tracks": ["zz"]})
    assert "at least a frame after" in refused(cut, {"op": "ripple_delete", "start": 3, "end": 3})


def test_ripple_delete_with_a_voice_says_the_narration_stays(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    demo = tmp_path / "demo"
    shutil.copytree(Path(__file__).parent / "fixtures" / "demo", demo, ignore=shutil.ignore_patterns("build"))
    s = ok(demo, {"op": "ripple_delete", "start": "line:2", "end": "line:3"})
    assert "the narration is not cut" in s
    assert errors(demo) == []


# ------------------------------------------------------------------ insert_gap
def test_insert_gap_splits_and_pushes_later_clips(cut):
    s = ok(cut, {"op": "insert_gap", "at": 3, "dur": 1, "tracks": ["v1"]})
    assert "inserted 1.00 s at 3.00 s on v1" in s
    sp = spans(cut)
    assert sp["c1"] == (0, 3) and sp["c1_2"] == (4, 7) and sp["c2"] == (7, 10)
    d = raw(cut)
    assert clip(d, "c1_2")["trim_in"] == 5
    assert d["markers"] == {"hit": 5.5, "late": "clip:c2+1"}       # markers follow the picture
    assert sp["title"] == (6, 9)                                   # t1 untouched: pinned where it was
    assert errors(cut) == []


def test_insert_gap_moves_a_clip_starting_at_the_point_but_not_one_ending_there(cut):
    ok(cut, {"op": "insert_gap", "at": 6, "dur": 0.5})
    sp = spans(cut)
    assert sp["c1"] == (0, 6) and sp["c2"] == (6.5, 9.5) and sp["title"] == (6.5, 9.5)
    assert raw(cut)["duration"] == 9.5
    assert "dur is under one frame" in refused(cut, {"op": "insert_gap", "at": 1, "dur": 0.001})


# ------------------------------------------------------------------ trim_clip
def test_trim_clip_source_in_and_out_keep_the_picture_in_place(cut):
    s = ok(cut, {"op": "trim_clip", "id": "c1", "in": 3, "out": 7})
    assert "trimmed clip c1 to 1.00-5.00 s (source 3.00-7.00 s)" in s
    d = raw(cut)
    assert clip(d, "c1")["trim_in"] == 3 and spans(cut)["c1"] == (1, 5) and spans(cut)["c2"] == (6, 9)


def test_trim_clip_with_ripple_pulls_the_rest_of_the_track(cut):
    s = ok(cut, {"op": "trim_clip", "id": "c1", "in": 3, "ripple": True})
    assert "1 later clip(s) on v1 moved -1.00 s" in s
    sp = spans(cut)
    assert sp["c1"] == (0, 5) and sp["c2"] == (5, 8) and sp["title"] == (5, 8)      # title follows c2's anchor
    assert raw(cut)["markers"]["hit"] == 4.5                                         # markers stay
    ok(cut, {"op": "trim_clip", "id": "c2", "out": 4, "ripple": True})                # rate 2: 2 s of film
    assert spans(cut)["c2"] == (5, 7)


def test_trim_clip_extends_the_head_and_refuses_past_the_source(cut):
    ok(cut, {"op": "trim_clip", "id": "c1", "in": 0.5, "ripple": True})
    d = raw(cut)
    assert clip(d, "c1")["trim_in"] == 0.5 and spans(cut)["c1"] == (0, 7.5)
    assert "past the end of the source" in refused(cut, {"op": "trim_clip", "id": "c1", "out": 30})
    assert "must come after in" in refused(cut, {"op": "trim_clip", "id": "c1", "in": 5, "out": 4})
    assert "before the film starts" in refused(cut, {"op": "trim_clip", "id": "c1", "in": 0})


def test_trim_clip_on_a_text_clip_takes_times(cut):
    ok(cut, {"op": "trim_clip", "id": "note", "in": 1.5, "out": "clip:c1.end-1"})
    assert spans(cut)["note"] == (1.5, 5)
    assert "give in and/or out" in refused(cut, {"op": "trim_clip", "id": "note"})


def test_trim_clip_head_cut_keeps_keyframes_on_their_frames(cut):
    data = raw(cut)
    clip(data, "c1")["keyframes"] = {"zoom": [{"t": 0, "v": 1}, {"t": 4, "v": 2}]}
    write(cut, data)
    ok(cut, {"op": "trim_clip", "id": "c1", "in": 4})               # 2 s off the head, the picture stays put
    zoom = clip(raw(cut), "c1")["keyframes"]["zoom"]
    assert zoom[0] == {"t": 0, "v": 1.5} and zoom[-1]["t"] == 2 and zoom[-1]["v"] == 2


# ------------------------------------------------------------------ split on media clips
def test_split_video_with_rate_and_audio_fades(cut):
    ok(cut, {"op": "split_clip", "id": "c2", "at": 7, "new_id": "c2b"},
       {"op": "split_clip", "id": "m1", "at": 4, "new_id": "m1b"})
    d = raw(cut)
    assert clip(d, "c2b")["trim_in"] == 2 and clip(d, "c2b")["rate"] == 2           # 1 film s at rate 2
    assert clip(d, "m1")["fade_in"] == 0.5 and "fade_out" not in clip(d, "m1")
    assert clip(d, "m1b")["fade_out"] == 1 and "fade_in" not in clip(d, "m1b")
    assert errors(cut) == []


def test_split_moves_source_anchors_past_the_cut_to_the_new_clip(cut):
    data = raw(cut)
    data["markers"] = {"early": "src:c1@3", "later": "src:c1@7"}
    write(cut, data)
    ok(cut, {"op": "split_clip", "id": "c1", "at": 3, "new_id": "c1b"})
    assert raw(cut)["markers"] == {"early": "src:c1@3", "later": "src:c1b@7"}
    assert R.time_of(cut, "mark:later") == 5
    ok(cut, {"op": "update_clip", "id": "c1b", "set": {"id": "tail"}})
    assert raw(cut)["markers"]["later"] == "src:tail@7"


def test_audio_clips_take_volume_keyframes_only(cut):
    ok(cut, {"op": "set_keyframes", "id": "m1", "prop": "volume", "frames": [{"t": 0, "v": 1}, {"t": 2, "v": 0.2}]})
    assert clip(raw(cut), "m1")["keyframes"]["volume"][1]["v"] == 0.2
    assert "except volume" in refused(cut, {"op": "set_keyframes", "id": "m1", "prop": "opacity",
                                            "frames": [{"t": 0, "v": 1}]})
    assert "volume keyframes are for video and audio" in refused(
        cut, {"op": "set_keyframes", "id": "note", "prop": "volume", "frames": [{"t": 0, "v": 1}]})


# ------------------------------------------------------------------ transitions
def rclip(resolved, cid):
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def raudio(resolved, cid):
    return next(a for a in resolved["audio"] if a["id"] == cid)


def test_a_transition_lets_a_clip_overlap_the_one_before_by_its_dur(cut):
    ok(cut, {"op": "move_clip", "id": "c2", "start": "clip:c1.end-0.5"},
       {"op": "update_clip", "id": "c2", "set": {"transition": {"type": "crossfade", "dur": 0.5}}})
    r = R.resolve(cut)
    c1, c2 = rclip(r, "c1"), rclip(r, "c2")
    assert c2["transition"] == {"type": "crossfade", "dur": 15, "from": "c1"} and c2["transitionOut"] is None
    assert c1["transitionOut"] == {"type": "crossfade", "dur": 15, "at": 165, "to": "c2"}
    assert c1["content"]["fadeOut"] == 15 and "fadeIn" not in c2["content"]        # c2 is muted: only c1 fades
    assert rclip(r, "note")["transition"] is None
    rows = refused(cut, {"op": "move_clip", "id": "c2", "start": 5})
    assert "overlap by 1.00 s, more than c2's transition (0.5 s)" in rows
    rows = refused(cut, {"op": "update_clip", "id": "c2", "set": {"transition": None}})
    assert "must not overlap" in rows
    rows = refused(cut, {"op": "update_clip", "id": "note", "set": {"transition": {"type": "zoom", "dur": 2}}})
    assert "longer than the clip" in rows


def test_every_transition_type_resolves_and_the_first_clip_comes_from_nothing(cut):
    for kind in D.CUTS:
        ok(cut, {"op": "update_clip", "id": "c1", "set": {"transition": {"type": kind, "dur": 0.4}}})
        assert rclip(R.resolve(cut), "c1")["transition"] == {"type": kind, "dur": 12, "from": None}
    rows = refused(cut, {"op": "update_clip", "id": "c1", "set": {"transition": {"type": "spin", "dur": 1}}})
    assert "transition.type" in rows


def test_audio_clips_crossfade_through_their_fades(cut):
    ok(cut, {"op": "split_clip", "id": "m1", "at": 4, "new_id": "m2"})
    ok(cut, {"op": "move_clip", "id": "m2", "start": 3},
       {"op": "update_clip", "id": "m2", "set": {"transition": {"type": "crossfade", "dur": 1}}})
    r = R.resolve(cut)
    m1, m2 = raudio(r, "m1"), raudio(r, "m2")
    assert m1["fadeOut"] == 30 and m2["fadeIn"] == 30 and m1["fadeIn"] == 15
    rows = refused(cut, {"op": "update_clip", "id": "m2", "set": {"transition": {"type": "wipe_left", "dur": 1}}})
    assert "audio clips crossfade only" in rows


def test_layout_checks_skip_frames_inside_a_transition(cut):
    from reelsmith import checks
    ok(cut, {"op": "move_clip", "id": "c2", "start": "clip:c1.end-0.5"},
       {"op": "update_clip", "id": "c2", "set": {"transition": {"type": "slide_left", "dur": 0.5}}})
    windows = checks.transition_windows(R.resolve(cut))
    assert windows["c2"] == [(165, 180)] and windows["c1"] == [(165, 180)]


# ------------------------------------------------------------------ volume keyframes and ducking
def test_volume_keyframes_become_sound_curves_not_picture_keyframes(cut):
    ok(cut, {"op": "set_keyframes", "id": "c1", "prop": "volume", "frames": [{"t": 0, "v": 0}, {"t": 1, "v": 1}]},
       {"op": "set_keyframes", "id": "m1", "prop": "volume",
        "frames": [{"t": 0, "v": 1}, {"t": "clip:c2", "v": 0.2, "ease": "inOut"}]})
    r = R.resolve(cut)
    assert "volume" not in rclip(r, "c1")["keyframes"]
    assert rclip(r, "c1")["content"]["volumeKeys"] == [{"f": 0, "v": 0, "ease": "linear"},
                                                       {"f": 30, "v": 1, "ease": "linear"}]
    assert raudio(r, "m1")["volumeKeys"][1] == {"f": 180, "v": 0.2, "ease": "inOut"}
    rows = refused(cut, {"op": "set_keyframes", "id": "m1", "prop": "volume", "frames": [{"t": 0, "v": -1}]})
    assert "0 (silent) or more" in rows


def test_a_music_bed_ducks_under_a_track_while_it_sounds(cut):
    ok(cut, {"op": "update_clip", "id": "m1", "set": {"duck": {"under": "v1", "to": 0.2, "fade": 0.5}}})
    duck = raudio(R.resolve(cut), "m1")["duck"]
    assert duck == [{"start": 0, "end": 180, "level": 0.2, "fade": 15}]          # c1 sounds 0-6 s; c2 is muted
    ok(cut, {"op": "update_clip", "id": "c2", "set": {"volume": 0.5}})
    duck = raudio(R.resolve(cut), "m1")["duck"]
    assert duck == [{"start": 0, "end": 270, "level": 0.2, "fade": 15}]          # touching ranges merge
    assert "no track 'zz'" in refused(cut, {"op": "update_clip", "id": "m1", "set": {"duck": {"under": "zz"}}})
    assert "its own track" in refused(cut, {"op": "update_clip", "id": "m1", "set": {"duck": {"under": "a1"}}})
    assert "has none" in refused(cut, {"op": "update_clip", "id": "m1", "set": {"duck": {"under": "voice"}}})


def test_ducking_under_the_voice_follows_the_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    demo = tmp_path / "demo"
    shutil.copytree(Path(__file__).parent / "fixtures" / "demo", demo, ignore=shutil.ignore_patterns("build"))
    ok(demo, {"op": "update_clip", "id": "bed1", "set": {"dur": 21, "duck": {"under": "voice", "fade": 0.1}}})
    duck = raudio(R.resolve(demo), "bed1")["duck"]
    assert len(duck) == 7 and duck[1] == {"start": 103, "end": 162, "level": 0.25, "fade": 3}   # one per line
    ok(demo, {"op": "update_clip", "id": "bed1", "set": {"duck": {"under": "voice", "fade": 0.15}}})
    duck = raudio(R.resolve(demo), "bed1")["duck"]
    assert duck == [{"start": 0, "end": 630, "level": 0.25, "fade": 5}]         # gaps under 2 x fade are bridged


# ------------------------------------------------------------------ captions from a transcript
def transcript(p, words, asset="v"):
    (p / "assets" / f"{asset}.transcript.json").write_text(json.dumps({
        "version": 1, "asset": asset, "words": [{"word": w, "start": a, "end": b} for w, a, b in words]}),
        encoding="utf-8")
    data = raw(p)
    data["assets"][asset]["transcript"] = f"assets/{asset}.transcript.json"
    write(p, data)


WORDS = [("cut", 1.0, 1.4), ("Hello", 2.5, 2.9), ("there,", 3.0, 3.4), ("my", 3.5, 3.7), ("friend.", 3.8, 4.2),
         ("This", 6.0, 6.3), ("is", 6.4, 6.5), ("footage", 6.6, 7.2)]


def caption_track(p, **extra):
    data = raw(p)
    track(data, "cap").pop("items")
    track(data, "cap").update({"source": "clip:c1", "max_chars": 14, **extra})
    write(p, data)


def caption_texts(p):
    items = next(t for t in R.resolve(p)["tracks"] if t["id"] == "cap")["items"]
    return items, ["".join(r["text"] for r in it["runs"]) for it in items]


def test_captions_follow_the_transcript_through_the_clip(cut):
    transcript(cut, WORDS)
    caption_track(cut, emphasis=["friend"])
    assert errors(cut) == []
    items, texts = caption_texts(cut)
    assert texts == ["Hello there,", "my friend.", "This is", "footage"]      # "cut" is trimmed away (trim_in 2)
    assert (items[0]["from"], items[0]["to"]) == (15, 45)                    # 0.5 s; held until the next phrase
    assert items[2]["from"] == 120 and items[-1]["to"] <= 180                # within c1 (0-6 s)
    assert any(r["accent"] and r["text"] == "friend" for r in items[1]["runs"])


def test_captions_from_a_transcript_survive_a_ripple_cut(cut):
    transcript(cut, WORDS)
    caption_track(cut)
    ok(cut, {"op": "ripple_delete", "start": "src:c1@4.4", "end": "src:c1@5.8"})
    items, texts = caption_texts(cut)
    assert texts[-2:] == ["This is", "footage"]                               # through the piece after the cut
    assert items[-2]["from"] == round((6.0 - 2 - 1.4) * 30)


def test_captions_from_a_transcript_are_checked(cut):
    caption_track(cut)
    assert any("has no transcript: transcribe v first" in e for e in errors(cut))
    transcript(cut, WORDS)
    (cut / "assets" / "v.transcript.json").unlink()
    issues = [str(i) for i in D.check_data(cut, raw(cut))[1]]
    assert any("[error] track cap.source" in i and "missing or unreadable" in i for i in issues)
    assert any("[warning] assets.v.transcript" in i for i in issues)
    data = raw(cut)
    track(data, "cap")["source"] = "clip:nope"
    assert any("no clip 'nope'" in str(i) for i in D.check_data(cut, data)[1])
    track(data, "cap")["source"] = "words"
    assert any('"voice" or "clip:<id>"' in str(i) for i in D.check_data(cut, data)[1])


def test_join_words_spaces_latin_and_not_cjk():
    assert R.join_words(["Hello", "there", ",", "you"]) == "Hello there, you"
    assert R.join_words(["你好", "世界", "。"]) == "你好世界。"
    assert R.join_words(["iPhone", "17", "发布"]) == "iPhone 17发布"


def test_transcript_phrases_break_at_pauses_sentences_and_length():
    def w(t, a, b):
        return {"word": t, "a": a, "b": b}
    out = R.transcript_phrases([w("one", 0, 0.2), w("two", 0.3, 0.5), w("three", 1.5, 1.8), w("four.", 1.9, 2.1),
                                w("five", 2.2, 2.4), w("sixsix", 2.5, 2.7)], 12)
    assert [R.join_words([x["word"] for x in ph]) for ph in out] == ["one two", "three four.", "five sixsix"]


# ------------------------------------------------------------------ describe
def test_describe_shows_markers_transcripts_transitions_and_sound(cut):
    transcript(cut, WORDS)
    caption_track(cut)
    ok(cut, {"op": "move_clip", "id": "c2", "start": "clip:c1.end-0.5"},
       {"op": "update_clip", "id": "c2", "set": {"transition": {"type": "dip_black", "dur": 0.5}}},
       {"op": "set_keyframes", "id": "m1", "prop": "volume", "frames": [{"t": 0, "v": 1}, {"t": 2, "v": 0.3}]},
       {"op": "update_clip", "id": "m1", "set": {"duck": {"under": "v1"}}})
    text = R.describe(cut)
    assert 'markers ("mark:NAME"): hit 4.50, late 6.50 (clip:c2+1)' in text
    assert "transcript 8 words" in text and "transition dip_black 0.5s" in text
    assert "vol kf(2)" in text and "ducks under v1 to 0.25" in text
    assert "from the transcript of v through c1" in text
    at = R.describe(cut, at=1)
    assert "now: volume" in at and 'caption "' in at
