// Things drawn with material: a gradient body, a darker side, a rim light, a soft ground shadow and a little seeded
// irregularity, so they read as made objects. Positions are clip px; default sizes scale with the clip width.
import React from "react";
import { random } from "remotion";
import { FONTS } from "../../fonts";
import { textWidth } from "../helpers";
import { blob, fibre, mixColor, roughRect, smooth } from "./geom";
import type { Pt } from "./geom";
import { shades, useFilters, usePalette, useUnit } from "./palette";

const Canvas = ({ children, z }: { children: React.ReactNode; z?: number }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", zIndex: z }}>{children}</svg>
);

type MatProps = {
  /** the body outline */
  d: string;
  /** the same outline moved down: the visible side / thickness (omit for flat things) */
  side?: string;
  base: string;
  /** the ground shadow: centre and radii (omit for none) */
  shadow?: [number, number, number, number];
  /** rim-light width in px */
  rim?: number;
  /** seeded surface specks (count) and the box they are scattered in */
  specks?: number; box?: [number, number, number, number];
  seed: string;
  /** drawn inside the body, clipped to it */
  children?: React.ReactNode;
  outline?: number;
};

/** The material recipe every thing is built on. */
function Mat({ d, side, base, shadow, rim = 8, specks = 0, box, seed, children, outline = 2.2 }: MatProps) {
  const pal = usePalette();
  const { id, defs, soft } = useFilters(9);
  const c = shades(base);
  const r = rim;
  return (
    <g>
      {defs}
      <defs>
        <radialGradient id={id + "g"} cx="36%" cy="30%" r="85%">
          <stop offset="0" stopColor={c.hi} />
          <stop offset="0.55" stopColor={c.base} />
          <stop offset="1" stopColor={c.deep} />
        </radialGradient>
        <linearGradient id={id + "d"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.4" stopColor={c.deep} />
          <stop offset="1" stopColor={mixColor(c.deep, "#000000", 0.35)} />
        </linearGradient>
        <clipPath id={id + "c"}><path d={d} /></clipPath>
        <filter id={id + "r"} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={Math.max(0.5, r * 0.35)} /></filter>
      </defs>
      {shadow ? <ellipse cx={shadow[0]} cy={shadow[1]} rx={shadow[2]} ry={shadow[3]} fill={pal.shadow} opacity={0.3} filter={soft} /> : null}
      {side ? <path d={side} fill={`url(#${id}d)`} /> : null}
      <path d={d} fill={`url(#${id}g)`} />
      <g clipPath={`url(#${id}c)`}>
        {box && specks > 0 ? Array.from({ length: specks }, (_, i) => {
          const x = box[0] + random(`${seed}sx${i}`) * box[2], y = box[1] + random(`${seed}sy${i}`) * box[3];
          const l = (0.02 + random(`${seed}sl${i}`) * 0.05) * box[2];
          return <path key={i} d={`M${x} ${y} q${l / 2} ${(random(`${seed}sq${i}`) - 0.5) * l * 0.5} ${l} 0`} fill="none" strokeLinecap="round"
            stroke={random(`${seed}sc${i}`) > 0.5 ? c.hi : c.deep} strokeWidth={Math.max(1, box[3] * 0.012)} opacity={0.35} />;
        }) : null}
        {children}
        <path d={d} fill="none" stroke={c.rim} strokeWidth={r} opacity={0.75} transform={`translate(${r * 0.9} ${r * 0.9})`} filter={`url(#${id}r)`} />
      </g>
      <path d={d} fill="none" stroke={pal.ink} strokeOpacity={0.32} strokeWidth={outline} />
    </g>
  );
}

export type SlabProps = {
  /** centre of the top face, its width and height */
  x: number; y: number; w: number; h: number;
  shape?: "blob" | "round" | "rect";
  color?: string;
  /** thickness of the visible side, as a fraction of h (0 = flat) */
  depth?: number;
  r?: number;
  seed?: string;
  /** a sheen swept across from the left, 0..1 */
  sheen?: number;
  /** surface detail drawn inside the top face, clip px, clipped to it */
  detail?: React.ReactNode;
};

/** A slab of material: meat, soap, tallow, cheese, a brick, a stack: anything solid that sits on a surface. */
export function Slab({ x, y, w, h, shape = "blob", color, depth = 0.34, r = 0, seed = "slab", sheen = 0, detail }: SlabProps) {
  const pal = usePalette();
  const base = color ?? pal.accent;
  const outline = (oy: number, k = 1) =>
    shape === "blob" ? blob(x, y + oy, (w / 2) * k, (h / 2) * k, seed)
      : roughRect(x - (w / 2) * k, y + oy - (h / 2) * k, w * k, h * k, shape === "round" ? Math.min(w, h) * 0.28 : Math.min(w, h) * 0.06, seed);
  const top = outline(0);
  const side = depth > 0 ? outline(h * depth, 0.985) : undefined;
  return (
    <Canvas>
      <g transform={`rotate(${r} ${x} ${y + h / 2})`}>
        <Mat d={top} side={side} base={base} seed={seed} rim={Math.max(3, h * 0.07)} specks={Math.round(w / 12)}
          box={[x - w / 2, y - h / 2, w, h]} shadow={[x + w * 0.03, y + h * (0.5 + depth) - h * 0.02, w * 0.52, h * 0.16]}>
          {detail}
          {sheen > 0 ? <rect x={x - w / 2} y={y - h / 2} width={w * sheen} height={h} fill="#FFFFFF" opacity={0.22} /> : null}
          <ellipse cx={x - w * 0.15} cy={y - h * 0.24} rx={w * 0.2} ry={h * 0.08} fill="#FFFFFF" opacity={0.16} />
        </Mat>
      </g>
    </Canvas>
  );
}

export type HandPose = "open" | "point" | "pinch";

// per finger: base on the knuckle line, then two segments [angle deg, length]; the hand points to -x
type Finger = { at: Pt; a1: number; l1: number; a2: number; l2: number; w: number };
const CURL = (y: number, w: number): Finger => ({ at: [-88, y], a1: 172, l1: 30, a2: 95, l2: 22, w });
const POSES: Record<HandPose, { fingers: Finger[]; thumb: Finger }> = {
  open: {
    fingers: [
      { at: [-90, -28], a1: 196, l1: 60, a2: 192, l2: 46, w: 25 },
      { at: [-94, -8], a1: 182, l1: 66, a2: 180, l2: 50, w: 26 },
      { at: [-92, 12], a1: 170, l1: 60, a2: 168, l2: 46, w: 24 },
      { at: [-84, 30], a1: 158, l1: 46, a2: 154, l2: 36, w: 20 },
    ],
    thumb: { at: [-36, -40], a1: 232, l1: 50, a2: 212, l2: 42, w: 26 },
  },
  point: {
    fingers: [{ at: [-90, -28], a1: 184, l1: 64, a2: 182, l2: 52, w: 25 }, CURL(-6, 26), CURL(13, 24), CURL(30, 20)],
    thumb: { at: [-36, -40], a1: 196, l1: 44, a2: 168, l2: 34, w: 26 },
  },
  pinch: {
    fingers: [{ at: [-90, -28], a1: 200, l1: 56, a2: 140, l2: 40, w: 25 }, CURL(-6, 26), CURL(13, 24), CURL(30, 20)],
    thumb: { at: [-40, -40], a1: 190, l1: 70, a2: 151, l2: 64, w: 26 },
  },
};
const joints = (g: Finger): Pt[] => {
  const r = (deg: number) => (deg * Math.PI) / 180;
  const j: Pt = [g.at[0] + Math.cos(r(g.a1)) * g.l1, g.at[1] + Math.sin(r(g.a1)) * g.l1];
  return [g.at, j, [j[0] + Math.cos(r(g.a2)) * g.l2, j[1] + Math.sin(r(g.a2)) * g.l2]];
};

export type HandProps = {
  /** where the hand acts: the fingertip (point), the pinch (pinch) or the palm (open), in clip px */
  x: number; y: number;
  /** direction it points, degrees: 0 left, 90 up, 180 right, -90 down */
  ang?: number;
  pose?: HandPose;
  /** sleeve length behind the wrist, in hand px */
  len?: number;
  s?: number;
  glove?: string; sleeve?: string;
  seed?: string;
};

/** A gloved hand on a sleeve: points at, pinches, or lays its palm on things. People appear as hands, never faces. */
export function Hand({ x, y, ang = 0, pose = "point", len = 520, s, glove = "#ECE5D6", sleeve = "#5E6B5C", seed = "hand" }: HandProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(9);
  const P = POSES[pose];
  const fingers = P.fingers.map(joints);
  const thumb = joints(P.thumb);
  const act: Pt = pose === "point" ? fingers[0][2] : pose === "pinch"
    ? [(fingers[0][2][0] + thumb[2][0]) / 2, (fingers[0][2][1] + thumb[2][1]) / 2] : [-60, 0];
  const k = s ?? 1.3 * u;
  const g = shades(glove), sl = shades(sleeve);
  const ink = pal.ink;
  // two segments of different widths: the joint reads as a knuckle and the tip tapers
  const seg = (pts: Pt[], k: 0 | 1) => `M${pts[k][0]} ${pts[k][1]} L${pts[k + 1][0]} ${pts[k + 1][1]}`;
  const digit = (pts: Pt[], w: number, i: number) => (
    <g key={i}>
      <path d={seg(pts, 0)} stroke={ink} strokeOpacity={0.32} strokeWidth={w + 4} fill="none" strokeLinecap="round" />
      <path d={seg(pts, 1)} stroke={ink} strokeOpacity={0.32} strokeWidth={w * 0.86 + 4} fill="none" strokeLinecap="round" />
      <path d={seg(pts, 0)} stroke={`url(#${id}g)`} strokeWidth={w} fill="none" strokeLinecap="round" />
      <path d={seg(pts, 1)} stroke={`url(#${id}g)`} strokeWidth={w * 0.86} fill="none" strokeLinecap="round" />
      <path d={smooth(pts)} stroke="#FFFFFF" strokeOpacity={0.4} strokeWidth={w * 0.2} fill="none" strokeLinecap="round"
        transform={`translate(0 ${-w * 0.22})`} />
      <path d={`M${pts[1][0] - 4} ${pts[1][1] - w * 0.3} q4 ${w * 0.3} 0 ${w * 0.6}`} stroke={g.deep} strokeOpacity={0.55} strokeWidth={1.8} fill="none" />
    </g>
  );
  const fold = (i: number) => {
    const fx = 110 + i * 120 + random(`${seed}f${i}`) * 40;
    return <path key={i} d={`M${fx} ${-50 - i * 3} q${-18} ${50} ${6} ${100 + i * 4}`} stroke={sl.deep} strokeWidth={5} fill="none" opacity={0.45} strokeLinecap="round" />;
  };
  return (
    <Canvas>
      {defs}
      <defs>
        <linearGradient id={id + "g"} gradientUnits="userSpaceOnUse" x1="0" y1="-60" x2="0" y2="60">
          <stop offset="0" stopColor={g.hi} /><stop offset="0.5" stopColor={g.base} /><stop offset="1" stopColor={g.deep} />
        </linearGradient>
        <linearGradient id={id + "s"} gradientUnits="userSpaceOnUse" x1="0" y1="-62" x2="0" y2="62">
          <stop offset="0" stopColor={sl.hi} /><stop offset="0.45" stopColor={sl.base} /><stop offset="1" stopColor={sl.deep} />
        </linearGradient>
      </defs>
      <g transform={`translate(${x} ${y}) rotate(${ang}) scale(${k}) translate(${-act[0]} ${-act[1]})`}>
        <path d={`M40 -46 L${len} -60 L${len} 60 L40 46 Z`} fill={pal.shadow} opacity={0.22} transform="translate(12 22)" filter={soft} />
        <path d={`M44 -48 L${len} -62 L${len} 62 L44 48 Q30 0 44 -48 Z`} fill={`url(#${id}s)`} />
        {[0, 1, 2].map(fold)}
        <path d={`M60 -40 L${len} -52`} stroke="#FFFFFF" strokeOpacity={0.16} strokeWidth={9} />
        <rect x={26} y={-50} width={34} height={100} rx={12} fill={sl.deep} />
        <rect x={30} y={-46} width={26} height={10} rx={5} fill="#FFFFFF" opacity={0.12} />
        {fingers.map((pts, i) => digit(pts, P.fingers[i].w, i)).reverse()}
        <path d="M34 -40 C 0 -48 -60 -44 -94 -32 C -106 -14 -106 22 -90 36 C -60 46 -12 46 34 40 Z" fill={`url(#${id}g)`} stroke={ink} strokeOpacity={0.32} strokeWidth={2} />
        <path d="M20 -34 C -20 -40 -60 -38 -86 -28" stroke="#FFFFFF" strokeOpacity={0.3} strokeWidth={5} fill="none" strokeLinecap="round" />
        <path d="M-60 -2 C -40 2 -24 2 -8 -2" stroke={g.deep} strokeOpacity={0.4} strokeWidth={2} fill="none" />
        {digit(thumb, P.thumb.w, 9)}
      </g>
    </Canvas>
  );
}

export type WheelProps = { x: number; y: number; r?: number; roll?: number; color?: string; tyre?: string; spokes?: number };

/** A spoked wheel; `roll` in degrees (distance / r * 57.3 for a wheel that rolls without slipping). */
export function Wheel({ x, y, r, roll = 0, color, tyre, spokes = 6 }: WheelProps) {
  const pal = usePalette();
  const u = useUnit();
  const R = r ?? 86 * u;
  const rim = shades(color ?? pal.wood);
  const t = tyre ?? pal.woodDeep;
  return (
    <Canvas>
      <g transform={`translate(${x} ${y})`}>
        <circle r={R} fill={t} />
        <circle r={R * 0.97} fill="none" stroke="#FFFFFF" strokeOpacity={0.14} strokeWidth={R * 0.05} strokeDasharray={`${R * 1.6} ${R * 10}`} transform="rotate(200)" />
        <g transform={`rotate(${roll})`}>
          <circle r={R * 0.8} fill="none" stroke={rim.base} strokeWidth={R * 0.16} />
          {Array.from({ length: Math.max(1, Math.round(spokes / 2)) }, (_, i) => (
            <rect key={i} x={-R * 0.07} y={-R * 0.8} width={R * 0.14} height={R * 1.6} rx={R * 0.04} fill={rim.base} transform={`rotate(${(360 / spokes) * i})`} />
          ))}
          <circle r={R * 0.72} fill="none" stroke={rim.deep} strokeWidth={R * 0.03} opacity={0.6} />
          <circle r={R * 0.2} fill={rim.hi} stroke={rim.deep} strokeWidth={R * 0.04} />
          <circle r={R * 0.07} fill={rim.deep} />
        </g>
        <path d={`M${-R * 0.7} ${-R * 0.5} A ${R * 0.86} ${R * 0.86} 0 0 1 ${R * 0.3} ${-R * 0.82}`} stroke="#FFFFFF" strokeOpacity={0.3} strokeWidth={R * 0.05} fill="none" strokeLinecap="round" />
      </g>
    </Canvas>
  );
}

export type SignProps = {
  /** where the strings are pinned (centre), the board hangs `hang` px below */
  x: number; y: number; text: string;
  ang?: number; size?: number; hang?: number;
  color?: string; textColor?: string;
  font?: "serif" | "sans" | "display";
  seed?: string;
};

/** A wooden board on two strings with a carved-looking word (a place, a shop, a name of a thing). */
export function Sign({ x, y, text, ang = 0, size, hang, color, textColor, font = "serif", seed = "sign" }: SignProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(9);
  const fs = size ?? 82 * u;
  const fam = FONTS[font];
  const W = textWidth(text, fs, fam, 900) + fs * 0.16 * Array.from(text).length + fs * 1.2, H = fs * 1.6;
  const L = hang ?? 200 * u;
  const wood = shades(color ?? pal.wood);
  return (
    <Canvas>
      {defs}
      <defs>
        <linearGradient id={id + "w"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={wood.hi} /><stop offset="0.5" stopColor={wood.base} /><stop offset="1" stopColor={wood.deep} />
        </linearGradient>
      </defs>
      <g transform={`translate(${x} ${y}) rotate(${ang})`}>
        <line x1={-W * 0.32} y1={0} x2={-W * 0.32} y2={L} stroke={pal.ink} strokeWidth={3 * u} opacity={0.7} />
        <line x1={W * 0.32} y1={0} x2={W * 0.32} y2={L} stroke={pal.ink} strokeWidth={3 * u} opacity={0.7} />
        <path d={roughRect(-W / 2, L, W, H, 10 * u, seed)} fill={pal.shadow} opacity={0.28} transform={`translate(${10 * u} ${16 * u})`} filter={soft} />
        <path d={roughRect(-W / 2, L, W, H, 10 * u, seed)} fill={`url(#${id}w)`} />
        {Array.from({ length: 6 }, (_, i) => (
          <path key={i} d={fibre(-W / 2 + 8 * u, W / 2 - 8 * u, L + H * (0.12 + i * 0.15), 2.5 * u, `${seed}g${i}`, 6)} stroke={wood.deep} strokeWidth={1.6 * u} fill="none" opacity={0.35} />
        ))}
        <path d={roughRect(-W / 2 + 12 * u, L + 12 * u, W - 24 * u, H - 24 * u, 6 * u, seed + "i")} fill="none" stroke={pal.kraftLight} strokeWidth={3 * u} opacity={0.6} />
        <rect x={-W / 2 + 6 * u} y={L + 4 * u} width={W - 12 * u} height={5 * u} rx={2 * u} fill="#FFFFFF" opacity={0.2} />
        <text x={0} y={L + H / 2 + fs * 0.36} textAnchor="middle" fontFamily={fam} fontWeight={900} fontSize={fs} letterSpacing={fs * 0.16}
          fill={wood.deep} opacity={0.6} transform={`translate(${2 * u} ${3 * u})`}>{text}</text>
        <text x={0} y={L + H / 2 + fs * 0.36} textAnchor="middle" fontFamily={fam} fontWeight={900} fontSize={fs} letterSpacing={fs * 0.16}
          fill={textColor ?? "#F4E8D0"}>{text}</text>
      </g>
    </Canvas>
  );
}

/** The y of each board's top of a Shelf (top board first), to stand items on. */
export const shelfBoards = (y: number, h: number, rows = 3): number[] =>
  Array.from({ length: rows }, (_, i) => y - h + ((i + 1) * h) / rows - h * 0.02);

export type ShelfProps = {
  /** centre of its foot and its size */
  x: number; y: number; w?: number; h?: number;
  rows?: number;
  /** fill the boards with seeded boxes and jars */
  stock?: boolean;
  color?: string;
  seed?: string;
  /** things standing on it, in clip px (see shelfBoards) */
  items?: React.ReactNode;
};

/** A wooden shelf unit with boards in depth, stocked with plain boxes and jars or with your own items. */
export function Shelf({ x, y, w, h, rows = 3, stock = true, color, seed = "shelf", items }: ShelfProps) {
  const pal = usePalette();
  const u = useUnit();
  const W = w ?? 620 * u, H = h ?? 760 * u;
  const wood = shades(color ?? pal.wood);
  const L = x - W / 2, T = y - H, post = 22 * u, board = 18 * u, depth = 26 * u;
  const tops = shelfBoards(y, H, rows);
  const goods = [pal.kraft, pal.paper, pal.accent, pal.kraftLight, pal.steel];
  return (
    <>
      <Canvas>
        <rect x={L + post} y={T} width={W - 2 * post} height={H} fill={wood.deep} opacity={0.55} />
        {stock ? tops.map((ty, r) => {
          let cx = L + post + 14 * u;
          const out: React.ReactNode[] = [];
          for (let i = 0; cx < L + W - post - 60 * u; i++) {
            const bw = (52 + random(`${seed}w${r}-${i}`) * 60) * u, bh = (50 + random(`${seed}h${r}-${i}`) * ((H / rows) * 0.5 / u)) * u;
            if (cx + bw > L + W - post - 10 * u) break;
            const c = goods[Math.floor(random(`${seed}c${r}-${i}`) * goods.length)];
            const jar = random(`${seed}j${r}-${i}`) > 0.62;
            out.push(jar
              ? <Slab key={i} x={cx + bw / 2} y={ty - bh / 2} w={bw * 0.9} h={bh} shape="round" depth={0} color={c} seed={`${seed}${r}-${i}`} />
              : <Slab key={i} x={cx + bw / 2} y={ty - bh / 2} w={bw} h={bh} shape="rect" depth={0} color={c} seed={`${seed}${r}-${i}`} />);
            cx += bw + (8 + random(`${seed}g${r}-${i}`) * 18) * u;
          }
          return <g key={r}>{out}</g>;
        }) : null}
        {tops.map((ty, r) => (
          <g key={"b" + r}>
            <rect x={L} y={ty - depth * 0.4} width={W} height={depth * 0.6} fill={wood.hi} />
            <rect x={L} y={ty + depth * 0.2} width={W} height={board} fill={wood.base} />
            <rect x={L} y={ty + depth * 0.2 + board} width={W} height={6 * u} fill={pal.shadow} opacity={0.25} />
          </g>
        ))}
        <rect x={L} y={T} width={post} height={H} fill={wood.base} />
        <rect x={L + W - post} y={T} width={post} height={H} fill={wood.base} />
        <rect x={L + 3 * u} y={T} width={5 * u} height={H} fill="#FFFFFF" opacity={0.18} />
      </Canvas>
      {items}
    </>
  );
}

export type PhoneProps = {
  /** centre, width (height follows at 2.05x), rotation */
  x: number; y: number; w?: number; r?: number;
  color?: string;
  /** what the screen shows: HTML laid out in a box the size of the screen */
  screen?: React.ReactNode;
  /** screen colour when it shows nothing */
  glass?: string;
  seed?: string;
};

/** A phone in a hand-made metal body with a glass screen; give it `screen` to show a message, a price, a chart. */
export function Phone({ x, y, w, r = 0, color, screen, glass = "#1D2329", seed = "phone" }: PhoneProps) {
  const pal = usePalette();
  const u = useUnit();
  const W = w ?? 300 * u, H = W * 2.05;
  const bez = W * 0.055, sw = W - 2 * bez, sh = H - 2 * bez;
  const body = color ?? "#3A3F45";
  const d = roughRect(-W / 2, -H / 2, W, H, W * 0.16, seed, 0.002);
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, transform: `rotate(${r}deg)` }}>
      <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <Mat d={d} side={roughRect(-W / 2 + 4 * u, -H / 2 + 10 * u, W, H, W * 0.16, seed, 0.002)} base={body} seed={seed} rim={W * 0.03}
          shadow={[W * 0.06, H * 0.5, W * 0.55, W * 0.07]} outline={2.5 * u} />
        <rect x={W / 2 - 1 * u} y={-H * 0.24} width={5 * u} height={H * 0.1} rx={2 * u} fill={body} />
        <rect x={W / 2 - 1 * u} y={-H * 0.1} width={5 * u} height={H * 0.06} rx={2 * u} fill={body} />
      </svg>
      <div style={{ position: "absolute", left: -sw / 2, top: -sh / 2, width: sw, height: sh, borderRadius: W * 0.12, overflow: "hidden", background: glass }}>
        {screen}
        <div style={{ position: "absolute", left: "50%", top: sh * 0.018, width: W * 0.24, height: W * 0.07, marginLeft: -W * 0.12, borderRadius: W * 0.04, background: "#0C0E10" }} />
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(125deg, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0.04) 38%, rgba(255,255,255,0) 39%)" }} />
      </div>
      <div style={{ position: "absolute", left: -sw / 2, top: -sh / 2, width: sw, height: sh, borderRadius: W * 0.12, boxShadow: `inset 0 0 0 ${2 * u}px ${pal.ink}` , opacity: 0.5 }} />
    </div>
  );
}

export type NoteProps = {
  x: number; y: number; w?: number; r?: number;
  /** the printed value */
  value?: string;
  color?: string;
  /** a fanned stack of this many notes */
  count?: number;
  seed?: string;
};

/** A banknote of no real currency: guilloche lines, a rosette, the value large in a corner. */
export function Note({ x, y, w, r = 0, value = "100", color, count = 1, seed = "note" }: NoteProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(8);
  const W = w ?? 440 * u, H = W * 0.48;
  const c = shades(color ?? "#7BA387");
  const big = Math.max(64, H * 0.36), small = Math.max(40, H * 0.17);
  const one = (k: number) => {
    const s = `${seed}${k}`;
    const d = roughRect(-W / 2, -H / 2, W, H, 6 * u, s, 0.003);
    return (
      <g key={k} transform={`rotate(${(k - (count - 1) / 2) * 7}) translate(${k * 6 * u} ${-k * 3 * u})`}>
        <defs><clipPath id={`${id}c${k}`}><path d={d} /></clipPath></defs>
        <path d={d} fill={pal.shadow} opacity={0.22} transform={`translate(${6 * u} ${10 * u})`} filter={soft} />
        <path d={d} fill={`url(#${id}g)`} />
        <g clipPath={`url(#${id}c${k})`}>
          {Array.from({ length: 14 }, (_, i) => (
            <path key={i} d={fibre(-W / 2, W / 2, -H / 2 + (i + 0.5) * (H / 14), H * 0.03, `${s}l${i}`, 8)} stroke={c.deep} strokeWidth={1.2 * u} fill="none" opacity={0.28} />
          ))}
          <rect x={-W / 2 + H * 0.08} y={-H / 2 + H * 0.08} width={W - H * 0.16} height={H * 0.84} rx={4 * u} fill="none" stroke={c.deep} strokeWidth={3 * u} opacity={0.6} />
          <g transform={`translate(${-W * 0.22} 0)`}>
            <circle r={H * 0.3} fill={c.hi} opacity={0.7} />
            {Array.from({ length: 12 }, (_, i) => (
              <ellipse key={i} rx={H * 0.27} ry={H * 0.08} fill="none" stroke={c.deep} strokeWidth={1.4 * u} opacity={0.55} transform={`rotate(${i * 15})`} />
            ))}
            <circle r={H * 0.07} fill={c.deep} opacity={0.6} />
          </g>
          <rect x={-W / 2} y={-H / 2} width={W} height={H * 0.12} fill="#FFFFFF" opacity={0.18} />
        </g>
        <text x={W / 2 - H * 0.14} y={H * 0.3} textAnchor="end" fontFamily={FONTS.sans} fontWeight={900} fontSize={big} fill={c.deep}>{value}</text>
        <text x={-W / 2 + H * 0.14} y={-H / 2 + H * 0.14 + small} fontFamily={FONTS.sans} fontWeight={800} fontSize={small} fill={c.deep} opacity={0.8}>{value}</text>
        <path d={d} fill="none" stroke={pal.ink} strokeOpacity={0.3} strokeWidth={1.6 * u} />
      </g>
    );
  };
  return (
    <Canvas>
      {defs}
      <defs>
        <linearGradient id={id + "g"} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c.hi} /><stop offset="0.6" stopColor={c.base} /><stop offset="1" stopColor={c.deep} />
        </linearGradient>
      </defs>
      <g transform={`translate(${x} ${y}) rotate(${r})`}>{Array.from({ length: Math.max(1, count) }, (_, k) => one(k))}</g>
    </Canvas>
  );
}

export type ParcelProps = {
  /** centre of its front bottom edge; width, height and depth */
  x: number; y: number; w?: number; h?: number; d?: number;
  color?: string; tape?: string;
  /** a word on its shipping label */
  label?: string;
  seed?: string;
};

/** A cardboard box seen from a little above and to the side, taped, with a shipping label. */
export function Parcel({ x, y, w, h, d, color, tape, label, seed = "parcel" }: ParcelProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(10);
  const W = w ?? 380 * u, Hh = h ?? 260 * u, D = d ?? 200 * u;
  const dx = D * 0.55, dy = D * 0.42;
  const c = shades(color ?? pal.kraft);
  const L = x - W / 2, T = y - Hh;
  const top = `M${L} ${T} L${L + W} ${T} L${L + W + dx} ${T - dy} L${L + dx} ${T - dy} Z`;
  const side = `M${L + W} ${T} L${L + W + dx} ${T - dy} L${L + W + dx} ${y - dy} L${L + W} ${y} Z`;
  const tp = tape ?? mixColor(pal.kraftLight, "#FFFFFF", 0.3);
  const ls = Math.max(40, W * 0.12);
  return (
    <Canvas>
      {defs}
      <defs>
        <linearGradient id={id + "t"} x1="0" y1="1" x2="1" y2="0"><stop offset="0" stopColor={c.hi} /><stop offset="1" stopColor={c.rim} /></linearGradient>
        <linearGradient id={id + "s"} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor={c.deep} /><stop offset="1" stopColor={mixColor(c.deep, "#000000", 0.25)} /></linearGradient>
      </defs>
      <ellipse cx={x + dx * 0.6} cy={y - dy * 0.3} rx={W * 0.7} ry={D * 0.22} fill={pal.shadow} opacity={0.3} filter={soft} />
      <path d={side} fill={`url(#${id}s)`} stroke={pal.ink} strokeOpacity={0.3} strokeWidth={2 * u} />
      <path d={top} fill={`url(#${id}t)`} stroke={pal.ink} strokeOpacity={0.3} strokeWidth={2 * u} />
      <path d={`M${L + W * 0.44} ${T} L${L + W * 0.44 + dx} ${T - dy} L${L + W * 0.56 + dx} ${T - dy} L${L + W * 0.56} ${T} Z`} fill={tp} opacity={0.85} />
      <Mat d={roughRect(L, T, W, Hh, 4 * u, seed, 0.006)} base={c.base} seed={seed} rim={6 * u} specks={30} box={[L, T, W, Hh]}>
        <rect x={L + W * 0.44} y={T} width={W * 0.12} height={Hh * 0.46} fill={tp} opacity={0.85} />
        <path d={`M${L + W * 0.12} ${T + Hh * 0.3} q${W * 0.1} ${Hh * 0.04} ${W * 0.2} ${-Hh * 0.01}`} stroke={c.deep} strokeWidth={2 * u} fill="none" opacity={0.5} />
        {label ? (
          <g>
            <rect x={L + W * 0.1} y={T + Hh * 0.52} width={W * 0.62} height={ls * 1.7} rx={4 * u} fill={pal.paper} />
            <text x={L + W * 0.14} y={T + Hh * 0.52 + ls * 1.15} fontFamily={FONTS.sans} fontWeight={900} fontSize={ls} fill={pal.ink}>{label}</text>
          </g>
        ) : null}
      </Mat>
    </Canvas>
  );
}

export type DocProps = {
  x: number; y: number; w?: number; h?: number; r?: number;
  /** a heading in real text; the body is drawn as lines of writing */
  title?: string;
  lines?: number;
  /** 0..1 of the lines written so far */
  p?: number;
  /** a red stamp word across the lower half */
  stamp?: string;
  color?: string;
  seed?: string;
};

/** A sheet of paper with a heading, lines of writing and a folded corner: a contract, a notice, a report. */
export function Doc({ x, y, w, h, r = 0, title, lines = 7, p = 1, stamp, color, seed = "doc" }: DocProps) {
  const pal = usePalette();
  const u = useUnit();
  const { defs, soft } = useFilters(9);
  const W = w ?? 420 * u, H = h ?? W * 1.36;
  const L = -W / 2, T = -H / 2, fold = W * 0.14;
  const page = `M${L} ${T} L${L + W - fold} ${T} L${L + W} ${T + fold} L${L + W} ${T + H} L${L} ${T + H} Z`;
  const ts = Math.max(64, W * 0.15);
  const y0 = T + (title ? ts * 1.75 : W * 0.14);
  const gap = (T + H - W * 0.1 - y0) / Math.max(1, lines);
  const shown = p * lines;
  const ss = Math.max(64, W * 0.16);
  const sw = stamp ? textWidth(stamp, ss, FONTS.sans, 900) : 0;
  return (
    <Canvas>
      {defs}
      <g transform={`translate(${x} ${y}) rotate(${r})`}>
        <path d={page} fill={pal.shadow} opacity={0.24} transform={`translate(${8 * u} ${14 * u})`} filter={soft} />
        <Mat d={page} base={color ?? pal.paper} seed={seed} rim={5 * u} outline={1.6 * u}>
          {Array.from({ length: lines }, (_, i) => {
            const len = (i === lines - 1 ? 0.45 : 0.72 + random(`${seed}${i}`) * 0.2) * (W - W * 0.2);
            const k = Math.max(0, Math.min(1, shown - i));
            return k > 0 ? <rect key={i} x={L + W * 0.1} y={y0 + i * gap} width={len * k} height={Math.max(6 * u, gap * 0.28)} rx={3 * u} fill={pal.ink} opacity={0.22} /> : null;
          })}
        </Mat>
        <path d={`M${L + W - fold} ${T} L${L + W - fold} ${T + fold} L${L + W} ${T + fold} Z`} fill={mixColor(color ?? pal.paper, "#000000", 0.12)}
          stroke={pal.ink} strokeOpacity={0.25} strokeWidth={1.6 * u} />
        {title ? <text x={L + W * 0.1} y={T + ts * 1.25} fontFamily={FONTS.sans} fontWeight={900} fontSize={ts} fill={pal.ink}>{title}</text> : null}
        {stamp ? (
          <g transform={`translate(${W * 0.12} ${H * 0.22}) rotate(-12)`} opacity={0.82}>
            <rect x={-sw / 2 - ss * 0.4} y={-ss * 0.85} width={sw + ss * 0.8} height={ss * 1.4} rx={ss * 0.12} fill="none" stroke={pal.red} strokeWidth={ss * 0.08} />
            <text x={0} y={ss * 0.32} textAnchor="middle" fontFamily={FONTS.sans} fontWeight={900} fontSize={ss} fill={pal.red}>{stamp}</text>
          </g>
        ) : null}
      </g>
    </Canvas>
  );
}

export type CarProps = {
  /** where it meets the ground (centre) and its length; it faces left unless flip */
  x: number; y: number; w?: number;
  color?: string;
  /** wheel turn in degrees */
  roll?: number;
  flip?: boolean;
  seed?: string;
};

/** A small car in side view: shaded body, glass, lights and turning wheels. */
export function Car({ x, y, w, color, roll = 0, flip = false, seed = "car" }: CarProps) {
  const pal = usePalette();
  const u = useUnit();
  const { id, defs, soft } = useFilters(10);
  const W = w ?? 640 * u;
  const base = color ?? pal.accent;
  const P = (px: number, py: number) => `${(px * W).toFixed(1)} ${(py * W).toFixed(1)}`;
  const body = `M${P(0.01, -0.13)} L${P(0.0, -0.25)} Q${P(0.0, -0.31)} ${P(0.06, -0.315)} L${P(0.31, -0.34)} L${P(0.44, -0.515)}`
    + ` Q${P(0.46, -0.53)} ${P(0.5, -0.53)} L${P(0.69, -0.53)} Q${P(0.72, -0.53)} ${P(0.74, -0.5)} L${P(0.84, -0.37)}`
    + ` L${P(0.96, -0.355)} Q${P(1.0, -0.35)} ${P(1.0, -0.3)} L${P(0.995, -0.14)} L${P(0.93, -0.13)}`
    + ` A${P(0.14, 0.14)} 0 0 0 ${P(0.65, -0.13)} L${P(0.36, -0.13)} A${P(0.14, 0.14)} 0 0 0 ${P(0.08, -0.13)} Z`;
  const glass = `M${P(0.36, -0.355)} L${P(0.45, -0.49)} Q${P(0.47, -0.505)} ${P(0.5, -0.505)} L${P(0.68, -0.505)}`
    + ` Q${P(0.7, -0.505)} ${P(0.715, -0.49)} L${P(0.8, -0.37)} Z`;
  const R = 0.105 * W;
  const tyre = (cx: number) => (
    <g transform={`translate(${cx * W} ${-R}) rotate(${roll})`}>
      <circle r={R} fill="#24272A" />
      <circle r={R * 0.62} fill={pal.steel} />
      <circle r={R * 0.62} fill="none" stroke="#FFFFFF" strokeOpacity={0.35} strokeWidth={R * 0.06} strokeDasharray={`${R * 0.9} ${R * 4}`} />
      {Array.from({ length: 5 }, (_, i) => (
        <rect key={i} x={-R * 0.07} y={-R * 0.56} width={R * 0.14} height={R * 0.42} rx={R * 0.05} fill="#5E646A" transform={`rotate(${i * 72})`} />
      ))}
      <circle r={R * 0.14} fill="#3C4146" />
    </g>
  );
  return (
    <Canvas>
      {defs}
      <defs>
        <linearGradient id={id + "w"} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7C93A6" /><stop offset="0.5" stopColor="#2E3B47" /><stop offset="1" stopColor="#1B232B" />
        </linearGradient>
      </defs>
      <g transform={`translate(${flip ? x + W / 2 : x - W / 2} ${y}) scale(${flip ? -1 : 1} 1)`}>
        <ellipse cx={W * 0.5} cy={0} rx={W * 0.52} ry={W * 0.035} fill={pal.shadow} opacity={0.4} filter={soft} />
        <Mat d={body} base={base} seed={seed} rim={W * 0.012} outline={2.2 * u}>
          <path d={`M${P(0, -0.2)} L${P(1, -0.2)}`} stroke="#FFFFFF" strokeOpacity={0.22} strokeWidth={W * 0.006} />
          <rect x={0} y={-0.16 * W} width={W} height={0.04 * W} fill="#000000" opacity={0.18} />
        </Mat>
        <path d={glass} fill={`url(#${id}w)`} stroke={pal.ink} strokeOpacity={0.4} strokeWidth={2 * u} />
        <path d={`M${P(0.58, -0.505)} L${P(0.58, -0.355)}`} stroke={shades(base).deep} strokeWidth={W * 0.014} />
        <path d={`M${P(0.47, -0.48)} L${P(0.53, -0.48)} L${P(0.44, -0.38)} L${P(0.4, -0.38)} Z`} fill="#FFFFFF" opacity={0.18} />
        <path d={`M${P(0.58, -0.35)} L${P(0.585, -0.16)}`} stroke={pal.ink} strokeOpacity={0.35} strokeWidth={2 * u} />
        <rect x={0.5 * W} y={-0.31 * W} width={0.05 * W} height={0.012 * W} rx={0.006 * W} fill={pal.ink} opacity={0.5} />
        <ellipse cx={0.025 * W} cy={-0.27 * W} rx={0.018 * W} ry={0.022 * W} fill={pal.lemon} stroke={pal.ink} strokeOpacity={0.3} />
        <rect x={0.975 * W} y={-0.31 * W} width={0.022 * W} height={0.05 * W} rx={0.006 * W} fill={pal.red} />
        {tyre(0.22)}
        {tyre(0.79)}
      </g>
    </Canvas>
  );
}
