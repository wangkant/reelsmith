// Grounds: the paper or wall behind the action and the table top that fills the lower frame.
import { random } from "remotion";
import { useClip } from "../context";
import { fibre, mixColor } from "./geom";
import { useFilters, usePalette, useUnit } from "./palette";
import { useStage } from "./Stage";

type Span = { pad?: number };

const box = (w: number, h: number, pad: number) => ({ x: -w * pad, y: -h * pad, W: w * (1 + 2 * pad), H: h * (1 + 2 * pad) });

/** Kraft paper: a static fibre texture, loose fibres and a soft warm light. `pad` (fraction of the frame) is drawn
 *  beyond every edge so the camera and drift never show its border. */
export function KraftGround({ color, fibres = 170, seed = "kraft", pad = 0.25 }: Span & { color?: string; fibres?: number; seed?: string }) {
  const { w, h } = useClip();
  const pal = usePalette();
  const { id } = useFilters();
  const base = color ?? pal.kraft;
  const b = box(w, h, pad);
  const lines = Array.from({ length: fibres }, (_, i) => {
    const x = b.x + random(`${seed}x${i}`) * b.W, y = b.y + random(`${seed}y${i}`) * b.H;
    const a = random(`${seed}a${i}`) * Math.PI, l = 10 + random(`${seed}l${i}`) * 34;
    const light = random(`${seed}c${i}`) > 0.5;
    return <path key={i} d={`M${x.toFixed(1)} ${y.toFixed(1)} q${(Math.cos(a) * l * 0.5 + 4).toFixed(1)} ${(Math.sin(a) * l * 0.5 - 3).toFixed(1)} ${(Math.cos(a) * l).toFixed(1)} ${(Math.sin(a) * l).toFixed(1)}`}
      stroke={light ? mixColor(base, "#FFFFFF", 0.45) : mixColor(base, "#000000", 0.38)} strokeWidth={1.2} fill="none" opacity={0.35} />;
  });
  return (
    <svg width={b.W} height={b.H} viewBox={`${b.x} ${b.y} ${b.W} ${b.H}`} style={{ position: "absolute", left: b.x, top: b.y }}>
      <defs>
        <filter id={id + "t"} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={3} />
          <feColorMatrix values="0 0 0 0 0.25  0 0 0 0 0.16  0 0 0 0 0.06  0 0 0 0.5 0" />
        </filter>
        <radialGradient id={id + "v"} cx="0.42" cy="0.35" r="0.85">
          <stop offset="0" stopColor="#F5D9AE" stopOpacity={0.35} />
          <stop offset="0.6" stopColor="#000" stopOpacity={0} />
          <stop offset="1" stopColor="#2A1A0A" stopOpacity={0.3} />
        </radialGradient>
      </defs>
      <rect x={b.x} y={b.y} width={b.W} height={b.H} fill={base} />
      <rect x={b.x} y={b.y} width={b.W} height={b.H} filter={`url(#${id}t)`} opacity={0.5} />
      {lines}
      <rect x={b.x} y={b.y} width={b.W} height={b.H} fill={`url(#${id}v)`} />
    </svg>
  );
}

export type WallGroundProps = Span & {
  /** wall colours (default palette wall / wallDeep) */
  color?: string; deep?: string;
  /** awning stripe colours; null = no awning */
  awning?: [string, string] | null;
  /** width of one bay (shelf unit, lamp, awning) in px */
  bay?: number;
  /** world span to fill in x, for a camera that travels (default the frame plus pad) */
  x0?: number; x1?: number;
  lamps?: boolean;
  seed?: string;
};

/** A back wall of repeated bays: shelf recesses with boxes, posts, an optional striped awning and swaying lamps. */
export function WallGround({ color, deep, awning = null, bay = 620, x0, x1, lamps = true, seed = "wall", pad = 0.25 }: WallGroundProps) {
  const { w, h } = useClip();
  const { f } = useStage();
  const pal = usePalette();
  const u = useUnit();
  const fx = useFilters(9 * u);
  const wall = color ?? pal.wall, wd = deep ?? pal.wallDeep;
  const b = box(w, h, pad);
  const L = x0 ?? b.x, R = x1 ?? b.x + b.W;
  const B = bay * u;
  const bays: number[] = [];
  for (let x = L; x < R; x += B) bays.push(x);
  const s = h / 1920;
  return (
    <svg width={R - L} height={b.H} viewBox={`${L} ${b.y} ${R - L} ${b.H}`} style={{ position: "absolute", left: L, top: b.y, overflow: "visible" }}>
      {fx.defs}
      <rect x={L} y={b.y} width={R - L} height={b.H} fill={wall} />
      <rect x={L} y={520 * s} width={R - L} height={420 * s} fill={wd} opacity={0.55} />
      {bays.map((x, i) => (
        <g key={i}>
          <rect x={x + 40 * u} y={240 * s} width={B - 80 * u} height={680 * s} fill={mixColor(wd, pal.kraftDeep, 0.35)} opacity={0.45} />
          {[0, 1, 2].map((r) => <rect key={r} x={x + 70 * u} y={(560 + r * 110) * s} width={B - 140 * u} height={14 * s} fill={pal.woodDeep} opacity={0.25} />)}
          {Array.from({ length: 5 }, (_, j) => (
            <rect key={"c" + j} x={x + (90 + j * 92) * u} y={(480 + (j % 2) * 110 + Math.floor(random(`${seed}${i}-${j}`) * 2) * 110) * s}
              width={(58 + random(`${seed}w${i}-${j}`) * 24) * u} height={70 * s} rx={6} fill={pal.kraft} opacity={0.35} />
          ))}
          <rect x={x + 18 * u} y={140 * s} width={22 * u} height={820 * s} fill={pal.woodDeep} opacity={0.55} />
          {awning ? <Awning x={x} w={B} y={40 * s} hgt={140 * s} c={awning} alt={i % 2 === 1} wood={pal.woodDeep} soft={fx.soft} /> : null}
          {lamps ? <Lamp x={x + B / 2} y={200 * s} a={Math.sin(f / 23 + i * 0.9) * 3.5} u={u} ink={pal.ink} soft={fx.soft} /> : null}
        </g>
      ))}
    </svg>
  );
}

function Awning({ x, w, y, hgt, c, alt, wood, soft }: { x: number; w: number; y: number; hgt: number; c: [string, string]; alt: boolean; wood: string; soft: string }) {
  const n = 8, sw = w / n;
  return (
    <g>
      <rect x={x} y={y + 20} width={w} height={hgt + 10} fill="#4a2a18" opacity={0.18} transform="translate(0 22)" filter={soft} />
      {Array.from({ length: n }, (_, j) => (
        <path key={j} d={`M${x + j * sw} ${y} L${x + (j + 1) * sw} ${y} L${x + (j + 1) * sw} ${y + hgt} Q${x + (j + 0.5) * sw} ${y + hgt * 1.3} ${x + j * sw} ${y + hgt} Z`}
          fill={(j + (alt ? 1 : 0)) % 2 === 0 ? c[0] : c[1]} />
      ))}
      <rect x={x} y={y - 4} width={w} height={18} fill={wood} opacity={0.7} />
    </g>
  );
}

function Lamp({ x, y, a, u, ink, soft }: { x: number; y: number; a: number; u: number; ink: string; soft: string }) {
  return (
    <g transform={`rotate(${a} ${x} ${y})`}>
      <line x1={x} y1={y} x2={x} y2={y + 120 * u} stroke={ink} strokeWidth={3 * u} opacity={0.6} />
      <ellipse cx={x} cy={y + 196 * u} rx={130 * u} ry={60 * u} fill="#FFE9B8" opacity={0.25} filter={soft} />
      <path d={`M${x - 56 * u} ${y + 170 * u} Q${x} ${y + 100 * u} ${x + 56 * u} ${y + 170 * u} Z`} fill="#F8F4EB" stroke="#D8CFBF" strokeWidth={3 * u} />
      <ellipse cx={x} cy={y + 172 * u} rx={20 * u} ry={8 * u} fill="#FFF3C8" />
    </g>
  );
}

export type TableTopProps = Span & {
  /** y of the table's far edge in clip px (default 62 % of the height) */
  top?: number;
  color?: string;
  /** "wood" planks, "kraft" paper, "cloth" a woven cloth */
  kind?: "wood" | "kraft" | "cloth";
  x0?: number; x1?: number;
  seed?: string;
};

/** A table surface from `top` to below the frame: far edge lit, near edge darker, receding planks or weave, so the
 *  lower frame is a place where things stand rather than empty ground. Put it on a depth-1 layer under the actors. */
export function TableTop({ top, color, kind = "wood", x0, x1, seed = "table", pad = 0.25 }: TableTopProps) {
  const { w, h } = useClip();
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(10 * u);
  const base = color ?? (kind === "wood" ? pal.wood : kind === "kraft" ? pal.kraftLight : pal.paper);
  const T = top ?? h * 0.62;
  const L = x0 ?? -w * pad, R = x1 ?? w * (1 + pad), B = h * (1 + pad);
  const hi = mixColor(base, "#FFF4DC", 0.32), lo = mixColor(base, "#000000", 0.2);
  const rows: number[] = [];
  for (let y = T + 30 * u, g = 34 * u; y < B; y += g, g *= 1.22) rows.push(y);
  const grains = Array.from({ length: 40 }, (_, i) => {
    const y = T + 20 * u + random(`${seed}g${i}`) * (B - T);
    const x = L + random(`${seed}x${i}`) * (R - L);
    const len = (160 + random(`${seed}l${i}`) * 420) * u;
    return <path key={i} d={fibre(x, x + len, y, 3 * u, `${seed}f${i}`, 5)} stroke={random(`${seed}c${i}`) > 0.5 ? hi : lo}
      strokeWidth={2 * u} fill="none" opacity={0.28} />;
  });
  return (
    <svg width={R - L} height={B - T + 40 * u} viewBox={`${L} ${T - 40 * u} ${R - L} ${B - T + 40 * u}`}
      style={{ position: "absolute", left: L, top: T - 40 * u, overflow: "visible" }}>
      {defs}
      <defs>
        <linearGradient id={id + "g"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={hi} />
          <stop offset="0.3" stopColor={base} />
          <stop offset="1" stopColor={mixColor(base, lo, 0.7)} />
        </linearGradient>
      </defs>
      <rect x={L} y={T - 34 * u} width={R - L} height={44 * u} fill={pal.shadow} opacity={0.22} filter={soft} />
      <rect x={L} y={T} width={R - L} height={B - T} fill={`url(#${id}g)`} />
      {kind === "wood" ? rows.map((y, i) => <rect key={i} x={L} y={y} width={R - L} height={Math.max(2, 3 * u * (1 + i * 0.25))} fill={lo} opacity={0.35} />) : null}
      {kind === "cloth" ? rows.map((y, i) => <rect key={i} x={L} y={y} width={R - L} height={10 * u * (1 + i * 0.2)} fill={pal.red} opacity={0.18} />) : null}
      {kind !== "cloth" ? grains : null}
      <rect x={L} y={T} width={R - L} height={6 * u} fill="#FFF6E2" opacity={0.55} />
    </svg>
  );
}
