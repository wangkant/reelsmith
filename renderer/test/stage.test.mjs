// Unit tests for the stage kit's pure functions (cues, drawn-pose acting, step, win, torn, motion, camera stations, photo optics, Broll's camera): bundles them
// with esbuild and runs them in Node, no browser and no render. A few seconds.
//   node test/stage.test.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-stage-"));
const entry = path.join(OUT, "entry.ts");
fs.writeFileSync(entry, [
  `export * from ${JSON.stringify(path.join(ROOT, "src/kit/stage/time.ts").replace(/\\/g, "/"))};`,
  `export * from ${JSON.stringify(path.join(ROOT, "src/kit/stage/geom.ts").replace(/\\/g, "/"))};`,
  `export * from ${JSON.stringify(path.join(ROOT, "src/kit/stage/motion.ts").replace(/\\/g, "/"))};`,
  `export { camAt } from ${JSON.stringify(path.join(ROOT, "src/kit/stage/Stage.tsx").replace(/\\/g, "/"))};`,
  `export * from ${JSON.stringify(path.join(ROOT, "src/kit/stage/optics.ts").replace(/\\/g, "/"))};`,
  `export { lightMatrix } from ${JSON.stringify(path.join(ROOT, "src/kit/stage/photo.tsx").replace(/\\/g, "/"))};`,
  `export { softEllipse, softRing } from ${JSON.stringify(path.join(ROOT, "src/kit/stage/warp.tsx").replace(/\\/g, "/"))};`,
  `export { actAt, beatAt, blinkAt, checkTwins, faceAt, framingAt, poseBox, talkAt, toss } from ${JSON.stringify(path.join(ROOT, "src/kit/stage/drawn.tsx").replace(/\\/g, "/"))};`,
  `export { handPan, keepInside } from ${JSON.stringify(path.join(ROOT, "src/presets/Broll.tsx").replace(/\\/g, "/"))};`,
].join("\n"));
const bundle = path.join(OUT, "stage.mjs");
await build({
  entryPoints: [entry], bundle: true, platform: "node", format: "esm", outfile: bundle, logLevel: "error",
  absWorkingDir: ROOT, nodePaths: [path.join(ROOT, "node_modules")],
  alias: { "@reelsmith/kit": path.join(ROOT, "src/kit/index.ts") },
  loader: { ".css": "empty", ".woff": "empty", ".woff2": "empty", ".ttf": "empty", ".otf": "empty" },
  banner: { js: "import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);" },
});
const K = await import(pathToFileURL(bundle).href);

let failures = 0;
const test = (name, fn) => {
  try {
    fn();
    console.log(`  ok   ${name}`);
  } catch (e) {
    failures++;
    console.log(`  FAIL ${name}\n       ${e && e.message}`);
  }
};

const LINES = [
  { i: 2, text: "三十块一斤的牛肉，警方一验，全是猪肉。", from: -12, to: 88 },
  { i: 3, text: "Only the price gives it away: the price.", from: 95, to: 245 },
];

test("T places a word by character position, punctuation included", () => {
  const { T } = K.cues(LINES, 30);
  const n = Array.from(LINES[0].text).length;
  assert.equal(T("三十"), -12);
  assert.equal(T("警方"), Math.round(-12 + (100 * LINES[0].text.indexOf("警方")) / n));
  assert.equal(T("猪肉"), Math.round(-12 + (100 * LINES[0].text.indexOf("猪肉")) / n));
});

test("T adds an offset in seconds and finds the nth occurrence across lines", () => {
  const { T } = K.cues(LINES, 30);
  assert.equal(T("三十", 0.5), -12 + 15);
  const first = T("price"), second = T("price", 0, 1);
  assert.ok(second > first, `${second} > ${first}`);
  assert.ok(T("肉", 0, 1) > T("肉"));
});

test("T throws when the word is not said, or the occurrence does not exist", () => {
  const { T } = K.cues(LINES, 30);
  assert.throws(() => T("牛排"), /牛排/);
  assert.throws(() => T("price", 0, 2), /occurrence 2/);
  assert.throws(() => K.cues([], 30).T("x"), /no narration lines/);
});

test("at, end and S", () => {
  const c = K.cues(LINES, 25);
  assert.equal(c.at(), -12);
  assert.equal(c.end(), 245);
  assert.equal(c.at(3), 95);
  assert.equal(c.end(2), 88);
  assert.throws(() => c.at(7), /line 7/);
  assert.equal(c.S(2), 50);
  assert.throws(() => K.cues([], 30).at(), /no narration/);
});

test("step holds poses at the given rate", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6].map((f) => K.step(f)), [0, 0, 0, 2.5, 2.5, 5, 5]);
  assert.deepEqual([0, 4, 5, 9, 10].map((f) => K.step(f, 6)), [0, 0, 5, 5, 10]);
  assert.equal(K.step(25, 12, 25), 25);
  assert.equal(K.step(26, 12, 25), 25);
});

test("win rises, holds and falls", () => {
  assert.equal(K.win(-1, 0, 30), 0);
  assert.equal(K.win(3, 0, 30), 0.5);
  assert.equal(K.win(15, 0, 30), 1);
  assert.equal(K.win(27, 0, 30), 0.5);
  assert.equal(K.win(31, 0, 30), 0);
  assert.equal(K.win(5, 5, 20, 0, 0), 1);
});

test("torn is deterministic per seed and differs between seeds", () => {
  const pts = K.rect(0, 0, 400, 300);
  const a = K.torn(pts, "piece"), b = K.torn(pts, "piece"), c = K.torn(pts, "other");
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.match(a, /^M[-\d.]+ [-\d.]+(L[-\d.]+ [-\d.]+)+Z$/);
  const segs = a.split("L").length;
  assert.ok(segs >= 84 && segs <= 92, `segments ${segs}`);
});

test("easing and helpers stay in range", () => {
  assert.equal(K.prog(5, 0, 10), 0.5);
  assert.equal(K.prog(5, 5, 0), 1);
  assert.ok(Math.abs(K.backOut(1) - 1) < 1e-9);
  assert.equal(K.wob(10, 10, 5), 0);
  assert.equal(K.mixColor("#000000", "#FFFFFF", 0.5), "#808080");
  assert.deepEqual(K.along([[0, 0], [10, 0], [10, 10]], 0.75), [10, 5]);
  const [x, y] = K.boil("s", 5, 3);
  assert.ok(Math.abs(x) <= 3 && Math.abs(y) <= 3);
  assert.deepEqual(K.boil("s", 5, 3), K.boil("s", 6, 3));
});

test("drop falls faster and faster, lands at `to`, squashes and settles", () => {
  const at = 10, to = 900;
  assert.deepEqual(K.drop(5, at, 0, to), { y: 0, sx: 1, sy: 1, t: 0, landed: false });
  const ys = [12, 14, 16, 18].map((f) => K.drop(f, at, 0, to).y);
  assert.ok(ys[1] - ys[0] < ys[3] - ys[2], `accelerates: ${ys}`);
  let land = at;
  while (!K.drop(land, at, 0, to).landed) land++;
  const hit = K.drop(land, at, 0, to, { squash: 0.3 });
  assert.equal(hit.y, to);
  assert.ok(hit.sx > 1 && hit.sy < 1, "squashes on landing");
  const late = K.drop(land + 90, at, 0, to, { squash: 0.3 });
  assert.ok(Math.abs(late.sx - 1) < 0.01 && Math.abs(late.sy - 1) < 0.01, "settles");
});

test("pendulum decays to a faint idle sway, never a dead stop", () => {
  const early = Math.max(...Array.from({ length: 30 }, (_, i) => Math.abs(K.pendulum(i, 0, 24))));
  const late = Array.from({ length: 90 }, (_, i) => K.pendulum(300 + i, 0, 24));
  assert.ok(early > 15);
  assert.ok(Math.max(...late.map(Math.abs)) <= 1.4 && Math.max(...late) - Math.min(...late) > 0.5);
});

test("follow trails its leader and catches up when it stops", () => {
  const lead = (f) => Math.min(100, Math.max(0, f));
  assert.ok(K.follow(50, lead, 8) < lead(50));
  assert.ok(Math.abs(K.follow(200, lead, 8) - 100) < 1e-9);
});

test("shake is deterministic, bounded and over after its duration", () => {
  assert.deepEqual(K.shake("s", 13, 10, 12, 18), K.shake("s", 13, 10, 12, 18));
  for (let f = 10; f <= 28; f++) {
    const [x, y] = K.shake("s", f, 10, 12, 18);
    assert.ok(Math.abs(x) <= 12 && Math.abs(y) <= 12);
  }
  assert.deepEqual(K.shake("s", 40, 10, 12, 18), [0, 0]);
  assert.deepEqual(K.shake("s", 5, 10, 12, 18), [0, 0]);
});

test("breathe stays within 1 +- amp", () => {
  const v = Array.from({ length: 200 }, (_, f) => K.breathe(f, 0.02));
  assert.ok(Math.max(...v) <= 1.02 + 1e-9 && Math.min(...v) >= 0.98 - 1e-9 && Math.max(...v) > 1.015);
});

test("stations arrive on each stop's frame, hold with a push and dip the zoom while travelling", () => {
  const stops = [{ at: 0, x: 100, y: 200, z: 1 }, { at: 60, x: 900, y: 300, z: 1.2 }, { at: 90, x: 1500, y: 300 }];
  const keys = K.stations(stops, { travel: 20, dip: 0.1, push: 0.05, until: 150 });
  for (const s of stops) {
    const c = K.camAt(keys, s.at);
    assert.ok(Math.abs(c.x - s.x) < 1e-9 && Math.abs(c.y - s.y) < 1e-9, `at ${s.at}`);
  }
  assert.equal(K.camAt(keys, 30).x, 100);
  assert.ok(K.camAt(keys, 30).z > 1, "pushes in while holding");
  assert.ok(K.camAt(keys, 50).z < K.camAt(keys, 40).z, "dips mid-travel");
  assert.ok(K.camAt(keys, 150).z > 1, "keeps pushing on the last stop");
  const close = K.stations([{ at: 0, x: 0, y: 0 }, { at: 5, x: 10, y: 0 }], { travel: 30 });
  assert.ok(close.every((k, i) => i === 0 || k.at > close[i - 1].at), "keys stay in order when stops are close");
});

const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

test("coverFit covers the frame with the pad to spare and maps traced points", () => {
  const fit = K.coverFit(1024, 1536, 1080, 1920, 0.06);
  assert.ok(near(fit.s, 1.4) && near(fit.w, 1433.6) && near(fit.x, (1080 - 1433.6) / 2));
  assert.ok(fit.x <= -1080 * 0.06 + 1e-9 && fit.y <= -1920 * 0.06 + 1e-9);
  assert.ok(fit.x + fit.w >= 1080 * 1.06 - 1e-9 && fit.y + fit.h >= 1920 * 1.06 - 1e-9);
  const [x, y] = fit.at([512, 768]);
  assert.ok(near(x, 540) && near(y, 960), "the picture's centre lands on the frame's");
  const top = K.coverFit(1000, 1000, 1080, 1920, 0, [0.5, 0]);
  assert.equal(top.y, 0);
});

test("dofBlur is zero in focus, grows with the depth difference and is capped", () => {
  assert.equal(K.dofBlur(0.9, 0.9, 10), 0);
  assert.ok(near(K.dofBlur(1.3, 0.9, 10), 4) && near(K.dofBlur(0.5, 0.9, 10), 4));
  assert.equal(K.dofBlur(10, 0, 10, 25), 25);
  assert.equal(K.dofBlur(1.5, 1, 0), 0);
});

test("pointAt walks a polyline by length and gives its direction", () => {
  const line = [[0, 0], [100, 0], [100, 100]];
  const mid = K.pointAt(line, 0.5);
  assert.ok(near(mid.x, 100) && near(mid.y, 0));
  const q = K.pointAt(line, 0.75);
  assert.ok(near(q.x, 100) && near(q.y, 50) && near(q.ang, 90));
  assert.deepEqual(K.pointAt([[3, 4]], 0.5), { x: 3, y: 4, ang: 0 });
});

test("travelAt waits, eases along the line with perspective scale, holds, and measures speed", () => {
  const line = [[0, 0], [300, 0]];
  const o = { sizes: [1, 0.5], ease: "linear" };
  const before = K.travelAt(line, 5, 10, 30, o), mid = K.travelAt(line, 25, 10, 30, o), after = K.travelAt(line, 60, 10, 30, o);
  assert.ok(before.x === 0 && before.t === 0 && before.speed === 0 && before.s === 1);
  assert.ok(near(mid.x, 150) && near(mid.s, 0.75) && near(mid.speed, 10));
  assert.ok(after.x === 300 && after.t === 1 && after.speed === 0 && after.s === 0.5);
  const eased = K.travelAt(line, 11, 10, 30);
  assert.ok(eased.speed < 10, "inOut starts slowly");
});

test("distanceAt sums a varying speed", () => {
  assert.equal(K.distanceAt(10, () => 3), 30);
  assert.equal(K.distanceAt(4, (f) => f), 0 + 1 + 2 + 3);
  assert.ok(near(K.distanceAt(2.5, () => 2), 5));
});

test("shadeRamp rises from one point to the other and holds beyond", () => {
  const s = K.shadeRamp([0, 0], [100, 0], 0.6);
  assert.equal(s(-50, 7), 0);
  assert.ok(near(s(50, 0), 0.3) && near(s(400, 0), 0.6));
});

test("handheld is deterministic, bounded and moves", () => {
  const a = K.handheld(40, 6, "cam"), b = K.handheld(40, 6, "cam");
  assert.deepEqual(a, b);
  const xs = Array.from({ length: 300 }, (_, f) => K.handheld(f, 6, "cam")[0]);
  assert.ok(Math.max(...xs.map(Math.abs)) <= 6 + 1e-9 && Math.max(...xs) - Math.min(...xs) > 2);
});

test("joinAt runs 0 to 1 over the join", () => {
  assert.equal(K.joinAt(5, 10, 12), 0);
  assert.equal(K.joinAt(30, 10, 12), 1);
  assert.ok(near(K.joinAt(16, 10, 12), 0.5));
});

test("lookAt puts a point in the frame centre and onScreen agrees", () => {
  for (const depth of [0.6, 0.9, 1, 1.3]) {
    const c = K.lookAt([700, 400], depth, 1080, 1920);
    const o = K.onScreen({ ...c, z: 1.4 }, depth, 1080, 1920, [700, 400]);
    assert.ok(near(o.x, 540) && near(o.y, 960), `depth ${depth}`);
    assert.ok(near(o.s, Math.pow(1.4, 0.5 + 0.5 * depth)));
  }
});

test("lightMatrix keeps alpha, darkens by shade and mixes toward haze", () => {
  const rows = (m) => m.split(/\s{2}/).map((r) => r.trim().split(" ").map(Number));
  assert.deepEqual(rows(K.lightMatrix())[3], [0, 0, 0, 1, 0]);
  assert.equal(rows(K.lightMatrix(0.25))[0][0], 0.75);
  const hz = rows(K.lightMatrix(0, "#FFFFFF", 0, 0.5, "#FFFFFF"));
  assert.ok(near(hz[1][1], 0.5) && near(hz[1][4], 0.5));
  assert.ok(rows(K.lightMatrix(0, "#FF0000", 1))[1][1] === 0, "a red tint takes green out");
});

test("softEllipse and softRing are CSS gradients around the given centre", () => {
  assert.match(K.softEllipse([100, 200, 50, 80]), /^radial-gradient\(50px 80px at 100px 200px, black 55%, transparent 100%\)$/);
  const ring = K.softRing(10, 20, 100, 20);
  assert.match(ring, /at 10px 20px, transparent 66\.67%, black 83\.33%, transparent 100%/);
});

test("hazeBand gives ascending stops whichever way the band runs", () => {
  const down = K.hazeBand(100, 300, 0.5);
  assert.deepEqual([down.top, down.bot], [100, 400]);
  assert.deepEqual(down.stops.map(([, o]) => o), [0, 1, 0]);
  assert.ok(Math.abs(down.stops[1][0] - 2 / 3) < 1e-9);
  const up = K.hazeBand(300, 100, 0.5);
  assert.deepEqual([up.top, up.bot], [0, 300]);
  const offs = up.stops.map(([o]) => o);
  assert.deepEqual(offs, [...offs].sort((a, b) => a - b));
  assert.deepEqual(up.stops.map(([, o]) => o), [0, 1, 0]);
  assert.ok(Math.abs(up.stops[1][0] - 1 / 3) < 1e-9);
});

test("swayAngle is zero at rest, bounded by amp, and a gust decays", () => {
  for (let f = 0; f < 300; f += 7) assert.equal(K.swayAngle(f, 30, 0), 0);
  for (let f = 0; f < 300; f += 7) assert.ok(Math.abs(K.swayAngle(f, 30, 2)) <= 2 + 1e-9);
  assert.equal(K.swayAngle(40, 30, 0, 0.35, 50, 3), 0, "no gust before its frame");
  assert.ok(Math.abs(K.swayAngle(52, 30, 0, 0.35, 50, 3)) > 0.1);
  assert.ok(Math.abs(K.swayAngle(50 + 30 * 6, 30, 0, 0.35, 50, 3)) < 1e-3, "gone after a few seconds");
});

test("filmFrame holds, plays at its rate, ends on its last frame, loops and releases", () => {
  assert.deepEqual(K.filmFrame({ at: 30 }, 10, 30, 2), { state: "before", frame: 0 });
  assert.deepEqual(K.filmFrame({ at: 30 }, 45, 30, 2), { state: "play", frame: 15 });
  assert.deepEqual(K.filmFrame({ at: 30 }, 89, 30, 2), { state: "play", frame: 59 });
  assert.deepEqual(K.filmFrame({ at: 30 }, 200, 30, 2), { state: "after", frame: 59 });
  assert.equal(K.filmFrame({ at: 30, hold: "before" }, 200, 30, 2).frame, null);
  assert.equal(K.filmFrame({ at: 30, hold: false }, 0, 30, 2).frame, null);
  assert.equal(K.filmFrame({ at: 0, rate: 2, from: 0.5 }, 10, 30, 2).frame, 35);
  assert.equal(K.filmFrame({ at: 0, loop: true }, 65, 30, 2).frame, 5);
  assert.equal(K.filmFrame({ at: 0, len: 1 }, 50, 30, 2).frame, 29);
});

test("punchAt picks the cue in force and punchView keeps the crop inside the picture", () => {
  const cues = [{ at: 10, end: 20, to: [500, 500], z: 1.5 }, { at: 30, to: [0, 0], z: 2 }];
  assert.equal(K.punchAt(cues, 5), null);
  assert.equal(K.punchAt(cues, 12), cues[0]);
  assert.equal(K.punchAt(cues, 25), null);
  assert.equal(K.punchAt(cues, 99), cues[1]);
  const fit = K.coverFit(1080, 1620, 1080, 1920, 0.02);
  const v = K.punchView(cues[1], fit, 1080, 1920);
  const [l, t] = [v.cx - 1080 / (2 * v.z), v.cy - 1920 / (2 * v.z)];
  assert.ok(Math.abs(l - fit.x) < 1e-6 && Math.abs(t - fit.y) < 1e-6, "a corner point is clamped to the picture's corner");
  assert.deepEqual(K.viewed(v, 1080, 1920, [v.cx, v.cy]), [540, 960]);
});

test("castMatrix keeps the foot on the ground and lays the top away from the light", () => {
  const { m, len } = K.castMatrix({ from: "upper-left", height: 0.5 }, 800);
  const ap = ([x, y]) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  const foot = ap([300, 800]), top = ap([300, 600]);
  assert.ok(Math.abs(foot[0] - 300) < 1e-9 && Math.abs(foot[1] - 800) < 1e-9);
  assert.ok(top[0] > 300 && top[1] > 800, "falls right and toward the camera");
  assert.ok(len > 0.5 && len < 1.5);
  const front = K.castMatrix({ from: "front" }, 800).m;
  assert.ok(front[3] * 600 + front[5] < 800, "a light behind the camera puts the shadow behind the thing");
  assert.ok(K.castMatrix({ from: "left", height: 0.9 }, 0).len < K.castMatrix({ from: "left", height: 0.2 }, 0).len);
});

test("filmFrame refuses loop when the clip's length is unknown, and loops with len", () => {
  assert.throws(() => K.filmFrame({ at: 0, loop: true }, 100, 24, null), /pass `len`.*asset ref/);
  assert.equal(K.filmFrame({ at: 0, loop: true, len: 1 }, 30, 24, null).frame, 6);
  assert.equal(K.filmFrame({ at: 0, loop: true }, 60, 24, 2).frame, 12);
});

test("showsFilm: before the start the still shows unless the clip starts past its first frame", () => {
  const show = (t, f) => K.showsFilm(t, K.filmFrame(t, f, 24, 2));
  assert.equal(show({ at: 10 }, 5), false, "frame 0 is the still");
  assert.equal(show({ at: 10, from: 0.5 }, 5), true, "frame `from` holds before, as Footage does");
  assert.equal(show({ at: 10 }, 12), true);
  assert.equal(show({ at: 0, hold: "before" }, 200), false, "past the end with hold before");
  assert.equal(show({ at: 0 }, 200), true, "the last frame holds by default");
});

test("silhouette finds the real lowest pixels under rotation, flip, squash and empty rows", () => {
  const box = [[0, 0], [1, 0], [0, 1], [1, 1]];
  const up = K.silhouette(box, 500, 800, -200, -100, 400, 100);
  assert.ok(Math.abs(up.foot - 800) < 1e-9 && Math.abs(up.top - 700) < 1e-9 && Math.abs(up.cx - 500) < 1e-9);
  // an oval at r -8, anchor 0.92: its foot is the ellipse's, not the rotated box's lower corner
  const oval = Array.from({ length: 360 }, (_, i) => [0.5 + 0.5 * Math.cos((i * Math.PI) / 180), 0.5 + 0.5 * Math.sin((i * Math.PI) / 180)]);
  const ox = -200, oy = -0.92 * 300;
  const rot = K.silhouette(oval, 500, 800, ox, oy, 400, 300, -8), corner = K.silhouette(box, 500, 800, ox, oy, 400, 300, -8);
  const s8 = Math.sin((8 * Math.PI) / 180), c8 = Math.cos((8 * Math.PI) / 180);
  const want = 800 - 126 * c8 + Math.sqrt(200 * 200 * s8 * s8 + 150 * 150 * c8 * c8);
  assert.ok(Math.abs(rot.foot - want) < 1, `oval foot ${rot.foot} want ${want}`);
  assert.ok(rot.foot < corner.foot - 20, `${rot.foot} vs box ${corner.foot}`);
  // a quarter turn: the picture's right edge becomes its bottom
  const q = K.silhouette([[0.9, 0.2], [0.9, 0.8], [0.1, 0.5]], 0, 0, -50, -50, 100, 100, 90);
  assert.ok(Math.abs(q.foot - 40) < 1e-9 && Math.abs(q.top + 40) < 1e-9, `${q.foot} ${q.top}`);
  // flip mirrors x around the anchor; empty bottom rows do not count
  const f = K.silhouette([[0.1, 0], [0.3, 0.6]], 100, 0, -50, -100, 100, 100, 0, true);
  assert.ok(Math.abs(f.foot + 40) < 1e-9 && Math.abs(f.cx - 120) < 1e-9, `${f.foot} ${f.cx}`);
  assert.ok(Math.abs(K.silhouette(box, 0, 0, -50, -200, 100, 200).foot) < 1e-9, "sy is in dh");
});

test("Broll's pan eases in and out, a little unevenly, and lands exactly", () => {
  for (const seed of [1, 2, 7]) {
    assert.equal(K.handPan(0, seed), 0);
    assert.equal(K.handPan(1, seed), 1);
    const steps = [];
    let prev = 0;
    for (let i = 1; i <= 200; i++) {
      const v = K.handPan(i / 200, seed);
      assert.ok(v >= prev, `monotone at ${i / 200}`);
      steps.push(v - prev);
      prev = v;
    }
    const mid = steps.slice(60, 140);
    assert.ok(steps[0] < 0.004 && steps[199] < 0.004, `slow at the ends: ${steps[0]} ${steps[199]}`);
    assert.ok(Math.max(...mid) / Math.min(...mid) > 1.1, "uneven in the middle");
  }
  assert.notEqual(K.handPan(0.5, 1), K.handPan(0.5, 2));
});

test("Broll's camera never shows past the plate's edge", () => {
  const inside = (fit, c, w, h, ax, ay) => c.x - w / (2 * c.z) - ax >= fit.x - 1e-9 && c.x + w / (2 * c.z) + ax <= fit.x + fit.w + 1e-9
    && c.y - h / (2 * c.z) - ay >= fit.y - 1e-9 && c.y + h / (2 * c.z) + ay <= fit.y + fit.h + 1e-9;
  const W = 1080, H = 1920;
  const wide = K.coverFit(1536, 1024, W, H, 0);
  const left = K.keepInside(-500, H / 2, 1.04, wide, W, H, 9, 8);
  assert.ok(inside(wide, left, W, H, 9, 8) && left.z === 1.04, JSON.stringify(left));
  assert.ok(Math.abs(left.x - (wide.x + W / 2.08 + 9)) < 1e-9, "a pan past the edge stops at the edge");
  assert.equal(K.keepInside(W / 2 + 100, H / 2, 1.04, wide, W, H, 9, 8).x, W / 2 + 100);
  // a plate of exactly the canvas aspect at zoom 1: the zoom rises just enough for the wobble
  const same = K.coverFit(1080, 1920, W, H, 0);
  const tight = K.keepInside(W / 2, H / 2, 1, same, W, H, 9, 8);
  assert.ok(inside(same, tight, W, H, 9, 8) && tight.z > 1 && tight.z < 1.02, JSON.stringify(tight));
  for (const [iw, ih, w, h] of [[1024, 1024, 1920, 1080], [1920, 1080, 1080, 1080], [1080, 1920, 1920, 1080]]) {
    const fit = K.coverFit(iw, ih, w, h, 0);
    for (const [x, y] of [[-1e4, -1e4], [1e4, 1e4], [w / 2, h / 2]]) {
      assert.ok(inside(fit, K.keepInside(x, y, 1, fit, w, h, 12, 10), w, h, 12, 10), `${iw}x${ih} on ${w}x${h}`);
    }
  }
});

test("beatAt and actAt: hold, anticipate against the move, snap, overshoot and settle", () => {
  const beats = [{ at: 0, pose: "a" }, { at: 30, pose: "b", dir: 1, scale: 0.9 }, { at: 60, pose: "c", dir: -1 }];
  assert.equal(K.beatAt(beats, -5), 0);
  assert.equal(K.beatAt(beats, 29), 0);
  assert.equal(K.beatAt(beats, 30), 1);
  const still = { breath: 0, sway: 0 };
  const held = K.actAt(beats, 10, still);
  assert.deepEqual([held.pose, held.sx, held.sy, held.rot, held.dy], ["a", 1, 1, 0, 0]);
  const crouch = K.actAt(beats, 29, still);              // last anticipation frame: deepest crouch, leaning left
  assert.equal(crouch.pose, "a");
  assert.ok(crouch.sy < 0.95 && crouch.sx > 1 && crouch.rot < 0 && crouch.dy > 0, JSON.stringify(crouch));
  assert.ok(K.actAt(beats, 59, still).rot > 0, "a move to the left leans right first");
  const snap = K.actAt(beats, 30, still);
  assert.equal(snap.pose, "b");
  assert.equal(snap.scale, 0.9);
  assert.ok(snap.sy > 1.05 && snap.rot > 3, JSON.stringify(snap));
  const settled = K.actAt(beats, 42, still);
  assert.ok(Math.abs(settled.sy - 1) < 1e-9 && settled.rot === 0);
  const first = K.actAt(beats, 0, still);                // the first pose does not overshoot
  assert.equal(first.sy, 1);
  assert.deepEqual(K.actAt(beats, 0, { ...still, antic: 0 }).sy, 1);
});

test("actAt: the moving hold breathes and sways, never dead", () => {
  const beats = [{ at: 0, pose: "a" }];
  const ys = Array.from({ length: 90 }, (_, f) => K.actAt(beats, f).sy);
  const rs = Array.from({ length: 90 }, (_, f) => K.actAt(beats, f).rot);
  assert.ok(Math.max(...ys) - Math.min(...ys) > 0.015 && Math.max(...ys) < 1.013);
  assert.ok(Math.max(...rs) - Math.min(...rs) > 0.5);
  assert.throws(() => K.actAt([], 0), /beats is empty/);
});

test("blinkAt: a deterministic blink every 2.5 to 5 s, len frames long", () => {
  const on = Array.from({ length: 900 }, (_, f) => K.blinkAt(f, "cat"));
  assert.deepEqual(on, Array.from({ length: 900 }, (_, f) => K.blinkAt(f, "cat")));
  const starts = on.map((v, f) => v && !on[f - 1] ? f : -1).filter((f) => f >= 0);
  assert.ok(starts.length >= 5 && starts.length <= 12, String(starts));
  for (let i = 1; i < starts.length; i++) assert.ok(starts[i] - starts[i - 1] >= 75 && starts[i] - starts[i - 1] <= 150);
  assert.equal(on.filter(Boolean).length, starts.length * 3);
  assert.notDeepEqual(starts, Array.from({ length: 900 }, (_, f) => K.blinkAt(f, "dog")).map((v, f, a) => v && !a[f - 1] ? f : -1).filter((f) => f >= 0));
  assert.equal(K.blinkAt(-3), false);
});

test("talkAt: on twos, opens above `open`, holds while above `hold`", () => {
  const L = [0, 0, 0.5, 0.5, 0.1, 0.1, 0.1, 0.1, 0.02, 0.02, 0.1, 0.1, 0.3, 0.9];
  assert.equal(K.talkAt(L, 0), false);
  assert.equal(K.talkAt(L, 2), true);
  assert.equal(K.talkAt(L, 3), true);                    // the odd frame repeats the even one
  assert.equal(K.talkAt(L, 4), true);                    // 0.1 after an open frame stays open
  assert.equal(K.talkAt(L, 6), true);
  assert.equal(K.talkAt(L, 8), false);
  assert.equal(K.talkAt(L, 10), false);                  // 0.1 after a closed frame stays shut
  assert.equal(K.talkAt((f) => (f === 12 ? 0.3 : 0), 12), true);
  assert.equal(K.talkAt([], 40), false);
});

test("toss: waits, flies on an arc above the line, lands and squashes", () => {
  const from = [100, 500], to = [400, 600];
  assert.deepEqual([K.toss(0, 10, from, to).x, K.toss(0, 10, from, to).y], from);
  const mid = K.toss(19, 10, from, to, 18, 200);
  assert.ok(mid.y < 550 - 150 && mid.x > 100 && mid.x < 400 && !mid.landed, JSON.stringify(mid));
  const land = K.toss(28, 10, from, to, 18, 200);
  assert.ok(land.landed && land.x === 400 && land.y === 600 && land.sx > 1.1 && land.sy < 0.9);
  assert.ok(Math.abs(K.toss(80, 10, from, to).sy - 1) < 0.01);
});

test("faceAt: talking shows the open mouth, silence the shut one; a blink never opens the mouth", () => {
  const full = { src: "open", shut: "shut", blink: "blink", blinkOpen: "blinkOpen" };
  assert.equal(K.faceAt(full, true, false), "open");
  assert.equal(K.faceAt(full, true, true), "blinkOpen");
  assert.equal(K.faceAt(full, false, false), "shut");
  assert.equal(K.faceAt(full, false, true), "blink");
  const noOpenBlink = { src: "open", shut: "shut", blink: "blink" };
  assert.equal(K.faceAt(noOpenBlink, true, true), "open");          // talking: the blink is skipped
  assert.equal(K.faceAt(noOpenBlink, false, true), "blink");
  assert.equal(K.faceAt({ src: "open", shut: "shut" }, false, true), "shut");
  assert.equal(K.faceAt({ src: "open" }, false, true), "open");
});

test("checkTwins: a twin not on its pose's canvas is refused by name", () => {
  const ref = (w, h) => ({ src: `a${w}.png`, size: [w, h] });
  K.checkTwins({ pA: { src: ref(929, 1438), shut: ref(929, 1438), blink: ref(929, 1438) }, pB: { src: "x.png", shut: ref(5, 5) } });
  assert.throws(() => K.checkTwins({ pA: { src: ref(929, 1438), shut: ref(951, 1440) } }),
    /pose "pA": its shut picture is 951x1440 but the pose is 929x1438; redraw the twin with draw\(\.\.\., twin_of=<the pose>\).*jump/);
  assert.throws(() => K.checkTwins({ pB: { src: ref(10, 20), imgW: 10, imgH: 20, blink: ref(11, 20) } }), /twin_of=<its shut twin>/);
});

test("actAt: beats in any order act as if sorted, ties kept in order", () => {
  const still = { breath: 0, sway: 0 };
  const sorted = [{ at: 0, pose: "a" }, { at: 30, pose: "b" }, { at: 60, pose: "c" }];
  const shuffled = [sorted[2], sorted[0], sorted[1]];
  for (const f of [0, 28, 30, 35, 59, 61, 90]) assert.deepEqual(K.actAt(shuffled, f, still), K.actAt(sorted, f, still));
  assert.equal(shuffled[0].pose, "c", "the caller's list is not reordered");
  assert.equal(K.actAt([{ at: 0, pose: "a" }, { at: 10, pose: "b" }, { at: 10, pose: "c" }], 12, still).pose, "c");
});

test("poseBox: h is the canvas height at scale 1; feet and scale applied", () => {
  const b = K.poseBox({ src: { src: "p.png", size: [500, 1000] }, feet: 0.4, scale: 0.9 }, 1200);
  assert.ok(Math.abs(b.hh - 1080) < 1e-9 && Math.abs(b.w - 540) < 1e-9 && Math.abs(b.fx - 216) < 1e-9, JSON.stringify(b));
  assert.equal(K.poseBox({ src: "p.png", imgW: 400, imgH: 800 }, 800).fx, 200);
});

test("poseBox: the soles, not the canvas's clear trim pad, stand on the ground line", () => {
  // a 500x1000 cut-out with 20 clear rows under its feet and 24 over its head, drawn 2000 tall
  const b = K.poseBox({ src: { src: "p.png", size: [500, 1000], inset: [24, 20] } }, 2000);
  assert.equal(b.sole, 1960);
  assert.equal(b.head, 48);
  assert.equal(K.poseBox({ src: "p.png", imgW: 500, imgH: 1000, inset: [24, 20] }, 1000).sole, 980);
  const bare = K.poseBox({ src: { src: "p.png", size: [500, 1000] } }, 1000);    // unmeasured: the canvas bottom
  assert.equal(bare.sole, 1000);
  assert.equal(bare.head, 20);
});

test("framingAt: hard cuts at their frames, clamped inside the scene", () => {
  const cuts = [{ at: 40, x: 300, y: 1500, z: 2 }, { at: 10, x: 540, y: 960, z: 1.5 }];
  assert.deepEqual(K.framingAt(cuts, 0, 1080, 1920), { x: 540, y: 960, z: 1 });
  assert.deepEqual(K.framingAt(cuts, 10, 1080, 1920), { x: 540, y: 960, z: 1.5 });
  assert.deepEqual(K.framingAt(cuts, 39, 1080, 1920), { x: 540, y: 960, z: 1.5 });   // no easing
  assert.deepEqual(K.framingAt(cuts, 40, 1080, 1920), { x: 300, y: 1500, z: 2 });
  assert.deepEqual(K.framingAt([{ at: 0, x: 100, y: 1900, z: 2 }], 5, 1080, 1920, [1080, 1920]), { x: 270, y: 1440, z: 2 });
  assert.equal(K.framingAt([{ at: 0, x: 540, y: 960, z: 0.5 }], 5, 1080, 1920, [1080, 1920]).z, 1);   // never smaller than the frame
});

fs.rmSync(OUT, { recursive: true, force: true });
console.log(failures ? `${failures} failed` : "all passed");
process.exit(failures ? 1 : 0);
