// Chinese faces bundled with the renderer (SIL OFL 1.1): nothing is fetched from the network at render time.
import "@fontsource-variable/noto-sans-sc/wght.css";
import "@fontsource-variable/noto-serif-sc/wght.css";
import "@fontsource/zcool-qingke-huangyou/chinese-simplified-400.css";
import "@fontsource/zcool-qingke-huangyou/latin-400.css";
import "./fonts/smiley-sans.css";
import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";
import type { WorkspaceFont } from "./types";

/** Noto Sans SC, variable weight 100-900: body, captions, numbers. */
export const SANS = '"Noto Sans SC Variable", "Noto Sans SC", sans-serif';
/** Noto Serif SC, variable weight 200-900: quotes, a calmer or editorial voice. */
export const SERIF = '"Noto Serif SC Variable", "Noto Serif SC", serif';
/** Smiley Sans 得意黑 (one oblique weight): punchy headlines that stay legible; rare glyphs fall back to the sans. */
export const DISPLAY = '"Smiley Sans", "Noto Sans SC Variable", sans-serif';
/** ZCOOL QingKe HuangYou (one weight): a decorative poster face, hard to read for many common characters. */
export const ZCOOL = '"ZCOOL QingKe HuangYou", "Noto Sans SC Variable", sans-serif';

export const FONTS = { sans: SANS, serif: SERIF, display: DISPLAY, zcool: ZCOOL } as const;

// the workspace's families once loaded (useWorkspaceFonts): named alone, they fall back to the sans face
const WORKSPACE = new Set<string>();

/** A FONTS key, a workspace font family, or any CSS font-family. */
export const fontFamily = (font?: string | null): string =>
  font && font in FONTS
    ? FONTS[font as keyof typeof FONTS]
    : font && WORKSPACE.has(font)
      ? `"${font}", ${SANS}`
      : font || SANS;

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

const loads = new Map<string, Promise<void>>();

/** One workspace face through the FontFace API, loaded once per page. */
const loadFace = (f: WorkspaceFont): Promise<void> => {
  const key = JSON.stringify([f.family, f.src, f.weight ?? "", f.style ?? ""]);
  let p = loads.get(key);
  if (!p) {
    const descriptors: FontFaceDescriptors = { display: "block" };
    if (f.weight) descriptors.weight = f.weight;
    if (f.style) descriptors.style = f.style;
    const face = new FontFace(f.family, `url("${staticFile(f.src)}")`, descriptors);
    p = face.load().then(
      (done) => {
        document.fonts.add(done);
        WORKSPACE.add(f.family);
      },
      (err) => {
        throw new Error(`the workspace font ${f.family} (${f.src}) did not load: ${err}`);
      },
    );
    loads.set(key, p);
  }
  return p;
};

/** False until the workspace's fonts (resolved.json `fonts`) are loaded; the frame waits for them. */
export const useWorkspaceFonts = (fonts?: WorkspaceFont[] | null): boolean => {
  const list = (Array.isArray(fonts) ? fonts : []).filter(
    (f) => f && typeof f.family === "string" && typeof f.src === "string",
  );
  const key = JSON.stringify(list.map((f) => [f.family, f.src, f.weight ?? "", f.style ?? ""]));
  const [done, setDone] = useState<string | null>(list.length && typeof document !== "undefined" ? null : key);
  const [handle] = useState(() =>
    done === key ? null : delayRender("Loading the workspace's fonts", { timeoutInMilliseconds: 60000 }),
  );
  useEffect(() => {
    if (done === key) return;
    let live = true;
    Promise.all(list.map(loadFace)).then(
      () => live && setDone(key),
      (err) => cancelRender(err),
    );
    return () => {
      live = false;
    };
  }, [key]);
  useEffect(() => {
    if (done === key && handle !== null) continueRender(handle);
  }, [done, key, handle]);
  useEffect(() => () => (handle !== null ? continueRender(handle) : undefined), [handle]);
  return done === key;
};

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
