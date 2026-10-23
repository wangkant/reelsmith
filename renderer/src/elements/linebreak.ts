// Word-aware line breaking for Chinese and mixed text: Intl.Segmenter("zh") words glued into pieces no break may
// enter, then lines filled greedily (preferring punctuation) or balanced to a given count. Pure: widths come from
// the caller, so Node can test it too.

const segmenter = typeof Intl !== "undefined" && "Segmenter" in Intl ? new Intl.Segmenter("zh", { granularity: "word" }) : null;

/** Intl.Segmenter("zh") words, spaces included (split on spaces where there is no segmenter). */
export const wordSegments = (text: string): string[] =>
  segmenter ? [...segmenter.segment(text)].map((x) => x.segment) : text.split(/(\s+)/).filter(Boolean);

const CLOSING = /^[，、：；？！。,.:;?!）)\]】》」』”’〉%‰℃°…—]+$/u;
const OPENING = /^[（(\[【《「『“‘〈¥$€£￥＄]+$/u;
const NUMERIC = /^[+\-−]?[0-9０-９]+(?:[.,:：/][0-9０-９]+)*$/u;
const CN_NUM = /^[零〇一二三四五六七八九十百千万亿两几]+$/u;
const CN_LEAD = /^[零〇一二三四五六七八九十百千万亿两几]+/u;
// glued to the number after them ("百分之五", "第3")
const BEFORE_NUM = /(?:分之|^第)$/u;
// what may follow a number and stay with it: a sign, 1-3 Latin letters (kg, GB) or a measure word (the list the
// caption splitter in resolve.py keeps with its number)
const UNITS = new Set([
  "块钱", "元钱", "美元", "港元", "日元", "欧元", "英镑", "平方米", "平米", "平方", "立方", "公里", "千米", "厘米", "毫米",
  "公斤", "千克", "毫升", "小时", "分钟", "个月", "元", "块", "角", "毛", "分", "号", "个", "只", "条", "张", "件", "位",
  "名", "人", "次", "倍", "成", "年", "月", "日", "天", "周", "岁", "吨", "斤", "克", "升", "米", "亩", "套", "台", "辆",
  "部", "家", "所", "款", "项", "杯", "瓶", "箱", "包", "页", "层", "楼", "度", "秒", "折", "股", "份", "篇", "本", "批",
  "颗", "粒", "口", "碗", "盒", "袋", "点", "时", "钱",
]);
const isUnit = (s: string) => UNITS.has(s) || /^(?:[%‰℃°]|[A-Za-z]{1,3})$/u.test(s);
const APPROX = /^[多余]$/u;
const PREFER = /[，。！？；：,.!?;:、…][”’」』)）]*$/u;

type Glued = { text: string; space: boolean; num: boolean; open: boolean };

/** Word segments glued into unbreakable pieces: closing punctuation stays with the word before it, an opening bracket
 *  or currency sign with the word after, a number with its digits, unit and approximators ("1.5万公里", "8999 元",
 *  "九千三百七十一元", "百分之五"). Spaces are their own pieces (a line may break there). */
export const pieces = (text: string): Array<{ text: string; space: boolean }> => {
  const segs = wordSegments(text);
  const out: Glued[] = [];
  for (const seg of segs) {
    const n = out.length;
    const last = n ? out[n - 1] : null;
    if (/^\s+$/u.test(seg)) {
      out.push({ text: seg, space: true, num: false, open: false });
      continue;
    }
    // "七十一", or a numeral word with its unit ("一元", "三块")
    const lead = seg.match(CN_LEAD)?.[0] ?? "";
    const numeric = NUMERIC.test(seg) || CN_NUM.test(seg) || (lead.length > 0 && isUnit(seg.slice(lead.length)));
    const unit = isUnit(seg);
    const open = OPENING.test(seg) || BEFORE_NUM.test(seg);
    if (last && !last.space) {
      // "百分" + "之" + "五"
      if (seg === "之" && /分$/u.test(last.text)) {
        last.text += seg;
        last.num = false;
        last.open = true;
        continue;
      }
      if (CLOSING.test(seg)) {
        last.text += seg;
        last.num = false;
        last.open = false;
        continue;
      }
      if (last.open || (last.num && (numeric || unit))) {
        last.text += seg;
        last.num = numeric || (last.num && APPROX.test(seg));
        last.open = open;
        continue;
      }
    } else if (last && last.text === " " && unit && n >= 2 && out[n - 2].num) {
      out.pop();
      out[n - 2].text += ` ${seg}`;
      out[n - 2].num = false;
      continue;
    }
    out.push({ text: seg, space: false, num: numeric, open });
  }
  return out.map((g) => ({ text: g.text, space: g.space }));
};

/** A piece no line break may enter, its width (in whatever unit `measure` gives), and its length in characters. */
export type Unit = { text: string; space: boolean; w: number; n: number; prefer: boolean };

export const unitsOf = (text: string, measure: (s: string) => number): Unit[] =>
  pieces(text).map((p) => ({ text: p.text, space: p.space, w: measure(p.text), n: [...p.text].length, prefer: PREFER.test(p.text) }));

/** Units [a, b) of one line. */
export type Range = [number, number];

/** Sums over units [a, b) without the spaces at either end. */
export const makeSpan = (u: Unit[]) => {
  const W = [0];
  const N = [0];
  for (const x of u) {
    W.push(W[W.length - 1] + x.w);
    N.push(N[N.length - 1] + x.n);
  }
  return (a: number, b: number) => {
    while (a < b && u[a].space) a++;
    while (b > a && u[b - 1].space) b--;
    return { a, b, w: W[b] - W[a], n: N[b] - N[a] };
  };
};

/** Whether a line of summed width `w` and `n` characters fits. */
export type Fits = (w: number, n: number) => boolean;

/** Lines filled about as far as each goes, breaking after punctuation instead when that keeps the line 3/4 full;
 *  null when one piece alone is too wide. */
export const greedy = (u: Unit[], fits: Fits): Range[] | null => {
  const span = makeSpan(u);
  const lines: Range[] = [];
  let a = 0;
  for (let i = 0; i < u.length; i++) {
    if (u[i].space) continue;
    const s = span(a, i + 1);
    if (fits(s.w, s.n)) continue;
    const before = span(a, i);
    if (before.b > before.a) {
      let cut = i;
      for (let j = i - 1; j > before.a; j--) {
        if (u[j - 1].prefer && span(a, j).w >= 0.75 * before.w) {
          cut = j;
          break;
        }
      }
      const line = span(a, cut);
      lines.push([line.a, line.b]);
      a = cut;
      i = cut - 1;
      continue;
    }
    const alone = span(i, i + 1);
    if (!fits(alone.w, alone.n)) return null;
  }
  const rest = span(a, u.length);
  lines.push([rest.a, rest.b]);
  return lines;
};

/** The same text in exactly k lines of near-equal width (after punctuation when that costs little); null when it
 *  cannot be done. */
export const balanced = (u: Unit[], k: number, fits: Fits): Range[] | null => {
  const span = makeSpan(u);
  const n = u.length;
  const total = span(0, n).w;
  if (k <= 1 || total <= 0) return null;
  const avg = total / k;
  const penalty = (i: number) => {
    let j = i - 1;
    while (j > 0 && u[j].space) j--;
    if (u[j].prefer) return -0.12 * avg;
    return u[i - 1].space || u[i].space ? 0 : 0.03 * avg;
  };
  type Cell = { max: number; pen: number; prev: number } | null;
  const dp: Cell[][] = Array.from({ length: k + 1 }, () => Array<Cell>(n + 1).fill(null));
  dp[0][0] = { max: 0, pen: 0, prev: -1 };
  for (let j = 1; j <= k; j++) {
    for (let i = 1; i <= n; i++) {
      if ((j < k && i === n) || (j === k && i !== n)) continue;
      let best: Cell = null;
      for (let a = j - 1; a < i; a++) {
        const p = dp[j - 1][a];
        if (!p) continue;
        const s = span(a, i);
        if (s.b <= s.a || !fits(s.w, s.n)) continue;
        const cell = { max: Math.max(p.max, s.w), pen: p.pen + (a > 0 ? penalty(a) : 0), prev: a };
        if (!best || cell.max + cell.pen < best.max + best.pen) best = cell;
      }
      dp[j][i] = best;
    }
  }
  if (!dp[k][n]) return null;
  const cuts: number[] = [];
  for (let j = k, i = n; j > 0; j--) {
    cuts.unshift(i);
    i = (dp[j][i] as NonNullable<Cell>).prev;
  }
  const out: Range[] = [];
  let a = 0;
  for (const b of cuts) {
    const s = span(a, b);
    out.push([s.a, s.b]);
    a = b;
  }
  return out;
};

/** `text` broken into lines no wider than `width` (widths from `measure`), greedy or balanced: the same rules the
 *  text clip uses, for components that lay out their own labels. A piece wider than `width` gets a line of its own. */
export const breakLines = (text: string, width: number, measure: (s: string) => number, balance = false): string[] => {
  const u = unitsOf(text, measure);
  if (!u.length) return [text];
  const widest = Math.max(width, ...u.map((x) => x.w));
  const fits: Fits = (w) => w <= widest;
  const g = greedy(u, fits) ?? [[0, u.length] as Range];
  const ranges = balance && g.length > 1 ? balanced(u, g.length, fits) ?? g : g;
  return ranges.map(([a, b]) => u.slice(a, b).map((x) => x.text).join(""));
};
