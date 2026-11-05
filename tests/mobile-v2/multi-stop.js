'use strict';
// Multi-stop walks: stops named in the request (as you type) and stops added by hand appear between From and To —
// in the Plan view (Edit) and as one compact "Via" line on the phone home block — in visiting order, and the planned
// walk visits them in that order. Stops are added in Edit, not with a button on the control panel.
const { launch, newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0; const check = (n, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${n}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
const rows = (page) => page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent,
  via: [...document.querySelectorAll('#mContextStops .m-ft-row')].map((r) => r.querySelector('.m-ft-k').textContent + ': ' + r.querySelector('.m-ft-v').textContent),
  stops: journey.named.map((n) => n.place.name),
  named: journey.named.map((n) => [n.place.name, n.order, n.src || 'hand']) }));
(async () => {
  const b = await launch();
  const { page, log } = await newPage(b, { width: 440, height: 956 });
  await openApp(page, 2500);
  // 1) English request with two stops
  await page.click('#intentText');
  await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center via Times Square and the New York Public Library'); await page.dispatchEvent('#intentText', 'input');
  await page.waitForFunction(() => journey.named.length === 2, null, { timeout: 20000 }).catch(() => {});
  let r = await rows(page);
  check('typed "via A and B": two stops in the typed order, shown as one "Via" line between From and To', r.from === 'Bryant Park' && r.to === 'Rockefeller Center' && r.stops.length === 2 && /Times Square/.test(r.stops[0]) && /New York Public Library/.test(r.stops[1]) && r.via.length === 1 && /^Via: 2 stops · Times Square.*, .*New York Public Library/.test(r.via[0]) && r.named.every((n, i) => n[1] === i + 1 && n[2] === 'text'), r);
  await shot(page, 'multi-stop-typing.png');
  // 2) editing the request replaces the text stops (no duplicates)
  await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center via Grand Central Terminal'); await page.dispatchEvent('#intentText', 'input');
  await page.waitForFunction(() => journey.named.length === 1 && /Grand Central/.test(journey.named[0].place.name), null, { timeout: 20000 }).catch(() => {});
  r = await rows(page);
  check('changing the text replaces the stops it named (one stop now, no leftovers)', r.stops.length === 1 && /Grand Central/.test(r.stops[0]) && /^Via: Grand Central/.test(r.via[0]) && r.named.length === 1 && r.named[0][1] === null, r);
  // 3) Chinese
  await page.fill('#intentText', '从时代广场出发，途经布莱恩特公园和中央车站，到帝国大厦'); await page.dispatchEvent('#intentText', 'input');
  await page.waitForFunction(() => journey.named.length === 2 && $('mContextTo').textContent === 'Empire State Building', null, { timeout: 20000 }).catch(() => {});
  r = await rows(page);
  check('Chinese "途经A和B": From 时代广场, two stops in order, To 帝国大厦', r.from === 'Times Square' && r.to === 'Empire State Building' && r.stops.length === 2 && /Bryant Park/.test(r.stops[0]) && /Grand Central/.test(r.stops[1]), r);
  // 4) no "+ Add stop" button on the control panel; Edit opens the Plan view with the stop search between From and To
  await page.click('#intentText'); await page.evaluate(() => document.activeElement.blur()); await page.waitForTimeout(300);
  const panel = await page.evaluate(() => ({ button: !!document.getElementById('mAddStop'), text: document.querySelector('.m-composer').innerText,
    h: Math.round(document.querySelector('.m-route-ends').getBoundingClientRect().height) }));
  check('control panel has no "Add stop" button; stops take one line (From / Via / To)', !panel.button && !/Add stop/i.test(panel.text) && panel.h < 110, panel);
  await page.click('#mContext'); await page.waitForTimeout(700);
  const plan = await page.evaluate(() => { const box = $('stopsBox'), from = $('searchStart'), to = $('searchEnd');
    const after = (a, z) => !!(a.compareDocumentPosition(z) & Node.DOCUMENT_POSITION_FOLLOWING);
    const sr = $('addStopSearch').getBoundingClientRect();
    return { view: document.body.dataset.mview, search: sr.height > 0 && getComputedStyle($('addStopSearch')).visibility !== 'hidden', order: after(from, box) && after(box, to), listed: [...box.querySelectorAll('.js-name')].map((e) => e.firstChild.textContent), count: $('stopsCount').textContent }; });
  check('Edit opens the Plan view, where the stop search is shown', plan.view === 'plan' && plan.search, plan);
  check('Plan view reads From → Stops → To; the stops are listed there in order', plan.order && plan.listed.length === 2 && /Bryant Park/.test(plan.listed[0]) && plan.count === '2 STOPS', plan);
  await shot(page, 'multi-stop-plan.png');
  // 5) add one by hand and remove one: home rows follow
  await page.evaluate(async () => { const p = await findNamedPlace('Madison Square Park'); addNamedStop(p); });
  await page.waitForTimeout(300);
  r = await rows(page);
  check('a stop added by hand is kept next to the typed ones', r.named.length === 3 && r.named.some((n) => /Madison Square/.test(n[0]) && n[2] === 'hand'), r);
  await page.evaluate(() => document.querySelector('#stopList [data-js-x="0"]').click()); await page.waitForTimeout(300);
  r = await rows(page);
  check('removing a stop in the Plan view updates the home "Via" line', r.named.length === 2 && !r.named.some((n) => /Bryant Park/.test(n[0])), r);
  // 6) four stops: still one line on the home block
  await page.evaluate(async () => { for (const n of ['Union Square', 'Washington Square Park']) addNamedStop(await findNamedPlace(n)); });
  await page.waitForTimeout(300);
  r = await rows(page);
  check('4 stops: home block still shows one "Via · 4 stops" line', r.named.length === 4 && r.via.length === 1 && /^Via: 4 stops · /.test(r.via[0]), r);
  // 7) a real plan visits the stops in order
  await page.evaluate(() => $('mSheetBack')?.click()); await page.waitForTimeout(500);
  await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center via Times Square and the New York Public Library'); await page.dispatchEvent('#intentText', 'input');
  await page.evaluate(() => { for (const n of [...journey.named]) if (n.src !== 'text') journey.named.splice(journey.named.indexOf(n), 1); });
  await page.waitForFunction(() => journey.named.length === 2 && journey.named.every((n) => n.src === 'text'), null, { timeout: 20000 }).catch(() => {});
  await page.evaluate(() => planJourney(false)); await page.waitForFunction(() => journey.plan && state.routes.length > 0, null, { timeout: 90000 }).catch(() => {});
  const plan2 = await page.evaluate(() => ({ stops: (journey.plan?.stops || []).filter((s) => s.role !== 'end').map((s) => s.name), routes: state.routes.length }));
  check('planned walk visits Times Square then the Library (real routing)', plan2.routes > 0 && plan2.stops.findIndex((n) => /Times Square/.test(n)) >= 0 && plan2.stops.findIndex((n) => /Times Square/.test(n)) < plan2.stops.findIndex((n) => /New York Public Library/.test(n)), plan2);
  await shot(page, 'multi-stop-results.png');
  check('no page errors', log.errors.length === 0, log.errors.slice(0, 3));
  await b.close(); console.log(`\n${total - failed}/${total} checks passed (multi-stop walks)`); process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
