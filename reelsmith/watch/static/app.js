import { getHistory, getState, subscribe } from "./api.js";
import { t, translate } from "./i18n.js";
import { createMonitor } from "./monitor.js";
import { createPanel } from "./panel.js";
import { createTimeline } from "./timeline.js";
import { bytes, clamp, clock, h, storage, store, timecode } from "./util.js";

translate();

// ---------------------------------------------------------------- the shared store
const listeners = {};
const app = {
  state: null,
  lastGood: null,
  viewing: null,          // a history snapshot {n, at, summary, duration, tracks} or null for the live cut
  replaying: false,
  time: 0,
  playing: false,
  selected: null,
  follow: storage("follow", true),
  safe: storage("safe", false),
  source: "live",
  volume: storage("volume", 1),
  muted: storage("muted", false),
  changed: new Map(),
  editingUntil: 0,
  status: "connecting",

  on(evt, fn) { (listeners[evt] ||= []).push(fn); },
  emit(evt, arg) { for (const fn of listeners[evt] || []) fn(arg); },

  fps() { return this.state?.canvas?.fps || 30; },
  frame() { return Math.round(this.time * this.fps()); },
  duration() {
    const d = this.view().duration || 0;
    const del = this.source === "delivered" ? this.state?.render?.delivered?.duration || 0 : 0;
    return Math.max(d, del);
  },
  lastFrameTime() { return Math.max(0, (Math.max(1, Math.round(this.duration() * this.fps())) - 1) / this.fps()); },

  view() {
    const s = this.state || {};
    if (this.viewing) {
      return { tracks: this.viewing.tracks, duration: this.viewing.duration, voice: s.voice, markers: [], chapters: [],
        issues: [], valid: true };
    }
    if (s.valid === false && this.lastGood) return { ...this.lastGood, valid: false };
    return s;
  },
  dimmed() { return !this.viewing && this.state?.valid === false && !!this.lastGood; },

  setTime(sec, origin = "seek") {
    const nt = clamp(sec, 0, this.lastFrameTime());
    if (nt === this.time && origin !== "seek" && origin !== "scrub") return;
    this.time = nt;
    this.emit("time", origin);
  },
  seek(sec, origin = "seek") { this.setTime(Math.round(sec * this.fps()) / this.fps(), origin); },
  step(frames) { this.seek(this.time + frames / this.fps()); },
  setPlaying(v, origin = "ui") {
    if (v && origin === "ui" && this.time >= this.lastFrameTime() - 1e-6) this.setTime(0, "seek");
    if (this.playing === v) return;
    this.playing = v;
    this.emit("playing", origin);
  },
  toggle() { this.setPlaying(!this.playing, "ui"); },
  select(id) { this.selected = id; this.emit("select", id); },
  seekToClip(id) {
    for (const tr of this.view().tracks || []) for (const c of tr.clips || []) if (c.id === id) return this.seek(c.start);
  },
  openIssue(is) {
    if (is.clip) this.select(is.clip);
    if (is.t != null) this.seek(is.t);
    else if (is.clip) this.seekToClip(is.clip);
  },
  changedAt(id) { return this.changed.get(id) || 0; },
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
let loading = false, again = false;
async function refresh() {
  if (loading) { again = true; return; }
  loading = true;
  try {
    const next = await getState();
    const prev = app.state;
    const revisionChanged = !prev || prev.revision !== next.revision;
    if (revisionChanged) {
      const before = prev?.valid ? prev.tracks : app.lastGood?.tracks;
      app.state = next;
      if (next.valid) app.lastGood = next;
      const changed = prev && next.valid ? diff(before, next.tracks) : new Set();
      if (prev) {
        app.editingUntil = Date.now() + 4000;
        flash(changed);
      }
      if (app.time > app.lastFrameTime()) app.setTime(app.lastFrameTime(), "state");
      renderTop();
      renderError();
      app.emit("state", { revisionChanged });
      if (!app.viewing) app.emit("view", { changed });
    }
  } catch (e) {
    app.status = "reconnecting";
    renderStatus();
  } finally {
    loading = false;
    if (again) { again = false; refresh(); }
  }
}

// ---------------------------------------------------------------- history
const snapshots = new Map();
async function loadSnapshot(n) {
  if (!snapshots.has(n)) snapshots.set(n, getHistory(n).catch((e) => { snapshots.delete(n); throw e; }));
  return snapshots.get(n);
}
app.viewHistory = async (n) => {
  try {
    const snap = await loadSnapshot(n);
    const before = app.view().tracks;
    app.viewing = snap;
    const changed = diff(before, snap.tracks);
    flash(changed);
    renderBanner();
    app.emit("view", { changed });
  } catch (e) {
    console.warn("history", n, e);
  }
};
app.backToNow = () => {
  stopReplay();
  if (!app.viewing) return;
  const before = app.viewing.tracks;
  app.viewing = null;
  flash(diff(before, app.view().tracks));
  renderBanner();
  app.emit("view", { changed: new Set() });
};
app.stepHistory = (d) => {
  const hist = app.state?.history || [];
  if (!hist.length) return;
  let i = app.viewing ? hist.findIndex((x) => x.n === app.viewing.n) : hist.length;
  i = clamp(i + d, 0, hist.length);
  if (i >= hist.length) app.backToNow(); else app.viewHistory(hist[i].n);
};
let replayTimer = 0;
function stopReplay() {
  clearTimeout(replayTimer);
  if (app.replaying) { app.replaying = false; app.emit("replay"); }
}
app.toggleReplay = () => {
  if (app.replaying) return stopReplay();
  const hist = app.state?.history || [];
  if (!hist.length) return;
  app.replaying = true;
  app.emit("replay");
  let i = app.viewing ? hist.findIndex((x) => x.n === app.viewing.n) + 1 : 0;
  if (i >= hist.length) i = 0;
  const tick = async () => {
    if (!app.replaying) return;
    if (i >= hist.length) { app.backToNow(); return; }
    await app.viewHistory(hist[i].n);
    i += 1;
    replayTimer = setTimeout(tick, 900);
  };
  tick();
};

// ---------------------------------------------------------------- top bar
const $ = (id) => document.getElementById(id);
function renderTop() {
  const s = app.state;
  const title = s.project?.title || t("top.untitled");
  $("filmTitle").textContent = title;
  $("filmTitle").title = title;
  $("projName").textContent = s.project?.name || "";
  $("projName").title = s.project?.path || "";
  document.title = `${title} · reelsmith watch`;
  const c = s.canvas || {};
  $("canvasInfo").textContent = c.width ? `${c.profile} · ${c.width}×${c.height} · ${c.fps} fps` : "";
  $("lengthInfo").textContent = s.duration ? timecode(s.duration, app.fps()) : "–";

  const sp = s.spend;
  $("spendBox").hidden = !sp;
  if (sp) {
    $("spendText").textContent = sp.budget_usd ? `$${sp.project_usd.toFixed(2)} ${t("top.of")} $${sp.budget_usd.toFixed(2)}` : `$${sp.project_usd.toFixed(2)}`;
    $("spendBar").style.setProperty("--fill", `${sp.budget_usd ? clamp((sp.project_usd / sp.budget_usd) * 100, 0, 100) : 0}%`);
    $("spendBar").hidden = !sp.budget_usd;
    $("spendBox").classList.toggle("is-over", !!sp.budget_usd && sp.project_usd > sp.budget_usd * 0.9);
  }

  const d = s.render?.delivered, last = s.render?.last;
  const del = $("delivery");
  del.className = "pill";
  if (last && !last.ok && (!d || (last.at > d.at && !d.matches_cut))) {
    del.classList.add("is-error");
    del.textContent = `${t("top.lastFailed")}${last.stage ? ` · ${last.stage}` : ""}`;
    del.title = last.text || "";
  } else if (d) {
    del.classList.add(d.matches_cut ? "is-ok" : "is-warn");
    del.textContent = t(d.matches_cut ? "top.delivered.matches" : "top.delivered.stale");
    del.title = [clock(d.at), d.duration ? `${d.duration.toFixed(2)} s` : null, d.lufs != null ? `${d.lufs} LUFS` : null, bytes(d.bytes)]
      .filter(Boolean).join(" · ");
  } else {
    del.textContent = t("top.notDelivered");
    del.title = "";
  }
  const sw = $("srcDelivered");
  sw.disabled = !d;
  if (!d && app.source === "delivered") setSource("live");
  renderStatus();
}

function renderStatus() {
  const st = $("status");
  const editing = Date.now() < app.editingUntil && app.status === "connected";
  st.dataset.state = editing ? "editing" : app.status;
  $("statusText").textContent = t(editing ? "status.editing" : `status.${app.status}`);
}
setInterval(renderStatus, 1000);

function renderError() {
  const s = app.state;
  const card = $("errorCard");
  card.hidden = s.valid !== false;
  if (s.valid === false) {
    $("errorText").textContent = s.error || "";
    $("errorNote").textContent = app.lastGood ? `${t("tl.lastGood")}. ${t("err.hint")}` : t("err.hint");
  }
}

function renderBanner() {
  const b = $("historyBanner");
  b.hidden = !app.viewing;
  if (app.viewing) {
    $("historyText").textContent = t("tl.viewing", { n: app.viewing.n, at: clock(app.viewing.at) });
    $("historyText").title = app.viewing.summary;
  }
  document.body.classList.toggle("is-history", !!app.viewing);
}
$("backToNow").addEventListener("click", () => app.backToNow());

// ---------------------------------------------------------------- transport
const playBtn = $("playBtn");
function renderTransport() {
  playBtn.setAttribute("aria-pressed", String(app.playing));
  playBtn.title = `${t(app.playing ? "tr.pause" : "tr.play")} (Space)`;
  playBtn.setAttribute("aria-label", t(app.playing ? "tr.pause" : "tr.play"));
  playBtn.classList.toggle("is-playing", app.playing);
}
function renderTime() {
  $("tc").textContent = timecode(app.time, app.fps());
  $("tcFrame").textContent = `${t("tr.frame")} ${app.frame()}`;
  $("tcTotal").textContent = timecode(app.duration(), app.fps());
}
playBtn.addEventListener("click", () => app.toggle());
$("startBtn").addEventListener("click", () => app.seek(0));
$("endBtn").addEventListener("click", () => app.seek(app.lastFrameTime()));
$("backBtn").addEventListener("click", () => app.step(-1));
$("fwdBtn").addEventListener("click", () => app.step(1));

const vol = $("volume");
function renderAudio() {
  vol.value = String(app.muted ? 0 : app.volume);
  vol.style.setProperty("--fill", `${(app.muted ? 0 : app.volume) * 100}%`);
  const mb = $("muteBtn");
  mb.setAttribute("aria-pressed", String(app.muted));
  mb.title = t(app.muted ? "tr.unmute" : "tr.mute");
  mb.setAttribute("aria-label", mb.title);
  mb.classList.toggle("is-muted", app.muted || app.volume === 0);
}
vol.addEventListener("input", () => {
  app.volume = Number(vol.value);
  app.muted = app.volume === 0;
  store("volume", app.volume); store("muted", app.muted);
  renderAudio();
  app.emit("audio");
});
$("muteBtn").addEventListener("click", () => {
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
  app.emit("safe");
}
$("safeBtn").addEventListener("click", () => setSafe(!app.safe));

function setSource(src) {
  app.source = src;
  $("srcLive").setAttribute("aria-pressed", String(src === "live"));
  $("srcDelivered").setAttribute("aria-pressed", String(src === "delivered"));
  app.emit("source");
  renderTime();
}
$("srcLive").addEventListener("click", () => setSource("live"));
$("srcDelivered").addEventListener("click", () => setSource("delivered"));

// ---------------------------------------------------------------- timeline toolbar
const followBtn = $("followBtn");
function setFollow(v) {
  app.follow = v;
  store("follow", v);
  followBtn.setAttribute("aria-pressed", String(v));
}
followBtn.addEventListener("click", () => setFollow(!app.follow));

// ---------------------------------------------------------------- splitter between the monitor row and the timeline
const split = $("split");
function setTimelineHeight(px) {
  const max = window.innerHeight - 260;
  const v = clamp(px, 180, Math.max(180, max));
  document.documentElement.style.setProperty("--tl-h", `${v}px`);
  return v;
}
setTimelineHeight(storage("tlh", Math.round(window.innerHeight * 0.4)));
split.addEventListener("pointerdown", (e) => {
  split.setPointerCapture(e.pointerId);
  const move = (ev) => store("tlh", setTimelineHeight(window.innerHeight - ev.clientY - 3));
  const up = () => { split.removeEventListener("pointermove", move); split.removeEventListener("pointerup", up); };
  split.addEventListener("pointermove", move);
  split.addEventListener("pointerup", up);
});
split.addEventListener("keydown", (e) => {
  const cur = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tl-h")) || 300;
  if (e.key === "ArrowUp" || e.key === "ArrowDown") {
    e.preventDefault();
    e.stopPropagation();
    store("tlh", setTimelineHeight(cur + (e.key === "ArrowUp" ? 24 : -24)));
  }
});
addEventListener("resize", () => setTimelineHeight(parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tl-h")) || 300));

// ---------------------------------------------------------------- help
const help = $("help");
$("helpBtn").addEventListener("click", () => help.showModal());
$("helpClose").addEventListener("click", () => help.close());
help.addEventListener("click", (e) => { if (e.target === help) help.close(); });

// ---------------------------------------------------------------- wiring
const monitor = createMonitor(app);
const timeline = createTimeline(app);
const panel = createPanel(app);
$("zoomIn").addEventListener("click", timeline.zoomIn);
$("zoomOut").addEventListener("click", timeline.zoomOut);
$("zoomFit").addEventListener("click", timeline.fit);

app.on("time", renderTime);
app.on("playing", renderTransport);
app.on("state", renderTime);

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
    if (tag === "BUTTON" && e.target.id !== "playBtn") return;
    e.preventDefault();
    app.toggle();
  } else if ((k === "ArrowLeft" || k === "ArrowRight") && !onRange && !(e.ctrlKey || e.metaKey)) {
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
  else if (k >= "1" && k <= "4") panel.show(Number(k) - 1);
  else if (k === "?") { e.preventDefault(); help.open ? help.close() : help.showModal(); }
  else if (k === "Escape" && app.viewing) app.backToNow();
});

// ---------------------------------------------------------------- start
setFollow(app.follow);
setSafe(app.safe);
setSource("live");
renderAudio();
renderTransport();
subscribe(() => refresh(), (s) => { app.status = s; renderStatus(); });
refresh();
