# Urban data expansion and spatial pipeline audit

Generated 2026-10-24T20:12:32.994492+00:00. Counts below are computed from indexed source snapshots; the existing full inventory remains in DATA_AUDIT_REPORT.md and data/registry.json.

| Dataset | Retained records | Source URL | Routing role |
|---|---:|---|---|
| NYPD Complaint Data Historic | 567,391 | https://data.cityofnewyork.us/d/qgea-i56i | Independent complaint density: candidate edge costs + exact published-point route corridors + ranking |
| NYPD Complaint Data Current (Year To Date) | 277,593 | https://data.cityofnewyork.us/d/5uac-w243 | Independent complaint density: candidate edge costs + exact published-point route corridors + ranking |
| Forestry Tree Points | 897,619 | https://data.cityofnewyork.us/d/hn5i-inap | Queryable independent tree evidence; existing Nature score remains its versioned tree/park snapshot |
| NYC Planimetric Database: Hydrography | 2,206 | https://data.cityofnewyork.us/d/pjs3-c3z5 | Independent water-proximity edge costs + length-weighted route metrics + ranking |
| Waterfront Public Access Areas (WPAAs) | 78 | https://data.cityofnewyork.us/d/388s-pnvc | context until explicit geometric linkage is built |
| NYC DOT Pedestrian Plazas - Polygon | 93 | https://data.cityofnewyork.us/d/k5k6-6jex | context until explicit geometric linkage is built |
| Street Closures due to Construction Activities by Block and Intersection | 4,157 | https://data.cityofnewyork.us/d/ezy6-djsf | context until explicit geometric linkage is built |
| Seating Locations | 5,702 | https://data.cityofnewyork.us/d/esmy-s8q5 | context until explicit geometric linkage is built |
| MTA Subway Stations | 496 | https://data.ny.gov/d/39hk-dx4f | Queryable official transit context; existing Transit Connectivity scoring snapshot unchanged |
| MTA Subway Entrances and Exits: 2024 | 2,120 | https://data.ny.gov/d/i9wp-a4ja | Queryable official transit context; existing Transit Connectivity scoring snapshot unchanged |
| MTA Current Bus Stops | 13,735 | https://data.ny.gov/d/ai5j-txmn | Queryable official transit context; existing Transit Connectivity scoring snapshot unchanged |

## Source quality and exact roles

NYPD retained 844,984 unique complaint IDs across both sources. Borough counts: {'BRONX': 190549, 'BROOKLYN': 239168, 'MANHATTAN': 197804, 'QUEENS': 181045, 'STATEN ISLAND': 34336, 'UNKNOWN': 2082}. Rejections: {'qgea-i56i': {'invalid_or_missing_identity_date_coordinate_or_offense': 277, 'report_before_occurrence': 0}, '5uac-w243': {'invalid_or_missing_identity_date_coordinate_or_offense': 125, 'report_before_occurrence': 4}}. Raw source date ranges include impossible early dates; only the declared interval is ingested. SQL NULL and literal (null) are both counted as missing text. Publisher narrative descriptions still mention 2019; actual row maxima and update timestamps, not that stale prose, establish the data interval. Unknown boroughs remain unknown.

Crime raw → exact-source point R*Tree and daily 200 m grid counts → graph candidate-search heuristic using 600 m neighbourhoods sampled every <=50 m → physically cell/date-clustered source rows for final de-duplicated complaint counts within 100 m of each real route → reports per route km and a declared nominal strip-area density → monotonic density/(density+fixed graph p95) preference fit → weighted objective utility with unchanged distance penalties. Both high and low search candidates are generated for either preference, so tests compare the same candidate geometries. No hard clipping at p95. No personal-risk prediction.

Official hydrography polygons → <=25 m samples along graph geometries → share within 100 m of mapped water → candidate costs and final traversed-length-weighted proximity. Water includes rivers, coastal water and lakes; this is not viewshed analysis or proof of a public waterfront entrance. Display polygons are clipped to 2 km fragments and simplified by 2 m; routing uses the original geometry.

Forestry current Full-structure inventory is queryable across NYC and displayed by zoom. It includes 11,703 Dead and 4,401 Unknown condition records; Full does not mean living. The misleading Living label was corrected to Full-structure inventory trees while keeping all feature geometries, indicators and 12 numeric scores unchanged. Source species/condition/update/DBH are not canopy shade. New tree-index evidence does not silently replace the versioned Nature scoring method or pretend that its planting-date missingness is zero. Exact missing fractions are in inventory.json.

Construction WKT is transformed from NYC State Plane EPSG:2263 to WGS84 and checked against NYC bounds. Only permits whose work-date interval includes build day are retained. A full roadway closure permit may operate for part of its date interval and does not establish that the sidewalk is blocked. These records are context, not automatic pedestrian-network closures.

## Existing downloaded data versus routing usage

Existing building footprints, PLUTO land use/building ages and many street-furniture/transit datasets are legitimate map context, but they do not all enter core experience scores. Architecture currently uses landmark proximity; building age, landmark status and architectural style are not interchangeable. Explore continues to show the original 13 views. Full runtime wiring is verified by route tests, not merely file existence. The new crime/water criteria have independent metrics and explanations instead of being smuggled into Access & Safety or Scenic & Visual.

## Bounded infrastructure

Raw large inventories are streamed offline into SQLite and shipped compressed. Runtime streams decompression to a versioned temporary file, verifies the hash and uses read-only immutable SQLite with 1 MiB page cache and mmap disabled. R*Trees and date/type indexes bound queries; the API never downloads an NYC dataset during routing. Crime edge fields use a four-entry cache and a single-flight build lock. Exact corridor metrics have a separate bounded 64-entry cache keyed by source hash, geometry, distance and all time/type filters; direction is excluded because counts do not depend on preference direction. Map queries sum complete daily cells instead of random source row lookups. Full route objects are bounded to 8 MiB/32 entries; lightweight navigation geometry has a separate 4 MiB/200-entry bound. Segment Inspector uses a small indexed view, while source-hash validation prevents stale derived fields. All indices are derived from real source records.

## Menu evidence

Two real first-party menu-verifier receipts (Bagel and Cappuccino at the indexed Bagel Pub) are included with official URL and checked time. They seed evidence for at most 12 hours and never imply current stock, branch availability or verified USD pricing. One verified venue may fulfil both dishes as one waypoint; every required item is checked independently. Unverified extra items fail. Expired corpus entries trigger live verification rather than permanent success.

## Research and remaining gaps

The official NYC catalog was actively searched for shoreline/hydrography, canopy, bus stops, closures, sidewalk sheds, public art, GTFS, greenways, traffic volume, ramps, museums and hotels. A separate source-discovery receipt records IDs, publishers, update dates and source descriptions. 2015 Street Tree Census was compared with the newer Parks inventory; the newer inventory was selected for current lookup, not mislabelled as measured shade. Building footprints and PLUTO metadata were rechecked; no unverified architectural-style classification is added.

MTA station/entrance metadata on data.ny.gov returned proxy CONNECT 403, not an origin authentication error. Required MTA/NOAA domains and the tested offline Shapely dependency were saved in the cloud environment draft; the draft still requires user publication and does not prove runtime access. A normal CI ETL runner then retrieved the complete official MTA station (496), entrance (2,120) and Current Bus Stops (23,218 route-stop rows) datasets. Exact publisher bus IDs/coordinates group these into 13,735 stops with route lists and validity intervals. They now have indexed, bounded map queries and explicit source dates; existing Transit Connectivity score values remain unchanged. Partial historic and ridership samples were excluded from the runtime release. Current station coverage includes all five boroughs; ADA flags are not current elevator status. NOAA/NWS point metadata and 156 hourly forecast periods were also successfully checked; existing Open-Meteo forecasts and NWS alerts remain in place. Live MTA alerts/full GTFS timetable integration, full five-borough routing, canopy/solar exposure, live business ratings/room availability, verified current admission prices and proven wheelchair connectivity remain incomplete. These gaps are reported after actual source discovery and ingestion attempts, not used as a substitute for this release.

## Performance and production receipts

Before/after process memory, latency, concurrency, map inspection and actual production inputs/results are recorded separately in the release acceptance report and PR. A local result is not a Render result; mocks and recorded menu replays are not live API tests. No production-deployment success is claimed by this generated data audit alone.
