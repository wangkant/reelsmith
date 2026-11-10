// Two versions of the same thing side by side (what they say / what the filing says). Each panel lands with its title,
// then its lines one by one; at strike_at one side is crossed out, at pick_at one side lifts with an accent edge.
import React from "react";
import { useCurrentFrame } from "remotion";
import { breakLines, FONTS, frameOr, onGround, springAt, textWidth, themeColor, useClip, withAlpha, words } from "@reelsmith/kit";

type Line = { text: string; at?: any };
type Side = { title: string; tag?: string; lines: Line[] };
type Row = { text: string; line: number; first: boolean };

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

/** Width at 100 px of the widest unbreakable word. */
const widestWord = (text: string, family: string, weight: number | string = 400) =>
  Math.max(1, ...words(text).filter((s) => s.trim()).map((s) => textWidth(s, 100, family, weight)));

function sideOf(v: any): Side {
  const s = v && typeof v === "object" ? v : {};
  const lines = Array.isArray(s.lines) ? s.lines.filter((l: any) => l && String(l.text ?? "").trim()).slice(0, 3) : [];
  return { title: String(s.title ?? "").trim(), tag: s.tag ? String(s.tag).trim() : "", lines };
}

export default function Versus({ props }: { props: any }) {
  const { w, h, fps, theme, width, height } = useClip();
  const f = useCurrentFrame();
  const u = Math.min(width, height) / 1080; // 1 at a 1080 px short side
  if (!(w >= 200 * u && h >= 200 * u)) return null;

  const TITLE_MAX = 72 * u;
  const TITLE_MIN = 52 * u;
  const TEXT_FLOOR = 40 * u;
  const TAG_SIZE = 34 * u;

  const g = onGround(theme, props.ground);
  const dark = g.dark;
  const cols = props.layout === "columns";
  const accent = themeColor(theme, props.color, "accent");
  const sides = [sideOf(props.a), sideOf(props.b)];

  // Timing: panel a, its lines, then panel b, its lines (each line no earlier than its panel).
  const step = Math.round(0.45 * fps);
  const aAt = frameOr(props.a_at, 0);
  const lineAts: number[][] = [[], []];
  sides[0].lines.forEach((l, i) => lineAts[0].push(Math.max(aAt + 6, frameOr(l.at, aAt + 10 + i * step))));
  const aLast = lineAts[0].length ? lineAts[0][lineAts[0].length - 1] : aAt;
  const bAt = frameOr(props.b_at, aLast + Math.round(0.6 * fps));
  sides[1].lines.forEach((l, i) => lineAts[1].push(Math.max(bAt + 6, frameOr(l.at, bAt + 10 + i * step))));
  const panelAts = [aAt, bAt];
  const bLast = lineAts[1].length ? lineAts[1][lineAts[1].length - 1] : bAt;
  const strikeSide = props.strike === "a" ? 0 : props.strike === "b" ? 1 : -1;
  const pickSide = props.pick === "a" ? 0 : props.pick === "b" ? 1 : -1;
  const strikeAt = strikeSide < 0 ? Infinity : frameOr(props.strike_at, bLast + Math.round(0.8 * fps));
  const pickAt = pickSide < 0 ? Infinity : frameOr(props.pick_at, bLast + Math.round(0.8 * fps));
  if (f < Math.min(aAt, bAt)) return null;

  // Geometry for one line size; `tight` trims padding and gaps for small boxes.
  const bar = 10 * u; // accent edge width, reserved on every panel so the text never moves
  const bulletW = 34 * u;
  const tagGap = 14 * u;
  const geo = (size: number, tight: boolean, W = w) => {
    const gap = cols ? Math.max(28 * u, W * 0.04) : tight ? 30 * u : Math.max(40 * u, h * 0.05);
    const pw = cols ? (W - gap) / 2 : W;
    const pad = Math.round(tight ? Math.max(22 * u, Math.min(32 * u, pw * 0.05)) : Math.max(26 * u, Math.min(44 * u, pw * 0.07)));
    const textX = pad + bar;
    const textW = pw - textX - pad;
    const titles = sides.map((s) => {
      const tagW = s.tag ? textWidth(s.tag, TAG_SIZE, FONTS.sans, 700) + TAG_SIZE * 1.1 + tagGap : 0;
      // a tag that would leave the title under half the row goes under it
      const tagBelow = !!s.tag && (cols || tagW > textW * 0.5);
      const room = tagBelow ? textW : textW - tagW;
      const one = (room * 100) / Math.max(1, textWidth(s.title, 100, FONTS.display));
      const tmin = tight ? 44 * u : TITLE_MIN;
      // a title is a label: never larger than the points under it
      const tmax = tight ? TITLE_MIN + 4 * u : Math.max(TITLE_MIN, Math.min(TITLE_MAX, size * 0.92));
      let tsize = Math.max(tmin, Math.min(tmax, Math.floor(one)));
      if (textWidth(s.title, tsize, FONTS.display) <= room) return { size: tsize, lines: [s.title], tagW, tagBelow };
      // wraps between words; a long word shrinks the title (to the text floor) before it is cut
      tsize = Math.max(TEXT_FLOOR, Math.min(tmin, Math.floor((room * 100) / widestWord(s.title, FONTS.display))));
      return { size: tsize, lines: wrap(s.title, room, (t) => textWidth(t, tsize, FONTS.display)), tagW, tagBelow };
    });
    const titleBlock = (i: number) =>
      titles[i].lines.length * titles[i].size * 1.18 + (titles[i].tagBelow ? TAG_SIZE * 1.7 + 10 * u : 0);
    const lineTextW = textW - bulletW;
    const rows = sides.map((s) =>
      s.lines.flatMap((l, li) => wrap(String(l.text).trim(), lineTextW, (t) => textWidth(t, size, FONTS.sans, 700))
        .map((text, k): Row => ({ text, line: li, first: k === 0 }))));
    const lh = size * 1.3;
    const lineGap = size * (tight ? 0.22 : 0.4);
    const ruleGap = size * (tight ? 0.45 : 0.7);
    const bodyInset = size * (tight ? 0.35 : 0.55);
    const heights = rows.map((r, i) => {
      const nLines = sides[i].lines.length;
      const body = r.length * lh + Math.max(0, nLines - 1) * lineGap;
      return pad + titleBlock(i) + (nLines ? ruleGap + 2 * u + bodyInset : 0) + body + pad;
    });
    const need = cols ? Math.max(...heights) : heights[0] + heights[1] + gap;
    return { size, gap, pw, pad, textX, textW, titles, titleBlock, rows, lh, lineGap, ruleGap, bodyInset, heights, need };
  };
  // Bounded search: roomy layout first (fewest wrapped rows, then the largest size), then a tight one; when even the
  // tight floor does not fit, the group is laid out in a box as much larger as it needs (wider too, so the points take
  // fewer rows) and scaled down to this one.
  const maxLine = cols ? 60 : 80;
  let G: ReturnType<typeof geo> | null = null;
  for (const tight of [false, true]) {
    let best = Infinity;
    for (let s = tight ? 46 : maxLine; s >= (tight ? 40 : 44); s -= 2) {
      const lay = geo(s * u, tight);
      const rowsN = lay.rows[0].length + lay.rows[1].length;
      if (lay.need <= h && rowsN < best) { best = rowsN; G = lay; }
    }
    if (G) break;
  }
  let lay = G ?? geo(TEXT_FLOOR, true);
  let fitScale = 1;
  if (!G) {
    for (let k = 0.96; k >= 0.6; k -= 0.04) {
      lay = geo(TEXT_FLOOR, true, w / k);
      fitScale = k;
      if (lay.need <= h / k) break;
    }
    fitScale = Math.min(fitScale, h / lay.need);
  }
  const W = w / fitScale;
  const H = h / fitScale;
  const { size, gap, pw, pad, textX, textW, titles, titleBlock } = lay;
  const tall = Math.max(...lay.heights);
  const phs = cols ? [tall, tall] : lay.heights;
  const groupH = cols ? tall : phs[0] + phs[1] + gap;
  const top0 = (H - groupH) / 2;
  const origin = (i: number) => (cols ? { x: i * (pw + gap), y: top0 } : { x: 0, y: top0 + (i ? phs[0] + gap : 0) });

  // Colours: side a is the muted "claim" card, side b the bright "fact" card.
  const ink = g.ink;
  const ground = dark ? theme.night : theme.paper;
  const cardBg = dark ? [mix(theme.night, theme.snow, 0.03), mix(theme.night, theme.snow, 0.17)]
    : [mix(theme.paper, theme.ink, 0.07), mix(theme.paper, "#FFFFFF", 0.75)];
  const softInk = dark ? withAlpha(theme.snow, 0.72) : mix(theme.ink, theme.paper, 0.2);
  const titleCol = [dark ? withAlpha(theme.snow, 0.7) : withAlpha(theme.ink, 0.72), ink];
  const lineCol = [softInk, ink];
  const border = withAlpha(ink, dark ? 0.12 : 0.1);
  const radius = 30 * u;
  const t = f / fps;

  const panel = (i: number) => {
    const s = sides[i];
    const at = panelAts[i];
    if (f < at) return null;
    const { x, y } = origin(i);
    const pin = springAt(f, at, { fps, damping: 15, durationInFrames: 13 });
    const pk = pickSide === i ? springAt(f, pickAt, { fps, damping: 14, durationInFrames: 12 }) : 0;
    const sk = strikeSide === i ? springAt(f, strikeAt, { fps, damping: 200, durationInFrames: 12 }) : 0;
    const float = Math.sin(t * 1.4 + i * 1.7) * 3 * u;
    const tt = titles[i];
    const rows = lay.rows[i];
    const bodyTop = pad + titleBlock(i) + lay.ruleGap;
    // the card grows down to each point as it lands: no empty body waits for its first line
    let rowsDone = 0;
    let visH = pad + titleBlock(i) + pad;
    s.lines.forEach((_, li) => {
      rowsDone += rows.filter((r) => r.line === li).length;
      const end = li === s.lines.length - 1 ? phs[i] : bodyTop + 2 * u + lay.bodyInset + rowsDone * lay.lh + li * lay.lineGap + pad;
      visH += (end - visH) * springAt(f, lineAts[i][li] - 3, { fps, durationInFrames: 10 });
    });
    const ruleIn = s.lines.length ? springAt(f, lineAts[i][0] - 3, { fps, durationInFrames: 10 }) : 0;
    const shadow = pk > 0
      ? `0 ${(18 + 14 * pk) * u}px ${(44 + 20 * pk) * u}px rgba(20,14,8,${0.22 + 0.12 * pk})`
      : `0 ${16 * u}px ${40 * u}px rgba(20,14,8,${dark ? 0.4 : 0.16})`;
    const lift = -14 * u * pk;
    const dim = 1 - 0.52 * sk;

    // Strike geometry: one stroke per text row, drawn left to right in sequence.
    const strikes: React.ReactElement[] = [];
    if (sk > 0) {
      const rowsY = rows.map((r, k) => bodyTop + 2 * u + lay.bodyInset + k * lay.lh + r.line * lay.lineGap + lay.lh / 2);
      const drawDur = Math.round(0.28 * fps);
      rows.forEach((r, k) => {
        const p = Math.max(0, Math.min(1, (f - strikeAt - k * 5) / drawDur));
        if (p <= 0) return;
        const x0 = textX + bulletW - 8 * u;
        const x1 = textX + bulletW + textWidth(r.text, size, FONTS.sans, 700) + 10 * u;
        const yy = rowsY[k] + 5 * u;
        strikes.push(<line key={k} x1={x0} y1={yy} x2={x0 + (x1 - x0) * p} y2={yy - 9 * u * p}
          stroke={accent} strokeWidth={Math.max(6 * u, size * 0.13)} strokeLinecap="round" />);
      });
      const tp = Math.max(0, Math.min(1, (f - strikeAt) / drawDur));
      tt.lines.forEach((tl, k) => {
        const yy = pad + (k + 0.55) * tt.size * 1.18 + 4 * u;
        const x0 = textX - 6 * u;
        const x1 = textX + textWidth(tl, tt.size, FONTS.display) + 8 * u;
        strikes.push(<line key={"t" + k} x1={x0} y1={yy} x2={x0 + (x1 - x0) * tp} y2={yy - 7 * u * tp}
          stroke={accent} strokeWidth={Math.max(6 * u, tt.size * 0.11)} strokeLinecap="round" />);
      });
    }

    const tagEl = s.tag ? (
      <div style={{
        fontFamily: FONTS.sans, fontWeight: 700, fontSize: TAG_SIZE, lineHeight: 1, whiteSpace: "pre",
        padding: `${TAG_SIZE * 0.28}px ${TAG_SIZE * 0.55}px`, borderRadius: 999,
        background: i === 0 ? withAlpha(ink, dark ? 0.14 : 0.1) : ink,
        color: i === 0 ? (dark ? withAlpha(theme.snow, 0.85) : softInk) : ground,
      }}>{s.tag}</div>
    ) : null;

    return (
      <div key={i} style={{
        position: "absolute", left: x, top: y, width: pw, height: phs[i],
        transform: `translateY(${(1 - pin) * 46 * u + lift + float}px) scale(${0.96 + 0.04 * pin})`,
        opacity: Math.min(1, pin * 1.4), transformOrigin: "50% 60%",
      }}>
        <div style={{
          position: "absolute", left: 0, top: 0, width: pw, height: visH, borderRadius: radius, background: cardBg[i], overflow: "hidden",
          boxShadow: shadow, border: `${2 * u}px solid ${pk > 0 ? withAlpha(accent, pk) : border}`, boxSizing: "border-box",
        }}>
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: bar + 2 * u, background: accent, opacity: pk * (0.85 + 0.15 * Math.sin(t * 3)) }} />
        </div>
        <div style={{ position: "absolute", inset: 0, opacity: dim }}>
          <div style={{ position: "absolute", left: textX, top: pad, width: textW, display: "flex", alignItems: tt.lines.length > 1 ? "flex-start" : "center", gap: tagGap }}>
            <div style={{ fontFamily: FONTS.display, fontSize: tt.size, lineHeight: 1.18, color: titleCol[i], whiteSpace: "pre" }}>{tt.lines.join("\n")}</div>
            {!tt.tagBelow && tagEl ? <div style={{ marginLeft: "auto", flex: "none" }}>{tagEl}</div> : null}
          </div>
          {tt.tagBelow && tagEl ? <div style={{ position: "absolute", left: textX, top: pad + tt.lines.length * tt.size * 1.18 + 10 * u }}>{tagEl}</div> : null}
          {rows.length ? (
            <div style={{ position: "absolute", left: textX, top: bodyTop, width: textW * ruleIn, height: 2 * u, background: withAlpha(ink, dark ? 0.14 : 0.12) }} />
          ) : null}
          {rows.map((r, k) => {
            const la = lineAts[i][r.line];
            if (f < la) return null;
            const p = springAt(f, la, { fps, damping: 14, durationInFrames: 11 });
            const yy = bodyTop + 2 * u + lay.bodyInset + k * lay.lh + r.line * lay.lineGap;
            const d = size * 0.3;
            return (
              <div key={k} style={{ position: "absolute", left: textX, top: yy, height: lay.lh, display: "flex", alignItems: "center",
                opacity: Math.min(1, p * 1.5), transform: `translateY(${(1 - p) * 18 * u}px)` }}>
                <div style={{ width: bulletW, flex: "none", display: "flex", alignItems: "center" }}>
                  {r.first ? (
                    <div style={{ width: d, height: d, borderRadius: d, boxSizing: "border-box",
                      background: i === 0 ? "transparent" : ink, border: i === 0 ? `${Math.max(3 * u, d * 0.22)}px solid ${lineCol[0]}` : "none" }} />
                  ) : null}
                </div>
                <div style={{ fontFamily: FONTS.sans, fontWeight: 700, fontSize: size, lineHeight: 1, color: lineCol[i], whiteSpace: "pre" }}>{r.text}</div>
              </div>
            );
          })}
        </div>
        {strikes.length ? (
          <svg width={pw} height={phs[i]} style={{ position: "absolute", inset: 0, overflow: "visible" }}>{strikes}</svg>
        ) : null}
      </div>
    );
  };

  // The VS badge sits in the gap once panel b has landed.
  const vsP = springAt(f, bAt, { fps, damping: 11, durationInFrames: 14 });
  const vsD = Math.min(96 * u, Math.max(72 * u, gap * 1.6));
  const vsC = cols ? { x: W / 2, y: top0 + tall / 2 } : { x: W / 2, y: top0 + phs[0] + gap / 2 };
  const breathe = 1 + 0.035 * Math.sin(t * 2.2);
  const vs = f >= bAt ? (
    <div style={{
      position: "absolute", left: vsC.x - vsD / 2, top: vsC.y - vsD / 2, width: vsD, height: vsD, borderRadius: vsD,
      background: ink, color: ground, display: "flex",
      alignItems: "center", justifyContent: "center", fontFamily: FONTS.display, fontSize: vsD * 0.42, whiteSpace: "pre",
      boxShadow: `0 0 0 ${vsD * 0.09}px ${ground}, 0 ${10 * u}px ${24 * u}px rgba(20,14,8,0.28)`,
      transform: `scale(${vsP * breathe}) rotate(${(1 - vsP) * -30}deg)`,
    }}>VS</div>
  ) : null;

  return (
    <div style={{ position: "absolute", width: W, height: H, transform: fitScale < 1 ? `scale(${fitScale})` : undefined, transformOrigin: "0 0" }}>
      {panel(0)}
      {panel(1)}
      {vs}
    </div>
  );
}
