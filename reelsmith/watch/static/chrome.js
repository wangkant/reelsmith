// The language menu and the theme switch, shared by the project page and the home.
import { LANGS, lang, setLang, t } from "./i18n.js";
import { h, icon, menuButton, note, pressable, storage, store, tip } from "./util.js";

export function setupLanguage(btn, menu, nameEl, beforeReload = () => {}) {
  const own = LANGS.find(([c]) => c === lang)[1];
  nameEl.textContent = own;
  tip(btn, t("top.language"), null, `${t("top.language")}: ${own}`);
  menu.replaceChildren(h("div", { class: "menu-title", text: t("top.language") }), ...LANGS.map(([code, name]) =>
    h("button", { type: "button", class: "menu-item", role: "menuitemradio", "aria-checked": String(code === lang), lang: code, tabindex: "-1", "data-code": code },
      h("span", { text: name }), icon("i-tick"))));
  const ctl = menuButton(btn, menu, (list) => Math.max(0, list.findIndex((b) => b.dataset.code === lang)));
  menu.addEventListener("click", (e) => {
    const b = e.target.closest(".menu-item");
    if (!b) return;
    if (b.dataset.code === lang) { ctl.close(true); return; }
    setLang(b.dataset.code);
    beforeReload();
    location.reload();
  });
  return ctl;
}

// Light, dark or the system's; onApply hears every change (the canvas colours follow it).
export function setupTheme(seg, onApply = () => {}) {
  const dark = matchMedia("(prefers-color-scheme: dark)");
  // the desktop window's border (and, with the system frame, its title bar) follows the page; a browser tab has none
  const nativeTheme = () => { try { window.pywebview?.api?.set_theme?.(document.documentElement.dataset.theme); } catch { /* a browser */ } };
  function apply(pick, said) {
    const root = document.documentElement;
    root.dataset.themePick = pick;
    root.dataset.theme = pick === "system" ? (dark.matches ? "dark" : "light") : pick;
    for (const b of seg.children) {
      b.setAttribute("aria-pressed", String(b.dataset.pick === pick));
      tip(b, t(`theme.${b.dataset.pick}`));
    }
    onApply();
    nativeTheme();
    if (said) note(seg, t("theme.set", { name: t(`theme.${pick}`) }));
  }
  addEventListener("pywebviewready", nativeTheme);
  seg.setAttribute("aria-label", t("theme.label"));
  for (const b of seg.children) pressable(b, () => { store("theme", b.dataset.pick); apply(b.dataset.pick, true); });
  dark.addEventListener("change", () => { if (document.documentElement.dataset.themePick === "system") apply("system"); });
  apply(storage("theme", "system"));
}

// "3 min ago" from an ISO time.
export function ago(ts) {
  const d = (Date.now() - new Date(ts).getTime()) / 1000;
  if (!(d >= 0)) return "";
  if (d < 10) return t("ago.now");
  if (d < 60) return t("ago.s", { n: Math.floor(d) });
  if (d < 3600) return t("ago.min", { n: Math.floor(d / 60) });
  if (d < 86400) return t("ago.h", { n: Math.floor(d / 3600) });
  return new Date(ts).toLocaleDateString(document.documentElement.lang, { day: "numeric", month: "short", year: new Date(ts).getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}
