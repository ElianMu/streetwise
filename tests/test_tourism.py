"""Tourism intelligence on the real shipped data: datasets and registry, the canonical place store, opening hours,
provider adapters (HTTP stubbed: no network, no keys), evidence-aware food recommendations, hotels, time-aware itineraries,
the /api/places, /api/hotels and /api/recommend endpoints, and agent scenarios A–F.
Run: python3 -m unittest tests.test_tourism
"""
import json, math, os, pathlib, sys, threading, unittest, urllib.error, urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing.engine import get_planner  # noqa: E402
from routing.itinerary import Planner, validate_request  # noqa: E402
from routing import hours as oh, menu, providers  # noqa: E402
from routing.places import store  # noqa: E402
from routing.recommend import recommend_food  # noqa: E402
import server  # noqa: E402

P = get_planner()
S = store()
KEYS = ('GOOGLE_PLACES_API_KEY', 'YELP_API_KEY', 'FOURSQUARE_API_KEY', 'BOOKING_DEMAND_API_KEY', 'EXPEDIA_RAPID_API_KEY')
NO_KEYS = {k: '' for k in KEYS}
BRYANT = {'lat': 40.7536, 'lon': -73.9832, 'name': 'Bryant Park'}
MADISON_SQ = {'lat': 40.7420, 'lon': -73.9880, 'name': 'Madison Square Park'}
MET = {'lat': 40.7794, 'lon': -73.9632, 'name': 'The Met'}
WED_NOON = '2026-10-21T12:00:00-04:00'


def fake_menu(status):
    def verify(doc, now=None):
        out = {'place_id': doc['place_id'], 'item': doc['item'], 'status': status, 'checked_at': '2026-10-21T16:00:00Z', 'reason': None}
        if status == 'confirmed_menu_match':
            out.update(matched_item=doc['item'].title(), price=4.5, menu_source_url='https://example.test/menu', source_url='https://example.test/menu')
        elif status != 'probable_match_review':
            out['reason'] = 'The item is not on the checked official menu.'
        return out
    return verify


def recommend(doc, status='not_found_in_checked_sources'):
    with mock.patch.dict(os.environ, NO_KEYS), mock.patch.object(menu, 'verify', side_effect=fake_menu(status)):
        providers._cache.clear()
        return recommend_food(P, doc)


class A_Datasets(unittest.TestCase):
    def test_index_ids_unique_and_coordinates_in_manhattan(self):
        for cat in S.categories:
            recs = list(S.records(cat))
            ids = [r['id'] for r in recs]
            self.assertEqual(len(ids), len(set(ids)), cat)
            for r in recs:
                self.assertTrue(40.68 < r['lat'] < 40.89 and -74.05 < r['lon'] < -73.90, (cat, r['id']))

    def test_dohmh_covers_five_boroughs_with_metadata(self):
        meta = S._outside()
        self.assertLessEqual({'Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island'}, set(meta['by_borough']))
        self.assertEqual({r['boro'] for r in S.records('_dohmh')}, {'Brooklyn', 'Queens', 'Bronx', 'Staten Island'})
        self.assertGreater(meta['records'], 20000)
        self.assertIn('43nn-pn8j', meta['source'])

    def test_registry_classes_and_blocked_providers(self):
        reg = json.loads((ROOT / 'data' / 'registry.json').read_text())['datasets']
        classes = {'static_urban', 'periodic_poi', 'on_demand_business', 'realtime_availability'}
        for r in reg:
            self.assertIn(r['data_class'], classes, r['dataset_id'])
            self.assertTrue(r['update_frequency'] and r['known_limitations'], r['dataset_id'])
        prov = {r['dataset_id']: r for r in reg if r['dataset_id'].startswith('provider:')}
        self.assertEqual(set(prov), {'provider:' + p for p in ('google_places', 'yelp_fusion', 'foursquare', 'booking_demand', 'expedia_rapid')})
        self.assertIsNone(prov['provider:yelp_fusion']['feature_count'])   # nothing stored from a provider

    def test_audit_report_table(self):
        md = (ROOT / 'DATA_AUDIT_REPORT.md').read_text()
        self.assertIn('| Dataset | Provider | Class | Coverage | Records | Freshness (days) | Missing fields | Quality | Integration |', md)
        self.assertIn('blocked_by_provider_access', md)


class B_Places(unittest.TestCase):
    def test_met_is_a_verified_attraction_with_sources(self):
        met = S.search(MET, ['museums'], radius_m=300, limit=5, query='metropolitan')[0]
        self.assertEqual(met['quality_status'], 'verified')
        a = met['attraction']
        self.assertTrue(a['designated_landmark'])
        self.assertIn('STREETWISE estimate', a['visit_duration_basis'])
        self.assertIsNone(a['current_exhibitions'])
        self.assertIn('Wikidata', met['data_sources'])

    def test_hotel_keeps_stars_apart_from_guest_rating_and_has_no_rooms(self):
        for h in S.search(BRYANT, ['hotels'], radius_m=800, limit=30):
            self.assertIsNone(h['hotel']['guest_rating'])
            self.assertIsNone(h['hotel']['room_types']); self.assertIsNone(h['hotel']['prices']); self.assertIsNone(h['hotel']['availability'])
            if h['hotel']['star_rating']:
                self.assertEqual(h['hotel']['star_rating_source'], 'OpenStreetMap stars tag')
            if h['quality_status'] == 'verified':
                self.assertIsNotNone(h['hotel']['dof_hotel_lot'])

    def test_outside_manhattan_is_search_only(self):
        res = S.search({'lat': 40.6782, 'lon': -73.9442}, ['restaurants'], radius_m=400, limit=10)
        self.assertTrue(res)
        self.assertTrue(all(r['routing_coverage'] == 'search_only' and r['borough'] == 'Brooklyn' for r in res))

    def test_dohmh_closed_places_hidden_unless_asked(self):
        closed = next(r for c in ('restaurants', 'cafes') for r in S.records(c) if r.get('closed'))
        near = {'lat': closed['lat'], 'lon': closed['lon']}
        ids = lambda **k: {r['index_id'] for r in S.search(near, [closed['cat']], radius_m=30, limit=50, **k)}
        self.assertNotIn(closed['id'], ids())
        self.assertIn(closed['id'], ids(include_closed=True))
        self.assertEqual(S.get(closed['id'])['quality_status'], 'closed')

    def test_branches_stay_separate_entities(self):
        names = {}
        for r in S.records('restaurants'):
            names.setdefault(r['name'], []).append(r)
        multi = next(v for k, v in names.items() if len(v) >= 3 and k)
        self.assertEqual(len({r['id'] for r in multi}), len(multi))
        self.assertGreater(max(math.hypot(a['lat'] - b['lat'], a['lon'] - b['lon']) for a in multi for b in multi), 0)


class C_Hours(unittest.TestCase):
    MET_H = '10:00-17:00; Fr-Sa 10:00-21:00; We off; May Mo[1] off; Nov Th[4] off; Dec 25 off; Jan 01 off'

    def at(self, s):
        return oh.is_open_at(self.MET_H, datetime.fromisoformat(s))

    def test_weekday_rules_and_date_exceptions(self):
        self.assertTrue(self.at('2026-10-23T20:00:00-04:00'))      # Friday late opening
        self.assertFalse(self.at('2026-10-21T12:00:00-04:00'))     # Wednesday off
        self.assertFalse(self.at('2026-11-26T12:00:00-05:00'))     # Thanksgiving
        self.assertTrue(self.at('2026-11-19T12:00:00-05:00'))      # a normal Thursday in November
        self.assertFalse(self.at('2026-12-25T12:00:00-05:00'))
        self.assertFalse(self.at('2027-01-01T12:00:00-05:00'))

    def test_unknown_syntax_is_none_not_a_guess(self):
        self.assertIsNone(oh.is_open_at('sunrise-sunset', datetime.fromisoformat(WED_NOON)))
        self.assertIsNone(oh.is_open_at('Jul-Aug Mo-Fr 09:00-17:00', datetime.fromisoformat('2026-07-15T12:00:00-04:00')))
        self.assertIsNone(oh.is_open_at(None, datetime.fromisoformat(WED_NOON)))

    def test_past_midnight_and_closing_soon(self):
        self.assertTrue(oh.is_open_at('Mo-Su 18:00-02:00', datetime.fromisoformat('2026-10-22T01:30:00-04:00')))
        self.assertTrue(oh.closes_within('Mo-Su 09:00-17:00', datetime.fromisoformat('2026-10-21T16:40:00-04:00'), 45))
        self.assertFalse(oh.closes_within('Mo-Su 09:00-17:00', datetime.fromisoformat('2026-10-21T12:00:00-04:00'), 45))


class D_Providers(unittest.TestCase):
    PLACE = {'place_id': 'x', 'name': 'Joe Coffee Company', 'address': '1 Test St', 'lat': 40.75, 'lon': -73.98}

    def setUp(self):
        providers._cache.clear()

    def test_without_keys_everything_is_blocked(self):
        with mock.patch.dict(os.environ, NO_KEYS), mock.patch.object(providers, '_http', side_effect=AssertionError('no call without a key')):
            r = providers.ratings(self.PLACE)
            rooms = providers.hotel_rooms(self.PLACE, '2026-11-01', '2026-11-03', 2)
        self.assertEqual(r['status'], 'blocked_by_provider_access'); self.assertEqual(r['ratings'], [])
        self.assertEqual(rooms['status'], 'blocked_by_provider_access'); self.assertEqual(rooms['rooms'], [])

    def test_ratings_kept_per_provider_and_matched_by_place(self):
        google = {'places': [{'id': 'g1', 'displayName': {'text': 'Joe Coffee Company'}, 'location': {'latitude': 40.7501, 'longitude': -73.9801}, 'rating': 4.5, 'userRatingCount': 900}]}
        yelp = {'businesses': [{'id': 'y1', 'name': 'Joe Coffee', 'coordinates': {'latitude': 40.7502, 'longitude': -73.98}, 'rating': 4.0, 'review_count': 300, 'url': 'https://yelp.test/joe'}]}
        env = {**NO_KEYS, 'GOOGLE_PLACES_API_KEY': 'k', 'YELP_API_KEY': 'k'}
        with mock.patch.dict(os.environ, env), mock.patch.object(providers, '_http', side_effect=lambda url, *a, **k: google if 'googleapis' in url else yelp):
            r = providers.ratings(self.PLACE)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual({(x['provider'], x['rating'], x['review_count']) for x in r['ratings']}, {('Google', 4.5, 900), ('Yelp', 4.0, 300)})
        self.assertFalse({'rating', 'combined_rating', 'score'} & set(r)); self.assertEqual(r['not_configured'], ['foursquare'])

    def test_a_different_place_is_not_accepted(self):
        far = {'places': [{'id': 'g2', 'displayName': {'text': 'Joe Coffee Company'}, 'location': {'latitude': 40.76, 'longitude': -73.97}, 'rating': 3.1}]}
        with mock.patch.dict(os.environ, {**NO_KEYS, 'GOOGLE_PLACES_API_KEY': 'k'}), mock.patch.object(providers, '_http', return_value=far):
            r = providers.ratings(self.PLACE)
        self.assertEqual(r['ratings'], []); self.assertEqual(r['status'], 'unavailable')
        self.assertIn('no confident match', r['errors'][0]['error'])


class E_Scenarios(unittest.TestCase):
    """Agent scenarios A–F of the specification, answered from evidence only."""

    def test_A_item_not_confirmed_is_never_presented_as_meeting_the_request(self):
        r = recommend({'item': 'cappuccino', 'categories': ['cafes'], 'near': MET, 'radius_m': 700, 'departure': WED_NOON})
        self.assertEqual(r['status'], 'no_confirmed_match')
        self.assertFalse([c for c in r['candidates'] if c['classification'] == 'meets_request'])
        for c in r['candidates']:
            if c['classification'] != 'excluded':
                self.assertTrue(any('cappuccino' in u for u in c['explanation']['unknown']))
                self.assertEqual(c['explanation']['interpretation_basis'], 'rule-based (no language model)')

    def test_B_confirmed_item_ranks_first_with_evidence(self):
        r = recommend({'item': 'bagel', 'categories': ['cafes', 'restaurants'], 'sequence': [BRYANT, MADISON_SQ], 'radius_m': 800, 'departure': WED_NOON},
                      status='confirmed_menu_match')
        self.assertEqual(r['status'], 'ok')
        meets = [c for c in r['candidates'] if c['classification'] == 'meets_request']
        self.assertTrue(meets)
        self.assertEqual(r['candidates'][0]['classification'], 'meets_request')
        for c in meets:
            self.assertEqual(c['item_status'], 'confirmed_menu_match'); self.assertTrue(c['place']['official_website'])
            self.assertTrue(any('official menu' in f for f in c['explanation']['verified_facts']))
            self.assertIn('Today’s stock and prices: a menu listing does not confirm them.', c['explanation']['unknown'])
            self.assertIsNotNone(c['detour_m'])
        ranks = [c['detour_m'] for c in meets]
        self.assertEqual(ranks, sorted(ranks))
        for c in r['candidates']:
            if c['item_status'] == 'not_checked':
                self.assertEqual(c['classification'], 'not_confirmed'); self.assertTrue(c['menu']['reason'])

    def test_B2_probable_match_needs_review(self):
        r = recommend({'item': 'flat white', 'categories': ['cafes'], 'near': BRYANT, 'radius_m': 600, 'departure': WED_NOON}, status='probable_match_review')
        self.assertEqual(r['status'], 'no_confirmed_match')
        self.assertTrue(any(c['classification'] == 'needs_review' for c in r['candidates']))

    def test_C_closed_at_arrival_is_excluded_and_ranked_last(self):
        r = recommend({'item': 'coffee', 'categories': ['cafes'], 'near': BRYANT, 'radius_m': 600, 'departure': '2026-10-21T03:30:00-04:00'}, status='confirmed_menu_match')
        closed = [c for c in r['candidates'] if c['open_at_arrival'] is False]
        self.assertTrue(closed)
        self.assertTrue(all(c['classification'] == 'excluded' and c['ratings'] is None for c in closed))
        order = [c['classification'] == 'excluded' for c in r['candidates']]
        self.assertEqual(order, sorted(order))

    def test_D_hotel_rooms_and_budget_are_blocked_not_invented(self):
        h = next(x for x in S.search(BRYANT, ['hotels'], radius_m=800, limit=20))
        with mock.patch.dict(os.environ, NO_KEYS):
            r = providers.hotel_rooms(h, '2026-11-01', '2026-11-03', 2)
        self.assertEqual((r['status'], r['rooms']), ('blocked_by_provider_access', []))
        self.assertNotRegex(json.dumps(r), r'\$\d')

    def test_E_detour_limit_and_closed_permits_are_hard_filters(self):
        r = recommend({'categories': ['restaurants'], 'near': BRYANT, 'radius_m': 900, 'max_detour_min': 3, 'departure': WED_NOON})
        for c in r['candidates']:
            if c['detour_min'] is not None and c['detour_min'] > 3:
                self.assertEqual(c['classification'], 'excluded')
            self.assertNotEqual(c['place']['quality_status'], 'closed')

    def test_F_no_rating_is_shown_without_a_provider(self):
        r = recommend({'item': 'espresso', 'categories': ['cafes'], 'near': BRYANT, 'radius_m': 500, 'departure': WED_NOON})
        for c in r['candidates']:
            if c['classification'] != 'excluded':
                self.assertEqual(c['ratings']['status'], 'blocked_by_provider_access')
                self.assertIn('Ratings and review counts: no rating provider is configured.', c['explanation']['unknown'])
                self.assertFalse([f for f in c['explanation']['verified_facts'] if 'rating ' in f])


class F_TimeAwareItinerary(unittest.TestCase):
    def test_required_stop_closed_at_arrival_is_reported(self):
        stop = {'id': 'kaufman', 'name': 'Test venue', 'lat': 40.7735, 'lon': -73.9845, 'hours': 'Mo-Su 09:00-10:00', 'visit_min': 20}
        r = Planner(P).plan(validate_request({'origin': BRYANT, 'end': {'mode': 'round'}, 'stops': [stop], 'departure': '2026-10-23T16:40:00-04:00'}))
        it = r['itinerary']
        s = next(x for x in it['stops'] if x['name'] == 'Test venue')
        self.assertIs(s['open_at_arrival'], False)
        self.assertFalse(it['constraints']['feasible'])
        self.assertTrue(any('closed at the estimated arrival' in v for v in it['constraints']['violations']))
        v = r['routes'][0]['validation']
        self.assertEqual(v['opening_hours_status'], 'fail')
        self.assertTrue(v['navigation_allowed'])   # a closed venue is reported, never a reason to block walking

    def test_open_stop_has_no_time_violation(self):
        stop = {'id': 'v', 'name': 'Open venue', 'lat': 40.7735, 'lon': -73.9845, 'hours': 'Mo-Su 09:00-22:00', 'visit_min': 20}
        it = Planner(P).plan(validate_request({'origin': BRYANT, 'end': {'mode': 'round'}, 'stops': [stop], 'departure': '2026-10-23T16:40:00-04:00'}))['itinerary']
        self.assertIs(next(x for x in it['stops'] if x['name'] == 'Open venue')['open_at_arrival'], True)
        self.assertFalse([v for v in it['constraints']['violations'] if 'closed' in v])


class G_Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, NO_KEYS); cls.env.start()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.env.stop()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def test_status_reports_providers_without_keys(self):
        code, d = self.get('/api/status')
        self.assertEqual(code, 200)
        self.assertEqual(set(d['providers']), {'google_places', 'yelp_fusion', 'foursquare', 'booking_demand', 'expedia_rapid'})
        self.assertNotIn('KEY', json.dumps(d))

    def test_search_detail_ratings_rooms(self):
        code, d = self.get('/api/places/search?lat=40.7536&lon=-73.9832&categories=hotels&radius_m=600&limit=2')
        self.assertEqual(code, 200)
        hid = d['results'][0]['index_id']
        code, h = self.get('/api/places/' + hid)
        self.assertEqual((code, h['category']), (200, 'hotels'))
        self.assertEqual(self.get(f'/api/hotels/{hid}/rooms?checkin=2026-11-01&checkout=2026-11-03&guests=2')[1]['status'], 'blocked_by_provider_access')
        self.assertEqual(self.get(f'/api/places/{hid}/ratings')[1]['status'], 'blocked_by_provider_access')

    def test_slash_ids_and_bad_input(self):
        oid = next(r['id'] for r in S.records('museums') if r['id'].startswith('osm:'))
        self.assertEqual(self.get('/api/places/' + oid)[0], 200)
        self.assertEqual(self.get('/api/places/nope:1')[0], 404)
        self.assertEqual(self.get('/api/places/search?lat=1&lon=2')[0], 400)
        self.assertEqual(self.get('/api/hotels/' + oid + '/rooms')[0], 404)
        self.assertEqual(self.get('/api/places/search?lon=-73.98')[0], 400)


if __name__ == '__main__':
    unittest.main()
