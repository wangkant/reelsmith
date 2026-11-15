// Line 1, drawn objects: a river is inked down the page, salt grains drop into it and ride it into the sea.
import React from "react";
import { useCurrentFrame } from "remotion";
import { along, Label, Marker, prog, smooth, spr, Stage, Stamp, step, useClip, useCues } from "@reelsmith/kit";
import { Crystal, RIVER, Sea } from "./salt/parts";

export default function SaltRiver() {
  const f = useCurrentFrame();
  const { dur } = useClip();
  const { T } = useCues();
  const sf = step(f);
  const ride = prog(f, T("into") - 2, 28);
  const leave = prog(f, dur - 8, 8);
  return (
    <Stage grain={0} light={0} vignette={0}>
      <Sea k={spr(sf, T("sea") - 5)} />
      <Marker d={smooth(RIVER)} p={prog(f, T("Rivers") - 4, 18)} color="#5B95C2" w={58} seed="river" jitter={0.6} />
      <Marker d={smooth(RIVER)} p={prog(f, T("Rivers"), 18)} color="#A9CDE6" w={14} seed="glint" jitter={0.6} />
      {[0, 1, 2, 3, 4].map((i) => {
        const [x, y] = along(RIVER, Math.min(1, 0.08 + 0.13 * i + 0.9 * ride));
        const sink = prog(f, T("into") + 12 + i * 3, 8);
        return <Crystal key={i} x={x} y={y} k={spr(sf, T("salt") - 3 + i * 3) * (1 - sink)} seed={"g" + i} />;
      })}
      <Label x={740} y={720} text="a little salt" r={4} seed="little" at={T("little") - 2} peel={leave} />
      <Stamp x={700} y={900} text="EVERY DAY" r={-7} size={84} color="#7E1A12" at={T("every") - 2} seed="daily" />
    </Stage>
  );
}
