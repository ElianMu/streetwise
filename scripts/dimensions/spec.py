"""STROLLANE · NYC — 12 Experience Dimensions × 24 Indicators (calculation specification v1).

Transcribed row by row from the project's "12 Dimensions × 24 Indicators" tables. This module is the single
source of truth for names, units, parameters, scoring direction and data sources; the pipeline, the exported
manifest and the Map Mode inspector all read it. Do not rename or regroup dimensions here.

role:
  up          higher raw value → higher score
  down        lower raw value  → higher score (percentile reversed)
  validation  measured for checking a dimension, never part of a street score   (ped_flow_observed)
  context     area-level context, never assigned to a street score               (no2_area_context)
"""

SPEC_VERSION = 'strollane-12x24-v1'
CRS_METRIC = 'EPSG:32618'  # WGS 84 / UTM zone 18N — metres; all distances, buffers and lengths use it
CRS_WGS84 = 'EPSG:4326'

# Dimension keys keep the order and keys already used by the app (d0 … d11).
DIMENSIONS = [
    ('architecture', '01', 'Architecture'),
    ('nature', '02', 'Nature'),
    ('culture', '03', 'Culture'),
    ('quiet', '04', 'Quiet & Relax'),
    ('spatial_comfort', '05', 'Spatial Comfort'),
    ('urban_vibrancy', '06', 'Urban Vibrancy'),
    ('food_retail', '07', 'Food & Retail'),
    ('scenic_visual', '08', 'Scenic & Visual'),
    ('walkability', '09', 'Walkability'),
    ('access_safety', '10', 'Access & Safety'),
    ('environment', '11', 'Environment'),
    ('transit_connectivity', '12', 'Transit Connectivity'),
]
DIM_KEYS = [d[0] for d in DIMENSIONS]


def I(key, dim, label, unit, role, method, db, params=None):
    return {'key': key, 'dimension': dim, 'label': label, 'unit': unit, 'role': role, 'method': method,
            'db': db, 'params': params or {}}


INDICATORS = [
    I('lpc_k', 'architecture', 'Weighted landmark proximity', 'index', 'up',
      'Sample the street centerline every 40 m. For LPC landmark lots within 300 m, apply Gaussian distance weights '
      '(σ = 100 m) and average all samples. Higher values indicate stronger exposure to recognized landmarks.',
      ['lpc'], {'step_m': 40, 'cutoff_m': 300, 'sigma_m': 100}),
    I('tree_km', 'nature', 'Recorded trees', 'trees/km', 'up',
      'Count mapped tree points within 30 m of each street segment. Divide by segment length in kilometres, using a '
      'minimum length of 80 m to avoid inflated short-segment values. Higher values mean denser recorded tree presence.',
      ['trees'], {'radius_m': 30, 'min_length_m': 80}),
    I('park_pct', 'nature', 'Park adjacency', 'share 0–1', 'up',
      'Sample points along the street centerline and side offsets at 20 m and 40 m. Divide points inside official park '
      'polygons by all valid sample points. Higher values indicate stronger spatial adjacency to park land.',
      ['parks'], {'step_m': 20, 'offsets_m': [0, -20, 20, -40, 40]}),
    I('canopy_pct', 'nature', 'Tree-canopy cover', '%', 'up',
      'Create a 20 m buffer on both sides of the street and intersect it with the 2021 land-cover raster. Divide '
      'canopy-class pixel area by total valid classified area × 100. Higher values indicate more overhead tree cover.',
      ['tnc_landcover'], {'buffer_m': 20}),
    I('cult_k', 'culture', 'Cultural POI proximity', 'index', 'up',
      'Map museums, galleries, theatres, libraries, and similar cultural destinations. For locations within 450 m, sum '
      'Gaussian distance-decay weights (σ = 150 m) along the street. Higher values indicate stronger nearby cultural access.',
      ['osm'], {'step_m': 40, 'cutoff_m': 450, 'sigma_m': 150}),
    I('noise_k', 'quiet', 'Noise-complaint intensity', 'index', 'down',
      'Filter geolocated NYC 311 noise complaints to the latest 12 months. Sum Gaussian distance weights for reports '
      'within 150 m (σ = 50 m), then reverse the percentile. Fewer nearby complaints rank higher.',
      ['noise'], {'step_m': 40, 'cutoff_m': 150, 'sigma_m': 50}),
    I('width_ft', 'quiet', 'Roadway width', 'ft', 'down',
      'Read roadway width in feet from NYC LION for each street segment. Convert values to Manhattan-relative '
      'percentiles and reverse them so narrower streets rank higher. This is a quietness proxy, not a measured sound level.',
      ['lion']),
    I('sidewalk_pct', 'spatial_comfort', 'Mapped sidewalk coverage', 'share 0–1', 'up',
      'Sample roughly every 20 m along the street and add left/right offsets at 5, 8, 11, and 14 m. Divide points inside '
      'mapped sidewalk polygons by all valid points. Higher values indicate wider or more continuous sidewalk coverage.',
      ['sidewalks'], {'step_m': 20, 'offsets_m': [-5, 5, -8, 8, -11, 11, -14, 14]}),
    I('seat_access_m', 'spatial_comfort', 'Walking distance to seating', 'm', 'down',
      'Locate public seating points on the walkable network. From each street midpoint, calculate the shortest walking '
      'distance to the nearest seat, capped at 500 m. Shorter distances indicate easier access to rest.',
      ['seating', 'osm_walk'], {'cap_m': 500}),
    I('ramp_coverage', 'spatial_comfort', 'Pedestrian-ramp coverage', 'share 0–1', 'up',
      'Identify evaluable pedestrian crossing nodes along the street. Check whether at least one recorded curb ramp lies '
      'within 20 m of each node, then divide covered nodes by all eligible nodes. Higher values mean more documented ramp provision.',
      ['ramps', 'lion'], {'radius_m': 20}),
    I('vibr_idx', 'urban_vibrancy', 'POI diversity × quantity', 'index', 'up',
      'Collect OSM places within 150 m of the street midpoint and group them by activity type. Compute normalized Shannon '
      'diversity H and multiply it by ln(1 + POI count). Higher values indicate both more places and greater use diversity.',
      ['osm'], {'radius_m': 150}),
    I('ped_flow_observed', 'urban_vibrancy', 'Observed pedestrian flow', 'people/h', 'validation',
      'Standardize pedestrian-sensor observations by hour and period to make locations comparable. Use the median valid '
      'hourly pedestrian count and compare it with the POI-based vibrancy model. This is validation evidence, not a full-street score.',
      ['ped_counts']),
    I('food_k', 'food_retail', 'Food and retail proximity', 'index', 'up',
      'Extract mapped restaurants, cafés, bars, shops, and other retail POIs. At street samples, sum Gaussian proximity '
      'values for locations within 150 m (σ = 50 m). Higher values indicate stronger nearby food and retail availability.',
      ['osm'], {'step_m': 40, 'cutoff_m': 150, 'sigma_m': 50}),
    I('scenic_k', 'scenic_visual', 'Scenic POI proximity', 'index', 'up',
      'Select OSM viewpoints, public art, fountains, memorials, and monuments. Compute Gaussian distance weights within '
      '300 m (σ = 100 m) along street samples. Higher values indicate greater proximity to scenic features.',
      ['osm'], {'step_m': 40, 'cutoff_m': 300, 'sigma_m': 100}),
    I('waterfront_access_m', 'scenic_visual', 'Walking distance to waterfront', 'm', 'down',
      'Verify public waterfront entries and their links to walkable paths. Calculate the shortest pedestrian-network route '
      'from each street midpoint to the nearest valid entrance. Shorter distances indicate easier public access to waterfront views.',
      ['waterfront_access', 'parks', 'hydrography', 'osm_walk'], {'cap_m': 3000, 'entrance_water_m': 60}),
    I('inter_n', 'walkability', 'Connected junctions', 'count', 'up',
      'Construct the walkable-road topology from NYC LION segments. Identify junctions meeting at least three segments and '
      'count those within 250 m of each street midpoint. Higher counts indicate more route choices and connections.',
      ['lion'], {'radius_m': 250}),
    I('route_directness', 'walkability', 'Walking-network detour', 'ratio ≥1', 'down',
      'Sample feasible nearby origin–destination pairs around each street. Divide the shortest pedestrian-network distance '
      'by straight-line distance and take the median. Ratios closer to 1 indicate less detour and more direct walking.',
      ['osm_walk'], {'ring_m': [250, 500], 'sectors': 8, 'min_pairs': 3}),
    I('crash_k', 'access_safety', 'Pedestrian-injury crash intensity', 'index', 'down',
      'Filter three years of reported collisions involving pedestrian injury or death. Sum Gaussian proximity weights for '
      'crash points within 120 m (σ = 40 m) and reverse the percentile. Fewer nearby crashes rank higher.',
      ['collisions'], {'step_m': 40, 'cutoff_m': 120, 'sigma_m': 40}),
    I('crime_k', 'access_safety', 'Crime-report proximity', 'index', 'down',
      'Combine NYPD historic and current-YTD complaint records, deduplicate incident IDs, and retain felony and misdemeanor '
      'cases. Sum Gaussian weights for reports within 300 m (σ = 100 m). Fewer reports rank higher, but this remains a proxy '
      'rather than personal risk.',
      ['nypd_complaints'], {'step_m': 40, 'cutoff_m': 300, 'sigma_m': 100}),
    I('hwy_m', 'environment', 'Distance to highways/ramps', 'm', 'up',
      'Measure straight-line distance from each street midpoint to the nearest mapped highway or access ramp. Cap distances '
      'at 1,500 m and rank farther distances higher. This acts as a proximity-based environmental exposure proxy.',
      ['lion'], {'cap_m': 1500}),
    I('impervious_pct', 'environment', 'Impervious surface cover', '%', 'down',
      'Buffer each street by 20 m on both sides and overlay the 2021 classified land-cover raster. Divide impervious-surface '
      'area by total valid raster area × 100. Lower values indicate less nearby hard-surface cover.',
      ['tnc_landcover'], {'buffer_m': 20}),
    I('no2_area_context', 'environment', 'Annual NO₂ area context', 'source units', 'context',
      'Read annual NO₂ concentration using the official DOHMH geography, period, and source units. Use this only as '
      'neighbourhood-scale environmental context; do not assign the value directly to individual street segments.',
      ['dohmh_no2']),
    I('sub_n', 'transit_connectivity', 'Entry-permitted subway entrances', 'count', 'up',
      'Keep only MTA entrances that allow passengers to enter. Count qualifying entrances within 400 m of each street '
      'midpoint. Higher values indicate more nearby access points, not higher service frequency.',
      ['subway'], {'radius_m': 400}),
    I('sub_m', 'transit_connectivity', 'Distance to subway entrance', 'm', 'down',
      'From each street midpoint, find the nearest MTA entrance that permits boarding access. Measure distance, cap it at '
      '1,500 m, and reverse the Manhattan percentile. Shorter distances indicate stronger subway proximity.',
      ['subway'], {'cap_m': 1500}),
]
BY_KEY = {x['key']: x for x in INDICATORS}
SCORED_ROLES = ('up', 'down')

assert len(DIMENSIONS) == 12 and len(INDICATORS) == 24
assert {x['dimension'] for x in INDICATORS} == set(DIM_KEYS)


def indicators_of(dim, scored_only=False):
    return [x for x in INDICATORS if x['dimension'] == dim and (not scored_only or x['role'] in SCORED_ROLES)]


# Data sources named in the "DB" column, with the dataset actually used and where it lives in this repo.
SOURCES = {
    'lion': {'label': 'NYC Street Centerline (LION) — NYC DCP', 'url': 'https://data.cityofnewyork.us/d/inkn-q76z',
             'api': 'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0',
             'file': 'data/cache/sources/streets_v4.json'},
    'lpc': {'label': 'LPC Individual Landmark Lots', 'url': 'https://services5.arcgis.com/Oos4pNA2538iVFA1/ArcGIS/rest/services/Ind_Landmark_Lots_POLY/FeatureServer/0',
            'file': 'data/cache/sources/lpc.json'},
    'trees': {'label': 'NYC Parks Forestry Tree Points (structure = Full)', 'url': 'https://data.cityofnewyork.us/d/hn5i-inap',
              'file': 'data/cache/sources/forestry_trees.json'},
    'parks': {'label': 'NYC Parks Properties', 'url': 'https://data.cityofnewyork.us/d/enfh-gkve', 'file': 'data/cache/sources/parks.json'},
    'tnc_landcover': {'label': 'NYC Land Cover 2021 (6 in) — TNC / UVM Spatial Analysis Lab', 'url': 'https://data.cityofnewyork.us/d/he6d-2qns', 'file': None},
    'osm': {'label': 'OpenStreetMap POIs via Overpass API', 'url': 'https://www.openstreetmap.org', 'file': 'data/cache/sources/osm.json'},
    'osm_walk': {'label': 'OpenStreetMap pedestrian network (OSMnx walk graph)', 'url': 'https://www.openstreetmap.org',
                 'file': 'data/pedestrian/manhattan-walk-graph.json.gz'},
    'noise': {'label': 'NYC 311 Service Requests — Noise*', 'url': 'https://data.cityofnewyork.us/d/erm2-nwe9', 'file': 'data/cache/sources/noise.json'},
    'sidewalks': {'label': 'NYC Planimetric Database: Sidewalk', 'url': 'https://data.cityofnewyork.us/d/52n9-sdep', 'file': 'data/cache/sources/sidewalks.json'},
    'seating': {'label': 'NYC DOT Seating Locations', 'url': 'https://data.cityofnewyork.us/d/esmy-s8q5', 'file': 'data/urban/context/seating.geojson.gz'},
    'ramps': {'label': 'NYC DOT Pedestrian Ramp Locations', 'url': 'https://data.cityofnewyork.us/d/ufzp-rrqu', 'file': 'data/layers/tiles/pedestrian_ramps/*.json'},
    'ped_counts': {'label': 'NYC DOT Bi-Annual Pedestrian Counts', 'url': 'https://data.cityofnewyork.us/d/cqsj-cfgu', 'file': 'data/dimensions/sources/ped_counts.json'},
    'collisions': {'label': 'NYPD Motor Vehicle Collisions — Crashes', 'url': 'https://data.cityofnewyork.us/d/h9gi-nx95', 'file': 'data/cache/sources/collisions.json'},
    'nypd_complaints': {'label': 'NYPD Complaint Data Historic (qgea-i56i) + Current YTD (5uac-w243)', 'url': 'https://data.cityofnewyork.us/d/qgea-i56i',
                        'file': 'data/urban/crime/complaints.sqlite.gz'},
    'waterfront_access': {'label': 'Waterfront Public Access Areas (WPAA)', 'url': 'https://data.cityofnewyork.us/d/388s-pnvc', 'file': 'data/urban/context/waterfront_access.geojson.gz'},
    'hydrography': {'label': 'NYC Planimetric Database: Hydrography', 'url': 'https://data.cityofnewyork.us/d/pjs3-c3z5', 'file': 'data/urban/context/hydrography.geojson.gz'},
    'dohmh_no2': {'label': 'NYC DOHMH Air Quality (NYCCAS annual NO₂)', 'url': 'https://data.cityofnewyork.us/d/c3uy-2p5r', 'file': 'data/dimensions/sources/no2.json'},
    'subway': {'label': 'MTA Subway Entrances and Exits: 2024 (entry allowed)', 'url': 'https://data.ny.gov/d/i9wp-a4ja', 'file': 'data/cache/sources/subway.json'},
}

# Study areas. Midtown pilot = segment midpoints inside this quadrilateral (W 34 St–W 59 St, Hudson–East River).
AREAS = {
    'midtown': {'label': 'Midtown pilot (34th–59th St, river to river)',
                'polygon': [(-74.0040, 40.7570), (-73.9720, 40.7432), (-73.9575, 40.7595), (-73.9935, 40.7738), (-74.0040, 40.7570)]},
    'manhattan': {'label': 'Manhattan (LION borocode 1 incl. Roosevelt & Randalls Is.)', 'polygon': None},
}

SCORE_METHOD = (
    'Each scored indicator → percentile rank 0–100 among segments of the comparison area that have a value '
    '(ties take the lowest rank; "lower is better" indicators reversed as 100 − rank). Dimension score = equal-weight mean '
    'of the indicator percentiles available on that segment. N/A when none is available; missing values are never 0. '
    'Validation/context indicators never enter a score.')
