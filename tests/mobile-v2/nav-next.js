'use strict';
// Navigation, step 3 of the Experience-first plan:
// - the top card names the next listed place ahead ("Next: Madison Square Park · 200 m") from the same place index the
//   route cards use, with its distance along the route, and its photo with author and licence when one exists;
// - the AR button says what it is ("AR · compass") and the 3D button says it is a map ("3D map preview").
// Simulated walking (GPS fixes at walking speed) along a real engine route (local server.py); Wikimedia answers from real recorded responses.
const { launch, newPage, openApp, shot } = require('./harness');
const { wikimedia } = require('./wikimedia-fixture');
let failed = 0, total = 0; const check = (n, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${n}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
(async () => {
  const b = await launch();
  const { page, log, context } = await newPage(b, { width: 402, height: 874, isMobile: true, hasTouch: true });
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ latitude: 40.7536, longitude: -73.9832, accuracy: 8 });
  await wikimedia(page, 'up');
  await openApp(page, 2500);
  await page.click('#intentText'); await page.fill('#intentText', 'A quiet, green walk from Bryant Park to Union Square.'); await page.click('#mCreate');
  await page.waitForTimeout(1500); await page.waitForFunction(() => state.routes.length && !state.routingBusy, null, { timeout: 90000 }).catch(() => {}); await page.waitForTimeout(2500);
  const labels = await page.evaluate(() => ({ preview: $('routePreviewBtn').textContent.trim(), ar: $('navAr').textContent.trim(), arTitle: $('navAr').title }));
  check('3D button says it is a map: "3D map preview"', labels.preview === '3D map preview', labels);
  check('AR button says it uses the compass: "AR · compass"', labels.ar === 'AR · compass' && /compass/.test(labels.arTitle), labels);
  const c0 = await page.evaluate(() => state.routes.find((r) => r.id === state.activeRoute).raw.geometry.coordinates[0]);
  await context.setGeolocation({ latitude: c0[1], longitude: c0[0], accuracy: 8 });
  await page.locator('#navStart').scrollIntoViewIfNeeded(); await page.click('#navStart'); await page.waitForTimeout(1500);
  if (await page.locator('#navChoice:not(.hidden)').count()) { await page.locator('#navChoice button').first().click(); await page.waitForTimeout(800); }
  // walk the route at 1.33 m/s: a fix every 20 m, 15 s apart (the engine treats faster motion as a GPS jump)
  const seen = await page.evaluate(async () => {
    const c = nav.route.geometry.coordinates, k = 111320 * Math.cos(c[0][1] * Math.PI / 180), pts = [];
    for (let i = 1; i < c.length; i++) { const L = Math.hypot((c[i][0] - c[i - 1][0]) * k, (c[i][1] - c[i - 1][1]) * 110540), n = Math.max(1, Math.round(L / 20)); for (let j = 0; j < n; j++) pts.push([c[i - 1][0] + (c[i][0] - c[i - 1][0]) * j / n, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * j / n]); }
    const out = [], t0 = Date.now(), stopAt = Math.floor(pts.length * 0.7);
    for (let i = 0; i < stopAt; i++) {
      onFix({ coords: { latitude: pts[i][1], longitude: pts[i][0], accuracy: 6, speed: 1.33, heading: null }, timestamp: t0 + i * 15000 });
      if (i % Math.ceil(stopAt / 8)) continue;
      await new Promise((r) => setTimeout(r, 50));
      const box = $('navPlace'), prog = nav.engine.lastOutput?.progress_m ?? 0, places = nav.places || [];
      const m = box.textContent.match(/^Next: (.+?) · ([\d.,]+) (m|km|ft|mi)/), p = m && places.find((x) => x.name === m[1]);
      out.push({ prog: Math.round(prog), state: nav.engine.state, text: box.textContent, shown: !box.classList.contains('hidden'), name: m?.[1], dist: m ? +m[2].replace(',', '') * (m[3] === 'km' ? 1000 : 1) : null, unit: m?.[3], expected: p ? Math.round(p.along - prog) : null, ahead: p ? p.along > prog : null, listed: Boolean(p), img: box.querySelector('img')?.alt || null, credit: box.querySelector('a')?.textContent || null, href: box.querySelector('a')?.href || null });
    }
    return out;
  });
  console.log(JSON.stringify(seen.map((s) => [s.prog, s.state, s.name, s.dist])));
  const shown = seen.filter((s) => s.shown);
  check('navigation shows "Next: <place> · <distance>" for a listed place ahead on the route', shown.length >= 3 && shown.every((s) => s.listed && s.ahead), seen);
  check('the distance is the distance along the route to that place (±30 m, metric)', shown.every((s) => s.unit !== 'm' || Math.abs(s.dist - s.expected) <= 30), shown.map((s) => [s.name, s.dist, s.expected]));
  check('the place changes as you walk past it', new Set(shown.map((s) => s.name)).size >= 2, shown.map((s) => s.name));
  const withPhoto = shown.filter((s) => s.img);
  check('a photo next to the place carries its author · licence and links to its Commons page', withPhoto.length > 0 && withPhoto.every((s) => /·/.test(s.credit) && /^https:\/\/commons\.wikimedia\.org\/wiki\/File:/.test(s.href)), withPhoto);
  const heading = await page.evaluate(() => $('navHeadingNote').textContent);
  check('direction note only speaks up when direction is missing (none here: no device compass in this browser)', /No device direction|No direction data/.test(heading), heading);
  await shot(page, 'nav-next-place.png');
  check('no page errors', log.errors.length === 0, log.errors.slice(0, 3));
  await b.close();
  console.log(`\n${total - failed}/${total} checks passed (navigation: next place, honest AR / 3D labels)`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
