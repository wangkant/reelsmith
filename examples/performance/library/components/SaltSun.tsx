// Line 2, drawn objects: the sun rises, the sea steams away into a cloud and leaves a pile of salt behind.
import React from "react";
import { useCurrentFrame } from "remotion";
import { inOut, Mist, prog, Slab, spr, Stage, Stamp, step, useClip, useCues, Wisps } from "@reelsmith/kit";
import { SEA, Sea } from "./salt/parts";

function Sun({ x, y, r, k, f }: { x: number; y: number; r: number; k: number; f: number }) {
  const { w, h } = useClip();
  if (k <= 0) return null;
  const turn = (f * 0.6) % 360;
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <g transform={`translate(${x} ${y}) scale(${k}) rotate(${turn})`}>
        {Array.from({ length: 12 }, (_, i) => (
          <line key={i} x1={0} y1={-r * 1.22} x2={0} y2={-r * (i % 2 ? 1.45 : 1.6)} stroke="#E9A93A" strokeWidth={14}
            strokeLinecap="round" transform={`rotate(${i * 30})`} />
        ))}
        <circle r={r} fill="#F2B640" />
        <circle r={r * 0.8} cx={-r * 0.12} cy={-r * 0.14} fill="#F8CB5E" />
      </g>
    </svg>
  );
}

export default function SaltSun() {
  const f = useCurrentFrame();
  const { w } = useClip();
  const { T } = useCues();
  const sf = step(f);
  const lift = prog(f, T("lifts") - 2, 40);
  const dry = inOut(prog(f, T("salt") - 6, 24));
  const cloud = spr(sf, T("sky") - 4);
  return (
    <Stage grain={0} light={0} vignette={0}>
      <Sun x={w * 0.74} y={440} r={110} k={spr(sf, T("sun") - 5)} f={f} />
      <Sea level={1 - 0.75 * lift - 0.25 * dry} k={1 - dry} />
      {[0, 1, 2].map((i) => (
        <Wisps key={i} x={SEA.x - 260 + i * 260} y={SEA.y - 60} k={prog(f, T("lifts") + i * 5, 46)} n={3} spread={90} color="#FFFFFF" />
      ))}
      <Mist x={SEA.x} y={SEA.y - 40} age={f - T("water")} dir={270} n={40} life={40} speed={1.4} seed="steam" />
      {cloud > 0 ? (
        <div style={{ position: "absolute", inset: 0, transformOrigin: "330px 520px", transform: `scale(${cloud})` }}>
          <Slab x={330} y={520} w={380} h={170} color="#FBF8F2" depth={0.12} seed="cloud" />
          <Slab x={250} y={480} w={220} h={140} color="#FFFFFF" depth={0.1} seed="cloud2" />
        </div>
      ) : null}
      {dry > 0 ? (
        <div style={{ position: "absolute", inset: 0, transformOrigin: `${SEA.x}px ${SEA.y}px`, transform: `scale(${dry})` }}>
          <Slab x={SEA.x} y={SEA.y - 20} w={420} h={170} color="#F4F0E6" depth={0.45} seed="pile" sheen={0.5} />
        </div>
      ) : null}
      <Stamp x={SEA.x} y={760} text="SALT STAYS" r={-6} size={84} color="#7E1A12" at={T("stays") - 2} seed="stays" />
    </Stage>
  );
}
