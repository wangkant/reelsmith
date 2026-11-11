"""The window's dictionaries: every language carries English's keys, placeholders and nothing left in English."""
import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "reelsmith" / "watch" / "static"
LANGS = re.findall(r'\["([a-zA-Z-]+)", "[^"]+", \w+\]', (STATIC / "i18n.js").read_text(encoding="utf-8"))
OTHERS = [code for code in LANGS if code != "en"]
# Intl.PluralRules never answers "one" in these, so their ".one" forms would never be read.
NO_ONE = {"zh-CN", "zh-TW", "ja", "ko"}
HOLE = re.compile(r"\{(\w+)\}")
# Names, units and symbols that read the same in every language.
SAME_EVERYWHERE = {"reelsmith watch", "{n} fps", "{n} s", "s"}
# Words a language shares with English by its own right (French and German editors say "clip" and "timeline").
SAME_IN = {
    "fr": {"Agent", "Animation", "Clip", "Films", "Pause", "Session", "Timeline", "Transcription", "Type", "Volume",
           "{n} clips", "{n} films"},
    "de": {"Agent", "Animation", "Clip", "Import", "Layout", "Pause", "Text", "Video"},
    "es": {"Clip", "Error", "Video", "video", "{n} clips", "1 clip", "1 error"},
}
# The glossary, enforced: terms a language must not use because it settled on another for the same thing.
NOT_THE_TERM = {
    "zh-CN": [r"代理", r"请求(?!修正)", r"播放指针", r"时间轴(?!卡片)"],
    "zh-TW": [r"成片", r"视频|視頻", r"软件|軟件", r"文件(?!夾)", r"播放頭", r"渲染", r"請求", r"[这们说后为]"],
    "ja": [r"レンダリング", r"リクエスト", r"検査"],
    "ko": [r"컷"],
    "es": [r"vídeo", r"fragmento", r"tramo(?!s suprimidos|\s+suprimido)", r"[Pp]ulse\b", r"[Dd]escriba", r"[Vv]uelva a"],
    "fr": [r"séquence", r"[Aa]ppuyez", r"[Vv]euillez", r"\bnarration"],
    "de": [r"Timeline", r"\bStille Abschnitte", r"während der \{stage\}"],
}


def load(code: str) -> dict:
    """A dictionary file is `export default { "key": "value", ... };` with JSON strings."""
    src = (STATIC / "i18n" / f"{code}.js").read_text(encoding="utf-8")
    body = src[src.index("export default {") + len("export default "):src.rindex("}") + 1]
    body = re.sub(r"^\s*//.*$", "", body, flags=re.M)
    body = re.sub(r",(\s*)\}$", r"\1}", body)

    def unique(pairs):
        keys = [k for k, _ in pairs]
        dup = {k for k in keys if keys.count(k) > 1}
        assert not dup, f"{code}: duplicate keys {sorted(dup)}"
        return dict(pairs)
    return json.loads(body, object_pairs_hook=unique)


EN = load("en")


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


def test_every_key_the_page_names_exists():
    src = "".join(p.read_text(encoding="utf-8") for p in [*STATIC.glob("*.js"), STATIC / "index.html", STATIC / "home.html"]
                  if not p.name.startswith("i18n"))
    named = set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", src))
    named |= set(re.findall(r'data-i18n(?:-title)?="([\w.]+)"', src))
    assert sorted(named - EN.keys()) == []
