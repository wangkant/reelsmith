// Stage colours and the shared look: palette tokens, soft shadows, per-instance filters, the size unit.
import React, { createContext, createElement, useContext, useId } from "react";
import { useClip } from "../context";
import { mixColor } from "./geom";

export type Palette = {
  /** dark lines and words */
  ink: string;
  /** stickers, labels, documents */
  paper: string;
  /** the ground sheet and wrapping */
  kraft: string;
  kraftDeep: string;
  kraftLight: string;
  /** stamps, marker loops, warnings */
  red: string;
  /** highlighter and dye */
  lemon: string;
  /** the film's own colour (defaults to the theme accent) */
  accent: string;
  /** wood of tables, signs, carts */
  wood: string;
  woodDeep: string;
  /** a back wall */
  wall: string;
  wallDeep: string;
  /** warm shadow colour, no alpha */
  shadow: string;
  /** steel, glass and plastic */
  steel: string;
  /** the sky at the top and at the horizon */
  sky: string;
  haze: string;
  /** grass, leaves and hills */
  leaf: string;
};

export const PALETTE: Palette = {
  ink: "#211A14", paper: "#FBF6EA", kraft: "#C29B6C", kraftDeep: "#9C7046", kraftLight: "#E0C298",
  red: "#C8372D", lemon: "#F7D417", accent: "#C8372D", wood: "#8B5A34", woodDeep: "#5F3B20",
  wall: "#EBDDC5", wallDeep: "#D9C3A1", shadow: "#28180A", steel: "#8E949A",
  sky: "#7FB2D6", haze: "#F3E3C4", leaf: "#6E9A4E",
};

export const PaletteContext = createContext<Partial<Palette> | null>(null);

/** The palette in force: the kit's tokens, the theme accent, then whatever the enclosing <Stage palette> set. */
export const usePalette = (): Palette => {
  const over = useContext(PaletteContext);
  const { theme } = useClip();
  return { ...PALETTE, accent: theme?.accent || PALETTE.accent, ...(over ?? {}) };
};

/** Canvas px per design px: sizes in the kit are designed on a 1080-wide frame and scale with the clip. */
export const useUnit = (): number => {
  const { w } = useClip();
  return w > 0 ? w / 1080 : 1;
};

/** A CSS drop-shadow for something `lift` (0 lying flat .. 1 held up) above the page. */
export const shadowCss = (lift = 0, color = PALETTE.shadow): string => {
  const k = Math.max(0, Math.min(1, lift));
  const a = (0.42 - 0.12 * k).toFixed(2);
  const c = /^#[0-9a-f]{6}$/i.test(color) ? `rgba(${[1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)).join(",")},${a})` : color;
  return `drop-shadow(${3 + 14 * k}px ${5 + 22 * k}px ${6 + 20 * k}px ${c})`;
};

/** Lighter and darker shades of a base colour for the material recipe. */
export const shades = (base: string) => ({
  base, hi: mixColor(base, "#FFFFFF", 0.38), deep: mixColor(base, "#000000", 0.32), rim: mixColor(base, "#FFF6E0", 0.7),
});

/** Ids unique to this instance (so two primitives never share a filter) and their <defs>: `soft` and `blur`
 *  are Gaussian blurs of `softPx` and `blurPx`. Put `defs` inside the primitive's own <svg>; build further ids as
 *  `id + "suffix"` (the filters take "-fs" and "-fb"). */
export const useFilters = (softPx = 9, blurPx = 14) => {
  const id = "st" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const filter = (name: string, std: number) =>
    createElement("filter", { id: id + name, key: name, x: "-40%", y: "-40%", width: "180%", height: "180%" },
      createElement("feGaussianBlur", { stdDeviation: std }));
  const defs: React.ReactNode = createElement("defs", null, filter("-fs", softPx), filter("-fb", blurPx));
  return { id, soft: `url(#${id}-fs)`, blur: `url(#${id}-fb)`, defs };
};
