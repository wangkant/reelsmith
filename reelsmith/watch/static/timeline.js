import { lang, t } from "./i18n.js";
import { clamp, css, disable, h, timecode, tip, typeColor, writtenText } from "./util.js";

const RULER = 40;
const LABELS = 18;                 // the top band of the ruler holds the time labels, the rest the ticks and the playhead
const ROW = { narration: 44, visual: 52, audio: 40, captions: 28 };
const BAR_H = 36, HBAR_H = 13;
const MAX_PPS = 600;
const FLASH_MS = 1600;
const STOPS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16];
const GRAPHIC = new Set(["text", "component", "shape", "evidence"]);
const UI_FONT = "system-ui, 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', sans-serif";
const LABEL_INK = "#f2f3f5";

// The timeline is one canvas drawn from the view (the live cut or a history snapshot); only the visible span is drawn.
export function createTimeline(app) {
  const $ = (id) => document.getElementById(id);
  const main = $("tlMain"), canvas = $("tlCanvas"), ctx = canvas.getContext("2d");
  const heads = $("tlHeads"), tipEl = $("tlTip"), empty = $("tlEmpty");
  const hbar = $("tlHbar"), hthumb = $("tlHthumb"), vbar = $("tlVbar"), vthumb = $("tlVthumb"), fade = $("tlFade");
  const zoomLabel = $("zoomLabel"), zoomInBtn = $("zoomIn"), zoomOutBtn = $("zoomOut"), fitBtn = $("zoomFit");
  canvas.setAttribute("aria-label", t("tl.canvas"));

  let W = 0, H = 0, dpr = 1;
  let pps = 40, scrollT = 0, scrollY = 0, fit = true;
  let rows = [];
  let hits = [];
  let hover = null, pressed = null;
  let ghostX = null, onHeadNow = false;    // the ruler's hover line, and the playhead under the pointer
  let raf = 0;
  let pointerX = null;
  const images = new Map();
  const waves = new Map();
  const lastSpan = new Map();      // a clip's last known times, to keep drawing it when it cannot be timed
  let marks = { level: new Map(), missing: new Set(), issue: new Map() };
  let colors = {};
  let hatch = null;

  function readColors() {
    colors = {
      bg: css("--tl-bg"), row: css("--tl-row"), rowAlt: css("--tl-row-alt"), line: css("--line"), text: css("--text"),
      dim: css("--text-dim"), faint: css("--text-faint"), accent: css("--accent"), accentHover: css("--accent-hover"), accentInk: css("--accent-ink"),
      ruler: css("--tl-ruler"), error: css("--error"), warning: css("--warning"), advice: css("--advice"),
      voice: css("--clip-voice"), caption: css("--clip-caption"), marker: css("--marker"),
    };
    const p = document.createElement("canvas");
    p.width = p.height = 8;
    const g = p.getContext("2d");
    g.strokeStyle = "rgba(255,127,117,0.42)";
    g.lineWidth = 3;
    g.beginPath(); g.moveTo(-2, 10); g.lineTo(10, -2); g.moveTo(6, 10); g.lineTo(10, 6); g.moveTo(-2, 2); g.lineTo(2, -2); g.stroke();
    hatch = ctx.createPattern(p, "repeat");
  }

  // ---------------------------------------------------------------- geometry
  const view = () => app.view();
  const dur = () => Math.max(view().duration || (rows.length ? 1 : 10), 0.001);
  const x = (sec) => (sec - scrollT) * pps;
  const tAt = (px) => scrollT + px / pps;
  const fitPps = () => Math.max(1e-3, (W - 24) / Math.max(dur(), 1));
  const minPps = () => fitPps() * STOPS[0];
  const maxPps = () => Math.max(MAX_PPS, fitPps());
  const maxScroll = () => Math.max(0, dur() + 24 / pps - W / pps);
  const contentH = () => rows.reduce((s, r) => s + r.h, 0);
  const maxScrollY = () => Math.max(0, contentH() + RULER - H);
  const zoomLevel = () => pps / fitPps();

  // ---------------------------------------------------------------- rows and their heads
  function roleOf(r) {
    if (r.kind === "narration") return t("tl.narration");
    if (r.kind === "captions") return t("tl.role.captions");
    if (r.kind === "audio") return t("tl.role.sound");
    const clips = r.track.clips || [];
    if (!clips.length) return t("tl.role.picture");
    const gfx = clips.filter((c) => GRAPHIC.has(c.type)).length;
    return t(gfx * 2 >= clips.length ? "tl.role.titles" : "tl.role.footage");
  }
  function dominant(r) {
    if (r.kind === "narration") return "voice";
    if (r.kind === "captions") return "caption";
    const n = new Map();
    for (const c of r.track.clips || []) n.set(c.type, (n.get(c.type) || 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1])[0]?.[0] || (r.kind === "audio" ? "audio" : "shape");
  }

  function buildMarks() {
    const v = view();
    const level = new Map(), issue = new Map();
    const rank = { error: 3, warning: 2, advice: 1 };
    for (const is of v.issues || []) {
      if (!is.clip) continue;
      if ((rank[is.level] || 0) > (rank[level.get(is.clip)] || 0)) { level.set(is.clip, is.level); issue.set(is.clip, is); }
    }
    const gone = new Set((v.assets || app.state?.assets || []).filter((a) => a.missing).map((a) => a.id));
    marks = { level, issue, missing: gone };
  }
  const isMissing = (c) => !!c.asset && marks.missing.has(c.asset);
  const levelOf = (c) => (c.start == null || isMissing(c) ? "error" : marks.level.get(c.id) || null);

  function buildRows() {
    const v = view();
    buildMarks();
    rows = [];
    if (v.voice) rows.push({ kind: "narration", h: ROW.narration, id: "voice" });
    for (const tr of v.tracks || []) rows.push({ kind: tr.kind, h: ROW[tr.kind] || ROW.visual, track: tr, id: tr.id });
    let y = RULER;
    for (const r of rows) { r.y = y; y += r.h; }
    if (!app.viewing) {
      for (const tr of v.tracks || []) for (const c of tr.clips || []) if (c.start != null) lastSpan.set(c.id, { start: c.start, end: c.end });
    }
    renderHeads();
    const visual = (v.tracks || []).some((tr) => tr.kind === "visual");
    const showEmpty = !app.dimmed() && (app.viewing ? !visual : !(v.tracks || []).length && !app.broken());
    empty.hidden = !showEmpty;
    if (showEmpty) {
      $("tlEmptyTitle").textContent = app.viewing ? t("tl.emptyHistory", { n: app.viewing.n }) : t("tl.emptyTitle");
      $("tlEmptyBody").textContent = app.viewing ? "" : t("tl.emptyBody");
    }
  }

  function renderHeads() {
    heads.replaceChildren(h("div", { class: "tl-head-ruler" }));
    const inner = h("div", { class: "tl-head-rows" });
    const v = view();
    for (const r of rows) {
      let count;
      if (r.kind === "narration") count = t("tl.lines", { n: v.voice?.lines.length || 0 });
      else if (r.kind === "captions") count = t("tl.items", { n: (r.track.items || []).length });
      else count = t("tl.clips", { n: r.track.clips.length });
      const bad = (r.track?.clips || []).some((c) => levelOf(c) === "error");
      const role = roleOf(r);
      inner.append(h("div", { class: `tl-head k-${r.kind}${r.track?.hidden ? " is-hidden" : ""}`, style: { height: `${r.h}px`, "--sw": `var(--clip-${dominant(r)})` } },
        h("span", { class: "tl-head-swatch" }),
        h("span", { class: "tl-head-text" },
          h("span", { class: "tl-head-name", text: role, title: role }),
          h("span", { class: "tl-head-kind", text: `${r.id} · ${count}` })),
        bad ? h("span", { class: "tl-head-err", title: t("tl.trackProblem") }) : null,
        r.track?.hidden ? h("span", { class: "tl-head-eye", title: t("tl.hiddenTip") },
          (() => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); const u = document.createElementNS("http://www.w3.org/2000/svg", "use"); u.setAttribute("href", "#i-eye-off"); s.append(u); return s; })()) : null));
    }
    heads.append(inner);
    syncHeads();
  }
  function syncHeads() {
    const inner = heads.querySelector(".tl-head-rows");
    if (inner) inner.style.transform = `translateY(${-scrollY}px)`;
  }

  function resize() {
    const r = main.getBoundingClientRect();
    dpr = devicePixelRatio || 1;
    W = Math.max(1, Math.floor(r.width));
    H = Math.max(1, Math.floor(r.height));
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    if (fit) doFit(); else clampScroll();
    draw();
  }

  function clampScroll() {
    pps = clamp(pps, minPps(), maxPps());
    scrollT = clamp(scrollT, 0, maxScroll());
    scrollY = clamp(scrollY, 0, maxScrollY());
    syncHeads();
    updateBars();
  }

  function doFit() {
    fit = true;
    pps = fitPps();
    scrollT = 0;
    clampScroll();
  }

  function anchor() {
    if (pointerX != null) return pointerX;
    const ph = x(app.time);
    return ph >= 0 && ph <= W ? ph : W / 2;
  }
  function zoomTo(next, ax = anchor()) {
    const at = tAt(ax);
    pps = clamp(next, minPps(), maxPps());
    fit = Math.abs(pps - fitPps()) < 0.5;
    scrollT = at - ax / pps;
    clampScroll();
    request();
  }
  function zoomStep(dir) {
    const z = zoomLevel();
    let next;
    if (dir > 0) next = STOPS.find((s) => s > z * 1.01) ?? z * 1.5;
    else next = [...STOPS].reverse().find((s) => s < z / 1.01) ?? z / 1.5;
    zoomTo(next * fitPps());
  }

  function updateBars() {
    const total = dur() + 24 / pps;
    const vis = W / pps;
    hbar.classList.toggle("off", vis >= total - 1e-6);
    const bw = hbar.clientWidth - 148;
    const tw = Math.max(32, (vis / total) * bw);
    hthumb.style.width = `${tw}px`;
    hthumb.style.transform = `translateX(${maxScroll() ? (scrollT / maxScroll()) * (bw - tw) : 0}px)`;

    const over = maxScrollY() > 0 && rows.length;
    vbar.hidden = !over;
    fade.hidden = !over || scrollY >= maxScrollY() - 1;
    if (over) {
      const track = H - RULER - 4;
      const th = Math.max(24, ((H - RULER) / contentH()) * track);
      vthumb.style.height = `${th}px`;
      vthumb.style.top = `${(scrollY / maxScrollY()) * (track - th)}px`;
    }

    const z = zoomLevel();
    zoomLabel.textContent = `${Math.round(z * 100)}%`;
    disable(zoomInBtn, pps >= maxPps() - 1e-6 ? t("tl.zoomMax") : null, t("tl.zoomIn"), "+");
    disable(zoomOutBtn, pps <= minPps() + 1e-6 ? t("tl.zoomMin") : null, t("tl.zoomOut"), "−");
    fitBtn.setAttribute("aria-pressed", String(fit));
    tip(fitBtn, fit ? t("tl.fitted") : t("tl.fitTip"), "F");
  }

  // ---------------------------------------------------------------- assets for drawing
  function image(url) {
    let e = images.get(url);
    if (!e) {
      e = { img: new Image(), ok: false };
      e.img.onload = () => { e.ok = true; request(); };
      e.img.src = url;
      images.set(url, e);
    }
    return e.ok ? e.img : null;
  }
  function wave(asset) {
    let e = waves.get(asset);
    if (!e) {
      e = { data: null };
      waves.set(asset, e);
      fetch(`/api/wave?asset=${encodeURIComponent(asset)}`).then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (d?.peaks?.length) d.max = Math.max(0.05, ...d.peaks); e.data = d; request(); }).catch(() => {});
    }
    return e.data;
  }

  // ---------------------------------------------------------------- text
  const seg = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(lang === "zh" ? "zh" : "en", { granularity: "word" }) : null;
  const words = new Map();
  function wordsOf(s) {
    let w = words.get(s);
    if (!w) {
      w = seg ? [...seg.segment(s)].map((p) => p.segment) : s.split(/(\s+)/);
      if (words.size > 2000) words.clear();
      words.set(s, w);
    }
    return w;
  }
  // Whole words or nothing: a caption cut mid-word reads as noise.
  function fitWords(s, maxW) {
    if (ctx.measureText(s).width <= maxW) return s;
    let acc = "", best = "";
    for (const w of wordsOf(s)) {
      acc += w;
      const cand = acc.trimEnd();
      if (ctx.measureText(cand + "…").width <= maxW) best = cand; else break;
    }
    return best && /\S/.test(best) ? best + "…" : "";
  }
  function text(str, x0, y0, maxW, font, color, whole = false) {
    if (maxW < 12 || !str) return 0;
    ctx.font = font;
    ctx.fillStyle = color;
    let s = str;
    if (whole) s = fitWords(str, maxW);
    else if (ctx.measureText(s).width > maxW) {
      let lo = 0, hi = s.length;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (ctx.measureText(s.slice(0, mid) + "…").width <= maxW) lo = mid; else hi = mid - 1;
      }
      s = lo >= 2 ? s.slice(0, lo) + "…" : "";
    }
    if (s) ctx.fillText(s, x0, y0);
    return s ? ctx.measureText(s).width : 0;
  }

  // ---------------------------------------------------------------- drawing
  function request() {
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); });
  }

  function rr(x0, y0, w, hh, r) {
    ctx.beginPath();
    ctx.roundRect(x0, y0, w, hh, Math.max(0, Math.min(r, w / 2, hh / 2)));
  }

  function niceStep(minPx) {
    const steps = [1 / 30, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    return steps.find((s) => s * pps >= minPx) || 600;
  }
  function rulerLabel(sec, step) {
    const m = Math.floor(sec / 60), s = sec - m * 60;
    const ss = step < 1 ? s.toFixed(2).padStart(5, "0") : String(Math.round(s)).padStart(2, "0");
    return `${m}:${ss}`;
  }

  function draw() {
    if (!W) return;
    const now = performance.now();
    const v = view();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = colors.bg;
    ctx.fillRect(0, 0, W, H);
    hits = [];
    const t0 = tAt(0), t1 = tAt(W);
    let flashing = false;
    const dim = app.dimmed();

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, RULER, W, H - RULER);
    ctx.clip();
    ctx.translate(0, -scrollY);
    rows.forEach((r, i) => {
      if (r.y + r.h < scrollY + RULER || r.y > scrollY + H) return;
      ctx.fillStyle = i % 2 ? colors.rowAlt : colors.row;
      ctx.fillRect(0, r.y, W, r.h);
      ctx.fillStyle = colors.line;
      ctx.fillRect(0, r.y + r.h - 1, W, 1);
    });
    if (v.duration && x(v.duration) < W) {
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.fillRect(Math.max(0, x(v.duration)), RULER, W, contentH() + scrollY);
    }
    for (const r of rows) {
      if (r.y + r.h < scrollY + RULER || r.y > scrollY + H) continue;
      ctx.globalAlpha = (r.track?.hidden ? 0.4 : 1) * (dim ? 0.32 : 1);
      if (r.kind === "narration") drawNarration(r, t0, t1);
      else if (r.kind === "captions") drawCaptions(r, t0, t1);
      else {
        const placed = placeAll(r.track.clips);
        for (const p of placed) {
          if (p.end < t0 || p.start > t1) continue;
          flashing = drawClip(p.c, r, now, p) || flashing;
        }
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    drawRuler(t0, t1, v);
    drawPlayhead();
    if (flashing) request();
  }

  // Where each clip is drawn: its own times, else where it last was, else in the first gap that holds it.
  function placeAll(clips) {
    const timed = clips.filter((c) => c.start != null).sort((a, b) => a.start - b.start);
    const taken = timed.map((c) => [c.start, c.end]);
    return clips.map((c) => {
      if (c.start != null) return { c, start: c.start, end: c.end, ghost: false };
      const last = lastSpan.get(c.id);
      if (last) return { c, start: last.start, end: last.end, ghost: true };
      const need = Math.max(1, 64 / pps);
      let at = 0;
      for (const [a, b] of taken) {
        if (a - at >= need) break;
        at = Math.max(at, b);
      }
      const end = taken.find(([a]) => a >= at)?.[0];
      const span = [at, end != null && end - at >= need ? end : at + need];
      taken.push(span);
      taken.sort((p, q) => p[0] - q[0]);
      return { c, start: span[0], end: span[1], ghost: true };
    });
  }

  function clipRect(p, r) {
    const x0 = x(p.start), x1 = x(p.end);
    return { x: x0, y: r.y + 4, w: Math.max(2, x1 - x0), h: r.h - 8 };
  }

  function drawClip(c, r, now, p) {
    const b = clipRect(p, r);
    const sel = app.selected === c.id;
    const isHover = hover?.clip === c;
    const missing = isMissing(c);
    const level = levelOf(c);
    const hatched = p.ghost || missing;
    ctx.save();
    rr(b.x, b.y, b.w, b.h, 4);
    ctx.fillStyle = hatched ? colors.row : typeColor(c.type);
    ctx.fill();
    if (hatched) { ctx.fillStyle = hatch; ctx.fill(); }
    ctx.clip();

    if (!hatched && r.kind === "visual" && c.thumb && b.w > 24) {
      const img = image(`${c.thumb}${c.thumb.includes("?") ? "&" : "?"}h=72`);
      if (img) {
        const th = b.h - 16;
        const tw = (img.naturalWidth / img.naturalHeight) * th;
        const a = ctx.globalAlpha;
        ctx.globalAlpha = a * 0.62;
        const left = Math.max(b.x, -tw);
        const startX = b.x + Math.floor((left - b.x) / (tw + 2)) * (tw + 2);
        for (let px = startX; px < Math.min(b.x + b.w, W); px += tw + 2) ctx.drawImage(img, px, b.y + 16, tw, th);
        ctx.globalAlpha = a;
      }
    }
    if (!hatched && r.kind === "audio" && c.asset) drawWave(c, b, "rgba(255,255,255,0.42)");

    // Label strip: the label on the left, badges on the right; a mark (! or missing file) wins the right end.
    ctx.fillStyle = "rgba(0,0,0,0.3)";
    ctx.fillRect(b.x, b.y, b.w, 16);
    const lx = Math.max(b.x, 0) + 6;
    let right = b.x + b.w - 5;
    const badge = (s, bg, fg) => {
      ctx.font = `600 10px ${UI_FONT}`;
      const w = ctx.measureText(s).width + 8;
      if (right - w < lx + 24) return false;
      right -= w;
      rr(right, b.y + 2, w, 12, 3);
      ctx.fillStyle = bg;
      ctx.fill();
      ctx.fillStyle = fg;
      ctx.fillText(s, right + 4, b.y + 11);
      right -= 3;
      return true;
    };
    if (level === "error" || level === "warning") {
      const col = colors[level];
      const cx = right - 6;
      if (cx > lx + 10) {
        ctx.beginPath(); ctx.arc(cx, b.y + 8, 6, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
        ctx.fillStyle = "#1a0f0e"; ctx.font = `700 10px ${UI_FONT}`; ctx.fillText("!", cx - 1.6, b.y + 11.5);
        right -= 15;
      }
    }
    if (missing) badge(t("tl.missingFile"), "rgba(255,127,117,0.9)", "#2a0e0c");
    else if (p.ghost) badge(t("tl.notTimed"), "rgba(255,127,117,0.9)", "#2a0e0c");
    else for (const s of badgesOf(c).reverse()) if (!badge(s, "rgba(0,0,0,0.5)", "#e9eaee")) break;
    text(c.label || c.id, lx, b.y + 12, right - lx - 2, `500 11px ${UI_FONT}`, hatched ? colors.text : LABEL_INK);
    if (r.kind === "visual" && c.label !== c.id && b.h > 34 && !c.thumb) {
      text(c.id, lx, b.y + 31, b.x + b.w - lx - 6, "11px ui-monospace, Consolas, monospace", "rgba(242,243,245,0.85)");
    }

    if (!hatched) {
      // Enter / exit ramps along the bottom edge.
      ctx.fillStyle = "rgba(255,255,255,0.32)";
      if (c.enter?.dur) {
        const w = c.enter.dur * pps;
        ctx.beginPath(); ctx.moveTo(b.x, b.y + b.h); ctx.lineTo(b.x + w, b.y + b.h); ctx.lineTo(b.x, b.y + b.h - 9); ctx.fill();
      }
      if (c.exit?.dur) {
        const w = c.exit.dur * pps, e = b.x + b.w;
        ctx.beginPath(); ctx.moveTo(e, b.y + b.h); ctx.lineTo(e - w, b.y + b.h); ctx.lineTo(e, b.y + b.h - 9); ctx.fill();
      }
      const kfs = Object.values(c.keyframes || {}).flat();
      if (kfs.length) {
        ctx.fillStyle = "#f4e2b0";
        ctx.strokeStyle = "rgba(0,0,0,0.5)";
        for (const k of kfs) {
          const kx = x(k), ky = b.y + b.h - 8;
          if (kx < b.x - 4 || kx > b.x + b.w + 4) continue;
          ctx.beginPath(); ctx.moveTo(kx, ky - 4); ctx.lineTo(kx + 4, ky); ctx.lineTo(kx, ky + 4); ctx.lineTo(kx - 4, ky); ctx.closePath();
          ctx.fill(); ctx.stroke();
        }
      }
    }
    if (pressed === c.id) { ctx.fillStyle = "rgba(0,0,0,0.22)"; ctx.fillRect(b.x, b.y, b.w, b.h); }
    else if (isHover) { ctx.fillStyle = "rgba(255,255,255,0.07)"; ctx.fillRect(b.x, b.y, b.w, b.h); }
    ctx.restore();

    if (c.transition?.dur && !hatched) {
      const tx = b.x, tw = c.transition.dur * pps;
      ctx.save();
      rr(tx, b.y, tw, b.h, 3);
      ctx.fillStyle = "rgba(255,255,255,0.16)";
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(tx, b.y + b.h); ctx.lineTo(tx + tw, b.y); ctx.moveTo(tx, b.y); ctx.lineTo(tx + tw, b.y + b.h); ctx.stroke();
      ctx.restore();
    }

    // Marks around the clip: problem, latest change, recent flash, hover, selection, keyboard focus.
    if (level === "error" || level === "warning" || hatched) {
      rr(b.x + 0.75, b.y + 0.75, b.w - 1.5, b.h - 1.5, 4);
      ctx.strokeStyle = colors[level || "error"];
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    if (app.latest.has(c.id) && !app.viewing && b.w > 12) {
      ctx.beginPath(); ctx.arc(b.x + b.w - 4, b.y + b.h - 4, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = colors.accent; ctx.fill();
    }
    let flashing = false;
    const changed = app.changedAt(c.id);
    if (changed) {
      const k = 1 - (now - changed) / FLASH_MS;
      if (k > 0) {
        flashing = true;
        ctx.save();
        rr(b.x - 1, b.y - 1, b.w + 2, b.h + 2, 5);
        ctx.strokeStyle = colors.accent;
        ctx.globalAlpha = Math.min(1, k * 1.4);
        ctx.lineWidth = 2;
        ctx.shadowColor = colors.accent;
        ctx.shadowBlur = 12 * k;
        ctx.stroke();
        ctx.fillStyle = colors.accent;
        ctx.globalAlpha = 0.18 * k;
        ctx.fill();
        ctx.restore();
      }
    }
    if (sel) {
      rr(b.x + 1, b.y + 1, b.w - 2, b.h - 2, 4);
      ctx.strokeStyle = colors.accent;
      ctx.lineWidth = 2;
      ctx.stroke();
      if (canvas.matches(":focus-visible")) {
        rr(b.x - 2.5, b.y - 2.5, b.w + 5, b.h + 5, 6);
        ctx.strokeStyle = "rgba(110,168,255,0.55)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    } else if (isHover) {
      rr(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1, 4);
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.lineWidth = 1;
    hits.push({ ...b, y: b.y - scrollY, clip: c, track: r.track, ghost: p.ghost, start: p.start, end: p.end });
    return flashing;
  }

  function badgesOf(c) {
    const out = [];
    if (c.rate != null && c.rate !== 1) out.push(`${+c.rate.toFixed(2)}×`);
    if (c.reverse) out.push(t("badge.rev"));
    if (c.hold != null) out.push(t("badge.freeze"));
    if (c.muted) out.push(t("badge.mute"));
    else if (c.type === "audio" && c.volume != null && c.volume !== 1) out.push(t("badge.vol", { v: c.volume }));
    if (c.loop) out.push(t("badge.loop"));
    return out;
  }

  function drawWave(c, b, color, top = 16) {
    const d = wave(c.asset);
    if (!d || !d.peaks?.length) return;
    const rate = c.rate || 1;
    const trim = +(c.raw?.trim_in || 0);
    const per = d.peaks.length / Math.max(d.duration, 1e-3);
    const mid = b.y + top + (b.h - top) / 2, amp = (b.h - top - 4) / 2;
    ctx.fillStyle = color;
    const xs = Math.max(b.x, 0), xe = Math.min(b.x + b.w, W);
    for (let px = xs; px < xe; px += 2) {
      let src = (tAt(px) - c.start) * rate + trim;
      if (c.loop && d.duration) src %= d.duration;
      const i = Math.floor(src * per);
      if (i < 0 || i >= d.peaks.length) continue;
      const pk = (d.peaks[i] / d.max) * amp;
      ctx.fillRect(px, mid - pk, 1.2, Math.max(1, pk * 2));
    }
  }

  function drawNarration(r, t0, t1) {
    const v = view().voice;
    const b = { y: r.y + 4, h: r.h - 8 };
    for (const ln of v.lines) {
      if (ln.end < t0 || ln.start > t1) continue;
      const x0 = x(ln.start), w = Math.max(2, x(ln.end) - x0);
      ctx.save();
      rr(x0, b.y, w, b.h, 4);
      ctx.fillStyle = colors.voice;
      ctx.fill();
      ctx.clip();
      drawWave({ asset: v.asset || "voice", start: 0, rate: 1, raw: {} }, { x: x0, y: b.y, w, h: b.h }, "rgba(255,255,255,0.2)", 16);
      ctx.fillStyle = "rgba(0,0,0,0.3)";
      ctx.fillRect(x0, b.y, w, 17);
      const lx = Math.max(x0, 0) + 4;
      const room = x0 + w - lx - 6;
      if (room > 22) {
        ctx.beginPath(); ctx.arc(lx + 7, b.y + 8.5, 7, 0, Math.PI * 2); ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fill();
        ctx.font = `600 9.5px ${UI_FONT}`;
        ctx.fillStyle = LABEL_INK;
        const n = String(ln.i);
        ctx.fillText(n, lx + 7 - ctx.measureText(n).width / 2, b.y + 12);
        text(ln.text, lx + 19, b.y + 12.5, room - 19, `500 11px ${UI_FONT}`, LABEL_INK, true);
      }
      if (hover?.line === ln) { ctx.fillStyle = "rgba(255,255,255,0.07)"; ctx.fillRect(x0, b.y, w, b.h); }
      ctx.restore();
      hits.push({ x: x0, y: b.y - scrollY, w, h: b.h, line: ln });
      if (hover?.line === ln) { rr(x0 + 0.5, b.y + 0.5, w - 1, b.h - 1, 4); ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.stroke(); }
    }
  }

  function drawCaptions(r, t0, t1) {
    for (const it of r.track.items || []) {
      if (it.end < t0 || it.start > t1) continue;
      const x0 = x(it.start), w = Math.max(2, x(it.end) - x0 - 1);
      ctx.save();
      rr(x0, r.y + 4, w, r.h - 8, 3);
      ctx.fillStyle = colors.caption;
      ctx.fill();
      ctx.clip();
      if (w >= 40) text(it.text, Math.max(x0, 0) + 5, r.y + r.h / 2 + 4, x0 + w - Math.max(x0, 0) - 9, `11px ${UI_FONT}`, LABEL_INK, true);
      if (hover?.item === it) { ctx.fillStyle = "rgba(255,255,255,0.1)"; ctx.fillRect(x0, r.y, w, r.h); }
      ctx.restore();
      hits.push({ x: x0, y: r.y + 4 - scrollY, w, h: r.h - 8, item: it, track: r.track });
      if (hover?.item === it) { rr(x0 + 0.5, r.y + 4.5, w - 1, r.h - 9, 3); ctx.strokeStyle = "rgba(255,255,255,0.6)"; ctx.stroke(); }
    }
  }

  function drawRuler(t0, t1, v) {
    ctx.fillStyle = colors.ruler;
    ctx.fillRect(0, 0, W, RULER);
    ctx.fillStyle = colors.line;
    ctx.fillRect(0, RULER - 1, W, 1);
    const ph = x(app.time);
    const major = niceStep(84);
    const minorDiv = major >= 60 ? 6 : major === 2 ? 4 : 5;
    const minor = major / minorDiv;
    ctx.font = "10px ui-monospace, 'Cascadia Mono', Consolas, monospace";
    const first = Math.floor(t0 / minor) * minor;
    for (let s = first; s <= t1 + minor; s += minor) {
      if (s < -1e-9) continue;
      const px = Math.round(x(s)) + 0.5;
      const isMajor = Math.abs(s / major - Math.round(s / major)) < 1e-6;
      ctx.fillStyle = isMajor ? colors.dim : colors.faint;
      ctx.fillRect(px, isMajor ? RULER - 11 : RULER - 5, 1, isMajor ? 10 : 4);
      if (isMajor && Math.abs(px + 20 - ph) > 34) {
        ctx.fillStyle = colors.dim;
        ctx.fillText(rulerLabel(Math.round(s * 1000) / 1000, major), px + 3, 13);
      }
    }
    if (v.duration) {
      const ex = x(v.duration);
      if (ex >= 0 && ex <= W) { ctx.fillStyle = colors.dim; ctx.fillRect(Math.round(ex), LABELS, 1, RULER - LABELS); }
    }

    // Chapters and markers sit in the tick band, under the labels.
    const chapters = v.chapters || [];
    chapters.forEach((c, i) => {
      const px = x(c.t);
      const next = chapters[i + 1] ? x(chapters[i + 1].t) : W;
      if (next < 0 || px > W) return;
      ctx.fillStyle = colors.marker;
      ctx.fillRect(Math.round(px), LABELS + 1, 1, 12);
      ctx.beginPath(); ctx.moveTo(px, LABELS + 1); ctx.lineTo(px + 6, LABELS + 4); ctx.lineTo(px, LABELS + 7); ctx.fill();
      text(c.title, px + 9, LABELS + 10, next - px - 14, `500 10px ${UI_FONT}`, colors.dim);
      hits.push({ x: px - 3, y: LABELS, w: 12, h: 14, chapter: c, ruler: true });
    });
    for (const m of v.markers || []) {
      const px = x(m.t);
      if (px < -4 || px > W + 4) continue;
      ctx.fillStyle = colors.marker;
      ctx.beginPath(); ctx.moveTo(px - 4, LABELS + 1); ctx.lineTo(px + 4, LABELS + 1); ctx.lineTo(px + 4, LABELS + 7); ctx.lineTo(px, LABELS + 11); ctx.lineTo(px - 4, LABELS + 7); ctx.fill();
      hits.push({ x: px - 5, y: LABELS, w: 10, h: 12, marker: m, ruler: true });
    }
    for (const is of v.issues || []) {
      if (is.t == null) continue;
      const px = x(is.t);
      if (px < -5 || px > W + 5) continue;
      ctx.fillStyle = colors[is.level] || colors.dim;
      ctx.beginPath(); ctx.moveTo(px - 5, RULER - 1); ctx.lineTo(px + 5, RULER - 1); ctx.lineTo(px, RULER - 9); ctx.fill();
      hits.push({ x: px - 6, y: RULER - 11, w: 12, h: 11, issue: is, ruler: true });
    }
  }

  function drawPlayhead() {
    if (ghostX != null && !drag) {
      ctx.fillStyle = "rgba(110,168,255,0.45)";
      ctx.fillRect(Math.round(ghostX), LABELS, 1, H - LABELS);
    }
    const px = Math.round(x(app.time)) + 0.5;
    if (px < -40 || px > W + 40) return;
    const strong = onHeadNow || app.scrubbing;
    ctx.fillStyle = strong ? colors.accentHover : colors.accent;
    if (px >= -8 && px <= W + 8) {
      const lw = strong ? 2.5 : 1.5;
      ctx.fillRect(px - lw / 2, LABELS + 12, lw, H - LABELS - 12);
      ctx.beginPath();
      ctx.moveTo(px - 5, LABELS + 1); ctx.lineTo(px + 5, LABELS + 1); ctx.lineTo(px + 5, LABELS + 8); ctx.lineTo(px, LABELS + 13); ctx.lineTo(px - 5, LABELS + 8);
      ctx.closePath();
      ctx.fill();
    }
    // the current time, in the label band where a ruler label would be
    ctx.font = "600 10px ui-monospace, 'Cascadia Mono', Consolas, monospace";
    const s = timecode(app.time, app.fps());
    const w = ctx.measureText(s).width + 10;
    const bx = clamp(px - w / 2, 1, W - w - 1);
    rr(bx, 2, w, 14, 3);
    ctx.fillStyle = colors.accent;
    ctx.fill();
    ctx.fillStyle = colors.accentInk;
    ctx.fillText(s, bx + 5, 12.5);
  }

  // ---------------------------------------------------------------- pointer
  function hitAt(px, py) {
    for (let i = hits.length - 1; i >= 0; i--) {
      const b = hits[i];
      if (b.ruler && py >= RULER) continue;
      if (!b.ruler && py < RULER) continue;
      if (px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h) return b;
    }
    return null;
  }
  const sameHit = (a, b) => a === b || !!a && !!b && a.clip === b.clip && a.line === b.line && a.item === b.item
    && a.issue === b.issue && a.marker === b.marker && a.chapter === b.chapter;

  const typeName = (type) => t(`type.${type}`) !== `type.${type}` ? t(`type.${type}`) : type;
  function tipLines(b) {
    const tc = (s) => timecode(s, app.fps());
    const out = [];
    const head = (a, id) => out.push(h("div", { class: "tip-head" }, h("span", { text: a }), id ? h("span", { class: "tip-id", text: id }) : null));
    if (b.clip) {
      const c = b.clip;
      head(`${typeName(c.type)} · ${roleOf(rows.find((r) => r.track === b.track) || { kind: b.track.kind, track: b.track })}`, c.id);
      if (c.label && c.label !== c.id) out.push(h("div", { class: "tip-body", text: c.label }));
      out.push(h("div", { class: "tip-time", text: c.start != null ? `${tc(c.start)} – ${tc(c.end)} · ${(c.end - c.start).toFixed(2)} ${t("unit.s")}` : writtenText(c.written) }));
      if (b.ghost) out.push(h("div", { class: "tip-bad", text: t("tl.notTimed") }));
      if (isMissing(c)) out.push(h("div", { class: "tip-bad", text: `${t("tl.missingFile")}: ${c.asset}` }));
      const is = marks.issue.get(c.id);
      if (is) out.push(h("div", { class: is.level === "error" ? "tip-bad" : "tip-warn", text: is.text }));
    } else if (b.line) {
      head(t("tl.narration"), `line:${b.line.i}`);
      out.push(h("div", { class: "tip-time", text: `${tc(b.line.start)} – ${tc(b.line.end)}` }));
      out.push(h("div", { class: "tip-body", text: b.line.text }));
    } else if (b.item) {
      head(t("type.caption"), b.item.line ? `line:${b.item.line}` : "");
      out.push(h("div", { class: "tip-time", text: `${tc(b.item.start)} – ${tc(b.item.end)}` }));
      out.push(h("div", { class: "tip-body", text: b.item.text }));
    } else if (b.issue) {
      head(t(`lv.${b.issue.level}`), b.issue.clip || "");
      out.push(h("div", { class: "tip-time", text: tc(b.issue.t) }));
      out.push(h("div", { class: "tip-body", text: b.issue.text }));
    } else if (b.marker) {
      head(b.marker.id, tc(b.marker.t));
    } else if (b.chapter) {
      head(b.chapter.title, tc(b.chapter.t));
    }
    return out;
  }
  let tipFor = null, tipTimer = 0;
  function placeTip(px, py) {
    const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
    tipEl.style.left = `${clamp(px + 14, 4, W - tw - 4)}px`;
    tipEl.style.top = `${py + 18 + th > H ? Math.max(4, py - th - 10) : py + 18}px`;
  }
  function showTip(b, px, py) {
    if (!b) { hideTip(); return; }
    if (sameHit(b, tipFor)) { if (!tipEl.hidden) placeTip(px, py); return; }
    hideTip();
    tipFor = b;
    tipTimer = setTimeout(() => {
      tipEl.replaceChildren(...tipLines(b));
      tipEl.hidden = false;
      placeTip(px, py);
    }, 400);
  }
  function hideTip() {
    clearTimeout(tipTimer);
    tipFor = null;
    tipEl.hidden = true;
  }

  function local(e) {
    const r = canvas.getBoundingClientRect();
    return { px: e.clientX - r.left, py: e.clientY - r.top };
  }

  function chooseClip(b) {
    app.select(b.clip.id);
    if (b.ghost || isMissing(b.clip) || marks.level.get(b.clip.id) === "error") {
      const is = marks.issue.get(b.clip.id);
      if (is) app.openIssue(is);
      app.showPanel("issues");
    } else {
      app.showPanel("clip");
    }
  }

  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    hideTip();
    const { px, py } = local(e);
    const onHead = Math.abs(px - x(app.time)) <= 6 && py >= LABELS;
    const b = hitAt(px, py);
    canvas.setPointerCapture(e.pointerId);
    if (py < RULER || onHead) {
      if (b?.issue && !onHead) { app.openIssue(b.issue); app.showPanel("issues"); return; }
      if (b?.marker || b?.chapter) { app.seek((b.marker || b.chapter).t); return; }
      drag = { scrub: true };
      app.scrubbing = true;
      app.seek(tAt(px), "scrub");
      return;
    }
    if (b?.clip) {
      pressed = b.clip.id;
      chooseClip(b);
    }
    app.seek(clamp(tAt(px), 0, dur()), "scrub");
    drag = { scrub: true };
    app.scrubbing = true;
    request();
  });
  canvas.addEventListener("pointermove", (e) => {
    const { px, py } = local(e);
    if (drag?.scrub) {
      app.seek(clamp(tAt(px), 0, dur()), "scrub");
      if (px > W - 20) { scrollT = clamp(scrollT + 8 / pps, 0, maxScroll()); fit = false; updateBars(); }
      if (px < 20) { scrollT = clamp(scrollT - 8 / pps, 0, maxScroll()); fit = false; updateBars(); }
      return;
    }
    const b = hitAt(px, py);
    const onHead = Math.abs(px - x(app.time)) <= 6 && py >= LABELS;
    canvas.style.cursor = b && py < RULER ? "pointer" : onHead || py < RULER ? "ew-resize" : b ? "pointer" : "default";
    const gx = py < RULER && !onHead && !b ? px : null;
    if (gx !== ghostX || onHead !== onHeadNow) { ghostX = gx; onHeadNow = onHead; request(); }
    if (!sameHit(b, hover)) { hover = b; request(); }
    showTip(b, px, py);
  });
  const endDrag = () => {
    drag = null;
    app.scrubbing = false;
    if (pressed) { pressed = null; request(); }
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("pointerleave", () => { hover = null; ghostX = null; onHeadNow = false; hideTip(); request(); });
  main.addEventListener("pointermove", (e) => { pointerX = local(e).px; });
  main.addEventListener("pointerleave", () => { pointerX = null; });
  canvas.addEventListener("focus", request);
  canvas.addEventListener("blur", request);

  main.addEventListener("wheel", (e) => {
    e.preventDefault();
    hideTip();
    const { px } = local(e);
    if (e.ctrlKey || e.metaKey) {
      zoomTo(pps * Math.exp(-e.deltaY * 0.0022), px);
      return;
    }
    const dx = e.shiftKey ? e.deltaY : e.deltaX;
    const dy = e.shiftKey ? 0 : e.deltaY;
    if (Math.abs(dx) > 0 || !maxScrollY()) {
      scrollT = clamp(scrollT + (dx || dy) / pps, 0, maxScroll());
      if (scrollT > 0) fit = false;
    } else {
      scrollY += dy;
    }
    clampScroll();
    request();
  }, { passive: false });

  // ---------------------------------------------------------------- scrollbars
  function thumbDrag(thumb, onMove) {
    thumb.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      thumb.setPointerCapture(e.pointerId);
      thumb.classList.add("is-dragging");
      const start = { x: e.clientX, y: e.clientY, t: scrollT, sy: scrollY };
      const move = (ev) => { onMove(ev, start); clampScroll(); request(); };
      const up = () => {
        thumb.classList.remove("is-dragging");
        thumb.removeEventListener("pointermove", move);
        thumb.removeEventListener("pointerup", up);
        thumb.removeEventListener("pointercancel", up);
      };
      thumb.addEventListener("pointermove", move);
      thumb.addEventListener("pointerup", up);
      thumb.addEventListener("pointercancel", up);
    });
  }
  thumbDrag(hthumb, (ev, s) => {
    const bw = hbar.clientWidth - 148 - hthumb.offsetWidth;
    scrollT = clamp(s.t + ((ev.clientX - s.x) / Math.max(1, bw)) * maxScroll(), 0, maxScroll());
    fit = false;
  });
  thumbDrag(vthumb, (ev, s) => {
    const track = vbar.clientHeight - vthumb.offsetHeight;
    scrollY = s.sy + ((ev.clientY - s.y) / Math.max(1, track)) * maxScrollY();
  });
  hbar.addEventListener("pointerdown", (e) => {
    if (e.target !== hbar) return;
    const r = hbar.getBoundingClientRect();
    const frac = (e.clientX - r.left - 148) / Math.max(1, r.width - 148);
    scrollT = clamp(frac * (dur() + 24 / pps) - W / pps / 2, 0, maxScroll());
    fit = false;
    clampScroll();
    request();
  });
  vbar.addEventListener("pointerdown", (e) => {
    if (e.target !== vbar) return;
    const r = vbar.getBoundingClientRect();
    scrollY = ((e.clientY - r.top) / r.height) * maxScrollY();
    clampScroll();
    request();
  });

  // ---------------------------------------------------------------- keyboard: clips as controls
  const clipRows = () => rows.filter((r) => r.track && r.track.kind !== "captions" && r.track.clips.length);
  function nearest(r, time) {
    const placed = placeAll(r.track.clips);
    return placed.find((p) => time >= p.start && time < p.end) ||
      placed.slice().sort((a, b) => Math.abs(a.start - time) - Math.abs(b.start - time))[0];
  }
  function rowOf(id) { return rows.findIndex((r) => (r.track?.clips || []).some((c) => c.id === id)); }
  function pick(p) {
    app.select(p.c.id);
    revealSpan(p.start, p.end, rows[rowOf(p.c.id)]);
    request();
  }
  canvas.addEventListener("keydown", (e) => {
    const k = e.key;
    const list = clipRows();
    if (!list.length) return;
    const cur = app.selected ? rowOf(app.selected) : -1;
    const curRow = cur >= 0 ? rows[cur] : null;
    if (k === "ArrowUp" || k === "ArrowDown") {
      let i = curRow ? list.indexOf(curRow) : -1;
      i = clamp(i + (k === "ArrowDown" ? 1 : -1), 0, list.length - 1);
      if (i < 0) i = 0;
      pick(nearest(list[i], app.time));
    } else if (k === "[" || k === "]") {
      const r = curRow || list[0];
      const placed = placeAll(r.track.clips);
      let i = placed.findIndex((p) => p.c.id === app.selected);
      if (i < 0) i = placed.indexOf(nearest(r, app.time)) - (k === "]" ? 1 : -1);
      i = clamp(i + (k === "]" ? 1 : -1), 0, placed.length - 1);
      pick(placed[i]);
    } else if (k === "Enter" && app.selected) {
      const c = app.clipById(app.selected);
      if (c?.start != null) app.seek(c.start);
      chooseClip({ clip: c, ghost: c?.start == null });
    } else if (k === "Escape" && app.selected && !app.viewing) {
      app.select(null);
    } else return;
    e.preventDefault();
    e.stopPropagation();
  });

  // ---------------------------------------------------------------- follow
  function keepPlayheadInView() {
    const px = x(app.time);
    if (px > W * 0.92 || px < 0) {
      scrollT = clamp(app.time - (W * 0.1) / pps, 0, maxScroll());
      clampScroll();
    }
  }
  function revealSpan(s, e, row) {
    const ph = app.time;
    const lo = Math.min(s, ph), hi = Math.max(Math.min(e, s + W / pps * 0.7), ph);
    if (x(s) < 0 || x(Math.min(e, s + W / pps)) > W || x(ph) < 0 || x(ph) > W) {
      // both the change and the playhead when they fit together, else the change
      scrollT = hi - lo < (W * 0.8) / pps ? clamp(lo - (W * 0.1) / pps, 0, maxScroll()) : clamp(s - (W * 0.2) / pps, 0, maxScroll());
      fit = false;
    }
    if (row && (row.y - scrollY < RULER || row.y + row.h - scrollY > H)) scrollY = row.y - RULER - 4;
    clampScroll();
  }
  function changedClips(ids) {
    const out = [];
    for (const r of rows) for (const c of r.track?.clips || []) if (ids.has(c.id)) out.push({ c, r });
    return out;
  }

  // ---------------------------------------------------------------- hooks
  app.on("view", ({ changed, live } = {}) => {
    buildRows();
    if (fit) doFit(); else clampScroll();
    if (live && changed?.size && app.follow && !app.viewing) {
      const list = changedClips(changed).filter((w) => w.c.start != null).sort((a, b) => a.c.start - b.c.start);
      const first = list[0];
      if (first) {
        const at = first.c.start + Math.min(0.3, (first.c.end - first.c.start) / 2);
        if (app.playing || app.scrubbing) app.emit("pending-change", { at });
        else {
          app.seek(at, "follow");
          revealSpan(first.c.start, first.c.end, first.r);
        }
      }
    }
    request();
  });
  app.on("time", (origin) => {
    if (origin !== "scrub" && (app.playing ? app.follow : true)) keepPlayheadInView();
    request();
  });
  app.on("select", (id) => {
    if (id) {
      const ri = rowOf(id);
      const c = app.clipById(id);
      const span = c ? placeAll(rows[ri]?.track.clips || []).find((p) => p.c.id === id) : null;
      if (span && (x(span.end) < 0 || x(span.start) > W)) revealSpan(span.start, span.end, rows[ri]);
    }
    request();
  });
  app.on("state", () => { buildMarks(); request(); });

  new ResizeObserver(resize).observe(main);
  readColors();

  return {
    zoomIn: () => zoomStep(1),
    zoomOut: () => zoomStep(-1),
    fit: () => { doFit(); request(); },
    redraw: request,
    naturalHeight: () => BAR_H + RULER + (rows.length ? contentH() : 120) + HBAR_H + 6
      + (document.getElementById("errorBanner").hidden ? 0 : 44),
  };
}
