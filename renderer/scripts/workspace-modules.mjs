// Where bare imports resolve when a workspace brings npm packages of its own (add_package): library components find
// the workspace's node_modules first, a workspace package finds its own nested dependencies first, and everything
// falls back to the renderer's node_modules. react and remotion always resolve to the renderer's single copy (the
// bundler aliases them); react-dom is aliased here for the same reason.
import fs from "node:fs";
import path from "node:path";

const norm = (p) => {
  const abs = path.resolve(String(p));
  return process.platform === "win32" ? abs.toLowerCase() : abs;
};
// a folder by its given and its real path (node_modules may be a junction; webpack reports real paths)
const places = (p) => {
  let real = p;
  try {
    real = fs.realpathSync.native(p);
  } catch {
    // not there yet
  }
  return [...new Set([norm(p), norm(real)])];
};
const within = (p, dirs) => {
  const n = norm(p);
  return dirs.some((d) => n === d || n.startsWith(d + path.sep));
};

/**
 * @param {{root: string, library: string, workspace?: string | null}} opts
 * @returns {{alias: Record<string, string>, rules: object[]}}
 */
export function workspaceModules({ root, library, workspace = null }) {
  const rendererModules = path.join(root, "node_modules");
  const alias = { "react-dom": path.join(rendererModules, "react-dom") };
  if (!workspace) return { alias, rules: [] };
  const own = path.join(workspace, "node_modules");
  const libs = [...places(library), ...places(path.join(workspace, "library", "made"))];
  const pkgs = places(own);
  return {
    alias,
    rules: [
      { include: (p) => within(p, libs), resolve: { modules: [own, rendererModules] } },
      { include: (p) => within(p, pkgs), resolve: { modules: ["node_modules", rendererModules] } },
    ],
  };
}
