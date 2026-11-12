// The frameless desktop window's own controls (minimise, maximise or restore, close) and its drag fallback.
// A browser tab, or a window with the system frame, shows none of it.
import { t } from "./i18n.js";
import { h, tip } from "./util.js";

const api = () => window.pywebview?.api;
const SVG = "http://www.w3.org/2000/svg";
const GLYPH = {
  min: '<path d="M0 5.5h10"/>',
  max: '<rect x="0.5" y="0.5" width="9" height="9" rx="1.5"/>',
  restore: '<rect x="0.5" y="2.5" width="7" height="7" rx="1.5"/><path d="M2.5 2.5V2A1.5 1.5 0 0 1 4 .5h4A1.5 1.5 0 0 1 9.5 2v4A1.5 1.5 0 0 1 8 7.5h-.5"/>',
  close: '<path d="m.5.5 9 9M9.5.5l-9 9"/>',
};
// where the page stands for the title bar; WebView2 moves the window from these by itself
const DRAG = ".win-drag, .side-head, .film-app .top, .shelf-head, .page-head, .set-nav > h1";
const ACTIVE = "a[href], button, input, select, textarea, label, summary, [role='button'], [role='tab'], [role='menuitem'], [tabindex], [data-tip]:not(.side-ws), [contenteditable], .conn, .status, .menu, .side-edge";

function glyph(name) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 10 10");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = GLYPH[name];
  return s;
}

export function mountWindowFrame() {
  const root = document.documentElement;
  if (!window.chrome?.webview && !root.classList.contains("frameless")) return;     // a browser tab
  const drag = h("div", { class: "win-drag", "aria-hidden": "true" });
  document.body.prepend(drag);              // first in the page, so every control after it stays clickable
  const btn = (cls, name) => h("button", { class: `win-btn ${cls}`, type: "button" }, glyph(name));
  const min = btn("win-min", "min"), max = btn("win-max", "max"), close = btn("win-close", "close");
  const grip = h("div", { class: "win-grip", "aria-hidden": "true" }, h("i", { "data-edge": "top" }), h("i", { "data-edge": "top-right" }));
  const box = h("div", { class: "win-ctl", role: "group", "aria-label": t("frame.win.label") }, min, max, close, grip);
  document.body.append(box);
  tip(min, t("frame.win.minimise"));
  tip(close, t("frame.win.close"));

  let maximised = false;
  function render() {
    root.classList.toggle("is-maximised", maximised);
    max.replaceChildren(glyph(maximised ? "restore" : "max"));
    tip(max, t(maximised ? "frame.win.restore" : "frame.win.maximise"));
  }
  render();
  const take = (s) => {
    if (!s) return;
    try { sessionStorage.setItem("rs-watch:frame", s.frame); } catch { /* storage refused */ }
    root.classList.toggle("frameless", s.frame === "frameless");
    if (s.frame !== "frameless") return;
    maximised = !!s.maximised;
    render();
  };
  const ask = () => api()?.window_state?.().then(take).catch(() => {});
  const call = (name, ...a) => { try { return api()?.[name]?.(...a) ?? Promise.resolve(); } catch { return Promise.resolve(); } };

  // a click acts on release, as a title bar's buttons do; moving off before release cancels it
  min.addEventListener("click", () => call("minimise"));
  max.addEventListener("click", () => call("toggle_maximise").then(take));
  close.addEventListener("click", () => call("close"));
  // the top edge above the controls resizes, as a native window's does
  grip.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || maximised) return;
    e.preventDefault();
    call("start_resize", e.target.dataset.edge || "top");
  });

  // without WebView2's drag regions (an older runtime) the press reaches the page: the system moves the window then
  const inDrag = (e) => !e.target.closest?.(ACTIVE) && (e.clientY < drag.offsetHeight || !!e.target.closest?.(DRAG));
  addEventListener("mousedown", (e) => { if (e.button === 0 && e.detail === 1 && root.classList.contains("frameless") && inDrag(e)) call("start_drag"); });
  addEventListener("dblclick", (e) => { if (root.classList.contains("frameless") && inDrag(e)) call("toggle_maximise").then(take); });

  // a maximised or restored window resizes the page: ask then, and when the window's api arrives
  let timer = 0;
  addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(ask, 60); });
  addEventListener("pywebviewready", ask);
  if (api()) ask();
  // the controls dim while another window is in front, as the system's own do
  const focus = () => root.classList.toggle("win-inactive", !document.hasFocus());
  addEventListener("focus", focus);
  addEventListener("blur", focus);
  focus();
}
