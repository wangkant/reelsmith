// Photo layers: a generated photograph (with or without alpha) placed on the stage at a depth, lit to sit in the
// plate's light, softened by the lens's depth of field, smeared along its motion, standing on a contact shadow.
import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { continueRender, delayRender, Img } from "remotion";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import { Layer, useDepth } from "./Stage";
import { useLens } from "./lens";
import { dofBlur, travelAt } from "./optics";
import type { TravelOptions } from "./optics";
import type { Pt } from "./geom";

/** A picture's pixel size: from the asset ref, else imgW/imgH, else an error that says what to pass. */
export const pictureSize = (src: AssetRef | string, w?: number, h?: number, who = "Photo"): [number, number] => {
  if (w && h) return [w, h];
  const size = isAsset(src) ? src.size : null;
  if (size && size[0] > 0 && size[1] > 0) return [size[0], size[1]];
  throw new Error(`${who}: the picture's size is unknown; pass imgW and imgH (its pixel size)`);
};

const hex = (c: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6})$/i.exec(c.trim());
  if (!m) return [1, 1, 1];
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};

/** An feColorMatrix that darkens by `shade`, multiplies by `tint` at strength `tintA`, and mixes toward `haze`. */
export const lightMatrix = (shade = 0, tint = "#FFFFFF", tintA = 0, haze = 0, hazeColor = "#DCE6EE"): string => {
  const t = hex(tint), hc = hex(hazeColor), k = 1 - Math.max(0, Math.min(1, shade)), hz = Math.max(0, Math.min(1, haze));
  const rows = [0, 1, 2].map((i) => {
    const g = k * (1 - tintA + tintA * t[i]) * (1 - hz);
    const row = [0, 0, 0, 0, hz * hc[i]];
    row[i] = g;
    return row.map((v) => +v.toFixed(4)).join(" ");
  });
  return [...rows, "0 0 0 1 0"].join("  ");
};

export type PhotoProps = {
  /** the picture: an `*_asset` prop as it reaches the component, or a URL with imgW/imgH */
  src: AssetRef | string;
  imgW?: number; imgH?: number;
  /** where the anchor point stands, in stage px of its layer */
  x: number; y: number;
  /** drawn width in stage px (default the picture's width times `s`) */
  w?: number;
  s?: number;
  /** stretch of the height around the anchor (a flame flaring, a squash on landing) */
  sy?: number;
  /** the point of the picture placed at (x, y), as fractions; [0.5, 1] = standing on its bottom centre */
  anchor?: Pt;
  /** rotation in degrees around the anchor; flip mirrors it left to right */
  r?: number;
  flip?: boolean;
  /** give it its own parallax layer at this depth (leave out inside a Layer or a Plate) */
  depth?: number;
  /** extra blur in px, added to the lens's depth of field */
  blur?: number;
  /** motion blur in px along `smearAng` degrees (0 = along x) */
  smear?: number;
  smearAng?: number;
  /** 0..1 darker (in shade); tint multiplies by a colour at strength tintA (the plate's light); haze mixes toward air */
  shade?: number;
  tint?: string;
  tintA?: number;
  haze?: number;
  hazeColor?: string;
  /** contact shadow strength 0..1 where it stands; its width as a fraction of the drawn width; lift 0..1 off the ground */
  shadow?: number;
  shadowW?: number;
  lift?: number;
  opacity?: number;
};

/** A photograph on the stage. Inside a Layer or Plate it takes their depth for depth of field; with `depth` it
 *  makes its own parallax layer. */
export function Photo(p: PhotoProps) {
  if (p.depth !== undefined) {
    const { depth, ...rest } = p;
    return <Layer depth={depth}><Photo {...rest} /></Layer>;
  }
  return <PhotoBody {...p} />;
}

function PhotoBody({ src, imgW, imgH, x, y, w, s = 1, sy = 1, anchor = [0.5, 1], r = 0, flip = false, blur = 0, smear = 0, smearAng = 0,
  shade = 0, tint = "#FFFFFF", tintA = 0, haze = 0, hazeColor, shadow = 0, shadowW = 0.8, lift = 0, opacity = 1 }: PhotoProps) {
  const id = "ph" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const { w: cw, h: ch } = useClip();
  const depth = useDepth();
  const lens = useLens();
  const [IW, IH] = pictureSize(src, imgW, imgH);
  const dw = w ?? IW * s, dh = ((dw * IH) / IW) * sy;
  const dof = dofBlur(depth, lens.focus, lens.aperture) + blur;
  const sm = Math.max(0, smear);
  const bx = Math.sqrt(dof * dof + sm * sm), by = dof;
  const lit = shade > 0 || tintA > 0 || haze > 0;
  const filtered = bx > 0.3 || lit;
  const rel = smearAng - r;
  const sw = dw * shadowW * (1 + lift * 0.6), so = shadow * 0.6 * (1 - 0.6 * lift);
  return (
    <svg width={cw} height={ch} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none", opacity }}>
      <defs>
        {filtered ? (
          <filter id={id} x="-60%" y="-60%" width="220%" height="220%" colorInterpolationFilters="sRGB">
            {bx > 0.3 ? <feGaussianBlur stdDeviation={`${bx.toFixed(2)} ${by.toFixed(2)}`} /> : null}
            {lit ? <feColorMatrix type="matrix" values={lightMatrix(shade, tint, tintA, haze, hazeColor)} /> : null}
          </filter>
        ) : null}
        {so > 0 ? (
          <radialGradient id={id + "s"}>
            <stop offset="0" stopColor="#000" stopOpacity={so} />
            <stop offset="0.55" stopColor="#000" stopOpacity={so * 0.45} />
            <stop offset="1" stopColor="#000" stopOpacity={0} />
          </radialGradient>
        ) : null}
      </defs>
      {so > 0 ? <ellipse cx={x + sm * 0.2} cy={y + dh * 0.01} rx={sw / 2 + sm} ry={sw * (0.06 + lift * 0.05)} fill={`url(#${id}s)`} /> : null}
      <g transform={`translate(${x} ${y}) rotate(${r})`}>
        <g transform={`rotate(${rel})`} filter={filtered ? `url(#${id})` : undefined}>
          <g transform={`rotate(${-rel})`}>
            <SvgImage key={assetSrc(src)} href={assetSrc(src)} x={-anchor[0] * dw} y={-anchor[1] * dh} width={dw} height={dh} preserveAspectRatio="none"
              transform={flip ? "scale(-1 1)" : undefined} />
          </g>
        </g>
      </g>
      <Hold src={src} />
    </svg>
  );
}

/** An SVG <image> that holds the render until it has loaded: an SVG image decodes on its own, even after an <Img>
 *  of the same picture has. Key it by `href` so a new picture holds again. */
export function SvgImage(props: React.SVGProps<SVGImageElement> & { href: string }) {
  const [handle] = useState(() => delayRender(`Loading picture ${props.href.slice(0, 80)}`));
  const open = useRef(true);
  const done = useCallback(() => {
    if (open.current) { open.current = false; continueRender(handle); }
  }, [handle]);
  useEffect(() => done, [done]);
  return <image {...props} onLoad={done} onError={done} />;
}

/** The render waits for an <Img> to load, not for an SVG image: a hidden Img holds the frame until it has. */
export const Hold = ({ src }: { src: AssetRef | string }) => (
  <foreignObject width={1} height={1} opacity={0}><Img src={assetSrc(src)} style={{ width: 1, height: 1 }} /></foreignObject>
);

export type TravelProps = Omit<PhotoProps, "x" | "y" | "smear" | "smearAng" | "shade"> & TravelOptions & {
  /** the traced path in stage px (usePlate().at maps picture px), start to end */
  line: Pt[];
  /** frame it sets off and frames it takes */
  at: number;
  dur: number;
  /** motion blur in px per px of travel per frame (0 = none), capped at maxSmear */
  smearK?: number;
  maxSmear?: number;
  /** 0..1 shade at a point of the line (shadeRamp gives one) */
  shadeAt?: (x: number, y: number) => number;
  /** rotate with the line's direction */
  turn?: boolean;
  f: number;
};

/** A photo moving along a traced line: perspective scale (`sizes`), a smear that grows with speed, a shadow that
 *  follows and shading by where it is. */
export function Travel({ line, at, dur, sizes, ease, smearK = 0.7, maxSmear = 60, shadeAt, turn = false, f, w, s = 1, r = 0, ...rest }: TravelProps) {
  const st = travelAt(line, f, at, dur, { sizes, ease });
  const [IW] = pictureSize(rest.src, rest.imgW, rest.imgH, "Travel");
  const base = w ?? IW * s;
  return (
    <Photo {...rest} x={st.x} y={st.y} w={base * st.s} r={r + (turn ? st.ang : 0)}
      smear={Math.min(maxSmear, st.speed * smearK)} smearAng={st.ang} shade={shadeAt ? shadeAt(st.x, st.y) : 0} />
  );
}
