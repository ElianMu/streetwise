'use strict';
// Serves Wikimedia API calls from real recorded responses (fixture-wikimedia.json) in browser tests: the test sandbox
// cannot reach Wikimedia. mode 'down' makes every Wikimedia request fail (network error).
const path = require('path');
// Wikimedia answers from real recorded responses (fixture-wikimedia.json); the sandbox cannot reach Wikimedia.
const WM = require(path.join(__dirname, 'fixture-wikimedia.json'));
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==', 'base64');
async function wikimedia(page, mode) {
  const seen = { wd: 0, cm: 0, thumbs: 0 };
  await page.route(/wikidata\.org\/w\/api\.php|commons\.wikimedia\.org\/w\/api\.php|thumb\.wikimedia\.org/, (route) => {
    const u = new URL(route.request().url());
    if (mode === 'down') return route.abort('internetdisconnected');
    if (u.hostname === 'thumb.wikimedia.org') { seen.thumbs++; return route.fulfill({ status: 200, contentType: 'image/png', body: PIXEL }); } // test-only image bytes
    if (u.hostname.endsWith('wikidata.org')) {
      seen.wd++;
      const entities = {};
      for (const id of (u.searchParams.get('ids') || '').split('|')) {
        const e = WM.entities[id];
        entities[id] = e ? { id, claims: { ...(e.P18 ? { P18: [{ mainsnak: { datavalue: { value: e.P18 } } }] } : {}), ...(e.P625 ? { P625: [{ mainsnak: { datavalue: { value: e.P625 } } }] } : {}) } } : { id, missing: '' };
      }
      return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ entities }) });
    }
    seen.cm++;
    const pages = {}; let i = -1;
    for (const t of (u.searchParams.get('titles') || '').split('|')) pages[WM.pages[t] ? String(1000 + (++i)) : String(-1 - (++i))] = WM.pages[t] || { title: t, missing: '' };
    return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ query: { pages } }) });
  });
  return seen;
}
module.exports = { wikimedia };
