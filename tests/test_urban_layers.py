"""Navigate Urban Data Layers and dynamic walking-time limits, on the real built data.
Run: python3 -m unittest tests.test_urban_layers
"""
import gzip, importlib.util, json, math, pathlib, sys, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing.engine import get_planner, xy, RoutingError  # noqa: E402
from routing.layers import get_store, LayerError, _pt_seg  # noqa: E402

P, S = get_planner(), get_store()
REG = S.registry
pt = lambda lon, lat: {'lon': lon, 'lat': lat}
BRYANT, ROCK, BATTERY, MET = pt(-73.9832, 40.7536), pt(-73.9787, 40.7587), pt(-74.0168, 40.7032), pt(-73.9632, 40.7794)


def route(a=BRYANT, b=ROCK, **c):
    return P.plan(a, b, {'weights': {'Nature': 90}}, {'max_minutes': 120, 'max_detour_pct': 25, **c})


class Registry(unittest.TestCase):
    def test_every_dimension_has_layers_and_metadata(self):
        dims = {d['dimension'] for l in REG['layers'].values() for d in l['dims']}
        self.assertEqual(dims, set(REG['dimension_order']))
        for lid, l in REG['layers'].items():
            if l['status'] == 'available':
                for k in ('name', 'dataset', 'source', 'url', 'geometry', 'processing', 'display_distance_m', 'updated', 'retrieved', 'attributes', 'feature_count'):
                    self.assertIn(k, l, lid)
                self.assertTrue((ROOT / 'data' / 'layers' / f'{lid}.geojson.gz').exists())
            else:
                self.assertTrue(l['reason'])
                self.assertFalse((ROOT / 'data' / 'layers' / f'{lid}.geojson.gz').exists(), 'unavailable layers must have no data')

    def test_scoring_links_point_at_real_sub_indicators(self):
        for lid, l in REG['layers'].items():
            for d in l['dims']:
                if d['role'] == 'scoring':
                    keys = {x['key'] for x in REG['indicators'][d['dimension']]}
                    self.assertTrue(d['sub_indicators'] and set(d['sub_indicators']) <= keys, (lid, d))
                else:
                    self.assertEqual(d['sub_indicators'], [], f'{lid} is context only and must not claim a sub-indicator')

    def test_feature_counts_and_real_attributes(self):
        for lid in ('street_trees', 'pedestrian_crashes', 'landmarks', 'subway_entrances'):
            L = S.layer(lid)
            self.assertEqual(len(L.features), REG['layers'][lid]['feature_count'])
            f = L.features[0]['properties']
            self.assertTrue(f['feature_id'])
            present = [a for a in REG['layers'][lid]['attributes'] if f.get(a) not in (None, '')]
            self.assertTrue(present, lid)
            self.assertTrue(set(f) - {'feature_id'} <= set(REG['layers'][lid]['attributes']) | {'source_id'}, 'no invented attributes')

    def test_unavailable_layer_refused(self):
        with self.assertRaises(LayerError):
            S.layer('air_quality')


class Queries(unittest.TestCase):
    def test_along_route_exact_for_points(self):
        r = route()['routes'][0]
        coords = r['geometry']['coordinates']; line = [xy(*c) for c in coords]
        res = S.along_route('street_trees', coords, 30)
        got = {f['properties']['feature_id'] for f in res['features']}
        want = set()
        for f in S.layer('street_trees').features:  # brute force over the whole layer
            p = xy(*f['geometry']['coordinates'])
            if min(_pt_seg(p, a, b) for a, b in zip(line, line[1:])) <= 30:
                want.add(f['properties']['feature_id'])
        self.assertEqual(got, want)
        self.assertTrue(all(f['properties']['distance_to_route_m'] <= 30 for f in res['features']))

    def test_along_route_lines_and_polygons_within_distance(self):
        r = route()['routes'][0]
        for lid, d in (('osm_crosswalks', 30), ('landmarks', 150), ('parks', 40)):
            res = S.along_route(lid, r['geometry']['coordinates'], d)
            self.assertGreater(res['count'], 0, lid)
            self.assertTrue(all(f['properties']['distance_to_route_m'] <= d for f in res['features']))

    def test_route_switch_changes_data(self):
        rs = route(BRYANT, MET)['routes']
        a = {f['properties']['feature_id'] for f in S.along_route('street_trees', rs[0]['geometry']['coordinates'])['features']}
        b = {f['properties']['feature_id'] for f in S.along_route('street_trees', rs[1]['geometry']['coordinates'])['features']}
        self.assertNotEqual(a, b)

    def test_current_view(self):
        bbox = [-73.99, 40.75, -73.98, 40.76]
        res = S.in_view('subway_entrances', bbox)
        for f in res['features']:
            lon, lat = f['geometry']['coordinates']
            self.assertTrue(bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3])
        big = S.in_view('noise_complaints', [-74.02, 40.70, -73.93, 40.80])
        self.assertTrue(big['too_many']); self.assertEqual(big['features'], [])

    def test_display_distance_never_changes_scores(self):
        res = route(); r = res['routes'][0]
        before = json.dumps(P.net.gscores[:3000]) + json.dumps(r['dimension_scores'])
        for d in (30, 300, 1500):
            S.along_route('noise_complaints', r['geometry']['coordinates'], d)
        self.assertEqual(before, json.dumps(P.net.gscores[:3000]) + json.dumps(r['dimension_scores']))


class RouteSegments(unittest.TestCase):
    def test_matched_and_unmatched_edges(self):
        edges = route()['routes'][0]['edges']
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
        for bad in (5, 9.9, -3, 'abc', None.__class__, float('nan'), float('inf')):
            with self.assertRaises((ValueError, TypeError)):
                self.m.validate_route_request(self.req(max_minutes=bad))
        self.assertEqual(self.m.validate_interpretation({'time_minutes': 300})['time_minutes'], 300)
        with self.assertRaises(ValueError):
            self.m.validate_interpretation({'time_minutes': 5})

    def test_engine_uses_the_users_limit(self):
        # Battery → Met is about 122 minutes on foot.
        tight = P.plan(BATTERY, MET, {}, {'max_minutes': 72, 'max_detour_pct': 25})
        self.assertEqual(tight['constraints_used']['max_minutes'], 72)
        self.assertEqual(tight['feasible_count'], 0)
        self.assertFalse(any(r['recommended'] for r in tight['routes']))
        self.assertTrue(all(any('72-minute limit' in v for v in r['constraints']['violations']) for r in tight['routes']))
        exact = P.plan(BATTERY, MET, {}, {'max_minutes': 120, 'max_detour_pct': 25})
        self.assertEqual(exact['feasible_count'], 0, 'a 122-minute walk must not pass a 120-minute limit')
        loose = P.plan(BATTERY, MET, {}, {'max_minutes': 150, 'max_detour_pct': 25})
        rec = next(r for r in loose['routes'] if r['recommended'])
        self.assertLessEqual(rec['estimated_duration_min'], 150)
        for r in loose['routes']:
            self.assertEqual(r['constraints']['feasible'], r['estimated_duration_min'] <= 150 and r['detour_percentage'] <= 25)

    def test_detour_rule_unchanged(self):
        res = P.plan(BRYANT, MET, {'weights': {'Nature': 100}}, {'max_minutes': 120, 'max_detour_pct': 0})
        for r in res['routes']:
            self.assertEqual(r['constraints']['feasible'], r['detour_percentage'] <= 0)


class HttpLayers(unittest.TestCase):
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

    def get(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body else None, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_layer_endpoints(self):
        status, reg = self.get('/api/layers'); self.assertEqual(status, 200); self.assertIn('street_trees', reg['layers'])
        status, doc = self.get('/api/routes', {'origin': BRYANT, 'destination': ROCK, 'constraints': {'max_minutes': 72}})
        self.assertEqual((status, doc['constraints_used']['max_minutes']), (200, 72))
        rid = doc['routes'][0]['route_id']
        status, a = self.get(f'/api/layers/street_trees?route_id={rid}&distance=30')
        self.assertEqual((status, a['scope']), (200, 'along_route')); self.assertTrue(a['features'])
        self.assertEqual(self.get('/api/layers/street_trees?bbox=-73.99,40.75,-73.98,40.76')[0], 200)
        self.assertEqual(self.get('/api/layers/air_quality?bbox=-73.99,40.75,-73.98,40.76')[0], 404)
        self.assertEqual(self.get('/api/layers/nope?bbox=-73.99,40.75,-73.98,40.76')[0], 404)
        self.assertEqual(self.get('/api/layers/street_trees?bbox=1,2')[0], 400)
        self.assertEqual(self.get('/api/layers/street_trees?route_id=rt-missing')[0], 422)
        self.assertEqual(self.get('/api/routes', {'origin': BRYANT, 'destination': ROCK, 'constraints': {'max_minutes': 5}})[0], 400)


if __name__ == '__main__':
    unittest.main()
