// Things inside a photograph that bend: Refract displaces whatever it wraps with moving noise (heat shimmer, a
// pressure front, a ripple); Warp bulges, squashes, bends or shakes one soft region of what it wraps.
import React, { useId } from "react";
import { useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { clamp01 } from "./time";

/** An ellipse [cx, cy, rx, ry] in the stage px of the wrapped content. */
export type Area = [number, number, number, number];

const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: "100%", height: "100%" };

/** A CSS mask: a soft ellipse, or a soft ring of radius r and `width` (a front). */
export const softEllipse = ([cx, cy, rx, ry]: Area, feather = 0.45): string =>
  `radial-gradient(${rx}px ${ry}px at ${cx}px ${cy}px, black ${Math.round((1 - clamp01(feather)) * 100)}%, transparent 100%)`;
export const softRing = (cx: number, cy: number, r: number, width: number, squash = 1): string => {
  const R = r + width;
  const s = (v: number) => `${Math.max(0, (100 * v) / R).toFixed(2)}%`;
  return `radial-gradient(${R}px ${R * squash}px at ${cx}px ${cy}px, transparent ${s(r - width)}, black ${s(r)}, transparent 100%)`;
};

export type RefractProps = {
  /** heat: noise rising through `area`; front: a ring of radius `r` and `width` around (area cx, cy) bending outward;
   *  ripple: a few rings spreading from (cx, cy) at `r` */
  kind?: "heat" | "front" | "ripple";
  area: Area;
  r?: number;
  width?: number;
  /** displacement in px (how far the picture bends), noise grain in px, scroll in px per second */
  strength?: number;
  grain?: number;
  speed?: number;
  /** a push outward on the ring, as a fraction (front, ripple) */
  push?: number;
  seed?: number;
  f?: number;
  children?: React.ReactNode;
};

/** Bends what it wraps: the wrapped content is drawn once as it is and once displaced, inside a soft mask. */
export function Refract({ kind = "heat", area, r = 0, width = 60, strength = 14, grain = 60, speed = 120, push = 0.03, seed = 5, f: fIn, children }: RefractProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const id = "rf" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const [cx, cy, rx, ry] = area;
  const d = (f / (fps || 30)) * speed;                       // the noise scrolls by d, the picture stays
  const mask = kind === "heat" ? softEllipse(area)
    : kind === "front" ? softRing(cx, cy, r, width, ry / Math.max(1, rx))
    : [0, 1, 2].map((i) => softRing(cx, cy, Math.max(0, r - i * width * 2.2), width * (1 - i * 0.2), ry / Math.max(1, rx))).join(", ");
  const reach = kind === "heat" ? Math.max(rx, ry) : r + width * 2;
  const s = 1 + (kind === "heat" ? 0 : push);
  const rect = { x: cx - reach - strength, y: cy - reach - strength + (kind === "heat" ? d : 0), width: 2 * (reach + strength), height: 2 * (reach + strength) };
  const idle = !(strength > 0) || (kind === "heat" ? !(rx > 0 && ry > 0) : !(r > 0 && width > 0));
  if (idle) return <>{children}</>;
  return (
    <>
      {children}
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id={id} filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" {...rect} colorInterpolationFilters="sRGB">
          <feTurbulence type={kind === "heat" ? "turbulence" : "fractalNoise"} baseFrequency={`${(1 / grain).toFixed(5)} ${(kind === "heat" ? 0.45 / grain : 1 / grain).toFixed(5)}`}
            numOctaves={2} seed={seed} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={strength} xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
      <div style={{ ...full, width: w, height: h, WebkitMaskImage: mask, maskImage: mask, pointerEvents: "none" }}>
        <div style={{ ...full, width: w, height: h, transform: kind === "heat" ? `translateY(${-d}px)` : undefined, filter: `url(#${id})` }}>
          <div style={{ ...full, width: w, height: h, transformOrigin: `${cx}px ${cy + (kind === "heat" ? d : 0)}px`,
            transform: `${kind === "heat" ? `translateY(${d}px)` : ""} scale(${s})` }}>
            {children}
          </div>
        </div>
      </div>
    </>
  );
}

export type WarpProps = {
  /** the soft region that moves, and how much of its radius is feathered (0..1) */
  area: Area;
  feather?: number;
  /** the pivot (default the area's centre) */
  origin?: [number, number];
  /** scale x and y (bulge > 1, squash sx > 1 with sy < 1), rotation in degrees, skew x in degrees, shift in px */
  sx?: number; sy?: number;
  rot?: number;
  skew?: number;
  dx?: number; dy?: number;
  children?: React.ReactNode;
};

/** Deforms one soft region of what it wraps: the region is drawn again transformed and feathered into the rest. */
export function Warp({ area, feather = 0.5, origin, sx = 1, sy = 1, rot = 0, skew = 0, dx = 0, dy = 0, children }: WarpProps) {
  const { w, h } = useClip();
  const [ox, oy] = origin ?? [area[0], area[1]];
  const still = sx === 1 && sy === 1 && !rot && !skew && !dx && !dy;
  if (still) return <>{children}</>;
  const mask = softEllipse(area, feather);
  return (
    <>
      {children}
      <div style={{ ...full, width: w, height: h, WebkitMaskImage: mask, maskImage: mask, pointerEvents: "none" }}>
        <div style={{ ...full, width: w, height: h, transformOrigin: `${ox}px ${oy}px`,
          transform: `translate(${dx}px, ${dy}px) rotate(${rot}deg) skewX(${skew}deg) scale(${sx}, ${sy})` }}>
          {children}
        </div>
      </div>
    </>
  );
}
