"""Build the Navigate Urban Data catalog: real NYC / OSM datasets, cut into static 1 km spatial tiles.

Run: python3 scripts/build_urban_layers.py [--refresh]
Writes data/layers/catalog.json and data/layers/tiles/<tileset>/<tx>_<ty>.json (Manhattan only).
The browser reads these as static files (GitHub Pages or server.py) and filters them along the selected route,
so the backend never has to hold them in memory. Needs OSMnx/Shapely/pyproj at build time only.

Dataset-centred: every entry is a real dataset (or a documented view of one) with its source, update date, time
range, original attributes and whether it feeds the existing experience scores. Candidates without a connected
dataset are listed with a status (AVAILABLE_NOT_CONNECTED / MISSING / UNAVAILABLE) and no features.
"""
import argparse, json, math, os, shutil, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streetwise_indicators as si

ROOT = si.ROOT
OUT = os.path.join(ROOT, 'data', 'layers')
TILES = os.path.join(OUT, 'tiles')
CACHE = os.path.join(ROOT, 'data', 'cache', 'sources')
GRAPH = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
TILE_M = 1000.0
# Local metric projection for the urban-data tiles and urban-geo.js: equirectangular with the WGS84 ellipsoid's
# east-west and north-south scale at 40.78°N, within 0.15 % of the WGS84 geodesic across Manhattan (tested against
# pyproj). Note: routing/engine.py and the scoring scripts still use an older approximation (north-south ~0.46 % short).
LAT0 = 40.78
_A, _E2 = 6378137.0, 0.00669437999014
_W = 1 - _E2 * math.sin(math.radians(LAT0)) ** 2
MX = _A / math.sqrt(_W) * math.cos(math.radians(LAT0)) * math.pi / 180   # metres per degree of longitude
MY = _A * (1 - _E2) / _W ** 1.5 * math.pi / 180                            # metres per degree of latitude
OPEN_DATA = 'https://data.cityofnewyork.us'
NY_DATA = 'https://data.ny.gov'
OSM_KEEP = ('name', 'amenity', 'shop', 'tourism', 'leisure', 'historic', 'artwork_type', 'cuisine', 'opening_hours', 'website',
            'addr:housenumber', 'addr:street', 'operator', 'wheelchair')

CATEGORIES = [
    ('streets', 'Streets & Pedestrian Infrastructure'), ('nature', 'Nature & Green Infrastructure'), ('buildings', 'Buildings & Urban Form'),
    ('heritage', 'Historic & Cultural Places'), ('activities', 'Food, Retail & Urban Activities'), ('safety', 'Traffic & Pedestrian Safety'),
    ('environment', 'Environmental Conditions'), ('transit', 'Transit & Accessibility'), ('services', 'Public Services & Amenities'),
    ('waterfront', 'Waterfront & Public Realm')]


def xy(lon, lat):
    return lon * MX, lat * MY


def tile_of(x, y):
    return int(math.floor(x / TILE_M)), int(math.floor(y / TILE_M))


def coords_of(geom):
    t, c = geom['type'], geom['coordinates']
    if t == 'Point':
        return [c]
    if t in ('LineString', 'MultiPoint'):
        return c
    if t in ('MultiLineString', 'Polygon'):
        return [p for part in c for p in part]
    if t == 'MultiPolygon':
        return [p for poly in c for ring in poly for p in ring]
    return []


def rounded(geom):
    def r(c):
        return [round(c[0], 6), round(c[1], 6)] if isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {'type': geom['type'], 'coordinates': r(geom['coordinates'])}


def feature(fid, props, geom):
    return {'type': 'Feature', 'properties': {'feature_id': str(fid), **{k: v for k, v in props.items() if v not in (None, '')}}, 'geometry': rounded(geom)}


def pt(lon, lat):
    return {'type': 'Point', 'coordinates': [float(lon), float(lat)]}


def write_tiles(tileset, feats):
    """Each feature goes into every 1 km tile its bounding box touches (the client de-duplicates by feature_id)."""
    d = os.path.join(TILES, tileset)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    tiles = {}
    for f in feats:
        pts = coords_of(f['geometry'])
        xs, ys = zip(*(xy(*p) for p in pts))
        (tx0, ty0), (tx1, ty1) = tile_of(min(xs), min(ys)), tile_of(max(xs), max(ys))
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                tiles.setdefault(f'{tx}_{ty}', []).append(f)
    for key, fs in tiles.items():
        with open(os.path.join(d, f'{key}.json'), 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': fs}, fh, separators=(',', ':'), ensure_ascii=False)
    return {k: len(v) for k, v in tiles.items()}


def view_updated(host, view_id):
    try:
        d = si.get(f'{host}/api/views/{view_id}.json', timeout=40)
        return datetime.fromtimestamp(d.get('rowsUpdatedAt', 0), timezone.utc).date().isoformat()
    except RuntimeError:
        return None


def arcgis_updated(layer_url):
    try:
        e = si.get(layer_url.replace('/query', ''), {'f': 'json'}, timeout=40).get('editingInfo', {})
        ms = e.get('dataLastEditDate') or e.get('lastEditDate')
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() if ms else None
    except RuntimeError:
        return None


def overpass(query):
    return si.get(si.SOURCES['osm'], data=si.parse.urlencode({'data': query}).encode(), timeout=240)


def fetch_osm_full():
    s, w, n, e = si.BOX[1], si.BOX[0], si.BOX[3], si.BOX[2]
    b = f'{s},{w},{n},{e}'
    d = overpass(f'[out:json][timeout:180];(nwr["amenity"]({b});nwr["shop"]({b});nwr["tourism"]({b});nwr["leisure"]({b});nwr["historic"]({b}););out tags center;')
    out = []
    for x in d['elements']:
        lat, lon = (x.get('lat'), x.get('lon')) if x['type'] == 'node' else (x.get('center', {}).get('lat'), x.get('center', {}).get('lon'))
        if lat is not None:
            out.append({'id': f"{x['type']}/{x['id']}", 'lon': lon, 'lat': lat, 'tags': {k: v for k, v in x.get('tags', {}).items() if k in OSM_KEEP}})
    return {'timestamp_osm_base': d.get('osm3s', {}).get('timestamp_osm_base'), 'elements': out}


def fetch_osm_street_nodes():
    s, w, n, e = si.BOX[1], si.BOX[0], si.BOX[3], si.BOX[2]
    d = overpass(f'[out:json][timeout:120];node["highway"~"^(bus_stop|traffic_signals)$"]({s},{w},{n},{e});out;')
    keep = ('highway', 'name', 'route_ref', 'shelter', 'bench', 'crossing', 'traffic_signals', 'network', 'operator')
    return {'timestamp_osm_base': d.get('osm3s', {}).get('timestamp_osm_base'),
            'elements': [{'id': f"node/{x['id']}", 'lon': x['lon'], 'lat': x['lat'], 'tags': {k: v for k, v in x.get('tags', {}).items() if k in keep}} for x in d['elements']]}


def fetch_citibike():
    d = si.get('https://gbfs.citibikenyc.com/gbfs/en/station_information.json', timeout=40)
    return {'last_updated': d.get('last_updated'), 'stations': d['data']['stations']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='download every source again')
    args = ap.parse_args()
    import osmnx as ox
    from pyproj import Transformer
    from shapely.geometry import shape, Point
    from shapely.prepared import prep
    ox.settings.use_cache = True; ox.settings.cache_folder = os.path.join(ROOT, 'data', 'cache', 'osmnx'); ox.settings.log_console = False
    boundary = ox.geocode_to_gdf('Manhattan, New York County, New York, United States').geometry.iloc[0]
    inside = prep(boundary.buffer(0.0007))  # ~60 m so shoreline paths and piers stay in
    in_mh = lambda lon, lat: inside.contains(Point(lon, lat))
    touches = lambda g: inside.intersects(shape(g))
    c = lambda name, fn: si.cached(CACHE, name, fn, args.refresh)
    now = si.NOW
    noise_from = (now - si.timedelta(days=365)).strftime('%Y-%m-%dT00:00:00')
    crash_from = (now - si.timedelta(days=365 * 3)).strftime('%Y-%m-%dT00:00:00')
    W, S, E, N = si.BOX
    box = f'{N},{W},{S},{E}'
    soc = lambda view, select, where, page=50000, host=OPEN_DATA: si.socrata(f'{host}/resource/{view}.json', select, where, page)
    T = {}  # tileset id -> features
    rng = {}  # tileset id -> observed time range of the records

    print('Downloading datasets…', flush=True)
    # A. Streets & pedestrian infrastructure
    raw, _ = si.download_sources(CACHE)
    degree, express, centre = {}, [], []
    for p, rw, i, line in si.lion_lines(raw):
        if rw in si.LION_WALK_TYPES:
            for end in (line[0], line[-1]):
                k = (round(end[0], 6), round(end[1], 6)); degree[k] = degree.get(k, 0) + 1
        mid = line[len(line) // 2]
        if not in_mh(*mid):
            continue
        g = {'type': 'LineString', 'coordinates': line}
        props = {'lion_physicalid': p.get('physicalid'), 'street_name': p.get('st_label') or p.get('st_name'),
                 'road_type': {1: 'Street', 2: 'Highway', 3: 'Bridge', 4: 'Tunnel', 5: 'Boardwalk', 6: 'Path/Trail', 7: 'Step street', 8: 'Driveway', 9: 'Ramp', 10: 'Alley', 13: 'U-turn', 14: 'Ferry route'}.get(rw, str(rw)),
                 'street_width_ft': p.get('st_width')}
        centre.append(feature(f"{p.get('physicalid')}-{i}", props, g))
        if rw in (2, 9):
            express.append(feature(f"{p.get('physicalid')}-{i}", props, g))
    T['lion_centerline'] = centre
    T['expressways'] = express
    T['intersections'] = [feature(f'X{lon:.6f},{lat:.6f}', {'joining_segments': d}, pt(lon, lat)) for (lon, lat), d in degree.items() if d >= 3 and in_mh(lon, lat)]
    graph = json.load(__import__('gzip').open(GRAPH, 'rt', encoding='utf-8'))
    walk = {'osm_sidewalks': [], 'osm_crosswalks': [], 'osm_paths': [], 'pedestrian_bridges': []}
    for u, v, k, gi, rev, length, osmids, tags in graph['edges']:
        if rev:
            continue
        fw = tags.get('footway'); fw = fw if isinstance(fw, list) else [fw]
        hw = tags.get('highway'); hw = hw if isinstance(hw, list) else [hw]
        props = {'osm_way_ids': ' '.join(map(str, osmids)), 'highway': '/'.join(map(str, hw)), 'footway': '/'.join(str(x) for x in fw if x),
                 'name': tags.get('name') if not isinstance(tags.get('name'), list) else '/'.join(tags['name']), 'surface': tags.get('surface'), 'length_m': length,
                 'bridge': tags.get('bridge') if not isinstance(tags.get('bridge'), list) else '/'.join(tags['bridge'])}
        f = feature(f'{u}-{v}-{k}', props, {'type': 'LineString', 'coordinates': graph['geoms'][gi]})
        kind = 'osm_sidewalks' if 'sidewalk' in fw else 'osm_crosswalks' if 'crossing' in fw else 'osm_paths' if set(hw) & {'footway', 'path', 'pedestrian', 'steps', 'bridleway', 'track', 'corridor'} else None
        if kind:
            walk[kind].append(f)
        if kind and tags.get('bridge') not in (None, 'no'):
            walk['pedestrian_bridges'].append(f)
    T.update(walk)
    side = c('layer_sidewalks', lambda: soc('52n9-sdep', 'source_id,feat_code,sub_code,status,shape_area,the_geom', f'within_box(the_geom,{box})', 5000))
    T['sidewalk_surface'] = [feature(f"{s.get('source_id')}-{i}", {'source_id': s.get('source_id'), 'feat_code': s.get('feat_code'), 'sub_code': s.get('sub_code'), 'status': s.get('status'), 'shape_area_sqft': s.get('shape_area')}, s['the_geom'])
                             for i, s in enumerate(side) if s.get('the_geom') and touches(s['the_geom'])]
    ramps = c('layer_ramps', lambda: soc('ufzp-rrqu', 'rampid,cornerid,stname1,stname2,ramp_width,ramp_running_slope_total,curb_reveal,dws_conditions,ponding,the_geom', f'within_box(the_geom,{box})'))
    T['pedestrian_ramps'] = [feature(r.get('rampid') or f'ramp-{i}', {k: r.get(k) for k in ('cornerid', 'stname1', 'stname2', 'ramp_width', 'ramp_running_slope_total', 'curb_reveal', 'dws_conditions', 'ponding')}, r['the_geom'])
                             for i, r in enumerate(ramps) if r.get('the_geom') and in_mh(*r['the_geom']['coordinates'])]
    plazas = c('layer_plazas', lambda: soc('k5k6-6jex', 'objectid,plazaname,onstreet,fromstreet,tostreet,partner,boroname,the_geom', "boroname='Manhattan'"))
    T['pedestrian_plazas'] = [feature(p['objectid'], {k: p.get(k) for k in ('plazaname', 'onstreet', 'fromstreet', 'tostreet', 'partner')}, p['the_geom']) for p in plazas if p.get('the_geom')]
    bikes = c('layer_bike_routes', lambda: soc('mzxg-pwib', 'segmentid,street,fromstreet,tostreet,facilitycl,allclasses,bikedir,onoffst,instdate,status,the_geom', f'within_box(the_geom,{box})'))
    T['bike_routes'] = [feature(f"{b.get('segmentid')}-{i}", {k: b.get(k) for k in ('street', 'fromstreet', 'tostreet', 'facilitycl', 'allclasses', 'bikedir', 'onoffst', 'instdate', 'status')}, b['the_geom'])
                        for i, b in enumerate(bikes) if b.get('the_geom') and touches(b['the_geom'])]
    street_nodes = c('layer_osm_street_nodes', fetch_osm_street_nodes)
    T['traffic_signals'] = [feature(x['id'], x['tags'], pt(x['lon'], x['lat'])) for x in street_nodes['elements'] if x['tags'].get('highway') == 'traffic_signals' and in_mh(x['lon'], x['lat'])]
    T['bus_stops'] = [feature(x['id'], x['tags'], pt(x['lon'], x['lat'])) for x in street_nodes['elements'] if x['tags'].get('highway') == 'bus_stop' and in_mh(x['lon'], x['lat'])]
    fountains = c('layer_fountains', lambda: soc('qnv7-p7a2', 'system,fountainty,position,propertyna,featuresta,the_geom', "borough='M'"))
    T['drinking_fountains'] = [feature(f['system'], {'fountain_type': f.get('fountainty'), 'position': f.get('position'), 'property': f.get('propertyna'), 'feature_status': f.get('featuresta')}, f['the_geom']) for f in fountains if f.get('the_geom')]
    rest = c('layer_restrooms', lambda: soc('i7jb-7jku', 'facility_name,location_type,operator,status,open,hours_of_operation,accessibility,restroom_type,changing_stations,website,latitude,longitude', 'latitude IS NOT NULL'))
    T['public_restrooms'] = [feature(f"{r['facility_name']}-{i}", {k: r.get(k) for k in ('facility_name', 'location_type', 'operator', 'status', 'open', 'hours_of_operation', 'accessibility', 'restroom_type', 'changing_stations', 'website')}, pt(r['longitude'], r['latitude']))
                             for i, r in enumerate(rest) if in_mh(float(r['longitude']), float(r['latitude']))]

    # B. Nature
    trees = c('layer_trees', lambda: soc('hn5i-inap', 'objectid,genusspecies,dbh,tpcondition,tpstructure,planteddate,updateddate,riskrating,location', f"tpstructure='Full' AND within_box(location,{box})"))
    T['street_trees'] = [feature(r['objectid'], {k: r.get(k) for k in ('genusspecies', 'dbh', 'tpcondition', 'tpstructure', 'planteddate', 'updateddate', 'riskrating')}, r['location'])
                         for r in trees if r.get('location') and in_mh(*r['location']['coordinates'])]
    parks = c('layer_parks', lambda: soc('enfh-gkve', 'gispropnum,signname,typecategory,subcategory,acres,address,multipolygon', "borough='M'"))
    T['parks'] = [feature(p['gispropnum'], {k: p.get(k) for k in ('signname', 'typecategory', 'subcategory', 'acres', 'address')}, p['multipolygon']) for p in parks if p.get('multipolygon')]
    gardens = c('layer_gardens', lambda: soc('p78i-pat6', 'parksid,gardenname,address,status,juris,openhrsm,openhrstu,openhrsw,openhrsth,openhrsf,openhrssa,openhrssu,multipolygon', "borough='M'"))
    T['community_gardens'] = [feature(g.get('parksid') or g['gardenname'], {k: g.get(k) for k in ('gardenname', 'address', 'status', 'juris', 'openhrsm', 'openhrstu', 'openhrsw', 'openhrsth', 'openhrsf', 'openhrssa', 'openhrssu')}, g['multipolygon'])
                              for g in gardens if g.get('multipolygon')]

    # C. Buildings & urban form
    bld = c('layer_buildings', lambda: soc('5zhs-2jue', 'doitt_id,bin,name,construction_year,height_roof,ground_elevation,feature_code,last_status_type,last_edited_date,base_bbl,the_geom', "starts_with(base_bbl,'1')"))
    T['building_footprints'] = [feature(b.get('doitt_id') or b.get('bin'), {'bin': b.get('bin'), 'name': b.get('name'), 'construction_year': b.get('construction_year'), 'height_roof_ft': b.get('height_roof'),
                                                                           'ground_elevation_ft': b.get('ground_elevation'), 'feature_code': b.get('feature_code'), 'last_status_type': b.get('last_status_type'), 'last_edited_date': b.get('last_edited_date'), 'base_bbl': b.get('base_bbl')}, b['the_geom'])
                                for b in bld if b.get('the_geom')]
    pluto = c('layer_pluto', lambda: soc('64uk-42ks', 'bbl,address,landuse,bldgclass,yearbuilt,numfloors,zonedist1,lotarea,latitude,longitude', "borough='MN' AND latitude IS NOT NULL"))
    LANDUSE = {'1': 'One & two family', '2': 'Multi-family walk-up', '3': 'Multi-family elevator', '4': 'Mixed residential & commercial', '5': 'Commercial & office', '6': 'Industrial & manufacturing',
               '7': 'Transportation & utility', '8': 'Public facilities & institutions', '9': 'Open space & outdoor recreation', '10': 'Parking', '11': 'Vacant land'}
    T['pluto_lots'] = [feature(str(int(float(r['bbl']))), {'address': r.get('address'), 'landuse': r.get('landuse'), 'landuse_name': LANDUSE.get(str(r.get('landuse')).lstrip('0')), 'building_class': r.get('bldgclass'),
                                                           'year_built': r.get('yearbuilt'), 'floors': r.get('numfloors'), 'zoning_district': r.get('zonedist1'), 'lot_area_sqft': r.get('lotarea')}, pt(r['longitude'], r['latitude']))
                       for r in pluto if r.get('latitude')]
    pops = c('layer_pops', lambda: soc('rvih-nhyn', 'pops_number,building_name,building_address_with_zip,public_space_type,year_completed,hour_of_access_required,amenities_required,latitude,longitude', "borough_name='Manhattan' AND latitude IS NOT NULL"))
    T['pops'] = [feature(p['pops_number'], {k: p.get(k) for k in ('building_name', 'building_address_with_zip', 'public_space_type', 'year_completed', 'hour_of_access_required', 'amenities_required')}, pt(p['longitude'], p['latitude'])) for p in pops]

    # D. Historic & cultural
    lpc = c('layer_lpc', lambda: si.arcgis(si.SOURCES['lpc'], "BORO='Manhattan'", 'LPC_LPNumb,LPC_NAME,Address,DesDate,Style_Prim,Arch_Prima,BuildType,Date_Low,Date_High,URL_REPORT,BBL'))
    # ArcGIS returns DesDate as epoch milliseconds; show it as the calendar date it encodes.
    epoch_date = lambda v: datetime.fromtimestamp(v / 1000, timezone.utc).date().isoformat() if isinstance(v, (int, float)) else v
    T['landmarks'] = [feature(f['properties'].get('LPC_LPNumb') or f"BBL{f['properties'].get('BBL')}", {k: epoch_date(v) if k == 'DesDate' else v for k, v in f['properties'].items() if k != 'LPC_LPNumb'}, f['geometry'])
                      for f in lpc if f.get('geometry') and touches(f['geometry'])]
    hd = c('layer_historic_districts', lambda: soc('skyk-mpzq', 'lp_number,area_name,status_of_,desdate,caldate,extension,the_geom', "borough='MN'"))
    # Source geometry is NY State Plane Long Island (EPSG:2263, US feet); convert to WGS84 lon/lat.
    to_wgs = Transformer.from_crs(2263, 4326, always_xy=True).transform

    def reproject(g):
        def r(cs):
            return list(to_wgs(*cs)) if isinstance(cs[0], (int, float)) else [r(x) for x in cs]
        return {'type': g['type'], 'coordinates': r(g['coordinates'])}
    T['historic_districts'] = [feature(h['lp_number'] + (f"-{i}" if h.get('extension') else ''), {'area_name': h.get('area_name'), 'lp_number': h.get('lp_number'), 'status': h.get('status_of_'), 'designated': h.get('desdate'),
                                                                                                    'calendared': h.get('caldate'), 'extension': h.get('extension')}, reproject(h['the_geom'])) for i, h in enumerate(hd) if h.get('the_geom')]
    osm = c('layer_osm', fetch_osm_full)
    osm_layer = lambda pred: [feature(x['id'], x['tags'], pt(x['lon'], x['lat'])) for x in osm['elements'] if pred(x['tags']) and in_mh(x['lon'], x['lat'])]
    T['museums'] = osm_layer(lambda t: t.get('tourism') == 'museum')
    T['galleries'] = osm_layer(lambda t: t.get('tourism') == 'gallery')
    T['theaters'] = osm_layer(lambda t: t.get('amenity') in ('theatre', 'music_venue', 'concert_hall', 'arts_centre'))
    T['cinemas'] = osm_layer(lambda t: t.get('amenity') == 'cinema')
    T['libraries'] = osm_layer(lambda t: t.get('amenity') == 'library')
    T['public_art'] = osm_layer(lambda t: t.get('tourism') == 'artwork')
    T['monuments'] = osm_layer(lambda t: t.get('historic') in ('memorial', 'monument'))
    # E. Food, retail & activities
    T['restaurants'] = osm_layer(lambda t: t.get('amenity') in ('restaurant', 'fast_food', 'food_court'))
    T['cafes'] = osm_layer(lambda t: t.get('amenity') in ('cafe', 'ice_cream'))
    T['bars'] = osm_layer(lambda t: t.get('amenity') in ('bar', 'pub', 'biergarten'))
    T['bakeries'] = osm_layer(lambda t: t.get('shop') in ('bakery', 'pastry'))
    T['grocery'] = osm_layer(lambda t: t.get('shop') in ('supermarket', 'convenience', 'greengrocer', 'deli', 'grocery'))
    T['retail'] = osm_layer(lambda t: 'shop' in t and t['shop'] not in ('bakery', 'pastry', 'supermarket', 'convenience', 'greengrocer', 'deli', 'grocery'))
    T['markets'] = osm_layer(lambda t: t.get('amenity') == 'marketplace')
    T['entertainment'] = osm_layer(lambda t: t.get('amenity') in ('nightclub', 'casino') or t.get('leisure') in ('amusement_arcade', 'bowling_alley', 'escape_game'))
    T['recreation'] = osm_layer(lambda t: t.get('leisure') in ('sports_centre', 'fitness_centre', 'playground', 'pitch', 'swimming_pool', 'track'))
    T['activity_places'] = osm_layer(lambda t: any(k in t for k in ('amenity', 'shop', 'tourism', 'leisure', 'historic')))
    # I. Services (OSM)
    T['hospitals_clinics'] = osm_layer(lambda t: t.get('amenity') in ('hospital', 'clinic', 'doctors'))
    T['pharmacies'] = osm_layer(lambda t: t.get('amenity') == 'pharmacy')
    T['schools'] = osm_layer(lambda t: t.get('amenity') == 'school')
    T['benches'] = osm_layer(lambda t: t.get('amenity') == 'bench' or t.get('leisure') == 'picnic_table')
    T['ferry_terminals'] = osm_layer(lambda t: t.get('amenity') == 'ferry_terminal')
    T['viewpoints'] = osm_layer(lambda t: t.get('tourism') == 'viewpoint')
    link = c('layer_linknyc', lambda: soc('s4kf-3yrf', 'link_site_id,street_address,cross_street_1,cross_street_2,link_installation_status,planned_kiosk_type,link_installation,latitude,longitude', "boro='Manhattan' AND latitude IS NOT NULL"))
    T['linknyc'] = [feature(k['link_site_id'], {x: k.get(x) for x in ('street_address', 'cross_street_1', 'cross_street_2', 'link_installation_status', 'planned_kiosk_type', 'link_installation')}, pt(k['longitude'], k['latitude'])) for k in link]

    # F. Safety
    crashes = c('layer_crashes', lambda: soc('h9gi-nx95', 'collision_id,crash_date,crash_time,on_street_name,cross_street_name,off_street_name,number_of_pedestrians_injured,number_of_pedestrians_killed,contributing_factor_vehicle_1,latitude,longitude',
                                             f"borough='MANHATTAN' AND (number_of_pedestrians_injured>0 OR number_of_pedestrians_killed>0) AND crash_date>='{crash_from}'"))
    cyc = c('layer_cyclist_crashes', lambda: soc('h9gi-nx95', 'collision_id,crash_date,crash_time,on_street_name,cross_street_name,off_street_name,number_of_cyclist_injured,number_of_cyclist_killed,contributing_factor_vehicle_1,latitude,longitude',
                                                 f"borough='MANHATTAN' AND (number_of_cyclist_injured>0 OR number_of_cyclist_killed>0) AND crash_date>='{crash_from}'"))
    valid = lambda r: r.get('latitude') and r.get('longitude') and float(r['latitude']) > 40 and in_mh(float(r['longitude']), float(r['latitude']))
    T['pedestrian_crashes'] = [feature(r['collision_id'], {k: r.get(k) for k in ('crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_pedestrians_injured', 'number_of_pedestrians_killed', 'contributing_factor_vehicle_1')}, pt(r['longitude'], r['latitude'])) for r in crashes if valid(r)]
    T['cyclist_crashes'] = [feature(r['collision_id'], {k: r.get(k) for k in ('crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_cyclist_injured', 'number_of_cyclist_killed', 'contributing_factor_vehicle_1')}, pt(r['longitude'], r['latitude'])) for r in cyc if valid(r)]
    speed = c('layer_speed_limits', lambda: soc('5mad-ntua', 'street,postvz_sl,the_geom', f'within_box(the_geom,{box})'))
    T['speed_limits'] = [feature(f'sl-{i}', {'street': s.get('street'), 'speed_limit_mph': s.get('postvz_sl')}, s['the_geom']) for i, s in enumerate(speed) if s.get('the_geom') and touches(s['the_geom'])]
    # G. Environment
    noise = c('layer_noise', lambda: soc('erm2-nwe9', 'unique_key,created_date,complaint_type,descriptor,location_type,incident_address,status,latitude,longitude', f"borough='MANHATTAN' AND starts_with(complaint_type,'Noise') AND created_date>='{noise_from}'"))
    T['noise_complaints'] = [feature(r['unique_key'], {k: r.get(k) for k in ('created_date', 'complaint_type', 'descriptor', 'location_type', 'incident_address', 'status')}, pt(r['longitude'], r['latitude'])) for r in noise if r.get('latitude') and r.get('longitude')]
    # H. Transit
    stations = c('layer_subway_stations', lambda: soc('39hk-dx4f', 'gtfs_stop_id,station_id,complex_id,stop_name,daytime_routes,line,structure,ada,ada_notes,gtfs_latitude,gtfs_longitude', "borough='M'", host=NY_DATA))
    T['subway_stations'] = [feature(s['gtfs_stop_id'], {k: s.get(k) for k in ('station_id', 'complex_id', 'stop_name', 'daytime_routes', 'line', 'structure', 'ada', 'ada_notes')}, pt(s['gtfs_longitude'], s['gtfs_latitude'])) for s in stations]
    subway = c('layer_subway', lambda: soc('i9wp-a4ja', 'station_id,gtfs_stop_id,stop_name,daytime_routes,line,division,entrance_type,entry_allowed,exit_allowed,entrance_latitude,entrance_longitude', "borough='M'", host=NY_DATA))
    T['subway_entrances'] = [feature(f"{r.get('gtfs_stop_id')}-{i}", {k: r.get(k) for k in ('stop_name', 'daytime_routes', 'line', 'division', 'entrance_type', 'entry_allowed', 'exit_allowed', 'station_id', 'gtfs_stop_id')}, pt(r['entrance_longitude'], r['entrance_latitude']))
                             for i, r in enumerate(subway) if r.get('entrance_latitude')]
    cb = c('layer_citibike', fetch_citibike)
    T['bike_share'] = [feature(s['station_id'], {'name': s.get('name'), 'short_name': s.get('short_name'), 'capacity': s.get('capacity'), 'station_type': s.get('station_type')}, pt(s['lon'], s['lat']))
                       for s in cb['stations'] if in_mh(s['lon'], s['lat'])]

    # Observed time ranges, from the records themselves.
    def span(tileset, field):
        vals = sorted(f['properties'][field][:10] for f in T[tileset] if f['properties'].get(field))
        return f'{vals[0]} to {vals[-1]}' if vals else None
    rng.update({'pedestrian_crashes': span('pedestrian_crashes', 'crash_date'), 'cyclist_crashes': span('cyclist_crashes', 'crash_date'), 'noise_complaints': span('noise_complaints', 'created_date')})

    print('Reading publisher update dates…', flush=True)
    upd = {v: view_updated(OPEN_DATA, v) for v in ('hn5i-inap', 'enfh-gkve', '52n9-sdep', 'erm2-nwe9', 'h9gi-nx95', 'ufzp-rrqu', 'k5k6-6jex', 'mzxg-pwib', 'qnv7-p7a2', 'i7jb-7jku', 'p78i-pat6',
                                                     '5zhs-2jue', '64uk-42ks', 'rvih-nhyn', 'skyk-mpzq', 's4kf-3yrf', '5mad-ntua')}
    upd.update({v: view_updated(NY_DATA, v) for v in ('i9wp-a4ja', '39hk-dx4f')})
    upd['lpc'] = arcgis_updated(si.SOURCES['lpc']); upd['lion'] = arcgis_updated(si.SOURCES['streets'])
    upd['osm'] = (osm.get('timestamp_osm_base') or '')[:10] or None
    upd['osm_nodes'] = (street_nodes.get('timestamp_osm_base') or '')[:10] or None
    upd['graph'] = graph['metadata']['built_at'][:10]
    upd['citibike'] = datetime.fromtimestamp(cb['last_updated'], timezone.utc).date().isoformat() if cb.get('last_updated') else None

    shutil.rmtree(TILES, ignore_errors=True); os.makedirs(TILES)
    manifests = {tid: write_tiles(tid, feats) for tid, feats in T.items()}
    catalog = build_catalog(upd, rng, manifests, {tid: len(f) for tid, f in T.items()}, graph['metadata']['network_version'], noise_from[:10], crash_from[:10])
    for old in os.listdir(OUT):  # previous single-file layers are replaced by tiles
        if old.endswith('.geojson.gz') or old == 'registry.json':
            os.remove(os.path.join(OUT, old))
    json.dump(catalog, open(os.path.join(OUT, 'catalog.json'), 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: len(v) for k, v in T.items()}))


def build_catalog(upd, rng, manifests, counts, network_version, noise_from, crash_from):
    OD = lambda v: f'{OPEN_DATA}/d/{v}'
    NY = lambda v: f'{NY_DATA}/d/{v}'
    OSM = 'https://www.openstreetmap.org'
    # (id, name, categories, tileset, filter, geometry, source, url, updated, time_note, attributes, scoring, extra)
    # scoring: [(dimension, [sub-indicator keys])] — only datasets that feed the existing scores; [] = context only.
    D = []
    add = lambda *a, **kw: D.append((a, kw))
    add('lion_centerline', 'Street centerlines (LION)', ['streets'], 'lion_centerline', None, 'LineString', 'NYC DCP LION via ArcGIS', 'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0', upd['lion'], 'Current edition',
        ['street_name', 'road_type', 'street_width_ft', 'lion_physicalid'], [], note='Road centrelines — the geometry street scores are measured on. Not the walkable network.')
    add('osm_sidewalks', 'Sidewalks (pedestrian network)', ['streets'], 'osm_sidewalks', None, 'LineString', 'OpenStreetMap via OSMnx (routing graph)', OSM, upd['graph'], f'Graph {network_version}', ['name', 'highway', 'footway', 'surface', 'length_m', 'osm_way_ids'], [],
        note='Edges of the routing graph that routes are computed on.')
    add('osm_crosswalks', 'Crosswalks', ['streets', 'safety'], 'osm_crosswalks', None, 'LineString', 'OpenStreetMap via OSMnx (routing graph)', OSM, upd['graph'], f'Graph {network_version}', ['highway', 'footway', 'surface', 'length_m', 'osm_way_ids'], [])
    add('osm_paths', 'Pedestrian paths & steps', ['streets'], 'osm_paths', None, 'LineString', 'OpenStreetMap via OSMnx (routing graph)', OSM, upd['graph'], f'Graph {network_version}', ['name', 'highway', 'surface', 'length_m', 'osm_way_ids'], [])
    add('sidewalk_surface', 'Sidewalk surface (planimetric)', ['streets'], 'sidewalk_surface', None, 'Polygon', 'NYC OTI Planimetric Database', OD('52n9-sdep'), upd['52n9-sdep'], 'Planimetric capture', ['feat_code', 'sub_code', 'status', 'shape_area_sqft', 'source_id'], [('spatial_comfort', ['sidewalk_pct'])])
    add('pedestrian_ramps', 'Pedestrian ramps', ['streets', 'transit'], 'pedestrian_ramps', None, 'Point', 'NYC DOT Pedestrian Ramp Locations', OD('ufzp-rrqu'), upd['ufzp-rrqu'], 'DOT ramp survey (dataset last updated ' + str(upd['ufzp-rrqu']) + ')',
        ['stname1', 'stname2', 'cornerid', 'ramp_width', 'ramp_running_slope_total', 'curb_reveal', 'dws_conditions', 'ponding'], [])
    add('intersections', 'Intersections (3+ way)', ['streets'], 'intersections', None, 'Point', 'Derived from NYC DCP LION', 'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0', upd['lion'], 'Current edition', ['joining_segments'], [('walkability', ['inter_n'])])
    add('traffic_signals', 'Traffic signals', ['streets', 'safety'], 'traffic_signals', None, 'Point', 'OpenStreetMap (highway=traffic_signals)', OSM, upd['osm_nodes'], 'OSM snapshot', ['crossing', 'traffic_signals'], [])
    add('pedestrian_plazas', 'Pedestrian plazas', ['streets', 'waterfront'], 'pedestrian_plazas', None, 'Polygon', 'NYC DOT Pedestrian Plazas', OD('k5k6-6jex'), upd['k5k6-6jex'], 'Current program', ['plazaname', 'onstreet', 'fromstreet', 'tostreet', 'partner'], [])
    add('bike_routes', 'Bicycle lanes & routes', ['streets', 'transit'], 'bike_routes', None, 'LineString', 'NYC DOT Bike Routes', OD('mzxg-pwib'), upd['mzxg-pwib'], 'Current network', ['street', 'fromstreet', 'tostreet', 'facilitycl', 'allclasses', 'bikedir', 'onoffst', 'instdate'], [])
    add('benches', 'Benches & seating', ['streets', 'services', 'waterfront'], 'benches', None, 'Point', 'OpenStreetMap (amenity=bench)', OSM, upd['osm'], 'OSM snapshot', ['amenity', 'leisure', 'name'], [])
    add('drinking_fountains', 'Drinking fountains (NYC Parks)', ['streets', 'services'], 'drinking_fountains', None, 'Point', 'NYC Parks Drinking Fountains', OD('qnv7-p7a2'), upd['qnv7-p7a2'], 'Parks inventory', ['property', 'position', 'fountain_type', 'feature_status'], [])
    add('public_restrooms', 'Public restrooms', ['streets', 'services'], 'public_restrooms', None, 'Point', 'NYC Open Data Public Restrooms', OD('i7jb-7jku'), upd['i7jb-7jku'], 'Operational status as published',
        ['facility_name', 'location_type', 'operator', 'status', 'open', 'hours_of_operation', 'accessibility', 'restroom_type', 'changing_stations', 'website'], [])
    add('street_trees', 'Street trees', ['nature'], 'street_trees', None, 'Point', 'NYC Parks Forestry Tree Points', OD('hn5i-inap'), upd['hn5i-inap'], 'Live inventory (structure = Full)', ['genusspecies', 'dbh', 'tpcondition', 'tpstructure', 'planteddate', 'updateddate', 'riskrating'], [('nature', ['tree_km', 'tree_n'])])
    add('parks', 'Parks & green spaces', ['nature', 'waterfront'], 'parks', None, 'Polygon', 'NYC Parks Properties', OD('enfh-gkve'), upd['enfh-gkve'], 'Current properties', ['signname', 'typecategory', 'subcategory', 'acres', 'address'], [('nature', ['park_pct'])])
    add('natural_areas', 'Natural areas', ['nature'], 'parks', {'typecategory': ['Nature Area']}, 'Polygon', 'NYC Parks Properties (type = Nature Area)', OD('enfh-gkve'), upd['enfh-gkve'], 'Current properties', ['signname', 'typecategory', 'acres', 'address'], [])
    add('waterfront_parks', 'Waterfront parks', ['nature', 'waterfront'], 'parks', {'typecategory': ['Waterfront Facility']}, 'Polygon', 'NYC Parks Properties (type = Waterfront Facility)', OD('enfh-gkve'), upd['enfh-gkve'], 'Current properties', ['signname', 'typecategory', 'acres', 'address'], [])
    add('community_gardens', 'Community gardens', ['nature'], 'community_gardens', None, 'Polygon', 'NYC Parks GreenThumb Garden Info', OD('p78i-pat6'), upd['p78i-pat6'], 'Current program', ['gardenname', 'address', 'status', 'juris', 'openhrsm', 'openhrssa', 'openhrssu'], [])
    add('building_footprints', 'Building footprints', ['buildings'], 'building_footprints', None, 'Polygon', 'NYC Building Footprints', OD('5zhs-2jue'), upd['5zhs-2jue'], 'Current footprints',
        ['name', 'bin', 'construction_year', 'height_roof_ft', 'ground_elevation_ft', 'feature_code', 'last_status_type', 'last_edited_date'], [])
    add('building_heights', 'Building heights', ['buildings'], 'building_footprints', None, 'Polygon', 'NYC Building Footprints (height_roof)', OD('5zhs-2jue'), upd['5zhs-2jue'], 'Roof height in feet', ['name', 'bin', 'height_roof_ft', 'construction_year'], [],
        style={'by': 'height_roof_ft', 'unit': 'ft', 'stops': [[0, '#1d3b49'], [60, '#2a6f8a'], [150, '#3fb0c9'], [300, '#e8d24a'], [600, '#ffe86b']]})
    add('building_age', 'Building year built', ['buildings'], 'building_footprints', None, 'Polygon', 'NYC Building Footprints (construction_year)', OD('5zhs-2jue'), upd['5zhs-2jue'], 'Recorded construction year', ['name', 'bin', 'construction_year', 'height_roof_ft'], [],
        style={'by': 'construction_year', 'unit': '', 'stops': [[1800, '#8a4b2a'], [1900, '#c97c45'], [1940, '#e3b26a'], [1980, '#7fb7c9'], [2020, '#3f7fc9']]})
    add('land_use', 'Land use (tax lots)', ['buildings'], 'pluto_lots', None, 'Point', 'NYC DCP PLUTO', OD('64uk-42ks'), upd['64uk-42ks'], 'PLUTO release; one point per tax lot (no lot polygons)',
        ['address', 'landuse_name', 'building_class', 'year_built', 'floors', 'zoning_district', 'lot_area_sqft'], [], style={'by_category': 'landuse_name'}, note='Shown as lot centroid points: MapPLUTO lot polygons are not connected.')
    add('pops', 'Privately owned public spaces', ['buildings', 'waterfront'], 'pops', None, 'Point', 'NYC DCP POPS', OD('rvih-nhyn'), upd['rvih-nhyn'], 'Current list', ['building_name', 'building_address_with_zip', 'public_space_type', 'year_completed', 'hour_of_access_required', 'amenities_required'], [])
    add('landmarks', 'Historic landmarks (individual)', ['heritage'], 'landmarks', None, 'Polygon', 'NYC Landmarks Preservation Commission', 'https://services5.arcgis.com/Oos4pNA2538iVFA1/ArcGIS/rest/services/Ind_Landmark_Lots_POLY/FeatureServer/0', upd['lpc'], 'Designations to date',
        ['LPC_NAME', 'Address', 'DesDate', 'BuildType', 'Style_Prim', 'Arch_Prima', 'Date_Low', 'Date_High', 'URL_REPORT', 'BBL'], [('architecture', ['lpc_k', 'lpc_n'])], note='Landmark tax lots (polygons).')
    add('historic_districts', 'Historic districts', ['heritage'], 'historic_districts', None, 'Polygon', 'NYC LPC Historic Districts', OD('skyk-mpzq'), upd['skyk-mpzq'], 'Designations to date', ['area_name', 'lp_number', 'status', 'designated', 'calendared', 'extension'], [],
        note='District boundaries; reprojected from NY State Plane (EPSG:2263).')
    for lid, name, tid, tags in (('museums', 'Museums', 'museums', 'tourism=museum'), ('galleries', 'Art galleries', 'galleries', 'tourism=gallery'), ('theaters', 'Theaters & performance venues', 'theaters', 'amenity=theatre/music_venue/concert_hall/arts_centre'),
                                 ('cinemas', 'Cinemas', 'cinemas', 'amenity=cinema'), ('libraries', 'Libraries', 'libraries', 'amenity=library')):
        add(lid, name, ['heritage'] + (['services'] if lid == 'libraries' else []), tid, None, 'Point', f'OpenStreetMap ({tags})', OSM, upd['osm'], 'OSM snapshot', ['name', 'tourism', 'amenity', 'website', 'opening_hours', 'addr:housenumber', 'addr:street', 'wheelchair'], [('culture', ['cult_k', 'cult_n'])])
    add('public_art', 'Public art', ['heritage'], 'public_art', None, 'Point', 'OpenStreetMap (tourism=artwork)', OSM, upd['osm'], 'OSM snapshot', ['name', 'artwork_type', 'operator'], [('scenic_visual', ['scenic_k', 'scenic_n'])])
    add('monuments', 'Monuments & memorials', ['heritage'], 'monuments', None, 'Point', 'OpenStreetMap (historic=monument/memorial)', OSM, upd['osm'], 'OSM snapshot', ['name', 'historic'], [('scenic_visual', ['scenic_k', 'scenic_n'])])
    for lid, name, tags, used in (('restaurants', 'Restaurants', 'amenity=restaurant/fast_food/food_court', True), ('cafes', 'Cafés', 'amenity=cafe/ice_cream', True), ('bars', 'Bars & pubs', 'amenity=bar/pub/biergarten', True),
                                  ('bakeries', 'Bakeries', 'shop=bakery/pastry', True), ('grocery', 'Grocery stores', 'shop=supermarket/convenience/greengrocer/deli', True), ('retail', 'Retail stores', 'other shop=*', True),
                                  ('markets', 'Markets', 'amenity=marketplace', False), ('entertainment', 'Entertainment venues', 'amenity=nightclub/casino, leisure=arcade/bowling', False), ('recreation', 'Recreation facilities', 'leisure=sports_centre/fitness_centre/playground/pitch/pool', False)):
        add(lid, name, ['activities'] + (['services'] if lid == 'recreation' else []), lid, None, 'Point', f'OpenStreetMap ({tags})', OSM, upd['osm'], 'OSM snapshot; open status not verified', ['name', 'amenity', 'shop', 'leisure', 'cuisine', 'opening_hours', 'addr:housenumber', 'addr:street'],
            [('food_retail', ['food_k', 'food_km', 'food_n'])] if used else [])
    add('activity_places', 'All activity places (mix)', ['activities'], 'activity_places', None, 'Point', 'OpenStreetMap (amenity, shop, tourism, leisure, historic)', OSM, upd['osm'], 'OSM snapshot', ['name', 'amenity', 'shop', 'tourism', 'leisure', 'historic'], [('urban_vibrancy', ['vibr_idx', 'poi_n', 'diversity'])])
    add('pedestrian_crashes', 'Pedestrian injury crashes', ['safety'], 'pedestrian_crashes', None, 'Point', 'NYPD Motor Vehicle Collisions – Crashes', OD('h9gi-nx95'), upd['h9gi-nx95'], f"Crashes {rng['pedestrian_crashes']} (3 years)",
        ['crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_pedestrians_injured', 'number_of_pedestrians_killed', 'contributing_factor_vehicle_1'], [('access_safety', ['crash_k', 'crash_n'])], historical=True)
    add('cyclist_crashes', 'Cyclist injury crashes', ['safety'], 'cyclist_crashes', None, 'Point', 'NYPD Motor Vehicle Collisions – Crashes', OD('h9gi-nx95'), upd['h9gi-nx95'], f"Crashes {rng['cyclist_crashes']} (3 years)",
        ['crash_date', 'crash_time', 'on_street_name', 'cross_street_name', 'off_street_name', 'number_of_cyclist_injured', 'number_of_cyclist_killed', 'contributing_factor_vehicle_1'], [], historical=True)
    add('speed_limits', 'Speed limits', ['safety'], 'speed_limits', None, 'LineString', 'NYC DOT Vision Zero View Speed Limits', OD('5mad-ntua'), upd['5mad-ntua'], 'Posted limits as published', ['street', 'speed_limit_mph'], [],
        style={'by': 'speed_limit_mph', 'unit': 'mph', 'stops': [[15, '#3fb0c9'], [25, '#e8d24a'], [35, '#f08a4b'], [50, '#e0475b']]})
    add('noise_complaints', '311 noise complaints', ['environment'], 'noise_complaints', None, 'Point', 'NYC 311 Service Requests (Noise*)', OD('erm2-nwe9'), upd['erm2-nwe9'], f"Complaints {rng['noise_complaints']} (12 months)",
        ['created_date', 'complaint_type', 'descriptor', 'location_type', 'incident_address', 'status'], [('quiet', ['noise_k', 'noise_n'])], historical=True, note='Reports by residents, not sound-level measurements.')
    add('expressways', 'Expressways & ramps (traffic exposure)', ['environment', 'safety'], 'expressways', None, 'LineString', 'NYC DCP LION (road type Highway / Ramp)', 'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0', upd['lion'], 'Current edition', ['street_name', 'road_type', 'lion_physicalid'], [('environment', ['hwy_m'])])
    add('subway_stations', 'Subway stations', ['transit'], 'subway_stations', None, 'Point', 'MTA Subway Stations', NY('39hk-dx4f'), upd['39hk-dx4f'], 'Static station list', ['stop_name', 'daytime_routes', 'line', 'structure', 'ada', 'ada_notes', 'station_id', 'complex_id'], [])
    add('subway_entrances', 'Subway entrances', ['transit'], 'subway_entrances', None, 'Point', 'MTA Subway Entrances and Exits', NY('i9wp-a4ja'), upd['i9wp-a4ja'], 'Static entrance list', ['stop_name', 'daytime_routes', 'entrance_type', 'entry_allowed', 'exit_allowed', 'line', 'station_id', 'gtfs_stop_id'], [('transit_connectivity', ['sub_n', 'sub_m'])])
    add('accessible_entrances', 'Accessible subway entrances (elevator)', ['transit'], 'subway_entrances', {'entrance_type': ['Elevator']}, 'Point', 'MTA Subway Entrances and Exits (entrance type = Elevator)', NY('i9wp-a4ja'), upd['i9wp-a4ja'], 'Static entrance list', ['stop_name', 'daytime_routes', 'entrance_type', 'station_id'], [],
        note='Elevator entrances only; elevator outages are not shown.')
    add('bus_stops', 'Bus stops', ['transit'], 'bus_stops', None, 'Point', 'OpenStreetMap (highway=bus_stop)', OSM, upd['osm_nodes'], 'OSM snapshot', ['name', 'route_ref', 'shelter', 'bench', 'network', 'operator'], [], note='OSM-mapped stops, not the MTA GTFS feed.')
    add('bike_share', 'Citi Bike stations', ['transit'], 'bike_share', None, 'Point', 'Citi Bike GBFS station_information', 'https://gbfs.citibikenyc.com/gbfs/en/station_information.json', upd['citibike'], 'Static station list (live availability not shown)', ['name', 'capacity', 'station_type', 'short_name'], [])
    add('ferry_terminals', 'Ferry terminals', ['transit', 'waterfront'], 'ferry_terminals', None, 'Point', 'OpenStreetMap (amenity=ferry_terminal)', OSM, upd['osm'], 'OSM snapshot', ['name', 'operator'], [])
    add('hospitals_clinics', 'Hospitals & clinics', ['services'], 'hospitals_clinics', None, 'Point', 'OpenStreetMap (amenity=hospital/clinic/doctors)', OSM, upd['osm'], 'OSM snapshot', ['name', 'amenity', 'operator', 'addr:housenumber', 'addr:street'], [])
    add('pharmacies', 'Pharmacies', ['services'], 'pharmacies', None, 'Point', 'OpenStreetMap (amenity=pharmacy)', OSM, upd['osm'], 'OSM snapshot', ['name', 'opening_hours', 'addr:housenumber', 'addr:street'], [])
    add('schools', 'Schools', ['services'], 'schools', None, 'Point', 'OpenStreetMap (amenity=school)', OSM, upd['osm'], 'OSM snapshot', ['name', 'operator', 'addr:housenumber', 'addr:street'], [])
    add('linknyc', 'Public Wi-Fi (LinkNYC)', ['services'], 'linknyc', {'link_installation_status': ['Live']}, 'Point', 'LinkNYC Kiosk Locations', OD('s4kf-3yrf'), upd['s4kf-3yrf'], 'Kiosks with status Live', ['street_address', 'cross_street_1', 'cross_street_2', 'link_installation_status', 'planned_kiosk_type', 'link_installation'], [])
    add('viewpoints', 'Scenic viewpoints', ['waterfront'], 'viewpoints', None, 'Point', 'OpenStreetMap (tourism=viewpoint)', OSM, upd['osm'], 'OSM snapshot', ['name'], [('scenic_visual', ['scenic_k', 'scenic_n'])], note='Mapped viewpoints only; no view-shed analysis.')
    add('pedestrian_bridges', 'Pedestrian bridges', ['waterfront', 'streets'], 'pedestrian_bridges', None, 'LineString', 'OpenStreetMap via OSMnx (routing graph, bridge=*)', OSM, upd['graph'], f'Graph {network_version}', ['name', 'highway', 'bridge', 'length_m', 'osm_way_ids'], [])

    # Not connected — no features are drawn for these.
    U = []
    nc = lambda lid, name, cats, status, source, url, reason: U.append({'id': lid, 'name': name, 'categories': cats, 'status': status, 'source': source, 'source_url': url, 'reason': reason})
    nc('restaurant_inspections', 'Restaurant inspections (DOHMH)', ['activities'], 'AVAILABLE_NOT_CONNECTED', 'NYC DOHMH Restaurant Inspection Results', OD('43nn-pn8j'), 'Inspection records do not show whether a restaurant is open now; OSM listings are used instead.')
    nc('tree_canopy', 'Tree canopy', ['nature'], 'AVAILABLE_NOT_CONNECTED', 'NYC Land Cover 2017 (6 in LiDAR raster)', OD('he6d-2qns'), 'Raster tiles not processed yet.')
    nc('green_infrastructure', 'Green infrastructure / bioswales', ['nature'], 'MISSING', 'NYC DEP (not verified in this audit)', None, 'No verified dataset identified yet.')
    nc('water_bodies', 'Water bodies', ['nature', 'waterfront'], 'MISSING', None, None, 'No dataset connected; the basemap shows water.')
    nc('zoning', 'Zoning districts (polygons)', ['buildings'], 'AVAILABLE_NOT_CONNECTED', 'NYC DCP Zoning GIS data', 'https://www.nyc.gov/site/planning/data-maps/open-data/dwn-gis-zoning.page', 'Polygon download not processed; the zoning code of each lot is shown in Land use.')
    nc('street_wall', 'Street wall / frontage', ['buildings'], 'MISSING', None, None, 'No dataset; would need derivation from footprints.')
    nc('building_entrances', 'Building entrances', ['buildings'], 'MISSING', None, None, 'No reliable citywide dataset.')
    nc('all_collisions', 'All motor vehicle collisions', ['safety'], 'AVAILABLE_NOT_CONNECTED', 'NYPD Motor Vehicle Collisions – Crashes', OD('h9gi-nx95'), 'Only pedestrian and cyclist injury crashes are connected.')
    nc('traffic_volume', 'Traffic volume', ['safety', 'environment'], 'AVAILABLE_NOT_CONNECTED', 'NYC DOT Automated Traffic Volume Counts', OD('7ym2-wayt'), 'Short counts from different years on scattered segments; not comparable along a route without modelling.')
    nc('safety_improvements', 'Pedestrian safety improvements', ['safety'], 'AVAILABLE_NOT_CONNECTED', 'NYC DOT Vision Zero View datasets', 'https://vzv.nyc', 'Not processed yet.')
    nc('street_closures', 'Temporary street closures', ['safety'], 'AVAILABLE_NOT_CONNECTED', 'NYC DOT Street Closures due to Construction', OD('i6b5-j7bu'), 'Time-limited permits need date filtering against the walk time; not connected.')
    nc('air_quality', 'Air quality (NYCCAS)', ['environment'], 'AVAILABLE_NOT_CONNECTED', 'NYC Community Air Survey (Environment & Health Data Portal)', 'https://a816-dohbesp.nyc.gov/IndicatorPublic/', 'Annual modelled surface / neighbourhood averages; not connected, and never a street-level measurement.')
    nc('urban_heat', 'Urban heat / heat vulnerability', ['environment'], 'AVAILABLE_NOT_CONNECTED', 'NYC Heat Vulnerability Index (EH Data Portal)', 'https://a816-dohbesp.nyc.gov/IndicatorPublic/', 'Neighbourhood-level index; not connected.')
    nc('surface_temperature', 'Surface temperature', ['environment'], 'AVAILABLE_NOT_CONNECTED', 'Landsat land surface temperature (USGS)', 'https://earthexplorer.usgs.gov', 'Satellite raster; not processed.')
    nc('shade', 'Shade / solar exposure', ['environment'], 'MISSING', None, None, 'No shade model available.')
    nc('flood_risk', 'Flood risk', ['environment'], 'AVAILABLE_NOT_CONNECTED', 'NYC Stormwater Flood Maps / FEMA', OD('9i7c-xyvv'), 'Not processed yet.')
    nc('air_monitors', 'Air pollution monitoring stations', ['environment'], 'AVAILABLE_NOT_CONNECTED', 'US EPA AirNow / AQS', 'https://www.airnow.gov', 'Not connected.')
    nc('subway_lines', 'Subway lines', ['transit'], 'MISSING', None, None, 'No verified line geometry connected.')
    nc('bus_routes', 'Bus routes', ['transit'], 'AVAILABLE_NOT_CONNECTED', 'MTA GTFS static feeds', 'https://new.mta.info/developers', 'GTFS shapes not processed.')
    nc('transit_status', 'Transit service status (real-time)', ['transit'], 'AVAILABLE_NOT_CONNECTED', 'MTA GTFS-realtime', 'https://new.mta.info/developers', 'Real-time feed; would be managed separately from static layers.')
    nc('waterfront_access', 'Waterfront public access areas', ['waterfront'], 'AVAILABLE_NOT_CONNECTED', 'NYC DCP Waterfront Public Access Areas', OD('jakx-zd39'), 'Published as a map view; feature data not processed.')
    nc('shorelines', 'Shorelines', ['waterfront'], 'MISSING', None, None, 'No dataset connected.')
    nc('waterfront_walkways', 'Waterfront walkways', ['waterfront'], 'MISSING', None, None, 'Cannot be separated reliably from other paths without a dedicated dataset.')

    datasets = []
    for (lid, name, cats, tileset, flt, geom, source, url, updated, time_note, attrs, scoring), kw in D:
        datasets.append({'id': lid, 'name': name, 'categories': cats, 'status': 'CONNECTED', 'tileset': tileset, 'filter': flt, 'geometry': geom,
                         'layer_type': {'Point': 'circle', 'LineString': 'line', 'Polygon': 'fill'}[geom], 'source': source, 'source_url': url,
                         'last_updated': updated, 'time_range': time_note, 'attributes': attrs, 'used_in_scoring': bool(scoring),
                         'scoring': [{'dimension': d, 'sub_indicators': subs} for d, subs in scoring], 'historical': kw.get('historical', False),
                         'note': kw.get('note'), 'style': kw.get('style'), 'min_zoom_view': 13 if counts[tileset] > 20000 else 11, 'default_visible': False,
                         'feature_count': counts[tileset]})
    return {'built_at': si.NOW.isoformat(timespec='seconds'), 'tile_size_m': TILE_M, 'projection': {'lat0': LAT0, 'mx': MX, 'my': MY},
            'categories': [{'id': k, 'name': n} for k, n in CATEGORIES], 'datasets': datasets + U,
            'tilesets': {tid: {'tiles': m, 'features': counts[tid]} for tid, m in manifests.items()},
            'network_version': network_version, 'score_version': si.score_version(),
            'windows': {'noise_from': noise_from, 'crash_from': crash_from},
            'note': 'Display corridors only filter what is drawn; they never change experience scores. Context-only datasets are not part of any score.'}


if __name__ == '__main__':
    sys.exit(main())
