// Things printed on or shown by an object in a photograph: children laid on a quadrilateral traced in the
// picture's pixels (a blank label, a screen, a sheet of paper), in its perspective and taking its light.
import React, { useContext, useId } from "react";
import { PictureContext } from "./photo";
import type { Pt } from "./geom";

/** The CSS matrix3d that maps a w x h box (origin at its top-left) onto the quad [top-left, top-right,
 *  bottom-right, bottom-left] in px: a true perspective map, so straight lines stay straight. */
export const quadMatrix = (w: number, h: number, quad: Pt[]): string => {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = quad;
  const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  let g = 0, hh = 0;
  const den = dx1 * dy2 - dx2 * dy1;
  if ((Math.abs(dx3) > 1e-9 || Math.abs(dy3) > 1e-9) && Math.abs(den) > 1e-12) {
    g = (dx3 * dy2 - dx2 * dy3) / den;
    hh = (dx1 * dy3 - dx3 * dy1) / den;
  }
  const a = x1 - x0 + g * x1, b = x3 - x0 + hh * x3, d = y1 - y0 + g * y1, e = y3 - y0 + hh * y3;
  const m = [a / w, d / w, 0, g / w, b / h, e / h, 0, hh / h, 0, 0, 1, 0, x0, y0, 0, 1];
  return `matrix3d(${m.map((v) => +v.toFixed(8)).join(", ")})`;
};

export type SurfaceProps = {
  /** the corners in picture px as seen: top-left, top-right, bottom-right, bottom-left of the blank area */
  quad: Pt[];
  /** map picture px to stage px yourself (default: the enclosing Photo or Plate) */
  at?: (pt: Pt) => Pt;
  /** the layout box the children are written in, px (default: the quad's own size on the stage) */
  w?: number;
  h?: number;
  /** print: ink on the surface, multiplied into its paper, folds and light; glow: an emitting screen; plain: as is */
  ink?: "print" | "glow" | "plain";
  /** frayed ink edges in px (print); extra softness in px, over the enclosing picture's depth of field and smear */
  rough?: number;
  blur?: number;
  /** text colour for the children, padding as a fraction of the box */
  color?: string;
  pad?: number;
  opacity?: number;
  seed?: number;
  children?: React.ReactNode;
};

/** Children on a traced quad of a picture: they follow the Photo, Plate or Travel the quad belongs to, in its
 *  perspective and its blur; printed ink takes the surface's grain and shading, a screen glows. Centred in the box. */
export function Surface({ quad, at, w, h, ink = "print", rough, blur = 0.4, color, pad = 0.08, opacity = 1, seed = 7, children }: SurfaceProps) {
  const pic = useContext(PictureContext);
  const id = "sf" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const map = at ?? pic?.at;
  if (!map) throw new Error("Surface: put it inside a <Photo> or a <Plate>, or pass `at`");
  if (quad.length !== 4) throw new Error("Surface: quad needs four corners (top-left, top-right, bottom-right, bottom-left)");
  if (!(opacity > 0)) return null;
  const q = quad.map(map);
  const dist = (a: Pt, b: Pt) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const bw = w ?? (dist(q[0], q[1]) + dist(q[3], q[2])) / 2;
  const bh = h ?? (dist(q[0], q[3]) + dist(q[1], q[2])) / 2;
  const fray = rough ?? (ink === "print" ? Math.max(0.6, bw / 400) : 0);
  // the picture's depth of field and smear, turned into the box's own px and axes, so the ink blurs with the thing
  const qw = (dist(q[0], q[1]) + dist(q[3], q[2])) / 2 || 1, qh = (dist(q[0], q[3]) + dist(q[1], q[2])) / 2 || 1;
  const pb = pic && !at ? pic.blur ?? 0 : 0, sm = pic && !at ? pic.smear ?? 0 : 0;
  const rel = (((pic?.smearAng ?? 0) * Math.PI) / 180) - Math.atan2(q[1][1] - q[0][1], q[1][0] - q[0][0]);
  const sx = Math.hypot(blur, (bw / qw) * Math.hypot(pb, sm * Math.cos(rel)));
  const sy = Math.hypot(blur, (bh / qh) * Math.hypot(pb, sm * Math.sin(rel)));
  const soft = sx > 0.05 || sy > 0.05;
  const mx = Math.min(1, 0.05 + (3 * sx) / bw), my = Math.min(1, 0.05 + (3 * sy) / bh);
  const filters = [fray > 0 || soft ? `url(#${id})` : "",
    ink === "glow" ? `drop-shadow(0 0 ${(bh * 0.04).toFixed(1)}px currentColor)` : ""].filter(Boolean).join(" ");
  return (
    <>
      {fray > 0 || soft ? (
        <svg width={0} height={0} style={{ position: "absolute" }}>
          <filter id={id} x={`${(-mx * 100).toFixed(1)}%`} y={`${(-my * 100).toFixed(1)}%`} width={`${(100 + mx * 200).toFixed(1)}%`}
            height={`${(100 + my * 200).toFixed(1)}%`} colorInterpolationFilters="sRGB">
            {fray > 0 ? <feTurbulence type="fractalNoise" baseFrequency={(1 / Math.max(1, fray * 1.8)).toFixed(4)} numOctaves={2} seed={seed} result="n" /> : null}
            {fray > 0 ? <feDisplacementMap in="SourceGraphic" in2="n" scale={fray * 2} xChannelSelector="R" yChannelSelector="G" /> : null}
            {soft ? <feGaussianBlur stdDeviation={`${sx.toFixed(2)} ${sy.toFixed(2)}`} /> : null}
          </filter>
        </svg>
      ) : null}
      <div style={{
        position: "absolute", left: 0, top: 0, width: bw, height: bh, boxSizing: "border-box", padding: `${(pad * bh).toFixed(1)}px ${(pad * bw).toFixed(1)}px`,
        transformOrigin: "0 0", transform: quadMatrix(bw, bh, q), display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center",
        color: color ?? (ink === "glow" ? "#F4FBFF" : "#2A1C12"), opacity: opacity < 1 ? opacity : undefined, pointerEvents: "none",
        mixBlendMode: ink === "print" ? "multiply" : ink === "glow" ? "screen" : undefined, filter: filters || undefined,
      }}>
        {children}
      </div>
    </>
  );
}
