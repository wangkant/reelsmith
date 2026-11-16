// One world for the whole film in layered photographs: a valley plate with the balloon behind its treetops, a push
// into the balloon, the burner lighting inside it, a whip pan back out as the balloon lifts clear of the trees.
import React from "react";
import { useCurrentFrame } from "remotion";
import { Join, Lens, prog, useClip, useCues } from "@reelsmith/kit";
import { envelopeOnScreen, Opening, openingShot, Rise } from "./balloon/valley";
import { flameAt, Inside } from "./balloon/inside";

export default function Balloon({ props }: { props: any }) {
  const f = useCurrentFrame();
  const { w, h, dur } = useClip();
  const { T, at } = useCues();
  const lighter = T("lighter"), lit = T("burner") - 4, heats = T("heats"), mist = T("mist");
  const push = at(2) - 20, whip = T("So") - 10;
  const shot = openingShot(w, h, lighter, push + 18);
  const a = { valley: props.valley_asset, balloon: props.balloon_asset, inside: props.inside_asset, flame: props.flame_asset };
  const inside = <Inside f={f} a={a} start={push} end={whip + 12} lit={lit} heats={heats} />;
  // warmer while the burner roars
  const warm = f >= push && f < whip + 12 ? Math.min(1, flameAt(f, lit)) * (0.6 + 0.4 * prog(f, heats, 20)) : 0;
  return (
    <Lens handheld={4} vignette={0.32} grain={0.04} kick={[{ at: lit + 1, amp: 9, dur: 12, fringe: 5 }]}
      grade={{ lift: 0.02, gamma: 1.03, tint: "#FFDDB0", tintA: 0.06 + 0.1 * warm }}>
      {f < whip ? (
        <Join kind="push" oval feather={0.3} at={push} len={18} hole={envelopeOnScreen(shot, push, w, h)}
          a={<Opening f={f} a={a} shot={shot} lighter={lighter} />} b={inside} />
      ) : (
        <Join kind="whip" dir="left" at={whip} len={12} a={inside}
          b={<Rise f={f} a={a} start={whip + 6} end={dur} mist={mist} />} />
      )}
    </Lens>
  );
}
