// Every preset (and the example library component) at its meta example, in an 840x700 box and variants: dark ground,
// narrow, wide and short, tall and narrow, small. The dashed line is the clip box; nothing textual may cross it.
// Each still also logs one "@@probe" line (every visible text with its rendered size, every leaf shape) for check.mjs.
import React, { useEffect, useRef, useState } from "react";
import { AbsoluteFill, Composition, continueRender, delayRender } from "remotion";
import { ClipContext } from "@reelsmith/kit";
import { useFontsReady } from "../../src/fonts";
import Arrow from "../../src/presets/Arrow";
import ArrowMeta from "../../src/presets/Arrow.meta.json";
import BarCompare from "../../src/presets/BarCompare";
import BarCompareMeta from "../../src/presets/BarCompare.meta.json";
import CountUp from "../../src/presets/CountUp";
import CountUpMeta from "../../src/presets/CountUp.meta.json";
import DotGrid from "../../src/presets/DotGrid";
import DotGridMeta from "../../src/presets/DotGrid.meta.json";
import EvidenceCard from "../../src/presets/EvidenceCard";
import EvidenceCardMeta from "../../src/presets/EvidenceCard.meta.json";
import Highlighter from "../../src/presets/Highlighter";
import HighlighterMeta from "../../src/presets/Highlighter.meta.json";
import Receipt from "../../src/presets/Receipt";
import ReceiptMeta from "../../src/presets/Receipt.meta.json";
import Stamp from "../../src/presets/Stamp";
import StampMeta from "../../src/presets/Stamp.meta.json";
import TimelineRule from "../../src/presets/TimelineRule";
import TimelineRuleMeta from "../../src/presets/TimelineRule.meta.json";
import PriceTag from "../../../examples/workspace/library/components/PriceTag";
import PriceTagMeta from "../../../examples/workspace/library/components/PriceTag.meta.json";
import RingStat from "./RingStat";
import { fit, FONTS } from "@reelsmith/kit";

type Comp = React.FC<{ props: any }>;
type Meta = { name: string; example: Record<string, unknown>; props: { properties?: Record<string, unknown> } };

const FPS = 30;
const DUR = 90;
// reelsmith/profiles.py PAPER
const THEME = { paper: "#F3EBDD", ink: "#1E1A16", night: "#16130F", snow: "#F7F1E6", accent: "#C8372D", gold: "#D9A441", good: "#2E8B57", bad: "#C8372D", muted: "#7A6F62" };

// what asset ids in the examples stand for: made-up captures under public/ (fixtures.py draws them)
const ARTICLE = { src: "assets/ev_article.png", kind: "evidence", size: [1290, 1489], box: [66, 677, 943, 66], site: "Example Daily" };
const ASSETS: Record<string, object> = {
  ev_article: ARTICLE,
  ev_notice: { src: "assets/ev_notice.png", kind: "evidence", size: [1290, 892], box: [168, 654, 561, 66], site: "Example Mall" },
  ev_host: { ...ARTICLE, site: "www.example.org" },
};

/** What the resolver does to component props, for a clip starting at 0: Times (seconds) to frames, asset ids to refs. */
const prepare = (v: unknown, key = ""): unknown => {
  if (Array.isArray(v)) return v.map((x) => prepare(x));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, prepare(x, k)]));
  if ((key === "at" || key.endsWith("_at")) && typeof v === "number") return Math.round(v * FPS);
  if ((key === "asset" || key.endsWith("_asset")) && typeof v === "string") return ASSETS[v] ?? null;
  return v;
};

const ENTRIES: [Comp, Meta][] = [
  [Receipt, ReceiptMeta], [Stamp, StampMeta], [CountUp, CountUpMeta], [BarCompare, BarCompareMeta],
  [TimelineRule, TimelineRuleMeta], [DotGrid, DotGridMeta], [EvidenceCard, EvidenceCardMeta],
  [Highlighter, HighlighterMeta], [Arrow, ArrowMeta], [PriceTag, PriceTagMeta as Meta],
] as [Comp, Meta][];

const VARIANTS = [
  { id: "base", w: 840, h: 700, dark: false },
  { id: "dark", w: 840, h: 700, dark: true },
  { id: "narrow", w: 420, h: 700, dark: false },
  { id: "wide", w: 840, h: 340, dark: false },
  { id: "tall", w: 320, h: 760, dark: false },
  { id: "small", w: 320, h: 320, dark: false },
];
const M = 40;

/** Something to highlight, so the Highlighter preview shows what it does. */
const SAMPLE = "You keep $960";
const Underlay: React.FC<{ w: number; h: number; dark: boolean }> = ({ w, h, dark }) => (
  <div data-underlay style={{
    position: "absolute", left: M, top: M, width: w, height: h, display: "flex", alignItems: "center", justifyContent: "center",
    fontFamily: FONTS.sans, fontWeight: 900, fontSize: fit(SAMPLE, w * 0.9, h * 0.5, FONTS.sans, 900), color: dark ? THEME.snow : THEME.ink,
    whiteSpace: "pre",
  }}>{SAMPLE}</div>
);

/** The element's own transform: its scale and whether it turns. */
const transformOf = (el: Element): { k: number; turned: boolean } => {
  const t = getComputedStyle(el).transform;
  if (!t || t === "none") return { k: 1, turned: false };
  const m = t.match(/matrix(3d)?\(([^)]+)\)/);
  if (!m) return { k: 1, turned: false };
  const v = m[2].split(",").map(Number);
  return { k: Math.hypot(v[0], v[1]), turned: Math.abs(v[1]) > 1e-3 };
};

/** Every element with its own text (size = computed font size x every ancestor's scale) and every leaf shape. */
const probe = (root: HTMLElement) => {
  const box = root.getBoundingClientRect();
  // n..e: preorder index of the element and the end of its subtree, so a check can tell nesting from overlap
  // q: under a rotation (its rect is the turned box's bounds)
  const texts: { t: string; s: number; r: number[]; o: number; n: number; e: number; q: boolean }[] = [];
  const shapes: { r: number[]; o: number }[] = [];
  let count = 0;
  const walk = (el: Element, opacity: number, scale: number, turned: boolean) => {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    const n = count++;
    const o = opacity * Number(cs.opacity || 1);
    const own = transformOf(el);
    const k = scale * own.k;
    const q = turned || own.turned;
    const rc = el.getBoundingClientRect();
    const r = [rc.left - box.left, rc.top - box.top, rc.width, rc.height].map((v) => Math.round(v * 10) / 10);
    const text = [...el.childNodes].filter((c) => c.nodeType === Node.TEXT_NODE).map((c) => c.textContent ?? "").join("");
    const item = text.trim() ? { t: text, s: Math.round(parseFloat(cs.fontSize) * k * 10) / 10, r, o: Math.round(o * 100) / 100, n, e: n, q } : null;
    if (item) texts.push(item);
    else if (!el.children.length && rc.width > 0 && rc.height > 0 && shapes.length < 600) shapes.push({ r, o: Math.round(o * 100) / 100 });
    for (const c of el.children) walk(c, o, k, q);
    if (item) item.e = count;
  };
  for (const c of root.children) walk(c, 1, 1, false);
  return { texts, shapes };
};

const Stage: React.FC<{ id: string; Comp: Comp; props: unknown; w: number; h: number; dark: boolean; underlay: boolean; locale?: string }> = ({
  id, Comp, props, w, h, dark, underlay, locale = "en",
}) => {
  const ready = useFontsReady();
  const ref = useRef<HTMLDivElement>(null);
  const [handle] = useState(() => delayRender("probe"));
  const done = useRef(false);
  useEffect(() => {
    if (!ready) return;
    if (ref.current) console.debug("@@probe " + JSON.stringify({ id, w, h, ...probe(ref.current) }));
    if (!done.current) continueRender(handle);
    done.current = true;
  });
  return (
    <AbsoluteFill style={{ background: dark ? THEME.night : THEME.paper }}>
      {underlay ? <Underlay w={w} h={h} dark={dark} /> : null}
      <div ref={ref} style={{ position: "absolute", left: M, top: M, width: w, height: h, outline: "2px dashed rgba(120,120,120,0.55)" }}>
        <ClipContext.Provider value={{ w, h, dur: DUR, fps: FPS, theme: THEME, width: w + 2 * M, height: h + 2 * M, safe: { x: 0, y: 0, w: w + 2 * M, h: h + 2 * M }, locale, progress: 0 }}>
          {ready ? <Comp props={props} /> : null}
        </ClipContext.Provider>
      </div>
    </AbsoluteFill>
  );
};

/** Props beyond the examples: other orientations, shapes and edge cases ("x-" ids). */
const EXTRAS: { id: string; Comp: Comp; props: Record<string, unknown>; w: number; h: number; dark?: boolean; underlay?: boolean; locale?: string }[] = [
  // the examples as they were in Chinese, so CJK layout stays covered
  {
    id: "x-Receipt-zh", Comp: Receipt, w: 840, h: 700, locale: "zh-CN",
    props: { header: "RECEIPT · 中奖小票", title: "这份奖品到手多少", rows: [
      { label: "笔记本电脑", value: "¥11,714", sub: "奖品按商家标价计税" }, { label: "运费", value: "包邮" },
      { label: "个税 20%", value: "-¥2,343", tone: "bad" },
    ], total: { label: "到手约", value: "¥9,371" } },
  },
  { id: "x-Stamp-zh", Comp: Stamp, w: 500, h: 500, locale: "zh-CN", props: { text: "真香", rotate: -12 } },
  { id: "x-CountUp-zh", Comp: CountUp, w: 840, h: 700, locale: "zh-CN", props: { value: 12860, suffix: "人", label: "报名百日挑战，全勤的不到一成" } },
  {
    id: "x-BarCompare-zh", Comp: BarCompare, w: 840, h: 700, locale: "zh-CN",
    props: { items: [{ label: "奖品价值", value: 11714 }, { label: "个税", value: 2343, tone: "bad" }, { label: "到手", value: 9371 }], unit: "元" },
  },
  {
    id: "x-TimelineRule-zh", Comp: TimelineRule, w: 840, h: 700, locale: "zh-CN",
    props: { points: [{ when: "第1天", text: "报名百日挑战" }, { when: "第100天", text: "全勤打卡，进抽奖池" }, { when: "第108天", text: "抽中一台笔记本" }], highlight: 2 },
  },
  { id: "x-DotGrid-zh", Comp: DotGrid, w: 840, h: 700, locale: "zh-CN", props: { total: 100, lit: 20, label_lit: "交给个税", label_rest: "落进口袋" } },
  // Latin text at the schemas' longest
  { id: "x-Stamp-two-words", Comp: Stamp, w: 500, h: 500, props: { text: "NOT WORTH IT", shape: "round", double: true } },
  { id: "x-Stamp-one-long-word", Comp: Stamp, w: 500, h: 500, props: { text: "UNBELIEVABLE" } },
  {
    id: "x-CountUp-latin-long", Comp: CountUp, w: 840, h: 700,
    props: { value: 45, prefix: "~", suffix: "minutes a day", label: "spent on the phone before getting out of bed" },
  },
  {
    id: "x-Receipt-latin-long", Comp: Receipt, w: 840, h: 700,
    props: { header: "RECEIPT · WHAT A PRIZE REALLY COSTS", title: "What the grand prize is worth", rows: [
      { label: "Laptop at the list price", value: "$1,200", sub: "the store sets the price the tax is based on" },
      { label: "Delivery to your door", value: "free" }, { label: "Income tax at 20 %", value: "-$240", tone: "bad" },
    ], total: { label: "What you keep", value: "$960" } },
  },
  {
    id: "x-BarCompare-latin-long", Comp: BarCompare, w: 840, h: 700,
    props: { unit: " USD", items: [{ label: "Median household income", value: 80610 }, { label: "Median rural income", value: 66250 }, { label: "Median urban income", value: 84490 }] },
  },
  {
    id: "x-TimelineRule-latin-long", Comp: TimelineRule, w: 840, h: 700,
    props: { points: [
      { when: "January 2024", text: "Rent goes up for the first time, by $200 a month" },
      { when: "June 2024", text: "Graduation season: the busiest month to rent" },
      { when: "October 2024", text: "Back to where it was at the start of the year" },
    ] },
  },
  { id: "x-DotGrid-latin-long", Comp: DotGrid, w: 840, h: 700, props: { total: 50, lit: 12, label_lit: "were refused at the first review", label_rest: "made it through to the interview" } },
  { id: "x-Arrow-latin-long", Comp: Arrow, w: 840, h: 700, props: { from: [0.1, 0.85], to: [0.85, 0.2], label: "the part the buyer never sees", label_pos: "start" } },
  {
    id: "x-EvidenceCard-latin-long-source", Comp: EvidenceCard, w: 840, h: 500,
    props: { asset: "ev_notice", source: "Source: Example Mall member centre, rules of the 100-day challenge, June 2025" },
  },
  { id: "x-EvidenceCard-hostname-zh", Comp: EvidenceCard, w: 840, h: 420, locale: "zh-CN", props: { asset: "ev_host" } },
  { id: "x-TimelineRule-horizontal", Comp: TimelineRule, w: 840, h: 700, props: { ...TimelineRuleMeta.example, orientation: "horizontal" } },
  { id: "x-TimelineRule-horizontal-wide", Comp: TimelineRule, w: 840, h: 340, props: { ...TimelineRuleMeta.example, orientation: "horizontal" } },
  {
    id: "x-TimelineRule-six-long", Comp: TimelineRule, w: 840, h: 700,
    props: { points: [
      { when: "1月", text: "房租第一次上调，每月涨了两百多" }, { when: "3月", text: "再涨" }, { when: "5月", text: "小幅回落，但还是比年初贵" },
      { when: "7月", text: "毕业季租房高峰" }, { when: "9月", text: "跌回年初水平" }, { when: "10月", text: "又涨了，这次是今年最大的一次涨幅" },
    ] },
  },
  {
    id: "x-BarCompare-horizontal", Comp: BarCompare, w: 840, h: 700,
    props: { orientation: "horizontal", unit: "元/杯", items: [
      { label: "上海门店", value: 32.5 }, { label: "北京门店", value: 31.8 }, { label: "深圳门店", value: 33.6 },
      { label: "成都门店", value: 28.5 }, { label: "杭州门店", value: 36.9 },
    ], highlight: 4 },
  },
  {
    id: "x-BarCompare-six-dark", Comp: BarCompare, w: 840, h: 700, dark: true,
    props: { ground: "dark", items: [1, 2, 3, 4, 5, 6].map((i) => ({ label: `第${i}季度营收`, value: i * i * 1234.5 })), unit: "万", highlight: -1 },
  },
  {
    id: "x-BarCompare-long-labels", Comp: BarCompare, w: 840, h: 700,
    props: { unit: "元", items: [{ label: "城镇居民中位数", value: 39728 }, { label: "农村居民中位数", value: 15895 }, { label: "全国中位数", value: 28388 }] },
  },
  {
    id: "x-BarCompare-vertical-tall", Comp: BarCompare, w: 320, h: 760,
    props: { ...BarCompareMeta.example, orientation: "vertical" },
  },
  { id: "x-CountUp-down-left", Comp: CountUp, w: 840, h: 400, props: { value: 9371.4, from: 11714, prefix: "¥", align: "left", color: "bad", label: "扣完税" } },
  { id: "x-CountUp-percent-nolabel", Comp: CountUp, w: 600, h: 300, props: { value: 20, suffix: "%", underline: false } },
  { id: "x-CountUp-late", Comp: CountUp, w: 840, h: 400, props: { value: 12999, prefix: "¥", suffix: "元", label: "起售价", at: 1, dur: 1.2 } },
  { id: "x-DotGrid-20-square", Comp: DotGrid, w: 840, h: 400, props: { total: 20, lit: 7, shape: "square", counter: false } },
  { id: "x-DotGrid-400", Comp: DotGrid, w: 840, h: 700, props: { total: 400, lit: 123, label_lit: "人中签" } },
  { id: "x-DotGrid-late", Comp: DotGrid, w: 840, h: 700, props: { ...DotGridMeta.example, at: 1, dur: 1 } },
  {
    id: "x-Receipt-seven-plain", Comp: Receipt, w: 840, h: 700,
    props: { rows: [1, 2, 3, 4, 5, 6, 7].map((i) => ({ label: `第${i}项支出明细`, value: `¥${i * 123},456.00` })), total: { label: "合计", value: "¥3,456,789.00" } },
  },
  { id: "x-Stamp-four-round", Comp: Stamp, w: 500, h: 500, props: { text: "血亏到底", shape: "round", double: true, rotate: 8 } },
  { id: "x-Stamp-dark", Comp: Stamp, w: 500, h: 500, dark: true, props: { text: "不值", ground: "dark", color: "gold" } },
  { id: "x-EvidenceCard-notice-tight", Comp: EvidenceCard, w: 840, h: 300, props: { asset: "ev_notice", context: 0, source: "Source: example.com" } },
  { id: "x-EvidenceCard-hostname", Comp: EvidenceCard, w: 840, h: 420, props: { asset: "ev_host" } },
  { id: "x-EvidenceCard-long-source", Comp: EvidenceCard, w: 840, h: 500, props: { asset: "ev_notice", source: "来源：示例市示例区示例商场会员中心 2025年6月30日活动规则" } },
  { id: "x-Highlighter-underline-line", Comp: Highlighter, w: 840, h: 160, underlay: true, props: { shape: "underline", color: "accent" } },
  { id: "x-Highlighter-block-left", Comp: Highlighter, w: 840, h: 160, underlay: true, props: { direction: "left" } },
  { id: "x-Highlighter-marker-line", Comp: Highlighter, w: 840, h: 160, underlay: true, props: { shape: "marker" } },
  {
    id: "x-Arrow-dashed-end", Comp: Arrow, w: 840, h: 700,
    props: { from: [0.9, 0.9], to: [0.15, 0.1], curve: -0.4, dashed: true, label: "从这里涨上去", label_pos: "end", label_style: "plain" },
  },
  { id: "x-Arrow-straight-edges", Comp: Arrow, w: 840, h: 300, props: { from: [0, 0.5], to: [1, 0.5], curve: 0, label: "全程", label_pos: "end" } },
  { id: "x-Arrow-long-label-tall", Comp: Arrow, w: 320, h: 760, props: { from: [0.2, 0.9], to: [0.8, 0.15], label: "比去年同期多出来的这笔钱", label_pos: "start" } },
  { id: "x-PriceTag-600x500", Comp: PriceTag, w: 600, h: 500, props: PriceTagMeta.example },
  // docs/kit.md's complete component, kept in step by check.mjs
  { id: "x-RingStat-doc", Comp: RingStat, w: 600, h: 700, props: { pct: 62, label: "live in cities", at: 0.3 } },
  { id: "x-RingStat-doc-dark", Comp: RingStat, w: 600, h: 700, dark: true, props: { pct: 62, label: "live in cities", ground: "dark" } },
  { id: "x-Arrow-empty", Comp: Arrow, w: 840, h: 300, props: { from: [0.5, 0.5], to: [0.5, 0.5] } },
  { id: "x-BarCompare-empty", Comp: BarCompare, w: 840, h: 300, props: { items: [] } },
  { id: "x-EvidenceCard-missing", Comp: EvidenceCard, w: 840, h: 300, props: { asset: "nope" } },
];

export const Root: React.FC = () => (
  <>
    {EXTRAS.map((x) => (
      <Composition
        key={x.id}
        id={x.id}
        component={() => <Stage id={x.id} Comp={x.Comp} props={prepare(x.props)} w={x.w} h={x.h} dark={!!x.dark} underlay={!!x.underlay} locale={x.locale} />}
        durationInFrames={DUR}
        fps={FPS}
        width={x.w + 2 * M}
        height={x.h + 2 * M}
      />
    ))}
    {ENTRIES.flatMap(([Comp, meta]) =>
      VARIANTS.map((v) => {
        const hasGround = !!meta.props.properties && "ground" in meta.props.properties;
        const props = prepare(v.dark && hasGround ? { ...meta.example, ground: "dark" } : meta.example);
        const id = `${meta.name}-${v.id}`;
        return (
          <Composition
            key={id}
            id={id}
            component={() => <Stage id={id} Comp={Comp} props={props} w={v.w} h={v.h} dark={v.dark} underlay={meta.name === "Highlighter"} />}
            durationInFrames={DUR}
            fps={FPS}
            width={v.w + 2 * M}
            height={v.h + 2 * M}
          />
        );
      }),
    )}
  </>
);
