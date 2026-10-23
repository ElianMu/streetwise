"""Shared Streetwise experience indicators: source downloads, spatial measurement and 0-100 scoring.

Used by build_manhattan_streets.py (NYC LION analysis segments, the reference scale) and by
build_pedestrian_network.py (OSM pedestrian edges that match no LION segment), so both are measured
with one definition. Standard library only. Nothing is estimated or filled in: a value that cannot be
measured is None (shown as N/A). Scores are relative ranks within Manhattan, not calibrated scores.
"""
import bisect, hashlib, json, math, os, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib import request, parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX = (-74.030, 40.698, -73.905, 40.882)  # west, south, east, north
# Manhattan borough boundary bounds (OSM/Nominatim, incl. Governors Island) + 500 m; LION records outside are misplaced.
BOROUGH_BOUNDS = (-74.0522, 40.6747, -73.9018, 40.8870)
LAT0 = 40.78
MX, MY = 111320 * math.cos(math.radians(LAT0)), 110540  # metres per degree
UA = {'User-Agent': 'StreetwiseResearchPrototype/0.4'}
NOW = datetime.now(timezone.utc)

SOCRATA = 'https://data.cityofnewyork.us/resource/'
SOURCES = {
    'streets': 'https://services.arcgis.com/V6ZHFr6zdgNZuVG0/ArcGIS/rest/services/NYC_Street_Centerline/FeatureServer/0/query',
    'lpc': 'https://services5.arcgis.com/Oos4pNA2538iVFA1/ArcGIS/rest/services/Ind_Landmark_Lots_POLY/FeatureServer/0/query',
    'trees': SOCRATA + 'hn5i-inap.json',  # NYC Parks Forestry Tree Points (live inventory)
    'parks': SOCRATA + 'enfh-gkve.json',
    'sidewalks': SOCRATA + '52n9-sdep.json',
    'noise': SOCRATA + 'erm2-nwe9.json',
    'collisions': SOCRATA + 'h9gi-nx95.json',
    'subway': 'https://data.ny.gov/resource/i9wp-a4ja.json',
    'osm': 'https://overpass-api.de/api/interpreter',
}


def get(url, params=None, data=None, timeout=120, tries=3):
    if params:
        url += '?' + parse.urlencode(params)
    for attempt in range(tries):
        try:
            req = request.Request(url, data=data, headers=UA)
            with request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # retry transient public-API failures
            if attempt == tries - 1:
                raise RuntimeError(f'{url[:90]}: {e}')
            time.sleep(3 * (attempt + 1))


def cached(cache, name, fn, refresh=False):
    path = cache and os.path.join(cache, name + '.json')
    if path and os.path.exists(path) and not refresh:
        return json.load(open(path))
    t = time.time(); value = fn()
    print(f'  {name}: {len(value)} records in {time.time()-t:.0f}s', flush=True)
    if path:
        json.dump(value, open(path, 'w'))
    return value


def socrata(url, select, where, page=50000):
    out, offset = [], 0
    while True:
        rows = get(url, {'$select': select, '$where': where, '$limit': page, '$offset': offset, '$order': ':id'})
        out += rows; offset += len(rows)
        if len(rows) < page:
            return out


def arcgis(url, where, fields, page=2000):
    out, offset = [], 0
    while True:
        d = get(url, {'where': where, 'outFields': fields, 'outSR': 4326, 'f': 'geojson',
                      'resultOffset': offset, 'resultRecordCount': page, 'orderByFields': 'FID ASC'})
        out += d['features']; offset += len(d['features'])
        if len(d['features']) < page and not d.get('exceededTransferLimit') and not d.get('properties', {}).get('exceededTransferLimit'):
            return out


def latlon_points(rows, lat='latitude', lon='longitude'):
    pts = []
    for r in rows:
        try:
            p = (float(r[lon]), float(r[lat]))
        except (KeyError, TypeError, ValueError):
            continue
        if BOX[0] <= p[0] <= BOX[2] and BOX[1] <= p[1] <= BOX[3]:
            pts.append(p)
    return pts


def fetch_osm():
    s, w, n, e = BOX[1], BOX[0], BOX[3], BOX[2]
    b = f'{s},{w},{n},{e}'
    q = (f'[out:json][timeout:180];('
         f'nwr["amenity"]({b});nwr["shop"]({b});nwr["tourism"]({b});nwr["leisure"]({b});'
         f'nwr["historic"]({b});'
         f');out tags center;')
    d = get(SOURCES['osm'], data=parse.urlencode({'data': q}).encode(), timeout=240)
    out = []
    for x in d['elements']:
        lat, lon = (x.get('lat'), x.get('lon')) if x['type'] == 'node' else (x.get('center', {}).get('lat'), x.get('center', {}).get('lon'))
        if lat is None:
            continue
        t = x.get('tags', {})
        out.append([lon, lat, {k: t[k] for k in ('amenity', 'shop', 'tourism', 'leisure', 'historic', 'name') if k in t}])
    return out


# --- geometry helpers (local metric plane) ---------------------------------------------------
def xy(p):
    return ((p[0] - BOX[0]) * MX, (p[1] - BOX[1]) * MY)


def lonlat(x, y):
    return (BOX[0] + x / MX, BOX[1] + y / MY)


def rings_of(geom):
    if not geom:
        return []
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates'] if geom['type'] == 'MultiPolygon' else []
    return [[[xy(p) for p in ring] for ring in poly] for poly in polys]


def in_ring(p, ring):
    yes = False
    j = len(ring) - 1
    for i in range(len(ring)):
        a, b = ring[i], ring[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            yes = not yes
        j = i
    return yes


def entropy(counts):
    total = sum(counts.values())
    if total < 2:
        return 0.0
    return -sum(c / total * math.log(c / total) for c in counts.values() if c) / math.log(len(counts)) if len(counts) > 1 else 0.0


def percentiles(values, invert=False):
    """Percentile rank (0-100) inside Manhattan; tied values take the lowest rank, so 'no records' sits at the bottom."""
    keys = sorted(values, key=lambda k: values[k])
    n = len(keys); out = {}; i = 0
    while i < n:
        j = i
        while j + 1 < n and values[keys[j + 1]] == values[keys[i]]:
            j += 1
        pct = i / max(n - 1, 1) * 100
        for k in keys[i:j + 1]:
            out[k] = round(100 - pct if invert else pct, 1)
        i = j + 1
    return out



INDICATORS = {
    'architecture': [
        ('lpc_k', 'Landmark proximity', 'decay-weighted landmarks', 'Gaussian distance decay Σexp(−d²/2σ²), σ 100 m, cutoff 300 m, mean of points every 40 m along the segment', 'lpc', 'up'),
        ('lpc_n', 'Individual landmarks within 150 m', 'landmarks', 'Landmark lot centroids within 150 m of the segment midpoint', 'lpc', 'context')],
    'nature': [
        ('tree_km', 'Living street trees per km', 'trees / km', 'Trees with structure "Full" within 30 m, snapped to the nearest segment, ÷ length (80 m floor)', 'trees', 'up'),
        ('park_pct', 'Beside parkland', '% of samples', 'Share of points 0/±20/±40 m from the centreline inside NYC Parks properties', 'parks', 'up'),
        ('tree_n', 'Living trees along segment', 'trees', 'Raw count behind trees per km', 'trees', 'context')],
    'culture': [
        ('cult_k', 'Cultural venue proximity', 'decay-weighted venues', 'Gaussian distance decay, σ 150 m, cutoff 450 m: museums, galleries, theatres, arts centres, cinemas, libraries, music venues', 'osm', 'up'),
        ('cult_n', 'Cultural venues within 200 m', 'venues', 'Count within 200 m of the segment midpoint', 'osm', 'context')],
    'quiet': [
        ('noise_k', '311 noise complaint intensity', 'decay-weighted complaints', 'Gaussian distance decay, σ 50 m, cutoff 150 m, last 12 months; fewer is better. Reporting depends on who calls 311', 'noise', 'down'),
        ('width_ft', 'Roadway width', 'ft', 'LION street width; narrower carries less through-traffic noise. N/A where NYC does not record a width', 'streets', 'down'),
        ('noise_n', 'Noise complaints along segment', 'complaints', 'Complaints within 40 m, snapped to the nearest segment', 'noise', 'context')],
    'spatial_comfort': [
        ('sidewalk_pct', 'Sidewalk surface beside the street', '% of samples', 'Share of points 5/8/11/14 m either side of the centreline inside planimetric sidewalk polygons (a sidewalk-width proxy). N/A on park paths and step streets', 'sidewalks', 'up')],
    'urban_vibrancy': [
        ('vibr_idx', 'Activity mix index', 'index', 'Normalised Shannon diversity of place categories × ln(1 + places), within 150 m', 'osm', 'up'),
        ('poi_n', 'Places within 150 m', 'places', 'OSM amenity, shop, tourism, leisure and historic features', 'osm', 'context'),
        ('diversity', 'Category diversity', '0–1', 'Normalised Shannon entropy of those places', 'osm', 'context')],
    'food_retail': [
        ('food_k', 'Food & shop proximity', 'decay-weighted places', 'Gaussian distance decay, σ 50 m, cutoff 150 m: restaurants, cafés, bars, fast food and all shops', 'osm', 'up'),
        ('food_km', 'Food & shops per km', 'places / km', 'Places within 60 m snapped to the nearest segment ÷ length (80 m floor)', 'osm', 'context'),
        ('food_n', 'Food & shops along segment', 'places', 'Raw count behind places per km', 'osm', 'context')],
    'scenic_visual': [
        ('scenic_k', 'Scenic feature proximity', 'decay-weighted features', 'Gaussian distance decay, σ 100 m, cutoff 300 m: viewpoints, public artworks, fountains, memorials, monuments', 'osm', 'up'),
        ('scenic_n', 'Scenic features within 150 m', 'features', 'Count within 150 m of the segment midpoint', 'osm', 'context')],
    'walkability': [
        ('inter_n', 'Intersections within 250 m', 'intersections', 'Centreline nodes joining 3+ walkable segments (streets, paths, step streets, alleys) within 250 m of the midpoint', 'streets', 'up')],
    'access_safety': [
        ('crash_k', 'Pedestrian injury crash intensity', 'decay-weighted crashes', 'Gaussian distance decay, σ 40 m, cutoff 120 m, crashes injuring or killing pedestrians, last 3 years; fewer is better. Not adjusted for pedestrian volume', 'collisions', 'down'),
        ('crash_n', 'Pedestrian injury crashes within 25 m', 'crashes', 'Count within 25 m of the segment, last 3 years', 'collisions', 'context')],
    'environment': [
        ('hwy_m', 'Distance to expressway or ramp', 'm', 'Midpoint to nearest expressway/ramp centreline, capped at 1,500 m; farther means less traffic-pollution exposure', 'streets', 'up')],
    'transit_connectivity': [
        ('sub_n', 'Subway entrances within 400 m', 'entrances', 'Entrances with entry allowed within 400 m of the midpoint', 'subway', 'up'),
        ('sub_m', 'Distance to nearest subway entrance', 'm', 'Midpoint to nearest entrance, capped at 1,500 m', 'subway', 'down')],
}
KEYS = list(INDICATORS)
CULTURE_TAGS = {('amenity', v) for v in ('theatre', 'arts_centre', 'cinema', 'library', 'music_venue', 'concert_hall')} | {('tourism', v) for v in ('museum', 'gallery')}
FOOD_AMENITY = {'restaurant', 'cafe', 'bar', 'pub', 'fast_food', 'ice_cream', 'food_court', 'biergarten'}
SCENIC_TAGS = {('tourism', 'viewpoint'), ('tourism', 'artwork'), ('amenity', 'fountain'), ('historic', 'memorial'), ('historic', 'monument')}
LION_WALK_TYPES = {1, 6, 7, 10}


def score_version():
    """Changes whenever an indicator definition changes, so cached edge scores can be checked against it."""
    spec = json.dumps({d: [x[:2] + x[3:] for x in dim] for d, dim in INDICATORS.items()}, sort_keys=True)
    return 'sw-score-' + hashlib.sha1(spec.encode()).hexdigest()[:10]


def download_sources(cache=None, refresh=False):
    if cache:
        os.makedirs(cache, exist_ok=True)
    noise_from = (NOW - timedelta(days=365)).strftime('%Y-%m-%dT00:00:00')
    crash_from = (NOW - timedelta(days=365 * 3)).strftime('%Y-%m-%dT00:00:00')
    box_where = f'within_box(the_geom,{BOX[3]},{BOX[0]},{BOX[1]},{BOX[2]})'
    jobs = {
        'streets_v4': lambda: arcgis(SOURCES['streets'], "borocode='1'", 'FID,physicalid,rw_type,st_label,st_name,st_width'),
        'lpc': lambda: arcgis(SOURCES['lpc'], "BORO='Manhattan'", 'FID,LPC_NAME'),
        'forestry_trees': lambda: [p['location']['coordinates'] for p in socrata(SOURCES['trees'], 'location', f"tpstructure='Full' AND within_box(location,{BOX[3]},{BOX[0]},{BOX[1]},{BOX[2]})") if p.get('location')],
        'parks': lambda: socrata(SOURCES['parks'], 'signname,typecategory,multipolygon', "borough='M'"),
        'sidewalks': lambda: socrata(SOURCES['sidewalks'], 'the_geom', box_where, 5000),
        'noise': lambda: latlon_points(socrata(SOURCES['noise'], 'latitude,longitude', f"borough='MANHATTAN' AND starts_with(complaint_type,'Noise') AND created_date>='{noise_from}'")),
        'collisions': lambda: latlon_points(socrata(SOURCES['collisions'], 'latitude,longitude', f"borough='MANHATTAN' AND (number_of_pedestrians_injured>0 OR number_of_pedestrians_killed>0) AND crash_date>='{crash_from}'")),
        'subway': lambda: latlon_points(socrata(SOURCES['subway'], 'entrance_latitude,entrance_longitude', "borough='M' AND entry_allowed='YES'"), 'entrance_latitude', 'entrance_longitude'),
        'osm': fetch_osm,
    }
    print('Downloading public sources…', flush=True)
    with ThreadPoolExecutor(4) as pool:
        futures = {k: pool.submit(cached, cache, k, fn, refresh) for k, fn in jobs.items()}
        raw = {k: f.result() for k, f in futures.items()}
    return raw, {'noise_window_from': noise_from[:10], 'collision_window_from': crash_from[:10]}


def lion_lines(raw):
    """(properties, rw_type, part index, line) for every LION centerline part."""
    for f in raw['streets_v4']:
        g, p = f.get('geometry') or {}, f.get('properties') or {}
        lines = [g['coordinates']] if g.get('type') == 'LineString' else g.get('coordinates', []) if g.get('type') == 'MultiLineString' else []
        for i, line in enumerate(lines):
            if len(line) >= 2:
                yield p, p.get('rw_type'), i, line


def make_item(line, **extra):
    pts = [xy(q) for q in line]
    return {'line': line, 'pts': pts, 'len': sum(math.dist(a, b) for a, b in zip(pts, pts[1:])), **extra}


class Measurer:
    """Measures the raw sub-indicators for any set of street lines (dicts from make_item, with 'path' and 'width')."""
    B = 100  # bucket size in metres for spatial indexes

    def __init__(self, raw):
        self.raw = raw
        degree, self.highway_pts = {}, []
        for p, rw, i, line in lion_lines(raw):
            if rw in LION_WALK_TYPES:
                for end in (line[0], line[-1]):
                    k = (round(end[0], 6), round(end[1], 6)); degree[k] = degree.get(k, 0) + 1
            if rw in (2, 9):  # expressway and ramp centerlines: densify to 25 m samples
                for a, b in zip(line, line[1:]):
                    n = max(1, int(math.dist(xy(a), xy(b)) // 25))
                    self.highway_pts += [(a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n) for t in range(n)]
        self.intersections = [k for k, d in degree.items() if d >= 3]
        osm = raw['osm']
        has = lambda t, pairs: any(t.get(k) == v for k, v in pairs)
        self.lpc_pts = [p for p in map(self.lpc_point, raw['lpc']) if p]
        self.culture_pts = [p[:2] for p in osm if has(p[2], CULTURE_TAGS)]
        self.food_pts = [p[:2] for p in osm if p[2].get('amenity') in FOOD_AMENITY or 'shop' in p[2]]
        self.scenic_pts = [p[:2] for p in osm if has(p[2], SCENIC_TAGS)]
        self.poi_grid = {}
        for lon, lat, t in osm:
            cat = next((('shop' if key == 'shop' else f'{key}={t[key]}') for key in ('amenity', 'shop', 'tourism', 'leisure', 'historic') if key in t), None)
            if cat:
                p = xy((lon, lat)); self.poi_grid.setdefault((int(p[0] // 150), int(p[1] // 150)), []).append((p, cat))
        self.park_polys = [r for row in raw['parks'] for r in rings_of(row.get('multipolygon'))]
        self.sidewalk_polys = [r for row in raw['sidewalks'] for r in rings_of(row.get('the_geom'))]

    @staticmethod
    def lpc_point(f):
        rings = rings_of(f.get('geometry'))
        if not rings:
            return None
        pts = rings[0][0]
        return lonlat(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def measure(self, segs, nearest_snap=True):
        """Raw values per segment. nearest_snap: records snap to their nearest segment in `segs` (the LION reference
        definition); False counts every record within the distance (for OSM edges measured on their own)."""
        B, raw = self.B, self.raw
        seg_index = {}
        for s_i, s in enumerate(segs):
            for a, b in zip(s['pts'], s['pts'][1:]):
                for gx in range(int((min(a[0], b[0]) - 60) // B), int((max(a[0], b[0]) + 60) // B) + 1):
                    for gy in range(int((min(a[1], b[1]) - 60) // B), int((max(a[1], b[1]) + 60) // B) + 1):
                        bucket = seg_index.setdefault((gx, gy), [])
                        if not bucket or bucket[-1] != s_i:
                            bucket.append(s_i)

        def seg_dist(p, s):
            best = float('inf')
            for a, b in zip(s['pts'], s['pts'][1:]):
                ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], p[0] - a[0], p[1] - a[1]
                l2 = ux * ux + uy * uy
                t = max(0.0, min(1.0, (vx * ux + vy * uy) / l2)) if l2 else 0.0
                best = min(best, math.hypot(vx - t * ux, vy - t * uy))
            return best

        def snap(points, maxd, every=False):
            """Assign each point to its nearest segment within maxd metres (or to every segment within maxd)."""
            hits = [0] * len(segs)
            every = every or not nearest_snap
            for q in points:
                p = xy(q)
                cands = [(seg_dist(p, segs[i]), i) for i in set(seg_index.get((int(p[0] // B), int(p[1] // B)), ()))]
                cands = [c for c in cands if c[0] <= maxd]
                for d, i in (cands if every else [min(cands)] if cands else []):
                    hits[i] += 1
            return hits

        def midpoint(s):
            half, run = s['len'] / 2, 0.0
            for a, b in zip(s['pts'], s['pts'][1:]):
                d = math.dist(a, b)
                if run + d >= half:
                    t = (half - run) / d if d else 0
                    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                run += d
            return s['pts'][-1]

        mids = [midpoint(s) for s in segs]

        def near(points, radius):
            grid = {}
            for q in points:
                x, y = xy(q); grid.setdefault((int(x // radius), int(y // radius)), []).append((x, y))
            out = []
            for cx, cy in mids:
                gx, gy = int(cx // radius), int(cy // radius)
                out.append(sum(1 for i in (-1, 0, 1) for j in (-1, 0, 1) for (x, y) in grid.get((gx + i, gy + j), ()) if math.hypot(x - cx, y - cy) <= radius))
            return out

        samples = []  # points every ~40 m along each segment (at least its midpoint)
        for s, mid in zip(segs, mids):
            n = max(1, round(s['len'] / 40)); pts, run, out = s['pts'], 0.0, []
            targets = [(k + .5) * s['len'] / n for k in range(n)]
            for a, b in zip(pts, pts[1:]):
                d = math.dist(a, b)
                while targets and targets[0] <= run + d:
                    t = (targets.pop(0) - run) / d if d else 0
                    out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                run += d
            samples.append(out or [mid])

        def kernel(points, sigma, cutoff):
            """Gaussian distance-decay intensity: mean over a segment's samples of sum exp(-d²/2σ²) for points within cutoff."""
            grid = {}
            for q in points:
                x, y = xy(q); grid.setdefault((int(x // cutoff), int(y // cutoff)), []).append((x, y))
            k2, out = 2 * sigma * sigma, []
            for smp in samples:
                total = 0.0
                for cx, cy in smp:
                    gx, gy = int(cx // cutoff), int(cy // cutoff)
                    for i in (-1, 0, 1):
                        for j in (-1, 0, 1):
                            for x, y in grid.get((gx + i, gy + j), ()):
                                d2 = (x - cx) ** 2 + (y - cy) ** 2
                                if d2 <= cutoff * cutoff:
                                    total += math.exp(-d2 / k2)
                out.append(total / len(smp))
            return out

        def side_share(polys, offsets, step=20):
            """Share of sample points beside each segment (perpendicular offsets, metres) inside the polygons."""
            index = {}
            for k, poly in enumerate(polys):
                xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
                box = (min(xs), min(ys), max(xs), max(ys))
                for gx in range(int(box[0] // B), int(box[2] // B) + 1):
                    for gy in range(int(box[1] // B), int(box[3] // B) + 1):
                        index.setdefault((gx, gy), []).append((k, box))
            out = []
            for s in segs:
                hit = total = 0
                for a, b in zip(s['pts'], s['pts'][1:]):
                    d = math.dist(a, b)
                    if not d:
                        continue
                    nx, ny = -(b[1] - a[1]) / d, (b[0] - a[0]) / d
                    for t in range(max(1, int(d // step))):
                        f = (t + .5) / max(1, int(d // step))
                        cx, cy = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                        for o in offsets:
                            p = (cx + nx * o, cy + ny * o); total += 1
                            for k, (x0, y0, x1, y1) in index.get((int(p[0] // B), int(p[1] // B)), ()):
                                if x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and in_ring(p, polys[k][0]) and not any(in_ring(p, h) for h in polys[k][1:]):
                                    hit += 1; break
                out.append(hit / total if total else 0.0)
            return out

        def nearest(points, cap=1500.0):
            """Metres from each segment midpoint to the nearest point, capped."""
            grid = {}
            for q in points:
                x, y = xy(q); grid.setdefault((int(x // 250), int(y // 250)), []).append((x, y))
            out = []
            for cx, cy in mids:
                gx, gy, best = int(cx // 250), int(cy // 250), cap
                for r in range(int(cap // 250) + 2):
                    for i in range(-r, r + 1):
                        for j in range(-r, r + 1):
                            if max(abs(i), abs(j)) == r:
                                for x, y in grid.get((gx + i, gy + j), ()):
                                    best = min(best, math.hypot(x - cx, y - cy))
                    if best <= r * 250:
                        break
                out.append(best)
            return out

        trees = snap(raw['forestry_trees'], 30)
        lpc, culture, scenic = near(self.lpc_pts, 150), near(self.culture_pts, 200), near(self.scenic_pts, 150)
        food = snap(self.food_pts, 60)
        noise = snap(raw['noise'], 40)
        crashes = snap(raw['collisions'], 25, every=True)
        print('  distance-decay kernels…', flush=True)
        k_lpc, k_culture, k_scenic = kernel(self.lpc_pts, 100, 300), kernel(self.culture_pts, 150, 450), kernel(self.scenic_pts, 100, 300)
        k_food, k_noise, k_crash = kernel(self.food_pts, 50, 150), kernel(raw['noise'], 50, 150), kernel(raw['collisions'], 40, 120)
        vibr, vibr_div, poi_n = [], [], []
        for cx, cy in mids:  # land-use mix within 150 m of each segment midpoint
            mix = {}
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    for p, cat in self.poi_grid.get((int(cx // 150) + i, int(cy // 150) + j), ()):
                        if math.hypot(p[0] - cx, p[1] - cy) <= 150:
                            mix[cat] = mix.get(cat, 0) + 1
            n = sum(mix.values()); poi_n.append(n); vibr.append(entropy(mix) * math.log1p(n)); vibr_div.append(entropy(mix))
        inter = near(self.intersections, 250)
        subway = near(raw['subway'], 400)
        highway = nearest(self.highway_pts)  # metres to the nearest expressway/ramp centerline, capped at 1500 m
        subway_dist = nearest(raw['subway'])
        park = side_share(self.park_polys, (0, -20, 20, -40, 40))
        sidewalk = side_share(self.sidewalk_polys, (-5, 5, -8, 8, -11, 11, -14, 14))

        km = [max(s['len'], 80) / 1000 for s in segs]  # 80 m floor keeps very short stubs from spiking rates
        n = len(segs)
        r1, r2 = lambda v: round(v, 1), lambda v: round(v, 2)
        # Raw sub-indicator values per segment. None = not measurable for this segment (shown as N/A, never filled).
        return {
            'lpc_k': [r2(v) for v in k_lpc], 'lpc_n': lpc,
            'tree_km': [r1(trees[i] / km[i]) for i in range(n)], 'tree_n': trees, 'park_pct': [round(v * 100) for v in park],
            'cult_k': [r2(v) for v in k_culture], 'cult_n': culture,
            'noise_k': [r2(v) for v in k_noise], 'noise_n': noise, 'width_ft': [s.get('width') for s in segs],
            'sidewalk_pct': [None if s.get('path') else round(sidewalk[i] * 100) for i, s in enumerate(segs)],
            'poi_n': poi_n, 'diversity': [r2(v) for v in vibr_div], 'vibr_idx': [r2(v) for v in vibr],
            'food_k': [r2(v) for v in k_food], 'food_n': food, 'food_km': [r1(food[i] / km[i]) for i in range(n)],
            'scenic_k': [r2(v) for v in k_scenic], 'scenic_n': scenic,
            'inter_n': inter,
            'crash_k': [r2(v) for v in k_crash], 'crash_n': crashes,
            'hwy_m': [round(v) for v in highway],
            'sub_n': subway, 'sub_m': [round(v) for v in subway_dist],
        }


def scored_keys(dim):
    return [(k, role) for k, *_, role in INDICATORS[dim] if role != 'context']


def score_reference(values):
    """Percentile ranks of the reference set (LION analysis segments) and 12 dimension scores per segment."""
    n = len(next(iter(values.values())))
    ranks = {}
    for dim in KEYS:
        for key, role in scored_keys(dim):
            avail = {i: v for i, v in enumerate(values[key]) if v is not None}
            ranks[key] = percentiles(avail, invert=(role == 'down'))
    scores = {}
    for dim in KEYS:
        scores[dim] = []
        for i in range(n):
            got = [ranks[k][i] for k, _ in scored_keys(dim) if i in ranks[k]]
            scores[dim].append(round(sum(got) / len(got)) if got else None)
    return scores


def score_against(reference, values):
    """Score new lines on the reference scale: each value takes the percentile it would hold among the reference
    values (same lowest-rank-for-ties rule), so OSM-measured and LION scores mean the same thing."""
    ref = {}
    for dim in KEYS:
        for key, role in scored_keys(dim):
            ref[key] = sorted(v for v in reference[key] if v is not None)
    n = len(next(iter(values.values())))
    scores = {}
    for dim in KEYS:
        scores[dim] = []
        for i in range(n):
            got = []
            for key, role in scored_keys(dim):
                v = values[key][i]
                if v is None:
                    continue
                r = ref[key]
                pct = bisect.bisect_left(r, v) / max(len(r) - 1, 1) * 100
                got.append(round(100 - pct if role == 'down' else pct, 1))
            scores[dim].append(round(sum(got) / len(got)) if got else None)
    return scores


SOURCE_LABELS = {
    'streets': 'NYC Street Centerline (LION), NYC DCP via ArcGIS', 'lpc': 'NYC LPC Individual Landmark Lots',
    'trees': 'NYC Parks Forestry Tree Points (live inventory)', 'parks': 'NYC Parks Properties',
    'sidewalks': 'NYC Planimetric Database: Sidewalk', 'noise': 'NYC 311 Service Requests (Noise*)',
    'collisions': 'NYPD Motor Vehicle Collisions – Crashes', 'subway': 'MTA Subway Entrances and Exits',
    'osm': 'OpenStreetMap via Overpass API'}
SCORE_METHOD = ('Dimension score = mean of its ranked sub-indicators, each a 0–100 percentile among Manhattan segments (ties take the lowest rank; '
                '"fewer is better" indicators reversed). N/A when no ranked sub-indicator is measurable. Overall = equal-weight mean of the available '
                'dimension scores; coverage = how many of 12 were available.')
