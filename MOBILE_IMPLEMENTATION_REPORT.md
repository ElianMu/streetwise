# Mobile-First Web App Implementation Report

Branch: `feature/mobile-first-pwa`. Scope actually delivered in this pass, against the
full brief in the originating prompt — this report says plainly which parts of that
brief are done, which are partial, and which were not attempted, rather than treating
the whole brief as completed.

## 1. What was audited first (Phase 1)

Before changing anything: `git status` (clean except a pre-existing untracked
`.gitattributes`), `git log`, and the full existing automated test suite, as a
baseline to diff against:

- 8 Node test files (`tests/*.test.cjs`): spatial, real-route, urban-geo, urban-style,
  weather, places, opening-hours, nav-gps — **all 8 passed** before any change.
- `tests/dom.test.cjs` (jsdom integration, loads `index.html` + the real app scripts
  and exercises the AI planner, routing, Explore, navigation and urban-data code
  paths with network calls stubbed) — **passed**.
- `python3 -m unittest discover -s tests -p 'test_*.py'` — **263 tests, all passed**.

Read in full or in relevant part: `README.md`, `ARCHITECTURE.md`, `API.md`,
`DEPLOYMENT.md`, `index.html`, `styles.css`, `app.js`, `api-config.js`, `server.py`
(CORS section), `nav-ui.js` / `nav-engine.js` (navigation state machine and UI),
`experience-core.js` (the 12 Experience Dimensions — **not modified, not
renamed, not reinterpreted**), `site.webmanifest`.

Key findings that shaped everything below:

- Mobile support was exactly as the brief suspected: `#leftPanel` (planning form) and
  `#rightPanel` (route results) were desktop side columns that, under `max-width:
  1060px` / `740px`, became **slide-in drawers** toggled by two small buttons
  (`#mobilePlan`, `#mobileResults`) via a plain `.mobile-active` class — not a
  bottom-sheet, not map-first.
- `api-config.js` and `server.py`'s CORS allow-list are **already correctly scoped**
  for "mobile web, not native app": the API base only special-cases
  `elianmu.github.io`, everything else (including a phone on the same Wi-Fi hitting
  `server.py` directly) uses the relative `/api/...` path, which works unchanged
  because `server.py` serves both the static app and the API on one origin. CORS
  only allow-lists `https://elianmu.github.io`. **No change was needed or made** to
  either file.
- `nav-engine.js` / `nav-ui.js` already implement almost everything §10 of the brief
  asked for: a 13-state navigation state machine, windowed map-matching, turn-by-turn
  maneuvers from real route topology, voice (EN/中文), pause/resume, off-route
  detection and rerouting that preserves remaining required stops, and a
  `body.nav-mode` CSS convention that already makes navigation take over the full
  screen on phones. This was **not rewritten** — see §4.
- No Service Worker existed anywhere in the project despite a complete
  `site.webmanifest` and icon set.

## 2. What was built (Phases 2–4, 6)

### A real bottom-sheet shell (new file `mobile-ui.js`, ~115 lines)

Replaces the drawer toggle with a genuine bottom sheet for `#leftPanel` (Plan) and
`#rightPanel` (Results), active only at `≤740px` (`matchMedia`-gated; a no-op on
tablet/desktop):

- Three snap levels — **collapsed** (a 64px peek: drag handle + "Plan your walk" /
  "Your routes" label), **half** (~50% of viewport), **full** (~88dvh, leaving a
  sliver of map visible under the topbar).
- Drag-to-resize on a dedicated handle (not the whole panel, so scrolling the form or
  results list never fights the sheet), plus tap-to-toggle (collapsed ↔ full) on the
  same handle and an explicit `<button class="sheet-toggle">` for keyboard/screen-reader
  users (`aria-expanded`, `inert` + `aria-hidden` on whichever panel is closed).
- One sheet open at a time (opening one closes the other — same rule the old drawer
  buttons already enforced).
- Tapping the map collapses (not hides) a fully-expanded sheet, so the map stays the
  primary interactive surface.
- **Auto-surfaces the Results sheet** once real routes exist, via a
  `MutationObserver` on the existing `#navStart` button's `hidden` class — this
  observes the DOM, it does not call into `journey.js` / `route-client.js` / any
  routing logic, so route/journey business logic is untouched.
- Fully inert during navigation: `body.nav-mode` already hides `#leftPanel`,
  `#rightPanel` and the topbar (pre-existing CSS, confirmed, not changed) — this
  script does nothing extra to achieve that, it just doesn't fight it.
- On resize across the breakpoint (e.g. phone → tablet rotation that crosses a
  layout breakpoint matched by width), state is cleanly torn down (`unwire()`).

### CSS (`styles.css`, 19 lines net, all inside `@media(max-width:740px)` or new
standalone rules — the 20 other pre-existing media queries for map controls, legend,
weather pill, Explore panel sizing etc. were **left untouched**, since they weren't
part of the identified problem):

- The old `.left-panel{position:absolute;...transform:translateX(-103%)}` drawer rule
  is replaced with the bottom-sheet positioning (`position:fixed`, GPU-only
  `transform: translateY(...)`, `transition` disabled under
  `prefers-reduced-motion: reduce`).
- `env(safe-area-inset-top)` added to the topbar height and `.app-layout` height on
  phones; `env(safe-area-inset-bottom)` added to the sheet's own padding and to
  `.mobile-bottom`'s offset — covers the iPhone notch/Dynamic Island and the
  Home Indicator.
- z-index was tuned (sheet `19`, between the existing `mobile-bottom` buttons `18`
  and `topbar`/`nav-overlay` `20`) so an open sheet correctly covers the old
  Plan/Results buttons underneath it instead of them floating on top.

### PWA (Phase 6 — see `PWA_IMPLEMENTATION.md` for the full writeup)

- New `sw.js`: app-shell-only cache (same-origin static files), explicitly never
  caches `/api/*`, `/data/*`, or any cross-origin request (MapLibre CDN, CARTO/OSM
  tiles, Open-Meteo, the Render API). Network-first for the HTML document itself so
  cached JS can never run against a stale page; cache-first for the already
  `?v=NN`-tagged static assets.
- New `pwa-register.js`: registers the worker, and shows a small dismissible
  "Add to Home Screen" banner — but **only after the user has generated a real
  route** (same non-invasive `MutationObserver` on `#navStart` used by
  `mobile-ui.js`), never on first load. iOS gets a Share-sheet tip (no
  `beforeinstallprompt` exists there); Chromium gets the real install prompt.
- `site.webmanifest`, icons and Apple meta tags were **audited, not changed** — they
  were already correct.

## 3. What was deliberately NOT done in this pass

Said plainly, per the brief's own instruction not to write completed work that isn't:

- **Explore Urban Data (§12) was not migrated to the new bottom-sheet system.** The
  13-map Explore panel, the Street Segment Inspector, and the Urban Data Layers
  catalog panel still use their pre-existing `position:absolute` mobile CSS
  (unchanged, still functional, still passes the automated tests) rather than the
  new sheet. This is the single largest remaining gap against the brief.
- **No Playwright visual-regression screenshot suite** (§20.4) was added. Visual
  verification in this pass was manual, via the Browser pane, at 360×800, 375×812,
  390×844 and 768×1024 (phone/tablet) and 1440×900 (desktop) — see
  `MOBILE_TEST_REPORT.md` for exactly what was checked and what each screenshot
  showed.
- **Navigation camera/heading work (§10.2–10.4) was not touched.** `nav-ui.js`
  already implements heading priority (device compass → GPS course → route-direction
  fallback, explicitly labelled as such, never faked), FOLLOWING/FREE_LOOK/
  RECENTERING camera states, and north-up/heading-up toggling. Per the brief's own
  instruction not to rewrite a working engine without reason, this was left as-is;
  it was not independently re-verified beyond confirming `tests/nav-gps.test.cjs`
  (15 replayed GPS scenarios) still passes unchanged.
- **Real-device testing (iOS Safari, Android Chrome, physical GPS/compass/voice) was
  not performed** — this machine has no such device attached to this session. See
  `MOBILE_TEST_REPORT.md` §4 for exactly what that leaves unverified.
- **Service Worker activation could not be confirmed inside this session's sandboxed
  Browser-pane tool** — the file serves correctly (verified by direct `fetch()` and
  `curl`) but `navigator.serviceWorker.register()` fails there with a generic
  "unknown error fetching script"; a trivial no-op SW fails the same way, so this
  looks like the automation browser disabling Service Workers rather than a bug in
  `sw.js`. Needs confirmation in an ordinary desktop/mobile browser.

## 4. Files changed

| File | Change |
|---|---|
| `index.html` | +2 lines: `<script src="./mobile-ui.js">`, `<script src="./pwa-register.js">` |
| `app.js` | −2 lines: removed the old plain `.mobile-active` toggle listeners for `#mobilePlan`/`#mobileResults` (now owned by `mobile-ui.js`) |
| `styles.css` | +19 net lines: bottom-sheet rules, safe-area insets, install-banner styles, nav-mode hides the banner too |
| `mobile-ui.js` | **new** — bottom-sheet controller |
| `pwa-register.js` | **new** — SW registration + gated install banner |
| `sw.js` | **new** — app-shell service worker |

Nothing else changed: no DOM ids were renamed, no Python file was touched, no
dataset/model/routing file was touched, the 12 Experience Dimensions in
`experience-core.js` are byte-for-byte unchanged, `api-config.js` and the CORS
section of `server.py` are unchanged (found already correct for this scope).

See `MOBILE_TEST_REPORT.md` for the before/after test results and manual
verification log, `MOBILE_DESIGN_SYSTEM.md` for the sheet/breakpoint/motion rules,
`PWA_IMPLEMENTATION.md` for the service-worker/install details, and
`MOBILE_DEPLOYMENT.md` for how to run and test this locally and on a phone.
