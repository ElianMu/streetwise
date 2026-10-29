# Running and Testing the Mobile-First Build

Nothing in this pass touched deployment config, the production API host, or the
GitHub Pages site. This is a local-code change on `feature/mobile-first-pwa`,
**not deployed**. Deploying is the same process the project already uses
(`DEPLOYMENT.md`); this file only covers running and testing what's on this branch.

## 1. Run it locally

```bash
cd STREETWISE_NYC_v04
git checkout feature/mobile-first-pwa
python3 server.py
# or: bash START_HERE_MAC.command
```

Open **http://127.0.0.1:8080**. No `OPENAI_API_KEY` is required to see the mobile UI
and generate routes — without it, the natural-language planner falls back to the
existing, honestly-labelled "LOCAL PREVIEW" interpreter (unchanged behavior; see
`README.md`).

Resize the browser window (or open DevTools device toolbar) to ≤740px width to see
the new bottom-sheet shell; above that it's the unchanged tablet/desktop layout.

## 2. Test it on your iPhone, on the same Wi-Fi

1. Find this Mac's LAN IP: `ipconfig getifaddr en0` (Wi-Fi) or check System Settings
   → Wi-Fi → Details.
2. `python3 server.py` as above (it listens on all interfaces, not just localhost).
3. On the iPhone, open Safari to `http://<that-ip>:8080`.
4. This works unmodified because of the existing `api-config.js` design: a non-
   `elianmu.github.io` hostname uses a relative `/api/...` base, which `server.py`
   serves itself on the same origin — no CORS, no config needed.

If your Mac's firewall prompts to allow incoming connections for `python3`, allow it;
otherwise the phone will time out connecting.

## 3. What to actually check on the phone

- Load the page: map should render full-screen with the collapsed "Plan your walk"
  sheet peeking at the bottom (handle + label), not a blank screen or a desktop-
  shrunk layout.
- Drag the handle up: sheet should follow your finger smoothly with no map-drag
  interference; release should snap to the nearest of collapsed/half/full.
- Scroll the open form: should scroll normally without the sheet closing.
- Tap **Plan My Walk**: a route should appear on the map and the sheet should
  auto-switch to Results.
- Tap **Start Navigation**: should go full-screen (topbar, sheet and the old
  Plan/Results buttons should all disappear — this is the pre-existing `nav-mode`
  behavior, now confirmed to still work with the new sheet in place).
- Rotate the phone, back out of navigation, check nothing is left in a stuck state.
- **This is exactly the device/sensor testing this session could not do** — GPS
  accuracy, compass heading, voice prompts, Wake Lock, and Add-to-Home-Screen all
  need a real device. See `MOBILE_TEST_REPORT.md` §4 for the full list of what's
  still unverified.

## 4. Add to Home Screen (once you've generated at least one route)

- **iOS Safari:** the in-app banner will show a tip; or manually: Share icon →
  "Add to Home Screen".
- **Android Chrome:** the in-app banner's **Install** button triggers the real
  Chrome install prompt; or manually: ⋮ menu → "Install app" / "Add to Home screen".

## 5. Deploying (unchanged process — not done in this session)

This session made **no production changes**: no deploy, no change to
`https://elianmu.github.io`, no change to the Render API, no change to
`server.py`'s CORS allow-list or `api-config.js`'s host detection. When you're ready
to ship this branch, the existing process in `DEPLOYMENT.md` applies unmodified —
merge to `main` and push GitHub Pages as usual; the Render backend needs no
redeploy since `server.py` wasn't touched.

## 6. Rolling back

Nothing was deployed, so there is nothing to roll back in production. Locally,
`git checkout main` (or delete the branch) fully reverts every file this pass
touched; the three new files (`mobile-ui.js`, `pwa-register.js`, `sw.js`) simply
don't exist on `main`.

If a Service Worker ever does get installed on some other deployed origin while
testing this branch (e.g. if you test against a `github.io` preview) and you want to
remove it: DevTools → Application → Service Workers → Unregister, or visit the site
and run `navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r =>
r.unregister()))` in the console. `sw.js` itself also self-cleans old-named caches
on activate, so a simple re-deploy under the same cache name is enough in the normal
case.
