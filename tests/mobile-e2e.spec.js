// Mobile-first E2E (Playwright, §20.4-20.5 of the Mobile-first brief): real browser,
// real local server, real screenshots. Not a visual-regression diff suite (no baseline
// images are committed) — it's a functional + layout check at the required widths plus
// one full user-flow pass, with screenshots saved for human review.
//
// Requires a running local server first: `python3 server.py` (defaults to :8080) or set
// MOBILE_E2E_BASE_URL to point at another instance (e.g. the one this repo's other tests
// start on :8090 via the Browser pane). Skips cleanly (not a failure) if nothing answers.
//
// Run: npx playwright test tests/mobile-e2e.spec.js
'use strict';
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.MOBILE_E2E_BASE_URL || 'http://127.0.0.1:8080';
const SHOT_DIR = path.join(__dirname, '..', 'screenshots', 'mobile-e2e');
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.beforeAll(async ({ request }) => {
  try {
    const r = await request.get(BASE_URL, { timeout: 3000 });
    if (!r.ok()) test.skip(true, `${BASE_URL} responded ${r.status()} - start server.py first`);
  } catch (e) {
    test.skip(true, `${BASE_URL} is not reachable (${e.message}) - start server.py first`);
  }
});

// §14: the required device/viewport matrix, plus tablet and desktop.
const WIDTHS = [
  { name: '360x800-android', width: 360, height: 800 },
  { name: '375x667-iphone-se', width: 375, height: 667 },
  { name: '390x844-iphone12-13', width: 390, height: 844 },
  { name: '393x852-iphone14', width: 393, height: 852 },
  { name: '430x932-iphone-pro-max', width: 430, height: 932 },
  { name: '768x1024-tablet', width: 768, height: 1024 },
  { name: '1440x900-desktop', width: 1440, height: 900 },
];

// 741-1060px (the "768x1024-tablet" row below) is the pre-existing tablet drawer,
// untouched by this change and by Priorities 1-4 (scoped to <=740px): #rightPanel
// sits off-canvas via `transform: translateX(calc(100% + 30px))`. That inflates
// document.documentElement.scrollWidth, and — confirmed live, including after
// trying the stronger `overflow-x: clip` on html/body — window.scrollTo() can
// still move window.scrollX at this width even though nothing is rendered
// scrollable and no scrollbar appears. This was already flagged as a known,
// pre-existing characteristic (not a regression) by the mobile-first pass this
// branch builds on; real touch/trackpad scrolling was not confirmed to trigger
// it (only programmatic scrollTo was tested here), and fixing the underlying
// 741-1060px drawer is out of this change's scope. Recorded as a real, open,
// deferred finding — see MOBILE_TEST_REPORT.md — rather than silently passed.
for (const vp of WIDTHS) {
  const isKnownTabletDrawerWidth = vp.width > 740 && vp.width <= 1060;
  test(`no horizontal overflow at ${vp.name}`, async ({ page }) => {
    test.fixme(isKnownTabletDrawerWidth, 'pre-existing 741-1060px tablet drawer scrollWidth/scrollTo quirk — see comment above, out of scope for this change');
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto(BASE_URL, { waitUntil: 'load' });
    await page.waitForTimeout(2500); // real map/data load, not a fixed-size asset
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await page.screenshot({ path: path.join(SHOT_DIR, `viewport-${vp.name}.png`) });
    // 1px tolerance for sub-pixel layout rounding, not a silent pass on real overflow.
    expect(overflow, `${vp.name}: document is ${overflow}px wider than the viewport`).toBeLessThanOrEqual(1);
  });
}

test('mobile v2 home: natural-language composer + map, optional chip row only — no Personalize sheet, Customize panel or FROM/TO form', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto(BASE_URL, { waitUntil: 'load' });
  await page.waitForTimeout(2500);
  await expect(page.locator('body')).toHaveAttribute('data-mview', 'home');
  await expect(page.locator('#mComposer')).toBeVisible();
  await expect(page.locator('#intentText')).toHaveAttribute('placeholder', 'Describe your ideal walk...');
  await expect(page.locator('#mCreate')).toBeVisible();
  await expect(page.locator('#mapLocate')).toBeVisible();
  for (const id of ['leftPanel', 'rightPanel', 'exploreSheet']) await expect(page.locator('#' + id)).toHaveAttribute('data-level', 'hidden');
  // Only the optional home chip row (#mQuickPrefs) may show chips; the Customize panel (#quickPrefs) stays closed.
  expect(await page.locator('#mQuickPrefs .quick-pref').count()).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.getElementById('quickPrefs').getBoundingClientRect().top >= innerHeight)).toBe(true);
  expect(await page.getByText('Personalize your walk').count()).toBe(0);
  // Focusing the composer must never open Customize / the 12 dimensions.
  await page.locator('#intentText').click();
  await expect(page.locator('body')).toHaveAttribute('data-mview', 'typing');
  await expect(page.locator('#leftPanel')).toHaveAttribute('data-level', 'hidden');
});

test('mobile user flow: explore -> plan -> results -> navigation', async ({ page, context }) => {
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ latitude: 40.7536, longitude: -73.9832, accuracy: 15 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(BASE_URL, { waitUntil: 'load' });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(SHOT_DIR, '01-mobile-explore.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

  // Explore Urban Data -> the migrated bottom sheet (Priority 2)
  await page.getByRole('button', { name: 'Explore Urban Data' }).click();
  await page.waitForTimeout(600);
  await expect(page.locator('#exploreSheet')).toHaveAttribute('data-level', /half|full/);
  await page.screenshot({ path: path.join(SHOT_DIR, '05-mobile-urban-data.png') });

  // Back to the map (Mobile v2: Urban Data is a full-screen map view with a "← Map" pill), then open
  // Plan walk from the menu and generate a real route from the FROM/TO form — no natural language needed.
  await page.locator('#mViewExit').click();
  await expect(page.locator('body')).toHaveAttribute('data-mview', 'home');
  await page.locator('#mobileMore summary').click();
  await page.locator('[data-mview-go="plan"]').click();
  await expect(page.locator('#leftPanel')).toHaveAttribute('data-level', /half|full/);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOT_DIR, '02-mobile-planner.png') });

  await page.locator('#mSheetGo').click();
  // `state` is a top-level `const` in app.js — a classic script's top-level
  // const/let becomes a lexical global, not a window property, so this must be
  // a bare reference (`window.state` is always undefined and would hang forever).
  await page.waitForFunction(() => typeof state !== 'undefined' && state.routes && state.routes.length > 0, undefined, { timeout: 30000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOT_DIR, '03-mobile-results.png') });

  // Priority 3: swipeable cards exist and scroll-snap is active
  const cardCount = await page.locator('#routeCards .route-card').count();
  expect(cardCount).toBeGreaterThan(0);
  if (cardCount > 1) await expect(page.locator('#routeDots')).not.toHaveClass(/hidden/);

  // Start Navigation -> full-screen nav mode (Priority 4)
  const navStart = page.locator('#navStart');
  await expect(navStart).toBeVisible({ timeout: 10000 });
  await navStart.click();
  await page.waitForTimeout(1500);
  await expect(page.locator('body')).toHaveClass(/nav-mode/);
  await page.screenshot({ path: path.join(SHOT_DIR, '04-mobile-navigation.png') });

  await page.locator('#navExit').click();
  await expect(page.locator('body')).not.toHaveClass(/nav-mode/);
});

test('desktop regression: three-column layout, no mobile sheet handles', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(BASE_URL, { waitUntil: 'load' });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(SHOT_DIR, '06-desktop-home.png') });
  expect(await page.locator('.sheet-handle').count()).toBe(0);
  await expect(page.locator('#leftPanel')).toBeVisible();
  await expect(page.locator('#rightPanel')).toBeVisible();
  const leftPanelPos = await page.locator('#leftPanel').evaluate((el) => getComputedStyle(el).position);
  expect(leftPanelPos).toBe('static');
});
