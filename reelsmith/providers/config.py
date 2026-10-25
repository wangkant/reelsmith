"""Where a provider call writes, what it may spend and which keys it uses; shared plumbing for the asset tools.

Every public provider function takes the project path first and returns (text, is_error). This module turns that
path into a Context (workspace, merged provider config, budget, keys, ledger, cache), registers produced assets in
project.json, and keeps keys out of everything the tools return or log.
"""
from __future__ import annotations

import copy
import functools
import importlib
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PROJECT_FILE = "project.json"
VOICE_JSON = "voice/voice.json"
ASSET_KINDS = ("image", "video", "audio", "evidence")
# Same rule as tools._id_arg; ids that differ only by case are refused (they would share a file on Windows).
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SHARING_TRIES = 25          # ~6 s of backoff: an editor or another process briefly holding project.json

DEFAULT_PROVIDERS: dict = {
    # model and voice None: the provider's defaults, the voice by the locale (tts.default_model, tts.default_voice)
    "tts": {"provider": "openrouter", "model": None, "voice": None,
            "instructions": "", "speed_scale": 1.0, "usd_per_1k_chars": 0.02, "line_lufs": -12.0},
    "image": {"provider": "codex", "max_draws": 30, "timeout_s": 360, "effort": "low"},
    "video": {"provider": "openrouter", "model": "bytedance/seedance-1-5-pro", "resolution": "720p",
              "usd_per_s": None, "timeout_s": 360},
    "capture": {"proxy": None},
    "import": {"max_mb": 200},
    "transcribe": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "whisper-1",
                   "key_env": "OPENAI_API_KEY", "usd_per_min": 0.006, "max_mb": 24, "timeout_s": 600,
                   "language": None, "local_model": "small", "device": "auto", "compute_type": "default"},
}
DEFAULT_BUDGET: dict = {"per_project_usd": 1.0, "min_balance_usd": 5.0}
# Process-level overrides of workspace.json (the runner's --budget-usd caps the Claude session, not asset spend).
BUDGET_ENV = "REELSMITH_BUDGET_USD"
MIN_BALANCE_ENV = "REELSMITH_MIN_BALANCE_USD"

_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.I)
_SECRET_PATTERNS = (re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}"), re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
                    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"))
REDACTED = "[redacted]"


class ProviderError(Exception):
    """A failure whose message is already fit for the agent (actionable, no secrets)."""


# ------------------------------------------------------------------ secrets
def env_secrets() -> list[str]:
    return [v for k, v in os.environ.items() if v and len(v) >= 8 and _SECRET_NAME.search(k)]


def redact(text: Any, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """The text with every known key value and anything shaped like a key replaced."""
    out = str(text if text is not None else "")
    for value in sorted({s for s in (*secrets, *env_secrets()) if s and len(s) >= 8}, key=len, reverse=True):
        out = out.replace(value, REDACTED)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, out)
    return out


# ------------------------------------------------------------------ workspace
def _workspace_module():
    try:
        mod = importlib.import_module("reelsmith.workspace")
    except Exception:  # noqa: BLE001 — a half-written neighbour must not take the tools down
        return None
    return mod if hasattr(mod, "find_workspace") else None


@dataclass
class _LocalWorkspace:
    """Stand-in with Workspace's attribute names, used only when reelsmith.workspace cannot be imported."""
    root: Path
    config: dict
    keys: dict

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"


def _parse_env(path: Path) -> dict:
    out = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.removeprefix("export ").partition("=")
        v = v.strip().strip("'\"")
        if k.strip() and v:
            out[k.strip()] = v
    return out


def _local_find(project_dir: Path):
    for d in (project_dir, *project_dir.parents):
        cfg = d / "workspace.json"
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise ProviderError(f"{cfg} is not valid JSON ({exc}); fix it first") from None
            # .env only: Context.key falls back to the environment, and secrets() must not list PATH and friends
            return _LocalWorkspace(d, data if isinstance(data, dict) else {}, _parse_env(d / ".env"))
    return None


def project_profile(ctx):
    """The project's profile (workspace.profile_for); None when it cannot be read."""
    mod = _workspace_module()
    try:
        return mod.profile_for(ctx.project) if mod is not None and hasattr(mod, "profile_for") else None
    except Exception:  # noqa: BLE001 - check and render report a bad profile; a tool falls back to its default
        return None


def project_locale(ctx) -> str:
    """The project's locale (workspace.locale_for), "en" without one; ProviderError for a malformed tag."""
    mod = _workspace_module()
    if mod is None or not hasattr(mod, "locale_for"):
        return "en"
    try:
        return mod.locale_for(ctx.project)
    except ValueError as exc:
        raise ProviderError(f"{exc} (project.json or workspace.json locale)") from None


def find_workspace(project_dir: Path):
    mod = _workspace_module()
    if mod is None:
        return _local_find(project_dir)
    try:
        return mod.find_workspace(project_dir)
    except ValueError as exc:               # WorkspaceError: a file the owner must fix
        raise ProviderError(str(exc)) from None


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else {}


def _merged(defaults: dict, found) -> dict:
    out = copy.deepcopy(defaults)
    for name, part in _as_dict(found).items():
        if isinstance(part, dict) and isinstance(out.get(name), dict):
            out[name].update(part)
        elif isinstance(part, dict):
            out[name] = dict(part)
    return out


def _env_number(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ProviderError(f"environment {name}={raw!r} is not a number") from None
    if value < 0:
        raise ProviderError(f"environment {name} must be >= 0")
    return value


def _budget(found) -> dict:
    budget = dict(DEFAULT_BUDGET)
    for k, v in _as_dict(found).items():
        if k in budget and v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ProviderError(f"workspace.json budget.{k} must be a number >= 0 (got {v!r})")
            budget[k] = float(v)
    for key, env in (("per_project_usd", BUDGET_ENV), ("min_balance_usd", MIN_BALANCE_ENV)):
        value = _env_number(env)
        if value is not None:
            budget[key] = value
    return budget


# ------------------------------------------------------------------ context
@dataclass
class Context:
    project: Path
    workspace: Any
    providers: dict
    budget: dict
    ledger_path: Path
    cache_dir: Path
    project_key: str
    _keys: Any = field(default=None, repr=False)

    @property
    def project_file(self) -> Path:
        return self.project / PROJECT_FILE

    @property
    def assets_dir(self) -> Path:
        return self.project / "assets"

    @property
    def voice_dir(self) -> Path:
        return self.project / "voice"

    def key(self, name: str) -> str:
        """A provider key from Workspace.keys or the environment; '' when absent."""
        value = None
        if self._keys is not None:
            try:
                value = self._keys.get(name)
            except Exception:  # noqa: BLE001
                value = None
        return str(value or os.environ.get(name) or "").strip()

    def secrets(self) -> list[str]:
        return _dict_values(self._keys)

    def redact(self, text: Any) -> str:
        return redact(text, self.secrets())

    def ledger(self):
        from .ledger import Ledger
        return Ledger(self.ledger_path)


def project_dir(project) -> Path:
    if project is None or str(project).strip() == "":
        raise ProviderError("project is required: the path of the project folder")
    p = Path(str(project)).expanduser().resolve()
    if p.name == PROJECT_FILE and p.is_file():
        p = p.parent
    if not p.is_dir():
        raise ProviderError(f"project folder {p} does not exist; create it (with project.json) first")
    return p


def context(project) -> Context:
    p = project_dir(project)
    ws = find_workspace(p)
    if ws is not None:
        cfg = _as_dict(getattr(ws, "config", {}))
        root = Path(ws.root)
        ledger_path = Path(getattr(ws, "ledger_path", root / "ledger.jsonl"))
        cache = Path(getattr(ws, "cache_dir", root / ".cache"))
        try:
            key = p.relative_to(root).as_posix() or p.name
        except ValueError:
            key = p.name
        keys = getattr(ws, "keys", None)
    else:
        # outside a workspace the project keeps its own ledger and cache; keys from the environment
        cfg, ledger_path, cache, key, keys = {}, p / "ledger.jsonl", p / ".cache", p.name, None
    return Context(project=p, workspace=ws, providers=_merged(DEFAULT_PROVIDERS, cfg.get("providers")),
                   budget=_budget(cfg.get("budget")), ledger_path=ledger_path, cache_dir=cache,
                   project_key=key, _keys=keys)


def safe_tool(fn: Callable) -> Callable:
    """No provider raises to its caller: a failure comes back as (redacted text, True)."""
    @functools.wraps(fn)
    def wrapper(project, *args, **kwargs):
        try:
            text, is_error = fn(project, *args, **kwargs)
        except ProviderError as exc:
            text, is_error = str(exc), True
        except Exception as exc:  # noqa: BLE001
            text, is_error = f"{fn.__name__} failed: {type(exc).__name__}: {exc}", True
        try:
            ws = find_workspace(project_dir(project))
            secrets = _dict_values(getattr(ws, "keys", None))
        except Exception:  # noqa: BLE001
            secrets = []
        return redact(text, secrets), bool(is_error)
    return wrapper


def _dict_values(keys) -> list[str]:
    # dict.values: Workspace.keys falls back to os.environ on lookup, but only its .env entries are stored
    return [str(v) for v in dict.values(keys) if v] if isinstance(keys, dict) else []


# ------------------------------------------------------------------ validation
def check_id(asset_id, what: str = "id") -> str:
    s = asset_id if isinstance(asset_id, str) else ""
    if not ASSET_ID_RE.match(s):
        raise ProviderError(f"{what} {asset_id!r} must be 1-64 letters, digits, _ or -, starting with a letter or "
                            "digit (it becomes the file name under assets/)")
    return s


def number(value, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise ProviderError(f"{what} must be a number (got {value!r})")
    if not low <= value <= high:
        raise ProviderError(f"{what} must be between {low} and {high} (got {value})")
    return float(value)


# ------------------------------------------------------------------ project.json
_PROJECT_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _project_lock(path: Path) -> threading.RLock:
    """Serializes this process's edits of one project.json (parallel draws register at the same time)."""
    with _LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(str(path).lower(), threading.RLock())


def patient(op: Callable, tries: int = SHARING_TRIES):
    """op(), retried while Windows reports a sharing violation (another reader or writer holds the file)."""
    for n in range(tries):
        try:
            return op()
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(0.02 * (n + 1))


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        patient(lambda: os.replace(tmp, path))
    finally:
        tmp.unlink(missing_ok=True)


def read_project(ctx: Context) -> dict:
    """project.json as a dict ({} when missing); invalid JSON is an error the agent must fix."""
    try:
        with _project_lock(ctx.project_file):
            text = patient(lambda: ctx.project_file.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ProviderError(f"cannot read {ctx.project_file}: {exc}") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProviderError(f"{ctx.project_file} is not valid JSON ({exc}); fix it, then call again") from None
    if not isinstance(data, dict):
        raise ProviderError(f"{ctx.project_file} must hold a JSON object")
    return data


def _minimal_project() -> dict:
    return {"version": 2, "meta": {"title": "", "desc": "", "topic": "", "shape": "", "sources": []},
            "assets": {}, "tracks": []}


def ensure_project(ctx: Context) -> None:
    if not ctx.project_file.exists():
        with _project_lock(ctx.project_file):
            if not ctx.project_file.exists():
                write_json(ctx.project_file, _minimal_project())


def existing_asset(ctx: Context, asset_id: str) -> dict | None:
    assets = read_project(ctx).get("assets")
    entry = assets.get(asset_id) if isinstance(assets, dict) else None
    return entry if isinstance(entry, dict) else None


def check_replaceable(ctx: Context, asset_id: str, kind: str) -> dict | None:
    """The existing entry for asset_id, refused before any work when it holds another kind of asset or when another
    id differs from it only by case."""
    assets = read_project(ctx).get("assets")
    assets = assets if isinstance(assets, dict) else {}
    twin = next((k for k in assets if k != asset_id and str(k).lower() == asset_id.lower()), None)
    if twin is not None:
        raise ProviderError(f"asset id {asset_id!r} differs from the existing {twin!r} only by case; the two would "
                            f"share a file. Use {twin!r} to replace it, or pick another id")
    old = assets.get(asset_id)
    old = old if isinstance(old, dict) else None
    if old is not None and old.get("kind") != kind:
        was = str(old.get("kind"))
        raise ProviderError(f"asset id {asset_id!r} already names {'an' if was[:1] in 'aeiou' else 'a'} {was} "
                            f"({old.get('path')}); pick another id, or remove_asset it first")
    return old


def _ops_apply():
    # importlib, not `from reelsmith import ops`: sys.modules is the one seam tests and callers can swap
    try:
        ops = importlib.import_module("reelsmith.ops")
    except Exception:  # noqa: BLE001 — missing or half-written: fall back to writing project.json
        return None
    apply = getattr(ops, "apply", None)
    return apply if callable(apply) else None


def _issues_text(issues) -> str:
    if isinstance(issues, (str, bytes)):
        issues = [issues]
    rows = [str(i) for i in (issues or [])][:4]
    return "; ".join(rows)


class EditRefused(ProviderError):
    """reelsmith.ops refused (or failed on) a provider's change; project.json was left as it was."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def _apply_or_write(ctx: Context, ops: list[dict], direct: Callable[[dict], None], replacing: bool = False) -> str:
    """Run the ops through reelsmith.ops (validated, undoable); a note for the agent ('' when ops took it). When ops
    refuses, EditRefused: an unvalidated write could leave a project that no longer loads. Only when reelsmith.ops
    cannot be imported is the same change made in project.json directly."""
    with _project_lock(ctx.project_file):
        ensure_project(ctx)
        apply = _ops_apply()
        if apply is not None:
            try:
                result = apply(ctx.project, ops)
                ok, issues = bool(result[0]), result[1]
            except Exception as exc:  # noqa: BLE001
                ok, issues = False, [f"the edit module failed: {type(exc).__name__}: {exc}"]
            if ok:
                return ""
            raise EditRefused(_issues_text(issues) or "refused")
        data = read_project(ctx) or _minimal_project()
        direct(data)
        write_json(ctx.project_file, data)
    if replacing:
        return " (replaced the earlier entry of that id in project.json)"
    return " (written to project.json directly: the edit module is unavailable. Run check to see any issues.)"


def register_asset(ctx: Context, asset_id: str, entry: dict) -> str:
    """Add or replace assets[asset_id]; '' or a note on how it was registered."""
    entry = {k: v for k, v in entry.items() if v is not None}
    if entry.get("kind") == "evidence":
        entry.setdefault("site", "")
        entry.setdefault("url", "")
    if not entry.get("note"):
        entry.pop("note", None)
    old = existing_asset(ctx, asset_id)
    if old == entry:
        return ""

    def direct(data: dict) -> None:
        assets = data.get("assets")
        if not isinstance(assets, dict):
            assets = data["assets"] = {}
        assets[asset_id] = entry

    op = {"op": "add_asset", "id": asset_id, "asset": entry}
    try:
        return _apply_or_write(ctx, [op], direct, replacing=old is not None)
    except EditRefused as exc:
        raise ProviderError(f"{entry.get('path')} is written, but project.json did not take asset {asset_id!r}: "
                            f"{exc.why}. project.json is unchanged. Fix that, then register the file with edit "
                            f"{json.dumps([op], ensure_ascii=False)}") from None


def set_voice_if_unset(ctx: Context, rel: str = VOICE_JSON) -> str:
    """Point project `voice` at rel when it is unset; a note on what happened."""
    current = read_project(ctx).get("voice")
    if current == rel:
        return ""
    if current:
        return f" project.json voice still points at {current!r}; set it to {rel!r} to use this narration."

    def direct(data: dict) -> None:
        data["voice"] = rel

    op = {"op": "set", "path": "voice", "value": rel}
    try:
        note = _apply_or_write(ctx, [op], direct)
    except EditRefused as exc:
        return (f" project.json voice was NOT set ({exc.why}); fix that, then set it with edit "
                f"{json.dumps([op], ensure_ascii=False)}.")
    return f" project.json voice set to {rel!r}." + note


def rel(ctx: Context, path: Path) -> str:
    return Path(path).resolve().relative_to(ctx.project).as_posix()


# ------------------------------------------------------------------ processes and media
def exe(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ProviderError(f"{name} is not on PATH; install it to use this tool")
    return found


def _kill_tree(proc) -> None:
    # codex and browsers leave children behind; killing only the parent keeps them (and the pipes) alive
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)         # its own session: the whole group
        except OSError:
            proc.kill()


def run_tree(cmd, cwd=None, env=None, timeout=600, stdin=None, no_window=False):
    """(returncode, stdout, stderr, timed_out) of a fixed argument list; a timeout or an interrupt kills the whole
    process tree."""
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env,
                            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW if no_window else 0, start_new_session=os.name != "nt")
    timed_out = False
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    except BaseException:
        _kill_tree(proc)        # a child in its own session or without a console never sees the terminal's Ctrl+C
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), timed_out


def tail(text: str, lines: int = 3, chars: int = 300) -> str:
    rows = [r.rstrip() for r in (text or "").replace("\r", "\n").splitlines() if r.strip()]
    return "\n".join(rows[-lines:])[-chars:]


def probe(path: Path) -> dict:
    rc, out, err, _ = run_tree([exe("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams",
                                "-show_format", str(path)], timeout=120)
    if rc != 0:
        raise ProviderError(f"ffprobe cannot read {Path(path).name}: {tail(err, 2, 200)}")
    try:
        return json.loads(out or "{}")
    except ValueError:
        return {}


def media_duration(path: Path) -> float | None:
    try:
        return float(probe(path).get("format", {}).get("duration") or 0) or None
    except (ProviderError, ValueError, TypeError):
        return None


def header_size(path: Path) -> tuple[int, int] | None:
    """(w, h) from a PNG, GIF, JPEG or WebP header without decoding; None for anything else."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _webp_size(head)
            if head[:2] == b"\xff\xd8":
                return _jpeg_size(fh)
    except (OSError, struct.error):
        return None
    return None


def _webp_size(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        b = int.from_bytes(head[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    return None


def _jpeg_size(fh) -> tuple[int, int] | None:
    fh.seek(2)
    while True:
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
            continue
        seg = fh.read(2)
        if len(seg) < 2:
            return None
        length = struct.unpack(">H", seg)[0]
        if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            data = fh.read(5)
            h, w = struct.unpack(">HH", data[1:5])
            return w, h
        fh.seek(length - 2, 1)


def image_size(path: Path) -> tuple[int, int]:
    """(w, h) of an image; (0, 0) when unreadable."""
    size = header_size(path)
    if size:
        return int(size[0]), int(size[1])
    try:
        video = next((s for s in probe(path).get("streams") or [] if s.get("codec_type") == "video"), {})
    except ProviderError:
        return 0, 0
    return int(video.get("width") or 0), int(video.get("height") or 0)
