"""STROLLANE · NYC — build street-level indicator values and 12 dimension scores from real NYC GIS sources.

  python3 -m scripts.dimensions.build --area midtown            # Midtown pilot
  python3 -m scripts.dimensions.build --area manhattan          # all Manhattan
  python3 -m scripts.dimensions.build --area manhattan --only crime_k --force

Each indicator is a resumable stage cached in data/dimensions/work/<area>/<key>.npz, so a run can stop at
--budget seconds and continue next time. When every stage is done the scores are exported to
data/dimensions/<area>/{segments.geojson, indicators.json, manifest.json}.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np

from . import geo, indicators, scoring, sources, spec

OUT = os.path.join(sources.ROOT, 'data', 'dimensions')
WORK = os.path.join(OUT, 'work')
CODE_FILES = ['spec.py', 'geo.py', 'sources.py', 'indicators.py', 'scoring.py', 'build.py']


def calc_version():
    h = hashlib.sha1()
    for f in CODE_FILES:
        h.update(open(os.path.join(os.path.dirname(__file__), f), 'rb').read())
    return f'{spec.SPEC_VERSION}+{h.hexdigest()[:10]}'


def log(area, **rec):
    os.makedirs(os.path.join(OUT, area), exist_ok=True)
    rec = {'at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), **rec}
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    with open(os.path.join(OUT, area, 'run_log.jsonl'), 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


class Context:
    def __init__(self, area):
        self.area = area
        os.makedirs(WORK, exist_ok=True)
        seg_cache = os.path.join(WORK, 'segments.pkl')
        if os.path.exists(seg_cache):
            self.rec, self.highways, self.seg_qa = pickle.load(open(seg_cache, 'rb'))
        else:
            self.rec, self.highways, self.seg_qa = sources.segments()
            pickle.dump((self.rec, self.highways, self.seg_qa), open(seg_cache, 'wb'))
        self.T = np.flatnonzero(sources.in_area(self.rec, area))
        self.lines = self.rec['geometry'][self.T]
        self.mids = geo.midpoints(self.lines)
        self.mids_ll = np.column_stack(sources.TO_LL.transform(self.mids[:, 0], self.mids[:, 1])) if len(self.mids) else np.zeros((0, 2))
        self._src, self._samples, self._graph, self._nodes = {}, {}, None, None
        self.qa = {'lion': self.seg_qa}

    def src(self, name):
        if name not in self._src:
            w = sources.windows()
            loader = {'lpc': sources.lpc, 'trees': sources.trees, 'parks': sources.parks, 'sidewalks': sources.sidewalks,
                      'osm': sources.osm, 'noise': lambda: sources.noise(w['noise']), 'collisions': lambda: sources.collisions(w['collisions']),
                      'subway': sources.subway, 'seating': sources.seating, 'ramps': sources.ramps, 'crime': sources.crime,
                      'water': sources.water_and_waterfront, 'ped_counts': sources.ped_counts, 'no2': sources.no2}[name]
            self._src[name] = loader()
            q = self._src[name][-1]
            for x in (q if isinstance(q, list) else [q]):
                self.qa[x['source']] = x
        return self._src[name]

    def samples(self, step):
        if step not in self._samples:
            self._samples[step] = geo.sample_along(self.lines, step)
        return self._samples[step]

    def walk_graph(self):
        if self._graph is None:
            xy, u, v, w, q = sources.osm_walk_graph()
            self._graph = geo.Graph(xy, u, v, w)
            q['nodes_outside_largest_component'] = int(self._graph.n_dropped)
            self.qa['osm_walk'] = q
        return self._graph

    def lion_nodes(self):
        """Node degree over walkable LION types and whether a roadway (type 1) touches the node."""
        if self._nodes is None:
            deg, road = {}, {}
            for ends, rw in zip(self.rec['end_keys'], self.rec['rw_type']):
                if rw in indicators.LION_WALK_TYPES:
                    for k in set(ends):
                        deg[k] = deg.get(k, 0) + 1
                        road[k] = road.get(k, False) or rw == 1
            self._nodes = (deg, road)
        return self._nodes

    @staticmethod
    def node_xy(keys):
        return sources.xy_from_lonlat(np.array(keys, float)) if len(keys) else np.zeros((0, 2))


def stage_path(area, key):
    return os.path.join(WORK, area, key + '.npz')


def run_stages(ctx, keys, budget, force):
    os.makedirs(os.path.join(WORK, ctx.area), exist_ok=True)
    t_start = time.time()
    for key in keys:
        p = stage_path(ctx.area, key)
        if os.path.exists(p) and not force:
            continue
        left = budget - (time.time() - t_start)
        if left < 20:
            return False
        t = time.time()
        fn = indicators.COMPUTE[key]
        if key == 'route_directness':
            part_p = os.path.join(WORK, ctx.area, 'route_directness.partial.pkl')
            partial = pickle.load(open(part_p, 'rb')) if os.path.exists(part_p) and not force else {}
            v, done = fn(ctx, budget_s=max(10, left - 25), partial=partial)
            if v is None:
                pickle.dump(done, open(part_p, 'wb'))
                log(ctx.area, stage=key, status='partial', origins_done=len(done), seconds=round(time.time() - t, 1))
                return False
            extras, notes = {}, indicators.ROUTE_DIRECTNESS_NOTES
        else:
            v, extras, notes = fn(ctx)
        v = np.asarray(v, float)
        assert v.shape == (len(ctx.T),), (key, v.shape)
        np.savez_compressed(p, values=v, **{f'x_{k}': np.asarray(a) for k, a in extras.items()},
                            meta=json.dumps({'notes': notes, 'qa': {k: ctx.qa[k] for k in ctx.qa}, 'seconds': round(time.time() - t, 1),
                                             'computed_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}))
        fin = np.isfinite(v)
        log(ctx.area, stage=key, status='done', segments=len(v), valid=int(fin.sum()),
            min=float(np.nanmin(v)) if fin.any() else None, median=float(np.nanmedian(v)) if fin.any() else None,
            max=float(np.nanmax(v)) if fin.any() else None, seconds=round(time.time() - t, 1))
    return True


def export(ctx):
    n = len(ctx.T)
    raw, extras, ind_meta, qa = {}, {}, {}, dict(ctx.qa)
    for x in spec.INDICATORS:
        k = x['key']
        p = stage_path(ctx.area, k)
        if os.path.exists(p):
            z = np.load(p, allow_pickle=False)
            raw[k] = np.round(z['values'], 3)  # rank exactly the published values, so outputs are reproducible from the files
            m = json.loads(str(z['meta']))
            qa.update(m['qa'])
            for e in z.files:
                if e.startswith('x_'):
                    extras[e[2:]] = z[e]
            fin = np.isfinite(raw[k])
            status = {'validation': 'validation-only', 'context': 'context-only'}.get(x['role'], 'computed')
            ind_meta[k] = {'status': status, 'valid_segments': int(fin.sum()), 'coverage': round(float(fin.mean()), 4),
                           'notes': m['notes'], 'computed_at': m['computed_at'], 'seconds': m['seconds'],
                           'stats': {q: round(float(f(raw[k][fin])), 3) for q, f in (('min', np.min), ('p50', np.median), ('max', np.max), ('mean', np.mean))} if fin.any() else None}
        else:
            reason = indicators.UNAVAILABLE.get(k, 'Not computed in this run.')
            ind_meta[k] = {'status': 'unavailable', 'valid_segments': 0, 'coverage': 0.0, 'notes': [reason]}
    pct = scoring.normalise(raw)
    scores, counts = scoring.aggregate(pct, n)

    # Validation: observed pedestrian flow vs the POI-based vibrancy model (never feeds a score).
    validation = {}
    if 'ped_flow_observed' in raw and 'vibr_idx' in raw:
        from scipy.stats import spearmanr
        m = np.isfinite(raw['ped_flow_observed']) & np.isfinite(raw['vibr_idx'])
        if m.sum() >= 5:
            uv = scores['urban_vibrancy']
            validation['urban_vibrancy_vs_ped_flow'] = {
                'locations': int(m.sum()),
                'spearman_vibr_idx': round(float(spearmanr(raw['ped_flow_observed'][m], raw['vibr_idx'][m]).correlation), 3),
                'spearman_dimension_score': round(float(spearmanr(raw['ped_flow_observed'][m], uv[m]).correlation), 3),
                'note': 'Rank correlation between DOT observed people/hour and the POI-based vibrancy model at count locations. '
                        'DOT locations are mostly busy retail corridors, so the range is restricted.'}
    # Context layer: NO₂ stays on its Community District polygons.
    no2_layer = None
    if 'no2' in ctx._src or os.path.exists(os.path.join(sources.ROOT, spec.SOURCES['dohmh_no2']['file'])):
        d, vals, feats, _ = ctx.src('no2')
        no2_layer = {'type': 'FeatureCollection', 'metadata': {k: d[k] for k in ('dataset_id', 'name', 'source_url', 'geography', 'time_period', 'measure', 'units', 'retrieved_at')},
                     'features': [{'type': 'Feature', 'properties': {'cd': int(cd), 'name': vals[cd]['name'], 'no2_ppb': round(vals[cd]['value'], 2)},
                                   'geometry': json.loads(__import__('shapely').to_geojson(g))} for cd, g in feats]}

    def num(v, nd=3):
        return None if v is None or not np.isfinite(v) else (int(v) if float(v).is_integer() and nd == 0 else round(float(v), nd))

    feats = []
    rec, T = ctx.rec, ctx.T
    for j, i in enumerate(T):
        props = {'id': rec['id'][i], 'name': rec['name'][i], 'length_m': round(float(rec['length_m'][i]), 1)}
        dims = []
        for d_i, dim in enumerate(spec.DIM_KEYS):
            s = scores[dim][j]
            props[f'd{d_i}'] = None if not np.isfinite(s) else round(float(s), 1)
            props[f'n{d_i}'] = int(counts[dim][j])
            if np.isfinite(s):
                dims.append(s)
        props['overall'] = round(float(np.mean(dims)), 1) if dims else None
        props['coverage'] = len(dims)
        feats.append({'type': 'Feature', 'properties': props,
                      'geometry': {'type': 'LineString', 'coordinates': [[round(a, 6), round(b, 6)] for a, b in rec['lonlat'][i]]}})

    dims_meta = []
    for d_i, (dim, num_, label) in enumerate(spec.DIMENSIONS):
        inds = spec.indicators_of(dim)
        scored = [x['key'] for x in inds if x['role'] in spec.SCORED_ROLES]
        avail = [k for k in scored if ind_meta[k]['status'] == 'computed']
        s = scores[dim]
        dims_meta.append({'key': dim, 'num': num_, 'label': label, 'prop': f'd{d_i}', 'count_prop': f'n{d_i}',
                          'indicators': [x['key'] for x in inds], 'scored_indicators': scored, 'available_indicators': avail,
                          'model_coverage': f'{len(avail)}/{len(scored)}',
                          'status': 'computed' if len(avail) == len(scored) else 'partial' if avail else 'unavailable',
                          'segments_with_score': int(np.isfinite(s).sum()), 'segment_coverage': round(float(np.isfinite(s).mean()), 4)})
    version = calc_version()
    src_meta = {k: {**v, 'qa': qa.get(k), 'status': 'loaded' if qa.get(k) else 'not used in this run' if v['file'] else 'not acquired'}
                for k, v in spec.SOURCES.items()}
    manifest = {
        'title': 'STROLLANE · NYC — street-level 12 Experience Dimensions', 'area': ctx.area, 'area_label': spec.AREAS[ctx.area]['label'],
        'area_polygon': spec.AREAS[ctx.area]['polygon'], 'segments': n, 'spec_version': spec.SPEC_VERSION, 'calculation_version': version,
        'built_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'crs_processing': spec.CRS_METRIC, 'crs_output': spec.CRS_WGS84,
        'comparison_scope': f'Percentiles are ranked among the {n:,} segments of this area ({spec.AREAS[ctx.area]["label"]}).',
        'score_method': spec.SCORE_METHOD, 'dimensions': dims_meta,
        'indicators': [{**x, **ind_meta[x['key']], 'sources': [spec.SOURCES[s]['label'] for s in x['db']]} for x in spec.INDICATORS],
        'sources': src_meta, 'windows': sources.windows(),
        'id_scheme': 'segment_id = "MN-" + LION physicalid (+ "-n" when several LION records share one), identical to data/manhattan-streets.json.',
        'files': {'segments': 'segments.geojson', 'indicators': 'indicators.json', **({'context_no2': 'context_no2.geojson'} if no2_layer else {})},
        'validation': validation,
        'value_note': 'Scores are relative ranks within the comparison area, not calibrated experience scores. N/A = not measurable, never 0.',
    }
    det = {'ids': [rec['id'][i] for i in T], 'calculation_version': version,
           'raw': {k: [num(x) for x in v] for k, v in raw.items()},
           'pct': {k: [num(x, 1) for x in v] for k, v in pct.items()},
           'extras': {k: [num(x) for x in v] for k, v in extras.items()}}
    d = os.path.join(OUT, ctx.area)
    os.makedirs(d, exist_ok=True)
    for name, obj in (('segments.geojson', {'type': 'FeatureCollection', 'metadata': {'calculation_version': version, 'area': ctx.area, 'segments': n}, 'features': feats}),
                      ('indicators.json', det), ('manifest.json', manifest)) + ((('context_no2.geojson', no2_layer),) if no2_layer else ()):
        tmp = os.path.join(d, name + '.tmp')
        json.dump(obj, open(tmp, 'w'), ensure_ascii=False, separators=(',', ':') if name != 'manifest.json' else None, indent=None if name != 'manifest.json' else 1, allow_nan=False)
        os.replace(tmp, os.path.join(d, name))
    log(ctx.area, stage='export', status='done', segments=n, calculation_version=version,
        dimensions={m['label']: m['model_coverage'] for m in dims_meta})
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--area', choices=list(spec.AREAS), default='midtown')
    ap.add_argument('--only', nargs='*', help='indicator keys to (re)compute')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--budget', type=float, default=150, help='seconds per invocation; stages resume on the next run')
    ap.add_argument('--no-export', action='store_true')
    a = ap.parse_args(argv)
    t = time.time()
    ctx = Context(a.area)
    keys = a.only or list(indicators.COMPUTE)
    finished = run_stages(ctx, keys, a.budget - (time.time() - t), a.force)
    if not finished:
        print('BUDGET: stopped early, run again to continue', flush=True)
        return 3
    if not a.no_export:
        export(ctx)
    return 0


if __name__ == '__main__':
    sys.exit(main())
