// m:ss.hh: hundredths of a second, snapped to a frame first so the readout matches the picture.
export function timecode(t, fps) {
  const f = Math.max(0, Math.round((+t || 0) * fps));
  const cs = Math.round((f / fps) * 100);
  const sec = Math.floor(cs / 100);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
}

// m:ss for lengths a person reads at a glance.
export function shortTime(t) {
  const s = Math.round(+t || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// 34 s, then 1:05 past a minute.
export function elapsed(sec) {
  const s = Math.max(0, Math.floor(sec));
  return s < 60 ? `${s} s` : shortTime(s);
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
    else if (k === "style" && typeof v === "object") for (const [sk, sv] of Object.entries(v)) el.style.setProperty(sk.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`), sv);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

// A Lucide icon from the sprite in index.html.
export function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#${name}`);
  s.append(u);
  return s;
}

// "Rendering the film" inside a sentence: "The agent is rendering the film".
// German capitalises its nouns, so a name set mid-sentence keeps its capital there
export const lowerFirst = (s) => (/^[A-Z][a-z]/.test(s) && !/^de/.test(document.documentElement.lang) ? s[0].toLowerCase() + s.slice(1) : s);

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Per-type colours, read from CSS so the stylesheet owns the palette.
export function typeColor(type) {
  return css(`--clip-${type}`) || css("--clip-shape");
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
  try {
    if (value == null) localStorage.removeItem("rs-watch:" + key);
    else localStorage.setItem("rs-watch:" + key, JSON.stringify(value));
  } catch { /* private window */ }
}

// ---------------------------------------------------------------- controls
// The tooltip text, its shortcut key, and the accessible name of an icon-only control in one place.
export function tip(el, text, key = null, name = text) {
  el.dataset.tip = text || "";
  if (key != null) el.dataset.key = key;
  if (!el.textContent.trim() || el.tagName === "INPUT") el.setAttribute("aria-label", name || "");
  if (current === el) showTip(el);
}

// aria-disabled instead of disabled, so the control keeps its tooltip and says why it does nothing.
export function disable(el, why, base, key = null) {
  el.setAttribute("aria-disabled", String(!!why));
  tip(el, why || base, key, base);
  if (why) el.setAttribute("aria-description", why); else el.removeAttribute("aria-description");
}
export const isOff = (el) => el.getAttribute("aria-disabled") === "true";

export function busy(el, on) {
  el.classList.toggle("is-busy", !!on);
  el.setAttribute("aria-busy", String(!!on));
}

// A short note that appears next to a control and fades: the visible result of a click.
let noteEl = null, noteTimer = 0;
export function note(anchor, text, kind = "") {
  noteEl ||= document.body.appendChild(h("div", { class: "ui-note", role: "status", "aria-live": "polite" }));
  noteEl.textContent = text;
  noteEl.className = `ui-note ${kind}`;
  hideTip();
  const r = anchor.getBoundingClientRect();
  noteEl.hidden = false;
  const w = noteEl.offsetWidth, ht = noteEl.offsetHeight;
  const below = r.bottom + 8 + ht < innerHeight;
  noteEl.style.left = `${clamp(r.left + r.width / 2 - w / 2, 6, innerWidth - w - 6)}px`;
  noteEl.style.top = `${below ? r.bottom + 8 : r.top - ht - 8}px`;
  noteEl.classList.add("is-on");
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => noteEl.classList.remove("is-on"), 1600);
}

// One tooltip for the whole page: after 400 ms of hover or keyboard focus, with the shortcut key when there is one.
// A plain title attribute is taken over on first hover so the browser's own tooltip never doubles it.
let tipEl = null, tipTimer = 0, current = null;
function adopt(el) {
  if (el.hasAttribute("title")) {
    const s = el.getAttribute("title");
    el.removeAttribute("title");
    if (s) {
      el.dataset.tip = s;
      if (!el.hasAttribute("aria-label") && !el.textContent.trim()) el.setAttribute("aria-label", s);
    }
  }
  return el.dataset.tip ? el : null;
}
function showTip(el) {
  tipEl ||= document.body.appendChild(h("div", { class: "ui-tip", role: "tooltip", hidden: true }));
  const text = el.dataset.tip;
  if (!text || !el.isConnected) return hideTip();
  tipEl.replaceChildren(h("span", { text }), ...(el.dataset.key ? [h("kbd", { text: el.dataset.key })] : []));
  tipEl.hidden = false;
  const r = el.getBoundingClientRect();
  const w = tipEl.offsetWidth, ht = tipEl.offsetHeight;
  const below = r.bottom + 8 + ht < innerHeight;
  tipEl.style.left = `${clamp(r.left + r.width / 2 - w / 2, 6, innerWidth - w - 6)}px`;
  tipEl.style.top = `${below ? r.bottom + 8 : Math.max(6, r.top - ht - 8)}px`;
  current = el;
}
export function hideTip() {
  clearTimeout(tipTimer);
  if (tipEl) tipEl.hidden = true;
  current = null;
}
export function installTips() {
  const arm = (el) => {
    clearTimeout(tipTimer);
    if (!el) return hideTip();
    if (current && current !== el) hideTip();
    tipTimer = setTimeout(() => showTip(el), current ? 0 : 400);
  };
  const target = (node) => {
    for (let el = node; el && el !== document.body; el = el.parentElement) {
      if (el.nodeType === 1 && (el.hasAttribute("title") || el.dataset.tip)) return adopt(el);
    }
    return null;
  };
  document.addEventListener("pointerover", (e) => { const el = target(e.target); if (el !== current) arm(el); });
  document.addEventListener("pointerout", (e) => { if (!e.relatedTarget) hideTip(); });
  document.addEventListener("pointerdown", hideTip, true);
  document.addEventListener("focusin", (e) => { if (e.target.matches?.(":focus-visible")) arm(target(e.target)); });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
  addEventListener("blur", hideTip);
}

// A button and its menu of .menu-item buttons: arrows, Home and End move; Escape and Tab close it and return to the
// button; a press outside closes it. `first` picks the item the keyboard lands on.
export function menuButton(btn, menu, first = () => 0) {
  const items = () => [...menu.querySelectorAll(".menu-item")].filter((el) => el.offsetParent !== null);
  function open(focus) {
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    if (focus) items()[first(items())]?.focus();
  }
  function close(refocus) {
    if (menu.hidden) return false;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (refocus) btn.focus();
    return true;
  }
  btn.addEventListener("click", (e) => { menu.hidden ? open(e.detail === 0) : close(false); });
  btn.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { e.preventDefault(); open(true); } });
  menu.addEventListener("keydown", (e) => {
    const list = items(), i = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); list[(i + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length].focus(); }
    else if (e.key === "Home" || e.key === "End") { e.preventDefault(); list[e.key === "Home" ? 0 : list.length - 1].focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); close(true); }
  });
  document.addEventListener("pointerdown", (e) => { if (!btn.parentElement.contains(e.target)) close(false); });
  return { open, close };
}

// A click on the backdrop closes a dialog, but not a press that began inside it and slid off.
export function closeOnBackdrop(dlg) {
  let down = null;
  dlg.addEventListener("pointerdown", (e) => { down = e.target; });
  dlg.addEventListener("click", (e) => { if (e.target === dlg && down === dlg) dlg.close(); down = null; });
}

// Enter and Space on something that is not a native button (a role="button" element) do what a click does.
export function pressable(el, fn) {
  el.addEventListener("click", (e) => { if (!isOff(el)) fn(e); });
  if (el.tagName !== "BUTTON") {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); if (!isOff(el)) fn(e); }
    });
  }
}
