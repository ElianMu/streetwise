'use strict';
/* STROLLANE · NYC — app-shell service worker.
   Caches ONLY same-origin static shell files (HTML/CSS/JS/icons/manifest).
   Never caches: /api/* (live routing, weather, places — must always be fresh or
   fail honestly), /data/* (large GIS/urban JSON — loaded on demand, not shipped
   offline), or any cross-origin request (MapLibre CDN, CARTO/OSM tiles,
   Open-Meteo, Overpass, the Render API). Existing files are already cache-busted
   with "?v=NN" query strings in index.html, so a version bump naturally fetches
   a new URL — this worker does not need its own version string to avoid stale
   JS running against new HTML. */
const CACHE = 'strollane-shell-v10'; // v10: map palette v2 (tonal areas, crisp clusters, no violet); v9: black tech theme; v8: iOS full Home Screen viewport (document height), translucent header; v7: iOS system strip handling (no layout extension); v6: hidden sheets stay off-screen after viewport changes; v5: iOS Home Screen viewport gap fix; v4: full-screen iPhone app shell (safe areas); v3: NL-first mobile UI + subpath-safe exclusions — bumping the name purges every older shell entry on activate

// Paths are compared relative to this worker's own scope, so the exclusions also hold when the site is served
// from a GitHub Pages project subpath (https://<user>.github.io/<repo>/data/...), not only from the domain root.
const SCOPE_PATH = new URL(self.registration ? self.registration.scope : './', self.location.href).pathname;
function isShellRequest(url) {
  if (url.origin !== self.location.origin) return false;
  const rel = url.pathname.startsWith(SCOPE_PATH) ? url.pathname.slice(SCOPE_PATH.length) : url.pathname.replace(/^\//, '');
  if (rel.startsWith('api/')) return false;
  if (rel.startsWith('data/')) return false;
  return true;
}

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return; // never cache POST (route planning, menu checks, etc.)
  const url = new URL(request.url);
  if (!isShellRequest(url)) return; // let the browser handle it normally — no SW involvement

  const isNavigation = request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');

  if (isNavigation) {
    // Network-first for the document itself: always prefer a fresh index.html
    // when online, so cached JS/CSS never runs against a mismatched old page.
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request);
        const cache = await caches.open(CACHE);
        cache.put(request, fresh.clone());
        return fresh;
      } catch (err) {
        const cached = await caches.match(request);
        if (cached) return cached;
        return new Response(
          '<!doctype html><title>Offline</title><p>STROLLANE is offline and this page was never cached. Reconnect and reload.</p>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
    })());
    return;
  }

  // Cache-first for static, version-tagged assets (JS/CSS/icons/manifest).
  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    try {
      const fresh = await fetch(request);
      if (fresh && fresh.ok) {
        const cache = await caches.open(CACHE);
        cache.put(request, fresh.clone());
      }
      return fresh;
    } catch (err) {
      if (cached) return cached;
      throw err;
    }
  })());
});
