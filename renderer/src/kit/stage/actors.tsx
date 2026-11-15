// Actors: torn photo cut-outs, a loupe chip and a magnifying glass, and the enter / idle / exit wrapper.
import React from "react";
import { Img, useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { assetSrc, isAsset } from "../helpers";
import type { AssetRef } from "../helpers";
import { backOut, boil, clamp01, in2, lerp, prog, step } from "./time";
import { bbox, circle, torn } from "./geom";
import type { Pt } from "./geom";
import { shadowCss, useFilters, usePalette, useUnit } from "./palette";

/** Where a cut-out sits: its outline in source pixels, its centre on the canvas, scale and rotation (deg). */
export type Placed = { poly: Pt[]; x: number; y: number; s?: number; r?: number };

export type CutProps = Placed & {
  /** the picture: an asset ref (an `*_asset` prop as it reaches the component) or a URL */
  src: AssetRef | string;
  /** the picture's pixel size; read from the asset ref when it carries one, else required */
  imgW?: number; imgH?: number;
  seed: string;
  /** 0 lying flat .. 1 held above the page */
  lift?: number;
  opacity?: number;
  /** paper border in canvas px */
  keyline?: number;
  /** tear roughness in source px */
  amp?: number;
  tint?: { color: string; a: number; blend?: React.CSSProperties["mixBlendMode"] };
  /** CSS filter on the photo only */
  photo?: string;
  /** drawn on the piece in source pixels, clipped to it */
  over?: React.ReactNode;
  /** drawn on the piece in source pixels, not clipped */
  free?: React.ReactNode;
  z?: number;
  /** keyline colour (default palette paper) */
  edge?: string;
};

/** Where a source-pixel point of a placed piece lands on the canvas (for pens, loupes and arrows that follow a detail). */
export const toCanvas = (p: Placed, pt: Pt): Pt => {
  const b = bbox(p.poly);
  const s = p.s ?? 1, a = ((p.r ?? 0) * Math.PI) / 180;
  const dx = (pt[0] - (b.x + b.w / 2)) * s, dy = (pt[1] - (b.y + b.h / 2)) * s;
  return [p.x + dx * Math.cos(a) - dy * Math.sin(a), p.y + dx * Math.sin(a) + dy * Math.cos(a)];
};

const imageSize = (src: AssetRef | string, w?: number, h?: number): [number, number] => {
  if (w && h) return [w, h];
  const size = isAsset(src) ? src.size : null;
  if (size && size[0] > 0 && size[1] > 0) return [size[0], size[1]];
  throw new Error("Cut: the picture's size is unknown; pass imgW and imgH (its pixel size)");
};

/** A piece cut out of a picture along `poly`: torn edge, paper keyline, a shadow that grows with lift. */
export function Cut(p: CutProps) {
  const pal = usePalette();
  const [IW, IH] = imageSize(p.src, p.imgW, p.imgH);
  const url = assetSrc(p.src);
  const s = p.s ?? 1;
  const b = bbox(p.poly);
  const kl = (p.keyline ?? 9) / s;
  const d = torn(p.poly, p.seed, p.amp ?? 7);
  const lift = p.lift ?? 0;
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  const edge = p.edge ?? pal.paper;
  return (
    <div style={{
      position: "absolute", left: p.x, top: p.y, width: 0, height: 0, zIndex: p.z,
      transform: `rotate(${p.r ?? 0}deg) scale(${s * (1 + 0.04 * lift)})`, transformOrigin: "0 0",
      filter: shadowCss(lift, pal.shadow), opacity: p.opacity ?? 1,
    }}>
      <div style={{ position: "absolute", left: -cx, top: -cy, width: IW, height: IH }}>
        <svg width={IW} height={IH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <path d={d} fill={edge} stroke={edge} strokeWidth={kl * 2} strokeLinejoin="round" />
        </svg>
        <div style={{ position: "absolute", left: 0, top: 0, width: IW, height: IH, clipPath: `path('${d}')` }}>
          <Img src={url} style={{ position: "absolute", left: 0, top: 0, width: IW, height: IH, filter: p.photo }} />
          {p.tint ? <div style={{ position: "absolute", inset: 0, background: p.tint.color, opacity: p.tint.a, mixBlendMode: p.tint.blend ?? "multiply" }} /> : null}
          {p.over ? <svg width={IW} height={IH} style={{ position: "absolute", left: 0, top: 0 }}>{p.over}</svg> : null}
        </div>
        {p.free ? <svg width={IW} height={IH} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>{p.free}</svg> : null}
      </div>
    </div>
  );
}

export type LoupeProps = {
  src: AssetRef | string; imgW?: number; imgH?: number;
  /** the detail, in source pixels */
  at: Pt;
  /** the loupe's centre on the canvas and its radius */
  x: number; y: number; r?: number;
  /** canvas px per source px inside the loupe */
  zoom?: number;
  /** when given, a leader line runs from the detail on this placed piece to the loupe */
  piece?: Placed;
  /** 0..1 appearance (pops in, leader draws on) */
  p?: number;
  seed?: string;
  ring?: string;
};

/** A round chip of the same picture, enlarged around a detail, with a leader line from where the detail is. */
export function Loupe({ src, imgW, imgH, at, x, y, r, zoom = 1.9, piece, p = 1, seed = "loupe", ring }: LoupeProps) {
  const pal = usePalette();
  const u = useUnit();
  if (p <= 0) return null;
  const k = backOut(clamp01(p * 1.6), 1.6);
  const R = r ?? 110 * u;
  const poly = circle(at[0], at[1], R / zoom, 40);
  const from = piece ? toCanvas(piece, at) : null;
  const lead = clamp01((p - 0.2) / 0.5);
  const ux = from ? x - from[0] : 0, uy = from ? y - from[1] : 0, ul = Math.hypot(ux, uy) || 1;
  const end: Pt | null = from ? [x - (ux / ul) * R, y - (uy / ul) * R] : null;
  return (
    <>
      {from && end && lead > 0 ? (
        <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <circle cx={from[0]} cy={from[1]} r={7 * u} fill="none" stroke={ring ?? pal.ink} strokeWidth={3 * u} opacity={lead} />
          <path d={`M${from[0]} ${from[1]} L${end[0]} ${end[1]}`} pathLength={1} stroke={ring ?? pal.ink} strokeWidth={3 * u}
            strokeDasharray="1 1" strokeDashoffset={1 - lead} fill="none" />
        </svg>
      ) : null}
      <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, transform: `scale(${k})` }}>
        <Cut src={src} imgW={imgW} imgH={imgH} poly={poly} x={0} y={0} s={zoom} seed={seed} amp={0.01} keyline={7 * u} lift={0.4} />
        <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <circle r={R + 3 * u} fill="none" stroke={ring ?? pal.ink} strokeWidth={5 * u} />
        </svg>
      </div>
    </>
  );
}

export type MagnifierProps = {
  /** the lens centre on the canvas, its radius, the handle angle (deg) */
  x: number; y: number; r?: number; ang?: number;
  zoom?: number;
  /** the canvas point shown at the lens centre (default the lens centre) */
  focus?: Pt;
  /** fill behind what the lens shows */
  back?: string;
  /** what the lens magnifies: the same elements as the scene, in canvas coordinates */
  children?: React.ReactNode;
};

/** A magnifying glass with a wooden handle that shows its children enlarged inside the lens. */
export function Magnifier({ x, y, r, ang = 35, zoom = 1.9, focus, back, children }: MagnifierProps) {
  const pal = usePalette();
  const u = useUnit();
  const { w, h } = useClip();
  const { soft, defs } = useFilters(9 * u);
  const [fx, fy] = focus ?? [x, y];
  const R = r ?? 150 * u;
  return (
    <>
      <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {defs}
        <g transform={`rotate(${ang} ${x} ${y})`}>
          <rect x={x + R * 0.95} y={y - 22 * u} width={R * 1.9} height={44 * u} rx={20 * u} fill={pal.shadow} opacity={0.22} transform={`translate(${10 * u} ${18 * u})`} filter={soft} />
          <rect x={x + R * 0.95} y={y - 22 * u} width={R * 1.9} height={44 * u} rx={20 * u} fill={pal.wood} />
          <rect x={x + R * 0.95} y={y - 22 * u} width={R * 1.9} height={12 * u} rx={6 * u} fill="#fff" opacity={0.18} />
          <rect x={x + R * 0.9} y={y - 28 * u} width={40 * u} height={56 * u} rx={8 * u} fill="#B89A5A" />
        </g>
        <circle cx={x + 8 * u} cy={y + 14 * u} r={R + 14 * u} fill={pal.shadow} opacity={0.2} filter={soft} />
      </svg>
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, clipPath: `circle(${R}px at ${x}px ${y}px)` }}>
        <div style={{ position: "absolute", inset: 0, background: back ?? pal.wall }} />
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0",
          transform: `translate(${x}px, ${y}px) scale(${zoom}) translate(${-fx}px, ${-fy}px)` }}>{children}</div>
        <div style={{ position: "absolute", left: x - R * 0.8, top: y - R * 0.75, width: R * 0.9, height: R * 0.42, borderRadius: "50%",
          background: "rgba(255,255,255,0.28)", transform: "rotate(-30deg)" }} />
      </div>
      <svg width={1} height={1} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        <circle cx={x} cy={y} r={R} fill="none" stroke="#B89A5A" strokeWidth={16 * u} />
        <circle cx={x} cy={y} r={R + 8 * u} fill="none" stroke={pal.ink} strokeOpacity={0.35} strokeWidth={2 * u} />
      </svg>
    </>
  );
}

export type Entrance = "drop" | "left" | "right" | "up" | "slap" | "grow" | "fade";
export type Exit = "left" | "right" | "up" | "down" | "shrink" | "fade";

export type ActorProps = {
  /** the frame it starts to enter; nothing is drawn before */
  at: number;
  /** the frame it starts to leave; nothing is drawn once it has gone (default: stays) */
  leave?: number;
  from?: Entrance;
  to?: Exit;
  /** frames the entrance and exit take */
  inLen?: number; outLen?: number;
  /** the point its scale and slap pivot on (default the clip centre) */
  ox?: number; oy?: number;
  /** move at 12 poses a second, like paper (true) or smoothly, like ink (false) */
  stop?: boolean;
  /** idle jitter in px while it stays (0 = still) */
  idle?: number;
  seed?: string;
  f?: number;
  children?: React.ReactNode;
};

/** Enter, stay, leave: wraps any child (a cut-out, a thing, a label) in an entrance, an idle boil and an exit. */
export function Actor({ at, leave, from = "drop", to = "fade", inLen = 8, outLen = 7, ox, oy, stop = true, idle = 0, seed = "actor", f: fIn, children }: ActorProps) {
  const now = useCurrentFrame();
  const { w, h, fps } = useClip();
  const f = fIn ?? now;
  if (f < at) return null;
  if (leave !== undefined && f >= leave + outLen) return null;
  const sf = stop ? Math.max(at, step(f, 12, fps)) : f;
  const e = from === "slap" || from === "grow" ? backOut(prog(sf, at, inLen), 2.2) : backOut(prog(sf, at, inLen), 1.4);
  const x = leave === undefined ? 0 : in2(prog(sf, leave, outLen));
  let tx = 0, ty = 0, sc = 1, op = 1, rot = 0;
  if (from === "drop") { ty = -(1 - e) * h * 0.5; rot = (1 - e) * 8; }
  else if (from === "left") tx = -(1 - e) * w;
  else if (from === "right") tx = (1 - e) * w;
  else if (from === "up") ty = (1 - e) * h * 0.6;
  else if (from === "slap") { sc = lerp(1.6, 1, e); op = clamp01(prog(sf, at, 2) + 0.2); }
  else if (from === "grow") sc = e;
  else op = clamp01(prog(f, at, inLen));
  if (x > 0) {
    if (to === "left") tx -= x * w;
    else if (to === "right") tx += x * w;
    else if (to === "up") ty -= x * h * 0.6;
    else if (to === "down") ty += x * h * 0.6;
    else if (to === "shrink") sc *= 1 - x;
    else op *= 1 - x;
  }
  const [jx, jy] = idle > 0 ? boil(seed, f, idle, fps) : [0, 0];
  const px = ox ?? w / 2, py = oy ?? h / 2;
  return (
    <div style={{
      position: "absolute", left: 0, top: 0, width: w, height: h, opacity: op, transformOrigin: `${px}px ${py}px`,
      transform: `translate(${tx + jx}px, ${ty + jy}px) rotate(${rot}deg) scale(${Math.max(0, sc)})`,
    }}>
      {children}
    </div>
  );
}
