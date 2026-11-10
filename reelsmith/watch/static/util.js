// m:ss.ff where ff is the frame within the second.
export function timecode(t, fps) {
  const f = Math.max(0, Math.round(t * fps));
  const sec = Math.floor(f / fps);
  const ff = f - sec * fps;
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}.${String(ff).padStart(2, "0")}`;
}

export function seconds(t, digits = 2) {
  return `${(+t).toFixed(digits)} s`;
}

export function clock(ts) {
  if (!ts) return "";
  const m = /T(\d\d:\d\d:\d\d)/.exec(ts);
  return m ? m[1] : ts;
}

export function bytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Muted per-type colours, read from CSS so the stylesheet owns the palette.
export function typeColor(type) {
  return css(`--clip-${type}`) || css("--clip-shape");
}

export function debounce(fn, ms) {
  let id = 0;
  return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); };
}

export function writtenText(w) {
  if (!w) return "";
  return [w.start != null ? `start ${w.start}` : null, w.end != null ? (String(w.end).startsWith("dur") ? w.end : `end ${w.end}`) : null]
    .filter(Boolean).join(" -> ");
}

export function storage(key, fallback) {
  try { const v = localStorage.getItem("rs-watch:" + key); return v == null ? fallback : JSON.parse(v); }
  catch { return fallback; }
}

export function store(key, value) {
  try { localStorage.setItem("rs-watch:" + key, JSON.stringify(value)); } catch { /* private window */ }
}
