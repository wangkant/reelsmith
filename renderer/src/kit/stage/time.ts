// Stage timing: narration cues, easing, springs and the stop-motion clock. Every time here is in frames.
import { random } from "remotion";
import { springAt } from "../helpers";
import type { SpringOptions } from "../helpers";
import { useClip } from "../context";
import type { ClipLine } from "../context";

/** One narration line as a clip sees it (useClip().lines): frames relative to the clip's start. */
export type CueLine = ClipLine;

export type Cues = {
  /** frame where `word` is said (the `nth` occurrence, 0-based, across the clip's lines), plus `off` seconds */
  T: (word: string, off?: number, nth?: number) => number;
  /** first frame of line `i` (the line's own index); without `i`, of the clip's first line */
  at: (i?: number) => number;
  /** last frame of line `i`; without `i`, of the clip's last line */
  end: (i?: number) => number;
  /** seconds to frames */
  S: (sec: number) => number;
  lines: CueLine[];
  fps: number;
};

const describe = (lines: CueLine[]) =>
  lines.length ? lines.map((l) => `${l.i}: ${l.text}`).join(" | ") : "no narration lines reach this clip";

/** Cue lookups over plain line data. A word's frame is placed by character position inside its line (every
 *  character, punctuation included, takes an equal share of the line's time). Missing words and lines throw. */
export const cues = (lines: CueLine[], fps = 30): Cues => {
  const list = Array.isArray(lines) ? lines : [];
  const S = (sec: number) => Math.round(sec * fps);
  const T = (word: string, off = 0, nth = 0): number => {
    if (!word) throw new Error("cue: empty word");
    let seen = 0;
    for (const l of list) {
      const chars = Array.from(l.text);
      const n = chars.length || 1;
      let from = 0;
      for (;;) {
        const at = l.text.indexOf(word, from);
        if (at < 0) break;
        if (seen === nth) {
          const idx = Array.from(l.text.slice(0, at)).length;
          return Math.round(l.from + ((l.to - l.from) * idx) / n + off * fps);
        }
        seen++;
        from = at + word.length;
      }
    }
    throw new Error(`cue: "${word}"${nth ? ` (occurrence ${nth})` : ""} is not in the narration (${describe(list)})`);
  };
  const line = (i: number | undefined, last: boolean): CueLine => {
    if (!list.length) throw new Error("cue: no narration lines reach this clip");
    if (i === undefined) return last ? list[list.length - 1] : list[0];
    const hit = list.find((l) => l.i === i);
    if (!hit) throw new Error(`cue: line ${i} is not under this clip (${describe(list)})`);
    return hit;
  };
  return {
    T, S, lines: list, fps,
    at: (i?: number) => Math.round(line(i, false).from),
    end: (i?: number) => Math.round(line(i, true).to),
  };
};

/** The clip's narration cues. */
export const useCues = (): Cues => {
  const clip = useClip();
  return cues(clip.lines, clip.fps);
};

export const clamp01 = (x: number): number => (x < 0 ? 0 : x > 1 ? 1 : x);
/** 0..1 over `len` frames from `a`; a step at `a` when len <= 0. */
export const prog = (f: number, a: number, len: number): number => (len <= 0 ? (f >= a ? 1 : 0) : clamp01((f - a) / len));
export const out3 = (t: number): number => 1 - Math.pow(1 - clamp01(t), 3);
export const in2 = (t: number): number => clamp01(t) * clamp01(t);
export const inOut = (t: number): number => {
  const x = clamp01(t);
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
};
/** Ease-out that overshoots and settles. */
export const backOut = (t: number, s = 1.9): number => {
  const x = clamp01(t) - 1;
  return 1 + (s + 1) * x * x * x + s * x * x;
};
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** Decaying sine kicked at frame `at`: a hit, a nod, a wobble. */
export const wob = (f: number, at: number, amp: number, hz = 1.6, decay = 2.2, fps = 30): number => {
  if (f <= at) return 0;
  const t = (f - at) / fps;
  return amp * Math.exp(-decay * t) * Math.sin(2 * Math.PI * hz * t);
};

/** 0 -> 1 spring from frame `at`, a little bouncy by default (the kit's springAt underneath). */
export const spr = (f: number, at: number, cfg: SpringOptions = {}): number =>
  springAt(f, at, { damping: 11, stiffness: 170, mass: 0.9, ...cfg });

/** The frame held by a stop-motion clock at `rate` poses a second (paper and photos move at 12). */
export const step = (f: number, rate = 12, fps = 30): number => {
  const hold = fps / Math.max(1e-6, rate);
  return Math.floor(f / hold + 1e-9) * hold;
};

/** Damped swing in degrees for things hung on a string; `amp` before `at`. */
export const swing = (f: number, at: number, amp = 28, hz = 1.3, decay = 2.2, fps = 30): number => {
  if (f < at) return amp;
  const t = (f - at) / fps;
  return amp * Math.exp(-decay * t) * Math.cos(2 * Math.PI * hz * t);
};

/** Hand-made jitter [dx, dy] that changes 12 times a second. */
export const boil = (seed: string, f: number, amp = 1, fps = 30): [number, number] => {
  const k = Math.floor((f * 12) / fps);
  return [(random(`${seed}x${k}`) - 0.5) * 2 * amp, (random(`${seed}y${k}`) - 0.5) * 2 * amp];
};

/** Life envelope: 0 before `a`, up to 1 over `inLen`, 1 until `b - outLen`, down to 0 at `b`. */
export const win = (f: number, a: number, b: number, inLen = 6, outLen = 6): number => {
  if (f < a || f > b) return 0;
  const up = inLen > 0 ? clamp01((f - a) / inLen) : 1;
  const down = outLen > 0 ? clamp01((b - f) / outLen) : 1;
  return Math.min(up, down);
};
