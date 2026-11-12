import de from "./i18n/de.js";
import en from "./i18n/en.js";
import es from "./i18n/es.js";
import fr from "./i18n/fr.js";
import ja from "./i18n/ja.js";
import ko from "./i18n/ko.js";
import zhCN from "./i18n/zh-CN.js";
import zhTW from "./i18n/zh-TW.js";
import dePages from "./i18n/pages/de.js";
import enPages from "./i18n/pages/en.js";
import esPages from "./i18n/pages/es.js";
import frPages from "./i18n/pages/fr.js";
import jaPages from "./i18n/pages/ja.js";
import koPages from "./i18n/pages/ko.js";
import zhCNPages from "./i18n/pages/zh-CN.js";
import zhTWPages from "./i18n/pages/zh-TW.js";

// Each language names itself in its own script; the order is the menu's.
export const LANGS = [
  ["en", "English", { ...en, ...enPages }], ["zh-CN", "简体中文", { ...zhCN, ...zhCNPages }],
  ["zh-TW", "繁體中文", { ...zhTW, ...zhTWPages }], ["ja", "日本語", { ...ja, ...jaPages }],
  ["ko", "한국어", { ...ko, ...koPages }], ["es", "Español", { ...es, ...esPages }],
  ["fr", "Français", { ...fr, ...frPages }], ["de", "Deutsch", { ...de, ...dePages }],
];
const BY = Object.fromEntries(LANGS.map(([code, , d]) => [code, d]));
const KEY = "rs-watch:lang";

function fromSystem() {
  for (const raw of navigator.languages || [navigator.language || "en"]) {
    const l = raw.toLowerCase();
    if (/^zh-(tw|hk|mo|hant)/.test(l)) return "zh-TW";
    if (l.startsWith("zh")) return "zh-CN";
    const base = l.split("-")[0];
    if (BY[base]) return base;
  }
  return "en";
}
function chosen() {
  try { const v = JSON.parse(localStorage.getItem(KEY)); if (BY[v]) return v; } catch { /* private window */ }
  return null;
}

// ?lang= shows one language without changing the remembered choice (screenshots, support).
function fromUrl() {
  const v = new URLSearchParams(location.search).get("lang");
  return BY[v] ? v : null;
}

export const lang = fromUrl() || chosen() || fromSystem();
const dict = { ...BY.en, ...BY[lang] };
const plural = new Intl.PluralRules(lang);

// {n} picks the ".one" form when the language says n is singular and a ".one" form exists.
export function t(key, vars) {
  const one = vars && typeof vars.n === "number" && plural.select(vars.n) === "one" ? dict[`${key}.one`] : null;
  let s = one || dict[key] || key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}

export const has = (key) => key in dict;

// The choice is kept per machine; the page reloads to apply it.
export function setLang(code) {
  try { localStorage.setItem(KEY, JSON.stringify(code)); } catch { /* private window */ }
  const url = new URL(location.href);
  if (url.searchParams.has("lang")) {
    // the menu's choice must win over the address on the reload that follows
    url.searchParams.delete("lang");
    history.replaceState(history.state, "", url);
  }
}

// For the translator: the English keys a language does not have yet.
export function missingKeys(code) {
  const d = BY[code] || {};
  return Object.keys(BY.en).filter((k) => !(k in d));
}
window.__i18n = { missingKeys, langs: LANGS.map(([c]) => c) };

// Static markup: data-i18n sets text, data-i18n-title sets the tooltip and aria-label.
export function translate(root = document) {
  document.documentElement.lang = lang;
  for (const el of root.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of root.querySelectorAll("[data-i18n-title]")) {
    el.dataset.tip = t(el.dataset.i18nTitle);
    if (!el.textContent.trim() || el.tagName === "INPUT") el.setAttribute("aria-label", el.dataset.tip);
  }
}
