// The one composition: plays a resolved.json. Tracks paint bottom to top; each clip lives in a Sequence.
import React, { useRef } from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { AudioTrack } from "./elements/AudioTrack";
import { Captions } from "./elements/Captions";
import { Element } from "./elements/Element";
import { useFontsReady } from "./fonts";
import { useInspect } from "./inspect";
import type { Box, CaptionTrack, FilmProps, RenderMode, Resolved, Theme, VisualTrack } from "./types";

const FALLBACK_THEME: Theme = {
  paper: "#F3EBDD", ink: "#1E1A16", night: "#16130F", snow: "#F7F1E6", accent: "#C8372D", gold: "#D9A441",
  good: "#2E8B57", bad: "#C8372D", muted: "#7A6F62",
};

const Stage: React.FC<{ r: Resolved; mode: RenderMode }> = ({ r, mode }) => {
  const root = useRef<HTMLDivElement>(null);
  useInspect(!!r.inspect, root, r.width, r.height);
  const theme = { ...FALLBACK_THEME, ...(r.theme ?? {}) };
  const safe: Box = r.safe ?? { x: 0, y: 0, w: r.width, h: r.height };
  return (
    <div ref={root} style={{ position: "absolute", left: 0, top: 0, width: r.width, height: r.height, overflow: "hidden" }}>
      {r.tracks.map((track) => {
        if (!track || track.hidden) return null;
        if (track.kind === "visual") {
          return (
            <React.Fragment key={track.id}>
              {((track as VisualTrack).clips ?? []).map((clip) =>
                clip && clip.dur > 0 ? (
                  <Sequence key={clip.id} from={Math.round(clip.from)} durationInFrames={Math.round(clip.dur)} layout="none" name={clip.id}>
                    <Element clip={{ ...clip, track: clip.track ?? track.id }} theme={theme} safe={safe} mode={mode} />
                  </Sequence>
                ) : null,
              )}
            </React.Fragment>
          );
        }
        if (track.kind === "captions") return <Captions key={track.id} track={track as CaptionTrack} safe={safe} theme={theme} />;
        return null;
      })}
      <AudioTrack items={r.audio ?? []} />
    </div>
  );
};

export const Film: React.FC<FilmProps> = ({ resolved, mode = "studio" }) => {
  const ready = useFontsReady();
  const ok = !!resolved && Array.isArray(resolved.tracks);
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {ok && ready ? <Stage r={resolved} mode={mode} /> : null}
    </AbsoluteFill>
  );
};
