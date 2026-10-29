'use strict';
// iPhone full-screen app-shell check (Safari tab + Home Screen app) across iPhone sizes.
// SIMULATED: Chromium cannot emulate env(safe-area-inset-*), so each device's insets are injected through the
// --sat/--sab custom properties that styles.css derives from env(); viewport sizes are the devices' CSS sizes.
// Everything else (page, map, server.py routing) is real. This is NOT a real-device test.
// Run: python3 server.py &  then  node tests/mobile-v2/iphone-shell.js   (SANDBOX_CDN=1 in a restricted sandbox)
const { launch, newPage, openApp, shot } = require('./harness');
const fs = require('fs');
const path = require('path');

// [label, width, height, status-bar inset (Home Screen app), home-indicator inset]
const DEVICES = [
  ['iPhone SE (2nd/3rd)', 375, 667, 20, 0],
  ['iPhone 12/13 mini', 375, 812, 50, 34],
  ['iPhone 13/14', 390, 844, 47, 34],
  ['iPhone 14 Pro / 15 / 16', 393, 852, 59, 34],
  ['iPhone 16 Pro / 17 / 17 Pro', 402, 874, 62, 34],
  ['iPhone 14 Plus', 428, 926, 47, 34],
  ['iPhone 15/16 Plus, 14/15 Pro Max', 430, 932, 59, 34],
  ['iPhone 16/17 Pro Max', 440, 956, 62, 34],
  ['Safari tab (no insets) 17 Pro Max', 440, 830, 0, 0],
];
const results = []; let failed = 0;
const check = (dev, name, ok, detail) => { results.push({ dev, name, ok: Boolean(ok), detail }); if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} [${dev}] ${name}${ok ? '' : ' — ' + JSON.stringify(detail)}`); };
const setInsets = (page, sat, sab) => page.evaluate(([t, b]) => { const s = document.documentElement.style; s.setProperty('--sat', t + 'px'); s.setProperty('--sab', b + 'px'); }, [sat, sab]);
const geom = (page) => page.evaluate(() => {
  const R = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width, h: r.height, vis: !!el.offsetParent && getComputedStyle(el).visibility !== 'hidden' }; };
  const q = (s) => document.querySelector(s);
  const canvas = q('#map canvas');
  return { w: innerWidth, h: innerHeight, overflowX: document.documentElement.scrollWidth - innerWidth,
    scaled: ['html', 'body', '.site-shell', '.app-layout'].some((s) => { const t = getComputedStyle(q(s)).transform; return t && t !== 'none'; }),
    shell: R(q('.site-shell')), map: R(q('#map')), canvas: canvas ? { w: canvas.clientWidth, h: canvas.clientHeight } : null,
    topbar: R(q('.topbar')), brand: R(q('.brand-name')), menu: R(q('#mobileMore summary')), composer: R(q('#mComposer')), footer: R(q('.map-footer')),
    footerText: R(q('.map-footer span')), zoom: R(q('.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group')),
    controls: ['#mapLocate', '#mUrbanBtn', '#mapReset', '#toggleLegend'].map((s) => ({ s, ...R(q(s)) })), legend: R(q('#udLegend')) };
});
const overlap = (a, b) => a && b && a.vis !== false && b.vis !== false && !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);

(async () => {
  const browser = await launch();
  for (const [dev, w, h, sat, sab] of DEVICES) {
    const { page, context, log } = await newPage(browser, { width: w, height: h, geo: { latitude: 40.7536, longitude: -73.9832, accuracy: 10 } });
    await openApp(page, 1500);
    await setInsets(page, sat, sab); await page.waitForTimeout(500);
    const g = await geom(page);
    const slug = dev.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase();
    await shot(page, `iphone-${slug}-home.png`);
    check(dev, 'map is the full-screen base layer (0..width, 0..height) and its canvas matches', g.map.top === 0 && Math.round(g.map.bottom) === h && g.map.left === 0 && Math.round(g.map.right) === w && g.canvas && Math.abs(g.canvas.h - h) <= 1 && Math.abs(g.canvas.w - w) <= 1, { map: g.map, canvas: g.canvas });
    check(dev, 'no horizontal overflow, no scaled shell', g.overflowX <= 0 && !g.scaled, { overflowX: g.overflowX, scaled: g.scaled });
    check(dev, 'compact header = status-bar inset + 48px; brand and menu fully below the status bar', Math.round(g.topbar.h) === 48 + sat && g.brand.top >= sat && g.brand.bottom <= g.topbar.bottom && g.menu.top >= sat && g.menu.bottom <= g.topbar.bottom, { topbar: g.topbar, brand: g.brand, menu: g.menu });
    check(dev, 'request card below the header (≥8px gap), fully on screen, map keeps most of the screen', g.composer.top >= g.topbar.bottom + 8 && g.composer.bottom <= h && (h - g.composer.bottom) / h >= 0.5, { composer: g.composer, mapShareBelowCard: +((h - g.composer.bottom) / h).toFixed(2) });
    check(dev, 'footer sits on the bottom edge; its text clears the home indicator', Math.round(g.footer.bottom) === h && g.footerText.bottom <= h - sab + 1, { footer: g.footer, text: g.footerText });
    const shown = g.controls.filter((c) => c.vis), hidden = g.controls.filter((c) => !c.vis).map((c) => c.s);
    check(dev, 'right edge shows GPS + Urban Data only (Reset view / Legend moved to the menu)', shown.map((c) => c.s).join() === '#mapLocate,#mUrbanBtn' && hidden.includes('#mapReset') && hidden.includes('#toggleLegend'), { shown: shown.map((c) => c.s) });
    check(dev, 'map controls ≥44px and clear of card, zoom, footer, legend and home indicator', shown.every((c) => c.w >= 44 && c.h >= 44 && !overlap(c, g.composer) && !overlap(c, g.zoom) && !overlap(c, g.footer) && !overlap(c, g.legend) && c.bottom <= h - sab), { controls: shown, zoom: g.zoom });
    check(dev, 'zoom control clears footer and home indicator', g.zoom && g.zoom.bottom <= g.footer.top + 1 && g.zoom.bottom <= h - sab, g.zoom);
    const menu = await page.evaluate(() => [...document.querySelectorAll('#mobileMore [data-more-proxy]')].map((b) => b.dataset.moreProxy));
    check(dev, 'Reset view and Legend reachable from the ☰ menu', menu.includes('mapReset') && menu.includes('toggleLegend'), menu);

    if (dev.startsWith('iPhone 16/17 Pro Max') || dev.startsWith('iPhone SE')) {
      // Keyboard open / close (approximated by shrinking the viewport as iOS does) — map must re-measure, no band left.
      await page.click('#intentText');
      await page.setViewportSize({ width: w, height: h - 336 }); await page.waitForTimeout(700);
      const k = await geom(page);
      check(dev, 'keyboard open: request card and Create button still visible', k.composer.top >= 0 && k.composer.bottom <= h - 336 && (await page.locator('#mCreate').isVisible()), { composer: k.composer, vh: k.h });
      await page.locator('#intentText').blur();
      await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(700);
      const k2 = await geom(page);
      check(dev, 'keyboard closed: map and canvas back to full height (no unpainted band)', Math.round(k2.map.bottom) === h && Math.abs(k2.canvas.h - h) <= 1, { map: k2.map, canvas: k2.canvas });
      // Rotation and back
      await page.setViewportSize({ width: h, height: w }); await page.waitForTimeout(900);
      const land = await page.evaluate(() => ({ overflowX: document.documentElement.scrollWidth - innerWidth, map: Math.round(document.getElementById('map').getBoundingClientRect().height), canvas: document.querySelector('#map canvas').clientHeight }));
      await shot(page, `iphone-${slug}-landscape.png`);
      check(dev, 'landscape: no horizontal overflow, map canvas matches its container', land.overflowX <= 0 && Math.abs(land.map - land.canvas) <= 1, land);
      await page.setViewportSize({ width: w, height: h }); await page.waitForTimeout(900);
      const back = await geom(page);
      check(dev, 'rotated back to portrait: full-screen map + home view restored', Math.round(back.map.bottom) === h && Math.abs(back.canvas.h - h) <= 1 && (await page.evaluate(() => document.body.dataset.mview)) === 'home', { map: back.map, canvas: back.canvas });
      // Returning from the background
      await page.evaluate(() => { window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })); document.dispatchEvent(new Event('visibilitychange')); });
      await page.waitForTimeout(300);
      check(dev, 'foreground again (pageshow / visibilitychange): layout intact', Math.round((await geom(page)).map.bottom) === h);
    }

    // Functional: Create My Walk -> results -> full sheet -> navigation, all clear of the system areas
    await page.click('#intentText'); await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center.'); await page.click('#mCreate');
    await page.waitForFunction(() => document.body.dataset.mview === 'results', null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(500);
    check(dev, 'Create My Walk -> real route results', (await page.evaluate(() => state.routes.length)) > 0);
    await shot(page, `iphone-${slug}-results.png`);
    await page.evaluate(() => $('rightPanel').querySelector('.sheet-toggle').click()); await page.waitForTimeout(500);
    const full = await page.evaluate(() => ({ top: $('rightPanel').getBoundingClientRect().top, hdr: document.querySelector('.topbar').getBoundingClientRect().bottom, level: $('rightPanel').dataset.level }));
    check(dev, 'full results sheet stays below the header', full.level === 'full' && full.top >= full.hdr - 1, full);
    await page.evaluate(() => $('rightPanel').querySelector('.sheet-toggle').click()); await page.waitForTimeout(400);
    await page.locator('#navStart').scrollIntoViewIfNeeded(); await page.click('#navStart'); await page.waitForTimeout(1500);
    if (await page.locator('#navChoice:not(.hidden)').count()) { await page.locator('#navChoice button').first().click(); await page.waitForTimeout(800); }
    // The walking camera tilts to 55° on the first GPS fix: send two simulated fixes on the route.
    const c0 = await page.evaluate(() => nav.route.geometry.coordinates.slice(0, 3));
    for (const c of c0) { await context.setGeolocation({ latitude: c[1], longitude: c[0], accuracy: 8 }); await page.waitForTimeout(1500); }
    const nav = await page.evaluate(() => { const R = (s) => document.querySelector(s).getBoundingClientRect(); return { navMode: document.body.classList.contains('nav-mode'), card: R('.nav-top').top, bar: R('.nav-bottom').bottom, map: R('#map').bottom, pitch: Math.round(state.map.getPitch()) }; });
    check(dev, 'navigation: card clears status bar / Dynamic Island, controls clear home indicator, map full-screen, 3D pitch kept', nav.navMode && nav.card >= sat + 8 && nav.bar <= h - sab - 8 && Math.round(nav.map) === h && nav.pitch >= 45, nav);
    await shot(page, `iphone-${slug}-nav.png`);
    check(dev, 'no uncaught page errors', log.errors.length === 0, log.errors.slice(0, 3));
    await context.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(require('./harness').SHOTS, 'iphone-shell-results.json'), JSON.stringify(results, null, 1));
  console.log(`\n${results.length - failed}/${results.length} checks passed (simulated safe areas; not a real-device test)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
