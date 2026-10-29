# PWA Implementation

## What existed before this pass

`site.webmanifest` (name, icons at 16/32/192/512, `display: standalone`, theme and
background colors matching the app), `apple-touch-icon.png`, and the Apple PWA meta
tags in `index.html` (`apple-mobile-web-app-capable`, status-bar style, etc.) were
**already correct** — read and left unchanged. There was no Service Worker and no
install-prompt handling anywhere in the project.

## What was added

### `sw.js` — app-shell cache only

A single cache (`strollane-shell-v1`). On every `fetch`, the worker decides per
request:

```
not same-origin                → do not intercept at all (MapLibre CDN, CARTO/OSM
                                  tiles, Open-Meteo, Overpass, the Render API)
/api/*                         → do not intercept (always live — routing, weather,
                                  places, menu verification must never be served
                                  stale or fake)
/data/*                        → do not intercept (large GIS/urban JSON — loaded on
                                  demand by the app's own code, never shipped as
                                  part of the installable shell)
POST (any path)                → never touched (route planning, menu checks, etc.)
navigation request (the HTML)  → network-first, falls back to the last cached copy
                                  only if the network fails; always caches the fresh
                                  copy when online
everything else, same-origin   → cache-first, falls back to network and caches the
                                  result
```

The network-first HTML strategy is what prevents the exact failure mode the brief
warned about ("避免旧 JS 与新 HTML 版本不兼容"): the document itself is always fresh
when there's a connection, so it always references the *current* `?v=NN` script
URLs. Those scripts are cache-first, which is safe specifically because they're
already cache-busted by version query strings elsewhere in the project (e.g.
`nav-ui.js?v=30`) — a deploy that bumps a file's version produces a new URL that
isn't cached yet, so it's fetched fresh automatically; there is no SW-side version
number to remember to bump.

On activate, any cache not named `strollane-shell-v1` is deleted (handles a future
rename) and `clients.claim()` runs so an already-open tab picks up the worker
without needing a second reload.

### `pwa-register.js` — registration + a gated install prompt

- Registers `sw.js` on `window.load`, wrapped in try/catch; a failure is logged as a
  warning and does not affect the app (`catch` body says so explicitly, and this was
  exercised for real in this session — see `MOBILE_TEST_REPORT.md` §3, registration
  did fail in the test sandbox and the app kept working normally).
- Chromium: captures the real `beforeinstallprompt` event (`preventDefault()`'d so
  the browser's own mini-infobar doesn't also show), stored until the user taps
  **Install** in STROLLANE's own banner.
- iOS Safari has no `beforeinstallprompt` — there, the banner instead shows a static
  tip ("tap Share, then Add to Home Screen") since no programmatic install exists.
- **Never shown on first load.** A `MutationObserver` on the existing `#navStart`
  button (the same technique `mobile-ui.js` uses, for the same reason: it observes a
  DOM attribute the routing code already toggles, rather than calling into
  `journey.js`/`route-client.js` directly) only reveals the banner once a real route
  has actually been generated — i.e. after the user has had one genuine success
  with the product, matching the brief's "建议用户完成一次路线探索后，再温和展示安装入口."
- Dismissible, remembers dismissal in `localStorage`
  (`strollane.installBanner.dismissed`), bilingual (English/中文 by `navigator.language`),
  and hidden during `body.nav-mode` (added to the same CSS rule that already hides
  the topbar and side panels during live navigation).
- Already-installed detection (`display-mode: standalone` or `navigator.standalone`)
  skips all of this entirely.

## What is explicitly not claimed

- **Offline navigation is not implemented and nothing in the UI claims it is.** The
  cached app shell lets the page itself load with no network (it'll show its own
  honest "offline, reconnect" response for the document if nothing was ever cached —
  see `sw.js`'s navigation fallback), but every route-planning, live-position,
  weather, and places feature still requires a live connection to `/api/*`, exactly
  as before this pass. This matches the brief's explicit instruction not to promise
  reliable offline navigation.
- **Service Worker activation itself was not confirmed working** in this session —
  see `MOBILE_TEST_REPORT.md` §3 for exactly what was and wasn't verified, and why.
  Until that's confirmed in an ordinary browser, treat the caching behavior as
  code-reviewed and syntax-checked, not Tested.
- No change was made to `site.webmanifest`, the icon files, or the Apple meta tags —
  they didn't need one.
