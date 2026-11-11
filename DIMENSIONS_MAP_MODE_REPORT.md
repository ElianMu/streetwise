# STROLLANE · NYC — Real GIS 12 Dimensions × 24 Indicators + Map Mode

Build `strollane-12x24-v1+bb10da45e2` · 2026-11-10 · Manhattan, 10,533 LION street segments (Midtown pilot: 1,208).

Map Mode ("Explore Urban Data") now colours real Manhattan street segments by **computed** dimension scores. Every
value on the map and in the Street Details panel is read from files produced by the pipeline below. No value is
random, hard-coded, filled in, or carried over from the old proxy file.

## 1. How to run

```bash
pip install numpy pandas scipy shapely pyproj geopandas pytest       # pipeline only; server.py stays stdlib-only
python3 -m scripts.dimensions.build --area midtown                     # pilot
python3 -m scripts.dimensions.build --area manhattan                   # all Manhattan (~20 s)
python3 -m scripts.dimensions.build --area manhattan --only crime_k --force   # recompute one indicator
python3 -m pytest tests/test_dimensions.py -q                          # 19 pipeline tests
python3 -m http.server 8080 &  python3 tests/map_mode_e2e.py           # browser check: map + panel = GIS output
```

Each indicator is a resumable stage cached in `data/dimensions/work/` (git-ignored). Outputs per area:

| File | Content |
|---|---|
| `data/dimensions/<area>/segments.geojson` | LION geometry + `d0…d11` dimension scores, `n0…n11` indicators used, `overall`, `coverage` |
| `data/dimensions/<area>/indicators.json` | raw value + 0–100 percentile of every indicator per segment (fetched by the map on first click) |
| `data/dimensions/<area>/manifest.json` | spec, status/coverage/stats of each indicator, dimension coverage, source QA, versions, validation |
| `data/dimensions/<area>/context_no2.geojson` | DOHMH NO₂ by Community District (area context layer) |
| `data/dimensions/<area>/run_log.jsonl` | run log of every stage |

Segment IDs are identical to `data/manhattan-streets.json` (`MN-` + LION physicalid), so the route engine's data
and Map Mode data join on `segment_id`.

## 2. Pipeline

`Raw sources → clean & validate → EPSG:32618 (metres) → spatial join / buffers / kernels / network distance →
indicator → percentile (comparison area) → reverse "lower is better" → equal-weight dimension mean → GeoJSON → MapLibre`

Code: `scripts/dimensions/` — `spec.py` (the two tables, row by row), `sources.py` (loaders + QA), `geo.py` (vectorised
GeoPandas/Shapely/SciPy primitives), `indicators.py` (one function per row), `scoring.py`, `build.py`.

## 3. Data sources actually processed

| Source (DB column) | Dataset | Records used | Retrieved |
|---|---|---|---|
| LION | NYC Street Centerline, borocode 1 | 10,533 walkable segments; 1,414 expressway/ramp lines | 2026-10-23 |
| LPC | Individual Landmark Lots (Manhattan) | 995 lots (multi-part lots kept whole) | 2026-10-23 |
| Trees | NYC Parks Forestry Tree Points (`hn5i-inap`, structure Full) | 174,207 | 2026-10-23 |
| Parks | NYC Parks Properties (`enfh-gkve`, borough M) | 396 properties | 2026-10-23 |
| OSM | Overpass POIs (amenity/shop/tourism/leisure/historic) | 76,712 | 2026-10-23 |
| OSM walk | OSMnx pedestrian graph | 122,092 edges | 2026-10-23 |
| 311 | Noise complaints, 12 months | 177,034 | 2025-10-23 → 2026-10-23 |
| Sidewalk | Planimetric Sidewalk (`52n9-sdep`) | 9,730 polygons | 2026-10-23 |
| Seats | DOT Seating Locations (`esmy-s8q5`, Manhattan) | 1,194 | 2026-10-24 |
| Ramps | DOT Pedestrian Ramps (`ufzp-rrqu`) | 23,668 | 2026-10-24 |
| NYPD | Motor Vehicle Collisions, pedestrian injury/death, 3 years | 4,204 | 2023-10-24 → 2026-10-23 |
| NYPD + YTD | Complaints Historic `qgea-i56i` + Current `5uac-w243`, felony + misdemeanor, dedup on complaint no. | 171,188 | 2025-01-01 → 2026-06-30 |
| Water | WPAA `388s-pnvc` (Open / Partially Open) + Hydrography `pjs3-c3z5` (rivers, bay) | 42 + 86 polygons | 2026-10-24 |
| MTA | Subway Entrances (`i9wp-a4ja`, entry allowed) | 840 | 2026-10-23 |
| Counts | DOT Bi-Annual Pedestrian Counts (`cqsj-cfgu`), Oct 2024 – May 2026 rounds | 36 Manhattan locations | **2026-11-10** (new) |
| DOHMH | Air Quality `c3uy-2p5r`: NO₂ annual mean 2024, by CD + CD boundaries `5crt-au7u` | 12 districts | **2026-11-10** (new) |
| TNC | Land Cover 2021 raster | **not acquired** — see §7 | — |

The two new sources were fetched through the Socrata API in the desktop browser, because the processing sandboxes
cannot reach `data.cityofnewyork.us`. Both copies were checked against checksums computed from the publisher
response (column sums; vertex counts and coordinate sums). All other sources are the snapshots already in the repo,
downloaded by the existing build scripts.

## 4. Indicator status (Manhattan, 10,533 segments)

| Indicator | Dimension | Status | Segments with value | min / median / max |
|---|---|---|---|---|
| `lpc_k` | 01 Architecture | computed | 100% | 0 / 0.73 / 19.6 |
| `tree_km` | 02 Nature | computed | 100% | 0 / 46.3 / 856.6 trees/km |
| `park_pct` | 02 Nature | computed | 100% | 0 / 0 / 1 |
| `canopy_pct` | 02 Nature | **N/A — source not acquired** | 0 | — |
| `cult_k` | 03 Culture | computed | 100% | 0 / 0.69 / 55.7 |
| `noise_k` ↓ | 04 Quiet & Relax | computed | 100% | 0 / 29.3 / 1,564 |
| `width_ft` ↓ | 04 Quiet & Relax | computed | 89.0% (LION width missing) | 5 / 34 / 85 ft |
| `sidewalk_pct` | 05 Spatial Comfort | computed | 89.1% (N/A on park paths, step streets) | 0 / 0.35 / 1 |
| `seat_access_m` ↓ | 05 Spatial Comfort | computed | 100% | 11 / 207 / 500 m (cap) |
| `ramp_coverage` | 05 Spatial Comfort | computed | 89.9% (N/A without a crossing node) | 0 / 1 / 1 |
| `vibr_idx` | 06 Urban Vibrancy | computed | 100% | 0 / 3.02 / 4.43 |
| `ped_flow_observed` | 06 Urban Vibrancy | **validation only** | 36 count locations | 341 / 2,168 / 5,464 people/h |
| `food_k` | 07 Food & Retail | computed | 100% | 0 / 1.78 / 46.4 |
| `scenic_k` | 08 Scenic & Visual | computed | 100% | 0 / 0.57 / 20.8 |
| `waterfront_access_m` ↓ | 08 Scenic & Visual | computed | 100% | 0.4 / 1,071 / 2,981 m |
| `inter_n` | 09 Walkability | computed | 100% | 0 / 19 / 53 |
| `route_directness` ↓ | 09 Walkability | computed | 99.9% | 1.05 / 1.32 / 3.46 |
| `crash_k` ↓ | 10 Access & Safety | computed | 100% | 0 / 0.66 / 11.5 |
| `crime_k` ↓ | 10 Access & Safety | computed (report proxy, not personal risk) | 100% | 0 / 153 / 2,504 |
| `hwy_m` | 11 Environment | computed | 100% | 0 / 376 / 1,500 m (cap) |
| `impervious_pct` ↓ | 11 Environment | **N/A — source not acquired** | 0 | — |
| `no2_area_context` | 11 Environment | **area context only** (12 CDs, 16.2–25.1 ppb) | not assigned to streets | — |
| `sub_n` | 12 Transit | computed | 100% | 0 / 4 / 91 |
| `sub_m` ↓ | 12 Transit | computed | 100% | 5 / 257 / 1,500 m (cap) |

**20 of 22 scored indicators are computed.** ↓ = lower raw value is better (percentile reversed).

## 5. Dimension coverage

All 12 dimensions have a score on every segment. Two dimensions are **partial** and labelled that way in the map,
legend, tooltip and panel: **02 Nature 2/3** (no canopy) and **11 Environment 1/2** (no impervious; NO₂ is context).
The other 10 are complete (1/1, 2/2, 3/3). Per segment, `n0…n11` record how many indicators entered each score. A
segment where an indicator is missing, e.g. no LION width, is scored on the remaining indicators and shows that
count. A dimension with no available indicator would be `null` (N/A), never 0; this is enforced by tests.

## 6. Validation

* **Front end = GIS output** (`tests/map_mode_e2e.py`, headless Chrome, 11/11 PASS in light and dark themes): all 10,533 × 12 scores in the map
  layer equal `segments.geojson`. Rendered line colours equal the ramp colour of each score (300 features). The
  Street Details panel's raw values, percentiles and dimension scores equal `indicators.json` for 60 segment/dimension
  checks across Nature, Architecture, Access & Safety, Spatial Comfort, Environment and Overall. No JS errors.
* **Pipeline tests** (`tests/test_dimensions.py`, 19/19 PASS): metres in EPSG:32618 vs geodesic (< 0.2%), sampling and
  side offsets, 20/40 m offset shares, nearest-segment tree snapping (corner tree counted once, 80 m floor), Gaussian
  weights and cutoff, polygon kernels, network vs straight-line distance, percentile ties and reversal, NaN never 0,
  validation/context never scored, scores and percentiles recomputed from the published files, honest N/A statuses,
  and `lpc_k` vs an independent brute-force GeoPandas computation.
* **Cross-check with the repo's earlier pure-Python measurement** (Midtown): Spearman ρ ≥ 0.99 for 12 of 15 shared
  indicators. Expected differences: `lpc_k` now uses distance to the lot polygon as specified (0.989), and
  `park_pct`/`sidewalk_pct` use a different sampling scheme (0.968 / 0.917).
* **Observed pedestrian flow vs vibrancy model:** at the 36 Manhattan DOT locations, ρ(people/h, `vibr_idx`) = −0.02;
  in the Midtown pilot (17) it is 0.16. **The POI-based vibrancy index does not reproduce observed foot traffic.**
  DOT sites are all busy retail corridors (restricted range), but this is a real limitation of 06 Urban Vibrancy
  and is reported in the manifest.
* **Existing suites:** `dom.test.cjs` (updated Map Mode section, route-edge inspector unchanged), `food-discovery`,
  `place-cards` and 8 other node suites pass. Python suites: 242 passed; 4 failures are unrelated: 3 use a hard-coded
  hotel check-in date (2026-11-01) that is now in the past, and 1 needs `pyproj` in the test interpreter.

## 7. Not implemented, and why

| Item | Reason |
|---|---|
| `canopy_pct`, `impervious_pct` | The spec requires the **TNC/UVM 2021** land-cover raster. It is not in the repo, and NYC Open Data only publishes the **2017** edition (`he6d-2qns`, 6-in, 1.33 GB zip). Using 2017 would silently change the spec, so both are N/A. To finish: put the 2021 GeoTIFF (Manhattan clip) in `data/dimensions/sources/` and add a rasterio stage (20 m street buffer → class share). |
| `ped_flow_observed` in scores | By design: validation only. Covers 36 mid-block count locations, not streets. |
| `no2_area_context` on streets | By design: kept on Community District polygons; the panel shows the district value as context. |
| Fresh re-download of all sources | Sandboxes cannot reach NYC Open Data / ArcGIS. The repo snapshots (Oct 23–24) were used, with dates recorded per source. `scripts/build_manhattan_streets.py --refresh` re-downloads them where network allows. |
| Route Mode reading new scores | Route Mode is unchanged and still uses `manhattan-streets.json` / edge scores. The new files share segment IDs, so switching the route engine is a separate, deliberate step (it changes route rankings). |

## 8. Interpretation choices (where the table was not explicit)

* `tree_km`: each tree is assigned to its nearest segment within 30 m, so a corner tree is not counted twice.
* Kernel indicators (`cult_k`, `noise_k`, `food_k`, `scenic_k`, `crash_k`, `crime_k`) use the same 40 m samples as `lpc_k`.
* `seat_access_m`, `waterfront_access_m`, `route_directness` use the OSM pedestrian graph's largest connected component.
  The midpoint joins at its nearest node (snap distance added); seats > 100 m from the network are dropped (3 of 1,194).
* Valid waterfront entrance = walk-graph node inside public waterfront space (open WPAA, or a park within 30 m of
  river/bay) and within 60 m of open water. Ponds and reservoirs are excluded. Capped at 3,000 m (no segment reached it).
* `route_directness`: up to 8 destinations (one per 45° sector, nearest to 375 m in a 250–500 m ring); N/A with < 3 feasible pairs.
* `ramp_coverage`: eligible = segment end nodes joining ≥ 3 walkable segments with at least one roadway.
* `ped_flow_observed`: count ÷ period hours (weekday 7–9 AM = 2 h, 4–7 PM = 3 h, Saturday 12–2 PM = 2 h, per DOT readme); median of valid periods.
* Percentiles: ties take the lowest rank (the app's existing rule), computed on the published 3-decimal values so
  anyone can reproduce them from `indicators.json`.

## 9. Map Mode changes

`explore-map.js` (data loader, layers, panel, theme-aware ramp), `explore-analytics.js` (text), `urban-layers.js` (route-edge
inspector reads the legacy file explicitly), `app.js` (one theme hook), `index.html` (scope label, cache-busting), `styles.css`
(theme variables), `tests/dom.test.cjs`.

* 12-dimension selector (+ Overall). Partial dimensions show their `x/y` coverage badge and list their indicators,
  including N/A, validation-only and context-only ones.
* Street segments as one MapLibre line layer (no per-segment DOM). Continuous green ramp that follows the map theme:
  light → dark green on the light basemap (default), dark → bright green on the dark one, so high scores always have
  the most contrast. N/A segments get a separate dashed grey style. `applyMapTheme()` repaints Map Mode on a theme switch.
* Hover highlight + tooltip (score, indicators used). Click → Street Segment Information: ID, name, length, dimension,
  score, raw value and percentile of every indicator, direction, status, method (table text), notes, source, version.
* Environment view adds the NO₂ Community District layer as faint area context.
* Status line: segment count, 20/22 computed, retrieval date, comparison scope, calculation version, build time.
  If only the Midtown pilot exists, the header says "MIDTOWN PILOT ONLY · NOT ALL MANHATTAN".
* Detailed values (2.8 MB) load only on the first click; the map layer itself is 5.2 MB.

Screenshots: `screenshots/map-mode/` (light theme: Manhattan views, Midtown Street Details, Environment + NO₂; plus one
dark-theme Street Details). The offline browser test used a blank basemap because the sandbox cannot reach the CARTO
tiles; the live app shows the normal basemap. `tests/map_mode_e2e.py --theme light|dark` passes 11/11 in both themes.
