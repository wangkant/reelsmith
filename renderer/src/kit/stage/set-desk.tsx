// Desk: a work surface seen from above under a warm lamp pool, soft props scattered round the edges, the centre clear.
import { random } from "remotion";
import { useClip } from "../context";
import { fibre, mixColor, roughRect } from "./geom";
import { useFilters, usePalette } from "./palette";
import { Leaves, Plate, SetShell, spanAt, useSetUnit } from "./setbase";
import type { SetProps } from "./setbase";
import { useStage } from "./Stage";

export type DeskProps = SetProps & {
  /** "wood" planks, "felt" a green desk mat on wood, "paper" a sheet of kraft over the desk */
  top?: "wood" | "felt" | "paper";
  /** the scattered props round the edges (false = a bare top) */
  props?: boolean;
};

function Mug({ x, y, r, f }: { x: number; y: number; r: number; f: number }) {
  const pal = usePalette();
  const { soft } = useFilters(r * 0.12);
  return (
    <g>
      <circle cx={x + r * 0.18} cy={y + r * 0.24} r={r * 1.04} fill={pal.shadow} opacity={0.3} filter={soft} />
      <path d={`M${x + r * 0.8} ${y - r * 0.35} q${r * 0.75} ${r * 0.35} 0 ${r * 0.75}`} stroke={pal.paper} strokeWidth={r * 0.2} fill="none" />
      <circle cx={x} cy={y} r={r} fill={pal.paper} />
      <circle cx={x} cy={y} r={r * 0.82} fill={mixColor(pal.woodDeep, "#000000", 0.25)} />
      <ellipse cx={x - r * 0.25} cy={y - r * 0.3} rx={r * 0.3} ry={r * 0.12} fill="#FFFFFF" opacity={0.22} transform={`rotate(-30 ${x} ${y})`} />
      {[0, 1, 2].map((i) => {
        const ph = f / 22 + i * 2.1, k = ((f / 70 + i / 3) % 1);
        return <circle key={i} cx={x + Math.sin(ph) * r * 0.5} cy={y - k * r * 2.2} r={r * (0.3 + k * 0.5)} fill="#FFFFFF" opacity={0.16 * (1 - k)} filter={soft} />;
      })}
    </g>
  );
}

function Sheet({ x, y, sw, sh, r, seed, lines = 9 }: { x: number; y: number; sw: number; sh: number; r: number; seed: string; lines?: number }) {
  const pal = usePalette();
  const { soft } = useFilters(sw * 0.02);
  return (
    <g transform={`rotate(${r} ${x + sw / 2} ${y + sh / 2})`}>
      <rect x={x + sw * 0.03} y={y + sw * 0.04} width={sw} height={sh} fill={pal.shadow} opacity={0.22} filter={soft} />
      <path d={roughRect(x, y, sw, sh, 3, seed, 0.004)} fill={pal.paper} />
      {Array.from({ length: lines }, (_, i) => (
        <path key={i} d={fibre(x + sw * 0.12, x + sw * (0.5 + 0.38 * random(`${seed}l${i}`)), y + sh * (0.16 + (0.72 * i) / lines), 1.2, `${seed}f${i}`, 4)}
          stroke={pal.ink} strokeOpacity={0.3} strokeWidth={Math.max(1.5, sw * 0.012)} fill="none" />
      ))}
    </g>
  );
}

function Pencil({ x, y, len, ang }: { x: number; y: number; len: number; ang: number }) {
  const pal = usePalette();
  const t = len * 0.06;
  return (
    <g transform={`rotate(${ang} ${x} ${y})`}>
      <rect x={x + t * 0.6} y={y + t * 0.9} width={len} height={t} fill={pal.shadow} opacity={0.2} />
      <rect x={x} y={y - t / 2} width={len * 0.86} height={t} fill={pal.lemon} />
      <rect x={x} y={y - t / 2} width={len * 0.86} height={t * 0.3} fill="#FFFFFF" opacity={0.35} />
      <path d={`M${x + len * 0.86} ${y - t / 2} L${x + len} ${y} L${x + len * 0.86} ${y + t / 2} Z`} fill={pal.kraftLight} />
      <path d={`M${x + len * 0.96} ${y - t * 0.15} L${x + len} ${y} L${x + len * 0.96} ${y + t * 0.15} Z`} fill={pal.ink} />
      <rect x={x - t * 0.8} y={y - t / 2} width={t * 0.8} height={t} rx={t * 0.2} fill={pal.red} />
    </g>
  );
}

/** A desk from above: the top (0.85) under a lamp pool, edge props on it, blurred props in front (1.25), action at 1. */
export function Desk({ floor: fl, span, front = true, seed = "desk", back, top = "wood", props = true, children, ...stage }: DeskProps) {
  const { w, h } = useClip();
  const { f } = useStage();
  const pal = usePalette();
  const u = useSetUnit();
  const { id } = useFilters();
  const floor = fl ?? h * 0.62;
  const [x0, x1] = span ?? [-w * 0.3, w * 1.3];
  const [dx0, dx1] = spanAt(x0, x1, w, 0.85);
  const y0 = -h * 0.6, y1 = h * 1.6;
  const plank = 210 * u;
  const surfaceNode = (
    <Plate x0={dx0} x1={dx1} y0={y0} y1={y1}>
      <defs>
        <radialGradient id={id + "l"} cx="0.4" cy="0.3" r="0.75">
          <stop offset="0" stopColor="#FFE7B4" stopOpacity={0.45} /><stop offset="0.5" stopColor="#FFE7B4" stopOpacity={0.08} /><stop offset="1" stopColor={pal.shadow} stopOpacity={0.35} />
        </radialGradient>
      </defs>
      <rect x={dx0} y={y0} width={dx1 - dx0} height={y1 - y0} fill={top === "paper" ? pal.kraft : pal.wood} />
      {top !== "paper" ? Array.from({ length: Math.ceil((dx1 - dx0) / plank) }, (_, i) => (
        <g key={i}>
          <rect x={dx0 + i * plank} y={y0} width={plank} height={y1 - y0} fill={mixColor(pal.wood, i % 2 ? "#000000" : "#FFF0D0", 0.06 + 0.05 * random(`${seed}p${i}`))} />
          {Array.from({ length: 5 }, (_, j) => (
            <path key={j} d={fibre(y0, y1, dx0 + i * plank + plank * (0.15 + j * 0.17), 6 * u, `${seed}g${i}-${j}`, 9)}
              transform={`rotate(90 ${dx0 + i * plank + plank * (0.15 + j * 0.17)} ${dx0 + i * plank + plank * (0.15 + j * 0.17)})`}
              stroke={pal.woodDeep} strokeOpacity={0.18} strokeWidth={2 * u} fill="none" />
          ))}
          <rect x={dx0 + i * plank} y={y0} width={3 * u} height={y1 - y0} fill={pal.woodDeep} opacity={0.5} />
        </g>
      )) : null}
      {top === "felt" ? <rect x={w * 0.08} y={h * 0.2} width={w * 0.84} height={h * 0.66} rx={24 * u} fill={mixColor(pal.leaf, pal.ink, 0.35)} /> : null}
      {props ? (
        <g>
          <Sheet x={-w * 0.12} y={h * 0.04} sw={w * 0.44} sh={w * 0.58} r={-12} seed={seed + "s1"} />
          <Sheet x={w * 0.74} y={h * 0.66} sw={w * 0.4} sh={w * 0.52} r={9} seed={seed + "s2"} lines={7} />
          <Pencil x={w * 0.62} y={h * 0.1} len={380 * u} ang={24} />
          <Mug x={w * 0.88} y={h * 0.2} r={95 * u} f={f} />
          <Leaves x={-w * 0.02} y={h * 0.88} size={260 * u} ang={50} n={8} seed={seed + "pl"} sway={1.5} />
        </g>
      ) : null}
      <rect x={dx0} y={y0} width={dx1 - dx0} height={y1 - y0} fill={`url(#${id}l)`} />
      {back}
    </Plate>
  );
  const fg = front ? {
    depth: 1.25, blur: 9 * u,
    node: (
      <Plate x0={-w} x1={w * 2} y0={-h * 0.4} y1={h * 1.4}>
        <Pencil x={-w * 0.12} y={h * 0.98} len={520 * u} ang={-28} />
        <Leaves x={w * 1.04} y={-h * 0.02} size={300 * u} ang={200} n={7} seed={seed + "fg"} sway={1.5} color={mixColor(pal.leaf, "#000000", 0.25)} />
      </Plate>
    ),
  } : null;
  return (
    <SetShell info={{ floor, near: floor, x0, x1, w, h }} stage={stage} planes={[{ depth: 0.85, node: surfaceNode }]} surface={null} front={fg}>
      {children}
    </SetShell>
  );
}
