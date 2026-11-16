// The lens over a photographic world: focus for depth of field, a grade, vignette, static grain, impact kicks
// with a colour fringe and a hand-held drift; and joins that travel from one scene into the next.
import React, { createContext, useContext, useId } from "react";
import { useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { Grain } from "./Stage";
import { shake } from "./motion";
import { handheld } from "./optics";
import { clamp01 } from "./time";

export type LensState = { focus: number; aperture: number };
const LensContext = createContext<LensState>({ focus: 1, aperture: 0 });

/** The enclosing lens's focus depth and aperture (all sharp outside a Lens). */
export const useLens = (): LensState => useContext(LensContext);

export type Grade = {
  /** raise the blacks, 0..0.2 */
  lift?: number;
  /** midtones: above 1 brighter, below 1 darker */
  gamma?: number;
  /** highlights, around 1 */
  gain?: number;
  /** a colour multiplied in at strength tintA (warm morning, cool shade) */
  tint?: string;
  tintA?: number;
};

export type Kick = {
  /** frame of the impact, shake size in px, frames it lasts, colour fringe in px at its peak */
  at: number; amp?: number; dur?: number; fringe?: number;
};

export type LensProps = {
  /** depth in focus (a Layer depth) and the blur in px per unit of depth away from it (0 = all sharp) */
  focus?: number;
  aperture?: number;
  grade?: Grade;
  vignette?: number;
  /** static grain 0..0.2 */
  grain?: number;
  kick?: Kick | Kick[];
  /** hand-held drift in px (0 = locked off) */
  handheld?: number;
  seed?: string;
  f?: number;
  children?: React.ReactNode;
};

const rgb = (c: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6})$/i.exec((c || "").trim());
  const n = m ? parseInt(m[1], 16) : 0xffffff;
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};

/** A camera body around a whole world (put the Stage inside, with its own light, vignette and grain at 0). */
export function Lens({ focus = 1, aperture = 0, grade, vignette = 0.35, grain = 0.05, kick, handheld: hand = 0, seed = "lens", f: fIn, children }: LensProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const id = "ln" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const kicks = kick ? (Array.isArray(kick) ? kick : [kick]) : [];
  let kx = 0, ky = 0, fringe = 0;
  kicks.forEach((k, i) => {
    const dur = k.dur ?? 14;
    const [sx, sy] = shake(`${seed}k${i}`, f, k.at, k.amp ?? 22, dur, 16, fps || 30);
    kx += sx; ky += sy;
    if (f >= k.at && f < k.at + dur) fringe = Math.max(fringe, (k.fringe ?? 6) * Math.pow(1 - (f - k.at) / dur, 2));
  });
  const [hx, hy, hr] = hand > 0 ? handheld(f, hand, seed, fps || 30) : [0, 0, 0];
  const over = 1 + (2 * (hand + Math.max(0, ...kicks.map((k) => k.amp ?? 22)) * (kicks.length ? 1 : 0))) / Math.min(w, h);
  const g = grade, graded = !!g && (g.lift || (g.gamma && g.gamma !== 1) || (g.gain && g.gain !== 1) || g.tintA);
  const t = rgb(g?.tint ?? "#FFFFFF"), ta = clamp01(g?.tintA ?? 0);
  const filtered = graded || fringe > 0.25;
  const fn = (i: number) => ({
    type: "gamma" as const, amplitude: (g?.gain ?? 1) * (1 - ta + ta * t[i]), exponent: 1 / Math.max(0.2, g?.gamma ?? 1), offset: g?.lift ?? 0,
  });
  return (
    <LensContext.Provider value={{ focus, aperture }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, overflow: "hidden", background: "#000" }}>
        {filtered ? (
          <svg width={0} height={0} style={{ position: "absolute" }}>
            <filter id={id} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
              {fringe > 0.25 ? (
                <>
                  <feOffset in="SourceGraphic" dx={fringe} dy={fringe * 0.3} result="r0" />
                  <feColorMatrix in="r0" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
                  <feColorMatrix in="SourceGraphic" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
                  <feOffset in="SourceGraphic" dx={-fringe} dy={-fringe * 0.3} result="b0" />
                  <feColorMatrix in="b0" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
                  <feComposite in="r" in2="g" operator="arithmetic" k2={1} k3={1} result="rg" />
                  <feComposite in="rg" in2="b" operator="arithmetic" k2={1} k3={1} result="rgb" />
                </>
              ) : null}
              {graded ? <feComponentTransfer><feFuncR {...fn(0)} /><feFuncG {...fn(1)} /><feFuncB {...fn(2)} /></feComponentTransfer> : null}
            </filter>
          </svg>
        ) : null}
        <div style={{
          position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "50% 50%",
          transform: `translate(${(hx + kx).toFixed(2)}px, ${(hy + ky).toFixed(2)}px) rotate(${hr.toFixed(3)}deg) scale(${over.toFixed(4)})`,
          filter: filtered ? `url(#${id})` : undefined,
        }}>
          {children}
        </div>
        {vignette > 0 ? (
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
            background: `radial-gradient(ellipse 80% 70% at 50% 46%, rgba(0,0,0,0) 55%, rgba(8,6,4,${(0.55 * vignette).toFixed(3)}) 100%)` }} />
        ) : null}
        {grain > 0 ? <Grain w={w} h={h} amount={grain} /> : null}
      </div>
    </LensContext.Provider>
  );
}
