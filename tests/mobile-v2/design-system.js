'use strict';
// Editorial design system (round 9): brand lockup, map theme, start/end marks, swap, icon set, route styling.
// Real page + real routing (server.py); MapLibre runs on the sandbox basemap when SANDBOX_CDN=1, so CARTO's own
// layers are absent here — the basemap colours are verified on the live site, not in this test.
const { launch, newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0;
const check = (name, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
(async () => {
  const b = await launch();
  for (const [label, w, h] of [['phone', 375, 667], ['phone', 440, 956], ['desktop', 1440, 900]]) {
    const { page, log } = await newPage(b, { width: w, height: h });
    await openApp(page, 1500);
    const brand = await page.evaluate(() => { const n = document.querySelector('.brand-name'), m = document.querySelector('.brand-mark');
      const r = n.getBoundingClientRect(), mr = m.getBoundingClientRect(), menu = document.querySelector('#mobileMore summary')?.getBoundingClientRect();
      return { text: n.textContent.replace(/\s+/g, ''), clipped: n.scrollWidth > n.clientWidth + 1, centreDelta: Math.abs((r.top + r.bottom) / 2 - (mr.top + mr.bottom) / 2),
        markColor: getComputedStyle(m).color, overlapMenu: menu && menu.width ? !(r.right <= menu.left || r.left >= menu.right) : false,
        oldParts: document.querySelectorAll('.brand-location:not([hidden]), .top-center').length && [...document.querySelectorAll('.brand-location,.top-center')].some((e) => e.offsetParent) };
    });
    check(`[${label} ${w}] brand reads "STROLLANE·NYC", one line, not truncated, mark centred on the text`, brand.text === 'STROLLANE·NYC' && !brand.clipped && brand.centreDelta <= 2, brand);
    check(`[${label} ${w}] white mark (no lime), no duplicate "MANHATTAN · NYC" / tagline, menu never covers the name`, /245, 245, 242/.test(brand.markColor) && !brand.oldParts && !brand.overlapMenu, brand);
    const icons = await page.evaluate(() => ({ emoji: /[\u{1F300}-\u{1FAFF}]/u.test(document.body.innerText), mic: [...document.querySelectorAll('.mic-btn')].every((x) => x.querySelector('svg')),
      tools: ['#mapLocate', '#mUrbanBtn'].every((s) => document.querySelector(s)?.querySelector('svg')), glow: getComputedStyle(document.querySelector('.m-create')).boxShadow }));
    check(`[${label} ${w}] no emoji in the UI; microphone and map tools are line icons; no glow on the primary action`, !icons.emoji && icons.mic && icons.tools && icons.glow === 'none', icons);
    if (label === 'phone') {
      const ends = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent, card: $('mComposer').getBoundingClientRect().bottom, H: innerHeight }));
      check(`[${w}] home shows From and To as two rows; map keeps ≥ 40 % of the screen`, ends.from === 'Bryant Park' && ends.to === 'Rockefeller Center' && (ends.H - ends.card) / ends.H >= 0.4, ends);
      await page.click('.m-swap'); await page.waitForTimeout(300);
      const sw = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent, start: getPlace('start')?.name, end: getPlace('end')?.name }));
      check(`[${w}] swap exchanges start and destination (state + UI)`, sw.from === 'Rockefeller Center' && sw.to === 'Bryant Park' && sw.start === 'Rockefeller Center' && sw.end === 'Bryant Park', sw);
      await page.click('.m-swap'); await page.waitForTimeout(200);
      // Map theme from the ☰ menu
      await page.click('#mobileMore summary'); await page.click('[data-map-theme="light"]'); await page.waitForTimeout(400);
      const lt = await page.evaluate(() => ({ theme: document.documentElement.dataset.mapTheme, saved: localStorage.getItem('strollane.mapTheme'), route: state.map.getPaintProperty('route-selected', 'line-color'),
        casing: state.map.getPaintProperty('route-shadow', 'line-color'), pressed: document.querySelector('[data-map-theme="light"]').getAttribute('aria-pressed') }));
      check(`[${w}] Light map: theme saved, route inverts to ink on a white casing, control shows the state`, lt.theme === 'light' && lt.saved === 'light' && lt.route === '#141413' && lt.casing === '#FFFFFF' && lt.pressed === 'true', lt);
      await page.click('[data-map-theme="dark"]'); await page.click('#mobileMore summary'); await page.waitForTimeout(300);
    }
    // Route styling + marks after a real plan
    await page.evaluate(() => (typeof generateRoutes === 'function' ? generateRoutes() : null)); await page.waitForFunction(() => state.routes.length > 0, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(800);
    const rs = await page.evaluate(() => { const m = state.map, g = (id, p) => m.getPaintProperty(id, p);
      return { routes: state.routes.length, line: g('route-selected', 'line-color'), casing: g('route-shadow', 'line-color'), glow: g('route-glow', 'line-opacity'), arrows: !!m.getLayer('route-arrows') && m.hasImage('route-arrow-dark'),
        start: [g('point-starts', 'circle-color'), g('point-starts', 'circle-stroke-color')], end: [g('point-ends', 'circle-color'), !!m.getLayer('point-ends-core')], alt: g('route-alts', 'line-dasharray') };
    });
    check(`[${label} ${w}] selected route: warm white on a dark casing, no glow, direction chevrons; alternatives dashed grey`, rs.routes > 0 && rs.line === '#F3EFE4' && rs.casing === '#0B0B0B' && rs.glow === 0 && rs.arrows && Array.isArray(rs.alt), rs);
    check(`[${label} ${w}] start = hollow ring, destination = solid bullseye (shape, not only colour)`, rs.start[0] === '#0B0B0B' && rs.start[1] === '#F5F5F2' && rs.end[0] === '#F3EFE4' && rs.end[1], rs);
    await shot(page, `design-${label}-${w}.png`);
    check(`[${label} ${w}] no page errors`, log.errors.length === 0, log.errors.slice(0, 3));
    await page.context().close();
  }
  // PWA icons: black tile + white walker, maskable variant listed
  const { page } = await newPage(b, { width: 400, height: 400 });
  const man = await page.request.get(require('./harness').BASE + '/site.webmanifest').then((r) => r.json());
  const icon = await page.request.get(require('./harness').BASE + '/icon-512.png');
  check('manifest: theme #0B0B0B, maskable icon listed, icons served', man.theme_color === '#0B0B0B' && man.icons.some((i) => i.purpose === 'maskable') && icon.ok(), { theme: man.theme_color, icons: man.icons.length });
  await b.close();
  console.log(`\n${total - failed}/${total} checks passed (design system; basemap colours verified on the live site)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
