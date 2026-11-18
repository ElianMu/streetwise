/* Share this walk: a link that reproduces the request, not a stored route.

   The link carries only what is needed to ask for the walk again: the start, the destination (or "loop" / "open"),
   the 12 priorities that were changed, and the walking-time limit. It is kept in the URL fragment (after "#"), which
   browsers do not send to any server; coordinates are rounded to 4 decimals (about 11 m). Nothing is uploaded or saved
   anywhere, and no route geometry or score travels in the link: whoever opens it gets the route the engine computes
   then, from the same inputs. A walk with a destination comes out the same while the score build is the same. A
   recommended walk (loop / open) also depends on which places are open at that moment, so it can differ, and the
   notice on opening says which kind was loaded.

   Not carried: the crime and waterfront preferences, step-free / stairs constraints, named stops, food and hotel
   requests. shareLinkOmits() lists the ones in use so the Share notice can say what was left out. */
const SHARE_PREFIX = '#walk?';
const SHARE_END_MODES = ['fixed', 'round', 'open'];

const shareCoord = (v) => Number(v).toFixed(4);
function sharePlace(p) { return p && Number.isFinite(p.lat) && Number.isFinite(p.lon) ? {lat: +shareCoord(p.lat), lon: +shareCoord(p.lon), name: String(p.name || '').slice(0, 80)} : null; }

/** The current request as plain data, or null when there is nothing complete to share. */
function shareLinkState() {
 if (typeof state === 'undefined' || typeof journey === 'undefined') return null;
 const mode = journey.endMode;
 if (!SHARE_END_MODES.includes(mode)) return null; // "back to my hotel" is personal and is not shared
 const from = sharePlace(getPlace('start')), to = mode === 'fixed' ? sharePlace(getPlace('end')) : null;
 if (!from || (mode === 'fixed' && !to)) return null;
 const prefs = [];
 DIMENSIONS.forEach((d, i) => { if (planner.origins[d.name] !== 'default') prefs.push({i, w: Math.round(planner.weights[d.name]), low: planner.directions[d.name] === 'low'}); });
 return {from, to, end: mode, prefs, minutes: state.budget};
}

/** What the visitor has set that the link does not carry. */
function shareLinkOmits() {
 const out = [];
 if (planner.crime) out.push('the crime-report preference');
 if (planner.waterfront) out.push('the waterfront preference');
 if (planner.constraints.avoidStairs || planner.constraints.stepFree || planner.constraints.avoidDetours) out.push('route constraints');
 if (typeof journey !== 'undefined' && (journey.named.length || journey.food.length || journey.services.length)) out.push('requested stops');
 return out;
}

function shareLinkEncode(st, base) {
 const q = new URLSearchParams();
 q.set('from', `${shareCoord(st.from.lat)},${shareCoord(st.from.lon)}`); if (st.from.name) q.set('fromName', st.from.name);
 if (st.to) { q.set('to', `${shareCoord(st.to.lat)},${shareCoord(st.to.lon)}`); if (st.to.name) q.set('toName', st.to.name); }
 else q.set('end', st.end);
 if (st.prefs.length) q.set('p', st.prefs.map((x) => `${x.i}.${x.w}${x.low ? 'l' : ''}`).join(','));
 if (Number.isFinite(st.minutes)) q.set('min', String(st.minutes));
 return (base || (location.origin + location.pathname)) + SHARE_PREFIX + q.toString();
}

/** Parse a fragment. Returns the state, or null for anything that is not a complete, valid Manhattan request:
    a link is outside input, so every field is checked and nothing is guessed. */
function shareLinkParse(hash) {
 if (typeof hash !== 'string' || !hash.startsWith(SHARE_PREFIX)) return null;
 const q = new URLSearchParams(hash.slice(SHARE_PREFIX.length));
 const point = (key) => {
  const m = /^(-?\d{1,2}\.\d{1,6}),(-?\d{1,3}\.\d{1,6})$/.exec(q.get(key) || '');
  if (!m) return null;
  const p = {lat: +m[1], lon: +m[2], name: (q.get(key + 'Name') || '').replace(/[\u0000-\u001f<>]/g, '').trim().slice(0, 80)};
  return latLonInsideManhattanEnvelope(p) ? p : null;
 };
 const from = point('from'); if (!from) return null;
 let to = null, end = 'fixed';
 if (q.has('to')) { to = point('to'); if (!to) return null; }
 else { end = q.get('end'); if (end !== 'round' && end !== 'open') return null; }
 const prefs = [];
 for (const part of (q.get('p') || '').split(',').filter(Boolean)) {
  const m = /^(\d{1,2})\.(\d{1,3})(l?)$/.exec(part);
  if (!m || +m[1] >= DIMENSIONS.length || +m[2] > 100 || prefs.some((x) => x.i === +m[1])) return null;
  prefs.push({i: +m[1], w: +m[2], low: m[3] === 'l'});
 }
 let minutes = null;
 if (q.has('min')) { minutes = validWalkMinutes(q.get('min')); if (minutes === null) return null; }
 return {from, to, end, prefs, minutes};
}

/** Put a parsed link into the planner. Changes only the request; planning is a separate step. */
function shareLinkApply(st) {
 const place = (p, kind) => ({id: `shared:${shareCoord(p.lat)},${shareCoord(p.lon)}`, name: p.name || `Shared ${kind} ${shareCoord(p.lat)}, ${shareCoord(p.lon)}`, lat: p.lat, lon: p.lon, source: 'Shared link'});
 setEndMode('fixed');
 setJourneyPlace('start', place(st.from, 'start'));
 if (st.to) setJourneyPlace('end', place(st.to, 'destination'));
 else { state.end = null; state.customEnd = null; if (typeof placeInputs !== 'undefined') placeInputs.end?.clear?.(); const box = document.getElementById('searchEnd'); if (box) box.value = ''; }
 for (const d of DIMENSIONS) { planner.weights[d.name] = 50; planner.origins[d.name] = 'default'; planner.directions[d.name] = 'high'; }
 for (const x of st.prefs) { const n = DIMENSIONS[x.i].name; planner.weights[n] = x.w; planner.origins[n] = 'manual'; planner.directions[n] = x.low ? 'low' : 'high'; }
 if (st.minutes != null) setBudget(st.minutes);
 if (typeof walkPresets !== 'undefined') walkPresets.activity = null;
 if (typeof renderPreferenceSummary === 'function') renderPreferenceSummary();
 if (typeof renderDimensions === 'function') renderDimensions();
 if (typeof window.strollaneRenderChips === 'function') window.strollaneRenderChips();
 if (typeof renderWalkPresets === 'function') { renderWalkPresets(); syncWalkPresetRequest(); }
}

function shareLinkSummary(st) {
 const prefs = st.prefs.map((x) => `${dimLabel(DIMENSIONS[x.i].name)} ${x.w}${x.low ? ' (prefer less)' : ''}`).join(', ');
 const where = st.to ? `from ${st.from.name || 'the shared start'} to ${st.to.name || 'the shared destination'}` : `${st.end === 'round' ? 'a loop' : 'an open-ended walk'} from ${st.from.name || 'the shared start'}`;
 return `Shared walk: ${where}${prefs ? `, favouring ${prefs}` : ''}.`;
}

/** Open a shared link: fill the request in and plan it. The route is computed now, by the engine, from these inputs. */
async function shareLinkOpen(hash) {
 const st = shareLinkParse(hash);
 if (!st) { if (typeof hash === 'string' && hash.startsWith(SHARE_PREFIX)) toast('This shared link is incomplete or outside Manhattan, so nothing was loaded.'); return false; }
 shareLinkApply(st);
 const note = shareLinkSummary(st) + (st.to ? ' Planning it now from the same inputs.' : ' Planning it now; a recommended walk depends on which places are open, so it can differ from the sender’s.');
 appendChat('assistant', note); toast(note);
 if (st.to) await generateRoutes(null, false);
 else { const rec = prepareRecommendedWalk(st.end === 'round' ? 'a loop' : ''); if (rec) appendChat('assistant', rec); await planJourney(false); }
 return true;
}

/** Share button: copy (or hand to the system share sheet) a link for the walk on screen. */
async function shareWalk() {
 const st = shareLinkState();
 if (!st) { toast('Choose a start and a destination, or a loop, before sharing.'); return null; }
 const url = shareLinkEncode(st), omitted = shareLinkOmits();
 const tail = ` It contains the start point${st.to ? ' and destination' : ''} (to about 11 m) and your priorities${omitted.length ? `, but not ${omitted.join(', ')}` : ''}.`;
 try { history.replaceState(null, '', url.slice(url.indexOf('#'))); } catch (e) { /* file:// or sandboxed frame: the copy below still works */ }
 try {
  if (navigator.share && window.matchMedia('(pointer: coarse)').matches) { await navigator.share({title: 'STROLLANE · NYC walk', url}); toast('Link shared.' + tail); return url; }
  await navigator.clipboard.writeText(url); toast('Link copied.' + tail);
 } catch (err) {
  if (err && err.name === 'AbortError') return url; // share sheet closed by the visitor
  toast('Could not copy automatically. The link is now in the address bar: copy it from there.' + tail);
 }
 return url;
}

function renderShareButton() {
 const b = document.getElementById('shareWalk'); if (!b) return;
 b.classList.toggle('hidden', !(typeof state !== 'undefined' && state.routes.length && shareLinkState()));
}

function setupShareLink() {
 const b = document.getElementById('shareWalk'); if (!b) return;
 b.addEventListener('click', shareWalk);
 const target = document.getElementById('navStart'); // shown and hidden with the selected route, like the 3D preview button
 if (target) new MutationObserver(renderShareButton).observe(target, {attributes: true, attributeFilter: ['class', 'disabled']});
 renderShareButton();
 window.addEventListener('hashchange', () => { if (location.hash.startsWith(SHARE_PREFIX)) shareLinkOpen(location.hash); });
 if (location.hash.startsWith(SHARE_PREFIX)) setTimeout(() => shareLinkOpen(location.hash), 600); // after the planner has finished setting up
}

if (typeof window !== 'undefined') {
 Object.assign(window, {shareLinkState, shareLinkEncode, shareLinkParse, shareLinkApply, shareLinkOpen, shareLinkOmits, shareWalk});
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupShareLink); else setupShareLink();
}
