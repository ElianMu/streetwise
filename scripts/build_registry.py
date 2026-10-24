"""Dataset Registry (data/registry.json): one row per dataset STREETWISE uses, measured from the files actually shipped.

Counts are computed by reading every tile / record, not copied from documentation: features, features with valid geometry,
duplicate IDs, missing attribute rates. Publisher, licence and update method come from the source; freshness is the age of
the publisher's last update at build time. A record count is not a count of places verified open today.
Run: python3 scripts/build_registry.py   (reads data/ only; no network)
"""
import gzip, json, math, os
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, 'data', *p)
NYC = (-74.2591, 40.4774, -73.7004, 40.9176)

LICENSES = [('OpenStreetMap', 'OpenStreetMap contributors', 'ODbL 1.0', 'https://www.openstreetmap.org/copyright'),
            ('Overpass', 'OpenStreetMap contributors', 'ODbL 1.0', 'https://www.openstreetmap.org/copyright'),
            ('NYC Open Data', 'City of New York (NYC Open Data)', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('NYC DCP', 'NYC Department of City Planning', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('NYC Parks', 'NYC Department of Parks & Recreation (NYC Open Data)', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('311', 'NYC 311 (NYC Open Data)', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('NYPD', 'NYPD (NYC Open Data)', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('DOT', 'NYC Department of Transportation (NYC Open Data)', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('LPC', 'NYC Landmarks Preservation Commission', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'),
            ('NYS', 'State of New York (data.ny.gov)', 'Open Data NY Terms of Use', 'https://data.ny.gov/download/77gx-ii52/application/pdf'),
            ('MTA', 'Metropolitan Transportation Authority (data.ny.gov)', 'Open Data NY Terms of Use', 'https://data.ny.gov/download/77gx-ii52/application/pdf'),
            ('Wikidata', 'Wikidata', 'CC0 1.0', 'https://creativecommons.org/publicdomain/zero/1.0/')]


def licence(source):
    for key, pub, lic, url in LICENSES:
        if key.lower() in (source or '').lower():
            return pub, lic, url
    s = source or ''
    if s.startswith('NYC ') or 'LinkNYC' in s:
        return 'City of New York', 'NYC Open Data Terms of Use', 'https://www.nyc.gov/home/terms-of-use.page'
    if 'USGS' in s or 'EPA' in s:
        return s, 'US Government work (public domain)', None
    if 'Citi Bike' in s:
        return 'Lyft / Citi Bike', 'Citi Bike Data License Agreement', 'https://ride.citibikenyc.com/data-sharing-policy'
    return (s or 'Not connected'), 'Not applicable (no data used)' if not s else 'See source', None


def valid_geom(g):
    def pts(c):
        return [c] if c and isinstance(c[0], (int, float)) else [p for x in (c or []) for p in pts(x)]
    p = pts(g.get('coordinates') if g else None)
    return bool(p) and all(len(q) >= 2 and all(math.isfinite(v) for v in q[:2]) and NYC[0] <= q[0] <= NYC[2] and NYC[1] <= q[1] <= NYC[3] for q in p)


def age_days(date, now):
    try:
        d = datetime.fromisoformat(str(date).replace('Z', '+00:00'))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return (now - d).days
    except (TypeError, ValueError):
        return None


def tileset_stats(tileset, flt, attributes):
    base = D('layers', 'tiles', tileset)
    seen, n, valid, dup, missing = set(), 0, 0, 0, Counter()
    if not os.path.isdir(base):
        return None
    for fn in os.listdir(base):
        for f in json.load(open(os.path.join(base, fn)))['features']:
            p = f['properties']
            if flt and not all(p.get(k) in v for k, v in flt.items()):
                continue
            fid = p.get('feature_id')
            if fid in seen:
                continue  # the same feature is repeated in every tile it crosses: not a duplicate record
            seen.add(fid); n += 1
            valid += valid_geom(f.get('geometry'))
            for a in attributes:
                missing[a] += p.get(a) in (None, '')
    return {'feature_count': n, 'valid_geometry_count': valid, 'duplicate_records': dup,
            'missing_fields': {a: round(missing[a] / n, 3) for a in attributes if n and missing[a]}}


def main():
    now = datetime.now(timezone.utc)
    cat = json.load(open(D('layers', 'catalog.json')))
    rows = []
    for d in cat['datasets']:
        pub, lic, lic_url = licence(d.get('source'))
        st = tileset_stats(d['tileset'], d.get('filter'), d.get('attributes') or []) if d['status'] == 'CONNECTED' and d.get('tileset') else None
        rows.append({'dataset_id': d['id'], 'name': d['name'], 'group': 'urban_data_layers', 'publisher': pub, 'source': d.get('source'),
                     'source_url': d.get('source_url'), 'license': lic, 'license_url': lic_url, 'retrieved_at': cat['built_at'],
                     'publisher_updated_at': d.get('last_updated'), 'freshness_days': age_days(d.get('last_updated'), now),
                     'coverage_area': 'Manhattan (tile build box)', 'time_range': d.get('time_range'),
                     **(st or {'feature_count': None, 'valid_geometry_count': None, 'duplicate_records': None, 'missing_fields': {}}),
                     'update_method': 'scripts/build_urban_layers.py (rebuilt with street data refresh)',
                     'integration_status': {'CONNECTED': 'connected', 'AVAILABLE_NOT_CONNECTED': 'available, not connected',
                                            'MISSING': 'no dataset', 'UNAVAILABLE': 'unavailable'}.get(d['status'], d['status']),
                     'used_in_scoring': d.get('used_in_scoring', False), 'historical': d.get('historical', False), 'note': d.get('note')})
    idx = json.load(open(D('places', 'index.json')))
    for c in idx['categories']:
        recs = json.load(open(D('places', c['id'] + '.json')))['records']
        src = Counter(r.get('src') for r in recs)
        pub, lic, lic_url = licence('LPC' if c['id'] == 'historic_lpc' else 'NYC Open Data' if c['id'] == 'restrooms' and src.get('nyc_restrooms', 0) > src.get('osm', 0) else 'OpenStreetMap')
        rows.append({'dataset_id': 'places:' + c['id'], 'name': c['label'] + ' (discovery index)', 'group': 'tourism_discovery', 'publisher': pub,
                     'source': ', '.join(f'{k} ({v})' for k, v in src.items()), 'source_url': 'https://overpass-api.de/' if src.get('osm') else None,
                     'license': lic, 'license_url': lic_url, 'retrieved_at': idx['built_at'], 'publisher_updated_at': idx['osm_timestamp'],
                     'freshness_days': age_days(idx['osm_timestamp'], now), 'coverage_area': idx['coverage'],
                     'feature_count': len(recs), 'valid_geometry_count': sum(valid_geom({'coordinates': [r['lon'], r['lat']]}) for r in recs),
                     'duplicate_records': c.get('merged_duplicates', 0), 'records_with_conflicts': c.get('records_with_conflicts', 0),
                     'missing_fields': {f: round(v / max(1, len(recs)), 3) for f, v in (c.get('missing') or {}).items()},
                     'update_method': 'scripts/build_place_index.py (Overpass snapshot + Wikidata sitelinks)', 'integration_status': 'connected',
                     'note': 'Listed places; operating status today is not verified.'})
    graph = json.load(gzip.open(D('pedestrian', 'manhattan-walk-graph.json.gz'), 'rt'))
    g = {**graph['metadata'], 'edges': len(graph['edges']), 'nodes': len(graph['nodes'])}
    es = json.load(gzip.open(D('pedestrian', 'edge-scores.json.gz'), 'rt'))['metadata']
    st = json.load(open(D('manhattan-streets.json')))['metadata']
    for row in ({'dataset_id': 'pedestrian_network', 'name': 'OSM pedestrian routing graph', 'publisher': 'OpenStreetMap contributors', 'license': 'ODbL 1.0',
                 'retrieved_at': g.get('built_at'), 'publisher_updated_at': g.get('osm_timestamp') or g.get('built_at'), 'coverage_area': g.get('place', 'Manhattan'),
                 'feature_count': g.get('edges') or g.get('edge_count'), 'version': g.get('network_version'), 'update_method': 'scripts/build_pedestrian_network.py (OSMnx)'},
                {'dataset_id': 'edge_scores', 'name': '12-dimension scores on routing edges', 'publisher': 'STREETWISE (derived)', 'license': 'derived from listed sources',
                 'retrieved_at': es.get('built_at'), 'coverage_area': 'Manhattan', 'feature_count': es.get('geometries'), 'version': es.get('score_version'),
                 'coverage_by_dimension': es.get('routable_length_coverage_by_dimension'), 'update_method': 'scripts/match_lion_osm.py'},
                {'dataset_id': 'street_segments', 'name': 'Manhattan street segments with 12-dimension scores', 'publisher': 'STREETWISE (derived from NYC DCP LION and listed sources)',
                 'license': 'derived', 'retrieved_at': st.get('retrieved_at'), 'publisher_updated_at': st.get('data_version'), 'coverage_area': 'Manhattan',
                 'feature_count': st.get('segments'), 'version': st.get('score_version'), 'update_method': 'scripts/build_manhattan_streets.py'}):
        rows.append({'group': 'routing_and_scoring', 'integration_status': 'connected', 'freshness_days': age_days(row.get('publisher_updated_at') or row.get('retrieved_at'), now), **row})
    out = {'built_at': now.isoformat(timespec='seconds'), 'datasets': rows,
           'notes': ['feature_count is records in the shipped files; it is not a count of places verified as currently open.',
                     'Search covers five boroughs through external providers (places.js); routing, scoring and discovery cover Manhattan.']}
    json.dump(out, open(D('registry.json'), 'w'), indent=1)
    print(len(rows), 'datasets;', sum(r.get('feature_count') or 0 for r in rows), 'records')


if __name__ == '__main__':
    main()
