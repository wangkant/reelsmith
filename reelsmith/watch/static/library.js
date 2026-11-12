// The Library: the components an agent can place, the workspace's notes, its rules and its fonts.
import { post } from "./api.js";
import { ago } from "./chrome.js";
import { has, t, translate } from "./i18n.js";
import { mountShell } from "./shell.js";
import { busy, h, icon, installTips, note, pressable, storage, store, tip } from "./util.js";

installTips();
translate();
mountShell({ page: "library" });

const $ = (id) => document.getElementById(id);
const SECS = ["components", "notes", "rules", "fonts"];
const lib = { data: null, sec: null, query: "", origin: storage("lib:origin", "all"), pick: storage("lib:component", null) };

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw Object.assign(new Error(body?.error || `${r.status} ${r.statusText}`), { status: r.status, code: body?.code, params: body?.params });
  return body;
}
const reason = (e) => (e.code && has(e.code) ? t(e.code, e.params || {}) : e.message);
const fullTime = (ts) => { try { return new Date(ts).toLocaleString(document.documentElement.lang, { dateStyle: "medium", timeStyle: "short" }); } catch { return ts; } };

// ---------------------------------------------------------------- loading
async function load() {
  try {
    lib.data = await getJSON("/api/library");
    $("loadErr").hidden = true;
  } catch (e) {
    if (!lib.data) {
      $("loadErr").hidden = false;
      $("loadErrText").textContent = t("lib.loadFailed", { why: e.message });
    }
  }
  $("loading").hidden = true;
  render();
}
const retry = $("retryBtn");
tip(retry, t("pages.retry"));
pressable(retry, async () => {
  busy(retry, true);
  await load();
  busy(retry, false);
  if ($("loadErr").hidden) note($("tabs"), t("lib.loaded"), "is-ok");
});

// ---------------------------------------------------------------- tabs
const tabs = [...$("tabs").querySelectorAll('[role="tab"]')];
function showSec(sec, focus = false) {
  if (!SECS.includes(sec)) sec = "components";
  lib.sec = sec;
  for (const b of tabs) {
    const on = b.dataset.sec === sec;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
  }
  for (const s of SECS) $(`sec-${s}`).hidden = !lib.data || s !== sec;
  if (location.hash.slice(1) !== sec) history.replaceState(history.state, "", `#${sec}`);
  if (sec === "components") showPreview();
}
for (const b of tabs) b.addEventListener("click", () => showSec(b.dataset.sec));
$("tabs").addEventListener("keydown", (e) => {
  const i = tabs.findIndex((b) => b.dataset.sec === lib.sec);
  const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to == null) return;
  e.preventDefault();
  showSec(tabs[(to + tabs.length) % tabs.length].dataset.sec, true);
});
addEventListener("hashchange", () => showSec(location.hash.slice(1)));

function render() {
  const d = lib.data;
  $("tabs").hidden = !d;
  if (!d) { for (const s of SECS) $(`sec-${s}`).hidden = true; return; }
  const counts = {
    components: d.components?.length || 0,
    notes: null,
    rules: (d.rules?.hard?.length || 0) + (d.rules?.advice?.length || 0),
    fonts: d.fonts?.length || 0,
  };
  for (const b of tabs) {
    const n = counts[b.dataset.sec];
    b.querySelector(".count").textContent = n ? String(n) : "";
  }
  renderComponents();
  renderNotes();
  renderRules();
  renderFonts();
  showSec(lib.sec || location.hash.slice(1));
}

// ---------------------------------------------------------------- components
const search = $("search");
search.placeholder = t("lib.comp.search");
search.setAttribute("aria-label", t("lib.comp.search"));
tip($("searchClear"), t("lib.comp.searchClear"));
search.addEventListener("input", () => { lib.query = search.value.trim(); renderList(); });
search.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); listButtons()[0]?.focus(); }
  else if (e.key === "Escape" && search.value) { e.preventDefault(); clearSearch(); }
});
function clearSearch() { search.value = ""; lib.query = ""; renderList(); search.focus(); }
pressable($("searchClear"), clearSearch);

const originSeg = $("originSeg");
originSeg.setAttribute("aria-label", t("lib.origin.label"));
for (const b of originSeg.children) {
  pressable(b, () => { lib.origin = b.dataset.origin; store("lib:origin", lib.origin); renderList(); });
}

const comps = () => lib.data?.components || [];
const originText = (o) => t(o === "workspace" ? "lib.origin.workspaceOne" : "lib.origin.builtinOne");
function matches(c) {
  if (lib.origin !== "all" && c.origin !== lib.origin) return false;
  if (!lib.query) return true;
  const q = lib.query.toLowerCase();
  return [c.name, c.about, ...(c.props || []).map((p) => p.name)].some((s) => String(s || "").toLowerCase().includes(q));
}
const listButtons = () => [...$("compList").querySelectorAll('[role="option"]')];

function renderComponents() {
  const all = comps();
  const empty = !all.length;
  $("compEmpty").hidden = !empty;
  $("sec-components").classList.toggle("is-empty", empty);
  const both = all.some((c) => c.origin === "workspace") && all.some((c) => c.origin !== "workspace");
  originSeg.hidden = !both;
  if (!both) lib.origin = "all";
  renderList();
}

function renderList() {
  const shown = comps().filter(matches);
  for (const b of originSeg.children) b.setAttribute("aria-pressed", String(b.dataset.origin === lib.origin));
  $("searchClear").hidden = !search.value;
  if (!shown.some((c) => c.name === lib.pick)) lib.pick = shown[0]?.name ?? null;
  $("compList").replaceChildren(...shown.map((c) => {
    const on = c.name === lib.pick;
    const b = h("div", { role: "option", class: "comp-row", id: `comp-${c.name}`, "aria-selected": String(on), tabindex: on ? "0" : "-1", "data-name": c.name },
      h("span", { class: "comp-name", text: c.name }),
      c.problem ? h("span", { class: "comp-flag", text: t("lib.comp.unusableShort") }) : c.origin === "workspace" ? h("span", { class: "comp-origin", text: t("lib.origin.workspace") }) : null,
      h("span", { class: "comp-about", text: c.about || "" }));
    pressable(b, () => pick(c.name, true));
    return b;
  }));
  const q = search.value.trim();
  $("noMatch").hidden = !!shown.length || !comps().length;
  $("noMatch").textContent = q ? t("lib.comp.noMatch", { q }) : t("lib.comp.noneHere");
  renderDetail();
}

$("compList").addEventListener("keydown", (e) => {
  const list = listButtons();
  const i = list.findIndex((b) => b.dataset.name === lib.pick);
  const to = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: list.length - 1, PageDown: i + 8, PageUp: i - 8 }[e.key];
  if (to == null) return;
  e.preventDefault();
  if (to < 0 && e.key === "ArrowUp") { search.focus(); return; }
  const b = list[Math.max(0, Math.min(list.length - 1, to))];
  if (b) pick(b.dataset.name, true);
});

function pick(name, focus) {
  lib.pick = name;
  store("lib:component", name);
  for (const b of listButtons()) {
    const on = b.dataset.name === name;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) { b.focus(); b.scrollIntoView({ block: "nearest" }); }
  }
  renderDetail();
}

function renderDetail() {
  const box = $("compDetail");
  const c = comps().find((x) => x.name === lib.pick);
  box.hidden = !c;
  if (!c) { box.replaceChildren(); return; }
  if (box.dataset.name === c.name && box.dataset.theme === document.documentElement.dataset.theme) return;
  box.dataset.name = c.name;
  const img = h("img", { alt: t("lib.comp.pictureAlt", { name: c.name }), decoding: "async" });
  const msg = h("span", { class: "pic-msg" });
  const pic = h("div", { class: "comp-pic is-pending" }, img, h("div", { class: "pic-wait" }, icon("i-shapes"), msg));
  const props = c.props || [];
  const example = typeof c.example === "string" ? c.example : JSON.stringify(c.example ?? {}, null, 2);
  const copy = h("button", { class: "text-btn", type: "button" }, icon("i-copy"), h("span", { text: t("lib.comp.copy") }));
  tip(copy, t("lib.comp.copyTip"));
  pressable(copy, () => copyText(example, copy));
  box.replaceChildren(
    pic,
    h("header", { class: "comp-head" },
      h("h2", { class: "mono", text: c.name }),
      h("span", { class: "comp-origin", text: originText(c.origin) })),
    h("p", { class: "comp-text", text: c.about || t("lib.comp.noAbout") }),
    h("h3", { class: "sub-head", text: t("lib.comp.props") }),
    props.length
      ? h("table", { class: "props" },
        h("thead", {}, h("tr", {}, ...["lib.prop.name", "lib.prop.type", "lib.prop.required", "lib.prop.about"].map((k) => h("th", { scope: "col", text: t(k) })))),
        h("tbody", {}, ...props.map((p) => h("tr", {},
          h("td", { class: "mono", text: p.name }),
          h("td", { class: "mono dim", text: p.type || "" }),
          h("td", { class: p.required ? "req" : "faint", text: t(p.required ? "lib.prop.yes" : "lib.prop.no") }),
          h("td", { text: p.about || "" })))))
      : h("p", { class: "small-empty", text: t("lib.comp.noProps") }),
    h("div", { class: "sub-head-row" }, h("h3", { class: "sub-head", text: t("lib.comp.example") }), copy),
    h("pre", { class: "code-block" }, h("code", { text: example })));
  showPreview();
}

// ---------------------------------------------------------------- the component's picture, drawn by the renderer
const pics = new Map();            // "name|theme" -> object URL
let picRun = 0;
async function showPreview() {
  const box = $("compDetail");
  const c = comps().find((x) => x.name === lib.pick);
  const pic = box.querySelector(".comp-pic");
  if (!c || !pic || lib.sec !== "components") return;
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  box.dataset.theme = theme;
  const img = pic.querySelector("img"), msg = pic.querySelector(".pic-msg");
  const key = `${c.name}|${theme}`;
  const run = ++picRun;
  const put = (url) => {
    img.onload = () => { pic.classList.remove("is-pending", "is-failed"); pic.classList.add("has-picture"); };
    img.src = url;
  };
  if (c.problem) {
    pic.classList.remove("is-pending", "has-picture");
    pic.classList.add("is-failed");
    msg.textContent = t("lib.comp.unusable", { why: c.problem });
    return;
  }
  if (pics.has(key)) { put(pics.get(key)); return; }
  pic.classList.remove("has-picture", "is-failed");
  pic.classList.add("is-pending");
  msg.textContent = t("lib.comp.drawing");
  for (let tries = 0; tries < 90 && run === picRun; tries++) {
    let r;
    try {
      r = await fetch(`/api/library/preview?name=${encodeURIComponent(c.name)}&theme=${theme}`, { cache: "no-store" });
    } catch (e) {
      r = null;
    }
    if (run !== picRun) return;
    if (r && r.status === 200) {
      const url = URL.createObjectURL(await r.blob());
      pics.set(key, url);
      if (run === picRun) put(url);
      return;
    }
    if (!r || r.status !== 202) {
      let why = r ? `${r.status}` : t("lib.comp.offline");
      try { const b = await r.json(); why = b.code && has(b.code) ? t(b.code, b.params || {}) : b.error || why; } catch { /* not JSON */ }
      pic.classList.remove("is-pending");
      pic.classList.add("is-failed");
      msg.textContent = t("lib.comp.noPicture", { why });
      return;
    }
    await new Promise((ok) => setTimeout(ok, Math.min(2000, 500 + tries * 150)));
  }
  if (run === picRun) {
    pic.classList.remove("is-pending");
    pic.classList.add("is-failed");
    msg.textContent = t("lib.comp.slow");
  }
}
// the pictures follow the theme
new MutationObserver(() => { const box = $("compDetail"); if (box.dataset.name) { delete box.dataset.name; renderDetail(); } })
  .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

async function copyText(text, btn) {
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch {
    // the desktop window may refuse the clipboard API; the older command still works there
    const ta = h("textarea", { class: "offscreen", "aria-hidden": "true" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    btn.focus();
  }
  note(btn, t(ok ? "lib.comp.copied" : "lib.comp.copyFailed"), ok ? "is-ok" : "is-error");
}

// ---------------------------------------------------------------- notes: Markdown shown as text, never as HTML
function inline(text) {
  const out = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*\s][^*]*)\*|_([^_\s][^_]*)_/g;
  let at = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > at) out.push(text.slice(at, m.index));
    if (m[1] != null) out.push(h("code", { text: m[1] }));
    else if (m[2] != null || m[3] != null) out.push(h("strong", { text: m[2] ?? m[3] }));
    else if (m[4] != null) {
      out.push(/^https?:\/\//i.test(m[5]) ? h("a", { href: m[5], target: "_blank", rel: "noopener noreferrer", text: m[4] }) : `${m[4]} (${m[5]})`);
    } else out.push(h("em", { text: m[6] ?? m[7] }));
    at = re.lastIndex;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}
function markdown(src) {
  const blocks = [];
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  let para = [], list = null;
  const endPara = () => { if (para.length) blocks.push(h("p", {}, inline(para.join(" ")))); para = []; };
  const endList = () => { if (list) blocks.push(list); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if (/^\s*```/.test(line)) {
      endPara(); endList();
      const code = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i]);
      blocks.push(h("pre", { class: "code-block" }, h("code", { text: code.join("\n") })));
    } else if ((m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line))) {
      endPara(); endList();
      blocks.push(h(`h${Math.min(6, m[1].length + 1)}`, {}, inline(m[2])));
    } else if ((m = /^(\s*)(?:[-*+]|(\d+)[.)])\s+(.*)$/.exec(line))) {
      endPara();
      const tag = m[2] ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) { endList(); list = h(tag); }
      list.append(h("li", { class: m[1].length >= 2 ? "deep" : null }, inline(m[3])));
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      endPara(); endList();
      blocks.push(h("hr"));
    } else if ((m = /^>\s?(.*)$/.exec(line))) {
      endPara(); endList();
      blocks.push(h("blockquote", {}, inline(m[1])));
    } else if (!line.trim()) {
      endPara(); endList();
    } else if (list && /^\s{2,}\S/.test(line)) {
      list.lastChild.append(" ", ...inline(line.trim()));      // a list item that wraps onto the next line
    } else {
      endList();
      para.push(line.trim());
    }
  }
  endPara(); endList();
  return blocks;
}

function renderNotes() {
  const n = lib.data.notes;
  const filled = !!(n && n.text && n.text.trim());
  $("notesEmpty").hidden = filled;
  $("notesBody").hidden = !filled;
  $("notesBar").hidden = !n;
  if (n) {
    $("notesPath").textContent = n.path;
    tip($("notesPath"), n.path);
    $("notesWhen").textContent = n.modified ? ago(n.modified) : t("pages.unknown");
    if (n.modified) tip($("notesWhen"), fullTime(n.modified));
  }
  $("notesBody").replaceChildren(...(filled ? markdown(n.text) : []));
}
const notesReveal = $("notesReveal");
tip(notesReveal, t("lib.notes.revealTip"));
pressable(notesReveal, () => reveal(notesReveal, "notes"));

async function reveal(btn, what) {
  busy(btn, true);
  try {
    await post("/api/reveal", { what });
    note(btn, t("pages.revealed"), "is-ok");
  } catch (e) {
    note(btn, t("pages.revealFailed", { why: reason(e) }), "is-error");
  }
  busy(btn, false);
}

// ---------------------------------------------------------------- rules and fonts
const valueText = (v) => (v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
function renderRules() {
  const r = lib.data.rules || { hard: [], advice: [] };
  for (const [kind, list, empty] of [["hard", "hardList", "hardEmpty"], ["advice", "adviceList", "adviceEmpty"]]) {
    const rows = r[kind] || [];
    $(empty).hidden = !!rows.length;
    $(list).hidden = !rows.length;
    $(list).replaceChildren(...rows.map((x) => h("div", { class: "kv-row" },
      h("dt", { class: "mono", text: x.key }), h("dd", { class: "mono", text: valueText(x.value) }))));
  }
}
function renderFonts() {
  const f = lib.data.fonts || [];
  $("fontsEmpty").hidden = !!f.length;
  $("fontList").hidden = !f.length;
  $("fontList").replaceChildren(...f.map((x) => h("li", { class: "row" },
    h("span", { class: "row-name", text: x.name }), h("span", { class: "row-path mono", text: x.path }))));
}

// ---------------------------------------------------------------- keys: "/" searches the components
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest?.("input, textarea, [contenteditable], dialog")) return;
  if (e.key === "/" && lib.data) { e.preventDefault(); showSec("components"); search.focus(); search.select(); }
});

load().then(() => requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready"))));
