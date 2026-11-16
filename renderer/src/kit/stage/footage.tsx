// Footage: a short video clip as a layer of the photographic world (a tween between key pictures of one shot, a
// camera travelling through a still), placed, lit and timed like a Photo.
import React, { useId } from "react";
import { Freeze, Img, useCurrentFrame } from "remotion";
import { Video } from "@remotion/media";
import type { VideoObjectFit } from "@remotion/media";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import { isVideo } from "../../elements/Media";
import { Layer, useDepth, useStage } from "./Stage";
import { useLens } from "./lens";
import { dofBlur, filmFrame, onScreen, showsFilm, viewed } from "./optics";
import type { FilmTiming } from "./optics";
import { lightMatrix, pictureSize, useView } from "./photo";
import type { Pt } from "./geom";

/** A clip and when it plays (see FilmTiming): `at` frame, `rate`, `from` seconds in, `len` seconds, `loop`, `hold`. */
export type Film = FilmTiming & { src: AssetRef | string };

/** Whether an asset ref or path is a video clip. */
export const isFilm = (src: AssetRef | string | undefined): boolean =>
  !!src && isVideo(typeof src === "string" ? { src } : src);

/** The clip's length in seconds when its ref knows it. */
export const filmDuration = (src: AssetRef | string): number | null => (isAsset(src) && src.duration ? src.duration : null);

/** One frame of a clip filling its parent. `frame` counts clip frames at the composition's fps from the clip start. */
export function FilmFrame({ src, frame, fit = "fill", style }: { src: AssetRef | string; frame: number; fit?: VideoObjectFit; style?: React.CSSProperties }) {
  // decoded in the page (WebCodecs) as Media.tsx does: OffthreadVideo's shared frame cache drops frames with parallel tabs
  return (
    <Freeze frame={0}>
      <Video src={assetSrc(src)} muted trimBefore={frame > 0 ? frame : undefined} objectFit={fit}
        style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", ...style }} />
    </Freeze>
  );
}

export type FootageProps = Film & {
  /** the picture the clip was made from: shown instead of the clip while it is not running and not held (and
   *  before it starts, where the clip's first frame is that picture), and the size when the clip's is unknown */
  still?: AssetRef | string;
  imgW?: number; imgH?: number;
  /** where the anchor point stands, in stage px of its layer */
  x: number; y: number;
  /** drawn width or height in stage px (default the picture's size times `s`); both with `fit` to box it */
  w?: number; h?: number;
  s?: number;
  fit?: VideoObjectFit;
  anchor?: Pt;
  r?: number;
  flip?: boolean;
  depth?: number;
  /** extra blur in px, added to the lens's depth of field */
  blur?: number;
  shade?: number; tint?: string; tintA?: number; haze?: number; hazeColor?: string;
  opacity?: number;
  f?: number;
};

/** A video clip standing in the world like a Photo; it draws nothing while it is off screen or not shown. */
export function Footage(p: FootageProps) {
  if (p.depth !== undefined) {
    const { depth, ...rest } = p;
    return <Layer depth={depth}><Footage {...rest} /></Layer>;
  }
  return <FootageBody {...p} />;
}

function FootageBody({ src, at, rate, from, len, loop, hold, still, imgW, imgH, x, y, w, h, s = 1, fit = "fill", anchor = [0.5, 0.5], r = 0,
  flip = false, blur = 0, shade = 0, tint = "#FFFFFF", tintA = 0, haze = 0, hazeColor, opacity = 1, f: fIn }: FootageProps) {
  const id = "ft" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w: cw, h: ch, fps } = useClip();
  const depth = useDepth();
  const lens = useLens();
  const { cam } = useStage();
  const view = useView();
  const [IW, IH] = pictureSize(isAsset(still) && still.size ? still : src, imgW, imgH, "Footage");
  const dw = w ?? (h ? (h * IW) / IH : IW * s), dh = h ?? (dw * IH) / IW;
  const ox = -anchor[0] * dw, oy = -anchor[1] * dh;
  const timing = { at, rate, from, len, loop, hold };
  const ff = filmFrame(timing, f, fps || 30, filmDuration(src));
  const frame = ff.frame;
  if (opacity <= 0 || (frame === null && !still)) return null;
  // off screen (with a margin for rotation, drift and hand-held moves): decode nothing
  const rad = (r * Math.PI) / 180, c = Math.cos(rad), sn = Math.sin(rad);
  const pts = [[ox, oy], [ox + dw, oy], [ox, oy + dh], [ox + dw, oy + dh]].map(([lx, ly]) =>
    onScreen(cam, depth, cw, ch, viewed(view, cw, ch, [x + lx * c - ly * sn, y + lx * sn + ly * c])));
  const m = 0.1 * Math.max(cw, ch);
  if (Math.max(...pts.map((q) => q.x)) < -m || Math.min(...pts.map((q) => q.x)) > cw + m
    || Math.max(...pts.map((q) => q.y)) < -m || Math.min(...pts.map((q) => q.y)) > ch + m) return null;
  const showStill = !!still && !showsFilm(timing, ff);
  const dof = dofBlur(depth, lens.focus, lens.aperture) + blur;
  const lit = shade > 0 || tintA > 0 || haze > 0;
  const filter = [dof > 0.3 ? `blur(${dof.toFixed(2)}px)` : "", lit ? `url(#${id})` : ""].join(" ").trim() || undefined;
  return (
    <div style={{
      position: "absolute", left: x + ox, top: y + oy, width: dw, height: dh, opacity, filter, pointerEvents: "none",
      transformOrigin: `${-ox}px ${-oy}px`, transform: r || flip ? `rotate(${r}deg)${flip ? " scaleX(-1)" : ""}` : undefined,
    }}>
      {lit ? (
        <svg width={0} height={0} style={{ position: "absolute" }}>
          <filter id={id} colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={lightMatrix(shade, tint, tintA, haze, hazeColor)} /></filter>
        </svg>
      ) : null}
      {showStill
        ? <Img src={assetSrc(still as AssetRef | string)} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", objectFit: fit, maxWidth: "none" }} />
        : <FilmFrame src={src} frame={frame as number} fit={fit} />}
    </div>
  );
}
