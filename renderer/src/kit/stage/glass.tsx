// Speed and glass: a picture streaking past inside an opening (scenery outside a moving window), and a pane that
// darkens and mirrors another layer (a window going into a tunnel).
import React, { useId } from "react";
import { Img } from "remotion";
import { useClip } from "../context";
import { assetSrc } from "../helpers";
import type { AssetRef } from "../helpers";
import { pictureSize } from "./photo";
import { clamp01 } from "./time";

export type StreakProps = {
  src: AssetRef | string;
  imgW?: number; imgH?: number;
  /** the opening in stage px [x, y, w, h], and its corner radius */
  box: [number, number, number, number];
  round?: number;
  /** distance travelled in px (distanceAt gives it from a speed) and the speed now in px per frame */
  pos: number;
  speed?: number;
  /** which way the scenery runs */
  dir?: "left" | "right";
  /** picture height as a multiple of the box height, and its vertical placement 0..1 */
  zoom?: number;
  align?: number;
  /** motion blur in px per px of speed, capped */
  blurK?: number;
  maxBlur?: number;
};

/** Scenery running past an opening: the picture repeats mirrored (no seam), smeared along the run by its speed. */
export function Streak({ src, imgW, imgH, box, round = 0, pos, speed = 0, dir = "left", zoom = 1.15, align = 0.5, blurK = 0.8, maxBlur = 70 }: StreakProps) {
  const id = "sk" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const [x, y, bw, bh] = box;
  const [IW, IH] = pictureSize(src, imgW, imgH, "Streak");
  const th = bh * zoom, tw = (th * IW) / IH;
  const off = (((pos % (2 * tw)) + 2 * tw) % (2 * tw)) * (dir === "left" ? -1 : 1);
  const blur = Math.min(maxBlur, Math.abs(speed) * blurK);
  const n = Math.ceil(bw / tw) + 3;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: bw, height: bh, overflow: "hidden", borderRadius: round }}>
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id={id} x="-5%" y="0" width="110%" height="100%"><feGaussianBlur stdDeviation={`${blur.toFixed(1)} 0.01`} /></filter>
      </svg>
      <div style={{ position: "absolute", left: -2 * tw, top: (bh - th) * align, height: th, width: n * tw + 4 * tw,
        transform: `translateX(${off}px)`, filter: blur > 0.4 ? `url(#${id})` : undefined }}>
        {Array.from({ length: n + 4 }, (_, i) => (
          <Img key={i} src={assetSrc(src)} style={{ position: "absolute", left: i * tw, top: 0, width: tw, height: th, maxWidth: "none",
            transform: i % 2 ? "scaleX(-1)" : undefined }} />
        ))}
      </div>
    </div>
  );
}

export type PaneProps = {
  /** the glass in stage px [x, y, w, h], and its corner radius */
  box: [number, number, number, number];
  round?: number;
  /** 0..1 how dark it is outside (a tunnel); the darker, the more the glass mirrors */
  dark?: number;
  /** what the glass mirrors (drawn in stage px, flipped left to right about the box), and how strongly */
  reflect?: React.ReactNode;
  reflectA?: number;
  /** a faint diagonal sheen */
  sheen?: number;
};

/** A sheet of glass over an opening: it darkens, carries a sheen and mirrors another layer more as it darkens. */
export function Pane({ box, round = 0, dark = 0, reflect, reflectA = 0.5, sheen = 0.1 }: PaneProps) {
  const { w, h } = useClip();
  const [x, y, bw, bh] = box;
  const d = clamp01(dark);
  const mirror = reflect ? clamp01(reflectA * (0.2 + 0.8 * d)) : 0;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: bw, height: bh, overflow: "hidden", borderRadius: round, pointerEvents: "none" }}>
      {d > 0 ? <div style={{ position: "absolute", inset: 0, background: `rgba(6,8,11,${(0.9 * d).toFixed(3)})` }} /> : null}
      {mirror > 0.01 ? (
        <div style={{ position: "absolute", left: -x, top: -y, width: w, height: h, opacity: mirror, mixBlendMode: "screen",
          transformOrigin: `${x + bw / 2}px 50%`, transform: "scaleX(-1)", filter: "blur(2px) saturate(0.7)" }}>
          {reflect}
        </div>
      ) : null}
      {sheen > 0 ? <div style={{ position: "absolute", inset: 0,
        background: `linear-gradient(115deg, rgba(255,255,255,0) 30%, rgba(255,255,255,${sheen}) 45%, rgba(255,255,255,0) 60%)` }} /> : null}
    </div>
  );
}
