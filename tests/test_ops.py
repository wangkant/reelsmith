import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

from reelsmith import ops
from reelsmith import resolve as R
from reelsmith import tools

FIXTURE = Path(__file__).parent / "fixtures" / "demo"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "demo"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    return p


def raw(p):
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


def text_of(p):
    return (p / "project.json").read_bytes()


def clip(data, cid):
    return next(c for t in data["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def track(data, tid):
    return next(t for t in data["tracks"] if t["id"] == tid)


def ok(p, *batch):
    good, issues, summary = ops.apply(p, list(batch))
    assert good, [str(i) for i in issues] + [summary]
    return summary


def refused(p, *batch):
    before = text_of(p)
    snaps = ops.snapshots(p)
    good, issues, summary = ops.apply(p, list(batch))
    assert not good and summary.startswith("nothing changed")
    assert text_of(p) == before and ops.snapshots(p) == snaps          # untouched, no snapshot
    return [str(i) for i in issues]


# ------------------------------------------------------------------ tracks
def test_add_track_positions(demo):
    assert ok(demo, {"op": "add_track", "track": {"id": "top", "kind": "visual"}}) == "added visual track top on top"
    assert raw(demo)["tracks"][-1] == {"id": "top", "kind": "visual", "clips": []}
    ok(demo, {"op": "add_track", "track": {"id": "under", "kind": "visual"}, "index": 0})
    assert raw(demo)["tracks"][0]["id"] == "under"
    assert "taken" in refused(demo, {"op": "add_track", "track": {"id": "bg", "kind": "visual"}})[0]
    assert "position 0-8" in refused(demo, {"op": "add_track", "track": {"id": "x", "kind": "visual"}, "index": 9})[0]
    assert "kind 'video'" in refused(demo, {"op": "add_track", "track": {"id": "x", "kind": "video"}})[0]


def test_update_track_deep_merges(demo):
    s = ok(demo, {"op": "update_track", "id": "cap", "set": {"emphasis": ["毛利"], "max_chars": None,
                                                             "style": {"color": "#FFD34D"}}})
    assert s == "updated track cap: emphasis, max_chars (removed), style"
    cap = track(raw(demo), "cap")
    assert cap["emphasis"] == ["毛利"] and "max_chars" not in cap and cap["style"] == {"color": "#FFD34D"}
    ok(demo, {"op": "update_track", "id": "cap", "set": {"style": {"weight": 700}}})
    assert track(raw(demo), "cap")["style"] == {"color": "#FFD34D", "weight": 700}
    rows = refused(demo, {"op": "update_track", "id": "cap", "set": {"max_chars": 1}})
    assert any("max_chars" in r for r in rows)


def test_remove_track(demo):
    assert ok(demo, {"op": "remove_track", "id": "notes"}) == "removed track notes with 1 clip(s): todo"
    ok(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "clip:shop+7"}})
    rows = refused(demo, {"op": "remove_track", "id": "bg"})        # arrow is timed from a clip on bg
    assert any("there is no clip 'shop'" in r for r in rows)
    assert "no track 'zz'" in refused(demo, {"op": "remove_track", "id": "zz"})[0]


# ------------------------------------------------------------------ clips
def test_add_clip(demo):
    s = ok(demo, {"op": "add_clip", "track": "fg", "clip": {"id": "t2", "type": "text", "text": "**两块五**",
                                                            "start": "line:3", "dur": 1.5}})
    assert s == "added text clip t2 to fg [t2 5.62-7.12 s]"
    assert clip(raw(demo), "t2")["text"] == "**两块五**"
    assert "captions track" in refused(demo, {"op": "add_clip", "track": "cap", "clip": {"id": "x"}})[0]
    assert "audio track" in refused(demo, {"op": "add_clip", "track": "music",
                                           "clip": {"id": "x", "type": "text", "text": "a", "start": 0, "dur": 1}})[0]
    assert "visual track" in refused(demo, {"op": "add_clip", "track": "fg",
                                            "clip": {"id": "x", "type": "audio", "asset": "bed", "start": 0,
                                                     "dur": 1}})[0]
    assert "taken" in refused(demo, {"op": "add_clip", "track": "fg", "clip": {"id": "hook"}})[0]


def test_add_clip_that_overlaps_is_refused_with_the_reason(demo):
    rows = refused(demo, {"op": "add_clip", "track": "fg", "clip": {"id": "t3", "type": "text", "text": "x",
                                                                    "start": 1, "dur": 1}})
    assert rows == ["[error] track fg: clips hook (0.00-5.40 s) and t3 (1.00-2.00 s) overlap by 1.00 s: clips on one "
                    "track must not overlap; trim or move one, or put it on another track"]


def test_update_clip(demo):
    s = ok(demo, {"op": "update_clip", "id": "hook", "set": {"style": {"color": "#FFD34D", "stroke": None},
                                                             "reveal": None, "opacity": 0.9}})
    assert s.startswith("updated clip hook: style.color, style.stroke (removed), reveal (removed), opacity")
    c = clip(raw(demo), "hook")
    assert c["style"] == {"size": "fit", "max_size": 130, "weight": 900, "color": "#FFD34D"}
    assert "reveal" not in c and c["opacity"] == 0.9
    ok(demo, {"op": "update_clip", "id": "arrow", "set": {"end": "line:5.end"}})
    c = clip(raw(demo), "arrow")
    assert c["end"] == "line:5.end" and "dur" not in c                # end replaces dur
    ok(demo, {"op": "update_clip", "id": "arrow", "set": {"dur": 1}})
    c = clip(raw(demo), "arrow")
    assert c["dur"] == 1 and "end" not in c
    rows = refused(demo, {"op": "update_clip", "id": "hook", "set": {"style": {"size": "huge"}}})
    assert rows[0].startswith("[error] clip hook.style.size: should be a size")


def test_update_clip_rename_follows_references(demo):
    ok(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "clip:proof+1"}})
    s = ok(demo, {"op": "update_clip", "id": "proof", "set": {"id": "proof1"}})
    assert "renamed to proof1; 1 Time reference(s) follow it" in s
    assert clip(raw(demo), "arrow")["start"] == "clip:proof1+1"
    assert "taken" in refused(demo, {"op": "update_clip", "id": "proof1", "set": {"id": "hook"}})[0]


def test_op_field_errors_say_how_to_call(demo):
    rows = refused(demo, {"op": "update_clip", "id": "hook", "style": {}})
    assert rows == ['[error] ops[0] update_clip: update_clip needs set and has unknown field(s) style; its fields: '
                    'id, set (the changes go inside "set": {"set": {"style": ...}})']
    assert "unknown op 'delete_clip'; ops: add_track" in refused(demo, {"op": "delete_clip", "id": "x"})[0]
    assert 'each op is an object with an "op"' in refused(demo, {"id": "x"})[0]
    assert "no clip 'nope'; clips: open, shop" in refused(demo, {"op": "remove_clip", "id": "nope"})[0]
    good, issues, summary = ops.apply(demo, [])
    assert not good and "non-empty list" in str(issues[0])


def test_remove_clip(demo):
    assert ok(demo, {"op": "remove_clip", "id": "todo"}) == "removed text clip todo from notes"
    ok(demo, {"op": "update_clip", "id": "arrow", "set": {"start": "clip:proof+1"}})
    rows = refused(demo, {"op": "remove_clip", "id": "proof"})
    assert any("clip arrow" in r and "no clip 'proof'" in r for r in rows)


def test_move_clip_keeps_length_and_changes_track(demo):
    good, issues, s = ops.apply(demo, [{"op": "move_clip", "id": "verdict", "start": "line:7+0.2"}])
    c = clip(raw(demo), "verdict")
    assert good and c["start"] == "line:7+0.2" and c["dur"] == 3.28 and "end" not in c
    assert "length kept: dur 3.28 s" in s and "verdict 18.72-22.00 s" in s
    assert [str(i) for i in issues] == ["[warning] clip verdict: ends at 22.00 s, after the film's end (21.80 s): "
                                        "the rest is cut"]
    ok(demo, {"op": "move_clip", "id": "arrow", "start": "line:5+0.5"})
    assert clip(raw(demo), "arrow")["dur"] == 1.5                     # a dur clip keeps its dur as written
    rows = refused(demo, {"op": "move_clip", "id": "proof", "start": "line:5+0.5"})    # 3.6 s now runs into count
    assert any("clips proof (12.12-15.72 s) and count (15.22-18.52 s) overlap" in r for r in rows)
    ok(demo, {"op": "add_track", "track": {"id": "v4", "kind": "visual"}},
       {"op": "move_clip", "id": "proof", "track": "v4", "start": "line:5", "end": "line:6.end"})
    data = raw(demo)
    assert [c["id"] for c in track(data, "v4")["clips"]] == ["proof"]
    assert "proof" not in [c["id"] for c in track(data, "mid")["clips"]]
    assert clip(data, "proof")["end"] == "line:6.end" and "dur" not in clip(data, "proof")
    assert "audio track" in refused(demo, {"op": "move_clip", "id": "proof", "track": "music"})[0]
    assert "nothing to move" in refused(demo, {"op": "move_clip", "id": "proof"})[0]
    assert "not both" in refused(demo, {"op": "move_clip", "id": "proof", "end": 20, "dur": 1})[0]


def test_set_keyframes(demo):
    s = ok(demo, {"op": "set_keyframes", "id": "proof", "prop": "scale",
                  "frames": [{"t": 0, "v": 0.9}, {"t": "line:5+0.5", "v": 1, "ease": "out"}]})
    assert s.startswith("set 2 keyframe(s) for scale on proof")
    assert clip(raw(demo), "proof")["keyframes"]["scale"][1]["t"] == "line:5+0.5"
    ok(demo, {"op": "set_keyframes", "id": "proof", "prop": "scale", "frames": []})
    assert "keyframes" not in clip(raw(demo), "proof")
    assert "prop 'zoooom'" in refused(demo, {"op": "set_keyframes", "id": "proof", "prop": "zoooom", "frames": []})[0]
    assert "audio clips have no keyframes" in refused(demo, {"op": "set_keyframes", "id": "bed1", "prop": "x",
                                                             "frames": []})[0]
    rows = refused(demo, {"op": "set_keyframes", "id": "proof", "prop": "x", "frames": [{"t": "line:99", "v": 1}]})
    assert any("line:99 is past the voice" in r for r in rows)


# ------------------------------------------------------------------ split
def frames_of(resolved, cid):
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def rendered(resolved, cid, prop, fps=30):
    """{absolute frame: value} of a keyframed prop over the clip, as the renderer computes it."""
    c = frames_of(resolved, cid)
    return {c["from"] + f: R.value_at(c["keyframes"][prop], f, fps) for f in range(c["dur"])}


def test_split_keeps_every_rendered_value_of_linear_moves(demo):
    ok(demo, {"op": "set_keyframes", "id": "proof", "prop": "x",
              "frames": [{"t": 0, "v": 60}, {"t": 1, "v": 100}, {"t": "line:6-0.5", "v": 40, "ease": "linear"}]})
    before = rendered(R.resolve(demo), "proof", "x")
    s = ok(demo, {"op": "split_clip", "id": "proof", "at": "line:5+1.5", "new_id": "proof2"})
    assert s.startswith("split clip proof at 13.12 s into proof and proof2")
    after = R.resolve(demo)
    joined = {**rendered(after, "proof", "x"), **rendered(after, "proof2", "x")}
    assert joined.keys() == before.keys()
    for f, v in before.items():
        assert joined[f] == pytest.approx(v, abs=1e-6), f


def every_frame(resolved, ids):
    """{(prop, absolute frame): value} of every keyframed prop of the clips, as the renderer computes it."""
    out = {}
    for t in resolved["tracks"]:
        for c in t.get("clips") or []:
            if c["id"] in ids:
                for prop, ks in c["keyframes"].items():
                    out.update({(prop, c["from"] + f): R.value_at(ks, f, resolved["fps"]) for f in range(c["dur"])})
    return out


def assert_same_film(before, after):
    assert after.keys() == before.keys()
    bad = [(k, before[k], after[k]) for k in before if abs(before[k] - after[k]) > 1e-6]
    assert not bad, bad[:5]


def test_split_is_exact_on_every_frame_for_eased_moves_and_motion(demo):
    ok(demo, {"op": "set_keyframes", "id": "close", "prop": "opacity",
              "frames": [{"t": 1, "v": 0.2}, {"t": 6, "v": 1, "ease": "inOut"}]})
    before = every_frame(R.resolve(demo), {"close"})
    s = ok(demo, {"op": "split_clip", "id": "close", "at": 15, "new_id": "close2"})
    data = raw(demo)
    assert "motion" not in clip(data, "close") and "motion" not in clip(data, "close2")     # baked in
    assert "motion 'pull' became zoom/pan keyframes on both halves" in s
    assert_same_film(before, every_frame(R.resolve(demo), {"close", "close2"}))


@pytest.mark.parametrize("ease", ["in", "out", "inOut", "spring"])
@pytest.mark.parametrize("at", ["line:5+0.5", "line:5+1.3", "line:5+2.9"])
def test_split_inside_an_eased_move_keeps_both_halves_frame_exact(demo, ease, at):
    ok(demo, {"op": "set_keyframes", "id": "proof", "prop": "x",
              "frames": [{"t": 0.2, "v": 60}, {"t": 3, "v": 400, "ease": ease}]},
       {"op": "set_keyframes", "id": "proof", "prop": "scale",
        "frames": [{"t": 0, "v": 0.9}, {"t": "line:5+1", "v": 1.1, "ease": "spring"},
                   {"t": 2.5, "v": 1, "ease": "in"}]})
    before = every_frame(R.resolve(demo), {"proof"})
    ok(demo, {"op": "split_clip", "id": "proof", "at": at, "new_id": "proof2"})
    assert_same_film(before, every_frame(R.resolve(demo), {"proof", "proof2"}))


def test_split_edge_cases_are_frame_exact(demo):
    for cid, at in (("ring", "line:6+0.8"), ("hook", 0.25), ("open", "line:2")):
        p = demo.parent / f"case_{cid}"
        shutil.copytree(demo, p)
        before = every_frame(R.resolve(p), {cid})
        ok(p, {"op": "split_clip", "id": cid, "at": at, "new_id": f"{cid}2"})
        assert_same_film(before, every_frame(R.resolve(p), {cid, f"{cid}2"}))


def test_split_mid_draw_on_continues_the_draw(demo):
    ok(demo, {"op": "split_clip", "id": "arrow", "at": "clip:arrow+0.3", "new_id": "arrow2"})
    r = R.resolve(demo)
    two = frames_of(r, "arrow2")
    n = 18                                                            # the renderer's default draw: 0.6 s, out-cubic
    for k in range(two["dur"]):
        want = 1 - (1 - min(1, (9 + k) / n)) ** 3
        assert R.value_at(two["keyframes"]["progress"], k, 30) == pytest.approx(want, abs=1e-6), k
    assert "keyframes" not in clip(raw(demo), "arrow")                 # the first half draws as before


def test_split_moves_numbers_inside_the_clip_to_the_second_half(demo):
    ok(demo, {"op": "update_clip", "id": "proof", "set": {"highlight": {"at": 1}}},
       {"op": "update_clip", "id": "bill", "set": {"props": {"rows": [{"label": "茶底和奶", "value": "¥2.5", "at": 2.0},
                                                                      {"label": "杯子吸管", "value": "¥1.0",
                                                                       "at": "line:4"}]}}})
    r0 = R.resolve(demo)
    hl_abs = frames_of(r0, "proof")["from"] + frames_of(r0, "proof")["content"]["highlight"]["at"]
    ok(demo, {"op": "split_clip", "id": "proof", "at": "clip:proof+0.5", "new_id": "proof2"},
       {"op": "split_clip", "id": "bill", "at": "line:3+1", "new_id": "bill2"},
       {"op": "split_clip", "id": "verdict", "at": "line:7+1", "new_id": "verdict2"})
    data = raw(demo)
    assert clip(data, "proof2")["highlight"] == {"at": 0.5}
    rows = clip(data, "bill2")["props"]["rows"]
    assert rows[0]["at"] == 1 and rows[1]["at"] == "line:4"
    assert clip(data, "verdict2")["props"]["at"] == "clip:verdict+0.3"  # already past: anchored on the first half
    r1 = R.resolve(demo)
    two = frames_of(r1, "proof2")
    assert two["from"] + two["content"]["highlight"]["at"] == hl_abs
    assert frames_of(r1, "verdict2")["content"]["props"]["at"] < 0


def test_split_after_the_default_highlight_keeps_it_done(demo):
    ok(demo, {"op": "update_clip", "id": "proof", "set": {"highlight": {"at": None, "dur": 0.8}}})
    r0 = R.resolve(demo)
    assert frames_of(r0, "proof")["content"]["highlight"]["at"] is None          # the renderer's 0.3 s
    ok(demo, {"op": "split_clip", "id": "proof", "at": "clip:proof+2", "new_id": "proof2"})
    assert clip(raw(demo), "proof2")["highlight"]["at"] == "clip:proof+0.3"
    two = frames_of(R.resolve(demo), "proof2")
    assert two["from"] + two["content"]["highlight"]["at"] == frames_of(r0, "proof")["from"] + 9


def test_split_video_trim_enter_exit_and_end_references(demo):
    ok(demo, {"op": "update_clip", "id": "shop", "set": {"enter": {"preset": "fade"}, "exit": {"preset": "fade"},
                                                         "rate": 2}},
       {"op": "update_clip", "id": "bill", "set": {"end": "clip:shop.end"}})
    s = ok(demo, {"op": "split_clip", "id": "shop", "at": "line:4", "new_id": "shop2"})
    data = raw(demo)
    a, b = clip(data, "shop"), clip(data, "shop2")
    assert a["end"] == "line:4" and "exit" not in a and a["enter"] == {"preset": "fade"}
    assert b["start"] == "line:4" and b["end"] == "line:5" and "enter" not in b and b["exit"] == {"preset": "fade"}
    # a 2 s looping source, trim 15 frames, rate 2: the renderer's loop is 22 frames; 78 frames in it is at 12
    assert b["trim_in"] == (1.3 if shutil.which("ffprobe") else pytest.approx(0.5 + 78 / 30 * 2))
    assert "shop2 starts where the loop was at the cut" in s
    assert clip(data, "bill")["end"] == "clip:shop2.end"                       # still ends where shop ended
    assert "1 reference(s) to clip:shop.end now point at shop2" in s
    ids = [c["id"] for c in track(data, "bg")["clips"]]
    assert ids == ["open", "shop", "shop2", "close"]


def test_split_dur_clip_and_self_relative_cut(demo):
    ok(demo, {"op": "split_clip", "id": "arrow", "at": "clip:arrow+0.8", "new_id": "arrow2"},
       {"op": "split_clip", "id": "ring", "at": "clip:ring+0.3", "new_id": "ring2"})
    data = raw(demo)
    a, b = clip(data, "arrow"), clip(data, "arrow2")
    assert a["end"] == 13.433 and "dur" not in a                   # baked to seconds, on its frame (403)
    assert b["start"] == 13.433 and b["dur"] == 0.687
    assert b["draw"] is False                                         # its 0.6 s draw-on already happened
    assert clip(data, "ring2")["draw"] is True                        # driven by progress keyframes: kept


def test_split_text_evidence_component(demo):
    s = ok(demo, {"op": "split_clip", "id": "hook", "at": 3, "new_id": "hook2"},
           {"op": "split_clip", "id": "proof", "at": 14, "new_id": "proof2"},
           {"op": "split_clip", "id": "verdict", "at": 20, "new_id": "verdict2"})
    data = raw(demo)
    assert "reveal" in clip(data, "hook") and "reveal" not in clip(data, "hook2")
    assert clip(data, "proof2")["highlight"] == {"at": "line:5+0.8"}           # absolute Times need no change
    assert "start over in verdict2" in s and "hook2 shows its text without the reveal" in s


def test_split_audio_clip_advances_trim(demo):
    ok(demo, {"op": "update_clip", "id": "bed1", "set": {"trim_in": 0.2, "fade_in": 0.3}})
    ok(demo, {"op": "split_clip", "id": "bed1", "at": 1.5, "new_id": "bed2"})
    data = raw(demo)
    assert clip(data, "bed1")["end"] == 1.5 and clip(data, "bed2")["start"] == 1.5
    assert clip(data, "bed2")["dur"] == 0.5 and clip(data, "bed2")["trim_in"] == pytest.approx(1.7)
    audio = {a["id"]: a for a in R.resolve(demo)["audio"]}
    assert (audio["bed1"]["from"], audio["bed1"]["dur"]) == (0, 45)
    assert (audio["bed2"]["from"], audio["bed2"]["dur"], audio["bed2"]["trimIn"]) == (45, 15, 51)


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not on PATH")
def test_split_looping_audio_starts_where_the_loop_was(demo):
    ok(demo, {"op": "update_clip", "id": "bed1", "set": {"loop": True, "dur": 12}})
    s = ok(demo, {"op": "split_clip", "id": "bed1", "at": 5, "new_id": "bed2"})
    assert clip(raw(demo), "bed2")["trim_in"] == 1 and clip(raw(demo), "bed2")["loop"] is True    # 150 % 60 frames
    assert "bed2 starts where the loop was at the cut" in s


def test_provider_style_calls(demo):
    # what reelsmith.providers sends: add_asset to register or replace, set voice when unset
    shutil.copy(demo / "assets" / "photo.png", demo / "assets" / "drawn.png")
    good, _, s = ops.apply(demo, [{"op": "add_asset", "id": "drawn",
                                   "asset": {"path": "assets/drawn.png", "kind": "image", "note": "a prompt"}}])
    assert good and s.startswith("added asset drawn")
    good, _, s = ops.apply(demo, [{"op": "set", "path": "voice", "value": "voice/voice.json"}])
    assert good and "unchanged" in s


def test_split_refusals(demo):
    assert "not inside clip hook" in refused(demo, {"op": "split_clip", "id": "hook", "at": 9, "new_id": "h2"})[0]
    assert "not inside" in refused(demo, {"op": "split_clip", "id": "hook", "at": 0, "new_id": "h2"})[0]
    assert "taken" in refused(demo, {"op": "split_clip", "id": "hook", "at": 1, "new_id": "proof"})[0]
    assert "cannot read the Time" in refused(demo, {"op": "split_clip", "id": "hook", "at": "soon", "new_id": "h"})[0]


def test_split_keyframes_unit():
    ks = [{"f": 10, "v": 0.0, "ease": None, "raw": {"t": "line:2", "v": 0}},
          {"f": 40, "v": 1.0, "ease": "out", "raw": {"t": 40 / 30, "v": 1, "ease": "out"}}]
    first, second = ops.split_keyframes(ks, 5, 30)               # before the first key: both halves hold
    assert first == [{"t": 0.1667, "v": 0}] and second[0] == {"t": 0, "v": 0}
    assert second[1] == {"t": "line:2", "v": 0} and second[2]["t"] == pytest.approx(40 / 30 - 5 / 30, abs=1e-4)
    first, second = ops.split_keyframes(ks, 25, 30)              # inside an eased move: one linear key per frame
    assert [k["t"] for k in first[1:]] == [round(f / 30, 4) for f in range(11, 26)] and "ease" not in first[-1]
    assert first[-1]["v"] == pytest.approx(R.value_at(ks, 25, 30), abs=1e-6)
    assert [round(k["t"] * 30) for k in second] == list(range(0, 16)) and second[-1] == {"t": 0.5, "v": 1,
                                                                                         "ease": "out"}
    first, second = ops.split_keyframes(ks, 40, 30)              # exactly on a key: no extra key
    assert len(first) == 2 and second == [{"t": 0, "v": 1}]
    linear = [dict(ks[0]), {**ks[1], "ease": "linear", "raw": {"t": 40 / 30, "v": 1, "ease": "linear"}}]
    first, second = ops.split_keyframes(linear, 25, 30)          # a linear move cuts exactly with one key
    assert first[-1] == {"t": 0.8333, "v": 0.5, "ease": "linear"} and len(second) == 2


# ------------------------------------------------------------------ assets and set
def test_assets(demo):
    assert ok(demo, {"op": "add_asset", "id": "p2", "asset": {"path": "assets/photo.png", "kind": "image"}}) == \
        "added asset p2 (image assets/photo.png)"
    assert ok(demo, {"op": "add_asset", "id": "p2", "asset": {"path": "assets/evidence.png", "kind": "image"}}) == \
        "replaced asset p2 (image assets/evidence.png)"
    assert ok(demo, {"op": "remove_asset", "id": "p2"}) == "removed asset p2 (the file stays in the project folder)"
    assert "used by clip(s) open, close" in refused(demo, {"op": "remove_asset", "id": "photo"})[0]
    ok(demo, {"op": "add_track", "track": {"id": "cards", "kind": "visual"}},
       {"op": "add_clip", "track": "cards", "clip": {"id": "card", "type": "component", "name": "EvidenceCard",
                                                     "start": 16, "dur": 0.5, "props": {"asset": "ev"}}},
       {"op": "update_clip", "id": "proof", "set": {"type": "text", "text": "x", "asset": None, "highlight": None}})
    assert "used by clip(s) card" in refused(demo, {"op": "remove_asset", "id": "ev"})[0]
    rows = refused(demo, {"op": "add_asset", "id": "x", "asset": {"path": "assets/none.png", "kind": "image"}})
    assert rows == ["[error] assets.x: file missing: assets/none.png"]
    assert "asset id 'a b'" in refused(demo, {"op": "add_asset", "id": "a b", "asset": {}})[0]


def test_update_asset(demo):
    s = ok(demo, {"op": "update_asset", "id": "ev", "set": {"box": [40, 400, 470, 80], "note": "wider", "site": None}})
    assert s == "updated asset ev: box, note, site (removed)"
    assert raw(demo)["assets"]["ev"] == {"path": "assets/evidence.png", "kind": "evidence", "box": [40, 400, 470, 80],
                                         "url": "https://example.com/milk-tea-cost", "note": "wider"}
    rows = refused(demo, {"op": "update_asset", "id": "photo", "set": {"kind": "evidence"}})
    assert rows == ["[error] ops[0] update_asset: asset 'photo' is used by clip(s) open, close: its kind cannot "
                    "change from 'image' to 'evidence' while they use it"]
    ok(demo, {"op": "add_asset", "id": "p2", "asset": {"path": "assets/photo.png", "kind": "image"}})
    ok(demo, {"op": "update_asset", "id": "p2", "set": {"kind": "evidence"}})        # nothing uses it: fine
    assert "no asset 'nope'" in refused(demo, {"op": "update_asset", "id": "nope", "set": {}})[0]
    assert "its key" in refused(demo, {"op": "update_asset", "id": "ev", "set": {"id": "ev9"}})[0]
    rows = refused(demo, {"op": "update_asset", "id": "ev", "set": {"path": None}})
    assert any("assets.ev.path: path is required" in r for r in rows)
    assert "set must be an object" in refused(demo, {"op": "update_asset", "id": "ev", "set": [1]})[0]


def test_bad_input_types_are_refused_not_crashed(demo):
    assert "no asset ['photo']" in refused(demo, {"op": "remove_asset", "id": ["photo"]})[0]
    assert "no asset {'a': 1}" in refused(demo, {"op": "update_asset", "id": {"a": 1}, "set": {}})[0]
    assert "'²' is not a position" in refused(demo, {"op": "set", "path": "meta.sources.²", "value": 1})[0]
    assert "no track ['bg']" in refused(demo, {"op": "add_clip", "track": ["bg"], "clip": {}})[0]
    assert "no clip ['hook']" in refused(demo, {"op": "update_clip", "id": ["hook"], "set": {}})[0]
    assert "prop ['x']" in refused(demo, {"op": "set_keyframes", "id": "hook", "prop": ["x"], "frames": []})[0]


# ------------------------------------------------------------------ project.json held open (Windows)
def debris(p):
    return sorted(f.name for f in p.iterdir() if f.name.endswith(".tmp"))


def test_a_write_that_fails_leaves_no_history_and_no_temp_file(demo, monkeypatch):
    real = ops.os.replace

    def held(src, dst):
        if Path(dst).name == "project.json":
            raise PermissionError(13, "the file is held by another program")
        return real(src, dst)
    monkeypatch.setattr(ops.os, "replace", held)
    monkeypatch.setattr(ops, "SHARING_TRIES", 3)
    before = text_of(demo)
    good, issues, summary = ops.apply(demo, [{"op": "set", "path": "meta.title", "value": "新"}])
    assert not good and summary == "nothing changed"
    assert str(issues[0]).startswith("[error] project.json: cannot be written (the file is held by another program): "
                                     "another program holds it open; close it, then send the batch again")
    assert text_of(demo) == before and debris(demo) == [] and ops.snapshots(demo) == []
    assert not (demo / ".history" / "log.jsonl").exists()
    monkeypatch.setattr(ops.os, "replace", real)
    ok(demo, {"op": "set", "path": "meta.title", "value": "新"})
    assert [n for n, _ in ops.snapshots(demo)] == [1]                  # numbering did not skip the failed batch
    good, text = ops.undo(demo)
    assert good and text_of(demo) == before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing violations")
def test_project_json_held_open_on_windows(demo, monkeypatch):
    monkeypatch.setattr(ops, "SHARING_TRIES", 3)
    before = text_of(demo)
    with open(demo / "project.json", "rb"):                             # what an editor or a scanner does
        good, issues, _ = ops.apply(demo, [{"op": "set", "path": "meta.title", "value": "新"}])
    assert not good and "another program holds it open" in str(issues[0])
    assert text_of(demo) == before and debris(demo) == [] and ops.snapshots(demo) == []
    assert ops.undo(demo) == (False, "nothing to undo: no edit batch has been recorded for this project")
    monkeypatch.setattr(ops, "SHARING_TRIES", 20)
    handle = open(demo / "project.json", "rb")
    threading.Timer(0.15, handle.close).start()                         # let go while the edit retries
    ok(demo, {"op": "set", "path": "meta.title", "value": "新"})
    assert raw(demo)["meta"]["title"] == "新" and len(ops.snapshots(demo)) == 1 and debris(demo) == []


def test_set_paths(demo):
    assert ok(demo, {"op": "set", "path": "meta.title", "value": "奶茶的账"}) == 'set meta.title = "奶茶的账"'
    ok(demo, {"op": "set", "path": "meta.sources.1", "value": {"title": "b", "url": "https://b.example"}})
    ok(demo, {"op": "set", "path": "meta.sources.0.title", "value": "first"})
    data = raw(demo)
    assert data["meta"]["title"] == "奶茶的账" and [s["title"] for s in data["meta"]["sources"]] == ["first", "b"]
    assert ok(demo, {"op": "set", "path": "meta.sources.1", "value": None}) == "removed meta.sources.1"
    assert len(raw(demo)["meta"]["sources"]) == 1
    ok(demo, {"op": "set", "path": "duration", "value": "line:7.end+1"})
    assert raw(demo)["duration"] == "line:7.end+1"
    assert ok(demo, {"op": "set", "path": "theme.accent", "value": "#E33"}) == 'set theme.accent = "#E33"'
    assert "does not edit tracks" in refused(demo, {"op": "set", "path": "tracks.0.id", "value": "x"})[0]
    assert "not a position" in refused(demo, {"op": "set", "path": "meta.sources.5", "value": {}})[0]
    assert "holds a value, not an object" in refused(demo, {"op": "set", "path": "voice.file", "value": "x"})[0]
    assert "'x' is inside a value that is not an object" in refused(demo, {"op": "set", "path": "meta.title.x.y",
                                                                             "value": 1})[0]
    rows = refused(demo, {"op": "set", "path": "meta.titel", "value": "x"})
    assert rows[0].startswith("[error] meta.titel: unknown field 'titel'")
    assert "unchanged" in ops.apply(demo, [{"op": "set", "path": "meta.nothing", "value": None}])[2]


# ------------------------------------------------------------------ atomicity and pre-existing errors
def test_a_failing_op_late_in_the_batch_changes_nothing(demo):
    rows = refused(demo, {"op": "set", "path": "meta.title", "value": "x"},
                   {"op": "remove_clip", "id": "todo"},
                   {"op": "remove_clip", "id": "todo"})
    assert rows == ["[error] ops[2] remove_clip: no clip 'todo'; clips: open, shop, close, bill, proof, count, hook, "
                    "arrow, ring, verdict, bed1"]


def test_errors_already_there_do_not_block_other_edits(demo):
    data = raw(demo)
    data["assets"]["gone"] = {"path": "assets/gone.png", "kind": "image"}       # broken by hand
    (demo / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    good, issues, summary = ops.apply(demo, [{"op": "set", "path": "meta.title", "value": "新"}])
    assert good and any("file missing: assets/gone.png" in str(i) for i in issues)
    rows = refused(demo, {"op": "update_clip", "id": "open", "set": {"asset": "nope"}})
    assert all("gone.png" not in r for r in rows) and any("no asset 'nope'" in r for r in rows)
    assert ok(demo, {"op": "remove_asset", "id": "gone"}) == "removed asset gone (the file stays in the project folder)"


def test_unreadable_project_is_refused(demo):
    (demo / "project.json").write_text("{oops", encoding="utf-8")
    good, issues, _ = ops.apply(demo, [{"op": "set", "path": "meta.title", "value": "x"}])
    assert not good and "cannot be read" in str(issues[0]) and "undo" in str(issues[0])
    good, issues, _ = ops.apply(demo.parent / "nowhere", [{"op": "set", "path": "meta.title", "value": "x"}])
    assert not good and "new_project" in str(issues[0])


# ------------------------------------------------------------------ history and undo
def test_history_and_undo(demo):
    original = text_of(demo)
    ok(demo, {"op": "set", "path": "meta.title", "value": "一"})
    after_one = text_of(demo)
    ok(demo, {"op": "set", "path": "meta.title", "value": "二"})
    ok(demo, {"op": "remove_clip", "id": "todo"})
    assert [n for n, _ in ops.snapshots(demo)] == [1, 2, 3]
    assert (demo / ".history" / "0001.json").read_bytes() == original           # the exact previous file
    good, text = ops.undo(demo)
    assert good and "back to its state before batch 3" in text and "undone: removed text clip todo" in text
    assert raw(demo)["meta"]["title"] == "二" and clip(raw(demo), "todo")
    assert (demo / ".history" / "redo.json").is_file()
    good, text = ops.undo(demo)
    assert good and text_of(demo) == after_one
    good, text = ops.undo(demo)
    assert good and text_of(demo) == original
    assert ops.snapshots(demo) == []


def test_undo_steps_and_limits(demo):
    original = text_of(demo)
    good, text = ops.undo(demo)
    assert not good and "nothing to undo" in text
    for title in ("a", "b", "c"):
        ok(demo, {"op": "set", "path": "meta.title", "value": title})
    good, text = ops.undo(demo, 4)
    assert not good and text == "only 3 batch(es) can be undone; nothing changed"
    good, text = ops.undo(demo, 3)
    assert good and text_of(demo) == original and ops.snapshots(demo) == []
    assert ops.undo(demo, 0) == (False, "steps must be a whole number >= 1")
    ok(demo, {"op": "set", "path": "meta.title", "value": "d"})
    assert [n for n, _ in ops.snapshots(demo)] == [1]


def test_unchanged_batch_takes_no_snapshot(demo):
    ok(demo, {"op": "update_track", "id": "cap", "set": {}})
    assert ops.snapshots(demo) == []


def test_tools_edit_and_undo_use_the_real_ops(demo):
    r = tools.edit(str(demo), [{"op": "set", "path": "meta.title", "value": "工具"}])
    assert r.ok and r.startswith('applied: set meta.title = "工具"')
    r = tools.edit(str(demo), [{"op": "remove_clip", "id": "nope"}])
    assert not r.ok and r.startswith("REFUSED: nothing changed.") and "no clip 'nope'" in r
    r = tools.undo(str(demo))
    assert r.ok and "back to its state before batch 1" in r
    assert raw(demo)["meta"]["title"] == "一杯奶茶的成本"
