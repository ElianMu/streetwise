"""Real shipped snapshots and real network tests; no provider/LLM responses are represented as live calls."""
import gzip,json,math,pathlib,sqlite3,sys,unittest
from datetime import date
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from routing import crime,urban_query,waterfront
from routing.urban_store import connection,manifest
from routing.engine import get_planner,DIMENSIONS,xy
import server

class IndexedUrban(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.p=get_planner()
 def test_real_crime_inventory_counts_and_coverage(self):
  m=crime.metadata()
  self.assertEqual(m['records'],sum(m['by_borough'].values()))
  self.assertTrue(all(m['by_borough'][b]>0 for b in ['MANHATTAN','BROOKLYN','QUEENS','BRONX','STATEN ISLAND']))
  with connection('crime') as db:
   self.assertEqual(db.execute('select count(*) from incidents').fetchone()[0],m['records'])
   self.assertEqual(db.execute('select count(*) from incident_rtree').fetchone()[0],m['records'])
   self.assertEqual(db.execute('select count(distinct id) from incidents').fetchone()[0],m['records'])
 def test_crime_dates_types_and_direction_are_strict(self):
  for bad in [{'direction':'safe'},{'direction':'high','from':'1800-01-01'},{'direction':'high','offense_codes':[99999]},{'direction':'low','weight':float('nan')},{'direction':'high','offense_types':[None]},{'direction':'high','offense_types':'ROBBERY'},{'direction':'high','offense_codes':{}},{'direction':'high','from':'20250101'}]:
   with self.subTest(bad=bad),self.assertRaises(ValueError):crime.validate(bad)
  p=crime.validate({'direction':'high','from':'2025-01-01','to':'2026-01-01','offense_types':['ROBBERY']})
  self.assertEqual(p['offense_codes'],[105]);self.assertEqual(p['direction'],'high')
 def test_density_normalization_does_not_clip_high_values(self):
  self.assertGreater(crime.fit(300,'high',100),crime.fit(200,'high',100))
  self.assertLess(crime.fit(300,'low',100),crime.fit(200,'low',100))
 def test_exact_corridor_count_matches_independent_straight_line_reference(self):
  p=crime.validate({'direction':'high','from':'2025-01-01','to':'2026-01-01','offense_codes':[105]})
  coords=[[-73.985,40.752],[-73.985,40.758]];a,b=map(lambda c:xy(*c),coords);length=math.dist(a,b)
  measured=crime.corridor(coords,p,length);expected=0
  with connection('crime') as db:
   for x,y in db.execute('SELECT x,y FROM incidents WHERE offense=105 AND day>=? AND day<? AND law IN (?,?) AND x BETWEEN ? AND ? AND y BETWEEN ? AND ?', [p['day_from'],p['day_to'],'FELONY','MISDEMEANOR',a[0]-100,a[0]+100,a[1]-100,b[1]+100]):
    # Analytic distance to this vertical finite segment, independent of runtime segment-index implementation.
    dy=max(a[1]-y,0,y-b[1]);expected+=math.hypot(x-a[0],dy)<=100
  self.assertEqual(measured['count'],expected);self.assertEqual(sum(measured['by_offense'].values()),expected)
 def test_opposite_crime_preferences_reorder_identical_real_candidate_pool(self):
  a={'lon':-73.999,'lat':40.733};b={'lon':-73.977,'lat':40.758};con={'max_minutes':100,'max_detour_pct':40}
  hi=self.p.plan(a,b,{'crime':{'direction':'high'}},con);lo=self.p.plan(a,b,{'crime':{'direction':'low'}},con)
  signature=lambda r:tuple(r['ordered_edge_ids'])
  self.assertEqual({signature(r) for r in hi['routes']},{signature(r) for r in lo['routes']})
  self.assertNotEqual(signature(hi['routes'][0]),signature(lo['routes'][0]))
  self.assertGreater(hi['routes'][0]['independent_metrics']['crime']['reported_incidents_per_route_km'],lo['routes'][0]['independent_metrics']['crime']['reported_incidents_per_route_km'])
  self.assertEqual(set(hi['routes'][0]['dimension_scores']),set(DIMENSIONS))
  self.assertTrue(all(r['edges'] and r['geometry']['coordinates'] and r['navigation']['state']=='planned' for r in hi['routes']))
 def test_waterfront_reversal_changes_real_path_and_water_proximity(self):
  a={'lon':-74.0089,'lat':40.7396};b={'lon':-73.9997,'lat':40.7645};con={'max_minutes':100,'max_detour_pct':40}
  high=self.p.plan(a,b,{'waterfront':{'direction':'high'}},con)['routes'][0]
  low=self.p.plan(a,b,{'waterfront':{'direction':'low'}},con)['routes'][0]
  self.assertGreater(high['independent_metrics']['waterfront']['within_100m_share'],low['independent_metrics']['waterfront']['within_100m_share'])
  self.assertNotEqual(high['ordered_edge_ids'],low['ordered_edge_ids'])
 def test_citywide_indexed_trees_have_real_points_and_aggregate_labels(self):
  for lon,lat in [(-73.985,40.755),(-73.95,40.68),(-73.87,40.75),(-73.89,40.85),(-74.15,40.57)]:
   fc=urban_query.trees([lon-.008,lat-.008,lon+.008,lat+.008],17)
   self.assertTrue(fc['features']);self.assertTrue(all(f['properties']['record_kind']=='inventory_tree' for f in fc['features']))
  fc=urban_query.trees([-74.01,40.73,-73.97,40.77],13)
  self.assertTrue(all(f['properties']['record_kind']=='aggregated_inventory_cell' for f in fc['features']))
 def test_current_construction_and_water_geometry_are_queryable(self):
  for cat in ['construction','hydrography','seating']:
   fc=urban_query.context(cat,[-74.03,40.70,-73.94,40.80]);self.assertTrue(fc['features'])
   self.assertTrue(all(f['properties'].get('source_url','').startswith('https://data.cityofnewyork.us') for f in fc['features']))
 def test_segment_inspector_uses_identical_indexed_source(self):
  with gzip.open(ROOT/'data/pedestrian/segment-evidence.json.gz','rt') as f:small=json.load(f)
  sid=next(iter(small['records']));s=server.street_segment(sid)
  self.assertEqual(s['street_name'],small['records'][sid]['name']);self.assertEqual(len(s['dimension_scores']),12)
  self.assertIsInstance(server._segments[1],server.IndexedSegments)
 def test_full_route_eviction_retains_lightweight_navigation_geometry(self):
  r=self.p.plan({'lon':-73.9832,'lat':40.7536},{'lon':-73.9787,'lat':40.7587})['routes'][0]
  with self.p.lock:self.p.routes.pop(r['route_id'],None);self.p.route_sizes.pop(r['route_id'],None)
  point=r['geometry']['coordinates'][0];result=self.p.progress(r['route_id'],point[0],point[1],10)
  self.assertLess(result['progress_m'],2)
  self.assertLessEqual(sum(self.p.route_sizes.values()),8*1024*1024);self.assertLessEqual(sum(self.p.nav_sizes.values()),4*1024*1024)
 def test_crime_map_uses_real_aggregate_counts_not_fake_incident_points(self):
  p=crime.validate({'direction':'high','offense_types':['ROBBERY']});fc=crime.map_cells([-74.01,40.74,-73.97,40.77],p,15)
  self.assertTrue(fc['features']);self.assertTrue(all(f['geometry']['type']=='Polygon' and f['properties']['count']>0 for f in fc['features']))
  self.assertLessEqual(len(fc['features']),1800)

class FoodEvidence(unittest.TestCase):
 def test_all_required_items_need_source_evidence(self):
  from routing.itinerary import validate_request,RoutingError
  origin={'lon':-73.9832,'lat':40.7536}
  with self.assertRaises(RoutingError):validate_request({'origin':origin,'slots':[{'required_items':['bagel','imaginary-dish'],'candidates':[{'id':'osm:node/14167035601','name':'Bagel Pub','lon':-73.992933,'lat':40.748135}]}]})
 def test_live_poi_failure_uses_actual_snapshot_with_explicit_provenance(self):
  from unittest import mock
  with mock.patch.object(server,'fetch_pois',side_effect=TimeoutError),mock.patch.dict(server._poi_state,{'retry_at':0,'inflight':False}):
   r=server.load_pois((40.74,-74.0,40.77,-73.97))
  self.assertEqual(r['status'],'snapshot_fallback');self.assertEqual(r['upstream_status'],'unavailable')
  self.assertTrue(r['pois']);self.assertTrue(all(p['id'].startswith('osm:node/') for p in r['pois']))

 def test_recorded_menu_evidence_expires_and_cannot_become_permanent(self):
  from unittest import mock
  from routing import menu
  from datetime import datetime
  doc=json.loads((ROOT/'data/menus/verified-items.json').read_text());record=doc['records'][0]
  checked=datetime.fromisoformat(record['checked_at']).timestamp()
  with mock.patch.object(menu.time,'time',return_value=checked+menu.TTL+1):
   self.assertIsNone(menu.cached_evidence(record['place_id'],record['item']))
 def test_recorded_official_items_can_share_one_real_waypoint(self):
  from unittest import mock
  from datetime import datetime
  from routing import menu
  from routing.itinerary import validate_request,Planner
  checked=max(datetime.fromisoformat(x['checked_at']).timestamp() for x in json.loads((ROOT/'data/menus/verified-items.json').read_text())['records'])
  # Fixed-time replay of the actual checked evidence; this test is not a live website/API claim.
  with mock.patch.object(menu.time,'time',return_value=checked+1):
   req=validate_request({'origin':{'lon':-73.9832,'lat':40.7536},'end':{'mode':'fixed','place':{'lon':-73.9787,'lat':40.7587}},'slots':[{'label':'Bagel + Cappuccino','required_items':['bagel','cappuccino'],'candidates':[{'id':'osm:node/14167035601','name':'Bagel Pub','lon':-73.992933,'lat':40.748135}]}],'constraints':{'max_minutes':100}})
   result=Planner(get_planner()).plan(req)
  stops=[s for s in result['itinerary']['stops'] if s['required']]
  self.assertEqual(len(stops),1);self.assertEqual(stops[0]['required_items'],['bagel','cappuccino'])

if __name__=='__main__':unittest.main()
