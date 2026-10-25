// Preset regression checks on rendered stills: node test/presets-preview/check.mjs [out dir]   (cwd: renderer/)
// Renders every preview composition (settled frame 89, plus timing frames), reads each still's @@probe (visible texts
// with rendered size and rect, leaf shapes) and checks sizes, overlaps, the box edge and timing. ~2 minutes.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getCompositions } from "@remotion/renderer";
import { bundlePreview, renderJobs } from "./bundle.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] ? path.resolve(process.argv[2]) : fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-presets-"));
const SETTLED = 89;
// early in a count the number has fewer digits than where it lands
const TIMING = { "x-CountUp-late": [15, 31, 40], "CountUp-base": [3], "x-DotGrid-late": [15, 40] };

const serveUrl = await bundlePreview();
const ids = (await getCompositions(serveUrl)).map((c) => c.id);
const jobs = ids.flatMap((id) => [SETTLED, ...(TIMING[id] ?? [])].map((frame) => ({ id, frame })));
const t0 = Date.now();
const { probes, errors } = await renderJobs(serveUrl, jobs, out);
fs.writeFileSync(path.join(out, "probes.json"), JSON.stringify(probes, null, 1));
console.log(`${jobs.length} stills in ${((Date.now() - t0) / 1000).toFixed(0)} s -> ${out}`);

let failures = 0;
const check = (cond, what) => {
  if (cond) return;
  failures++;
  console.log(`  FAIL ${what}`);
};
const probeOf = (id, frame = SETTLED) => probes[`${id}_${frame}`];
const shown = (p) => (p ? p.texts.filter((t) => t.o > 0.1 && t.s > 0 && t.r[2] > 0) : []);
const linesOf = (t) => t.t.split("\n").map((l) => l.trim()).filter(Boolean);
const minSize = (ts) => Math.min(...ts.map((t) => t.s));
const nested = (a, b) => (a.n < b.n && b.n < a.e) || (b.n < a.n && a.n < b.e);
const fmtT = (t) => `"${t.t.replace(/\n/g, "/")}" ${t.s}px`;

check(errors.length === 0, `browser errors: ${errors.slice(0, 5).join(" | ")}`);
check(Object.values(probes).every(Boolean), `every still logged a probe (${Object.keys(probes).filter((k) => !probes[k]).join(", ")})`);

console.log("every still: text inside the box, no text over text");
for (const id of ids) {
  const p = probeOf(id);
  if (!p) continue;
  const ts = shown(p);
  // an inline run's rect is its font's content area, taller than the ink: allow that much
  const slack = (t) => Math.max(2, 0.12 * t.s);
  for (const t of ts) {
    const [x, y, w, h] = t.r;
    const k = slack(t);
    check(x >= -k && y >= -k && x + w <= p.w + k && y + h <= p.h + k, `${id}: ${fmtT(t)} crosses the box edge (${t.r.join(",")})`);
  }
  for (let i = 0; i < ts.length; i++) {
    for (let j = i + 1; j < ts.length; j++) {
      const [a, b] = [ts[i], ts[j]];
      if (nested(a, b) || (a.q && b.q)) continue;
      const ox = Math.min(a.r[0] + a.r[2], b.r[0] + b.r[2]) - Math.max(a.r[0], b.r[0]);
      const oy = Math.min(a.r[1] + a.r[3], b.r[1] + b.r[3]) - Math.max(a.r[1], b.r[1]);
      check(!(ox > 2 && oy > slack(a) + slack(b)), `${id}: ${fmtT(a)} overlaps ${fmtT(b)}`);
    }
  }
}

console.log("example props in an 840x700 box: nothing under 24 px (the library PriceTag: 40 px)");
for (const id of ids.filter((i) => /-(base|dark)$/.test(i) || i === "x-PriceTag-600x500")) {
  const ts = shown(probeOf(id));
  if (!ts.length) continue;
  const floor = id.startsWith("PriceTag") ? 40 : 24;
  const small = ts.filter((t) => t.s < floor);
  check(!small.length, `${id}: text under ${floor} px: ${small.map(fmtT).join(", ")}`);
}

console.log("EvidenceCard: the source line is never under 28 px; a hostname loses its www.");
for (const id of ids.filter((i) => i.includes("EvidenceCard") && !i.includes("missing"))) {
  const ts = shown(probeOf(id));
  check(ts.length > 0, `${id}: a source line shows`);
  for (const t of ts) check(t.s >= 28, `${id}: source ${fmtT(t)} is under 28 px`);
}
// the default lead-in follows the locale
for (const [id, want] of [["x-EvidenceCard-hostname", "Source: example.org"], ["x-EvidenceCard-hostname-zh", "来源：example.org"]]) {
  const got = shown(probeOf(id)).map((t) => t.t).join("");
  check(got === want, `${id}: the source reads ${want} (${got})`);
}

console.log("Arrow: the label is never under 28 px");
for (const id of ids.filter((i) => i.includes("Arrow") && !i.includes("empty"))) {
  const ts = shown(probeOf(id));
  check(ts.length > 0, `${id}: a label shows`);
  for (const t of ts) check(t.s >= 28, `${id}: label ${fmtT(t)} is under 28 px`);
}

console.log("BarCompare: labels never larger than values, a clear gap between neighbours, legible in tall boxes");
const LABELS = {
  "x-BarCompare-horizontal": ["上海门店", "北京门店", "深圳门店", "成都门店", "杭州门店"],
  "x-BarCompare-six-dark": [1, 2, 3, 4, 5, 6].map((i) => `第${i}季度营收`),
  "x-BarCompare-long-labels": ["城镇居民中位数", "农村居民中位数", "全国中位数"],
  "x-BarCompare-zh": ["奖品价值", "个税", "到手"],
  "x-BarCompare-latin-long": ["Median household income", "Median rural income", "Median urban income"],
};
const squash = (s) => s.replace(/\s+/g, "");
for (const id of ids.filter((i) => i.includes("BarCompare") && !i.includes("empty"))) {
  const names = LABELS[id] ?? ["Coffee", "Jeans", "T-shirt"];
  const ts = shown(probeOf(id));
  // a label may wrap to two lines: compare without the spaces
  const isLabel = (t) => names.map(squash).includes(squash(linesOf(t).join("")));
  const labels = ts.filter(isLabel);
  const values = ts.filter((t) => !isLabel(t));
  check(labels.length === names.length && values.length === names.length, `${id}: ${names.length} labels and values (${ts.map(fmtT).join(", ")})`);
  if (!labels.length || !values.length) continue;
  check(Math.max(...labels.map((t) => t.s)) <= minSize(values) + 0.5,
    `${id}: a label is larger than a value (labels ${labels.map((t) => t.s).join("/")}, values ${values.map((t) => t.s).join("/")})`);
  // forced columns in a narrow box are the author's call
  if (id !== "x-BarCompare-vertical-tall") check(minSize(ts) >= 24, `${id}: text under 24 px: ${ts.filter((t) => t.s < 24).map(fmtT).join(", ")}`);
  for (let i = 0; i < ts.length; i++) {
    for (let j = i + 1; j < ts.length; j++) {
      const [a, b] = [ts[i], ts[j]];
      const oy = Math.min(a.r[1] + a.r[3], b.r[1] + b.r[3]) - Math.max(a.r[1], b.r[1]);
      if (oy <= 2) continue;
      const gap = Math.max(a.r[0], b.r[0]) - Math.min(a.r[0] + a.r[2], b.r[0] + b.r[2]);
      const need = Math.max(12, 0.25 * Math.min(a.s, b.s));
      check(gap >= need, `${id}: ${fmtT(a)} and ${fmtT(b)} side by side ${gap.toFixed(0)} px apart (need ${need.toFixed(0)})`);
    }
  }
}

console.log("CountUp: nothing before `at`, then the number never re-centres while it counts");
{
  check(shown(probeOf("x-CountUp-late", 15)).length === 0, `x-CountUp-late @15 (before at): ${shown(probeOf("x-CountUp-late", 15)).map(fmtT).join(", ")}`);
  for (const [id, mid] of [["x-CountUp-late", 31], ["x-CountUp-late", 40], ["CountUp-base", 3]]) {
    const a = shown(probeOf(id, mid));
    const b = shown(probeOf(id));
    const pin = (ts, s) => ts.find((t) => t.t === s);
    const digits = (ts) => ts.find((t) => /^[\d,.]+$/.test(t.t));
    if (mid !== 40) {
      check(digits(a) && digits(b) && digits(a).t.replace(/\D/g, "").length < digits(b).t.replace(/\D/g, "").length,
        `${id} @${mid}: fewer digits early in the count (${digits(a)?.t} -> ${digits(b)?.t})`);
    }
    // the suffix and the digits' right edge stay put (the prefix rides the digits)
    const [sa, sb] = [pin(a, id === "CountUp-base" ? "people" : "元"), pin(b, id === "CountUp-base" ? "people" : "元")];
    check(sa && sb && Math.abs(sa.r[0] - sb.r[0]) <= 1, `${id}: the suffix at x ${sa?.r[0]} @${mid} and ${sb?.r[0]} landed`);
    const right = (t) => (t ? t.r[0] + t.r[2] : NaN);
    check(Math.abs(right(digits(a)) - right(digits(b))) <= 1, `${id}: digits end at x ${right(digits(a))} @${mid} and ${right(digits(b))} landed`);
    if (id !== "CountUp-base") {
      const [pa, da] = [pin(a, "¥"), digits(a)];
      check(pa && da && da.r[0] - (pa.r[0] + pa.r[2]) <= 2, `${id} @${mid}: the prefix sits against the digits`);
    }
  }
}

console.log("DotGrid: no counter or legend before the lighting starts; full rows");
{
  const before = probeOf("x-DotGrid-late", 15);
  check(shown(before).length === 0, `x-DotGrid-late @15 (before at): ${shown(before).map(fmtT).join(", ")}`);
  check((before?.shapes ?? []).filter((s) => s.o > 0.1).length >= 50, "x-DotGrid-late @15: the dots are already there");
  const after = shown(probeOf("x-DotGrid-late", 40)).map((t) => t.t).join("|");
  check(after.includes("go to tax") && after.includes("stay in your pocket"), `x-DotGrid-late @40: counter and legend once lighting starts (${after})`);
  // lit dots are drawn a little larger: count column centres
  const cols = (id) => new Set((probeOf(id)?.shapes ?? []).filter((s) => s.r[2] > 4 && Math.abs(s.r[2] - s.r[3]) < 1).map((s) => Math.round(s.r[0] + s.r[2] / 2))).size;
  check(cols("DotGrid-tall") === 10, `DotGrid-tall: 100 dots in 10 columns (got ${cols("DotGrid-tall")})`);
  check(cols("DotGrid-base") === 10, `DotGrid-base: 100 dots in 10 columns (got ${cols("DotGrid-base")})`);
}

console.log("TimelineRule and every two-line split: never inside a word");
for (const id of ids) {
  for (const t of shown(probeOf(id))) {
    for (const bad of ["报名百", "日挑战", "抽中一", "记本", "奖池"]) {
      check(!linesOf(t).includes(bad), `${id}: a line reads "${bad}" (${fmtT(t)})`);
    }
  }
}

console.log("Latin text: a one-word stamp stays whole, words split only between words, a word suffix keeps a word space");
{
  const lines = (id) => shown(probeOf(id)).map((t) => t.t.trim());
  check(lines("Stamp-base").join("|") === "APPROVED", `Stamp-base: one line APPROVED (${lines("Stamp-base").join("|")})`);
  check(lines("x-Stamp-one-long-word").join("|") === "UNBELIEVABLE", `x-Stamp-one-long-word: one line (${lines("x-Stamp-one-long-word").join("|")})`);
  const two = lines("x-Stamp-two-words");
  check(two.length === 2 && two.join(" ") === "NOT WORTH IT", `x-Stamp-two-words: two lines of whole words (${two.join("|")})`);
  const cu = shown(probeOf("CountUp-base"));
  const suf = cu.find((t) => t.t === "people");
  const dig = cu.find((t) => /^[\d,.]+$/.test(t.t));
  const gap = suf && dig ? suf.r[0] - (dig.r[0] + dig.r[2]) : NaN;
  check(gap >= 0.08 * (dig?.s ?? 0), `CountUp-base: a word space between the digits and "people" (${gap} px)`);
}

console.log("docs/kit.md: every kit export documented, the complete component is RingStat.tsx and renders");
{
  const doc = fs.readFileSync(path.resolve(here, "..", "..", "..", "docs", "kit.md"), "utf8").replace(/\r\n/g, "\n");
  const index = fs.readFileSync(path.resolve(here, "..", "..", "src", "kit", "index.ts"), "utf8");
  const names = [...index.matchAll(/export (?:type )?\{([^}]*)\}/g)].flatMap((m) => m[1].split(",").map((s) => s.trim()).filter(Boolean));
  check(names.length > 20, `kit exports read from index.ts (${names.length})`);
  for (const n of names) check(doc.includes(`\`${n}`), `docs/kit.md documents \`${n}\``);
  const block = doc.match(/```tsx\n(\/\/ library\/components\/RingStat\.tsx[\s\S]*?)```/);
  const file = fs.readFileSync(path.join(here, "RingStat.tsx"), "utf8").replace(/\r\n/g, "\n");
  check(block && block[1].trim() === file.trim(), "the tsx block in docs/kit.md equals test/presets-preview/RingStat.tsx");
  const meta = doc.match(/```json\n(\{"name": "RingStat"[\s\S]*?)```/);
  let ok = false;
  try {
    ok = JSON.parse(meta[1]).name === "RingStat";
  } catch {
    ok = false;
  }
  check(ok, "the RingStat meta.json block in docs/kit.md is JSON");
  const ring = shown(probeOf("x-RingStat-doc")).map((t) => t.t);
  check(ring.includes("62%") && ring.includes("live in cities"), `RingStat renders its number and label (${ring.join(", ")})`);
}

// a temporary folder goes when everything passed; a folder you named stays
const keep = Boolean(process.argv[2]) || failures > 0;
if (!keep) fs.rmSync(out, { recursive: true, force: true });
console.log(failures ? `${failures} FAILED (stills and probes.json in ${out})` : keep ? `all ok (stills in ${out})` : "all ok");
process.exit(failures ? 1 : 0);
