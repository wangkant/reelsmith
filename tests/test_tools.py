import asyncio
import importlib
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import types
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

import reelsmith
from reelsmith import cli, media, profiles
from reelsmith import render as R
from reelsmith import timeexpr as TE
from reelsmith import tools as T
from reelsmith.issues import Issue
from reelsmith.profiles import DOUYIN, Box

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
needs_tsc = pytest.mark.skipif(not shutil.which("node") or not (R.RENDERER / "node_modules" / "typescript").is_dir(),
                               reason="node or the renderer's typescript missing")
TINY = replace(DOUYIN, name="tiny", width=108, height=192, safe=Box(8, 20, 92, 150), min_s=1, max_s=30,
               target_s=(1, 10), lufs=-16.0, max_still_s=2.0)
META = {"title": "油价为什么又涨了", "desc": "一句 #油价", "topic": "油价", "shape": "",
        "sources": [{"title": "示例日报", "url": "https://www.example.org/x"}]}
SPEC_TOOLS = {"manual", "describe", "edit", "undo", "check", "library", "preview", "render", "review", "speak",
              "capture", "draw", "animate", "import_asset", "assets", "notes", "note", "typecheck"}


def fake_module(monkeypatch, name, **attrs):
    mod = types.ModuleType(f"reelsmith.{name}")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, f"reelsmith.{name}", mod)
    return mod


def write_png(path: Path, w=108, h=192, rgb=(200, 60, 40)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_film(path: Path, seconds=3, audio=True, still=False):
    src = f"color=c=0x3366aa:s=108x192:r=30:d={seconds}" if still else f"testsrc2=s=108x192:r=30:d={seconds}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def tiny_resolved(seconds=3):
    clips = [{"id": "bg", "type": "image", "track": "v1", "from": 0, "dur": seconds * 30, "box": {}, "style": {},
              "keyframes": {}, "enter": None, "exit": None, "content": {}},
             {"id": "t1", "type": "text", "track": "v2", "from": 15, "dur": 45, "box": {}, "style": {},
              "keyframes": {}, "enter": None, "exit": None, "content": {"runs": [{"text": "钩子", "accent": False}]}}]
    return {"version": 2, "fps": 30, "width": 108, "height": 192, "durationInFrames": seconds * 30,
            "safe": {"x": 8, "y": 20, "w": 92, "h": 150}, "theme": {},
            "tracks": [{"id": "v1", "kind": "visual", "clips": clips}], "audio": [], "inspect": False}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project in a workspace, with fake document/resolve neighbours and the tiny profile."""
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    monkeypatch.setitem(profiles.PROFILES, "tiny", TINY)
    ws = tmp_path / "ws"
    (ws / "library" / "components").mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"profile": "tiny"}), encoding="utf-8")
    p = ws / "projects" / "oil"
    (p / "voice").mkdir(parents=True)
    (p / "voice" / "voice.json").write_text(json.dumps({"file": "voice.wav", "duration_s": 2.5, "lines": [
        {"i": 1, "text": "一", "t0": 0.0, "t1": 1.0}, {"i": 2, "text": "二", "t0": 1.2, "t1": 2.4}]}), encoding="utf-8")
    (p / "project.json").write_text(json.dumps({"version": 2, "voice": "voice/voice.json", "meta": META,
                                                "assets": {}, "tracks": []}), encoding="utf-8")
    state = types.SimpleNamespace(issues=[], resolved=tiny_resolved(), asked=[])

    def time_of(pr, value):
        # the resolver's Time reading, over the fixture's voice lines and resolved clips
        state.asked.append(value)
        r = state.resolved
        fps = r["fps"]
        clips = {c["id"]: TE.ClipTiming(c["from"] / fps, (c["from"] + c["dur"]) / fps)
                 for t in r["tracks"] for c in t.get("clips") or []}
        sched = TE.Schedule([(0.0, 1.0), (1.2, 2.4)], clips, duration=r["durationInFrames"] / fps)
        return TE.resolve(value, sched)
    fake_module(monkeypatch, "document", load=lambda pr: types.SimpleNamespace(meta=dict(META)),
                validate=lambda pr, doc: list(state.issues))
    fake_module(monkeypatch, "resolve", resolve=lambda pr: json.loads(json.dumps(state.resolved)), time_of=time_of,
                describe=lambda pr, at=None: f"window of {Path(pr).name} at {at}")
    state.path = p
    return state


# ------------------------------------------------------------------ basics
def test_tool_result_and_exceptions_become_text():
    @T.tool
    def explode():
        raise RuntimeError("disk full")
    r = explode()
    assert isinstance(r, str) and not r.ok and "disk full" in r
    assert T.ToolResult("x").ok


def test_missing_project_says_what_to_do(tmp_path):
    r = T.check(str(tmp_path / "nope"))
    assert not r.ok and "new_project" in r
    r = T.check("")
    assert not r.ok and "project must be" in r


def test_reelsmith_root_confines_projects(project, tmp_path, monkeypatch):
    monkeypatch.setenv("REELSMITH_ROOT", str(tmp_path / "elsewhere"))
    r = T.check(str(project.path))
    assert not r.ok and "outside" in r


def test_new_project(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    p = tmp_path / "ws" / "projects" / "n1"
    r = T.new_project(str(p), profile="douyin", title="标题")
    assert r.ok and "outside any workspace" in r
    for name in ("project.json", "script.md"):              # LF on Windows too
        raw = (p / name).read_bytes()
        assert b"\r\n" not in raw and raw.endswith(b"\n")
    doc = json.loads((p / "project.json").read_text(encoding="utf-8"))
    assert doc["version"] == 2 and doc["profile"] == "douyin" and doc["meta"]["title"] == "标题"
    assert doc["tracks"] == [] and doc["assets"] == {}
    assert (p / "assets").is_dir() and (p / "voice").is_dir() and (p / "script.md").is_file()
    assert not T.new_project(str(p)).ok
    bad = T.new_project(str(tmp_path / "n2"), profile="vine")
    assert not bad.ok and "unknown profile" in bad


def test_manual_is_served():
    r = T.manual()
    assert r.ok and "reelsmith" in r.lower()


# ------------------------------------------------------------------ check / describe / edit / undo
def test_check_text(project):
    r = T.check(str(project.path))
    assert r.ok and r.startswith("OK")
    project.issues = [Issue("error", "tracks[1]", "clip c3 overlaps c2")]
    r = T.check(str(project.path))
    assert not r.ok and r.startswith("BLOCKED: 1 error") and "[error] tracks[1]: clip c3 overlaps c2" in r


def test_describe_with_time_string(project):
    assert T.describe(str(project.path)) == "window of oil at None"
    assert T.describe(str(project.path), at="line:2+0.3") == f"window of oil at {1.2 + 0.3}"
    # every Time goes through the resolver's own reading (no second parser)
    assert T.describe(str(project.path), at="LINE:2") == "window of oil at 1.2" and "LINE:2" in project.asked
    # "clip:X.end" is X's last frame (the end itself is the frame after it)
    at = float(T.describe(str(project.path), at="clip:t1.end").rsplit(" ", 1)[1])
    assert TE.to_frame(at, 30) == 59
    assert T.describe(str(project.path), at="clip:t1.end-0.5") == "window of oil at 1.5"
    bad = T.describe(str(project.path), at="clip:nope")
    assert not bad.ok and "cannot read the time" in bad and "no clip 'nope'" in bad


def test_edit_passes_ops_and_reports(project, monkeypatch):
    seen = []

    def apply(pr, ops):
        seen.append(ops)
        if ops[0]["op"] == "remove_asset":
            return False, [Issue("error", "assets.a1", "used by clip c1")], ""
        return True, [Issue("advice", "hook", "no words")], "1 op: set meta.title"
    fake_module(monkeypatch, "ops", apply=apply)
    r = T.edit(str(project.path), [{"op": "set", "path": "meta.title", "value": "x"}])
    assert r.ok and r.startswith("applied: 1 op") and "[advice] hook" in r
    assert T.edit(str(project.path), '{"op": "set", "path": "meta.desc", "value": "y"}').ok
    assert seen[1] == [{"op": "set", "path": "meta.desc", "value": "y"}]
    r = T.edit(str(project.path), [{"op": "remove_asset", "id": "a1"}])
    assert not r.ok and r.startswith("REFUSED: nothing changed.") and "used by clip c1" in r
    for bad in ("[1, 2]", "{not json", [], [{"id": "x"}]):
        r = T.edit(str(project.path), bad)
        assert not r.ok and "op" in r


def test_undo_result_shapes(project, monkeypatch):
    fake_module(monkeypatch, "ops", undo=lambda pr, steps: (True, f"restored .history/000{steps}.json"))
    assert T.undo(str(project.path), 2) == "restored .history/0002.json"
    fake_module(monkeypatch, "ops", undo=lambda pr, steps: False)
    assert not T.undo(str(project.path)).ok
    fake_module(monkeypatch, "ops", undo=lambda pr, steps: "undid 1 batch")
    assert T.undo(str(project.path)) == "undid 1 batch"
    assert not T.undo(str(project.path), 0).ok


# ------------------------------------------------------------------ library, notes, providers
def test_library_list_and_detail(project, monkeypatch, tmp_path):
    meta = tmp_path / "Stamp.meta.json"
    meta.write_text(json.dumps({"name": "Stamp", "example": {"label": "涨"}}), encoding="utf-8")
    schema = {"type": "object", "required": ["label"],
              "properties": {"label": {"type": "string", "description": "the word on the stamp"},
                             "at": {"description": "Time it lands"}}}
    comp = types.SimpleNamespace(name="Stamp", description="A red stamp that lands. Use it for a verdict.",
                                 schema=schema, source="preset", path=str(meta))
    fake_module(monkeypatch, "library", components=lambda pr: {"Stamp": comp})
    r = T.library(str(project.path))
    # the list stays small: one line of description and the prop names, no schemas
    assert r.ok and "- Stamp (preset): A red stamp that lands.\n  props: label*, at" in r
    assert "the word on the stamp" not in r and "Use it for" not in r
    assert "components" in r and str(T.KIT_DOC) in r
    r = T.library(str(project.path), "Stamp")
    assert '"label": "涨"' in r and "Stamp.tsx" in r and "the word on the stamp" in r and str(T.KIT_DOC) in r
    assert not T.library(str(project.path), "Nope").ok


def test_notes_and_note(project, tmp_path):
    assert "no notes yet" in T.notes(str(project.path))
    assert T.note(str(project.path), "证据截图要裁到一句话").ok
    assert T.note(str(project.path), "second").ok
    text = T.notes(str(project.path))
    assert "证据截图要裁到一句话" in text and text.index("证据") < text.index("second") and "· oil" in text
    assert not T.note(str(project.path), "").ok
    assert not T.note(str(project.path), "x" * 5000).ok
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    (lonely / "project.json").write_text("{}", encoding="utf-8")
    assert not T.notes(str(lonely)).ok and not T.note(str(lonely), "x").ok


def test_providers_delegation(project, monkeypatch):
    calls = []

    def capture(pr, url, match="", id=""):
        calls.append(("capture", url, match, id))
        return f"captured {id}"

    def speak(pr, lines, gap_s=0.22):
        calls.append(("speak", lines, gap_s))
        return "voice/voice.wav: 2 lines"

    def draw(pr, **kw):
        raise RuntimeError("codex is not logged in: run codex login")

    def import_asset(pr, id, source, kind=None):
        calls.append(("import", id, source, kind))
        return f"kind must be one of image, video, audio; got {kind!r}", kind not in (None, "image")
    fake_module(monkeypatch, "providers", capture=capture, speak=speak, draw=draw, import_asset=import_asset,
                assets=lambda pr: ("no assets", False))
    r = T.capture(str(project.path), "https://example.com/a", "ev1")
    assert r.ok and calls[-1] == ("capture", "https://example.com/a", "", "ev1")  # empty match left to the default
    assert T.speak(str(project.path), '["一", {"text": "二", "pace": 0.9}]').ok
    assert calls[-1] == ("speak", ["一", {"text": "二", "pace": 0.9}], 0.22)
    r = T.speak(str(project.path), [])
    assert not r.ok and '["First line.", {"text": "Second line.", "pace": 0.95}]' in r and r.isascii()
    r = T.draw(str(project.path), "img1", "a pump")
    assert not r.ok and "codex login" in r
    assert T.assets(str(project.path)) == "no assets"
    r = T.animate(str(project.path), "v1", "img1", "slow push")
    assert not r.ok and "no animate()" in r
    assert not T.capture(str(project.path), "file:///etc/passwd", "ev2").ok
    assert not T.capture(str(project.path), "https://x", "../evil").ok
    r = T.import_asset(str(project.path), "a", "x.png", "photo")              # (text, is_error=True) from the provider
    assert not r.ok and "got 'photo'" in r
    assert T.import_asset(str(project.path), "a", " x.png ").ok
    assert calls[-1] == ("import", "a", "x.png", None)


def test_providers_missing_package(project, monkeypatch):
    monkeypatch.setitem(sys.modules, "reelsmith.providers", None)       # import fails
    r = T.speak(str(project.path), ["一"])
    assert not r.ok and "unavailable" in r


# ------------------------------------------------------------------ preview / render / review with a fake render.mjs
class FakeNode:
    def __init__(self, items_for=None, film_audio=True, film_ok=True, film_still=False, inspect_fail=None,
                 browser_errors=(), on_inspect=None):
        self.calls = []
        self.items_for = items_for or (lambda f: [])
        self.film_audio, self.film_ok, self.film_still = film_audio, film_ok, film_still
        self.inspect_fail, self.browser_errors, self.on_inspect = inspect_fail, list(browser_errors), on_inspect

    def __call__(self, mode, resolved, project, out, frames=None, timeout=None):
        data = json.loads(Path(resolved).read_text(encoding="utf-8"))
        self.calls.append((mode, data["inspect"], list(frames or []), Path(resolved).name))
        out = Path(out)
        if mode == "inspect":
            if self.on_inspect:
                self.on_inspect()
            if self.inspect_fail:
                return dict(self.inspect_fail)
            out.mkdir(parents=True, exist_ok=True)
            rows = []
            for f in frames:
                write_png(out / f"still_{f:05d}.png")
                rows.append({"frame": f, "png": f"still_{f:05d}.png", "items": self.items_for(f)})
            (out / "inspect.json").write_text(json.dumps({"frames": rows}), encoding="utf-8")
            return {"ok": True, "frames": len(rows), "bundleMs": 1200, "browserErrors": self.browser_errors}
        if not self.film_ok:
            return {"ok": False, "stage": "bundle", "error": "Module not found: fs", "browserErrors": []}
        make_film(out, audio=self.film_audio, still=self.film_still)
        return {"ok": True, "out": str(out), "bundleMs": 900, "renderMs": 2000}


def text_item(clip, rect, words="钩子", **kw):
    return {"clip": clip, "track": "v2", "kind": "text", "rect": rect, "opacity": 1, "text": words, **kw}


@needs_ffmpeg
def test_preview(project, monkeypatch):
    node = FakeNode(items_for=lambda f: [text_item("t1", [10, 2, 60, 12])] if f == 36 else [])
    monkeypatch.setattr(R, "run_node", node)
    r = T.preview(str(project.path), [0, "line:2", "clip:t1.end-0.5", "end", 99])
    assert r.ok, r
    mode, inspect_flag, frames, name = node.calls[0]
    # its own copy: a preview never rewrites the resolved.json a render reads
    assert (mode, inspect_flag, name) == ("inspect", True, "resolved.preview.json")
    assert frames == [0, 36, 45, 89]                    # deduped, clamped, sorted
    assert "4 still(s) of a 3.0 s film" in r and "contact sheet" in r
    assert (project.path / "build" / "stills" / "contact.png").is_file()
    assert "t1 @ 1.2s" in r and "outside the safe area (top)" in r and "would block render" in r


def test_preview_frames_round_as_the_timeline_does(project, monkeypatch):
    # 0.75 s is frame 22.5; the timeline (to_frame) rounds halves up, Python's round() to even
    node = FakeNode()
    monkeypatch.setattr(R, "run_node", node)
    monkeypatch.setattr(R, "_sheet", lambda *a, **k: None)
    assert T.preview(str(project.path), [0.75, "clip:t1.end", "clip:t1.end-0.1", "end"]).ok
    # "clip:t1.end" is t1's last frame (59), not the first frame after it; an offset is taken as written
    assert node.calls[0][2] == [23, 57, 59, 89]


def test_preview_keeps_earlier_stills(project, monkeypatch):
    monkeypatch.setattr(R, "run_node", FakeNode())
    monkeypatch.setattr(R, "_sheet", lambda *a, **k: None)
    stills = project.path / "build" / "stills"
    assert T.preview(str(project.path), [0]).ok
    assert T.preview(str(project.path), [1]).ok
    assert (stills / "still_00000.png").is_file() and (stills / "still_00030.png").is_file()


@needs_ffmpeg
def test_preview_sweep_measures_the_whole_film_without_a_film(project, monkeypatch):
    # the per-second layout pass, before a render
    node = FakeNode(items_for=lambda f: [text_item("t1", [10, 2, 60, 12])] if f == 60 else [])
    monkeypatch.setattr(R, "run_node", node)
    r = T.preview(str(project.path), sweep=True)
    assert r.ok, r
    assert [c[0] for c in node.calls] == ["inspect"] and node.calls[0][2] == [0, 30, 60, 89]
    assert "sweep: measured 4 still(s)" in r and "t1 @ 2.0s" in r and "would block render" in r
    stills = project.path / "build" / "stills"
    assert (stills / "still_00060.png").is_file() and not (stills / "still_00030.png").exists()
    assert cli.main(["preview", str(project.path), "0.5", "--sweep"]) == 0       # asked times are kept too
    assert node.calls[-1][2] == [0, 15, 30, 60, 89] and (stills / "still_00015.png").is_file()


def test_preview_refuses_invalid_project_and_bad_times(project, monkeypatch):
    monkeypatch.setattr(R, "run_node", FakeNode())
    assert not T.preview(str(project.path), []).ok
    assert not T.preview(str(project.path), list(range(25))).ok
    r = T.preview(str(project.path), ["line:9"])
    assert not r.ok and "cannot read the time 'line:9'" in r and "2 line(s)" in r
    project.issues = [Issue("error", "tracks", "bad")]
    r = T.preview(str(project.path), [1])
    assert not r.ok and "does not validate" in r and "[error] tracks: bad" in r


def test_preview_leads_with_a_component_crash(project, monkeypatch):
    # the red error box is not measured as layout; the crash comes first, with its source line
    project.resolved["tracks"][0]["clips"].append(
        {"id": "k", "type": "component", "track": "v1", "from": 0, "dur": 90, "box": {}, "style": {}, "keyframes": {},
         "enter": None, "exit": None, "content": {"name": "ZzThrow", "props": {}}})
    node = FakeNode(items_for=lambda f: [text_item("k", [0, 0, 100, 30], "ZzThrow: Cannot read pro")],
                    browser_errors=["JSHandle@error", "component ZzThrow failed: TypeError: Cannot read properties of "
                                    "undefined (reading 'deep')\n    at ZzThrow (http://localhost:3000/bundle.js:9:1)"
                                    "\n    at ZzThrow (library/components/ZzThrow.tsx:3)  ->  return x.deep;",
                                    "Failed to load resource: assets/missing.png"])
    monkeypatch.setattr(R, "run_node", node)
    monkeypatch.setattr(R, "_sheet", lambda *a, **k: None)
    r = T.preview(str(project.path), [1])
    assert r.startswith("component ZzThrow crashed: TypeError: Cannot read properties of undefined"), r
    assert "ZzThrow.tsx:3" in r and "bundle.js" not in r and "JSHandle" not in r
    assert "layout: ok" in r and "missing.png" in r


def test_component_crash_reported_by_the_renderer_leads(project, monkeypatch):
    # the renderer's own shape for a crash (stage "component", source-mapped): no layout, no "render.mjs failed at"
    fail = {"ok": False, "stage": "component", "component": "ZzThrow", "source": "library/components/ZzThrow.tsx:3",
            "error": "component ZzThrow crashed at library/components/ZzThrow.tsx:3: TypeError: Cannot read "
                     "properties of undefined (reading 'deep')\n    at ZzThrow (library/components/ZzThrow.tsx:3)"}
    monkeypatch.setattr(R, "run_node", FakeNode(inspect_fail=fail))
    r = T.preview(str(project.path), [1])
    assert not r.ok and r.startswith("component ZzThrow crashed at library/components/ZzThrow.tsx:3: TypeError")
    assert "render.mjs failed" not in r and "typecheck" in r
    r = T.render(str(project.path))
    assert not r.ok and "stopped at component" in r and "component ZzThrow crashed at" in r and "layout" not in r


def test_preview_transient_failure_says_so(project, monkeypatch):
    fail = {"ok": False, "stage": "infra", "transient": True,
            "error": "Error: net::ERR_CONNECTION_ABORTED at http://localhost:3000/index.html"}
    monkeypatch.setattr(R, "run_node", FakeNode(inspect_fail=fail))
    r = T.preview(str(project.path), [1])
    assert not r.ok and "transient problem" in r and "not your project" in r and "(infra)" not in r


@needs_ffmpeg
def test_render_delivers_and_review(project, monkeypatch):
    node = FakeNode()
    monkeypatch.setattr(R, "run_node", node)
    r = T.render(str(project.path))
    assert r.ok, r
    assert r.startswith("DELIVERED:") and "108x192 30 fps, h264/aac" in r
    assert [c[0] for c in node.calls] == ["inspect", "film"]
    assert node.calls[0][2] == [0, 30, 60, 89] and node.calls[0][1] is True
    assert node.calls[1][1] is False and node.calls[1][3] == "resolved.film.json"
    out = project.path / "out"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert report["ok"] and report["film_check"]["lufs"] == pytest.approx(-16, abs=1.5)
    # per-stage timings (render.mjs's bundle time surfaced too)
    assert {"check", "layout", "layout_bundle", "film", "film_bundle", "master", "film_check"} <= set(report["timings"])
    assert report["timings"]["layout_bundle"] == 1.2 and "stages: check" in r
    # the latest attempt is always in build/report.json (a runner reads the newest outcome there)
    assert json.loads((project.path / "build" / "report.json").read_text(encoding="utf-8"))["ok"] is True
    assert meta["title"] == META["title"] and meta["profile"] == "tiny"
    assert meta["duration_s"] == pytest.approx(3, abs=.2)
    assert not (project.path / "build" / "film.raw.mp4").exists()
    assert list((project.path / "build" / "inspect").glob("*.png")) == []          # clean frames are dropped
    rv = T.review(str(project.path), 4)
    assert rv.ok and rv.count(".png") == 5 and "contact sheet" in rv


@needs_ffmpeg
def test_review_watches_the_film_a_second_at_a_time_with_the_voice(project, monkeypatch):
    line = lambda i, text, t0, t1: types.SimpleNamespace(i=i, text=text, t0=t0, t1=t1)  # noqa: E731
    (project.path / "out").mkdir()
    make_film(project.path / "out" / "film.mp4", seconds=10, still=True)
    monkeypatch.setattr(R, "_voice_lines", lambda root: [line(1, "一", 0.0, 1.0), line(2, "二", 1.2, 2.4)])
    rv = T.review(str(project.path))
    assert rv.ok, rv
    assert "10 frames, one every 1 s, on 2 sheet(s)" in rv
    assert "sheet 1, 0-7 s:" in rv and "sheet 2, 8-9 s:" in rv
    review = project.path / "build" / "review"
    assert sorted(p.name for p in review.glob("sheet_*.png")) == ["sheet_01.png", "sheet_02.png"]
    assert len(list(review.glob("watch_*.png"))) == 10
    assert "- 0 s: [1] 一" in rv and "- 1 s: (no voice)" in rv and "- 2 s: [2] 二" in rv
    assert "- 3-9 s: (no voice)" in rv
    assert "the picture does not change" in rv and "- 0-9 s" in rv          # one colour throughout
    quick = T.review(str(project.path), 3)                                   # n: the quick look, as before
    assert quick.ok and "contact sheet" in quick and not list(review.glob("sheet_*.png"))


@needs_ffmpeg
def test_frames_every_takes_the_frame_on_screen_at_each_mark(tmp_path):
    from PIL import Image
    film = tmp_path / "count.mp4"           # luma = 2 x the frame number, 30 fps
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=64x64:r=30:d=4,geq=lum='16+N*2':cb=128:cr=128", "-c:v", "libx264", "-qp", "0",
                    "-pix_fmt", "yuv420p", str(film)], check=True, capture_output=True)
    got = media.frames_every(film, 1.0, tmp_path / "out")
    assert [t for t, _ in got] == [0, 1, 2, 3]
    frame = [round((Image.open(p).convert("L").getpixel((32, 32)) * 219 / 255) / 2) for _, p in got]
    assert all(abs(n - 30 * t) <= 1 for (t, _), n in zip(got, frame)), frame     # not half a step later


@needs_ffmpeg
def test_render_keeps_its_own_resolved_and_holds_the_lock(project, monkeypatch):
    # a preview during a render waits, and cannot change what the film renders
    order = []
    started = []

    def preview_meanwhile():
        project.resolved["durationInFrames"] = 60           # the project changes, then a preview runs
        t = threading.Thread(target=lambda: order.append(("preview", T.preview(str(project.path), [0]).ok)))
        t.start()
        started.append(t)

    node = FakeNode(on_inspect=lambda: None if started else preview_meanwhile())
    real = node.__call__

    def tracked(mode, resolved, *a, **k):
        order.append((mode, json.loads(Path(resolved).read_text(encoding="utf-8"))["durationInFrames"]))
        return real(mode, resolved, *a, **k)
    monkeypatch.setattr(R, "run_node", tracked)
    monkeypatch.setattr(R, "_sheet", lambda *a, **k: None)
    r = T.render(str(project.path))
    started[0].join(30)
    assert r.ok, r
    assert order[:2] == [("inspect", 90), ("film", 90)]           # the film is what was measured
    assert order[2] == ("inspect", 60) and order[3] == ("preview", True)


@needs_ffmpeg
def test_render_layout_failure_keeps_previous_film(project, monkeypatch):
    (project.path / "out").mkdir()
    (project.path / "out" / "film.mp4").write_bytes(b"previous")
    node = FakeNode(items_for=lambda f: [text_item("t1", [10, 180, 60, 12], "底部")] if f == 30 else [])
    monkeypatch.setattr(R, "run_node", node)
    r = T.render(str(project.path))
    assert not r.ok and "NOT DELIVERED (stopped at layout)" in r and "previous out/film.mp4 is kept" in r
    assert "t1 @ 1.0s" in r and "still_00030.png" in r
    assert [c[0] for c in node.calls] == ["inspect"]                       # no film spent
    assert (project.path / "out" / "film.mp4").read_bytes() == b"previous"
    assert not (project.path / "out" / "report.json").exists()
    assert json.loads((project.path / "build" / "report.json").read_text(encoding="utf-8"))["stage"] == "layout"


def test_render_transient_failure_is_not_a_layout_problem(project, monkeypatch):
    # a dev-server socket error is the renderer's, retried, and said to be
    fail = {"ok": False, "stage": "infra", "transient": True, "retried": ["net::ERR_SOCKET_NOT_CONNECTED"],
            "error": "NetworkError: A network error occurred."}
    monkeypatch.setattr(R, "run_node", FakeNode(inspect_fail=fail))
    r = T.render(str(project.path))
    assert not r.ok and "transient problem" in r and "retried once" in r and "Run the same call again" in r
    assert "stopped at layout" not in r and "layout" not in r.split("\n")[0]
    rep = json.loads((project.path / "build" / "report.json").read_text(encoding="utf-8"))
    assert rep["stage"] == "infra" and rep["transient"] is True


def test_render_stops_on_a_component_crash(project, monkeypatch):
    project.resolved["tracks"][0]["clips"].append(
        {"id": "k", "type": "component", "track": "v1", "from": 0, "dur": 90, "box": {}, "style": {}, "keyframes": {},
         "enter": None, "exit": None, "content": {"name": "ZzThrow", "props": {}}})
    node = FakeNode(items_for=lambda f: [text_item("k", [0, 0, 100, 30], "ZzThrow: boom")],
                    browser_errors=["component ZzThrow failed: Error: boom"])
    monkeypatch.setattr(R, "run_node", node)
    r = T.render(str(project.path))
    assert not r.ok and "stopped at component" in r and "component ZzThrow crashed: Error: boom" in r
    assert "outside the safe area" not in r and [c[0] for c in node.calls] == ["inspect"]


@needs_ffmpeg
def test_render_failures_by_stage(project, monkeypatch):
    monkeypatch.setattr(R, "run_node", FakeNode(film_audio=False))
    r = T.render(str(project.path))
    assert not r.ok and "stopped at master" in r and "no sound" in r and "No film was delivered" in r
    monkeypatch.setattr(R, "run_node", FakeNode(film_ok=False))
    r = T.render(str(project.path))
    assert not r.ok and "stopped at film" in r and "Module not found: fs" in r
    monkeypatch.setattr(R, "run_node", FakeNode(film_still=True))
    r = T.render(str(project.path))
    assert not r.ok and "stopped at film_check" in r and "without any motion" in r
    assert (project.path / "build" / "film.rejected.mp4").is_file() and not (project.path / "out" / "film.mp4").exists()
    node = FakeNode()
    monkeypatch.setattr(R, "run_node", node)
    project.issues = [Issue("error", "clips.c1", "asset a9 missing")]
    r = T.render(str(project.path))
    assert not r.ok and "stopped at check" in r and "asset a9 missing" in r and node.calls == []


def test_review_without_film(project):
    r = T.review(str(project.path))
    assert not r.ok and "render first" in r


def test_run_node_reports_missing_result(monkeypatch, tmp_path):
    monkeypatch.setattr(R.media, "run_tree", lambda *a, **k: (1, "render 10%\n", "Error: boom\n", False))
    res = R.run_node("film", tmp_path / "r.json", tmp_path, tmp_path / "o.mp4")
    assert not res["ok"] and res["stage"] == "node" and "boom" in res["error"]
    monkeypatch.setattr(R.media, "run_tree", lambda *a, **k: (0, "x\n{\"ok\": true, \"files\": []}\n", "", False))
    assert R.run_node("stills", tmp_path / "r.json", tmp_path, tmp_path)["ok"]
    monkeypatch.setattr(R.media, "run_tree", lambda *a, **k: (1, "", "", True))
    assert R.run_node("film", tmp_path / "r.json", tmp_path, tmp_path / "o.mp4")["stage"] == "timeout"


def test_run_node_retries_a_transient_failure_once(monkeypatch, tmp_path):
    flaky = json.dumps({"ok": False, "stage": "render", "error": "Error: net::ERR_SOCKET_NOT_CONNECTED at "
                                                                 "http://localhost:3000/index.html"})
    flagged = json.dumps({"ok": False, "stage": "infra", "transient": True, "error": "Compositor error: frame"})
    bad = json.dumps({"ok": False, "stage": "render", "error": "TypeError: x is undefined"})
    good = json.dumps({"ok": True, "out": "o.mp4"})

    def runs(*outs):
        calls = []

        def run_tree(*a, **k):
            calls.append(1)
            return 1 if '"ok": false' in outs[len(calls) - 1] else 0, outs[len(calls) - 1] + "\n", "", False
        monkeypatch.setattr(R.media, "run_tree", run_tree)
        return calls
    calls = runs(flaky, good)
    res = R.run_node("film", tmp_path / "r.json", tmp_path, tmp_path / "o.mp4")
    assert res["ok"] and len(calls) == 2 and "ERR_SOCKET_NOT_CONNECTED" in res["retried"][0]
    calls = runs(flagged, flaky)
    res = R.run_node("film", tmp_path / "r.json", tmp_path, tmp_path / "o.mp4")
    assert not res["ok"] and len(calls) == 2 and res["stage"] == "infra" and res["transient"] is True
    assert "transient problem" in R.failure_text(res) and "render.mjs failed at" not in R.failure_text(res)
    calls = runs(bad, good)                                 # the project's own failure is not retried
    res = R.run_node("film", tmp_path / "r.json", tmp_path, tmp_path / "o.mp4")
    assert not res["ok"] and len(calls) == 1 and res["stage"] == "render" and not res.get("transient")


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259                        # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait(cond, seconds=20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


TREE = ("import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(sys.argv[1], 'w').write(str(c.pid))\n"
        "time.sleep(120)\n")


def test_run_tree_kills_the_whole_tree_when_interrupted(tmp_path, monkeypatch):
    # an aborted render must not leave node or the browser running
    pidfile = tmp_path / "child.pid"
    real = subprocess.Popen.communicate
    seen = {}

    def interrupted(self, *a, **k):
        if TREE not in self.args:
            return real(self, *a, **k)                  # taskkill and friends run as usual
        assert _wait(lambda: pidfile.is_file() and pidfile.read_text().strip())
        seen["child"], seen["parent"] = int(pidfile.read_text()), self.pid
        raise KeyboardInterrupt
    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        media.run_tree([sys.executable, "-c", TREE, str(pidfile)], timeout=60)
    monkeypatch.setattr(subprocess.Popen, "communicate", real)
    assert _wait(lambda: not _alive(seen["parent"]) and not _alive(seen["child"]))
    assert not media._LIVE


@pytest.mark.skipif(os.name != "nt", reason="the job object is the Windows guard")
def test_run_tree_children_die_with_their_parent(tmp_path):
    # the MCP server killed outright (no atexit, no except): the job object still takes node and Chrome down
    pidfile = tmp_path / "child.pid"
    script = (f"import sys; sys.path.insert(0, {str(Path(reelsmith.__file__).parent.parent)!r})\n"
              "from reelsmith import media\n"
              f"media.run_tree([sys.executable, '-c', {TREE!r}, {str(pidfile)!r}], timeout=120)\n")
    host = subprocess.Popen([sys.executable, "-c", script])
    try:
        assert _wait(lambda: pidfile.is_file() and pidfile.read_text().strip())
        child = int(pidfile.read_text())
        assert _alive(child)
        subprocess.run(["taskkill", "/F", "/PID", str(host.pid)], capture_output=True)    # the parent only
        assert _wait(lambda: not _alive(child)), "the grandchild outlived its killed parent"
    finally:
        host.kill()


@needs_ffmpeg
def test_contact_sheet_tiles_are_labelled(tmp_path):
    pngs = []
    for i in range(2):
        write_png(tmp_path / f"s{i}.png", rgb=(255, 255, 255))
        pngs.append(tmp_path / f"s{i}.png")
    plain = media.contact_sheet(pngs, tmp_path / "plain.png", [], (108, 192), (108, 192))
    labelled = media.contact_sheet(pngs, tmp_path / "labelled.png", [], (108, 192), (108, 192), labels=["0.00s", "1.50s"])
    from PIL import Image
    with Image.open(plain) as a, Image.open(labelled) as b:
        assert a.getpixel((8, 8)) != b.getpixel((8, 8)) and b.getpixel((8, 8))[0] < 60      # a dark chip


def test_node_env_points_at_the_workspace_library(project, monkeypatch, tmp_path):
    monkeypatch.setenv("REELSMITH_LIBRARY", "stale")
    env = R.node_env(project.path)
    assert env["REELSMITH_LIBRARY"] == str((project.path.parent.parent / "library" / "components").resolve())
    assert "REELSMITH_LIBRARY" not in R.node_env(tmp_path / "lonely")


# ------------------------------------------------------------------ typecheck (real tsc)
@needs_tsc
def test_typecheck_reports_only_library_errors(project):
    lib = project.path.parent.parent / "library" / "components"
    assert "nothing to check" in T.typecheck(str(project.path))
    (lib / "Good.tsx").write_text(
        'import React from "react";\nimport { useCurrentFrame } from "remotion";\n'
        "export default function Good({ props }: { props: any }) {\n  const f = useCurrentFrame();\n"
        "  return <div style={{ opacity: Math.min(1, f / 10) }}>{String(props.label ?? \"\")}</div>;\n}\n",
        encoding="utf-8")
    r = T.typecheck(str(project.path))
    assert r.ok and "no type errors" in r, r
    (lib / "Bad.tsx").write_text(
        "export default function Bad({ props }: { props: { n: number } }) {\n  const s: string = props.n;\n"
        "  return <div>{s}</div>;\n}\n", encoding="utf-8")
    r = T.typecheck(str(project.path))
    assert not r.ok and "components/Bad.tsx(2," in r and "TS2322" in r and "Good.tsx" not in r


# ------------------------------------------------------------------ MCP and CLI
def test_mcp_exposes_every_tool_with_descriptions():
    from reelsmith.mcp_server import mcp

    async def go():
        listed = {t.name: t for t in await mcp.list_tools()}
        bad = await mcp.call_tool("check", {"project": "Z:/definitely/not/here"})
        return listed, bad
    listed, bad = asyncio.run(go())
    assert SPEC_TOOLS <= set(listed)
    assert all(len(t.description) > 30 for t in listed.values())
    from reelsmith.ops import OPS
    assert [op for op in OPS if op not in listed["edit"].description] == []        # clients see only this text
    assert listed["preview"].input_schema["properties"]["times"]["type"] == "array"
    assert bad.is_error and "new_project" in bad.content[0].text


def test_cli_exit_codes_and_files(project, monkeypatch, tmp_path, capsys):
    assert cli.main(["check", str(project.path)]) == 0
    project.issues = [Issue("error", "x", "y")]
    assert cli.main(["check", str(project.path)]) == 1
    seen = []
    fake_module(monkeypatch, "ops", apply=lambda pr, ops: (seen.append(ops), (True, [], "ok"))[1])
    ops_file = tmp_path / "ops.json"
    ops_file.write_text('[{"op": "set", "path": "meta.title", "value": "t"}]', encoding="utf-8")
    assert cli.main(["edit", str(project.path), f"@{ops_file}"]) == 0
    assert seen == [[{"op": "set", "path": "meta.title", "value": "t"}]]
    assert cli.main(["edit", str(project.path), f"@{tmp_path / 'missing.json'}"]) == 2
    capsys.readouterr()


def test_cli_run_delegates_to_runner(monkeypatch):
    # `from . import runner` reads the package attribute first: once any test imported the real runner, a
    # sys.modules entry alone is bypassed, so the attribute is swapped too
    got = []
    fake = fake_module(monkeypatch, "runner", main=lambda argv=None: got.append(argv) or 0)
    monkeypatch.setattr(reelsmith, "runner", fake, raising=False)
    assert cli.main(["run", "p", "--brief", "油价"]) == 0
    assert got == [["p", "--brief", "油价"]]
    monkeypatch.delattr(reelsmith, "runner")
    monkeypatch.setitem(sys.modules, "reelsmith.runner", None)
    assert cli.main(["run", "p"]) == 2


def test_cli_run_delegates_after_the_real_runner_was_imported(monkeypatch):
    importlib.import_module("reelsmith.runner")             # the import order that the test above must survive
    test_cli_run_delegates_to_runner(monkeypatch)


@needs_ffmpeg
def test_render_delivers_a_silent_still_film_on_a_generic_profile(project, monkeypatch):
    monkeypatch.setitem(profiles.PROFILES, "tinyg", replace(TINY, name="tinyg", require_audio=False, max_still_s=None,
                                                            ui=False))
    (project.path.parent.parent / "workspace.json").write_text(json.dumps({"profile": "tinyg"}), encoding="utf-8")
    monkeypatch.setattr(R, "run_node", FakeNode(film_audio=False, film_still=True))
    r = T.render(str(project.path))
    assert r.ok, r
    report = json.loads((project.path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["master"] == "silent film: not mastered" and "a silent film" in " ".join(report["film_check"]["notes"])
