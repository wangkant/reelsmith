// A rule that draws itself through a row of dated nodes; each node lights and its text arrives at its own time.
// Vertical (one point per row, text on the right) or horizontal (dates above the rule, text below).
import React from "react";
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, numOr, onGround, spread, themeColor, twoLines, useClip, withAlpha } from "@reelsmith/kit";

type Point = { when: string; text: string; at?: number; tone?: string };

/** One uniform size for every line, two-line split when it buys a clearly larger size. */
const fitAll = (texts: string[], width: number, cap: number, capTwo: number, weight: number) => {
  const one = Math.min(cap, ...texts.map((t) => fit(t, width, cap, FONTS.sans, weight)));
  const split = texts.map((t) => twoLines(t, 4));
  if (one >= cap * 0.7 || !split.some((r) => r.length > 1)) return { size: one, rows: texts.map((t) => [t]) };
  const two = Math.min(capTwo, ...split.flat().map((r) => fit(r, width, capTwo, FONTS.sans, weight)));
  return two > one * 1.15 ? { size: two, rows: split } : { size: one, rows: texts.map((t) => [t]) };
};

export default function TimelineRule({ props }: { props: any }) {
  const { w, h, dur, theme } = useClip();
  const f = useCurrentFrame();
  const pts: Point[] = (Array.isArray(props?.points) ? props.points : [])
    .filter((p: any) => p && typeof p === "object")
    .map((p: any) => ({ ...p, when: String(p.when ?? ""), text: String(p.text ?? "") }));
  if (!pts.length) return null;

  const n = pts.length;
  const ink = onGround(theme, props?.ground);
  const accent = themeColor(theme, props?.color, "accent");
  const hl = Math.round(numOr(props?.highlight, -1));
  const start = frameOr(props?.at, 0);
  const auto = spread(n, start + 8, Math.max(start + 8 + 10 * (n - 1), Math.round(dur * 0.6)));
  const ats = pts.map((p, i) => frameOr(p.at, auto[i]));
  const drawn = ease(f, start, Math.max(start + 20, Math.max(...ats) + 10));
  const hollow = ink.dark ? theme.night : theme.paper;
  const lit = (i: number) => f >= ats[i];
  const nodeColor = (i: number) => (pts[i].tone ? themeColor(theme, pts[i].tone, "accent") : accent);

  const node = (i: number, cx: number, cy: number, r: number) => {
    const on = ease(f, ats[i], ats[i] + 10);
    const big = i === hl ? 1.25 : 1;
    const c = nodeColor(i);
    return (
      <div key={`n${i}`} style={{
        position: "absolute", left: cx - r, top: cy - r, width: r * 2, height: r * 2, borderRadius: r, boxSizing: "border-box",
        background: lit(i) ? c : hollow, border: `${Math.max(3, r * 0.24)}px solid ${lit(i) ? c : ink.ink}`,
        transform: `scale(${(0.6 + 0.4 * on) * big})`,
        boxShadow: i === hl && lit(i) ? `0 0 0 ${r * 0.35 * on}px ${withAlpha(c, 0.22)}` : undefined,
      }} />
    );
  };

  if (props?.orientation === "horizontal") {
    const slotW = w / n;
    const tw = slotW * 0.92;
    const whenFit = fitAll(pts.map((p) => p.when), tw, Math.min(46, h * 0.12), Math.min(40, h * 0.09), 900);
    const textFit = fitAll(pts.map((p) => p.text), tw, Math.min(52, h * 0.11), Math.min(46, h * 0.1), 800);
    const r = Math.max(8, Math.min(26, slotW * 0.08, h * 0.05));
    const whenRows = Math.max(...whenFit.rows.map((x) => x.length));
    const textRows = Math.max(...textFit.rows.map((x) => x.length));
    const gap = r * 1.2;
    const whenH = whenRows * whenFit.size * 1.2;
    const textH = textRows * textFit.size * 1.25;
    const total = whenH + gap + 2 * r + gap + textH;
    const top = Math.max(0, (h - total) / 2);
    const ry = top + whenH + gap + r;
    const x0 = slotW / 2;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div style={{ position: "absolute", left: x0, top: ry - 4, width: (w - slotW) * drawn, height: 8, borderRadius: 4, background: ink.ink, opacity: 0.35 }} />
        {pts.map((p, i) => {
          const cx = slotW * (i + 0.5);
          const on = ease(f, ats[i], ats[i] + 10);
          return (
            <React.Fragment key={i}>
              {node(i, cx, ry, r)}
              <div style={{
                position: "absolute", left: cx - tw / 2, width: tw, top: top, height: whenH, display: "flex", flexDirection: "column",
                justifyContent: "flex-end", textAlign: "center", fontFamily: FONTS.sans, fontWeight: 900, fontSize: whenFit.size,
                lineHeight: 1.2, color: lit(i) ? nodeColor(i) : ink.muted, whiteSpace: "pre", opacity: 0.35 + 0.65 * on,
              }}>{whenFit.rows[i].join("\n")}</div>
              <div style={{
                position: "absolute", left: cx - tw / 2, width: tw, top: ry + r + gap, textAlign: "center", fontFamily: FONTS.sans,
                fontWeight: 800, fontSize: textFit.size, lineHeight: 1.25, color: ink.ink, whiteSpace: "pre", opacity: on,
                transform: `translateY(${(1 - on) * -textFit.size * 0.3}px)`,
              }}>{textFit.rows[i].join("\n")}</div>
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  const slot = h / n;
  const r = Math.max(8, Math.min(28, slot * 0.18, w * 0.035));
  const lx = r * 1.75; // room for the highlighted node's scale and ring
  const x0 = lx + r + Math.max(16, w * 0.035);
  const tw = Math.max(10, (w - x0) * 0.97);
  const room = slot * 0.9;
  const whenCap = Math.min(46, room * 0.3);
  const whenSize = Math.min(whenCap, ...pts.map((p) => (p.when ? fit(p.when, tw, whenCap, FONTS.sans, 900) : whenCap)));
  const textRoom = room - (pts.some((p) => p.when) ? whenSize * 1.2 : 0);
  const textFit = fitAll(pts.map((p) => p.text), tw, Math.min(58, textRoom / 1.2), Math.min(52, textRoom / 2.5), 800);
  const y = (i: number) => slot * (i + 0.5);
  const span = y(n - 1) - y(0);
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ position: "absolute", left: lx - 4, top: y(0), width: 8, height: span * drawn, borderRadius: 4, background: ink.ink, opacity: 0.35 }} />
      {pts.map((p, i) => {
        const on = ease(f, ats[i], ats[i] + 10);
        const whenH = p.when ? whenSize * 1.2 : 0;
        const block = whenH + textFit.rows[i].length * textFit.size * 1.2;
        return (
          <React.Fragment key={i}>
            {node(i, lx, y(i), r)}
            <div style={{
              position: "absolute", left: x0, width: tw, top: y(i) - block / 2, opacity: on,
              transform: `translateY(${(1 - on) * Math.min(14, (slot - block) / 2)}px)`,
            }}>
              {p.when ? (
                <div style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: whenSize, lineHeight: 1.2, color: nodeColor(i), whiteSpace: "pre" }}>{p.when}</div>
              ) : null}
              <div style={{
                fontFamily: FONTS.sans, fontWeight: 800, fontSize: textFit.size, lineHeight: 1.2, whiteSpace: "pre",
                color: i === hl ? nodeColor(i) : ink.ink,
              }}>{textFit.rows[i].join("\n")}</div>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}
