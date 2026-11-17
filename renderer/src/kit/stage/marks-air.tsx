// Weather and air drawn in the drawings' line over an area: rain, snow, confetti, petals or leaves, bubbles. Each
// area is pre-filled at `at` (the rain is already falling) and fades in and out over a few frames.
import React from "react";
import { random, useCurrentFrame } from "remotion";
import { useLineStyle } from "./drawn";
import { clamp01 } from "./time";

const Canvas = ({ children, opacity }: { children: React.ReactNode; opacity?: number }) => (
  <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", opacity }}>{children}</svg>
);
const useFrame = (fIn?: number) => {
  const now = useCurrentFrame();
  return fIn ?? now;
};
const fx = (v: number) => v.toFixed(1);
const mod = (a: number, b: number) => ((a % b) + b) % b;
const envelope = (f: number, at: number, len: number, fade = 6) =>
  Math.min(clamp01((f - at + 1) / fade), Number.isFinite(len) ? clamp01((at + len - f) / fade) : 1);

export type AirArea = { x: number; y: number; w: number; h: number };
export type Fall = { i: number; x: number; y: number; cycle: number; j: number; seed: number; splash: { x: number; age: number } | null };
export type FallOptions = { n?: number; speed?: number; slant?: number; sway?: number; swayPeriod?: number; pad?: number; splashLen?: number; seed?: string };

/** Things falling through `area` at frame f: `n` of them at about `speed` px a frame, drifting `slant` px across per
 *  px down and swaying `sway` px; each comes back at the top when it lands, with a `splash` for `splashLen` frames
 *  where it landed. Empty before `at` and from `at + len`. */
export const fallAt = (f: number, at: number, len: number, area: AirArea, o: FallOptions = {}): Fall[] => {
  if (f < at || f >= at + len) return [];
  const { x, y, w, h } = area, n = o.n ?? 60, pad = o.pad ?? 0, seed = o.seed ?? "fall", j = f - at;
  const travel = h + pad, slant = o.slant ?? 0, sway = o.sway ?? 0, period = o.swayPeriod ?? 60, splashLen = o.splashLen ?? 0;
  const xAt = (i: number, cyc: number, d: number, t: number) =>
    x + mod(random(`${seed}x${i}:${cyc}`) * w + slant * d + sway * Math.sin((2 * Math.PI * t) / period + 6.28 * random(`${seed}w${i}`)), w);
  return Array.from({ length: n }, (_, i) => {
    const v = (o.speed ?? 20) * (0.8 + 0.4 * random(`${seed}v${i}`));
    const pos = random(`${seed}p${i}`) * travel + v * j, cycle = Math.floor(pos / travel), d = pos - cycle * travel;
    const age = d / v;
    const splash = splashLen > 0 && cycle > 0 && age < splashLen ? { x: xAt(i, cycle - 1, travel, j - age), age } : null;
    return { i, x: xAt(i, cycle, d, j), y: y - pad + d, cycle, j, seed: random(`${seed}s${i}:${cycle}`), splash };
  });
};

export type Rise = { i: number; x: number; y: number; r: number; pop: number | null };
/** Bubbles rising from the bottom of `area` at frame f, wobbling `wobble` px, each popping at its own height (the
 *  `pop` age in frames while it bursts, for `popLen` frames) and rising again a little later. Empty before `at`. */
export const riseAt = (f: number, at: number, len: number, area: AirArea, o: { n?: number; speed?: number; size?: number; wobble?: number; popLen?: number; seed?: string } = {}): Rise[] => {
  if (f < at || f >= at + len) return [];
  const { x, y, w, h } = area, n = o.n ?? 14, seed = o.seed ?? "rise", size = o.size ?? 40, popLen = o.popLen ?? 5, j = f - at;
  const out: Rise[] = [];
  for (let i = 0; i < n; i++) {
    const v = (o.speed ?? 5) * (0.7 + 0.6 * random(`${seed}v${i}`)), top = h * (0.35 + 0.6 * random(`${seed}t${i}`));
    const travel = top + v * popLen + h * 0.3 * random(`${seed}g${i}`);
    const pos = random(`${seed}p${i}`) * travel + v * j, cyc = Math.floor(pos / travel), d = pos - cyc * travel;
    const r = size * (0.45 + 0.55 * random(`${seed}r${i}:${cyc}`)) / 2;
    const bx = x + r + random(`${seed}x${i}:${cyc}`) * Math.max(0, w - 2 * r) + (o.wobble ?? size * 0.3) * Math.sin(d / (size * 0.9) + i);
    if (d < top) out.push({ i, x: bx, y: y + h - r - d, r, pop: null });
    else if (d < top + v * popLen) out.push({ i, x: bx, y: y + h - r - top, r, pop: (d - top) / v });
  }
  return out;
};

type AirProps = { x: number; y: number; w: number; h: number; at: number; len?: number; n?: number; size?: number; color?: string; seed?: string; f?: number };

export type RainProps = AirProps & { speed?: number; slant?: number; splash?: boolean };
/** Rain over the area: slanted streaks (`size` long) falling `speed` px a frame, with small splashes on its floor. */
export function Rain({ x, y, w, h, at, len = Infinity, n = 70, size = 70, speed = 46, slant = 0.18, splash = true, color, seed = "rain", f: fIn }: RainProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const drops = fallAt(f, at, len, { x, y, w, h }, { n, speed, slant, pad: size, splashLen: splash ? 6 : 0, seed });
  if (!drops.length) return null;
  const c = color ?? ink.color, k = Math.hypot(1, slant);
  return (
    <Canvas opacity={envelope(f, at, len)}>
      <svg x={x} y={y} width={w} height={h} viewBox={`${x} ${y} ${w} ${h}`} overflow="hidden"><g stroke={c} strokeLinecap="round">
        {drops.map((d) => {
          const l = size * (0.6 + 0.6 * d.seed), dx = (slant * l) / k, dy = l / k, cut = Math.max(0, d.y - (y + h));
          return (
            <g key={d.i}>
              {d.y - dy < y + h ? <line x1={fx(d.x - dx)} y1={fx(d.y - dy)} x2={fx(d.x - slant * cut)} y2={fx(Math.min(d.y, y + h))} strokeWidth={ink.weight * 0.3} opacity={0.55} /> : null}
              {d.splash && random(`${seed}k${d.i}`) < 0.45 ? [-1, 0, 1].map((s) => {
                const q = d.splash!.age / 6, r0 = size * 0.08 * (0.5 + q), r1 = r0 + size * 0.14 * (1 - q), a = -Math.PI / 2 + s * 0.8;
                return <line key={s} x1={fx(d.splash!.x + Math.cos(a) * r0)} y1={fx(y + h + Math.sin(a) * r0)} x2={fx(d.splash!.x + Math.cos(a) * r1)}
                  y2={fx(y + h + Math.sin(a) * r1)} strokeWidth={ink.weight * 0.45} opacity={1 - q} />;
              }) : null}
            </g>
          );
        })}
      </g></svg>
    </Canvas>
  );
}

export type SnowProps = AirProps & { speed?: number; sway?: number };
/** Snow over the area: round flakes (up to `size` across) with a fine ink edge, drifting down and swaying. */
export function Snow({ x, y, w, h, at, len = Infinity, n = 46, size = 26, speed = 2.6, sway = 40, color, seed = "snow", f: fIn }: SnowProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const flakes = fallAt(f, at, len, { x, y, w, h }, { n, speed, sway, swayPeriod: 80, pad: size, seed });
  if (!flakes.length) return null;
  return (
    <Canvas opacity={envelope(f, at, len)}>
      {flakes.map((d) => {
        const r = (size / 2) * (0.4 + 0.6 * random(`${seed}r${d.i}`));
        return <circle key={d.i} cx={fx(d.x)} cy={fx(d.y)} r={fx(r)} fill={color ?? ink.paper} stroke={ink.color} strokeWidth={Math.min(ink.weight * 0.22, r * 0.18)} />;
      })}
    </Canvas>
  );
}

const CONFETTI = ["#FF6F91", "#FFD45C", "#5CC8FF", "#7ED957", "#B98CFF"];

export type ConfettiProps = Omit<AirProps, "color"> & { colors?: string[]; speed?: number; sway?: number };
/** Confetti over the area: paper bits (`size` long) in `colors`, tumbling (they flip edge-on and back) as they fall. */
export function Confetti({ x, y, w, h, at, len = Infinity, n = 60, size = 34, colors = CONFETTI, speed = 7, sway = 30, seed = "confetti", f: fIn }: ConfettiProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const bits = fallAt(f, at, len, { x, y, w, h }, { n, speed, sway, swayPeriod: 50, pad: size, seed });
  if (!bits.length) return null;
  return (
    <Canvas opacity={envelope(f, at, len)}>
      {bits.map((d) => {
        const rate = 0.12 + 0.2 * random(`${seed}t${d.i}`), flip = Math.cos(d.j * rate + d.seed * 6.28), l = size * (0.7 + 0.5 * d.seed);
        const rot = (d.seed * 360 + d.j * (random(`${seed}o${d.i}`) - 0.5) * 14) % 360;
        return <rect key={d.i} x={-l / 2} y={(-l * 0.3) * Math.abs(flip)} width={l} height={Math.max(1, l * 0.6 * Math.abs(flip))}
          transform={`translate(${fx(d.x)} ${fx(d.y)}) rotate(${fx(rot)})`} fill={colors[Math.floor(d.seed * colors.length) % colors.length]}
          stroke={ink.color} strokeWidth={ink.weight * 0.3} strokeLinejoin="round" />;
      })}
    </Canvas>
  );
}

const PETAL = ["#FFB7C9", "#FFC9D6", "#F7A1B8"];
const LEAF = ["#E8833A", "#D9542B", "#E8B53A", "#B5642A"];

export type PetalsProps = Omit<AirProps, "color"> & { kind?: "petal" | "leaf"; colors?: string[]; speed?: number; sway?: number; slant?: number };
/** Blossom petals or autumn leaves (`kind`) over the area, drifting down on the wind (`slant`), swaying and turning. */
export function Petals({ x, y, w, h, at, len = Infinity, n = 26, size = 46, kind = "petal", colors, speed = 3.2, sway = 70, slant = 0.35, seed = "petals", f: fIn }: PetalsProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const bits = fallAt(f, at, len, { x, y, w, h }, { n, speed, sway, slant, swayPeriod: 70, pad: size, seed });
  if (!bits.length) return null;
  const pal = colors ?? (kind === "leaf" ? LEAF : PETAL);
  return (
    <Canvas opacity={envelope(f, at, len)}>
      {bits.map((d) => {
        const s = (size / 2) * (0.7 + 0.5 * d.seed), turn = Math.cos(d.j * (0.06 + 0.08 * random(`${seed}t${d.i}`)) + d.seed * 6.28);
        const rot = d.seed * 360 + 35 * Math.sin(d.j * 0.05 + d.i);
        const body = kind === "leaf"
          ? `M${-s} 0 Q${-s * 0.2} ${-s * 0.75} ${s} 0 Q${-s * 0.2} ${s * 0.75} ${-s} 0Z`
          : `M${-s} 0 Q${-s * 0.3} ${-s * 0.7} ${s * 0.75} ${-s * 0.32} L${s * 0.45} 0 L${s * 0.75} ${s * 0.32} Q${-s * 0.3} ${s * 0.7} ${-s} 0Z`;
        return (
          <g key={d.i} transform={`translate(${fx(d.x)} ${fx(d.y)}) rotate(${fx(rot)}) scale(1 ${fx(Math.max(0.12, Math.abs(turn)))})`}
            stroke={ink.color} strokeWidth={ink.weight * 0.22} strokeLinejoin="round" strokeLinecap="round">
            <path d={body} fill={pal[Math.floor(d.seed * pal.length) % pal.length]} />
            {kind === "leaf" ? <path d={`M${-s * 1.25} 0 L${s * 0.7} 0`} fill="none" /> : null}
          </g>
        );
      })}
    </Canvas>
  );
}

export type BubblesProps = AirProps & { speed?: number; wobble?: number };
/** Bubbles rising through the area from its floor (up to `size` across), wobbling, each popping at its own height. */
export function Bubbles({ x, y, w, h, at, len = Infinity, n = 14, size = 70, speed = 5, wobble, color, seed = "bubbles", f: fIn }: BubblesProps) {
  const ink = useLineStyle();
  const f = useFrame(fIn);
  const bs = riseAt(f, at, len, { x, y, w, h }, { n, speed, size, wobble, seed });
  if (!bs.length) return null;
  return (
    <Canvas opacity={envelope(f, at, len)}>
      {bs.map((b) => {
        if (b.pop !== null) {
          const q = b.pop / 5;
          return (
            <g key={b.i} stroke={ink.color} strokeWidth={ink.weight * 0.5} strokeLinecap="round" opacity={1 - q}>
              {Array.from({ length: 6 }, (_, t) => {
                const a = (t / 6) * 2 * Math.PI + 0.3, r0 = b.r * (0.8 + 0.6 * q), r1 = r0 + b.r * 0.4;
                return <line key={t} x1={fx(b.x + Math.cos(a) * r0)} y1={fx(b.y + Math.sin(a) * r0)} x2={fx(b.x + Math.cos(a) * r1)} y2={fx(b.y + Math.sin(a) * r1)} />;
              })}
            </g>
          );
        }
        return (
          <g key={b.i}>
            <circle cx={fx(b.x)} cy={fx(b.y)} r={fx(b.r)} fill={color ?? ink.paper} fillOpacity={0.35} stroke={ink.color} strokeWidth={ink.weight * 0.5} />
            <path d={`M${fx(b.x - b.r * 0.6)} ${fx(b.y - b.r * 0.1)} A${fx(b.r * 0.6)} ${fx(b.r * 0.6)} 0 0 1 ${fx(b.x - b.r * 0.1)} ${fx(b.y - b.r * 0.6)}`}
              fill="none" stroke={ink.paper} strokeWidth={Math.max(2, b.r * 0.16)} strokeLinecap="round" />
          </g>
        );
      })}
    </Canvas>
  );
}
