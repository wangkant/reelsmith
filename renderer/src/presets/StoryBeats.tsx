// What happened, in order. A rail grows down to each beat as it lands; the latest beat is large with its `when` chip,
// earlier beats fold into compact dimmed lines, later beats stay hidden until their time.
import React from "react";
import { useCurrentFrame } from "remotion";
import { breakLines, FONTS, frameOr, onGround, springAt, textWidth, themeColor, twoLines, useClip, withAlpha, words } from "@reelsmith/kit";

type Beat = { when: string; text: string; hot: boolean; at: number };

/** `a` moved toward `b` by `t` (hex colours; anything else returns `a`). */
const mix = (a: string, b: string, t: number): string => {
  const rgb = (c: string) => {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c.trim());
    if (!m) return null;
    const x = m[1].length === 3 ? m[1].split("").map((d) => d + d).join("") : m[1];
    return [0, 2, 4].map((i) => parseInt(x.slice(i, i + 2), 16));
  };
  const p = rgb(a);
  const q = rgb(b);
  if (!p || !q) return a;
  return "#" + p.map((v, i) => Math.round(v + (q[i] - v) * t).toString(16).padStart(2, "0")).join("");
};

/** Lines no wider than `width`, broken between words (balanced unless that strands a short line); a word wider than
 *  `width` alone is cut by characters; a hyphen that starts a line goes back to the end of the line before. */
const wrap = (text: string, width: number, measure: (s: string) => number): string[] => {
  const bal = breakLines(text, width, measure, true);
  const gre = breakLines(text, width, measure, false);
  const shortest = (ls: string[]) => Math.min(...ls.map(measure)) / Math.max(1, ...ls.map(measure));
  const pick = gre.length < bal.length || (gre.length === bal.length && shortest(bal) < 0.35 && shortest(gre) > shortest(bal)) ? gre : bal;
  const lines = pick.flatMap((line) => {
    if (measure(line) <= width) return [line];
    const out: string[] = [];
    let cur = "";
    for (const ch of [...line]) {
      if (cur && measure(cur + ch) > width) { out.push(cur.trim()); cur = ""; }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  });
  for (let i = 1; i < lines.length; i++) {
    const m = /^[-\u2010\u2013]/.exec(lines[i]);
    if (m && lines[i].length > 1 && measure(lines[i - 1] + m[0]) <= width) {
      lines[i - 1] += m[0];
      lines[i] = lines[i].slice(1).trimStart();
    }
  }
  return lines;
};

/** `wrap`, except that Han text breaks between characters (as Chinese is set) when word breaks cost a line. */
const wrapTight = (text: string, width: number, measure: (s: string) => number): string[] => {
  const byWord = wrap(text, width, measure);
  if (!/\p{Script=Han}/u.test(text)) return byWord;
  const byChar = breakLines(text, width, measure, false, true);
  return byChar.length < byWord.length ? byChar : byWord;
};

/** Width at 100 px of the widest unbreakable word. */
const widestWord = (text: string, family: string, weight: number | string = 400) =>
  Math.max(1, ...words(text).filter((s) => s.trim()).map((s) => textWidth(s, 100, family, weight)));

export default function StoryBeats({ props }: { props: any }) {
  const { w, h, fps, theme, width, height } = useClip();
  const f = useCurrentFrame();
  const uid = "sb" + React.useId().replace(/[^A-Za-z0-9_-]/g, "");
  const u = Math.min(width, height) / 1080; // 1 at a 1080 px short side
  if (!(w >= 200 * u && h >= 200 * u)) return null;

  const raw: any[] = Array.isArray(props.beats) ? props.beats : [];
  const step = Math.round(1.6 * fps);
  const beats: Beat[] = raw
    .filter((b) => b && String(b.text ?? "").trim())
    .slice(0, 5)
    .map((b, i) => ({ when: String(b.when ?? "").trim(), text: String(b.text).trim(), hot: !!b.hot, at: frameOr(b.at, i * step) }));
  for (let i = 1; i < beats.length; i++) beats[i].at = Math.max(beats[i].at, beats[i - 1].at + 4);
  const n = beats.length;
  if (!n || f < beats[0].at) return null;

  const g = onGround(theme, props.ground);
  const dark = g.dark;
  const accent = themeColor(theme, props.color, "accent");
  const ink = g.ink;
  const ground = dark ? theme.night : theme.paper;
  const cardBg = dark ? mix(theme.night, theme.snow, 0.08) : mix(theme.paper, "#FFFFFF", 0.75);
  const dimInk = withAlpha(ink, dark ? 0.62 : 0.58);
  const railCol = withAlpha(ink, dark ? 0.22 : 0.16);

  const WHEN_SIZE = 30 * u;
  const CHIP_SIZE = 34 * u;
  const FLOOR = 40 * u;
  const BIG_MIN = 56 * u;
  const chipGap = 16 * u;
  const pad = Math.round(Math.max(34 * u, Math.min(56 * u, w * 0.07)));
  const dotR = 11 * u;
  const railX = pad + 16 * u;
  const textX = railX + 42 * u;
  const textW = Math.max(80 * u, w - textX - pad);

  // One shared column for the compact `when` labels, so every compact text starts at the same x; long labels wrap in it
  // at their own line height, and the column stays under 30 % of the card so the texts keep their room.
  const whenW = (s: string) => textWidth(s, WHEN_SIZE, FONTS.sans, 700);
  const colGap = 20 * u;
  const whenCol = Math.min(textW * 0.3, Math.max(0, ...beats.map((b) => (b.when ? whenW(b.when) + colGap : 0))));
  const whenLines = beats.map((b) => (b.when ? wrap(b.when, Math.max(1, whenCol - colGap), whenW) : []));
  // The chip of the large beat: shrinks to fit the text column (never under 30 px at a 1080 short side), then wraps.
  const chipPadX = 0.55;
  const chips = beats.map((b) => {
    if (!b.when) return { size: 0, lines: [] as string[] };
    const size = Math.max(WHEN_SIZE, Math.min(CHIP_SIZE, Math.floor((textW * 100) / (textWidth(b.when, 100, FONTS.sans, 800) + 2 * chipPadX * 100))));
    const lines = wrap(b.when, Math.max(1, textW - 2 * chipPadX * size), (s) => textWidth(s, size, FONTS.sans, 800));
    return { size, lines };
  });

  // Geometry for one size step; bounded search below picks the largest step where every moment fits.
  const geom = (k: number) => {
    // past step 14 the large beat itself gives way, from 56 down to the 40 floor
    const bigMin = k <= 14 ? BIG_MIN : Math.max(FLOOR, BIG_MIN - (k - 14) * 2 * u);
    const bigMax = Math.max(bigMin, (104 - k * 4) * u);
    const csMax = Math.max(FLOOR, (50 - k) * u);
    const gap = Math.max(18, 48 - k * 3) * u;
    const cRoom = Math.max(60 * u, textW - whenCol);
    // One compact size for every row: the largest that keeps each on one line, floored at 40 (then it wraps).
    const cs = Math.max(FLOOR, Math.min(csMax, ...beats.map((b) =>
      Math.floor((cRoom * 100) / Math.max(1, textWidth(b.text, 100, FONTS.sans, 600))))));
    const items = beats.map((b, i) => {
      const cLines = textWidth(b.text, cs, FONTS.sans, 600) <= cRoom
        ? [b.text]
        : wrapTight(b.text, cRoom, (t) => textWidth(t, cs, FONTS.sans, 600));
      const w100 = (t: string) => textWidth(t, 100, FONTS.sans, 800);
      const one = Math.floor((textW * 100) / Math.max(1, w100(b.text)));
      // the smallest large size: 56, less when one long word needs it (never under the 40 floor)
      const low = Math.max(FLOOR, Math.min(bigMin, Math.floor((textW * 100) / widestWord(b.text, FONTS.sans, 800))));
      // One line when it stays big; else two balanced lines sized to the wider one; else as many as it needs.
      const two = twoLines(b.text, 4);
      const bLines = one >= 80 * u ? [b.text]
        : Math.max(...two.map(w100)) * (low / 100) <= textW ? two
        : wrap(b.text, textW, (t) => textWidth(t, low, FONTS.sans, 800));
      const widest = Math.max(...bLines.map(w100));
      const bs = Math.max(low, Math.min(bigMax, Math.floor((textW * 100) / Math.max(1, widest))));
      const chip = chips[i];
      const chipH = b.when ? chip.lines.length * chip.size * 1.15 + chip.size * 0.5 + chipGap : 0;
      const whenH = whenLines[i].length ? (cs * 1.32 - WHEN_SIZE * 1.2) / 2 + whenLines[i].length * WHEN_SIZE * 1.2 : 0;
      return { cLines, Hc: Math.max(cLines.length * cs * 1.32, whenH), bs, bLines, chipH, Hb: chipH + bLines.length * bs * 1.2 };
    });
    let need = 0;
    let acc = 0;
    let finalH = 0;
    items.forEach((it) => { need = Math.max(need, acc + it.Hb); finalH = acc + it.Hb; acc += it.Hc + gap; });
    return { cs, gap, items, need: need + pad * 2, finalH: finalH + pad * 2 };
  };
  const LAST = 22;
  let G = geom(LAST);
  for (let k = 0; k <= LAST; k++) {
    const lay = geom(k);
    if (lay.need <= h) { G = lay; break; }
  }
  const { cs, gap, items } = G;
  // When even the floor does not fit, the card is laid out in a taller box and scaled down to this one.
  const fitScale = G.need > h ? h / G.need : 1;
  const H = h / fitScale;
  // The card grows down from a top that centres its final (all beats landed) height in the box.
  const top = Math.max(0, Math.min((H - G.finalH) / 2, H - G.need));

  const sp = (at: number) => (f < at ? 0 : springAt(f, at, { fps, damping: 15, durationInFrames: 12 }));
  const p = beats.map((b) => sp(b.at));
  const big = beats.map((_, i) => Math.max(0, p[i] - (i + 1 < n ? p[i + 1] : 0)));
  const cur = beats.reduce((c, b, i) => (f >= b.at ? i : c), 0);
  const t = f / fps;

  let y = pad;
  let lastGap = 0;
  const rows: React.ReactElement[] = [];
  const dots: { y: number; i: number }[] = [];
  beats.forEach((b, i) => {
    if (p[i] <= 0 && f < b.at) return;
    const it = items[i];
    const bi = big[i];
    const height = p[i] * it.Hc + bi * (it.Hb - it.Hc);
    const cDotY = y + (cs * 1.32) / 2;
    const bDotY = y + it.chipH + (it.bs * 1.2) / 2;
    dots.push({ y: cDotY + (bDotY - cDotY) * (bi / Math.max(0.001, p[i])), i });
    const collapsing = i + 1 < n && f >= beats[i + 1].at;
    // A collapsing beat clears out in the first half of the change and shrinks toward its compact size, so it never
    // ghosts over the beat that replaces it.
    const compactOp = collapsing ? Math.min(1, Math.max(0, (0.45 - bi) / 0.35)) : 0;
    const bigOp = collapsing ? Math.max(0, (bi - 0.55) / 0.45) : Math.min(1, p[i] * 1.4);
    const bigScale = collapsing ? cs / it.bs + (1 - cs / it.bs) * bi : 0.94 + 0.06 * Math.min(1, bi);
    const rise = collapsing ? 0 : (1 - p[i]) * 22 * u;
    const chip = chips[i];
    rows.push(
      <div key={"c" + i} style={{ position: "absolute", left: textX, top: y, width: textW, opacity: compactOp, display: "flex", alignItems: "flex-start" }}>
        {b.when ? (
          <div style={{ width: whenCol, flex: "none", fontFamily: FONTS.sans, fontWeight: 700, fontSize: WHEN_SIZE, lineHeight: `${WHEN_SIZE * 1.2}px`,
            paddingTop: (cs * 1.32 - WHEN_SIZE * 1.2) / 2, color: b.hot ? accent : dimInk, whiteSpace: "pre" }}>{whenLines[i].join("\n")}</div>
        ) : null}
        <div style={{ fontFamily: FONTS.sans, fontWeight: 600, fontSize: cs, lineHeight: 1.32, color: dimInk, whiteSpace: "pre" }}>{it.cLines.join("\n")}</div>
      </div>,
    );
    if (bigOp > 0.01) {
      rows.push(
        <div key={"b" + i} style={{ position: "absolute", left: textX, top: y, width: textW, opacity: bigOp,
          transform: `translateY(${rise}px) scale(${bigScale})`, transformOrigin: "0 0" }}>
          {b.when ? (
            <div style={{ display: "inline-block", fontFamily: FONTS.sans, fontWeight: 800, fontSize: chip.size, lineHeight: 1.15,
              padding: `${chip.size * 0.25}px ${chip.size * chipPadX}px`, borderRadius: chip.size, whiteSpace: "pre",
              background: b.hot ? accent : ink, color: b.hot ? theme.snow : ground, marginBottom: chipGap }}>{chip.lines.join("\n")}</div>
          ) : null}
          <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: it.bs, lineHeight: 1.2, color: ink, whiteSpace: "pre" }}>{it.bLines.join("\n")}</div>
        </div>,
      );
    }
    lastGap = gap * p[i];
    y += height + lastGap;
  });
  const cardH = Math.min(H - top, y - lastGap + pad);
  const cardIn = p[0];
  const radius = 30 * u;

  // Rail: from the first dot down to the newest dot, growing with it.
  const firstY = dots.length ? dots[0].y : pad;
  const last = dots[dots.length - 1];
  const railEnd = last ? last.y : firstY;
  const flowLen = Math.max(1, railEnd - firstY);
  const flowY = firstY + ((t * 160 * u) % (flowLen + 120 * u)) - 60 * u;
  const pulse = 0.5 + 0.5 * Math.sin(t * 4);

  return (
    <div style={{ position: "absolute", width: w, height: H, transform: fitScale < 1 ? `scale(${fitScale})` : undefined, transformOrigin: "50% 0" }}>
      <div style={{ position: "absolute", left: 0, top, width: w, height: Math.max(pad * 2 + cs, cardH),
        transform: `translateY(${((1 - cardIn) * 30 + Math.sin(t * 1.3) * 3) * u}px)`, opacity: Math.min(1, cardIn * 1.5) }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: radius, background: cardBg,
          border: `${2 * u}px solid ${withAlpha(ink, dark ? 0.12 : 0.08)}`, boxSizing: "border-box",
          boxShadow: `0 ${18 * u}px ${44 * u}px rgba(20,14,8,${dark ? 0.45 : 0.2})` }} />
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: radius }}>
        <svg width={w} height={H}style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id={uid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={ink} stopOpacity="0" />
              <stop offset="0.5" stopColor={ink} stopOpacity={dark ? 0.55 : 0.4} />
              <stop offset="1" stopColor={ink} stopOpacity="0" />
            </linearGradient>
            <clipPath id={uid + "c"}><rect x={railX - 4 * u} y={firstY} width={8 * u} height={Math.max(0, railEnd - firstY)} /></clipPath>
          </defs>
          <line x1={railX} y1={firstY} x2={railX} y2={railEnd} stroke={railCol} strokeWidth={5 * u} strokeLinecap="round" />
          {railEnd - firstY > 30 * u ? (
            <rect x={railX - 2.5 * u} y={flowY - 30 * u} width={5 * u} height={60 * u} fill={`url(#${uid})`} clipPath={`url(#${uid}c)`} />
          ) : null}
          {dots.map(({ y: dy, i }) => {
            const isCur = i === cur;
            const col = beats[i].hot ? accent : isCur ? ink : withAlpha(ink, dark ? 0.5 : 0.4);
            const r = dotR * (isCur ? 1.25 : 0.85) * Math.min(1, p[i] * 1.2);
            return (
              <g key={i}>
                {isCur ? <circle cx={railX} cy={dy} r={r + (6 + 10 * pulse) * u} fill="none" stroke={col} strokeOpacity={0.45 * (1 - pulse)} strokeWidth={3 * u} /> : null}
                <circle cx={railX} cy={dy} r={r + 4 * u} fill={cardBg} />
                <circle cx={railX} cy={dy} r={r} fill={col} />
              </g>
            );
          })}
        </svg>
        {rows}
        </div>
      </div>
    </div>
  );
}
