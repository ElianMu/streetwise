# Tool Registry

`agent/tools.py` — 5 LangChain `@tool`-decorated functions, each a thin wrapper around an existing, already-
tested `routing/*` function. No tool invents new business logic; each just gives the agent a structured,
uniform interface to something that already worked.

Uniform result shape: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"type": ..., "message": ...}}`
on failure. `error.type` is one of `invalid_input`, `upstream_unavailable`, `not_found` — this is the signal
`agent/runtime.py`'s retry logic reads to decide whether retrying could possibly help.

| Tool | Wraps | Real call verified against |
|---|---|---|
| `search_places(lat, lon, categories, query, cuisine, radius_m, limit)` | `routing/places.py`'s `PlaceStore.search` | Real local place index — e.g. found "Revel & Rye" and 11 other real restaurants near Times Square |
| `get_weather(lat, lon, minutes)` | Open-Meteo forecast API (same source as `weather.js`) + `routing/weather.py`'s `validate_snapshot`/`assess` | Real live network call — returned a real current feels-like temperature and heat/rain/wind assessment |
| `calculate_route(origin_lat, origin_lon, dest_lat, dest_lon, max_minutes)` | `routing/engine.py`'s `RoutePlanner.plan` (A*/Dijkstra on the OSM pedestrian graph) | Real route between two Manhattan points, real `distance_m` |
| `validate_route(route_minutes, max_minutes, route_km, max_km)` | New (pure arithmetic — nothing to wrap; the router doesn't itself apply the agent's dynamic constraint) | Verified it both flags and clears violations correctly |
| `verify_restaurant_menu(place_id, item, name)` | `routing/menu.py`'s `verify` (official-site menu check, SSRF-guarded, cached) | Real call against a real place id; returned a real `unverified` status with its real reason |

Every row above was exercised with a real call against real local data in this session (see
`tests/test_agent.py`'s `ToolRegistryRealDataTests`), not a mock.

## Deliberately not wrapped as tools

- `recommend_food` (the existing deterministic pipeline) — this is the baseline the agent is compared
  against, not a tool it calls. Wrapping it as a tool would let the "agent" just call one tool and short-
  circuit the entire point of giving it multi-step tool selection.
- `query_urban_data` (trees/crime/context layers) — real City Walk functionality, but no scenario in this
  vertical slice needs it. Adding it now would be scope creep without a concrete use; the registry is
  designed to add tools the same way (a `@tool`-decorated wrapper + an entry in `TOOLS`) when a real scenario
  needs one.
