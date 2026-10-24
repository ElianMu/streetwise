# STREETWISE · NYC — Data Audit Report

Generated 2026-10-24T03:07:54+00:00 by `scripts/build_audit_report.py` from the shipped files (no estimates).

**112 datasets** (84 connected), **919,245 records** in the shipped files. A record count is not a count of places verified open today.

## Datasets

| Dataset | Provider | Class | Coverage | Records | Freshness (days) | Missing fields | Quality | Integration |
|---|---|---|---|---|---|---|---|---|
| Street centerlines (LION) | NYC Department of City Planning | static_urban | Manhattan (tile build box) | 13297 | 519 | — | good | connected |
| Sidewalks (pedestrian network) | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 26604 | 1 | name 95%, surface 29% | fair (a field missing in 95%) | connected |
| Crosswalks | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 8019 | 1 | surface 47% | good | connected |
| Pedestrian paths & steps | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 16675 | 1 | name 90%, surface 34% | fair (a field missing in 90%) | connected |
| Sidewalk surface (planimetric) | City of New York | static_urban | Manhattan (tile build box) | 5461 | 913 | — | good | connected |
| Pedestrian ramps | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | 23668 | 1823 | stname2 1%, stname1 0% | good | connected |
| Intersections (3+ way) | NYC Department of City Planning | static_urban | Manhattan (tile build box) | 5040 | 519 | — | good | connected |
| Traffic signals | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 3945 | 1 | crossing 99%, traffic_signals 50% | fair (a field missing in 99%) | connected |
| Pedestrian plazas | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | 36 | 23 | tostreet 6% | good | connected |
| Bicycle lanes & routes | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | 7898 | 92 | fromstreet 0%, tostreet 0% | good | connected |
| Benches & seating | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 7280 | 1 | name 100%, leisure 94%, amenity 5% | fair (a field missing in 100%) | connected |
| Drinking fountains (NYC Parks) | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 909 | 831 | position 6% | good | connected |
| Public restrooms | City of New York (NYC Open Data) | static_urban | Manhattan (tile build box) | 237 | 484 | website 80%, restroom_type 29%, accessibility 20% | fair (a field missing in 80%) | connected |
| Street trees | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 99873 | 3 | planteddate 88%, riskrating 28%, updateddate 20% | fair (a field missing in 88%) | connected |
| Parks & green spaces | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 396 | 8 | address 30%, subcategory 10% | good | connected |
| Natural areas | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 2 | 8 | address 100% | fair (a field missing in 100%) | connected |
| Waterfront parks | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 6 | 8 | address 50% | good | connected |
| Community gardens | NYC Department of Parks & Recreation (NYC Open Data) | static_urban | Manhattan (tile build box) | 163 | 3 | openhrsm 47%, openhrssu 38%, openhrssa 31% | good | connected |
| Building footprints | City of New York | static_urban | Manhattan (tile build box) | 45178 | 5 | name 98%, construction_year 2%, ground_elevation_ft 0% | fair (a field missing in 98%) | connected |
| Building heights | City of New York | static_urban | Manhattan (tile build box) | 45178 | 5 | name 98%, construction_year 2% | fair (a field missing in 98%) | connected |
| Building year built | City of New York | static_urban | Manhattan (tile build box) | 45178 | 5 | name 98%, construction_year 2% | fair (a field missing in 98%) | connected |
| Land use (tax lots) | NYC Department of City Planning | static_urban | Manhattan (tile build box) | 42106 | 61 | floors 5%, landuse_name 0%, zoning_district 0% | good | connected |
| Privately owned public spaces | NYC Department of City Planning | static_urban | Manhattan (tile build box) | 366 | 375 | building_name 32%, year_completed 6%, hour_of_access_required 6% | good | connected |
| Historic landmarks (individual) | City of New York | static_urban | Manhattan (tile build box) | 943 | 192 | — | good | connected |
| Historic districts | NYC Landmarks Preservation Commission | static_urban | Manhattan (tile build box) | 70 | 128 | calendared 64% | fair (a field missing in 64%) | connected |
| Museums | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 86 | 1 | wheelchair 100%, amenity 98%, opening_hours 29% | fair (a field missing in 100%) | connected |
| Art galleries | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 252 | 1 | wheelchair 100%, amenity 98%, opening_hours 33% | fair (a field missing in 100%) | connected |
| Theaters & performance venues | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 242 | 1 | wheelchair 100%, tourism 98%, opening_hours 91% | fair (a field missing in 100%) | connected |
| Cinemas | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 33 | 1 | wheelchair 100%, tourism 97%, opening_hours 79% | fair (a field missing in 100%) | connected |
| Libraries | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 64 | 1 | wheelchair 100%, tourism 97%, opening_hours 31% | fair (a field missing in 100%) | connected |
| Public art | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 431 | 1 | operator 99%, name 36%, artwork_type 7% | fair (a field missing in 99%) | connected |
| Monuments & memorials | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 495 | 1 | name 37% | good | connected |
| Restaurants | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 5113 | 1 | leisure 100%, shop 99%, opening_hours 42% | fair (a field missing in 100%) | connected |
| Cafés | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 1390 | 1 | leisure 100%, shop 96%, opening_hours 44% | fair (a field missing in 100%) | connected |
| Bars & pubs | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 887 | 1 | leisure 100%, shop 99%, cuisine 76% | fair (a field missing in 100%) | connected |
| Bakeries | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 282 | 1 | leisure 100%, amenity 86%, cuisine 86% | fair (a field missing in 100%) | connected |
| Grocery stores | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 1064 | 1 | leisure 100%, amenity 98%, cuisine 87% | fair (a field missing in 100%) | connected |
| Retail stores | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 6072 | 1 | leisure 100%, cuisine 100%, amenity 98% | fair (a field missing in 100%) | connected |
| Markets | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 30 | 1 | shop 100%, leisure 100%, cuisine 100% | fair (a field missing in 100%) | connected |
| Entertainment venues | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 45 | 1 | shop 100%, cuisine 91%, leisure 78% | fair (a field missing in 100%) | connected |
| Recreation facilities | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 1851 | 1 | shop 100%, cuisine 100%, amenity 100% | fair (a field missing in 100%) | connected |
| All activity places (mix) | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 45618 | 1 | historic 98%, tourism 95%, shop 84% | fair (a field missing in 98%) | connected |
| Pedestrian injury crashes | NYPD (NYC Open Data) | static_urban | Manhattan (tile build box) | 4204 | 131 | cross_street_name 74%, on_street_name 26%, off_street_name 26% | fair (a field missing in 74%) | connected |
| Cyclist injury crashes | NYPD (NYC Open Data) | static_urban | Manhattan (tile build box) | 3668 | 131 | cross_street_name 69%, on_street_name 31%, off_street_name 31% | fair (a field missing in 69%) | connected |
| Speed limits | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | 17118 | 23 | — | good | connected |
| 311 noise complaints | NYC 311 (NYC Open Data) | static_urban | Manhattan (tile build box) | 177477 | 1 | location_type 9%, incident_address 1% | good | connected |
| Expressways & ramps (traffic exposure) | NYC Department of City Planning | static_urban | Manhattan (tile build box) | 1414 | 519 | — | good | connected |
| Subway stations | Metropolitan Transportation Authority (data.ny.gov) | static_urban | Manhattan (tile build box) | 153 | 1 | — | good | connected |
| Subway entrances | Metropolitan Transportation Authority (data.ny.gov) | static_urban | Manhattan (tile build box) | 868 | 323 | — | good | connected |
| Accessible subway entrances (elevator) | Metropolitan Transportation Authority (data.ny.gov) | static_urban | Manhattan (tile build box) | 39 | 323 | — | good | connected |
| Bus stops | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 1682 | 1 | operator 69%, network 48%, route_ref 26% | fair (a field missing in 69%) | connected |
| Citi Bike stations | Lyft / Citi Bike | static_urban | Manhattan (tile build box) | 696 | 1 | — | good | connected |
| Ferry terminals | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 23 | 1 | operator 65%, name 4% | fair (a field missing in 65%) | connected |
| Hospitals & clinics | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 326 | 1 | operator 54%, addr:street 14%, addr:housenumber 14% | fair (a field missing in 54%) | connected |
| Pharmacies | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 300 | 1 | opening_hours 35%, addr:housenumber 22%, addr:street 21% | good | connected |
| Schools | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 526 | 1 | operator 90%, addr:housenumber 20%, addr:street 19% | fair (a field missing in 90%) | connected |
| Public Wi-Fi (LinkNYC) | City of New York | static_urban | Manhattan (tile build box) | 1225 | 205 | cross_street_1 0%, cross_street_2 0% | good | connected |
| Scenic viewpoints | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 96 | 1 | name 78% | fair (a field missing in 78%) | connected |
| Pedestrian bridges | OpenStreetMap contributors | static_urban | Manhattan (tile build box) | 472 | 1 | name 70% | fair (a field missing in 70%) | connected |
| Restaurant inspections (DOHMH) | City of New York | static_urban | Manhattan (tile build box) | — | — | — | measured in its connected row | connected (server-side, not a map layer) |
| Tree canopy | City of New York | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Green infrastructure / bioswales | City of New York | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Water bodies | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Zoning districts (polygons) | NYC Department of City Planning | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Street wall / frontage | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Building entrances | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| All motor vehicle collisions | NYPD (NYC Open Data) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Traffic volume | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Pedestrian safety improvements | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Temporary street closures | NYC Department of Transportation (NYC Open Data) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Air quality (NYCCAS) | City of New York | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Urban heat / heat vulnerability | City of New York | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Surface temperature | Landsat land surface temperature (USGS) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Shade / solar exposure | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Flood risk | City of New York | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Air pollution monitoring stations | US EPA AirNow / AQS | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Subway lines | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Bus routes | Metropolitan Transportation Authority (data.ny.gov) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Transit service status (real-time) | Metropolitan Transportation Authority (data.ny.gov) | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Waterfront public access areas | NYC Department of City Planning | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | available, not connected |
| Shorelines | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Waterfront walkways | Not connected | static_urban | Manhattan (tile build box) | — | — | — | n/a (not connected) | no dataset |
| Hotels & accommodation (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 473 | 0 | hours 96%, web 20%, addr 10% | fair (a field missing in 96%) | connected |
| Museums & galleries (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 365 | 0 | hours 36%, web 16%, addr 15% | good | connected |
| Famous attractions & viewpoints (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 228 | 0 | hours 93%, addr 83%, web 53% | fair (a field missing in 93%) | connected |
| Historic places (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 390 | 0 | hours 99%, addr 91%, web 82% | fair (a field missing in 99%) | connected |
| Parks & gardens (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 526 | 0 | hours 90%, addr 80%, web 53% | fair (a field missing in 90%) | connected |
| Cafés & coffee (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 2001 | 0 | web 65%, hours 64%, addr 16% | fair (a field missing in 65%) | connected |
| Bakeries & desserts (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 713 | 0 | web 72%, hours 70%, addr 14% | fair (a field missing in 72%) | connected |
| Restaurants (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 10919 | 0 | hours 73%, web 72%, addr 10% | fair (a field missing in 73%) | connected |
| Bars & pubs (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 884 | 0 | hours 46%, web 41%, addr 23% | good | connected |
| Theatres, libraries & landmarks of worship (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 434 | 0 | hours 88%, web 20%, addr 14% | fair (a field missing in 88%) | connected |
| Shopping (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 278 | 0 | web 54%, hours 52%, addr 32% | fair (a field missing in 54%) | connected |
| Pharmacies (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 327 | 0 | web 53%, hours 35%, addr 20% | fair (a field missing in 53%) | connected |
| Groceries & convenience (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 1012 | 0 | web 76%, hours 60%, addr 20% | fair (a field missing in 76%) | connected |
| Hospitals & clinics (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 231 | 0 | hours 46%, web 27%, addr 13% | good | connected |
| Banks & ATMs (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 532 | 0 | web 56%, addr 44%, hours 38% | fair (a field missing in 56%) | connected |
| Public restrooms (discovery index) | City of New York (NYC Open Data) | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 419 | 0 | addr 97%, web 88%, hours 48% | fair (a field missing in 97%) | connected |
| Luggage storage (discovery index) | OpenStreetMap contributors | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 1 | 0 | hours 100%, addr 0%, web 0% | fair (a field missing in 100%) | connected |
| NYC designated individual landmarks (discovery index) | NYC Landmarks Preservation Commission | periodic_poi | Within 150 m of the routable pedestrian graph (osm-walk-20261023-99602011): Manhattan | 921 | 0 | web 100%, hours 100%, addr 0% | fair (a field missing in 100%) | connected |
| OSM pedestrian routing graph | OpenStreetMap contributors | static_urban | Manhattan | 122092 | 0 | — | good | connected |
| 12-dimension scores on routing edges | STREETWISE (derived) | static_urban | Manhattan | 61047 | 0 | — | good | connected |
| Manhattan street segments with 12-dimension scores | STREETWISE (derived from NYC DCP LION and listed sources) | static_urban | Manhattan | 10533 | 1 | — | good | connected |
| Food establishment permits and inspections (five boroughs) | NYC Department of Health and Mental Hygiene | periodic_poi | NYC five boroughs {"Bronx": 2632, "Manhattan": 12536, "Brooklyn": 7997, "Staten Island": 1114, "Queens": 6989, "0": 101} | 31369 | 0 | coordinates 3% | limited (valid geometry 97.4%) | connected |
| Hotel-class tax lots (Manhattan) | NYC Department of Finance | periodic_poi | Manhattan | 780 | 0 | — | good | connected |
| Google Places API (New) | Google | on_demand_business | per request | — | — | — | n/a (blocked by provider access) | blocked_by_provider_access |
| Yelp Fusion API | Yelp | on_demand_business | per request | — | — | — | n/a (blocked by provider access) | blocked_by_provider_access |
| Foursquare Places API | Foursquare | on_demand_business | per request | — | — | — | n/a (blocked by provider access) | blocked_by_provider_access |
| Booking.com Demand API | Booking.com | realtime_availability | per request | — | — | — | n/a (blocked by provider access) | blocked_by_provider_access |
| Expedia Rapid API | Expedia | realtime_availability | per request | — | — | — | n/a (blocked by provider access) | blocked_by_provider_access |
| Current weather | Open-Meteo | realtime_availability | NYC | — | — | — | unmeasured | connected |
| Weather alerts | US National Weather Service | realtime_availability | NYC | — | — | — | unmeasured | connected |

## Hard-coded quick-pick places (app.js `PLACES`)

Real places with hand-entered coordinates, used only as optional quick picks. Offset = distance to the same-name record in the discovery index.

| Preset | Name | Matched record | Offset (m) |
|---|---|---|---|
| bryant | Bryant Park | Bryant Park | 33 |
| carnegie | Carnegie Hall | Carnegie Hall | 11 |
| times | Times Square | Times Square | 93 |
| rock | Rockefeller Center | Rockefeller Center | 18 |
| nypl | New York Public Library | New York Public Library, Astor, Lenox and Tilden Foundations | 59 |
| stpatrick | St. Patrick’s Cathedral | no index match | — |
| radio | Radio City Music Hall | Radio City Music Hall | 39 |
| moma | Museum of Modern Art | no index match | — |
| grand | Grand Central Terminal | Grand Central Terminal | 8 |
| battery | The Battery | no index match | — |
| wall | Wall Street | Wall Street Bordealix | 230 |
| washington | Washington Square Park | Washington Square Park | 27 |
| union | Union Square | Union Square Park | 17 |
| columbus | Columbus Circle | Columbus Circle | 3 |
| met | The Metropolitan Museum | The Metropolitan Museum of Art | 18 |
| columbia | Columbia University | Columbia University Bookstore | 63 |
| apollo | Apollo Theater | Apollo Theater | 25 |
| fort | Fort Tryon Park | Fort Tryon Park | 212 |

## Placeholder / simulated data in runtime code

No matches for random values, mock/fake/dummy data or hard-coded ratings.

## Data files not read by runtime code

route-validation.json, route-verification.json, validation.json

## Agent tools

| Capability | Implementation | Status |
|---|---|---|
| search_places / autocomplete | places.js searchPlaces (Photon + NYC GeoSearch, live) | wired (call site found) |
| discover places (POI index) | journey.js discoverPlaces → data/places/*.json | wired (call site found) |
| verify_menu_item | POST /api/menu/verify (routing/menu.py) | wired (call site found) |
| calculate_walking_route | POST /api/routes, /api/itinerary | wired (call site found) |
| validate_route | routing/validation.py on every route | wired (call site found) |
| turn-by-turn maneuvers | routing/maneuvers.py | wired (call site found) |
| find along route (detours) | POST /api/detours | wired (call site found) |
| weather context | weather.js (Open-Meteo, NWS) | wired (call site found) |

## Business-data provider access (this build environment)

| Provider | Key configured |
|---|---|
| google_places | no |
| yelp_fusion | no |
| foursquare | no |
| booking_demand | no |
| expedia_rapid | no |
| openai | no |

Ratings, review counts, review text, hotel room types, live prices and availability need one of these providers; without a key they are reported as **Blocked by Provider Access**, never simulated.

