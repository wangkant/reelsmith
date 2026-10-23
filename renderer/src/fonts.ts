// Chinese faces bundled with the renderer (SIL OFL 1.1): nothing is fetched from the network at render time.
import "@fontsource-variable/noto-sans-sc/wght.css";
import "@fontsource-variable/noto-serif-sc/wght.css";
import "@fontsource/zcool-qingke-huangyou/chinese-simplified-400.css";
import "@fontsource/zcool-qingke-huangyou/latin-400.css";
import "./fonts/smiley-sans.css";
import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender } from "remotion";

/** Noto Sans SC, variable weight 100-900: body, captions, numbers. */
export const SANS = '"Noto Sans SC Variable", "Noto Sans SC", sans-serif';
/** Noto Serif SC, variable weight 200-900: quotes, a calmer or editorial voice. */
export const SERIF = '"Noto Serif SC Variable", "Noto Serif SC", serif';
/** Smiley Sans 得意黑 (one oblique weight): punchy headlines that stay legible; rare glyphs fall back to the sans. */
export const DISPLAY = '"Smiley Sans", "Noto Sans SC Variable", sans-serif';
/** ZCOOL QingKe HuangYou (one weight): a decorative poster face, hard to read for many common characters. */
export const ZCOOL = '"ZCOOL QingKe HuangYou", "Noto Sans SC Variable", sans-serif';

export const FONTS = { sans: SANS, serif: SERIF, display: DISPLAY, zcool: ZCOOL } as const;

/** A FONTS key or any CSS font-family. */
export const fontFamily = (font?: string | null): string =>
  font && font in FONTS ? FONTS[font as keyof typeof FONTS] : font || SANS;

const FAMILIES = ["Noto Sans SC Variable", "Noto Serif SC Variable", "ZCOOL QingKe HuangYou", "Smiley Sans"];

// The CJK faces are split into ~100 unicode-range slices the browser fetches only once a glyph needs one, which
// can land after the frame is shot; load every slice before the first frame instead.
const loadAll = async (): Promise<number> => {
  for (let attempt = 0; attempt < 100; attempt++) {
    const faces = [...document.fonts].filter((f) => FAMILIES.includes(f.family.replace(/^["']|["']$/g, "")));
    const present = new Set(faces.map((f) => f.family.replace(/^["']|["']$/g, "")));
    if (present.size === FAMILIES.length) {
      await Promise.all(faces.map((f) => f.load()));
      return faces.length;
    }
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("bundled CJK @font-face rules never registered");
};

let loaded = false;
const ready: Promise<void> =
  typeof document === "undefined"
    ? Promise.resolve()
    : (() => {
        const handle = delayRender("Loading bundled CJK fonts", { timeoutInMilliseconds: 60000 });
        return loadAll().then(
          () => {
            loaded = true;
            continueRender(handle);
          },
          (err) => cancelRender(err),
        );
      })();

/** False until every bundled face is loaded. Text measured before that (fitText caches it) would keep fallback
 *  metrics for the whole render, so the film draws nothing until this turns true; the frame waits for the
 *  re-render through its own delayRender. */
export const useFontsReady = (): boolean => {
  const [ok, setOk] = useState(loaded);
  const [handle] = useState(() => (loaded ? null : delayRender("Waiting for the first render with fonts")));
  useEffect(() => {
    if (ok) return;
    let live = true;
    ready.then(() => live && setOk(true));
    return () => {
      live = false;
    };
  }, [ok]);
  // released once the render with fonts has committed, or on unmount
  useEffect(() => {
    if (ok && handle !== null) continueRender(handle);
  }, [ok, handle]);
  useEffect(() => () => (handle !== null ? continueRender(handle) : undefined), [handle]);
  return ok;
};
