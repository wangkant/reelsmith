"""animate: a picture becomes a short silent clip whose first frame it is (OpenRouter image-to-video, seedance).

Money first: the estimate is reserved in the ledger (budget and balance floor checked under the ledger lock) before
anything is sent, and the accepted job is in the ledger from the moment it exists. A later call with the same
picture and motion polls that job instead of paying again, and a finished clip is never bought twice: one whose
download or conversion failed is collected again from its job.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import os
import shutil
import socket
import time
import urllib.error
import uuid
from pathlib import Path

from .config import (Context, ProviderError, check_id, check_replaceable, context, existing_asset, exe,
                     image_size, register_asset, run_tree, safe_tool, tail)
from .ledger import Ledger, Reservation, age_s
from .openrouter import KEY_NAME, ApiError, OpenRouter, Unreachable

CAMERA = {"push": "a very slow push in", "pull": "a very slow pull back", "pan_left": "a slow pan to the left",
          "pan_right": "a slow pan to the right", "rise": "a slow upward tilt", "still": "locked off, almost still"}
SHAPES = {"9:16": 9 / 16, "1:1": 1.0, "16:9": 16 / 9}      # the clip shapes seedance takes
# estimates: 720p was billed $0.10476 per 4 s, 480p $0.0487; 1080p is a guess from the pixel count
USD_PER_S = {"480p": 0.0125, "720p": 0.0275, "1080p": 0.062}
SECONDS = (2, 12)
MAX_MOTION_CHARS = 300
POLL_S = 8
TIMEOUT_S = 6 * 60          # seedance jobs can take a few minutes
DONE = ("completed", "failed", "cancelled", "expired", "gone")
RESERVE_STALE_S = 10 * 60   # a reservation never submitted after this is a dead call (it still counts as spent)
COLLECT = "collect"         # ledger status: finished and paid, the clip not yet downloaded


class VideoAPI:
    """What animate needs from a video provider."""
    name = "video"

    def balance(self) -> float: ...
    def submit(self, body: dict) -> dict: ...
    def poll(self, job: str, polling_url: str | None) -> dict: ...
    def fetch(self, job: str, done: dict) -> bytes: ...


class OpenRouterVideo(VideoAPI):
    name = "openrouter"

    def __init__(self, key: str, client: OpenRouter | None = None):
        self.client = client or OpenRouter(key)

    def balance(self):
        return self.client.balance()

    def submit(self, body):
        return self.client.submit_video(body)

    def poll(self, job, polling_url):
        return self.client.poll_video(job, polling_url)

    def fetch(self, job, done):
        return self.client.fetch_video(job, done)


def make_api(ctx: Context) -> VideoAPI:
    name = str(ctx.providers["video"].get("provider") or "openrouter")
    if name != "openrouter":
        raise ProviderError(f"video provider {name!r} is not available (workspace.json providers.video.provider); "
                            "available: openrouter")
    return OpenRouterVideo(ctx.key(KEY_NAME))


def prompt_for(motion: str, camera: str) -> str:
    motion = str(motion or "").strip().rstrip("。！!？?；;，, ")[:MAX_MOTION_CHARS] or \
        "subtle ambient motion, the light shifts slowly"
    return (f"Keep this exact illustration's style, palette, characters and composition. Gentle living motion: "
            f"{motion}. Camera: {CAMERA.get(camera, CAMERA['push'])}. "
            "No text, no new objects, no style change, no cuts.")


def maybe_accepted(exc: BaseException) -> bool:
    """A submit that failed while its answer was being read may have been taken; a 4xx, an edge 502/503 or a
    request never sent was not."""
    if isinstance(exc, ApiError):
        return exc.code == 504
    if isinstance(exc, Unreachable):
        return exc.maybe_sent
    if isinstance(exc, urllib.error.URLError):
        return isinstance(exc.reason, (socket.timeout, TimeoutError))
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionResetError, http.client.HTTPException, ValueError))


def estimate(cfg: dict, seconds: int) -> float:
    per_s = cfg.get("usd_per_s")
    if per_s is None:
        res = str(cfg.get("resolution") or "720p")
        if res not in USD_PER_S:
            raise ProviderError(f"no price known for resolution {res!r}; set providers.video.usd_per_s in "
                                "workspace.json")
        per_s = USD_PER_S[res]
    if isinstance(per_s, bool) or not isinstance(per_s, (int, float)) or per_s < 0:
        raise ProviderError("providers.video.usd_per_s must be a number >= 0")
    return round(float(per_s) * seconds, 6)


def first_frame(png: Path, workdir: Path, run=run_tree) -> tuple[str, str]:
    """The picture cut to the nearest clip shape, as a JPEG data URL; (url, shape)."""
    w, h = image_size(png)
    if not w or not h:
        raise ProviderError("cannot read the picture's size")
    shape = min(SHAPES, key=lambda k: abs(SHAPES[k] - w / h))
    a = SHAPES[shape]
    cw, ch = (round(h * a), h) if w / h > a else (w, round(w / a))
    jpg = workdir / "first.jpg"
    rc, _, err, _ = run([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(png), "-vf",
                         f"crop={cw}:{ch},scale=-2:'min(1280,ih)'", "-q:v", "3", str(jpg)], timeout=60)
    if rc != 0 or not jpg.is_file():
        raise ProviderError(f"cutting the first frame failed: {tail(err)}")
    return "data:image/jpeg;base64," + base64.b64encode(jpg.read_bytes()).decode("ascii"), shape


def _source(ctx: Context, image_asset) -> Path:
    check_id(image_asset, "image_asset")
    entry = existing_asset(ctx, image_asset)
    if entry is None or entry.get("kind") != "image":
        raise ProviderError(f"image_asset {image_asset!r} must be an image asset of this project (draw or import "
                            "one first; see assets)")
    path = (ctx.project / str(entry.get("path") or "")).resolve()
    if not path.is_file() or ctx.project not in path.parents:
        raise ProviderError(f"image_asset {image_asset!r}: its file {entry.get('path')!r} is missing")
    return path


def _seconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ProviderError(f"seconds must be a whole number (got {value!r})")
    if not SECONDS[0] <= value <= SECONDS[1]:
        raise ProviderError(f"seconds must be {SECONDS[0]}-{SECONDS[1]} (got {value})")
    return int(value)


def already_made(rows: list[dict], asset_id: str, key: str, assets_dir: Path) -> str | None:
    """The asset id whose clip file still holds this exact request's result (asset_id itself first), or None."""
    latest: dict[str, dict] = {}
    for row in rows:                    # file order: a later success for an asset replaced its file
        if row.get("status") == "success" and row.get("asset"):
            latest[str(row["asset"])] = row
    owners = [a for a, row in latest.items() if row.get("key") == key and (assets_dir / f"{a}.mp4").is_file()]
    if asset_id in owners:
        return asset_id
    return owners[-1] if owners else None


def in_progress(calls: dict, key: str) -> tuple[str, dict | None]:
    """("submitted", row) for an accepted job of this exact request that has no clip yet, still running or finished
    and paid but not downloaded ("collect"): poll it, never buy it again; ("reserved", row) while a parallel call is
    about to submit it; ("", None) otherwise."""
    state, found = "", None
    for rows in calls.values():
        last = rows[-1]
        if last.get("key") != key:
            continue
        job = str(last.get("job") or "")
        if last.get("status") in ("submitted", COLLECT) and job and not job.startswith("unknown-"):
            state, found = "submitted", last
        elif last.get("status") == "reserved" and age_s(rows[0].get("ts")) < RESERVE_STALE_S and not state:
            state, found = "reserved", last
    return state, found


def _copy(src: Path, dst: Path) -> None:
    part = dst.with_name(f".{dst.stem}.{uuid.uuid4().hex[:6]}.part.mp4")
    try:
        shutil.copyfile(src, part)
        os.replace(part, dst)
    finally:
        part.unlink(missing_ok=True)


def _resume(pending: dict, project_key: str, asset_id: str, est: float) -> Reservation:
    res = Reservation(str(pending["id"]), project_key, "animate", str(pending.get("provider") or "openrouter"),
                      float(pending.get("est_usd") or est),
                      {k: pending.get(k) for k in ("key", "model", "resolution", "seconds", "job", "polling_url",
                                                    "shape", "paid_usd") if pending.get(k) is not None})
    if pending.get("status") == COLLECT:
        res.fields["paid_usd"] = float(pending.get("cost_usd") or 0.0)
    res.fields["asset"] = asset_id
    return res


@safe_tool
def animate(project, id, image_asset, motion, seconds=4, *, camera="push", api: VideoAPI | None = None,
            sleep=time.sleep, timeout_s: float | None = None):
    """(text, is_error): assets/<id>.mp4, a silent clip that starts on image_asset's picture."""
    ctx = context(project)
    asset_id = check_id(id)
    png = _source(ctx, image_asset)
    motion = str(motion or "").strip()
    if not motion or len(motion) > MAX_MOTION_CHARS:
        return (f"motion must say what moves and how, in 1-{MAX_MOTION_CHARS} characters "
                "(e.g. 'steam rises from the cup, the cat's tail flicks')"), True
    if camera not in CAMERA:
        return f"camera must be one of {', '.join(CAMERA)} (got {camera!r})", True
    secs = _seconds(seconds)
    check_replaceable(ctx, asset_id, "video")
    cfg = ctx.providers["video"]
    model, resolution = str(cfg.get("model")), str(cfg.get("resolution") or "720p")
    est = estimate(cfg, secs)
    prompt = prompt_for(motion, camera)
    key = hashlib.sha1(png.read_bytes() + "|".join([prompt, model, resolution, str(secs)]).encode("utf-8")) \
        .hexdigest()[:16]
    out = ctx.assets_dir / f"{asset_id}.mp4"
    entry = {"path": f"assets/{asset_id}.mp4", "kind": "video", "note": f"from {image_asset}: {motion}"[:200]}
    timeout = float(timeout_s if timeout_s is not None else cfg.get("timeout_s") or TIMEOUT_S)
    job = _Job(ctx, ctx.ledger(), api, sleep, timeout)
    with job.ledger.locked():               # look and reserve as one step: parallel calls never buy one clip twice
        rows = [r for r in job.ledger.rows() if r.get("project") == ctx.project_key and r.get("tool") == "animate"]
        calls: dict[str, list[dict]] = {}
        for r in rows:
            calls.setdefault(str(r.get("id")), []).append(r)
        owner = already_made(rows, asset_id, key, ctx.assets_dir)
        state, pending = ("", None) if owner else in_progress(calls, key)
        res = None
        if not owner and state == "submitted":
            res = _resume(pending, ctx.project_key, asset_id, est)
        elif not owner and not state:
            res = job.reserve(est, key=key, asset=asset_id, model=model, resolution=resolution, seconds=secs)
    if owner:
        if owner != asset_id:
            _copy(ctx.assets_dir / f"{owner}.mp4", out)
        reg = register_asset(ctx, asset_id, entry)
        same = "" if owner == asset_id else f" (a copy of {owner!r}, made from the same request)"
        return (f"Animated {asset_id!r} already exists from this picture and motion{same}, no new charge: "
                f"{entry['path']}.{reg}"), False
    if state == "reserved":
        return (f"animate {asset_id!r}: an identical request is being submitted right now; call animate again with "
                "the same arguments in a minute to collect it (no new charge)."), True
    why = job.wait(res, out) if state == "submitted" else job.buy_and_wait(res, png, prompt, model, resolution,
                                                                          secs, out)
    return job.text(why, asset_id, entry, secs, resolution)


class _Job:
    def __init__(self, ctx: Context, ledger: Ledger, api: VideoAPI | None, sleep, timeout: float):
        self.ctx, self.ledger, self._api, self.sleep, self.timeout = ctx, ledger, api, sleep, timeout
        self.cost = 0.0
        self.shape = ""
        self.collect = False

    @property
    def api(self) -> VideoAPI:
        if self._api is None:           # lazily: a clip already made needs no key
            self._api = make_api(self.ctx)
        return self._api

    def reserve(self, est: float, **fields) -> Reservation:
        ctx = self.ctx
        return self.ledger.reserve(project=ctx.project_key, tool="animate", provider=self.api.name, est_usd=est,
                                   budget_usd=ctx.budget["per_project_usd"],
                                   min_balance_usd=ctx.budget["min_balance_usd"], balance=self.api.balance, **fields)

    def buy_and_wait(self, res: Reservation, png, prompt, model, resolution, secs, out) -> str:
        ctx = self.ctx
        work = ctx.cache_dir / "animate" / uuid.uuid4().hex[:8]
        work.mkdir(parents=True, exist_ok=True)
        try:
            frame, shape = first_frame(png, work)
        except Exception as exc:  # noqa: BLE001
            self.ledger.settle(res, "failed", 0.0, error=ctx.redact(exc)[:200])
            raise
        finally:
            for f in work.glob("*"):
                f.unlink(missing_ok=True)
            work.rmdir()
        body = {"model": model, "prompt": prompt, "duration": secs, "resolution": resolution, "aspect_ratio": shape,
                "generate_audio": False,
                "frame_images": [{"type": "image_url", "frame_type": "first_frame", "image_url": {"url": frame}}]}
        try:
            job = self.api.submit(body)
        except Exception as exc:  # noqa: BLE001
            said = ctx.redact(f"submit: {type(exc).__name__}: {exc}")[:200]
            if maybe_accepted(exc):
                self.ledger.mark(res, "submitted", job=f"unknown-{uuid.uuid4().hex[:12]}", error=said)
                return f"the submit broke off ({type(exc).__name__}) and may have been taken; counted at its estimate"
            self.ledger.settle(res, "failed", 0.0, error=said)
            return f"the provider refused the job ({ctx.redact(exc)[:160]})"
        if not isinstance(job, dict) or not job.get("id"):
            self.ledger.settle(res, "failed", 0.0, error="no job id in the answer")
            return "the provider gave no job id"
        res.fields.update(job=str(job["id"]), polling_url=job.get("polling_url"), shape=shape)
        self.ledger.mark(res, "submitted")      # in the ledger before the wait: a kill now resumes, never re-buys
        return self.wait(res, out)

    def wait(self, res: Reservation, out: Path) -> str:
        """'' once the clip is written, 'pending' when still running, else why not."""
        self.shape = str(res.fields.get("shape") or "")
        job, url = str(res.fields["job"]), res.fields.get("polling_url")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                st = self.api.poll(job, url)
            except ApiError as exc:
                st = {"status": "gone"} if exc.code == 404 else None
            except (ProviderError, OSError, ValueError, http.client.HTTPException):
                st = None
            status = str((st or {}).get("status") or "")
            if status in DONE:
                return self._settle(res, st, status, out)
            if time.monotonic() >= deadline:
                return "pending"
            self.sleep(POLL_S)

    def _settle(self, res: Reservation, st: dict, status: str, out: Path) -> str:
        paid = (st.get("usage") or {}).get("cost")
        if paid is None:
            paid = res.fields.get("paid_usd")         # a clip collected again: what the first answer said it cost
        try:
            cost = float(paid) if paid is not None else (res.est_usd if status in ("completed", "gone") else 0.0)
        except (TypeError, ValueError):
            cost = res.est_usd
        self.cost = cost
        if status != "completed":
            why = f"{status}: {st.get('error') or st.get('message') or ''}"[:200]
            self.ledger.settle(res, status, cost, error=self.ctx.redact(why)[:200])
            return why
        why = self._finish(res, st, out)
        # paid either way; a clip that did not arrive stays collectable from its job, never bought again
        self.collect = bool(why)
        self.ledger.settle(res, COLLECT if why else "success", cost, error=self.ctx.redact(why)[:200] if why else None)
        return why

    def _finish(self, res: Reservation, done: dict, out: Path) -> str:
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = out.with_name(f".{out.stem}.{uuid.uuid4().hex[:6]}.download.mp4")
        part = out.with_name(f".{out.stem}.{uuid.uuid4().hex[:6]}.part.mp4")
        try:
            raw.write_bytes(self.api.fetch(str(res.fields["job"]), done))
            rc, _, err, _ = run_tree([exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                                      "-map", "0:v:0", "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                                      "-movflags", "+faststart", str(part)], timeout=180)
            if rc != 0 or not part.is_file():
                return f"the downloaded clip could not be converted: {tail(err)}"
            part.replace(out)
            return ""
        except (ProviderError, OSError) as exc:
            return f"the clip could not be downloaded: {exc}"
        finally:
            raw.unlink(missing_ok=True)
            part.unlink(missing_ok=True)

    def text(self, why: str, asset_id: str, entry: dict, secs: int, resolution: str):
        if why == "pending":
            return (f"animate {asset_id!r}: still generating after {self.timeout / 60:.0f} min. The job is paid for "
                    "and kept: call animate again with the same arguments later to collect it (no new charge)."), True
        if why and self.collect:
            return (f"animate {asset_id!r}: the clip was made and paid for (${self.cost:.3f}), but {why}. It is kept "
                    "with the provider: call animate again with the same arguments to collect it (no new "
                    "charge)."), True
        if why:
            return (f"animate {asset_id!r}: no clip ({why}). Move the still in the editor instead (motion, zoom/pan "
                    "keyframes, parallax)."), True
        reg = register_asset(self.ctx, asset_id, entry)
        shape = f", {self.shape}" if self.shape else ""
        return (f"Animated {asset_id!r}: {entry['path']}, {secs} s{shape}, {resolution}, silent; cost "
                f"${self.cost:.3f}.{reg} Use it as a video clip (volume 0); for a longer shot slow it with rate or "
                "hold its last frame."), False
