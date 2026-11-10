async function json(url) {
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
export function subscribe(onChange, onStatus, onRunning) {
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
