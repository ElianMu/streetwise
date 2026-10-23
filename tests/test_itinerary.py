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
    def run_with(self, pages, **doc):
        menu.CACHE.clear()
        with mock.patch.object(menu, '_allowed', return_value=True), mock.patch.object(menu, '_get', side_effect=lambda u: pages[u]):
            return menu.verify({'place_id': 'osm:node/1', 'name': 'Test Café', 'item': 'cappuccino', **doc})

    def test_verified_on_menu_page(self):
        r = self.run_with({'https://cafe.test/menu': ('https://cafe.test/menu', '<title>Menu</title><li>Cappuccino $5.25</li>')}, menu_url='https://cafe.test/menu')
        self.assertEqual(r['status'], 'verified_on_menu'); self.assertEqual(r['price'], 5.25); self.assertEqual(r['source_url'], 'https://cafe.test/menu')

    def test_follows_menu_link_and_reports_not_found(self):
        pages = {'https://cafe.test/': ('https://cafe.test/', '<title>Home</title><a href="/our-menu">Menu</a>'),
                 'https://cafe.test/our-menu': ('https://cafe.test/our-menu', '<title>Our menu</title><li>Latte</li><li>Espresso</li>')}
        r = self.run_with(pages, website='https://cafe.test/')
        self.assertEqual(r['status'], 'not_found'); self.assertIn('cannot be read', r['reason'])

    def test_mention_outside_menu_is_not_verification(self):
        r = self.run_with({'https://cafe.test/': ('https://cafe.test/', '<title>Blog</title><p>Our cappuccino story</p>')}, website='https://cafe.test/')
        self.assertEqual(r['status'], 'unverified')

    def test_no_website(self):
        r = menu.verify({'place_id': 'x', 'name': 'No Site', 'item': 'cappuccino'})
        self.assertEqual(r['status'], 'unverified'); self.assertIn('No official website', r['reason'])

    def test_robots_disallow_is_respected(self):
        menu.CACHE.clear()
        with mock.patch.object(menu, '_allowed', return_value=False), mock.patch.object(menu, '_get', side_effect=AssertionError('must not fetch')):
            r = menu.verify({'place_id': 'y', 'name': 'Blocked', 'item': 'cappuccino', 'website': 'https://blocked.test/'})
        self.assertEqual(r['status'], 'unverified'); self.assertIn('robots.txt', r['reason'])


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
                self.assertTrue(r['id'].startswith(('osm:', 'lpc:', 'nycrr:'))); self.assertTrue(r['name'])
                NET.snap(r['lon'], r['lat'], r['name'])  # every indexed place is routable


if __name__ == '__main__':
    unittest.main()
