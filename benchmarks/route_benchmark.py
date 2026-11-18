#!/usr/bin/env python3
"""Route benchmark: shortest path vs the preference route vs the best other candidate, on the real routing engine.

For every trip in benchmarks/od_pairs.json and every experience dimension (one preference at a time, weight 80 —
the weight the quick-preference chips and the walk presets set), this calls routing.engine.RoutePlanner.plan()
in-process and records, from the engine's own response:

  A  shortest route                 distance, target-dimension score
  B  preference route               the feasible route the engine ranks first: distance, detour %, target score,
                                    coverage of that dimension, share of its length shared with A, QA status
  C  alternative                    the next feasible candidate that is neither A nor B (when one exists)

Honesty rules:
  - Nothing here asserts or assumes that B is better than A. "Same as shortest" and zero or negative gains are
    reported as they come out.
  - Scores are the router's own street scores (ranks within Manhattan, see README). A gain shows that the engine
    moved its own metric, not that a walker would notice the difference. That needs user validation.
  - The trip set is hand-picked (19 trips), not a random sample.
  - No weather, no crime/waterfront preference: only the 12 static dimensions.

Deterministic for a given network_version + score_version: the search has no randomness, so two runs give the same
`runs` list (tests/test_route_benchmark.py checks this).

Usage:  python3 benchmarks/route_benchmark.py            # writes benchmarks/route_benchmark.json + ROUTE_BENCHMARK.md
        python3 benchmarks/route_benchmark.py --no-write # print the summary only
"""
import argparse
import datetime
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from routing.engine import DIMENSIONS, RoutingError, get_planner, overlap  # noqa: E402

WEIGHT = 80                     # mobile-ui.js QUICK_WEIGHT
CONSTRAINTS = {'max_minutes': 100, 'max_detour_pct': 25, 'avoid_detours': True}   # the app's defaults
CLAIM_POINTS = 5                # route-story.js STORY.MORE: below this the app says "similar", not "greener"
PRESETS = {'Nature': 'Nature', 'Quiet & Relax': 'Quiet & Relax'}                   # dimensions broken down by trip length in the report
BUCKETS = (('short (< 1.5 km)', 0, 1500), ('medium (1.5–3 km)', 1500, 3000), ('long (≥ 3 km)', 3000, 10 ** 9))


def bucket(m):
    return next(name for name, lo, hi in BUCKETS if lo <= m < hi)


def brief(route, dim, shortest):
    return {'objective': route['objective'], 'route_signature': route['route_signature'], 'distance_m': route['distance_m'],
            'detour_pct': route['detour_percentage'], 'score': route['dimension_scores'][dim],
            'coverage': route['data_coverage']['by_dimension'][dim],
            'overlap_with_shortest': round(overlap(route, shortest), 3),
            'qa_status': route['validation']['status'], 'blocking_issues': len(route['validation']['blocking_issues'])}


def run_one(planner, pair, dim):
    o, d = pair['o'], pair['d']
    try:
        res = planner.plan({'lon': o[0], 'lat': o[1]}, {'lon': d[0], 'lat': d[1]},
                           {'weights': {dim: WEIGHT}, 'directions': {}}, dict(CONSTRAINTS))
    except RoutingError as e:
        return {'pair': pair['id'], 'area': pair['area'], 'dimension': dim, 'error': str(e)}
    routes = res['routes']
    shortest = next(r for r in routes if r['objective'] == 'shortest')
    feasible = sorted((r for r in routes if r['constraints']['feasible']), key=lambda r: r['rank'])
    top = feasible[0] if feasible else None
    alt = next((r for r in feasible if r is not top and r is not shortest), None)
    out = {'pair': pair['id'], 'area': pair['area'], 'dimension': dim, 'length_bucket': bucket(shortest['distance_m']),
           'candidates': len(routes), 'feasible': len(feasible), 'shortest': brief(shortest, dim, shortest),
           'preference': brief(top, dim, shortest) if top else None, 'alternative': brief(alt, dim, shortest) if alt else None}
    if top:
        a, b = out['shortest']['score'], out['preference']['score']
        out['same_as_shortest'] = top is shortest
        out['gain_points'] = None if a is None or b is None else round(b - a, 1)
    return out


def run(pairs=None, dimensions=None):
    planner = get_planner()
    pairs = pairs or json.loads((ROOT / 'benchmarks' / 'od_pairs.json').read_text())['pairs']
    runs = [run_one(planner, p, dim) for p in pairs for dim in (dimensions or DIMENSIONS)]
    return {'network_version': planner.net.network_version, 'score_version': planner.net.score_version,
            'weight': WEIGHT, 'constraints': CONSTRAINTS, 'claim_points': CLAIM_POINTS, 'pairs': len(pairs), 'runs': runs}


def summarise(rows):
    """Aggregate figures for a list of runs; None-safe (a dimension can be N/A on a route)."""
    ok = [r for r in rows if r.get('preference') and r.get('gain_points') is not None]
    if not ok:
        return {'runs': len(rows), 'scored': 0}
    gains = [r['gain_points'] for r in ok]
    return {'runs': len(rows), 'scored': len(ok),
            'same_as_shortest': sum(r['same_as_shortest'] for r in ok),
            'mean_gain': round(statistics.mean(gains), 1), 'median_gain': round(statistics.median(gains), 1),
            'gain_at_least_claim': sum(g >= CLAIM_POINTS for g in gains), 'negative_gain': sum(g < 0 for g in gains),
            'mean_detour_pct': round(statistics.mean(r['preference']['detour_pct'] for r in ok), 1),
            'max_detour_pct': max(r['preference']['detour_pct'] for r in ok),
            'mean_overlap_with_shortest': round(statistics.mean(r['preference']['overlap_with_shortest'] for r in ok), 2),
            'mean_coverage': round(statistics.mean(r['preference']['coverage'] for r in ok), 2),
            'blocking_issues': sum(r['preference']['blocking_issues'] for r in ok)}


def summary(result):
    runs = result['runs']
    by_dim = {d: summarise([r for r in runs if r['dimension'] == d]) for d in DIMENSIONS if any(r['dimension'] == d for r in runs)}
    by_bucket = {name: summarise([r for r in runs if r.get('length_bucket') == name]) for name, *_ in BUCKETS}
    presets = {name: {b: summarise([r for r in runs if r['dimension'] == dim and r.get('length_bucket') == b]) for b, *_ in BUCKETS}
               for name, dim in PRESETS.items()}
    return {'all': summarise(runs), 'errors': sum('error' in r for r in runs), 'by_dimension': by_dim,
            'by_length': by_bucket, 'presets_by_length': presets}


def markdown(result, s):
    def row(label, x):
        if not x.get('scored'):
            return f"| {label} | {x['runs']} | – | – | – | – | – | – |"
        return (f"| {label} | {x['scored']} | {x['mean_gain']:+.1f} | {x['median_gain']:+.1f} | {x['gain_at_least_claim']}/{x['scored']} | "
                f"{x['same_as_shortest']}/{x['scored']} | {x['mean_detour_pct']}% | {x['mean_overlap_with_shortest']:.2f} |")
    head = ('| | Runs | Mean gain (pts) | Median gain | Gain ≥ %d pts | Same as shortest | Mean detour | Mean overlap with shortest |\n'
            '|---|---|---|---|---|---|---|---|') % result['claim_points']
    lines = ['# Route benchmark — shortest vs preference route', '',
             f"Generated {result['generated_at']} by `benchmarks/route_benchmark.py` · network `{result['network_version']}` · "
             f"scores `{result['score_version']}` · {result['pairs']} trips × {len(s['by_dimension'])} single-dimension preferences "
             f"(weight {result['weight']}) · limits: {result['constraints']['max_minutes']} min, {result['constraints']['max_detour_pct']}% detour.", '',
             '"Gain" = the preference route\'s score on the requested dimension minus the shortest route\'s score (0–100 ranks within '
             f"Manhattan). {result['claim_points']} points is the smallest difference the app describes in words (`route-story.js`). "
             'These are the router\'s own scores: a gain shows the engine moved its metric, **not** that a walker perceives the '
             'difference. The trip set is hand-picked, not a random sample.', '',
             '## By dimension', '', head] + [row(d, x) for d, x in s['by_dimension'].items()] + [row('**All**', s['all'])]
    lines += ['', '## By trip length (shortest-path distance)', '', head] + [row(b, x) for b, x in s['by_length'].items()]
    for name, per in s['presets_by_length'].items():
        lines += ['', f"## {name} ({PRESETS[name]}) by trip length", '', head] + [row(b, x) for b, x in per.items()]
    lines += ['', f"Routing errors: {s['errors']}. Blocking QA issues on preference routes: {s['all'].get('blocking_issues', 0)}. "
              f"Preference routes scoring below the shortest route on the requested dimension: {s['all'].get('negative_gain', 0)}.", '']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--no-write', action='store_true', help='print the summary without writing files')
    args = ap.parse_args()
    result = run()
    result['generated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    s = summary(result)
    result['summary'] = s
    md = markdown(result, s)
    print(md)
    if not args.no_write:
        (ROOT / 'benchmarks' / 'route_benchmark.json').write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
        (ROOT / 'benchmarks' / 'ROUTE_BENCHMARK.md').write_text(md)


if __name__ == '__main__':
    main()
