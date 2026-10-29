'use strict';
// AR walking view + 3D route preview.
// SIMULATED: Chromium's fake camera (--use-fake-device-for-media-stream) stands in for the rear camera; compass and
// tilt are synthetic deviceorientation events (webkitCompassHeading / beta, as iOS sends them); GPS fixes come from
// Playwright geolocation. The route, its maneuvers and the navigation engine are real (server.py).
// What this cannot test: real magnetometer error, real camera FOV, or iOS permission prompts — REAL DEVICE CHECK REQUIRED.
// Run: python3 server.py &  then  node tests/mobile-v2/ar-preview.js   (SANDBOX_CDN=1 in a restricted sandbox)
const { chromium } = require('playwright');
const { newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0;
const check = (name, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
const orient = (page, heading, beta = 88) => page.evaluate(([h, b]) => {
  const e = new Event('deviceorientation'); Object.assign(e, { alpha: (360 - h) % 360, beta: b, gamma: 0, absolute: false, webkitCompassHeading: h, webkitCompassAccuracy: 12 });
  for (let i = 0; i < 40; i++) window.dispatchEvent(e); // the overlay low-pass filters the compass; settle it
  window.strollaneAr?.render(); // draw now instead of waiting for the next animation frame (flaky under load)
}, [heading, beta]);
// Raise to View needs the tilt to be HELD: one event to enter the state, a second after the hold time.
const tilt = async (page, beta) => {
  const send = () => page.evaluate((b) => { const e = new Event('deviceorientation'); Object.assign(e, { alpha: 0, beta: b, gamma: 0, absolute: false }); window.dispatchEvent(e); }, beta);
  await send(); await page.waitForTimeout(750); await send(); await page.waitForTimeout(700);
};

(async () => {
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const { page, context, log } = await newPage(browser, { width: 440, height: 956, geo: { latitude: 40.7536, longitude: -73.9832, accuracy: 8 } });
  await context.grantPermissions(['geolocation', 'camera', 'accelerometer', 'gyroscope', 'magnetometer']);
  await openApp(page, 1500);
  await page.evaluate(() => { const s = document.documentElement.style; s.setProperty('--sat', '62px'); s.setProperty('--sab', '34px'); });
  await page.click('#intentText'); await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center.'); await page.click('#mCreate');
  await page.waitForFunction(() => document.body.dataset.mview === 'results', null, { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(600);
  check('route planned (real engine)', await page.evaluate(() => state.routes.length > 0));

  /* ---------- 3D preview ---------- */
  check('"Preview walk in 3D" offered for the selected route', await page.locator('#routePreviewBtn').isVisible());
  const cam0 = await page.evaluate(() => ({ pitch: Math.round(state.map.getPitch()), zoom: +state.map.getZoom().toFixed(2) }));
  await page.locator('#routePreviewBtn').scrollIntoViewIfNeeded(); await page.click('#routePreviewBtn'); await page.waitForTimeout(800);
  const p1 = await page.evaluate(() => ({ mode: document.body.classList.contains('preview-mode'), pitch: Math.round(state.map.getPitch()), s: strollanePreview.state.s,
    playing: strollanePreview.state.playing, instr: document.getElementById('rpInstr').textContent, walker: state.map.getSource('preview-walker')?._data?.features?.length,
    hidden: ['.m-composer', '.right-panel', '.topbar'].every((q) => getComputedStyle(document.querySelector(q)).display === 'none') }));
  check('preview opens full-screen: first-person pitch, walker marker, UI chrome hidden, playing', p1.mode && p1.pitch >= 65 && p1.walker === 1 && p1.hidden && p1.playing, p1);
  check('preview shows the next instruction from the real maneuvers', p1.instr.length > 3 && p1.instr !== 'Preview of your walk', p1.instr);
  await shot(page, 'preview-phone.png');
  await page.waitForTimeout(1500);
  const p2 = await page.evaluate(() => ({ s: strollanePreview.state.s, len: strollanePreview.state.eng.netLen, bearing: state.map.getBearing() }));
  check('playback advances along the route', p2.s > p1.s + 5, { before: p1.s, after: p2.s });
  await page.click('#rpSpeed');
  check('speed cycles 1× → 2×', (await page.textContent('#rpSpeed')) === '2×');
  await page.evaluate(() => { const r = document.getElementById('rpScrub'); r.value = '500'; r.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.waitForTimeout(200);
  const p3 = await page.evaluate(() => ({ s: strollanePreview.state.s, len: strollanePreview.state.eng.netLen, playing: strollanePreview.state.playing }));
  check('scrubbing jumps to that point and pauses', Math.abs(p3.s - p3.len / 2) < p3.len * 0.01 && !p3.playing, p3);
  await shot(page, 'preview-phone-mid.png');
  await page.click('#rpClose'); await page.waitForTimeout(900);
  const p4 = await page.evaluate(() => ({ mode: document.body.classList.contains('preview-mode'), pitch: Math.round(state.map.getPitch()), view: document.body.dataset.mview,
    sheet: getComputedStyle(document.querySelector('.right-panel')).display }));
  check('closing restores the previous camera and the results view', !p4.mode && Math.abs(p4.pitch - cam0.pitch) <= 2 && p4.view === 'results' && p4.sheet !== 'none', { p4, cam0 });

  /* ---------- AR view during navigation ---------- */
  await page.locator('#navStart').scrollIntoViewIfNeeded(); await page.click('#navStart'); await page.waitForTimeout(1500);
  if (await page.locator('#navChoice:not(.hidden)').count()) { await page.locator('#navChoice button').first().click(); await page.waitForTimeout(800); }
  const c0 = await page.evaluate(() => nav.route.geometry.coordinates.slice(0, 3));
  for (const c of c0) { await context.setGeolocation({ latitude: c[1], longitude: c[0], accuracy: 8 }); await page.waitForTimeout(1200); }
  check('AR view offered in navigation on a touch phone', await page.locator('#navAr').isVisible());
  check('3D preview button hidden while navigating', !(await page.locator('#routePreviewBtn').isVisible()));
  await page.click('#navAr'); await page.waitForFunction(() => strollaneAr.state.on, null, { timeout: 8000 }).catch(() => {}); await page.waitForTimeout(500);
  const a1 = await page.evaluate(() => { const v = document.getElementById('arVideo'); return { on: strollaneAr.state.on, mode: document.body.classList.contains('ar-mode'),
    tracks: strollaneAr.state.stream?.getVideoTracks().length || 0, live: strollaneAr.state.stream?.getVideoTracks()[0]?.readyState, playing: v && !v.paused && v.readyState >= 2, btn: document.getElementById('navAr').textContent }; });
  check('AR starts the rear camera (fake device) and shows it full-screen', a1.on && a1.mode && a1.tracks === 1 && a1.live === 'live' && a1.playing && a1.btn === 'Map view', a1);
  // Point the phone straight down the route: the floor arrow should point (almost) straight ahead.
  const ahead = await page.evaluate(() => { const o = nav.engine.lastOutput, here = o.matched_coordinate && o.confidence === 'high' ? o.matched_coordinate : o.raw;
    const a = nav.engine.pointAt(Math.min(nav.engine.netLen, (o.progress_m || 0) + Math.min(28, Math.max(8, o.distance_to_next_m ?? 1e9)))); return strollaneAr.bearing(here, a); });
  await orient(page, ahead, 88); await page.waitForTimeout(300);
  const a2 = await page.evaluate(() => ({ ready: document.getElementById('arView').classList.contains('ar-ready'), rot: parseFloat(getComputedStyle(document.getElementById('arFloor')).getPropertyValue('--rot')),
    left: document.getElementById('arEdgeLeft').classList.contains('show'), right: document.getElementById('arEdgeRight').classList.contains('show'),
    hint: document.getElementById('arHint').textContent, quality: document.getElementById('arQuality').textContent }));
  check('facing down the route: arrow straight ahead, no turn indicator, overlay ready', a2.ready && Math.abs(a2.rot) < 6 && !a2.left && !a2.right, a2);
  check('accuracy readout shows GPS and compass error honestly', /GPS ±\d+ m/.test(a2.quality) && /Compass ±12°/.test(a2.quality), a2.quality);
  await shot(page, 'ar-ahead.png');
  // Turn 90° to the right of the route: the arrow swings left and "Turn left" appears.
  await orient(page, (ahead + 90) % 360, 88); await page.waitForTimeout(300);
  const a3 = await page.evaluate(() => ({ rot: parseFloat(getComputedStyle(document.getElementById('arFloor')).getPropertyValue('--rot')), left: document.getElementById('arEdgeLeft').classList.contains('show') }));
  check('facing 90° off: arrow turns ≈ −90° and "Turn left" shows', a3.left && Math.abs(a3.rot + 90) < 8, a3);
  await shot(page, 'ar-turn-left.png');
  // Phone held flat: ask the walker to raise it.
  await orient(page, ahead, 15); await page.waitForTimeout(300);
  check('phone held flat → "Hold the phone upright" hint', /upright/.test(await page.textContent('#arHint')));
  // Projection sanity: a point 20 m straight ahead at eye height 1.5 m sits just below the horizon line.
  const proj = await page.evaluate(() => strollaneAr.project(0, 20, 0, { h: 52, v: 66 }));
  check('ground projection: 20 m ahead lands centred, slightly below the horizon', Math.abs(proj.x - 50) < .01 && proj.y > 50 && proj.y < 58, proj);
  check('heading from Euler angles (Android path) — upright, facing east ≈ 90°', Math.abs(await page.evaluate(() => strollaneAr.headingFromEuler(270, 90, 0)) - 90) < 1);
  // Safety + glance design (Google Live View / Apple Maps): a one-time look-up and battery notice on entry.
  check('first AR entry shows the look-up / battery notice', /watch for traffic/.test(await page.textContent('#arFlash')) && /battery/.test(await page.textContent('#arFlash')));
  // Approaching a turn: arrows brighten and grow, then the instruction shows as "now" (Apple Maps behaviour).
  const near = await page.evaluate(() => { const o = nav.engine.lastOutput, keep = { d: o.distance_to_next_m, nm: o.next_maneuver };
    o.next_maneuver = { ...(keep.nm || {}), type: 'turn_left', instruction_text: 'Turn left onto W 42nd St', coordinate: keep.nm?.coordinate || nav.engine.pointAt(20) };
    o.distance_to_next_m = 25; strollaneAr.render(); const r1 = { near: document.getElementById('arView').classList.contains('ar-near'), now: document.getElementById('arNow').classList.contains('show') };
    o.distance_to_next_m = 8; strollaneAr.render(); const r2 = { near: document.getElementById('arView').classList.contains('ar-near'), now: document.getElementById('arNow').textContent };
    o.distance_to_next_m = keep.d; o.next_maneuver = keep.nm; strollaneAr.render(); return { r1, r2 }; });
  check('within 30 m of a turn the arrows switch to their "near" state', near.r1.near && !near.r1.now, near.r1);
  check('within 10 m the instruction appears as a "now" banner', near.r2.near && /Turn left onto W 42nd St/.test(near.r2.now), near.r2);
  await shot(page, 'ar-near.png');
  // Raise to View (Apple Maps): lower → back to the map with the camera parked; raise → AR again without a new prompt.
  await tilt(page, 20);
  const r1 = await page.evaluate(() => ({ on: strollaneAr.state.on, stream: strollaneAr.state.stream?.getVideoTracks()[0]?.readyState, mode: document.body.classList.contains('ar-mode') }));
  check('lowering the phone returns to the map; camera parked, not released', !r1.on && r1.stream === 'live' && !r1.mode, r1);
  const sameStream = await page.evaluate(() => { window.__arStream = strollaneAr.state.stream; return true; });
  await tilt(page, 86);
  const r2 = await page.evaluate(() => ({ on: strollaneAr.state.on, same: strollaneAr.state.stream === window.__arStream, mode: document.body.classList.contains('ar-mode') }));
  check('raising the phone again re-opens AR instantly with the same camera stream', sameStream && r2.on && r2.same && r2.mode, r2);
  // Manual Map view while still upright must not bounce back into AR until the phone has been lowered once.
  await page.click('#navAr'); await page.waitForTimeout(200); await tilt(page, 86);
  check('manual Map view is respected while the phone stays upright', await page.evaluate(() => !strollaneAr.state.on));
  await tilt(page, 20); await tilt(page, 86); await page.waitForFunction(() => strollaneAr.state.on, null, { timeout: 8000 }).catch(() => {});
  check('after lowering once, raising opens AR again (fresh camera, no tap)', await page.evaluate(() => strollaneAr.state.on && !!strollaneAr.state.stream));
  // The setting lives in More and is remembered.
  await page.evaluate(() => strollaneAr.setRaise(false)); await tilt(page, 20); await tilt(page, 86);
  const off = await page.evaluate(() => ({ on: strollaneAr.state.on, label: document.getElementById('navArRaise')?.textContent, saved: localStorage.getItem('strollane.ar.raise') }));
  check('Raise to view off: lowering still leaves AR, raising does not re-open it; label + saved', off.label === 'Raise to view: off' && off.saved === '0' && !off.on, off);
  await page.evaluate(() => strollaneAr.setRaise(true));
  // Parked camera is released when the app goes to the background.
  await tilt(page, 86); await page.evaluate(() => strollaneAr.state.on || strollaneAr.start()); await page.waitForTimeout(500); await tilt(page, 20);
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
  check('backgrounding releases a parked camera', await page.evaluate(() => !strollaneAr.state.stream));
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); });
  await page.click('#navAr'); await page.waitForTimeout(900);
  // Back to the map: camera released.
  await page.click('#navAr'); await page.waitForTimeout(300);
  const a4 = await page.evaluate(() => ({ on: strollaneAr.state.on, stream: !!strollaneAr.state.stream, mode: document.body.classList.contains('ar-mode'), hidden: document.getElementById('arView').classList.contains('hidden') }));
  check('Map view: camera stopped and released, AR layer hidden', !a4.on && !a4.stream && !a4.mode && a4.hidden, a4);
  // AR on, then end navigation: the camera must not keep running.
  await page.click('#navAr'); await page.waitForTimeout(800);
  await page.click('#navExit'); await page.waitForTimeout(500);
  const a5 = await page.evaluate(() => ({ on: strollaneAr.state.on, stream: !!strollaneAr.state.stream, nav: !!nav.engine }));
  check('ending navigation also stops the camera', !a5.on && !a5.stream && !a5.nav, a5);
  check('no page errors (phone)', log.errors.length === 0, log.errors.slice(0, 3));
  await context.close();

  /* ---------- desktop ---------- */
  const d = await newPage(browser, { width: 1440, height: 900 });
  await openApp(d.page, 1500);
  await d.page.evaluate(() => generateRoutes()); await d.page.waitForFunction(() => state.routes.length > 0, null, { timeout: 90000 }).catch(() => {});
  await d.page.waitForTimeout(500);
  check('desktop: AR hidden (no touch camera/compass), 3D preview offered', await d.page.evaluate(() => document.getElementById('navAr').classList.contains('hidden')) && await d.page.locator('#routePreviewBtn').isVisible());
  await d.page.click('#routePreviewBtn'); await d.page.waitForTimeout(900);
  const dw = await d.page.evaluate(() => ({ mapW: Math.round(document.getElementById('map').getBoundingClientRect().width), canvasW: document.querySelector('#map canvas').clientWidth, pitch: Math.round(state.map.getPitch()) }));
  check('desktop preview: map takes the full window, first-person pitch', dw.mapW === 1440 && Math.abs(dw.canvasW - 1440) <= 1 && dw.pitch >= 65, dw);
  await shot(d.page, 'preview-desktop.png');
  await d.page.keyboard.press('Escape'); await d.page.waitForTimeout(900);
  check('desktop: Esc closes the preview and the three-column layout returns', await d.page.evaluate(() => !document.body.classList.contains('preview-mode') && getComputedStyle(document.querySelector('.left-panel')).display !== 'none'));
  check('no page errors (desktop)', d.log.errors.length === 0, d.log.errors.slice(0, 3));
  await browser.close();
  console.log(`\n${total - failed}/${total} checks passed (fake camera + synthetic compass; REAL DEVICE CHECK REQUIRED)`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
