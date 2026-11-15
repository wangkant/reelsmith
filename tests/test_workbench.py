"""The workbench: packages a workspace adds (validation, npm's command line, refusals, restore, a failed install)
and scripts run under Node's permission model (arguments, environment, refusals, timeouts, the sandbox itself)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reelsmith import cli
from reelsmith import tools as T
from reelsmith import workbench as W
from reelsmith.workspace import Workspace

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")

FAKE_NPM = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_NPM_LOG"])
log.write_text(log.read_text() + json.dumps(args) + "\n" if log.exists() else json.dumps(args) + "\n")
if os.environ.get("FAKE_NPM_FAIL"):
    print("npm error code ECONNREFUSED", file=sys.stderr)
    sys.exit(1)
root = Path(args[args.index("--prefix") + 1])
specs = args[args.index("--") + 1:] if "--" in args else []
manifest = json.loads((root / "package.json").read_text())
lock = {"packages": {"": {}}}
for spec in specs:
    at = spec.rfind("@")
    name, version = (spec[:at], spec[at + 1:]) if at > 0 else (spec, "1.0.0")
    manifest.setdefault("dependencies", {})[name] = version
for name, version in manifest.get("dependencies", {}).items():
    pkg = root / "node_modules" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(json.dumps({"name": name, "version": version, "types": "index.d.ts"}))
    url = os.environ.get("FAKE_NPM_RESOLVED") or f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
    lock["packages"]["node_modules/" + name] = {"version": version, "resolved": url}
(root / "package.json").write_text(json.dumps(manifest))
(root / "package-lock.json").write_text(json.dumps(lock))
'''


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "ws"
    (root / "library" / "components").mkdir(parents=True)
    (root / "workspace.json").write_text("{}", encoding="utf-8")
    project = root / "projects" / "p"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"version": 2, "assets": {}, "tracks": []}), encoding="utf-8")
    return Workspace.load(root), project


@pytest.fixture
def fake_npm(tmp_path, monkeypatch):
    script = tmp_path / "fake_npm.py"
    script.write_text(FAKE_NPM, encoding="utf-8")
    log = tmp_path / "npm.log"
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))
    monkeypatch.setattr(W, "npm_command", lambda: [sys.executable, str(script)])

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return calls


# ------------------------------------------------------------------ specs
@pytest.mark.parametrize("spec,want", [
    ("d3-shape", ("d3-shape", None)), ("d3-shape@3.2.0", ("d3-shape", "3.2.0")), ("x@^1.2", ("x", "^1.2")),
    ("@scope/pkg", ("@scope/pkg", None)), ("@scope/pkg@next", ("@scope/pkg", "next")),
    ("simplex-noise@4.0.3", ("simplex-noise", "4.0.3")), ("a.b_c~d@1.0.0-beta.2", ("a.b_c~d", "1.0.0-beta.2")),
])
def test_registry_specs_are_read(spec, want):
    assert W.parse_spec(spec) == want


@pytest.mark.parametrize("spec", [
    "", " d3", "d3 ", "a b", "https://x.org/a.tgz", "git+ssh://git@github.com/a/b.git", "github:a/b", "user/repo",
    "../lib", "./x", "/abs/x", "C:\\x", "file:x", "npm:react@18", "alias@npm:react", "--global", "-g", "Foo",
    "foo.tgz", "foo.tar.gz", "x@", "x@>=1 <2", "x@1.0.0 || 2", "x@latest;rm", "@scope", "@/x", "x\0y", "x" * 215,
    "x@1.0.0@2", ".hidden", "_under",
])
def test_anything_but_a_registry_name_is_refused(spec):
    with pytest.raises(W.WorkbenchError):
        W.parse_spec(spec)


def test_shipped_packages_are_refused_and_remotion_ones_pinned():
    remotion = W.renderer_manifest()["dependencies"]["remotion"]
    install, notes = W.plan(["react", "react-dom@18", "remotion", "typescript", "@types/react", "@remotion/paths",
                             "@remotion/shapes@1.0.0", "@remotion/noise", "d3-shape", "d3-shape"])
    assert install == [f"@remotion/shapes@{remotion}", f"@remotion/noise@{remotion}", "d3-shape"]
    for name in ("react", "react-dom", "remotion", "typescript", "@types/react", "@remotion/paths"):
        assert any(n.startswith(f"{name} is already there") for n in notes), name
    assert f"@remotion/shapes pinned to {remotion}, the renderer's Remotion (not 1.0.0)" in notes
    with pytest.raises(W.WorkbenchError):
        W.plan([f"p{i}" for i in range(W.MAX_SPECS + 1)])


def test_npm_runs_through_node_with_a_fixed_argument_list(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "npm_command", lambda: ["node", "npm-cli.js"])
    flags = ["--ignore-scripts", "--no-audit", "--no-fund", "--legacy-peer-deps", "--no-bin-links", "--no-progress",
             "--update-notifier=false", "--loglevel=error"]
    assert W.install_command(tmp_path, ["simplex-noise@4.0.3", "@remotion/shapes@4.0.1"]) == [
        "node", "npm-cli.js", "install", "--prefix", str(tmp_path), *flags, "--save-exact", "--",
        "simplex-noise@4.0.3", "@remotion/shapes@4.0.1"]
    assert W.install_command(tmp_path, []) == ["node", "npm-cli.js", "install", "--prefix", str(tmp_path), *flags]


@pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")
def test_the_real_npm_is_found_next_to_node():
    cmd = W.npm_command()
    assert cmd[0] == shutil.which("node") and cmd[1].endswith("npm-cli.js") and Path(cmd[1]).is_file()


def test_npm_gets_no_keys_and_no_node_options():
    env = W.npm_env({"OPENROUTER_API_KEY": "k", "GITHUB_TOKEN": "t", "DOUYIN_COOKIE": "c", "PATH": "p",
                     "NODE_OPTIONS": "--require x", "npm_config_cache": "D:/c", "NPM_CONFIG_REGISTRY": "r",
                     "REELSMITH_PROXY": "http://127.0.0.1:7890"})
    assert not {"OPENROUTER_API_KEY", "GITHUB_TOKEN", "DOUYIN_COOKIE", "NODE_OPTIONS"} & set(env)
    assert env["PATH"] == "p" and env["npm_config_cache"] == "D:/c" and env["NPM_CONFIG_REGISTRY"] == "r"
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert W.npm_env({"HTTPS_PROXY": "http://a:1", "REELSMITH_PROXY": "http://b:2"})["HTTPS_PROXY"] == "http://a:1"


# ------------------------------------------------------------------ add_package
def test_add_creates_a_private_package_json_and_installs(ws, fake_npm):
    w, project = ws
    r = T.add_package(str(project), ["simplex-noise@4.0.3", "react"])
    assert r.ok, r
    manifest = json.loads((w.root / "package.json").read_text())
    assert manifest["private"] is True and manifest["dependencies"] == {"simplex-noise": "4.0.3"}
    assert "react is already there" in r and "- simplex-noise 4.0.3" in r
    (call,) = fake_npm()
    assert call[:3] == ["install", "--prefix", str(w.root)] and "--ignore-scripts" in call
    assert call[call.index("--"):] == ["--", "simplex-noise@4.0.3"]
    listing = T.library(str(project))
    assert "Packages a component can import: " in listing and "- simplex-noise 4.0.3" in listing
    assert "@remotion/paths" in listing and "react" in listing


def test_the_workspace_folder_itself_takes_packages(ws, fake_npm):
    w, _ = ws
    assert T.add_package(str(w.root), ["d3-shape"]).ok
    assert W.declared(w.root) == {"d3-shape": "1.0.0"}
    assert not T.add_package(str(w.root.parent), ["d3-shape"]).ok          # no workspace above it


def test_only_shipped_packages_change_nothing(ws, fake_npm):
    w, project = ws
    r = T.add_package(str(project), ["react", "remotion@4"])
    assert not r.ok and "already there" in r and "nothing to install" in r
    assert fake_npm() == [] and not (w.root / "package.json").exists()


def test_a_bad_name_refuses_the_whole_call(ws, fake_npm):
    w, project = ws
    r = T.add_package(str(project), ["d3-shape", "git+https://evil.example/x.git"])
    assert not r.ok and "not a registry package name" in r
    assert fake_npm() == [] and not (w.root / "package.json").exists()


def test_no_names_restores_what_package_json_lists(ws, fake_npm):
    w, project = ws
    assert "no packages yet" in T.add_package(str(project), [])
    assert T.add_package(str(project), ["a-pkg@2.0.0", "b-pkg"]).ok
    shutil.rmtree(w.root / "node_modules")
    assert "not installed" in W.packages_text(w.root)
    r = T.add_package(str(project), [])
    assert r.ok and "restored 2 package(s)" in r and "- a-pkg 2.0.0" in r
    assert "--" not in fake_npm()[-1] and (w.root / "node_modules" / "b-pkg").is_dir()


def test_a_failed_install_puts_package_json_back(ws, fake_npm, monkeypatch):
    w, project = ws
    assert T.add_package(str(project), ["a-pkg"]).ok
    before = (w.root / "package.json").read_bytes(), (w.root / "package-lock.json").read_bytes()
    monkeypatch.setenv("FAKE_NPM_FAIL", "1")
    r = T.add_package(str(project), ["b-pkg"])
    assert not r.ok and "the registry could not be reached" in r and "package.json is as it was" in r
    assert ((w.root / "package.json").read_bytes(), (w.root / "package-lock.json").read_bytes()) == before
    assert not (w.root / ".cache" / "packages.lock").exists()


def test_a_dependency_from_outside_the_registry_is_removed_again(ws, fake_npm, monkeypatch):
    w, project = ws
    monkeypatch.setenv("FAKE_NPM_RESOLVED", "git+ssh://git@github.com/evil/x.git#abc")
    r = T.add_package(str(project), ["a-pkg"])
    assert not r.ok and "only registry packages" in r and "a-pkg (git+ssh://" in r
    calls = fake_npm()
    assert len(calls) == 2 and "--" not in calls[1]          # the restore after putting package.json back
    assert "they were removed again" in r and not (w.root / "node_modules" / "a-pkg").exists()
    assert W.declared(w.root) == {}


def test_removing_a_foreign_package_stays_inside_node_modules(tmp_path):
    (tmp_path / "node_modules" / "@s" / "x").mkdir(parents=True)
    (tmp_path / "keep").mkdir()
    assert W.remove_installed(tmp_path, ["@s/x", "../keep", "missing"]) == [str(tmp_path / "node_modules" / "../keep")]
    assert not (tmp_path / "node_modules" / "@s" / "x").exists() and (tmp_path / "keep").is_dir()


def test_the_install_lock_waits_and_clears_a_stale_one(tmp_path):
    lock = tmp_path / ".cache" / "packages.lock"
    with W._Lock(lock, wait_s=0.2):
        with pytest.raises(W.WorkbenchError):
            with W._Lock(lock, wait_s=0.2):
                pass
    assert not lock.exists()
    lock.write_text("")
    old = time.time() - W.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    with W._Lock(lock, wait_s=0.2):
        assert lock.exists()


def test_typecheck_sees_the_workspace_packages_and_made_files(ws):
    w, _ = ws
    cfg = json.loads(T._typecheck_config(w, Path("R")).read_text())
    opts, own = cfg["compilerOptions"], (w.root / "node_modules").as_posix()
    assert opts["paths"]["*"] == [f"{own}/@types/*", f"{own}/*", "R/node_modules/@types/*", "R/node_modules/*"]
    assert opts["paths"]["react"][:2] == ["R/node_modules/@types/react", "R/node_modules/react"]
    assert opts["paths"]["@remotion/*"][1] == "R/node_modules/@remotion/*" and opts["resolveJsonModule"] is True
    media = Path(cfg["include"][-1])
    assert media.name == "media.d.ts" and 'declare module "*.png"' in media.read_text()


# ------------------------------------------------------------------ run_script: arguments and refusals
def test_the_sandbox_command_line(ws):
    w, project = ws
    reads, writes = W.sandbox_dirs(project, w)
    script = w.library_dir / "tools" / "t.mjs"
    cmd = W.script_command("node", script, ["--seed", "3"], reads, writes)
    nm = W.renderer_dir().resolve() / "node_modules"
    pkgs = W.renderer_packages()
    assert pkgs and nm / "remotion" in pkgs and all(p.parent == nm and not p.name.startswith(".") for p in pkgs)
    assert cmd == ["node", "--permission", "--no-addons", "--no-experimental-sqlite",
                   f"--allow-fs-read={project}", f"--allow-fs-read={w.library_dir}",
                   f"--allow-fs-read={w.root / 'node_modules'}", *[f"--allow-fs-read={p}" for p in pkgs],
                   f"--allow-fs-read={W.PRELOAD}",
                   f"--allow-fs-write={project / 'made'}", f"--allow-fs-write={w.library_dir / 'made'}",
                   "--import", W.PRELOAD.as_uri(), str(script), "--seed", "3"]
    assert f"--allow-fs-read={nm}" not in cmd and f"--allow-fs-read={nm / '.cache'}" not in cmd
    with pytest.raises(W.WorkbenchError, match="too long"):
        W.script_command("node", script, ["x" * 2000] * 16, reads, writes)
    assert not any(a.startswith(("--allow-child", "--allow-worker", "--allow-addons", "--allow-wasi",
                                 "--allow-inspector")) for a in cmd)
    env = W.script_env(project, w)
    assert set(env) - {"SYSTEMROOT"} == {"REELSMITH_MADE", "REELSMITH_LIBRARY_MADE", "REELSMITH_RENDERER_MODULES"}


def test_scripts_live_in_the_project_or_the_library(ws, tmp_path):
    w, project = ws
    (w.library_dir / "tools").mkdir()
    (w.library_dir / "tools" / "t.mjs").write_text("")
    (project / "local.js").write_text("")
    assert W.resolve_script(project, w, "library/tools/t.mjs") == (w.library_dir / "tools" / "t.mjs").resolve()
    assert W.resolve_script(project, w, "local.js") == (project / "local.js").resolve()
    assert W.resolve_script(project, w, str(project / "local.js")) == (project / "local.js").resolve()
    (w.root / "top.mjs").write_text("")
    (project / "x.py").write_text("")
    (project / "node_modules" / "p").mkdir(parents=True)
    (project / "node_modules" / "p" / "i.mjs").write_text("")
    (tmp_path / "out.mjs").write_text("")
    for bad in ("top.mjs", "../../top.mjs", "x.py", "node_modules/p/i.mjs", str(tmp_path / "out.mjs"), "nope.mjs",
                "", "a\0b"):
        with pytest.raises(W.WorkbenchError):
            W.resolve_script(project, w, bad)


def test_secrets_and_the_workspace_itself_are_never_handed_to_a_script(ws):
    w, project = ws
    reads = W.sandbox_dirs(project, w)[0]
    assert W.sandbox_problems(project, w, reads) == []
    (project / ".env").write_text("K=v")
    (w.library_dir / "id.pem").write_text("")
    found = W.sandbox_problems(project, w, reads)
    assert len(found) == 2 and all("looks like a secret" in f for f in found)
    assert "holds the workspace itself" in W.sandbox_problems(w.root, w, W.sandbox_dirs(w.root, w)[0])[0]
    (project / "s.mjs").write_text("")
    r = T.run_script(str(project), "s.mjs")
    assert not r.ok and "the script was not run" in r


def test_arguments_and_time_limits_are_checked(ws):
    _, project = ws
    (project / "s.mjs").write_text("")
    assert not T.run_script(str(project), "s.mjs", ["x"] * (W.MAX_ARGS + 1)).ok
    assert not T.run_script(str(project), "s.mjs", timeout_s=0).ok
    assert not T.run_script(str(project), "s.mjs", timeout_s=W.MAX_SCRIPT_TIMEOUT_S + 1).ok


def test_output_is_capped_and_a_timeout_kills_the_tree(tmp_path):
    rc, out, err, timed, dropped = W.run_capped([sys.executable, "-c", "print('x' * 100000)"], tmp_path, dict(os.environ),
                                                30, cap=1000)
    assert rc == 0 and len(out) == 1000 and dropped > 99000 and not timed
    code = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print('up', flush=True); time.sleep(60)")
    t0 = time.monotonic()
    rc, out, err, timed, dropped = W.run_capped([sys.executable, "-c", code], tmp_path, dict(os.environ), 2)
    assert timed and out.strip() == "up" and time.monotonic() - t0 < 30


PROBE = """import fs from "node:fs";
const out = {};
const tryIt = async (k, f) => { try { out[k] = String(await f()); } catch (e) { out[k] = "denied:" + (e.code || e.message); } };
await tryIt("workspace", () => fs.readFileSync("../../workspace.json", "utf8"));
await tryIt("env", () => fs.readFileSync("../../.env", "utf8"));
await tryIt("own", () => fs.readFileSync("project.json", "utf8").length);
await tryIt("writeProject", () => fs.writeFileSync("project.json", "{}"));
await tryIt("writeComponents", () => fs.writeFileSync(process.env.REELSMITH_LIBRARY_MADE + "/../components/X.tsx", ""));
await tryIt("child", async () => (await import("node:child_process")).execSync("echo hi"));
await tryIt("worker", async () => new (await import("node:worker_threads")).Worker("0", { eval: true }));
await tryIt("paths", async () => (await import("@remotion/paths")).getLength("M 0 0 L 3 4"));
out.keys = Object.keys(process.env).filter((k) => k !== "SYSTEMROOT").sort().join(",");
fs.writeFileSync("made/out.json", JSON.stringify(out));
fs.writeFileSync(process.env.REELSMITH_LIBRARY_MADE + "/kept.txt", "kept");
console.log(process.argv.slice(2).join("|"), process.cwd());
"""


@needs_node
def test_a_real_script_runs_inside_the_sandbox(ws, monkeypatch):
    w, project = ws
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-leak")
    (w.root / ".env").write_text("SECRET=1", encoding="utf-8")
    (w.library_dir / "tools").mkdir()
    (w.library_dir / "tools" / "probe.mjs").write_text(PROBE, encoding="utf-8")
    before = (project / "project.json").read_text()
    r = T.run_script(str(project), "library/tools/probe.mjs", ["a b", "--flag"])
    assert r.ok, r
    assert "made made/out.json" in r and "made library/made/kept.txt" in r and f"a b|--flag {project}" in r
    got = json.loads((project / "made" / "out.json").read_text())
    for key in ("workspace", "env", "writeProject", "writeComponents", "child", "worker"):
        assert got[key].startswith("denied:ERR_ACCESS_DENIED"), (key, got[key])
    assert got["own"] == str(len(before)) and got["paths"] == "5"
    assert got["keys"] == "REELSMITH_LIBRARY_MADE,REELSMITH_MADE,REELSMITH_RENDERER_MODULES"
    assert (project / "project.json").read_text() == before
    assert not (w.library_dir / "components" / "X.tsx").exists()


@needs_node
def test_a_script_that_runs_too_long_is_stopped(ws):
    _, project = ws
    (project / "spin.mjs").write_text('console.log("start"); for (;;) {}', encoding="utf-8")
    t0 = time.monotonic()
    r = T.run_script(str(project), "spin.mjs", timeout_s=2)
    assert not r.ok and r.startswith("stopped after 2 s") and "start" in r and time.monotonic() - t0 < 30
    (project / "bad.mjs").write_text('import fs from "node:fs"; fs.readFileSync("../../workspace.json")',
                                     encoding="utf-8")
    r = T.run_script(str(project), "bad.mjs")
    assert not r.ok and "exit 1" in r and "the sandbox refused that" in r


def test_the_cli_reads_add_and_script():
    a = cli._parser().parse_args(["add", "proj", "d3-shape", "simplex-noise@4.0.3"])
    assert a.cmd == "add" and a.names == ["d3-shape", "simplex-noise@4.0.3"]
    s = cli._parser().parse_args(["script", "proj", "--timeout", "5", "library/tools/t.mjs", "--seed", "3"])
    assert (s.cmd, s.script, s.args, s.timeout_s) == ("script", "library/tools/t.mjs", ["--seed", "3"], 5.0)
    assert {"add_package", "run_script"} <= set(T.TOOLS)
