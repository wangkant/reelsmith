// A picture or a clip filling its parent (cover/contain around a focus point), optionally moving (Ken Burns).
// The image/video clip types use it with no motion (their motion is zoom/pan keyframes on the clip); the kit
// re-exports it for components.
import React from "react";
import { Easing, Freeze, Img, interpolate, Loop, useCurrentFrame } from "remotion";
import { Video, type VideoObjectFit } from "@remotion/media";
import { useClip } from "../kit/context";
import type { Keyframe, MediaRef } from "../types";
import { audible, curveAt } from "./sound";
import { clamp01, num, srcUrl } from "./util";

export type Motion = "push" | "pull" | "pan_left" | "pan_right" | "rise" | "still";

export type MediaProps = {
  /** an asset ref as components receive it, or a project-relative path */
  media: MediaRef | string;
  fit?: "cover" | "contain";
  /** 0..1 point kept in view when cropping (and zoomed towards) */
  focus?: [number, number] | null;
  /** a slow move over `dur` frames (default: the clip's length) */
  motion?: Motion | null;
  dur?: number;
  /** video only: frames skipped at the start, speed, loop when the clip outlasts the source, volume (0 = muted) */
  trimIn?: number;
  rate?: number;
  loop?: boolean;
  volume?: number;
  /** video only: a volume curve (frames from the clip start) replacing `volume`, and fades in frames */
  volumeKeys?: Keyframe[] | null;
  fadeIn?: number;
  fadeOut?: number;
  /** a dark veil 0..1 over the picture, for text on top */
  dim?: number;
  style?: React.CSSProperties;
};

const VIDEO_EXT = /\.(mp4|m4v|mov|webm|mkv)$/i;

export const isVideo = (m: MediaRef) => m.kind === "video" || (!m.kind && VIDEO_EXT.test(m.src));

const motionTransform = (motion: Motion | null | undefined, t: number): string | undefined => {
  if (!motion || motion === "still") return undefined;
  const k = Easing.inOut(Easing.sin)(clamp01(t));
  switch (motion) {
    case "pull":
      return `scale(${1.12 - 0.1 * k})`;
    case "pan_left":
      return `scale(1.14) translateX(${(0.5 - k) * 6}%)`;
    case "pan_right":
      return `scale(1.14) translateX(${(k - 0.5) * 6}%)`;
    case "rise":
      return `scale(1.1) translateY(${(0.5 - k) * 4}%)`;
    default:
      return `scale(${1.02 + 0.1 * k})`;
  }
};

const VideoBody: React.FC<{
  m: MediaRef; style: React.CSSProperties; trimIn: number; rate: number; loop: boolean; volume: number; fps: number;
  keys?: Keyframe[] | null; fadeIn?: number; fadeOut?: number; dur: number;
}> = ({ m, style, trimIn, rate, loop, volume, fps, keys, fadeIn, fadeOut, dur }) => {
  const f = useCurrentFrame();
  const src = srcUrl(m.src);
  const { objectFit, ...css } = style;
  const srcFrames = m.duration && m.duration > 0 ? Math.floor(m.duration * fps) : null;
  // composition frames the source covers; one frame of margin: asking for the very last frame can fail
  const playable = srcFrames === null ? null : Math.floor((srcFrames - trimIn - 1) / rate);
  const heard = audible(volume, keys);
  const curved = (keys?.length ?? 0) > 0 || num(fadeIn, 0) > 0 || num(fadeOut, 0) > 0;
  // inside a Loop the frame starts over on every pass; the curve counts over the whole clip
  const pass = loop && playable !== null && playable >= 1 ? Math.floor(f / playable) * playable : 0;
  const level = !heard ? undefined : curved ? (fr: number) => curveAt(volume, keys, fadeIn, fadeOut, dur, fr + pass, fps) : volume;
  // decoded in the page (WebCodecs): OffthreadVideo's shared frame cache drops frames under memory pressure with
  // parallel tabs ("No frame found at position"); a file the browser cannot decode still falls back to it
  const video = (
    <Video
      src={src}
      trimBefore={trimIn > 0 ? Math.round(trimIn) : undefined}
      playbackRate={rate}
      muted={!heard}
      volume={level}
      objectFit={(objectFit as VideoObjectFit | undefined) ?? "cover"}
      style={css}
    />
  );
  if (playable === null) return video;
  if (playable < 1) return <Freeze frame={0}>{video}</Freeze>;
  if (loop) return <Loop durationInFrames={playable}>{video}</Loop>;
  return (
    <Freeze frame={playable - 1} active={f >= playable}>
      {video}
    </Freeze>
  );
};

export const Media: React.FC<MediaProps> = ({
  media, fit = "cover", focus, motion, dur, trimIn = 0, rate = 1, loop = false, volume = 0, volumeKeys, fadeIn, fadeOut,
  dim = 0, style,
}) => {
  const f = useCurrentFrame();
  const clip = useClip();
  const m: MediaRef = typeof media === "string" ? { src: media } : media;
  if (!m || !m.src) return null;
  const [fx, fy] = focus && focus.length === 2 ? focus : [0.5, 0.5];
  const length = Math.max(1, dur ?? clip.dur);
  const transform = motionTransform(motion, interpolate(f, [0, length], [0, 1]));
  const inner: React.CSSProperties = {
    position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: fit,
    objectPosition: `${clamp01(fx) * 100}% ${clamp01(fy) * 100}%`, transform,
    transformOrigin: `${clamp01(fx) * 100}% ${clamp01(fy) * 100}%`, maxWidth: "none", ...style,
  };
  const body = isVideo(m) ? (
    <VideoBody
      m={m} style={inner} trimIn={Math.max(0, trimIn)} rate={rate > 0 ? rate : 1} loop={loop} volume={volume} fps={clip.fps}
      keys={volumeKeys} fadeIn={fadeIn} fadeOut={fadeOut} dur={clip.dur}
    />
  ) : (
    <Img src={srcUrl(m.src)} style={inner} />
  );
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      {body}
      {dim > 0 ? <div style={{ position: "absolute", inset: 0, background: `rgba(8,8,10,${clamp01(dim)})` }} /> : null}
    </div>
  );
};
