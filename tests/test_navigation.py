"""Navigation backbone: maneuver generation (routing/maneuvers.py) on synthetic networks and real routes, route signatures,
and restart-safe progress from a client snapshot (routing/engine.py). Each test is an explicit Pass / Fail.
Run: python3 -m unittest tests.test_navigation
"""
import copy, math, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from routing import maneuvers as mv  # noqa: E402
from routing.engine import get_planner, route_signature, RoutingError  # noqa: E402

P = get_planner()
NET = P.net
M = (84414.3, 111049.7)
O = (-73.98, 40.75)


def at(dx, dy):
    return [O[0] + dx / M[0], O[1] + dy / M[1]]


class FakeNet:
    """A tiny directed walking network: nodes at metric offsets, ways between them (both directions)."""
    def __init__(self, nodes, ways):
        self.nodes = {k: [*at(*xy), 0, 0] for k, xy in nodes.items()}
        self.nodes = {k: [v[0], v[1], 0, 0] for k, v in self.nodes.items()}
        for k in self.nodes:
            self.nodes[k][3] = 0
        self.edges, self.adj, self.tags = [], {}, {}
        for u, v, tags in ways:
            for a, b in ((u, v), (v, u)):
                i = len(self.edges)
                self.edges.append((a, b, 0, i, False, 0, [], tags))
                self.adj.setdefault(a, []).append(i)

    def edge_id(self, i):
        return f'{self.edges[i][0]}-{self.edges[i][1]}-0'

    def coords(self, i):
        a, b = self.edges[i][0], self.edges[i][1]
        return [self.nodes[a][:2], self.nodes[b][:2]]


def route_through(net, path, tags_by_pair=None):
    edges = []
    for a, b in zip(path, path[1:]):
        i = next(i for i in net.adj[a] if net.edges[i][1] == b)
        t = net.edges[i][7]
        g = net.coords(i)
        L = math.hypot((g[1][0] - g[0][0]) * M[0], (g[1][1] - g[0][1]) * M[1])
        edges.append({'edge_id': net.edge_id(i), 'u': a, 'v': b, 'name': t.get('name'), 'street_name': t.get('street_name'), 'highway': t.get('highway', 'footway'),
                      'pedestrian_access': {'footway': t.get('footway'), 'crossing': t.get('crossing'), 'steps': t.get('steps', False), 'bridge': None},
                      'geometry': {'type': 'LineString', 'coordinates': g}, 'traversed_length_m': L})
    return {'route_id': 'rt-test', 'edges': edges}


def types(ms):
    return [m['type'] for m in ms]


# A plus-shaped junction at C with arms 100 m long, plus extra nodes for bends / forks.
GRID = {'S': (0, -100), 'C': (0, 0), 'N': (0, 100), 'E': (100, 0), 'W': (-100, 0), 'NE': (80, 60), 'NW': (-30, 100), 'SE': (90, -40)}
ST = {'name': 'Main St', 'highway': 'residential'}


class A_SyntheticManeuvers(unittest.TestCase):
    def plus(self, extra=()):
        return FakeNet(GRID, [('S', 'C', ST), ('C', 'N', ST), ('C', 'E', {'name': 'East St', 'highway': 'residential'}), ('C', 'W', {'name': 'West St', 'highway': 'residential'}), *extra])

    def test_straight_through_junction_is_silent(self):
        net = self.plus()
        ms = mv.build(route_through(net, ['S', 'C', 'N']), net)
        self.assertEqual(types(ms), ['depart', 'arrive'])
        self.assertIn('north', ms[0]['instruction_text'])

    def test_left_and_right(self):
        net = self.plus()
        r = mv.build(route_through(net, ['S', 'C', 'E']), net)
        l = mv.build(route_through(net, ['S', 'C', 'W']), net)
        self.assertEqual(r[1]['type'], 'turn_right'); self.assertEqual(r[1]['street_name'], 'East St')
        self.assertEqual(l[1]['type'], 'turn_left'); self.assertEqual(l[1]['instruction_text'], 'Turn left onto West St')
        self.assertEqual(r[1]['node_id'], 'C'); self.assertAlmostEqual(r[1]['distance_along_route_m'], 100, delta=1)
        self.assertEqual(r[1]['instruction_zh'], '右转进入East St')

    def test_sharp_turn(self):
        net = FakeNet({**GRID, 'X': (40, -60)}, [('S', 'C', ST), ('C', 'X', {'name': 'Back Rd', 'highway': 'residential'}), ('C', 'N', ST)])
        ms = mv.build(route_through(net, ['S', 'C', 'X']), net)
        self.assertEqual(ms[1]['type'], 'sharp_right')

    def test_bend_without_choice_is_silent(self):
        net = FakeNet({'A': (0, -100), 'B': (0, 0), 'C': (70, 70)}, [('A', 'B', ST), ('B', 'C', ST)])
        self.assertEqual(types(mv.build(route_through(net, ['A', 'B', 'C']), net)), ['depart', 'arrive'])

    def test_fork_says_keep(self):
        net = FakeNet({'A': (0, -100), 'B': (0, 0), 'L': (-25, 100), 'R': (25, 100)}, [('A', 'B', ST), ('B', 'L', {'name': 'Left Way', 'highway': 'residential'}), ('B', 'R', {'name': 'Right Way', 'highway': 'residential'})])
        ms = mv.build(route_through(net, ['A', 'B', 'R']), net)
        self.assertEqual(ms[1]['type'], 'keep_right')

    def test_straight_crosswalk_silent_turning_crosswalk_announced(self):
        cw = {'footway': 'crossing', 'highway': 'footway'}
        net = FakeNet({'A': (0, -100), 'B': (0, 0), 'C': (0, 15), 'D': (0, 100), 'E': (20, 0)},
                      [('A', 'B', ST), ('B', 'C', cw), ('C', 'D', ST), ('B', 'E', {'name': 'Side St'})])
        self.assertNotIn('cross', types(mv.build(route_through(net, ['A', 'B', 'C', 'D']), net)))
        net2 = FakeNet({'A': (0, -100), 'B': (0, 0), 'C': (15, 0), 'D': (100, 0), 'N': (0, 100)},
                       [('A', 'B', ST), ('B', 'C', cw), ('C', 'D', {'name': 'Far St'}), ('B', 'N', ST)])
        ms = mv.build(route_through(net2, ['A', 'B', 'C', 'D']), net2)
        self.assertIn('cross', types(ms)); self.assertIn('cross the street', next(m for m in ms if m['type'] == 'cross')['instruction_text'])

    def test_park_path_and_unnamed_way(self):
        net = self.plus([('C', 'NE', {'highway': 'path'})])
        ms = mv.build(route_through(net, ['S', 'C', 'NE']), net)
        self.assertEqual(ms[1]['type'], 'enter_path'); self.assertIn('the path', ms[1]['instruction_text'])
        self.assertNotEqual(ms[1]['confidence'], 'high', 'unnamed ways (and angles near a class boundary) are never high confidence')

    def test_derived_street_name(self):
        net = self.plus([('C', 'SE', {'street_name': 'W 42 ST', 'highway': 'footway', 'footway': 'sidewalk'})])
        ms = mv.build(route_through(net, ['S', 'C', 'SE']), net)
        self.assertEqual(ms[1]['street_name'], 'W 42nd St'); self.assertIn('lion_derived', ms[1]['data_source'])

    def test_reversed_direction(self):
        net = self.plus()
        ms = mv.build(route_through(net, ['N', 'C', 'E']), net)   # walking south, then east = turn left
        self.assertEqual(ms[1]['type'], 'turn_left')

    def test_close_consecutive_turns_are_merged(self):
        net = FakeNet({'A': (0, -100), 'B': (0, 0), 'C': (8, 0), 'D': (8, 100), 'X': (-100, 0), 'Y': (100, 0), 'Z': (8, -50)},
                      [('A', 'B', ST), ('B', 'C', {'name': 'Short'}), ('C', 'D', {'name': 'Up St'}), ('B', 'X', ST), ('C', 'Y', ST), ('C', 'Z', ST)])
        ms = mv.build(route_through(net, ['A', 'B', 'C', 'D']), net)
        turn = ms[1]
        self.assertIn('then', turn['instruction_text']); self.assertEqual(len([m for m in ms if m['type'] not in ('depart', 'arrive')]), 1)

    def test_loop_route(self):
        net = FakeNet({'A': (0, 0), 'B': (100, 0), 'C': (100, 100), 'D': (0, 100), 'X': (200, 0), 'Y': (100, 200), 'Z': (-100, 100)},
                      [('A', 'B', ST), ('B', 'C', ST), ('C', 'D', ST), ('D', 'A', ST), ('B', 'X', ST), ('C', 'Y', ST), ('D', 'Z', ST)])
        ms = mv.build(route_through(net, ['A', 'B', 'C', 'D', 'A']), net)
        self.assertEqual([m['type'] for m in ms[1:-1]], ['turn_left'] * 3)

    def test_discontinuity_is_flagged_not_guessed(self):
        net = self.plus()
        r = route_through(net, ['S', 'C', 'E'])
        r['edges'][1]['u'] = 'elsewhere'
        r['edges'][1]['geometry']['coordinates'][0] = at(0, 50)
        ms = mv.build(r, net)
        self.assertIn('notice', types(ms)); self.assertEqual(next(m for m in ms if m['type'] == 'notice')['confidence'], 'low')

    def test_multi_stop_arrivals(self):
        net = self.plus()
        ms = mv.build(route_through(net, ['S', 'C', 'E']), net, [{'name': 'Café', 'distance_along_route_m': 100, 'required': True, 'final': False, 'visit_min': 15},
                                                                 {'name': 'Museum', 'distance_along_route_m': 200, 'required': True, 'final': True}])
        arr = [m for m in ms if m['type'].startswith('arrive')]
        self.assertEqual([m['type'] for m in arr], ['arrive_stop', 'arrive']); self.assertEqual(arr[0]['stop_name'], 'Café'); self.assertEqual(arr[0]['visit_min'], 15)
        ids = [m['maneuver_id'] for m in ms]
        self.assertEqual(len(ids), len(set(ids)))


class B_RealRouteManeuvers(unittest.TestCase):
    def setUp(self):
        self.routes = []
        for a, b in (((-73.9832, 40.7536), (-73.9787, 40.7587)), ((-73.9632, 40.7794), (-73.9636, 40.8075)), ((-73.9973, 40.7308), (-73.9903, 40.7359))):
            self.routes += P.plan({'lon': a[0], 'lat': a[1]}, {'lon': b[0], 'lat': b[1]}, None, {'max_minutes': 100})['routes'][:2]

    def test_maneuvers_belong_to_the_route(self):
        for r in self.routes:
            ms = r['maneuvers']
            self.assertEqual(ms[0]['type'], 'depart'); self.assertEqual(ms[-1]['type'], 'arrive')
            nodes = {e['u'] for e in r['edges']} | {e['v'] for e in r['edges']}
            coords = r['geometry']['coordinates']
            dists = [m['distance_along_route_m'] for m in ms]
            self.assertEqual(dists, sorted(dists))
            for m in ms:
                if 'node_id' in m:
                    self.assertIn(m['node_id'], nodes, 'a turn is at a node of this route')
                p = m['coordinate']
                near = min(math.hypot((p[0] - c[0]) * M[0], (p[1] - c[1]) * M[1]) for c in coords)
                self.assertLess(near, 30, 'maneuver point lies on the route geometry')
                self.assertTrue(m['instruction_text'] and m['instruction_zh'])
                self.assertIn(m['confidence'], ('high', 'medium', 'low'))
            self.assertAlmostEqual(ms[-1]['distance_along_route_m'], r['distance_m'], delta=1)

    def test_known_route_reads_correctly(self):
        r = next(x for x in self.routes if x['objective'] == 'shortest')
        texts = [m['instruction_text'] for m in r['maneuvers']]
        self.assertIn('Turn right onto W 42nd St', texts); self.assertIn('Turn left onto 5th Ave', texts); self.assertIn('Turn left onto W 49th St', texts)

    def test_signature_and_snapshot_progress(self):
        r = self.routes[0]
        self.assertEqual(r['route_signature'], route_signature(r))
        snap = {'network_version': r['network_version'], 'ordered_edge_ids': r['ordered_edge_ids'], 'route_signature': r['route_signature']}
        saved = copy.copy(P.routes)
        P.routes.clear()   # as after a server restart
        try:
            mid = r['geometry']['coordinates'][len(r['geometry']['coordinates']) // 2]
            out = P.progress('lost-route-id', mid[0], mid[1], 10, snap)
            self.assertEqual(out['state'], 'on_route')
            with self.assertRaises(RoutingError):
                P.progress('x', mid[0], mid[1], 10, {**snap, 'network_version': 'osm-walk-older'})
            with self.assertRaises(RoutingError):
                P.progress('x', mid[0], mid[1], 10, {**snap, 'route_signature': '0000'})
            with self.assertRaises(RoutingError):
                P.progress('x', mid[0], mid[1], 10, {**snap, 'ordered_edge_ids': list(reversed(snap['ordered_edge_ids']))})
        finally:
            P.routes.update(saved)


if __name__ == '__main__':
    unittest.main()
