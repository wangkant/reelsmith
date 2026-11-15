"""Tools an agent equips itself with: npm packages for its components (add) and Node scripts that make files (run),
the scripts held by Node's permission model."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import media
from .doctor import renderer_dir   # not .library: tests swap that module out
from .workspace import in_made

# npm's own name rules, lower case only; a version, a ^/~ range on one, or a dist-tag
NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$")
VERSION = re.compile(r"^[~^]?\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
# no dots in a tag: npm reads x@evil.tgz or x@v1.tar as a local tarball
TAG = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ARCHIVE = re.compile(r"\.(?:tgz|tar|tar\.gz|tar\.bz2|zip)$", re.I)
MAX_NAME = 214
MAX_SPECS = 20
ALWAYS_SHIPPED = ("react", "react-dom", "remotion")
NPM_FLAGS = ("--ignore-scripts", "--no-audit", "--no-fund", "--legacy-peer-deps", "--no-bin-links", "--no-progress",
             "--update-notifier=false", "--loglevel=error")
NPM_TIMEOUT_S = 10 * 60
LOCK_STALE_S = NPM_TIMEOUT_S + 60
OFFLINE = re.compile(r"ENOTFOUND|ETIMEDOUT|ECONNREFUSED|ECONNRESET|EAI_AGAIN|ENETUNREACH|network|proxy", re.I)
# provider keys and tokens stay out of npm's environment; npm's own settings pass
_SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASS|COOKIE|CREDENTIAL|AUTH|SESSION", re.I)

SCRIPT_EXTS = (".mjs", ".js", ".cjs")
SCRIPT_TIMEOUT_S = 120
MAX_SCRIPT_TIMEOUT_S = 600
MAX_ARGS = 50
MAX_ARG_CHARS = 2000
OUTPUT_CAP = 12000
MAX_COMMAND_CHARS = 32000                                  # CreateProcess takes 32767
MADE_CAP = 1024 * 1024 * 1024
WATCH_EVERY_S = 0.5
PRELOAD = Path(__file__).with_name("script_preload.mjs")
_SECRET_FILE = re.compile(
    r"^(\.env.*|\.npmrc|\.yarnrc.*|\.pypirc|\.netrc|\.pgpass|\.htpasswd|\.git|\.git-credentials|\.ssh|\.aws|\.azure"
    r"|\.kube|\.docker|\.gnupg|workspace\.json|rules\.json|ledger\.jsonl.*|.*credential.*|auth\.json"
    r"|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|.*\.(pem|key|p12|pfx|kdbx|jks|keystore)|cookies?.*)$", re.I)


class WorkbenchError(ValueError):
    """A call that cannot run as asked; the message says why and what to do."""


# ------------------------------------------------------------------ package specs
def parse_spec(text) -> tuple[str, str | None]:
    """(name, version or tag or None) of a registry package spec like d3-shape, d3-shape@3.2.0, @scope/x@next.
    URLs, git, file and alias specs, paths, flags and anything with spaces are refused."""
    if not isinstance(text, str) or not text or text != text.strip() or len(text) > MAX_NAME + 70:
        raise WorkbenchError(f"{text!r} is not a package name: give a registry name, e.g. d3-shape or d3-shape@3.2.0")
    at = text.rfind("@")
    name, version = (text[:at], text[at + 1:]) if at > 0 else (text, None)
    if not NAME.match(name) or len(name) > MAX_NAME or ARCHIVE.search(name):
        raise WorkbenchError(f"{text!r} is not a registry package name (lower-case letters, digits, - . _ ~, an "
                             "optional @scope/; no URLs, git, file paths or aliases)")
    if version is not None and (not (VERSION.match(version) or TAG.match(version)) or ARCHIVE.search(version)):
        raise WorkbenchError(f"{text!r}: after @ give a version (3.2.0, ^3.2) or a dist-tag (latest, next)")
    return name, version


def renderer_manifest() -> dict:
    try:
        data = json.loads((renderer_dir() / "package.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def shipped() -> dict[str, str]:
    """{name: version} of every package the renderer ships (react, react-dom and remotion always count)."""
    m = renderer_manifest()
    out = {**(m.get("devDependencies") or {}), **(m.get("dependencies") or {})}
    for name in ALWAYS_SHIPPED:
        out.setdefault(name, "(bundled)")
    return out


def importable_shipped() -> list[str]:
    """The renderer's packages a component may import."""
    deps = renderer_manifest().get("dependencies") or {}
    node_only = {"@remotion/bundler", "@remotion/cli", "@remotion/renderer"}
    names = [n for n in deps if n in ("react", "remotion") or (n.startswith("@remotion/") and n not in node_only)]
    return sorted(set(names) | {"react", "remotion"})


def plan(specs: list[str]) -> tuple[list[str], list[str]]:
    """(the specs npm installs, notes): shipped packages refused, other @remotion/* pinned to the renderer's
    Remotion. A spec that is not a plain registry name raises WorkbenchError before anything runs."""
    if len(specs) > MAX_SPECS:
        raise WorkbenchError(f"{len(specs)} packages at once; add at most {MAX_SPECS} a call")
    parsed = [parse_spec(s) for s in specs]
    ships, remotion = shipped(), (renderer_manifest().get("dependencies") or {}).get("remotion")
    install, notes = [], []
    for name, version in parsed:
        if name in ships:
            notes.append(f"{name} is already there (the renderer ships {ships[name]}): import it as it is")
        elif name.startswith("@remotion/") and remotion:
            if version and version != remotion:
                notes.append(f"{name} pinned to {remotion}, the renderer's Remotion (not {version})")
            install.append(f"{name}@{remotion}")
        else:
            install.append(f"{name}@{version}" if version else name)
    return list(dict.fromkeys(install)), notes


# ------------------------------------------------------------------ npm
def node_exe() -> str | None:
    return shutil.which("node")


def npm_command() -> list[str]:
    """[node, npm-cli.js]: npm run by node itself, so no .cmd shim and no shell ever reads the arguments."""
    node = node_exe()
    if not node:
        raise WorkbenchError("node is not on PATH: packages cannot be installed")
    here = Path(node).resolve().parent
    for cli in (here / "node_modules" / "npm" / "bin" / "npm-cli.js",
                here.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"):
        if cli.is_file():
            return [node, str(cli)]
    found = shutil.which("npm")
    if found and Path(found).resolve().suffix == ".js":
        return [node, str(Path(found).resolve())]
    raise WorkbenchError("npm was not found next to node: install Node.js with npm")


def npm_env(base=None) -> dict:
    env = {k: v for k, v in dict(os.environ if base is None else base).items()
           if not _SECRET_ENV.search(k) or k.lower().startswith(("npm_config_", "npm_"))}
    proxy = env.get("REELSMITH_PROXY")
    if proxy and not (env.get("HTTPS_PROXY") or env.get("https_proxy")):
        env.update(HTTPS_PROXY=proxy, HTTP_PROXY=proxy)
    env.pop("NODE_OPTIONS", None)
    env["npm_config_update_notifier"] = "false"
    return env


def install_command(root: Path, specs: list[str]) -> list[str]:
    """npm install into <root>/node_modules; no names restores what <root>/package.json lists."""
    cmd = [*npm_command(), "install", "--prefix", str(root), *NPM_FLAGS]
    if specs:
        cmd += ["--save-exact", "--", *specs]
    return cmd


class _Lock:
    """One npm run per workspace at a time, across processes (a lock file older than an install is stale)."""

    def __init__(self, path: Path, wait_s: float = NPM_TIMEOUT_S):
        self.path, self.wait_s = path, wait_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_S:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() - start > self.wait_s:
                    raise WorkbenchError("another package install in this workspace is still running: try later")
                time.sleep(0.5)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def declared(root: Path) -> dict[str, str]:
    """{name: spec} of <root>/package.json's dependencies."""
    deps = _read_json(Path(root) / "package.json").get("dependencies")
    return {str(k): str(v) for k, v in deps.items()} if isinstance(deps, dict) else {}


def installed_version(root: Path, name: str) -> str | None:
    v = _read_json(Path(root) / "node_modules" / name / "package.json").get("version")
    return str(v) if v else None


def _has_types(root: Path, name: str) -> bool:
    pkg = Path(root) / "node_modules" / name
    m = _read_json(pkg / "package.json")
    if m.get("types") or m.get("typings") or (pkg / "index.d.ts").is_file():
        return True
    exports = json.dumps(m.get("exports") or {})
    if '"types"' in exports:
        return True
    types_name = name[1:].replace("/", "__") if name.startswith("@") else name
    return (Path(root) / "node_modules" / "@types" / types_name).is_dir()


def foreign_sources(root: Path) -> list[str]:
    """Locked packages that did not come from a registry tarball (git, a file, a link)."""
    packages = _read_json(Path(root) / "package-lock.json").get("packages") or {}
    bad = []
    for key, info in packages.items():
        if not key or not isinstance(info, dict) or info.get("inBundle"):
            continue
        resolved = str(info.get("resolved") or "")
        if info.get("link") or (resolved and not (resolved.startswith("https://") and "/-/" in resolved)):
            bad.append(f"{key.removeprefix('node_modules/')} ({resolved or 'a link'})")
    return bad


def remove_installed(root: Path, keys: list[str]) -> list[str]:
    """Delete node_modules/<key> folders (a link is unlinked, never followed); the ones that could not be removed."""
    base = (Path(root) / "node_modules").resolve()
    left = []
    for key in keys:
        target = Path(root) / "node_modules" / key
        try:
            if ".." in Path(key).parts or not target.parent.resolve().is_relative_to(base):
                left.append(str(target))
            elif getattr(os.path, "isjunction", lambda _: False)(target):
                os.rmdir(target)
            elif target.is_symlink():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
        except OSError:
            left.append(str(target))
    return left


def _npm(root: Path, specs: list[str]) -> tuple[bool, str]:
    rc, out, err, timed = media.run_tree(install_command(root, specs), cwd=root, env=npm_env(), timeout=NPM_TIMEOUT_S)
    if timed:
        return False, f"npm ran over {NPM_TIMEOUT_S // 60} minutes and was stopped"
    said = [r for r in f"{out}\n{err}".splitlines()
            if not re.match(r"^npm (error|warn)\s+at |.*complete log of this run", r)]
    text = media.tail("\n".join(said), 12, 1500)
    if rc != 0:
        why = (" (the registry could not be reached: offline, or a proxy is needed in HTTPS_PROXY)"
               if OFFLINE.search(text) else "")
        return False, f"npm failed (exit {rc}){why}:\n{text}"
    return True, text


def add_packages(root: str | Path, specs: list[str]) -> tuple[bool, str]:
    """Install registry packages into <root>/node_modules and record them in <root>/package.json (created on first
    use); no specs restores what package.json lists. A failed install puts package.json back as it was."""
    root = Path(root).resolve()
    if in_made(root):
        raise WorkbenchError(f"{root} is inside a made/ folder, which scripts write: packages go into the real "
                             "workspace")
    install, notes = plan(list(specs))
    if specs and not install:
        return False, "\n".join(notes + ["nothing to install"])
    manifest, lock = root / "package.json", root / "package-lock.json"
    with _Lock(root / ".cache" / "packages.lock"):
        if not manifest.is_file():
            if not specs:
                return True, "no packages yet: add one with a name, e.g. add_package(project, [\"d3-shape\"])"
            manifest.write_text(json.dumps({"private": True, "description": "Packages for this workspace's "
                                            "components and scripts (reelsmith add).", "dependencies": {}},
                                           indent=2) + "\n", encoding="utf-8", newline="\n")
        saved = {p: (p.read_bytes() if p.is_file() else None) for p in (manifest, lock)}

        def put_back() -> None:
            for p, data in saved.items():
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(data)

        ok, said = _npm(root, install)
        if not ok:
            put_back()
            return False, "\n".join(notes + [said, "package.json is as it was; the workspace still works without "
                                             "these packages"])
        foreign = foreign_sources(root)
        if foreign:
            put_back()
            left = remove_installed(root, [f.split(" (")[0] for f in foreign])
            ok, said = _npm(root, [])
            gone = "they were removed again" if ok and not left else (
                "removing them failed: delete " + ", ".join(left or ["node_modules"]) + " by hand")
            return False, ("refused: only registry packages may be installed, and these came from elsewhere: "
                           + ", ".join(foreign[:8]) + f"; {gone}")
    names = [parse_spec(s)[0] for s in install] if specs else list(declared(root))
    rows = notes + [package_line(root, n) for n in names]
    if not specs:
        rows.insert(0, f"restored {len(declared(root))} package(s) from {manifest}")
    return True, "\n".join(rows)


def package_line(root: Path, name: str) -> str:
    version = installed_version(root, name)
    if not version:
        return f"- {name}: not installed (add_package with no names restores the workspace's packages)"
    m = _read_json(root / "node_modules" / name / "package.json")
    peers = [p for p in (m.get("peerDependencies") or {}) if p not in shipped() and not installed_version(root, p)]
    rows = [f"- {name} {version}" + ("" if _has_types(root, name) else
                                     f" (no types: add @types/{name.lstrip('@').replace('/', '__')} if it exists, "
                                     "or declare the module in a .d.ts in the library)")]
    if peers:
        rows.append(f"  its peers not installed: {', '.join(peers)} (add them if you use what needs them)")
    return "\n".join(rows)


def packages_text(root: Path | None) -> str:
    """What a component or script can import: the renderer's packages, then the workspace's."""
    rows = ["Packages a component can import: " + ", ".join(importable_shipped())
            + ", @reelsmith/kit (the renderer's)"]
    mine = declared(root) if root else {}
    if mine:
        rows.append("The workspace's (add_package adds more):")
        rows += [package_line(root, n) for n in sorted(mine)]
    else:
        rows.append("The workspace has no packages of its own: add_package(project, [\"name\"]) adds one from npm")
    return "\n".join(rows)


# ------------------------------------------------------------------ scripts
def sandbox_dirs(project: Path, ws) -> tuple[list[Path], list[Path]]:
    """(folders a script may read, folders it may write)."""
    reads, writes = [project], [project / "made"]
    if ws is not None:
        reads += [ws.library_dir, ws.root / "node_modules"]
        writes.append(ws.library_dir / "made")
    return reads + renderer_packages(), writes


def renderer_packages() -> list[Path]:
    """Each package folder of the renderer's node_modules, but not its dot folders: .cache holds webpack's builds
    of every workspace's library, .bin and .remotion are tools."""
    base = renderer_dir().resolve() / "node_modules"
    try:
        entries = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return []
    return [base / e.name for e in entries
            if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)
            and not getattr(os.path, "isjunction", lambda _: False)(e.path)]


def script_command(node: str, script: Path, args: list[str], reads: list[Path], writes: list[Path]) -> list[str]:
    """node under the permission model: reads and writes only where given; no child processes, workers, addons,
    WASI or inspector (none of their --allow-* flags is passed), and no node:sqlite, which the model does not
    cover."""
    cmd = [node, "--permission", "--no-addons", "--no-experimental-sqlite"]
    cmd += [f"--allow-fs-read={p}" for p in [*reads, PRELOAD]]
    cmd += [f"--allow-fs-write={p}" for p in writes]
    cmd += ["--import", PRELOAD.as_uri(), str(script), *args]
    if sum(len(c) + 3 for c in cmd) > MAX_COMMAND_CHARS:
        raise WorkbenchError("the script's command line is too long for Windows: pass fewer or shorter arguments")
    return cmd


def script_env(project: Path, ws) -> dict:
    """Nothing inherited: no keys, no proxy, no NODE_OPTIONS; only what Windows needs to start a process."""
    env = {"REELSMITH_MADE": str(project / "made"),
           "REELSMITH_RENDERER_MODULES": str(renderer_dir().resolve() / "node_modules")}
    if ws is not None:
        env["REELSMITH_LIBRARY_MADE"] = str(ws.library_dir / "made")
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot") or r"C:\Windows"
    return env


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def resolve_script(project: Path, ws, script: str) -> Path:
    """The script's real path: a .mjs/.js/.cjs file in the project folder or the workspace library."""
    text = str(script or "").strip()
    if not text or "\0" in text:
        raise WorkbenchError("script must be the path of a .mjs or .js file, e.g. library/tools/texture.mjs")
    p = Path(text)
    homes = [project] + ([ws.library_dir.resolve()] if ws is not None else [])
    candidates = [p] if p.is_absolute() else [project / p] + ([ws.root / p] if ws is not None else [])
    # where it points is checked before whether it exists, so the answer says nothing about files elsewhere
    for cand in candidates:
        real = cand.resolve()
        if (_inside(real, homes) and "node_modules" not in (s.lower() for s in real.parts)
                and real.suffix.lower() in SCRIPT_EXTS and real.is_file()):
            return real
    raise WorkbenchError(f"no script at {text} in the project folder or the workspace library: a script is a .mjs, "
                         ".js or .cjs file there (library/tools/ for ones worth keeping), not in node_modules")


def sandbox_problems(project: Path, ws, reads: list[Path], limit: int = 200000) -> list[str]:
    """Why the readable folders cannot be handed to a script: the workspace's own files inside them, secret-looking
    files, or links that lead outside (the permission model follows links)."""
    if ws is not None and _inside(ws.root.resolve(), [project]):
        return [f"the project folder {project} holds the workspace itself: run scripts from a project inside it"]
    allowed = [r.resolve() for r in reads if r.exists()]
    out, seen = [], 0
    for top in [project] + ([ws.library_dir] if ws is not None else []):
        for dirpath, dirs, files in os.walk(top):
            base = Path(dirpath)
            # what a script wrote into made/ came from a script: no secret, and it must not lock out later runs
            scripted = in_made(base)
            for name in list(dirs):
                full = base / name
                if name.lower() == "node_modules":
                    dirs.remove(name)
                    continue
                if os.path.islink(full) or getattr(os.path, "isjunction", lambda _: False)(full):
                    dirs.remove(name)
                    if not _inside(full.resolve(), allowed):
                        out.append(f"{full} links outside the folders a script may read")
            for name in files + dirs:
                full = base / name
                if _SECRET_FILE.match(name) and not scripted:
                    out.append(f"{full} looks like a secret or the owner's settings")
                elif os.path.islink(full) and not _inside(full.resolve(), allowed):
                    out.append(f"{full} links outside the folders a script may read")
            seen += len(files) + len(dirs)
            if seen > limit or len(out) >= 5:
                return out
    return out


def run_capped(cmd: list[str], cwd: Path, env: dict, timeout: float, cap: int = OUTPUT_CAP, watch=None):
    """(returncode, stdout, stderr, timed_out, bytes dropped): at most `cap` bytes of each stream are kept (the rest
    is read and thrown away); a timeout, or `watch()` returning true (polled while it runs), kills the whole
    process tree."""
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=media.NO_WINDOW, start_new_session=os.name != "nt")
    media._adopt(proc)                                   # noqa: SLF001 - killed with this process, like run_tree's
    kept = {"out": bytearray(), "err": bytearray()}
    dropped = [0]

    def pump(pipe, buf: bytearray) -> None:
        while chunk := pipe.read1(65536):
            room = max(0, cap - len(buf))
            buf += chunk[:room]
            dropped[0] += len(chunk) - min(room, len(chunk))

    pumps = [threading.Thread(target=pump, args=(proc.stdout, kept["out"]), daemon=True),
             threading.Thread(target=pump, args=(proc.stderr, kept["err"]), daemon=True)]
    for t in pumps:
        t.start()
    timed, end = False, time.monotonic() + timeout
    try:
        while True:
            try:
                proc.wait(timeout=max(0.01, min(WATCH_EVERY_S, end - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                over = time.monotonic() >= end
                if over or (watch is not None and watch()):
                    timed = over
                    media.kill_tree(proc)
                    proc.wait(timeout=30)
                    break
    except BaseException:
        media.kill_tree(proc)
        raise
    finally:
        for t in pumps:
            t.join(10)
        media._release(proc)                             # noqa: SLF001
    return (proc.returncode, kept["out"].decode("utf-8", "replace"), kept["err"].decode("utf-8", "replace"), timed,
            dropped[0])


def _files(dirs: list[Path]) -> dict[Path, tuple[int, int]]:
    out = {}
    for d in dirs:
        if d.is_dir():
            for f in d.rglob("*"):
                if f.is_file():
                    st = f.stat()
                    out[f] = (st.st_size, st.st_mtime_ns)
    return out


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def run_script(project: Path, ws, script: str, args: list[str] | None = None,
               timeout_s: float = SCRIPT_TIMEOUT_S, made_cap: int = MADE_CAP) -> tuple[bool, str]:
    """Run a Node script of the agent's in the sandbox; (ok, what happened: exit, files made, output)."""
    args = [str(a) for a in (args or [])]
    if len(args) > MAX_ARGS or any(len(a) > MAX_ARG_CHARS or "\0" in a for a in args):
        raise WorkbenchError(f"at most {MAX_ARGS} arguments of {MAX_ARG_CHARS} characters each")
    if isinstance(timeout_s, bool) or not 1 <= float(timeout_s) <= MAX_SCRIPT_TIMEOUT_S:
        raise WorkbenchError(f"timeout_s must be 1 to {MAX_SCRIPT_TIMEOUT_S} seconds")
    project = Path(project).resolve()
    path = resolve_script(project, ws, script)
    node = node_exe()
    if not node:
        raise WorkbenchError("node is not on PATH: scripts cannot run")
    reads, writes = sandbox_dirs(project, ws)
    problems = sandbox_problems(project, ws, reads)
    if problems:
        return False, ("the script was not run: a script may read the project folder and the workspace library, "
                       "and these must not be there:\n" + "\n".join(f"- {p}" for p in problems))
    for d in writes:
        d.mkdir(parents=True, exist_ok=True)
    cmd = script_command(node, path, args, reads, writes)
    before, t0 = _files(writes), time.monotonic()
    start_size = sum(s for s, _ in before.values())
    full = []

    def too_big() -> bool:
        grown = _tree_size(writes) - start_size
        if grown > made_cap:
            full.append(grown)
        return bool(full)

    rc, out, err, timed, dropped = run_capped(cmd, project, script_env(project, ws), float(timeout_s), watch=too_big)
    seconds = time.monotonic() - t0
    after = _files(writes)
    made = [f for f, sig in after.items() if before.get(f) != sig]
    base = ws.root if ws is not None else project
    if full:
        rows = [f"stopped: it wrote more than {_size(made_cap)} into made/ (the limit for one run); its files are "
                "left there, delete what you do not need"]
    elif timed:
        rows = [f"stopped after {timeout_s:g} s (the time limit; pass timeout_s for more, at most "
                f"{MAX_SCRIPT_TIMEOUT_S})"]
    else:
        rows = [f"exit {rc} in {seconds:.1f} s"]
    for f in sorted(made)[:30]:
        rel = f.relative_to(project) if _inside(f, [project]) else f.relative_to(base)
        rows.append(f"made {rel.as_posix()} ({_size(after[f][0])})")
    if len(made) > 30:
        rows.append(f"... and {len(made) - 30} more files")
    if out.strip():
        rows += ["stdout:", out.rstrip()]
    if err.strip():
        rows += ["stderr:", err.rstrip()]
    if dropped:
        rows.append(f"({dropped} more bytes of output were dropped: print less)")
    if "ERR_ACCESS_DENIED" in err or "REELSMITH_SANDBOX" in err:
        rows.append("(the sandbox refused that: a script reads only the project, the workspace library and "
                    "installed packages, writes only made/ and library/made/, and has no network, processes, "
                    "workers or node:sqlite)")
    return (rc == 0 and not timed and not full), "\n".join(rows)


def _tree_size(dirs: list[Path]) -> int:
    total = 0
    for d in dirs:
        for dirpath, _, files in os.walk(d):
            for name in files:
                try:
                    total += os.stat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
    return total
