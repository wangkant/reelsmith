// A till receipt that prints one row per fact at its own time, then a ruled total. The paper feeds out as rows
// print; everything is sized so the finished receipt fits the clip box.
import { useCurrentFrame } from "remotion";
import { breakLines, ease, fitBlock, FONTS, frameOr, spread, textWidth, themeColor, useClip } from "@reelsmith/kit";

type Row = { label: string; value: string; sub?: string; tone?: string; at?: number };
type Total = { label: string; value: string; tone?: string; at?: number };

const BASE_W = 620; // the design width every size below is drawn at
const PAD_X = 40;
const PAD_TOP = 34;
const PAD_BOTTOM = 40;
const ZIG = 16;
const HEADER_H = 40;
const TITLE_SIZE = 54;
const TITLE_H = 64;
const RULE_H = 26;
const ROW_H = 112;
const TOTAL_H = 124;
const MIN_SMALL = 24; // the header and sub-lines at the example in an 840x700 box and up

const text = (v: unknown) => (v === undefined || v === null ? "" : String(v));

export default function Receipt({ props }: { props: any }) {
  const { w, h, dur, fps, theme, width, height } = useClip();
  const f = useCurrentFrame();
  const rows: Row[] = (Array.isArray(props?.rows) ? props.rows : []).filter((r: any) => r && typeof r === "object");
  const total: Total | null = props?.total && typeof props.total === "object" ? props.total : null;
  const header = text(props?.header);
  const title = text(props?.title);
  const floor = (28 * Math.min(width, height)) / 1080;

  // rows (then the total) print evenly over the first two thirds of the clip unless they carry their own `at`
  const n = rows.length + (total ? 1 : 0);
  const first = Math.round(0.25 * fps);
  const auto = spread(n, first, Math.max(first + 6 * n, Math.round(dur * 0.65)));
  const ats = rows.map((r, i) => frameOr(r.at, auto[i]));
  const totalAt = total ? frameOr(total.at, auto[n - 1]) : 0;

  const layout = (k: number, k0 = k) => {
    // the paper keeps its first width while the rest shrinks for wrapped lines
    const paperW = Math.min(w, BASE_W * k0 * 1.3);
    const inner = paperW - 2 * PAD_X * k;
    const gap = 24 * k;
    // one size for every row, shrunk until the widest label + value pair fits the paper
    const rowScale = Math.min(
      1,
      ...rows.map((r) => {
        const need = textWidth(text(r.label), 44 * k, FONTS.sans, 800) + textWidth(text(r.value), 56 * k, FONTS.sans, 900, true);
        return need > 0 ? (inner - gap) / need : 1;
      }),
    );
    let labelSize = 44 * k * rowScale;
    let valueSize = 56 * k * rowScale;
    const valueW = (r: Row) => textWidth(text(r.value), valueSize, FONTS.sans, 900, true);
    let labels = rows.map((r) => [text(r.label)]);
    if (labelSize < floor) {
      // labels wrap onto a second line rather than shrink under the floor; values take at most 0.42 of the paper
      valueSize = Math.min(56 * k, ...rows.map((r) => {
        const v = textWidth(text(r.value), 100, FONTS.sans, 900, true) / 100;
        return v > 0 ? (inner * 0.42) / v : 56 * k;
      }));
      const room = (r: Row) => Math.max(1, inner - gap - valueW(r));
      labelSize = Math.min(...rows.map((r) =>
        fitBlock(text(r.label), room(r), Infinity, { max: 44 * k, min: floor, maxLines: 2, family: FONTS.sans, weight: 800, lineHeight: 1.15 }).size));
      labels = rows.map((r) => breakLines(text(r.label), room(r), (s) => textWidth(s, labelSize, FONTS.sans, 800), true, true));
    }
    // small print stays readable: 24 px (MIN_SMALL) while that is under 0.85 of the label, wrapping before the floor
    const small = Math.max(Math.min(28 * k, labelSize * 0.7), Math.min(MIN_SMALL, labelSize * 0.85), Math.min(floor, labelSize));
    // the sub line may run under the value's column only as far as the value leaves room
    const subs = rows.map((r) => (r.sub
      ? fitBlock(text(r.sub), inner - gap - valueW(r), Infinity, { max: small, min: Math.min(floor, small), maxLines: 3, family: FONTS.sans, weight: 600, lineHeight: 1.3 })
      : null));
    const rowHs = rows.map((r, i) => {
      const s = subs[i];
      return Math.max(ROW_H * k, (labels[i].length * labelSize * 1.15 + (s ? s.lines.length * s.size * 1.3 : 0)) / 0.86);
    });
    const headerCap = Math.max(26 * k, Math.min(MIN_SMALL, labelSize * 0.85, HEADER_H * k * 0.9));
    const head = header
      ? fitBlock(header, inner - 4 * k * [...header].length, Infinity, { max: Math.max(headerCap, floor), min: floor, maxLines: 3, family: FONTS.sans, weight: 600, lineHeight: 1.25 })
      : null;
    const headerH = head ? Math.max(HEADER_H * k, head.lines.length * head.size * 1.25) : 0;
    const tit = title ? fitBlock(title, inner, Infinity, { max: TITLE_SIZE * k, min: floor, maxLines: 3, family: FONTS.sans, weight: 900, lineHeight: 1.18 }) : null;
    const titleH = tit ? Math.max(TITLE_H * k, tit.lines.length * tit.size * 1.18) : 0;
    const topH = PAD_TOP * k + headerH + titleH + (header || title ? RULE_H * k : 0);
    const totalScale = total
      ? Math.min(1, (inner - gap) / Math.max(1, textWidth(text(total.label), 48 * k, FONTS.sans, 900) + textWidth(text(total.value), 76 * k, FONTS.sans, 900, true)))
      : 1;
    // the total's label, like the rows', wraps before it goes under the floor; its value keeps the size it has room for
    let totalValue = 76 * k * totalScale;
    let totalLabel = { size: 48 * k * totalScale, lines: [text(total?.label)] };
    if (total && totalLabel.size < floor) {
      const v = textWidth(text(total.value), 100, FONTS.sans, 900, true) / 100;
      totalValue = Math.min(76 * k, v > 0 ? (inner * 0.42) / v : 76 * k);
      totalLabel = fitBlock(text(total.label), inner - gap - v * totalValue, 92 * k,
        { max: 48 * k, min: floor, maxLines: 2, family: FONTS.sans, weight: 900, lineHeight: 1.15 });
    }
    const finalH = topH + rowHs.reduce((a, b) => a + b, 0) + (total ? TOTAL_H * k : 0) + (PAD_BOTTOM + ZIG) * k;
    return {
      k, paperW, inner, gap, labelSize, valueSize, labels, subs, rowHs, head, headerH, tit, titleH, topH, totalValue, totalLabel, finalH,
    };
  };

  const designH = PAD_TOP + (header ? HEADER_H : 0) + (title ? TITLE_H : 0) + (header || title ? RULE_H : 0) +
    rows.length * ROW_H + (total ? TOTAL_H : 0) + PAD_BOTTOM + ZIG;
  const k0 = Math.max(0.05, Math.min(w / BASE_W, h / designH));
  let L = layout(k0);
  // wrapped lines make rows taller: the rest shrinks until the receipt fits again (text stays at the floor)
  for (let i = 0; i < 4 && L.finalH > h + 0.5 && L.k > 0.05; i++) L = layout(Math.max(0.05, (L.k * h) / L.finalH), k0);
  const {
    k, paperW, inner, gap, labelSize, valueSize, labels, subs, rowHs, head, headerH, tit, titleH, topH, totalValue, totalLabel, finalH,
  } = L;
  const rowY = rowHs.map((_, i) => topH + rowHs.slice(0, i).reduce((a, b) => a + b, 0));

  const printed = rows.map((_, i) => ease(f, ats[i], ats[i] + 8));
  const feed = printed.reduce((m, p, i) => (p > 0 ? Math.max(m, i + p) : m), 0);
  const totalOn = total ? ease(f, totalAt, totalAt + 10) : 0;
  const rowsShown = totalOn > 0 ? rows.length : feed;
  const shownH = rowHs.reduce((a, rh, i) => a + rh * Math.max(0, Math.min(1, rowsShown - i)), 0);
  const paperH = topH + (PAD_BOTTOM + ZIG) * k + shownH + totalOn * TOTAL_H * k;
  const left = (w - paperW) / 2;
  const top = Math.max(0, (h - finalH) * 0.4);
  const zig = "polygon(0% 0%, 100% 0%, " +
    Array.from({ length: 41 }, (_, i) => `${100 - (i / 40) * 100}% ${i % 2 ? "100%" : `calc(100% - ${ZIG * k}px)`}`).join(", ") + ")";
  const paper = `color-mix(in srgb, ${theme.paper} 22%, #FFFFFF)`;
  const tone = (t?: string) => themeColor(theme, t, "ink");

  return (
    <div style={{ position: "absolute", left, top, width: paperW, height: paperH, filter: `drop-shadow(0 ${18 * k}px ${26 * k}px rgba(20,16,12,0.28))` }}>
      <div style={{ position: "absolute", inset: 0, background: paper, clipPath: zig, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: PAD_X * k, top: PAD_TOP * k, width: inner }}>
          {head ? (
            <div style={{
              height: headerH, fontFamily: FONTS.sans, fontWeight: 600, color: theme.muted, textAlign: "center", whiteSpace: "pre",
              fontSize: head.size, letterSpacing: 4 * k, lineHeight: `${headerH / head.lines.length}px`,
            }}>{head.lines.join("\n")}</div>
          ) : null}
          {tit ? (
            <div style={{
              height: titleH, fontFamily: FONTS.sans, fontWeight: 900, color: theme.ink, textAlign: "center", whiteSpace: "pre",
              fontSize: tit.size, lineHeight: `${titleH / tit.lines.length}px`,
            }}>{tit.lines.join("\n")}</div>
          ) : null}
          {header || title ? <div style={{ height: RULE_H * k, borderTop: `${Math.max(2, 4 * k)}px dashed ${theme.ink}`, opacity: 0.45, marginTop: 14 * k, boxSizing: "border-box" }} /> : null}
        </div>
        {rows.map((r, i) => {
          const p = printed[i];
          if (p <= 0) return null;
          const s = subs[i];
          return (
            <div key={i} style={{
              position: "absolute", left: PAD_X * k, width: inner, top: rowY[i], height: rowHs[i],
              display: "flex", justifyContent: "space-between", alignItems: "center", gap,
              opacity: p, transform: `translateY(${(1 - p) * -18 * k}px)`, borderBottom: `${Math.max(1, 2 * k)}px dotted rgba(30,26,22,0.18)`,
              boxSizing: "border-box",
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, color: theme.ink, lineHeight: 1.15, whiteSpace: "pre" }}>{labels[i].join("\n")}</div>
                {s ? (
                  <div style={{ fontFamily: FONTS.sans, fontWeight: 600, color: theme.muted, lineHeight: 1.3, whiteSpace: "pre", fontSize: s.size }}>
                    {s.lines.join("\n")}
                  </div>
                ) : null}
              </div>
              <span style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: valueSize, color: tone(r.tone), fontVariantNumeric: "tabular-nums", whiteSpace: "pre" }}>
                {text(r.value)}
              </span>
            </div>
          );
        })}
        {total && totalOn > 0 ? (
          <div style={{ position: "absolute", left: PAD_X * k, width: inner, top: topH + rowHs.reduce((a, b) => a + b, 0), opacity: totalOn }}>
            <div style={{ borderTop: `${Math.max(3, 6 * k)}px double ${theme.ink}`, margin: `${12 * k}px 0 ${8 * k}px` }} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap, height: 92 * k }}>
              <span style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: totalLabel.size, lineHeight: 1.15, color: theme.ink, whiteSpace: "pre" }}>
                {totalLabel.lines.join("\n")}
              </span>
              <span style={{
                fontFamily: FONTS.sans, fontWeight: 900, fontSize: totalValue, color: themeColor(theme, total.tone, "accent"),
                fontVariantNumeric: "tabular-nums", whiteSpace: "pre", transform: `scale(${1 + 0.06 * (1 - ease(f, totalAt + 6, totalAt + 16))})`,
                transformOrigin: "100% 50%", display: "inline-block",
              }}>{text(total.value)}</span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
