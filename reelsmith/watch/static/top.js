import { BASE, post } from "./api.js";
import { setupLanguage, setupTheme } from "./chrome.js";
import { t } from "./i18n.js";
import { busy, bytes, clamp, clock, disable, h, icon, menuButton, note, pressable, storage, store, timecode, tip } from "./util.js";

const $ = (id) => document.getElementById(id);
const orientation = (c) => (c.width > c.height ? "landscape" : c.width < c.height ? "vertical" : "square");

export function createTop(app) {
  // ---------------------------------------------------------------- title, canvas facts, the result
  function renderTop() {
    const s = app.state;
    const title = s.project?.title || app.lastGood?.project?.title || s.project?.name || app.lastGood?.project?.name || t("top.untitled");
    $("filmTitle").textContent = title;
    tip($("filmTitle"), t("top.projTip", { title, path: s.project?.path || "" }));
    document.title = `${title} · reelsmith watch`;
    renderWorkspace();
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

  // ---------------------------------------------------------------- the workspace: home, and the other films
  const here = BASE ? decodeURIComponent(BASE.slice(3)) : null;
  const switchBtn = $("switchBtn"), switchMenu = $("switchMenu");
  let switcher = null, films = null, filling = null;
  function renderWorkspace() {
    const name = (app.state?.project?.workspace || app.lastGood?.project?.workspace || "").split("/").filter(Boolean).pop();
    if (!BASE || !name) return;
    const link = $("wsLink");
    if (link.hidden) {
      link.hidden = $("wsSep").hidden = $("switchWrap").hidden = false;
      switcher = menuButton(switchBtn, switchMenu, (list) => Math.max(0, list.findIndex((b) => b.dataset.name === here)));
      switchBtn.addEventListener("click", () => { if (!switchMenu.hidden) fillSwitch(); });
      pressable(link, (e) => { e.preventDefault(); busy(link, true); location.href = "/"; });
      tip(switchBtn, t("home.switch"));
      fillSwitch();
    }
    if (link.dataset.name !== name) {
      link.dataset.name = name;
      link.replaceChildren(h("span", { class: "ws-name", text: name }), h("span", { class: "spin", "aria-hidden": "true" }));
    }
    tip(link, t("home.backTip", { workspace: name }));
  }
  function switchItems() {
    if (!films) return [h("div", { class: "menu-title", text: t(filling ? "home.loading" : "home.loadFailedShort") })];
    const rows = films.map((p) => h("button", { type: "button", class: "menu-item switch-item", role: "menuitemradio", tabindex: "-1", "aria-checked": String(p.name === here), "data-name": p.name, "data-url": p.url },
      icon("i-tick"), h("span", { class: "switch-name" }, h("b", { text: p.title || p.name }), ...(p.title ? [h("small", { text: p.name })] : [])),
      ...(p.working ? [h("i", { class: "switch-dot", "aria-hidden": "true" })] : []), h("span", { class: "spin", "aria-hidden": "true" })));
    return [h("div", { class: "menu-title", text: t("home.switchTitle") }), ...rows, h("div", { class: "menu-sep", role: "separator" }),
      h("button", { type: "button", class: "menu-item", role: "menuitem", tabindex: "-1", "data-url": "/" }, icon("i-grid", "is-shown"), h("span", { text: t("home.all") }))];
  }
  async function fillSwitch() {
    const refocus = () => {
      if (switchMenu.hidden || switchMenu.contains(document.activeElement) || document.activeElement !== document.body) return;
      switchMenu.querySelector('[aria-checked="true"]')?.focus();
    };
    filling = fetch("/api/home", { cache: "no-store" }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))));
    if (!films) switchMenu.replaceChildren(...switchItems());
    try { films = (await filling).projects; } catch { /* the last list stands */ }
    filling = null;
    const focusedName = document.activeElement?.dataset?.name;
    switchMenu.replaceChildren(...switchItems());
    if (focusedName) switchMenu.querySelector(`[data-name="${CSS.escape(focusedName)}"]`)?.focus();
    refocus();
  }
  switchMenu.addEventListener("click", (e) => {
    const b = e.target.closest(".menu-item");
    if (!b) return;
    if (b.dataset.name === here) { switcher?.close(true); return; }
    busy(b, true);
    location.href = b.dataset.url;
  });

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
      if (e.code === "owner.elsewhere") app.emit("owner-elsewhere", e);
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

  // ---------------------------------------------------------------- language, theme
  app.keepPlace = () => {
    try { sessionStorage.setItem("rs-watch:resume", JSON.stringify({ time: app.time, beat: app.beat })); } catch { /* private window */ }
  };
  const langs = setupLanguage($("langBtn"), $("langMenu"), $("langName"), app.keepPlace);
  app.closeMenus = () => langs.close(true);
  setupTheme($("themeSeg"), () => app.emit("theme"));

  // ---------------------------------------------------------------- the divider between the session and the stage
  const split = $("colSplit");
  // inside the frame the column starts after the sidebar and shares the main area's width
  const area = () => document.getElementById("main") || document.documentElement;
  const left = () => area().getBoundingClientRect().left;
  const room = () => area().clientWidth || innerWidth;
  const minW = () => (room() < 960 ? 300 : 340);
  const fallback = () => Math.round(clamp(room() * 0.356, 340, 560));
  const maxW = () => Math.max(minW(), Math.min(680, room() - 520));
  let userW = storage("session-w", null);
  function applyWidth() {
    const w = Math.round(clamp(userW ?? fallback(), minW(), maxW()));
    document.documentElement.style.setProperty("--session-w", `${w}px`);
    split.setAttribute("aria-valuenow", String(w));
    split.setAttribute("aria-valuemin", String(minW()));
    split.setAttribute("aria-valuemax", String(maxW()));
  }
  function setWidth(px) {
    userW = Math.round(clamp(px, minW(), maxW()));
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
    const move = (ev) => setWidth(ev.clientX - left());
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
