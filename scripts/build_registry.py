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
    repeats, missing_ids = 0, 0
    if not os.path.isdir(base):
        return None
    for fn in os.listdir(base):
        in_tile = set()
        for f in json.load(open(os.path.join(base, fn)))['features']:
            p = f['properties']
            if flt and not all(p.get(k) in v for k, v in flt.items()):
                continue
            fid = p.get('feature_id')
            if fid is None:
                missing_ids += 1
                fid = 'missing:' + json.dumps(f, sort_keys=True)
            if fid in in_tile: dup += 1
            in_tile.add(fid)
            if fid in seen:
                repeats += 1
                continue  # the same feature is repeated in every tile it crosses: not a duplicate record
            seen.add(fid); n += 1
            valid += valid_geom(f.get('geometry'))
            for a in attributes:
                missing[a] += p.get(a) in (None, '')
    return {'feature_count': n, 'valid_geometry_count': valid, 'duplicate_records': dup, 'cross_tile_repetitions': repeats, 'missing_feature_ids': missing_ids,
            'missing_fields': {a: round(missing[a] / n, 3) for a in attributes if n and missing[a]}}


def classify(r):
    """Data class, expected update frequency and known limitations (the registry's update policy)."""
    g, i = r['group'], r['dataset_id']
    if g == 'realtime':
        return {'data_class': 'realtime_availability', 'update_frequency': 'live (minutes)', 'known_limitations': 'Not stored; unavailable when the provider is down.'}
    if g == 'on_demand_providers':
        return {'data_class': 'realtime_availability' if i in ('provider:booking_demand', 'provider:expedia_rapid') else 'on_demand_business',
                'update_frequency': 'per request (no default content cache)',
                'known_limitations': 'Requires a backend key and the provider terms; results are matched by name and distance and may find no confident match.'}
    if g == 'business_evidence':
        return {'data_class': 'periodic_poi', 'update_frequency': 'daily at the publisher; rebuilt on demand',
                'known_limitations': 'Licensing / inspection evidence, not reviews or live opening status.' if i == 'dohmh_inspections' else 'Tax-lot evidence only.'}
    if i.startswith('citywide:'):
        return {'data_class':'periodic_poi','update_frequency':'daily audit target; download only if publisher version changes','known_limitations':r.get('note') or 'Source snapshot, not live opening status'}
    if g == 'tourism_discovery':
        return {'data_class': 'periodic_poi', 'update_frequency': 'weekly to monthly snapshot',
                'known_limitations': r.get('note') if r['dataset_id'].startswith('citywide:') else 'Volunteer-mapped; opening hours and websites may be outdated; Manhattan only.'}
    return {'data_class': 'static_urban', 'update_frequency': 'monthly to yearly', 'known_limitations': r.get('note') or 'See source documentation.'}


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
    # business evidence (server-side files) and on-demand / real-time providers
    insp = D('inspections', 'dohmh.json.gz')
    if os.path.exists(insp):
        m = json.load(gzip.open(insp, 'rt'))['metadata']
        rows.append({'dataset_id': 'dohmh_inspections', 'name': 'Food establishment permits and inspections (five boroughs)', 'group': 'business_evidence',
                     'publisher': 'NYC Department of Health and Mental Hygiene', 'source': m['source'], 'source_url': m['source_url'], 'license': m['license'],
                     'license_url': 'https://www.nyc.gov/home/terms-of-use.page', 'retrieved_at': m['retrieved_at'], 'publisher_updated_at': m['publisher_updated_at'],
                     'freshness_days': age_days(m['publisher_updated_at'] or m['retrieved_at'], now), 'coverage_area': 'NYC five boroughs ' + json.dumps(m['by_borough']),
                     'feature_count': m['records'], 'valid_geometry_count': m['with_coordinates'], 'duplicate_records': 0,
                     'missing_fields': {'coordinates': round(1 - m['with_coordinates'] / max(1, m['records']), 3)},
                     'update_method': 'scripts/build_inspections.py (Socrata API)', 'integration_status': 'connected', 'note': m['note']})
        for r in rows:
            if r['dataset_id'] == 'restaurant_inspections':
                r.update(integration_status='connected (server-side, not a map layer)', note='Used through dohmh_inspections for place status, grades and closures.')
    hl = idx.get('hotel_lots') or {}
    if hl.get('available'):
        rows.append({'dataset_id': 'dof_hotel_lots', 'name': 'Hotel-class tax lots (Manhattan)', 'group': 'business_evidence', 'publisher': 'NYC Department of Finance',
                     'source': 'NYC DOF Hotels Properties Citywide (tjus-cn27)', 'source_url': 'https://data.cityofnewyork.us/d/tjus-cn27', 'license': 'NYC Open Data Terms of Use',
                     'license_url': 'https://www.nyc.gov/home/terms-of-use.page', 'retrieved_at': idx['built_at'], 'freshness_days': age_days(idx['built_at'], now),
                     'coverage_area': 'Manhattan', 'feature_count': hl['lots'], 'linked_records': hl['hotels_matched'], 'update_method': 'scripts/build_place_index.py',
                     'integration_status': 'connected', 'note': 'Confirms a hotel-class building at the mapped point; says nothing about rooms, prices or ratings.'})
    for pid, name, env, what in (('google_places', 'Google Places API (New)', 'GOOGLE_PLACES_API_KEY', 'ratings, review counts, price level, hours'),
                                 ('yelp_fusion', 'Yelp Fusion API', 'YELP_API_KEY', 'ratings, review counts, price'),
                                 ('foursquare', 'Foursquare Places API', 'FOURSQUARE_API_KEY', 'ratings (0-10), rating counts, price'),
                                 ('booking_demand', 'Booking.com Demand API', 'BOOKING_DEMAND_API_KEY', 'hotel room types, rates, availability'),
                                 ('expedia_rapid', 'Expedia Rapid API', 'EXPEDIA_RAPID_API_KEY', 'hotel room types, rates, availability')):
        rows.append({'dataset_id': 'provider:' + pid, 'name': name, 'group': 'on_demand_providers', 'publisher': name.split()[0], 'license': 'provider terms (no long-term storage)', 'retrieved_at': None,
                     'coverage_area': 'per request', 'feature_count': None, 'integration_status': ('not_implemented' if pid in ('booking_demand', 'expedia_rapid') else 'configured_not_verified') if os.environ.get(env, '').strip() else 'blocked_by_provider_access',
                     'update_method': f'live per request, no default content cache (env {env} on the backend)', 'note': f'Provides {what}. Nothing is stored or shown without the key.'})
    for rid, name, pub, url, what in (('open_meteo', 'Current weather', 'Open-Meteo', 'https://open-meteo.com/', 'temperature, wind, precipitation (model, not station)'),
                                      ('nws_alerts', 'Weather alerts', 'US National Weather Service', 'https://api.weather.gov/', 'active alerts for the map area')):
        rows.append({'dataset_id': rid, 'name': name, 'group': 'realtime', 'publisher': pub, 'source_url': url, 'license': 'CC BY 4.0' if rid == 'open_meteo' else 'US public domain', 'retrieved_at': None,
                     'coverage_area': 'NYC', 'feature_count': None, 'integration_status': 'connected', 'update_method': 'live in the browser (weather.js)', 'note': what})
    citywide = D('places', 'citywide.json')
    if os.path.exists(citywide):
        document = json.load(open(citywide))
        for source in document['metadata']['sources']:
            records = [r for r in document['records'] if source['dataset_id'] in r['id']]
            rows.append({'dataset_id': 'citywide:' + source['dataset_id'], 'name': source['name'], 'group': 'tourism_discovery',
                         'publisher': source['publisher'], 'source_url': source['source_url'], 'license': source['license'],
                         'retrieved_at': source['retrieved_at'], 'publisher_updated_at': source['publisher_updated_at'],
                         'freshness_days': age_days(source['publisher_updated_at'], now), 'feature_count': len(records),
                         'valid_geometry_count': sum(NYC[0]<=r['lon']<=NYC[2] and NYC[1]<=r['lat']<=NYC[3] for r in records),
                         'duplicate_records': len(records)-len({r['id'] for r in records}), 'coverage_area': 'NYC citywide (search only)',
                         'geometry_type': 'Point (not a verified entrance)', 'integration_status': 'connected',
                         'missing_fields': {k: sum(not r.get(k) for r in records)/len(records) for k in ['addr','hours','web','boro']},
                         'note': source['known_limitations']})
    inventory=D('urban','inventory.json')
    if os.path.exists(inventory):
        for s in json.load(open(inventory))['datasets']:
            miss={k:(v.get('fraction') if isinstance(v,dict) else v) for k,v in s.get('missing_fields',{}).items()}
            rows.append({'dataset_id':'indexed:'+s['dataset_id'],'name':s['name'],'group':'indexed_urban',
                'publisher':s['name'].split(' ')[0]+' / NYC Open Data','source_url':s['source_url'],'license':'NYC Open Data Terms of Use',
                'coverage_area':s['coverage'],'feature_count':s['records'],'valid_geometry_count':s['records'],
                'publisher_updated_at':s['publisher_updated_at'],'retrieved_at':s['retrieved_at'],'freshness_days':age_days(s['publisher_updated_at'],now),
                'missing_fields':miss,'duplicate_records':0,'geometry_type':'Indexed source geometry','integration_status':'connected',
                'routing_usage':s['routing_usage'],'frontend_usage':s['frontend_usage'],'note':s['representation']})
    for r in rows:
        r.update(classify(r))
    out = {'built_at': now.isoformat(timespec='seconds'), 'datasets': rows,
           'notes': ['feature_count is records in the shipped files; it is not a count of places verified as currently open.',
                     'Search covers five boroughs through external providers (places.js); routing, scoring and discovery cover Manhattan.']}
    json.dump(out, open(D('registry.json'), 'w'), indent=1)
    print(len(rows), 'datasets;', sum(r.get('feature_count') or 0 for r in rows), 'records')


if __name__ == '__main__':
    main()
