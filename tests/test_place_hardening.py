"""Real source integrity plus explicitly mocked menu transport failure/cache tests."""
import gzip
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
import zlib
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_place_index as build
from routing import hours, menu
from routing.places import store, food_access
from routing.itinerary import validate_request
from routing.engine import RoutingError


class PlaceHardening(unittest.TestCase):
    def test_real_uninspected_permit_is_not_a_public_restaurant_recommendation(self):
        s=store();p=s.get('dohmh:50181591')
        self.assertIn('Pinterest',p['name'])
        self.assertFalse(p['public_access']['recommendation_eligible'])
        self.assertIsNone(p['last_verified_at'])
        self.assertIsNone(p['restaurant']['inspection']['last_inspection'])
        found=s.search(p['coordinates'],['restaurants'],radius_m=100,limit=100)
        self.assertNotIn(p['place_id'],[r['place_id'] for r in found])
        with self.assertRaisesRegex(RoutingError,'public access'):
            validate_request({'origin':{'lat':40.741,'lon':-73.987},'end':{'mode':'round'},
                              'stops':[{'id':p['index_id'],'name':p['name'],**p['coordinates']}]})
        self.assertFalse(food_access({'src':'osm','access':'private'})['recommendation_eligible'])

    def test_real_algonquin_uses_existing_lpc_identity_without_invented_rooms(self):
        p=store().get('osm:way/266170533')
        self.assertEqual(p['quality_status'],'verified')
        self.assertTrue(any(r['source']=='NYC LPC' and r['record_id']=='lpc:LP-01547' for r in p['verification_basis']))
        self.assertIsNone(p['hotel']['room_types']);self.assertIsNone(p['hotel']['availability'])

    def test_every_repaired_osm_permit_link_matches_real_source_address_and_name(self):
        with gzip.open(ROOT/'data/inspections/dohmh.json.gz','rt') as f:permits={r['camis']:r for r in json.load(f)['records']}
        count=0
        for cat in ('restaurants','cafes','bakeries','bars'):
            for r in store().records(cat):
                if r.get('src')=='osm' and r.get('dohmh'):
                    self.assertTrue(build.permit_matches(r,permits[r['dohmh']]),r['id'])
                    count+=1
        self.assertGreater(count,3000)

    def test_matching_does_not_move_a_grade_between_nearby_branches(self):
        a={'name':'Test Cafe','addr':'100 West 44th Street','lat':40.75,'lon':-73.98}
        self.assertTrue(build.permit_matches(a,{**a,'addr':'100 WEST 44 STREET'}))
        self.assertFalse(build.permit_matches(a,{**a,'addr':'101 WEST 44 STREET'}))
        self.assertFalse(build.permit_matches(a,{**a,'name':'Different Cafe'}))

    def test_holiday_and_invalid_clock_rules_are_unknown_not_open(self):
        when=datetime.fromisoformat('2026-12-25T12:00:00-05:00')
        for rule in ['Mo-Su 09:00-18:00; PH off','09:00-25:30','09:65-18:00','24:00-04:00']:
            with self.subTest(rule=rule):self.assertIsNone(hours.is_open_at(rule,when))
        self.assertTrue(hours.is_open_at('00:00-24:00',when))

    def test_shared_official_document_is_read_once_with_actual_read_timestamp(self):
        html=b'<title>Menu</title><main>Cappuccino $5. Plain bagel $3. Coffee.</main>'
        url='https://multi-item-fixture.invalid/menu'
        with mock.patch.object(menu,'place_sites',return_value={'test:document':(url,url)}),mock.patch.object(menu,'_allowed',return_value=True),mock.patch.object(menu,'safe_get',return_value=(url,'text/html',html,{})) as read:
            first=menu.verify({'place_id':'test:document','item':'cappuccino'})
            second=menu.verify({'place_id':'test:document','item':'bagel'})
        self.assertEqual(first['status'],'confirmed_menu_match')
        self.assertEqual(second['status'],'confirmed_menu_match')
        self.assertEqual(read.call_count,1)
        self.assertEqual(first['checked_at'],second['checked_at'])
        self.assertLessEqual(menu.DOCUMENT_BYTES,menu.DOCUMENT_LIMIT)

    def test_deadline_prevents_starting_another_website_check(self):
        url='https://deadline-fixture.invalid/menu'
        with mock.patch.object(menu,'place_sites',return_value={'test:deadline':(url,url)}),mock.patch.object(menu,'_allowed') as allowed:
            r=menu.verify({'place_id':'test:deadline','item':'unique-dish'},deadline=time.monotonic()-1)
        allowed.assert_not_called();self.assertEqual(r['status'],'unverified')
        self.assertIn('time limit',r['reason'])

    def test_oversized_compressed_pdf_is_not_expanded_as_evidence(self):
        compressed=zlib.compress(b'(Cappuccino) Tj\n' * 700000)
        self.assertEqual(menu.pdf_text(b'stream\n'+compressed+b'\nendstream'),'')
