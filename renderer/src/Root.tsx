import React from "react";
import { Composition } from "remotion";
import { Film } from "./Film";
import "./fonts";
import type { FilmProps, Resolved } from "./types";

// What the Studio shows without input props: an empty 2 s canvas.
const EMPTY: Resolved = {
  version: 2, fps: 30, width: 1080, height: 1920, durationInFrames: 60, safe: { x: 40, y: 220, w: 840, h: 1240 },
  theme: {
    paper: "#F3EBDD", ink: "#1E1A16", night: "#16130F", snow: "#F7F1E6", accent: "#C8372D", gold: "#D9A441",
    good: "#2E8B57", bad: "#C8372D", muted: "#7A6F62",
  },
  tracks: [], audio: [], inspect: false,
};

const positive = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.round(v) : fallback);

export const Root: React.FC = () => (
  <Composition
    id="Film"
    component={Film as unknown as React.FC<Record<string, unknown>>}
    defaultProps={{ resolved: EMPTY, mode: "studio" } satisfies FilmProps}
    durationInFrames={EMPTY.durationInFrames}
    fps={EMPTY.fps}
    width={EMPTY.width}
    height={EMPTY.height}
    calculateMetadata={({ props }) => {
      const r = (props as unknown as FilmProps).resolved ?? EMPTY;
      return {
        durationInFrames: positive(r.durationInFrames, EMPTY.durationInFrames),
        fps: positive(r.fps, EMPTY.fps),
        width: positive(r.width, EMPTY.width),
        height: positive(r.height, EMPTY.height),
      };
    }}
  />
);
