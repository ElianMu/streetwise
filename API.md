# STREETWISE · NYC — API and data contracts

All endpoints are served by `server.py` (standard library). Field names below are the shared contract used by
`routing/engine.py`, `route-client.js` (AI Journey, Route Intelligence) and `explore-map.js` (Explore Urban Data).

## Endpoints

| Method | Path | Status | Purpose |
|---|---|---|---|
| GET | `/api/status` | unchanged | LLM availability `{llm, model}` |
| POST | `/api/interpret` | unchanged | Natural-language preferences → weights, directions, limits |
| POST | `/api/pois` | unchanged | OSM POIs in a bounding box |
| POST | `/api/routes` | **new** | Candidate pedestrian routes, scored and ranked |
| GET | `/api/routing/status` | **new** | Network / score versions, counts, coverage |
| GET | `/api/edges/{u-v-key}` | **new** | One Pedestrian Edge Object |
| GET | `/api/segments/{segment_id}` | **new** | One Street Segment Object |
| POST | `/api/navigation/progress` | **new** | Position along a planned route (for future GPS navigation) |

Errors: `400` invalid input, `422` valid input the network cannot satisfy (too far from a path, unreachable,
unknown route), `503` routing data not built. Every error body is `{"error": "..."}`.

### POST /api/routes

```json
{
  "origin": {"lat": 40.7536, "lon": -73.9832},
  "destination": {"lat": 40.7587, "lon": -73.9787},
  "preferences": {"weights": {"Nature": 90, "Quiet & Relax": 90}, "directions": {"Nature": "high"}},
  "constraints": {"max_minutes": 30, "max_detour_pct": 25, "avoid_detours": true, "avoid_stairs": false}
}
```

`weights` keys must be among the 12 dimension names exactly. Only weights > 0 count; with none, all 12 count equally.
Weights describe the user and never change street scores. Response:
`{network_version, score_version, origin, destination, shortest_distance_m, preferences_used, preferences_expressed, routes: [Route], compute_seconds, notes}`.
Routes are sorted by rank; at most one has `recommended: true`, and none if no route meets the hard constraints.

### POST /api/navigation/progress

`{"route_id": "rt-…", "lat": 40.755, "lon": -73.982, "accuracy_m": 8}` →
`{state: on_route|off_route|arrived, distance_from_route_m, progress_m, remaining_m, remaining_min, current_edge_id, off_route, reroute_recommended}`.
Off-route = more than 35 m from the route with a fix of 60 m or better. Re-routing = `POST /api/routes` with the
current position as origin. Routes are kept in server memory (latest 200); this is geometry only, not live tracking.

## Objects

### Street Segment Object (Explore layer, NYC LION)
`segment_id` (analysis ID: `MN-{LION physicalid}` or `MN-{physicalid}-{n}`), `source_segment_id` (LION physicalid),
`lion_part`, `street_name`, `geometry`, `length_m`, `dimension_scores` {12 names → 0–100 | null}, `overall_score`,
`sub_indicators` {dimension → [{key, label, unit, method, source, role, value}]}, `data_sources`,
`data_coverage` {dimensions_available, of: 12}, `score_version`, `data_version`.

Explore reads `data/manhattan-streets.json` directly; its compact keys map to the contract as:
`id→segment_id`, `name→street_name`, `d0…d11→dimension_scores` (order = `metadata.keys`), `overall→overall_score`,
`coverage→data_coverage.dimensions_available`, indicator keys → `sub_indicators[*].value`.

### Pedestrian Edge Object (routing layer, OSM)
`edge_id` (`"{u}-{v}-{key}"`, the full MultiDiGraph identity), `u`, `v`, `key`, `osm_way_ids` (one edge can span
several ways; one way can span many edges), `geometry_index`, `name`, `highway`, `geometry`, `length_m`,
`traversed_length_m` (inside a route), `pedestrian_access` {foot, access, steps, footway, crossing, bridge, tunnel, layer, surface},
`dimension_scores`, `overall_score`, `data_coverage` {dimension → share of edge length scored},
`score_source` (`lion_match` | `direct_osm` | `none`), `match_quality`, `matched_segment_ids`, `lion_match_share`,
`direct_sub_indicators` (raw values when measured directly), `network_version`, `score_version`.

### Route Object
`route_id`, `route_name`, `objective` (`shortest` | `experience` | `experience_balanced` | `alternative`), `origin`,
`destination` (input + snapped edge + snap distance), `geometry`, `ordered_edge_ids`, `edges` [Pedestrian Edge Object,
in order, first/last may be `partial`], `distance_m`, `estimated_duration_min` (4.8 km/h), `detour_percentage`,
`dimension_scores`, `overall_score`, `data_coverage` {by_dimension, mean, low_coverage_dimensions},
`personalized_score` {utility, weighted_experience, travel_cost_penalty, components, formula}, `constraints`
{feasible, violations, avoid_stairs, contains_steps}, `rank`, `recommended`, `ranking_explanation`,
`navigation` {state, progress_m, remaining_m, remaining_min, off_route, current_edge_id, progress_endpoint},
`network_version`, `score_version`.

`ordered_edge_ids` is the single source of the route: geometry, distance and scores are all derived from it.

## Formulas

- Route dimension score: `Σ(length_e × coverage_e,d × score_e,d) / Σ(length_e × coverage_e,d)`; N/A edges are skipped, never 0.
- Coverage: `Σ(length_e × coverage_e,d) / route length`; under 0.6 is listed in `low_coverage_dimensions`.
- Personalized utility: `Σ w_d · (50 + coverage_d · (fit_d − 50)) / Σ w_d − 0.4 × detour %`, with `fit = score` or
  `100 − score` for "prefer less". Missing coverage pulls a dimension toward neutral 50, so sparse data cannot win.
- Hard constraints (time, detour, avoid stairs) filter before ranking; step-free is refused (no verified accessibility data).

## Breaking changes and migration (front end)

| Before | After |
|---|---|
| Browser called public Valhalla (`API.valhalla`, `fetchPedestrianRoute`, `makeCandidateSpecs`) | `POST /api/routes` (`route-client.js`) |
| Browser re-ranked with 2015 tree / LPC scans (`measureRouteEvidence`, `rankRoutes` scoring) | Engine ranking; `rankRoutes()` now asks the engine again |
| Route `{id,label,km,min,coords,score,treesPerKm,lpcPerKm,segmentNature,…}` | Adapter keeps `{id,label,km,min,coords,feasible,score}`; everything else is in `route.raw` (Route Object) |
| Route sections with geometry-hash IDs (`mapExperience.routeSegments`) | OSM `edge_id`s in `ordered_edge_ids` / `edges` |
| "Avoid stairs" blocked every route | Excludes OSM `highway=steps`; step-free still blocked |

All callers were updated in the same change (`app.js`, `center-map.js`, `explore-map.js`, `route-client.js`, tests).
The single-file demo (`STREETWISE_single_file_demo.html`) has no server, so it can show Explore but cannot route.
