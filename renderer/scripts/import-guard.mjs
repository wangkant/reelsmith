// A webpack plugin that fails the bundle when it would pull in anything outside the renderer's own code, its npm
// packages and the workspace's component library, and that holds library components to contract section 6:
// they import only react, remotion, installed @remotion/* packages, @reelsmith/kit and relative files inside the
// library folder. Built-in presets get the same check as warnings (they are ours, not the agent's).
import fs from "node:fs";
import path from "node:path";

const NAME = "reelsmith-import-guard";
// css-loader and style-loader write inline-loader requests for every CSS import; the bundler's own loaders run TS.
const LOADER_PACKAGES = ["css-loader", "style-loader", "@remotion/bundler"];
const PACKAGE = /^(react|react\/.+|remotion|remotion\/.+|@remotion\/[a-z0-9][a-z0-9._-]*(\/.+)?)$/;
const KIT = "@reelsmith/kit";

const norm = (p) => {
  const abs = path.resolve(String(p));
  return process.platform === "win32" ? abs.toLowerCase() : abs;
};
const within = (p, dir) => {
  const n = norm(p);
  return [].concat(dir).some((d) => n === d || n.startsWith(d + path.sep));
};
// a folder as named and, when it is a link or junction (a shared node_modules), where it really is: webpack
// reports real paths
const places = (p) => {
  const named = norm(p);
  try {
    const real = norm(fs.realpathSync.native(p));
    return real === named ? named : [named, real];
  } catch {
    return named;
  }
};

/**
 * @param {{root: string, library: string, warn?: (msg: string) => void}} opts
 *   root: the renderer folder; library: the folder @library points at
 */
export function importGuard({ root, library, warn = (m) => console.error(m) }) {
  const src = norm(path.join(root, "src"));
  const kit = norm(path.join(root, "src", "kit"));
  const presets = norm(path.join(root, "src", "presets"));
  const modules = places(path.join(root, "node_modules"));
  const lib = norm(library);
  const loaders = LOADER_PACKAGES.map((p) => places(path.join(root, "node_modules", p)));
  const warned = new Set();

  const fail = (msg) => {
    throw new Error(`${NAME}: ${msg}`);
  };
  const fileOf = (resource) => String(resource || "").split("?")[0].split("#")[0];

  // where any module may come from at all
  const checkPlace = (file, what) => {
    if (!file || /^data:/i.test(file)) return;
    if (/^[a-z][a-z0-9+.-]+:/i.test(file) && !/^[a-z]:[\\/]/i.test(file)) fail(`${what} URI ${file} refused`);
    if (!path.isAbsolute(file)) fail(`${what} ${file} refused: not a file path`);
    if (!(within(file, src) || within(file, modules) || within(file, lib))) {
      fail(`${what} ${file} refused: only the renderer's src/, its node_modules and the component library may be bundled`);
    }
  };

  const ALLOWED = `only react, remotion, @remotion/*, ${KIT} and files in the same folder are allowed`;
  const said = (issuer, request, why) => {
    const who = `${within(issuer, lib) ? "Component" : "Preset"} ${path.basename(issuer).replace(/\.[cm]?[jt]sx?$/, "")}`;
    return `${who} imports '${request}'${why ? ` (${why})` : ""}: ${ALLOWED}`;
  };

  // contract section 6, for a request made by a component file; `file` is null before resolving
  const componentRule = (request, file, issuer) => {
    if (/[!?#]/.test(request) || /^data:/i.test(request)) return said(issuer, request, "loaders, queries and data: URIs");
    if (request.startsWith("./") || request.startsWith("../")) {
      const home = within(issuer, lib) ? lib : presets;
      return file === null || within(file, home) ? null : said(issuer, request, "it leaves the component folder");
    }
    if (request === KIT) return file === null || within(file, kit) ? null : said(issuer, request, "it did not resolve to the renderer kit");
    if (PACKAGE.test(request)) {
      return file === null || within(file, modules) ? null : said(issuer, request, "it did not resolve to the renderer's installed packages");
    }
    return said(issuer, request, "");
  };

  return {
    apply(compiler) {
      compiler.hooks.normalModuleFactory.tap(NAME, (nmf) => {
        // a library request that is not allowed is refused by name before webpack tries (and fails) to resolve it
        nmf.hooks.beforeResolve.tap(NAME, (data) => {
          const issuer = (data && data.contextInfo && data.contextInfo.issuer) || "";
          const request = String((data && data.request) || "");
          if (!issuer || !request || !within(issuer, lib)) return;
          const bad = componentRule(request, null, issuer);
          if (bad) fail(bad);
        });
        // covers static imports, dynamic import(), require(), new URL(..., import.meta.url) and context members
        nmf.hooks.afterResolve.tap(NAME, (data) => {
          const made = (data && data.createData) || {};
          const file = fileOf((made.resourceResolveData && made.resourceResolveData.path) || made.resource);
          checkPlace(file, "module");
          for (const l of made.loaders || []) {
            if (!loaders.some((d) => within(l.loader, d))) fail(`loader ${l.loader} refused: only css-loader and style-loader may run inline`);
          }
          const issuer = (data.contextInfo && data.contextInfo.issuer) || "";
          const request = String(data.request || "");
          if (!issuer || !request) return;
          if (within(issuer, lib)) {
            const bad = componentRule(request, file, issuer);
            if (bad) fail(bad);
          } else if (within(issuer, presets)) {
            const bad = componentRule(request, file, issuer);
            if (bad && !warned.has(bad)) {
              warned.add(bad);
              warn(`${NAME}: warning: ${bad}`);
            }
          }
        });
      });
      compiler.hooks.contextModuleFactory.tap(NAME, (cmf) => {
        // a require.context / import.meta.webpackContext folder: its file names would land in the bundle
        cmf.hooks.afterResolve.tap(NAME, (data) => {
          if (!data) return;
          const issuer = (data.contextInfo && data.contextInfo.issuer) || "";
          for (const dir of [].concat(data.resource || [])) {
            checkPlace(fileOf(dir), "context folder");
            if (issuer && within(issuer, lib) && !within(dir, lib)) fail(`library component ${path.basename(issuer)}: dynamic import outside the library`);
          }
        });
      });
    },
  };
}

/**
 * Narrows require.context folders to the files a film uses, so a broken, unused component cannot fail the bundle.
 * @param {Array<{dir: string, names: string[]}>} folders
 */
export function narrowContexts(folders) {
  const NAME2 = "reelsmith-narrow-contexts";
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const table = folders.map(({ dir, names }) => ({
    dir: norm(dir),
    re: names.length ? new RegExp(`^\\./(${names.map(esc).join("|")})\\.tsx$`) : /^\.\/\0$/,
  }));
  return {
    apply(compiler) {
      compiler.hooks.contextModuleFactory.tap(NAME2, (cmf) => {
        cmf.hooks.afterResolve.tap(NAME2, (data) => {
          if (!data || typeof data.resource !== "string") return;
          const hit = table.find((t) => norm(data.resource) === t.dir);
          if (hit) data.regExp = hit.re;
        });
      });
    },
  };
}
