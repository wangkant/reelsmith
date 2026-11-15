// Stage geometry: points, torn and organic outlines, smooth paths, colour mixing. Seeded, never Math.random.
import { random } from "remotion";
import { clamp01 } from "./time";

export type Pt = [number, number];

/** A torn-paper outline through polygon `pts`: edges cut into `seg`-long bits with a seeded wobble of `amp`. */
export const torn = (pts: Pt[], seed: string, amp = 7, seg = 16): string => {
  const out: Pt[] = [];
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    const len = Math.hypot(bx - ax, by - ay);
    const n = Math.max(1, Math.round(len / seg));
    const nx = -(by - ay) / (len || 1), ny = (bx - ax) / (len || 1);
    for (let j = 0; j < n; j++) {
      const t = j / n;
      const r = j === 0 ? 0 : (random(`${seed}-${i}-${j}`) - 0.5) * 2 * amp;
      const notch = j > 0 && random(`${seed}n${i}-${j}`) > 0.93 ? amp * 1.8 : 0;
      out.push([ax + (bx - ax) * t + nx * (r - notch), ay + (by - ay) * t + ny * (r - notch)]);
    }
  }
  return out.length ? "M" + out.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("L") + "Z" : "";
};

export const bbox = (pts: Pt[]) => {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
};

export const rect = (x: number, y: number, w: number, h: number): Pt[] => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];

export const circle = (cx: number, cy: number, r: number, n = 28): Pt[] =>
  Array.from({ length: n }, (_, i) => [cx + r * Math.cos((2 * Math.PI * i) / n), cy + r * Math.sin((2 * Math.PI * i) / n)] as Pt);

const cubic = (p0: Pt, p1: Pt, p2: Pt, p3: Pt) => {
  const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
  const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
  return ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
};

/** Open smooth path through the points (Catmull-Rom as cubic Beziers). */
export const smooth = (pts: Pt[]): string => {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) d += cubic(pts[Math.max(0, i - 1)], pts[i], pts[i + 1], pts[Math.min(pts.length - 1, i + 2)]);
  return d;
};

/** Closed smooth path through the points. */
export const smoothClosed = (pts: Pt[]): string => {
  const n = pts.length;
  if (n < 3) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n; i++) d += cubic(pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]);
  return d + "Z";
};

/** An organic closed shape around (cx, cy) with a flatter bottom, so it sits on a surface. */
export const blob = (cx: number, cy: number, rx: number, ry: number, seed: string, n = 12, jit = 0.12): string => {
  const pts: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const r = 1 + (random(seed + i) - 0.5) * 2 * jit;
    const yy = Math.sin(a) > 0 ? Math.sin(a) * 0.82 : Math.sin(a);
    pts.push([cx + Math.cos(a) * rx * r, cy + yy * ry * r]);
  }
  return smoothClosed(pts);
};

/** A rounded rectangle whose corners and edges are a little uneven (made by hand, not by a ruler). */
export const roughRect = (x: number, y: number, w: number, h: number, rad: number, seed: string, jit = 0.012): string => {
  const j = (k: string) => (random(seed + k) - 0.5) * 2 * jit * Math.max(w, h);
  const r = Math.max(0, Math.min(rad, w / 2, h / 2));
  const p = (px: number, py: number, k: string) => `${(px + j(k + "x")).toFixed(1)} ${(py + j(k + "y")).toFixed(1)}`;
  return `M${p(x + r, y, "a")} L${p(x + w - r, y, "b")} Q${x + w} ${y} ${p(x + w, y + r, "c")} L${p(x + w, y + h - r, "d")}`
    + ` Q${x + w} ${y + h} ${p(x + w - r, y + h, "e")} L${p(x + r, y + h, "f")} Q${x} ${y + h} ${p(x, y + h - r, "g")}`
    + ` L${p(x, y + r, "h")} Q${x} ${y} ${p(x + r, y, "a")}Z`;
};

/** A wavy line from x0 to x1 around y (fibres, grain, guilloche). */
export const fibre = (x0: number, x1: number, y: number, amp: number, seed: string, n = 6): string => {
  const pts: Pt[] = [];
  for (let i = 0; i <= n; i++) pts.push([x0 + ((x1 - x0) * i) / n, y + (random(seed + i) - 0.5) * 2 * amp + Math.sin(i * 1.3) * amp * 0.4]);
  return smooth(pts);
};

/** The point at fraction t along a polyline (a pen tip following a stroke). */
export const along = (pts: Pt[], t: number): Pt => {
  if (pts.length < 2) return pts[0] ?? [0, 0];
  const segs = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  const total = segs.reduce((a, b) => a + b, 0);
  let d = clamp01(t) * total;
  for (let i = 0; i < segs.length; i++) {
    if (d <= segs[i] || i === segs.length - 1) {
      const k = segs[i] ? Math.min(1, d / segs[i]) : 0;
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k];
    }
    d -= segs[i];
  }
  return pts[pts.length - 1];
};

const rgb = (c: string): number[] | null => {
  const m = c.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!m) return null;
  const v = m[1].length === 3 ? [...m[1]].map((x) => x + x).join("") : m[1];
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
};

/** Hex colour between a and b (k = 0..1); anything not hex goes through color-mix. */
export const mixColor = (a: string, b: string, k: number): string => {
  const A = rgb(a), B = rgb(b), t = clamp01(k);
  if (!A || !B) return `color-mix(in srgb, ${a} ${Math.round((1 - t) * 100)}%, ${b})`;
  return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
};

/** A stable small integer from a seed string (for SVG filter seeds). */
export const seedInt = (seed: string, max = 997): number => Math.floor(random(seed) * max) + 1;
