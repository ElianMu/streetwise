# Mobile-First Implementation — Test Report

Honest status only: a row says "Passed" only where a command was actually run and
its real output is shown or summarized below. Nothing here is inferred or assumed.

## 1. Automated tests — before vs. after

Baseline run before any code change, and the identical commands re-run after all
changes (`mobile-ui.js`, `pwa-register.js`, `sw.js`, and the `index.html`/`app.js`/
`styles.css` edits):

| Suite | Before | After |
|---|---|---|
| `node tests/spatial.test.cjs` | pass | pass |
| `node tests/real-route.test.cjs` | pass | pass |
| `node tests/urban-geo.test.cjs` | pass (14/14 geometry checks, 0.146% projection error) | pass |
| `node tests/urban-style.test.cjs` | pass (route is the only lime of 42 colours checked) | pass |
| `node tests/weather.test.cjs` | pass | pass |
| `node tests/places.test.cjs` | pass (recorded provider responses) | pass |
| `node tests/opening-hours.test.cjs` | pass (23 cases) | pass |
| `node tests/nav-gps.test.cjs` | pass (15/15 replayed GPS scenarios) | pass |
| `JSDOM_PATH=... node tests/dom.test.cjs` | pass | pass |
| `python3 -m unittest discover -s tests -p 'test_*.py'` | **263/263 pass** | not re-run (no Python file was touched; see below) |

The Python suite was not re-run after the mobile/PWA edits because zero `.py` files
changed in this pass — re-running it would test nothing new. It was run once, at the
start, to establish that the baseline itself was clean (it was: `Ran 263 tests ... OK`).

`tests/dom.test.cjs` loads `index.html` and executes `experience-core.js`,
`api-config.js`, `weather.js`, `places.js`, `opening-hours.js`, `app.js`,
`route-client.js`, `weather-ui.js`, `journey.js`, `journey-ui.js`, `voice.js`,
`nav-engine.js`, `nav-ui.js`, `urban-geo.js`, `urban-style.js`, `urban-layers.js`,
`explore-map.js`, `explore-analytics.js`, `center-map.js` — i.e. it exercises the
files `app.js`'s edit touches. It does **not** load `mobile-ui.js`,
`pwa-register.js` or `sw.js` (they aren't in its fixed script list), so it does not
by itself prove those three new files are correct — the manual browser verification
below is what covers them.

`node --check` syntax validation on all three new files: **all three pass.**

## 2. Manual verification — real browser, real local server

Server: `python3 server.py` (LLM key not configured locally → "LOCAL PREVIEW" mode,
honestly labelled in the UI itself, consistent with `README.md`). Driven through
Claude's Browser-pane tool (a real Chromium instance, not a stub).

**Desktop regression (1440×900):** three-column layout renders exactly as before;
`document.querySelectorAll('.sheet-handle').length === 0`, `#leftPanel`'s computed
`transform: none`, `position: static` — confirms the mobile JS/CSS is fully inert
above 740px.

**Phone, 375×812:**
- Fresh load: map renders fully (real MapLibre/CARTO tiles, live NYC data layers —
  "Urban Data Layers 61/69 on"), sheet shows correctly collapsed (`"Plan your walk"`
  peek, 64px visible).
- Tap the handle → sheet animates to `full`, the real planning form is reachable
  (From/To fields pre-filled with Bryant Park → Rockefeller Center, natural-language
  box, "Plan My Walk" button, journey stops, preferences).
- Scrolled the open sheet's content (`.panel-scroll`) — scrolls normally, sheet stays
  pinned at `full`, no accidental close. (This is the exact failure mode §11.2 of the
  brief called out — verified not to happen.)
- Tapped **Plan My Walk** → a real route was computed on the real pedestrian routing
  engine and drawn on the map (yellow route line, real "Recommended. Personalized
  score 60.6 = weighted experience 60.6 − 0.0 detour penalty (+0.0% vs shortest)..."
  text — genuine computed output, not a stub) — **and the Results sheet auto-opened
  to `half`**, confirming the `MutationObserver` on `#navStart` works.
- The install banner ("Install STROLLANE on your home screen…") appeared **only
  after** that real route was generated, not on first load — confirmed by checking
  `document.getElementById('installBanner')` is `null` immediately after a fresh
  page load, before any interaction.
- Dismissed the banner (✕) — removed, and a `localStorage` flag set (not
  independently re-verified that it stays dismissed after reload, see §4).
- Expanded the Results sheet to `full`, then dispatched a `pointerdown` on `#map` —
  confirmed via `dataset.level` reading `"collapsed"` afterward (programmatic, since
  the visible map area at `full` is too small to reliably hit by screen coordinate
  in this tool).
- Simulated `body.classList.add('nav-mode')` and read computed `display` on
  `#leftPanel`, `#rightPanel`, `.topbar`, `.mobile-bottom`: all `"none"` — the
  pre-existing nav-mode CSS convention still fully applies on top of the new sheet.

**Phone, 390×844 and 360×800:** `document.documentElement.scrollWidth <=
innerWidth` — **true at both sizes** (no horizontal overflow). 2 sheet handles
present at both sizes. Screenshotted both; map, topbar controls and sheet peek all
fit without clipping or overlap.

**Tablet, 768×1024:** `scrollWidth (1123) > innerWidth (768)` — **numerically
true**, but `overflow-x: hidden` is already set on `html`/`body` by a *pre-existing*
rule (`@media(max-width:1060px){html,body{overflow-x:hidden}}`, not written in this
pass) specifically to neutralize the old tablet drawer's off-screen
`translateX(calc(100% + 30px))` positioning, which is what's inflating `scrollWidth`.
The practical effect — confirmed by inspecting `getComputedStyle` — is that nothing
is actually scrollable; this is a pre-existing characteristic of the untouched
741–1060px drawer, not a regression, and was not "fixed" here because it's outside
this pass's scope (only ≤740px was changed). Flagging it rather than silently
leaving it out.

## 3. Service Worker — what was and wasn't confirmed

- `curl -D- http://localhost:8080/sw.js` → `200 OK`, `Content-type: text/javascript`,
  2923 bytes — the file is served correctly.
- `fetch('/sw.js')` from the page → `ok:true, status:200` — reachable from the page's
  own origin with no CORS/MIME issue.
- `navigator.serviceWorker.register('./sw.js')` → **fails** in this session's
  Browser-pane tool with `TypeError: ... An unknown error occurred when fetching the
  script.` A trivial inline no-op worker (via a data/blob URL) fails registration
  too, for an unrelated same-origin reason (`blob:` URLs aren't a valid SW script
  origin) — which rules out `sw.js`'s own content as the cause of the *first*
  failure, but does not positively prove registration would succeed elsewhere.
- **Conclusion: `sw.js` and its registration code are believed correct (file serves
  correctly, syntax-checked, and the caching logic was code-reviewed against the
  same-origin/`/api/`/`/data/` rules in `PWA_IMPLEMENTATION.md`), but Service Worker
  *activation* was not actually observed working in this session.** This needs a
  real desktop or mobile browser (not this automation sandbox) before it's called
  Tested rather than Implemented.

## 4. Not tested at all (said plainly, not left implicit)

- Any physical device: no iPhone, no Android phone, no real GPS/compass/orientation
  sensor, no real microphone (Web Speech voice input), no real Wake Lock behavior,
  no real "Add to Home Screen" flow on iOS Safari or Android Chrome, no real
  lock-screen/background behavior.
- Whether the install banner's dismissal actually persists across a reload (only the
  immediate DOM removal was checked, not a subsequent fresh load).
- A Playwright-driven visual-regression screenshot suite (the brief's §20.4) — not
  built; manual screenshots were taken instead (see §2) but there's no repeatable
  automated screenshot comparison in the repo from this pass.
- Explore Urban Data's phone layout — unchanged from before this pass, so not
  re-tested beyond the existing `dom.test.cjs` coverage of its logic (which was
  already passing and still passes).
- Any of `nav-ui.js`'s real-device-only claims in `README.md` (GPS heading vs
  compass, lock-screen limits) — these were already honestly marked
  "Implemented, Not Device-Tested" in the README before this pass, and remain so;
  nothing in this pass changed that status either way.
