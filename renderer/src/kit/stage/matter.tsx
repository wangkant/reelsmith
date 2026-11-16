// Matter inside a photograph: vapour that rises and thins, light that falls off and flickers, embers, and liquid
// that drops or pours under gravity. Each is shaded like the picture around it (soft, blended, never outlined),
// deterministic per frame and drawn not at all when idle.
import React, { useId } from "react";
import { random, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { mixColor, seedInt } from "./geom";
import { clamp01, lerp } from "./time";

const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" };

/** Smooth value noise in 0..1 at time t (units of t = one change). */
const vnoise = (seed: string, t: number): number => {
  const i = Math.floor(t), fr = t - i, s = fr * fr * (3 - 2 * fr);
  return lerp(random(`${seed}:${i}`), random(`${seed}:${i + 1}`), s);
};

/** Opacity stops of a soft round falloff (close to a gaussian, no visible rim). */
const SOFT: [number, number][] = [[0, 1], [0.2, 0.86], [0.4, 0.58], [0.6, 0.3], [0.8, 0.1], [1, 0]];

const useIdent = (p: string) => p + useId().replace(/[^A-Za-z0-9_-]/g, "");

export type VaporProps = {
  /** where it leaves (stage px) and how wide the source is */
  x: number; y: number;
  w?: number;
  /** 0..1 how much (0 draws nothing) */
  amount?: number;
  /** how high it climbs before it has thinned away, and the size of a puff as it leaves, in px */
  rise?: number;
  size?: number;
  /** puffs alive at once, and the seconds one lives */
  n?: number;
  life?: number;
  /** sideways drift in px reached by the top, and how much the air curls the shapes (0..1) */
  wind?: number;
  curl?: number;
  color?: string;
  /** screen: steam and breath against a darker picture; multiply or normal: smoke */
  blend?: "screen" | "normal" | "multiply";
  seed?: string;
  f?: number;
};

/** Steam, smoke or breath: soft puffs that rise, slow, spread with the wind, thin out and fade, their edges torn
 *  into wisps by moving noise instead of drawn as curls. */
export function Vapor({ x, y, w = 80, amount = 0.6, rise = 420, size = 50, n = 18, life = 2.6, wind = 60, curl = 0.6,
  color = "#F4F1EC", blend = "screen", seed = "vp", f: fIn }: VaporProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w: cw, h: ch, fps } = useClip();
  const id = useIdent("va");
  if (!(amount > 0) || !(n > 0) || !(life > 0)) return null;
  const t = f / (fps || 30);
  const speed = rise / life;
  const d = t * speed * 0.7;                                  // the noise climbs with the vapour
  const reach = rise + size * 3, side = w + Math.abs(wind) + rise * 0.5 + size * 3;
  const box = { x: x - side, y: y - reach - size * 2, width: side * 2, height: reach + size * 4 };
  const puffs = Array.from({ length: n }, (_, i) => {
    const run = t / life + i / n + random(`${seed}j${i}`) * 0.3;
    const gen = Math.floor(run), a = run - gen;              // this puff's age 0..1; each generation is new
    const r = (k: string) => random(`${seed}${k}${i}:${gen}`);
    const lift = 1 - Math.pow(1 - a, 1.5);
    const px = x + (r("x") - 0.5) * w * (1 + a) + wind * a * a + Math.sin(t * 1.3 + i * 2.1) * size * 0.35 * a;
    const py = y - rise * lift * (0.75 + 0.5 * r("h"));
    const rad = size * (0.55 + 2.1 * a) * (0.7 + 0.6 * r("s"));
    const op = amount * 0.5 * clamp01(a / 0.12) * Math.pow(1 - a, 1.4) * (0.6 + 0.4 * r("o"));
    return { px, py, rx: rad * (0.85 + 0.15 * a), ry: rad * (1.3 + 0.7 * a), op, rot: (r("r") - 0.5) * 36 };
  });
  return (
    <svg width={cw} height={ch} style={{ ...full, mixBlendMode: blend }}>
      <defs>
        <radialGradient id={id + "g"}>
          {SOFT.map(([o, a]) => <stop key={o} offset={o} stopColor={color} stopOpacity={a} />)}
        </radialGradient>
        <filter id={id} filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" x={box.x} y={box.y + d} width={box.width} height={box.height}
          colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency={`${(1.5 / size).toFixed(5)} ${(0.4 / size).toFixed(5)}`} numOctaves={3} seed={seedInt(seed)} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={size * 2.4 * clamp01(curl)} xChannelSelector="R" yChannelSelector="G" result="d" />
          <feGaussianBlur in="d" stdDeviation={size * 0.08} />
        </filter>
      </defs>
      <g transform={`translate(0 ${-d})`} filter={`url(#${id})`}>
        <g transform={`translate(0 ${d})`}>
          {puffs.map((p, i) => p.op > 0.003 ? (
            <ellipse key={i} cx={p.px} cy={p.py} rx={p.rx} ry={p.ry} fill={`url(#${id}g)`} opacity={p.op}
              transform={`rotate(${p.rot.toFixed(1)} ${p.px.toFixed(1)} ${p.py.toFixed(1)})`} />
          ) : null)}
        </g>
      </g>
    </svg>
  );
}

export type GlowProps = {
  /** the light's centre and reach in stage px; squash < 1 flattens it (light pooled on a table) */
  x: number; y: number; r: number;
  squash?: number;
  /** 0..1 (0 draws nothing) */
  strength?: number;
  color?: string;
  /** a hotter colour at the centre (a filament, the heart of a fire) and how much of the reach it fills */
  core?: string;
  coreR?: number;
  /** 0..1 how much it flickers (firelight 0.5, a candle 0.3, a screen 0), and how fast in changes per second */
  flicker?: number;
  rate?: number;
  blend?: "screen" | "plus-lighter" | "overlay" | "soft-light";
  seed?: string;
  f?: number;
};

/** Light added to the picture: a warm falloff (bright near the source, a long soft tail, no rim) that can
 *  flicker. Put it over the thing that is lit, inside the plate, so it moves with it. */
export function Glow({ x, y, r, squash = 1, strength = 0.6, color = "#FFB46A", core = "#FFF1D6", coreR = 0.22, flicker = 0, rate = 7,
  blend = "screen", seed = "gl", f: fIn }: GlowProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { fps } = useClip();
  if (!(strength > 0) || !(r > 0)) return null;
  const t = (f / (fps || 30)) * rate;
  const fl = flicker > 0 ? 1 - flicker * (0.55 * vnoise(seed, t) + 0.45 * vnoise(seed + "b", t * 2.7)) : 1;
  const k = clamp01(strength * fl);
  const R = r * (flicker > 0 ? 0.94 + 0.06 * fl : 1);
  const grad = (c: string, a: number) => {
    const stops = Array.from({ length: 9 }, (_, i) => {
      const dd = i / 8, v = (1 / (1 + (dd * 3.2) ** 2) - 1 / (1 + 3.2 ** 2)) / (1 - 1 / (1 + 3.2 ** 2));
      return `${rgba(c, a * v)} ${(dd * 100).toFixed(1)}%`;
    });
    return `radial-gradient(closest-side, ${stops.join(", ")})`;
  };
  const spot = (rad: number, bg: string): React.CSSProperties => ({
    position: "absolute", left: x - rad, top: y - rad * squash, width: 2 * rad, height: 2 * rad * squash, background: bg, pointerEvents: "none",
  });
  return (
    <div style={{ ...full, mixBlendMode: blend }}>
      <div style={spot(R, grad(color, k))} />
      {coreR > 0 ? <div style={spot(R * coreR, grad(core, k * 0.9))} /> : null}
    </div>
  );
}

const rgba = (c: string, a: number): string => {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c.trim());
  if (m) {
    const n = parseInt(m[1].length === 3 ? [...m[1]].map((x) => x + x).join("") : m[1], 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${clamp01(a).toFixed(4)})`;
  }
  if (typeof CSS !== "undefined" && CSS.supports("color", c)) return `color-mix(in srgb, ${c} ${(clamp01(a) * 100).toFixed(2)}%, transparent)`;
  throw new Error(`Glow: cannot read the colour "${c}"; give a hex colour or a CSS colour name`);
};

export type EmbersProps = {
  /** the source: a line from (x, y) `w` wide (a fire bed, a grill, a chimney mouth) */
  x: number; y: number;
  w?: number;
  /** 0..1 (0 draws nothing); embers alive at once; seconds one lives */
  amount?: number;
  n?: number;
  life?: number;
  /** how high they climb, sideways drift by the top, ember radius, in px */
  rise?: number;
  wind?: number;
  size?: number;
  /** hot colour at birth and the colour they cool to */
  hot?: string;
  cool?: string;
  seed?: string;
  f?: number;
};

/** Sparks and embers lifting off a fire: small hot points with a short motion streak and a halo, swaying as they
 *  climb, cooling from yellow-white to red, winking out. Added as light. */
export function Embers({ x, y, w = 120, amount = 0.8, n = 18, life = 1.8, rise = 480, wind = 40, size = 3, hot = "#FFE9B0", cool = "#E0401A",
  seed = "em", f: fIn }: EmbersProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w: cw, h: ch, fps } = useClip();
  const id = useIdent("em");
  if (!(amount > 0) || !(n > 0) || !(life > 0)) return null;
  const sec = fps || 30, t = f / sec;
  const pos = (i: number, gen: number, a: number) => {
    const r = (k: string) => random(`${seed}${k}${i}:${gen}`);
    const up = rise * (0.6 + 0.6 * r("h")) * (1 - Math.pow(1 - a, 1.8));
    const sway = Math.sin(a * (5 + 4 * r("w")) + r("p") * 6.3) * 22 * a;
    return [x + (r("x") - 0.5) * w + wind * a * a + sway, y - up] as const;
  };
  return (
    <svg width={cw} height={ch} style={{ ...full, mixBlendMode: "screen" }}>
      <defs>
        {[["w", "#FFFFFF"], ["h", hot], ["c", cool]].map(([k, c]) => (
          <radialGradient key={k} id={id + k}>
            {SOFT.map(([o, a]) => <stop key={o} offset={o} stopColor={c} stopOpacity={a} />)}
          </radialGradient>
        ))}
      </defs>
      {Array.from({ length: n }, (_, i) => {
        const run = t / life + i / n + random(`${seed}j${i}`) * 0.5;
        const gen = Math.floor(run), a = run - gen;
        const [px, py] = pos(i, gen, a);
        const [qx, qy] = pos(i, gen, Math.max(0, a - 1.5 / (sec * life)));   // where it was half a shutter ago
        const len = Math.hypot(px - qx, py - qy), ang = (Math.atan2(py - qy, px - qx) * 180) / Math.PI;
        const wink = 0.65 + 0.35 * Math.sin(t * (9 + 7 * random(`${seed}f${i}`)) + i);
        const o = clamp01(amount * clamp01(a / 0.06) * (1 - a) ** 1.2 * wink);
        if (o < 0.01) return null;
        const cl = clamp01(a * 1.3);
        const s = size * (0.6 + 0.8 * random(`${seed}s${i}:${gen}`)) * (1 - 0.5 * a);
        const cx = (px + qx) / 2, cy = (py + qy) / 2;
        return (
          <g key={i} opacity={o} transform={`rotate(${ang.toFixed(1)} ${cx.toFixed(1)} ${cy.toFixed(1)})`}>
            <ellipse cx={cx} cy={cy} rx={s * 4 + len * 0.6} ry={s * 4} fill={`url(#${id}h)`} opacity={0.22 * (1 - cl)} />
            <ellipse cx={cx} cy={cy} rx={s * 4 + len * 0.6} ry={s * 4} fill={`url(#${id}c)`} opacity={0.22 * cl} />
            <ellipse cx={cx} cy={cy} rx={s + len / 2} ry={s * 0.8} fill={`url(#${id}h)`} opacity={1 - cl} />
            <ellipse cx={cx} cy={cy} rx={s + len / 2} ry={s * 0.8} fill={`url(#${id}c)`} opacity={cl} />
            <ellipse cx={cx} cy={cy} rx={s * 0.45 + len * 0.4} ry={s * 0.35} fill={`url(#${id}w)`} opacity={1 - cl * 0.8} />
          </g>
        );
      })}
    </svg>
  );
}

type LiquidLook = {
  /** the liquid's colour and how opaque its body is (water 0.4, oil 0.75, syrup or sauce 0.9) */
  color?: string;
  alpha?: number;
  /** gravity in px per second squared (about 2.5 frame heights a second squared reads as real) */
  g?: number;
};

/** Gradient defs shared by drops and streams: a darker rim, a lit body, a bright edge where light passes through. */
function LiquidDefs({ id, color, alpha }: { id: string; color: string; alpha: number }) {
  const lite = mixColor(color, "#FFFFFF", 0.45), deep = mixColor(color, "#000000", 0.45);
  return (
    <>
      <radialGradient id={id + "b"} cx="0.42" cy="0.4" r="0.62" fx="0.35" fy="0.3">
        <stop offset="0" stopColor={lite} stopOpacity={alpha * 0.9} />
        <stop offset="0.55" stopColor={color} stopOpacity={alpha} />
        <stop offset="0.86" stopColor={deep} stopOpacity={Math.min(1, alpha * 1.1)} />
        <stop offset="1" stopColor={lite} stopOpacity={alpha * 0.7} />
      </radialGradient>
      <radialGradient id={id + "p"} cx="0.5" cy="0.5" r="0.5" fx="0.45" fy="0.4">
        <stop offset="0" stopColor={lite} stopOpacity={alpha * 0.8} />
        <stop offset="0.5" stopColor={color} stopOpacity={alpha} />
        <stop offset="0.8" stopColor={deep} stopOpacity={alpha * 0.8} />
        <stop offset="1" stopColor={deep} stopOpacity={0} />
      </radialGradient>
      <radialGradient id={id + "w"}>
        {SOFT.map(([o, a]) => <stop key={o} offset={o} stopColor="#FFFFFF" stopOpacity={a} />)}
      </radialGradient>
    </>
  );
}

/** A teardrop of radius r whose tail stretches `k` radii above its round bottom at (0, 0). */
const tear = (r: number, k: number): string => {
  const top = -r - r * k;
  return `M0 ${top.toFixed(2)} C${(r * 0.35).toFixed(2)} ${(top + r * k * 0.55).toFixed(2)} ${r.toFixed(2)} ${(-r * 0.9).toFixed(2)} ${r.toFixed(2)} 0 `
    + `A${r.toFixed(2)} ${r.toFixed(2)} 0 0 1 ${(-r).toFixed(2)} 0 C${(-r).toFixed(2)} ${(-r * 0.9).toFixed(2)} ${(-r * 0.35).toFixed(2)} ${(top + r * k * 0.55).toFixed(2)} 0 ${top.toFixed(2)} Z`;
};

export type DropletProps = LiquidLook & {
  /** the lip it hangs from and the height where it lands, in stage px */
  x: number; y: number; land: number;
  /** frame(s) it lets go; it swells at the lip for `swell` seconds first */
  at: number | number[];
  swell?: number;
  /** radius in px */
  size?: number;
  /** a little sideways speed in px per second (dripping off a tipped spout) */
  vx?: number;
  seed?: string;
  f?: number;
};

/** A drop of liquid: it swells at the lip, lets go, stretches as gravity speeds it up, blurs with its speed and
 *  lands with a flattening splat and a few beads thrown up. Lit like the liquid it is. */
export function Droplet({ x, y, land, at, swell: swellS = 0.33, size = 9, vx = 0, color = "#B8741E", alpha = 0.9, g, seed = "dr", f: fIn }: DropletProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w: cw, h: ch, fps } = useClip();
  const id = useIdent("dp");
  const sec = fps || 30, G = g ?? ch * 2.5;
  const swell = swellS * sec, splat = 0.4 * sec;
  const times = Array.isArray(at) ? at : [at];
  // it lets go with its centre 1.4 radii below the lip; it lands when its bottom (about 0.88 radii lower) meets `land`
  const start = y + size * 1.4, rFall = size * 0.88;
  const tFall = Math.sqrt((2 * Math.max(0, land - start - rFall)) / G);
  const live = times.filter((a) => f >= a - swell && f < a + tFall * sec + splat);
  if (!live.length || !(size > 0)) return null;
  return (
    <svg width={cw} height={ch} style={full}>
      <defs>
        <LiquidDefs id={id} color={color} alpha={alpha} />
        <filter id={id + "f"} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation={size * 0.06} /></filter>
      </defs>
      {live.map((a, j) => {
        if (f < a) {                                                       // swelling at the lip
          const k = clamp01((f - (a - swell)) / Math.max(1, swell));
          const r = size * (0.35 + 0.65 * k);
          return <Bead key={j} id={id} x={x} y={y + r * (0.6 + 0.8 * k)} r={r} k={0.4 + 0.9 * k} blur={0} />;
        }
        const t = (f - a) / sec;
        if (t < tFall) {
          const v = G * t;
          const stretch = 0.6 + Math.min(1.6, v / (G * 0.25));
          const r = size * (1 - 0.12 * Math.min(1, stretch - 0.6));
          const yy = Math.min(start + 0.5 * G * t * t, land - r);
          const blur = Math.min(size * 1.5, (v / sec) * 0.35);
          const tilt = (Math.atan2(vx, v + 1e-6) * 180) / Math.PI;
          return <Bead key={j} id={id} x={x + vx * t} y={yy} r={r} k={stretch} blur={blur} rot={-tilt} />;
        }
        const s = clamp01(((t - tFall) * sec) / splat);                  // landed: splat and beads
        const lx = x + vx * tFall, ry = size * 0.38 * (1 - 0.6 * s);
        return (
          <g key={j} opacity={1 - s} filter={`url(#${id}f)`}>
            <ellipse cx={lx} cy={land - ry} rx={size * (1 + 1.7 * Math.sqrt(s))} ry={ry} fill={`url(#${id}b)`} />
            {[0, 1, 2, 3].map((b) => {
              const dir = (random(`${seed}${j}d${b}`) - 0.5) * 2.4, up = (0.5 + random(`${seed}${j}u${b}`)) * size * 5;
              const bt = s * 0.9;
              return <circle key={b} cx={lx + dir * size * 3 * bt} cy={land - up * bt + up * bt * bt * 1.4} r={size * 0.22 * (1 - s * 0.5)} fill={`url(#${id}b)`} />;
            })}
          </g>
        );
      })}
    </svg>
  );
}

function Bead({ id, x, y, r, k, blur, rot = 0 }: { id: string; x: number; y: number; r: number; k: number; blur: number; rot?: number }) {
  const fid = `${id}m${Math.round(blur * 4)}`;
  return (
    <g transform={`translate(${x.toFixed(2)} ${y.toFixed(2)}) rotate(${rot.toFixed(2)})`}>
      {blur > 0.4 ? (
        <filter id={fid} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation={`${(r * 0.05).toFixed(2)} ${blur.toFixed(2)}`} /></filter>
      ) : null}
      <g filter={blur > 0.4 ? `url(#${fid})` : undefined}>
        <path d={tear(r, k)} fill={`url(#${id}b)`} />
        <ellipse cx={-r * 0.38} cy={-r * 0.42 - r * k * 0.15} rx={r * 0.26} ry={r * (0.34 + 0.12 * k)} fill={`url(#${id}w)`} opacity={0.85} />
        <ellipse cx={r * 0.3} cy={r * 0.45} rx={r * 0.42} ry={r * 0.18} fill={`url(#${id}w)`} opacity={0.3} />
      </g>
    </g>
  );
}

export type PourProps = LiquidLook & {
  /** the lip it leaves and the height where it lands, stage px */
  x: number; y: number; land: number;
  /** frame it starts, frame it stops (the tail then falls clear); leave `end` out to keep pouring */
  at: number;
  end?: number;
  /** width at the lip in px, speed leaving the lip (down) and sideways in px per second */
  width?: number;
  v0?: number;
  vx?: number;
  /** sideways wobble of the stream in px */
  wobble?: number;
  /** radius of the pool it spreads into where it lands (0: none, it falls into something); the pool stays after
   *  the stream, or soaks in over `soak` seconds */
  pool?: number;
  soak?: number;
  seed?: string;
  f?: number;
};

/** A thin stream of liquid: it leaves the lip, thins as it speeds up (falling in a curve when poured sideways),
 *  carries a highlight down its length, and stops by letting its tail fall clear. */
export function Pour({ x, y, land, at, end, width = 14, v0 = 200, vx = 0, wobble = 1.5, pool = 0, soak = 0, color = "#B8741E", alpha = 0.9, g, seed = "pr", f: fIn }: PourProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w: cw, h: ch, fps } = useClip();
  const id = useIdent("po");
  const sec = fps || 30, G = g ?? ch * 2.5;
  const H = Math.max(1, land - y);
  const fallT = (dy: number) => (Math.sqrt(v0 * v0 + 2 * G * dy) - v0) / G;   // seconds to fall dy below the lip
  const t = (f - at) / sec;
  const tEnd = end !== undefined ? (end - at) / sec : Infinity;
  if (t <= 0 || !(width > 0)) return null;
  const head = Math.min(H, v0 * t + 0.5 * G * t * t);
  const tt = t - tEnd;
  const tail = tt > 0 ? Math.min(H, v0 * tt + 0.5 * G * tt * tt) : 0;
  const landed = Math.max(0, t - fallT(H)), gone = tt > 0 ? Math.max(0, tt - fallT(H)) : 0;
  const done = tail >= H && gone > 0.4;
  // the pool stays where it landed; with `soak` it fades into the surface over that many seconds
  const fade = done && soak > 0 ? clamp01((gone - 0.4) / soak) : 0;
  if (done && (!(pool > 0) || fade >= 1)) return null;
  const N = 28, ph = t * 9;
  const pts = Array.from({ length: N + 1 }, (_, i) => {
    const dy = tail + ((head - tail) * i) / N;
    const tf = fallT(dy);
    const wd = width * Math.pow(v0 / Math.sqrt(v0 * v0 + 2 * G * dy), 0.3) * (i === N && head < H ? 1.3 : 1);
    const wob = Math.sin(ph - dy * 0.02 + random(seed) * 6) * wobble * (dy / H);
    return { x: x + vx * tf + wob, y: y + dy, wd: Math.max(0.6, wd) };
  });
  // the body is shaded across its width in lanes (dark rim, lit side, body, dark rim) that follow its curve
  const lite = mixColor(color, "#FFFFFF", 0.4), deep = mixColor(color, "#000000", 0.45);
  const shadeAt = (u: number) => (u < 0.3 ? mixColor(deep, lite, u / 0.3) : u < 0.55 ? mixColor(lite, color, (u - 0.3) / 0.25) : mixColor(color, deep, (u - 0.55) / 0.45));
  const LANES = 8;
  const edge = (u: number, rev = false) => (rev ? pts.slice().reverse() : pts).map((p) => `${(p.x + p.wd * (u - 0.5)).toFixed(2)} ${p.y.toFixed(2)}`);
  const hi = pts.map((p) => `${(p.x - p.wd * 0.2).toFixed(2)} ${p.y.toFixed(2)}`);
  const last = pts[N];
  const poolX = x + vx * fallT(H);
  const spread = pool > 0 ? pool * clamp01(Math.sqrt(landed / 1.5)) : 0;
  return (
    <svg width={cw} height={ch} style={full}>
      <defs>
        <LiquidDefs id={id} color={color} alpha={alpha} />
        <filter id={id + "f"} x="-50%" y="-10%" width="200%" height="120%"><feGaussianBlur stdDeviation={Math.max(0.5, width * 0.06)} /></filter>
        <filter id={id + "h"} x="-50%" y="-10%" width="200%" height="120%"><feGaussianBlur stdDeviation={Math.max(0.5, width * 0.1)} /></filter>
      </defs>
      {spread > 0 ? (
        <ellipse cx={poolX} cy={land} rx={spread} ry={spread * 0.22} fill={`url(#${id}p)`} opacity={1 - fade} />
      ) : null}
      {done ? null : (
        <>
          <g filter={`url(#${id}f)`}>
            {Array.from({ length: LANES }, (_, k) => (
              <path key={k} d={`M${edge(k / LANES).join(" L")} L${edge((k + 1) / LANES, true).join(" L")} Z`}
                fill={shadeAt((k + 0.5) / LANES)} fillOpacity={alpha} />
            ))}
            {head >= H && tail < H ? (
              <ellipse cx={last.x} cy={land} rx={last.wd * (1.4 + 0.15 * Math.sin(t * 20))} ry={last.wd * 0.45} fill={`url(#${id}p)`} />
            ) : head < H ? <circle cx={last.x} cy={last.y} r={last.wd * 0.62} fill={`url(#${id}b)`} /> : null}
          </g>
          <path d={`M${hi.join(" L")}`} stroke="#FFFFFF" strokeOpacity={0.45} strokeWidth={Math.max(0.8, width * 0.14)} fill="none" filter={`url(#${id}h)`} />
        </>
      )}
    </svg>
  );
}
