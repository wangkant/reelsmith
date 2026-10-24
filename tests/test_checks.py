import json
import re
import shutil
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import pydantic
import pytest

from reelsmith import checks as C
from reelsmith.issues import Issue
from reelsmith.profiles import DOUYIN, Box
from reelsmith.workspace import DEFAULT_RULES, default_rules

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
TINY = replace(DOUYIN, name="tiny", width=108, height=192, safe=Box(8, 20, 92, 150), min_s=1, max_s=30,
               target_s=(1, 10), lufs=-16.0, max_still_s=2.0)


def fake_module(monkeypatch, name, **attrs):
    mod = types.ModuleType(f"reelsmith.{name}")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, f"reelsmith.{name}", mod)
    return mod


def clip(cid, typ="image", start=0, dur=60, **kw):
    c = {"id": cid, "type": typ, "track": "v1", "from": start, "dur": dur,
         "box": {"x": 0, "y": 0, "w": 1080, "h": 1920},
         "style": {"opacity": 1}, "keyframes": {}, "enter": None, "exit": None, "content": {}}
    c.update(kw)
    return c


def resolved(clips, seconds=60.0, captions=None):
    tracks = [{"id": "v1", "kind": "visual", "clips": clips}]
    if captions is not None:
        tracks.append({"id": "cap", "kind": "captions", "box": {}, "style": {}, "items": captions})
    return {"version": 2, "fps": 30, "width": 1080, "height": 1920, "durationInFrames": round(seconds * 30),
            "tracks": tracks, "audio": [], "inspect": False}


GOOD_META = {"title": "油价为什么又涨了", "desc": "一句话 #油价", "topic": "油价",
             "sources": [{"title": "示例日报", "url": "https://www.example.org/x"}]}


# ------------------------------------------------------------------ owner rules
def test_rules_pass_on_a_good_post():
    assert C.rule_issues(GOOD_META, default_rules()) == []


def test_title_length_and_numbers():
    meta = dict(GOOD_META, title="2026年油价涨了3.5元，第12次" + "啊" * 10)
    found = C.rule_issues(meta, default_rules())
    msgs = [str(i) for i in found]
    assert any("characters; the owner's limit is 24" in m for m in msgs)
    assert any("3 numbers (2026, 3.5, 12)" in m for m in msgs)
    assert all(i.level == "error" and i.where == "meta.title" for i in found)
    two = dict(GOOD_META, title="油价涨3.5元，一年第12次")
    assert C.rule_issues(two, default_rules()) == []


def test_empty_title_is_only_a_warning():
    found = C.rule_issues(dict(GOOD_META, title=""), default_rules())
    assert [i.level for i in found] == ["warning"]


def test_sources_need_http_urls():
    meta = dict(GOOD_META, sources=[{"title": "x", "url": "ftp://x"}, {"title": "y"}, "z"])
    found = C.rule_issues(meta, default_rules())
    assert [(i.level, i.where) for i in found] == [("error", "meta.sources")]
    rules = default_rules()
    rules["hard"]["min_sources"] = 0
    assert C.rule_issues(meta, rules) == []


def test_banned_words_case_insensitive_in_title_desc_topic():
    rules = default_rules()
    rules["hard"]["banned"] = ["Tesla", ""]
    found = C.rule_issues(dict(GOOD_META, desc="about tesla #car", topic="TESLA"), rules)
    assert len(found) == 1 and found[0].where == "meta.desc/topic" and "'Tesla'" in found[0].msg


# ------------------------------------------------------------------ advice
def text_clip(cid, start=0, dur=60, words="开头一句话"):
    return clip(cid, "text", start, dur, content={"runs": [{"text": words, "accent": False}]})


def test_advice_quiet_on_a_good_film():
    r = resolved([clip("bg", "image", 0, 7 * 30), text_clip("t1", 0, 45)], seconds=60)
    assert C.advice_issues(r, default_rules(), DOUYIN) == []


def test_advice_hook_without_words():
    r = resolved([clip("bg", "image", 0, 7 * 30), text_clip("t1", 90, 30)], seconds=60)
    found = C.advice_issues(r, default_rules(), DOUYIN)
    assert [i.where for i in found] == ["hook"]
    assert all(i.level == "advice" for i in found)
    assert "first 2 s" in found[0].msg


def test_advice_hook_satisfied_by_captions_or_evidence_or_component_words():
    base = [clip("bg", "image", 0, 7 * 30)]
    with_captions = resolved(base, 60, captions=[{"from": 10, "to": 40, "runs": []}])
    assert C.advice_issues(with_captions, default_rules(), DOUYIN) == []
    assert C.advice_issues(resolved(base + [clip("e", "evidence", 30, 30)], 60), default_rules(), DOUYIN) == []
    comp = clip("k", "component", 0, 30, content={"name": "Stamp", "props": {"label": "涨价", "at": 10}})
    assert C.advice_issues(resolved(base + [comp], 60), default_rules(), DOUYIN) == []
    only_asset = clip("k", "component", 0, 30, content={"name": "X", "props": {"asset": {"src": "assets/a.png"}}})
    assert [i.where for i in C.advice_issues(resolved(base + [only_asset], 60), default_rules(), DOUYIN)] == ["hook"]


def test_advice_empty_first_frame():
    r = resolved([text_clip("t1", 15, 30), clip("bg", "image", 15, 30)], seconds=60)
    found = C.advice_issues(r, default_rules(), DOUYIN)
    assert any("empty frame" in i.msg for i in found)


def test_advice_long_single_visual_only_for_still_pictures():
    # video, components and anything keyframed move by themselves
    moving = clip("kb", "image", 0, 12 * 30, keyframes={"zoom": [{"f": 0, "v": 1.02}, {"f": 359, "v": 1.12}]})
    slid = clip("ev", "evidence", 0, 12 * 30, keyframes={"y": [{"f": 0, "v": 620}, {"f": 90, "v": 300}]})
    held = clip("ev2", "evidence", 400, 10 * 30, keyframes={"opacity": [{"f": 0, "v": 1}, {"f": 30, "v": 1}]})
    r = resolved([clip("bg", "image", 0, 9 * 30), text_clip("t1", 0, 20 * 30),
                  clip("s", "shape", 0, 20 * 30), clip("v", "video", 300, 10 * 30),
                  clip("k", "component", 0, 15 * 30, content={"name": "WaterFill", "props": {}}), moving, slid, held],
                 seconds=60)
    found = C.advice_issues(r, default_rules(), DOUYIN)
    assert [i.where for i in found] == ["bg @ 0.0s", "ev2 @ 13.3s"]
    assert "9.0 s" in found[0].msg and "still image" in found[0].msg


# ------------------------------------------------------------------ the cover (frame 0)
def test_cover_whole_words_pass():
    r = resolved([clip("bg", "image", 0, 300), text_clip("hook", 0, 60)])
    assert C.cover_issues(r) == []


def test_cover_mid_reveal_or_enter_warns():
    # frame 0 is the cover: a half-typed hook or evidence still fading in makes a poor one
    reveal = clip("hook", "text", 0, 60, content={"runs": [{"text": "一吨汽油", "accent": False}],
                                                   "reveal": {"mode": "chars", "dur": 0.6}})
    card = clip("card", "evidence", 0, 90, enter={"preset": "fade", "dur": 12})
    fading = clip("k", "component", 0, 90, content={"name": "Stamp", "props": {"label": "涨价"}},
                  keyframes={"opacity": [{"f": 0, "v": 0}, {"f": 10, "v": 1}]})
    found = C.cover_issues(resolved([clip("bg", "image", 0, 300), reveal, card, fading]))
    msgs = {i.where: i.msg for i in found}
    assert set(msgs) == {"hook @ 0.0s", "card @ 0.0s", "k @ 0.0s", "cover"}
    assert all(i.level == "warning" for i in found)
    assert "half-typed" in msgs["hook @ 0.0s"] and "enters (fade)" in msgs["card @ 0.0s"]
    assert "fades in" in msgs["k @ 0.0s"] and "nothing readable" in msgs["cover"]


def test_cover_captions_or_a_whole_clip_are_readable():
    reveal = clip("hook", "text", 0, 60, content={"runs": [{"text": "一吨汽油", "accent": False}],
                                                   "reveal": {"mode": "words", "dur": 0.6}})
    with_caps = resolved([clip("bg", "image", 0, 300), reveal], captions=[{"from": 0, "to": 40, "runs": []}])
    assert [i.where for i in C.cover_issues(with_caps)] == ["hook @ 0.0s"]
    assert C.cover_issues(resolved([text_clip("late", 30, 60)])) == []      # empty frame: the hook advice says it
    pictures = resolved([clip("bg", "image", 0, 300)])
    assert [i.where for i in C.cover_issues(pictures)] == ["cover"]


# ------------------------------------------------------------------ evidence that will read small
def _capture(path: Path, lines: list[tuple[int, int]], size=(1290, 600)) -> Path:
    """A white page with black text-like bars: (top, height) per line, 60..1230 px wide."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    for top, h in lines:
        for x in range(60, 1230, 50):                   # glyph-like blocks with gaps
            d.rectangle((x, top, x + 38, top + h), fill=(20, 20, 20))
    im.save(path)
    return path


def _ev_clip(cid, w, h, ref, typ="evidence"):
    box = {"x": 40, "y": 300, "w": w, "h": h}
    if typ == "evidence":
        return clip(cid, "evidence", 0, 90, box=box, content=ref)
    return clip(cid, "component", 0, 90, box=box, content={"name": "EvidenceCard", "props": {"asset": ref}})


def test_evidence_that_reads_small_warns(tmp_path):
    # a two-line box 1974 px wide in a card comes out ~20 px a character; one line boxed reads fine
    (tmp_path / "assets").mkdir()
    _capture(tmp_path / "assets" / "two.png", [(130, 44), (232, 39)], size=(2058, 615))
    _capture(tmp_path / "assets" / "one.png", [(93, 44)], size=(2058, 615))
    two = {"src": "assets/two.png", "kind": "evidence", "size": [2058, 615], "box": [42, 130, 1974, 204]}
    one = {"src": "assets/one.png", "kind": "evidence", "size": [2058, 615], "box": [392, 93, 723, 51]}
    r = resolved([_ev_clip("card", 820, 330, two, "component"), _ev_clip("k_avg", 840, 150, one),
                  _ev_clip("k_two", 840, 480, two)])
    found = C.evidence_issues(r, tmp_path)
    by = {i.where.split(" @")[0]: i for i in found}
    assert set(by) == {"card", "k_two"}
    assert all(i.level == "warning" for i in found)
    px = int(re.search(r"about (\d+) px", by["card"].msg).group(1))
    assert 12 <= px <= 25 and "shorter" in by["card"].msg and "phone width" in by["card"].msg


def test_evidence_check_skips_what_it_cannot_measure(tmp_path):
    ref = {"src": "assets/none.png", "kind": "evidence", "size": [1000, 500], "box": [0, 0, 1000, 500]}
    assert C.evidence_issues(resolved([_ev_clip("e", 840, 400, ref)]), tmp_path) == []
    ref = {"src": "assets/none.png", "kind": "evidence", "size": [1000, 500], "box": None}
    assert C.evidence_issues(resolved([_ev_clip("e", 840, 400, ref)]), tmp_path) == []


def test_advice_duration_target_from_rules_or_profile():
    r = resolved([clip("bg", "image", 0, 7 * 30), text_clip("t1")], seconds=30)
    found = C.advice_issues(r, default_rules(), DOUYIN)
    assert [i.where for i in found] == ["duration"] and "45-75" in found[0].msg
    rules = default_rules()
    rules["advice"]["target_s"] = [20, 40]
    assert C.advice_issues(r, rules, DOUYIN) == []


def test_duration_outside_platform_limits_is_an_error():
    assert C.duration_issues(resolved([], seconds=12), DOUYIN)[0].level == "error"
    assert C.duration_issues(resolved([], seconds=95), DOUYIN)[0].level == "error"
    assert C.duration_issues(resolved([], seconds=50), DOUYIN) == []


# ------------------------------------------------------------------ check_project with fake neighbours
@pytest.fixture
def project(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    (p / "project.json").write_text(json.dumps({"version": 2, "meta": GOOD_META}), encoding="utf-8")
    return p


def fake_doc(monkeypatch, meta=None, issues=(), load_exc=None):
    def load(project):
        if load_exc:
            raise load_exc
        return types.SimpleNamespace(meta=dict(meta or GOOD_META))
    return fake_module(monkeypatch, "document", load=load, validate=lambda project, doc: list(issues))


def test_check_project_missing_file(monkeypatch, project):
    fake_doc(monkeypatch, load_exc=FileNotFoundError("project.json"))
    found = C.check_project(project)
    assert len(found) == 1 and found[0].level == "error" and "not found" in found[0].msg


def test_check_project_pydantic_errors_one_per_line(monkeypatch, project):
    class M(pydantic.BaseModel):
        version: int
        tracks: list

    try:
        M.model_validate({"version": "x"})
    except pydantic.ValidationError as exc:
        err = exc
    fake_doc(monkeypatch, load_exc=err)
    msgs = [i.msg for i in C.check_project(project)]
    assert len(msgs) == 2 and msgs[0].startswith("version:") and msgs[1].startswith("tracks:")


def test_check_project_validation_errors_skip_advice(monkeypatch, project):
    fake_doc(monkeypatch, issues=[Issue("error", "tracks[0].clips[1]", "overlaps c1"), Issue("warning", "x", "w")])

    def boom(project):
        raise AssertionError("resolve must not run on an invalid project")
    fake_module(monkeypatch, "resolve", resolve=boom)
    found = C.check_project(project)
    assert [i.level for i in found] == ["error", "warning"]


def test_check_project_full(monkeypatch, project):
    fake_doc(monkeypatch, meta=dict(GOOD_META, title="一二三四五六七八九十一二三四五六七八九十一二三四五"))
    fake_module(monkeypatch, "resolve", resolve=lambda p: resolved([clip("bg", "image", 30, 300)], seconds=15))
    found = C.check_project(project)
    levels = [i.level for i in found]
    assert levels == sorted(levels, key=C.LEVEL_ORDER.get)
    wheres = {(i.level, i.where) for i in found}
    assert ("error", "meta.title") in wheres
    assert ("error", "duration") in wheres                  # 15 s: douyin takes 20-90
    assert ("advice", "hook") in wheres
    assert ("advice", "bg @ 1.0s") in wheres


def test_check_project_resolve_failure_is_an_error(monkeypatch, project):
    fake_doc(monkeypatch)

    def bad(p):
        raise ValueError("clip:a -> clip:b -> clip:a is a cycle")
    fake_module(monkeypatch, "resolve", resolve=bad)
    found = C.check_project(project)
    assert [(i.level, i.where) for i in found] == [("error", "resolve")] and "cycle" in found[0].msg


def test_check_project_bad_rules_file(monkeypatch, tmp_path):
    (tmp_path / "workspace.json").write_text("{}", encoding="utf-8")
    (tmp_path / "rules.json").write_text("{oops", encoding="utf-8")
    p = tmp_path / "projects" / "a"
    p.mkdir(parents=True)
    found = C.check_project(p)
    assert found[0].where == "workspace" and "rules.json" in found[0].msg


def test_check_project_uses_workspace_rules(monkeypatch, tmp_path):
    (tmp_path / "workspace.json").write_text("{}", encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps({"hard": {"banned": ["油价"]}}), encoding="utf-8")
    p = tmp_path / "projects" / "a"
    p.mkdir(parents=True)
    fake_doc(monkeypatch)
    fake_module(monkeypatch, "resolve", resolve=lambda p: resolved([clip("bg", "image", 0, 200), text_clip("t")], 50))
    found = C.check_project(p)
    assert [i.msg for i in found if i.level == "error"] == ["contains the banned word '油价': reword it"]


# ------------------------------------------------------------------ layout
def frame(f, *items):
    return {"frame": f, "png": f"f{f}.png", "items": list(items)}


def text(cid, rect, opacity=1.0, words="几个字"):
    return {"clip": cid, "track": "v1", "kind": "text", "rect": rect, "opacity": opacity, "text": words}


def box(cid, rect):
    return {"clip": cid, "track": "v1", "kind": "clip", "rect": rect, "opacity": 1.0}


def test_layout_clean():
    ins = {"frames": [frame(0, box("t1", [40, 300, 840, 400]), text("t1", [60, 320, 700, 200]))]}
    assert C.check_layout(ins, DOUYIN) == []


def test_layout_outside_safe_area_aggregated_per_clip():
    top = [100, 120, 600, 90]                       # safe area starts at y 220: 100 px out
    ins = {"frames": [frame(30, text("title", top)), frame(60, text("title", top)),
                      frame(90, text("ok", [100, 400, 50, 50]))]}
    found = C.check_layout(ins, DOUYIN)
    assert len(found) == 1
    i = found[0]
    assert i.level == "error" and i.where == "title @ 1.0s"
    assert "100 px outside the safe area (top)" in i.msg and "also at 2.0s" in i.msg and "几个字" in i.msg


def test_layout_right_rail_and_cut_edge_and_overflow():
    ins = {"frames": [frame(0,
                            text("rail", [700, 900, 300, 60]),                  # x 1000 > 880
                            box("big", [40, 600, 500, 200]), text("big", [40, 600, 1100, 120], words="很长很长的一行"),
                            )]}
    found = {(i.where.split(" @")[0], i.level): i.msg for i in C.check_layout(ins, DOUYIN)}
    assert "outside the safe area (right)" in found[("rail", "error")]
    assert "cut by the canvas edge (right" in found[("big", "error")]
    assert "overflows its clip box" in found[("big", "warning")]


def test_layout_ignores_faint_offcanvas_and_small_overhang():
    ins = {"frames": [frame(0,
                            text("faint", [0, 0, 300, 60], opacity=0.05),
                            text("gone", [-900, 300, 400, 60]),                  # wholly off canvas
                            text("edge", [40, 214, 400, 100]),                   # 6 px above the safe top: line box
                            )]}
    assert C.check_layout(ins, DOUYIN) == []


def test_layout_captions_track_items_use_track_id():
    ins = {"frames": [frame(0, {"clip": None, "track": "cap", "kind": "text", "rect": [40, 1500, 600, 80],
                                "opacity": 1, "text": "字幕"})]}
    found = C.check_layout(ins, DOUYIN)
    assert found[0].where == "cap @ 0.0s" and "(bottom)" in found[0].msg


def test_layout_skips_enter_exit_animations_when_resolved_given():
    r = resolved([clip("t1", "text", 0, 90, enter={"preset": "rise", "dur": 12}, exit={"preset": "fade", "dur": 12})])
    out = [100, 120, 600, 90]
    ins = {"frames": [frame(5, text("t1", out)), frame(85, text("t1", out))]}
    assert C.check_layout(ins, DOUYIN, r) == []
    ins["frames"].append(frame(40, text("t1", out)))
    assert len(C.check_layout(ins, DOUYIN, r)) == 1


def test_layout_small_and_tiny_text():
    # inspect gives each text's computed font size
    ins = {"frames": [frame(0, text("ok", [100, 400, 300, 60]) | {"size": 44},
                            text("receipt", [100, 600, 300, 30], words="小字") | {"size": 24},
                            text("receipt", [100, 640, 300, 20], words="更小") | {"size": 11.3},
                            text("tag", [100, 800, 300, 30]) | {"size": 26}),
                      frame(30, text("tag", [100, 800, 300, 30]) | {"size": 22})]}
    found = {(i.where, i.level): i.msg for i in C.check_layout(ins, DOUYIN)}
    assert set(found) == {("receipt @ 0.0s", "error"), ("receipt @ 0.0s", "warning"), ("tag @ 0.0s", "warning")}
    assert "\"更小\" is 11.3 px" in found[("receipt @ 0.0s", "error")] and "refuses under 20" in \
        found[("receipt @ 0.0s", "error")]
    assert "is 22 px (also at 1.0s)" in found[("tag @ 0.0s", "warning")]          # the worst size is quoted


def test_layout_text_over_text_names_both():
    cap = {"clip": "cap", "track": "cap", "kind": "text", "rect": [160, 1300, 600, 80], "opacity": 1, "text": "字幕"}
    ins = {"frames": [frame(30, text("body", [100, 1260, 700, 120], words="正文"), dict(cap),
                            text("title", [100, 300, 700, 100]), text("sub", [100, 396, 700, 80]))]}
    found = [i for i in C.check_layout(ins, DOUYIN)]
    assert [(i.level, i.where) for i in found] == [("warning", "body @ 1.0s")]       # touching line boxes pass
    assert "\"正文\" overlaps text \"字幕\" of cap" in found[0].msg
    faint = dict(text("body", [100, 1260, 700, 120]), opacity=0.2)                    # a backdrop, not a collision
    assert C.check_layout({"frames": [frame(0, faint, dict(cap))]}, DOUYIN) == []


def _still(path: Path, ground, patches=()) -> str:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1080, 1920), ground)
    d = ImageDraw.Draw(im)
    for (x, y, w, h), fill in patches:
        for gx in range(int(x), int(x + w), 40):            # glyph-like strokes in the text's colour
            d.rectangle((gx, y + 10, gx + 22, y + h - 10), fill=fill)
    im.save(path)
    return str(path)


def test_layout_low_contrast_sampled_from_the_still(tmp_path):
    # text with no colour set is ink on the night ground: invisible, though its layout is fine
    ink, night, snow, red = (30, 26, 22), (22, 19, 15), (247, 241, 230), (200, 55, 45)
    png = _still(tmp_path / "s.png", night, [((100, 400, 600, 80), ink), ((100, 700, 600, 80), snow),
                                             ((100, 1000, 600, 80), red)])
    ins = {"frames": [{"frame": 0, "png": png, "items": [
        text("lost", [100, 400, 600, 80]) | {"color": "rgb(30, 26, 22)"},
        text("white", [100, 700, 600, 80]) | {"color": "rgb(247, 241, 230)"},
        text("red", [100, 1000, 600, 80]) | {"color": "rgb(200, 55, 45)"},             # a saturated accent reads
        text("fading", [100, 400, 600, 80]) | {"color": "rgb(30, 26, 22)", "opacity": 0.3}]}]}
    found = C.check_layout(ins, DOUYIN)
    assert [(i.level, i.where) for i in found] == [("warning", "lost @ 0.0s")]
    assert "contrast 1.1:1" in found[0].msg and "#" in found[0].msg
    gold_on_paper = _still(tmp_path / "p.png", (243, 235, 221), [((100, 400, 600, 80), (217, 164, 65))])
    ins = {"frames": [{"frame": 0, "png": gold_on_paper,
                       "items": [text("gold", [100, 400, 600, 80]) | {"color": "rgb(217, 164, 65)"}]}]}
    assert [i.where for i in C.check_layout(ins, DOUYIN)] == ["gold @ 0.0s"]


def test_contrast_helpers():
    assert C.parse_color("rgb(255, 255, 255)") == (255, 255, 255, 1.0)
    assert C.parse_color("rgba(0, 0, 0, 0.5)") == (0, 0, 0, 0.5)
    assert C.parse_color("#C8372D")[:3] == (200, 55, 45) and C.parse_color("var(--x)") is None
    assert C.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert C.hard_to_read(1.1, 5) and not C.hard_to_read(2.6, 70) and C.hard_to_read(1.9, 70)


def test_layout_ignores_given_clips():
    ins = {"frames": [frame(0, text("crashed", [0, 0, 300, 30]) | {"size": 26})]}
    assert C.check_layout(ins, DOUYIN, ignore={"crashed"}) == []
    assert len(C.check_layout(ins, DOUYIN)) == 2


def test_layout_tolerates_junk():
    assert C.check_layout({}, DOUYIN) == []
    assert C.check_layout({"frames": [{"frame": 0, "items": [{"kind": "text", "rect": "x"}, {"kind": "text"}]}]},
                          DOUYIN) == []


# ------------------------------------------------------------------ film
def make_film(path: Path, seconds=3, size="108x192", rate=30, audio=True, still=False, vcodec="libx264"):
    src = f"color=c=0x3366aa:s={size}:r={rate}:d={seconds}" if still else f"testsrc2=s={size}:r={rate}:d={seconds}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", vcodec, "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@needs_ffmpeg
def test_check_film_passes(tmp_path):
    res = C.check_film(make_film(tmp_path / "f.mp4"), TINY)
    assert res["ok"], res["problems"]
    assert (res["width"], res["height"], res["fps"], res["vcodec"], res["acodec"]) == (108, 192, 30, "h264", "aac")
    assert res["duration_s"] == pytest.approx(3, abs=0.1)
    assert res["lufs"] is not None and res["black_s"] == 0
    assert any("mastered for -16" in n for n in res["notes"])      # an unmastered sine sits far from the target


@needs_ffmpeg
def test_check_film_problems(tmp_path):
    res = C.check_film(make_film(tmp_path / "f.mp4", rate=25, audio=False, size="120x200"), TINY)
    text = " | ".join(res["problems"])
    assert not res["ok"]
    assert "25 fps; want 30" in text and "120x200; want 108x192" in text and "no audio stream" in text


@needs_ffmpeg
def test_check_film_still_picture_fails(tmp_path):
    res = C.check_film(make_film(tmp_path / "f.mp4", seconds=4, still=True), TINY)
    assert not res["ok"] and any("without any motion" in p for p in res["problems"])


@needs_ffmpeg
def test_check_film_codec(tmp_path):
    res = C.check_film(make_film(tmp_path / "f.mp4", vcodec="mpeg4"), TINY)
    assert any("video codec mpeg4; want h264" in p for p in res["problems"])


def test_check_film_missing(tmp_path):
    res = C.check_film(tmp_path / "none.mp4", TINY)
    assert not res["ok"] and res["why"].startswith("no film at")


def test_defaults_are_not_shared():
    r = default_rules()
    r["hard"]["banned"].append("x")
    assert DEFAULT_RULES["hard"]["banned"] == []


def test_douyin_long_keeps_the_screen_and_allows_longer_films():
    from reelsmith.profiles import DOUYIN_LONG, get_profile
    assert get_profile("douyin-long") is DOUYIN_LONG
    assert (DOUYIN_LONG.safe, DOUYIN_LONG.captions, DOUYIN_LONG.lufs) == (DOUYIN.safe, DOUYIN.captions, DOUYIN.lufs)
    assert DOUYIN_LONG.max_s == 300 and DOUYIN_LONG.target_s == (90, 180) and DOUYIN_LONG.max_mb == 250
