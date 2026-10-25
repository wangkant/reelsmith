// Renderer self-test: stills + inspect on test/basic.resolved.json, word-aware text layout and evidence crops
// (layout.resolved.json), transitions between clips (cuts.resolved.json), sound curves and ducking, a film with
// looping video and audio (video.resolved.json), the import guard, context narrowing, component crashes, word-by-word
// captions, transient failures, parallel calls and argument errors. Offline; needs ffmpeg on PATH;
// ~3-4 minutes (each case bundles once).
//   node test/selftest.mjs [--keep <dir>]     (--keep leaves the stills there to look at)
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const RENDER = path.join(ROOT, "scripts", "render.mjs");
const keepAt = process.argv.indexOf("--keep");
const OUT = keepAt > 0 ? path.resolve(process.argv[keepAt + 1]) : fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-selftest-"));
fs.mkdirSync(OUT, { recursive: true });

let failures = 0;
const check = (cond, what) => {
  if (cond) console.log(`  ok   ${what}`);
  else {
    failures++;
    console.log(`  FAIL ${what}`);
  }
};

const run = (args, env = {}) => {
  const t0 = Date.now();
  const r = spawnSync(process.execPath, [RENDER, ...args], {
    cwd: ROOT, encoding: "utf8", env: { ...process.env, REELSMITH_LIBRARY: "", ...env }, timeout: 10 * 60 * 1000,
  });
  const lines = (r.stdout || "").trim().split("\n");
  let result = null;
  try {
    result = JSON.parse(lines[lines.length - 1]);
  } catch {
    result = null;
  }
  return { code: r.status, result, stdout: r.stdout || "", stderr: r.stderr || "", s: ((Date.now() - t0) / 1000).toFixed(1) };
};

const lastJson = (stdout) => {
  const lines = (stdout || "").trim().split("\n");
  try {
    return JSON.parse(lines[lines.length - 1]);
  } catch {
    return null;
  }
};

/** The same as run(), without blocking: for calls that must overlap. */
const runAsync = (args, env = {}) =>
  new Promise((resolve) => {
    const t0 = Date.now();
    const p = spawn(process.execPath, [RENDER, ...args], { cwd: ROOT, env: { ...process.env, REELSMITH_LIBRARY: "", ...env } });
    let stdout = "";
    p.stdout.on("data", (d) => (stdout += d));
    p.stderr.on("data", () => undefined);
    p.on("close", (code) => resolve({ code, result: lastJson(stdout), stdout, s: ((Date.now() - t0) / 1000).toFixed(1) }));
  });

/** RGB bytes of a w x h region of an image, or of frame `n` of a video. */
const pixels = (file, x, y, w, h, n = null) => {
  const pick = n === null ? [] : ["-vf", `select=eq(n\\,${n}),crop=${w}:${h}:${x}:${y}`, "-frames:v", "1"];
  const crop = n === null ? ["-vf", `crop=${w}:${h}:${x}:${y}`] : [];
  const r = spawnSync("ffmpeg", ["-v", "error", "-i", file, ...pick, ...crop, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], {
    maxBuffer: 64 * 1024 * 1024,
  });
  return r.stdout && r.stdout.length === w * h * 3 ? r.stdout : null;
};
const mean = (buf) => {
  if (!buf) return [NaN, NaN, NaN];
  const s = [0, 0, 0];
  for (let i = 0; i < buf.length; i++) s[i % 3] += buf[i];
  return s.map((v) => v / (buf.length / 3));
};
const darkest = (buf) => {
  let m = 255;
  for (let i = 0; buf && i < buf.length; i += 3) m = Math.min(m, (buf[i] + buf[i + 1] + buf[i + 2]) / 3);
  return m;
};
const diff = (a, b) => {
  if (!a || !b || a.length !== b.length) return NaN;
  let s = 0;
  for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return s / a.length;
};

const pngSize = (file) => {
  const b = fs.readFileSync(file);
  return b.toString("ascii", 12, 16) === "IHDR" ? [b.readUInt32BE(16), b.readUInt32BE(20)] : null;
};

const isRect = (r) => Array.isArray(r) && r.length === 4 && r.every((v) => typeof v === "number" && Number.isFinite(v));

const fixture = path.join(HERE, "basic.resolved.json");
const library = path.join(HERE, "library");
const basic = JSON.parse(fs.readFileSync(fixture, "utf8"));
const boxOf = (id) => basic.tracks.flatMap((t) => t.clips ?? []).find((c) => c.id === id)?.box;

// ------------------------------------------------------------------ stills
console.log("stills");
{
  const frames = [0, 12, 45, 64, 100, 119, 500];
  const r = run(["stills", fixture, HERE, path.join(OUT, "stills"), ...frames.map(String)], { REELSMITH_LIBRARY: library });
  console.log(`  (${r.s} s)`);
  check(r.code === 0 && r.result?.ok === true, `stills ok (${r.result?.error ?? ""})`);
  const files = r.result?.files ?? [];
  check(files.length === 6, `6 distinct stills (frame 500 clamps to 119): got ${files.length}`);
  check(files.every((f) => fs.existsSync(f) && String(pngSize(f)) === "1080,1920"), "every still is a 1080x1920 png");
  check((r.result?.notes ?? []).some((n) => n.includes("past the end")), "a note says frame 500 was past the end");
  check(JSON.stringify(r.result?.components) === JSON.stringify(["Badge", "CountUp", "Stamp"]), "components used are listed");
  check((r.result?.browserErrors ?? []).length === 0, `no browser errors ${JSON.stringify(r.result?.browserErrors ?? [])}`);
  check(!r.stdout.includes("@@inspect"), "stdout carries no @@inspect lines");
}

// ------------------------------------------------------------------ inspect
console.log("inspect");
{
  const r = run(["inspect", fixture, HERE, path.join(OUT, "inspect"), "12", "64"], { REELSMITH_LIBRARY: library });
  console.log(`  (${r.s} s)`);
  check(r.code === 0 && r.result?.ok === true, `inspect ok (${r.result?.error ?? ""})`);
  check(!r.stdout.includes("@@inspect"), "the @@inspect lines are not echoed on stdout");
  const file = path.join(OUT, "inspect", "inspect.json");
  const data = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { frames: [] };
  check(r.result?.inspect === file, "result names inspect.json");
  check(Array.isArray(data.frames) && data.frames.length === 2, "two frames in inspect.json");
  const shapeOk = data.frames.every((fr) =>
    Number.isInteger(fr.frame) && typeof fr.png === "string" && fs.existsSync(fr.png) && Array.isArray(fr.items) &&
    fr.items.every((it) =>
      typeof it.clip === "string" && it.clip && typeof it.track === "string" && it.track && ["clip", "text"].includes(it.kind) &&
      isRect(it.rect) && typeof it.opacity === "number" && it.opacity > 0 && it.opacity <= 1 &&
      (it.kind === "clip" ? it.text === undefined : typeof it.text === "string" && [...it.text].length <= 24 && it.text.length > 0)));
  check(shapeOk, "every frame is {frame, png, items} and every item {clip, track, kind, rect[4], opacity, text?}");
  const at = (f) => data.frames.find((x) => x.frame === f)?.items ?? [];
  const f12 = at(12);
  const f64 = at(64);
  const item = (items, clip, kind) => items.filter((i) => i.clip === clip && i.kind === kind);
  check(JSON.stringify(item(f12, "photo", "clip")[0]?.rect) === "[0,0,1080,1920]", "the background clip covers the canvas");
  check(!f12.some((i) => i.clip === "ghost1"), "a hidden track is not rendered");
  check(!f12.some((i) => i.clip === "ev") && item(f64, "ev", "clip").length === 1, "a clip shows only inside its time range");
  check(item(f12, "sub", "text").some((i) => i.opacity < 1), "a revealing text has a partly faded node");
  check(item(f12, "note", "clip")[0]?.opacity === 0.5 && item(f12, "note", "text")[0]?.opacity === 0.5, "clip opacity reaches its text");
  check(item(f12, "cap", "text").map((i) => i.text).join("") === "油价又涨了", "caption item 1 at frame 12");
  check(item(f64, "cap", "text").map((i) => i.text).join("") === "每吨汽油涨了215元", "caption item 2 at frame 64, runs kept apart");
  check(item(f64, "stamp", "text").some((i) => i.text === "LIB"), "a library component shadows the preset of the same name");
  check(item(f64, "badge", "text")[0]?.text === "NEW", "a library component with kit and relative imports renders");
  check(item(f64, "count", "text").some((i) => i.text === "215"), "a preset component renders (CountUp lands on 215)");
  const tb = boxOf("title");
  const titleText = item(f64, "title", "text");
  check(titleText.length >= 2 && titleText.every((i) => i.rect[1] >= tb.y - 1 && i.rect[1] + i.rect[3] <= tb.y + tb.h + 1 &&
    i.rect[0] >= tb.x - 1 && i.rect[0] + i.rect[2] <= tb.x + tb.w + 1), "fitted, balanced title stays inside its box");
  check(titleText.map((i) => i.text).join("").startsWith("油价"), "title text starts with its accent run");
  const lines = new Set(titleText.map((i) => Math.round(i.rect[1])));
  check(lines.size === 2, `balanced title sits on two lines (${[...lines].join(", ")})`);
  const texts = data.frames.flatMap((fr) => fr.items.filter((i) => i.kind === "text"));
  check(texts.length > 0 && texts.every((i) => typeof i.size === "number" && i.size > 0 && /^rgba?\(/.test(i.color ?? "")),
    "text items carry their computed size (px) and colour");
  check(item(f64, "cap", "text").some((i) => i.color === "rgb(255, 255, 255)") &&
    item(f64, "cap", "text").some((i) => i.color === "rgb(217, 164, 65)"), "caption text is white with a gold accent run");
  check(data.frames.every((fr) => fr.items.filter((i) => i.kind === "clip").every((i) => i.size === undefined && i.color === undefined)),
    "clip items have no size or colour");
}

// ------------------------------------------------------------------ keyframes, presets, reveal (motion.resolved.json)
console.log("motion");
{
  const motion = path.join(HERE, "motion.resolved.json");
  const r = run(["inspect", motion, HERE, path.join(OUT, "motion"), "5", "10", "20", "59"]);
  console.log(`  (${r.s} s)`);
  check(r.code === 0 && r.result?.ok === true, `inspect ok (${r.result?.error ?? ""})`);
  const file = path.join(OUT, "motion", "inspect.json");
  const data = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { frames: [] };
  const get = (f, clip, kind = "clip") => (data.frames.find((x) => x.frame === f)?.items ?? []).filter((i) => i.clip === clip && i.kind === kind);
  const rect = (f, clip) => get(f, clip)[0]?.rect ?? [NaN, NaN, NaN, NaN];
  check(rect(5, "lin")[0] === 150 && rect(10, "lin")[0] === 200 && rect(20, "lin")[0] === 300, "linear x: 150, 200, 300 at frames 5, 10, 20");
  check(rect(10, "stp")[1] === 250 && rect(20, "stp")[1] === 450, "step y holds 250 until frame 20, then 450");
  check(rect(10, "ein")[0] === 125 && rect(10, "eout")[0] === 275, "ease in / out at the midpoint: 125 and 275");
  check(rect(10, "size")[2] === 150 && rect(10, "size")[3] === 150, "keyframed w/h: 150 x 150 at the midpoint");
  check(rect(10, "spr")[0] > 300 && rect(20, "spr")[0] === 300 && rect(59, "spr")[0] === 300, "spring overshoots, then lands on 300");
  check(get(10, "op")[0]?.opacity === 0.5, "opacity keyframes: 0.5 at the midpoint");
  check(get(5, "fade")[0]?.opacity === 0.875, "fade enter: ease-out 0.875 halfway");
  check(get(59, "fade").length === 0 || get(59, "fade")[0].opacity < 0.05, "fade clip gone on its last frame (rise exit)");
  check(get(10, "words", "text").some((i) => i.opacity > 0 && i.opacity < 1), "words reveal: a word mid-fade at frame 10");
  check(get(5, "lines", "text").map((i) => i.text).join("|") === "第一行" && get(20, "lines", "text").length === 2, "lines reveal: one line, then two");
  const all = data.frames.flatMap((x) => x.items);
  check(all.length > 0 && all.every((i) => Math.round(i.opacity * 1000) === i.opacity * 1000), "opacities are rounded to 3 decimals");
  check(get(10, "cap", "clip")[0]?.rect.join(",") === "40,1260,840,200", "captions without a box sit in the bottom 200 px of the safe area");
}

// ------------------------------------------------------------------ guard, narrowing, missing component, args
const mini = (clips) => ({
  version: 2, fps: 30, width: 540, height: 960, durationInFrames: 10, safe: { x: 20, y: 110, w: 420, h: 620 },
  theme: basic.theme, tracks: [{ id: "v", kind: "visual", clips }], audio: [], inspect: false,
});
const comp = (id, name) => ({
  id, type: "component", track: "v", from: 0, dur: 10, box: { x: 0, y: 0, w: 540, h: 960 }, style: {}, keyframes: {},
  enter: null, exit: null, content: { name, props: {} },
});
const writeMini = (name, clips) => {
  const dir = path.join(OUT, name);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, "resolved.json");
  fs.writeFileSync(file, JSON.stringify(mini(clips)));
  return { dir, file };
};
const badlib = path.join(HERE, "badlib");

console.log("import guard");
{
  const a = writeMini("guard-escape", [comp("c", "Escape")]);
  const r1 = run(["stills", a.file, a.dir, path.join(a.dir, "out"), "0"], { REELSMITH_LIBRARY: badlib });
  check(r1.code === 1 && r1.result?.ok === false && r1.result?.stage === "bundle", `a library import outside its folder fails the bundle (${r1.s} s)`);
  check((r1.result?.error ?? "").startsWith("Component Escape imports '../../src/fonts' (it leaves the component folder): only react"),
    `the error names the component, the import and the rule: ${r1.result?.error ?? ""}`);
  const b = writeMini("guard-pkg", [comp("c", "Pkg")]);
  const r2 = run(["stills", b.file, b.dir, path.join(b.dir, "out"), "0"], { REELSMITH_LIBRARY: badlib });
  check(r2.result?.ok === false && /Component Pkg imports 'react-dom'/.test(r2.result?.error ?? ""), `a package outside the allowed list fails (${r2.s} s)`);
  // run the escape case again: the webpack cache must not let it through
  const r3 = run(["stills", a.file, a.dir, path.join(a.dir, "out"), "0"], { REELSMITH_LIBRARY: badlib });
  check(r3.result?.ok === false && r3.result?.stage === "bundle", `still refused on a cached rebuild (${r3.s} s)`);
  // a node built-in cannot even resolve: refused by name before webpack prints its resolve trace
  const g = writeMini("guard-fs", [comp("c", "UsesFs")]);
  const r4 = run(["stills", g.file, g.dir, path.join(g.dir, "out"), "0"], { REELSMITH_LIBRARY: badlib });
  check(r4.result?.stage === "bundle" && r4.result?.error ===
    "Component UsesFs imports 'fs': only react, remotion, @remotion/*, @reelsmith/kit and files in the same folder are allowed",
  `an unresolvable forbidden import is refused by name, without a resolve trace (${r4.s} s): ${r4.result?.error ?? ""}`);
}

console.log("narrowing, missing and crashing components");
{
  const c = writeMini("narrow", [comp("c", "Stamp")]);
  const r1 = run(["stills", c.file, c.dir, path.join(c.dir, "out"), "5"], { REELSMITH_LIBRARY: badlib });
  check(r1.result?.ok === true, `unused broken library components do not break a film (${r1.s} s) ${r1.result?.error ?? ""}`);
  const d = writeMini("missing", [comp("c", "NoSuchThing")]);
  const r2 = run(["stills", d.file, d.dir, path.join(d.dir, "out"), "5"]);
  check(r2.result?.ok === false && r2.result?.stage === "component" && r2.result?.component === "NoSuchThing" &&
    /^component "NoSuchThing" not found/.test(r2.result?.error ?? ""), `stills fail on a missing component, stage component (${r2.s} s)`);
  // a crash is the component's own failure with its source line, in every mode; never a layout item
  const e = writeMini("crash", [comp("c", "Crash")]);
  for (const mode of ["stills", "inspect", "film"]) {
    const out = mode === "film" ? path.join(e.dir, "crash.mp4") : path.join(e.dir, mode);
    const r = run(mode === "film" ? [mode, e.file, e.dir, out] : [mode, e.file, e.dir, out, "3"], { REELSMITH_LIBRARY: badlib });
    const err = r.result?.error ?? "";
    check(r.result?.ok === false && r.result?.stage === "component" && r.result?.component === "Crash" &&
      /badlib\/Crash\.tsx:5$/.test(r.result?.source ?? "") &&
      err.startsWith("component Crash crashed at test/badlib/Crash.tsx:5: TypeError: Cannot read properties of undefined") &&
      !/JSHandle|bundle\.js/.test(err + JSON.stringify(r.result?.browserErrors ?? [])),
    `${mode}: a crashing component is reported as itself with file:line (${r.s} s): ${err.split("\n")[0]}`);
  }
}

console.log("word-by-word captions");
{
  const words = [{ from: 0, to: 10, chars: [0, 3] }, { from: 10, to: 20, chars: [4, 7] }, { from: 20, to: 30, chars: [8, 13] }];
  const cap = (id, mode, y) => ({
    id, kind: "captions", mode, box: { x: 20, y, w: 500, h: 90 }, style: {},
    items: [{ from: 0, to: 30, runs: [{ text: "one two three", accent: false }], words }],
  });
  const dir = path.join(OUT, "words");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, "resolved.json");
  fs.writeFileSync(file, JSON.stringify({
    ...mini([]), durationInFrames: 30, tracks: [cap("kw", "words", 100), cap("kb", "build", 300), cap("kp", "phrase", 500)],
  }));
  const r = run(["inspect", file, dir, path.join(dir, "out"), "5", "15", "25"]);
  check(r.code === 0 && r.result?.ok === true, `inspect ok (${r.s} s) ${r.result?.error ?? ""}`);
  const insp = path.join(dir, "out", "inspect.json");
  const data = fs.existsSync(insp) ? JSON.parse(fs.readFileSync(insp, "utf8")) : { frames: [] };
  const texts = (f, clip) => (data.frames.find((x) => x.frame === f)?.items ?? []).filter((i) => i.clip === clip && i.kind === "text");
  const colour = (f, clip, word) => texts(f, clip).find((i) => i.text === word)?.color;
  const GOLD = "rgb(217, 164, 65)";
  const WHITE = "rgb(255, 255, 255)";
  check(colour(5, "kw", "one") === GOLD && colour(5, "kw", "two three") === WHITE,
    `words: the first word is lit while it is said ${JSON.stringify(texts(5, "kw").map((i) => [i.text, i.color]))}`);
  check(colour(15, "kw", "two") === GOLD && colour(15, "kw", "one") === WHITE && colour(15, "kw", "three") === WHITE,
    "words: then the second, and the first goes back to white");
  check(texts(5, "kb").map((i) => i.text).join("|") === "one" && texts(15, "kb").map((i) => i.text).join("|") === "one two" &&
    texts(25, "kb").map((i) => i.text).join("|") === "one two three", "build: words appear as they are said");
  const left = (f) => texts(f, "kb")[0]?.rect[0];
  check(left(5) !== undefined && Math.abs(left(5) - left(25)) <= 1, "build: the phrase is laid out whole, so nothing moves");
  check(texts(15, "kp").map((i) => `${i.text} ${i.color}`).join("|") === `one two three ${WHITE}`, "phrase: the item shows whole");
}

console.log("word-aware line breaking (unit)");
{
  const { pieces, breakLines } = await import("../src/elements/linebreak.ts");
  const glued = (s) => pieces(s).filter((p) => !p.space).map((p) => p.text);
  const has = (s, ...want) => want.every((w) => glued(s).includes(w));
  check(has("按92号汽油密度0.725换算，一吨大约1370升，个税按偶然所得20%扣，到手大约九千三百七十一元。", "0.725", "1370升，", "20%", "九千三百七十一元。"),
    "numbers keep their digits, units and punctuation");
  check(has("iPhone 17 Pro 售价 8999 元，比去年贵了 12%", "8999 元，", "12%"), "a number keeps its unit across one space");
  check(has("比上年名义增长百分之五", "百分之五"), "百分之 stays with its numeral");
  check(has("第3名，约1.5万公里（含税）", "第3名，", "1.5万公里"), "第, 万 and a two-character unit stay with the number");
  const quote = glued("他说：“这不对。”然后走了");
  check(quote.every((p) => !/^[”’）)》」』，。、]/.test(p)), `no piece starts with closing punctuation (${quote.join(" | ")})`);
  const byChar = (s) => [...s].length;
  const lines = breakLines("按92号汽油密度0.725换算，一吨大约1370升，个税按偶然所得20%扣，到手大约九千三百七十一元。", 9, byChar);
  check(lines.every((l) => byChar(l) <= 9 || !/\S\s?\S/.test(l)) && lines.join("") ===
    "按92号汽油密度0.725换算，一吨大约1370升，个税按偶然所得20%扣，到手大约九千三百七十一元。" &&
    !lines.some((l, i) => i > 0 && /[0-9]$/.test(lines[i - 1]) && /^[0-9%元升.]/.test(l)), `greedy lines never split a number (${lines.join(" / ")})`);
  check(lines.some((l) => /，$/.test(l)), "a line ends at a comma when one is near");
  const two = breakLines("iPhone 17 Pro 售价 8999 元，比去年贵了 12%", 20, byChar, true);
  check(two.length === 2 && !two.some((l) => /^元/.test(l)) && Math.abs(byChar(two[0]) - byChar(two[1])) <= 8,
    `balanced lines stay even and keep 8999 元 together (${two.join(" / ")})`);
}

console.log("text layout, default colour, fonts and evidence crops (layout.resolved.json)");
{
  const fx = path.join(HERE, "layout.resolved.json");
  const r = run(["inspect", fx, HERE, path.join(OUT, "layout"), "2", "20", "59", "90"]);
  console.log(`  (${r.s} s)`);
  check(r.code === 0 && r.result?.ok === true, `inspect ok (${r.result?.error ?? ""})`);
  const file = path.join(OUT, "layout", "inspect.json");
  const data = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { frames: [] };
  const texts = (f, clip) => (data.frames.find((x) => x.frame === f)?.items ?? []).filter((i) => i.clip === clip && i.kind === "text" && i.opacity > 0.02);
  const rows = (items) => [...new Set(items.map((i) => Math.round(i.rect[1])))].sort((a, b) => a - b);

  const nowrap = texts(59, "nowrap");
  check(rows(nowrap).length === 1 && nowrap[0].rect[2] > 800, `wrap:false keeps one line, overflowing the 800 px box (${nowrap.map((i) => i.rect[2])})`);

  const fit = texts(59, "fit");
  const fitRows = rows(fit);
  check(fit.length && fit.every((i) => i.size >= 56) && fitRows.length >= 3,
    `size "fit" uses several lines at a large size (${fit[0]?.size} px, ${fitRows.length} lines), not one line at 28 px`);
  const last = fit.reduce((m, i) => Math.max(m, i.rect[1] + i.rect[3]), 0);
  check(last <= 200 + 360 + 2, `the fitted lines stay inside the box height (bottom ${last})`);
  check(fit.every((i, k) => k === 0 || !(/[0-9.]$/.test(fit[k - 1].text) && /^[0-9%元升.]/.test(i.text))),
    `no fitted line splits a number from its digits or unit (${fit.map((i) => i.text).join(" / ")})`);

  const bal = texts(59, "bal");
  check(rows(bal).length === 2 && !bal.some((i) => /^元/.test(i.text)) && bal.some((i) => /8999 元/.test(i.text)),
    `balanced px text keeps "8999 元" together (${bal.map((i) => i.text).join(" / ")})`);

  const l2 = rows(texts(2, "lines")).length;
  const l20 = rows(texts(20, "lines")).length;
  const l59 = rows(texts(59, "lines")).length;
  check(l2 === 1 && l20 > l2 && l59 > l20 && l59 >= 3, `reveal "lines" on wrapped px text shows the visual lines one by one (${l2}, ${l20}, ${l59})`);

  const plain = texts(59, "plain");
  check(plain.length && plain.every((i) => i.color === "rgb(247, 241, 230)"), `text with no colour is snow (${plain[0]?.color})`);

  // the same words in display (Smiley Sans), zcool and sans: three different faces, none fallen back to another
  const face = (y) => pixels(path.join(OUT, "layout", "still_00059.png"), 60, y, 600, 100);
  const [dsp, zc, sans] = [face(1480), face(1600), face(1720)];
  check(diff(dsp, zc) > 8 && diff(dsp, sans) > 8 && diff(zc, sans) > 8,
    `display, zcool and sans draw differently (${diff(dsp, zc).toFixed(1)}, ${diff(dsp, sans).toFixed(1)}, ${diff(zc, sans).toFixed(1)})`);

  // evidence at frame 90: ev_tall (box 40,220 500x1240) hugs its sentence; the rest of the box shows the ground
  const png = path.join(OUT, "layout", "still_00090.png");
  const above = mean(pixels(png, 60, 300, 460, 300));
  const below = mean(pixels(png, 60, 1100, 460, 300));
  check(above[2] > above[0] + 60 && below[2] > below[0] + 60, `a tall evidence box is not padded with white page (above ${above.map(Math.round)}, below ${below.map(Math.round)})`);
  const s = 500 / (330 + 2 * 66 * 0.35);
  const panelH = (66 + 2 * 40) * s;
  const top = 220 + (1240 - panelH) / 2;
  const middle = pixels(png, 120, Math.round(top + 40 * s), 300, Math.round(66 * s));
  check(mean(middle).every((v) => v > 150) && darkest(middle) < 90, "the sentence fills the panel: white page with dark text");
  // the cut sides fade to page: the outermost columns over the sentence carry no ink
  const leftEdge = pixels(png, 41, Math.round(top + 40 * s), 3, Math.round(66 * s));
  const rightEdge = pixels(png, 536, Math.round(top + 40 * s), 3, Math.round(66 * s));
  check(darkest(leftEdge) > 200 && darkest(rightEdge) > 200, `no half glyph at the cut edges (darkest ${Math.round(darkest(leftEdge))}, ${Math.round(darkest(rightEdge))})`);
  const narrowAbove = mean(pixels(png, 610, 420, 280, 200));
  check(narrowAbove[2] > narrowAbove[0] + 60, "a narrow tall evidence box shrinks to its content too");

  // pan_x 0 -> 100 with no zoom: the picture is zoomed enough that the box never shows the ground behind it
  const strip = mean(pixels(png, 42, 1510, 90, 280));
  const ground = [58, 110, 165];
  check(strip.some((v, i) => Math.abs(v - ground[i]) > 25), `a pan without zoom shows no empty strip (${strip.map(Math.round)})`);
  // a line with only a fill is drawn in that colour (gold #D9A441) from top-left to bottom-right
  const mid = mean(pixels(png, 798, 1648, 4, 4));
  check(mid[0] > 180 && mid[2] < 120, `a line with only "fill" draws in that colour (${mid.map(Math.round)})`);
}

console.log("transitions between clips on a track (cuts.resolved.json)");
{
  const fx = path.join(HERE, "cuts.resolved.json");
  const r = run(["stills", fx, HERE, path.join(OUT, "cuts"), "44", "45", "52", "57", "60"]);
  console.log(`  (${r.s} s)`);
  check(r.code === 0 && r.result?.ok === true, `stills ok (${r.result?.error ?? ""})`);
  const at = (f, x, y) => mean(pixels(path.join(OUT, "cuts", `still_${String(f).padStart(5, "0")}.png`), x, y, 8, 8));
  const rgb = (v) => v.map(Math.round).join(",");
  const [red, mix, blue] = [at(44, 270, 120), at(52, 270, 120), at(60, 270, 120)];
  check(red[0] > 240 && red[2] < 15 && blue[2] > 240 && blue[0] < 15, `before and after a crossfade: one clip each (${rgb(red)} / ${rgb(blue)})`);
  check(mix[0] > 120 && mix[0] < 150 && mix[2] > 105 && mix[2] < 135,
    `crossfade at 7/15: the incoming clip at 47 % over the outgoing, painted on top though listed first (${rgb(mix)})`);
  const [left, right] = [at(52, 100, 360), at(52, 500, 360)];
  check(left[1] > 240 && left[0] < 15 && right.every((v) => v > 240), `wipe_left: the new clip on the right, the old on the left (${rgb(left)} / ${rgb(right)})`);
  const [dark, rising] = [at(52, 270, 600), at(57, 270, 600)];
  check(Math.max(...dark) < 40, `dip_black is black mid-way (${rgb(dark)})`);
  check(rising[0] < 30 && rising[1] > 130 && rising[1] < 175, `dip_black: the new clip comes up out of black (${rgb(rising)})`);
  const [still, pushed, coming] = [at(45, 500, 840), at(52, 100, 840), at(52, 500, 840)];
  check(still[0] > 240 && still[2] > 240, `slide_left starts with the old clip in place (${rgb(still)})`);
  check(pushed[0] > 240 && pushed[2] > 240 && coming[0] > 240 && coming[1] > 110 && coming[1] < 150 && coming[2] < 15,
    `slide_left pushes the old clip out left as the new one comes in from the right (${rgb(pushed)} / ${rgb(coming)})`);
}

console.log("sound curves: video volume keyframes and a ducked bed (film)");
{
  const dir = path.join(OUT, "sound");
  fs.mkdirSync(path.join(dir, "assets"), { recursive: true });
  const gen = (args, name) => spawnSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", ...args, path.join(dir, "assets", name)]);
  gen(["-f", "lavfi", "-i", "testsrc2=s=270x480:r=30:d=4", "-f", "lavfi", "-i", "sine=f=1000:d=4", "-c:v", "libx264",
    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"], "talk.mp4");
  gen(["-f", "lavfi", "-i", "sine=f=250:d=4"], "bed.wav");
  const film = {
    version: 2, fps: 30, width: 270, height: 480, durationInFrames: 120, safe: { x: 10, y: 50, w: 250, h: 380 }, theme: basic.theme,
    tracks: [{ id: "v", kind: "visual", clips: [{
      id: "talk", type: "video", track: "v", from: 0, dur: 120, box: { x: 0, y: 0, w: 270, h: 480 }, style: {}, keyframes: {},
      enter: null, exit: null, transition: null, transitionOut: null,
      content: { src: "assets/talk.mp4", duration: 4, trimIn: 0, rate: 1, loop: false, fit: "cover", focus: null, volume: 1,
        volumeKeys: [{ f: 0, v: 1 }, { f: 29, v: 1 }, { f: 30, v: 0.02 }, { f: 59, v: 0.02 }, { f: 60, v: 1 }] },
    }] }],
    audio: [{ id: "bed", src: "assets/bed.wav", from: 0, dur: 120, trimIn: 0, volume: 1, fadeIn: 0, fadeOut: 0, loop: false,
      duck: [{ start: 63, end: 89, level: 0.03, fade: 3 }] }],
    inspect: false,
  };
  const file = path.join(dir, "resolved.json");
  fs.writeFileSync(file, JSON.stringify(film));
  const mp4 = path.join(dir, "sound.mp4");
  const r = run(["film", file, dir, mp4]);
  console.log(`  (${r.s} s)`);
  check(r.result?.ok === true && fs.existsSync(mp4), `film with a sounding video and a bed renders (${r.result?.error ?? ""})`);
  const level = (from, len, freq) => {
    const band = `bandpass=f=${freq}:width_type=h:w=150`;
    const v = spawnSync("ffmpeg", ["-hide_banner", "-ss", String(from), "-t", String(len), "-i", mp4, "-vn", "-af",
      `${band},${band},volumedetect`, "-f", "null", "-"], { encoding: "utf8" });
    const m = /mean_volume: (-?[\d.]+) dB/.exec(v.stderr || "");
    return m ? Number(m[1]) : NaN;
  };
  const talk = [level(0.2, 0.6, 1000), level(1.2, 0.6, 1000), level(2.2, 0.6, 1000)];
  const bed = [level(0.2, 0.6, 250), level(2.3, 0.5, 250), level(3.2, 0.6, 250)];
  const db = (xs) => xs.map((x) => x.toFixed(1)).join(", ");
  check(talk[0] - talk[1] > 20 && Math.abs(talk[0] - talk[2]) < 4, `video volume keyframes: quiet 1-2 s, loud again after (${db(talk)} dB)`);
  check(bed[0] - bed[1] > 20 && Math.abs(bed[0] - bed[2]) < 4, `the bed ducks 2.1-3 s and comes back (${db(bed)} dB)`);
}

console.log("transient failures");
{
  const once = run(["stills", fixture, HERE, path.join(OUT, "flaky"), "12"], { REELSMITH_LIBRARY: library, REELSMITH_FAKE_SOCKET_ERROR: "once" });
  check(once.result?.ok === true && /retrying once/.test(once.stdout), `a still that hits a socket error is retried once and passes (${once.s} s)`);
  const always = run(["stills", fixture, HERE, path.join(OUT, "flaky"), "12"], { REELSMITH_LIBRARY: library, REELSMITH_FAKE_SOCKET_ERROR: "always" });
  check(always.result?.ok === false && always.result?.stage === "infra" && always.result?.transient === true && always.result?.during === "render",
    `a repeated socket error is reported as transient infra, not as the project's fault (${always.result?.stage})`);
}

console.log("film with looping video and audio (video.resolved.json)");
{
  const fx = path.join(HERE, "video.resolved.json");
  const mp4 = path.join(OUT, "video.mp4");
  const r = run(["film", fx, HERE, mp4]);
  console.log(`  (${r.s} s)`);
  check(r.result?.ok === true && fs.existsSync(mp4), `film with two video clips renders (${r.result?.error ?? ""})`);
  const t = r.result?.timings ?? {};
  check(["bundle", "browser", "composition", "render", "total"].every((k) => Number.isFinite(t[k])) && r.result?.bundleMs >= 0 &&
    r.result?.renderMs >= 0, `per-stage timings ${JSON.stringify(t)}`);
  // trimIn 6, rate 1.25 over a 60-frame source: the loop is floor(53 / 1.25) = 42 frames long
  const band = (n) => pixels(mp4, 300, 700, 200, 120, n);
  check(diff(band(30), band(72)) < 4 && diff(band(30), band(50)) > 10, `the video loops every 42 frames (${diff(band(30), band(72)).toFixed(1)} vs ${diff(band(30), band(50)).toFixed(1)})`);
  const vol = spawnSync("ffmpeg", ["-hide_banner", "-ss", "3", "-t", "1.5", "-i", mp4, "-vn", "-af", "volumedetect", "-f", "null", "-"], { encoding: "utf8" });
  const m = /mean_volume: (-?[\d.]+) dB/.exec(vol.stderr || "");
  check(m && Number(m[1]) > -35, `a looping 2 s music clip still plays at 3-4.5 s (${m?.[1]} dB)`);
}

console.log("parallel calls");
{
  const [a, b, c] = await Promise.all([
    runAsync(["stills", fixture, HERE, path.join(OUT, "par-a"), "0", "12", "45", "64"], { REELSMITH_LIBRARY: library }),
    runAsync(["stills", fixture, HERE, path.join(OUT, "par-b"), "1", "13", "46", "65"], { REELSMITH_LIBRARY: library }),
    runAsync(["film", path.join(HERE, "video.resolved.json"), HERE, path.join(OUT, "par-c.mp4")]),
  ]);
  check(a.result?.ok && b.result?.ok && c.result?.ok, `two stills calls and a film at once all pass (${a.s}, ${b.s}, ${c.s} s) ` +
    `${[a, b, c].map((x) => x.result?.error ?? "").join(" ")}`);
  const ports = [a, b, c].map((x) => x.result?.port);
  check(ports.every(Number.isInteger) && new Set(ports).size === 3, `each call serves on its own port (${ports.join(", ")})`);
}

console.log("arguments");
{
  const r1 = run(["movie", fixture, HERE, OUT]);
  check(r1.code === 2 && r1.result?.ok === false && r1.result?.stage === "args", "an unknown mode is refused with stage args");
  const r2 = run(["stills", fixture, HERE, OUT]);
  check(r2.code === 2 && /at least one frame/.test(r2.result?.error ?? ""), "stills without frames is refused");
  const r3 = run(["stills", fixture, HERE, OUT, "1.5"]);
  check(r3.code === 2 && /whole number/.test(r3.result?.error ?? ""), "a fractional frame is refused");
  const bad = path.join(OUT, "bad.json");
  fs.writeFileSync(bad, JSON.stringify({ fps: 30, tracks: [] }));
  const r4 = run(["stills", bad, HERE, OUT, "0"]);
  check(r4.result?.stage === "input" && /width must be a positive number/.test(r4.result?.error ?? ""), "a malformed resolved.json is refused with stage input");
}

console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
if (keepAt < 0) fs.rmSync(OUT, { recursive: true, force: true });
else console.log(`outputs kept in ${OUT}`);
process.exit(failures ? 1 : 0);
