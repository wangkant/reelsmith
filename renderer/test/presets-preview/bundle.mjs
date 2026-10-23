// Shared by render.mjs and check.mjs: bundle the preview (@reelsmith/kit -> src/kit, as in scripts/render.mjs) and
// render stills with one browser, collecting each still's "@@probe" line.
import { bundle } from "@remotion/bundler";
import { getCompositions, openBrowser, renderStill } from "@remotion/renderer";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const renderer = path.resolve(here, "..", "..");

export const bundlePreview = async () => {
  const kit = path.join(renderer, "src", "kit", "index.ts");
  return bundle({
    entryPoint: path.join(here, "index.ts"),
    publicDir: path.join(here, "public"),
    webpackOverride: (c) => ({
      ...c,
      resolve: {
        ...c.resolve,
        alias: { ...(c.resolve?.alias ?? {}), "@reelsmith/kit": kit },
        // the example library component lives outside renderer/, so bare imports resolve from renderer/node_modules
        modules: [path.join(renderer, "node_modules"), "node_modules"],
      },
    }),
  });
};

/** jobs: [{id, frame}]; writes <out>/<id>_<frame>.png and returns {"<id>_<frame>": probe | null}. */
export const renderJobs = async (serveUrl, jobs, out) => {
  const comps = new Map((await getCompositions(serveUrl)).map((c) => [c.id, c]));
  fs.mkdirSync(out, { recursive: true });
  const browser = await openBrowser("chrome", { logLevel: "error" });
  const probes = {};
  const errors = [];
  try {
    for (const { id, frame } of jobs) {
      const composition = comps.get(id);
      if (!composition) {
        errors.push(`no composition ${id}`);
        continue;
      }
      const key = `${id}_${frame}`;
      let last = null;
      await renderStill({
        serveUrl, composition, output: path.join(out, `${key}.png`), frame: Math.min(frame, composition.durationInFrames - 1),
        imageFormat: "png", overwrite: true, puppeteerInstance: browser, logLevel: "error",
        onBrowserLog: (log) => {
          if (log.text.startsWith("@@probe ")) last = JSON.parse(log.text.slice(8));
          else if (log.type === "error") errors.push(`${key}: ${log.text}`);
        },
      });
      probes[key] = last;
    }
  } finally {
    await browser.close({ silent: true });
  }
  return { probes, errors, ids: [...comps.keys()] };
};
