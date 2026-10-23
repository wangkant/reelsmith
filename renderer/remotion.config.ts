// Used by the Remotion CLI and Studio only; scripts/render.mjs sets the same options itself.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Config } from "@remotion/cli/config";
import { importGuard } from "./scripts/import-guard.mjs";

Config.setEntryPoint("src/index.ts");
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(95);
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");
Config.setColorSpace("bt709");
Config.setCrf(18);
Config.setOverwriteOutput(true);

// The CLI evaluates this file with the renderer folder as cwd.
const root = process.cwd();
const library = process.env.REELSMITH_LIBRARY
  ? path.resolve(process.env.REELSMITH_LIBRARY)
  : path.join(os.tmpdir(), "reelsmith-empty-library");
fs.mkdirSync(library, { recursive: true });

Config.overrideWebpackConfig((config) => ({
  ...config,
  resolve: {
    ...(config.resolve ?? {}),
    alias: {
      ...((config.resolve?.alias as Record<string, string>) ?? {}),
      "@reelsmith/kit$": path.join(root, "src", "kit", "index.ts"),
      "@library": library,
    },
    modules: [path.join(root, "node_modules"), "node_modules"],
  },
  plugins: [...(config.plugins ?? []), importGuard({ root, library })],
}));
