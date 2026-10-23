"""Preview stills with layout measurement, the delivered film (render, master, checks, layout) and a review sheet."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import media
from .checks import check_film, check_layout, check_project, load_and_validate
from .profiles import Profile, get_profile
from .timeexpr import TimeError, parse as parse_time, to_frame
from .workspace import PROJECT_FILE, find_workspace, profile_for, project_paths, project_root

ROOT = Path(__file__).resolve().parent.parent
RENDERER = Path(os.environ.get("REELSMITH_RENDERER") or ROOT / "renderer")
FILM_TIMEOUT_S = 40 * 60
STILLS_TIMEOUT_S = 15 * 60
MAX_PREVIEW_FRAMES = 24
KEEP_STILLS = 96                    # earlier previews' stills stay readable; the oldest go past this
SHEET_TILE = (360, 640)             # a third of 1080x1920: about what a phone shows at arm's length
LAYOUT_EVERY_S = 1.0
# One bundle or render at a time (they share the CPU and webpack's cache). Reentrant: render holds it from resolve
# to film, so a preview in between waits instead of changing what is rendered.
_NODE_LOCK = threading.RLock()
# render.mjs failures a plain retry fixes (its own "transient" flag says so; this catches older renderers)
_TRANSIENT = re.compile(r"net::ERR_(?:CONNECTION_\w+|SOCKET_NOT_CONNECTED|EMPTY_RESPONSE|NETWORK_CHANGED|ADDRESS_\w+)"
                        r"|NetworkError|ECONNRESET|ECONNREFUSED|EPIPE|socket hang up|Target closed|Session closed"
                        r"|Compositor error: No frame found", re.I)
_CRASH = re.compile(r"component (?P<name>[A-Za-z0-9_]+) failed: (?P<msg>.+)", re.S)
_MISSING = re.compile(r'component "(?P<name>[A-Za-z0-9_]+)" (?P<msg>(?:not found|\(\w+\) has no default export).*)',
                      re.S)


class RenderError(RuntimeError):
    """A request the platform cannot carry out as given; the message says what to do."""


def _mod(name: str):
    return importlib.import_module(f"{__package__}.{name}")


# ------------------------------------------------------------------ render.mjs
def _last_json(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
    return None


def node_env(project: Path) -> dict:
    """The environment for render.mjs: REELSMITH_LIBRARY = the workspace's components folder, when there is one."""
    env = dict(os.environ)
    env.pop("REELSMITH_LIBRARY", None)
    ws = find_workspace(project)
    if ws and ws.components_dir.is_dir():
        env["REELSMITH_LIBRARY"] = str(ws.components_dir)
    return env


def is_transient(res: dict) -> bool:
    """A failure a plain retry can fix (dev server, socket, network, compositor frame lookup), not the project's."""
    if res.get("ok"):
        return False
    if res.get("transient"):
        return True
    return bool(_TRANSIENT.search(f"{res.get('error') or ''}\n{res.get('log') or ''}"))


def _node_once(cmd: list, project: Path, mode: str, timeout: float) -> dict:
    rc, stdout, stderr, timed = media.run_tree(cmd, cwd=RENDERER, env=node_env(project), timeout=timeout)
    if timed:
        return {"ok": False, "stage": "timeout",
                "error": f"render.mjs {mode} ran over {timeout / 60:.0f} minutes and was stopped: the picture may be "
                         "too heavy (huge images, many blurred layers)"}
    res = _last_json(stdout)
    if res is None:
        return {"ok": False, "stage": "node", "error": f"render.mjs exited {rc} without a result:\n"
                                                       f"{media.tail(stdout + chr(10) + stderr, 25, 2500)}"}
    if not res.get("ok") and rc != 0 and stderr.strip():
        res.setdefault("log", media.tail(stderr, 15, 1500))
    return res


def run_node(mode: str, resolved: Path, project: Path, out: Path, frames: list[int] | None = None,
             timeout: float = STILLS_TIMEOUT_S) -> dict:
    """`node scripts/render.mjs <mode> <resolved> <project> <out> [frame...]`; its last JSON line, or a failure
    shaped like one ({"ok": false, "stage", "error"}). A transient failure is retried once; if it fails again the
    result has stage "infra" and "transient": true."""
    node = shutil.which("node")
    script = RENDERER / "scripts" / "render.mjs"
    if not node:
        return {"ok": False, "stage": "setup", "error": "node is not on PATH"}
    if not script.is_file():
        return {"ok": False, "stage": "setup", "error": f"{script} is missing"}
    cmd = [node, str(script), mode, str(Path(resolved).resolve()), str(Path(project).resolve()),
           str(Path(out).resolve()), *map(str, frames or [])]
    with _NODE_LOCK:
        res = _node_once(cmd, project, mode, timeout)
        if is_transient(res):
            first = str(res.get("error") or "").strip().splitlines()[:1]
            res = _node_once(cmd, project, mode, timeout)
            res["retried"] = first or ["transient failure"]
    if is_transient(res):
        res.update(stage="infra", transient=True)
    return res


def failure_text(res: dict) -> str:
    """render.mjs's failure in a few lines."""
    error = str(res.get("error") or "").strip()
    if res.get("transient"):
        during = f" during {res['during']}" if res.get("during") else ""
        return (f"the renderer had a transient problem{during} (its local server or browser, not your project); it "
                f"was retried once and failed again: {media.tail(error, 4, 600)}\nRun the same call again.")
    if res.get("stage") == "component":
        # render.mjs leads with "component X crashed at File.tsx:N: ..." and the source lines
        return f"{error}\n  (fix the component, typecheck, then preview that moment again)"
    rows = [f"render.mjs failed at {res.get('stage') or '?'}: {error}"]
    rows += [f"  browser: {e}" for e in _browser_errors(res)[:10]]
    if res.get("log"):
        rows.append(res["log"])
    return "\n".join(rows)


def _browser_errors(res: dict) -> list[str]:
    # "JSHandle@error" is the console's placeholder for an Error object: it says nothing
    return [e for e in res.get("browserErrors") or [] if str(e).strip() not in ("JSHandle@error", "")]


def component_crashes(res: dict) -> dict[str, str]:
    """{component name: what went wrong} from render.mjs's browser errors (stills draw a red box instead)."""
    out: dict[str, str] = {}
    for e in _browser_errors(res):
        m = _CRASH.search(str(e)) or _MISSING.search(str(e))
        if not m or m["name"] in out:
            continue
        lines = [ln.strip() for ln in m["msg"].strip().splitlines() if ln.strip()]
        where = [ln for ln in lines[1:] if ".tsx" in ln and "node_modules" not in ln][:2]
        out[m["name"]] = "\n    ".join(lines[:1] + where)
    return out


def crash_rows(crashes: dict[str, str]) -> list[str]:
    rows = [f"component {name} crashed: {msg}" for name, msg in crashes.items()]
    if rows:
        rows.append("  (its clips show a red error box: fix the component, typecheck, then preview that moment again)")
    return rows


def _crashed_clips(resolved: dict, crashes: dict) -> set[str]:
    return {c.get("id") for t in resolved.get("tracks") or [] for c in t.get("clips") or []
            if c.get("type") == "component" and (c.get("content") or {}).get("name") in crashes}


# ------------------------------------------------------------------ resolve and times
def _resolve(project: Path, inspect: bool, path: Path) -> dict:
    """resolve.resolve(project) with the inspect flag, written to `path` (a copy only this caller reads)."""
    resolved = _mod("resolve").resolve(project)
    resolved["inspect"] = inspect
    _write_json(path, resolved)
    return resolved


def ends_clip(value) -> bool:
    try:
        e = parse_time(value)
    except TimeError:
        return False
    return e.anchor == "clip" and e.at_end and not e.offset


def seconds_of(project: Path, value) -> float:
    """A Time in seconds (resolve.time_of); RenderError with the reason when it cannot be read."""
    try:
        return float(_mod("resolve").time_of(project, value))
    except (TimeError, ValueError) as exc:
        raise RenderError(f"cannot read the time {value!r}: {exc}") from exc


def frame_of(project: Path, value, fps: float, last: int) -> int:
    """The frame a Time shows (halves up, as the timeline rounds); "clip:X.end" is X's last frame."""
    f = to_frame(seconds_of(project, value), fps) - (1 if ends_clip(value) else 0)
    return min(last, max(0, f))


def _fresh_stills(folder: Path) -> None:
    """Ready for a new preview: this call's sheet and measurements only; earlier stills kept (the newest ones)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("inspect.json", "contact.png"):
        (folder / name).unlink(missing_ok=True)
    stills = sorted(folder.glob("still_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in stills[KEEP_STILLS:]:
        old.unlink(missing_ok=True)


def _clear(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)


def _read_inspect(out_dir: Path) -> dict:
    path = out_dir / "inspect.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RenderError(f"render.mjs reported ok but {path} is missing or unreadable ({exc})") from exc
    if not isinstance(data, dict):
        raise RenderError(f"{path} is not an object")
    for fr in data.get("frames") or []:
        png = fr.get("png")
        if png and not Path(png).is_absolute():
            fr["png"] = str(out_dir / png)
    return data


def _sheet(pngs: list, out: Path, profile: Profile, labels: list[str] | None = None) -> str | None:
    pairs = [(p, lab) for p, lab in zip(pngs, labels or [""] * len(pngs)) if p and Path(p).is_file()]
    s = profile.safe
    try:
        sheet = media.contact_sheet([p for p, _ in pairs], out, profile.outside_safe(), (profile.width, profile.height),
                                    SHEET_TILE, outline=(s.x, s.y, s.w, s.h), labels=[lab for _, lab in pairs])
    except RuntimeError:
        return None
    return str(sheet) if sheet else None


def layout_frames(resolved: dict, every_s: float = LAYOUT_EVERY_S) -> list[int]:
    fps = float(resolved.get("fps") or 30)
    total = int(resolved.get("durationInFrames") or 0)
    step = max(1, round(every_s * fps))
    return sorted(set(range(0, total, step)) | ({total - 1} if total else set()))


def _flagged(issues: list, fps: float) -> set[int]:
    """The frames issues point at ("clip @ 3.0s")."""
    return {to_frame(float(m.group(1)), fps) for i in issues for m in [re.search(r"@ ([\d.]+)s", i.where)] if m}


def _near(frame: int, flagged: set[int], fps: float) -> bool:
    return any(abs(frame - f) <= max(1, round(0.06 * fps)) for f in flagged)     # times are rounded to 0.1 s


def _keep_problem_frames(inspect: dict, issues: list, fps: float, keep: set[int] = frozenset()) -> list[str]:
    """Drop the measured stills nobody needs (a 60 s film makes ~60 full-size PNGs); keep those with an issue."""
    flagged = _flagged(issues, fps)
    kept = []
    for fr in inspect.get("frames") or []:
        png = fr.get("png")
        if not png:
            continue
        frame = fr.get("frame") or 0
        if frame in keep or _near(frame, flagged, fps):
            kept.append(png)
        else:
            Path(png).unlink(missing_ok=True)
    return kept


# ------------------------------------------------------------------ preview
def preview(project: str | Path, times: list | None, sweep: bool = False) -> dict:
    """Stills at the given Times straight from the project, measured: {ok, frames, contact, layout, ...}. With
    `sweep`, also the layout pass render makes (a still every second, not encoded): only flagged stills are kept."""
    root = project_root(project)
    paths = project_paths(root)
    times = list(times or [])
    if not times and not sweep:
        raise RenderError("give at least one time (seconds or a Time like \"line:3\" or \"clip:c2+0.5\"), or sweep "
                          "to measure the whole film")
    if len(times) > MAX_PREVIEW_FRAMES:
        raise RenderError(f"at most {MAX_PREVIEW_FRAMES} times per preview; split the request")
    _, issues = load_and_validate(root)
    bad = [str(i) for i in issues if i.level == "error"]
    if bad:
        return {"ok": False, "stage": "check", "error": "the project does not validate; fix these first",
                "issues": bad}
    profile = profile_for(root)
    with _NODE_LOCK:
        json_path = paths.build / "resolved.preview.json"
        resolved = _resolve(root, True, json_path)
        fps = float(resolved.get("fps") or profile.fps)
        last = max(0, int(resolved.get("durationInFrames") or 1) - 1)
        asked = {frame_of(root, t, fps, last) for t in times}
        frames = sorted(asked | (set(layout_frames(resolved)) if sweep else set()))
        _fresh_stills(paths.stills)
        res = run_node("inspect", json_path, root, paths.stills, frames)
    if not res.get("ok"):
        return {"ok": False, "stage": res.get("stage"), "error": failure_text(res),
                "transient": bool(res.get("transient")), "crashes": crash_rows(component_crashes(res))}
    try:
        inspect = _read_inspect(paths.stills)
    except RenderError as exc:
        return {"ok": False, "stage": "inspect", "error": str(exc)}
    crashes = component_crashes(res)
    layout = check_layout(inspect, profile, resolved, ignore=_crashed_clips(resolved, crashes))
    if sweep:
        kept = set(_keep_problem_frames(inspect, layout, fps, keep=asked))
        measured = len(inspect.get("frames") or [])
        inspect["frames"] = [fr for fr in inspect.get("frames") or [] if fr.get("png") in kept]
    shots = [{"frame": fr.get("frame"), "t": round((fr.get("frame") or 0) / fps, 2), "png": fr.get("png")}
             for fr in inspect.get("frames") or []]
    tiles = shots[:MAX_PREVIEW_FRAMES]
    out = {"ok": True, "fps": fps, "duration_s": round((resolved.get("durationInFrames") or 0) / fps, 2),
           "frames": shots, "layout": [str(i) for i in layout], "crashes": crash_rows(crashes),
           "contact": _sheet([s["png"] for s in tiles], paths.stills / "contact.png", profile,
                             [f"{s['t']:.2f}s" for s in tiles]),
           "browserErrors": [e for e in _browser_errors(res) if not (_CRASH.search(e) or _MISSING.search(e))],
           "notes": res.get("notes") or []}
    if res.get("retried"):
        out["notes"] = out["notes"] + [f"the renderer had a transient problem and was retried: {res['retried'][0]}"]
    if sweep:
        out["sweep"] = {"measured": measured, "kept": len(shots)}
    return out


# ------------------------------------------------------------------ render
def _has_audio(path: Path) -> bool:
    try:
        return any(s.get("codec_type") == "audio" for s in media.probe(path).get("streams") or [])
    except Exception:  # noqa: BLE001 - mastering will say what is wrong
        return True


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _replace(src: Path, dst: Path, tries: int = 6) -> None:
    """os.replace that waits out a short lock on `dst` (Windows: a player or a scanner holding it)."""
    for n in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(0.25 * (n + 1))


def _post_meta(root: Path, report: dict, profile: Profile) -> dict:
    try:
        data = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8-sig"))
        meta = dict(data.get("meta") or {})
    except (OSError, ValueError, AttributeError):
        meta = {}
    meta.update(duration_s=(report.get("film_check") or {}).get("duration_s"), profile=profile.name,
                film="film.mp4", rendered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return meta


def cut_digest(data: dict) -> str:
    """The project minus its post meta (title, sources...), which never reaches the film's pixels or sound."""
    body = {k: v for k, v in data.items() if k != "meta"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def film_inputs(root: Path) -> dict:
    """{cut, components}: recorded with a render so delivery can tell a meta edit or an unused component's edit
    from a change to the film. {} when project.json cannot be read."""
    try:
        data = json.loads((Path(root) / PROJECT_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    used = sorted({str(c.get("name")) for t in data.get("tracks") or [] if isinstance(t, dict)
                   for c in t.get("clips") or [] if isinstance(c, dict) and c.get("type") == "component"})
    return {"cut": cut_digest(data), "components": used}


def render(project: str | Path) -> dict:
    """The film into <project>/out/film.mp4, mastered and checked. Every attempt's report goes to build/report.json
    (the latest attempt, delivered or not); a delivered one also to out/report.json. On any failure the previous
    film stays. Returns the report: {ok, stage, film, issues, layout, film_check, timings, ...}."""
    started = time.time()
    root = project_root(project)
    paths = project_paths(root)
    timings: dict = {}
    report: dict = {"ok": False, "stage": "check", "project": str(root), "film": None,
                    "kept_previous": paths.film.is_file(), "timings": timings}
    clock = [started]

    def lap(stage: str, res: dict | None = None) -> None:
        now = time.time()
        timings[stage] = round(now - clock[0], 1)
        clock[0] = now
        node = (res or {}).get("timings") if isinstance((res or {}).get("timings"), dict) else \
            {"bundle": (res or {}).get("bundleMs")}
        for part, ms in node.items():          # render.mjs's own split (bundle, browser, frames)
            if isinstance(ms, (int, float)) and not isinstance(ms, bool):
                timings[f"{stage}_{part}"] = round(ms / 1000, 1)

    def finish(stage: str, error: str | None = None) -> dict:
        report.update(stage=stage, render_s=round(time.time() - started, 1))
        if error:
            report["error"] = error
        else:
            report.update(ok=True, film=str(paths.film), kept_previous=False)
            _write_json(paths.report, report)
        _write_json(paths.build / "report.json", report)
        return report

    def node_failed(stage: str, res: dict) -> dict:
        if res.get("transient"):
            report["transient"] = True
            return finish("infra", failure_text(res))
        if res.get("stage") == "component":
            report["crashes"] = [failure_text(res)]
            return finish("component", "a component crashed (listed in crashes): fix it and render again")
        return finish(stage, failure_text(res))

    with _NODE_LOCK:
        issues = check_project(root)
        report["issues"] = [str(i) for i in issues]
        report["inputs"] = film_inputs(root)
        lap("check")
        if any(i.level == "error" for i in issues):
            return finish("check", "the project has errors (listed in issues): fix them and render again")
        profile = profile_for(root)
        report["profile"] = profile.name
        # this render's own copies: a preview or check rewriting build/resolved.json cannot change them
        resolved = _resolve(root, False, paths.build / "resolved.film.json")
        inspect_json = paths.build / "resolved.inspect.json"
        _write_json(inspect_json, {**resolved, "inspect": True})
        fps = float(resolved.get("fps") or profile.fps)

        # layout first: a few stills cost far less than the film and are the usual failure
        _clear(paths.inspect)
        res = run_node("inspect", inspect_json, root, paths.inspect, layout_frames(resolved))
        if not res.get("ok"):
            return node_failed("layout", res)
        try:
            inspect = _read_inspect(paths.inspect)
        except RenderError as exc:
            return finish("layout", str(exc))
        crashes = component_crashes(res)
        layout = check_layout(inspect, profile, resolved, ignore=_crashed_clips(resolved, crashes))
        report["layout"] = [str(i) for i in layout]
        report["layout_frames"] = _keep_problem_frames(inspect, layout, fps)
        lap("layout", res)
        if crashes:
            report["crashes"] = crash_rows(crashes)
            return finish("component", "a component crashed while the layout was measured (listed in crashes): "
                                       "fix it and render again")
        if any(i.level == "error" for i in layout):
            return finish("layout", "words sit where the viewer cannot read them (listed in layout): fix and render "
                                    "again")

        raw, mastered = paths.build / "film.raw.mp4", paths.build / "film.mastered.mp4"
        raw.unlink(missing_ok=True)
        res = run_node("film", paths.build / "resolved.film.json", root, raw, timeout=FILM_TIMEOUT_S)
        if not res.get("ok"):
            return node_failed("film", res)
        if not raw.is_file():
            return finish("film", "render.mjs reported ok but wrote no film")
        lap("film", res)

    if not _has_audio(raw):
        return finish("master", "the film has no sound: add narration (speak) or an audio clip")
    try:
        media.master(raw, mastered, profile.lufs, profile.peak_db)
    except RuntimeError as exc:
        return finish("master", str(exc))
    finally:
        raw.unlink(missing_ok=True)
    lap("master")
    report["film_check"] = check_film(mastered, profile)
    lap("film_check")
    if not report["film_check"]["ok"]:
        rejected = paths.build / "film.rejected.mp4"
        _replace(mastered, rejected)                # kept to look at, never delivered
        report["rejected_film"] = str(rejected)
        return finish("film_check", f"the film fails delivery: {report['film_check']['why']}")
    paths.out.mkdir(parents=True, exist_ok=True)
    try:
        _replace(mastered, paths.film)
    except PermissionError:
        report["finished_film"] = str(mastered)
        return finish("deliver", f"{paths.film} is held open by another program (a video player?): close it and "
                                 f"render again (the finished film waits at {mastered})")
    report["film_check"]["path"] = str(paths.film)
    _write_json(paths.meta, _post_meta(root, report, profile))
    return finish("done")


# ------------------------------------------------------------------ review
def review(project: str | Path, n: int = 12) -> dict:
    """Evenly spaced frames from the delivered film and a contact sheet with the platform's UI bands darkened."""
    root = project_root(project)
    paths = project_paths(root)
    if not paths.film.is_file():
        raise RenderError("no out/film.mp4 yet: render first")
    n = max(2, min(MAX_PREVIEW_FRAMES, int(n)))
    length = media.duration(paths.film) or 0.0
    if length <= 0:
        raise RenderError(f"{paths.film} has no readable duration: render again")
    times = [round(length * (i + 0.5) / n, 2) for i in range(n)]
    _clear(paths.review)
    made = {f.name: f for f in media.frames_at(paths.film, times, paths.review)}
    shots = [{"t": t, "png": str(made[name])} for t in times if (name := f"frame_{t:07.2f}s.png") in made]
    try:
        profile = profile_for(root)
    except ValueError:
        profile = get_profile(None)
    return {"ok": bool(shots), "film": str(paths.film), "duration_s": round(length, 2), "frames": shots,
            "contact": _sheet([s["png"] for s in shots], paths.review / "contact.png", profile,
                              [f"{s['t']:.2f}s" for s in shots])}
