"""Build the Navigate Urban Data Layers: real NYC / OSM features with their original attributes, plus a registry
that ties every layer to the 12 experience dimensions and their sub-indicators.

Run: python3 scripts/build_urban_layers.py [--refresh]
Writes data/layers/<layer_id>.geojson.gz (Manhattan only) and data/layers/registry.json.
Needs OSMnx/Shapely at build time (Manhattan boundary); the server reads the output with the standard library.
Candidate layers without a connected dataset are listed as unavailable: no points, scores or heatmaps are invented.
"""
import argparse, gzip, json, math, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streetwise_indicators as si

ROOT = si.ROOT
OUT = os.path.join(ROOT, 'data', 'layers')
CACHE = os.path.join(ROOT, 'data', 'cache', 'sources')
GRAPH = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
SOCRATA_VIEW = 'https://data.cityofnewyork.us/api/views/{}.json'
CULTURE = {'museum', 'gallery'}, {'theatre', 'arts_centre', 'cinema', 'library', 'music_venue', 'concert_hall'}
FOOD = {'restaurant', 'cafe', 'bar', 'pub', 'fast_food', 'ice_cream', 'food_court', 'biergarten'}
SCENIC = {('tourism', 'viewpoint'), ('amenity', 'fountain'), ('historic', 'memorial'), ('historic', 'monument')}
OSM_KEEP = ('name', 'amenity', 'shop', 'tourism', 'leisure', 'historic', 'artwork_type', 'cuisine', 'opening_hours', 'website', 'addr:housenumber', 'addr:street', 'operator')


def socrata_updated(view_id, host='https://data.cityofnewyork.us'):
    try:
        d = si.get(f'{host}/api/views/{view_id}.json', timeout=40)
        return datetime.fromtimestamp(d.get('rowsUpdatedAt', 0), timezone.utc).date().isoformat()
    except RuntimeError:
        return None


def arcgis_updated(layer_url):
    try:
        d = si.get(layer_url.replace('/query', ''), {'f': 'json'}, timeout=40)
        e = d.get('editingInfo', {})
        ms = e.get('dataLastEditDate') or e.get('lastEditDate')
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() if ms else None
    except RuntimeError:
        return None


def fetch_osm_full():
    """Same Overpass query as the scoring step, keeping element IDs and descriptive tags for inspection."""
    s, w, n, e = si.BOX[1], si.BOX[0], si.BOX[3], si.BOX[2]
    b = f'{s},{w},{n},{e}'
    q = f'[out:json][timeout:180];(nwr["amenity"]({b});nwr["shop"]({b});nwr["tourism"]({b});nwr["leisure"]({b});nwr["historic"]({b}););out tags center;'
    d = si.get(si.SOURCES['osm'], data=si.parse.urlencode({'data': q}).encode(), timeout=240)
    out = []
    for x in d['elements']:
        lat, lon = (x.get('lat'), x.get('lon')) if x['type'] == 'node' else (x.get('center', {}).get('lat'), x.get('center', {}).get('lon'))
        if lat is not None:
            out.append({'id': f"{x['type']}/{x['id']}", 'lon': lon, 'lat': lat, 'tags': {k: v for k, v in x.get('tags', {}).items() if k in OSM_KEEP}})
    return {'timestamp_osm_base': d.get('osm3s', {}).get('timestamp_osm_base'), 'elements': out}


def point(lon, lat, fid, props):
    return {'type': 'Feature', 'id': str(fid), 'properties': {'feature_id': str(fid), **props}, 'geometry': {'type': 'Point', 'coordinates': [round(lon, 6), round(lat, 6)]}}


def rounded(geom):
    def r(c):
        return [round(c[0], 6), round(c[1], 6)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {'type': geom['type'], 'coordinates': r(geom['coordinates'])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='download every source again')
    args = ap.parse_args()
    import osmnx as ox
    from shapely.geometry import shape, Point
    from shapely.prepared import prep
    ox.settings.use_cache = True; ox.settings.cache_folder = os.path.join(ROOT, 'data', 'cache', 'osmnx'); ox.settings.log_console = False
    boundary = ox.geocode_to_gdf('Manhattan, New York County, New York, United States').geometry.iloc[0]
    inside = prep(boundary.buffer(0.0007))  # ~60 m so shoreline paths and piers stay in
    in_mh = lambda lon, lat: inside.contains(Point(lon, lat))
    touches = lambda g: inside.intersects(shape(g))
    os.makedirs(OUT, exist_ok=True)
    c = lambda name, fn: si.cached(CACHE, name, fn, args.refresh)
    now = si.NOW
    noise_from = (now - si.timedelta(days=365)).strftime('%Y-%m-%dT00:00:00')
    crash_from = (now - si.timedelta(days=365 * 3)).strftime('%Y-%m-%dT00:00:00')
    W, S, E, N = si.BOX
    layers = {}

    print('Downloading layer datasets with attributes…', flush=True)
    trees = c('layer_trees', lambda: si.socrata(si.SOURCES['trees'], 'objectid,genusspecies,dbh,tpcondition,tpstructure,planteddate,updateddate,riskrating,location',
                                                 f"tpstructure='Full' AND within_box(location,{N},{W},{S},{E})"))
    layers['street_trees'] = [point(*r['location']['coordinates'], r['objectid'], {k: r.get(k) for k in ('genusspecies', 'dbh', 'tpcondition', 'tpstructure', 'planteddate', 'updateddate', 'riskrating')})
                              for r in trees if r.get('location') and in_mh(*r['location']['coordinates'])]
    parks = c('layer_parks', lambda: si.socrata(si.SOURCES['parks'], 'gispropnum,signname,typecategory,subcategory,acres,address,multipolygon', "borough='M'"))
    layers['parks'] = [{'type': 'Feature', 'id': p['gispropnum'], 'properties': {'feature_id': p['gispropnum'], **{k: p.get(k) for k in ('signname', 'typecategory', 'subcategory', 'acres', 'address')}},
                        'geometry': rounded(p['multipolygon'])} for p in parks if p.get('multipolygon')]
    lpc = c('layer_lpc', lambda: si.arcgis(si.SOURCES['lpc'], "BORO='Manhattan'", 'LPC_LPNumb,LPC_NAME,Address,DesDate,Style_Prim,Arch_Prima,BuildType,Date_Low,Date_High,URL_REPORT,BBL'))
    layers['landmarks'] = [{'type': 'Feature', 'id': f['properties'].get('LPC_LPNumb') or f"BBL{f['properties'].get('BBL')}",
                            'properties': {'feature_id': f['properties'].get('LPC_LPNumb') or f"BBL{f['properties'].get('BBL')}", **{k: v for k, v in f['properties'].items() if k != 'LPC_LPNumb'}},
                            'geometry': rounded(f['geometry'])} for f in lpc if f.get('geometry') and touches(f['geometry'])]
    side = c('layer_sidewalks', lambda: si.socrata(si.SOURCES['sidewalks'], 'source_id,feat_code,sub_code,status,shape_area,the_geom', f'within_box(the_geom,{N},{W},{S},{E})', 5000))
    layers['sidewalk_surface'] = [{'type': 'Feature', 'id': f"{s.get('source_id')}-{i}", 'properties': {'feature_id': f"{s.get('source_id')}-{i}", 'source_id': s.get('source_id'), 'feat_code': s.get('feat_code'), 'sub_code': s.get('sub_code'), 'status': s.get('status'), 'shape_area_sqft': s.get('shape_area')},
                                   'geometry': rounded(s['the_geom'])} for i, s in enumerate(side) if s.get('the_geom') and touches(s['the_geom'])]
    noise = c('layer_noise', lambda: si.socrata(si.SOURCES['noise'], 'unique_key,created_date,complaint_type,descriptor,location_type,incident_address,status,latitude,longitude',
                                                f"borough='MANHATTAN' AND starts_with(complaint_type,'Noise') AND created_date>='{noise_from}'"))
    layers['noise_complaints'] = [point(float(r['longitude']), float(r['latitude']), r['unique_key'], {k: r.get(k) for k in ('created_date', 'complaint_type', 'descriptor', 'location_type', 'incident_address', 'status')})
                                  for r in noise if r.get('latitude') and r.get('longitude')]
    crashes = c('layer_crashes', lambda: si.socrata(si.SOURCES['collisions'], 'collision_id,crash_date,crash_time,on_street_name,cross_street_name,off_street_name,number_of_pedestrians_injured,number_of_pedestrians_killed,contributing_factor_vehicle_1,latitude,longitude',
                                                    f"borough='MANHATTAN' AND (number_of_pedestrians_injured>0 OR number_of_pedestrians_killed>0) AND crash_date>='{crash_from}'"))
    layers['pedestrian_crashes'] = [point(float(r['longitude']), float(r['latitude']), r['collision_id'], {k: r.get(k) for k in ('crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_pedestrians_injured', 'number_of_pedestrians_killed', 'contributing_factor_vehicle_1')})
                                    for r in crashes if r.get('latitude') and r.get('longitude') and float(r['latitude']) > 40]
    subway = c('layer_subway', lambda: si.socrata(si.SOURCES['subway'], 'station_id,gtfs_stop_id,stop_name,daytime_routes,line,division,entrance_type,entry_allowed,exit_allowed,entrance_latitude,entrance_longitude', "borough='M'"))
    layers['subway_entrances'] = [point(float(r['entrance_longitude']), float(r['entrance_latitude']), f"{r.get('gtfs_stop_id')}-{i}", {k: r.get(k) for k in ('station_id', 'gtfs_stop_id', 'stop_name', 'daytime_routes', 'line', 'division', 'entrance_type', 'entry_allowed', 'exit_allowed')})
                                  for i, r in enumerate(subway) if r.get('entrance_latitude')]
    osm = c('layer_osm', fetch_osm_full)
    osm_points = lambda pred: [point(x['lon'], x['lat'], x['id'], x['tags']) for x in osm['elements'] if pred(x['tags']) and in_mh(x['lon'], x['lat'])]
    layers['cultural_venues'] = osm_points(lambda t: t.get('tourism') in CULTURE[0] or t.get('amenity') in CULTURE[1])
    layers['public_art'] = osm_points(lambda t: t.get('tourism') == 'artwork')
    layers['scenic_points'] = osm_points(lambda t: any(t.get(k) == v for k, v in SCENIC))
    layers['food_drink'] = osm_points(lambda t: t.get('amenity') in FOOD)
    layers['retail'] = osm_points(lambda t: 'shop' in t)
    layers['activity_places'] = osm_points(lambda t: any(k in t for k in ('amenity', 'shop', 'tourism', 'leisure', 'historic')))
    layers['seating'] = osm_points(lambda t: t.get('amenity') == 'bench' or t.get('leisure') == 'picnic_table')

    # Derived from NYC LION (same definitions as the Walkability and Environment indicators).
    raw, _ = si.download_sources(CACHE)
    degree, express = {}, []
    for p, rw, i, line in si.lion_lines(raw):
        if rw in si.LION_WALK_TYPES:
            for end in (line[0], line[-1]):
                k = (round(end[0], 6), round(end[1], 6)); degree[k] = degree.get(k, 0) + 1
        if rw in (2, 9) and any(in_mh(*q) for q in line[::max(1, len(line) // 4)]):
            express.append({'type': 'Feature', 'id': f"{p.get('physicalid')}-{i}", 'properties': {'feature_id': f"{p.get('physicalid')}-{i}", 'lion_physicalid': p.get('physicalid'), 'street_name': p.get('st_label') or p.get('st_name'), 'rw_type': {2: 'Highway', 9: 'Ramp'}[rw]},
                            'geometry': {'type': 'LineString', 'coordinates': [[round(a, 6), round(b, 6)] for a, b in line]}})
    layers['expressways'] = express
    layers['intersections'] = [point(lon, lat, f'X{lon:.6f},{lat:.6f}', {'joining_segments': d}) for (lon, lat), d in degree.items() if d >= 3 and in_mh(lon, lat)]

    # OSM pedestrian network (the routing graph), one feature per shared edge geometry.
    graph = json.load(gzip.open(GRAPH, 'rt', encoding='utf-8'))
    walk = {'osm_sidewalks': [], 'osm_crosswalks': [], 'osm_paths': []}
    for u, v, k, gi, rev, length, osmids, tags in graph['edges']:
        if rev:
            continue
        fw = tags.get('footway'); fw = fw if isinstance(fw, list) else [fw]
        hw = tags.get('highway'); hw = hw if isinstance(hw, list) else [hw]
        kind = 'osm_sidewalks' if 'sidewalk' in fw else 'osm_crosswalks' if 'crossing' in fw else 'osm_paths' if set(hw) & {'footway', 'path', 'pedestrian', 'steps', 'bridleway', 'track', 'corridor'} else None
        if kind:
            walk[kind].append({'type': 'Feature', 'id': f'{u}-{v}-{k}', 'properties': {'feature_id': f'{u}-{v}-{k}', 'osm_way_ids': ' '.join(map(str, osmids)), 'highway': '/'.join(map(str, hw)), 'footway': '/'.join(str(x) for x in fw if x),
                                                                                 'name': tags.get('name') if not isinstance(tags.get('name'), list) else '/'.join(tags['name']), 'surface': tags.get('surface'), 'length_m': length},
                               'geometry': {'type': 'LineString', 'coordinates': graph['geoms'][gi]}})
    layers.update(walk)

    print('Reading dataset update dates…', flush=True)
    upd = {'trees': socrata_updated('hn5i-inap'), 'parks': socrata_updated('enfh-gkve'), 'sidewalks': socrata_updated('52n9-sdep'),
           'noise': socrata_updated('erm2-nwe9'), 'collisions': socrata_updated('h9gi-nx95'), 'subway': socrata_updated('i9wp-a4ja', 'https://data.ny.gov'),
           'lpc': arcgis_updated(si.SOURCES['lpc']), 'streets': arcgis_updated(si.SOURCES['streets']),
           'osm': (osm.get('timestamp_osm_base') or '')[:10] or None, 'graph': graph['metadata']['built_at'][:10]}
    retrieved = now.date().isoformat()
    registry = registry_entries(upd, retrieved, graph['metadata']['network_version'])
    for lid, feats in layers.items():
        with gzip.open(os.path.join(OUT, f'{lid}.geojson.gz'), 'wt', encoding='utf-8') as f:
            json.dump({'type': 'FeatureCollection', 'features': feats}, f, separators=(',', ':'), ensure_ascii=False)
        registry['layers'][lid]['feature_count'] = len(feats)
    missing = [lid for lid, e in registry['layers'].items() if e['status'] == 'available' and lid not in layers]
    assert not missing, missing
    registry['score_version'] = si.score_version()
    registry['indicators'] = {d: [{'key': k, 'label': lb, 'unit': u, 'method': m, 'source': src, 'role': role} for k, lb, u, m, src, role in dim] for d, dim in si.INDICATORS.items()}
    registry['source_labels'] = si.SOURCE_LABELS
    streets = json.load(open(os.path.join(ROOT, 'data', 'manhattan-streets.json'), encoding='utf-8'))['metadata']
    registry['scoring_snapshot'] = {'retrieved_at': streets['retrieved_at'], 'record_counts': streets['record_counts'],
                                    'note': 'Scores were computed from this snapshot; layers show the records retrieved on retrieved/updated dates and can differ by recent additions.'}
    json.dump(registry, open(os.path.join(OUT, 'registry.json'), 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: len(v) for k, v in layers.items()}))


def registry_entries(upd, retrieved, network_version):
    """Layer registry. dims: [(dimension, role, sub-indicator keys)]; role 'scoring' = the records feed that
    sub-indicator, 'context' = shown for orientation only. scoring_distance_m comes from the indicator definition;
    display_distance_m is only the default Along Route display range and never changes a score."""
    S = si.SOURCES
    A = lambda **kw: {'status': 'available', 'retrieved': retrieved, **kw}
    U = lambda name, dims, reason: {'status': 'unavailable', 'name': name, 'dims': dims, 'reason': reason}
    L = {
        'landmarks': A(name='Individual landmarks (LPC)', dataset='NYC LPC Individual Landmark Lots', source='NYC Landmarks Preservation Commission (ArcGIS)', url=S['lpc'], geometry='Polygon',
                       dims=[('architecture', 'scoring', ['lpc_k', 'lpc_n'])], processing='Lot centroid; Gaussian distance decay σ 100 m (cutoff 300 m) along the street', scoring_distance_m=300, display_distance_m=150,
                       updated=upd['lpc'], attributes=['LPC_NAME', 'Address', 'DesDate', 'Style_Prim', 'Arch_Prima', 'BuildType', 'Date_Low', 'Date_High', 'URL_REPORT', 'BBL']),
        'street_trees': A(name='Street & park trees (live)', dataset='NYC Parks Forestry Tree Points (structure = Full)', source='NYC Parks via NYC Open Data', url='https://data.cityofnewyork.us/d/hn5i-inap', geometry='Point',
                          dims=[('nature', 'scoring', ['tree_km', 'tree_n'])], processing='Snapped to the nearest street segment within 30 m, counted per km', scoring_distance_m=30, display_distance_m=30,
                          updated=upd['trees'], attributes=['genusspecies', 'dbh', 'tpcondition', 'tpstructure', 'planteddate', 'updateddate', 'riskrating']),
        'parks': A(name='Parks & green spaces', dataset='NYC Parks Properties', source='NYC Parks via NYC Open Data', url='https://data.cityofnewyork.us/d/enfh-gkve', geometry='Polygon',
                   dims=[('nature', 'scoring', ['park_pct'])], processing='Share of points 0/±20/±40 m from the street inside a park property', scoring_distance_m=40, display_distance_m=40,
                   updated=upd['parks'], attributes=['signname', 'typecategory', 'subcategory', 'acres', 'address']),
        'cultural_venues': A(name='Museums & cultural venues', dataset='OSM museums, galleries, theatres, arts centres, cinemas, libraries, music venues', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                             dims=[('culture', 'scoring', ['cult_k', 'cult_n'])], processing='Gaussian distance decay σ 150 m (cutoff 450 m)', scoring_distance_m=450, display_distance_m=200,
                             updated=upd['osm'], attributes=['name', 'tourism', 'amenity', 'website', 'opening_hours', 'addr:housenumber', 'addr:street']),
        'public_art': A(name='Public art', dataset='OSM tourism=artwork', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                        dims=[('scenic_visual', 'scoring', ['scenic_k', 'scenic_n']), ('culture', 'context', [])], processing='Part of the scenic-feature distance decay σ 100 m (cutoff 300 m); context only for Culture',
                        scoring_distance_m=300, display_distance_m=150, updated=upd['osm'], attributes=['name', 'artwork_type', 'tourism', 'operator']),
        'scenic_points': A(name='Viewpoints, fountains & memorials', dataset='OSM tourism=viewpoint, amenity=fountain, historic=memorial/monument', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                           dims=[('scenic_visual', 'scoring', ['scenic_k', 'scenic_n'])], processing='Gaussian distance decay σ 100 m (cutoff 300 m)', scoring_distance_m=300, display_distance_m=150,
                           updated=upd['osm'], attributes=['name', 'tourism', 'amenity', 'historic']),
        'noise_complaints': A(name='311 noise complaints (12 months)', dataset='NYC 311 Service Requests, complaint type Noise*', source='NYC 311 via NYC Open Data', url='https://data.cityofnewyork.us/d/erm2-nwe9', geometry='Point',
                              dims=[('quiet', 'scoring', ['noise_k', 'noise_n'])], processing='Gaussian distance decay σ 50 m (cutoff 150 m); fewer is quieter. Complaints are reports, not measured sound levels',
                              scoring_distance_m=150, display_distance_m=60, updated=upd['noise'], attributes=['created_date', 'complaint_type', 'descriptor', 'location_type', 'incident_address', 'status']),
        'sidewalk_surface': A(name='Sidewalk surface (planimetric)', dataset='NYC Planimetric Database: Sidewalk', source='NYC OTI via NYC Open Data', url='https://data.cityofnewyork.us/d/52n9-sdep', geometry='Polygon',
                              dims=[('spatial_comfort', 'scoring', ['sidewalk_pct']), ('walkability', 'context', [])], processing='Share of points 5–14 m either side of the street inside sidewalk polygons (sidewalk-width proxy)',
                              scoring_distance_m=14, display_distance_m=25, updated=upd['sidewalks'], attributes=['source_id', 'feat_code', 'sub_code', 'status', 'shape_area_sqft']),
        'seating': A(name='Benches & seating', dataset='OSM amenity=bench, leisure=picnic_table', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                     dims=[('spatial_comfort', 'context', [])], processing='Shown for orientation; not part of any score', scoring_distance_m=None, display_distance_m=60,
                     updated=upd['osm'], attributes=['amenity', 'leisure', 'name']),
        'activity_places': A(name='Activity places (all categories)', dataset='OSM amenity, shop, tourism, leisure, historic features', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                             dims=[('urban_vibrancy', 'scoring', ['vibr_idx', 'poi_n', 'diversity'])], processing='Category diversity × ln(1 + places) within 150 m of the segment midpoint', scoring_distance_m=150, display_distance_m=60,
                             updated=upd['osm'], attributes=['name', 'amenity', 'shop', 'tourism', 'leisure', 'historic']),
        'food_drink': A(name='Restaurants, cafés & bars', dataset='OSM amenity=restaurant/cafe/bar/pub/fast_food/ice_cream/food_court/biergarten', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                        dims=[('food_retail', 'scoring', ['food_k', 'food_km', 'food_n'])], processing='Gaussian distance decay σ 50 m (cutoff 150 m)', scoring_distance_m=150, display_distance_m=60,
                        updated=upd['osm'], attributes=['name', 'amenity', 'cuisine', 'opening_hours', 'addr:housenumber', 'addr:street']),
        'retail': A(name='Shops', dataset='OSM shop=*', source='OpenStreetMap via Overpass API', url=S['osm'], geometry='Point',
                    dims=[('food_retail', 'scoring', ['food_k', 'food_km', 'food_n'])], processing='Gaussian distance decay σ 50 m (cutoff 150 m), together with food & drink', scoring_distance_m=150, display_distance_m=60,
                    updated=upd['osm'], attributes=['name', 'shop', 'opening_hours', 'addr:housenumber', 'addr:street']),
        'intersections': A(name='Street intersections (3+ way)', dataset='Derived from NYC Street Centerline (LION) nodes', source='NYC DCP LION via ArcGIS (derived)', url=S['streets'], geometry='Point',
                           dims=[('walkability', 'scoring', ['inter_n'])], processing='LION nodes joining 3+ walkable segments, counted within 250 m', scoring_distance_m=250, display_distance_m=60,
                           updated=upd['streets'], attributes=['joining_segments']),
        'osm_sidewalks': A(name='Sidewalks (routing network)', dataset='OSM footway=sidewalk edges of the pedestrian graph', source='OpenStreetMap via OSMnx', url='https://www.openstreetmap.org', geometry='LineString',
                           dims=[('walkability', 'context', [])], processing=f'Edges of the routing graph {network_version}; carry LION-matched scores but are not an indicator', scoring_distance_m=None, display_distance_m=30,
                           updated=upd['graph'], attributes=['osm_way_ids', 'highway', 'footway', 'name', 'surface', 'length_m']),
        'osm_crosswalks': A(name='Crosswalks (routing network)', dataset='OSM footway=crossing edges of the pedestrian graph', source='OpenStreetMap via OSMnx', url='https://www.openstreetmap.org', geometry='LineString',
                            dims=[('walkability', 'context', [])], processing='Routing graph edges; context only', scoring_distance_m=None, display_distance_m=30,
                            updated=upd['graph'], attributes=['osm_way_ids', 'highway', 'footway', 'surface', 'length_m']),
        'osm_paths': A(name='Pedestrian paths & steps (routing network)', dataset='OSM footway/path/pedestrian/steps edges of the pedestrian graph', source='OpenStreetMap via OSMnx', url='https://www.openstreetmap.org', geometry='LineString',
                       dims=[('walkability', 'context', [])], processing='Routing graph edges; context only', scoring_distance_m=None, display_distance_m=30,
                       updated=upd['graph'], attributes=['osm_way_ids', 'highway', 'name', 'surface', 'length_m']),
        'pedestrian_crashes': A(name='Pedestrian injury crashes (3 years)', dataset='NYPD Motor Vehicle Collisions – Crashes (pedestrians injured or killed)', source='NYPD via NYC Open Data', url='https://data.cityofnewyork.us/d/h9gi-nx95', geometry='Point',
                                dims=[('access_safety', 'scoring', ['crash_k', 'crash_n'])], processing='Gaussian distance decay σ 40 m (cutoff 120 m); fewer is safer. Not adjusted for pedestrian volume', scoring_distance_m=120, display_distance_m=60,
                                updated=upd['collisions'], attributes=['crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_pedestrians_injured', 'number_of_pedestrians_killed', 'contributing_factor_vehicle_1']),
        'expressways': A(name='Expressways & ramps', dataset='NYC Street Centerline (LION) road types Highway and Ramp', source='NYC DCP LION via ArcGIS', url=S['streets'], geometry='LineString',
                         dims=[('environment', 'scoring', ['hwy_m'])], processing='Distance from the segment midpoint to the nearest expressway/ramp (capped 1,500 m); traffic-pollution exposure proxy', scoring_distance_m=1500, display_distance_m=400,
                         updated=upd['streets'], attributes=['lion_physicalid', 'street_name', 'rw_type']),
        'subway_entrances': A(name='Subway entrances', dataset='MTA Subway Entrances and Exits: 2024', source='MTA via data.ny.gov', url='https://data.ny.gov/d/i9wp-a4ja', geometry='Point',
                              dims=[('transit_connectivity', 'scoring', ['sub_n', 'sub_m'])], processing='Entrances with entry allowed within 400 m, and distance to the nearest one', scoring_distance_m=400, display_distance_m=400,
                              updated=upd['subway'], attributes=['stop_name', 'daytime_routes', 'line', 'division', 'entrance_type', 'entry_allowed', 'exit_allowed', 'station_id', 'gtfs_stop_id']),
        # Candidate layers without a connected dataset.
        'building_footprints': U('Building footprints', [('architecture', 'context', [])], 'NYC Building Footprints not connected yet.'),
        'historic_districts': U('Historic districts', [('architecture', 'context', [])], 'LPC Historic Districts not connected yet; Architecture uses individual landmarks only.'),
        'tree_canopy': U('Tree canopy', [('nature', 'context', [])], 'Canopy (LiDAR land cover raster) not connected; Nature uses tree points and park land.'),
        'traffic_noise': U('Modelled traffic noise', [('quiet', 'context', [])], 'No measured or modelled sound-level layer; Quiet uses 311 complaints and roadway width.'),
        'traffic_volume': U('Traffic volume', [('quiet', 'context', [])], 'NYC DOT traffic counts not connected.'),
        'shade': U('Shade', [('spatial_comfort', 'context', [])], 'No shade model or canopy raster connected.'),
        'sidewalk_amenities': U('Sidewalk amenities (beyond seating)', [('spatial_comfort', 'context', [])], 'Street furniture inventory not connected; benches from OSM are shown under Seating.'),
        'land_use': U('Land use (MapPLUTO)', [('urban_vibrancy', 'context', [])], 'MapPLUTO land use not connected; Vibrancy uses OSM place mix.'),
        'waterfront': U('Waterfront', [('scenic_visual', 'context', [])], 'Waterfront access layer not connected.'),
        'risk_areas': U('Risk areas', [('access_safety', 'context', [])], 'No validated risk-area layer; Safety uses crash records only.'),
        'air_quality': U('Air quality (NYCCAS)', [('environment', 'context', [])], 'NYC Community Air Survey rasters not connected; Environment uses distance to expressways.'),
        'urban_heat': U('Urban heat', [('environment', 'context', [])], 'Heat vulnerability / surface temperature not connected.'),
        'bus_stops': U('Bus stops', [('transit_connectivity', 'context', [])], 'MTA bus stops (GTFS) not connected; Transit uses subway entrances only.'),
    }
    for lid, e in L.items():
        e['id'] = lid
        e['dims'] = [{'dimension': d, 'role': role, 'sub_indicators': subs} for d, role, subs in e['dims']]
        e['role'] = 'scoring' if any(x['role'] == 'scoring' for x in e['dims']) else 'context' if e['status'] == 'available' else 'unavailable'
    return {'built_at': si.NOW.isoformat(timespec='seconds'), 'dimension_order': si.KEYS, 'network_version': network_version, 'layers': L,
            'distances': 'scoring_distance_m = spatial range used by the indicator; display_distance_m = default Along Route display range only (changing it never changes a score).'}


if __name__ == '__main__':
    sys.exit(main())
