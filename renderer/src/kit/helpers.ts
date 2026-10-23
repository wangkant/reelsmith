// Small pure helpers for components: easing, springs, fitted text, number formatting, theme colours.
import { Easing, interpolate, spring } from "remotion";
import type { SpringConfig } from "remotion";
import { fitText, measureText } from "@remotion/layout-utils";
import { fontFamily as cssFamily, FONTS } from "../fonts";
import { pieces, wordSegments } from "../elements/linebreak";
import { srcUrl } from "../elements/util";
import type { MediaRef } from "../types";

export type FontName = keyof typeof FONTS;

type Piece = ReturnType<typeof pieces>[number];

const SANS = "sans";

/** interpolate() options that hold the ends: `interpolate(f, [a, b], [0, 1], clamp)`. */
export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const EASE_OUT = Easing.bezier(0.22, 1, 0.36, 1);

/** Frames a..b mapped to from..to on an ease-out curve, held at both ends. b <= a is a step at a. */
export const ease = (f: number, a: number, b: number, from = 0, to = 1): number => {
  if (!(b > a)) return f >= a ? to : from;
  return interpolate(f, [a, b], [from, to], { ...clamp, easing: EASE_OUT });
};

export type SpringOptions = Partial<SpringConfig> & { fps?: number; durationInFrames?: number };

/** 0 -> 1 spring that starts at frame `at` (0 before it). fps defaults to 30; pass `{fps}` from useClip() otherwise. */
export const springAt = (f: number, at: number, config: SpringOptions = {}): number => {
  const { fps = 30, durationInFrames, ...cfg } = config;
  if (f < at) return 0;
  return spring({ frame: f - at, fps, config: { damping: 200, ...cfg }, durationInFrames });
};

/** A FONTS key or a CSS font-family; empty means the sans face, as everywhere else. */
const fontFamily = (family?: string): string => cssFamily(family || SANS);

/** Width in px of `text` on one line at `size`; `tabular` measures digits as with fontVariantNumeric "tabular-nums". */
export const textWidth = (text: string, size: number, family: string = SANS, weight: string | number = 400, tabular = false): number => {
  if (!text || !(size > 0) || !Number.isFinite(size)) return 0;
  try {
    return measureText({
      text, fontFamily: fontFamily(family), fontSize: size, fontWeight: String(weight),
      fontVariantNumeric: tabular ? "tabular-nums" : undefined,
    }).width;
  } catch {
    return text.length * size; // outside a browser: CJK glyphs are ~1 em wide
  }
};

/** Largest font size (<= max) at which `text` fits on one line `width` px wide. */
export const fit = (text: string, width: number, max: number, family: string = SANS, weight: string | number = 400): number => {
  // NaN or Infinity (a box not measured yet) must not reach fitText's search, which then never ends
  if (!(width > 0) || !Number.isFinite(width) || !(max > 0)) return 0;
  if (!text) return Math.floor(max);
  try {
    const size = fitText({ text, withinWidth: width, fontFamily: fontFamily(family), fontWeight: String(weight) }).fontSize;
    return Math.max(1, Math.min(max, Math.floor(size)));
  } catch {
    return Math.max(1, Math.min(max, Math.floor(width / Math.max(1, text.length))));
  }
};

/** Word segments of `text` (Intl.Segmenter "zh"), spaces included; joined they give `text`. */
export const words = (text: string): string[] => (text ? wordSegments(text) : []);

const PUNCT_END = /[，、：；？！。,.:;?!…][”’」』)）]*$/u;
const single = (p: string) => [...p].length === 1 && /\p{Script=Han}/u.test(p);

/** Cost of a line break between two unbreakable pieces: a bonus after punctuation, a little next to a lone character
 *  (where the dictionary was unsure, as in 报名|百日|挑战 vs 报名百|日挑战). */
const breakCost = (a: Piece, b: Piece): number => {
  if (a.space || b.space) return 0;
  if (PUNCT_END.test(a.text)) return -2.5;
  if (single(a.text) && single(b.text)) return 2;
  if (single(a.text) || single(b.text)) return 0.5;
  return 0;
};

/** Split a line into at most two balanced lines at a break the text clip would also take (Intl.Segmenter "zh"
 *  words; never inside a word, a number, a number and its unit, or before closing punctuation): near the middle,
 *  after punctuation if one is close. */
export const twoLines = (text: string, maxOne = 9): string[] => {
  const s = (text ?? "").trim();
  const n = [...s].length;
  if (n <= maxOne || n < 2) return [s];
  const ps = pieces(s);
  const mid = n / 2;
  let best = -1;
  let bestScore = Infinity;
  let k = 0;
  for (let i = 0; i < ps.length - 1; i++) {
    k += [...ps[i].text].length;
    const score = Math.abs(k - mid) + breakCost(ps[i], ps[i + 1]);
    if (score < bestScore) {
      bestScore = score;
      best = i + 1;
    }
  }
  if (best < 0) return [s];
  const line = (from: number, to: number) => ps.slice(from, to).map((p) => p.text).join("").trim();
  const [a, b] = [line(0, best), line(best, ps.length)];
  return a && b ? [a, b] : [s];
};

/** The largest size (<= max) at which `text` fits `width` on one line; when that is under `min`, two lines
 *  (twoLines) if they fit larger. Render `lines.join("\n")` with whiteSpace "pre". */
export const fitLines = (
  text: string, width: number, max: number, min = 0, family: string = SANS, weight: string | number = 400,
): { size: number; lines: string[] } => {
  const s = (text ?? "").trim();
  const one = fit(s, width, max, family, weight);
  if (one >= min) return { size: one, lines: [s] };
  const split = twoLines(s, 0);
  if (split.length < 2) return { size: one, lines: [s] };
  const two = Math.min(...split.map((l) => fit(l, width, max, family, weight)));
  return two > one ? { size: two, lines: split } : { size: one, lines: [s] };
};

/** "12,345.6" style number text; non-finite values print as they are. */
export const fmt = (value: number, decimals = 0, grouping = true): string => {
  if (!Number.isFinite(value)) return String(value);
  const d = Math.max(0, Math.min(20, Math.round(decimals)));
  return value.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: grouping });
};

/** Decimal places a number is written with (3 -> 0, 2.5 -> 1, 0.125 -> 3), at most 4. */
export const decimalsOf = (value: number): number => {
  if (!Number.isFinite(value) || Number.isInteger(value)) return 0;
  const m = String(value).match(/\.(\d+)/);
  return m ? Math.min(4, m[1].length) : 0;
};

// ---------------------------------------------------------------- theme colours

export type Tokens = {
  paper: string; ink: string; night: string; snow: string; accent: string; gold: string; good: string; bad: string; muted: string;
};
export const TOKEN_NAMES = ["paper", "ink", "night", "snow", "accent", "gold", "good", "bad", "muted"] as const;

/** A theme token name ("accent", "gold", ...) to its colour; any other non-empty string is used as CSS. */
export const themeColor = (theme: Tokens, value?: string | null, fallback: keyof Tokens = "accent"): string => {
  if (typeof value !== "string" || !value.trim()) return theme[fallback];
  return (TOKEN_NAMES as readonly string[]).includes(value) ? theme[value as keyof Tokens] : value;
};

/** `color` at opacity `a` (hex is converted; anything else goes through color-mix). */
export const withAlpha = (color: string, a: number): string => {
  const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  const k = Math.max(0, Math.min(1, a));
  if (!hex) return `color-mix(in srgb, ${color} ${Math.round(k * 100)}%, transparent)`;
  const v = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join("") : hex[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
  return `rgba(${r},${g},${b},${k})`;
};

export type Ground = "light" | "dark";

/** Text colours for a component sitting on a light ground (paper, a pale picture) or a dark one (night, a photo). */
export const onGround = (theme: Tokens, ground?: string | null) =>
  ground === "dark"
    ? { dark: true, ink: theme.snow, muted: "rgba(255,255,255,0.74)", faint: "rgba(255,255,255,0.2)" }
    : { dark: false, ink: theme.ink, muted: theme.muted, faint: withAlpha(theme.ink, 0.14) };

// ---------------------------------------------------------------- props and timing

/** A finite number from props, or the fallback. */
export const numOr = (value: unknown, fallback: number): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

/** A Time prop (it reaches the component as frames from the clip start), or the fallback when absent. */
export const frameOr = numOr;

/** An asset prop as it reaches a component (`{src, kind, size?, box?, site?, duration?}`). */
export type AssetRef = MediaRef;

/** True when a prop value looks like an asset ref (an unknown asset id arrives as something else). */
export const isAsset = (v: unknown): v is AssetRef =>
  !!v && typeof v === "object" && typeof (v as AssetRef).src === "string" && (v as AssetRef).src.length > 0;

/** URL for an asset (or its src) to give <Img>/<OffthreadVideo>: project paths go through staticFile, URLs stay. */
export const assetSrc = (ref: AssetRef | string): string => srcUrl(typeof ref === "string" ? ref : ref.src);

/** Seconds to frames. */
export const toFrames = (seconds: number, fps: number): number => Math.round(seconds * fps);

/** n frames evenly spaced from a to b (n = 1 gives [a]). */
export const spread = (n: number, a: number, b: number): number[] =>
  Array.from({ length: Math.max(0, n) }, (_, i) => Math.round(n <= 1 ? a : a + ((b - a) * i) / (n - 1)));
