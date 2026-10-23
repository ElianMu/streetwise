"""Weather-aware routing for the STREETWISE engine: a dynamic context next to the 12 static dimensions, never a 13th.

The browser sends a weather snapshot (Open-Meteo forecast for the walking window). Weather enters the edge cost only where
the network has spatial evidence for it:

  heat  — street-tree density and parkland beside each edge (the Nature sub-indicators tree_km and park_pct). This is a
          tree-cover PROXY, not measured shade: tree points say nothing about crown size, building shadows or sun angle.
  rain  — no covered-walkway, scaffolding or ponding data is connected: advisory only, never a routing cost.
  wind  — no street-level wind-exposure data is connected: advisory only.

Every coefficient below is configuration with its reason; changing one changes `config_version`, which the response echoes.
"""
import hashlib
import json

CONFIG = {
    'heat': {
        # NWS heat-index bands: "Caution" from 80 °F (≈27 °C), "Extreme caution" from 90 °F (≈32 °C). Feels-like temperature
        # (Open-Meteo apparent_temperature) below the first band adds nothing; the penalty grows linearly to full at the second.
        'feels_like_start_c': 27.0,
        'feels_like_full_c': 32.0,
        # Tree cover proxy: trees per km at which an edge counts as fully lined. 150/km (one tree every ~7 m) is the 90th
        # percentile of Manhattan LION segments; parkland beside the edge counts as cover in the same 0..1 scale.
        'tree_km_full_cover': 150.0,
        # Extra cost per metre of a fully exposed edge at full heat (same scale as the experience term, whose lambda is 0.8–2.0).
        'edge_coefficient': 0.6,
        # Ranking: points subtracted per 100 % exposed route length at full heat (personalized scores run 0–100).
        'rank_points': 20.0,
        # When the user explicitly asks for a cooler / shadier walk, the heat term counts this much more (an expressed
        # preference, like a dimension weight), on the edge cost and on the ranking.
        'explicit_request_multiplier': 2.0,
        # Shade only matters while the sun is up.
        'daylight_only': True,
    },
    'rain': {'advisory_probability_pct': 40, 'advisory_mm_per_h': 0.5},
    'wind': {'advisory_kmh': 30},
    'max_snapshot_age_min': 180,
}
CONFIG_VERSION = 'wx-' + hashlib.sha1(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:8]
EVIDENCE = {
    'heat': 'Street-tree density (NYC Parks Forestry Tree Points, living trees within 30 m per km) and share of the edge beside '
            'NYC Parks properties, from the Nature sub-indicators. A tree-cover proxy, not measured shade or canopy.',
}


def _num(v, lo, hi):
    return float(v) if type(v) in (int, float) and lo <= v <= hi else None


def validate_snapshot(doc):
    """Request field `weather` → normalized snapshot, or None when absent. Unknown values stay None (never 'normal weather')."""
    if doc is None:
        return None
    if not isinstance(doc, dict):
        raise ValueError('weather must be an object')
    snap = {
        'source': str(doc.get('source') or '')[:80] or None,
        'kind': doc.get('kind') if doc.get('kind') in ('forecast_window', 'current') else None,
        'valid_from': str(doc.get('valid_from') or '')[:32] or None,
        'valid_to': str(doc.get('valid_to') or '')[:32] or None,
        'age_min': _num(doc.get('age_min'), 0, 1e6),
        'feels_like_max_c': _num(doc.get('feels_like_max_c'), -60, 70),
        'temperature_max_c': _num(doc.get('temperature_max_c'), -60, 70),
        'precip_probability_max_pct': _num(doc.get('precip_probability_max_pct'), 0, 100),
        'precip_max_mm_per_h': _num(doc.get('precip_max_mm_per_h'), 0, 500),
        'wind_max_kmh': _num(doc.get('wind_max_kmh'), 0, 400),
        'daylight': doc.get('daylight') if isinstance(doc.get('daylight'), bool) else None,
        'mode': doc.get('mode') if doc.get('mode') in ('auto', 'off') else 'auto',
        'priority': 'high' if doc.get('priority') == 'high' else 'normal',
        'alerts': [str(a)[:160] for a in (doc.get('alerts') or [])[:5]] if isinstance(doc.get('alerts'), list) else [],
    }
    return snap


def heat_level(feels_like_c):
    h = CONFIG['heat']
    if feels_like_c is None:
        return None
    return max(0.0, min(1.0, (feels_like_c - h['feels_like_start_c']) / (h['feels_like_full_c'] - h['feels_like_start_c'])))


def assess(snap, evidence_available=True):
    """What the weather means for this request. `routing.active` is True only when a factor has spatial evidence AND applies."""
    out = {'config_version': CONFIG_VERSION, 'snapshot': snap, 'data_available': False, 'factors': [],
           'routing': {'status': 'unavailable', 'active': False, 'factor': None, 'level': 0.0, 'reason': 'No weather snapshot was sent.'}}
    if not snap:
        return out
    usable = snap['kind'] is not None and (snap['age_min'] is None or snap['age_min'] <= CONFIG['max_snapshot_age_min'])
    out['data_available'] = usable and any(snap[k] is not None for k in ('feels_like_max_c', 'precip_probability_max_pct', 'wind_max_kmh'))
    if not out['data_available']:
        out['routing'].update(reason='Weather data is missing or older than %d minutes; routes use the static experience scores only.' % CONFIG['max_snapshot_age_min'])
        return out
    h = heat_level(snap['feels_like_max_c'])
    if h is not None:
        out['factors'].append({'factor': 'heat', 'value_c': snap['feels_like_max_c'], 'level': round(h, 2), 'routing_capable': True,
                               'note': 'Feels-like temperature during the walk' if h > 0 else 'Below the heat-caution band'})
    rain = (snap['precip_probability_max_pct'] or 0) >= CONFIG['rain']['advisory_probability_pct'] or (snap['precip_max_mm_per_h'] or 0) >= CONFIG['rain']['advisory_mm_per_h']
    if snap['precip_probability_max_pct'] is not None:
        out['factors'].append({'factor': 'rain', 'probability_pct': snap['precip_probability_max_pct'], 'mm_per_h': snap['precip_max_mm_per_h'],
                               'advisory': rain, 'routing_capable': False,
                               'note': 'No covered-walkway, scaffolding or ponding data is connected, so rain cannot change the route.'})
    if snap['wind_max_kmh'] is not None:
        out['factors'].append({'factor': 'wind', 'kmh': snap['wind_max_kmh'], 'advisory': snap['wind_max_kmh'] >= CONFIG['wind']['advisory_kmh'],
                               'routing_capable': False, 'note': 'No street-level wind-exposure data is connected; no route is claimed to be more sheltered.'})
    r = out['routing']
    if snap['mode'] == 'off':
        r.update(status='not_active', reason='Weather-aware routing was switched off.')
    elif h is None or h <= 0:
        r.update(status='not_active', reason='No weather factor with spatial evidence applies right now (feels-like temperature is below the heat-caution band); the static ranking is kept.')
    elif CONFIG['heat']['daylight_only'] and snap['daylight'] is False:
        r.update(status='not_active', reason='It is hot, but the walk is after dark, so tree cover does not change sun exposure.')
    elif not evidence_available:
        r.update(status='unavailable', reason='Tree-cover evidence is not loaded on this server.')
    else:
        mult = CONFIG['heat']['explicit_request_multiplier'] if snap['priority'] == 'high' else 1.0
        r.update(status='active', active=True, factor='heat', level=round(h, 2), multiplier=mult,
                 reason=f"Feels-like {snap['feels_like_max_c']:.0f} °C during the walk: edges with less street-tree / park cover cost more"
                        + (' (you asked for a cooler walk, so this counts double).' if mult > 1 else '.'))
    return out


def edge_cover(gscore, segment_raw):
    """0..1 tree-cover proxy of one edge geometry, or None without evidence."""
    raws = [gscore['raw']] if gscore.get('raw') else [segment_raw[m] for m in gscore.get('m') or () if m in segment_raw]
    vals = []
    for r in raws:
        t, p = r.get('tree_km'), r.get('park_pct')
        if t is None and p is None:
            continue
        vals.append(max(min(1.0, (t or 0) / CONFIG['heat']['tree_km_full_cover']), (p or 0) / 100))
    return sum(vals) / len(vals) if vals else None


def exposure_table(gscores, segment_raw):
    """Per-geometry heat exposure (1 − cover); edges without evidence take the network median (neutral, never worst)."""
    cover = [edge_cover(g, segment_raw) for g in gscores]
    known = sorted(c for c in cover if c is not None)
    median = known[len(known) // 2] if known else 0.5
    return [1 - (c if c is not None else median) for c in cover], [c is not None for c in cover], round(1 - median, 3)
