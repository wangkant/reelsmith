// Loaded before a sandboxed `reelsmith script`. Node's permission model covers files, processes, workers, addons
// and WASI; this closes what it leaves open (network, signals to other processes, trace files, V8 flags) and lets a
// bare import the workspace lacks fall back to the renderer's packages. Best effort in-process, not a kernel wall.
import { createRequire, registerHooks, syncBuiltinESMExports } from "node:module";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);

const refuse = (what) => () => {
  const err = new Error(`REELSMITH_SANDBOX: ${what} is not allowed in a script`);
  err.code = "ERR_ACCESS_DENIED";
  throw err;
};
// non-writable and non-configurable, so a script cannot put the original back
const lock = (obj, key, value) => Object.defineProperty(obj, key, { value, writable: false, configurable: false });

// network: every TCP, pipe and TLS client (http, fetch, WebSocket included) connects through Socket#connect
const net = require("node:net");
lock(net.Socket.prototype, "connect", refuse("network access"));
lock(net.Server.prototype, "listen", refuse("listening for connections"));
lock(net, "_createServerHandle", refuse("listening for connections"));
const dns = require("node:dns");
for (const target of [dns, dns.promises, dns.Resolver.prototype, dns.promises.Resolver.prototype]) {
  for (const k of Object.getOwnPropertyNames(target)) {
    if (/^(lookup|resolve|reverse)/.test(k) && typeof target[k] === "function") lock(target, k, refuse("DNS"));
  }
}

// the native handles behind those classes are reachable too (process.stdout._handle, a TLSSocket's parent, a
// dgram socket's state): lock their prototypes, letting stdio keep its own pipes
process.stdout;
process.stderr;
const lockNative = (handle, names) => {
  const proto = handle && Object.getPrototypeOf(handle);
  for (const k of names) {
    const original = proto && proto[k];
    if (typeof original !== "function") continue;
    lock(proto, k, k === "open" ? function (fd, ...rest) {
      if (!(fd >= 0 && fd <= 2)) refuse("network access")();
      return original.call(this, fd, ...rest);
    } : refuse("network access"));
  }
};
const tls = require("node:tls");
const dgram = require("node:dgram");
const tcpSock = new tls.TLSSocket();
const pipeSock = new tls.TLSSocket(null, { pipe: true });
const udp = dgram.createSocket("udp4");
const udpState = Object.getOwnPropertySymbols(udp).map((s) => udp[s]).find((v) => v && v.handle);
const resolver = new dns.Resolver();
lockNative(tcpSock._handle?._parent, ["open", "bind", "bind6", "listen", "connect", "connect6"]);
lockNative(pipeSock._handle?._parent, ["open", "bind", "listen", "connect"]);
lockNative(udpState?.handle, ["open", "bind", "bind6", "connect", "connect6", "send", "send6", "recvStart"]);
lockNative(resolver._handle, Object.getOwnPropertyNames(Object.getPrototypeOf(resolver._handle))
  .filter((k) => /^(query|getHostByAddr)/.test(k)));
tcpSock.destroy();
pipeSock.destroy();
udp.close();
for (const k of ["bind", "connect", "send"]) lock(dgram.Socket.prototype, k, refuse("network access"));

// signals reach any process of the user: a script may only signal itself
const ownPid = process.pid;
for (const k of ["kill", "_kill"]) {
  const original = process[k];
  if (typeof original !== "function") continue;
  lock(process, k, function (pid, ...rest) {
    if (Number(pid) !== ownPid) refuse("signalling another process")();
    return original.call(process, pid, ...rest);
  });
}
const os = require("node:os");
const setPriority = os.setPriority;
lock(os, "setPriority", (pid, priority) => {
  if (priority !== undefined && pid !== 0 && Number(pid) !== ownPid) refuse("changing another process")();
  return priority === undefined ? setPriority(pid) : setPriority(pid, priority);
});

// trace files are written to the working directory past the permission model; V8 flags change the engine itself
// realpath and findPackageJSON answer for paths the script may not read: check access first, so they say nothing
const fs = require("node:fs");
const mod = require("node:module");
const readable = (fn) => function (p, ...rest) {
  fs.accessSync(p);
  return fn.call(this, p, ...rest);
};
for (const name of ["realpathSync", "realpath"]) {
  const original = fs[name];
  const guarded = readable(original);
  guarded.native = readable(original.native);
  lock(fs, name, guarded);
}
const promiseRealpath = fs.promises.realpath;
lock(fs.promises, "realpath", async (p, ...rest) => {
  await fs.promises.access(p);
  return promiseRealpath(p, ...rest);
});
const findPackageJSON = mod.findPackageJSON;
if (typeof findPackageJSON === "function") {
  lock(mod, "findPackageJSON", (...args) => {
    const [spec, base] = args;
    const text = String(spec);
    if (spec instanceof URL || /^file:/i.test(text)) fs.accessSync(new URL(spec));
    else if (isAbsolute(text)) fs.accessSync(text);
    else if (/^\.\.?([\\/]|$)/.test(text) && base) fs.accessSync(new URL(text, base));
    const found = findPackageJSON(...args);
    if (found) fs.accessSync(found);
    return found;
  });
}
lock(require("node:trace_events"), "createTracing", refuse("trace events"));
lock(require("node:v8"), "setFlagsFromString", refuse("changing V8 flags"));
syncBuiltinESMExports();

const modules = process.env.REELSMITH_RENDERER_MODULES;
if (modules) {
  // a parent inside node_modules keeps the lookup from walking above it
  const parentURL = pathToFileURL(`${modules}/.reelsmith/`).href;
  // require() ignores a swapped parentURL, so it resolves from there itself
  const fromRenderer = createRequire(`${parentURL}index.js`);
  registerHooks({
    resolve(specifier, context, next) {
      try {
        return next(specifier, context);
      } catch (err) {
        if (!["ERR_MODULE_NOT_FOUND", "MODULE_NOT_FOUND"].includes(err?.code) || /^(\.|\/|[a-z][a-z0-9+.-]*:)/i.test(specifier)) throw err;
        if (context.conditions?.includes("require")) {
          return { url: pathToFileURL(fromRenderer.resolve(specifier)).href, shortCircuit: true };
        }
        return next(specifier, { ...context, parentURL });
      }
    },
  });
}
