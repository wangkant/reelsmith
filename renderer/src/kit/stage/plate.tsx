// The backdrop plate: one full-frame generated photograph as the far layer, with slow life (drift, a swaying near
// strip), and occluders: the same plate clipped to a traced polygon and drawn again in front, so things pass behind.
import React, { createContext, useContext, useId } from "react";
import { Img, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { assetSrc } from "../helpers";
import type { AssetRef } from "../helpers";
import { Layer, useDepth } from "./Stage";
import { useLens } from "./lens";
import { coverFit, dofBlur, swayAngle } from "./optics";
import type { Fit } from "./optics";
import { Hold, pictureSize, SvgImage } from "./photo";
import type { Pt } from "./geom";

const PlateContext = createContext<Fit | null>(null);

/** The enclosing plate's fit: `at([px, py])` turns a point traced on the picture into stage px. */
export const usePlate = (): Fit => {
  const fit = useContext(PlateContext);
  if (!fit) throw new Error("usePlate: call it inside a <Plate>");
  return fit;
};

export type Sway = {
  /** picture y (px) where the swaying strip starts; it runs to the bottom */
  y: number;
  /** skew in degrees, cycles a second, feather of its top edge in picture px */
  amp?: number;
  hz?: number;
  feather?: number;
  /** a gust: frame and extra degrees, decaying over a second */
  gust?: number;
  gustAmp?: number;
};

export type PlateProps = {
  src: AssetRef | string;
  imgW?: number; imgH?: number;
  /** parallax depth of the plate and everything inside it */
  depth?: number;
  /** fraction kept beyond each edge, so camera moves never show a border */
  pad?: number;
  /** which part of the picture stays in frame when its aspect differs from the clip [0..1, 0..1] */
  focus?: Pt;
  /** slow life: a breathing drift of the whole plate in px */
  drift?: number;
  sway?: Sway;
  /** polygons traced in picture px: these parts of the plate are drawn again in front of the children */
  fronts?: Pt[][];
  /** softness of a front's edge in stage px */
  feather?: number;
  /** extra blur in px, added to the lens's depth of field */
  blur?: number;
  /** a CSS filter on the plate and its fronts (a local grade) */
  photo?: string;
  f?: number;
  /** what stands in the plate (stage px; usePlate().at maps traced points), drawn between the plate and its fronts */
  children?: React.ReactNode;
};

/** A full-frame photograph as the far layer: children stand in it, its traced fronts hide them. */
export function Plate({ depth = 0.9, ...p }: PlateProps) {
  return <Layer depth={depth}><PlateBody {...p} /></Layer>;
}

function PlateBody({ src, imgW, imgH, pad = 0.06, focus, drift = 0, sway, fronts = [], feather = 3, blur = 0, photo, f: fIn, children }: PlateProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const depth = useDepth();
  const lens = useLens();
  const [IW, IH] = pictureSize(src, imgW, imgH, "Plate");
  const fit = coverFit(IW, IH, w, h, pad, focus);
  const b = dofBlur(depth, lens.focus, lens.aperture) + blur;
  const filter = [b > 0.3 ? `blur(${b.toFixed(2)}px)` : "", photo ?? ""].join(" ").trim() || undefined;
  const sec = f / (fps || 30);
  const life = drift ? `translate(${(Math.sin(sec * 0.37) * drift).toFixed(2)}px, ${(Math.cos(sec * 0.29) * drift * 0.6).toFixed(2)}px) scale(${(1 + (drift / w) * (1 + Math.sin(sec * 0.21))).toFixed(5)})` : undefined;
  const img = (style?: React.CSSProperties) => (
    <Img src={assetSrc(src)} style={{ position: "absolute", left: fit.x, top: fit.y, width: fit.w, height: fit.h, maxWidth: "none", filter, ...style }} />
  );
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transform: life, transformOrigin: "50% 50%" }}>
      {img()}
      {sway ? <SwayStrip fit={fit} sway={sway} f={f} fps={fps || 30} img={img} /> : null}
      <PlateContext.Provider value={fit}>{children}</PlateContext.Provider>
      {fronts.map((poly, i) => <Front key={i} fit={fit} poly={poly} feather={feather} src={src} filter={filter} />)}
    </div>
  );
}

function SwayStrip({ fit, sway, f, fps, img }: { fit: Fit; sway: Sway; f: number; fps: number; img: (s?: React.CSSProperties) => React.ReactNode }) {
  const top = fit.y + sway.y * fit.s, fe = (sway.feather ?? 60) * fit.s;
  const deg = swayAngle(f, fps, sway.amp ?? 1.2, sway.hz ?? 0.35, sway.gust, sway.gustAmp ?? 3);
  // a strip at rest would only draw the plate a second time
  if ((sway.amp ?? 1.2) === 0 && Math.abs(deg) < 1e-3) return null;
  const mask = `linear-gradient(180deg, transparent ${top}px, black ${top + fe}px)`;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", WebkitMaskImage: mask, maskImage: mask,
      transform: `skewX(${deg.toFixed(3)}deg)`, transformOrigin: `50% ${fit.y + fit.h}px` }}>
      {img()}
    </div>
  );
}

function Front({ fit, poly, feather, src, filter }: { fit: Fit; poly: Pt[]; feather: number; src: AssetRef | string; filter?: string }) {
  const id = "pf" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const { w, h } = useClip();
  const d = "M" + poly.map((pt) => fit.at(pt).map((v) => v.toFixed(1)).join(" ")).join(" L") + " Z";
  return (
    <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none", filter }}>
      <defs>
        <filter id={id + "f"} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation={feather / 2} /></filter>
        <mask id={id} maskUnits="userSpaceOnUse" x={fit.x} y={fit.y} width={fit.w} height={fit.h}>
          <path d={d} fill="#fff" filter={feather > 0 ? `url(#${id}f)` : undefined} />
        </mask>
      </defs>
      <SvgImage key={assetSrc(src)} href={assetSrc(src)} x={fit.x} y={fit.y} width={fit.w} height={fit.h} preserveAspectRatio="none" mask={`url(#${id})`} />
      <Hold src={src} />
    </svg>
  );
}

export type OccluderProps = {
  src: AssetRef | string;
  imgW?: number; imgH?: number;
  /** the traced polygon in picture px */
  poly: Pt[];
  pad?: number;
  focus?: Pt;
  feather?: number;
  filter?: string;
};

/** A traced part of a plate drawn on its own, for a front you place yourself (same pad and focus as its plate, in
 *  a Layer of the plate's depth). Inside a Plate, `fronts` does this for you. */
export function Occluder({ src, imgW, imgH, poly, pad = 0.06, focus, feather = 3, filter }: OccluderProps) {
  const { w, h } = useClip();
  const [IW, IH] = pictureSize(src, imgW, imgH, "Occluder");
  return <Front fit={coverFit(IW, IH, w, h, pad, focus)} poly={poly} feather={feather} src={src} filter={filter} />;
}
