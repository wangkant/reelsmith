// The live player: the renderer's own Film in @remotion/player, driven by window.postMessage from the page that
// frames it (load, seek, play, pause, volume, muted) and reporting back (ready, loaded, frame, playing, ended, error).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Player, type PlayerRef } from "@remotion/player";
import { Film } from "../Film";
import { componentNames, findComponent } from "../elements/ComponentHost";
import type { FilmProps, Resolved } from "../types";

type Skipped = Record<string, string>;
type Loaded = { resolved: Resolved; key: string; start: number };
type Inbound =
  | { type: "load"; resolved: Resolved }
  | { type: "seek"; frame: number }
  | { type: "play" }
  | { type: "pause" }
  | { type: "volume"; value: number }
  | { type: "muted"; value: boolean };

declare global {
  interface Window {
    /** written into index.html by scripts/player.mjs: library components left out of the bundle, with why */
    reelsmith_player?: { skipped?: Skipped };
  }
}

const post = (msg: Record<string, unknown>) => {
  if (window.parent !== window) window.parent.postMessage(msg, location.origin);
};

// one message per component (or per distinct error): a crashing component re-renders on every frame, and a module
// that failed to load fails differently when asked again
const said = new Set<string>();
const report = (message: string) => {
  const key = /^component "?(\w+)"? /.exec(message)?.[1] ?? message;
  if (said.has(key)) return;
  said.add(key);
  post({ type: "error", message });
};

const rate = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : fallback);
const whole = (v: unknown, fallback: number) => Math.round(rate(v, fallback));

/** The composition's size, fps and length as Root's calculateMetadata gives them. */
const metaOf = (r: Resolved) => ({
  fps: rate(r.fps, 30),
  width: whole(r.width, 1920),
  height: whole(r.height, 1080),
  frames: whole(r.durationInFrames, 60),
});

/** Components the film names that this bundle cannot draw: missing, left out at build, or failing to load. */
const componentProblems = (r: Resolved): string[] => {
  const skipped = window.reelsmith_player?.skipped ?? {};
  const have = new Set(componentNames());
  const out: string[] = [];
  for (const t of r.tracks ?? []) {
    if (t?.kind !== "visual" || t.hidden) continue;
    for (const c of (t as { clips?: Array<{ type?: string; content?: { name?: unknown } }> }).clips ?? []) {
      const name = c?.type === "component" ? c.content?.name : null;
      if (typeof name !== "string") continue;
      if (skipped[name]) out.push(`component ${name} was left out of the player: ${skipped[name]}`);
      else if (!have.has(name)) out.push(`component "${name}" is not in the player (written after it was built?)`);
      else {
        const found = findComponent(name);
        if (found instanceof Error) out.push(found.message);
      }
    }
  }
  return [...new Set(out)];
};

const App: React.FC = () => {
  const player = useRef<PlayerRef>(null);
  const [film, setFilm] = useState<Loaded | null>(null);
  const current = useRef<Loaded | null>(null);
  const pending = useRef<number | null>(null);

  const load = useCallback((resolved: Resolved) => {
    const m = metaOf(resolved);
    const now = player.current?.getCurrentFrame() ?? 0;
    const frame = Math.max(0, Math.min(now, m.frames - 1));
    // a new size or fps remounts the player (it starts at `start`); otherwise the props change under it
    const key = `${m.width}x${m.height}@${m.fps}`;
    const prev = current.current;
    const same = !!prev && prev.key === key;
    if (same && frame !== now) pending.current = frame;
    current.current = { resolved, key, start: same ? prev.start : frame };
    setFilm(current.current);
    said.clear();
    for (const problem of componentProblems(resolved)) report(problem);
    post({ type: "loaded", frames: m.frames, fps: m.fps });
  }, []);

  useEffect(() => {
    if (pending.current !== null) {
      player.current?.seekTo(pending.current);
      pending.current = null;
    }
  }, [film]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== location.origin || !e.data || typeof e.data !== "object") return;
      const msg = e.data as Inbound;
      const p = player.current;
      try {
        if (msg.type === "load") load(msg.resolved);
        else if (msg.type === "seek" && p) p.seekTo(Math.max(0, Math.round(Number(msg.frame) || 0)));
        else if (msg.type === "play" && p) p.play();
        else if (msg.type === "pause" && p) p.pause();
        else if (msg.type === "volume" && p) p.setVolume(Math.max(0, Math.min(1, Number(msg.value))));
        else if (msg.type === "muted" && p) (msg.value ? p.mute() : p.unmute());
      } catch (err) {
        report(String((err as Error)?.message ?? err));
      }
    };
    window.addEventListener("message", onMessage);
    post({ type: "ready" });
    return () => window.removeEventListener("message", onMessage);
  }, [load]);

  // the player's events, re-attached whenever it remounts
  useEffect(() => {
    const p = player.current;
    if (!p) return;
    const onFrame = (e: { detail: { frame: number } }) => post({ type: "frame", frame: e.detail.frame });
    let playing = false;
    let pausedAt = -Infinity;
    const onPlay = () => {
      playing = true;
      post({ type: "playing", value: true });
    };
    const onPause = () => {
      if (!playing) return;
      playing = false;
      pausedAt = performance.now();
      post({ type: "playing", value: false });
    };
    // playing into the end pauses just before "ended"; a shorter film loaded under a paused playhead also says
    // "ended", and that is not one
    const onEnded = () => {
      if (!playing && performance.now() - pausedAt > 250) return;
      if (playing) post({ type: "playing", value: false });
      playing = false;
      post({ type: "ended" });
    };
    const onError = (e: { detail: { error: Error } }) => report(e.detail.error.message);
    p.addEventListener("frameupdate", onFrame);
    p.addEventListener("seeked", onFrame);
    p.addEventListener("play", onPlay);
    p.addEventListener("pause", onPause);
    p.addEventListener("ended", onEnded);
    p.addEventListener("error", onError);
    return () => {
      p.removeEventListener("frameupdate", onFrame);
      p.removeEventListener("seeked", onFrame);
      p.removeEventListener("play", onPlay);
      p.removeEventListener("pause", onPause);
      p.removeEventListener("ended", onEnded);
      p.removeEventListener("error", onError);
    };
  }, [film?.key]);

  if (!film) return null;
  const m = metaOf(film.resolved);
  const inputProps: FilmProps = { resolved: film.resolved, mode: "studio" };
  return (
    <Player
      key={film.key}
      ref={player}
      component={Film as unknown as React.FC<Record<string, unknown>>}
      inputProps={inputProps as unknown as Record<string, unknown>}
      durationInFrames={m.frames}
      fps={m.fps}
      compositionWidth={m.width}
      compositionHeight={m.height}
      initialFrame={film.start}
      controls={false}
      clickToPlay={false}
      doubleClickToFullscreen={false}
      spaceKeyToPlayOrPause={false}
      moveToBeginningWhenEnded={false}
      acknowledgeRemotionLicense
      errorFallback={({ error }) => {
        report(error.message);
        return (
          <div style={{ position: "absolute", inset: 0, background: "rgba(200,30,30,0.55)", border: "4px solid #ff3030",
            color: "#fff", fontFamily: "monospace", fontSize: 16, padding: 16, whiteSpace: "pre-wrap" }}>{error.message}</div>
        );
      }}
      style={{ width: "100%", height: "100%" }}
    />
  );
};

// errors a component's error boundary caught still reach the host page
const root = createRoot(document.getElementById("root") as HTMLElement, {
  onCaughtError: (error, info) => {
    const who = /\n\s*at (\w+)/.exec(info.componentStack ?? "")?.[1];
    const message = String((error as Error)?.message ?? error);
    report(who && !message.includes(who) ? `component ${who} crashed: ${message}` : message);
  },
  onUncaughtError: (error) => report(String((error as Error)?.message ?? error)),
});
window.addEventListener("error", (e) => report(String(e.message)));
window.addEventListener("unhandledrejection", (e) => report(String(e.reason?.message ?? e.reason)));
root.render(<App />);
