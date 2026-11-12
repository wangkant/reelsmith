import { t } from "./i18n.js";
import { h, icon, pressable, shortTime, timecode, tip } from "./util.js";

// ---------------------------------------------------------------- beats from the state
const overlap = (c, s, e) => Math.min(c.end, e) - Math.max(c.start, s);
const timed = (c) => c.start != null && c.end != null && c.end > c.start;
const isShot = (c) => (c.type === "video" || c.type === "image") && c.box === "full";

function clipsOf(s) {
  const out = [];
  for (const tr of s.tracks || []) {
    if (tr.hidden) continue;
    for (const c of tr.clips || []) if (timed(c)) out.push({ ...c, track: tr.id, trackKind: tr.kind });
  }
  return out;
}
function captionsOf(s) {
  return (s.tracks || []).filter((tr) => tr.kind === "captions" && !tr.hidden).flatMap((tr) => tr.items || []);
}

function fill(b, clips, caps) {
  const need = Math.min(0.6, (b.end - b.start) / 3);
  const inside = (c) => overlap(c, b.start, b.end) > need;
  b.shots = clips.filter((c) => isShot(c) && inside(c)).sort((x, y) => x.start - y.start);
  b.elements = clips.filter((c) => c.trackKind !== "audio" && !isShot(c) && inside(c)).sort((x, y) => x.start - y.start);
  b.sounds = clips.filter((c) => c.trackKind === "audio" && inside(c));
  b.captions = caps.filter((c) => (b.line != null && c.line === (b.lineI ?? b.i)) || (c.line == null && overlap(c, b.start, b.end) > 0.05));
  return b;
}

// One beat per narration line; without narration one per shot, then one per caption group.
function deriveBeats(s) {
  if (!s || s.valid === false && !s.tracks?.length) return [];
  const dur = s.duration || 0;
  const clips = clipsOf(s), caps = captionsOf(s);
  const lines = s.voice?.lines || [];
  if (lines.length) {
    return lines.map((ln, k) => fill({
      i: k + 1, kind: "line", text: ln.text, line: [ln.start, ln.end],
      start: k === 0 ? 0 : ln.start, end: k + 1 < lines.length ? lines[k + 1].start : Math.max(dur, ln.end),
    }, clips, caps));
  }
  const shots = clips.filter(isShot).sort((x, y) => x.start - y.start);
  if (shots.length) {
    return shots.map((c, k) => fill({
      i: k + 1, kind: "shot", text: caps.filter((it) => overlap(it, c.start, c.end) > 0.05).map((it) => it.text).join(" "),
      line: null, start: k === 0 ? 0 : c.start, end: k + 1 < shots.length ? shots[k + 1].start : Math.max(dur, c.end),
    }, clips, caps));
  }
  if (caps.length) {
    return caps.map((it, k) => fill({ i: k + 1, kind: "caption", text: it.text, line: null, start: it.start, end: it.end },
      clips, caps));
  }
  return [];
}

// The server's beats decide the windows and their numbers (its activity rows and results name beats by number);
// an earlier cut shown from the history carries none, so its beats are worked out here.
export function beatsOf(s) {
  const own = s?.beats;
  if (!own?.length) return deriveBeats(s);
  const clips = clipsOf(s), caps = captionsOf(s);
  const lines = new Map((s.voice?.lines || []).map((ln) => [ln.i, ln]));
  return own.map((w) => {
    const ln = w.line_i != null ? lines.get(w.line_i) : null;
    return fill({
      i: w.n, kind: w.kind === "phrase" ? "caption" : w.kind, lineI: w.line_i, start: w.start, end: w.end,
      text: w.line ?? (w.phrases || []).map((p) => p.text).join(" "),
      line: w.kind === "line" ? [ln ? ln.start : w.start, ln ? ln.end : w.end] : null,
    }, clips, caps);
  });
}

export const beatAt = (beats, sec) => beats.find((b) => sec >= b.start - 1e-6 && sec < b.end) || beats.at(-1) || null;

// ---------------------------------------------------------------- what an element is, in plain words
const COMPONENT = [
  [/evidence|quote|source/i, "evidence", "i-quote"], [/story|step|list|beats/i, "steps", "i-steps"],
  [/count|number|figure|stat/i, "figure", "i-hash"], [/chart|graph|bar/i, "chart", "i-rows"], [/map/i, "map", "i-globe"],
];
function elementKind(c) {
  if (isShot(c)) return c.type === "video" ? ["shot", "i-film"] : ["still", "i-pic"];
  if (c.trackKind === "audio" || c.type === "audio") return [c.loop || c.end - c.start > 10 ? "bed" : "effect", "i-audio"];
  if (c.type === "text") return [c.start < 0.5 ? "title" : "text", "i-type"];
  if (c.type === "evidence") return ["evidence", "i-quote"];
  if (c.type === "shape") return ["plate", "i-square"];
  if (c.type === "image" || c.type === "video") return ["picture", "i-pic"];
  for (const [re, k, ic] of COMPONENT) if (re.test(c.label || "")) return [k, ic];
  return ["card", "i-shapes"];
}
export const kindName = (c) => t(`el.${elementKind(c)[0]}`);
// The words an element shows, without the markup that styles them.
const plain = (s) => String(s).replace(/\*\*|__|`/g, "");
function words(c) {
  return plain(rawWords(c));
}
function rawWords(c) {
  const p = c.raw?.props || {};
  if (c.type === "text") return c.raw?.text || c.label || "";
  if (p.value != null) return `${p.value}${p.suffix || ""}${p.label ? ` · ${p.label}` : ""}`;
  if (p.source) return p.source;
  if (Array.isArray(p.beats)) return p.beats.map((x) => x.title || x.text || x).filter((x) => typeof x === "string").join(" · ");
  if (c.asset) return c.asset;
  return "";
}

// An issue in the person's language when the server gave its code; the engine's own words otherwise.
function issueText(is) {
  if (!is.code || t(is.code) === is.code) return is.text;
  const p = { ...(is.params || {}) };
  if (p.side && t(`side.${p.side}`) !== `side.${p.side}`) p.side = t(`side.${p.side}`);
  return t(is.code, p);
}

// ---------------------------------------------------------------- the beats region
export function createBeats(app) {
  const $ = (id) => document.getElementById(id);
  const row = $("beatRow"), sum = $("beatsSum"), health = $("health");
  let beats = [], key = "";
  const frameApi = true;      // the server always cuts beat frames; an empty film has no beats to ask for
  const frameUrl = (sec) => `/api/frame?t=${sec.toFixed(2)}&w=320&cut=${encodeURIComponent(app.cut()?.revision || "")}`;
  function pic(c, b) {
    const mid = (Math.max(c.start, b ? b.start : c.start) + Math.min(c.end, b ? b.end : c.end)) / 2;
    const thumb = c.asset ? `/api/thumb?asset=${encodeURIComponent(c.asset)}&h=180` : null;
    const src = frameApi ? frameUrl(mid) : thumb;
    // a frame the engine has not rendered yet answers 202: the asset's own picture stands in until "frames" says
    // the real one is ready
    const swap = (e) => {
      if (e.target.src.indexOf("/api/frame") >= 0) e.target.dataset.want = src;
      if (thumb && e.target.src.indexOf("/api/thumb") < 0) e.target.src = thumb;
      else if (!e.target.dataset.want) e.target.replaceWith(h("span", { class: "no-pic" }));
    };
    return src ? h("img", { src, alt: "", loading: "lazy", draggable: "false", onerror: swap }) : h("span", { class: "no-pic" });
  }
  let drawn = 0;
  function framesReady() {
    drawn += 1;
    for (const img of row.querySelectorAll("img[data-want]")) {
      const want = img.dataset.want;
      delete img.dataset.want;
      img.src = `${want}&r=${drawn}`;
    }
  }

  const tall = () => document.body.classList.contains("is-tall");
  const fps = () => app.fps();
  const issuesIn = (b) => (app.state?.issues || []).filter((is) => {
    const at = is.t ?? app.clipById(is.clip)?.start;
    return at != null && at >= b.start - 1e-6 && at < b.end;
  });
  const refusedIn = (b) => {
    const r = app.result();
    return r.state === "refused" && r.t != null && r.t >= b.start && r.t < b.end ? r : null;
  };
  const changedIn = (b) => [...b.shots, ...b.elements, ...b.sounds].some((c) => app.latest.has(c.id));
  const len = (b) => t("beats.len", { n: (b.end - b.start).toFixed(1) });

  function card(b) {
    const sel = app.beat === b.i;
    const bad = issuesIn(b), refused = refusedIn(b);
    const problem = refused ? refused.reason : bad[0] ? issueText(bad[0]) : null;
    const el = h("div", {
      class: `beat${sel ? " is-sel is-open" : ""}${problem ? " is-bad" : ""}`, role: "option", "aria-selected": String(sel),
      tabindex: sel || (app.beat == null && b.i === 1) ? "0" : "-1", "data-i": b.i,
      style: { "--grow": (b.end - b.start + 4).toFixed(2) },
      "aria-label": `${t("beats.n", { n: b.i })}, ${timecode(b.start, fps())}–${timecode(b.end, fps())}. ${b.text || ""}`,
    });
    const strip = h("div", { class: "strip" }, ...(b.shots.length ? b.shots.slice(0, tall() ? 1 : 4).map((c) => pic(c, b)) : [h("span", { class: "no-pic" })]));
    const top = h("div", { class: "b-top", title: `${timecode(b.start, fps())}–${timecode(b.end, fps())}` },
      h("b", { text: t("beats.n", { n: b.i }) }), h("span", { class: "now", hidden: true }),
      changedIn(b) ? h("span", { class: "chg", text: t("beats.changed") }) : null,
      h("span", { class: "grow" }), h("span", { text: len(b) }));
    const body = h("div", { class: "b-body" }, top);
    if (sel) body.append(detail(b, bad, refused));
    else {
      body.append(h("div", { class: "b-line", text: b.text || t(b.kind === "line" ? "beats.silent" : "beats.noWords") }));
      if (problem) body.append(h("div", { class: "b-issue" }, icon("i-warn"), h("span", { text: problem })));
      else body.append(elems(b));
    }
    el.append(strip, body);
    return el;
  }

  function elems(b) {
    const out = h("div", { class: "b-els" });
    if (b.shots.length) out.append(h("span", {}, icon("i-film"), h("span", { text: t("beats.shots", { n: b.shots.length }) })));
    const seen = new Set();
    for (const c of b.elements) {
      const [k, ic] = elementKind(c);
      if (seen.has(k)) continue;
      seen.add(k);
      out.append(h("span", {}, icon(ic), h("span", { text: t(`el.${k}`) })));
    }
    return out;
  }

  // The open beat: its line in caption phrases, its pictures in order, its text and cards; each one seeks and
  // becomes the subject of the next message. Two columns that scroll on their own, so the stage keeps its height.
  function detail(b, bad, refused) {
    const out = [];
    const side = [];
    const caps = b.captions.length ? b.captions : null;
    const line = h("div", { class: "d-line" });
    if (caps) {
      caps.forEach((c, k) => {
        const p = h("button", { type: "button", class: "d-phrase", "data-t": c.start, text: c.text });
        tip(p, t("beats.seekTo", { t: timecode(c.start, fps()) }));
        pressable(p, () => app.seek(c.start + 0.001));
        line.append(p, k < caps.length - 1 ? " " : "");
      });
    } else line.textContent = b.text || t(b.kind === "line" ? "beats.silent" : "beats.noWords");
    out.push(line);

    if (refused) out.push(h("div", { class: "d-bad" }, icon("i-refused"), h("span", { text: `${refused.reason} · ${timecode(refused.t, fps())}` })));
    // the refusal already names its own first problem
    for (const is of bad.filter((x) => !(refused && x.clip === refused.clip && Math.abs((x.t ?? -1) - (refused.t ?? -2)) < 0.05))) {
      out.push(h("div", { class: "d-bad" }, icon("i-warn"), h("span", { text: issueText(is) })));
    }

    if (b.shots.length) {
      const pics = h("div", { class: "d-pics" });
      for (const c of b.shots) {
        const at = Math.max(c.start, b.start);
        const p = h("button", { type: "button", class: `d-pic${app.selected === c.id ? " is-sel" : ""}${app.latest.has(c.id) ? " is-chg" : ""}`, "data-clip": c.id },
          pic(c, b), h("span", { text: timecode(at, fps()) }));
        tip(p, `${kindName(c)} · ${c.label || c.id} · ${timecode(c.start, fps())}–${timecode(c.end, fps())}${app.latest.has(c.id) ? ` · ${t("beats.changed")}` : ""}`);
        pressable(p, () => pick(c, at));
        pics.append(p);
      }
      out.push(h("div", { class: "d-sec" }, h("h4", { text: t("beats.pictures") }), pics));
    }
    const rows = [...b.elements, ...b.sounds];
    if (rows.length) {
      const list = h("div", { class: "d-rows" });
      for (const c of rows) {
        const [, ic] = elementKind(c);
        const at = Math.max(c.start, b.start);
        const faulty = (app.state?.issues || []).some((is) => is.clip === c.id);
        const r = h("button", { type: "button", class: `d-row${app.selected === c.id ? " is-sel" : ""}${app.latest.has(c.id) ? " is-chg" : ""}${faulty ? " is-bad" : ""}`, "data-clip": c.id },
          icon(faulty ? "i-warn" : ic), h("span", { class: "d-kind", text: kindName(c) }), h("span", { class: "d-text", text: words(c) }),
          h("span", { class: "d-time", text: timecode(c.start, fps()) }));
        tip(r, `${kindName(c)} · ${c.id} · ${timecode(c.start, fps())}–${timecode(c.end, fps())}${app.latest.has(c.id) ? ` · ${t("beats.changed")}` : ""}`);
        pressable(r, () => pick(c, at));
        list.append(r);
      }
      side.push(h("div", { class: "d-sec" }, h("h4", { text: t("beats.onScreen") }), list));
    }
    if (!b.shots.length && !rows.length) out.push(h("p", { class: "d-note", text: t("beats.nothingPlaced") }));
    const col = (kids) => {
      const c = h("div", { class: "d-col" }, ...kids);
      c.addEventListener("scroll", () => fade(c), { passive: true });
      return c;
    };
    return h("div", { class: `d-grid${side.length ? "" : " is-one"}` }, col(out), side.length ? col(side) : null);
  }

  // A column with more below or above fades at that edge, so the cut-off content reads as more, not as the end.
  function fade(c) {
    c.classList.toggle("more-below", c.scrollTop + c.clientHeight < c.scrollHeight - 2);
    c.classList.toggle("more-above", c.scrollTop > 2);
  }

  function pick(c, at) {
    app.select(app.selected === c.id ? null : c.id);
    app.seek(at + 0.001);
  }

  // ---------------------------------------------------------------- the whole region
  function emptyBox(title, body) {
    return h("div", { class: "beats-empty" }, h("div", {},
      h("div", { class: "ghosts", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      title ? h("strong", { text: title }) : null, h("p", { text: body })));
  }

  function render(force = false) {
    const cut = app.cut();
    beats = cut ? beatsOf(cut) : [];
    app.beats = beats;
    if (app.beat != null && !beats.some((b) => b.i === app.beat)) app.beat = null;
    const k = JSON.stringify([cut?.revision, app.beat, app.selected, [...app.latest], app.result(), (app.state?.issues || []).length,
      document.body.classList.contains("is-tall"), frameApi, app.dimmed()]);
    if (k === key && !force) return renderLive();
    key = k;
    renderHead();
    if (!beats.length) {
      row.removeAttribute("aria-label");
      if (app.broken()) row.replaceChildren(emptyBox(null, t("beats.brokenBody")));      // the banner above names the error
      else row.replaceChildren(emptyBox(null, t("beats.empty")));
      return;
    }
    row.setAttribute("aria-label", t("beats.title"));
    row.setAttribute("aria-orientation", tall() ? "vertical" : "horizontal");
    row.replaceChildren(...beats.map(card));
    row.style.opacity = app.dimmed() ? "0.55" : "";
    renderLive();
    const open = row.querySelector(".is-open");
    if (open) requestAnimationFrame(() => {
      open.scrollIntoView({ block: "nearest", inline: "nearest" });
      open.querySelectorAll(".d-col").forEach(fade);
    });
  }
  new ResizeObserver(() => row.querySelectorAll(".is-open .d-col").forEach(fade)).observe(row);

  function renderHead() {
    const cut = app.cut();
    if (!beats.length) { sum.textContent = ""; renderHealth(); return; }
    const dur = shortTime(cut.duration || 0);
    const v = cut.voice?.duration;
    sum.textContent = [t("beats.count", { n: beats.length }), timecode(cut.duration || 0, fps()).replace(/\d$/, ""),
      v ? t("beats.narration", { d: timecode(v, fps()).replace(/\d$/, "") }) : t("beats.noNarration")].join(" · ");
    tip(sum, beats[0].kind === "line" ? t("beats.sumTip", { d: dur }) : t("beats.sumTipShots"));
    renderHealth();
  }

  function renderHealth() {
    const r = app.running;
    const n = (app.state?.issues || []).length + (app.result().state === "refused" ? 1 : 0);
    health.className = "health";
    health.removeAttribute("role");
    health.tabIndex = -1;
    if (r && app.runText) {
      health.classList.add("is-run");
      health.replaceChildren(icon("i-scan"), app.runText().short);
    } else if (!beats.length) {
      health.replaceChildren();
    } else if (n) {
      health.classList.add("is-bad");
      health.replaceChildren(icon("i-warn"), t("beats.issues", { n }));
      health.setAttribute("role", "button");
      health.tabIndex = 0;
      tip(health, t("beats.issuesTip"));
    } else {
      health.replaceChildren(icon("i-check"), t("beats.clean"));
      tip(health, t("beats.cleanTip"));
    }
    fitHead();
  }
  // one line in every language: the summary drops first, then the Tracks label (its icon and tooltip stay)
  function fitHead() {
    const head = sum.parentElement;
    head.classList.remove("no-sum", "is-tight");
    const over = () => head.scrollWidth > head.clientWidth + 1;
    if (sum.scrollWidth > sum.clientWidth + 1 || over()) head.classList.add("no-sum");
    if (over()) head.classList.add("is-tight");
  }
  new ResizeObserver(fitHead).observe(sum.parentElement);
  pressable(health, () => { if (health.getAttribute("role") === "button") app.showPanel("issues"); });

  // what moves with the playhead and the agent's progress, without rebuilding the cards
  let liveNow = -1;
  function renderLive() {
    const now = beatAt(beats, app.time)?.i ?? -1;
    const r = app.running;
    const pos = r && typeof r.progress === "number" && /render|draft/.test(r.tool) ? r.progress * (app.cut()?.duration || 0) : null;
    for (const el of row.querySelectorAll(".beat")) {
      const b = beats[Number(el.dataset.i) - 1];
      el.classList.toggle("is-now", b.i === now);
      el.querySelector(".now").hidden = b.i !== now || app.beat === b.i;
      const strip = el.querySelector(".strip");
      let prog = strip.querySelector(".prog"), chk = strip.querySelector(".chk");
      const p = pos != null ? (pos - b.start) / (b.end - b.start) : b.i === now ? (app.time - b.start) / (b.end - b.start) : null;
      const done = pos != null && pos >= b.end;
      if (done && !chk) strip.append(chk = h("span", { class: "chk" }, icon("i-tick")));
      if (!done && chk) chk.remove();
      if (p != null && p > 0 && p < 1 && !done) {
        if (!prog) strip.append(prog = h("span", { class: "prog" }));
        prog.style.setProperty("--p", `${p * 100}%`);
      } else if (prog) prog.remove();
      for (const ph of el.querySelectorAll(".d-phrase")) {
        const c = b.captions.find((x) => Math.abs(x.start - Number(ph.dataset.t)) < 1e-6);
        ph.classList.toggle("is-now", !!c && app.time >= c.start && app.time < c.end);
      }
    }
    if (now !== liveNow) liveNow = now;
    renderHealth();
  }

  // ---------------------------------------------------------------- choosing a beat
  app.setBeat = (i, { seek = true, focus = false } = {}) => {
    const b = beats.find((x) => x.i === i);
    app.beat = b ? b.i : null;
    if (b && seek) {
      if (app.selected) app.select(null);
      const r = refusedIn(b);
      app.seek(r ? r.t : b.start + (b.i === 1 ? 0 : 0.001));
    }
    app.emit("beat", app.beat);
    render();
    if (focus) row.querySelector(`.beat[data-i="${app.beat}"]`)?.focus({ preventScroll: true });
  };
  app.stepBeat = (d) => {
    if (!beats.length) return false;
    const cur = beatAt(beats, app.time);
    let i = cur.i + d;
    if (d < 0 && app.time - cur.start > 0.6) i = cur.i;      // back once returns to the start of the beat
    i = Math.min(beats.length, Math.max(1, i));
    app.setBeat(i);
    return true;
  };

  row.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    const el = e.target.closest(".beat");
    if (!el || el.classList.contains("is-open")) return;
    app.setBeat(Number(el.dataset.i), { focus: true });
  });
  row.addEventListener("keydown", (e) => {
    const el = e.target.closest?.(".beat");
    if (!el || e.target !== el) return;
    const i = Number(el.dataset.i);
    const back = tall() ? "ArrowUp" : "ArrowLeft", fwd = tall() ? "ArrowDown" : "ArrowRight";
    let n = null;
    if (e.key === back) n = i - 1;
    else if (e.key === fwd) n = i + 1;
    else if (e.key === "Home") n = 1;
    else if (e.key === "End") n = beats.length;
    else if (e.key === "Enter" || e.key === " ") n = i;
    if (n == null) return;
    e.preventDefault();
    e.stopPropagation();
    app.setBeat(Math.min(beats.length, Math.max(1, n)), { focus: true });
  });

  let liveAt = 0;
  app.on("time", () => {
    const now = performance.now();
    if (app.playing && now - liveAt < 120) return;
    liveAt = now;
    renderLive();
  });
  app.on("state", () => render());
  app.on("view", () => render());
  app.on("select", () => render());
  app.on("running", () => { render(); renderLive(); });
  app.on("tick", () => { if (app.running) renderHealth(); });
  app.on("progress", renderLive);
  app.on("frames", framesReady);
  app.on("layout", () => render(true));

  render();
  return { render, beats: () => beats };
}
