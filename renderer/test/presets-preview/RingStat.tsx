// library/components/RingStat.tsx: a ring that fills to `pct` from `at`, the percentage counting up inside it.
import { useId } from "react";
import { useCurrentFrame } from "remotion";
import { ease, fit, fmt, FONTS, frameOr, numOr, onGround, themeColor, useClip } from "@reelsmith/kit";

export default function RingStat({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame(); // frames from the clip's start
  const gid = "ring" + useId().replace(/[^A-Za-z0-9_-]/g, ""); // unique per instance: two rings never share an id
  const at = frameOr(props.at, 0); // a Time prop arrives as frames from the clip's start
  if (f < at) return null; // nothing before its moment
  const pct = Math.max(0, Math.min(100, numOr(props.pct, 0)));
  const t = ease(f, at, at + Math.round(1.2 * fps)); // 0 -> 1 over 1.2 s, then held
  const ink = onGround(theme, props.ground);
  const color = themeColor(theme, props.color, "accent");
  const label = String(props.label ?? "");
  const labelSize = label ? fit(label, w * 0.9, Math.min(64, h * 0.12), FONTS.sans, 800) : 0;
  const d = Math.min(w, h - labelSize * 1.6) * 0.92; // the ring, with room left for the label
  const sw = d * 0.12;
  const r = (d - sw) / 2;
  const len = 2 * Math.PI * r;
  const numSize = fit(`${fmt(pct)}%`, r * 1.3, r * 0.7, FONTS.sans, 900); // sized at the final text
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "relative", width: d, height: d }}>
        <svg width={d} height={d} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={color} />
              <stop offset="1" stopColor={theme.gold} />
            </linearGradient>
          </defs>
          <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke={ink.faint} strokeWidth={sw} />
          <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke={`url(#${gid})`} strokeWidth={sw} strokeLinecap="round"
            strokeDasharray={len} strokeDashoffset={len * (1 - (pct / 100) * t)} transform={`rotate(-90 ${d / 2} ${d / 2})`} />
        </svg>
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.sans,
          fontWeight: 900, fontSize: numSize, color: ink.ink, fontVariantNumeric: "tabular-nums", whiteSpace: "pre",
        }}>{`${fmt(pct * t)}%`}</div>
      </div>
      {label ? (
        <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: labelSize, color: ink.ink, marginTop: labelSize * 0.4, whiteSpace: "pre" }}>{label}</div>
      ) : null}
    </div>
  );
}
