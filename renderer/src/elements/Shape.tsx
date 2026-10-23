// SVG shapes in box coordinates: rect, ellipse, line and arrow (top-left -> bottom-right of the box unless `d` is
// given), path (`d`). With `draw`, the stroke draws on with progress (default 0 -> 1 over the first 0.6 s).
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { getLength, getPointAtLength, getTangentAtLength } from "@remotion/paths";
import type { ShapeContent, Theme } from "../types";
import { clamp01, color } from "./util";

/** The shape's outline as a path in box pixels (strokes kept inside the box for rect/ellipse). */
export const shapePath = (c: ShapeContent, w: number, h: number, sw: number, radius: number): string => {
  if (c.d && (c.shape === "path" || c.shape === "line" || c.shape === "arrow")) return c.d;
  const i = sw / 2;
  if (c.shape === "rect") {
    const [x0, y0, x1, y1] = [i, i, Math.max(i, w - i), Math.max(i, h - i)];
    const r = Math.max(0, Math.min(radius, (x1 - x0) / 2, (y1 - y0) / 2));
    if (r <= 0) return `M${x0} ${y0}H${x1}V${y1}H${x0}Z`;
    return `M${x0 + r} ${y0}H${x1 - r}A${r} ${r} 0 0 1 ${x1} ${y0 + r}V${y1 - r}A${r} ${r} 0 0 1 ${x1 - r} ${y1}` +
      `H${x0 + r}A${r} ${r} 0 0 1 ${x0} ${y1 - r}V${y0 + r}A${r} ${r} 0 0 1 ${x0 + r} ${y0}Z`;
  }
  if (c.shape === "ellipse") {
    const [cx, cy] = [w / 2, h / 2];
    const [rx, ry] = [Math.max(0.5, w / 2 - i), Math.max(0.5, h / 2 - i)];
    return `M${cx} ${cy - ry}A${rx} ${ry} 0 1 1 ${cx} ${cy + ry}A${rx} ${ry} 0 1 1 ${cx} ${cy - ry}Z`;
  }
  return `M0 0L${w} ${h}`;
};

const safeLength = (d: string): number => {
  try {
    return getLength(d);
  } catch {
    return 0;
  }
};

export type ShapeProps = { c: ShapeContent; w: number; h: number; progress: number | null; theme: Theme; fps: number; radius: number };

export const Shape: React.FC<ShapeProps> = ({ c, w, h, progress, theme, fps, radius }) => {
  const f = useCurrentFrame();
  // a line or arrow has nothing to fill: its fill colour is the stroke's
  const lineLike = c.shape === "line" || c.shape === "arrow";
  const hasStroke = !!c.stroke || !c.fill || lineLike;
  const stroke = hasStroke ? color(theme, c.stroke || (lineLike ? c.fill : null), theme.accent) : "none";
  const sw = hasStroke ? Math.max(0, c.stroke_width ?? (c.stroke ? 6 : 8)) : 0;
  const open = c.shape === "line" || c.shape === "arrow" || (c.shape === "path" && !/z\s*$/i.test(c.d ?? ""));
  const fill = c.fill ? color(theme, c.fill, "none") : "none";
  const d = shapePath(c, w, h, sw, radius);
  const p = !c.draw
    ? 1
    : progress !== null
      ? clamp01(progress)
      : interpolate(f, [0, Math.max(1, Math.round(0.6 * fps))], [0, 1], {
          extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic),
        });
  const total = c.draw || c.shape === "arrow" ? safeLength(d) : 0;
  const shown = total * p;
  const head = c.shape === "arrow" && total > 0 ? Math.max(18, sw * 3.2) : 0;
  // the line stops short of the head's tip so its width does not poke out past the point
  const lineLen = Math.max(0, shown - head * 0.7);
  const dash = c.draw || head ? { strokeDasharray: `${lineLen} ${total + 1}`, strokeDashoffset: 0 } : {};
  let headPath: string | null = null;
  if (head && shown > 0.5) {
    try {
      const tip = getPointAtLength(d, shown);
      const t = getTangentAtLength(d, shown);
      if (!tip || !t) throw new Error("no point");
      const len = Math.hypot(t.x, t.y) || 1;
      const [ux, uy] = [t.x / len, t.y / len];
      const k = Math.min(1, shown / head); // grows in while the line is shorter than the head
      const [hl, hw] = [head * k, head * 0.62 * k];
      const bx = tip.x - ux * hl;
      const by = tip.y - uy * hl;
      headPath = `M${tip.x} ${tip.y}L${bx - uy * hw} ${by + ux * hw}L${bx + uy * hw} ${by - ux * hw}Z`;
    } catch {
      headPath = null;
    }
  }
  const fillOpacity = c.draw && fill !== "none" ? clamp01((p - 0.6) / 0.4) : 1;
  // a zero-length dash still paints its round cap as a dot
  const strokeShown = !(c.draw || head) || lineLen >= 0.5;
  if (!strokeShown && !headPath && (fill === "none" || fillOpacity <= 0)) return null;
  return (
    <svg width={Math.max(1, w)} height={Math.max(1, h)} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <path
        strokeOpacity={strokeShown ? 1 : 0}
        d={d}
        fill={open && c.shape !== "path" ? "none" : fill}
        fillOpacity={fillOpacity}
        stroke={stroke}
        strokeWidth={sw}
        strokeLinecap={head ? "butt" : "round"}
        strokeLinejoin="round"
        {...dash}
      />
      {headPath ? <path d={headPath} fill={stroke === "none" ? fill : stroke} /> : null}
    </svg>
  );
};
