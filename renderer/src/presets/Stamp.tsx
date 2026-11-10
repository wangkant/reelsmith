// A verdict seal slammed down at `at`: overshoots, shakes, settles. Sized so the rotated seal fits the clip box.
import { interpolate, useCurrentFrame } from "remotion";
import { FONTS, frameOr, numOr, springAt, textWidth, themeColor, twoLines, useClip, withAlpha } from "@reelsmith/kit";

// Han, kana and hangul fill a square seal; an alphabet's word does not
const SQUARE_SCRIPT = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/;

export default function Stamp({ props }: { props: any }) {
  const { w, h, fps, theme } = useClip();
  const f = useCurrentFrame();
  const label = String(props?.text ?? "").trim();
  const at = frameOr(props?.at, Math.round(0.2 * fps));
  if (!label || f < at) return null;

  const rotate = Math.max(-45, Math.min(45, numOr(props?.rotate, -12)));
  const round = props?.shape === "round";
  const dark = props?.ground === "dark";
  const color = themeColor(theme, props?.color, "accent");

  const lines = [...label].length >= 4 ? twoLines(label, 3) : [label];
  const longest = Math.max(...lines.map((l) => [...l].length));
  // one word in an alphabet is far wider than tall: its seal is a plaque around the word, not a square
  const plaque = !round && lines.length === 1 && longest >= 4 && !SQUARE_SCRIPT.test(label);
  // a line's width in em, its letter spacing (0.06 em a glyph) included
  const em = (l: string) => textWidth(l, 100, FONTS.display, 400) / 100 + 0.06 * [...l].length;
  const aspect = plaque ? Math.max(1.6, Math.min(4, em(label) * 0.58 + 0.44)) : 1;
  // the largest seal whose rotated outline still fits the box
  const rad = (Math.abs(rotate) * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const size = Math.max(10, round ? Math.min(w, h) * 0.94 : Math.min((w * 0.94) / (aspect * cos + sin), (h * 0.94) / (aspect * sin + cos)));
  const width = size * aspect;
  const border = size * (plaque ? 0.07 : 0.05);
  // a round seal holds text in its inscribed square
  const inner = round ? (size - border * 2) * 0.68 : width - border * 2 - size * (plaque ? 0.3 : 0.12);
  const cap = size * (plaque ? 0.58 : lines.length > 1 ? 0.36 : longest <= 2 ? 0.42 : 0.32);
  const fontSize = Math.min(cap, inner / Math.max(...lines.map(em)), inner / lines.length / 1.08);

  const hit = springAt(f, at, { fps, damping: 9, stiffness: 260, mass: 0.6 });
  const scale = interpolate(hit, [0, 1], [2.4, 1]);
  const t = f - at;
  const shake = t < 8 ? Math.sin(t * 2.6) * (8 - t) * (size / 340) : 0;

  return (
    <div style={{
      position: "absolute", left: (w - width) / 2 + shake, top: (h - size) / 2, width, height: size, boxSizing: "border-box",
      border: `${border}px ${props?.double ? "double" : "solid"} ${color}`, borderRadius: round ? "50%" : size * 0.08, color,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: FONTS.display, fontSize, lineHeight: 1.08, letterSpacing: fontSize * 0.06, whiteSpace: "pre",
      opacity: Math.min(1, hit * 1.4) * 0.94, transform: `rotate(${rotate}deg) scale(${scale})`,
      boxShadow: `inset 0 0 ${size * 0.06}px ${withAlpha(color, 0.35)}`,
      // multiply reads as ink on paper; on a dark ground it would vanish, so a faint plate carries it instead
      mixBlendMode: dark ? "normal" : "multiply",
      background: dark ? "rgba(255,253,248,0.12)" : "rgba(255,253,248,0.3)",
    }}>
      {lines.map((l, i) => <div key={i}>{l}</div>)}
    </div>
  );
}
