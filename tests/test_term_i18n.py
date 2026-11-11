"""The terminal's dictionaries: every language carries English's keys and placeholders, nothing left in English, the
window's terms, and a home table that stays aligned in every language."""
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from reelsmith.term import i18n
from reelsmith.watch.chat import REASONS
from reelsmith.term.session import Session, cells
from reelsmith.term.views import PlainView
from test_watch_i18n import NOT_THE_TERM, load as load_window

LANGS = list(i18n.LANGUAGES)
OTHERS = [code for code in LANGS if code != "en"]
EN = i18n.load("en")
HOLE = re.compile(r"\{(\w+)\}")
FIXTURE = Path(__file__).parent / "fixtures" / "demo"
# Commands, units and symbols that read the same in every language.
SAME_EVERYWHERE = {"/help", "{n} s", "{m} min {s} s"}
# Words a language shares with English by its own right.
SAME_IN = {
    "fr": {"Agent", "Animation", "Film", "Note", "Notes", "Plan", "Silences", "Transcription"},
    "de": {"Agent", "Animation", "Engine", "Film", "Import", "Name", "Plan"},
    "es": {"Error", "Manual", "Plan"},
}
# One concept, one word: the terminal says what the window says.
SAME_AS_WINDOW = {"head.language": "top.language", "who.agent": "chat.agent", "status.beats": "beats.title",
                  "status.issues": "tab.issues", "tool.render": "tool.render", "status.thinking": "chat.thinking",
                  "help.keys": "help.keys", "code.action.render.ok": "action.render.ok",
                  "code.chat.engine_unavailable": "chat.engine_unavailable", "side.left": "side.left",
                  "code.owner.elsewhere": "owner.elsewhere",
                  **{"why." + code: code for code in REASONS}}
NB = "  "


def holes(s: str) -> set:
    return set(HOLE.findall(s))


def test_every_language_has_a_dictionary():
    assert i18n.available() == LANGS


@pytest.mark.parametrize("code", OTHERS)
def test_same_keys_as_english(code):
    d = i18n.load(code)
    assert sorted(EN.keys() - d.keys()) == [] and sorted(d.keys() - EN.keys()) == []


@pytest.mark.parametrize("code", OTHERS)
def test_same_placeholders(code):
    d = i18n.load(code)
    assert [(k, EN[k], v) for k, v in d.items() if holes(v) != holes(EN[k])] == []


@pytest.mark.parametrize("code", LANGS)
def test_no_empty_value_and_no_control_character(code):
    d = i18n.load(code)
    assert [k for k, v in d.items() if not v.strip()] == []
    assert [k for k, v in d.items() if re.search(r"[\x00-\x1f\x7f]", v)] == []


@pytest.mark.parametrize("code", LANGS)
def test_register(code):
    assert [k for k, v in i18n.load(code).items() if "!" in v or "！" in v] == []


@pytest.mark.parametrize("code", OTHERS)
def test_nothing_left_in_english(code):
    d = i18n.load(code)
    allowed = SAME_EVERYWHERE | SAME_IN.get(code, set())
    left = [(k, v) for k, v in d.items() if v == EN[k] and v not in allowed and re.search(r"[^\W\d_]", HOLE.sub("", v))]
    assert left == []


@pytest.mark.parametrize("code", sorted(SAME_IN))
def test_allow_list_is_in_use(code):
    d = i18n.load(code)
    assert sorted(SAME_IN[code] - {v for k, v in d.items() if v == EN[k]}) == []


@pytest.mark.parametrize("code", LANGS)
def test_the_window_terms(code):
    d, w = i18n.load(code), load_window(code)
    norm = lambda s: s.replace(" ", " ")             # noqa: E731 - the terminal uses the wider no-break space
    assert [(k, d[k], w[wk]) for k, wk in SAME_AS_WINDOW.items() if norm(d[k]) != norm(w[wk])] == []


@pytest.mark.parametrize("code", sorted(set(NOT_THE_TERM) & set(LANGS)))
def test_glossary_terms(code):
    d = i18n.load(code)
    assert [(k, v) for k, v in d.items() for p in NOT_THE_TERM[code] if re.search(p, v)] == []


@pytest.mark.parametrize("code", LANGS)
def test_the_new_film_question_defaults_to_yes(code):
    d = i18n.load(code)
    letter = re.search(r"\[(\w)/n\]", d["new.confirm"]).group(1).lower()
    assert letter in d["yes.words"].split(",")


@pytest.mark.parametrize("code", LANGS)
def test_the_yes_answer_matches_the_question(code):
    d = i18n.load(code)
    words = d["yes.words"].split(",")
    letter = re.search(r"\[(\w)/N\]", d["start.create_ask"]).group(1)
    assert "y" in words and letter in words and all(w == w.strip().lower() and w for w in words)


def test_french_spaces_before_high_punctuation():
    d = i18n.load("fr")
    wrong = [(k, v) for k, v in d.items()
             if re.search(rf"(?<![{NB}])[;?!»]|«(?![{NB}])|(?<![{NB}\d}}]):|\s[{NB}]", v)]
    assert wrong == []


# ------------------------------------------------------------------ the session, read in each language
@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv(i18n.LANG_ENV, raising=False)
    monkeypatch.setenv(i18n.CONFIG_ENV, str(tmp_path / "config"))
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE, root / "projects" / "demo", ignore=shutil.ignore_patterns("build", ".history"))
    (root / "workspace.json").write_text(json.dumps({"runner": {"engine": "api"}}), encoding="utf-8")
    (root / "library" / "components").mkdir(parents=True)
    other = root / "projects" / "zh"
    shutil.copytree(root / "projects" / "demo", other)
    data = json.loads((other / "project.json").read_text("utf-8"))
    data.setdefault("meta", {})["title"] = "潮汐的秘密与海岸线上的灯塔守望者"
    (other / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def plain(start, lang, *lines):
    import io
    out, todo = io.StringIO(), list(lines)

    def reader(prompt, session):
        if not todo:
            raise EOFError
        return todo.pop(0)
    opts = {"engines_fn": lambda engine, ws: (engine == "api", "fake model")}
    Session(start, PlainView(out), reader, lang=lang, chat_options=opts, today=date(2026, 11, 11),
            window_ok=lambda: False).run()
    return out.getvalue()


@pytest.mark.parametrize("code", LANGS)
def test_the_home_table_lines_up_in_every_language(ws, code):
    t = i18n.Texts(code)
    lines = plain(ws, code, "/help").splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith(t("col.n") + "  " + t("col.name")))
    rows = lines[head:head + 3]
    starts = [cells(r[:r.index(w)]) for r, w in zip(rows, (t("col.film"), t("film.none"), t("film.none")))]
    assert len(set(starts)) == 1, rows
    assert len({cells(r) - cells(re.split(r" {2,}", r)[-1]) for r in rows}) == 1, rows      # the last column too
    text = "\n".join(lines)
    assert t("home.hint") in text and t("help.title") in text and t("keys.quit") in text
    assert text.count(t("home.title", workspace="ws")) == 1                   # nothing printed twice
