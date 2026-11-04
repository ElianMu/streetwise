const { launch, newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0; const check = (n, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${n}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
(async () => {
  const b = await launch();
  // 1) location allowed, inside Manhattan: the start is the user's location
  { const { page, log } = await newPage(b, { width: 440, height: 956, geo: { latitude: 40.7484, longitude: -73.9857, accuracy: 10 } });
    await openApp(page, 2500); await page.waitForTimeout(800);
    const r = await page.evaluate(() => ({ start: state.start, from: $('mContextFrom').textContent, search: $('searchStart').value }));
    check('location allowed: start = my location (From row and Plan field)', r.start === 'gps' && r.from === 'My current location' && r.search === 'My current location', r);
    // 2) typing a request with from / to updates From / To while typing
    await page.click('#intentText'); await page.fill('#intentText', ''); await page.type('#intentText', 'Walk from Washington Square Park to Union Square', { delay: 5 });
    await page.waitForFunction(() => /Union Square/.test($('mContextTo').textContent) && /Washington Square/.test($('mContextFrom').textContent), null, { timeout: 15000 }).catch(() => {});
    const t = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent, start: getPlace('start')?.name, end: getPlace('end')?.name, sStart: $('searchStart').value, sEnd: $('searchEnd').value }));
    check('typing "from … to …" updates From / To (state, rows and Plan fields) before Create', /Washington Square/.test(t.from) && /Union Square/.test(t.to) && t.start === t.sStart && t.end === t.sEnd && /Washington Square/.test(t.start) && /Union Square/.test(t.end), t);
    await page.fill('#intentText', '从时代广场出发，去中央公园'); await page.dispatchEvent('#intentText', 'input');
    await page.waitForFunction(() => $('mContextTo').textContent === 'Central Park', null, { timeout: 15000 }).catch(() => {});
    const z = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent }));
    check('Chinese request (从…出发，去…) updates From / To', z.from === 'Times Square' && z.to === 'Central Park', z);
    await page.fill('#intentText', 'i will go to columbia university from my location'); await page.dispatchEvent('#intentText', 'input');
    await page.waitForFunction(() => /Columbia University/.test($('mContextTo').textContent) && state.start === 'gps', null, { timeout: 15000 }).catch(() => {});
    const c = await page.evaluate(() => ({ start: state.start, from: $('mContextFrom').textContent, to: $('mContextTo').textContent }));
    check('the reported request "i will go to columbia university from my location": From = my location, To = Columbia University', c.start === 'gps' && c.from === 'My current location' && /^Columbia University/.test(c.to), c);
    await page.fill('#intentText', '从时代广场出发，去中央公园'); await page.dispatchEvent('#intentText', 'input');
    await page.waitForFunction(() => $('mContextTo').textContent === 'Central Park', null, { timeout: 15000 }).catch(() => {});
    await page.fill('#intentText', 'A quiet walk with architecture'); await page.dispatchEvent('#intentText', 'input'); await page.waitForTimeout(1200);
    const k = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent }));
    check('a request without places leaves From / To as they are', k.from === 'Times Square' && k.to === 'Central Park', k);
    await page.fill('#intentText', 'from here to the Empire State Building'); await page.dispatchEvent('#intentText', 'input');
    await page.waitForFunction(() => $('mContextTo').textContent === 'Empire State Building', null, { timeout: 15000 }).catch(() => {});
    const h = await page.evaluate(() => ({ start: state.start, from: $('mContextFrom').textContent, to: $('mContextTo').textContent }));
    check('"from here" = my location', h.start === 'gps' && h.from === 'My current location' && h.to === 'Empire State Building', h);
    await shot(page, 'live-ends.png');
    check('no page errors', log.errors.length === 0, log.errors.slice(0, 3));
    await page.context().close(); }
  // 3) location refused: preset stays (never invented), the existing "where should this start?" flow still asks
  { const { page } = await newPage(b, { width: 440, height: 956 });
    await openApp(page, 2500);
    const r = await page.evaluate(() => ({ start: state.start, from: $('mContextFrom').textContent }));
    check('no location permission: start stays the preset, nothing invented', r.start === 'bryant' && r.from === 'Bryant Park', r);
    await page.context().close(); }
  // 4) location outside Manhattan: preset kept, user told why
  { const { page } = await newPage(b, { width: 440, height: 956, geo: { latitude: 40.6782, longitude: -73.9442, accuracy: 10 } });
    await page.addInitScript(() => { window.__toasts = []; document.addEventListener('DOMContentLoaded', () => { const t = document.querySelector('.toast') || document.getElementById('toast'); if (t) new MutationObserver(() => { const x = t.textContent.trim(); if (x) window.__toasts.push(x); }).observe(t, { childList: true, characterData: true, subtree: true }); }); });
    await openApp(page, 2500); await page.waitForTimeout(800);
    // the note is a toast; another toast can replace it a moment later, so record every toast text that appears
    const r = await page.evaluate(() => ({ start: state.start, gps: !!state.gps, toast: (window.__toasts || []).join(' | ') || document.querySelector('.toast')?.textContent || '' }));
    check('location outside Manhattan: start stays the preset, with a note', r.start === 'bryant' && r.gps && /outside Manhattan/.test(r.toast), r);
    await page.context().close(); }
  // 5) results sheet (phone): ONE "01 / Refine your walk" section under the routes = quick options + conversation
  { const { page, log } = await newPage(b, { width: 440, height: 956 });
    await openApp(page, 2000);
    await page.evaluate(() => generateRoutes()); await page.waitForFunction(() => state.routes.length > 0, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(800);
    const r = await page.evaluate(() => { const sec = $('conversationSection'), vis = (e) => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
      const heads = [...$('rightPanel').querySelectorAll('.section-overline')].filter(vis).map((e) => e.textContent.trim()).filter((t) => /REFINE/i.test(t));
      const chips = sec.querySelector('.refine-actions'), form = $('chatForm'), cards = $('routeCards');
      return { label: $('conversationLabel').textContent, heads, inside: sec.contains($('refineQuick')), visible: vis(sec), chips: chips ? chips.querySelectorAll('button').length : 0,
        chipsBeforeChat: !!(chips && form && (chips.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING)),
        afterRoutes: !!(cards.compareDocumentPosition(sec) & Node.DOCUMENT_POSITION_FOLLOWING), countShown: vis($('conversationCount')) };
    });
    check('phone results: one "01 / REFINE YOUR WALK" section (quick options + conversation) right after the routes', r.label === '01 / REFINE YOUR WALK' && r.heads.length === 1 && r.heads[0] === '01 / REFINE YOUR WALK' && r.inside && r.visible && r.chips >= 4 && r.chipsBeforeChat && r.afterRoutes && !r.countShown, r);
    // the sheet label stays inside its handle (it overlapped the first line of the sheet before)
    const o = await page.evaluate(() => { const h = $('rightPanel').querySelector('.sheet-handle').getBoundingClientRect(), t = $('rightPanel').querySelector('.sheet-toggle').getBoundingClientRect(); return { hb: Math.round(h.bottom), tb: Math.round(t.bottom) }; });
    check('"Your routes" label inside the sheet handle (no overlap with the content)', o.tb <= o.hb, o);
    await page.evaluate(() => { const s = $('rightPanel').querySelector('.panel-scroll,.right-scroll') || $('rightPanel'); $('conversationSection').scrollIntoView({ block: 'start' }); });
    await page.waitForTimeout(300); await shot(page, 'refine-merged.png');
    check('no page errors', log.errors.length === 0, log.errors.slice(0, 3));
    await page.context().close();
    // desktop keeps its layout: step 05 conversation on the left, options on the right
    const d = await newPage(b, { width: 1440, height: 900 }); await openApp(d.page, 1500);
    const dk = await d.page.evaluate(() => ({ label: $('conversationLabel').textContent, opts: $('rightPanel').contains($('refineQuick')), conv: $('leftPanel').contains($('conversationSection')) }));
    check('desktop unchanged: "05 / REFINE YOUR WALK" conversation on the left, options in the right panel', dk.label === '05 / REFINE YOUR WALK' && dk.opts && dk.conv, dk);
    await d.page.context().close(); }
  await b.close(); console.log(`\n${total - failed}/${total} checks passed (live From/To + GPS start + refine section)`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
