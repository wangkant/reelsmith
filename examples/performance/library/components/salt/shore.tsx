// The shore world's pieces, in world px on the action plane: the river, the sea, the sun, a cloud, rocks, salt.
import React from "react";
import { blob, Gloss, roughRect, smooth, Solid } from "@reelsmith/kit";
import type { Pt } from "@reelsmith/kit";

/** The river's course from the far left down to the shore. */
export const riverPath = (floor: number): Pt[] => [
  [-500, floor + 40], [-80, floor + 150], [300, floor + 330], [700, floor + 300], [1150, floor + 420], [1500, floor + 330], [1950, floor + 110],
];

/** The river: a dark bed, the water and a glint that runs downstream with the frame. */
export function River({ pts, f }: { pts: Pt[]; f: number }) {
  const d = smooth(pts);
  return (
    <g>
      <path d={d} stroke="#7A6648" strokeWidth={190} fill="none" strokeLinecap="round" opacity={0.35} transform="translate(8 16)" />
      <path d={d} stroke="#2F6E9E" strokeWidth={160} fill="none" strokeLinecap="round" />
      <path d={d} stroke="#4C93C4" strokeWidth={110} fill="none" strokeLinecap="round" />
      <path d={d} stroke="#BFE0F2" strokeWidth={9} fill="none" strokeLinecap="round" strokeDasharray="70 160" strokeDashoffset={-f * 6} opacity={0.75} transform="translate(0 -22)" />
      <path d={d} stroke="#E6F4FB" strokeWidth={6} fill="none" strokeLinecap="round" strokeDasharray="40 210" strokeDashoffset={-f * 7 - 90} opacity={0.6} transform="translate(0 26)" />
    </g>
  );
}

/** The sea seen across: flat to the horizon at `top`, a bay closing at x0, its shoreline at `shore` lapping on the frame. */
export function Sea({ x0, top, shore, f, glint }: { x0: number; top: number; shore: number; f: number; glint: number }) {
  const lap = Math.sin(f / 16) * 10;
  const line: Pt[] = Array.from({ length: 9 }, (_, i) => [4400 - i * ((4400 - x0 - 620) / 8), shore + lap + Math.sin(i * 1.7) * 18]);
  const edge = smooth([...line, [x0 + 300, shore - (shore - top) * 0.4], [x0 + 80, top + (shore - top) * 0.15], [x0 - 40, top]]);
  const d = `M${x0 - 40} ${top} L4400 ${top} L4400 ${line[0][1]} ${edge.replace(/^M[^C]*/, "")} Z`;
  const box: [number, number, number, number] = [x0, top, 4400 - x0, shore - top + 30];
  return (
    <g>
      <path d={smooth(line)} stroke="#B9A57E" strokeWidth={60} fill="none" opacity={0.45} transform="translate(0 18)" />
      <Solid d={d} box={box} tone="#3F86BA" under={0.1} shadow={0} rim={3} outline={0} seed="sea" />
      <Gloss d={d} at={[0.3, 0.05]} size={0.3} strength={0.35} sweep={glint} />
      <rect x={x0 + 300} y={top} width={4400 - x0} height={10} fill="#DCEFF8" opacity={0.6} />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <path key={i} d={`M${x0 + 420 + (i % 3) * 330} ${top + 50 + i * 38} q50 -14 100 0 t100 0`} stroke="#DCEFF8" strokeWidth={6} fill="none"
          strokeLinecap="round" opacity={0.55} transform={`translate(${Math.sin(f / 20 + i) * 26} 0)`} />
      ))}
      <path d={smooth(line)} stroke="#F4FAFD" strokeWidth={12} fill="none" opacity={0.8} />
    </g>
  );
}

/** A sandy beach from x0 rightwards, from `top` down past the frame. */
export function Beach({ x0, top, bottom }: { x0: number; top: number; bottom: number }) {
  const d = `M${x0 + 300} ${top} L4400 ${top} L4400 ${bottom} L${x0 - 200} ${bottom} Q${x0 - 80} ${(top + bottom) / 2} ${x0 + 300} ${top} Z`;
  return <Solid d={d} box={[x0 - 200, top, 4600 - x0, bottom - top]} tone="#E2CC9C" under={0.3} shadow={0} speckle={50} outline={0} seed="beach" />;
}

/** A low sun with a soft halo; `k` 0..1 grows it in. */
export function Sun({ x, y, k }: { x: number; y: number; k: number }) {
  if (k <= 0) return null;
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`}>
      <circle r={230} fill="#FFE29A" opacity={0.35} />
      <circle r={160} fill="#FFD36E" opacity={0.45} />
      <Solid box={[-110, -110, 220, 220]} tone="#F6B33E" shadow={0} under={0.12} gloss={0.5} rim={12}><circle r={110} /></Solid>
    </g>
  );
}

/** A cloud of round puffs; `k` 0..1 grows it. */
export function Cloud({ x, y, k, s = 1 }: { x: number; y: number; k: number; s?: number }) {
  if (k <= 0) return null;
  return (
    <g transform={`translate(${x} ${y}) scale(${k * s})`}>
      <Solid box={[-230, -150, 460, 220]} tone="#F4F6F8" shadow={0} under={0.35} rim={10}>
        <circle cx={-120} cy={10} r={80} /><circle cx={0} cy={-50} r={120} /><circle cx={120} cy={0} r={90} />
        <rect x={-200} y={0} width={400} height={70} rx={35} />
      </Solid>
    </g>
  );
}

/** A grey rock resting on y. */
export function Rock({ x, y, rx, ry, seed }: { x: number; y: number; rx: number; ry: number; seed: string }) {
  return <Solid d={blob(x, y - ry, rx, ry, seed, 11, 0.16)} box={[x - rx, y - 2 * ry, 2 * rx, 2 * ry]} tone="#8C8A84" side={12} speckle={30} seed={seed} />;
}

/** A salt crystal centred on (x, y), its size s. */
export function Crystal({ x, y, s, seed }: { x: number; y: number; s: number; seed: string }) {
  return (
    <Solid d={roughRect(x - s / 2, y - s / 2, s, s * 0.82, s * 0.18, seed, 0.03)} box={[x - s / 2, y - s / 2, s, s * 0.82]}
      tone="#F7F5EF" side={s * 0.18} gloss={0.6} rim={4} shadow={0.7} seed={seed} />
  );
}
