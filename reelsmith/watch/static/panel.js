import { BASE, post } from "./api.js";
import { kindName } from "./beats.js";
import { has, lang, t } from "./i18n.js";
import {
  busy as busyOn, bytes, clamp, clock, closeOnBackdrop, disable, elapsed, h, icon, menuButton, note, pressable, shortTime, storage, store, timecode, tip, typeColor,
  writtenText,
} from "./util.js";

const PANES = ["chat", "issues", "clip", "assets"];
const GROUP_MIN = 3;            // a run of this many calls to one tool collapses into one row
const GROUP_GAP_S = 300;        // and a pause this long breaks the run (and puts a time divider in the feed)
const PAID = new Set(["speak", "draw", "animate", "capture", "transcribe", "footage"]);
const ICONS = {
  edit: "i-pencil", undo: "i-undo", redo: "i-undo", preview: "i-eye", frames: "i-eye", inspect: "i-eye", review: "i-eye",
  check: "i-check", render: "i-film", speak: "i-mic", transcribe: "i-mic", draw: "i-brush", animate: "i-brush",
  capture: "i-pic", footage: "i-import", import_asset: "i-import", new_project: "i-spark",
};
const KINDS = {
  edit: "edit", undo: "edit", redo: "edit", preview: "look", frames: "look", inspect: "look", review: "look",
  check: "check", render: "render", speak: "make", transcribe: "make", draw: "make", animate: "make", capture: "make",
  footage: "make", import_asset: "bring", new_project: "bring",
};

export const toolIcon = (tool) => ICONS[tool] || "i-dot";
const toolKind = (tool) => KINDS[tool] || "other";
export function toolName(tool) {
  const k = `tool.${tool}`;
  return t(k) !== k ? t(k) : tool;
}

// A centred empty state: a line icon, a heading and a hint.
export function emptyState(iconName, title, body, ...extra) {
  return h("div", { class: "empty-state" }, icon(iconName, "es-icon"), h("strong", { text: title }),
    body ? h("p", { text: body }) : null, ...extra);
}

// A long list is one Tab stop: the arrow keys move between its controls, so Tab gets past it in one press.
export function rove(box, label) {
  const items = () => [...box.querySelectorAll("button")].filter((el) => el.offsetParent !== null);
  const quiet = () => { for (const el of box.querySelectorAll("button")) el.tabIndex = -1; };
  new MutationObserver(quiet).observe(box, { childList: true, subtree: true });
  quiet();
  box.setAttribute("aria-description", label);
  box.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    const list = items();
    if (!list.length) return;
    e.preventDefault();
    e.stopPropagation();
    const i = list.indexOf(document.activeElement);
    const n = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1
      : i < 0 ? (e.key === "ArrowDown" ? 0 : list.length - 1) : clamp(i + (e.key === "ArrowDown" ? 1 : -1), 0, list.length - 1);
    list[n].focus();
    list[n].scrollIntoView({ block: "nearest" });
  });
}

export function money(usd) {
  if (usd == null) return "";
  return usd > 0 && usd < 0.005 ? "<$0.01" : `$${usd.toFixed(2)}`;
}

// A disclosure button: aria-expanded on the button, the body hidden or shown, the choice kept by the caller.
export function disclosure(label, body, open, onToggle, cls = "") {
  const id = `d${Math.random().toString(36).slice(2, 9)}`;
  body.id = id;
  body.hidden = !open;
  const btn = h("button", { type: "button", class: `disc ${cls}`, "aria-expanded": String(!!open), "aria-controls": id },
    icon("i-chev", "disc-chev"), h("span", { text: label }));
  btn.addEventListener("click", () => {
    const now = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(now));
    body.hidden = !now;
    onToggle?.(now);
  });
  return btn;
}

// ---------------------------------------------------------------- what a tool call did, in a person's words
const firstLine = (a) => String(a.text || a.summary || "").split("\n", 1)[0];
const lines = (a) => String(a.text || a.summary || "").split("\n");
const count = (key, n) => t(key, { n });

function costOf(a) {
  if (!PAID.has(a.tool)) return null;
  const body = lines(a).filter((l) => !/^Paid spend/i.test(l)).join("\n");
  const m = /\$(\d+\.\d+)/.exec(body);
  return m ? Number(m[1]) : null;
}

function clipIds(text) {
  const ids = new Set();
  for (const m of text.matchAll(/\bclip (?!track)([A-Za-z0-9_][\w-]*)/g)) ids.add(m[1]);
  const br = /\[([^\]]*)\]\s*$/.exec(text.split("\n", 1)[0]);
  if (br) for (const m of br[1].matchAll(/([A-Za-z0-9_][\w-]*) \d+\.\d+-\d+\.\d+ s/g)) ids.add(m[1]);
  return [...ids];
}

const OPS = [
  ["add", /^added \S+ clip /], ["track", /^added \S+ track /], ["change", /^updated clip /], ["move", /^moved clip /],
  ["remove", /^removed \S+ clip /], ["untrack", /^removed track /], ["cut", /^ripple-deleted /], ["insert", /^inserted /],
  ["split", /^split clip /], ["trim", /^trimmed clip /], ["keys", /keyframe/], ["trackset", /^updated track /],
  ["asset", /^(added|updated|removed) asset /], ["set", /^(set|removed) [a-z_]+[.=\s]/],
];
function editSentence(head) {
  let body = head.replace(/^applied:\s*/, "");
  const total = Number((/^(\d+) ops:\s*/.exec(body) || [])[1] || 1);
  body = body.replace(/^\d+ ops:\s*/, "").replace(/\s*\[[^\]]*\]\s*$/, "");
  const counts = {};
  let known = 0;
  for (const part of body.split("; ")) {
    const hit = OPS.find(([, re]) => re.test(part));
    if (hit) { counts[hit[0]] = (counts[hit[0]] || 0) + 1; known += 1; }
  }
  const kinds = OPS.map(([k]) => k).filter((k) => counts[k]);
  const quiet = kinds.length > 0 && kinds.every((k) => k === "asset" || k === "set");
  if (kinds.length === 1 && kinds[0] === "asset") return { text: count("act.edit.files", counts.asset), quiet, files: true };
  if (quiet) return { text: t("act.edit.details"), quiet };
  if (!kinds.length) return { text: total > 1 ? count("act.edit.n", total) : t("act.edit.one") };
  const parts = kinds.map((k) => count(`op.${k}`, counts[k]));
  if (total > known && known) parts.push(count("op.more", total - known));
  return { text: `${t("act.edit.head")}${parts.slice(0, 3).join(t("list.sep"))}${parts.length > 3 ? ` +${parts.length - 3}` : ""}` };
}

function spans(head, fps, name) {
  const br = /\[([^\]]*)\]\s*$/.exec(head);
  if (!br) return null;
  const items = [...br[1].matchAll(/([A-Za-z0-9_][\w-]*) (\d+\.\d+)-(\d+\.\d+) s/g)]
    .map((m) => `${name(m[1])} ${timecode(+m[2], fps)}–${timecode(+m[3], fps)}`);
  return items.length ? items.slice(0, 3).join(" · ") + (items.length > 3 ? ` +${items.length - 3}` : "") : null;
}

// What the activity row says to a person: {text, sub, subKind, fail, cost, ids, next, action}.
function describe(a, fps = 30, name = (id) => id) {
  const head = firstLine(a);
  const all = lines(a);
  const fail = a.ok === false;
  const d = { icon: toolIcon(a.tool), kind: toolKind(a.tool), fail, cost: costOf(a), ids: [], sub: null, subKind: "" };
  const reason = () => (all.slice(1).find((l) => l.trim()) || "").replace(/^\[(error|warning)\]\s*/, "").trim();
  switch (a.tool) {
    case "edit":
      if (fail) {
        d.text = t("act.edit.refused");
        d.sub = reason() || head;
        d.subKind = "is-error";
        break;
      }
      {
        const e = editSentence(head);
        d.text = e.text;
        d.quiet = !!e.quiet;           // nothing on the timeline changed: no history view, and runs of them group apart
        d.files = !!e.files;
        d.ids = clipIds(a.text || a.summary || "");
        d.sub = e.files ? [...head.matchAll(/asset (\S+)/g)].map((m) => m[1]).join(" · ") : spans(head, fps, name);
        d.mono = !!e.files;
      }
      break;
    case "undo": d.text = fail ? t("act.undo.none") : t("act.undo"); d.sub = fail ? head : null; break;
    case "redo": d.text = fail ? t("act.redo.none") : t("act.redo"); d.sub = fail ? head : null; break;
    case "preview": {
      if (fail) break;
      const sweep = /^sweep: measured (\d+)/.exec(head);
      const n = sweep ? +sweep[1] : +((/^(\d+) still/.exec(head) || [])[1] || 0);
      d.text = sweep ? count("act.sweep", n) : count("act.preview", n);
      const probs = /layout: (\d+) problem/.exec(a.text || "");
      const times = [...String(a.text || "").matchAll(/^- (\d+(?:\.\d+)?)s \(frame/gm)].map((m) => timecode(+m[1], fps));
      if (probs) { d.text += ` · ${count("act.problems", +probs[1])}`; d.sub = reason2(a); d.subKind = "is-warn"; }
      else if (/layout: ok/.test(a.text || "")) { d.sub = t("act.layoutOk"); d.good = true; }
      if (!d.sub && times.length) d.sub = t("act.at", { times: times.slice(0, 6).join(", ") + (times.length > 6 ? " …" : "") });
      break;
    }
    case "frames": case "review": {
      if (fail) break;
      const n = +((/(\d+) frame/.exec(head) || [])[1] || 0);
      d.text = count(a.tool === "review" ? "act.review" : "act.frames", n);
      break;
    }
    case "inspect": if (!fail) d.text = t("act.inspect"); break;
    case "check": {
      const errs = /^BLOCKED: (\d+) error/.exec(head);
      const warns = /(\d+) warning/.exec(head);
      if (errs) { d.text = `${t("act.check")} · ${count("act.errors", +errs[1])}`; d.fail = true; d.sub = reason(); d.subKind = "is-error"; }
      else if (/no issues/.test(head) || (warns && +warns[1] === 0)) { d.text = t("act.check"); d.sub = t("beats.clean"); d.good = true; }
      else if (warns) d.text = `${t("act.check")} · ${count("act.warnings", +warns[1])}`;
      else if (!fail) d.text = t("act.check");
      break;
    }
    case "render": {
      const ok = /^DELIVERED/.exec(head);
      const stopped = /^NOT DELIVERED(?: \(stopped at ([^)]+)\))?: (.*)$/.exec(head);
      if (ok) {
        const m = /\((\d+(?:\.\d+)?) s,.*?([\d.]+ [KMG]?B); rendered in ([\d.]+) s\)/.exec(head);
        d.text = t("act.rendered");
        if (m) d.sub = [shortTime(+m[1]), m[2], t("act.took", { d: elapsed(+m[3]) })].join(" · ");
        d.action = "watch";
      } else if (stopped) {
        d.text = stopped[1] ? t("act.renderStopped", { stage: stageWord(stopped[1]) }) : t("act.renderFailed");
        d.sub = stopped[2];
        d.subKind = "is-error";
        d.action = "issues";
      }
      break;
    }
    case "speak": {
      if (fail) break;
      const n = +((/(\d+) line\(s\) newly/.exec(a.text || "") || [])[1] ?? NaN);
      const dur = /, ([\d.]+) s, /.exec(head);
      d.text = Number.isFinite(n) ? count("act.speak", n) : t("act.speakOne");
      const cached = +((/(\d+) from cache/.exec(a.text || "") || [])[1] || 0);
      d.sub = [dur ? t("act.speech", { d: shortTime(+dur[1]) }) : null, cached ? count("act.cached", cached) : null].filter(Boolean).join(" · ") || null;
      break;
    }
    case "draw": case "animate": case "import_asset": {
      if (fail) break;
      const id = (/'([^']+)'/.exec(head) || [])[1];
      const kind = a.tool === "import_asset" ? (/\((image|video|audio|evidence|font)\b/.exec(head) || [])[1] : null;
      d.text = t(`act.${a.tool}`, { id: id || "", what: kind ? t(`ak.${kind}`) : "" });
      if (a.tool === "import_asset") d.sub = (/: (\S+) \(/.exec(head) || [])[1] || null;
      break;
    }
    case "new_project": if (!fail) d.text = t("act.new_project"); break;
    case "transcribe": if (!fail) d.text = t("act.transcribe"); break;
    case "capture": if (!fail) d.text = t("act.capture"); break;
    default: break;
  }
  if (!d.text) {
    d.text = fail ? t("act.failedTool", { tool: toolName(a.tool) }) : t("act.ran", { tool: toolName(a.tool) });
    if (fail) { d.sub = head; d.subKind = "is-error"; }
  }
  if (d.fail && a.tool !== "check") d.next = true;
  return d;
}
function reason2(a) {
  const l = lines(a).find((x) => /^\[(error|warning)\]/.test(x));
  return l ? l.replace(/^\[(error|warning)\]\s*/, "") : null;
}
function stageWord(s) { return has(`stage.${s}`) ? t(`stage.${s}`) : s; }

function groupSentence(tool, n) {
  return has(`act.group.${tool}`) ? count(`act.group.${tool}`, n) : t("act.group.other", { tool: toolName(tool), n });
}

// Problems the agent's last preview listed: [level] where @ t s: message.
function previewIssues(acts, clipExists) {
  const last = [...acts].reverse().find((a) => a.tool === "preview" && a.ok && a.text);
  if (!last) return null;
  const rows = [];
  for (const l of lines(last)) {
    const m = /^\[(error|warning|advice)\] (\S+?)(?: @ (\d+(?:\.\d+)?)s)?: (.+)$/.exec(l);
    if (!m) continue;
    rows.push({ level: m[1], source: "preview", clip: clipExists(m[2]) ? m[2] : null, t: m[3] != null ? +m[3] : null,
      text: `${m[2]}: ${m[4]}` });
  }
  const later = acts.some((a) => a.tool === "edit" && a.ok && a.batch != null && a.ts > last.ts);
  return { at: last.ts, rows, stale: later };
}

// ---------------------------------------------------------------- the panel
export function createPanel(app) {
  const $ = (id) => document.getElementById(id);
  const panes = Object.fromEntries(PANES.map((k) => [k, $(`pane-${k}`)]));
  const replay = $("replay"), replayRange = $("replayRange"), replayLabel = $("replayLabel"), replayPlay = $("replayPlay");
  const issuesList = $("issuesList"), clipPane = $("clipBody"), assetsList = $("assetsList");
  const issueCount = $("issueCount"), assetCount = $("assetCount");
  const paneHead = $("paneHead"), moreBtn = $("moreBtn"), moreMenu = $("moreMenu");

  // The thread is the session; the issues, the selected element and the files open in its place, one at a time.
  let current = "chat", touched = false;
  function show(name, byPerson = true) {
    if (!panes[name]) return;
    if (byPerson) touched = true;
    const was = current;
    current = name;
    for (const [k, el] of Object.entries(panes)) el.hidden = k !== name;
    paneHead.hidden = name === "chat";
    $("paneTitle").textContent = name === "chat" ? "" : t(`pane.${name}`);
    for (const it of moreMenu.querySelectorAll("[data-pane]")) it.setAttribute("aria-checked", String(it.dataset.pane === name));
    if (was !== name) app.emit("panel", name);
  }
  pressable($("paneBack"), () => { show("chat"); $("chatInput").focus(); });
  tip($("paneBack"), t("pane.backTip"), "Esc");

  const more = menuButton(moreBtn, moreMenu);
  const closeOthers = app.closeMenus;
  app.closeMenus = () => more.close(true) || !!closeOthers?.();
  tip(moreBtn, t("pane.more"));
  moreMenu.addEventListener("click", (e) => {
    const it = e.target.closest(".menu-item");
    if (!it) return;
    more.close(false);
    if (it.dataset.pane) { show(current === it.dataset.pane ? "chat" : it.dataset.pane); (current === "chat" ? moreBtn : $("paneBack")).focus(); }
    else if (it.dataset.filter) { setFilter(it.dataset.filter); moreBtn.focus(); }
    else if (it.dataset.do === "help") app.openHelp();
  });

  // What the thread shows: everything, the requests and replies, the changes, or the problems. The entries stay in
  // the page; the stylesheet hides the others, so streaming and scrolling work the same in every view.
  const log = $("chatLog"), chip = $("filterChip");
  $("filterGroup").hidden = !has("filter.all");
  function setFilter(f) {
    if (!has(`filter.${f}`)) f = "all";
    store("filter", f === "all" ? null : f);
    log.dataset.filter = f;
    log.dataset.none = t("filter.none");
    for (const it of moreMenu.querySelectorAll("[data-filter]")) it.setAttribute("aria-checked", String(it.dataset.filter === f));
    chip.hidden = f === "all";
    $("filterText").textContent = f === "all" ? "" : t(`filter.${f}`);
    tip(chip, t("filter.clear"));
    if (current !== "chat") show("chat");
    log.scrollTop = log.scrollHeight;
  }
  pressable(chip, () => { setFilter("all"); moreBtn.focus(); });
  setFilter(storage("filter", "all"));
  for (const it of moreMenu.querySelectorAll("[data-label]")) it.querySelector("span").textContent = t(it.dataset.label);

  // the history of the cut, batch by batch: a bar under the head, opened from it
  const replayBtn = $("replayBtn");
  function setReplayBar(on) {
    store("replay-bar", on);
    if (!on && app.viewing) app.backToNow();
    renderReplay();
  }
  pressable(replayBtn, () => {
    if (!(app.state?.history || []).length) { note(replayBtn, t("act.noHistory")); return; }
    setReplayBar(replay.hidden);
  });

  // ---------------------------------------------------------------- the first-run card
  const intro = $("intro");
  function renderIntro() {
    if (storage("intro-done", false)) { intro.hidden = true; return; }
    const done = () => {
      store("intro-done", true);
      intro.hidden = true;
      note(moreBtn, t("intro.gone"));
      $("chatInput").focus();
    };
    const ok = h("button", { type: "button", class: "text-btn sm", text: t("intro.ok") });
    tip(ok, t("intro.okTip"));
    pressable(ok, done);
    const more = h("button", { type: "button", class: "link-btn", text: t("intro.keys") });
    tip(more, t("help.btn"), "?");
    pressable(more, () => app.openHelp());
    intro.replaceChildren(
      h("div", { class: "intro-head" }, h("strong", { class: "intro-title", id: "introTitle", text: t("intro.title") }), ok),
      h("p", {}, t("intro.body"), " ", more));
    intro.hidden = false;
  }

  // ---------------------------------------------------------------- the agent's steps, as entries in the session thread
  const openResults = new Set(), openGroups = new Set();
  let seen = null, stepsKey = "", stepsOut = [];

  function keyed(acts) {
    const n = new Map();
    return acts.map((a) => {
      const base = `${a.ts}|${a.tool}|${a.batch ?? ""}`;
      const k = (n.get(base) || 0) + 1;
      n.set(base, k);
      return { a, key: `${base}|${k}` };
    });
  }
  const secsOf = (ts) => new Date(ts).getTime() / 1000;

  const nameOf = (id) => { const c = app.clipById(id, app.state?.tracks); return c ? kindName(c) : id; };
  const said = (item) => (item.d ||= describe(item.a, app.fps(), nameOf));
  const family = (item) => `${item.a.tool}|${said(item).files ? "files" : said(item).quiet ? "quiet" : ""}`;
  // Runs of one tool (all of them fine, close together) become one entry; failures always stand alone.
  function grouped(items) {
    const out = [];
    for (let i = 0; i < items.length;) {
      let j = i + 1;
      const a = items[i].a, kin = family(items[i]);
      if (a.ok !== false && a.tool !== "render") {
        while (j < items.length && family(items[j]) === kin && items[j].a.ok !== false
          && secsOf(items[j].a.ts) - secsOf(items[j - 1].a.ts) < GROUP_GAP_S) j += 1;
      }
      if (j - i >= GROUP_MIN) { out.push({ group: items.slice(i, j) }); i = j; } else { out.push(items[i]); i += 1; }
    }
    return out;
  }

  function timeLabel(ts) {
    const d = new Date(ts);
    const today = new Date().toDateString() === d.toDateString();
    const hm = clock(ts).slice(0, 5);
    return today ? hm : `${d.toLocaleDateString(lang, { month: "short", day: "numeric" })} · ${hm}`;
  }

  function thumbLabel(path) {
    const name = path.split("/").pop();
    const fr = /(?:still|frame)_(\d+)/.exec(name);
    if (fr) return timecode(+fr[1] / app.fps(), app.fps());
    if (/^contact/.test(name)) return t("pic.contact");
    const sh = /sheet_?(\d+)/.exec(name);
    if (sh) return t("pic.sheet", { n: +sh[1] });
    return name.replace(/\.\w+$/, "");
  }
  function pictures(a) {
    return (a.files || []).filter((p) => /\.(png|jpe?g|webp|gif)$/i.test(p)).map((p) => {
      const fr = /(?:still|frame)_(\d+)/.exec(p);
      return { url: `${BASE}/project/${p.split("/").map(encodeURIComponent).join("/")}`, label: thumbLabel(p), path: p,
        t: fr ? +fr[1] / app.fps() : null };
    });
  }
  function thumb(p, onOpen, cls = "") {
    const b = h("button", { type: "button", class: `thumb ${cls}` },
      h("img", { src: p.url, alt: "", loading: "lazy", draggable: "false", onerror: (e) => e.target.replaceWith(icon("i-pic", "thumb-gone")) }),
      p.label ? h("span", { class: "thumb-cap", text: p.label }) : null);
    tip(b, t("pic.open", { what: p.label || "" }));
    pressable(b, onOpen);
    return b;
  }
  function strip(a) {
    const pics = pictures(a);
    if (!pics.length) return null;
    const MAX = 4;
    const shown = pics.slice(0, pics.length > MAX ? MAX - 1 : MAX);
    const kids = shown.map((p, i) => thumb(p, (e) => lightbox.open(pics, i, e.currentTarget)));
    if (pics.length > shown.length) {
      const more = h("button", { type: "button", class: "thumb more", text: `+${pics.length - shown.length}` });
      tip(more, t("pic.more", { n: pics.length - shown.length }));
      pressable(more, () => lightbox.open(pics, shown.length, more));
      kids.push(more);
    }
    return h("div", { class: "act-strip" }, ...kids);
  }

  // The beats an edit touched, each one a way back to that beat.
  function beatChips(nums) {
    if (!nums?.length) return null;
    const shown = nums.slice(0, 6);
    return h("div", { class: "act-beats" }, ...shown.map((n) => {
      const b = h("button", { type: "button", class: "chip is-beat" }, icon("i-target"), h("span", { text: t("beats.n", { n }) }));
      tip(b, t("act.beatTip", { n }));
      pressable(b, () => {
        if (app.viewing) app.backToNow();
        app.setBeat(n, { focus: false });
        note(b, t("act.beatShown", { n }));
      });
      return b;
    }), nums.length > shown.length ? h("span", { class: "faint small", text: `+${nums.length - shown.length}` }) : null);
  }

  // The latest delivered film, as a card that plays it on the stage.
  function filmCard(a) {
    const d = app.state?.render?.delivered;
    const pic = { url: `${BASE}/api/frame?t=1.5&h=180&src=film`, label: "" };
    const play = h("button", { type: "button", class: "text-btn mini" }, icon("i-play"), h("span", { text: t("act.watch") }));
    tip(play, t("act.watchTip"));
    pressable(play, () => {
      if (app.viewing) app.backToNow();
      app.setSource("delivered");
      app.seek(0);
      app.setPlaying(true, "ui");
      note(play, t("act.watching"));
    });
    const kids = [play];
    {
      const rev = h("button", { type: "button", class: "text-btn mini" }, icon("i-folder"), h("span", { text: t("top.reveal") }), h("span", { class: "spin", "aria-hidden": "true" }));
      tip(rev, t("reveal.tip"));
      pressable(rev, async () => {
        if (rev.classList.contains("is-busy")) return;
        const slow = setTimeout(() => busyOn(rev, true), 150);
        try { await post("/api/reveal", {}); note(rev, t("reveal.ok")); }
        catch (e) { note(rev, t("reveal.failed", { why: e.message }), "is-error"); }
        finally { clearTimeout(slow); busyOn(rev, false); }
      });
      kids.push(rev);
    }
    const facts = [d.duration ? timecode(d.duration, app.fps()).replace(/\d$/, "") : null, bytes(d.bytes),
      a.seconds ? t("act.renderedIn", { d: elapsed(a.seconds) }) : null].filter(Boolean).join(" · ");
    const open = h("button", { type: "button", class: "film-thumb" }, h("img", { src: pic.url, alt: "", loading: "lazy", draggable: "false",
      onerror: (e) => e.target.replaceWith(icon("i-film", "thumb-gone")) }), h("span", { class: "film-play" }, icon("i-play")));
    tip(open, t("act.watchTip"));
    pressable(open, () => play.click());
    const lufs = d.lufs != null ? h("div", { class: "act-sub is-ok" }, icon("i-check"), t("act.loudness", { v: String(d.lufs).replace("-", "−") })) : null;
    return h("div", { class: "film-wrap" }, lufs, h("div", { class: "film-card" }, open,
      h("div", { class: "film-info" }, h("strong", { text: t("act.film") }), h("span", { class: "num dim", text: facts }), h("div", { class: "film-actions" }, ...kids))));
  }

  // A refused render: the frame it measured, where the problem is, and a way to ask for the correction.
  function refusedBody() {
    const r = app.result();
    if (r.state !== "refused") return null;
    const kids = [];
    if (r.frame) {
      const pic = { url: `${BASE}${r.frame.startsWith("/") ? "" : "/project/"}${r.frame}`, label: r.t != null ? timecode(r.t, app.fps()) : "", path: r.frame, t: r.t };
      kids.push(h("div", { class: "act-strip is-large" }, thumb(pic, (e) => lightbox.open([pic], 0, e.currentTarget), "is-bad")));
    }
    const chips = [];
    if (r.beat != null) {
      const b = h("button", { type: "button", class: "chip is-bad" }, icon("i-warn"),
        h("span", { text: r.t != null ? `${t("beats.n", { n: r.beat })} · ${timecode(r.t, app.fps())}` : t("beats.n", { n: r.beat }) }));
      tip(b, t("act.goProblem"));
      pressable(b, () => { if (app.viewing) app.backToNow(); app.setBeat(r.beat, { focus: false }); if (r.t != null) app.seek(r.t); });
      chips.push(b);
    }
    const fix = h("button", { type: "button", class: "chip is-link" }, icon("i-undo"), h("span", { text: t("act.askFix") }));
    tip(fix, t("act.askFixTip"));
    pressable(fix, () => {
      if (r.beat != null) app.setBeat(r.beat, { focus: false });
      if (r.t != null) app.seek(r.t);
      app.emit("compose", t("act.fixText", { why: r.reason }));
    });
    chips.push(fix);
    kids.push(h("div", { class: "act-beats" }, ...chips));
    return kids;
  }

  function revealClips(ids, anchor) {
    if (app.viewing) app.backToNow();
    const found = ids.map((id) => app.clipById(id)).filter(Boolean);
    if (!found.length) { note(anchor, t("act.gone"), "is-error"); return; }
    const now = performance.now();
    for (const c of found) app.changed.set(c.id, now);
    const timed = found.filter((c) => c.start != null).sort((x, y) => x.start - y.start);
    const first = timed[0] || found[0];
    if (first.start != null) app.seek(first.start + Math.min(0.3, ((first.end ?? first.start) - first.start) / 2));
    app.select(first.id);
    note(anchor, count("act.shown", found.length));
  }

  function fixedLater(items, idx) {
    const a = items[idx].a;
    for (let j = idx + 1; j < items.length; j++) if (items[j].a.tool === a.tool && items[j].a.ok) return items[j].a.ts;
    return null;
  }

  function rowEl(item, idx, items, inGroup = false) {
    const { a, key } = item;
    const d = said(item);
    const viewing = a.batch != null && app.viewing?.n === a.batch;
    const later = d.fail ? fixedLater(items, idx) : null;
    const isNew = seen && !seen.has(key);
    const lastRender = a.tool === "render" && items.slice(idx + 1).every((x) => x.a.tool !== "render");
    const li = h("div", { class: `act k-${d.kind}${d.fail ? " is-fail" : ""}${later ? " is-fixed" : ""}${viewing ? " is-viewing" : ""}${isNew ? " is-new" : ""}${inGroup ? " in-group" : ""}` });
    const live = d.ids.length && d.ids.some((id) => app.clipById(id, app.state?.tracks));
    let title;
    if (live) {
      title = h("button", { type: "button", class: "act-text act-link", text: d.text });
      tip(title, t("act.linkTip"));
      pressable(title, () => revealClips(d.ids, title));
    } else {
      title = h("span", { class: "act-text", text: d.text });
    }
    const actions = [];
    if (a.seconds != null && a.text && a.text.trim() && (d.fail || a.tool !== "render")) {   // rows made from history alone have nothing more to show
      const pre = h("pre", { class: "act-result", text: a.text });
      actions.push({ btn: disclosure(t("act.result"), pre, openResults.has(key), (on) => { on ? openResults.add(key) : openResults.delete(key); }), body: pre });
    }
    if (a.batch != null && !d.quiet && (app.state?.history || []).some((x) => x.n === a.batch)) {
      const b = h("button", { type: "button", class: "text-btn mini then", "aria-pressed": String(viewing) },
        icon("i-history"), h("span", { text: viewing ? t("act.thenOn") : t("act.then") }));
      tip(b, viewing ? t("act.thenOnTip") : t("act.thenTip", { n: a.batch }));
      pressable(b, async () => {
        if (viewing) { app.backToNow(); return; }
        if (b.classList.contains("is-busy")) return;
        b.classList.add("is-busy");
        await app.viewHistory(a.batch);
        b.classList.remove("is-busy");
      });
      actions.push({ btn: b });
    }
    if (d.action === "issues" && (app.state?.issues || []).length) {
      const b = h("button", { type: "button", class: "text-btn mini" }, icon("i-alert"), h("span", { text: t("act.showIssues") }));
      tip(b, t("act.showIssuesTip"));
      pressable(b, () => app.showPanel("issues"));
      actions.push({ btn: b });
    }
    const secs = a.seconds != null && a.seconds >= 1 ? elapsed(a.seconds) : null;
    const film = d.action === "watch" && lastRender && app.state?.render?.delivered ? filmCard(a) : null;
    if (film) d.sub = null;
    const refused = d.fail && a.tool === "render" && lastRender && app.result().state === "refused" ? refusedBody() : null;
    if (refused) {
      const r = app.result();
      d.sub = [r.reason + (r.t != null ? ` · ${timecode(r.t, app.fps())}` : ""), app.state?.render?.delivered ? t("act.keptPrevious") : null].filter(Boolean).join(". ");
    }
    li.append(
      h("span", { class: "act-ic" }, icon(d.fail ? (a.tool === "render" ? "i-refused" : "i-alert") : d.icon)),
      h("div", { class: "act-main" },
        h("div", { class: "act-head" }, title,
          h("span", { class: "act-side" },
            d.cost != null ? h("span", { class: "cost-chip num", text: money(d.cost) }) : null,
            secs ? h("span", { class: "act-secs num", text: secs }) : null,
            h("span", { class: "act-time num", text: clock(a.ts).slice(0, 5) }))),
        d.sub ? h("div", { class: `act-sub${d.mono ? " mono" : ""} ${d.subKind}${d.good ? " is-ok" : ""}` }, d.good ? icon("i-check") : null, d.sub) : null,
        d.next && !refused ? h("div", { class: "act-next", text: later ? t("act.fixedLater", { at: clock(later).slice(0, 5) }) : t("act.agentSees") }) : null,
        a.tool === "edit" && !d.fail && !d.quiet ? beatChips(a.touched?.beats) : null,
        strip(a),
        film,
        ...(refused || []),
        actions.length ? h("div", { class: "act-actions" }, ...actions.map((x) => x.btn)) : null,
        ...actions.filter((x) => x.body).map((x) => x.body)));
    tip(li.querySelector(".act-ic"), d.fail ? t("act.failedTip") : toolName(a.tool));
    return li;
  }

  function groupEl(g, items) {
    const first = g.group[0], last = g.group.at(-1);
    const open = openGroups.has(first.key) || g.group.some((x) => x.a.batch != null && x.a.batch === app.viewing?.n);
    const d = said(last);
    const list = h("div", { class: "act-list sub" }, ...g.group.map((x) => rowEl(x, items.indexOf(x), items, true)));
    const isNew = seen && g.group.some((x) => !seen.has(x.key));
    const cost = g.group.reduce((s, x) => s + (costOf(x.a) || 0), 0);
    const sentence = g.group.every((x) => said(x).files) ? count("act.edit.files", g.group.length) : groupSentence(first.a.tool, g.group.length);
    const btn = disclosure(sentence, list, open, (on) => { on ? openGroups.add(first.key) : openGroups.delete(first.key); }, "act-group-btn");
    tip(btn, open ? t("act.groupClose") : t("act.groupOpen"));
    btn.addEventListener("click", () => tip(btn, btn.getAttribute("aria-expanded") === "true" ? t("act.groupClose") : t("act.groupOpen")));
    return h("div", { class: `act act-group k-${toolKind(first.a.tool)}${isNew ? " is-new" : ""}` },
      h("span", { class: "act-ic" }, icon(toolIcon(first.a.tool))),
      h("div", { class: "act-main" },
        h("div", { class: "act-head" }, btn, h("span", { class: "act-side" },
          cost ? h("span", { class: "cost-chip num", text: money(cost) }) : null,
          h("span", { class: "act-time num", text: `${clock(first.a.ts).slice(0, 5)}–${clock(last.a.ts).slice(0, 5)}` }))),
        h("div", { class: "act-sub", text: `${t("act.latest")}: ${d.text}` }), list));
  }

  // The steps as thread entries {key, ts, el}; rebuilt only when the log, the view or the result moves.
  function steps() {
    const acts = app.state?.activity || [];
    const key = JSON.stringify([acts.length, acts.at(-1)?.ts, app.viewing?.n ?? "", app.state?.revision, app.state?.render?.delivered?.at,
      app.state?.result?.state, lang]);
    if (key === stepsKey) return stepsOut;
    stepsKey = key;
    const items = keyed(acts);
    const out = [];
    let prevTs = null;
    for (const g of grouped(items)) {
      const head = g.group ? g.group[0] : g;
      const ts = head.a.ts;
      if (!prevTs || secsOf(ts) - secsOf(prevTs) >= GROUP_GAP_S) {
        out.push({ key: `div|${ts}`, ts, el: h("div", { class: "act-divider", "aria-hidden": "true" }, h("span", { text: timeLabel(ts) })) });
      }
      prevTs = (g.group ? g.group.at(-1) : g).a.ts;
      out.push({ key: head.key, ts, el: g.group ? groupEl(g, items) : rowEl(g, items.indexOf(g), items) });
    }
    if (app.state) seen = new Set(items.map((x) => x.key));      // what was there on arrival is not news
    stepsOut = out;
    return out;
  }

  function renderReplay() {
    const hist = app.state?.history || [];
    const on = storage("replay-bar", false) || !!app.viewing;
    replay.hidden = !on || !hist.length;
    replayBtn.setAttribute("aria-pressed", String(!replay.hidden));
    disable(replayBtn, hist.length ? null : t("act.noHistory"), t(replay.hidden ? "act.replayShow" : "act.replayHide"));
    if (!hist.length) return;
    replayRange.max = String(hist.length);
    const idx = app.historyIndex();
    replayRange.value = String(idx < 0 ? hist.length : idx);
    replayRange.style.setProperty("--fill", `${(Number(replayRange.value) / hist.length) * 100}%`);
    replayRange.setAttribute("aria-valuetext", app.viewing ? t("act.batchOf", { n: app.viewing.n, of: hist.at(-1).n }) : t("act.now"));
    tip(replayRange, app.viewing ? t("act.batchOf", { n: app.viewing.n, of: hist.at(-1).n }) : t("act.replayHint"));
    replayLabel.textContent = app.viewing ? t("act.batchOf", { n: app.viewing.n, of: hist.at(-1).n }) : t("act.now");
    replayPlay.setAttribute("aria-pressed", String(!!app.replaying));
    tip(replayPlay, app.replaying ? t("act.stopReplay") : t("act.playReplay"));
    const i = app.historyIndex();
    disable($("replayPrev"), i <= 0 ? t("act.atFirst") : null, t("act.prev"));
    disable($("replayNext"), !app.viewing ? t("act.atNow") : null, t("act.next"));
  }
  replayRange.addEventListener("input", () => {
    const hist = app.state?.history || [];
    const i = Number(replayRange.value);
    if (i >= hist.length) app.backToNow(); else app.viewHistory(hist[i].n);
  });
  const stepBtn = (id, d) => {
    const b = $(id);
    pressable(b, async () => {
      const slow = setTimeout(() => b.classList.add("is-busy"), 150);
      const moved = await app.stepHistory(d);
      clearTimeout(slow);
      b.classList.remove("is-busy");
      if (!moved) note(b, d < 0 ? t("act.noEarlier") : t("act.atNow"));
    });
  };
  stepBtn("replayPrev", -1);
  stepBtn("replayNext", 1);
  pressable(replayPlay, () => app.toggleReplay());

  // ---------------------------------------------------------------- issues
  const SOURCE = { check: "src.check", layout: "src.layout", film: "src.film", preview: "src.preview" };
  function issueEl(is) {
    const b = h("button", { type: "button", class: `iss lv-${is.level}` },
      h("span", { class: "iss-text", text: is.text }),
      h("span", { class: "iss-meta" },
        is.t != null ? h("span", { class: "chip num", text: timecode(is.t, app.fps()) }) : null,
        is.clip ? h("span", { class: "chip mono", text: is.clip }) : null,
        h("span", { class: "chip", text: has(SOURCE[is.source] || "") ? t(SOURCE[is.source]) : is.source })));
    const where = is.clip || is.t != null;
    tip(b, where ? t("iss.goTip") : t("iss.noWhere"));
    pressable(b, () => {
      if (!where) { note(b, t("iss.noWhere")); return; }
      if (app.viewing) app.backToNow();
      app.openIssue(is);
      note(b, is.t != null ? t("iss.went", { t: timecode(is.t, app.fps()) }) : t("iss.selected", { id: is.clip }));
    });
    return h("li", {}, b);
  }
  function lastChecked() {
    const acts = app.state?.activity || [];
    const r = [...acts].reverse().find((a) => ["check", "preview", "render"].includes(a.tool) && a.ok !== null);
    return r ? r.ts : app.state?.render?.last?.at || null;
  }
  let issuesKey = "";
  function renderIssues() {
    const issues = app.state?.issues || [];
    const pv = previewIssues(app.state?.activity || [], (id) => !!app.clipById(id, app.state?.tracks));
    const key = JSON.stringify([issues, pv, app.state?.revision]);
    const errors = issues.filter((i) => i.level === "error").length + (pv && !pv.stale ? pv.rows.filter((r) => r.level === "error").length : 0);
    const total = issues.length + (pv && !pv.stale ? pv.rows.length : 0);
    issueCount.textContent = total ? String(total) : "";
    issueCount.className = `tab-count${errors ? " is-error" : total ? " is-warn" : ""}`;
    if (key === issuesKey) return;
    issuesKey = key;
    const checked = lastChecked();
    const out = [];
    if (!issues.length && !(pv && pv.rows.length)) {
      issuesList.replaceChildren(emptyState("i-check", t("iss.noneTitle"),
        checked ? t("iss.checkedAt", { at: timeLabel(checked) }) : t("iss.none")));
      issuesList.firstChild.classList.toggle("is-ok", !!checked);
      return;
    }
    for (const lv of ["error", "warning", "advice"]) {
      const list = issues.filter((i) => i.level === lv);
      if (!list.length) continue;
      out.push(h("section", { class: "iss-group" },
        h("h3", { class: `iss-head lv-${lv}` }, h("span", { class: "lv-dot" }), t(`iss.${lv}`), h("span", { class: "iss-n", text: String(list.length) })),
        h("ul", { class: "iss-list" }, ...list.map(issueEl))));
    }
    if (pv && pv.rows.length) {
      out.push(h("section", { class: `iss-group${pv.stale ? " is-stale" : ""}` },
        h("h3", { class: "iss-head" }, icon("i-eye", "iss-ic"), t("iss.preview", { at: clock(pv.at) }), h("span", { class: "iss-n", text: String(pv.rows.length) })),
        pv.stale ? h("p", { class: "iss-note", text: t("iss.previewStale") }) : null,
        h("ul", { class: "iss-list" }, ...pv.rows.map(issueEl))));
    }
    if (checked) out.push(h("p", { class: "iss-foot", text: t("iss.checkedAt", { at: timeLabel(checked) }) }));
    issuesList.replaceChildren(...out);
  }

  // ---------------------------------------------------------------- clip
  function findClip(id) {
    for (const tr of app.view().tracks || []) for (const c of tr.clips || []) if (c.id === id) return { c, tr };
    return null;
  }
  function row(label, ...value) {
    return h("div", { class: "kv" }, h("dt", { text: label }), h("dd", {}, ...value));
  }
  function playback(c) {
    const out = [];
    if (c.rate != null && c.rate !== 1) out.push(t("pb.rate", { v: c.rate }));
    if (c.reverse) out.push(t("pb.reverse"));
    if (c.hold != null) out.push(t("pb.hold", { v: c.hold }));
    if (c.volume != null) out.push(t("pb.volume", { v: Math.round(c.volume * 100) }));
    if (c.loop) out.push(t("pb.loop"));
    if (c.transition) out.push(t("pb.transition", { type: c.transition.type, d: c.transition.dur }));
    if (c.enter) out.push(t("pb.enter", { type: c.enter.preset, d: c.enter.dur }));
    if (c.exit) out.push(t("pb.exit", { type: c.exit.preset, d: c.exit.dur }));
    for (const [k, v] of Object.entries(c.keyframes || {})) out.push(t("pb.keys", { what: k, n: v.length }));
    return out;
  }
  function lastChange(id) {
    const acts = app.state?.activity || [];
    const word = new RegExp(`(^|[^\\w-])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^\\w-]|$)`);
    return [...acts].reverse().find((a) => a.tool === "edit" && a.ok && word.test(a.text || a.summary || ""));
  }
  function clipLabel(c) {
    if (c.label && c.label !== c.id) return c.label;
    const p = c.raw?.text || c.raw?.props?.title || c.raw?.props?.text;
    return typeof p === "string" ? p : null;
  }
  let clipOpen = storage("clip-json", false);
  async function copy(text, anchor) {
    try {
      await navigator.clipboard.writeText(text);
      note(anchor, t("clip.copied"));
    } catch {
      note(anchor, t("clip.copyFailed"), "is-error");
    }
  }
  function renderClip() {
    const id = app.selected;
    if (!id) {
      clipPane.replaceChildren(emptyState("i-target", t("clip.noneTitle"), t("clip.none")));
      return;
    }
    const f = findClip(id);
    if (!f) {
      clipPane.replaceChildren(emptyState("i-target", t("clip.goneTitle", { id }), app.viewing ? t("clip.notThen") : t("clip.missing")));
      return;
    }
    const { c, tr } = f;
    const fps = app.fps();
    const asset = c.asset ? (app.state.assets || []).find((a) => a.id === c.asset) : null;
    const cv = app.state.canvas || app.lastGood?.canvas;
    const label = clipLabel(c);
    const typeWord = has(`type.${c.type}`) ? t(`type.${c.type}`) : c.type;
    const timed = c.start != null && c.end != null;
    const changed = lastChange(c.id);
    const probs = (app.state.issues || []).filter((i) => i.clip === c.id);
    const flags = playback(c);

    const go = h("button", { type: "button", class: "text-btn mini" }, icon("i-jump"), h("span", { text: t("clip.go") }));
    disable(go, timed ? null : t("clip.noTime"), t("clip.goTip"));
    pressable(go, () => { app.seek(c.start); note(go, t("iss.went", { t: timecode(c.start, fps) })); });
    const ask = h("button", { type: "button", class: "text-btn mini accent" }, icon("i-chat"), h("span", { text: t("clip.ask") }));
    tip(ask, t("clip.askTip"));
    pressable(ask, () => { app.showPanel("chat"); app.emit("ask-about", c.id); });

    const json = h("pre", { class: "json" }, ...highlight(c.raw));
    const copyId = h("button", { type: "button", class: "icon-btn sm" }, icon("i-copy"));
    tip(copyId, t("clip.copyId"));
    pressable(copyId, () => copy(c.id, copyId));
    const copyJson = h("button", { type: "button", class: "text-btn mini" }, icon("i-copy"), h("span", { text: t("clip.copyJson") }));
    tip(copyJson, t("clip.copyJsonTip"));
    pressable(copyJson, () => copy(JSON.stringify(c.raw, null, 2), copyJson));
    const kids = [
      h("header", { class: "clip-head" },
        h("span", { class: "swatch", style: { background: typeColor(c.type) } }),
        h("span", { class: "clip-type", text: typeWord }),
        h("span", { class: "clip-id mono", text: c.id, title: c.id }), copyId),
      label ? h("p", { class: "clip-label", text: `“${label}”` }) : null,
      h("p", { class: "clip-lead" }, timed
        ? t("clip.onScreen", { a: timecode(c.start, fps), b: timecode(c.end, fps), d: `${(c.end - c.start).toFixed(2)} ${t("unit.s")}` })
        : t("clip.noTime")),
      h("div", { class: "clip-actions" }, go, ask),
      probs.length ? h("ul", { class: "iss-list clip-probs" }, ...probs.map(issueEl)) : null,
      asset?.missing ? h("p", { class: "missing-line" }, icon("i-alert"), t("as.missingAt", { path: asset.path })) : null,
      h("dl", { class: "kvs" },
        row(t("clip.track"), h("span", { text: tr.id, class: "mono" }), h("span", { class: "dim", text: has(`kind.${tr.kind}`) ? t(`kind.${tr.kind}`) : tr.kind })),
        timed ? row(t("clip.duration"), h("span", { class: "num", text: `${(c.end - c.start).toFixed(2)} ${t("unit.s")}` })) : null,
        flags.length ? row(t("clip.flags"), ...flags.map((s) => h("span", { class: "chip", text: s }))) : null,
        c.box && c.box !== "full" && cv ? row(t("clip.box"), boxView(c.box, cv)) : row(t("clip.box"), h("span", { text: t("clip.full") })),
        asset ? row(t("clip.asset"), assetPreview(asset)) : null,
        changed ? row(t("clip.changed"), h("span", { class: "num", text: clock(changed.ts) }), h("span", { class: "dim", text: describe(changed, fps).text })) : null,
        c.written ? row(t("clip.written"), h("span", { class: "mono dim", text: writtenText(c.written) })) : null),
      h("div", { class: "clip-json" },
        h("div", { class: "clip-json-head" },
          disclosure(t("clip.json"), json, clipOpen, (on) => { clipOpen = on; store("clip-json", on); }), copyJson),
        json),
    ];
    clipPane.replaceChildren(...kids.filter(Boolean));
  }

  function boxView(b, cv) {
    const W = 120, H = Math.round((W * cv.height) / cv.width);
    const s = W / cv.width;
    const out = b.x < 0 || b.y < 0 || b.x + b.w > cv.width || b.y + b.h > cv.height;
    return h("span", { class: "box-view" },
      h("span", { class: "box-frame", style: { width: `${W}px`, height: `${H}px` } },
        h("span", { class: `box-rect${out ? " is-out" : ""}`, style: { left: `${b.x * s}px`, top: `${b.y * s}px`, width: `${b.w * s}px`, height: `${b.h * s}px` } })),
      h("span", { class: "box-nums" },
        h("span", { class: "num", text: `${b.w} × ${b.h}` }),
        h("span", { class: "dim num", text: t("clip.at", { x: b.x, y: b.y }) }),
        out ? h("span", { class: "is-error", text: t("clip.outside") }) : null));
  }

  function thumbFor(a, hgt, cls) {
    if (a.missing) return h("span", { class: `${cls} is-missing` }, icon("i-alert"));
    if (!["image", "video", "evidence"].includes(a.kind)) return h("span", { class: `${cls} k-${a.kind}` }, icon(a.kind === "audio" ? "i-mic" : "i-box"));
    return h("span", { class: cls },
      h("img", { src: `${BASE}/api/thumb?asset=${encodeURIComponent(a.id)}&h=${hgt}`, alt: "", loading: "lazy",
        onerror: (e) => e.target.replaceWith(icon("i-pic", "thumb-gone")) }));
  }
  function assetMeta(a) {
    return [has(`ak.${a.kind}`) ? t(`ak.${a.kind}`) : a.kind, a.width ? `${a.width}×${a.height}` : null,
      a.duration ? `${a.duration.toFixed(1)} ${t("unit.s")}` : null].filter(Boolean).join(" · ");
  }
  function assetPreview(a) {
    return h("span", { class: "asset-inline" }, thumbFor(a, 144, "asset-pic"),
      h("span", {}, h("span", { class: "mono", text: a.id }), h("br"), h("span", { class: a.missing ? "is-error" : "dim", text: a.missing ? t("as.missing") : assetMeta(a) })));
  }

  function highlight(v) {
    const out = [];
    const json = JSON.stringify(v, null, 2) ?? "null";
    const re = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)|\b(true|false|null)\b/g;
    let last = 0, m;
    while ((m = re.exec(json))) {
      if (m.index > last) out.push(json.slice(last, m.index));
      if (m[1]) {
        out.push(h("span", { class: m[2] ? "j-key" : "j-str", text: m[1] }));
        if (m[2]) out.push(m[2]);
      } else if (m[3]) out.push(h("span", { class: "j-num", text: m[3] }));
      else out.push(h("span", { class: "j-lit", text: m[4] }));
      last = re.lastIndex;
    }
    out.push(json.slice(last));
    return out;
  }

  // ---------------------------------------------------------------- assets
  let assetsKey = "";
  function renderAssets() {
    const assets = app.state?.assets || [];
    const missing = assets.filter((a) => a.missing).length;
    assetCount.textContent = missing ? String(missing) : "";
    assetCount.className = `tab-count${missing ? " is-error" : ""}`;
    tip(assetCount, missing ? count("as.missingN", missing) : "");
    const key = JSON.stringify(assets);
    if (key === assetsKey) return;
    assetsKey = key;
    if (!assets.length) {
      assetsList.replaceChildren(emptyState("i-box", t("as.noneTitle"), t("as.none")));
      return;
    }
    const sorted = [...assets].sort((x, y) => (y.missing ? 1 : 0) - (x.missing ? 1 : 0));
    assetsList.replaceChildren(...[
      missing ? h("p", { class: "missing-line" }, icon("i-alert"), count("as.missingN", missing)) : null,
      h("ul", { class: "assets" }, ...sorted.map((a) => h("li", { class: `asset${a.missing ? " is-missing" : ""}` },
        thumbFor(a, 72, "asset-thumb"),
        h("span", { class: "asset-info" },
          h("span", { class: "asset-name" }, h("span", { class: "mono", text: a.id, title: a.id }),
            a.missing ? h("span", { class: "chip is-error", text: t("as.missing") }) : null),
          h("span", { class: "dim small", text: assetMeta(a) }),
          h("span", { class: `small ${a.missing ? "is-error" : "faint"}`, text: a.path, title: a.path }),
          h("span", { class: "asset-users" },
            a.used_by?.length
              ? [h("span", { class: "faint small", text: t("as.usedBy") }), ...a.used_by.map((id) => {
                const b = h("button", { type: "button", class: "chip mono is-link", text: id });
                tip(b, t("as.showClip", { id }));
                pressable(b, () => {
                  if (app.viewing) app.backToNow();
                  app.select(id);
                  app.seekToClip(id);
                  note(b, t("iss.selected", { id }));
                });
                return b;
              })]
              : h("span", { class: "faint small", text: t("as.unused") }))))))].filter(Boolean));
  }

  // ---------------------------------------------------------------- the picture viewer
  const lightbox = (() => {
    const dlg = $("lightbox"), img = $("lbImg");
    let pics = [], at = 0, opener = null;
    const prev = $("lbPrev"), next = $("lbNext"), close = $("lbClose");
    tip(close, t("pic.close"), "Esc");
    function render() {
      const p = pics[at];
      img.src = p.url;
      img.alt = p.label;
      $("lbTitle").textContent = p.label;
      $("lbCount").textContent = pics.length > 1 ? `${at + 1} / ${pics.length}` : "";
      const cap = $("lbCap");
      cap.replaceChildren(h("span", { class: "mono dim", text: p.path }));
      if (p.t != null) {
        const go = h("button", { type: "button", class: "text-btn mini accent" }, icon("i-jump"), h("span", { text: t("pic.goto", { t: timecode(p.t, app.fps()) }) }));
        tip(go, t("pic.gotoTip"));
        pressable(go, () => { dlg.close(); if (app.viewing) app.backToNow(); app.seek(p.t); });
        cap.append(go);
      }
      disable(prev, at === 0 ? t("pic.first") : null, t("pic.prev"), "←");
      disable(next, at === pics.length - 1 ? t("pic.last") : null, t("pic.next"), "→");
      prev.hidden = next.hidden = pics.length < 2;
    }
    const go = (d) => { const n = clamp(at + d, 0, pics.length - 1); if (n !== at) { at = n; render(); } };
    pressable(prev, () => go(-1));
    pressable(next, () => go(1));
    pressable(close, () => dlg.close());
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); go(e.key === "ArrowLeft" ? -1 : 1); }
      else if (e.key === "Home") { e.preventDefault(); at = 0; render(); }
      else if (e.key === "End") { e.preventDefault(); at = pics.length - 1; render(); }
      e.stopPropagation();          // the window's own shortcuts wait while the picture is open
    });
    closeOnBackdrop(dlg);
    dlg.addEventListener("close", () => { img.removeAttribute("src"); opener?.isConnected && opener.focus(); });
    return {
      open(list, i, from) {
        pics = list; at = i; opener = from;
        render();
        dlg.showModal();
        close.focus();
      },
    };
  })();

  // ---------------------------------------------------------------- hooks
  app.on("state", () => { renderReplay(); renderIssues(); renderAssets(); renderClip(); app.emit("steps"); });
  app.on("view", () => { renderReplay(); renderClip(); app.emit("steps"); });
  app.on("select", renderClip);
  app.on("replay", renderReplay);

  renderIntro();
  show("chat", false);
  return { show, current: () => current, touched: () => touched, steps, lightbox };
}
