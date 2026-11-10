// Who is involved and what passes between them. Party cards land one by one; links draw themselves card edge to card
// edge with an arrowhead and a label pill; money / people links keep coins or people flowing; cut_at breaks one.
import React, { useId, useMemo } from "react";
import { useCurrentFrame } from "remotion";
import { breakLines, ease, FONTS, frameOr, onGround, springAt, textWidth, themeColor, useClip, withAlpha } from "@reelsmith/kit";

type Pt = { x: number; y: number };
type Rect = { x: number; y: number; w: number; h: number };
type Party = { id: string; name: string; role?: string; icon?: string; at?: number; hot?: boolean };
type Link = { from: string; to: string; label?: string; flow?: string; at?: number; cut_at?: number };
type Block = { size: number; lines: string[] };
type Card = { rect: Rect; style: "v" | "h"; badge: number; name: Block; role: Block };
type Curve = { p0: Pt; c1: Pt; c2: Pt; p3: Pt; n3: Pt; arc: boolean; flat?: boolean; lean?: number };
type Routed = { curve: Curve; pts: Pt[]; cum: number[]; len: number; pill: Rect | null; slash: Pt; slashAng: number; strike: boolean };

const cl = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const ARROW = 26;
const GAP = 6;
// text floors in canvas px at a 1080 short side
const READ = 40;
const SMALL = 30;
// widest label pill (px at a 1080 short side): longer labels wrap to two lines so they fit between cards
const PILL = 300;

/** One line at `min`..`max` if it fits; else the largest size down to `floor` that wraps (word and CJK rules of
 *  breakLines) into at most `maxLines`; a single word too wide even then shrinks below the floor rather than overflow. */
function fitBlock(text: string, maxW: number, max: number, min: number, floor: number, weight: number, maxLines: number): Block {
  const s0 = text.trim();
  if (!s0 || maxW <= 0) return { size: 0, lines: [] };
  const lo = Math.min(min, floor);
  const hiMin = Math.max(min, floor);
  const hiMax = Math.max(max, hiMin);
  const one = Math.floor((maxW * 100) / Math.max(1, textWidth(s0, 100, FONTS.sans, weight)));
  if (one >= hiMin) return { size: Math.min(hiMax, one), lines: [s0] };
  const wrap = (s: number) => {
    const m = (x: string) => textWidth(x, s, FONTS.sans, weight);
    const lines = breakLines(s0, maxW, m, true).map((l) => l.trim()).filter(Boolean);
    return { lines, widest: Math.max(1, ...lines.map(m)) };
  };
  const bottom = Math.max(lo, floor);
  for (let s = hiMin; s >= bottom; s -= 2) {
    const { lines, widest } = wrap(s);
    if (lines.length <= maxLines && widest <= maxW) return { size: Math.max(s, Math.min(hiMax, Math.floor((s * maxW) / widest))), lines };
  }
  const { lines, widest } = wrap(bottom);
  return { size: widest > maxW ? Math.floor((bottom * maxW) / widest) : bottom, lines };
}

function measureCard(p: Party, style: "v" | "h", cw: number, badge: number, k: number): Omit<Card, "rect"> & { hgt: number } {
  const padX = style === "v" ? 20 : 26;
  const textW = style === "v" ? cw - padX * 2 : cw - padX * 2 - badge - 24;
  const name = fitBlock(String(p.name ?? ""), textW, 60, 48, READ / k, 800, 2);
  const role = fitBlock(String(p.role ?? ""), textW, 40, 34, SMALL / k, 500, 2);
  const nameH = name.lines.length * name.size * 1.16;
  const roleH = role.lines.length ? 8 + role.lines.length * role.size * 1.24 : 0;
  const hgt = style === "v" ? 26 + badge + 14 + nameH + roleH + 26 : Math.max(badge + 48, nameH + roleH + 52);
  return { style, badge, name, role, hgt };
}

// rowGap: room a labelled link between two side-by-side cards needs, so it can run straight with its label in the gap
function layoutCards(parties: Party[], mode: string, X0: number, Y0: number, IW: number, IH: number, hasLinks: boolean, rowGap: number, k: number): { cards: Card[]; ok: boolean } {
  const n = parties.length;
  const rg = rowGap / k;
  const scales = [1, 0.9, 0.8];
  let out: Card[] = [];
  let ok = false;
  for (const s of scales) {
    out = [];
    if (mode === "column") {
      const badge = Math.round(Math.min(120, IW * 0.17) * s);
      const ms = parties.map((p) => measureCard(p, "h", IW, badge, k));
      const hc = Math.max(...ms.map((m) => m.hgt));
      const step = n > 1 ? (IH - hc) / (n - 1) : 0;
      ms.forEach((m, i) => out.push({ ...m, rect: { x: X0, y: n > 1 ? Y0 + i * step : Y0 + (IH - hc) / 2, w: IW, h: hc } }));
      ok = n * hc + (n - 1) * (hasLinks ? 120 : 40) <= IH;
      if (n * hc + (n - 1) * (hasLinks ? 170 : 60) <= IH) break;
    } else if (mode === "row") {
      const gap = n === 2 ? Math.max(IW * 0.34, Math.min(rg, IW * 0.5)) : IW * 0.14;
      const cw = (IW - gap * (n - 1)) / n;
      const badge = Math.round(Math.min(120, cw * 0.44) * s);
      const ms = parties.map((p) => measureCard(p, "v", cw, badge, k));
      const hc = Math.max(...ms.map((m) => m.hgt));
      ms.forEach((m, i) => out.push({ ...m, rect: { x: X0 + i * (cw + gap), y: Y0 + (IH - hc) / 2, w: cw, h: hc } }));
      ok = hc <= IH * 0.72;
      if (hc <= IH * 0.56) break;
    } else if (mode === "triangle") {
      const tw = IW * 0.66;
      const bw = Math.min(IW * 0.39, (IW - Math.min(rg, IW * 0.34)) / 2);
      const badgeT = Math.round(Math.min(116, tw * 0.25) * s);
      const badgeB = Math.round(Math.min(112, bw * 0.34) * s);
      const top = measureCard(parties[0], "h", tw, badgeT, k);
      const bs = parties.slice(1).map((p) => measureCard(p, "v", bw, badgeB, k));
      const hb = Math.max(...bs.map((m) => m.hgt));
      out.push({ ...top, rect: { x: X0 + (IW - tw) / 2, y: Y0, w: tw, h: top.hgt } });
      bs.forEach((m, i) => out.push({ ...m, rect: { x: i === 0 ? X0 : X0 + IW - bw, y: Y0 + IH - hb, w: bw, h: hb } }));
      ok = top.hgt + hb + 170 <= IH;
      if (top.hgt + hb + 230 <= IH) break;
    } else {
      const gx = Math.max(IW * 0.26, Math.min(rg, IW * 0.34));
      const cw = (IW - gx) / 2;
      const badge = Math.round(Math.min(96, cw * 0.32) * s);
      const ms = parties.map((p) => measureCard(p, "v", cw, badge, k));
      const hc = Math.max(...ms.map((m) => m.hgt));
      ms.forEach((m, i) => {
        const row = i < 2 ? 0 : 1;
        const lastAlone = n === 3 && i === 2;
        const x = lastAlone ? X0 + (IW - cw) / 2 : X0 + (i % 2) * (cw + gx);
        out.push({ ...m, rect: { x, y: row === 0 ? Y0 : Y0 + IH - hc, w: cw, h: hc } });
      });
      ok = 2 * hc + 240 <= IH;
      if (2 * hc + 300 <= IH) break;
    }
  }
  return { cards: out, ok };
}

const bez = (c: Curve, t: number): Pt => {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, d = 3 * u * t * t, e = t * t * t;
  return { x: a * c.p0.x + b * c.c1.x + d * c.c2.x + e * c.p3.x, y: a * c.p0.y + b * c.c1.y + d * c.c2.y + e * c.p3.y };
};
const inside = (p: Pt, r: Rect, pad = 0) => p.x > r.x - pad && p.x < r.x + r.w + pad && p.y > r.y - pad && p.y < r.y + r.h + pad;
const overlap = (a: Rect, b: Rect, pad = 0) =>
  a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;

function facing(A: Rect, B: Rect, off: number, sa = 0, sb = 0): Curve {
  const acx = A.x + A.w / 2, acy = A.y + A.h / 2, bcx = B.x + B.w / 2, bcy = B.y + B.h / 2;
  const dx = bcx - acx, dy = bcy - acy;
  const vert = Math.abs(dy) / (A.h + B.h) >= Math.abs(dx) / (A.w + B.w);
  let p0: Pt, p3: Pt, n0: Pt, n3: Pt;
  if (vert) {
    off *= Math.min(A.w, B.w) * 0.44;
    const s = dy >= 0 ? 1 : -1;
    // the wider card's anchor leans toward the other card, the narrower one's stays near its outer middle
    const ka = A.w > B.w * 1.2 ? 0.5 : B.w > A.w * 1.2 ? -0.1 : 0.5;
    const kb = B.w > A.w * 1.2 ? 0.5 : A.w > B.w * 1.2 ? -0.1 : 0.15;
    const xa = cl(acx + dx * ka + off + sa * A.w, A.x + 34, A.x + A.w - 34);
    const xb = cl(bcx - dx * kb + off + sb * B.w, B.x + 34, B.x + B.w - 34);
    p0 = { x: xa, y: s > 0 ? A.y + A.h + GAP : A.y - GAP };
    p3 = { x: xb, y: s > 0 ? B.y - GAP : B.y + B.h + GAP };
    n0 = { x: 0, y: s };
    n3 = { x: 0, y: -s };
  } else {
    off *= Math.min(A.h, B.h) * 0.44;
    const s = dx >= 0 ? 1 : -1;
    const ya = cl(acy + dy * 0.5 + off + sa * A.h, A.y + 30, A.y + A.h - 30);
    const yb = cl(bcy - dy * 0.5 + off + sb * B.h, B.y + 30, B.y + B.h - 30);
    p0 = { x: s > 0 ? A.x + A.w + GAP : A.x - GAP, y: ya };
    p3 = { x: s > 0 ? B.x - GAP : B.x + B.w + GAP, y: yb };
    n0 = { x: s, y: 0 };
    n3 = { x: -s, y: 0 };
  }
  const k = Math.max(30, Math.hypot(p3.x - p0.x, p3.y - p0.y) * 0.42);
  return { p0, c1: { x: p0.x + n0.x * k, y: p0.y + n0.y * k }, c2: { x: p3.x + n3.x * k, y: p3.y + n3.y * k }, p3, n3, arc: false };
}

function arc(A: Rect, B: Rect, side: number, off: number, kf: number, top: number, bottom: number, pillH: number, sa = 0, sb = 0): Curve | null {
  const acx = A.x + A.w / 2, bcx = B.x + B.w / 2;
  const sx = bcx >= acx ? 1 : -1;
  off *= Math.min(A.w, B.w) * 0.3;
  const xa = cl(acx + sx * A.w * (0.3 + sa) + off, A.x + 34, A.x + A.w - 34);
  const xb = cl(bcx - sx * B.w * (0.3 + sb) + off, B.x + 34, B.x + B.w - 34);
  const ya = side < 0 ? A.y - GAP : A.y + A.h + GAP;
  const yb = side < 0 ? B.y - GAP : B.y + B.h + GAP;
  const room = side < 0 ? Math.min(ya, yb) - top : bottom - Math.max(ya, yb);
  const k = Math.min(kf * (0.35 * Math.abs(xb - xa) + 80), (room - pillH / 2 - 6) / 0.75);
  if (k < 50) return null;
  const n = { x: 0, y: side };
  const p0 = { x: xa, y: ya }, p3 = { x: xb, y: yb };
  return { p0, c1: { x: xa, y: ya + side * k }, c2: { x: xb, y: yb + side * k }, p3, n3: n, arc: true, flat: kf < 1 };
}

const segX = (a: Pt, b: Pt, c: Pt, d: Pt) => {
  const o = (p: Pt, q: Pt, r: Pt) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0;
};
// how many times two sampled curves cross (ends trimmed: links that share a card meet there legitimately)
function crossings(a: Pt[], b: Pt[]) {
  let c = 0;
  for (let i = 3; i < a.length - 3; i += 3) for (let j = 3; j < b.length - 3; j += 3) {
    if (segX(a[i - 3], a[i], b[j - 3], b[j])) c++;
  }
  return c;
}

function sample(c: Curve, n: number) {
  const pts: Pt[] = [];
  const cum: number[] = [];
  let len = 0;
  for (let i = 0; i <= n; i++) {
    const p = bez(c, i / n);
    if (i) len += Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y);
    pts.push(p);
    cum.push(len);
  }
  return { pts, cum, len };
}

function atLen(pts: Pt[], cum: number[], s: number): Pt {
  let i = 1;
  while (i < cum.length - 1 && cum[i] < s) i++;
  const seg = cum[i] - cum[i - 1] || 1;
  const u = cl((s - cum[i - 1]) / seg, 0, 1);
  return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * u, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * u };
}

function Icon({ kind, fg, bg, size }: { kind: string; fg: string; bg: string; size: number }) {
  const person = (cx: number, cy: number, s: number, key: string, ring?: string) => (
    <g key={key} transform={`translate(${cx} ${cy}) scale(${s})`} stroke={ring ?? "none"} strokeWidth={ring ? 6 / s : 0}>
      <circle cx={0} cy={-19} r={15} fill={fg} />
      <path d="M-30 34 C-30 10 -17 1 0 1 C17 1 30 10 30 34 Q30 38 26 38 H-26 Q-30 38 -30 34 Z" fill={fg} />
    </g>
  );
  let body: React.ReactNode;
  if (kind === "crowd") {
    body = [person(28, 52, 0.72, "a"), person(72, 52, 0.72, "b"), person(50, 54, 0.92, "c", bg)];
  } else if (kind === "shop") {
    body = (
      <g fill={fg}>
        <path d="M16 22 Q16 16 22 16 H78 Q84 16 84 22 L88 38 H12 Z" />
        {[21, 40, 60, 79].map((x) => <circle key={x} cx={x} cy={39} r={9.5} />)}
        <rect x={20} y={50} width={60} height={36} rx={4} />
        <rect x={43} y={62} width={14} height={24} rx={2} fill={bg} />
        <rect x={27} y={58} width={11} height={11} rx={2} fill={bg} />
        <rect x={62} y={58} width={11} height={11} rx={2} fill={bg} />
      </g>
    );
  } else if (kind === "company") {
    body = (
      <g>
        <rect x={27} y={12} width={46} height={76} rx={6} fill={fg} />
        {[0, 1, 2, 3].flatMap((r) => [0, 1, 2].map((c) => (
          <rect key={`${r}${c}`} x={34 + c * 12} y={21 + r * 13} width={8} height={8} rx={1.5} fill={bg} />
        )))}
        <rect x={44} y={74} width={12} height={14} rx={2} fill={bg} />
      </g>
    );
  } else if (kind === "official") {
    body = (
      <g fill={fg}>
        <rect x={48.5} y={10} width={3} height={12} rx={1.5} />
        <path d="M33 38 A17 17 0 0 1 67 38 Z" />
        <rect x={16} y={38} width={68} height={8} rx={2} />
        {[22, 38, 54, 70].map((x) => <rect key={x} x={x} y={49} width={8} height={29} rx={2} />)}
        <rect x={12} y={80} width={76} height={8} rx={2} />
      </g>
    );
  } else if (kind === "bank") {
    body = (
      <g fill={fg}>
        <path d="M50 10 L90 34 Q91 37 88 37 H12 Q9 37 10 34 Z" />
        <circle cx={50} cy={27} r={5.5} fill={bg} />
        <rect x={15} y={40} width={70} height={6} rx={2} />
        {[20, 36, 55, 71].map((x) => <rect key={x} x={x} y={49} width={9} height={29} rx={2} />)}
        <rect x={10} y={80} width={80} height={8} rx={2} />
      </g>
    );
  } else if (kind === "factory") {
    body = (
      <g fill={fg}>
        <rect x={68} y={14} width={12} height={40} rx={2} />
        <path d="M12 88 V50 L30 38 V50 L48 38 V50 L66 38 V50 H88 V88 Z" strokeLinejoin="round" />
        {[20, 38, 56, 72].map((x) => <rect key={x} x={x} y={62} width={9} height={11} rx={1.5} fill={bg} />)}
      </g>
    );
  } else {
    body = person(50, 52, 1.1, "p");
  }
  return <svg width={size} height={size} viewBox="0 0 100 100" style={{ display: "block" }}>{body}</svg>;
}

export default function Parties({ props }: { props: any }) {
  const { w: boxW, h: boxH, fps, theme, width, height } = useClip();
  const f = useCurrentFrame();
  const uid = "pt" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  // laid out in px of a 1080 short side, then scaled to the canvas
  const unit = Math.min(width, height) / 1080 || 1;
  const ink = onGround(theme, props?.ground);
  const dark = ink.dark;
  const parties: Party[] = (Array.isArray(props?.parties) ? props.parties : []).filter((p: any) => p && p.id != null).slice(0, 4);
  const n = parties.length;
  const idx = new Map(parties.map((p, i) => [String(p.id), i]));
  const links: Link[] = (Array.isArray(props?.links) ? props.links : []).filter(
    (l: any) => l && idx.has(String(l.from)) && idx.has(String(l.to)) && String(l.from) !== String(l.to),
  );
  const bw0 = boxW / unit, bh0 = boxH / unit;
  let mode = String(props?.layout ?? "auto");
  if (mode === "triangle" && n !== 3) mode = "auto";
  if (mode === "grid" && n < 3) mode = "auto";
  if (mode === "auto" || !["column", "row", "triangle", "grid"].includes(mode)) {
    mode = n <= 2 ? (bw0 >= bh0 * 1.25 ? "row" : "column") : n === 3 ? "triangle" : "grid";
  }
  const sameRow = (a: number, b: number) => (mode === "grid" ? (a < 2) === (b < 2) : mode === "triangle" ? a > 0 && b > 0 : mode === "row");
  const pillW = (label: string) => {
    const b = fitBlock(label, PILL - 44, READ, READ, READ, 700, 2);
    return Math.max(0, ...b.lines.map((x) => textWidth(x, b.size, FONTS.sans, 700))) + 44;
  };
  const rowGap = Math.max(0, ...links.filter((l) => l.label && sameRow(idx.get(String(l.from))!, idx.get(String(l.to))!))
    .map((l) => pillW(String(l.label)) + 60));
  // a box too small for the cards is laid out larger and scaled down whole (text keeps its floor, so it wraps instead)
  const pad = (bw: number, bh: number) => Math.round(cl(Math.min(bw, bh) * 0.04, 20, 34));
  let k = 1;
  if (bw0 >= 200 && bh0 >= 200 && n >= 2) {
    for (const kk of [1, 0.92, 0.84, 0.76, 0.68, 0.6, 0.52]) {
      k = kk;
      const vw = bw0 / kk, vh = bh0 / kk, pp = pad(vw, vh);
      if (layoutCards(parties, mode, pp, pp, vw - 2 * pp, vh - 2 * pp, links.length > 0, rowGap, kk).ok) break;
    }
  }
  const w = bw0 / k, h = bh0 / k;
  const P = pad(w, h);
  const X0 = P, IW = w - 2 * P;
  let Y0 = P, IH = h - 2 * P;
  if (mode === "column" && n >= 2 && w >= 200 && h >= 200) {
    // a tall box would leave a void between the cards: cap the gap and let the panel hug the content
    const hc = layoutCards(parties, mode, X0, Y0, IW, IH, links.length > 0, rowGap, k).cards[0].rect.h;
    const used = Math.min(IH, n * hc + (n - 1) * (links.length ? 380 : 110));
    Y0 += (IH - used) / 2;
    IH = used;
  } else if (mode === "row" && n >= 2 && w >= 200 && h >= 200) {
    const hc = layoutCards(parties, mode, X0, Y0, IW, IH, links.length > 0, rowGap, k).cards[0].rect.h;
    // two side by side link straight across the gap; more need room for arcs above and below
    const used = Math.min(IH, hc + (links.length ? (n === 2 ? 140 : 400) : 0));
    Y0 += (IH - used) / 2;
    IH = used;
  }

  const key = JSON.stringify([w, h, k, mode, parties.map((p) => [p.id, p.name, p.role]), links.map((l) => [l.from, l.to, l.label])]);
  const geo = useMemo(() => {
    if (w < 200 || h < 200 || n < 2) return null;
    const cards = layoutCards(parties, mode, X0, Y0, IW, IH, links.length > 0, rowGap, k).cards;
    const rects = cards.map((c) => c.rect);
    const pillMax = Math.min(IW * 0.62, PILL / k);
    const pills = links.map((l) => fitBlock(String(l.label ?? ""), pillMax - 44, 40, 40, READ / k, 700, 2));
    const pillDims = pills.map((b) => (b.lines.length
      ? { w: Math.max(...b.lines.map((s) => textWidth(s, b.size, FONTS.sans, 700))) + 44, h: b.lines.length * b.size * 1.22 + 22 }
      : { w: 0, h: 0 }));
    const pairCount = new Map<string, number>();
    const pairSeen = new Map<string, number>();
    const pk = (l: Link) => [String(l.from), String(l.to)].sort().join("|");
    links.forEach((l) => pairCount.set(pk(l), (pairCount.get(pk(l)) ?? 0) + 1));
    type Pick = { score: number; c: Curve; t: number; s: ReturnType<typeof sample>; pill: Rect | null };
    const candsOf = links.map((l, li) => {
      const A = rects[idx.get(String(l.from))!], B = rects[idx.get(String(l.to))!];
      const m = pairCount.get(pk(l))!;
      const j = pairSeen.get(pk(l)) ?? 0;
      pairSeen.set(pk(l), j + 1);
      const off = m > 1 ? (j - (m - 1) / 2) / (m - 1) : 0;
      const cs: Curve[] = [];
      for (const sa of [0, -0.22, 0.22]) for (const sb of [0, -0.22, 0.22]) {
        const c = facing(A, B, off, sa, sb);
        c.lean = (Math.abs(sa) + Math.abs(sb)) * 900;
        cs.push(c);
      }
      for (const side of [-1, 1]) for (const kf of [0.8, 1.3, 1.9, 2.6]) {
        for (const [sa, sb] of [[0, 0], [0, -0.25], [-0.25, 0], [0, -0.5], [-0.5, 0]]) {
          const c = arc(A, B, side, off, kf, Y0, Y0 + IH, pillDims[li].h, sa, sb);
          if (c) { c.lean = (Math.abs(sa) + Math.abs(sb)) * 160; cs.push(c); }
        }
      }
      return cs.map((c) => ({ c, s: sample(c, 48), pen: (c.flat ? 110 : 0) + (c.lean ?? 0) }));
    });
    const choose = (li: number, pillsO: Rect[], ptsO: Pt[][]): Pick => {
      const l = links[li];
      const a = idx.get(String(l.from))!, b = idx.get(String(l.to))!;
      const pd = pillDims[li];
      let best: Pick | null = null;
      for (const { c, s, pen } of candsOf[li]) {
        let base = (c.arc ? 160 : 0) + pen;
        ptsO.forEach((pp) => {
          for (const e of [pp[0], pp[pp.length - 1]]) for (const q of [c.p0, c.p3]) { const dq = Math.hypot(e.x - q.x, e.y - q.y); if (dq < 76) base += dq < 50 ? 3000 : 1200; }
        });
        const chord = Math.hypot(c.p3.x - c.p0.x, c.p3.y - c.p0.y);
        if (chord < 150) base += (150 - chord) * 20; // a stub of a line between two close cards does not read
        ptsO.forEach((pp) => { base += 420 * crossings(s.pts, pp); });
        s.pts.forEach((p, i) => {
          const t = i / 48;
          if (p.x < X0 - 4 || p.x > X0 + IW + 4 || p.y < Y0 - 8 || p.y > Y0 + IH + 8) base += 400;
          rects.forEach((r, ri) => {
            const own = ri === a || ri === b;
            if (own && (t < 0.1 || t > 0.9)) return;
            if (inside(p, r, own ? -4 : 8)) base += 900;
          });
          pillsO.forEach((pr) => { if (inside(p, pr, 6)) base += 260; });
          if (t > 0.12 && t < 0.88) ptsO.forEach((pp) => {
            for (let q = 6; q < pp.length - 6; q++) if (Math.abs(pp[q].x - p.x) < 22 && Math.abs(pp[q].y - p.y) < 22) { base += 45; break; }
          });
        });
        const ts = c.arc ? [0.5, 0.4, 0.6, 0.3, 0.7] : [0.5, 0.42, 0.58, 0.34, 0.66, 0.27, 0.73];
        for (const t of ts) {
          let score = base + Math.abs(t - 0.5) * 120;
          let pill: Rect | null = null;
          if (pd.w) {
            const q = bez(c, t);
            pill = { x: cl(q.x - pd.w / 2, 4, w - pd.w - 4), y: cl(q.y - pd.h / 2, 4, h - pd.h - 4), w: pd.w, h: pd.h };
            rects.forEach((r) => { if (overlap(pill!, r, 10)) score += 5000; });
            const bare = s.pts.filter((p) => !inside(p, pill!, 4)).length / 48 * s.len;
            if (bare < 120) score += (120 - bare) * 3;
            pillsO.forEach((pr) => { if (overlap(pill!, pr, 12)) score += 5000; });
            ptsO.forEach((pp) => pp.forEach((p) => { if (inside(p, pill!, 4)) score += 220; }));
          }
          if (!best || score < best.score) best = { score, c, t, s, pill };
        }
      }
      return best!;
    };
    // greedy pass, then one pass where each link re-routes around all the others
    const run = (order: number[]) => {
      const pk2: (Pick | null)[] = links.map(() => null);
      const others = (li: number) => pk2.filter((p, j) => p && j !== li) as Pick[];
      for (const li of order) { const o = others(li); pk2[li] = choose(li, o.map((p) => p.pill).filter(Boolean) as Rect[], o.map((p) => p.s.pts)); }
      let total = 0;
      for (const li of order) { const o = others(li); pk2[li] = choose(li, o.map((p) => p.pill).filter(Boolean) as Rect[], o.map((p) => p.s.pts)); total += pk2[li]!.score; }
      return { picks: pk2 as Pick[], total };
    };
    const fwd = links.map((_, i) => i);
    const a1 = run(fwd), a2 = run([...fwd].reverse());
    const picks = a2.total < a1.total ? a2.picks : a1.picks;
    const routed: Routed[] = picks.map((B2) => {
      // the slash goes where the line is clear of every pill and card, close to its own label
      const gap = (q: Pt, r: Rect) => Math.max(r.x - q.x, q.x - r.x - r.w, r.y - q.y, q.y - r.y - r.h);
      let sl = bez(B2.c, 0.5);
      let st = 0.5;
      let bestG = -Infinity;
      let rawG = 0;
      for (let t = 0.1; t <= 0.9; t += 0.02) {
        const q = bez(B2.c, t);
        const g = Math.min(40, ...picks.filter((o) => o.pill).map((o) => gap(q, o.pill!) - 14), ...rects.map((r) => gap(q, r)));
        const sc = Math.min(g, 30) * 10 - Math.abs(t - B2.t) * 60;
        if (sc > bestG) { bestG = sc; sl = q; st = t; rawG = g; }
      }
      const q2 = bez(B2.c, Math.min(1, st + 0.01));
      let ang = (Math.atan2(q2.y - sl.y, q2.x - sl.x) * 180) / Math.PI;
      // no clear stretch of line (a short link mostly under its label): strike through the label itself
      const strike = rawG < 10 && !!B2.pill;
      if (strike) { sl = { x: B2.pill!.x + B2.pill!.w / 2, y: B2.pill!.y + B2.pill!.h / 2 }; ang = -67; }
      return { curve: B2.c, pts: B2.s.pts, cum: B2.s.cum, len: B2.s.len, pill: B2.pill, slash: sl, slashAng: ang, strike };
    });
    return { cards, routed, pills };
  }, [key]);

  if (bw0 < 200 || bh0 < 200 || !geo) return null;
  const { cards, routed, pills } = geo;
  const accent = themeColor(theme, props?.color, "accent");
  const C = dark
    ? { panel: theme.night, card: "#28231E", border: "rgba(255,255,255,0.09)", badge: theme.snow, icon: theme.night,
        line: withAlpha(theme.snow, 0.82), pill: theme.snow, pillText: theme.night, grey: "#6F665D", cutPill: "#4A433C",
        cutText: "#C2B7AA", person: theme.snow, shadow: "rgba(0,0,0,0.45)" }
    : { panel: theme.paper, card: "#FFFCF7", border: withAlpha(theme.ink, 0.08), badge: theme.ink, icon: theme.paper,
        line: withAlpha(theme.ink, 0.78), pill: theme.ink, pillText: theme.snow, grey: "#ABA095", cutPill: "#DDD5CA",
        cutText: "#5E554C", person: theme.ink, shadow: "rgba(40,30,20,0.16)" };
  const stagger = Math.round(0.45 * fps);
  const drawDur = Math.round(0.55 * fps);
  const breathe = (i: number) => 0.5 + 0.5 * Math.sin((f / fps) * Math.PI * 2 / 2.6 + i * 1.7);
  const cardAt = (p: Party, i: number) => (p.at !== undefined && p.at !== null ? frameOr(p.at, i * stagger) : i * stagger);

  const firstAt = Math.min(...parties.map(cardAt));
  if (f < firstAt) return null;
  const panelS = springAt(f, firstAt, { fps, damping: 200, durationInFrames: 10 });
  const linkLayer: React.ReactNode[] = [];
  const dotLayer: React.ReactNode[] = [];
  const pillLayer: React.ReactNode[] = [];
  const slashLayer: React.ReactNode[] = [];
  links.forEach((l, li) => {
    const R = routed[li];
    const a0 = frameOr(l.at, 0);
    if (f < a0) return;
    const p = ease(f, a0, a0 + drawDur);
    const cutAt = l.cut_at !== undefined && l.cut_at !== null ? frameOr(l.cut_at, Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;
    const cutT = f >= cutAt ? ease(f, cutAt, cutAt + 10) : 0;
    const c = R.curve;
    const end = { x: c.p3.x + c.n3.x * ARROW * 0.55, y: c.p3.y + c.n3.y * ARROW * 0.55 };
    const d = `M${c.p0.x},${c.p0.y} C${c.c1.x},${c.c1.y} ${c.c2.x},${c.c2.y} ${end.x},${end.y}`;
    const L = R.len * 1.03 + 4;
    const tip = c.p3;
    const base = { x: c.p3.x + c.n3.x * ARROW, y: c.p3.y + c.n3.y * ARROW };
    const nx = -c.n3.y, ny = c.n3.x;
    const arrowS = ease(f, a0 + drawDur * 0.8, a0 + drawDur + 3);
    const arrowPts = (col: string, key2: string, op: number) => {
      const hw = ARROW * 0.55 * arrowS;
      const bx = tip.x + (base.x - tip.x) * arrowS, by = tip.y + (base.y - tip.y) * arrowS;
      return <path key={key2} d={`M${tip.x},${tip.y} L${bx + nx * hw},${by + ny * hw} Q${(bx + tip.x) / 2 + (base.x - tip.x) * 0.2},${(by + tip.y) / 2 + (base.y - tip.y) * 0.2} ${bx - nx * hw},${by - ny * hw} Z`}
        fill={col} opacity={op} strokeLinejoin="round" stroke={col} strokeWidth={2} />;
    };
    linkLayer.push(
      <g key={"l" + li}>
        <path d={d} fill="none" stroke={C.line} strokeWidth={6} strokeLinecap="round" strokeDasharray={L} strokeDashoffset={L * (1 - p)} opacity={1 - cutT} />
        {cutT > 0 ? <path d={d} fill="none" stroke={C.grey} strokeWidth={6} strokeLinecap="round" strokeDasharray="4 16" opacity={cutT} /> : null}
        {arrowS > 0 ? arrowPts(C.line, "a", 1 - cutT) : null}
        {arrowS > 0 && cutT > 0 ? arrowPts(C.grey, "g", cutT) : null}
      </g>,
    );
    const flow = String(l.flow ?? "none");
    const flowStart = a0 + drawDur;
    if ((flow === "money" || flow === "people") && f >= flowStart && cutT < 1) {
      const speed = 130 / fps;
      const count = Math.max(2, Math.floor(R.len / 150));
      const fadeIn = ease(f, flowStart, flowStart + 10);
      const usable = R.len - ARROW - 8;
      for (let i = 0; i < count; i++) {
        const u = ((((f - flowStart) * speed) / usable + i / count) % 1 + 1) % 1;
        const q = atLen(R.pts, R.cum, 10 + u * (usable - 10));
        const op = Math.min(1, u / 0.1, (1 - u) / 0.1) * fadeIn * (1 - cutT);
        if (flow === "money") {
          dotLayer.push(
            <g key={`m${li}-${i}`} transform={`translate(${q.x} ${q.y})`} opacity={op}>
              <circle r={14} fill={theme.gold} stroke="#8A6420" strokeWidth={3} />
              <circle r={7} fill="none" stroke="#8A6420" strokeWidth={2.2} opacity={0.8} />
            </g>,
          );
        } else {
          dotLayer.push(
            <g key={`p${li}-${i}`} transform={`translate(${q.x} ${q.y})`} opacity={op}>
              <circle r={20} fill={C.panel} stroke={C.person} strokeWidth={2.5} />
              <circle cx={0} cy={-6} r={6.5} fill={C.person} />
              <path d="M-12 13 C-12 3 -6 0 0 0 C6 0 12 3 12 13 Z" fill={C.person} />
            </g>,
          );
        }
      }
    }
    const pb = pills[li];
    if (R.pill && pb.lines.length) {
      const ps = springAt(f, a0 + Math.round(drawDur * 0.45), { fps, damping: 13 });
      if (ps > 0) {
        pillLayer.push(
          <div key={"p" + li} style={{
            position: "absolute", left: R.pill.x, top: R.pill.y, width: R.pill.w, height: R.pill.h, borderRadius: Math.min(R.pill.h / 2, 30),
            background: cutT > 0.5 ? C.cutPill : C.pill, color: cutT > 0.5 ? C.cutText : C.pillText, fontFamily: FONTS.sans, fontWeight: 700, fontSize: pb.size,
            lineHeight: 1.22, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", whiteSpace: "pre",
            opacity: Math.min(1, ps * 1.4), transform: `scale(${0.82 + 0.18 * ps})`, boxShadow: `0 6px 16px ${C.shadow}`,
          }}>{pb.lines.join("\n")}</div>,
        );
      }
    }
    if (f >= cutAt) {
      const ss = springAt(f, cutAt + 2, { fps, damping: 12 });
      const len = (R.strike && R.pill ? R.pill.w / 2 + 6 : 34) * ss;
      slashLayer.push(
        <g key={"s" + li} transform={`translate(${R.slash.x} ${R.slash.y}) rotate(${R.slashAng + 62})`}>
          {R.strike ? null : <line x1={-len} y1={0} x2={len} y2={0} stroke={C.panel} strokeWidth={20} strokeLinecap="round" />}
          <line x1={-len} y1={0} x2={len} y2={0} stroke={accent} strokeWidth={R.strike ? 7 : 11} strokeLinecap="round" />
        </g>,
      );
    }
  });

  const S = unit * k;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transform: S !== 1 ? `scale(${S})` : undefined, transformOrigin: "0 0" }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: Y0 - P, height: IH + 2 * P, borderRadius: 36, background: C.panel, boxShadow: `0 24px 60px ${C.shadow}`,
        opacity: Math.min(1, panelS * 1.5), transform: `scale(${0.96 + 0.04 * panelS})` }} />
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>
          <filter id={uid} x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="2" stdDeviation="2" floodOpacity="0.25" />
          </filter>
        </defs>
        {linkLayer}
        <g filter={`url(#${uid})`}>{dotLayer}</g>
      </svg>
      {cards.map((cd, i) => {
        const p = parties[i];
        const a0 = cardAt(p, i);
        if (f < a0) return null;
        const s = springAt(f, a0, { fps, damping: 14 });
        const bs = springAt(f, a0 + 4, { fps, damping: 11 });
        const r = cd.rect;
        const hot = !!p.hot;
        const pulse = breathe(i);
        const ring = hot ? `0 0 0 5px ${accent}, 0 0 0 ${9 + pulse * 7}px ${withAlpha(accent, 0.16 + 0.1 * (1 - pulse))}, ` : "";
        const badgeBg = hot ? accent : C.badge;
        const iconFg = hot ? "#FFF8F0" : C.icon;
        const iconScale = 1 + 0.035 * pulse;
        const v = cd.style === "v";
        return (
          <div key={"c" + i} style={{
            position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: 28, background: C.card,
            border: `2px solid ${C.border}`, boxSizing: "border-box", boxShadow: `${ring}0 12px 30px ${C.shadow}`,
            opacity: Math.min(1, s * 1.3), transform: `translateY(${(1 - s) * 26}px) scale(${0.94 + 0.06 * s})`,
            display: "flex", flexDirection: v ? "column" : "row", alignItems: "center",
            justifyContent: "center", gap: v ? 14 : 24, padding: v ? "0 20px" : "0 26px",
          }}>
            <div style={{
              width: cd.badge, height: cd.badge, borderRadius: cd.badge / 2, background: badgeBg, flex: "none",
              display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${0.6 + 0.4 * bs})`,
            }}>
              <div style={{ transform: `scale(${iconScale}) translateY(${-1.5 * pulse}px)` }}>
                <Icon kind={String(p.icon ?? "person")} fg={iconFg} bg={badgeBg} size={cd.badge * 0.64} />
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: v ? "center" : "flex-start", flex: v ? "none" : "1 1 auto", minWidth: 0 }}>
              {cd.name.lines.length ? (
                <div style={{ fontFamily: FONTS.sans, fontWeight: 800, fontSize: cd.name.size, lineHeight: 1.16, color: ink.ink, whiteSpace: "pre", textAlign: v ? "center" : "left" }}>
                  {cd.name.lines.join("\n")}
                </div>
              ) : null}
              {cd.role.lines.length ? (
                <div style={{ fontFamily: FONTS.sans, fontWeight: 500, fontSize: cd.role.size, lineHeight: 1.24, color: ink.muted, whiteSpace: "pre", marginTop: 8, textAlign: v ? "center" : "left" }}>
                  {cd.role.lines.join("\n")}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
      {pillLayer}
      <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0 }}>{slashLayer}</svg>
    </div>
  );
}
