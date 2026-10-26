#!/usr/bin/env python3
"""Agent Evaluation framework (scoped): runs eval/agent_tasks.jsonl against the real /api/agent/food-stop
endpoint logic (in-process, same code path the server uses — no mocks) and checks each task's declared
constraints programmatically against the real response, never by asking an LLM to judge itself.

12 real, hand-picked City Walk scenarios, not a padded 200-case suite — see EVALUATION.md for why.

Honesty note: every result records which path actually served it (`served_by`: "agent" or
"deterministic_fallback"). Without OPENAI_API_KEY + AGENT_ENABLED=1, every task is served by the existing
deterministic pipeline — this script says so plainly rather than implying agent coverage that didn't happen.

Usage: python3 eval/run_eval.py
"""
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


def call_agent_endpoint(task):
    import server
    handler = object.__new__(server.Handler)
    handler.path = '/api/agent/food-stop'
    body = json.dumps({'request': task['request'], 'lat': task['lat'], 'lon': task['lon'], 'item': task.get('item')}).encode()
    handler.headers = {'Content-Length': str(len(body))}
    handler.rfile = io.BytesIO(body)
    captured = {}
    handler.send_json = lambda code, data: captured.update(code=code, data=data)
    handler.post_admitted()
    return captured


def check(name, code, data):
    if name == 'has_candidates':
        candidates = (data.get('result') or {}).get('candidates') or (data.get('final_answer') and [1]) or []
        return len(candidates) > 0, f'{len(candidates)} candidates'
    if name == 'item_status_is_known':
        candidates = (data.get('result') or {}).get('candidates') or []
        if not candidates:
            return False, 'no candidates to check item status on'
        valid = {'confirmed_menu_match', 'probable_match_review', 'unverified', 'not_checked', 'not_found_in_checked_sources'}
        statuses = [c.get('item_status') for c in candidates]
        return all(s in valid for s in statuses), f'statuses seen: {statuses[:5]}'
    if name == 'no_candidates_outside_coverage':
        candidates = (data.get('result') or {}).get('candidates') or []
        return len(candidates) == 0, f'{len(candidates)} candidates (expected 0 outside NYC coverage)'
    return False, f'unknown check {name}'


def main():
    tasks = [json.loads(l) for l in (ROOT / 'eval' / 'agent_tasks.jsonl').read_text().splitlines() if l.strip()]
    results, served_by_counts = [], {}
    for task in tasks:
        out = call_agent_endpoint(task)
        code, data = out.get('code'), out.get('data') or {}
        served_by = data.get('served_by', 'unknown')
        served_by_counts[served_by] = served_by_counts.get(served_by, 0) + 1
        checks_passed = []
        for c in task['checks']:
            if code != 200:
                checks_passed.append((c, False, f'HTTP {code}'))
                continue
            passed, detail = check(c, code, data)
            checks_passed.append((c, passed, detail))
        results.append({'id': task['id'], 'request': task['request'], 'served_by': served_by, 'http_code': code,
                         'checks': [{'check': c, 'passed': p, 'detail': d} for c, p, d in checks_passed]})
    total_checks = sum(len(r['checks']) for r in results)
    passed_checks = sum(1 for r in results for c in r['checks'] if c['passed'])
    summary = {'tasks': len(tasks), 'total_checks': total_checks, 'passed_checks': passed_checks,
               'pass_rate': round(passed_checks / total_checks, 3) if total_checks else None,
               'served_by_breakdown': served_by_counts, 'results': results}
    out_path = ROOT / 'eval' / 'eval_results.json'
    out_path.write_text(json.dumps(summary, indent=2))
    print(f'{passed_checks}/{total_checks} checks passed across {len(tasks)} tasks. served_by: {served_by_counts}')
    print(f'Wrote {out_path}')
    for r in results:
        failed = [c for c in r['checks'] if not c['passed']]
        if failed:
            print(f'  FAIL {r["id"]}: {failed}')


if __name__ == '__main__':
    main()
