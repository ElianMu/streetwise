"""Evidence and failure-path regressions; provider responses are explicitly mocked."""
import contextlib, copy, importlib.util, json, os, pathlib, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from datetime import date, timedelta
from unittest import mock
from http.server import ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from routing import menu, providers
from routing.places import store
from routing.engine import get_planner, RoutingError
from routing.itinerary import validate_request
import build_place_index as build
import server


class TourismEvidence(unittest.TestCase):
    def test_official_citywide_snapshot(self):
        d=json.loads((ROOT/'data/places/citywide.json').read_text())
        self.assertEqual(len(d['records']),sum(s['records'] for s in d['metadata']['sources']))
        self.assertEqual(len(d['records']),len({r['id'] for r in d['records']}))
        self.assertEqual({r['boro'] for r in d['records'] if r['cat']=='parks'}, {'Manhattan','Brooklyn','Queens','Bronx','Staten Island'})
        self.assertTrue(all(r['search_only'] and r['source_url'].startswith('https://data.cityofnewyork.us/') for r in d['records']))
        q=store().search({'lat':40.67,'lon':-73.98},['parks'],radius_m=3000)
        self.assertTrue(q)
        self.assertTrue(all(r['routing_coverage']=='search_only' for r in q))

    def test_queens_inside_manhattan_rectangle_still_gets_citywide_food(self):
        results=store().search({'lat':40.744,'lon':-73.956},['restaurants'],radius_m=1000,limit=50)
        queens=[r for r in results if r['borough']=='Queens']
        self.assertTrue(queens)
        self.assertTrue(all(r['routing_coverage']=='search_only' for r in queens))

    def test_current_inspection_and_snapshot_timestamp_are_distinct(self):
        r={'id':'test:1','name':'Test fixture','lat':40.75,'lon':-73.98,'cat':'cafes','src':'osm','chk':'2026-10-24','amen':{'wifi':'no','delivery':'yes'}}
        p=store().canonical(r)
        self.assertIsNone(p['last_verified_at']);self.assertEqual(p['retrieved_at'],'2026-10-24')
        self.assertNotIn('wifi',p['amenities'])
        self.assertEqual(store().quality({**r,'dohmh':'1','insp':date.today().isoformat()}),'verified')
        self.assertNotEqual(store().quality({**r,'dohmh':'1','insp':(date.today()+timedelta(days=1)).isoformat()}),'verified')

    def test_entity_resolution_does_not_merge_by_nearness_alone(self):
        records=[{'id':'osm:node/1','name':'Same Brand','lat':40.75,'lon':-73.98,'sub':'amenity=cafe','src':'osm','addr':'1 West Street'},
                 {'id':'osm:node/2','name':'Same Brand','lat':40.75001,'lon':-73.98,'sub':'amenity=cafe','src':'osm','addr':'2 West Street'}]
        groups={c:[] for c,_,_ in build.CATEGORIES};groups['historic_lpc']=[];groups['cafes']=records
        with tempfile.TemporaryDirectory() as t, mock.patch.object(build,'OUT',t):
            build.resolve_entities(groups,'2026-10-24','2026-10-24')
        self.assertEqual(len(groups['cafes']),2)

    def test_exact_official_links_preserve_current_unavailable_status(self):
        S=store()
        self.assertTrue(S.official_updates)
        pid=next(k for k,v in S.official_updates.items() if v.get('source_status')=='Not Operational')
        p=S.get(pid)
        self.assertEqual(p['operational_status'],'Not Operational')
        nearby=S.search(p['coordinates'],['restrooms'],radius_m=100,limit=50)
        self.assertNotIn(p['place_id'],{x['place_id'] for x in nearby})

    def test_split_entity_does_not_reuse_one_canonical_id_twice(self):
        records=[{'id':'osm:node/1','name':'Same Brand','lat':40.75,'lon':-73.98,'sub':'amenity=cafe','src':'osm','addr':'1 West St'},
                 {'id':'osm:node/2','name':'Same Brand','lat':40.75001,'lon':-73.98,'sub':'amenity=cafe','src':'osm','addr':'2 West St'}]
        groups={c:[] for c,_,_ in build.CATEGORIES};groups['historic_lpc']=[];groups['cafes']=records
        with tempfile.TemporaryDirectory() as t:
            pathlib.Path(t,'index.json').write_text(json.dumps({'categories':[{'id':'cafes'}]}))
            pathlib.Path(t,'cafes.json').write_text(json.dumps({'records':[{**records[0],'cid':'sw:previous','pids':['osm:node/1','osm:node/2']}]}))
            with mock.patch.object(build,'OUT',t):build.resolve_entities(groups,'2026-10-24','2026-10-24')
        self.assertEqual(len({r['cid'] for r in groups['cafes']}),2)
        self.assertEqual(next(r for r in groups['cafes'] if r['id']=='osm:node/1')['cid'],'sw:previous')

    def test_nearby_different_branch_is_not_a_provider_match(self):
        p={'name':'Test Cafe','address':'1 West St','lat':40.75,'lon':-73.98}
        self.assertFalse(providers._same_place(p,'Test Cafe',-73.98,40.75001,'2 West St'))
        self.assertFalse(providers._same_place(p,'Test Cafe',-73.98,40.75001,None))
        self.assertTrue(providers._same_place(p,'Test Cafe',-73.98,40.75001,'1 West Street'))

    def test_structured_item_price_is_associated_not_nearby(self):
        html='<script type="application/ld+json">'+json.dumps({'@type':'Menu','hasMenuItem':[
            {'@type':'MenuItem','name':'Cappuccino','offers':{'price':'5.25','priceCurrency':'USD'}},
            {'@type':'MenuItem','name':'Tiramisu','offers':{'price':'12','priceCurrency':'USD'}}]})+'</script>'
        items=menu.structured_menu_items(html)
        by_name={i['name']:i for i in items}
        self.assertEqual(by_name['Cappuccino']['price'],5.25);self.assertEqual(by_name['Tiramisu']['price'],12)
        self.assertIsNone(menu.match_item('cappuccino','Cappuccino unavailable. Tiramisu $12')[3])

    def test_restricted_platform_pages_are_not_scraped(self):
        with mock.patch.object(menu,'_check_host') as dns:
            for url in ['https://www.yelp.com/biz/example','https://booking.com/hotel/example','https://www.google.com/maps/place/example']:
                with self.assertRaises(menu.UnsafeURL):menu.check_url(url)
            dns.assert_not_called()

    def test_menu_deadline_prevents_another_network_hop(self):
        with mock.patch.object(menu,'check_url') as dns,self.assertRaises(TimeoutError):
            menu.safe_get('https://example.test/menu',deadline=time.monotonic()-1)
        dns.assert_not_called()

    def test_unreachable_robots_does_not_authorize_crawling(self):
        with mock.patch.object(menu,'safe_get',side_effect=OSError('HTTP 503')):
            self.assertFalse(menu._allowed('https://example.test/menu'))
        with mock.patch.object(menu,'safe_get',side_effect=OSError('HTTP 404')):
            self.assertTrue(menu._allowed('https://example.test/menu'))

    def test_stale_menu_is_not_current_evidence(self):
        menu.CACHE.clear()
        with mock.patch.object(menu,'place_sites',return_value={'test:stale':('https://example.test','https://example.test/menu')}),mock.patch.object(menu,'_allowed',return_value=True),mock.patch.object(menu,'safe_get',return_value=('https://example.test/menu','text/html',b'<title>Menu</title>Cappuccino $5',{'Last-Modified':'Mon, 01 Jan 2018 00:00:00 GMT'})):
            r=menu.verify({'place_id':'test:stale','item':'cappuccino'})
        self.assertEqual(r['status'],'unverified');self.assertEqual(r['freshness'],'stale');self.assertIsNone(r['price'])

    def test_source_id_cannot_label_different_coordinates(self):
        from routing.itinerary import Planner
        hotel=next(store().records('hotels'))
        request=validate_request({'origin':{'id':'b','name':'Bryant','lat':40.7536,'lon':-73.9832},'end':{'mode':'round'},
            'stops':[{'id':hotel['id'],'name':hotel['name'],'lat':40.7536,'lon':-73.98,'required':True}]})
        with self.assertRaisesRegex(RoutingError,'coordinates disagree'):
            Planner(get_planner()).plan(request)

    def test_missing_required_poi_and_unverified_item_are_blocked(self):
        origin={'id':'o','name':'Bryant','lat':40.7536,'lon':-73.9832}
        for slots in [[{'label':'coffee','required':True,'candidates':[]}],
                      [{'label':'coffee','required':True,'required_item':'imaginary-item','candidates':[origin]}]]:
            with self.assertRaises(RoutingError):validate_request({'origin':origin,'slots':slots})
        with self.assertRaises(RoutingError):validate_request({'origin':origin,'constraints':{'step_free':True}})

    def test_business_requirements_and_counts_survive_validation(self):
        r=server.validate_interpretation({'journey':{'interests':['famous'],'counts':{'famous':2},
            'requirements':{'ratings_required':True,'hotel_budget_per_night_usd':250,'beds':2,'must_be_open':True}}})
        self.assertEqual(r['journey']['counts']['famous'],2)
        self.assertEqual(r['journey']['requirements']['hotel_budget_per_night_usd'],250)
        with self.assertRaises(ValueError):server.validate_interpretation({'journey':{'requirements':{'minimum_rating':6}}})

    def test_missing_opening_hours_blocks_required_visit_when_requested(self):
        from routing.itinerary import Planner
        request=validate_request({'origin':{'id':'b','name':'Bryant','lat':40.7536,'lon':-73.9832},
            'end':{'mode':'fixed','place':{'id':'r','name':'Rockefeller','lat':40.7587,'lon':-73.9787}},
            'stops':[{'id':'s','name':'Fixture stop with unknown hours','lat':40.756,'lon':-73.981,'required':True}],
            'departure':'2026-11-01T12:00:00-05:00','constraints':{'max_minutes':100,'require_open':True}})
        result=Planner(get_planner()).plan(request)
        self.assertFalse(result['itinerary']['constraints']['feasible'])
        self.assertFalse(result['routes'][0]['validation']['navigation_allowed'])

    def test_snapshot_publish_rolls_back_on_failure(self):
        from snapshot_io import publish
        with tempfile.TemporaryDirectory() as t:
            destination=pathlib.Path(t)/'live';history=pathlib.Path(t)/'history';destination.mkdir()
            (destination/'a.json').write_text('{"old":1}')
            (destination/'index.json').write_text('{"old":2}')
            real_replace=os.replace;calls=0
            def once(a,b):
                nonlocal calls
                calls+=1
                if calls==2:raise OSError('simulated disk error')
                return real_replace(a,b)
            with mock.patch.object(os,'replace',side_effect=once),self.assertRaises(OSError):
                publish(destination,{'a.json':{'new':1},'index.json':{'new':2}},history)
            self.assertEqual(json.loads((destination/'a.json').read_text()),{'old':1})
            self.assertEqual(json.loads((destination/'index.json').read_text()),{'old':2})

    def test_key_format_and_room_dates(self):
        with mock.patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'bad\nkey'}),self.assertRaisesRegex(RuntimeError,'invalid_key_format'):
            providers._key('GOOGLE_PLACES_API_KEY')
        p={'place_id':'test:hotel'}
        with self.assertRaises(ValueError):providers.hotel_rooms(p,'2027-02-30','2027-03-01',2)
        with self.assertRaises(ValueError):providers.hotel_rooms(p,'2027-02-02','2027-02-01',2)
        with mock.patch.dict(os.environ,{'BOOKING_DEMAND_API_KEY':'','EXPEDIA_RAPID_API_KEY':''}):
            r=providers.hotel_rooms(p,None,None,2)
        self.assertEqual(r['status'],'blocked_by_provider_access');self.assertEqual(r['rooms'],[])

    def test_required_reviews_do_not_turn_missing_into_bad_rating(self):
        from routing.recommend import recommend_food
        keys={k:'' for k in ['GOOGLE_PLACES_API_KEY','YELP_API_KEY','FOURSQUARE_API_KEY']}
        with mock.patch.dict(os.environ,keys),mock.patch.object(menu,'verify') as call:
            r=recommend_food(get_planner(),{'near':{'lon':-73.9832,'lat':40.7536},'item':'cappuccino','ratings_required':True,'categories':['cafes']})
        self.assertEqual(r['status'],'blocked_by_provider_access');call.assert_not_called()
        self.assertTrue(all(c['classification']!='meets_request' for c in r['candidates']))


class StaticSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_address[1])
    @classmethod
    def tearDownClass(cls): cls.http.shutdown();cls.http.server_close()
    def test_private_files_and_sources_not_served(self):
        for path in ['/.git/HEAD','/.git/config','/server.py','/routing/places.py','/data/places/']:
            for method in ['GET','HEAD']:
                with self.subTest(path=path,method=method),self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(self.base+path,method=method,headers={'Accept-Encoding':'gzip'}))
                self.assertEqual(caught.exception.code,404)
        with urllib.request.urlopen(self.base+'/data/places/index.json') as r:self.assertEqual(r.status,200)

if __name__=='__main__':unittest.main()
