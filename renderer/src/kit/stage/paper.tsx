// Paper props that carry words: sticker labels, a hanging price tag, ink stamps, tape and a flip card.
import { useId } from "react";
import { useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { FONTS } from "../../fonts";
import { textWidth } from "../helpers";
import { clamp01, step } from "./time";
import { rect, roughRect, seedInt, torn } from "./geom";
import type { Pt } from "./geom";
import { shadowCss, usePalette, useUnit } from "./palette";

type Face = "display" | "sans" | "serif";
const family = (font?: Face) => (font === "sans" ? FONTS.sans : font === "serif" ? FONTS.serif : FONTS.display);
const weight = (font?: Face) => (font === "display" || !font ? 400 : 900);

/** The slap of a sticker pressed on at `at`: [scale, lift], stepped like a hand; null before `at`. */
const slap = (f: number, at: number | undefined, fps: number): [number, number] | null => {
  if (at === undefined) return [1, 0];
  if (f < at) return null;
  const t = step(f, 12, fps) - at;
  return t < 2.5 ? [1.5, 1] : t < 5 ? [0.95, 0.25] : [1, 0];
};

export type LabelProps = {
  x: number; y: number; text: string;
  /** font size in px (default 72; keep words on props at 64 or more) */
  size?: number;
  r?: number; s?: number; seed: string;
  /** a smaller second line under the text */
  sub?: string;
  bg?: string; color?: string; font?: Face;
  lift?: number; opacity?: number; padX?: number;
  /** 0..1: the sticker peels off about its left edge and is gone at 1 */
  peel?: number;
  /** when given, it slaps on at this frame (nothing before) */
  at?: number;
  f?: number;
  z?: number;
};

/** A paper sticker with a slightly torn edge, sized to its text. */
export function Label(p: LabelProps) {
  const now = useCurrentFrame();
  const { fps } = useClip();
  const pal = usePalette();
  const u = useUnit();
  const sl = slap(p.f ?? now, p.at, fps);
  if (!sl) return null;
  const size = p.size ?? 72 * u;
  const fam = family(p.font), wt = weight(p.font);
  const n = Array.from(p.text).length;
  const tw = textWidth(p.text, size, fam, wt) + size * 0.08 * n;
  const subSize = Math.max(40, size * 0.5);
  const W = Math.max(tw, p.sub ? textWidth(p.sub, subSize, FONTS.sans, 700) : 0) + (p.padX ?? size * 0.7) * 2;
  const H = size * 1.55 + (p.sub ? subSize * 1.3 : 0);
  const lift = Math.max(p.lift ?? 0, sl[1]);
  const ry = -180 * clamp01(p.peel ?? 0);
  const back = ry < -90;
  return (
    <div style={{
      position: "absolute", left: p.x - W / 2, top: p.y - H / 2, width: W, height: H, zIndex: p.z,
      transform: `perspective(1400px) rotate(${p.r ?? 0}deg) rotateY(${ry}deg) scale(${(p.s ?? 1) * sl[0] * (1 + 0.05 * lift)})`,
      transformOrigin: ry ? "0% 50%" : "50% 50%", opacity: (p.opacity ?? 1) * (1 - clamp01(((p.peel ?? 0) - 0.7) / 0.3)), filter: shadowCss(lift * 0.8, pal.shadow),
    }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        <path d={torn(rect(0, 0, W, H), p.seed, 2.2, 14)} fill={back ? "#E6DDCB" : p.bg ?? pal.paper} />
      </svg>
      {back ? null : (
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          fontFamily: fam, fontWeight: wt, fontSize: size, color: p.color ?? pal.ink, letterSpacing: size * 0.08, whiteSpace: "pre", lineHeight: 1,
        }}>
          <div>{p.text}</div>
          {p.sub ? <div style={{ fontFamily: FONTS.sans, fontWeight: 700, fontSize: subSize, letterSpacing: 2, marginTop: subSize * 0.25, opacity: 0.75 }}>{p.sub}</div> : null}
        </div>
      )}
    </div>
  );
}

export type TagProps = {
  /** the pin it hangs from, and its angle (deg; swing() makes it sway) */
  x: number; y: number; ang?: number; s?: number;
  text: string;
  unit?: string;
  /** 0..1: a red loop drawn round the text, a crack drawn across, the halves pulled apart */
  circle?: number; tear?: number; split?: number;
  w?: number; h?: number;
  color?: string;
  opacity?: number;
};

/** A manila tag on a string: one big word or number and a unit; it can be circled, cracked and torn in two. */
export function Tag({ x, y, ang = 0, s = 1, text, unit, circle = 0, tear = 0, split = 0, w, h, color, opacity = 1 }: TagProps) {
  const pal = usePalette();
  const u = useUnit();
  const W = w ?? 260 * u, H = h ?? 380 * u, L = 120 * u;
  const manila = color ?? "#E3C38A";
  const big = Math.min(150 * (W / 260), (W * 0.86) / Math.max(1, Array.from(text).length * 0.62));
  const unitSize = Math.max(40, W * 0.21);
  const crack = "0% 52%, 18% 47%, 31% 58%, 47% 49%, 62% 60%, 79% 50%, 100% 56%";
  const top = "polygon(0% 0%, 100% 0%, 100% 56%, 79% 50%, 62% 60%, 47% 49%, 31% 58%, 18% 47%, 0% 52%)";
  const bot = `polygon(${crack}, 100% 100%, 0% 100%)`;
  const half = (clip: string, k: number) => (
    <div style={{
      position: "absolute", left: -W / 2, top: L, width: W, height: H, clipPath: split > 0 ? clip : undefined,
      transform: `translate(${k * split * 70 * u}px, ${k > 0 ? split * 260 * u : -split * 30 * u}px) rotate(${k * split * 24}deg)`,
      opacity: k > 0 ? 1 - clamp01((split - 0.6) * 2.5) : 1,
    }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <path d={`M${W * 0.15} 0 L${W * 0.85} 0 L${W} ${H * 0.12} L${W} ${H} L0 ${H} L0 ${H * 0.12} Z`} fill={manila} stroke="#B8945C" strokeWidth={3 * u} />
        <circle cx={W / 2} cy={H * 0.095} r={13 * u} fill={pal.kraft} stroke="#9C7748" strokeWidth={5 * u} />
        <path d={`M${14 * u} ${H - 14 * u} L${W - 14 * u} ${H - 14 * u}`} stroke="#B8945C" strokeWidth={2 * u} strokeDasharray={`${8 * u} ${7 * u}`} />
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: H * 0.2, height: H * 0.44, display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: FONTS.sans, fontWeight: 900, fontSize: big, color: pal.ink, lineHeight: 1, letterSpacing: -big * 0.03, whiteSpace: "pre" }}>{text}</div>
      {unit ? <div style={{ position: "absolute", left: 0, right: 0, top: H * 0.66, textAlign: "center", fontFamily: FONTS.sans, fontWeight: 800,
        fontSize: unitSize, color: pal.ink, letterSpacing: 4 * u, whiteSpace: "pre" }}>{unit}</div> : null}
      {circle > 0 ? (
        <svg width={W} height={H} viewBox="0 0 260 380" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <path d="M60 120 C 40 60, 230 50, 225 140 C 220 225, 40 230, 38 150 C 36 95, 110 70, 150 74" pathLength={1}
            fill="none" stroke={pal.red} strokeWidth={9} strokeLinecap="round" strokeDasharray="1 1" strokeDashoffset={1 - clamp01(circle)} />
        </svg>
      ) : null}
      {tear > 0 && split === 0 ? (
        <svg width={W} height={H} viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
          <polyline points="0,52 18,47 31,58 47,49 62,60 79,50 100,56" pathLength={1} fill="none" stroke={pal.ink} strokeWidth={0.9}
            strokeDasharray="1 1" strokeDashoffset={1 - clamp01(tear)} />
        </svg>
      ) : null}
    </div>
  );
  return (
    <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, transform: `rotate(${ang}deg) scale(${s})`, transformOrigin: "0 0", opacity }}>
      <svg width={4} height={L + 40 * u} style={{ position: "absolute", left: -2, top: 0, overflow: "visible" }}>
        <path d={`M2 0 Q ${-6 * u} ${L * 0.5} 2 ${L + 36 * u}`} stroke="#6E5536" strokeWidth={3 * u} fill="none" />
      </svg>
      <div style={{ position: "absolute", left: -11 * u, top: -11 * u, width: 22 * u, height: 22 * u, borderRadius: "50%", background: "radial-gradient(circle at 35% 35%, #F2E7D2, #8A7A63)", boxShadow: "2px 4px 5px rgba(0,0,0,0.35)" }} />
      <div style={{ position: "absolute", left: 0, top: 0, filter: shadowCss(0.5, pal.shadow) }}>
        {half(top, -1)}
        {split > 0 ? half(bot, 1) : null}
      </div>
    </div>
  );
}

export type StampProps = {
  x: number; y: number; text: string;
  /** the frame it thumps down (nothing before) */
  at: number;
  sub?: string; round?: boolean;
  r?: number; size?: number; color?: string;
  /** seeds the ink texture, so no two stamps look alike */
  seed?: string;
  fade?: number;
  f?: number;
};

/** An ink stamp pressed down at `at` like a hand press, rough where the ink did not take. */
export function Stamp({ x, y, text, at, sub, round = false, r = -8, size: sizeIn, color, seed = "stamp", fade = 1, f: fIn }: StampProps) {
  const id = "ss" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const now = useCurrentFrame();
  const { fps } = useClip();
  const pal = usePalette();
  const f = fIn ?? now;
  const u = useUnit();
  const size = sizeIn ?? 78 * u;
  if (f < at) return null;
  const t = ((f - at) * 30) / fps;
  const sc = t < 2 ? 1.45 : t < 4 ? 0.94 : 1;
  const ink = t < 2 ? 0.25 : 0.86;
  const c = color ?? pal.red;
  const n = Array.from(text).length;
  const subSize = Math.max(40, size * 0.5);
  const W = round ? size * Math.max(3.3, n * 1.2 + 1) : size * (n * 1.12 + 0.9), H = round ? W : size * 1.55 + (sub ? subSize * 1.2 : 0);
  return (
    <div style={{
      position: "absolute", left: x - W / 2, top: y - H / 2, width: W, height: H, opacity: ink * fade,
      transform: `rotate(${r}deg) scale(${sc})`, filter: `url(#${id})`, mixBlendMode: "multiply",
    }}>
      <svg width={0} height={0} style={{ position: "absolute" }}>
        <filter id={id}>
          <feTurbulence type="fractalNoise" baseFrequency="0.06" numOctaves={2} seed={seedInt(seed + "d")} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={5} result="d" />
          <feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves={1} seed={seedInt(seed + "s")} result="s" />
          <feColorMatrix in="s" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 1.7" result="m" />
          <feComposite in="d" in2="m" operator="in" />
        </filter>
      </svg>
      <div style={{
        position: "absolute", inset: 0, border: `${size * 0.09}px solid ${c}`, borderRadius: round ? "50%" : size * 0.12,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: c,
        fontFamily: FONTS.sans, fontWeight: 900, fontSize: size, letterSpacing: size * 0.1, whiteSpace: "pre", lineHeight: 1.05,
      }}>
        {round ? <div style={{ position: "absolute", inset: size * 0.22, border: `${size * 0.04}px solid ${c}`, borderRadius: "50%" }} /> : null}
        <div>{text}</div>
        {sub ? <div style={{ fontSize: subSize, letterSpacing: size * 0.06, marginTop: size * 0.12 }}>{sub}</div> : null}
      </div>
    </div>
  );
}

/** A strip of masking tape (to pin a cut-out down). */
export function Tape({ x, y, w, r = 0, seed, opacity = 1, color = "#EFE6CC" }: { x: number; y: number; w?: number; r?: number; seed: string; opacity?: number; color?: string }) {
  const u = useUnit();
  const W = w ?? 150 * u, h = 46 * u;
  const pts: Pt[] = [[0, 0], [W, 0], [W, h], [0, h]];
  const d = torn(pts, seed, 3 * u, 7 * u);
  return (
    <svg width={W} height={h} style={{ position: "absolute", left: x - W / 2, top: y - h / 2, transform: `rotate(${r}deg)`, overflow: "visible", opacity }}>
      <path d={d} fill={color} opacity={0.8} />
      <path d={d} fill="none" stroke="#fff" strokeOpacity={0.3} />
    </svg>
  );
}

export type CardProps = {
  x: number; y: number;
  /** front and back text */
  a: string; b: string;
  /** 0..1: the flip (past 0.5 the back shows) */
  flip?: number;
  w?: number; h?: number; size?: number;
  color?: string; back?: string;
  r?: number; seed?: string;
};

/** A stiff card that flips over to change its word (the reveal of what something really is). */
export function Card({ x, y, a, b, flip = 0, w, h, size, color, back, r = 0, seed = "card" }: CardProps) {
  const pal = usePalette();
  const u = useUnit();
  const k = Math.cos(Math.PI * clamp01(flip));
  const showB = flip >= 0.5;
  const text = showB ? b : a;
  const n = Math.max(Array.from(a).length, Array.from(b).length);
  const fs = size ?? 84 * u;
  const W = w ?? Math.max(300 * u, fs * (n * 1.12 + 1.2)), H = h ?? fs * 1.9;
  const ink = color ?? pal.red;
  const lift = Math.sin(Math.PI * clamp01(flip));
  return (
    <div style={{ position: "absolute", left: x - W / 2, top: y - H / 2, width: W, height: H, transform: `rotate(${r}deg) translateY(${-40 * u * lift}px)` }}>
      <div style={{ position: "absolute", inset: 0, transform: `scaleX(${Math.max(0.02, Math.abs(k))})`, filter: shadowCss(0.2 + 0.6 * lift, pal.shadow) }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <path d={roughRect(0, 0, W, H, 12 * u, seed + (showB ? "b" : "a"), 0.004)} fill={showB ? back ?? "#FBF3E4" : pal.paper} stroke="#D8CFBF" strokeWidth={3 * u} />
          <rect x={12 * u} y={12 * u} width={W - 24 * u} height={H - 24 * u} rx={6 * u} fill="none" stroke={ink} strokeWidth={3 * u} opacity={0.8} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.serif,
          fontWeight: 900, fontSize: fs, color: ink, letterSpacing: fs * 0.12, whiteSpace: "pre", lineHeight: 1 }}>{text}</div>
      </div>
    </div>
  );
}
