// The captions track: already phrase-split and timed items, each shown in the track's box with its style over
// caption defaults (white, heavy, fitted to one line, on a dark plate; a phrase too long for one line at the floor
// size wraps between words). Sizes are written for a 1080 px short side and follow the canvas. With word times, mode
// "words" paints the word being said in the accent colour and "build" shows words as they are said (the phrase is
// laid out whole, so nothing moves).
import React from "react";
import { Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { Box, CaptionItem, CaptionMode, CaptionTrack, DrawnRun, TextStyle, Theme } from "../types";
import { TEXT_DEFAULTS, TextBlock } from "./Text";
import { clamp01 } from "./util";

const BUILD_FADE = 3;   // frames a word takes to appear in "build" mode

/** The item's runs at absolute frame `frame`, painted by its word times. Characters outside every word (spaces,
 *  leading quotes) go with the next word, or the last one. */
export const paintWords = (item: CaptionItem, mode: CaptionMode | undefined, frame: number): DrawnRun[] => {
  const runs = (item.runs ?? []).filter((r) => r && typeof r.text === "string");
  const words = (item.words ?? []).filter((w) => w && Array.isArray(w.chars));
  if (!words.length || (mode !== "words" && mode !== "build")) return runs;
  const chars: Array<{ c: string; accent: boolean }> = [];
  for (const r of runs) for (const c of [...r.text]) chars.push({ c, accent: !!r.accent });
  const owner = new Array<number>(chars.length).fill(-1);
  words.forEach((w, i) => {
    for (let k = Math.max(0, w.chars[0]); k < Math.min(chars.length, w.chars[1]); k++) owner[k] = i;
  });
  let next = words.length - 1;
  for (let k = chars.length - 1; k >= 0; k--) {
    if (owner[k] >= 0) next = owner[k];
    else owner[k] = next;
  }
  const out: DrawnRun[] = [];
  chars.forEach(({ c, accent }, k) => {
    const w = words[owner[k]];
    const run: DrawnRun = mode === "words"
      ? { text: c, accent: frame >= w.from && frame < w.to }
      : { text: c, accent, o: clamp01((frame - w.from + 1) / BUILD_FADE) };
    const last = out[out.length - 1];
    if (last && last.accent === run.accent && last.o === run.o) last.text += c;
    else out.push(run);
  });
  return out;
};

export const CAPTION_DEFAULTS: TextStyle = {
  ...TEXT_DEFAULTS, size: "fit", max_size: 66, min_size: 36, weight: 900, color: "#FFFFFF", accent: "gold",
  align: "center", valign: "middle", line_height: 1.2, bg: { color: "rgba(10,10,12,0.62)", radius: 14, pad: 14 },
  shadow: "0 2px 8px rgba(0,0,0,0.5)",
};

/** The canvas's short side / 1080: what caption sizes are multiplied by. */
export const canvasScale = (width: number, height: number): number =>
  width > 0 && height > 0 ? Math.min(width, height) / 1080 : 1;

/** CAPTION_DEFAULTS sized for the canvas. */
export const captionDefaults = (scale: number): TextStyle =>
  scale === 1
    ? CAPTION_DEFAULTS
    : {
        ...CAPTION_DEFAULTS, max_size: Math.round(66 * scale), min_size: Math.round(36 * scale),
        bg: { ...CAPTION_DEFAULTS.bg, radius: Math.round(14 * scale), pad: Math.round(14 * scale) },
      };

/** Without a box (resolve.py always sends the profile's): the safe area's bottom band, 200 px at scale 1. */
export const captionBox = (track: CaptionTrack, safe: Box, scale = 1): Box => {
  if (track.box && track.box.w > 0 && track.box.h > 0) return track.box;
  const band = Math.min(safe.h, Math.round(200 * scale));
  return { x: safe.x, y: safe.y + safe.h - band, w: safe.w, h: band };
};

const Item: React.FC<{ item: CaptionItem; track: CaptionTrack; box: Box; theme: Theme }> = ({ item, track, box, theme }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
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
        runs={paintWords(item, track.mode, Math.round(item.from) + f)} style={track.style} base={captionDefaults(canvasScale(width, height))}
        w={box.w} h={box.h} theme={theme} fps={fps} maxLines={1}
      />
    </div>
  );
};

export const Captions: React.FC<{ track: CaptionTrack; safe: Box; theme: Theme }> = ({ track, safe, theme }) => {
  const { width, height } = useVideoConfig();
  const box = captionBox(track, safe, canvasScale(width, height));
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
