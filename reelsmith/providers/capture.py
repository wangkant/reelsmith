"""capture: an evidence screenshot of a public web page at phone width, with the box of the sentence that proves it.

Playwright drives a Chromium browser (installed Microsoft Edge, else installed Google Chrome, else Playwright's own
Chromium) with a 430 CSS px layout viewport at 3x DPR. All of the browser's traffic goes through a
netcheck.GuardProxy, so neither the page nor its redirects, frames or scripts reach local or private addresses.
The page's fixed and sticky overlays are hidden, a text column wider than the phone is reflowed to it, the deepest
visible element holding the match is found, the match grows to its sentence (whole lines of the text column), the
crop widens to a readable block, and the box comes back in the PNG's own pixels.
"""
from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path

from .. import netcheck
from .config import (ProviderError, check_id, check_replaceable, context, header_size, read_project, register_asset,
                     rel, safe_tool)

VIEWPORT = {"width": 430, "height": 932}
DEVICE_SCALE = 3
TIMEOUT_MS = 30000
PAD_CSS = 14
MAX_MATCH_CHARS = 200
MAX_BOX_LINES = 4           # a longer sentence is boxed on the match's own lines
READABLE_PX = 40            # the house minimum for text on the 1080-wide canvas
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/141.0.0.0 Mobile Safari/537.36")
# WebRTC would otherwise open UDP around the proxy
LAUNCH_ARGS = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
# Playwright channels in order of preference; None is the Chromium that `playwright install chromium` downloads
CHANNELS = ("msedge", "chrome", None)
INSTALL_HINT = ("capture needs a Chromium browser: install Microsoft Edge or Google Chrome, or run "
                "`python -m playwright install chromium`")
_NO_BROWSER = re.compile(r"Executable doesn't exist|Chromium distribution '[^']*' is not (?:found|supported)")
_LOCK = threading.Lock()        # one browser at a time: stray headless browsers add up to gigabytes

FIND_JS = r"""
([match, pad, maxLines]) => {
  const norm = s => (s || "").normalize("NFKC").replace(/\s+/g, "").toLowerCase();
  const want = norm(match);
  const visible = el => {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  };
  for (const el of document.querySelectorAll("body *")) {
    const pos = getComputedStyle(el).position;
    if (pos === "fixed" || pos === "sticky") el.style.setProperty("display", "none", "important");
  }
  document.documentElement.style.setProperty("overflow", "auto", "important");
  if (document.body) document.body.style.setProperty("overflow", "auto", "important");
  const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "svg", "SVG", "HEAD", "IFRAME"]);
  const meta = sel => ((document.querySelector(sel) || {}).content || "").trim();
  const ldName = pick => {            // schema.org data: the WebSite's name, else the publisher's
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent);
        for (const x of [].concat(d && d["@graph"] ? d["@graph"] : d)) {
          const n = x && (pick === "site" ? x["@type"] === "WebSite" && x.name : x.publisher && x.publisher.name);
          if (typeof n === "string" && n.trim()) return n.trim();
        }
      } catch (e) {}
    }
    return "";
  };
  const titleName = () => {
    const parts = document.title.split(/\s*[|｜_–—]\s*|\s+-\s+|-(?=[^-]{2,16}$)/).map(s => s.trim()).filter(Boolean);
    const last = parts.length > 1 ? parts[parts.length - 1] : "";
    return last.length >= 2 && last.length <= 16 && !/^\d/.test(last) ? last : "";
  };
  const site = meta('meta[property="og:site_name"]') || meta('meta[name="sitename" i]') ||
    meta('meta[name="application-name" i]') || meta('meta[name="apple-mobile-web-app-title" i]') ||
    ldName("site") || titleName() || ldName("publisher") || location.hostname;
  let target = null;
  if (want) {
    const hits = [...document.querySelectorAll("body *")].filter(
      el => !skip.has(el.tagName) && norm(el.textContent).includes(want));
    const set = new Set(hits);
    target = hits.filter(el => ![...el.children].some(c => set.has(c))).find(visible) || null;
  } else {
    target = [...document.querySelectorAll("h1, h2, [class*=title]")].find(
      el => visible(el) && norm(el.innerText).length >= 6) || null;
  }
  if (!target) {
    return {found: false, title: document.title, site,
            heads: [...document.querySelectorAll("h1,h2,h3")].filter(visible).slice(0, 6)
                     .map(e => e.innerText.trim().slice(0, 60)),
            text: (document.body ? document.body.innerText : "").replace(/\s+/g, " ").slice(0, 400)};
  }
  const vw = document.documentElement.clientWidth || window.innerWidth;
  // a column laid out wider than the phone (fixed-width desktop layouts) is reflowed to it, ancestors included
  // (judged on the column itself: with overflow forced above, the document no longer reports its own width)
  window.scrollTo(0, window.scrollY);
  if (document.body) document.body.scrollLeft = 0;
  const wide = [];
  for (let e = target; e && e !== document.documentElement; e = e.parentElement) {
    const r = e.getBoundingClientRect();
    if (r.width > vw + 1 || r.right + window.scrollX > vw + 1 || r.left + window.scrollX < -1) wide.push(e);
  }
  const rules = [["width", "auto"], ["min-width", "0"], ["max-width", "100%"], ["margin-left", "0"],
                 ["margin-right", "0"], ["float", "none"], ["box-sizing", "border-box"]];
  for (const e of wide) {
    for (const [k, v] of rules) e.style.setProperty(k, v, "important");
    // column rules and sidebars painted as backgrounds of a wide layout land across the reflowed text
    if (e !== target) e.style.setProperty("background-image", "none", "important");
  }
  if (wide.length) {
    for (const e of [document.documentElement, document.body]) {
      if (e) { e.style.setProperty("min-width", "0", "important"); e.style.setProperty("width", "auto", "important"); }
    }
  }
  const fitted = wide.length > 0;
  target.scrollIntoView({block: "center"});
  let tb = target;                    // the text column: the nearest block-level element around the match
  while (tb.parentElement && tb !== document.body && /^(inline|contents)/.test(getComputedStyle(tb).display))
    tb = tb.parentElement;
  let mr = target.getBoundingClientRect();
  let fontPx = parseFloat(getComputedStyle(target).fontSize) || 0;
  let sentence = "", cut = false;
  if (want) {
    const units = [];
    const walker = document.createTreeWalker(tb, NodeFilter.SHOW_TEXT, {acceptNode: n =>
      n.parentElement && !skip.has(n.parentElement.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      for (let k = 0; k < n.data.length; k++) {
        const ch = n.data[k];
        if (/\s/.test(ch)) { if (units.length) units[units.length - 1].ws = true; continue; }
        units.push({n, k, s: ch.normalize("NFKC").toLowerCase(), ws: false});
      }
    }
    let flat = "";
    const starts = [];
    for (const u of units) { starts.push(flat.length); flat += u.s; }
    const unitAt = pos => {
      let lo = 0, hi = starts.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (starts[mid] <= pos) lo = mid; else hi = mid - 1; }
      return lo;
    };
    let a = -1, b = -1;
    for (let at = flat.indexOf(want); at >= 0; at = flat.indexOf(want, at + 1)) {
      const ia = unitAt(at), ib = unitAt(at + want.length - 1);
      if (a < 0) { a = ia; b = ib; }
      if (target.contains(units[ia].n)) { a = ia; b = ib; break; }
    }
    if (a >= 0) {
      const END = "。！？!?；;", CLOSE = "”’」』）)】》〉\"'";
      const isEnd = i => END.includes(units[i].s) || (units[i].s === "." && (units[i].ws || i + 1 === units.length));
      let s0 = a, s1 = b;
      while (s0 > 0 && !isEnd(s0 - 1)) s0--;
      while (s0 < a && CLOSE.includes(units[s0].s)) s0++;
      while (s1 + 1 < units.length && !isEnd(s1)) s1++;
      while (s1 + 1 < units.length && CLOSE.includes(units[s1 + 1].s)) s1++;
      const span = (i, j) => {
        const r = document.createRange();
        r.setStart(units[i].n, units[i].k);
        r.setEnd(units[j].n, units[j].k + 1);
        return r;
      };
      const bands = range => {         // the range's rects merged into one band per text line
        const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0)
          .sort((p, q) => p.top - q.top);
        const out = [];
        for (const r of rects) {
          const last = out[out.length - 1];
          const overlap = last ? Math.min(last.bottom, r.bottom) - Math.max(last.top, r.top) : 0;
          if (last && overlap > 0.5 * Math.min(last.bottom - last.top, r.height)) {
            last.top = Math.min(last.top, r.top); last.bottom = Math.max(last.bottom, r.bottom);
            last.left = Math.min(last.left, r.left); last.right = Math.max(last.right, r.right);
          } else out.push({top: r.top, bottom: r.bottom, left: r.left, right: r.right});
        }
        return out;
      };
      const whole = span(s0, s1);
      sentence = whole.toString().replace(/\s+/g, " ").trim();
      let lines = bands(whole);
      if (lines.length > maxLines) {
        const own = bands(span(a, b));
        lines = lines.filter(l => own.some(m => Math.min(l.bottom, m.bottom) - Math.max(l.top, m.top) > 0));
        cut = true;
      }
      if (lines.length) {
        const cs = getComputedStyle(tb), tr = tb.getBoundingClientRect();
        const left = Math.max(tr.left, Math.min(tr.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
                                                ...lines.map(l => l.left)));
        const right = Math.min(tr.right, Math.max(tr.right - parseFloat(cs.borderRightWidth) -
                                                  parseFloat(cs.paddingRight), ...lines.map(l => l.right)));
        const top = lines[0].top, bottom = lines[lines.length - 1].bottom;
        if (right > left && bottom > top) mr = {left, top, width: right - left, height: bottom - top};
      }
      fontPx = parseFloat(getComputedStyle(units[a].n.parentElement).fontSize) || fontPx;
    }
  }
  const sx = window.scrollX, sy = window.scrollY;
  let block = tb;
  while (block.parentElement && block.parentElement !== document.body &&
         block.getBoundingClientRect().width < vw * 0.6) block = block.parentElement;
  const br = block.getBoundingClientRect();
  const docW = br.right <= vw + 1 ? vw : Math.max(document.documentElement.scrollWidth, vw);
  const docH = document.documentElement.scrollHeight;
  const x0 = Math.max(0, Math.min(br.left, mr.left) + sx - pad);
  const x1 = Math.min(docW, Math.max(br.right, mr.left + mr.width) + sx + pad), W = x1 - x0;
  const wantH = Math.min(Math.max(mr.height + W * 0.5, W * 0.45), W * 1.25);
  const top = br.top + sy - pad, bot = br.bottom + sy + pad;
  let y0, y1;
  if (bot - top <= wantH) {
    const extra = Math.max(0, W * 0.3 - (bot - top)) / 2;
    y0 = top - extra; y1 = bot + extra;
  } else {
    const cy = mr.top + sy + mr.height / 2;
    y0 = cy - wantH / 2; y1 = cy + wantH / 2;
    if (y0 < top) { y1 += top - y0; y0 = top; }
    if (y1 > bot) { y0 -= y1 - bot; y1 = bot; }
  }
  y0 = Math.max(0, Math.min(y0, mr.top + sy - 4)); y1 = Math.min(docH, Math.max(y1, mr.top + sy + mr.height + 4));
  const flatText = (block.innerText || "").replace(/\s+/g, " ").trim();
  let excerpt = sentence || flatText.slice(0, 220);
  if (!sentence) {
    const raw = (match || "").replace(/\s+/g, " ").trim();
    const pos = raw ? flatText.indexOf(raw) : -1;
    if (pos > 90) excerpt = "…" + flatText.slice(pos - 90, pos + raw.length + 110);
  }
  return {found: true, title: document.title, site, excerpt, sentence, cut, fitted, font_px: fontPx,
          layout_width: vw, crop: {x: x0, y: y0, width: W, height: y1 - y0},
          match: {x: mr.left + sx - x0, y: mr.top + sy - y0, width: mr.width, height: mr.height}};
}
"""


def default_proxy(ctx) -> str | None:
    cfg = ctx.providers.get("capture") or {}
    return cfg.get("proxy") or os.environ.get("REELSMITH_PROXY") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("HTTP_PROXY") or None


def launch_browser(chromium, proxy: str):
    """The first browser of CHANNELS that is installed, headless behind `proxy`; ProviderError when none is."""
    for channel in CHANNELS:
        try:
            return chromium.launch(channel=channel, headless=True, proxy={"server": proxy}, args=LAUNCH_ARGS)
        except Exception as exc:  # noqa: BLE001 - only a missing browser moves on to the next one
            if not _NO_BROWSER.search(str(exc)):
                raise
    raise ProviderError(INSTALL_HINT)


def capture_page(p, url: str, match: str, out: Path, guard) -> dict:
    """One browser session behind `guard`: {"error"} | {"miss", "final_url"} | the FIND_JS result plus final_url."""
    browser = launch_browser(p.chromium, guard.address)
    try:
        # not is_mobile: mobile emulation lays a page without a fitting meta viewport out at 980 px (or its content
        # width) and zooms out, so crops came out ~630 CSS px wide; a 430 px desktop viewport keeps the layout at 430
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DEVICE_SCALE, is_mobile=False,
                                      has_touch=True, user_agent=MOBILE_UA, locale="zh-CN",
                                      timezone_id="Asia/Shanghai")
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        response = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        if response is not None and response.status >= 400:
            return {"error": f"the page answered HTTP {response.status} (blocked or missing); use another source"}
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:  # noqa: BLE001 — busy pages never go idle; what loaded is enough
            pass
        page.wait_for_timeout(800)
        page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
        info = page.evaluate(FIND_JS, [match or "", PAD_CSS, MAX_BOX_LINES])
        if not info.get("found"):
            return {"miss": info, "final_url": page.url}
        crop = info.get("crop") or {}
        if min(float(crop.get("width") or 0), float(crop.get("height") or 0)) < 1:
            return {"error": "the matched text has no visible area on the page (hidden or collapsed); give another "
                             "phrase or leave match empty"}
        page.wait_for_timeout(500)
        page.screenshot(path=str(out), clip=info["crop"], full_page=True, animations="disabled")
        info["final_url"] = page.url
        return info
    finally:
        browser.close()


def box_in_pixels(info: dict, size: tuple[int, int], scale: float = DEVICE_SCALE) -> list[int]:
    """The box (CSS px, relative to the crop) as [x, y, w, h] in the PNG's pixels, kept inside the image."""
    m = info["match"]
    w_img, h_img = size
    x0 = min(max(0.0, float(m["x"]) * scale), float(w_img))
    y0 = min(max(0.0, float(m["y"]) * scale), float(h_img))
    x1 = min(max(x0, (float(m["x"]) + float(m["width"])) * scale), float(w_img))
    y1 = min(max(y0, (float(m["y"]) + float(m["height"])) * scale), float(h_img))
    return [int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))]


def readable_width(font_css: float, box_w: int, scale: float = DEVICE_SCALE) -> int | None:
    """How wide (canvas px) the box must be shown for its text to stand READABLE_PX tall; None when unknown."""
    if not font_css or font_css <= 0 or box_w <= 0:
        return None
    return int(math.ceil(READABLE_PX * box_w / (font_css * scale)))


def _next_id(ctx) -> str:
    taken = set((read_project(ctx).get("assets") or {}).keys()) | {f.stem for f in ctx.assets_dir.glob("ev_*.png")}
    n = 1
    while f"ev_{n:02d}" in taken:
        n += 1
    return f"ev_{n:02d}"


def _miss_text(match: str, miss: dict) -> str:
    heads = "; ".join(h for h in miss.get("heads") or [] if h) or "(none)"
    what = f"Did not find {match!r} on the page." if match else "Found no headline to capture."
    return (f"{what} Page title: {miss.get('title')} ({miss.get('site')}). Headings: {heads}. "
            f"Text starts: {miss.get('text')}\n"
            "Give match as a short phrase exactly as the page shows it (8-20 characters work best; numbers as "
            "written there), or leave it empty to capture the headline. A page that reads like a captcha or "
            "'access denied' blocks robots: use another source.")


def _refused_text(rows: list[str]) -> str:
    return "; ".join(rows[:3]) + (f" (+{len(rows) - 3} more)" if len(rows) > 3 else "")


@safe_tool
def capture(project, url, match="", id="", *, sync_playwright=None, proxy="default", resolve=None, trusted=()):
    """(text, is_error): assets/<id>.png evidence of a public web page, its box around the sentence that holds
    `match` (whole lines of the text column; the headline when match is empty)."""
    ctx = context(project)
    url = str(url or "").strip()
    if not re.match(r"^https?://[^\s/]+", url):
        return "url must be a public web page address starting with http:// or https://", True
    proxy = default_proxy(ctx) if proxy == "default" else proxy
    if proxy:
        try:
            netcheck.proxy_address(proxy)
        except ValueError as exc:
            return f"{exc} (providers.capture.proxy, REELSMITH_PROXY or HTTPS_PROXY)", True
    why = netcheck.public_url(url, resolve or (netcheck.doh_resolver(proxy) if proxy else None), trusted)
    if why:
        return f"capture refused {url[:120]}: {why}", True
    match = re.sub(r"\s+", " ", str(match or "")).strip()
    if len(match) > MAX_MATCH_CHARS:
        return f"match is {len(match)} characters; give a short phrase (at most {MAX_MATCH_CHARS})", True
    asset_id = check_id(id) if id else _next_id(ctx)
    check_replaceable(ctx, asset_id, "evidence")
    if sync_playwright is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ProviderError("playwright is not installed; capture cannot run here") from None
    ctx.assets_dir.mkdir(parents=True, exist_ok=True)
    out = ctx.assets_dir / f"{asset_id}.png"
    part = ctx.assets_dir / f".{asset_id}.capture.png"
    try:
        info = _run_browser(sync_playwright, url, match, part, proxy, resolve, trusted)
        if info.get("error"):
            return info["error"], True
        if "miss" in info:
            return _miss_text(match, info["miss"]), True
        size = header_size(part)
        if not size:
            return "the screenshot came out unreadable; try again", True
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    box = box_in_pixels(info, size)
    note = " | ".join(x for x in (str(info.get("title") or "").strip()[:120],
                                  str(info.get("excerpt") or "").strip()[:240]) if x)
    entry = {"path": rel(ctx, out), "kind": "evidence", "box": box, "site": str(info.get("site") or "")[:80],
             "url": url, "note": note}
    reg = register_asset(ctx, asset_id, entry)
    final = info.get("final_url") or url
    moved = f" (landed on {final})" if final != url else ""
    what = "the sentence that holds the match" if info.get("sentence") else \
        "the matched text" if match else "the headline"
    if info.get("cut"):
        what = f"the match's own lines (its sentence runs over {MAX_BOX_LINES} lines)"
    rows = [f"Evidence {asset_id!r}: {entry['path']}, {size[0]}x{size[1]} px.{reg}",
            f"Source: {info.get('title')} ({entry['site']}) {url}{moved}",
            f"It shows: {info.get('excerpt')}",
            f"Box of {what} (x, y, w, h in the image's pixels, whole lines of the text column): {box}. That is the "
            "part to enlarge and highlight."]
    need = readable_width(float(info.get("font_px") or 0), box[2])
    if need:
        at840 = READABLE_PX * 840 / need
        rows.append(f"Its text is {float(info['font_px']):.0f} CSS px: the box must be shown at least {need} px wide "
                    f"for it to stand {READABLE_PX} px tall (at 840 px wide: {at840:.0f} px).")
    if info.get("refused"):
        rows.append(f"Blocked while loading (local or private addresses): {_refused_text(info['refused'])}.")
    rows.append("Look at the PNG once to confirm it is clear and not covered, and add the page to meta.sources.")
    return "\n".join(rows), False


def _browser_error(exc: Exception, guard) -> Exception:
    said = str(exc)
    if _NO_BROWSER.search(said):
        return ProviderError(INSTALL_HINT)
    if guard.refused:
        return ProviderError(f"the page led to an address capture refuses ({_refused_text(guard.refused)}); "
                             "use another source")
    if "Timeout" in type(exc).__name__:
        return ProviderError(f"the page did not load within {TIMEOUT_MS // 1000} s; try again or use another source")
    if "net::ERR_" in said:
        err = re.search(r"net::ERR_[A-Z_]+", said).group(0)
        reach = f": {guard.unreachable[0]}" if guard.unreachable else ""
        return ProviderError(f"the page could not be opened ({err}{reach}); check the address or use another source")
    return exc


def _run_browser(sync_playwright, url, match, out, proxy, resolve=None, trusted=()) -> dict:
    with _LOCK:
        with sync_playwright() as p:
            upstream = proxy
            while True:
                with netcheck.GuardProxy(upstream, resolve=resolve, trusted=trusted) as guard:
                    try:
                        info = capture_page(p, url, match, out, guard)
                    except Exception as exc:  # noqa: BLE001
                        if upstream and guard.upstream_failed:
                            upstream = None                 # the outbound proxy is down: go direct
                            continue
                        raise _browser_error(exc, guard) from None
                    failed = "error" in info or "miss" in info
                    if failed and upstream and guard.upstream_failed:
                        upstream = None
                        continue
                    if "error" in info and guard.refused:
                        return {"error": f"the page led to an address capture refuses "
                                         f"({_refused_text(guard.refused)}); use another source"}
                    info["refused"] = list(guard.refused)
                    return info
