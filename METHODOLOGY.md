# Spatial evidence methodology / 空间证据方法

> **Read this first (updated 2026-11-15).** Everything below "Scope and truthfulness" describes the original **Midtown
> pilot "Street evidence" layer** (`experience-core.js`, `data/pilot.json`): two raw proxies, 75 m buffers, scores NULL.
> That layer still exists in Navigate → *Street evidence*, and the text is accurate **for that layer only**. It is no
> longer how routes are ranked or how the Explore map is coloured. Current scoring is described in the next three
> sections, in `README.md`, `ARCHITECTURE.md` and `DIMENSIONS_MAP_MODE_REPORT.md`.

## One score build for routes and the Explore map (since 2026-11-14)

Routes and the Explore Urban Data map now use the same street scores: build `strollane-12x24-v1+bb10da45e2`
(`scripts/dimensions/` → `data/dimensions/manhattan/`, 20 computed indicators of 24 specified; the canopy and
impervious-surface rasters are not connected, so those two indicators stay N/A). `scripts/transfer_dimension_scores.py`
puts those street scores on the routing edges (`data/pedestrian/edge-scores.json.gz`), using the existing street-to-edge
matching unchanged. The 12 dimensions, their names, order, definitions and the equal-weight rule are unchanged.

Until 2026-11-14 routes used an earlier build (`sw-score-46f39c1c97`, 15 indicators, `scripts/streetwise_indicators.py`).
Compared with it, the unified build adds five indicators: walking distance to seating and ramp coverage (Spatial
Comfort), walking distance to waterfront (Scenic & Visual), walking-network detour (Walkability) and crime-report
proximity (Access & Safety). Share of scored routing edges whose score moved by more than 20 points at the switch:
Spatial Comfort 37 %, Scenic & Visual 19 %, Walkability 13 %, Access & Safety 7 %, Architecture and Nature about 1 %,
the other six 0 %. The route benchmark was rerun on the unified scores (`benchmarks/ROUTE_BENCHMARK.md`): mean gain
+8.4 points for a 3.9 % mean detour (before: +9.5 and 4.3 %); the largest change is Spatial Comfort, +5.8 instead of
+14.2, because with three indicators instead of one there is less to gain by detouring.

**Crossings, park paths and bridges (updated 2026-11-15).** 27.3 % of routable length is not a street segment but a
crossing, park path, bridge or unmatched street, scored from raw values measured directly on the OSM geometry. At the
unification the five indicators the map build added had not been measured on those edges. Four of them now are, by
`scripts/measure_direct_edges.py`, which calls the map build's own indicator functions on the edge geometry with source
snapshots already in this repository: walking distance to seating, walking-network detour, crime-report proximity and
walking distance to waterfront. Before writing anything the script runs the same code on the 10,533 street segments and
compares with the values the map build stored; all four were reproduced (within 1 m, 0.01 ratio units or 1 % for
99.2–99.99 % of segments; the remainder are midpoints that snap to a neighbouring network node because segment
geometry is read back from rounded GeoJSON coordinates).

The fifth, ramp coverage, is **not** measured there and is left absent: it is defined on the LION end nodes of a
street segment, and a crossing or a park path has none. No substitute definition was invented.

What changed for routes: Scenic & Visual, Walkability and Access & Safety now rest on all their indicators on
98.8 % of routable length (before: about 72 %). Spatial Comfort is scored on 98.8 % of routable length (before: 75.5 %),
because park paths now have walking distance to seating; on 31 % it rests on fewer than its three indicators (no
sidewalk record on paths, no ramp coverage on directly measured edges). Quiet & Relax still rests on one indicator
instead of two on 30 % (roadway width is not recorded for paths and some streets). These shares are written by the
transfer into `indicator_basis` in the edge-score metadata, and *Why this route?* states them.

The benchmark was rerun: mean gain +8.3 points for a 4.0 % mean detour over 228 runs (unification: +8.4 and 3.9 %).
By dimension the picture moved more: Spatial Comfort +9.7 (was +5.8), Access & Safety +9.0 (was +11.0), Walkability
+6.0 (was +8.0), Scenic & Visual +2.8 (was +4.4). The three that fell were being helped by the gap: with one
indicator missing on paths and crossings, a detour through them looked better than it measures now.

The transfer was checked against the earlier file: recomputing the earlier edge scores from the earlier street scores
with the same code reproduces 395,828 of 397,680 values exactly; 1,852 differ by 1 point (the matching table stores
overlap lengths to 0.1 m) and none by more (`python3 scripts/transfer_dimension_scores.py --verify-previous`, run on
the earlier file).

## What the route scores are, and are not

Each scored indicator is a 0–100 percentile rank among Manhattan street segments ("lower is better" indicators
reversed); a dimension score is the equal-weight mean of its available indicators; a route score is the length-weighted
mean over the OSM edges the route uses. These are **relative ranks of proxies computed from public records**. They are
not calibrated measurements and have not been validated against how people experience a walk.

All 12 dimensions are offered as walk priorities on the first screen (`walk-presets.js`), ordered by their effect in
the route benchmark. Proxy limits a reader should know for each name:

- **Nature**: density of inventory tree points within 30 m and share of samples beside NYC Parks land. Not canopy
  cover and not shade.
- **Quiet & Relax**: 311 noise-complaint intensity over the last 12 months and roadway width. Complaints depend on who
  calls 311; neither indicator is a sound level.
- **Scenic & Visual**: proximity to OSM viewpoints, public art, fountains, memorials and monuments. It does not measure
  whether a street looks nice.
- **Urban Vibrancy**: POI diversity × quantity. At the 36 Manhattan DOT pedestrian-count locations its rank correlation
  with observed people per hour is −0.022 (`data/dimensions/manhattan/manifest.json`; the locations are mostly busy
  retail corridors, so the range is restricted). It is not evidence of how lively a street is.
- **Access & Safety**: pedestrian-injury crash intensity and proximity of reported felonies and misdemeanours. Reports
  depend on reporting and policing; it is not a measure of personal safety.
- **Spatial Comfort**: mapped sidewalk share, walking distance to public seating and curb-ramp coverage. It does not
  measure crowding, shade or surface quality.

*Why this route?* states the indicators behind every priority the visitor picked, so these limits are visible in use.

## Benchmark and validation status

- **Route benchmark** (`benchmarks/route_benchmark.py`, results in `benchmarks/ROUTE_BENCHMARK.md`): shortest route vs
  the preference route vs the next candidate for 19 fixed trips × 12 single-dimension preferences. It reports gains,
  detours, overlap and "same as shortest" as they come out, and asserts nothing about which route is better. It shows
  whether the engine moves its own metric, not whether a walker notices.
- **User validation**: not done. `RESEARCH_PROTOCOL.md` describes the planned before/after-walk study. No user
  feedback has been collected and none is simulated anywhere in this repository.

## Scope and truthfulness

Two calculated raw proxies; zero research-calibrated 0–100 experience scores. The 12 `*_score` properties are always NULL in this release. Candidate match (0–100) is a separate relative comparison among requested routes; it is not an urban quality score. User sliders are importance, never environmental measurements.

## Source screening

- Nature: official NYC Open Data 2015 Tree Census, `https://data.cityofnewyork.us/resource/uvpi-gqnh.json`. Numeric latitude/longitude box and Manhattan `borocode='1'`; stable `tree_id` pagination, count verification and duplicate rejection. Only `status='Alive'` enters exposure counts. Original Alive/Dead/Stump records remain available in the raw layer. No canopy or shade inference.
- Architecture: original project's ArcGIS LPC individual-landmark parcel service retained. Bounded query, object-ID-sorted paging, expected-count verification and deduplication. All 186 pilot records are Designated. It excludes historic districts, non-landmark architecture, building visibility and subjective aesthetic quality. Source observation year unspecified.
- Street geometry: original project's NYC Street Centerline ArcGIS service, Manhattan borough filter. A road centerline is a research display geometry, not proof of pedestrian access. Source observation year unspecified.
- Routes: returned Valhalla pedestrian shapes based on OSM. Never join arbitrary centerline edges into fabricated walkable paths. Weather: Open-Meteo forecast context only. POIs: existing backend's named OSM nodes near the selected route.

The original tree mirror had malformed status fields. This release deliberately uses the authoritative Socrata records instead. The 3,177-record pilot contains 3,025 Alive, 102 Dead and 50 Stump records.

## Geometry and units

Pure computations are in `experience-core.js`. Coordinates remain WGS84 in GeoJSON. Distance uses a local equirectangular metric approximation at latitude 40.76° (x = longitude × 111320 × cos(latitude), y = latitude × 111320). This is explicitly an exploratory local approximation, not survey-grade distance or a formal projected CRS analysis. Full-Manhattan production processing should use an appropriate projected CRS and spatial index.

For a line section of length L km:

- Nature raw exposure = number of unique living tree records within 75 m / L.
- Architecture raw exposure = number of unique LPC parcels within 75 m / L.
- Polygon proximity checks line–polygon intersections, edge distances, interiors, holes and MultiPolygons; not merely proximity to polygon vertices.
- A complete evidence query must cover the **entire 75 m buffer**. Sections within the 75 m query-box margin are excluded or NULL, never silently assigned zero.
- Empty, successfully completed observations yield a legitimate raw zero. Failed or unavailable observations yield NULL.

The 75 m buffer is retained as an **exploratory pilot parameter**, not a literature-validated field-of-view distance or a claim that all dimensions should use the same radius. Other dimensions require their own influence models. No fabricated normalization or percentiles are emitted as calibrated scores.

## Two geometry populations

1. **Explore:** 477 fully covered NYC centerline parts within the real Midtown snapshot. MultiLineString parts are analyzed separately, with IDs `nyc-{sourceID}-{part}`. Centerline parts can include representations with different physical meaning; no citywide reference distribution or 0–100 calibration is derived from these parts.
2. **Navigate:** returned pedestrian route geometry split into sections of at most approximately 80 m while retaining all turns. Stable geometry-derived `walk-{hash}` section IDs and `route_id` link to the returned route. These are **not OSM graph edge IDs**. No claim of exact graph-edge matching or edge-cost optimization is made.

Route exposure = Σ(section exposure × section length) / Σ(section length). Every section must have complete observations for a dimension, or its route aggregate is NULL. Overlapping buffers intentionally repeat environmental exposure across sections; aggregate exposure is not a unique-record total. Whole-route deduplicated counts are displayed separately for continuity with the original UI.

The map uses local terciles of raw records/km solely to color available section evidence. Exact numeric breakpoints are in the legend and change with the analyzed section collection. Colors do not imply cross-neighborhood absolute quality. No-data sections are gray.

## Ranking and replanning

The existing Valhalla waypoint candidate strategy is retained. Manual weight changes and conversational refinements request real pedestrian paths again; they do not just relabel lines. Only expressed Nature / Architecture dimensions with complete route-section aggregates enter candidate ranking. Each is min–max normalized across the candidates; direction is applied separately (`high` or `low`). Importance zero excludes the dimension. All-equal evidence is excluded as nondiscriminating.

Time and detour limits filter feasible candidates first. Step-free/stair avoidance remains blocked without accessibility proof. The existing walking-time tie penalty is retained. This is constrained **candidate reranking**, not a guaranteed global optimum, not 12D edge-cost routing and not a certified accessible route.

The same `route.sections` collection feeds the map, route aggregate and right-panel shared section evidence. Source errors cannot be converted into score zero. Replanning preserves the current view on follow-ups. Identical best geometry receives an explicit unchanged explanation.

## Exact dimension registry

| # | Dimension | This release |
|---|---|---|
| 01 | Architecture | Computed LPC proximity proxy; score NULL |
| 02 | Nature | Computed living-tree proximity proxy; score NULL |
| 03 | Culture | Venue inventory/access model missing; NULL |
| 04 | Quiet & Relax | Noise/time model and inverse conversion missing; NULL |
| 05 | Spatial Comfort | Width, obstruction and crowding data missing; NULL |
| 06 | Urban Vibrancy | Activity model missing; NULL. Higher activity is not universally better; user direction is separate |
| 07 | Food & Retail | Business/opening-hours model missing; NULL |
| 08 | Scenic & Visual | Visibility/perception model missing; NULL |
| 09 | Walkability | Grade, crossing and connectivity model missing; NULL |
| 10 | Access & Safety | Barrier/hazard evidence missing; NULL |
| 11 | Environment | Street-level air/heat exposure model missing; NULL. Weather is context only |
| 12 | Transit Connectivity | Entrances/service-frequency model missing; NULL |

## Validation boundary

Automated spatial checks cover NULL vs zero, duplicate trees, dead trees, polygon crossings and holes, complete buffers, turn-preserving splitting, length conservation, unique IDs and weighted aggregation. Real pilot data and real recorded Valhalla responses are used in separate reproducible checks. DOM/state tests cover preferences, direction, mode, shared data, errors and replanning calls.

These checks establish computational consistency; they do not validate human experience, 75 m perception distance, source positional accuracy, OSM access quality, production browser rendering or real GPS navigation. No consent, itinerary or GPS records are stored by this implementation; external routing/weather/POI services receive the coordinates needed for their requests.
