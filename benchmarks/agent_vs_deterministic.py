#!/usr/bin/env python3
"""Phase 0 baseline benchmark: the real deterministic /api/recommend/food pipeline vs the real Agent Runtime,
on the same set of requests, run in-process (no HTTP layer) against this machine's real local data.

Honesty rule this script follows: if OPENAI_API_KEY is not set, it does NOT fabricate agent-path numbers — it
runs the deterministic baseline for real, and marks the agent path explicitly "blocked: OPENAI_API_KEY not set"
in the output. Run again with a real key exported to get real agent numbers.

Usage: python3 benchmarks/agent_vs_deterministic.py
Writes: benchmarks/baseline.json
"""
import json
import os
import resource
import statistics
import sys
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUESTS = [
    {'request': 'find a burger place near me', 'lat': 40.758, 'lon': -73.9855, 'item': 'burger'},
    {'request': 'I want a cheap slice of pizza nearby', 'lat': 40.7484, 'lon': -73.9857, 'item': 'pizza'},
    {'request': 'find a coffee shop with vegan options near Union Square', 'lat': 40.7359, 'lon': -73.9911, 'item': 'vegan'},
    {'request': 'a quiet cafe within a 10 minute walk', 'lat': 40.7614, 'lon': -73.9776, 'item': None},
    {'request': 'bakery with gluten free bread nearby', 'lat': 40.7295, 'lon': -73.9965, 'item': 'gluten free'},
]


def rss_mb():
    # macOS reports ru_maxrss in bytes; Linux reports it in KiB.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0 if sys.platform == 'darwin' else 1024.0)


def pctl(values, p):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def bench_deterministic():
    from routing.engine import get_planner
    from routing.recommend import recommend_food
    planner = get_planner()
    latencies_ms = []
    for req in REQUESTS:
        doc = {'near': {'lat': req['lat'], 'lon': req['lon']}, 'item': req['item']}
        t0 = time.monotonic()
        try:
            recommend_food(planner, doc)
        except Exception as e:
            print(f'  deterministic request failed: {e}', file=sys.stderr)
        latencies_ms.append((time.monotonic() - t0) * 1000)
    # ru_maxrss is a lifetime peak, not a point-in-time sample, so only a single post-phase reading is meaningful.
    return {'n': len(REQUESTS), 'p50_ms': pctl(latencies_ms, 50), 'p95_ms': pctl(latencies_ms, 95),
            'mean_ms': statistics.mean(latencies_ms), 'peak_rss_mb_so_far': round(rss_mb(), 1)}


def bench_agent():
    if not os.environ.get('OPENAI_API_KEY'):
        return {'blocked': True, 'reason': 'OPENAI_API_KEY not set in this environment; '
                'no agent-path latency/cost numbers were fabricated. Export a real key and re-run.'}
    from agent.runtime import run_food_stop_agent
    latencies_ms, statuses = [], []
    for req in REQUESTS:
        t0 = time.monotonic()
        result = run_food_stop_agent(req['request'])
        latencies_ms.append((time.monotonic() - t0) * 1000)
        statuses.append(result['status'])
    return {'n': len(REQUESTS), 'p50_ms': pctl(latencies_ms, 50), 'p95_ms': pctl(latencies_ms, 95),
            'mean_ms': statistics.mean(latencies_ms), 'statuses': statuses, 'peak_rss_mb_so_far': round(rss_mb(), 1)}


def bench_admission_concurrency():
    """Real concurrency sweep against the actual Admission gate used by /api/recommend/food and friends."""
    from routing.capacity import Admission
    results = {}
    for n in (1, 5, 10, 20):
        gate = Admission(active_limit=2, queue_limit=3)
        accepted = sum(1 for _ in range(n) if gate.acquire(timeout=0))
        for _ in range(accepted):
            gate.release()
        results[str(n)] = {'attempted': n, 'accepted_immediately': accepted, 'rejected': n - accepted}
    return results


def main():
    print('Running deterministic baseline (real local data, real planner)...')
    deterministic = bench_deterministic()
    print('Running agent path...')
    agent = bench_agent()
    print('Running admission/concurrency sweep (real Admission gate, not simulated)...')
    concurrency = bench_admission_concurrency()
    out = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'requests': REQUESTS,
           'deterministic_pipeline': deterministic, 'agent_runtime': agent, 'admission_concurrency_sweep': concurrency,
           'note': 'LLM-enabled-vs-fallback comparison is the deterministic_pipeline (always real) vs agent_runtime '
                   '(real only when OPENAI_API_KEY is set; otherwise honestly marked blocked, not estimated).'}
    out_path = pathlib.Path(__file__).parent / 'baseline.json'
    out_path.write_text(json.dumps(out, indent=2))
    print(f'Wrote {out_path}')
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
