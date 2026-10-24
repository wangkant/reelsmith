"""The api engine's web tools: web_fetch reads a public page as text, web_search asks a search backend.

web_fetch holds to netcheck's rules, the ones capture uses: the URL is checked first, then every connection (each
redirect hop included) goes through a netcheck.GuardProxy, which reaches public addresses only and connects to the
addresses it checked. web_search is pluggable: the ddgs package (no key), Tavily (TAVILY_API_KEY) or a callable.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Callable

from .. import guard, netcheck

FETCH_TIMEOUT_S = 30
SEARCH_TIMEOUT_S = 20
MAX_BYTES = 5 << 20
DEFAULT_CHARS = 20000
MIN_CHARS = 500
MAX_CHARS = 200000
TAVILY_URL = "https://api.tavily.com/search"
RECENT = ("day", "week", "month", "year")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")
ACCEPT = "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.5"
_TEXT_TYPES = ("application/json", "application/xml", "application/rss+xml", "application/atom+xml",
               "application/ld+json", "application/javascript")
_HTML_TYPES = ("text/html", "application/xhtml+xml")
_CJK = re.compile(r"[㐀-鿿]")

Search = Callable[[str, int, str], list]


class FetchError(Exception):
    """A fetch that cannot go on; the message is for the agent."""


# ------------------------------------------------------------------ html to text
class _Text(HTMLParser):
    """Readable text from HTML: no scripts or styles, a line per block, links as [text](url)."""

    SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "object", "canvas", "select"}
    BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "ul", "ol", "table",
             "tr", "blockquote", "pre", "figure", "figcaption", "form", "br", "hr", "dl", "dt", "dd", "address",
             "details", "summary", "tbody", "thead"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out: list[str] = []
        self.title: list[str] = []
        self.skip = 0
        self.in_title = False
        self.links: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag == "title":
            self.in_title = True
        elif tag == "li":
            self.out.append("\n- ")
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n" + "#" * int(tag[1]) + " ")
        elif tag in ("td", "th"):
            self.out.append(" ")
        elif tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.out.append(f" [image: {alt}] ")
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and not self.skip:
            self.links.append((len(self.out), dict(attrs).get("href") or ""))

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag == "title":
            self.in_title = False
        elif tag == "a" and self.links:
            start, href = self.links.pop()
            text = re.sub(r"\s+", " ", "".join(self.out[start:])).strip()
            url = urllib.parse.urljoin(self.base, href.strip()) if href.strip() else ""
            if text and url.startswith(("http://", "https://")) and len(text) >= 2:
                self.out[start:] = [f"[{text}]({url})"]
        elif tag in self.BLOCK or re.fullmatch(r"h[1-6]", tag) or tag == "li":
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.out.append(re.sub(r"\s+", " ", data))

    def text(self) -> tuple[str, str]:
        title = re.sub(r"\s+", " ", "".join(self.title)).strip()
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(self.out).split("\n")]
        body, blank = [], False
        for line in lines:
            if line:
                body.append(line)
                blank = False
            elif not blank and body:
                body.append("")
                blank = True
        return title, "\n".join(body).strip()


def html_text(html: str, base: str = "") -> tuple[str, str]:
    """(title, readable text) of an HTML document."""
    parser = _Text(base)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken page still gives what was parsed
        pass
    return parser.text()


def _decode(raw: bytes, charset: str | None, html: bool) -> str:
    candidates = [charset] if charset else []
    if html and not charset:
        m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_\-]+)", raw[:4096], re.I)
        if m:
            candidates.append(m.group(1).decode("ascii", "ignore"))
    for enc in [*candidates, "utf-8", "gb18030"]:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ fetching
class _ThroughGuard(urllib.request.HTTPRedirectHandler):
    """Every redirect hop is checked and sent through the guard proxy, like the first request."""

    def __init__(self, hostport: str):
        super().__init__()
        self.hostport = hostport

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = guard.check_url(newurl)
        if why:
            raise FetchError(f"the page redirected to {newurl[:200]}, which is refused: {why}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.set_proxy(self.hostport, "http")
        return new


def default_proxy() -> str | None:
    """The outbound proxy urllib would use (REELSMITH_PROXY first), when it is an http:// proxy GuardProxy chains to."""
    found = os.environ.get("REELSMITH_PROXY") or ""
    if not found:
        proxies = urllib.request.getproxies()
        found = proxies.get("https") or proxies.get("http") or ""
    if not found:
        return None
    try:
        netcheck.proxy_address(found)
    except ValueError:
        return None
    return found


def _open(url: str, upstream: str | None, resolve, trusted, connect, timeout: float):
    """(status, headers, body bytes, final url) through a GuardProxy; FetchError when it cannot be fetched."""
    while True:
        with netcheck.GuardProxy(upstream, resolve=resolve, trusted=trusted, connect=connect) as gp:
            hostport = gp.address.split("//", 1)[1]
            # an empty ProxyHandler: no environment or registry proxy may route around the guard
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _ThroughGuard(hostport))
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": ACCEPT,
                                                       "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            req.set_proxy(hostport, "http")
            try:
                with opener.open(req, timeout=timeout) as resp:
                    return resp.status, resp.headers, resp.read(MAX_BYTES + 1), resp.geturl()
            except urllib.error.HTTPError as exc:
                if upstream and gp.upstream_failed:
                    upstream = None                 # the outbound proxy is down: go direct
                    continue
                if gp.refused:
                    raise FetchError(f"the page led to an address that is refused ({gp.refused[-1]}); "
                                     f"{netcheck.PUBLIC_ONLY}") from None
                if gp.unreachable:
                    raise FetchError(f"cannot reach {gp.unreachable[-1]}") from None
                if 300 <= exc.code < 400:       # urllib refused the hop itself (file:, data:, a loop)
                    where = str(exc.geturl() or "")
                    why = guard.check_url(where)
                    if why:
                        raise FetchError(f"the page redirected to {where[:200]}, which is refused: {why}") from None
                    raise FetchError(f"{url[:200]} redirects too many times or in a loop") from None
                try:
                    body = exc.read(MAX_BYTES + 1)
                except Exception:  # noqa: BLE001
                    body = b""
                return exc.code, exc.headers, body, exc.geturl() or url
            except FetchError:
                raise
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if upstream and gp.upstream_failed:
                    upstream = None
                    continue
                if gp.unreachable:
                    raise FetchError(f"cannot reach {gp.unreachable[-1]}") from None
                reason = getattr(exc, "reason", exc)
                raise FetchError(f"cannot fetch {url[:200]}: {reason}") from None


def fetch(url: str, max_chars: int = DEFAULT_CHARS, *, proxy: str | None = None, resolve=None, trusted=(),
          connect=None, timeout: float = FETCH_TIMEOUT_S) -> tuple[str, bool]:
    """(text, is_error): a public http(s) page as readable text, cut at max_chars. proxy None: the environment's
    proxy, "" direct. resolve, trusted and connect are netcheck's hooks (tests)."""
    url = str(url or "").strip()
    why = guard.check_url(url)
    if why:
        return why, True
    upstream = default_proxy() if proxy is None else (proxy or None)
    check_resolve = resolve or (netcheck.doh_resolver(upstream) if upstream else None)
    why = netcheck.public_url(url, check_resolve, trusted)
    if why:
        return f"cannot fetch {url[:200]}: {why}", True
    try:
        limit = int(max_chars)
    except (TypeError, ValueError):
        limit = DEFAULT_CHARS
    limit = min(MAX_CHARS, max(MIN_CHARS, limit))
    try:
        status, headers, raw, final = _open(url, upstream, resolve, trusted, connect, timeout)
    except FetchError as exc:
        return str(exc), True
    ctype = str(headers.get("Content-Type") or "").lower() if headers else ""
    mime = ctype.split(";")[0].strip()
    m = re.search(r"charset=[\"']?([A-Za-z0-9_\-]+)", ctype)
    charset = m.group(1) if m else None
    is_html = mime in _HTML_TYPES or (not mime and raw.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")))
    if not (is_html or mime.startswith("text/") or mime in _TEXT_TYPES or mime.endswith(("+json", "+xml"))):
        hint = (" To use a picture or a clip from the web, import_asset it; to show a page, capture it."
                if mime.startswith(("image/", "video/", "audio/")) else "")
        return f"{final} serves {mime or 'an unknown type'}, not a text page.{hint}", True
    cut_bytes = len(raw) > MAX_BYTES
    text = _decode(raw[:MAX_BYTES], charset, is_html)
    title = ""
    if is_html:
        title, text = html_text(text, final)
    head = [f"{title}" if title else "", f"URL: {final}"]
    if status >= 400:
        head.append(f"HTTP {status}: the server refused or has no such page")
    total = len(text)
    if total > limit:
        text = text[:limit] + f"\n\n[cut at {limit} of {total} characters; pass a larger max_chars for more]"
    elif cut_bytes:
        text += f"\n\n[the page is over {MAX_BYTES >> 20} MB; only its start was read]"
    body = "\n".join(h for h in head if h) + "\n\n" + (text or "(no readable text on this page)")
    return body, status >= 400


# ------------------------------------------------------------------ searching
def _region(query: str, region: str | None) -> str:
    return region or ("cn-zh" if _CJK.search(query) else "us-en")


def ddgs_search(proxy: str | None = None, region: str | None = None, timeout: int = SEARCH_TIMEOUT_S) -> Search:
    """Search with the ddgs metasearch package (no key)."""
    def search(query: str, n: int, recent: str = "") -> list[dict]:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException
        kwargs = {"region": _region(query, region), "max_results": n}
        if recent:
            kwargs["timelimit"] = recent[0]           # d, w, m, y
        try:
            rows = DDGS(proxy=proxy, timeout=timeout).text(query, **kwargs)
        except DDGSException as exc:
            if "no results" in str(exc).lower():
                return []
            raise
        return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in rows or []]
    return search


def tavily_search(key: str, url: str = TAVILY_URL, timeout: int = SEARCH_TIMEOUT_S) -> Search:
    """Search with the Tavily API."""
    def search(query: str, n: int, recent: str = "") -> list[dict]:
        body = {"query": query, "max_results": n, "search_depth": "basic"}
        if recent:
            body["time_range"] = recent
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.build_opener().open(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            what = {401: "the Tavily key was refused", 429: "Tavily's rate limit was hit",
                    432: "the Tavily plan's credits are used up"}.get(exc.code, "Tavily refused the search")
            raise RuntimeError(f"{what} (HTTP {exc.code})") from None
        return [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")}
                for r in (data.get("results") or []) if isinstance(r, dict)]
    return search


def search_backend(web: dict, keys=None) -> tuple[Search | None, str]:
    """(search, '') for the backend web["search"] names, or (None, why web_search is left out).

    web["search"]: "auto" (default: ddgs when installed, else Tavily when a key is found), "ddgs", "tavily", None or
    "none" (off), or a callable search(query, n, recent) -> [{"title", "url", "snippet"}]."""
    choice = web.get("search", "auto")
    if callable(choice):
        return choice, ""
    if choice in (None, False, "", "none", "off"):
        return None, "web search is turned off (web.search)"
    choice = str(choice).lower()
    if choice not in ("auto", "ddgs", "tavily"):
        return None, f"unknown web search backend {choice!r}: use ddgs, tavily or none"
    reasons = []
    if choice in ("auto", "ddgs"):
        if importlib.util.find_spec("ddgs") is not None:
            proxy = web.get("proxy")
            return ddgs_search(default_proxy() if proxy is None else (proxy or None), web.get("region")), ""
        reasons.append("the ddgs package is not installed (pip install ddgs)")
    if choice in ("auto", "tavily"):
        key = web.get("tavily_key") or (keys.get("TAVILY_API_KEY") if keys is not None else None) \
            or os.environ.get("TAVILY_API_KEY")
        if key:
            return tavily_search(key, web.get("tavily_url") or TAVILY_URL), ""
        reasons.append("TAVILY_API_KEY is in neither the workspace .env nor the environment")
    return None, "web_search is left out: " + "; ".join(reasons)


def format_results(rows: list, n: int) -> str:
    lines = []
    for i, r in enumerate([r for r in rows if isinstance(r, dict)][:n], 1):
        title = re.sub(r"\s+", " ", str(r.get("title") or r.get("name") or "")).strip() or "(no title)"
        url = str(r.get("url") or r.get("href") or r.get("link") or "").strip()
        snippet = re.sub(r"\s+", " ", str(r.get("snippet") or r.get("body") or r.get("content") or "")).strip()
        if len(snippet) > 400:
            snippet = snippet[:399] + "…"
        lines.append(f"{i}. {title}\n   {url}" + (f"\n   {snippet}" if snippet else ""))
    return "\n".join(lines)
