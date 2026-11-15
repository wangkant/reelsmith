// Pieces the salt scenes share: the river's course, the sea slab and a salt grain.
import React from "react";
import { Slab } from "@reelsmith/kit";
import type { Pt } from "@reelsmith/kit";

export const RIVER: Pt[] = [[150, 560], [340, 640], [440, 770], [330, 900], [380, 1020], [540, 1110]];
export const SEA = { x: 560, y: 1170, w: 820, h: 230 };

export function Sea({ k = 1, level = 1 }: { k?: number; level?: number }) {
  if (k <= 0) return null;
  return (
    <div style={{ position: "absolute", inset: 0, transformOrigin: `${SEA.x}px ${SEA.y}px`, transform: `scale(${k})` }}>
      <Slab x={SEA.x} y={SEA.y + SEA.h * (1 - level) * 0.5} w={SEA.w * (0.7 + 0.3 * level)} h={SEA.h * level}
        color="#3F7DAF" depth={0.18} seed="sea" sheen={0.4} />
    </div>
  );
}

export function Crystal({ x, y, k, seed }: { x: number; y: number; k: number; seed: string }) {
  if (k <= 0) return null;
  return (
    <div style={{ position: "absolute", inset: 0, transformOrigin: `${x}px ${y}px`, transform: `scale(${k})` }}>
      <Slab x={x} y={y} w={46} h={34} shape="round" color="#F7F4EC" depth={0.4} seed={seed} />
    </div>
  );
}
