"""STREETWISE pedestrian routing engine (standard library only).

Routes are computed on the OSM pedestrian graph (data/pedestrian/manhattan-walk-graph.json.gz) and scored with
the 12 experience scores transferred to each OSM edge (data/pedestrian/edge-scores.json.gz). NYC LION is never
routed on; it only supplies scores through street_osm_edge_mapping. Every route keeps its ordered edge list, and
its geometry, distance and scores are all derived from that one list.
"""
import gzip, heapq, json, math, os, threading, time, uuid
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPH = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
SCORES = os.path.join(ROOT, 'data', 'pedestrian', 'edge-scores.json.gz')
DIMENSIONS = ['Architecture', 'Nature', 'Culture', 'Quiet & Relax', 'Spatial Comfort', 'Urban Vibrancy', 'Food & Retail',
              'Scenic & Visual', 'Walkability', 'Access & Safety', 'Environment', 'Transit Connectivity']
MIN_WALK_MINUTES = 10  # smallest accepted max walking time; there is deliberately no upper cap
WALK_SPEED_M_PER_MIN = 80.0  # 4.8 km/h, a common planning pace; no live pace data is used
MAX_SNAP_M = 150.0
LOW_COVERAGE = 0.6
OFF_ROUTE_M = 35.0
LAT0 = 40.78
MX, MY = 111320 * math.cos(math.radians(LAT0)), 110540


class RoutingError(ValueError):
    """A request the network cannot satisfy (bad input, too far from a path, unreachable)."""


def xy(lon, lat):
    return (lon * MX, lat * MY)


def as_list(v):
    return v if isinstance(v, list) else [] if v is None else [v]


class PedestrianNetwork:
    def __init__(self, graph_path=GRAPH, scores_path=SCORES):
        t0 = time.time()
        graph = json.load(gzip.open(graph_path, 'rt', encoding='utf-8'))
        scores = json.load(gzip.open(scores_path, 'rt', encoding='utf-8'))
        self.meta, self.score_meta = graph['metadata'], scores['metadata']
        if self.score_meta['network_version'] != self.meta['network_version']:
            raise RuntimeError('edge-scores.json.gz was built for a different network version; rerun scripts/match_lion_osm.py')
        self.network_version = self.meta['network_version']
        self.score_version = self.score_meta['score_version']
        self.nodes = {int(k): v for k, v in graph['nodes'].items()}
        self.geoms, self.edges, self.gscores = graph['geoms'], graph['edges'], scores['geoms']
        self.adj, self.by_id, self.by_geom = {}, {}, {}
        for i, (u, v, k, gi, rev, length, osmids, tags) in enumerate(self.edges):
            self.adj.setdefault(u, []).append(i)
            self.by_id[f'{u}-{v}-{k}'] = i
            self.by_geom[(gi, rev)] = i
            tags['_steps'] = 'steps' in as_list(tags.get('highway'))
        # Metric polylines and a 100 m bucket index of routable edge geometries (both endpoints in the main component).
        self.gxy = [[xy(*p) for p in g] for g in self.geoms]
        self.glen = [sum(math.dist(a, b) for a, b in zip(g, g[1:])) for g in self.gxy]
        self.index = {}
        for i, (u, v, k, gi, rev, *_rest) in enumerate(self.edges):
            if rev or self.nodes[u][3] != 0 or self.nodes[v][3] != 0:
                continue
            for a, b in zip(self.gxy[gi], self.gxy[gi][1:]):
                for bx in range(int(min(a[0], b[0]) // 100), int(max(a[0], b[0]) // 100) + 1):
                    for by in range(int(min(a[1], b[1]) // 100), int(max(a[1], b[1]) // 100) + 1):
                        cell = self.index.setdefault((bx, by), [])
                        if not cell or cell[-1] != i:
                            cell.append(i)
        self._step_free = None
        streets = os.path.join(ROOT, 'data', 'manhattan-streets.json')
        self.segment_names = {f['properties']['id']: (f['properties']['name'], f['properties'].get('source_segment_id'))
                              for f in json.load(open(streets, encoding='utf-8'))['features']} if os.path.exists(streets) else {}
        self.load_seconds = round(time.time() - t0, 1)

    def step_free_nodes(self):
        """Nodes of the largest network reachable without any steps (computed once). Snapping for 'avoid stairs'
        targets this network, so a start inside a pocket enclosed by stairs is not chosen."""
        if self._step_free is None:
            adj = {}
            for u, v, k, gi, rev, length, osmids, tags in self.edges:
                if not tags['_steps'] and self.nodes[u][3] == 0 and self.nodes[v][3] == 0:
                    adj.setdefault(u, []).append(v)
            seen, best = set(), set()
            for start in adj:
                if start in seen:
                    continue
                comp, stack = {start}, [start]
                while stack:
                    for nb in adj.get(stack.pop(), ()):
                        if nb not in comp:
                            comp.add(nb); stack.append(nb)
                seen |= comp
                if len(comp) > len(best):
                    best = comp
            self._step_free = best
        return self._step_free

    # --- identities and lookups ------------------------------------------------------------------------------
    def edge_id(self, i):
        u, v, k = self.edges[i][:3]
        return f'{u}-{v}-{k}'

    def twin(self, i):
        gi, rev = self.edges[i][3], self.edges[i][4]
        return self.by_geom.get((gi, 1 - rev))

    def coords(self, i):
        gi, rev = self.edges[i][3], self.edges[i][4]
        g = self.geoms[gi]
        return g[::-1] if rev else g

    def coords_xy(self, i):
        gi, rev = self.edges[i][3], self.edges[i][4]
        g = self.gxy[gi]
        return g[::-1] if rev else g

    def status(self):
        c = self.meta['counts']
        return {'network_version': self.network_version, 'score_version': self.score_version, 'data_version': self.score_meta['data_version'],
                'nodes': c['nodes'], 'edges': c['edges'], 'main_component_nodes': c['main_component_nodes'], 'components': c['components'],
                'edge_score_sources': self.score_meta['sources'], 'dimension_length_coverage': self.score_meta['routable_length_coverage_by_dimension'],
                'load_seconds': self.load_seconds}

    def edge_object(self, i, traversed=None, offsets=None):
        """Pedestrian Edge Object (shared data contract)."""
        u, v, k, gi, rev, length, osmids, tags = self.edges[i]
        s = self.gscores[gi]
        geom = self.coords(i) if offsets is None else self.clip(i, *offsets)
        return {
            'edge_id': f'{u}-{v}-{k}', 'u': u, 'v': v, 'key': k, 'osm_way_ids': osmids, 'geometry_index': gi,
            'name': (as_list(tags.get('name')) or [None])[0], 'highway': tags.get('highway'),
            'geometry': {'type': 'LineString', 'coordinates': geom},
            'length_m': round(length, 1), 'traversed_length_m': round(traversed if traversed is not None else length, 1),
            'pedestrian_access': {'foot': tags.get('foot'), 'access': tags.get('access'), 'steps': tags['_steps'],
                                  'footway': tags.get('footway'), 'crossing': tags.get('crossing'), 'bridge': tags.get('bridge'),
                                  'tunnel': tags.get('tunnel'), 'layer': tags.get('layer'), 'surface': tags.get('surface')},
            'dimension_scores': dict(zip(DIMENSIONS, s['s'])), 'overall_score': s['o'],
            'data_coverage': dict(zip(DIMENSIONS, s['c'])), 'score_source': s['src'], 'match_quality': s['q'],
            'matched_segment_ids': s['m'], 'lion_match_share': s['frac'],
            'matched_segments': [{'segment_id': m, 'street_name': self.segment_names.get(m, (None, None))[0], 'source_segment_id': self.segment_names.get(m, (None, None))[1]} for m in s['m']],
            'lion_match': 'matched' if s['m'] else 'unmatched',
            'street_name': (as_list(tags.get('name')) or [None])[0] or (self.segment_names.get(s['m'][0], (None,))[0] if s['m'] else None),
            'direct_sub_indicators': s.get('raw'), 'network_version': self.network_version, 'score_version': self.score_version,
        }

    # --- snapping --------------------------------------------------------------------------------------------
    def snap(self, lon, lat, label, allowed=None):
        """Project a coordinate onto the nearest routable edge (never straight onto a node); allowed(i) can exclude edges."""
        p = xy(lon, lat)
        bx, by = int(p[0] // 100), int(p[1] // 100)
        best = None
        for r in range(0, int(MAX_SNAP_M // 100) + 2):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    for i in self.index.get((bx + dx, by + dy), ()):
                        if allowed and not allowed(i):
                            continue
                        g = self.coords_xy(i); run = 0.0
                        for a, b in zip(g, g[1:]):
                            ux, uy = b[0] - a[0], b[1] - a[1]; l2 = ux * ux + uy * uy; seg = math.sqrt(l2)
                            t = max(0.0, min(1.0, ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / l2)) if l2 else 0.0
                            d = math.hypot(p[0] - a[0] - t * ux, p[1] - a[1] - t * uy)
                            if best is None or d < best[0]:
                                best = (d, i, run + t * seg)
                            run += seg
            if best and best[0] <= r * 100:
                break
        if not best or best[0] > MAX_SNAP_M:
            raise RoutingError(f'{label} is more than {MAX_SNAP_M:.0f} m from any walkable path in the Manhattan pedestrian network'
                               + (' that avoids stairs.' if allowed else '. Roosevelt, Randall\'s and Governors Island connect only through other boroughs and are not routable.'))
        d, i, along = best
        geo_len = self.glen[self.edges[i][3]] or 1
        return {'edge': i, 'offset_m': along / geo_len * self.edges[i][5], 'snap_distance_m': round(d, 1),
                'edge_id': self.edge_id(i), 'input': [lon, lat]}

    # --- geometry helpers ------------------------------------------------------------------------------------
    def clip(self, i, a_m, b_m):
        """Edge coordinates between two offsets (metres of the edge's own length, in its direction)."""
        length = self.edges[i][5] or 1
        g, gx = self.coords(i), self.coords_xy(i)
        cum = [0.0]
        for p, q in zip(gx, gx[1:]):
            cum.append(cum[-1] + math.dist(p, q))
        scale = (cum[-1] or 1) / length
        a, b = a_m * scale, b_m * scale

        def at(d):
            for j in range(1, len(cum)):
                if d <= cum[j] or j == len(cum) - 1:
                    t = 0 if cum[j] == cum[j - 1] else max(0.0, min(1.0, (d - cum[j - 1]) / (cum[j] - cum[j - 1])))
                    return [round(g[j - 1][0] + (g[j][0] - g[j - 1][0]) * t, 7), round(g[j - 1][1] + (g[j][1] - g[j - 1][1]) * t, 7)], j
            return g[-1], len(g) - 1
        start, js = at(a)
        end, je = at(b)
        return [start] + [list(c) for c in g[js:je]] + [end]

    # --- search ----------------------------------------------------------------------------------------------
    def search(self, origin, dest, edge_cost):
        """A* over the graph with virtual origin/destination nodes on their snapped edges.
        edge_cost(i) returns cost per metre multiplier (>= 1, so straight-line distance stays admissible) or None."""
        O, D = 'O', 'D'
        tx, ty = xy(*self.clip(dest['edge'], dest['offset_m'], dest['offset_m'])[0])

        def h(node):
            lon, lat = self.nodes[node][:2]
            x, y = xy(lon, lat)
            return math.hypot(x - tx, y - ty)

        def leaving(snapped):
            """(node, step) choices from a snapped point: forward along its edge, or backward along the twin."""
            i, off = snapped['edge'], snapped['offset_m']
            out = [(self.edges[i][1], (i, off, self.edges[i][5]))]
            j = self.twin(i)
            if j is not None:
                out.append((self.edges[j][1], (j, self.edges[j][5] - off, self.edges[j][5])))
            return out

        def arriving(snapped):
            """node -> step that ends at the snapped destination point."""
            i, off = snapped['edge'], snapped['offset_m']
            out = {self.edges[i][0]: (i, 0.0, off)}
            j = self.twin(i)
            if j is not None:
                out[self.edges[j][0]] = (j, 0.0, self.edges[j][5] - off)
            return out

        cost_cache = {}

        def cost(i):
            if i not in cost_cache:
                cost_cache[i] = edge_cost(i)
            return cost_cache[i]

        def step_cost(step):
            i, a, b = step
            c = cost(i)
            return None if c is None else c * (b - a)

        ends = arriving(dest)
        best = {O: 0.0}
        pred = {}
        heap = []
        # Same-edge trip: walk directly between the two snapped points.
        if origin['edge'] in (dest['edge'], self.twin(dest['edge'])):
            i = dest['edge']
            a, b = (origin['offset_m'] if origin['edge'] == i else self.edges[i][5] - origin['offset_m']), dest['offset_m']
            step = (i, a, b) if a <= b else (self.twin(i), self.edges[i][5] - a, self.edges[i][5] - b) if self.twin(i) is not None else None
            if step and step_cost(step) is not None:
                best[D] = step_cost(step); pred[D] = (O, step)
                heapq.heappush(heap, (best[D], best[D], D))
        for node, step in leaving(origin):
            c = step_cost(step)
            if c is not None and c < best.get(node, math.inf):
                best[node] = c; pred[node] = (O, step)
                heapq.heappush(heap, (c + h(node), c, node))
        done = set()
        while heap:
            f, g, node = heapq.heappop(heap)
            if node in done or g > best.get(node, math.inf):
                continue
            if node == D:
                break
            done.add(node)
            if node in ends:
                c = step_cost(ends[node])
                if c is not None and g + c < best.get(D, math.inf):
                    best[D] = g + c; pred[D] = (node, ends[node])
                    heapq.heappush(heap, (best[D], best[D], D))
            for i in self.adj.get(node, ()):
                v = self.edges[i][1]
                if v in done or self.nodes[v][3] != 0:
                    continue
                c = cost(i)
                if c is None:
                    continue
                ng = g + c * self.edges[i][5]
                if ng < best.get(v, math.inf):
                    best[v] = ng; pred[v] = (node, (i, 0.0, self.edges[i][5]))
                    heapq.heappush(heap, (ng + h(v), ng, v))
        if D not in pred:
            return None
        steps, node = [], D
        while node != O:
            node, step = pred[node]
            steps.append(step)
        return steps[::-1]


def preference_weights(preferences):
    """Expressed preferences only (weight > 0); if none are expressed every dimension counts equally.
    Weights describe the user, never the street: they are kept separate from the objective scores."""
    prefs = preferences or {}
    weights, dirs = prefs.get('weights') or {}, prefs.get('directions') or {}
    expressed = {d: float(w) for d, w in weights.items() if d in DIMENSIONS and w and float(w) > 0}
    if expressed:
        return {d: (w, dirs.get(d, 'high')) for d, w in expressed.items()}, True
    return {d: (50.0, 'high') for d in DIMENSIONS}, False


class RoutePlanner:
    def __init__(self, network):
        self.net = network
        self.routes = OrderedDict()  # route_id -> navigation-ready route, for progress/off-route queries
        self.lock = threading.Lock()

    def edge_utility(self, gi, weights):
        """0..1 preference fit of one edge; missing dimensions count as neutral 0.5 (never as good or bad)."""
        s = self.net.gscores[gi]
        num = den = 0.0
        for j, d in enumerate(DIMENSIONS):
            if d not in weights:
                continue
            w, direction = weights[d]
            den += w
            v, c = s['s'][j], s['c'][j]
            if v is None:
                continue
            fit = (v if direction == 'high' else 100 - v) / 100
            num += w * c * (fit - .5)
        return .5 + (num / den if den else 0.0)

    def plan(self, origin, destination, preferences=None, constraints=None):
        t0 = time.time()
        net = self.net
        constraints = constraints or {}
        avoid_stairs = bool(constraints.get('avoid_stairs'))
        sf = net.step_free_nodes() if avoid_stairs else None
        no_steps = (lambda i: not net.edges[i][7]['_steps'] and net.edges[i][0] in sf and net.edges[i][1] in sf) if avoid_stairs else None
        o = net.snap(origin['lon'], origin['lat'], 'Origin', no_steps)
        d = net.snap(destination['lon'], destination['lat'], 'Destination', no_steps)
        weights, expressed = preference_weights(preferences)

        def allowed(i):
            return not (avoid_stairs and net.edges[i][7]['_steps'])

        def length_cost(i):
            return 1.0 if allowed(i) else None

        def experience_cost(lam, penalties=None):
            def f(i):
                if not allowed(i):
                    return None
                gi = net.edges[i][3]
                c = 1.0 + lam * (1.0 - net_utility(gi))
                return c * (penalties.get(gi, 1.0) if penalties else 1.0)
            return f

        util_cache = {}

        def net_utility(gi):
            if gi not in util_cache:
                util_cache[gi] = self.edge_utility(gi, weights)
            return util_cache[gi]

        specs = [('shortest', 'Shortest Walk', length_cost)]
        specs += [('experience', 'Best Experience Match', experience_cost(2.0)), ('experience_balanced', 'Balanced Experience Route', experience_cost(0.8))]
        candidates = []
        for objective, name, fn in specs:
            steps = net.search(o, d, fn)
            if steps is None:
                if objective == 'shortest':
                    raise RoutingError('No walkable connection exists between these points' + (' without stairs.' if avoid_stairs else '.'))
                continue
            candidates.append((objective, name, steps))
        # Diversity: penalise edges already used and search again, so alternatives are genuinely different paths.
        used = {}
        for _, _, steps in candidates:
            for i, *_ in steps:
                used[net.edges[i][3]] = 1.8
        for _ in range(2):
            steps = net.search(o, d, experience_cost(1.2, used))
            if steps is None:
                break
            candidates.append(('alternative', 'Alternative Experience Route', steps))
            for i, *_ in steps:
                used[net.edges[i][3]] = used.get(net.edges[i][3], 1.0) * 1.8

        routes = []
        for objective, name, steps in candidates:
            r = self.build_route(objective, name, steps, o, d, origin, destination)
            if any(overlap(r, x) > .85 for x in routes):
                continue  # same path found by another objective: keep one copy, never relabel duplicates
            routes.append(r)
        alts = [r for r in routes if r['objective'] == 'alternative']
        for n, r in enumerate(alts[1:], 2):
            r['route_name'] = f'Alternative Experience Route {n}'
        shortest = min(r['distance_m'] for r in routes)
        max_minutes = constraints.get('max_minutes')
        max_detour = constraints.get('max_detour_pct') if constraints.get('avoid_detours', True) else None
        for r in routes:
            r['detour_percentage'] = round((r['distance_m'] / shortest - 1) * 100, 1) if shortest else 0.0
            violations = []
            if max_minutes is not None and r['estimated_duration_min'] > max_minutes + 1e-6:
                violations.append(f"{r['estimated_duration_min']:.0f} min exceeds the {max_minutes:g}-minute limit")
            if max_detour is not None and r['detour_percentage'] > max_detour + 1e-6:
                violations.append(f"{r['detour_percentage']:.0f}% detour exceeds the {max_detour:g}% limit")
            r['constraints'] = {'feasible': not violations, 'violations': violations, 'avoid_stairs': avoid_stairs,
                                'contains_steps': any(e['pedestrian_access']['steps'] for e in r['edges'])}
            self.personalize(r, weights, expressed)
        ranked = sorted(routes, key=lambda r: (not r['constraints']['feasible'], -r['personalized_score']['utility'], r['distance_m']))
        for n, r in enumerate(ranked, 1):
            r['rank'] = n
            r['recommended'] = n == 1 and r['constraints']['feasible']
            r['ranking_explanation'] = explain(r, ranked, weights, expressed)
        with self.lock:
            for r in ranked:
                self.routes[r['route_id']] = r
            while len(self.routes) > 200:
                self.routes.popitem(last=False)
        return {
            'network_version': net.network_version, 'score_version': net.score_version,
            'origin': o, 'destination': d, 'shortest_distance_m': shortest,
            'preferences_used': {k: {'weight': w, 'direction': dr} for k, (w, dr) in weights.items()}, 'preferences_expressed': expressed,
            'constraints_used': {'max_minutes': max_minutes, 'max_detour_pct': max_detour, 'avoid_detours': constraints.get('avoid_detours', True), 'avoid_stairs': avoid_stairs},
            'feasible_count': sum(r['constraints']['feasible'] for r in ranked),
            'routes': ranked, 'compute_seconds': round(time.time() - t0, 2),
            'notes': ['Walking time uses a fixed 4.8 km/h planning pace; no live pedestrian or traffic data.',
                      'Scores are relative ranks within Manhattan (0–100), not calibrated experience scores. N/A dimensions are excluded, never counted as zero.'],
        }

    def build_route(self, objective, name, steps, o, d, origin, destination):
        """Route Object: geometry, distance and scores all come from the same ordered edge list."""
        net = self.net
        coords, edges, total = [], [], 0.0
        num, scored = [0.0] * 12, [0.0] * 12
        for i, a, b in steps:
            seg = net.clip(i, a, b)
            if coords and seg and coords[-1] == seg[0]:
                seg = seg[1:]
            coords += seg
            length = b - a
            total += length
            e = net.edge_object(i, traversed=length, offsets=(a, b))
            e['partial'] = a > 0.01 or b < net.edges[i][5] - 0.01
            edges.append(e)
            s = net.gscores[net.edges[i][3]]
            for j in range(12):
                if s['s'][j] is not None:
                    w = length * s['c'][j]
                    num[j] += w * s['s'][j]; scored[j] += w
        dims = {DIMENSIONS[j]: (round(num[j] / scored[j]) if scored[j] else None) for j in range(12)}
        cov = {DIMENSIONS[j]: round(scored[j] / total, 3) if total else 0.0 for j in range(12)}
        have = [v for v in dims.values() if v is not None]
        rid = 'rt-' + uuid.uuid4().hex[:10]
        duration = total / WALK_SPEED_M_PER_MIN
        return {
            'route_id': rid, 'route_name': name, 'objective': objective,
            'origin': {'input': origin, 'snapped_edge_id': o['edge_id'], 'snap_distance_m': o['snap_distance_m']},
            'destination': {'input': destination, 'snapped_edge_id': d['edge_id'], 'snap_distance_m': d['snap_distance_m']},
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'ordered_edge_ids': [e['edge_id'] for e in edges], 'edges': edges,
            'distance_m': round(total, 1), 'estimated_duration_min': round(duration, 1),
            'dimension_scores': dims, 'overall_score': round(sum(have) / len(have)) if have else None,
            'data_coverage': {'by_dimension': cov, 'mean': round(sum(cov.values()) / 12, 3),
                              'low_coverage_dimensions': [k for k, v in cov.items() if v < LOW_COVERAGE]},
            'network_version': net.network_version, 'score_version': net.score_version,
            'navigation': {'state': 'planned', 'progress_m': 0.0, 'remaining_m': round(total, 1),
                           'remaining_min': round(duration, 1), 'off_route': False, 'current_edge_id': edges[0]['edge_id'] if edges else None,
                           'progress_endpoint': '/api/navigation/progress'},
        }

    def personalize(self, r, weights, expressed):
        """PersonalizedUtility = WeightedExperience − TravelCostPenalty. A dimension's route score is pulled toward the
        neutral 50 in proportion to its missing coverage, so sparse data can't produce a false high score."""
        parts, num, den = {}, 0.0, 0.0
        for dim, (w, direction) in weights.items():
            v, c = r['dimension_scores'][dim], r['data_coverage']['by_dimension'][dim]
            fit = None if v is None else (v if direction == 'high' else 100 - v)
            adjusted = 50 + c * (fit - 50) if fit is not None else 50
            parts[dim] = {'weight': w, 'direction': direction, 'route_score': v, 'coverage': c, 'adjusted_fit': round(adjusted, 1)}
            num += w * adjusted; den += w
        experience = num / den if den else 50.0
        penalty = 0.4 * max(0.0, r['detour_percentage'])  # 0.4 points per % longer than the shortest path
        r['personalized_score'] = {'utility': round(experience - penalty, 1), 'weighted_experience': round(experience, 1),
                                   'travel_cost_penalty': round(penalty, 1), 'components': parts, 'preferences_expressed': expressed,
                                   'formula': 'Σ w·(50 + coverage·(fit − 50)) / Σ w − 0.4 × detour %'}

    # --- navigation readiness ------------------------------------------------------------------------------
    def progress(self, route_id, lon, lat, accuracy_m=None):
        """Where a reported position sits on a planned route. Pure geometry: no live tracking is claimed."""
        with self.lock:
            r = self.routes.get(route_id)
        if not r:
            raise RoutingError('Unknown or expired route_id; plan the route again.')
        p = xy(lon, lat)
        g = [xy(*c) for c in r['geometry']['coordinates']]
        best, run = None, 0.0
        for a, b in zip(g, g[1:]):
            ux, uy = b[0] - a[0], b[1] - a[1]; l2 = ux * ux + uy * uy; seg = math.sqrt(l2)
            t = max(0.0, min(1.0, ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / l2)) if l2 else 0.0
            dist = math.hypot(p[0] - a[0] - t * ux, p[1] - a[1] - t * uy)
            if best is None or dist < best[0]:
                best = (dist, run + t * seg)
            run += seg
        dist, along = best
        geo_total = run or 1
        progress = along / geo_total * r['distance_m']
        acc_ok = accuracy_m is None or accuracy_m <= 60
        off = dist > OFF_ROUTE_M and acc_ok
        cum, current = 0.0, None
        for e in r['edges']:
            cum += e['traversed_length_m']
            if cum >= progress:
                current = e['edge_id']; break
        remaining = max(0.0, r['distance_m'] - progress)
        state = 'off_route' if off else 'arrived' if remaining < 20 else 'on_route'
        return {'route_id': route_id, 'state': state, 'distance_from_route_m': round(dist, 1), 'progress_m': round(progress, 1),
                'remaining_m': round(remaining, 1), 'remaining_min': round(remaining / WALK_SPEED_M_PER_MIN, 1),
                'current_edge_id': current, 'off_route': off, 'reroute_recommended': off,
                'accuracy_considered': acc_ok, 'reroute_hint': 'POST /api/routes with origin = current position' if off else None}


def overlap(a, b):
    """Share of route a's length on street geometries that route b also uses (either direction)."""
    used = {e['geometry_index'] for e in b['edges']}
    return sum(e['traversed_length_m'] for e in a['edges'] if e['geometry_index'] in used) / (a['distance_m'] or 1)


def explain(r, ranked, weights, expressed):
    ps = r['personalized_score']
    top = sorted(ps['components'].items(), key=lambda kv: -kv[1]['weight'])[:4]
    shortest = min(ranked, key=lambda x: x['distance_m'])
    bits = []
    for dim, c in top:
        if c['route_score'] is None:
            bits.append(f'{dim} N/A')
            continue
        delta = '' if r is shortest or shortest['dimension_scores'][dim] is None else f" ({c['route_score'] - shortest['dimension_scores'][dim]:+d} vs shortest)"
        bits.append(f"{dim} {c['route_score']}{' (prefer less)' if c['direction'] == 'low' else ''}{delta}")
    basis = 'your expressed preferences' if expressed else 'all 12 dimensions equally (no preference expressed)'
    status = 'Recommended' if r.get('recommended') else 'Not feasible: ' + '; '.join(r['constraints']['violations']) if not r['constraints']['feasible'] else f"Ranked {r['rank']} of {len(ranked)}"
    low = r['data_coverage']['low_coverage_dimensions']
    return (f"{status}. Personalized score {ps['utility']} = weighted experience {ps['weighted_experience']} − {ps['travel_cost_penalty']} detour penalty "
            f"(+{r['detour_percentage']}% vs shortest), weighted by {basis}. Route scores: {', '.join(bits)}."
            + (f" Low data coverage: {', '.join(low)}." if low else ''))


_planner, _error, _lock = None, None, threading.Lock()


def reset_planner():
    """Drop the loaded network so the next request reads freshly rebuilt files."""
    global _planner, _error
    with _lock:
        _planner, _error = None, None


def get_planner():
    """Load the network once per process; later requests reuse it."""
    global _planner, _error
    with _lock:
        if _planner is None and _error is None:
            try:
                _planner = RoutePlanner(PedestrianNetwork())
            except FileNotFoundError as e:
                _error = f'Pedestrian network not built: {os.path.basename(e.filename or "")} missing. Run scripts/build_pedestrian_network.py then scripts/match_lion_osm.py.'
            except Exception as e:  # corrupted or mismatched build
                _error = f'Pedestrian network unavailable: {e}'
    if _error:
        raise RuntimeError(_error)
    return _planner
