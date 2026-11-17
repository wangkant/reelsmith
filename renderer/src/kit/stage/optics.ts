// Photograph components, the pure part: plate fit, depth of field, travel along a traced line, shade ramps, a
// camera's handheld drift and the progress of a scene join. Functions of the frame only.
import { random } from "remotion";
import type { Pt } from "./geom";
import type { Cam } from "./Stage";
import { clamp01, in2, inOut, lerp, out3 } from "./time";

export type Fit = {
  /** scale from picture px to stage px, and where the picture's top-left lands */
  s: number; x: number; y: number;
  /** drawn size in stage px */
  w: number; h: number;
  /** a picture px point (traced on AssetGrid) in stage px */
  at: (pt: Pt) => Pt;
};

/** A picture of imgW x imgH covering a w x h frame with `pad` (a fraction) to spare on every side, centred;
 *  `focus` [0..1, 0..1] picks which part of the picture stays in frame when the aspect differs. */
export const coverFit = (imgW: number, imgH: number, w: number, h: number, pad = 0.06, focus: Pt = [0.5, 0.5]): Fit => {
  const s = Math.max((w * (1 + 2 * pad)) / imgW, (h * (1 + 2 * pad)) / imgH);
  const dw = imgW * s, dh = imgH * s;
  const x = (w - dw) * clamp01(focus[0]), y = (h - dh) * clamp01(focus[1]);
  return { s, x, y, w: dw, h: dh, at: ([px, py]) => [x + px * s, y + py * s] };
};

/** Blur in px for a plane at `depth` when the lens focuses at `focus`: the circle of confusion grows with the
 *  difference of parallax depths (parallax ~ 1 / distance). `aperture` is px per unit of depth; capped at `max`. */
export const dofBlur = (depth: number, focus = 1, aperture = 10, max = 40): number =>
  Math.min(max, Math.max(0, aperture * Math.abs(depth - focus)));

export type Ease = "linear" | "in" | "out" | "inOut" | ((t: number) => number);
const easeOf = (e: Ease): ((t: number) => number) =>
  typeof e === "function" ? e : e === "in" ? in2 : e === "out" ? out3 : e === "inOut" ? inOut : clamp01;

const lengths = (line: Pt[]): number[] => {
  const acc = [0];
  for (let i = 1; i < line.length; i++) acc.push(acc[i - 1] + Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1]));
  return acc;
};

/** The point, and the direction in degrees, at fraction `t` of a polyline's length. */
export const pointAt = (line: Pt[], t: number): { x: number; y: number; ang: number } => {
  if (line.length === 0) return { x: 0, y: 0, ang: 0 };
  if (line.length === 1) return { x: line[0][0], y: line[0][1], ang: 0 };
  const acc = lengths(line), total = acc[acc.length - 1] || 1;
  const d = clamp01(t) * total;
  let i = 1;
  while (i < line.length - 1 && acc[i] < d) i++;
  const a = line[i - 1], b = line[i], seg = acc[i] - acc[i - 1] || 1;
  const k = (d - acc[i - 1]) / seg;
  return { x: a[0] + (b[0] - a[0]) * k, y: a[1] + (b[1] - a[1]) * k, ang: (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI };
};

export type TravelOptions = {
  /** scale at the start and at the end of the line (perspective: smaller far away) */
  sizes?: [number, number];
  ease?: Ease;
};

export type TravelState = {
  x: number; y: number;
  /** direction of travel in degrees */
  ang: number;
  /** 0 before `at`, 1 once arrived */
  t: number;
  /** scale for this point of the line */
  s: number;
  /** speed in stage px per frame, measured over the last frame */
  speed: number;
};

/** A thing moving along `line` from frame `at` for `dur` frames, eased, scaled by perspective. Before `at` it
 *  waits at the start, after it holds at the end. */
export const travelAt = (line: Pt[], f: number, at: number, dur: number, o: TravelOptions = {}): TravelState => {
  const e = easeOf(o.ease ?? "inOut");
  const [s0, s1] = o.sizes ?? [1, 1];
  const tAt = (fr: number) => (dur <= 0 ? (fr >= at ? 1 : 0) : clamp01((fr - at) / dur));
  const t = tAt(f), k = e(t);
  const p = pointAt(line, k), q = pointAt(line, e(tAt(f - 1)));
  return { x: p.x, y: p.y, ang: p.ang, t, s: lerp(s0, s1, k), speed: Math.hypot(p.x - q.x, p.y - q.y) };
};

/** Distance covered by frame f at `speed(frame)` px per frame from frame 0 (scenery past a window). */
export const distanceAt = (f: number, speed: (frame: number) => number): number => {
  let d = 0;
  for (let i = 0; i < Math.floor(f); i++) d += speed(i);
  return d + (f - Math.floor(f)) * speed(Math.floor(f));
};

/** A shade function for `Travel` and `Photo`: 0 at `from`, rising to `max` at `to` (projected onto that
 *  direction), held beyond: the walk into the shadow of a wall or a doorway. */
export const shadeRamp = (from: Pt, to: Pt, max = 0.6): ((x: number, y: number) => number) => {
  const dx = to[0] - from[0], dy = to[1] - from[1], l2 = dx * dx + dy * dy || 1;
  return (x, y) => max * clamp01(((x - from[0]) * dx + (y - from[1]) * dy) / l2);
};

const smoothNoise = (seed: string, x: number): number => {
  const i = Math.floor(x), t = x - i;
  const a = random(`${seed}${i}`) * 2 - 1, b = random(`${seed}${i + 1}`) * 2 - 1;
  return a + (b - a) * t * t * (3 - 2 * t);
};

/** A hand-held camera's slow drift: [dx, dy] in px and a roll in degrees, from layered smooth noise. */
export const handheld = (f: number, amp = 6, seed = "hand", fps = 30): [number, number, number] => {
  const x = f / fps;
  const n = (s: string) => 0.7 * smoothNoise(seed + s, x * 0.45) + 0.3 * smoothNoise(seed + s + "f", x * 1.3);
  return [n("x") * amp, n("y") * amp * 0.8, n("r") * amp * 0.035];
};

/** Progress of a join that starts at `at` and lasts `len` frames: 0 before, 1 after, eased in between. */
export const joinAt = (f: number, at: number, len: number): number => inOut(len <= 0 ? (f >= at ? 1 : 0) : (f - at) / len);

/** Where a stage point of a layer at `depth` lands in the frame under camera `cam`, and that layer's scale there. */
export const onScreen = (cam: Cam, depth: number, w: number, h: number, pt: Pt): { x: number; y: number; s: number } => {
  const tx = w / 2 + (cam.x - w / 2) * depth, ty = h / 2 + (cam.y - h / 2) * depth;
  const s = Math.pow(Math.max(1e-3, cam.z), 0.5 + 0.5 * depth);
  return { x: w / 2 + s * (pt[0] - tx), y: h / 2 + s * (pt[1] - ty), s };
};

/** The camera x, y that puts a stage point of a layer at `depth` in the frame centre (for camera keys). */
export const lookAt = (pt: Pt, depth: number, w: number, h: number): { x: number; y: number } => ({
  x: w / 2 + (pt[0] - w / 2) / Math.max(1e-3, depth), y: h / 2 + (pt[1] - h / 2) / Math.max(1e-3, depth),
});

/** A haze band's extent and gradient stops (offset 0..1 within [top, bot], opacity), in ascending order whichever
 *  way the band runs: clear at y0, thickest at y1, clear again `tail` of the band beyond y1. */
export const hazeBand = (y0: number, y1: number, tail = 0.35): { top: number; bot: number; stops: [number, number][] } => {
  const y2 = y1 + (y1 - y0) * Math.max(0.05, tail);
  const top = Math.min(y0, y2), bot = Math.max(y0, y2), span = Math.max(1, bot - top);
  const stops: [number, number][] = [[y0, 0], [y1, 1], [y2, 0]].map(([y, o]) => [clamp01((y - top) / span), o] as [number, number]);
  return { top, bot, stops: stops.sort((a, b) => a[0] - b[0]) };
};

/** A swaying strip's skew in degrees at frame f: a slow sway of `amp` at `hz` plus a gust that decays over a second. */
export const swayAngle = (f: number, fps: number, amp = 1.2, hz = 0.35, gust?: number, gustAmp = 3): number => {
  const sec = f / (fps || 30);
  const g = gust !== undefined && f >= gust ? gustAmp * Math.exp(-((f - gust) / (fps || 30)) * 1.6) * Math.sin(((f - gust) / (fps || 30)) * 7) : 0;
  return amp * (0.7 * Math.sin(sec * 2 * Math.PI * hz) + 0.3 * Math.sin(sec * 5.3 + 1)) + g;
};

/** When a clip plays in the world: from frame `at`, at speed `rate`, starting `from` seconds in, for `len` seconds
 *  (default to its end), looping or holding its first frame before and its last after (`hold` true = both). */
export type FilmTiming = { at?: number; rate?: number; from?: number; len?: number; loop?: boolean; hold?: boolean | "before" | "after" };

/** The clip's frame (in frames of the clip fps from its start) shown at frame f, or null for none, and whether it is
 *  before, playing or after. `duration` is the clip's length in seconds when known. */
export const filmFrame = (t: FilmTiming, f: number, fps: number, duration?: number | null): { state: "before" | "play" | "after"; frame: number | null } => {
  const at = t.at ?? 0, rate = t.rate && t.rate > 0 ? t.rate : 1, hold = t.hold ?? true;
  const start = Math.max(0, Math.round((t.from ?? 0) * fps));
  const last = duration && duration > 0 ? Math.max(0, Math.floor(duration * fps + 1e-6) - 1) : Infinity;
  const end = Math.max(start, Math.min(last, t.len && t.len > 0 ? start + Math.round(t.len * fps) - 1 : Infinity));
  if (t.loop && !Number.isFinite(end)) {
    throw new Error("film loop: the clip's length is unknown; pass `len` (seconds) or the clip as an asset ref (an `*_asset` prop)");
  }
  const dt = f - at;
  if (dt < 0) return { state: "before", frame: hold === true || hold === "before" ? start : null };
  const run = Math.floor(dt * rate + 1e-6);
  if (t.loop) return { state: "play", frame: start + (run % (end - start + 1)) };
  if (start + run <= end) return { state: "play", frame: start + run };
  return { state: "after", frame: hold === true || hold === "after" ? end : null };
};

/** Whether a film's frame is drawn rather than its still: not when it shows none, and before its start only when it
 *  starts past the clip's first frame (which is the still). Footage and Plate share this rule. */
export const showsFilm = (t: FilmTiming, ff: { state: "before" | "play" | "after"; frame: number | null }): boolean =>
  ff.frame !== null && !(ff.state === "before" && !t.from);

/** Where a placed picture's silhouette stands in stage px: `pts` are opaque outline points as picture fractions,
 *  placed like Photo (anchor at x, y; box offset ox, oy; drawn dw x dh; rotated r degrees; mirrored by flip).
 *  `foot` is its lowest stage y, `top` its highest, `w` its width and `cx` the middle of its lowest quarter. */
export const silhouette = (pts: Pt[], x: number, y: number, ox: number, oy: number, dw: number, dh: number, r = 0, flip = false) => {
  const rad = (r * Math.PI) / 180, c = Math.cos(rad), sn = Math.sin(rad), fx = flip ? -1 : 1;
  const st = pts.map(([u, v]) => {
    const lx = fx * (ox + u * dw), ly = oy + v * dh;
    return [x + lx * c - ly * sn, y + lx * sn + ly * c] as Pt;
  });
  const ys = st.map((q) => q[1]), xs = st.map((q) => q[0]);
  const foot = Math.max(...ys), top = Math.min(...ys), left = Math.min(...xs);
  const low = st.filter((q) => q[1] >= foot - 0.28 * Math.max(1, foot - top)).map((q) => q[0]);
  return { foot, top, left, w: Math.max(1, Math.max(...xs) - left), cx: (Math.min(...low) + Math.max(...low)) / 2 };
};

/** A second camera on the same plate: from frame `at` (until `end`, if given) it frames picture point `to` (picture
 *  px) `z` times closer, as a cut; `focus` and `aperture` set the lens for that shot. */
export type Punch = { at: number; end?: number; to: Pt; z?: number; focus?: number; aperture?: number };

/** The punch in force at frame f (a later one wins), or null. */
export const punchAt = (punches: Punch[] | undefined, f: number): Punch | null => {
  let on: Punch | null = null;
  for (const p of punches ?? []) if (f >= p.at && (p.end === undefined || f < p.end)) on = p;
  return on;
};

/** A reframing: stage point (cx, cy) of the layer lands in the frame centre, z times larger. */
export type View = { z: number; cx: number; cy: number };

/** The view of a punch on a plate fitted by `fit` in a w x h frame, its crop kept inside the picture. */
export const punchView = (p: Punch, fit: Fit, w: number, h: number): View => {
  const z = Math.max(1, p.z ?? 1.5);
  const [px, py] = fit.at(p.to);
  const keep = (v: number, a: number, len: number, half: number) => (len <= 2 * half ? a + len / 2 : Math.max(a + half, Math.min(a + len - half, v)));
  return { z, cx: keep(px, fit.x, fit.w, w / (2 * z)), cy: keep(py, fit.y, fit.h, h / (2 * z)) };
};

/** Where a stage point lands after a view (unchanged without one). */
export const viewed = (v: View | null, w: number, h: number, pt: Pt): Pt =>
  v ? [w / 2 + (pt[0] - v.cx) * v.z, h / 2 + (pt[1] - v.cy) * v.z] : pt;

/** The direction light comes from on screen: a name, or degrees (0 = from the right, 90 = from the back of the
 *  scene, so shadows fall toward the camera); `height` 0..1 is its elevation (1 = overhead, short shadows). */
export type Light = { from?: "left" | "right" | "upper-left" | "upper-right" | "back" | "front" | "lower-left" | "lower-right" | number; height?: number };

const FROM = { right: 0, "upper-right": 45, back: 90, "upper-left": 135, left: 180, "lower-left": 225, front: 270, "lower-right": 315 };

/** The SVG matrix that lays a standing silhouette on the ground line y = `ground` as its cast shadow, and the
 *  shadow's length per px of height. Depth on the ground is foreshortened, so a shadow toward the camera is short. */
export const castMatrix = (light: Light, ground: number): { m: [number, number, number, number, number, number]; len: number } => {
  const from = light.from ?? "upper-left";
  const rad = ((typeof from === "number" ? from : FROM[from] ?? 135) * Math.PI) / 180;
  const ax = -Math.cos(rad), ay = Math.sin(rad) * 0.4;
  const elev = (Math.max(0.08, Math.min(0.95, light.height ?? 0.5)) * Math.PI) / 2;
  const L = Math.min(3, 1 / Math.tan(elev));
  const c = -L * ax;
  let d = -L * ay;
  // a shadow lying exactly sideways would be a line: the ground under a thing has some depth
  if (Math.abs(d) < 0.12) d = d > 0 ? 0.12 : -0.12;
  return { m: [1, 0, c, d, -c * ground, ground * (1 - d)], len: Math.hypot(L * ax, L * ay) };
};
