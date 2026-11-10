import { getResolved, getStill, playerStatus } from "./api.js";
import { t } from "./i18n.js";
import { clamp, clock, h, tip } from "./util.js";

const LOAD_TIMEOUT_MS = 20000;
const WAIT_MS = 250;

// The monitor shows one of three sources: the live player (iframe), engine stills, or the delivered mp4.
export function createMonitor(app) {
  const $ = (id) => document.getElementById(id);
  const screen = $("screen"), film = $("film"), frame = $("player"), still = $("still"), video = $("delivered");
  const safe = $("safe"), msg = $("screenMsg"), tag = $("sourceTag"), chip = $("monChip"), bar = $("monBar");
  const selBox = $("selBox"), selTag = $("selTag"), pop = $("popGlyph"), justChanged = $("justChanged");
  const scrim = $("histScrim");

  const P = { status: "unknown", ready: false, loaded: false, failed: null, warn: null, pendingSeek: null, cutKey: null,
    poll: 0, loadTimer: 0 };
  let mode = "still";
  let clockRaf = 0;

  // ---------------------------------------------------------------- layout
  function layout() {
    const c = app.cut()?.canvas || app.state?.canvas;
    if (!c) return;
    const box = screen.getBoundingClientRect();
    const pad = 16;
    const aw = Math.max(1, box.width - pad * 2), ah = Math.max(1, box.height - pad * 2);
    const s = Math.min(aw / c.width, ah / c.height);
    const w = Math.round(c.width * s), hgt = Math.round(c.height * s);
    Object.assign(film.style, { width: `${w}px`, height: `${hgt}px`, left: `${Math.round((box.width - w) / 2)}px`,
      top: `${Math.round((box.height - hgt) / 2)}px` });
    const sa = c.safe;
    if (sa) Object.assign(safe.style, { left: `${(sa.x / c.width) * 100}%`, top: `${(sa.y / c.height) * 100}%`,
      width: `${(sa.w / c.width) * 100}%`, height: `${(sa.h / c.height) * 100}%` });
  }
  new ResizeObserver(layout).observe(screen);

  // The part of a state that changes the picture; activity, issues or spend alone never reload the player.
  function cutKey(s) {
    if (!s?.frames) return null;
    return JSON.stringify([s.tracks, s.voice, s.duration, s.canvas, s.markers, s.chapters,
      (s.assets || []).map((a) => [a.id, a.path, a.width, a.height, a.duration, a.missing])]);
  }

  // ---------------------------------------------------------------- player
  function post(m) {
    if (P.ready) frame.contentWindow?.postMessage(m, location.origin);
  }

  async function checkPlayer() {
    clearTimeout(P.poll);
    const s = await playerStatus();
    if (s.ok) {
      if (P.status !== "ok") {
        P.status = "ok";
        P.failed = null;
        frame.src = "/player/index.html";
      }
    } else {
      P.status = s.building ? "building" : "down";
      if (!s.building) P.failed = s.error;
      P.poll = setTimeout(checkPlayer, s.building ? 2000 : 15000);
    }
    choose();
  }

  async function loadResolved() {
    const key = cutKey(app.state);
    if (!P.ready || !app.state?.valid || !key || key === P.cutKey) return;
    try {
      const resolved = await getResolved();
      P.cutKey = key;
      P.pendingSeek = app.frame();
      post({ type: "load", resolved });
      clearTimeout(P.loadTimer);
      if (!P.loaded) P.loadTimer = setTimeout(() => { P.failed = t("mon.noLoad"); choose(); }, LOAD_TIMEOUT_MS);
    } catch {
      // The cut does not resolve right now: keep the last loaded film on screen.
    }
  }

  addEventListener("message", (e) => {
    if (e.source !== frame.contentWindow) return;
    const m = e.data || {};
    if (m.type === "ready") {
      P.ready = true;
      loadResolved();
      post({ type: "volume", value: app.volume });
      post({ type: "muted", value: app.muted });
    } else if (m.type === "loaded") {
      clearTimeout(P.loadTimer);
      P.loaded = true;
      P.failed = null;
      choose();
      if (P.pendingSeek != null) post({ type: "seek", frame: clamp(P.pendingSeek, 0, Math.max(0, m.frames - 1)) });
      P.pendingSeek = null;
      if (app.playing && mode === "player") post({ type: "play" });
    } else if (m.type === "frame" && mode === "player") {
      gotFrame();
      app.setTime(m.frame / app.fps(), "player");
    } else if (m.type === "playing" && mode === "player") {
      app.setPlaying(!!m.value, "player");
    } else if (m.type === "ended" && mode === "player") {
      app.setPlaying(false, "player");
    } else if (m.type === "error") {
      const text = String(m.message || "error");
      if (/ResizeObserver loop/.test(text)) return;          // a browser notice, not a failure
      P.warn = text;                                          // a graphic failed: say so, keep playing the rest
      renderTag();
    }
  });

  // ---------------------------------------------------------------- waiting for frames after play
  let waitTimer = 0;
  function armWait() {
    clearTimeout(waitTimer);
    if (!app.playing || mode === "still") return;
    waitTimer = setTimeout(() => { if (app.playing) app.setWaiting(true); }, WAIT_MS);
  }
  function gotFrame() {
    app.setWaiting(false);
    if (app.playing) armWait();
  }

  // ---------------------------------------------------------------- stills
  let stillWant = null, stillBusy = false, stillTimer = 0, stillShown = null, stillError = null;
  function requestStill() {
    const s = app.state;
    if (mode !== "still" || !s?.valid || !s.frames) return;
    const f = app.frame();
    stillWant = `${P.cutKey ?? s.revision}:${f}`;
    clearTimeout(stillTimer);
    stillTimer = setTimeout(() => fetchStill(+(f / app.fps()).toFixed(3), stillWant), app.playing ? 0 : 140);
  }
  async function fetchStill(tSec, key) {
    if (stillBusy || key === stillShown) return;
    stillBusy = true;
    const slow = setTimeout(() => { if (stillBusy) bar.hidden = false; }, 150);
    const w = Math.min(1280, Math.max(320, Math.round(film.clientWidth * devicePixelRatio)));
    const got = await getStill(tSec, w, app.state?.revision);
    clearTimeout(slow);
    stillBusy = false;
    bar.hidden = !(P.status === "building" && mode === "still");
    if (got.url) {
      const old = still.src;
      still.src = got.url;
      if (old.startsWith("blob:")) URL.revokeObjectURL(old);
      stillShown = key;
      stillError = null;
    } else {
      stillError = got.busy ? t("mon.stillBusy") : got.error;
      if (got.busy) setTimeout(requestStill, 3000);
    }
    choose();
    if (stillWant !== key) requestStill();
  }

  // ---------------------------------------------------------------- delivered
  function deliveredUrl() {
    return app.state?.render?.delivered?.url || null;
  }
  let videoRaf = 0;
  function videoLoop() {
    cancelAnimationFrame(videoRaf);
    const step = () => {
      if (mode !== "delivered") return;
      app.setTime(video.currentTime, "video");
      if (!video.paused) videoRaf = requestAnimationFrame(step);
    };
    videoRaf = requestAnimationFrame(step);
  }
  const setSourceBusy = (v) => { if (app.sourceBusy !== v) { app.sourceBusy = v; app.emit("source-busy"); } };
  video.addEventListener("play", () => { app.setPlaying(true, "video"); armWait(); videoLoop(); });
  video.addEventListener("playing", gotFrame);
  video.addEventListener("timeupdate", () => { if (!video.paused) gotFrame(); });
  video.addEventListener("waiting", () => app.setWaiting(true));
  video.addEventListener("pause", () => app.setPlaying(false, "video"));
  video.addEventListener("ended", () => app.setPlaying(false, "video"));
  video.addEventListener("loadeddata", () => setSourceBusy(false));
  video.addEventListener("error", () => setSourceBusy(false));

  // ---------------------------------------------------------------- what is on screen
  function setMsg(title, sub = "", small = false, extra = null) {
    msg.hidden = !title;
    msg.classList.toggle("small", small);
    msg.replaceChildren();
    if (!title) return;
    msg.append(h("strong", { text: title }));
    if (sub) msg.append(h("span", { text: sub }));
    if (extra) msg.append(h("span", { class: "facts", text: extra }));
  }

  function renderTag() {
    tag.hidden = true;
    if (mode === "still" && !still.hidden) {
      tag.hidden = false;
      tag.textContent = t("mon.engine");
      tip(tag, P.failed ? `${t("mon.playerFailed")}: ${P.failed}` : t("mon.engineTip"));
    } else if (mode === "delivered" && app.state?.render?.delivered && !app.state.render.delivered.matches_cut) {
      tag.hidden = false;
      tag.textContent = t("mon.staleDelivered");
      tip(tag, "");
    }
    tag.classList.toggle("is-warn", mode === "delivered");
    // one chip at the top left: paused (the project does not load) outranks a graphic's problem
    chip.hidden = true;
    chip.className = "mon-chip";
    if (app.broken() && !app.viewing) {
      chip.hidden = false;
      chip.classList.add("is-error");
      chip.textContent = t("mon.paused");
      tip(chip, t("mon.pausedTip"));
    } else if (P.warn && mode === "player") {
      chip.hidden = false;
      chip.classList.add("is-warn");
      chip.textContent = t("mon.componentWarn");
      tip(chip, P.warn);
    }
  }

  function choose() {
    const st = app.state;
    const cut = app.cut();
    const prev = mode;
    const hasFilm = !!cut?.frames;
    if (app.source === "delivered" && deliveredUrl()) mode = "delivered";
    else if (P.status === "ok" && P.loaded && !P.failed) mode = "player";
    else mode = "still";

    if (prev !== mode) {
      if (prev === "player") post({ type: "pause" });
      if (prev === "delivered") video.pause();
      stopClock();
      if (app.playing) app.setPlaying(false, "monitor");
    }
    frame.hidden = mode !== "player";
    video.hidden = mode !== "delivered";
    still.hidden = mode !== "still" || !still.getAttribute("src") || !hasFilm;
    film.classList.toggle("is-dim", app.dimmed() && mode !== "delivered");
    film.classList.toggle("is-playable", hasFilm || mode === "delivered");
    tip(film, hasFilm || mode === "delivered" ? t("mon.clickTip") : "");
    if (mode !== "delivered") setSourceBusy(false);

    if (mode === "delivered") {
      const url = deliveredUrl();
      if (video.dataset.src !== url) {
        video.dataset.src = url;
        video.src = url;
      }
      if (video.readyState < 2) setSourceBusy(true);
      if (Math.abs(video.currentTime - app.time) > 0.02) video.currentTime = app.time;
      setMsg(null);
      bar.hidden = true;
    } else if (!hasFilm) {
      still.removeAttribute("src");
      stillShown = null;
      bar.hidden = true;
      const c = st?.canvas;
      const facts = c ? `${t(`top.orient.${c.width > c.height ? "landscape" : c.width < c.height ? "vertical" : "square"}`)} · ${c.width}×${c.height} · ${t("top.fps", { n: c.fps })}` : null;
      if (app.empty()) setMsg(t("mon.waiting"), t("mon.waitingSub"), false, facts);
      else setMsg(null);                      // a project that does not load says so once, in the chip
    } else if (mode === "player") {
      setMsg(null);
      bar.hidden = true;
      if (prev !== "player") post({ type: "seek", frame: app.frame() });
    } else {
      const showing = !still.hidden;
      bar.hidden = !(P.status === "building" || P.status === "unknown" || stillBusy);
      if (showing) setMsg(null);
      else if (P.status === "building" || P.status === "unknown" || (P.status === "ok" && !P.loaded && !P.failed)) setMsg(t("mon.preparing"), t("mon.preparingSub"), true);
      else if (stillError) setMsg(stillError === t("mon.stillBusy") ? stillError : t("mon.noStill"), stillError === t("mon.stillBusy") ? "" : stillError, true);
      else setMsg(t("mon.loading"), "", true);
      requestStill();
    }
    renderTag();
    renderSelection();
    renderHistory();
    applyAudio();
  }

  // ---------------------------------------------------------------- the selected clip's box over the picture
  function renderSelection() {
    const c = app.viewing || !app.selected ? null : app.clipById(app.selected, app.cut()?.tracks);
    const cv = app.cut()?.canvas;
    const box = c?.box;
    if (!c || !cv || !box || box === "full" || typeof box !== "object" || mode === "delivered") { selBox.hidden = true; return; }
    selBox.hidden = false;
    Object.assign(selBox.style, { left: `${(box.x / cv.width) * 100}%`, top: `${(box.y / cv.height) * 100}%`,
      width: `${(box.w / cv.width) * 100}%`, height: `${(box.h / cv.height) * 100}%` });
    selTag.textContent = c.id;
    const inside = c.start != null && app.time >= c.start - 1e-6 && app.time < c.end;
    selBox.classList.toggle("is-out", !inside);
    selBox.classList.toggle("is-top", box.y < cv.height * 0.04);
  }

  // ---------------------------------------------------------------- history: the picture is always the current cut
  function renderHistory() {
    const v = app.viewing;
    scrim.hidden = !v;
    film.classList.toggle("is-history", !!v);
    if (v) {
      $("histTitle").textContent = t("mon.histTitle");
      $("histSub").textContent = t("mon.histSub", { n: v.n, at: clock(v.at) });
    }
  }

  // ---------------------------------------------------------------- what the agent just changed
  const TYPE = { text: "text", component: "component", image: "image", video: "video", evidence: "evidence", shape: "shape", audio: "audio" };
  let justTimer = 0;
  function sayChanged(ids) {
    const list = [...ids];
    const c = app.clipById(list[0]);
    if (!c) return;
    const one = `${t(`type.${TYPE[c.type] || "shape"}`)} ${c.id}`;
    justChanged.textContent = t("mon.justChanged", { what: list.length > 1 ? t("mon.andMore", { what: one, n: list.length - 1 }) : one });
    justChanged.hidden = false;
    clearTimeout(justTimer);
    justTimer = setTimeout(() => { justChanged.hidden = true; }, 3000);
  }

  // ---------------------------------------------------------------- clicking the picture plays or pauses
  function popGlyph() {
    pop.querySelector("use").setAttribute("href", app.playing ? "#i-play" : "#i-pause");
    pop.classList.remove("is-pop");
    void pop.offsetWidth;
    pop.classList.add("is-pop");
  }
  film.addEventListener("click", () => {
    if (!film.classList.contains("is-playable") || !app.duration()) return;
    app.toggle();
    popGlyph();
  });

  // ---------------------------------------------------------------- still-mode clock
  function stopClock() {
    cancelAnimationFrame(clockRaf);
    clockRaf = 0;
  }
  function startClock() {
    stopClock();
    let last = performance.now();
    const step = (now) => {
      const nt = app.time + (now - last) / 1000;
      last = now;
      if (nt >= app.duration()) {
        app.setTime(app.duration(), "clock");
        app.setPlaying(false, "clock");
        return;
      }
      app.setTime(nt, "clock");
      clockRaf = requestAnimationFrame(step);
    };
    clockRaf = requestAnimationFrame(step);
  }

  function applyAudio() {
    video.volume = app.volume;
    video.muted = app.muted;
    post({ type: "volume", value: app.volume });
    post({ type: "muted", value: app.muted });
  }

  // ---------------------------------------------------------------- app hooks
  app.on("time", (origin) => {
    if (mode === "player" && origin !== "player") post({ type: "seek", frame: app.frame() });
    else if (mode === "delivered" && origin !== "video" && Math.abs(video.currentTime - app.time) > 0.02) video.currentTime = app.time;
    else if (mode === "still") requestStill();
    if (!selBox.hidden || app.selected) renderSelection();
  });
  app.on("playing", (origin) => {
    if (app.playing) armWait(); else clearTimeout(waitTimer);
    if (origin === "player" || origin === "video" || origin === "clock" || origin === "monitor") return;
    if (mode === "player") post({ type: app.playing ? "play" : "pause" });
    else if (mode === "delivered") app.playing ? video.play().catch(() => app.setPlaying(false, "video")) : video.pause();
    else app.playing ? startClock() : stopClock();
  });
  app.on("state", () => {
    layout();
    const key = cutKey(app.state);
    if (key && key !== P.cutKey) {
      stillShown = null;
      stillError = null;
      if (P.ready) loadResolved();
    }
    choose();
  });
  app.on("view", ({ changed, live } = {}) => {
    choose();
    if (live && changed?.size && !app.viewing) sayChanged(changed);
  });
  app.on("select", renderSelection);
  app.on("source", choose);
  app.on("audio", applyAudio);
  app.on("safe", () => { safe.hidden = !app.safe; });
  safe.hidden = !app.safe;

  checkPlayer();
  choose();
  return { layout, mode: () => mode, pop: popGlyph };
}
