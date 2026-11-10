'use strict';
// Experience-first results: a "from A to B" sentence gives 2–3 walks that feel different, each told in words
// (name, one sentence, distance and time). Scores, coverage and OSM edges are not in the main view, but all of them are
// still one tap away (card "Details" and "Technical details"). Every word on a card must match the engine's scores.
// Runs against the real server.py (real routing engine, real place index); nothing is mocked.
const { launch, newPage, openApp, shot } = require('./harness');
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
let failed = 0, total = 0; const check = (n, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${n}${ok ? '' : ' — ' + JSON.stringify(d)}`); };

async function plan(page, text, phone) {
  const calls = []; const on = (r) => { if (/\/api\/(routes|itinerary)$/.test(r.url())) calls.push(new URL(r.url()).pathname); };
  page.on('request', on);
  if (phone) await page.click('#intentText');
  await page.fill('#intentText', text);
  await page.click(phone ? '#mCreate' : '#generateRoutes');
  await page.waitForTimeout(1500);
  await page.waitForFunction(() => state.routes.length && !state.routingBusy, null, { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(2500); // the place index (for "via" names) loads once, then the cards re-render
  page.off('request', on);
  return calls;
}
// What the main view shows (visible cards only, without their folded Details)
const mainView = (page) => page.evaluate(() => [...document.querySelectorAll('#routeCards .route-card:not(.hidden)')].map((c) => ({
  id: c.dataset.route, name: c.querySelector('.rc-name')?.textContent || '', sentence: c.querySelector('.rc-sentence')?.textContent || '',
  meta: c.querySelector('.rc-meta')?.textContent || '', pick: c.querySelector('.route-pick').innerText, imgs: [...c.querySelectorAll('img')].map((i) => ({ src: i.src, credit: i.closest('figure')?.querySelector('figcaption')?.textContent || i.getAttribute('data-credit') || '' })) })));

(async () => {
  const b = await launch();
  for (const [label, vp, phone] of [['desktop', { width: 1440, height: 900 }, false], ['phone', { width: 402, height: 874 }, true]]) {
    const { page, log, context } = await newPage(b, vp);
    const wm = await wikimedia(page, 'up');
    await openApp(page, 2500);
    // 1) an A→B sentence asks the routing engine for alternatives and shows 2–3 cards
    const calls = await plan(page, 'A quiet, green walk from Bryant Park to Union Square.', phone);
    const cards = await mainView(page);
    check(`${label}: A→B sentence → /api/routes, 2–3 walk cards`, calls.includes('/api/routes') && !calls.includes('/api/itinerary') && cards.length >= 2 && cards.length <= 3, { calls, n: cards.length });
    // 2) each card: a name, one sentence, distance and time
    check(`${label}: every card has a name, a sentence, km and minutes`, cards.every((c) => c.name.length > 2 && c.sentence.length > 10 && /\d(\.\d)? km/.test(c.meta) && /\d+ min/.test(c.meta)), cards.map((c) => [c.name, c.sentence, c.meta]));
    // 3) no scores, coverage or edge counts in the main view
    const research = /Personalized|Overall \d|coverage|OSM edges?|utility|weight \d|fit \d|Σ/i;
    check(`${label}: no score, coverage or edge count in the main view`, cards.every((c) => !research.test(c.pick)), cards.filter((c) => research.test(c.pick)).map((c) => c.pick));
    // 4) …all still there: per card under Details, and in Technical details
    const kept = await page.evaluate(() => ({
      details: [...document.querySelectorAll('#routeCards .route-card')].every((c) => { const t = c.querySelector('.route-numbers')?.textContent || ''; return /Personalized score/.test(t) && /Data coverage/.test(t) && /OSM edges/.test(t) && /Hard limits used/.test(t); }),
      inTech: ['whyRoute', 'profileChart', 'routeEdgeList', 'rankingStatus', 'wxRoute', 'routeUrbanData', 'segmentDetail'].every((id) => $('techDetails').contains($(id))),
      why: /Personalized score/.test($('whyRoute').textContent), profile: document.querySelectorAll('#profileChart .experience-row').length,
      edges: document.querySelectorAll('#routeEdgeList .edge-row').length === state.routes.find((r) => r.id === state.activeRoute).raw.ordered_edge_ids.length,
      techClosed: !$('techDetails').open }));
    check(`${label}: scores, formula, 12-dimension profile and edges kept (card Details + Technical details)`, kept.details && kept.inTech && kept.why && kept.profile === 12 && kept.edges && kept.techClosed, kept);
    // 5) photos: real places this walk passes, each with author, licence and its Commons page
    await page.waitForFunction(() => document.querySelectorAll('#routeCards .rp-photo').length > 0, null, { timeout: 15000 }).catch(() => {});
    const ph = await page.evaluate(() => [...document.querySelectorAll('#routeCards .route-card:not(.hidden)')].map((c) => {
      const raw = state.routes.find((r) => r.id === c.dataset.route).raw, near = (storyPlacesNear(raw) || []).map((p) => p.name);
      return [...c.querySelectorAll('.rp-photo')].map((f) => ({ alt: f.querySelector('img').alt, src: f.querySelector('img').src, credit: f.querySelector('figcaption a')?.textContent || '', href: f.querySelector('figcaption a')?.href || '', near: near.includes(f.querySelector('img').alt) }));
    }).flat());
    const credited = ph.every((x) => x.alt && /·/.test(x.credit) && /(CC|Public domain)/.test(x.credit) && /^https:\/\/commons\.wikimedia\.org\/wiki\/File:/.test(x.href) && /^https:\/\/thumb\.wikimedia\.org\//.test(x.src));
    check(`${label}: card photos are real places on that route, each credited (author · licence → Commons page) (${ph.length} photos)`, ph.length > 0 && credited && ph.every((x) => x.near), { n: ph.length, bad: ph.filter((x) => !x.near || !/·/.test(x.credit)), calls: wm });
    check(`${label}: no photo without a named author unless public domain (Farragut / Conkling files have none)`, ph.every((x) => !/Farragut|Conkling/.test(x.alt)) && ph.every((x) => !/machine-readable|panoramic|\(talk\)/i.test(x.credit)), ph.map((x) => x.credit));
    const imgs = cards.flatMap((c) => c.imgs);
    // 6) every word on a card matches the engine's scores for the routes shown
    const audit = await page.evaluate(() => {
      const W = routeStory.WORDS, L = routeStory.LIMITS, last = routeStory.last, raw = (id) => state.routes.find((r) => r.id === id).raw;
      const shown = last.shown.map(raw), fastest = shown.reduce((a, r) => (!a || r.estimated_duration_min < a.estimated_duration_min ? r : a), null);
      const sc = (r, d) => { const v = r.dimension_scores[d], c = r.data_coverage.by_dimension[d]; return v == null || c < L.COVER ? null : v; };
      const bad = [];
      for (const r of shown) {
        const st = last.stories[r.route_id], name = st.short, s = st.sentence || '';
        if (name === 'Fastest' && r.estimated_duration_min > fastest.estimated_duration_min + 1.5) bad.push(['not the fastest', name]);
        for (const [d, w] of Object.entries(W)) {
          if (w.name && name === w.name) { const v = sc(r, d); if (v == null || shown.some((o) => o !== r && (sc(o, d) == null || v - sc(o, d) < L.LEAD))) bad.push(['name not supported', name, d]); }
          if (r === fastest || !s.includes('than the fastest way')) continue;
          const head = s.split(' than the fastest way')[0].toLowerCase(), tail = s.split(' than the fastest way')[1] || '';
          const diff = sc(r, d) == null || sc(fastest, d) == null ? null : sc(r, d) - sc(fastest, d);
          if (head.includes(w.more) && !(diff != null && diff >= L.MORE)) bad.push(['claim', w.more, diff]);
          if (head.includes('much ' + w.more) && !(diff >= L.MUCH)) bad.push(['claim', 'much ' + w.more, diff]);
          if (tail.includes('but ' + w.less) && !(diff != null && diff <= -L.MORE)) bad.push(['claim', w.less, diff]);
        }
        const m = s.match(/about (\d+) min (longer|shorter)/);
        if (m && Math.abs(Math.round(r.estimated_duration_min - fastest.estimated_duration_min)) !== +m[1]) bad.push(['minutes', s]);
      }
      return { bad, n: shown.length, stories: shown.map((r) => last.stories[r.route_id].name + ' — ' + last.stories[r.route_id].sentence) };
    });
    check(`${label}: every name and sentence matches the scores it came from`, audit.bad.length === 0, audit);
    // map summary and card share the same name
    const same = await page.evaluate(() => { const x = state.routes.find((r) => r.id === state.activeRoute); return { label: x.label, card: document.querySelector('#routeCards .route-card.selected .rc-name')?.textContent }; });
    check(`${label}: the selected walk has the same name on the card and on the map`, same.label === same.card, same);
    // "More routes (n)" shows the engine's other candidates, nothing dropped
    const more = await page.evaluate(() => ({ n: state.routes.length, all: document.querySelectorAll('#routeCards .route-card').length, hidden: $('routeMore').classList.contains('hidden'), text: $('routeMore').textContent }));
    if (more.n > 3 || !more.hidden) {
      await page.click('#routeMore'); await page.waitForTimeout(300);
      const open = await page.evaluate(() => document.querySelectorAll('#routeCards .route-card:not(.hidden)').length);
      check(`${label}: "More routes" reveals every engine route`, more.all === more.n && open === more.n, { more, open });
      await page.click('#routeMore');
    }
    await shot(page, `route-cards-${label}.png`);
    // "Along this walk": stretch-by-stretch sentences for the selected walk
    const along = await page.evaluate(() => $('alongWalk').innerText);
    check(`${label}: "Along this walk" describes the selected walk stretch by stretch`, /^First \d+ min/.test(along), along);
    check(`${label}: no page errors`, log.errors.length === 0, log.errors.slice(0, 3));
    await context.close();
  }
  // Wikimedia unreachable: the cards show without photos, nothing breaks
  { const { page, log, context } = await newPage(b, { width: 1440, height: 900 }); await wikimedia(page, 'down'); await openApp(page, 2500);
    await plan(page, 'A quiet, green walk from Bryant Park to Union Square.', false); await page.waitForTimeout(1500);
    const r = await page.evaluate(() => ({ cards: document.querySelectorAll('#routeCards .route-card:not(.hidden)').length, photos: document.querySelectorAll('.rp-photo').length, names: [...document.querySelectorAll('.rc-name')].map((n) => n.textContent) }));
    check('Wikimedia unreachable → cards without photos, no errors', r.cards >= 2 && r.photos === 0 && log.errors.length === 0, { r, errors: log.errors.slice(0, 2) });
    await context.close(); }
  // a walk with a stop still goes to the itinerary planner (one city-walk route)
  { const { page, context } = await newPage(b, { width: 1440, height: 900 }); await wikimedia(page, 'up'); await openApp(page, 2500);
    const calls = await plan(page, 'Walk from Bryant Park to Union Square via the Empire State Building.', false);
    const r = await page.evaluate(() => ({ n: state.routes.length, stops: journey.named.map((n) => n.place.name), name: document.querySelector('#routeCards .rc-name')?.textContent }));
    check('a sentence with a stop still plans a city walk with that stop (itinerary)', calls.includes('/api/itinerary') && r.n === 1 && r.stops.includes('Empire State Building'), { calls, r });
    // removing the stop gives the A→B choice back
    await page.evaluate(() => { const id = journey.named[0].place.id; journey.removed.add(id); journey.named = []; });
    const back = await page.evaluate(() => journeyMode());
    check('with the stop removed, the walk is A→B again (routes, not itinerary)', back === false, { back });
    // Chinese A→B
    await page.evaluate(() => { journey.removed.clear(); });
    const zh = await plan(page, '从布莱恩特公园到洛克菲勒中心', false);
    const n = await page.evaluate(() => document.querySelectorAll('#routeCards .route-card:not(.hidden)').length);
    check('Chinese "从A到B" → /api/routes and 2–3 cards', zh.includes('/api/routes') && n >= 2 && n <= 3, { zh, n });
    await context.close(); }
  await b.close();
  console.log(`\n${total - failed}/${total} checks passed (experience-first route cards)`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
