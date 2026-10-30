# Mobile Implementation Report

## Round 10: iOS input auto-zoom + keyboard layout

**Root cause (measured at phone width):**
- On touch devices, the Plan walk text fields computed to 12 px: From (`#searchStart`), To (`#searchEnd`), hotel and
  add-stop.
- The place pickers (`#startSelect`, `#endSelect`) were 10 px, and other hidden fields 10–11 px.
- iOS (Safari and Home Screen apps) zooms the whole page when a focused field's font-size is below 16 px, and keeps
  the zoom after the keyboard closes. The enlarged page pushed Prefs / Find routes off screen.
- At 1× the bar fits: at 375 px, Find routes ends at 359 px and there is no overflow. The cut-off buttons were a
  consequence of the zoom, not a layout bug.
- The viewport meta was already correct (`width=device-width, initial-scale=1, viewport-fit=cover`) and is unchanged.
  Pinch zoom stays enabled: no `maximum-scale` and no `user-scalable`.

**Fix:**
- `styles.css`: under `@media (pointer:coarse)`, every text-entry `input`, `textarea` and `select` is set to 16 px.
  Place fields are 46 px tall with a focus ring on the whole field. Mouse devices keep the compact 12 px.
- `mobile-ui.js` keyboard handling:
  - the keyboard overlap is measured from `visualViewport` (`innerHeight − vv.height − vv.offsetTop`), never assumed,
    so it is not subtracted twice on Android, where the layout viewport itself shrinks;
  - while the keyboard is open, `--kb` and `html.kb-open` pad the open sheet so content below the field can scroll
    above the keyboard;
  - focusing a field in a sheet raises the sheet to full and places the field just below the sheet's title bar;
  - when the keyboard closes, any iOS pan is undone and the map re-measured.
- `places.js`: choosing a suggestion on a touch device blurs the field, so the keyboard closes. Start, destination,
  preferences and the map are untouched.

**Tests:** new `tests/mobile-v2/input-keyboard.js`, 61/61.
- Devices: iPhone SE, 13/14, 15 Pro and 17 Pro Max, plus Android (Pixel 8). The desktop check confirms the compact
  field size is unchanged.
- The keyboard is simulated by shrinking `visualViewport`.
- The place providers (Photon, NYC GeoSearch) are mocked with the two parks' real coordinates; routing is real.
- **REAL IPHONE VERIFICATION REQUIRED** in both a Safari tab and the Home Screen app.

## Round 9: editorial design system, brand, cartography (Editorial Minimalism × Dark Cartography)

**Audit (live site, before):**
- P0: a slow map load showed "Map tiles not reachable" after 16 s.
- P0: 19 `Space Grotesk` declarations had no fallback font, so text fell back to Times when the font failed (e.g. offline).
- P1 brand:
  - white Home Screen icon;
  - lime walker;
  - "STROLLANE | MANHATTAN · NYC" with a stray bar and a duplicated city.
- P1 color: lime with glows on every element, plus single-word accents.
- P1 icons: 🎙 / 🏨 / ☕ emoji, and Unicode glyphs as map tools.
- P1 map:
  - New Jersey labels louder than Manhattan;
  - the default white MapLibre zoom control;
  - the route told apart by glow only;
  - start and end markers told apart only by colour;
  - the route hidden under the results sheet on phones.
- P1 results: metric boxes inside a box.
- Photography: none in the product. None was added — no AI-generated or unlicensed "NYC" images.

**References:**
- Apple Maps and Mapbox Navigation: route line + casing, vanishing traveled part, location dot + accuracy halo + heading
  beam.
- Google Maps Night Mode: tonal areas.
- Mapbox dark-style patterns: road hierarchy by lightness.
- Editorial travel and architecture sites: monochrome, whitespace, a serif display face over a grotesk.

**Brand:**
- New walker mark: a 24-unit grid with uniform 2.1 round strokes, `currentColor`, legible at 14 px.
- `brand/` holds the mark, dark and light lockups, and full-bleed and light icons.
- Header lockup is "STROLLANE · NYC": one line, never truncated, separate from the menu button.
- Favicon, Apple touch icon, 192/512 and a maskable 512 icon are now a black tile with the white walker.

**Tokens:**
- Neutral: `#0B0B0B` / `#171717` / `#242424`, text `#F5F5F2` / `#A8A8A5`, hairline `#2E2E2E`.
- `--accent` warm white for the primary action.
- `--signal` lime only for the live position, the active navigation step and AR guidance.
- Radius scale 6/8/12/16/20 and spacing 4/8/12/16/20/24/32.
- Type: DM Sans for the UI; Instrument Serif for display and headlines (desktop hero, route title, the phone request
  question); full fallback stacks.
- 108 lime shades → warm whites, and 566 tinted greys → neutral, all at the same lightness.

**Components:**
- Primary action: white with black type, no glow. Chips: 8 px hairline.
- Results metrics sit on hairlines.
- Menu rows are text + a quiet second line.
- One line-icon set (locate, legend, reset, layers, map style, menu, mic, swap).
- Map controls share one 44 px, 12 px-radius style. On phones the zoom buttons give way to pinch + compass.

**Map:**
- Warm-grey dark cartography over the same CARTO tiles: land < minor < secondary < primary < motorway by lightness, a
  cool water step, quieter labels.
- **Light map** (☰ › Map, or the desktop map tool) uses the same tiles and data with only paint changes, so routes and
  scores are identical.
- Route: warm white on a dark casing with direction chevrons; it inverts in the light map. Alternatives are dashed grey.
- Start: a hollow ring. Destination: a solid bullseye.
- Live position: the signal colour, a white ring, an accuracy halo and a heading beam; grey when uncertain.
- Buildings use a neutral height ramp, with a light-map variant.
- Experience-score streets use one amber ramp, so they can't be confused with the white route.

**Phone:**
- From and To are two rows with the same marks as the map, plus Edit and ⇅ swap. Swap is also on desktop.
- "Show the whole route" frames the route between the request card and the sheet.

**Tests:**
- New `tests/mobile-v2/design-system.js`: 25/25.
- `tests/urban-style.test.cjs` rule updated: the route is now the only warm-white line (was lime).
- **REAL DEVICE VERIFICATION REQUIRED** for Home Screen icon rendering and daylight readability of the light map.

## Round 8: AR walking view + 3D route preview (learned from Google and Apple)

**What the reference products do, and what STROLLANE took from them:**

| Reference | Pattern | In STROLLANE |
|---|---|---|
| Google Maps Live View | big arrows on the street; built for glances; safety prompt | chevrons on the ground toward the route ahead; turn pin at its real bearing and distance; one-time "look up / watch for traffic" notice; after 25 s a reminder to lower the phone |
| Apple Maps AR walking | raise to view, lower for the map; arrows grow and glow near the turn; battery note | Raise to View (lowering always returns to the map; the setting, under More, decides whether raising re-opens AR); camera parked 60 s so raising again is instant without a new prompt; arrows brighten within 30 m; "now" banner within 10 m; battery note |
| Live View street labels | labels never collide | turn and stop labels placed nearest-first and pushed apart; kept between the instruction card and the bottom bar |
| Google Immersive View for routes | preview the route in 3D before you go | "Preview walk in 3D": first-person fly-through of the real route through the 3D city, with play/pause, scrubbing and 1×/2×/4× speed (desktop too) |

**How it works on the web:**
- iPhone Safari and Home Screen apps have no WebXR, so the AR view uses the rear camera (`getUserMedia`), GPS and the
  compass (`webkitCompassHeading`, with iOS motion permission requested from the tap).
- The compass is low-pass filtered.
- GPS and compass error are shown honestly, with hints when either is weak and a figure-8 calibration hint.
- The camera is released on Map view, on exit, and when the app goes to the background.
- No frames are captured or sent.

**Smaller fix:** route POI dots changed from violet to warm cream, to match round 7.

**Tests:** `tests/mobile-v2/ar-preview.js` 33/33, using Chromium's fake camera and synthetic compass/tilt events with
real routing and the nav engine. **REAL DEVICE VERIFICATION REQUIRED** for the camera field of view, magnetometer
error and iOS permission prompts.

## Round 7: map palette v2 (from reference dark maps)

**Feedback:** the legend's green and purple looked cheap.

**Diagnosis on the live map:**
- Parks were filled with saturated categorical green `#008300`.
- Historic districts and landmark lots were violet `#9085e9`.
- The 311 noise heatmap (mauve → rose) laid a pink-purple haze over Midtown.
- Ten categories of translucent cluster rings, each with a number in its series colour, stacked into a coloured fog.

**References:**
- Google Maps Night Mode: parks `#263c3f` on a `#242f3e` base, i.e. a tonal shift, not a hue.
- Mapbox cartography guidance: a neutral base, with colour reserved for data; background features muted.
- kepler.gl: low-contrast base maps that recede behind the data.

**Changes:**
- **Areas are tonal, not saturated.**
  - Parks: deep moss `#0f2018` with a fine sage edge.
  - Historic districts: a brass dashed hairline with no fill.
  - Landmark lots: a 9 % brass wash.
- **Point palette rebuilt in OKLCH** at one lightness band, with no violet:
  - azure, tangerine, sage, sky, raspberry, brass, teal, coral;
  - dataviz validator on black: lightness, chroma and contrast PASS; adjacent normal-vision ΔE ≥ 17.8; CVD ΔE 7.0
    (warn band, legal with the text legend and labels on tap).
- **Clusters are crisp solid dots**, small at city zoom and growing with zoom; a black ring separates neighbours.
  Street and building records stay faint. Counts are neutral text, from z14 only.
- **Noise density** is a faint cool glow (one hue, brighter = denser).
- **Expressway and speed-limit lines** are neutral graphite instead of salmon.
- SW cache `strollane-shell-v10`.

## Round 6: black tech theme (UI + map)

**Brief:** optimise the visual expression and colour of both the interface and the map, on a black background in a
tech style.

**Interface:**
- **Tokens:** pure black `--bg #000`; cool graphite surfaces `#07080a` / `#0b0d10` / `#12151a` and hairline
  `#1f242c`.
- **Recolour:** all 286 ink-green-tinted greys in `styles.css` were recoloured to neutral graphite at the same
  lightness, so the hierarchy is unchanged.
- **Accents:** the brand lime stays for the primary action and the selected route; electric cyan `#45d4e6` is the
  secondary signal.
- **Request card:** the one bold element. It is black glass with a lime → cyan light edge and a lime focus ring on
  the input.
- **Header:** black frosted glass.
- **Fix:** MapLibre attribution links were dark ink, which was invisible on black.

**Map:**
- **Basemap:** CARTO dark-matter re-tinted to pure black land, deep navy water and cool graphite roads, brighter by
  road class.
- **Data categories:** a new categorical set, validated with the dataviz palette validator on black:
  - adjacent-pair colourblind ΔE ≥ 8.4;
  - normal-vision ΔE ≥ 19.3;
  - all colours ≥ 3:1 contrast.
  Street infrastructure and building records stay neutral so they recede.
- **Clusters:** shrink at city zoom (radius ∝ zoom), so ten categories no longer stack into a field of overlapping
  rings.
- **Buildings:** the height ramp is cool graphite → slate.
- **Other layers:** start marker cyan; the route halo and point strokes are black.
- **Meta and versions:** `theme-color` and the manifest colours are `#000`; asset versions are bumped; SW cache
  `strollane-shell-v9`.

## Round 5: the real root cause of the iOS Home Screen bands — document height

**Evidence (real iPhone 17 Pro Max, round-4 build, screenshot at 12:09):**
- Still 0 → 894 pt of page, then a flat strip from 894 to 956 pt.
- The round-4 fade made the dark area at the bottom taller, not smaller.
- At the top, the status bar plus the opaque header formed a 110 pt solid band.
- The Legend chip floated in the middle of the left edge.

**Root cause.** iOS 26 Home Screen apps with `viewport-fit=cover` + `black-translucent` (WebKit 301108 / 301994)
shorten the viewport by the status-bar height **only while the document is no taller than that short viewport**.
- The frappe-ui team measured this in the iOS 26.2 simulator (frappe-ui #1284/#1289). Our phone CSS pinned
  `html, body { height:100% }`, so the document was always exactly the short height, and iOS kept it short.
- Round 2 stretched a fixed element and round 4 blended the edge. Neither changes the *document* height, so neither
  could work.
- This also matches our round-2 evidence: content inside a fixed element below the short edge was never drawn.

**Fix:**
- `styles.css`: in Home Screen mode, make the document at least screen-tall. The rule applies under
  `@media (display-mode: standalone)` and to `html.ios-standalone`, set by an inline head script before first
  layout:
  ```css
  html{min-height:min(100lvh,calc(100% + var(--sat)))}
  ```
  `min()` caps it at the screen, so once iOS gives the full viewport there is nothing to scroll. With an opaque
  status bar the inset is 0 and the rule computes to 100%. Safari tabs, Android and desktop don't match.
- Removed the round-4 fade band. The strip detector stays only as a fallback: `--sab: 0`, plus diagnostics.
- Translucent, frosted header (alpha .72 → .5 with blur), so the map continues under the status bar and the header.
- Legend chip moved to the bottom-left corner, level with the map attribution button in the bottom-right corner.
- Diagnostics now also show:
  - the viewport at launch and the viewport now;
  - the html height, min-height and scrollHeight;
  - `100lvh` in px.
- `styles.css?v=43`, `mobile-ui.js?v=19`, SW `strollane-shell-v8`.

**REAL DEVICE VERIFICATION REQUIRED.** Chromium cannot reproduce how iOS decides the viewport size. The fix is
verified by others in the iOS 26.2 simulator only.

## Round 4: the iOS Home Screen bottom strip — root cause and fix

**Evidence.** The real screenshot came from an iPhone 17 Pro Max Home Screen app running the deployed round-3
build (`c7a7888`), 1280×2781 px, which is 2.909 px per point.
- From 0 to 895 pt, the page paints normally: map, header and controls.
- From 896 to 956 pt (61 pt), the screen is one perfectly flat colour, rgb(7,18,20), with a standard deviation of 0.
  That equals the page background `--bg` #081114.
- Round 2 placed the map footer (with its attribution text) inside that band. It is **not visible** on the device.
- The status-bar area, rgb(12,22,24), already matches the header, rgb(13,24,26), so the top is continuous.

**Root cause.** In a Home Screen web app with `apple-mobile-web-app-status-bar-style: black-translucent`, iOS 26.1+
does three things:
- it reports a viewport shortened by the status-bar height (`innerHeight` = 894 on a 956 pt screen);
- it shows the page only inside that viewport;
- it fills the rest of the screen with the page background colour.

This is WebKit bug 301994. It was reopened and still reproduces on iOS 26.5 and the 27 beta. Content cannot be drawn
into the strip, and no CSS or JS workaround is known: `100vh`, `100dvh`, `100lvh`, `screen.height` and
`position:fixed; bottom:0` all stop at the viewport edge. The strip is therefore **not a layout bug in our page**.
Round 2's compensation (`--vgap`, extending the shell by the measured difference) was based on the wrong assumption
that the strip was drawable. All it did was move bottom UI out of sight.

**What the page controls, and what round 4 does:**
- **Reverted the round-2 `--vgap` compensation** in `styles.css` and `mobile-ui.js`. The shell is `position:fixed;
  inset:0` again, so the map fills exactly the drawable viewport, and its canvas is re-measured on resize,
  orientation, pageshow, visibility and visualViewport changes.
- **Strip detection.** `detectIosSystemStrip()` in `mobile-ui.js` checks for `navigator.standalone === true`, which
  is iOS-only, and a 40–80 pt difference between the screen and the viewport. When both hold, it adds
  `html.ios-system-strip` and records the size in `data-ios-strip`. Nothing changes in a Safari tab, on Android or on
  desktop, or once Apple fixes the bug, because the difference then disappears.
- **In that mode:**
  - `--sab: 0`, because the home indicator lies inside the system strip, so a second 34 pt inset would only waste
    map space;
  - the map footer fades into exactly `--bg`, which is the colour iOS uses for the strip, so map and strip read as
    one edge instead of a hard black band;
  - the MapLibre controls sit above that fade.
- **Diagnostics.** Tap the logo 5 times, or open `?debug=layout`. The panel now reports `iOS system strip detected:
  N pt` and draws a red line at the bottom of the page's viewport. A real-device screenshot then shows directly where
  iOS stops drawing the page.
- `styles.css?v=42`, `mobile-ui.js?v=18`, service worker cache `strollane-shell-v7`.
- No per-device pixel values and no solid cover layers. All 12 dimensions, routing, GIS, navigation and desktop are
  unchanged.

**What is still not possible from the page:** painting map pixels into the bottom 61 pt of an iOS 26.1+ Home Screen
app. **REAL DEVICE VERIFICATION REQUIRED** to confirm that the fade blends with the strip on the device.

## Round 3: hidden sheets after viewport changes (found on the live site)

The production check of round 2, done on the live GitHub Pages URL in a real browser, found that the hidden bottom
sheets showed a dark band at the bottom of the home screen whenever the viewport grew after load. A hidden sheet was
pushed down by a pixel value measured once at load, and only the open sheet was re-measured on resize. This can
happen on an iPhone with rotation, Safari's toolbars, or the Home Screen viewport settling.

Fix (`mobile-ui.js`): hidden sheets use `translateY(calc(100% + 40px))`, which is relative to their own height, so it
stays correct at any viewport size. Placing a sheet that wasn't on screen happens without the slide animation, so
sheets no longer sweep across the screen after a rotation. Regression test: `tests/mobile-v2/ios-standalone-gap.js`
now loads at one size and then resizes / rotates; it passes 28/28. Service worker cache `strollane-shell-v6`.

## iPhone Home Screen app — bottom-gap fix, round 2

**Measured root cause.** From the real iPhone 17 Pro Max screenshots (440×956 pt): with the previous code the
map/shell ended at ≈895 pt, i.e. 61 pt above the screen bottom, with a 120 pt header. In a Home Screen app with the
`black-translucent` status bar, WebKit draws the page from the top of the screen but reports a layout viewport that is
shorter by the status-bar height (innerHeight / `100%` / `100dvh` / `position:fixed; inset:0` = 956 − 62 = 894). The
round-1 fix sized the shell to that viewport, so it still ended 62 pt short. In the original code, the inset was
also subtracted a second time, which gave the ≈121 pt gap in the first screenshot. A Chromium simulation of
exactly this viewport reproduces both real screenshots: the map/shell ends at 894 and the header bottom is at 120.

**Fixes**
- **Bottom gap.** `mobile-ui.js` measures the missing strip (screen height − `innerHeight`) only in an iOS Home Screen
  app (`navigator.standalone`, which is iOS-only), and only within the status-bar range (1–80 pt). It exposes the value
  as `--vgap`. The shell is `height: calc(100% + var(--vgap))`, and bottom-anchored fixed layers (sheets, toast,
  install banner, modal) are moved down by the same amount. On a correct viewport the gap measures 0, so nothing
  changes; Android and desktop are never affected.
- **Header:** 48 pt of content below the status bar (was 58). The menu keeps a 44 pt tap target.
- **Request card:** tighter padding; 44 pt input and button heights. The map footer is a transparent fade, so the map
  is visible to the bottom edge.
- **Map labels on phones:** per-category cluster count numbers appear from zoom 13 up. Cluster rings, data,
  tap-to-expand and desktop are unchanged.
- **Toast:** can be tapped away on phones; it still auto-hides after 4.8 s. The street-data disclaimer also stays in
  the map legend and the Data panel.
- **Diagnostics:** on a real device, open `?debug=layout` or tap the logo 5 times. The panel prints the real
  `innerHeight`, `visualViewport`, `screen`, safe-area insets, `--vgap`, the shell / map / canvas rectangles and the
  remaining gap below the map.
- **Service worker** cache: `strollane-shell-v5`.

## iPhone Home Screen app — full-screen shell fix (round 1)

Reported on a real iPhone 17 Pro Max opened from the Home Screen: the map stopped short with a black band at the
bottom, and the STROLLANE header sat under the status bar, covered by the request card. Safari tabs looked fine.

**Root cause** (this was not a generic `100vh` problem). The page uses `viewport-fit=cover` with the
`black-translucent` status bar, so a Home Screen app draws under the status bar and `env(safe-area-inset-top)`
is about 47–62 pt; in a Safari tab it is 0, which is why the tab looked fine.
1. The phone header had `height:58px` plus `padding-top:env(safe-area-inset-top)` with `box-sizing:border-box`. The
   inset (~62) was larger than the header, so the header could not grow: the brand spilled down, the map started at
   58 px, and the request card was drawn over the brand.
2. The map area was `height:calc(100dvh - 58px - env(safe-area-inset-top))`, which subtracted the inset a second time
   although the header never grew. The map ended about one inset short of the bottom edge: the black band.
3. Live navigation hid the header, but its instruction card was `top:10px` and its bottom bar `bottom:12px`, so in
   Home Screen mode they would sit under the Dynamic Island and the home indicator.
Not involved: there is no `transform: scale()`, no fixed-size phone frame, and no JS viewport arithmetic. The
service worker uses network-first for the page and versioned assets, and the cache was bumped to
`strollane-shell-v4`. MapLibre is not resized by our code on iOS viewport changes, so explicit `map.resize()` hooks
were added.

**Fix (phones ≤740 px)**
- **App shell:** `.site-shell` is one fixed full-screen layer (`inset:0`). The MAP is the full-screen base layer,
  from the top edge to the bottom edge. The header, request card, map controls and navigation are overlays. No
  `100vh`/`100dvh` arithmetic is left in the phone layout.
- **Insets:** they go through `--sat/--sab/--sal/--sar` (= `env(safe-area-inset-*)`).
  - The header height is `58px + inset`, and the request card sits below it with fluid `clamp()` spacing.
  - The map footer and MapLibre's own controls sit above the home indicator.
  - A full sheet stops below the header.
  - Navigation clears the Dynamic Island and the home indicator.
  - Left/right insets are respected in landscape.
- **Map controls:** the right edge keeps GPS and Urban Data (44 px, 8 px apart, stacked above zoom). Reset view and
  the legend toggle moved into the ☰ menu; no function was removed.
- **Viewport changes:** `map.resize()` runs on `orientationchange`, `pageshow`, `visibilitychange` and
  `visualViewport` resize (keyboard, rotation, returning from the background).
- **Status bar:** `black-translucent` is kept on purpose. It is what makes the dark map run under the status bar
  (the full-screen look); `default` would add a separate light status-bar strip.
- **Also fixed:**
  - Tablet / landscape phone (741–1060 px): the off-canvas results drawer was positioned against the page, so the
    page could scroll sideways by ~355 px. It is now anchored to `.app-layout` and clipped.
  - The Plan/Results drawer buttons had been unwired at those widths since the first mobile pass, so the results
    drawer could not be opened. The original toggle behaviour is restored there.

Files: `styles.css`, `mobile-ui.js`, `index.html` (menu entries, cache-busting), `sw.js` (cache v4), new
`tests/mobile-v2/iphone-shell.js`, `tests/mobile-e2e.spec.js` (tablet overflow test enabled; it is no longer skipped).

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
