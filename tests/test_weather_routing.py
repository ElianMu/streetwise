"""Weather-aware routing (routing/weather.py + engine) on the real network: weather is a separate dynamic context,
enters the edge cost only with spatial evidence (daytime heat → street-tree / park cover proxy), keeps every hard
constraint, and never changes a route when it does not apply. Weather values are fixed test snapshots, not live API data.
Run: python3 -m unittest tests.test_weather_routing
"""
import pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing import weather as wx  # noqa: E402
from routing.engine import get_planner  # noqa: E402
import server  # noqa: E402

P = get_planner()
NET = P.net
PLACES = {'bryant': (-73.9832, 40.7536), 'rock': (-73.9787, 40.7587), 'chelsea_a': (-74.0060, 40.7425), 'chelsea_b': (-73.9934, 40.7505),
          'met': (-73.9632, 40.7794), 'columbia': (-73.9626, 40.8075)}
pt = lambda k: {'lon': PLACES[k][0], 'lat': PLACES[k][1]}
HOT = {'source': 'test', 'kind': 'forecast_window', 'age_min': 5, 'feels_like_max_c': 34, 'temperature_max_c': 31,
       'precip_probability_max_pct': 10, 'precip_max_mm_per_h': 0, 'wind_max_kmh': 12, 'daylight': True}
MILD = dict(HOT, feels_like_max_c=19, temperature_max_c=19)


def plan(a, b, weather=None, weights=None, **constraints):
    return P.plan(pt(a), pt(b), {'weights': weights or {}, 'directions': {}}, constraints or {'max_minutes': 60}, weather)


def paths(resp):
    return [(r['objective'], tuple(r['ordered_edge_ids']), r['recommended']) for r in resp['routes']]


class A_WeatherContext(unittest.TestCase):
    def test_snapshot_validation(self):
        self.assertIsNone(wx.validate_snapshot(None))
        with self.assertRaises(ValueError):
            wx.validate_snapshot('hot')
        s = wx.validate_snapshot({'kind': 'forecast_window', 'feels_like_max_c': 999, 'precip_probability_max_pct': -3, 'mode': 'x', 'priority': 'max'})
        self.assertIsNone(s['feels_like_max_c']); self.assertIsNone(s['precip_probability_max_pct'])  # out of range → unknown, never "normal"
        self.assertEqual((s['mode'], s['priority']), ('auto', 'normal'))

    def test_four_states_are_distinct(self):
        none = wx.assess(None)
        self.assertFalse(none['data_available']); self.assertEqual(none['routing']['status'], 'unavailable')
        stale = wx.assess(wx.validate_snapshot(dict(HOT, age_min=500)))
        self.assertFalse(stale['data_available']); self.assertFalse(stale['routing']['active'])
        mild = wx.assess(wx.validate_snapshot(MILD))
        self.assertTrue(mild['data_available']); self.assertEqual(mild['routing']['status'], 'not_active')  # data available ≠ routing active
        hot = wx.assess(wx.validate_snapshot(HOT))
        self.assertTrue(hot['routing']['active']); self.assertEqual(hot['routing']['factor'], 'heat'); self.assertEqual(hot['routing']['level'], 1.0)
        self.assertEqual(wx.assess(wx.validate_snapshot(HOT), evidence_available=False)['routing']['status'], 'unavailable')

    def test_heat_only_by_day_and_switchable(self):
        self.assertFalse(wx.assess(wx.validate_snapshot(dict(HOT, daylight=False)))['routing']['active'])
        self.assertFalse(wx.assess(wx.validate_snapshot(dict(HOT, mode='off')))['routing']['active'])
        self.assertEqual(wx.assess(wx.validate_snapshot(dict(HOT, priority='high')))['routing']['multiplier'], wx.CONFIG['heat']['explicit_request_multiplier'])
        self.assertEqual(wx.heat_level(27), 0.0); self.assertEqual(wx.heat_level(29.5), 0.5); self.assertEqual(wx.heat_level(40), 1.0)

    def test_rain_and_wind_are_advisory_only(self):
        a = wx.assess(wx.validate_snapshot(dict(MILD, precip_probability_max_pct=90, precip_max_mm_per_h=4, wind_max_kmh=55)))
        f = {x['factor']: x for x in a['factors']}
        self.assertTrue(f['rain']['advisory']); self.assertTrue(f['wind']['advisory'])
        self.assertFalse(f['rain']['routing_capable']); self.assertFalse(f['wind']['routing_capable'])
        self.assertFalse(a['routing']['active'])  # no covered-walkway or wind-exposure data → never a route change

    def test_cover_proxy_and_missing_evidence(self):
        full = wx.CONFIG['heat']['tree_km_full_cover']
        self.assertEqual(wx.edge_cover({'raw': {'tree_km': full, 'park_pct': 0}}, {}), 1.0)
        self.assertEqual(wx.edge_cover({'raw': {'tree_km': 0, 'park_pct': 100}}, {}), 1.0)
        self.assertEqual(wx.edge_cover({'m': ['A', 'B']}, {'A': {'tree_km': full / 2, 'park_pct': 0}, 'B': {'tree_km': 0, 'park_pct': 0}}), .25)
        self.assertIsNone(wx.edge_cover({'m': []}, {}))
        exp, has, median = NET.heat_exposure()
        self.assertGreater(sum(has) / len(has), .9)
        for e, h in zip(exp, has):
            if not h:
                self.assertAlmostEqual(e, median, 3)  # missing evidence is neutral, never the worst case


class B_WeatherRouting(unittest.TestCase):
    def test_no_or_mild_weather_keeps_static_routes(self):
        base = plan('bryant', 'rock')
        self.assertEqual(base['weather_routing']['routing']['status'], 'unavailable')
        for wthr in (MILD, dict(HOT, daylight=False), dict(HOT, mode='off')):
            r = plan('bryant', 'rock', wthr)
            self.assertEqual(paths(r), paths(base))
            self.assertFalse(r['weather_routing']['routing']['active'])
            self.assertTrue(all('weather_adjustment' not in x['personalized_score'] for x in r['routes']))

    def test_static_candidates_unchanged_and_heat_term_in_search(self):
        base, hot = plan('chelsea_a', 'chelsea_b'), plan('chelsea_a', 'chelsea_b', HOT)
        static = lambda resp: {p for o, p, _ in paths(resp) if o != 'weather_heat'}
        self.assertEqual(static(hot), static(base))  # the heat search is an extra candidate; it never alters the static ones
        self.assertTrue(hot['weather_routing']['routing']['active'])
        for r in hot['routes']:
            self.assertIn('weather', r); self.assertGreater(r['weather']['evidence_coverage'], .5)
            self.assertIn('weather_adjustment', r['personalized_score'])

    def test_heat_term_reduces_exposed_length(self):
        """Same search, same experience term, plus the heat term: the exposed metres can only go down (A* optimality)."""
        o, d = NET.snap(*PLACES['chelsea_a'], 'o'), NET.snap(*PLACES['chelsea_b'], 'd')
        exp, _, _ = NET.heat_exposure()
        util = lambda gi: P.edge_utility(gi, {})
        base = lambda i: 1.0 + .8 * (1 - util(NET.edges[i][3]))
        heat = lambda i: base(i) + wx.CONFIG['heat']['edge_coefficient'] * 2 * exp[NET.edges[i][3]]
        exposed = lambda steps: sum(exp[NET.edges[i][3]] * (b - a) for i, a, b in steps)
        sb, sh = NET.search(o, d, base), NET.search(o, d, heat)
        self.assertLessEqual(exposed(sh), exposed(sb) + 1e-6)
        self.assertLess(exposed(sh), exposed(sb))  # on this trip the cooler path is genuinely different

    def test_effect_record_is_consistent(self):
        r = plan('chelsea_a', 'chelsea_b', dict(HOT, priority='high'))
        e = r['weather_routing']['routing']['effect']
        best = next(x for x in r['routes'] if x['recommended'])
        self.assertEqual(e['recommended_route_id'], best['route_id'])
        base = next(x for x in r['routes'] if x['route_id'] == e['baseline_route_id'])
        self.assertNotEqual(base['objective'], 'weather_heat')
        if e['changed']:
            self.assertLess(best['weather']['heat_exposure_share'], base['weather']['heat_exposure_share'])
            self.assertAlmostEqual(e['extra_minutes'], best['estimated_duration_min'] - base['estimated_duration_min'], 1)
        else:
            self.assertEqual(e['extra_minutes'], 0.0)

    def test_hard_constraints_survive_weather(self):
        r = plan('met', 'columbia', dict(HOT, priority='high'), max_minutes=52, avoid_stairs=True)
        for x in r['routes']:
            self.assertFalse(any(e['pedestrian_access']['steps'] for e in x['edges']))
            if x['estimated_duration_min'] > 52:
                self.assertFalse(x['constraints']['feasible'])
        best = [x for x in r['routes'] if x['recommended']]
        self.assertTrue(all(x['constraints']['feasible'] for x in best))

    def test_reproducible(self):
        a, b = plan('chelsea_a', 'chelsea_b', HOT), plan('chelsea_a', 'chelsea_b', HOT)
        self.assertEqual([(o, p) for o, p, _ in paths(a)], [(o, p) for o, p, _ in paths(b)])
        strip = lambda w: {**w['routing'], 'effect': None}
        self.assertEqual(strip(a['weather_routing']), strip(b['weather_routing']))
        self.assertEqual(a['weather_routing']['config_version'], wx.CONFIG_VERSION)

    def test_static_dimension_scores_never_change(self):
        base, hot = plan('bryant', 'rock'), plan('bryant', 'rock', HOT)
        by = {tuple(r['ordered_edge_ids']): r['dimension_scores'] for r in base['routes']}
        for r in hot['routes']:
            if tuple(r['ordered_edge_ids']) in by:
                self.assertEqual(r['dimension_scores'], by[tuple(r['ordered_edge_ids'])])
            self.assertEqual(len(r['dimension_scores']), 12)  # no 13th dimension


class C_Contracts(unittest.TestCase):
    def test_route_request_carries_weather(self):
        doc = {'origin': {'lat': 40.75, 'lon': -73.98}, 'destination': {'lat': 40.76, 'lon': -73.97}, 'weather': HOT}
        self.assertEqual(server.validate_route_request(doc)[4]['feels_like_max_c'], 34.0)
        self.assertIsNone(server.validate_route_request({**doc, 'weather': None})[4])

    def test_llm_weather_intent(self):
        ok = server.validate_interpretation({'weights': {}, 'directions': {}, 'constraints': {}, 'weather': 'cooler'})
        self.assertEqual(ok['weather'], 'cooler')
        with self.assertRaises(ValueError):
            server.validate_interpretation({'weights': {}, 'directions': {}, 'constraints': {}, 'weather': 'make it 5 degrees cooler'})


if __name__ == '__main__':
    unittest.main()
