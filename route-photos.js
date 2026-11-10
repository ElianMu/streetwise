'use strict';
/* Route photos: real photos of the real places a walk passes, with their authors and licences.

   Source: Wikimedia Commons, through the place's own Wikidata entry (image property P18). Only places in the
   place index that carry a Wikidata ID (data/places/*.json, field `wd`) and lie within 50 m of the route are used
   (route-story.js storyPlacesNear). Nothing is generated, guessed or substituted: a place without a usable photo
   simply shows none.

   Safeguards:
   - the Wikidata entry's own coordinates (P625) must be within 300 m of the place, so a wrong ID never shows a
     photo of something else;
   - only free licences (CC BY / BY-SA / CC0 / public domain) with a named author (or public domain) are shown;
   - every photo carries its author, licence and a link to its Commons page.

   Cost and limits: free, no key. Requests go from the visitor's browser straight to wikidata.org and
   commons.wikimedia.org (anonymous CORS, `origin=*`), batched (≤ 50 ids per call) and cached for the session, so
   Wikimedia sees the visitor's IP and the places looked up. Thumbnails are 320 px from thumb.wikimedia.org.
   Turn off with window.STROLLANE_PHOTOS = false.                                                                 */

const PHOTO = {MAX_KM: 0.3, WIDTH: 320, BATCH: 50, FREE: /^(CC[ -]?BY|CC0|CC-BY|Public domain|PD)/i};
const routePhotos = {cache: new Map(), inflight: null, queue: new Set(), failed: false};

function photoStrip(html) { const d = document.createElement('div'); d.innerHTML = html || ''; return (d.textContent || '').replace(/\s+/g, ' ').trim(); }
function photoKm(a, b) { const k = Math.PI / 180, x = (b.lon - a.lon) * Math.cos((a.lat + b.lat) / 2 * k), y = b.lat - a.lat; return Math.hypot(x, y) * k * 6371; }
function photosEnabled() { return typeof window !== 'undefined' && window.STROLLANE_PHOTOS !== false && typeof fetch === 'function'; }

/** Photos already loaded for these places (in their order), each {wd, name, thumb, w, h, page, author, license}. */
function photosFor(places) {
 return (places || []).map((p) => { const x = routePhotos.cache.get(p.wd); return x && x.thumb ? {...x, name: p.name} : null; }).filter(Boolean);
}
/** Load photos for places not seen yet; calls `done` once new photos arrived. Network errors leave no photos. */
function photosLoad(places, done) {
 if (!photosEnabled() || routePhotos.failed) return;
 for (const p of places || []) if (p.wd && !routePhotos.cache.has(p.wd)) routePhotos.queue.add(p);
 if (routePhotos.inflight || !routePhotos.queue.size) return;
 const batch = [...routePhotos.queue].slice(0, PHOTO.BATCH);
 batch.forEach((p) => routePhotos.queue.delete(p));
 routePhotos.inflight = photosFetch(batch).then((found) => {
  routePhotos.inflight = null;
  if (found && typeof done === 'function') done();
  if (routePhotos.queue.size) photosLoad([], done);
 }).catch(() => { routePhotos.inflight = null; routePhotos.failed = true; batch.forEach((p) => routePhotos.cache.set(p.wd, {none: true})); });
}
async function photosFetch(places) {
 const ids = places.map((p) => p.wd);
 const wd = await fetch(`https://www.wikidata.org/w/api.php?action=wbgetentities&ids=${ids.join('|')}&props=claims&format=json&origin=*`).then((r) => r.json());
 const want = {};
 for (const p of places) {
  const claims = wd.entities?.[p.wd]?.claims || {}, file = claims.P18?.[0]?.mainsnak?.datavalue?.value, at = claims.P625?.[0]?.mainsnak?.datavalue?.value;
  // the entry must be this place: its own coordinates within 300 m of the place index point
  const here = at && photoKm({lat: p.lat, lon: p.lon}, {lat: at.latitude, lon: at.longitude}) <= PHOTO.MAX_KM;
  if (file && here) want['File:' + file] = p.wd; else routePhotos.cache.set(p.wd, {none: true});
 }
 const titles = Object.keys(want);
 if (!titles.length) return false;
 const cm = await fetch(`https://commons.wikimedia.org/w/api.php?action=query&titles=${encodeURIComponent(titles.join('|'))}&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=${PHOTO.WIDTH}&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|Credit&format=json&origin=*`).then((r) => r.json());
 const alias = Object.fromEntries((cm.query?.normalized || []).map((n) => [n.to, n.from]));
 let found = false;
 for (const page of Object.values(cm.query?.pages || {})) {
  const id = want[alias[page.title] || page.title]; if (!id) continue;
  const info = page.imageinfo?.[0], m = info?.extmetadata || {};
  const license = photoStrip(m.LicenseShortName?.value), author = photoStrip(m.Artist?.value) || (/public domain|^PD/i.test(license) ? '' : null);
  if (!info?.thumburl || !PHOTO.FREE.test(license) || author == null) { routePhotos.cache.set(id, {none: true}); continue; }
  routePhotos.cache.set(id, {wd: id, thumb: info.thumburl, w: info.thumbwidth, h: info.thumbheight, page: info.descriptionurl, author: author.slice(0, 80), license, licenseUrl: m.LicenseUrl?.value || null});
  found = true;
 }
 for (const t of titles) if (!routePhotos.cache.has(want[t])) routePhotos.cache.set(want[t], {none: true});
 return found;
}
const photoEsc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
/** A row of photos, each with the place name and its credit (author · licence, linked to the Commons page). */
function photoFigures(photos, cls) {
 if (!photos.length) return '';
 return `<div class="${cls}">${photos.map((x) => {
  const credit = [x.author, x.license].filter(Boolean).join(' · ');
  return `<figure class="rp-photo"><img src="${photoEsc(x.thumb)}" alt="${photoEsc(x.name)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" width="${x.w || 320}" height="${x.h || 213}"><figcaption><strong>${photoEsc(x.name)}</strong><a href="${photoEsc(x.page)}" target="_blank" rel="noopener" title="${photoEsc(credit)} — Wikimedia Commons">${photoEsc(credit)}</a></figcaption></figure>`;
 }).join('')}</div>`;
}

if (typeof window !== 'undefined') { window.routePhotos = routePhotos; Object.assign(routePhotos, {for: photosFor, load: photosLoad, figures: photoFigures, LIMITS: PHOTO}); }
