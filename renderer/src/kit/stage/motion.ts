// Physical motion: pure functions of the frame for falls, swings, lag, shakes, idling and camera stations.
import { random } from "remotion";
import type { Key } from "./Stage";
import { clamp01, swing } from "./time";

export type Drop = {
  /** the y to draw at (from `from` to `to`) */
  y: number;
  /** squash scales around the contact point: wider and flatter on landing, then back to 1 */
  sx: number;
  sy: number;
  /** 0 before the fall, 0..1 falling, 1 once landed */
  t: number;
  landed: boolean;
};

export type DropOptions = {
  /** frames the fall takes (default from the height: about a real fall at 1 m = 900 px) */
  dur?: number;
  /** how flat the landing squashes, 0..0.6 */
  squash?: number;
  /** settling wobble frequency in Hz and its decay */
  hz?: number;
  decay?: number;
  fps?: number;
};

/** A thing let go at frame `at` above `to`: it accelerates down (y ~ t^2), squashes on landing and settles. */
export const drop = (f: number, at: number, from: number, to: number, o: DropOptions = {}): Drop => {
  const fps = o.fps ?? 30;
  const dist = Math.abs(to - from);
  const dur = Math.max(1, o.dur ?? Math.round(fps * Math.max(0.18, Math.sqrt(dist / 900) * 0.45)));
  const squash = Math.max(0, Math.min(0.6, o.squash ?? 0.22));
  if (f < at) return { y: from, sx: 1, sy: 1, t: 0, landed: false };
  const t = clamp01((f - at) / dur);
  if (t < 1) {
    const y = from + (to - from) * t * t;
    const st = 1 + 0.08 * t * t; // stretch along the fall
    return { y, sx: 1 / Math.sqrt(st), sy: st, t, landed: false };
  }
  const s = (f - at - dur) / fps;
  const k = squash * Math.exp(-(o.decay ?? 5) * s) * Math.cos(2 * Math.PI * (o.hz ?? 2.4) * s);
  return { y: to, sx: 1 + k, sy: 1 - k, t: 1, landed: true };
};

/** A damped swing in degrees kicked at `at` that keeps a faint idle sway (`idle` degrees) instead of stopping dead. */
export const pendulum = (f: number, at: number, amp = 24, hz = 1.1, decay = 1.6, idle = 1.2, fps = 30): number =>
  swing(f, at, amp, hz, decay, fps) + idle * Math.sin((2 * Math.PI * f) / (fps * 2.7) + at * 0.37);

/** A value that trails `leader` (a function of the frame) by about `lag` frames, smoothed: tails, followers, cargo. */
export const follow = (f: number, leader: (frame: number) => number, lag = 6, n = 6): number => {
  let sum = 0, wsum = 0;
  for (let i = 0; i < n; i++) {
    const w = Math.exp(-i / Math.max(1, n / 2));
    sum += w * leader(f - lag * (0.4 + (1.2 * i) / Math.max(1, n - 1)));
    wsum += w;
  }
  return sum / wsum;
};

const noise = (seed: string, x: number): number => {
  const i = Math.floor(x), t = x - i;
  const a = random(`${seed}${i}`) * 2 - 1, b = random(`${seed}${i + 1}`) * 2 - 1;
  const s = t * t * (3 - 2 * t);
  return a + (b - a) * s;
};

/** A shake [dx, dy] in px from frame `at`, fading out over `dur` frames: an impact, a rumble, an engine. */
export const shake = (seed: string, f: number, at: number, amp = 10, dur = 18, hz = 14, fps = 30): [number, number] => {
  if (f < at || f > at + dur) return [0, 0];
  const k = amp * (1 - (f - at) / Math.max(1, dur)) ** 2;
  const x = ((f - at) * hz) / fps;
  return [noise(seed + "x", x) * k, noise(seed + "y", x) * k];
};

/** An idle scale around 1 (1 + amp at most), one breath every `period` seconds; `phase` 0..1 desyncs neighbours. */
export const breathe = (f: number, amp = 0.015, period = 3.2, phase = 0, fps = 30): number =>
  1 + amp * Math.sin(2 * Math.PI * (f / (fps * period) + phase));

export type Stop = {
  /** frame the camera should have arrived (usually a cue: T("word") - 4) */
  at: number;
  /** stage point at the frame centre, and zoom (default 1) */
  x: number; y: number; z?: number;
};

export type StationOptions = {
  /** frames each travel takes, ending at the stop's `at` (shortened when stops are close) */
  travel?: number;
  /** zoom-out mid-travel, 0..0.4 */
  dip?: number;
  /** slow push-in while holding at a stop, as a zoom fraction (0 = a locked-off camera) */
  push?: number;
  /** keep pushing in on the last stop until this frame (usually the clip's last frame) */
  until?: number;
};

/** Camera keys for <Stage cam>: hold at each stop with a slow push, travel to the next with an eased move that
 *  dips its zoom, and arrive at the stop's `at`. */
export const stations = (stops: Stop[], o: StationOptions = {}): Key[] => {
  const travel = Math.max(1, o.travel ?? 22), dip = Math.max(0, Math.min(0.4, o.dip ?? 0.1)), push = o.push ?? 0.04;
  const list = [...stops].sort((a, b) => a.at - b.at);
  const keys: Key[] = [];
  list.forEach((s, i) => {
    const z = s.z ?? 1;
    if (i > 0) {
      const p = list[i - 1], pz = (p.z ?? 1);
      const leave = Math.max(p.at + 1, s.at - travel);
      const held = pz * (1 + push * clamp01((leave - p.at) / 90));
      if (leave > p.at) keys.push({ at: leave, x: p.x, y: p.y, z: held });
      keys.push({ at: s.at, x: s.x, y: s.y, z, dip });
    } else keys.push({ at: s.at, x: s.x, y: s.y, z });
  });
  const last = list[list.length - 1];
  if (last && o.until !== undefined && o.until > last.at)
    keys.push({ at: o.until, x: last.x, y: last.y, z: (last.z ?? 1) * (1 + push * clamp01((o.until - last.at) / 90)) });
  return keys;
};
