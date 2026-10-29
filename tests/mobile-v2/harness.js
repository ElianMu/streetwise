'use strict';
// Browser harness for the Mobile v2 (Natural-Language-first) E2E flows against a running server.py.
// Run:  python3 server.py   then   node tests/mobile-v2/flows.js        (needs the `playwright` package + Chromium)
// By default nothing is intercepted: the page loads MapLibre, the CARTO basemap and fonts from the network as in production.
// Set SANDBOX_CDN=1 only in an egress-restricted sandbox (needs `npm i maplibre-gl@4.7.1` next to this file); then,
// and ONLY then, these are substituted:
//   * unpkg.com maplibre-gl@4.7.1 js/css  -> the identical files from the npm package maplibre-gl@4.7.1
//   * CARTO dark-matter basemap style     -> a plain dark background style (no basemap streets/labels)
//   * basemap glyph requests              -> empty glyph PBFs (map labels from the app's own layers do not render)
//   * Google Fonts and every other blocked third-party host -> aborted immediately (they are unreachable here anyway)
// Everything served by server.py (index.html, JS, /api/*, /data/*) is the real app and the real backend.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8080';
const SANDBOX = process.env.SANDBOX_CDN === '1';
const ML = path.join(process.env.MAPLIBRE_DIST || path.join(__dirname, 'node_modules', 'maplibre-gl', 'dist'));
const OFFLINE_STYLE = {
  version: 8, name: 'offline-substitute (CARTO blocked in test sandbox)',
  glyphs: 'https://glyphs.invalid/{fontstack}/{range}.pbf',
  sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#0d1a1e' } }],
};

async function launch() { return chromium.launch(); }

async function newPage(browser, { width, height, geo, mobile = width <= 740 }) {
  const context = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile,
    permissions: geo ? ['geolocation'] : [], geolocation: geo || undefined,
    serviceWorkers: 'block', // SW is verified separately; here every load must be the current files
  });
  if (SANDBOX) await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') return route.continue();
    if (url.hostname === 'unpkg.com' && url.pathname.startsWith('/maplibre-gl@4.7.1/dist/')) {
      const f = path.join(ML, path.basename(url.pathname));
      return route.fulfill({ path: f, contentType: f.endsWith('.css') ? 'text/css' : 'application/javascript' });
    }
    if (url.hostname === 'basemaps.cartocdn.com' && url.pathname.endsWith('style.json')) return route.fulfill({ json: OFFLINE_STYLE });
    if (url.hostname === 'glyphs.invalid') return route.fulfill({ status: 200, body: Buffer.alloc(0), contentType: 'application/x-protobuf' });
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  const log = { errors: [], console: [] };
  page.on('pageerror', (e) => log.errors.push(String(e && e.message || e)));
  page.on('console', (m) => { if (m.type() === 'error') log.console.push(m.text()); });
  return { context, page, log };
}

async function openApp(page, waitMs = 3500) {
  await page.goto(BASE, { waitUntil: 'load' });
  await page.waitForFunction(() => typeof state !== 'undefined' && state.mapReady, null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(waitMs);
}

const SHOTS = process.env.SHOT_DIR || path.join(__dirname, '..', '..', 'screenshots', 'mobile-v2');
fs.mkdirSync(SHOTS, { recursive: true });
async function shot(page, name) { const p = path.join(SHOTS, name); await page.screenshot({ path: p }); return p; }

module.exports = { launch, newPage, openApp, shot, BASE, SHOTS };
