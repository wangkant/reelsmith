import { t } from "./i18n.js";
import { clamp, css, h, timecode, typeColor, writtenText } from "./util.js";

const RULER = 40;
const ROW = { narration: 40, visual: 52, audio: 40, captions: 30 };
const MAX_PPS = 480;
const FLASH_MS = 1600;

// The timeline is one canvas drawn from the view (the live cut or a history snapshot); only the visible span is drawn.
export function createTimeline(app) {
  const main = document.getElementById("tlMain");
  const canvas = document.getElementById("tlCanvas");
  const ctx = canvas.getContext("2d");
  const heads = document.getElementById("tlHeads");
  const tip = document.getElementById("tlTip");
  const empty = document.getElementById("tlEmpty");
  const hbar = document.getElementById("tlHbar");
  const hthumb = document.getElementById("tlHthumb");
  const zoomLabel = document.getElementById("zoomLabel");

  let W = 0, H = 0, dpr = 1;
  let pps = 40, scrollT = 0, scrollY = 0, fit = true;
  let rows = [];
  let hits = [];
  let hover = null;
  let raf = 0;
  const images = new Map();
  const waves = new Map();
  let colors = {};

  function readColors() {
    colors = {
      bg: css("--tl-bg"), row: css("--tl-row"), rowAlt: css("--tl-row-alt"), line: css("--line"), text: css("--text"),
      dim: css("--text-dim"), faint: css("--text-faint"), accent: css("--accent"), ruler: css("--tl-ruler"),
      error: css("--error"), warning: css("--warning"), advice: css("--advice"), voice: css("--clip-voice"),
      caption: css("--clip-caption"), marker: css("--marker"),
    };
  }

  // ---------------------------------------------------------------- geometry
  const view = () => app.view();
  const dur = () => Math.max(view().duration || 0, 0.001);
  const x = (sec) => (sec - scrollT) * pps;
  const tAt = (px) => scrollT + px / pps;
  const fitPps = () => Math.max(1e-3, (W - 24) / Math.max(dur(), 1));
  const minPps = () => Math.min(fitPps(), 4);
  const maxScroll = () => Math.max(0, dur() + 24 / pps - W / pps);
  const contentH = () => rows.reduce((s, r) => s + r.h, 0);

  function buildRows() {
    const v = view();
    rows = [];
    if (v.voice) rows.push({ kind: "narration", h: ROW.narration, id: "voice" });
    for (const tr of v.tracks || []) rows.push({ kind: tr.kind, h: ROW[tr.kind] || ROW.visual, track: tr, id: tr.id });
    let y = RULER;
    for (const r of rows) { r.y = y; y += r.h; }
    renderHeads();
    empty.hidden = !(v.valid !== false && !(v.tracks || []).length);
  }

  function renderHeads() {
    heads.replaceChildren(h("div", { class: "tl-head-ruler" }));
    const inner = h("div", { class: "tl-head-rows" });
    for (const r of rows) {
      const name = r.kind === "narration" ? t("tl.narration") : r.track.id;
      const kind = r.kind === "narration" ? "" : t(`kind.${r.kind}`);
      const n = r.track ? (r.track.kind === "captions" ? (r.track.items || []).length : r.track.clips.length) : (view().voice?.lines.length || 0);
      inner.append(h("div", { class: `tl-head k-${r.kind}${r.track?.hidden ? " is-hidden" : ""}`, style: { height: `${r.h}px` } },
        h("span", { class: "tl-head-swatch" }),
        h("span", { class: "tl-head-text" },
          h("span", { class: "tl-head-name", text: name, title: name }),
          h("span", { class: "tl-head-kind", text: [kind, String(n), r.track?.hidden ? t("tl.hidden") : null].filter(Boolean).join(" · ") }))));
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
    pps = clamp(pps, minPps(), MAX_PPS);
    scrollT = clamp(scrollT, 0, maxScroll());
    scrollY = clamp(scrollY, 0, Math.max(0, contentH() + RULER - H + 8));
    syncHeads();
    updateBar();
  }

  function doFit() {
    fit = true;
    pps = fitPps();
    scrollT = 0;
    clampScroll();
  }

  function zoom(factor, anchorPx = null) {
    const ax = anchorPx ?? clamp(x(app.time), 0, W);
    const at = tAt(ax);
    pps = clamp(pps * factor, minPps(), MAX_PPS);
    fit = Math.abs(pps - fitPps()) < 0.5;
    scrollT = at - ax / pps;
    clampScroll();
    request();
  }

  function updateBar() {
    const total = dur() + 24 / pps;
    const vis = W / pps;
    const show = vis < total - 1e-6;
    hbar.classList.toggle("off", !show);
    const bw = hbar.clientWidth;
    const tw = Math.max(32, (vis / total) * bw);
    hthumb.style.width = `${tw}px`;
    hthumb.style.transform = `translateX(${maxScroll() ? (scrollT / maxScroll()) * (bw - tw) : 0}px)`;
    zoomLabel.textContent = `${Math.round((pps / fitPps()) * 100)}%`;
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

  // ---------------------------------------------------------------- drawing
  function request() {
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); });
  }

  function rr(x0, y0, w, hh, r) {
    ctx.beginPath();
    ctx.roundRect(x0, y0, w, hh, Math.min(r, w / 2, hh / 2));
  }

  function text(str, x0, y0, maxW, font, color) {
    if (maxW < 12) return;
    ctx.font = font;
    ctx.fillStyle = color;
    let s = str;
    if (ctx.measureText(s).width > maxW) {
      let lo = 0, hi = s.length;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (ctx.measureText(s.slice(0, mid) + "…").width <= maxW) lo = mid; else hi = mid - 1;
      }
      s = lo ? s.slice(0, lo) + "…" : "";
    }
    if (s) ctx.fillText(s, x0, y0);
  }

  function niceStep(minPx) {
    const steps = [1 / 30, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    return steps.find((s) => s * pps >= minPx) || 600;
  }
  function rulerLabel(sec, step) {
    const m = Math.floor(sec / 60), s = sec - m * 60;
    const ss = step < 1 ? s.toFixed(step < 0.1 ? 2 : 1).padStart(step < 0.1 ? 5 : 4, "0") : String(Math.round(s)).padStart(2, "0");
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
    const filmEnd = x(dur());
    let flashing = false;
    const dim = app.dimmed();

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, RULER, W, H - RULER);
    ctx.clip();
    ctx.translate(0, -scrollY);
    if (dim) ctx.globalAlpha = 0.32;

    rows.forEach((r, i) => {
      if (r.y + r.h < scrollY + RULER || r.y > scrollY + H) return;
      ctx.fillStyle = i % 2 ? colors.rowAlt : colors.row;
      ctx.fillRect(0, r.y, W, r.h);
      ctx.fillStyle = colors.line;
      ctx.fillRect(0, r.y + r.h - 1, W, 1);
    });
    // Past the film's end.
    if (filmEnd < W) {
      ctx.fillStyle = "rgba(0,0,0,0.28)";
      ctx.fillRect(Math.max(0, filmEnd), RULER, W, contentH() + scrollY);
    }

    for (const r of rows) {
      if (r.y + r.h < scrollY + RULER || r.y > scrollY + H) continue;
      const alpha = r.track?.hidden ? 0.4 : 1;
      ctx.globalAlpha = alpha * (dim ? 0.32 : 1);
      if (r.kind === "narration") drawNarration(r, t0, t1);
      else if (r.kind === "captions") drawCaptions(r, t0, t1);
      else for (const c of r.track.clips) {
        if (c.end < t0 || c.start > t1) continue;
        flashing = drawClip(c, r, now) || flashing;
      }
      ctx.globalAlpha = dim ? 0.32 : 1;
    }
    ctx.restore();

    drawRuler(t0, t1, v);
    drawPlayhead();
    if (flashing) request();
  }

  function clipRect(c, r) {
    const x0 = x(c.start), x1 = x(c.end);
    return { x: x0, y: r.y + 4, w: Math.max(2, x1 - x0), h: r.h - 8 };
  }

  function drawClip(c, r, now) {
    const b = clipRect(c, r);
    const base = typeColor(c.type);
    const sel = app.selected === c.id;
    const isHover = hover?.clip === c;
    ctx.save();
    rr(b.x, b.y, b.w, b.h, 4);
    ctx.fillStyle = base;
    ctx.fill();
    ctx.clip();

    if (r.kind === "visual" && c.thumb && b.w > 24) {
      const img = image(`${c.thumb}${c.thumb.includes("?") ? "&" : "?"}h=72`);
      if (img) {
        const th = b.h - 16;
        const tw = (img.naturalWidth / img.naturalHeight) * th;
        ctx.globalAlpha *= 0.62;
        const left = Math.max(b.x, -tw);
        const startX = b.x + Math.floor((left - b.x) / (tw + 2)) * (tw + 2);
        for (let px = startX; px < Math.min(b.x + b.w, W); px += tw + 2) ctx.drawImage(img, px, b.y + 16, tw, th);
        ctx.globalAlpha /= 0.62;
      }
    }
    if (r.kind === "audio" && c.asset) drawWave(c, b, "rgba(255,255,255,0.42)");

    // Label strip.
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.fillRect(b.x, b.y, b.w, 16);
    const lx = Math.max(b.x, 0) + 6;
    const badges = badgesOf(c);
    let bw = 0;
    ctx.font = "600 10px system-ui, sans-serif";
    for (const s of badges) bw += ctx.measureText(s).width + 10;
    const room = b.x + b.w - lx - 6;
    const showBadges = room > bw + 50;
    text(c.label || c.id, lx, b.y + 12, room - (showBadges ? bw : 0), "500 11px system-ui, 'Segoe UI', 'Microsoft YaHei UI', sans-serif", "#f2f3f5");
    if (r.kind === "visual" && c.label !== c.id && b.h > 34 && !c.thumb) {
      text(c.id, lx, b.y + 30, room, "11px ui-monospace, Consolas, monospace", "rgba(242,243,245,0.72)");
    }
    if (showBadges) {
      let bx = b.x + b.w - 6;
      for (const s of badges.slice().reverse()) {
        ctx.font = "600 10px system-ui, sans-serif";
        const w = ctx.measureText(s).width + 8;
        bx -= w;
        if (bx < lx + 40) break;
        rr(bx, b.y + 2, w, 12, 3);
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        ctx.fill();
        ctx.fillStyle = "#e9eaee";
        ctx.fillText(s, bx + 4, b.y + 11);
        bx -= 3;
      }
    }

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
    // Keyframes as diamonds.
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
    ctx.restore();

    // Transition: the overlap with the previous clip, drawn as a crossed band.
    if (c.transition?.dur) {
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

    // Outline: selection, hover, recent change.
    const changed = app.changedAt(c.id);
    let flashing = false;
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
    if (sel || isHover) {
      rr(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1, 4);
      ctx.strokeStyle = sel ? colors.accent : "rgba(255,255,255,0.55)";
      ctx.lineWidth = sel ? 2 : 1;
      ctx.stroke();
      ctx.lineWidth = 1;
    }
    hits.push({ ...b, y: b.y - scrollY, clip: c, track: r.track });
    return flashing;
  }

  function badgesOf(c) {
    const out = [];
    if (c.rate != null && c.rate !== 1) out.push(`${+c.rate.toFixed(2)}×`);
    if (c.reverse) out.push("rev");
    if (c.hold != null) out.push("freeze");
    if (c.muted) out.push("mute");
    else if (c.type === "audio" && c.volume != null && c.volume !== 1) out.push(`vol ${c.volume}`);
    if (c.loop) out.push("loop");
    return out;
  }

  function drawWave(c, b, color) {
    const d = wave(c.asset);
    if (!d || !d.peaks?.length) return;
    const rate = c.rate || 1;
    const trim = +(c.raw?.trim_in || 0);
    const per = d.peaks.length / Math.max(d.duration, 1e-3);
    const mid = b.y + 16 + (b.h - 16) / 2, amp = (b.h - 20) / 2;
    ctx.fillStyle = color;
    const xs = Math.max(b.x, 0), xe = Math.min(b.x + b.w, W);
    for (let px = xs; px < xe; px += 2) {
      let src = (tAt(px) - c.start) * rate + trim;
      if (c.loop && d.duration) src %= d.duration;
      const i = Math.floor(src * per);
      if (i < 0 || i >= d.peaks.length) continue;
      const p = (d.peaks[i] / d.max) * amp;
      ctx.fillRect(px, mid - p, 1.2, Math.max(1, p * 2));
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
      drawWave({ asset: v.asset || "voice", start: 0, rate: 1, raw: {} }, { x: x0, y: b.y - 6, w, h: b.h + 6 }, "rgba(255,255,255,0.22)");
      text(`${ln.i}  ${ln.text}`, Math.max(x0, 0) + 6, b.y + 13, x0 + w - Math.max(x0, 0) - 10,
        "500 11px system-ui, 'Segoe UI', 'Microsoft YaHei UI', sans-serif", "#f3efe6");
      ctx.restore();
      const hb = { x: x0, y: b.y - scrollY, w, h: b.h, line: ln };
      hits.push(hb);
      if (hover?.line === ln) { rr(x0 + 0.5, b.y + 0.5, w - 1, b.h - 1, 4); ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.stroke(); }
    }
  }

  function drawCaptions(r, t0, t1) {
    for (const it of r.track.items || []) {
      if (it.end < t0 || it.start > t1) continue;
      const x0 = x(it.start), w = Math.max(2, x(it.end) - x0 - 1);
      ctx.save();
      rr(x0, r.y + 5, w, r.h - 10, 3);
      ctx.fillStyle = colors.caption;
      ctx.fill();
      ctx.clip();
      text(it.text, Math.max(x0, 0) + 5, r.y + r.h / 2 + 4, x0 + w - Math.max(x0, 0) - 8,
        "11px system-ui, 'Segoe UI', 'Microsoft YaHei UI', sans-serif", "#efeaf5");
      ctx.restore();
      hits.push({ x: x0, y: r.y + 5 - scrollY, w, h: r.h - 10, item: it, track: r.track });
      if (hover?.item === it) { rr(x0 + 0.5, r.y + 5.5, w - 1, r.h - 11, 3); ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.stroke(); }
    }
  }

  function drawRuler(t0, t1, v) {
    ctx.fillStyle = colors.ruler;
    ctx.fillRect(0, 0, W, RULER);
    ctx.fillStyle = colors.line;
    ctx.fillRect(0, RULER - 1, W, 1);
    const major = niceStep(84);
    const minorDiv = major >= 60 ? 6 : major >= 10 ? 5 : major >= 1 ? (major === 2 ? 4 : 5) : 5;
    const minor = major / minorDiv;
    ctx.font = "11px ui-monospace, 'Cascadia Mono', Consolas, monospace";
    const first = Math.floor(t0 / minor) * minor;
    for (let s = first; s <= t1 + minor; s += minor) {
      if (s < -1e-9) continue;
      const px = Math.round(x(s)) + 0.5;
      const isMajor = Math.abs(s / major - Math.round(s / major)) < 1e-6;
      ctx.fillStyle = isMajor ? colors.dim : colors.faint;
      ctx.fillRect(px, isMajor ? RULER - 12 : RULER - 6, 1, isMajor ? 11 : 5);
      if (isMajor) {
        ctx.fillStyle = colors.dim;
        ctx.fillText(rulerLabel(Math.round(s * 1000) / 1000, major), px + 4, RULER - 15);
      }
    }
    // Film end.
    const ex = x(dur());
    if (ex >= 0 && ex <= W) { ctx.fillStyle = colors.dim; ctx.fillRect(Math.round(ex), 16, 1, RULER - 16); }

    // Chapters and markers as flags along the top band.
    ctx.font = "500 10px system-ui, 'Segoe UI', 'Microsoft YaHei UI', sans-serif";
    const chapters = v.chapters || [];
    chapters.forEach((c, i) => {
      const px = x(c.t);
      const next = chapters[i + 1] ? x(chapters[i + 1].t) : W;
      if (next < 0 || px > W) return;
      ctx.fillStyle = colors.marker;
      ctx.fillRect(Math.round(px), 2, 1, 13);
      ctx.beginPath(); ctx.moveTo(px, 2); ctx.lineTo(px + 6, 5); ctx.lineTo(px, 8); ctx.fill();
      text(c.title, px + 9, 12, next - px - 14, ctx.font, colors.dim);
      hits.push({ x: px - 3, y: 0, w: 12, h: 16, chapter: c, ruler: true });
    });
    for (const m of v.markers || []) {
      const px = x(m.t);
      if (px < -4 || px > W + 4) continue;
      ctx.fillStyle = colors.accent;
      ctx.beginPath(); ctx.moveTo(px - 4, 2); ctx.lineTo(px + 4, 2); ctx.lineTo(px + 4, 9); ctx.lineTo(px, 13); ctx.lineTo(px - 4, 9); ctx.fill();
      hits.push({ x: px - 5, y: 0, w: 10, h: 16, marker: m, ruler: true });
    }
    // Issues with a time, along the bottom of the ruler.
    for (const is of v.issues || []) {
      if (is.t == null) continue;
      const px = x(is.t);
      if (px < -5 || px > W + 5) continue;
      ctx.fillStyle = colors[is.level] || colors.dim;
      ctx.beginPath(); ctx.moveTo(px - 5, RULER - 1); ctx.lineTo(px + 5, RULER - 1); ctx.lineTo(px, RULER - 8); ctx.fill();
      hits.push({ x: px - 6, y: RULER - 10, w: 12, h: 10, issue: is, ruler: true });
    }
  }

  function drawPlayhead() {
    const px = Math.round(x(app.time)) + 0.5;
    if (px < -8 || px > W + 8) return;
    ctx.fillStyle = colors.accent;
    ctx.fillRect(px - 0.5, 16, 1.5, H - 16);
    ctx.beginPath();
    ctx.moveTo(px - 6, 16); ctx.lineTo(px + 6, 16); ctx.lineTo(px + 6, 24); ctx.lineTo(px, 30); ctx.lineTo(px - 6, 24);
    ctx.closePath();
    ctx.fill();
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

  function showTip(b, px, py) {
    if (!b) { tip.hidden = true; return; }
    const fps = app.fps();
    const tc = (s) => timecode(s, fps);
    let lines;
    if (b.clip) {
      const c = b.clip;
      lines = [[`${c.id}`, `${c.type} · ${b.track.id}`], [`${tc(c.start)} – ${tc(c.end)}`, `${(c.end - c.start).toFixed(2)} s`],
        [writtenText(c.written), ""]];
      if (c.label && c.label !== c.id) lines.splice(1, 0, [c.label, ""]);
    } else if (b.line) {
      lines = [[`${t("tl.narration")} · line:${b.line.i}`, ""], [`${tc(b.line.start)} – ${tc(b.line.end)}`, ""], [b.line.text, ""]];
    } else if (b.item) {
      lines = [[b.item.text, b.item.line ? `line:${b.item.line}` : ""], [`${tc(b.item.start)} – ${tc(b.item.end)}`, ""]];
    } else if (b.issue) {
      lines = [[`${b.issue.level}${b.issue.clip ? " · " + b.issue.clip : ""}`, tc(b.issue.t)], [b.issue.text, ""]];
    } else if (b.marker) {
      lines = [[b.marker.id, tc(b.marker.t)]];
    } else if (b.chapter) {
      lines = [[b.chapter.title, tc(b.chapter.t)]];
    }
    tip.replaceChildren(...lines.filter((l) => l[0]).map(([a, z], i) =>
      h("div", { class: i === 0 ? "tip-head" : "tip-row" }, h("span", { text: a }), z ? h("span", { class: "tip-aside", text: z }) : null)));
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    tip.style.left = `${clamp(px + 14, 4, W - tw - 4)}px`;
    tip.style.top = `${py + 18 + th > H ? Math.max(4, py - th - 10) : py + 18}px`;
  }

  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    canvas.focus({ preventScroll: true });
    const { px, py } = local(e);
    const onHead = Math.abs(px - x(app.time)) <= 6;
    const b = hitAt(px, py);
    if (py < RULER || onHead) {
      if (b?.issue && !onHead) { app.openIssue(b.issue); return; }
      drag = { scrub: true };
      canvas.setPointerCapture(e.pointerId);
      app.seek(tAt(px), "scrub");
      return;
    }
    if (b?.clip) app.select(b.clip.id);
    app.seek(clamp(tAt(px), 0, dur()), "scrub");
    drag = { scrub: true };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    const { px, py } = local(e);
    if (drag?.scrub) {
      app.seek(clamp(tAt(px), 0, dur()), "scrub");
      if (px > W - 20) { scrollT = clamp(scrollT + 8 / pps, 0, maxScroll()); fit = false; updateBar(); }
      if (px < 20) { scrollT = clamp(scrollT - 8 / pps, 0, maxScroll()); fit = false; updateBar(); }
      tip.hidden = true;
      return;
    }
    const b = hitAt(px, py);
    const onHead = Math.abs(px - x(app.time)) <= 6;
    canvas.style.cursor = onHead || py < RULER ? "ew-resize" : b ? "pointer" : "default";
    if (b !== hover && (b?.clip !== hover?.clip || b?.line !== hover?.line || b?.item !== hover?.item)) { hover = b; request(); }
    showTip(b, px, py);
  });
  canvas.addEventListener("pointerup", () => { drag = null; });
  canvas.addEventListener("pointercancel", () => { drag = null; });
  canvas.addEventListener("pointerleave", () => { hover = null; tip.hidden = true; request(); });

  function local(e) {
    const r = canvas.getBoundingClientRect();
    return { px: e.clientX - r.left, py: e.clientY - r.top };
  }

  main.addEventListener("wheel", (e) => {
    e.preventDefault();
    const { px } = local(e);
    if (e.ctrlKey || e.metaKey) {
      zoom(Math.exp(-e.deltaY * 0.0022), px);
      return;
    }
    const dx = e.shiftKey ? e.deltaY : e.deltaX;
    const dy = e.shiftKey ? 0 : e.deltaY;
    const canV = contentH() + RULER > H;
    if (Math.abs(dx) > 0 || !canV) {
      scrollT = clamp(scrollT + (dx || dy) / pps, 0, maxScroll());
      if (scrollT > 0) fit = false;
    } else {
      scrollY += dy;
    }
    clampScroll();
    request();
  }, { passive: false });

  // Horizontal scrollbar.
  hthumb.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    hthumb.setPointerCapture(e.pointerId);
    const startX = e.clientX, start = scrollT;
    const bw = hbar.clientWidth - hthumb.offsetWidth;
    const move = (ev) => {
      scrollT = clamp(start + ((ev.clientX - startX) / Math.max(1, bw)) * maxScroll(), 0, maxScroll());
      fit = false;
      clampScroll();
      request();
    };
    const up = () => { hthumb.removeEventListener("pointermove", move); hthumb.removeEventListener("pointerup", up); };
    hthumb.addEventListener("pointermove", move);
    hthumb.addEventListener("pointerup", up);
  });
  hbar.addEventListener("pointerdown", (e) => {
    if (e.target !== hbar) return;
    const r = hbar.getBoundingClientRect();
    scrollT = clamp(((e.clientX - r.left) / r.width) * (dur() + 24 / pps) - W / pps / 2, 0, maxScroll());
    fit = false;
    clampScroll();
    request();
  });

  // ---------------------------------------------------------------- follow
  function keepPlayheadInView() {
    const px = x(app.time);
    if (px > W * 0.92 || px < 0) {
      scrollT = clamp(app.time - (W * 0.1) / pps, 0, maxScroll());
      clampScroll();
    }
  }

  function reveal(ids) {
    const want = [];
    for (const r of rows) for (const c of r.track?.clips || []) if (ids.has(c.id)) want.push({ c, r });
    if (!want.length) return;
    const s = Math.min(...want.map((w) => w.c.start)), e = Math.max(...want.map((w) => w.c.end));
    if (x(s) < 0 || x(Math.min(e, s + W / pps)) > W) {
      scrollT = clamp(s - (W * 0.2) / pps, 0, maxScroll());
    }
    const r = want[0].r;
    if (r.y - scrollY < RULER || r.y + r.h - scrollY > H) scrollY = r.y - RULER - 8;
    clampScroll();
  }

  // ---------------------------------------------------------------- hooks
  app.on("view", ({ changed } = {}) => {
    buildRows();
    if (fit) doFit(); else clampScroll();
    if (changed?.size && app.follow) reveal(changed);
    request();
  });
  app.on("time", (origin) => {
    if (origin !== "scrub" && (app.playing ? app.follow : true)) keepPlayheadInView();
    request();
  });
  app.on("select", (id) => {
    if (id && app.follow) {
      const ids = new Set([id]);
      const inView = rows.some((r) => (r.track?.clips || []).some((c) => c.id === id && x(c.end) > 0 && x(c.start) < W));
      if (!inView) reveal(ids);
    }
    request();
  });

  new ResizeObserver(resize).observe(main);
  readColors();

  return {
    zoomIn: () => zoom(1.5),
    zoomOut: () => zoom(1 / 1.5),
    fit: () => { doFit(); request(); },
    redraw: request,
  };
}
