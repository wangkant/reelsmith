import json
import shutil
from pathlib import Path

import pytest

from reelsmith import checks
from reelsmith import document as D
from reelsmith import library as L

FIXTURE = Path(__file__).parent / "fixtures" / "demo"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "demo"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    return p


def raw(p):
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


def write(p, data):
    (p / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def clip(data, cid):
    return next(c for t in data["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def issues_of(p, data):
    return D.check_data(p, data)[1]


def find(issues, level, where, text=""):
    return [i for i in issues if i.level == level and i.where == where and text in i.msg]


# ------------------------------------------------------------------ load / save
def test_fixture_loads_and_validates_clean(demo):
    doc = D.load(demo)
    assert D.validate(demo, doc) == []
    types = {c.type for _, c in D.clips_of(doc)}
    assert types == {"image", "video", "text", "shape", "evidence", "component", "audio"}
    assert {t.kind for t in doc.tracks} == {"visual", "audio", "captions"}


def test_save_round_trips_and_keeps_the_file_readable(demo):
    doc = D.load(demo)
    D.save(demo, doc)
    text = (demo / "project.json").read_text(encoding="utf-8")
    assert "一杯奶茶的成本" in text and "\\u" not in text          # ensure_ascii False
    assert text.startswith("{\n \"version\": 2")                  # indent 1
    again = D.load(demo)
    assert again == doc
    saved = json.loads(text)
    assert saved["tracks"][0]["clips"][0]["start"] == 0 and isinstance(saved["tracks"][0]["clips"][0]["start"], int)
    assert "opacity" not in saved["tracks"][0]["clips"][0]            # defaults are not written out
    assert saved == raw(FIXTURE)


def test_save_accepts_a_dict_and_writes_atomically(demo, monkeypatch):
    D.save(demo, {"version": 2, "tracks": []})
    assert raw(demo) == {"version": 2, "tracks": []}
    assert not [f for f in demo.iterdir() if f.name.endswith(".tmp")]

    def held(src, dst):
        raise PermissionError(13, "held open")
    monkeypatch.setattr(D.os, "replace", held)
    with pytest.raises(PermissionError):
        D.save(demo, {"version": 2})
    assert raw(demo) == {"version": 2, "tracks": []}
    assert not [f for f in demo.iterdir() if f.name.endswith(".tmp")]      # no debris after a failed write


def test_load_errors_pass_through_for_checks(demo):
    (demo / "project.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        D.load(demo)
    (demo / "project.json").unlink()
    with pytest.raises(FileNotFoundError):
        D.load(demo)
    write(demo, [1, 2])
    with pytest.raises(D.DocumentError, match="JSON object"):
        D.load(demo)


# ------------------------------------------------------------------ schema errors
def schema(data) -> list[str]:
    with pytest.raises(D.DocumentError) as e:
        D.parse(data)
    return [f"{i.where}: {i.msg}" for i in e.value.issues]


def test_schema_errors_name_the_clip_and_field():
    rows = schema({"version": 2, "tracks": [{"id": "v1", "kind": "visual", "clips": [
        {"id": "c1", "type": "image", "asset": "a", "start": 0, "end": 2, "fit": "fill", "colour": 1},
        {"id": "c2", "type": "text", "text": "x", "start": 0, "dur": 1, "style": {"size": "big",
                                                                                "stroke": {"colour": "red"}}},
    ]}]})
    assert "clip c1.fit: should be 'cover' or 'contain' (got 'fill')" in rows
    assert any(r.startswith("clip c1.colour: unknown field 'colour'; allowed here: id, type, start") for r in rows)
    assert 'clip c2.style.size: should be a size in px (a number > 0) or "fit" (got \'big\')' in rows
    assert "clip c2.style.stroke.colour: unknown field 'colour'; allowed here: color, width" in rows


@pytest.mark.parametrize("bad, expect", [
    ({"id": "c", "type": "img", "start": 0, "dur": 1}, "clip c: type 'img' is not known"),
    ({"id": "c", "start": 0, "dur": 1}, "clip c: missing 'type' (one of image, video, text"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "end": 1, "dur": 1}, "clip c: give end or dur, not both"),
    ({"id": "c", "type": "text", "text": "x", "start": 0}, "clip c: needs end (a Time) or dur"),
    ({"id": "c", "type": "text", "text": "x", "start": True, "dur": 1}, "clip c.start: should be seconds"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": -1}, "clip c.dur: should be greater than 0"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "box": "middle"},
     "clip c.box: should be 'full' or 'safe'"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "box": {"x": 0}}, "clip c.box.w: w is required"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "keyframes": {"zoomm": []}},
     "clip c.keyframes.zoomm (key): should be 'x'"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "keyframes": {"zoom": [{"t": 0}]}},
     "clip c.keyframes.zoom[0].v: v is required"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "enter": {"preset": "slide"}},
     "clip c.enter.preset: should be 'fade'"),
    ({"id": "c", "type": "image", "asset": "a", "start": 0, "dur": 1, "focus": [0.5]},
     "clip c.focus: List should have at least 2 items"),
    ({"id": "c", "type": "text", "text": "x", "start": 0, "dur": 1, "opacity": "1"}, "clip c.opacity: should be a "),
])
def test_schema_error_messages(bad, expect):
    rows = schema({"version": 2, "tracks": [{"id": "v1", "kind": "visual", "clips": [bad]}]})
    assert any(r.startswith(expect) for r in rows), rows


def test_schema_errors_for_tracks_assets_and_root():
    rows = schema({"version": 3, "meta": {"tags": []}, "assets": {"a": {"path": "a.png", "kind": "img"}},
                   "tracks": [{"id": "m", "kind": "audio", "clips": [{"id": "x", "type": "image", "asset": "a",
                                                                       "start": 0, "dur": 1}]},
                              {"id": "s", "kind": "subtitles"},
                              {"kind": "captions", "max_chars": 2}]})
    assert "version: version must be 2 (this is the v2 project format)" in rows
    assert any(r.startswith("meta.tags: unknown field 'tags'") for r in rows)
    assert "assets.a.kind: should be 'image', 'video', 'audio' or 'evidence' (got 'img')" in rows
    assert any(r.startswith("clip x.type: audio tracks hold only audio clips") for r in rows)
    assert any(r.startswith("track s: kind 'subtitles' is not known") for r in rows)
    assert "tracks[2].id: id is required" in rows
    assert any(r.startswith("tracks[2].max_chars: should be greater than or equal to 4") for r in rows)


def test_document_error_reads_like_checks_expects():
    try:
        D.parse({"version": 2, "tracks": [{"id": "v", "kind": "visual", "clips": [{"id": "c", "type": "x"}]}]})
    except D.DocumentError as exc:
        rows = checks.describe_load_error(exc)
    assert rows and rows[0].startswith("clip c: type 'x' is not known")


# ------------------------------------------------------------------ semantic validation
def test_duplicate_and_malformed_ids(demo):
    data = raw(demo)
    data["tracks"][0]["clips"][0]["id"] = "mid"                    # a track's id
    data["tracks"][1]["clips"][0]["id"] = "bad id"
    data["tracks"][2]["clips"][0]["id"] = "hook-2"
    issues = issues_of(demo, data)
    assert find(issues, "error", "track mid", "id 'mid' is used twice (clip and track)")
    assert find(issues, "error", "clip bad id", "use 1-64 letters")
    assert find(issues, "error", "clip hook-2", "ends like a time offset")


def test_asset_problems(demo):
    data = raw(demo)
    data["assets"]["gone"] = {"path": "assets/gone.png", "kind": "image"}
    data["assets"]["abs"] = {"path": str(demo / "assets" / "photo.png"), "kind": "image"}
    data["assets"]["out"] = {"path": "../photo.png", "kind": "image"}
    data["assets"]["wrong"] = {"path": "assets/clip.mp4", "kind": "image"}
    data["assets"]["odd"] = {"path": "assets/photo.png", "kind": "image", "site": "x"}
    issues = issues_of(demo, data)
    assert find(issues, "error", "assets.gone", "file missing: assets/gone.png")
    assert find(issues, "error", "assets.abs", "must be relative")
    assert find(issues, "error", "assets.out", "leaves the project folder")
    assert find(issues, "error", "assets.wrong", "is not an image file (.mp4); kind should be video")
    assert find(issues, "warning", "assets.odd", "only mean something on evidence")


def test_clip_asset_references(demo):
    data = raw(demo)
    clip(data, "open")["asset"] = "nope"
    clip(data, "shop")["asset"] = "photo"
    clip(data, "proof")["asset"] = "photo"
    clip(data, "bed1")["asset"] = "clip"                            # audio from a video file is fine
    issues = issues_of(demo, data)
    assert find(issues, "error", "clip open.asset", "no asset 'nope' (assets: bed, clip, ev, photo)")
    assert find(issues, "error", "clip shop.asset", "video clips take video assets; 'photo' is image")
    assert find(issues, "error", "clip proof.asset", "evidence clips take evidence assets")
    assert not find(issues, "error", "clip bed1.asset")


def test_time_problems(demo):
    data = raw(demo)
    clip(data, "open")["end"] = "line:9"
    clip(data, "hook")["end"] = "clip:nobody.end"
    clip(data, "arrow")["start"] = "lien:5"
    clip(data, "ring")["end"] = "line:6"                            # == its start
    issues = issues_of(demo, data)
    assert find(issues, "error", "clip open", "line:9 is past the voice: it has 7 line(s)")
    assert find(issues, "error", "clip hook", "there is no clip 'nobody'")
    assert find(issues, "error", "clip arrow", "cannot read the Time 'lien:5'")
    assert find(issues, "error", "clip ring", "not after its start")


def test_cycles_are_errors(demo):
    data = raw(demo)
    clip(data, "arrow")["start"] = "clip:ring.end"
    clip(data, "ring")["end"] = "clip:arrow"
    issues = issues_of(demo, data)
    rows = [i for i in issues if "cycle" in i.msg]
    assert {i.where for i in rows} >= {"clip arrow", "clip ring"}


def test_overlaps_on_one_track_but_not_when_adjacent(demo):
    data = raw(demo)
    clip(data, "shop")["start"] = "line:2.end"                      # into open (ends line:3)
    issues = issues_of(demo, data)
    rows = find(issues, "error", "track bg", "clips open (0.00-5.62 s) and shop (5.40-11.62 s) overlap by 0.22 s")
    assert rows and "another track" in rows[0].msg
    assert not find(issues_of(demo, raw(demo)), "error", "track bg")     # line:3 -> line:3 touches, no overlap


def test_clips_past_the_end_warn(demo):
    data = raw(demo)
    clip(data, "verdict")["end"] = "end+2"
    data["tracks"][2]["clips"].append({"id": "late", "type": "text", "text": "x", "start": 30, "dur": 1})
    issues = issues_of(demo, data)
    assert find(issues, "warning", "clip verdict", "after the film's end (21.80 s): the rest is cut")
    assert find(issues, "warning", "clip late", "never shows")


def test_component_checks(demo):
    data = raw(demo)
    clip(data, "verdict")["props"] = {"text": "太长了不能盖章啊", "at": "line:99", "colour": "red"}
    clip(data, "count")["name"] = "Counter"
    clip(data, "bill")["props"]["rows"][0]["at"] = "line:7"           # after the clip ends
    issues = issues_of(demo, data)
    assert find(issues, "error", "clip verdict", "props: unknown prop(s) colour")
    assert find(issues, "error", "clip verdict", "props.text: 8 characters; at most 6")
    assert find(issues, "error", "clip verdict.props.at", "line:99 is past the voice")
    assert find(issues, "error", "clip count.name", "no component 'Counter'; there are: Arrow, BarCompare")
    assert find(issues, "warning", "clip bill.props.rows[0].at", "after the clip ends")


def test_component_asset_props(demo):
    data = raw(demo)
    data["tracks"][1]["clips"].append({"id": "card", "type": "component", "name": "EvidenceCard", "start": 19,
                                       "dur": 1, "props": {"asset": "evv"}})
    issues = issues_of(demo, data)
    assert find(issues, "error", "clip card.props.asset", "no asset 'evv'")
    data["tracks"][1]["clips"][-1]["props"]["asset"] = "ev"
    assert not [i for i in issues_of(demo, data) if i.where.startswith("clip card")]


def test_voice_problems(demo):
    data = raw(demo)
    data["voice"] = "voice/nope.json"
    assert find(issues_of(demo, data), "error", "voice", "voice/nope.json not found")
    (demo / "voice" / "voice.wav").unlink()
    data["voice"] = "voice/voice.json"
    assert find(issues_of(demo, data), "error", "voice", "narration audio voice/voice.wav")
    (demo / "voice" / "bad.json").write_text('{"lines": [{"t0": 1, "t1": 0.5}, {"text": "x"}]}', encoding="utf-8")
    data["voice"] = "voice/bad.json"
    issues = issues_of(demo, data)
    assert find(issues, "error", "voice line 1", "needs 0 <= t0 <= t1")
    assert find(issues, "error", "voice line 2", "numeric t0 and t1")


def test_voice_file_next_to_voice_json_is_found(demo):
    v = json.loads((demo / "voice" / "voice.json").read_text(encoding="utf-8"))
    v["file"] = "voice.wav"                                          # relative to voice.json
    (demo / "voice" / "voice.json").write_text(json.dumps(v), encoding="utf-8")
    voice, issues = D.load_voice(demo, "voice/voice.json")
    assert issues == [] and voice.audio_rel == "voice/voice.wav" and len(voice.lines) == 7
    assert voice.end == pytest.approx(21.2)


def test_captions_checks(demo):
    data = raw(demo)
    cap = data["tracks"][-1]
    cap["overrides"].append({"line": 9, "text": "x"})
    cap["overrides"].append({"line": 3, "text": "again"})
    issues = issues_of(demo, data)
    assert find(issues, "error", "track cap.overrides[1]", "line 9 is past the voice")
    assert find(issues, "warning", "track cap.overrides[2]", "overridden twice")
    data.pop("voice")
    for t in data["tracks"]:
        for c in t.get("clips") or []:
            for k in ("start", "end"):
                if isinstance(c.get(k), str) and c[k].startswith("line"):
                    c[k] = 1 if k == "start" else 2
    data["duration"] = 22
    issues = issues_of(demo, data)
    assert find(issues, "error", "track cap", "captions come from the voice")
    cap["items"] = [{"start": 0, "end": 1, "text": "hi"}, {"start": 2, "end": 1, "text": ""}]
    issues = issues_of(demo, data)
    assert not find(issues, "error", "track cap")
    assert find(issues, "error", "track cap.items[1]", "not after its start")
    assert find(issues, "warning", "track cap.items[1]", "empty caption")


def test_misc_warnings(demo):
    data = raw(demo)
    clip(data, "open")["keyframes"] = {"zoom": [{"t": 0, "v": 1}, {"t": -1, "v": 2}]}
    clip(data, "arrow")["shape"] = "path"
    clip(data, "hook")["text"] = "a **b"
    data["theme"] = {"accentt": "#fff", "name": "neon"}
    data["profile"] = "vine"
    issues = issues_of(demo, data)
    assert find(issues, "warning", "clip open", "motion 'push' and keyframes on zoom")
    assert find(issues, "error", "clip open.keyframes.zoom[1]", "seconds from the clip's start")
    assert find(issues, "error", "clip arrow", "needs d")
    assert find(issues, "warning", "clip hook", "odd number of ** markers")
    assert find(issues, "warning", "theme.accentt", "not a theme token")
    assert find(issues, "error", "theme.name", "unknown theme 'neon'")
    assert find(issues, "error", "profile", "unknown profile 'vine'")


def test_numbers_inside_a_clip_count_from_its_start(demo):
    data = raw(demo)
    clip(data, "proof")["highlight"] = {"at": 9}                    # proof lasts 3.60 s
    clip(data, "verdict")["props"]["at"] = -1
    clip(data, "bill")["props"]["rows"][0]["at"] = 0.4               # fine: 0.4 s into the receipt
    clip(data, "ring")["keyframes"]["progress"][1]["t"] = 30
    issues = issues_of(demo, data)
    rows = find(issues, "warning", "clip proof.highlight.at",
                "9 s from the clip's start is after it ends (it lasts 3.60 s)")
    assert rows and "numbers here count from the clip's start" in rows[0].msg
    assert find(issues, "error", "clip verdict.props.at", "-1: a number here is seconds from the clip's start")
    assert find(issues, "warning", "clip ring.keyframes.progress[1]", "after it ends")
    assert not [i for i in issues if i.where.startswith("clip bill")]
    clip(data, "proof")["highlight"] = {"at": "line:4"}               # a Time string stays absolute
    assert find(issues_of(demo, data), "advice", "clip proof.highlight.at", "before the clip starts")


def test_fonts_are_the_built_in_ones_or_the_workspaces(demo):
    data = raw(demo)
    for font in D.FONTS:
        clip(data, "hook")["style"]["font"] = font
        assert not [i for i in issues_of(demo, data) if i.level == "error"], font
    clip(data, "hook")["style"]["font"] = "comic"
    data["tracks"][-1]["style"] = {"font": "comic"}
    bad = [str(i) for i in issues_of(demo, data) if i.level == "error"]
    assert len(bad) == 2 and "clip hook.style.font: unknown font 'comic': built-in sans, serif, display, zcool" in bad[0]
    assert "library/fonts/<Family>.woff2" in bad[0] and bad[1].startswith("[error] track cap.style.font")


def test_audio_clip_loop(demo):
    data = raw(demo)
    clip(data, "bed1").update({"loop": True, "dur": 12})
    doc, issues = D.check_data(demo, data)
    assert issues == [] and next(c for _, c in D.clips_of(doc) if c.id == "bed1").loop is True
    clip(data, "bed1")["loop"] = "yes"
    assert any(r.startswith("clip bed1.loop: should be a valid boolean") for r in schema(data))


def test_lines_and_arrows_with_only_fill_are_fine(demo):
    # the renderer strokes a line or arrow in its fill colour when it has no stroke
    data = raw(demo)
    data["tracks"][3]["clips"] += [
        {"id": "l1", "type": "shape", "shape": "line", "fill": "accent", "start": 2, "dur": 1},
        {"id": "l2", "type": "shape", "shape": "arrow", "fill": "accent", "start": 3, "dur": 1},
        {"id": "l3", "type": "shape", "shape": "line", "stroke": "accent", "fill": "gold", "start": 4, "dur": 1},
        {"id": "l4", "type": "shape", "shape": "rect", "fill": "accent", "start": 5, "dur": 1},
        {"id": "t1", "type": "text", "text": "no colour", "start": 6, "dur": 1}]
    issues = issues_of(demo, data)
    assert not [i for i in issues if i.where in ("clip l1", "clip l2", "clip l3", "clip l4", "clip t1")]


def test_new_empty_project_has_one_clear_error(tmp_path):
    p = tmp_path / "empty"
    p.mkdir()
    issues = issues_of(p, {"version": 2, "meta": {}, "assets": {}, "tracks": []})
    assert [(i.level, i.where) for i in issues] == [("error", "duration")]
    assert "no length" in issues[0].msg


def test_markup_runs():
    assert D.markup_runs("a **b** c") == [("a ", False), ("b", True), (" c", False)]
    assert D.markup_runs("**x**") == [("x", True)]
    assert D.markup_runs("a **b") == [("a **b", False)]
    assert D.markup_runs("") == []


def test_prop_refs_any_depth():
    props = {"at": "line:2", "rows": [{"at": 3, "x_asset": "ev"}, {"label": "no"}], "total": {"label_at": "end"},
             "asset": "photo", "format": "x", "data": {"asset": None}}
    found = list(D.prop_refs(props))
    assert ("props.at", "time", "line:2") in found
    assert ("props.rows[0].at", "time", 3) in found
    assert ("props.rows[0].x_asset", "asset", "ev") in found
    assert ("props.total.label_at", "time", "end") in found
    assert ("props.asset", "asset", "photo") in found
    assert len(found) == 5


# ------------------------------------------------------------------ library
def test_every_shipped_example_validates_against_its_schema():
    # a project folder need not exist: the library comes from the nearest workspace.json above it
    comps = L.components(Path(__file__).parent.parent / "examples" / "workspace" / "projects" / "new-film")
    presets = {"Receipt", "Stamp", "CountUp", "BarCompare", "TimelineRule", "DotGrid", "EvidenceCard",
               "Highlighter", "Arrow"}
    assert presets <= set(comps)
    assert comps["PriceTag"].source == "library"
    for name, comp in comps.items():
        assert comp.problem == "", name
        assert comp.example is not None, name
        assert L.validate_props(comp, comp.example) == [], name
        assert comp.path.name == f"{name}.tsx" and comp.path.is_file()


def test_presets_take_latin_text_and_lead_with_english_examples():
    # the same strings renderer/test/presets-preview renders at these lengths
    comps = L.components(Path(__file__).parent.parent / "examples" / "workspace" / "projects" / "new-film")
    latin = {
        "Stamp": {"text": "NOT WORTH IT"},
        "CountUp": {"value": 45, "prefix": "~", "suffix": "minutes a day",
                    "label": "spent on the phone before getting out of bed"},
        "Receipt": {"header": "RECEIPT · WHAT A PRIZE REALLY COSTS", "title": "What the grand prize is worth",
                    "rows": [{"label": "Laptop at the list price", "value": "$1,200",
                              "sub": "the store sets the price the tax is based on"}],
                    "total": {"label": "What you keep", "value": "$960"}},
        "BarCompare": {"unit": " USD", "items": [{"label": "Median household income", "value": 80610}]},
        "TimelineRule": {"points": [{"when": "January 2024", "text": "Rent goes up for the first time, by $200 a month"}]},
        "DotGrid": {"total": 50, "lit": 12, "label_lit": "were refused at the first review",
                    "label_rest": "made it through to the interview"},
        "Arrow": {"label": "the part the buyer never sees"},
        "EvidenceCard": {"asset": "ev", "source": "Source: Example Mall member centre, rules of the 100-day challenge"},
        "PriceTag": {"price": "$4.50", "old": "$3.80", "label": "Large latte, oat milk"},
    }
    for name, props in latin.items():
        assert L.validate_props(comps[name], props) == [], name
    for name, comp in comps.items():
        assert not any("　" <= ch <= "鿿" for ch in json.dumps(comp.example, ensure_ascii=False)), name


def make_lib(tmp_path) -> Path:
    ws = tmp_path / "ws"
    comps = ws / "library" / "components"
    comps.mkdir(parents=True)
    (ws / "workspace.json").write_text("{}", encoding="utf-8")
    (ws / "projects" / "p").mkdir(parents=True)
    return comps


def test_library_shadows_presets_and_reports_broken_metas(tmp_path):
    comps = make_lib(tmp_path)
    (comps / "Stamp.tsx").write_text("export default () => null;", encoding="utf-8")
    (comps / "Stamp.meta.json").write_text(json.dumps({"name": "Stamp", "description": "mine", "props": {
        "type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}}), encoding="utf-8")
    (comps / "Broken.tsx").write_text("", encoding="utf-8")
    (comps / "Broken.meta.json").write_text("{nope", encoding="utf-8")
    (comps / "Lonely.meta.json").write_text(json.dumps({"name": "Lonely", "props": {}}), encoding="utf-8")
    (comps / "Named.tsx").write_text("", encoding="utf-8")
    (comps / "Named.meta.json").write_text(json.dumps({"name": "Other", "props": {}}), encoding="utf-8")
    (comps / "BadSchema.tsx").write_text("", encoding="utf-8")
    (comps / "BadSchema.meta.json").write_text(json.dumps({"props": {"type": "objekt"}}), encoding="utf-8")
    (comps / "Bare.tsx").write_text("", encoding="utf-8")
    (comps / "bad-name.tsx").write_text("", encoding="utf-8")
    found = L.components(tmp_path / "ws" / "projects" / "p")
    assert found["Stamp"].source == "library" and found["Stamp"].description == "mine"
    assert L.validate_props(found["Stamp"], {"text": "x"}) == ["props: 'word' is required"]
    assert "not valid JSON" in found["Broken"].problem
    assert "Lonely.tsx is missing" in found["Lonely"].problem
    assert "says name 'Other'" in found["Named"].problem
    assert "not valid JSON Schema" in found["BadSchema"].problem
    assert found["Bare"].schema == {} and L.validate_props(found["Bare"], {"anything": 1}) == []
    assert "bad-name" not in found
    assert L.validate_props(found["Broken"], {})[0].startswith("component Broken cannot be used")
    assert found["Receipt"].source == "preset"


def test_validate_props_messages():
    comps = L.components(FIXTURE)
    receipt = comps["Receipt"]
    rows = L.validate_props(receipt, {"rows": [{"label": "x" * 20, "value": 1, "foo": 2}], "bar": 1})
    assert rows[0] == "props: unknown prop(s) bar; allowed: header, rows, title, total"
    assert "props.rows[0]: unknown prop(s) foo; allowed: at, label, sub, tone, value" in rows
    assert "props.rows[0].label: 20 characters; at most 14" in rows
    assert L.validate_props(receipt, []) == ["props must be an object"]
    assert L.validate_props(comps["Arrow"], {"label_pos": "middle"}) == [
        "props.label_pos: 'middle' is not one of 'start', 'end'"]
    # Times and asset ids are checked as written: strings and numbers both pass the schema
    assert L.validate_props(comps["Stamp"], {"text": "真香", "at": "line:3+0.2"}) == []
    assert L.validate_props(comps["Stamp"], {"text": "真香", "at": 4.5}) == []
