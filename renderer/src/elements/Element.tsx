// One visual clip: its box (keyframed), style, enter/exit and Ken Burns (zoom/pan move the content inside an
// overflow-hidden box), then the content by type. Rendered inside the clip's <Sequence>, so frames count from
// the clip's start.
import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { ClipContext, type ClipCtx } from "../kit/context";
import { cutAt, sample, transitionAt } from "../keyframes";
import type { Box, ClipStyle, EvidenceContent, Keyframe, RClip, RenderMode, Theme } from "../types";
import { ComponentHost } from "./ComponentHost";
import { EvidenceCrop } from "./EvidenceCrop";
import { Media } from "./Media";
import { Shape } from "./Shape";
import { TextBlock } from "./Text";
import { clamp01, filterBase, filterCss, type FilterNow, num, origin, shadowFor } from "./util";

// content that fills the box and is cropped by it
const CROPPED = new Set(["image", "video", "evidence"]);

type Props = { clip: RClip; theme: Theme; safe: Box; mode: RenderMode };

type ContentProps = {
  clip: RClip; w: number; h: number; progress: number | null; theme: Theme; mode: RenderMode; radius: number; focus: [number, number];
};

const Content: React.FC<ContentProps> = ({ clip, w, h, progress, theme, mode, radius, focus }) => {
  const { fps } = useVideoConfig();
  const c = clip.content ?? {};
  switch (clip.type) {
    case "image":
      return <Media media={{ src: c.src, kind: "image", size: c.size, animated: !!c.animated }} fit={c.fit ?? "cover"} focus={focus} />;
    case "video":
      return (
        <Media
          media={{ src: c.src, kind: "video", duration: c.duration }} fit={c.fit ?? "cover"} focus={focus}
          trimIn={num(c.trimIn, 0)} rate={num(c.rate, 1)} loop={!!c.loop} volume={num(c.volume, 0)}
          volumeKeys={c.volumeKeys} fadeIn={c.fadeIn} fadeOut={c.fadeOut} hold={c.hold ?? null} rateKeys={c.rateKeys ?? null}
        />
      );
    case "text":
      return <TextBlock runs={c.runs ?? []} style={c.style} reveal={c.reveal} w={w} h={h} theme={theme} fps={fps} />;
    case "shape":
      return <Shape c={c} w={w} h={h} progress={progress} theme={theme} fps={fps} radius={radius} />;
    case "evidence": {
      const ev = c as EvidenceContent;
      return (
        <EvidenceCrop
          ev={{ src: ev.src, size: ev.size, box: ev.box, site: ev.site }} w={w} h={h} highlight={ev.highlight ?? null} radius={radius}
        />
      );
    }
    case "component":
      return <ComponentHost name={String(c.name ?? "")} props={c.props} mode={mode} />;
    default:
      throw new Error(`clip ${clip.id}: unknown type "${String(clip.type)}"`);
  }
};

type Span = [number, number];

/** The least zoom at which no pan in the clip shows past the picture's edges. The zoom grows around the focus point
 *  (on screen), so a pan right (p > 0) needs fx * w * (zoom - 1) >= p and a pan left needs (1 - fx) * w * (zoom - 1)
 *  >= -p, for every focus the clip moves through (`fx`, `fy`: the lowest and highest). */
const panFloor = (k: NonNullable<RClip["keyframes"]> | Record<string, never>, w: number, h: number, fx: Span, fy: Span): number => {
  const need = (frames: Keyframe[] | undefined, size: number, [lo, hi]: Span) => {
    const vs = (frames ?? []).map((kf) => kf?.v).filter((v): v is number => Number.isFinite(v));
    if (!vs.length || !(size > 0)) return 1;
    // a spring ease overshoots its keyframes
    const over = (frames ?? []).some((kf) => kf?.ease === "spring") ? 1.25 : 1;
    const right = Math.max(0, ...vs) * over;
    const left = Math.max(0, ...vs.map((v) => -v)) * over;
    return Math.max(1 + right / (Math.max(0.05, lo) * size), 1 + left / (Math.max(0.05, 1 - hi) * size));
  };
  return Math.max(need(k.pan_x, w, fx), need(k.pan_y, h, fy));
};

/** The lowest and highest value a 0..1 prop takes over the clip: its keyframes, else `still`. */
const reach = (frames: Keyframe[] | undefined, still: number): Span => {
  const vs = (frames ?? []).map((kf) => kf?.v).filter((v): v is number => Number.isFinite(v)).map(clamp01);
  return vs.length ? [Math.min(...vs), Math.max(...vs)] : [still, still];
};

const mirror = (s: Span, flip: boolean): Span => (flip ? [1 - s[1], 1 - s[0]] : s);

const FILTERS = ["blur", "brightness", "contrast", "saturate", "grayscale", "sepia", "invert", "hue_rotate"] as const;

export const Element: React.FC<Props> = ({ clip, theme, safe, mode }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const k = clip.keyframes ?? {};
  const st: ClipStyle = clip.style ?? {};
  const box = clip.box ?? { x: 0, y: 0, w: width, h: height };
  const at = (prop: keyof NonNullable<RClip["keyframes"]>, fallback: number) => sample(k[prop], f, fps, fallback);

  const x = at("x", box.x);
  const y = at("y", box.y);
  const w = Math.max(0, at("w", box.w));
  const h = Math.max(0, at("h", box.h));
  const opacity = clamp01(at("opacity", num(st.opacity, 1)));
  const rotate = at("rotate", num(st.rotate, 0));
  const scale = at("scale", num(st.scale, 1));
  const still = filterBase(st.filter);
  const filter = Object.fromEntries(FILTERS.map((p) => [p, at(p, still[p])])) as FilterNow;
  const panX = at("pan_x", 0);
  const panY = at("pan_y", 0);
  const picture = clip.type === "image" || clip.type === "video";
  const focus = picture ? clip.content?.focus : null;
  const [fx0, fy0] = Array.isArray(focus) && focus.length === 2 ? [clamp01(focus[0]), clamp01(focus[1])] : [0.5, 0.5];
  const fx = picture ? clamp01(at("focus_x", fx0)) : fx0;
  const fy = picture ? clamp01(at("focus_y", fy0)) : fy0;
  // the focus is a point of the picture; mirrored, it sits at 1 - f on screen, and zoom closes in there
  const flipX = !!st.flipX;
  const flipY = !!st.flipY;
  const sx = flipX ? 1 - fx : fx;
  const sy = flipY ? 1 - fy : fy;
  // a panned picture never shows past its edges: it is zoomed at least as much as its widest pan needs
  const floor = picture ? panFloor(k, box.w, box.h, mirror(reach(k.focus_x, fx0), flipX), mirror(reach(k.focus_y, fy0), flipY)) : 1;
  const zoom = Math.max(at("zoom", 1), floor);
  const kfProgress = k.progress && k.progress.length ? clamp01(at("progress", 0)) : null;
  const tr = transitionAt(clip.enter, clip.exit, f, clip.dur, fps, h);
  const cut = cutAt(clip.transition, clip.transitionOut, f, w);
  const radius = Math.max(0, num(st.radius, 0));
  const shadow = shadowFor(st, clip.type);
  const cropped = CROPPED.has(clip.type);

  const ctx: ClipCtx = {
    w, h, dur: clip.dur, fps, theme, width, height, safe,
    progress: kfProgress ?? (clip.dur > 1 ? clamp01(f / (clip.dur - 1)) : 1),
  };
  const moved = zoom !== 1 || panX !== 0 || panY !== 0;
  const contentOrigin = `${sx * 100}% ${sy * 100}%`;
  const body = <Content clip={clip} w={w} h={h} progress={kfProgress} theme={theme} mode={mode} radius={radius} focus={[fx, fy]} />;

  return (
    <div
      data-clip={clip.id}
      data-track={clip.track}
      style={{
        position: "absolute", left: x, top: y, width: w, height: h, boxSizing: "border-box",
        opacity: opacity * tr.opacity * cut.opacity,
        transform: `translate(${tr.tx + cut.tx}px, ${tr.ty + cut.ty}px) rotate(${rotate}deg) scale(${scale * tr.scale * cut.scale})`,
        transformOrigin: origin(st.origin),
        filter: filterCss(filter, shadow.drop),
        mixBlendMode: (st.blend && st.blend !== "normal" ? st.blend : undefined) as React.CSSProperties["mixBlendMode"],
        clipPath: cut.clip ?? tr.clip ?? undefined,
        // shapes and evidence round their own outline (evidence: the panel hugging its content)
        borderRadius: clip.type === "shape" || clip.type === "evidence" ? undefined : radius || undefined,
        overflow: cropped || (radius > 0 && clip.type !== "shape" && clip.type !== "text") ? "hidden" : "visible",
        boxShadow: shadow.box,
      }}
    >
      <div style={{
        position: "absolute", left: 0, top: 0, width: w, height: h, opacity: cut.content < 1 ? cut.content : undefined,
        transform: moved ? `translate(${panX}px, ${panY}px) scale(${zoom})` : undefined, transformOrigin: contentOrigin,
      }}>
        <ClipContext.Provider value={ctx}>
          {flipX || flipY ? (
            // mirrored in place, inside the pan and zoom: those stay in screen directions
            <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transform: `scale(${flipX ? -1 : 1}, ${flipY ? -1 : 1})` }}>
              {body}
            </div>
          ) : body}
        </ClipContext.Provider>
      </div>
      {cut.veil && cut.veilOpacity > 0 ? (
        <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, background: cut.veil, opacity: clamp01(cut.veilOpacity) }} />
      ) : null}
    </div>
  );
};
