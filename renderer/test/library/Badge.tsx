// Test library component: kit imports plus a relative helper in the same folder.
import React from "react";
import { useCurrentFrame } from "remotion";
import { ease, FONTS, useClip } from "@reelsmith/kit";
import { badgeColors } from "./badgeStyle";

export default function Badge({ props }: { props: any }) {
  const { w, h, theme } = useClip();
  const f = useCurrentFrame();
  const c = badgeColors(theme);
  const k = ease(f, 0, 10);
  return (
    <div style={{
      position: "absolute", left: 0, top: 0, width: w, height: h, borderRadius: h / 2, background: c.bg, color: c.fg,
      display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.sans, fontWeight: 900,
      fontSize: h * 0.45, transform: `scale(${0.8 + 0.2 * k})`,
    }}>{String(props?.text ?? "")}</div>
  );
}
