"""What run_script and add_package close beyond Node's permission model: network, signals, trace files, V8 flags,
the renderer's build cache, disk use, planted workspaces and secrets, and what a refusal gives away."""
import json
import shutil
import socket
import subprocess
import sys
import threading

import pytest

from reelsmith import tools as T
from reelsmith import workbench as W
from reelsmith.workspace import Workspace

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")


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


def _probe(project, body: str, args=(), **kw) -> dict:
    (project / "probe.mjs").write_text(
        'import fs from "node:fs";\nconst out = {};\n'
        'const t = async (k, f) => { try { out[k] = String(await f()); } catch (e) { out[k] = "denied:" + (e.code || e.name); } };\n'
        + body + '\nfs.writeFileSync("made/probe.json", JSON.stringify(out));\nprocess.exit(0);\n', encoding="utf-8")
    r = T.run_script(str(project), "probe.mjs", list(args), timeout_s=30, **kw)
    assert "exit 0" in r, r
    return json.loads((project / "made" / "probe.json").read_text(encoding="utf-8"))


NET = """import net from "node:net"; import tls from "node:tls"; import dgram from "node:dgram"; import dns from "node:dns";
import http from "node:http";
const port = Number(process.argv[2]), pipe = process.argv[3];
await t("connect", () => new Promise((ok, no) => net.connect(port, "127.0.0.1", () => ok("opened")).on("error", no)));
await t("fetch", async () => (await fetch(`http://127.0.0.1:${port}/`)).status);
await t("http", () => new Promise((ok, no) => http.get(`http://127.0.0.1:${port}/`, () => ok("got")).on("error", no)));
await t("pipe", () => new Promise((ok, no) => net.connect(pipe, () => ok("opened")).on("error", no)));
await t("rawTcp", () => { const h = new tls.TLSSocket()._handle._parent; const req = new h.constructor(0);
  req.oncomplete = () => {}; return h.connect(req, "127.0.0.1", port); });
await t("rawPipe", () => { const H = process.stdout._handle.constructor; const h = new H(1); const req = new H(1);
  req.oncomplete = () => {}; return h.connect(req, pipe); });
await t("rawOpen", () => new tls.TLSSocket()._handle._parent.open(5));
await t("udp", () => dgram.createSocket("udp4").send("x", port, "127.0.0.1"));
await t("rawUdp", () => { const u = dgram.createSocket("udp4");
  const st = Object.getOwnPropertySymbols(u).map((s) => u[s]).find((v) => v && v.handle);
  return st.handle.bind("127.0.0.1", 0, 0); });
await t("dns", () => new Promise((ok, no) => dns.lookup("localhost", (e, a) => e ? no(e) : ok(a))));
await t("dnsRaw", () => new dns.Resolver()._handle.queryA({ oncomplete() {} }, "example.com"));
await t("listen", () => new Promise((ok, no) => net.createServer().listen(0, () => ok("listening")).on("error", no)));
await t("serverHandle", () => net._createServerHandle("127.0.0.1", 0, 4));
await t("putBack", () => { net.Socket.prototype.connect = () => 1; return "assigned"; });
await t("redefine", () => { Object.defineProperty(net.Socket.prototype, "connect", { value: () => 1 }); return "x"; });
"""


@needs_node
def test_a_script_has_no_network_not_even_local(ws):
    _, project = ws
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(0.2)
    port, hits, stop = srv.getsockname()[1], [], threading.Event()

    def accept():
        while not stop.is_set():
            try:
                hits.append(srv.accept())
            except OSError:
                pass
    threading.Thread(target=accept, daemon=True).start()
    pipe = rf"\\.\pipe\reelsmith-test-{port}" if sys.platform == "win32" else str(project / "made" / "s.sock")
    if sys.platform == "win32":
        from multiprocessing.connection import Listener
        listener = Listener(pipe, family="AF_PIPE")
        threading.Thread(target=lambda: hits.append(listener.accept()), daemon=True).start()
    try:
        got = _probe(project, NET, [str(port), pipe])
    finally:
        stop.set()
        srv.close()
    assert len(got) == 15
    for key, value in got.items():
        assert value.startswith("denied:"), (key, value)
    assert hits == []


@needs_node
def test_trace_files_and_v8_flags_are_refused(ws):
    _, project = ws
    got = _probe(project, "await t('trace', async () => (await import('node:trace_events')).createTracing("
                          "{ categories: ['node.perf'] }).enable());"
                          "await t('v8', async () => (await import('node:v8')).setFlagsFromString('--allow-natives-syntax'));")
    assert got == {"trace": "denied:ERR_ACCESS_DENIED", "v8": "denied:ERR_ACCESS_DENIED"}
    assert not list(project.glob("node_trace*"))


@needs_node
def test_the_renderer_build_cache_is_unreadable_but_its_packages_import(ws):
    _, project = ws
    got = _probe(project, "const nm = process.env.REELSMITH_RENDERER_MODULES;"
                          "await t('cache', () => fs.readdirSync(nm + '/.cache').length);"
                          "await t('root', () => fs.readdirSync(nm).length);"
                          "await t('paths', async () => (await import('@remotion/paths')).getLength('M 0 0 L 3 4'));")
    assert got["cache"].startswith("denied:") and got["root"].startswith("denied:") and got["paths"] == "5", got


@needs_node
def test_a_script_that_fills_the_disk_is_stopped(ws):
    w, project = ws
    (project / "flood.mjs").write_text(
        'import fs from "node:fs"; const b = Buffer.alloc(1 << 20);'
        'for (let i = 0; i < 400; i++) { fs.appendFileSync("made/big.bin", b); await new Promise(r => setTimeout(r, 20)); }',
        encoding="utf-8")
    ok, text = W.run_script(project, w, "flood.mjs", timeout_s=60, made_cap=3 << 20)
    assert not ok and text.startswith("stopped: it wrote more than 3.0 MB"), text
    assert (project / "made" / "big.bin").stat().st_size < 100 << 20


def test_what_a_script_wrote_into_made_never_locks_out_later_runs(ws):
    w, project = ws
    reads = W.sandbox_dirs(project, w)[0]
    for name in (".env", "workspace.json", "id_rsa", ".npmrc"):
        (project / "made" / name).parent.mkdir(exist_ok=True)
        (project / "made" / name).write_text("planted")
    (w.library_dir / "made").mkdir()
    (w.library_dir / "made" / "credentials.json").write_text("planted")
    assert W.sandbox_problems(project, w, reads) == []
    for name in (".credentials.json", "id_ed25519", ".git-credentials", "vault.kdbx", ".pypirc"):
        (project / name).write_text("")
    found = W.sandbox_problems(project, w, reads)
    assert len(found) == 5 and all("looks like a secret" in f for f in found)


def test_a_refusal_does_not_say_whether_a_file_outside_exists(ws, tmp_path):
    w, project = ws
    (tmp_path / "there.txt").write_text("x")
    (tmp_path / "there.mjs").write_text("x")
    said = set()
    for path in (tmp_path / "there.txt", tmp_path / "there.mjs", tmp_path / "missing.mjs", tmp_path / "missing.txt"):
        with pytest.raises(W.WorkbenchError) as e:
            W.resolve_script(project, w, str(path))
        said.add(str(e.value).replace(str(path), "PATH"))
    assert len(said) == 1


@needs_node
def test_a_script_cannot_tell_whether_a_file_outside_exists(ws, tmp_path):
    w, project = ws
    (tmp_path / "there.txt").write_text("x")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "package.json").write_text("{}")
    (tmp_path / "pkg" / "x.js").write_text("")
    there, gone = json.dumps(str(tmp_path / "there.txt")), json.dumps(str(tmp_path / "gone.txt"))
    pkg, nopkg = json.dumps((tmp_path / "pkg" / "x.js").as_uri()), json.dumps((tmp_path / "pkg" / "y.js").as_uri())
    got = _probe(project, "import { createRequire, findPackageJSON } from 'node:module';"
                          f"await t('there', () => fs.realpathSync({there}));"
                          f"await t('gone', () => fs.realpathSync({gone}));"
                          f"await t('native', () => fs.realpathSync.native({there}));"
                          f"await t('promise', () => fs.promises.realpath({there}));"
                          f"await t('pkg', () => findPackageJSON({pkg}));"
                          f"await t('nopkg', () => findPackageJSON({nopkg}));"
                          f"await t('pkgPath', () => findPackageJSON({there}));"
                          "await t('own', () => fs.realpathSync('project.json').endsWith('project.json'));"
                          "await t('req', () => typeof createRequire(import.meta.url)('@remotion/paths').getLength);")
    for key in ("there", "gone", "native", "promise", "pkg", "nopkg", "pkgPath"):
        assert got[key] == "denied:ERR_ACCESS_DENIED", (key, got[key])
    assert got["own"] == "true" and got["req"] == "function"


def test_a_planted_project_json_does_not_make_made_a_workspace(ws):
    w, project = ws
    made = project / "made"
    (made / "made").mkdir(parents=True)
    (made / "workspace.json").write_text("{}")
    (made / "project.json").write_text("{}")
    (made / "made" / "workspace.json").write_text("{}")
    from reelsmith.workspace import find_workspace, in_made
    assert in_made(made) and in_made(made / "made") and not in_made(project) and not in_made(w.root)
    assert find_workspace(made / "made").root == w.root


def test_npm_never_runs_in_a_made_folder(ws, monkeypatch):
    w, project = ws
    made = project / "made"
    made.mkdir()
    (made / "workspace.json").write_text("{}", encoding="utf-8")
    (made / ".npmrc").write_text("git=evil.exe\n", encoding="utf-8")
    (made / "package.json").write_text('{"dependencies": {"x": "git+https://example.invalid/x.git"}}')
    with pytest.raises(W.WorkbenchError, match="made/"):
        W.add_packages(made, [])
    seen = []
    monkeypatch.setattr(W, "add_packages", lambda root, specs: (seen.append(root), (True, "ok"))[1])
    assert T.add_package(str(made), []).ok and seen == [w.root]          # no fence: still the real workspace


@pytest.mark.parametrize("spec", ["x@1.0.0-a.tgz", "x@1.0.0-A.TGZ", "x@v1.x", "x@next.zip"])
def test_versions_and_tags_that_npm_reads_as_files_are_refused(spec):
    with pytest.raises(W.WorkbenchError):
        W.parse_spec(spec)
