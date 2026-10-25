// Small shared helpers for the clip elements. Elements import only kit/context (not the kit index, which
// re-exports Media and EvidenceCrop from here: importing it back would be a cycle).
import { staticFile } from "remotion";
import type { ClipStyle, FilterSpec, Theme } from "../types";

export const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);

export const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** A project-relative asset path to a URL the page can load (the bundle's public dir is the project). */
export const srcUrl = (src: string): string => {
  if (!src) return src;
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  return staticFile(src.replace(/\\/g, "/").replace(/^\.?\/+/, ""));
};

const TOKENS = ["paper", "ink", "night", "snow", "accent", "gold", "good", "bad", "muted"] as const;

/** A theme token name ("accent", "gold", ...) to its colour; any other non-empty string is CSS as it is. */
export const color = (theme: Theme, value: string | null | undefined, fallback: string): string => {
  if (!value) return fallback;
  if ((TOKENS as readonly string[]).includes(value)) return theme[value as (typeof TOKENS)[number]];
  return value;
};

const ORIGINS: Record<string, string> = {
  center: "50% 50%", top: "50% 0%", bottom: "50% 100%", left: "0% 50%", right: "100% 50%",
  "top-left": "0% 0%", "top-right": "100% 0%", "bottom-left": "0% 100%", "bottom-right": "100% 100%",
};

/** "top-left" etc. to a CSS transform-origin; anything else is passed through as CSS. */
export const origin = (o: string | null | undefined): string => (o ? ORIGINS[o] ?? o : "50% 50%");

/** A clip's filter values now: its filter fields, or their keyframes where it has them. */
export type FilterNow = Required<FilterSpec>;

/** The clip's filter fields with neutral values for the ones it does not set. */
export const filterBase = (f: FilterSpec | null | undefined): FilterNow => ({
  blur: num(f?.blur, 0), brightness: num(f?.brightness, 1), contrast: num(f?.contrast, 1), saturate: num(f?.saturate, 1),
  grayscale: num(f?.grayscale, 0), sepia: num(f?.sepia, 0), invert: num(f?.invert, 0), hue_rotate: num(f?.hue_rotate, 0),
});

/** The CSS filter for a clip's filter values and a drop shadow; neutral values are left out. */
export const filterCss = (v: FilterNow, dropShadow: string | null) => {
  const parts: string[] = [];
  if (v.blur > 0) parts.push(`blur(${v.blur}px)`);
  if (v.brightness !== 1) parts.push(`brightness(${Math.max(0, v.brightness)})`);
  if (v.contrast !== 1) parts.push(`contrast(${Math.max(0, v.contrast)})`);
  if (v.saturate !== 1) parts.push(`saturate(${Math.max(0, v.saturate)})`);
  if (v.grayscale > 0) parts.push(`grayscale(${clamp01(v.grayscale)})`);
  if (v.sepia > 0) parts.push(`sepia(${clamp01(v.sepia)})`);
  if (v.hue_rotate !== 0) parts.push(`hue-rotate(${v.hue_rotate}deg)`);
  if (v.invert > 0) parts.push(`invert(${clamp01(v.invert)})`);
  if (dropShadow) parts.push(`drop-shadow(${dropShadow})`);
  return parts.length ? parts.join(" ") : undefined;
};

export const DEFAULT_SHADOW = "0 18px 44px rgba(0,0,0,0.42)";

/** Shadow for a clip: true -> the default; a CSS string as given. Text, shapes and evidence get a drop-shadow (it
 *  follows the glyphs, strokes, or the evidence panel inside its box), boxes get a box-shadow. */
export const shadowFor = (style: ClipStyle | null | undefined, type: string) => {
  const s = style?.shadow;
  if (!s) return { box: undefined, drop: null };
  const css = s === true ? DEFAULT_SHADOW : String(s);
  return type === "text" || type === "shape" || type === "evidence" ? { box: undefined, drop: css } : { box: css, drop: null };
};
