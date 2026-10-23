# STREETWISE · NYC — Architecture (routing refactor)

## Audit of the previous version

| Question | Finding before the refactor |
|---|---|
| Real pedestrian network? | Yes, but outsourced: the browser called the public Valhalla router (OSM). Alternatives were forced through hard-coded landmarks. No edge IDs came back. |
| LION used as the walk network? | No. LION was only the grey street layer and the Explore scoring base. |
| Where were the 12 scores? | `data/manhattan-streets.json` (LION segments), used by Explore only. |
| Segment IDs | Explore: LION physicalid-based. Route sections: geometry hashes, not traceable. |
| Same scores for map and routes? | No. Ranking re-scanned the 2015 tree census and LPC lots in the browser (2 dimensions); the profile showed 12 × "Not Available". |
| APIs extensible? | Only `/api/status`, `/api/interpret`, `/api/pois`; routing lived in the browser. |
| UI-only parts | Route labels (fastest/best) on waypoint detours, the 12-dimension route profile, "avoid stairs" (blocked everything). |

## Layers

```
Urban Experience Layer      NYC datasets → scripts/streetwise_indicators.py → LION analysis segments
                            → 12 scores + overall → data/manhattan-streets.json → Explore Urban Data
Routing Layer               OSM (OSMnx walk) → data/pedestrian/manhattan-walk-graph.json.gz
                            → LION–OSM matching → street_osm_edge_mapping.csv.gz + edge-scores.json.gz
                            → routing/engine.py (A*, candidates, ranking)
Application Layer           server.py APIs → route-client.js (AI Journey, Route Intelligence, edge inspector)
                            explore-map.js (13 maps, segment inspector) — both read the same score_version
Future Navigation Layer     /api/navigation/progress (on/off route, remaining distance); re-route = /api/routes
```

LION is the spatial reference for streets and experience; it is never routed on. OSM is the only routing graph.

## Identifiers

- Analysis segment: `MN-{physicalid}[-n]` (`source_segment_id` = LION physicalid, `lion_part` = multipart index).
- OSM edge: `{u}-{v}-{key}` — never the OSM way ID, because simplified edges can span several ways.
- Mapping table rows link the two, with overlap, distance, angle, name check, quality, method and versions.

## Versions

- `network_version` `osm-walk-YYYYMMDD-hash` — changes when the OSM graph is rebuilt.
- `score_version` `sw-score-hash` — hash of the indicator definitions; the matcher refuses mismatched inputs.
- `data_version` — date the public sources were downloaded.

## Build pipeline

```
python3 scripts/build_pedestrian_network.py   # OSMnx; ~15 s from cache, ~2 min fresh
python3 scripts/build_manhattan_streets.py     # 12 scores on LION segments (~1 min from cache)
python3 scripts/match_lion_osm.py              # matching + edge scores (~70 s)
```

`server.py` rebuilds steps 2–3 together in the background when the data is older than 30 days, then reloads the
router. The OSM graph is rebuilt manually (it needs OSMnx; the server itself needs only the standard library).
Raw source downloads are cached in `data/cache/` (about 150 MB, safe to delete; it is re-downloaded).

## Matching rules

An OSM edge is sampled every 5 m. A sample may borrow a LION segment only if it is within the edge type's band
(centreline 15 m, sidewalk 28 m, path 12 m), runs within 20° of it, has no conflicting street name (distinctive
words, house numbers and E/W prefix must agree; known co-names such as Lenox Av / Malcolm X Blvd are aliased), and the
edge is not a bridge, tunnel, indoor or non-zero layer. Slivers under min(8 m, 40 %) are dropped. Edges with ≥ 60 %
of their length matched take the overlap-weighted mean of the segment scores; the rest (crossings, park paths,
bridges) are measured directly with the same indicator code and placed on the LION percentile scale.
