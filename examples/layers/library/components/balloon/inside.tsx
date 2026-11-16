// Line 2: looking up from the basket into the envelope. The burner lights, the flame roars up, the air above it
// bends with heat, and on "heats" the envelope swells.
import React from "react";
import { camAt, coverFit, onScreen, out3, Photo, Plate, prog, Refract, Stage, useClip, Warp } from "@reelsmith/kit";
import type { AssetRef, Key } from "@reelsmith/kit";
import { BURNER, PAD, PLATE, VENT } from "./trace";

const DEPTH = 0.9;

/** Flame height 0..1: it flares on lighting, then roars with a ragged flicker. */
export const flameAt = (f: number, lit: number): number => {
  if (f < lit) return 0;
  const grow = out3(prog(f, lit, 7));
  const flick = 0.06 * Math.sin(f * 1.9) + 0.05 * Math.sin(f * 3.7 + 1) + 0.04 * Math.sin(f * 0.83);
  return grow * (1 + flick + 0.18 * Math.exp(-(f - lit) / 6));
};

export function Inside({ f, a, start, end, lit, heats }: { f: number; a: { inside: AssetRef; flame: AssetRef }; start: number; end: number; lit: number; heats: number }) {
  const { w, h } = useClip();
  const fit = coverFit(PLATE[0], PLATE[1], w, h, PAD);
  const [nx, ny] = fit.at(BURNER), [vx, vy] = fit.at(VENT);
  const fl = flameAt(f, lit);
  const swell = out3(prog(f, heats - 3, 26)) - 0.25 * Math.max(0, Math.sin(Math.PI * prog(f, heats + 20, 20)));
  const keys: Key[] = [
    { at: start, x: w / 2, y: h / 2 + 40, z: 1.0 },
    { at: lit, x: w / 2, y: h / 2, z: 1.04 },
    { at: end, x: w / 2, y: h / 2 - 140, z: 1.2 },
  ];
  const glow = Math.min(1, fl) * 0.85;
  // Refract and Warp work in frame px: where the burner and the vent are on screen now
  const cam = camAt(keys, f);
  const nb = onScreen(cam, DEPTH, w, h, [nx, ny]), vt = onScreen(cam, DEPTH, w, h, [vx, vy]);
  const z = nb.s;
  return (
    <Stage cam={keys} grain={0} light={0} vignette={0} f={f}>
      <Refract kind="heat" area={[nb.x, nb.y - 520 * z, 260 * z, 520 * z]} strength={22 * Math.min(1, fl)} grain={34} speed={260} f={f}>
        <Warp area={[vt.x, vt.y + 260 * z, 560 * z, 520 * z]} feather={0.6} origin={[vt.x, vt.y + 120 * z]} sx={1 + 0.05 * swell} sy={1 + 0.07 * swell}>
          <Plate src={a.inside} depth={DEPTH} pad={PAD} drift={2} f={f}>
            {fl > 0 ? <Photo src={a.flame} x={nx} y={ny + 12} w={210 * (0.9 + 0.1 * fl)} sy={fl} anchor={[0.5, 0.98]} /> : null}
            {/* the fabric lit from below by the flame, added as light where it falls */}
            <div style={{ position: "absolute", left: nx - 640, top: ny - 1250, width: 1280, height: 1300, opacity: glow, mixBlendMode: "screen",
              background: "radial-gradient(closest-side, rgba(255,190,110,0.55), rgba(255,140,60,0.22) 50%, rgba(255,120,40,0))" }} />
          </Plate>
        </Warp>
      </Refract>
    </Stage>
  );
}
