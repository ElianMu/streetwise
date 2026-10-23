# Spatial evidence methodology / 空间证据方法

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
