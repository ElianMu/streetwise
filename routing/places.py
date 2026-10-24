"""Canonical NYC place store for the agent tools (GET /api/places/search, GET /api/places/<id>, ratings, hotel rooms).

Sources: data/places (Manhattan discovery index: OpenStreetMap, NYC LPC, NYC restrooms, DOHMH permits, Wikidata) and
data/inspections/dohmh.json.gz (DOHMH food permits in all five boroughs). Every field is copied from a source or left None;
`data_sources` lists where each place's facts come from.

quality_status is set by rules on evidence, never for looks:
  closed            DOHMH's latest action is a closure with no later re-opening
  verified          an authority confirms the place: DOHMH inspection within 365 days (food), NYC LPC designation or a Wikidata-
                    notable place with an official website (attractions), a NYC DOF hotel-class tax lot (hotels)
  limited_data      no address, website or hours in any source
  unverified        listed by a source, nothing more confirmed
routing_coverage: 'manhattan_network' when the place snaps to the pedestrian graph, otherwise 'search_only'.
"""
import gzip, json, math, os, re
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_DIR = os.path.join(ROOT, 'data', 'places')
DOHMH = os.path.join(ROOT, 'data', 'inspections', 'dohmh.json.gz')
FOOD = ('restaurants', 'cafes', 'bakeries', 'bars')
ATTRACTION = ('museums', 'attractions', 'historic', 'historic_lpc', 'culture', 'parks', 'shopping')
SERVICE = ('pharmacies', 'groceries', 'health', 'banks', 'restrooms', 'luggage')
VISIT_MIN = {'museums': 45, 'attractions': 20, 'historic': 10, 'historic_lpc': 10, 'parks': 20, 'culture': 20, 'shopping': 25,
             'cafes': 15, 'bakeries': 10, 'restaurants': 45, 'bars': 30}
SOURCE_LABEL = {'osm': 'OpenStreetMap (ODbL)', 'lpc': 'NYC Landmarks Preservation Commission', 'nyc_restrooms': 'NYC Open Data Public Restrooms',
                'dohmh': 'NYC DOHMH Restaurant Inspection Results'}
BORO = {'Manhattan': 'Manhattan', 'Brooklyn': 'Brooklyn', 'Queens': 'Queens', 'Bronx': 'Bronx', 'Staten Island': 'Staten Island'}


def _metres(a, b):
    return math.hypot((a['lon'] - b['lon']) * 84414.3, (a['lat'] - b['lat']) * 111049.7)


def _days_since(d):
    try:
        return (date.today() - date.fromisoformat(str(d)[:10])).days
    except ValueError:
        return None


class PlaceStore:
    def __init__(self):
        self.index = json.load(open(os.path.join(PLACES_DIR, 'index.json')))
        self.by_id, self.by_cat = {}, {}
        for c in self.index['categories']:
            recs = json.load(open(os.path.join(PLACES_DIR, c['id'] + '.json')))['records']
            for r in recs:
                r['cat'] = c['id']
                self.by_id[r['id']] = r
                self.by_id.setdefault(r.get('cid'), r)
            self.by_cat[c['id']] = recs
        self.nyc_food = []
        if os.path.exists(DOHMH):
            d = json.load(gzip.open(DOHMH, 'rt'))
            self.dohmh_meta = d['metadata']
            for r in d['records']:
                if r['lat'] and r['boro'] in BORO:
                    self.nyc_food.append(r)
                    self.by_id.setdefault('dohmh:' + r['camis'], {'id': 'dohmh:' + r['camis'], 'name': ' '.join(w.capitalize() for w in r['name'].split()), 'lat': r['lat'],
                                                                  'lon': r['lon'], 'src': 'dohmh', 'addr': r['addr'].title(), 'phone': r['phone'], 'dcuisine': r['cuisine'],
                                                                  'dohmh': r['camis'], 'grade': r['grade'], 'gdate': r['grade_date'], 'insp': r['last_inspection'],
                                                                  'closed': r['closure_date'] if r['closed_by_dohmh'] else None, 'boro': r['boro'],
                                                                  'cat': 'cafes' if r['cuisine'] == 'Coffee/Tea' else 'bakeries' if r['cuisine'] in ('Bakery Products/Desserts', 'Donuts') else 'restaurants',
                                                                  'search_only': r['boro'] != 'Manhattan'})
        else:
            self.dohmh_meta = None

    # ---------------------------------------------------------------- canonical model
    def quality(self, r):
        if r.get('closed'):
            return 'closed'
        cat = r.get('cat')
        if cat in FOOD and r.get('insp') and (_days_since(r['insp']) or 9999) <= 365:
            return 'verified'
        if cat in ATTRACTION and (r.get('src') == 'lpc' or r.get('lpc') or (r.get('sl') and r.get('web'))):
            return 'verified'
        if cat == 'hotels' and r.get('dof_lot'):
            return 'verified'
        if not (r.get('addr') or r.get('web') or r.get('hours')):
            return 'limited_data'
        return 'unverified'

    def canonical(self, r):
        cat = r.get('cat')
        sources = sorted({SOURCE_LABEL.get(p.split(':')[0], p.split(':')[0]) for p in (r.get('pids') or [r['id']])} |
                         ({'Wikidata'} if r.get('sl') or r.get('wdesc') else set()) | ({SOURCE_LABEL['dohmh']} if r.get('dohmh') else set()) |
                         ({'NYC DOF Hotels Properties Citywide'} if r.get('dof_lot') else set()) | ({SOURCE_LABEL['lpc']} if r.get('lpc') else set()))
        base = {'place_id': r.get('cid') or r['id'], 'index_id': r['id'], 'provider_ids': {p.split(':')[0]: p.split(':', 1)[1] for p in (r.get('pids') or [r['id']])},
                'name': r['name'], 'category': cat, 'subcategory': r.get('sub'), 'address': r.get('addr'),
                'borough': r.get('boro') or 'Manhattan', 'coordinates': {'lat': r['lat'], 'lon': r['lon']},
                'entrance_coordinates': None,   # entrances are not mapped in the sources used; the routing access point is used instead
                'access_point_distance_m': r.get('snap'), 'official_website': r.get('web'), 'website_source': r.get('web_src') or ('OpenStreetMap' if r.get('web') else None),
                'opening_hours': r.get('hours'), 'opening_hours_source': 'OpenStreetMap (as mapped, not live)' if r.get('hours') else None,
                'operational_status': 'closed_by_dohmh' if r.get('closed') else 'listed (not verified open today)',
                'rating_summary': None, 'rating_note': 'Ratings come only from a configured provider (GET /api/places/<id>/ratings); none is stored.',
                'price_level': None, 'amenities': sorted((r.get('amen') or {}).keys()), 'data_sources': sources,
                'last_verified_at': r.get('insp') if r.get('dohmh') else r.get('chk'), 'quality_status': self.quality(r),
                'routing_coverage': 'search_only' if r.get('search_only') else 'manhattan_network', 'phone': r.get('phone')}
        if cat in FOOD:
            base['restaurant'] = {'cuisine': r.get('cuisine'), 'cuisine_dohmh': r.get('dcuisine'),
                                  'inspection': {'permit': r.get('dohmh'), 'grade': r.get('grade'), 'grade_date': r.get('gdate'), 'last_inspection': r.get('insp'),
                                                 'closed_since': r.get('closed'), 'source': 'NYC DOHMH' if r.get('dohmh') else None,
                                                 'meaning': 'Health inspection grade, not a review or a quality rating.'} if r.get('dohmh') else None,
                                  'menu_url': r.get('menu'), 'menu_items': None, 'menu_note': 'Item evidence is checked per request (POST /api/menu/verify).',
                                  'drink_tags_osm': r.get('drink'), 'dietary_osm': r.get('diet'), 'reservation_url': None,
                                  'services_osm': {k: v for k, v in (r.get('amen') or {}).items() if k in ('outdoor_seating', 'takeaway', 'delivery')} or None}
        elif cat == 'hotels':
            amen = r.get('amen') or {}
            base['hotel'] = {'star_rating': r.get('stars'), 'star_rating_source': 'OpenStreetMap stars tag' if r.get('stars') else None,
                             'guest_rating': None, 'guest_rating_note': 'Guest ratings come only from a configured provider; never mixed with stars.',
                             'rooms_count_osm': amen.get('rooms'), 'check_in': amen.get('check_in'), 'check_out': amen.get('check_out'),
                             'internet_access': amen.get('internet_access'), 'wheelchair': r.get('wheelchair'),
                             'dof_hotel_lot': {'bbl': r.get('dof_lot'), 'building_class': r.get('dof_class'), 'tax_year': r.get('dof_year')} if r.get('dof_lot') else None,
                             'room_types': None, 'prices': None, 'availability': None,
                             'rooms_note': 'Room types, prices and availability need a lodging partner API with dates and guests (GET /api/hotels/<id>/rooms).'}
        elif cat in ATTRACTION:
            base['attraction'] = {'description': r.get('wdesc') or r.get('desc'), 'description_source': 'Wikidata' if r.get('wdesc') else 'OpenStreetMap' if r.get('desc') else None,
                                  'notability_wikipedia_editions': r.get('sl'), 'admission': r.get('charge') or ({'yes': 'fee charged (amount not mapped)', 'no': 'free'}.get(r.get('fee'))),
                                  'admission_source': 'OpenStreetMap fee/charge tags' if r.get('fee') or r.get('charge') else None,
                                  'reservation': r.get('reservation'), 'designated_landmark': bool(r.get('src') == 'lpc' or r.get('lpc')),
                                  'lpc': {'designated': r.get('designated'), 'style': r.get('style'), 'architect': r.get('architect'), 'built': r.get('built'), 'report': r.get('report')} if r.get('src') == 'lpc' else None,
                                  'recommended_visit_min': VISIT_MIN.get(cat), 'visit_duration_basis': 'STREETWISE estimate by category (editable), not from the venue',
                                  'current_exhibitions': None, 'accessibility': r.get('wheelchair')}
        elif cat in SERVICE:
            base['service'] = {'kind': cat, 'operator': r.get('operator'), 'status_published': r.get('status'), 'access': r.get('access')}
        return base

    def get(self, pid):
        r = self.by_id.get(pid)
        return self.canonical(r) if r else None

    # ---------------------------------------------------------------- search
    def search(self, near, categories, radius_m=1200, limit=20, query=None, cuisine=None, include_closed=False):
        """Places of the given categories within radius_m of near (straight-line pre-selection; walking distance is the
        router's job). Manhattan comes from the discovery index; food elsewhere in NYC from DOHMH (search only)."""
        q = re.sub(r'[^a-z0-9 ]', '', (query or '').lower()).strip()
        out, seen = [], set()
        pools = [self.by_cat.get(c, []) for c in categories]
        if set(categories) & set(FOOD) and not self._in_manhattan(near):
            pools.append([r for r in (self.by_id.get('dohmh:' + x['camis']) for x in self.nyc_food) if r and r['cat'] in categories])
        for pool in pools:
            for r in pool:
                key = r.get('cid') or r['id']
                if key in seen or (r.get('closed') and not include_closed):
                    continue
                if q and q not in r['name'].lower():
                    continue
                if cuisine and cuisine.lower() not in f"{r.get('cuisine') or ''};{(r.get('dcuisine') or '').lower()}":
                    continue
                d = _metres(r, near)
                if d <= radius_m:
                    seen.add(key)
                    out.append((d, r))
        out.sort(key=lambda x: x[0])
        return [{**self.canonical(r), 'straight_line_m': round(d)} for d, r in out[:limit]]

    @staticmethod
    def _in_manhattan(p):
        return -74.03 <= p['lon'] <= -73.905 and 40.698 <= p['lat'] <= 40.882


_STORE = None


def store():
    global _STORE
    if _STORE is None:
        _STORE = PlaceStore()
    return _STORE
