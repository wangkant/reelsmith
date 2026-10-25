// Gain curves: a volume or a volume curve (keyframes), linear fades (crossfades arrive as fades) and ducking.
import { valueAt } from "../keyframes";
import type { DuckRange, Keyframe } from "../types";
import { clamp01, num } from "./util";

/** The duck's gain at frame f: `level` inside a range, eased linearly over `fade` frames into and out of it. */
export const duckAt = (ranges: DuckRange[] | null | undefined, f: number): number => {
  let g = 1;
  for (const r of ranges ?? []) {
    if (!r) continue;
    const fade = Math.max(0, num(r.fade, 0));
    const level = clamp01(num(r.level, 1));
    let v = 1;
    if (f >= r.start && f <= r.end) v = level;
    else if (fade > 0 && f < r.start && f > r.start - fade) v = 1 + (level - 1) * ((f - (r.start - fade)) / fade);
    else if (fade > 0 && f > r.end && f < r.end + fade) v = level + (1 - level) * ((f - r.end) / fade);
    g = Math.min(g, v);
  }
  return g;
};

/** Gain at frame f of a sound `dur` frames long: its volume, or its volume curve, capped at 1 (mastering sets the
 *  loudness), times its fades. */
export const curveAt = (
  volume: number | undefined, keys: Keyframe[] | null | undefined, fadeIn: number | undefined, fadeOut: number | undefined,
  dur: number, f: number, fps: number,
): number => {
  const fromKeys = keys && keys.length ? valueAt(keys, f, fps) : NaN;
  const base = Number.isFinite(fromKeys) ? fromKeys : num(volume, 1);
  const v = Math.max(0, Math.min(1, base));
  const fin = Math.max(0, num(fadeIn, 0));
  const fout = Math.max(0, num(fadeOut, 0));
  const up = fin > 0 ? clamp01(f / fin) : 1;
  const down = fout > 0 ? clamp01((dur - f) / fout) : 1;
  return v * up * down;
};

/** Whether a sound is heard at all: a volume above 0, or a curve that rises above 0. */
export const audible = (volume: number | undefined, keys: Keyframe[] | null | undefined): boolean =>
  num(volume, 0) > 0 || (keys ?? []).some((k) => k && Number.isFinite(k.v) && k.v > 0);
