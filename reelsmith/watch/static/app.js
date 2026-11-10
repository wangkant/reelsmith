import { getHistory, getState, subscribe } from "./api.js";
import { createBeats } from "./beats.js";
import { createChat } from "./chat.js";
import { has, lang, t, translate } from "./i18n.js";
import { createMonitor } from "./monitor.js";
import { createPanel } from "./panel.js";
import { createTimeline } from "./timeline.js";
import { createTop } from "./top.js";
import { createTransport } from "./transport.js";
import { busy, clamp, closeOnBackdrop, elapsed, h, installTips, lowerFirst, note, pressable, storage, store, tip } from "./util.js";

installTips();
translate();

// A brand-new project has no length yet: that is a waiting state, not an error.
const NO_LENGTH = /has no length/;

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
  beat: null,
  beats: [],
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
  // What the monitor plays and the beats describe: always the current cut, or the last one that loaded.
  cut() { return this.state?.valid === false && this.lastGood ? this.lastGood : this.state; },
  dimmed() { return !this.viewing && this.state?.valid === false && !!this.lastGood; },
  empty() { return !!this.state?.empty; },
  broken() { return this.state?.valid === false && !this.state.empty; },

  // The standing of the result, in the person's language: the server's reason code wins over its English.
  result() {
    const r = this.state?.result;
    if (!r?.state) return { state: "none" };
    const reason = r.reason_code && has(r.reason_code) ? t(r.reason_code, localParams(r.params)) : r.reason;
    return { ...r, reason, accepted_at: r.accepted?.at || null };
  },

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
  showPanel(name) { panel.show(name); },
};
window.__watch = app;

// Layout codes carry their side as a word to translate; numbers and quoted text stay as they are.
function localParams(p = {}) {
  const out = { ...p };
  if (out.side && has(`side.${out.side}`)) out.side = t(`side.${out.side}`);
  if (out.stage && has(`stage.${out.stage}`)) out.stage = t(`stage.${out.stage}`);
  return out;
}

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
    if (app.status !== "connected") { app.status = "connected"; top.renderConn(); }
    const moved = !prev || prev.revision !== next.revision || JSON.stringify([prev.can, prev.action, prev.last_action, prev.result])
      !== JSON.stringify([next.can, next.action, next.last_action, next.result]);
    if (moved) {
      const before = prev?.valid ? prev.tracks : app.lastGood?.tracks;
      const newCut = !prev || prev.revision !== next.revision;
      app.state = next;
      if (next.valid) app.lastGood = next;
      const changed = newCut && prev && next.valid ? diff(before, next.tracks) : new Set();
      if (changed.size) {
        flash(changed);
        app.latest = changed;
      }
      setRunning(next.running ?? null);
      if (app.time > app.lastFrameTime()) app.setTime(app.lastFrameTime(), "state");
      const c = next.canvas || app.lastGood?.canvas;
      if (c?.width) {
        document.body.classList.toggle("is-tall", c.height >= c.width);
        document.body.classList.toggle("is-square", c.height === c.width);
      }
      document.body.classList.toggle("is-empty", app.empty());
      top.renderTop();
      renderError();
      renderSummary();
      app.emit("state", { revisionChanged: newCut });
      if (newCut && !app.viewing) app.emit("view", { changed, live: !!prev });
      if (firstPaint) {
        firstPaint = false;
        resume();
        requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("ready")));
      }
    } else setRunning(next.running ?? null);
  } catch (e) {
    console.warn("watch: refresh", e);
    app.status = "reconnecting";
    top.renderConn();
    clearTimeout(retryTimer);
    retryTimer = setTimeout(refresh, 2000);
  } finally {
    loading = false;
    if (again) { again = false; refresh(); }
  }
}
app.refresh = refresh;

// A language change reloads the page; the playhead and the open beat come back where they were.
function resume() {
  try {
    const r = JSON.parse(sessionStorage.getItem("rs-watch:resume"));
    sessionStorage.removeItem("rs-watch:resume");
    if (!r) return;
    if (r.beat != null) app.setBeat(r.beat, { seek: false });
    app.seek(r.time || 0);
  } catch { /* private window */ }
}

// ---------------------------------------------------------------- the agent at work
function setRunning(r) {
  const same = r && app.running && r.tool === app.running.tool && r.since === app.running.since;
  const was = JSON.stringify(app.running && { ...app.running, at: 0 });
  if (r) {
    const at = same && Math.abs(app.running.at - (performance.now() - (r.seconds || 0) * 1000)) < 1500
      ? app.running.at : performance.now() - (r.seconds || 0) * 1000;
    app.running = { ...r, at };
  } else {
    app.running = null;
  }
  top.renderAgent();
  if (!same) app.emit("running");
  else if (was !== JSON.stringify({ ...app.running, at: 0 })) app.emit("progress");
}

function runWhat(r) {
  const k = `run.${r.tool}`;
  return has(k) ? t(k) : t("run.other", { tool: r.tool });
}
const upperFirst = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// The words for a running call, shared by the top bar, the session and the stage so all say the same thing.
app.runText = () => {
  const r = app.running;
  if (!r) return null;
  const secs = (performance.now() - r.at) / 1000;
  const what = runWhat(r);
  const sk = r.stage_code || (r.stage ? `stage.${r.stage}` : null);
  const stage = sk ? (has(sk) ? t(sk) : r.stage) : null;
  const pct = typeof r.progress === "number" ? t("unit.pct", { n: Math.round(r.progress * 100) }) : null;
  const stuck = secs > 600;
  const how = stage ? (pct ? `${stage} (${pct})` : stage) : pct;
  return {
    what, lower: lowerFirst(what), stuck, secs, elapsed: elapsed(secs), stage, pct,
    figures: [pct, elapsed(secs)].filter(Boolean).join(" · "),
    short: how ? upperFirst(how) : what,
    text: `${stuck ? `${t("run.stuck")}: ` : ""}${how ? t("run.withStage", { what, how }) : what}`,
  };
};
setInterval(() => { top.renderAgent(); app.emit("tick"); }, 1000);

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- the Tracks drawer's summary line
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
    h("span", { text: t("sum.clips", { n: sum.clips ?? 0 }) }),
    sum.covered != null ? h("span", { text: t("sum.picture", { p: t("unit.pct", { n: Math.round(sum.covered * 100) }) }) }) : null,
    errors ? h("span", { class: "is-error", text: t("sum.errors", { n: errors }) }) : null,
    warnings ? h("span", { class: "is-warn", text: t("sum.warnings", { n: warnings }) }) : null,
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
    $("historyText").textContent = t("tl.viewing", { n: app.viewing.n, at: (app.viewing.at || "").slice(11, 19) });
    tip($("historyText"), app.viewing.summary);
  }
  document.body.classList.toggle("is-history", !!app.viewing);
  top.renderResult();
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
    if (!tracksOpen()) setTracks(true);
    renderBanner();
    app.emit("view", { changed: new Set() });
  } catch (e) {
    note($("historyBanner").hidden ? $("tracksBtn") : $("historyBanner"), t("tl.historyFailed", { n, why: e.message }), "is-error");
  } finally {
    clearTimeout(slow);
    busy($("historyBanner"), false);
    $("summary").classList.remove("is-loading");
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

// ---------------------------------------------------------------- the Tracks drawer
const tracksBtn = $("tracksBtn"), timelineEl = $("timeline");
const tracksOpen = () => !timelineEl.hidden;
function setTracks(open) {
  timelineEl.hidden = !open;
  document.body.classList.toggle("tracks-open", open);
  tracksBtn.setAttribute("aria-expanded", String(open));
  tracksBtn.setAttribute("aria-pressed", String(open));
  tip(tracksBtn, t(open ? "beats.tracksHide" : "beats.tracksShow"), "T");
  store("tracks", open);
  if (!open && app.viewing) app.backToNow();
  app.emit("layout");
}
app.toggleTracks = () => setTracks(!tracksOpen());
pressable(tracksBtn, app.toggleTracks);

const followBtn = $("followBtn");
function setFollow(v, said = false) {
  app.follow = v;
  store("follow", v);
  followBtn.setAttribute("aria-pressed", String(v));
  tip(followBtn, t(v ? "tl.followOn" : "tl.followOff"));
  if (said) note(followBtn, t(v ? "follow.on" : "follow.off"));
}
pressable(followBtn, () => setFollow(!app.follow, true));

// ---------------------------------------------------------------- help
const help = $("help");
const TYPES = ["video", "image", "text", "component", "evidence", "shape", "audio", "voice", "caption"];
$("legend").replaceChildren(...TYPES.map((k) => h("li", {}, h("span", { class: "sw", style: { "--sw": `var(--clip-${k})` } }), t(`type.${k}`))));
// Close takes the focus, so the sheet would open scrolled to its foot: start it at the top.
app.openHelp = () => { help.showModal(); help.scrollTop = 0; };
pressable($("helpClose"), () => help.close());
closeOnBackdrop(help);

// ---------------------------------------------------------------- wiring
const top = createTop(app);
app.on("chat-busy", () => top.renderAgent());
const monitor = createMonitor(app);
const timeline = createTimeline(app);
const panel = createPanel(app);
createBeats(app);
createTransport(app);
createChat(app, panel);
// The stage takes the canvas's shape: as wide as the area allows while the beats keep their row below it, or,
// for a vertical or square film, as tall as the area with the beats in a column beside it.
const stageArea = $("stageArea"), playerBox = $("playerBox"), screenEl = $("screen");
function fitStage() {
  const c = app.cut()?.canvas || app.state?.canvas;
  if (!c?.width) return;
  const cs = getComputedStyle(stageArea);
  const aw = stageArea.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const ah = stageArea.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const tr = $("transport").offsetHeight || 56, gap = parseFloat(cs.rowGap) || 16;
  const ar = c.height / c.width;
  const keep = (innerHeight < 760 ? 186 : 220) + (tracksOpen() ? 272 : 0);
  // a square film takes more of the width than a vertical one; either leaves the column of beats 300 px
  const w = Math.floor(c.height >= c.width ? Math.min(aw * (ar === 1 ? 0.6 : 0.52), aw - gap - 300, (ah - tr) / ar) : Math.min(aw, (ah - tr - gap - keep) / ar));
  playerBox.style.width = `${Math.max(200, w)}px`;
  screenEl.style.height = `${Math.round(Math.max(200, w) * ar)}px`;
  monitor.layout();
}
new ResizeObserver(fitStage).observe(stageArea);
app.on("state", fitStage);
app.on("layout", fitStage);

pressable($("zoomIn"), timeline.zoomIn);
pressable($("zoomOut"), timeline.zoomOut);
pressable($("zoomFit"), () => {
  if ($("zoomFit").getAttribute("aria-pressed") === "true") note($("zoomFit"), t("tl.fitted"));
  timeline.fit();
});
tip($("zoomLabel"), t("tl.zoomLabel"));
app.on("view", renderSummary);

// ---------------------------------------------------------------- keys
addEventListener("keydown", (e) => {
  if (e.defaultPrevented || e.altKey) return;
  const tag = e.target?.tagName;
  const typing = tag === "INPUT" && e.target.type !== "range" || tag === "TEXTAREA" || e.target?.isContentEditable;
  if (typing || help.open && e.key !== "?") return;
  if (document.querySelector("dialog[open]") && e.key !== "?") return;
  const onRange = tag === "INPUT" && e.target.type === "range";
  const onList = e.target?.closest?.("[role=listbox], [role=menu], [role=tablist]");
  const k = e.key;
  const fps = app.fps();
  if (k === " " && !(e.ctrlKey || e.metaKey)) {
    if (["BUTTON", "SUMMARY"].includes(tag) && e.target.id !== "playBtn" || e.target?.getAttribute?.("role") === "button" || onList) return;
    e.preventDefault();
    app.toggle();
    if (e.target?.id !== "playBtn") monitor.pop();
  } else if ((k === "ArrowLeft" || k === "ArrowRight") && !onRange && !onList && !(e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    app.step(k === "ArrowLeft" ? -(e.shiftKey ? fps : 1) : e.shiftKey ? fps : 1);
  } else if (k === "Home" && !onRange && !onList) { e.preventDefault(); app.seek(0); }
  else if (k === "End" && !onRange && !onList) { e.preventDefault(); app.seek(app.lastFrameTime()); }
  else if (k === "PageUp" || k === "PageDown") { e.preventDefault(); app.stepBeat(k === "PageUp" ? -1 : 1); }
  else if (e.ctrlKey || e.metaKey) return;
  else if ((k === "+" || k === "=") && tracksOpen()) { e.preventDefault(); timeline.zoomIn(); }
  else if ((k === "-" || k === "_") && tracksOpen()) { e.preventDefault(); timeline.zoomOut(); }
  else if ((k === "f" || k === "F") && tracksOpen()) timeline.fit();
  else if (k === "t" || k === "T") app.toggleTracks();
  else if (k === "s" || k === "S") app.setSafe(!app.safe);
  else if (k === "m" || k === "M") app.toggleMute();
  else if (k === "?") { e.preventDefault(); help.open ? help.close() : app.openHelp(); }
  else if (k === "Escape" && app.closeMenus?.()) e.preventDefault();
  else if (k === "Escape" && app.viewing) app.backToNow();
  else if (k === "Escape" && panel.current() !== "chat") panel.show("chat");
  else if (k === "Escape" && app.selected) app.select(null);
  else if (k === "Escape" && app.beat != null) app.setBeat(null, { seek: false });
});

// ---------------------------------------------------------------- start
document.documentElement.classList.toggle("lang-cjk", /^(zh|ja|ko)/.test(lang));
setFollow(app.follow);
setTracks(storage("tracks", false));
top.renderConn();
top.renderAgent();
subscribe(() => refresh(), (s) => { app.status = s; top.renderConn(); }, setRunning,
  (name, d) => (name === "frames" ? app.emit("frames", d) : refresh()));
refresh();
