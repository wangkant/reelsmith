// Drawn-pose animation: a drawn character acted pose to pose as limited TV animation does, props tossed on arcs, and
// cartoon effects drawn in the drawings' own line. Every time here is in frames.
import React, { createContext, useContext, useId } from "react";
import { Img, random, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import type { Pt } from "./geom";
import { useUnit } from "./palette";
import { pictureSize } from "./photo";
import { clamp01 } from "./time";

/** One key pose of the performer: `src` with the mouth open; its twins, all on `src`'s canvas (draw's `twin_of`):
 *  `shut` the mouth closed (twin_of src), `blink` the eyes shut on the shut drawing (twin_of shut), `blinkOpen` the
 *  eyes shut with the mouth open (twin_of src). `scale` multiplies this pose so its head matches the others; `feet`
 *  is the x midway between the feet as a fraction of the canvas width (default 0.5; draw reports it). */
export type Pose = {
  src: AssetRef | string; shut?: AssetRef | string; blink?: AssetRef | string; blinkOpen?: AssetRef | string;
  scale?: number; feet?: number; imgW?: number; imgH?: number;
};

/** The drawing shown: while talking the open mouth (eyes shut only through `blinkOpen`, else the blink is skipped);
 *  in silence the shut mouth, `blink` while blinking. A blink never opens the mouth. */
export const faceAt = (pose: Pose, talking: boolean, blinking: boolean): AssetRef | string =>
  talking ? (blinking && pose.blinkOpen ? pose.blinkOpen : pose.src)
    : blinking && pose.blink ? pose.blink : pose.shut ?? pose.src;

const TWINS = { shut: "the pose", blink: "its shut twin", blinkOpen: "the pose" } as const;
const refSize = (r?: AssetRef | string): [number, number] | null =>
  isAsset(r) && r.size && r.size[0] > 0 && r.size[1] > 0 ? [r.size[0], r.size[1]] : null;

/** Throws when a twin's pixel size differs from its pose's picture: it was not registered onto the pose's canvas. */
export const checkTwins = (poses: Record<string, Pose>) => {
  for (const [id, p] of Object.entries(poses)) {
    const base = p.imgW && p.imgH ? [p.imgW, p.imgH] : refSize(p.src);
    if (!base) continue;
    for (const k of Object.keys(TWINS) as (keyof typeof TWINS)[]) {
      const s = refSize(p[k]);
      if (s && (s[0] !== base[0] || s[1] !== base[1])) {
        throw new Error(`Performer: pose "${id}": its ${k} picture is ${s[0]}x${s[1]} but the pose is ${base[0]}x${base[1]}; `
          + `redraw the twin with draw(..., twin_of=<${TWINS[k]}>) so it lies on the same canvas `
          + "(an unregistered twin makes the whole figure jump on every mouth flap)");
      }
    }
  }
};

/** Where a pose stands at drawn height `h` (clip px at scale 1): its size `w` x `hh`, the feet `fx` px from its left
 *  edge, and `s` the picture-to-clip factor. */
export const poseBox = (pose: Pose, h: number, scale = 1, who = "Performer") => {
  const [IW, IH] = pictureSize(pose.src, pose.imgW, pose.imgH, who);
  const s = (h / IH) * (pose.scale ?? 1) * scale;
  return { w: IW * s, hh: IH * s, fx: (pose.feet ?? 0.5) * IW * s, s };
};

const byAt = <T extends { at: number }>(xs: T[]): T[] => [...xs].sort((a, b) => a.at - b.at);

/** From frame `at` the performer holds `pose`; `dir` is the way the move goes (1 right, -1 left, 0 straight). */
export type Beat = { at: number; pose: string; dir?: number; scale?: number };

/** How a snap from pose to pose is acted. Defaults are the values of a tested film. */
export type ActOptions = {
  /** frames of anticipation before a snap: a crouch and a lean against the move */
  antic?: number; anticSquash?: number; anticLean?: number; anticDip?: number;
  /** frames of overshoot after a snap, settling: squash and stretch, rotation about the feet */
  settle?: number; overSquash?: number; overRot?: number; overDecay?: number; overHz?: number;
  /** the moving hold: breath (a fraction of height) and sway (degrees), periods in seconds */
  breath?: number; breathPeriod?: number; sway?: number; swayPeriod?: number;
  fps?: number;
};

/** The performer at one frame: which beat, its pose and scale, and the squash, stretch, rotation and dip to apply. */
export type Act = { i: number; pose: string; scale: number; sx: number; sy: number; rot: number; dy: number };

/** Index of the beat in force at frame `f` (the first beat before it starts). Beats must be in time order. */
export const beatAt = (beats: Beat[], f: number): number => {
  let i = 0;
  for (let k = 0; k < beats.length; k++) if (f >= beats[k].at) i = k;
  return i;
};

/** Anticipation, snap, overshoot and moving hold at frame `f`: a pure function of the frame. Beats in any order
 *  (sorted by `at`, ties kept in the order given); `i` indexes the sorted list. */
export const actAt = (beatsIn: Beat[], f: number, o: ActOptions = {}): Act => {
  if (!beatsIn.length) throw new Error("Performer: beats is empty; give at least one {at, pose}");
  const beats = byAt(beatsIn);
  const { antic = 3, anticSquash = 0.07, anticLean = 3, anticDip = 6, settle = 12, overSquash = 0.09, overRot = 5,
    overDecay = 3.2, overHz = 0.95, breath = 0.012, breathPeriod = 2.8, sway = 0.6, swayPeriod = 4.1, fps = 30 } = o;
  const i = beatAt(beats, f);
  const b = beats[i], next = beats[i + 1];
  let sx = 1, sy = 1, rot = 0, dy = 0;
  if (next && antic > 0 && f >= next.at - antic && f < next.at) {
    const k = (f - (next.at - antic) + 1) / antic;
    sy = 1 - anticSquash * k; sx = 1 + anticSquash * 0.65 * k; rot = -(next.dir ?? 1) * anticLean * k; dy = anticDip * k;
  } else if (i > 0 && f - b.at < settle && f >= b.at) {
    const k = f - b.at, a = Math.exp(-k / overDecay) * Math.cos(k * overHz);
    sy = 1 + overSquash * a; sx = 1 - overSquash * 0.67 * a; rot = (b.dir ?? 1) * overRot * a;
  }
  const t = f / fps;
  const br = Math.sin((2 * Math.PI * t) / breathPeriod);
  sy *= 1 + breath * br; sx *= 1 - (breath / 2) * br;
  rot += sway * Math.sin((2 * Math.PI * t) / swayPeriod);
  return { i, pose: b.pose, scale: b.scale ?? 1, sx, sy, rot, dy };
};

/** Eyes shut at frame `f` on an automatic schedule: a blink of `len` frames every `every` [min, max] seconds, the
 *  same for the same seed. */
export const blinkAt = (f: number, seed = "blink", every: [number, number] = [2.5, 5], len = 3, fps = 30): boolean => {
  if (f < 0 || len <= 0) return false;
  const gap = (k: number) => Math.max(len + 1, Math.round((every[0] + (every[1] - every[0]) * random(`${seed}${k}`)) * fps));
  let t = gap(0);
  for (let k = 1; t <= f; k++) {
    if (f < t + len) return true;
    t += gap(k);
  }
  return false;
};

/** Mouth open at frame `f`: the voice level read on twos (the mouth changes every other frame), opening above `open`
 *  and staying open while it stays above `hold` (hysteresis over the last few twos, so the jaw does not chatter). */
export const talkAt = (level: ((f: number) => number) | number[], f: number, open = 0.14, hold = 0.07): boolean => {
  const L = typeof level === "function" ? level : (k: number) => level[k] ?? 0;
  const g = f - (((f % 2) + 2) % 2);
  for (let k = 0; k < 6; k++) {
    const v = L(g - 2 * k);
    if (v > open) return true;
    if (v <= hold) return false;
  }
  return false;
};

/** The narration's loudness 0..1 at a frame from the clip's start (0 without a voice, or past it). */
export const useVoiceLevel = (): ((f: number) => number) => {
  const { level } = useClip();
  return (f: number) => (level ? level[Math.round(f)] ?? 0 : 0);
};

/** Acting inside a held drawing: a nod, a bob on a word. Added to the act at that frame. */
export type Nudge = { dx?: number; dy?: number; rot?: number; sy?: number };

export type PerformerProps = ActOptions & {
  poses: Record<string, Pose>;
  beats: Beat[];
  /** where the feet stand (the point `feet` of the canvas's bottom edge), clip px */
  x: number; y: number;
  /** the drawn height of a pose's canvas at scale 1, clip px */
  h: number;
  flip?: boolean;
  /** the voice level per frame (default useVoiceLevel()); thresholds as in talkAt */
  level?: (f: number) => number; open?: number; hold?: number;
  /** extra blinks: frames where one starts */
  blinks?: number[];
  /** automatic blinks (shown as faceAt picks) every `blinkEvery` [min, max] seconds, `blinkLen` frames */
  autoBlink?: boolean; blinkEvery?: [number, number]; blinkLen?: number;
  nudge?: (f: number) => Nudge;
  seed?: string;
  f?: number;
};

/** A drawn character played pose to pose: holds a drawing, anticipates, snaps to the next, overshoots and settles,
 *  breathes while it holds, flaps its mouth on the voice and blinks. */
export function Performer({ poses, beats, x, y, h, flip = false, level: levelIn, open = 0.14, hold = 0.07, blinks = [],
  autoBlink = true, blinkEvery = [2.5, 5], blinkLen = 3, nudge, seed = "performer", f: fIn, ...o }: PerformerProps) {
  const now = useCurrentFrame();
  const voice = useVoiceLevel();
  const f = fIn ?? now;
  const level = levelIn ?? voice;
  const { fps } = useClip();
  checkTwins(poses);
  const a = actAt(beats, f, { fps, ...o });
  const pose = poses[a.pose];
  if (!pose) throw new Error(`Performer: a beat names pose "${a.pose}", not one of ${Object.keys(poses).join(", ")}`);
  const n = nudge ? nudge(f) : {};
  const sy = a.sy * (n.sy ?? 1), sx = a.sx / Math.sqrt(n.sy ?? 1);
  const { w, hh, fx } = poseBox(pose, h, a.scale);
  const blinking = blinks.some((b) => f >= b && f < b + blinkLen) || (autoBlink && blinkAt(f, seed, blinkEvery, blinkLen, fps));
  const pic = faceAt(pose, talkAt(level, f, open, hold), blinking);
  return (
    <div style={{
      position: "absolute", left: x - fx + (n.dx ?? 0), top: y - hh + a.dy + (n.dy ?? 0), width: w, height: hh,
      transform: `rotate(${a.rot + (n.rot ?? 0)}deg) scale(${flip ? -sx : sx}, ${sy})`, transformOrigin: `${fx}px ${hh}px`,
    }}>
      <Img src={assetSrc(pic)} style={{ width: w, height: hh, display: "block" }} />
    </div>
  );
}

export type PoseSheetProps = {
  poses: Record<string, Pose>;
  /** which poses, in order (default all) */
  ids?: string[];
  /** as Performer's h */
  h: number;
  /** the ground line's y (default 85% down the frame) */
  y?: number;
  /** the drawing shown for each pose */
  show?: "src" | "shut" | "blink" | "blinkOpen";
};

/** A preview still: the poses side by side on one ground line, each placed as Performer places it (same `h`, its
 *  `scale` and `feet`), its id under it, a tick at its feet and a guide across at the first pose's head top (its
 *  canvas top less draw's 2% trim pad): one look shows whether the head size holds and the feet are right. */
export function PoseSheet({ poses, ids, h, y, show = "src" }: PoseSheetProps) {
  const { w: W, h: H } = useClip();
  const ink = useLineStyle();
  checkTwins(poses);
  const list = ids ?? Object.keys(poses);
  const gy = y ?? H * 0.85;
  const boxes = list.map((id) => {
    const p = poses[id];
    if (!p) throw new Error(`PoseSheet: no pose "${id}"; poses has ${Object.keys(poses).join(", ")}`);
    return { id, p, b: poseBox(p, h, 1, "PoseSheet") };
  });
  const first = boxes[0];
  const head = first ? gy - first.b.hh + 0.02 * Math.max(first.b.w, first.b.hh) : 0;
  const font = Math.max(32, W / 30);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: H }}>
      {boxes.map(({ id, p, b }, i) => {
        const cx = (W * (i + 0.5)) / boxes.length;
        return (
          <React.Fragment key={id}>
            <Img src={assetSrc(p[show] ?? p.src)} style={{ position: "absolute", left: cx - b.fx, top: gy - b.hh, width: b.w, height: b.hh }} />
            <div style={{ position: "absolute", left: cx - ink.weight / 2, top: gy - font * 0.6, width: ink.weight, height: font * 1.2, background: "#D0342C" }} />
            <div style={{ position: "absolute", left: cx - 200, top: gy + font * 0.8, width: 400, textAlign: "center", fontSize: font, fontFamily: "sans-serif", color: ink.color }}>{id}</div>
          </React.Fragment>
        );
      })}
      <div style={{ position: "absolute", left: 0, top: gy - ink.weight / 4, width: W, height: ink.weight / 2, background: ink.color }} />
      <div style={{ position: "absolute", left: 0, top: head, width: W, borderTop: `${Math.max(2, ink.weight / 3)}px dashed #D0342C` }} />
    </div>
  );
}

/** A hard cut: from frame `at` the scene is shown `z` times larger with its point (`x`, `y`) at the frame centre. */
export type FramingCut = { at: number; x: number; y: number; z: number };

/** The framing in force at frame `f`: before the first cut the whole frame (z 1, centred). With `scene` [w, h] (the
 *  drawn scene's size in its own px, from 0, 0) it is clamped so no edge of the scene shows. */
export const framingAt = (cuts: FramingCut[], f: number, w: number, h: number, scene?: [number, number]): { x: number; y: number; z: number } => {
  let c = { x: w / 2, y: h / 2, z: 1 };
  for (const k of byAt(cuts)) if (f >= k.at) c = { x: k.x, y: k.y, z: k.z };
  if (!scene) return c;
  const z = Math.max(c.z, w / scene[0], h / scene[1]);
  const fit = (v: number, half: number, side: number) => Math.min(Math.max(v, half), side - half);
  return { x: fit(c.x, w / (2 * z), scene[0]), y: fit(c.y, h / (2 * z), scene[1]), z };
};

export type FramingProps = { cuts: FramingCut[]; scene?: [number, number]; f?: number; children?: React.ReactNode };

/** Hard cuts between framings of one drawn scene (wide, mid, a close shot of the detail): no easing, no move. */
export function Framing({ cuts, scene, f: fIn, children }: FramingProps) {
  const now = useCurrentFrame();
  const { w, h } = useClip();
  const c = framingAt(cuts, fIn ?? now, w, h, scene);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0",
        transform: `translate(${w / 2 - c.x * c.z}px, ${h / 2 - c.y * c.z}px) scale(${c.z})` }}>{children}</div>
    </div>
  );
}

/** A prop thrown from `from` to `to`: a parabola `height` px above the straight line, stretched in flight, squashed
 *  on landing and settling; `spin` degrees over the flight. Before `at` it waits at `from`. */
export type Toss = { x: number; y: number; r: number; sx: number; sy: number; t: number; landed: boolean };
export const toss = (f: number, at: number, from: Pt, to: Pt, len = 18, height = 220, spin = 0): Toss => {
  if (f < at) return { x: from[0], y: from[1], r: 0, sx: 1, sy: 1, t: 0, landed: false };
  const k = f - at;
  if (k < len) {
    const t = k / len;
    return { x: from[0] + (to[0] - from[0]) * t, y: from[1] + (to[1] - from[1]) * t - 4 * height * t * (1 - t),
      r: spin * t, sx: 0.94, sy: 1.08, t, landed: false };
  }
  const j = k - len, a = Math.exp(-j / 4) * Math.cos(j * 0.9);
  return { x: to[0], y: to[1], r: spin, sx: 1 + 0.16 * a, sy: 1 - 0.18 * a, t: 1, landed: true };
};

// ------------------------------------------------------------------ effects in the drawings' line

export type LineStyleValue = { color: string; weight: number; paper: string; spark: string };
const LineCtx = createContext<Partial<LineStyleValue>>({});

/** Sets the ink once for the effects inside: line `color` and `weight` (match the drawings), `paper` (the light fill
 *  of steam, flashes and marks) and `spark` (stars). */
export function LineStyle({ children, ...v }: Partial<LineStyleValue> & { children?: React.ReactNode }) {
  return <LineCtx.Provider value={{ ...useContext(LineCtx), ...v }}>{children}</LineCtx.Provider>;
}

/** The ink in force: a dark brown line 9 px wide at a 1080 px frame unless a LineStyle says otherwise. */
export const useLineStyle = (): LineStyleValue => {
  const c = useContext(LineCtx);
  const u = useUnit();
  return { color: c.color ?? "#2A1A0E", weight: c.weight ?? 9 * u, paper: c.paper ?? "#FFFBF2", spark: c.spark ?? "#FFD45C" };
};

const Canvas = ({ children, opacity }: { children: React.ReactNode; opacity?: number }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity }}>{children}</svg>
);
const life = (f: number, at: number, len: number) => (f < at || f >= at + len ? -1 : (f - at) / len);
const starPath = (r: number) => {
  const q = r * 0.1;
  return `M0 ${-r} Q${q} ${-q} ${r} 0 Q${q} ${q} 0 ${r} Q${-q} ${q} ${-r} 0 Q${-q} ${-q} 0 ${-r}Z`;
};

export type BurstProps = { x: number; y: number; at: number; r?: number; n?: number; len?: number; seed?: string; f?: number };
/** An impact: a jagged flash and rays shooting out from (x, y), over in `len` frames. */
export function Burst({ x, y, at, r = 120, n = 9, len = 14, seed = "burst", f: fIn }: BurstProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const k = life(fIn ?? now, at, len);
  if (k < 0) return null;
  const flash = k < 0.4 ? 1 - k / 0.4 : 0;
  const pts = Array.from({ length: n * 2 }, (_, i) => {
    const a = (i / (n * 2)) * 2 * Math.PI, rr = (i % 2 ? 0.45 : 0.85 + 0.3 * random(`${seed}${i}`)) * r * (0.7 + 0.5 * k);
    return `${(x + Math.cos(a) * rr).toFixed(1)},${(y + Math.sin(a) * rr).toFixed(1)}`;
  }).join(" ");
  return (
    <Canvas>
      {flash > 0 ? <polygon points={pts} fill={ink.paper} stroke={ink.color} strokeWidth={ink.weight} strokeLinejoin="round" opacity={flash} /> : null}
      {Array.from({ length: n }, (_, i) => {
        const a = ((i + 0.5) / n) * 2 * Math.PI + random(`${seed}a${i}`) * 0.3;
        const r0 = r * (0.9 + 0.9 * k), r1 = r0 + r * 0.7 * (1 - k);
        return <line key={i} x1={x + Math.cos(a) * r0} y1={y + Math.sin(a) * r0} x2={x + Math.cos(a) * r1} y2={y + Math.sin(a) * r1}
          stroke={ink.color} strokeWidth={ink.weight * 1.3} strokeLinecap="round" />;
      })}
    </Canvas>
  );
}

export type ToonStarProps = { x: number; y: number; r?: number; rot?: number; at?: number; len?: number; spin?: number; color?: string; f?: number };
/** A cartoon four-point star with an ink outline; with `at`, it pops up, spins and shrinks away over `len` frames. */
export function ToonStar({ x, y, r = 48, rot = 0, at, len = 20, spin = 6, color, f: fIn }: ToonStarProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const f = fIn ?? now;
  let rr = r, a = rot;
  if (at !== undefined) {
    const k = life(f, at, len);
    if (k < 0) return null;
    // pops to full size with an overshoot, twinkles while it holds, shrinks away at the end
    const j = f - at, pop = 1 - Math.exp(-j / 1.8) * Math.cos(j * 0.9);
    rr = r * pop * (k > 0.7 ? (1 - k) / 0.3 : 1) * (1 + 0.08 * Math.sin(j * 1.3));
    a = rot + spin * (f - at);
  }
  if (rr <= 0.5) return null;
  return (
    <Canvas>
      <path d={starPath(rr)} transform={`translate(${x} ${y}) rotate(${a})`} fill={color ?? ink.spark} stroke={ink.color}
        strokeWidth={Math.max(ink.weight * 0.6, rr * 0.13)} strokeLinejoin="round" />
    </Canvas>
  );
}

export type SteamCurlsProps = { x: number; y: number; n?: number; spread?: number; rise?: number; scale?: number; at?: number; f?: number };
/** Cartoon steam: wavy light curls with an ink edge rising from (x, y) and fading, looping from `at`. */
export function SteamCurls({ x, y, n = 3, spread = 120, rise = 260, scale = 1, at = 0, f: fIn }: SteamCurlsProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const f = (fIn ?? now) - at;
  if (f < 0) return null;
  return (
    <Canvas>
      {Array.from({ length: n }, (_, i) => {
        const period = 64 + i * 9, t = ((f + i * 23) % period) / period;
        const cx = x + (i - (n - 1) / 2) * spread * 0.5, cy = y - t * rise, L = 80 * scale, q = 20 * scale;
        const d = `M${cx} ${cy} q${q} ${-L / 3} 0 ${-L / 1.5} q${-q} ${-L / 3} 0 ${-L / 1.5}`;
        return (
          <g key={i} opacity={Math.sin(t * Math.PI)}>
            <path d={d} fill="none" stroke={ink.color} strokeWidth={ink.weight * 2 * scale} strokeLinecap="round" />
            <path d={d} fill="none" stroke={ink.paper} strokeWidth={ink.weight * 1.1 * scale} strokeLinecap="round" />
          </g>
        );
      })}
    </Canvas>
  );
}

export type SplashProps = { x: number; y: number; at: number; w?: number; n?: number; len?: number; color?: string; seed?: string; f?: number };
/** Something lands in liquid at (x, y): a ring spreading on the surface and drops thrown up that fall back, filled
 *  with `color` (default the LineStyle paper). */
export function Splash({ x, y, at, w = 180, n = 6, len = 24, color, seed = "splash", f: fIn }: SplashProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const k = life(fIn ?? now, at, len);
  if (k < 0) return null;
  const j = k * len, rx = w * (0.3 + 0.9 * k);
  return (
    <Canvas>
      <ellipse cx={x} cy={y} rx={rx} ry={rx * 0.28} fill="none" stroke={ink.color} strokeWidth={ink.weight} opacity={1 - k} />
      {Array.from({ length: n }, (_, i) => {
        const vx = (i / Math.max(1, n - 1) - 0.5) * 2 * (0.8 + 0.4 * random(`${seed}x${i}`)), vy = 1 + 0.8 * random(`${seed}y${i}`);
        const t = j / 30, dx = vx * w * 1.5 * t, dy = -vy * 560 * t + 0.5 * 2800 * t * t;
        const r = (0.11 + 0.05 * random(`${seed}r${i}`)) * w;
        return dy < r ? <ellipse key={i} cx={x + dx} cy={y + dy} rx={r * 0.8} ry={r} fill={color ?? ink.paper} stroke={ink.color} strokeWidth={ink.weight * 0.7} /> : null;
      })}
    </Canvas>
  );
}

export type SpeedLinesProps = { x: number; y: number; at: number; dir?: number; len?: number; n?: number; spread?: number; life?: number; seed?: string; f?: number };
/** Strokes trailing behind a move: `dir` is the way the thing goes (degrees, 0 = right); they shoot back and thin out. */
export function SpeedLines({ x, y, at, dir = 0, len = 240, n = 5, spread = 170, life: span = 10, seed = "speed", f: fIn }: SpeedLinesProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const k = life(fIn ?? now, at, span);
  if (k < 0) return null;
  const a = (dir * Math.PI) / 180, bx = -Math.cos(a), by = -Math.sin(a), px = -by, py = bx;
  return (
    <Canvas>
      {Array.from({ length: n }, (_, i) => {
        const off = (i / Math.max(1, n - 1) - 0.5) * spread, l = len * (0.6 + 0.4 * random(`${seed}${i}`));
        const s0 = l * 0.2 + l * 0.8 * k, s1 = s0 + l * (1 - k);
        const ox = x + px * off, oy = y + py * off;
        return <line key={i} x1={ox + bx * s0} y1={oy + by * s0} x2={ox + bx * s1} y2={oy + by * s1}
          stroke={ink.color} strokeWidth={ink.weight * (1.2 - 0.6 * k)} strokeLinecap="round" />;
      })}
    </Canvas>
  );
}

export type SweatDropProps = { x: number; y: number; at: number; size?: number; len?: number; color?: string; f?: number };
/** A nervous sweat drop that pops on at (x, y) and slides down a little before it fades. */
export function SweatDrop({ x, y, at, size = 54, len = 30, color = "#9FD8F2", f: fIn }: SweatDropProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const k = life(fIn ?? now, at, len);
  if (k < 0) return null;
  const pop = k < 0.2 ? Math.sin((k / 0.2) * Math.PI * 0.75) / 0.71 : 1;
  const s = size * pop, dy = size * 0.8 * Math.max(0, k - 0.3);
  const d = `M0 ${-s} C${s * 0.25} ${-s * 0.4} ${s * 0.55} ${-s * 0.05} ${s * 0.55} ${s * 0.3} A${s * 0.55} ${s * 0.55} 0 0 1 ${-s * 0.55} ${s * 0.3} C${-s * 0.55} ${-s * 0.05} ${-s * 0.25} ${-s * 0.4} 0 ${-s}Z`;
  return (
    <Canvas opacity={k > 0.8 ? (1 - k) / 0.2 : 1}>
      <path d={d} transform={`translate(${x} ${y + dy})`} fill={color} stroke={ink.color} strokeWidth={ink.weight * 0.8} strokeLinejoin="round" />
    </Canvas>
  );
}

export type PopMarkProps = { x: number; y: number; at: number; kind?: "!" | "?"; size?: number; len?: number; r?: number; color?: string; f?: number };
/** An exclamation or question mark (filled with the spark colour) that pops over a head with an overshoot, wobbles
 *  and fades. */
export function PopMark({ x, y, at, kind = "!", size = 170, len = 36, r = 10, color, f: fIn }: PopMarkProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const f = fIn ?? now;
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at, s = size * (1 - Math.exp(-j / 2.5) * Math.cos(j * 0.9)), w = s * 0.14;
  const body = kind === "!" ? `M0 ${-s * 0.5} L0 ${s * 0.12}` : `M${-s * 0.2} ${-s * 0.3} Q${-s * 0.2} ${-s * 0.55} 0 ${-s * 0.55} Q${s * 0.22} ${-s * 0.55} ${s * 0.22} ${-s * 0.33} Q${s * 0.22} ${-s * 0.15} 0 ${-s * 0.05} L0 ${s * 0.1}`;
  const fill = color ?? ink.spark;
  return (
    <Canvas opacity={k > 0.8 ? (1 - k) / 0.2 : 1}>
      <g transform={`translate(${x} ${y}) rotate(${r + 6 * Math.exp(-j / 6) * Math.sin(j * 0.7)})`}>
        <path d={body} fill="none" stroke={ink.color} strokeWidth={w + ink.weight * 1.6} strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={0} cy={s * 0.38} r={w * 0.7 + ink.weight * 0.8} fill={ink.color} />
        <path d={body} fill="none" stroke={fill} strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={0} cy={s * 0.38} r={w * 0.7} fill={fill} />
      </g>
    </Canvas>
  );
}

export type CracksProps = { x: number; y: number; at?: number; len?: number; p?: number; clip?: [number, number, number, number] | string; n?: number; reach?: number; seed?: string; f?: number };
/** Cracks spreading from a hit at (x, y) over `len` frames from `at` (or as `p` goes 0..1), kept inside `clip`: an
 *  ellipse [cx, cy, rx, ry] or a path. They stay once grown. */
export function Cracks({ x, y, at = 0, len = 6, p, clip, n = 7, reach = 320, seed = "cracks", f: fIn }: CracksProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const id = "ck" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const k = clamp01(p ?? (len > 0 ? ((fIn ?? now) - at + 1) / len : (fIn ?? now) >= at ? 1 : 0));
  if (k <= 0) return null;
  const paths: string[] = [];
  for (let i = 0; i < n; i++) {
    let a = (i / n) * Math.PI * 2 + random(`${seed}${i}`) * 0.6, cx = x, cy = y, d = `M${x} ${y}`;
    const len = (0.45 + random(`${seed}l${i}`) * 0.8) * reach * k;
    for (let s = 0; s < 6; s++) {
      a += (random(`${seed}${i}a${s}`) - 0.5) * 0.9;
      cx += (Math.cos(a) * len) / 6; cy += (Math.sin(a) * len) / 6;
      d += ` L${cx.toFixed(1)} ${cy.toFixed(1)}`;
      if (s === 2 && k > 0.5) {
        const b = a + (random(`${seed}${i}b`) > 0.5 ? 0.9 : -0.9);
        paths.push(`M${cx.toFixed(1)} ${cy.toFixed(1)} l${(Math.cos(b) * len * 0.35).toFixed(1)} ${(Math.sin(b) * len * 0.35).toFixed(1)}`);
      }
    }
    paths.push(d);
  }
  return (
    <Canvas>
      {clip ? <defs><clipPath id={id}>{typeof clip === "string" ? <path d={clip} /> : <ellipse cx={clip[0]} cy={clip[1]} rx={clip[2]} ry={clip[3]} />}</clipPath></defs> : null}
      <g clipPath={clip ? `url(#${id})` : undefined} fill="none" stroke={ink.color} strokeLinecap="round" strokeLinejoin="round">
        {paths.map((d, i) => <path key={i} d={d} strokeWidth={ink.weight * (i % 2 ? 0.7 : 1)} />)}
      </g>
    </Canvas>
  );
}

export type DustPuffProps = { x: number; y: number; at: number; w?: number; n?: number; len?: number; color?: string; seed?: string; f?: number };
/** A landing kicks up dust: two cartoon clouds (`n` bumps each, one shared ink edge) rolling out sideways along the
 *  ground from (x, y), swelling, rising a little and thinning away. */
export function DustPuff({ x, y, at, w = 260, n = 4, len = 22, color = "#EFE3CC", seed = "dust", f: fIn }: DustPuffProps) {
  const now = useCurrentFrame();
  const ink = useLineStyle();
  const k = life(fIn ?? now, at, len);
  if (k < 0) return null;
  const e = 1 - Math.pow(1 - k, 3);
  const bumps = [-1, 1].flatMap((side) => Array.from({ length: n }, (_, i) => {
    const u = i / Math.max(1, n - 1);
    const r = w * (0.07 + 0.05 * (1 - u) + 0.03 * random(`${seed}${side}${i}`)) * (0.7 + 0.6 * e);
    return { cx: x + side * w * (0.12 + 0.3 * u) * (0.4 + 0.9 * e), cy: y - r * 0.8 - w * 0.1 * e * (1 - u), r };
  }));
  // every edge first, then every fill: the bumps of one cloud merge into one outline
  return (
    <Canvas opacity={k > 0.55 ? Math.max(0, (1 - k) / 0.45) : 1}>
      {bumps.map((b, i) => <circle key={"e" + i} cx={b.cx} cy={b.cy} r={b.r + ink.weight * 0.7} fill={ink.color} />)}
      {bumps.map((b, i) => <circle key={"f" + i} cx={b.cx} cy={b.cy} r={b.r} fill={color} />)}
    </Canvas>
  );
}
