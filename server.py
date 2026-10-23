"""STREETWISE local development server.
Run: OPENAI_API_KEY=... python3 server.py
Keeps API keys on the server; never embeds credentials in client JavaScript.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os
import json
import math
import gzip
import subprocess
import sys
import threading
import time
from urllib import request, error
from urllib.parse import unquote, urlsplit, parse_qs
from routing.engine import get_planner, reset_planner, RoutingError, DIMENSIONS as ROUTE_DIMENSIONS, MIN_WALK_MINUTES

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT', '8080'))
MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
KEY = os.environ.get('OPENAI_API_KEY', '')
STREETS_DATA = ROOT / 'data' / 'manhattan-streets.json'
REFRESH_DAYS = float(os.environ.get('STREETWISE_REFRESH_DAYS', '30'))
GZIP_TYPES = ('.json', '.js', '.css', '.html')
_gzip_cache = {}
DIMENSIONS = [
    'Architecture', 'Nature', 'Culture', 'Quiet & Relax', 'Spatial Comfort',
    'Urban Vibrancy', 'Food & Retail', 'Scenic & Visual', 'Walkability',
    'Access & Safety', 'Environment', 'Transit Connectivity'
]

SYSTEM = f"""You are STREETWISE's structured walking-preference interpreter. Never invent route geometry, verified spatial indicators, observations, or street-level environmental evidence.
Return one JSON object ONLY with keys:
"weights": object mapping ONLY mentioned dimensions (exactly these 12 names: {json.dumps(DIMENSIONS)}) to independent IMPORTANCE integers 0..100. 0 means ignore, not an inverse objective. A clear request such as 'more greenery', 'less traffic', or 'quieter streets' gives high importance about 85-95.
"directions": object mapping ONLY the same mentioned dimensions to either 'high' or 'low': desired greater or lesser measured exposure. 'Less crowded' = Urban Vibrancy weight 90 direction low. 'Quieter' = Quiet & Relax weight 90 direction high (quiet is desired high). Do not use low weights to represent a negative preference.
"time_minutes": absolute walking hard cap in whole minutes (at least 10; no upper limit), if explicitly given; otherwise null.
"time_delta_minutes": signed integer modification to existing walking cap, if user explicitly says 'five more minutes'; otherwise null. Never return both time_minutes and time_delta_minutes non-null.
"max_detour_percent": optional integer from 0 to 100 if explicitly specified (extra distance over the shortest candidate route distance), otherwise null.
"constraints": object containing ONLY changed boolean entries from 'avoidDetours', 'stepFree', 'avoidStairs'. Keep unmentioned prior constraints.
"clarification": null unless user intent is materially ambiguous or contradictory (for example asks for both a strict 10-minute cap and a 30-minute minimum, or asks for inaccessible route when step-free is required). If ambiguous, write one short question here, do not infer changes.
Preserve current state by omitting every unmentioned dimension/constraint. Time and accessibility are hard constraints, not dimension scores. Do not claim quiet or step-free conditions are validated.
"""

def validate_interpretation(doc):
    if not isinstance(doc, dict):
        raise ValueError('LLM must return a JSON object')
    allowed = {'weights', 'directions', 'time_minutes', 'time_delta_minutes', 'max_detour_percent', 'constraints', 'clarification'}
    if set(doc) - allowed:
        raise ValueError('Unrecognized output keys')
    weights = doc.get('weights', {})
    dirs = doc.get('directions', {})
    constraints = doc.get('constraints', {})
    if not all(isinstance(x, dict) for x in (weights, dirs, constraints)):
        raise ValueError('Invalid object fields')
    if set(weights) - set(DIMENSIONS) or set(dirs) - set(weights):
        raise ValueError('Invalid dimension name')
    if any(type(v) is not int or not 0 <= v <= 100 for v in weights.values()):
        raise ValueError('Preference must be integer 0..100')
    if any(v not in ('high', 'low') for v in dirs.values()):
        raise ValueError('Invalid dimension direction')
    if set(constraints) - {'avoidDetours', 'stepFree', 'avoidStairs'} or any(type(v) is not bool for v in constraints.values()):
        raise ValueError('Invalid hard constraint')
    absolute, delta, detour = (doc.get(x) for x in ('time_minutes', 'time_delta_minutes', 'max_detour_percent'))
    if absolute is not None and (type(absolute) is not int or absolute < MIN_WALK_MINUTES):
        raise ValueError('Invalid absolute minutes')
    if delta is not None and (type(delta) is not int or abs(delta) > 1440):
        raise ValueError('Invalid time delta')
    if absolute is not None and delta is not None:
        raise ValueError('Conflicting time outputs')
    if detour is not None and (type(detour) is not int or not 0 <= detour <= 100):
        raise ValueError('Invalid detour percent')
    clarification = doc.get('clarification')
    if clarification is not None and (not isinstance(clarification, str) or len(clarification) > 300):
        raise ValueError('Invalid clarification')
    return {'weights':weights, 'directions':{k:dirs.get(k, 'high') for k in weights},
            'time_minutes':absolute,'time_delta_minutes':delta,'max_detour_percent':detour,
            'constraints':constraints,'clarification':clarification}

def read_json(handler, limit):
    n = int(handler.headers.get('Content-Length', 0))
    if n <= 0 or n > limit:
        raise ValueError('Invalid request size')
    return json.loads(handler.rfile.read(n))


def validate_point(p, label):
    if not isinstance(p, dict) or type(p.get('lat')) not in (int, float) or type(p.get('lon')) not in (int, float):
        raise ValueError(f'{label} must be {{"lat": number, "lon": number}}')
    if not (-74.1 <= p['lon'] <= -73.85 and 40.65 <= p['lat'] <= 40.92):
        raise ValueError(f'{label} is outside the Manhattan routing area')
    return {'lat': float(p['lat']), 'lon': float(p['lon'])}


def validate_route_request(doc):
    """Routing API input: origin, destination, optional preferences (user weights, never street scores) and constraints."""
    if not isinstance(doc, dict):
        raise ValueError('Expected a JSON object')
    prefs = doc.get('preferences') or {}
    weights, dirs = prefs.get('weights') or {}, prefs.get('directions') or {}
    if not isinstance(weights, dict) or not isinstance(dirs, dict) or set(weights) - set(ROUTE_DIMENSIONS) or set(dirs) - set(ROUTE_DIMENSIONS):
        raise ValueError(f'preferences.weights/directions keys must be among {ROUTE_DIMENSIONS}')
    if any(type(v) not in (int, float) or not 0 <= v <= 100 for v in weights.values()) or any(v not in ('high', 'low') for v in dirs.values()):
        raise ValueError('Weights must be 0..100 and directions "high" or "low"')
    c = doc.get('constraints') or {}
    out = {'avoid_detours': c.get('avoid_detours', True) is not False, 'avoid_stairs': c.get('avoid_stairs') is True}
    # Max walking time is the user's own hard limit: at least 10 minutes, no hidden upper cap.
    m = c.get('max_minutes')
    if m is not None:
        if type(m) not in (int, float) or not math.isfinite(m) or m < MIN_WALK_MINUTES:
            raise ValueError(f'constraints.max_minutes must be a number of minutes ≥ {MIN_WALK_MINUTES}')
        out['max_minutes'] = float(m)
    d = c.get('max_detour_pct')
    if d is not None:
        if type(d) not in (int, float) or not 0 <= d <= 100:
            raise ValueError('constraints.max_detour_pct must be 0..100')
        out['max_detour_pct'] = float(d)
    return validate_point(doc.get('origin'), 'origin'), validate_point(doc.get('destination'), 'destination'), {'weights': weights, 'directions': dirs}, out


_segments = None


def street_segment(segment_id):
    """Street Segment Object (shared data contract) from the Explore Urban Data layer."""
    global _segments
    if _segments is None:
        data = json.loads(STREETS_DATA.read_text(encoding='utf-8'))
        _segments = (data['metadata'], {f['properties']['id']: f for f in data['features']})
    meta, index = _segments
    f = index.get(segment_id)
    if not f:
        return None
    p = f['properties']
    dims = {d: p[f'd{j}'] for j, d in enumerate(ROUTE_DIMENSIONS)}
    return {
        'segment_id': p['id'], 'source_segment_id': p.get('source_segment_id'), 'lion_part': p.get('lion_part'),
        'street_name': p['name'], 'geometry': f['geometry'], 'length_m': p['length_m'],
        'dimension_scores': dims, 'overall_score': p['overall'],
        'sub_indicators': {d: [{**x, 'value': p.get(x['key'])} for x in meta['indicators'][k]] for d, k in zip(ROUTE_DIMENSIONS, meta['keys'])},
        'data_sources': meta['source_labels'], 'data_coverage': {'dimensions_available': p['coverage'], 'of': 12},
        'score_version': meta.get('score_version'), 'data_version': meta.get('data_version'),
    }


def validate_bbox(data):
    if not isinstance(data, dict) or not isinstance(data.get('bbox'), list) or len(data['bbox']) != 4:
        raise ValueError('Expected bbox [west,south,east,north]')
    bounds = data['bbox']
    if any(type(v) not in (int, float) or not -180 <= v <= 180 for v in bounds):
        raise ValueError('Invalid bounding box')
    west,south,east,north = bounds
    if not (-74.1 <= west < east <= -73.7 and 40.5 <= south < north <= 40.98 and east-west <= .055 and north-south <= .055):
        raise ValueError('Box outside supported Manhattan area or too large')
    return (south, west, north, east)

# Live Overpass query: named real OSM nodes only. No made-up coordinates or results.
def fetch_pois(bounds):
    from urllib.parse import urlencode
    south,west,north,east = bounds
    bbox = ','.join(f'{x:.6f}' for x in (south,west,north,east))
    query = (f'[out:json][timeout:17];('
             f'node["name"]["tourism"~"^(museum|gallery|attraction|viewpoint)$"]({bbox});'
             f'node["name"]["historic"]({bbox});'
             f'node["name"]["amenity"~"^(cafe|restaurant|theatre)$"]({bbox});'
             f'node["name"]["leisure"~"^(park|garden)$"]({bbox});'
             ');out body 450;')
    endpoint = os.environ.get('OVERPASS_URL', 'https://overpass-api.de/api/interpreter')
    payload = urlencode({'data':query}).encode('utf-8')
    req = request.Request(endpoint, data=payload, method='POST', headers={'User-Agent':'StreetwiseResearchPrototype/0.4', 'Content-Type':'application/x-www-form-urlencoded'})
    with request.urlopen(req, timeout=23) as resp:
        doc = json.load(resp)
    return [{'id':str(x['id']), 'lat':x['lat'], 'lon':x['lon'], 'name':x['tags']['name'], 'tags':x['tags']}
            for x in doc.get('elements', []) if x.get('type')=='node' and isinstance(x.get('tags',{}).get('name'),str)
            and isinstance(x.get('lat'), (int,float)) and isinstance(x.get('lon'), (int,float))][:450]

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # Allow the STREETWISE GitHub Pages frontend to access the API.
        if self.path.startswith('/api/'):
            origin = self.headers.get('Origin', '')
            if origin == 'https://elianmu.github.io':
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        else:
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_OPTIONS(self):
        if self.path.startswith('/api/'):
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/api/status':
            self.send_json(200, {'llm': bool(KEY), 'model': MODEL if KEY else None})
            return
        if self.path == '/api/routing/status':
            try:
                self.send_json(200, {'available': True, **get_planner().net.status()})
            except RuntimeError as e:
                self.send_json(503, {'available': False, 'error': str(e)})
            return
        if self.path.startswith('/api/edges/'):
            try:
                net = get_planner().net
            except RuntimeError as e:
                self.send_json(503, {'error': str(e)}); return
            i = net.by_id.get(unquote(self.path[len('/api/edges/'):]))
            self.send_json(200, net.edge_object(i)) if i is not None else self.send_json(404, {'error': 'Unknown OSM edge ID (expected "u-v-key")'})
            return
        if self.path.startswith('/api/segments/'):
            seg = street_segment(unquote(self.path[len('/api/segments/'):]))
            self.send_json(200, seg) if seg else self.send_json(404, {'error': 'Unknown analysis segment ID'})
            return
        if self.send_gzipped():
            return
        return super().do_GET()

    def send_gzipped(self):
        """Serve text assets gzip-compressed (the 12-dimension street file shrinks ~5x)."""
        if 'gzip' not in self.headers.get('Accept-Encoding', ''):
            return False
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / 'index.html'
        if path.suffix not in GZIP_TYPES or not path.is_file():
            return False
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        body = _gzip_cache.get(key)
        if body is None:
            body = gzip.compress(path.read_bytes(), 6)
            _gzip_cache.clear() if len(_gzip_cache) > 32 else None
            _gzip_cache[key] = body
        self.send_response(200)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Vary', 'Accept-Encoding')
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_POST(self):
        if self.path in ('/api/routes', '/api/navigation/progress'):
            try:
                doc = read_json(self, 20000)
                planner = get_planner()
                if self.path == '/api/routes':
                    self.send_json(200, planner.plan(*validate_route_request(doc)))
                else:
                    p = validate_point(doc, 'position')
                    acc = doc.get('accuracy_m')
                    self.send_json(200, planner.progress(str(doc.get('route_id', '')), p['lon'], p['lat'], acc if type(acc) in (int, float) else None))
            except (ValueError, TypeError, json.JSONDecodeError) as e:  # RoutingError is a ValueError
                self.send_json(422 if isinstance(e, RoutingError) else 400, {'error': str(e)})
            except RuntimeError as e:
                self.send_json(503, {'error': str(e)})
            return
        if self.path == '/api/pois':
            try:
                n = int(self.headers.get('Content-Length', 0))
                if n <= 0 or n > 1000:
                    self.send_json(413, {'error': 'Invalid POI request size'}); return
                bounds = validate_bbox(json.loads(self.rfile.read(n)))
                self.send_json(200, {'source':'OpenStreetMap Overpass live nodes','pois':fetch_pois(bounds)})
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json(400, {'error':'Invalid POI request'})
            except Exception:
                self.send_json(503, {'error':'OpenStreetMap POI service unavailable'})
            return
        if self.path != '/api/interpret':
            self.send_json(404, {'error': 'Unknown endpoint'})
            return
        if not KEY:
            self.send_json(503, {'error': 'Set OPENAI_API_KEY on the local server to use LLM interpretation.'})
            return
        try:
            n = int(self.headers.get('Content-Length', 0))
            if n <= 0 or n > 25000:
                self.send_json(413, {'error': 'Invalid request size'})
                return
            doc = json.loads(self.rfile.read(n))
            message = doc.get('message', '')
            if not isinstance(message, str) or not message.strip() or len(message) > 2000:
                self.send_json(400, {'error': 'Invalid message'})
                return
            context = {k: doc.get(k) for k in ('weights', 'budget', 'constraints')}
            payload = {
                'model': MODEL,
                'temperature': 0,
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': 'Current state: '+json.dumps(context, ensure_ascii=False)+'\nRecent conversation: '+json.dumps(doc.get('history', [])[-8:], ensure_ascii=False)+'\nLatest instruction: '+message}
                ]
            }
            req = request.Request('https://api.openai.com/v1/chat/completions', json.dumps(payload).encode('utf-8'),
                                  headers={'Authorization':'Bearer '+KEY, 'Content-Type':'application/json'}, method='POST')
            with request.urlopen(req, timeout=26) as resp:
                response = json.load(resp)
            output = validate_interpretation(json.loads(response['choices'][0]['message']['content']))
            self.send_json(200, output)
        except (error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(502, {'error': 'LLM request failed; local preview can be used.'})
        except Exception:
            self.send_json(500, {'error': 'Server interpretation error'})

def refresh_street_data_if_stale():
    """Rebuild the 12-dimension street snapshot in the background when it is missing or older than REFRESH_DAYS."""
    age_days = (time.time() - STREETS_DATA.stat().st_mtime) / 86400 if STREETS_DATA.exists() else None
    if REFRESH_DAYS <= 0 or (age_days is not None and age_days < REFRESH_DAYS):
        print(f'Street data: {age_days:.0f} days old (refresh after {REFRESH_DAYS:.0f}).' if age_days is not None else 'Street data: refresh disabled.')
        return
    print('Street data missing or stale; rebuilding street and edge scores from public sources in the background (about 4 minutes)…')
    def run():
        global _segments
        # Street scores and OSM edge scores are rebuilt together from the same download, so their versions always agree.
        for script, args in (('build_manhattan_streets.py', ['--refresh']), ('match_lion_osm.py', [])):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *args], capture_output=True, text=True)
            if result.returncode != 0:
                print(f'{script} failed; keeping the previous snapshot.\n' + result.stderr[-600:])
                return
        _segments = None
        reset_planner()
        print('Street data and edge scores refreshed.')
        # Static urban data tiles are rebuilt from the same day's sources; they need OSMnx, and a failure keeps the previous tiles.
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'build_urban_layers.py')], capture_output=True, text=True)
        print('Urban data tiles refreshed.' if result.returncode == 0 else 'Urban data tiles not refreshed (previous tiles kept):\n' + result.stderr[-400:])
    threading.Thread(target=run, daemon=True).start()

if __name__ == '__main__':
    print(f'STREETWISE · http://localhost:{PORT}')
    print('LLM status:', f'ON ({MODEL})' if KEY else 'OFF (limited local preview)')
    refresh_street_data_if_stale()
    def warm():
        try:
            print('Pedestrian routing network ready:', get_planner().net.network_version)
        except RuntimeError as e:
            print('Routing unavailable:', e)
    threading.Thread(target=warm, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
