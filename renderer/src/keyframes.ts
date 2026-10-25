// Keyframe interpolation and the enter/exit presets. Pure functions of the frame, so stills match the film.
import { Easing, spring } from "remotion";
import type { CutIn, CutOut, Ease, Keyframe, Transition } from "./types";

const clamp01 = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t);

const CURVES: Record<Exclude<Ease, "spring" | "step">, (t: number) => number> = {
  linear: (t) => t,
  in: Easing.in(Easing.cubic),
  out: Easing.out(Easing.cubic),
  inOut: Easing.inOut(Easing.cubic),
};

// A little overshoot so "spring" reads as one; settles by the segment's end.
const SPRING = { damping: 12, stiffness: 140, mass: 0.9 };

/** Progress 0..1 (spring may overshoot) of a segment `len` frames long, `t` frames in. */
export const easeAt = (ease: Ease | null | undefined, t: number, len: number, fps: number): number => {
  if (len <= 0) return 1;
  if (ease === "step") return t >= len ? 1 : 0;
  if (ease === "spring") return t <= 0 ? 0 : t >= len ? 1 : spring({ frame: t, fps, config: SPRING, durationInFrames: len });
  const curve = CURVES[(ease ?? "linear") as keyof typeof CURVES] ?? CURVES.linear;
  return curve(clamp01(t / len));
};

const sorted = new WeakMap<Keyframe[], Keyframe[]>();
const ordered = (frames: Keyframe[]): Keyframe[] => {
  let s = sorted.get(frames);
  if (!s) {
    s = frames.filter((k) => k && Number.isFinite(k.f) && Number.isFinite(k.v)).slice().sort((a, b) => a.f - b.f);
    sorted.set(frames, s);
  }
  return s;
};

/** The keyframed value at frame `f` (frames from the clip start). Holds the first value before the first key and
 *  the last after the last; the segment k-1 -> k is shaped by keyframe k's ease (default linear). */
export const valueAt = (frames: Keyframe[], f: number, fps: number): number => {
  const k = ordered(frames);
  if (k.length === 0) return NaN;
  if (f <= k[0].f) return k[0].v;
  const last = k[k.length - 1];
  if (f >= last.f) return last.v;
  let i = 1;
  while (i < k.length && k[i].f <= f) i++;
  const a = k[i - 1];
  const b = k[i];
  return a.v + (b.v - a.v) * easeAt(b.ease, f - a.f, b.f - a.f, fps);
};

/** `fallback` unless the prop has keyframes. */
export const sample = (frames: Keyframe[] | null | undefined, f: number, fps: number, fallback: number): number => {
  if (!frames || frames.length === 0) return fallback;
  const v = valueAt(frames, f, fps);
  return Number.isFinite(v) ? v : fallback;
};

export type TransitionState = { opacity: number; tx: number; ty: number; scale: number; clip: string | null };

const NONE: TransitionState = { opacity: 1, tx: 0, ty: 0, scale: 1, clip: null };

/** One preset at amount `p` (1 = settled, 0 = fully gone). `entering` picks the direction it leaves in. */
const presetAt = (preset: string, p: number, entering: boolean, travel: number, raw: number, fps: number, len: number) => {
  const gone = 1 - p;
  switch (preset) {
    case "fade":
      return { ...NONE, opacity: p };
    case "rise": // moves up: in from below, out above
      return { ...NONE, opacity: p, ty: (entering ? 1 : -1) * gone * travel };
    case "drop": // moves down: in from above, out below
      return { ...NONE, opacity: p, ty: (entering ? -1 : 1) * gone * travel };
    case "pop": {
      const s = entering ? spring({ frame: raw, fps, config: { damping: 11, stiffness: 220, mass: 0.7 }, durationInFrames: len }) : p;
      return { ...NONE, opacity: Math.min(1, p * 1.6), scale: 0.6 + 0.4 * s };
    }
    case "zoom": // from larger in, to larger out
      return { ...NONE, opacity: p, scale: 1 + 0.25 * gone };
    case "wipe_left": // the edge travels leftward both ways
      return { ...NONE, clip: entering ? `inset(0 0 0 ${gone * 100}%)` : `inset(0 ${gone * 100}% 0 0)` };
    case "wipe_up": // the edge travels upward both ways
      return { ...NONE, clip: entering ? `inset(${gone * 100}% 0 0 0)` : `inset(0 0 ${gone * 100}% 0)` };
    default:
      return NONE;
  }
};

/** Enter/exit state at frame `f` of a clip `dur` frames long. Presets that overlap are squeezed to fit. */
export const transitionAt = (
  enter: Transition | null | undefined, exit: Transition | null | undefined, f: number, dur: number, fps: number, h: number,
): TransitionState => {
  let ein = enter && enter.dur > 0 ? enter.dur : 0;
  let eout = exit && exit.dur > 0 ? exit.dur : 0;
  if (ein + eout > dur && ein + eout > 0) {
    const k = dur / (ein + eout);
    ein *= k;
    eout *= k;
  }
  const travel = Math.min(60, Math.max(20, h * 0.5));
  let st = NONE;
  if (enter && ein > 0 && f < ein) {
    const p = Easing.out(Easing.cubic)(clamp01(f / ein));
    st = presetAt(enter.preset, p, true, travel, f, fps, Math.max(1, Math.round(ein)));
  }
  const last = dur - 1;
  if (exit && eout > 0 && f > last - eout) {
    const q = 1 - Easing.in(Easing.cubic)(clamp01((f - (last - eout)) / eout));
    const out = presetAt(exit.preset, q, false, travel, f, fps, Math.max(1, Math.round(eout)));
    st = {
      opacity: st.opacity * out.opacity, tx: st.tx + out.tx, ty: st.ty + out.ty, scale: st.scale * out.scale,
      clip: out.clip ?? st.clip,
    };
  }
  return st;
};

export type CutState = TransitionState & { content: number; veil: string | null; veilOpacity: number };

const sweep = Easing.inOut(Easing.cubic);

/** A clip's look at frame `f` from the transitions it takes part in: in from the clip before it over its first
 *  `cin.dur` frames (painted over that clip), out to the clip after it from `cout.at`. `w` is the box width. */
export const cutAt = (cin: CutIn | null | undefined, cout: CutOut | null | undefined, f: number, w: number): CutState => {
  const st: CutState = { ...NONE, content: 1, veil: null, veilOpacity: 0 };
  if (cin && cin.dur > 0 && f < cin.dur) {
    const p = clamp01(f / cin.dur);
    const e = sweep(p);
    switch (cin.type) {
      case "crossfade":
        st.opacity = p;
        break;
      case "dip_black":
      case "dip_white": // the colour rises over the clip before, then falls off this one
        st.veil = cin.type === "dip_black" ? "#000000" : "#FFFFFF";
        st.content = p < 0.5 ? 0 : 1;
        st.veilOpacity = p < 0.5 ? 2 * p : 2 * (1 - p);
        break;
      case "wipe_left": // the edge travels leftward: this clip appears from the right
        st.clip = `inset(0 0 0 ${(1 - e) * 100}%)`;
        break;
      case "wipe_right":
        st.clip = `inset(0 ${(1 - e) * 100}% 0 0)`;
        break;
      case "wipe_up":
        st.clip = `inset(${(1 - e) * 100}% 0 0 0)`;
        break;
      case "slide_left": // pushes in from the right
        st.tx = (1 - e) * w;
        break;
      case "zoom":
        st.opacity = p;
        st.scale = 1.2 - 0.2 * e;
        break;
    }
  }
  if (cout && cout.dur > 0 && f >= cout.at) {
    const p = clamp01((f - cout.at) / cout.dur);
    const e = sweep(p);
    switch (cout.type) {
      case "dip_black":
      case "dip_white":
        st.veil = cout.type === "dip_black" ? "#000000" : "#FFFFFF";
        st.veilOpacity = Math.max(st.veilOpacity, Math.min(1, 2 * p));
        break;
      case "slide_left": // pushed out to the left
        st.tx -= e * w;
        break;
      case "zoom":
        st.scale *= 1 + 0.2 * e;
        break;
    }
  }
  return st;
};
