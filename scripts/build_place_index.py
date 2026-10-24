"""Discovery POI index for AI Discover My Walk: real named places inside the pedestrian routing coverage.

One Overpass snapshot of OpenStreetMap (ODbL) plus NYC LPC individual landmarks (from the urban data tiles),
split by discovery category into data/places/<category>.json, with data/places/index.json as the catalog.
Only places within 150 m of the routable pedestrian graph are kept, so every candidate can be reached by the
routing engine (today: Manhattan). Nothing is invented: every field is copied from its source or left out.
Run: python3 scripts/build_place_index.py   (about 1 minute; needs network access to the Overpass API)
"""
import hashlib, json, math, os, re, sys, time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streetwise_indicators as si  # noqa: E402
from routing.engine import PedestrianNetwork, RoutingError  # noqa: E402

ROOT = si.ROOT
OUT = os.path.join(ROOT, 'data', 'places')
LANDMARK_TILES = os.path.join(ROOT, 'data', 'layers', 'tiles', 'landmarks')
RESTROOM_TILES = os.path.join(ROOT, 'data', 'layers', 'tiles', 'public_restrooms')
# Service places are often unnamed in OSM; they get their type as a label (never an invented name).
UNNAMED_LABEL = {'restrooms': 'Public restroom', 'banks': 'ATM', 'luggage': 'Luggage storage'}
KEEP = ('name', 'tourism', 'historic', 'amenity', 'shop', 'leisure', 'cuisine', 'opening_hours', 'website', 'website:menu', 'wikidata',
        'wikipedia', 'brand', 'operator', 'stars', 'wheelchair', 'addr:housenumber', 'addr:street', 'phone', 'fee', 'toilets:wheelchair',
        'charge', 'reservation', 'description', 'rooms', 'beds', 'internet_access', 'air_conditioning', 'check_in', 'check_out', 'contact:phone',
        'contact:website', 'diet:vegetarian', 'diet:vegan', 'outdoor_seating', 'takeaway', 'delivery', 'reservation', 'payment:cash')

# Discovery categories: (id, label, matcher on OSM tags). A place belongs to the first category that matches.
CATEGORIES = [
    ('hotels', 'Hotels & accommodation', lambda t: t.get('tourism') in ('hotel', 'hostel', 'guest_house', 'motel', 'apartment')),
    ('museums', 'Museums & galleries', lambda t: t.get('tourism') in ('museum', 'gallery') or t.get('amenity') == 'arts_centre'),
    ('attractions', 'Famous attractions & viewpoints', lambda t: t.get('tourism') in ('attraction', 'viewpoint', 'zoo', 'aquarium', 'theme_park')
        or (t.get('tourism') == 'artwork' and 'wikidata' in t)),
    ('historic', 'Historic places', lambda t: 'historic' in t and 'name' in t),
    ('parks', 'Parks & gardens', lambda t: t.get('leisure') in ('park', 'garden', 'nature_reserve') and 'name' in t),
    ('cafes', 'Cafés & coffee', lambda t: t.get('amenity') == 'cafe' or t.get('shop') == 'coffee'),
    ('bakeries', 'Bakeries & desserts', lambda t: t.get('shop') in ('bakery', 'pastry', 'confectionery') or t.get('amenity') == 'ice_cream'),
    ('restaurants', 'Restaurants', lambda t: t.get('amenity') in ('restaurant', 'fast_food')),
    ('bars', 'Bars & pubs', lambda t: t.get('amenity') in ('bar', 'pub')),
    ('culture', 'Theatres, libraries & landmarks of worship', lambda t: t.get('amenity') in ('theatre', 'library') or (t.get('amenity') == 'place_of_worship' and 'wikidata' in t)),
    ('shopping', 'Shopping', lambda t: t.get('shop') in ('mall', 'department_store', 'books', 'gift')),
    ('pharmacies', 'Pharmacies', lambda t: t.get('amenity') == 'pharmacy' or t.get('shop') == 'chemist'),
    ('groceries', 'Groceries & convenience', lambda t: t.get('shop') in ('supermarket', 'convenience', 'deli') or t.get('amenity') == 'marketplace'),
    ('health', 'Hospitals & clinics', lambda t: t.get('amenity') in ('hospital', 'clinic')),
    ('banks', 'Banks & ATMs', lambda t: t.get('amenity') in ('bank', 'atm')),
    ('restrooms', 'Public restrooms', lambda t: t.get('amenity') == 'toilets'),
    ('luggage', 'Luggage storage', lambda t: t.get('amenity') == 'luggage_locker' or t.get('shop') == 'luggage_storage'),
]


def overpass_pois():
    s, w, n, e = si.BOX[1], si.BOX[0], si.BOX[3], si.BOX[2]
    b = f'{s},{w},{n},{e}'
    q = (f'[out:json][timeout:180];(nwr["tourism"]["name"]({b});nwr["historic"]["name"]({b});'
         f'nwr["amenity"~"^(cafe|restaurant|fast_food|bar|pub|ice_cream|pharmacy|hospital|clinic|bank|atm|toilets|marketplace|arts_centre|theatre|library|place_of_worship|luggage_locker)$"]({b});'
         f'nwr["shop"~"^(bakery|pastry|confectionery|supermarket|convenience|mall|department_store|chemist|deli|coffee|books|gift|luggage_storage)$"]({b});'
         f'nwr["leisure"~"^(park|garden|nature_reserve)$"]["name"]({b}););out tags center;')
    return si.get(si.SOURCES['osm'], data=si.parse.urlencode({'data': q}).encode(), timeout=240)


def subtype(t):
    for k in ('tourism', 'historic', 'amenity', 'shop', 'leisure'):
        if k in t:
            return f'{k}={t[k]}'
    return None


def landmark_records():
    """NYC LPC individual landmarks (lot polygons in the urban data tiles) → name + centroid."""
    out, seen = [], set()
    for fn in sorted(os.listdir(LANDMARK_TILES)):
        for f in json.load(open(os.path.join(LANDMARK_TILES, fn)))['features']:
            p = f['properties']
            if p['feature_id'] in seen or not p.get('LPC_NAME') or p.get('BuildType') in ('Lamppost', 'Clock', 'Sidewalk Clock'):
                continue
            seen.add(p['feature_id'])
            ring = f['geometry']['coordinates'][0] if f['geometry']['type'] == 'Polygon' else f['geometry']['coordinates'][0][0]
            lon, lat = sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)
            rec = {'id': 'lpc:' + p['feature_id'], 'name': p['LPC_NAME'], 'lat': round(lat, 6), 'lon': round(lon, 6), 'addr': p.get('Address'),
                   'sub': 'lpc=individual_landmark', 'src': 'lpc', 'designated': p.get('DesDate'), 'style': p.get('Style_Prim'),
                   'architect': p.get('Arch_Prima'), 'built': p.get('Date_Low'), 'report': p.get('URL_REPORT'), 'type': p.get('BuildType')}
            out.append({k: v for k, v in rec.items() if v not in (None, '', 0)})
    return out


def restroom_records():
    """NYC Open Data public restrooms (operator, status and hours as published)."""
    out = []
    for fn in sorted(os.listdir(RESTROOM_TILES)):
        for f in json.load(open(os.path.join(RESTROOM_TILES, fn)))['features']:
            p = f['properties']
            lon, lat = f['geometry']['coordinates']
            rec = {'id': 'nycrr:' + p['feature_id'], 'name': p.get('facility_name') or 'Public restroom', 'lat': round(lat, 6), 'lon': round(lon, 6),
                   'sub': 'nyc=public_restroom', 'src': 'nyc_restrooms', 'hours': p.get('hours_of_operation'), 'status': p.get('status'),
                   'operator': p.get('operator'), 'access': p.get('accessibility'), 'web': p.get('website')}
            out.append({k: v for k, v in rec.items() if v not in (None, '')})
    return out


def wikidata_sitelinks(ids):
    """{QID: (sitelink count, English label)}: sitelinks are a public, checkable notability signal. Polite pacing,
    retries on HTTP 429."""
    out, ids = {}, sorted(set(ids))
    for k in range(0, len(ids), 50):
        q = si.parse.urlencode({'action': 'wbgetentities', 'ids': '|'.join(ids[k:k + 50]), 'props': 'sitelinks|labels|descriptions|claims', 'languages': 'en', 'format': 'json'})
        for attempt in range(4):
            try:
                d = si.get('https://www.wikidata.org/w/api.php?' + q, timeout=60, tries=1)
                break
            except RuntimeError as e:
                d = None
                time.sleep(5 * (attempt + 1))
        if not d:
            raise RuntimeError('Wikidata enrichment failed; preserving the existing place snapshot')
        for qid, ent in d.get('entities', {}).items():
            if 'sitelinks' in ent:
                site = next((c['mainsnak'].get('datavalue', {}).get('value') for c in ent.get('claims', {}).get('P856', []) if c.get('mainsnak', {}).get('datavalue')), None)
                out[qid] = (len(ent['sitelinks']), ent.get('labels', {}).get('en', {}).get('value', ''), ent.get('descriptions', {}).get('en', {}).get('value'), site)
        time.sleep(1)
    return out


def _same_thing(name, label):
    """OSM objects sometimes carry the Wikidata ID of their subject (a plaque about Broadway); count notability only
    when the place's own name and the Wikidata label share their main words."""
    norm = lambda x: set(w for w in __import__('re').sub(r'[^a-z0-9 ]', ' ', x.lower()).split() if w not in ('the', 'of', 'and', 'new', 'york', 'nyc', 'at'))
    a, b = norm(name), norm(label)
    initials = ''.join(w[0] for w in __import__('re').sub(r'[^a-z ]', ' ', label.lower()).split() if w not in ('of', 'the', 'and'))
    if name.replace(' ', '').lower() in (initials, initials[:len(name.replace(' ', ''))]) and len(name) >= 3:
        return True  # MoMA = Museum of Modern Art
    return bool(a and b) and len(a & b) >= max(1, min(len(a), len(b)) // 2)


WORD = re.compile(r'[a-z0-9]+')
STOP = {'the', 'of', 'and', 'new', 'york', 'nyc', 'at', 'building', 'house', 'church', 'hall'}


def _norm(name):
    return ' '.join(WORD.findall(str(name).lower().replace('&', ' and ')))


def _addr(a):
    a = _norm(a or '')
    for k, v in (('street', 'st'), ('avenue', 'av'), ('ave', 'av'), ('west', 'w'), ('east', 'e'), ('place', 'pl')):
        a = re.sub(rf'\b{k}\b', v, a)
    return a or None


def _metres(a, b):
    return math.hypot((a['lon'] - b['lon']) * 84414.3, (a['lat'] - b['lat']) * 111049.7)


INSPECTIONS = os.path.join(ROOT, 'data', 'inspections', 'dohmh.json.gz')
DOHMH_CATEGORY = [(('Coffee/Tea', 'Juice, Smoothies, Fruit Salads'), 'cafes'),
                  (('Bakery Products/Desserts', 'Donuts', 'Frozen Desserts', 'Bagels/Pretzels'), 'bakeries')]
DOHMH_CUISINE = {'Coffee/Tea': 'coffee_shop', 'Bakery Products/Desserts': 'bakery', 'Bagels/Pretzels': 'bagel', 'Frozen Desserts': 'ice_cream',
                 'Juice, Smoothies, Fruit Salads': 'juice', 'Pizza': 'pizza', 'Hamburgers': 'burger', 'Sandwiches': 'sandwich'}


def _title(s):
    return ' '.join(w.capitalize() if w.isupper() or w.islower() else w for w in str(s or '').split()) or None


def link_hotel_lots(groups):
    """Corroborate mapped hotels with NYC Department of Finance hotel-class tax lots (Hotels Properties Citywide, tjus-cn27):
    a lot in building class H* within 35 m. The lot proves a hotel property, not the hotel's name, rating or availability."""
    try:
        rows = si.get('https://data.cityofnewyork.us/resource/tjus-cn27.json?' + si.parse.urlencode(
            {'$select': 'bbl,parid,taxyear,bldg_class,latitude,longitude', '$where': "borough in('MANHATTAN','1') and latitude is not null", '$limit': 50000}), timeout=120)
    except RuntimeError as e:
        raise RuntimeError('Hotel-property source unavailable; preserving existing verified source evidence') from e
    lots = {}
    for r in rows:
        key = r.get('bbl') or r.get('parid')
        if not key or not r.get('latitude'):
            continue
        r['bbl'] = key
        if key not in lots or r.get('taxyear', '') > lots[key].get('taxyear', ''):
            lots[key] = r
    pts = [{'lat': float(r['latitude']), 'lon': float(r['longitude']), **r} for r in lots.values()]
    n = 0
    for h in groups['hotels']:
        best = min(pts, key=lambda p: _metres(p, h), default=None)
        if best and _metres(best, h) < 35:
            h['dof_lot'] = best['bbl']; h['dof_class'] = best['bldg_class']; h['dof_year'] = best['taxyear']; n += 1
    return {'available': True, 'lots': len(pts), 'hotels_matched': n}


def link_inspections(groups, routable):
    """Attach DOHMH permits to OpenStreetMap food places (same name words AND within 60 m), and add the routable permits
    that OSM does not map as their own records. Returns link counts."""
    if not os.path.exists(INSPECTIONS):
        return {'available': False}
    import gzip
    recs = [r for r in json.load(gzip.open(INSPECTIONS, 'rt'))['records'] if r['boro'] == 'Manhattan' and r['lat']]
    food = [r for c in ('restaurants', 'cafes', 'bakeries', 'bars') for r in groups[c]]
    grid = {}
    for r in food:
        grid.setdefault((int(r['lat'] * 1500), int(r['lon'] * 1150)), []).append(r)
    linked, added, closed = 0, 0, 0
    for d in recs:
        dw = set(_norm(d['name']).split()) - {'the', 'and', 'of', 'nyc', 'new', 'york', 'cafe', 'restaurant', 'inc', 'llc'}
        best = None
        gy, gx = int(d['lat'] * 1500), int(d['lon'] * 1150)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for r in grid.get((gy + dy, gx + dx), ()):
                    if r.get('dohmh'):
                        continue
                    rw = set(_norm(r['name']).split()) - {'the', 'and', 'of', 'nyc', 'new', 'york', 'cafe', 'restaurant'}
                    m = _metres(r, d)
                    if dw and rw and len(dw & rw) >= max(1, min(len(dw), len(rw)) / 2) and m < 60 and (best is None or m < _metres(best, d)):
                        best = r
        insp = {'dohmh': d['camis'], 'grade': d['grade'], 'gdate': d['grade_date'], 'insp': d['last_inspection'], 'dcuisine': d['cuisine']}
        if d['closed_by_dohmh']:
            insp['closed'] = d['closure_date']
            closed += 1
        if best:
            best.update({k: v for k, v in insp.items() if v is not None})
            best.setdefault('phone', d['phone'])
            linked += 1
            continue
        snap = routable(d['lon'], d['lat'])
        if snap is None:
            continue
        cat = next((c for keys, c in DOHMH_CATEGORY if d['cuisine'] in keys), 'restaurants')
        rec = {'id': 'dohmh:' + d['camis'], 'name': _title(d['name']), 'name_registered': d['name'], 'lat': d['lat'], 'lon': d['lon'], 'src': 'dohmh',
               'sub': 'dohmh=' + (d['cuisine'] or 'food_service'), 'addr': _title(d['addr']), 'phone': d['phone'],
               'cuisine': DOHMH_CUISINE.get(d['cuisine'], (d['cuisine'] or '').lower().replace(' ', '_').replace('/', '_') or None), 'snap': round(snap, 1),
               **{k: v for k, v in insp.items() if v is not None}}
        groups[cat].append({k: v for k, v in rec.items() if v not in (None, '')})
        added += 1
    return {'available': True, 'manhattan_permits': len(recs), 'linked_to_osm': linked, 'added_from_dohmh': added, 'closed_by_dohmh': closed}


def resolve_entities(groups, osm_stamp, built):
    """Entity resolution. Two records are the same place only when their names match AND their addresses match AND they lie
    within 60 m (or share an identical provider identity); a different name in the same building stays a separate place. NYC LPC landmarks are linked (not merged) to
    the OpenStreetMap record of the same building when the main name words overlap and they lie within 120 m.
    Adds the canonical fields to every record and returns per-category quality counts."""
    previous_ids, previous_leads, claimed = {}, {}, set()
    if os.path.exists(os.path.join(OUT, 'index.json')):
        previous = json.load(open(os.path.join(OUT, 'index.json')))
        for category in previous.get('categories', []):
            path = os.path.join(OUT, category['id'] + '.json')
            if not os.path.exists(path): continue
            for old in json.load(open(path)).get('records', []):
                if old.get('cid'):
                    for pid in old.get('pids') or [old['id']]:
                        previous_ids[pid] = old['cid']; previous_leads[pid] = old['id']
    quality = {}
    for cat, recs in groups.items():
        by_name, out, dups, conflicts = {}, [], 0, 0
        for r in recs:
            # same name AND same kind (a bank branch and its ATM are different services)
            by_name.setdefault(_norm(r['name']) + '|' + str(r.get('sub')) + ('#' + r['id'] if r.get('unnamed') else ''), []).append(r)
        for name, rs in by_name.items():
            clusters = []
            for r in sorted(rs, key=lambda r: (-len(r), r['id'])):   # the most complete record leads its cluster
                home = next((c for c in clusters if (_addr(r.get('addr')) and _addr(r.get('addr')) == _addr(c[0].get('addr')) and _metres(r, c[0]) < 60) or r['id'] == c[0]['id']), None)
                (home.append(r) if home else clusters.append([r]))
            for c in clusters:
                lead = dict(c[0])
                lead['pids'] = [x['id'] for x in c]
                lead['field_sources'] = {f: lead['id'] for f in ('name','addr','web','hours','menu','lat','lon') if lead.get(f) is not None}
                conf = []
                evidence_conflicts = []
                for other in c[1:]:
                    dups += 1
                    for f in ('web', 'hours', 'addr', 'menu', 'wd'):
                        if other.get(f) and not lead.get(f):
                            lead[f] = other[f]
                            lead['field_sources'][f] = other['id']
                        elif other.get(f) and lead.get(f) and other[f] != lead[f] and f not in ('addr',):
                            conf.append(f)
                            evidence_conflicts.append({'field': f, 'retained': lead[f], 'other': other[f], 'other_provider_id': other['id']})
                if conf:
                    lead['conf'] = sorted(set(conf)); lead['field_conflicts'] = evidence_conflicts; conflicts += 1
                out.append(lead)
        for r in out:
            r['cid'] = next((previous_ids[p] for p in sorted(r['pids']) if p in previous_ids and previous_leads[p] in r['pids'] and previous_ids[p] not in claimed), 'sw:' + hashlib.sha1(min(r['pids']).encode()).hexdigest()[:12])
            claimed.add(r['cid'])
            r['status'] = 'closed_by_dohmh' if r.get('closed') else 'listed'
            r['upd'] = osm_stamp if r.get('src') == 'osm' else r.get('insp') if r.get('src') == 'dohmh' else r.get('designated') or None
            if r.get('dohmh') and r.get('src') == 'osm':
                r['pids'] = (r.get('pids') or [r['id']]) + ['dohmh:' + r['dohmh']]
            r['chk'] = built
            have = sum(bool(r.get(f)) for f in ('addr', 'web', 'hours'))
            r['q'] = 'complete' if have == 3 else 'partial' if have else 'minimal'
            if len(r['pids']) == 1:
                del r['pids']
        groups[cat] = out
        quality[cat] = {'merged_duplicates': dups, 'records_with_conflicts': conflicts,
                        'missing': {f: sum(1 for r in out if not r.get(f)) for f in ('addr', 'web', 'hours')}}
    # link LPC landmarks to the OSM record of the same building (kept as two linked records, one canonical ID)
    osm = [r for c in ('historic', 'attractions', 'museums', 'culture', 'parks', 'shopping', 'hotels') for r in groups[c]]
    linked = 0
    for l in groups['historic_lpc']:
        lw = set(_norm(l['name']).split()) - STOP
        best = None
        for r in osm:
            if abs(r['lat'] - l['lat']) > .0012 or abs(r['lon'] - l['lon']) > .0016:
                continue
            rw = set(_norm(r['name']).split()) - STOP
            if lw and rw and len(lw & rw) >= max(1, min(len(lw), len(rw)) / 2) and _metres(r, l) < 120:
                if best is None or _metres(r, l) < _metres(best, l):
                    best = r
        if best:
            l['cid'] = best['cid']; best['lpc'] = l['id']; l['osm'] = best['id']; linked += 1
    quality['historic_lpc']['linked_to_osm'] = linked
    return quality


def main():
    t0 = time.time()
    net = PedestrianNetwork()

    def routable(lon, lat):
        try:
            return net.snap(lon, lat, 'poi')['snap_distance_m']
        except RoutingError:
            return None

    d = overpass_pois()
    stamp = d.get('osm3s', {}).get('timestamp_osm_base')
    groups = {c[0]: [] for c in CATEGORIES}
    groups['historic_lpc'] = []
    dropped = 0
    for x in d['elements']:
        t = x.get('tags', {})
        lat, lon = (x.get('lat'), x.get('lon')) if x['type'] == 'node' else (x.get('center', {}).get('lat'), x.get('center', {}).get('lon'))
        if lat is None:
            continue
        cat = next((c for c, _, m in CATEGORIES if m(t)), None)
        if not cat or not (t.get('name') or cat in UNNAMED_LABEL):
            continue
        if cat == 'banks' and not t.get('name') and t.get('amenity') != 'atm':
            continue
        snap = routable(lon, lat)
        if snap is None:
            dropped += 1
            continue
        rec = {'id': f"osm:{x['type']}/{x['id']}", 'name': t.get('name') or UNNAMED_LABEL[cat], 'unnamed': None if t.get('name') else True, 'lat': round(lat, 6), 'lon': round(lon, 6), 'sub': subtype(t), 'src': 'osm',
               'addr': ' '.join(v for v in (t.get('addr:housenumber'), t.get('addr:street')) if v) or None,
               'web': t.get('website'), 'menu': t.get('website:menu'), 'hours': t.get('opening_hours'), 'wd': t.get('wikidata'),
               'cuisine': t.get('cuisine'), 'brand': t.get('brand'), 'stars': t.get('stars'), 'wheelchair': t.get('wheelchair'),
               'drink': {k[6:]: v for k, v in t.items() if k.startswith('drink:')} or None,
               'diet': {k[5:]: v for k, v in t.items() if k.startswith('diet:')} or None, 'snap': round(snap, 1),
               'phone': t.get('phone') or t.get('contact:phone'), 'fee': t.get('fee'), 'charge': t.get('charge'), 'reservation': t.get('reservation'),
               'desc': t.get('description'),
               # hotel facts as mapped (OSM): kept apart from any guest rating
               'amen': {k: t[k] for k in ('internet_access', 'air_conditioning', 'outdoor_seating', 'takeaway', 'delivery', 'rooms', 'beds', 'check_in', 'check_out') if t.get(k)} or None}
        if not rec['web'] and t.get('contact:website'):
            rec['web'] = t['contact:website']
        groups[cat].append({k: v for k, v in rec.items() if v is not None})
    for rec in restroom_records():
        snap = routable(rec['lon'], rec['lat'])
        if snap is not None:
            groups['restrooms'].append({**rec, 'snap': round(snap, 1)})
    for rec in landmark_records():
        snap = routable(rec['lon'], rec['lat'])
        if snap is not None:
            groups['historic_lpc'].append({**rec, 'snap': round(snap, 1)})
    notable = ('hotels', 'museums', 'attractions', 'historic', 'parks', 'culture', 'shopping')
    sl = wikidata_sitelinks([r['wd'] for c in notable for r in groups[c] if r.get('wd', '').startswith('Q')])
    from collections import Counter
    shared = Counter(r.get('wd') for c in notable for r in groups[c] if r.get('wd'))
    for c in notable:
        for r in groups[c]:
            # an ID on many records names their subject (45 plaques "Broadway" → Q11260), not each place
            if r.get('wd') in sl and shared[r['wd']] <= 3 and _same_thing(r['name'], sl[r['wd']][1]):
                r['sl'] = sl[r['wd']][0]
                if sl[r['wd']][2]:
                    r['wdesc'] = sl[r['wd']][2]          # Wikidata short description (CC0)
                if sl[r['wd']][3] and not r.get('web'):
                    r['web'] = sl[r['wd']][3]; r['web_src'] = 'wikidata P856'
    built = datetime.now(timezone.utc).isoformat(timespec='seconds')
    inspections = link_inspections(groups, routable)
    hotel_lots = link_hotel_lots(groups)
    quality = resolve_entities(groups, stamp, built)
    os.makedirs(OUT, exist_ok=True)
    cats, documents = [], {}
    labels = dict((c, l) for c, l, _ in CATEGORIES) | {'historic_lpc': 'NYC designated individual landmarks'}
    for cat, recs in groups.items():
        recs.sort(key=lambda r: (r['name'].lower(), r['id']))
        documents[cat+'.json'] = {'category': cat, 'records': recs}
        cats.append({'id': cat, 'label': labels[cat], 'count': len(recs), **quality.get(cat, {})})
    index = {'built_at': built, 'osm_timestamp': stamp, 'coverage': 'Within 150 m of the routable pedestrian graph (' + net.network_version + '): Manhattan',
             'network_version': net.network_version, 'categories': cats,
             'sources': {'osm': 'OpenStreetMap contributors via Overpass API (ODbL); names, tags and hours as mapped, not verified by STREETWISE',
                         'lpc': 'NYC Landmarks Preservation Commission individual landmarks (NYC Open Data)',
                         'nyc_restrooms': 'NYC Open Data Public Restrooms (i7jb-7jku), status as published',
                         'wikidata': 'Wikidata API sitelink counts (CC0)',
                         'dof_hotels': 'NYC Department of Finance Hotels Properties Citywide (tjus-cn27): hotel-class tax lots',
                         'dohmh': 'NYC DOHMH Restaurant Inspection Results (43nn-pn8j): permit, cuisine, phone, grade, last inspection, closure — not reviews'},
             'fields': {'sub': 'source tag', 'web': 'website', 'menu': 'website:menu (official menu link if mapped)', 'hours': 'opening_hours (OSM syntax)',
                        'cid': 'canonical place ID (stable across sources)', 'pids': 'provider IDs merged into this record', 'snap': 'metres to the walkable access point on the pedestrian graph',
                        'q': 'data quality: complete | partial | minimal', 'conf': 'fields that disagree between merged provider records', 'lpc': 'linked NYC LPC landmark ID',
                        'status': 'operational status as known: listed (in source; not verified open today)', 'upd': 'source data timestamp', 'chk': 'when STREETWISE built this record',
                        'wd': 'Wikidata ID', 'sl': 'Wikidata sitelink count (Wikipedia language editions etc.): notability signal', 'drink': 'drink:* tags (community-mapped, not menu verification)', 'diet': 'diet:* tags'},
             'dropped_outside_routing_coverage': dropped, 'inspections': inspections, 'hotel_lots': hotel_lots}
    from snapshot_io import publish
    documents['index.json'] = index
    publish(OUT, documents, os.path.join(os.path.dirname(ROOT), 'streetwise-data-history', 'poi-index'))
    print(json.dumps({c['id']: c['count'] for c in cats}), 'dropped', dropped, f'{time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
