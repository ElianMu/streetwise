"""Refresh official NYC-wide parks and restrooms as search-only evidence.
No commercial scraping. Full source snapshots are used when no reliable change cursor exists.
Validate before atomic replacement; keep previous version for rollback outside the checkout.
"""
import hashlib, json, os, pathlib, tempfile, urllib.parse, urllib.request
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/places/citywide.json'
SOURCES = {'parks': ('enfh-gkve', 'NYC Parks Properties'), 'restrooms': ('i7jb-7jku', 'NYC Public Restrooms')}
BORO = {'M': 'Manhattan', 'B': 'Brooklyn', 'Q': 'Queens', 'X': 'Bronx', 'R': 'Staten Island'}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'STREETWISE-NYC-data-audit/1.0'}), timeout=60) as r:
        return json.load(r)


def interior_point(geometry):
    """Scanline representative point inside an outer ring, never an asserted entrance."""
    polys = geometry.get('coordinates', []) if geometry.get('type') == 'MultiPolygon' else [geometry.get('coordinates', [])]
    best = None
    for poly in polys:
        if not poly or not poly[0]: continue
        y = (min(p[1] for p in poly[0]) + max(p[1] for p in poly[0])) / 2
        crossings = []
        for ring in poly:
            for a, b in zip(ring, ring[1:]):
                if (a[1] > y) != (b[1] > y):
                    crossings.append(a[0] + (y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
        crossings.sort()
        for x1, x2 in zip(crossings[::2], crossings[1::2]):
            if best is None or x2-x1 > best[0]: best = (x2-x1, (x1+x2)/2, y)
    return (best[1], best[2]) if best else None


def build():
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    all_records, metadata = [], []
    previous = json.loads(OUT.read_text()) if OUT.exists() else None
    previous_sources = {s['dataset_id']: s for s in previous['metadata']['sources']} if previous else {}
    for category, (dataset, name) in SOURCES.items():
        meta = fetch(f'https://data.cityofnewyork.us/api/views/{dataset}.json')
        old_source = previous_sources.get(dataset)
        updated = datetime.fromtimestamp(meta['rowsUpdatedAt'], timezone.utc).isoformat() if meta.get('rowsUpdatedAt') else None
        if old_source and updated and old_source.get('publisher_updated_at') == updated:
            all_records.extend(r for r in previous['records'] if r['id'].startswith('nyc:'+dataset+':'))
            metadata.append(old_source)
            continue
        rows, offset = [], 0
        while True:
            batch = fetch(f'https://data.cityofnewyork.us/resource/{dataset}.json?' + urllib.parse.urlencode({'$limit': 5000, '$offset': offset, '$order': ':id'}))
            rows.extend(batch)
            if len(batch) < 5000: break
            offset += 5000
        if not rows: raise ValueError('Empty source; preserving existing snapshot')
        records, rejected = {}, 0
        for r in rows:
            if category == 'parks':
                if str(r.get('retired')).lower() == 'true': continue
                point = interior_point(r.get('multipolygon') or {})
                pid, label = r.get('gispropnum') or r.get('globalid'), r.get('signname') or r.get('name311')
                extra = {'boro': BORO.get(r.get('borough')), 'sub': r.get('typecategory'), 'addr': r.get('address'),
                         'coordinate_basis': 'derived polygon interior point; not a visitor entrance', 'waterfront': r.get('waterfront')}
            else:
                try: point = float(r['longitude']), float(r['latitude'])
                except (KeyError, ValueError, TypeError): point = None
                # No publisher facility ID: stable source-field hash, not a claimed cross-provider identity.
                pid = hashlib.sha256(json.dumps([r.get('facility_name'),r.get('operator'),point], sort_keys=True).encode()).hexdigest()[:20]
                label = r.get('facility_name')
                extra = {'hours': r.get('hours_of_operation'), 'operator': r.get('operator'), 'source_status': r.get('status'),
                         'access': r.get('accessibility'), 'coordinate_basis': 'publisher point; entrance unverified'}
            if not pid or not label or not point or not (-74.30 < point[0] < -73.68 and 40.45 < point[1] < 40.95):
                rejected += 1; continue
            rec = {'id': f'nyc:{dataset}:{pid}', 'name': label, 'lat': point[1], 'lon': point[0],
                   'cat': category, 'src': name, 'source_url': f'https://data.cityofnewyork.us/d/{dataset}',
                   'upd': datetime.fromtimestamp(meta['rowsUpdatedAt'], timezone.utc).isoformat() if meta.get('rowsUpdatedAt') else None,
                   'chk': now, 'search_only': True, **extra}
            # Duplicate publisher IDs are parcels of the same park; retain one representative point.
            records.setdefault(rec['id'], rec)
        if len(records) < 20: raise ValueError('Suspiciously small source; preserving snapshot')
        all_records.extend(records.values())
        metadata.append({'dataset_id': dataset, 'name': meta.get('name') or name, 'publisher': 'City of New York',
                         'source_url': f'https://data.cityofnewyork.us/d/{dataset}', 'license': 'NYC Open Data Terms of Use',
                         'retrieved_at': now, 'publisher_updated_at': next(iter(records.values()))['upd'],
                         'source_rows': len(rows), 'records': len(records), 'invalid_or_missing_coordinates_or_identity': rejected,
                         'data_class': 'periodic_poi', 'coverage': 'NYC citywide', 'geometry_type': 'representative Point',
                         'update_frequency': 'on-demand snapshot; compare publisher rowsUpdatedAt',
                         'known_limitations': 'Search only; no live opening or entrance verification. Restroom borough is unavailable in this source snapshot.'})
    if previous and metadata == previous['metadata']['sources']:
        return previous
    return {'metadata': {'retrieved_at': now, 'sources': metadata, 'records': len(all_records)}, 'records': all_records}


def save(document, destination=OUT):
    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()
    # Content changes, excluding fetch timestamps, are recorded without losing prior valid state.
    previous = destination.read_bytes() if destination.exists() else None
    if previous:
        old = json.loads(previous)
        if old == document:
            print('Publisher versions unchanged; retaining validated snapshot'); return
        if len(document['records']) < .7 * len(old['records']): raise ValueError('Large count regression; manual review required')
        old_ids = {r['id'] for r in old['records']}; new_ids = {r['id'] for r in document['records']}
        document['metadata']['change_detection'] = {'added': len(new_ids-old_ids), 'removed': len(old_ids-new_ids)}
        archive = ROOT.parent / 'streetwise-data-history'; archive.mkdir(exist_ok=True)
        (archive / (hashlib.sha256(previous).hexdigest()+'.json')).write_bytes(previous)
        document['metadata']['previous_version'] = hashlib.sha256(previous).hexdigest()
    payload = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as f:
        f.write(payload); staging = f.name
    os.replace(staging, destination)
    print(json.dumps(document['metadata'], indent=2))

if __name__ == '__main__': save(build())
