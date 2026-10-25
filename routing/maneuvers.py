"""Turn-by-turn maneuvers for a STREETWISE Route Object, derived only from its own ordered OSM edges and the network topology.

Chain: selected route → ordered edge IDs (directed, u→v) → route polyline → decision points → maneuvers. No external router
and no language model decides a turn.

At each node where one edge hands over to the next:
  · the turn angle is measured on the walked polyline 12 m before and after the node (not on one tiny sidewalk segment);
  · the node's other walkable options are counted from the network (a bend with no other way to go is not an instruction);
  · names come from OSM, else the matched LION street (marked as derived), else a description of the way (sidewalk, path…);
  · crossings, paths, stairs, bridges and tunnels are named as such.
Close decisions (< 12 m apart) are merged into one instruction with a "then" hint; decisions where the edges do not join are
emitted as low-confidence "check the map" notices instead of a guessed turn.
Turn classes (|angle|): < 25° straight · 25–50° slight · 50–120° turn · 120–165° sharp · ≥ 165° U-turn.
"""
import math

MX, MY = 84414.3, 111049.7
WINDOW_M, MERGE_M, NOTICE_GAP_M = 12.0, 12.0, 2.0
PATHLIKE = {'footway', 'path', 'pedestrian', 'steps', 'cycleway', 'bridleway', 'track'}
ZH_TURN = {'depart': '出发', 'continue': '继续直行', 'slight_left': '稍向左转', 'turn_left': '左转', 'sharp_left': '向左急转',
           'slight_right': '稍向右转', 'turn_right': '右转', 'sharp_right': '向右急转', 'keep_left': '靠左', 'keep_right': '靠右',
           'u_turn': '掉头', 'enter_path': '进入步道', 'cross': '过马路', 'arrive_stop': '到达站点', 'arrive': '到达目的地', 'notice': '请看地图'}
EN_TURN = {'continue': 'Continue', 'slight_left': 'Slight left', 'turn_left': 'Turn left', 'sharp_left': 'Sharp left', 'slight_right': 'Slight right',
           'turn_right': 'Turn right', 'sharp_right': 'Sharp right', 'keep_left': 'Keep left', 'keep_right': 'Keep right', 'u_turn': 'Make a U-turn'}
COMPASS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']
COMPASS_ZH = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']


def _bearing(a, b):
    dx, dy = (b[0] - a[0]) * MX, (b[1] - a[1]) * MY
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def _delta(before, after):
    return (after - before + 540) % 360 - 180   # -180..180, negative = left


def _as_list(v):
    return v if isinstance(v, list) else [v] if v else []


class Polyline:
    """The walked route as one polyline with cumulative metres, for bearings and along-route distances."""
    def __init__(self, coords):
        self.c = coords
        self.cum = [0.0]
        for a, b in zip(coords, coords[1:]):
            self.cum.append(self.cum[-1] + math.hypot((b[0] - a[0]) * MX, (b[1] - a[1]) * MY))

    @property
    def length(self):
        return self.cum[-1]

    def at(self, s):
        s = max(0.0, min(self.length, s))
        lo, hi = 0, len(self.cum) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        t = (s - self.cum[lo]) / seg if seg else 0.0
        a, b = self.c[lo], self.c[hi]
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]

    def bearing_around(self, s, before=True):
        a, b = (self.at(s - WINDOW_M), self.at(s)) if before else (self.at(s), self.at(s + WINDOW_M))
        return _bearing(a, b) if a != b else None


ABBR = {'AV': 'Ave', 'AVE': 'Ave', 'ST': 'St', 'PL': 'Pl', 'PLZ': 'Plaza', 'BLVD': 'Blvd', 'DR': 'Dr', 'RD': 'Rd', 'LN': 'Ln', 'SQ': 'Sq',
        'PKWY': 'Pkwy', 'HWY': 'Hwy', 'TER': 'Ter', 'CT': 'Ct', 'W': 'W', 'E': 'E', 'N': 'N', 'S': 'S'}


def pretty_street(name):
    """LION's 'W 42 ST' → 'W 42nd St'; names that are already mixed case are left as they are."""
    if not name or name != name.upper():
        return name
    words, out = name.split(), []
    for k, w in enumerate(words):
        if w.isdigit() and k + 1 < len(words) and words[k + 1] in ('ST', 'AV', 'AVE', 'PL', 'DR', 'RD', 'TRANSVERSE'):
            n = int(w)
            w = f'{n}{"th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'
        else:
            w = ABBR.get(w, w.capitalize())
        out.append(w)
    return ' '.join(out)


def way_label(e, lang='en'):
    """(label, confidence source) for an edge: OSM name, else derived street, else the kind of way."""
    if e.get('name'):
        return e['name'], 'osm_name'
    pa = e.get('pedestrian_access') or {}
    fw = set(_as_list(pa.get('footway')))
    hw = set(_as_list(e.get('highway')))
    if 'crossing' in fw or pa.get('crossing'):
        # the street a crosswalk crosses is not reliably known (its matched centerline is often the parallel avenue)
        return ('the crosswalk' if lang == 'en' else '人行横道'), 'way_type'
    if e.get('street_name'):
        return pretty_street(e['street_name']), 'lion_derived'
    if pa.get('steps') or 'steps' in hw:
        return ('the stairs' if lang == 'en' else '台阶'), 'way_type'
    if pa.get('bridge'):
        return ('the bridge path' if lang == 'en' else '桥上步道'), 'way_type'
    if hw & PATHLIKE:
        return ('the sidewalk' if 'sidewalk' in fw else 'the path') if lang == 'en' else ('人行道' if 'sidewalk' in fw else '步道'), 'way_type'
    return ('the street' if lang == 'en' else '街道'), 'way_type'


def _kind(e):
    pa = e.get('pedestrian_access') or {}
    fw = set(_as_list(pa.get('footway')))
    hw = set(_as_list(e.get('highway')))
    if 'crossing' in fw or pa.get('crossing'):
        return 'crossing'
    if hw & PATHLIKE and not ('sidewalk' in fw):
        return 'path'
    return 'street'


def classify(delta, alt_bearings, after):
    a = abs(delta)
    side = 'left' if delta < 0 else 'right'
    if a < 25:
        # a fork: another option also leads roughly ahead → say which branch
        close = [b for b in alt_bearings if abs(_delta(after, b)) < 45]
        if close:
            other = close[0]
            return 'keep_left' if _delta(other, after) < 0 else 'keep_right'
        return 'continue'
    if a < 50:
        return f'slight_{side}'
    if a < 120:
        return f'turn_{side}'
    if a < 165:
        return f'sharp_{side}'
    return 'u_turn'


def build(route, net, stops=None):
    """Maneuver list for a Route Object. stops: [{'name','distance_along_route_m','required','final'}] (itineraries)."""
    edges = route.get('edges') or []
    if not edges:
        return []
    coords = []
    bounds = []  # route metres where each edge starts
    pl_coords = []
    for e in edges:
        g = e['geometry']['coordinates']
        if pl_coords and g and pl_coords[-1] == g[0]:
            g = g[1:]
        pl_coords += g
    pl = Polyline(pl_coords)
    run = 0.0
    for e in edges:
        bounds.append(run)
        run += e['traversed_length_m']
    scale = pl.length / run if run else 1.0   # polyline vs network lengths differ by rounding only
    rid = route.get('route_id')
    out = []

    def add(kind, k_edge, s, before, after, text_en, text_zh, label, conf, src, extra=None):
        out.append({'maneuver_id': f'{rid}-m{len(out)}', 'route_id': rid, 'leg_id': None, 'type': kind, 'street_name': label,
                    'coordinate': pl.at(s * scale), 'distance_along_route_m': round(s, 1), 'bearing_before': None if before is None else round(before),
                    'bearing_after': None if after is None else round(after), 'instruction_text': text_en, 'instruction_zh': text_zh,
                    'confidence': conf, 'data_source': src, 'edge_index': k_edge, **(extra or {})})

    first = edges[0]
    b0 = pl.bearing_around(0, before=False)
    lab, src = way_label(first)
    labz, _ = way_label(first, 'zh')
    head = COMPASS[int(((b0 or 0) + 22.5) // 45) % 8] if b0 is not None else None
        # depart: direction from the first metres of the walk
    add('depart', 0, 0.0, None, b0, f'Head {head} on {lab}' if head else f'Start on {lab}',
        f'向{COMPASS_ZH[int(((b0 or 0) + 22.5) // 45) % 8]}出发，沿{labz}' if b0 is not None else f'沿{labz}出发', lab,
        'high' if src == 'osm_name' else 'medium', f'route edges · {src}')
    for k in range(1, len(edges)):
        e1, e2 = edges[k - 1], edges[k]
        s = bounds[k]
        node = e2['u']
        if e1['v'] != e2['u']:
            g1, g2 = e1['geometry']['coordinates'][-1], e2['geometry']['coordinates'][0]
            gap = math.hypot((g1[0] - g2[0]) * MX, (g1[1] - g2[1]) * MY)
            if gap > NOTICE_GAP_M:
                add('notice', k, s, None, None, 'Route data break here — follow the line on the map.', '此处路线数据不连续，请按地图上的路线行走。',
                    None, 'low', 'discontinuity detected')
            continue
        before, after = pl.bearing_around(s * scale, True), pl.bearing_around(s * scale, False)
        if before is None or after is None:
            continue
        delta = _delta(before, after)
        # other walkable ways leaving this node (not back where we came from, not the one we take)
        alts = []
        for i in net.adj.get(node, ()):
            u, v = net.edges[i][0], net.edges[i][1]
            if v == e1['u'] or net.edge_id(i) == e2['edge_id'] or net.nodes[v][3] != 0:
                continue
            g = net.coords(i)
            if len(g) > 1:
                alts.append(_bearing(g[0], g[min(len(g) - 1, 1)]))
        kind1, kind2 = _kind(e1), _kind(e2)
        lab1, _ = way_label(e1)
        lab2, src2 = way_label(e2)
        lab2z, _ = way_label(e2, 'zh')
        if not alts and abs(delta) < 165:
            continue   # a bend with no other way to go: no instruction needed
        t = classify(delta, alts, after)
        name_change = lab2 != lab1
        if kind2 == 'crossing' or kind1 == 'crossing':
            # going straight through a crosswalk is not a decision; turning onto one is
            if t == 'continue' or kind1 == 'crossing' and kind2 == 'crossing':
                continue
            if kind2 == 'crossing':
                text, zh, typ = f'{EN_TURN[t]} and cross the street', f'{ZH_TURN[t]}，过马路', 'cross'
            else:
                text, zh, typ = f'{EN_TURN[t]} onto {lab2}', f'{ZH_TURN[t]}进入{lab2z}', t
        elif t == 'continue':
            if not name_change or kind1 == 'crossing':
                continue
            text, zh, typ = f'Continue onto {lab2}', f'继续直行进入{lab2z}', 'continue'
        else:
            typ = t
            if kind2 == 'path' and kind1 != 'path':
                typ = 'enter_path'
                text, zh = f'{EN_TURN[t]} onto {lab2}', f'{ZH_TURN[t]}，进入{lab2z}'
            else:
                text, zh = f'{EN_TURN[t]} onto {lab2}', f'{ZH_TURN[t]}进入{lab2z}'
        near_threshold = min(abs(abs(delta) - x) for x in (25, 50, 120, 165)) < 6
        conf = 'high' if src2 == 'osm_name' and not near_threshold else 'medium' if not near_threshold else 'low'
        add(typ if typ != 'cross' else 'cross', k, s, before, after, text, zh, lab2, conf,
            f'route edges {e1["edge_id"]} → {e2["edge_id"]}; {len(alts)} other way(s) at node {node}; name: {src2}',
            {'turn_angle': round(delta), 'node_id': node})
    # merge decisions that are too close to announce separately
    merged = [out[0]]
    for m in out[1:]:
        prev = merged[-1]
        if m['type'] != 'notice' and prev['type'] not in ('depart', 'notice') and m['distance_along_route_m'] - prev['distance_along_route_m'] < MERGE_M:
            prev['then'] = m['instruction_text']
            prev['then_zh'] = m['instruction_zh']
            prev['instruction_text'] += f', then {m["instruction_text"][0].lower() + m["instruction_text"][1:]}'
            prev['instruction_zh'] += f'，随后{m["instruction_zh"]}'
            continue
        merged.append(m)
    # arrivals: stops along the way and the destination
    for st in stops or [{'name': None, 'distance_along_route_m': run, 'final': True}]:
        s = min(run, st['distance_along_route_m'])
        final = st.get('final')
        nm = st.get('name')
        merged.append({'maneuver_id': f'{rid}-a{len(merged)}', 'route_id': rid, 'leg_id': st.get('leg_id'), 'type': 'arrive' if final else 'arrive_stop',
                       'street_name': None, 'coordinate': pl.at(s * scale), 'distance_along_route_m': round(s, 1), 'bearing_before': None, 'bearing_after': None,
                       'instruction_text': (f'Arrive at {nm}' if nm else 'Arrive at your destination') if final else f'Arrive at stop: {nm}',
                       'instruction_zh': (f'到达{nm}' if nm else '到达目的地') if final else f'到达站点：{nm}',
                       'confidence': 'high', 'data_source': 'route end' if final else 'itinerary stop', 'stop_name': nm,
                       'stop_id': st.get('id'), 'required': st.get('required', True), 'visit_min': st.get('visit_min')})
    merged.sort(key=lambda m: (m['distance_along_route_m'], m['type'].startswith('arrive')))
    for n, m in enumerate(merged):
        m['maneuver_id'] = f'{rid}-m{n}'
    return merged
