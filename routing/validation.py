"""Independent route quality assurance: every route the engine returns carries a `validation` object.

The checks re-read the route against the pedestrian network instead of trusting the search that produced it:
  geometry_status            finite coordinates inside NYC; consecutive edges join (≤ 1 m); no implausible jumps
  pedestrian_network_status  every edge ID exists on the network version, belongs to the routable component, is open to
                             pedestrians (no motorway / foot=no / private); stairs absent when avoided. Live closures and
                             construction are not known: reported as a warning, never claimed checked.
  required_stops_status      each required stop is actually reached (route passes within 15 m of its access point)
  stop_access_status         distance from each mapped place to its network access point (≤ 30 m pass, ≤ 80 m warning, more = review)
  time_constraint_status / distance_constraint_status   against the hard limits that were applied
  food_evidence_status       Not Checked on the server: item evidence is a separate step (POST /api/menu/verify)
  data_coverage              length-weighted share of the 12 dimensions with data; N/A dimensions listed, never 0
Overall status: Fail when any blocking issue exists (navigation must not start), Pass with Warnings, or Pass.
"""
import math
from datetime import datetime, timezone

VALIDATION_VERSION = 'sw-validate-1'
NYC_BBOX = (-74.2591, 40.4774, -73.7004, 40.9176)
JOIN_TOL_M, JUMP_M = 1.0, 800.0
STOP_REACH_M, ACCESS_OK_M, ACCESS_WARN_M = 15.0, 30.0, 80.0
BLOCKED_HIGHWAY = {'motorway', 'motorway_link', 'trunk_link'}
MX, MY = 84414.3, 111049.7


def _m(a, b):
    return math.hypot((a[0] - b[0]) * MX, (a[1] - b[1]) * MY)


def _dist_to_line(p, coords):
    best = math.inf
    px, py = p[0] * MX, p[1] * MY
    for a, b in zip(coords, coords[1:]):
        ax, ay, bx, by = a[0] * MX, a[1] * MY, b[0] * MX, b[1] * MY
        ux, uy = bx - ax, by - ay
        l2 = ux * ux + uy * uy
        t = max(0.0, min(1.0, ((px - ax) * ux + (py - ay) * uy) / l2)) if l2 else 0.0
        best = min(best, math.hypot(px - ax - t * ux, py - ay - t * uy))
    return best


def _status(items):
    s = [x for x in items if x]
    if 'fail' in s:
        return 'fail'
    if 'warning' in s:
        return 'pass_with_warnings'
    return 'pass' if s else 'not_checked'


def validate(route, net, constraints=None, stops=None, now=None):
    """route: Route Object; stops: [{'name','lat','lon','required','snap_distance_m'}] for itineraries."""
    constraints, stops = constraints or {}, stops or []
    blocking, warnings = [], []
    coords = route['geometry']['coordinates']

    # geometry ---------------------------------------------------------------------------------------------
    g = 'pass'
    if len(coords) < 2 or not all(isinstance(c, (list, tuple)) and len(c) == 2 and all(math.isfinite(v) for v in c) for c in coords):
        g = 'fail'; blocking.append('Route geometry has missing or invalid coordinates.')
    elif not all(NYC_BBOX[0] <= c[0] <= NYC_BBOX[2] and NYC_BBOX[1] <= c[1] <= NYC_BBOX[3] for c in coords):
        g = 'fail'; blocking.append('Route geometry leaves New York City.')
    edges = route.get('edges') or []
    for k, (a, b) in enumerate(zip(edges, edges[1:])):
        ga, gb = a['geometry']['coordinates'], b['geometry']['coordinates']
        if ga and gb and _m(ga[-1], gb[0]) > JOIN_TOL_M:
            g = 'fail'; blocking.append(f'Edges {a["edge_id"]} and {b["edge_id"]} do not join ({_m(ga[-1], gb[0]):.0f} m gap).')
            break
    jumps = [round(_m(a, b)) for a, b in zip(coords, coords[1:]) if _m(a, b) > JUMP_M]
    if jumps and g == 'pass':
        g = 'warning'; warnings.append(f'{len(jumps)} straight geometry run(s) longer than {JUMP_M:.0f} m (long straight paths or bridges).')

    # pedestrian network -----------------------------------------------------------------------------------
    n = 'pass'
    unknown, closed, steps = [], [], 0
    for e in edges:
        i = net.by_id.get(e['edge_id'])
        if i is None:
            unknown.append(e['edge_id']); continue
        u, v, k, gi, rev, length, osmids, tags = net.edges[i]
        if net.nodes[u][3] != 0 or net.nodes[v][3] != 0:
            closed.append(e['edge_id'])
        hw = tags.get('highway')
        hw = hw if isinstance(hw, list) else [hw]
        foot = tags.get('foot')
        if set(hw) & BLOCKED_HIGHWAY or foot in ('no', 'private') or tags.get('access') in ('no', 'private'):
            closed.append(e['edge_id'])
        steps += bool(tags.get('_steps'))
    if unknown:
        n = 'fail'; blocking.append(f'{len(unknown)} edge ID(s) are not on network {net.network_version}.')
    if closed:
        n = 'fail'; blocking.append(f'{len(closed)} edge(s) are outside the routable pedestrian network or closed to pedestrians.')
    if constraints.get('avoid_stairs') and steps:
        n = 'fail'; blocking.append(f'Route uses {steps} stair edge(s) although stairs are to be avoided.')
    elif steps:
        warnings.append(f'Route includes {steps} stair segment(s) (OpenStreetMap highway=steps).')
    warnings.append('Live closures and construction are not known to STREETWISE; passability is as mapped in OpenStreetMap.')
    if n == 'pass':
        n = 'pass_with_warnings'

    # stops ------------------------------------------------------------------------------------------------
    req = [s for s in stops if s.get('required')]
    rs = 'not_checked' if not req else 'pass'
    for s in req:
        d = _dist_to_line((s['lon'], s['lat']), coords) - (s.get('snap_distance_m') or 0)
        if d > STOP_REACH_M:
            rs = 'fail'; blocking.append(f'Required stop “{s["name"]}” is not reached by the route ({d:.0f} m away).')
    sa = 'not_checked' if not stops else 'pass'
    for s in stops:
        sd = s.get('snap_distance_m')
        if sd is None:
            continue
        if sd > ACCESS_WARN_M:
            sa = 'warning'; warnings.append(f'“{s["name"]}” is {sd:.0f} m from its nearest walkable access point; check the entrance on arrival.')
        elif sd > ACCESS_OK_M and sa == 'pass':
            sa = 'warning'; warnings.append(f'“{s["name"]}” access point approximated ({sd:.0f} m from the mapped location).')

    # Required visit feasibility also gates navigation; geometry alone is insufficient.
    known = [s for s in stops if s.get('open_at_arrival') is not None]
    tw = 'not_checked' if not known else 'pass'
    for s in known:
        if s['open_at_arrival'] is False and s.get('required'):
            tw = 'fail'
        elif s.get('closes_during_visit') and tw == 'pass':
            tw = 'warning'; warnings.append(f'“{s["name"]}” closes during the planned visit (OpenStreetMap hours).')
    if tw == 'fail':
        warnings.append('A required stop is closed at its estimated arrival; reorder, replace it or change the start time.')

    if route.get('constraints', {}).get('feasible') is False:
        blocking.extend(str(v) for v in route['constraints'].get('violations', []) if str(v) not in blocking)
        if not route['constraints'].get('violations'): blocking.append('Route does not satisfy required constraints')

    # constraints ------------------------------------------------------------------------------------------
    viol = route.get('constraints', {}).get('violations', [])
    tc = 'not_checked' if constraints.get('max_minutes') is None and constraints.get('max_outing_minutes') is None else (
        'fail' if any('min' in v for v in viol) else 'pass')
    dc = 'not_checked' if constraints.get('max_km') is None else ('fail' if any('km limit' in v for v in viol) else 'pass')
    if tc == 'fail':
        warnings.append('Walking-time limit not met (see constraints).')
    if dc == 'fail':
        warnings.append('Distance limit not met (see constraints).')

    # data coverage ----------------------------------------------------------------------------------------
    cov = route.get('data_coverage') or {}
    na = [d for d, v in (route.get('dimension_scores') or {}).items() if v is None]
    coverage = {'mean': cov.get('mean'), 'low_coverage_dimensions': cov.get('low_coverage_dimensions', []), 'not_available': na,
                'score_version': route.get('score_version'), 'network_version': route.get('network_version')}
    if na:
        warnings.append(f'{len(na)} dimension(s) have no data on this route and are shown as N/A: {", ".join(na)}.')

    checks = {'geometry_status': g, 'pedestrian_network_status': n, 'required_stops_status': rs, 'stop_access_status': sa,
              'time_constraint_status': tc, 'distance_constraint_status': dc, 'opening_hours_status': tw, 'food_evidence_status': 'not_checked'}
    status = 'fail' if blocking else _status([('warning' if v == 'pass_with_warnings' else v) for v in checks.values() if v != 'not_checked'] + (['warning'] if warnings else []))
    return {**checks, 'status': status, 'navigation_allowed': not blocking,
            'data_coverage': coverage, 'warnings': warnings, 'blocking_issues': blocking, 'validation_version': VALIDATION_VERSION,
            'validation_timestamp': (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')}
