// Unit tests for the stage kit's pure functions (cues, step, win, torn, motion, camera stations): bundles them with esbuild and runs them in
// Node, no browser and no render. A few seconds.
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
].join("\n"));
const bundle = path.join(OUT, "stage.mjs");
await build({
  entryPoints: [entry], bundle: true, platform: "node", format: "esm", outfile: bundle, logLevel: "error",
  absWorkingDir: ROOT, nodePaths: [path.join(ROOT, "node_modules")],
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

fs.rmSync(OUT, { recursive: true, force: true });
console.log(failures ? `${failures} failed` : "all passed");
process.exit(failures ? 1 : 0);
