// A verdict seal slammed down at `at`: overshoots, shakes, settles. Sized so the rotated seal fits the clip box.
import { interpolate, useCurrentFrame } from "remotion";
import { fit, FONTS, frameOr, numOr, springAt, themeColor, twoLines, useClip, withAlpha } from "@reelsmith/kit";

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

  // the largest seal whose rotated outline still fits the box
  const rad = (Math.abs(rotate) * Math.PI) / 180;
  const turn = round ? 1 : Math.cos(rad) + Math.sin(rad);
  const size = Math.max(10, (Math.min(w, h) * 0.94) / turn);
  const border = size * 0.05;
  const inner = round ? (size - border * 2) * 0.68 : size - border * 2 - size * 0.12; // a round seal holds text in its inscribed square
  const lines = [...label].length >= 4 ? twoLines(label, 3) : [label];
  const longest = Math.max(...lines.map((l) => [...l].length));
  const cap = size * (lines.length > 1 ? 0.36 : longest <= 2 ? 0.42 : 0.32);
  // letter spacing (0.06 em a glyph) is not in the fitted width, so fit to a narrower line
  const fontSize = Math.min(...lines.map((l) => fit(l, inner / (1 + 0.06 * longest), cap, FONTS.display, 400)), inner / lines.length / 1.08);

  const hit = springAt(f, at, { fps, damping: 9, stiffness: 260, mass: 0.6 });
  const scale = interpolate(hit, [0, 1], [2.4, 1]);
  const t = f - at;
  const shake = t < 8 ? Math.sin(t * 2.6) * (8 - t) * (size / 340) : 0;

  return (
    <div style={{
      position: "absolute", left: (w - size) / 2 + shake, top: (h - size) / 2, width: size, height: size, boxSizing: "border-box",
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
