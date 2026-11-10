import { t } from "./i18n.js";
import { bytes, clock, h, timecode, typeColor, writtenText } from "./util.js";

const TABS = ["activity", "issues", "clip", "assets"];

export function createPanel(app) {
  const tabButtons = TABS.map((k) => document.getElementById(`tab-${k}`));
  const panes = TABS.map((k) => document.getElementById(`pane-${k}`));
  const feed = document.getElementById("feed");
  const replay = document.getElementById("replay");
  const replayRange = document.getElementById("replayRange");
  const replayLabel = document.getElementById("replayLabel");
  const replayPlay = document.getElementById("replayPlay");
  const issuesList = document.getElementById("issuesList");
  const clipPane = document.getElementById("clipBody");
  const assetsList = document.getElementById("assetsList");
  const issueCount = document.getElementById("issueCount");

  let current = 0;
  function show(i) {
    current = i;
    tabButtons.forEach((b, k) => {
      b.setAttribute("aria-selected", String(k === i));
      b.tabIndex = k === i ? 0 : -1;
    });
    panes.forEach((p, k) => { p.hidden = k !== i; });
    if (i === 0) stickBottom(true);
  }
  tabButtons.forEach((b, i) => {
    b.addEventListener("click", () => show(i));
    b.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        e.stopPropagation();
        const n = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
        show(n);
        tabButtons[n].focus();
      }
    });
  });

  // ---------------------------------------------------------------- activity
  let atBottom = true;
  feed.addEventListener("scroll", () => { atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 24; });
  function stickBottom(force) {
    if (force || atBottom) feed.scrollTop = feed.scrollHeight;
  }

  let feedKey = "";
  function renderActivity() {
    const acts = app.state?.activity || [];
    const viewing = app.viewing?.n ?? null;
    const key = `${acts.length}:${acts.at(-1)?.ts}:${viewing}:${app.state?.revision}`;
    if (key === feedKey) return;
    feedKey = key;
    if (!acts.length) {
      feed.replaceChildren(h("p", { class: "empty-note", text: t("act.empty") }));
      return;
    }
    const items = acts.map((a) => {
      const body = [
        h("span", { class: "act-time", text: clock(a.ts) }),
        h("span", { class: `act-tool tool-${a.tool}`, text: a.tool }),
        h("span", { class: "act-sum", text: a.summary, title: a.summary }),
        h("span", { class: "act-secs", text: a.seconds != null ? `${a.seconds < 10 ? a.seconds.toFixed(1) : Math.round(a.seconds)} s` : "" }),
      ];
      const cls = `act${a.ok ? "" : " is-fail"}${a.batch != null && a.batch === viewing ? " is-viewing" : ""}`;
      if (a.batch != null) {
        return h("li", { class: cls },
          h("button", { class: "act-btn", type: "button", title: `${t("act.open")} (${t("act.batch", { n: a.batch })})`,
            onclick: () => app.viewHistory(a.batch) }, ...body));
      }
      return h("li", { class: cls }, h("div", { class: "act-btn is-static" }, ...body,
        a.ok ? null : h("span", { class: "sr-only", text: t("act.failed") })));
    });
    feed.replaceChildren(h("ol", { class: "act-list" }, ...items));
    stickBottom(false);
  }

  function renderReplay() {
    const hist = app.state?.history || [];
    replay.hidden = !hist.length;
    if (!hist.length) return;
    replayRange.max = String(hist.length);
    const idx = app.viewing ? hist.findIndex((x) => x.n === app.viewing.n) : hist.length;
    replayRange.value = String(idx < 0 ? hist.length : idx);
    const pct = (Number(replayRange.value) / hist.length) * 100;
    replayRange.style.setProperty("--fill", `${pct}%`);
    replayLabel.textContent = app.viewing ? `${t("act.batch", { n: app.viewing.n })} / ${hist.at(-1).n}` : t("act.now");
    replayPlay.setAttribute("aria-pressed", String(!!app.replaying));
    replayPlay.title = app.replaying ? t("act.stopReplay") : t("act.playReplay");
    replayPlay.setAttribute("aria-label", replayPlay.title);
  }
  replayRange.addEventListener("input", () => {
    const hist = app.state?.history || [];
    const i = Number(replayRange.value);
    if (i >= hist.length) app.backToNow(); else app.viewHistory(hist[i].n);
  });
  document.getElementById("replayPrev").addEventListener("click", () => app.stepHistory(-1));
  document.getElementById("replayNext").addEventListener("click", () => app.stepHistory(1));
  replayPlay.addEventListener("click", () => app.toggleReplay());

  // ---------------------------------------------------------------- issues
  function renderIssues() {
    const issues = app.state?.issues || [];
    const errors = issues.filter((i) => i.level === "error").length;
    issueCount.textContent = issues.length ? String(issues.length) : "";
    issueCount.className = `tab-count${errors ? " is-error" : ""}`;
    if (!issues.length) {
      issuesList.replaceChildren(h("p", { class: "empty-note", text: t("iss.none") }));
      return;
    }
    const groups = ["error", "warning", "advice"].map((lv) => {
      const list = issues.filter((i) => i.level === lv);
      if (!list.length) return null;
      return h("section", { class: "iss-group" },
        h("h3", { class: `iss-head lv-${lv}` }, h("span", { class: "lv-dot" }), t(`iss.${lv}`), h("span", { class: "iss-n", text: String(list.length) })),
        h("ul", { class: "iss-list" }, ...list.map((is) => h("li", {},
          h("button", { type: "button", class: `iss lv-${is.level}`, onclick: () => app.openIssue(is) },
            h("span", { class: "iss-text", text: is.text }),
            h("span", { class: "iss-meta" },
              is.t != null ? h("span", { class: "chip mono", text: timecode(is.t, app.fps()) }) : null,
              is.clip ? h("span", { class: "chip mono", text: is.clip }) : null,
              h("span", { class: "chip", text: is.source })))))));
    });
    issuesList.replaceChildren(...groups.filter(Boolean));
  }

  // ---------------------------------------------------------------- clip
  function findClip(id) {
    for (const tr of app.view().tracks || []) for (const c of tr.clips || []) if (c.id === id) return { c, tr };
    return null;
  }
  function row(label, ...value) {
    return h("div", { class: "kv" }, h("dt", { text: label }), h("dd", {}, ...value));
  }
  function renderClip() {
    const id = app.selected;
    if (!id) {
      clipPane.replaceChildren(h("p", { class: "empty-note", text: t("clip.none") }));
      return;
    }
    const f = findClip(id);
    if (!f) {
      clipPane.replaceChildren(h("p", { class: "empty-note" }, h("span", { class: "mono", text: id }), " · ", t("clip.missing")));
      return;
    }
    const { c, tr } = f;
    const fps = app.fps();
    const flags = [];
    if (c.rate != null) flags.push(`rate ${c.rate}`);
    if (c.reverse) flags.push("reverse");
    if (c.hold != null) flags.push(`hold ${c.hold}`);
    if (c.volume != null) flags.push(`volume ${c.volume}`);
    if (c.loop) flags.push("loop");
    if (c.transition) flags.push(`${c.transition.type} ${c.transition.dur} s`);
    if (c.enter) flags.push(`enter ${c.enter.preset} ${c.enter.dur} s`);
    if (c.exit) flags.push(`exit ${c.exit.preset} ${c.exit.dur} s`);
    for (const [k, v] of Object.entries(c.keyframes || {})) flags.push(`${k} ◆${v.length}`);
    const asset = c.asset ? (app.state.assets || []).find((a) => a.id === c.asset) : null;
    const cv = app.state.canvas;

    const kids = [
      h("header", { class: "clip-head" },
        h("span", { class: "swatch", style: { background: typeColor(c.type) } }),
        h("span", { class: "clip-id mono", text: c.id }),
        h("span", { class: "clip-type", text: `${c.type} · ${tr.id}` })),
      c.label && c.label !== c.id ? h("p", { class: "clip-label", text: c.label }) : null,
      h("dl", { class: "kvs" },
        row(t("clip.times"), h("span", { class: "mono", text: `${timecode(c.start, fps)} – ${timecode(c.end, fps)}` }),
          h("span", { class: "dim", text: `  ${(c.end - c.start).toFixed(2)} s` })),
        row(t("clip.written"), h("span", { class: "mono", text: writtenText(c.written) })),
        flags.length ? row(t("clip.flags"), ...flags.map((s) => h("span", { class: "chip mono", text: s }))) : null,
        row(t("clip.box"), c.box === "full" || !c.box ? t("clip.full") : boxView(c.box, cv)),
        asset ? row(t("clip.asset"), assetPreview(asset)) : null),
      h("h3", { class: "sub-head", text: t("clip.json") }),
      h("pre", { class: "json" }, ...highlight(c.raw)),
    ];
    clipPane.replaceChildren(...kids.filter(Boolean));
  }

  function boxView(b, cv) {
    const W = 120, H = Math.round((W * cv.height) / cv.width);
    const s = W / cv.width;
    return h("span", { class: "box-view" },
      h("span", { class: "box-frame", style: { width: `${W}px`, height: `${H}px` } },
        h("span", { class: "box-rect", style: { left: `${b.x * s}px`, top: `${b.y * s}px`, width: `${b.w * s}px`, height: `${b.h * s}px` } })),
      h("span", { class: "mono", text: `x ${b.x}  y ${b.y}\nw ${b.w}  h ${b.h}` }));
  }

  function assetPreview(a) {
    const meta = [a.kind, a.width ? `${a.width}×${a.height}` : null, a.duration ? `${a.duration.toFixed(2)} s` : null].filter(Boolean).join(" · ");
    const pic = ["image", "video", "evidence"].includes(a.kind)
      ? h("img", { class: "asset-pic", src: `/api/thumb?asset=${encodeURIComponent(a.id)}&h=144`, alt: a.id, loading: "lazy" })
      : null;
    return h("span", { class: "asset-inline" }, pic,
      h("span", {}, h("span", { class: "mono", text: a.id }), h("br"), h("span", { class: "dim", text: meta })));
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
    const key = JSON.stringify(assets);
    if (key === assetsKey) return;
    assetsKey = key;
    if (!assets.length) {
      assetsList.replaceChildren(h("p", { class: "empty-note", text: t("as.none") }));
      return;
    }
    assetsList.replaceChildren(h("ul", { class: "assets" }, ...assets.map((a) => {
      const visual = ["image", "video", "evidence"].includes(a.kind);
      const meta = [a.width ? `${a.width}×${a.height}` : null, a.duration ? `${a.duration.toFixed(2)} s` : null].filter(Boolean).join(" · ");
      return h("li", { class: "asset" },
        h("span", { class: `asset-thumb k-${a.kind}` },
          visual ? h("img", { src: `/api/thumb?asset=${encodeURIComponent(a.id)}&h=72`, alt: "", loading: "lazy" })
            : h("span", { class: "asset-glyph", text: a.kind === "audio" ? "♪" : "·" })),
        h("span", { class: "asset-info" },
          h("span", { class: "asset-name" }, h("span", { class: "mono", text: a.id }), h("span", { class: "chip", text: a.kind })),
          h("span", { class: "dim small", text: meta || a.path, title: a.path }),
          h("span", { class: "asset-users" },
            a.used_by?.length
              ? a.used_by.map((id) => h("button", { type: "button", class: "chip mono is-link", text: id, onclick: () => { app.select(id); app.seekToClip(id); } }))
              : h("span", { class: "dim small", text: t("as.unused") }))));
    })));
  }

  // ---------------------------------------------------------------- hooks
  app.on("state", () => { renderActivity(); renderReplay(); renderIssues(); renderAssets(); renderClip(); });
  app.on("view", () => { renderActivity(); renderReplay(); renderClip(); });
  app.on("select", renderClip);
  app.on("replay", renderReplay);

  show(0);
  return { show, current: () => current };
}
