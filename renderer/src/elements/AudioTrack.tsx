// Narration and audio clips: each placed at its frame, trimmed, with volume and linear fades (frames); a looping
// clip repeats its asset (from trimIn) until the clip ends.
import React from "react";
import { Sequence } from "remotion";
import { Audio } from "@remotion/media";
import type { AudioItem } from "../types";
import { clamp01, num, srcUrl } from "./util";

/** Gain at frame f of an item `dur` frames long. Volumes above 1 are capped: mastering sets the loudness. */
export const gainAt = (a: AudioItem, f: number): number => {
  const v = Math.max(0, Math.min(1, num(a.volume, 1)));
  const fin = Math.max(0, num(a.fadeIn, 0));
  const fout = Math.max(0, num(a.fadeOut, 0));
  const up = fin > 0 ? clamp01(f / fin) : 1;
  const down = fout > 0 ? clamp01((a.dur - f) / fout) : 1;
  return v * up * down;
};

export const AudioTrack: React.FC<{ items: AudioItem[] }> = ({ items }) => (
  <>
    {items.map((a, i) =>
      a && a.src && a.dur > 0 ? (
        <Sequence key={`${a.id}-${i}`} from={Math.round(a.from)} durationInFrames={Math.round(a.dur)} layout="none" name={`audio ${a.id}`}>
          <Audio
            src={srcUrl(a.src)}
            trimBefore={num(a.trimIn, 0) > 0 ? Math.round(num(a.trimIn, 0)) : undefined}
            volume={(f: number) => gainAt(a, f)}
            loop={a.loop === true}
            // fades count over the whole clip, not again on every pass
            loopVolumeCurveBehavior="extend"
          />
        </Sequence>
      ) : null,
    )}
  </>
);
