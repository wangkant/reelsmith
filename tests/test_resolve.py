import json
import math
import re
import shutil
import struct
from pathlib import Path

import pytest

from reelsmith import document as D
from reelsmith import resolve as R
from reelsmith import timeexpr as T
from reelsmith import tools

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "demo"
TYPES_TS = (ROOT / "renderer" / "src" / "types.ts").read_text(encoding="utf-8")
needs_ffprobe = pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe not on PATH")


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "demo"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    return p


@pytest.fixture
def resolved(demo):
    return R.resolve(demo)


def raw(p):
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


def write(p, data):
    (p / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def rclip(resolved, cid):
    return next(c for t in resolved["tracks"] for c in t.get("clips") or [] if c["id"] == cid)


def rtrack(resolved, tid):
    return next(t for t in resolved["tracks"] if t["id"] == tid)


def ts_fields(name: str) -> set[str]:
    """Field names of `export type <name> = { ... }` in renderer/src/types.ts (nested object types skipped)."""
    m = re.search(rf"export type {name} = \{{(.*?)\n?\}};", TYPES_TS, re.S)
    assert m, f"{name} not found in types.ts"
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", m.group(1), flags=re.S)
    while re.search(r"\{[^{}]*\}", body):
        body = re.sub(r"\{[^{}]*\}", "", body)
    return set(re.findall(r"(\w+)\??\s*:", body))


# ------------------------------------------------------------------ shape vs types.ts
def test_top_level_matches_types_ts(resolved):
    assert set(resolved) == ts_fields("Resolved")
    assert resolved["version"] == 2 and resolved["fps"] == 30 and (resolved["width"], resolved["height"]) == (1080, 1920)
    assert resolved["durationInFrames"] == 654                       # (21.2 + 0.6) * 30
    assert resolved["safe"] == {"x": 40, "y": 220, "w": 840, "h": 1240}
    assert set(resolved["theme"]) <= ts_fields("Theme") and resolved["theme"]["accent"] == "#C8372D"
    assert resolved["inspect"] is False
    json.dumps(resolved, allow_nan=False)                            # plain JSON, no NaN


def test_tracks_and_clips_match_types_ts(resolved):
    kinds = {t["id"]: t["kind"] for t in resolved["tracks"]}
    assert kinds == {"bg": "visual", "mid": "visual", "fg": "visual", "notes": "visual", "music": "audio",
                     "cap": "captions"}
    assert set(rtrack(resolved, "bg")) == ts_fields("VisualTrack")
    assert set(rtrack(resolved, "cap")) == ts_fields("CaptionTrack")
    assert set(rtrack(resolved, "music")) == {"id", "kind", "hidden"}
    assert rtrack(resolved, "notes")["hidden"] is True
    content = {"image": "ImageContent", "video": "VideoContent", "text": "TextContent", "shape": "ShapeContent",
               "evidence": "EvidenceContent", "component": "ComponentContent"}
    seen = set()
    for t in resolved["tracks"]:
        for c in t.get("clips") or []:
            assert set(c) == ts_fields("RClip"), c["id"]
            assert set(c["box"]) == ts_fields("Box")
            assert set(c["style"]) <= ts_fields("ClipStyle")
            assert set(c["keyframes"]) <= set(D.KEYFRAME_PROPS)
            for frames in c["keyframes"].values():
                assert all(set(k) == ts_fields("Keyframe") and isinstance(k["f"], int) for k in frames)
            for tr in (c["enter"], c["exit"]):
                assert tr is None or set(tr) == ts_fields("Transition")
            assert set(c["content"]) <= ts_fields(content[c["type"]]), c["id"]
            seen.add(c["type"])
    assert seen == set(content)
    for item in rtrack(resolved, "cap")["items"]:
        assert set(item) == ts_fields("CaptionItem")
        assert all(set(r) == ts_fields("Run") for r in item["runs"])
    for a in resolved["audio"]:
        optional = {"volumeKeys", "duck"}                               # only when the clip has them
        assert set(a) - optional == ts_fields("AudioItem") - optional    # loop included


def test_text_style_and_nested_shapes_match_types_ts(resolved):
    style = rclip(resolved, "hook")["content"]["style"]
    assert set(style) == ts_fields("TextStyle")
    assert set(rclip(resolved, "hook")["content"]["reveal"]) == ts_fields("Reveal")
    assert set(rclip(resolved, "proof")["content"]["highlight"]) == ts_fields("Highlight")
    ref = rclip(resolved, "count")["content"]["props"]
    assert isinstance(ref["at"], int)


# ------------------------------------------------------------------ units and values
def test_frames_units_and_media_facts(resolved):
    open_ = rclip(resolved, "open")
    assert (open_["from"], open_["dur"]) == (0, 169)                 # line:3 at 5.62 s
    assert open_["content"] == {"src": "assets/photo.png", "size": [270, 480], "fit": "cover", "focus": None}
    proof = rclip(resolved, "proof")
    assert (proof["from"], proof["dur"]) == (349, 108)
    assert proof["enter"] == {"preset": "rise", "dur": 12}           # 0.4 s
    assert proof["content"]["highlight"] == {"at": 24, "dur": 24, "color": None}   # line:5+0.8, 0.8 s
    assert proof["content"]["box"] == [40, 420, 460, 50] and proof["content"]["site"] == "example.com"
    assert proof["content"]["size"] == [540, 900]
    assert proof["style"]["radius"] == 16 and proof["style"]["shadow"] is True
    hook = rclip(resolved, "hook")
    assert hook["content"]["reveal"] == {"mode": "chars", "dur": 0.6}          # seconds, as the renderer reads it
    assert hook["keyframes"]["scale"] == [{"f": 0, "v": 0.92, "ease": "linear"}, {"f": 15, "v": 1, "ease": "spring"}]
    ring = rclip(resolved, "ring")
    assert ring["keyframes"]["progress"] == [{"f": 12, "v": 0, "ease": "linear"},          # 0.4 s from its start
                                             {"f": 36, "v": 1, "ease": "out"}]             # line:6+1.2 absolute
    assert rclip(resolved, "shop")["style"]["filter"] == {"brightness": 0.7}


@needs_ffprobe
def test_video_and_audio_durations(resolved):
    shop = rclip(resolved, "shop")["content"]
    assert shop["duration"] == pytest.approx(2.0, abs=0.05) and shop["trimIn"] == 15 and shop["loop"] is True
    assert shop["volume"] == 0 and shop["rate"] == 1
    voice, bed = resolved["audio"]
    assert voice == {"id": "voice", "src": "voice/voice.wav", "from": 0, "dur": 636, "trimIn": 0, "volume": 1,
                     "fadeIn": 0, "fadeOut": 0, "loop": False}
    assert bed == {"id": "bed1", "src": "assets/bed.wav", "from": 0, "dur": 60, "trimIn": 0, "volume": 0.1,
                   "fadeIn": 0, "fadeOut": 15, "loop": False}


def test_text_runs_and_defaults(resolved):
    hook = rclip(resolved, "hook")["content"]
    assert hook["runs"] == [{"text": "一杯奶茶，", "accent": False}, {"text": "成本多少", "accent": True},
                            {"text": "？", "accent": False}]
    s = hook["style"]
    assert s["size"] == "fit" and s["max_size"] == 130 and s["weight"] == 900 and s["color"] == "#FFFFFF"
    assert s["stroke"] == {"color": "#000", "width": 6}
    assert s["font"] == "sans" and s["min_size"] == 28 and s["align"] == "left" and s["bg"] is None
    todo = rclip(resolved, "todo")["content"]["style"]
    assert todo == R.TEXT_DEFAULTS


def test_text_style_null_means_none_for_nullable_keys():
    st = D.TextStyle.model_validate({"stroke": None, "size": None, "color": None})
    out = R.text_style(st)
    assert out["stroke"] is None and out["color"] is None and out["size"] == 64
    assert R.caption_style(D.TextStyle.model_validate({"size": None, "bg": None, "weight": 800})) == {
        "bg": None, "weight": 800}
    assert R.caption_style(None) is None


def test_component_props_get_frames_and_asset_refs(demo):
    data = raw(demo)
    data["tracks"].append({"id": "cards", "kind": "visual", "clips": [
        {"id": "card", "type": "component", "name": "EvidenceCard", "start": "line:6", "end": "line:7",
         "props": {"asset": "ev", "highlight_at": "line:6+0.5", "source": "来源"}}]})
    bill = data["tracks"][1]["clips"][0]
    bill["props"]["rows"][0]["at"] = 0.4                               # seconds from the clip's start
    write(demo, data)
    r = R.resolve(demo)
    props = rclip(r, "card")["content"]["props"]
    assert props["highlight_at"] == 15 and props["source"] == "来源"
    assert props["asset"] == {"src": "assets/evidence.png", "kind": "evidence", "size": [540, 900],
                              "box": [40, 420, 460, 50], "site": "example.com"}
    rows = rclip(r, "bill")["content"]["props"]["rows"]
    assert rows[0]["at"] == 12 and rows[1]["at"] == 247 - 169
    assert rclip(r, "bill")["content"]["props"]["total"]["at"] == 342 - 169       # line:4.end at 11.40 s


def test_motion_becomes_keyframes_and_explicit_keyframes_win(demo):
    data = raw(demo)
    open_ = data["tracks"][0]["clips"][0]
    open_["motion"] = "pan_left"
    open_["box"] = {"x": 0, "y": 0, "w": 1000, "h": 1600}
    close = data["tracks"][0]["clips"][2]
    close["keyframes"] = {"zoom": [{"t": 0, "v": 1.3}]}
    write(demo, data)
    r = R.resolve(demo)
    k = rclip(r, "open")["keyframes"]
    assert k["zoom"] == [{"f": 0, "v": 1.14, "ease": "linear"}]
    assert k["pan_x"] == [{"f": 0, "v": 34, "ease": "linear"}, {"f": 168, "v": -34, "ease": "linear"}]
    assert rclip(r, "close")["keyframes"] == {"zoom": [{"f": 0, "v": 1.3, "ease": "linear"}]}
    assert R.motion_keyframes("still", 3, 100, 100) == {} and R.motion_keyframes(None, 3, 100, 100) == {}
    assert R.motion_keyframes("rise", 2, 100, 1000)["pan_y"][1] == {"t": 2, "v": -22.0, "ease": "linear"}


def test_boxes_full_safe_and_hidden_audio_tracks(demo):
    data = raw(demo)
    data["tracks"][1]["clips"][1]["box"] = "safe"
    data["tracks"][-1]["box"] = "safe"
    data["tracks"][-2]["hidden"] = True                                  # music
    write(demo, data)
    r = R.resolve(demo)
    assert rclip(r, "proof")["box"] == {"x": 40, "y": 220, "w": 840, "h": 1240}
    assert rtrack(r, "cap")["box"] == {"x": 40, "y": 220, "w": 840, "h": 1240}
    assert [a["id"] for a in r["audio"]] == ["voice"]


def test_resolve_writes_build_resolved_json(demo, resolved):
    on_disk = json.loads((demo / "build" / "resolved.json").read_text(encoding="utf-8"))
    assert on_disk == resolved


def test_resolve_skips_untimed_clips_and_refuses_without_length(demo):
    data = raw(demo)
    data["tracks"][2]["clips"][1]["start"] = "line:99"
    write(demo, data)
    r = R.resolve(demo)
    assert "arrow" not in [c["id"] for c in rtrack(r, "fg")["clips"]]
    data["voice"] = None
    data["duration"] = "line:2"
    write(demo, data)
    with pytest.raises(R.ResolveError, match="the film's length"):
        R.resolve(demo)
    data["duration"] = 10
    data["profile"] = "vine"
    write(demo, data)
    with pytest.raises(R.ResolveError, match="unknown profile"):
        R.resolve(demo)


def test_theme_from_workspace_and_project(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "projects" / "t"
    p.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"theme": {"accent": "#111111", "gold": "#222222"}}),
                                       encoding="utf-8")
    write(p, {"version": 2, "theme": {"name": "night", "gold": "#333333"}, "duration": 20,
              "tracks": [{"id": "v", "kind": "visual", "clips": [
                  {"id": "t", "type": "text", "text": "x", "start": 0, "dur": 20}]}]})
    theme = R.resolve(p)["theme"]
    assert theme["name"] == "night" and theme["accent"] == "#111111" and theme["gold"] == "#333333"
    assert theme["paper"] == "#E9EEF3"                                   # the night base


# ------------------------------------------------------------------ captions
def chars(text, max_chars=14):
    """phrases() on the character fallback (what runs without node)."""
    return R.phrases(text, max_chars, R.char_words(text))


def test_phrases_keep_words_whole():
    assert R.phrases("一杯十八块的奶茶，成本到底多少钱？") == ["一杯十八块的奶茶", "成本到底多少钱"]
    assert R.phrases("好，我们走吧。") == ["好我们走吧"]                      # short parts merge forward
    assert chars("甲乙丙丁戊己庚辛壬癸甲乙丙丁戊己庚辛壬癸") == ["甲乙丙丁戊己庚辛壬癸", "甲乙丙丁戊己庚辛壬癸"]
    assert [len(p) for p in chars("嗯" * 40)] == [14, 13, 13]         # over 2x max: cut at max, then halves
    assert R.phrases("大约2.5元，涨了3.1%。") == ["大约2.5元", "涨了3.1%"]    # decimals are not breaks
    assert R.phrases("AI, GPT") == ["AI GPT"]                          # Latin parts keep a space
    assert R.phrases("") == [] and R.phrases("，。") == []
    assert chars("甲乙丙丁戊己", max_chars=4) == ["甲乙丙", "丁戊己"]


def test_phrase_cut_avoids_latin_words_and_numbers():
    assert R.phrases("这台手机叫做iPhone15ProMax价格很贵") == ["这台手机叫做", "iPhone15ProMax", "价格很贵"]
    assert chars("甲乙丙丁戊己庚辛壬癸甲乙丙iPhone15Pro") == ["甲乙丙丁戊己庚辛壬癸甲乙丙", "iPhone15Pro"]
    assert chars("一二三四五六七八九十一二三四五六七八九十") == ["一二三四五六七八九十一二三四五六七八九十"]   # one number


# texts a naive splitter cuts mid-word, and where the cut goes
MIDWORD_LINES = {
    "按92号汽油密度0.725换算": ["按92号汽油", "密度0.725换算"],
    "全国居民人均可支配收入34230元": ["全国居民人均可支配", "收入34230元"],
    "原来税后只剩九千三百七十一块钱": ["原来税后只剩", "九千三百七十一块钱"],
    "他说：“这不对。”然后走了": ["他说“这不对”", "然后走了"],
    "iPhone 17 Pro 售价 8999 元": ["iPhone 17 Pro", "售价 8999 元"],
}


@pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")
def test_captions_cut_between_words_with_the_segmenter():
    for text, want in MIDWORD_LINES.items():
        assert R.phrases(text) == want, text
    assert R.phrases("国家统计局发布的数据显示城乡居民收入差距继续缩小") == ["国家统计局发布的数据显示",
                                                                         "城乡居民收入差距继续缩小"]
    assert R.phrases("真正的大头，是房租和人工，占了六成。") == ["真正的大头", "是房租和人工", "占了六成"]


def test_captions_fallback_keeps_numbers_units_and_quotes_together():
    out = {text: chars(text) for text in MIDWORD_LINES}
    assert out["按92号汽油密度0.725换算"] == ["按92号汽油密度", "0.725换算"]
    assert out["全国居民人均可支配收入34230元"] == ["全国居民人均可支配收入", "34230元"]
    assert out["原来税后只剩九千三百七十一块钱"] == ["原来税后只剩", "九千三百七十一块钱"]
    assert out["他说：“这不对。”然后走了"] == ["他说“这不对”", "然后走了"]
    assert out["iPhone 17 Pro 售价 8999 元"] == ["iPhone 17 Pro", "售价 8999 元"]
    for phrases in out.values():
        assert all(p == p.strip() for p in phrases)                     # no trailing spaces
    assert chars("（一）甲乙丙丁戊己庚辛壬癸甲乙丙丁「戊己」", max_chars=8)[-1].endswith("「戊己」")


def test_segment_script_gives_code_point_lengths():
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    words = R._node_words(["iPhone 17 Pro 售价 8999 元", "😀表情", ""])
    assert words == [[6, 1, 2, 1, 3, 1, 2, 1, 4, 1, 1], [1, 2], []]


def test_one_segmenter_call_per_resolve_then_the_cache(demo, monkeypatch):
    calls = []
    real = R._node_words

    def counting(texts, locale="en"):
        calls.append(list(texts))
        return real(texts, locale) if shutil.which("node") else [R.char_words(t) for t in texts]
    monkeypatch.setattr(R, "_node_words", counting)
    monkeypatch.setattr(R, "_WORDS", {})
    R.resolve(demo)
    assert len(calls) == 1 and len(calls[0]) == 7                     # every voice line in one call
    assert (demo / "build" / "segments.json").is_file()
    monkeypatch.setattr(R, "_WORDS", {})                               # a new process: the project's cache answers
    R.resolve(demo)
    R.describe(demo)
    assert len(calls) == 1
    data = raw(demo)
    data["tracks"][-1]["overrides"].append({"line": 5, "text": "真正的大头是房租和人工"})
    write(demo, data)
    R.resolve(demo)
    assert len(calls) == 2 and calls[1] == ["真正的大头是房租和人工"]       # only the changed line
    (demo / "build" / "segments.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(R, "_WORDS", {})
    assert rtrack(R.resolve(demo), "cap")["items"] and len(calls) == 3   # a broken cache is just a miss


def test_captions_without_node_use_the_fallback(demo, monkeypatch):
    monkeypatch.setattr(R, "_node_words", lambda texts, locale="en": None)
    monkeypatch.setattr(R, "_WORDS", {})
    items = rtrack(R.resolve(demo), "cap")["items"]
    assert ["".join(r["text"] for r in it["runs"]) for it in items][:3] == ["一杯十八块的奶茶", "成本到底多少钱",
                                                                           "我们把账单拆开来算"]
    assert not (demo / "build" / "segments.json").exists()               # a fallback answer is not cached


def test_voice_captions_timing_accents_and_overrides(resolved):
    items = rtrack(resolved, "cap")["items"]
    assert items[0] == {"from": 0, "to": 51, "runs": [{"text": "一杯十八块的奶茶", "accent": False}]}
    assert items[1]["runs"] == [{"text": "成本", "accent": True}, {"text": "到底多少钱", "accent": False}]
    assert items[1]["to"] == items[2]["from"]                          # held until the next phrase
    three = [it for it in items if 169 <= it["from"] < 240]
    assert ["".join(r["text"] for r in it["runs"]) for it in three] == ["茶底加奶", "大约2.5元"]
    assert three[1]["runs"] == [{"text": "大约", "accent": False}, {"text": "2.5元", "accent": True}]
    assert all(a["to"] > a["from"] for a in items)
    # 8 characters of 15 in a line from 0.00 to 3.20 s
    assert items[0]["to"] == round(3.2 * 8 / 15 * 30)


def test_given_caption_items(demo):
    data = raw(demo)
    data["tracks"][-1] = {"id": "cap", "kind": "captions", "emphasis": ["账单"],
                          "items": [{"start": "line:2", "end": "line:2.end", "text": "看**账单**"},
                                    {"start": 9, "end": 8, "text": "dropped"}]}
    write(demo, data)
    items = rtrack(R.resolve(demo), "cap")["items"]
    assert items == [{"from": 103, "to": 162, "runs": [{"text": "看", "accent": False},
                                                         {"text": "账单", "accent": True}]}]


def test_text_runs():
    assert R.text_runs("a **b** c", ["c"]) == [{"text": "a ", "accent": False}, {"text": "b", "accent": True},
                                                {"text": " ", "accent": False}, {"text": "c", "accent": True}]
    assert R.text_runs("") == []


# ------------------------------------------------------------------ keyframe math (renderer parity)
REMOTION_SPRING = {(15, 1): 0.15871246303671604, (15, 3.5): 0.9114936958488379, (15, 5): 1.1142207672588351,
                   (15, 8): 1.0637509867754837, (15, 14): 0.9922992575177184, (40, 1): 0.026163685117604585,
                   (40, 12): 1.0729397764115731, (40, 30): 0.9819095100394232}


def test_spring_matches_remotion():
    for (length, t), want in REMOTION_SPRING.items():          # spring({frame: t, fps: 30, config, durationInFrames})
        assert R.spring_at(t, length, 30) == pytest.approx(want, abs=1e-12)
    assert R.ease_at("spring", 0, 15, 30) == 0 and R.ease_at("spring", 15, 15, 30) == 1


def test_eases_match_remotion_easing():
    assert R.ease_at("in", 3, 10, 30) == pytest.approx(0.027)
    assert R.ease_at("out", 3, 10, 30) == pytest.approx(0.657)
    assert R.ease_at("inOut", 3, 10, 30) == pytest.approx(0.108)
    assert R.ease_at("inOut", 7, 10, 30) == pytest.approx(0.892)
    assert R.ease_at(None, 5, 10, 30) == 0.5 and R.ease_at("linear", 12, 10, 30) == 1
    assert R.ease_at("step", 9, 10, 30) == 0 and R.ease_at("step", 10, 10, 30) == 1
    assert R.ease_at("out", 5, 0, 30) == 1


def test_value_at_holds_outside_and_eases_into_keys():
    ks = [{"f": 30, "v": 10.0, "ease": None}, {"f": 10, "v": 0.0, "ease": "spring"}, {"f": 20, "v": 5.0, "ease": "in"}]
    assert R.value_at(ks, 0, 30) == 0 and R.value_at(ks, 99, 30) == 10
    assert R.value_at(ks, 15, 30) == pytest.approx(5 * 0.5 ** 3)        # into the key at 20, eased "in"
    assert R.value_at(ks, 25, 30) == pytest.approx(7.5)                 # into the key at 30: linear
    assert R.value_at([], 5, 30) is None
    assert R.value_at([{"f": 0, "v": math.nan}], 5, 30) is None


# ------------------------------------------------------------------ media headers
def test_image_sizes_from_headers(tmp_path):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a" + struct.pack("<HH", 33, 44) + b"\x00" * 20)
    assert R.image_size(gif) == (33, 44)
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
                    + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 600, 800) + b"\x00" * 12)
    assert R.image_size(jpg) == (800, 600)
    vp8x = tmp_path / "x.webp"
    vp8x.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 8 + (639).to_bytes(3, "little")
                     + (479).to_bytes(3, "little"))
    assert R.image_size(vp8x) == (640, 480)
    vp8l = tmp_path / "l.webp"
    w, h = 300, 200
    bits = (w - 1) | ((h - 1) << 14)
    vp8l.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8L" + b"\x00\x00\x00\x00\x2f" + bits.to_bytes(4, "little")
                     + b"\x00" * 8)
    assert R.image_size(vp8l) == (300, 200)
    vp8 = tmp_path / "v.webp"
    vp8.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 10 + struct.pack("<HH", 120, 90) + b"\x00" * 4)
    assert R.image_size(vp8) == (120, 90)
    junk = tmp_path / "j.png"
    junk.write_bytes(b"nope")
    assert R.image_size(junk) is None and R.image_size(tmp_path / "missing.png") is None


def test_media_duration_tolerates_failure(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert R.media_duration(bad) is None
    assert R.media_duration(tmp_path / "missing.mp4") is None


# ------------------------------------------------------------------ describe
def test_describe_window(demo):
    text = R.describe(demo)
    assert text.startswith("project demo: douyin 1080x1920 30 fps, portrait; safe area x 40-880, y 220-1460 (the "
                           "platform's UI covers the rest); locale zh-CN")
    assert "duration 21.80 s (654 frames, voice end + 0.6 s)" in text
    assert "  [3] 5.62-8.00 茶底加奶，大约两块五。" in text
    assert "    shop video 5.62-11.62 (line:3 -> line:5)  [full]  asset clip cover trim 0.5s loop" in text
    assert "    bill component 5.62-11.62 (line:3 -> line:5)  [80,560 720x640]  Receipt" in text
    assert "notes (visual, hidden, 1 clip)" in text
    assert "cap (captions) from the voice, 14 phrase(s), max 12 chars; emphasis 成本; 1 override(s)" in text
    assert "  photo image assets/photo.png 270x480 used by open, close" in text
    lines = text.splitlines()
    assert lines.index("tracks, bottom to top:") < lines.index("assets (4):") < lines.index("issues: none")
    assert lines[-1] == "issues: none"


def test_describe_at_a_moment(demo):
    text = R.describe(demo, 15.5)
    lines = text.splitlines()
    assert lines[0] == "at 15.50 s (frame 465) of 21.80 s"
    assert lines[1] == "voice: [6] 15.22-18.30 所以算下来，一杯的毛利不到五块。"
    shown = [ln.split(":")[0].strip() for ln in lines[3:] if ln.startswith("  ")]
    assert shown == ["bg", "mid", "fg", "cap"]                        # bottom to top
    assert "close image" in text and "now: zoom 1.08" in text and "progress 0" in text
    assert 'cap: caption "所以算下来"' in text
    assert "todo" not in text                                           # hidden track
    assert "nothing visible" in R.describe(demo, 30)


def test_describe_lists_issues_and_survives_broken_projects(demo):
    data = raw(demo)
    data["tracks"][2]["clips"][1]["start"] = "line:99"
    write(demo, data)
    text = R.describe(demo)
    assert "arrow shape ?-? (clip arrow start 'line:99'" in text
    assert text.splitlines()[-1].startswith("  [error] clip arrow: clip arrow start 'line:99'")
    data["tracks"][2]["clips"][1]["colour"] = 1
    write(demo, data)
    text = R.describe(demo)
    assert text.startswith("project.json does not fit the format") and "clip arrow.colour: unknown field" in text
    (demo / "project.json").write_text("{", encoding="utf-8")
    assert "not valid JSON" in R.describe(demo)
    assert "no project.json" in R.describe(demo / "nowhere")


def test_tools_describe_uses_the_real_resolve(demo):
    r = tools.describe(str(demo), at="line:6+0.28")
    assert r.ok and r.startswith("at 15.50 s (frame 465)")


# ------------------------------------------------------------------ Times inside a clip
def test_numbers_inside_a_clip_count_from_its_start(demo):
    data = raw(demo)
    proof = data["tracks"][1]["clips"][1]                              # starts at line:5 = 11.62 s (frame 349)
    proof["highlight"] = {"at": 0.8}
    proof["keyframes"] = {"x": [{"t": "0.5", "v": 60}, {"t": "line:5+1", "v": 80}]}
    data["tracks"][2]["clips"][3]["props"]["at"] = 0.3                 # verdict, the Stamp
    write(demo, data)
    r = R.resolve(demo)
    assert rclip(r, "proof")["content"]["highlight"]["at"] == 24
    assert rclip(r, "proof")["keyframes"]["x"] == [{"f": 15, "v": 60, "ease": "linear"},     # a numeric string too
                                                   {"f": 30, "v": 80, "ease": "linear"}]     # Time string: absolute
    assert rclip(r, "verdict")["content"]["props"]["at"] == 9
    assert R.describe(demo).endswith("issues: none")


def test_time_of_reads_every_time_against_the_project(demo):
    assert R.time_of(demo, 3) == 3.0 and R.time_of(demo, "2.5") == 2.5
    assert R.time_of(demo, "clip:bed1") == 0.0                         # audio clips are clips too
    assert R.time_of(demo, "clip:bed1.end-0.5") == pytest.approx(1.5)
    assert R.time_of(demo, "LINE:3") == 5.62 and R.time_of(demo, "clip:open.END") == 5.62
    assert R.time_of(demo, "End-1") == pytest.approx(20.8)
    assert R.time_of(demo, "clip:todo.end") == 2.0                      # hidden tracks still have times
    with pytest.raises(T.TimeError, match="line:99 is past the voice: it has 7 line"):
        R.time_of(demo, "line:99")
    with pytest.raises(T.TimeError, match="no clip 'zz'"):
        R.time_of(demo, "clip:zz")
    with pytest.raises(T.TimeError, match="cannot read the Time 'soon'"):
        R.time_of(demo, "soon")
    (demo / "project.json").write_text("{", encoding="utf-8")
    with pytest.raises(T.TimeError, match="not valid JSON"):
        R.time_of(demo, "line:2")
    assert R.time_of(demo, 4) == 4.0                                    # numbers need no project


def test_describe_at_takes_a_time_string(demo):
    assert R.describe(demo, "line:6+0.28").startswith("at 15.50 s (frame 465)")
    assert R.describe(demo, "clip:nope").startswith("cannot read the time: clip:nope: there is no clip 'nope'")


# ------------------------------------------------------------------ audio loop
def test_audio_loop_reaches_resolved_and_describe(demo):
    data = raw(demo)
    bed = data["tracks"][4]["clips"][0]
    bed.update({"loop": True, "dur": 12})
    write(demo, data)
    r = R.resolve(demo)
    assert next(a for a in r["audio"] if a["id"] == "bed1")["loop"] is True
    assert next(a for a in r["audio"] if a["id"] == "voice")["loop"] is False
    assert "bed1 audio 0.00-12.00  asset bed vol 0.1 loop fade_out 0.5s" in R.describe(demo)


# ------------------------------------------------------------------ describe additions
def test_describe_shows_theme_caption_box_and_every_phrase(demo):
    text = R.describe(demo)
    assert "theme paper (a colour may name a token): paper #F3EBDD, ink #1E1A16, night #16130F" in text
    assert "accent #C8372D" in text
    assert "box 40,1260 840x200, y 1260-1460 (default: douyin's captions band)" in text
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("  cap (captions)"))
    rows = lines[start + 1:start + 15]
    assert rows[0] == "    [1] 0.00-1.70 一杯十八块的奶茶"
    assert rows[1] == "    [1] 1.70-3.43 **成本**到底多少钱"
    assert rows[4] == "    [3] 6.57-8.23 大约**2.5元**"
    assert all(r.startswith("    [") for r in rows) and lines[start + 15] == "assets (4):"
    data = raw(demo)
    data["tracks"][-1]["box"] = "safe"
    write(demo, data)
    assert "box 40,220 840x1240, y 220-1460 (safe)" in R.describe(demo)


def test_describe_counts_assets_used_through_component_props(demo):
    data = raw(demo)
    data["assets"]["ev2"] = dict(data["assets"]["ev"])
    data["tracks"].append({"id": "cards", "kind": "visual", "clips": [
        {"id": "card", "type": "component", "name": "EvidenceCard", "start": "line:6", "end": "line:7",
         "props": {"asset": "ev2"}}]})
    write(demo, data)
    text = R.describe(demo)
    assert "  ev2 evidence assets/evidence.png 540x900 box [40, 420, 460, 50] example.com used by card" in text
    assert "unused" not in text


def test_describe_at_uses_the_safe_size_for_safe_boxes(demo):
    data = raw(demo)
    close = data["tracks"][0]["clips"][2]
    close.update({"motion": "pan_left", "box": "safe"})
    write(demo, data)
    text = R.describe(demo, "line:5")
    assert "close image" in text and "pan_x 28.6" in text                # 0.034 x 840, not x 1080
    assert rclip(R.resolve(demo), "close")["keyframes"]["pan_x"][0]["v"] == 28.6
