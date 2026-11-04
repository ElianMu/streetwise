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
      // translucent request card, but every field / button that holds text is opaque (map labels never show behind text)
      const card = await page.evaluate(() => { const a = (sel) => { const c = getComputedStyle(document.querySelector(sel)).backgroundColor; const m = c.match(/[\d.]+/g).map(Number); return m.length > 3 ? m[3] : 1; };
        const h = getComputedStyle(document.querySelector('.topbar'));
        return { card: a('#mComposer'), field: a('#intentText'), ends: a('#mContext'), swap: a('.m-swap'), mic: a('.m-mic-slot .mic-btn'), header: a('.topbar'), hdrBlur: h.backdropFilter, hdrPos: h.position, brand: [getComputedStyle(document.querySelector('.brand-name')).fontSize, getComputedStyle(document.querySelector('.brand-name')).fontWeight], cardBlur: getComputedStyle(document.querySelector('#mComposer')).backdropFilter }; });
      check(`[${w}] solid FIXED header (iOS samples it for the status bar), 16px/700 wordmark; request card translucent (no blur) with opaque field, From/To, mic and swap`, card.header === 1 && card.hdrBlur === 'none' && card.hdrPos === 'fixed' && card.brand[0] === '16px' && card.brand[1] === '700' && card.card >= 0.65 && card.card <= 0.8 && card.cardBlur === 'none' && [card.field, card.ends, card.swap, card.mic].every((x) => x === 1), card);
      const ends = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent, card: $('mComposer').getBoundingClientRect().bottom, H: innerHeight }));
      check(`[${w}] home shows From and To as two rows (default destination Columbia University, W 116th St); map keeps ≥ 40 % of the screen`, ends.from === 'Bryant Park' && ends.to === 'Columbia University' && (ends.H - ends.card) / ends.H >= 0.4, ends);
      await page.click('.m-swap'); await page.waitForTimeout(300);
      const sw = await page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent, start: getPlace('start')?.name, end: getPlace('end')?.name }));
      check(`[${w}] swap exchanges start and destination (state + UI)`, sw.from === 'Columbia University' && sw.to === 'Bryant Park' && sw.start === 'Columbia University' && sw.end === 'Bryant Park', sw);
      await page.click('.m-swap'); await page.waitForTimeout(200);
      // Map theme from the ☰ menu
      await page.click('#mobileMore summary'); await page.click('button[data-map-theme="light"]'); await page.waitForTimeout(400);
      const lt = await page.evaluate(() => ({ theme: document.documentElement.dataset.mapTheme, saved: localStorage.getItem('strollane.mapTheme'), route: state.map.getPaintProperty('route-selected', 'line-color'),
        casing: state.map.getPaintProperty('route-shadow', 'line-color'), pressed: document.querySelector('button[data-map-theme="light"]').getAttribute('aria-pressed') }));
      check(`[${w}] Light map: theme saved, route inverts to ink on a white casing, control shows the state`, lt.theme === 'light' && lt.saved === 'light' && lt.route === '#141413' && lt.casing === '#FFFFFF' && lt.pressed === 'true', lt);
      // the whole interface follows the light map (the phone header is transparent over the map, null = no fill): white surfaces, dark text; the turn box is white with a black arrow
      const uiProbe = () => { const lum = (c) => { const m = c.match(/[\d.]+/g).map(Number); if (m.length > 3 && m[3] === 0) return null; const k = c.startsWith('color(') ? 1 : 255; return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / k; };
        const bg = (sel) => { const e = document.querySelector(sel); return e ? lum(getComputedStyle(e).backgroundColor) : null; };
        const probe = (cls, tag = 'div') => { const e = document.createElement(tag); e.className = cls; document.querySelector('.map-workspace').appendChild(e); const c = getComputedStyle(e); const v = [lum(c.backgroundColor), lum(c.color), lum(c.borderTopColor)]; e.remove(); return v; };
        const arrow = probe('nav-arrow'), navCard = probe('nav-top'), chip = probe('explore-chip', 'button');
        return { topbar: bg('.topbar'), menu: bg('.mobile-more-body'), field: bg('#intentText'), panel: bg('#leftPanel'), text: lum(getComputedStyle(document.querySelector('#intentText')).color),
          arrow, navCard, chip, meta: document.querySelector('meta[name="theme-color"]').getAttribute('content') }; };
      const lu = await page.evaluate(`(${uiProbe})()`);
      check(`[${w}] Light map: header, menu, panel and text fields are white with dark text; browser / status bar white`, (lu.topbar === null || lu.topbar > 0.95) && lu.menu > 0.95 && lu.field > 0.95 && lu.panel > 0.95 && lu.text < 0.15 && lu.meta === '#FFFFFF', lu);
      check(`[${w}] Light map: navigation card and turn box white, black arrow and text, light-grey border (no green)`, lu.navCard[0] > 0.95 && lu.navCard[1] < 0.1 && lu.arrow[0] > 0.95 && lu.arrow[1] < 0.1 && lu.arrow[2] > 0.7 && lu.arrow[2] < 0.95, lu);
      check(`[${w}] Light map: Experience Dimension chips white with dark text`, lu.chip[0] > 0.95 && lu.chip[1] < 0.35, lu.chip);
      await page.click('button[data-map-theme="dark"]'); await page.click('#mobileMore summary'); await page.waitForTimeout(300);
      const du = await page.evaluate(`(${uiProbe})()`);
      check(`[${w}] Dark map: interface back to dark; navigation card and turn box dark with a white arrow (no lime)`, (du.topbar === null || du.topbar < 0.1) && du.field < 0.15 && du.text > 0.85 && du.meta === '#0B0B0B' && du.navCard[0] < 0.12 && du.arrow[0] < 0.12 && du.arrow[1] > 0.9 && du.chip[1] > 0.6, du);
      // a click anywhere else must not touch the theme (the <html> element also carries data-map-theme)
      await page.evaluate(() => { localStorage.setItem('strollane.mapTheme', 'dark'); window.__applies = 0; const o = window.applyMapTheme; window.applyMapTheme = (...x) => { window.__applies++; return o(...x); }; });
      await page.mouse.click(200, 520); await page.click('.m-context-edit').catch(() => {}); await page.evaluate(() => document.body.click()); await page.waitForTimeout(200);
      const stray = await page.evaluate(() => ({ applies: window.__applies, saved: localStorage.getItem('strollane.mapTheme'), theme: document.documentElement.dataset.mapTheme }));
      check(`[${w}] ordinary clicks never switch or re-apply the map theme`, stray.applies === 0 && stray.saved === 'dark' && stray.theme === 'dark', stray);
      await page.evaluate(() => { if (document.body.dataset.mview !== 'home' && typeof setView === 'function') setView('home'); });
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
  {
    const w = 440;
    const { page } = await newPage(b, { width: 440, height: 956, geo: { latitude: 40.7536, longitude: -73.9832, accuracy: 10 } });
    await openApp(page, 1500);
    await page.evaluate(() => (typeof generateRoutes === 'function' ? generateRoutes() : null)); await page.waitForFunction(() => state.routes.length > 0, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(600);
      // switching the theme in the middle of a walk: the turn card, the bottom panel and the route all follow at once
      await page.evaluate(() => $('navStart')?.click()); await page.waitForTimeout(1200);
      const navTheme = async () => page.evaluate(() => { const lum = (c) => { const m = c.match(/[\d.]+/g).map(Number); const k = c.startsWith('color(') ? 1 : 255; return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / k; };
        const g = (sel, p) => lum(getComputedStyle(document.querySelector(sel))[p]);
        return { on: !document.getElementById('navOverlay').classList.contains('hidden'), top: g('.nav-top', 'backgroundColor'), arrowBg: g('#navArrow', 'backgroundColor'), arrow: g('#navArrow', 'color'), bottom: document.querySelector('.nav-bottom') ? lum(getComputedStyle(document.querySelector('.nav-bottom')).backgroundColor) : null,
          route: state.map.getPaintProperty('route-selected', 'line-color') }; });
      await page.evaluate(() => setMapTheme('light')); await page.waitForTimeout(300);
      const nl = await navTheme();
      await page.evaluate(() => setMapTheme('dark')); await page.waitForTimeout(300);
      const nd = await navTheme();
      check(`[${w}] theme switched during navigation: turn card, arrow, bottom panel and route follow without a reload`, nl.on && nl.top > 0.95 && nl.arrowBg > 0.95 && nl.arrow < 0.1 && nl.bottom > 0.95 && nl.route === '#141413' && nd.top < 0.12 && nd.arrow > 0.9 && nd.bottom < 0.12 && nd.route !== '#141413', { nl, nd });
      await page.evaluate(() => $('navExit')?.click()); await page.waitForTimeout(300);
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
