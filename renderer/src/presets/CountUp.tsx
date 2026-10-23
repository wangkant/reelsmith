// A number that counts from `from` to `value` starting at `at` (nothing shows before it), pops when it lands, then
// underlines itself; an optional label rises under it. The number is laid out once, at the widest text it will show,
// with right-aligned tabular digits, so it does not re-centre while digits are added.
import { useCurrentFrame } from "remotion";
import {
  decimalsOf, ease, fit, fmt, FONTS, frameOr, numOr, onGround, textWidth, themeColor, toFrames, useClip,
} from "@reelsmith/kit";

const PRE = 0.55; // prefix and suffix sizes relative to the digits
const SUF = 0.45;

export default function CountUp({ props }: { props: any }) {
  const { w, h, dur, fps, theme } = useClip();
  const f = useCurrentFrame();
  const value = numOr(props?.value, 0);
  const start = numOr(props?.from, 0);
  const decimals = Math.max(0, Math.min(4, Math.round(numOr(props?.decimals, Math.max(decimalsOf(value), decimalsOf(start))))));
  const grouping = props?.grouping !== false;
  const prefix = String(props?.prefix ?? "");
  const suffix = String(props?.suffix ?? "");
  const label = String(props?.label ?? "").trim();
  const left = props?.align === "left";
  const underline = props?.underline !== false;
  const ink = onGround(theme, props?.ground);
  const color = themeColor(theme, props?.color, "accent");

  const at = frameOr(props?.at, 0);
  // a stale zero on screen would be a false claim
  if (f < at) return null;
  const countFrames = Math.max(1, props?.dur !== undefined
    ? toFrames(numOr(props.dur, 1.2), fps)
    : Math.min(toFrames(1.4, fps), Math.max(6, Math.round((dur - at) * 0.5))));
  const land = at + countFrames;
  const t = ease(f, at, land);
  const shown = fmt(start + (value - start) * t, decimals, grouping);

  // widths at font size 1, so the digits' size can be solved for the box
  const unit = (s: string, k: number) => (s ? textWidth(s, 100 * k, FONTS.sans, 900, true) / 100 : 0);
  const digits = Math.max(unit(fmt(value, decimals, grouping), 1), unit(fmt(start, decimals, grouping), 1)) * 1.02;
  const perPx = unit(prefix, PRE) + digits + unit(suffix, SUF) + (suffix ? 0.04 : 0);
  const labelSize = label ? Math.min(72, h * 0.13, fit(label, w * 0.94, 72, FONTS.sans, 800)) : 0;
  const labelBlock = label ? labelSize * 0.7 + labelSize * 1.25 : 0;
  const barGap = 0.16; // clear of a comma's descender
  const barH = 0.04;
  // 0.9 of the width leaves room for the landing pop
  const byWidth = perPx > 0 ? (w * 0.9) / perPx : h;
  const byHeight = ((h - labelBlock) * 0.95) / (1.15 + (underline ? barGap + barH : 0));
  const size = Math.max(8, Math.min(byWidth, byHeight, 420));
  const block = size * 1.15 + (underline ? size * (barGap + barH) : 0) + labelBlock;
  const top = Math.max(0, (h - block) / 2);
  const appear = ease(f, at, at + 4);
  const pop = f >= land ? 1 + 0.06 * Math.max(0, 1 - (f - land) / 8) : 1;
  const barW = w * 0.38 * ease(f, land - 6, land + 10);
  const labelIn = ease(f, land - 8, land + 6);
  const rise = Math.max(0, Math.min(labelSize * 0.4, h - (top + block))); // never below the box

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{
        position: "absolute", left: 0, top, width: w, height: size * 1.15, lineHeight: 1.15, whiteSpace: "pre",
        textAlign: left ? "left" : "center", fontFamily: FONTS.sans, fontWeight: 900, fontSize: size, color,
        fontVariantNumeric: "tabular-nums", opacity: appear, transform: `scale(${pop})`, transformOrigin: left ? "0% 60%" : "50% 60%",
      }}>
        {/* centred: prefix and digits right-aligned in the widest text's width, so the suffix never moves and the
            prefix rides the digits; left-aligned it simply grows to the right */}
        <span style={left ? undefined : { display: "inline-block", width: (unit(prefix, PRE) + digits) * size, textAlign: "right" }}>
          {prefix ? <span style={{ fontSize: size * PRE }}>{prefix}</span> : null}
          <span>{shown}</span>
        </span>
        {suffix ? <span style={{ fontSize: size * SUF, marginLeft: size * 0.04 }}>{suffix}</span> : null}
      </div>
      {underline ? (
        <div style={{
          position: "absolute", top: top + size * (1.15 + barGap), height: Math.max(4, size * barH), width: barW,
          left: left ? 0 : (w - barW) / 2, background: color, borderRadius: size,
        }} />
      ) : null}
      {label ? (
        <div style={{
          position: "absolute", left: 0, width: w, top: top + block - labelSize * 1.25, height: labelSize * 1.25,
          textAlign: left ? "left" : "center", fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, lineHeight: 1.25,
          color: ink.ink, whiteSpace: "pre", opacity: labelIn, transform: `translateY(${(1 - labelIn) * rise}px)`,
        }}>{label}</div>
      ) : null}
    </div>
  );
}
