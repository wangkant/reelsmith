// Test library component: a clipping window with a row inside it, a row half under its edge and a row outside it.
import React from "react";
import { FONTS } from "@reelsmith/kit";

export default function Window() {
  const row = (top: number, text: string) => (
    <div style={{ position: "absolute", left: 10, top, fontFamily: FONTS.sans, fontSize: 40, lineHeight: 1, whiteSpace: "pre" }}>{text}</div>
  );
  return (
    <div style={{ position: "absolute", left: 100, top: 100, width: 300, height: 100, overflow: "hidden", background: "#fff" }}>
      {row(10, "shown")}
      {row(80, "half")}
      {row(300, "hidden")}
    </div>
  );
}
