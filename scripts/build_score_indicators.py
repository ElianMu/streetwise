#!/usr/bin/env python3
"""Write data/pedestrian/score-indicators.json: what each of the 12 route scores is made of.

A small static copy of the indicator definitions the ROUTER's scores are built with, so the route explanation
("Why this route?") and the walk-priority tooltips can name the real indicators, sources and time windows.

Since 2026-11-14 the router uses the street scores of the Explore Urban Data map (scripts/dimensions/, transferred to
the routing edges by scripts/transfer_dimension_scores.py), so the definitions are copied from that build's manifest,
data/dimensions/manhattan/manifest.json. Nothing is defined here: labels, units, methods and roles are copied, never
rewritten. Only indicators that are computed and scored are given role "up"/"down"; specified-but-unavailable,
validation-only and context-only indicators are listed with role "context" and their status, and never described as
part of a score.

The file carries the same score_version as data/pedestrian/edge-scores.json.gz; the browser shows it only when it
matches the score_version of the route on screen, and tests/test_score_indicators.py fails if it goes stale.

Run after scripts/transfer_dimension_scores.py:   python3 scripts/build_score_indicators.py
"""
import gzip
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MANIFEST = ROOT / 'data' / 'dimensions' / 'manhattan' / 'manifest.json'
EDGES = ROOT / 'data' / 'pedestrian' / 'edge-scores.json.gz'
OUT = ROOT / 'data' / 'pedestrian' / 'score-indicators.json'


def build():
    from routing.engine import DIMENSIONS
    m = json.loads(MANIFEST.read_text())
    edge = json.load(gzip.open(EDGES, 'rt', encoding='utf-8'))['metadata']
    assert [d['label'] for d in m['dimensions']] == list(DIMENSIONS) and len(DIMENSIONS) == 12
    assert edge['score_version'] == m['calculation_version'], 'run scripts/transfer_dimension_scores.py first'
    by_key = {i['key']: i for i in m['indicators']}
    labels = {k: v['label'] for k, v in m['sources'].items()}
    dims = {}
    for d in m['dimensions']:
        rows = []
        for key in d['indicators']:
            i = by_key[key]
            scored = key in d['available_indicators'] and i['role'] in ('up', 'down')
            source = '+'.join(i['db'])
            labels.setdefault(source, ' · '.join(m['sources'][s]['label'] for s in i['db']))
            rows.append({'key': key, 'label': i['label'], 'unit': i['unit'], 'method': i['method'].rstrip('. '), 'source': source,
                         'role': i['role'] if scored else 'context', 'status': i['status']})
        dims[d['label']] = rows
    # Where the route scores rest on fewer indicators than the street scores: computed by the transfer, only quoted here.
    fewer = {d['label']: edge['indicator_basis'][d['key']]['routable_length_with_fewer'] for d in m['dimensions']}
    partial = [f"{name} {round(share * 100)}%" for name, share in fewer.items() if share >= 0.01]
    note = m['value_note'] + (' On crossings, park paths, bridges and streets with a missing record, a score rests on fewer indicators than '
                              'listed, because the others were not measured there (share of routable length: ' + ', '.join(partial) + ').' if partial else '')
    return {
        'score_version': edge['score_version'], 'data_version': edge['data_version'], 'retrieved_at': m['windows']['retrieved_at'],
        'value_note': note, 'score_method': m['score_method'],
        'windows': {k: v for k, v in m['windows'].items() if k != 'retrieved_at'},
        'source_labels': labels,
        'record_counts': {k: v['qa']['records_kept'] for k, v in m['sources'].items() if isinstance(v.get('qa'), dict) and 'records_kept' in v['qa']},
        'fewer_indicators_share_of_routable_length': fewer,
        'dimensions': dims,
    }


if __name__ == '__main__':
    doc = build()
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n')
    print(f"wrote {OUT.relative_to(ROOT)} · {doc['score_version']} · {sum(1 for v in doc['dimensions'].values() for x in v if x['role'] in ('up', 'down'))} scored indicators")
