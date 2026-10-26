"""Tool Registry: existing STROLLANE routing/data capabilities wrapped as LangChain tools for the Agent Runtime.

Every tool here is a thin wrapper around a real, already-tested function in routing/* — it adds no new business
logic. Each returns a uniform {"ok": bool, "data": ...} or {"ok": False, "error": {"type": ..., "message": ...}}
envelope so the agent graph (agent/runtime.py) can reason about failure without each tool inventing its own shape.

Tools, and what they actually call:
  search_places          -> routing.places.store().search(...)            (place discovery)
  get_weather             -> Open-Meteo forecast API (same source as weather.js) + routing.weather.assess(...)
  calculate_route         -> routing.engine.get_planner().plan(...)        (A*/Dijkstra pedestrian routing)
  validate_route          -> checks a route's own returned fields against the caller's stated constraints
  verify_restaurant_menu  -> routing.menu.verify(...)                      (official-site menu check, cached, SSRF-guarded)

No tool here talks to the network for anything other than get_weather (Open-Meteo, no key, same endpoint the
client already calls) — search/route/menu all run against this process's own local data and caches.
"""
import math
import time
from urllib import request as _urlreq, error as _urlerr, parse as _urlparse

from langchain_core.tools import tool

ERR_INVALID_INPUT = 'invalid_input'
ERR_UPSTREAM = 'upstream_unavailable'
ERR_NOT_FOUND = 'not_found'


def _ok(data):
    return {'ok': True, 'data': data}


def _err(kind, message):
    return {'ok': False, 'error': {'type': kind, 'message': str(message)[:400]}}


@tool
def search_places(lat: float, lon: float, categories: str = 'restaurants', query: str = '', cuisine: str = '',
                   radius_m: int = 800, limit: int = 8) -> dict:
    """Search for real places (restaurants, cafes, bakeries, bars, etc.) near a point in NYC.

    categories: comma-separated, from the app's own category catalog (e.g. "restaurants,cafes").
    Returns candidate places with place_id, name, coordinates, category — no ratings or menu facts yet;
    call verify_restaurant_menu / providers ratings separately for those.
    """
    from routing.places import store
    try:
        if not (40.4 < lat < 41.0 and -74.3 < lon < -73.6):
            return _err(ERR_INVALID_INPUT, 'lat/lon must be in New York City')
        S = store()
        cats = [c for c in categories.split(',') if c in S.categories][:8] or ['restaurants']
        radius = max(50, min(3000, int(radius_m or 800)))
        results = S.search({'lat': float(lat), 'lon': float(lon)}, cats, radius_m=radius,
                            limit=max(1, min(20, int(limit or 8))), query=(query or '')[:60] or None,
                            cuisine=(cuisine or '')[:40] or None)
        return _ok({'results': results, 'count': len(results), 'radius_m': radius,
                    'note': 'Straight-line pre-selection; real walking distance comes from calculate_route.'})
    except (ValueError, TypeError, KeyError) as e:
        return _err(ERR_INVALID_INPUT, e)
    except RuntimeError as e:
        return _err(ERR_UPSTREAM, e)


@tool
def get_weather(lat: float, lon: float, minutes: int = 30) -> dict:
    """Current/near-term weather for a point, from Open-Meteo (no key; model forecast, not a street-level
    measurement — same source the app's own weather.js uses). `minutes` is how far ahead to look (a walk window).
    Returns the routing-engine's weather assessment (heat/rain/wind advisories), not raw numbers only.
    """
    from routing.weather import validate_snapshot, assess
    try:
        q = _urlparse.urlencode({'latitude': f'{float(lat):.4f}', 'longitude': f'{float(lon):.4f}',
                                  'timezone': 'America/New_York', 'forecast_hours': '6',
                                  'current': 'apparent_temperature,precipitation,weather_code,wind_speed_10m,is_day',
                                  'hourly': 'apparent_temperature,precipitation_probability,precipitation,wind_speed_10m,is_day'})
        req = _urlreq.Request(f'https://api.open-meteo.com/v1/forecast?{q}', headers={'User-Agent': 'strollane-agent/1'})
        with _urlreq.urlopen(req, timeout=10) as resp:
            import json as _json
            d = _json.loads(resp.read().decode('utf-8'))
        if not d.get('current') or not d.get('hourly'):
            return _err(ERR_UPSTREAM, 'Open-Meteo returned no model output')
        c, h = d['current'], d['hourly']
        window = max(10, int(minutes or 30))
        end_idx = max(1, min(len(h['time']), math.ceil(window / 60) + 1))
        feels_vals = [v for v in h['apparent_temperature'][:end_idx] + [c.get('apparent_temperature')] if v is not None]
        precip_prob_vals = [v for v in h['precipitation_probability'][:end_idx] if v is not None]
        wind_vals = [v for v in h['wind_speed_10m'][:end_idx] + [c.get('wind_speed_10m')] if v is not None]
        snap_in = {'source': 'open-meteo', 'kind': 'forecast_window', 'age_min': 0,
                   'feels_like_max_c': max(feels_vals) if feels_vals else None,
                   'temperature_max_c': max(feels_vals) if feels_vals else None,
                   'precip_probability_max_pct': max(precip_prob_vals) if precip_prob_vals else None,
                   'precip_max_mm_per_h': c.get('precipitation'), 'wind_max_kmh': max(wind_vals) if wind_vals else None,
                   'daylight': c.get('is_day') == 1, 'mode': 'auto', 'priority': 'normal', 'alerts': []}
        snap = validate_snapshot(snap_in)
        return _ok(assess(snap))
    except (_urlerr.URLError, TimeoutError, OSError) as e:
        return _err(ERR_UPSTREAM, f'Open-Meteo unreachable: {e}')
    except (ValueError, TypeError, KeyError) as e:
        return _err(ERR_INVALID_INPUT, e)


@tool
def calculate_route(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float,
                     max_minutes: float = 0) -> dict:
    """Plan a real walking route between two points using the OSM pedestrian graph (A*/Dijkstra).
    max_minutes (optional): the caller's own hard time limit; 0 means no limit. Returns the ranked route(s)
    with actual distance/time, never an estimate.
    """
    from routing.engine import get_planner, RoutingError
    try:
        planner = get_planner()
        constraints = {'avoid_detours': True, 'avoid_stairs': False}
        if max_minutes and max_minutes > 0:
            constraints['max_minutes'] = float(max_minutes)
        result = planner.plan({'lat': float(origin_lat), 'lon': float(origin_lon)},
                               {'lat': float(dest_lat), 'lon': float(dest_lon)},
                               {'weights': {}, 'directions': {}}, constraints, None)
        return _ok(result)
    except RoutingError as e:
        return _err(ERR_INVALID_INPUT, e)
    except (ValueError, TypeError) as e:
        return _err(ERR_INVALID_INPUT, e)
    except RuntimeError as e:
        return _err(ERR_UPSTREAM, e)


@tool
def validate_route(route_minutes: float, max_minutes: float = 0, max_km: float = 0, route_km: float = 0) -> dict:
    """Check a route calculate_route already returned against the caller's own stated constraints
    (max walk time / max distance). Pure arithmetic check — does not call the router again.
    """
    violations = []
    if max_minutes and max_minutes > 0 and route_minutes > max_minutes:
        violations.append(f'route takes {route_minutes:.1f} min, over the {max_minutes:.1f} min limit')
    if max_km and max_km > 0 and route_km > max_km:
        violations.append(f'route is {route_km:.2f} km, over the {max_km:.2f} km limit')
    return _ok({'satisfies_constraints': not violations, 'violations': violations})


@tool
def verify_restaurant_menu(place_id: str, item: str, name: str = '') -> dict:
    """Check whether a specific place's OFFICIAL website menu lists a requested food item. Real evidence only —
    never guesses. Status is one of confirmed_menu_match / probable_match_review / unverified / not_found_in_checked_sources.
    """
    from routing import menu as menu_check
    try:
        result = menu_check.verify({'place_id': place_id, 'item': item, 'name': name})
        return _ok(result)
    except (ValueError, TypeError) as e:
        return _err(ERR_INVALID_INPUT, e)


TOOLS = [search_places, get_weather, calculate_route, validate_route, verify_restaurant_menu]
