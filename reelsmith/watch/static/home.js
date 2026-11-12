import { json, postAt } from "./api.js";
import { ago } from "./chrome.js";
import { mountShell } from "./shell.js";
import { has, t, translate } from "./i18n.js";
import { busy, disable, h, handOff, icon, installTips, isOff, note, pressable, shortTime, storage, store, tip } from "./util.js";

installTips();
translate();

const $ = (id) => document.getElementById(id);
const home = { data: null, status: "connecting", query: "" };
const cards = new Map();            // project name -> {el, poster, img, ...}
const SEARCH_FROM = 9;              // the search appears once there are more films than fit at a glance

// a film the frame no longer lists (moved to the trash) leaves the shelf at once, before its poster is asked for again
const shell = mountShell({ page: "films" }).on("films", (films) => {
  if (!home.data) return;
  const names = new Set(films.map((f) => f.name));
  const kept = home.data.projects.filter((p) => names.has(p.name));
  if (kept.length !== home.data.projects.length) { home.data.projects = kept; render(); }
});

// ---------------------------------------------------------------- the server
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw Object.assign(new Error(body?.error || `${r.status} ${r.statusText}`), { status: r.status, body });
  return body;
}

let loading = null, again = false;
async function load() {
  if (loading) { again = true; return loading; }
  loading = (async () => {
    try {
      home.data = await getJSON("/api/home");
      $("loadErr").hidden = true;
    } catch (e) {
      if (!home.data) {
        $("loadErr").hidden = false;
        $("loadErrText").textContent = t("home.loadFailed", { why: e.message });
      }
    }
    render();
  })();
  await loading;
  loading = null;
  if (again) { again = false; return load(); }
}
const retry = $("retryBtn");
tip(retry, t("home.retry"));
pressable(retry, async () => {
  busy(retry, true);
  await load();
  busy(retry, false);
  if ($("loadErr").hidden) note($("grid"), t("home.loaded"), "is-ok");
});

// A "projects" event says the list would read differently; the stream reconnects on its own.
function subscribe() {
  let es = null, timer = 0, retryAt = 0;
  const setStatus = (s) => { home.status = s; renderConn(); };
  const open = () => {
    setStatus(home.status === "connected" ? "reconnecting" : home.status);
    es = new EventSource("/api/home/events");
    es.onopen = () => { setStatus("connected"); load(); };
    es.addEventListener("projects", () => { clearTimeout(timer); timer = setTimeout(load, 120); });
    es.onerror = () => {
      setStatus("reconnecting");
      if (es.readyState === EventSource.CLOSED) { es.close(); clearTimeout(retryAt); retryAt = setTimeout(open, 2000); }
    };
  };
  open();
}

// ---------------------------------------------------------------- the top bar
function renderConn() {
  const c = $("conn");
  c.dataset.state = home.status === "connecting" && !home.data ? "connected" : home.status;
  $("connText").textContent = t(`status.${home.status}`);
  tip(c, t("status.goneTip"));
  const why = home.status === "reconnecting" ? t("status.goneTip") : null;
  for (const b of [$("newBtn"), $("emptyNew")]) disable(b, why, t("home.newTip"), "N");
  cfRender();
}

function renderHead() {
  const d = home.data;
  if (!d) return;
  document.title = `${t("frame.films")} · ${d.workspace.name}`;
  const n = d.projects.length;
  $("wsCount").textContent = n ? t("home.count", { n }) : "";
}

// ---------------------------------------------------------------- the cards
function resultOf(p) {
  if (!p.valid && !p.empty) return { cls: "is-err", text: t("project.invalid"), tip: t("project.invalid") };
  const r = p.result || { state: "none" };
  if (r.state === "current" && r.accepted) return { cls: "is-accepted", text: t("top.accepted"), tip: t("result.currentTip") };
  return {
    none: { cls: "is-none", text: t("result.none"), tip: t("result.noneTip") },
    current: { cls: "is-ok", text: t("result.current"), tip: t("result.currentTip") },
    stale: { cls: "is-warn", text: t("result.stale"), tip: t("result.staleTip") },
    refused: { cls: "is-err", text: t("result.refused"), tip: t("result.refusedTip") },
  }[r.state] || { cls: "is-none", text: t("result.none"), tip: t("result.noneTip") };
}

function workText(w) {
  const what = w.tool && has(`run.${w.tool}`) ? t(`run.${w.tool}`) : t("home.agentWorking");
  return typeof w.percent === "number" ? `${what} · ${w.percent} %` : what;
}

function fullTime(ts) {
  try { return new Date(ts).toLocaleString(document.documentElement.lang, { dateStyle: "medium", timeStyle: "short" }); } catch { return ts; }
}

function makeCard(p) {
  const img = h("img", { alt: "", decoding: "async" });
  const emptyText = h("span");
  const poster = h("div", { class: "poster" }, img, h("div", { class: "poster-empty" }, icon("i-film"), emptyText),
    h("span", { class: "dur num" }), h("span", { class: "work-tag", hidden: true }, h("span", { class: "dot" }), h("span")),
    h("span", { class: "opening", "aria-hidden": "true" }, h("span", { class: "spin" })));
  const title = h("b"), folder = h("code"), state = h("span", { class: "state" }, h("span", { class: "dot" }), h("span")), when = h("span", { class: "ago" });
  const el = h("a", { class: "film-card", href: p.url, "data-name": p.name }, poster,
    h("div", { class: "card-body" }, h("div", { class: "card-title" }, title, folder),
      h("div", { class: "card-meta" }, state, h("span", { class: "sep" }), when)));
  el.addEventListener("click", (e) => {
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    busy(el, true);         // the page that follows replaces this one; the spinner covers the wait
  });
  const c = { el, poster, img, emptyText, title, folder, state, when, want: null, shown: null, tries: 0 };
  img.addEventListener("load", () => {
    img.classList.add("is-in");
    poster.classList.add("has-picture");
    poster.classList.remove("is-pending");
  });
  return c;
}

function fillCard(c, p) {
  // a film without a title goes by its folder's name, which is then not repeated beside it
  const name = p.title || p.name;
  c.el.setAttribute("href", p.url);
  c.title.textContent = name;
  c.folder.textContent = p.title ? p.name : "";
  c.folder.hidden = !p.title;
  c.el.setAttribute("aria-label", [name, p.title ? p.name : null, resultOf(p).text, p.working ? workText(p.working) : null].filter(Boolean).join(", "));
  tip(c.el, t("home.openTip", { title: name }));
  tip(c.folder, t("top.projTip", { title: name, path: p.path }));
  const r = resultOf(p);
  c.state.className = `state ${r.cls}`;
  c.state.lastChild.textContent = r.text;
  tip(c.state, r.tip);
  c.when.textContent = p.modified ? t("home.changed", { ago: ago(p.modified) }) : "";
  if (p.modified) tip(c.when, fullTime(p.modified));
  c.poster.querySelector(".dur").textContent = p.duration ? shortTime(p.duration) : "";
  const tag = c.poster.querySelector(".work-tag");
  tag.hidden = !p.working;
  if (p.working) {
    tag.lastChild.textContent = workText(p.working);
    tip(tag, p.working.by === "agent" ? t("status.working", { what: workText(p.working) }) : workText(p.working));
  }
  if (!p.poster || p.empty) {
    c.want = null;
    c.poster.classList.remove("has-picture", "is-pending");
    c.img.classList.remove("is-in");
    c.emptyText.textContent = p.empty ? t("mon.waiting") : p.valid ? t("home.noPicture") : t("project.invalid");
  } else if (p.poster !== c.want) {
    c.want = p.poster;
    c.tries = 0;
    if (!c.poster.classList.contains("has-picture")) c.emptyText.textContent = t("home.noPicture");
    queuePoster(c);
  }
}

// Posters come two at a time: a cut's frame starts the renderer, and every project has its own.
const posterQ = [];
let posterBusy = 0;
function queuePoster(c) {
  if (!posterQ.includes(c)) posterQ.push(c);
  setTimeout(pump, 0);          // a new card joins the grid first
}
function pump() {
  while (posterBusy < 2 && posterQ.length) {
    const c = posterQ.shift();
    posterBusy++;
    fetchPoster(c).finally(() => { posterBusy--; pump(); });
  }
}
async function fetchPoster(c) {
  const url = c.want;
  if (!url || !c.el.isConnected) return;
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (url !== c.want) return;
    if (r.status === 202) {             // queued for the renderer: ask again shortly
      c.poster.classList.add("is-pending");
      if (!c.poster.classList.contains("has-picture")) c.emptyText.textContent = t("home.posterPending");
      if (++c.tries < 80) setTimeout(() => { if (url === c.want) queuePoster(c); }, 2500);
      return;
    }
    if (!r.ok) {
      let body = null;
      try { body = await r.json(); } catch { /* not JSON */ }
      c.poster.classList.remove("is-pending");
      if (!c.poster.classList.contains("has-picture")) c.emptyText.textContent = t("home.noPicture");
      tip(c.poster, body?.code && has(body.code) ? t(body.code, body.params || {}) : body?.error || "");
      return;
    }
    const blob = await r.blob();
    if (url !== c.want) return;
    const old = c.shown;
    c.shown = URL.createObjectURL(blob);
    c.img.src = c.shown;
    tip(c.poster, "");
    if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);
  } catch {
    if (++c.tries < 80) setTimeout(() => { if (url === c.want) queuePoster(c); }, 4000);
  }
}

const norm = (s) => String(s || "").normalize("NFKC").toLocaleLowerCase();
function render() {
  renderHead();
  renderConn();
  const d = home.data;
  const grid = $("grid");
  grid.setAttribute("aria-busy", String(!d));
  if (!d) return;
  const all = d.projects;
  const searchable = all.length >= SEARCH_FROM;
  $("searchBox").hidden = !searchable;
  if (!searchable && home.query) { home.query = ""; $("search").value = ""; }
  const q = norm(home.query.trim());
  const shown = q ? all.filter((p) => norm(`${p.title || ""} ${p.name}`).includes(q)) : all;
  const keep = new Set(shown.map((p) => p.name));
  for (const [name, c] of cards) if (!all.some((p) => p.name === name)) { c.el.remove(); cards.delete(name); if (c.shown) URL.revokeObjectURL(c.shown); }
  const order = [];
  for (const p of all) {
    let c = cards.get(p.name);
    if (!c) { c = makeCard(p); cards.set(p.name, c); }
    fillCard(c, p);
    c.el.hidden = !keep.has(p.name);
    order.push(c.el);
  }
  // reorder only when the order changed, so focus and hover survive a refresh
  if (order.some((el, i) => grid.children[i] !== el)) grid.replaceChildren(...order);
  $("empty").hidden = all.length > 0;
  $("noMatch").hidden = !(all.length && !shown.length);
  $("noMatch").textContent = t("home.noMatch", { q: home.query.trim() });
  $("searchClear").hidden = !home.query;
}
setInterval(() => { if (home.data) for (const p of home.data.projects) { const c = cards.get(p.name); if (c && p.modified) c.when.textContent = t("home.changed", { ago: ago(p.modified) }); } }, 30000);

// ---------------------------------------------------------------- search
const search = $("search");
search.placeholder = t("home.search");
search.setAttribute("aria-label", t("home.search"));
search.setAttribute("aria-keyshortcuts", "/");
search.addEventListener("input", () => { home.query = search.value; render(); });
search.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && search.value) { e.preventDefault(); e.stopPropagation(); search.value = ""; home.query = ""; render(); }
});
const clear = $("searchClear");
tip(clear, t("home.searchClear"));
pressable(clear, () => { search.value = ""; home.query = ""; render(); search.focus(); });

// ---------------------------------------------------------------- the composer: describe a film, Enter creates it
const cf = { form: $("cf"), text: $("cfText"), go: $("cfGo"), folder: $("cfFolder"), hint: $("cfHint"), more: $("cfMore"),
  creating: false, seq: 0, timer: 0 };
const reasonOf = (e) => (e?.code && has(e.code) ? t(e.code, e.params || {}) : e?.message || String(e));
cf.text.placeholder = t("home.compose");
cf.text.setAttribute("aria-label", t("home.compose"));
tip(cf.more, t("home.composeMoreTip"));
function cfGrow() {
  cf.text.style.height = "auto";
  cf.text.style.height = `${Math.min(cf.text.scrollHeight, 168)}px`;
}
function cfHint(text = null, kind = "") {
  cf.hint.className = `cf-hint${kind ? ` ${kind}` : ""}`;
  cf.hint.textContent = text ?? (cf.text.value.trim() ? t("home.composeHint") : "");
  cf.form.classList.toggle("is-bad", kind === "is-bad");
}
function cfRender() {
  const lost = home.status === "reconnecting";
  const why = cf.creating ? t("home.composeBusy") : lost ? t("status.goneTip") : !cf.text.value.trim() ? t("home.composeEmpty") : null;
  disable(cf.go, why, t("newp.createTip"), "Enter");
  cf.go.setAttribute("aria-label", t("newp.createStart"));
}
async function cfSuggest() {
  const text = cf.text.value.trim(), seq = ++cf.seq;
  if (!text) { cf.folder.hidden = true; return; }
  try {
    const got = await json(`/api/films/suggest?text=${encodeURIComponent(text.slice(0, 400))}`);
    if (seq !== cf.seq) return;
    cf.folder.textContent = t("home.composeFolder", { name: got.name });
    tip(cf.folder, t("newp.nameHint"));
    cf.folder.hidden = false;
  } catch { cf.folder.hidden = true; }      // the server names it on create
}
cf.text.value = storage("films-compose", "") || "";
cf.text.addEventListener("input", () => {
  store("films-compose", cf.text.value || null);
  cfGrow();
  cfHint();
  cfRender();
  clearTimeout(cf.timer);
  cf.timer = setTimeout(cfSuggest, 250);
});
cf.text.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !e.isComposing) { cf.text.blur(); return; }
  if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  cfSubmit();
});
cf.form.addEventListener("submit", (e) => { e.preventDefault(); cfSubmit(); });
async function cfSubmit() {
  if (cf.creating) return;
  if (isOff(cf.go)) { note(cf.go, cf.go.dataset.tip || "", "is-error"); cf.text.focus(); return; }
  const text = cf.text.value.trim();
  cf.creating = true;
  cf.text.readOnly = true;
  busy(cf.go, true);
  cfRender();
  cfHint(t("home.composeBusy"));
  try {
    const res = await postAt("/api/films", { description: text, start: true });
    if (res.refused) {                              // never lost: the film's message box receives it, with the reason
      handOff(`film:${res.name}`, { text, refused: res.refused });
      store("films-compose", null);
      location.href = res.url;
      return;
    }
    cf.text.value = "";
    store("films-compose", null);
    cf.folder.hidden = true;
    cfGrow();
    cfHint(t("home.composeDone", { name: res.name }), "is-ok");
    note(cf.go, t("home.composeDone", { name: res.name }), "is-ok");
    shell.refresh();
    load();
  } catch (e) {
    cfHint(t("home.composeFailed", { why: reasonOf(e) }), "is-bad");
    note(cf.go, t("home.composeFailed", { why: reasonOf(e) }), "is-error");
  }
  cf.creating = false;
  cf.text.readOnly = false;
  busy(cf.go, false);
  cfRender();
  cf.text.focus();
}
cf.more.addEventListener("click", (e) => {
  if (e.ctrlKey || e.metaKey || e.shiftKey) return;
  if (cf.creating) { e.preventDefault(); return; }
  if (cf.text.value.trim()) handOff("new", { text: cf.text.value.trim() });
  busy(cf.more, true);
});
cfGrow();
cfHint();
cfRender();
if (cf.text.value.trim()) cfSuggest();

// ---------------------------------------------------------------- a new film: its own page
for (const b of [$("newBtn"), $("emptyNew")]) {
  b.addEventListener("click", (e) => { if (!isLocked(b)) { if (!(e.ctrlKey || e.metaKey || e.shiftKey)) busy(b, true); } else { e.preventDefault(); note(b, b.dataset.tip || ""); } });
}
function isLocked(b) { return b.getAttribute("aria-disabled") === "true"; }

// ---------------------------------------------------------------- keys: "/" searches (the frame has "N")
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || document.querySelector("dialog[open]")) return;
  if (e.target.closest?.("input, textarea, [contenteditable]")) return;
  if (e.key === "/" && !$("searchBox").hidden) { e.preventDefault(); search.focus(); search.select(); }
});

render();
load().then(() => requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready"))));
subscribe();
