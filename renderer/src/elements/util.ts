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

/** The CSS filter for a clip: its filter fields, keyframed blur/brightness and a drop shadow. */
export const filterCss = (f: FilterSpec | null | undefined, blur: number, brightness: number, dropShadow: string | null) => {
  const parts: string[] = [];
  if (blur > 0) parts.push(`blur(${blur}px)`);
  if (brightness !== 1) parts.push(`brightness(${Math.max(0, brightness)})`);
  if (f?.contrast !== undefined && f.contrast !== null && f.contrast !== 1) parts.push(`contrast(${f.contrast})`);
  if (f?.saturate !== undefined && f.saturate !== null && f.saturate !== 1) parts.push(`saturate(${f.saturate})`);
  if (f?.grayscale) parts.push(`grayscale(${f.grayscale})`);
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
