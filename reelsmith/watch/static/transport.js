import { beatAt } from "./beats.js";
import { t } from "./i18n.js";
import { busy, clamp, disable, h, isOff, pressable, storage, store, timecode, tip } from "./util.js";

// The transport inside the stage: play, beats and frames, the time, the beat-segmented bar, sound, safe area, source.
export function createTransport(app) {
  const $ = (id) => document.getElementById(id);
  const playBtn = $("playBtn"), bar = $("bar"), segs = $("barSegs"), marks = $("barMarks"), knob = $("knob"), hover = $("barHover");

  // ---------------------------------------------------------------- buttons and time
  function renderPlay() {
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
    const none = !(app.beats || []).length;
    disable($("prevBeat"), none ? t("tr.noBeats") : atStart ? t("tr.atStart") : null, t("tr.prevBeat"), "PgUp");
    disable($("nextBeat"), none ? t("tr.noBeats") : atEnd || beatAt(app.beats, app.time) === app.beats.at(-1) ? t("tr.lastBeat") : null, t("tr.nextBeat"), "PgDn");
    disable($("backBtn"), atStart ? t("tr.atStart") : null, t("tr.back"), "←");
    disable($("fwdBtn"), atEnd ? t("tr.atEnd") : null, t("tr.fwd"), "→");
  }
  function renderTime() {
    $("tc").textContent = timecode(app.time, app.fps());
    $("tcFrame").textContent = t("tr.frameN", { n: app.frame() });
    $("tcTotal").textContent = timecode(app.duration(), app.fps());
    bar.setAttribute("aria-valuemax", String(+app.duration().toFixed(2)));
    bar.setAttribute("aria-valuenow", String(+app.time.toFixed(2)));
    bar.setAttribute("aria-valuetext", `${timecode(app.time, app.fps())} / ${timecode(app.duration(), app.fps())}`);
    renderFill();
    renderEnds();
  }
  pressable(playBtn, () => app.toggle());
  pressable($("prevBeat"), () => app.stepBeat(-1));
  pressable($("nextBeat"), () => app.stepBeat(1));
  pressable($("backBtn"), () => app.step(-1));
  pressable($("fwdBtn"), () => app.step(1));

  // ---------------------------------------------------------------- the bar, one segment per beat
  let segKey = "";
  function renderSegs() {
    const beats = app.beats || [];
    const dur = app.duration() || 0;
    const k = JSON.stringify([beats.map((b) => [b.start, b.end]), dur, app.beat]);
    if (k !== segKey) {
      segKey = k;
      segs.replaceChildren(...(beats.length && dur
        ? beats.map((b) => h("div", { class: `bseg${app.beat === b.i ? " is-sel" : ""}`, style: { flex: `${Math.max(0.01, b.end - b.start)} 1 0` }, "data-s": b.start, "data-e": b.end }, h("i")))
        : [h("div", { class: "bseg", style: { flex: "1 1 0" }, "data-s": 0, "data-e": dur || 1 }, h("i"))]));
    }
    renderMarks();
    renderFill();
  }
  function renderFill() {
    const dur = app.duration();
    for (const s of segs.children) {
      const a = Number(s.dataset.s), b = Number(s.dataset.e);
      s.style.setProperty("--f", `${clamp((app.time - a) / (b - a || 1), 0, 1) * 100}%`);
    }
    knob.hidden = !dur;
    knob.style.left = `${dur ? clamp(app.time / dur, 0, 1) * 100 : 0}%`;
  }
  function renderMarks() {
    const dur = app.duration();
    const out = [];
    if (dur && !app.viewing) {
      const seen = new Set();
      for (const id of app.latest) {
        const c = app.clipById(id, app.cut()?.tracks);
        if (c?.start == null || seen.has(c.start.toFixed(1))) continue;
        seen.add(c.start.toFixed(1));
        out.push([c.start, "is-changed", t("tr.markChanged", { what: c.id, t: timecode(c.start, app.fps()) })]);
      }
      for (const is of app.state?.issues || []) {
        const at = is.t ?? app.clipById(is.clip)?.start;
        if (at != null) out.push([at, "is-bad", is.text]);
      }
      const r = app.result();
      if (r.state === "refused" && r.t != null) out.push([r.t, "is-bad", `${r.reason} · ${timecode(r.t, app.fps())}`]);
    }
    marks.replaceChildren(...out.map(([at, cls, text]) => {
      const m = h("span", { class: `mk ${cls}`, style: { left: `${clamp(at / dur, 0, 1) * 100}%` } });
      tip(m, text);
      return m;
    }));
  }

  const timeAt = (x) => {
    const r = segs.getBoundingClientRect();
    return clamp((x - r.left) / r.width, 0, 1) * app.duration();
  };
  bar.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !app.duration()) return;
    bar.setPointerCapture(e.pointerId);
    bar.classList.add("is-scrubbing");
    const was = app.playing;
    if (was) app.setPlaying(false);
    app.seek(timeAt(e.clientX), "scrub");
    const move = (ev) => { app.seek(timeAt(ev.clientX), "scrub"); showHover(ev.clientX); };
    const up = () => {
      bar.classList.remove("is-scrubbing");
      bar.removeEventListener("pointermove", move);
      bar.removeEventListener("pointerup", up);
      bar.removeEventListener("pointercancel", up);
      app.seek(app.time);
      if (was) app.setPlaying(true);
    };
    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", up);
    bar.addEventListener("pointercancel", up);
  });
  function showHover(x) {
    if (!app.duration()) return;
    const r = segs.getBoundingClientRect();
    const sec = timeAt(x);
    const b = beatAt(app.beats || [], sec);
    hover.hidden = false;
    hover.textContent = b ? `${timecode(sec, app.fps())} · ${t("beats.n", { n: b.i })}` : timecode(sec, app.fps());
    hover.style.left = `${clamp(x - r.left, 0, r.width)}px`;
  }
  bar.addEventListener("pointermove", (e) => { if (!e.target.closest(".mk")) showHover(e.clientX); else hover.hidden = true; });
  bar.addEventListener("pointerleave", () => { if (!bar.classList.contains("is-scrubbing")) hover.hidden = true; });
  tip(bar, t("tr.barTip"), "← →", t("tr.bar"));

  // ---------------------------------------------------------------- sound
  const vol = $("volume"), volVal = $("volVal");
  let volHide = 0;
  function renderAudio() {
    const v = app.muted ? 0 : app.volume;
    vol.value = String(v);
    vol.style.setProperty("--fill", `${v * 100}%`);
    vol.setAttribute("aria-valuetext", t("tr.volumeValue", { v: Math.round(v * 100) }));
    tip(vol, t("tr.volumeValue", { v: Math.round(v * 100) }), null, t("tr.volume"));
    const mb = $("muteBtn");
    mb.setAttribute("aria-pressed", String(app.muted));
    tip(mb, t(app.muted ? "tr.unmute" : "tr.mute"), "M");
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
  app.toggleMute = () => {
    app.muted = !app.muted;
    if (!app.muted && app.volume === 0) app.volume = 1;
    store("muted", app.muted);
    renderAudio();
    app.emit("audio");
  };
  pressable($("muteBtn"), app.toggleMute);

  // ---------------------------------------------------------------- safe area
  app.setSafe = (v) => {
    app.safe = v;
    store("safe", v);
    $("safeBtn").setAttribute("aria-pressed", String(v));
    tip($("safeBtn"), t(v ? "tr.safeOn" : "tr.safeOff"), "S", t("tr.safe"));
    app.emit("safe");
  };
  pressable($("safeBtn"), () => app.setSafe(!app.safe));

  // ---------------------------------------------------------------- current cut or delivered film
  function setSource(src) {
    app.source = src;
    $("srcLive").setAttribute("aria-pressed", String(src === "live"));
    $("srcDelivered").setAttribute("aria-pressed", String(src === "delivered"));
    app.emit("source");
    renderTime();
    renderPlay();
  }
  app.setSource = setSource;
  tip($("srcLive"), t("tr.liveTip"));
  pressable($("srcLive"), () => setSource("live"));
  pressable($("srcDelivered"), () => setSource("delivered"));
  function renderSource() {
    const d = app.state?.render?.delivered;
    const sw = $("srcDelivered");
    sw.classList.toggle("is-stale", !!d && !d.matches_cut);
    if (!app.sourceBusy) disable(sw, d ? null : t("tr.noDelivered"), d && !d.matches_cut ? t("tr.deliveredStaleTip") : t("tr.deliveredTip"));
    if (!d && app.source === "delivered") setSource("live");
  }
  app.on("source-busy", () => {
    busy($("srcDelivered"), app.sourceBusy);
    if (app.sourceBusy) tip($("srcDelivered"), t("tr.deliveredLoading"));
    else if (!isOff($("srcDelivered"))) renderSource();
  });

  // A change landed while the film played: offer to go there instead of pulling the playhead away.
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

  app.on("time", renderTime);
  app.on("playing", renderPlay);
  app.on("waiting", renderPlay);
  app.on("state", () => { renderSource(); renderSegs(); renderTime(); renderPlay(); });
  app.on("view", renderSegs);
  app.on("beat", renderSegs);
  app.on("select", renderMarks);
  app.on("conn", renderPlay);

  app.setSafe(storage("safe", false));
  setSource("live");
  renderAudio();
  renderPlay();
  renderTime();
  return { renderPlay, renderTime, renderSegs };
}
