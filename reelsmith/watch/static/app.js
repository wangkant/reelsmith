import { getHistory, getState, subscribe } from "./api.js";
import { createChat } from "./chat.js";
import { lang, t, translate } from "./i18n.js";
import { createMonitor } from "./monitor.js";
import { createPanel } from "./panel.js";
import { createTimeline } from "./timeline.js";
import {
  busy, bytes, clamp, clock, closeOnBackdrop, disable, elapsed, h, installTips, isOff, note, pressable, shortTime, storage, store,
  timecode, tip,
} from "./util.js";

installTips();
translate();

// A brand-new project has no length yet: that is a waiting state, not an error.
const NO_LENGTH = /has no length/;
const PANELS = ["chat", "activity", "issues", "clip", "assets"];

// ---------------------------------------------------------------- the shared store
const listeners = {};
const app = {
  state: null,
  lastGood: null,
  viewing: null,          // a history snapshot {n, at, summary, duration, tracks} or null for the live cut
  replaying: false,
  time: 0,
  playing: false,
  waiting: false,         // playing was asked for but no frame has come yet
  scrubbing: false,
  selected: null,
  follow: storage("follow", true),
  safe: storage("safe", false),
  source: "live",
  sourceBusy: false,
  volume: storage("volume", 1),
  muted: storage("muted", false),
  changed: new Map(),
  latest: new Set(),      // clips the latest live batch changed; marked until the next one
  running: null,
  status: "connecting",

  on(evt, fn) { (listeners[evt] ||= []).push(fn); },
  emit(evt, arg) { for (const fn of listeners[evt] || []) fn(arg); },

  fps() { return this.state?.canvas?.fps || this.lastGood?.canvas?.fps || 30; },
  frame() { return Math.round(this.time * this.fps()); },
  duration() {
    const d = this.view().duration || 0;
    const del = this.source === "delivered" ? this.state?.render?.delivered?.duration || 0 : 0;
    return Math.max(d, del);
  },
  lastFrameTime() { return Math.max(0, (Math.max(1, Math.round(this.duration() * this.fps())) - 1) / this.fps()); },

  // What the timeline draws: a history snapshot, the live cut, or the last cut that loaded (dimmed).
  view() {
    const s = this.state || {};
    if (this.viewing) {
      return { tracks: this.viewing.tracks, duration: this.viewing.duration, voice: s.voice, markers: [], chapters: [],
        issues: [], assets: s.assets || [], valid: true };
    }
    if (s.valid === false && this.lastGood) return { ...this.lastGood, valid: false };
    return s;
  },
  // What the monitor plays: always the current cut, or the last one that loaded.
  cut() { return this.state?.valid === false && this.lastGood ? this.lastGood : this.state; },
  dimmed() { return !this.viewing && this.state?.valid === false && !!this.lastGood; },
  empty() { return !!this.state?.empty; },
  broken() { return this.state?.valid === false && !this.state.empty; },

  setTime(sec, origin = "seek") {
    const nt = clamp(sec, 0, this.lastFrameTime());
    if (nt === this.time && origin !== "seek" && origin !== "scrub") return;
    this.time = nt;
    this.emit("time", origin);
  },
  seek(sec, origin = "seek") { this.setTime(Math.round(sec * this.fps()) / this.fps(), origin); },
  step(frames) { this.seek(this.time + frames / this.fps()); },
  setPlaying(v, origin = "ui") {
    if (v && !this.duration()) return;
    if (v && origin === "ui" && this.time >= this.lastFrameTime() - 1e-6) this.setTime(0, "seek");
    if (this.playing === v) return;
    this.playing = v;
    if (!v) this.setWaiting(false);
    this.emit("playing", origin);
  },
  setWaiting(v) {
    if (this.waiting === v) return;
    this.waiting = v;
    this.emit("waiting");
  },
  toggle() { this.setPlaying(!this.playing, "ui"); },
  select(id) { this.selected = id; this.emit("select", id); },
  clipById(id, tracks = this.view().tracks) {
    for (const tr of tracks || []) for (const c of tr.clips || []) if (c.id === id) return c;
    return null;
  },
  seekToClip(id) {
    const c = this.clipById(id);
    if (c?.start != null) this.seek(c.start);
  },
  openIssue(is) {
    if (is.clip) this.select(is.clip);
    if (is.t != null) this.seek(is.t);
    else if (is.clip) this.seekToClip(is.clip);
  },
  changedAt(id) { return this.changed.get(id) || 0; },
  showPanel(name) {
    const i = PANELS.indexOf(name);
    // the chat already shows a picked clip as the context of the next message: stay there
    if (name === "clip" && panel.current() === 0) return;
    if (i >= 0) panel.show(i);
  },
};
window.__watch = app;

// ---------------------------------------------------------------- diffing two cuts
function clipKeys(tracks) {
  const m = new Map();
  for (const tr of tracks || []) {
    for (const c of tr.clips || []) m.set(c.id, JSON.stringify([tr.id, c.start, c.end, c.raw, c.label]));
    if (tr.kind === "captions") m.set(`#${tr.id}`, JSON.stringify(tr.items || []));
  }
  return m;
}
function diff(before, after) {
  const a = clipKeys(before), b = clipKeys(after);
  const out = new Set();
  for (const [id, k] of b) if (!id.startsWith("#") && a.get(id) !== k) out.add(id);
  return out;
}
function flash(ids) {
  const now = performance.now();
  for (const id of ids) app.changed.set(id, now);
}

// ---------------------------------------------------------------- loading state
function prepare(next) {
  const noTracks = !(next.tracks || []).length && !next.voice;
  next.empty = noTracks && (next.valid || NO_LENGTH.test(next.error || "")) && !app.lastGood?.tracks?.length;
  if (next.empty) next.issues = (next.issues || []).filter((i) => !NO_LENGTH.test(i.text));
  return next;
}

let loading = false, again = false, firstPaint = true, retryTimer = 0;
async function refresh() {
  if (loading) { again = true; return; }
  loading = true;
  try {
    const next = prepare(await getState());
    const prev = app.state;
    if (app.status !== "connected") { app.status = "connected"; renderConn(); }
    setRunning(next.running ?? null);
    if (!prev || prev.revision !== next.revision) {
      const before = prev?.valid ? prev.tracks : app.lastGood?.tracks;
      app.state = next;
      if (next.valid) app.lastGood = next;
      const changed = prev && next.valid ? diff(before, next.tracks) : new Set();
      if (changed.size) {
        flash(changed);
        app.latest = changed;
      }
      if (app.time > app.lastFrameTime()) app.setTime(app.lastFrameTime(), "state");
      renderTop();
      renderError();
      renderSummary();
      app.emit("state", { revisionChanged: true });
      if (!app.viewing) app.emit("view", { changed, live: !!prev });
      if (firstPaint) {
        firstPaint = false;
        requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
      }
    }
  } catch (e) {
    console.warn("watch: refresh", e);
    app.status = "reconnecting";
    renderConn();
    clearTimeout(retryTimer);
    retryTimer = setTimeout(refresh, 2000);
  } finally {
    loading = false;
    if (again) { again = false; refresh(); }
  }
}

// ---------------------------------------------------------------- the agent at work
function setRunning(r) {
  const same = r && app.running && r.tool === app.running.tool && r.since === app.running.since;
  if (r) {
    const at = same && Math.abs(app.running.at - (performance.now() - (r.seconds || 0) * 1000)) < 1500
      ? app.running.at : performance.now() - (r.seconds || 0) * 1000;
    app.running = { ...r, at };
  } else {
    app.running = null;
  }
  renderAgent();
  if (!same) app.emit("running");
}

function ago(ts) {
  const d = (Date.now() - new Date(ts).getTime()) / 1000;
  if (!(d >= 0)) return "";
  if (d < 10) return t("ago.now");
  if (d < 60) return t("ago.s", { n: Math.floor(d) });
  if (d < 3600) return t("ago.min", { n: Math.floor(d / 60) });
  return t("ago.h", { n: Math.floor(d / 3600) });
}

function runWhat(r) {
  return t(`run.${r.tool}`) !== `run.${r.tool}` ? t(`run.${r.tool}`) : t("run.other", { tool: r.tool });
}

// The words for a running call, shared by the top bar and the Activity feed so both say the same thing.
app.runText = () => {
  const r = app.running;
  if (!r) return null;
  const secs = (performance.now() - r.at) / 1000;
  const what = runWhat(r);
  const stage = r.stage ? (t(`stage.${r.stage}`) !== `stage.${r.stage}` ? t(`stage.${r.stage}`) : r.stage) : null;
  const pct = typeof r.progress === "number" ? `${Math.round(r.progress * 100)}%` : null;
  const stuck = secs > 600;
  return { what, stuck, secs, text: [stuck ? `${t("run.stuck")}: ${what}` : what, stage, pct, elapsed(secs)].filter(Boolean).join(" · ") };
};

const $ = (id) => document.getElementById(id);
function renderAgent() {
  const el = $("agent"), bar = $("runBar");
  const r = app.running;
  document.getElementById("timeline").classList.toggle("is-working", !!r);
  app.emit("tick");
  if (r) {
    const { what, stuck, secs, text } = app.runText();
    el.dataset.state = stuck ? "stuck" : "running";
    $("agentText").textContent = text;
    tip(el, stuck ? t("run.stuckTip", { what, ago: elapsed(secs) }) : t("status.tip"));
    bar.hidden = typeof r.progress !== "number";
    bar.style.setProperty("--p", `${clamp((r.progress || 0) * 100, 0, 100)}%`);
    return;
  }
  bar.hidden = true;
  const acts = app.state?.activity || [];
  const last = acts.at(-1)?.ts;
  el.dataset.state = app.state ? "idle" : "off";
  $("agentText").textContent = last ? t("status.idleAgo", { ago: ago(last) }) : t("status.idle");
  tip(el, t("status.tip"));
}
setInterval(renderAgent, 1000);

function renderConn() {
  const c = $("conn");
  c.dataset.state = app.status;
  $("connText").textContent = t(`status.${app.status}`);
  tip(c, app.status === "connected" ? t("status.connected") : t("status.goneTip"));
  renderTransport();
}

// ---------------------------------------------------------------- top bar
function orientation(c) {
  return c.width > c.height ? "landscape" : c.width < c.height ? "vertical" : "square";
}
function renderTop() {
  const s = app.state;
  const title = s.project?.title || app.lastGood?.project?.title || t("top.untitled");
  $("filmTitle").textContent = title;
  tip($("filmTitle"), title);
  $("projName").textContent = s.project?.name || "";
  tip($("projName"), t("top.projTip", { path: s.project?.path || "" }));
  document.title = `${title} · reelsmith watch`;

  const c = s.canvas || app.lastGood?.canvas;
  const info = $("canvasInfo");
  if (c?.width) {
    const len = app.cut()?.duration;
    info.replaceChildren(t(`top.orient.${orientation(c)}`), " ", h("span", { class: "num", text: `${c.width}×${c.height}` }),
      h("span", { class: "c-fps" }, " · ", h("span", { class: "num", text: t("top.fps", { n: c.fps }) })),
      ...(len ? [h("span", {}, " · ", h("span", { class: "num", text: timecode(len, c.fps) }))] : []));
    tip(info, t("top.canvasTip", { profile: c.profile, w: c.width, h: c.height, fps: c.fps }));
    document.body.classList.toggle("is-tall", c.height >= c.width);
  } else {
    info.replaceChildren();
  }

  const sp = s.spend;
  $("spendBox").hidden = !sp;
  if (sp) {
    const spent = `$${sp.project_usd.toFixed(2)}`;
    const share = sp.budget_usd ? sp.project_usd / sp.budget_usd : 0;
    $("spendText").textContent = sp.budget_usd ? `${spent} ${t("top.of")} $${sp.budget_usd.toFixed(2)}` : spent;
    $("spendBar").style.setProperty("--fill", `${clamp(share * 100, 0, 100)}%`);
    $("spendBar").hidden = !sp.budget_usd;
    $("spendBox").classList.toggle("is-high", share > 0.8 || !sp.budget_usd);
    tip($("spendBox"), sp.budget_usd ? t("top.spendTip", { spent, budget: `$${sp.budget_usd.toFixed(2)}` })
      : t("top.spendTipNoBudget", { spent }));
  }
  renderDelivery();
  renderAgent();
  renderConn();
}

function renderDelivery() {
  const s = app.state;
  const d = s.render?.delivered, last = s.render?.last;
  const del = $("delivery");
  del.hidden = !!app.viewing || app.broken();
  del.className = "pill";
  if (last && !last.ok && (!d || (last.at > d.at && !d.matches_cut))) {
    del.classList.add("is-error");
    del.textContent = `${t("top.lastFailed")}${last.stage ? ` · ${last.stage}` : ""}`;
    tip(del, last.text || "");
  } else if (d) {
    del.classList.add(d.matches_cut ? "is-ok" : "is-warn");
    del.textContent = t(d.matches_cut ? "top.delivered.matches" : "top.delivered.stale");
    tip(del, [clock(d.at), d.duration ? timecode(d.duration, app.fps()) : null, d.lufs != null ? `${d.lufs} LUFS` : null, bytes(d.bytes)]
      .filter(Boolean).join(" · "));
  } else {
    del.textContent = t("top.notDelivered");
    tip(del, t("top.notDeliveredTip"));
  }
  const sw = $("srcDelivered");
  disable(sw, d ? null : t("tr.noDelivered"), t("tr.deliveredTip"));
  if (!d && app.source === "delivered") setSource("live");
}

// ---------------------------------------------------------------- the film so far
function renderSummary() {
  const el = $("summary");
  el.hidden = !!app.viewing;
  const s = app.state, cut = app.cut();
  if (!cut || app.empty() || !(cut.tracks || []).length && !cut.voice) {
    el.replaceChildren(h("span", { class: "sum-k", text: t("sum.label") }), t("sum.empty"));
    tip(el, t("sum.tip"));
    return;
  }
  const sum = cut.summary || {};
  const issues = s.issues || [];
  const errors = issues.filter((i) => i.level === "error").length, warnings = issues.filter((i) => i.level === "warning").length;
  const parts = [
    h("b", { class: "num", text: shortTime(cut.duration || 0) }),
    h("span", { text: t("sum.clips", { n: sum.clips ?? 0 }) }),
    sum.covered != null ? h("span", { text: t("sum.picture", { p: `${Math.round(sum.covered * 100)}%` }) }) : null,
    h("span", { text: sum.narrated_s ? t("sum.narrated", { d: shortTime(sum.narrated_s) }) : t("sum.notNarrated") }),
    errors ? h("span", { class: "is-error", text: t("sum.errors", { n: errors }) }) : null,
    warnings ? h("span", { class: "is-warn", text: t("sum.warnings", { n: warnings }) }) : null,
    !errors && !warnings ? h("span", { class: "is-ok", text: t("sum.clean") }) : null,
  ].filter(Boolean);
  const out = [h("span", { class: "sum-k", text: t("sum.label") })];
  parts.forEach((p, i) => out.push(...(i ? [" · ", p] : [p])));
  el.replaceChildren(...out);
  tip(el, t("sum.tip"));
}

function renderError() {
  const s = app.state;
  const show = app.broken();
  $("errorBanner").hidden = !show;
  if (show) {
    $("errorText").textContent = s.error || "";
    $("errorNote").textContent = app.lastGood ? `${t("err.lastGood")} ${t("err.hint")}` : t("err.hint");
  }
}

function renderBanner() {
  const b = $("historyBanner");
  b.hidden = !app.viewing;
  if (app.viewing) {
    $("historyText").textContent = t("tl.viewing", { n: app.viewing.n, at: clock(app.viewing.at) });
    tip($("historyText"), app.viewing.summary);
  }
  document.body.classList.toggle("is-history", !!app.viewing);
  renderDelivery();
  renderSummary();
}
pressable($("backToNow"), () => app.backToNow());
tip($("backToNow"), t("tl.backToNowTip"), "Esc");

// ---------------------------------------------------------------- history
const snapshots = new Map();
async function loadSnapshot(n) {
  if (!snapshots.has(n)) snapshots.set(n, getHistory(n).catch((e) => { snapshots.delete(n); throw e; }));
  return snapshots.get(n);
}
let historyAsk = 0;
app.viewHistory = async (n) => {
  const ask = ++historyAsk;
  const slow = setTimeout(() => { busy($("historyBanner"), true); $("summary").classList.add("is-loading"); }, 150);
  try {
    const snap = await loadSnapshot(n);
    if (ask !== historyAsk) return;
    const before = app.view().tracks;
    app.viewing = snap;
    flash(diff(before, snap.tracks));
    renderBanner();
    app.emit("view", { changed: new Set() });
  } catch (e) {
    note($("historyBanner").hidden ? $("summary") : $("historyBanner"), t("tl.historyFailed", { n, why: e.message }), "is-error");
  } finally {
    clearTimeout(slow);
    busy($("historyBanner"), false);
  }
};
app.backToNow = () => {
  stopReplay();
  historyAsk++;
  if (!app.viewing) return;
  const before = app.viewing.tracks;
  app.viewing = null;
  flash(diff(before, app.view().tracks));
  renderBanner();
  app.emit("view", { changed: new Set() });
};
function sameCut(a, b) {
  const ka = clipKeys(a), kb = clipKeys(b);
  if (ka.size !== kb.size) return false;
  for (const [id, k] of ka) if (kb.get(id) !== k) return false;
  return true;
}
// Batches that change nothing on the timeline (an asset registered, the title set) are stepped over.
async function visibleFrom(i, d) {
  const hist = app.state?.history || [];
  const shown = app.view().tracks;
  for (let j = i + d; j >= 0 && j < hist.length; j += d) {
    try {
      if (!sameCut(shown, (await loadSnapshot(hist[j].n)).tracks)) return j;
    } catch {
      return j;              // viewHistory says why it cannot load
    }
  }
  return d > 0 ? hist.length : i;
}
app.historyIndex = () => {
  const hist = app.state?.history || [];
  return app.viewing ? hist.findIndex((x) => x.n === app.viewing.n) : hist.length;
};
app.stepHistory = async (d) => {
  const hist = app.state?.history || [];
  if (!hist.length) return false;
  const i = app.historyIndex();
  const j = clamp(await visibleFrom(i, d), 0, hist.length);
  if (j === i) return false;
  if (j >= hist.length) app.backToNow(); else await app.viewHistory(hist[j].n);
  return true;
};
let replayTimer = 0;
function stopReplay() {
  clearTimeout(replayTimer);
  if (app.replaying) { app.replaying = false; app.emit("replay"); }
}
app.toggleReplay = async () => {
  if (app.replaying) return stopReplay();
  const hist = app.state?.history || [];
  if (!hist.length) return;
  app.replaying = true;
  app.emit("replay");
  if (!app.viewing || app.historyIndex() >= hist.length - 1) await app.viewHistory(hist[0].n);
  const tick = async () => {
    if (!app.replaying) return;
    await app.stepHistory(1);
    if (!app.viewing) return stopReplay();
    replayTimer = setTimeout(tick, 900);
  };
  replayTimer = setTimeout(tick, 900);
};

// ---------------------------------------------------------------- transport
const playBtn = $("playBtn");
function renderTransport() {
  const nothing = !app.duration();
  playBtn.setAttribute("aria-pressed", String(app.playing));
  playBtn.classList.toggle("is-playing", app.playing);
  disable(playBtn, nothing ? t("tr.nothing") : null, t(app.playing ? "tr.pause" : "tr.play"), "Space");
  busy(playBtn, app.playing && app.waiting);
  const note = $("tcNote");
  const gone = app.status !== "connected" && app.playing && app.waiting;
  note.textContent = gone ? t("mon.serverGone") : app.playing && app.waiting ? t("mon.buffering") : "";
  note.classList.toggle("is-warn", gone);
  renderEnds();
}
function renderEnds() {
  const atStart = app.time <= 1e-6, atEnd = app.time >= app.lastFrameTime() - 1e-6 || !app.duration();
  disable($("startBtn"), atStart ? t("tr.atStart") : null, t("tr.start"), "Home");
  disable($("backBtn"), atStart ? t("tr.atStart") : null, t("tr.back"), "←");
  disable($("fwdBtn"), atEnd ? t("tr.atEnd") : null, t("tr.fwd"), "→");
  disable($("endBtn"), atEnd ? t("tr.atEnd") : null, t("tr.end"), "End");
}
function renderTime() {
  $("tc").textContent = timecode(app.time, app.fps());
  $("tcFrame").textContent = t("tr.frameN", { n: app.frame() });
  $("tcTotal").textContent = timecode(app.duration(), app.fps());
  renderEnds();
}
pressable(playBtn, () => app.toggle());
pressable($("startBtn"), () => app.seek(0));
pressable($("endBtn"), () => app.seek(app.lastFrameTime()));
pressable($("backBtn"), () => app.step(-1));
pressable($("fwdBtn"), () => app.step(1));

const vol = $("volume"), volVal = $("volVal");
let volHide = 0;
function renderAudio() {
  const v = app.muted ? 0 : app.volume;
  vol.value = String(v);
  vol.style.setProperty("--fill", `${v * 100}%`);
  vol.setAttribute("aria-valuetext", t("tr.volumeValue", { v: Math.round(v * 100) }));
  tip(vol, t("tr.volumeValue", { v: Math.round(v * 100) }));
  const mb = $("muteBtn");
  mb.setAttribute("aria-pressed", String(app.muted));
  tip(mb, t(app.muted ? "tr.unmute" : "tr.mute"));
  mb.classList.toggle("is-muted", app.muted || app.volume === 0);
}
function showVolume() {
  volVal.hidden = false;
  volVal.textContent = `${Math.round(Number(vol.value) * 100)}%`;
  volVal.style.setProperty("--x", `${5 + Number(vol.value) * (vol.offsetWidth - 10)}px`);
  clearTimeout(volHide);
  volHide = setTimeout(() => { volVal.hidden = true; }, 900);
}
vol.addEventListener("input", () => {
  app.volume = Number(vol.value);
  app.muted = app.volume === 0;
  store("volume", app.volume); store("muted", app.muted);
  renderAudio();
  showVolume();
  app.emit("audio");
});
vol.addEventListener("pointerdown", showVolume);
pressable($("muteBtn"), () => {
  app.muted = !app.muted;
  if (!app.muted && app.volume === 0) app.volume = 1;
  store("muted", app.muted);
  renderAudio();
  app.emit("audio");
});

function setSafe(v) {
  app.safe = v;
  store("safe", v);
  $("safeBtn").setAttribute("aria-pressed", String(v));
  tip($("safeBtn"), t(v ? "tr.safeOn" : "tr.safe"), "S", t("tr.safe"));
  app.emit("safe");
}
pressable($("safeBtn"), () => setSafe(!app.safe));

function setSource(src) {
  app.source = src;
  $("srcLive").setAttribute("aria-pressed", String(src === "live"));
  $("srcDelivered").setAttribute("aria-pressed", String(src === "delivered"));
  app.emit("source");
  renderTime();
  renderTransport();
}
app.setSource = setSource;
tip($("srcLive"), t("tr.liveTip"));
pressable($("srcLive"), () => setSource("live"));
pressable($("srcDelivered"), () => setSource("delivered"));
app.on("source-busy", () => {
  busy($("srcDelivered"), app.sourceBusy);
  if (app.sourceBusy) tip($("srcDelivered"), t("tr.deliveredLoading"));
  else if (!isOff($("srcDelivered"))) tip($("srcDelivered"), t("tr.deliveredTip"));
});

// A change landed while the person was playing: offer to go there instead of pulling the playhead away.
const jump = $("jumpChange");
let jumpTo = null, jumpHide = 0;
app.on("pending-change", ({ at }) => {
  jumpTo = at;
  $("jumpText").textContent = t("tr.jumpChange", { t: timecode(at, app.fps()) });
  tip(jump, t("tr.jumpChangeTip"));
  jump.hidden = false;
  clearTimeout(jumpHide);
  jumpHide = setTimeout(() => { jump.hidden = true; }, 12000);
});
pressable(jump, () => {
  jump.hidden = true;
  if (jumpTo != null) app.seek(jumpTo);
});

// ---------------------------------------------------------------- timeline toolbar
const followBtn = $("followBtn");
function setFollow(v, said = false) {
  app.follow = v;
  store("follow", v);
  followBtn.setAttribute("aria-pressed", String(v));
  tip(followBtn, t(v ? "tl.followOn" : "tl.followOff"));
  if (said) note(followBtn, t(v ? "follow.on" : "follow.off"));
}
pressable(followBtn, () => setFollow(!app.follow, true));

// ---------------------------------------------------------------- splitter between the monitor row and the timeline
const split = $("split");
let userTl = storage("tl-user", null);
function maxTl() { return Math.max(180, innerHeight - 260); }
function applyTlHeight() {
  const ih = innerHeight;
  const tall = document.body.classList.contains("is-tall");
  const want = userTl ?? clamp(timeline.naturalHeight(), ih * 0.3, ih * (tall ? 0.36 : 0.42));
  const v = Math.round(clamp(want, 170, maxTl()));
  document.documentElement.style.setProperty("--tl-h", `${v}px`);
  split.setAttribute("aria-valuenow", String(v));
  split.setAttribute("aria-valuemin", "170");
  split.setAttribute("aria-valuemax", String(maxTl()));
}
function setUserTl(px) {
  userTl = Math.round(clamp(px, 170, maxTl()));
  store("tl-user", userTl);
  applyTlHeight();
}
tip(split, t("split.tip"), null, t("tl.timeline"));
split.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  split.setPointerCapture(e.pointerId);
  split.classList.add("is-dragging");
  const move = (ev) => setUserTl(innerHeight - ev.clientY - 3);
  const up = () => {
    split.classList.remove("is-dragging");
    split.removeEventListener("pointermove", move);
    split.removeEventListener("pointerup", up);
    split.removeEventListener("pointercancel", up);
  };
  split.addEventListener("pointermove", move);
  split.addEventListener("pointerup", up);
  split.addEventListener("pointercancel", up);
});
function autoHeight() {
  userTl = null;
  store("tl-user", null);
  applyTlHeight();
  note(split, t("split.auto"));
}
split.addEventListener("dblclick", autoHeight);
split.addEventListener("keydown", (e) => {
  const cur = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tl-h")) || 300;
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    e.preventDefault();
    e.stopPropagation();
    setUserTl(cur + (e.key === "ArrowUp" ? 24 : -24));
  } else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    e.stopPropagation();
    autoHeight();
  }
});
addEventListener("resize", applyTlHeight);

// ---------------------------------------------------------------- help
const help = $("help");
const TYPES = ["video", "image", "text", "component", "evidence", "shape", "audio", "voice", "caption"];
$("legend").replaceChildren(...TYPES.map((k) => h("li", {}, h("span", { class: "sw", style: { "--sw": `var(--clip-${k})` } }), t(`type.${k}`))));
const helpBtn = $("helpBtn");
tip(helpBtn, t("help.btn"), "?");
// Close takes the focus, so the sheet would open scrolled to its foot: start it at the top.
app.openHelp = () => { help.showModal(); help.scrollTop = 0; };
pressable(helpBtn, app.openHelp);
pressable($("helpClose"), () => help.close());
closeOnBackdrop(help);

// ---------------------------------------------------------------- wiring
const monitor = createMonitor(app);
const timeline = createTimeline(app);
const panel = createPanel(app);
createChat(app, panel);
pressable($("zoomIn"), timeline.zoomIn);
pressable($("zoomOut"), timeline.zoomOut);
pressable($("zoomFit"), () => {
  if ($("zoomFit").getAttribute("aria-pressed") === "true") note($("zoomFit"), t("tl.fitted"));
  timeline.fit();
});
tip($("zoomLabel"), t("tl.zoomLabel"));

app.on("time", renderTime);
app.on("playing", renderTransport);
app.on("waiting", renderTransport);
app.on("state", () => { renderTime(); renderTransport(); });
app.on("view", () => { if (!app.viewing) applyTlHeight(); renderSummary(); });   // a past batch never resizes the window

// ---------------------------------------------------------------- keys
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || e.altKey) return;
  const tag = e.target?.tagName;
  const typing = tag === "INPUT" && e.target.type !== "range" || tag === "TEXTAREA" || e.target?.isContentEditable;
  if (typing || help.open && e.key !== "?") return;
  const onRange = tag === "INPUT" && e.target.type === "range";
  const k = e.key;
  const fps = app.fps();
  if (k === " " && !(e.ctrlKey || e.metaKey)) {
    if ((tag === "BUTTON" || e.target?.getAttribute?.("role") === "tab") && e.target.id !== "playBtn") return;
    e.preventDefault();
    app.toggle();
    if (e.target?.id !== "playBtn") monitor.pop();
  } else if ((k === "ArrowLeft" || k === "ArrowRight") && !onRange && !(e.ctrlKey || e.metaKey)) {
    if (e.target?.getAttribute?.("role") === "tab") return;
    e.preventDefault();
    const n = e.shiftKey ? fps : 1;
    app.step(k === "ArrowLeft" ? -n : n);
  } else if (k === "Home" && !onRange) { e.preventDefault(); app.seek(0); }
  else if (k === "End" && !onRange) { e.preventDefault(); app.seek(app.lastFrameTime()); }
  else if ((k === "+" || k === "=") && !(e.ctrlKey || e.metaKey)) { e.preventDefault(); timeline.zoomIn(); }
  else if ((k === "-" || k === "_") && !(e.ctrlKey || e.metaKey)) { e.preventDefault(); timeline.zoomOut(); }
  else if (e.ctrlKey || e.metaKey) return;
  else if (k === "f" || k === "F") timeline.fit();
  else if (k === "s" || k === "S") setSafe(!app.safe);
  else if (k >= "1" && k <= "5") panel.show(Number(k) - 1);
  else if (k === "?") { e.preventDefault(); help.open ? help.close() : app.openHelp(); }
  else if (k === "Escape" && app.viewing) app.backToNow();
  else if (k === "Escape" && app.selected) app.select(null);
});

// ---------------------------------------------------------------- start
document.documentElement.classList.toggle("lang-zh", lang === "zh");
setFollow(app.follow);
setSafe(app.safe);
setSource("live");
renderAudio();
renderTransport();
renderTime();
renderConn();
applyTlHeight();
subscribe(() => refresh(), (s) => { app.status = s; renderConn(); }, setRunning);
refresh();
