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
const CACHE = 'strollane-shell-v1';

function isShellRequest(url) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith('/api/')) return false;
  if (url.pathname.startsWith('/data/')) return false;
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
