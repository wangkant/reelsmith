// Air and light made visible inside a photograph: haze by depth, lit motes, light rays, and refraction that bends
// whatever is behind it (heat shimmer, a travelling pressure front, a ripple) instead of drawing rings over it.
import { useId } from "react";
import { random, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { hazeBand } from "./optics";
import { clamp01 } from "./time";

export type HazeProps = {
  /** the band in stage px where the air thickens: clear at y0, thickest at y1, gone again `tail` of the band past y1 */
  y0: number; y1: number;
  tail?: number;
  color?: string;
  /** 0..1 at its thickest */
  amount?: number;
  /** wisps drifting sideways in px per second (0 = an even veil) */
  drift?: number;
  seed?: number;
  f?: number;
};

/** A veil of air thickening toward the distance: put it between plate planes, or over a plate's far part. */
export function Haze({ y0, y1, tail = 0.35, color = "#E6EEF3", amount = 0.35, drift = 6, seed = 3, f: fIn }: HazeProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const id = "hz" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const { top, bot, stops } = hazeBand(y0, y1, tail);
  const dx = drift ? (f / (fps || 30)) * drift : 0;
  const pad = w * 0.3;
  const c = hexRgb(color);
  if (!(amount > 0)) return null;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }}>
      <defs>
        <linearGradient id={id + "g"} gradientUnits="userSpaceOnUse" x1={0} x2={0} y1={top} y2={bot}>
          {stops.map(([o, a], i) => <stop key={i} offset={o.toFixed(4)} stopColor="#fff" stopOpacity={a} />)}
        </linearGradient>
        <mask id={id + "m"} maskUnits="userSpaceOnUse" x={-pad} y={top} width={w + 2 * pad} height={bot - top}>
          <rect x={-pad} y={top} width={w + 2 * pad} height={bot - top} fill={`url(#${id}g)`} />
        </mask>
        <filter id={id + "w"} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency={`${(1.6 / w).toFixed(5)} ${(5 / Math.max(1, bot - top)).toFixed(5)}`} numOctaves={3} seed={seed} />
          <feColorMatrix values={`0 0 0 0 ${c[0]}  0 0 0 0 ${c[1]}  0 0 0 0 ${c[2]}  0 0 0 1.8 -0.6`} />
        </filter>
      </defs>
      <g mask={`url(#${id}m)`} opacity={clamp01(amount)}>
        <rect x={-pad} y={top} width={w + 2 * pad} height={bot - top} fill={color} opacity={drift ? 0.6 : 1} />
        {drift ? (
          <g transform={`translate(${dx - w} 0)`}>
            {/* only the visible stretch: the noise is fixed in user space, so it never wraps or jumps */}
            <rect x={w - pad - dx} y={top} width={w + 2 * pad} height={bot - top} filter={`url(#${id}w)`} />
          </g>
        ) : null}
      </g>
    </svg>
  );
}

const hexRgb = (c: string): [string, string, string] => {
  const m = /^#?([0-9a-f]{6})$/i.exec(c.trim());
  const n = m ? parseInt(m[1], 16) : 0xffffff;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => (v / 255).toFixed(3)) as [string, string, string];
};

export type MotesProps = {
  /** where the motes float [x, y, w, h] in stage px */
  box: [number, number, number, number];
  n?: number;
  /** radius in px, drift [x, y] in px per second, colour */
  size?: number;
  wind?: [number, number];
  color?: string;
  /** 0..1 how bright; `light` is a point they glint near (a sun, a window) */
  opacity?: number;
  light?: [number, number];
  seed?: string;
  f?: number;
};

/** Specks of dust or pollen catching the light: soft round points, not dashes, that drift and glint. */
export function Motes({ box, n = 40, size = 4, wind = [10, -4], color = "#FFF6DF", opacity = 0.7, light, seed = "mt", f: fIn }: MotesProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const id = "mo" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const [bx, by, bw, bh] = box;
  const t = f / (fps || 30);
  const reach = Math.hypot(w, h) * 0.45;
  if (!(n > 0 && opacity > 0 && bw > 0 && bh > 0)) return null;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }}>
      <defs>
        <radialGradient id={id}>
          <stop offset="0" stopColor={color} stopOpacity={1} />
          <stop offset="0.4" stopColor={color} stopOpacity={0.55} />
          <stop offset="1" stopColor={color} stopOpacity={0} />
        </radialGradient>
      </defs>
      {Array.from({ length: n }, (_, i) => {
        const sp = 0.5 + random(`${seed}v${i}`);
        const x = bx + ((((random(`${seed}x${i}`) * bw + wind[0] * sp * t + Math.sin(t * 0.9 + i) * 6) % bw) + bw) % bw);
        const y = by + ((((random(`${seed}y${i}`) * bh + wind[1] * sp * t + Math.cos(t * 0.7 + i * 1.7) * 8) % bh) + bh) % bh);
        const r = size * (0.5 + random(`${seed}r${i}`) * 1.2);
        const near = light ? clamp01(1 - Math.hypot(x - light[0], y - light[1]) / reach) : 0.6;
        const glint = 0.55 + 0.45 * Math.sin(t * (2 + random(`${seed}g${i}`) * 3) + i);
        return <circle key={i} cx={x} cy={y} r={r * 2.2} fill={`url(#${id})`} opacity={opacity * (0.25 + 0.75 * near) * glint} />;
      })}
    </svg>
  );
}

export type RaysProps = {
  /** where the light comes from (may be outside the frame) and the direction it falls, in degrees (90 = down) */
  x: number; y: number;
  ang?: number;
  /** fan width in degrees, number of shafts, length in px */
  spread?: number;
  n?: number;
  len?: number;
  color?: string;
  /** 0..1 */
  strength?: number;
  seed?: string;
  f?: number;
};

/** Shafts of light through air: soft wedges that fade along their length and breathe slowly, added as light. */
export function Rays({ x, y, ang = 115, spread = 34, n = 6, len, color = "#FFE9B8", strength = 0.35, seed = "ry", f: fIn }: RaysProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const id = "ry" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const L = len ?? Math.hypot(w, h) * 1.1;
  const t = f / (fps || 30);
  const rad = (d: number) => (d * Math.PI) / 180;
  if (!(n > 0 && strength > 0)) return null;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none", mixBlendMode: "screen" }}>
      <defs>
        <radialGradient id={id + "g"} gradientUnits="userSpaceOnUse" cx={x} cy={y} r={L}>
          <stop offset="0" stopColor={color} stopOpacity={1} />
          <stop offset="0.45" stopColor={color} stopOpacity={0.45} />
          <stop offset="1" stopColor={color} stopOpacity={0} />
        </radialGradient>
        <filter id={id + "b"} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={L * 0.012} /></filter>
      </defs>
      <g filter={`url(#${id}b)`}>
        {Array.from({ length: n }, (_, i) => {
          const a = ang - spread / 2 + (spread * (i + random(`${seed}a${i}`) * 0.8)) / n;
          const wd = (spread / n) * (0.25 + random(`${seed}w${i}`) * 0.5);
          const o = strength * (0.4 + 0.6 * random(`${seed}o${i}`)) * (0.75 + 0.25 * Math.sin(t * (0.5 + random(`${seed}s${i}`)) + i * 2.1));
          const p1 = [x + Math.cos(rad(a - wd / 2)) * L, y + Math.sin(rad(a - wd / 2)) * L];
          const p2 = [x + Math.cos(rad(a + wd / 2)) * L, y + Math.sin(rad(a + wd / 2)) * L];
          return <path key={i} d={`M${x} ${y} L${p1[0]} ${p1[1]} L${p2[0]} ${p2[1]} Z`} fill={`url(#${id}g)`} opacity={o} />;
        })}
      </g>
    </svg>
  );
}
