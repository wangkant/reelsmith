// Who gains and who loses from the same thing. Weight chips drop onto two plates, then the beam tips toward the side
// that carries more (plates stay level and ride the beam), sways a little, and a verdict lands last.
import React from "react";
import { useCurrentFrame } from "remotion";
import { breakLines, ease, FONTS, frameOr, onGround, springAt, textWidth, themeColor, twoLines, useClip, withAlpha } from "@reelsmith/kit";

type Item = { text: string; at?: number };
type Side = { title?: string; items?: Item[] };
type Chip = { lines: string[]; w: number; h: number };

const cl = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
// reading-text floor in canvas px at a 1080 short side
const READ = 40;

const natural = (text: string, maxW: number, family: string, weight: number) =>
  Math.floor((maxW * 100) / Math.max(1, textWidth(text, 100, family, weight)));

/** Lines of `text` at `size` within `maxW`: one line, else two balanced lines, else as many as it takes (never
 *  inside a word; CJK by the kit's breaking rules). */
function linesAt(text: string, size: number, maxW: number, family: string, weight: number): string[] {
  const m = (s: string) => textWidth(s, size, family, weight);
  if (m(text) <= maxW) return [text];
  const two = twoLines(text, 1);
  if (two.every((l) => m(l) <= maxW)) return two;
  return breakLines(text, maxW, m, true).map((l) => l.trim()).filter(Boolean);
}

function chipsFor(items: Item[], size: number, maxW: number): Chip[] {
  const pad = Math.round(size * 0.42);
  const m = (s: string) => textWidth(s, size, FONTS.sans, 800);
  return items.map((it) => {
    const lines = linesAt(String(it.text ?? "").trim(), size, maxW - pad * 2, FONTS.sans, 800);
    const tw = Math.max(...lines.map(m));
    return { lines, w: Math.max(tw + pad * 2, size * 3.2), h: lines.length * size * 1.2 + size * 0.62 };
  });
}

export default function Seesaw({ props }: { props: any }) {
  const { w: boxW, h: boxH, fps, theme, width, height } = useClip();
  const f = useCurrentFrame();
  // laid out in px of a 1080 short side, then scaled to the canvas
  const unit = Math.min(width, height) / 1080 || 1;
  const bw0 = boxW / unit, bh0 = boxH / unit;
  if (!(bw0 >= 200 && bh0 >= 200)) return null;
  const ink = onGround(theme, props?.ground);
  const dark = ink.dark;
  const accent = themeColor(theme, props?.color, "accent");
  const sides: Side[] = [props?.left ?? {}, props?.right ?? {}];
  const items: Item[][] = sides.map((s) => (Array.isArray(s.items) ? s.items.filter((it) => it && typeof it === "object").slice(0, 3) : []));
  const titles = sides.map((s) => String(s.title ?? "").trim());
  const tilt = props?.tilt === "left" ? -1 : props?.tilt === "right" ? 1 : 0;
  const verdict = props?.verdict && props.verdict.text ? props.verdict : null;
  const vText = verdict ? String(verdict.text).trim() : "";
  const maxAng = (9 * Math.PI) / 180;
  const post = 22;
  const plateH = 16;

  const C = dark
    ? { panel: theme.night, chip: "#2C2621", chipBorder: "rgba(255,255,255,0.12)", beam: theme.snow, pivot: "#5C5248",
        plate: "#9A8C7C", shadow: "rgba(0,0,0,0.45)", vBg: theme.snow, vText: theme.night }
    : { panel: theme.paper, chip: "#FFFCF7", chipBorder: withAlpha(theme.ink, 0.1), beam: theme.ink, pivot: "#3B332B",
        plate: "#5A4E42", shadow: "rgba(40,30,20,0.16)", vBg: theme.ink, vText: theme.snow };

  // layout of a w x h box at scale k; a box too small is laid out larger and scaled down whole, text keeping its floor
  const layoutAt = (w: number, h: number, k: number, chipFloor = READ) => {
    const floor = READ / k;
    const P = Math.round(cl(Math.min(w, h) * 0.04, 20, 34));
    const IW = w - 2 * P;
    // titles: one shared size, 48-62 px on one line; else down to the floor; else two lines
    const tMax = IW / 2 - 28;
    const tOne = Math.min(62, ...titles.filter(Boolean).map((t) => natural(t, tMax, FONTS.display, 400)));
    let titleSize = Math.max(Math.min(62, Math.max(48, floor)), floor);
    let tLines = titles.map((t) => (t ? [t] : []));
    if (tOne >= Math.max(48, floor)) titleSize = Math.min(Math.max(62, floor), tOne);
    else if (tOne >= floor) titleSize = tOne;
    else {
      titleSize = Math.max(48, floor);
      while (titleSize > floor && titles.some((t) => t && linesAt(t, titleSize, tMax, FONTS.display, 400).length > 2)) titleSize -= 2;
      titleSize = Math.max(titleSize, floor);
      tLines = titles.map((t) => (t ? linesAt(t, titleSize, tMax, FONTS.display, 400) : []));
    }
    const tRows = Math.max(1, ...tLines.map((l) => l.length));
    const titleBottom = P + 8 + tRows * titleSize * 1.15;
    const titleOk = tLines.every((ls) => ls.every((l) => textWidth(l, titleSize, FONTS.display, 400) <= IW / 2 - 16));
    // verdict: one line down to 44 px, else two (or more) balanced lines down to the floor
    const vMax = IW - 80;
    let vLines = vText ? [vText] : [];
    let vSize = vText ? Math.min(Math.max(60, floor), natural(vText, vMax, FONTS.display, 400)) : 0;
    if (vText && vSize < Math.max(44, floor)) {
      vSize = Math.max(52, floor);
      vLines = linesAt(vText, vSize, vMax, FONTS.display, 400);
      while (vSize > floor && (vLines.length > 2 || vLines.some((l) => textWidth(l, vSize, FONTS.display, 400) > vMax))) {
        vSize -= 2;
        vLines = linesAt(vText, vSize, vMax, FONTS.display, 400);
      }
      vSize = Math.max(floor, Math.min(vSize, Math.max(52, floor), ...vLines.map((l) => natural(l, vMax, FONTS.display, 400))));
    }
    const vH = vText ? vLines.length * vSize * 1.2 + 26 : 0;
    const textOk = vLines.every((l) => textWidth(l, vSize, FONTS.display, 400) <= vMax + 1);
    const plateW = Math.min(IW * 0.46, 340);
    const half = IW / 2 - plateW / 2;
    const rise = half * Math.sin(maxAng + 0.012) + 6;
    const beamT = Math.max(16, Math.round(IW * 0.03));
    const pivotBase = h - P - (vH ? vH + 22 : 6);
    let lay = { pivH: 64, size: floor, chips: [[], []] as Chip[][] };
    let ok = false;
    let slack = -Infinity;
    for (const pivH of [150, 125, 100, 80, 64]) {
      for (const s of [46, 43, 40, 37, 34, 31]) {
        if (s < chipFloor) break;
        const size = Math.max(s, chipFloor / k);
        const chips = items.map((its) => chipsFor(its, size, IW / 2 - 14));
        const stackH = Math.max(0, ...chips.map((cs) => cs.reduce((a, c) => a + c.h + 8, 0)));
        const plateTop = pivotBase - pivH - beamT / 2 - post - plateH;
        lay = { pivH, size, chips };
        const wide = chips.every((cs) => cs.every((c) => c.w <= IW / 2 - 14));
        const room = plateTop - stackH - rise - (titleBottom + 14);
        slack = Math.max(slack, room * k);
        if (wide && textOk && titleOk && room >= 0) { ok = true; break; }
      }
      if (ok) break;
    }
    return { P, IW, titleSize, tLines, titleBottom, vSize, vLines, vH, plateW, half, beamT, pivotBase, lay, ok, slack };
  };
  let k = 1;
  let G = layoutAt(bw0, bh0, 1);
  let best = { G, k };
  for (const kk of [0.92, 0.84, 0.76, 0.68, 0.6, 0.52]) {
    if (G.ok) break;
    k = kk;
    G = layoutAt(bw0 / kk, bh0 / kk, kk);
    if (G.ok || G.slack > best.G.slack) best = { G, k };
  }
  // nothing fits at 40 px: let the chips go down to 30 px before anything overlaps, else the least bad scale
  for (const kk of [1, 0.92, 0.84, 0.76, 0.68, 0.6, 0.52]) {
    if (G.ok) break;
    const g = layoutAt(bw0 / kk, bh0 / kk, kk, 30);
    if (g.ok) { G = g; k = kk; }
  }
  if (!G.ok) ({ G, k } = best);
  const w = bw0 / k, h = bh0 / k;
  const { P, IW, titleSize, tLines, titleBottom, vSize, vLines, vH, plateW, half, beamT, pivotBase, lay } = G;
  const cx = w / 2;
  const yc = pivotBase - lay.pivH;

  // time
  const start = 0;
  const baseS = springAt(f, start, { fps, damping: 200, durationInFrames: 12 });
  const itemAt = items.map((its, si) => its.map((it, i) => (it.at !== undefined && it.at !== null ? frameOr(it.at, 0) : Math.round((0.6 + si * 0.9 + i * 0.35) * fps))));
  const lastItem = Math.max(0, ...itemAt.flat());
  const tiltAt = frameOr(props?.tilt_at, lastItem + Math.round(0.6 * fps));
  const vAt = verdict ? frameOr(verdict.at, tiltAt + Math.round(0.8 * fps)) : 0;

  // beam angle: little bumps as chips land, the tilt spring, then a slow sway
  let ang = 0;
  items.forEach((its, si) => its.forEach((_, i) => {
    const a = itemAt[si][i];
    if (f >= a) {
      const t = f - a - 3;
      if (t > 0) ang += (si === 0 ? -1 : 1) * 0.012 * Math.exp(-t / 7) * Math.sin(t / 2.2);
    }
  }));
  const tS = tilt ? springAt(f, tiltAt, { fps, damping: 9, stiffness: 70, mass: 1.1 }) : 0;
  ang += tilt * maxAng * tS;
  const swayIn = ease(f, tiltAt + Math.round(0.8 * fps), tiltAt + Math.round(1.6 * fps));
  ang += Math.sin((f / fps) * Math.PI * 2 / 3.4) * 0.0075 * (tilt ? swayIn : 1);
  ang = cl(ang, -maxAng - 0.012, maxAng + 0.012);
  const end = (s: number) => ({ x: cx + s * half * Math.cos(ang), y: yc + s * half * Math.sin(ang) });
  const heavy = tilt === 0 ? -1 : tilt < 0 ? 0 : 1;
  const heavyT = tilt ? ease(f, tiltAt + 4, tiltAt + 16) : 0;

  const out: React.ReactNode[] = [];
  // titles
  tLines.forEach((ls, si) => {
    if (!ls.length) return;
    const s = springAt(f, start + 4 + si * 5, { fps, damping: 14 });
    const hot = si === heavy && heavyT > 0;
    // centred over its plate, but never past the panel edge
    const tcx = cl(cx + (si === 0 ? -1 : 1) * half, P + IW / 4, w - P - IW / 4);
    out.push(
      <div key={"t" + si} style={{
        position: "absolute", left: tcx - IW / 4 + 4, width: IW / 2 - 8, top: P + 8, textAlign: "center",
        fontFamily: FONTS.display, fontSize: titleSize, lineHeight: 1.15, whiteSpace: "pre",
        color: hot ? accent : ink.ink, opacity: s, transform: `translateY(${(1 - s) * 18}px)`,
      }}>{ls.join("\n")}</div>,
    );
    if (hot) {
      const tw = Math.max(...ls.map((l) => textWidth(l, titleSize, FONTS.display, 400)));
      const uw = Math.min(IW / 2 - 40, tw) * heavyT;
      out.push(<div key={"u" + si} style={{ position: "absolute", left: tcx - uw / 2, top: titleBottom + 2, width: uw, height: 6, borderRadius: 3, background: accent }} />);
    }
  });

  // pivot, beam, plates
  const pv = lay.pivH;
  const pw = Math.min(pv * 1.05, IW * 0.22);
  out.unshift(
    <svg key="rig" width={w} height={h} style={{ position: "absolute", left: 0, top: 0, opacity: baseS }}>
      <ellipse cx={cx} cy={pivotBase + 4} rx={pw * 0.95} ry={9} fill={C.shadow} />
      <path d={`M${cx} ${yc + 4} L${cx + pw / 2} ${pivotBase} Q${cx + pw / 2 + 4} ${pivotBase + 4} ${cx + pw / 2 - 6} ${pivotBase + 4} L${cx - pw / 2 + 6} ${pivotBase + 4} Q${cx - pw / 2 - 4} ${pivotBase + 4} ${cx - pw / 2} ${pivotBase} Z`}
        fill={C.pivot} stroke={C.pivot} strokeWidth={10} strokeLinejoin="round" />
      <g transform={`rotate(${(ang * 180) / Math.PI} ${cx} ${yc})`}>
        <rect x={cx - half - beamT} y={yc - beamT / 2} width={half * 2 + beamT * 2} height={beamT} rx={beamT / 2} fill={C.beam} />
      </g>
      <circle cx={cx} cy={yc} r={beamT * 0.95} fill={theme.gold} stroke={C.beam} strokeWidth={4} />
      {[-1, 1].map((s) => {
        const e = end(s);
        const top = e.y - beamT / 2 - post - plateH;
        return (
          <g key={"pl" + s}>
            <rect x={e.x - 5} y={top + plateH - 2} width={10} height={post + 4} rx={4} fill={C.beam} />
            <path d={`M${e.x - plateW / 2} ${top} H${e.x + plateW / 2} L${e.x + plateW / 2 - 18} ${top + plateH} H${e.x - plateW / 2 + 18} Z`}
              fill={C.plate} stroke={C.plate} strokeWidth={6} strokeLinejoin="round" />
          </g>
        );
      })}
    </svg>,
  );

  // chips stacked on each plate, riding with it
  lay.chips.forEach((chips, si) => {
    const s = si === 0 ? -1 : 1;
    const e = end(s);
    let y = e.y - beamT / 2 - post - plateH - 4;
    chips.forEach((c, i) => {
      const a = itemAt[si][i];
      const top = y - c.h;
      y = top - 8;
      if (f < a) return;
      const sp = springAt(f, a, { fps, damping: 11, stiffness: 160 });
      const drop = (1 - sp) * -140;
      const jx = (i % 2 === 0 ? 1 : -1) * (i ? 7 : 0) * s;
      const rot = (i % 2 === 0 ? -1 : 1) * (i ? 1.4 : 0.6);
      const left = cl(e.x - c.w / 2 + jx, P * 0.5, w - P * 0.5 - c.w);
      out.push(
        <div key={`c${si}-${i}`} style={{
          position: "absolute", left, top: top + drop, width: c.w, height: c.h, borderRadius: 16,
          background: C.chip, border: `2px solid ${C.chipBorder}`, boxSizing: "border-box",
          boxShadow: `0 8px 18px ${C.shadow}, inset 0 -6px 0 ${withAlpha(dark ? "#000000" : theme.ink, dark ? 0.25 : 0.06)}`,
          display: "flex", alignItems: "center", justifyContent: "center", paddingBottom: 4,
          opacity: Math.min(1, sp * 2), transform: `rotate(${rot}deg)`,
          fontFamily: FONTS.sans, fontWeight: 800, fontSize: lay.size, lineHeight: 1.2, color: ink.ink,
          whiteSpace: "pre", textAlign: "center",
        }}>{c.lines.join("\n")}</div>,
      );
    });
  });

  // verdict under the pivot
  if (verdict && f >= vAt) {
    const s = springAt(f, vAt, { fps, damping: 13 });
    const vw = Math.min(IW, Math.max(...vLines.map((l) => textWidth(l, vSize, FONTS.display, 400))) + 60);
    out.push(
      <div key="v" style={{
        position: "absolute", left: cx - vw / 2, top: h - P - vH, width: vw, height: vH, borderRadius: Math.min(vH / 2, 40), textAlign: "center",
        background: C.vBg, color: C.vText, fontFamily: FONTS.display, fontSize: vSize, lineHeight: 1.2,
        display: "flex", alignItems: "center", justifyContent: "center", whiteSpace: "pre",
        opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 20}px) scale(${0.9 + 0.1 * s})`,
        boxShadow: `0 8px 20px ${C.shadow}`,
      }}>{vLines.join("\n")}</div>,
    );
  }

  const S = unit * k;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transform: S !== 1 ? `scale(${S})` : undefined, transformOrigin: "0 0" }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: 36, background: C.panel, boxShadow: `0 24px 60px ${C.shadow}`,
        opacity: Math.min(1, baseS * 1.5), transform: `scale(${0.96 + 0.04 * baseS})` }} />
      {out}
    </div>
  );
}
