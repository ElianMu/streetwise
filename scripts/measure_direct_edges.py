#!/usr/bin/env python3
"""Measure the Explore map build's newer indicators on the routing edges that are not street segments.

27 % of routable length is a crossing, park path, bridge or unmatched street ("direct_osm" edges in
data/pedestrian/edge-scores.json.gz). Their scores come from raw values measured on the edge's own OSM geometry.
Until now only the 15 indicators of the earlier script were measured there. This script measures, on the same
geometry, the indicators the map build added, with the map build's OWN functions (scripts/dimensions/indicators.py)
and source snapshots that are already in this repository:

  seat_access_m         walking distance to NYC DOT seating         data/urban/context/seating.geojson.gz
  route_directness      walking-network detour ratio                 data/pedestrian/manhattan-walk-graph.json.gz
  crime_k               felony + misdemeanour report proximity       data/urban/crime/complaints.sqlite.gz
  waterfront_access_m   walking distance to public waterfront        hydrography + waterfront access + parks tiles

NOT measured, and left absent rather than approximated:
  ramp_coverage         its definition counts ramps at the LION end nodes of a street segment. A crossing or a park
                        path has no LION end nodes, so the indicator does not exist for it.

Nothing is redefined. `--verify` first runs exactly this code on the 10,533 street segments and compares the result
with the values the map build stored (data/dimensions/manhattan/indicators.json); an indicator whose stored values are
not reproduced is NOT written (see TOLERANCE). The only difference from the map build is where the geometry comes
from: the routing edge instead of the LION segment.

Needs numpy, scipy, pandas, shapely, pyproj (the same packages as scripts/dimensions/). Run from the repo root:
  python3 scripts/measure_direct_edges.py --verify     # self-check only, writes nothing
  python3 scripts/measure_direct_edges.py              # self-check, then write data/pedestrian/direct-edge-indicators.json.gz
Then: python3 scripts/transfer_dimension_scores.py && python3 scripts/build_score_indicators.py
"""
import argparse
import datetime
import glob
import gzip
import json
import os
import sys

import numpy as np
import shapely

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts.dimensions import geo, indicators, sources  # noqa: E402

GRAPH = os.path.join(ROOT, 'data', 'pedestrian', 'manhattan-walk-graph.json.gz')
SCORES = os.path.join(ROOT, 'data', 'pedestrian', 'edge-scores.json.gz')
MAP_BUILD = os.path.join(ROOT, 'data', 'dimensions', 'manhattan')
OUT = os.path.join(ROOT, 'data', 'pedestrian', 'direct-edge-indicators.json.gz')
PARK_TILES = 'data/layers/tiles/parks/*.json'
KEYS = ['seat_access_m', 'route_directness', 'crime_k', 'waterfront_access_m']
# An indicator is written only if, on street segments, at least this share of values match the map build's stored
# value within the tolerance, and where a value exists in one it exists in the other. Segment geometry is read back
# from GeoJSON (coordinates rounded to ~0.1 m), so a few midpoints snap to a neighbouring network node.
# Absolute tolerances: metres for the two distances, ratio units for directness. crime_k is a kernel sum of reports
# (street median about 150), so it is compared relatively: within 1 % of the stored value.
TOLERANCE = {'seat_access_m': 1.0, 'route_directness': 0.01, 'crime_k': 0.01, 'waterfront_access_m': 1.0}
RELATIVE = {'crime_k'}
MIN_MATCH = 0.99


def park_polygons():
    """NYC Parks Properties from the map-layer tiles in this repo (the map build read the same dataset from a download
    cache that is not committed). Tiles repeat a park that crosses a tile edge; each feature_id is used once."""
    seen, geoms = set(), []
    for f in sorted(glob.glob(os.path.join(ROOT, PARK_TILES))):
        for x in json.load(open(f))['features']:
            fid = x['properties'].get('feature_id')
            if fid in seen or not x.get('geometry'):
                continue
            seen.add(fid)
            geoms.append(x['geometry'])
    g, bad = sources.geoms_metric(geoms)
    return sources.polygons_only(g), sources.qa('parks', PARK_TILES, len(geoms), len(g), invalid_repaired=bad, scope='map-layer tiles, unique feature_id')


class Lines:
    """The part of scripts.dimensions.build.Context the four indicator functions use, for any set of lines."""

    def __init__(self, lonlat_lines, graph):
        self.lines = np.array([shapely.linestrings(np.column_stack(sources.TO_M.transform(*np.asarray(c, float).T))) for c in lonlat_lines], dtype=object)
        self.T = np.arange(len(self.lines))
        self.mids = geo.midpoints(self.lines)
        self._graph, self._src, self._samples = graph, {}, {}

    def walk_graph(self):
        return self._graph

    def samples(self, step):
        if step not in self._samples:
            self._samples[step] = geo.sample_along(self.lines, step)
        return self._samples[step]

    def src(self, name):
        if name not in self._src:
            self._src[name] = {'seating': sources.seating, 'crime': sources.crime, 'water': sources.water_and_waterfront, 'parks': park_polygons}[name]()
        return self._src[name]


def measure(ctx, keys):
    out = {}
    for k in keys:
        r = indicators.COMPUTE[k](ctx)
        out[k] = np.asarray(r[0], float)
    return out


def verify(graph):
    """Run the same code on the street segments and compare with what the map build stored."""
    stored = json.load(open(os.path.join(MAP_BUILD, 'indicators.json'), encoding='utf-8'))
    feats = {f['properties']['id']: f['geometry']['coordinates'] for f in json.load(open(os.path.join(MAP_BUILD, 'segments.geojson'), encoding='utf-8'))['features']}
    ctx = Lines([feats[i] for i in stored['ids']], graph)
    ctx._src = SHARED_SOURCES
    got = measure(ctx, KEYS)
    report = {}
    for k in KEYS:
        ref = np.array([np.nan if v is None else v for v in stored['raw'][k]], float)
        both = np.isfinite(ref) & np.isfinite(got[k])
        same_presence = float((np.isfinite(ref) == np.isfinite(got[k])).mean())
        diff = np.abs(ref[both] - got[k][both])
        allowed = TOLERANCE[k] * np.maximum(np.abs(ref[both]), 1.0) if k in RELATIVE else TOLERANCE[k]
        match = float((diff <= allowed).mean()) if both.any() else 0.0
        report[k] = {'segments': int(len(ref)), 'compared': int(both.sum()), 'same_presence': round(same_presence, 4), 'within_tolerance': round(match, 4),
                     'tolerance': f'{TOLERANCE[k]:.0%} of value' if k in RELATIVE else TOLERANCE[k], 'stored_median': round(float(np.nanmedian(ref)), 3), 'median_abs_diff': round(float(np.median(diff)), 4) if both.any() else None,
                     'p99_abs_diff': round(float(np.quantile(diff, 0.99)), 3) if both.any() else None,
                     'reproduced': bool(match >= MIN_MATCH and same_presence >= MIN_MATCH)}
    return report


SHARED_SOURCES = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='only run the self-check on street segments; write nothing')
    args = ap.parse_args()
    xy, u, v, w, _ = sources.osm_walk_graph()
    graph = geo.Graph(xy, u, v, w)
    report = verify(graph)
    print(json.dumps({'self_check_on_street_segments': report}, indent=1))
    keep = [k for k in KEYS if report[k]['reproduced']]
    if args.verify:
        return 0 if len(keep) == len(KEYS) else 1

    g = json.load(gzip.open(GRAPH, 'rt', encoding='utf-8'))
    scores = json.load(gzip.open(SCORES, 'rt', encoding='utf-8'))
    if g['metadata']['network_version'] != scores['metadata']['network_version']:
        sys.exit('walk graph and edge scores are from different network versions.')
    direct = [gi for gi, s in enumerate(scores['geoms']) if s['src'] == 'direct_osm']
    ctx = Lines([g['geoms'][gi] for gi in direct], graph)
    ctx._src = SHARED_SOURCES
    got = measure(ctx, keep)
    rnd = {'seat_access_m': 1, 'route_directness': 3, 'crime_k': 3, 'waterfront_access_m': 1}
    values = {k: [None if not np.isfinite(x) else round(float(x), rnd[k]) for x in got[k]] for k in keep}
    doc = {'network_version': g['metadata']['network_version'],
           'map_build': json.load(open(os.path.join(MAP_BUILD, 'manifest.json'), encoding='utf-8'))['calculation_version'],
           'measured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
           'method': 'scripts/measure_direct_edges.py: the map build\'s indicator functions on the OSM geometry of each directly measured edge.',
           'not_measured': {'ramp_coverage': 'defined on the LION end nodes of a street segment; a crossing or park path has none.',
                            **{k: 'self-check on street segments did not reproduce the map build\'s stored values; not written.' for k in KEYS if k not in keep}},
           'self_check_on_street_segments': report,
           'geometry_index': direct, 'values': values,
           'coverage': {k: round(sum(x is not None for x in values[k]) / max(len(direct), 1), 4) for k in keep}}
    with gzip.open(OUT + '.tmp', 'wt', encoding='utf-8') as f:
        json.dump(doc, f, separators=(',', ':'))
    os.replace(OUT + '.tmp', OUT)
    print(json.dumps({'written': os.path.relpath(OUT, ROOT), 'direct_edges': len(direct), 'indicators': keep, 'coverage': doc['coverage']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
