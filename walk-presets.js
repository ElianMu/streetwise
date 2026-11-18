'use strict';
/* Walk priorities: one row of the 12 experience dimensions a visitor can pick without typing.

   A pill is NOT a new dimension, score or route. Tapping one does exactly what the quick-preference chips do: it sets
   that existing dimension to importance 80 (direction high), or back to "not expressed" when tapped again. Several can
   be on at once. Names, definitions and weights of the 12 dimensions are untouched; sliders, chips and the "describe
   your walk" box stay in sync because all of them read planner state.

   The request box then shows the choice in words. "Create My Walk" / "Plan My Walk" stays the only start button; when
   the box holds exactly that generated sentence, planning uses the app's existing manual path (no AI interpretation
   call), so the weights planned with are exactly the ones the pills set.

   Order: the three dimensions featured for the lead audience first, then the rest by mean gain in the route
   benchmark (see WALK_PRESET_ORDER below; tests/test_route_benchmark.py fails if it drifts from the benchmark).
   Each pill's tooltip names the indicators its score is built from, read from data/pedestrian/score-indicators.json
   (the router's real definitions, loaded by route-client.js); nothing about the data is hard-coded here. */

// The three dimensions the lead audience's first use case leans on (AUDIENCE.md) come first; the other nine follow in
// order of mean gain in the route benchmark (benchmarks/ROUTE_BENCHMARK.md). tests/test_route_benchmark.py checks both.
const WALK_FEATURED = ['Nature', 'Quiet & Relax', 'Architecture'];
const WALK_PRESET_ORDER = [...WALK_FEATURED, 'Transit Connectivity', 'Spatial Comfort', 'Access & Safety',
 'Food & Retail', 'Culture', 'Environment', 'Walkability', 'Urban Vibrancy', 'Scenic & Visual'];
/* Walk activities: the three use cases written for the lead audience (AUDIENCE.md), as one-tap starting points.
   An activity is only a named bundle of EXISTING dimensions, each set to the same importance a pill sets (80). It adds
   no dimension, score, weight or route of its own. What kind of walk comes out is decided by machinery that already
   exists: with no destination the app recommends a walk past real places chosen from those priorities (journey.js
   prepareRecommendedWalk; "a loop" comes back to the start), with a destination it routes there along streets
   ranked by them. Choosing an activity replaces the pills chosen before it; changing a pill afterwards turns the
   choice back into plain priorities. */
const WALK_ACTIVITIES = [
 {key: 'neighbourhood', title: 'Know a neighbourhood', lead: 'Get to know a neighbourhood', loop: true,
  dims: ['Nature', 'Quiet & Relax', 'Architecture'],
  about: 'A loop from where you are, past parks and historic buildings, along greener and quieter streets. About an hour.'},
 {key: 'nicer-way', title: 'The nicer way', lead: 'Take the nicer way', needsEnd: true,
  dims: ['Quiet & Relax', 'Nature', 'Spatial Comfort'],
  about: 'Between two places you already go, by quieter, greener streets with more sidewalk, for a modest detour. Needs a destination.'},
 {key: 'with-a-point', title: 'A walk with a point', lead: 'A walk with a point',
  dims: ['Culture', 'Food & Retail'],
  about: 'A walk that passes cultural venues and shopping streets worth knowing.'},
];

const WALK_PRESET_WEIGHT = 80; // same as mobile-ui.js QUICK_WEIGHT
const WALK_REQUEST_PREFIX = 'Prioritise: ';
const walkPresets = {lastRequest: '', activity: null};

function walkPresetDims() { return typeof DIMENSIONS === 'undefined' ? [] : WALK_PRESET_ORDER.filter((n) => DIMENSIONS.some((d) => d.name === n)); }
function walkPresetOn(dim) { return typeof planner !== 'undefined' && planner.origins[dim] !== 'default' && planner.weights[dim] >= 70 && planner.directions[dim] !== 'low'; }
function walkPresetLabel(dim) { return typeof dimLabel === 'function' ? dimLabel(dim) : dim; }
/** Scored indicators behind a dimension, from the router's definitions file (empty until it has loaded). */
function walkPresetBasis(dim) {
 const doc = typeof scoreBasis !== 'undefined' ? scoreBasis.doc : null;
 return doc?.dimensions?.[dim] ? doc.dimensions[dim].filter((i) => i.role === 'up' || i.role === 'down').map((i) => i.label) : [];
}
/** True when choosing a looping activity will really give a loop: the walk is already set to return to the start, or
    no destination is chosen and the recommender (journey.js) will read "a loop" and set that. Not when the visitor has
    picked an open-ended or hotel ending themselves: that choice is kept, so the sentence must not promise a loop. */
function walkWillLoop() {
 if (typeof journey === 'undefined') return false;
 return journey.endMode === 'round' || (journey.endMode === 'fixed' && !(typeof getPlace === 'function' && getPlace('end')));
}
function walkHasDestination() { return typeof journey !== 'undefined' && journey.endMode === 'fixed' && typeof getPlace === 'function' && Boolean(getPlace('end')); }
/** The chosen activity, only while the dimensions that are on are exactly its own (a pill changed since = no activity). */
function walkActivity() {
 const a = WALK_ACTIVITIES.find((x) => x.key === walkPresets.activity);
 if (!a) return null;
 const on = walkPresetDims().filter(walkPresetOn);
 return on.length === a.dims.length && a.dims.every((d) => on.includes(d)) ? a : null;
}
/** The choice in words; '' when nothing is chosen. An activity names itself; plain pills list the priorities. */
function walkPresetRequest() {
 const on = walkPresetDims().filter(walkPresetOn);
 if (!on.length) return '';
 const a = walkActivity();
 if (!a) return WALK_REQUEST_PREFIX + on.map(walkPresetLabel).join(', ') + '.';
 return `${a.lead}: ${a.loop && walkWillLoop() ? 'a loop from here, ' : ''}favouring ${a.dims.map(walkPresetLabel).join(', ')}.`;
}
/** True when `text` is exactly the sentence the pills generated for the current choice (so no AI call is needed). */
function isWalkPresetRequest(text) { const t = (text || '').trim(); return Boolean(t) && t === walkPresetRequest(); }
/** Write the choice into the request box — only if the box is empty, still holds the sample sentence, or holds an
    earlier generated sentence. Words the visitor typed themselves are never overwritten. */
function syncWalkPresetRequest() {
 const box = document.getElementById('intentText'); if (!box) return;
 const cur = box.value.trim(), next = walkPresetRequest();
 const replaceable = !cur || cur === walkPresets.lastRequest || cur === (box.defaultValue || '').trim() || cur.startsWith(WALK_REQUEST_PREFIX) || WALK_ACTIVITIES.some((a) => cur.startsWith(a.lead + ': '));
 if (!replaceable) return;
 box.value = next; walkPresets.lastRequest = next;
 box.dispatchEvent(new Event('input', {bubbles: true}));
 if (typeof window.strollaneMarkSubmitted === 'function') window.strollaneMarkSubmitted(next); // phone: not an "unsent request"
}
function toggleWalkPreset(dim) {
 if (typeof planner === 'undefined' || !walkPresetDims().includes(dim)) return false;
 const on = !walkPresetOn(dim);
 planner.weights[dim] = on ? WALK_PRESET_WEIGHT : 50;
 planner.origins[dim] = on ? 'manual' : 'default';
 planner.directions[dim] = 'high';
 if (typeof renderPreferenceSummary === 'function') renderPreferenceSummary();
 if (typeof renderDimensions === 'function') renderDimensions();
 if (typeof window.strollaneRenderChips === 'function') window.strollaneRenderChips();
 syncWalkPresetRequest();
 renderWalkPresets();
 // with a walk already on screen this is the same as moving that dimension's slider
 if (typeof state !== 'undefined' && state.routes.length && typeof queueMapReplan === 'function') queueMapReplan();
 return on;
}
/** Choose an activity (or tap it again to clear it): the pills chosen before it are released, its own are set. */
function chooseWalkActivity(key) {
 const a = WALK_ACTIVITIES.find((x) => x.key === key);
 if (!a || typeof planner === 'undefined' || !a.dims.every((d) => walkPresetDims().includes(d))) return false;
 const wasOn = walkActivity() === a;
 for (const d of walkPresetDims()) {              // release only what a pill or an activity set: exactly 80, by hand
  if (planner.origins[d] === 'manual' && planner.weights[d] === WALK_PRESET_WEIGHT && planner.directions[d] !== 'low') { planner.weights[d] = 50; planner.origins[d] = 'default'; }
 }
 walkPresets.activity = wasOn ? null : a.key;
 if (!wasOn) for (const d of a.dims) { planner.weights[d] = WALK_PRESET_WEIGHT; planner.origins[d] = 'manual'; planner.directions[d] = 'high'; }
 if (typeof renderPreferenceSummary === 'function') renderPreferenceSummary();
 if (typeof renderDimensions === 'function') renderDimensions();
 if (typeof window.strollaneRenderChips === 'function') window.strollaneRenderChips();
 syncWalkPresetRequest();
 renderWalkPresets();
 if (!wasOn && a.needsEnd && !walkHasDestination() && typeof toast === 'function') toast('Choose where you are going (To). Without a destination I will recommend a walk instead.');
 if (typeof state !== 'undefined' && state.routes.length && typeof queueMapReplan === 'function') queueMapReplan();
 return !wasOn;
}
/** Desktop "Plan My Walk" when the box holds the pills' own sentence: handlePlan() without the interpretation call. */
async function planFromWalkPresets() {
 if (state.routingBusy || planner.parsing) return;
 for (const kind of ['start', 'end']) {
  if (kind === 'end' && typeof journey !== 'undefined' && journey.endMode !== 'fixed') continue;
  const typed = document.getElementById(kind === 'start' ? 'searchStart' : 'searchEnd').value.trim(), chosen = getPlace(kind);
  if (typed !== (chosen?.name || '')) { toast(`Search and choose a ${kind === 'start' ? 'starting point' : 'destination'} result first, or clear the box.`); return; }
 }
 const on = walkPresetDims().filter(walkPresetOn);
 appendChat('user', walkPresetRequest());
 appendChat('assistant', `Your priorities: ${on.map((d) => `${walkPresetLabel(d)} ${planner.weights[d]}`).join(' · ')}. Checking feasible pedestrian paths…`);
 const problem = await ensurePlanStart();
 if (problem) { document.getElementById('rankingStatus').textContent = problem; appendChat('assistant', problem + ' The displayed previous route has not been recalculated.'); return; }
 const rec = typeof prepareRecommendedWalk === 'function' ? prepareRecommendedWalk(walkPresetRequest()) : null; // "a loop" comes back to the start
 if (rec) appendChat('assistant', rec);
 if (typeof journeyMode === 'function' && journeyMode()) await planJourney(false); else await generateRoutes(null, false);
}
function renderWalkPresets() {
 const active = walkActivity();
 for (const root of document.querySelectorAll('[data-walk-presets]')) {
  const scroll = root.scrollLeft;
  root.textContent = '';
  for (const a of WALK_ACTIVITIES) {
   if (!a.dims.every((d) => walkPresetDims().includes(d))) continue; // registry check: only existing dimensions
   const b = document.createElement('button'); b.type = 'button'; b.className = 'walk-pill walk-activity'; b.dataset.activity = a.key;
   b.textContent = a.title; b.setAttribute('aria-pressed', String(active === a));
   b.title = `${a.about} Sets ${a.dims.join(', ')} to ${WALK_PRESET_WEIGHT}.`;
   b.addEventListener('click', () => chooseWalkActivity(a.key));
   root.appendChild(b);
  }
  if (root.children.length) { const br = document.createElement('span'); br.className = 'walk-pill-break'; br.setAttribute('aria-hidden', 'true'); root.appendChild(br); }
  for (const dim of walkPresetDims()) {
   const b = document.createElement('button'); b.type = 'button'; b.className = 'walk-pill'; b.dataset.dim = dim;
   b.textContent = walkPresetLabel(dim);
   b.setAttribute('aria-pressed', String(walkPresetOn(dim)));
   const basis = walkPresetBasis(dim);
   b.title = `Sets ${dim} to ${WALK_PRESET_WEIGHT}.` + (basis.length ? ` Based on: ${basis.join(' · ')}.` : '');
   b.addEventListener('click', () => toggleWalkPreset(dim));
   root.appendChild(b);
  }
  root.scrollLeft = scroll;
  root.classList.toggle('hidden', !root.children.length);
 }
}
if (typeof window !== 'undefined') {
 Object.assign(window, {WALK_PRESET_ORDER, WALK_FEATURED, WALK_ACTIVITIES, chooseWalkActivity, walkActivity, walkPresets, walkPresetRequest, isWalkPresetRequest, toggleWalkPreset, planFromWalkPresets, renderWalkPresets});
 const boot = () => { renderWalkPresets(); if (typeof loadScoreBasis === 'function') loadScoreBasis().then((d) => { if (d) renderWalkPresets(); }); };
 if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else setTimeout(boot, 0);
}
