// The captions track: already phrase-split and timed items, each shown in the track's box with its style over
// caption defaults (white, heavy, fitted to one line, on a dark plate; a phrase too long for one line at the floor
// size wraps between words).
import React from "react";
import { Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { Box, CaptionItem, CaptionTrack, TextStyle, Theme } from "../types";
import { TEXT_DEFAULTS, TextBlock } from "./Text";

export const CAPTION_DEFAULTS: TextStyle = {
  ...TEXT_DEFAULTS, size: "fit", max_size: 66, min_size: 36, weight: 900, color: "#FFFFFF", accent: "gold",
  align: "center", valign: "middle", line_height: 1.2, bg: { color: "rgba(10,10,12,0.62)", radius: 14, pad: 14 },
  shadow: "0 2px 8px rgba(0,0,0,0.5)",
};

/** Without a box: a 200 px band at the bottom of the safe area. */
export const captionBox = (track: CaptionTrack, safe: Box): Box =>
  track.box && track.box.w > 0 && track.box.h > 0 ? track.box : { x: safe.x, y: safe.y + safe.h - 200, w: safe.w, h: 200 };

const Item: React.FC<{ item: CaptionItem; track: CaptionTrack; box: Box; theme: Theme }> = ({ item, track, box, theme }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: f, fps, config: { damping: 18, stiffness: 240 }, durationInFrames: 8 });
  return (
    <div
      data-clip={track.id}
      data-track={track.id}
      style={{
        position: "absolute", left: box.x, top: box.y, width: box.w, height: box.h, transform: `scale(${0.94 + 0.06 * pop})`,
      }}
    >
      <TextBlock
        runs={item.runs ?? []} style={track.style} base={CAPTION_DEFAULTS} w={box.w} h={box.h} theme={theme} fps={fps}
        maxLines={1}
      />
    </div>
  );
};

export const Captions: React.FC<{ track: CaptionTrack; safe: Box; theme: Theme }> = ({ track, safe, theme }) => {
  const box = captionBox(track, safe);
  return (
    <>
      {(track.items ?? []).map((item, i) =>
        item && Math.round(item.to) > Math.round(item.from) ? (
          <Sequence
            key={i} from={Math.round(item.from)} durationInFrames={Math.round(item.to) - Math.round(item.from)} layout="none"
            name={`${track.id} ${i + 1}`}
          >
            <Item item={item} track={track} box={box} theme={theme} />
          </Sequence>
        ) : null,
      )}
    </>
  );
};
