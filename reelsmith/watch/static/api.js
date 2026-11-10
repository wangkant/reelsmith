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

// EventSource reconnects on its own; status reports what the person sees in the top bar.
export function subscribe(onChange, onStatus) {
  let es = null;
  let retry = 0;
  const open = () => {
    onStatus("connecting");
    es = new EventSource("/api/events");
    es.onopen = () => { onStatus("connected"); onChange(null); };
    es.addEventListener("change", (e) => {
      let rev = null;
      try { rev = JSON.parse(e.data).revision; } catch { /* keep null */ }
      onChange(rev);
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
