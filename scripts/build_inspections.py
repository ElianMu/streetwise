"""NYC food establishments from the DOHMH Restaurant Inspection Results (NYC Open Data 43nn-pn8j), all five boroughs.

One record per permit (CAMIS) with: name (DBA as registered), address, phone, cuisine, coordinates, BBL, last inspection date,
latest letter grade and its date, and whether the most recent closure action is still standing (closed by DOHMH, not
re-opened). This is official licensing / inspection evidence — not reviews, not ratings, not proof of today's opening hours.
Output: data/inspections/dohmh.json.gz (server-side; too large for the browser) + metadata.
Run: python3 scripts/build_inspections.py   (about 30 s; network)
"""
import gzip, json, os, sys, time, tempfile, hashlib, shutil
from datetime import datetime, timezone
from urllib import parse, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'inspections')
API = 'https://data.cityofnewyork.us/resource/43nn-pn8j.json?'
META = 'https://data.cityofnewyork.us/api/views/43nn-pn8j.json'
UA = {'User-Agent': 'STREETWISE-NYC-build/1.0 (https://elianmu.github.io/streetwise/)'}


def q(params, tries=3):
    for k in range(tries):
        try:
            with request.urlopen(request.Request(API + parse.urlencode(params), headers=UA), timeout=180) as r:
                return json.load(r)
        except Exception as e:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def paged(params):
    out, off = [], 0
    while True:
        rows = q({**params, '$limit': 50000, '$offset': off})
        out += rows
        if len(rows) < 50000:
            return out
        off += 50000


def main():
    t0 = time.time()
    base = paged({'$select': 'camis,dba,boro,building,street,zipcode,phone,cuisine_description,latitude,longitude,bbl,max(inspection_date) as last_inspection',
                  '$group': 'camis,dba,boro,building,street,zipcode,phone,cuisine_description,latitude,longitude,bbl', '$order': 'camis'})
    grades = paged({'$select': 'camis,grade,max(grade_date) as gd', '$where': "grade in ('A','B','C')", '$group': 'camis,grade'})
    actions = paged({'$select': 'camis,action,max(inspection_date) as d', '$where': "action like 'Establishment%'", '$group': 'camis,action'})
    if not base or not grades or not actions: raise ValueError('Incomplete inspection source response; retaining previous snapshot')
    latest_grade = {}
    for g in grades:
        if g.get('gd') and (g['camis'] not in latest_grade or g['gd'] > latest_grade[g['camis']][1]):
            latest_grade[g['camis']] = (g['grade'], g['gd'])
    closure = {}
    for a in actions:
        kind = 'reopened' if 're-opened' in a['action'] else 'closed'
        if a['camis'] not in closure or a['d'] > closure[a['camis']][1]:
            closure[a['camis']] = (kind, a['d'])
    recs, seen = [], {}
    for b in base:
        c = b['camis']
        lat, lon = float(b.get('latitude') or 0), float(b.get('longitude') or 0)
        if c in seen:   # the same permit with an amended address / phone: keep the most recently inspected version
            if b['last_inspection'] <= seen[c]['last_inspection']:
                continue
            recs.remove(seen[c])
        gr = latest_grade.get(c)
        cl = closure.get(c)
        r = {'camis': c, 'name': (b.get('dba') or '').strip(), 'boro': b.get('boro'), 'addr': ' '.join(x for x in (b.get('building'), b.get('street')) if x),
             'zip': b.get('zipcode'), 'phone': b.get('phone'), 'cuisine': b.get('cuisine_description'), 'bbl': b.get('bbl'),
             'lat': round(lat, 6) if lat else None, 'lon': round(lon, 6) if lon else None, 'last_inspection': (b.get('last_inspection') or '')[:10] or None,
             'grade': gr[0] if gr else None, 'grade_date': gr[1][:10] if gr else None,
             'closed_by_dohmh': bool(cl and cl[0] == 'closed'), 'closure_date': cl[1][:10] if cl and cl[0] == 'closed' else None}
        recs.append(r)
        seen[c] = r
    try:
        with request.urlopen(request.Request(META, headers=UA), timeout=60) as resp:
            updated = datetime.fromtimestamp(json.load(resp).get('rowsUpdatedAt', 0), timezone.utc).isoformat(timespec='seconds')
    except Exception:
        updated = None
    os.makedirs(OUT, exist_ok=True)
    meta = {'source': 'NYC DOHMH Restaurant Inspection Results (NYC Open Data 43nn-pn8j)', 'source_url': 'https://data.cityofnewyork.us/d/43nn-pn8j',
            'license': 'NYC Open Data Terms of Use', 'publisher_updated_at': updated, 'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'records': len(recs), 'with_coordinates': sum(1 for r in recs if r['lat']), 'by_borough': {},
            'note': 'Permits and inspections, not reviews. "closed_by_dohmh" = the latest closure action has no later re-opening action.'}
    for r in recs:
        meta['by_borough'][r['boro']] = meta['by_borough'].get(r['boro'], 0) + 1
    if not recs: raise ValueError('Empty refresh; retaining current inspection snapshot')
    destination = os.path.join(OUT, 'dohmh.json.gz')
    if os.path.exists(destination):
        archive = os.path.join(os.path.dirname(ROOT), 'streetwise-data-history', 'inspections')
        os.makedirs(archive,exist_ok=True)
        with open(destination,'rb') as f: version=hashlib.sha256(f.read()).hexdigest()
        shutil.copy2(destination,os.path.join(archive,version+'.json.gz'))
    with tempfile.NamedTemporaryFile(dir=OUT,delete=False) as f: staging=f.name
    try:
        with gzip.open(staging, 'wt', encoding='utf-8') as f:
            json.dump({'metadata': meta, 'records': recs}, f, separators=(',', ':'))
        os.replace(staging,destination)
    finally:
        if os.path.exists(staging): os.unlink(staging)
    print(json.dumps({k: meta[k] for k in ('records', 'with_coordinates', 'by_borough', 'publisher_updated_at')}), f'{time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
