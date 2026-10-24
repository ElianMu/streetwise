"""Multi-stop city walks on the existing pedestrian engine (POST /api/itinerary).

Inputs are real places chosen in the browser (search providers or the discovery POI index); nothing here invents a place.
  origin            start point
  end               {'mode': 'fixed' | 'round' | 'hotel' | 'open', 'place': {...} for fixed/hotel}
  stops             concrete places: {'id','name','lat','lon','required','order' (int|None),'visit_min'}
  slots             "one of these" needs (a café with cappuccino, a pharmacy): {'slot_id','label','required','visit_min','candidates':[place+score]}
  pool              optional extra discoveries: {'label','max_stops','candidates':[place+score+visit_min]}
  constraints       max_minutes (walking), max_km, max_outing_minutes (walking + visits)

Method (reported in the response, never claimed optimal unless it is):
  1. Snap every place to the routable graph (same snap as routing; places off the network are reported, not routed).
  2. Real network distance matrix: one Dijkstra per place (RoutePlanner.net.distances), metres → minutes at 4.8 km/h.
  3. Required stops and required slots: exact search over orders (and slot choices) when small, otherwise cheapest
     insertion + 2-opt. Explicitly ordered stops keep their relative order. Required stops are never dropped: if the
     budget cannot hold them, the itinerary is returned as not feasible with the reason.
  4. Optional slots and pool places: greedy insertion by value per added minute while every budget still holds.
  5. Each leg is routed with the experience cost (λ 0.8, the user's weights); if that breaks a budget the legs fall back to
     shortest paths. Legs are stitched into one Route Object (continuous OSM edges, same contract as /api/routes).
"""
import itertools, math, re, time

from .engine import RoutingError, WALK_SPEED_M_PER_MIN, preference_weights
from . import validation as qa
from . import hours as oh
from datetime import datetime, timedelta, timezone
from . import maneuvers as mv

MAX_EXACT = 7            # required items up to this many: exact enumeration of orders
MAX_SLOT_CHOICES = 4     # candidates kept per slot for exact search
MAX_POINTS = 60          # matrix size guard
SCORE_M = 1500           # a slot candidate's relevance 0..1 is worth up to this many metres of extra walking


def _pt(doc, what):
    if not isinstance(doc, dict) or type(doc.get('lat')) not in (int, float) or type(doc.get('lon')) not in (int, float):
        raise ValueError(f'{what} needs numeric lat/lon')
    if not (math.isfinite(doc['lat']) and math.isfinite(doc['lon']) and -90<=doc['lat']<=90 and -180<=doc['lon']<=180):
        raise ValueError(f'{what} needs finite geographic coordinates')
    return {'id': str(doc.get('id') or what)[:120], 'name': str(doc.get('name') or what)[:160], 'lat': float(doc['lat']), 'lon': float(doc['lon']),
            'category': str(doc.get('category') or '')[:60] or None, 'address': str(doc.get('address') or '')[:200] or None,
            'source': str(doc.get('source') or '')[:80] or None, 'hours': str(doc.get('hours'))[:300] if doc.get('hours') else None}


def _norm(name):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', ' ', re.sub(r'^the\s+', '', str(name).lower())).strip()


def _near_m(a, b):
    return math.hypot((a['lon'] - b['lon']) * 84414.3, (a['lat'] - b['lat']) * 111049.7)


def _visit(doc, default=0):
    v = doc.get('visit_min', default)
    return float(v) if type(v) in (int, float) and 0 <= v <= 600 else float(default)


def validate_request(doc):
    if not isinstance(doc, dict):
        raise ValueError('Expected a JSON object')
    if len(doc.get('stops') or []) > 12 or len(doc.get('slots') or []) > 6:
        raise RoutingError('Too many required stops/discovery groups; split the walk instead of dropping requirements')
    origin = _pt(doc.get('origin'), 'origin')
    if (doc.get('constraints') or {}).get('step_free'):
        raise RoutingError('Verified step-free access is unavailable; no route can be recommended')
    end = doc.get('end') or {'mode': 'open'}
    mode = end.get('mode') if end.get('mode') in ('fixed', 'round', 'hotel', 'open') else None
    if not mode:
        raise ValueError('end.mode must be fixed, round, hotel or open')
    end_place = _pt(end.get('place'), 'end') if mode in ('fixed', 'hotel') else None
    stops = []
    def check_public_access(p):
        from .places import store, food_access, FOOD
        r = store().raw(p['id'])
        if r and r.get('cat') in FOOD and not food_access(r)['recommendation_eligible']:
            raise RoutingError('This food listing has no verified public access or is restricted; it cannot be added as a public restaurant stop.')
    def required_items(value):
        items=value.get('required_items') or []
        if not isinstance(items,list) or len(items)>5 or any(not isinstance(x,str) or not x.strip() or len(x)>60 for x in items):raise ValueError('Invalid required menu items')
        if value.get('required_item'):
            legacy=value['required_item']
            if not isinstance(legacy,str) or not legacy.strip() or len(legacy)>60:raise ValueError('Invalid required menu item')
            items=[*items,legacy]
        if len(set(x.strip().lower() for x in items))>5:raise ValueError('Too many required menu items')
        return list(dict.fromkeys(x.strip().lower() for x in items))
    for k, s in enumerate((doc.get('stops') or [])[:12]):
        p = _pt(s, f'stop {k + 1}')
        check_public_access(p)
        items=required_items(s)
        for item in items:
            from .menu import cached_evidence
            evidence = cached_evidence(p['id'], item)
            if not evidence or evidence['status'] != 'confirmed_menu_match':
                raise RoutingError('Required menu item is not verified for chosen place; check the official menu first')
        order = s.get('order')
        stops.append({**p, 'required': s.get('required', True) is not False, 'order': order if type(order) is int else None,
                      'required_item':s.get('required_item'), 'required_items':items, 'visit_min': _visit(s), 'visit_estimated': bool(s.get('visit_estimated', True)), 'kind': 'stop'})
    slots = []
    for k, sl in enumerate((doc.get('slots') or [])[:6]):
        cands = [{**_pt(c, 'candidate'), 'score': float(c.get('score') or 0), 'evidence': c.get('evidence')} for c in (sl.get('candidates') or [])[:8]]
        for candidate in cands: check_public_access(candidate)
        items=required_items(sl)
        if items:
            from .menu import cached_evidence
            cands = [c for c in cands if all((cached_evidence(c['id'], item) or {}).get('status') == 'confirmed_menu_match' for item in items)]
        if not cands and sl.get('required', True) is not False:
            raise RoutingError('Required place has no candidates: ' + str(sl.get('label') or sl.get('slot_id') or 'stop'))
        if cands:
            slots.append({'slot_id': str(sl.get('slot_id') or f'slot{k}')[:40], 'label': str(sl.get('label') or 'Stop')[:80],
                          'required': sl.get('required', True) is not False, 'required_item':sl.get('required_item'), 'required_items':items, 'visit_min': _visit(sl, 15), 'candidates': cands,
                          'order': sl.get('order') if type(sl.get('order')) is int else None})
    pool = doc.get('pool') or {}
    pool_c = [{**_pt(c, 'candidate'), 'score': float(c.get('score') or 0), 'visit_min': _visit(c, 20), 'evidence': c.get('evidence'),
               'group': str(c.get('group') or '')[:40] or None} for c in (pool.get('candidates') or [])[:30]]
    max_pool = pool.get('max_stops') if type(pool.get('max_stops')) is int else 4
    c = doc.get('constraints') or {}
    cons = {}
    for k, lo in (('max_minutes', 10), ('max_km', 0.1), ('max_outing_minutes', 10)):
        v = c.get(k)
        if v is not None:
            if type(v) not in (int, float) or not math.isfinite(v) or v < lo:
                raise ValueError(f'constraints.{k} must be a number ≥ {lo}')
            cons[k] = float(v)
    cons['require_open'] = c.get('require_open') is True
    cons['avoid_stairs'] = c.get('avoid_stairs') is True
    prefs = doc.get('preferences') or {}
    dep = doc.get('departure')
    try:
        departure = datetime.fromisoformat(dep) if isinstance(dep, str) else None
        if departure and departure.tzinfo is None:
            departure = departure.replace(tzinfo=oh.NY)
    except ValueError:
        raise ValueError('departure must be an ISO 8601 date-time')
    if cons.get('require_open') and departure is None: raise ValueError('departure is required to verify opening hours')
    return {'departure': departure,'origin': origin, 'end_mode': mode, 'end_place': end_place, 'stops': stops, 'slots': slots,
            'pool': {'label': str(pool.get('label') or 'Discovered places')[:80], 'max_stops': max(0, min(8, max_pool)), 'candidates': pool_c},
            'constraints': cons, 'preferences': prefs if isinstance(prefs, dict) else {}, 'theme': str(doc.get('theme') or '')[:120] or None}


class Planner:
    def __init__(self, route_planner):
        self.rp, self.net = route_planner, route_planner.net

    def plan(self, req, weather=None):
        t0 = time.time()
        net, cons = self.net, req['constraints']
        notes, skipped = [], []
        avoid = cons.get('avoid_stairs')
        allowed = (lambda i: not net.edges[i][7]['_steps']) if avoid else (lambda i: True)

        # 1. snap everything that may be visited -------------------------------------------------------------
        points = []  # each: dict(place, snap, role, ...)

        def add(place, role, **extra):
            from .places import store
            known = store().get(place['id'])
            if known and not known.get('public_access',{}).get('recommendation_eligible',True):
                return None, 'food listing has restricted or unverified public access; a permit alone does not establish a visitor-facing restaurant'
            if known and _near_m(place,{'lat':known['coordinates']['lat'],'lon':known['coordinates']['lon']}) > 30:
                return None, 'place ID and coordinates disagree with the canonical source; refresh the selection'
            if known and (known['quality_status']=='closed' or str(known.get('operational_status') or '').lower() in ('not operational','closed','inactive')):
                return None, 'source reports this place unavailable; refresh evidence before visiting'
            try:
                sn = net.snap(place['lon'], place['lat'], place['name'])
            except RoutingError as e:
                return None, str(e)
            points.append({**place, 'snap': sn, 'role': role, **extra})
            return len(points) - 1, None

        oi, err = add(req['origin'], 'origin')
        if oi is None:
            raise RoutingError(f"Start is outside walking-route coverage ({err}). Place search covers all five boroughs; walking routes cover Manhattan.")
        ei = None
        if req['end_mode'] in ('fixed', 'hotel'):
            ei, err = add(req['end_place'], 'end')
            if ei is None:
                raise RoutingError(f"End point is outside walking-route coverage ({err}).")
        elif req['end_mode'] == 'round':
            ei = oi
        required, optional = [], []   # items: ('stop', idx) or ('slot', [idx...], slot)
        for s in req['stops']:
            k, err = add(s, 'stop')
            if k is None:
                if s['required']:
                    raise RoutingError(f"Required stop “{s['name']}” is outside walking-route coverage ({err}).")
                skipped.append({'id': s['id'], 'name': s['name'], 'reason': 'Outside walking-route coverage'})
                continue
            (required if s['required'] else optional).append({'type': 'stop', 'idx': [k], 'visit': s['visit_min'], 'order': s['order'], 'label': s['name']})
        for sl in req['slots']:
            idxs = []
            for c in sorted(sl['candidates'], key=lambda c: -c['score']):
                k, err = add(c, 'candidate', slot=sl['slot_id'], required_item=sl.get('required_item'),required_items=sl.get('required_items'))
                if k is not None:
                    idxs.append(k)
            if not idxs and sl['required']:
                raise RoutingError('Required place has no reachable candidate: ' + sl['label'])
            if not idxs:
                (notes if not sl['required'] else skipped).append(f"No reachable candidate for {sl['label']}." if not sl['required'] else
                                                                   {'id': sl['slot_id'], 'name': sl['label'], 'reason': 'No candidate within walking-route coverage'})
                continue
            item = {'type': 'slot', 'idx': idxs, 'visit': sl['visit_min'], 'order': sl['order'], 'label': sl['label'], 'slot_id': sl['slot_id']}
            (required if sl['required'] else optional).append(item)
        pool_items = []
        fixed = [p for p in points if p['role'] in ('origin', 'end', 'stop')]
        for c in req['pool']['candidates']:
            # the same place under another source / ID is not a second stop
            if any(_norm(c['name']) == _norm(f['name']) or _near_m(c, f) < 60 for f in fixed):
                continue
            k, err = add(c, 'pool')
            if k is not None:
                pool_items.append({'type': 'stop', 'idx': [k], 'visit': c['visit_min'], 'order': None, 'label': c['name'], 'score': c['score'], 'group': c.get('group')})
        if len(points) > MAX_POINTS:
            raise ValueError(f'Too many places to compare ({len(points)}); narrow the request.')

        # 2. real network distance matrix (metres) ------------------------------------------------------------
        tm = time.time()
        cost = (lambda i: 1.0 if allowed(i) else None)
        snaps = [p['snap'] for p in points]
        M = [net.distances(snaps[a], snaps, cost) for a in range(len(points))]
        matrix_s = round(time.time() - tm, 2)
        dist = lambda a, b: 0.0 if a == b else (M[a][b] if M[a][b] is not None else math.inf)

        def walk_m(seq):
            return sum(dist(a, b) for a, b in zip(seq, seq[1:]))

        def visit_total(chosen):
            return sum(v for _, v in chosen)

        def within(seq_m, visit):
            walk_min = seq_m / WALK_SPEED_M_PER_MIN
            v = []
            if 'max_minutes' in cons and walk_min > cons['max_minutes'] + 1e-6:
                v.append(f"walking {walk_min:.0f} min exceeds the {cons['max_minutes']:g}-minute limit")
            if 'max_km' in cons and seq_m > cons['max_km'] * 1000 + 1e-6:
                v.append(f"{seq_m / 1000:.1f} km exceeds the {cons['max_km']:g} km limit")
            if 'max_outing_minutes' in cons and walk_min + visit > cons['max_outing_minutes'] + 1e-6:
                v.append(f"walking + visits {walk_min + visit:.0f} min exceeds the {cons['max_outing_minutes']:g}-minute outing")
            return v

        departure = req.get('departure')
        if cons.get('require_open'): notes.append('Opening checks use mapped source hours, not live admission or reservation availability.')
        visit_of = {}
        for it in required + optional + pool_items:
            for k in it['idx']:
                visit_of[k] = it['visit']

        def closed_count(seq):
            """Stops whose mapped hours say closed at the estimated arrival along seq (0 when no departure or hours)."""
            if not departure:
                return 0
            clock, n = 0.0, 0
            for a, b in zip(seq, seq[1:]):
                clock += dist(a, b) / WALK_SPEED_M_PER_MIN
                if b in visit_of:
                    at=departure+timedelta(minutes=clock)
                    opened=oh.is_open_at(points[b].get('hours'),at)
                    if opened is False or (cons.get('require_open') and opened is None) or oh.closes_within(points[b].get('hours'),at,visit_of[b]):
                        n += 1
                clock += visit_of.get(b, 0)
            return n

        # 3. required items: choose slot candidates and order ------------------------------------------------
        def tour(inner):
            return [oi] + inner + ([ei] if ei is not None else [])

        def order_ok(seq_items):
            ranks = [it['order'] for it in seq_items if it['order'] is not None]
            return ranks == sorted(ranks)

        method = []
        n_req = len(required)
        choice_space = 1
        for it in required:
            choice_space *= min(len(it['idx']), MAX_SLOT_CHOICES)
        best = None
        if n_req and n_req <= MAX_EXACT and math.factorial(n_req) * choice_space <= 60000:
            for picks in itertools.product(*[it['idx'][:MAX_SLOT_CHOICES] for it in required]):
                # one place never fills two needs (slot choices are compared by name: one venue may have several records)
                slot_names = [_norm(points[k]['name']) for k, it in zip(picks, required) if it['type'] == 'slot']
                fixed_names = {_norm(points[k]['name']) for k, it in zip(picks, required) if it['type'] == 'stop'}
                if len(set(slot_names)) < len(slot_names) or fixed_names & set(slot_names):
                    continue
                for perm in itertools.permutations(range(n_req)):
                    items = [required[k] for k in perm]
                    if not order_ok(items):
                        continue
                    seq = tour([picks[k] for k in perm])
                    # an order that reaches a place while it is closed loses to any order that does not
                    m = walk_m(seq) - SCORE_M * sum(points[k].get('score', 0) for k in picks) + 1e7 * closed_count(seq)
                    if best is None or m < best[0]:
                        best = (m, [picks[k] for k in perm], items)
            method.append(f'exact enumeration of {n_req} required stop(s) and slot choices (network walk minus {SCORE_M} m per unit of relevance)')
        elif n_req:
            inner, items = [], []
            for it in sorted(required, key=lambda it: (it['order'] is None, it['order'] or 0)):
                cand = None
                used = {_norm(points[j]['name']) for j in inner} if it['type'] == 'slot' else set()
                for k in it['idx'][:MAX_SLOT_CHOICES]:
                    if _norm(points[k]['name']) in used:
                        continue
                    for pos in range(len(inner) + 1):
                        trial_items = items[:pos] + [it] + items[pos:]
                        if not order_ok(trial_items):
                            continue
                        trial = tour(inner[:pos] + [k] + inner[pos:])
                        m = walk_m(trial) - SCORE_M * points[k].get('score', 0) + 1e7 * closed_count(trial)
                        if cand is None or m < cand[0]:
                            cand = (m, pos, k)
                if cand is None:
                    raise RoutingError('Required discovery groups cannot be satisfied by distinct places')
                inner.insert(cand[1], cand[2]); items.insert(cand[1], it)
            improved = True
            while improved:  # 2-opt on segments without explicit order
                improved = False
                for a in range(len(inner) - 1):
                    for b in range(a + 1, len(inner)):
                        cand_inner = inner[:a] + inner[a:b + 1][::-1] + inner[b + 1:]
                        cand_items = items[:a] + items[a:b + 1][::-1] + items[b + 1:]
                        if order_ok(cand_items) and walk_m(tour(cand_inner)) + 1e-6 < walk_m(tour(inner)):
                            inner, items, improved = cand_inner, cand_items, True
            best = (walk_m(tour(inner)), inner, items)
            method.append(f'cheapest insertion + 2-opt for {n_req} required stops (heuristic, not guaranteed optimal)')
        inner, items = (best[1], best[2]) if best else ([], [])
        chosen = [(it, it['visit']) for it in items]

        # 4. optional slots and discovered places: greedy value per added minute within budget ---------------
        extra_cands = [it for it in optional] + pool_items
        added_pool = 0
        while extra_cands:
            base_m = walk_m(tour(inner))
            best_add = None
            for it in extra_cands:
                if it in pool_items and added_pool >= req['pool']['max_stops']:
                    continue
                used = {_norm(points[j]['name']) for j in inner} | {_norm(points[oi]['name'])} | ({_norm(points[ei]['name'])} if ei is not None else set())
                for k in it['idx'][:MAX_SLOT_CHOICES]:
                    if k in inner or _norm(points[k]['name']) in used:
                        continue
                    for pos in range(len(inner) + 1):
                        trial_items = items[:pos] + [it] + items[pos:]
                        if not order_ok(trial_items):
                            continue
                        new_inner = inner[:pos] + [k] + inner[pos:]
                        m = walk_m(tour(new_inner))
                        if m == math.inf or within(m, visit_total(chosen) + it['visit']) or closed_count(tour(new_inner)) > closed_count(tour(inner)):
                            continue   # over budget, or it (or a later stop) would be reached while closed
                        added_min = (m - base_m) / WALK_SPEED_M_PER_MIN + it['visit']
                        value = 1.0 + it.get('score', points[k].get('score', 0) or 0)
                        ratio = value / max(added_min, 1.0)
                        if best_add is None or ratio > best_add[0]:
                            best_add = (ratio, it, k, pos)
            if not best_add:
                break
            _, it, k, pos = best_add
            inner.insert(pos, k); items.insert(pos, it); chosen.append((it, it['visit']))
            extra_cands.remove(it)
            if it in pool_items:
                added_pool += 1
        for it in extra_cands:
            if it['type'] == 'slot':
                skipped.append({'id': it.get('slot_id'), 'name': it['label'], 'reason': 'Optional stop did not fit the time / distance budget'})
        if optional or pool_items:
            method.append('optional stops: greedy insertion by value per added minute within the budgets (heuristic)')
        if not method:
            method.append('direct route (no intermediate stops)')

        seq = tour(inner)
        if len(seq) < 2:
            raise RoutingError('Nothing to walk to: add a destination, a stop or something to discover.')

        # 5. route each leg with the experience cost, stitch into one Route Object ----------------------------
        weights, expressed = preference_weights(req['preferences'])
        crime_pref=crime_field=None
        if req['preferences'].get('crime'):
            from . import crime
            crime_pref=crime.validate(req['preferences']['crime']);crime_field=crime.edge_field(net,crime_pref)
        water_pref=water_data=None
        if req['preferences'].get('waterfront'):
            from . import waterfront
            water_pref=waterfront.validate(req['preferences']['waterfront']);water_data=waterfront.data(net)
        util_cache = {}

        def util(gi):
            if gi not in util_cache:
                util_cache[gi] = self.rp.edge_utility(gi, weights)
            return util_cache[gi]

        def exp_cost(i):
            if not allowed(i):return None
            gi=net.edges[i][3];cost=1+.8*(1-util(gi))
            if crime_pref:cost+=1.2*(1-crime.fit(crime_field['values'][gi],crime_pref['direction'],crime_field['scale']))
            if water_pref:
                share=water_data['within_100m_share'][gi];cost+=1.2*(1-(share if water_pref['direction']=='high' else 1-share))
            return cost
        len_cost = lambda i: 1.0 if allowed(i) else None

        def route_legs(fn):
            legs, steps = [], []
            for a, b in zip(seq, seq[1:]):
                if a == b:
                    continue
                st = net.search(snaps[a], snaps[b], fn)
                if st is None:
                    raise RoutingError(f"No walkable connection between {points[a]['name']} and {points[b]['name']}.")
                legs.append((a, b, st)); steps += st
            return legs, steps

        legs, steps = route_legs(exp_cost)
        total = sum(s[2] - s[1] for s in steps)
        if within(total, visit_total(chosen)) and not within(walk_m(seq), visit_total(chosen)):
            legs, steps = route_legs(len_cost)
            notes.append('Experience-weighted legs broke a budget, so shortest legs are used.')
        o_s, d_s = snaps[seq[0]], snaps[seq[-1]]
        route = self.rp.build_route('itinerary', req['theme'] or 'Your City Walk', steps, o_s, d_s,
                                    {'lat': points[seq[0]]['lat'], 'lon': points[seq[0]]['lon']}, {'lat': points[seq[-1]]['lat'], 'lon': points[seq[-1]]['lon']})
        route['detour_percentage'] = 0.0
        violations = within(route['distance_m'], visit_total(chosen))
        route['constraints'] = {'feasible': not violations, 'violations': violations, 'avoid_stairs': bool(avoid),
                                'contains_steps': any(e['pedestrian_access']['steps'] for e in route['edges'])}
        self.rp.personalize(route, weights, expressed)
        if crime_pref:crime.apply(route,crime_pref,crime_field,weights if expressed else {})
        if water_pref:waterfront.apply(route,water_pref,net,weights if expressed else {})
        route['rank'], route['recommended'] = 1, not violations
        route['ranking_explanation'] = (f"{len(inner)} stop(s), {route['distance_m'] / 1000:.2f} km on the OSM pedestrian graph, "
                                        f"{route['estimated_duration_min']:.0f} min walking + {visit_total(chosen):.0f} min visits. "
                                        + ('Within your limits.' if not violations else 'Not feasible: ' + '; '.join(violations) + '.'))
        # stop records with real leg distances and arrival offsets (minutes after departure)
        leg_m = {}
        for a, b, st in legs:
            leg_m[(a, b)] = sum(s[2] - s[1] for s in st)
        clock, out_stops, time_issues, time_warnings = 0.0, [], [], []
        by_point = {}
        for it in items:
            for k in it['idx']:
                by_point.setdefault(k, it)
        prev = seq[0]
        for n, k in enumerate(seq[1:], 1):
            m = leg_m.get((prev, k), 0.0)
            clock += m / WALK_SPEED_M_PER_MIN
            p, it = points[k], by_point.get(k)
            is_end = n == len(seq) - 1 and ei is not None
            rec = {'seq': n, 'id': p['id'], 'name': p['name'], 'lat': p['lat'], 'lon': p['lon'], 'category': p.get('category'), 'address': p.get('address'),
                   'source': p.get('source'), 'role': 'end' if is_end and not it else p['role'], 'required': bool(it) and it in required,
                   'arrival_min': round(clock, 1), 'leg_in_m': round(m, 1), 'leg_in_min': round(m / WALK_SPEED_M_PER_MIN, 1),
                   'hours':p.get('hours'), 'required_item':p.get('required_item'), 'required_items':p.get('required_items') or [], 'visit_min': it['visit'] if it else 0, 'snap_distance_m': p['snap']['snap_distance_m'], 'evidence': p.get('evidence')}
            if it and it['type'] == 'slot':
                rec.update(slot_id=it['slot_id'], slot_label=it['label'], alternatives=[points[j]['id'] for j in it['idx'] if j != k][:5])
            if departure and it:
                at = departure + timedelta(minutes=clock)
                rec.update(arrival_time=at.astimezone(oh.NY).isoformat(timespec='minutes'), hours=p.get('hours'),
                           open_at_arrival=oh.is_open_at(p.get('hours'), at), closes_during_visit=oh.closes_within(p.get('hours'), at, rec['visit_min']))
                if rec['open_at_arrival'] is False:
                    time_issues.append(f"{p['name']} is closed at the estimated arrival {at.astimezone(oh.NY).strftime('%H:%M')} (OpenStreetMap hours)")
                elif rec['open_at_arrival'] is None and cons.get('require_open') and rec['required']:
                    time_issues.append(f"Opening hours cannot be verified for required {p['name']}")
                elif rec['closes_during_visit']:
                    time_issues.append(f"{p['name']} closes during the planned {rec['visit_min']:.0f}-minute visit")
            out_stops.append(rec)
            clock += rec['visit_min']
            prev = k
        walk_min = route['estimated_duration_min']
        if time_issues:
            violations = violations + time_issues
            route['constraints'] = {**route['constraints'], 'feasible': False, 'violations': violations}
            route['recommended'] = False
        along, stops_mv = 0.0, []
        for k, s in enumerate(out_stops):
            along += s['leg_in_m']
            stops_mv.append({'name': s['name'], 'distance_along_route_m': along, 'required': s['required'], 'final': k == len(out_stops) - 1,
                             'visit_min': s['visit_min'], 'leg_id': k})
        route['maneuvers'] = mv.build(route, net, stops_mv)
        from .engine import route_signature
        route['route_signature'] = route_signature(route)
        route['validation'] = qa.validate(route, net, {**cons},
                                          [{'name': s['name'], 'lat': s['lat'], 'lon': s['lon'], 'required': s['required'] or s['role'] == 'end',
                                            'snap_distance_m': s['snap_distance_m'], 'open_at_arrival': s.get('open_at_arrival'),
                                            'closes_during_visit': s.get('closes_during_visit')} for s in out_stops])
        self.rp.remember([route])
        pool_requested = min(req['pool']['max_stops'], len(pool_items))
        itinerary = {'end_mode': req['end_mode'], 'pool': {'requested': pool_requested, 'added': added_pool}, 'start': {k: points[oi][k] for k in ('id', 'name', 'lat', 'lon')},
                     'stops': out_stops, 'skipped': skipped, 'notes': notes, 'method': method,
                     'totals': {'walk_m': route['distance_m'], 'walk_min': walk_min, 'visit_min': visit_total(chosen),
                                'outing_min': round(walk_min + visit_total(chosen), 1), 'stops': len(inner)},
                     'constraints': {**cons, 'feasible': not violations, 'violations': violations},
                     'departure': departure.astimezone(oh.NY).isoformat(timespec='minutes') if departure else None, 'time_warnings': time_warnings,
                     'matrix': {'points': len(points), 'seconds': matrix_s, 'basis': 'network shortest-path metres (Dijkstra on the OSM pedestrian graph)'},
                     'coverage': 'Walking routes use the Manhattan OSM pedestrian graph; places elsewhere can be searched but not routed.'}
        return {'network_version': net.network_version, 'score_version': net.score_version, 'routes': [route], 'itinerary': itinerary,
                'feasible_count': int(not violations), 'shortest_distance_m': route['distance_m'],
                'constraints_used': {'max_minutes': cons.get('max_minutes'), 'max_km': cons.get('max_km'), 'max_outing_minutes': cons.get('max_outing_minutes'),
                                     'max_detour_pct': None, 'avoid_detours': False, 'avoid_stairs': bool(avoid)},
                'preferences_used': {k: {'weight': w, 'direction': d} for k, (w, d) in weights.items()}, 'preferences_expressed': expressed or bool(crime_pref) or bool(water_pref),
                'independent_preferences_used':{**({'crime':crime.public_preference(crime_pref)} if crime_pref else {}),**({'waterfront':water_pref} if water_pref else {})},
                'compute_seconds': round(time.time() - t0, 2),
                'notes': ['Walking time uses a fixed 4.8 km/h planning pace. Visit durations are estimates you can change.']}


def detours(route_planner, doc):
    """POST /api/detours: for each candidate place, the cheapest real-network detour of inserting it between two
    consecutive points of the current walk (origin, stops, end). Used by "find along my walk"."""
    net = route_planner.net
    seq = [_pt(p, f'point {k}') for k, p in enumerate((doc.get('sequence') or [])[:14])]
    cands = [_pt(c, 'candidate') for c in (doc.get('candidates') or [])[:20]]
    if len(seq) < 2 or not cands:
        raise ValueError('Need a walk of at least two points and one candidate')
    snap = lambda p: net.snap(p['lon'], p['lat'], p['name'])
    try:
        s_seq = [snap(p) for p in seq]
    except RoutingError as e:
        raise RoutingError(f'The current walk is outside routing coverage ({e}).')
    legs = [net.distances(s_seq[k], [s_seq[k + 1]])[0] for k in range(len(seq) - 1)]
    out = []
    for c in cands:
        try:
            sc = snap(c)
        except RoutingError:
            out.append({'id': c['id'], 'reachable': False, 'reason': 'Outside walking-route coverage'})
            continue
        d_from = net.distances(sc, s_seq)          # candidate → each walk point (the graph is walkable both ways)
        best = None
        for k in range(len(seq) - 1):
            if None in (d_from[k], d_from[k + 1], legs[k]):
                continue
            extra = d_from[k] + d_from[k + 1] - legs[k]
            if best is None or extra < best[0]:
                best = (extra, k)
        out.append({'id': c['id'], 'reachable': best is not None, 'detour_m': round(best[0], 1) if best else None,
                    'detour_min': round(best[0] / WALK_SPEED_M_PER_MIN, 1) if best else None, 'after_index': best[1] if best else None})
    return {'candidates': out, 'basis': 'network shortest-path metres; detour = d(a,c) + d(c,b) − d(a,b) at the best insertion point'}
