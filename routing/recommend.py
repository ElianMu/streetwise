"""Evidence-aware food recommendations (POST /api/recommend/food).

  intent → discover places (place store) → hard filters (DOHMH closure, closed at arrival, walking-detour limit)
  → item evidence on the official menu (routing/menu.py) → per-provider ratings (routing/providers.py, if configured)
  → rank the candidates that pass → explain.

A requested item is satisfied only by `confirmed_menu_match`; `probable_match_review` is shown as needing review; anything
else is listed as "not confirmed" and never presented as meeting the request. Missing ratings or menus are neither treated as
the worst nor as satisfying. Each candidate's explanation separates verified facts, derived metrics, the rule-based
interpretation and unknowns. No language model writes these facts.
"""
import concurrent.futures as cf
import math, time
from datetime import datetime, timedelta, timezone

from . import hours as oh
from . import menu, providers
from .engine import WALK_SPEED_M_PER_MIN, RoutingError
from .places import store

EVIDENCE_RANK = {'confirmed_menu_match': 0, 'probable_match_review': 1, 'unverified': 2, 'not_checked': 2, 'not_found_in_checked_sources': 3, None: 2}
CHECK_LIMIT, DEADLINE_S = 6, 25


def _pt(d, name):
    if not isinstance(d, dict) or type(d.get('lat')) not in (int, float) or type(d.get('lon')) not in (int, float):
        raise ValueError(f'{name} needs numeric lat/lon')
    return {'lat': float(d['lat']), 'lon': float(d['lon']), 'name': str(d.get('name') or name)[:120]}


def recommend_food(planner, doc):
    t0 = time.time()
    item = (doc.get('item') or '').strip()[:60] or None
    cuisine = (doc.get('cuisine') or '').strip()[:40] or None
    cats = [c for c in (doc.get('categories') or [doc.get('category') or 'restaurants']) if c in ('restaurants', 'cafes', 'bakeries', 'bars')] or ['restaurants']
    seq = [_pt(p, f'point {k}') for k, p in enumerate((doc.get('sequence') or [])[:12])] or [_pt(doc.get('near'), 'near')]
    max_detour = doc.get('max_detour_min') if type(doc.get('max_detour_min')) in (int, float) else None
    dep = doc.get('departure')
    try:
        departure = datetime.fromisoformat(dep) if isinstance(dep, str) else datetime.now(timezone.utc)
    except ValueError:
        raise ValueError('departure must be ISO 8601')
    S = store()
    found = {}
    for p in seq:
        for c in S.search(p, cats, radius_m=int(doc.get('radius_m') or 700), limit=30, cuisine=cuisine):
            found.setdefault(c['place_id'], c)
    cands = list(found.values())
    # prefer places whose own tags hint at the item (still not evidence), then nearest
    hint = (item or '').lower()
    def pre(c):
        r = c.get('restaurant') or {}
        tag = 1 if hint and ((r.get('drink_tags_osm') or {}).get(hint) == 'yes' or ('espresso' in (r.get('drink_tags_osm') or {}) and hint in ('cappuccino', 'latte', 'flat white'))) else 0
        return (-tag, -bool(c.get('official_website')), c['straight_line_m'])
    cands.sort(key=pre)
    cands = cands[:12]
    net = planner.net
    # real walking cost: detour against the current walk, or one-way distance from the single point
    if len(seq) >= 2:
        from .itinerary import detours
        try:
            dt = detours(planner, {'sequence': seq, 'candidates': [{'id': c['place_id'], 'name': c['name'], **c['coordinates']} for c in cands]})
            walk = {x['id']: (x['detour_m'], x.get('after_index')) for x in dt['candidates'] if x['reachable']}
        except RoutingError:
            walk = {}
    else:
        try:
            src = net.snap(seq[0]['lon'], seq[0]['lat'], 'origin')
            snaps, ids = [], []
            for c in cands:
                try:
                    snaps.append(net.snap(c['coordinates']['lon'], c['coordinates']['lat'], c['name'])); ids.append(c['place_id'])
                except RoutingError:
                    pass
            walk = {i: (d, 0) for i, d in zip(ids, net.distances(src, snaps)) if d is not None}
        except RoutingError:
            walk = {}
    # item evidence for the best few with an official website (parallel, bounded)
    to_check = [c for c in cands if c.get('official_website')][:CHECK_LIMIT] if item else []
    menus = {}
    if to_check:
        with cf.ThreadPoolExecutor(max_workers=CHECK_LIMIT) as ex:
            futs = {ex.submit(menu.verify, {'place_id': c['place_id'], 'name': c['name'], 'item': item}): c['place_id'] for c in to_check}
            try:
                for f in cf.as_completed(futs, timeout=DEADLINE_S):
                    try:
                        menus[futs[f]] = f.result()
                    except Exception as e:
                        menus[futs[f]] = {'status': 'unverified', 'reason': f'menu check failed ({type(e).__name__})'}
            except cf.TimeoutError:
                pass
    results = []
    for c in cands:
        w = walk.get(c['place_id'])
        detour_m = w[0] if w else None
        eta = departure + timedelta(minutes=(detour_m or 0) / WALK_SPEED_M_PER_MIN / (2 if len(seq) >= 2 else 1))
        open_eta = oh.is_open_at(c.get('opening_hours'), eta)
        m = menus.get(c['place_id'])
        if item and not m:
            m = {'status': 'not_checked', 'reason': 'No official website in the checked sources, so no menu could be read.' if not c.get('official_website')
                 else f'Not checked: only the {CHECK_LIMIT} nearest places with an official website are checked per request.'}
        status = m['status'] if m else None
        excluded = []
        if c['quality_status'] == 'closed':
            excluded.append('closed by NYC DOHMH')
        if open_eta is False:
            excluded.append(f'closed at the estimated arrival ({eta.astimezone(oh.NY).strftime("%H:%M")}) per OpenStreetMap hours')
        if detour_m is None and c['routing_coverage'] == 'manhattan_network':
            excluded.append('not reachable on the walking network')
        if max_detour is not None and detour_m is not None and detour_m / WALK_SPEED_M_PER_MIN > max_detour:
            excluded.append(f'detour {detour_m / WALK_SPEED_M_PER_MIN:.0f} min exceeds {max_detour:g} min')
        if item:
            meets = 'meets_request' if status == 'confirmed_menu_match' else 'needs_review' if status == 'probable_match_review' else 'not_confirmed'
        else:
            meets = 'meets_request'
        results.append({'place': {k: c[k] for k in ('place_id', 'index_id', 'name', 'category', 'address', 'borough', 'coordinates', 'official_website', 'opening_hours',
                                                     'quality_status', 'routing_coverage', 'data_sources', 'phone')} | {'restaurant': c.get('restaurant')},
                        'menu': m, 'item_status': status, 'open_at_arrival': open_eta, 'eta': eta.astimezone(oh.NY).isoformat(timespec='minutes'),
                        'detour_m': round(detour_m, 1) if detour_m is not None else None,
                        'detour_min': round(detour_m / WALK_SPEED_M_PER_MIN, 1) if detour_m is not None else None,
                        'insert_after_index': w[1] if w else None, 'classification': 'excluded' if excluded else meets, 'excluded_because': excluded})
    # ratings only for those still in the running (provider calls are limited and not stored)
    for r in results:
        r['ratings'] = providers.ratings({'place_id': r['place']['place_id'], 'name': r['place']['name'], 'address': r['place']['address'], **r['place']['coordinates']}) \
            if r['classification'] != 'excluded' else None
    order = {'meets_request': 0, 'needs_review': 1, 'not_confirmed': 2, 'excluded': 3}
    grade = {'A': 0, 'B': 1, 'C': 2}
    results.sort(key=lambda r: (order[r['classification']], EVIDENCE_RANK.get(r['item_status'], 2), r['detour_m'] if r['detour_m'] is not None else 1e9,
                                grade.get(((r['place'].get('restaurant') or {}).get('inspection') or {}).get('grade'), 3)))
    for n, r in enumerate(results, 1):
        r['rank'] = n
        r['explanation'] = explain(r, item)
    return {'item': item, 'cuisine': cuisine, 'categories': cats, 'departure': departure.astimezone(oh.NY).isoformat(timespec='minutes'),
            'status': 'ok' if any(r['classification'] == 'meets_request' for r in results) else 'no_confirmed_match' if item else 'ok',
            'candidates': results, 'checked_menus': len(menus), 'providers_configured': providers.configured(), 'compute_seconds': round(time.time() - t0, 2),
            'method': 'Hard filters first (DOHMH closure, closed at arrival, detour limit, reachability); then requested-item evidence, '
                      'walking detour on the network, health-inspection grade as a tie-break. Ratings are shown per provider and not blended.'}


def explain(r, item):
    p, insp = r['place'], ((r['place'].get('restaurant') or {}).get('inspection') or {})
    facts, derived, unknown = [], [], []
    m = r.get('menu') or {}
    if item and m.get('status') == 'confirmed_menu_match':
        price = f", listed at ${m['price']:.2f}" if m.get('price') else ''
        facts.append(f"“{m.get('matched_item')}” is on the official menu ({m.get('menu_source_url')}){price}; checked {m.get('checked_at')}.")
    if insp.get('grade'):
        facts.append(f"NYC Health inspection grade {insp['grade']} ({insp.get('grade_date')}); last inspected {insp.get('last_inspection')}.")
    for rt in (r.get('ratings') or {}).get('ratings', []):
        facts.append(f"{rt['provider']} rating {rt['rating']}/{rt['rating_scale']} from {rt.get('review_count')} reviews.")
    if p.get('official_website'):
        facts.append(f"Official website: {p['official_website']}.")
    if r.get('detour_min') is not None:
        derived.append(f"Adds {r['detour_m']:.0f} m / {r['detour_min']:.0f} min of walking on the pedestrian network.")
    if r.get('open_at_arrival') is True:
        derived.append(f"Open at the estimated arrival {r['eta'][11:16]} according to its mapped hours.")
    if item and m.get('status') != 'confirmed_menu_match':
        unknown.append(f"Whether it serves {item}: {m.get('reason') or 'no official menu could be checked'}")
    if not (r.get('ratings') or {}).get('ratings'):
        unknown.append('Ratings and review counts: no rating provider is configured.' if (r.get('ratings') or {}).get('status') == 'blocked_by_provider_access' else 'Ratings: not available.')
    if r.get('open_at_arrival') is None:
        unknown.append('Opening hours at arrival: not mapped or not machine-readable.')
    unknown.append('Today’s stock and prices: a menu listing does not confirm them.')
    interp = ('Recommended: the requested item is confirmed and the detour is short.' if r['classification'] == 'meets_request' and item else
              'Possible match: please review the menu evidence.' if r['classification'] == 'needs_review' else
              'Listed for reference only: it does not meet the request on current evidence.' if r['classification'] == 'not_confirmed' else
              'Excluded: ' + '; '.join(r['excluded_because']) if r['classification'] == 'excluded' else 'Matches the requested kind of place.')
    return {'verified_facts': facts, 'derived_metrics': derived, 'interpretation': interp, 'interpretation_basis': 'rule-based (no language model)', 'unknown': unknown}
