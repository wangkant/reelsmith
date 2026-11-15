// A webpack plugin that fails the bundle when it would pull in anything outside the renderer's own code, its npm
// packages, the workspace's component library, library/made and the workspace's own packages, and that holds library
// components to contract section 6: they import only react, remotion, installed @remotion/* packages,
// @reelsmith/kit, the packages the workspace's package.json declares and relative files inside the library folder
// or library/made. Built-in presets get the same check as warnings (they are ours, not the agent's).
import fs from "node:fs";
import path from "node:path";

const NAME = "reelsmith-import-guard";
// css-loader and style-loader write inline-loader requests for every CSS import; the bundler's own loaders run TS.
const LOADER_PACKAGES = ["css-loader", "style-loader", "@remotion/bundler"];
const PACKAGE = /^(react|react\/.+|remotion|remotion\/.+|@remotion\/[a-z0-9][a-z0-9._-]*(\/.+)?)$/;
export const KIT = "@reelsmith/kit";

// the installed package an allowed request names ("react/jsx-runtime" -> "react"); null for any other request,
// one with a "." or ".." segment included ("react/../react-dom" would reach every installed package)
export const packageOf = (request) => {
  const parts = String(request).split("/");
  if (!PACKAGE.test(request) || parts.some((s) => s === "." || s === ".." || s === "")) return null;
  return parts.slice(0, request.startsWith("@") ? 2 : 1).join("/");
};
export const dotted = (request) => PACKAGE.test(request) && packageOf(request) === null;
const ANY_PACKAGE = /^(@[a-z0-9][a-z0-9._~-]*\/)?[a-z0-9][a-z0-9._~-]*(\/.+)?$/;
// the package any bare request names ("d3-shape/dist/x" -> "d3-shape"); null for a path, a URL or a dotted segment
export const anyPackageOf = (request) => {
  const parts = String(request).split("/");
  if (!ANY_PACKAGE.test(request) || parts.some((s) => s === "." || s === ".." || s === "")) return null;
  return parts.slice(0, request.startsWith("@") ? 2 : 1).join("/");
};
// the names a workspace's package.json declares (what add_package installed)
export const declaredPackages = (workspace) => {
  if (!workspace) return [];
  try {
    const deps = JSON.parse(fs.readFileSync(path.join(workspace, "package.json"), "utf8")).dependencies;
    return deps && typeof deps === "object" ? Object.keys(deps) : [];
  } catch {
    return [];
  }
};

const norm = (p) => {
  const abs = path.resolve(String(p));
  return process.platform === "win32" ? abs.toLowerCase() : abs;
};
const within = (p, dir) => {
  const n = norm(p);
  return [].concat(dir).some((d) => n === d || n.startsWith(d + path.sep));
};
// node_modules may be a symlink or junction (a shared install); webpack reports the files at their real path
const places = (p) => {
  let real = p;
  try {
    real = fs.realpathSync.native(p);
  } catch {
    // not there yet: only the given path
  }
  return [...new Set([norm(p), norm(real)])];
};

/**
 * @param {{root: string, library: string, workspace?: string | null, warn?: (msg: string) => void}} opts
 *   root: the renderer folder; library: the folder @library points at; workspace: the folder holding package.json,
 *   node_modules and library/made
 */
export function importGuard({ root, library, workspace = null, warn = (m) => console.error(m) }) {
  const src = norm(path.join(root, "src"));
  const kit = norm(path.join(root, "src", "kit"));
  const presets = norm(path.join(root, "src", "presets"));
  const modules = places(path.join(root, "node_modules"));
  const libs = [norm(library), ...(workspace ? [norm(path.join(workspace, "library", "made"))] : [])];
  const own = workspace ? places(path.join(workspace, "node_modules")) : [];
  const declared = new Set(declaredPackages(workspace));
  const shipped = new Set(declaredPackages(root));
  const loaders = LOADER_PACKAGES.flatMap((p) => modules.map((m) => path.join(m, p)));
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
    if (!(within(file, src) || within(file, modules) || within(file, libs) || within(file, own))) {
      fail(`${what} ${file} refused: only the renderer's src/, its node_modules, the component library, library/made and the workspace's node_modules may be bundled`);
    }
  };

  const ALLOWED = `only react, remotion, @remotion/*, ${KIT}, the workspace's packages (add_package) and files in the library folder or library/made are allowed`;
  const said = (issuer, request, why) => {
    const who = `${within(issuer, libs) ? "Component" : "Preset"} ${path.basename(issuer).replace(/\.[cm]?[jt]sx?$/, "")}`;
    return `${who} imports '${request}'${why ? ` (${why})` : ""}: ${ALLOWED}`;
  };

  // contract section 6, for a request made by a component file; `file` is null before resolving
  const componentRule = (request, file, issuer) => {
    if (/[!?#]/.test(request) || /^data:/i.test(request)) return said(issuer, request, "loaders, queries and data: URIs");
    if (request.startsWith("./") || request.startsWith("../")) {
      const home = within(issuer, libs) ? libs : presets;
      return file === null || within(file, home) ? null : said(issuer, request, "it leaves the component folder");
    }
    if (request === KIT) return file === null || within(file, kit) ? null : said(issuer, request, "it did not resolve to the renderer kit");
    const pkg = packageOf(request);
    if (pkg) {
      // a @remotion/* package may also come from the workspace (a dependency of one of its packages)
      const homes = [...modules, ...(pkg.startsWith("@remotion/") ? own : [])];
      return file === null || within(file, homes.map((m) => norm(path.join(m, pkg)))) ? null
        : said(issuer, request, "it did not resolve to the renderer's installed packages");
    }
    if (dotted(request)) return said(issuer, request, "a package path may not hold . or .. segments");
    const mine = anyPackageOf(request);
    if (mine && declared.has(mine)) {
      return file === null || within(file, own.map((m) => norm(path.join(m, mine)))) ? null
        : said(issuer, request, "it did not resolve to the workspace's node_modules: add_package with no names restores them");
    }
    // the renderer's own packages (react-dom, the bundler) are not for components; add_package refuses them too
    if (mine && workspace && !shipped.has(mine)) return said(issuer, request, "not a package of this workspace: add it with add_package");
    return said(issuer, request, "");
  };

  return {
    apply(compiler) {
      compiler.hooks.normalModuleFactory.tap(NAME, (nmf) => {
        // a library request that is not allowed is refused by name before webpack tries (and fails) to resolve it
        nmf.hooks.beforeResolve.tap(NAME, (data) => {
          const issuer = (data && data.contextInfo && data.contextInfo.issuer) || "";
          const request = String((data && data.request) || "");
          if (!issuer || !request || !within(issuer, libs)) return;
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
          if (within(issuer, libs)) {
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
            if (issuer && within(issuer, libs) && !within(dir, libs)) fail(`library component ${path.basename(issuer)}: dynamic import outside the library`);
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
