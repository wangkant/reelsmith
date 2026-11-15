// Test library component: one row per voice line useClip() hands it, as "i from to text".
import React from "react";
import { FONTS, useClip } from "@reelsmith/kit";
import type { ClipLine } from "@reelsmith/kit";

export default function Lines() {
  const { lines } = useClip();
  return (
    <>
      {lines.map((ln: ClipLine, k: number) => (
        <div key={ln.i} style={{ position: "absolute", left: 40, top: 200 + k * 60, fontFamily: FONTS.sans, fontSize: 40, whiteSpace: "pre" }}>
          {`${ln.i} ${ln.from} ${ln.to} ${ln.text}`}
        </div>
      ))}
      {lines.length === 0 ? <div style={{ position: "absolute", left: 40, top: 200, fontFamily: FONTS.sans, fontSize: 40 }}>none</div> : null}
    </>
  );
}
