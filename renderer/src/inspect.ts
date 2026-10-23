// Layout measurement (contract section 12): after a frame renders, every visible clip container and text node is
// measured in canvas pixels and logged as one `@@inspect {...}` line that render.mjs collects.
import { useEffect, type RefObject } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";
import type { InspectItem } from "./types";

const round = (v: number) => Math.round(v * 10) / 10;
const round3 = (v: number) => Math.round(v * 1000) / 1000;

/** Opacity of `el` multiplied up to (not past) `root`; 0 when hidden. Cached per element for one frame. */
const opacityOf = (el: Element | null, root: Element, cache: Map<Element, number>): number => {
  if (!el || el === root.parentElement) return 1;
  const known = cache.get(el);
  if (known !== undefined) return known;
  const cs = getComputedStyle(el);
  let o = cs.display === "none" || cs.visibility === "hidden" ? 0 : parseFloat(cs.opacity);
  if (!Number.isFinite(o)) o = 1;
  if (o > 0 && el !== root) o *= opacityOf(el.parentElement, root, cache);
  cache.set(el, o);
  return o;
};

// A text Range's rects are the font's content area (about 1.45 em for the CJK faces), taller than the line box when
// line-height is tighter, so they would poke out of a box the glyphs fit in. Rects are shrunk to the line box.
const contentEm = new Map<string, number>();
const contentAreaEm = (family: string): number => {
  const known = contentEm.get(family);
  if (known !== undefined) return known;
  const span = document.createElement("span");
  span.style.cssText = "position:absolute;left:-9999px;top:0;font-size:100px;line-height:normal;white-space:pre";
  span.style.fontFamily = family;
  span.textContent = "国Ag";
  document.body.appendChild(span);
  const r = document.createRange();
  r.selectNodeContents(span.firstChild as Node);
  const h = Math.max(0, ...Array.from(r.getClientRects()).map((q) => q.height));
  span.remove();
  const em = h > 0 ? h / 100 : 1.2;
  contentEm.set(family, em);
  return em;
};

const lineBoxRatio = (el: Element | null): number => {
  if (!el) return 1;
  const cs = getComputedStyle(el);
  const fs = parseFloat(cs.fontSize);
  const lh = parseFloat(cs.lineHeight);
  if (!(fs > 0) || !(lh > 0)) return 1;
  return Math.min(1, lh / fs / contentAreaEm(cs.fontFamily));
};

/** Every visible clip container and text node under `root`, in canvas pixels. */
export const measure = (root: HTMLElement, width: number, height: number): InspectItem[] => {
  const rr = root.getBoundingClientRect();
  const sx = rr.width / width || 1;
  const sy = rr.height / height || 1;
  const rect = (r: { left: number; top: number; width: number; height: number }): [number, number, number, number] => [
    round((r.left - rr.left) / sx), round((r.top - rr.top) / sy), round(r.width / sx), round(r.height / sy),
  ];
  const cache = new Map<Element, number>();
  const items: InspectItem[] = [];
  const range = document.createRange();
  for (const el of Array.from(root.querySelectorAll<HTMLElement>("[data-clip]"))) {
    const clip = el.dataset.clip ?? "";
    const track = el.dataset.track ?? "";
    const op = opacityOf(el, root, cache);
    if (op <= 0.001) continue;
    items.push({ clip, track, kind: "clip", rect: rect(el.getBoundingClientRect()), opacity: round3(op) });
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.nodeValue ?? "";
      if (!text.trim()) continue;
      // a clip nested inside another reports its own text; error boxes are not layout
      if (n.parentElement?.closest("[data-clip]") !== el || n.parentElement?.closest("[data-noinspect]")) continue;
      const o = opacityOf(n.parentElement, root, cache);
      if (o <= 0.01) continue;
      range.selectNodeContents(n);
      const k = lineBoxRatio(n.parentElement);
      let l = Infinity;
      let t = Infinity;
      let r = -Infinity;
      let b = -Infinity;
      for (const q of Array.from(range.getClientRects())) {
        if (q.width <= 0 && q.height <= 0) continue;
        const cut = (q.height * (1 - k)) / 2;
        l = Math.min(l, q.left);
        t = Math.min(t, q.top + cut);
        r = Math.max(r, q.right);
        b = Math.max(b, q.bottom - cut);
      }
      if (!(r > l) || !(b > t)) continue;
      const cs = n.parentElement ? getComputedStyle(n.parentElement) : null;
      items.push({
        clip, track, kind: "text", rect: rect({ left: l, top: t, width: r - l, height: b - t }),
        opacity: round3(o), text: [...text.trim()].slice(0, 24).join(""),
        size: round(parseFloat(cs?.fontSize ?? "") || 0), color: cs?.color ?? "",
      });
    }
  }
  range.detach();
  return items;
};

/** Measures and logs each rendered frame while `enabled`; the frame is held until the line is out. */
export const useInspect = (enabled: boolean, root: RefObject<HTMLDivElement | null>, width: number, height: number) => {
  const frame = useCurrentFrame();
  useEffect(() => {
    if (!enabled) return;
    const handle = delayRender(`inspect frame ${frame}`);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      continueRender(handle);
    };
    const timers: ReturnType<typeof setTimeout>[] = [];
    // after this commit's effects (fitted text, media boxes) have settled
    timers.push(setTimeout(() => {
      try {
        const items = root.current ? measure(root.current, width, height) : [];
        // logged from a bare timer (no bundle frame on the stack): Remotion then forwards it to onBrowserLog
        // without echoing it on the renderer's stdout
        timers.push(setTimeout(console.log.bind(console, `@@inspect ${JSON.stringify({ frame, items })}`), 0));
      } catch (err) {
        console.error(`inspect failed at frame ${frame}: ${(err as Error)?.message ?? err}`);
      }
      timers.push(setTimeout(finish, 0));
    }, 0));
    return () => {
      timers.forEach(clearTimeout);
      finish();
    };
  }, [enabled, frame, root, width, height]);
};
