// A captured page cropped to its proving sentence (`box`, capture pixels): the sentence scaled to the window's width
// (or height), page context only above and below it, and a panel that hugs that content instead of padding the window
// with page or white. Where the crop cuts into the page (the characters beside the sentence, the context's outer
// lines) it fades out, so no half glyph shows a hard edge. An optional highlighter sweeps across the sentence. The
// evidence clip type is exactly this; the kit re-exports it for components.
import React from "react";
import { Easing, Img, interpolate, useCurrentFrame } from "remotion";
import { useClip } from "../kit/context";
import type { Highlight, MediaRef } from "../types";
import { color, srcUrl } from "./util";

/** Captures are 3x DPR: past 2x of that they turn soft. */
export const MAX_ZOOM = 2;

type Rect = { x: number; y: number; w: number; h: number };

export type EvidenceLayout = {
  /** capture pixels -> window pixels */
  s: number;
  /** where the whole capture lands in the window (drawn there, clipped to `panel`) */
  left: number;
  top: number;
  imgW: number;
  imgH: number;
  /** the proving sentence in window pixels */
  mark: Rect;
  /** the part of the window the content fills (centred); outside it the window stays empty */
  panel: Rect;
  /** fade widths at the panel's edges, window px (0 where the panel ends at the capture's own edge) */
  fade: { left: number; right: number; top: number; bottom: number };
  /** true when page above/below the sentence shows */
  context: boolean;
};

type EvidenceLike = Pick<MediaRef, "size" | "box">;

/** How a capture sits in a w x h window. The sentence plus a margin of about a third of a line on each side (where the
 *  neighbouring characters fade out) is scaled to the window's width, or its height when the window is short, at most
 *  MAX_ZOOM; up to `context` capture px of page above and below fill the height the sentence leaves. */
export const evidenceLayout = (ev: EvidenceLike, w: number, h: number, context?: number): EvidenceLayout | null => {
  const size = ev.size;
  if (!size || !(size[0] > 0) || !(size[1] > 0) || !(w > 0) || !(h > 0)) return null;
  const [W, H] = size;
  const raw = ev.box && ev.box.length === 4 ? ev.box : [0, 0, W, H];
  const bx = Math.max(0, Math.min(W - 1, raw[0]));
  const by = Math.max(0, Math.min(H - 1, raw[1]));
  const bw = Math.max(1, Math.min(W - bx, raw[2]));
  const bh = Math.max(1, Math.min(H - by, raw[3]));
  // about a third of a line: the neighbouring characters show only inside the fade
  const margin = Math.max(10, Math.min(40, bh * 0.35));
  const x0 = Math.max(0, bx - margin);
  const x1 = Math.min(W, bx + bw + margin);
  const s = Math.min(w / (x1 - x0), h / bh, MAX_ZOOM);
  // context: what was asked, what the page has, and what the window's height leaves, shared above and below
  const want = Math.max(0, context ?? Math.max(40, Math.min(240, bh * 0.35)));
  const room = Math.max(0, h / s - bh);
  let above = Math.min(want, by);
  let below = Math.min(want, H - by - bh);
  if (above + below > room) {
    const half = room / 2;
    if (above < half) below = room - above;
    else if (below < half) above = room - below;
    else above = below = half;
  }
  const y0 = by - above;
  const y1 = by + bh + below;
  const pw = (x1 - x0) * s;
  const ph = (y1 - y0) * s;
  const panel = { x: (w - pw) / 2, y: (h - ph) / 2, w: pw, h: ph };
  return {
    s, left: panel.x - x0 * s, top: panel.y - y0 * s, imgW: W * s, imgH: H * s,
    mark: { x: panel.x + (bx - x0) * s, y: panel.y + above * s, w: bw * s, h: bh * s },
    panel,
    fade: {
      left: x0 > 0 ? (bx - x0) * s : 0,
      right: x1 < W ? (x1 - bx - bw) * s : 0,
      top: y0 > 0 ? above * s * 0.85 : 0,
      bottom: y1 < H ? below * s * 0.85 : 0,
    },
    context: above + below > 8,
  };
};

export type EvidenceCropProps = {
  ev: MediaRef;
  /** window size; default the clip box */
  w?: number;
  h?: number;
  /** `at`, `dur` in frames from the clip start; null/undefined = no sweep */
  highlight?: Highlight | null;
  /** capture px of page shown above and below the sentence (at most: the window's height may leave less) */
  context?: number;
  /** the page colour the cut edges fade into */
  background?: string;
  /** corner radius of the panel */
  radius?: number;
};

/** A strip at one edge: solid page colour for its outer third, then easing to transparent. */
const Edge: React.FC<{ to: string; background: string; at: React.CSSProperties }> = ({ to, background, at }) => (
  <div style={{ position: "absolute", ...at, background: `linear-gradient(${to}, ${background} 0%, ${background} 30%, transparent 100%)` }} />
);

export const EvidenceCrop: React.FC<EvidenceCropProps> = ({ ev, w, h, highlight, context, background = "#FFFFFF", radius = 0 }) => {
  const f = useCurrentFrame();
  const clip = useClip();
  const W = w ?? clip.w;
  const H = h ?? clip.h;
  if (!ev || !ev.src) return null;
  const L = evidenceLayout(ev, W, H, context);
  const src = srcUrl(ev.src);
  if (!L) {
    return <Img src={src} style={{ position: "absolute", left: 0, top: 0, width: W, height: H, objectFit: "contain" }} />;
  }
  let sweep = 0;
  if (highlight) {
    const at = highlight.at ?? Math.round(0.3 * clip.fps);
    const len = Math.max(1, highlight.dur ?? Math.round(0.8 * clip.fps));
    sweep = interpolate(f, [at, at + len], [0, 1], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic),
    });
  }
  const { panel, fade } = L;
  return (
    <div style={{
      position: "absolute", left: panel.x, top: panel.y, width: panel.w, height: panel.h, overflow: "hidden", background,
      borderRadius: radius || undefined,
    }}>
      <Img src={src} style={{
        position: "absolute", left: L.left - panel.x, top: L.top - panel.y, width: L.imgW, height: L.imgH, maxWidth: "none",
      }} />
      {sweep > 0 ? (
        <div style={{
          position: "absolute", left: L.mark.x - panel.x - 6, top: L.mark.y - panel.y + L.mark.h * 0.07,
          width: (L.mark.w + 12) * sweep, height: L.mark.h * 0.86, background: color(clip.theme, highlight?.color, clip.theme.gold),
          opacity: 0.42, mixBlendMode: "multiply", borderRadius: 6,
        }} />
      ) : null}
      {fade.top > 2 ? <Edge to="to bottom" background={background} at={{ left: 0, right: 0, top: 0, height: fade.top }} /> : null}
      {fade.bottom > 2 ? <Edge to="to top" background={background} at={{ left: 0, right: 0, bottom: 0, height: fade.bottom }} /> : null}
      {fade.left > 2 ? <Edge to="to right" background={background} at={{ top: 0, bottom: 0, left: 0, width: fade.left }} /> : null}
      {fade.right > 2 ? <Edge to="to left" background={background} at={{ top: 0, bottom: 0, right: 0, width: fade.right }} /> : null}
    </div>
  );
};
