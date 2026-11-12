// The New film page: a description, a suggested folder name, the format, the language and the engine.
import { json, postAt } from "./api.js";
import { has, LANGS, t, translate } from "./i18n.js";
import { mountShell } from "./shell.js";
import { busy, disable, h, handOff, installTips, isOff, note, takeHandOff } from "./util.js";

installTips();
translate();
const $ = (id) => document.getElementById(id);
const shell = mountShell({ page: "new" });
document.title = `${t("newp.title")} · reelsmith`;

const desc = $("desc"), name = $("name"), start = $("start"), create = $("create"), form = $("newForm");
const NAME = /^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$/;
// the server's list of names Windows refuses, the same one its suggestion avoids
const reserved = () => shell.app()?.names?.reserved || [];
const reason = (e) => (e?.code && has(e.code) ? t(e.code, e.params || {}) : e?.message || String(e));
let typedName = false, creating = false, suggestSeq = 0, suggestTimer = 0;
const refusedNames = new Set();
desc.placeholder = t("newp.descPh");

function nameProblem(v) {
  if (!v) return { code: "create.empty", quiet: true };
  if (v.length > 64) return { code: "create.long" };
  if (!NAME.test(v)) return { code: "create.chars" };
  if (reserved().includes(v.toLowerCase())) return { code: "create.reserved" };
  if (refusedNames.has(v.toLowerCase()) || shell.films().some((f) => f.name.toLowerCase() === v.toLowerCase())) return { code: "create.taken" };
  return null;
}
function validate() {
  const v = name.value.trim();
  const bad = nameProblem(v);
  const field = $("nameField"), msg = $("nameMsg");
  field.classList.toggle("is-bad", !!bad && !bad.quiet);
  msg.className = `fld-msg${bad && !bad.quiet ? " is-bad" : ""}`;
  msg.textContent = bad && !bad.quiet ? t(bad.code, { name: v }) : typedName || !v ? t("newp.nameHint") : `${t("newp.nameAuto")} · ${t("newp.nameHint")}`;
  name.setAttribute("aria-invalid", String(!!bad && !bad.quiet));
  const needDesc = start.checked && !desc.value.trim();
  $("descField").classList.toggle("is-bad", false);
  $("createText").textContent = t(start.checked ? "newp.createStart" : "newp.create");
  // without a name the server suggests one, so an empty name stops nothing
  const why = creating ? t("newp.busy") : needDesc ? t("newp.needDesc") : bad && !bad.quiet ? t(bad.code, { name: v }) : null;
  disable(create, why, t("newp.createTip"), "Ctrl Enter");
  $("why").textContent = creating ? "" : why || "";
  return !why;
}

async function suggest() {
  if (typedName) return;
  const text = desc.value.trim();
  const seq = ++suggestSeq;
  if (!text) { name.value = ""; validate(); return; }
  try {
    const got = await json(`/api/films/suggest?text=${encodeURIComponent(text.slice(0, 400))}`);
    if (seq === suggestSeq && !typedName) { name.value = got.name; validate(); }
  } catch { /* the server names it on create */ }
}
desc.addEventListener("input", () => { clearTimeout(suggestTimer); suggestTimer = setTimeout(suggest, 300); validate(); });
name.addEventListener("input", () => { typedName = name.value.trim() !== ""; $("formErr").hidden = true; validate(); });
start.addEventListener("change", validate);
shell.on("films", validate);

// ---------------------------------------------------------------- the choices
function option(value, text, off = false) { return h("option", { value, disabled: off || null, text }); }
async function loadChoices() {
  const lang = $("locale");
  lang.replaceChildren(option("", t("newp.localeDefault")), ...LANGS.map(([code, own]) => option(code, `${own} (${code})`)));
  try {
    const f = await json("/api/formats");
    $("format").replaceChildren(option("", `${t("newp.formatDefault")} (${f.default})`),
      ...f.formats.map((x) => option(x.id, t("newp.formatOpt", { id: x.id, w: x.width, h: x.height, fps: x.fps }))));
  } catch (e) {
    $("format").replaceChildren(option("", t("newp.formatDefault")));
    $("formErr").hidden = false;
    $("formErr").textContent = t("newp.loadFailed", { why: reason(e) });
  }
  try {
    const s = await json("/api/settings");
    const def = s.engines.find((r) => r.id === s.default_engine) || s.engines.find((r) => r.available);
    $("engine").replaceChildren(option("", t("newp.engineDefault", { label: def?.label || def?.id || t("frame.engine.none") })),
      ...s.engines.map((r) => option(r.id, r.available ? r.label || r.id : t("newp.engineOff", { label: r.label || r.id }), !r.available)));
  } catch {
    $("engine").replaceChildren(option("", t("newp.engineDefault", { label: "" }).replace(/\s*[(（]\s*[)）]/, "")));
  }
}

// ---------------------------------------------------------------- create
async function submit() {
  if (creating) return;
  if (!validate()) { note(create, create.dataset.tip || "", "is-error"); (start.checked && !desc.value.trim() ? desc : name).focus(); return; }
  creating = true;
  validate();
  busy(create, true);
  for (const el of [desc, name]) el.readOnly = true;
  const body = { description: desc.value.trim() || undefined, name: name.value.trim() || undefined, start: start.checked && !!desc.value.trim() };
  for (const k of ["format", "locale", "engine"]) if ($(k).value) body[k] = $(k).value;
  try {
    const res = await postAt("/api/films", body);
    note(create, t("newp.created"), "is-ok");
    // a first request the chat refused: the film's message box receives the text and the reason
    if (res.refused && body.description) handOff(`film:${res.name}`, { text: body.description, refused: res.refused });
    location.href = res.url;          // stays busy until the film's page replaces this one
    return;
  } catch (e) {
    if (e.code === "create.taken") refusedNames.add(String(body.name || "").toLowerCase());
    $("formErr").hidden = false;
    $("formErr").textContent = t("newp.failed", { why: reason(e) });
    note(create, t("newp.failed", { why: reason(e) }), "is-error");
  }
  creating = false;
  busy(create, false);
  for (const el of [desc, name]) el.readOnly = false;
  validate();
}
form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
create.addEventListener("click", (e) => { if (isOff(create)) { e.preventDefault(); note(create, create.dataset.tip || "", "is-error"); } });
desc.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
$("cancel").addEventListener("click", (e) => { if (creating) e.preventDefault(); });

const carried = takeHandOff("new");            // the Films page's composer, with "More options"
if (carried?.text) { desc.value = carried.text; suggest(); }
validate();
loadChoices();
desc.focus();
requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
