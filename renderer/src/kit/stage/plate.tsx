// The backdrop plate: one full-frame generated photograph as the far layer, with slow life (drift, a swaying near
// strip), and occluders: the same plate clipped to a traced polygon and drawn again in front, so things pass behind.
import React, { createContext, useContext, useId } from "react";
import { Img, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { assetSrc } from "../helpers";
import type { AssetRef } from "../helpers";
import { Layer, useDepth } from "./Stage";
import { LensContext, useLens } from "./lens";
import { coverFit, dofBlur, filmFrame, punchAt, punchView, showsFilm, swayAngle } from "./optics";
import type { Fit, Light, Punch } from "./optics";
import { checkSameAspect, Hold, LightProvider, pictureSize, PictureContext, SvgImage, ViewProvider, wipeBand } from "./photo";
import { FilmFrame, filmDuration, isFilm } from "./footage";
import type { Film } from "./footage";
import type { Wipe } from "./photo";
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
  /** the same place from the same camera in another state (lights on, rain, night), over the first by progress `p`
   *  0..1: a dissolve, or a `wipe` with a `soft` edge; `wipeAt` (picture fractions) is where an "out" wipe starts */
  to?: AssetRef | string;
  p?: number;
  wipe?: Wipe;
  soft?: number;
  wipeAt?: Pt;
  /** the plate moving: a clip made from `src` (same aspect), played over it from `film.at` (a frame on the plate's
   *  clock: `f` if given); before that the still shows (clip frame `from` when from > 0), after it the last frame
   *  holds (with hold false or "before", the still returns). A video `src` plays from frame 0, and wherever it is
   *  not running its first frame stands in for the still */
  film?: Film;
  /** where the light comes from: the photos inside cast their shadows away from it */
  light?: Light;
  /** second camera angles on the same plate: from each cue's frame it cuts to a closer framing of a picture point */
  punch?: Punch | Punch[];
  /** what stands in the plate (stage px; usePlate().at maps traced points), drawn between the plate and its fronts */
  children?: React.ReactNode;
};

/** A full-frame photograph as the far layer: children stand in it, its traced fronts hide them. */
export function Plate({ depth = 0.9, ...p }: PlateProps) {
  return <Layer depth={depth}><PlateBody {...p} /></Layer>;
}

function PlateBody({ src, imgW, imgH, pad = 0.06, focus, drift = 0, sway, fronts = [], feather = 3, blur = 0, photo, f: fIn, to, p = 0, wipe,
  soft = 0.3, wipeAt = [0.5, 0.5], film: filmIn, light, punch, children }: PlateProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h, fps } = useClip();
  const depth = useDepth();
  const outer = useLens();
  const [IW, IH] = pictureSize(src, imgW, imgH, "Plate");
  if (to) checkSameAspect(to, IW, IH, "Plate");
  const fit = coverFit(IW, IH, w, h, pad, focus);
  const shot = punchAt(punch === undefined ? undefined : Array.isArray(punch) ? punch : [punch], f);
  const view = shot ? punchView(shot, fit, w, h) : null;
  const lens = shot && (shot.focus !== undefined || shot.aperture !== undefined)
    ? { focus: shot.focus ?? outer.focus, aperture: shot.aperture ?? outer.aperture } : outer;
  const b = dofBlur(depth, lens.focus, lens.aperture) + blur;
  const film: Film | undefined = filmIn ?? (isFilm(src) ? { src, at: 0 } : undefined);
  if (filmIn && isFilm(filmIn.src)) checkSameAspect(filmIn.src, IW, IH, "Plate film");
  const ff = film ? filmFrame(film, f, fps || 30, filmDuration(film.src)) : null;
  // a video src has no still: its first frame stands in, so an <Img> never gets a clip
  const moving = !!film && !!ff && ff.frame !== null && (film.src === src || showsFilm(film, ff));
  const filter = [b > 0.3 ? `blur(${b.toFixed(2)}px)` : "", photo ?? ""].join(" ").trim() || undefined;
  const sec = f / (fps || 30);
  const life = drift ? `translate(${(Math.sin(sec * 0.37) * drift).toFixed(2)}px, ${(Math.cos(sec * 0.29) * drift * 0.6).toFixed(2)}px) scale(${(1 + (drift / w) * (1 + Math.sin(sec * 0.21))).toFixed(5)})` : undefined;
  const k = to ? Math.max(0, Math.min(1, p)) : 0;
  const mask = to && k > 0 && k < 1 && wipe ? wipeCss(fit, k, wipe, soft, wipeAt) : undefined;
  const veil: React.CSSProperties = mask ? { WebkitMaskImage: mask, maskImage: mask } : k < 1 ? { opacity: k } : {};
  const one = (pic: AssetRef | string, style?: React.CSSProperties) => (
    <Img src={assetSrc(pic)} style={{ position: "absolute", left: fit.x, top: fit.y, width: fit.w, height: fit.h, maxWidth: "none", filter, ...style }} />
  );
  const framed = (clip: AssetRef | string, frame: number, clipMask?: string) => (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, filter,
      ...(clipMask ? { WebkitMaskImage: clipMask, maskImage: clipMask, WebkitMaskSize: `${w}px ${h}px`, maskSize: `${w}px ${h}px`,
        WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat" } : {}) }}>
      <div style={{ position: "absolute", left: fit.x, top: fit.y, width: fit.w, height: fit.h }}>
        <FilmFrame src={clip} frame={frame} />
      </div>
    </div>
  );
  const moved = (clipMask?: string) => framed((film as Film).src, ff?.frame ?? 0, clipMask);
  const still = (pic: AssetRef | string) => (isFilm(pic) ? framed(pic, 0) : one(pic));
  const img = () => (
    <>
      {k >= 1 ? null : moving ? moved() : still(src)}
      {to && k > 0 ? <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, ...veil }}>{still(to)}</div> : null}
    </>
  );
  const frontStill = (pic: AssetRef | string, poly: Pt[], i: number) => isFilm(pic)
    ? <React.Fragment key={i}>{framed(pic, 0, frontMask(fit, poly, feather, w, h))}</React.Fragment>
    : <Front key={i} fit={fit} poly={poly} feather={feather} src={pic} filter={filter} />;
  const frontOf = (poly: Pt[], i: number) => moving
    ? <React.Fragment key={i}>{moved(frontMask(fit, poly, feather, w, h))}</React.Fragment>
    : frontStill(src, poly, i);
  const plate = (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transform: life, transformOrigin: "50% 50%" }}>
      {img()}
      {sway ? <SwayStrip fit={fit} sway={sway} f={f} fps={fps || 30} img={img} /> : null}
      <PlateContext.Provider value={fit}>
        <PictureContext.Provider value={{ at: fit.at, s: fit.s, r: 0, blur: b > 0.3 ? b : 0 }}>{children}</PictureContext.Provider>
      </PlateContext.Provider>
      {k >= 1 ? null : fronts.map(frontOf)}
      {to && k > 0 && fronts.length ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, ...veil }}>
          {fronts.map((poly, i) => frontStill(to, poly, i))}
        </div>
      ) : null}
    </div>
  );
  return (
    <LensContext.Provider value={lens}>
      <LightProvider value={light ?? null}>
        <ViewProvider value={view}>
          {view ? (
            <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0",
              transform: `translate(${w / 2}px, ${h / 2}px) scale(${view.z}) translate(${-view.cx}px, ${-view.cy}px)` }}>{plate}</div>
          ) : plate}
        </ViewProvider>
      </LightProvider>
    </LensContext.Provider>
  );
}

/** A front's feathered polygon as a CSS mask image, for fronts cut from a moving plate. */
const frontMask = (fit: Fit, poly: Pt[], feather: number, w: number, h: number): string => {
  const d = "M" + poly.map((pt) => fit.at(pt).map((v) => v.toFixed(1)).join(" ")).join(" L") + " Z";
  const blur = feather > 0 ? `<filter id='b' x='-20%' y='-20%' width='140%' height='140%'><feGaussianBlur stdDeviation='${feather / 2}'/></filter>` : "";
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${w}' height='${h}'>${blur}<path d='${d}' fill='white'${feather > 0 ? " filter='url(#b)'" : ""}/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
};

/** The CSS mask for a plate's wipe, in stage px of the plate's layer. */
const wipeCss = (fit: Fit, p: number, wipe: Wipe, soft: number, at: Pt): string => {
  const [e0, e1] = wipeBand(p, soft);
  if (wipe === "out") {
    const cx = fit.x + at[0] * fit.w, cy = fit.y + at[1] * fit.h;
    const R = Math.max(...[[fit.x, fit.y], [fit.x + fit.w, fit.y], [fit.x, fit.y + fit.h], [fit.x + fit.w, fit.y + fit.h]].map(([a, b]) => Math.hypot(a - cx, b - cy)));
    return `radial-gradient(circle ${R.toFixed(1)}px at ${cx.toFixed(1)}px ${cy.toFixed(1)}px, black ${(e0 * R).toFixed(1)}px, transparent ${(e1 * R).toFixed(1)}px)`;
  }
  const horiz = wipe === "left" || wipe === "right";
  const a = horiz ? fit.x : fit.y, len = horiz ? fit.w : fit.h;
  const rev = wipe === "left" || wipe === "up";
  const pos = (e: number) => (rev ? a + len * (1 - e) : a + len * e).toFixed(1);
  const dir = horiz ? "to right" : "to bottom";
  return rev
    ? `linear-gradient(${dir}, transparent ${pos(e1)}px, black ${pos(e0)}px)`
    : `linear-gradient(${dir}, black ${pos(e0)}px, transparent ${pos(e1)}px)`;
};

function SwayStrip({ fit, sway, f, fps, img }: { fit: Fit; sway: Sway; f: number; fps: number; img: () => React.ReactNode }) {
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
