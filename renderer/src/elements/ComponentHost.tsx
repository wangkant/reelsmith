// Finds a component by name among the built-in presets and the workspace library (@library, which shadows a
// preset of the same name) and renders <Comp props={...}/>. render.mjs narrows both folders to the names a film
// uses, so a half-written component nobody uses cannot break the bundle.
import React from "react";
import type { RenderMode } from "../types";

type WebpackContext = { keys(): string[]; (id: string): Record<string, unknown> };
// webpack's require.context; typed here so the renderer does not need @types/webpack-env
declare const require: { context(dir: string, deep: boolean, filter: RegExp): WebpackContext };

const presets = require.context("../presets", false, /^\.\/[A-Za-z0-9_]+\.tsx$/);
const library = require.context("@library", false, /^\.\/[A-Za-z0-9_]+\.tsx$/);

type Comp = React.ComponentType<{ props: Record<string, unknown> }>;

const nameOf = (key: string) => key.replace(/^.*[\\/]/, "").replace(/\.tsx$/, "");

const index = (ctx: WebpackContext) => {
  const map = new Map<string, string>();
  for (const key of ctx.keys()) if (!map.has(nameOf(key))) map.set(nameOf(key), key);
  return map;
};

const PRESETS = index(presets);
const LIBRARY = index(library);

const pick = (mod: Record<string, unknown>, name: string): Comp | null => {
  const c = mod.default ?? mod[name];
  return typeof c === "function" || (typeof c === "object" && c !== null) ? (c as Comp) : null;
};

/** The component called `name` (library first), or an Error saying what exists. */
export const findComponent = (name: string): Comp | Error => {
  const lib = LIBRARY.get(name);
  const pre = PRESETS.get(name);
  const key = lib ?? pre;
  if (!key) {
    // the bundle only holds the components a film names, so there is no list to offer here
    return new Error(
      `component "${name}" not found: it is neither a built-in preset nor library/components/${name}.tsx in the workspace`,
    );
  }
  const mod = lib ? library(key) : presets(key);
  const comp = pick(mod, name);
  if (!comp) return new Error(`component "${name}" (${lib ? "library" : "preset"}) has no default export`);
  return comp;
};

// Studio only; data-noinspect keeps its text out of layout measurement.
const ErrorBox: React.FC<{ message: string }> = ({ message }) => (
  <div data-noinspect="" style={{
    position: "absolute", inset: 0, background: "rgba(200,30,30,0.55)", border: "4px solid #ff3030", color: "#fff",
    fontFamily: "monospace", fontSize: 26, lineHeight: 1.25, padding: 16, boxSizing: "border-box", overflow: "hidden",
    whiteSpace: "pre-wrap", wordBreak: "break-all",
  }}>{message}</div>
);

/** The thrown error itself (its stack is what render.mjs source-maps), its message naming the component. */
const crashed = (name: string, err: unknown): Error => {
  const e = err instanceof Error ? err : new Error(String(err));
  if (!e.message.startsWith(`component ${name} crashed: `)) e.message = `component ${name} crashed: ${e.message}`;
  return e;
};

class Boundary extends React.Component<{ name: string; mode: RenderMode; children: React.ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.mode === "studio") return <ErrorBox message={`${this.props.name}: ${error.message}`} />;
    throw crashed(this.props.name, error);
  }
}

/** Renders the component. A missing or crashing one fails film, stills and inspect alike (render.mjs reports it
 *  as stage "component" with the source line); the Studio draws a red box instead. */
export const ComponentHost: React.FC<{ name: string; props?: Record<string, unknown>; mode: RenderMode }> = ({ name, props, mode }) => {
  const found = findComponent(name);
  if (found instanceof Error) {
    if (mode !== "studio") throw found;
    return <ErrorBox message={found.message} />;
  }
  const Comp = found;
  return (
    <Boundary name={name} mode={mode}>
      <Comp props={props ?? {}} />
    </Boundary>
  );
};
