// The stage: a camera over parallax layers, a ground, faint grain and warm light, sized to the clip.
import React, { createContext, useContext, useId } from "react";
import { useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { inOut } from "./time";
import { PaletteContext, usePalette } from "./palette";
import type { Palette } from "./palette";

/** A camera key: at frame `at` the frame centre looks at (x, y) of the stage at zoom z. `dip` pulls the zoom out
 *  mid-move (0..1) on the way to this key, so long travels read as a move, not a smear. */
export type Key = { at: number; x: number; y: number; z: number; dip?: number };

export type Cam = { x: number; y: number; z: number };

/** The camera at frame f: eased between keys, zoom interpolated geometrically. */
export const camAt = (keys: Key[], f: number): Cam => {
  if (!keys.length) return { x: NaN, y: NaN, z: 1 };
  if (f <= keys[0].at) return keys[0];
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1];
    if (f <= b.at) {
      const t = b.at > a.at ? (f - a.at) / (b.at - a.at) : 1;
      const k = inOut(t);
      const za = Math.max(1e-3, a.z), zb = Math.max(1e-3, b.z);
      const dip = b.dip ? 1 - b.dip * Math.sin(Math.PI * t) : 1;
      return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, z: za * Math.pow(zb / za, k) * dip };
    }
  }
  return keys[keys.length - 1];
};

type StageCtx = { cam: Cam; w: number; h: number; f: number };
const StageContext = createContext<StageCtx | null>(null);
const DepthContext = createContext(1);

/** The depth of the enclosing <Layer> (1 outside one): photo layers read it for depth of field. */
export const useDepth = (): number => useContext(DepthContext);

/** The enclosing stage's camera, size and frame (a still camera at the frame centre outside a stage). */
export const useStage = (): StageCtx => {
  const ctx = useContext(StageContext);
  const { w, h } = useClip();
  const f = useCurrentFrame();
  return ctx ?? { cam: { x: w / 2, y: h / 2, z: 1 }, w, h, f };
};

export type StageProps = {
  /** camera keys in clip frames; none = a still camera on the frame centre */
  cam?: Key[];
  /** the ground: a node (KraftGround, WallGround...) painted on a depth-0.55 layer behind everything; CSS colour = flat */
  ground?: React.ReactNode | string;
  /** grain strength 0..0.2 (0 = none); static unless grainFps > 0 (at most 6) */
  grain?: number;
  grainFps?: number;
  /** warm light from the top left, 0..1 */
  light?: number;
  /** darkened corners, 0..1 */
  vignette?: number;
  /** a slow idle drift of the whole stage in px (0 = still) */
  drift?: number;
  palette?: Partial<Palette>;
  /** the clip frame (defaults to the current frame) */
  f?: number;
  children?: React.ReactNode;
};

/** A full-clip stage. Children are usually <Layer depth> blocks; anything else sits at depth 1. */
export function Stage({ cam, ground, grain = 0.06, grainFps = 0, light = 0.5, vignette = 0.45, drift = 0, palette, f: fIn, children }: StageProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h } = useClip();
  const base = camAt(cam ?? [], f);
  const dx = drift ? Math.sin(f / 70) * drift : 0, dy = drift ? Math.cos(f / 90) * drift * 0.8 : 0;
  const c: Cam = Number.isFinite(base.x) ? { x: base.x - dx, y: base.y - dy, z: base.z } : { x: w / 2 - dx, y: h / 2 - dy, z: 1 };
  const ctx: StageCtx = { cam: c, w, h, f };
  const body = (
    <StageContext.Provider value={ctx}>
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, overflow: "hidden" }}>
        {typeof ground === "string" ? <div style={{ position: "absolute", inset: 0, background: ground }} />
          : ground ? <Layer depth={0.55}>{ground}</Layer> : null}
        {children}
        <Light w={w} h={h} light={light} vignette={vignette} />
        {grain > 0 ? <Grain w={w} h={h} amount={grain} fps={grainFps} f={f} /> : null}
      </div>
    </StageContext.Provider>
  );
  return palette ? <PaletteContext.Provider value={palette}>{body}</PaletteContext.Provider> : body;
}

/** A plane of the stage at `depth`: 1 moves with the camera, under 1 lags behind (background), over 1 runs ahead
 *  (foreground); parallax applies to x, y and zoom. `blur` softens a foreground plane (px). */
export function Layer({ depth = 1, blur = 0, opacity = 1, children }: { depth?: number; blur?: number; opacity?: number; children?: React.ReactNode }) {
  const { cam, w, h } = useStage();
  const tx = w / 2 + (cam.x - w / 2) * depth, ty = h / 2 + (cam.y - h / 2) * depth;
  const zp = 0.5 + 0.5 * depth;
  const z = Math.pow(Math.max(1e-3, cam.z), zp);
  return (
    <div style={{
      position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0", opacity,
      transform: `translate(${w / 2}px, ${h / 2}px) scale(${z}) translate(${-tx}px, ${-ty}px)`,
      filter: blur > 0 ? `blur(${blur}px)` : undefined,
    }}>
      <DepthContext.Provider value={depth}>{children}</DepthContext.Provider>
    </div>
  );
}

function Light({ w, h, light, vignette }: { w: number; h: number; light: number; vignette: number }) {
  const id = "sl" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const pal = usePalette();
  if (light <= 0 && vignette <= 0) return null;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none" }}>
      <defs>
        <linearGradient id={id + "l"} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FFE7B0" stopOpacity={0.3 * light} />
          <stop offset="0.6" stopColor="#FFE7B0" stopOpacity={0} />
        </linearGradient>
        <radialGradient id={id + "v"} cx="50%" cy="45%" r="75%">
          <stop offset="0.55" stopColor={pal.shadow} stopOpacity={0} />
          <stop offset="1" stopColor={pal.shadow} stopOpacity={0.5 * vignette} />
        </radialGradient>
      </defs>
      {light > 0 ? <rect width={w} height={h} fill={`url(#${id}l)`} /> : null}
      {vignette > 0 ? <rect width={w} height={h} fill={`url(#${id}v)`} /> : null}
    </svg>
  );
}

/** Faint paper grain over the frame. Static by default; re-seeded at most 6 times a second, because grain that
 *  changes every frame is what makes a film several times larger. */
export function Grain({ w, h, amount = 0.06, fps = 0, f = 0 }: { w: number; h: number; amount?: number; fps?: number; f?: number }) {
  const id = "sg" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const clipFps = useClip().fps || 30;
  const rate = Math.max(0, Math.min(6, fps));
  const seed = rate > 0 ? 1 + (Math.floor((f * rate) / clipFps) % 4) : 1;
  const a = Math.max(0, Math.min(0.2, amount));
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none", opacity: a / 0.2 }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={seed} />
        <feColorMatrix values="0 0 0 0 0.16  0 0 0 0 0.1  0 0 0 0 0.04  0 0 0 0.55 0" />
      </filter>
      <rect width={w} height={h} filter={`url(#${id})`} opacity={0.36} />
    </svg>
  );
}
