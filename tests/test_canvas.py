"""Any canvas, any locale: profiles (built-in and custom), the locale, workspace fonts and canvas-scaled checks."""
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from reelsmith import checks as C
from reelsmith import document as D
from reelsmith import locales as L
from reelsmith import profiles as P
from reelsmith import render as RN
from reelsmith import resolve as R
from reelsmith import tools as T
from reelsmith import workspace as W

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "demo"
FONT = ROOT / "renderer" / "src" / "fonts" / "SmileySans-Oblique.woff2"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
needs_renderer = pytest.mark.skipif(not (shutil.which("node") and shutil.which("ffmpeg")
                                         and (RN.RENDERER / "node_modules" / "remotion").is_dir()),
                                    reason="node, ffmpeg or the renderer's packages missing")


def make_ws(root: Path, config=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace.json").write_text(json.dumps(config or {}), encoding="utf-8")
    return root


def write(p: Path, data: dict) -> None:
    (p / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def raw(p: Path) -> dict:
    return json.loads((p / "project.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """The demo project (douyin, zh-CN) inside an empty workspace."""
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    ws = make_ws(tmp_path / "ws")
    p = ws / "projects" / "demo"
    shutil.copytree(FIXTURE, p, ignore=shutil.ignore_patterns("build", ".history"))
    return p


def english(p: Path, lines: list[str], **project) -> None:
    """Narration timing for `lines` (2.5 s each) next to the fixture's audio, and a project that captions it."""
    voice = {"file": "voice/voice.wav", "duration_s": 2.5 * len(lines),
             "lines": [{"i": n, "text": t, "t0": 2.5 * (n - 1), "t1": 2.5 * n - 0.2} for n, t in enumerate(lines, 1)]}
    (p / "voice" / "voice.json").write_text(json.dumps(voice), encoding="utf-8")
    write(p, {"version": 2, "voice": "voice/voice.json", "assets": {}, **project,
              "tracks": [{"id": "cap", "kind": "captions"}, *project.pop("tracks", [])]})


# ------------------------------------------------------------------ 1. profiles
def test_generic_and_platform_profiles():
    assert set(P.PROFILES) == {"landscape", "vertical", "square", "portrait", "youtube", "douyin", "douyin-long",
                               "tiktok", "shorts", "reels"}
    assert P.get_profile(None) is P.LANDSCAPE and P.DEFAULT_PROFILE == "landscape"
    sizes = {n: (P.PROFILES[n].width, P.PROFILES[n].height) for n in ("landscape", "vertical", "square", "portrait")}
    assert sizes == {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080),
                     "portrait": (1080, 1350)}
    for name in sizes:
        p = P.PROFILES[name]
        assert (p.safe.x, p.safe.y) == (round(0.05 * p.width), round(0.05 * p.height)), name
        assert p.safe.x + p.safe.w == p.width - p.safe.x and p.safe.y + p.safe.h == p.height - p.safe.y
        assert (p.min_s, p.max_s, p.target_s, p.max_mb, p.max_still_s) == (None,) * 5
        assert not p.require_audio and not p.ui and p.lufs == -14.0
        assert (p.captions.x, p.captions.w, p.captions.h, p.captions.y + p.captions.h) == (
            p.safe.x, p.safe.w, 200, p.safe.y + p.safe.h)
    assert P.YOUTUBE.require_audio and (P.YOUTUBE.width, P.YOUTUBE.height, P.YOUTUBE.lufs) == (1920, 1080, -14.0)
    assert P.YOUTUBE.max_s is None and P.YOUTUBE.max_mb is None and P.YOUTUBE.max_still_s is None
    assert P.REELS.safe == P.Box(66, 250, 884, 1000) and (P.REELS.min_s, P.REELS.max_s, P.REELS.lufs) == (3, 180, -14)
    for name in ("douyin", "douyin-long", "tiktok", "shorts", "reels"):        # the social ones keep every check
        p = P.PROFILES[name]
        assert p.require_audio and p.max_still_s == 5.0 and p.ui and p.max_black_ratio == 0.10, name
    d = P.DOUYIN
    assert (d.width, d.height, d.safe, d.captions, d.min_s, d.max_s, d.target_s, d.max_mb, d.lufs) == (
        1080, 1920, P.Box(40, 220, 840, 1240), P.Box(40, 1260, 840, 200), 20, 90, (45, 75), 80, -10.0)
    assert [P.PROFILES[n].orientation for n in ("landscape", "vertical", "square")] == ["landscape", "portrait",
                                                                                       "square"]
    assert P.LANDSCAPE.scale == 1 and P.make_profile({"width": 1280, "height": 720}).scale == pytest.approx(2 / 3)


def test_custom_profiles_from_workspace_json(tmp_path):
    root = make_ws(tmp_path / "ws", {"profile": "wide720", "profiles": {
        "brand": {"base": "douyin", "fps": 25, "lufs": -16},
        "wide720": {"width": 1280, "height": 720, "fps": 50},
        "brand_short": {"base": "brand", "max_s": 30, "min_s": None, "target_s": None},
        "boxed": {"base": "square", "safe": {"x": 0, "y": 0, "w": 1080, "h": 1080}, "require_audio": True}}})
    ws = W.Workspace.load(root)
    brand, wide, short, boxed = (ws.profiles[n] for n in ("brand", "wide720", "brand_short", "boxed"))
    assert (brand.name, brand.fps, brand.lufs, brand.safe, brand.max_s) == ("brand", 25, -16.0, P.DOUYIN.safe, 90)
    assert (wide.width, wide.height, wide.fps, wide.safe) == (1280, 720, 50, P.Box(64, 36, 1152, 648))
    assert wide.captions == P.Box(64, 551, 1152, 133)                    # the band, scaled with the short side
    assert (short.fps, short.max_s, short.min_s, short.target_s) == (25, 30, None, None)
    assert boxed.captions == P.Box(0, 880, 1080, 200) and boxed.require_audio
    p = root / "projects" / "a"
    p.mkdir(parents=True)
    assert W.profile_for(p) == wide                                    # workspace.json profile names a custom one
    write(p, {"version": 2, "profile": "brand"})
    assert W.profile_for(p).name == "brand"
    write(p, {"version": 2, "profile": {"base": "brand", "width": 720, "height": 1280}})
    got = W.profile_for(p)
    assert (got.name, got.width, got.height, got.fps, got.lufs) == ("custom", 720, 1280, 25, -16.0)
    assert got.safe == P.Box(27, 147, 560, 827)                         # douyin's, scaled by 2/3
    assert P.choose(None, {"width": 640, "height": 360}).width == 640   # workspace.json profile may be inline too


@pytest.mark.parametrize("profiles, fragment", [
    ({"x": {"width": 1001}}, "profiles.x.width must be an even whole number 64-4096"),
    ({"x": {"height": 32}}, "profiles.x.height"),
    ({"x": {"fps": 0}}, "profiles.x.fps must be a whole number 1-120"),
    ({"x": {"fps": 29.97}}, "profiles.x.fps"),
    ({"x": {"safe": [0, 0, 1921, 10]}}, "profiles.x.safe [0, 0, 1921, 10] must lie inside the 1920x1080 canvas"),
    ({"x": {"captions": {"x": 0, "y": 1000, "w": 100, "h": 100}}}, "profiles.x.captions"),
    ({"x": {"min_s": 50, "max_s": 10}}, "min_s 50 is over max_s 10"),
    ({"x": {"target_s": [9, 3]}}, "profiles.x.target_s"),
    ({"x": {"aspect": "16:9"}}, "unknown field(s) aspect"),
    ({"x": {"base": "vine"}}, "profiles.x.base: unknown profile 'vine'"),
    ({"a": {"base": "b"}, "b": {"base": "a"}}, "base profiles loop (a -> b -> a)"),
    ({"douyin": {"fps": 60}}, "'douyin' is a built-in profile"),
    ({"bad name": {}}, "a profile name is 1-64 letters"),
    ([1], "profiles must be an object"),
])
def test_bad_custom_profiles_are_refused_at_load(tmp_path, profiles, fragment):
    root = make_ws(tmp_path / "ws", {"profiles": profiles})
    with pytest.raises(W.WorkspaceError) as exc:
        W.Workspace.load(root)
    assert fragment in str(exc.value)


def test_canvas_strings():
    assert P.parse_canvas("1920x1080@25") == {"width": 1920, "height": 1080, "fps": 25}
    assert P.parse_canvas(" 1280 x 720 ") == {"width": 1280, "height": 720}
    for bad in ("1920", "1920x", "16:9", "1920x1080@", "x1080"):
        with pytest.raises(P.ProfileError, match="1920x1080@25"):
            P.parse_canvas(bad)


# ------------------------------------------------------------------ 2. custom canvases in project.json
def test_inline_profile_and_locale_in_project_json(demo):
    data = raw(demo)
    data.update(profile={"base": "douyin", "fps": 25}, locale="en-GB")
    doc, issues = D.check_data(demo, data)
    assert not [i for i in issues if i.level == "error"]
    assert D.profile_of(demo, doc).fps == 25 and D.locale_of(demo, doc) == "en-GB"
    data.update(profile={"width": 1081}, locale="english please")
    found = {(i.where, i.msg.split(" must")[0]) for i in D.check_data(demo, data)[1] if i.level == "error"}
    assert ("profile", "project.json profile.width") in found
    assert ("locale", "locale 'english please' is not a BCP-47 language tag such as \"en\", \"en-GB\", \"zh-CN\" or "
            "\"ja\"") in {(i.where, i.msg) for i in D.check_data(demo, data)[1]}
    write(demo, {**data, "profile": "vine", "locale": "en"})
    assert any(i.where == "profile" and "unknown profile 'vine'" in i.msg for i in D.validate(demo, D.load(demo)))


def test_new_project_with_a_profile_a_canvas_and_a_locale(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = make_ws(tmp_path / "ws", {"profile": "douyin", "profiles": {"brand": {"base": "square", "fps": 24}}})
    r = T.new_project(str(root / "projects" / "a"))
    assert r.ok and "douyin 1080x1920 30 fps, safe area x 40-880, y 220-1460" in r
    assert "profile" not in raw(root / "projects" / "a")                      # the workspace's stays in charge
    r = T.new_project(str(root / "projects" / "b"), canvas="720x1280@25", locale="ja")
    assert r.ok and "custom 720x1280 25 fps" in r
    assert raw(root / "projects" / "b")["profile"] == {"base": "douyin", "width": 720, "height": 1280, "fps": 25}
    assert raw(root / "projects" / "b")["locale"] == "ja"
    r = T.new_project(str(root / "projects" / "c"), profile="brand")
    assert r.ok and "brand 1080x1080 24 fps" in r and raw(root / "projects" / "c")["profile"] == "brand"
    r = T.new_project(str(root / "projects" / "d"), profile="landscape", canvas="3840x2160")
    assert r.ok and raw(root / "projects" / "d")["profile"] == {"base": "landscape", "width": 3840, "height": 2160}
    for kw, says in (({"canvas": "16:9"}, "1920x1080@25"), ({"canvas": "1921x1080"}, "even whole number"),
                     ({"profile": "vine"}, "unknown profile 'vine'"), ({"locale": "en_US"}, "BCP-47")):
        r = T.new_project(str(root / "projects" / "e"), **kw)
        assert not r.ok and says in r, kw
        assert not (root / "projects" / "e" / "project.json").exists()
    from reelsmith import cli
    assert cli.main(["new", str(root / "projects" / "f"), "--canvas", "1080x1080@60", "--locale", "zh-CN"]) == 0
    assert raw(root / "projects" / "f")["profile"]["fps"] == 60


# ------------------------------------------------------------------ 3. the canvas scales px thresholds
def text_item(clip, rect, size, words="words"):
    return {"clip": clip, "track": "v1", "kind": "text", "rect": rect, "opacity": 1, "text": words, "size": size,
            "color": "rgb(255,255,255)"}


def test_layout_thresholds_follow_the_canvas():
    small = P.make_profile({"width": 720, "height": 1280}, name="p720")      # scale 2/3: 18.67 and 13.33 px
    big = P.make_profile({"width": 3840, "height": 2160}, name="p4k")        # scale 2: 56 and 40 px
    frame = {"frames": [{"frame": 0, "items": [text_item("a", [100, 300, 300, 40], 17),
                                               text_item("b", [100, 400, 300, 40], 12)]}]}
    found = {i.where.split(" @")[0]: i for i in C.check_layout(frame, small)}
    assert found["a"].level == "warning" and "under 18.67 px" in found["a"].msg and "720x1280 canvas" in found["a"].msg
    assert found["b"].level == "error" and "render refuses under 13.33" in found["b"].msg
    frame = {"frames": [{"frame": 0, "items": [text_item("a", [400, 300, 600, 60], 50),
                                               text_item("b", [400, 500, 600, 60], 30)]}]}
    found = {i.where.split(" @")[0]: i.level for i in C.check_layout(frame, big)}
    assert found == {"a": "warning", "b": "error"}
    assert C.check_layout(frame, replace(big, width=1080, height=1920, safe=P.Box(0, 0, 1080, 1920))) == []


def test_unsafe_text_names_the_title_safe_margin_on_generic_canvases():
    frame = {"frames": [{"frame": 0, "items": [text_item("t", [10, 300, 300, 60], 60)]}]}
    generic = C.check_layout(frame, P.LANDSCAPE)[0].msg
    social = C.check_layout(frame, P.DOUYIN)[0].msg
    assert "the title-safe margin" in generic and "x 96-1824, y 54-1026" in generic
    assert "the platform's UI covers it" in social


def test_evidence_legibility_scales_with_the_canvas(tmp_path):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1290, 600), "white")
    for x in range(40, 1240, 30):                                              # one line of 31 px "glyphs"
        ImageDraw.Draw(img).rectangle((x, 300, x + 18, 330), fill="black")
    (tmp_path / "assets").mkdir()
    img.save(tmp_path / "assets" / "ev.png")
    # shown at twice its size: the 31 px line reads at about 73 px
    ev = {"id": "e", "type": "evidence", "track": "v1", "from": 0, "dur": 30, "box": {"x": 0, "y": 0, "w": 2600,
          "h": 400}, "style": {"opacity": 1}, "keyframes": {}, "enter": None, "exit": None,
          "content": {"src": "assets/ev.png", "size": [1290, 600], "box": [40, 290, 1210, 50]}}

    def at(w, h):
        r = {"fps": 30, "width": w, "height": h, "durationInFrames": 30,
             "tracks": [{"id": "v1", "kind": "visual", "clips": [ev]}]}
        return C.evidence_issues(r, tmp_path)
    assert at(1080, 1920) == []                                          # over 40 px
    issues = at(2160, 3840)
    assert issues and "about 73 px (under 80 px" in issues[0].msg       # a 4K canvas wants twice as much


def test_contact_sheet_tiles_follow_the_canvas():
    assert RN.sheet_tile(P.DOUYIN) == (360, 640)
    assert RN.sheet_tile(P.LANDSCAPE) == (640, 360)
    assert RN.sheet_tile(P.SQUARE) == (480, 480)
    w, h = RN.sheet_tile(P.PORTRAIT)
    assert w % 2 == 0 and h % 2 == 0 and abs(w / h - 0.8) < 0.01


def test_resolve_a_landscape_project_scales_defaults_and_places_captions(demo):
    data = raw(demo)
    data.update(profile="landscape")
    data["tracks"][-1].pop("max_chars")
    data["tracks"][2]["clips"][0]["style"] = {}                           # the hook: default sizes
    write(demo, data)
    r = R.resolve(demo)
    assert (r["width"], r["height"], r["fps"]) == (1920, 1080, 30)
    assert r["safe"] == {"x": 96, "y": 54, "w": 1728, "h": 972}
    cap = next(t for t in r["tracks"] if t["kind"] == "captions")
    assert cap["box"] == {"x": 96, "y": 826, "w": 1728, "h": 200}
    hook = next(c for t in r["tracks"] for c in t.get("clips") or [] if c["id"] == "hook")
    assert (hook["content"]["style"]["size"], hook["content"]["style"]["min_size"]) == (64, 28)   # scale 1
    data["profile"] = {"base": "landscape", "width": 1280, "height": 720, "fps": 25}
    write(demo, data)
    r = R.resolve(demo)
    hook = next(c for t in r["tracks"] for c in t.get("clips") or [] if c["id"] == "hook")
    style = hook["content"]["style"]
    assert (style["size"], style["max_size"], style["min_size"]) == (43, 107, 19)
    assert r["fps"] == 25 and r["durationInFrames"] == round(21.8 * 25)
    assert next(t for t in r["tracks"] if t["kind"] == "captions")["box"]["h"] == 133


def test_describe_landscape_and_square(demo):
    data = raw(demo)
    data.update(profile="landscape", locale="en")
    write(demo, data)
    text = R.describe(demo)
    assert text.startswith("project demo: landscape 1920x1080 30 fps, landscape; safe area x 96-1824, y 54-1026 "
                           "(a title-safe margin); locale en")
    data.update(profile="square")
    data["tracks"][-1].pop("max_chars")
    write(demo, data)
    text = R.describe(demo)
    assert "square 1080x1080 30 fps, square; safe area x 54-1026, y 54-1026" in text
    assert "box 54,826 972x200, y 826-1026 (default: square's captions band)" in text
    assert "max 32 chars" in text


# ------------------------------------------------------------------ 4. locale: captions
def test_locales_helpers():
    assert [L.caption_chars(t) for t in ("zh-CN", "ja", "ko", "en", "de-DE", "th")] == [14, 14, 14, 32, 32, 32]
    assert L.is_chinese("zh-Hant-TW") and L.is_chinese("yue") and not L.is_chinese("ja")
    assert L.accept_language("zh-CN") == "zh-CN,zh;q=0.9,en;q=0.8"
    assert L.accept_language("en") == "en" and L.accept_language("en-GB") == "en-GB,en;q=0.9"
    assert L.accept_language("ja") == "ja,en;q=0.8"
    for bad in ("", "e", "en_US", "zh-CN!", 3, None):
        with pytest.raises(ValueError):
            L.check(bad)


def test_locale_precedence_and_validation(tmp_path):
    root = make_ws(tmp_path / "ws", {"locale": "zh-CN"})
    p = root / "projects" / "a"
    p.mkdir(parents=True)
    assert W.locale_for(p) == "zh-CN" and W.locale_for(tmp_path / "lonely") == "en"
    write(p, {"version": 2, "locale": "ja"})
    assert W.locale_for(p) == "ja"
    write(p, {"version": 2, "locale": "not a tag"})
    with pytest.raises(ValueError, match="BCP-47"):
        W.locale_for(p)
    with pytest.raises(W.WorkspaceError, match="workspace.json: locale 'english!'"):
        W.Workspace.load(make_ws(tmp_path / "ws2", {"locale": "english!"}))


def test_caption_max_chars_defaults_by_locale(demo):
    data = raw(demo)
    data["tracks"][-1].pop("max_chars")
    write(demo, data)
    zh = next(t for t in R.resolve(demo)["tracks"] if t["kind"] == "captions")["items"]
    assert max(sum(len(r["text"]) for r in it["runs"]) for it in zh) <= 14
    data["locale"] = "en"
    write(demo, data)
    en = next(t for t in R.resolve(demo)["tracks"] if t["kind"] == "captions")["items"]
    assert len(en) < len(zh)                                             # 32 characters a phrase
    data["tracks"][-1]["max_chars"] = 60
    assert not [i for i in D.check_data(demo, data)[1] if i.level == "error"]


def test_latin_captions_split_between_words(demo):
    lines = ["So here's the thing: most people never check the label on the back of the bottle, and that is a "
             "mistake.", "Well, I think so.", "Prices rose 3.5% in 2024 across forty-two countries."]
    english(demo, lines, locale="en", profile="landscape")
    items = next(t for t in R.resolve(demo)["tracks"] if t["kind"] == "captions")["items"]
    phrases = ["".join(r["text"] for r in it["runs"]) for it in items]
    words = {w for ln in lines for w in ln.replace(",", " ").replace(":", " ").replace(".", " ").split()}
    for ph in phrases:
        assert len(ph) <= 32, ph
        assert all(w in words or w in ("3.5%",) for w in ph.split()), ph       # never a broken word
    assert "Well I think so" in phrases                                   # a lone short word joins its neighbour
    assert "3.5%" in " ".join(phrases) and "forty-two" in " ".join(phrases)


def test_segmenter_gets_the_locale_and_caches_per_locale(demo, monkeypatch):
    calls = []

    def fake(texts, locale="en"):
        calls.append(locale)
        return [R.char_words(t) for t in texts]
    monkeypatch.setattr(R, "_node_words", fake)
    monkeypatch.setattr(R, "_WORDS", {})
    R.resolve(demo)
    data = raw(demo)
    data["locale"] = "ja"
    write(demo, data)
    R.resolve(demo)
    R.resolve(demo)
    assert calls == ["zh-CN", "ja"]                                      # one call per locale, then the cache
    cache = json.loads((demo / "build" / "segments.json").read_text(encoding="utf-8"))
    assert cache["version"] == R.SEGMENT_VERSION == 2


def test_segment_script_takes_the_locale():
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    script = ROOT / "renderer" / "scripts" / "segment.mjs"
    for locale in ("en", "ja", "zh-CN", "not a tag"):
        out = subprocess.run(["node", str(script)], input=json.dumps({"texts": ["Don't stop now"], "locale": locale}),
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert json.loads(out.stdout)["words"] == [[5, 1, 4, 1, 3]], locale


# ------------------------------------------------------------------ 5. workspace fonts
def test_workspace_fonts_by_file_stem_and_map(tmp_path):
    root = make_ws(tmp_path / "ws")
    fonts = root / "library" / "fonts"
    fonts.mkdir(parents=True)
    for name in ("Brand Sans.woff2", "Mono-1.ttf", "sans.otf", "bad!name.woff", "notes.txt"):
        (fonts / name).write_bytes(b"x")
    (root / "extra.otf").write_bytes(b"x")
    found = W.Workspace.load(root).fonts
    assert sorted(found) == ["Brand Sans", "Mono-1"]                   # a built-in name or an odd stem is skipped
    assert found["Brand Sans"][0]["path"] == (fonts / "Brand Sans.woff2").resolve()
    (root / "workspace.json").write_text(json.dumps({"fonts": {
        "Headline": {"src": "extra.otf", "weight": "100 900", "style": "italic"},
        "Mono-1": ["library/fonts/Mono-1.ttf", {"src": "extra.otf", "weight": "700"}]}}), encoding="utf-8")
    found = W.Workspace.load(root).fonts
    assert found["Headline"] == [{"path": (root / "extra.otf").resolve(), "weight": "100 900", "style": "italic"}]
    assert [f["weight"] for f in found["Mono-1"]] == [None, "700"] and "Brand Sans" in found
    bad = (({"serif": "extra.otf"}, "not one of sans"), ({"X": "../outside.otf"}, "inside the workspace"),
           ({"X": "library/fonts/notes.txt"}, "is not a"), ({"X": {"src": "extra.otf", "weight": "bold"}}, "weight"),
           ([1], "must be an object"))
    for fonts_map, says in bad:
        (root / "workspace.json").write_text(json.dumps({"fonts": fonts_map}), encoding="utf-8")
        with pytest.raises(W.WorkspaceError, match=says):
            W.Workspace.load(root)


def _link_folder(link: Path, target: Path) -> None:
    if os.name == "nt":                                             # a junction needs no symlink privilege
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_library_fonts_that_lead_out_of_the_workspace_are_skipped(tmp_path):
    root = make_ws(tmp_path / "ws")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "Secret.ttf").write_bytes(b"x")
    (root / "library").mkdir()
    shared = root / "shared"
    shared.mkdir()
    (shared / "House.ttf").write_bytes(b"x")
    _link_folder(root / "library" / "fonts", outside)
    try:
        assert W.Workspace.load(root).fonts == {}                 # nothing outside reaches build/fonts
    finally:
        (root / "library" / "fonts").rmdir() if os.name == "nt" else (root / "library" / "fonts").unlink()
    _link_folder(root / "library" / "fonts", shared)              # a link that stays inside the workspace is fine
    try:
        assert list(W.Workspace.load(root).fonts) == ["House"]
    finally:
        (root / "library" / "fonts").rmdir() if os.name == "nt" else (root / "library" / "fonts").unlink()


def test_a_workspace_font_validates_resolves_and_is_served_from_the_project(demo):
    fonts = demo.parent.parent / "library" / "fonts"
    fonts.mkdir(parents=True)
    shutil.copy(FONT, fonts / "MyDisplay.woff2")
    data = raw(demo)
    data["tracks"][2]["clips"][0]["style"]["font"] = "MyDisplay"
    data["tracks"][-1]["style"] = {"font": "MyDisplay"}
    write(demo, data)
    assert not [i for i in D.validate(demo, D.load(demo)) if i.level == "error"]
    r = R.resolve(demo)
    assert r["fonts"] == [{"family": "MyDisplay", "src": "build/fonts/MyDisplay.woff2"}]
    served = demo / "build" / "fonts" / "MyDisplay.woff2"
    assert served.read_bytes() == FONT.read_bytes()
    stamp = served.stat().st_mtime_ns
    R.resolve(demo)
    assert served.stat().st_mtime_ns == stamp                           # linked or copied once
    data["tracks"][2]["clips"][0]["style"]["font"] = "Missing"
    write(demo, data)
    bad = [i for i in D.validate(demo, D.load(demo)) if i.level == "error"]
    assert len(bad) == 1 and "unknown font 'Missing'" in bad[0].msg and "the workspace's MyDisplay" in bad[0].msg


# ------------------------------------------------------------------ delivery on generic profiles
def make_film(path: Path, audio: bool, still: bool, seconds=3):
    src = f"color=c=0x3366aa:s=160x90:r=25:d={seconds}" if still else f"testsrc2=s=160x90:r=25:d={seconds}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


@needs_ffmpeg
def test_film_check_on_a_generic_profile(tmp_path):
    tiny = P.make_profile({"width": 160, "height": 90, "fps": 25}, name="tiny")
    assert not tiny.require_audio and tiny.max_still_s is None and tiny.max_s is None
    silent = tmp_path / "silent.mp4"
    make_film(silent, audio=False, still=True)
    out = C.check_film(silent, tiny)
    assert out["ok"], out["why"]
    assert "a silent film (this profile allows one)" in out["notes"]
    quiet = tmp_path / "quiet.mp4"
    make_film(quiet, audio=True, still=False)
    out = C.check_film(quiet, tiny)
    assert out["ok"] and any("silent" in n for n in out["notes"])
    strict = replace(tiny, require_audio=True, max_still_s=1.0, max_s=2.0)
    why = C.check_film(silent, strict)["why"]
    assert "no audio stream" in why and "without any motion" in why and "takes at most 2 s" in why
    assert C.duration_issues({"fps": 25, "durationInFrames": 25 * 4000}, tiny) == []


# ------------------------------------------------------------------ the real renderer on other canvases
def canvas_project(tmp_path, config: dict, tracks: list, seconds: float) -> Path:
    ws = make_ws(tmp_path / "ws", config)
    p = ws / "projects" / "p"
    p.mkdir(parents=True)
    write(p, {"version": 2, "duration": seconds, "assets": {}, "tracks": tracks})
    return p


def text_clip(cid, start, end, text, box, **style):
    return {"id": cid, "type": "text", "text": text, "start": start, "end": end, "box": box,
            "style": {"size": 72, "color": "snow", **style}}


def png_size(path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


@needs_renderer
def test_preview_a_landscape_project_through_the_renderer(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    tracks = [
        {"id": "bg", "kind": "visual", "clips": [{"id": "ground", "type": "shape", "shape": "rect", "fill": "night",
                                                 "start": 0, "end": "end"}]},
        {"id": "fg", "kind": "visual", "clips": [
            text_clip("inside", 0, "end", "Inside the safe area", {"x": 200, "y": 200, "w": 1400, "h": 160})]},
        {"id": "fg2", "kind": "visual", "clips": [
            text_clip("edge", 0, "end", "Off the edge", {"x": 0, "y": 500, "w": 700, "h": 120})]},
        {"id": "cap", "kind": "captions", "items": [{"start": 0, "end": "end", "text": "Captions sit in the band"}]}]
    p = canvas_project(tmp_path, {"locale": "en"}, tracks, 1.5)              # no profile: landscape
    res = RN.preview(p, [0.5])
    assert res["ok"], res
    assert png_size(res["frames"][0]["png"]) == (1920, 1080)
    sheet = png_size(res["contact"])
    assert sheet[0] > sheet[1]                                                 # a landscape tile
    unsafe = [r for r in res["layout"] if "outside the safe area" in r]
    assert len(unsafe) == 1 and unsafe[0].startswith("[error] edge @ 0.5s") and "title-safe margin" in unsafe[0]
    assert not [r for r in res["layout"] if r.startswith(("[error] inside", "[error] cap", "[warning] cap"))]
    assert R.describe(p).startswith("project p: landscape 1920x1080 30 fps, landscape")


@needs_renderer
def test_preview_a_square_project_with_a_workspace_font(tmp_path, monkeypatch):
    from PIL import ImageChops, Image
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    box = {"x": 140, "y": 300, "w": 800, "h": 240}
    words = "Hello 2026"
    tracks = [
        {"id": "bg", "kind": "visual", "clips": [{"id": "ground", "type": "shape", "shape": "rect", "fill": "night",
                                                 "start": 0, "end": "end"}]},
        {"id": "fg", "kind": "visual", "clips": [
            text_clip("mine", 0, 1, words, box, font="MyDisplay"),
            text_clip("built", 1, 2, words, box, font="display"),
            text_clip("plain", 2, 3, words, box, font="sans")]}]
    p = canvas_project(tmp_path, {"profile": "square"}, tracks, 3)
    fonts = p.parent.parent / "library" / "fonts"
    fonts.mkdir(parents=True)
    shutil.copy(FONT, fonts / "MyDisplay.woff2")
    res = RN.preview(p, [0.5, 1.5, 2.5])
    assert res["ok"], res
    assert res["layout"] == [] and res["browserErrors"] == []
    mine, built, plain = (Image.open(f["png"]).convert("RGB") for f in res["frames"])
    assert mine.size == (1080, 1080)
    crop = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
    assert ImageChops.difference(mine.crop(crop), built.crop(crop)).getbbox() is None     # the same face
    assert ImageChops.difference(mine.crop(crop), plain.crop(crop)).getbbox() is not None
    assert png_size(res["contact"])[0] >= png_size(res["contact"])[1]
