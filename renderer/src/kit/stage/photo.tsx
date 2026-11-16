// Photo layers: a generated photograph (with or without alpha) placed on the stage at a depth, lit to sit in the
// plate's light, softened by the lens's depth of field, smeared along its motion, standing on a contact shadow.
import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { continueRender, delayRender, Img, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import { Layer, useDepth } from "./Stage";
import { useLens } from "./lens";
import { castMatrix, dofBlur, silhouette, travelAt } from "./optics";
import type { Light, TravelOptions, View } from "./optics";
import type { Pt } from "./geom";

const LightContext = createContext<Light | null>(null);
/** Provides the light that casts the shadows of the photos inside (Plate's `light` does this). */
export const LightProvider = LightContext.Provider;
/** The light the enclosing Plate gives, or null. */
export const useLight = (): Light | null => useContext(LightContext);

const ViewContext = createContext<View | null>(null);
// a Plate's punch, so footage inside can tell whether it is on screen
export const ViewProvider = ViewContext.Provider;
export const useView = (): View | null => useContext(ViewContext);

/** Where a point of the enclosing picture lands: `at([px, py])` maps picture px to stage px, `s` is stage px per
 *  picture px and `r` the picture's rotation in degrees; `blur` (depth of field) and `smear` along `smearAng`
 *  (stage degrees) are the picture's softness in stage px. Photo and Plate provide it to their children. */
export type Picture = { at: (pt: Pt) => Pt; s: number; r: number; blur?: number; smear?: number; smearAng?: number };
export const PictureContext = createContext<Picture | null>(null);

/** The enclosing Photo's or Plate's mapping from picture px to stage px. */
export const usePicture = (): Picture => {
  const pic = useContext(PictureContext);
  if (!pic) throw new Error("usePicture: call it inside a <Photo> or a <Plate>, or pass `at`");
  return pic;
};

/** The direction a change sweeps across a picture: "right" starts at its left edge and moves right, "up" starts at
 *  its bottom, "out" grows from `wipeAt`. */
export type Wipe = "left" | "right" | "up" | "down" | "out";

/** The band [e0, e1] (fractions of the sweep) where a wipe at progress p fades from the new state to the old. */
export const wipeBand = (p: number, soft = 0.3): [number, number] => {
  const k = Math.max(0, Math.min(1, p)), sf = Math.max(0.001, soft);
  const e1 = k * (1 + sf);
  return [e1 - sf, e1];
};

/** A picture's pixel size: from the asset ref, else imgW/imgH, else an error that says what to pass. */
export const pictureSize = (src: AssetRef | string, w?: number, h?: number, who = "Photo"): [number, number] => {
  if (w && h) return [w, h];
  const size = isAsset(src) ? src.size : null;
  if (size && size[0] > 0 && size[1] > 0) return [size[0], size[1]];
  throw new Error(`${who}: the picture's size is unknown; pass imgW and imgH (its pixel size)`);
};

/** Throws when a state-change picture `to` would be stretched: its aspect must match the first picture's within 1%. */
export const checkSameAspect = (to: AssetRef | string, IW: number, IH: number, who: string) => {
  const size = isAsset(to) ? to.size : null;
  if (!size || !(size[0] > 0 && size[1] > 0)) return;
  if (Math.abs((size[0] / size[1]) / (IW / IH) - 1) > 0.01) {
    throw new Error(`${who}: the \`to\` picture is ${size[0]}x${size[1]} but the first is ${IW}x${IH}; `
      + "draw both at the same aspect so the change lines up");
  }
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
  /** ground shadow 0..1, made from the picture's own alpha: a soft contact patch under its lowest pixels and, when a
   *  light is known (the Plate's `light` or this `light`), a cast shadow away from it that fades with distance */
  shadow?: number;
  /** the cast shadow's strength (default 0.6 of `shadow`); the contact patch's width factor */
  cast?: number;
  shadowW?: number;
  light?: Light;
  /** stage y of the ground under it (default its lowest opaque pixel), or `lift`: its height off the ground as a
   *  fraction of its drawn height (the shadow drops by that much, spreads and fades) */
  ground?: number;
  lift?: number;
  opacity?: number;
  /** a second picture of the same thing from the same angle and size (raw then cooked, off then on), shown over
   *  the first by progress `p` 0..1: a dissolve, or a `wipe` with a `soft` edge (a fraction of the sweep) */
  to?: AssetRef | string;
  p?: number;
  wipe?: Wipe;
  soft?: number;
  /** where an "out" wipe starts, as fractions of the picture */
  wipeAt?: Pt;
  /** things fixed to the picture (a Surface on its label): they follow it as it moves, scales and turns */
  children?: React.ReactNode;
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
  shade = 0, tint = "#FFFFFF", tintA = 0, haze = 0, hazeColor, shadow = 0, cast, shadowW = 1, light: lightIn, ground, lift = 0, opacity = 1,
  to, p = 0, wipe, soft = 0.3, wipeAt = [0.5, 0.5], children }: PhotoProps) {
  const id = "ph" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const { w: cw, h: ch } = useClip();
  const depth = useDepth();
  const lens = useLens();
  const plateLight = useLight();
  const light = lightIn ?? plateLight;
  const [IW, IH] = pictureSize(src, imgW, imgH);
  if (to) checkSameAspect(to, IW, IH, "Photo");
  const dw = w ?? IW * s, dh = ((dw * IH) / IW) * sy;
  const dof = dofBlur(depth, lens.focus, lens.aperture) + blur;
  const sm = Math.max(0, smear);
  const bx = Math.sqrt(dof * dof + sm * sm), by = dof;
  const lit = shade > 0 || tintA > 0 || haze > 0;
  const filtered = bx > 0.3 || lit;
  const rel = smearAng - r;
  const k = to ? Math.max(0, Math.min(1, p)) : 0;
  const onlyTo = k >= 1;
  const ox = -anchor[0] * dw, oy = -anchor[1] * dh;
  const img = (href: string, extra?: React.SVGProps<SVGImageElement>) => (
    <SvgImage key={href} href={href} x={ox} y={oy} width={dw} height={dh} preserveAspectRatio="none" {...extra} />
  );
  // during a change both silhouettes' shadows cross-fade with the pictures, so nothing pops at p = 1
  const shadowOf = (pic: AssetRef | string, key: string) => (
    <GroundShadow key={assetSrc(pic)} id={id + key} href={assetSrc(pic)} x={x} y={y} ox={ox} oy={oy} dw={dw} dh={dh} r={r} flip={flip}
      strength={shadow} cast={cast ?? shadow * 0.6} spread={shadowW} light={light} ground={ground} lift={lift} soft={dof} smear={sm} />
  );
  const pic = (
    <g transform={flip ? "scale(-1 1)" : undefined}>
      {onlyTo ? null : img(assetSrc(src))}
      {to && k > 0 ? img(assetSrc(to), onlyTo ? undefined : wipe ? { mask: `url(#${id}w)` } : { opacity: k }) : null}
    </g>
  );
  const svg = (
    <svg width={cw} height={ch} style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none", opacity }}>
      <defs>
        {filtered ? (
          <filter id={id} x="-60%" y="-60%" width="220%" height="220%" colorInterpolationFilters="sRGB">
            {bx > 0.3 ? <feGaussianBlur stdDeviation={`${bx.toFixed(2)} ${by.toFixed(2)}`} /> : null}
            {lit ? <feColorMatrix type="matrix" values={lightMatrix(shade, tint, tintA, haze, hazeColor)} /> : null}
          </filter>
        ) : null}
        {to && k > 0 && !onlyTo && wipe ? <WipeMask id={id + "w"} x={ox} y={oy} w={dw} h={dh} p={k} soft={soft} at={wipeAt}
          wipe={flip && wipe === "left" ? "right" : flip && wipe === "right" ? "left" : wipe} /> : null}
      </defs>
      {shadow > 0 && !onlyTo ? <g opacity={to && k > 0 ? 1 - k : undefined}>{shadowOf(src, "s")}</g> : null}
      {shadow > 0 && to && k > 0 ? <g opacity={onlyTo ? undefined : k}>{shadowOf(to, "t")}</g> : null}
      <g transform={`translate(${x} ${y}) rotate(${r})`}>
        <g transform={`rotate(${rel})`} filter={filtered ? `url(#${id})` : undefined}>
          <g transform={`rotate(${-rel})`}>{pic}</g>
        </g>
      </g>
      <Hold src={src} />
      {to && k > 0 ? <Hold src={to} /> : null}
    </svg>
  );
  if (children === undefined || children === null) return svg;
  const rad = (r * Math.PI) / 180, c = Math.cos(rad), sn = Math.sin(rad), sc = dw / IW, scy = dh / IH;
  const at = ([px, py]: Pt): Pt => {
    const lx = (flip ? -1 : 1) * (ox + px * sc), ly = oy + py * scy;
    return [x + lx * c - ly * sn, y + lx * sn + ly * c];
  };
  return (
    <>
      {svg}
      <PictureContext.Provider value={{ at, s: sc, r, blur: dof, smear: sm, smearAng }}>
        <div style={{ position: "absolute", left: 0, top: 0, width: cw, height: ch, opacity, pointerEvents: "none" }}>{children}</div>
      </PictureContext.Provider>
    </>
  );
}

type ShadowProps = {
  id: string; href: string; x: number; y: number; ox: number; oy: number; dw: number; dh: number; r: number; flip: boolean;
  strength: number; cast: number; spread: number; light: Light | null; ground?: number; lift: number; soft: number; smear: number;
};

const BOX: Pt[] = [[0, 0], [1, 0], [0, 1], [1, 1]];
const OPAQUE = new Map<string, Pt[]>();
const MEASURING = new Map<string, Promise<void>>();

/** The corners of each row's opaque run, as picture fractions on a coarse grid: every convex-hull point of the
 *  silhouette is among them, so its lowest point is found under any rotation. The box when it cannot be read. */
const measureOpaque = (href: string): Promise<void> => {
  let job = MEASURING.get(href);
  if (!job) {
    job = new Promise<void>((done) => {
      const im = new Image();
      im.crossOrigin = "anonymous";
      im.onload = () => {
        try {
          const N = 96, iw = im.naturalWidth || 1, ih = im.naturalHeight || 1;
          const cw = Math.max(1, Math.round(iw >= ih ? N : (N * iw) / ih)), chh = Math.max(1, Math.round(ih >= iw ? N : (N * ih) / iw));
          const cv = document.createElement("canvas");
          cv.width = cw; cv.height = chh;
          const g = cv.getContext("2d", { willReadFrequently: true });
          if (!g) throw new Error("no 2d context");
          g.drawImage(im, 0, 0, cw, chh);
          const a = g.getImageData(0, 0, cw, chh).data, pts: Pt[] = [];
          for (let j = 0; j < chh; j++) {
            let lo = -1, hi = -1;
            for (let i = 0; i < cw; i++) if (a[(j * cw + i) * 4 + 3] > 26) { if (lo < 0) lo = i; hi = i; }
            if (lo >= 0) pts.push([lo / cw, j / chh], [lo / cw, (j + 1) / chh], [(hi + 1) / cw, j / chh], [(hi + 1) / cw, (j + 1) / chh]);
          }
          OPAQUE.set(href, pts.length ? pts : BOX);
        } catch {
          OPAQUE.set(href, BOX);
        }
        done();
      };
      im.onerror = () => { OPAQUE.set(href, BOX); done(); };
      im.src = href;
    });
    MEASURING.set(href, job);
  }
  return job;
};

/** A picture's opaque outline points (measured once per picture, the render held until then). */
function useOpaque(href: string): Pt[] {
  const [, bump] = useState(0);
  const [handle] = useState(() => (OPAQUE.has(href) ? null : delayRender(`Measuring ${href.slice(0, 80)}`)));
  useEffect(() => {
    if (handle === null) return;
    measureOpaque(href).then(() => { bump((n) => n + 1); continueRender(handle); });
  }, [href, handle]);
  return OPAQUE.get(href) ?? BOX;
}

/** A photo's ground shadow from its own alpha, built in stage space so rotation, flip and squash are all honoured:
 *  the silhouette's lowest band squashed flat under its real lowest pixels (contact), and the whole silhouette laid
 *  on the ground away from the light (cast), sharper near the foot and fading out. */
function GroundShadow({ id, href, x, y, ox, oy, dw, dh, r, flip, strength, cast, spread, light, ground, lift, soft, smear }: ShadowProps) {
  const opaque = useOpaque(href);
  const { foot, top, left, w: W, cx } = silhouette(opaque, x, y, ox, oy, dw, dh, r, flip);
  const H = Math.max(1, foot - top);
  const G = ground ?? foot + Math.max(0, lift) * dh;
  const gap = Math.max(0, G - foot);
  const fade = Math.exp(-gap / Math.max(1, 0.35 * H));
  // the patch is about a tenth of the width deep, made from the bottom quarter of the silhouette; alpha gains
  // above 1 make the masked silhouette solid where it is dense
  const t = 0.1 * W * (1 + gap / H);
  const kq = Math.max(0.04, Math.min(0.6, t / (0.28 * H)));
  const sx = spread * (1 + 0.5 * gap / H);
  const patch = `matrix(${sx} 0 0 ${kq} ${cx * (1 - sx)} ${G - foot * kq + t * 0.45})`;
  // a thin dark core where it touches: the ground it hides from the sky
  const kc = kq * 0.35;
  const core = `matrix(${sx * 0.96} 0 0 ${kc} ${cx * (1 - sx * 0.96)} ${G - foot * kc + t * 0.08})`;
  const x0 = left - W, bw = 3 * W;
  const body = (mask: string) => (
    <g mask={`url(#${mask})`}>
      <g transform={`translate(${x} ${y}) rotate(${r})`}>
        <g transform={flip ? "scale(-1 1)" : undefined}>
          <SvgImage href={href} x={ox} y={oy} width={dw} height={dh} preserveAspectRatio="none" />
        </g>
      </g>
    </g>
  );
  // a band of the silhouette in stage space, measured up from its foot: offset 0 = foot, 1 = its top
  const band = (key: string, stops: [number, number][]) => (
    <>
      <linearGradient id={id + key + "g"} gradientUnits="userSpaceOnUse" x1={0} y1={foot} x2={0} y2={top}>
        {stops.map(([o, a], i) => <stop key={i} offset={o} stopColor="#fff" stopOpacity={a} />)}
      </linearGradient>
      <mask id={id + key + "m"} maskUnits="userSpaceOnUse" x={x0} y={top - 2} width={bw} height={H + 4}>
        <rect x={x0} y={top - 2} width={bw} height={H + 4} fill={`url(#${id + key}g)`} />
      </mask>
    </>
  );
  const ink = (a: number) => `0 0 0 0 0.05  0 0 0 0 0.035  0 0 0 0 0.02  0 0 0 ${a.toFixed(3)} 0`;
  const blurOf = (b: number) => `${(b + smear).toFixed(2)} ${b.toFixed(2)}`;
  const cm = light && cast > 0 ? castMatrix(light, G) : null;
  const castA = Math.min(1, cast) * (0.75 + 0.25 * fade);
  const reach = cm ? cm.len * H : 0;
  return (
    <>
      <defs>
        {band("p", [[0, 1], [0.28, 0]])}
        <filter id={id + "p"} x="-50%" y="-200%" width="200%" height="500%" colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={ink(Math.min(1, strength) * 2.2 * fade)} />
          <feGaussianBlur stdDeviation={blurOf(t * 0.3 + soft)} />
        </filter>
        <filter id={id + "c"} x="-50%" y="-200%" width="200%" height="500%" colorInterpolationFilters="sRGB">
          <feColorMatrix type="matrix" values={ink(Math.min(1, strength) * 3)} />
          <feGaussianBlur stdDeviation={blurOf(t * 0.06 + soft + 0.6)} />
        </filter>
        {cm ? (
          <>
            {band("n", [[0, 1], [0.45, 0]])}
            {band("f", [[0, 0.55], [1, 0]])}
            <filter id={id + "n"} x="-50%" y="-50%" width="200%" height="200%" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values={ink(castA * 1.4)} />
              <feGaussianBlur stdDeviation={blurOf(1 + 0.012 * reach + soft + gap * 0.05)} />
            </filter>
            <filter id={id + "f"} x="-50%" y="-50%" width="200%" height="200%" colorInterpolationFilters="sRGB">
              <feColorMatrix type="matrix" values={ink(castA * 0.9)} />
              <feGaussianBlur stdDeviation={blurOf(2 + 0.05 * reach + soft + gap * 0.1)} />
            </filter>
          </>
        ) : null}
      </defs>
      {cm ? (
        <>
          <g filter={`url(#${id}f)`}><g transform={`matrix(${cm.m.map((v) => +v.toFixed(5)).join(" ")})`}>{body(id + "fm")}</g></g>
          <g filter={`url(#${id}n)`}><g transform={`matrix(${cm.m.map((v) => +v.toFixed(5)).join(" ")})`}>{body(id + "nm")}</g></g>
        </>
      ) : null}
      <g filter={`url(#${id}p)`}><g transform={patch}>{body(id + "pm")}</g></g>
      {gap < 0.05 * H ? <g filter={`url(#${id}c)`}><g transform={core}>{body(id + "pm")}</g></g> : null}
    </>
  );
}

/** An SVG mask that shows the new picture where a wipe has passed, with a soft edge, in the picture's own box. */
function WipeMask({ id, x, y, w, h, p, wipe, soft, at }: { id: string; x: number; y: number; w: number; h: number; p: number; wipe: Wipe; soft: number; at: Pt }) {
  const [e0, e1] = wipeBand(p, soft);
  const sf = e1 - e0;
  // the gradient spans the whole sweep, soft band included, so the edge keeps its width at both ends (as Plate's)
  const lo = wipe === "out" ? 0 : -sf, hi = 1 + sf;
  const op = (e: number) => Math.max(0, Math.min(1, (e1 - e) / sf));
  const off = (e: number) => (Math.max(lo, Math.min(hi, e)) - lo) / (hi - lo);
  const stops = (
    <>
      <stop offset={off(e0)} stopColor="#fff" stopOpacity={op(Math.max(lo, e0))} />
      <stop offset={off(e1)} stopColor="#fff" stopOpacity={op(Math.min(hi, e1))} />
    </>
  );
  const cx = x + at[0] * w, cy = y + at[1] * h;
  const R = Math.max(...[[x, y], [x + w, y], [x, y + h], [x + w, y + h]].map(([a, b]) => Math.hypot(a - cx, b - cy)));
  const ext = (a: number, len: number, rev: boolean) => (rev ? [a + len * (1 - lo), a + len * (1 - hi)] : [a + len * lo, a + len * hi]);
  const [hx1, hx2] = ext(x, w, wipe === "left"), [vy1, vy2] = ext(y, h, wipe === "up");
  const line = wipe === "left" || wipe === "right" ? [hx1, 0, hx2, 0] : [0, vy1, 0, vy2];
  return (
    <>
      {wipe === "out" ? (
        <radialGradient id={id + "g"} gradientUnits="userSpaceOnUse" cx={cx} cy={cy} r={R * hi}>{stops}</radialGradient>
      ) : (
        <linearGradient id={id + "g"} gradientUnits="userSpaceOnUse" x1={line[0]} y1={line[1]} x2={line[2]} y2={line[3]}>{stops}</linearGradient>
      )}
      <mask id={id} maskUnits="userSpaceOnUse" x={x} y={y} width={w} height={h}>
        <rect x={x} y={y} width={w} height={h} fill={`url(#${id}g)`} />
      </mask>
    </>
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
  /** stage y of the ground under a point (a hop or a throw keeps its shadow on the floor) */
  groundAt?: (x: number, y: number) => number;
  f?: number;
};

/** A photo moving along a traced line: perspective scale (`sizes`), a smear that grows with speed, a shadow that
 *  follows and shading by where it is. */
export function Travel({ line, at, dur, sizes, ease, smearK = 0.7, maxSmear = 60, shadeAt, turn = false, groundAt, f: fIn, w, s = 1, r = 0, ...rest }: TravelProps) {
  const now = useCurrentFrame();
  const st = travelAt(line, fIn ?? now, at, dur, { sizes, ease });
  const [IW] = pictureSize(rest.src, rest.imgW, rest.imgH, "Travel");
  const base = w ?? IW * s;
  return (
    <Photo {...rest} x={st.x} y={st.y} w={base * st.s} r={r + (turn ? st.ang : 0)}
      smear={Math.min(maxSmear, st.speed * smearK)} smearAng={st.ang} shade={shadeAt ? shadeAt(st.x, st.y) : 0}
      ground={groundAt ? groundAt(st.x, st.y) : rest.ground} />
  );
}
