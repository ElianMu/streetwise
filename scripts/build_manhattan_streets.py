"""Score every Manhattan street centerline segment on raw proxies for the 12 Streetwise dimensions.

Run: python3 scripts/build_manhattan_streets.py [--refresh] [--cache DIR]
Writes data/manhattan-streets.json (the Explore Urban Data layer and the reference scale for OSM edge
scores). Standard library only; indicator definitions live in streetwise_indicators.py. Nothing is
estimated or filled in. Percentiles are a relative ranking inside Manhattan, not calibrated scores.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streetwise_indicators as si


def lion_segments(raw):
    """NYC LION centerline parts pedestrians can use (no expressways, ramps, bridges, tunnels, ferries)."""
    skip_types, path_types = {2, 3, 4, 9, 13, 14}, {6, 7}  # park paths and step streets have no curbside sidewalk
    segs, misplaced = [], []
    w, s_, e, n = si.BOROUGH_BOUNDS
    for p, rw, i, line in si.lion_lines(raw):
        if rw in skip_types:
            continue
        if not all(w <= x <= e and s_ <= y <= n for x, y in line):
            misplaced.append(p.get('physicalid'))  # a borocode-1 record drawn outside Manhattan is a source error
            continue
        s = si.make_item(line, name=p.get('st_label') or p.get('st_name') or '', width=p.get('st_width') or None,
                         rw=rw, path=rw in path_types, physicalid=p.get('physicalid'), fid=p.get('FID'), part=i)
        if s['len'] >= 1:
            s['pid'] = f"MN-{int(s['physicalid'])}" if s['physicalid'] else f"MN-FID{s['fid']}"
            segs.append(s)
    # Stable ID: LION physical segment ID (persists across NYC releases); records sharing one get a suffix
    # ordered by their geometry, so the same street piece keeps the same ID between rebuilds.
    groups = {}
    for s in segs:
        groups.setdefault(s['pid'], []).append(s)
    for pid, group in groups.items():
        group.sort(key=lambda s: (round(s['line'][0][0], 6), round(s['line'][0][1], 6), round(s['line'][-1][0], 6), round(s['line'][-1][1], 6), len(s['line'])))
        for k, s in enumerate(group):
            s['id'] = pid if len(group) == 1 else f'{pid}-{k + 1}'
    return segs, misplaced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default=os.path.join(si.ROOT, 'data', 'cache', 'sources'), help='raw source cache, shared with match_lion_osm.py')
    ap.add_argument('--refresh', action='store_true', help='download every source again instead of using the cache')
    args = ap.parse_args()
    raw, windows = si.download_sources(args.cache, args.refresh)
    segs, misplaced = lion_segments(raw)
    print(f'  {len(segs)} street segments', flush=True)
    print('Measuring segments…', flush=True)
    values = si.Measurer(raw).measure(segs)
    scores = si.score_reference(values)
    version = si.score_version()
    data_version = si.NOW.strftime('%Y-%m-%d')

    features = []
    for i, s in enumerate(segs):
        dims = [scores[d][i] for d in si.KEYS]
        have = [v for v in dims if v is not None]
        props = {'id': s['id'], 'source_segment_id': int(s['physicalid']) if s['physicalid'] else None, 'lion_part': s['part'],
                 'name': s['name'], 'length_m': round(s['len'], 1),
                 'overall': round(sum(have) / len(have)) if have else None, 'coverage': len(have)}
        props.update({f'd{j}': v for j, v in enumerate(dims)})
        props.update({k: values[k][i] for k in values})
        features.append({'type': 'Feature', 'properties': props,
                         'geometry': {'type': 'LineString', 'coordinates': [[round(a, 5), round(b, 5)] for a, b in s['line']]}})
    ids = [f['properties']['id'] for f in features]
    assert len(ids) == len(set(ids)), 'segment IDs must be unique'

    meta = {
        'retrieved_at': si.NOW.isoformat(timespec='seconds'), 'data_version': data_version, 'score_version': version,
        'segments': len(features), 'keys': si.KEYS,
        'indicators': {d: [{'key': k, 'label': lb, 'unit': u, 'method': m, 'source': src, 'role': role} for k, lb, u, m, src, role in dim] for d, dim in si.INDICATORS.items()},
        'source_labels': si.SOURCE_LABELS, 'score_method': si.SCORE_METHOD,
        'id_scheme': 'id = analysis segment ID: "MN-" + LION physicalid, with "-n" when several LION records share one physicalid (ordered by geometry). source_segment_id = LION physicalid; lion_part = part index of a multi-part LION record.',
        'study_area': 'NYC Street Centerline, borocode 1 (Manhattan incl. Roosevelt & Randalls Is.); bridges, tunnels, ramps and ferry routes excluded',
        'value': 'Scores are relative ranks within Manhattan, NOT calibrated experience scores.',
        'record_counts': {k: len(v) for k, v in raw.items()},
        'excluded_misplaced_lion_physicalids': misplaced,
        'trees_inventory_updated': (si.get(si.SOURCES['trees'], {'$select': 'max(updateddate) AS d'})[0].get('d') or '')[:10],
        'sources': si.SOURCES, **windows,
    }
    out = {'type': 'FeatureCollection', 'metadata': meta, 'features': features}
    path = os.path.join(si.ROOT, 'data', 'manhattan-streets.json')
    json.dump(out, open(path + '.tmp', 'w'), separators=(',', ':'), ensure_ascii=False)
    os.replace(path + '.tmp', path)  # atomic: the server never serves a half-written file
    print(f'Wrote {path}: {len(features)} segments, {os.path.getsize(path)/1e6:.1f} MB', flush=True)


if __name__ == '__main__':
    sys.exit(main())
