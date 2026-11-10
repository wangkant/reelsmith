// A news report retold as a brief card: a "source · date" kicker, the headline in the display face with a marker
// sweeping under hot words, a rule drawing across, then up to three points landing one by one.
import React from "react";
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, onGround, springAt, textWidth, themeColor, useClip, withAlpha, words } from "@reelsmith/kit";

// closing / opening punctuation kept with the word next to them: ，。！？；：、,.!?;:…—）)」』”’% and （(「『“‘
const CLOSE = "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001,.!?;:\u2026\u2014\uff09)\u300d\u300f\u201d\u2019%";
const OPEN = "\uff08(\u300c\u300e\u201c\u2018";
const HAN1 = /^\p{Script=Han}$/u;
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303f\uff00-\uffef]/u;
const PUNCT_RE = /[\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001,.!?;:\u2026\u2014\uff08\uff09()\u300c\u300d\u300e\u300f\u201c\u201d\u2018\u2019%\s]/g;
// digits and the Chinese numerals: a break inside a number is avoided
const NUM_END = /[0-9\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07\u4ebf\u4e24]\s*$/u;
const NUM_START = /^[0-9\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07\u4ebf\u4e24]/u;
const PREP = "\u4ece\u5728\u628a\u88ab\u5411\u7ed9\u5bf9\u548c\u4e0e\u8ddf\u6bd4\u5c06"; // Chinese prepositions: a line may start with these, never end on them

type Wrap = { lines: [number, number][]; bad: boolean; over: boolean; soft: number; ugly: number };

// Word tokens a line may break between: spaces stay with the word before them, Latin runs ("2,700", "don't",
// "Lagarde-Smith") stay whole, so Latin text breaks only at spaces and CJK keeps its word boundaries.
function tokens(text: string): string[] {
  const tk: string[] = [];
  for (const s of words(text)) {
    const prev = tk[tk.length - 1];
    if (prev === undefined) { tk.push(s); continue; }
    const last = prev.slice(-1);
    // a Latin run may still break after a hyphen ("Lagarde-" / "Smith")
    const latinRun = !/[\s-]/.test(last) && !/\s/.test(s[0]) && !CJK.test(last) && !CJK.test(s[0]);
    if (/^\s+$/.test(s) || latinRun || CLOSE.includes(s[0]) || OPEN.includes(last)) tk[tk.length - 1] = prev + s;
    else tk.push(s);
  }
  return tk;
}

// Line breaks at word boundaries, chosen for even lines; breaking after punctuation is preferred, and breaking
// between two one-character words (often a split compound) or inside an `avoid` range is penalised.
function wrap(text: string, width: number, measure: (s: string) => number, avoid: [number, number][]): Wrap {
  const m = (s: string) => measure(s.trimEnd());
  const tk = tokens(text);
  const n = tk.length;
  const pos = [0];
  tk.forEach((t) => pos.push(pos[pos.length - 1] + t.length));
  const brk = (k: number) => {
    const endCh = tk[k - 1].trimEnd().slice(-1);
    if (CLOSE.includes(endCh) && endCh !== "%") return -8; // after punctuation, but not after a percent sign
    let c = 0;
    const core = (t: string) => t.replace(PUNCT_RE, "");
    const s1 = HAN1.test(core(tk[k - 1])), s2 = HAN1.test(core(tk[k])) && !PREP.includes(tk[k]);
    // keep a Chinese particle (aspect, structural, sentence-final) off the start of a line, a preposition off the end
    if (/^[\u4e86\u7684\u7740\u8fc7\u5417\u5462\u5427\u554a\u4e48]/.test(tk[k]) || (s1 && PREP.includes(tk[k - 1]))) c += 45;
    else if (s1 && s2) c += 45;
    else if (s1 || s2) c += 20;
    // a break right after an aspect or structural particle is slightly preferred
    else if (/[\u7684\u4e86\u7740\u8fc7]$/.test(tk[k - 1])) c -= 4;
    if (NUM_END.test(tk[k - 1]) && NUM_START.test(tk[k])) c += 45; // not inside a number
    if (avoid.some(([a, b]) => pos[k] > a && pos[k] < b)) c += 35;
    return c;
  };
  const best = new Array(n + 1).fill(Infinity);
  const from = new Array(n + 1).fill(-1);
  best[0] = 0;
  for (let i = 1; i <= n; i++) {
    for (let j = i - 1; j >= 0; j--) {
      const lw = m(text.slice(pos[j], pos[i]));
      if (lw > width && i - j > 1) break;
      if (best[j] === Infinity) continue;
      const slack = Math.max(0, width - lw) / width;
      const c = 20 + (i === n ? (lw < width * 0.28 && j > 0 ? 30 : 0) : slack * slack * 60 + (lw < width * 0.45 ? 25 : 0)) + (j > 0 ? brk(j) : 0) + (lw > width ? 1000 : 0);
      if (best[j] + c < best[i]) { best[i] = best[j] + c; from[i] = j; }
    }
  }
  const lines: [number, number][] = [];
  let bad = false, over = false, soft = 0, ugly = 0;
  for (let i = n; i > 0; i = from[i]) {
    const j = from[i];
    lines.unshift([pos[j], pos[i]]);
    if (j > 0 && brk(j) >= 35) bad = true;
    if (j > 0 && brk(j) >= 0) soft++;
    if (j > 0) ugly += Math.max(0, brk(j));
    if (i < n && m(text.slice(pos[j], pos[i])) < width * 0.45) ugly += 20;
    if (m(text.slice(pos[j], pos[i])) > width + 0.5) over = true;
  }
  return { lines, bad, over, soft, ugly };
}

// Text at `max` px on one line, else shrunk to `floor`, else wrapped at `floor`; the font size and its lines.
function fitWrap(text: string, width: number, max: number, floor: number, family: string, weight: number) {
  if (!text) return { size: 0, lines: [] as string[] };
  const one = Math.min(max, fit(text, width, max, family, weight));
  if (one >= floor) return { size: one, lines: [text] };
  const W = wrap(text, width, (t) => textWidth(t, floor, family, weight), []);
  return { size: floor, lines: W.lines.map(([a, b]) => text.slice(a, b).trimEnd()) };
}

type Pt = { text: string; at: number; hot: boolean };

// the kicker's lead-in by the film's language: zh "<lead> X", ja "<lead>X", anything else "Source: X"
const LEAD_ZH = "\u636e ";
const LEAD_ZH_HANT = "\u64da ";
const LEAD_JA = "\u51fa\u5178\uff1a";
const leadIn = (locale?: string) => {
  const tag = String(locale || "en").toLowerCase();
  if (tag.startsWith("zh")) return /-(hant|tw|hk|mo)(-|$)/.test(tag) ? LEAD_ZH_HANT : LEAD_ZH;
  return tag.startsWith("ja") ? LEAD_JA : "Source: ";
};
// a source that already starts with a lead-in loses it, so the card never says it twice
const LEAD_RE = /^(source\s*:|\u636e|\u64da|\u51fa\u5178\s*[:\uff1a])\s*[:\uff1a]?\s*/i;

export default function NewsBrief({ props }: { props: any }) {
  const { w, h, fps, theme, locale, width, height } = useClip();
  const f = useCurrentFrame();
  const u = Math.min(width, height) / 1080; // px at a 1080 short side -> this canvas
  if (!(w >= 200 * u && h >= 200 * u)) return null;
  const headline = String(props?.headline ?? "").trim();
  if (!headline) return null;
  const at = frameOr(props?.at, 0);
  if (f < at) return null;
  const fr = (n: number) => Math.round((n * fps) / 30); // frame counts written for 30 fps

  const ground = onGround(theme, props?.ground);
  const dark = ground.dark;
  const ink = ground.ink;
  const muted = ground.muted;
  const cardBg = dark ? withAlpha(theme.night, 0.95) : "#FFFBF3";
  // the accent is too dark on the dark card, so it lifts there unless a colour is given
  const hotColor = dark && !props?.color ? "#F06A5D" : themeColor(theme, props?.color, "accent");
  const band = withAlpha(theme.gold, dark ? 0.6 : 0.5);
  const source = String(props?.source ?? "").trim().replace(LEAD_RE, "");
  const date = String(props?.date ?? "").trim();
  const srcText = source ? leadIn(locale) + source : "";

  const pts: Pt[] = (Array.isArray(props?.points) ? props.points : []).slice(0, 3)
    .map((p: any, i: number) => ({
      text: String(p?.text ?? "").trim(),
      at: Math.max(at + fr(16), frameOr(p?.at, at + fps + i * Math.round(0.8 * fps))),
      hot: !!p?.hot,
    }))
    .filter((p: Pt) => p.text);

  const hots: [number, number][] = [];
  (Array.isArray(props?.hot) ? props.hot : []).forEach((x: any) => {
    const s = String(x ?? "");
    const i = s ? headline.indexOf(s) : -1;
    if (i >= 0 && !hots.some(([a, b]) => i < b && i + s.length > a)) hots.push([i, i + s.length]);
  });
  hots.sort((p, q) => p[0] - q[0]);

  // the card hugs a text column of at most 1040 px and centres in the box
  const innerW = Math.min(w - 96 * u, 1040 * u);
  const pad = Math.min((w - innerW) / 2, 64 * u);
  const cardW = innerW + pad * 2;
  const cardLeft = (w - cardW) / 2;
  const left = cardLeft + pad;

  // kicker: "source · date" in one pill when it fits, else the date drops under it; a long source wraps in the pill
  const kSize = 30 * u;
  const dotD = 16 * u;
  const pillPadL = 18 * u, pillPadR = 24 * u, pillGap = 12 * u, pillPadY = 12 * u;
  const pillTextW = innerW - pillPadL - dotD - pillGap - pillPadR;
  const kSep = " \u00b7 ";
  const kWidth = (t: string) => textWidth(t, kSize, FONTS.sans, 700);
  const oneRow = srcText && date ? kWidth(srcText + kSep + date) <= pillTextW : true;
  const pillText = oneRow ? (srcText && date ? srcText + kSep + date : srcText || date) : srcText;
  const pillLines = pillText ? fitWrap(pillText, pillTextW, kSize, kSize, FONTS.sans, 700).lines : [];
  const dateBelow = !oneRow ? fitWrap(date, innerW - 6 * u, kSize, kSize, FONTS.sans, 500).lines : [];
  const kH = pillLines.length ? Math.max(54 * u, pillLines.length * kSize * 1.3 + pillPadY * 2) : 0;
  const kBlock = kH + (dateBelow.length ? 10 * u + dateBelow.length * kSize * 1.3 : 0);

  const chars = headline.replace(/\s/g, "").length;
  const latin = !CJK.test(headline);
  const maxH = Math.min((chars <= (latin ? 14 : 6) ? 132 : chars <= (latin ? 26 : 12) ? 108 : 96) * u, innerW / 4);
  const markW = 44 * u;
  const ptW = innerW - markW;
  const hm = (s: number) => (t: string) => textWidth(t, s, FONTS.display, 400);
  const plan = (compact: boolean) => {
    const padY = compact ? 40 * u : Math.max(46 * u, pad * 0.95);
    const gapK = kBlock ? (compact ? 18 : 30) * u : 0;
    const hlh = compact ? 1.12 : 1.18;
    const plh = compact ? 1.26 : 1.36;
    const ptGap = (compact ? 12 : 22) * u;
    const ruleGap = (compact ? 22 : 34) * u;
    const ruleBlock = pts.length ? ruleGap * 2 + 3 * u : 0;
    const hFloor = (compact ? 48 : 56) * u;
    const maxHL = compact ? 5 : chars >= (latin ? 32 : 16) ? 4 : 3;
    const maxPL = compact ? 3 : 2;
    const ptLay = (ps: number) => pts.map((p) => wrap(p.text, ptW, (t) => textWidth(t, ps, FONTS.sans, p.hot ? 700 : 500), []));
    let pick: { hs: number; H: Wrap; ps: number; P: Wrap[]; total: number } | null = null;
    let first = 0;
    for (let hs = Math.round(maxH); hs >= hFloor; hs -= 4 * u) {
      if (first && hs < first * 0.75) break;
      const H = wrap(headline, innerW, hm(hs), hots);
      if (H.over || H.lines.length > maxHL) continue;
      for (const ps of [44 * u, 42 * u, 40 * u]) {
        const P = ptLay(ps);
        if (P.some((l) => l.over || l.lines.length > maxPL)) continue;
        const pH = P.reduce((s, l) => s + l.lines.length * ps * plh, 0) + Math.max(0, P.length - 1) * ptGap;
        const total = padY * 2 + kBlock + gapK + H.lines.length * hs * hlh + ruleBlock + pH;
        if (total > h) continue;
        if (!first) first = hs;
        if (!pick || (+H.bad - +pick.H.bad || H.ugly - pick.H.ugly || H.soft - pick.H.soft) < 0) pick = { hs, H, ps, P, total };
        break;
      }
    }
    return { padY, gapK, hlh, plh, ptGap, ruleGap, pick };
  };
  let L = plan(false);
  if (!L.pick) L = plan(true);
  const fallback = () => {
    const hs = 48 * u, ps = 40 * u;
    const H = wrap(headline, innerW, hm(hs), hots);
    const P = pts.map((p) => wrap(p.text, ptW, (t) => textWidth(t, ps, FONTS.sans, p.hot ? 700 : 500), []));
    const pH = P.reduce((s, l) => s + l.lines.length * ps * L.plh, 0) + Math.max(0, P.length - 1) * L.ptGap;
    const total = L.padY * 2 + kBlock + L.gapK + H.lines.length * hs * L.hlh + (pts.length ? L.ruleGap * 2 + 3 * u : 0) + pH;
    return { hs, H, ps, P, total };
  };
  const pick = L.pick ?? fallback();
  const { padY, gapK, hlh, plh, ptGap, ruleGap } = L;
  const { hs, ps } = pick;
  const cardH = pick.total;
  const fitScale = cardH > h ? h / cardH : 1; // last resort only: the compact plan fits every box the meta allows
  const top = Math.max(0, (h - cardH * fitScale) / 2);

  const life = (f - at) * (30 / fps);
  const cardIn = springAt(f, at, { fps, durationInFrames: fr(12) });
  const kIn = springAt(f, at + fr(3), { fps, durationInFrames: fr(12) });
  const hAt = at + fr(8);
  const hIn = springAt(f, hAt, { fps, durationInFrames: fr(14) });
  const hotAt = hAt + fr(14);
  const totalHot = hots.reduce((s, [a, b]) => s + b - a, 0);
  const hotP = ease(f, hotAt, hotAt + Math.max(fr(12), Math.round(fr(totalHot * (latin ? 0.8 : 1.6)))));
  const ruleT = ease(f, at + fr(16), at + fr(32));
  const drift = 1 + 0.012 * ease(f, at, at + Math.max(30, Math.round(8 * fps)));
  const pulse = 0.5 + 0.5 * Math.sin(life / 9);

  // headline segments; the marker sweeps the hot ranges in reading order
  const hotDone = (c: number) => { let s = 0; for (const [a, b] of hots) { if (c <= a) break; s += Math.min(c, b) - a; } return s; };
  const headLines = pick.H.lines.map(([off, end0], li) => {
    const end = off + headline.slice(off, end0).trimEnd().length;
    const cuts = new Set<number>([off, end]);
    hots.forEach(([a, b]) => { [a, b].forEach((c) => { if (c > off && c < end) cuts.add(c); }); });
    const cs = Array.from(cuts).sort((x, y) => x - y);
    return (
      <div key={li} style={{ height: hs * hlh, lineHeight: `${hs * hlh}px`, whiteSpace: "pre" }}>
        {cs.slice(0, -1).map((a, k) => {
          const b = cs[k + 1];
          const style: React.CSSProperties = {};
          if (totalHot > 0 && hots.some(([x, y]) => a >= x && a < y)) {
            const sp = Math.max(0, Math.min(1, (hotP * totalHot - hotDone(a)) / (b - a)));
            style.backgroundImage = `linear-gradient(${band}, ${band})`;
            style.backgroundRepeat = "no-repeat";
            style.backgroundSize = `${sp * 100}% 0.4em`;
            style.backgroundPosition = "0 88%";
          }
          return <span key={k} style={style}>{headline.slice(a, b)}</span>;
        })}
      </div>
    );
  });

  const headTop = padY + kBlock + gapK;
  const ruleTop = headTop + pick.H.lines.length * hs * hlh + ruleGap;
  let y = ruleTop + 3 * u + ruleGap;
  const ptEls = pts.map((p, i) => {
    const lines = pick.P[i].lines.map(([a, b]) => p.text.slice(a, b).trimEnd());
    const top0 = y;
    y += lines.length * ps * plh + ptGap;
    if (f < p.at) return null;
    const t = springAt(f, p.at, { fps, durationInFrames: fr(12) });
    const sweep = p.hot ? ease(f, p.at + fr(12), p.at + fr(12 + 8 * lines.length)) : 0;
    const md = Math.round(ps * 0.42);
    const cy = (ps * plh) / 2;
    const ripple = ((f - p.at) / fps) % 1;
    return (
      <div key={i} style={{ position: "absolute", left, top: top0, width: innerW, opacity: t, transform: `translateY(${(1 - t) * 16 * u}px)` }}>
        {p.hot ? (
          <div style={{
            position: "absolute", left: 4 * u + md / 2 - md, top: cy - md, width: md * 2, height: md * 2, borderRadius: "50%",
            border: `${3 * u}px solid ${withAlpha(hotColor, 0.45 * (1 - ripple))}`, transform: `scale(${0.6 + 0.8 * ripple})`,
          }} />
        ) : null}
        <div style={{
          position: "absolute", left: 4 * u, top: cy - md / 2, width: md, height: md, borderRadius: p.hot ? md / 2 : 4 * u,
          background: p.hot ? hotColor : withAlpha(ink, 0.8), transform: `scale(${0.4 + 0.6 * t}) rotate(${p.hot ? 0 : 45}deg)`,
        }} />
        <div style={{ position: "absolute", left: markW, top: 0, width: ptW }}>
          {lines.map((ln, li) => (
            <div key={li} style={{
              height: ps * plh, lineHeight: `${ps * plh}px`, whiteSpace: "pre", fontFamily: FONTS.sans, fontWeight: p.hot ? 700 : 500, fontSize: ps, color: ink,
            }}>
              <span style={p.hot ? {
                backgroundImage: `linear-gradient(${band}, ${band})`, backgroundRepeat: "no-repeat",
                backgroundSize: `${Math.max(0, Math.min(1, sweep * lines.length - li)) * 100}% 0.4em`, backgroundPosition: "0 90%",
              } : undefined}>{ln}</span>
            </div>
          ))}
        </div>
      </div>
    );
  });

  const ringR = Math.min(cardW, cardH) * 0.36;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{
        position: "absolute", left: 0, top, width: w, height: cardH, transformOrigin: "50% 40%",
        transform: `scale(${fitScale * (0.96 + 0.04 * cardIn) * drift}) translateY(${(1 - cardIn) * 24 * u}px)`, opacity: cardIn,
      }}>
        <div style={{
          position: "absolute", left: cardLeft, top: 0, width: cardW, height: cardH, borderRadius: 34 * u, background: cardBg, overflow: "hidden",
          border: `${1.5 * u}px solid ${dark ? withAlpha(theme.snow, 0.12) : withAlpha(theme.ink, 0.07)}`,
          boxShadow: `0 ${24 * u}px ${60 * u}px rgba(20,14,8,0.30), 0 ${3 * u}px ${10 * u}px rgba(20,14,8,0.14)`,
        }}>
          {/* corner rings, turning slowly */}
          <svg width={ringR * 2} height={ringR * 2} style={{
            position: "absolute", right: -ringR * 0.8, bottom: -ringR * 0.8, transform: `rotate(${life * 0.25}deg)`,
          }}>
            {[0.98, 0.74, 0.5].map((k, i) => (
              <circle key={i} cx={ringR} cy={ringR} r={ringR * k - 2 * u} fill="none" stroke={withAlpha(theme.gold, dark ? 0.22 : 0.28)}
                strokeWidth={(i === 0 ? 3 : 2) * u} strokeDasharray={i === 1 ? `${6 * u} ${14 * u}` : undefined} />
            ))}
          </svg>
        </div>
        {pillLines.length ? (
          <div style={{
            position: "absolute", left, top: padY, height: kH, borderRadius: Math.min(kH / 2, 27 * u), display: "flex", alignItems: "center",
            gap: pillGap, padding: `0 ${pillPadR}px 0 ${pillPadL}px`, background: dark ? theme.snow : theme.ink,
            opacity: kIn, transform: `translateX(${(1 - kIn) * -30 * u}px)`,
          }}>
            <div style={{ position: "relative", width: dotD, height: dotD, flex: "none" }}>
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: theme.gold }} />
              <div style={{
                position: "absolute", inset: -7 * u * pulse, borderRadius: "50%", border: `${2 * u}px solid ${withAlpha(theme.gold, 0.7 * (1 - pulse))}`,
              }} />
            </div>
            <div style={{
              fontFamily: FONTS.sans, fontWeight: 700, fontSize: kSize, lineHeight: 1.3, color: dark ? theme.night : "#FFFBF3", whiteSpace: "pre",
            }}>{pillLines.join("\n")}</div>
          </div>
        ) : null}
        {dateBelow.length ? (
          <div style={{
            position: "absolute", left: left + 6 * u, top: padY + kH + 10 * u, fontFamily: FONTS.sans, fontWeight: 500, fontSize: kSize, lineHeight: 1.3,
            color: muted, whiteSpace: "pre", opacity: kIn,
          }}>{dateBelow.join("\n")}</div>
        ) : null}
        <div style={{
          position: "absolute", left, top: headTop, width: innerW, fontFamily: FONTS.display, fontSize: hs, color: ink,
          opacity: hIn, transform: `translateY(${(1 - hIn) * 22 * u}px)`,
        }}>{headLines}</div>
        {pts.length ? (
          <div style={{
            position: "absolute", left, top: ruleTop, width: innerW * ruleT, height: 3 * u, borderRadius: 2 * u, background: withAlpha(ink, 0.16),
          }} />
        ) : null}
        {ptEls}
      </div>
    </div>
  );
}
