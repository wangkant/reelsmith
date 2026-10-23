// Test library component that shadows the built-in Stamp preset.
import React from "react";
import { useClip } from "@reelsmith/kit";

export default function Stamp({ props }: { props: any }) {
  const { w, h } = useClip();
  return (
    <div style={{
      position: "absolute", left: 0, top: 0, width: w, height: h, border: "8px dashed #2E8B57", color: "#2E8B57",
      display: "flex", alignItems: "center", justifyContent: "center", fontSize: 40, fontWeight: 900,
    }}>LIB {String(props?.text ?? "")}</div>
  );
}
