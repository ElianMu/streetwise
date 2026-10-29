'use strict';
// Reproduces the viewport measured on a real iPhone 17 Pro Max Home Screen app (black-translucent status bar):
// screen 440x956pt, but WebKit reports innerHeight = 894 (956 - 62) and only shows the page from 0 to 894pt;
// the bottom 62pt are a flat system strip painted in the page background colour (WebKit bug 301994, iOS 26.1+).
// The page CANNOT draw into that strip (round 2 tried; content placed there never appeared on the device).
// SIMULATED in Chromium: navigator.standalone=true and screen.width/height are injected before the page loads,
// the viewport is screen - status bar, and the top inset is injected through --sat (Chromium has no env()).
// Pass criteria (what the page controls): the map fills the whole drawable viewport (0..innerHeight), the strip is
// detected, no second home-indicator inset is reserved (the indicator lies inside the system strip), the map
// fades into exactly the strip colour (--bg), every control/sheet/nav bar stays inside the drawable viewport.
// This is NOT a real-device test: REAL DEVICE VERIFICATION REQUIRED.
const { launch, newPage, openApp, shot } = require('./harness');
const CASES = [
  // [label, screen w, screen h, status-bar inset, strip expected]
  ['iPhone 16/17 Pro Max', 440, 956, 62, true],
  ['iPhone 16 Pro / 17 / 17 Pro', 402, 874, 62, true],
  ['iPhone 14 Pro / 15 / 16', 393, 852, 59, true],
  ['iPhone 13/14', 390, 844, 47, true],
  ['iPhone SE', 375, 667, 20, false],
];
let failed = 0, total = 0;
const check = (dev, name, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} [${dev}] ${name}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
const measure = (page) => page.evaluate(() => {
  const R = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height), vis: !!e.offsetParent }; };
  const c = document.querySelector('#map canvas'); const cs = getComputedStyle(document.documentElement);
  return { innerHeight, vv: window.visualViewport ? Math.round(visualViewport.height) : null, scrollH: document.documentElement.scrollHeight,
    strip: document.documentElement.classList.contains('ios-system-strip'), stripPt: document.documentElement.dataset.iosStrip,
    sab: cs.getPropertyValue('--sab').trim(), bg: cs.getPropertyValue('--bg').trim(),
    shell: R('.site-shell'), map: R('#map'), canvasH: c && c.clientHeight, footer: R('.map-footer'),
    footerBg: getComputedStyle(document.querySelector('.map-footer')).backgroundImage,
    zoom: R('.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group'), gps: R('#mapLocate'), urban: R('#mUrbanBtn'),
    header: R('.topbar'), card: R('#mComposer'),
    diag: window.strollaneLayoutReport ? window.strollaneLayoutReport() : '' };
});
(async () => {
  const b = await launch();
  for (const [dev, sw, sh, sat, stripExpected] of CASES) {
    const ih = sh - sat; // what iOS reports (and shows) as the viewport in the Home Screen app
    const { page, context, log } = await newPage(b, { width: sw, height: ih, geo: { latitude: 40.7536, longitude: -73.9832, accuracy: 10 } });
    await context.addInitScript(([w, h]) => {
      Object.defineProperty(navigator, 'standalone', { get: () => true });
      Object.defineProperty(screen, 'width', { get: () => w }); Object.defineProperty(screen, 'height', { get: () => h });
    }, [sw, sh]);
    await openApp(page, 1500);
    await page.evaluate((t) => document.documentElement.style.setProperty('--sat', t + 'px'), sat);
    if (!stripExpected) await page.evaluate(() => document.documentElement.style.setProperty('--sab', '0px'));
    await page.waitForTimeout(500);
    const m = await measure(page);
    const slug = dev.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase();
    await shot(page, `ios-standalone-${slug}.png`);
    check(dev, `system strip ${stripExpected ? 'detected (' + sat + 'pt)' : 'not detected'}`, m.strip === stripExpected && m.stripPt === String(stripExpected ? sat : 0), { strip: m.strip, stripPt: m.stripPt, ih: m.innerHeight });
    check(dev, 'map + canvas fill the whole drawable viewport (0..innerHeight); no page scroll', m.map.top === 0 && m.map.bottom === ih && m.shell.bottom === ih && Math.abs(m.canvasH - ih) <= 1 && m.scrollH <= ih, { map: m.map, shell: m.shell, canvasH: m.canvasH, scrollH: m.scrollH });
    if (stripExpected) {
      check(dev, 'no second home-indicator inset reserved (--sab 0 — indicator is inside the system strip)', m.sab === '0px', m.sab);
      check(dev, 'map fades into exactly the strip colour (--bg) at the viewport edge', m.footer.bottom === ih && /linear-gradient/.test(m.footerBg) && /rgb\(8, 17, 20\)|#081114/i.test(m.footerBg + m.bg), { footer: m.footer, bg: m.footerBg });
      check(dev, 'zoom, GPS and Urban Data inside the drawable viewport and above the fade', [m.zoom, m.gps, m.urban].every((r) => r && r.bottom <= ih - 30), { zoom: m.zoom, gps: m.gps, urban: m.urban });
      check(dev, 'diagnostics report the strip size and the viewport edge', m.diag.includes(`iOS system strip detected: ${sat}pt`) && m.diag.includes(`red line = bottom of the page's viewport (${ih}pt)`), m.diag.split('\n').slice(-4));
    }
    check(dev, 'compact header = inset + 48; card starts 8px below it', m.header.h === sat + 48 && m.card.top === sat + 48 + 8, { header: m.header, card: m.card });
    // Diagnostics overlay draws the red edge exactly at the viewport bottom
    await page.evaluate(() => window.strollaneToggleLayoutDebug ? window.strollaneToggleLayoutDebug(true) : null);
    const edge = await page.evaluate(() => { const e = document.getElementById('layoutDebugEdge'); return e ? Math.round(e.getBoundingClientRect().bottom) : null; });
    if (edge !== null) check(dev, 'diagnostics red line sits on the viewport bottom', edge === ih, edge);
    await page.evaluate(() => { document.getElementById('layoutDebug')?.remove(); document.getElementById('layoutDebugEdge')?.remove(); });
    // Results: full sheet inside the drawable viewport
    await page.click('#intentText'); await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center.'); await page.click('#mCreate');
    await page.waitForFunction(() => document.body.dataset.mview === 'results', null, { timeout: 90000 }).catch(() => {});
    await page.evaluate(() => $('rightPanel').querySelector('.sheet-toggle').click()); await page.waitForTimeout(600);
    const sheet = await page.evaluate(() => ({ bottom: Math.round($('rightPanel').getBoundingClientRect().bottom), top: Math.round($('rightPanel').getBoundingClientRect().top), header: Math.round(document.querySelector('.topbar').getBoundingClientRect().bottom), routes: state.routes.length }));
    check(dev, 'Create My Walk → results; full sheet ends at the viewport bottom, top below the header', sheet.routes > 0 && sheet.bottom === ih && sheet.top >= sheet.header, sheet);
    await shot(page, `ios-standalone-${slug}-results.png`);
    // Navigation bar inside the drawable viewport
    await page.evaluate(() => $('rightPanel').querySelector('.sheet-toggle').click()); await page.waitForTimeout(400);
    await page.locator('#navStart').scrollIntoViewIfNeeded(); await page.click('#navStart'); await page.waitForTimeout(1500);
    if (await page.locator('#navChoice:not(.hidden)').count()) { await page.locator('#navChoice button').first().click(); await page.waitForTimeout(800); }
    const nav = await page.evaluate(() => ({ navMode: document.body.classList.contains('nav-mode'), card: Math.round(document.querySelector('.nav-top').getBoundingClientRect().top), bar: Math.round(document.querySelector('.nav-bottom').getBoundingClientRect().bottom), map: Math.round(document.getElementById('map').getBoundingClientRect().bottom) }));
    check(dev, 'navigation: card below the status bar, bottom bar inside the viewport, map full height', nav.navMode && nav.card >= sat + 8 && nav.bar <= ih - 8 && nav.map === ih, nav);
    await shot(page, `ios-standalone-${slug}-nav.png`);
    // Rotation: landscape screen; strip re-evaluated and map re-measured
    if (dev.startsWith('iPhone 16/17 Pro Max')) {
      await page.setViewportSize({ width: sh, height: sw }); await page.waitForTimeout(900);
      const land = await page.evaluate(() => ({ strip: document.documentElement.dataset.iosStrip, map: Math.round(document.getElementById('map').getBoundingClientRect().height), mapBottom: Math.round(document.getElementById('map').getBoundingClientRect().bottom), canvas: document.querySelector('#map canvas').clientHeight, ih: innerHeight, ox: document.documentElement.scrollWidth - innerWidth }));
      check(dev, 'landscape: strip re-evaluated (none at full height), map reaches the viewport bottom, canvas matches map, no overflow', land.strip === '0' && Math.abs(land.map - land.canvas) <= 1 && land.mapBottom === land.ih && land.ox <= 0, land);
    }
    check(dev, 'no page errors', log.errors.length === 0, log.errors);
    await context.close();
  }
  // Regression found on the live site: viewport grows AFTER load (rotation / Safari toolbars / Home Screen
  // viewport settling) — hidden sheets must stay fully below the screen, never peek in as a dark band.
  {
    const { page, context } = await newPage(b, { width: 440, height: 600 });
    await openApp(page, 1500);
    for (const [w, h] of [[440, 956], [440, 700], [956, 440], [440, 956]]) {
      await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(700);
      const r = await page.evaluate(() => ({ ih: innerHeight, mview: document.body.dataset.mview, tops: ['leftPanel', 'rightPanel', 'exploreSheet'].map((id) => { const e = document.getElementById(id); return { id, level: e.dataset.level, top: Math.round(e.getBoundingClientRect().top) }; }) }));
      if (w <= 740) check(`resize → ${w}x${h}`, 'hidden sheets stay completely off-screen', r.tops.every((t) => t.level !== 'hidden' || t.top >= r.ih), r);
    }
    await context.close();
  }
  // Safari tab / non-iOS: nothing detected, map ends at the viewport bottom, real home-indicator inset kept
  const { page, context } = await newPage(b, { width: 440, height: 830 });
  await openApp(page, 1200);
  await page.evaluate(() => document.documentElement.style.setProperty('--sab', '34px')); await page.waitForTimeout(300);
  const v = await page.evaluate(() => ({ strip: document.documentElement.classList.contains('ios-system-strip'), sab: getComputedStyle(document.documentElement).getPropertyValue('--sab').trim(), map: Math.round(document.getElementById('map').getBoundingClientRect().bottom), ih: innerHeight }));
  check('Safari tab / Android / desktop', 'no strip class, --sab honoured, map ends at the viewport bottom', !v.strip && v.sab === '34px' && v.map === v.ih, v);
  await context.close(); await b.close();
  console.log(`\n${total - failed}/${total} checks passed (simulated iOS Home Screen viewport; not a real-device test)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
