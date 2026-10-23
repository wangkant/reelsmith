// Bars that grow one after another, each with its value counting up and its label; one bar is highlighted.
// Three layouts, every text fitted to the box and no label larger than the values: columns; rows with labels in a
// left column; rows with label and value on a line above each bar (narrow boxes). "auto" keeps columns unless a row
// layout reads clearly larger.
import React from "react";
import { useCurrentFrame } from "remotion";
import {
  decimalsOf, ease, fit, fmt, FONTS, frameOr, numOr, onGround, textWidth, themeColor, toFrames, twoLines, useClip,
} from "@reelsmith/kit";

type Item = { label: string; value: number; display?: string; tone?: string; at?: number };

const GROW = 24; // frames a bar takes to reach its height
const LABEL_K = 0.85; // a row label next to its value, relative to the value's size

/** Width of `s` at font size 1. */
const unitW = (s: string, weight: number, tabular = false) => (s ? textWidth(s, 100, FONTS.sans, weight, tabular) / 100 : 0);

export default function BarCompare({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const items: Item[] = (Array.isArray(props?.items) ? props.items : [])
    .filter((it: any) => it && typeof it === "object")
    .map((it: any) => ({ ...it, label: String(it.label ?? ""), value: numOr(it.value, 0) }));
  if (!items.length) return null;

  const n = items.length;
  const unit = String(props?.unit ?? "");
  const decimals = Math.max(0, Math.min(4, Math.round(numOr(props?.decimals, Math.max(...items.map((it) => decimalsOf(it.value)))))));
  const top = Math.max(...items.map((it) => Math.abs(it.value)));
  const max = numOr(props?.max, 0) > 0 ? numOr(props.max, 0) : top || 1;
  const hl = Math.round(numOr(props?.highlight, n - 1));
  const ink = onGround(theme, props?.ground);
  const accent = themeColor(theme, props?.color, "accent");
  const plain = ink.dark ? "rgba(255,255,255,0.5)" : theme.muted;
  const first = frameOr(props?.at, 6);
  const stagger = toFrames(Math.max(0, numOr(props?.stagger, 0.33)), fps);
  const ats = items.map((it, i) => frameOr(it.at, first + i * stagger));
  const grow = ats.map((a) => ease(f, a, a + GROW));
  const valueText = (it: Item, g: number) => (it.display ? String(it.display) : `${fmt(it.value * g, decimals)}${unit}`);
  const colorOf = (it: Item, i: number) => (it.tone ? themeColor(theme, it.tone, "accent") : i === hl ? accent : plain);
  const textColorOf = (it: Item, i: number) => (it.tone || i === hl ? colorOf(it, i) : ink.ink);
  const finals = items.map((it) => valueText(it, 1));
  const labelIn = (i: number) => ease(f, ats[i] - 4, ats[i] + 6);

  // ---- columns: labels fit their own bar's width, so neighbours keep a whole gap between them
  const cols = (() => {
    const gap = Math.max(18, w * (n > 4 ? 0.04 : 0.06));
    const bw = Math.max(1, (w - gap * (n - 1)) / n);
    const valueSize = Math.min(68, h * 0.12, ...finals.map((t) => fit(t, bw + gap * 0.5, 68, FONTS.sans, 900)));
    const cap = Math.min(52, h * 0.1, valueSize);
    const one = Math.min(cap, ...items.map((it) => fit(it.label, bw, cap, FONTS.sans, 800)));
    const split = items.map((it) => twoLines(it.label, 3));
    const two = Math.min(cap, ...split.flat().map((r) => fit(r, bw, cap, FONTS.sans, 800)));
    const useTwo = two > one * 1.2 && split.some((r) => r.length > 1);
    const labelSize = useTwo ? two : one;
    return { gap, bw, valueSize, labelSize, rows: useTwo ? split : items.map((it) => [it.label]), score: Math.min(valueSize, labelSize) };
  })();

  // ---- rows, labels in a left column
  const side = (() => {
    const rowH = h / n;
    const colMax = w * 0.34;
    const valueSize = Math.min(rowH * 0.42, 64, ...finals.map((t) => fit(t, w * 0.3, 64, FONTS.sans, 900)));
    const labelSize = Math.min(rowH * 0.36, 52, valueSize, ...items.map((it) => fit(it.label, colMax, 52, FONTS.sans, 800)));
    return { rowH, colMax, valueSize, labelSize, score: Math.min(valueSize, labelSize) };
  })();

  // ---- rows, label left and value right on a line above each full-width bar
  const stack = (() => {
    const rowH = h / n;
    const gap = Math.max(16, w * 0.03);
    const per = Math.max(...items.map((it, i) => LABEL_K * unitW(it.label, 800) + unitW(finals[i], 900, true)));
    const valueSize = Math.max(1, Math.min(64, rowH / 2.6, per > 0 ? (w - gap) / per : 64));
    const labelSize = valueSize * LABEL_K;
    return { rowH, gap, valueSize, labelSize, score: Math.min(valueSize, labelSize) };
  })();

  const mode = props?.orientation === "vertical" ? "cols"
    : props?.orientation === "horizontal" ? (side.score >= stack.score ? "side" : "stack")
    : cols.score >= 0.85 * Math.max(side.score, stack.score) ? "cols"
    : side.score >= stack.score ? "side" : "stack";

  if (mode === "stack") {
    const { rowH, valueSize, labelSize } = stack;
    const lineH = valueSize * 1.25;
    const thick = Math.max(6, Math.min(valueSize * 0.9, rowH - lineH - valueSize * 0.15 - rowH * 0.18));
    const block = lineH + valueSize * 0.15 + thick;
    // rows stay together (centred) in a tall box rather than spreading to its ends
    const pitch = Math.min(rowH, block * 1.7);
    const y0 = (h - pitch * n) / 2;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        {items.map((it, i) => {
          const g = grow[i];
          const y = y0 + pitch * i + (pitch - block) / 2;
          const len = Math.max(it.value ? 4 : 0, (Math.abs(it.value) / max) * w * g);
          return (
            <React.Fragment key={i}>
              <div style={{
                position: "absolute", left: 0, top: y, width: w, height: lineH, display: "flex", alignItems: "baseline",
                justifyContent: "space-between", whiteSpace: "pre", fontFamily: FONTS.sans, lineHeight: `${lineH}px`,
              }}>
                <span style={{ fontWeight: 800, fontSize: labelSize, color: ink.ink, opacity: labelIn(i) }}>{it.label}</span>
                <span style={{ fontWeight: 900, fontSize: valueSize, color: textColorOf(it, i), fontVariantNumeric: "tabular-nums", opacity: g }}>
                  {valueText(it, g)}
                </span>
              </div>
              <div style={{
                position: "absolute", left: 0, top: y + lineH + valueSize * 0.15, width: len, height: thick, background: colorOf(it, i),
                borderRadius: `0 ${thick * 0.18}px ${thick * 0.18}px 0`,
              }} />
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  if (mode === "side") {
    const { rowH, colMax, valueSize, labelSize } = side;
    const labelW = Math.min(colMax, Math.max(...items.map((it) => textWidth(it.label, labelSize, FONTS.sans, 800))));
    const valueW = Math.max(...finals.map((t) => textWidth(t, valueSize, FONTS.sans, 900, true)));
    const gap = Math.max(12, w * 0.025);
    const barX = labelW + gap;
    const room = Math.max(0, w - barX - gap - valueW * 1.05);
    const thick = rowH * 0.5;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div style={{ position: "absolute", left: barX - 2, top: 0, width: 4, height: h, background: ink.ink, opacity: 0.5 }} />
        {items.map((it, i) => {
          const g = grow[i];
          const len = Math.max(it.value ? 4 : 0, (Math.abs(it.value) / max) * room * g);
          const cy = rowH * (i + 0.5);
          return (
            <React.Fragment key={i}>
              <div style={{
                position: "absolute", left: 0, width: labelW, top: cy - labelSize * 0.65, height: labelSize * 1.3, textAlign: "right",
                fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, lineHeight: 1.3, color: ink.ink, whiteSpace: "pre",
                opacity: labelIn(i),
              }}>{it.label}</div>
              <div style={{ position: "absolute", left: barX, top: cy - thick / 2, width: len, height: thick, background: colorOf(it, i), borderRadius: `0 ${thick * 0.18}px ${thick * 0.18}px 0` }} />
              <div style={{
                position: "absolute", left: barX + len + gap, top: cy - valueSize * 0.62, height: valueSize * 1.25, lineHeight: 1.25,
                fontFamily: FONTS.sans, fontWeight: 900, fontSize: valueSize, color: textColorOf(it, i), whiteSpace: "pre",
                fontVariantNumeric: "tabular-nums", opacity: g,
              }}>{valueText(it, g)}</div>
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  const { gap, bw, valueSize, labelSize, rows } = cols;
  const labelRows = Math.max(...rows.map((r) => r.length));
  const labelArea = labelRows * labelSize * 1.2 + labelSize * 0.45;
  const valueArea = valueSize * 1.25 + valueSize * 0.25;
  const base = h - labelArea;
  const maxBar = Math.max(0, base - valueArea);
  // a text centred over its bar, nudged inwards when it would cross the box edge
  const over = (cx: number, tw: number) => {
    const width = Math.min(w, tw + 2);
    return { left: Math.max(0, Math.min(w - width, cx - width / 2)), width };
  };
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ position: "absolute", left: 0, top: base - 2, width: w, height: 4, background: ink.ink, opacity: 0.5 }} />
      {items.map((it, i) => {
        const g = grow[i];
        const x = i * (bw + gap);
        const bar = Math.max(it.value ? 4 : 0, (Math.abs(it.value) / max) * maxBar * g);
        const cx = x + bw / 2;
        const vBox = over(cx, textWidth(finals[i], valueSize, FONTS.sans, 900, true));
        const lBox = over(cx, Math.max(...rows[i].map((r) => textWidth(r, labelSize, FONTS.sans, 800))));
        return (
          <React.Fragment key={i}>
            <div style={{ position: "absolute", left: x, top: base - bar, width: bw, height: bar, background: colorOf(it, i), borderRadius: `${Math.min(14, bw * 0.08)}px ${Math.min(14, bw * 0.08)}px 0 0` }} />
            <div style={{
              position: "absolute", ...vBox, top: base - bar - valueArea + valueSize * 0.1, height: valueSize * 1.25,
              lineHeight: 1.25, textAlign: "center", fontFamily: FONTS.sans, fontWeight: 900, fontSize: valueSize, whiteSpace: "pre",
              color: textColorOf(it, i), opacity: g, fontVariantNumeric: "tabular-nums",
            }}>{valueText(it, g)}</div>
            <div style={{
              position: "absolute", ...lBox, top: base + labelSize * 0.45, textAlign: "center",
              fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, lineHeight: 1.2, color: ink.ink, whiteSpace: "pre",
              opacity: labelIn(i),
            }}>{rows[i].join("\n")}</div>
          </React.Fragment>
        );
      })}
    </div>
  );
}
