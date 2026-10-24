"""Multi-stop itineraries (routing/itinerary.py) on the real pedestrian network and the real discovery POI index
(data/places), menu verification statuses (routing/menu.py, HTTP stubbed: no network) and the LLM journey contract.
Run: python3 -m unittest tests.test_itinerary
"""
import json, math, pathlib, sys, unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing.engine import get_planner, RoutingError, WALK_SPEED_M_PER_MIN  # noqa: E402
from routing.itinerary import Planner, validate_request, detours  # noqa: E402
from routing import menu  # noqa: E402
import server  # noqa: E402

P = get_planner()
NET = P.net
IT = Planner(P)
PLACES = {k: json.loads((ROOT / 'data' / 'places' / f'{k}.json').read_text())['records'] for k in ('hotels', 'cafes', 'museums', 'attractions', 'historic_lpc')}
HOTEL = next(h for h in PLACES['hotels'] if h['name'] == 'Hilton New York Midtown')
ROCK = {'id': 'rock', 'name': 'Rockefeller Center', 'lat': 40.7587, 'lon': -73.9787}
near = lambda r, p: math.hypot((r['lat'] - p['lat']) * 111, (r['lon'] - p['lon']) * 84)


def cands(cat, around, n, **extra):
    return [{**r, 'score': .5, **extra} for r in sorted(PLACES[cat], key=lambda r: near(r, around))[:n]]


def plan(**req):
    return IT.plan(validate_request({'origin': HOTEL, 'end': {'mode': 'round'}, **req}))


def continuous(route):
    """Each traversed edge starts where the previous one ends (within 1 m), across every stitched leg."""
    g = [e['geometry']['coordinates'] for e in route['edges']]
    return all(math.hypot((a[-1][0] - b[0][0]) * 84414, (a[-1][1] - b[0][1]) * 111050) < 1.0 for a, b in zip(g, g[1:]))


class A_Itinerary(unittest.TestCase):
    def test_round_trip_is_real_and_closed(self):
        r = plan(stops=[{**ROCK, 'visit_min': 20}], slots=[{'slot_id': 'coffee', 'label': 'Café', 'candidates': cands('cafes', ROCK, 4)}],
                 constraints={'max_minutes': 100})
        it, route = r['itinerary'], r['routes'][0]
        self.assertEqual(it['stops'][-1]['role'], 'end'); self.assertEqual(it['stops'][-1]['id'], HOTEL['id'])
        self.assertTrue(continuous(route), 'stitched legs form one continuous path')
        self.assertAlmostEqual(sum(s['leg_in_m'] for s in it['stops']), route['distance_m'], delta=2)
        self.assertAlmostEqual(it['totals']['walk_min'], route['distance_m'] / WALK_SPEED_M_PER_MIN, delta=.2)
        self.assertEqual(it['totals']['outing_min'], round(it['totals']['walk_min'] + it['totals']['visit_min'], 1))
        self.assertEqual(len(route['dimension_scores']), 12)
        self.assertTrue(any(s['id'] == 'rock' for s in it['stops']))
        self.assertEqual(sum(1 for s in it['stops'] if s.get('slot_id') == 'coffee'), 1)

    def test_matrix_is_network_distance(self):
        pts = [HOTEL, ROCK] + cands('cafes', ROCK, 3)
        sn = [NET.snap(p['lon'], p['lat'], p['name']) for p in pts]
        row = NET.distances(sn[0], sn[1:])
        for k, s in enumerate(sn[1:]):
            steps = NET.search(sn[0], s, lambda i: 1.0)
            self.assertAlmostEqual(row[k], sum(b - a for _, a, b in steps), delta=.01)
            self.assertGreaterEqual(row[k] + 1e-6, near(HOTEL, pts[k + 1]) * 1000 * .98)  # never shorter than straight line

    def test_required_stop_never_dropped(self):
        far = [{**r, 'required': True, 'visit_min': 60} for r in cands('museums', ROCK, 3)]
        r = plan(stops=far, constraints={'max_outing_minutes': 60})
        it = r['itinerary']
        self.assertFalse(it['constraints']['feasible']); self.assertTrue(it['constraints']['violations'])
        self.assertEqual({s['id'] for s in it['stops'] if s['role'] == 'stop'}, {x['id'] for x in far})
        self.assertFalse(r['routes'][0]['recommended'])

    def test_explicit_order_kept(self):
        a, b = cands('attractions', ROCK, 6)[3], cands('museums', HOTEL, 6)[5]
        r = plan(stops=[{**a, 'order': 1}, {**b, 'order': 2}, {**ROCK, 'order': 3}])
        seq = [s['id'] for s in r['itinerary']['stops'] if s['role'] == 'stop']
        self.assertEqual(seq, [a['id'], b['id'], 'rock'])

    def test_one_place_fills_one_need(self):
        both = cands('museums', ROCK, 3)
        r = plan(slots=[{'slot_id': 'a', 'label': 'Museum', 'candidates': both}, {'slot_id': 'b', 'label': 'Famous', 'candidates': both}])
        ids = [s['id'] for s in r['itinerary']['stops'] if s.get('slot_id')]
        self.assertEqual(len(ids), len(set(ids)))

    def test_optional_places_respect_budget(self):
        pool = {'max_stops': 6, 'candidates': [{**c, 'visit_min': 30} for c in cands('attractions', ROCK, 10)]}
        r = plan(stops=[ROCK], pool=pool, constraints={'max_outing_minutes': 90})
        it = r['itinerary']
        self.assertTrue(it['constraints']['feasible'])
        self.assertLessEqual(it['totals']['outing_min'], 90)
        self.assertLess(it['pool']['added'], 6, 'budget limits the extra places')
        none = plan(stops=[ROCK], pool={**pool, 'candidates': [{**ROCK, 'id': 'dup', 'visit_min': 30}]})
        self.assertEqual(none['itinerary']['pool']['requested'], 0, 'a pool place equal to a chosen stop is not offered twice')

    def test_distance_limit(self):
        r = plan(stops=[ROCK], slots=[{'slot_id': 'm', 'label': 'Museum', 'candidates': cands('museums', HOTEL, 3)}], constraints={'max_km': .5})
        self.assertFalse(r['itinerary']['constraints']['feasible'])
        self.assertTrue(any('km limit' in v for v in r['itinerary']['constraints']['violations']))

    def test_open_ended_and_fixed_end(self):
        r = plan(end={'mode': 'open'}, stops=[ROCK])
        self.assertEqual(r['itinerary']['stops'][-1]['id'], 'rock')
        lpc = PLACES['historic_lpc'][0]
        r2 = plan(end={'mode': 'fixed', 'place': lpc}, stops=[ROCK])
        self.assertEqual(r2['itinerary']['stops'][-1]['id'], lpc['id'])

    def test_heuristic_is_labelled(self):
        many = [{**c, 'required': True} for c in cands('cafes', ROCK, 9)]
        r = plan(stops=many)
        self.assertTrue(any('heuristic' in m for m in r['itinerary']['method']))
        small = plan(stops=many[:3])
        self.assertTrue(any('exact' in m for m in small['itinerary']['method']))

    def test_outside_coverage_is_explicit(self):
        brooklyn_museum = {'id': 'bkm', 'name': 'Brooklyn Museum', 'lat': 40.6710, 'lon': -73.9633}
        with self.assertRaisesRegex(RoutingError, 'coverage'):
            plan(stops=[{**brooklyn_museum, 'required': True}])
        with self.assertRaisesRegex(RoutingError, 'coverage'):
            IT.plan(validate_request({'origin': brooklyn_museum, 'end': {'mode': 'round'}, 'stops': [ROCK]}))

    def test_validation(self):
        for bad in ({}, {'origin': {'lat': 'x'}}, {'origin': HOTEL, 'end': {'mode': 'fly'}}, {'origin': HOTEL, 'constraints': {'max_minutes': 3}}):
            with self.assertRaises(ValueError):
                validate_request(bad)

    def test_detours_are_real_insertion_costs(self):
        seq = [HOTEL, ROCK]
        cs = cands('cafes', ROCK, 5)
        d = detours(P, {'sequence': seq, 'candidates': cs})
        sn = [NET.snap(p['lon'], p['lat'], p['name']) for p in seq]
        base = NET.distances(sn[0], [sn[1]])[0]
        for c, x in zip(cs, d['candidates']):
            sc = NET.snap(c['lon'], c['lat'], c['name'])
            via = NET.distances(sn[0], [sc])[0] + NET.distances(sc, [sn[1]])[0]
            self.assertAlmostEqual(x['detour_m'], via - base, delta=1.0)
            self.assertGreaterEqual(x['detour_m'], -1.0)


class B_MenuVerification(unittest.TestCase):
    """Menu evidence grades with HTTP stubbed (no network); the official site comes from the place index only."""
    SITE = 'https://cafe.test/'

    def run_with(self, pages, menu_url=None, **doc):
        menu.CACHE.clear()
        def get(u, max_bytes=menu.MAX_BYTES, hops=3):
            final, ctype, body = pages[u]
            return final, ctype, body.encode() if isinstance(body, str) else body, {}
        with mock.patch.object(menu, 'place_sites', return_value={'osm:node/1': (self.SITE, menu_url)}), \
             mock.patch.object(menu, '_allowed', return_value=True), mock.patch.object(menu, 'safe_get', side_effect=get):
            return menu.verify({'place_id': 'osm:node/1', 'name': 'Test Café', 'item': 'cappuccino', **doc})

    def test_confirmed_on_menu_page(self):
        r = self.run_with({'https://cafe.test/menu': ('https://cafe.test/menu', 'text/html', '<title>Menu</title><li>Cappuccino $5.25</li>'),
                           self.SITE: (self.SITE, 'text/html', '<title>Home</title>')}, menu_url='https://cafe.test/menu')
        self.assertEqual(r['status'], 'confirmed_menu_match'); self.assertEqual(r['price'], 5.25)
        self.assertEqual(r['menu_source_url'], 'https://cafe.test/menu'); self.assertEqual(r['matched_item'], 'Cappuccino')
        for k in ('place_id', 'requested_item', 'matched_item', 'evidence_type', 'menu_source_url', 'evidence', 'menu_date', 'checked_at', 'price'):
            self.assertIn(k, r)

    def test_probable_variant_needs_review(self):
        r = self.run_with({'https://cafe.test/menu': ('https://cafe.test/menu', 'text/html', '<title>Menu</title><li>Iced Cappuccinos $6</li>' + 'x' * 300),
                           self.SITE: (self.SITE, 'text/html', '<title>Home</title>')}, menu_url='https://cafe.test/menu')
        self.assertEqual(r['status'], 'probable_match_review'); self.assertIsNone(r['price'])

    def test_follows_menu_link_and_reports_not_found(self):
        r = self.run_with({self.SITE: (self.SITE, 'text/html', '<title>Home</title><a href="/our-menu">Menu</a>'),
                           'https://cafe.test/our-menu': ('https://cafe.test/our-menu', 'text/html', '<title>Our menu</title><li>Latte</li><li>Espresso</li>' + 'y' * 300)})
        self.assertEqual(r['status'], 'not_found_in_checked_sources'); self.assertIn('may differ', r['reason'])

    def test_mention_outside_menu_is_not_verification(self):
        r = self.run_with({self.SITE: (self.SITE, 'text/html', '<title>Blog</title><p>Our cappuccino story</p>')})
        self.assertEqual(r['status'], 'unverified'); self.assertEqual(r['evidence_type'], 'website_mention')

    def test_pdf_menu(self):
        import zlib
        stream = zlib.compress(b'BT /F1 12 Tf (Espresso 3.50) Tj (Cappuccino $4.75) Tj ET')
        pdf = b'%PDF-1.4\n1 0 obj<<>>stream\n' + stream + b'\nendstream\nendobj\n%%EOF'
        r = self.run_with({'https://cafe.test/menu.pdf': ('https://cafe.test/menu.pdf', 'application/pdf', pdf), self.SITE: (self.SITE, 'text/html', '<title>x</title>')},
                          menu_url='https://cafe.test/menu.pdf')
        self.assertEqual(r['status'], 'confirmed_menu_match'); self.assertEqual(r['evidence_type'], 'pdf_menu'); self.assertEqual(r['price'], 4.75)

    def test_image_menu_is_unverified(self):
        r = self.run_with({'https://cafe.test/menu.jpg': ('https://cafe.test/menu.jpg', 'image/jpeg', b'\xff\xd8'), self.SITE: (self.SITE, 'text/html', '<title>x</title>')},
                          menu_url='https://cafe.test/menu.jpg')
        self.assertEqual(r['status'], 'unverified'); self.assertIn('image menu', r['reason'])

    def test_no_website_and_client_url_ignored(self):
        menu.CACHE.clear()
        with mock.patch.object(menu, 'place_sites', return_value={}), mock.patch.object(menu, 'safe_get', side_effect=AssertionError('must not fetch')):
            r = menu.verify({'place_id': 'x', 'name': 'No Site', 'item': 'cappuccino', 'website': 'http://169.254.169.254/', 'menu_url': 'http://127.0.0.1/'})
        self.assertEqual(r['status'], 'unverified'); self.assertIn('No official website', r['reason'])

    def test_robots_disallow_is_respected(self):
        menu.CACHE.clear()
        with mock.patch.object(menu, 'place_sites', return_value={'y': ('https://blocked.test/', None)}), \
             mock.patch.object(menu, '_allowed', return_value=False), mock.patch.object(menu, 'safe_get', side_effect=AssertionError('must not fetch')):
            r = menu.verify({'place_id': 'y', 'name': 'Blocked', 'item': 'cappuccino'})
        self.assertEqual(r['status'], 'unverified'); self.assertIn('robots.txt', r['reason'])

    def test_ssrf_targets_refused(self):
        for u in ('http://127.0.0.1/', 'http://localhost/', 'http://169.254.169.254/latest/meta-data/', 'http://10.1.2.3/', 'http://192.168.0.1/',
                  'http://[::1]/', 'file:///etc/passwd', 'gopher://example.com/', 'http://example.com:6379/', 'http://u:p@example.com/'):
            with self.assertRaises(menu.UnsafeURL, msg=u):
                menu.check_url(u)

    def test_redirect_to_private_address_refused(self):
        class Resp:
            status = 302
            def getheader(self, k, d=None):
                return 'http://127.0.0.1/admin' if k == 'Location' else d
        class Conn:
            def __init__(self, *a, **k): pass
            def request(self, *a, **k): pass
            def getresponse(self): return Resp()
            def close(self): pass
        with mock.patch.object(menu, '_check_host', side_effect=lambda h: '93.184.215.14' if h == 'example.com' else menu.ipaddress.ip_address('127.0.0.1') and (_ for _ in ()).throw(menu.UnsafeURL('private'))), \
             mock.patch.object(menu, '_Pinned', Conn), mock.patch.object(menu, '_PinnedHTTP', Conn):
            with self.assertRaises(menu.UnsafeURL):
                menu.safe_get('https://example.com/')


class D_RouteValidation(unittest.TestCase):
    def test_every_route_and_itinerary_is_validated(self):
        r = P.plan({'lon': -73.9832, 'lat': 40.7536}, {'lon': -73.9787, 'lat': 40.7587}, None, {'max_minutes': 100, 'max_km': 5})
        for x in r['routes']:
            v = x['validation']
            self.assertIn(v['status'], ('pass', 'pass_with_warnings')); self.assertTrue(v['navigation_allowed'])
            for k in ('geometry_status', 'pedestrian_network_status', 'required_stops_status', 'stop_access_status', 'time_constraint_status',
                      'distance_constraint_status', 'food_evidence_status', 'data_coverage', 'warnings', 'blocking_issues', 'validation_version', 'validation_timestamp'):
                self.assertIn(k, v)
            self.assertEqual(v['food_evidence_status'], 'not_checked')
            self.assertTrue(any('closures' in w for w in v['warnings']), 'live passability is never claimed')
        it = plan(stops=[{**ROCK, 'visit_min': 20}])['routes'][0]['validation']
        self.assertEqual(it['required_stops_status'], 'pass')

    def broken(self, mutate):
        from routing.validation import validate
        import copy
        r = copy.deepcopy(plan(stops=[ROCK])['routes'][0])
        mutate(r)
        return validate(r, NET, {'max_minutes': 100}, [{'name': 'Rockefeller Center', 'lat': ROCK['lat'], 'lon': ROCK['lon'], 'required': True, 'snap_distance_m': 4}])

    def test_gap_between_edges_fails(self):
        def cut(r):
            del r['edges'][len(r['edges']) // 2]
        v = self.broken(cut)
        self.assertEqual(v['status'], 'fail'); self.assertFalse(v['navigation_allowed']); self.assertEqual(v['geometry_status'], 'fail')

    def test_unknown_edge_fails(self):
        v = self.broken(lambda r: r['edges'][0].update(edge_id='999-999-0'))
        self.assertEqual(v['pedestrian_network_status'], 'fail'); self.assertFalse(v['navigation_allowed'])

    def test_missed_required_stop_fails(self):
        def detach(r):
            r['geometry']['coordinates'] = r['geometry']['coordinates'][:3]
        v = self.broken(detach)
        self.assertEqual(v['required_stops_status'], 'fail')

    def test_geometry_outside_nyc_fails(self):
        v = self.broken(lambda r: r['geometry']['coordinates'].append([-80.0, 25.0]))
        self.assertEqual(v['geometry_status'], 'fail')

    def test_budget_failure_is_reported_not_blocking(self):
        r = plan(stops=[{**c, 'required': True, 'visit_min': 60} for c in cands('museums', ROCK, 3)], constraints={'max_outing_minutes': 60})
        v = r['routes'][0]['validation']
        self.assertEqual(v['time_constraint_status'], 'fail'); self.assertTrue(v['navigation_allowed'], 'an over-budget walk can still be walked')


class E_DataModel(unittest.TestCase):
    def test_canonical_fields_and_resolution(self):
        met = next(r for r in PLACES['museums'] if r['name'] == 'The Metropolitan Museum of Art')
        self.assertTrue(met['cid'].startswith('sw:')); self.assertEqual(met['status'], 'listed'); self.assertIn(met['q'], ('complete', 'partial', 'minimal'))
        self.assertTrue(met.get('lpc', '').startswith('lpc:'), 'linked to its NYC landmark record')
        lpc = next(r for r in PLACES['historic_lpc'] if r['id'] == met['lpc'])
        self.assertEqual(lpc['cid'], met['cid'], 'one canonical place across sources')
        for cat in PLACES:
            ids = [r['cid'] for r in PLACES[cat]]
            self.assertEqual(len(ids), len(set(ids)) if cat != 'historic_lpc' else len(ids))
            for r in PLACES[cat][:200]:
                self.assertIsInstance(r['snap'], (int, float)); self.assertLessEqual(r['snap'], 150)

    def test_same_building_different_businesses_kept(self):
        recs = [r for r in PLACES['cafes']]
        by_spot = {}
        for r in recs:
            by_spot.setdefault((round(r['lat'], 4), round(r['lon'], 4)), set()).add(r['name'])
        self.assertTrue(any(len(names) > 1 for names in by_spot.values()), 'different cafés at one spot remain separate')

    def test_registry(self):
        reg = json.loads((ROOT / 'data' / 'registry.json').read_text())
        rows = {r['dataset_id']: r for r in reg['datasets']}
        for k in ('street_trees', 'places:cafes', 'pedestrian_network', 'street_segments'):
            self.assertIn(k, rows)
        for r in reg['datasets']:
            for f in ('dataset_id', 'name', 'publisher', 'license', 'retrieved_at', 'coverage_area', 'feature_count', 'integration_status'):
                self.assertIn(f, r)
            if r['integration_status'] == 'connected' and r.get('valid_geometry_count') is not None:
                self.assertLessEqual(r['valid_geometry_count'], r['feature_count'])
        self.assertEqual(rows['places:cafes']['feature_count'], len(PLACES['cafes']))


class C_JourneyContract(unittest.TestCase):
    def test_llm_journey_is_names_and_limits_only(self):
        out = server.validate_interpretation({'weights': {}, 'directions': {}, 'constraints': {}, 'journey': {
            'interests': ['museums', 'teleport'], 'named_stops': [{'name': 'Rockefeller Center', 'required': True}],
            'food': [{'category': 'cafes', 'item': 'cappuccino'}], 'services': ['pharmacies'], 'hotel': {'name': 'Marriott', 'is_mine': True},
            'end_mode': 'hotel', 'outing_minutes': 150, 'distance_km': 5}})
        j = out['journey']
        self.assertEqual(j['interests'], ['museums']); self.assertEqual(j['end_mode'], 'hotel'); self.assertEqual(j['outing_minutes'], 150)
        self.assertEqual(j['hotel'], {'name': 'Marriott', 'is_mine': True})
        with self.assertRaises(ValueError):  # coordinates or menus from the model are refused
            server.validate_interpretation({'weights': {}, 'directions': {}, 'constraints': {}, 'journey': {'lat': 40.7}})

    def test_place_index_provenance(self):
        idx = json.loads((ROOT / 'data' / 'places' / 'index.json').read_text())
        self.assertIn('Manhattan', idx['coverage']); self.assertTrue(idx['osm_timestamp'])
        for cat in ('hotels', 'cafes', 'museums'):
            for r in PLACES[cat][:50]:
                self.assertTrue(r['id'].startswith(('osm:', 'lpc:', 'nycrr:', 'dohmh:'))); self.assertTrue(r['name'])
                NET.snap(r['lon'], r['lat'], r['name'])  # every indexed place is routable


if __name__ == '__main__':
    unittest.main()
