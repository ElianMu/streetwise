"""Match NYC LION analysis segments to OSM pedestrian edges and give every edge the 12 experience scores.

Run: python3 scripts/match_lion_osm.py [--cache DIR]
Reads  data/pedestrian/manhattan-walk-graph.json.gz (routing layer) and data/manhattan-streets.json (experience layer).
Writes data/pedestrian/street_osm_edge_mapping.csv.gz  one row per (directed OSM edge, LION analysis segment) match
       data/pedestrian/edge-scores.json.gz             12 scores, coverage, source and match quality per edge geometry
Standard library only. Explore's LION scores are read, never changed.

Matching is not nearest-neighbour: every 5 m sample of an OSM edge must find a LION segment that is close enough
for the edge's type (centreline, sidewalk offset or path), runs in the same direction (<= 20 deg), does not carry a
conflicting street name, and is on the same level (bridges, tunnels and layered edges never match ground streets).
An edge whose length is mostly unmatched (crossings, park paths, bridges) is measured directly with the same
indicator code and scored on the LION reference scale; if that is impossible its scores stay None (N/A).
"""
import argparse, csv, gzip, io, json, math, os, re, sys, time, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streetwise_indicators as si

ROOT = si.ROOT
GRAPH = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
STREETS = os.path.join(ROOT, 'data', 'manhattan-streets.json')
MAPPING = os.path.join(ROOT, 'data', 'pedestrian', 'street_osm_edge_mapping.csv.gz')
SCORES = os.path.join(ROOT, 'data', 'pedestrian', 'edge-scores.json.gz')
ROAD = {'residential', 'primary', 'secondary', 'tertiary', 'unclassified', 'living_street', 'service', 'trunk',
        'primary_link', 'secondary_link', 'tertiary_link', 'trunk_link', 'road'}
MAX_DIST = {'road': 15.0, 'sidewalk': 28.0, 'path': 12.0}  # metres from the LION centreline
MAX_ANGLE = 20.0
STEP = 5.0
MIN_LION_SHARE = 0.6  # below this the edge is measured directly instead of borrowing LION scores

WORDS = {'STREET': 'ST', 'AVENUE': 'AV', 'AVE': 'AV', 'WEST': 'W', 'EAST': 'E', 'NORTH': 'N', 'SOUTH': 'S',
         'BOULEVARD': 'BLVD', 'PLACE': 'PL', 'DRIVE': 'DR', 'ROAD': 'RD', 'PARKWAY': 'PKWY', 'SQUARE': 'SQ',
         'LANE': 'LN', 'TERRACE': 'TER', 'PLAZA': 'PLZ', 'SAINT': 'ST', 'FREDERICK': 'FRED', 'DOUGLASS': 'DOUGLASS'}


# Official co-names: OSM often uses one, LION the other.
ALIASES = [('6 AV', 'AV AMERICAS', 'MEXICO TENOCHTITLAN AV'), ('LENOX AV', 'MALCOLM X BLVD'),
           ('7 AV', 'ADAM CLAYTON POWELL JR BLVD'), ('8 AV', 'FREDERICK DOUGLASS BLVD'), ('E 116 ST', 'LUIS MUNOZ MARIN BLVD'),
           ('W 125 ST', 'E 125 ST', 'MARTIN LUTHER KING JR BLVD', 'DR MARTIN LUTHER KING JR BLVD')]


def _tokens(name):
    s = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode().upper()
    s = re.sub(r'(\d+)(ST|ND|RD|TH)\b', r'\1', re.sub(r'[^A-Z0-9 ]', ' ', s))
    return frozenset(WORDS.get(t, t) for t in s.split() if t not in {'THE', 'OF'})


ALIAS_OF = {_tokens(n): i for i, group in enumerate(ALIASES) for n in group}


def name_tokens(name):
    if not name:
        return frozenset()
    t = _tokens(name)
    return frozenset({f'ALIAS{ALIAS_OF[t]}'}) if t in ALIAS_OF else t


GENERIC = {'W', 'E', 'N', 'S', 'ST', 'AV', 'BLVD', 'PL', 'DR', 'RD', 'PKWY', 'SQ', 'LN', 'TER', 'PLZ', 'JR'}


def names_compatible(a, b):
    """None = cannot tell (a name missing); True/False = agreement. Distinctive words must overlap and numbers must
    be identical, so 'W 42 ST' never matches 'W 43 ST' and 'E 42 ST' never matches 'W 42 ST'."""
    if not a or not b:
        return None
    da, db = a - GENERIC, b - GENERIC
    if not da or not db:
        return None
    na, nb = {t for t in da if t.isdigit()}, {t for t in db if t.isdigit()}
    if (na or nb) and na != nb:
        return False
    ea, eb = a & {'E', 'W', 'N', 'S'}, b & {'E', 'W', 'N', 'S'}
    if ea != eb:  # 'Broadway' vs 'W Broadway' are different streets; unsure cases fall back to direct measurement
        return False
    return bool(da & db)


def edge_kind(tags):
    footway, highway = set(si_list(tags.get('footway'))), set(si_list(tags.get('highway')))
    if 'sidewalk' in footway:
        return 'sidewalk'
    if 'crossing' in footway:
        return 'crossing'
    if highway & ROAD:
        return 'road'
    return 'path'


def si_list(v):
    return v if isinstance(v, list) else [] if v is None else [v]


def layered(tags):
    vals = lambda k: [x for x in si_list(tags.get(k)) if x not in ('no', None)]
    return bool(vals('bridge') or vals('tunnel') or [x for x in si_list(tags.get('layer')) if str(x) not in ('0',)] or vals('indoor'))


def bearing(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def angle_diff(x, y):
    d = abs(x - y) % 180
    return min(d, 180 - d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default=os.path.join(ROOT, 'data', 'cache', 'sources'), help='raw source cache (shared with build_manhattan_streets.py)')
    args = ap.parse_args()
    t0 = time.time()
    graph = json.load(gzip.open(GRAPH, 'rt', encoding='utf-8'))
    streets = json.load(open(STREETS, encoding='utf-8'))
    gmeta, smeta = graph['metadata'], streets['metadata']
    if smeta.get('score_version') != si.score_version():
        sys.exit('manhattan-streets.json was built with a different indicator definition; rebuild it first.')
    nodes, geoms, edges = graph['nodes'], graph['geoms'], graph['edges']

    # LION analysis segments in metric space, indexed by 50 m buckets.
    segs = []
    for f in streets['features']:
        p = f['properties']; pts = [si.xy(q) for q in f['geometry']['coordinates']]
        segs.append({'p': p, 'pts': pts, 'names': name_tokens(p['name']),
                     'bearings': [bearing(a, b) for a, b in zip(pts, pts[1:])]})
    B, index = 50.0, {}
    for i, s in enumerate(segs):
        for a, b in zip(s['pts'], s['pts'][1:]):
            pad = 30
            for gx in range(int((min(a[0], b[0]) - pad) // B), int((max(a[0], b[0]) + pad) // B) + 1):
                for gy in range(int((min(a[1], b[1]) - pad) // B), int((max(a[1], b[1]) + pad) // B) + 1):
                    bucket = index.setdefault((gx, gy), [])
                    if not bucket or bucket[-1] != i:
                        bucket.append(i)

    def nearest_on(s, p):
        best = (float('inf'), 0)
        for j, (a, b) in enumerate(zip(s['pts'], s['pts'][1:])):
            ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], p[0] - a[0], p[1] - a[1]
            l2 = ux * ux + uy * uy
            t = max(0.0, min(1.0, (vx * ux + vy * uy) / l2)) if l2 else 0.0
            d = math.hypot(vx - t * ux, vy - t * uy)
            if d < best[0]:
                best = (d, j)
        return best

    # One representative tag set and component per shared geometry.
    geom_info = {}
    for u, v, k, gi, rev, length, osmids, tags in edges:
        if gi not in geom_info:
            geom_info[gi] = {'tags': tags, 'len': length, 'routable': nodes[str(u)][3] == 0 and nodes[str(v)][3] == 0}

    print(f'Matching {len(geoms)} edge geometries to {len(segs)} LION segments…', flush=True)
    matches, stats = {}, {'lion': 0, 'direct': 0, 'none': 0}
    for gi, coords in enumerate(geoms):
        info = geom_info[gi]; tags = info['tags']; kind = edge_kind(tags)
        info['kind'] = kind
        if layered(tags) or kind == 'crossing':
            info['rows'], info['frac'] = {}, 0.0
            continue
        maxd = MAX_DIST['road' if kind == 'road' else kind if kind in MAX_DIST else 'path']
        pts = [si.xy(q) for q in coords]
        lens = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
        total = sum(lens) or info['len']
        n = max(2, math.ceil(total / STEP)); step = total / n
        osm_names = [name_tokens(n) for n in si_list(tags.get('name'))]  # merged edges can carry several street names
        rows, piece, run = {}, 0, 0.0
        for t in range(n):
            target = (t + .5) * step
            while piece < len(lens) - 1 and run + lens[piece] < target:
                run += lens[piece]; piece += 1
            a, b = pts[piece], pts[piece + 1]
            f = (target - run) / lens[piece] if lens[piece] else 0
            p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            eb = bearing(a, b)
            best = None
            for i in set(index.get((int(p[0] // B), int(p[1] // B)), ())):
                s = segs[i]
                d, j = nearest_on(s, p)
                if d > maxd:
                    continue
                ang = angle_diff(eb, s['bearings'][j])
                if ang > MAX_ANGLE:
                    continue  # cross streets at intersections run the other way
                nm = any_compatible(osm_names, s['names'])
                if nm is False:
                    continue  # a differently named parallel street is never borrowed from
                cost = d + ang * .5 - (3 if nm else 0)
                if best is None or cost < best[0]:
                    best = (cost, i, d, ang, nm)
            if best:
                r = rows.setdefault(best[1], [0, 0.0, 0.0, best[4]])
                r[0] += 1; r[1] += best[2]; r[2] += best[3]
        kept = {}
        for i, (cnt, sd, sa, nm) in rows.items():
            overlap = cnt * step
            if overlap >= min(8.0, .4 * total):  # drop slivers that only touch the segment at an intersection
                kept[i] = {'overlap': overlap, 'dist': sd / cnt, 'angle': sa / cnt, 'name': 'match' if nm else 'unknown'}
        info['rows'] = kept
        info['frac'] = min(1.0, sum(r['overlap'] for r in kept.values()) / total) if total else 0.0
    print(f'  matched in {time.time() - t0:.0f}s', flush=True)

    # Scores: LION-borrowed when most of the edge is matched; otherwise measured directly on the OSM geometry.
    keys = si.KEYS
    direct = [gi for gi, info in geom_info.items() if info['frac'] < MIN_LION_SHARE and info['routable']]
    print(f'Measuring {len(direct)} unmatched routable edges directly…', flush=True)
    raw, _ = si.download_sources(args.cache)
    items = [si.make_item(geoms[gi], path=geom_info[gi]['kind'] != 'road', width=None) for gi in direct]
    direct_values = si.Measurer(raw).measure(items, nearest_snap=False) if items else {}
    reference = {k: [f['properties'][k] for f in streets['features']] for k in direct_values}
    direct_scores = si.score_against(reference, direct_values) if items else {}
    direct_pos = {gi: n for n, gi in enumerate(direct)}

    out_geoms = []
    for gi in range(len(geoms)):
        info = geom_info[gi]
        if info['frac'] >= MIN_LION_SHARE:
            rows = info['rows']; total = info['len'] or 1
            dims, cov = [], []
            for j in range(12):
                scored = [(r['overlap'], segs[i]['p'][f'd{j}']) for i, r in rows.items() if segs[i]['p'][f'd{j}'] is not None]
                w = sum(o for o, _ in scored)
                dims.append(round(sum(o * v for o, v in scored) / w) if w else None)
                cov.append(round(min(1.0, w / total), 2))
            quality = 'high' if info['frac'] >= .9 and all(r['angle'] <= 8 for r in rows.values()) else 'medium' if info['frac'] >= .75 else 'low'
            src = 'lion_match'; stats['lion'] += 1; rawv = None
        elif gi in direct_pos:
            n = direct_pos[gi]
            dims = [direct_scores[k][n] for k in keys]
            cov = [1.0 if v is not None else 0.0 for v in dims]
            quality, src = 'direct_measurement', 'direct_osm'; stats['direct'] += 1
            rawv = {k: direct_values[k][n] for k in direct_values}
        else:
            dims, cov, quality, src, rawv = [None] * 12, [0.0] * 12, 'unscored', 'none', None
            stats['none'] += 1
        have = [v for v in dims if v is not None]
        out_geoms.append({'s': dims, 'o': round(sum(have) / len(have)) if have else None, 'c': cov, 'src': src, 'q': quality,
                          'kind': info['kind'], 'frac': round(info['frac'], 2),
                          'm': sorted(segs[i]['p']['id'] for i in info['rows']), **({'raw': rawv} if rawv else {})})

    versions = {'network_version': gmeta['network_version'], 'score_version': smeta['score_version'], 'data_version': smeta['data_version']}
    dim_cov = {k: round(sum(g['c'][j] * geom_info[gi]['len'] for gi, g in enumerate(out_geoms) if geom_info[gi]['routable'])
                        / max(1, sum(geom_info[gi]['len'] for gi in geom_info if geom_info[gi]['routable'])), 3) for j, k in enumerate(keys)}
    meta = {**versions, 'built_at': si.NOW.isoformat(timespec='seconds'), 'keys': keys, 'geometries': len(out_geoms),
            'sources': stats, 'routable_length_coverage_by_dimension': dim_cov,
            'fields': {'s': '12 dimension scores (None = N/A)', 'o': 'overall', 'c': 'per-dimension coverage share of edge length',
                       'src': 'lion_match | direct_osm | none', 'q': 'match quality', 'm': 'matched analysis segment IDs',
                       'frac': 'share of edge length matched to LION', 'raw': 'directly measured sub-indicators'},
            'method': f'LION-borrowed when >= {MIN_LION_SHARE:.0%} of the edge matches (overlap-length weighted mean of segment scores); '
                      'otherwise measured directly on the OSM geometry with the shared indicator code and ranked on the LION reference scale '
                      '(records within distance rather than snapped; sidewalk width and roadway width not measurable on paths, so N/A).'}
    with gzip.open(SCORES + '.tmp', 'wt', encoding='utf-8') as f:
        json.dump({'metadata': meta, 'geoms': out_geoms}, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(SCORES + '.tmp', SCORES)

    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(['mapping_id', 'lion_segment_id', 'analysis_segment_id', 'osm_edge_id', 'graph_u', 'graph_v', 'graph_key', 'osm_way_ids',
                'overlap_length', 'overlap_share', 'match_distance', 'angle_difference', 'name_check', 'match_quality', 'matching_method', 'used_for_scores',
                'network_version', 'score_version', 'data_version'])
    mid = 0
    for u, v, k, gi, rev, length, osmids, tags in edges:
        info = geom_info[gi]
        for i, r in sorted(info['rows'].items(), key=lambda x: segs[x[0]]['p']['id']):
            mid += 1; p = segs[i]['p']
            # Row quality judges the geometric fit; a long edge legitimately splits across several segments.
            q = 'high' if r['angle'] <= 8 and r['dist'] <= (20 if info['kind'] == 'sidewalk' else 6) else 'medium' if r['angle'] <= 14 else 'low'
            w.writerow([mid, p['source_segment_id'], p['id'], f'{u}-{v}-{k}', u, v, k, ' '.join(map(str, osmids)),
                        round(r['overlap'], 1), round(r['overlap'] / (info['len'] or 1), 2), round(r['dist'], 1), round(r['angle'], 1), r['name'], q,
                        {'sidewalk': 'sidewalk_offset', 'road': 'centerline_overlap'}.get(info['kind'], 'path_overlap') + '+direction+name+layer',
                        info['frac'] >= MIN_LION_SHARE, *versions.values()])
    with gzip.open(MAPPING + '.tmp', 'wt', encoding='utf-8', newline='') as f:
        f.write(buf.getvalue())
    os.replace(MAPPING + '.tmp', MAPPING)
    print(json.dumps(stats), 'mapping rows', mid, json.dumps(dim_cov), f'{time.time() - t0:.0f}s')


def any_compatible(osm_names, lion_names):
    """True if any of the edge's names agrees, False only if every name conflicts, None if nothing can be compared."""
    results = [names_compatible(n, lion_names) for n in osm_names]
    return True if True in results else None if None in results or not results else False


if __name__ == '__main__':
    sys.exit(main())
