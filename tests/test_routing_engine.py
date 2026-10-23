"""End-to-end checks of the pedestrian routing layer on the real built data (no mocks, no synthetic graph).

Covers: A pedestrian network, B LION–OSM matching, C experience scores, E AI Journey ranking and constraints,
F route figures, G navigation readiness, plus the HTTP API. Needs the files produced by
scripts/build_pedestrian_network.py and scripts/match_lion_osm.py.
Run: python3 -m unittest tests.test_routing_engine
"""
import csv, gzip, importlib.util, json, math, pathlib, random, sys, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from routing.engine import DIMENSIONS, RoutingError, get_planner, xy  # noqa: E402
from match_lion_osm import name_tokens, names_compatible, any_compatible, layered  # noqa: E402

P = get_planner()
NET = P.net
STREETS = json.loads((ROOT / 'data' / 'manhattan-streets.json').read_text())
SEG = {f['properties']['id']: f['properties'] for f in STREETS['features']}
MAPPING = list(csv.DictReader(gzip.open(ROOT / 'data' / 'pedestrian' / 'street_osm_edge_mapping.csv.gz', 'rt')))
PLACES = {'bryant': (-73.9832, 40.7536), 'rock': (-73.9787, 40.7587), 'met': (-73.9632, 40.7794), 'columbia': (-73.9636, 40.8075),
          'washington': (-73.9973, 40.7308), 'battery': (-74.0168, 40.7032), 'union': (-73.9903, 40.7359), 'columbus': (-73.9819, 40.7681)}
pt = lambda k: {'lon': PLACES[k][0], 'lat': PLACES[k][1]}


def plan(a, b, weights=None, **constraints):
    return P.plan(pt(a), pt(b), {'weights': weights or {}, 'directions': {}}, constraints)


class A_PedestrianNetwork(unittest.TestCase):
    def test_network_loaded_and_versioned(self):
        s = NET.status()
        self.assertGreater(s['nodes'], 30000); self.assertGreater(s['edges'], 100000)
        self.assertGreater(s['main_component_nodes'] / s['nodes'], .85)
        self.assertTrue(s['network_version'].startswith('osm-walk-'))

    def test_pedestrian_restrictions_applied(self):
        for u, v, k, gi, rev, length, osmids, t in NET.edges:
            foot, access, hw = set(map(str, [t.get('foot')] if not isinstance(t.get('foot'), list) else t['foot'])), t.get('access'), t.get('highway')
            self.assertFalse(foot & {'no', 'private', 'use_sidepath'}, (u, v, k))
            hws = set(hw if isinstance(hw, list) else [hw])
            self.assertFalse(hws & {'motorway', 'motorway_link'})
            if hws & {'trunk', 'trunk_link'}:
                self.assertTrue(foot & {'yes', 'designated', 'permissive'})

    def test_topology_geometry_matches_nodes(self):
        for i in random.Random(1).sample(range(len(NET.edges)), 3000):
            u, v = NET.edges[i][:2]
            c = NET.coords(i)
            self.assertLess(math.dist(c[0], NET.nodes[u][:2]), 1e-6); self.assertLess(math.dist(c[-1], NET.nodes[v][:2]), 1e-6)
            j = NET.twin(i)
            if j is not None:
                self.assertEqual(NET.coords(j), c[::-1])

    def test_edge_identity_is_full_u_v_key(self):
        ids = [NET.edge_id(i) for i in range(len(NET.edges))]
        self.assertEqual(len(ids), len(set(ids)))
        multi_way = sum(1 for e in NET.edges if len(e[6]) > 1)
        self.assertGreater(multi_way, 0, 'simplified edges can span several OSM ways, so way IDs alone cannot identify edges')

    def test_snapping_reaches_street_segments(self):
        # Every sampled LION street snaps to the routable network, except streets on islands whose own walk network
        # connects to Manhattan only through other boroughs (their nearest graph node is outside the main component).
        rnd = random.Random(7); feats = rnd.sample(STREETS['features'], 300)
        nodes = [(xy(*v[:2]), v[3]) for v in NET.nodes.values()]
        for f in feats:
            c = f['geometry']['coordinates'][len(f['geometry']['coordinates']) // 2]
            try:
                self.assertLessEqual(NET.snap(c[0], c[1], 'p')['snap_distance_m'], 150)
            except RoutingError:
                p = xy(*c)
                comp = min(nodes, key=lambda n: math.dist(n[0], p))[1]
                self.assertNotEqual(comp, 0, f"{f['properties']['name']} failed to snap although it sits on the main network")

    def test_snap_projects_onto_edge_not_node(self):
        s = NET.snap(*PLACES['bryant'], 'Origin')
        self.assertTrue(0 <= s['offset_m'] <= NET.edges[s['edge']][5])

    def test_water_point_is_rejected(self):
        with self.assertRaises(RoutingError):
            NET.snap(-74.03, 40.70, 'Destination')


class B_LionOsmMatching(unittest.TestCase):
    def test_ids_traceable_both_ways(self):
        for r in MAPPING[::25]:
            self.assertIn(r['osm_edge_id'], NET.by_id)
            seg = SEG[r['analysis_segment_id']]
            self.assertEqual(str(seg['source_segment_id']), r['lion_segment_id'])
            u, v, k = map(int, r['osm_edge_id'].split('-'))
            self.assertEqual((int(r['graph_u']), int(r['graph_v']), int(r['graph_key'])), (u, v, k))

    def test_bridges_tunnels_never_match_ground_segments(self):
        for r in MAPPING:
            tags = NET.edges[NET.by_id[r['osm_edge_id']]][7]
            self.assertFalse(layered(tags), r['osm_edge_id'])

    def test_no_differently_named_street_borrowed(self):
        bad = 0
        for r in MAPPING[::5]:
            tags = NET.edges[NET.by_id[r['osm_edge_id']]][7]
            names = tags.get('name') if isinstance(tags.get('name'), list) else [tags.get('name')]
            if any_compatible([name_tokens(n) for n in names if n], name_tokens(SEG[r['analysis_segment_id']]['name'])) is False:
                bad += 1
        self.assertEqual(bad, 0)

    def test_parallel_streets_not_confused(self):
        self.assertFalse(names_compatible(name_tokens('West 42nd Street'), name_tokens('W 43 ST')))
        self.assertFalse(names_compatible(name_tokens('Broadway'), name_tokens('W BROADWAY')))
        self.assertFalse(names_compatible(name_tokens('East 42nd Street'), name_tokens('W 42 ST')))
        self.assertTrue(names_compatible(name_tokens('Malcolm X Boulevard'), name_tokens('LENOX AV')))
        # Geometric guard: every match lies within the type's distance band and runs the same way.
        for r in MAPPING[::10]:
            self.assertLessEqual(float(r['match_distance']), 28.0); self.assertLessEqual(float(r['angle_difference']), 20.0)

    def test_unmatched_edges_handled(self):
        srcs = {g['src'] for g in NET.gscores}
        self.assertEqual(srcs, {'lion_match', 'direct_osm', 'none'})
        for g in NET.gscores:
            if g['src'] == 'direct_osm':
                self.assertIsNotNone(g.get('raw'))
            if g['src'] == 'none':
                self.assertTrue(all(v is None for v in g['s']))


class C_ExperienceScores(unittest.TestCase):
    def test_versions_consistent(self):
        self.assertEqual(NET.score_version, STREETS['metadata']['score_version'])
        self.assertEqual({r['score_version'] for r in MAPPING}, {NET.score_version})
        self.assertEqual({r['network_version'] for r in MAPPING}, {NET.network_version})

    def test_edge_score_is_overlap_weighted_mean_of_segments(self):
        rows = {}
        for r in MAPPING:
            if r['used_for_scores'] == 'True':
                rows.setdefault(r['osm_edge_id'], []).append(r)
        for eid, rs in list(rows.items())[::40]:
            g = NET.gscores[NET.edges[NET.by_id[eid]][3]]
            for j in range(12):
                pairs = [(float(r['overlap_length']), SEG[r['analysis_segment_id']][f'd{j}']) for r in rs if SEG[r['analysis_segment_id']][f'd{j}'] is not None]
                w = sum(o for o, _ in pairs)
                expect = sum(o * v for o, v in pairs) / w if w else None
                if expect is None:
                    self.assertIsNone(g['s'][j])
                else:  # the CSV rounds overlap to 0.1 m, so allow the last digit to differ
                    self.assertLessEqual(abs(g['s'][j] - expect), 1, (eid, j))

    def test_missing_never_becomes_zero(self):
        # Comfort is N/A on park paths: edges matched only to such segments must stay N/A, not 0.
        rows = {}
        for r in MAPPING:
            if r['used_for_scores'] == 'True':
                rows.setdefault(r['osm_edge_id'], []).append(SEG[r['analysis_segment_id']]['d4'])
        only_na = [eid for eid, vals in rows.items() if all(v is None for v in vals)]
        self.assertTrue(only_na)
        for eid in only_na[:200]:
            self.assertIsNone(NET.gscores[NET.edges[NET.by_id[eid]][3]]['s'][4])

    def test_route_scores_length_weighted_with_coverage(self):
        r = plan('met', 'columbia', {'Nature': 90})['routes'][0]
        for j, d in enumerate(DIMENSIONS):
            num = den = 0.0
            for e in r['edges']:
                v, c = e['dimension_scores'][d], e['data_coverage'][d]
                if v is not None:
                    num += e['traversed_length_m'] * c * v; den += e['traversed_length_m'] * c
            self.assertEqual(r['dimension_scores'][d], round(num / den) if den else None)
            self.assertAlmostEqual(r['data_coverage']['by_dimension'][d], round(den / r['distance_m'], 3), places=3)

    def test_planning_does_not_change_objective_scores(self):
        before = json.dumps(NET.gscores[:2000])
        plan('bryant', 'rock', {'Nature': 100, 'Food & Retail': 100})
        plan('bryant', 'rock', {'Quiet & Relax': 100}, avoid_stairs=True)
        self.assertEqual(before, json.dumps(NET.gscores[:2000]))


class E_AIJourney(unittest.TestCase):
    def test_routes_are_continuous_real_edges(self):
        res = plan('washington', 'battery', {'Nature': 80})
        for r in res['routes']:
            self.assertEqual([e['edge_id'] for e in r['edges']], r['ordered_edge_ids'])
            for a, b in zip(r['edges'], r['edges'][1:]):
                self.assertEqual(a['v'], b['u'], 'consecutive edges must share a graph node')
                self.assertLess(math.dist(a['geometry']['coordinates'][-1], b['geometry']['coordinates'][0]), 1e-6)
            self.assertTrue(all(eid in NET.by_id for eid in r['ordered_edge_ids']))
            self.assertLess(math.dist(r['geometry']['coordinates'][0], r['edges'][0]['geometry']['coordinates'][0]), 1e-6)

    def test_candidates_are_distinct_paths(self):
        from routing.engine import overlap
        for a, b in (('met', 'columbia'), ('washington', 'battery'), ('union', 'columbus')):
            rs = plan(a, b, {'Nature': 90})['routes']
            for x in rs:
                for y in rs:
                    if x is not y:
                        self.assertLessEqual(overlap(x, y), .85)

    def test_preferences_change_ranking(self):
        changed = 0
        for a, b in (('met', 'columbia'), ('washington', 'battery'), ('union', 'columbus'), ('bryant', 'columbus')):
            n = plan(a, b, {'Nature': 100}, max_detour_pct=40)['routes'][0]['ordered_edge_ids']
            f = plan(a, b, {'Food & Retail': 100, 'Urban Vibrancy': 100}, max_detour_pct=40)['routes'][0]['ordered_edge_ids']
            changed += n != f
        self.assertGreater(changed, 0, 'different preferences must be able to change the recommended route')

    def test_detour_and_time_constraints(self):
        res = plan('met', 'columbia', {'Nature': 100}, max_detour_pct=0)
        for r in res['routes']:
            self.assertEqual(r['constraints']['feasible'], r['detour_percentage'] <= 0)
        self.assertEqual(res['routes'][0]['objective'] if res['routes'][0]['recommended'] else 'shortest', 'shortest')
        res = plan('met', 'columbia', max_minutes=10)
        self.assertFalse(any(r['recommended'] for r in res['routes']))
        self.assertTrue(all('10-minute limit' in ' '.join(r['constraints']['violations']) for r in res['routes']))

    def test_avoid_stairs_excludes_steps(self):
        for r in plan('columbia', 'met', avoid_stairs=True)['routes']:
            self.assertFalse(any(e['pedestrian_access']['steps'] for e in r['edges']))

    def test_unreachable_and_invalid(self):
        with self.assertRaises(RoutingError):
            P.plan(pt('bryant'), {'lon': -74.03, 'lat': 40.70}, {}, {})

    def test_low_coverage_cannot_inflate_score(self):
        r = plan('met', 'columbia', {'Spatial Comfort': 100})['routes'][0]
        c = r['personalized_score']['components']['Spatial Comfort']
        fit = c['route_score']
        self.assertAlmostEqual(c['adjusted_fit'], round(50 + c['coverage'] * (fit - 50), 1), places=1)


class F_RouteFigures(unittest.TestCase):
    def test_distance_time_detour(self):
        res = plan('union', 'columbus', {'Nature': 90})
        shortest = min(r['distance_m'] for r in res['routes'])
        for r in res['routes']:
            self.assertAlmostEqual(r['distance_m'], sum(e['traversed_length_m'] for e in r['edges']), delta=1.0)
            self.assertAlmostEqual(r['estimated_duration_min'], r['distance_m'] / 80, delta=.1)
            self.assertAlmostEqual(r['detour_percentage'], round((r['distance_m'] / shortest - 1) * 100, 1), delta=.1)
            geo = sum(math.dist(xy(*a), xy(*b)) for a, b in zip(r['geometry']['coordinates'], r['geometry']['coordinates'][1:]))
            self.assertLess(abs(geo - r['distance_m']) / r['distance_m'], .02, 'route length must match its drawn geometry')


class G_NavigationReadiness(unittest.TestCase):
    def test_progress_on_and_off_route(self):
        r = plan('bryant', 'rock')['routes'][0]
        c = r['geometry']['coordinates']; mid = c[len(c) // 2]
        p = P.progress(r['route_id'], mid[0], mid[1], 10)
        self.assertEqual(p['state'], 'on_route'); self.assertFalse(p['off_route'])
        self.assertIn(p['current_edge_id'], r['ordered_edge_ids'])
        self.assertAlmostEqual(p['progress_m'] + p['remaining_m'], r['distance_m'], delta=1)
        off = P.progress(r['route_id'], mid[0] + .0015, mid[1], 10)
        self.assertTrue(off['off_route']); self.assertTrue(off['reroute_recommended'])
        coarse = P.progress(r['route_id'], mid[0] + .0015, mid[1], 200)
        self.assertFalse(coarse['off_route'], 'a fix worse than 60 m must not trigger a re-route')
        end = P.progress(r['route_id'], *c[-1], 5)
        self.assertEqual(end['state'], 'arrived')
        with self.assertRaises(RoutingError):
            P.progress('rt-unknown', *mid)

    def test_route_object_has_navigation_fields(self):
        r = plan('bryant', 'rock')['routes'][0]
        for k in ('route_id', 'route_name', 'origin', 'destination', 'geometry', 'ordered_edge_ids', 'distance_m', 'estimated_duration_min',
                  'detour_percentage', 'dimension_scores', 'personalized_score', 'data_coverage', 'ranking_explanation', 'network_version', 'score_version', 'navigation'):
            self.assertIn(k, r)
        self.assertEqual(r['navigation']['state'], 'planned')


class HttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('streetwise_server', ROOT / 'server.py')
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.m.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_existing_endpoint_unchanged(self):
        status, doc = self.call('/api/status')
        self.assertEqual(status, 200); self.assertLessEqual({'llm', 'model'}, set(doc))  # original contract kept; 'features' is additive

    def test_routes_edges_segments_progress(self):
        status, doc = self.call('/api/routes', {'origin': pt('bryant'), 'destination': pt('rock'), 'preferences': {'weights': {'Nature': 90}},
                                                'constraints': {'max_minutes': 30, 'max_detour_pct': 25}})
        self.assertEqual(status, 200)
        r = doc['routes'][0]
        e = next(x for x in r['edges'] if x['matched_segment_ids'])
        status, edge = self.call('/api/edges/' + e['edge_id'])
        self.assertEqual((status, edge['edge_id'], edge['matched_segment_ids']), (200, e['edge_id'], e['matched_segment_ids']))
        status, seg = self.call('/api/segments/' + e['matched_segment_ids'][0])
        self.assertEqual(status, 200); self.assertEqual(seg['segment_id'], e['matched_segment_ids'][0])
        self.assertEqual(set(seg['dimension_scores']), set(DIMENSIONS)); self.assertEqual(seg['score_version'], r['score_version'])
        c = r['geometry']['coordinates'][3]
        status, prog = self.call('/api/navigation/progress', {'route_id': r['route_id'], 'lon': c[0], 'lat': c[1], 'accuracy_m': 8})
        self.assertEqual((status, prog['state']), (200, 'on_route'))

    def test_errors_are_explicit(self):
        self.assertEqual(self.call('/api/routes', {'origin': pt('bryant'), 'destination': {'lon': -74.03, 'lat': 40.70}})[0], 422)
        self.assertEqual(self.call('/api/routes', {'origin': pt('bryant'), 'destination': pt('rock'), 'preferences': {'weights': {'Greenery': 50}}})[0], 400)
        self.assertEqual(self.call('/api/routes', {'origin': {'lat': 48.8, 'lon': 2.3}, 'destination': pt('rock')})[0], 400)
        self.assertEqual(self.call('/api/edges/1-2-3')[0], 404)
        self.assertEqual(self.call('/api/navigation/progress', {'route_id': 'nope', 'lon': -73.98, 'lat': 40.75})[0], 422)


if __name__ == '__main__':
    unittest.main()
