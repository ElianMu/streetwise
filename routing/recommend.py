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
from .places import store, _metres

EVIDENCE_RANK = {'confirmed_menu_match': 0, 'probable_match_review': 1, 'unverified': 2, 'not_checked': 2, 'not_found_in_checked_sources': 3, None: 2}
CHECK_LIMIT, WORKERS, DEADLINE_S = 6, 3, 25   # 3 parallel page reads keep memory bounded on the server


def _pt(d, name):
    if not isinstance(d, dict) or type(d.get('lat')) not in (int, float) or type(d.get('lon')) not in (int, float):
        raise ValueError(f'{name} needs numeric lat/lon')
    return {'lat': float(d['lat']), 'lon': float(d['lon']), 'name': str(d.get('name') or name)[:120]}


def recommend_food(planner, doc):
    t0 = time.time()
    ratings_required = doc.get('ratings_required') is True
    min_rating = doc.get('minimum_rating')
    max_price = doc.get('max_item_price_usd')
    for label, value, upper in [('minimum_rating', min_rating, 5), ('max_item_price_usd', max_price, 10000)]:
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= upper):
            raise ValueError(label + ' must be a non-negative numeric limit')
    ratings_required = ratings_required or min_rating is not None
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
    search_points=[_pt(doc['search_near'],'search_near')] if doc.get('search_near') else seq
    for p in search_points:
        for c in S.search(p, cats, radius_m=int(doc.get('radius_m') or 700), limit=30, cuisine=cuisine):
            found.setdefault(c['place_id'], c)
    # Dense Midtown can have >30 nearer food businesses. Known actual menu venues
    # must be considered before that nearest-place cap; expired receipts are hints only.
    known=set()
    if item:
        for pid in menu.candidate_venues(item):
            c=S.get(pid)
            if not c or c['category'] not in cats:continue
            raw=S.raw(pid)
            if cuisine and cuisine.lower() not in f"{raw.get('cuisine') or ''};{(raw.get('dcuisine') or '').lower()}":continue
            distance=min(_metres(c['coordinates'],p) for p in search_points)
            if distance>int(doc.get('radius_m') or 700):continue
            known.add(c['place_id']);found.setdefault(c['place_id'],{**c,'straight_line_m':round(distance)})
    cands = list(found.values())
    # prefer places whose own tags hint at the item (still not evidence), then nearest
    hint = (item or '').lower()
    def pre(c):
        r = c.get('restaurant') or {}
        tag = 1 if hint and ((r.get('drink_tags_osm') or {}).get(hint) == 'yes' or ('espresso' in (r.get('drink_tags_osm') or {}) and hint in ('cappuccino', 'latte', 'flat white'))) else 0
        recorded=menu.cached_evidence(c['place_id'],item) if item else None
        return (-bool(recorded), -bool(c['place_id'] in known or (c.get('restaurant') or {}).get('menu_url')), -tag, -bool(c.get('official_website')), c['straight_line_m'])
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
    rating_results = {}
    rating_ready = any(providers.configured()[k] for k in ('google_places','yelp_fusion','foursquare'))
    if rating_ready:
        def rate(c):
            return c['place_id'], providers.ratings({'place_id': c['place_id'], 'name': c['name'], 'address': c['address'], **c['coordinates']})
        with cf.ThreadPoolExecutor(max_workers=4) as executor:
            rating_results.update(executor.map(rate, cands[:4]))
    # item evidence for the best few with an official website (parallel, bounded)
    menus = {}
    if item:
        menus={c['place_id']:r for c in cands if (r:=menu.cached_evidence(c['place_id'],item))}
    def fresh_eligible(c):
        m=menus.get(c['place_id']);w=walk.get(c['place_id'])
        if not m or m.get('status')!='confirmed_menu_match' or not w or c['routing_coverage']!='manhattan_network' or c['quality_status']=='closed':return False
        if max_detour is not None and w[0]/WALK_SPEED_M_PER_MIN>max_detour:return False
        eta=departure+timedelta(minutes=w[0]/WALK_SPEED_M_PER_MIN/(2 if len(seq)>=2 else 1))
        return oh.is_open_at(c.get('opening_hours'),eta) is not False
    fresh_ready=not ratings_required and max_price is None and any(fresh_eligible(c) for c in cands)
    to_check = [c for c in cands if (c.get('official_website') or (c.get('restaurant') or {}).get('menu_url')) and c['place_id'] not in menus][:CHECK_LIMIT] if item and not fresh_ready and (not ratings_required or rating_ready) else []
    if to_check:
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(menu.verify, {'place_id': c['place_id'], 'name': c['name'], 'item': item}): c['place_id'] for c in to_check}
            try:
                for f in cf.as_completed(futs, timeout=DEADLINE_S):
                    try:
                        menus[futs[f]] = f.result()
                    except Exception as e:
                        menus[futs[f]] = {'status': 'unverified', 'reason': f'menu check failed ({type(e).__name__})'}
            except cf.TimeoutError:
                for f, pid in futs.items():
                    f.cancel()
                    menus.setdefault(pid, {'status': 'not_checked', 'reason': f'The menu check did not finish within {DEADLINE_S} s.'})
    results = []
    for c in cands:
        w = walk.get(c['place_id'])
        detour_m = w[0] if w else None
        eta = departure + timedelta(minutes=(detour_m or 0) / WALK_SPEED_M_PER_MIN / (2 if len(seq) >= 2 else 1))
        open_eta = oh.is_open_at(c.get('opening_hours'), eta)
        m = menus.get(c['place_id'])
        if item and not m:
            m = {'status': 'not_checked', 'reason': 'Fresh source-confirmed matches are available; other venues remain unchecked.' if fresh_ready else 'No official website in the checked sources, so no menu could be read.' if not c.get('official_website')
                 else f'Not checked: only the {CHECK_LIMIT} nearest places with an official website are checked per request.'}
        status = m['status'] if m else None
        excluded = []
        if c['routing_coverage'] != 'manhattan_network': excluded.append('Discovery only: outside verified walking-route coverage')
        ratings = rating_results.get(c['place_id'], {'status': 'blocked_by_provider_access' if not rating_ready else 'not_checked', 'ratings': []})
        rating_matches = [r for r in ratings['ratings'] if type(r.get('rating')) in (int,float) and r.get('rating_scale')]
        if ratings_required and not rating_matches: excluded.append('requested review evidence unavailable (not a low rating)')
        if min_rating is not None and rating_matches and not any(r['rating']/r['rating_scale']*5 >= min_rating for r in rating_matches):
            excluded.append('verified provider rating does not meet the requested minimum')
        if max_price is not None:
            if not m or m.get('price') is None or m.get('currency') != 'USD' or m.get('price_verification') != 'structured_source':
                excluded.append('budget cannot be verified: no directly associated verified USD item price')
            elif m['price'] > max_price: excluded.append('verified item price exceeds budget')
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
        r['ratings'] = None if r['classification']=='excluded' else rating_results.get(r['place']['place_id'], {'status': 'blocked_by_provider_access' if not rating_ready else 'not_checked', 'ratings': []})
    order = {'meets_request': 0, 'needs_review': 1, 'not_confirmed': 2, 'excluded': 3}
    grade = {'A': 0, 'B': 1, 'C': 2}
    results.sort(key=lambda r: (order[r['classification']], EVIDENCE_RANK.get(r['item_status'], 2), r['detour_m'] if r['detour_m'] is not None else 1e9,
                                grade.get(((r['place'].get('restaurant') or {}).get('inspection') or {}).get('grade'), 3)))
    for n, r in enumerate(results, 1):
        r['rank'] = n
        r['explanation'] = explain(r, item)
    return {'item': item, 'cuisine': cuisine, 'categories': cats, 'departure': departure.astimezone(oh.NY).isoformat(timespec='minutes'),
            'status': 'blocked_by_provider_access' if ratings_required and not rating_ready else 'ok' if any(r['classification'] == 'meets_request' for r in results) else 'no_confirmed_match' if item else 'ok',
            'candidates': results, 'checked_menus': sum(1 for m in menus.values() if m['status'] != 'not_checked'), 'providers_configured': providers.configured(), 'compute_seconds': round(time.time() - t0, 2),
            'method': 'Fresh official-menu matches are reused before bounded new website checks; known expired receipts are discovery hints only. Hard filters first (DOHMH closure, closed at arrival, detour limit, reachability); then requested-item evidence, '
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
