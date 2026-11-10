import { getResolved, playerStatus } from "./api.js";
import { t } from "./i18n.js";
import { clamp } from "./util.js";

// The monitor shows one of three sources: the live player (iframe), engine stills, or the delivered mp4.
export function createMonitor(app) {
  const screen = document.getElementById("screen");
  const film = document.getElementById("film");
  const frame = document.getElementById("player");
  const still = document.getElementById("still");
  const video = document.getElementById("delivered");
  const safe = document.getElementById("safe");
  const msg = document.getElementById("screenMsg");
  const tag = document.getElementById("sourceTag");
  const staleTag = document.getElementById("staleTag");

  const P = { status: "unknown", ready: false, loaded: false, failed: null, pendingSeek: null, revision: null, poll: 0 };
  let mode = "still";
  let clockRaf = 0;

  // ---------------------------------------------------------------- layout
  function layout() {
    const c = app.state?.canvas;
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
      P.poll = setTimeout(checkPlayer, s.building ? 3000 : 15000);
    }
    choose();
  }

  async function loadResolved() {
    if (!P.ready || !app.state?.valid || !app.state.frames) return;
    try {
      const resolved = await getResolved();
      P.revision = app.state.revision;
      P.pendingSeek = app.frame();
      post({ type: "load", resolved });
    } catch (e) {
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
      P.loaded = true;
      choose();
      if (P.pendingSeek != null) post({ type: "seek", frame: clamp(P.pendingSeek, 0, Math.max(0, m.frames - 1)) });
      P.pendingSeek = null;
      if (app.playing && mode === "player") post({ type: "play" });
    } else if (m.type === "frame" && mode === "player") {
      app.setTime(m.frame / app.fps(), "player");
    } else if (m.type === "playing" && mode === "player") {
      app.setPlaying(!!m.value, "player");
    } else if (m.type === "ended" && mode === "player") {
      app.setPlaying(false, "player");
    } else if (m.type === "error") {
      P.failed = m.message || "error";
      P.loaded = false;
      choose();
    }
  });

  // ---------------------------------------------------------------- stills
  let stillWant = null, stillBusy = false, stillTimer = 0, stillShown = null;
  function requestStill() {
    if (mode !== "still" || !app.state?.frames) return;
    const f = app.frame();
    const tSec = +(f / app.fps()).toFixed(3);
    stillWant = `${app.state.revision}:${f}`;
    clearTimeout(stillTimer);
    stillTimer = setTimeout(() => fetchStill(tSec, stillWant), app.playing ? 0 : 140);
  }
  function fetchStill(tSec, key) {
    if (stillBusy || key === stillShown) return;
    stillBusy = true;
    const w = Math.min(1280, Math.max(320, Math.round(film.clientWidth * devicePixelRatio)));
    const img = new Image();
    img.onload = () => {
      stillBusy = false;
      still.src = img.src;
      still.hidden = mode !== "still";
      stillShown = key;
      setMsg(null);
      if (stillWant !== key) requestStill();
    };
    img.onerror = () => {
      stillBusy = false;
      if (!still.getAttribute("src")) setMsg(t("mon.noStill"), "", true);
      if (stillWant !== key) requestStill();
    };
    img.src = `/api/still?t=${tSec}&w=${w}`;
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
  video.addEventListener("play", () => { app.setPlaying(true, "video"); videoLoop(); });
  video.addEventListener("pause", () => app.setPlaying(false, "video"));
  video.addEventListener("ended", () => app.setPlaying(false, "video"));

  // ---------------------------------------------------------------- choosing the source
  function setMsg(title, sub = "", small = false) {
    msg.hidden = !title;
    msg.classList.toggle("small", small);
    msg.replaceChildren();
    if (!title) return;
    const a = document.createElement("strong");
    a.textContent = title;
    msg.append(a);
    if (sub) {
      const b = document.createElement("span");
      b.textContent = sub;
      msg.append(b);
    }
  }

  function choose() {
    const st = app.state;
    const prev = mode;
    const empty = !st || !st.frames;
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
    still.hidden = mode !== "still" || !still.getAttribute("src");
    staleTag.hidden = !(mode === "delivered" && st?.render?.delivered && !st.render.delivered.matches_cut);

    if (mode === "delivered") {
      const url = deliveredUrl();
      if (video.dataset.src !== url) {
        video.dataset.src = url;
        video.src = url;
      }
      video.currentTime = app.time;
      tag.textContent = t("mon.delivered");
      setMsg(null);
    } else if (mode === "player") {
      tag.textContent = t("mon.live");
      setMsg(null);
      if (prev !== "player") post({ type: "seek", frame: app.frame() });
    } else {
      tag.textContent = t("mon.engine");
      if (empty) {
        still.hidden = true;
        still.removeAttribute("src");
        stillShown = null;
        if (st?.valid === false) setMsg(t("err.title"), t("err.hint"));
        else setMsg(t("mon.nothing"), t("mon.nothingHint"));
      } else {
        if (P.status === "building" && !still.getAttribute("src")) setMsg(t("mon.building"), "", true);
        else if (P.failed && !still.getAttribute("src")) setMsg(t("mon.playerFailed"), P.failed, true);
        else if (!still.getAttribute("src")) setMsg(t("mon.loading"), "", true);
        requestStill();
      }
    }
    tag.title = P.failed ? `${t("mon.playerFailed")}: ${P.failed}` : (P.status === "building" ? t("mon.building") : "");
    applyAudio();
  }

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
  });
  app.on("playing", (origin) => {
    if (origin === "player" || origin === "video" || origin === "clock" || origin === "monitor") return;
    if (mode === "player") post({ type: app.playing ? "play" : "pause" });
    else if (mode === "delivered") app.playing ? video.play().catch(() => app.setPlaying(false, "video")) : video.pause();
    else app.playing ? startClock() : stopClock();
  });
  app.on("state", ({ revisionChanged }) => {
    layout();
    if (revisionChanged && P.ready && P.revision !== app.state.revision) loadResolved();
    if (revisionChanged) stillShown = null;
    choose();
  });
  app.on("source", choose);
  app.on("audio", applyAudio);
  app.on("safe", () => { safe.hidden = !app.safe; });
  safe.hidden = !app.safe;

  checkPlayer();
  return { layout, mode: () => mode };
}
