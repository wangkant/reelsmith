"""Hostile use of add_package and run_script: what the boundary holds."""
import json
import shutil
import subprocess
import sys

import pytest

from reelsmith import tools as T
from reelsmith import workbench as W
from reelsmith.workspace import Workspace

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows path forms")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    root = tmp_path / "ws"
    (root / "library" / "components").mkdir(parents=True)
    (root / "workspace.json").write_text("{}", encoding="utf-8")
    project = root / "projects" / "p"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"version": 2, "assets": {}, "tracks": []}), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("DECOY", encoding="utf-8")
    sibling = root / "projects" / "p2"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("DECOY", encoding="utf-8")
    return Workspace.load(root), project, outside


def _probe(project, body: str) -> dict:
    (project / "probe.mjs").write_text(
        'import fs from "node:fs";\nconst out = {};\n'
        'const t = async (k, f) => { try { out[k] = String(await f()); } catch (e) { out[k] = "denied:" + (e.code || e.name); } };\n'
        + body + '\nfs.writeFileSync("made/probe.json", JSON.stringify(out));\n', encoding="utf-8")
    r = T.run_script(str(project), "probe.mjs", timeout_s=30)
    assert "exit 0" in r, r
    return json.loads((project / "made" / "probe.json").read_text(encoding="utf-8"))


@needs_node
def test_path_forms_do_not_reach_outside(ws):
    _, project, outside = ws
    s = str(outside / "secret.txt")
    sib = str(project.parent / "p2" / "secret.txt")
    got = _probe(project, "\n".join(f"await t({json.dumps(k)}, () => fs.readFileSync({json.dumps(p)}, 'utf8'));" for k, p in {
        "direct": s, "upper": s.upper(), "prefix_sibling": sib, "long": "\\\\?\\" + s,
        "unc": "\\\\localhost\\" + s[0] + "$" + s[2:], "ads": s + "::$DATA"}.items())
        + f"\nawait t('url', () => fs.readFileSync(new URL({json.dumps((outside / 'secret.txt').as_uri())}), 'utf8'));"
        + f"\nawait t('symlink', () => fs.symlinkSync({json.dumps(str(outside))}, 'made/l', 'junction'));"
        + f"\nawait t('hardlink', () => fs.linkSync({json.dumps(s)}, 'made/h.txt'));")
    for key, value in got.items():
        assert value.startswith("denied:ERR_ACCESS_DENIED"), (key, value)


@needs_node
def test_sqlite_cannot_touch_files_outside(ws):
    _, project, outside = ws
    target = json.dumps(str(outside / "made.db"))
    got = _probe(project, f"await t('sqlite', async () => {{ const {{ DatabaseSync }} = await import('node:sqlite'); "
                          f"new DatabaseSync({target}).exec('create table t(a)'); return 'opened'; }});")
    assert got["sqlite"].startswith("denied:") and not (outside / "made.db").exists()
    got = _probe(project, "await t('builtin', () => typeof process.getBuiltinModule('node:sqlite'));"
                          "await t('require', async () => (await import('node:module')).createRequire(import.meta.url)"
                          "('node:sqlite'));")
    assert got["builtin"] == "undefined" and got["require"].startswith("denied:"), got


@needs_node
def test_a_script_cannot_kill_other_processes(ws):
    _, project, _ = ws
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        got = _probe(project, f"await t('kill', () => process.kill({victim.pid}));"
                              f"await t('_kill', () => process._kill({victim.pid}, 15));"
                              f"await t('parent', () => process.kill(process.ppid));"
                              f"await t('priority', async () => (await import('node:os')).setPriority({victim.pid}, 19));"
                              "await t('self', () => process.kill(process.pid, 0));")
        assert all(got[k].startswith("denied:") for k in ("kill", "_kill", "parent", "priority")), got
        assert got["self"] == "true" and victim.poll() is None
    finally:
        victim.kill()


@pytest.mark.parametrize("spec", ["x@evil.tgz", "x@evil.tar", "x@a.tar.gz", "x@v1.tar"])
def test_a_tag_that_npm_reads_as_a_file_is_refused(spec):
    with pytest.raises(W.WorkbenchError):
        W.parse_spec(spec)


def test_add_package_ignores_a_workspace_planted_in_made(ws, monkeypatch):
    w, project, _ = ws
    made = project / "made"
    made.mkdir()
    (made / "workspace.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("REELSMITH_ROOT", str(w.root))
    _, found = T._workspace_of(str(made))                 # noqa: SLF001
    assert found.root == w.root
