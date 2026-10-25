"""reelsmith mcp --http: loopback by default, remote only with a bearer token; a real server lists tools and serves a
call."""
import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from reelsmith import cli, mcp_server

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "t0ken-for-tests-0123456789"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(port: int, **env) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "reelsmith.mcp_server", "--http", "--port", str(port)], cwd=ROOT,
                            env={**os.environ, "PYTHONUTF8": "1", **env}, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail("the server exited: " + proc.stderr.read().decode("utf-8", "replace")[-800:])
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.fail("the server did not start listening")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def test_loopback_and_remote_rules(tmp_path):
    for host in ("127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.2", "LOCALHOST", "0:0:0:0:0:0:0:1"):
        assert mcp_server.loopback(host) and mcp_server.check_http(host, False, "") == ""
    for host in ("0.0.0.0", "192.168.1.20", "example.com", "::"):
        assert not mcp_server.loopback(host)
        assert "not a loopback address" in mcp_server.check_http(host, False, TOKEN)
        assert "bearer token" in mcp_server.check_http(host, True, "short", root=str(tmp_path))
        assert "--root" in mcp_server.check_http(host, True, TOKEN)            # a remote caller needs a fence
        assert "--root" in mcp_server.check_http(host, True, TOKEN, root=str(tmp_path / "missing"))
        assert mcp_server.check_http(host, True, TOKEN, root=str(tmp_path)) == ""


def test_cli_refuses_before_serving(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    monkeypatch.setenv("REELSMITH_ROOT", "")
    monkeypatch.delenv("REELSMITH_ROOT")
    assert cli.main(["mcp", "--http", "--host", "0.0.0.0"]) == 2
    assert cli.main(["mcp", "--http", "--host", "0.0.0.0", "--allow-remote"]) == 2
    assert cli.main(["mcp", "--port", "9000"]) == 2                   # --port without --http
    monkeypatch.setenv(mcp_server.TOKEN_ENV, TOKEN)
    assert cli.main(["mcp", "--http", "--host", "0.0.0.0", "--allow-remote"]) == 2
    assert cli.main(["mcp", "--http", "--root", str(tmp_path / "missing")]) == 2
    err = capsys.readouterr().err
    assert "not a loopback address" in err and "bearer token" in err and "go with --http" in err
    assert "needs --root (or REELSMITH_ROOT)" in err and "is not a folder" in err


def test_a_remote_bind_is_fenced_and_warned(monkeypatch, capsys, tmp_path):
    import uvicorn
    served = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.append(kw))
    monkeypatch.setenv("REELSMITH_ROOT", "")                # recorded, so the value --root sets is undone
    monkeypatch.delenv("REELSMITH_ROOT")
    monkeypatch.setenv(mcp_server.TOKEN_ENV, TOKEN)
    assert cli.main(["mcp", "--http", "--host", "0.0.0.0", "--allow-remote", "--root", str(tmp_path)]) == 0
    assert served == [{"host": "0.0.0.0", "port": mcp_server.DEFAULT_PORT, "log_level": "warning"}]
    assert os.environ["REELSMITH_ROOT"] == str(tmp_path.resolve())
    assert "plain HTTP" in capsys.readouterr().err


@pytest.mark.parametrize("host,good", [("127.0.0.1", "127.0.0.1:8765"), ("127.0.0.2", "127.0.0.2:8765"),
                                       ("LOCALHOST", "localhost:8765"), ("0:0:0:0:0:0:0:1", "[::1]:8765")])
def test_every_loopback_spelling_checks_host_and_origin(host, good):
    from starlette.testclient import TestClient
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    accept = {"Accept": "application/json, text/event-stream"}
    with TestClient(mcp_server.http_app(host)) as c:
        evil = c.post("/mcp", json=init, headers={**accept, "Host": "evil.example:8765",
                                                   "Origin": "http://evil.example:8765"})
        foreign_page = c.post("/mcp", json=init, headers={**accept, "Host": good, "Origin": "http://evil.example"})
        ok = c.post("/mcp", json=init, headers={**accept, "Host": good, "Origin": f"http://{good}"})
    assert (evil.status_code, foreign_page.status_code, ok.status_code) == (421, 403, 200)


def test_bearer_wrapper():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    async def call(headers, kind="http"):
        sent = []

        async def send(msg):
            sent.append(msg)
        await mcp_server.BearerAuth(app, TOKEN)({"type": kind, "headers": headers}, None, send)
        return sent
    sent = asyncio.run(call([]))
    assert sent[0]["status"] == 401 and not seen
    assert asyncio.run(call([(b"authorization", b"Bearer wrong")]))[0]["status"] == 401
    assert asyncio.run(call([(b"authorization", f"Bearer {TOKEN}".encode())])) == [] and seen == ["http"]
    asyncio.run(call([], kind="lifespan"))
    assert seen == ["http", "lifespan"]                               # startup and shutdown pass through


def test_http_server_lists_tools_and_serves_a_call():
    port = free_port()
    proc = start(port)
    try:
        async def talk():
            async with Client(f"http://127.0.0.1:{port}/mcp") as c:
                return await c.list_tools(), await c.call_tool("manual", {})
        tools, result = asyncio.run(talk())
    finally:
        stop(proc)
    assert {"manual", "new_project", "edit", "preview", "render"} <= {t.name for t in tools.tools}
    assert not result.is_error and "reelsmith manual" in result.content[0].text
    assert proc.returncode is not None


def test_http_server_with_a_token():
    port = free_port()
    proc = start(port, REELSMITH_MCP_TOKEN=TOKEN)
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=10)
        assert caught.value.code == 401

        async def talk():
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {TOKEN}"})
            async with http, Client(streamable_http_client(url, http_client=http)) as c:
                return await c.list_tools()
        tools = asyncio.run(talk())
    finally:
        stop(proc)
    assert "render" in {t.name for t in tools.tools}
