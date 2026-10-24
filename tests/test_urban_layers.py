"""Navigate Urban Data Layers (static catalog + tiles) and dynamic walking-time limits, on the real built data.
Run: python3 -m unittest tests.test_urban_layers
"""
import importlib.util, json, math, os, pathlib, random, sys, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing.engine import get_planner  # noqa: E402
from routing.layers import Catalog, along_route, distance_to_line  # noqa: E402

P, C = get_planner(), Catalog()
CAT = C.doc
pt = lambda lon, lat: {'lon': lon, 'lat': lat}
BRYANT, ROCK, BATTERY, MET = pt(-73.9832, 40.7536), pt(-73.9787, 40.7587), pt(-74.0168, 40.7032), pt(-73.9632, 40.7794)
STATUSES = {'CONNECTED', 'AVAILABLE_NOT_CONNECTED', 'MISSING', 'UNAVAILABLE'}
# Manhattan borough bounds (incl. Governors Island) + ~500 m: anything outside is a CRS or geocoding error.
W, S, E, N = -74.0522, 40.6747, -73.9018, 40.8870


def coords(g):
    t, c = g['type'], g['coordinates']
    return [c] if t == 'Point' else c if t in ('LineString', 'MultiPoint') else [p for part in c for p in part] if t in ('MultiLineString', 'Polygon') else [p for poly in c for r in poly for p in r]


class Catalog_(unittest.TestCase):
    def test_dataset_centred_categories(self):
        self.assertEqual([c['id'] for c in CAT['categories']], ['streets', 'nature', 'buildings', 'heritage', 'activities', 'safety', 'environment', 'transit', 'services', 'waterfront'])
        for d in CAT['datasets']:
            self.assertIn(d['status'], STATUSES, d['id'])
            self.assertTrue(set(d['categories']) <= {c['id'] for c in CAT['categories']})
            self.assertNotIn('dimension', d, 'datasets are grouped by data category, not by experience dimension')
        self.assertTrue(all(any(d['status'] == 'CONNECTED' and c['id'] in d['categories'] for d in CAT['datasets']) for c in CAT['categories']))

    def test_connected_datasets_documented_and_tiled(self):
        for d in CAT['datasets']:
            if d['status'] != 'CONNECTED':
                self.assertTrue(d['reason']); self.assertNotIn('tileset', d)
                continue
            for k in ('name', 'source', 'source_url', 'geometry', 'last_updated', 'time_range', 'attributes', 'feature_count', 'layer_type'):
                self.assertTrue(d.get(k) not in (None, ''), (d['id'], k))
            ts = CAT['tilesets'][d['tileset']]
            self.assertEqual(ts['features'], d['feature_count'])
            for key in list(ts['tiles'])[:3]:
                self.assertTrue((ROOT / 'data' / 'layers' / 'tiles' / d['tileset'] / f'{key}.json').exists())

    def test_scoring_flags_match_existing_score_definitions(self):
        streets = json.loads((ROOT / 'data' / 'manhattan-streets.json').read_text())['metadata']['indicators']
        for d in CAT['datasets']:
            if d['status'] != 'CONNECTED':
                continue
            self.assertEqual(d['used_in_scoring'], bool(d['scoring']))
            for s in d['scoring']:
                keys = {x['key'] for x in streets[s['dimension']]}
                self.assertTrue(set(s['sub_indicators']) <= keys, (d['id'], s))
        context = {d['id'] for d in CAT['datasets'] if d['status'] == 'CONNECTED' and not d['used_in_scoring']}
        self.assertTrue({'building_footprints', 'historic_districts', 'bus_stops', 'cyclist_crashes', 'pedestrian_ramps'} <= context, 'new datasets must not enter scoring')

    def test_tile_index_consistent(self):
        size = CAT['tile_size_m']
        for tid in ('street_trees', 'historic_districts', 'bike_routes', 'building_footprints'):
            for key, n in list(CAT['tilesets'][tid]['tiles'].items())[:6]:
                fs = json.loads((ROOT / 'data' / 'layers' / 'tiles' / tid / f'{key}.json').read_text())['features']
                self.assertEqual(len(fs), n)
                tx, ty = map(int, key.split('_'))
                for f in fs:
                    xs = [C.xy(c)[0] for c in coords(f['geometry'])]; ys = [C.xy(c)[1] for c in coords(f['geometry'])]
                    self.assertTrue(min(xs) <= (tx + 1) * size and max(xs) >= tx * size and min(ys) <= (ty + 1) * size and max(ys) >= ty * size, (tid, key))


class GeographicAccuracy(unittest.TestCase):
    def test_all_coordinates_in_manhattan_lon_lat(self):
        """Catches swapped lon/lat and unconverted State Plane feet (the historic districts source is EPSG:2263)."""
        for tid in CAT['tilesets']:
            for f in C.features(tid)[:4000]:
                for lon, lat in coords(f['geometry']):
                    self.assertTrue(W <= lon <= E and S <= lat <= N, (tid, lon, lat))

    def test_historic_districts_reprojected_and_real(self):
        hd = C.features('historic_districts')
        self.assertGreater(len(hd), 30)
        names = {f['properties']['area_name'] for f in hd}
        self.assertTrue(any('Greenwich Village' in n for n in names) and any('SoHo' in n or 'Cast Iron' in n for n in names), names)
        gv = next(f for f in hd if 'Greenwich Village' in f['properties']['area_name'])
        self.assertEqual(distance_to_line(C, gv['geometry'], [[-73.9993, 40.7353], [-73.9990, 40.7356]]), 0.0, 'a point on Bank St / W 11 St lies in the Greenwich Village HD')

    def test_projection_against_wgs84_geodesic(self):
        from pyproj import Geod
        g, rnd, worst = Geod(ellps='WGS84'), random.Random(5), 0.0
        for _ in range(2000):
            a, b = (-74.02 + rnd.random() * .11, 40.70 + rnd.random() * .18), (-74.02 + rnd.random() * .11, 40.70 + rnd.random() * .18)
            d = g.inv(*a, *b)[2]
            if d > 50:
                pa, pb = C.xy(a), C.xy(b)
                worst = max(worst, abs(math.hypot(pa[0] - pb[0], pa[1] - pb[1]) - d) / d)
        self.assertLess(worst, 0.002)

    def test_trees_lie_along_streets(self):
        trees = C.features('street_trees')
        lion = C.features('lion_centerline')
        grid = {}
        for f in lion:
            for p in f['geometry']['coordinates']:
                x, y = C.xy(p); grid.setdefault((int(x // 100), int(y // 100)), []).append(f)
        rnd, near, sample = random.Random(2), 0, 400
        for f in rnd.sample(trees, sample):
            x, y = C.xy(f['geometry']['coordinates'])
            cands = {id(g): g for i in (-1, 0, 1) for j in (-1, 0, 1) for g in grid.get((int(x // 100) + i, int(y // 100) + j), [])}.values()
            if any(distance_to_line(C, f['geometry'], g['geometry']['coordinates']) <= 40 for g in cands):
                near += 1
        self.assertGreater(near / sample, .8, 'street & park trees should mostly sit within 40 m of a centreline (park interiors are the rest)')

    def test_subway_entrances_near_stations(self):
        stations = C.features('subway_stations')
        far = [e for e in C.features('subway_entrances') if min(math.dist(C.xy(e['geometry']['coordinates']), C.xy(s['geometry']['coordinates'])) for s in stations) > 400]
        self.assertLess(len(far) / len(C.features('subway_entrances')), .02)

    def test_buildings_and_crashes_valid(self):
        b = C.features('building_footprints')
        self.assertGreater(len(b), 40000)
        self.assertTrue(all(f['geometry']['type'] in ('Polygon', 'MultiPolygon') for f in b[:2000]))
        crashes = C.features('pedestrian_crashes')
        self.assertTrue(all(f['properties'].get('crash_date') for f in crashes))
        self.assertEqual(len({f['properties']['feature_id'] for f in crashes}), len(crashes), 'no duplicate collision IDs')


class RouteQueries(unittest.TestCase):
    def test_along_route_uses_route_geometry(self):
        r = P.plan(BRYANT, MET, {'weights': {'Nature': 90}}, {'max_minutes': 120})['routes']
        a = along_route(C, 'street_trees', r[0]['geometry']['coordinates'], 100)
        b = along_route(C, 'street_trees', r[1]['geometry']['coordinates'], 100)
        self.assertTrue(a and b); self.assertNotEqual(set(a), set(b))
        self.assertTrue(all(v <= 100 for v in a.values()))
        wider = along_route(C, 'street_trees', r[0]['geometry']['coordinates'], 200)
        self.assertTrue(set(a) <= set(wider))

    def test_large_polygons_by_intersection_not_centroid(self):
        # Central Park: a route along its interior drive is inside the park polygon although far from its centroid.
        hits = along_route(C, 'parks', [[-73.9686, 40.7700], [-73.9690, 40.7712]], 50)
        names = {f['properties']['signname'] for f in C.dataset_features('parks') if f['properties']['feature_id'] in hits}
        self.assertIn('Central Park', names)
        self.assertEqual(hits[next(f['properties']['feature_id'] for f in C.dataset_features('parks') if f['properties']['signname'] == 'Central Park')], 0.0)

    def test_display_corridor_never_changes_scores(self):
        r = P.plan(BRYANT, ROCK, {'weights': {'Nature': 90}}, {})['routes'][0]
        before = json.dumps(P.net.gscores[:3000]) + json.dumps(r['dimension_scores'])
        for dist in (50, 500):
            along_route(C, 'noise_complaints', r['geometry']['coordinates'], dist)
        self.assertEqual(before, json.dumps(P.net.gscores[:3000]) + json.dumps(r['dimension_scores']))


class RouteSegments(unittest.TestCase):
    def test_matched_and_unmatched_edges(self):
        edges = P.plan(BRYANT, ROCK, {'weights': {'Nature': 90}}, {})['routes'][0]['edges']
        m = next(e for e in edges if e['matched_segment_ids'])
        self.assertEqual(m['lion_match'], 'matched'); self.assertTrue(m['matched_segments'][0]['street_name'])
        u = next(e for e in edges if not e['matched_segment_ids'])
        self.assertEqual(u['lion_match'], 'unmatched'); self.assertEqual(u['matched_segments'], [])


class WalkingTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('streetwise_server', ROOT / 'server.py')
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)

    def req(self, **c):
        return {'origin': BRYANT, 'destination': ROCK, 'constraints': c}

    def test_validation_accepts_long_limits_and_rejects_bad_values(self):
        for v in (10, 45, 60, 72, 120, 600):
            self.assertEqual(self.m.validate_route_request(self.req(max_minutes=v))[3]['max_minutes'], v)
        for bad in (5, 9.9, -3, 'abc', float('nan'), float('inf')):
            with self.assertRaises((ValueError, TypeError)):
                self.m.validate_route_request(self.req(max_minutes=bad))
        self.assertEqual(self.m.validate_interpretation({'time_minutes': 300})['time_minutes'], 300)
        with self.assertRaises(ValueError):
            self.m.validate_interpretation({'time_minutes': 5})

    def test_engine_uses_the_users_limit(self):
        # Battery → Met is about 122 minutes on foot.
        tight = P.plan(BATTERY, MET, {}, {'max_minutes': 72, 'max_detour_pct': 25})
        self.assertEqual((tight['constraints_used']['max_minutes'], tight['feasible_count']), (72, 0))
        self.assertEqual(P.plan(BATTERY, MET, {}, {'max_minutes': 120, 'max_detour_pct': 25})['feasible_count'], 0)
        loose = P.plan(BATTERY, MET, {}, {'max_minutes': 150, 'max_detour_pct': 25})
        rec = next(r for r in loose['routes'] if r['recommended'])
        self.assertLessEqual(rec['estimated_duration_min'], 150)
        for r in loose['routes']:
            self.assertEqual(r['constraints']['feasible'], r['estimated_duration_min'] <= 150 and r['detour_percentage'] <= 25)

    def test_detour_rule_unchanged(self):
        for r in P.plan(BRYANT, MET, {'weights': {'Nature': 100}}, {'max_minutes': 120, 'max_detour_pct': 0})['routes']:
            self.assertEqual(r['constraints']['feasible'], r['detour_percentage'] <= 0)


class StaticServing(unittest.TestCase):
    """Layers are static files (GitHub Pages or server.py) and must come back as JSON, never an HTML page."""
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('streetwise_server', ROOT / 'server.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), m.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_catalog_and_tile_are_json(self):
        key = next(iter(CAT['tilesets']['street_trees']['tiles']))
        for path in ('/data/layers/catalog.json', f'/data/layers/tiles/street_trees/{key}.json'):
            with urllib.request.urlopen(self.base + path, timeout=30) as r:
                self.assertEqual(r.status, 200); self.assertIn('json', r.headers['Content-Type'])
                self.assertIn(r.read()[:1], (b'{', b'['))

    def test_old_layer_api_removed(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + '/api/layers', timeout=10)
        self.assertEqual(e.exception.code, 404)

    def test_no_absolute_static_paths_in_frontend(self):
        """GitHub Pages serves the site under /streetwise/, so static files must be fetched with relative paths."""
        for f in ('urban-layers.js', 'explore-map.js', 'route-client.js', 'app.js'):
            src = (ROOT / f).read_text()
            self.assertNotIn("'/data/", src, f); self.assertNotIn('"/data/', src, f)
            self.assertNotRegex(src, r"(?<!streetwise)fetch\('/api/", f'{f}: /api/ calls must go through streetwiseFetch/streetwiseJson')


if __name__ == '__main__':
    unittest.main()
