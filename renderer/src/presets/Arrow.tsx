// An arrow that draws itself from one point of the box to another (straight or bent), its head riding the tip;
// an optional label (at least 28 px, on two lines if it must) sits at the tail or the head, kept inside the box.
// The SVG mask id comes from React's useId, so two arrows on screen never share one.
import React, { useId } from "react";
import { useCurrentFrame } from "remotion";
import { getLength, getPointAtLength, getTangentAtLength } from "@remotion/paths";
import { ease, fitLines, FONTS, frameOr, numOr, onGround, textWidth, themeColor, toFrames, useClip } from "@reelsmith/kit";

const MIN_LABEL = 28;

const unitPoint = (v: unknown, fallback: [number, number]): [number, number] =>
  Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === "number" && Number.isFinite(n))
    ? [Math.max(0, Math.min(1, v[0])), Math.max(0, Math.min(1, v[1]))]
    : fallback;

export default function Arrow({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const uid = "a" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const color = themeColor(theme, props?.color, "accent");
  const stroke = Math.max(2, numOr(props?.width, Math.max(6, Math.min(w, h) * 0.022)));
  const withHead = props?.head !== false;
  const headLen = withHead ? stroke * 3.4 : 0;

  // keep the head and the stroke's round caps inside the box
  const inset = Math.min(w, h) * 0.5 > headLen ? headLen * 0.6 + stroke : 0;
  const [fx, fy] = unitPoint(props?.from, [0.12, 0.85]);
  const [tx, ty] = unitPoint(props?.to, [0.85, 0.18]);
  const px = (u: number) => inset + u * Math.max(0, w - 2 * inset);
  const py = (u: number) => inset + u * Math.max(0, h - 2 * inset);
  const x0 = px(fx), y0 = py(fy), x1 = px(tx), y1 = py(ty);
  const len = Math.hypot(x1 - x0, y1 - y0);
  if (len < 1) return null;
  const bend = Math.max(-1, Math.min(1, numOr(props?.curve, 0.25)));
  // the control point stays in the box, so the whole curve does (convex hull)
  const cx = Math.max(inset, Math.min(w - inset, (x0 + x1) / 2 + (-(y1 - y0) / len) * bend * len * 0.5));
  const cy = Math.max(inset, Math.min(h - inset, (y0 + y1) / 2 + ((x1 - x0) / len) * bend * len * 0.5));
  const d = `M ${x0} ${y0} Q ${cx} ${cy} ${x1} ${y1}`;

  const at = frameOr(props?.at, 0);
  const frames = Math.max(1, toFrames(Math.max(0.05, numOr(props?.dur, 0.6)), fps));
  const p = ease(f, at, at + frames);
  const total = getLength(d);
  const tipLen = total * p;
  const tip = getPointAtLength(d, tipLen) ?? { x: x0, y: y0 };
  const tan = getTangentAtLength(d, Math.max(0.01, tipLen)) ?? { x: 1, y: 0 };
  const angle = (Math.atan2(tan.y, tan.x) * 180) / Math.PI;
  const body = Math.max(0, tipLen - headLen * 0.75); // the stroke stops under the head
  const dashed = props?.dashed === true;

  const label = String(props?.label ?? "").trim();
  const labelAt = frameOr(props?.label_at, at);
  const labelIn = ease(f, labelAt, labelAt + 8);
  let labelNode: React.ReactNode = null;
  if (label && labelIn > 0) {
    const pill = props?.label_style !== "plain";
    // never under MIN_LABEL: two lines first, then the box's width, and smaller only when even that is too narrow
    const cap = Math.max(MIN_LABEL, Math.min(56, h * 0.1, w * 0.08));
    const room = (k: number) => w * k - (pill ? cap * 0.8 : 0);
    let fitted = fitLines(label, room(0.62), cap, MIN_LABEL, FONTS.sans, 800);
    if (fitted.size < MIN_LABEL) fitted = fitLines(label, room(0.96), cap, MIN_LABEL, FONTS.sans, 800);
    const { size, lines } = fitted;
    const padX = pill ? size * 0.4 : 0;
    const padY = pill ? size * 0.16 : 0;
    const bw = Math.min(w, Math.max(...lines.map((l) => textWidth(l, size, FONTS.sans, 800))) + padX * 2 + 2);
    const bh = lines.length * size * 1.3 + padY * 2;
    const atEnd = props?.label_pos === "end";
    const anchor = atEnd ? { x: x1, y: y1 } : { x: x0, y: y0 };
    const dir = (atEnd ? getTangentAtLength(d, total - 0.01) : getTangentAtLength(d, 0.01)) ?? { x: 1, y: 0 };
    const away = atEnd ? 1 : -1; // past the head, or behind the tail
    const reach = Math.hypot(bw, bh) / 2 + stroke * 2 + (atEnd ? headLen * 0.3 : 0);
    // in line with the arrow first; beside the anchor when the box edge would push the label onto the arrow
    const spots = [
      { x: dir.x * away, y: dir.y * away },
      { x: dir.y, y: -dir.x },
      { x: -dir.y, y: dir.x },
    ].map((u) => ({ x: anchor.x + u.x * reach - bw / 2, y: anchor.y + u.y * reach - bh / 2 }));
    const inside = (s: { x: number; y: number }) => {
      const cx = Math.max(0, Math.min(w - bw, s.x));
      const cy = Math.max(0, Math.min(h - bh, s.y));
      return { x: cx, y: cy, moved: Math.hypot(cx - s.x, cy - s.y) };
    };
    const placed = spots.map(inside);
    const best = placed.find((p) => p.moved < Math.min(bw, bh) * 0.3) ?? placed.reduce((a, b) => (b.moved < a.moved ? b : a));
    const bx = best.x;
    const by = best.y;
    const ink = onGround(theme, props?.ground);
    labelNode = (
      <div style={{
        position: "absolute", left: bx, top: by, width: bw, height: bh, boxSizing: "border-box", padding: `${padY}px ${padX}px`,
        borderRadius: Math.min(bh / 2, size * 0.65 + padY), background: pill ? color : "transparent", color: pill ? "#FFFFFF" : ink.ink,
        fontFamily: FONTS.sans, fontWeight: 800, fontSize: size, lineHeight: 1.3, whiteSpace: "pre", textAlign: "center",
        opacity: labelIn, transform: `scale(${0.85 + 0.15 * labelIn})`,
      }}>{lines.join("\n")}</div>
    );
  }

  const line = { fill: "none", stroke: color, strokeWidth: stroke, strokeLinecap: "round" as const };
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {p > 0 ? (
        <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          {dashed ? (
            <>
              <defs>
                <mask id={uid} maskUnits="userSpaceOnUse" x={0} y={0} width={w} height={h}>
                  <path d={d} {...line} stroke="#FFFFFF" strokeWidth={stroke * 2} strokeDasharray={total} strokeDashoffset={total - body} />
                </mask>
              </defs>
              <path d={d} {...line} strokeDasharray={`${stroke * 2.2} ${stroke * 1.8}`} strokeLinecap="butt" mask={`url(#${uid})`} />
            </>
          ) : (
            <path d={d} {...line} strokeDasharray={total} strokeDashoffset={total - body} />
          )}
          {withHead ? (
            <polygon
              points={`0,0 ${-headLen},${-headLen * 0.58} ${-headLen * 0.72},0 ${-headLen},${headLen * 0.58}`}
              fill={color} strokeLinejoin="round" stroke={color} strokeWidth={stroke * 0.4}
              transform={`translate(${tip.x} ${tip.y}) rotate(${angle})`} opacity={Math.min(1, p * 8)}
            />
          ) : null}
        </svg>
      ) : null}
      {labelNode}
    </div>
  );
}
