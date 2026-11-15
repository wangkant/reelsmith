// Materials: the shading recipe as wrappers for any shape an author draws (a path or SVG children), so story
// objects read as made things: a lit body, a rim light, a darker underside, specks, gloss and a contact shadow.
import React from "react";
import { random } from "remotion";
import { useClip } from "../context";
import { mixColor } from "./geom";
import { shades, useFilters, usePalette, useUnit } from "./palette";

/** An SVG plane over the whole clip, in clip px, that never clips what is drawn past its edges. */
export function Canvas({ z, opacity, children }: { z?: number; opacity?: number; children?: React.ReactNode }) {
  const { w, h } = useClip();
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", zIndex: z, opacity }}>
      {children}
    </svg>
  );
}

export type Box = [number, number, number, number];

type Shape = {
  /** the outline as an SVG path in clip px */
  d?: string;
  /** or any SVG shapes (their own fills are ignored; only their silhouette counts); needs `box` */
  children?: React.ReactNode;
  /** [x, y, w, h] the shape occupies: required with children; with `d` it places the shadow and the specks */
  box?: Box;
};

const WHITE = "0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1 0";

/** The shape's silhouette as a clip (path) or mask (children), and a filler that paints it with any fill. */
function useShape({ d, children, box }: Shape, id: string) {
  const defs = d ? (
    <clipPath id={id + "c"}><path d={d} /></clipPath>
  ) : (
    <>
      <filter id={id + "w"}><feColorMatrix values={WHITE} /></filter>
      <mask id={id + "m"} maskUnits="userSpaceOnUse" x={(box?.[0] ?? 0) - 2000} y={(box?.[1] ?? 0) - 2000} width={(box?.[2] ?? 0) + 4000} height={(box?.[3] ?? 0) + 4000}>
        <g filter={`url(#${id}w)`}>{children}</g>
      </mask>
    </>
  );
  const within = d ? { clipPath: `url(#${id}c)` } : { mask: `url(#${id}m)` };
  const fill = (paint: string, extra: React.SVGProps<SVGPathElement> = {}) =>
    d ? <path d={d} fill={paint} {...extra} />
      : box ? <rect x={box[0]} y={box[1]} width={box[2]} height={box[3]} fill={paint} {...(extra as React.SVGProps<SVGRectElement>)} /> : null;
  return { defs, within, fill };
}

export type ShadowProps = {
  /** contact shadow: the point under the object's base, and its width (height defaults to w * 0.13) */
  x?: number; y?: number; w?: number; h?: number;
  /** 0 resting on the surface .. 1 held well above it: the shadow spreads, softens and fades */
  lift?: number;
  opacity?: number;
  /** with children: a drop shadow of the children instead (offset and blur by `lift`) */
  children?: React.ReactNode;
};

/** A contact shadow (a dark core and a soft wide penumbra) or, around children, a drop shadow. */
export function Shadow({ x = 0, y = 0, w = 200, h, lift = 0, opacity = 1, children }: ShadowProps) {
  const pal = usePalette();
  const u = useUnit();
  const k = Math.max(0, Math.min(1, lift));
  const { id, defs, soft, blur } = useFilters(6 * u + 10 * u * k, 16 * u + 18 * u * k);
  if (children) {
    return (
      <g>
        <defs>
          <filter id={id + "d"} x="-30%" y="-30%" width="160%" height="170%">
            <feDropShadow dx={(4 + 16 * k) * u} dy={(6 + 30 * k) * u} stdDeviation={(5 + 14 * k) * u} floodColor={pal.shadow} floodOpacity={(0.38 - 0.14 * k) * opacity} />
          </filter>
        </defs>
        <g filter={`url(#${id}d)`}>{children}</g>
      </g>
    );
  }
  const hh = h ?? w * 0.13;
  const sx = x + 10 * u * (1 + k);
  return (
    <g>
      {defs}
      <ellipse cx={sx} cy={y + hh * 0.15} rx={w * (0.62 + 0.25 * k)} ry={hh * (1 + 0.6 * k)} fill={pal.shadow} opacity={(0.22 - 0.1 * k) * opacity} filter={blur} />
      <ellipse cx={sx} cy={y} rx={w * (0.46 + 0.1 * k)} ry={hh * 0.5} fill={pal.shadow} opacity={0.42 * (1 - 0.8 * k) * opacity} filter={soft} />
    </g>
  );
}

export type GlossProps = Shape & {
  /** where the highlight sits on the shape, 0..1 of its box (default upper left) */
  at?: [number, number];
  /** highlight radius as a fraction of the shape */
  size?: number;
  strength?: number;
  /** 0..1 a glint band sweeping across the shape (omit for none) */
  sweep?: number;
};

/** A wet or polished highlight clipped to the shape, with an optional moving glint. */
export function Gloss({ at = [0.3, 0.24], size = 0.32, strength = 0.6, sweep, ...shape }: GlossProps) {
  const { id } = useFilters();
  const s = useShape(shape, id);
  const sw = sweep === undefined ? null : Math.max(-0.3, Math.min(1.3, sweep));
  const box = shape.box;
  const units = shape.d ? "objectBoundingBox" : "userSpaceOnUse";
  const pos = (fx: number, fy: number) => (shape.d || !box ? [fx, fy] : [box[0] + fx * box[2], box[1] + fy * box[3]]);
  const [cx, cy] = pos(at[0], at[1]);
  const r = shape.d || !box ? size : size * Math.max(box[2], box[3]);
  const [x1, y1] = pos(0, 0.1), [x2, y2] = pos(1, 0.9);
  return (
    <g>
      <defs>
        {s.defs}
        <radialGradient id={id + "h"} gradientUnits={units} cx={cx} cy={cy} r={r}>
          <stop offset="0" stopColor="#FFFFFF" stopOpacity={strength} />
          <stop offset="0.45" stopColor="#FFFFFF" stopOpacity={strength * 0.35} />
          <stop offset="1" stopColor="#FFFFFF" stopOpacity={0} />
        </radialGradient>
        {sw !== null ? (
          <linearGradient id={id + "s"} gradientUnits={units} x1={x1} y1={y1} x2={x2} y2={y2}>
            <stop offset={Math.max(0, sw - 0.08)} stopColor="#FFFFFF" stopOpacity={0} />
            <stop offset={Math.max(0, Math.min(1, sw))} stopColor="#FFFFFF" stopOpacity={strength * 0.8} />
            <stop offset={Math.min(1, sw + 0.08)} stopColor="#FFFFFF" stopOpacity={0} />
          </linearGradient>
        ) : null}
      </defs>
      <g {...s.within}>
        {s.fill(`url(#${id}h)`)}
        {sw !== null ? s.fill(`url(#${id}s)`) : null}
      </g>
    </g>
  );
}

export type SolidProps = Shape & {
  /** the body colour; lit and shaded versions come from it */
  tone: string;
  /** visible thickness under the body in px (0 = a flat shape) */
  side?: number;
  /** rim-light width in px (default 7u) */
  rim?: number;
  /** how dark the underside goes, 0..1 */
  under?: number;
  /** seeded surface specks (needs a box) */
  speckle?: number;
  /** a highlight 0..1, and a glint position 0..1 (see Gloss) */
  gloss?: number;
  sweep?: number;
  /** contact-shadow strength (needs a box; 0 = none) and the object's lift off its surface 0..1 */
  shadow?: number;
  lift?: number;
  /** ink outline width (path shapes only; 0 = none) */
  outline?: number;
  seed?: string;
  /** drawn on the body and clipped to it: stripes, labels, seams */
  detail?: React.ReactNode;
};

/** Any shape made solid: a contact shadow, a thickness, a lit gradient body, a rim light along the lit edge, a darker
 *  underside, specks, gloss and a faint ink line. SVG: put it inside a <Canvas> or your own <svg>. */
export function Solid({ d, children, box, tone, side = 0, rim, under = 0.5, speckle = 0, gloss = 0, sweep, shadow = 1, lift = 0,
  outline = 2, seed = "solid", detail }: SolidProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id } = useFilters();
  const s = useShape({ d, children, box }, id);
  const c = shades(tone);
  const r = rim ?? 7 * u;
  const units = d ? "objectBoundingBox" : "userSpaceOnUse";
  const g = (fx: number, fy: number) => (d || !box ? [fx, fy] : [box[0] + fx * box[2], box[1] + fy * box[3]]);
  const [gx, gy] = g(0.34, 0.26), [lx1, ly1] = g(0, 0), [lx2, ly2] = g(0, 1);
  const gr = d || !box ? 0.95 : 0.95 * Math.max(box[2], box[3]);
  const sideFill = mixColor(c.deep, "#000000", 0.25);
  const sideShape = side > 0 ? (d ? <path d={d} fill={sideFill} transform={`translate(0 ${side})`} />
    : <g transform={`translate(0 ${side})`} mask={`url(#${id}m)`}>{s.fill(sideFill)}</g>) : null;
  return (
    <g>
      <defs>
        {s.defs}
        <radialGradient id={id + "g"} gradientUnits={units} cx={gx} cy={gy} r={gr}>
          <stop offset="0" stopColor={c.hi} />
          <stop offset="0.5" stopColor={c.base} />
          <stop offset="1" stopColor={c.deep} />
        </radialGradient>
        <linearGradient id={id + "u"} gradientUnits={units} x1={lx1} y1={ly1} x2={lx2} y2={ly2}>
          <stop offset="0.5" stopColor={c.deep} stopOpacity={0} />
          <stop offset="1" stopColor={mixColor(c.deep, "#000000", 0.3)} stopOpacity={under} />
        </linearGradient>
        <filter id={id + "r"} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={Math.max(0.6, r * 0.45)} /></filter>
      </defs>
      {box && shadow > 0 ? <Shadow x={box[0] + box[2] / 2} y={box[1] + box[3] + side} w={box[2] * 0.5} lift={lift} opacity={shadow} /> : null}
      {sideShape}
      <g {...s.within}>
        {s.fill(c.rim)}
        <g transform={`translate(${r} ${r})`} filter={`url(#${id}r)`}>{s.fill(`url(#${id}g)`)}</g>
        {s.fill(`url(#${id}u)`)}
        {box && speckle > 0 ? Array.from({ length: speckle }, (_, i) => {
          const x = box[0] + random(`${seed}sx${i}`) * box[2], y = box[1] + random(`${seed}sy${i}`) * box[3];
          const l = (0.015 + random(`${seed}sl${i}`) * 0.04) * Math.min(box[2], 420 * u);
          return <path key={i} d={`M${x.toFixed(1)} ${y.toFixed(1)} q${(l / 2).toFixed(1)} ${((random(`${seed}sq${i}`) - 0.5) * l * 0.6).toFixed(1)} ${l.toFixed(1)} 0`}
            fill="none" strokeLinecap="round" stroke={random(`${seed}sc${i}`) > 0.5 ? c.hi : c.deep} strokeWidth={Math.max(1.2, Math.min(box[3] * 0.012, 4 * u))} opacity={0.4} />;
        }) : null}
        {detail}
      </g>
      {gloss > 0 ? <Gloss d={d} box={box} strength={gloss} sweep={sweep}>{children}</Gloss> : null}
      {d && outline > 0 ? <path d={d} fill="none" stroke={pal.ink} strokeOpacity={0.3} strokeWidth={outline * u} /> : null}
    </g>
  );
}
