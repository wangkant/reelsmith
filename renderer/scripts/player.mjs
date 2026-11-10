// node scripts/player.mjs <outDir> [--library <dir>]
// Builds the live player (src/player/) into static files in <outDir>: index.html, bundle.js and the fonts. Unlike
// render.mjs the bundle holds every preset and every library component (the film changes while the page stays
// open) and no project files: the page fetches them from /project/ at run time. A library component that does not
// compile, or imports what contract section 6 forbids, is left out (its name and why go into the page) instead of
// failing the build. Prints one JSON line: {"ok": true, "outDir", "ms", "components", "skipped"} or {"ok": false, "error"}.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import * as esbuild from "esbuild";
import { KIT, dotted, importGuard, narrowContexts, packageOf } from "./import-guard.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "src");
const require = createRequire(import.meta.url);
const PROBING = Symbol("probing");
const CODE = /\.[cm]?[jt]sx?$/i;

const finish = (result, code) => process.stdout.write(`${JSON.stringify(result)}\n`, () => process.exit(code));

const parseArgs = (argv) => {
  let outDir = null;
  let library = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--library") library = argv[++i];
    else if (argv[i].startsWith("--library=")) library = argv[i].slice("--library=".length);
    else if (!outDir) outDir = argv[i];
    else throw new Error(`unexpected argument "${argv[i]}"`);
  }
  if (!outDir || library === undefined) throw new Error("usage: node scripts/player.mjs <outDir> [--library <dir>]");
  return { outDir: path.resolve(outDir), library: library ? path.resolve(library) : null };
};

const libraryDir = (asked) => {
  if (asked && fs.existsSync(asked)) {
    if (!fs.statSync(asked).isDirectory()) throw new Error(`--library is not a folder: ${asked}`);
    return asked;
  }
  // render.mjs's empty stand-in: a workspace that has not written a component yet
  const dir = path.join(os.tmpdir(), "reelsmith-empty-library");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
};

const within = (file, dir) => {
  const rel = path.relative(dir, file);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
};

const real = (p) => {
  try {
    return fs.realpathSync.native(p);
  } catch {
    return p;
  }
};

/** Compiles one library component on its own (esbuild; packages are resolved in the renderer's node_modules, as
 * webpack will, then left external): null, or why it cannot be bundled. */
const probe = async (file, library) => {
  const name = path.basename(file, ".tsx");
  const refuse = (request, why) =>
    `Component ${name} imports '${request}'${why ? ` (${why})` : ""}: only react, remotion, @remotion/*, ${KIT} and files in the same folder are allowed`;
  const guard = {
    name: "guard",
    setup(b) {
      b.onResolve({ filter: /.*/ }, async (args) => {
        if (args.kind === "entry-point" || args.pluginData === PROBING) return undefined;
        const req = args.path;
        if (/[!?#]/.test(req) || /^data:/i.test(req)) return { errors: [{ text: refuse(req, "loaders, queries and data: URIs") }] };
        if (req.startsWith("./") || req.startsWith("../")) {
          const target = path.resolve(args.resolveDir, req);
          if (!within(target, library)) return { errors: [{ text: refuse(req, "it leaves the component folder") }] };
          // css, images and fonts go through webpack's loaders; only code is compiled here
          if (CODE.test(req) || !path.extname(req)) return undefined;
          return fs.existsSync(target) ? { path: target, external: true } : { errors: [{ text: `Component ${name} imports '${req}', which is not there` }] };
        }
        if (req === KIT) return { path: req, external: true };
        const pkg = packageOf(req);
        if (pkg) {
          const r = await b.resolve(req, { resolveDir: ROOT, kind: args.kind, pluginData: PROBING });
          const home = path.join(ROOT, "node_modules", pkg);
          if (r.errors.length || !(within(r.path, home) || within(real(r.path), real(home)))) {
            return { errors: [{ text: refuse(req, "it is not installed in the renderer") }] };
          }
          return { path: req, external: true };
        }
        return { errors: [{ text: refuse(req, dotted(req) ? "a package path may not hold . or .. segments" : "") }] };
      });
    },
  };
  try {
    await esbuild.build({
      entryPoints: [file], bundle: true, write: false, format: "esm", platform: "browser", logLevel: "silent",
      jsx: "automatic", loader: { ".tsx": "tsx", ".ts": "ts" }, plugins: [guard],
    });
    return null;
  } catch (err) {
    const e = (err.errors ?? [])[0];
    if (!e) return String(err.message ?? err);
    // library files as the agent knows them: relative to the workspace (library/components/X.tsx)
    const at = e.location ? `${path.relative(path.dirname(path.dirname(library)), path.resolve(e.location.file)).replace(/\\/g, "/")}:${e.location.line}: ` : "";
    return `${at}${e.text}`;
  }
};

const page = (skipped) => `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>reelsmith player</title>
<link rel="icon" href="data:,">
<style>html, body, #root { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
<script>
window.remotion_staticBase = "/project";
window.remotion_isPlayer = true;
window.reelsmith_player = ${JSON.stringify({ skipped }).replace(/</g, "\\u003c")};
</script>
</head>
<body>
<div id="root"></div>
<script src="bundle.js"></script>
</body>
</html>
`;

const main = async () => {
  const t0 = Date.now();
  const args = parseArgs(process.argv.slice(2));
  const library = libraryDir(args.library);
  const names = fs.readdirSync(library).filter((f) => /^[A-Za-z0-9_]+\.tsx$/.test(f)).map((f) => f.slice(0, -4)).sort();
  const skipped = {};
  await Promise.all(names.map(async (n) => {
    const why = await probe(path.join(library, `${n}.tsx`), library);
    if (why) skipped[n] = why;
  }));
  const good = names.filter((n) => !skipped[n]);

  // a fresh folder next to the old one, swapped in at the end: the old player keeps serving until then
  fs.mkdirSync(path.dirname(args.outDir), { recursive: true });
  const tmp = fs.mkdtempSync(`${args.outDir}.build-`);
  const warnings = [];
  try {
    await bundle({
      entryPoint: path.join(SRC, "player", "index.tsx"),
      ignoreRegisterRootWarning: true,
      rootDir: ROOT,
      outDir: tmp,
      // nothing to copy: project files are fetched from /project/ at run time
      publicDir: path.join(tmp, "no-public"),
      // webpack's file cache would live in node_modules, which may be a shared install
      enableCaching: false,
      webpackOverride: (config) => ({
        ...config,
        // the bundler's own environment setup (window.process.env), then the player instead of the Studio's entry
        entry: [path.join(path.dirname(require.resolve("@remotion/bundler")), "setup-environment.js"), path.join(SRC, "player", "index.tsx")],
        resolve: {
          ...(config.resolve ?? {}),
          alias: {
            ...((config.resolve && config.resolve.alias) || {}),
            "@reelsmith/kit$": path.join(SRC, "kit", "index.ts"),
            "@library": library,
          },
          modules: [path.join(ROOT, "node_modules"), "node_modules"],
        },
        plugins: [
          ...(config.plugins ?? []),
          importGuard({ root: ROOT, library, warn: (m) => warnings.push(m) }),
          narrowContexts([{ dir: library, names: good }]),
        ],
      }),
    });
    fs.writeFileSync(path.join(tmp, "index.html"), page(skipped), "utf8");
    fs.rmSync(args.outDir, { recursive: true, force: true, maxRetries: 5 });
    fs.renameSync(tmp, args.outDir);
  } catch (err) {
    fs.rmSync(tmp, { recursive: true, force: true });
    const text = String(err?.message ?? err);
    const guard = text.match(/reelsmith-import-guard: ([^\n]*)/);
    throw new Error(guard ? guard[1] : text.split("\n").slice(0, 12).join("\n"));
  }
  return { ok: true, outDir: args.outDir, ms: Date.now() - t0, components: good, skipped, warnings };
};

main().then(
  (r) => finish(r, 0),
  (err) => finish({ ok: false, error: String(err?.message ?? err) }, 1),
);
