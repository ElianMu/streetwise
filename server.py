"""STREETWISE local development server.
Run: OPENAI_API_KEY=... python3 server.py
Keeps API keys on the server; never embeds credentials in client JavaScript.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os
import json
import math
import re
import gzip
import subprocess
import sys
import threading
import time
import traceback
from urllib import request, error
from urllib.parse import unquote, urlsplit, parse_qs
from routing.engine import get_planner, reset_planner, RoutingError, DIMENSIONS as ROUTE_DIMENSIONS, MIN_WALK_MINUTES
from routing.weather import validate_snapshot as validate_weather
from routing.itinerary import Planner as ItineraryPlanner, validate_request as validate_itinerary
from routing import menu as menu_check
from routing import providers
from routing.places import store as place_store
from routing.recommend import recommend_food
from interpretation_contract import RESPONSE_FORMAT, JOURNEY, validate as validate_contract, normalize_wire

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT', '8080'))
MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
def normalize_openai_api_key(raw):
    """Remove accidental whitespace at the edges of a pasted environment variable."""
    return raw.strip()


def openai_key_problem(key):
    """Check HTTP-header safety without logging or exposing the credential."""
    if not key:
        return 'not_configured'
    # HTTP header values cannot contain whitespace, control characters or non-ASCII.
    # Do not silently alter whitespace inside a credential.
    if any(not 33 <= ord(char) <= 126 for char in key):
        return 'invalid_key_format'
    return None


KEY = normalize_openai_api_key(os.environ.get('OPENAI_API_KEY', ''))
STREETS_DATA = ROOT / 'data' / 'manhattan-streets.json'
REFRESH_DAYS = float(os.environ.get('STREETWISE_REFRESH_DAYS', '30'))
GZIP_TYPES = ('.json', '.js', '.css', '.html')
_gzip_cache = {}
DIMENSIONS = list(ROUTE_DIMENSIONS)

SYSTEM = f"""You are STREETWISE's structured walking-preference interpreter. Never invent route geometry, verified spatial indicators, observations, or street-level environmental evidence.
Return one JSON object matching the supplied strict schema. All schema properties must exist: use null for unspecified nullable values, empty arrays for no requests, and null in constraints/more entries to preserve unchanged state. Keys:
"preferences": array of unique mentioned dimensions, each an object with "dimension" (exactly one of {json.dumps(DIMENSIONS)}), "weight" (integer 0..100), and "direction" (high or low). Weight is importance, not a street score. Clear preferences such as more trees, quieter or fewer busy streets should have high importance around 85–95, independently of direction. Fewer busy streets means Urban Vibrancy with high importance and direction low, not a small weight. For example less crowded means Urban Vibrancy with high importance and direction low; quieter means Quiet & Relax direction high. Omit unmentioned dimensions from the array. Never return separate weights/directions maps; the backend derives them from these pairs. Use full canonical names, not UI abbreviations.
"time_minutes": absolute walking hard cap in whole minutes (at least 10; no upper limit), if explicitly given; otherwise null.
"time_delta_minutes": signed integer modification to existing walking cap, if user explicitly says 'five more minutes'; otherwise null. Never return both time_minutes and time_delta_minutes non-null.
For an explicitly shortest route set constraints.avoidDetours=true and max_detour_percent=0. Historic landmarks map to Architecture and/or Culture; waterfront scenery maps to Scenic & Visual, not a new dimension.
"max_detour_percent": optional integer from 0 to 100 if explicitly specified (extra distance over the shortest candidate route distance), otherwise null.
"constraints": object with schema keys; changed values are boolean and unchanged values are null, for 'avoidDetours', 'stepFree', 'avoidStairs'. Null preserves prior constraints.
"weather": "ask" if the user asks whether the walk or route is comfortable in the current weather (answered from data, no re-routing); "cooler" if they want a cooler, shadier or less sun-exposed walk because of heat; "consider" if they ask to take today's weather into account; otherwise null. Weather is a separate context, not a dimension: "shade" may also raise Nature, but never invent temperatures, shade, rain cover or wind shelter. The current forecast is given in the state as "weather" (null when unavailable).
"journey": null unless the user explicitly requests places, visits, food, services, hotels or a trip endpoint change. Use only the supplied schema, with every property present. Unrequested arrays are empty; unrequested nullable fields are null. Do not turn preferences into extra visits.
  interests contains ONLY requested visit categories: famous, museums, historic, parks, shopping, culture. Architecture as a streetscape preference needs only a preference pair; a museum visit also needs interests=[museums]. Cafes/restaurants/bakeries belong ONLY in food, never shopping or culture unless those visits are separately requested.
  named_stops contains ONLY actual place names supplied by the user (translated to a known English NYC name if needed). Never invent names or placeholders such as landmark 1, landmark 2, museum 1. Generic categories belong in interests. Each named stop has name, required, and order (null unless an order is requested).
  For any explicit food/drink or food-category request, food must preserve it, including restaurants or cafes without naming a dish. Fields: category cafes/restaurants/bakeries/bars, item the specific dish/drink or null, cuisine an OSM cuisine value or null, required boolean. Coffee means item coffee. Raising Food & Retail never fulfils a POI requirement. Example: waterfront walk with restaurants and cultural attractions needs Scenic & Visual and Culture preferences, food category restaurants, and interest culture.
  services contains only explicitly requested service types. service_scope is null unless services is nonempty.
  origin and destination change ONLY for explicit start/from/end/finish instructions. "Near Central Park" is a search area, NOT a new origin. end_mode is null unless the user requests a fixed/flexible end, return to start (round), or return to hotel (hotel). "From my hotel" means origin=hotel.
  hotel is null for generic hotel searches; a named landmark near a hotel is not the hotel's name. Only use a hotel object for an actual named hotel, with is_mine reflecting whether the user stays there.
  counts is null unless explicit TOTAL visit counts are given. "visit two landmarks" means interests=[famous], counts.famous=2, named_stops=[], and every more entry null. "Add two more landmarks" instead means more.famous=2. Never use more for a total. Count keys must belong to interests. Requests above five of one category require clarification.
  requirements is null unless explicit business conditions or a search area exist. Preserve search_anchor for search proximity independently from the route origin; must_be_open for entry/open at arrival; ratings_required for good/highly rated venues or reviews; minimum_rating only for an explicit numeric 5-point threshold. Monetary fields restaurant_budget_usd, ticket_budget_usd, total_budget_usd, hotel_budget_per_night_usd require an explicit money amount/currency in the user's instructions. The current state's budget is WALKING MINUTES, never dollars. "Within my walking budget" must not become restaurant_budget_usd. Dates checkin/checkout, guests and beds are user requirements, never fetched facts. Keep unmentioned fields null.
  walking_minutes is a walking cap; outing_minutes is total time including visits; distance_km is a walking distance. more is incremental requested additions; remove contains explicitly removed names.
  Intent binding examples (fragments only; still return the FULL schema):
  - Find a highly rated cafe serving cappuccino near Central Park: interests=[], named_stops=[], food=[category cafes,item cappuccino,required true], origin=null, end_mode=null; requirements search_anchor=Central Park, ratings_required=true.
  - Start from my hotel, visit two landmarks and return to my hotel: interests=[famous], named_stops=[], origin=hotel, end_mode=hotel, counts.famous=2, all more entries null.
  - Find a hotel near Central Park with two beds and a budget of $250 per night: hotel=null, origin=null, interests=[], requirements search_anchor=Central Park,beds=2,hotel_budget_per_night_usd=250.
  - Recommend tiramisu with good reviews within my walking budget: interests=[], food=[category restaurants,item tiramisu,required true], requirements ratings_required=true, every monetary field null.
  Never output coordinates, addresses, menus, fetched prices, ratings or opening hours. STREETWISE data tools provide those facts.
"clarification": null unless user intent is materially ambiguous or contradictory (for example asks for both a strict 10-minute cap and a 30-minute minimum, or asks for inaccessible route when step-free is required). If ambiguous, write one short question here, do not infer changes.
Preserve current state: omit unmentioned dimensions from preferences; set unmentioned constraint values to null. Time and accessibility are hard constraints, not dimension scores. Do not claim quiet or step-free conditions are validated.
"""

def validate_interpretation(doc):
    if not isinstance(doc, dict):
        raise ValueError('LLM must return a JSON object')
    allowed = {'weights', 'directions', 'time_minutes', 'time_delta_minutes', 'max_detour_percent', 'constraints', 'clarification', 'weather', 'journey'}
    if set(doc) - allowed:
        raise ValueError('Unrecognized output keys')
    weights = doc.get('weights', {})
    dirs = doc.get('directions', {})
    constraints = doc.get('constraints', {})
    if not all(isinstance(x, dict) for x in (weights, dirs, constraints)):
        raise ValueError('Invalid object fields')
    if set(weights) - set(DIMENSIONS):
        raise ValueError('Invalid dimension name in weights (use canonical dimension names)')
    if set(dirs) - set(DIMENSIONS):
        raise ValueError('Invalid dimension name in directions (use canonical dimension names)')
    if set(dirs) - set(weights):
        raise ValueError('Direction has no corresponding weight')
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
    if doc.get('weather') not in (None, 'ask', 'cooler', 'consider'):
        raise ValueError('Invalid weather intent')
    journey = validate_journey(doc.get('journey'))
    clarification = doc.get('clarification')
    if clarification is not None and (not isinstance(clarification, str) or len(clarification) > 300):
        raise ValueError('Invalid clarification')
    return {'weights':weights, 'directions':{k:dirs.get(k, 'high') for k in weights},
            'time_minutes':absolute,'time_delta_minutes':delta,'max_detour_percent':detour,
            'constraints':constraints,'clarification':clarification,'weather':doc.get('weather'),'journey':journey}

JOURNEY_ENUMS = {'interests': {'famous', 'museums', 'historic', 'parks', 'shopping', 'culture'},
                 'services': {'pharmacies', 'groceries', 'health', 'banks', 'restrooms', 'luggage'}}

def validate_journey(j):
    """Structured tourist intent from the LLM: names and categories only, never coordinates or menus."""
    if j is None:
        return None
    validate_contract(j, JOURNEY, 'journey', required=False)
    if not isinstance(j, dict) or set(j) - {'interests', 'named_stops', 'food', 'services', 'service_scope', 'hotel', 'origin', 'destination',
                                              'end_mode', 'walking_minutes', 'outing_minutes', 'distance_km', 'more', 'remove', 'requirements', 'counts'}:
        raise ValueError('Invalid journey object')
    s = lambda v, n=160: v[:n] if isinstance(v, str) and v.strip() else None
    num = lambda v, lo, hi: v if type(v) in (int, float) and lo <= v <= hi else None
    out = {'interests': [x for x in (j.get('interests') or []) if x in JOURNEY_ENUMS['interests']],
           'services': [x for x in (j.get('services') or []) if x in JOURNEY_ENUMS['services']],
           'named_stops': [{'name': s(x.get('name')), 'required': x.get('required') is not False, 'order': x.get('order') if type(x.get('order')) is int else None}
                           for x in (j.get('named_stops') or [])[:8] if isinstance(x, dict) and s(x.get('name'))],
           'food': [{'category': x.get('category') if x.get('category') in ('cafes', 'restaurants', 'bakeries', 'bars') else 'restaurants',
                     'item': s(x.get('item'), 60), 'cuisine': s(x.get('cuisine'), 40), 'required': x.get('required') is not False}
                    for x in (j.get('food') or [])[:4] if isinstance(x, dict)],
           'service_scope': j.get('service_scope') if j.get('service_scope') in ('near_hotel', 'along_route', 'near_start') else None,
           'hotel': {'name': s(j['hotel'].get('name')), 'is_mine': j['hotel'].get('is_mine') is True} if isinstance(j.get('hotel'), dict) and s(j['hotel'].get('name')) else None,
           'origin': s(j.get('origin')), 'destination': s(j.get('destination')),
           'end_mode': j.get('end_mode') if j.get('end_mode') in ('fixed', 'round', 'hotel', 'open') else None,
           'walking_minutes': num(j.get('walking_minutes'), MIN_WALK_MINUTES, 1440), 'outing_minutes': num(j.get('outing_minutes'), 10, 1440),
           'distance_km': num(j.get('distance_km'), .1, 100),
           'more': {k: int(v) for k, v in (j.get('more') or {}).items() if k in JOURNEY_ENUMS['interests'] | {'cafes', 'restaurants'} and type(v) is int and 0 < v <= 5}
                   if isinstance(j.get('more'), dict) else {},
           'remove': [s(x) for x in (j.get('remove') or [])[:5] if s(x)],
           'requirements': j.get('requirements'), 'counts': j.get('counts') or {}}
    return out

# Per-client rate limits (requests per rolling minute). Render puts the client address in X-Forwarded-For.
RATE_LIMITS = {'interpret': 12, 'menu': 10, 'itinerary': 30, 'routes': 60, 'recommend': 6, 'places': 60, 'ratings': 20}
_rate, _rate_lock = {}, threading.Lock()


def client_ip(handler):
    fwd = handler.headers.get('X-Forwarded-For', '')
    return (fwd.split(',')[0].strip() or handler.client_address[0])[:64]


def rate_ok(handler, bucket):
    key, now = (client_ip(handler), bucket), time.time()
    with _rate_lock:
        hits = [t for t in _rate.get(key, []) if now - t < 60]
        if len(hits) >= RATE_LIMITS[bucket]:
            _rate[key] = hits
            return False
        hits.append(now)
        _rate[key] = hits
        if len(_rate) > 5000:
            _rate.clear()
    return True


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
    km = c.get('max_km')
    if km is not None:
        if type(km) not in (int, float) or not math.isfinite(km) or km <= 0:
            raise ValueError('constraints.max_km must be a positive number of kilometres')
        out['max_km'] = float(km)
    d = c.get('max_detour_pct')
    if d is not None:
        if type(d) not in (int, float) or not 0 <= d <= 100:
            raise ValueError('constraints.max_detour_pct must be 0..100')
        out['max_detour_pct'] = float(d)
    return (validate_point(doc.get('origin'), 'origin'), validate_point(doc.get('destination'), 'destination'), {'weights': weights, 'directions': dirs}, out,
            validate_weather(doc.get('weather')))


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

    def send_head(self):
        path = Path(self.translate_path(self.path))
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else None
        if rel is None or any(part.startswith('.') for part in rel.parts) or path.suffix in ('.py', '.pyc') or path.is_dir() and not (path/'index.html').exists():
            self.send_error(404, 'Not found'); return None
        return super().send_head()

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
            key_ready = openai_key_problem(KEY) is None
            self.send_json(200, {'llm': key_ready, 'model': MODEL if key_ready else None,
                                 'deployment_commit': os.environ.get('RENDER_GIT_COMMIT'),
                                 'interpretation_contract': 'strict-paired-v2',
                                 'features': {'itinerary': True, 'menu_verify': 'official website only (no menu API connected)',
                                              'routing_coverage': 'Manhattan OSM pedestrian graph',
                                              'place_search': 'Manhattan discovery + NYC DOHMH food permits + NYC Parks and public restrooms (citywide discovery; new unsnapped points are search only)',
                                              'food_recommendations': True, 'menu_ocr_available': bool(menu_check.shutil.which('tesseract')),
                                              'citywide_official_discovery': True},
                                 'providers': providers.configured()})
            return
        if self.path.startswith(('/api/places', '/api/hotels/')):
            self.places_get()
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

    def places_get(self):
        """GET /api/places/search?lat&lon&categories&radius_m&q&cuisine · /api/places/<id> · /api/places/<id>/ratings ·
        /api/hotels/<id>/rooms?checkin&checkout&guests. Ids are canonical place ids (e.g. osm:node/123, dohmh:50012345)."""
        u = urlsplit(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [unquote(x) for x in u.path.split('/')[2:]]   # ['places', ...] or ['hotels', ...]
        bucket = 'ratings' if parts[-1] in ('ratings', 'rooms') else 'places'
        if not rate_ok(self, bucket):
            self.send_json(429, {'error': f'Too many requests; limit {RATE_LIMITS[bucket]} per minute.'}); return
        S = place_store()
        try:
            if parts == ['places','categories']:
                self.send_json(200, json.loads((ROOT/'data/places/category_catalog.json').read_text())); return
            if parts[:2] == ['places', 'search']:
                near = {'lat': float(qs['lat']), 'lon': float(qs['lon'])}
                if not (40.4 < near['lat'] < 41.0 and -74.3 < near['lon'] < -73.6):
                    raise ValueError('lat/lon must be in New York City')
                cats = [c for c in (qs.get('categories') or 'restaurants').split(',') if c in S.categories][:8]
                if not cats:
                    raise ValueError('unknown categories')
                radius = max(50, min(3000, int(qs.get('radius_m') or 800)))
                res = S.search(near, cats, radius_m=radius, limit=max(1, min(50, int(qs.get('limit') or 20))), query=(qs.get('q') or '')[:60] or None,
                               cuisine=(qs.get('cuisine') or '')[:40] or None, include_closed=qs.get('include_closed') == '1')
                self.send_json(200, {'results': res, 'count': len(res), 'radius_m': radius, 'categories': cats,
                                     'note': 'Straight-line pre-selection; walking distance comes from the router. Outside Manhattan results are search only.'})
                return
            if parts == ['hotels', 'search']:
                near = {'lat': float(qs['lat']), 'lon': float(qs['lon'])}
                if not (40.4 < near['lat'] < 41 and -74.3 < near['lon'] < -73.6): raise ValueError('Search point outside NYC')
                guests = int(qs.get('guests') or 2)
                if not 1 <= guests <= 12: raise ValueError('guests must be 1-12')
                criteria = providers.validate_stay(qs.get('checkin'),qs.get('checkout'),guests,int(qs['beds']) if qs.get('beds') else None,float(qs['max_price']) if qs.get('max_price') else None)
                candidates = S.search(near, ['hotels'], radius_m=3000, limit=10)
                self.send_json(200, {'status': 'blocked_by_provider_access' if not any(providers.configured()[p] for p in ('booking_demand','expedia_rapid')) else 'not_implemented',
                    'candidates': candidates, 'rooms': [], 'price_matches': [],
                    'requirements': criteria,
                    'reason': 'Static hotel discovery only. Bed types, date-specific prices, availability and cancellations cannot be verified without an implemented authorized lodging provider.'})
                return
            pid = '/'.join(parts[1:-1]) if parts[-1] in ('ratings', 'rooms') else '/'.join(parts[1:])
            place = S.get(pid)
            if not place:
                self.send_json(404, {'error': 'Unknown place id'}); return
            if parts[0] == 'hotels':
                if parts[-1] != 'rooms' or place['category'] != 'hotels':
                    self.send_json(404, {'error': 'Use /api/hotels/<hotel id>/rooms'}); return
                guests = int(qs.get('guests') or 2)
                if not (1 <= guests <= 12):
                    raise ValueError('guests must be 1-12')
                for k in ('checkin', 'checkout'):
                    if qs.get(k) and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', qs[k]):
                        raise ValueError(f'{k} must be YYYY-MM-DD')
                self.send_json(200, providers.hotel_rooms(place, qs.get('checkin'), qs.get('checkout'), guests,int(qs['beds']) if qs.get('beds') else None,float(qs['max_price']) if qs.get('max_price') else None))
                return
            if parts[-1] == 'ratings':
                self.send_json(200, providers.ratings({'place_id': place['place_id'], 'name': place['name'], 'address': place['address'], **place['coordinates']}))
                return
            self.send_json(200, place)
        except (KeyError, ValueError) as e:
            self.send_json(400, {'error': f'Invalid request: {e}' if isinstance(e, ValueError) else 'lat and lon are required'})

    def send_gzipped(self):
        """Serve text assets gzip-compressed (the 12-dimension street file shrinks ~5x)."""
        if 'gzip' not in self.headers.get('Accept-Encoding', ''):
            return False
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / 'index.html'
        if any(p.startswith('.') for p in path.relative_to(ROOT).parts) or path.suffix not in GZIP_TYPES or not path.is_file():
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
        bucket = {'/api/menu/verify': 'menu', '/api/itinerary': 'itinerary', '/api/routes': 'routes', '/api/detours': 'itinerary',
                  '/api/interpret': 'interpret', '/api/recommend/food': 'recommend'}.get(self.path)
        if bucket and not rate_ok(self, bucket):
            self.send_json(429, {'error': f'Too many requests; limit {RATE_LIMITS[bucket]} per minute.'})
            return
        if self.path == '/api/itinerary':
            try:
                doc = read_json(self, 120000)
                self.send_json(200, ItineraryPlanner(get_planner()).plan(validate_itinerary(doc)))
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                self.send_json(422 if isinstance(e, RoutingError) else 400, {'error': str(e)})
            except RuntimeError as e:
                self.send_json(503, {'error': str(e)})
            return
        if self.path == '/api/detours':
            try:
                from routing.itinerary import detours
                self.send_json(200, detours(get_planner(), read_json(self, 30000)))
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                self.send_json(422 if isinstance(e, RoutingError) else 400, {'error': str(e)})
            return
        if self.path == '/api/recommend/food':
            try:
                self.send_json(200, recommend_food(get_planner(), read_json(self, 8000)))
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                self.send_json(422 if isinstance(e, RoutingError) else 400, {'error': str(e)})
            except RuntimeError as e:
                self.send_json(503, {'error': str(e)})
            return
        if self.path == '/api/menu/verify':
            try:
                result = menu_check.verify(read_json(self, 4000))
                if any('refused' in p for p in [result.get('reason') or '']):
                    print('menu-verify refused URL', client_ip(self), result.get('place_id'), flush=True)  # security log
                self.send_json(200, result)
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                self.send_json(400, {'error': str(e)})
            return
        if self.path in ('/api/routes', '/api/navigation/progress'):
            try:
                doc = read_json(self, 20000)
                planner = get_planner()
                if self.path == '/api/routes':
                    self.send_json(200, planner.plan(*validate_route_request(doc)))
                else:
                    p = validate_point(doc, 'position')
                    acc = doc.get('accuracy_m')
                    self.send_json(200, planner.progress(str(doc.get('route_id', '')), p['lon'], p['lat'], acc if type(acc) in (int, float) else None,
                                                         doc.get('route_snapshot')))
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
        try:
            n = int(self.headers.get('Content-Length', 0))
            if n <= 0 or n > 25000:
                self.send_json(413, {'error': 'Invalid request size'})
                return
            doc = json.loads(self.rfile.read(n))
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {'error': 'Invalid JSON'})
            return
        status, body = interpret(doc)
        self.send_json(status, body)


class LLMFailure(Exception):
    """A failed interpretation with a reason that is safe to show and log (never the key, never the provider's message)."""
    def __init__(self, stage, http_status=None, type_=None, code=None, detail=None):
        super().__init__(stage)
        self.reason = {'stage': stage, 'http_status': http_status, 'type': type_, 'code': code, 'detail': scrub(detail)}


def scrub(text):
    """Remove anything that looks like a credential from a diagnostic string."""
    if not text:
        return None
    text = str(text)[:200]
    if KEY:
        text = text.replace(KEY, '[key]')
    return re.sub(r'(sk|rk|pk)-[A-Za-z0-9_\-*]{6,}', '[key]', text)


def call_llm(payload, timeout=26):
    req = request.Request('https://api.openai.com/v1/chat/completions', json.dumps(payload).encode('utf-8'),
                          headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}, method='POST')
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except error.HTTPError as e:
        # OpenAI error bodies: {"error": {"type": ..., "code": ...}}; only type and code are kept (the message can echo key fragments)
        try:
            err = json.loads(e.read() or b'{}').get('error') or {}
        except (ValueError, AttributeError):
            err = {}
        raise LLMFailure('upstream_http', e.code, err.get('type'), err.get('code'))
    except (error.URLError, TimeoutError, OSError) as e:
        raise LLMFailure('upstream_unreachable', detail=type(getattr(e, 'reason', e)).__name__)
    try:
        choice = json.loads(raw)['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise LLMFailure('model_output_incomplete')
        if choice['message'].get('refusal'):
            raise LLMFailure('model_refused')
        content = choice['message']['content']
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMFailure('upstream_bad_response', detail='no choices[0].message.content in the provider response')
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        raise LLMFailure('model_output_invalid_json')



def validate_intent_bindings(result, message, history=()):
    """Reject known invented bindings; ask the model to repair, never manufacture intent."""
    j = result.get('journey') or {}
    if result.get('clarification'): return
    text = message.lower()
    for stop in j.get('named_stops', []):
        name = stop['name'].lower().strip()
        if re.fullmatch(r'(?:landmark|museum|cafe|restaurant|hotel|park|attraction|stop)[ _-]*(?:[0-9]+|one|two|three)', name) and name not in text:
            raise ValueError('Generic numbered visits are not named places; use interests and total counts, not invented named_stops')
    counts = j.get('counts') or {}
    if set(counts) - set(j.get('interests', [])):
        raise ValueError('Total visit count keys must belong to interests')
    total = re.search(r'\b(?:visit|see|explore)\s+(one|two|three|four|five|[1-5])\s+(landmarks?|museums?|parks?)\b', text)
    if total:
        value = int(total[1]) if total[1].isdigit() else ['one','two','three','four','five'].index(total[1])+1
        categories = ['famous','historic'] if total[2].startswith('landmark') else ['museums'] if total[2].startswith('museum') else ['parks']
        if sum(counts.get(k,0) for k in categories) != value or any(k in (j.get('more') or {}) for k in categories):
            raise ValueError('Explicit total visits need total counts, not increments. counts='+str(counts)+'; more='+str(j.get('more') or {}))
    req = j.get('requirements') or {}
    if re.search(r'\bgood\s+(?:bakery|bakery shop|caf[eé]|restaurant)\b',text) and req.get('ratings_required') is not True:
        raise ValueError('Requested good venue needs ratings_required=true; generic category discovery cannot verify quality')
    user_text = text + ' ' + ' '.join(str(h.get('content') or '').lower() for h in history[-8:] if isinstance(h,dict) and h.get('role')=='user')
    if any(req.get(k) is not None for k in ('restaurant_budget_usd','ticket_budget_usd','total_budget_usd','hotel_budget_per_night_usd')) and not re.search(r'[$]|\b(?:usd|dollars?)\b|美元', user_text):
        raise ValueError('Monetary requirements need explicit user currency; current-state budget is walking minutes, not dollars')
    anchor = req.get('search_anchor')
    if anchor and j.get('origin') == anchor and not re.search(r'\b(?:start|from|begin|leave)\b|出发|起点|从',text):
        raise ValueError('Search proximity is not a route origin change; preserve search_anchor and leave origin null')


def count_contract_example():
    """A prompt demonstration of the same wire schema, never an API fallback."""
    from interpretation_contract import WIRE_SCHEMA
    def blank(schema):
        if 'anyOf' in schema: return None
        if schema['type']=='object': return {k:blank(v) for k,v in schema['properties'].items()}
        return [] if schema['type']=='array' else None
    sample=blank(WIRE_SCHEMA)
    j=blank(JOURNEY)
    j.update(interests=['famous'],origin='hotel',end_mode='hotel')
    j['counts']=blank(JOURNEY['properties']['counts']['anyOf'][0]);j['counts']['famous']=2
    sample['journey']=j
    return sample


def interpret(doc):
    """POST /api/interpret → (HTTP status, body). Failures carry a safe `reason` and are logged without secrets."""
    key_problem = openai_key_problem(KEY)
    if key_problem == 'not_configured':
        return 503, {'error': 'Set OPENAI_API_KEY on the server to use LLM interpretation.', 'reason': {'stage': 'not_configured'}}
    if key_problem == 'invalid_key_format':
        reason = {'stage': 'invalid_key_format'}
        print('interpret failure', json.dumps(reason), flush=True)
        return 503, {'error': 'OPENAI_API_KEY has invalid formatting on the server.', 'reason': reason}
    if not isinstance(doc, dict):
        return 400, {'error': 'Expected a JSON object'}
    message = doc.get('message', '')
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        return 400, {'error': 'Invalid message'}
    history = doc.get('history', [])
    if not isinstance(history, list):
        return 400, {'error': 'history must be an array'}
    context = {k: doc.get(k) for k in ('weights', 'constraints', 'weather')}
    context['walking_budget_minutes'] = doc.get('budget')
    payload = {
        'model': MODEL,
        'temperature': 0,
        'response_format': RESPONSE_FORMAT,
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': 'Start from my hotel, visit two landmarks and return to my hotel.'},
            {'role': 'assistant', 'content': json.dumps(count_contract_example())},
            {'role': 'user', 'content': 'Current state: '+json.dumps(context, ensure_ascii=False)+'\nRecent conversation: '+json.dumps(history[-8:], ensure_ascii=False)+'\nLatest instruction: '+message}
        ]
    }
    try:
        deadline = time.monotonic() + 26
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMFailure('upstream_unreachable', detail='TimeoutError')
            output = call_llm(payload, timeout=remaining)
            try:
                result = validate_interpretation(normalize_wire(output))
                validate_intent_bindings(result, message, history)
                return 200, result
            except ValueError as e:
                failure = LLMFailure('model_output_rejected', detail=f'{e}; keys: {sorted(output)[:12] if isinstance(output, dict) else type(output).__name__}')
                if attempt:
                    raise failure
                # Ask the model to repair its own result; never manufacture a weight or
                # silently drop a preference. Keep strict validation on the second result.
                print('interpret retry', json.dumps(failure.reason), flush=True)
                payload['messages'].extend([
                    {'role': 'assistant', 'content': json.dumps(output, ensure_ascii=False)},
                    {'role': 'user', 'content':
                     'Your JSON failed validation: ' + str(e) + '. Return a corrected JSON object for the ORIGINAL request. '
                     'Use the strict schema preferences array with unique dimension/weight/direction triples. '
                     'Omit unrequested dimensions from that array; never invent weights to satisfy validation. Preserve explicit POI requirements in journey.food and preserve all other intent.'}
                ])
    except LLMFailure as f:
        print('interpret failure', json.dumps(f.reason), flush=True)
        return 502, {'error': 'LLM request failed; local preview can be used.', 'reason': f.reason}
    except Exception as e:
        reason = {'stage': 'server_error', 'detail': type(e).__name__}
        # Frame locations only: exception messages and locals can contain credentials.
        frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                  for f in traceback.extract_tb(e.__traceback__)]
        print('interpret failure', json.dumps({**reason, 'frames': frames}), flush=True)
        return 500, {'error': 'Server interpretation error', 'reason': reason}

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
