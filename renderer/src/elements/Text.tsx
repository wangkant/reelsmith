// Text in a box: runs with an accent colour, a size in px or "fit" (the largest size at which the text, broken into as
// many lines as help, fits the box's width and height), word-aware line breaks (never inside a word, a number or a
// number with its unit, nor before closing punctuation; after punctuation when one is near), optional balanced lines,
// stroke, shadow, a background plate, and a chars/words/lines reveal. Text with no colour is snow with a shadow.
import React from "react";
import { useCurrentFrame } from "remotion";
import { measureText } from "@remotion/layout-utils";
import { fontFamily } from "../fonts";
import type { Reveal, Run, TextStyle, Theme } from "../types";
import { balanced, type Fits, greedy, makeSpan, type Range, type Unit, unitsOf, wordSegments } from "./linebreak";
import { clamp01, color } from "./util";

export const TEXT_DEFAULTS: TextStyle = {
  font: "sans", size: 64, max_size: 160, min_size: 28, weight: 700, color: null, accent: null, align: "left",
  valign: "top", line_height: 1.15, letter_spacing: 0, wrap: true, balance: false, stroke: null, shadow: false, bg: null,
};

/** The shadow text gets when it has no colour (and so is drawn in snow). */
export const AUTO_SHADOW = "0 4px 18px rgba(0,0,0,0.45)";

// null on these means "none"; on the others it means "the default"
const NULLABLE = new Set(["stroke", "bg", "color", "accent"]);

/** `style` over `base`, ignoring unknown keys and wrong types. */
export const fullStyle = (style: Partial<TextStyle> | null | undefined, base: TextStyle = TEXT_DEFAULTS): TextStyle => {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(style ?? {})) {
    if (!(k in base)) continue;
    if (v === null) {
      if (NULLABLE.has(k)) out[k] = null;
      continue;
    }
    if (v !== undefined) out[k] = v;
  }
  const s = out as TextStyle;
  if (s.size !== "fit" && !(typeof s.size === "number" && s.size > 0)) s.size = base.size;
  return s;
};

/** letter_spacing: |v| < 1 is em (tracking), otherwise px. */
const spacing = (ls: number) => (!ls ? { em: 0, px: 0 } : Math.abs(ls) < 1 ? { em: ls, px: 0 } : { em: 0, px: ls });

const textOf = (runs: Run[]) => runs.map((r) => r.text).join("");
const chars = (s: string) => [...s];

const width100 = (text: string, family: string, weight: number, em: number): number => {
  if (!text) return 0;
  return measureText({
    text, fontFamily: family, fontSize: 100, fontWeight: String(weight), letterSpacing: em ? `${em}em` : undefined,
    // measured as drawn: the display face has one weight and is never faux-bolded
    additionalStyles: { fontSynthesis: "none" },
  }).width;
};

/** Hard lines ("\n") as runs. */
const splitLines = (runs: Run[]): Run[][] => {
  const lines: Run[][] = [[]];
  for (const r of runs) {
    String(r.text ?? "").split("\n").forEach((part, j) => {
      if (j > 0) lines.push([]);
      if (part) lines[lines.length - 1].push({ text: part, accent: !!r.accent });
    });
  }
  return lines;
};

/** Runs cut at character `k` of their joined text. */
const cutRuns = (runs: Run[], k: number): [Run[], Run[]] => {
  const a: Run[] = [];
  const b: Run[] = [];
  let pos = 0;
  for (const r of runs) {
    const cs = chars(r.text);
    const take = Math.max(0, Math.min(cs.length, k - pos));
    if (take > 0) a.push({ text: cs.slice(0, take).join(""), accent: r.accent });
    if (take < cs.length) b.push({ text: cs.slice(take).join(""), accent: r.accent });
    pos += cs.length;
  }
  return [a, b];
};

const sliceRuns = (runs: Run[], from: number, to: number): Run[] => cutRuns(cutRuns(runs, to)[0], from)[1];

// ---------------------------------------------------------------- word-aware breaking

const unitsAt100 = (text: string, family: string, weight: number, em: number): Unit[] =>
  unitsOf(text, (t) => width100(t, family, weight, em));

/** Ranges of units as runs of the hard line they came from. */
const toRuns = (line: Run[], u: Unit[], ranges: Range[]): Run[][] => {
  const at = [0];
  for (const x of u) at.push(at[at.length - 1] + x.n);
  return ranges.map(([a, b]) => sliceRuns(line, at[a], at[b]));
};

/** One line split into two balanced lines, word-aware (never inside a word, a number or a number with its unit). */
export const balanceTwo = (line: Run[], family: string, weight: number, em: number): Run[][] => {
  const u = unitsAt100(textOf(line), family, weight, em);
  const two = balanced(u, 2, () => true);
  return two && two.length === 2 ? toRuns(line, u, two) : [line];
};

// ---------------------------------------------------------------- layout

export type TextLayout = {
  size: number;
  /** explicit lines, or null: one flow the browser wraps (only when a piece is wider than the box) */
  lines: Run[][] | null;
  /** whether the browser may wrap inside a line */
  wrap: boolean;
  balanceCss: boolean;
};

const memo = new Map<string, TextLayout>();

/** Size and line breaks for runs in a w x h box; `maxLines` caps how many lines "fit" may use. Needs the fonts
 *  loaded (the Film waits for them). */
export const layoutText = (runs: Run[], s: TextStyle, w: number, h: number, maxLines = Infinity): TextLayout => {
  const key = JSON.stringify([runs, s, w, h, maxLines]);
  const known = memo.get(key);
  if (known) return known;
  const L = layoutUncached(runs, s, w, h, maxLines);
  if (memo.size > 400) memo.clear();
  memo.set(key, L);
  return L;
};

const layoutUncached = (runs: Run[], s: TextStyle, w: number, h: number, maxLines: number): TextLayout => {
  const family = fontFamily(s.font);
  const pad = s.bg ? Math.max(0, s.bg.pad ?? 0) : 0;
  const sw = s.stroke ? Math.max(0, s.stroke.width ?? 0) : 0;
  const availW = Math.max(1, w - 2 * pad - 2 * sw - 2);
  const availH = Math.max(1, h - 2 * pad - 2 * sw);
  const lh = s.line_height > 0 ? s.line_height : 1.15;
  const { em, px } = spacing(s.letter_spacing);
  const hard = splitLines(runs);
  const units = hard.map((line) => unitsAt100(textOf(line), family, s.weight, em));
  const fitsAt = (size: number): Fits => (w100, n) => (w100 * size) / 100 + px * n <= availW;

  // `two`: "balance" asks for two even lines, so each hard line of 4+ characters is split in two
  const forcedTwo = (u: Unit[], two: boolean) => two && makeSpan(u)(0, u.length).n >= 4;

  /** Lines at `size`: greedy, then balanced to the same count when asked; null when a piece cannot fit. */
  const arrange = (size: number, split: boolean, two = false): Run[][] | null => {
    const out: Run[][] = [];
    for (const [i, line] of hard.entries()) {
      const u = units[i];
      if (!split || !u.length) {
        out.push(line);
        continue;
      }
      const fits = fitsAt(size);
      const g = forcedTwo(u, two) ? balanced(u, 2, fits) : greedy(u, fits);
      if (!g) return null;
      const ranges = s.balance && g.length > 1 ? balanced(u, g.length, fits) ?? g : g;
      out.push(...toRuns(line, u, ranges));
    }
    return out;
  };

  if (s.size !== "fit") {
    const lines = arrange(s.size, s.wrap);
    if (!lines) return { size: s.size, lines: null, wrap: true, balanceCss: s.balance };
    return { size: s.size, lines, wrap: false, balanceCss: false };
  }

  const max = s.max_size > 0 ? s.max_size : 160;
  const min = Math.min(max, s.min_size > 0 ? s.min_size : 1);
  const split = s.wrap && maxLines > hard.length;
  /** How many lines the text needs at `size` (Infinity: it cannot fit the width). */
  const count = (size: number, two: boolean): number => {
    const fits = fitsAt(size);
    let n = 0;
    for (const u of units) {
      const t = makeSpan(u)(0, u.length);
      if (t.b <= t.a) n += 1;
      else if (!split) {
        if (!fits(t.w, t.n)) return Infinity;
        n += 1;
      } else if (forcedTwo(u, two)) {
        if (!balanced(u, 2, fits)) return Infinity;
        n += 2;
      } else {
        const g = greedy(u, fits);
        if (!g || (s.balance && g.length > 2)) return Infinity;
        n += g.length;
      }
    }
    return n;
  };
  /** The largest whole size that fits width and height, or null. Fewer lines at a smaller size, so feasibility only
   *  grows as the size shrinks and a binary search finds it. */
  const search = (two: boolean): number | null => {
    const ok = (size: number) => {
      const n = count(size, two);
      return n <= maxLines && n * size * lh <= availH;
    };
    let lo = Math.ceil(min);
    let hi = Math.floor(max);
    if (!ok(lo)) return null;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (ok(mid)) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  };
  const natural = search(false);
  const even = s.balance && split ? search(true) : null;
  const two = even !== null && (natural === null || even > natural);
  const lo = two ? (even as number) : natural;
  if (lo === null) {
    // nothing fits at the floor size: wrap word-aware at it (the layout check reports the overflow)
    const lines = arrange(min, s.wrap);
    return { size: min, lines, wrap: !lines && s.wrap, balanceCss: !lines && s.balance };
  }
  const lines = arrange(lo, split, two) ?? hard;
  // the lines measured whole (kerning across pieces) may be a hair wider than their pieces' sum
  let size = lo;
  for (const line of lines) {
    const t = textOf(line).trim();
    const lw = width100(t, family, s.weight, em);
    if (lw > 0) size = Math.min(size, Math.floor(((availW - px * chars(t).length) * 100) / lw));
  }
  return { size: Math.max(Math.min(min, lo), size), lines, wrap: false, balanceCss: false };
};

// ---------------------------------------------------------------- reveal

type Piece = { text: string; accent: boolean; unit: number };

const words = (s: string): string[] => {
  const out: string[] = [];
  const parts = wordSegments(s);
  for (const p of parts) {
    // spaces and punctuation ride with the word before them
    if (out.length && (/^\s+$/.test(p) || /^[\p{P}\p{S}]+$/u.test(p))) out[out.length - 1] += p;
    else out.push(p);
  }
  return out;
};

/** Pieces of `lines` tagged with their reveal unit (0-based, in reading order), and how many units there are. */
const segment = (lines: Run[][], mode: Reveal["mode"]): { pieces: Piece[][]; units: number } => {
  let unit = 0;
  const pieces = lines.map((line, li) => {
    const out: Piece[] = [];
    if (mode === "lines" && li > 0) unit++;
    for (const r of line) {
      const accent = !!r.accent;
      if (mode === "chars") {
        for (const c of chars(r.text)) out.push({ text: c, accent, unit: /\s/.test(c) ? unit : unit++ });
      } else if (mode === "words") {
        for (const wd of words(r.text)) out.push({ text: wd, accent, unit: unit++ });
      } else if (mode === "lines") {
        // hard breaks inside a flowing text start a new unit too
        r.text.split("\n").forEach((part, j) => {
          if (j > 0) unit++;
          if (j > 0) out.push({ text: "\n", accent, unit });
          if (part) out.push({ text: part, accent, unit });
        });
      } else {
        out.push({ text: r.text, accent, unit: 0 });
      }
    }
    return out;
  });
  const units = mode === "chars" || mode === "words" ? unit : unit + 1;
  return { pieces, units: Math.max(1, units) };
};

/** Unit i's opacity at frame f of a reveal `total` frames long over n units. */
const unitOpacity = (i: number, n: number, f: number, total: number) => {
  const fade = Math.max(1, Math.min(8, Math.round((2 * total) / n)));
  const start = n > 1 ? (i * Math.max(0, total - fade)) / (n - 1) : 0;
  return clamp01((f - start + 1) / fade);
};

/** Adjacent pieces with the same colour and a settled opacity (0 or 1) merge, so the DOM stays small. */
const merge = (pieces: Array<{ text: string; accent: boolean; o: number }>) => {
  const out: Array<{ text: string; accent: boolean; o: number }> = [];
  for (const p of pieces) {
    const last = out[out.length - 1];
    if (last && last.accent === p.accent && last.o === p.o && (p.o === 0 || p.o === 1)) last.text += p.text;
    else out.push({ ...p });
  }
  return out;
};

const Spans: React.FC<{ pieces: Array<{ text: string; accent: boolean; o: number }>; accent: string }> = ({ pieces, accent }) => (
  <>
    {merge(pieces).map((p, i) => {
      const style: React.CSSProperties = {};
      if (p.accent) style.color = accent;
      if (p.o < 1) style.opacity = p.o;
      return Object.keys(style).length ? <span key={i} style={style}>{p.text}</span> : <React.Fragment key={i}>{p.text}</React.Fragment>;
    })}
  </>
);

// ---------------------------------------------------------------- the block

// an empty line keeps its height with a no-break space (trim() drops it, so inspect ignores it)
const NBSP = String.fromCharCode(160);

const JUSTIFY = { top: "flex-start", middle: "center", bottom: "flex-end" } as const;
const ALIGN = { left: "flex-start", center: "center", right: "flex-end" } as const;

export type TextBlockProps = {
  runs: Run[];
  style?: Partial<TextStyle> | null;
  /** defaults under `style` (captions use their own) */
  base?: TextStyle;
  reveal?: Reveal | null;
  w: number;
  h: number;
  theme: Theme;
  fps: number;
  /** at most this many lines for size "fit" (captions: 1); past the box's floor size text still wraps */
  maxLines?: number;
};

export const TextBlock: React.FC<TextBlockProps> = ({ runs, style, base, reveal, w, h, theme, fps, maxLines }) => {
  const f = useCurrentFrame();
  const s = fullStyle(style, base);
  const clean = (Array.isArray(runs) ? runs : []).filter((r) => r && typeof r.text === "string" && r.text.length);
  const L = layoutText(clean, s, w, h, maxLines ?? Infinity);
  const accent = color(theme, s.accent, theme.accent);
  const mode = reveal && reveal.mode && reveal.mode !== "none" ? reveal.mode : null;
  const lines = L.lines ?? [clean];
  const { pieces, units } = segment(lines, mode ?? "none");
  const total = Math.max(1, Math.round((reveal?.dur && reveal.dur > 0 ? reveal.dur : 0.8) * fps));
  const shown = (p: Piece) => ({ text: p.text, accent: p.accent, o: mode ? unitOpacity(p.unit, units, f, total) : 1 });

  const pad = s.bg ? Math.max(0, s.bg.pad ?? 0) : 0;
  const sw = s.stroke ? Math.max(0, s.stroke.width ?? 0) : 0;
  const { em, px } = spacing(s.letter_spacing);
  // no colour set: snow with a shadow reads on photos, video and the film's dark default ground
  const auto = !s.color;
  const shadowSpec = s.shadow || (auto ? AUTO_SHADOW : false);
  const shadow = shadowSpec ? (shadowSpec === true ? AUTO_SHADOW : String(shadowSpec)) : undefined;
  const block: React.CSSProperties = {
    boxSizing: "border-box", maxWidth: "100%", fontFamily: fontFamily(s.font), fontWeight: s.weight, fontSize: L.size,
    fontSynthesis: "none", lineHeight: s.line_height > 0 ? s.line_height : 1.15,
    color: auto ? theme.snow : color(theme, s.color, theme.snow),
    letterSpacing: em ? `${em}em` : px ? `${px}px` : undefined, textAlign: s.align,
    // longhands: a white-space shorthand next to text-wrap would let one reset the other
    whiteSpaceCollapse: "preserve", textWrapMode: L.wrap ? "wrap" : "nowrap", textWrapStyle: L.balanceCss ? "balance" : "auto",
    overflowWrap: "break-word", lineBreak: "strict",
    padding: pad || undefined, background: s.bg ? color(theme, s.bg.color, "rgba(10,10,12,0.62)") : undefined,
    borderRadius: s.bg ? s.bg.radius ?? 0 : undefined, textShadow: shadow,
    WebkitTextStroke: sw ? `${sw * 2}px ${color(theme, s.stroke?.color, theme.night)}` : undefined,
    paintOrder: sw ? "stroke fill" : undefined,
  };
  return (
    <div style={{
      position: "absolute", left: 0, top: 0, width: w, height: h, display: "flex", flexDirection: "column",
      justifyContent: JUSTIFY[s.valign] ?? "flex-start", alignItems: ALIGN[s.align] ?? "flex-start",
    }}>
      <div style={block}>
        {L.lines
          ? pieces.map((line, i) => (
              <div key={i}>
                {line.length ? <Spans pieces={line.map(shown)} accent={accent} /> : NBSP}
              </div>
            ))
          : <Spans pieces={pieces[0].map(shown)} accent={accent} />}
      </div>
    </div>
  );
};
