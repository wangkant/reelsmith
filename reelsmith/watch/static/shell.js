// The application's frame: the sidebar every page shares, kept live from /api/app and its event stream.
import { json, postAt } from "./api.js";
import { ago, setupLanguage, setupTheme } from "./chrome.js";
import { has, t } from "./i18n.js";
import { busy, clamp, closeOnBackdrop, h, icon, isOff, note, storage, store, tip } from "./util.js";
import { mountWindowFrame } from "./winframe.js";

// Icons the frame draws; added to the page's sprite when the page does not carry them.
const SPRITE = {
  "i-sidebar": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
  "i-gear": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  "i-timer": '<line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/>',
  "i-trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  "i-search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  "i-book": '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  "i-plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
  "i-more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  "i-stop": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
  "i-folder": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
  "i-copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  "i-pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  "i-close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "i-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  "i-film": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
  "i-tick": '<path d="M20 6 9 17l-5-5"/>',
  "i-chev": '<path d="m6 9 6 6 6-6"/>',
  "i-globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  "i-sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  "i-moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  "i-monitor": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
  "i-okc": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  "i-fail": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
  "i-eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  "i-import": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  "i-arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
};
function addSprite() {
  const need = Object.keys(SPRITE).filter((id) => !document.getElementById(id));
  if (!need.length) return;
  const box = document.createElement("div");
  box.innerHTML = `<svg class="sprite" width="0" height="0" aria-hidden="true">${need.map((id) => `<symbol id="${id}" viewBox="0 0 24 24">${SPRITE[id]}</symbol>`).join("")}</svg>`;
  document.body.prepend(box.firstChild);
}

const enc = encodeURIComponent;
const reason = (e) => (e?.code && has(e.code) ? t(e.code, e.params || {}) : e?.message || String(e));
const typing = (el) => !!el?.closest?.("input, textarea, select, [contenteditable]");
const desktop = () => window.pywebview?.api;
const SIDE_W = 248;

export function mountShell({ page, film = null, beforeReload = () => {}, onTheme = () => {} } = {}) {
  const here = film || (/^\/p\/([^/]+)/.exec(location.pathname) || [])[1];
  const current = here ? decodeURIComponent(here) : null;
  const handlers = {};
  const emit = (ev, d) => (handlers[ev] || []).forEach((fn) => { try { fn(d); } catch (e) { console.error(e); } });
  const S = { app: null, films: [], conn: "connecting", commands: [], rows: new Map(), seenEnded: new Set() };
  const side = document.getElementById("side");
  addSprite();
  mountWindowFrame();
  if (!side) return { on() { return this; }, films: () => [], app: () => null, commands() {}, refresh() {} };

  // ---------------------------------------------------------------- the rail and the width
  const root = document.documentElement;
  root.classList.toggle("side-rail", !!storage("side-rail", false));
  const applyW = (w) => root.style.setProperty("--side-w", `${clamp(w, 200, 400)}px`);
  applyW(storage("side-w", SIDE_W));

  // ---------------------------------------------------------------- the skeleton
  const wsName = h("span", { class: "side-ws-name" });
  const ws = h("div", { class: "side-ws" }, h("span", { class: "mark", "aria-hidden": "true" }, h("i")), wsName);
  const toggle = h("button", { class: "icon-btn side-toggle", type: "button", "aria-keyshortcuts": "Control+B" }, icon("i-sidebar"));
  const item = (href, ic, key, cur, extra = "") => {
    const a = h("a", { class: `side-item${extra}`, href }, icon(ic), h("span", { text: t(key) }), h("span", { class: "spin", "aria-hidden": "true" }));
    if (cur) a.setAttribute("aria-current", "page");
    tip(a, t(key), null, t(key));
    a.addEventListener("click", (e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !cur) busy(a, true); });
    return a;
  };
  const newItem = item("/new", "i-plus", "frame.new", page === "new", " side-new");
  newItem.insertBefore(h("kbd", { text: "N" }), newItem.querySelector(".spin"));
  tip(newItem, t("frame.newTip"), "N", t("frame.new"));
  const findItem = h("button", { class: "side-item side-find", type: "button", "aria-haspopup": "dialog", "aria-keyshortcuts": "Control+K" },
    icon("i-search"), h("span", { text: t("frame.find") }), h("kbd", { text: "Ctrl K" }));
  tip(findItem, t("frame.findTip"), "Ctrl K", t("frame.find"));
  const top = h("nav", { class: "side-top", "aria-label": t("frame.nav") }, newItem, findItem,
    item("/", "i-grid", "frame.films", page === "films"), item("/library", "i-book", "frame.library", page === "library"),
    item("/settings", "i-gear", "frame.settings", page === "settings"));
  const scroll = h("div", { class: "side-scroll", role: "navigation", "aria-label": t("frame.filmsNav") });
  const engine = h("a", { class: "side-engine", href: "/settings#agent" }, h("span", { class: "dot" }), h("span", { class: "label" }), h("span", { class: "work num" }));
  const langBtn = h("button", { class: "btn sm lang-btn", type: "button", "aria-haspopup": "menu", "aria-expanded": "false", "aria-controls": "sideLangMenu" },
    icon("i-globe"), h("span", { class: "lang-name" }), icon("i-chev", "chev"));
  const langMenu = h("div", { class: "menu lang-menu", id: "sideLangMenu", role: "menu", hidden: true });
  const seg = h("div", { class: "seg theme", role: "group" }, ...["light", "dark", "system"].map((p) =>
    h("button", { type: "button", "data-pick": p }, icon({ light: "i-sun", dark: "i-moon", system: "i-monitor" }[p]))));
  const foot = h("div", { class: "side-foot" }, engine, h("div", { class: "side-tools" }, h("div", { class: "menu-wrap" }, langBtn, langMenu), seg));
  const edge = h("div", { class: "side-edge", role: "separator", "aria-orientation": "vertical", tabindex: "0", "aria-valuemin": "200", "aria-valuemax": "400" });
  side.replaceChildren(h("div", { class: "side-head" }, ws, toggle), top, h("div", { class: "side-sep" }), scroll, foot, edge);
  side.setAttribute("aria-label", t("frame.sidebar"));
  setupLanguage(langBtn, langMenu, langBtn.querySelector(".lang-name"), beforeReload);
  setupTheme(seg, () => { onTheme(); emit("theme"); });

  // ---------------------------------------------------------------- rail, width
  function renderToggle() {
    const rail = root.classList.contains("side-rail");
    tip(toggle, t(rail ? "frame.expand" : "frame.collapse"), "Ctrl B");
    toggle.setAttribute("aria-expanded", String(!rail));
  }
  function setRail(on) {
    root.classList.toggle("side-rail", on);
    store("side-rail", on || null);
    renderToggle();
    dispatchEvent(new Event("resize"));
  }
  toggle.addEventListener("click", () => setRail(!root.classList.contains("side-rail")));
  renderToggle();
  const width = () => parseFloat(getComputedStyle(root).getPropertyValue("--side-w")) || SIDE_W;
  function setW(w, keep = true) {
    applyW(w);
    if (keep) store("side-w", Math.round(clamp(w, 200, 400)));
    edge.setAttribute("aria-valuenow", String(Math.round(width())));
    dispatchEvent(new Event("resize"));
  }
  const resetW = () => { store("side-w", null); setW(SIDE_W, false); note(edge, t("frame.resized")); };
  tip(edge, t("frame.resizeTip"), null, t("frame.resize"));
  edge.setAttribute("aria-valuenow", String(Math.round(width())));
  edge.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    edge.setPointerCapture(e.pointerId);
    edge.classList.add("is-dragging");
    document.body.classList.add("is-side-resizing");
    const move = (ev) => setW(ev.clientX);
    const up = () => {
      edge.classList.remove("is-dragging");
      document.body.classList.remove("is-side-resizing");
      edge.removeEventListener("pointermove", move);
      edge.removeEventListener("pointerup", up);
    };
    edge.addEventListener("pointermove", move);
    edge.addEventListener("pointerup", up);
  });
  edge.addEventListener("dblclick", resetW);
  edge.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); setW(width() + (e.key === "ArrowRight" ? 16 : -16)); }
    else if (e.key === "Enter") { e.preventDefault(); resetW(); }
  });

  // ---------------------------------------------------------------- the film rows
  const workText = (w) => {
    if (!w) return t("frame.st.working");
    if (w.stage_code && has(w.stage_code)) return t(w.stage_code, w.stage_params || {});
    const what = w.tool && has(`run.${w.tool}`) ? t(`run.${w.tool}`) : t("frame.st.working");
    return typeof w.percent === "number" ? `${what} · ${w.percent} %` : what;
  };
  function statusOf(f) {
    if (f.status === "working") return { cls: "is-working", text: workText(f.working), mark: "ring" };
    if (f.status === "queued") return { cls: "is-queued", text: t("frame.st.queued", { n: f.queue || 1 }), mark: "queue" };
    const a = (f.attention || [])[0];
    const err = a && /failed|refused/.test(a.code);
    if (f.unread) return { cls: "is-unread", text: f.last?.text || t("frame.st.unread"), mark: "unread" };
    if (a) return { cls: err ? "is-failed" : "is-attention", text: has(a.code) ? t(a.code, a.params || {}) : a.code, mark: err ? "err" : "warn" };
    if (f.empty) return { cls: "", text: t("frame.st.empty"), mark: "idle" };
    return { cls: "", text: f.modified ? t("frame.st.changed", { ago: ago(f.modified) }) : "", mark: "idle" };
  }
  function markEl(kind) {
    if (kind === "ring") return h("span", { class: "ring" });
    if (kind === "queue") return icon("i-timer");
    return h("span", { class: `dot${kind === "unread" ? " is-unread" : kind === "err" ? " is-err" : kind === "idle" ? " is-idle" : ""}` });
  }
  function makeRow(f) {
    const title = h("span", { class: "side-title" }), status = h("span", { class: "side-status" });
    const mark = h("span", { class: "side-mark", "aria-hidden": "true" });
    const letter = h("span", { class: "side-letter", "aria-hidden": "true" });
    const link = h("a", { class: "side-link", href: f.url, "data-name": f.name }, mark, letter, h("span", { class: "side-text" }, title, status));
    const stop = h("button", { class: "icon-btn side-stop", type: "button" }, icon("i-stop"));
    const more = h("button", { class: "icon-btn side-more", type: "button", "aria-haspopup": "menu", "aria-expanded": "false" }, icon("i-more"));
    tip(more, t("frame.row.more"));
    const el = h("div", { class: "side-row", role: "listitem", "data-name": f.name }, link, h("div", { class: "side-acts" }, stop, more));
    const r = { el, link, title, status, mark, letter, stop, more, f, k: "" };
    link.addEventListener("click", (e) => {
      if (el.querySelector(".side-rename")) { e.preventDefault(); return; }
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
      if (r.f.name !== current) busy(el, true);
    });
    link.addEventListener("contextmenu", (e) => { e.preventDefault(); openMenu(r.f, el, { x: e.clientX, y: e.clientY }); });
    stop.addEventListener("click", () => stopFilm(r.f, stop));
    more.addEventListener("click", () => (menuEl?.btn === more ? closeMenu(false) : openMenu(r.f, el, null, more)));
    return r;
  }
  function fillRow(r, f) {
    r.f = f;
    const name = f.title || f.name;
    const st = statusOf(f);
    const k = JSON.stringify([name, st, f.url]);
    if (k === r.k) return;
    r.k = k;
    r.title.textContent = name;
    r.status.textContent = st.text;
    r.letter.textContent = [...name.trim()][0]?.toUpperCase() || "·";
    r.mark.replaceChildren(markEl(st.mark));
    r.el.className = `side-row ${st.cls}`.trim();
    r.link.setAttribute("href", f.url);
    if (f.name === current) r.link.setAttribute("aria-current", "page"); else r.link.removeAttribute("aria-current");
    const said = [name, st.text].filter(Boolean).join(", ");
    tip(r.link, [name, f.title ? f.name : null, st.text].filter(Boolean).join(" · "), null, said);
    r.link.setAttribute("aria-label", said);
    const active = f.status === "working" || f.status === "queued";
    r.stop.hidden = !active;
    tip(r.stop, t(f.status === "queued" ? "frame.row.cancel" : "frame.row.stop"));
    r.el.style.setProperty("--acts-w", active ? "58px" : "30px");
  }
  function groupOf(f) {
    if (f.status === "working" || f.status === "queued") return "active";
    if (f.unread || f.status === "attention") return "attention";
    return "other";
  }
  const groups = Object.fromEntries(["active", "attention", "other"].map((g) => {
    const list = h("div", { class: "side-list", role: "list" });
    const n = h("span", { class: "n" });
    const el = h("section", { class: "side-group" }, h("h3", {}, h("span", { text: t(`frame.group.${g}`) }), n), list);
    return [g, { el, list, n }];
  }));
  const emptyEl = h("p", { class: "side-empty" });
  function renderFilms() {
    const films = S.films;
    for (const [name, r] of S.rows) if (!films.some((f) => f.name === name)) { r.el.remove(); S.rows.delete(name); }
    const by = { active: [], attention: [], other: [] };
    for (const f of films) {
      let r = S.rows.get(f.name);
      if (!r) { r = makeRow(f); S.rows.set(f.name, r); }
      fillRow(r, f);
      by[groupOf(f)].push(r.el);
    }
    const shown = [];
    for (const [g, G] of Object.entries(groups)) {
      if (G.list.children.length !== by[g].length || by[g].some((el, i) => G.list.children[i] !== el)) G.list.replaceChildren(...by[g]);
      G.n.textContent = by[g].length;
      if (by[g].length) shown.push(G.el);
    }
    emptyEl.textContent = S.conn === "failed" ? t("frame.loadFailed") : S.app ? t("frame.empty") : t("frame.loading");
    const want = shown.length ? shown : [emptyEl];
    if (scroll.children.length !== want.length || want.some((el, i) => scroll.children[i] !== el)) scroll.replaceChildren(...want);
    renderFoot();
    renderTitle();
  }
  function renderFoot() {
    const a = S.app;
    const e = a?.engine;
    const label = engine.querySelector(".label"), work = engine.querySelector(".work");
    const lost = S.conn === "reconnecting" || S.conn === "failed";
    engine.classList.toggle("is-off", lost || !e?.available);
    label.textContent = lost ? t("frame.conn.lost") : !a ? t("frame.loading") : e?.available ? e.label || e.id : t("frame.engine.none");
    const c = a?.counts || {};
    work.textContent = [c.working ? t("frame.work.working", { n: c.working }) : "", c.queued ? t("frame.work.queued", { n: c.queued }) : ""].filter(Boolean).join(" · ");
    const why = e && !e.available && e.code && has(e.code) ? t(e.code, e.params || {}) : "";
    tip(engine, lost ? t("frame.conn.lostTip") : [t("frame.engine.tip"), why].filter(Boolean).join(" "), null, label.textContent);
    if (a?.workspace) {
      wsName.textContent = a.workspace.name;
      tip(ws, t("frame.wsTip", { path: a.workspace.path }));
    }
  }
  // the page's own title, with the number of films that have news in front of it
  let baseTitle = document.title, writing = false;
  function renderTitle() {
    const n = S.films.filter((f) => f.unread && f.name !== current).length;
    const want = (n ? `(${n}) ` : "") + baseTitle;
    if (document.title !== want) { writing = true; document.title = want; writing = false; }
    // the desktop window keeps its own name, with the same count in front
    const desk = (n ? `(${n}) ` : "") + `reelsmith · ${S.app?.workspace?.name || ""}`.trim();
    try { desktop()?.set_title?.(desk); } catch { /* a browser tab */ }
  }
  const titleEl = document.querySelector("title") || document.head.appendChild(h("title"));
  new MutationObserver(() => { if (writing) return; baseTitle = document.title.replace(/^\(\d+\) /, ""); renderTitle(); })
    .observe(titleEl, { childList: true, characterData: true, subtree: true });
  setInterval(() => { for (const r of S.rows.values()) { r.k = ""; fillRow(r, r.f); } }, 30000);

  // ---------------------------------------------------------------- the server
  function take(d) {
    S.app = d;
    S.films = d.films || [];
    S.conn = "connected";
    renderFilms();
    emit("app", d);
    emit("films", S.films);
  }
  async function load() {
    try {
      take(await json("/api/app"));
      return true;
    } catch (e) {
      if (e.status === 404) { root.classList.add("no-side"); side.hidden = true; return false; }   // a single film's window
      S.conn = "failed";
      renderFilms();
      return false;
    }
  }
  function stream() {
    let es = null, retry = 0;
    const open = () => {
      es = new EventSource("/api/app/events");
      es.onopen = () => { if (S.conn !== "connected") load(); };
      es.addEventListener("films", (e) => {
        try {
          const d = JSON.parse(e.data);
          const films = Array.isArray(d) ? d : d.films;
          if (!films) return;
          S.conn = "connected";
          S.app = { ...(S.app || {}), films, ...(d.counts ? { counts: d.counts } : {}), ...(d.parallel ? { parallel: d.parallel } : {}) };
          S.films = films;
          renderFilms();
          emit("films", films);
        } catch { /* a partial line */ }
      });
      es.addEventListener("ended", (e) => { try { ended(JSON.parse(e.data)); } catch { /* a partial line */ } });
      es.onerror = () => {
        S.conn = "reconnecting";
        renderFoot();
        if (es.readyState === EventSource.CLOSED) { es.close(); clearTimeout(retry); retry = setTimeout(open, 2000); }
      };
    };
    open();
  }

  // ---------------------------------------------------------------- notices: a request ended in another film
  const notices = h("div", { class: "frame-notices", role: "status", "aria-live": "polite" });
  document.body.append(notices);
  function ended(d) {
    const key = `${d.name}#${d.turn}`;
    if (S.seenEnded.has(key)) return;
    S.seenEnded.add(key);
    emit("ended", d);
    if (d.name === current) { seenHere(); return; }
    const f = S.films.find((x) => x.name === d.name);
    const title = d.title || f?.title || d.name;
    const out = ["done", "stopped", "failed", "refused"].includes(d.outcome) ? d.outcome : "done";
    const open = h("button", { class: "text-btn accent", type: "button" }, h("span", { text: t("frame.notice.open") }), h("span", { class: "spin", "aria-hidden": "true" }));
    const close = h("button", { class: "icon-btn sm", type: "button" }, icon("i-close"));
    tip(close, t("frame.notice.dismiss"));
    const el = h("div", { class: `notice is-${out}` }, icon(out === "done" ? "i-okc" : out === "stopped" ? "i-stop" : "i-fail"),
      h("div", { class: "notice-text" }, h("b", { text: title }), h("span", { text: t(`frame.notice.${out}`) })), h("div", { class: "notice-acts" }, open, close));
    const leave = () => { el.classList.add("is-leaving"); setTimeout(() => el.remove(), 200); };
    open.addEventListener("click", () => { busy(open, true); location.href = f?.url || `/p/${enc(d.name)}/`; });
    close.addEventListener("click", leave);
    let timer = setTimeout(leave, 9000);
    el.addEventListener("pointerenter", () => clearTimeout(timer));
    el.addEventListener("pointerleave", () => { timer = setTimeout(leave, 4000); });
    notices.append(el);
    while (notices.children.length > 4) notices.firstElementChild.remove();
    if (document.hidden || !document.hasFocus()) { try { desktop()?.attention?.(); } catch { /* a browser tab */ } }
  }

  // the film on screen is read as its request ends; a hidden window marks it once it is shown again
  function seenHere() {
    if (document.hidden) { addEventListener("visibilitychange", seenHere, { once: true }); return; }
    postAt("/api/app/seen", { name: current }).then(() => load()).catch(() => { /* the next state read clears it */ });
  }

  // ---------------------------------------------------------------- a film's actions
  async function stopFilm(f, btn) {
    if (isOff(btn)) return;
    busy(btn, true);
    try {
      await postAt(`/p/${enc(f.name)}/api/chat/stop`, {});
      note(btn, t(f.status === "queued" ? "frame.row.cancelled" : "frame.row.stopped"), "is-ok");
    } catch (e) {
      note(btn, t("frame.row.stopFailed", { why: reason(e) }), "is-error");
    } finally { busy(btn, false); }
  }
  let menuEl = null;
  function closeMenu(refocus) {
    if (!menuEl) return false;
    const m = menuEl;
    menuEl = null;
    m.el.remove();
    m.row?.classList.remove("menu-open");
    m.btn?.setAttribute("aria-expanded", "false");
    if (refocus) (m.btn || m.row?.querySelector(".side-link"))?.focus();
    return true;
  }
  function openMenu(f, row, at, btn = null) {
    closeMenu(false);
    const active = f.status === "working" || f.status === "queued";
    const mi = (ic, key, fn, { danger = false, off = null, kbd = null } = {}) => {
      const b = h("button", { class: `menu-item${danger ? " is-danger" : ""}`, type: "button", role: "menuitem", tabindex: "-1" }, icon(ic), h("span", { text: t(key) }), ...(kbd ? [h("kbd", { text: kbd })] : []));
      if (off) { b.setAttribute("aria-disabled", "true"); tip(b, off); }
      // focus goes back to the row's control first; an action that moves it (rename, a dialog) then takes it
      b.addEventListener("click", () => { if (off) { note(b, off, "is-error"); return; } closeMenu(true); fn(); });
      return b;
    };
    const items = [
      mi("i-arrow", "frame.menu.open", () => { busy(row, true); location.href = f.url; }),
      mi("i-pencil", "frame.menu.rename", () => rename(f), { kbd: "F2" }),
      mi("i-copy", "frame.menu.duplicate", () => duplicate(f, row)),
      mi("i-folder", "frame.menu.reveal", () => reveal(f, "folder", row)),
      mi("i-folder", "frame.menu.revealOut", () => reveal(f, "out", row)),
      ...(f.unread ? [mi("i-eye", "frame.menu.seen", () => seen(f, row))] : []),
      h("div", { class: "menu-sep", role: "separator" }),
      mi("i-trash", "frame.menu.trash", () => askTrash(f), { danger: true, kbd: "Del", off: active ? t("film.busy", { name: f.name }) : null }),
    ];
    const el = h("div", { class: "menu pop", role: "menu", "aria-label": f.title || f.name }, ...items);
    document.body.append(el);
    const r = (btn || row).getBoundingClientRect();
    const x = at ? at.x : r.left, y = at ? at.y : r.bottom + 4;
    el.style.left = `${clamp(x, 6, innerWidth - el.offsetWidth - 6)}px`;
    el.style.top = `${y + el.offsetHeight > innerHeight - 6 ? Math.max(6, (at ? y : r.top - 4) - el.offsetHeight) : y}px`;
    row.classList.add("menu-open");
    btn?.setAttribute("aria-expanded", "true");
    menuEl = { el, row, btn };
    const list = () => [...el.querySelectorAll(".menu-item")];
    list()[0].focus();
    el.addEventListener("keydown", (e) => {
      const l = list(), i = l.indexOf(document.activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); l[(i + (e.key === "ArrowDown" ? 1 : l.length - 1)) % l.length].focus(); }
      else if (e.key === "Home" || e.key === "End") { e.preventDefault(); l[e.key === "Home" ? 0 : l.length - 1].focus(); }
      else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
    });
  }
  document.addEventListener("pointerdown", (e) => { if (menuEl && !menuEl.el.contains(e.target) && !menuEl.btn?.contains(e.target)) closeMenu(false); }, true);

  function rename(f) {
    const r = S.rows.get(f.name);
    if (!r || r.el.querySelector(".side-rename")) return;
    if (root.classList.contains("side-rail")) setRail(false);
    const input = h("input", { class: "side-rename", type: "text", maxlength: "200", value: r.f.title || "", "aria-label": t("frame.renameLabel"), placeholder: f.name });
    r.title.replaceWith(input);
    input.focus();
    input.select();
    let done = false;
    const before = r.f.title || "";
    const finish = async (save) => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      input.replaceWith(r.title);
      r.link.focus();
      if (!save || value === before) return;
      r.title.textContent = value || f.name;
      busy(r.el, true);
      try {
        await postAt(`/api/films/${enc(f.name)}/title`, { title: value });
        r.f = { ...r.f, title: value };         // the list catches up a moment later
        r.k = "";
        fillRow(r, r.f);
        note(r.link, t("frame.renamed"), "is-ok");
      } catch (e) {
        r.k = "";
        fillRow(r, f);
        note(r.link, t("frame.renameFailed", { why: reason(e) }), "is-error");
      } finally { busy(r.el, false); }
    };
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
    input.addEventListener("click", (e) => e.preventDefault());
  }
  async function duplicate(f, row) {
    busy(row, true);
    try {
      const got = await postAt(`/api/films/${enc(f.name)}/duplicate`, {});
      await load();
      const r = S.rows.get(got.name);
      r?.link.focus();
      note(r?.link || row, t("frame.duplicated", { name: got.name }), "is-ok");
    } catch (e) {
      note(row, t("frame.duplicateFailed", { why: reason(e) }), "is-error");
    } finally { busy(row, false); }
  }
  async function reveal(f, what, row) {
    try {
      await postAt(`/api/films/${enc(f.name)}/reveal`, { what });
      note(row, t("frame.revealed"), "is-ok");
    } catch (e) {
      note(row, t("frame.revealFailed", { why: reason(e) }), "is-error");
    }
  }
  async function seen(f, row) {
    try {
      await postAt("/api/app/seen", { name: f.name });
      note(row, t("frame.markedSeen"), "is-ok");
      load();
    } catch (e) { note(row, reason(e), "is-error"); }
  }

  // the trash, with a confirmation that names the film and its folder
  const dlgTitle = h("h2", { id: "trashDlgTitle" }), dlgBody = h("p"), dlgErr = h("p", { class: "dlg-err", role: "alert", hidden: true });
  const dlgCancel = h("button", { class: "btn", type: "button", text: t("frame.trash.cancel") });
  const dlgOk = h("button", { class: "btn danger", type: "button" }, icon("i-trash"), h("span", { text: t("frame.trash.confirm") }), h("span", { class: "spin", "aria-hidden": "true" }));
  const dlg = h("dialog", { class: "frame-dlg", id: "trashDlg", "aria-labelledby": "trashDlgTitle" }, dlgTitle, dlgBody, dlgErr, h("div", { class: "dlg-foot" }, dlgCancel, dlgOk));
  document.body.append(dlg);
  closeOnBackdrop(dlg);
  let trashing = null, trashBusy = false;
  dlg.addEventListener("cancel", (e) => { if (trashBusy) e.preventDefault(); });
  dlg.addEventListener("close", () => { const r = trashing && S.rows.get(trashing.name); (r?.link || findItem).focus(); });
  dlgCancel.addEventListener("click", () => { if (!trashBusy) dlg.close(); });
  function askTrash(f) {
    if (f.status === "working" || f.status === "queued") {
      const r = S.rows.get(f.name);
      if (r) note(r.link, t("film.busy", { name: f.name }), "is-error");
      return;
    }
    trashing = f;
    dlgTitle.textContent = t("frame.trash.title", { title: f.title || f.name });
    dlgBody.textContent = t("frame.trash.body", { name: f.name });
    dlgErr.hidden = true;
    dlg.showModal();
    dlgCancel.focus();
  }
  dlgOk.addEventListener("click", async () => {
    if (trashBusy || !trashing) return;
    trashBusy = true;
    busy(dlgOk, true);
    const f = trashing;
    try {
      await postAt(`/api/films/${enc(f.name)}/trash`, {});
      trashBusy = false;
      dlg.close();
      if (f.name === current) { location.href = "/"; return; }
      note(findItem, t("frame.trash.done", { title: f.title || f.name }), "is-ok");
      load();
    } catch (e) {
      dlgErr.hidden = false;
      dlgErr.textContent = t("frame.trash.failed", { why: reason(e) });
    } finally { trashBusy = false; busy(dlgOk, false); }
  });

  // ---------------------------------------------------------------- the palette: films, pages and the page's commands
  const palInput = h("input", { type: "text", role: "combobox", "aria-expanded": "true", "aria-controls": "palList", "aria-autocomplete": "list", spellcheck: "false", autocomplete: "off", placeholder: t("frame.pal.placeholder"), "aria-label": t("frame.pal.placeholder") });
  const palList = h("ul", { class: "pal-list", id: "palList", role: "listbox" });
  const palFoot = h("div", { class: "pal-foot" }, h("span", {}, h("kbd", { text: "↑↓" }), " ", t("frame.pal.move")), h("span", {}, h("kbd", { text: "Enter" }), " ", t("frame.pal.open")), h("span", {}, h("kbd", { text: "Esc" }), " ", t("frame.pal.close")));
  const pal = h("dialog", { class: "palette", id: "palette", "aria-label": t("frame.find") }, h("div", { class: "pal-field" }, icon("i-search"), palInput), palList, palFoot);
  document.body.append(pal);
  closeOnBackdrop(pal);
  let palOpts = [], palAt = 0, palFrom = null;
  const norm = (s) => String(s || "").normalize("NFKC").toLocaleLowerCase();
  function palEntries() {
    const go = (url) => () => { location.href = url; };
    return [
      ...S.films.filter((f) => f.name !== current).map((f) => ({ group: "films", ic: "i-film", text: f.title || f.name, hint: f.title ? f.name : "", run: go(f.url) })),
      ...(page !== "films" ? [{ group: "pages", ic: "i-grid", text: t("frame.films"), run: go("/") }] : []),
      ...(page !== "new" ? [{ group: "pages", ic: "i-plus", text: t("frame.new"), hint: "N", run: go("/new") }] : []),
      ...(page !== "library" ? [{ group: "pages", ic: "i-book", text: t("frame.library"), run: go("/library") }] : []),
      ...(page !== "settings" ? [{ group: "pages", ic: "i-gear", text: t("frame.settings"), run: go("/settings") }] : []),
      ...S.commands.map((c) => ({ group: "commands", ...c })),
      { group: "commands", ic: "i-sidebar", text: t(root.classList.contains("side-rail") ? "frame.expand" : "frame.collapse"), hint: "Ctrl B", run: () => setRail(!root.classList.contains("side-rail")) },
    ];
  }
  function renderPal() {
    const q = norm(palInput.value.trim());
    palOpts = palEntries().filter((o) => !q || norm(`${o.text} ${o.hint || ""}`).includes(q));
    palAt = clamp(palAt, 0, Math.max(0, palOpts.length - 1));
    const out = [];
    let last = null;
    palOpts.forEach((o, i) => {
      if (o.group !== last) { out.push(h("li", { class: "pal-group", role: "presentation", text: t(`frame.pal.${o.group}`) })); last = o.group; }
      const li = h("li", { class: `pal-opt${i === palAt ? " is-active" : ""}`, role: "option", id: `palOpt${i}`, "aria-selected": String(i === palAt), ...(o.off ? { "aria-disabled": "true" } : {}) },
        icon(o.ic || "i-arrow"), h("span", { class: "t", text: o.text }), h("span", { class: "k" }, ...(o.off ? [o.off] : o.hint ? [h("kbd", { text: o.hint })] : [])));
      li.addEventListener("pointermove", () => { if (palAt !== i) { palAt = i; renderPal(); } });
      li.addEventListener("click", () => runPal(i));
      out.push(li);
    });
    if (!palOpts.length) out.push(h("li", { class: "pal-none", role: "presentation", text: t("frame.pal.none", { q: palInput.value.trim() }) }));
    palList.replaceChildren(...out);
    palInput.setAttribute("aria-activedescendant", palOpts.length ? `palOpt${palAt}` : "");
    palList.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
  }
  function runPal(i) {
    const o = palOpts[i];
    if (!o) return;
    if (o.off) { note(palInput, o.off, "is-error"); return; }
    palFrom = null;
    pal.close();
    o.run();
  }
  function openPal() {
    if (pal.open) return;
    closeMenu(false);
    palFrom = document.activeElement;
    palInput.value = "";
    palAt = 0;
    renderPal();
    pal.showModal();
    palInput.focus();
  }
  pal.addEventListener("close", () => { if (palFrom?.isConnected) palFrom.focus(); });
  palInput.addEventListener("input", () => { palAt = 0; renderPal(); });
  palInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); palAt = (palAt + (e.key === "ArrowDown" ? 1 : palOpts.length - 1)) % Math.max(1, palOpts.length); renderPal(); }
    else if (e.key === "Enter") { e.preventDefault(); runPal(palAt); }
  });
  findItem.addEventListener("click", openPal);

  // ---------------------------------------------------------------- keys
  const links = () => [...scroll.querySelectorAll(".side-link")];
  scroll.addEventListener("keydown", (e) => {
    const l = links(), i = l.indexOf(document.activeElement);
    if (i < 0) return;
    const r = S.rows.get(l[i].dataset.name), f = r?.f;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); l[clamp(i + (e.key === "ArrowDown" ? 1 : -1), 0, l.length - 1)].focus(); }
    else if (e.key === "Home" || e.key === "End") { e.preventDefault(); l[e.key === "Home" ? 0 : l.length - 1].focus(); }
    else if (e.key === "F2" && f) { e.preventDefault(); rename(f); }
    else if (e.key === "Delete" && f) { e.preventDefault(); askTrash(f); }
    else if ((e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) && f) { e.preventDefault(); openMenu(f, r.el, null, r.more); }
  });
  addEventListener("keydown", (e) => {
    if (e.defaultPrevented) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); pal.open ? pal.close() : openPal(); return; }
    if (mod && !e.altKey && (e.key === "b" || e.key === "B") && !typing(e.target)) { e.preventDefault(); setRail(!root.classList.contains("side-rail")); return; }
    if (mod || e.altKey || typing(e.target) || document.querySelector("dialog[open]")) return;
    if ((e.key === "n" || e.key === "N") && page !== "new") { e.preventDefault(); busy(newItem, true); location.href = "/new"; }
  });

  renderFilms();
  load().then((ok) => { if (ok) stream(); });
  return {
    on(ev, fn) { (handlers[ev] ||= []).push(fn); if (ev === "films" && S.app) fn(S.films); return this; },
    films: () => S.films,
    app: () => S.app,
    // a page's own commands for the palette: [{text, ic, hint, run, off}]
    commands(list) { S.commands = list || []; if (pal.open) renderPal(); },
    refresh: load,
  };
}
