// Narration and audio clips: each placed at its frame, trimmed, with its volume (or volume curve), linear fades
// (frames; crossfades arrive as fades) and ducking; a looping clip repeats its asset (from trimIn) until it ends.
import React from "react";
import { Sequence, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import type { AudioItem } from "../types";
import { curveAt, duckAt } from "./sound";
import { num, srcUrl } from "./util";

/** Gain at frame f of an item `dur` frames long. Volumes above 1 are capped: mastering sets the loudness. */
export const gainAt = (a: AudioItem, f: number, fps = 30): number =>
  curveAt(a.volume, a.volumeKeys, a.fadeIn, a.fadeOut, a.dur, f, fps) * duckAt(a.duck, f);

export const AudioTrack: React.FC<{ items: AudioItem[] }> = ({ items }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {items.map((a, i) =>
        a && a.src && a.dur > 0 ? (
          <Sequence key={`${a.id}-${i}`} from={Math.round(a.from)} durationInFrames={Math.round(a.dur)} layout="none" name={`audio ${a.id}`}>
            <Audio
              src={srcUrl(a.src)}
              trimBefore={num(a.trimIn, 0) > 0 ? Math.round(num(a.trimIn, 0)) : undefined}
              volume={(f: number) => gainAt(a, f, fps)}
              loop={a.loop === true}
              // fades and curves count over the whole clip, not again on every pass
              loopVolumeCurveBehavior="extend"
            />
          </Sequence>
        ) : null,
      )}
    </>
  );
};
