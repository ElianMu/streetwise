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
  "constraints": {"max_minutes": 30, "max_detour_pct": 25, "avoid_detours": true, "avoid_stairs": false},
  "weather": {"source": "open-meteo", "kind": "forecast_window", "valid_from": "2026-07-15T14:00", "valid_to": "2026-07-15T15:00",
              "age_min": 4, "feels_like_max_c": 34, "temperature_max_c": 31, "precip_probability_max_pct": 10,
              "precip_max_mm_per_h": 0, "wind_max_kmh": 12, "daylight": true, "mode": "auto", "priority": "normal", "alerts": []}
}
```

`max_minutes` is the user's hard limit: any number ≥ 10, no upper cap (`constraints_used` echoes the limits applied, `feasible_count` how many routes meet them). `weights` keys must be among the 12 dimension names exactly. Only weights > 0 count; with none, all 12 count equally.
Weights describe the user and never change street scores. Response:
`{network_version, score_version, origin, destination, shortest_distance_m, preferences_used, preferences_expressed, routes: [Route], compute_seconds, weather_routing, notes}`.
`weather` is optional (null/absent → static routing only). Out-of-range values become null (unknown, never "normal"). `mode: "off"` disables
the weather term; `priority: "high"` (user asked for a cooler walk) multiplies it by `explicit_request_multiplier`.
`weather_routing` = `{config_version, snapshot, data_available, factors: [{factor: heat|rain|wind, …, routing_capable}],
routing: {status: active|not_active|unavailable, active, factor, level, multiplier, reason, effect}}`; `effect` (heat routing only) =
`{baseline_route_id, recommended_route_id, changed, extra_minutes, exposure_reduction}` against the recommendation the static ranking alone makes.
Each route then carries `weather: {heat_exposure_share, tree_cover_proxy_share, evidence_coverage, evidence}`, and while heat routing is
active `personalized_score.weather_adjustment`. A route with `objective: "weather_heat"` ("Cooler Route (tree-cover proxy)") is added on hot days.
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

### Route QA, maneuvers and navigation fields (every route from /api/routes and /api/itinerary)
- `validation`: `{geometry_status, pedestrian_network_status, required_stops_status, stop_access_status, time_constraint_status,
  distance_constraint_status, food_evidence_status, status: pass | pass_with_warnings | fail | not_checked, navigation_allowed,
  data_coverage:{mean, low_coverage_dimensions, not_available, score_version, network_version}, warnings, blocking_issues,
  validation_version, validation_timestamp}`. Blocking issues (edges that do not join, unknown edge IDs, closed edges,
  stairs when avoided, a required stop not reached, geometry outside NYC) set `navigation_allowed: false`.
- `maneuvers`: `[{maneuver_id, route_id, leg_id, type: depart | continue | slight_left | turn_left | sharp_left | slight_right |
  turn_right | sharp_right | keep_left | keep_right | u_turn | enter_path | cross | arrive_stop | arrive | notice, street_name,
  coordinate, distance_along_route_m, bearing_before, bearing_after, turn_angle, node_id, instruction_text, instruction_zh,
  confidence: high | medium | low, data_source, then?, stop_name?, required?, visit_min?}]`.
- `route_signature`: sha1(network_version | ordered edge IDs), 16 hex.

### POST /api/navigation/progress
Adds `route_snapshot: {network_version, ordered_edge_ids, route_signature}` for when this server process no longer holds the
route (restart): geometry is rebuilt from the server's own network; another network version or a wrong signature is refused
(plan again). Live navigation itself runs in the browser (`nav-engine.js`) and does not send positions to the server.

### POST /api/itinerary

Multi-stop city walk on the pedestrian graph. Places come from the client (search providers or `data/places`); the server never invents one.
```json
{"origin": {"id":"osm:node/1","name":"Hilton New York Midtown","lat":40.7623,"lon":-73.9797},
 "end": {"mode": "fixed | round | hotel | open", "place": {...}},
 "stops": [{"id","name","lat","lon","required":true,"order":1,"visit_min":20}],
 "slots": [{"slot_id":"food:cafes:cappuccino","label":"Cappuccino (café)","required":true,"visit_min":15,"candidates":[{"id","name","lat","lon","score":0.6,"evidence":"..."}]}],
 "pool": {"max_stops":3,"candidates":[{"id","name","lat","lon","score","visit_min","group"}]},
 "constraints": {"max_minutes":100,"max_km":5,"max_outing_minutes":150,"avoid_stairs":false},
 "preferences": {"weights":{},"directions":{}}, "theme": "City walk: ..."}
```
Response: the `/api/routes` shape with one Route Object (`objective: "itinerary"`, continuous stitched legs) plus
`itinerary` = `{end_mode, start, stops:[{seq,id,name,role,required,arrival_min,leg_in_m,leg_in_min,visit_min,slot_id,alternatives,evidence}],
skipped, notes, method, totals:{walk_m,walk_min,visit_min,outing_min,stops}, constraints:{...,feasible,violations}, pool:{requested,added},
matrix:{points,seconds,basis}, coverage}`. Places off the routable graph raise 422 with a coverage message.

### POST /api/detours
`{"sequence":[places in walk order], "candidates":[places]}` → per candidate `{reachable, detour_m, detour_min, after_index}`
(detour = d(a,c) + d(c,b) − d(a,b) at the best insertion, network metres).

### POST /api/menu/verify
`{"place_id","name","item"}` → `{status: confirmed_menu_match | probable_match_review | unverified | not_found_in_checked_sources, place_id,
requested_item, matched_item, evidence_type: html_menu_page | pdf_menu | website_page | website_mention, menu_source_url, evidence, menu_date,
menu_date_basis, checked_at, price, currency, pages_checked, reason, note}`. Only the official website recorded for `place_id` in
`data/places` is read (a client URL is ignored unless on that site); SSRF-safe fetching; robots.txt; ≤ 3 pages, 1.5 MB, 20 s; cached 12 h;
rate limit 10/min per client (HTTP 429). Itinerary 30/min, routes 60/min.

### POST /api/interpret (LLM, when configured)
Failures return a safe `reason` (also logged by the server): `{stage: not_configured | invalid_key_format | upstream_http | upstream_unreachable |
upstream_bad_response | model_output_invalid_json | model_output_rejected | server_error, http_status, type, code, detail}`.
`type` / `code` are OpenAI's error identifiers (e.g. 401 `invalid_api_key`, 429 `insufficient_quota`, 404 `model_not_found`);
the provider's message text is never passed on and anything resembling a key is scrubbed. 503 = no key, 502 = LLM failure,
500 = server error. 503 = key missing or malformed (invalid_key_format means the key contains internal whitespace or invalid header characters). The backend trims accidental leading/trailing whitespace in OPENAI_API_KEY without changing internal characters. The browser falls back to the labelled local parser and shows the reason.

Adds `journey`: `{interests, named_stops:[{name,required,order}], food:[{category,item,cuisine,required}], services, service_scope,
hotel:{name,is_mine}, origin, destination, end_mode, walking_minutes, outing_minutes, distance_km, more, remove}` — names, categories and
limits only; coordinates, menus, prices and hours are rejected.

`/api/routes` also accepts `constraints.max_km` (hard distance limit). `/api/status` adds `features`.

## Formulas

- Route dimension score: `Σ(length_e × coverage_e,d × score_e,d) / Σ(length_e × coverage_e,d)`; N/A edges are skipped, never 0.
- Coverage: `Σ(length_e × coverage_e,d) / route length`; under 0.6 is listed in `low_coverage_dimensions`.
- Personalized utility: `Σ w_d · (50 + coverage_d · (fit_d − 50)) / Σ w_d − 0.4 × detour %`, with `fit = score` or
  `100 − score` for "prefer less". Missing coverage pulls a dimension toward neutral 50, so sparse data cannot win.
- Itinerary ordering: exact enumeration (≤ 7 required items) minimizing network walk − 1500 m × Σ slot relevance; otherwise cheapest insertion + 2-opt (heuristic). Optional places: greedy value / added minute within all budgets.
- Hard constraints (time, distance, detour, avoid stairs) filter before ranking; step-free is refused (no verified accessibility data).
- Weather (routing/weather.py `CONFIG`): heat level `h = clamp((feels_like − 27) / (32 − 27))`, only by day; edge exposure
  `x = 1 − max(min(tree_km / 150, 1), park_pct / 100)` (median where no evidence). Weather candidate edge cost per metre
  `1 + 0.8·(1 − utility) + 0.6·h·m·x`; ranking `utility − 20·h·m·(exposed length share)`, `m` = 2 on explicit request, else 1.
  Rain and wind are advisory only (no covered-walkway or wind-exposure data).

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

## Urban Data Layers (static, no API)

Navigate → Urban Data Layers reads static files only, so it works on GitHub Pages without the backend:
`data/layers/catalog.json` and `data/layers/tiles/<tileset>/<tx>_<ty>.json` (1 km tiles in the catalog's local metric
projection; a feature is stored in every tile its bounding box touches and de-duplicated by `feature_id`).
Built by `scripts/build_urban_layers.py`; the former `/api/layers` endpoints were removed (they loaded whole layers
into backend memory).

Catalog entry: `id`, `name`, `categories` (10 data categories, not experience dimensions), `status`
(`CONNECTED` | `AVAILABLE_NOT_CONNECTED` | `MISSING` | `UNAVAILABLE`), and for connected datasets `tileset`, optional
`filter` (a documented view of a dataset, e.g. elevator entrances), `geometry`, `layer_type`, `source`, `source_url`,
`last_updated` (publisher), `time_range` (computed from the records where dated), `attributes` (original fields kept),
`used_in_scoring` + `scoring` [{dimension, sub_indicators}] (only datasets that feed the existing scores), `historical`,
`note`, `style`, `min_zoom_view`, `feature_count`. Unconnected entries carry `reason`.

Filtering (urban-geo.js, mirrored by routing/layers.py for tests): Along Selected Route keeps records whose geometry is
within the display corridor (50/100/200/500 m) of the route LineString — polygons by intersection or edge distance, not
centroid; Current Map View keeps records whose bounds intersect the view. Corridors never change scores.
