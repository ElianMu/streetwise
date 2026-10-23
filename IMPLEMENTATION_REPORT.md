# Implementation and acceptance / 修改与验收说明

## Completed code / 已实现代码

- One MapLibre instance; Navigate / Explore Urban Data modes and exact 12-name registry.
- Independent dimension render layers, raw-vs-section-evidence-vs-validated-score selector, data legend, source/year limitations, pilot boundaries, route summary, street and POI queries.
- Complete bounded live source scans and bundled real Midtown snapshot. Official tree-source replacement fixes corrupted mirror records.
- Nature and Architecture section calculations, shared map/profile data and actual candidate reranking. Missing score fields remain NULL.
- Manual preference sliders request new routes and observations. Follow-up requests preserve camera. Same best geometry gets an explanation.
- GPS requesting/denied/unavailable/timeout/insecure/stopped states; foreground position tracking and bounded off-route replanning when GPS is the start.
- Existing AI input, server, route cards, route comparison, weather, POIs, centerlines and Kepler export workflow retained.
- Kepler remains an external research workspace. Added computed-section export; no second unsynchronized embedded map, no claim of an existing Kepler component or saved Kepler configuration (none was included in the ZIP).

## Acceptance status / 验收状态

| Requirement | Status and evidence |
|---|---|
| Dual mode / 12 exact names | DOM/state tests passed |
| Kepler preserved | Existing launch and GeoJSON export retained; section export added |
| Independent raw / evidence / routes / POIs | Implemented; browser rendering acceptance pending |
| True street scores | Two raw proxies computed; **0/12 calibrated 0–100 scores** |
| Map/profile consistency | Same section objects and weighted aggregate; real-response DOM test passed |
| Preference-driven geometry refresh | Replanning hook tested; real Valhalla responses independently verified; no global edge optimizer |
| Multiple route choice | Existing cards and map handlers retained and linked to section data; visual click acceptance pending |
| GPS permissions | Denied and timeout tested with test-only geolocation stubs; device acceptance pending |
| No fabricated missing data | NULL/buffer/pagination tests; no generated heatmaps |
| Desktop/mobile | Responsive CSS implemented; **actual browser/touch acceptance not completed** |
| Existing features | Eight server tests passed; DOM tests cover key panel and ranking behavior; full regression cannot be asserted |

## Real verification data

`data/pilot.json`: 667 street records; 3,177 official tree records (3,025 Alive); 186 landmark parcel records. 477 centerline parts remain after complete-buffer screening. Bounds: longitude −73.992 to −73.970, latitude 40.749 to 40.769. This rectangular data-query envelope is not a borough boundary or a claim of full Manhattan scores.

Three real Valhalla responses, retrieved in this task for the same Bryant Park–Rockefeller Center endpoints:

| Route | Distance | Time | Nature exposure | Architecture exposure |
|---|---:|---:|---:|---:|
| Direct | 0.949 km | 11.45 min | 174.75 records/km | 36.84 parcels/km |
| Via Times Square | 1.510 km | 18.20 min | 89.69 records/km | 21.10 parcels/km |
| Via NYPL | 1.132 km | 13.60 min | 171.25 records/km | 42.37 parcels/km |

These are recorded verification observations, not hardcoded production UI results. Live requests can change. They demonstrate meaningful different geometry/exposure and a tradeoff: the direct route has higher Nature exposure in this pilot, while NYPL has higher Architecture exposure. Original route lengths/time come from Valhalla; exposure lengths use the documented local metric approximation.

## What is not finished / 尚未完成

- Human-experience calibration and defensible 0–100 scores for Nature / Architecture.
- Data acquisition and models for the remaining ten dimensions.
- Complete Manhattan scoring and precise OSM graph-edge IDs/cost optimization.
- Weather-aware indoor/covered route optimization. Weather remains context; no invented rain protection.
- Turn-by-turn, voice, background GPS, device navigation acceptance.
- WebGL/map-rendering and mobile visual acceptance: the runtime blocked browser startup (`socket() ... Operation not permitted`). This is distinct from the passed DOM/state checks.

## Modified / added files

Modified: `app.js`, `index.html`, `styles.css`, `STREETWISE_single_file_demo.html`, `README.md`, `METHODOLOGY.md`, `CODEX_NEXT_STEPS.md`, existing browser test scripts.

Added: `experience-core.js`, `center-map.js`, `START_HERE_MAC.command`, this report, `data/` snapshots/reports, `scripts/fetch_pilot.py`, `scripts/build_demo.py`, `tests/spatial.test.cjs`, `tests/real-route.test.cjs`, `tests/dom.test.cjs`.

`server.py` and the existing two-panel structure were retained. For the manual test sequence, use README steps 1–10. Do not mark all acceptance criteria complete before the remaining browser/device/research checks.
