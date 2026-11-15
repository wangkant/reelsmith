// Street: sky and a pale skyline far back, a row of shopfronts with awnings and hanging signs, a pavement and a road.
import React from "react";
import { random } from "remotion";
import { useClip } from "../context";
import { mixColor } from "./geom";
import { useFilters, usePalette } from "./palette";
import type { Palette } from "./palette";
import { pendulum } from "./motion";
import { Clouds, Leaves, Plate, SetShell, spanAt, useSetUnit } from "./setbase";
import type { SetProps } from "./setbase";
import { useStage } from "./Stage";

export type StreetProps = SetProps & {
  /** road below the pavement (false = the pavement fills the lower frame) */
  road?: boolean;
  /** awning stripes [a, b] (default the accent and paper) */
  awning?: [string, string];
};

function Shop({ x, sw, top, base, u, i, seed, pal, awning, f }: {
  x: number; sw: number; top: number; base: number; u: number; i: number; seed: string; pal: Palette; awning: [string, string]; f: number;
}) {
  const tones = [pal.wall, pal.kraftLight, mixColor(pal.red, pal.paper, 0.55), mixColor(pal.accent, pal.paper, 0.62), pal.wallDeep, mixColor(pal.sky, pal.paper, 0.5)];
  const c = tones[Math.floor(random(`${seed}t${i}`) * tones.length)];
  const floors = Math.max(2, Math.floor((base - 330 * u - top) / (230 * u)));
  const win = (fx: number, fy: number, k: string) => {
    const lit = random(k) > 0.7;
    return (
      <g key={k}>
        <rect x={fx} y={fy} width={sw * 0.2} height={140 * u} fill={lit ? "#FFE3A0" : mixColor(pal.steel, pal.sky, 0.4)} />
        <path d={`M${fx} ${fy} l${sw * 0.12} 0 l${-sw * 0.12} ${80 * u} Z`} fill="#FFFFFF" opacity={0.25} />
        <rect x={fx - 8 * u} y={fy + 140 * u} width={sw * 0.2 + 16 * u} height={12 * u} fill={mixColor(c, "#FFFFFF", 0.4)} />
        <rect x={fx} y={fy} width={sw * 0.2} height={140 * u} fill="none" stroke={mixColor(c, "#000000", 0.35)} strokeWidth={5 * u} />
      </g>
    );
  };
  const sign = pendulum(f, -999, 0, 1, 1, 2.5) * (i % 2 ? 1 : -1);
  const shopTop = base - 330 * u;
  return (
    <g>
      <rect x={x} y={top} width={sw} height={base - top} fill={c} />
      <rect x={x + sw - 18 * u} y={top} width={18 * u} height={base - top} fill="#000000" opacity={0.08} />
      <rect x={x - 6 * u} y={top - 22 * u} width={sw + 12 * u} height={26 * u} fill={mixColor(c, "#000000", 0.25)} />
      {Array.from({ length: floors }, (_, r) => [0.14, 0.4, 0.66].map((fx, j) => win(x + sw * fx, top + 60 * u + r * 230 * u, `${seed}${i}-${r}-${j}`)))}
      <rect x={x + sw * 0.06} y={shopTop + 70 * u} width={sw * 0.58} height={260 * u} fill={mixColor(pal.steel, pal.sky, 0.35)} />
      <path d={`M${x + sw * 0.06} ${shopTop + 70 * u} l${sw * 0.25} 0 l${-sw * 0.25} ${200 * u} Z`} fill="#FFFFFF" opacity={0.2} />
      <rect x={x + sw * 0.1} y={shopTop + 250 * u} width={sw * 0.5} height={80 * u} fill={mixColor(pal.kraft, pal.red, 0.2)} opacity={0.6} />
      <rect x={x + sw * 0.7} y={shopTop + 90 * u} width={sw * 0.22} height={240 * u} fill={mixColor(c, "#000000", 0.45)} />
      <circle cx={x + sw * 0.74} cy={shopTop + 220 * u} r={6 * u} fill={pal.lemon} />
      {Array.from({ length: 7 }, (_, j) => (
        <path key={j} d={`M${x + (sw * j) / 7} ${shopTop} l${sw / 7} 0 l0 ${66 * u} q${-sw / 14} ${26 * u} ${-sw / 7} 0 Z`} fill={j % 2 ? awning[1] : awning[0]} />
      ))}
      <rect x={x} y={shopTop - 8 * u} width={sw} height={14 * u} fill={pal.woodDeep} />
      <g transform={`rotate(${sign.toFixed(3)} ${x + sw - 30 * u} ${shopTop - 160 * u})`}>
        <line x1={x + sw - 30 * u} y1={shopTop - 160 * u} x2={x + sw - 30 * u} y2={shopTop - 120 * u} stroke={pal.ink} strokeWidth={3 * u} />
        <rect x={x + sw - 100 * u} y={shopTop - 120 * u} width={140 * u} height={90 * u} rx={10 * u} fill={pal.wood} />
        <rect x={x + sw - 88 * u} y={shopTop - 108 * u} width={116 * u} height={66 * u} rx={6 * u} fill="none" stroke={pal.kraftLight} strokeWidth={3 * u} opacity={0.7} />
      </g>
      <rect x={x} y={base - 20 * u} width={sw} height={20 * u} fill="#000000" opacity={0.12} />
    </g>
  );
}

/** A street seen from across the road: sky (0.15), skyline (0.35), shopfronts (0.7), pavement and road with the action (1). */
export function Street({ floor: fl, span, front = true, seed = "street", back, road = true, awning, children, ...stage }: StreetProps) {
  const { w, h } = useClip();
  const { f } = useStage();
  const pal = usePalette();
  const u = useSetUnit();
  const { id } = useFilters();
  const floor = fl ?? h * 0.58;
  const [x0, x1] = span ?? [-w * 0.3, w * 1.3];
  const top = -h * 0.6, bottom = h * 1.6;
  const aw: [string, string] = awning ?? [pal.accent, pal.paper];
  const [kx0, kx1] = spanAt(x0, x1, w, 0.15);
  const sky = (
    <Plate x0={kx0} x1={kx1} y0={top} y1={floor}>
      <defs>
        <linearGradient id={id + "s"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.3" stopColor={pal.sky} /><stop offset="1" stopColor={pal.haze} />
        </linearGradient>
      </defs>
      <rect x={kx0} y={top} width={kx1 - kx0} height={floor - top} fill={`url(#${id}s)`} />
      <Clouds x0={kx0} x1={kx1} y={h * 0.12} n={6} speed={0.35} seed={seed + "c"} />
      {back}
    </Plate>
  );
  const [lx0, lx1] = spanAt(x0, x1, w, 0.35);
  const towers: React.ReactNode[] = [];
  for (let x = lx0, i = 0; x < lx1; i++) {
    const tw = (120 + random(`${seed}kw${i}`) * 160) * u, th = (300 + random(`${seed}kh${i}`) * 520) * u;
    towers.push(<rect key={i} x={x} y={floor - 500 * u - th} width={tw} height={th + 500 * u} fill={mixColor(pal.sky, pal.haze, 0.35 + 0.25 * random(`${seed}kc${i}`))} />);
    x += tw + 6 * u;
  }
  const skyline = <Plate x0={lx0} x1={lx1} y0={top} y1={floor}>{towers}</Plate>;
  const [fx0, fx1] = spanAt(x0, x1, w, 0.7);
  const base = floor - 6 * u;
  const shops: React.ReactNode[] = [];
  for (let x = fx0, i = 0; x < fx1; i++) {
    const sw = (430 + random(`${seed}sw${i}`) * 200) * u;
    const t = base - (950 + random(`${seed}sh${i}`) * 380) * u;
    shops.push(<Shop key={i} x={x} sw={sw} top={t} base={base} u={u} i={i} seed={seed} pal={pal} awning={aw} f={f} />);
    x += sw;
  }
  const facades = <Plate x0={fx0} x1={fx1} y0={top} y1={floor + 200 * u}>{shops}</Plate>;
  const [sx0, sx1] = spanAt(x0, x1, w, 1);
  const curb = floor + 190 * u;
  const pave = mixColor(pal.wallDeep, pal.steel, 0.25);
  const asphalt = mixColor(pal.steel, pal.ink, 0.45);
  const roadH = 330 * u, nearCurb = curb + 38 * u + roadH;
  const surf = (
    <Plate x0={sx0} x1={sx1} y0={floor - 20 * u} y1={bottom}>
      <rect x={sx0} y={floor} width={sx1 - sx0} height={curb - floor} fill={pave} />
      <rect x={sx0} y={floor} width={sx1 - sx0} height={14 * u} fill="#000000" opacity={0.18} />
      {Array.from({ length: Math.ceil((sx1 - sx0) / (150 * u)) }, (_, i) => (
        <line key={i} x1={sx0 + i * 150 * u} y1={floor} x2={sx0 + i * 150 * u - 50 * u} y2={curb} stroke="#000000" strokeOpacity={0.12} strokeWidth={3 * u} />
      ))}
      <line x1={sx0} y1={floor + 90 * u} x2={sx1} y2={floor + 90 * u} stroke="#000000" strokeOpacity={0.1} strokeWidth={3 * u} />
      <rect x={sx0} y={curb} width={sx1 - sx0} height={12 * u} fill={mixColor(pave, "#FFFFFF", 0.45)} />
      <rect x={sx0} y={curb + 12 * u} width={sx1 - sx0} height={26 * u} fill={mixColor(pave, "#000000", 0.3)} />
      {road ? (
        <g>
          <rect x={sx0} y={curb + 38 * u} width={sx1 - sx0} height={roadH} fill={asphalt} />
          <rect x={sx0} y={curb + 38 * u} width={sx1 - sx0} height={50 * u} fill="#000000" opacity={0.15} />
          {Array.from({ length: Math.ceil((sx1 - sx0) / (300 * u)) }, (_, i) => (
            <rect key={i} x={sx0 + i * 300 * u} y={curb + 38 * u + roadH * 0.52} width={170 * u} height={16 * u} fill={pal.paper} opacity={0.75} />
          ))}
          {Array.from({ length: 60 }, (_, i) => (
            <circle key={"g" + i} cx={sx0 + random(`${seed}gx${i}`) * (sx1 - sx0)} cy={curb + 60 * u + random(`${seed}gy${i}`) * (roadH - 40 * u)} r={(3 + random(`${seed}gr${i}`) * 5) * u}
              fill={random(`${seed}gc${i}`) > 0.5 ? "#FFFFFF" : "#000000"} opacity={0.08} />
          ))}
          <rect x={sx0} y={nearCurb} width={sx1 - sx0} height={30 * u} fill={mixColor(pave, "#FFFFFF", 0.45)} />
          <rect x={sx0} y={nearCurb + 30 * u} width={sx1 - sx0} height={bottom - nearCurb} fill={mixColor(pave, "#FFFFFF", 0.08)} />
          {Array.from({ length: Math.ceil((sx1 - sx0) / (230 * u)) + 4 }, (_, i) => (
            <line key={"t" + i} x1={sx0 + i * 230 * u} y1={nearCurb + 30 * u} x2={sx0 + i * 230 * u + (sx0 + i * 230 * u - w / 2) * 0.6} y2={bottom} stroke="#000000" strokeOpacity={0.1} strokeWidth={4 * u} />
          ))}
          {[1, 2, 3, 4].map((i) => <rect key={"r" + i} x={sx0} y={nearCurb + 30 * u + i * i * 34 * u} width={sx1 - sx0} height={4 * u} fill="#000000" opacity={0.08} />)}
          <rect x={sx0} y={nearCurb + 30 * u} width={sx1 - sx0} height={40 * u} fill="#000000" opacity={0.12} />
        </g>
      ) : <rect x={sx0} y={curb + 38 * u} width={sx1 - sx0} height={bottom - curb} fill={mixColor(pave, "#000000", 0.08)} />}
    </Plate>
  );
  const fg = front ? {
    depth: 1.4, blur: 8 * u,
    node: (
      <Plate x0={-w} x1={w * 2} y0={-h * 0.4} y1={h * 1.4}>
        <rect x={w * 0.97} y={-h * 0.4} width={60 * u} height={h * 1.8} fill={mixColor(pal.ink, pal.steel, 0.2)} />
        <rect x={w * 0.97} y={-h * 0.4} width={14 * u} height={h * 1.8} fill="#FFFFFF" opacity={0.18} />
        <Leaves x={w * 0.02} y={h * 1.08} size={400 * u} ang={25} n={9} seed={seed + "fg"} sway={2} color={mixColor(pal.leaf, "#000000", 0.2)} />
      </Plate>
    ),
  } : null;
  return (
    <SetShell info={{ floor, near: road ? curb + 38 * u + roadH * 0.7 : floor, x0, x1, w, h }} stage={stage}
      planes={[{ depth: 0.15, node: sky }, { depth: 0.35, node: skyline }, { depth: 0.7, node: facades }]} surface={surf} front={fg}>
      {children}
    </SetShell>
  );
}
