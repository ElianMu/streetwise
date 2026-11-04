'use strict';
// Multi-stop walks: stops named in the request (as you type) and stops added by hand appear between From and To —
// on the phone home block and in the Plan view — in visiting order, and the planned walk visits them in that order.
const { launch, newPage, openApp, shot } = require('./harness');
let failed = 0, total = 0; const check = (n, ok, d) => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${n}${ok ? '' : ' — ' + JSON.stringify(d)}`); };
const rows = (page) => page.evaluate(() => ({ from: $('mContextFrom').textContent, to: $('mContextTo').textContent,
  stops: [...document.querySelectorAll('#mContextStops .m-ft-row')].map((r) => [r.querySelector('.m-ft-k').textContent, r.querySelector('.m-ft-v').textContent]),
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
  check('typed "via A and B": two stops between From and To, in the typed order', r.from === 'Bryant Park' && r.to === 'Rockefeller Center' && r.stops.length === 2 && r.stops[0][0] === 'Stop 1' && /Times Square/.test(r.stops[0][1]) && /New York Public Library/.test(r.stops[1][1]) && r.named.every((n, i) => n[1] === i + 1 && n[2] === 'text'), r);
  await shot(page, 'multi-stop-typing.png');
  // 2) editing the request replaces the text stops (no duplicates)
  await page.fill('#intentText', 'Walk from Bryant Park to Rockefeller Center via Grand Central Terminal'); await page.dispatchEvent('#intentText', 'input');
  await page.waitForFunction(() => journey.named.length === 1 && /Grand Central/.test(journey.named[0].place.name), null, { timeout: 20000 }).catch(() => {});
  r = await rows(page);
  check('changing the text replaces the stops it named (one stop now, no leftovers)', r.stops.length === 1 && /Grand Central/.test(r.stops[0][1]) && r.named.length === 1 && r.named[0][1] === null, r);
  // 3) Chinese
  await page.fill('#intentText', '从时代广场出发，途经布莱恩特公园和中央车站，到帝国大厦'); await page.dispatchEvent('#intentText', 'input');
  await page.waitForFunction(() => journey.named.length === 2 && $('mContextTo').textContent === 'Empire State Building', null, { timeout: 20000 }).catch(() => {});
  r = await rows(page);
  check('Chinese "途经A和B": From 时代广场, two stops in order, To 帝国大厦', r.from === 'Times Square' && r.to === 'Empire State Building' && r.stops.length === 2 && /Bryant Park/.test(r.stops[0][1]) && /Grand Central/.test(r.stops[1][1]), r);
  // 4) "+ Add stop" opens the Plan view at the stop search, which sits between From and To
  await page.click('#intentText'); await page.evaluate(() => document.activeElement.blur()); await page.waitForTimeout(300);
  const btn = await page.waitForSelector('#mAddStop', { state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
  await page.click('#mAddStop'); await page.waitForTimeout(700);
  const plan = await page.evaluate(() => { const box = $('stopsBox'), from = $('searchStart'), to = $('searchEnd');
    const after = (a, z) => !!(a.compareDocumentPosition(z) & Node.DOCUMENT_POSITION_FOLLOWING);
    return { view: document.body.dataset.mview, focused: document.activeElement?.id, order: after(from, box) && after(box, to), listed: [...box.querySelectorAll('.js-name')].map((e) => e.firstChild.textContent), count: $('stopsCount').textContent }; });
  check('"+ Add stop" on the home block opens the Plan view at the stop search', btn && plan.view === 'plan' && plan.focused === 'addStopSearch', { btn, ...plan });
  check('Plan view reads From → Stops → To; the stops are listed there in order', plan.order && plan.listed.length === 2 && /Bryant Park/.test(plan.listed[0]) && plan.count === '2 STOPS', plan);
  await shot(page, 'multi-stop-plan.png');
  // 5) add one by hand and remove one: home rows follow
  await page.evaluate(async () => { const p = await findNamedPlace('Madison Square Park'); addNamedStop(p); });
  await page.waitForTimeout(300);
  r = await rows(page);
  check('a stop added by hand is kept next to the typed ones', r.named.length === 3 && r.named.some((n) => /Madison Square/.test(n[0]) && n[2] === 'hand'), r);
  await page.evaluate(() => document.querySelector('#stopList [data-js-x="0"]').click()); await page.waitForTimeout(300);
  r = await rows(page);
  check('removing a stop in the Plan view updates the home rows', r.named.length === 2 && !r.named.some((n) => /Bryant Park/.test(n[0])), r);
  // 6) more than 3 stops: two rows + "+N more"
  await page.evaluate(async () => { for (const n of ['Union Square', 'Washington Square Park']) addNamedStop(await findNamedPlace(n)); });
  await page.waitForTimeout(300);
  r = await rows(page);
  check('4 stops: home block shows 2 rows and "+2 more stops"', r.named.length === 4 && r.stops.length === 3 && r.stops[2][1] === '+2 more stops', r);
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
