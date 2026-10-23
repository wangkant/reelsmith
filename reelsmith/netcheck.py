"""Which addresses the platform fetches on the agent's behalf: http(s) to hosts whose every address is public.

public_url(url) checks one URL before a request (import_asset runs it on the address and on every redirect hop).
GuardProxy applies the same rule to a browser: capture points the browser at it, so every connection a page opens
(redirect hops, frames, workers, websockets) is checked, which request interception alone cannot promise. A proxy the
owner uses for outbound traffic (e.g. http://127.0.0.1:3128) stays allowed: the targets are what is checked.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import threading
import urllib.parse
import urllib.request
from typing import Callable, Iterable
from urllib.parse import urlsplit

Resolver = Callable[[str, int], list]
# WHATWG reads "2130706433", "0x7f.1" or "127.1" as IPv4; the OS resolver may not, so they are refused outright
_NUMERIC_HOST = re.compile(r"(0x[0-9a-f]*|[0-9]+)(\.(0x[0-9a-f]*|[0-9]+))*\.?")
_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
HEAD_MAX = 64 * 1024
CONNECT_TIMEOUT_S = 15
IDLE_TIMEOUT_S = 120
PUBLIC_ONLY = "only public web addresses can be fetched"
DOH_URL = "https://dns.google/resolve"
DOH_TIMEOUT_S = 6


def system_resolve(host: str, port: int) -> list[str]:
    """Every address the OS resolver gives for host (A and AAAA)."""
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def open_connection(address: tuple[str, int], timeout: float):
    """A TCP connection (GuardProxy's way out; tests replace it)."""
    return socket.create_connection(address, timeout=timeout)


def address_problem(addr: str) -> str:
    """'' for an address on the public internet, else what kind of address it is."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return "not an IP address"
    if ip.version == 6 and ip in _NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    elif ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in _FAKE_IP:
        return "a proxy's fake-ip address (turn off fake-ip DNS so real addresses can be checked)"
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return "a local or private network address"
    return ""


def check_host(host: str, port: int, resolve: Resolver | None = None,
               trusted: Iterable[str] = ()) -> tuple[str, str, list[str]]:
    """(verdict, why, addresses): verdict "" with every address of a public host; "local" for a local or private
    host; "unresolved" when it has no address. `trusted` hosts skip the check (tests serve a local page under such a
    name)."""
    host = str(host or "").strip().strip("[]").rstrip(".").lower()
    if not host:
        return "local", "the address has no host", []
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")      # what browsers and resolvers send
        except UnicodeError:
            return "unresolved", f"{host} is not a valid host name", []
    resolver = resolve or system_resolve
    if host in {str(t).lower() for t in trusted}:
        try:
            return "", "", list(dict.fromkeys(resolver(host, port)))
        except (OSError, UnicodeError) as exc:
            return "unresolved", f"{host} does not resolve ({exc})", []
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        why = address_problem(host)
        return ("local", f"{host} is {why}", []) if why else ("", "", [host])
    if _NUMERIC_HOST.fullmatch(host):
        return "local", f"{host} is a numeric host: write it as a plain dotted IPv4 address", []
    if host == "localhost" or host.endswith(".localhost"):
        return "local", f"{host} is this machine", []
    try:
        addrs = list(dict.fromkeys(resolver(host, port)))
    except (OSError, UnicodeError) as exc:
        return "unresolved", f"{host} does not resolve ({type(exc).__name__}): check the address", []
    if not addrs:
        return "unresolved", f"{host} has no addresses", []
    for addr in addrs:
        why = address_problem(addr)
        if why:
            return "local", f"{host} resolves to {addr}, {why}", []
    return "", "", addrs


def host_problem(host: str, port: int, resolve: Resolver | None = None,
                 trusted: Iterable[str] = ()) -> tuple[str, list[str]]:
    """('', addresses) when host resolves only to public addresses; (why, []) otherwise."""
    _, why, addrs = check_host(host, port, resolve, trusted)
    return why, addrs


def doh_resolver(proxy: str, fallback: Resolver | None = None, opener=None) -> Resolver:
    """A resolver that asks DNS-over-HTTPS through `proxy`. Traffic sent through a proxy reaches whatever the proxy
    resolves, and the local resolver may be poisoned (a public name answered with a reserved address such as
    2001::1), so the check must see real answers. Falls back to `fallback` (the OS resolver) once DoH fails."""
    open_ = opener or urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})).open
    broken = threading.Event()

    def resolve(host: str, port: int) -> list[str]:
        if not broken.is_set():
            try:
                addrs = []
                for rtype in (1, 28):           # A, AAAA
                    query = urllib.parse.urlencode({"name": host, "type": rtype})
                    req = urllib.request.Request(f"{DOH_URL}?{query}", headers={"Accept": "application/dns-json"})
                    with open_(req, timeout=DOH_TIMEOUT_S) as resp:
                        data = json.loads(resp.read())
                    if data.get("Status") not in (0, 3):    # NOERROR, NXDOMAIN
                        raise OSError(f"DoH answered status {data.get('Status')}")
                    addrs += [str(a.get("data")) for a in data.get("Answer") or [] if a.get("type") == rtype]
            except (OSError, ValueError, AttributeError):
                broken.set()
            else:
                if not addrs:
                    raise OSError(f"{host} has no A or AAAA record")
                return addrs
        return (fallback or system_resolve)(host, port)
    return resolve


def env_resolver(url: str) -> Resolver | None:
    """The resolver matching how urllib will send `url`: DoH through the environment's proxy when it applies, else
    None (the OS resolver)."""
    parts = urlsplit(str(url or ""))
    proxy = urllib.request.getproxies().get(parts.scheme.lower())
    if not proxy or not parts.hostname or urllib.request.proxy_bypass(parts.hostname):
        return None
    return doh_resolver(proxy)


def public_url(url, resolve: Resolver | None = None, trusted: Iterable[str] = ()) -> str:
    """'' when url is http(s), carries no credentials and its host resolves only to public addresses; else why not,
    in words fit for the agent."""
    u = str(url or "").strip()
    try:
        parts = urlsplit(u)
        port = parts.port
    except ValueError:
        return f"not a valid web address: {u[:120]}"
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return f"only http(s) addresses can be fetched: {u[:120]}"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return f"web addresses with a user name or password are refused: {u[:120]}"
    if not parts.hostname:
        return f"the address has no host: {u[:120]}"
    why, _ = host_problem(parts.hostname, port or (443 if scheme == "https" else 80), resolve, trusted)
    return f"{why}; {PUBLIC_ONLY}" if why else ""


# ------------------------------------------------------------------ the browser's proxy
def _read_head(sock) -> tuple[bytes | None, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk or len(buf) + len(chunk) > HEAD_MAX:
            return None, b""
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def _split_hostport(target: str, default: int) -> tuple[str, int]:
    parts = urlsplit("//" + target)
    return parts.hostname or "", parts.port or default


def proxy_address(url: str) -> tuple[str, int]:
    """(host, port) of an http:// proxy; ValueError for anything GuardProxy cannot chain to."""
    parts = urlsplit(url if "//" in url else "//" + url)
    if parts.scheme.lower() not in ("", "http") or not parts.hostname:
        raise ValueError(f"the outbound proxy must be an http:// proxy that takes CONNECT (got {url})")
    return parts.hostname, parts.port or 80


def _close(sock) -> None:
    try:
        sock.close()
    except OSError:
        pass


def _pipe(a, b) -> None:
    def copy(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    back = threading.Thread(target=copy, args=(b, a), daemon=True)
    back.start()
    copy(a, b)
    back.join(IDLE_TIMEOUT_S)


def _answer(code: int, reason: str, text: str = "") -> bytes:
    body = text.encode("utf-8")
    return (f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n").encode("latin-1") + body


_HOP_HEADERS = {"proxy-connection", "proxy-authorization", "connection", "keep-alive"}


class GuardProxy:
    """A forward proxy on 127.0.0.1 that connects to public hosts only, directly or through `upstream`.

    Direct connections go to the addresses that were checked, so a host cannot re-resolve to a private address in
    between. Through an upstream, names are checked with DNS-over-HTTPS sent through it (doh_resolver) and the
    upstream gets the name, so its own routing rules still apply. `refused` lists local or private targets and
    `unreachable` the rest that failed ("host: why"); `upstream_failed` is set when the upstream proxy itself could
    not be reached (the caller may try again without it)."""

    def __init__(self, upstream: str | None = None, resolve: Resolver | None = None, trusted: Iterable[str] = (),
                 connect=None):
        self.upstream = proxy_address(upstream) if upstream else None
        self.resolve = resolve or (doh_resolver(upstream) if upstream else None)
        self.trusted = frozenset(str(t).lower() for t in trusted)
        self._connect = connect or (lambda address, timeout: open_connection(address, timeout))
        self.refused: list[str] = []
        self.unreachable: list[str] = []
        self.upstream_failed = False
        self._checked: dict[tuple[str, int], tuple[str, str, list[str]]] = {}
        self._lock = threading.Lock()
        self._socks: set = set()
        self._closed = False
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(128)
        self.address = f"http://127.0.0.1:{self._server.getsockname()[1]}"
        threading.Thread(target=self._serve, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._closed = True
        _close(self._server)
        with self._lock:
            socks, self._socks = list(self._socks), set()
        for s in socks:
            _close(s)

    def _track(self, sock, add: bool = True) -> None:
        with self._lock:
            (self._socks.add if add else self._socks.discard)(sock)

    def _note(self, rows: list[str], row: str) -> None:
        with self._lock:
            if row not in rows:
                rows.append(row)

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self._track(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def check(self, host: str, port: int) -> tuple[str, str, list[str]]:
        key = (host.lower().rstrip("."), port)
        with self._lock:
            hit = self._checked.get(key)
        if hit is None:
            hit = check_host(key[0], port, self.resolve, self.trusted)
            with self._lock:
                self._checked[key] = hit
        return hit

    def _open(self, host: str, port: int):
        """(socket, bytes the far side already sent) to host:port, or (None, answer for the browser)."""
        verdict, why, addrs = self.check(host, port)
        if verdict == "unresolved":
            self._note(self.unreachable, why)
            return None, _answer(502, "Bad Gateway", why)
        if verdict:
            self._note(self.refused, why)
            return None, _answer(403, "Forbidden", f"refused: {why}")
        try:
            if self.upstream:
                return self._via_upstream(host, port)
            last: OSError = OSError("no address")
            for addr in sorted(addrs, key=lambda a: ":" in a):     # IPv4 first: IPv6 routes are often missing
                try:
                    return self._connect((addr, port), timeout=CONNECT_TIMEOUT_S), b""
                except OSError as exc:
                    last = exc
            raise last
        except OSError as exc:
            self._note(self.unreachable, f"{host}: {exc}")
            return None, _answer(502, "Bad Gateway", f"cannot reach {host}: {exc}")

    def _via_upstream(self, host: str, port: int):
        try:
            sock = self._connect(self.upstream, timeout=CONNECT_TIMEOUT_S)
        except OSError:
            self.upstream_failed = True
            raise
        self._track(sock)
        target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        try:
            sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode("utf-8"))
            head, rest = _read_head(sock)
        except OSError:
            _close(sock)
            raise
        status = head.split(b" ", 2)[1:2] if head else []
        if status != [b"200"]:
            _close(sock)
            said = status[0].decode("latin-1") if status else "nothing"
            raise OSError(f"the outbound proxy answered {said}")
        return sock, rest

    def _handle(self, conn) -> None:
        remote = None
        try:
            conn.settimeout(IDLE_TIMEOUT_S)
            head, rest = _read_head(conn)
            if head is None:
                return
            lines = head.decode("latin-1").split("\r\n")
            method, target = (lines[0].split(" ") + ["", ""])[:2]
            if method.upper() == "CONNECT":
                host, port = _split_hostport(target, 443)
                remote, early = self._open(host, port)
                if remote is None:
                    conn.sendall(early)
                    return
                self._track(remote)
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n" + early)
            else:
                parts = urlsplit(target)
                if parts.scheme.lower() != "http" or not parts.hostname:
                    conn.sendall(_answer(400, "Bad Request", "absolute http:// address expected"))
                    return
                remote, early = self._open(parts.hostname, parts.port or 80)
                if remote is None:
                    conn.sendall(early)
                    return
                self._track(remote)
                # one request per connection: a reused connection must not reach a host that was never checked
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                keep = [h for h in lines[1:] if h and h.split(":", 1)[0].strip().lower() not in _HOP_HEADERS]
                out = "\r\n".join([f"{method} {path} HTTP/1.1", *keep, "Connection: close"]) + "\r\n\r\n"
                if early:
                    conn.sendall(early)
                remote.sendall(out.encode("latin-1") + rest)
                rest = b""
            if rest:
                remote.sendall(rest)
            remote.settimeout(IDLE_TIMEOUT_S)
            _pipe(conn, remote)
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            for s in (conn, remote):
                if s is not None:
                    _close(s)
                    self._track(s, add=False)
