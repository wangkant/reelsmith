// A translucent highlighter stroke that sweeps across its own box: put the clip over a word, a line, a number.
import React from "react";
import { random, useCurrentFrame } from "remotion";
import { ease, frameOr, numOr, themeColor, toFrames, useClip } from "@reelsmith/kit";

/** A pen-like outline in px: slanted ends, long edges a few px uneven (deterministic per seed). */
const markerPath = (seed: string, w: number, h: number) => {
  const amp = Math.min(h * 0.07, 9);
  const slant = Math.min(h * 0.35, w * 0.04);
  const n = Math.max(4, Math.round(w / 70));
  const xs = Array.from({ length: n - 1 }, (_, i) => slant + ((w - 2 * slant) * (i + 1)) / n);
  const top = xs.map((x, i) => `${x}px ${amp * random(`${seed}t${i}`)}px`);
  const bottom = xs.reverse().map((x, i) => `${x}px ${h - amp * random(`${seed}b${i}`)}px`);
  return `polygon(${slant}px 0px, ${top.join(", ")}, ${w}px ${amp * 0.5}px, ${w - slant}px ${h}px, ${bottom.join(", ")}, 0px ${h - amp * 0.5}px)`;
};

export default function Highlighter({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const at = frameOr(props?.at, 0);
  const frames = Math.max(1, toFrames(Math.max(0.05, numOr(props?.dur, 0.6)), fps));
  const p = ease(f, at, at + frames);
  if (p <= 0) return null;

  const dir = ["left", "down", "up"].includes(props?.direction) ? props.direction : "right";
  const shape = ["underline", "marker"].includes(props?.shape) ? props.shape : "block";
  const dark = props?.ground === "dark";
  const color = themeColor(theme, props?.color, "gold");
  const opacity = Math.max(0, Math.min(1, numOr(props?.opacity, dark ? 0.5 : 0.42)));
  const band = shape === "underline" ? { top: h * 0.62, height: h * 0.34 } : { top: 0, height: h };
  const radius = shape === "marker" ? 0 : Math.min(12, band.height * 0.12);

  const horizontal = dir === "right" || dir === "left";
  const reach = horizontal ? { width: w * p, height: band.height } : { width: w, height: band.height * p };
  const pos: React.CSSProperties = {
    left: dir === "left" ? w - reach.width : 0,
    top: dir === "up" ? band.top + band.height - reach.height : band.top,
  };
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", mixBlendMode: dark ? "screen" : "multiply" }}>
      <div style={{ position: "absolute", ...pos, ...reach, overflow: "hidden", borderRadius: radius }}>
        {/* the stroke is laid out at full size and uncovered, so the marker edges do not stretch while it sweeps */}
        <div style={{
          position: "absolute", width: w, height: band.height, background: color, opacity,
          left: dir === "left" ? reach.width - w : 0, top: dir === "up" ? reach.height - band.height : 0,
          clipPath: shape === "marker" ? markerPath(String(props?.seed ?? "hl"), w, band.height) : undefined,
        }} />
      </div>
    </div>
  );
}
