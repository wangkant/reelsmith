import { post } from "./api.js";
import { LANGS, lang, setLang, t } from "./i18n.js";
import { busy, bytes, clamp, clock, disable, h, icon, menuButton, note, pressable, storage, store, timecode, tip } from "./util.js";

const $ = (id) => document.getElementById(id);
const orientation = (c) => (c.width > c.height ? "landscape" : c.width < c.height ? "vertical" : "square");

export function createTop(app) {
  // ---------------------------------------------------------------- title, canvas facts, the result
  function renderTop() {
    const s = app.state;
    const title = s.project?.title || app.lastGood?.project?.title || t("top.untitled");
    $("filmTitle").textContent = title;
    tip($("filmTitle"), t("top.projTip", { title, path: s.project?.path || "" }));
    document.title = `${title} · reelsmith watch`;
    const c = s.canvas || app.lastGood?.canvas;
    const info = $("canvasInfo");
    if (c?.width) {
      const len = app.cut()?.duration;
      info.replaceChildren(h("span", { class: "num", text: `${c.width} × ${c.height}` }),
        h("span", { class: "c-fps" }, " · ", h("span", { class: "num", text: t("top.fps", { n: c.fps }) })),
        ...(len ? [" · ", h("span", { class: "num", text: timecode(len, c.fps).replace(/\d$/, "") })] : []));
      tip(info, t("top.canvasTip", { orient: t(`top.orient.${orientation(c)}`), w: c.width, h: c.height, fps: c.fps }));
    } else info.replaceChildren();
    renderResult();
  }

  function renderResult() {
    const el = $("result"), s = app.state || {};
    const r = app.running ? null : app.result();
    el.className = "status";
    el.hidden = !app.state;
    if (app.running) {
      const run = app.runText();
      el.classList.add("is-run");
      $("resultTitle").textContent = run.what;
      $("resultSub").textContent = run.figures;
      tip(el, run.text);
    } else if (app.viewing) {
      $("resultTitle").textContent = t("result.history", { n: app.viewing.n });
      $("resultSub").textContent = clock(app.viewing.at);
      tip(el, t("result.historyTip"));
    } else {
      const d = s.render?.delivered;
      const facts = d ? [clock(d.at), d.duration ? timecode(d.duration, app.fps()) : null, d.lufs != null ? `${d.lufs} LUFS` : null, bytes(d.bytes)].filter(Boolean).join(" · ") : "";
      el.classList.add({ current: "is-ok", stale: "is-warn", refused: "is-err", none: "is-none" }[r.state]);
      $("resultTitle").textContent = t(`result.${r.state}`);
      $("resultSub").textContent = r.state === "refused" ? (s.render?.delivered ? t("result.refusedSub") : "") : r.state === "none" ? "" : t(`result.${r.state}Sub`);
      tip(el, r.state === "refused" ? `${r.reason}. ${r.detail || ""}`.trim() : r.state === "none" ? t("result.noneTip") : `${t(`result.${r.state}Tip`)} ${facts}`);
    }
    renderActions();
  }

  // ---------------------------------------------------------------- accept the film
  const accept = $("acceptBtn");
  let accepting = false;
  function renderActions() {
    const s = app.state || {};
    const r = app.result();
    // the primary action stands only while a delivered film matches the cut; the thread says why otherwise
    accept.hidden = !s.render || r.state !== "current" || !!app.viewing || !!app.running;
    if (!accept.hidden) {
      const done = !!r.accepted_at;
      const why = accepting ? t("accept.busy") : app.status !== "connected" ? t("status.goneTip") : app.running ? t("accept.working") : done ? t("accept.done", { at: clock(r.accepted_at || "").slice(0, 5) }) : null;
      accept.querySelector("[data-i18n]").textContent = t(done ? "top.accepted" : "top.accept");
      accept.classList.toggle("is-done", done);
      disable(accept, why, t("accept.tip"));
    }
  }
  pressable(accept, async () => {
    if (accepting) return;
    accepting = true;
    const slow = setTimeout(() => busy(accept, true), 150);
    try {
      await post("/api/accept", {});
      note(accept, t("accept.ok"), "is-ok");
      app.refresh();
    } catch (e) {
      note(accept, t("accept.failed", { why: e.code && t(e.code) !== e.code ? t(e.code, e.params || {}) : e.message }), "is-error");
    } finally {
      clearTimeout(slow);
      busy(accept, false);
      accepting = false;
    }
  });
  // ---------------------------------------------------------------- the agent, in the session head; the stage's tag
  function ago(ts) {
    const d = (Date.now() - new Date(ts).getTime()) / 1000;
    if (!(d >= 0)) return "";
    if (d < 10) return t("ago.now");
    if (d < 60) return t("ago.s", { n: Math.floor(d) });
    if (d < 3600) return t("ago.min", { n: Math.floor(d / 60) });
    return t("ago.h", { n: Math.floor(d / 3600) });
  }
  function renderAgent() {
    const el = $("agent"), r = app.running;
    $("timeline").classList.toggle("is-working", !!r);
    if (r) {
      const run = app.runText();
      el.dataset.state = run.stuck ? "stuck" : "running";
      $("agentText").textContent = t("status.working", { what: run.lower });
      tip(el, run.stuck ? t("run.stuckTip", { what: run.what, ago: run.elapsed }) : run.text);
    } else if (app.chatBusy) {
      el.dataset.state = "running";
      $("agentText").textContent = t("status.working", { what: app.chatBusy });
      tip(el, t("status.tip"));
    } else {
      const last = app.state?.activity?.at(-1)?.ts;
      el.dataset.state = !app.state ? "off" : last || app.noEngine ? "idle" : "ready";
      $("agentText").textContent = app.noEngine ? t("chat.noEngine") : last ? t("status.idleAgo", { ago: ago(last) }) : t("status.ready");
      tip(el, app.noEngine ? t("chat.noEngineBody").replace(/[:：]\s*$/, "") : t("status.tip"));
    }
    const tag = $("workTag"), wb = $("workBar");
    tag.hidden = !r;
    wb.hidden = !r || typeof r.progress !== "number";
    if (r) {
      $("workText").textContent = app.runText().text;
      wb.style.setProperty("--p", `${clamp(r.progress * 100, 0, 100)}%`);
    }
    renderResult();
  }
  function renderConn() {
    const c = $("conn");
    c.dataset.state = app.status;
    $("connText").textContent = t(`status.${app.status}`);
    tip(c, t("status.goneTip"));
    app.emit("conn");
  }

  // ---------------------------------------------------------------- language
  const langBtn = $("langBtn"), langMenu = $("langMenu");
  $("langName").textContent = LANGS.find(([c]) => c === lang)[1];
  tip(langBtn, t("top.language"), null, `${t("top.language")}: ${LANGS.find(([c]) => c === lang)[1]}`);
  langMenu.replaceChildren(h("div", { class: "menu-title", text: t("top.language") }), ...LANGS.map(([code, name]) => {
    const b = h("button", { type: "button", class: "menu-item", role: "menuitemradio", "aria-checked": String(code === lang), lang: code, tabindex: "-1", "data-code": code },
      h("span", { text: name }), icon("i-tick"));
    return b;
  }));
  const langs = menuButton(langBtn, langMenu, (list) => Math.max(0, list.findIndex((b) => b.dataset.code === lang)));
  app.closeMenus = () => langs.close(true);
  langMenu.addEventListener("click", (e) => {
    const b = e.target.closest(".menu-item");
    if (!b) return;
    if (b.dataset.code === lang) { langs.close(true); return; }
    setLang(b.dataset.code);
    try { sessionStorage.setItem("rs-watch:resume", JSON.stringify({ time: app.time, beat: app.beat })); } catch { /* private window */ }
    location.reload();
  });

  // ---------------------------------------------------------------- theme: light, dark, system
  const seg = $("themeSeg"), dark = matchMedia("(prefers-color-scheme: dark)");
  function applyTheme(pick, said) {
    const root = document.documentElement;
    root.dataset.themePick = pick;
    root.dataset.theme = pick === "system" ? (dark.matches ? "dark" : "light") : pick;
    for (const b of seg.children) {
      b.setAttribute("aria-pressed", String(b.dataset.pick === pick));
      tip(b, t(`theme.${b.dataset.pick}`));
    }
    app.emit("theme");
    nativeTheme();
    if (said) note(seg, t("theme.set", { name: t(`theme.${pick}`) }));
  }
  // the desktop window's own title bar follows the page (a browser tab has none to set)
  const nativeTheme = () => { try { window.pywebview?.api?.set_theme?.(document.documentElement.dataset.theme); } catch { /* a browser */ } };
  addEventListener("pywebviewready", nativeTheme);
  seg.setAttribute("aria-label", t("theme.label"));
  for (const b of seg.children) pressable(b, () => { store("theme", b.dataset.pick); applyTheme(b.dataset.pick, true); });
  dark.addEventListener("change", () => { if (document.documentElement.dataset.themePick === "system") applyTheme("system"); });
  applyTheme(storage("theme", "system"));

  // ---------------------------------------------------------------- the divider between the session and the stage
  const split = $("colSplit");
  const fallback = () => Math.round(clamp(innerWidth * 0.356, 380, 560));
  const maxW = () => Math.max(340, Math.min(680, innerWidth - 560));
  let userW = storage("session-w", null);
  function applyWidth() {
    const w = Math.round(clamp(userW ?? fallback(), 340, maxW()));
    document.documentElement.style.setProperty("--session-w", `${w}px`);
    split.setAttribute("aria-valuenow", String(w));
    split.setAttribute("aria-valuemin", "340");
    split.setAttribute("aria-valuemax", String(maxW()));
  }
  function setWidth(px) {
    userW = Math.round(clamp(px, 340, maxW()));
    store("session-w", userW);
    applyWidth();
    app.emit("layout");
  }
  tip(split, t("split.tip"), null, t("split.name"));
  split.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    split.setPointerCapture(e.pointerId);
    split.classList.add("is-dragging");
    document.body.classList.add("is-resizing");
    const move = (ev) => setWidth(ev.clientX);
    const up = () => {
      split.classList.remove("is-dragging");
      document.body.classList.remove("is-resizing");
      split.removeEventListener("pointermove", move);
      split.removeEventListener("pointerup", up);
      split.removeEventListener("pointercancel", up);
    };
    split.addEventListener("pointermove", move);
    split.addEventListener("pointerup", up);
    split.addEventListener("pointercancel", up);
  });
  function resetWidth() {
    userW = null;
    store("session-w", null);
    applyWidth();
    app.emit("layout");
    note(split, t("split.auto"));
  }
  split.addEventListener("dblclick", resetWidth);
  split.addEventListener("keydown", (e) => {
    const cur = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--session-w")) || fallback();
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      e.stopPropagation();
      setWidth(cur + (e.key === "ArrowRight" ? 24 : -24));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      e.stopPropagation();
      resetWidth();
    }
  });
  applyWidth();
  addEventListener("resize", applyWidth);

  return { renderTop, renderResult, renderAgent, renderConn };
}
