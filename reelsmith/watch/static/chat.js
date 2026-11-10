import { t } from "./i18n.js";
import { busy, clamp, clock, disable, elapsed, h, isOff, note, pressable, storage, store, timecode, tip } from "./util.js";
import { BASE, disclosure, emptyState, icon, money, rove, toolIcon, toolName } from "./panel.js";

const MAX_MESSAGE = 8000;
const KEPT_ROWS = 600;                  // rows the log keeps in the page; older ones scroll out of memory
const SUGGESTIONS = ["chat.try1", "chat.try2", "chat.try3"];

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
export function markdown(text) {
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

export function createChat(app, panel) {
  const $ = (id) => document.getElementById(id);
  const log = $("chatLog"), input = $("chatInput"), form = $("composer"), send = $("sendBtn");
  const engineBtn = $("engineBtn"), menu = $("engineMenu"), ctxRow = $("ctxRow"), hint = $("composeHint");
  const errLine = $("composeErr"), pill = $("chatNew"), dot = $("chatDot");

  const S = {
    loaded: false, gone: false, busy: false, turn: null, stopping: false, engines: [], fallback: null, session: null,
    spent: 0, budget: null, rows: new Map(), sending: false, stopAsked: false,
  };
  let picked = storage("engine", null);
  const els = new Map();           // row id -> its element in the log

  // ---------------------------------------------------------------- talking to the server
  let token = null;
  async function getToken() {
    if (!token) {
      const r = await fetch(`${BASE}/api/session`, { cache: "no-store" });
      if (!r.ok) throw Object.assign(new Error(`${r.status}`), { status: r.status });
      token = (await r.json()).token;
    }
    return token;
  }
  async function post(path, body, again = true) {
    const r = await fetch(`${BASE}${path}`, {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Reelsmith-Token": await getToken() },
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch { /* not JSON */ }
    if (r.status === 403 && again && /header/.test(data?.error || "")) {      // a restarted server has a new token
      token = null;
      return post(path, body, false);
    }
    return { status: r.status, data };
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
    const first = !S.loaded;
    S.loaded = true;
    S.gone = false;
    S.busy = !!st.busy; S.turn = st.turn; S.stopping = !!st.stopping;
    S.engines = st.engines || []; S.fallback = st.engine; S.session = st.session_engine;
    S.spent = st.spent_usd || 0; S.budget = st.budget_usd;
    S.rows = new Map((st.messages || []).map((r) => [r.id, r]));
    if (!S.busy) S.stopAsked = false;
    renderAll();
    if (first && !S.engines.some((e) => e.available) && !panel.touched()) panel.show(1, false);
  }
  function merge(d) {
    if (d.resync) { load(); return; }
    const fresh = [];
    for (const r of d.rows || []) {
      const known = S.rows.has(r.id);
      S.rows.set(r.id, r);
      if (!known) fresh.push(r);
      if (r.role === "note") {
        if (r.spent_usd != null) S.spent = r.spent_usd;
        if (r.budget_usd != null) S.budget = r.budget_usd;
      }
      putRow(r);
    }
    if ("busy" in d) S.busy = !!d.busy;
    if ("turn" in d) S.turn = d.turn;
    if ("stopping" in d) S.stopping = !!d.stopping;
    if (!S.busy) S.stopAsked = false;
    trim();
    renderWorking();
    renderControls();
    afterAppend(fresh.length);
    if (fresh.some((r) => r.role === "assistant" || r.role === "note") && panel.current() !== 0) unread = true;
    renderDot();
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

  // ---------------------------------------------------------------- the log
  let atBottom = true, unseen = 0, unread = false;
  rove(log, t("list.keys"));
  log.addEventListener("scroll", () => {
    atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 32;
    if (atBottom && unseen) { unseen = 0; renderPill(); }
  });
  new ResizeObserver(() => { if (atBottom) log.scrollTop = log.scrollHeight; }).observe(log);
  function toBottom(smooth = false) {
    log.scrollTo({ top: log.scrollHeight, behavior: smooth && !matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "auto" });
    atBottom = true;
    unseen = 0;
    renderPill();
  }
  function afterAppend(n) {
    if (atBottom) toBottom();
    else if (n) { unseen += n; renderPill(); }
  }
  function renderPill() {
    pill.hidden = !unseen;
    $("chatNewText").textContent = t("chat.newRows", { n: unseen });
  }
  pressable(pill, () => { toBottom(true); input.focus(); });
  function renderDot() {
    dot.hidden = !(S.busy || unread);
    dot.classList.toggle("is-busy", S.busy);
    tip($("tab-chat"), S.busy ? t("chat.tabBusy") : unread ? t("chat.tabUnread") : t("tab.chatTip"), "1", t("tab.chat"));
  }
  app.on("panel", (name) => {
    if (name !== "chat") return;
    unread = false;
    renderDot();
    requestAnimationFrame(() => { if (atBottom) toBottom(); });
  });

  function contextText(c) {
    if (!c) return null;
    const fps = app.fps();
    const parts = [];
    if (c.clip) parts.push(c.start != null && c.end != null
      ? t("chat.about", { id: c.clip, a: timecode(c.start, fps), b: timecode(c.end, fps) }) : t("chat.aboutClip", { id: c.clip }));
    if (c.playhead != null) parts.push(t("chat.at", { t: timecode(c.playhead, fps) }));
    return parts.join(" · ");
  }

  function noteEl(r) {
    const cost = money(r.cost_usd || 0);
    const tryAgain = () => {
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
    };
    const used = r.budget_used_up ? h("p", { class: "c-note-more", text: t("chat.budgetNow", { budget: money(r.budget_usd) }) }) : null;
    switch (r.kind) {
      case "end":
        return h("div", { class: "c-end" }, h("span", { text: t("chat.done") }), h("span", { class: "num", text: cost }),
          h("span", { class: "c-time num", text: clock(r.ts) }), used);
      case "stopped":
        return h("div", { class: "c-end is-warn" }, h("span", { text: t("chat.stopped") }), h("span", { class: "num", text: cost }),
          h("span", { class: "c-time num", text: clock(r.ts) }), tryAgain());
      case "budget":
        return h("div", { class: "c-card is-error" }, h("strong", {}, icon("i-alert"), t("chat.budgetTitle")),
          h("p", { text: t("chat.budgetBody", { spent: money(r.spent_usd), budget: money(r.budget_usd) }) }));
      case "aborted": {
        const why = (/ended early: (.*?)\. It cost/.exec(r.text) || [])[1] || r.text;
        return h("div", { class: "c-card is-warn" }, h("strong", {}, icon("i-alert"), t("chat.aborted")),
          h("p", { class: "c-detail", text: why }), h("div", { class: "c-card-foot" }, h("span", { class: "num dim", text: cost }), tryAgain()), used);
      }
      default: {
        const why = String(r.text || "").replace(/^The turn failed:\s*/, "");
        return h("div", { class: "c-card is-error" }, h("strong", {}, icon("i-alert"), t("chat.failed")),
          h("p", { class: "c-detail", text: why }), h("div", { class: "c-card-foot" }, h("span", { class: "dim", text: t("chat.failedNext") }), tryAgain()), used);
      }
    }
  }

  function toolEl(r) {
    const state = r.ok == null ? "is-running" : r.ok ? "is-ok" : "is-fail";
    const status = r.ok == null ? h("span", { class: "spin c-spin", "aria-hidden": "true" })
      : icon(r.ok ? "i-check" : "i-alert", "c-status");
    const head = [status, icon(toolIcon(r.tool), "c-tool-ic"), h("span", { class: "c-tool-name", text: toolName(r.tool) }),
      r.text ? h("span", { class: "c-brief mono", text: r.text }) : null,
      h("span", { class: "sr-only", text: r.ok == null ? t("chat.toolRunning") : r.ok ? t("chat.toolOk") : t("chat.toolFailed") })];
    if (!r.detail) {
      const div = h("div", { class: `c-tool ${state}` }, h("div", { class: "c-tool-head" }, ...head));
      tip(div, `${toolName(r.tool)}${r.text ? ` · ${r.text}` : ""}`);
      return div;
    }
    const pre = h("pre", { class: "c-result", text: r.detail });
    const open = r.ok === false && openRows.has(r.id);
    const btn = disclosure("", pre, open, (on) => { on ? openRows.add(r.id) : openRows.delete(r.id); }, "c-tool-head");
    btn.replaceChildren(...head.filter(Boolean), icon("i-chev", "disc-chev"));
    tip(btn, r.ok === false ? t("chat.toolFailedTip") : t("chat.toolResultTip"));
    return h("div", { class: `c-tool ${state}` }, btn, pre);
  }
  const openRows = new Set();

  function rowEl(r) {
    if (r.role === "user") {
      const ctx = contextText(r.context);
      return h("div", { class: "c-row c-user", "data-id": r.id },
        h("div", { class: "c-bubble" }, h("div", { class: "c-text", text: r.text })),
        h("div", { class: "c-meta" },
          ctx ? h("span", { class: "c-ctx" }, icon("i-target"), ctx) : null,
          h("span", { class: "num", text: clock(r.ts) })));
    }
    if (r.role === "assistant") return h("div", { class: "c-row c-agent", "data-id": r.id }, h("div", { class: "md" }, ...markdown(r.text)));
    if (r.role === "tool") return h("div", { class: "c-row c-toolrow", "data-id": r.id }, toolEl(r));
    return h("div", { class: "c-row c-noterow", "data-id": r.id }, noteEl(r));
  }

  function putRow(r) {
    const el = rowEl(r);
    const old = els.get(r.id);
    if (old) old.replaceWith(el);
    else {
      empty?.remove();
      empty = null;
      log.insertBefore(el, working.isConnected ? working : null);
    }
    els.set(r.id, el);
  }
  function trim() {
    if (els.size <= KEPT_ROWS) return;
    const ids = [...els.keys()].sort((a, b) => a - b);
    for (const id of ids.slice(0, els.size - KEPT_ROWS)) { els.get(id).remove(); els.delete(id); }
  }

  const working = h("div", { class: "c-working", role: "status" });
  let empty = null;
  function turnStart() {
    const u = [...S.rows.values()].filter((r) => r.role === "user" && r.turn === S.turn).at(-1);
    return u ? Date.parse(u.ts) : null;
  }
  function renderWorking() {
    if (!S.busy) { working.remove(); return; }
    const since = turnStart();
    const secs = since ? Math.max(0, (Date.now() - since) / 1000) : null;
    const running = [...S.rows.values()].filter((r) => r.turn === S.turn && r.role === "tool" && r.ok == null).at(-1);
    const what = S.stopping || S.stopAsked ? t("chat.stopping") : running ? t("chat.usingTool", { tool: toolName(running.tool) }) : t("chat.thinking");
    working.replaceChildren(...[h("span", { class: "c-pulse" }), h("span", { text: what }),
      secs != null ? h("span", { class: "num dim", text: elapsed(secs) }) : null].filter(Boolean));
    working.classList.toggle("is-stopping", S.stopping || S.stopAsked);
    if (!working.isConnected) { log.append(working); afterAppend(0); }
  }
  app.on("tick", () => { if (S.busy) renderWorking(); });

  function renderAll() {
    els.clear();
    const rows = [...S.rows.values()].sort((a, b) => a.id - b.id);
    working.remove();
    if (!rows.length) {
      empty = renderEmpty();
      log.replaceChildren(empty);
    } else {
      empty = null;
      log.replaceChildren(...rows.map((r) => { const el = rowEl(r); els.set(r.id, el); return el; }));
    }
    renderWorking();
    renderControls();
    renderDot();
    requestAnimationFrame(() => toBottom());
  }
  function renderEmpty() {
    if (S.loaded && !S.engines.some((e) => e.available)) {
      return emptyState("i-alert", t("chat.noEngineTitle"), t("chat.noEngineBody"),
        h("ul", { class: "engine-why" }, ...S.engines.map((e) => h("li", {}, h("strong", { text: e.label }), h("span", { text: e.why })))));
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
    input.style.height = `${clamp(input.scrollHeight, 38, 180)}px`;
  }
  function setInput(text) {
    input.value = text;
    store("chat-draft", text || null);
    grow();
    input.setSelectionRange(text.length, text.length);
    renderControls();
  }
  input.placeholder = t("chat.placeholder");
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

    // the line under the box: why it cannot send, how long it is, or the keys
    const len = input.value.length;
    hint.className = "compose-hint";
    if (S.gone) { hint.textContent = t("chat.gone"); hint.classList.add("is-warn"); }
    else if (S.loaded && !engine() && !S.busy) { hint.textContent = t("chat.noEngine"); hint.classList.add("is-warn"); }
    else if (budgetGone() && !S.busy) { hint.textContent = t("chat.budgetGone", { budget: money(S.budget) }); hint.classList.add("is-error"); }
    else if (len > MAX_MESSAGE * 0.85) { hint.textContent = `${len} / ${MAX_MESSAGE}`; if (len > MAX_MESSAGE) hint.classList.add("is-error"); }
    else hint.textContent = S.busy ? t("chat.busyHint") : document.activeElement === input ? t("chat.keysEsc") : "";

    const e = engine();
    $("engineText").textContent = e ? e.label : S.loaded ? t("chat.noEngineShort") : "…";
    engineBtn.classList.toggle("is-none", !e);
    disable(engineBtn, S.busy ? t("chat.engineBusy") : !S.engines.length ? t("chat.loading") : null,
      e ? t("chat.engineTip", { label: e.label, why: e.why }) : t("chat.engineNone"));

    const sp = $("chatSpend");
    sp.hidden = !S.loaded || (S.budget == null && !S.spent);
    $("chatSpendText").textContent = S.budget != null ? `${money(S.spent)} / ${money(S.budget)}` : money(S.spent);
    const share = S.budget ? S.spent / S.budget : 0;
    $("chatSpendBar").hidden = !S.budget;
    $("chatSpendBar").style.setProperty("--fill", `${clamp(share * 100, 0, 100)}%`);
    sp.classList.toggle("is-high", share > 0.8);
    tip(sp, S.budget != null ? t("chat.spendTip", { spent: money(S.spent), budget: money(S.budget) }) : t("chat.spendTipNo", { spent: money(S.spent) }));
    renderContext();
    renderBlock();
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
    const list = h("ul", { class: "engine-why" }, ...S.engines.map((x) => h("li", {}, h("strong", { text: x.label }), h("span", { text: x.why }))));
    el.replaceChildren(h("strong", {}, icon("i-alert"), t("chat.noEngineTitle")),
      disclosure(t("chat.why"), list, false), list);
  }

  function showErr(text) { errLine.hidden = false; errLine.textContent = text; }
  function hideErr() { errLine.hidden = true; }

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
      if (status === 202) {
        setInput("");
        drop = { clip: null, playhead: false };
        S.busy = true; S.turn = data.turn;
        note(send, t("chat.sent"));
        toBottom();
      } else if (status === 409) {
        S.busy = true;
        showErr(t("chat.err409"));
      } else if (status === 413) showErr(t("chat.err413"));
      else if (status === 403) showErr(t("chat.err403"));
      else showErr(t("chat.err400", { why: data?.error || status }));
    } catch {
      S.gone = true;
      showErr(t("chat.errGone"));
    } finally {
      S.sending = false;
      renderWorking();
      renderControls();
    }
  }
  async function stop() {
    if (S.stopAsked || S.stopping) return;
    S.stopAsked = true;
    renderControls();
    renderWorking();
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
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (isOff(send)) { note(send, send.dataset.tip || "", "is-error"); return; }
    if (S.busy) stop(); else submit();
  });

  // ---------------------------------------------------------------- what the message is about
  let drop = { clip: null, playhead: false };           // what the person took off the next message
  function context() {
    const ctx = {};
    const c = app.selected ? app.clipById(app.selected, app.state?.tracks) : null;
    if (c && drop.clip !== c.id) {
      ctx.clip = c.id;
      if (c.start != null) ctx.start = +c.start.toFixed(3);
      if (c.end != null) ctx.end = +c.end.toFixed(3);
    }
    if (app.time > 0 && !drop.playhead) ctx.playhead = +app.time.toFixed(3);
    return Object.keys(ctx).length ? ctx : null;
  }
  let ctxKey = "";
  function renderContext() {
    const c = context();
    const key = JSON.stringify([c?.clip, c?.start, c?.end, c?.playhead != null ? timecode(c.playhead, app.fps()) : null]);
    if (key === ctxKey) return;
    ctxKey = key;
    ctxRow.hidden = !c;
    if (!c) { ctxRow.replaceChildren(); return; }
    const fps = app.fps();
    const chip = (text, label, onDrop) => {
      const x = h("button", { type: "button", class: "ctx-x" }, icon("i-close"));
      tip(x, t("chat.ctxDrop"), null, `${t("chat.ctxDrop")}: ${label}`);
      pressable(x, () => { onDrop(); ctxKey = ""; renderContext(); input.focus(); });
      return h("span", { class: "ctx-chip" }, h("span", { class: "ctx-text", text }), x);
    };
    const kids = [h("span", { class: "ctx-k", text: t("chat.ctxLabel") })];
    if (c.clip) {
      const text = c.start != null && c.end != null ? t("chat.about", { id: c.clip, a: timecode(c.start, fps), b: timecode(c.end, fps) })
        : t("chat.aboutClip", { id: c.clip });
      kids.push(chip(text, text, () => { drop.clip = c.clip; }));
    }
    if (c.playhead != null) {
      const text = t("chat.at", { t: timecode(c.playhead, fps) });
      kids.push(chip(text, text, () => { drop.playhead = true; }));
    }
    ctxRow.replaceChildren(...kids);
    tip(ctxRow.firstChild, t("chat.ctxTip"));
  }
  app.on("select", () => { if (app.selected !== drop.clip) drop.clip = null; renderContext(); });
  let ctxAt = 0;
  app.on("time", () => {                  // a playing film moves the chip four times a second, not every frame
    const now = performance.now();
    if (app.playing && now - ctxAt < 250) return;
    ctxAt = now;
    renderContext();
  });
  app.on("playing", renderContext);
  app.on("state", renderContext);
  app.on("ask-about", (id) => {
    if (drop.clip === id) drop.clip = null;
    renderContext();
    input.focus();
  });

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
        cur?.id === e.id ? icon("i-check", "engine-tick") : null),
      h("span", { class: "engine-why", text: e.available ? e.why : t("chat.cannot", { why: e.why }) }));
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
    if (!e.available) { note(options()[i], t("chat.cannot", { why: e.why }), "is-error"); return; }
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

  tip(pill, t("chat.toLatest"));
  input.style.height = "";
  grow();
  renderAll();
  listen();
  return { load };
}
