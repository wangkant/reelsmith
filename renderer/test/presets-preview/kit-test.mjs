// Unit checks for the pure @reelsmith/kit helpers (no browser): node test/presets-preview/kit-test.mjs  (cwd: renderer/)
// The pure exports are bundled with esbuild; CSS imports are dropped and DOM measuring falls back, so only logic is
// checked here (check.mjs checks what renders).
import { build } from "esbuild";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const renderer = path.resolve(here, "..", "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-kit-"));
const out = path.join(tmp, "helpers.mjs");
// the kit's pure exports (index.ts also re-exports React elements, which need a page)
const entry = [
  'export * from "./src/kit/helpers.ts";',
  'export { FONTS, fontFamily } from "./src/fonts.ts";',
  'export { breakLines } from "./src/elements/linebreak.ts";',
].join("\n");
await build({
  stdin: { contents: entry, resolveDir: renderer, loader: "ts", sourcefile: "kit-entry.ts" },
  bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "error",
  loader: { ".css": "empty", ".woff2": "empty" },
  external: ["remotion", "@remotion/*", "react", "react-dom"],
  nodePaths: [path.join(renderer, "node_modules")],
});
// externals resolve from renderer/node_modules
fs.symlinkSync(path.join(renderer, "node_modules"), path.join(tmp, "node_modules"), "junction");
const kit = await import(pathToFileURL(out).href);

let failures = 0;
const check = (cond, what) => {
  if (cond) console.log(`  ok   ${what}`);
  else {
    failures++;
    console.log(`  FAIL ${what}`);
  }
};
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log("twoLines");
{
  const t = (s, maxOne = 3) => kit.twoLines(s, maxOne);
  const never = [
    ["报名百日挑战", ["报名百", "日挑战"]],
    ["抽中一吨汽油", ["抽中一", "吨汽油"]],
    ["全国居民人均可支配收入34230元", null],
    ["按92号汽油密度0.725换算", null],
    ["原来税后只剩九千三百七十一块钱", null],
    ["iPhone 17 Pro 售价 8999 元", null],
    ["他说：“这不对。”然后走了", null],
  ];
  for (const [s, bad] of never) {
    const r = t(s);
    const joined = r.join("");
    check(joined.replace(/\s/g, "") === s.replace(/\s/g, ""), `${s}: nothing lost (${r.join(" / ")})`);
    if (bad) check(!eq(r, bad), `${s}: not split as ${bad.join("/")}`);
    check(!/^[，。、：；？！”’）》」』%]/.test(r[1] ?? ""), `${s}: second line does not start with closing punctuation`);
    check(!/[0-9０-９零一二三四五六七八九十百千万亿两]$/.test(r[0]) || !r[1] || /^[\s，。]/.test(r[1]) || /^[A-Za-z]/.test(r[1]),
      `${s}: no number cut from its unit (${r.join(" / ")})`);
  }
  check(eq(t("报名百日挑战"), ["报名", "百日挑战"]) || eq(t("报名百日挑战"), ["报名百日", "挑战"]), `报名百日挑战 -> ${t("报名百日挑战").join("/")}`);
  check(eq(t("百公里8升，能开这么远"), ["百公里8升，", "能开这么远"]), `punctuation wins: ${t("百公里8升，能开这么远").join("/")}`);
  check(eq(t("奖品价值"), ["奖品", "价值"]), "奖品价值 -> 奖品/价值");
  check(eq(t("个税"), ["个税"]), "short text stays one line");
  check(eq(t("第100天", 2), ["第100天"]), "第100天 is never split");
  check(eq(t("10月22日", 2), ["10月", "22日"]), `10月22日 -> ${t("10月22日", 2).join("/")}`);
  check(eq(kit.twoLines("短", 0), ["短"]), "one character stays");
  check(eq(kit.twoLines("", 0), [""]), "empty stays");
}

console.log("fonts");
{
  check(eq(Object.keys(kit.FONTS).sort(), ["display", "sans", "serif", "zcool"]), `FONTS has sans, serif, display, zcool (${Object.keys(kit.FONTS)})`);
  check(/Smiley Sans/.test(kit.FONTS.display) && /ZCOOL/.test(kit.FONTS.zcool), "display is Smiley Sans, zcool is ZCOOL QingKe HuangYou");
  check(kit.fontFamily("display") === kit.FONTS.display && kit.fontFamily("") === kit.FONTS.sans, "fontFamily maps keys, empty is sans");
}

console.log("breakLines");
{
  const lines = kit.breakLines("全国居民人均可支配收入34230元，比上年增长5.2%", 300, (s) => [...s].length * 30);
  check(lines.join("") === "全国居民人均可支配收入34230元，比上年增长5.2%" && lines.length >= 2, `breakLines keeps the text (${lines.join(" / ")})`);
  check(lines.every((l) => !/^[，。]/.test(l)) && !lines.some((l) => l.endsWith("34230")), "no line starts with punctuation or leaves a number without its unit");
}

console.log("words");
{
  check(kit.words("抽中一吨汽油").join("") === "抽中一吨汽油", "words join back to the text");
  check(kit.words("").length === 0, "no words in an empty string");
}

console.log("fitLines");
{
  check(kit.fit("标题", NaN, 56) === 0 && kit.fit("标题", Infinity, 56) === 0 && kit.fit("标题", 300, NaN) === 0,
    "fit: an unmeasured box gives 0, never a search");
  check(kit.textWidth("标题", NaN) === 0, "textWidth: NaN size gives 0");
  // no DOM here: fit() falls back to width / characters
  const one = kit.fitLines("短标签", 300, 56, 28);
  check(one.lines.length === 1 && one.size === 56, `short text: one line at the cap (${JSON.stringify(one)})`);
  const two = kit.fitLines("这是一个很长很长的箭头标签文字", 300, 56, 28);
  check(two.lines.length === 2 && two.size > kit.fit("这是一个很长很长的箭头标签文字", 300, 56), `long text: two lines, larger (${JSON.stringify(two)})`);
}

console.log("numbers, props, colours");
{
  check(kit.fmt(17125) === "17,125" && kit.fmt(9371.4, 1) === "9,371.4" && kit.fmt(1234, 0, false) === "1234", "fmt");
  check(kit.decimalsOf(2.5) === 1 && kit.decimalsOf(3) === 0, "decimalsOf");
  check(kit.numOr("3", 7) === 7 && kit.numOr(3, 7) === 3 && kit.frameOr(undefined, 12) === 12, "numOr / frameOr");
  check(kit.toFrames(1.5, 30) === 45, "toFrames");
  check(eq(kit.spread(3, 0, 10), [0, 5, 10]) && eq(kit.spread(1, 4, 9), [4]), "spread");
  const theme = { paper: "#F3EBDD", ink: "#1E1A16", night: "#16130F", snow: "#F7F1E6", accent: "#C8372D", gold: "#D9A441", good: "#2E8B57", bad: "#C8372D", muted: "#7A6F62" };
  check(kit.themeColor(theme, "gold") === "#D9A441" && kit.themeColor(theme, "#123456") === "#123456" && kit.themeColor(theme, "", "ink") === "#1E1A16", "themeColor");
  check(kit.withAlpha("#ffffff", 0.5) === "rgba(255,255,255,0.5)", "withAlpha");
  check(kit.onGround(theme, "dark").ink === theme.snow && kit.onGround(theme).ink === theme.ink, "onGround");
  check(kit.isAsset({ src: "assets/a.png" }) && !kit.isAsset(null) && !kit.isAsset("a"), "isAsset");
  check(kit.ease(0, 10, 20) === 0 && kit.ease(30, 10, 20) === 1 && kit.ease(15, 10, 10) === 1, "ease holds its ends");
  check(kit.springAt(5, 10) === 0 && kit.springAt(200, 10) > 0.99, "springAt");
}

fs.rmSync(tmp, { recursive: true, force: true });
console.log(failures ? `${failures} FAILED` : "all ok");
process.exit(failures ? 1 : 0);
