// Explainer furniture in the drawings' line: speech and thought bubbles that pop in with a squash, and a chalkboard
// with chalk that writes text and draws lines on by progress.
import React, { useId } from "react";
import { random, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { fontFamily } from "../../fonts";
import { textWidth } from "../helpers";
import { useLineStyle } from "./drawn";
import { roughRect, seedInt, smooth, smoothClosed } from "./geom";
import type { Pt } from "./geom";
import { useUnit } from "./palette";
import { clamp01, prog } from "./time";

const useFrame = (fIn?: number) => {
  const now = useCurrentFrame();
  return fIn ?? now;
};
const pop = (j: number) => {
  const s = 1 - Math.exp(-j / 2.2) * Math.cos(j * 0.95), q = 0.16 * Math.exp(-j / 3) * Math.sin(j * 0.95 + 0.6);
  return [Math.max(0, s * (1 + q)), Math.max(0, s * (1 - q))];
};
const away = (f: number, at: number, len: number) => (Number.isFinite(len) ? clamp01((at + len - f) / 5) : 1);

/** A hand-drawn ellipse `w` x `h` with its top-left at (0, 0), its edge a little uneven. */
const wobblyEllipse = (w: number, h: number, seed: string, n = 16, jit = 0.025): string =>
  smoothClosed(Array.from({ length: n }, (_, i): Pt => {
    const a = (i / n) * 2 * Math.PI, r = 1 + (random(`${seed}${i}`) - 0.5) * 2 * jit;
    return [w / 2 + Math.cos(a) * (w / 2) * r, h / 2 + Math.sin(a) * (h / 2) * r];
  }));

type BubbleProps = {
  /** the bubble's centre and size */
  x: number; y: number; w: number; h: number;
  /** the point the tail reaches toward (a speaker's mouth); null: no tail */
  tail?: Pt | null;
  at: number; len?: number;
  /** font size of plain text inside */
  size?: number;
  color?: string; seed?: string; f?: number;
  children?: React.ReactNode;
};

// the bubble's edge toward the tail, as an angle from its centre and a point on its edge (box-local px)
const toward = (x: number, y: number, w: number, h: number, tail: Pt) => {
  const a = Math.atan2(tail[1] - y, tail[0] - x);
  return { a, bx: w / 2 + Math.cos(a) * (w / 2) * 0.92, by: h / 2 + Math.sin(a) * (h / 2) * 0.92 };
};

const Content = ({ w, h, size, color, children }: { w: number; h: number; size: number; color: string; children?: React.ReactNode }) => (
  <div style={{
    position: "absolute", left: w * 0.13, top: h * 0.16, width: w * 0.74, height: h * 0.68, display: "flex", alignItems: "center",
    justifyContent: "center", textAlign: "center", fontFamily: fontFamily("sans"), fontWeight: 800, fontSize: size, lineHeight: 1.15, color,
  }}>{children}</div>
);

export type SpeechBubbleProps = BubbleProps & { shape?: "round" | "box" };
/** A hand-drawn speech bubble centred at (x, y) with a tail toward `tail`, popping in from the tail with a squash at
 *  `at` (and out over the last 5 frames of `len`); children are its content. */
export function SpeechBubble({ x, y, w, h, tail = null, at, len = Infinity, size, shape = "round", color, seed = "speech", f: fIn, children }: SpeechBubbleProps) {
  const ink = useLineStyle();
  const u = useUnit();
  const f = useFrame(fIn);
  if (f < at || f >= at + len) return null;
  const [sx, sy] = pop(f - at), out = away(f, at, len);
  const body = shape === "box" ? roughRect(0, 0, w, h, Math.min(w, h) * 0.22, seed) : wobblyEllipse(w, h, seed);
  let tailD = "", ox = w / 2, oy = h / 2;
  if (tail) {
    const t = toward(x, y, w, h, tail), sp = 0.22 * (h / Math.max(w, h)) + 0.08, rx = (w / 2) * 0.75, ry = (h / 2) * 0.75;
    const tip: Pt = [tail[0] - (x - w / 2), tail[1] - (y - h / 2)];
    const b1: Pt = [w / 2 + Math.cos(t.a - sp) * rx, h / 2 + Math.sin(t.a - sp) * ry], b2: Pt = [w / 2 + Math.cos(t.a + sp) * rx, h / 2 + Math.sin(t.a + sp) * ry];
    const bend = (p: Pt, k: number): Pt => [p[0] + (tip[0] - p[0]) * 0.55 + Math.sin(t.a) * k, p[1] + (tip[1] - p[1]) * 0.55 - Math.cos(t.a) * k];
    const k = Math.hypot(tip[0] - t.bx, tip[1] - t.by) * 0.12;
    tailD = `M${b1[0]} ${b1[1]} Q${bend(b1, k).join(" ")} ${tip[0]} ${tip[1]} Q${bend(b2, k * 0.4).join(" ")} ${b2[0]} ${b2[1]}Z`;
    ox = t.bx; oy = t.by;
  }
  const fill = color ?? ink.paper;
  return (
    <div style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, transformOrigin: `${ox}px ${oy}px`,
      transform: `scale(${sx * out}, ${sy * out})` }}>
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} strokeLinejoin="round">
        <path d={body} fill={ink.color} stroke={ink.color} strokeWidth={ink.weight * 2} />
        {tailD ? <path d={tailD} fill={ink.color} stroke={ink.color} strokeWidth={ink.weight * 2} /> : null}
        <path d={body} fill={fill} />
        {tailD ? <path d={tailD} fill={fill} /> : null}
      </svg>
      <Content w={w} h={h} size={size ?? 64 * u} color={ink.color}>{children}</Content>
    </div>
  );
}

export type ThoughtBubbleProps = BubbleProps & { bumps?: number };
/** A thought cloud centred at (x, y) whose trail of small circles leads to `tail` (a head): the circles pop on one by
 *  one from the head, then the cloud; children are its content. */
export function ThoughtBubble({ x, y, w, h, tail = null, at, len = Infinity, size, bumps = 11, color, seed = "thought", f: fIn, children }: ThoughtBubbleProps) {
  const ink = useLineStyle();
  const u = useUnit();
  const f = useFrame(fIn);
  if (f < at || f >= at + len) return null;
  const j = f - at, out = away(f, at, len), fill = color ?? ink.paper, lead = tail ? 6 : 0;
  const ring = Array.from({ length: bumps }, (_, i) => {
    const a = (i / bumps) * 2 * Math.PI + random(`${seed}a${i}`) * 0.2;
    return { cx: w / 2 + Math.cos(a) * w * 0.4, cy: h / 2 + Math.sin(a) * h * 0.38, r: Math.min(w, h) * (0.17 + 0.05 * random(`${seed}r${i}`)) };
  });
  const t = tail ? toward(x, y, w, h, tail) : null;
  const tip: Pt | null = tail ? [tail[0] - (x - w / 2), tail[1] - (y - h / 2)] : null;
  const dots = t && tip ? [0, 1, 2].map((i) => {
    const q = 0.15 + 0.3 * i, r = Math.min(w, h) * (0.05 + 0.035 * i);
    return { cx: tip[0] + (t.bx - tip[0]) * q, cy: tip[1] + (t.by - tip[1]) * q, r: r * (pop(j - 2 * i)[0] || 0), on: j >= 2 * i };
  }) : [];
  const [sx, sy] = j >= lead ? pop(j - lead) : [0, 0];
  const ox = t ? t.bx : w / 2, oy = t ? t.by : h / 2;
  return (
    <div style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, opacity: out }}>
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {dots.map((d, i) => (d.on && d.r > 0.5 ? <circle key={i} cx={d.cx} cy={d.cy} r={d.r} fill={fill} stroke={ink.color} strokeWidth={ink.weight} /> : null))}
        <g transform={`translate(${ox} ${oy}) scale(${sx} ${sy}) translate(${-ox} ${-oy})`}>
          {ring.map((b, i) => <circle key={"e" + i} cx={b.cx} cy={b.cy} r={b.r + ink.weight} fill={ink.color} />)}
          <ellipse cx={w / 2} cy={h / 2} rx={w * 0.4 + ink.weight} ry={h * 0.38 + ink.weight} fill={ink.color} />
          {ring.map((b, i) => <circle key={"f" + i} cx={b.cx} cy={b.cy} r={b.r} fill={fill} />)}
          <ellipse cx={w / 2} cy={h / 2} rx={w * 0.4} ry={h * 0.38} fill={fill} />
        </g>
      </svg>
      {sx > 0.6 ? <div style={{ position: "absolute", inset: 0, transformOrigin: `${ox}px ${oy}px`, transform: `scale(${sx}, ${sy})` }}>
        <Content w={w} h={h} size={size ?? 60 * u} color={ink.color}>{children}</Content>
      </div> : null}
    </div>
  );
}

// ------------------------------------------------------------------ chalkboard

const CHALK = "#F2EFE4";

/** How much of each line of `text` (split on newlines) is written at progress p: characters, the last one partly. */
export const writeAt = (text: string, p: number): number[] => {
  const lines = text.split("\n").map((l) => Array.from(l).length);
  let left = clamp01(p) * lines.reduce((a, b) => a + b, 0);
  return lines.map((n) => {
    const c = Math.min(n, left);
    left -= c;
    return c;
  });
};

/** A line drawn by hand from a to b: a slight bow and wobble, the same for one seed. */
export const chalkLine = (a: Pt, b: Pt, seed = "chalk", wobble = 0.012): string => {
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]), nx = -(b[1] - a[1]) / (L || 1), ny = (b[0] - a[0]) / (L || 1);
  const bow = (random(`${seed}bow`) - 0.5) * 2 * wobble * L;
  return smooth(Array.from({ length: 6 }, (_, i): Pt => {
    const t = i / 5, off = bow * 4 * t * (1 - t) + (i > 0 && i < 5 ? (random(`${seed}${i}`) - 0.5) * wobble * L : 0);
    return [a[0] + (b[0] - a[0]) * t + nx * off, a[1] + (b[1] - a[1]) * t + ny * off];
  }));
};

// chalk grain: speckled holes through the stroke and a rough edge
const Grain = ({ id, seed, rough = 2.5 }: { id: string; seed: string; rough?: number }) => {
  const { width: W, height: H } = useClip();
  return (
  <filter id={id} filterUnits="userSpaceOnUse" x={-W * 0.25} y={-H * 0.25} width={W * 1.5} height={H * 1.5}>
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={seedInt(seed)} result="n" />
    <feDisplacementMap in="SourceGraphic" in2="n" scale={rough} result="d" />
    <feColorMatrix in="n" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -3.2 2.35" result="m" />
    <feComposite in="d" in2="m" operator="in" />
  </filter>
  );
};

const useChalkP = (p: number | undefined, at: number, len: number, fIn?: number) => {
  const f = useFrame(fIn);
  return p ?? prog(f, at, len);
};

export type ChalkBoardProps = { x: number; y: number; w: number; h: number; color?: string; frame?: string; stand?: boolean; seed?: string; children?: React.ReactNode };
/** A framed dark board with old chalk dust and eraser smears, its outer box at (x, y, w, h), a ledge with a stick of
 *  chalk, on an easel's legs with `stand`; children (Chalk marks) are drawn over it. */
export function ChalkBoard({ x, y, w, h, color = "#2F4A3C", frame = "#9A6A3F", stand = false, seed = "board", children }: ChalkBoardProps) {
  const ink = useLineStyle();
  const id = "cb" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const t = Math.min(w, h) * 0.06, ix = x + t, iy = y + t, iw = w - 2 * t, ih = h - 2 * t;
  const smears = Array.from({ length: 4 }, (_, i) => {
    const cy = iy + ih * (0.2 + 0.6 * random(`${seed}s${i}`)), cx = ix + iw * (0.15 + 0.5 * random(`${seed}x${i}`)), l = iw * (0.25 + 0.3 * random(`${seed}l${i}`));
    return `M${cx} ${cy} q${l / 2} ${-ih * 0.06} ${l} 0 q${-l / 2} ${ih * 0.05} ${-l * 0.9} ${ih * 0.06}`;
  });
  const legs = stand ? [[x + w * 0.18, -1], [x + w * 0.82, 1]] : [];
  return (
    <>
      <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} strokeLinejoin="round" strokeLinecap="round">
        <defs>
          <clipPath id={id + "c"}><rect x={ix} y={iy} width={iw} height={ih} /></clipPath>
          <filter id={id + "d"} x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency={(3 / Math.max(iw, ih)).toFixed(5)} numOctaves={4} seed={seedInt(seed + "d")} />
            <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.9 -0.35" />
          </filter>
        </defs>
        {legs.map(([lx, s], i) => <path key={i} d={`M${lx} ${y + h * 0.6} L${lx + s * w * 0.06} ${y + h * 1.35}`} stroke={ink.color} strokeWidth={t * 0.9 + ink.weight * 1.6} />)}
        {legs.map(([lx, s], i) => <path key={"l" + i} d={`M${lx} ${y + h * 0.6} L${lx + s * w * 0.06} ${y + h * 1.35}`} stroke={frame} strokeWidth={t * 0.9} />)}
        <path d={roughRect(x, y, w, h, t * 0.5, seed, 0.004)} fill={frame} stroke={ink.color} strokeWidth={ink.weight} />
        <rect x={ix} y={iy} width={iw} height={ih} fill={color} stroke={ink.color} strokeWidth={ink.weight * 0.6} />
        <g clipPath={`url(#${id}c)`}>
          <rect x={ix} y={iy} width={iw} height={ih} filter={`url(#${id}d)`} opacity={0.22} />
          {smears.map((d, i) => <path key={i} d={d} fill="none" stroke={CHALK} strokeWidth={ih * 0.09} opacity={0.05} />)}
        </g>
        <rect x={x - t * 0.6} y={y + h - t * 0.4} width={w + t * 1.2} height={t * 1.1} rx={t * 0.2} fill={frame} stroke={ink.color} strokeWidth={ink.weight * 0.8} />
        <rect x={x + w * 0.7} y={y + h - t * 0.95} width={w * 0.07} height={t * 0.55} rx={t * 0.25} fill={CHALK} stroke={ink.color} strokeWidth={ink.weight * 0.5} />
      </svg>
      {children}
    </>
  );
}

export type ChalkTextProps = {
  /** where the first line starts (anchor "start") or is centred (anchor "middle"); y is its middle */
  x: number; y: number; text: string;
  /** 0..1 written; or written on over `len` frames from `at` */
  p?: number; at?: number; len?: number;
  size?: number; font?: string; weight?: number; anchor?: "start" | "middle"; color?: string; seed?: string; f?: number;
};
/** Text written on in chalk, character by character as p goes 0..1 (lines split on "\n"), grainy and a little rough. */
export function ChalkText({ x, y, text, p, at = 0, len = 30, size, font = "sans", weight = 700, anchor = "start", color = CHALK, seed = "chalktext", f: fIn }: ChalkTextProps) {
  const u = useUnit();
  const id = "ct" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const k = useChalkP(p, at, len, fIn);
  if (k <= 0) return null;
  const s = size ?? 72 * u, fam = fontFamily(font), lines = text.split("\n"), shown = writeAt(text, k);
  return (
    <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <defs>
        <Grain id={id} seed={seed} rough={s * 0.03} />
        {lines.map((l, i) => {
          const chars = Array.from(l), c = Math.floor(shown[i]), W = textWidth(l, s, fam, weight);
          const pre = textWidth(chars.slice(0, c).join(""), s, fam, weight), cw = c < chars.length ? textWidth(chars[c], s, fam, weight) : 0;
          const x0 = anchor === "middle" ? x - W / 2 : x;
          return <clipPath key={i} id={`${id}l${i}`}><rect x={x0 - s * 0.1} y={y + i * s * 1.25 - s} width={shown[i] > 0 ? pre + cw * (shown[i] - c) + s * 0.1 : 0} height={s * 2} /></clipPath>;
        })}
      </defs>
      {lines.map((l, i) => (
        <text key={i} x={x} y={y + i * s * 1.25} dominantBaseline="central" textAnchor={anchor} fontFamily={fam} fontWeight={weight} fontSize={s}
          fill={color} clipPath={`url(#${id}l${i})`} filter={`url(#${id})`}>{l}</text>
      ))}
    </svg>
  );
}

export type ChalkPathProps = { d: string; p?: number; at?: number; len?: number; width?: number; color?: string; seed?: string; f?: number };
/** A chalk stroke along path `d` drawn on as p goes 0..1 (or over `len` frames from `at`), grainy with a rough edge. */
export function ChalkPath({ d, p, at = 0, len = 20, width, color = CHALK, seed = "chalkpath", f: fIn }: ChalkPathProps) {
  const u = useUnit();
  const id = "cp" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const k = useChalkP(p, at, len, fIn);
  if (k <= 0) return null;
  const w = width ?? 11 * u;
  return (
    <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
      <defs><Grain id={id} seed={seed} rough={w * 0.35} /></defs>
      <path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - clamp01(k)} fill="none" stroke={color} strokeWidth={w}
        strokeLinecap="round" strokeLinejoin="round" filter={`url(#${id})`} />
    </svg>
  );
}

export type ChalkLineProps = Omit<ChalkPathProps, "d"> & { from: Pt; to: Pt; wobble?: number };
/** A hand-drawn chalk line from `from` to `to`, drawn on like ChalkPath. */
export function ChalkLine({ from, to, wobble, seed = "chalkline", ...rest }: ChalkLineProps) {
  return <ChalkPath d={chalkLine(from, to, seed, wobble)} seed={seed} {...rest} />;
}
