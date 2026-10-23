// A till receipt that prints one row per fact at its own time, then a ruled total. The paper feeds out as rows
// print; everything is sized so the finished receipt fits the clip box.
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, spread, textWidth, themeColor, useClip } from "@reelsmith/kit";

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
  const { w, h, dur, fps, theme } = useClip();
  const f = useCurrentFrame();
  const rows: Row[] = (Array.isArray(props?.rows) ? props.rows : []).filter((r: any) => r && typeof r === "object");
  const total: Total | null = props?.total && typeof props.total === "object" ? props.total : null;
  const header = text(props?.header);
  const title = text(props?.title);

  // rows (then the total) print evenly over the first two thirds of the clip unless they carry their own `at`
  const n = rows.length + (total ? 1 : 0);
  const first = Math.round(0.25 * fps);
  const auto = spread(n, first, Math.max(first + 6 * n, Math.round(dur * 0.65)));
  const ats = rows.map((r, i) => frameOr(r.at, auto[i]));
  const totalAt = total ? frameOr(total.at, auto[n - 1]) : 0;

  const topH = PAD_TOP + (header ? HEADER_H : 0) + (title ? TITLE_H : 0) + (header || title ? RULE_H : 0);
  const naturalH = topH + rows.length * ROW_H + (total ? TOTAL_H : 0) + PAD_BOTTOM + ZIG;
  const k = Math.max(0.05, Math.min(w / BASE_W, h / naturalH));
  const paperW = Math.min(w, BASE_W * k * 1.3);
  const inner = paperW - 2 * PAD_X * k;

  // one size for every row, shrunk until the widest label + value pair fits the paper
  const gap = 24 * k;
  const rowScale = Math.min(
    1,
    ...rows.map((r) => {
      const need = textWidth(text(r.label), 44 * k, FONTS.sans, 800) + textWidth(text(r.value), 56 * k, FONTS.sans, 900, true);
      return need > 0 ? (inner - gap) / need : 1;
    }),
  );
  const labelSize = 44 * k * rowScale;
  const valueSize = 56 * k * rowScale;
  // small print stays readable: 24 px (MIN_SMALL) while that is under 0.85 of the label, and always fits its row
  const small = Math.max(Math.min(28 * k, labelSize * 0.7), Math.min(MIN_SMALL, labelSize * 0.85));
  const subSize = Math.min(small, (ROW_H * k * 0.94 - labelSize * 1.15) / 1.3);
  const headerCap = Math.max(26 * k, Math.min(MIN_SMALL, labelSize * 0.85, HEADER_H * k * 0.9));
  const totalScale = total
    ? Math.min(1, (inner - gap) / Math.max(1, textWidth(text(total.label), 48 * k, FONTS.sans, 900) + textWidth(text(total.value), 76 * k, FONTS.sans, 900, true)))
    : 1;

  const printed = rows.map((_, i) => ease(f, ats[i], ats[i] + 8));
  const feed = printed.reduce((m, p, i) => (p > 0 ? Math.max(m, i + p) : m), 0);
  const totalOn = total ? ease(f, totalAt, totalAt + 10) : 0;
  const rowsShown = totalOn > 0 ? rows.length : feed;
  const paperH = (topH + PAD_BOTTOM + ZIG) * k + rowsShown * ROW_H * k + totalOn * TOTAL_H * k;
  const finalH = naturalH * k;
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
          {header ? (
            <div style={{
              height: HEADER_H * k, fontFamily: FONTS.sans, fontWeight: 600, color: theme.muted, textAlign: "center", whiteSpace: "pre",
              fontSize: fit(header, inner - 4 * k * [...header].length, headerCap, FONTS.sans, 600), letterSpacing: 4 * k, lineHeight: `${HEADER_H * k}px`,
            }}>{header}</div>
          ) : null}
          {title ? (
            <div style={{
              height: TITLE_H * k, fontFamily: FONTS.sans, fontWeight: 900, color: theme.ink, textAlign: "center", whiteSpace: "pre",
              fontSize: fit(title, inner, TITLE_SIZE * k, FONTS.sans, 900), lineHeight: `${TITLE_H * k}px`,
            }}>{title}</div>
          ) : null}
          {header || title ? <div style={{ height: RULE_H * k, borderTop: `${Math.max(2, 4 * k)}px dashed ${theme.ink}`, opacity: 0.45, marginTop: 14 * k, boxSizing: "border-box" }} /> : null}
        </div>
        {rows.map((r, i) => {
          const p = printed[i];
          if (p <= 0) return null;
          return (
            <div key={i} style={{
              position: "absolute", left: PAD_X * k, width: inner, top: (topH + i * ROW_H) * k, height: ROW_H * k,
              display: "flex", justifyContent: "space-between", alignItems: "center", gap,
              opacity: p, transform: `translateY(${(1 - p) * -18 * k}px)`, borderBottom: `${Math.max(1, 2 * k)}px dotted rgba(30,26,22,0.18)`,
              boxSizing: "border-box",
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, color: theme.ink, lineHeight: 1.15, whiteSpace: "pre" }}>{text(r.label)}</div>
                {r.sub ? (
                  <div style={{
                    fontFamily: FONTS.sans, fontWeight: 600, color: theme.muted, lineHeight: 1.3, whiteSpace: "pre",
                    // the sub line may run under the value's column only as far as the value leaves room
                    fontSize: fit(text(r.sub), inner - gap - textWidth(text(r.value), valueSize, FONTS.sans, 900, true), subSize, FONTS.sans, 600),
                  }}>{text(r.sub)}</div>
                ) : null}
              </div>
              <span style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: valueSize, color: tone(r.tone), fontVariantNumeric: "tabular-nums", whiteSpace: "pre" }}>
                {text(r.value)}
              </span>
            </div>
          );
        })}
        {total && totalOn > 0 ? (
          <div style={{ position: "absolute", left: PAD_X * k, width: inner, top: (topH + rows.length * ROW_H) * k, opacity: totalOn }}>
            <div style={{ borderTop: `${Math.max(3, 6 * k)}px double ${theme.ink}`, margin: `${12 * k}px 0 ${8 * k}px` }} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap, height: 92 * k }}>
              <span style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: 48 * k * totalScale, color: theme.ink, whiteSpace: "pre" }}>{text(total.label)}</span>
              <span style={{
                fontFamily: FONTS.sans, fontWeight: 900, fontSize: 76 * k * totalScale, color: themeColor(theme, total.tone, "accent"),
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
