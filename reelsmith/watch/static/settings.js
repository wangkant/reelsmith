// Settings: appearance, the agent, provider keys, spend, the system checks, the trash and the version.
import { post } from "./api.js";
import { ago, setupLanguage, setupTheme } from "./chrome.js";
import { has, lang, t, translate } from "./i18n.js";
import { mountShell } from "./shell.js";
import { bytes, busy, disable, h, icon, installTips, note, pressable, tip } from "./util.js";

installTips();
translate();
const shell = mountShell({ page: "settings" });

const $ = (id) => document.getElementById(id);
const SECS = ["appearance", "agent", "providers", "spend", "system", "trash", "about"];
const REPO = "https://github.com/wangkant/reelsmith";
const DOCS = [["set.doc.manual", "docs/manual.md"], ["set.doc.window", "docs/watch.md"], ["set.doc.terminal", "docs/terminal.md"],
  ["set.doc.agents", "docs/agents.md"]];
const set = { data: null, sec: null, trash: null, fields: [] };

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw Object.assign(new Error(body?.error || `${r.status} ${r.statusText}`), { status: r.status, code: body?.code, params: body?.params });
  return body;
}
const reason = (e) => (e.code && has(e.code) ? t(e.code, e.params || {}) : e.message);
const fullTime = (ts) => { try { return new Date(ts).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" }); } catch { return ts; } };
function money(v) {
  const n = +v || 0;
  const digits = n > 0 && n < 1 ? 3 : 2;
  return new Intl.NumberFormat(lang, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: digits }).format(n);
}
const count = (n) => new Intl.NumberFormat(lang).format(n || 0);

// ---------------------------------------------------------------- the per-field result: saving, saved, not saved
function saveState(el) {
  let timer = 0;
  const show = (cls, glyph, text) => {
    clearTimeout(timer);
    el.className = `save-state ${cls}`;
    el.replaceChildren(glyph, h("span", { text }));
  };
  return {
    busy: () => show("is-busy", h("span", { class: "spin-inline", "aria-hidden": "true" }), t("set.saving")),
    ok: (text = t("set.saved")) => {
      show("is-ok", icon("i-tick"), text);
      timer = setTimeout(() => { el.className = "save-state"; el.replaceChildren(); }, 2600);
    },
    fail: (why) => show("is-bad", icon("i-alert"), t("set.notSaved", { why })),
    clear: () => { clearTimeout(timer); el.className = "save-state"; el.replaceChildren(); },
  };
}

// A number saved on Enter or when the field is left; Escape puts the saved value back. A refused value stays in the
// field with the reason under it, so nothing typed is lost.
function numberField(row, { id, label, about, unit = null, integer = false, min = 0, max = 100000, positive = false, value, save, facts = null }) {
  const input = h("input", { id, type: "text", inputmode: integer ? "numeric" : "decimal", autocomplete: "off", spellcheck: "false", "aria-describedby": `${id}-msg ${id}-about` });
  const field = h("div", { class: "field line-field num-field" }, unit ? h("span", { class: "unit", text: unit, "aria-hidden": "true" }) : null, input);
  const msg = h("p", { class: "field-msg", id: `${id}-msg`, "aria-live": "polite" });
  const stateEl = h("span", { class: "save-state", "aria-live": "polite" });
  const st = saveState(stateEl);
  let saved = value, saving = false, again = false, refused;
  const shown = (v) => (v == null ? "" : String(v));
  input.value = shown(saved);
  const hint = () => (integer ? t("set.v.whole", { min, max }) : t(positive ? "set.v.positive" : "set.v.amount", { max: count(max) }));
  function parse() {
    const raw = input.value.trim().replace(/^\$/, "").replace(",", ".");
    if (!/^\d+(\.\d+)?$/.test(raw)) return { bad: hint() };
    const n = Number(raw);
    if (integer && !Number.isInteger(n)) return { bad: hint() };
    if (n < min || n > max || (positive && n === 0)) return { bad: hint() };
    return { value: n };
  }
  function check() {
    const p = parse();
    field.classList.toggle("is-bad", !!p.bad);
    input.setAttribute("aria-invalid", String(!!p.bad));
    msg.className = `field-msg ${p.bad ? "is-bad" : ""}`;
    msg.textContent = p.bad || "";
    return p;
  }
  async function commit(asked = false) {
    const p = check();
    if (p.bad || p.value === saved || (!asked && p.value === refused)) return;
    if (saving) { again = true; return; }
    saving = true;
    st.busy();
    try {
      await save(p.value);
      saved = p.value;
      refused = undefined;
      st.ok();
    } catch (e) {
      refused = p.value;
      field.classList.add("is-bad");
      st.fail(reason(e));
    }
    saving = false;
    if (again) { again = false; commit(); }
  }
  input.addEventListener("input", () => { check(); if (stateEl.classList.contains("is-bad")) st.clear(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(true); }
    else if (e.key === "Escape" && input.value !== shown(saved)) { e.preventDefault(); input.value = shown(saved); check(); st.clear(); }
  });
  input.addEventListener("blur", () => commit());
  row.replaceChildren(
    h("div", { class: "set-label" }, h("label", { for: id, text: label }), h("p", { id: `${id}-about`, text: about })),
    h("div", { class: "set-ctl stack" }, h("div", { class: "ctl-line" }, field, stateEl), msg, facts));
  const api = { flush: () => commit(), set: (v) => { if (!saving && input.value === shown(saved)) { saved = v; input.value = shown(v); } } };
  set.fields.push(api);
  return api;
}

// ---------------------------------------------------------------- confirmation, for what cannot be undone
const dlg = $("confirmDlg"), go = $("confirmGo"), cancel = $("confirmCancel");
let asking = null, running = false;
function confirmThen({ title, body, action, run }) {
  asking = { run };
  $("confirmTitle").textContent = title;
  $("confirmBody").textContent = body;
  $("confirmGoText").textContent = action;
  $("confirmErr").hidden = true;
  dlg.returnTo = document.activeElement;
  dlg.showModal();
  cancel.focus();           // the safe answer has the focus
}
$("confirmForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (running || !asking) return;
  running = true;
  busy(go, true);
  disable(cancel, t("pages.working"), t("pages.cancel"));
  try {
    const after = await asking.run();
    running = false;
    dlg.close();
    if (typeof after === "function") after();
  } catch (err) {
    $("confirmErr").hidden = false;
    $("confirmErr").textContent = reason(err);
    running = false;
  }
  busy(go, false);
  disable(cancel, null, t("pages.cancel"));
});
pressable(cancel, () => { if (!running) dlg.close(); });
dlg.addEventListener("cancel", (e) => { if (running) e.preventDefault(); });
dlg.addEventListener("close", () => {
  asking = null;
  const back = dlg.returnTo;
  if (back?.isConnected && !back.closest("[hidden]")) back.focus();
  else $(`tab-${set.sec}`)?.focus();
});
let downOn = null;
dlg.addEventListener("pointerdown", (e) => { downOn = e.target; });
dlg.addEventListener("click", (e) => { if (e.target === dlg && downOn === dlg && !running) dlg.close(); downOn = null; });

// ---------------------------------------------------------------- sections
const tabs = [...$("tabs").querySelectorAll('[role="tab"]')];
function showSec(sec, focus = false) {
  if (!SECS.includes(sec)) sec = "appearance";
  for (const f of set.fields) f.flush();
  set.sec = sec;
  for (const b of tabs) {
    const on = b.dataset.sec === sec;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
  }
  // Appearance and Trash work without the settings; the rest wait for them
  const ready = (s) => !!set.data || s === "appearance" || s === "trash";
  for (const s of SECS) $(`sec-${s}`).hidden = s !== sec || !ready(s);
  const waiting = !ready(sec);
  $("loadErr").hidden = !(waiting && loadFailed);
  $("loading").hidden = !(waiting && loadingNow);
  if (location.hash.slice(1) !== sec) history.replaceState(history.state, "", `#${sec}`);
  $("setBody").scrollTop = 0;
}
for (const b of tabs) b.addEventListener("click", () => showSec(b.dataset.sec));
$("tabs").addEventListener("keydown", (e) => {
  const i = tabs.findIndex((b) => b.dataset.sec === set.sec);
  const to = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to == null) return;
  e.preventDefault();
  showSec(tabs[(to + tabs.length) % tabs.length].dataset.sec, true);
});
addEventListener("hashchange", () => showSec(location.hash.slice(1)));
addEventListener("pagehide", () => { for (const f of set.fields) f.flush(); });

// ---------------------------------------------------------------- appearance
setupLanguage($("langBtn"), $("langMenu"), $("langName"), () => { for (const f of set.fields) f.flush(); });
const themeSeg = $("themeSeg");
setupTheme(themeSeg);
// the sidebar has the same switch: this one follows it
new MutationObserver(() => {
  const pick = document.documentElement.dataset.themePick;
  for (const b of themeSeg.children) b.setAttribute("aria-pressed", String(b.dataset.pick === pick));
}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme-pick"] });

// ---------------------------------------------------------------- loading
let loadingNow = true, loadFailed = false;
async function load() {
  loadingNow = true;
  try {
    set.data = await getJSON("/api/settings");
    loadFailed = false;
  } catch (e) {
    loadFailed = !set.data;
    $("loadErrText").textContent = t("set.loadFailed", { why: e.message });
  }
  loadingNow = false;
  if (set.data) render();
  showSec(set.sec || location.hash.slice(1));
}
const retry = $("retryBtn");
tip(retry, t("pages.retry"));
pressable(retry, async () => {
  busy(retry, true);
  await load();
  busy(retry, false);
  if (set.data) note($(`tab-${set.sec}`), t("set.loaded"), "is-ok");
});

let rendered = false;
function render() {
  const d = set.data;
  renderEngines();
  renderChecks();
  renderKeys();
  renderSpend();
  renderAbout();
  if (rendered) return;
  rendered = true;
  const b = d.budgets || {};
  set.parallel = numberField($("parallelRow"), {
    id: "parallel", label: t("set.parallel"), about: t("set.parallelAbout"), integer: true, min: 1, max: 8,
    value: d.parallel, save: (v) => saveSettings({ parallel: v }), facts: h("p", { class: "ctl-facts", id: "parallelNow" }),
  });
  set.request = numberField($("requestRow"), {
    id: "requestBudget", label: t("set.budget.request"), about: t("set.budget.requestAbout"), unit: "$", positive: true,
    value: b.request_usd ?? null, save: (v) => saveBudget("request_usd", v),
  });
  set.project = numberField($("projectRow"), {
    id: "projectBudget", label: t("set.budget.project"), about: t("set.budget.projectAbout"), unit: "$",
    value: b.project_usd ?? null, save: (v) => saveBudget("project_usd", v),
  });
  set.floor = numberField($("floorRow"), {
    id: "balanceFloor", label: t("set.budget.floor"), about: t("set.budget.floorAbout"), unit: "$",
    value: b.min_balance_usd ?? null, save: (v) => saveBudget("min_balance_usd", v),
  });
  showParallelNow();
}

// the server writes only the keys it is given
async function saveSettings(change) {
  await post("/api/settings", change);
  for (const k of ["default_engine", "parallel"]) if (k in change) set.data[k] = change[k];
}
async function saveBudget(key, v) {
  await saveSettings({ budgets: { [key]: v } });
  set.data.budgets = { ...(set.data.budgets || {}), [key]: v };
}

async function showParallelNow() {
  try {
    const app = await getJSON("/api/app");
    const p = app.parallel || {};
    $("parallelNow").textContent = t("set.parallelNow", { running: p.running ?? 0, queued: p.queued ?? 0 });
  } catch { /* the facts are a courtesy */ }
}

// ---------------------------------------------------------------- agent: the engines
const engineState = saveState($("engineState"));
let engineTimer = 0;
function engineWhy(e) {
  if (e.code && has(e.code)) return t(e.code, e.params || {});
  return t(e.available ? "set.engine.ready" : "set.engine.notReady");
}
function renderEngines() {
  const d = set.data;
  const rows = d.engines || [];
  $("engines").replaceChildren(...(rows.length ? rows.map((e) => {
    const input = h("input", { type: "radio", name: "engine", value: e.id, id: `engine-${e.id}`, "aria-describedby": `engine-${e.id}-why` });
    input.checked = e.id === d.default_engine;
    input.addEventListener("change", () => {
      clearTimeout(engineTimer);
      engineTimer = setTimeout(() => saveEngine(e.id), 300);      // arrows walk the group; the last stop is saved
    });
    return h("label", { class: `engine-row ${e.available ? "is-ready" : "is-off"}`, for: `engine-${e.id}` },
      input, h("span", { class: "radio", "aria-hidden": "true" }),
      h("span", { class: "engine-text" },
        h("span", { class: "engine-name" }, h("b", { text: e.label || e.id }), h("code", { class: "faint", text: e.id })),
        h("span", { class: "engine-why", id: `engine-${e.id}-why` }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", { text: engineWhy(e) }))));
  }) : [h("p", { class: "small-empty", text: t("set.engine.none") })]));
}
async function saveEngine(id) {
  if (id === set.data.default_engine) { engineState.clear(); return; }
  engineState.busy();
  try {
    await saveSettings({ default_engine: id });
    set.data.default_engine = id;
    engineState.ok();
  } catch (e) {
    engineState.fail(reason(e));          // the choice stays marked, so the next choice or Enter tries again
  }
}
$("engines").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.name === "engine") { e.preventDefault(); clearTimeout(engineTimer); saveEngine(e.target.value); }
});

// ---------------------------------------------------------------- providers: write-only keys
let openEditor = null;
function renderKeys() {
  const keys = set.data.keys || [];
  $("keysEmpty").hidden = !!keys.length;
  $("keys").replaceChildren(...keys.map(keyRow));
  const env = set.data.env_path || "";
  $("envPath").textContent = env;
  tip($("envPath"), env);
}
function keyRow(k) {
  const stateText = h("span");
  const state = h("span", { class: "key-state" }, h("span", { class: "dot", "aria-hidden": "true" }), stateText);
  const setBtn = h("button", { class: "text-btn", type: "button" }, icon("i-key"), h("span"));
  const delBtn = h("button", { class: "text-btn quiet-danger", type: "button" }, icon("i-trash"), h("span", { text: t("set.key.remove") }), h("span", { class: "spin", "aria-hidden": "true" }));
  const use = Array.isArray(k.used_for) ? k.used_for.join(", ") : k.used_for || "";
  const row = h("li", { class: "key-row", "data-name": k.name },
    h("div", { class: "key-main" }, h("span", { class: "mono key-name", text: k.name }), state, h("span", { class: "grow" }), setBtn, delBtn),
    use ? h("p", { class: "key-use", text: t("set.key.usedFor", { what: use }) }) : null);
  const paint = () => {
    const fromEnv = k.present && k.where === "environment";
    state.className = `key-state ${k.present ? "is-present" : "is-missing"}`;
    stateText.textContent = t(!k.present ? "set.key.missing" : fromEnv ? "set.key.fromEnv" : "set.key.present");
    tip(state, fromEnv ? t("set.key.fromEnvTip", { name: k.name }) : "");
    setBtn.lastChild.textContent = t(k.present ? "set.key.replace" : "set.key.set");
    tip(setBtn, t(k.present ? "set.key.replaceTip" : "set.key.setTip", { name: k.name }));
    delBtn.hidden = !k.present || fromEnv;
    tip(delBtn, t("set.key.removeTip", { name: k.name }));
  };
  paint();
  pressable(setBtn, () => editKey(row, k, setBtn, paint));
  pressable(delBtn, () => confirmThen({
    title: t("set.key.removeTitle", { name: k.name }),
    body: t("set.key.removeBody", { name: k.name }),
    action: t("set.key.removeGo"),
    run: async () => {
      await post("/api/settings/key/delete", { name: k.name });
      k.present = false;
      k.where = null;
      paint();
      return () => note(state, t("set.key.removed", { name: k.name }), "is-ok");
    },
  }));
  return row;
}
function editKey(row, k, opener, paint) {
  if (openEditor) openEditor.close(openEditor.row !== row);
  if (openEditor?.row === row) { openEditor = null; return; }
  const input = h("input", { type: "password", autocomplete: "new-password", spellcheck: "false", autocapitalize: "off",
    "aria-label": t("set.key.valueLabel", { name: k.name }), "aria-describedby": `key-${k.name}-msg` });
  const field = h("div", { class: "field line-field key-field" }, input);
  const save = h("button", { class: "btn sm primary", type: "submit" }, h("span", { text: t("set.key.save") }), h("span", { class: "spin", "aria-hidden": "true" }));
  const back = h("button", { class: "text-btn", type: "button", text: t("pages.cancel") });
  const msg = h("p", { class: "field-msg", id: `key-${k.name}-msg`, "aria-live": "polite", text: t("set.key.hint") });
  const form = h("form", { class: "key-edit", autocomplete: "off", novalidate: true },
    h("div", { class: "ctl-line" }, field, save, back), msg);
  let saving = false;
  const valid = () => {
    const v = input.value;
    const bad = !v.trim() ? null : /\s/.test(v.trim()) || v.length > 4096 ? t("set.key.badValue") : null;
    disable(save, !v.trim() ? t("set.key.needValue") : bad, t("set.key.saveTip", { name: k.name }));
    field.classList.toggle("is-bad", !!bad);
    msg.className = `field-msg ${bad ? "is-bad" : ""}`;
    msg.textContent = bad || t("set.key.hint");
    return v.trim() && !bad;
  };
  const close = (refocus = true) => {
    input.value = "";
    form.remove();
    opener.setAttribute("aria-expanded", "false");
    if (openEditor?.row === row) openEditor = null;
    if (refocus) opener.focus();
  };
  input.addEventListener("input", valid);
  input.addEventListener("keydown", (e) => { if (e.key === "Escape" && !saving) { e.preventDefault(); e.stopPropagation(); close(); } });
  pressable(back, () => { if (!saving) close(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (saving) return;
    if (!valid()) { note(save, save.dataset.tip, "is-error"); input.focus(); return; }
    saving = true;
    busy(save, true);
    input.readOnly = true;
    try {
      await post("/api/settings/key", { name: k.name, value: input.value.trim() });
      k.present = true;
      k.where = "env_file";
      paint();
      close();
      note(opener, t("set.key.saved", { name: k.name }), "is-ok");
    } catch (err) {
      msg.className = "field-msg is-bad";
      field.classList.add("is-bad");
      msg.textContent = t("set.notSaved", { why: reason(err) });
      input.readOnly = false;
      input.focus();
    }
    saving = false;
    busy(save, false);
  });
  row.append(form);
  opener.setAttribute("aria-expanded", "true");
  openEditor = { row, close };
  valid();
  input.focus();
}
const envReveal = $("envReveal");
tip(envReveal, t("set.envRevealTip"));
pressable(envReveal, () => reveal(envReveal, "env"));

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

// ---------------------------------------------------------------- spend
function renderSpend() {
  const s = set.data.spend || { month_usd: 0, by_tool: [] };
  $("monthSum").textContent = money(s.month_usd);
  const rows = (s.by_tool || []).slice().sort((a, b) => (b.usd || 0) - (a.usd || 0));
  $("spendEmpty").hidden = !!rows.length;
  $("spendTable").hidden = !rows.length;
  $("spendRows").replaceChildren(...rows.map((r) => h("tr", {},
    h("td", { class: "mono", text: r.tool }), h("td", { class: "n num", text: count(r.calls) }), h("td", { class: "n num", text: money(r.usd) }))));
}

// ---------------------------------------------------------------- system checks
function renderChecks(list = set.data.checks || []) {
  const failing = list.filter((c) => !c.ok && c.required).length;
  const optional = list.filter((c) => !c.ok && !c.required).length;
  $("checksEmpty").hidden = !!list.length;
  $("checksSummary").textContent = !list.length ? "" : failing ? t("set.checks.failing", { n: failing })
    : optional ? t("set.checks.optional", { n: optional }) : t("set.checks.allPass");
  $("checksSummary").className = `sec-about ${failing ? "is-bad" : ""}`;
  $("systemFlag").hidden = !failing;
  tip($("systemFlag"), failing ? t("set.checks.failing", { n: failing }) : "");
  $("checks").replaceChildren(...list.map((c) => {
    const kind = c.ok ? "is-ok" : c.required ? "is-bad" : "is-warn";
    const word = c.ok ? "set.checks.ok" : c.required ? "set.checks.fail" : "set.checks.absent";
    let fix = null;
    if (!c.ok && c.fix) {
      const copy = h("button", { class: "icon-btn sm", type: "button" }, icon("i-copy"));
      tip(copy, t("set.checks.copyFix"));
      pressable(copy, () => copyText(c.fix, copy));
      fix = h("div", { class: "check-fix" }, h("span", { class: "faint", text: t("set.checks.fixLabel") }), h("code", { text: c.fix }), copy);
    }
    return h("li", { class: `check ${kind}` },
      icon(c.ok ? "i-okc" : c.required ? "i-fail" : "i-warn", "check-glyph"),
      h("div", { class: "check-text" },
        h("div", { class: "check-head" }, h("b", { text: c.name }), h("span", { class: "check-word", text: t(word) }),
          h("span", { class: "check-req faint", text: t(c.required ? "set.checks.required" : "set.checks.optionalOne") })),
        c.detail ? h("p", { class: "check-detail", text: c.detail }) : null, fix));
  }));
}
const checksBtn = $("checksBtn");
tip(checksBtn, t("set.checks.runTip"));
pressable(checksBtn, async () => {
  busy(checksBtn, true);
  $("checks").setAttribute("aria-busy", "true");
  try {
    const got = await post("/api/settings/checks", {});
    set.data.checks = Array.isArray(got) ? got : got?.checks || [];
    renderChecks();
    const failing = set.data.checks.filter((c) => !c.ok && c.required).length;
    note(checksBtn, failing ? t("set.checks.failing", { n: failing }) : t("set.checks.ran"), failing ? "is-error" : "is-ok");
  } catch (e) {
    note(checksBtn, t("set.checks.runFailed", { why: reason(e) }), "is-error");
  }
  $("checks").setAttribute("aria-busy", "false");
  busy(checksBtn, false);
});

async function copyText(text, btn) {
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch {
    const ta = h("textarea", { class: "offscreen", "aria-hidden": "true" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    btn.focus();
  }
  note(btn, t(ok ? "pages.copied" : "pages.copyFailed"), ok ? "is-ok" : "is-error");
}

// ---------------------------------------------------------------- trash
let trashLoading = null;
async function loadTrash() {
  if (trashLoading) return trashLoading;
  trashLoading = (async () => {
    try {
      set.trash = await getJSON("/api/trash");
      $("trashErr").hidden = true;
    } catch (e) {
      if (!set.trash) {
        $("trashErr").hidden = false;
        $("trashErrText").textContent = t("set.trash.loadFailed", { why: e.message });
      }
    }
    renderTrash();
  })();
  await trashLoading;
  trashLoading = null;
}
const trashRetry = $("trashRetry");
tip(trashRetry, t("pages.retry"));
pressable(trashRetry, async () => { busy(trashRetry, true); await loadTrash(); busy(trashRetry, false); });

function renderTrash() {
  const list = set.trash;
  $("trashCount").textContent = list?.length ? String(list.length) : "";
  $("trashEmpty").hidden = !list || !!list.length;
  $("trash").replaceChildren(...(list || []).map(trashRow));
}
function trashRow(f) {
  const title = f.title || f.name;
  const restore = h("button", { class: "text-btn", type: "button" }, icon("i-undo"), h("span", { text: t("set.trash.restore") }), h("span", { class: "spin", "aria-hidden": "true" }));
  const del = h("button", { class: "text-btn quiet-danger", type: "button" }, icon("i-trash"), h("span", { text: t("set.trash.delete") }));
  tip(restore, t("set.trash.restoreTip", { title }));
  tip(del, t("set.trash.deleteTip", { title }));
  const when = h("span", { text: f.trashed_at ? t("set.trash.when", { ago: ago(f.trashed_at) }) : "" });
  if (f.trashed_at) tip(when, fullTime(f.trashed_at));
  const row = h("li", { class: "trash-row", "data-id": f.id },
    h("div", { class: "trash-text" },
      h("div", { class: "trash-name" }, h("b", { text: title }), f.title ? h("code", { class: "faint", text: f.name }) : null),
      h("div", { class: "trash-meta" }, when, f.size_bytes != null ? h("span", { class: "sep", "aria-hidden": "true" }) : null,
        f.size_bytes != null ? h("span", { class: "num", text: bytes(f.size_bytes) }) : null)),
    restore, del);
  const gone = () => {
    set.trash = set.trash.filter((x) => x.id !== f.id);
    const next = row.nextElementSibling || row.previousElementSibling;
    renderTrash();
    const to = next && $("trash").querySelector(`[data-id="${CSS.escape(next.dataset.id)}"] button`);
    return to || $("tab-trash");
  };
  pressable(restore, async () => {
    busy(restore, true);
    disable(del, t("pages.working"), t("set.trash.deleteTip", { title }));
    try {
      const got = await post(`/api/trash/${encodeURIComponent(f.id)}/restore`, {});
      note($("tab-trash"), t("set.trash.restored", { title: got?.name && got.name !== f.name ? `${title} (${got.name})` : title }), "is-ok");
      gone().focus();
    } catch (e) {
      busy(restore, false);
      disable(del, null, t("set.trash.deleteTip", { title }));
      note(restore, t("set.trash.restoreFailed", { why: reason(e) }), "is-error");
    }
  });
  pressable(del, () => confirmThen({
    title: t("set.trash.deleteTitle", { title }),
    body: t("set.trash.deleteBody", { name: f.name }),
    action: t("set.trash.deleteGo"),
    run: async () => {
      await post(`/api/trash/${encodeURIComponent(f.id)}/delete`, {});
      dlg.returnTo = gone();
      return () => note($("tab-trash"), t("set.trash.deleted", { title }), "is-ok");
    },
  }));
  return row;
}
// a film trashed from the sidebar shows up here without a reload
let trashTimer = 0;
try { shell?.on?.("films", () => { clearTimeout(trashTimer); trashTimer = setTimeout(loadTrash, 300); }); } catch { /* an older frame */ }

// ---------------------------------------------------------------- about
function renderAbout() {
  const d = set.data;
  $("aboutVersion").textContent = d.version || "";
  $("aboutLicence").textContent = d.licence || "";
  $("aboutPath").textContent = d.workspace_path || "";
  tip($("aboutPath"), d.workspace_path || "");
  $("docLinks").replaceChildren(...[...DOCS, ["set.doc.repo", ""]].map(([key, path]) =>
    h("li", {}, h("a", { class: "ext-link", href: path ? `${REPO}/blob/main/${path}` : REPO, target: "_blank", rel: "noopener noreferrer" },
      h("span", { text: t(key) }), icon("i-ext")))));
}
const wsReveal = $("wsReveal");
tip(wsReveal, t("set.wsRevealTip"));
pressable(wsReveal, () => reveal(wsReveal, "workspace"));

showSec(location.hash.slice(1));
loadTrash();
load().then(() => requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready"))));
