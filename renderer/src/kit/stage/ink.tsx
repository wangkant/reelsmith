// Ink drawn on at a fraction p (0..1): felt marker, highlighter, a wide paint stroke, a hand loop and an arrow.
import React from "react";
import { random, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { boil, clamp01 } from "./time";
import { smooth } from "./geom";
import type { Pt } from "./geom";
import { useFilters, usePalette, useUnit } from "./palette";

const Canvas = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", ...style }}>{children}</svg>
);

export type MarkerProps = {
  /** the path, in canvas px */
  d: string;
  /** 0..1 drawn */
  p: number;
  color?: string;
  w?: number;
  seed?: string;
  opacity?: number;
  /** boil in px at 12 poses a second (0 = still) */
  jitter?: number;
  /** a fixed dash pattern instead of drawing on */
  dash?: string;
  blend?: React.CSSProperties["mixBlendMode"];
  f?: number;
};

/** A felt-pen stroke drawn on to fraction p, boiling slightly. */
export function Marker({ d, p, color, w, seed = "marker", opacity = 1, jitter = 1.2, dash, blend, f: fIn }: MarkerProps) {
  const now = useCurrentFrame();
  const { fps } = useClip();
  const pal = usePalette();
  const u = useUnit();
  if (p <= 0) return null;
  const [jx, jy] = jitter > 0 ? boil(seed, fIn ?? now, jitter, fps) : [0, 0];
  return (
    <Canvas style={blend ? { mixBlendMode: blend } : undefined}>
      <g transform={`translate(${jx} ${jy})`} opacity={opacity}>
        <path d={d} pathLength={1} fill="none" stroke={color ?? pal.red} strokeWidth={w ?? 10 * u} strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray={dash ?? "1 1"} strokeDashoffset={dash ? 0 : 1 - clamp01(p)} />
      </g>
    </Canvas>
  );
}

/** A highlighter pass: a wide, translucent, multiplied marker. */
export function Highlighter(props: Omit<MarkerProps, "blend">) {
  const pal = usePalette();
  const u = useUnit();
  return <Marker jitter={0.6} {...props} w={props.w ?? 34 * u} color={props.color ?? pal.lemon} opacity={props.opacity ?? 0.8} blend="multiply" />;
}

export type StrokeProps = {
  /** the brush's path, in canvas px */
  d: string;
  /** the shape the paint stays inside (a path in canvas px) */
  clip?: string;
  p: number;
  color?: string;
  w?: number;
  opacity?: number;
};

/** A wide paint stroke, brushed on and kept inside a shape (dye on a surface, paint on a wall). */
export function Stroke({ d, clip, p, color, w: wIn, opacity = 0.92 }: StrokeProps) {
  const pal = usePalette();
  const u = useUnit();
  const w = wIn ?? 60 * u;
  const { id } = useFilters();
  if (p <= 0) return null;
  return (
    <Canvas>
      {clip ? <defs><clipPath id={id + "c"}><path d={clip} /></clipPath></defs> : null}
      <g clipPath={clip ? `url(#${id}c)` : undefined} opacity={opacity}>
        <path d={d} pathLength={1} fill="none" stroke={color ?? pal.lemon} strokeWidth={w} strokeLinecap="round" strokeLinejoin="round"
          strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)} />
        <path d={d} pathLength={1} fill="none" stroke="#FFFFFF" strokeOpacity={0.25} strokeWidth={w * 0.18} strokeLinecap="round"
          strokeDasharray="1 1" strokeDashoffset={1 - clamp01(p)} transform={`translate(${-w * 0.18} ${-w * 0.14})`} />
      </g>
    </Canvas>
  );
}

export type CircleItProps = { x: number; y: number; w: number; h: number; p: number; color?: string; sw?: number; seed?: string; f?: number };

/** A quick hand-drawn loop round a box centred at (x, y): starts top right, overshoots past its start. */
export function CircleIt({ x, y, w, h, p, color, sw, seed = "loop", f }: CircleItProps) {
  const pts: Pt[] = [];
  const n = 14;
  for (let i = 0; i <= n; i++) {
    const a = -Math.PI * 0.32 - (i / n) * Math.PI * 2.18;
    const r = 1 + (random(`${seed}${i}`) - 0.5) * 0.12 + (i / n) * 0.06;
    pts.push([x + Math.cos(a) * (w / 2) * 1.08 * r, y + Math.sin(a) * (h / 2) * 1.12 * r]);
  }
  return <Marker d={smooth(pts)} p={p} color={color} w={sw} seed={seed} f={f} />;
}

export type ArrowInkProps = { from: Pt; to: Pt; p: number; color?: string; w?: number; bend?: number; seed?: string; f?: number };

/** A hand-drawn curved arrow from `from` to `to`; the head lands as the line arrives. */
export function ArrowInk({ from, to, p, color, w, bend = 0.22, seed = "arrow", f }: ArrowInkProps) {
  const u = useUnit();
  const pal = usePalette();
  const dx = to[0] - from[0], dy = to[1] - from[1];
  const mid: Pt = [from[0] + dx / 2 - dy * bend, from[1] + dy / 2 + dx * bend];
  const d = `M${from[0]} ${from[1]} Q${mid[0]} ${mid[1]} ${to[0]} ${to[1]}`;
  const ang = Math.atan2(to[1] - mid[1], to[0] - mid[0]);
  const L = 34 * u, spread = 0.5;
  const head = `M${to[0] - L * Math.cos(ang - spread)} ${to[1] - L * Math.sin(ang - spread)} L${to[0]} ${to[1]} L${to[0] - L * Math.cos(ang + spread)} ${to[1] - L * Math.sin(ang + spread)}`;
  return (
    <>
      <Marker d={d} p={clamp01(p / 0.85)} color={color ?? pal.ink} w={w} seed={seed} f={f} />
      <Marker d={head} p={clamp01((p - 0.85) / 0.15)} color={color ?? pal.ink} w={w} seed={seed} f={f} />
    </>
  );
}
