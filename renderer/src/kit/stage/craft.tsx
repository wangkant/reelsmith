/// <reference path="./flubber.d.ts" />
// Craft helpers for drawn-pose films: poses from asset props, a two-drawing walk, smear frames, brush-pen strokes,
// shape morphs, boiling lines, even shadow ramps and baked simulations. Every time here is in frames.
import React, { useId, useMemo } from "react";
import { Img, random, useCurrentFrame } from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";
import { getStroke } from "perfect-freehand";
import { interpolate as flubber } from "flubber";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import { poseBox, useLineStyle } from "./drawn";
import type { Pose } from "./drawn";
import type { Pt } from "./geom";
import { useUnit } from "./palette";
import { clamp01, lerp } from "./time";

// ------------------------------------------------------------------ poses from asset props

export type Twin = "shut" | "half" | "blink" | "blinkOpen";
/** One pose of a film's cast: its asset id, `feet` and `scale` as in Pose, and which twins it has (required when
 *  listed; left out, whichever twins the assets hold). */
export type PoseSpec = { id: string; feet?: number; scale?: number; inset?: [number, number]; twins?: Twin[] };

const TWIN_KEYS: Record<Twin, string[]> = { shut: ["shut"], half: ["half"], blink: ["blink"], blinkOpen: ["blinkOpen", "blink_open"] };

/** The Performer's `poses` from a cast list and the component's asset props: pose `id` is the prop `<id>_asset` (or
 *  `<id>`), its twins `<id>_shut_asset`, `<id>_half_asset`, `<id>_blink_asset`, `<id>_blink_open_asset`. */
export const posesFrom = (cast: PoseSpec[], assets: Record<string, unknown>): Record<string, Pose> => {
  const pick = (names: string[]): AssetRef | undefined => {
    for (const n of names) {
      const v = assets?.[`${n}_asset`] ?? assets?.[n];
      if (v === undefined) continue;
      if (!isAsset(v)) throw new Error(`usePoses: "${n}" is ${JSON.stringify(v)}, not an asset (an unknown asset id arrives as a plain string)`);
      return v;
    }
    return undefined;
  };
  const out: Record<string, Pose> = {};
  for (const c of cast) {
    const src = pick([c.id]);
    if (!src) throw new Error(`usePoses: no asset prop "${c.id}_asset" for pose "${c.id}"; props have ${Object.keys(assets ?? {}).join(", ") || "none"}`);
    const pose: Pose = { src, feet: c.feet, scale: c.scale, inset: c.inset };
    for (const t of Object.keys(TWIN_KEYS) as Twin[]) {
      const ref = pick(TWIN_KEYS[t].map((k) => `${c.id}_${k}`));
      if (ref) pose[t] = ref;
      else if (c.twins?.includes(t)) throw new Error(`usePoses: pose "${c.id}" lists twin "${t}" but there is no prop "${c.id}_${TWIN_KEYS[t].at(-1)}_asset"`);
    }
    out[c.id] = pose;
  }
  return out;
};

/** posesFrom, built once per cast and props. */
export const usePoses = (cast: PoseSpec[], assets: Record<string, unknown>): Record<string, Pose> =>
  useMemo(() => posesFrom(cast, assets), [cast, assets]);

// ------------------------------------------------------------------ the two-drawing walk

export type WalkOptions = {
  /** first frame of the walk and its length in frames (default: whole strides at `stride` px a drawing) */
  at: number; dur?: number; stride?: number;
  x0: number; x1: number;
  /** frames each drawing holds */
  step?: number;
  /** the rise mid-step and the squash at each foot-fall (fractions of the drawn height h) */
  bob?: number; squash?: number;
  h: number;
};

/** The walk at frame `f`: `x` on a straight line at an even pace, which drawing (`k`), the rise `dy` (negative up)
 *  peaking mid-step and the squash `sy` on the frame a foot lands. Before `at` it stands at x0, after it at x1. */
export const walkAt = (f: number, o: WalkOptions) => {
  const { at, x0, x1, step = 6, bob = 0.012, squash = 0.035, h } = o;
  const stride = o.stride ?? 0.28 * h;
  const dur = o.dur ?? Math.max(step, Math.ceil(Math.abs(x1 - x0) / Math.max(1, stride)) * step);
  if (f < at || f >= at + dur) return { x: f < at ? x0 : x1, k: 0, dy: 0, sy: 1, moving: false, dur };
  const j = f - at, n = Math.floor(j / step), inStep = j - n * step;
  const dy = -bob * h * Math.sin((Math.PI * inStep) / step);
  const sy = inStep === 0 ? 1 - squash : inStep === 1 ? 1 - squash / 2 : 1;
  return { x: lerp(x0, x1, j / dur), k: n, dy, sy, moving: true, dur };
};

// an asset ref also has a string `src`: a Pose is told apart by its object src or its placement fields
const asPose = (d: Pose | AssetRef | string): Pose =>
  typeof d === "object" && (typeof d.src === "object" || (!("kind" in d) && ["feet", "scale", "imgW", "imgH"].some((k) => k in d)))
    ? (d as Pose) : { src: d as AssetRef | string };

export type WalkerProps = Omit<WalkOptions, "h"> & {
  /** the step drawings in order (contact, passing; or left step, right step), each a picture or a Pose */
  drawings: (Pose | AssetRef | string)[];
  /** the soles' line and the drawn height of a canvas, as Performer's y and h; `feet` for plain pictures */
  y: number; h: number; feet?: number;
  /** mirror (default: when walking left, for drawings that face right) */
  flip?: boolean;
  f?: number;
};

/** The classic two-drawing walk: the drawings alternate every `step` frames while the figure travels from x0 to x1,
 *  rising mid-step and squashing as a foot lands; it stands on its soles as Performer does. */
export function Walker({ drawings, y, h, feet, flip, f: fIn, ...o }: WalkerProps) {
  const now = useCurrentFrame();
  if (!drawings.length) throw new Error("Walker: drawings is empty; give two step drawings");
  const w = walkAt(fIn ?? now, { ...o, h });
  const pose = asPose(drawings[w.k % drawings.length]);
  const b = poseBox({ ...pose, feet: pose.feet ?? feet }, h, 1, "Walker");
  const mirror = flip ?? o.x1 < o.x0;
  const sx = 1 / Math.sqrt(w.sy);
  return (
    <div style={{ position: "absolute", left: w.x - b.fx, top: y - b.sole + w.dy, width: b.w, height: b.hh,
      transform: `scale(${mirror ? -sx : sx}, ${w.sy})`, transformOrigin: `${b.fx}px ${b.sole}px` }}>
      <Img src={assetSrc(pose.src)} style={{ width: b.w, height: b.hh, display: "block" }} />
    </div>
  );
}

// ------------------------------------------------------------------ smear frames

export type SmearOptions = {
  /** speed in px a frame above which the smear starts; the most it stretches (1 = twice as long) */
  fast?: number; max?: number;
  /** about half the moving thing's length along its motion, px: the smear keeps its leading edge there */
  r?: number;
};

/** The smear at frame `f` of a thing whose centre is at `pos(frame)`: its motion over the last frame (`dx`, `dy`,
 *  `speed`, `ang` in degrees) and the `stretch` along it (0 when slower than `fast`). */
export const smearAt = (pos: (f: number) => Pt, f: number, o: SmearOptions = {}) => {
  const { fast = 28, max = 1.2, r = 80 } = o;
  const [x, y] = pos(f), [px, py] = pos(f - 1);
  const dx = x - px, dy = y - py, speed = Math.hypot(dx, dy);
  const stretch = speed > fast ? Math.min(max, (0.8 * speed) / (2 * Math.max(1, r))) : 0;
  return { x, y, dx, dy, speed, ang: (Math.atan2(dy, dx) * 180) / Math.PI, stretch };
};

export type SmearProps = SmearOptions & {
  /** where the moving thing's centre is at a frame, stage px; the children draw it there themselves */
  pos: (f: number) => Pt;
  /** trailing ink lines on a smear frame */
  lines?: number;
  seed?: string;
  f?: number;
  children?: React.ReactNode;
};

/** A cartoon smear frame instead of motion blur: on the fast frames what it wraps is stretched along its motion
 *  (thinner across, leading edge kept) with a few ink lines trailing; drawn once. */
export function Smear({ pos, lines = 3, seed = "smear", f: fIn, children, ...o }: SmearProps) {
  const now = useCurrentFrame();
  const { w, h } = useClip();
  const ink = useLineStyle();
  const f = fIn ?? now;
  const s = smearAt(pos, f, o);
  const r = o.r ?? 80, max = o.max ?? 1.2;
  const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: w, height: h };
  if (s.stretch <= 0) return <div style={full}>{children}</div>;
  const ux = s.dx / s.speed, uy = s.dy / s.speed, ax = s.x + ux * r, ay = s.y + uy * r;
  const k = clamp01(s.stretch / max);
  return (
    <div style={full}>
      <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity: Math.min(1, 0.4 + k) }}>
        {Array.from({ length: lines }, (_, i) => {
          const off = (lines > 1 ? i / (lines - 1) - 0.5 : 0) * r * 1.1, len = (0.7 + 0.6 * random(`${seed}${i}${f}`)) * s.speed * 1.4;
          const bx = s.x - ux * r * 0.5 - uy * off, by = s.y - uy * r * 0.5 + ux * off;
          return <line key={i} x1={bx} y1={by} x2={bx - ux * len} y2={by - uy * len} stroke={ink.color}
            strokeWidth={ink.weight * (i % 2 ? 0.6 : 0.9)} strokeLinecap="round" />;
        })}
      </svg>
      <div style={{ ...full, transformOrigin: "0 0",
        transform: `translate(${ax}px, ${ay}px) rotate(${s.ang}deg) scale(${1 + s.stretch}, ${1 / Math.sqrt(1 + s.stretch)}) rotate(${-s.ang}deg) translate(${-ax}px, ${-ay}px)` }}>
        {children}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ brush-pen strokes

/** Points every `gap` px along a polyline or an SVG path, by length. */
export const sampleLine = (line: Pt[] | string, gap: number): Pt[] => {
  if (typeof line === "string") {
    const L = getLength(line), n = Math.max(2, Math.min(800, Math.ceil(L / Math.max(0.5, gap)) + 1));
    return Array.from({ length: n }, (_, i) => { const p = getPointAtLength(line, (L * i) / (n - 1)); return [p?.x ?? 0, p?.y ?? 0] as Pt; });
  }
  const out: Pt[] = line.length ? [line[0]] : [];
  for (let i = 1; i < line.length; i++) {
    const [ax, ay] = line[i - 1], [bx, by] = line[i], m = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / Math.max(0.5, gap)));
    for (let j = 1; j <= m; j++) out.push([ax + ((bx - ax) * j) / m, ay + ((by - ay) * j) / m]);
  }
  return out;
};

/** The first `p` (0..1, by length) of evenly sampled points, the last one cut part way. */
export const partOf = (pts: Pt[], p: number): Pt[] => {
  const k = clamp01(p) * (pts.length - 1), n = Math.floor(k), t = k - n;
  const head = pts.slice(0, n + 1);
  if (t > 1e-6 && pts[n + 1]) head.push([lerp(pts[n][0], pts[n + 1][0], t), lerp(pts[n][1], pts[n + 1][1], t)]);
  return head;
};

const outlinePath = (pts: number[][]): string => {
  if (pts.length < 3) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)} Q`;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
    d += `${x0.toFixed(1)} ${y0.toFixed(1)} ${((x0 + x1) / 2).toFixed(1)} ${((y0 + y1) / 2).toFixed(1)} `;
  }
  return d + "Z";
};

/** Pressure along a brush stroke at `t` (0..1 of its length): light at both ends, full in the middle. */
export const brushPressure = (t: number, taper = 0.6): number => 1 - taper + taper * Math.pow(Math.sin(Math.PI * clamp01(t)), 0.6);

export type BrushProps = {
  /** the centreline: points, or an SVG path `d` */
  line: Pt[] | string;
  /** drawn so far, 0..1 of its length (the pen moving along it) */
  p?: number;
  /** nib width in px (default 1.6 times the LineStyle weight); how much thinner light pressure draws (0..1) */
  size?: number; thinning?: number;
  /** how much the pressure falls at both ends (0 an even line) */
  taper?: number;
  color?: string; opacity?: number;
};

/** A brush-pen stroke along a centreline, filled in the LineStyle colour: thick in the middle, tapered at the ends,
 *  drawn on by `p`. */
export function Brush({ line, p = 1, size, thinning = 0.6, taper = 0.6, color, opacity }: BrushProps) {
  const ink = useLineStyle();
  const nib = size ?? ink.weight * 1.6;
  const pts = useMemo(() => sampleLine(line, Math.max(1, nib / 3)), [line, nib]);
  if (p <= 0 || pts.length < 2) return null;
  const done = partOf(pts, p), n = pts.length - 1;
  const outline = getStroke(done.map(([x, y], i) => [x, y, brushPressure(i / n, taper)]), {
    size: nib, thinning, smoothing: 0.5, streamline: 0.3, simulatePressure: false, last: p >= 1,
    start: { taper: nib * 2, cap: true }, end: { taper: p >= 1 ? nib * 2 : 0, cap: true },
  });
  return (
    <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity }}>
      <path d={outlinePath(outline)} fill={color ?? ink.color} />
    </svg>
  );
}

// ------------------------------------------------------------------ shape morphs

const MORPHS = new Map<string, (t: number) => string>();

/** The closed shape `from` turned `p` (0..1) of the way into `to` (both SVG paths); the interpolator is built once
 *  per pair and kept. */
export const morphAt = (from: string, to: string, p: number, maxSegmentLength = 6): string => {
  if (p <= 0) return from;
  if (p >= 1) return to;
  const key = `${maxSegmentLength}\n${from}\n${to}`;
  let mix = MORPHS.get(key);
  if (!mix) {
    mix = flubber(from, to, { maxSegmentLength });
    if (MORPHS.size >= 64) MORPHS.delete(MORPHS.keys().next().value as string);
    MORPHS.set(key, mix);
  }
  return mix(p);
};

export type MorphProps = {
  from: string; to: string; p: number;
  /** the fill, and the outline (default the LineStyle line; `false` none) */
  fill?: string; stroke?: string | false; weight?: number;
  /** the longest segment flubber cuts the outlines into, px: smaller is smoother and slower to build */
  maxSegmentLength?: number;
};

/** A closed shape turning into another by `p`: a puddle into a splash, a cloud into a heart. */
export function Morph({ from, to, p, fill = "none", stroke, weight, maxSegmentLength = 6 }: MorphProps) {
  const ink = useLineStyle();
  return (
    <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <path d={morphAt(from, to, p, maxSegmentLength)} fill={fill} stroke={stroke === false ? "none" : stroke ?? ink.color}
        strokeWidth={weight ?? ink.weight} strokeLinejoin="round" />
    </svg>
  );
}

// ------------------------------------------------------------------ boiling lines

/** The turbulence seed at frame `f`: a new one every `every` frames, cycling through `drawings` of them. */
export const boilSeed = (f: number, seed = 1, every = 2, drawings = 3): number =>
  seed + ((Math.floor(f / Math.max(1, every)) % drawings) + drawings) % drawings;

export type BoilProps = {
  /** how far lines wander, px at a 1080 frame; the size of the wobbles, px */
  amount?: number; grain?: number;
  /** the part that boils [x, y, w, h], clip px (default the whole clip; a smaller box costs less): it must hold
   *  everything wrapped, as nothing outside it is drawn */
  box?: [number, number, number, number];
  every?: number; drawings?: number; seed?: number;
  f?: number;
  children?: React.ReactNode;
};

/** Lines that boil as hand-drawn frames do: what it wraps is displaced by noise re-seeded on twos, cycling through
 *  a few drawings. One render of the children; only `box` is filtered. */
export function Boil({ amount = 3, grain = 40, box, every = 2, drawings = 3, seed = 1, f: fIn, children }: BoilProps) {
  const now = useCurrentFrame();
  const { w, h } = useClip();
  const u = useUnit();
  const id = "bo" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const s = amount * u, [bx, by, bw, bh] = box ?? [0, 0, w, h];
  const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: w, height: h };
  if (!(s > 0)) return <div style={full}>{children}</div>;
  return (
    <div style={full}>
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id={id} filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" x={bx - s} y={by - s} width={bw + 2 * s} height={bh + 2 * s}
          colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency={(1 / Math.max(1, grain * u)).toFixed(5)} numOctaves={1}
            seed={boilSeed(fIn ?? now, seed, every, drawings)} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={2 * s} xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
      <div style={{ ...full, filter: `url(#${id})` }}>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ OKLCH ramps

type Lch = [number, number, number];
const hexRgb = (hex: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`ramp: "${hex}" is not a #rgb or #rrggbb colour`);
  const v = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255) as [number, number, number];
};
const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const toSrgb = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
const toOklch = (hex: string): Lch => {
  const [r, g, b] = hexRgb(hex).map(toLin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793661785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), Math.atan2(B, A)];
};
const fromOklch = ([L, C, H]: Lch): [number, number, number] => {
  const A = C * Math.cos(H), B = C * Math.sin(H);
  const l = Math.pow(L + 0.3963377774 * A + 0.2158037573 * B, 3), m = Math.pow(L - 0.1055613458 * A - 0.0638541728 * B, 3);
  const s = Math.pow(L - 0.0894841775 * A - 1.291485548 * B, 3);
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
};
const inGamut = (c: number[]) => c.every((v) => v >= -1e-4 && v <= 1 + 1e-4);
const lchHex = (lch: Lch): string => {
  let rgb = fromOklch(lch);
  if (!inGamut(rgb)) {
    let lo = 0, hi = lch[1];                        // keep lightness and hue, give up chroma until it fits
    for (let i = 0; i < 20; i++) { const c = (lo + hi) / 2; if (inGamut(fromOklch([lch[0], c, lch[2]]))) lo = c; else hi = c; }
    rgb = fromOklch([lch[0], lo, lch[2]]);
  }
  return "#" + rgb.map((v) => Math.round(clamp01(toSrgb(clamp01(v))) * 255).toString(16).padStart(2, "0")).join("").toUpperCase();
};

/** `steps` colours from `light` to `dark` evenly in OKLCH (perceived lightness, chroma, the shorter way round the
 *  hue): one shadow ramp that reads the same across props. Both ends included. */
export const ramp = (light: string, dark: string, steps = 5): string[] => {
  const a = toOklch(light), b = toOklch(dark), n = Math.max(2, Math.round(steps));
  // a grey end takes the other end's hue
  const ha = a[1] < 1e-4 ? b[2] : a[2], hb = b[1] < 1e-4 ? ha : b[2];
  let dh = hb - ha;
  if (dh > Math.PI) dh -= 2 * Math.PI;
  if (dh < -Math.PI) dh += 2 * Math.PI;
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    if (i === 0) return lchHex(a);
    if (i === n - 1) return lchHex(b);
    return lchHex([lerp(a[0], b[0], t), lerp(a[1], b[1], t), ha + dh * t]);
  });
};

// ------------------------------------------------------------------ baked simulations

/** State `f` of a baked run (one entry a frame from the clip's start), held at the first and last. */
export const bakedAt = <T,>(data: T[], f: number): T => {
  if (!Array.isArray(data) || !data.length) throw new Error("useBaked: the baked data is empty; bake one state a frame into an array");
  return data[Math.min(data.length - 1, Math.max(0, Math.round(f)))];
};

/** The baked state at frame `f` (default the current frame). */
export const useBaked = <T,>(data: T[], f?: number): T => {
  const now = useCurrentFrame();
  return bakedAt(data, f ?? now);
};
