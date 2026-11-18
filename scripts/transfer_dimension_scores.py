#!/usr/bin/env python3
"""Give the routing edges the SAME 12 dimension scores the Explore Urban Data map shows.

Run: python3 scripts/transfer_dimension_scores.py            (standard library only, no network)
Reads  data/dimensions/manhattan/{manifest,segments,indicators}  the street scores of the Explore map
                                                                 (scripts/dimensions/, build "strollane-12x24-v1")
       data/pedestrian/street_osm_edge_mapping.csv.gz            which street segments each OSM edge runs along, and
                                                                 for how many metres (scripts/match_lion_osm.py)
       data/pedestrian/edge-scores.json.gz                       the previous file: edge kind, match share, matched
                                                                 segments and, for edges measured directly, raw values
       data/pedestrian/manhattan-walk-graph.json.gz              edge lengths, to report coverage of routable length
Writes data/pedestrian/edge-scores.json.gz                       same fields as before, scores from the map build
       data/pedestrian/street_osm_edge_mapping.csv.gz            same rows; only score_version / data_version change

Nothing about the matching changes: which edge follows which street segment, and for how long, is taken as it is.
Nothing about the 12 dimensions changes either: names, order, indicator definitions and the equal-weight rule all come
from the map build's manifest.

Two kinds of edges:

* Edges matched to street segments (src "lion_match"): each dimension is the overlap-length weighted mean of the map
  build's segment scores, the same formula scripts/match_lion_osm.py used with the earlier street scores.
  `--verify-previous` recomputes the PREVIOUS file from the previous street scores with this code, to show the transfer
  itself is faithful. The mapping table stores overlaps to 0.1 m, so a value that sat on a rounding boundary can come
  out 1 point away (0.5 % of values on 2026-11-14); nothing may differ by more.

* Edges measured directly on their OSM geometry (src "direct_osm": crossings, park paths, bridges, unmatched streets).
  Their raw indicator values come from two measurements on the edge's own geometry: the 15 indicators of
  scripts/streetwise_indicators.py (2026-10-23), and four indicators of the map build measured with the map build's
  own functions by scripts/measure_direct_edges.py (walking distance to seating, walking-network detour, crime-report
  proximity, walking distance to waterfront). Each value takes the percentile it would hold among the map build's
  street segments (lowest rank for ties, "lower is better" reversed), and a dimension is the equal-weight mean of the
  indicators available on that edge, which is the map build's own rule. An indicator that was not measured on an edge
  is absent there: no value is estimated, borrowed or filled in. That is always the case for ramp coverage, which is
  defined on the LION end nodes of a street segment and so does not exist for a crossing or a park path.
  `indicator_basis` in the metadata reports, per dimension, how much routable length is scored with every computed
  indicator and how much with fewer.
"""
import argparse
import bisect
import csv
import datetime
import gzip
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, 'data', *a)
GRAPH, MAPPING, SCORES = P('pedestrian', 'manhattan-walk-graph.json.gz'), P('pedestrian', 'street_osm_edge_mapping.csv.gz'), P('pedestrian', 'edge-scores.json.gz')
MANIFEST, SEGMENTS, INDICATORS = P('dimensions', 'manhattan', 'manifest.json'), P('dimensions', 'manhattan', 'segments.geojson'), P('dimensions', 'manhattan', 'indicators.json')
LEGACY_STREETS = P('manhattan-streets.json')
DIRECT_EXTRA = P('pedestrian', 'direct-edge-indicators.json.gz')  # scripts/measure_direct_edges.py
MIN_LION_SHARE = 0.6  # same threshold as scripts/match_lion_osm.py; only used to cross-check the previous file

# Raw values stored on directly measured edges use the earlier script's units; the map build stores these two as a
# 0–1 share instead of 0–100 %. Same quantity, so the conversion is exact.
DIRECT_UNIT = {'park_pct': 0.01, 'sidewalk_pct': 0.01}


def load_overlaps(graph):
    """{geometry index: {analysis segment id: overlap metres}} from the mapping table (directed twins repeat a row)."""
    edge_geom = {f'{u}-{v}-{k}': gi for u, v, k, gi, *_ in graph['edges']}
    rows = list(csv.DictReader(io.StringIO(gzip.open(MAPPING, 'rt', encoding='utf-8', newline='').read())))
    out = {}
    for r in rows:
        out.setdefault(edge_geom[r['osm_edge_id']], {})[r['analysis_segment_id']] = float(r['overlap_length'])
    return out, rows


def matched_scores(overlaps, seg_scores, length):
    """Overlap-length weighted mean per dimension and the share of the edge's length that has a score."""
    dims, cov = [], []
    total = length or 1
    for j in range(12):
        scored = [(o, seg_scores[sid][j]) for sid, o in overlaps.items() if seg_scores[sid][j] is not None]
        w = sum(o for o, _ in scored)
        dims.append(round(sum(o * v for o, v in scored) / w) if w else None)
        cov.append(round(min(1.0, w / total), 2))
    return dims, cov


def direct_scores(raw, scored_by_dim, reference):
    """Dimension scores of a directly measured edge on the map build's reference scale, plus how many indicators each used."""
    dims, used = [], []
    for inds in scored_by_dim:
        got = []
        for key, role in inds:
            v = raw.get(key)
            if v is None or key not in reference:
                continue
            ref = reference[key]
            pct = bisect.bisect_left(ref, v * DIRECT_UNIT.get(key, 1)) / max(len(ref) - 1, 1) * 100
            got.append(round(100 - pct if role == 'down' else pct, 1))
        dims.append(round(sum(got) / len(got)) if got else None)
        used.append(len(got))
    return dims, used


def verify_previous(graph, prev, overlaps):
    """Recompute the previous edge scores from the previous street scores: identical, or 1 point off by rounding."""
    streets = json.load(open(LEGACY_STREETS, encoding='utf-8'))
    if streets['metadata']['score_version'] != prev['metadata']['score_version']:
        sys.exit('--verify-previous needs the edge scores that were built from data/manhattan-streets.json (run it before transferring).')
    seg = {f['properties']['id']: [f['properties'][f'd{j}'] for j in range(12)] for f in streets['features']}
    length = {gi: ln for u, v, k, gi, rev, ln, *_ in graph['edges']}
    checked = values = off_by_one = worse = 0
    for gi, g in enumerate(prev['geoms']):
        if g['src'] != 'lion_match':
            continue
        dims, _ = matched_scores(overlaps.get(gi, {}), seg, length[gi])
        checked += 1
        for a, b in zip(dims, g['s']):
            values += 1
            if a != b:
                if a is not None and b is not None and abs(a - b) == 1:
                    off_by_one += 1
                else:
                    worse += 1
    print(f'verify-previous: {checked} matched edges, {values} dimension values recomputed; {values - off_by_one - worse} identical, '
          f'{off_by_one} differ by 1 point (rounding), {worse} differ by more')
    return worse == 0 and off_by_one <= values * 0.01


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify-previous', action='store_true', help='only check that this code reproduces the previous file from the previous street scores')
    args = ap.parse_args()
    graph = json.load(gzip.open(GRAPH, 'rt', encoding='utf-8'))
    prev = json.load(gzip.open(SCORES, 'rt', encoding='utf-8'))
    overlaps, mapping_rows = load_overlaps(graph)
    if args.verify_previous:
        return 0 if verify_previous(graph, prev, overlaps) else 1

    manifest = json.load(open(MANIFEST, encoding='utf-8'))
    keys = [d['key'] for d in manifest['dimensions']]
    if keys != prev['metadata']['keys'] or graph['metadata']['network_version'] != prev['metadata']['network_version']:
        sys.exit('dimension order or network version differs from the existing edge scores; rebuild the matching first.')
    feats = json.load(open(SEGMENTS, encoding='utf-8'))['features']
    seg = {f['properties']['id']: [f['properties'][d['prop']] for d in manifest['dimensions']] for f in feats}
    seg_n = {f['properties']['id']: [f['properties'][d['count_prop']] for d in manifest['dimensions']] for f in feats}  # indicators behind each segment score
    ind = json.load(open(INDICATORS, encoding='utf-8'))
    if ind['calculation_version'] != manifest['calculation_version']:
        sys.exit('indicators.json and manifest.json come from different builds.')
    role = {i['key']: i['role'] for i in manifest['indicators']}
    computed = [[(k, role[k]) for k in d['available_indicators'] if role[k] in ('up', 'down')] for d in manifest['dimensions']]
    reference = {k: sorted(v for v in ind['raw'][k] if v is not None) for inds in computed for k, _ in inds}

    # Indicators of the map build measured on the directly measured edges themselves (scripts/measure_direct_edges.py).
    # Used only when they were measured on this network with this map build; otherwise those indicators stay absent.
    extra, extra_keys = {}, []
    if os.path.exists(DIRECT_EXTRA):
        doc = json.load(gzip.open(DIRECT_EXTRA, 'rt', encoding='utf-8'))
        if doc['network_version'] == graph['metadata']['network_version'] and doc['map_build'] == manifest['calculation_version']:
            extra_keys = sorted(doc['values'])
            for n, gi in enumerate(doc['geometry_index']):
                extra[gi] = {k: doc['values'][k][n] for k in extra_keys}
        else:
            print('direct-edge-indicators.json.gz is from another network or map build: ignored. Rerun scripts/measure_direct_edges.py.')

    nodes = graph['nodes']
    info = {}
    for u, v, k, gi, rev, length, osmids, tags in graph['edges']:
        info.setdefault(gi, (length, nodes[str(u)][3] == 0 and nodes[str(v)][3] == 0))
    routable_len = sum(ln for ln, ok in info.values() if ok) or 1

    out, stats = [], {'lion': 0, 'direct': 0, 'none': 0}
    full = [0.0] * 12      # routable metres scored with every computed indicator of the dimension
    partial = [0.0] * 12   # routable metres scored with fewer
    for gi, g in enumerate(prev['geoms']):
        length, routable = info[gi]
        if g['src'] == 'lion_match':
            missing = [sid for sid in overlaps.get(gi, {}) if sid not in seg]
            if missing or sorted(overlaps.get(gi, {})) != g['m']:
                sys.exit(f'geometry {gi}: mapping table and edge scores disagree about the matched segments.')
            dims, cov = matched_scores(overlaps[gi], seg, length)
            used = [min((seg_n[sid][j] for sid in overlaps[gi] if seg[sid][j] is not None), default=0) for j in range(12)]
            stats['lion'] += 1
        elif g['src'] == 'direct_osm':
            if gi in extra:
                g = {**g, 'raw': {**g['raw'], **extra[gi]}}
            dims, used = direct_scores(g['raw'], computed, reference)
            cov = [1.0 if v is not None else 0.0 for v in dims]
            stats['direct'] += 1
        else:
            dims, cov, used = [None] * 12, [0.0] * 12, [0] * 12
            stats['none'] += 1
        if routable:
            for j in range(12):
                if dims[j] is not None:
                    share = length * cov[j]
                    if used[j] == len(computed[j]):
                        full[j] += share
                    else:
                        partial[j] += share
        have = [v for v in dims if v is not None]
        out.append({**g, 's': dims, 'o': round(sum(have) / len(have)) if have else None, 'c': cov})

    data_version = (manifest.get('windows', {}).get('retrieved_at') or manifest['built_at'])[:10]  # as explore-map.js reads it
    versions = {'network_version': graph['metadata']['network_version'], 'score_version': manifest['calculation_version'], 'data_version': data_version}
    meta = {**versions, 'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'keys': keys, 'geometries': len(out), 'sources': stats,
            'routable_length_coverage_by_dimension': {k: round((full[j] + partial[j]) / routable_len, 3) for j, k in enumerate(keys)},
            'indicator_basis': {k: {'computed_indicators': [x for x, _ in computed[j]],
                                    'routable_length_with_all': round(full[j] / routable_len, 3),
                                    'routable_length_with_fewer': round(partial[j] / routable_len, 3)} for j, k in enumerate(keys)},
            'direct_edge_indicators': {'file': 'data/pedestrian/direct-edge-indicators.json.gz', 'indicators': extra_keys,
                                       'not_measured_on_direct_edges': sorted({k for inds in computed for k, _ in inds} - set(extra_keys) - {k for g in out if g['src'] == 'direct_osm' for k in g['raw']})},
            'street_scores': {'spec_version': manifest['spec_version'], 'calculation_version': manifest['calculation_version'],
                              'built_at': manifest['built_at'], 'segments': manifest['segments'], 'files': 'data/dimensions/manhattan/'},
            'fields': prev['metadata']['fields'],
            'method': f'Street scores are those of the Explore Urban Data map ({manifest["calculation_version"]}). Edges of which at least '
                      f'{MIN_LION_SHARE:.0%} follows street segments take the overlap-length weighted mean of the segment scores. Other routable '
                      'edges (crossings, park paths, bridges) keep the raw indicator values measured directly on their OSM geometry and are '
                      'ranked on the same street reference scale; indicators that were not measured on such an edge are absent, never '
                      'estimated, and the dimension is the mean of those available (see indicator_basis).'}
    with gzip.open(SCORES + '.tmp', 'wt', encoding='utf-8') as f:
        json.dump({'metadata': meta, 'geoms': out}, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(SCORES + '.tmp', SCORES)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(mapping_rows[0].keys()), lineterminator='\r\n')
    w.writeheader()
    for r in mapping_rows:
        w.writerow({**r, 'score_version': versions['score_version'], 'data_version': versions['data_version']})
    with gzip.open(MAPPING + '.tmp', 'wt', encoding='utf-8', newline='') as f:
        f.write(buf.getvalue())
    os.replace(MAPPING + '.tmp', MAPPING)
    print(json.dumps({'versions': versions, 'sources': stats, 'coverage': meta['routable_length_coverage_by_dimension']}))
    print(json.dumps(meta['indicator_basis'], indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
