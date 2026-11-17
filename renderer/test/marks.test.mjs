// Unit tests for the drawn marks' pure parts (pop, spawning, focus lines, falling and rising things, chalk writing):
// bundles them with esbuild and runs them in Node, no browser and no render.
//   node test/marks.test.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-marks-"));
const entry = path.join(OUT, "entry.ts");
fs.writeFileSync(entry,
  `export { chalkLine, fallAt, focusLinesAt, popAt, riseAt, spawnsAt, writeAt } from ${JSON.stringify(path.join(ROOT, "src/kit/stage/marks.tsx").replace(/\\/g, "/"))};\n`);
const bundle = path.join(OUT, "marks.mjs");
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

const AREA = { x: 100, y: 200, w: 800, h: 1200 };

test("popAt is null before it starts, overshoots, then settles to 1", () => {
  assert.equal(K.popAt(-1), null);
  assert.deepEqual(K.popAt(0).map((v) => Math.round(v * 100) / 100), [0, 0]);
  const peak = Math.max(...Array.from({ length: 10 }, (_, j) => K.popAt(j)[0]));
  assert.ok(peak > 1.05, `peak ${peak}`);
  const [sx, sy] = K.popAt(40);
  assert.ok(Math.abs(sx - 1) < 0.01 && Math.abs(sy - 1) < 0.01);
});

test("spawnsAt gives nothing before at or from at + len, and none outlives at + len", () => {
  assert.deepEqual(K.spawnsAt(9, 10, 60, 8, 20), []);
  assert.deepEqual(K.spawnsAt(70, 10, 60, 8, 20), []);
  for (let f = 10; f < 70; f++) {
    for (const s of K.spawnsAt(f, 10, 60, 8, 20)) {
      assert.ok(s.age >= 0 && s.age < 20 && s.k >= 0 && s.k < 1);
      assert.ok(10 + s.i * 8 + 20 <= 70, `item ${s.i} outlives the mark`);
    }
  }
  assert.equal(K.spawnsAt(10, 10, 60, 8, 20).length, 1);
  assert.deepEqual(K.spawnsAt(30, 10, 60, 8, 20).map((s) => s.i), [1, 2]);
  assert.deepEqual(K.spawnsAt(30, 10, 60, 8, 20, 2).map((s) => s.i), [1]);
});

test("focusLinesAt: n wedges reaching past the area, tips outside the clear middle, held on twos", () => {
  const ls = K.focusLinesAt(5, 0, 30, AREA, { n: 50, inner: 0.6 });
  assert.equal(ls.length, 50);
  const cx = 500, cy = 800;
  for (const [tip, a, b] of ls) {
    const e = Math.hypot((tip[0] - cx) / 400, (tip[1] - cy) / 600);
    assert.ok(e >= 0.6 - 1e-9, `tip inside the clear middle (${e})`);
    for (const p of [a, b]) assert.ok(p[0] < 100 || p[0] > 900 || p[1] < 200 || p[1] > 1400, "a foot inside the area");
  }
  assert.deepEqual(K.focusLinesAt(4, 0, 30, AREA, { n: 50 }), K.focusLinesAt(5, 0, 30, AREA, { n: 50 }));
  assert.notDeepEqual(K.focusLinesAt(5, 0, 30, AREA, { n: 50 }), K.focusLinesAt(6, 0, 30, AREA, { n: 50 }));
  assert.deepEqual(K.focusLinesAt(-1, 0, 30, AREA), []);
  assert.deepEqual(K.focusLinesAt(30, 0, 30, AREA), []);
});

test("fallAt: deterministic, n things inside the area (plus the pad above), splashes only after a landing", () => {
  const o = { n: 40, speed: 30, slant: 0.2, pad: 50, splashLen: 6, seed: "t" };
  assert.deepEqual(K.fallAt(9, 10, 100, AREA, o), []);
  assert.deepEqual(K.fallAt(110, 10, 100, AREA, o), []);
  assert.deepEqual(K.fallAt(37, 10, 100, AREA, o), K.fallAt(37, 10, 100, AREA, o));
  const first = K.fallAt(10, 10, 100, AREA, o);
  assert.equal(first.length, 40);
  assert.ok(first.every((d) => d.splash === null), "a splash before anything landed");
  let splashes = 0;
  for (let f = 10; f < 110; f++) {
    for (const d of K.fallAt(f, 10, 100, AREA, o)) {
      assert.ok(d.x >= 100 && d.x < 900 && d.y >= 150 && d.y < 1400, `out of the area: ${d.x}, ${d.y}`);
      if (d.splash) {
        splashes++;
        assert.ok(d.splash.x >= 100 && d.splash.x < 900 && d.splash.age < 6);
      }
    }
  }
  assert.ok(splashes > 0);
});

test("riseAt: bubbles stay inside the area and some pop", () => {
  const o = { n: 12, speed: 6, size: 60, seed: "b" };
  assert.deepEqual(K.riseAt(-1, 0, 200, AREA, o), []);
  let pops = 0;
  for (let f = 0; f < 200; f++) {
    const bs = K.riseAt(f, 0, 200, AREA, o);
    assert.ok(bs.length <= 12);
    for (const b of bs) {
      assert.ok(b.y - b.r >= 200 - 1e-9 && b.y + b.r <= 1400 + 1e-9, `bubble out of the area: ${b.y}`);
      if (b.pop !== null) pops++;
    }
  }
  assert.ok(pops > 0);
  assert.deepEqual(K.riseAt(50, 0, 200, AREA, o), K.riseAt(50, 0, 200, AREA, o));
});

test("writeAt writes line by line, the last character partly", () => {
  assert.deepEqual(K.writeAt("abcd\nef", 0), [0, 0]);
  assert.deepEqual(K.writeAt("abcd\nef", 0.5), [3, 0]);
  assert.deepEqual(K.writeAt("abcd\nef", 1), [4, 2]);
  assert.deepEqual(K.writeAt("abcd\nef", 2), [4, 2]);
  const [a, b] = K.writeAt("abcd\nef", 0.75);
  assert.equal(a, 4);
  assert.ok(Math.abs(b - 0.5) < 1e-9);
});

test("chalkLine is the same for one seed, starts and ends on its points", () => {
  const d = K.chalkLine([0, 0], [400, 100], "s");
  assert.equal(d, K.chalkLine([0, 0], [400, 100], "s"));
  assert.notEqual(d, K.chalkLine([0, 0], [400, 100], "t"));
  assert.ok(d.startsWith("M0.0 0.0"));
  assert.ok(d.trim().endsWith("400.0 100.0"));
});

fs.rmSync(OUT, { recursive: true, force: true });
console.log(failures ? `${failures} failed` : "all passed");
process.exit(failures ? 1 : 0);
