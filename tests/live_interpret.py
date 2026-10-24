"""Explicit live acceptance: python3 tests/live_interpret.py. Calls production AI (billable).
Never included in unittest discovery; no mocks. Does not assert POI visits/GPS/map rendering.
"""
import json, pathlib, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import validate_interpretation

BASE = 'https://streetwise-api.onrender.com'
CASES = [
 ('A', 'I want a scenic walk with architecture, parks, and good coffee.'),
 ('B', 'Find me a quiet walking route with more trees and fewer busy streets.'),
 ('C', 'I want the shortest walking route with historic landmarks.'),
 ('D', 'Recommend a waterfront walk with restaurants and cultural attractions.')]


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={
        'Content-Type': 'application/json', 'Origin': 'https://elianmu.github.io'})
    with urllib.request.urlopen(req, timeout=40) as r:
        assert r.status == 200
        assert r.headers.get('Access-Control-Allow-Origin') == 'https://elianmu.github.io'
        return json.load(r)


def run():
    for label, text in CASES:
        p = post('/api/interpret', {'message': text})
        validate_interpretation(p)
        w, d, j = p['weights'], p['directions'], p.get('journey') or {}
        if label == 'A':
            assert all(w.get(k, 0) > 0 for k in ['Scenic & Visual', 'Architecture', 'Nature'])
            assert any(f['category'] == 'cafes' and f['item'] == 'coffee' for f in j.get('food', []))
        if label == 'B':
            assert w.get('Nature', 0) > 0 and w.get('Quiet & Relax', 0) > 0
            assert d['Nature'] == d['Quiet & Relax'] == 'high'
            assert w.get('Urban Vibrancy', 0) > 0 and d['Urban Vibrancy'] == 'low'
        if label == 'C':
            assert w.get('Architecture', 0) > 0 or w.get('Culture', 0) > 0
            assert p['constraints'].get('avoidDetours') is True and p['max_detour_percent'] == 0
        if label == 'D':
            assert w.get('Scenic & Visual', 0) > 0 and w.get('Culture', 0) > 0
            assert any(f['category'] == 'restaurants' for f in j.get('food', []))
        result = post('/api/routes', {'origin': {'lon': -73.9832, 'lat': 40.7536},
            'destination': {'lon': -73.9787, 'lat': 40.7587}, 'preferences': p,
            'constraints': {'max_minutes': 30, 'max_detour_pct': p['max_detour_percent'] if p['max_detour_percent'] is not None else 25,
                            'avoid_detours': p['constraints'].get('avoidDetours', True)}})
        assert result['preferences_expressed'] and result['routes']
        for k, weight in w.items():
            if weight <= 0: continue
            assert result['preferences_used'][k] == {'weight': weight, 'direction': d[k]}
            for route in result['routes']:
                component = route['personalized_score']['components'][k]
                assert component['weight'] == weight and component['direction'] == d[k]
                assert route['ordered_edge_ids'] and route['distance_m'] > 0
        utilities = [r['personalized_score']['utility'] for r in result['routes'] if r['constraints']['feasible']]
        assert utilities == sorted(utilities, reverse=True)
        print(json.dumps({'case': label, 'status': 'PASS', 'interpretation': p,
                          'ranks': [r['rank'] for r in result['routes']], 'utilities': utilities}), flush=True)

if __name__ == '__main__': run()
