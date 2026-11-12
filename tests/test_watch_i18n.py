"""The window's dictionaries: every language carries English's keys, placeholders and nothing left in English."""
import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "reelsmith" / "watch" / "static"
LANGS = re.findall(r'\["([a-zA-Z-]+)", "[^"]+", \{', (STATIC / "i18n.js").read_text(encoding="utf-8"))
OTHERS = [code for code in LANGS if code != "en"]
# Intl.PluralRules never answers "one" in these, so their ".one" forms would never be read.
NO_ONE = {"zh-CN", "zh-TW", "ja", "ko"}
HOLE = re.compile(r"\{(\w+)\}")
# Names, units and symbols that read the same in every language.
SAME_EVERYWHERE = {"reelsmith watch", "{n} fps", "{n} s", "s", "{id} · {w} × {h}, {fps} fps"}
# Words a language shares with English by its own right (French and German editors say "clip" and "timeline").
SAME_IN = {
    "fr": {"Agent", "Animation", "Clip", "Description", "Documentation", "Films", "Format", "Licence", "Notes", "Pages",
           "Pause", "Session", "Timeline", "Transcription", "Type", "Version", "Volume", "{n} clips", "{n} films"},
    "de": {"Agent", "Animation", "Clip", "Engine", "Format", "Import", "Layout", "Name", "Optional", "Pause", "System",
           "Text", "Version", "Video"},
    "es": {"Clip", "Error", "Manual", "No", "Video", "video", "{n} clips", "1 clip", "1 error"},
}
# The glossary, enforced: terms a language must not use because it settled on another for the same thing.
NOT_THE_TERM = {
    "zh-CN": [r"代理", r"请求(?!修正)", r"播放指针", r"时间轴(?!卡片)", r"废纸篓"],
    "zh-TW": [r"成片", r"视频|視頻", r"软件|軟件", r"文件(?!夾)", r"播放頭", r"渲染", r"請求", r"[这们说后为]", r"回收|廢紙簍"],
    "ja": [r"レンダリング", r"リクエスト", r"検査", r"ごみ箱"],
    "ko": [r"컷", r"쓰레기통"],
    "es": [r"vídeo", r"fragmento", r"tramo(?!s suprimidos|\s+suprimido)", r"[Pp]ulse\b", r"[Dd]escriba", r"[Vv]uelva a"],
    "fr": [r"séquence", r"[Aa]ppuyez", r"[Vv]euillez", r"\bnarration", r"[Rr]églages"],
    "de": [r"Timeline", r"\bStille Abschnitte", r"während der \{stage\}"],
}


def _part(path: Path, code: str) -> dict:
    """A dictionary file is `export default { "key": "value", ... };` with JSON strings."""
    src = path.read_text(encoding="utf-8")
    body = src[src.index("export default {") + len("export default "):src.rindex("}") + 1]
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    body = re.sub(r",(\s*)\}$", r"\1}", body)

    def unique(pairs):
        keys = [k for k, _ in pairs]
        dup = {k for k in keys if keys.count(k) > 1}
        assert not dup, f"{code}: duplicate keys {sorted(dup)}"
        return dict(pairs)
    return json.loads(body, object_pairs_hook=unique)


def load(code: str) -> dict:
    """A language's strings: its main file and the Library and Settings pages' part; no key in both."""
    main = _part(STATIC / "i18n" / f"{code}.js", code)
    pages = _part(STATIC / "i18n" / "pages" / f"{code}.js", code)
    assert not set(main) & set(pages), f"{code}: keys in both parts {sorted(set(main) & set(pages))}"
    return {**main, **pages}


EN = load("en")
EN_MAIN = _part(STATIC / "i18n" / "en.js", "en")
EN_PAGES = _part(STATIC / "i18n" / "pages" / "en.js", "en")
# The pages part's own prefixes, so the two parts never compete for a key.
PAGES_PREFIXES = ("pages.", "lib.", "set.", "library.", "settings.", "key.", "reveal.missing")


def holes(s: str) -> set:
    return set(HOLE.findall(s))


def test_menu_lists_every_language_once():
    assert LANGS[0] == "en" and len(LANGS) == len(set(LANGS)) == 8
    assert set(LANGS) == {"en", "zh-CN", "zh-TW", "ja", "ko", "es", "fr", "de"}


@pytest.mark.parametrize("code", LANGS)
def test_no_empty_value(code):
    d = load(code)
    assert [k for k, v in d.items() if not isinstance(v, str) or not v.strip()] == []


@pytest.mark.parametrize("code", LANGS)
def test_no_control_characters(code):
    # a broken substitution once left \x01 where French punctuation belonged
    assert [k for k, v in load(code).items() if re.search(r"[\x00-\x1f\x7f]", v)] == []


def test_every_singular_has_its_plural():
    # act.edit.one is a key of its own (beside act.edit.n), not a plural form
    assert [k for k in EN if k.endswith(".one") and k[:-4] not in EN] == ["act.edit.one"]


@pytest.mark.parametrize("code", OTHERS)
def test_same_keys_as_english(code):
    d = load(code)
    need = {k for k in EN if not (code in NO_ONE and k.endswith(".one") and k[:-4] in EN)}
    assert sorted(need - d.keys()) == [], f"{code} lacks keys"
    assert sorted(d.keys() - EN.keys()) == [], f"{code} has keys English does not"


@pytest.mark.parametrize("code", OTHERS)
def test_same_placeholders(code):
    d = load(code)
    wrong = []
    for k, v in d.items():
        if k not in EN:
            continue
        if k.endswith(".one"):
            # a singular may spell the number out ("1 clip") or keep it ("{n} plan": French "one" covers 0 too)
            base = EN.get(k[:-4], EN[k])
            ok = holes(EN[k]) <= holes(v) <= holes(EN[k]) | holes(base)
        else:
            ok = holes(v) == holes(EN[k])
        if not ok:
            wrong.append((k, EN[k], v))
    assert wrong == []


@pytest.mark.parametrize("code", OTHERS)
def test_nothing_left_in_english(code):
    d = load(code)
    allowed = SAME_EVERYWHERE | SAME_IN.get(code, set())
    left = []
    for k, v in d.items():
        if v != EN.get(k) or v in allowed:
            continue
        if not re.search(r"[^\W\d_]", HOLE.sub("", v)):     # placeholders, numbers and symbols only
            continue
        left.append((k, v))
    assert left == []


@pytest.mark.parametrize("code", sorted(SAME_IN))
def test_allow_list_is_in_use(code):
    d = load(code)
    used = {v for k, v in d.items() if v == EN.get(k)}
    assert sorted(SAME_IN[code] - used) == []


@pytest.mark.parametrize("code", LANGS)
def test_register(code):
    d = load(code)
    assert [k for k, v in d.items() if re.search(r"[!！]\s*$", v)] == []


@pytest.mark.parametrize("code", sorted(NOT_THE_TERM))
def test_glossary_terms(code):
    d = load(code)
    found = [(k, v) for k, v in d.items() for p in NOT_THE_TERM[code] if re.search(p, v)]
    assert found == []


def test_french_spaces_before_high_punctuation():
    d = load("fr")
    nb = "  "
    wrong = []
    for k, v in d.items():
        bad = re.search(rf"(?<![{nb}])[;?!»]|«(?![{nb}])", v)
        # a colon takes the space too, except inside a ratio ("{ratio}:1") or a time
        bad = bad or re.search(rf"(?<![{nb}\d}}]):|(?<=[\d}}]):(?!\d)", v)
        bad = bad or re.search(rf"\s[{nb}]", v)                     # a plain space doubling the no-break one
        if bad:
            wrong.append((k, v))
    assert wrong == []


@pytest.mark.parametrize("code", OTHERS)
@pytest.mark.parametrize("part", ["main", "pages"])
def test_each_key_sits_in_the_part_english_puts_it(code, part):
    en = EN_MAIN if part == "main" else EN_PAGES
    d = _part(STATIC / "i18n" / (f"{code}.js" if part == "main" else f"pages/{code}.js"), code)
    need = {k for k in en if not (code in NO_ONE and k.endswith(".one") and k[:-4] in en)}
    assert sorted(need - d.keys()) == [] and sorted(d.keys() - en.keys()) == []


def test_pages_part_keeps_to_its_prefixes():
    assert [k for k in EN_PAGES if not k.startswith(PAGES_PREFIXES)] == []


def test_every_key_the_page_names_exists():
    src = "".join(p.read_text(encoding="utf-8") for p in [*STATIC.glob("*.js"), *STATIC.glob("*.html")]
                  if not p.name.startswith("i18n"))
    named = set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", src))
    named |= set(re.findall(r'data-i18n(?:-title)?="([\w.]+)"', src))
    assert sorted(named - EN.keys()) == []


@pytest.mark.parametrize("code", LANGS)
def test_settings_name_the_theme_choice_as_its_button_does(code):
    d = {**EN, **load(code)}
    assert d["theme.system"] in d["set.themeAbout"]


@pytest.mark.parametrize("code", LANGS)
def test_directions_name_the_pages_as_the_sidebar_does(code):
    d = load(code)
    for key, section in (("frame.trash.body", "set.sec.trash"), ("frame.engine.tip", "set.sec.agent")):
        assert d["frame.settings"] in d[key] and d[section] in d[key], key
