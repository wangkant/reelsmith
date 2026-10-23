// node scripts/render.mjs film|stills|inspect <resolved.json> <project dir> <out> [frame ...]
//   film     <out> = the mp4 to write (h264 crf 18, yuv420p, bt709, jpeg 95 frames)
//   stills   <out> = a folder; each frame -> <out>/still_<frame>.png
//   inspect  <out> = a folder; stills as above plus <out>/inspect.json = {"frames": [{"frame", "png", "items"}]}
// One bundle per call; the public dir is the project dir; @reelsmith/kit -> src/kit, @library -> $REELSMITH_LIBRARY
// (an empty folder when unset); the import guard enforces contract section 6. Progress lines go to stdout and the
// last stdout line is JSON: {"ok": true, ..., "bundleMs", "renderMs", "timings", "port"} or
// {"ok": false, "stage", "error", "browserErrors", "timings"}. `timings` is ms per stage (bundle, browser,
// composition, render, cleanup, total); `port` is the local server port this call used (each call picks a free one).
// Failure stages of note:
//   "component" - a component crashed or is missing ("component", "source" = file:line name it);
//   "infra"     - with "transient": true and "during": the stage it hit; a plain retry may pass (socket, network,
//                 browser or compositor errors), nothing in the project needs changing.
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { openBrowser, renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import { importGuard, narrowContexts } from "./import-guard.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "src");
const MODES = ["film", "stills", "inspect"];
const MAX_FRAMES = 600;
const MARK = "@@inspect ";
const TIMEOUT_MS = 120000;
const FAKE = process.env.REELSMITH_FAKE_SOCKET_ERROR;

const clip = (text, n = 3000) => (text.length > n ? `${text.slice(0, n)}…` : text);
const log = (line) => process.stdout.write(`${line}\n`);

const finish = (result, code) => {
  process.stdout.write(`${JSON.stringify(result)}\n`, () => process.exit(code));
};

class Stop extends Error {
  constructor(stage, message, extra = {}) {
    super(message);
    this.stage = stage;
    this.extra = extra;
  }
}

// ------------------------------------------------------------------ arguments

const parseArgs = (argv) => {
  const [mode, resolvedPath, projectDir, out, ...rest] = argv;
  const usage = "usage: node scripts/render.mjs film|stills|inspect <resolved.json> <project dir> <out> [frame ...]";
  if (!MODES.includes(mode)) throw new Stop("args", `unknown mode "${mode ?? ""}"; ${usage}`);
  if (!resolvedPath || !projectDir || !out) throw new Stop("args", usage);
  if (!fs.existsSync(resolvedPath) || !fs.statSync(resolvedPath).isFile()) throw new Stop("args", `resolved.json not found: ${resolvedPath}`);
  if (!fs.existsSync(projectDir) || !fs.statSync(projectDir).isDirectory()) throw new Stop("args", `project dir not found: ${projectDir}`);
  const frames = [];
  for (const item of rest) {
    if (!/^\d{1,7}$/.test(item)) throw new Stop("args", `frame "${item}" is not a whole number`);
    frames.push(Number(item));
  }
  if (mode !== "film" && frames.length === 0) throw new Stop("args", `${mode} needs at least one frame number`);
  if (frames.length > MAX_FRAMES) throw new Stop("args", `${frames.length} frames asked; at most ${MAX_FRAMES} per call`);
  if (mode === "film" && frames.length) throw new Stop("args", "film takes no frame numbers");
  return { mode, resolvedPath: path.resolve(resolvedPath), projectDir: path.resolve(projectDir), out: path.resolve(out), frames };
};

const readResolved = (file) => {
  let r;
  try {
    r = JSON.parse(fs.readFileSync(file, "utf8").replace(/^﻿/, ""));
  } catch (err) {
    throw new Stop("input", `resolved.json is not valid JSON: ${err.message}`);
  }
  const bad = [];
  for (const k of ["fps", "width", "height", "durationInFrames"]) {
    if (!(Number.isFinite(r?.[k]) && r[k] > 0)) bad.push(`${k} must be a positive number`);
  }
  if (!Array.isArray(r?.tracks)) bad.push("tracks must be a list");
  if (r?.audio !== undefined && !Array.isArray(r.audio)) bad.push("audio must be a list");
  if (bad.length) throw new Stop("input", `resolved.json: ${bad.join("; ")}`);
  return r;
};

/** Component names a film uses (visual tracks only; components appear nowhere else). */
const componentNames = (r) => {
  const names = new Set();
  for (const t of r.tracks) {
    if (t?.kind !== "visual" || t.hidden) continue;
    for (const c of t.clips ?? []) {
      if (c?.type === "component" && typeof c.content?.name === "string" && /^[A-Za-z0-9_]+$/.test(c.content.name)) names.add(c.content.name);
    }
  }
  return [...names].sort();
};

// ------------------------------------------------------------------ library folder

const libraryDir = () => {
  const env = process.env.REELSMITH_LIBRARY;
  if (env) {
    const dir = path.resolve(env);
    if (fs.existsSync(dir)) {
      if (!fs.statSync(dir).isDirectory()) throw new Stop("args", `REELSMITH_LIBRARY is not a folder: ${dir}`);
      return dir;
    }
    // a workspace that has not written a component yet
    log(`library ${dir} does not exist; using no library components`);
  }
  // a stable path keeps webpack's cache key stable across calls
  const dir = path.join(os.tmpdir(), "reelsmith-empty-library");
  fs.mkdirSync(dir, { recursive: true });
  for (const name of fs.readdirSync(dir)) fs.rmSync(path.join(dir, name), { recursive: true, force: true });
  return dir;
};

// ------------------------------------------------------------------ server port

const HOSTS = ["::1", "127.0.0.1", "::", "0.0.0.0"];

const listenOnce = (port, host) =>
  new Promise((resolve) => {
    const srv = net.createServer();
    srv.unref();
    // a host this machine has no address for cannot clash
    srv.on("error", (err) => resolve(err && (err.code === "EADDRNOTAVAIL" || err.code === "EAFNOSUPPORT") ? port : null));
    srv.listen({ port, host }, () => {
      const got = srv.address().port;
      srv.close(() => resolve(got));
    });
  });

/** A port the OS just handed out and that is free on every host Remotion checks. Remotion's own search starts at
 *  3000 in every process, so two renders at once could pick the same port and load (or close) each other's server. */
const freePort = async () => {
  for (let i = 0; i < 20; i++) {
    const port = await listenOnce(0, "0.0.0.0");
    if (!port) continue;
    let ok = true;
    for (const host of HOSTS) if ((await listenOnce(port, host)) !== port) ok = false;
    if (ok) return port;
  }
  return undefined;
};

// ------------------------------------------------------------------ errors

let libraryRoot = null;

/** A source-mapped path as the agent knows it: library files relative to the workspace, the rest to the renderer. */
const showPath = (src) => {
  const abs = path.resolve(ROOT, src);
  if (libraryRoot) {
    const base = path.dirname(path.dirname(libraryRoot));
    const rel = path.relative(libraryRoot, abs);
    if (!rel.startsWith("..") && !path.isAbsolute(rel)) return path.relative(base, abs).replace(/\\/g, "/");
  }
  return src;
};

// Library, bundle and runner frames say nothing an agent can fix; its own component's lines, source-mapped, do.
const describe = async (err, bundleDir = null) => {
  const msg = String((err && err.message) || err);
  const stack = String((err && err.stack) || "");
  const lines = (stack.includes(msg) ? stack : `${msg}\n${stack}`)
    .split("\n")
    .filter((l) => l.trim() && l.trim() !== "undefined")
    .filter((l) => !/^\s*at .*(node_modules|node:|bundle\.js|__puppeteer|render\.mjs)/.test(l));
  const frames = bundleDir ? await sourceFrames((err && err.stackFrame) || [], bundleDir) : [];
  return { text: clip([...lines.slice(0, 12), ...frames.map((f) => f.line)].join("\n")), frames, message: msg };
};

const sourceFrames = async (frames, bundleDir) => {
  let SourceMapConsumer;
  try {
    ({ SourceMapConsumer } = await import("source-map"));
  } catch {
    return [];
  }
  const out = [];
  const maps = new Map();
  for (const f of frames) {
    const name = String(f.fileName || "").split("/").pop();
    const file = path.join(bundleDir, `${name}.map`);
    if (!name.endsWith(".js") || !fs.existsSync(file) || f.lineNumber == null) continue;
    try {
      if (!maps.has(file)) maps.set(file, await new SourceMapConsumer(JSON.parse(fs.readFileSync(file, "utf8"))));
      // DevTools call frames count lines and columns from 0; source-map lines count from 1
      const pos = maps.get(file).originalPositionFor({ line: f.lineNumber + 1, column: f.columnNumber || 0 });
      if (pos.source && !pos.source.includes("node_modules")) {
        const src = showPath(pos.source.replace(/^webpack:\/\/[^/]*\//, "").replace(/^\.\//, ""));
        const text = ((maps.get(file).sourceContentFor(pos.source, true) || "").split("\n")[pos.line - 1] || "").trim();
        const fn = f.functionName || pos.name || "?";
        out.push({ fn, src, at: `${src}:${pos.line}`, line: `    at ${fn} (${src}:${pos.line})${text ? `  ->  ${clip(text, 160)}` : ""}` });
      }
    } catch {
      // an unreadable map only costs the location
    }
    if (out.length >= 6) break;
  }
  for (const m of maps.values()) m.destroy?.();
  return out;
};

// Errors a plain retry can fix: the local server's sockets, the browser connection, the video frame server.
const TRANSIENT = [
  /net::ERR_(SOCKET_NOT_CONNECTED|CONNECTION_(ABORTED|REFUSED|RESET|CLOSED|FAILED)|EMPTY_RESPONSE|NETWORK_CHANGED|ADDRESS_IN_USE)/,
  /NetworkError: A network error occurred/,
  /\b(ECONNRESET|ECONNREFUSED|ECONNABORTED|EPIPE|EADDRINUSE)\b/,
  /Compositor error: No frame found|Could not extract frame from compositor|Compositor quit/,
  /Target closed|Session closed|Browser has disconnected|browser has been closed/i,
  /You specified port \d+ to be used for the HTTP server|No available ports found/,
];

const COMPONENT = /component "?([A-Za-z0-9_]+)"? (crashed: |not found: |\((?:library|preset)\) has no default export)/;

/** A thrown error as a failure: its own stage for a component, "infra" for transient errors, else `stage`. */
const failure = async (stage, err, bundleDir, extra = {}) => {
  const d = await describe(err, bundleDir);
  const comp = d.message.match(COMPONENT);
  if (comp) {
    const name = comp[1];
    if (comp[2] !== "crashed: ") {
      // missing or without a default export: the renderer's own frames would only point at the lookup
      return new Stop("component", d.message.replace(/^Error: /, ""), { ...extra, component: name });
    }
    // the component's (or preset's) own line, not the kit or renderer code it called
    const own = d.frames.find((f) => !/^src\/(?!presets\/)/.test(f.src)) ?? d.frames[0];
    const kind = (`${d.text}\n${d.message}`.match(/([A-Za-z]*Error): component /) ?? [])[1] ?? "Error";
    const what = d.message.slice(d.message.indexOf(comp[0]) + comp[0].length);
    const head = `component ${name} crashed${own ? ` at ${own.at}` : ""}: ${kind}: ${what}`;
    return new Stop("component", clip([head, ...d.frames.map((f) => f.line)].join("\n")), {
      ...extra, component: name, ...(own ? { source: own.at } : {}),
    });
  }
  const seen = [d.text, ...state.browserErrors].join("\n");
  if (TRANSIENT.some((re) => re.test(seen))) return new Stop("infra", d.text, { ...extra, transient: true, during: stage });
  return new Stop(stage, d.text, extra);
};

// ------------------------------------------------------------------ main

const main = async (state) => {
  const t0 = Date.now();
  const timings = state.timings;
  const lap = (name, since) => {
    timings[name] = (timings[name] ?? 0) + (Date.now() - since);
  };
  const args = parseArgs(process.argv.slice(2));
  const resolved = readResolved(args.resolvedPath);
  if (args.mode === "inspect") resolved.inspect = true;
  const library = libraryDir();
  libraryRoot = library;
  const used = componentNames(resolved);
  const inputProps = { resolved, mode: args.mode };

  state.bundleDir = fs.mkdtempSync(path.join(os.tmpdir(), "reelsmith-bundle-"));
  let lastPct = -1;
  let serveUrl;
  const guardWarnings = [];
  try {
    serveUrl = await bundle({
      entryPoint: path.join(SRC, "index.ts"),
      rootDir: ROOT,
      outDir: state.bundleDir,
      publicDir: args.projectDir,
      enableCaching: true,
      onProgress: (p) => {
        const pct = Math.floor(p / 25) * 25;
        if (pct !== lastPct) {
          lastPct = pct;
          log(`bundle ${pct}%`);
        }
      },
      webpackOverride: (config) => ({
        ...config,
        resolve: {
          ...(config.resolve ?? {}),
          alias: {
            ...((config.resolve && config.resolve.alias) || {}),
            "@reelsmith/kit$": path.join(SRC, "kit", "index.ts"),
            "@library": library,
          },
          // library files live outside the renderer: their package imports resolve here first
          modules: [path.join(ROOT, "node_modules"), "node_modules"],
        },
        plugins: [
          ...(config.plugins ?? []),
          importGuard({ root: ROOT, library, warn: (m) => guardWarnings.push(m) }),
          narrowContexts([
            { dir: path.join(SRC, "presets"), names: used },
            { dir: library, names: used },
          ]),
        ],
      }),
    });
  } catch (err) {
    const d = await describe(err);
    // the guard's own sentence, without webpack's resolve trace around it
    const guard = d.text.match(/reelsmith-import-guard: ([^\n]*)/);
    throw new Stop("bundle", guard ? guard[1] : d.text);
  } finally {
    lap("bundle", t0);
  }
  for (const w of guardWarnings) log(w);
  const bundleMs = Date.now() - t0;

  const browserErrors = [];
  const inspectLines = [];
  const onBrowserLog = (entry) => {
    const text = String(entry.text ?? "");
    if (text.startsWith(MARK)) {
      if (args.mode === "inspect") inspectLines.push(text.slice(MARK.length));
      return;
    }
    // an object logged without text says nothing
    if (/^JSHandle@\w+$/.test(text.trim())) return;
    const short = clip(text, 600);
    if (entry.type === "error" && browserErrors.length < 20 && !browserErrors.includes(short)) browserErrors.push(short);
  };
  state.browserErrors = browserErrors;
  const b0 = Date.now();
  try {
    state.browser = await openBrowser("chrome", { logLevel: "error" });
  } catch (err) {
    throw await failure("browser", err, null);
  } finally {
    lap("browser", b0);
  }
  let port = await freePort();
  state.port = port;

  let composition;
  const c0 = Date.now();
  try {
    composition = await selectComposition({
      serveUrl, id: "Film", inputProps, puppeteerInstance: state.browser, logLevel: "error", onBrowserLog,
      timeoutInMilliseconds: TIMEOUT_MS, port,
    });
  } catch (err) {
    throw await failure("composition", err, state.bundleDir);
  } finally {
    lap("composition", c0);
  }
  const { fps, durationInFrames, width, height } = composition;
  const base = { fps, durationInFrames, width, height, components: used, bundleMs };

  if (args.mode === "film") {
    fs.mkdirSync(path.dirname(args.out), { recursive: true });
    const concurrency = Math.max(1, Math.min(6, os.cpus().length - 2));
    let last = -1;
    const r0 = Date.now();
    try {
      await renderMedia({
        serveUrl, composition, inputProps, outputLocation: args.out, codec: "h264", crf: 18, pixelFormat: "yuv420p",
        colorSpace: "bt709", imageFormat: "jpeg", jpegQuality: 95, concurrency, overwrite: true, enforceAudioTrack: true,
        puppeteerInstance: state.browser, logLevel: "error", onBrowserLog, timeoutInMilliseconds: TIMEOUT_MS, port,
        onProgress: ({ progress, renderedFrames }) => {
          const pct = Math.floor(progress * 20) * 5;
          if (pct !== last) {
            last = pct;
            log(`render ${pct}% (${renderedFrames}/${durationInFrames} frames)`);
          }
        },
      });
    } catch (err) {
      throw await failure("render", err, state.bundleDir);
    } finally {
      lap("render", r0);
    }
    return { ok: true, mode: "film", out: args.out, ...base, renderMs: Date.now() - r0, browserErrors };
  }

  // stills / inspect
  fs.mkdirSync(args.out, { recursive: true });
  const notes = [];
  const frames = [];
  for (const asked of args.frames) {
    let fr = asked;
    if (fr > durationInFrames - 1) {
      notes.push(`frame ${asked} is past the end (last frame ${durationInFrames - 1}); rendered ${durationInFrames - 1}`);
      fr = durationInFrames - 1;
    }
    if (!frames.includes(fr)) frames.push(fr);
  }
  frames.sort((a, b) => a - b);
  const stills = [];
  const inspected = [];
  const r0 = Date.now();
  for (const [i, frame] of frames.entries()) {
    const png = path.join(args.out, `still_${String(frame).padStart(5, "0")}.png`);
    const s0 = Date.now();
    inspectLines.length = 0;
    for (let attempt = 0; ; attempt++) {
      try {
        // test hook (renderer self-test): fail as a dropped local socket does, on the first try or on every try
        if (FAKE === "always" || (FAKE === "once" && attempt === 0)) {
          throw new Error("net::ERR_SOCKET_NOT_CONNECTED at http://localhost:3000/index.html");
        }
        await renderStill({
          serveUrl, composition, inputProps, frame, output: png, imageFormat: "png", overwrite: true,
          puppeteerInstance: state.browser, logLevel: "error", onBrowserLog, timeoutInMilliseconds: TIMEOUT_MS, port,
        });
        break;
      } catch (err) {
        const stop = await failure("render", err, state.bundleDir, { frame, stills });
        // one still is cheap to redo: once, on a fresh port
        if (stop.stage !== "infra" || attempt > 0) {
          lap("render", r0);
          throw stop;
        }
        log(`still frame ${frame}: ${stop.message.split("\n")[0]}; retrying once`);
        port = await freePort();
        state.port = port;
        inspectLines.length = 0;
      }
    }
    stills.push({ frame, png, ms: Date.now() - s0 });
    log(`still ${i + 1}/${frames.length} frame ${frame} (${Date.now() - s0} ms)`);
    if (args.mode === "inspect") {
      // the page may render other frames on the way; keep the line for this one
      const line = [...inspectLines].reverse().map((l) => JSON.parse(l)).find((x) => x.frame === frame);
      if (!line) throw new Stop("inspect", `no @@inspect line for frame ${frame}`, { frame, stills });
      inspected.push({ frame, png, items: line.items });
    }
  }
  lap("render", r0);
  const result = {
    ok: true, mode: args.mode, ...base, renderMs: Date.now() - r0, files: stills.map((s) => s.png), stills, notes, browserErrors,
  };
  if (args.mode === "inspect") {
    const file = path.join(args.out, "inspect.json");
    fs.writeFileSync(file, JSON.stringify({ frames: inspected }), "utf8");
    result.inspect = file;
    result.items = inspected.reduce((n, x) => n + x.items.length, 0);
  }
  return result;
};

const state = { browser: null, bundleDir: null, browserErrors: [], timings: {}, port: null };
const started = Date.now();
main(state)
  .then((result) => [result, 0])
  .catch(async (err) => {
    const stop = err instanceof Stop ? err : await failure("unexpected", err, null);
    return [{ ok: false, stage: stop.stage, error: stop.message, ...stop.extra, browserErrors: state.browserErrors }, stop.stage === "args" ? 2 : 1];
  })
  .then(async ([result, code]) => {
    // cleanup first: exiting inside finish() would skip it
    const k0 = Date.now();
    if (state.browser) await state.browser.close({ silent: true }).catch(() => undefined);
    if (state.bundleDir) fs.rmSync(state.bundleDir, { recursive: true, force: true });
    state.timings.cleanup = Date.now() - k0;
    state.timings.total = Date.now() - started;
    finish({ ...result, timings: state.timings, ...(state.port ? { port: state.port } : {}) }, code);
  });
