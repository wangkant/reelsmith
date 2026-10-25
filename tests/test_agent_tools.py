"""The api engine's toolbox, offline: reelsmith tools through their schemas, guarded file tools, and the web tools over
local servers with fake resolvers (no real network)."""
import asyncio
import http.server
import inspect
import json
import os
import shutil
import socket
import sys
import threading
import types
import urllib.request
from pathlib import Path

import jsonschema
import pytest

from reelsmith import guard
from reelsmith import tools as rtools
from reelsmith.agent import tools as AT
from reelsmith.agent import web as W
from reelsmith.workspace import find_workspace

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "tests" / "fixtures" / "demo"
PUBLIC = "93.184.216.34"
ZONE = {"news.example": [PUBLIC], "intranet.example": ["10.0.0.7"], "mixed.example": [PUBLIC, "192.168.1.9"]}


def fake_resolve(host, port):
    if host not in ZONE:
        raise socket.gaierror(11001, "getaddrinfo failed")
    return list(ZONE[host])


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """The demo project inside a workspace that has a .env and a .cache, with the runner's scope."""
    monkeypatch.delenv("REELSMITH_ROOT", raising=False)
    ws_root = tmp_path / "ws"
    project = ws_root / "projects" / "demo"
    shutil.copytree(DEMO, project)
    (ws_root / "workspace.json").write_text("{}", encoding="utf-8")
    (ws_root / "library" / "components").mkdir(parents=True)
    (ws_root / ".env").write_text("FAKE_KEY=not-a-real-key\n", encoding="utf-8")
    (ws_root / ".cache").mkdir()
    (ws_root / ".cache" / "draw.log").write_text("raw words", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    ws = find_workspace(project)
    scope = guard.scope_for(project, ws, extra_read=[REPO / "docs", REPO / "renderer" / "src"])
    dialled = []

    def no_connect(address, timeout):           # nothing may leave: a connection is recorded and fails
        dialled.append(address)
        raise OSError("no network in tests")
    box = AT.toolbox(project, ws, scope, web={"search": "none", "proxy": "", "resolve": fake_resolve,
                                               "connect": no_connect})
    return types.SimpleNamespace(project=project, ws=ws, root=ws_root, scope=scope, box=box, tmp=tmp_path,
                                 dialled=dialled)


def call(box, name, /, **args):
    tool = box.get(name)
    assert tool is not None, f"no tool {name}"
    return tool.run(args)


def guard_says(scope, tool, inp):
    allowed, why = guard.decide(tool, inp, scope)
    assert not allowed
    return why


# ------------------------------------------------------------------ schemas
def test_every_reelsmith_tool_gets_a_valid_schema(demo):
    for name, fn in rtools.TOOLS.items():
        tool = demo.box.get(name)
        assert tool is not None, name
        schema = tool.parameters
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object" and "$ref" not in json.dumps(schema)
        params = inspect.signature(fn).parameters
        assert set(schema.get("properties") or {}) == set(params), name
        required = {p.name for p in params.values() if p.default is inspect.Parameter.empty}
        assert set(schema.get("required") or []) == required, name
        assert tool.description == inspect.cleandoc(fn.__doc__)


def test_reelsmith_schemas_are_the_ones_the_mcp_server_publishes(demo):
    from reelsmith import mcp_server
    published = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(published) == set(rtools.TOOLS)
    for name, t in published.items():
        assert demo.box.get(name).parameters == t.input_schema, name
        assert demo.box.get(name).description == t.description


def test_every_tool_has_a_chat_completions_spec(demo):
    names = [t.name for t in demo.box]
    assert len(names) == len(set(names))
    assert names[:len(rtools.TOOLS)] == list(rtools.TOOLS)
    assert {"read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "web_fetch"} <= set(names)
    for t in demo.box:
        jsonschema.Draft202012Validator.check_schema(t.parameters)
        spec = t.spec()
        assert spec["type"] == "function" and spec["function"]["name"] == t.name
        assert spec["function"]["parameters"]["type"] == "object" and spec["function"]["description"]
        assert len(t.description) <= 1024                 # some providers cap function descriptions there
    assert demo.box.notes == ["web search is turned off (web.search)"]
    assert demo.box.get("web_search") is None


# ------------------------------------------------------------------ reelsmith tools
def test_free_reelsmith_tools_run_through_the_tool(demo):
    r = call(demo.box, "manual")
    assert not r.error and "reelsmith" in r.text.lower() and len(r.text) > 1000
    r = call(demo.box, "library")
    assert not r.error and "component(s)" in r.text and "Receipt" in r.text
    r = call(demo.box, "describe", project=str(demo.project))
    assert not r.error and r.text.startswith("project demo")
    r = call(demo.box, "describe")                        # project left out: this run's project
    assert not r.error and r.text.startswith("project demo")
    r = call(demo.box, "describe", project=".")           # relative to the project, not the process's cwd
    assert not r.error and r.text.startswith("project demo")
    r = call(demo.box, "describe", at="line:3")
    assert not r.error and "line" in r.text


def test_arguments_are_validated_and_json_strings_opened(demo):
    r = call(demo.box, "describe", at={"not": "a time"})
    assert r.error and r.text.startswith("describe: invalid arguments") and "at" in r.text
    ops = json.dumps([{"op": "set", "path": "meta.title", "value": "奶茶的账"}], ensure_ascii=False)
    r = call(demo.box, "edit", ops=ops)                    # ops as a JSON string, as weaker models send it
    assert not r.error and r.text.startswith("applied"), r.text
    doc = json.loads((demo.project / "project.json").read_text(encoding="utf-8"))
    assert doc["meta"]["title"] == "奶茶的账"
    assert not call(demo.box, "undo").error
    doc = json.loads((demo.project / "project.json").read_text(encoding="utf-8"))
    assert doc["meta"]["title"] == "一杯奶茶的成本"
    r = demo.box.get("describe").run(json.dumps({"at": 1.0}))     # the whole arguments as a JSON string
    assert not r.error
    r = demo.box.get("describe").run(["not", "an object"])
    assert r.error and "JSON object" in r.text


def test_reelsmith_tools_are_held_to_the_guard(demo):
    other = demo.tmp / "elsewhere"
    r = call(demo.box, "describe", project=str(other))
    assert r.error and r.text == guard_says(demo.scope, "mcp__reelsmith__describe", {"project": str(other)})
    outside = str(demo.tmp / "outside.txt")
    r = call(demo.box, "import_asset", id="x", source=outside)
    assert r.error and r.text == guard_says(demo.scope, "mcp__reelsmith__import_asset",
                                            {"project": str(demo.project), "id": "x", "source": outside})
    r = call(demo.box, "capture", id="ev2", url="http://127.0.0.1:8080/admin")
    assert r.error and "Local network" in r.text


def test_a_failing_reelsmith_call_is_flagged(demo):
    r = call(demo.box, "library", name="NoSuchComponent")
    assert r.error and "no component" in r.text


def test_reelsmith_root_is_set_for_the_call_only(demo, monkeypatch):
    @rtools.tool
    def where(project: str) -> str:
        """Where the fence is."""
        return os.environ.get("REELSMITH_ROOT", "unset")
    tool = AT.reelsmith_tool("where", where, demo.project, demo.scope)
    assert tool.run({}).text == str(demo.scope.home)
    assert "REELSMITH_ROOT" not in os.environ
    monkeypatch.setenv("REELSMITH_ROOT", "owner-value")
    assert tool.run({}).text == str(demo.scope.home)
    assert os.environ["REELSMITH_ROOT"] == "owner-value"


# ------------------------------------------------------------------ read_file
def test_read_file_numbers_lines_and_pages(demo):
    r = call(demo.box, "read_file", path="project.json", limit=3)
    lines = r.text.split("\n")
    assert not r.error and lines[0] == "     1\t{" and lines[1].startswith("     2\t")
    assert lines[3].startswith("... ") and "offset=4" in lines[3]
    r = call(demo.box, "read_file", file_path="project.json", offset=2, limit=1)      # Claude Code's argument name
    assert r.text.split("\n")[0].startswith("     2\t")
    r = call(demo.box, "read_file", path="project.json", offset=10_000)
    assert r.error and "past the end" in r.text
    (demo.project / "crlf.md").write_bytes("一\r\n二\r\n".encode("utf-8"))
    assert call(demo.box, "read_file", path="crlf.md").text == "     1\t一\n     2\t二"
    long = demo.project / "long.txt"
    long.write_text("x" * 5000 + "\n", encoding="utf-8")
    assert "3000 more characters" in call(demo.box, "read_file", path=str(long)).text


def test_read_file_inside_and_outside_the_scope(demo):
    manual = REPO / "docs" / "manual.md"
    assert not call(demo.box, "read_file", path=str(manual), limit=1).error        # the manual is readable
    assert not call(demo.box, "read_file", path=str(demo.root / "workspace.json")).error
    for target in (str(demo.tmp / "outside.txt"), "../../.env", str(demo.root / ".env"),
                   str(demo.root / ".cache" / "draw.log"), "C:/Windows/win.ini"):
        r = call(demo.box, "read_file", path=target)
        assert r.error and r.text == guard_says(demo.scope, "Read", {"file_path": target}), target
    assert call(demo.box, "read_file", path="").error
    r = call(demo.box, "read_file", path="assets")
    assert r.error and "folder" in r.text
    r = call(demo.box, "read_file", path="nope.txt")
    assert r.error and "does not exist" in r.text


def test_read_file_shows_images_and_refuses_media_and_binaries(demo):
    r = call(demo.box, "read_file", path="assets/photo.png")
    assert not r.error and r.images == [demo.project / "assets" / "photo.png"]
    assert "270x480" in r.text
    (demo.project / "broken.png").write_bytes(b"not a png at all")
    r = call(demo.box, "read_file", path="broken.png")
    assert r.error and not r.images and "not a readable image" in r.text
    r = call(demo.box, "read_file", path="assets/clip.mp4")
    assert r.error and "preview or review" in r.text
    (demo.project / "blob.bin").write_bytes(b"\x00\x01\x02" * 100)
    r = call(demo.box, "read_file", path="blob.bin")
    assert r.error and "binary" in r.text


# ------------------------------------------------------------------ write_file / edit_file
def test_write_file_inside_the_scope(demo):
    r = call(demo.box, "write_file", path="notes/a/b.md", content="第一行\n第二行\n")
    assert not r.error and r.text.startswith("created notes/a/b.md")
    assert (demo.project / "notes" / "a" / "b.md").read_bytes() == "第一行\n第二行\n".encode("utf-8")
    (demo.project / "script.md").write_text("# old\n", encoding="utf-8")
    r = call(demo.box, "write_file", file_path="script.md", content="# new\n")
    assert not r.error and r.text.startswith("overwrote script.md")
    assert (demo.project / "script.md").read_text(encoding="utf-8") == "# new\n"
    lib = demo.root / "library" / "components" / "Card.tsx"
    assert not call(demo.box, "write_file", path=str(lib), content="export const x = 1;\n").error
    assert lib.is_file()


@pytest.mark.parametrize("target", ["build/x.json", "out/film.mp4", ".history/1.json", "../../workspace.json",
                                    "../../rules.json", "tool.py", "run.ps1", "../../.env", "../../outside.txt",
                                    "rules.json", "C:/Windows/x.txt"])
def test_write_file_outside_the_scope_is_refused_with_the_guards_reason(demo, target):
    r = call(demo.box, "write_file", path=target, content="x")
    assert r.error and r.text == guard_says(demo.scope, "Write", {"file_path": target})
    resolved = guard.resolve_token(target, demo.project)
    assert resolved is None or not resolved.is_file() or resolved.read_text(encoding="utf-8") != "x"


def test_edit_file_match_rules(demo):
    f = demo.project / "script.md"
    f.write_text("alpha\nbeta\nalpha\n", encoding="utf-8")
    r = call(demo.box, "edit_file", path="script.md", old="beta", new="gamma")
    assert not r.error and "1 replacement" in r.text
    assert f.read_text(encoding="utf-8") == "alpha\ngamma\nalpha\n"
    r = call(demo.box, "edit_file", path="script.md", old="alpha", new="delta")
    assert r.error and "matches 2 places" in r.text
    assert f.read_text(encoding="utf-8") == "alpha\ngamma\nalpha\n"
    r = call(demo.box, "edit_file", path="script.md", old="zeta", new="eta")
    assert r.error and "not found" in r.text
    r = call(demo.box, "edit_file", path="script.md", old="alpha", new="delta", replace_all=True)
    assert not r.error and "2 replacement" in r.text
    assert f.read_text(encoding="utf-8") == "delta\ngamma\ndelta\n"
    r = call(demo.box, "edit_file", file_path="script.md", old_string="gamma\n", new_string="")   # Claude Code's names
    assert not r.error and f.read_text(encoding="utf-8") == "delta\ndelta\n"
    assert call(demo.box, "edit_file", path="script.md", old="", new="x").error
    assert call(demo.box, "edit_file", path="script.md", old="delta", new="delta").error
    r = call(demo.box, "edit_file", path="missing.md", old="a", new="b")
    assert r.error and "write_file" in r.text


def test_edit_file_keeps_crlf_and_bom(demo):
    f = demo.project / "win.md"
    f.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\nthree\r\n")
    r = call(demo.box, "edit_file", path="win.md", old="one\ntwo", new="one\nTWO")
    assert not r.error
    assert f.read_bytes() == b"\xef\xbb\xbfone\r\nTWO\r\nthree\r\n"


def test_edit_file_outside_the_scope_is_refused(demo):
    for target in ("../../workspace.json", "build/report.json", str(demo.tmp / "outside.txt")):
        r = call(demo.box, "edit_file", path=target, old="a", new="b")
        assert r.error and r.text == guard_says(demo.scope, "Edit", {"file_path": target})
    assert (demo.tmp / "outside.txt").read_text(encoding="utf-8") == "outside"


# ------------------------------------------------------------------ glob / grep / list_dir
def test_glob(demo):
    r = call(demo.box, "glob", pattern="assets/*.{png,wav}")
    assert not r.error
    found = set(r.text.split("\n")[1:])
    assert found == {"assets/photo.png", "assets/evidence.png", "assets/bed.wav"}
    r = call(demo.box, "glob", pattern="**/*.json")
    assert "project.json" in r.text.split("\n") and "voice/voice.json" in r.text.split("\n")
    assert call(demo.box, "glob", pattern="project.json").text == "project.json"
    assert call(demo.box, "glob", pattern="*.nothing").text.startswith("no match")
    r = call(demo.box, "glob", pattern="*", path=str(demo.root))          # the workspace: secrets stay hidden
    assert not r.error and "workspace.json" in r.text and "projects/" in r.text
    assert ".env" not in r.text and ".cache" not in r.text


def test_glob_outside_the_scope_is_refused(demo):
    for inp in ({"pattern": "*", "path": str(demo.tmp)}, {"pattern": "**/.env*"}, {"pattern": "../../../*"},
                {"pattern": "C:/Windows/*"}):
        r = demo.box.get("glob").run(dict(inp))
        assert r.error and r.text == guard_says(demo.scope, "Glob", inp), inp
    # the guard lets a search start in .cache; what is in it is not shown
    r = call(demo.box, "glob", pattern="*", path=str(demo.root / ".cache"))
    assert not r.error and r.text.startswith("no match") and "draw.log" not in r.text
    r = call(demo.box, "list_dir", path=str(demo.root / ".cache"))
    assert "draw.log" not in r.text


def test_grep(demo):
    r = call(demo.box, "grep", pattern="photo", glob="*.json")
    assert not r.error and r.text.startswith("project.json:")
    assert all(row.startswith("project.json:") for row in r.text.split("\n"))
    r = call(demo.box, "grep", pattern="(?i)RECEIPT", path="project.json")
    assert not r.error and '"Receipt"' in r.text
    assert call(demo.box, "grep", pattern="no-such-words-here").text.startswith("no matches")
    r = call(demo.box, "grep", pattern="([unclosed")
    assert r.error and "regular expression" in r.text


def test_grep_outside_the_scope_is_refused(demo):
    for inp in ({"pattern": "KEY", "path": str(demo.root)},                  # covers .env and .cache
                {"pattern": "x", "path": str(demo.tmp)},
                {"pattern": "x", "path": str(demo.root / ".env")},
                {"pattern": "x", "glob": "../*"}):
        r = demo.box.get("grep").run(dict(inp))
        assert r.error and r.text == guard_says(demo.scope, "Grep", inp), inp


def test_list_dir(demo):
    r = call(demo.box, "list_dir")
    lines = r.text.split("\n")
    assert not r.error and lines[0] == ".:" and "assets/" in lines and any(x.startswith("project.json") for x in lines)
    assert lines.index("assets/") < next(i for i, x in enumerate(lines) if x.startswith("project.json"))
    r = call(demo.box, "list_dir", path=str(demo.root))
    assert "workspace.json" in r.text and ".env" not in r.text and ".cache" not in r.text
    r = call(demo.box, "list_dir", path=str(demo.tmp))
    assert r.error and r.text == guard_says(demo.scope, "Glob", {"pattern": "*", "path": str(demo.tmp)})
    r = call(demo.box, "list_dir", path="project.json")
    assert r.error and "read_file" in r.text


# ------------------------------------------------------------------ web_fetch
class Site(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def do_GET(self):  # noqa: N802
        self.seen.append((self.path, self.headers.get("Host")))
        status, headers, body = self.routes.get(self.path, (404, {"Content-Type": "text/html"}, b"<p>gone</p>"))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.seen.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(n) or b"{}")))
        status, headers, body = self.routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    Site.routes, Site.seen = {}, []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield types.SimpleNamespace(port=server.server_address[1], routes=Site.routes, seen=Site.seen)
    server.shutdown()
    server.server_close()


def web_box(demo, site, **web):
    port = site.port
    base = {"search": "none", "proxy": "", "resolve": fake_resolve,
            "connect": lambda address, timeout: socket.create_connection(("127.0.0.1", port), timeout=timeout)}
    return AT.toolbox(demo.project, demo.ws, demo.scope, web={**base, **web})


PAGE = """<!doctype html><html><head><title>油价 新闻</title><script>var secret = "nope";</script>
<style>.x{color:red}</style></head><body><nav><a href="/">Home</a></nav>
<h1>油价又涨了</h1><p>今天的油价 <b>上调</b> 了。</p><ul><li>一</li><li>二</li></ul>
<p>Read <a href="/more">the full story</a> here.</p><svg><title>icon</title><text>svg text</text></svg>
<img src="a.png" alt="加油站"></body></html>"""


def test_web_fetch_reads_a_public_page_as_text(demo, site):
    site.routes["/page"] = (200, {"Content-Type": "text/html; charset=utf-8"}, PAGE.encode("utf-8"))
    box = web_box(demo, site)
    r = call(box, "web_fetch", url="http://news.example/page")
    assert not r.error, r.text
    lines = r.text.split("\n")
    assert lines[0] == "油价 新闻" and lines[1] == "URL: http://news.example/page"
    assert "# 油价又涨了" in r.text and "今天的油价 上调 了。" in r.text and "- 一" in r.text
    assert "[the full story](http://news.example/more)" in r.text and "[image: 加油站]" in r.text
    assert "secret" not in r.text and "color:red" not in r.text and "svg text" not in r.text and "icon" not in r.text
    assert site.seen[0] == ("/page", "news.example")          # the request reached the host by name


def test_web_fetch_cuts_long_pages_and_decodes_declared_charsets(demo, site):
    site.routes["/long"] = (200, {"Content-Type": "text/plain"}, b"a" * 3000)
    site.routes["/gbk"] = (200, {"Content-Type": "text/html"},
                           '<html><head><meta charset="gbk"><title>中文</title></head><body>正文</body></html>'
                           .encode("gbk"))
    box = web_box(demo, site)
    r = call(box, "web_fetch", url="http://news.example/long", max_chars=500)
    assert not r.error and "cut at 500 of 3000" in r.text
    r = call(box, "web_fetch", url="http://news.example/gbk")
    assert not r.error and r.text.startswith("中文") and "正文" in r.text


def test_web_fetch_refuses_media_and_reports_http_errors(demo, site):
    site.routes["/pic.png"] = (200, {"Content-Type": "image/png"}, b"\x89PNG....")
    box = web_box(demo, site)
    r = call(box, "web_fetch", url="http://news.example/pic.png")
    assert r.error and "not a text page" in r.text and "import_asset" in r.text
    r = call(box, "web_fetch", url="http://news.example/missing")
    assert r.error and "HTTP 404" in r.text and "gone" in r.text


@pytest.mark.parametrize("url, says", [
    ("http://127.0.0.1:8080/admin", "Local network"),
    ("http://localhost/", "Local network"),
    ("http://[::1]/", "Local network"),
    ("http://10.0.0.7/", "Local network"),
    ("http://192.168.1.1/router", "Local network"),
    ("http://169.254.169.254/latest/meta-data", "Local network"),
    ("http://printer.local/", "Local network"),
    ("http://intranet/", "Local network"),
    ("http://2130706433/", "off limits"),
    ("http://0x7f.0.0.1/", "Numeric hosts"),
    ("file:///C:/Windows/win.ini", "Only http(s)"),
    ("ftp://news.example/a", "Only http(s)"),
    ("http://user:pw@news.example/", "No credentials"),
    ("http://intranet.example/", "10.0.0.7"),                  # a public-looking name on a private address
    ("http://mixed.example/", "192.168.1.9"),
    ("http://nowhere.example/", "does not resolve"),
])
def test_web_fetch_refuses_local_and_private_addresses(demo, url, says):
    r = call(demo.box, "web_fetch", url=url)
    assert r.error and says in r.text, r.text
    assert demo.dialled == []                               # refused before any connection


def test_web_fetch_checks_every_redirect_hop(demo, site):
    site.routes["/to-intranet"] = (302, {"Location": "http://intranet.example/secret"}, b"")
    site.routes["/to-file"] = (302, {"Location": "file:///C:/Windows/win.ini"}, b"")
    site.routes["/to-page"] = (301, {"Location": "/page"}, b"")
    site.routes["/page"] = (200, {"Content-Type": "text/html"}, b"<title>ok</title><p>moved here</p>")
    box = web_box(demo, site)
    r = call(box, "web_fetch", url="http://news.example/to-intranet")
    assert r.error and "refused" in r.text and "10.0.0.7" in r.text
    assert all(path != "/secret" for path, *_ in site.seen)
    r = call(box, "web_fetch", url="http://news.example/to-file")
    assert r.error and "redirected" in r.text and "Only http(s)" in r.text
    r = call(box, "web_fetch", url="http://news.example/to-page")
    assert not r.error and "URL: http://news.example/page" in r.text and "moved here" in r.text


def test_web_fetch_tunnels_https_through_the_guard(demo, site):
    dialled = []

    def connect(address, timeout):
        dialled.append(address)                 # a plain http server: the TLS handshake then fails
        return socket.create_connection(("127.0.0.1", site.port), timeout=timeout)
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": "none", "proxy": "", "resolve": fake_resolve,
                                                             "connect": connect})
    r = call(box, "web_fetch", url="https://news.example/secure")
    assert r.error and r.text.startswith("cannot fetch https://news.example/secure")
    assert dialled == [(PUBLIC, 443)]           # the checked address, reached through the guard's CONNECT


def test_html_text_survives_broken_markup():
    title, text = W.html_text("<title>t</title><div><p>one<p>two</div></span><a href='x'>link", "https://a.example/")
    assert title == "t" and "one" in text and "two" in text and "link" in text


# ------------------------------------------------------------------ web_search
def test_web_search_with_a_fake_backend(demo):
    asked = []

    def search(query, n, recent):
        asked.append((query, n, recent))
        return [{"title": f"结果 {i}", "url": f"https://news.example/{i}", "snippet": "  摘要\n内容 "}
                for i in range(n + 5)]
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": search, "fetch": False})
    assert box.get("web_fetch") is None and box.notes == ["web_fetch is left out: turned off (web.fetch)"]
    r = call(box, "web_search", query="油价", n=3, recent="week")
    assert not r.error and asked == [("油价", 3, "week")]
    assert r.text.split("\n")[:3] == ["1. 结果 0", "   https://news.example/0", "   摘要 内容"]
    assert r.text.count("https://news.example/") == 3
    assert call(box, "web_search", query="x").text.count("\n1") == 0 and asked[-1] == ("x", 8, "")
    assert call(box, "web_search", query="x", n=99) and asked[-1][1] == 20
    assert call(box, "web_search", query="  ").error
    assert call(box, "web_search", query="x", recent="decade").error


def test_web_search_failures_and_empty_results_are_text(demo):
    def broken(query, n, recent):
        raise TimeoutError("timed out")
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": broken, "fetch": False})
    r = call(box, "web_search", query="x")
    assert r.error and "search failed" in r.text and "timed out" in r.text
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": lambda q, n, recent: [], "fetch": False})
    r = call(box, "web_search", query="x")
    assert not r.error and r.text.startswith("no results")


def test_search_backend_choice(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(W.importlib.util, "find_spec", lambda name: None)
    search, why = W.search_backend({"search": "ddgs"})
    assert search is None and "ddgs package is not installed" in why
    search, why = W.search_backend({"search": "tavily"}, keys={})
    assert search is None and "TAVILY_API_KEY" in why
    search, why = W.search_backend({}, keys={})
    assert search is None and "ddgs" in why and "TAVILY_API_KEY" in why
    search, why = W.search_backend({"search": "bing"})
    assert search is None and "unknown" in why
    assert W.search_backend({"search": None})[0] is None
    assert W.search_backend({}, keys={"TAVILY_API_KEY": "k"})[0] is not None       # auto falls to Tavily
    monkeypatch.setattr(W.importlib.util, "find_spec", lambda name: object())
    assert W.search_backend({"proxy": ""})[0] is not None                          # auto prefers ddgs


def test_toolbox_logs_why_search_is_left_out(demo, monkeypatch, caplog):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(W.importlib.util, "find_spec", lambda name: None)
    with caplog.at_level("INFO", logger="reelsmith.agent.tools"):
        box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": "tavily", "fetch": False})
    assert box.get("web_search") is None and "TAVILY_API_KEY" in box.notes[-1]
    assert "TAVILY_API_KEY" in caplog.text


def test_ddgs_adapter(monkeypatch):
    made = []

    class DDGSException(Exception):
        pass

    class DDGS:
        def __init__(self, proxy=None, timeout=5):
            made.append({"proxy": proxy, "timeout": timeout})

        def text(self, query, **kwargs):
            made.append(kwargs)
            if query == "nothing":
                raise DDGSException("No results found.")
            if query == "boom":
                raise DDGSException("https://html.duckduckgo.com/html 202 Ratelimit")
            return [{"title": "T", "href": "https://a.example/", "body": "B"}]
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=DDGS))
    monkeypatch.setitem(sys.modules, "ddgs.exceptions", types.SimpleNamespace(DDGSException=DDGSException))
    search = W.ddgs_search(proxy="http://127.0.0.1:3128")
    assert search("油价", 5, "week") == [{"title": "T", "url": "https://a.example/", "snippet": "B"}]
    assert made[0]["proxy"] == "http://127.0.0.1:3128"
    assert made[1] == {"region": "cn-zh", "max_results": 5, "timelimit": "w"}
    search("oil prices", 3, "")
    assert made[-1] == {"region": "us-en", "max_results": 3}
    assert search("nothing", 3, "") == []
    with pytest.raises(DDGSException):
        search("boom", 3, "")


def test_tavily_adapter_over_a_local_server(demo, site, monkeypatch):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})     # no system proxy between us and the server
    site.routes["/search"] = (200, {"Content-Type": "application/json"}, json.dumps({"results": [
        {"title": "油价", "url": "https://news.example/1", "content": "上调", "score": 0.9}]}).encode("utf-8"))
    site.routes["/denied"] = (401, {"Content-Type": "application/json"}, b'{"detail": "bad key"}')
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={
        "search": "tavily", "fetch": False, "tavily_key": "test-key",
        "tavily_url": f"http://127.0.0.1:{site.port}/search"})
    r = call(box, "web_search", query="油价", n=4, recent="day")
    assert not r.error and r.text == "1. 油价\n   https://news.example/1\n   上调"
    path, auth, body = site.seen[-1]
    assert path == "/search" and auth == "Bearer test-key"
    assert body == {"query": "油价", "max_results": 4, "search_depth": "basic", "time_range": "day"}
    bad = W.tavily_search("test-key", f"http://127.0.0.1:{site.port}/denied")
    with pytest.raises(RuntimeError, match="key was refused") as info:
        bad("x", 3, "")
    assert "test-key" not in str(info.value)


# ------------------------------------------------------------------ extra tools
def test_extra_tools_come_last_and_never_raise(demo):
    def explode(args):
        raise RuntimeError("topic service down")
    extra = [AT.Tool("hot_topics", "Today's hot topics.", {"type": "object", "properties": {}}, lambda a: "a, b"),
             AT.Tool("pick_topic", "Pick one.", {"type": "object", "properties": {}}, explode)]
    box = AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": "none"}, extra=extra)
    assert [t.name for t in box][-2:] == ["hot_topics", "pick_topic"]
    assert call(box, "hot_topics") == AT.ToolResult("a, b")
    r = call(box, "pick_topic")
    assert r.error and "topic service down" in r.text
    with pytest.raises(ValueError, match="two tools"):
        AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": "none"},
                   extra=[AT.Tool("read_file", "dup", {"type": "object"}, lambda a: "")])
    with pytest.raises(ValueError, match="letters"):
        AT.toolbox(demo.project, demo.ws, demo.scope, web={"search": "none"},
                   extra=[AT.Tool("bad name", "x", {"type": "object"}, lambda a: "")])
