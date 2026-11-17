// Drawn marks in the drawings' own line (LineStyle): emotion marks by a head, impact frames and manga focus lines.
// Weather and air are in marks-air.tsx, speech bubbles and the chalkboard in marks-board.tsx. Every time is in frames.
import React from "react";
import { random, useCurrentFrame } from "remotion";
import { useLineStyle } from "./drawn";
import { clamp01 } from "./time";
import type { Pt } from "./geom";

export * from "./marks-air";
export * from "./marks-board";

const Canvas = ({ children, opacity }: { children: React.ReactNode; opacity?: number }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity }}>{children}</svg>
);
const life = (f: number, at: number, len: number) => (f < at || f >= at + len ? -1 : (f - at) / len);
const fadeOut = (k: number, tail = 0.2) => (k > 1 - tail ? (1 - k) / tail : 1);
const starPath = (r: number) => {
  const q = r * 0.1;
  return `M0 ${-r} Q${q} ${-q} ${r} 0 Q${q} ${q} 0 ${r} Q${-q} ${q} ${-r} 0 Q${-q} ${-q} 0 ${-r}Z`;
};
const fx = (v: number) => v.toFixed(1);
const useFrame = (fIn?: number) => {
  const now = useCurrentFrame();
  return fIn ?? now;
};

/** A pop-in with a squash: [sx, sy] `j` frames after it starts, overshooting and settling to [1, 1]; null before. */
export const popAt = (j: number, squash = 0.16): [number, number] | null => {
  if (j < 0) return null;
  const s = 1 - Math.exp(-j / 2.2) * Math.cos(j * 0.95), q = squash * Math.exp(-j / 3) * Math.sin(j * 0.95 + 0.6);
  return [Math.max(0, s * (1 + q)), Math.max(0, s * (1 - q))];
};

export type Spawn = { i: number; age: number; k: number };
/** Things given off one every `every` frames from `at`, each living `life` frames: the ones alive at frame f. None
 *  is born so late that it would outlive `at + len`; at most `max` in all. */
export const spawnsAt = (f: number, at: number, len: number, every: number, lifeLen: number, max = 99): Spawn[] => {
  const out: Spawn[] = [];
  if (f < at || f >= at + len || every <= 0 || lifeLen <= 0) return out;
  const last = Math.min(max - 1, Math.floor((len - lifeLen) / every));
  for (let i = Math.max(0, Math.floor((f - at - lifeLen) / every)); i <= last; i++) {
    const age = f - at - i * every;
    if (age < 0) break;
    if (age < lifeLen) out.push({ i, age, k: age / lifeLen });
  }
  return out;
};

export type FocusArea = { x: number; y: number; w: number; h: number };
/** Manga concentration lines over `area` at frame f: wedges (three points each: a tip toward (cx, cy), two feet
 *  past the area's edge), the clear middle an ellipse `inner` of the half-size; they change every `hold` frames. */
export const focusLinesAt = (f: number, at: number, len: number, area: FocusArea, o: {
  cx?: number; cy?: number; n?: number; inner?: number; width?: number; hold?: number; seed?: string;
} = {}): Pt[][] => {
  if (f < at || f >= at + len) return [];
  const { x, y, w, h } = area;
  const cx = o.cx ?? x + w / 2, cy = o.cy ?? y + h / 2, n = o.n ?? 64, inner = o.inner ?? 0.55, hold = Math.max(1, o.hold ?? 2);
  const key = `${o.seed ?? "focus"}:${Math.floor((f - at) / hold)}`;
  const far = Math.hypot(Math.max(cx - x, x + w - cx), Math.max(cy - y, y + h - cy)) * 1.05;
  const base = (o.width ?? 0.022) * far;
  return Array.from({ length: n }, (_, i) => {
    const a = ((i + 0.8 * random(`${key}a${i}`)) / n) * 2 * Math.PI, c = Math.cos(a), s = Math.sin(a);
    const ell = 1 / Math.hypot(c / (w / 2), s / (h / 2));
    const r0 = ell * inner * (1 + 0.45 * random(`${key}r${i}`)), half = (base * (0.35 + 0.9 * random(`${key}w${i}`))) / 2;
    return [[cx + c * r0, cy + s * r0], [cx + c * far - s * half, cy + s * far + c * half], [cx + c * far + s * half, cy + s * far - c * half]];
  });
};

type Mark = { x: number; y: number; at: number; len?: number; size?: number; color?: string; seed?: string; f?: number };

export type AngerVeinProps = Mark & { beat?: number };
/** The cross-shaped vein of a temper by a head: four red bent strokes that pop on and throb every `beat` frames. */
export function AngerVein({ x, y, at, len = 45, size = 90, color = "#E8443A", beat = 10, f: fIn }: AngerVeinProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  const pop = popAt(f - at);
  if (k < 0 || !pop) return null;
  const b = (f - at) % beat, throb = b < 2 ? 1.16 : b < 4 ? 1.06 : 1;
  const o = size * 0.5, g = size * 0.11, wd = size * 0.13;
  const d = [[1, 1], [-1, 1], [1, -1], [-1, -1]].map(([a, c]) =>
    `M${a * o} ${c * g * 1.6} Q${a * g * 0.3} ${c * g * 0.3} ${a * g * 1.6} ${c * o}`).join(" ");
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      <g transform={`translate(${x} ${y}) scale(${pop[0] * throb} ${pop[1] * throb})`} fill="none" strokeLinecap="round">
        <path d={d} stroke={ink.color} strokeWidth={wd + ink.weight * 1.4} />
        <path d={d} stroke={color} strokeWidth={wd} />
      </g>
    </Canvas>
  );
}

export type SparklesProps = Mark & { n?: number; r?: number };
/** Four-point stars twinkling in and out round (x, y) within `r`, each on its own beat. */
export function Sparkles({ x, y, at, len = 60, size = 46, n = 5, r = 150, color, seed = "sparkles", f: fIn }: SparklesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at;
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      {Array.from({ length: n }, (_, i) => {
        const a = (i / n) * 2 * Math.PI + random(`${seed}a${i}`) * 0.9, d = r * (0.35 + 0.65 * random(`${seed}d${i}`));
        const period = 16 + 12 * random(`${seed}p${i}`), ph = random(`${seed}h${i}`);
        const tw = Math.sin(2 * Math.PI * (j / period + ph) - (i === 0 ? 0 : 0.6));
        const s = size * (0.55 + 0.6 * random(`${seed}s${i}`)) * Math.pow(Math.max(0, tw), 0.6) * Math.min(1, j / 3);
        if (s < 1) return null;
        return <path key={i} d={starPath(s)} transform={`translate(${fx(x + Math.cos(a) * d)} ${fx(y + Math.sin(a) * d)}) rotate(${(j * 3) % 90})`}
          fill={color ?? ink.spark} stroke={ink.color} strokeWidth={Math.max(ink.weight * 0.5, s * 0.12)} strokeLinejoin="round" />;
      })}
    </Canvas>
  );
}

const heartPath = (s: number) =>
  `M0 ${s * 0.4} C${-s * 1.05} ${-s * 0.2} ${-s * 0.5} ${-s * 0.95} 0 ${-s * 0.38} C${s * 0.5} ${-s * 0.95} ${s * 1.05} ${-s * 0.2} 0 ${s * 0.4}Z`;

export type HeartsProps = Mark & { every?: number; life?: number; rise?: number; spread?: number };
/** Hearts rising from (x, y) one every `every` frames, swaying, each popping into ticks at the top of its rise. */
export function Hearts({ x, y, at, len = 60, size = 56, every = 9, life: span = 30, rise = 240, spread = 110, color = "#FF6F91", seed = "hearts", f: fIn }: HeartsProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const items = spawnsAt(f, at, len, every, span);
  if (!items.length) return null;
  return (
    <Canvas>
      {items.map(({ i, age, k }) => {
        const hx = x + (random(`${seed}x${i}`) - 0.5) * spread + Math.sin(age * 0.25 + i) * size * 0.25;
        const hy = y - rise * (1 - Math.pow(1 - Math.min(k / 0.8, 1), 2)), s = size * (0.75 + 0.4 * random(`${seed}s${i}`));
        const pop = popAt(age) ?? [0, 0];
        if (k > 0.8) {
          const q = (k - 0.8) / 0.2;
          return (
            <g key={i} transform={`translate(${fx(hx)} ${fx(hy)})`} opacity={1 - q} stroke={ink.color} strokeWidth={ink.weight * 0.8} strokeLinecap="round">
              <path d={heartPath(s * (1 + 0.5 * q))} fill={color} opacity={1 - q} />
              {Array.from({ length: 6 }, (_, t) => {
                const a = (t / 6) * 2 * Math.PI, r0 = s * (0.8 + 0.7 * q), r1 = r0 + s * 0.35;
                return <line key={t} x1={Math.cos(a) * r0} y1={Math.sin(a) * r0} x2={Math.cos(a) * r1} y2={Math.sin(a) * r1} />;
              })}
            </g>
          );
        }
        return <path key={i} d={heartPath(s)} transform={`translate(${fx(hx)} ${fx(hy)}) rotate(${Math.sin(age * 0.3 + i) * 12}) scale(${pop[0]} ${pop[1]})`}
          fill={color} stroke={ink.color} strokeWidth={ink.weight * 0.8} strokeLinejoin="round" />;
      })}
    </Canvas>
  );
}

export type ZzzProps = Mark & { every?: number; life?: number; rise?: number };
/** Sleep: letter Zs drawn as strokes, given off one every `every` frames, drifting up and to the side, growing and
 *  fading. `size` is the grown Z's height. */
export function Zzz({ x, y, at, len = 90, size = 70, every = 16, life: span = 44, rise = 200, color, f: fIn }: ZzzProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const items = spawnsAt(f, at, len, every, span);
  if (!items.length) return null;
  return (
    <Canvas>
      {items.map(({ i, age, k }) => {
        const s = size * (0.45 + 0.55 * k) / 2, zx = x + k * size * 1.2 + Math.sin(age * 0.18) * size * 0.2, zy = y - k * rise;
        const d = `M${-s * 0.8} ${-s} L${s * 0.8} ${-s} L${-s * 0.8} ${s} L${s * 0.8} ${s}`;
        return (
          <g key={i} transform={`translate(${fx(zx)} ${fx(zy)}) rotate(${-12 + 8 * Math.sin(age * 0.2)})`} opacity={Math.min(1, age / 4) * fadeOut(k, 0.3)}
            fill="none" strokeLinecap="round" strokeLinejoin="round">
            <path d={d} stroke={ink.color} strokeWidth={s * 0.32 + ink.weight * 1.4} />
            <path d={d} stroke={color ?? ink.paper} strokeWidth={s * 0.32} />
          </g>
        );
      })}
    </Canvas>
  );
}

const dropPath = (s: number) =>
  `M0 ${-s} C${s * 0.25} ${-s * 0.4} ${s * 0.55} ${-s * 0.05} ${s * 0.55} ${s * 0.3} A${s * 0.55} ${s * 0.55} 0 0 1 ${-s * 0.55} ${s * 0.3} C${-s * 0.55} ${-s * 0.05} ${-s * 0.25} ${-s * 0.4} 0 ${-s}Z`;

export type TearsProps = Mark & { kind?: "stream" | "drops"; gap?: number; fall?: number };
/** Crying from two eyes `gap` apart at (x, y): "stream" two flowing bands pouring outward and down `fall`, "drops"
 *  tear drops flung out sideways on arcs. */
export function Tears({ x, y, at, len = 60, size = 40, kind = "stream", gap = 140, fall = 260, color = "#9FD8F2", seed = "tears", f: fIn }: TearsProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at;
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      {[-1, 1].map((side) => {
        const ex = x + (side * gap) / 2;
        if (kind === "stream") {
          const grow = clamp01(j / 8), spread = size * 1.6;
          const d = `M${ex} ${y} C${ex + side * spread * 0.8} ${y + fall * 0.05} ${ex + side * spread} ${y + fall * 0.35} ${ex + side * spread * 1.05} ${y + fall}`;
          return (
            <g key={side} fill="none" strokeLinecap="round">
              <path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - grow} stroke={ink.color} strokeWidth={size * 0.7 + ink.weight * 1.4} />
              <path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - grow} stroke={color} strokeWidth={size * 0.7} />
              <path d={d} pathLength={1} strokeDasharray="0.05 0.11" strokeDashoffset={-j * 0.025} stroke={ink.paper} strokeWidth={size * 0.16} opacity={grow < 1 ? 0 : 1} />
            </g>
          );
        }
        return spawnsAt(f, at, len, 4, 16).map(({ i, age }) => {
          const t = age / 30, vx = 520 + 260 * random(`${seed}${side}v${i}`), vy = 300 + 200 * random(`${seed}${side}u${i}`);
          const dx = side * vx * t, dy = -vy * t + 0.5 * 2600 * t * t, ang = (Math.atan2(-vy + 2600 * t, side * vx) * 180) / Math.PI + 90;
          const s = size * (0.6 + 0.3 * random(`${seed}${side}s${i}`)) * Math.min(1, age / 2);
          return <path key={`${side}${i}`} d={dropPath(s)} transform={`translate(${fx(ex + dx)} ${fx(y + dy)}) rotate(${fx(ang + 180)})`}
            fill={color} stroke={ink.color} strokeWidth={ink.weight * 0.7} strokeLinejoin="round" />;
        });
      })}
    </Canvas>
  );
}
export type GloomLinesProps = Mark & { n?: number; reach?: number; cloud?: string };
/** Gloom over a head whose top is at (x, y): a small dark cloud and wavering vertical lines dropping down from it
 *  `reach` px. `size` is the cloud's width. */
export function GloomLines({ x, y, at, len = 60, size = 220, n = 7, reach = 300, color, cloud = "#6B6577", seed = "gloom", f: fIn }: GloomLinesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at, two = Math.floor(j / 2), cy = y - size * 0.35, bob = Math.sin(j * 0.15) * size * 0.03;
  const pop = popAt(j) ?? [0, 0];
  const bumps = Array.from({ length: 5 }, (_, i) => {
    const u = i / 4 - 0.5;
    return { cx: x + u * size * 0.75, cy: cy + bob - (1 - 4 * u * u) * size * 0.12, r: size * (0.17 + 0.05 * random(`${seed}b${i}`)) };
  });
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      <g stroke={color ?? ink.color} strokeLinecap="round" fill="none" opacity={0.6}>
        {Array.from({ length: n }, (_, i) => {
          const lx = x + (i / Math.max(1, n - 1) - 0.5) * size * 0.85, top = cy + size * 0.15;
          const grow = clamp01((j - 3 - 2 * random(`${seed}g${i}`) * 3) / 10), l = reach * (0.55 + 0.45 * random(`${seed}l${i}`)) * grow;
          if (l < 2) return null;
          const w = (random(`${seed}${i}:${two}`) - 0.5) * size * 0.05;
          return <path key={i} d={`M${fx(lx)} ${fx(top)} q${fx(w)} ${fx(l / 2)} 0 ${fx(l)}`} strokeWidth={ink.weight * (i % 2 ? 0.4 : 0.6)} />;
        })}
      </g>
      <g transform={`translate(${x} ${cy}) scale(${pop[0]} ${pop[1]}) translate(${-x} ${-cy})`}>
        {bumps.map((b, i) => <circle key={"e" + i} cx={b.cx} cy={b.cy} r={b.r + ink.weight * 0.7} fill={ink.color} />)}
        {bumps.map((b, i) => <circle key={"f" + i} cx={b.cx} cy={b.cy} r={b.r} fill={cloud} />)}
      </g>
    </Canvas>
  );
}

export type ShockLinesProps = Mark & { n?: number; arc?: number };
/** A start: short ticks bursting round a head centred at (x, y), `size` its radius, over the top `arc` degrees,
 *  shooting out and then trembling on twos. */
export function ShockLines({ x, y, at, len = 24, size = 170, n = 9, arc = 220, color, seed = "shock", f: fIn }: ShockLinesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at, out = 1 - Math.exp(-j / 1.5), two = Math.floor(j / 2);
  return (
    <Canvas opacity={fadeOut(k, 0.25)}>
      <g stroke={color ?? ink.color} strokeWidth={ink.weight * 1.2} strokeLinecap="round">
        {Array.from({ length: n }, (_, i) => {
          const a = ((-90 - arc / 2 + (arc * i) / Math.max(1, n - 1)) * Math.PI) / 180;
          const r0 = size * (0.85 + 0.25 * out) + size * 0.06 * random(`${seed}${i}:${two}`), l = size * (0.22 + 0.14 * random(`${seed}l${i}`)) * out;
          return <line key={i} x1={fx(x + Math.cos(a) * r0)} y1={fx(y + Math.sin(a) * r0)} x2={fx(x + Math.cos(a) * (r0 + l))} y2={fx(y + Math.sin(a) * (r0 + l))} />;
        })}
      </g>
    </Canvas>
  );
}

export type DizzyStarsProps = Mark & { n?: number; speed?: number };
/** Stars circling above a head on a flat ellipse round (x, y), `size` wide; those behind are smaller and dimmer. */
export function DizzyStars({ x, y, at, len = 60, size = 260, n = 3, speed = 0.16, color, f: fIn }: DizzyStarsProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const j = f - at, rx = size / 2, ry = size * 0.16, grow = Math.min(1, j / 5);
  const stars = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * 2 * Math.PI + speed * j, depth = (Math.sin(a) + 1) / 2;
    return { i, sx: x + Math.cos(a) * rx * grow, sy: y + Math.sin(a) * ry * grow, depth };
  }).sort((p, q) => p.depth - q.depth);
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      <ellipse cx={x} cy={y} rx={rx * grow} ry={ry * grow} fill="none" stroke={ink.color} strokeWidth={ink.weight * 0.5} strokeDasharray={`${ink.weight * 2} ${ink.weight * 2.5}`} opacity={0.45} />
      {stars.map((s) => {
        const r = size * 0.11 * (0.7 + 0.45 * s.depth) * grow;
        return <path key={s.i} d={starPath(r)} transform={`translate(${fx(s.sx)} ${fx(s.sy)}) rotate(${(j * 9 + s.i * 30) % 360})`}
          fill={color ?? ink.spark} stroke={ink.color} strokeWidth={Math.max(ink.weight * 0.5, r * 0.13)} strokeLinejoin="round" opacity={0.55 + 0.45 * s.depth} />;
      })}
    </Canvas>
  );
}
export type IdeaBulbProps = Mark & { rays?: number; click?: number };
/** An idea: a light bulb that pops on over a head at (x, y), lights `click` frames later and throws pulsing rays.
 *  `size` is the bulb's height. */
export function IdeaBulb({ x, y, at, len = 45, size = 150, rays = 8, click = 4, color, f: fIn }: IdeaBulbProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  const pop = popAt(f - at, 0.2);
  if (k < 0 || !pop) return null;
  const j = f - at, lit = j >= click, r = size * 0.32, cy = -size * 0.12, two = Math.floor(j / 2);
  const glass = `M${-r * 0.45} ${cy + r * 1.25} L${-r * 0.45} ${cy + r * 0.9} A${r} ${r} 0 1 1 ${r * 0.45} ${cy + r * 0.9} L${r * 0.45} ${cy + r * 1.25}Z`;
  const base = Array.from({ length: 3 }, (_, i) => ({ y: cy + r * (1.25 + 0.24 * i), w: r * (0.95 - 0.12 * i) }));
  return (
    <Canvas opacity={fadeOut(k, 0.15)}>
      <g transform={`translate(${x} ${y}) scale(${pop[0]} ${pop[1]})`} stroke={ink.color} strokeLinejoin="round" strokeLinecap="round">
        {lit ? <circle cx={0} cy={cy} r={r * 1.7} fill={color ?? ink.spark} stroke="none" opacity={0.25} /> : null}
        {lit ? Array.from({ length: rays }, (_, i) => {
          const a = ((-90 - 120 + (240 * i) / Math.max(1, rays - 1)) * Math.PI) / 180;
          const r0 = r * 1.35, l = r * (0.45 + 0.2 * ((i + two) % 2)) * Math.min(1, (j - click + 1) / 3);
          return <line key={i} x1={Math.cos(a) * r0} y1={cy + Math.sin(a) * r0} x2={Math.cos(a) * (r0 + l)} y2={cy + Math.sin(a) * (r0 + l)} strokeWidth={ink.weight * 1.1} />;
        }) : null}
        {base.map((b, i) => <rect key={i} x={-b.w / 2} y={b.y} width={b.w} height={r * 0.24} rx={r * 0.1} fill="#B9B4AA" strokeWidth={ink.weight * 0.8} />)}
        <path d={glass} fill={lit ? color ?? ink.spark : ink.paper} strokeWidth={ink.weight} />
        <path d={`M${-r * 0.22} ${cy + r * 1.1} L${-r * 0.22} ${cy + r * 0.35} l${r * 0.15} ${-r * 0.2} l${r * 0.15} ${r * 0.2} l${r * 0.15} ${-r * 0.2} L${r * 0.22} ${cy + r * 1.1}`}
          fill="none" strokeWidth={ink.weight * 0.5} opacity={0.8} />
        <path d={`M${-r * 0.55} ${cy - r * 0.25} A${r * 0.6} ${r * 0.6} 0 0 1 ${-r * 0.1} ${cy - r * 0.68}`} fill="none" stroke={ink.paper} strokeWidth={ink.weight * 0.9} />
      </g>
    </Canvas>
  );
}

export type MusicNotesProps = Mark & { every?: number; life?: number; rise?: number };
/** Humming: eighth notes and beamed pairs given off one every `every` frames, drifting up and swaying. */
export function MusicNotes({ x, y, at, len = 90, size = 80, every = 12, life: span = 38, rise = 260, color, seed = "notes", f: fIn }: MusicNotesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const items = spawnsAt(f, at, len, every, span);
  if (!items.length) return null;
  const head = color ?? ink.color;
  return (
    <Canvas>
      {items.map(({ i, age, k }) => {
        const s = size * (0.8 + 0.3 * random(`${seed}s${i}`)), side = random(`${seed}d${i}`) > 0.5 ? 1 : -1;
        const nx = x + side * k * size * 0.9 + Math.sin(age * 0.22 + i) * size * 0.3, ny = y - k * rise;
        const hr = s * 0.2, stem = s * 0.85, pair = i % 2 === 1;
        const heads = pair ? [0, s * 0.62] : [0];
        return (
          <g key={i} transform={`translate(${fx(nx)} ${fx(ny)}) rotate(${10 * Math.sin(age * 0.25)}) scale(${Math.min(1, age / 4)})`}
            opacity={fadeOut(k, 0.3)} stroke={ink.color} strokeLinecap="round" strokeLinejoin="round">
            {heads.map((hx, h) => <line key={"s" + h} x1={hx + hr * 0.9} y1={-hr * 0.2} x2={hx + hr * 0.9} y2={-stem - (pair ? hx * 0.15 : 0)} strokeWidth={ink.weight * 0.9} />)}
            {pair ? <path d={`M${hr * 0.9} ${-stem} L${s * 0.62 + hr * 0.9} ${-stem - s * 0.09}`} strokeWidth={hr * 0.75} />
              : <path d={`M${hr * 0.9} ${-stem} q${s * 0.32} ${s * 0.18} ${s * 0.22} ${s * 0.5}`} fill="none" strokeWidth={ink.weight * 0.9} />}
            {heads.map((hx, h) => <ellipse key={"h" + h} cx={hx} cy={0} rx={hr * 1.2} ry={hr * 0.85} transform={`rotate(-22 ${hx} 0)`} fill={head} strokeWidth={ink.weight * 0.5} />)}
          </g>
        );
      })}
    </Canvas>
  );
}
// ------------------------------------------------------------------ impact

export type PoofProps = Mark & { n?: number };
/** Something appears or vanishes at (x, y): a cloud puff that swells, then breaks into curls flying apart. `size`
 *  is the puff's width; hide the thing under it around 40% of `len`. */
export function Poof({ x, y, at, len = 22, size = 300, n = 7, color, seed = "poof", f: fIn }: PoofProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const k = life(f, at, len);
  if (k < 0) return null;
  const R = size / 2, swell = 1 - Math.pow(1 - Math.min(1, k / 0.4), 3), fade = k < 0.4 ? 1 : Math.max(0, 1 - (k - 0.4) / 0.25);
  const fill = color ?? ink.paper;
  const bumps = [{ cx: x, cy: y, r: R * 0.5 }, ...Array.from({ length: n }, (_, i) => {
    const a = (i / n) * 2 * Math.PI + random(`${seed}a${i}`) * 0.4, d = R * 0.5 * swell;
    return { cx: x + Math.cos(a) * d, cy: y + Math.sin(a) * d * 0.8, r: R * (0.3 + 0.1 * random(`${seed}r${i}`)) };
  })].map((b) => ({ ...b, r: b.r * swell * (0.8 + 0.2 * fade) }));
  const curls = k > 0.45 ? Array.from({ length: n }, (_, i) => {
    const q = (k - 0.45) / 0.55, a = ((i + 0.5) / n) * 2 * Math.PI + random(`${seed}c${i}`) * 0.5;
    const d = R * (0.85 + 0.7 * (1 - Math.pow(1 - q, 2))), c = R * 0.16 * (1 - 0.6 * q) * (0.8 + 0.4 * random(`${seed}s${i}`));
    return { x: x + Math.cos(a) * d, y: y + Math.sin(a) * d * 0.8, c, rot: (a * 180) / Math.PI + q * 120, o: 1 - q };
  }) : [];
  return (
    <Canvas>
      <g opacity={fade}>
      {bumps.map((b, i) => (b.r > 0.5 ? <circle key={"e" + i} cx={b.cx} cy={b.cy} r={b.r + ink.weight * 0.8} fill={ink.color} /> : null))}
      {bumps.map((b, i) => (b.r > 0.5 ? <circle key={"f" + i} cx={b.cx} cy={b.cy} r={b.r} fill={fill} /> : null))}
      </g>
      {curls.map((c, i) => {
        const d = `M${-c.c} 0 A${c.c} ${c.c} 0 1 1 0 ${c.c} A${c.c * 0.5} ${c.c * 0.5} 0 0 1 ${-c.c * 0.4} ${c.c * 0.1}`;
        return (
          <g key={"c" + i} transform={`translate(${fx(c.x)} ${fx(c.y)}) rotate(${fx(c.rot)})`} opacity={c.o} fill="none" strokeLinecap="round">
            <path d={d} stroke={ink.color} strokeWidth={c.c * 0.45 + ink.weight * 1.2} />
            <path d={d} stroke={fill} strokeWidth={c.c * 0.45} />
          </g>
        );
      })}
    </Canvas>
  );
}

const wedges = (ws: Pt[][], fill: string) =>
  ws.map((w, i) => <polygon key={i} points={w.map((p) => `${fx(p[0])},${fx(p[1])}`).join(" ")} fill={fill} />);

export type ImpactFlashProps = { x: number; y: number; w: number; h: number; at: number; len?: number; cx?: number; cy?: number; n?: number; seed?: string; f?: number };
/** An impact frame over the area for `len` frames (1 to 3): paper-white with radial ink lines from (cx, cy), new
 *  lines every frame, the last frame thinner; then gone. */
export function ImpactFlash({ x, y, w, h, at, len = 3, cx, cy, n = 40, seed = "impact", f: fIn }: ImpactFlashProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const span = Math.max(1, Math.min(3, Math.round(len)));
  const lines = focusLinesAt(f, at, span, { x, y, w, h }, { cx, cy, n, inner: 0.06, width: 0.05, hold: 1, seed });
  if (!lines.length) return null;
  const last = span > 1 && f - at === span - 1;
  return (
    <Canvas opacity={last ? 0.6 : 1}>
      <rect x={x} y={y} width={w} height={h} fill={ink.paper} />
      <svg x={x} y={y} width={w} height={h} viewBox={`${x} ${y} ${w} ${h}`} overflow="hidden">{wedges(lines, ink.color)}</svg>
    </Canvas>
  );
}

export type FocusLinesProps = { x: number; y: number; w: number; h: number; at: number; len?: number; cx?: number; cy?: number; n?: number; inner?: number; width?: number; color?: string; seed?: string; f?: number };
/** Manga concentration lines round the edge of the area pointing at (cx, cy) (default its centre), the middle an
 *  ellipse `inner` of the half-size left clear, boiling on twos. */
export function FocusLines({ x, y, w, h, at, len = 60, cx, cy, n = 72, inner = 0.6, width = 0.022, color, seed = "focus", f: fIn }: FocusLinesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const lines = focusLinesAt(f, at, len, { x, y, w, h }, { cx, cy, n, inner, width, hold: 2, seed });
  if (!lines.length) return null;
  return (
    <Canvas opacity={Math.min(1, (f - at + 1) / 2)}>
      <svg x={x} y={y} width={w} height={h} viewBox={`${x} ${y} ${w} ${h}`} overflow="hidden">{wedges(lines, color ?? ink.color)}</svg>
    </Canvas>
  );
}
