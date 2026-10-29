# Mobile Implementation — Test Report

## Mobile v2 — Natural Language First (current branch, final source tree)

A result is listed only for a command that was actually run on the final tree. Every row is classified; no simulated
run is reported as a real-device or real-service result.

### Environments

| Where | Used for | Notes |
|---|---|---|
| Your Mac, Linux shell of the Claude desktop app | Python + JS unit / integration suites on the final files | Python **3.12.16** in an isolated venv (the shell's system Python 3.10 cannot load the network: `routing/engine.py` uses `hashlib.file_digest`, 3.11+; CI pins 3.12). `pyproj 3.8.0` installed in that venv for the one geodesic test. Python suite run from a scratch copy of the tree, because the menu-verification tests create and delete `tests/.tmp-verified-items.json` and deletes are blocked inside the connected folder. `jsdom@24` from a folder outside the repo (`JSDOM_PATH`). |
| Cloud workspace (same files, checksum-verified) | Browser tests: Playwright Chromium against the real `server.py` | Outbound network limited to package registries: MapLibre CDN, CARTO basemap, Google Fonts, live geocoders, Open-Meteo, ArcGIS street service unreachable. With `SANDBOX_CDN=1`, MapLibre 4.7.1 is served from the identical npm build and the basemap style is a plain dark background — test fixture only, production config unchanged. |

### Results

| Suite | Command | Class | Result |
|---|---|---|---|
| Python, all | `python -m pytest -q tests` (3.12, scratch copy) | Unit + Integration (real routing engine, real data files) | **262 passed, 1 skipped, 0 failed** — skip: `tests/test_agent.py:68` needs live Open-Meteo (403 at the proxy) → **Blocked** |
| JS, all | `JSDOM_PATH=… node --test tests/*.test.cjs` | Unit + DOM integration (network blocked by design) | **11/11 suites pass** |
| Navigation GPS replay | `node tests/nav-gps.test.cjs` | Unit, deterministic synthetic tracks | **17/17** (incl. 2 new regression scenarios for the intermittent-error off-route bug; the first fails on the old engine) |
| Repo Playwright spec | `npx playwright test tests/mobile-e2e.spec.js` (CDN fixture injected) | Real Routing E2E | **9 passed, 1 skipped** (the pre-existing `fixme` for the 741–1060 px drawer quirk) |
| Mobile v2 flows | `SANDBOX_CDN=1 node tests/mobile-v2/flows.js` (needs `python3 server.py` running) | mixed, per check | **94/94 checks pass** |
| Service worker under a GitHub Pages-style subpath | static server at `/STREETWISE_NYC/`, Chromium with SW enabled | Integration (real browser SW) | pass: only `strollane-shell-v3` after activation (planted `v1` purged), page controlled, 23 shell files cached, **0** `data/` or `api/` entries, shell loads offline |
| Install-banner overlap | browser geometry check at 1440, 1100, 768, iPad-Safari 834 | Real browser layout | pass: banner overlaps no button/input/summary at any width; Navigate/Explore always clear |

`tests/mobile-v2/flows.js` checks by class (94 total, 0 failed):

| Class | Checks | What is real |
|---|---|---|
| Real Routing E2E — home, typing, Flow A (NL → local preview parser → `/api/itinerary`), refinement, Flow B (manual FROM/TO, pick on map, no text → itinerary with café stop), Flow C (Customize: chips, 60 min, 12 dimensions, back to Plan), Flow E (Urban Data, dimension switch, real street-segment tap → Street Inspector, route kept), Flow F (GPS denied, offline error, start confirmation), layers, viewports, desktop, tablet | 69 (incl. 2 "Refine" checks run inside the mocked-LLM block) | server.py engine, place index, itinerary, street scores; map rendering with the substituted basemap |
| Mock E2E: LLM — `/api/status` + `/api/interpret` mocked with server-validated documents | 8 | everything after the parse: client LLM branch, place resolution (`GET /api/places/search`), Discover mode + café stop + 45 min, real `/api/itinerary`, "Shorten it to 30 minutes" refinement (only the time changes, engine re-run, map redrawn), failed re-plan keeps the last route and leaves nothing stuck busy |
| Simulated GPS (Playwright geolocation; Flow D + its own block) | 9 + 3 | navigation state machine, camera pitch 55°, 3D building layer present, instructions, pause/resume, sustained deviation → off-route → real reroute replaced the route; one wild fix → no reroute; reroute failure offline → still navigating the last route with message + Retry; back on route → NAVIGATING; reload → "Resume navigation?" |
| Console | 5 | no uncaught page errors in any flow |

### Not verified (blocked or out of reach)

| Item | Status |
|---|---|
| Real LLM parsing (`OPENAI_API_KEY`) | **Blocked** — no key; the app correctly reported `llm:false` and used the labelled local preview |
| Real basemap rendering (CARTO tiles), MapLibre from unpkg, Google Fonts | **Blocked** in every environment used — screenshots show a plain dark background instead of basemap streets/labels |
| Live address/POI autocomplete (Photon, NYC GeoSearch, Mapbox) | **Blocked** — FROM tested via pick on map + preset list instead |
| Open-Meteo weather (UI + `test_agent.py`) | **Blocked** |
| Real devices (iOS Safari, Android Chrome, compass, background behaviour, soft keyboard) | **Not tested** — all phone sizes are Chromium emulation |
| Note on time of day | Feasibility depends on opening hours at the test time: the late-night mocked-LLM run produced an honestly "NOT FEASIBLE" walk (café closed at estimated arrival); the check asserts the engine ran and the UI shows its verdict, not that a walk is feasible |

### Screenshots (real browser, final code) — `screenshots/mobile-v2/`

`01-mobile-home` · `02-mobile-natural-language-focused` · `03-mobile-plan-from-to` · `03b-mobile-pick-on-map` ·
`04-mobile-customize-walk` · `05-mobile-agent-processing` (backend reply delayed 1.5 s, response untouched, so the
in-flight state is visible) · `06-mobile-route-results` · `06b-mobile-route-results-manual` · `07-mobile-route-refinement` ·
`08-mobile-3d-navigation` · `08b-mobile-nav-off-route` · `08c-mobile-nav-reroute-failed` · `09-mobile-urban-data` ·
`10-mobile-street-inspector` · `11-desktop-regression` · `11b-desktop-routes` · `12-mobile-network-error` ·
`13-mobile-map-layers` · `14-mobile-start-confirmation` · `15-mobile-llm-mock-results` · `16-mobile-llm-mock-refined` ·
`17-tablet-768-routes` · `viewport-{360x800,375x667,390x844,393x852,430x932,768x1024,1440x900}` · `results.json`
(every check with its detail). All taken with the basemap substitution described above.

### How to re-run

```
# Python (3.11+; CI uses 3.12)            # JS
python3.12 -m venv .venv && .venv/bin/pip install pytest pyproj -r requirements.txt
.venv/bin/python -m pytest -q tests        node --test tests/*.test.cjs     # needs jsdom installed
# Browser (with a normal internet connection no substitution is needed)
python3 server.py &
npx playwright test tests/mobile-e2e.spec.js
node tests/mobile-v2/flows.js              # add SANDBOX_CDN=1 only in a network-restricted sandbox
```

---

## Earlier pass (v1 — first mobile-first pass, historical)


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
