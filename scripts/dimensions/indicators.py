"""One function per indicator row of the 12 × 24 specification. Each returns (raw values for the target segments —
NaN where the indicator cannot be measured for that segment —, extras dict, notes list).

`ctx` (see build.Context) supplies: all Manhattan segments (rec), target indices (T), target lines / midpoints,
40 m kernel samples, and lazily loaded sources (ctx.src(name)).
"""
import math
from collections import Counter

import numpy as np
from scipy.spatial import cKDTree

from . import geo
from .spec import BY_KEY

CULTURE_TAGS = {('amenity', v) for v in ('theatre', 'arts_centre', 'cinema', 'library', 'music_venue', 'concert_hall')} | {('tourism', v) for v in ('museum', 'gallery')}
FOOD_AMENITY = {'restaurant', 'cafe', 'bar', 'pub', 'fast_food', 'ice_cream', 'food_court', 'biergarten'}
SCENIC_TAGS = {('tourism', 'viewpoint'), ('tourism', 'artwork'), ('amenity', 'fountain'), ('historic', 'memorial'), ('historic', 'monument')}
LION_WALK_TYPES = {1, 6, 7, 10}


def P(key):
    return BY_KEY[key]['params']


def _kernel(ctx, src_xy, key):
    p = P(key)
    seg, xy = ctx.samples(p['step_m'])
    return geo.gaussian_kernel(seg, xy, len(ctx.T), src_xy, p['sigma_m'], p['cutoff_m'])


def _osm_subset(ctx, pred):
    xy, tags, _ = ctx.src('osm')
    m = np.array([pred(t) for t in tags], bool)
    return xy[m]


# --- 01 Architecture ---------------------------------------------------------------------------------------
def lpc_k(ctx):
    polys, _ = ctx.src('lpc')
    p = P('lpc_k')
    seg, xy = ctx.samples(p['step_m'])
    v = geo.gaussian_kernel_polygons(seg, xy, len(ctx.T), polys, p['sigma_m'], p['cutoff_m'])
    return v, {}, ['Distance is to the landmark lot polygon (0 inside the lot); each lot (incl. multi-part lots) counted once per sample.']


# --- 02 Nature ---------------------------------------------------------------------------------------------
def tree_km(ctx):
    xy, _ = ctx.src('trees')
    p = P('tree_km')
    cnt, per_km = geo.snap_count_per_line(ctx.rec['geometry'], xy, p['radius_m'], p['min_length_m'])
    return per_km[ctx.T], {'tree_n': cnt[ctx.T]}, ['Each tree is assigned to its single nearest walkable segment within 30 m so trees at corners are not double-counted.']


def park_pct(ctx):
    polys, _ = ctx.src('parks')
    p = P('park_pct')
    return geo.share_inside(ctx.lines, polys, p['step_m'], p['offsets_m']), {}, ['Samples every 20 m at offsets 0, ±20, ±40 m.']


# --- 03 Culture --------------------------------------------------------------------------------------------
def cult_k(ctx):
    src = _osm_subset(ctx, lambda t: any(t.get(k) == v for k, v in CULTURE_TAGS))
    return _kernel(ctx, src, 'cult_k'), {}, [f'{len(src)} cultural POIs (museum, gallery, theatre, arts centre, cinema, library, music venue, concert hall).']


# --- 04 Quiet & Relax --------------------------------------------------------------------------------------
def noise_k(ctx):
    xy, _ = ctx.src('noise')
    return _kernel(ctx, xy, 'noise_k'), {}, [f'{len(xy)} geolocated noise complaints in the 12-month window.']


def width_ft(ctx):
    return ctx.rec['width_ft'][ctx.T], {}, ['N/A where LION records no roadway width (common on park paths and step streets).']


# --- 05 Spatial Comfort ------------------------------------------------------------------------------------
def sidewalk_pct(ctx):
    polys, _ = ctx.src('sidewalks')
    p = P('sidewalk_pct')
    v = geo.share_inside(ctx.lines, polys, p['step_m'], p['offsets_m'])
    v[ctx.rec['is_path'][ctx.T]] = np.nan
    return v, {}, ['N/A on park paths and step streets (LION types 6, 7): they have no curbside sidewalk to measure.']


def seat_access_m(ctx):
    G = ctx.walk_graph()
    seats, _ = ctx.src('seating')
    cap = P('seat_access_m')['cap_m']
    node, snap = G.snap(seats)
    ok = snap <= 100
    d = G.multi_source(node[ok], snap[ok], limit=cap + 1)
    mnode, msnap = G.snap(ctx.mids)
    v = np.minimum(d[mnode] + msnap, cap)
    return v, {}, [f'{int(ok.sum())} of {len(seats)} Manhattan seats linked to the OSM pedestrian network (≤100 m snap).',
                   'Midpoint joins the network at its nearest walk-graph node; values ≥ 500 m are capped at 500.']


def ramp_coverage(ctx):
    ramps, _ = ctx.src('ramps')
    r = P('ramp_coverage')['radius_m']
    deg, road = ctx.lion_nodes()
    keys = sorted(deg)
    kxy = ctx.node_xy(keys)
    kd = cKDTree(ramps)
    covered = dict(zip(keys, [len(x) > 0 for x in kd.query_ball_point(kxy, r)]))
    v = np.full(len(ctx.T), np.nan)
    elig_n = np.zeros(len(ctx.T), int)
    for j, i in enumerate(ctx.T):
        el = [k for k in ctx.rec['end_keys'][i] if deg.get(k, 0) >= 3 and road.get(k)]
        elig_n[j] = len(el)
        if el:
            v[j] = sum(covered[k] for k in el) / len(el)
    return v, {'ramp_nodes': elig_n}, ['Eligible nodes = segment end nodes joining ≥3 walkable segments, at least one a roadway (a crossing). '
                                      'N/A when a segment has no eligible crossing node.']


# --- 06 Urban Vibrancy -------------------------------------------------------------------------------------
def poi_category(t):
    for k in ('amenity', 'shop', 'tourism', 'leisure', 'historic'):
        if k in t:
            return 'shop' if k == 'shop' else f'{k}={t[k]}'
    return None


def vibr_idx(ctx):
    xy, tags, _ = ctx.src('osm')
    cats = np.array([poi_category(t) for t in tags], dtype=object)
    m = cats != None  # noqa: E711
    xy, cats = xy[m], cats[m]
    r = P('vibr_idx')['radius_m']
    near = cKDTree(xy).query_ball_point(ctx.mids, r)
    v, n_out, h_out = np.zeros(len(ctx.T)), np.zeros(len(ctx.T), int), np.zeros(len(ctx.T))
    for j, idx in enumerate(near):
        c = Counter(cats[idx])
        n = sum(c.values())
        k = len(c)
        H = -sum(x / n * math.log(x / n) for x in c.values()) / math.log(k) if n >= 2 and k > 1 else 0.0
        v[j], n_out[j], h_out[j] = H * math.log1p(n), n, H
    return v, {'poi_n': n_out, 'diversity_h': h_out}, ['H = Shannon entropy of activity types ÷ ln(number of types present) (0–1).']


# --- 07 Food & Retail --------------------------------------------------------------------------------------
def food_k(ctx):
    src = _osm_subset(ctx, lambda t: t.get('amenity') in FOOD_AMENITY or 'shop' in t)
    return _kernel(ctx, src, 'food_k'), {}, [f'{len(src)} food, drink and shop POIs.']


# --- 08 Scenic & Visual ------------------------------------------------------------------------------------
def scenic_k(ctx):
    src = _osm_subset(ctx, lambda t: any(t.get(k) == v for k, v in SCENIC_TAGS))
    return _kernel(ctx, src, 'scenic_k'), {}, [f'{len(src)} viewpoints, artworks, fountains, memorials and monuments.']


def waterfront_access_m(ctx):
    import shapely
    G = ctx.walk_graph()
    water, wpaa, _ = ctx.src('water')
    parks, _ = ctx.src('parks')
    p = P('waterfront_access_m')
    # public waterfront space = open WPAAs + NYC Parks properties within 30 m of open water
    wt = shapely.STRtree(water)
    pi, _ = wt.query(parks, predicate='dwithin', distance=30)
    space = np.concatenate([wpaa, parks[np.unique(pi)]])
    nodes = shapely.points(G.xy)
    in_space = np.zeros(len(G.xy), bool)
    a, _ = shapely.STRtree(space).query(nodes, predicate='intersects')
    in_space[np.unique(a)] = True
    near_water = np.zeros(len(G.xy), bool)
    b, _ = wt.query(nodes, predicate='dwithin', distance=p['entrance_water_m'])
    near_water[np.unique(b)] = True
    ent = np.flatnonzero(in_space & near_water)
    d = G.multi_source(ent, np.zeros(len(ent)), limit=p['cap_m'] + 1)
    mnode, msnap = G.snap(ctx.mids)
    v = np.minimum(d[mnode] + msnap, p['cap_m'])
    return v, {}, [f'{len(ent)} valid entrances: connected walk-graph nodes inside public waterfront space (open WPAA or a park within 30 m of river/bay) '
                   f'and within {p["entrance_water_m"]} m of open water. Capped at {p["cap_m"]} m.']


# --- 09 Walkability ----------------------------------------------------------------------------------------
def inter_n(ctx):
    deg, _ = ctx.lion_nodes()
    junctions = [k for k, d in deg.items() if d >= 3]
    return geo.count_within(ctx.mids, ctx.node_xy(junctions), P('inter_n')['radius_m']).astype(float), {}, [f'{len(junctions)} LION junctions (≥3 walkable segments).']


def route_directness(ctx, budget_s=None, partial=None):
    """Median network/straight-line ratio from the segment's network node to up to 8 nodes 250–500 m away (one per 45° sector)."""
    import time
    G = ctx.walk_graph()
    p = P('route_directness')
    r0, r1 = p['ring_m']
    origin, _ = G.snap(ctx.mids)
    uniq = np.unique(origin)
    done = dict(partial or {})
    todo = np.array([o for o in uniq if o not in done])
    t0 = time.time()
    for s, D in G.from_many(todo, limit=3 * r1, batch=100):
        for row, o in zip(D, todo[s:s + 100]):
            cand = np.array(G.kd.query_ball_point(G.xy[o], r1))
            if not len(cand):
                done[o] = np.nan; continue
            dv = G.xy[cand] - G.xy[o]
            e = np.hypot(dv[:, 0], dv[:, 1])
            m = e >= r0
            cand, dv, e = cand[m], dv[m], e[m]
            sector = ((np.arctan2(dv[:, 1], dv[:, 0]) + np.pi) / (2 * np.pi) * p['sectors']).astype(int) % p['sectors']
            ratios = []
            for k in range(p['sectors']):
                sk = np.flatnonzero(sector == k)
                if not len(sk):
                    continue
                pick = sk[np.argmin(np.abs(e[sk] - (r0 + r1) / 2))]
                if np.isfinite(row[cand[pick]]):
                    ratios.append(max(1.0, row[cand[pick]] / e[pick]))
            done[o] = float(np.median(ratios)) if len(ratios) >= p['min_pairs'] else np.nan
        if budget_s and time.time() - t0 > budget_s:
            return None, done
    v = np.array([done[o] for o in origin])
    return v, done


ROUTE_DIRECTNESS_NOTES = ['Origin = walk-graph node nearest the midpoint; destinations = node closest to 375 m in each 45° sector of the '
                          '250–500 m ring; pairs unreachable within 1.5 km excluded; N/A with fewer than 3 feasible pairs.']


# --- 10 Access & Safety ------------------------------------------------------------------------------------
def crash_k(ctx):
    xy, _ = ctx.src('collisions')
    return _kernel(ctx, xy, 'crash_k'), {}, [f'{len(xy)} pedestrian-injury/fatal crashes in the 3-year window. Not adjusted for pedestrian volume.']


def crime_k(ctx):
    xy, _ = ctx.src('crime')
    return _kernel(ctx, xy, 'crime_k'), {}, [f'{len(xy)} felony + misdemeanor complaint reports. Report density is a proxy, not personal risk.']


# --- 11 Environment ----------------------------------------------------------------------------------------
def hwy_m(ctx):
    hw = ctx.highways
    return geo.nearest_line_distance(ctx.mids, hw, P('hwy_m')['cap_m']), {}, [f'{len(hw)} LION expressway / ramp centerlines (types 2, 9).']


# --- 12 Transit Connectivity -------------------------------------------------------------------------------
def sub_n(ctx):
    xy, _ = ctx.src('subway')
    return geo.count_within(ctx.mids, xy, P('sub_n')['radius_m']).astype(float), {}, [f'{len(xy)} entry-permitted entrances.']


def sub_m(ctx):
    xy, _ = ctx.src('subway')
    return geo.nearest_distance(ctx.mids, xy, P('sub_m')['cap_m']), {}, []


# --- validation / context (never scored) -------------------------------------------------------------------
def ped_flow_observed(ctx):
    """Observed people/hour at DOT count locations, attached to the segment each mid-block screenline sits on."""
    import shapely
    locs, xy, _ = ctx.src('ped_counts')
    v = np.full(len(ctx.T), np.nan)
    loc_id = np.full(len(ctx.T), np.nan)
    if len(xy):
        (pi, gi), d = shapely.STRtree(ctx.lines).query_nearest(shapely.points(xy), max_distance=30, return_distance=True, all_matches=False)
        for p, g in zip(pi, gi):
            if np.isfinite(locs[p]['per_hour']):
                v[g] = locs[p]['per_hour'] if np.isnan(v[g]) else (v[g] + locs[p]['per_hour']) / 2
                loc_id[g] = locs[p]['loc']
    return v, {'ped_loc': loc_id}, [f'{int(np.isfinite(v).sum())} segments carry one of {len(locs)} Manhattan DOT count locations (snapped ≤ 30 m). '
                                     'Rate = period total ÷ hours (weekday 7–9 AM, 4–7 PM; Saturday 12–2 PM), median of valid periods in the 4 most recent rounds '
                                     '(Oct 2024 – May 2026). Validation evidence only — never part of a street score.']


def no2_area_context(ctx):
    """Context only: records which Community District each segment lies in; the NO₂ value stays on the CD polygon layer."""
    import shapely
    _, vals, feats, _ = ctx.src('no2')
    cd = np.full(len(ctx.T), np.nan)
    pts = shapely.points(ctx.mids_ll)
    for code, g in feats:
        cd[shapely.contains(g, pts)] = int(code)
    return np.full(len(ctx.T), np.nan), {'cd': cd}, ['Annual mean NO₂ 2024 (ppb) by Community District, DOHMH NYCCAS. Shown as a neighbourhood-scale '
                                                    'context layer; the value is deliberately NOT assigned to street segments and never scored.']


COMPUTE = {k: v for k, v in globals().items() if k in BY_KEY and callable(v)}

UNAVAILABLE = {
    'canopy_pct': 'Spec requires the TNC / UVM 2021 land-cover raster. It is not in the repo, and NYC Open Data only publishes the 2017 '
                  'edition (he6d-2qns, 6-in, 1.33 GB zip). The 2017 raster is not substituted for the 2021 one. N/A until the 2021 raster is supplied.',
    'impervious_pct': 'Same TNC / UVM 2021 land-cover raster as canopy_pct; not acquired, not substituted. N/A.',
}
