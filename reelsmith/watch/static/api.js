export async function json(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) {
    let body = null;
    try { body = await r.json(); } catch { /* not JSON */ }
    const err = new Error(body?.error || `${r.status} ${r.statusText}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return r.json();
}

export const getState = () => json("/api/state");
export const getHistory = (n) => json(`/api/history/${n}`);
export const getResolved = () => json("/api/resolved");

export async function playerStatus() {
  try {
    const r = await fetch("/player/index.html", { method: "GET", cache: "no-store" });
    if (r.ok) return { ok: true };
    let body = {};
    try { body = await r.json(); } catch { /* not JSON */ }
    return { ok: false, building: !!body.building, error: body.error || `${r.status}` };
  } catch (e) {
    return { ok: false, building: false, error: String(e) };
  }
}

// A still as a blob URL, or the server's reason (and whether it is only busy) when there is none.
export async function getStill(t, w, cut) {
  try {
    const r = await fetch(`/api/still?t=${t}&w=${w}&cut=${encodeURIComponent(cut || "")}`);
    if (r.status === 202) return { error: (await r.json().catch(() => ({}))).error || "busy", busy: true };   // the renderer is busy: ask again
    if (r.ok) return { url: URL.createObjectURL(await r.blob()) };
    let body = {};
    try { body = await r.json(); } catch { /* not JSON */ }
    return { error: body.error || `${r.status}`, busy: !!body.busy };
  } catch (e) {
    return { error: String(e), gone: true };
  }
}

// EventSource reconnects on its own; status reports what the person sees in the top bar. A 'running' event (a slow
// tool started, changed stage or ended) arrives at once and needs no state refetch.
export function subscribe(onChange, onStatus, onRunning, onPushed = () => {}) {
  let es = null;
  let retry = 0;
  const parse = (e) => { try { return JSON.parse(e.data); } catch { return undefined; } };
  const open = () => {
    onStatus("connecting");
    es = new EventSource("/api/events");
    es.onopen = () => { onStatus("connected"); onChange(null); };
    es.addEventListener("change", (e) => {
      const d = parse(e);
      if (d && "running" in d) onRunning(d.running);
      onChange(d?.revision ?? null);
    });
    es.addEventListener("running", (e) => {
      const d = parse(e);
      if (d !== undefined) onRunning(d);
    });
    for (const name of ["frames", "action"]) es.addEventListener(name, (e) => onPushed(name, parse(e)));
    es.onerror = () => {
      onStatus("reconnecting");
      if (es.readyState === EventSource.CLOSED) {
        es.close();
        clearTimeout(retry);
        retry = setTimeout(open, 2000);
      }
    };
  };
  open();
}

// Served from a workspace, the page and its requests live under /p/<project>.
export const BASE = (/^\/p\/[^/]+/.exec(location.pathname) || [""])[0];
let token = null;
async function getToken() {
  if (!token) token = (await json(`${BASE}/api/session`)).token;
  return token;
}

// A POST with a JSON body; the server's reason is the error's message, with its code and parameters beside it.
export const post = (url, body = {}) => postAt(`${BASE}${url}`, body);

// The same to an address that is not the page's own film (the workspace's /api/... and other films' /p/<name>/...).
export async function postAt(url, body = {}, again = true) {
  return send(url, "POST", { "Content-Type": "application/json" }, JSON.stringify(body), again);
}

// A file streamed as the body of a PUT, for a browser tab that has no paths to give.
export async function putFile(url, file) {
  return send(url, "PUT", { "Content-Type": file.type || "application/octet-stream" }, file, true);
}

async function send(url, method, headers, body, again) {
  const r = await fetch(url, { method, cache: "no-store", headers: { ...headers, "X-Reelsmith-Token": await getToken() }, body });
  let data = null;
  try { data = await r.json(); } catch { /* no body */ }
  if (r.status === 403 && again && /header/.test(data?.error || "")) {      // a restarted server has a new token
    token = null;
    return send(url, method, headers, body, false);
  }
  if (!r.ok) {
    const err = new Error(data?.error || `${r.status} ${r.statusText}`);
    err.status = r.status;
    err.code = data?.code;
    err.params = data?.params;
    throw err;
  }
  return data;
}
