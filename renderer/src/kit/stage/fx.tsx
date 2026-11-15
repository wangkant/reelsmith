// Small effects: a mist puff, rising wisps, drips and a burst of sparks. Ages and lives are in frames.
import React from "react";
import { random, useCurrentFrame } from "remotion";
import { clamp01 } from "./time";
import { smooth } from "./geom";
import type { Pt } from "./geom";
import { useFilters, usePalette, useUnit } from "./palette";

const Canvas = ({ children }: { children: React.ReactNode }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>{children}</svg>
);

export type MistProps = {
  /** the nozzle on the canvas */
  x: number; y: number;
  /** frames since the puff left (draws for 0 < age < life) */
  age: number;
  /** direction it travels, degrees (180 = to the left) */
  dir?: number;
  color?: string;
  n?: number; life?: number; speed?: number;
  seed?: string;
};

/** A puff of fine spray leaving a nozzle, spreading, slowing and settling. */
export function Mist({ x, y, age, dir = 180, color = "#FFF8EC", n = 46, life = 34, speed = 1, seed = "mist" }: MistProps) {
  const u = useUnit();
  const { soft, defs } = useFilters(2.5 * u);
  if (age <= 0 || age >= life) return null;
  const k = age / life;
  const base = (dir * Math.PI) / 180;
  return (
    <Canvas>
      {defs}
      <g filter={soft}>
        {Array.from({ length: n }, (_, i) => {
          const a = base + (random(`${seed}a${i}`) - 0.5) * 0.8;
          const sp = (9 + random(`${seed}s${i}`) * 14) * u * speed;
          const d = sp * age * (1 - age / (life * 2));
          const cx = x + Math.cos(a) * d, cy = y + Math.sin(a) * d * 0.6 + 1.2 * u * age;
          return <circle key={i} cx={cx} cy={cy} r={(5 + age * 0.7 * random(`${seed}r${i}`)) * u} fill={color} opacity={(1 - k) * 0.6} />;
        })}
      </g>
    </Canvas>
  );
}

export type WispsProps = {
  x: number; y: number;
  /** 0..1 how far they have risen */
  k: number;
  n?: number; spread?: number; color?: string;
  f?: number;
};

/** Curls of smell or steam drawn rising from a point, swaying as they go. */
export function Wisps({ x, y, k, n = 3, spread, color = "#F6EEE2", f: fIn }: WispsProps) {
  const now = useCurrentFrame();
  const u = useUnit();
  const { soft, defs } = useFilters(3 * u);
  if (k <= 0) return null;
  const f = fIn ?? now;
  const gap = spread ?? 90 * u;
  return (
    <Canvas>
      {defs}
      {Array.from({ length: n }, (_, i) => {
        const ox = x + (i - (n - 1) / 2) * gap;
        const ph = f / 14 + i * 1.7;
        const pts: Pt[] = Array.from({ length: 6 }, (_, j) => [ox + Math.sin(ph + j * 0.9) * (18 + j * 6) * u, y - j * 46 * u * k]);
        return (
          <path key={i} d={smooth(pts)} stroke={color} strokeWidth={(12 - i) * u} fill="none" strokeLinecap="round" filter={soft}
            opacity={0.8 * clamp01(k * 1.5)} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp01(k * 1.2)} />
        );
      })}
    </Canvas>
  );
}

export type DripsProps = {
  /** the edge they run from: left end (x, y) and its width */
  x: number; y: number; w: number;
  /** frames since they started */
  age: number;
  n?: number; len?: number; color?: string; seed?: string;
};

/** Drops running down from an edge, each at its own pace, a bead at each tip. */
export function Drips({ x, y, w, age, n = 5, len, color, seed = "drips" }: DripsProps) {
  const pal = usePalette();
  const u = useUnit();
  if (age <= 0) return null;
  const c = color ?? pal.lemon;
  const L = len ?? 160 * u;
  return (
    <Canvas>
      {Array.from({ length: n }, (_, i) => {
        const cx = x + (w * (i + 0.2 + random(`${seed}x${i}`) * 0.6)) / n;
        const speed = 0.5 + random(`${seed}s${i}`) * 0.8;
        const delay = random(`${seed}d${i}`) * 10;
        const l = L * clamp01(((age - delay) * speed) / 30);
        if (l <= 0) return null;
        const r = (10 + random(`${seed}r${i}`) * 7) * u;
        return (
          <g key={i}>
            <path d={`M${cx - r * 1.1} ${y} Q${cx - r * 0.55} ${y + 4 * u} ${cx - r * 0.55} ${y + l * 0.35} L${cx - r * 0.75} ${y + l} L${cx + r * 0.75} ${y + l} L${cx + r * 0.55} ${y + l * 0.35} Q${cx + r * 0.55} ${y + 4 * u} ${cx + r * 1.1} ${y} Z`} fill={c} />
            <circle cx={cx} cy={y + l} r={r} fill={c} />
            <path d={`M${cx - r * 0.3} ${y + 6 * u} L${cx - r * 0.3} ${y + l - r}`} stroke="#FFFFFF" strokeOpacity={0.35} strokeWidth={r * 0.25} strokeLinecap="round" />
            <circle cx={cx - r * 0.35} cy={y + l - r * 0.35} r={r * 0.3} fill="#FFFFFF" opacity={0.5} />
          </g>
        );
      })}
    </Canvas>
  );
}

export type SparksProps = {
  x: number; y: number;
  /** frames since the burst (draws for 0 < age < life) */
  age: number;
  n?: number; life?: number; reach?: number; color?: string; seed?: string;
};

/** A burst of short strokes flying out from a point: a hit, a pop, something coming loose. */
export function Sparks({ x, y, age, n = 14, life = 14, reach, color, seed = "sparks" }: SparksProps) {
  const pal = usePalette();
  const u = useUnit();
  if (age <= 0 || age >= life) return null;
  const k = age / life;
  const R = reach ?? 150 * u;
  const out = 1 - Math.pow(1 - k, 3);
  return (
    <Canvas>
      {Array.from({ length: n }, (_, i) => {
        const a = (i / n) * Math.PI * 2 + (random(`${seed}a${i}`) - 0.5) * 0.5;
        const r1 = R * (0.35 + 0.65 * out) * (0.7 + random(`${seed}r${i}`) * 0.5);
        const r0 = r1 - R * 0.28 * (1 - k);
        return <line key={i} x1={x + Math.cos(a) * r0} y1={y + Math.sin(a) * r0} x2={x + Math.cos(a) * r1} y2={y + Math.sin(a) * r1}
          stroke={color ?? pal.accent} strokeWidth={(7 - 4 * k) * u} strokeLinecap="round" opacity={1 - k * k} />;
      })}
    </Canvas>
  );
}
