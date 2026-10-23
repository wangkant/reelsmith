// A paper price tag that drops in on its string and swings to rest; the old price gets struck through at strike_at.
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, springAt, themeColor, useClip } from "@reelsmith/kit";

export default function PriceTag({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const price = String(props.price ?? "");
  const old = props.old ? String(props.old) : "";
  const label = props.label ? String(props.label) : "";
  const at = frameOr(props.at, 0);
  const strikeAt = frameOr(props.strike_at, at + Math.round(0.7 * fps));
  const color = themeColor(theme, props.color, "accent");
  if (f < at) return null;

  // tag 1.5:1 under a string; small enough that a 10 degree swing stays in the box
  const stringH = h * 0.14;
  const tagW = Math.min(w * 0.8, (h - stringH) * 0.86 * 1.5);
  const tagH = tagW / 1.5;
  const padX = tagW * 0.08;
  const inner = tagW - padX * 2;
  const hole = tagW * 0.04;
  const contentTop = hole * 3 + tagH * 0.04;
  const room = tagH - contentTop - tagH * 0.07;

  // the small lines get a fixed share of the tag, the price everything left
  const labelSize = label ? fit(label, inner, tagH * 0.14, FONTS.sans, 700) : 0;
  const oldSize = old ? fit(old, inner * 0.7, tagH * 0.15, FONTS.sans, 700) : 0;
  const priceSize = fit(price, inner, Math.max(10, (room - labelSize * 1.2 - oldSize * 1.2) / 1.1), FONTS.sans, 900);

  const drop = springAt(f, at, { fps, damping: 12, stiffness: 140 });
  const swing = (1 - springAt(f, at, { fps, damping: 5, stiffness: 90 })) * 10;
  const strike = ease(f, strikeAt, strikeAt + 8);

  return (
    <div style={{
      position: "absolute", left: (w - tagW) / 2, top: (h - stringH - tagH) / 2, width: tagW, height: stringH + tagH,
      transform: `translateY(${(1 - drop) * -h * 0.25}px) rotate(${swing}deg)`, transformOrigin: "50% 0%", opacity: Math.min(1, drop * 2),
    }}>
      <div style={{ position: "absolute", left: tagW / 2 - 1.5, top: 0, width: 3, height: stringH + hole * 2, background: theme.ink, opacity: 0.6 }} />
      <div style={{
        position: "absolute", left: 0, top: stringH, width: tagW, height: tagH, boxSizing: "border-box", padding: `${contentTop}px ${padX}px ${tagH * 0.07}px`,
        background: "#FFFDF6", borderRadius: tagW * 0.05, border: `${Math.max(2, tagW * 0.008)}px solid ${theme.ink}`,
        boxShadow: "0 18px 40px rgba(30,26,22,0.25)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{ position: "absolute", left: tagW / 2 - hole, top: hole, width: hole * 2, height: hole * 2, borderRadius: hole, background: theme.paper, border: `2px solid ${theme.ink}`, boxSizing: "border-box" }} />
        {label ? <div style={{ fontFamily: FONTS.sans, fontWeight: 700, fontSize: labelSize, lineHeight: 1.2, color: theme.muted, whiteSpace: "pre" }}>{label}</div> : null}
        {old ? (
          <div style={{ position: "relative", fontFamily: FONTS.sans, fontWeight: 700, fontSize: oldSize, lineHeight: 1.2, color: theme.muted, whiteSpace: "pre" }}>
            {old}
            <div style={{ position: "absolute", left: -4, top: "52%", height: Math.max(3, oldSize * 0.09), width: `calc(${strike * 100}% + ${8 * strike}px)`, background: color }} />
          </div>
        ) : null}
        <div style={{ fontFamily: FONTS.sans, fontWeight: 900, fontSize: priceSize, lineHeight: 1.1, color, whiteSpace: "pre", fontVariantNumeric: "tabular-nums" }}>{price}</div>
      </div>
    </div>
  );
}
