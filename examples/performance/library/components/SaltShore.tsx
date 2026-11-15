// Lines 1-2 as one world: salt drops off a rock into a river, rides it to the sea; the sun lifts the water into a
// cloud and the shore dries to a crust of salt. One Outdoors set, four camera stops, everything cued by word.
import React from "react";
import { useCurrentFrame } from "remotion";
import {
  along, breathe, Canvas, drop, follow, inOut, Label, Outdoors, pendulum, prog, Sign, Solid, spr, stations, useClip, useCues, Wisps,
} from "@reelsmith/kit";
import { Beach, Cloud, Crystal, River, riverPath, Rock, Sea, Sun } from "./salt/shore";

export default function SaltShore() {
  const f = useCurrentFrame();
  const { w, h, dur } = useClip();
  const { T } = useCues();
  const floor = h * 0.64;
  const river = riverPath(floor);
  const lift = inOut(prog(f, T("lifts") - 4, 70));
  const shore = floor + 250 - 110 * lift;
  const cam = stations([
    { at: 0, x: 520, y: floor + 40, z: 1.15 },
    { at: T("sea") + 4, x: 1720, y: floor - 20, z: 1.0 },
    { at: T("sun") - 2, x: 2060, y: floor - 330, z: 0.92 },
    { at: T("salt", 0, 1) - 2, x: 2080, y: floor + 20, z: 1.3 },
  ], { travel: 30, dip: 0.12, push: 0.05, until: dur });
  const ride = (fr: number) => inOut(prog(fr, T("into") - 2, 46));
  const signDrop = drop(f, T("every") - 6, floor - 900, floor - 156);
  const pile = drop(f, T("salt", 0, 1) - 8, floor - 420, floor + 250, { squash: 0.3 });
  const rise = spr(f, T("sun") - 6, { damping: 16 });
  return (
    <Outdoors span={[-w * 0.3, w * 2.9]} floor={floor} sun={null} cam={cam} trees={6} seed="shore">
      <Canvas>
        <Beach x0={1450} top={floor - 40} bottom={h * 1.7} />
        <Solid d={`M1900 ${floor + 250} Q2150 ${floor + 150} 2500 ${floor + 175} Q2620 ${floor + 250} 2400 ${floor + 300} Q2100 ${floor + 320} 1900 ${floor + 250} Z`}
          box={[1900, floor + 150, 720, 170]} tone="#F2EEE4" speckle={60} under={0.2} rim={3} shadow={0} outline={0} seed="crust" />
        <River pts={river} f={f} />
        <Sea x0={1350} top={floor - 200} shore={shore} f={f} glint={prog(f, T("sea") - 4, 40) * 1.2 - 0.1} />
        <Rock x={330} y={floor + 230} rx={130} ry={72} seed="r1" />
        <Rock x={560} y={floor + 205} rx={80} ry={46} seed="r2" />
        <Rock x={1260} y={floor + 330} rx={95} ry={50} seed="r3" />
        <Solid box={[1500, floor - 170, 26, 470]} tone="#7A5030" shadow={0.8} rim={3}><rect x={1500} y={floor - 170} width={26} height={470} /></Solid>
        <Solid box={[1500, floor - 170, 230, 18]} tone="#7A5030" shadow={0} rim={3}><rect x={1500} y={floor - 170} width={230} height={18} /></Solid>
        {[0, 1, 2, 3, 4].map((i) => {
          const sx = 260 + i * 34, top = floor + 230 - 144 - 26 - (i % 2) * 22;
          const fall = drop(f, T("salt") - 3 + i * 3, top, floor + 330 + (i % 3) * 8, { squash: 0.1 });
          const p = follow(f, ride, 3 + i * 3);
          const [rx, ry] = along(river, 0.36 + 0.62 * p);
          const x = fall.landed ? sx + (rx - 300) * p : sx, y = fall.landed ? fall.y + (ry - (floor + 330)) * p : fall.y;
          const sink = prog(f, T("every") + i * 3, 10);
          if (sink >= 1) return null;
          return <g key={i} opacity={1 - sink}><Crystal x={x} y={y} s={40 * (1 - 0.4 * sink)} seed={"c" + i} /></g>;
        })}
        <Sun x={2330} y={floor - 640 - 120 * rise} k={rise} />
        <Cloud x={2280 - 40 * lift} y={floor - 330 - 60 * lift} s={0.8} k={spr(f, T("sky") - 6) * breathe(f, 0.02)} />
        {pile.t > 0 ? (
          <g transform={`translate(2120 ${pile.y}) scale(${pile.sx} ${pile.sy}) translate(-2120 ${-(floor + 250)})`}>
            <Solid d={`M1980 ${floor + 250} Q2060 ${floor + 120} 2120 ${floor + 110} Q2190 ${floor + 120} 2260 ${floor + 250} Z`}
              box={[1980, floor + 110, 280, 140]} tone="#F7F4EC" speckle={50} gloss={0.35} lift={pile.landed ? 0 : 0.6} seed="pile" />
          </g>
        ) : null}
      </Canvas>
      {[0, 1, 2].map((i) => <Wisps key={i} x={1980 + i * 150} y={floor + 60} k={prog(f, T("lifts") + i * 6, 50)} n={2} spread={70} color="#FFFFFF" />)}
      {signDrop.t > 0 && f < T("sun") - 6 ? <Sign x={1690} y={signDrop.y} hang={40} text="EVERY DAY" size={64} ang={pendulum(f, T("every") + 4, 16)} seed="daily" /> : null}
      <Label x={2120} y={floor - 60} text="the salt stays" r={-4} seed="stays" at={T("stays") - 2} />
    </Outdoors>
  );
}
