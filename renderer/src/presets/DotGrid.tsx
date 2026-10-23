// "N out of M": a grid of dots that appear, then light one by one up to `lit`, with a live count and labels that
// show only once the lighting starts (a count of 0 before it would be a false claim).
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, numOr, onGround, textWidth, themeColor, toFrames, useClip } from "@reelsmith/kit";

/** Columns that give the largest cells for `total` dots in a w x h area. Whole rows win unless a ragged layout gives
 *  much bigger dots, and rows of ten (tenths at a glance) win among them, so 100 dots are 10 x 10 when that fits. */
const bestColumns = (total: number, w: number, h: number) => {
  let best = 1;
  let bestScore = 0;
  for (let c = 1; c <= total; c++) {
    const cell = Math.min(w / c, h / Math.ceil(total / c));
    const score = cell * (total % c !== 0 ? 0.6 : c === 10 ? 1.12 : 1);
    if (score > bestScore + 1e-6) {
      bestScore = score;
      best = c;
    }
  }
  return best;
};

export default function DotGrid({ props }: { props: any }) {
  const { w, h, dur, fps, theme } = useClip();
  const f = useCurrentFrame();
  const total = Math.max(1, Math.min(400, Math.round(numOr(props?.total, 10))));
  const lit = Math.max(0, Math.min(total, Math.round(numOr(props?.lit, 0))));
  const labelLit = String(props?.label_lit ?? "").trim();
  const labelRest = String(props?.label_rest ?? "").trim();
  const counter = props?.counter !== false;
  const square = props?.shape === "square";
  const ink = onGround(theme, props?.ground);
  const accent = themeColor(theme, props?.color, "accent");

  const at = frameOr(props?.at, 8);
  const lightFrames = Math.max(1, props?.dur !== undefined ? toFrames(numOr(props.dur, 1.5), fps) : Math.max(toFrames(0.7, fps), Math.round(dur * 0.55) - at));
  const litNow = Math.round(lit * ease(f, at, at + lightFrames));
  const legendIn = ease(f, at, at + 6);

  // legend: "● 37 label_lit" and "● 63 label_rest", fitted at their widest counts; laid out from the start
  const litLine = labelLit || counter ? `● ${lit} ${labelLit}`.trim() : "";
  const restLine = labelRest ? `● ${total} ${labelRest}` : "";
  const lines = [litLine, restLine].filter(Boolean);
  const cap = Math.min(64, h * 0.11);
  const legendSize = lines.length ? Math.min(cap, ...lines.map((l) => fit(l, w * 0.98, cap, FONTS.sans, 900))) : 0;
  const legendH = lines.length ? lines.length * legendSize * 1.3 + legendSize * 0.5 : 0;

  const gridH = Math.max(1, h - legendH);
  const cols = Math.max(1, Math.min(total, Math.round(numOr(props?.columns, bestColumns(total, w, gridH)))));
  const rows = Math.ceil(total / cols);
  const cell = Math.min(w / cols, gridH / rows);
  const dot = cell * 0.72;
  const gx = (w - cell * cols) / 2;
  const gy = Math.max(0, (gridH - cell * rows) / 2);
  const step = Math.min(0.4, 12 / total); // all dots appear within ~12 frames whatever the count
  const appear0 = Math.min(0, at - 14);
  // the legend lines up with the grid's first column when it fits there
  const legendW = Math.max(0, ...lines.map((l) => textWidth(l, legendSize, FONTS.sans, 900, true)));
  const legendX = Math.max(0, Math.min(gx + (cell - dot) / 2, w - legendW));

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {Array.from({ length: total }, (_, i) => {
        const on = i < litNow;
        const r = Math.floor(i / cols);
        const c = i % cols;
        const a = ease(f, appear0 + i * step, appear0 + i * step + 8);
        return (
          <div key={i} style={{
            position: "absolute", left: gx + c * cell + (cell - dot) / 2, top: gy + r * cell + (cell - dot) / 2, width: dot, height: dot,
            borderRadius: square ? dot * 0.18 : dot / 2, background: on ? accent : ink.faint, transform: `scale(${a * (on ? 1.06 : 1)})`,
          }} />
        );
      })}
      {lines.length && legendIn > 0 ? (
        <div style={{
          position: "absolute", left: legendX, width: w - legendX, top: h - lines.length * legendSize * 1.3, fontFamily: FONTS.sans,
          fontWeight: 900, lineHeight: 1.3, whiteSpace: "pre", opacity: legendIn,
        }}>
          {litLine ? (
            <div style={{ fontSize: legendSize, color: ink.ink }}>
              <span style={{ color: accent }}>● {litNow}</span>{labelLit ? ` ${labelLit}` : ""}
            </div>
          ) : null}
          {restLine ? (
            <div style={{ fontSize: legendSize, color: ink.muted }}>● {total - litNow} {labelRest}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
