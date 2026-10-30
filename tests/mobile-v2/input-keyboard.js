'use strict';
// iOS input auto-zoom + keyboard layout (round 10): the Plan walk flow on phone sizes.
// SIMULATED: Chromium cannot reproduce iOS's focus zoom, the virtual keyboard or the Home Screen viewport. What it
// can prove: every text field computes to ≥16px on touch devices (the trigger for iOS zoom), nothing is wider than
// the screen, focusing a field raises the sheet and keeps the field on screen, a (simulated) keyboard overlap pads
// the sheet, suggestions are selectable, and the From / To / preferences state survives to a real route.
// Place providers are MOCKED (external services); routing and app state are real.
// REAL IPHONE VERIFICATION REQUIRED (Safari tab and Home Screen app).
const { launch, newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0;
const check = (dev, name, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} [${dev}] ${name}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
const DEVICES = [['iPhone SE', 375, 667], ['iPhone 13/14', 390, 844], ['iPhone 15 Pro', 393, 852], ['iPhone 17 Pro Max', 440, 956], ['Android (Pixel 8)', 412, 915]];
const layout = (page) => page.evaluate(() => {
  const vis = (e) => !!e.offsetParent;
  const fields = [...document.querySelectorAll('input:not([type=range]):not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea,select')];
  const small = fields.filter((e) => parseFloat(getComputedStyle(e).fontSize) < 16).map((e) => `${e.id}:${getComputedStyle(e).fontSize}`);
  const bar = document.querySelector('#leftPanel .m-sheet-bar');
  const btns = bar ? [...bar.querySelectorAll('button')].filter(vis).map((b) => { const r = b.getBoundingClientRect(); return { t: b.textContent.trim(), l: Math.round(r.left), r: Math.round(r.right), clipped: b.scrollWidth > b.clientWidth + 1 }; }) : [];
  return { iw: innerWidth, ih: innerHeight, docW: document.documentElement.scrollWidth, bodyW: document.body.scrollWidth, small, btns };
});
(async () => {
  const b = await launch();
  for (const [dev, w, h] of DEVICES) {
    const { page, log } = await newPage(b, { width: w, height: h, geo: { latitude: 40.7536, longitude: -73.9832, accuracy: 10 } });
    // MOCKED place providers (Photon, NYC GeoSearch are external; the test sandbox has no route to them). The
    // fixtures are the real coordinates of the two parks; selection, state and routing below are real.
    await page.route(/photon\.komoot\.io|geosearch\.planninglabs\.nyc/, (route) => {
      const q = new URL(route.request().url()).searchParams;
      const text = (q.get('q') || q.get('text') || '').toLowerCase();
      const P = { 'bryant park': [-73.9832, 40.7536, 2192245], 'central park': [-73.9654, 40.7829, 427818536] };
      const hit = Object.entries(P).find(([k]) => k.startsWith(text.slice(0, 6)) || text.includes(k));
      const photon = /photon/.test(route.request().url());
      const feats = !hit ? [] : photon
        ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: hit[1].slice(0, 2) }, properties: { name: hit[0].replace(/\b\w/g, (c) => c.toUpperCase()), osm_type: 'W', osm_id: hit[1][2], osm_key: 'leisure', osm_value: 'park', city: 'New York', district: 'Manhattan', state: 'New York' } }]
        : [];
      route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ type: 'FeatureCollection', features: feats }) });
    });
    await openApp(page, 1500);
    const coarse = await page.evaluate(() => matchMedia('(pointer:coarse)').matches);
    const L0 = await layout(page);
    check(dev, 'touch device: every text field (incl. hidden ones) computes to ≥ 16px — no iOS focus zoom trigger', coarse && L0.small.length === 0, { coarse, small: L0.small });
    await page.click('#mobileMore summary'); await page.click('[data-mview-go="plan"]'); await page.waitForTimeout(600);
    const L1 = await layout(page);
    check(dev, 'Plan walk: no horizontal overflow; ←, Prefs and Find routes fully on screen, labels not clipped', L1.docW <= w && L1.bodyW <= w && L1.btns.length >= 3 && L1.btns.every((x) => x.l >= 0 && x.r <= w && !x.clipped), L1);
    const endBefore = await page.evaluate(() => getPlace('end')?.name);
    // From: focus → sheet full, field near the top of the visible area
    await page.click('#searchStart'); await page.waitForTimeout(450);
    const f = await page.evaluate(() => { const r = document.getElementById('searchStart').closest('.search-place').getBoundingClientRect(), bar = document.querySelector('#leftPanel .m-sheet-bar').getBoundingClientRect();
      return { level: $('leftPanel').dataset.level, top: Math.round(r.top), bottom: Math.round(r.bottom), barBottom: Math.round(bar.bottom), focused: document.activeElement.id, scrollY }; });
    check(dev, 'focusing From raises the sheet to full; the field (and its FROM label) sits just below the title bar, in the upper half', f.focused === 'searchStart' && f.level === 'full' && f.top >= f.barBottom + 4 && f.top <= f.barBottom + 100 && f.bottom <= h * 0.5 && f.scrollY === 0, f);
    // Simulated keyboard: shrink the visual viewport the way iOS does (layout viewport unchanged)
    await page.evaluate(([H]) => {
      const vv = window.visualViewport, kb = Math.round(H * 0.42);
      Object.defineProperty(vv, 'height', { configurable: true, get: () => H - kb });
      Object.defineProperty(vv, 'offsetTop', { configurable: true, get: () => 0 });
      vv.dispatchEvent(new Event('resize'));
    }, [h]); await page.waitForTimeout(150);
    const k = await page.evaluate(() => ({ open: document.documentElement.classList.contains('kb-open'), kb: getComputedStyle(document.documentElement).getPropertyValue('--kb').trim(),
      pad: getComputedStyle(document.querySelector('#leftPanel .panel-scroll')).paddingBottom, fieldBottom: Math.round(document.getElementById('searchStart').getBoundingClientRect().bottom), vvH: visualViewport.height }));
    check(dev, 'keyboard overlap measured from visualViewport → sheet padded by it; field stays above the keyboard', k.open && parseInt(k.kb) > 0 && parseInt(k.pad) >= parseInt(k.kb) && k.fieldBottom <= k.vvH, k);
    await page.fill('#searchStart', 'Bryant Park');
    await page.waitForSelector('#searchStartList .ps-item', { timeout: 15000 }).catch(() => {});
    const sug = await page.evaluate(() => { const l = document.getElementById('searchStartList'), it = l?.querySelector('.ps-item'); const r = l?.getBoundingClientRect();
      return { n: l ? l.querySelectorAll('.ps-item').length : 0, first: it?.querySelector('.ps-name')?.textContent, left: r && Math.round(r.left), right: r && Math.round(r.right), top: r && Math.round(r.top), vvH: visualViewport.height }; });
    check(dev, 'suggestions appear for "Bryant Park", within the screen width and starting above the keyboard', sug.n > 0 && sug.left >= 0 && sug.right <= w && sug.top < sug.vvH, sug);
    await shot(page, `kb-${dev.replace(/\W+/g, '-').toLowerCase()}-suggest.png`);
    if (sug.n) await page.locator('#searchStartList .ps-item').first().dispatchEvent('mousedown');
    await page.waitForTimeout(800);
    const sel = await page.evaluate(() => ({ start: getPlace('start')?.name, value: $('searchStart').value, focused: document.activeElement?.id, end: getPlace('end')?.name }));
    check(dev, 'choosing a suggestion sets the start, keeps the destination, and ends typing (field blurred → keyboard closes)', /Bryant Park/i.test(sel.start || '') && sel.value === sel.start && sel.focused !== 'searchStart' && sel.end === endBefore, sel);
    // keyboard closes
    await page.evaluate(([H]) => { const vv = window.visualViewport; Object.defineProperty(vv, 'height', { configurable: true, get: () => H }); vv.dispatchEvent(new Event('resize')); }, [h]); await page.waitForTimeout(150);
    const kc = await page.evaluate(() => ({ open: document.documentElement.classList.contains('kb-open'), kb: getComputedStyle(document.documentElement).getPropertyValue('--kb').trim(), sx: scrollX, sy: scrollY, map: Math.round(document.getElementById('map').getBoundingClientRect().height) }));
    check(dev, 'keyboard closed: layout restored (no padding, no pan), map full height', !kc.open && kc.kb === '0px' && kc.sx === 0 && kc.sy === 0 && kc.map === h, kc);
    // To: Central Park
    await page.click('#searchEnd'); await page.fill('#searchEnd', 'Central Park');
    await page.waitForSelector('#searchEndList .ps-item', { timeout: 15000 }).catch(() => {});
    if (await page.locator('#searchEndList .ps-item').count()) await page.locator('#searchEndList .ps-item').first().dispatchEvent('mousedown');
    await page.waitForTimeout(800);
    const to = await page.evaluate(() => ({ start: getPlace('start')?.name, end: getPlace('end')?.name }));
    check(dev, 'destination set to Central Park; start kept', /Central Park/i.test(to.end || '') && /Bryant Park/i.test(to.start || ''), to);
    // Preferences and back
    const prefsBefore = await page.evaluate(() => JSON.stringify(planner?.weights || state.weights || null));
    await page.click('#mSheetAlt'); await page.waitForTimeout(500);
    const v1 = await page.evaluate(() => document.body.dataset.mview);
    await page.click('#mSheetAlt'); await page.waitForTimeout(500);
    const back = await page.evaluate(() => ({ view: document.body.dataset.mview, start: getPlace('start')?.name, end: getPlace('end')?.name }));
    const prefsAfter = await page.evaluate(() => JSON.stringify(planner?.weights || state.weights || null));
    check(dev, 'Prefs and back: From, To and preferences intact', v1 === 'customize' && back.view === 'plan' && /Bryant/.test(back.start) && /Central/.test(back.end) && prefsBefore === prefsAfter, { v1, back });
    const L2 = await layout(page);
    check(dev, 'after the whole keyboard flow: still no horizontal overflow and nothing clipped', L2.docW <= w && L2.btns.every((x) => x.r <= w && !x.clipped), L2);
    // Find routes
    await page.click('#mSheetGo');
    await page.waitForFunction(() => document.body.dataset.mview === 'results', null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(800);
    const rr = await page.evaluate(() => ({ view: document.body.dataset.mview, routes: state.routes.length, line: state.map.getSource('selected-route')?._data?.features?.length ?? null, mapH: Math.round(document.getElementById('map').getBoundingClientRect().height) }));
    check(dev, 'Find routes → real route on the map (map not re-initialised, full height)', rr.view === 'results' && rr.routes > 0 && rr.mapH === h, rr);
    await shot(page, `kb-${dev.replace(/\W+/g, '-').toLowerCase()}-route.png`);
    check(dev, 'no page errors', log.errors.length === 0, log.errors.slice(0, 3));
    await page.context().close();
  }
  // Desktop unchanged: fields keep their compact size (fine pointer), three-column layout
  const { page } = await newPage(b, { width: 1440, height: 900 });
  await openApp(page, 1200);
  const d = await page.evaluate(() => ({ coarse: matchMedia('(pointer:coarse)').matches, fs: getComputedStyle(document.getElementById('searchStart')).fontSize, left: getComputedStyle(document.querySelector('.left-panel')).display }));
  check('desktop', 'mouse pointer: compact field type kept, desktop layout unchanged', !d.coarse && d.fs === '12px' && d.left !== 'none', d);
  await b.close();
  console.log(`\n${total - failed}/${total} checks passed (simulated keyboard; REAL IPHONE VERIFICATION REQUIRED)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
