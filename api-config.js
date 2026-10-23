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
