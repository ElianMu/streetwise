'use strict';

const STREETWISE_API_BASE =
  location.hostname === 'elianmu.github.io'
    ? 'https://streetwise-api.onrender.com'
    : '';

function streetwiseFetch(url, options) {
  if (typeof url === 'string' && url.startsWith('/api/')) {
    return fetch(STREETWISE_API_BASE + url, options);
  }
  return fetch(url, options);
}

/** Fetch JSON and say plainly what went wrong when the reply is not JSON (e.g. an HTML 404 page or a sleeping host),
    instead of surfacing "Unexpected token '<'". */
async function streetwiseJson(url, options) {
  const res = await streetwiseFetch(url, options);
  const type = res.headers.get('Content-Type') || '';
  const text = await res.text();
  if (!type.includes('json') && !/^\s*[[{]/.test(text)) {
    throw new Error(`${url} returned ${res.status} ${type.split(';')[0] || 'non-JSON'} instead of JSON${/^\s*</.test(text) ? ' (an HTML page — wrong path or the API host is unavailable)' : ''}`);
  }
  let data;
  try { data = JSON.parse(text); } catch (e) { throw new Error(`${url} returned invalid JSON: ${e.message}`); }
  if (!res.ok) throw new Error(data.error || `${url} returned HTTP ${res.status}`);
  return data;
}

/* ---- Sleeping API host ------------------------------------------------------------------------------------------
   The API host can be asleep (a hosted instance that idles is restarted on the next request, and server.py finishes
   its warm-up before it answers). The first planning request then outlived its own time limit and the visitor saw a
   bare "signal timed out". Planning now asks the cheap /api/status first and waits for it, saying so in plain words,
   before it sends the real request. Only when the API is on another host (the published site); on a host that is
   already up this costs one fast round trip. */
const streetwiseHost = {awakeAt: 0, waking: false, remote: Boolean(STREETWISE_API_BASE)};
const STREETWISE_WAKE_MESSAGE = 'Waking the route server. The first request after a pause can take up to a minute…';
const STREETWISE_AWAKE_FOR_MS = 5 * 60 * 1000;
/** Resolve once /api/status answers OK. `note(text)` is called once if the host does not answer straight away.
    Throws a plain-language error after `maxWaitMs`. Never blocks when the page is served by server.py itself. */
async function streetwiseAwake(note, maxWaitMs = 90000, pauseMs = 2500) {
  if (!streetwiseHost.remote) return true; // same origin: the server that sent this page is the API, so it is up
  if (Date.now() - streetwiseHost.awakeAt < STREETWISE_AWAKE_FOR_MS) return true;
  const deadline = Date.now() + maxWaitMs;
  let told = false;
  try {
    for (;;) {
      try {
        const res = await streetwiseFetch('/api/status', {signal: AbortSignal.timeout(8000)});
        if (res.ok) { streetwiseHost.awakeAt = Date.now(); return true; }
      } catch (e) { /* asleep, restarting or unreachable: keep waiting until the deadline */ }
      if (Date.now() + pauseMs >= deadline) break;
      if (!told) { told = true; streetwiseHost.waking = true; if (note) note(STREETWISE_WAKE_MESSAGE); }
      await new Promise((r) => setTimeout(r, pauseMs));
    }
  } finally { streetwiseHost.waking = false; }
  throw new Error('The route server is not answering right now. Nothing was changed. Try again in a minute.');
}
// Start waking the route server as soon as the page opens, so it is usually up by the time a walk is requested.
// Silent: no note, and a failure here is ignored (planning checks again and says so in words).
if (typeof window !== 'undefined' && streetwiseHost.remote) setTimeout(() => { streetwiseAwake(null).catch(() => {}); }, 0);

/** A request that outlived its time limit, said in words a visitor can act on (instead of "signal timed out"). */
function streetwiseErrorText(err) {
  if (err && (err.name === 'TimeoutError' || /signal timed out|aborted due to timeout/i.test(err.message || ''))) {
    streetwiseHost.awakeAt = 0; // check the host again before the next attempt
    return 'The route server took too long to answer. Try again; the first request after a pause is the slow one.';
  }
  return err && err.message ? err.message : String(err);
}
