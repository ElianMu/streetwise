"""Tests for the 12 × 24 dimension pipeline (scripts/dimensions): units, buffers/offsets, kernels, network distance,
scoring direction, missing values, aggregation, and integrity of the exported files.

  python3 -m pytest tests/test_dimensions.py -q
"""
import json
import math
import os

import numpy as np
import pytest
import shapely

from scripts.dimensions import geo, scoring, spec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'dimensions')


def line(*xy):
    return shapely.linestrings(np.array(xy, float))


# --- specification parity --------------------------------------------------------------------------------
def test_spec_has_12_dimensions_and_24_indicators_in_table_order():
    assert [d[2] for d in spec.DIMENSIONS] == ['Architecture', 'Nature', 'Culture', 'Quiet & Relax', 'Spatial Comfort', 'Urban Vibrancy',
                                              'Food & Retail', 'Scenic & Visual', 'Walkability', 'Access & Safety', 'Environment', 'Transit Connectivity']
    groups = {d: [x['key'] for x in spec.indicators_of(d)] for d in spec.DIM_KEYS}
    assert groups == {
        'architecture': ['lpc_k'], 'nature': ['tree_km', 'park_pct', 'canopy_pct'], 'culture': ['cult_k'], 'quiet': ['noise_k', 'width_ft'],
        'spatial_comfort': ['sidewalk_pct', 'seat_access_m', 'ramp_coverage'], 'urban_vibrancy': ['vibr_idx', 'ped_flow_observed'],
        'food_retail': ['food_k'], 'scenic_visual': ['scenic_k', 'waterfront_access_m'], 'walkability': ['inter_n', 'route_directness'],
        'access_safety': ['crash_k', 'crime_k'], 'environment': ['hwy_m', 'impervious_pct', 'no2_area_context'], 'transit_connectivity': ['sub_n', 'sub_m']}


def test_parameters_match_the_table():
    P = lambda k: spec.BY_KEY[k]['params']
    assert P('lpc_k') == {'step_m': 40, 'cutoff_m': 300, 'sigma_m': 100}
    assert P('tree_km') == {'radius_m': 30, 'min_length_m': 80}
    assert P('park_pct')['offsets_m'] == [0, -20, 20, -40, 40]
    assert (P('cult_k')['cutoff_m'], P('cult_k')['sigma_m']) == (450, 150)
    assert (P('noise_k')['cutoff_m'], P('noise_k')['sigma_m']) == (150, 50)
    assert sorted(P('sidewalk_pct')['offsets_m']) == [-14, -11, -8, -5, 5, 8, 11, 14]
    assert P('seat_access_m')['cap_m'] == 500 and P('ramp_coverage')['radius_m'] == 20 and P('vibr_idx')['radius_m'] == 150
    assert (P('food_k')['cutoff_m'], P('food_k')['sigma_m']) == (150, 50)
    assert (P('scenic_k')['cutoff_m'], P('scenic_k')['sigma_m']) == (300, 100)
    assert P('inter_n')['radius_m'] == 250
    assert (P('crash_k')['cutoff_m'], P('crash_k')['sigma_m']) == (120, 40)
    assert (P('crime_k')['cutoff_m'], P('crime_k')['sigma_m']) == (300, 100)
    assert P('hwy_m')['cap_m'] == 1500 and P('sub_n')['radius_m'] == 400 and P('sub_m')['cap_m'] == 1500


def test_scoring_direction_follows_the_table():
    down = {k for k, x in spec.BY_KEY.items() if x['role'] == 'down'}
    assert down == {'noise_k', 'width_ft', 'seat_access_m', 'waterfront_access_m', 'route_directness', 'crash_k', 'crime_k', 'impervious_pct', 'sub_m'}
    assert spec.BY_KEY['hwy_m']['role'] == 'up'  # farther from highways ranks higher
    assert spec.BY_KEY['ped_flow_observed']['role'] == 'validation' and spec.BY_KEY['no2_area_context']['role'] == 'context'


# --- units, sampling, buffers ------------------------------------------------------------------------------
def test_metric_crs_lengths_are_metres():
    from pyproj import Geod, Transformer
    t = Transformer.from_crs(spec.CRS_WGS84, spec.CRS_METRIC, always_xy=True)
    a, b = (-73.9857, 40.7484), (-73.9772, 40.7527)  # ~850 m in Midtown
    x, y = t.transform([a[0], b[0]], [a[1], b[1]])
    geodesic = Geod(ellps='WGS84').line_length([a[0], b[0]], [a[1], b[1]])
    assert abs(math.hypot(x[1] - x[0], y[1] - y[0]) - geodesic) / geodesic < 0.002


def test_sample_along_spacing_and_normals():
    seg, xy, nrm = geo.sample_along([line((0, 0), (100, 0)), line((0, 0), (10, 0))], 40, with_normals=True)
    assert list(seg) == [0, 0, 1]
    assert np.allclose(xy[:, 0], [25, 75, 5]) and np.allclose(xy[:, 1], 0)
    assert np.allclose(nrm, [[0, 1]] * 3)  # left normal of an eastbound line


def test_side_offsets_share_inside_polygon():
    poly = shapely.box(-10, 10, 210, 50)  # strip 10–50 m on the left side only
    s = geo.share_inside([line((0, 0), (200, 0))], [poly], 20, [0, -20, 20, -40, 40])
    assert s[0] == pytest.approx(2 / 5)  # +20 and +40 inside, 0 / −20 / −40 outside


def test_snap_count_assigns_corner_tree_once_and_uses_80m_floor():
    a, b = line((0, 0), (50, 0)), line((0, 0), (0, 200))
    cnt, per_km = geo.snap_count_per_line([a, b], np.array([[5, 3], [3, 150], [100, 100]]), 30, 80)
    assert cnt.sum() == 2 and list(cnt) == [1, 1]  # far tree ignored, corner tree counted once
    assert per_km[0] == pytest.approx(1 / 0.08) and per_km[1] == pytest.approx(1 / 0.2)


# --- kernels and distances ---------------------------------------------------------------------------------
def test_gaussian_kernel_weights_cutoff_and_mean_over_samples():
    seg = np.array([0, 0])
    smp = np.array([[0.0, 0.0], [1000.0, 0.0]])
    src = np.array([[0.0, 100.0], [0.0, 0.0], [0.0, 301.0]])
    v = geo.gaussian_kernel(seg, smp, 1, src, sigma=100, cutoff=300)
    assert v[0] == pytest.approx((math.exp(-0.5) + 1.0) / 2)  # second sample has nothing; point at 301 m is cut off


def test_polygon_kernel_is_one_inside_the_lot():
    v = geo.gaussian_kernel_polygons(np.array([0]), np.array([[5.0, 5.0]]), 1, [shapely.box(0, 0, 10, 10)], 100, 300)
    assert v[0] == pytest.approx(1.0)


def test_nearest_distance_cap_and_count_within():
    pts = np.array([[0.0, 0.0]])
    assert geo.nearest_distance(pts, np.array([[3.0, 4.0]]), 1500)[0] == pytest.approx(5)
    assert geo.nearest_distance(pts, np.array([[3000.0, 0.0]]), 1500)[0] == 1500
    assert geo.count_within(pts, np.array([[0, 399.0], [0, 401.0]]), 400)[0] == 1
    assert geo.nearest_line_distance(pts, [line((-10, 20), (10, 20))], 1500)[0] == pytest.approx(20)


def test_network_multi_source_distance_follows_edges_not_straight_line():
    # U-shaped path: 0-(0,0) 1-(0,100) 2-(10,100) 3-(10,0); nodes 0 and 3 are 10 m apart in a straight line
    xy = np.array([[0, 0], [0, 100], [10, 100], [10, 0], [500, 500]], float)
    G = geo.Graph(xy, [0, 1, 2], [1, 2, 3], [100, 10, 100])
    assert G.n_dropped == 1  # isolated node outside the largest component
    d = G.multi_source(np.array([0]), np.array([0.0]), limit=1000)
    assert d[3] == pytest.approx(210)
    d2 = G.multi_source(np.array([0, 3]), np.array([50.0, 0.0]), limit=1000)
    assert d2[0] == pytest.approx(50) and d2[1] == pytest.approx(110)


# --- scoring -------------------------------------------------------------------------------------------------
def test_percentile_ties_lowest_rank_invert_and_nan():
    v = np.array([0, 0, 5, 10, np.nan])
    assert list(scoring.percentile(v)[:4]) == [0, 0, pytest.approx(66.7), 100]
    inv = scoring.percentile(v, invert=True)
    assert list(inv[:4]) == [100, 100, pytest.approx(33.3), 0]  # fewer complaints rank higher
    assert np.isnan(inv[4])  # missing stays missing, never 0


def test_normalise_skips_validation_and_context():
    raw = {'noise_k': np.array([1.0, 2.0]), 'ped_flow_observed': np.array([10.0, 20.0]), 'no2_area_context': np.array([np.nan, np.nan])}
    assert set(scoring.normalise(raw)) == {'noise_k'}


def test_aggregate_equal_weight_coverage_and_na():
    pct = {'tree_km': np.array([80.0, np.nan, np.nan]), 'park_pct': np.array([40.0, 20.0, np.nan])}
    s, c = scoring.aggregate(pct, 3)
    assert s['nature'][0] == 60 and s['nature'][1] == 20 and np.isnan(s['nature'][2])
    assert list(c['nature']) == [2, 1, 0]
    assert np.isnan(s['culture']).all() and list(c['culture']) == [0, 0, 0]  # no indicator → N/A, not 0


# --- exported data integrity (runs when the pipeline output exists) -------------------------------------------
AREAS = [a for a in ('midtown', 'manhattan') if os.path.exists(os.path.join(OUT, a, 'manifest.json'))]


@pytest.mark.parametrize('area', AREAS)
def test_export_scores_recompute_from_indicator_file(area):
    m = json.load(open(os.path.join(OUT, area, 'manifest.json')))
    D = json.load(open(os.path.join(OUT, area, 'indicators.json')))
    fc = json.load(open(os.path.join(OUT, area, 'segments.geojson')))
    assert m['calculation_version'] == D['calculation_version'] == fc['metadata']['calculation_version']
    ids = [f['properties']['id'] for f in fc['features']]
    assert ids == D['ids'] and len(set(ids)) == len(ids) == m['segments']
    pct = {k: np.array([np.nan if x is None else x for x in v], float) for k, v in D['pct'].items()}
    s, c = scoring.aggregate(pct, len(ids))
    for j, dim in enumerate(spec.DIM_KEYS):
        got = np.array([np.nan if f['properties'][f'd{j}'] is None else f['properties'][f'd{j}'] for f in fc['features']])
        assert np.allclose(got, s[dim], equal_nan=True, atol=0.051), dim
        assert [f['properties'][f'n{j}'] for f in fc['features']] == list(c[dim])
    # percentiles recompute from raw values
    for k, v in D['raw'].items():
        if spec.BY_KEY[k]['role'] in spec.SCORED_ROLES:
            r = scoring.percentile(np.array([np.nan if x is None else x for x in v], float), invert=spec.BY_KEY[k]['role'] == 'down')
            assert np.allclose(r, pct[k], equal_nan=True, atol=0.051), k


@pytest.mark.parametrize('area', AREAS)
def test_export_is_honest_about_missing_sources(area):
    m = json.load(open(os.path.join(OUT, area, 'manifest.json')))
    D = json.load(open(os.path.join(OUT, area, 'indicators.json')))
    st = {x['key']: x for x in m['indicators']}
    for k in ('canopy_pct', 'impervious_pct'):
        assert st[k]['status'] == 'unavailable' and k not in D['raw'] and st[k]['notes']
    assert st['no2_area_context']['status'] == 'context-only' and all(v is None for v in D['raw']['no2_area_context'])
    assert st['ped_flow_observed']['status'] == 'validation-only'
    assert 'ped_flow_observed' not in D['pct'] and 'no2_area_context' not in D['pct']
    dims = {d['key']: d for d in m['dimensions']}
    assert dims['nature']['model_coverage'] == '2/3' and dims['nature']['status'] == 'partial'
    assert dims['environment']['model_coverage'] == '1/2' and dims['environment']['status'] == 'partial'
    # a segment with no measurable indicator in a dimension must be null, never 0
    fc = json.load(open(os.path.join(OUT, area, 'segments.geojson')))
    for f in fc['features']:
        for j in range(12):
            assert (f['properties'][f'n{j}'] == 0) == (f['properties'][f'd{j}'] is None)


@pytest.mark.skipif('manhattan' not in AREAS or not os.path.exists(os.path.join(ROOT, 'data/cache/sources/lpc.json')), reason='needs source cache')
def test_lpc_k_matches_an_independent_brute_force_computation():
    """Recompute lpc_k for a few segments with plain GeoPandas, without the pipeline's helpers."""
    import geopandas as gpd
    from shapely.geometry import shape
    lots = gpd.GeoSeries([shape(f['geometry']) for f in json.load(open(os.path.join(ROOT, 'data/cache/sources/lpc.json')))], crs=4326).to_crs(32618).make_valid()
    fc = json.load(open(os.path.join(OUT, 'manhattan', 'segments.geojson')))
    D = json.load(open(os.path.join(OUT, 'manhattan', 'indicators.json')))
    idx = {i: k for k, i in enumerate(D['ids'])}
    rng = np.random.default_rng(3)
    for f in rng.choice(fc['features'], 8, replace=False):
        g = gpd.GeoSeries([shape(f['geometry'])], crs=4326).to_crs(32618).iloc[0]
        n = max(1, round(g.length / 40))
        vals = []
        for k in range(n):
            p = g.interpolate((k + .5) * g.length / n)
            d = lots.distance(p)
            d = d[d <= 300]
            vals.append(float(np.exp(-(d ** 2) / (2 * 100 ** 2)).sum()))
        assert np.mean(vals) == pytest.approx(D['raw']['lpc_k'][idx[f['properties']['id']]], abs=0.002)
