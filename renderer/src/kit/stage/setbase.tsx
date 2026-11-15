// What every set shares: the set context, the layered shell over a Stage, and small idle pieces (clouds, lamps, leaves).
import React, { createContext, useContext } from "react";
import { random } from "remotion";
import { useClip } from "../context";
import { blob, mixColor } from "./geom";
import { useFilters, usePalette } from "./palette";
import { Layer, Stage, useStage } from "./Stage";
import type { StageProps } from "./Stage";
import { pendulum } from "./motion";

export type SetInfo = {
  /** y of the surface things stand on (clip px) */
  floor: number;
  /** y of a nearer surface (a road, the front of a counter); equals floor when the set has none */
  near: number;
  /** world x range the set is drawn over at the action plane */
  x0: number; x1: number;
  w: number; h: number;
};

const SetContext = createContext<SetInfo | null>(null);

/** The enclosing set's surfaces and span (a floor at 70 % of the height outside a set). */
export const useSet = (): SetInfo => {
  const ctx = useContext(SetContext);
  const { w, h } = useClip();
  return ctx ?? { floor: h * 0.7, near: h * 0.7, x0: -w * 0.3, x1: w * 1.3, w, h };
};

export type SetProps = Omit<StageProps, "ground" | "children"> & {
  /** y of the surface things stand on, in clip px (each set has its own default) */
  floor?: number;
  /** world x range the camera travels over, at the action plane (default the frame plus 30 % each side) */
  span?: [number, number];
  /** blurred foreground pieces at the frame edges */
  front?: boolean;
  seed?: string;
  /** drawn on the far wall or sky plane, moving with it (a sign on the wall, a plane in the sky) */
  back?: React.ReactNode;
  /** the action: drawn on the action plane (depth 1) in clip px, above the surface */
  children?: React.ReactNode;
};

/** The sets' size unit: 1 on a 1080 x 1920 frame, scaled by the tighter of width and height on any other. */
export const useSetUnit = (): number => {
  const { w, h } = useClip();
  return w > 0 && h > 0 ? Math.min(w / 1080, h / 1920) : 1;
};

/** x range to draw a plane at `depth` so the camera never shows its edge over the set's span. */
export const spanAt = (x0: number, x1: number, w: number, depth: number): [number, number] => {
  const pad = w * 0.75;
  return [w / 2 + (x0 - w / 2) * depth - pad, w / 2 + (x1 - w / 2) * depth + pad];
};

type Plane = { depth: number; node: React.ReactNode; blur?: number };

/** A Stage with the set's planes in depth order, the action plane at depth 1 and the foreground on top. */
export function SetShell({ info, planes, surface, front, stage, children }: {
  info: SetInfo; planes: Plane[]; surface: React.ReactNode; front?: Plane | null; stage: Omit<SetProps, "floor" | "span" | "front" | "seed" | "back" | "children">;
  children?: React.ReactNode;
}) {
  const { grain = 0.05, light = 0.45, vignette = 0.35, ...rest } = stage;
  return (
    <Stage grain={grain} light={light} vignette={vignette} {...rest}>
      <SetContext.Provider value={info}>
        {planes.map((p, i) => <Layer key={i} depth={p.depth} blur={p.blur}>{p.node}</Layer>)}
        <Layer depth={1}>{surface}{children}</Layer>
        {front ? <Layer depth={front.depth} blur={front.blur}>{front.node}</Layer> : null}
      </SetContext.Provider>
    </Stage>
  );
}

/** A full-plane SVG from x0 to x1 and from y0 to y1, in the plane's own px. */
export function Plate({ x0, x1, y0, y1, children }: { x0: number; x1: number; y0: number; y1: number; children?: React.ReactNode }) {
  return (
    <svg width={x1 - x0} height={y1 - y0} viewBox={`${x0} ${y0} ${x1 - x0} ${y1 - y0}`}
      style={{ position: "absolute", left: x0, top: y0, overflow: "visible" }}>
      {children}
    </svg>
  );
}

/** Soft clouds strung across [x0, x1] that drift right `speed` px a frame and wrap. */
export function Clouds({ x0, x1, y, n = 5, speed = 0.4, seed = "cloud", color = "#FFFFFF" }: {
  x0: number; x1: number; y: number; n?: number; speed?: number; seed?: string; color?: string;
}) {
  const { f } = useStage();
  const u = useSetUnit();
  const pal = usePalette();
  const { soft } = useFilters(5 * u);
  const span = x1 - x0;
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const base = x0 + (span * (i + random(`${seed}x${i}`) * 0.6)) / n;
        const x = x0 + ((((base - x0 + f * speed * (0.6 + random(`${seed}v${i}`) * 0.8)) % span) + span) % span);
        const cy = y + (random(`${seed}y${i}`) - 0.5) * 260 * u;
        const s = (0.7 + random(`${seed}s${i}`) * 0.7) * u;
        return (
          <g key={i} filter={soft}>
            <path d={blob(x + 20 * s, cy + 22 * s, 200 * s, 40 * s, `${seed}b${i}`, 10, 0.08)} fill={mixColor(color, pal.sky, 0.25)} opacity={0.75} />
            <path d={blob(x - 60 * s, cy, 110 * s, 62 * s, `${seed}l${i}`, 10, 0.1)} fill={color} opacity={0.9} />
            <path d={blob(x + 60 * s, cy - 24 * s, 130 * s, 80 * s, `${seed}r${i}`, 10, 0.1)} fill={color} opacity={0.95} />
          </g>
        );
      })}
    </g>
  );
}

/** A pendant lamp hung from (x, y) on a `len` cord, idly swaying, with a warm glow beneath. */
export function PendantLamp({ x, y, len, color, phase = 0 }: { x: number; y: number; len: number; color?: string; phase?: number }) {
  const { f } = useStage();
  const u = useSetUnit();
  const pal = usePalette();
  const { soft, blur } = useFilters(10 * u, 40 * u);
  const a = pendulum(f + phase * 30, -999, 0, 1.1, 1.6, 2.2);
  const shade = color ?? pal.paper;
  const by = y + len;
  return (
    <g transform={`rotate(${a.toFixed(3)} ${x} ${y})`}>
      <ellipse cx={x} cy={by + 150 * u} rx={210 * u} ry={130 * u} fill="#FFE6A8" opacity={0.28} filter={blur} />
      <line x1={x} y1={y} x2={x} y2={by} stroke={pal.ink} strokeWidth={3 * u} opacity={0.7} />
      <path d={`M${x - 82 * u} ${by + 92 * u} Q${x - 70 * u} ${by + 6 * u} ${x} ${by} Q${x + 70 * u} ${by + 6 * u} ${x + 82 * u} ${by + 92 * u} Z`}
        fill={shade} stroke={mixColor(shade, "#000000", 0.25)} strokeWidth={2.5 * u} />
      <path d={`M${x - 60 * u} ${by + 30 * u} Q${x - 40 * u} ${by + 12 * u} ${x - 10 * u} ${by + 8 * u}`} stroke="#FFFFFF" strokeWidth={6 * u}
        fill="none" opacity={0.55} strokeLinecap="round" />
      <ellipse cx={x} cy={by + 92 * u} rx={80 * u} ry={14 * u} fill="#FFF1C4" filter={soft} />
      <ellipse cx={x} cy={by + 94 * u} rx={26 * u} ry={11 * u} fill="#FFFBEA" />
    </g>
  );
}

/** A spray of leaves from (x, y) pointing `ang` degrees (0 = up), for plants and blurred foreground. */
export function Leaves({ x, y, size, ang = 0, n = 7, color, seed = "leaf", sway = 0 }: {
  x: number; y: number; size: number; ang?: number; n?: number; color?: string; seed?: string; sway?: number;
}) {
  const { f } = useStage();
  const pal = usePalette();
  const c = color ?? pal.leaf;
  return (
    <g transform={`rotate(${ang + Math.sin(f / 40) * sway} ${x} ${y})`}>
      {Array.from({ length: n }, (_, i) => {
        const a = -70 + (140 * i) / Math.max(1, n - 1) + (random(`${seed}a${i}`) - 0.5) * 18;
        const l = size * (0.65 + random(`${seed}l${i}`) * 0.45), wd = l * 0.2;
        const tone = mixColor(c, i % 2 ? "#000000" : "#FFF6D8", 0.12 + 0.1 * random(`${seed}t${i}`));
        return (
          <g key={i} transform={`rotate(${a} ${x} ${y})`}>
            <path d={`M${x} ${y} Q${x - wd} ${y - l * 0.5} ${x} ${y - l} Q${x + wd} ${y - l * 0.5} ${x} ${y} Z`} fill={tone} />
            <path d={`M${x} ${y} L${x} ${y - l * 0.92}`} stroke={mixColor(tone, "#FFFFFF", 0.3)} strokeWidth={Math.max(1, wd * 0.08)} opacity={0.6} />
          </g>
        );
      })}
    </g>
  );
}
