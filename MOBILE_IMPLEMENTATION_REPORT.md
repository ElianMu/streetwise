# Mobile Implementation Report

## Mobile v2 — Natural Language First (branch `feature/mobile-screens-v2`, current)

Status as of the final source tree on this branch. Everything below was checked against the code and the test runs
listed in `MOBILE_TEST_REPORT.md`. Nothing has been committed, pushed, merged or deployed.

### What the phone UI (≤740 px) now does

| Area | Behaviour | How (reuse, not re-implementation) |
|---|---|---|
| Home | Brand + `MANHATTAN · NYC`, "How would you like to explore New York?", the request box ("Describe your ideal walk..."), mic, **Create My Walk**, a start → destination line, and the map. No sheet, quick-preference chips, Customize panel, FROM/TO form or 12-dimension list on load. | The request box **is** the existing `#intentText` (and its mic), moved into `#mComposer` by `mobile-ui.js` on phones and moved back above 740 px. |
| Create My Walk | Same call as desktop "Plan My Walk": `handlePlan()` → `/api/interpret` (LLM) or the labelled local preview → `applyInterpretation` / `applyJourney` → `/api/routes` or `/api/itinerary`. Button disabled while in flight; progress labels read from `planner.parsing` / `state.routingBusy`. | `mobile-ui.js` `createFromText()` → `runPlan(handlePlan)` |
| Start point (§4.4) | 1) start named in the request, 2) start the user chose (preset list, search, map pick, GPS fix, Plan walk), 3) GPS only after the user taps it, 4) otherwise the app **asks** ("Start at Bryant Park" / "Use my location" / "Choose start"). The shipped preset start is never used silently. | `askForStart()`; GPS goes through the existing `#gpsStart` → `requestGPS()` |
| Plan walk | The existing FROM/TO form in the existing bottom sheet: GPS, search, pick on map, Destination / Discover for me / Back to start / Back to hotel, journey stops. **Find routes** works with no text (same place checks as `handlePlan`, then `planJourney` or `generateRoutes`). | `#leftPanel` with `data-lp="plan"` |
| Customize | Time and distance limits, detour, constraints, all 12 dimensions, quick chips. | `#leftPanel` with `data-lp="customize"` |
| Quick chips | Architecture, Quiet (= `Quiet & Relax`), Nature, Scenic (= `Scenic & Visual`), Culture set the existing dimension weight (80, origin `manual`); **Coffee stop** adds a journey café stop via `applyJourney({food:[{category:'cafes'}]})`, never a dimension. "Hidden gems" is not offered (no data). Chips appear only in Customize (removed from the phone home on request); they are drawn from live state, so a chip is on exactly when the preference is set (by the chip, the Agent's parse, or a slider). | `renderQuickPrefs()` |
| Results | Request box collapses to a one-line bar; the existing results sheet shows start → destination, route cards (swipe = `selectRoute`), Start Navigation, and the follow-up conversation (`#conversationSection`, moved in). | `#rightPanel`, `#mRefineSlot` |
| Refinement | Follow-ups go through `handlePlan(q, true)`; only the mentioned constraints change; the map is redrawn from the new engine response. **New:** if the re-plan fails, the last valid route is restored and the message says so. | `snapshotRoutes()` / `restoreRoutes()` in `app.js`, used by `generateRoutes` and `planJourney` for follow-ups |
| Urban Data / Map layers | Menu or ▦ button → the existing Explore panel + Street Inspector in the explore sheet; "Map layers" shows the existing layer catalog, Street evidence, weather and legend. Leaving returns to results with the route kept. | `#modeExplore` / `#modeNavigate` clicks, `#urbanLayers` |
| Navigation | Unchanged UI and camera (pitch 55°, building extrusions, heading fallback). Phone chrome hides while `body.nav-mode` is set; exit returns to results. | `nav-ui.js`, `nav-engine.js` |
| Back | Back buttons, Escape, swiping a sheet away, and the phone's Back gesture (one history entry per secondary view). | `closeSecondary()`, `popstate` |

### Bugs found and fixed in this branch

| Bug | Severity | Fix |
|---|---|---|
| Off-route never confirmed after an intermittent location error (`GPS_WEAK` → `NAVIGATING`, then the refused `NAVIGATING → OFF_ROUTE` transition), so a walker who strayed was never rerouted | High | `nav-engine.js`: step through `POSSIBLY_OFF_ROUTE` first; evidence rule (3 fixes over 8 s) unchanged. Regression tests in `tests/nav-gps.test.cjs`. |
| `planJourney` failure left planning stuck "busy" (`resetRoutes()` bumped the run id inside the error handler, so `finally` skipped clearing `state.routingBusy`; all plan buttons stayed disabled until reload) | High | `journey.js`: `resetRoutes(true)` in the error handler, plus restore of the last valid route on follow-ups |
| Failed follow-up re-plan wiped the displayed route | Medium | `app.js` `snapshotRoutes` / `restoreRoutes` |
| Failed reroute message was replaced by "Off route" at the next 3 s refresh | Medium | `nav-ui.js` `renderNav()` keeps "Could not recalculate — your last route is still shown. Tap Retry." while the failure lasts; counter resets when back on route |
| Pick on map: the notice box covered the centre of the phone map, so the tap hit the notice | Medium | phone CSS: notice is a top bar |
| Install banner covered Navigate / Explore, GPS, legend (and hotel search ~1100 px) on tablet/desktop after the first route; on phones it covered the request bar / back pill | Medium | CSS: ≥1061 px in the top bar's free centre; 741–1060 px a compact "Install ✕" pill (iPad Safari instructions sit between brand and ⓘ, the header weather label steps aside); phones: bottom of the map, home view only |
| Service worker cached `data/` (large GIS) and `api/` responses when served from a GitHub Pages project subpath — exclusions compared `pathname.startsWith('/data/')` | Medium | `sw.js`: paths compared relative to the worker's scope; cache renamed `strollane-shell-v3` (purges older caches on activate) |

### Agent integration (verified as far as possible without a key)

`Natural language → POST /api/interpret (server.py interpret(): one schema-constrained OpenAI call, strict
validate_interpretation() — closed keys, canonical 12 dimension names only, integer 0..100, journey schema with
names only, never coordinates — plus validate_intent_bindings(), one model self-repair retry) → client
applyInterpretation() (weights, time, constraints) + applyJourney() (origin/destination/stops resolved through the
app's own place index /api/places/search; unresolved names are reported, never invented) → /api/routes or
/api/itinerary (Python engine on the OSM pedestrian graph) → map layers from the response geometry.`

| Path | Verified how |
|---|---|
| Real LLM (`OPENAI_API_KEY`) | **Not verified** — no key in any environment used. `/api/status` reports `llm:false`. |
| Server-side validation of LLM output | Python unit tests with `call_llm` mocked (`tests/test_interpret.py`, `tests/test_interpretation_contract.py`) — pass |
| Client LLM branch end to end | **Mock E2E**: `/api/status` + `/api/interpret` replies mocked in the browser with documents that pass the server's own `validate_interpretation()` (`tests/mobile-v2/fixture-llm-*.json`); place resolution, itinerary routing and map rendering are real |
| Local fallback parser | Real E2E (labelled "LIMITED LOCAL PREVIEW" in the UI) |

No Agent schema fields were added. The 12 dimensions (`app.js DIMENSIONS`, `routing/engine.py DIMENSIONS`) are unchanged.

### Files

Modified: `index.html` (composer, menu, plan/customize grouping wrappers, results slots, cache-bust query
strings), `mobile-ui.js` (view state, composer, chips, start confirmation, back handling), `styles.css` (phone block +
tablet/desktop install banner), `app.js` (route snapshot/restore), `route-client.js` and `journey.js` (keep last route on
failed follow-up; journey busy fix), `nav-engine.js` (off-route fix), `nav-ui.js` (failed-reroute message), `sw.js`
(subpath-safe exclusions, cache v3), `tests/nav-gps.test.cjs` (2 regression tests), `tests/mobile-e2e.spec.js` (updated to
the v2 UI). Pre-existing uncommitted edits kept: `.gitignore`.

Added: `tests/mobile-v2/harness.js`, `tests/mobile-v2/flows.js`, `tests/mobile-v2/fixture-llm-request.json`,
`tests/mobile-v2/fixture-llm-refine.json`, `screenshots/mobile-v2/*` (real browser screenshots + `results.json`).

Not changed: Python routing engine, Agent runtime, place/GIS data, 12 dimensions and scoring, MapLibre and the CARTO
basemap, API contracts, desktop layout.

### Known limitations / open issues

| Issue | Severity |
|---|---|
| Real LLM parsing not verified (no `OPENAI_API_KEY`) | High (verification gap) |
| Real basemap tiles, MapLibre CDN, live geocoders (Photon, NYC GeoSearch, Mapbox) and Open-Meteo unreachable from every test environment used; browser tests substitute MapLibre with the identical npm build and the basemap with a plain background **only** under `SANDBOX_CDN=1` | Medium (verification gap) |
| No real-device test (GPS, compass, iOS sensor permission, soft keyboard, Safari bars) | Medium (verification gap) |
| A "45-minute walk" can return a much shorter walk: the walking time is a hard maximum, not a target length (observed: 3.5 min to one café in Discover mode) | Medium (product / engine behaviour, unchanged) |
| Place index can prefer a smaller feature with the same name ("Columbia University" → "Columbia University Well Garden") | Medium (place ranking, unchanged) |
| Start-point detection in the request is a conservative pattern (e.g. "from Columbia"); a request it misses only triggers the confirmation prompt, never a wrong start | Low |
| 741–1060 px tablet drawer horizontal-scroll quirk (pre-existing, documented in v1) | Low |
| No reliable background GPS in a mobile browser/PWA (foreground navigation only) | Inherent |

---

## Earlier pass (v1 — first mobile-first pass, historical)


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
