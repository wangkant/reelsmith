// Joins between scenes without a hard cut: push through an opening into the next scene, a whip pan with real
// motion blur, or a matched move from one shape to the same shape in the next scene.
import React, { useId } from "react";
import { useCurrentFrame } from "remotion";
import { useClip } from "../context";
import { joinAt } from "./optics";

export type JoinProps = {
  /** the scene before and the scene after (each a whole world, usually a Lens or a Stage) */
  a: React.ReactNode;
  b: React.ReactNode;
  /** first frame of the join and frames it takes */
  at: number;
  len?: number;
  /** push: into `hole` of A, where B is already seen; whip: a fast pan toward `dir`; match: `from` in A becomes `to` in B */
  kind?: "push" | "whip" | "match";
  /** push: the opening in A in frame px [x, y, w, h]; a rectangle with corner radius `round`, or an oval with a
   *  soft edge (`feather` 0..0.9 of its radius) */
  hole?: [number, number, number, number];
  round?: number;
  oval?: boolean;
  feather?: number;
  dir?: "left" | "right" | "up" | "down";
  /** match: the shared shape [x, y, size] as it sits in A's frame and in B's frame */
  from?: [number, number, number];
  to?: [number, number, number];
  f?: number;
};

const full = (w: number, h: number): React.CSSProperties => ({ position: "absolute", left: 0, top: 0, width: w, height: h });

/** Plays `a` until `at`, `b` after `at + len`, and travels from one into the other in between. */
export function Join({ a, b, at, len = 14, kind = "push", hole, round = 0, oval = false, feather = 0.25, dir = "left", from, to, f: fIn }: JoinProps) {
  const now = useCurrentFrame();
  const f = fIn ?? now;
  const { w, h } = useClip();
  const id = "jn" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  if (f < at) return <div style={full(w, h)}>{a}</div>;
  if (f >= at + len) return <div style={full(w, h)}>{b}</div>;
  const k = joinAt(f, at, len);
  if (kind === "whip") {
    const vx = dir === "left" ? -1 : dir === "right" ? 1 : 0, vy = dir === "up" ? -1 : dir === "down" ? 1 : 0;
    const blur = Math.sin(Math.PI * k) * 0.06 * (vx ? w : h);
    return (
      <div style={{ ...full(w, h), overflow: "hidden", background: "#000" }}>
        <svg width={0} height={0} style={{ position: "absolute" }}>
          <filter id={id} x="-10%" y="-10%" width="120%" height="120%">
            <feGaussianBlur stdDeviation={`${vx ? blur.toFixed(1) : 0} ${vy ? blur.toFixed(1) : 0}`} />
          </filter>
        </svg>
        <div style={{ ...full(w, h), transform: `translate(${vx * k * w}px, ${vy * k * h}px)`, filter: blur > 0.5 ? `url(#${id})` : undefined }}>
          <div style={full(w, h)}>{a}</div>
          <div style={{ ...full(w, h), left: -vx * w, top: -vy * h }}>{b}</div>
        </div>
      </div>
    );
  }
  if (kind === "match") {
    const [ax, ay, as] = from ?? [w / 2, h / 2, 1], [bx, by, bs] = to ?? [w / 2, h / 2, 1];
    const r = bs / Math.max(1e-3, as);
    // A moves its shape onto B's; B starts with its shape where A's was
    const ta = `translate(${(bx - ax) * k}px, ${(by - ay) * k}px) scale(${Math.pow(r, k)})`;
    const tb = `translate(${(ax - bx) * (1 - k)}px, ${(ay - by) * (1 - k)}px) scale(${Math.pow(1 / r, 1 - k)})`;
    return (
      <div style={{ ...full(w, h), overflow: "hidden", background: "#000" }}>
        <div style={{ ...full(w, h), transformOrigin: `${ax}px ${ay}px`, transform: ta }}>{a}</div>
        <div style={{ ...full(w, h), transformOrigin: `${bx}px ${by}px`, transform: tb, opacity: Math.min(1, k * 1.4) }}>{b}</div>
      </div>
    );
  }
  const [hx, hy, hw, hh] = hole ?? [w * 0.35, h * 0.35, w * 0.3, h * 0.3];
  const cx = hx + hw / 2, cy = hy + hh / 2;
  const c = Math.max(hw / w, hh / h);                 // B scaled to cover the opening
  const S = Math.pow(1 / c, k);
  const px = cx + (w / 2 - cx) * k, py = cy + (h / 2 - cy) * k;
  const world = `translate(${px}px, ${py}px) scale(${S}) translate(${-cx}px, ${-cy}px)`;
  const blur = Math.sin(Math.PI * k) * 5;
  // the window opens from the hole to past B's whole frame, so nothing of A is left when the join ends
  const grow = oval ? Math.SQRT2 * 1.08 : 1.02;
  const g = k * k;
  const ww = hw + (c * w * grow - hw) * g, wh = hh + (c * h * grow - hh) * g;
  const wx = cx - ww / 2, wy = cy - wh / 2;
  const fe = Math.max(0, Math.min(0.9, feather));
  const mask = oval ? `radial-gradient(closest-side, black ${Math.round(100 * (1 - fe))}%, transparent 100%)` : undefined;
  return (
    <div style={{ ...full(w, h), overflow: "hidden", background: "#000" }}>
      <div style={{ ...full(w, h), transformOrigin: "0 0", transform: world }}>
        <div style={{ ...full(w, h), filter: blur > 0.4 ? `blur(${blur.toFixed(1)}px)` : undefined }}>{a}</div>
        <div style={{ position: "absolute", left: wx, top: wy, width: ww, height: wh, overflow: "hidden",
          borderRadius: oval ? undefined : round * (1 - g), WebkitMaskImage: mask, maskImage: mask }}>
          <div style={{ ...full(w, h), transformOrigin: "0 0",
            transform: `translate(${cx - (c * w) / 2 - wx}px, ${cy - (c * h) / 2 - wy}px) scale(${c})` }}>{b}</div>
        </div>
      </div>
    </div>
  );
}
