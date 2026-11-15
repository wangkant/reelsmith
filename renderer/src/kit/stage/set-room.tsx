// Room: a back wall with wallpaper, wainscot, windows, a shelf and frames; a plank floor or a counter; a swaying lamp.
import React from "react";
import { random } from "remotion";
import { useClip } from "../context";
import { mixColor } from "./geom";
import { useFilters, usePalette } from "./palette";
import { Leaves, PendantLamp, Plate, SetShell, spanAt, useSetUnit } from "./setbase";
import type { SetProps } from "./setbase";

export type RoomProps = SetProps & {
  /** "floor": things stand on a plank floor; "counter": on a counter top whose front fills the lower frame */
  surface?: "floor" | "counter";
  /** lamps hung from the ceiling (0 = none) */
  lamps?: number;
  /** distance between windows in px (each bay: a window, then a shelf or a frame) */
  bay?: number;
};

function Window({ x, y, ww, wh, u, seed }: { x: number; y: number; ww: number; wh: number; u: number; seed: string }) {
  const pal = usePalette();
  const { id } = useFilters();
  const frame = mixColor(pal.paper, pal.wallDeep, 0.25);
  const curtain = mixColor(pal.accent, pal.paper, 0.55);
  const hill = `M${x} ${y + wh * 0.72} Q${x + ww * 0.3} ${y + wh * 0.55} ${x + ww * 0.55} ${y + wh * 0.66} T${x + ww} ${y + wh * 0.6} L${x + ww} ${y + wh} L${x} ${y + wh} Z`;
  return (
    <g>
      <defs>
        <linearGradient id={id + "s"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={pal.sky} /><stop offset="1" stopColor={pal.haze} />
        </linearGradient>
        <linearGradient id={id + "c"} x1="0" y1="0" x2="1" y2="0">
          {[0, 0.2, 0.4, 0.6, 0.8, 1].map((o, i) => <stop key={i} offset={o} stopColor={i % 2 ? mixColor(curtain, "#000000", 0.14) : curtain} />)}
        </linearGradient>
      </defs>
      <rect x={x - 26 * u} y={y - 26 * u} width={ww + 52 * u} height={wh + 52 * u} fill={pal.shadow} opacity={0.12} transform={`translate(${10 * u} ${14 * u})`} />
      <rect x={x} y={y} width={ww} height={wh} fill={`url(#${id}s)`} />
      <path d={hill} fill={mixColor(pal.leaf, pal.haze, 0.5)} />
      <circle cx={x + ww * (0.25 + random(seed) * 0.5)} cy={y + wh * 0.6} r={ww * 0.12} fill={mixColor(pal.leaf, pal.haze, 0.25)} />
      <path d={`M${x} ${y + wh * 0.15} L${x + ww * 0.45} ${y} L${x + ww * 0.6} ${y} L${x} ${y + wh * 0.35} Z`} fill="#FFFFFF" opacity={0.22} />
      <rect x={x - 18 * u} y={y - 18 * u} width={ww + 36 * u} height={wh + 36 * u} fill="none" stroke={frame} strokeWidth={22 * u} />
      <rect x={x + ww / 2 - 7 * u} y={y} width={14 * u} height={wh} fill={frame} />
      <rect x={x} y={y + wh * 0.45} width={ww} height={14 * u} fill={frame} />
      <rect x={x - 46 * u} y={y + wh + 12 * u} width={ww + 92 * u} height={26 * u} rx={6 * u} fill={mixColor(frame, "#FFFFFF", 0.3)} />
      <path d={`M${x - 70 * u} ${y - 50 * u} L${x + ww * 0.2} ${y - 50 * u} Q${x + ww * 0.08} ${y + wh * 0.5} ${x + ww * 0.14} ${y + wh + 60 * u} L${x - 70 * u} ${y + wh + 60 * u} Z`} fill={`url(#${id}c)`} />
      <path d={`M${x + ww + 70 * u} ${y - 50 * u} L${x + ww * 0.8} ${y - 50 * u} Q${x + ww * 0.92} ${y + wh * 0.5} ${x + ww * 0.86} ${y + wh + 60 * u} L${x + ww + 70 * u} ${y + wh + 60 * u} Z`} fill={`url(#${id}c)`} />
      <rect x={x - 100 * u} y={y - 66 * u} width={ww + 200 * u} height={16 * u} rx={8 * u} fill={pal.woodDeep} />
    </g>
  );
}

function Shelf({ x, y, sw, u, seed }: { x: number; y: number; sw: number; u: number; seed: string }) {
  const pal = usePalette();
  const tones = [pal.red, pal.accent, pal.kraftDeep, pal.steel, pal.lemon, pal.woodDeep, pal.paper];
  const books: React.ReactNode[] = [];
  for (let bx = x + 20 * u, i = 0; bx < x + sw * 0.62; i++) {
    const bw = (26 + random(`${seed}w${i}`) * 22) * u, bh = (110 + random(`${seed}h${i}`) * 70) * u;
    const t = mixColor(tones[Math.floor(random(`${seed}c${i}`) * tones.length)], pal.wall, 0.25);
    books.push(<rect key={i} x={bx} y={y - bh} width={bw} height={bh} rx={3 * u} fill={t} />, <rect key={"s" + i} x={bx + bw * 0.15} y={y - bh * 0.8} width={bw * 0.7} height={8 * u} fill="#FFFFFF" opacity={0.3} />);
    bx += bw + 3 * u;
  }
  return (
    <g>
      {books}
      <path d={`M${x + sw * 0.78} ${y} q${-30 * u} ${-70 * u} 0 ${-120 * u} q${30 * u} ${50 * u} 0 ${120 * u}`} fill={pal.leaf} />
      <rect x={x + sw * 0.72} y={y - 60 * u} width={sw * 0.14} height={60 * u} rx={8 * u} fill={pal.kraft} />
      <rect x={x} y={y} width={sw} height={20 * u} rx={4 * u} fill={pal.wood} />
      <rect x={x} y={y + 20 * u} width={sw} height={14 * u} fill={pal.shadow} opacity={0.18} />
    </g>
  );
}

function Frame({ x, y, fw, fh, u }: { x: number; y: number; fw: number; fh: number; u: number }) {
  const pal = usePalette();
  return (
    <g>
      <rect x={x + 10 * u} y={y + 14 * u} width={fw} height={fh} fill={pal.shadow} opacity={0.15} />
      <rect x={x} y={y} width={fw} height={fh} fill={pal.woodDeep} />
      <rect x={x + 18 * u} y={y + 18 * u} width={fw - 36 * u} height={fh - 36 * u} fill={pal.paper} />
      <circle cx={x + fw * 0.66} cy={y + fh * 0.38} r={fw * 0.1} fill={mixColor(pal.lemon, pal.paper, 0.3)} />
      <path d={`M${x + 18 * u} ${y + fh * 0.75} Q${x + fw * 0.4} ${y + fh * 0.45} ${x + fw - 18 * u} ${y + fh * 0.7} L${x + fw - 18 * u} ${y + fh - 18 * u} L${x + 18 * u} ${y + fh - 18 * u} Z`} fill={mixColor(pal.accent, pal.paper, 0.35)} />
    </g>
  );
}

/** A room seen from the front: the back wall moves at 0.8, lamps at 0.9, the floor or counter with the action at 1. */
export function Room({ floor: fl, span, front = true, seed = "room", back, surface = "floor", lamps = 1, bay, children, ...stage }: RoomProps) {
  const { w, h } = useClip();
  const pal = usePalette();
  const u = useSetUnit();
  const { id } = useFilters();
  const floor = fl ?? h * (surface === "counter" ? 0.6 : 0.66);
  const [x0, x1] = span ?? [-w * 0.3, w * 1.3];
  const B = bay ?? w * 1.05;
  const [wx0, wx1] = spanAt(x0, x1, w, 0.8);
  const top = -h * 0.6, bottom = h * 1.6;
  const wainTop = floor - 330 * u;
  const bays: number[] = [];
  for (let x = Math.floor((wx0 - w * 0.1) / B) * B + w * 0.1; x < wx1; x += B) bays.push(x);
  const far = (
    <Plate x0={wx0} x1={wx1} y0={top} y1={floor + 300 * u}>
      <rect x={wx0} y={top} width={wx1 - wx0} height={floor + 300 * u - top} fill={pal.wall} />
      {Array.from({ length: Math.ceil((wx1 - wx0) / (64 * u)) }, (_, i) => (
        <rect key={i} x={wx0 + i * 64 * u} y={top} width={22 * u} height={wainTop - top} fill={pal.wallDeep} opacity={0.22} />
      ))}
      <rect x={wx0} y={wainTop} width={wx1 - wx0} height={floor + 300 * u - wainTop} fill={mixColor(pal.wallDeep, pal.wood, 0.25)} />
      {Array.from({ length: Math.ceil((wx1 - wx0) / (150 * u)) }, (_, i) => (
        <rect key={"p" + i} x={wx0 + i * 150 * u + 22 * u} y={wainTop + 40 * u} width={106 * u} height={220 * u} rx={6 * u} fill="none" stroke={pal.shadow} strokeOpacity={0.12} strokeWidth={4 * u} />
      ))}
      <rect x={wx0} y={wainTop - 10 * u} width={wx1 - wx0} height={20 * u} fill={pal.wood} />
      {bays.map((x, i) => (
        <g key={i}>
          <Window x={x} y={floor - 1060 * u} ww={w * 0.36} wh={600 * u} u={u} seed={`${seed}w${i}`} />
          {i % 2 ? <Frame x={x + w * 0.58} y={floor - 1000 * u} fw={w * 0.26} fh={320 * u} u={u} />
            : <Shelf x={x + w * 0.54} y={floor - 640 * u} sw={w * 0.36} u={u} seed={`${seed}s${i}`} />}
        </g>
      ))}
      {back}
    </Plate>
  );
  const lampNode = lamps > 0 ? (
    <Plate x0={x0} x1={x1} y0={top} y1={floor}>
      {Array.from({ length: lamps }, (_, i) => (
        <PendantLamp key={i} x={x0 + ((x1 - x0) * (i + 0.5)) / lamps + w * 0.12} y={top} len={-top + floor * 0.12} phase={i * 1.7} />
      ))}
    </Plate>
  ) : null;
  const [sx0, sx1] = spanAt(x0, x1, w, 1);
  const vx = w / 2, vy = floor - 900 * u;
  const planks = Array.from({ length: Math.ceil((sx1 - sx0) / (120 * u)) + 1 }, (_, i) => {
    const px = sx0 + i * 120 * u, k = (bottom - vy) / (floor - vy);
    return <line key={i} x1={px} y1={floor} x2={vx + (px - vx) * k} y2={bottom} stroke={pal.woodDeep} strokeWidth={3 * u} opacity={0.35} />;
  });
  const rows: number[] = [];
  for (let y = floor + 40 * u, g = 40 * u; y < bottom; y += g, g *= 1.25) rows.push(y);
  const surf = (
    <Plate x0={sx0} x1={sx1} y0={floor - 60 * u} y1={bottom}>
      <defs>
        <linearGradient id={id + "f"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={mixColor(pal.wood, "#FFF2D6", 0.3)} /><stop offset="0.35" stopColor={pal.wood} /><stop offset="1" stopColor={pal.woodDeep} />
        </linearGradient>
        <linearGradient id={id + "k"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={mixColor(pal.kraftLight, "#FFFFFF", 0.3)} /><stop offset="1" stopColor={pal.kraft} />
        </linearGradient>
      </defs>
      {surface === "floor" ? (
        <g>
          <rect x={sx0} y={floor} width={sx1 - sx0} height={bottom - floor} fill={`url(#${id}f)`} />
          {planks}
          {rows.map((y, i) => <rect key={i} x={sx0} y={y} width={sx1 - sx0} height={2 * u * (1 + i * 0.3)} fill={pal.woodDeep} opacity={0.18} />)}
          <path d={`M${w * 0.05} ${floor} L${w * 0.5} ${floor} L${w * 0.95} ${bottom} L${-w * 0.4} ${bottom} Z`} fill="#FFE9B8" opacity={0.13} />
          <rect x={sx0} y={floor - 46 * u} width={sx1 - sx0} height={46 * u} fill={pal.paper} />
          <rect x={sx0} y={floor - 4 * u} width={sx1 - sx0} height={10 * u} fill={pal.shadow} opacity={0.25} />
        </g>
      ) : (
        <g>
          <rect x={sx0} y={floor - 40 * u} width={sx1 - sx0} height={170 * u} fill={`url(#${id}k)`} />
          <rect x={sx0} y={floor - 40 * u} width={sx1 - sx0} height={8 * u} fill="#FFFFFF" opacity={0.5} />
          <rect x={sx0} y={floor + 130 * u} width={sx1 - sx0} height={bottom - floor} fill={pal.wood} />
          <rect x={sx0} y={floor + 130 * u} width={sx1 - sx0} height={26 * u} fill={pal.woodDeep} opacity={0.6} />
          {Array.from({ length: Math.ceil((sx1 - sx0) / (260 * u)) }, (_, i) => (
            <rect key={i} x={sx0 + i * 260 * u + 26 * u} y={floor + 200 * u} width={208 * u} height={bottom - floor} rx={10 * u}
              fill={mixColor(pal.wood, "#FFFFFF", 0.06)} stroke={pal.woodDeep} strokeOpacity={0.5} strokeWidth={4 * u} />
          ))}
        </g>
      )}
    </Plate>
  );
  const fg = front ? {
    depth: 1.35, blur: 7 * u,
    node: (
      <Plate x0={-w} x1={w * 2} y0={0} y1={h * 1.4}>
        <Leaves x={-w * 0.04} y={h * 1.06} size={430 * u} ang={30} n={8} seed={seed + "fg"} sway={2} color={mixColor(pal.leaf, "#000000", 0.25)} />
        <rect x={w * 0.97} y={-h * 0.2} width={w * 0.2} height={h * 1.6} fill={mixColor(pal.woodDeep, "#000000", 0.25)} />
      </Plate>
    ),
  } : null;
  return (
    <SetShell info={{ floor, near: surface === "counter" ? floor + 130 * u : floor, x0, x1, w, h }} stage={stage}
      planes={[{ depth: 0.8, node: far }, ...(lampNode ? [{ depth: 0.9, node: lampNode }] : [])]} surface={surf} front={fg}>
      {children}
    </SetShell>
  );
}
