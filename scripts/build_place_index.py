"""Discovery POI index for AI Discover My Walk: real named places inside the pedestrian routing coverage.

One Overpass snapshot of OpenStreetMap (ODbL) plus NYC LPC individual landmarks (from the urban data tiles),
split by discovery category into data/places/<category>.json, with data/places/index.json as the catalog.
Only places within 150 m of the routable pedestrian graph are kept, so every candidate can be reached by the
routing engine (today: Manhattan). Nothing is invented: every field is copied from its source or left out.
Run: python3 scripts/build_place_index.py   (about 1 minute; needs network access to the Overpass API)
"""
import json, math, os, sys, time
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
        'wikipedia', 'brand', 'operator', 'stars', 'wheelchair', 'addr:housenumber', 'addr:street', 'phone', 'fee', 'toilets:wheelchair')

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
        q = si.parse.urlencode({'action': 'wbgetentities', 'ids': '|'.join(ids[k:k + 50]), 'props': 'sitelinks|labels', 'languages': 'en', 'format': 'json'})
        for attempt in range(4):
            try:
                d = si.get('https://www.wikidata.org/w/api.php?' + q, timeout=60, tries=1)
                break
            except RuntimeError as e:
                d = None
                time.sleep(5 * (attempt + 1))
        if not d:
            print('  wikidata batch skipped after retries')
            continue
        for qid, ent in d.get('entities', {}).items():
            if 'sitelinks' in ent:
                out[qid] = (len(ent['sitelinks']), ent.get('labels', {}).get('en', {}).get('value', ''))
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
               'diet': {k[5:]: v for k, v in t.items() if k.startswith('diet:')} or None}
        groups[cat].append({k: v for k, v in rec.items() if v is not None})
    for rec in restroom_records():
        if routable(rec['lon'], rec['lat']) is not None:
            groups['restrooms'].append(rec)
    for rec in landmark_records():
        if routable(rec['lon'], rec['lat']) is not None:
            groups['historic_lpc'].append(rec)
    notable = ('hotels', 'museums', 'attractions', 'historic', 'parks', 'culture', 'shopping')
    sl = wikidata_sitelinks([r['wd'] for c in notable for r in groups[c] if r.get('wd', '').startswith('Q')])
    from collections import Counter
    shared = Counter(r.get('wd') for c in notable for r in groups[c] if r.get('wd'))
    for c in notable:
        for r in groups[c]:
            # an ID on many records names their subject (45 plaques "Broadway" → Q11260), not each place
            if r.get('wd') in sl and shared[r['wd']] <= 3 and _same_thing(r['name'], sl[r['wd']][1]):
                r['sl'] = sl[r['wd']][0]
    os.makedirs(OUT, exist_ok=True)
    built = datetime.now(timezone.utc).isoformat(timespec='seconds')
    cats = []
    labels = dict((c, l) for c, l, _ in CATEGORIES) | {'historic_lpc': 'NYC designated individual landmarks'}
    for cat, recs in groups.items():
        recs.sort(key=lambda r: (r['name'].lower(), r['id']))
        with open(os.path.join(OUT, cat + '.json'), 'w') as f:
            json.dump({'category': cat, 'records': recs}, f, separators=(',', ':'), ensure_ascii=False)
        cats.append({'id': cat, 'label': labels[cat], 'count': len(recs)})
    index = {'built_at': built, 'osm_timestamp': stamp, 'coverage': 'Within 150 m of the routable pedestrian graph (' + net.network_version + '): Manhattan',
             'network_version': net.network_version, 'categories': cats,
             'sources': {'osm': 'OpenStreetMap contributors via Overpass API (ODbL); names, tags and hours as mapped, not verified by STREETWISE',
                         'lpc': 'NYC Landmarks Preservation Commission individual landmarks (NYC Open Data)',
                         'nyc_restrooms': 'NYC Open Data Public Restrooms (i7jb-7jku), status as published',
                         'wikidata': 'Wikidata API sitelink counts (CC0)'},
             'fields': {'sub': 'source tag', 'web': 'website', 'menu': 'website:menu (official menu link if mapped)', 'hours': 'opening_hours (OSM syntax)',
                        'wd': 'Wikidata ID', 'sl': 'Wikidata sitelink count (Wikipedia language editions etc.): notability signal', 'drink': 'drink:* tags (community-mapped, not menu verification)', 'diet': 'diet:* tags'},
             'dropped_outside_routing_coverage': dropped}
    json.dump(index, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
    print(json.dumps({c['id']: c['count'] for c in cats}), 'dropped', dropped, f'{time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
