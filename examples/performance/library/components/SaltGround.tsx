// The film's one ground: kraft paper over a wooden table, warm light and a slow drift under every scene.
import React from "react";
import { KraftGround, Layer, Stage, TableTop } from "@reelsmith/kit";

export default function SaltGround() {
  return (
    <Stage ground={<KraftGround seed="salt" />} drift={10} grain={0.06} light={0.55} vignette={0.4}>
      <Layer depth={0.8}>
        <TableTop kind="wood" seed="salt" />
      </Layer>
    </Stage>
  );
}
