'use strict';
/* Street photos: what the street itself looks like along the selected walk.

   Source: Mapillary street-level photos (CC BY-SA), asked for through this app's own API host (POST
   /api/street-photos, street_photos.py). The Mapillary access token lives only on that host; this file holds no
   key and talks to no third-party API. The host returns at most one photo for each of a few points along the route,
   and only photos taken within 25 m of the point; a point with no such photo has none. Nothing is generated or
   substituted.

   Each photo shows how far into the walk it is, the month it was taken, its author and a link to its Mapillary
   page. Thumbnails load from Mapillary's image servers, so Mapillary sees the visitor's IP for those images.
   If the host has no token, is an older build, or fails, nothing is shown.
   Turn off with window.STROLLANE_STREET_PHOTOS = false.                                                          */

const streetPhotos = {cache: new Map(), inflight: new Set()};
const STREET_PHOTO_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function streetPhotosEnabled() { return typeof window !== 'undefined' && window.STROLLANE_STREET_PHOTOS !== false && typeof streetwiseFetch === 'function'; }
function streetPhotoKey(raw) { return raw && raw.route_id && raw.geometry && Array.isArray(raw.geometry.coordinates) ? `${raw.route_id}|${raw.geometry.coordinates.length}` : null; }
function streetPhotoEsc(v) { return String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
/** Keep only well-formed records: an https thumbnail, a mapillary.com page, a date and a distance within the limit. */
function streetPhotoClean(doc) {
 if (!doc || doc.configured !== true || !Array.isArray(doc.photos)) return [];
 const limit = Number(doc.radius_m) || 25;
 return doc.photos.filter((p) => p && /^https:\/\//.test(p.thumb || '') && /^https:\/\/www\.mapillary\.com\//.test(p.page || '')
  && /^\d{4}-\d{2}-\d{2}$/.test(p.captured_on || '') && Number.isFinite(p.at_m) && Number.isFinite(p.distance_m) && p.distance_m <= limit).slice(0, 6);
}
/** Photos already loaded for this route (possibly an empty list), or null if not asked yet. */
function streetPhotosFor(raw) { const k = streetPhotoKey(raw); return k && streetPhotos.cache.has(k) ? streetPhotos.cache.get(k) : null; }
/** Ask once per route; `done` runs when the answer (or the failure) is in. */
function streetPhotosLoad(raw, done) {
 const k = streetPhotoKey(raw);
 if (!k || !streetPhotosEnabled() || streetPhotos.cache.has(k) || streetPhotos.inflight.has(k)) return;
 streetPhotos.inflight.add(k);
 streetwiseFetch('/api/street-photos', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({coordinates: raw.geometry.coordinates}), signal: AbortSignal.timeout(40000)})
  .then((r) => (r.ok ? r.json() : null)).then((doc) => { streetPhotos.cache.set(k, streetPhotoClean(doc)); })
  .catch(() => { streetPhotos.cache.set(k, []); })
  .finally(() => { streetPhotos.inflight.delete(k); if (typeof done === 'function') done(); });
}
function streetPhotoWhen(iso) { const [y, m] = iso.split('-').map(Number); return `${STREET_PHOTO_MONTHS[m - 1] || ''} ${y}`.trim(); }
function streetPhotoFigures(raw) {
 const list = streetPhotosFor(raw);
 if (!list || !list.length) return '';
 const figs = list.map((p) => {
  const km = (p.at_m / 1000).toFixed(p.at_m < 1000 ? 2 : 1), when = streetPhotoWhen(p.captured_on), who = p.username ? `© ${p.username} · Mapillary` : 'Mapillary';
  return `<figure class="rp-photo"><a href="${streetPhotoEsc(p.page)}" target="_blank" rel="noopener" aria-label="Open this photo on Mapillary"><img src="${streetPhotoEsc(p.thumb)}" alt="Street-level photo about ${km} km into the walk, taken ${streetPhotoEsc(when)}" loading="lazy" decoding="async" referrerpolicy="no-referrer"></a><figcaption><strong>${km} km · ${streetPhotoEsc(when)}</strong><a href="${streetPhotoEsc(p.page)}" target="_blank" rel="noopener">${streetPhotoEsc(who)}</a></figcaption></figure>`;
 }).join('');
 return `<div class="street-photos"><div class="street-photos-title">On the street</div><div class="along-photos">${figs}</div><small>Street-level photos taken within 25 m of this walk, in walking order, with the month each was taken. Streets change, so an older photo may not match today. Images from Mapillary, CC BY-SA.</small></div>`;
}
if (typeof window !== 'undefined') Object.assign(window, {streetPhotos, streetPhotosFor, streetPhotosLoad, streetPhotoFigures, streetPhotoClean});
