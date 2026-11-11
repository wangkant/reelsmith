import { BASE, post as act } from "./api.js";
import { kindName } from "./beats.js";
import { has, t } from "./i18n.js";
import { busy, clamp, clock, disable, elapsed, h, icon, isOff, lowerFirst, note, pressable, storage, store, timecode, tip } from "./util.js";
import { disclosure, emptyState, money, rove, toolName } from "./panel.js";

const MAX_MESSAGE = 8000;
const KEPT_ROWS = 600;                  // chat rows the thread keeps in the page; older ones scroll out of memory
const SUGGESTIONS = ["chat.try1", "chat.try2", "chat.try3"];
const RENDER_STAGES = ["check", "layout", "film", "master", "film check"];
// An engine's reason in the person's language; the server's English when the code is not known here.
export const engineWhy = (e) => (e?.code && has(e.code) ? t(e.code, e.params || {}) : e?.why || "");

// Light Markdown for the agent's replies: paragraphs, lists, fenced code, inline code, bold and italics.
function inline(text) {
  const out = [];
  const re = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|(?<![\w*])\*([^*\s][^*\n]*?)\*(?![\w*])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[1] != null ? h("code", { text: m[1] }) : m[2] != null ? h("strong", { text: m[2] }) : h("em", { text: m[3] }));
    last = re.lastIndex;
  }
  out.push(text.slice(last));
  return out;
}
function markdown(text) {
  const out = [];
  const src = String(text || "").replace(/\r/g, "").split("\n");
  const LIST = /^\s*([-*•]|\d+[.)])\s+(.*)$/;
  for (let i = 0; i < src.length;) {
    const l = src[i];
    if (/^\s*```/.test(l)) {
      const body = [];
      for (i += 1; i < src.length && !/^\s*```/.test(src[i]); i++) body.push(src[i]);
      i += 1;
      out.push(h("pre", { class: "md-code", text: body.join("\n") }));
    } else if (!l.trim()) {
      i += 1;
    } else if (LIST.test(l)) {
      const ordered = /^\s*\d/.test(l);
      const items = [];
      while (i < src.length && (LIST.test(src[i]) || (items.length && /^\s{2,}\S/.test(src[i])))) {
        const m = LIST.exec(src[i]);
        if (m) items.push(m[2]); else items[items.length - 1] += ` ${src[i].trim()}`;
        i += 1;
      }
      out.push(h(ordered ? "ol" : "ul", { class: "md-list" }, ...items.map((s) => h("li", {}, ...inline(s)))));
    } else if (/^#{1,4}\s/.test(l)) {
      out.push(h("p", { class: "md-h" }, ...inline(l.replace(/^#+\s*/, ""))));
      i += 1;
    } else {
      const para = [];
      while (i < src.length && src[i].trim() && !LIST.test(src[i]) && !/^\s*```/.test(src[i]) && !/^#{1,4}\s/.test(src[i])) para.push(src[i++]);
      const kids = [];
      para.forEach((p, k) => { if (k) kids.push(h("br")); kids.push(...inline(p)); });
      out.push(h("p", {}, ...kids));
    }
  }
  return out;
}

// The session: one thread of the person's requests, the agent's steps and its replies, and the composer under it.
export function createChat(app, panel) {
  const $ = (id) => document.getElementById(id);
  const log = $("chatLog"), input = $("chatInput"), form = $("composer"), send = $("sendBtn");
  const engineBtn = $("engineBtn"), menu = $("engineMenu"), ctxRow = $("ctxRow"), hint = $("composeHint");
  const errLine = $("composeErr"), pill = $("chatNew");

  const S = {
    loaded: false, gone: false, busy: false, turn: null, stopping: false, engines: [], fallback: null, session: null,
    spent: 0, budget: null, rows: new Map(), sending: false, stopAsked: false,
  };
  let picked = storage("engine", null);

  // ---------------------------------------------------------------- talking to the server
  async function post(path, body) {
    try {
      return { status: 200, data: await act(path, body) };
    } catch (e) {
      if (e.status == null) throw e;
      return { status: e.status, data: { error: e.message, code: e.code, params: e.params } };
    }
  }

  let loadTimer = 0;
  async function load() {
    clearTimeout(loadTimer);
    try {
      const r = await fetch(`${BASE}/api/chat`, { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status}`);
      apply(await r.json());
    } catch {
      S.gone = true;
      renderControls();
      loadTimer = setTimeout(load, 3000);
    }
  }
  function apply(st) {
    S.loaded = true;
    S.gone = false;
    S.busy = !!st.busy; S.turn = st.turn; S.stopping = !!st.stopping;
    S.engines = st.engines || []; S.fallback = st.engine; S.session = st.session_engine;
    app.noEngine = !S.engines.some((e) => e.available);      // the session head says so instead of "ready"
    S.spent = st.spent_usd || 0; S.budget = st.budget_usd;
    S.rows = new Map((st.messages || []).map((r) => [r.id, r]));
    if (!S.busy) S.stopAsked = false;
    tellBusy();
    renderLog(true);
    renderControls();
  }
  function merge(d) {
    if (d.resync) { load(); return; }
    let fresh = 0;
    for (const r of d.rows || []) {
      if (!S.rows.has(r.id) && r.role !== "tool") fresh += 1;
      S.rows.set(r.id, r);
      if (r.role === "note") {
        if (r.spent_usd != null) S.spent = r.spent_usd;
        if (r.budget_usd != null) S.budget = r.budget_usd;
      }
    }
    if ("busy" in d) S.busy = !!d.busy;
    if ("turn" in d) S.turn = d.turn;
    if ("stopping" in d) S.stopping = !!d.stopping;
    if (!S.busy) S.stopAsked = false;
    tellBusy();
    trim();
    renderLog(false, fresh);
    renderControls();
  }

  // an events stream of its own: the chat's rows come on it as "chat" events
  function listen() {
    const es = new EventSource(`${BASE}/api/events`);
    es.onopen = () => { S.gone = false; load(); };
    es.addEventListener("chat", (e) => { try { merge(JSON.parse(e.data)); } catch { load(); } });
    es.onerror = () => {
      S.gone = true;
      renderControls();
      if (es.readyState === EventSource.CLOSED) { es.close(); setTimeout(listen, 2000); }
    };
  }
  // the session head says the agent is at work while a request runs, even between tool calls
  function tellBusy() {
    const running = [...S.rows.values()].filter((x) => x.turn === S.turn && x.role === "tool" && x.ok == null).at(-1);
    const k = running && `run.${running.tool}`;
    app.chatBusy = !S.busy ? null : k && t(k) !== k ? lowerFirst(t(k)) : running ? toolName(running.tool) : t("chat.thinkingShort");
    app.emit("chat-busy");
  }
  function trim() {
    if (S.rows.size <= KEPT_ROWS) return;
    const ids = [...S.rows.keys()].sort((a, b) => a - b);
    for (const id of ids.slice(0, S.rows.size - KEPT_ROWS)) S.rows.delete(id);
  }

  // ---------------------------------------------------------------- scrolling
  let atBottom = true, unseen = 0;
  rove(log, t("list.keys"));
  log.addEventListener("scroll", () => {
    atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 32;
    if (atBottom && unseen) { unseen = 0; renderPill(); }
  });
  new ResizeObserver(() => { if (atBottom) log.scrollTop = log.scrollHeight; }).observe(log);
  // a picture that arrives after the entry grows the thread: the newest entry stays in view
  log.addEventListener("load", () => { if (atBottom) log.scrollTop = log.scrollHeight; }, true);
  function toBottom(smooth = false) {
    log.scrollTo({ top: log.scrollHeight, behavior: smooth && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "auto" });
    atBottom = true;
    unseen = 0;
    renderPill();
  }
  function renderPill() {
    pill.hidden = !unseen;
    $("chatNewText").textContent = t("chat.newRows", { n: unseen });
  }
  pressable(pill, () => { toBottom(true); input.focus(); });
  tip(pill, t("chat.toLatest"));

  // ---------------------------------------------------------------- entries
  const fps = () => app.fps();
  // what is on screen, in plain words; the id only when the clip is gone from the cut
  const clipName = (id) => { const c = app.clipById(id, app.state?.tracks); return c ? kindName(c) : id; };
  function contextChips(c) {
    if (!c) return [];
    const out = [];
    if (c.beat != null) out.push(h("span", { class: "chip is-ctx" }, icon("i-target"),
      c.start != null ? `${t("beats.n", { n: c.beat })} · ${timecode(c.start, fps())}–${timecode(c.end, fps())}` : t("beats.n", { n: c.beat })));
    if (c.clip) out.push(h("span", { class: "chip is-ctx" }, icon("i-target"),
      c.start != null ? t("chat.about", { id: clipName(c.clip), a: timecode(c.start, fps()), b: timecode(c.end, fps()) }) : t("chat.aboutClip", { id: clipName(c.clip) })));
    if (c.playhead != null) out.push(h("span", { class: "chip" }, icon("i-timer"), t("chat.playheadAt", { t: timecode(c.playhead, fps()) })));
    return out;
  }

  function tryAgain(r) {
    const b = h("button", { type: "button", class: "text-btn mini accent" }, icon("i-undo"), h("span", { text: t("chat.tryAgain") }));
    tip(b, t("chat.tryAgainTip"));
    pressable(b, () => {
      const user = [...S.rows.values()].find((x) => x.role === "user" && x.turn === r.turn);
      if (!user) { note(b, t("chat.noOriginal"), "is-error"); return; }
      setInput(user.text);
      input.focus();
      note(b, t("chat.refilled"));
    });
    return b;
  }
  function noteEl(r) {
    const cost = money(r.cost_usd || 0);
    const used = r.budget_used_up ? h("p", { class: "c-note-more", text: t("chat.budgetNow", { budget: money(r.budget_usd) }) }) : null;
    switch (r.kind) {
      case "stopped":
        return h("div", { class: "c-end is-warn" }, h("span", { text: t("chat.stopped") }), h("span", { class: "num", text: cost }),
          h("span", { class: "c-time num", text: clock(r.ts).slice(0, 5) }), tryAgain(r));
      case "budget":
        return h("div", { class: "c-card is-error" }, h("strong", {}, icon("i-alert"), t("chat.budgetTitle")),
          h("p", { text: t("chat.budgetBody", { spent: money(r.spent_usd), budget: money(r.budget_usd) }) }));
      case "aborted": {
        const why = (/ended early: (.*?)\. It cost/.exec(r.text) || [])[1] || r.text;
        return h("div", { class: "c-card is-warn" }, h("strong", {}, icon("i-alert"), t("chat.aborted")),
          h("p", { class: "c-detail", text: why }), h("div", { class: "c-card-foot" }, h("span", { class: "num dim", text: cost }), tryAgain(r)), used);
      }
      default: {
        const why = String(r.text || "").replace(/^The (turn|request) failed:\s*/, "");
        return h("div", { class: "c-card is-error" }, h("strong", {}, icon("i-alert"), t("chat.failed")),
          h("p", { class: "c-detail", text: why }), h("div", { class: "c-card-foot" }, h("span", { class: "dim", text: t("chat.failedNext") }), tryAgain(r)), used);
      }
    }
  }

  // The agent's reply carries its turn's length and cost once the turn has ended.
  function turnFacts(r) {
    const rows = [...S.rows.values()];
    const end = rows.find((x) => x.role === "note" && x.turn === r.turn);
    if (!end) return null;
    const last = rows.filter((x) => x.role === "assistant" && x.turn === r.turn).at(-1);
    if (last?.id !== r.id) return null;
    const user = rows.find((x) => x.role === "user" && x.turn === r.turn);
    const secs = user ? (Date.parse(end.ts) - Date.parse(user.ts)) / 1000 : null;
    return [secs != null && secs >= 0 ? elapsed(secs) : null, money(end.cost_usd || 0)].filter(Boolean).join(" · ");
  }
  function rowEl(r) {
    if (r.role === "user") {
      const chips = contextChips(r.context);
      return h("div", { class: "c-row c-user", "data-id": r.id },
        h("div", { class: "c-head" }, h("span", { class: "c-who", text: t("chat.request") }), h("span", { class: "grow" }),
          h("span", { class: "c-time num", text: clock(r.ts).slice(0, 5) })),
        chips.length ? h("div", { class: "c-chips" }, ...chips) : null,
        h("div", { class: "c-text", text: r.text }));
    }
    if (r.role === "assistant") {
      const facts = turnFacts(r);
      return h("div", { class: `c-row c-agent${facts == null ? " is-interim" : ""}`, "data-id": r.id },
        h("div", { class: "c-head" }, h("span", { class: "c-who", text: t("chat.agent") }),
          facts ? h("span", { class: "c-facts num", text: facts }) : null, h("span", { class: "grow" }),
          h("span", { class: "c-time num", text: clock(r.ts).slice(0, 5) })),
        h("div", { class: "md" }, ...markdown(r.text)));
    }
    return h("div", { class: "c-row c-noterow", "data-id": r.id }, noteEl(r));
  }

  // The live entry at the foot of the thread: what the agent is doing now, with the render's stages when it renders.
  const live = h("div", { class: "act is-live", role: "status" });
  let liveKey = "";
  function renderLive() {
    const r = app.running;
    const chatBusy = S.busy;
    if (!r && !chatBusy) { live.remove(); liveKey = ""; return false; }
    const rt = app.runText?.();
    const stopping = S.stopping || S.stopAsked;
    const running = [...S.rows.values()].filter((x) => x.turn === S.turn && x.role === "tool" && x.ok == null).at(-1);
    const what = stopping ? t("chat.stopping") : r ? rt.what : running ? t("chat.usingTool", { tool: toolName(running.tool) }) : t("chat.thinking");
    const since = r ? null : turnStart();
    const secs = r ? rt.secs : since ? Math.max(0, (Date.now() - since) / 1000) : null;
    const key = JSON.stringify([what, r?.tool, r?.stage, r?.progress, stopping, Math.floor(secs || 0)]);
    if (key === liveKey) return live.isConnected;
    liveKey = key;
    const head = h("div", { class: "act-head" }, h("span", { class: "act-text", text: what }),
      h("span", { class: "act-side" }, secs != null ? h("span", { class: "act-time num", text: t("act.elapsed", { d: elapsed(secs) }) }) : null));
    const body = [head];
    if (r && /^(render|draft)$/.test(r.tool)) {
      const at = Math.max(0, RENDER_STAGES.indexOf(r.stage));
      body.push(h("div", { class: "rail" }, ...RENDER_STAGES.map((st, i) => h("span", { class: `rail-step${i < at ? " is-done" : i === at ? " is-now" : ""}` },
        h("i", { style: { "--p": i < at ? "100%" : i === at && typeof r.progress === "number" ? `${Math.round(r.progress * 100)}%` : i === at ? "35%" : "0%" } }),
        h("span", { text: t(`rail.${st.replace(" ", "_")}`) })))));
      body.push(h("div", { class: "act-sub num", text: rt.short }));
    } else if (r) {
      body.push(h("div", { class: "act-sub num", text: rt.text }));
      if (typeof r.progress === "number") body.push(h("div", { class: "meter is-live", style: { "--fill": `${clamp(r.progress * 100, 0, 100)}%` } }));
    }
    const canStop = chatBusy || app.state?.can?.stop;
    if (r || chatBusy) {
      const b = h("button", { type: "button", class: "text-btn mini" }, icon("i-stop", "is-filled"), h("span", { text: t(stopping ? "chat.stoppingBtn" : r && /^(render|draft)$/.test(r.tool) ? "act.stopRender" : "chat.stop") }), h("span", { class: "spin", "aria-hidden": "true" }));
      const why = stopping ? t("chat.stoppingTip") : !canStop ? (app.state?.can?.why?.stop ? whyText(app.state.can.why.stop) : t("stop.unsupported")) : null;
      disable(b, why, t("chat.stopTip"));
      busy(b, stopping);
      pressable(b, () => (chatBusy ? stop() : stopAction(b)));
      body.push(h("div", { class: "act-actions" }, b));
    }
    live.className = `act is-live${rt?.stuck ? " is-stuck" : ""}${stopping ? " is-stopping" : ""}`;
    live.replaceChildren(h("span", { class: "act-ic" }, h("span", { class: "c-spin" })), h("div", { class: "act-main" }, ...body));
    return true;
  }
  function turnStart() {
    const u = [...S.rows.values()].filter((r) => r.role === "user" && r.turn === S.turn).at(-1);
    return u ? Date.parse(u.ts) : null;
  }

  // Requests, replies and the agent's steps in the order they happened; elements are reused while they stay the same.
  const cache = new Map();
  let empty = null;
  function entries() {
    const out = [];
    for (const r of [...S.rows.values()].sort((a, b) => a.id - b.id)) {
      if (r.role === "tool") continue;                     // its step appears in the thread from the activity log
      if (r.role === "note" && r.kind === "end" && !r.budget_used_up) continue;   // the reply above it carries its cost
      const sig = JSON.stringify([r, r.role === "assistant" ? turnFacts(r) : null]);
      let c = cache.get(`c${r.id}`);
      if (!c || c.sig !== sig) cache.set(`c${r.id}`, c = { sig, el: rowEl(r) });
      out.push({ ts: r.ts, n: r.id, el: c.el });
    }
    for (const s of panel.steps()) out.push({ ts: s.ts, n: 0, el: s.el });
    return out.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.n - b.n)).map((x) => x.el);
  }
  function renderLog(first = false, fresh = 0) {
    const els = entries();
    if (renderLive()) els.push(live);
    if (!els.length) {
      empty = renderEmpty();
      log.replaceChildren(empty);
      return;
    }
    empty = null;
    const same = els.length === log.children.length && els.every((el, i) => log.children[i] === el);
    if (!same) {
      const top = log.scrollTop;
      log.replaceChildren(...els);
      if (atBottom || first) requestAnimationFrame(() => toBottom());
      else { log.scrollTop = top; unseen += fresh; renderPill(); }
    }
  }
  app.on("steps", () => renderLog(false, 1));
  app.on("running", () => renderLog());
  app.on("progress", () => renderLog());
  app.on("tick", () => { if (S.busy || app.running) renderLog(); });

  function renderEmpty() {
    if (S.loaded && !S.engines.some((e) => e.available)) {
      return emptyState("i-alert", t("chat.noEngineTitle"), t("chat.noEngineBody"),
        h("ul", { class: "engine-why" }, ...S.engines.map((e) => h("li", {}, h("strong", { text: e.label }), h("span", { text: engineWhy(e) })))));
    }
    const chips = SUGGESTIONS.map((k) => {
      const b = h("button", { type: "button", class: "suggest" }, icon("i-chat"), h("span", { text: t(k) }));
      tip(b, t("chat.suggestTip"));
      pressable(b, () => { setInput(t(k)); input.focus(); note(input, t("chat.filled")); });
      return b;
    });
    return emptyState("i-chat", t("chat.emptyTitle"), t("chat.emptyBody"), h("div", { class: "suggests" }, ...chips));
  }

  // ---------------------------------------------------------------- the composer
  function grow() {
    input.style.height = "auto";
    input.style.height = `${clamp(input.scrollHeight, 40, 180)}px`;
  }
  function setInput(text) {
    input.value = text;
    store("chat-draft", text || null);
    grow();
    input.setSelectionRange(text.length, text.length);
    renderControls();
  }
  app.on("compose", (text) => { app.showPanel("chat"); setInput(text); input.focus(); note(input, t("chat.filled")); });
  input.setAttribute("aria-label", t("chat.inputLabel"));
  input.value = storage("chat-draft", "") || "";
  input.addEventListener("input", () => { store("chat-draft", input.value || null); grow(); renderControls(); hideErr(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !e.isComposing) { input.blur(); return; }       // the draft stays; the window's keys work again
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    if (S.busy) { note(send, t("chat.busyNote")); return; }
    submit();
  });
  input.addEventListener("focus", renderControls);
  input.addEventListener("blur", renderControls);

  function engine() {
    const ok = (id) => S.engines.find((e) => e.id === id && e.available);
    if (S.busy && S.fallback) return S.engines.find((e) => e.id === S.fallback) || null;
    return ok(picked) || ok(S.fallback) || S.engines.find((e) => e.available) || null;
  }
  const budgetGone = () => S.budget != null && S.spent >= S.budget - 1e-9;

  function whyNotSend() {
    if (!S.loaded) return t("chat.loading");
    if (S.gone) return t("chat.gone");
    if (!engine()) return t("chat.noEngine");
    if (budgetGone()) return t("chat.budgetGone", { budget: money(S.budget) });
    if (app.state?.action) return t("busy.action");
    if (!input.value.trim()) return t("chat.typeFirst");
    if (input.value.length > MAX_MESSAGE) return t("chat.tooLong", { n: MAX_MESSAGE });
    return null;
  }

  function renderControls() {
    const stopping = S.busy && (S.stopping || S.stopAsked);
    send.classList.toggle("is-stop", S.busy);
    $("sendText").textContent = S.busy ? (stopping ? t("chat.stoppingBtn") : t("chat.stop")) : t("chat.send");
    busy(send, S.sending || stopping);
    if (S.busy) disable(send, stopping ? t("chat.stoppingTip") : S.gone ? t("chat.gone") : null, t("chat.stopTip"), "");
    else disable(send, S.sending ? t("chat.sending") : whyNotSend(), t("chat.sendTip"), "Enter");
    form.classList.toggle("is-off", S.gone || (S.loaded && !engine() && !S.busy));
    const ctx = context();
    input.placeholder = S.busy ? t("chat.placeholderBusy") : ctx?.beat != null ? t("chat.placeholderBeat", { n: ctx.beat })
      : ctx?.clip ? t("chat.placeholderClip", { id: lowerFirst(clipName(ctx.clip)) }) : t("chat.placeholder");

    // the line under the box: only why it cannot send, or how long the message is
    const len = input.value.length;
    hint.className = "compose-hint";
    if (S.gone) { hint.textContent = t("chat.gone"); hint.classList.add("is-warn"); }
    else if (S.loaded && !engine() && !S.busy) { hint.textContent = t("chat.noEngine"); hint.classList.add("is-warn"); }
    else if (budgetGone() && !S.busy) { hint.textContent = t("chat.budgetGone", { budget: money(S.budget) }); hint.classList.add("is-error"); }
    else if (len > MAX_MESSAGE * 0.85) { hint.textContent = `${len} / ${MAX_MESSAGE}`; if (len > MAX_MESSAGE) hint.classList.add("is-error"); }
    else hint.textContent = "";

    const e = engine();
    $("engineText").textContent = e ? e.label : S.loaded ? t("chat.noEngineShort") : "…";
    engineBtn.classList.toggle("is-none", !e);
    disable(engineBtn, S.busy ? t("chat.engineBusy") : !S.engines.length ? t("chat.loading") : null,
      e ? t("chat.engineTip", { label: e.label, why: engineWhy(e) }) : t("chat.engineNone"));
    renderSpend();
    renderContext();
    renderBlock();
    renderQuick();
  }

  // The spend: the project's paid calls against its budget, the agent's model use beside it in the tooltip.
  function renderSpend() {
    const sp = app.state?.spend;
    const el = $("chatSpend");
    const proj = sp?.project_usd ?? null, pb = sp?.project_budget_usd ?? null;
    const chat = sp?.chat_usd ?? S.spent, cb = sp?.chat_budget_usd ?? S.budget;
    el.hidden = proj == null && chat == null;
    if (el.hidden) return;
    const spent = (proj || 0) + (chat || 0), budget = pb != null || cb != null ? (pb || 0) + (cb || 0) : null;
    $("chatSpendText").textContent = budget ? t("chat.spendOf", { spent: money(spent), budget: money(budget) }) : money(spent);
    const share = budget ? spent / budget : 0;
    $("chatSpendBar").hidden = !budget;
    $("chatSpendBar").style.setProperty("--fill", `${clamp(share * 100, 0, 100)}%`);
    el.classList.toggle("is-high", share > 0.8);
    tip(el, [pb != null ? t("chat.spendProject", { spent: money(proj || 0), budget: money(pb) }) : null,
      cb != null ? t("chat.spendAgent", { spent: money(chat || 0), budget: money(cb) }) : null].filter(Boolean).join(" · ") || money(spent));
  }

  // With a conversation on screen the empty state is gone, so the reasons no agent can run sit above the box.
  let blockKey = "";
  function renderBlock() {
    const el = $("chatBlock");
    const none = S.loaded && !S.busy && !S.engines.some((x) => x.available) && S.rows.size > 0;
    el.hidden = !none;
    const key = none ? JSON.stringify(S.engines) : "";
    if (!none || key === blockKey) return;
    blockKey = key;
    const list = h("ul", { class: "engine-why" }, ...S.engines.map((x) => h("li", {}, h("strong", { text: x.label }), h("span", { text: engineWhy(x) }))));
    el.replaceChildren(h("strong", {}, icon("i-alert"), t("chat.noEngineTitle")), disclosure(t("chat.why"), list, false), list);
  }

  function showErr(text) { errLine.hidden = false; errLine.textContent = text; }
  function hideErr() { errLine.hidden = true; }
  // a film held by another window: said in the session, whichever control was refused
  app.on("owner-elsewhere", (w) => showErr(whyText(w)));
  const whyText = (w) => {
    if (w?.code === "chat.engine_unavailable") {         // the engine's own reason, translated too
      const e = S.engines.find((x) => x.id === w.params?.engine);
      return t(w.code, { ...w.params, why: e ? engineWhy(e) : w.params?.why || "" });
    }
    return w?.code && t(w.code, w.params || {}) !== w.code ? t(w.code, w.params || {}) : w?.text || w?.error || "";
  };

  async function submit() {
    if (S.sending) return;
    const why = whyNotSend();
    if (why) { note(send, why, "is-error"); return; }
    const message = input.value.trim();
    const body = { message };
    const e = engine();
    if (e) body.engine = e.id;
    const ctx = context();
    if (ctx) body.context = ctx;
    S.sending = true;
    renderControls();
    hideErr();
    try {
      const { status, data } = await post("/api/chat", body);
      if (status === 200 || status === 202) {
        setInput("");
        drop = { target: null, playhead: false };
        S.busy = true; S.turn = data.turn;
        note(send, t("chat.sent"));
        toBottom();
      } else if (status === 409) {
        if (data?.code === "busy.chat") S.busy = true;
        showErr(data?.code ? whyText(data) : t("chat.err409"));
      } else if (status === 413) showErr(t("chat.err413"));
      else if (status === 403) showErr(t("chat.err403"));
      else showErr(data?.code ? whyText(data) : t("chat.err400", { why: data?.error || status }));
    } catch {
      S.gone = true;
      showErr(t("chat.errGone"));
    } finally {
      S.sending = false;
      renderLog();
      renderControls();
    }
  }
  async function stop() {
    if (S.stopAsked || S.stopping) return;
    S.stopAsked = true;
    renderControls();
    renderLog();
    try {
      const { status, data } = await post("/api/chat/stop", {});
      if (status !== 200) throw new Error(data?.error || status);
      if (!data.stopped) { S.stopAsked = false; note(send, t("chat.nothingToStop")); load(); }
      else note(send, t("chat.stopAsked"));
    } catch {
      S.stopAsked = false;
      showErr(t("chat.stopFailed"));
    }
    renderControls();
  }
  async function stopAction(b) {
    try {
      const d = await act("/api/action", { action: "stop" });
      note(b, d.stopped ? t("chat.stopAsked") : whyText(d) || t("stop.unsupported"), d.stopped ? "" : "is-error");
    } catch (e) {
      note(b, e.code ? whyText(e) : e.message, "is-error");
    }
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (isOff(send)) { note(send, send.dataset.tip || "", "is-error"); return; }
    if (S.busy) stop(); else submit();
  });

  // ---------------------------------------------------------------- quick actions: render, check, undo without typing
  const QUICK = [["qRender", "render"], ["qCheck", "check"], ["qUndo", "undo"]];
  const asked = new Set();
  function renderQuick() {
    const s = app.state;
    const can = s?.can || {};
    const doing = s?.action?.action;
    for (const [id, a] of QUICK) {
      const b = $(id);
      const mine = doing === a || asked.has(a);
      const why = !s ? t("chat.loading") : app.status !== "connected" ? t("chat.gone") : mine ? t(`q.${a}Busy`) : S.busy ? t("busy.chat") : doing ? t("busy.action")
        : app.running ? t("busy.render") : can[a] === false ? whyText(can.why?.[a]) || t("q.cannot") : null;
      busy(b, mine);
      disable(b, why, t(`q.${a}Tip`));
    }
  }
  let lastSeen = null;
  for (const [id, a] of QUICK) {
    const b = $(id);
    pressable(b, async () => {
      if (asked.has(a)) return;
      asked.add(a);
      renderQuick();
      try {
        await act("/api/action", { action: a });
        note(b, t(`q.${a}Started`));
      } catch (e) {
        note(b, e.code ? whyText(e) : t("q.failed", { why: e.message }), "is-error");
        if (e.code === "owner.elsewhere") showErr(whyText(e));
      } finally {
        asked.delete(a);
        renderQuick();
      }
    });
  }
  // how the window's last action ended, said next to the button that started it
  app.on("state", () => {
    const la = app.state?.last_action;
    const k = la ? `${la.action}|${la.at}` : null;
    if (k && lastSeen && k !== lastSeen) {
      const b = $(QUICK.find(([, a]) => a === la.action)?.[0] || "qRender");
      if (b && document.body.contains(b)) note(b, whyText(la) || la.text, la.ok ? "is-ok" : "is-error");
    }
    if (app.state) lastSeen = k || "";
    renderQuick();
    renderControls();
  });

  // ---------------------------------------------------------------- what "this" means: the beat or element, the playhead
  let drop = { target: null, playhead: false };           // what the person took off the next message
  function context() {
    const ctx = {};
    const c = app.selected ? app.clipById(app.selected, app.state?.tracks) : null;
    const b = app.beat != null ? (app.beats || []).find((x) => x.i === app.beat) : null;
    if (c && drop.target !== `c:${c.id}`) {
      ctx.clip = c.id;
      if (c.start != null) ctx.start = +c.start.toFixed(3);
      if (c.end != null) ctx.end = +c.end.toFixed(3);
    } else if (!c && b && drop.target !== `b:${b.i}`) {
      ctx.beat = b.i;
      ctx.start = +b.start.toFixed(3);
      ctx.end = +b.end.toFixed(3);
    }
    if (app.time > 0 && !drop.playhead) ctx.playhead = +app.time.toFixed(3);
    return Object.keys(ctx).length ? ctx : null;
  }
  let ctxKey = "";
  function renderContext() {
    const c = context();
    const key = JSON.stringify([c?.clip, c?.beat, c?.start, c?.end, c?.playhead != null ? timecode(c.playhead, fps()) : null]);
    if (key === ctxKey) return;
    ctxKey = key;
    ctxRow.hidden = !c;
    if (!c) { ctxRow.replaceChildren(); return; }
    const chip = (text, cls, iconName, onDrop) => {
      const x = h("button", { type: "button", class: "ctx-x" }, icon("i-close"));
      tip(x, t("chat.ctxDrop"), null, `${t("chat.ctxDrop")}: ${text}`);
      pressable(x, () => { onDrop(); ctxKey = ""; renderControls(); input.focus(); });
      const el = h("span", { class: `ctx-chip ${cls}` }, icon(iconName), h("span", { class: "ctx-text", text }), x);
      tip(el.querySelector(".ctx-text"), t("chat.ctxTip"));
      return el;
    };
    const kids = [];
    if (c.clip) {
      const text = c.start != null ? t("chat.about", { id: clipName(c.clip), a: timecode(c.start, fps()), b: timecode(c.end, fps()) }) : t("chat.aboutClip", { id: clipName(c.clip) });
      kids.push(chip(text, "is-sel", "i-target", () => { drop.target = `c:${c.clip}`; }));
    }
    if (c.beat != null) {
      const text = `${t("beats.n", { n: c.beat })} · ${timecode(c.start, fps())}–${timecode(c.end, fps())}`;
      kids.push(chip(text, "is-sel", "i-target", () => { drop.target = `b:${c.beat}`; }));
    }
    if (c.playhead != null) kids.push(chip(t("chat.playheadAt", { t: timecode(c.playhead, fps()) }), "", "i-timer", () => { drop.playhead = true; }));
    ctxRow.replaceChildren(...kids);
  }
  app.on("select", () => { drop.target = null; renderControls(); });
  app.on("beat", () => { drop.target = null; renderControls(); });
  let ctxAt = 0;
  app.on("time", () => {                  // a playing film moves the chip four times a second, not every frame
    const now = performance.now();
    if (app.playing && now - ctxAt < 250) return;
    ctxAt = now;
    renderContext();
  });
  app.on("playing", renderContext);
  app.on("conn", renderControls);
  app.on("ask-about", () => { drop.target = null; renderControls(); input.focus(); });

  // ---------------------------------------------------------------- the engine picker
  let active = 0;
  function options() { return [...menu.children]; }
  function renderMenu() {
    const cur = engine();
    menu.replaceChildren(...S.engines.map((e, i) => {
      const li = h("li", { role: "option", id: `eng-${e.id}`, class: "engine-opt", "aria-selected": String(cur?.id === e.id),
        "aria-disabled": String(!e.available) },
      h("span", { class: "engine-opt-head" }, h("span", { class: `engine-dot${e.available ? "" : " is-off"}` }), h("span", { text: e.label }),
        S.session === e.id ? h("span", { class: "chip", text: t("chat.thisConversation") }) : null,
        cur?.id === e.id ? icon("i-tick", "engine-tick") : null),
      h("span", { class: "engine-why", text: e.available ? engineWhy(e) : t("chat.cannot", { why: engineWhy(e) }) }));
      li.addEventListener("click", () => choose(i));
      li.addEventListener("pointermove", () => focusOpt(i));
      return li;
    }));
  }
  function focusOpt(i) {
    const opts = options();
    if (!opts.length) return;
    active = (i + opts.length) % opts.length;
    opts.forEach((o, k) => o.classList.toggle("is-active", k === active));
    menu.setAttribute("aria-activedescendant", opts[active].id);
    opts[active].scrollIntoView({ block: "nearest" });
  }
  function openMenu() {
    renderMenu();
    menu.hidden = false;
    engineBtn.setAttribute("aria-expanded", "true");
    const cur = engine();
    focusOpt(Math.max(0, S.engines.findIndex((e) => e.id === cur?.id)));
    menu.focus();
  }
  function closeMenu(back = true) {
    if (menu.hidden) return;
    menu.hidden = true;
    engineBtn.setAttribute("aria-expanded", "false");
    if (back) engineBtn.focus();
  }
  function choose(i) {
    const e = S.engines[i];
    if (!e) return;
    if (!e.available) { note(options()[i], t("chat.cannot", { why: engineWhy(e) }), "is-error"); return; }
    picked = e.id;
    store("engine", e.id);
    closeMenu();
    renderControls();
    note(engineBtn, t("chat.engineSet", { label: e.label }));
  }
  pressable(engineBtn, () => (menu.hidden ? openMenu() : closeMenu()));
  menu.addEventListener("keydown", (e) => {
    const k = e.key;
    if (k === "ArrowDown" || k === "ArrowUp") { e.preventDefault(); focusOpt(active + (k === "ArrowDown" ? 1 : -1)); }
    else if (k === "Home" || k === "End") { e.preventDefault(); focusOpt(k === "Home" ? 0 : S.engines.length - 1); }
    else if (k === "Enter" || k === " ") { e.preventDefault(); choose(active); }
    else if (k === "Escape") { e.preventDefault(); closeMenu(); }
    else if (k === "Tab") closeMenu(false);
    else return;
    e.stopPropagation();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !engineBtn.contains(e.target)) closeMenu(false);
  }, true);

  input.style.height = "";
  grow();
  renderLog(true);
  renderControls();
  listen();
  return { load };
}
