"""Every agent-facing tool (spec 10) as a plain function returning text. The MCP server, the CLI and the runner call
these. No tool raises: a failure comes back as text that says what to do, with `ok` False on the result."""
import functools
import importlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import locales
from . import render as R
from .checks import check_project
from .media import run_tree
from .profiles import ProfileError, choose, fps_label, parse_canvas
from .workspace import PROJECT_FILE, WorkspaceError, find_workspace, profile_for, project_root

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "docs" / "manual.md"
KIT_DOC = ROOT / "docs" / "kit.md"
MAX_NOTE_CHARS = 4000
MAX_NOTES_SHOWN = 30000
MAX_LINES = 60
SHEET_KEY = "dark bands = outside the safe area (the platform's UI or the title-safe margin), yellow line = its edge"
TYPECHECK_TIMEOUT_S = 5 * 60


class ToolResult(str):
    """The text a tool returns; `ok` is False when the call failed or found blocking problems."""
    ok: bool = True

    def __new__(cls, text: str, ok: bool = True):
        obj = super().__new__(cls, text)
        obj.ok = ok
        return obj


class ToolInputError(ValueError):
    """The call's arguments cannot be used; the message says how to call it."""


def _ok(text: str) -> ToolResult:
    return ToolResult(text, True)


def _fail(text: str) -> ToolResult:
    return ToolResult(text, False)


def _mod(name: str):
    return importlib.import_module(f"{__package__}.{name}")


def tool(fn):
    """Turn every exception into actionable text; plain strings become ok results."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except (ToolInputError, R.RenderError) as exc:
            return _fail(str(exc))
        except WorkspaceError as exc:
            return _fail(f"workspace problem: {exc}")
        except ModuleNotFoundError as exc:
            return _fail(f"{fn.__name__} is unavailable: module {exc.name} is missing from this reelsmith install. "
                         "Tell the operator; other tools still work.")
        except Exception as exc:  # noqa: BLE001 - nothing may reach the client as an exception
            return _fail(f"{fn.__name__} failed: {type(exc).__name__}: {exc}")
        if isinstance(result, ToolResult):
            return result
        return _ok(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1))
    return wrapper


def _project(project: str, must_exist: bool = True) -> Path:
    if not isinstance(project, str) or not project.strip():
        raise ToolInputError("project must be the path of a project folder (the folder holding project.json)")
    root = project_root(project.strip())
    allowed = os.environ.get("REELSMITH_ROOT")
    if allowed:
        base = Path(allowed).expanduser().resolve()
        if root != base and base not in root.parents:
            raise ToolInputError(f"{root} is outside {base}: projects must live inside it")
    if must_exist and not (root / PROJECT_FILE).is_file():
        hint = "create it with new_project" if not root.exists() else "write project.json there or call new_project"
        raise ToolInputError(f"no project at {root} ({PROJECT_FILE} missing): {hint}")
    return root


def _lines(rows: list, limit: int = MAX_LINES) -> str:
    rows = [str(r) for r in rows]
    if len(rows) > limit:
        rows = rows[:limit] + [f"... {len(rows) - limit} more"]
    return "\n".join(rows)


def _json_arg(value, what: str):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError as exc:
            raise ToolInputError(f"{what} is not valid JSON: {exc}") from exc
    return value


def _seconds(root: Path, value) -> float:
    """A Time argument in seconds, read as the project reads it (resolve.time_of); "clip:X.end" means X's last
    frame, where X still shows."""
    seconds = R.seconds_of(root, value)
    if R.ends_clip(value):
        seconds = max(0.0, seconds - 1 / profile_for(root).fps)
    return seconds


# ------------------------------------------------------------------ reading
@tool
def manual() -> str:
    """The reelsmith manual: how the editor works, the project format, Times, every tool, edit ops, components and
    what blocks delivery. Read it once before your first edit."""
    if not MANUAL.is_file():
        return _fail(f"the manual is missing at {MANUAL}; tell the operator")
    return MANUAL.read_text(encoding="utf-8")


@tool
def describe(project: str, at: float | str | None = None) -> str:
    """The editor's window as text: canvas, safe area, duration, voice lines, tracks bottom to top with their clips,
    assets and the latest issues. With `at` (seconds or a Time like "line:4"; "clip:c2.end" = c2's last frame),
    only what is on screen then."""
    root = _project(project)
    when = None if at is None or (isinstance(at, str) and not at.strip()) else _seconds(root, at)
    return _mod("resolve").describe(root, when)


@tool
def check(project: str) -> str:
    """Validate the project and apply the owner's rules. Errors block render; warnings and advice are information.
    Run it after a batch of edits and before render."""
    issues = check_project(_project(project))
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    advice = [i for i in issues if i.level == "advice"]
    if errs:
        head = f"BLOCKED: {len(errs)} error(s); render refuses until they are fixed."
    elif issues:
        head = f"OK: no errors ({len(warns)} warning(s), {len(advice)} advice; information only)."
    else:
        head = "OK: no issues."
    text = head + ("\n" + _lines(issues) if issues else "")
    return ToolResult(text, not errs)


@tool
def library(project: str, name: str = "") -> str:
    """The components a component clip can use (built-in presets and your own library): name, source, what it is
    and its prop names. With `name`, one component in full: props schema, example props and the source file to read
    as a model. Also gives the path of the @reelsmith/kit reference (docs/kit.md)."""
    root = _project(project)
    comps = _mod("library").components(root)
    kit = f"@reelsmith/kit (what a component can import) is documented in {KIT_DOC}"
    if name:
        comp = comps.get(name)
        if comp is None:
            return _fail(f"no component {name!r}; there are: {', '.join(sorted(comps)) or 'none'}")
        return _component_text(comp, full=True) + "\n" + kit
    if not comps:
        return f"no components found (presets missing and the library is empty)\n{kit}"
    rows = [_component_text(comps[n], full=False) for n in sorted(comps)]
    ws = find_workspace(root)
    where = f"\nYour own components go in {ws.components_dir} (Name.tsx + Name.meta.json)." if ws else ""
    return (f"{len(rows)} component(s) (props: * = required; library(project, name) gives one in full):\n"
            + "\n".join(rows) + where + f"\n{kit}")


def _component_meta(comp) -> dict:
    path = Path(str(getattr(comp, "path", "") or ""))
    name = getattr(comp, "name", "")
    meta = path if path.name.endswith(".meta.json") else path.with_name(f"{name}.meta.json")
    try:
        return json.loads(meta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _first_sentence(text: str, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    m = re.match(r"^(.+?[.。!?！？])(\s|$)", text)
    text = m.group(1) if m else text
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _prop_names(schema: dict) -> str:
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not props:
        return "(none)" if isinstance(schema, dict) and schema.get("additionalProperties") is False else "(any)"
    required = set(schema.get("required") or [])
    return ", ".join(f"{k}*" if k in required else k for k in props)


def _component_text(comp, full: bool) -> str:
    name, src = getattr(comp, "name", "?"), getattr(comp, "source", "?")
    desc = getattr(comp, "description", "") or ""
    schema = getattr(comp, "schema", None) or {}
    problem = getattr(comp, "problem", "") or ""
    if not full:
        bad = f"\n  cannot be used: {problem}" if problem else ""
        return f"- {name} ({src}): {_first_sentence(desc)}\n  props: {_prop_names(schema)}{bad}"
    rows = [f"{name} ({src}): {desc}"] + ([f"cannot be used: {problem}"] if problem else []) + \
        ["props schema:", json.dumps(schema, ensure_ascii=False, indent=1)]
    example = _component_meta(comp).get("example")
    if example is not None:
        rows += ["example props:", json.dumps(example, ensure_ascii=False, indent=1)]
    path = Path(str(getattr(comp, "path", "") or ""))
    tsx = path.with_name(f"{name}.tsx") if path.name.endswith(".meta.json") else path
    if tsx.suffix == ".tsx":
        rows.append(f"source: {tsx}")
    return "\n".join(rows)


@tool
def notes(project: str) -> str:
    """Your own notes for this workspace (library/NOTES.md): what worked, what to avoid. Read them when you start."""
    root = _project(project)
    ws = find_workspace(root)
    if not ws:
        return _fail("this project is outside a workspace (no workspace.json above it): there are no notes")
    if not ws.notes_path.is_file() or not ws.notes_path.read_text(encoding="utf-8").strip():
        return "no notes yet: add what you learn with note"
    text = ws.notes_path.read_text(encoding="utf-8")
    if len(text) > MAX_NOTES_SHOWN:
        text = f"(showing the last {MAX_NOTES_SHOWN} characters)\n" + text[-MAX_NOTES_SHOWN:]
    return text


@tool
def note(project: str, text: str) -> str:
    """Append a dated note at the end of the workspace's library/NOTES.md for future work (a lesson, a preference,
    a fix). Keep it short and specific. To put it under a heading or reword old notes, edit NOTES.md with your
    file tools."""
    root = _project(project)
    text = (text or "").strip()
    if not text:
        raise ToolInputError("text is empty: write the note")
    if len(text) > MAX_NOTE_CHARS:
        raise ToolInputError(f"{len(text)} characters; a note takes at most {MAX_NOTE_CHARS}: keep it short")
    ws = find_workspace(root)
    if not ws:
        return _fail("this project is outside a workspace (no workspace.json above it): notes need a workspace")
    ws.notes_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with ws.notes_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n## {stamp} · {root.name}\n{text}\n")
    return f"noted in {ws.notes_path}"


# ------------------------------------------------------------------ editing
@tool
def new_project(project: str, profile: str = "", title: str = "", canvas: str = "", locale: str = "") -> str:
    """Create a project folder with an empty project.json (no tracks yet), assets/, voice/ and script.md.
    Put it in <workspace>/projects/<name> to get the workspace's library, rules and keys. profile: a profile name
    (landscape, vertical, square, portrait, youtube, douyin, douyin-long, tiktok, shorts, reels or one of the
    workspace's); empty takes the workspace's (else landscape). canvas: "WIDTHxHEIGHT" or "WIDTHxHEIGHT@FPS" (e.g.
    "1920x1080@25", "1920x1080@29.97") for a canvas of your own, starting from `profile` (or the workspace's): its
    safe area scales to the new size. locale: the film's language as a BCP-47 tag
    ("en", "zh-CN", "ja"); empty takes the workspace's (else en)."""
    root = _project(project, must_exist=False)
    if (root / PROJECT_FILE).is_file():
        return _fail(f"{root / PROJECT_FILE} already exists: edit it instead")
    ws = find_workspace(root)
    custom, own = (ws.profiles, ws.config.get("profile")) if ws else (None, None)
    value = None
    try:
        if canvas:
            base = profile or (own if isinstance(own, str) else "")
            value = {**({"base": base} if base else {}), **parse_canvas(canvas)}
        elif profile:
            value = profile
        made = choose(value, own, custom)
    except ProfileError as exc:
        raise ToolInputError(str(exc)) from None
    if locale:
        try:
            locale = locales.check(locale)
        except ValueError as exc:
            raise ToolInputError(str(exc)) from None
    doc = {"version": 2, **({"profile": value} if value else {}), **({"locale": locale} if locale else {}),
           "meta": {"title": title, "desc": "", "topic": "", "shape": "", "sources": []}, "assets": {}, "tracks": []}
    for sub in ("assets", "voice"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    # LF on every OS: the files are diffed, hashed and edited by tools that expect it
    (root / PROJECT_FILE).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                                     newline="\n")
    script = root / "script.md"
    if not script.exists():
        script.write_text("# Research, sources and script\n", encoding="utf-8", newline="\n")
    where = f"in workspace {ws.root}" if ws else "outside any workspace (no library, default rules, keys from env)"
    s = made.safe
    return (f"created {root / PROJECT_FILE} {where}: {made.name} {made.width}x{made.height} {fps_label(made.fps)} "
            f"fps, safe area x {s.x}-{s.x + s.w}, y {s.y}-{s.y + s.h}")


def _ops_arg(ops) -> list[dict]:
    ops = _json_arg(ops, "ops")
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise ToolInputError('ops must be a list of edit ops, e.g. '
                             '[{"op": "set", "path": "meta.title", "value": "..."}]')
    for n, op in enumerate(ops):
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            raise ToolInputError(f"ops[{n}] must be an object with an \"op\" name (add_clip, update_clip, ...)")
    return ops


@tool
def edit(project: str, ops: list[dict] | str) -> str:
    """Apply a batch of edit ops atomically: all apply and validate, or nothing changes. Ops: add_track,
    update_track, remove_track, add_clip, update_clip, remove_clip, move_clip, split_clip, set_keyframes, add_asset
    (an existing id is replaced), update_asset ({"op": "update_asset", "id", "set": {...}}: deep merge, null
    removes a key), remove_asset, set (see the manual). Ripple edits for footage: ripple_delete ({"start", "end",
    "tracks"?}: take a film range out and close the gap), insert_gap ({"at", "dur", "tracks"?}: open room),
    trim_clip ({"id", "in"?, "out"?, "ripple"?}: a clip's in/out, in source seconds for video and audio). Every
    applied batch can be undone."""
    root = _project(project)
    result = _mod("ops").apply(root, _ops_arg(ops))
    try:
        ok, issues, summary = result
    except (TypeError, ValueError):
        return str(result)
    issues = list(issues or [])
    if not ok:
        rows = ["REFUSED: nothing changed."] + [str(i) for i in issues] + ([summary] if summary else [])
        return _fail(_lines(rows))
    text = f"applied: {summary}" if summary else "applied"
    return text + ("\n" + _lines(issues) if issues else "")


@tool
def undo(project: str, steps: int = 1) -> str:
    """Undo the last `steps` edit batches: project.json goes back to the snapshot taken before them."""
    root = _project(project)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ToolInputError("steps must be a whole number >= 1")
    result = _mod("ops").undo(root, steps)
    if isinstance(result, tuple) and result and isinstance(result[0], bool):
        rows = [x for r in result[1:] if r for x in (r if isinstance(r, list) else [r])]
        return ToolResult(_lines(rows) or ("undone" if result[0] else "nothing to undo"), result[0])
    if isinstance(result, bool):
        return ToolResult("undone" if result else "nothing to undo", result)
    return str(result) if result is not None else f"undid {steps} step(s)"


# ------------------------------------------------------------------ looking and rendering
def _layout_rows(layout: list[str]) -> list[str]:
    if not layout:
        return ["layout: ok (no words outside the safe area, cut, overflowing, tiny, overlapping or low-contrast)"]
    errs = sum(1 for r in layout if r.startswith("[error]"))
    head = f"layout: {len(layout)} problem(s)" + (f", {errs} would block render" if errs else "")
    return [head] + layout


@tool
def preview(project: str, times: list[float | str] = [], sweep: bool = False) -> str:  # noqa: B006 - never mutated
    """Render stills at the given moments straight from the project (no full render): seconds or Times like
    "line:3", "clip:c2+0.5", "end-1" ("clip:c2.end" = c2's last frame). Up to 24 per call. Returns PNG paths (look
    at them with Read), a contact sheet with the platform's UI bands darkened and the safe area outlined, and
    measured layout problems. sweep=true also measures the whole film as render does before it encodes (a still
    every second, spread out on films over 10 minutes, plus one in any text or caption between them; no film is
    made): every layout problem that would stop render shows now, with stills of the flagged moments."""
    root = _project(project)
    if isinstance(times, str) and times.strip().startswith("["):
        times = _json_arg(times, "times")
    if times is None or times == "":
        times = []
    if not isinstance(times, list):
        times = [times]                     # one Time on its own
    res = R.preview(root, times, sweep=bool(sweep))
    if not res.get("ok"):
        if res.get("stage") == "component":         # leads with "component X crashed at File.tsx:N"
            return _fail(_lines([str(res.get("error"))], 120))
        head = "preview failed" if res.get("transient") else f"preview failed ({res.get('stage')})"
        return _fail(_lines(res.get("crashes", []) + [f"{head}: {res.get('error')}"] + res.get("issues", []), 120))
    rows = list(res.get("crashes") or [])
    if res.get("sweep"):
        sw = res["sweep"]
        every = "one a second" if sw.get("every_s", 1) <= 1 else f"one every {sw['every_s']:g} s"
        rows.append(f"sweep: measured {sw['measured']} still(s), {every} and one in any text or caption between them; "
                    f"kept {sw['kept']} (asked or flagged)")
    rows.append(f"{len(res['frames'])} still(s) of a {res['duration_s']} s film at {res['fps']:g} fps (look with Read):")
    rows += [f"- {f['t']:.2f}s (frame {f['frame']}): {f['png']}" for f in res["frames"]]
    if res.get("contact"):
        rows.append(f"contact sheet ({SHEET_KEY}; keep words out of the dark bands): {res['contact']}")
    rows += _layout_rows(res.get("layout") or [])
    rows += [f"note: {n}" for n in res.get("notes") or []]
    if res.get("browserErrors"):
        rows += ["browser errors (often a wrong asset path):"] + [f"- {e}" for e in res["browserErrors"][:10]]
    return _lines(rows, 160)


def _timing_text(rep: dict) -> str:
    """The main stages' seconds (the report has render.mjs's finer split)."""
    t = rep.get("timings") or {}
    parts = []
    for stage in ("check", "layout", "film", "master", "film_check"):
        if isinstance(t.get(stage), (int, float)):
            bundle = t.get(f"{stage}_bundle")
            parts.append(f"{stage.replace('_', ' ')} {t[stage]:g} s"
                         + (f" (bundle {bundle:g} s)" if isinstance(bundle, (int, float)) else ""))
    return f"stages: {', '.join(parts)}" if parts else ""


def _render_text(rep: dict) -> ToolResult:
    fc = rep.get("film_check") or {}
    issues = rep.get("issues") or []
    timing = _timing_text(rep)
    if rep.get("ok"):
        rows = [f"DELIVERED: {rep['film']} ({fc.get('duration_s')} s, {fc.get('width')}x{fc.get('height')} "
                f"{fc.get('fps'):g} fps, {fc.get('vcodec')}/{fc.get('acodec')}, {fc.get('lufs')} LUFS, "
                f"{fc.get('size_mb')} MB; rendered in {rep.get('render_s')} s). Look at it with review."]
        rows += [timing] if timing else []
        side = rep.get("sidecars") or {}
        for c in side.get("captions") or []:
            rows.append(f"captions {c['track']} ({c['language'] or 'no language'}"
                        f"{', hidden: file only' if c['hidden'] else ''}, {c['cues']} cue(s)): {c['srt']}, {c['vtt']}")
        if side.get("chapters"):
            rows.append(f"chapters ({len(side['chapters'])}, also in the mp4): "
                        f"{Path(rep['film']).parent / 'chapters.txt'}")
        rows += [f"note: {n}" for n in (fc.get("notes") or []) + (rep.get("notes") or [])]
        rows += [r for r in rep.get("layout") or []] + issues
        return _ok(_lines(rows))
    if rep.get("stage") == "infra":
        rows = [f"NOT DELIVERED: {rep.get('error')}"]
    else:
        rows = [f"NOT DELIVERED (stopped at {rep.get('stage')}): {rep.get('error')}"]
    rows += rep.get("crashes") or []
    if rep.get("stage") == "check":
        rows += issues
    rows += _layout_rows(rep["layout"])[1:] if rep.get("layout") else []
    rows += [f"film check: {p}" for p in fc.get("problems") or []]
    rows += [timing] if timing else []
    if rep.get("rejected_film"):
        rows.append(f"the rejected film (not delivered), to look at: {rep['rejected_film']}")
    if rep.get("layout_frames"):
        rows.append("stills of the flagged moments: " + ", ".join(rep["layout_frames"][:8]))
    rows.append("The previous out/film.mp4 is kept." if rep.get("kept_previous") else "No film was delivered.")
    rows.append(f"Full report: {Path(rep.get('project', '.')) / 'build' / 'report.json'}")
    return _fail(_lines(rows))


def _draft_text(res: dict) -> ToolResult:
    if not res.get("ok"):
        return _fail(_lines([f"DRAFT FAILED ({res.get('stage')}): {res.get('error')}"] + res.get("issues", [])))
    return _ok(f"DRAFT (not delivered): {res['film']} ({res['width']}x{res['height']}, {res['from_s']:.2f}-"
               f"{res['to_s']:.2f} s of the film; rendered in {res['render_s']:g} s). A quick look: fast-encoded, not "
               "mastered and not checked; render without draft delivers the film.")


@tool
def render(project: str, draft: bool = False, start: float | str = "", end: float | str = "",
           scale: float = R.DRAFT_SCALE) -> str:
    """Render the whole film to out/film.mp4: refuses on check errors; measures text layout (the same pass as
    preview sweep=true); renders, masters loudness and runs the delivery checks; writes every captions track as
    out/captions/<track>.srt and .vtt and the chapters as out/chapters.txt. Anything failing keeps the previous film
    and says what to fix; a transient renderer failure is retried once and said to be one. Takes minutes: preview
    first. draft=true renders a quick low-quality look to build/draft.mp4 instead (no layout pass, no mastering, no
    delivery checks; out/ untouched): `scale` 0.1-1 of the canvas (default 0.5), `start`/`end` (seconds or Times)
    for a part of the film."""
    root = _project(project)
    if draft:
        return _draft_text(R.draft(root, start, end, scale))
    if start not in ("", None) or end not in ("", None):
        raise ToolInputError("start and end are for a draft (draft=true): a delivered film is always the whole film")
    return _render_text(R.render(root))


@tool
def review(project: str, n: int = 12) -> str:
    """Evenly spaced frames (2-24) from the delivered out/film.mp4 and a contact sheet, to judge the film as a viewer
    would."""
    res = R.review(_project(project), n)
    rows = [f"{len(res['frames'])} frame(s) of {res['film']} ({res['duration_s']} s), look with Read:"]
    rows += [f"- {f['t']:.2f}s: {f['png']}" for f in res["frames"]]
    if res.get("contact"):
        rows.append(f"contact sheet ({SHEET_KEY}): {res['contact']}")
    return ToolResult(_lines(rows), bool(res.get("ok")))


@tool
def export_captions(project: str, track: str = "") -> str:
    """Write captions as subtitle files without rendering: out/captions/<track>.srt (SubRip) and .vtt (WebVTT) for
    every captions track, or only `track`. A hidden captions track is written too: that is how a second language
    ships as a file only. Times are the film's as it stands; render writes the same files with the film."""
    res = R.export_captions(_project(project), track or None)
    if not res.get("ok"):
        return _fail(_lines([res["error"]] + res.get("issues", [])))
    rows = [f"wrote {len(res['files'])} captions track(s):"]
    rows += [f"- {f['track']} ({f['language'] or 'no language'}{', hidden' if f['hidden'] else ''}, {f['cues']} "
             f"cue(s)): {f['srt']}, {f['vtt']}" for f in res["files"]]
    return _lines(rows)


# ------------------------------------------------------------------ typecheck
def _typecheck_config(ws, renderer: Path) -> Path:
    nm = (renderer / "node_modules").as_posix()
    kit = (renderer / "src" / "kit").as_posix()
    comp = ws.components_dir.as_posix()
    cfg = {
        "compilerOptions": {
            "target": "ES2022", "module": "ES2022", "moduleResolution": "bundler", "jsx": "react-jsx",
            "lib": ["DOM", "DOM.Iterable", "ES2022"], "strict": True, "noEmit": True, "skipLibCheck": True,
            "esModuleInterop": True, "forceConsistentCasingInFileNames": True, "types": [],
            "typeRoots": [f"{nm}/@types"],
            # the library sits outside the renderer: point bare imports at its node_modules (@types first, since a
            # package without types would otherwise win); the kit folder before a stray kit.tsx
            "paths": {"@reelsmith/kit": [f"{kit}/index", kit], "*": [f"{nm}/@types/*", f"{nm}/*"]},
        },
        "include": [f"{comp}/**/*.tsx", f"{comp}/**/*.ts"],
    }
    path = ws.cache_dir / "typecheck" / "tsconfig.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=1), encoding="utf-8", newline="\n")
    return path


@tool
def typecheck(project: str) -> str:
    """Type-check your own components (library/components/*.tsx) with the renderer's TypeScript, before a preview
    bundles them. Lists errors in your files; errors elsewhere are counted, not shown."""
    root = _project(project)
    ws = find_workspace(root)
    if not ws:
        return _fail("this project is outside a workspace: there is no component library to check")
    files = sorted(ws.components_dir.glob("*.ts*")) if ws.components_dir.is_dir() else []
    if not files:
        return f"no components in {ws.components_dir} yet: nothing to check"
    renderer = R.RENDERER
    tsc = renderer / "node_modules" / "typescript" / "bin" / "tsc"
    node = shutil.which("node")
    if not node or not tsc.is_file():
        return _fail(f"cannot type-check: {'node is not on PATH' if not node else f'{tsc} is missing'}")
    cfg = _typecheck_config(ws, renderer)
    rc, out, err, timed = run_tree([node, tsc, "-p", cfg, "--pretty", "false"], cwd=ws.library_dir,
                                   timeout=TYPECHECK_TIMEOUT_S)
    if timed:
        return _fail("the type check ran over 5 minutes and was stopped")
    rows = [r.strip() for r in (out + "\n" + err).splitlines() if r.strip()]
    errors = [r for r in rows if re.search(r"error TS\d+", r)]
    mine = [r for r in errors if r.replace("\\", "/").startswith("components/")]
    others = len(errors) - len(mine)
    if rc != 0 and not errors:
        return _fail(f"the type check did not run (exit {rc}): {_lines(rows[-10:], 10)}")
    elsewhere = (f" ({others} error(s) outside your library, in reelsmith's own code: not yours to fix)"
                 if others else "")
    if not mine:
        return f"{len(files)} file(s) in {ws.components_dir}: no type errors{elsewhere}"
    return _fail(f"{len(mine)} type error(s) in {ws.library_dir}{elsewhere}:\n{_lines(mine, 40)}")


# ------------------------------------------------------------------ providers (assets)
def _provider(name: str, root: Path, **kwargs) -> ToolResult:
    try:
        providers = _mod("providers")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith(f"{__package__}.providers"):
            return _fail(f"{name} is unavailable: reelsmith.providers is not installed. Tell the operator.")
        raise
    fn = getattr(providers, name, None)
    if not callable(fn):
        return _fail(f"{name} is unavailable: reelsmith.providers has no {name}(). Tell the operator.")
    result = fn(root, **{k: v for k, v in kwargs.items() if v is not None})
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], bool):
        return ToolResult(str(result[0]), not result[1])          # providers return (text, is_error)
    if isinstance(result, ToolResult):
        return result
    return _ok(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1))


def _id_arg(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$", value or ""):
        raise ToolInputError(f"{what} must be 1-64 letters, digits, _ or - (starting with a letter or digit)")
    return value


@tool
def speak(project: str, lines: list[str | dict], gap_s: float = 0.22) -> str:
    """Narrate: one item per voice line, a string or {"text", "pace"?, "emotion"?}. pace: "slower", "normal",
    "faster" or a speed factor 0.5-2 relative to normal (1.0 normal, 0.9 a little slower, 1.1 a little faster).
    emotion: a word or two (at most 20 characters, e.g. "surprised", "calm") passed to the voice as an
    instruction; how much it changes depends on the voice model. gap_s: silence between lines. Writes
    voice/voice.wav and voice/voice.json (line times), sets the project's voice if unset. Only changed lines cost
    money (cached). Paid: estimates first and refuses over budget."""
    lines = _json_arg(lines, "lines")
    if not isinstance(lines, list) or not lines:
        raise ToolInputError('lines must be a non-empty list, e.g. ["First line.", {"text": "Second line.", '
                             '"pace": 0.95}]')
    return _provider("speak", _project(project), lines=lines, gap_s=gap_s)


@tool
def capture(project: str, url: str, id: str, match: str = "", viewport: str = "") -> str:
    """Screenshot a web page as evidence asset `id` (assets/<id>.png), boxing the sentence that contains `match` (a
    short exact phrase from the page, 8-20 characters is safest; empty boxes the title). viewport: "phone" (430 CSS
    px wide) or "desktop" (1440 CSS px wide); empty follows the canvas (phone for vertical and portrait, desktop for
    landscape and square)."""
    if not re.match(r"^https?://", url or ""):
        raise ToolInputError("url must start with http:// or https://")
    if viewport not in ("", "phone", "desktop"):
        raise ToolInputError('viewport must be "phone", "desktop" or empty (follow the canvas)')
    return _provider("capture", _project(project), url=url, match=match or None, id=_id_arg(id),
                     viewport=viewport or None)


@tool
def draw(project: str, id: str, prompt: str, style_ref_asset: str = "", size: str = "") -> str:
    """Generate an original image asset `id` from `prompt` (optionally in the style of an image asset). size: an
    aspect "9:16", "2:3", "3:4", "4:5", "1:1", "4:3", "3:2", "16:9" (default: the one nearest the project's canvas),
    or pixels "WxH" with sides 256-4096. Paid or rate-limited depending on the provider; slow (minutes)."""
    if not (prompt or "").strip():
        raise ToolInputError("prompt is empty: describe the picture")
    return _provider("draw", _project(project), id=_id_arg(id), prompt=prompt,
                     style_ref_asset=style_ref_asset or None, size=size or None)


@tool
def animate(project: str, id: str, image_asset: str, motion: str, seconds: float = 4, camera: str = "") -> str:
    """Turn image asset `image_asset` into a short silent video asset `id` (2-12 s) in which `motion` happens
    (what moves in the picture). `camera`: push, pull, pan_left, pan_right, rise or still (default push).
    Paid: estimates first and refuses over budget; a submitted job is resumed, never bought twice."""
    if not (motion or "").strip():
        raise ToolInputError("motion is empty: say what moves in the picture")
    return _provider("animate", _project(project), id=_id_arg(id), image_asset=_id_arg(image_asset, "image_asset"),
                     motion=motion, seconds=seconds, camera=camera or None)


@tool
def import_asset(project: str, id: str, source: str, kind: str = "") -> str:
    """Bring a local file into assets/ (any size; hard-linked when it is on the project's drive, so a big recording
    is not stored twice, else copied), or download an http(s) image/video/audio (size-capped), and register it as
    asset `id` (an existing id of the same kind is replaced). `kind` image, video, audio or evidence (a page
    screenshot you have: its box is the whole picture until you set one with the update_asset edit op); empty
    detects it from the file. This is also how music gets in: import a file you are allowed to use."""
    if not (source or "").strip():
        raise ToolInputError("source is empty: give a file path or an http(s) url")
    return _provider("import_asset", _project(project), id=_id_arg(id), source=source.strip(), kind=kind or None)


@tool
def assets(project: str) -> str:
    """The project's assets with kinds, sizes and durations."""
    return _provider("assets", _project(project))


# ------------------------------------------------------------------ footage (looking at sources)
def _source_arg(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{what} must be an asset id (see assets) or a file inside the project folder")
    return value.strip()


@tool
def probe(project: str, source: str) -> str:
    """What a media file holds: container, duration, size; the picture's codec, resolution, fps, rotation and colour
    (primaries, transfer, matrix; an HDR source, PQ, HLG or Dolby Vision, is flagged: the film is SDR and not
    tone-mapped); the sound's codec, channels, sample rate and loudness (LUFS, range, true peak). `source` is an
    asset id or a file inside the project folder. Text, then the same facts as JSON."""
    return _provider("probe", _project(project), source=_source_arg(source, "source"))


@tool
def frames(project: str, asset: str, times: list[float | str] = [], every: float = 0,  # noqa: B006 - never mutated
           n: int = 0) -> str:
    """Stills of a SOURCE video (an asset id, or a file inside the project) at source seconds, not the film's:
    `times` (seconds or m:ss, up to 24), or one every `every` seconds, or `n` evenly spaced (default 12). Returns
    PNG paths (look at them with Read) and a contact sheet with each still's source time burned in. Use it to see
    what a recording holds before you cut it."""
    if isinstance(times, str) and times.strip().startswith("["):
        times = _json_arg(times, "times")
    if times in (None, "") or times == []:
        times = None
    elif not isinstance(times, list):
        times = [times]
    return _provider("frames", _project(project), asset=_source_arg(asset, "asset"), times=times,
                     every=every or None, n=n or None)


@tool
def scenes(project: str, asset: str, threshold: float = 0.3) -> str:
    """Shot cuts of a source video in source seconds (ffmpeg's scene score; `threshold` 0.01-0.99, lower finds
    softer cuts), every shot's start, end and length, and a contact sheet of each shot's first frame (look with
    Read). Returns text and JSON."""
    return _provider("scenes", _project(project), asset=_source_arg(asset, "asset"), threshold=threshold)


@tool
def silences(project: str, asset: str, min_s: float = 0.5, noise_db: float = -35) -> str:
    """Silent ranges of a source's sound (quieter than `noise_db` dB for at least `min_s` seconds) and the sound
    ranges between them, in source seconds: the cut list for jump cuts (ripple_delete with "src:<clip>@<seconds>"
    Times). Returns text and JSON."""
    return _provider("silences", _project(project), asset=_source_arg(asset, "asset"), min_s=min_s,
                     noise_db=noise_db)


@tool
def transcribe(project: str, asset: str, language: str = "", prompt: str = "") -> str:
    """Word-level transcript of a video or audio asset (what is said and when, in source seconds), saved as
    assets/<id>.transcript.json and linked from the asset. `language`: an ISO code such as "en" or "zh" (empty:
    detected); `prompt`: names and words to spell right. Captions can then follow it (captions track "source":
    "clip:<id>"). Paid with an API provider: estimates first and refuses over budget."""
    return _provider("transcribe", _project(project), asset=_id_arg(asset, "asset"), language=language or None,
                     prompt=prompt or None)


TOOLS = {f.__name__: f for f in (manual, describe, new_project, edit, undo, check, library, preview, render, review,
                                 export_captions, speak, capture, draw, animate, import_asset, assets, probe, frames,
                                 scenes, silences, transcribe, notes, note, typecheck)}
