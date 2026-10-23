import pytest

from reelsmith import timeexpr as T
from reelsmith.timeexpr import ClipTiming, Schedule, TimeError, TimeExpr

LINES = [(0.0, 2.0), (2.2, 4.0), (4.3, 7.5)]


# ------------------------------------------------------------------ parse
@pytest.mark.parametrize("value, expr", [
    (0, TimeExpr("abs", None, False, 0.0)),
    (12.5, TimeExpr("abs", None, False, 12.5)),
    ("3", TimeExpr("abs", None, False, 3.0)),
    (" 2.25 ", TimeExpr("abs", None, False, 2.25)),
    (".5", TimeExpr("abs", None, False, 0.5)),
    ("line:5", TimeExpr("line", 5, False, 0.0)),
    ("line:5.end", TimeExpr("line", 5, True, 0.0)),
    ("line:5+0.3", TimeExpr("line", 5, False, 0.3)),
    ("line:12.end - 1", TimeExpr("line", 12, True, -1.0)),
    ("Line:2", TimeExpr("line", 2, False, 0.0)),
    ("clip:c2", TimeExpr("clip", "c2", False, 0.0)),
    ("clip:c2.end-0.5", TimeExpr("clip", "c2", True, -0.5)),
    ("clip:hook_2.END", TimeExpr("clip", "hook_2", True, 0.0)),
    ("clip:a-b", TimeExpr("clip", "a-b", False, 0.0)),
    ("clip:a-b+1", TimeExpr("clip", "a-b", False, 1.0)),
    ("clip:c-1", TimeExpr("clip", "c", False, -1.0)),      # why clip ids may not end in -digits
    ("end", TimeExpr("end", None, False, 0.0)),
    ("end-2", TimeExpr("end", None, False, -2.0)),
    ("end + .25", TimeExpr("end", None, False, 0.25)),
])
def test_parse_forms(value, expr):
    assert T.parse(value) == expr


@pytest.mark.parametrize("value, hint", [
    (True, "not a Time"), (None, "not a Time"), ([1], "not a Time"), (-1, "before the film starts"),
    (float("inf"), "finite"), ("", "empty"), ("   ", "empty"), ("line:0", "count from 1"), ("line:x", "whole number"),
    ("line", "whole number"), ("clip:", "clip's id"), ("start", "film start is 0"), ("3s", "without a unit"),
    ("-2", "negative"), ("line:3+", "cannot read"), ("end*2", "cannot read"), ("clip:a.b", "cannot read"),
    ("line:2.start", "cannot read"),
])
def test_parse_errors_say_why(value, hint):
    with pytest.raises(TimeError) as e:
        T.parse(value)
    assert hint in str(e.value)
    if isinstance(value, str) and value.strip() and hint != "count from 1":
        assert '"line:N"' in str(e.value)        # the grammar comes with the error


def test_str_round_trips():
    for text in ("line:5", "line:5.end+0.3", "clip:c2.end-0.5", "end-2", "end", "clip:x+1.25"):
        assert str(T.parse(text)) == text
        assert T.parse(str(T.parse(text))) == T.parse(text)
    assert str(T.parse(3)) == "3"


def test_check_returns_reason_or_none():
    assert T.check("line:2") is None
    assert "cannot read" in T.check("lien:2")


# ------------------------------------------------------------------ resolve
def test_resolve_against_a_context():
    ctx = T.simple_context(LINES, {"a": (1.0, 3.0), "b": (3.0, 5.5)}, end=9.0)
    assert T.resolve(4, ctx) == 4.0
    assert T.resolve("line:2", ctx) == 2.2
    assert T.resolve("line:3.end", ctx) == 7.5
    assert T.resolve("line:2+0.3", ctx) == pytest.approx(2.5)
    assert T.resolve("clip:a.end", ctx) == 3.0
    assert T.resolve("clip:b-0.5", ctx) == 2.5
    assert T.resolve("end-2", ctx) == 7.0
    assert T.resolve(T.parse("end"), ctx) == 9.0


def test_resolve_errors():
    ctx = T.simple_context(LINES, {"a": (1.0, 3.0)}, end=9.0)
    with pytest.raises(TimeError, match="past the voice: it has 3 line"):
        T.resolve("line:4", ctx)
    with pytest.raises(TimeError, match="no clip 'zz'"):
        T.resolve("clip:zz", ctx)
    with pytest.raises(TimeError, match="before the film starts"):
        T.resolve("line:1-0.5", ctx)
    with pytest.raises(TimeError, match="no voice"):
        T.resolve("line:1", T.simple_context([], {}, end=3))


def test_to_frame_rounds_halves_up_like_math_round():
    assert T.to_frame(0.25, 10) == 3          # Python's round(2.5) would give 2
    assert T.to_frame(0.35, 10) == 4
    assert T.to_frame(5.62, 30) == 169
    assert T.to_frame(0, 30) == 0


def test_times_inside_a_clip():
    ctx = T.simple_context(LINES, {"a": (1.0, 3.0)}, end=9.0)
    assert T.counts_from_clip(0.5) and T.counts_from_clip("0.5") and not T.counts_from_clip("line:2")
    assert not T.counts_from_clip("soon") and not T.counts_from_clip(True)
    assert T.clip_seconds(0.5, 4.0, ctx) == 4.5                       # numbers count from the clip's start
    assert T.clip_seconds("line:2+0.3", 4.0, ctx) == pytest.approx(2.5)   # Time strings are absolute
    assert T.clip_frame(0.5, 120, 30, ctx) == 15
    assert T.clip_frame("line:3", 120, 30, ctx) == 129 - 120
    assert T.clip_frame("clip:a.end", 120, 30, ctx) == 90 - 120       # before the clip: negative frames
    with pytest.raises(TimeError):
        T.clip_frame(-1, 120, 30, ctx)


# ------------------------------------------------------------------ schedule
def sched(clips, duration=None, voice_end=None, lines=LINES):
    return Schedule(lines, {k: ClipTiming(*v) if isinstance(v, tuple) else v for k, v in clips.items()},
                    duration=duration, voice_end=voice_end)


def test_schedule_chains_references():
    s = sched({"a": ("line:2", "line:3"), "b": ("clip:a.end", None, 1.5), "c": ("clip:b+0.2", "clip:b.end")},
              voice_end=7.6)
    assert s.span("a") == (2.2, 4.3)
    assert s.span("b") == (4.3, pytest.approx(5.8))
    assert s.span("c") == (pytest.approx(4.5), pytest.approx(5.8))
    assert s.film_end() == pytest.approx(8.2)
    assert s.film_end_source() == "voice end + 0.6 s"


def test_schedule_reports_cycles_with_the_loop():
    s = sched({"a": ("clip:b", None, 1), "b": ("clip:c.end", None, 1), "c": ("clip:a", None, 1)}, duration=10)
    with pytest.raises(T.CycleError) as e:
        s.start("a")
    assert str(e.value).startswith("these times refer to each other in a cycle: "
                                   "clip:a -> clip:b -> clip:c.end -> clip:c -> clip:a;")
    with pytest.raises(TimeError, match="cycle"):
        s.start("c")                      # memoised, same answer
    self_ref = sched({"x": ("clip:x.end-1", None, 2)}, duration=10)
    with pytest.raises(TimeError, match="cycle"):
        self_ref.span("x")


def test_schedule_end_and_dur():
    s = sched({"a": (1, None, None)}, duration=5)
    with pytest.raises(TimeError, match="needs end"):
        s.end("a")


def test_film_end_from_duration_time():
    s = sched({"a": (0, "line:3.end")}, duration="line:3.end+1")
    assert s.film_end() == 8.5
    assert s.film_end_source() == "set by duration"
    with pytest.raises(TimeError, match="cycle"):
        sched({"a": (0, "end")}, duration="clip:a.end").film_end()
    with pytest.raises(TimeError, match="more than 0"):
        sched({}, duration=0).film_end()


def test_film_end_from_clips_skips_those_anchored_on_the_end():
    s = sched({"a": (0, 4), "b": (1, None, 5), "outro": ("end-1", "end"), "ghost": ClipTiming(0, 50, counts=False)},
              lines=[])
    assert s.film_end() == 6.0
    assert s.span("outro") == (5.0, 6.0)
    assert s.film_end_source() == "last clip end"
    assert s.span("ghost") == (0, 50)
    with pytest.raises(TimeError, match="no length"):
        sched({"only": ("end-1", "end")}, lines=[]).film_end()
    with pytest.raises(TimeError, match="no length"):
        sched({}, lines=[]).film_end()


def test_errors_name_the_clip_and_field():
    s = sched({"a": ("line:9", None, 1)}, duration=10)
    with pytest.raises(TimeError) as e:
        s.start("a")
    assert str(e.value).startswith("clip a start 'line:9': line:9 is past the voice")
