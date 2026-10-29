'use strict';
// Reproduces the viewport measured on a real iPhone 17 Pro Max Home Screen app (black-translucent status bar):
// screen 440x956pt, but WebKit reports innerHeight = 894 (956 - 62 status bar) while drawing from the screen top.
// SIMULATED in Chromium: navigator.standalone=true and screen.width/height are injected before the page loads,
// the viewport is 440x894, the safe-area insets (62/34) are injected through --sat/--sab. Not a real-device test.
// Pass criterion: the shell, the map, its canvas, the footer and a full sheet all end at 956 (the physical
// screen bottom), i.e. no gap below the map. Also checks the compact header and request card.
const { launch, newPage, openApp, shot } = require('./harness');
const CASES = [
  // [label, screen w, screen h, status-bar inset, home-indicator inset]
  ['iPhone 16/17 Pro Max', 440, 956, 62, 34],
  ['iPhone 14 Pro / 15 / 16', 393, 852, 59, 34],
  ['iPhone 13/14', 390, 844, 47, 34],
  ['iPhone SE', 375, 667, 20, 0],
];
let failed = 0, total = 0;
const check = (dev, name, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} [${dev}] ${name}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
(async () => {
  const b = await launch();
  for (const [dev, sw, sh, sat, sab] of CASES) {
    const reportedH = sh - sat; // what iOS reports as the viewport height in the Home Screen app
    const { page, context, log } = await newPage(b, { width: sw, height: reportedH });
    await context.addInitScript(([w, h]) => {
      Object.defineProperty(navigator, 'standalone', { get: () => true });
      Object.defineProperty(screen, 'width', { get: () => w }); Object.defineProperty(screen, 'height', { get: () => h });
    }, [sw, sh]);
    await openApp(page, 1500);
    await page.evaluate(([t, bo]) => { const s = document.documentElement.style; s.setProperty('--sat', t + 'px'); s.setProperty('--sab', bo + 'px'); }, [sat, sab]);
    await page.waitForTimeout(500);
    const m = await page.evaluate(() => {
      const B = (sel) => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().bottom) : null; };
      const T = (sel) => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().top) : null; };
      const c = document.querySelector('#map canvas');
      return { innerHeight, vgap: getComputedStyle(document.documentElement).getPropertyValue('--vgap').trim(), shell: B('.site-shell'), map: B('#map'), canvasH: c && c.clientHeight, footer: B('.map-footer'),
        header: B('.topbar'), card: [T('#mComposer'), B('#mComposer')], diag: window.strollaneLayoutReport ? window.strollaneLayoutReport().split('\n').pop() : null };
    });
    check(dev, `measured gap = status bar (${sat}pt) → --vgap`, m.innerHeight === reportedH && m.vgap === `${sat}px`, m);
    check(dev, 'shell, map, canvas and footer reach the physical screen bottom (no gap)', m.shell === sh && m.map === sh && Math.abs(m.canvasH - sh) <= 1 && m.footer === sh, m);
    check(dev, 'diagnostics report: 0pt gap below the map', /GAP below map vs screen: 0pt/.test(m.diag || ''), m.diag);
    check(dev, 'compact header = inset + 48; card starts 8px below it', m.header === sat + 48 && m.card[0] === sat + 48 + 8, m);
    // A full results sheet must also reach the screen bottom
    await page.click('#intentText'); await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center.'); await page.click('#mCreate');
    await page.waitForFunction(() => document.body.dataset.mview === 'results', null, { timeout: 90000 }).catch(() => {});
    await page.evaluate(() => $('rightPanel').querySelector('.sheet-toggle').click()); await page.waitForTimeout(600);
    const sheet = await page.evaluate(() => ({ bottom: Math.round($('rightPanel').getBoundingClientRect().bottom), top: Math.round($('rightPanel').getBoundingClientRect().top), header: Math.round(document.querySelector('.topbar').getBoundingClientRect().bottom) }));
    check(dev, 'full results sheet: bottom at the screen bottom, top below the header', sheet.bottom === sh && sheet.top >= sheet.header, sheet);
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
  // Safari tab / non-iOS: no gap must be applied
  const { page, context } = await newPage(b, { width: 440, height: 830 });
  await openApp(page, 1200);
  const v = await page.evaluate(() => ({ vgap: getComputedStyle(document.documentElement).getPropertyValue('--vgap').trim(), map: Math.round(document.getElementById('map').getBoundingClientRect().bottom), ih: innerHeight }));
  check('Safari tab / Android / desktop', 'no compensation applied (--vgap 0), map ends at the viewport bottom', v.vgap === '0px' && v.map === v.ih, v);
  await context.close(); await b.close();
  console.log(`\n${total - failed}/${total} checks passed (simulated iOS Home Screen viewport; not a real-device test)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
