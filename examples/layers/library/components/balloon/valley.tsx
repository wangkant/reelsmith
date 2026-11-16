// The valley plate: the balloon waits behind the treetops (line 1), then lifts out of them into the sky (line 3).
import React from "react";
import {
  camAt, coverFit, Haze, lookAt, Motes, onScreen, out3, Photo, Plate, prog, Rays, Refract, shadeRamp, Stage, Travel, travelAt,
  useClip, Layer,
} from "@reelsmith/kit";
import type { AssetRef, Key, Pt } from "@reelsmith/kit";
import { BALLOON, CROWN, ENVELOPE, ENVELOPE_R, GRASS_Y, MIST, MOUTH, PAD, PLATE, SUN, TREES } from "./trace";

const DEPTH = 0.9;

/** A point of the balloon picture in stage px, for a balloon of width bw standing (basket bottom) on (x, y). */
const onBalloon = (x: number, y: number, bw: number, pt: Pt): Pt => {
  const k = bw / BALLOON[0];
  return [x + (pt[0] - BALLOON[0] / 2) * k, y - (BALLOON[1] - pt[1]) * k];
};

export type Shot = { keys: Key[]; at: (f: number) => { x: number; y: number }; bw: number };

/** Line 1: where the balloon stands and the camera's path, shared with the push into it. */
export function openingShot(w: number, h: number, lighter: number, end: number): Shot {
  const fit = coverFit(PLATE[0], PLATE[1], w, h, PAD);
  const [bx, by] = fit.at([560, 914]);
  const bw = 300;
  const at = (f: number) => ({ x: bx, y: by - 26 * out3(prog(f, lighter - 4, 40)) + Math.sin(f / 22) * 4 });
  const env = (f: number) => { const p = at(f); return onBalloon(p.x, p.y, bw, ENVELOPE); };
  const keys: Key[] = [
    { at: 0, x: 520, y: 1020, z: 1.04 },
    { at: lighter, ...lookAt(env(lighter), DEPTH, w, h), z: 1.2 },
    { at: end, ...lookAt(env(end), DEPTH, w, h), z: 1.55 },
  ];
  return { keys, at, bw };
}

/** The envelope's oval on screen at frame f of the opening (the push goes into it). */
export function envelopeOnScreen(shot: Shot, f: number, w: number, h: number): [number, number, number, number] {
  const p = shot.at(f);
  const c = onBalloon(p.x, p.y, shot.bw, ENVELOPE);
  const o = onScreen(camAt(shot.keys, f), DEPTH, w, h, c);
  const k = (shot.bw / BALLOON[0]) * o.s;
  const rx = ENVELOPE_R[0] * k * 0.8, ry = ENVELOPE_R[1] * k * 0.8;
  return [o.x - rx, o.y - ry, 2 * rx, 2 * ry];
}

type Assets = { valley: AssetRef; balloon: AssetRef };

function Air({ f, w, h }: { f: number; w: number; h: number }) {
  const fit = coverFit(PLATE[0], PLATE[1], w, h, PAD);
  const sun = fit.at(SUN);
  return (
    <>
      <Layer depth={DEPTH}><Rays x={sun[0]} y={sun[1]} ang={128} spread={40} n={7} strength={0.2} f={f} /></Layer>
      <Layer depth={1.35} blur={1.2}>
        <Motes box={[-200, 300, w + 400, h - 200]} n={34} size={5} wind={[14, -5]} light={sun} opacity={0.55} f={f} />
      </Layer>
    </>
  );
}

/** Line 1: the valley at sunrise; the balloon waits behind the treetops, warm air shimmering off its crown. */
export function Opening({ f, a, shot, lighter }: { f: number; a: Assets; shot: Shot; lighter: number }) {
  const { w, h } = useClip();
  const fit = coverFit(PLATE[0], PLATE[1], w, h, PAD);
  const p = shot.at(f);
  const crown = onScreen(camAt(shot.keys, f), DEPTH, w, h, onBalloon(p.x, p.y, shot.bw, CROWN));
  const heat = 0.6 + 0.4 * prog(f, lighter - 6, 20);
  const s = crown.s * (shot.bw / 300);
  return (
    <Stage cam={shot.keys} grain={0} light={0} vignette={0} f={f}>
      <Refract kind="heat" area={[crown.x, crown.y - 110 * s, 80 * s, 120 * s]} strength={7 * heat} grain={26} speed={70} f={f}>
        <Plate src={a.valley} depth={DEPTH} pad={PAD} drift={3} fronts={[TREES]} feather={4}
          sway={{ y: GRASS_Y, amp: 1.1, feather: 70 }} f={f}>
          <Haze y0={fit.at([0, MIST[0]])[1]} y1={fit.at([0, MIST[1]])[1]} amount={0.32} drift={10} f={f} />
          <Photo src={a.balloon} x={p.x} y={p.y} w={shot.bw} tint="#FFE3BC" tintA={0.25} haze={0.12} hazeColor="#E8EEF2" />
        </Plate>
      </Refract>
      <Air f={f} w={w} h={h} />
    </Stage>
  );
}

/** Line 3: the same valley; the balloon lifts out of the trees into the sun, its basket coming clear. */
export function Rise({ f, a, start, end, mist }: { f: number; a: Assets; start: number; end: number; mist: number }) {
  const { w, h } = useClip();
  const fit = coverFit(PLATE[0], PLATE[1], w, h, PAD);
  const line: Pt[] = [fit.at([566, 1030]), fit.at([572, 820]), fit.at([600, 470])];
  const bw = 330, dur = end - start - 6;
  const st = travelAt(line, f, start, dur, { sizes: [1, 0.78], ease: "inOut" });
  const top = line[line.length - 1], low = line[0];
  const keys: Key[] = [
    { at: start - 12, ...lookAt([low[0], low[1] - 230], DEPTH, w, h), z: 1.32 },
    { at: end, ...lookAt([top[0], top[1] + 250], DEPTH, w, h), z: 1.1 },
  ];
  const k = (bw * st.s) / BALLOON[0];
  const mouth = onBalloon(st.x, st.y, bw * st.s, MOUTH);
  const crown = onScreen(camAt(keys, f), DEPTH, w, h, onBalloon(st.x, st.y, bw * st.s, CROWN));
  const burn = 0.55 + 0.45 * Math.sin(f / 2.3) * Math.sin(f / 5.1);
  const stir = 0.3 + 0.12 * prog(f, mist - 6, 30);
  return (
    <Stage cam={keys} grain={0} light={0} vignette={0} f={f}>
      <Refract kind="heat" area={[crown.x, crown.y - 120 * crown.s * k, 70 * crown.s * k * 2, 120 * crown.s * k * 2]} strength={6} grain={26} speed={70} f={f}>
        <Plate src={a.valley} depth={DEPTH} pad={PAD} drift={3} fronts={[TREES]} feather={4}
          sway={{ y: GRASS_Y, amp: 1.1, feather: 70, gust: start, gustAmp: 2.5 }} f={f}>
          <Haze y0={fit.at([0, MIST[0]])[1]} y1={fit.at([0, MIST[1]])[1]} amount={stir} drift={14} f={f} />
          <Travel src={a.balloon} line={line} at={start} dur={dur} sizes={[1, 0.78]} w={bw} f={f} smearK={0.35}
            shadeAt={shadeRamp(top, low, 0.3)} tint="#FFE3BC" tintA={0.25} haze={0.1} hazeColor="#E8EEF2" />
          <div style={{ position: "absolute", left: mouth[0] - 60 * k * 2, top: mouth[1] - 30 * k * 2, width: 120 * k * 2, height: 60 * k * 2,
            borderRadius: "50%", background: "radial-gradient(closest-side, rgba(255,214,140,0.95), rgba(255,150,60,0.4) 55%, rgba(255,120,40,0))",
            opacity: burn, mixBlendMode: "screen" }} />
        </Plate>
      </Refract>
      <Air f={f} w={w} h={h} />
    </Stage>
  );
}
