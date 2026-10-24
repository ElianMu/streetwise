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
import gzip, json, math, os, re, threading
from array import array
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_DIR = os.path.join(ROOT, 'data', 'places')
DOHMH = os.path.join(ROOT, 'data', 'inspections', 'dohmh.json.gz')
FOOD = ('restaurants', 'cafes', 'bakeries', 'bars')
ATTRACTION = ('museums', 'attractions', 'historic', 'historic_lpc', 'culture', 'parks', 'shopping')
SERVICE = ('pharmacies', 'groceries', 'health', 'banks', 'restrooms', 'luggage')
VISIT_MIN = {'museums': 45, 'attractions': 20, 'historic': 10, 'historic_lpc': 10, 'parks': 20, 'culture': 20, 'shopping': 25,
             'cafes': 15, 'bakeries': 10, 'restaurants': 45, 'bars': 30}
SOURCE_LABEL = {'nyc':'NYC Open Data','nycrr':'NYC Open Data Public Restrooms','osm': 'OpenStreetMap (ODbL)', 'lpc': 'NYC Landmarks Preservation Commission', 'nyc_restrooms': 'NYC Open Data Public Restrooms',
                'dohmh': 'NYC DOHMH Restaurant Inspection Results'}
BORO = {'Manhattan': 'Manhattan', 'Brooklyn': 'Brooklyn', 'Queens': 'Queens', 'Bronx': 'Bronx', 'Staten Island': 'Staten Island'}


def _metres(a, b):
    return math.hypot((a['lon'] - b['lon']) * 84414.3, (a['lat'] - b['lat']) * 111049.7)


def _days_since(d):
    try:
        return (date.today() - date.fromisoformat(str(d)[:10])).days
    except ValueError:
        return None


def food_access(r):
    """Permit existence alone does not establish a public, operating restaurant."""
    if r.get('access') in ('private', 'no', 'permit'):
        return {'status':'restricted', 'recommendation_eligible':False,
                'basis':'OpenStreetMap access restriction: '+r['access']}
    permit_only = r.get('src')=='dohmh' and not any(str(p).startswith('osm:') for p in r.get('pids', []))
    inspected = bool(r.get('insp')) and not str(r['insp']).startswith('1900-01-01')
    if permit_only and not inspected and not r.get('web'):
        return {'status':'unverified', 'recommendation_eligible':False,
                'basis':'Permit-only listing with no actual inspection or official public-facing website; a permit may cover a private workplace or a venue not yet operating.'}
    return {'status':'mapped_customers' if r.get('access') in ('yes','customers','permissive') else 'unverified',
            'recommendation_eligible':True,
            'basis':'Source-listed food business; public access and current opening are not independently verified.'}


_DEC = json.JSONDecoder()


def _stream(text):
    """(record, record JSON text) for each element of the file's "records" array, one at a time (no full parse)."""
    i = text.index('[', text.index(',"records":['))
    while True:
        i += 1
        while text[i] in ' \n\r\t,':
            i += 1
        if text[i] == ']':
            return
        r, end = _DEC.raw_decode(text, i)
        yield r, text[i:end]
        i = end - 1


def _decode(text, pool):
    r = json.loads(text)
    if not pool.startswith('_'):
        r['cat'] = pool
    return r


class PlaceStore:
    """Records are held as compact JSON strings with parallel coordinate arrays (about a third of the memory of dicts; the
    routing graph already uses most of the server's memory) and decoded only when they fall inside a search radius or are
    asked for by id. DOHMH permits outside Manhattan are loaded on the first search or lookup that needs them."""

    def __init__(self):
        self.index = json.load(open(os.path.join(PLACES_DIR, 'index.json')))
        self.categories = [c['id'] for c in self.index['categories']]
        self.rows, self.lat, self.lon, self.ref = {}, {}, {}, {}
        for cat in self.categories:
            with open(os.path.join(PLACES_DIR, cat + '.json'), encoding='utf-8') as f:
                self._add(cat, _stream(f.read()), lambda r: [r['id'], r.get('cid'), *(r.get('pids') or [])])
        citywide = os.path.join(PLACES_DIR, 'citywide.json')
        self.citywide_meta = None
        self.official_updates = {}
        self.inspection_updates = {}
        self._outside_lock, self.dohmh_meta = threading.Lock(), None
        if os.path.exists(citywide):
            with open(citywide, encoding='utf-8') as f:
                document = json.load(f)
            self.citywide_meta = document['metadata']
            # Same publisher, exact facility name/operator and exact coordinate identity,
            # not a nearest-name merge. Retain new operational evidence on existing IDs.
            identity = lambda r: (r['name'].casefold(),r.get('operator'),round(r['lat'],6),round(r['lon'],6))
            prior = {identity(r):r for r in self.records('restrooms') if r.get('src')=='nyc_restrooms'}
            for r in document['records']:
                old = prior.get(identity(r)) if r['cat']=='restrooms' else None
                if old:
                    r['cid'] = old.get('cid') or old['id']
                    r['pids'] = list(dict.fromkeys([*(old.get('pids') or [old['id']]),r['id']]))
                    if old.get('snap') is not None:r['search_only']=False;r['snap']=old['snap']
                    self.official_updates[old['id']] = {k:r[k] for k in ('source_status','source_url','upd','chk','pids') if k in r}
            self._add('_citywide', ((r, json.dumps(r, separators=(',', ':'))) for r in document['records']), lambda r: [r['id']])


    def _add(self, pool, items, keys):
        """items: (record, its JSON text). Only the text and coordinates are kept."""
        rows, la, lo = self.rows.setdefault(pool, []), self.lat.setdefault(pool, array('d')), self.lon.setdefault(pool, array('d'))
        for r, text in items:
            for k in keys(r):
                if k:
                    self.ref.setdefault(k, (pool, len(rows)))
            rows.append(text)
            la.append(r['lat']); lo.append(r['lon'])

    def _outside(self):
        """DOHMH food permits in Brooklyn, Queens, the Bronx and Staten Island (Manhattan permits are already in the index)."""
        if self.dohmh_meta is None and os.path.exists(DOHMH):
            with self._outside_lock:
                if self.dohmh_meta is None:
                    with gzip.open(DOHMH, 'rt', encoding='utf-8') as f:
                        text = f.read()
                    meta = _DEC.raw_decode(text, text.index('"metadata":') + 11)[0]
                    def inspection_rows():
                        for r, _ in _stream(text):
                            if r['boro']=='Manhattan' and 'dohmh:'+r['camis'] in self.ref:
                                self.inspection_updates[r['camis']] = {'grade':r['grade'],'gdate':r['grade_date'],'insp':r['last_inspection'],
                                    'closed':r['closure_date'] if r['closed_by_dohmh'] else None, 'dcuisine':r['cuisine']}
                            if not (r.get('name') and r['lat'] and r['lon'] and 40.4<r['lat']<41 and -74.3<r['lon']< -73.6 and r['boro'] in BORO and r['boro']!='Manhattan'): continue
                            yield {'id':'dohmh:'+r['camis'],'name':' '.join(w.capitalize() for w in str(r['name'] or 'Name unavailable').split()),
                                'lat':r['lat'],'lon':r['lon'],'src':'dohmh','addr':r['addr'].title(),'phone':r['phone'],'dcuisine':r['cuisine'],
                                'dohmh':r['camis'],'grade':r['grade'],'gdate':r['grade_date'],'insp':r['last_inspection'],
                                'closed':r['closure_date'] if r['closed_by_dohmh'] else None,'boro':r['boro'],
                                'cat':'cafes' if r['cuisine']=='Coffee/Tea' else 'bakeries' if r['cuisine'] in ('Bakery Products/Desserts','Donuts') else 'restaurants',
                                'search_only':True}
                    recs = inspection_rows()
                    self._add('_dohmh', ((r, json.dumps(r, separators=(',', ':'))) for r in recs), lambda r: [r['id']])
                    del text
                    self.dohmh_meta = meta
        return self.dohmh_meta

    def raw(self, pid):
        """The stored record for any canonical, index or provider id, or None."""
        if pid not in self.ref and str(pid).startswith('dohmh:'):
            self._outside()
        at = self.ref.get(pid)
        return self._updated(_decode(self.rows[at[0]][at[1]], at[0])) if at else None

    def _updated(self, r):
        if r.get('dohmh') and self.dohmh_meta is None:self._outside()
        return {**r, **self.official_updates.get(r['id'], {}), **self.inspection_updates.get(r.get('dohmh'), {})}

    def records(self, cat):
        return (self._updated(_decode(x, cat)) for x in self.rows.get(cat, []))

    # ---------------------------------------------------------------- canonical model
    def quality(self, r):
        if r.get('closed'):
            return 'closed'
        cat = r.get('cat')
        if cat in FOOD and r.get('insp') and _days_since(r['insp']) is not None and 0 <= _days_since(r['insp']) <= 365:
            return 'verified'
        if cat in ATTRACTION and (r.get('src') == 'lpc' or r.get('lpc') or (r.get('sl') and r.get('web'))):
            return 'verified'
        if cat == 'hotels' and (r.get('dof_lot') or (r.get('lpc') and r.get('web'))):
            return 'verified'
        if not (r.get('addr') or r.get('web') or r.get('hours')):
            return 'limited_data'
        return 'unverified'

    def canonical(self, r):
        cat = r.get('cat')
        sources = sorted({SOURCE_LABEL.get(p.split(':')[0], p.split(':')[0]) for p in (r.get('pids') or [r['id']])} |
                         ({'Wikidata'} if r.get('sl') or r.get('wdesc') else set()) | ({SOURCE_LABEL['dohmh']} if r.get('dohmh') else set()) |
                         ({'NYC DOF Hotels Properties Citywide'} if r.get('dof_lot') else set()) | ({SOURCE_LABEL['lpc']} if r.get('lpc') else set()) | ({r['src']} if r.get('source_url') else set()))
        base = {'place_id': r.get('cid') or r['id'], 'index_id': r['id'], 'provider_ids': {p.split(':')[0]: p.split(':', 1)[1] for p in (r.get('pids') or [r['id']])},
                'name': r['name'], 'category': cat, 'subcategory': r.get('sub'), 'address': r.get('addr'),
                'borough': r.get('boro') or (None if r.get('search_only') else 'Manhattan'), 'coordinates': {'lat': r['lat'], 'lon': r['lon']},
                'entrance_coordinates': None,   # entrances are not mapped in the sources used; the routing access point is used instead
                'access_point_distance_m': r.get('snap'), 'official_website': r.get('web'), 'website_source': r.get('web_src') or ('OpenStreetMap' if r.get('web') else None),
                'opening_hours': r.get('hours'), 'opening_hours_source': 'OpenStreetMap (as mapped, not live)' if r.get('hours') else None,
                'operational_status': 'closed_by_dohmh' if r.get('closed') else (r.get('source_status') or 'listed (not verified open today)'),
                'rating_summary': None, 'rating_note': 'Ratings come only from a configured provider (GET /api/places/<id>/ratings); none is stored.',
                'price_level': None, 'amenities': sorted(k for k, v in (r.get('amen') or {}).items() if v not in ('no', 'unknown', False, None)), 'data_sources': sources,
                'last_verified_at': r.get('insp') if r.get('dohmh') else None,
                'retrieved_at': r.get('chk') or self.index.get('built_at'), 'source_updated_at': r.get('upd') if r.get('source_url') else None, 'source_observation_at': r.get('upd'),
                'field_conflicts': r.get('field_conflicts') or [{'field': f, 'detail': 'Source values disagree; retained source value is not independently verified.'} for f in r.get('conf', [])],
                'provider_id_aliases': {p: [x.split(':', 1)[1] for x in (r.get('pids') or [r['id']]) if x.split(':')[0] == p] for p in {x.split(':')[0] for x in (r.get('pids') or [r['id']])}},
                'coordinate_basis': r.get('coordinate_basis') or 'Source point; access point is not a verified visitor entrance',
                'source_links': [r['source_url']] if r.get('source_url') else [], 'quality_status': self.quality(r),
                'routing_coverage': 'search_only' if r.get('search_only') else 'manhattan_network', 'phone': r.get('phone')}
        base['verification_scope'] = 'Identity/source corroboration only; not live opening, menu, ratings, prices or availability.'
        base['verification_basis'] = ([{'source':'NYC LPC','record_id':r['lpc'],'scope':'Historic property identity/designation; not current hotel operation'}] if r.get('lpc') else []) + ([{'source':'NYC DOF','record_id':r['dof_lot'],'scope':'Hotel-class tax lot; not rooms or availability'}] if r.get('dof_lot') else [])
        if cat in FOOD:
            base['public_access'] = food_access(r)
            if str(base['last_verified_at'] or '').startswith('1900-01-01'):
                base['last_verified_at'] = None
        source_ids = r.get('pids') or [r['id']]
        base['field_provenance'] = {label: {'source_ids': [r['field_sources'][raw]] if r.get('field_sources',{}).get(raw) else source_ids,
            'resolution': 'field_source' if r.get('field_sources',{}).get(raw) else 'merged_source_set',
            'source_updated_at': r.get('upd') if r.get('source_url') else None, 'source_observation_at': r.get('upd'), 'retrieved_at': base['retrieved_at'], 'conflict': raw in (r.get('conf') or []),
            'verification': 'copied source evidence, not independently reverified'}
            for label,raw in [('name','name'),('address','addr'),('official_website','web'),('opening_hours','hours'),('coordinates','lat')] if r.get(raw) is not None}
        if cat in FOOD:
            base['restaurant'] = {'cuisine': r.get('cuisine'), 'cuisine_dohmh': r.get('dcuisine'),
                                  'inspection': {'permit': r.get('dohmh'), 'grade': r.get('grade'), 'grade_date': r.get('gdate'), 'last_inspection': None if str(r.get('insp') or '').startswith('1900-01-01') else r.get('insp'),
                                                 'closed_since': r.get('closed'), 'source': 'NYC DOHMH' if r.get('dohmh') else None,
                                                 'publisher_updated_at':(self.dohmh_meta or {}).get('publisher_updated_at'),
                                                 'retrieved_at':(self.dohmh_meta or {}).get('retrieved_at'),
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
        r = self.raw(pid)
        return self.canonical(r) if r else None

    # ---------------------------------------------------------------- search
    def search(self, near, categories, radius_m=1200, limit=20, query=None, cuisine=None, include_closed=False):
        """Places of the given categories within radius_m of near (straight-line pre-selection; walking distance is the
        router's job). Manhattan comes from the discovery index; food elsewhere in NYC from DOHMH (search only)."""
        q = re.sub(r'[^a-z0-9 ]', '', (query or '').lower()).strip()
        out, seen = [], set()
        pools = [c for c in categories if c in self.rows]
        if '_citywide' in self.rows:
            pools.append('_citywide')
        if set(categories) & set(FOOD) and self._outside():
            pools.append('_dohmh')
        dlat, dlon = radius_m / 111049.7, radius_m / 84414.3
        for pool in pools:
            la, lo, rows = self.lat[pool], self.lon[pool], self.rows[pool]
            for i in range(len(rows)):
                if abs(la[i] - near['lat']) > dlat or abs(lo[i] - near['lon']) > dlon:
                    continue
                r = self._updated(_decode(rows[i], pool))
                key = r.get('cid') or r['id']
                if key in seen or r['cat'] not in categories or (r.get('closed') and not include_closed):
                    continue
                if r['cat'] in FOOD and not food_access(r)['recommendation_eligible']:
                    continue
                if r.get('source_url','').endswith('/enfh-gkve') and r.get('sub') in ('Undeveloped','Operations','Lot','Parkway','Strip','Buildings/Institutions','Managed Sites','Cemetery'): continue
                if not include_closed and str(r.get('source_status') or '').lower() in ('not operational','closed','inactive'): continue
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


_STORE_LOCK = threading.Lock()


def store():
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = PlaceStore()
    return _STORE
