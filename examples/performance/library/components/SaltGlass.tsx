// Line 3, cut-out: a torn photo of a glass of seawater slaps down; the water line is marked, a label names the
// litre, a loupe finds the salt and a tag swings in with the number.
import React from "react";
import { useCurrentFrame } from "remotion";
import { Actor, CircleIt, Cut, Label, Loupe, Marker, prog, swing, Tag, Tape, toCanvas, useClip, useCues } from "@reelsmith/kit";
import type { Placed, Pt } from "@reelsmith/kit";

// outline in glass.jpg source pixels (232 x 338; read off an AssetGrid preview): the glass and the salt beside it
const GLASS: Pt[] = [[38, 66], [192, 66], [188, 236], [214, 232], [232, 242], [232, 316], [160, 320], [48, 302], [40, 250]];
const SALT: Pt = [205, 276];
const WATER: Pt[] = [[50, 124], [90, 119], [130, 126], [182, 121]];

export default function SaltGlass({ props }: { props: any }) {
  const f = useCurrentFrame();
  const { w } = useClip();
  const { T } = useCues();
  const piece: Placed = { poly: GLASS, x: w * 0.42, y: 840, s: 2.55, r: -3 };
  const salt = toCanvas(piece, SALT);
  const wave = WATER.map((pt) => toCanvas(piece, pt));
  return (
    <>
      <Actor at={0} from="slap" ox={piece.x} oy={piece.y}>
        <Cut src={props.photo_asset} seed="glass" {...piece} lift={0.15} photo="saturate(1.1) contrast(1.05)" />
        <Tape x={piece.x - 40} y={470} w={220} r={-8} seed="tape" />
      </Actor>
      <Marker d={"M" + wave.map((p) => p.join(" ")).join(" L")} p={prog(f, T("seawater") - 3, 12)} w={12} seed="water" />
      <Label x={300} y={420} text="1 litre" r={-5} seed="litre" at={T("litre") - 2} />
      <CircleIt x={salt[0]} y={salt[1]} w={210} h={150} p={prog(f, T("salt") - 6, 12)} />
      <Loupe src={props.photo_asset} at={SALT} x={880} y={1160} r={120} zoom={3.4} piece={piece} p={prog(f, T("grams") - 4, 10)} seed="lp" />
      {f >= T("thirty") - 4 ? <Tag x={790} y={300} ang={swing(f, T("thirty") - 4, 26)} text="35" unit="grams" /> : null}
    </>
  );
}
