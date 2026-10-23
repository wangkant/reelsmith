"""netcheck, offline: fake resolvers, and a GuardProxy driven over real local sockets with fake ways out."""
import io
import json
import socket
import threading
import urllib.parse

import pytest

from reelsmith import netcheck as N

PUBLIC = "93.184.216.34"
ZONE = {"example.com": [PUBLIC, "2606:2800:220:1:248:1893:25c8:1946"], "localtest.me": ["127.0.0.1", "::1"],
        "127.0.0.1.nip.io": ["127.0.0.1"], "169.254.169.254.nip.io": ["169.254.169.254"],
        "mixed.example": [PUBLIC, "10.0.0.7"], "fakeip.example": ["198.18.0.42"],
        "poisoned.example": ["2001::1"], "mapped.example": ["::ffff:192.168.1.1"]}


def fake_resolve(host, port):
    if host not in ZONE:
        raise socket.gaierror(11001, "getaddrinfo failed")
    return list(ZONE[host])


@pytest.mark.parametrize("url", ["https://example.com/a", "http://example.com:8080/x?y=1", "https://93.184.216.34/",
                                 "HTTPS://EXAMPLE.COM./a"])
def test_public_urls_pass(url):
    assert N.public_url(url, fake_resolve) == ""


@pytest.mark.parametrize("url, says", [
    ("http://localtest.me/x.png", "resolves to 127.0.0.1"),
    ("http://127.0.0.1.nip.io/x.png", "local or private"),
    ("http://169.254.169.254.nip.io/latest", "169.254.169.254"),
    ("http://mixed.example/", "10.0.0.7"),                     # one private address is enough
    ("http://fakeip.example/", "fake-ip"),
    ("http://poisoned.example/", "2001::1"),
    ("http://mapped.example/", "local or private"),
    ("http://127.0.0.1:8000/", "127.0.0.1 is a local"),
    ("http://[::1]/", "::1 is a local"),
    ("http://[::ffff:7f00:1]/", "local or private"),
    ("http://[64:ff9b::a00:1]/", "local or private"),          # NAT64 of 10.0.0.1
    ("http://10.1.2.3/", "local or private"),
    ("http://100.64.0.1/", "local or private"),                # carrier-grade NAT
    ("http://224.0.0.1/", "local or private"),
    ("http://0.0.0.0/", "local or private"),
    ("http://2130706433/", "numeric host"),
    ("http://0x7f.1/", "numeric host"),
    ("http://127.1/", "numeric host"),
    ("http://localhost:3000/", "this machine"),
    ("http://app.localhost/", "this machine"),
    ("http://user:pw@example.com/", "user name or password"),
    ("http://example.com@localtest.me/", "user name or password"),
    ("ftp://example.com/a", "only http(s)"),
    ("file:///C:/Windows/win.ini", "only http(s)"),
    ("http:///nohost", "no host"),
    ("http://example.com:99999/", "not a valid"),
    ("http://nowhere.example/", "does not resolve"),
])
def test_local_private_and_odd_urls_are_refused(url, says):
    why = N.public_url(url, fake_resolve)
    assert says in why, why
    assert N.PUBLIC_ONLY in why or "only http(s)" in why or "not a valid" in why or "user name" in why \
        or "no host" in why


def test_check_host_tells_unresolved_from_local_and_trusts_named_hosts():
    assert N.check_host("nowhere.example", 443, fake_resolve)[0] == "unresolved"
    assert N.check_host("localtest.me", 443, fake_resolve)[0] == "local"
    assert N.check_host("example.com", 443, fake_resolve) == ("", "", ZONE["example.com"])
    assert N.check_host("localtest.me", 443, fake_resolve, trusted=["LocalTest.me"])[0] == ""


class FakeDoH:
    """urlopen stand-in for dns.google's JSON API."""

    def __init__(self, answers=None, fail=False):
        self.answers, self.fail, self.asked = answers or {}, fail, []

    def __call__(self, req, timeout=None):
        if self.fail:
            raise OSError("timed out")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        self.asked.append((q["name"], int(q["type"])))
        rows = [{"type": int(q["type"]), "data": a} for a in self.answers.get(q["name"], [])
                if (":" in a) == (int(q["type"]) == 28)]
        body = {"Status": 0 if q["name"] in self.answers else 3, "Answer": rows}
        return io.BytesIO(json.dumps(body).encode())


def test_doh_resolver_asks_through_the_proxy_and_falls_back_once_it_fails():
    doh = FakeDoH({"zh.wikipedia.org": ["103.102.166.224", "2001:df2:e500:ed1a::1"]})
    resolve = N.doh_resolver("http://127.0.0.1:3128", fallback=lambda h, p: pytest.fail("fell back"), opener=doh)
    assert resolve("zh.wikipedia.org", 443) == ["103.102.166.224", "2001:df2:e500:ed1a::1"]
    assert doh.asked == [("zh.wikipedia.org", 1), ("zh.wikipedia.org", 28)]
    with pytest.raises(OSError, match="no A or AAAA"):
        resolve("nxdomain.example", 443)
    # the poisoned local answer (2001::1) is not what the check sees when the traffic goes through the proxy
    assert N.check_host("zh.wikipedia.org", 443, resolve)[0] == ""
    seen = []
    down = N.doh_resolver("http://127.0.0.1:3128", fallback=lambda h, p: seen.append(h) or [PUBLIC],
                          opener=FakeDoH(fail=True))
    assert down("a.example", 443) == [PUBLIC] and down("b.example", 443) == [PUBLIC] and seen == ["a.example",
                                                                                                 "b.example"]


def test_env_resolver_follows_the_environment_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "ALL_PROXY",
                 "all_proxy"):
        monkeypatch.delenv(name, raising=False)          # (Windows names ignore case: clear first, then set)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    assert callable(N.env_resolver("https://example.com/a.png"))
    assert N.env_resolver("http://example.com/a.png") is None          # no http proxy set
    assert N.env_resolver("https://127.0.0.1/a.png") is None           # bypassed


# ------------------------------------------------------------------ GuardProxy
class WayOut:
    """GuardProxy's connect seam: records where it went and answers like a tiny web server or an upstream proxy."""

    def __init__(self, upstream=None, upstream_down=False, refuse=()):
        self.upstream, self.upstream_down, self.refuse = upstream, upstream_down, set(refuse)
        self.dialed, self.received, self._keep = [], [], []

    def __call__(self, address, timeout=None):
        address = (str(address[0]), int(address[1]))
        self.dialed.append(address)
        if address in self.refuse or (self.upstream_down and address == self.upstream):
            raise ConnectionRefusedError(10061, "refused")
        mine, theirs = socket.socketpair()
        self._keep.append(theirs)
        threading.Thread(target=self._serve, args=(theirs, address == self.upstream), daemon=True).start()
        return mine

    def _serve(self, sock, is_upstream):
        try:
            if is_upstream:
                head = b""
                while b"\r\n\r\n" not in head:
                    head += sock.recv(4096)
                self.received.append(head.split(b"\r\n")[0])
                sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            data = sock.recv(65536)
            self.received.append(data)
            sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def ask(guard, head: bytes, then: bytes = b"") -> bytes:
    host, port = guard.address.rsplit("//", 1)[1].split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s:
        s.sendall(head)
        first = s.recv(65536)
        if then and first.startswith(b"HTTP/1.1 200 Connection"):
            s.sendall(then)
            rest = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                rest += chunk
            return first + rest
        return first


def test_guard_tunnels_to_the_checked_address_of_a_public_host():
    out = WayOut()
    with N.GuardProxy(resolve=fake_resolve, connect=out) as guard:
        got = ask(guard, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n", b"hello")
    assert got.startswith(b"HTTP/1.1 200 Connection established") and got.endswith(b"ok")
    assert out.dialed == [(PUBLIC, 443)] and out.received == [b"hello"]       # pinned to the address it checked
    assert guard.refused == [] and guard.unreachable == []


def test_guard_refuses_local_targets_and_counts_unresolved_ones_apart():
    out = WayOut()
    with N.GuardProxy(resolve=fake_resolve, connect=out) as guard:
        assert ask(guard, b"CONNECT localtest.me:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 403")
        assert ask(guard, b"CONNECT 127.0.0.1:8080 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 403")
        assert ask(guard, b"GET http://169.254.169.254.nip.io/latest HTTP/1.1\r\nHost: x\r\n\r\n") \
            .startswith(b"HTTP/1.1 403")
        assert ask(guard, b"CONNECT nowhere.example:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 502")
    assert out.dialed == []
    assert len(guard.refused) == 3 and "localtest.me resolves to 127.0.0.1" in guard.refused[0]
    assert guard.unreachable and "nowhere.example does not resolve" in guard.unreachable[0]


def test_guard_sends_plain_http_one_request_per_connection_in_origin_form():
    out = WayOut()
    with N.GuardProxy(resolve=fake_resolve, connect=out) as guard:
        got = ask(guard, b"GET http://example.com/a?b=1 HTTP/1.1\r\nHost: example.com\r\nProxy-Connection: keep-alive"
                         b"\r\nAccept: */*\r\n\r\n")
    assert got.startswith(b"HTTP/1.1 200 OK")
    sent = out.received[0]
    assert sent.startswith(b"GET /a?b=1 HTTP/1.1\r\n") and b"Proxy-Connection" not in sent
    assert b"Connection: close" in sent and b"Accept: */*" in sent


def test_guard_goes_through_the_upstream_by_name_and_says_when_it_is_down():
    up = ("127.0.0.1", 3128)
    out = WayOut(upstream=up)
    with N.GuardProxy("http://127.0.0.1:3128", resolve=fake_resolve, connect=out) as guard:
        got = ask(guard, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n", b"tls")
        assert ask(guard, b"CONNECT localtest.me:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 403")
    assert got.startswith(b"HTTP/1.1 200") and out.dialed == [up]              # the local target never left
    assert out.received[0] == b"CONNECT example.com:443 HTTP/1.1" and out.received[1] == b"tls"
    down = WayOut(upstream=up, upstream_down=True)
    with N.GuardProxy("http://127.0.0.1:3128", resolve=fake_resolve, connect=down) as guard:
        assert ask(guard, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 502")
    assert guard.upstream_failed and guard.unreachable


def test_proxy_address_takes_http_proxies_only():
    assert N.proxy_address("http://127.0.0.1:3128") == ("127.0.0.1", 3128)
    assert N.proxy_address("127.0.0.1:3128") == ("127.0.0.1", 3128)
    for bad in ("socks5://127.0.0.1:1080", "https://p.example:443", "http://"):
        with pytest.raises(ValueError, match="http:// proxy"):
            N.proxy_address(bad)


def test_guard_checks_through_doh_when_it_has_an_upstream(monkeypatch):
    made = []
    monkeypatch.setattr(N, "doh_resolver", lambda proxy, **k: made.append(proxy) or fake_resolve)
    with N.GuardProxy("http://127.0.0.1:3128", connect=WayOut()) as guard:
        assert guard.resolve is fake_resolve
    assert made == ["http://127.0.0.1:3128"]
    with N.GuardProxy(connect=WayOut()) as guard:
        assert guard.resolve is None                                           # direct: the OS resolver


def test_guard_closes_what_it_opened():
    out = WayOut()
    guard = N.GuardProxy(resolve=fake_resolve, connect=out)
    host, port = guard.address.rsplit("//", 1)[1].split(":")
    s = socket.create_connection((host, int(port)), timeout=5)
    s.sendall(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    assert s.recv(100).startswith(b"HTTP/1.1 200")
    guard.close()
    s.settimeout(5)
    assert s.recv(100) == b""                                                  # the tunnel was torn down
    s.close()
    with pytest.raises(OSError):
        socket.create_connection((host, int(port)), timeout=2).close()
