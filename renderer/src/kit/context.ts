// What a clip's content (and every component) knows about the box it renders in.
import { createContext, useContext } from "react";
import { useVideoConfig } from "remotion";
import type { Box, Theme } from "../types";

export type ClipCtx = {
  /** the clip box size now (keyframed w/h included) */
  w: number;
  h: number;
  /** the clip's length in frames */
  dur: number;
  fps: number;
  theme: Theme;
  /** the canvas */
  width: number;
  height: number;
  /** the platform's UI-safe area, canvas pixels */
  safe: Box;
  /** 0..1: the clip's "progress" keyframes, else its elapsed fraction */
  progress: number;
};

export const ClipContext = createContext<ClipCtx | null>(null);

const FALLBACK_THEME: Theme = {
  paper: "#F3EBDD", ink: "#1E1A16", night: "#16130F", snow: "#F7F1E6", accent: "#C8372D", gold: "#D9A441",
  good: "#2E8B57", bad: "#C8372D", muted: "#7A6F62",
};

/** The clip's box, length and theme; outside a clip (e.g. the Studio) it describes the whole canvas. */
export const useClip = (): ClipCtx => {
  const ctx = useContext(ClipContext);
  const { width, height, fps, durationInFrames } = useVideoConfig();
  if (ctx) return ctx;
  return {
    w: width, h: height, dur: durationInFrames, fps, theme: FALLBACK_THEME, width, height,
    safe: { x: 0, y: 0, w: width, h: height }, progress: 0,
  };
};
