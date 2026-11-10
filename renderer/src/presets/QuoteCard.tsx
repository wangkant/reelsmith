// One person's words typeset as a quote card: the speaker plate lands first, a quotation badge drops onto the corner,
// then the quote reveals phrase by phrase; hot substrings turn accent with a band sweeping under them.
import React, { useId } from "react";
import { useCurrentFrame } from "remotion";
import { ease, fit, FONTS, frameOr, numOr, onGround, springAt, textWidth, themeColor, useClip, withAlpha, words } from "@reelsmith/kit";

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

function Icon({ kind, fg, bg }: { kind: string; fg: string; bg: string }) {
  switch (kind) {
    case "shop":
      return (
        <g>
          <rect x="24" y="46" width="52" height="36" rx="5" fill={fg} />
          <path d="M18 34 H82 V42 Q82 50 74 50 Q66 50 66 42 Q66 50 58 50 Q50 50 50 42 Q50 50 42 50 Q34 50 34 42 Q34 50 26 50 Q18 50 18 42 Z" fill={fg} />
          <path d="M24 20 H76 L82 32 H18 Z" fill={fg} />
          <rect x="43" y="60" width="14" height="22" rx="3" fill={bg} />
          <rect x="29" y="58" width="9" height="9" rx="2" fill={bg} />
        </g>
      );
    case "company":
      return (
        <g>
          <rect x="22" y="16" width="38" height="68" rx="5" fill={fg} />
          <rect x="56" y="38" width="24" height="46" rx="4" fill={fg} />
          {[0, 1, 2, 3].map((r) => [0, 1].map((c) => (
            <rect key={`${r}${c}`} x={30 + c * 13} y={25 + r * 12} width="8" height="7" rx="1.5" fill={bg} />
          )))}
          {[0, 1].map((r) => <rect key={r} x="64" y={47 + r * 12} width="9" height="7" rx="1.5" fill={bg} />)}
        </g>
      );
    case "official":
      return (
        <g>
          <path d="M50 12 L88 32 H12 Z" fill={fg} />
          <rect x="16" y="34" width="68" height="6" rx="2" fill={fg} />
          {[0, 1, 2, 3].map((i) => <rect key={i} x={22 + i * 16} y="44" width="8" height="28" rx="3" fill={fg} />)}
          <rect x="12" y="75" width="76" height="9" rx="3" fill={fg} />
        </g>
      );
    case "phone":
      return (
        <g>
          <rect x="30" y="12" width="40" height="76" rx="10" fill={fg} />
          <rect x="35" y="22" width="30" height="50" rx="4" fill={bg} />
          <rect x="43" y="78" width="14" height="4" rx="2" fill={bg} />
        </g>
      );
    case "crowd":
      return (
        <g>
          <circle cx="26" cy="42" r="10" fill={fg} opacity="0.7" />
          <path d="M8 86 C8 66 15 58 26 58 C37 58 44 66 44 86 Z" fill={fg} opacity="0.7" />
          <circle cx="74" cy="42" r="10" fill={fg} opacity="0.7" />
          <path d="M56 86 C56 66 63 58 74 58 C85 58 92 66 92 86 Z" fill={fg} opacity="0.7" />
          <circle cx="50" cy="36" r="14" fill={fg} stroke={bg} strokeWidth="4" />
          <path d="M24 90 C24 64 35 54 50 54 C65 54 76 64 76 90 Z" fill={fg} stroke={bg} strokeWidth="4" />
        </g>
      );
    default:
      return (
        <g>
          <circle cx="50" cy="36" r="17" fill={fg} />
          <path d="M18 90 C18 66 31 57 50 57 C69 57 82 66 82 90 Z" fill={fg} />
        </g>
      );
  }
}

export default function QuoteCard({ props }: { props: any }) {
  const { w, h, fps, dur, theme, width, height } = useClip();
  const f = useCurrentFrame();
  const gid = "qc" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const u0 = Math.min(width, height) / 1080; // px at a 1080 short side -> this canvas
  if (!(w >= 200 * u0 && h >= 200 * u0)) return null;
  const quote = String(props?.quote ?? "").trim();
  if (!quote) return null;
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
  const who = String(props?.who ?? "").trim();
  const role = String(props?.role ?? "").trim();
  const source = String(props?.source ?? "").trim();
  const icon = String(props?.icon ?? "person");

  // hot ranges, in reading order
  const hotR: [number, number][] = [];
  (Array.isArray(props?.hot) ? props.hot : []).forEach((x: any) => {
    const s = String(x ?? "");
    if (!s) return;
    for (let i = quote.indexOf(s); i >= 0; i = quote.indexOf(s, i + s.length)) {
      if (!hotR.some(([a, b]) => i < b && i + s.length > a)) hotR.push([i, i + s.length]);
    }
  });
  hotR.sort((p, q) => p[0] - q[0]);

  const chars = quote.replace(/\s/g, "").length;
  const latin = !CJK.test(quote);
  const short = latin ? chars <= 16 : chars <= 8;
  const mid = latin ? chars <= 32 : chars <= 16;
  const qm = (s: number) => (t: string) => textWidth(t, s, FONTS.serif, 700);

  // the whole layout at a unit size u (u0 x a fill factor): the card grows to its box, the quote up to a ceiling
  // that a short one never passes, the labels within their own ceilings so the quote stays the largest thing
  const build = (u: number) => {
    // the card hugs a text column of at most 1040 px and centres in the box
    const innerW = Math.min(w - 96 * u, 1040 * u);
    const pad = Math.min((w - innerW) / 2, 64 * u);
    const cardW = innerW + pad * 2;
    const cardLeft = (w - cardW) / 2;
    const maxS = Math.round(Math.min((short ? 112 : mid ? 92 : 80) * u, (short ? 124 : 104) * u0, innerW / 5));

    // a roomy spacing first, a compact one when the quote would drop under the floor
    const plan = (compact: boolean, floor: number) => {
      const padY = compact ? 40 * u : Math.max(44 * u, pad * 0.9);
      const badge = Math.round(Math.max(92 * u, Math.min((compact ? 108 : 136) * u, cardW * 0.17)));
      const av = compact ? 84 * u : Math.round(Math.max(92 * u, Math.min(112 * u, cardW * 0.14)));
      const gap = (compact ? 20 : 26) * u;
      // the badge's lower half reaches into the plate row: the name keeps clear of all of it, the role of half
      const textW = innerW - av - gap - badge * 0.5;
      const nameW = innerW - av - gap - badge - 12 * u;
      const name = fitWrap(who, nameW, Math.min(52 * u, 60 * u0), 40 * u0, FONTS.sans, 800);
      const roleF = fitWrap(role, textW, Math.min(36 * u, 42 * u0), 34 * u0, FONTS.sans, 500);
      const textH = name.lines.length * name.size * 1.22 + roleF.lines.length * roleF.size * 1.3 + (who && role ? 4 * u : 0);
      const plateH = Math.max(av, textH);
      const src = fitWrap(source, innerW - 52 * u, Math.min(34 * u, 38 * u0), 32 * u0, FONTS.sans, 500);
      const srcH = src.lines.length * src.size * 1.4;
      const gapA = (compact ? 22 : 38) * u;
      const gapB = source ? (compact ? 16 : 30) * u : 0;
      const lh = compact ? 1.3 : 1.4;
      const overhang = Math.round(badge * 0.42);
      const budget = h - overhang - padY * 2 - plateH - gapA - gapB - srcH;
      const maxLines = compact ? 8 : 6;
      // the largest size that fits, unless one at most 12% smaller breaks more cleanly (no split compounds, more
      // breaks at punctuation)
      let pick: { s: number; L: Wrap } | null = null;
      let first = 0;
      for (let s = maxS; s >= floor; s -= 2 * u0) {
        if (first && s < first * 0.88) break;
        const L = wrap(quote, innerW, qm(s), hotR);
        if (L.over || L.lines.length > maxLines || L.lines.length * s * lh > budget) continue;
        if (!first) first = s;
        if (!pick || (+L.bad - +pick.L.bad || L.ugly - pick.L.ugly || L.soft - pick.L.soft) < 0) pick = { s, L };
      }
      return { padY, badge, av, gap, name, roleF, plateH, src, srcH, gapA, gapB, lh, overhang, pick };
    };
    return { u, innerW, pad, cardW, cardLeft, plan };
  };
  let B = build(u0);
  let P = B.plan(false, 48 * u0);
  for (const k of [1.3, 1.22, 1.14, 1.07]) {
    const b = build(u0 * k);
    const p = b.plan(false, 48 * u0);
    // a larger card only while the quote stays well above the name and its last line is no stub
    const L = p.pick?.L.lines;
    const stub = !!L && L.length > 1 && textWidth(quote.slice(...L[L.length - 1]).trim(), p.pick!.s, FONTS.serif, 700) < b.innerW * 0.5;
    if (p.pick && !stub && p.pick.s >= p.name.size * 1.2 && p.pick.s >= (P.pick?.s ?? 0)) {
      B = b;
      P = p;
      break;
    }
  }
  if (!P.pick) P = B.plan(true, 44 * u0);
  const { u, innerW, pad, cardW, cardLeft } = B;
  const qSize = P.pick ? P.pick.s : 40 * u0;
  const lines = P.pick ? P.pick.L.lines : wrap(quote, innerW, qm(40 * u0), hotR).lines;
  const { padY, badge, av, gap, name, roleF, plateH, src, srcH, gapA, gapB, lh, overhang } = P;
  const quoteH = lines.length * qSize * lh;
  const cardH = padY * 2 + plateH + gapA + quoteH + gapB + srcH;
  const fullH = overhang + cardH;
  // last resort when even the compact plan is too tall (the longest quote, name, role and source); 1.012 leaves room for the drift
  const fitScale = fullH > h ? h / (fullH * 1.012) : 1;
  // the card scales about 40 % of its height, so its top moves down by 0.4 x the height it loses
  const top = (h - fullH * fitScale) / 2 - 0.4 * fullH * (1 - fitScale);

  // phrases: each ends after a run of punctuation (Latin punctuation only before a space, so "2,700" stays whole)
  const starts: number[] = [0];
  for (let i = 0; i < quote.length - 1; i++) {
    const c = quote[i], next = quote[i + 1];
    if (!CLOSE.includes(c) || CLOSE.includes(next)) continue;
    if (/[,.!?;:%)\u2019\u201d]/.test(c) && !/\s/.test(next)) continue;
    starts.push(i + 1);
  }
  const phraseOf = (i: number) => { let p = 0; while (p + 1 < starts.length && starts[p + 1] <= i) p++; return p; };
  const qAt = at + fr(12);
  const tail = Math.round(1.6 * fps); // the source and a short hold must fit inside the clip
  const perChar = latin ? 0.05 : 0.11;
  const overWant = Math.round(Math.max(0.6, Math.min(7, numOr(props?.over, Math.min(4.5, chars * perChar)))) * fps);
  const overF = Math.max(6, Math.min(overWant, dur - qAt - tail));
  const phraseAt = starts.map((s) => qAt + Math.round((overF * s) / quote.length));
  const phraseT = phraseAt.map((a) => springAt(f, a, { fps, durationInFrames: fr(12) }));
  const sweepF = fr(14);
  const hotAt = hotR.map(([, b]) => phraseAt[phraseOf(b - 1)] + fr(10));
  const hotP = hotR.map((_, i) => ease(f, hotAt[i], hotAt[i] + sweepF));

  const cardIn = springAt(f, at, { fps, durationInFrames: fr(12) });
  const plateIn = springAt(f, at + fr(3), { fps, durationInFrames: fr(12) });
  const badgeIn = springAt(f, at + fr(6), { fps, damping: 14, durationInFrames: fr(14) });
  const srcAt = Math.min(qAt + overF + fr(6), Math.max(qAt, dur - Math.round(1.2 * fps)));
  const srcIn = springAt(f, srcAt, { fps, durationInFrames: fr(12) });
  // the card grows down line by line as the quote reveals, then to the source line, so it never shows empty rows
  const lineIn = lines.map(([off]) => springAt(f, phraseAt[phraseOf(off)] - fr(3), { fps, durationInFrames: fr(10) }));
  const srcGrow = source ? springAt(f, srcAt - fr(3), { fps, durationInFrames: fr(10) }) : 1;
  const cardVis = cardH - (gapB + srcH) * (1 - srcGrow) - lineIn.reduce((s, t) => s + (1 - t) * qSize * lh, 0);
  const life = (f - at) * (30 / fps);
  const drift = 1 + 0.012 * ease(f, at, at + Math.max(30, Math.round(8 * fps)));
  const breathe = 0.5 + 0.5 * Math.sin(life / 14);
  const avBg = dark ? theme.snow : theme.ink;
  const avFg = dark ? theme.night : "#FFFBF3";
  const plateTop = overhang + padY;
  const quoteTop = plateTop + plateH + gapA;
  const left = cardLeft + pad;

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{
        position: "absolute", left: 0, top, width: w, height: fullH, transformOrigin: "50% 40%",
        transform: `scale(${fitScale * (0.96 + 0.04 * cardIn) * drift}) translateY(${(1 - cardIn) * 24 * u}px)`, opacity: cardIn,
      }}>
        <div style={{
          position: "absolute", left: cardLeft, top: overhang, width: cardW, height: cardVis, borderRadius: 34 * u, background: cardBg,
          border: `${1.5 * u}px solid ${dark ? withAlpha(theme.snow, 0.12) : withAlpha(theme.ink, 0.07)}`,
          boxShadow: `0 ${24 * u}px ${60 * u}px rgba(20,14,8,0.30), 0 ${3 * u}px ${10 * u}px rgba(20,14,8,0.14)`,
        }} />
        {/* quotation badge hanging off the top-right corner */}
        <svg width={badge} height={badge} viewBox="0 0 100 100" style={{
          position: "absolute", left: cardLeft + cardW - pad - badge, top: overhang - badge * 0.5, overflow: "visible", opacity: badgeIn,
          transform: `translateY(${Math.sin(life / 32) * 5 * u}px) rotate(${Math.sin(life / 46) * 3 - 8 * (1 - badgeIn)}deg) scale(${0.6 + 0.4 * badgeIn})`,
        }}>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#E7BC5C" />
              <stop offset="1" stopColor={theme.gold} />
            </linearGradient>
          </defs>
          <circle cx="50" cy="54" r="46" fill="rgba(20,14,8,0.22)" />
          <circle cx="50" cy="50" r="46" fill={`url(#${gid})`} />
          {[0, 25].map((dx) => (
            <path key={dx} transform={`translate(${22 + dx} 26) scale(0.6)`} fill={theme.ink}
              d="M26 37 C36.5 37 45 45.5 45 56 C45 66.5 36.5 75 26 75 C15.5 75 7 66.5 7 56 C6 30 18 12 40 4 L44 12 C30 20 23 30 24 37.1 C24.7 37 25.3 37 26 37 Z" />
          ))}
        </svg>
        {/* speaker plate */}
        <div style={{
          position: "absolute", left, top: plateTop, height: plateH, display: "flex", alignItems: "center", gap,
          opacity: plateIn, transform: `translateX(${(1 - plateIn) * -40 * u}px)`,
        }}>
          <div style={{ position: "relative", width: av, height: av, flex: "none" }}>
            <div style={{
              position: "absolute", inset: (-6 - 5 * breathe) * u, borderRadius: "50%",
              border: `${3 * u}px solid ${withAlpha(dark ? theme.snow : theme.ink, 0.08 + 0.1 * (1 - breathe))}`,
            }} />
            <svg width={av} height={av} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0 }}>
              <circle cx="50" cy="50" r="50" fill={avBg} />
              <g transform="translate(17 17) scale(0.66)"><Icon kind={icon} fg={avFg} bg={avBg} /></g>
            </svg>
          </div>
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: who && role ? 4 * u : 0 }}>
            {name.lines.map((nl, i) => (
              <div key={`n${i}`} style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: name.size, lineHeight: 1.22, color: ink, whiteSpace: "pre" }}>{nl}</div>
            ))}
            {roleF.lines.map((rl, i) => (
              <div key={`r${i}`} style={{ fontFamily: FONTS.sans, fontWeight: 500, fontSize: roleF.size, lineHeight: 1.3, color: muted, whiteSpace: "pre" }}>{rl}</div>
            ))}
          </div>
        </div>
        {/* the quote */}
        <div style={{ position: "absolute", left, top: quoteTop, width: innerW }}>
          {lines.map(([off, end0], li) => {
            const end = off + quote.slice(off, end0).trimEnd().length;
            const cuts = new Set<number>([off, end]);
            starts.forEach((s) => { if (s > off && s < end) cuts.add(s); });
            hotR.forEach(([a, b]) => { [a, b].forEach((c) => { if (c > off && c < end) cuts.add(c); }); });
            const cs = Array.from(cuts).sort((x, y) => x - y);
            return (
              <div key={li} style={{ height: qSize * lh, lineHeight: `${qSize * lh}px`, whiteSpace: "pre", fontFamily: FONTS.serif, fontWeight: 700, fontSize: qSize, color: ink }}>
                {cs.slice(0, -1).map((a, k) => {
                  const b = cs[k + 1];
                  const t = phraseT[phraseOf(a)];
                  const style: React.CSSProperties = { display: "inline-block", opacity: t, transform: `translateY(${(1 - t) * 18 * u}px)` };
                  const hi = hotR.findIndex(([x, y]) => a >= x && a < y);
                  if (hi >= 0) {
                    const [x, y] = hotR[hi];
                    const sp = Math.max(0, Math.min(1, (hotP[hi] * (y - x) - (a - x)) / (b - a)));
                    const band = withAlpha(hotColor, dark ? 0.36 : 0.18);
                    if (hotP[hi] > 0) style.color = hotColor;
                    style.backgroundImage = `linear-gradient(${band}, ${band})`;
                    style.backgroundRepeat = "no-repeat";
                    style.backgroundSize = `${sp * 100}% ${latin ? 0.3 : 0.34}em`;
                    style.backgroundPosition = latin ? "0 92%" : "0 84%";
                    style.lineHeight = 1.25;
                  }
                  return <span key={k} style={style}>{quote.slice(a, b)}</span>;
                })}
              </div>
            );
          })}
        </div>
        {source ? (
          <div style={{
            position: "absolute", left, top: overhang + cardH - padY - srcH, height: srcH, display: "flex", alignItems: "center", gap: 16 * u,
            opacity: srcIn, transform: `translateY(${(1 - srcIn) * 10 * u}px)`,
          }}>
            <div style={{ width: 36 * u * srcIn, height: 3 * u, borderRadius: 2 * u, background: muted, flex: "none" }} />
            <div style={{ fontFamily: FONTS.sans, fontWeight: 500, fontSize: src.size, lineHeight: 1.4, color: muted, whiteSpace: "pre" }}>{src.lines.join("\n")}</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
