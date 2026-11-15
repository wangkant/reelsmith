// Outdoors: a sky with sun and drifting clouds, far hills or a skyline, near hills with trees, a field or a road.
import React from "react";
import { random } from "remotion";
import { useClip } from "../context";
import { mixColor, smooth } from "./geom";
import type { Pt } from "./geom";
import { useFilters, usePalette } from "./palette";
import { Clouds, Leaves, Plate, SetShell, spanAt, useSetUnit } from "./setbase";
import type { SetProps } from "./setbase";
import { useStage } from "./Stage";

export type OutdoorsProps = SetProps & {
  /** "grass" a field; "road" a road across the frame at the floor, grass below; "sand" a beach */
  ground?: "grass" | "road" | "sand";
  /** far plane: rolling hills or a city skyline */
  far?: "hills" | "skyline";
  /** the sun's place in the frame as fractions [x, y] (null = none) */
  sun?: [number, number] | null;
  /** trees on the near hills (0 = none) */
  trees?: number;
};

const ridge = (x0: number, x1: number, y: number, amp: number, seed: string, n: number, bottom: number): string => {
  const pts: Pt[] = Array.from({ length: n + 1 }, (_, i) => [x0 + ((x1 - x0) * i) / n, y - random(`${seed}${i}`) * amp]);
  return `${smooth(pts)} L${x1} ${bottom} L${x0} ${bottom} Z`;
};

function Tree({ x, y, s, seed, sway }: { x: number; y: number; s: number; seed: string; sway: number }) {
  const pal = usePalette();
  const dark = mixColor(pal.leaf, "#000000", 0.3), lit = mixColor(pal.leaf, "#FFF4C8", 0.25);
  return (
    <g transform={`rotate(${sway.toFixed(3)} ${x} ${y})`}>
      <ellipse cx={x + 30 * s} cy={y + 4 * s} rx={90 * s} ry={14 * s} fill={pal.shadow} opacity={0.2} />
      <rect x={x - 10 * s} y={y - 120 * s} width={20 * s} height={124 * s} fill={pal.woodDeep} />
      <circle cx={x} cy={y - 190 * s} r={(95 + random(seed) * 25) * s} fill={dark} />
      <circle cx={x - 40 * s} cy={y - 160 * s} r={70 * s} fill={pal.leaf} />
      <circle cx={x + 45 * s} cy={y - 175 * s} r={66 * s} fill={pal.leaf} />
      <circle cx={x - 22 * s} cy={y - 228 * s} r={58 * s} fill={lit} />
    </g>
  );
}

/** Open air: sky and sun (0.1), clouds (0.2), far hills or skyline (0.35), near hills with trees (0.6), ground with the action (1). */
export function Outdoors({ floor: fl, span, front = true, seed = "out", back, ground = "grass", far = "hills", sun = [0.76, 0.16], trees = 4,
  children, ...stage }: OutdoorsProps) {
  const { w, h } = useClip();
  const { f } = useStage();
  const pal = usePalette();
  const u = useSetUnit();
  const { id, blur } = useFilters(6, 60 * u);
  const floor = fl ?? h * 0.64;
  const [x0, x1] = span ?? [-w * 0.3, w * 1.3];
  const top = -h * 0.6, bottom = h * 1.6, horizon = floor - 230 * u;
  const [kx0, kx1] = spanAt(x0, x1, w, 0.1);
  const sky = (
    <Plate x0={kx0} x1={kx1} y0={top} y1={floor}>
      <defs>
        <linearGradient id={id + "s"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.25" stopColor={mixColor(pal.sky, "#000000", 0.08)} /><stop offset="0.85" stopColor={pal.haze} />
        </linearGradient>
      </defs>
      <rect x={kx0} y={top} width={kx1 - kx0} height={floor - top} fill={`url(#${id}s)`} />
      {sun ? (
        <g>
          <circle cx={w * sun[0]} cy={h * sun[1]} r={260 * u} fill="#FFF1C2" opacity={0.55} filter={blur} />
          <circle cx={w * sun[0]} cy={h * sun[1]} r={84 * u} fill="#FFF6DA" />
        </g>
      ) : null}
      {back}
    </Plate>
  );
  const [cx0, cx1] = spanAt(x0, x1, w, 0.2);
  const clouds = <Plate x0={cx0} x1={cx1} y0={top} y1={floor}><Clouds x0={cx0} x1={cx1} y={h * 0.2} n={6} speed={0.45} seed={seed + "c"} /></Plate>;
  const [hx0, hx1] = spanAt(x0, x1, w, 0.35);
  let farNode: React.ReactNode;
  if (far === "skyline") {
    const blocks: React.ReactNode[] = [];
    for (let x = hx0, i = 0; x < hx1; i++) {
      const bw = (90 + random(`${seed}bw${i}`) * 150) * u, bh = (160 + random(`${seed}bh${i}`) * 520) * u;
      blocks.push(<rect key={i} x={x} y={horizon - bh} width={bw} height={bh + 400 * u} fill={mixColor(pal.sky, pal.haze, 0.3 + 0.3 * random(`${seed}bc${i}`))} />);
      x += bw + 4 * u;
    }
    farNode = <Plate x0={hx0} x1={hx1} y0={top} y1={floor + 300 * u}>{blocks}</Plate>;
  } else {
    farNode = (
      <Plate x0={hx0} x1={hx1} y0={top} y1={floor + 300 * u}>
        <path d={ridge(hx0, hx1, horizon - 60 * u, 300 * u, seed + "r1", 9, floor + 300 * u)} fill={mixColor(pal.leaf, pal.haze, 0.68)} />
        <path d={ridge(hx0, hx1, horizon + 10 * u, 180 * u, seed + "r2", 12, floor + 300 * u)} fill={mixColor(pal.leaf, pal.haze, 0.5)} />
      </Plate>
    );
  }
  const [mx0, mx1] = spanAt(x0, x1, w, 0.6);
  const near = (
    <Plate x0={mx0} x1={mx1} y0={top} y1={floor + 300 * u}>
      <path d={ridge(mx0, mx1, horizon + 120 * u, 110 * u, seed + "r3", 8, floor + 300 * u)} fill={mixColor(pal.leaf, pal.haze, 0.22)} />
      {Array.from({ length: trees }, (_, i) => {
        const tx = mx0 + ((mx1 - mx0) * (i + 0.3 + random(`${seed}tx${i}`) * 0.4)) / Math.max(1, trees);
        return <Tree key={i} x={tx} y={horizon + 150 * u} s={(0.55 + random(`${seed}ts${i}`) * 0.35) * u} seed={`${seed}t${i}`} sway={Math.sin(f / 45 + i) * 0.8} />;
      })}
    </Plate>
  );
  const [sx0, sx1] = spanAt(x0, x1, w, 1);
  const g = ground === "sand" ? mixColor(pal.kraftLight, pal.haze, 0.3) : pal.leaf;
  const tufts = ground === "sand" ? null : Array.from({ length: 220 }, (_, i) => {
    const y = floor + Math.pow(random(`${seed}gy${i}`), 1.6) * (h * 1.05 - floor);
    const x = sx0 + random(`${seed}gx${i}`) * (sx1 - sx0);
    const s = (0.4 + 1.4 * (y - floor) / (h - floor)) * u;
    const lean = Math.sin(f / 30 + x * 0.01) * 4 * s;
    return <path key={i} d={`M${x - 14 * s} ${y} q${4 * s + lean} ${-30 * s} ${10 * s + lean} ${-46 * s} q${-2 * s} ${26 * s} ${8 * s} ${46 * s} q${8 * s + lean} ${-22 * s} ${20 * s + lean} ${-32 * s} q${-6 * s} ${20 * s} ${2 * s} ${32 * s} Z`}
      fill={mixColor(g, random(`${seed}gc${i}`) > 0.5 ? "#FFF2C0" : "#000000", 0.2)} />;
  });
  const roadTop = floor - 20 * u, roadH = 230 * u;
  const surf = (
    <Plate x0={sx0} x1={sx1} y0={floor - 60 * u} y1={bottom}>
      <defs>
        <linearGradient id={id + "g"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={mixColor(g, pal.haze, 0.25)} /><stop offset="0.4" stopColor={g} /><stop offset="1" stopColor={mixColor(g, "#000000", 0.3)} />
        </linearGradient>
      </defs>
      <rect x={sx0} y={floor - 50 * u} width={sx1 - sx0} height={bottom - floor + 50 * u} fill={`url(#${id}g)`} />
      {ground !== "sand" ? [0, 1, 2, 3, 4, 5].map((i) => (
        <path key={"m" + i} d={`M${sx0} ${floor + (60 + i * i * 40) * u} L${sx1} ${floor + (60 + i * i * 40) * u} L${sx1} ${floor + (60 + i * i * 40 + 20 + 10 * i * i) * u} L${sx0} ${floor + (60 + i * i * 40 + 20 + 10 * i * i) * u} Z`}
          fill={i % 2 ? "#000000" : "#FFF4C8"} opacity={0.05} />
      )) : null}
      {ground !== "sand" ? Array.from({ length: 40 }, (_, i) => {
        const fx = sx0 + random(`${seed}fx${i}`) * (sx1 - sx0), fy = floor + 280 * u + random(`${seed}fy${i}`) * (h - floor);
        const r = (5 + 9 * (fy - floor) / (h - floor)) * u;
        return <g key={"f" + i}><circle cx={fx} cy={fy} r={r} fill={[pal.paper, pal.lemon, mixColor(pal.red, pal.paper, 0.4)][i % 3]} /><circle cx={fx} cy={fy} r={r * 0.35} fill={pal.lemon} /></g>;
      }) : null}
      {tufts}
      {ground === "road" ? (
        <g>
          <rect x={sx0} y={roadTop} width={sx1 - sx0} height={roadH} fill={mixColor(pal.steel, pal.ink, 0.4)} />
          <rect x={sx0} y={roadTop} width={sx1 - sx0} height={10 * u} fill={pal.paper} opacity={0.5} />
          <rect x={sx0} y={roadTop + roadH - 10 * u} width={sx1 - sx0} height={10 * u} fill={pal.paper} opacity={0.5} />
          {Array.from({ length: Math.ceil((sx1 - sx0) / (260 * u)) }, (_, i) => (
            <rect key={i} x={sx0 + i * 260 * u} y={roadTop + roadH / 2 - 7 * u} width={140 * u} height={14 * u} fill={pal.lemon} opacity={0.85} />
          ))}
          <rect x={sx0} y={roadTop + roadH} width={sx1 - sx0} height={26 * u} fill="#000000" opacity={0.18} />
        </g>
      ) : null}
      {ground === "sand" ? Array.from({ length: 8 }, (_, i) => (
        <path key={i} d={`M${sx0} ${floor + (40 + i * i * 22) * u} q${(sx1 - sx0) / 4} ${-12 * u} ${(sx1 - sx0) / 2} 0 t${(sx1 - sx0) / 2} 0`} stroke="#FFFFFF" strokeOpacity={0.25} strokeWidth={4 * u} fill="none" />
      )) : null}
    </Plate>
  );
  const fg = front ? {
    depth: 1.4, blur: 8 * u,
    node: (
      <Plate x0={-w} x1={w * 2} y0={0} y1={h * 1.4}>
        <Leaves x={w * 0.02} y={h * 1.02} size={520 * u} ang={20} n={9} seed={seed + "fa"} sway={3} color={mixColor(pal.leaf, "#000000", 0.25)} />
        <Leaves x={w * 0.98} y={h * 1.04} size={460 * u} ang={-25} n={8} seed={seed + "fb"} sway={3} color={mixColor(pal.leaf, "#000000", 0.15)} />
      </Plate>
    ),
  } : null;
  return (
    <SetShell info={{ floor, near: ground === "road" ? roadTop + roadH * 0.75 : floor, x0, x1, w, h }} stage={stage}
      planes={[{ depth: 0.1, node: sky }, { depth: 0.2, node: clouds }, { depth: 0.35, node: farNode }, { depth: 0.6, node: near }]} surface={surf} front={fg}>
      {children}
    </SetShell>
  );
}
