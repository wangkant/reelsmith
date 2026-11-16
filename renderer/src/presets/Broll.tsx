// Shots that look filmed: each shot is one plate with a clip baked from it, held in a hand that never keeps still,
// panned the way a phone turns. Hard cuts at each shot's `at`; the frame never leaves the plate.
import { useCurrentFrame } from "remotion";
import { coverFit, handheld, isAsset, isFilm, Layer, Lens, Motes, Plate, Stage, Travel, useClip, Vapor } from "@reelsmith/kit";
import type { AssetRef, Fit } from "@reelsmith/kit";

type Pair = [number, number];
type Steam = { p: Pair; w?: number; amount?: number; size?: number; rise?: number; color?: string; blend?: "screen" | "normal" | "multiply" };
type Air = { n?: number; size?: number; wind?: Pair; color?: string; opacity?: number };
type Mover = { asset: AssetRef; line: Pair[]; w: number; sizes?: Pair };
export type BrollShot = { plate_asset: AssetRef; film_asset?: AssetRef; loop?: boolean; at: number; pan?: Pair; tilt?: Pair; zoom?: Pair;
  steam?: Steam[]; air?: Air; movers?: Mover[] };

/** 0..1 along a pan at shot fraction t: eased in and out, its speed a little uneven (a hand turning a phone),
 *  monotone, exactly 0 and 1 at the ends. */
export const handPan = (t: number, seed = 0): number => {
  if (!(t > 0)) return 0;
  if (t >= 1) return 1;
  const speed = (u: number) => (1 - 0.55 * Math.cos(2 * Math.PI * u))
    * (1 + 0.28 * Math.sin(2 * Math.PI * (1.3 * u + seed * 0.37)) + 0.14 * Math.sin(2 * Math.PI * (2.9 * u + seed * 0.61)));
  const N = 64;
  let total = 0, part = 0;
  for (let i = 0; i < N; i++) {
    const v = speed((i + 0.5) / N);
    total += v;
    part += v * Math.max(0, Math.min(1, (t - i / N) * N));
  }
  return part / total;
};

/** The camera nearest (cx, cy, z) whose frame, shaken by up to (ax, ay) px, stays on the fitted plate: the zoom is
 *  raised only when the plate leaves no room for the shake, then the centre is clamped. */
export const keepInside = (cx: number, cy: number, z: number, fit: Pick<Fit, "x" | "y" | "w" | "h">, w: number, h: number,
  ax: number, ay: number): { x: number; y: number; z: number } => {
  const zz = Math.max(z, w / Math.max(1, fit.w - 2 * ax), h / Math.max(1, fit.h - 2 * ay));
  const hx = w / (2 * zz) + ax, hy = h / (2 * zz) + ay;
  const clamp = (v: number, lo: number, hi: number) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));
  return { x: clamp(cx, fit.x + hx, fit.x + fit.w - hx), y: clamp(cy, fit.y + hy, fit.y + fit.h - hy), z: zz };
};

const NEAR = 1.3;

export default function Broll({ props }: { props: { shots?: BrollShot[]; hand?: number } }) {
  const f = useCurrentFrame();
  const { w, h, fps, dur } = useClip();
  // a shot that starts after the clip's end never shows and must not stretch the one before it
  const shots = [...(props?.shots || [])].filter((s) => !(s.at >= dur)).sort((a, b) => a.at - b.at);
  let k = 0;
  for (let i = 0; i < shots.length; i++) if (f >= shots[i].at) k = i;
  const shot = shots[k];
  if (!shot) return null;
  const plate = shot.plate_asset;
  if (!isAsset(plate)) throw new Error(`Broll: shot ${k + 1}'s plate_asset is not an asset; name an image asset of the project`);
  const size = plate.size;
  if (!(size && size[0] > 0 && size[1] > 0)) {
    throw new Error(`Broll: shot ${k + 1}'s plate (${plate.src}) has no pixel size; give plate_asset an image asset whose file the project can read (reelsmith check says why it cannot)`);
  }
  const from = shot.at, to = Math.min(dur, k + 1 < shots.length ? shots[k + 1].at : dur);
  const t = Math.max(0, Math.min(1, (f - from) / Math.max(1, to - from)));
  const fit = coverFit(size[0], size[1], w, h, 0);
  const u = handPan(t, k + 1);
  const along = (r: Pair | undefined, mid: number) => (r ? r[0] + (r[1] - r[0]) * u : mid);
  const [z0, z1] = shot.zoom ?? [1.04, 1.04];
  const want = fit.at([along(shot.pan, size[0] / 2), along(shot.tilt, size[1] / 2)]);
  const amp = Math.max(0, props?.hand ?? 8);
  // one px more than the shake, so no sub-pixel edge shows
  const c = keepInside(want[0], want[1], Math.max(1e-3, z0) * Math.pow(Math.max(1e-3, z1) / Math.max(1e-3, z0), u), fit, w, h,
    amp + 1, amp * 0.8 + 1);
  const [dx, dy] = handheld(f, amp, `broll${k}`, fps || 30);
  const air = shot.air;
  // specks over the whole plate, so they pan with it; density per screen as asked
  const count = (n: number, bw: number, bh: number) => Math.min(1500, Math.round((n * bw * bh) / (w * h)));
  const nearBox: [number, number, number, number] = [w / 2 + (fit.x - w / 2) * NEAR, h / 2 + (fit.y - h / 2) * NEAR, fit.w * NEAR, fit.h * NEAR];
  const wind = air?.wind ?? [18, 120];
  return (
    <Lens focus={1} aperture={0} vignette={0.08} grain={0} handheld={0} grade={{ gain: 1 + 0.012 * Math.sin(f * 0.05 + k) }}>
      <Stage key={k} cam={[{ at: 0, x: c.x + dx, y: c.y + dy, z: c.z }]} grain={0} light={0} vignette={0} f={f}>
        <Plate src={plate} pad={0} drift={0} depth={1} film={isAsset(shot.film_asset) ? { src: shot.film_asset, at: from, loop: !!shot.loop } : isFilm(plate) ? { src: plate, at: from, loop: !!shot.loop } : undefined} f={f}>
          {(shot.steam || []).map((s, i) => {
            const [sx, sy] = fit.at(s.p);
            return <Vapor key={i} x={sx} y={sy} w={(s.w ?? 24) * fit.s} amount={s.amount ?? 0.5} size={(s.size ?? 45) * fit.s} rise={(s.rise ?? 240) * fit.s}
              n={26} life={3.0} wind={30} color={s.color ?? "#F4F1EC"} blend={s.blend ?? "screen"} seed={`${k}-${i}`} f={f + 90} />;
          })}
          {(shot.movers || []).filter((m) => isAsset(m.asset)).map((m, i) => (
            <Travel key={`m${i}`} src={m.asset} line={m.line.map((pt) => fit.at(pt))} at={from} dur={Math.max(1, to - from)} w={m.w * fit.s}
              sizes={m.sizes ?? [1, 1]} smearK={0.3} maxSmear={18} f={f} />
          ))}
          {air ? <Motes box={[fit.x, fit.y, fit.w, fit.h]} n={count(air.n ?? 70, fit.w, fit.h)} size={air.size ?? 4} wind={wind}
            color={air.color ?? "#FFFFFF"} opacity={air.opacity ?? 0.8} seed={`air${k}`} f={f} /> : null}
        </Plate>
        {air ? (
          <Layer depth={NEAR} blur={2.5}>
            <Motes box={nearBox} n={count((air.n ?? 70) * 0.08, nearBox[2], nearBox[3])} size={(air.size ?? 4) * 2.6}
              wind={[wind[0] * 1.8, wind[1] * 1.8]} color={air.color ?? "#FFFFFF"} opacity={(air.opacity ?? 0.8) * 0.6}
              seed={`near${k}`} f={f} />
          </Layer>
        ) : null}
      </Stage>
    </Lens>
  );
}
