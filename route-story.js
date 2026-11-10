'use strict';
/* Route story: turns the engine's route objects into words a walker can choose by.

   Nothing here is new data. Every word comes from numbers the engine already returned for these routes
   (the 12 dimension scores, coverage, distance, time, edges and street names) or from the real place index
   (data/places/*.json records that carry a Wikidata ID). Scores are ranks within Manhattan (0–100), so the
   wording is always comparative ("greener than the fastest way"), never absolute ("green"). A claim is made only
   when both routes have that dimension measured on ≥ 60 % of their length, and only beyond a 5-point difference.

   The engine, the ranking and the 12 dimension definitions are untouched: this file only reads them.

   Thresholds (one place, so the wording and the tests share them):
     ≥ 15 points  → "much greener"     5–15 → "greener"     within ±5 → "similar"
     a superlative ("Greenest") needs the route to lead every other shown route by ≥ 3 points
     two routes sharing ≥ 85 % of their length count as the same option (only one is shown)                   */

const STORY = {MUCH: 15, MORE: 5, LEAD: 3, SAME: 0.85, COVER: 0.6, NEAR_M: 50, TYPICAL: 60};

// What each dimension measures (its sub-indicators in data/manhattan-streets.json) decides its words.
// name: the route name when it leads (null = never used as a name: too easy to overclaim)
const STORY_WORDS = {
 'Nature': {name: 'Greenest', sup: 'greenest', more: 'greener', less: 'less green', chip: 'More trees', noun: 'greenery', ask: 'nature'},
 'Quiet & Relax': {name: 'Quietest', sup: 'quietest', more: 'quieter', less: 'busier', chip: 'Quieter streets', noun: 'quiet', ask: 'quiet'},
 'Architecture': {name: 'Most landmarks', sup: 'closest to landmark buildings', more: 'closer to landmark buildings', less: 'farther from landmark buildings', chip: 'Landmark buildings', noun: 'landmark buildings', ask: 'architecture'},
 'Culture': {name: 'Most culture', sup: 'closest to cultural venues', more: 'closer to cultural venues', less: 'farther from cultural venues', chip: 'Cultural venues', noun: 'cultural venues', ask: 'culture'},
 'Scenic & Visual': {name: 'Most scenic', sup: 'most scenic', more: 'more scenic', less: 'less scenic', chip: 'Scenic spots', noun: 'scenery', ask: 'scenery'},
 'Urban Vibrancy': {name: 'Liveliest', sup: 'liveliest', more: 'livelier', less: 'calmer', chip: 'Lively streets', noun: 'street life', ask: 'lively streets'},
 'Food & Retail': {name: 'Most food & shops', sup: 'richest in food & shops', more: 'more food & shops', less: 'fewer food & shops', chip: 'Food & shops', noun: 'food & shops', ask: 'food & shops'},
 'Spatial Comfort': {name: 'Roomiest sidewalks', sup: 'roomiest', more: 'roomier sidewalks', less: 'tighter sidewalks', chip: 'Roomy sidewalks', noun: 'sidewalk space', ask: 'space'},
 'Walkability': {name: 'Most walkable', sup: 'most walkable', more: 'more walkable', less: 'less walkable', chip: 'Walkable grid', noun: 'walkability', ask: 'walkability'},
 'Access & Safety': {name: null, sup: 'fewest recorded pedestrian crashes', more: 'fewer recorded pedestrian crashes', less: 'more recorded pedestrian crashes', chip: 'Fewer recorded crashes', noun: 'crash record', ask: 'safety'},
 'Environment': {name: null, sup: 'farthest from highways', more: 'farther from highways', less: 'closer to highways', chip: 'Away from highways', noun: 'distance from highways', ask: 'less traffic'},
 'Transit Connectivity': {name: null, sup: 'closest to the subway', more: 'closer to the subway', less: 'farther from the subway', chip: 'Near the subway', noun: 'subway access', ask: 'transit'},
};
// dimensions that describe how a stretch of street feels (used for "Along this walk")
const STORY_FEEL = ['Nature', 'Quiet & Relax', 'Architecture', 'Culture', 'Urban Vibrancy', 'Food & Retail', 'Scenic & Visual', 'Spatial Comfort'];
const PLACE_KIND = {parks: ['park', 'parks'], museums: ['museum', 'museums'], historic: ['historic site', 'historic sites'], attractions: ['landmark', 'landmarks'], culture: ['cultural venue', 'cultural venues']};

const routeStory = {lists: null, loading: null, near: {}, showAll: false, last: null};

const storyMuch = (w) => (/^fewer/.test(w) ? 'far ' + w : 'much ' + w);
const storyCap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const storyJoin = (xs) => (xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs.at(-1));
function storyScore(r, d) { const v = r.dimension_scores?.[d], c = r.data_coverage?.by_dimension?.[d]; return v == null || (c != null && c < STORY.COVER) ? null : v; }
function storyDiff(a, b, d) { const x = storyScore(a, d), y = storyScore(b, d); return x == null || y == null ? null : x - y; }
/** The user's own priorities, strongest first (same source the engine request uses: planner.weights / origins). */
function storyAsks() {
 if (typeof planner === 'undefined' || typeof DIMENSIONS === 'undefined') return [];
 return DIMENSIONS.filter((d) => planner.origins[d.name] !== 'default' && planner.weights[d.name] > 50)
  .map((d) => ({dim: d.name, weight: planner.weights[d.name], low: planner.directions[d.name] === 'low'}))
  .sort((a, b) => b.weight - a.weight);
}

/* ---------- geometry ---------- */
function storyMeters(lat) { return {x: 111320 * Math.cos(lat * Math.PI / 180), y: 110540}; }
function storyDistToLine(p, coords, k) {
 let best = Infinity;
 for (let i = 1; i < coords.length; i++) {
  const ax = (coords[i - 1][0] - p.lon) * k.x, ay = (coords[i - 1][1] - p.lat) * k.y, bx = (coords[i][0] - p.lon) * k.x, by = (coords[i][1] - p.lat) * k.y;
  const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy, t = L ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L)) : 0;
  best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
 }
 return best;
}
/** Share of the shorter route's length that the two routes walk together (same OSM edges). */
function storyOverlap(a, b) {
 const len = (r) => Object.fromEntries((r.edges || []).map((e) => [e.edge_id, e.traversed_length_m || e.length_m || 0]));
 const A = len(a), B = len(b); let shared = 0;
 for (const [id, m] of Object.entries(A)) if (B[id] != null) shared += Math.min(m, B[id]);
 return shared / Math.max(1, Math.min(a.distance_m, b.distance_m));
}
const STREET_WORDS = {AV: 'Avenue', AVE: 'Avenue', ST: 'Street', PL: 'Place', BLVD: 'Boulevard', DR: 'Drive', RD: 'Road', PKWY: 'Parkway', SQ: 'Square', HWY: 'Highway', LN: 'Lane', TER: 'Terrace', PLZ: 'Plaza', EXPY: 'Expressway', BRG: 'Bridge'};
const STREET_DIR = {E: 'East', W: 'West', N: 'North', S: 'South'};
function storyOrdinal(n) { const v = +n, t = v % 100; return v + (t >= 11 && t <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[v % 10] || 'th')); }
/** "E 17 ST" → "East 17th Street", "5 AV" → "5th Avenue", "BROADWAY" → "Broadway" (an OSM name is used as it is). */
function storyStreetName(raw) {
 if (!raw) return null;
 if (/[a-z]/.test(raw)) return raw; // already written in words (OSM)
 const t = raw.trim().split(/\s+/);
 return t.map((w, i) => {
  if (i === 0 && STREET_DIR[w] && t.length > 1) return STREET_DIR[w];
  if (i === 0 && w === 'ST' && t.length > 2) return 'St'; // ST MARKS PL = St Marks Place
  if (i === t.length - 1 && STREET_WORDS[w]) return STREET_WORDS[w];
  if (/^\d+$/.test(w)) return storyOrdinal(w);
  return w.charAt(0) + w.slice(1).toLowerCase();
 }).join(' ');
}
function storyStreet(e) { const o = Array.isArray(e.name) ? e.name[0] : e.name, l = Array.isArray(e.street_name) ? e.street_name[0] : e.street_name; return storyStreetName(o || l || null); }
function storyStreets(r) {
 const by = {};
 for (const e of r.edges || []) { const n = storyStreet(e); if (n) by[n] = (by[n] || 0) + (e.traversed_length_m || 0); }
 return by;
}

/* ---------- real places along a route (place index, Wikidata-listed only) ---------- */
function storyEnsurePlaces() {
 if (routeStory.lists || routeStory.loading || typeof loadPlaces !== 'function') return;
 routeStory.loading = Promise.all(Object.keys(PLACE_KIND).map((c) => loadPlaces(c).then((rs) => rs.filter((r) => r.wd && r.name)).catch(() => [])))
  .then((lists) => {
   const seen = new Set(), out = [];
   Object.keys(PLACE_KIND).forEach((cat, i) => { for (const p of lists[i]) { const key = p.wd || p.name; if (seen.has(key)) continue; seen.add(key); out.push({...p, cat}); } });
   routeStory.lists = out; routeStory.near = {};
   if (typeof renderRouteCards === 'function' && typeof state !== 'undefined' && state.routes.length) renderRouteCards();
  });
}
function storyEndsNear(p, r) {
 // the start and the destination themselves are not "along the way"
 const k = storyMeters(p.lat), c = r.geometry?.coordinates || [], ends = [c[0], c.at(-1)].filter(Boolean);
 return ends.some(([lon, lat]) => Math.hypot((lon - p.lon) * k.x, (lat - p.lat) * k.y) < 120);
}
/** Wikidata-listed parks, museums, historic sites, landmarks and cultural venues within 50 m of the route line. */
function storyPlacesNear(r) {
 if (!routeStory.lists) return null;
 if (routeStory.near[r.route_id]) return routeStory.near[r.route_id];
 const c = r.geometry?.coordinates || [];
 if (c.length < 2) return [];
 let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
 for (const [x, y] of c) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
 const pad = 0.0008, k = storyMeters((s + n) / 2);
 const found = routeStory.lists.filter((p) => p.lon > w - pad && p.lon < e + pad && p.lat > s - pad && p.lat < n + pad)
  .map((p) => ({...p, d: storyDistToLine(p, c, k)})).filter((p) => p.d <= STORY.NEAR_M && !storyEndsNear(p, r))
  .sort((a, b) => (b.sl || 0) - (a.sl || 0));
 routeStory.near[r.route_id] = found;
 return found;
}
function storyPlaceChip(places) {
 if (!places?.length) return null;
 const by = {};
 for (const p of places) by[p.cat] = (by[p.cat] || 0) + 1;
 const [cat, n] = Object.entries(by).sort((a, b) => b[1] - a[1] || (a[0] === 'parks' ? -1 : 1))[0];
 return `${n} ${PLACE_KIND[cat][n > 1 ? 1 : 0]}`;
}

/* ---------- which 2–3 routes to show ---------- */
/** Best match, the fastest (unless it is the same walk), then the route that differs most from those. */
function storyPick(routes) {
 const feasible = routes.filter((r) => r.constraints?.feasible !== false), pool = feasible.length ? feasible : routes.slice();
 const best = pool.find((r) => r.recommended) || pool[0];
 if (!best) return {shown: [], extra: [], fastestToo: null};
 const shown = [best];
 const fastest = pool.reduce((a, r) => (!a || r.estimated_duration_min < a.estimated_duration_min ? r : a), null);
 let fastestToo = null;
 if (fastest && fastest !== best) {
  if (storyOverlap(fastest, best) < STORY.SAME) shown.push(fastest);
  else if (fastest.estimated_duration_min - best.estimated_duration_min > -1.5) fastestToo = best.route_id; // same walk, within ~1 min
  else shown.push(fastest);
 }
 const rest = pool.filter((r) => !shown.includes(r));
 while (shown.length < 3 && rest.length) {
  const scored = rest.map((r) => ({r, gap: 1 - Math.max(...shown.map((s) => storyOverlap(r, s)))})).sort((a, b) => b.gap - a.gap);
  if (scored[0].gap < 1 - STORY.SAME) break;
  shown.push(scored[0].r); rest.splice(rest.indexOf(scored[0].r), 1);
 }
 const order = [best, fastest].filter((r, i, a) => r && shown.includes(r) && a.indexOf(r) === i);
 const ordered = [...order, ...shown.filter((r) => !order.includes(r))];
 return {shown: ordered, extra: routes.filter((r) => !ordered.includes(r)), fastestToo};
}

/* ---------- words for one route ---------- */
function storyTraits(r, ref, dims) {
 return dims.map((d) => ({d, diff: storyDiff(r, ref, d)})).filter((t) => t.diff != null && Math.abs(t.diff) >= STORY.MORE);
}
function traitWord(t, low = false) {
 const w = STORY_WORDS[t.d], up = low ? t.diff < 0 : t.diff > 0, word = up ? (low ? w.less : w.more) : (low ? w.more : w.less);
 return Math.abs(t.diff) >= STORY.MUCH ? storyMuch(word) : word;
}
function storyLeader(r, others, dims) {
 let best = null;
 for (const d of dims) {
  const v = storyScore(r, d); if (v == null) continue;
  const gaps = others.map((o) => { const x = storyScore(o, d); return x == null ? null : v - x; });
  if (!others.length || gaps.some((g) => g == null || g < STORY.LEAD)) continue;
  const lead = Math.min(...gaps);
  if (!best || lead > best.lead) best = {d, lead};
 }
 return best;
}
function storyMinutes(a, b) { return Math.round(a.estimated_duration_min - b.estimated_duration_min); }
function storyTime(m) { return m <= 0 ? (m < 0 ? `about ${-m} min shorter` : 'about the same time') : `about ${m} min longer`; }

/** The dimension a route's name would use (asked-for dimensions first), or null. */
function lead0(r, others) {
 if (!others.length) return null;
 const asks = storyAsks().map((a) => a.dim), names = Object.keys(STORY_WORDS).filter((d) => STORY_WORDS[d].name);
 return (storyLeader(r, others, names.filter((d) => asks.includes(d))) || storyLeader(r, others, names.filter((d) => !asks.includes(d))))?.d || null;
}
/** Stories for the shown routes: {name, tag, sentence, highlights, why, via, note}. */
function storyBuild(routes) {
 const pick = storyPick(routes), shown = pick.shown, asks = storyAsks(), askDims = asks.map((a) => a.dim);
 const allDims = Object.keys(STORY_WORDS), nameDims = allDims.filter((d) => STORY_WORDS[d].name);
 const fastest = shown.reduce((a, r) => (!a || r.estimated_duration_min < a.estimated_duration_min ? r : a), null);
 const single = shown.length < 2, itinerary = routes.some((r) => r.objective === 'itinerary');
 const stories = {};
 const used = new Set();
 for (const r of shown) {
  const others = shown.filter((o) => o !== r), isFastest = r === fastest || pick.fastestToo === r.route_id;
  const places = storyPlacesNear(r) || [], otherPlaces = new Set(others.flatMap((o) => (storyPlacesNear(o) || []).map((p) => p.wd)));
  // via: the best-known listed place only this route passes, else its main street (the one others walk least)
  const kinds = {'Nature': ['parks'], 'Architecture': ['historic', 'attractions'], 'Culture': ['museums', 'culture'], 'Scenic & Visual': ['parks', 'attractions']}[lead0(r, others)] || [];
  const free = places.filter((p) => !otherPlaces.has(p.wd) && !used.has(p.wd));
  const own = kinds.length ? free.find((p) => kinds.includes(p.cat)) || null : free[0] || (single ? places[0] : null);
  let via = own?.name || null;
  if (own) used.add(own.wd);
  if (!via) {
   const mine = storyStreets(r), theirs = others.map(storyStreets);
   const street = Object.entries(mine).map(([n, m]) => [n, m - Math.max(0, ...theirs.map((t) => t[n] || 0))]).sort((a, b) => b[1] - a[1])[0];
   if (street && street[1] > 150) via = street[0];
  }
  // name
  const lead = single ? null : (storyLeader(r, others, nameDims.filter((d) => askDims.includes(d))) || storyLeader(r, others, nameDims.filter((d) => !askDims.includes(d))));
  let name;
  if (itinerary) name = r.route_name;
  else if (!single && isFastest) name = 'Fastest';
  else if (lead) name = STORY_WORDS[lead.d].name;
  else name = r.recommended ? 'Best match' : single ? 'Your walk' : 'Another way';
  const tag = r.recommended && !itinerary ? (asks.length ? 'Best match for you' : 'Best match') : '';
  // sentence
  const sentence = (() => {
   if (single) {
    const typical = allDims.map((d) => ({d, diff: storyScore(r, d) == null ? null : storyScore(r, d) - 50})).filter((t) => t.diff != null && t.diff >= STORY.TYPICAL - 50);
    const order = [...typical.filter((t) => askDims.includes(t.d)), ...typical.filter((t) => !askDims.includes(t.d)).sort((a, b) => b.diff - a.diff)].slice(0, 2);
    const main = Object.entries(storyStreets(r)).sort((a, b) => b[1] - a[1])[0];
    const parts = [];
    if (main && main[1] > 150) parts.push(`Mostly along ${main[0]}.`);
    if (order.length) parts.push(`${storyCap(storyJoin(order.map((t) => STORY_WORDS[t.d].more)))} than a typical Manhattan street.`);
    return parts.join(' ') || null;
   }
   if (isFastest) {
    const main = Object.entries(storyStreets(r)).sort((a, b) => b[1] - a[1])[0];
    const lows = asks.filter((a) => others.length && others.every((o) => { const d = storyDiff(r, o, a.dim); return d != null && (a.low ? d >= STORY.MORE : d <= -STORY.MORE); }));
    let s = `The most direct way${main && main[1] > 150 ? `, mostly along ${main[0]}` : ''}`;
    if (pick.fastestToo === r.route_id) s += ', and it ranks best for what you asked';
    s += '.';
    if (lows.length) s += ` ${storyCap(storyJoin(lows.slice(0, 2).map((a) => a.low ? STORY_WORDS[a.dim].more : STORY_WORDS[a.dim].less)))} than the other options.`;
    return s;
   }
   const tr = storyTraits(r, fastest, allDims);
   const good = [...tr.filter((t) => askDims.includes(t.d) && (asks.find((a) => a.dim === t.d).low ? t.diff < 0 : t.diff > 0)),
    ...tr.filter((t) => !askDims.includes(t.d) && t.diff > 0 && STORY_WORDS[t.d].name).sort((a, b) => b.diff - a.diff)].slice(0, 2);
   const bad = tr.filter((t) => askDims.includes(t.d) && (asks.find((a) => a.dim === t.d).low ? t.diff > 0 : t.diff < 0));
   const m = storyMinutes(r, fastest);
   let s = good.length ? `${storyCap(storyJoin(good.map((t) => traitWord(t, asks.find((a) => a.dim === t.d)?.low))))} than the fastest way` : 'Different streets, a similar feel to the fastest way';
   if (bad.length) s += `, but ${traitWord(bad[0], asks.find((a) => a.dim === bad[0].d)?.low)}`;
   return `${s}; ${storyTime(m)}.`;
  })();
  // highlights: what this route clearly has more of than the others (or than a typical street), plus real places
  const ref = single ? null : others;
  const chips = [];
  for (const d of [...allDims.filter((x) => askDims.includes(x)), ...allDims.filter((x) => !askDims.includes(x))]) {
   if (chips.length >= 2) break;
   const v = storyScore(r, d); if (v == null) continue;
   const ok = ref ? ref.every((o) => { const x = storyScore(o, d); return x != null && v - x >= STORY.MORE; }) : v >= STORY.TYPICAL;
   if (ok) chips.push(STORY_WORDS[d].chip);
  }
  const pc = storyPlaceChip(places); if (pc) chips.push(pc);
  // why it fits you: the user's own priorities, in the same comparisons
  let why;
  if (!asks.length) why = 'No preference set yet, so all 12 experience dimensions count equally.';
  else {
   const parts = asks.slice(0, 2).map((a) => {
    const w = STORY_WORDS[a.dim], v = storyScore(r, a.dim);
    if (v == null) return `${w.noun} not measured on enough of this route`;
    if (!single) {
     const leads = others.every((o) => { const x = storyScore(o, a.dim); return x != null && (a.low ? x - v : v - x) >= STORY.LEAD; });
     if (leads) return a.low ? `the least ${w.noun} of the ${shown.length}` : `the ${w.sup} of the ${shown.length}`;
     if (!isFastest) { const t = {d: a.dim, diff: storyDiff(r, fastest, a.dim)}; if (t.diff != null && Math.abs(t.diff) >= STORY.MORE) return `${traitWord(t, a.low)} than the fastest`; return `similar ${w.noun} to the fastest`; }
     const trails = others.every((o) => { const x = storyScore(o, a.dim); return x != null && (a.low ? v - x : x - v) >= STORY.MORE; });
     return trails ? `${a.low ? w.more : w.less} than the others` : `similar ${w.noun} to the others`;
    }
    return v >= STORY.TYPICAL ? `${w.more} than a typical Manhattan street` : v <= 100 - STORY.TYPICAL ? `${w.less} than a typical Manhattan street` : `about typical ${w.noun} for Manhattan`;
   });
   const asked = storyJoin(asks.slice(0, 2).map((a) => (a.low ? 'less ' : '') + STORY_WORDS[a.dim].ask));
   why = parts.every((x) => x.startsWith('similar')) ? `You asked for ${asked}: ${isFastest ? 'about the same as the other options' : 'about the same as the fastest way'}${parts.length > 1 ? ' on both' : ''}.` : `You asked for ${asked}: ${storyJoin(parts)}.`;
  }
  const water = r.independent_metrics?.waterfront?.within_100m_share;
  if (typeof planner !== 'undefined' && planner.waterfront && water != null) why += ` ${Math.round(water * 100)}% of it within 100 m of the water.`;
  const note = r.constraints?.feasible === false ? `Outside your limits: ${(r.constraints.violations || []).join('; ')}` : null;
  stories[r.route_id] = {name: via && !itinerary ? `${name} · via ${via}` : name, short: name, tag, sentence, highlights: chips.slice(0, 3), why, via, note};
 }
 for (const r of pick.extra) stories[r.route_id] = {name: r.route_name, short: r.route_name, tag: '', sentence: null, highlights: [], why: null, via: null, note: r.constraints?.feasible === false ? `Outside your limits: ${(r.constraints.violations || []).join('; ')}` : null};
 routeStory.last = {shown: shown.map((r) => r.route_id), extra: pick.extra.map((r) => r.route_id), stories};
 return routeStory.last;
}

/* ---------- "Along this walk": how the selected route feels, stretch by stretch ---------- */
function storyStretches(r) {
 const edges = (r?.edges || []).filter((e) => (e.traversed_length_m || 0) > 0), total = edges.reduce((s, e) => s + e.traversed_length_m, 0);
 if (total < 500) return [];
 const n = total < 1200 ? 2 : 3, pace = r.estimated_duration_min / Math.max(1, r.distance_m), parts = [];
 let i = 0, acc = 0;
 for (let k = 0; k < n; k++) {
  const until = total * (k + 1) / n, list = [];
  while (i < edges.length && (acc < until || k === n - 1)) { list.push(edges[i]); acc += edges[i].traversed_length_m; i++; }
  if (list.length) parts.push(list);
 }
 const mean = (list, d) => { let s = 0, m = 0; for (const e of list) { const v = e.dimension_scores?.[d]; if (v == null) continue; s += v * e.traversed_length_m; m += e.traversed_length_m; } const len = list.reduce((a, e) => a + e.traversed_length_m, 0); return m / len >= STORY.COVER ? s / m : null; };
 const whole = Object.fromEntries(STORY_FEEL.map((d) => [d, mean(edges, d)]));
 let prev = null;
 return parts.map((list, k) => {
  const len = list.reduce((a, e) => a + e.traversed_length_m, 0), min = Math.max(1, Math.round(len * pace));
  const by = {}; for (const e of list) { const s = storyStreet(e); if (s) by[s] = (by[s] || 0) + e.traversed_length_m; }
  const street = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
  const traits = STORY_FEEL.map((d) => { const v = mean(list, d); return {d, diff: v == null || whole[d] == null ? null : v - whole[d]}; })
   .filter((t) => t.diff != null && Math.abs(t.diff) >= 10).sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff)).slice(0, 2);
  const when = k === 0 ? `First ${min} min` : k === parts.length - 1 ? `Last ${min} min` : `Next ${min} min`;
  const name = street && street[1] > len * 0.3 ? street[0] : null, same = name && name === prev;
  prev = name;
  const where = name ? (same ? `, still on ${name}` : `, along ${name}`) : '';
  const feel = traits.length ? `: ${storyJoin(traits.map((t) => (t.diff > 0 ? STORY_WORDS[t.d].more : STORY_WORDS[t.d].less)))} than the rest of the walk` : '';
  return `${when}${where}${feel}.`;
 });
}

/* ---------- map preview: this route bold, the other shown routes faint ---------- */
function storyPreviewSvg(r, shown) {
 const all = shown.length ? shown : [r];
 let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
 for (const x of all) for (const [lon, lat] of x.geometry?.coordinates || []) { w = Math.min(w, lon); e = Math.max(e, lon); s = Math.min(s, lat); n = Math.max(n, lat); }
 if (!Number.isFinite(w)) return '';
 const k = Math.cos((s + n) / 2 * Math.PI / 180), W = Math.max(1e-6, (e - w) * k), H = Math.max(1e-6, n - s);
 const VW = 100, VH = 100, pad = 9, sc = Math.min((VW - 2 * pad) / W, (VH - 2 * pad) / H), ox = (VW - W * sc) / 2, oy = (VH - H * sc) / 2;
 const pt = ([lon, lat]) => `${(ox + (lon - w) * k * sc).toFixed(1)},${(oy + (n - lat) * sc).toFixed(1)}`;
 const line = (x, cls) => `<polyline class="${cls}" points="${(x.geometry?.coordinates || []).map(pt).join(' ')}"/>`;
 const c = r.geometry?.coordinates || [], a = c[0] && pt(c[0]).split(','), b = c.at(-1) && pt(c.at(-1)).split(',');
 return `<svg class="rs-map" viewBox="0 0 ${VW} ${VH}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Route shape">${all.filter((x) => x !== r).map((x) => line(x, 'rs-other')).join('')}${line(r, 'rs-this')}${a ? `<circle class="rs-start" cx="${a[0]}" cy="${a[1]}" r="4.5"/>` : ''}${b ? `<circle class="rs-end" cx="${b[0]}" cy="${b[1]}" r="4.5"/>` : ''}</svg>`;
}

if (typeof window !== 'undefined') {
 window.routeStory = routeStory;
 Object.assign(routeStory, {build: storyBuild, pick: storyPick, stretches: storyStretches, preview: storyPreviewSvg, placesNear: storyPlacesNear, overlap: storyOverlap, ensurePlaces: storyEnsurePlaces, WORDS: STORY_WORDS, LIMITS: STORY});
}
