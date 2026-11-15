// Line 3 on a Desk set: a torn photo of a glass of seawater is taped down, the litre is marked, a heap of salt drops
// into a dish beside it and a tag with the number swings in; the camera pushes in on the glass, then on the dish.
import React from "react";
import { useCurrentFrame } from "remotion";
import {
  Actor, Canvas, CircleIt, Cut, Desk, drop, Label, Loupe, Marker, pendulum, prog, Shadow, Solid, stations, Tag, Tape, toCanvas, useClip, useCues,
} from "@reelsmith/kit";
import type { Placed, Pt } from "@reelsmith/kit";

// outline in glass.jpg source pixels (232 x 338; read off an AssetGrid preview): the glass and the salt beside it
const GLASS: Pt[] = [[38, 66], [192, 66], [188, 236], [214, 232], [232, 242], [232, 316], [160, 320], [48, 302], [40, 250]];
const SALT: Pt = [205, 276];
const WATER: Pt[] = [[50, 124], [90, 119], [130, 126], [182, 121]];

export default function SaltDesk({ props }: { props: any }) {
  const f = useCurrentFrame();
  const { w, h, dur } = useClip();
  const { T } = useCues();
  const piece: Placed = { poly: GLASS, x: w * 0.36, y: h * 0.42, s: 2.4, r: -4 };
  const salt = toCanvas(piece, SALT);
  const wave = WATER.map((pt) => toCanvas(piece, pt));
  const dish = { x: w * 0.68, y: h * 0.66 };
  const heap = drop(f, T("thirty") - 10, dish.y - 700, dish.y - 10, { squash: 0.32 });
  const cam = stations([
    { at: 0, x: w * 0.5, y: h * 0.5, z: 0.94 },
    { at: T("seawater") - 2, x: w * 0.42, y: h * 0.44, z: 1.12 },
    { at: T("thirty") - 2, x: w * 0.6, y: h * 0.56, z: 1.18 },
  ], { travel: 24, dip: 0.08, push: 0.05, until: dur });
  return (
    <Desk cam={cam} seed="study">
      <Actor at={0} from="slap" ox={piece.x} oy={piece.y}>
        <Cut src={props.photo_asset} seed="glass" {...piece} lift={0.15} photo="saturate(1.1) contrast(1.05)" />
        <Tape x={piece.x - 40} y={piece.y - 330} w={220} r={-8} seed="tape" />
      </Actor>
      <Marker d={"M" + wave.map((p) => p.join(" ")).join(" L")} p={prog(f, T("seawater") - 3, 12)} w={12} seed="water" />
      <Label x={w * 0.62} y={h * 0.3} text="1 litre" r={-5} seed="litre" at={T("litre") - 2} />
      <Canvas>
        <Shadow x={dish.x} y={dish.y + 40} w={250} />
        <Solid d={`M${dish.x - 230} ${dish.y - 20} Q${dish.x} ${dish.y + 120} ${dish.x + 230} ${dish.y - 20} Z`} box={[dish.x - 230, dish.y - 20, 460, 90]}
          tone="#E9EEF0" side={14} gloss={0.5} shadow={0} seed="dish" />
        {heap.t > 0 ? (
          <g transform={`translate(${dish.x} ${heap.y}) scale(${heap.sx} ${heap.sy}) translate(${-dish.x} ${-(dish.y - 10)})`}>
            <Solid d={`M${dish.x - 170} ${dish.y - 10} Q${dish.x - 80} ${dish.y - 170} ${dish.x} ${dish.y - 175} Q${dish.x + 90} ${dish.y - 165} ${dish.x + 170} ${dish.y - 10} Z`}
              box={[dish.x - 170, dish.y - 175, 340, 165]} tone="#F8F6F0" speckle={70} gloss={0.3} shadow={heap.landed ? 0.6 : 0} seed="heap" />
          </g>
        ) : null}
        <ellipse cx={dish.x} cy={dish.y - 20} rx={230} ry={18} fill="none" stroke="#FFFFFF" strokeWidth={6} opacity={0.7} />
      </Canvas>
      <CircleIt x={salt[0]} y={salt[1]} w={210} h={150} p={prog(f, T("salt") - 6, 12)} />
      <Loupe src={props.photo_asset} at={SALT} x={w * 0.32} y={h * 0.7} r={120} zoom={3.4} piece={piece} p={prog(f, T("grams") - 4, 10)} seed="lp" />
      {f >= T("thirty") - 4 ? <Tag x={dish.x + 150} y={h * 0.38} ang={pendulum(f, T("thirty") - 4, 26)} text="35" unit="grams" /> : null}
    </Desk>
  );
}
