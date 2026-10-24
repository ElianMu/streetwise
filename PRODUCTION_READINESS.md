# Production readiness audit — 2026-10-24

No UI styles or map providers were changed. This is not a production release certification.

| Category | Status | Evidence | Remaining issues |
|---|---|---|---|
| Python tests | PASS | 163 tests, full discovery using tools venv | Existing ResourceWarnings about file/socket cleanup |
| JavaScript tests | PASS | Eight standalone scripts and jsdom integration exit 0 | Network failures are deliberately mocked in DOM tests |
| Browser routing pipeline | PASS | Chromium: recorded real routing response, explicit 30-minute limit, follow-up 35-minute request | Fixture-backed, not live AI or production |
| Map services | PASS | MapLibre JS, CARTO style and representative Manhattan vector tile HTTP 200 | Does not establish rendered desktop/mobile interaction |
| 13 experience maps | PASS | DOM loops all 13 views, checks score-property mapping and inspector; >10,000 real segments, scores null or 0–100 | Desktop 1440×900 and mobile 375×812 Chromium each timed out after 45 seconds waiting for map layers; rendered interaction BLOCKED |
| AI route recommendation | BLOCKED | Local engine and interpretation mocks pass; official-menu evidence gates item confirmation in recommendation code | No OPENAI_API_KEY or commercial providers; live pizza/menu verification not performed |
| Urban data layers | PASS | Geographic suite, catalog/tiles, spatial reference tests, DOM toggles and route counts | Live map performance/visual density unverified |
| GPS navigation | BLOCKED | 14 replay tracks pass; watchPosition/clearWatch, accuracy and reroute logic implemented | Physical mobile movement, permissions, background/foreground transitions unverified |
| GitHub Pages | BLOCKED | HTTPS CONNECT proxy 403 for elianmu.github.io | Origin status, CORS and refresh behavior unknown |
| Render backend | BLOCKED | HTTPS CONNECT proxy 403 for streetwise-api.onrender.com | No Render API credential; deployment configuration not present in checkout |
| Production deployment | BLOCKED | No deployment performed | GitHub API denied; no publish tool; production validation outstanding |

## Fixes

- DOM test now awaits route-summary work and the next event-loop turn before closing jsdom. Its original assertions are retained; unhandled rejections still fail Node.
- Browser pipeline loads current application dependencies, uses real Response mocks, and explicitly sets its scenario's time budget instead of depending on changing UI defaults.
- OpenAI key is trimmed on startup; embedded whitespace/control/non-ASCII bytes are rejected before constructing headers. Regression test verifies no network request occurs and no key is returned.

## Environment and deployment findings

Python standard-library server binds 0.0.0.0 and honors PORT; startup uses STREETWISE_REFRESH_DAYS=0 to preserve bundled snapshots. Frontend selects the existing Render URL only on elianmu.github.io. API CORS allows that exact origin and OPTIONS. No Render blueprint or GitHub Actions workflow exists in the checkout; external dashboard settings cannot be inferred from this absence. Existing server is a ThreadingHTTPServer development server, without production process supervision or general API rate limiting in this checkout; production operational hardening remains unverified.

Git read authentication succeeds through the platform proxy. GitHub CLI authentication/API access does not: Git reads do not establish API or push permissions. OPENAI_API_KEY, Google Places, Yelp, Foursquare and Render API variables were checked by presence only and are absent. No secrets were printed or added. A tracked-file scan found one candidate in tests/test_interpret.py, confirmed to be a synthetic scrub-test string; this is not an exhaustive secret-history audit.

The saved environment draft retains existing allowlist entries and adds elianmu.github.io, streetwise-api.onrender.com and api.github.com for production checks. Draft saving is confirmed; runtime application and publication are separate. The available tools cannot publish the environment.

Actual production end-to-end tests (desktop/mobile map interactions, route comparison, live POIs, GPS completion, refresh and network interruption) remain BLOCKED. Replay/DOM results must not be presented as real-device navigation or production validation. Unknown business item availability is explicitly not a confirmed match; recorded data is not a current inventory.
