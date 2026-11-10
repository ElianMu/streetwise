"""Load the real NYC / OSM source snapshots kept in this repo, clean them, and project them to EPSG:32618.

Every loader returns data plus a QA record (records read, kept, dropped and why, duplicates, invalid geometry,
time window, file retrieval time). Nothing is synthesised: a source that is not present is reported missing.
"""
import datetime as dt
import glob
import gzip
import json
import os
import sqlite3
import sys

import numpy as np
import shapely
from pyproj import Transformer

from . import spec

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
TO_M = Transformer.from_crs(spec.CRS_WGS84, spec.CRS_METRIC, always_xy=True)
TO_LL = Transformer.from_crs(spec.CRS_METRIC, spec.CRS_WGS84, always_xy=True)
BOX = (-74.06, 40.67, -73.90, 40.89)  # generous Manhattan box for point sources (WGS84)


def path(rel):
    return os.path.join(ROOT, rel)


def mtime(rel):
    p = path(rel)
    return dt.datetime.fromtimestamp(os.path.getmtime(p), dt.timezone.utc).isoformat(timespec='seconds') if os.path.exists(p) else None


def qa(source, rel, read, kept, **extra):
    return {'source': source, 'file': rel, 'file_retrieved_at': mtime(rel), 'crs_in': spec.CRS_WGS84, 'crs_out': spec.CRS_METRIC,
            'records_read': int(read), 'records_kept': int(kept), **extra}


def load_json(rel):
    p = path(rel)
    return json.load(gzip.open(p) if p.endswith('.gz') else open(p))


def xy_from_lonlat(lonlat):
    a = np.asarray(lonlat, float).reshape(-1, 2)
    x, y = TO_M.transform(a[:, 0], a[:, 1])
    return np.column_stack([x, y])


def clean_points(rows, source, rel, **extra):
    """[lon, lat] rows → unique metric points inside BOX. Exact duplicate coordinates are kept (separate reports at the
    same geocoded address are separate records) but counted in QA."""
    a = np.array([r[:2] for r in rows if r is not None and len(r) >= 2 and r[0] is not None and r[1] is not None], float)
    read = len(rows)
    ok = np.isfinite(a).all(1) & (a[:, 0] >= BOX[0]) & (a[:, 0] <= BOX[2]) & (a[:, 1] >= BOX[1]) & (a[:, 1] <= BOX[3]) if len(a) else np.array([], bool)
    a = a[ok]
    dup = len(a) - len(np.unique(np.round(a, 7), axis=0)) if len(a) else 0
    return xy_from_lonlat(a) if len(a) else np.zeros((0, 2)), qa(source, rel, read, len(a), dropped_invalid_or_outside=int(read - len(a)), duplicate_coordinates=int(dup), **extra)


def geoms_metric(geojson_geoms):
    """GeoJSON geometry dicts → valid shapely geometries in metres (invalid ones repaired with make_valid)."""
    g = np.array([shapely.from_geojson(json.dumps(x)) if x else None for x in geojson_geoms], dtype=object)
    g = g[[x is not None and not x.is_empty for x in g]]
    g = shapely.transform(g, lambda c: np.column_stack(TO_M.transform(c[:, 0], c[:, 1])))
    invalid = ~shapely.is_valid(g)
    g[invalid] = shapely.make_valid(g[invalid])
    return g, int(invalid.sum())


def polygonal(g):
    """Keep one geometry per record (a landmark lot stays one lot): drop non-polygon parts make_valid may add."""
    out = []
    for x in g:
        parts = shapely.get_parts(x)
        parts = parts[shapely.get_type_id(parts) == 3]
        if len(parts):
            out.append(parts[0] if len(parts) == 1 else shapely.multipolygons(parts))
    return np.array(out, dtype=object)


def polygons_only(g):
    """Explode to Polygon parts (make_valid can return collections)."""
    parts = shapely.get_parts(g)
    return parts[shapely.get_type_id(parts) == 3]


# --- LION street segments ------------------------------------------------------------------------------------
def segments():
    """Manhattan LION analysis segments with the app's stable IDs (same rule as build_manhattan_streets.py)."""
    import build_manhattan_streets as bms
    rel = spec.SOURCES['lion']['file']
    raw = {'streets_v4': load_json(rel)}
    segs, misplaced = bms.lion_segments(raw)
    lines = np.array([shapely.linestrings(np.column_stack(TO_M.transform(*np.asarray(s['line']).T))) for s in segs], dtype=object)
    width = np.array([float(s['width']) if s.get('width') not in (None, '', 0) and float(s['width']) > 0 else np.nan for s in segs])
    rec = {'id': np.array([s['id'] for s in segs]), 'name': np.array([s['name'] for s in segs]), 'rw_type': np.array([s['rw'] for s in segs]),
           'is_path': np.array([bool(s['path']) for s in segs]), 'width_ft': width, 'geometry': lines,
           'lonlat': [s['line'] for s in segs]}
    rec['length_m'] = shapely.length(lines)
    # topology nodes = LION endpoints rounded to 1e-6° (≈0.1 m), as in the existing intersection definition
    ends = [((round(s['line'][0][0], 6), round(s['line'][0][1], 6)), (round(s['line'][-1][0], 6), round(s['line'][-1][1], 6))) for s in segs]
    rec['end_keys'] = ends
    highways = [shapely.linestrings(np.column_stack(TO_M.transform(*np.asarray(line).T))) for p, rw, i, line in bms.si.lion_lines(raw) if rw in (2, 9)]
    q = qa('lion', rel, len(raw['streets_v4']), len(segs), excluded_types='2 highway, 3 bridge, 4 tunnel, 9 ramp, 13/14 ferry & other non-walkable',
           misplaced_outside_manhattan=len(misplaced), width_missing=int(np.isnan(width).sum()), expressway_ramp_lines=len(highways),
           duplicate_ids=int(len(rec['id']) - len(set(rec['id']))))
    return rec, np.array(highways, dtype=object), q


def in_area(rec, area):
    poly = spec.AREAS[area]['polygon']
    if not poly:
        return np.ones(len(rec['id']), bool)
    P = shapely.Polygon(np.column_stack(TO_M.transform(*np.asarray(poly).T)))
    return shapely.contains_xy(P, *midpoints_xy(rec['geometry']).T)


def midpoints_xy(lines):
    return shapely.get_coordinates(shapely.line_interpolate_point(np.asarray(lines, dtype=object), 0.5, normalized=True))


# --- individual sources --------------------------------------------------------------------------------------
def lpc():
    rel = spec.SOURCES['lpc']['file']
    fs = load_json(rel)
    g, bad = geoms_metric([f.get('geometry') for f in fs])
    lots = polygonal(g)
    return lots, qa('lpc', rel, len(fs), len(lots), invalid_repaired=bad, scope="BORO='Manhattan' landmark lots", note='each lot kept whole (multi-part lots counted once)')


def trees():
    rel = spec.SOURCES['trees']['file']
    return clean_points(load_json(rel), 'trees', rel, filter="tpstructure = 'Full'")


def parks():
    rel = spec.SOURCES['parks']['file']
    rows = load_json(rel)
    g, bad = geoms_metric([r.get('multipolygon') for r in rows])
    return polygons_only(g), qa('parks', rel, len(rows), len(g), invalid_repaired=bad, scope="borough = 'M'")


def sidewalks():
    rel = spec.SOURCES['sidewalks']['file']
    rows = load_json(rel)
    g, bad = geoms_metric([r.get('the_geom') for r in rows])
    return polygons_only(g), qa('sidewalks', rel, len(rows), len(g), invalid_repaired=bad, scope='Manhattan bounding box')


def osm():
    rel = spec.SOURCES['osm']['file']
    rows = load_json(rel)
    xy, q = clean_points([r[:2] for r in rows], 'osm', rel, query='amenity|shop|tourism|leisure|historic, nodes/ways/relations (centres)')
    keep = [r for r in rows if BOX[0] <= r[0] <= BOX[2] and BOX[1] <= r[1] <= BOX[3]]
    return xy, [r[2] for r in keep], q


def noise(window):
    rel = spec.SOURCES['noise']['file']
    return clean_points(load_json(rel), 'noise', rel, time_window=window, filter="complaint_type starts with 'Noise', borough = MANHATTAN")


def collisions(window):
    rel = spec.SOURCES['collisions']['file']
    return clean_points(load_json(rel), 'collisions', rel, time_window=window, filter='pedestrians injured > 0 OR pedestrians killed > 0, borough = MANHATTAN')


def subway():
    rel = spec.SOURCES['subway']['file']
    return clean_points(load_json(rel), 'subway', rel, filter="entry_allowed = 'YES', borough = 'M'")


def seating():
    rel = spec.SOURCES['seating']['file']
    fs = load_json(rel)['features']
    m = [f['geometry']['coordinates'] for f in fs if (f['properties'].get('boroname') or '').lower() == 'manhattan' and f.get('geometry')]
    return clean_points(m, 'seating', rel, filter="boroname = 'Manhattan'", citywide_records=len(fs))


def ramps():
    rel = spec.SOURCES['ramps']['file']
    seen, pts = set(), []
    n = 0
    for f in sorted(glob.glob(path(rel))):
        for x in json.load(open(f))['features']:
            n += 1
            fid = x['properties'].get('feature_id')
            if fid in seen:
                continue
            seen.add(fid)
            pts.append(x['geometry']['coordinates'])
    return clean_points(pts, 'ramps', rel, tiles_read=n, duplicate_ids_across_tiles=n - len(seen))


def crime():
    rel = spec.SOURCES['nypd_complaints']['file']
    db_path = os.path.expanduser('~/work/complaints.sqlite')
    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with gzip.open(path(rel)) as src, open(db_path, 'wb') as dst:
            dst.write(src.read())
    db = sqlite3.connect(db_path)
    total = db.execute("select count(*) from incidents where borough='MANHATTAN'").fetchone()[0]
    rows = db.execute("select lon, lat from incidents where borough='MANHATTAN' and law in ('FELONY','MISDEMEANOR')").fetchall()
    d0, d1 = db.execute("select min(day), max(day) from incidents").fetchone()
    man = load_json('data/urban/crime/manifest.json')
    window = f'{dt.date.fromordinal(d0)} / {dt.date.fromordinal(d1)}'
    xy, q = clean_points(rows, 'nypd_complaints', rel, time_window=window, manhattan_all_law_classes=total,
                         filter='borough = MANHATTAN, law IN (FELONY, MISDEMEANOR)', duplicate_source_ids=man.get('duplicate_source_ids'),
                         dedup='historic + YTD merged on complaint number (cmplnt_num) when the store was built')
    return xy, q


def water_and_waterfront():
    """Open water (rivers, bay, channels) and public waterfront space (open WPAAs + NYC Parks properties touching water)."""
    hrel, wrel = spec.SOURCES['hydrography']['file'], spec.SOURCES['waterfront_access']['file']
    h = load_json(hrel)['features']
    hw = [f['geometry'] for f in h if str(f['properties'].get('feat_code')) in ('2620', '2660')]
    water, bad = geoms_metric(hw)
    water = polygons_only(water)
    w = load_json(wrel)['features']
    open_w = [f['geometry'] for f in w if (f['properties'].get('status') or '').strip().lower() in ('open', 'partially open')]
    wpaa, bad2 = geoms_metric(open_w)
    return water, polygons_only(wpaa), [qa('hydrography', hrel, len(h), len(water), filter='feat_code 2620 (river) / 2660 (bay, channel); ponds and reservoirs excluded', invalid_repaired=bad),
                                         qa('waterfront_access', wrel, len(w), len(open_w), filter="status Open / Partially Open", invalid_repaired=bad2)]


def osm_walk_graph():
    rel = spec.SOURCES['osm_walk']['file']
    g = load_json(rel)
    ids = list(g['nodes'])
    pos = {k: i for i, k in enumerate(ids)}
    ll = np.array([g['nodes'][k][:2] for k in ids], float)
    u, v, w = [], [], []
    for e in g['edges']:
        a, b = pos.get(str(e[0])), pos.get(str(e[1]))
        if a is not None and b is not None and e[5] is not None:
            u.append(a); v.append(b); w.append(float(e[5]))
    q = qa('osm_walk', rel, len(g['edges']), len(u), nodes=len(ids), network_version=g['metadata'].get('network_version'))
    return xy_from_lonlat(ll), np.array(u), np.array(v), np.array(w), q


def ped_counts():
    """DOT bi-annual counts → people per hour per location: period total ÷ period hours (AM 2 h, PM 3 h, Sat MD 2 h),
    median over every valid (> 0) period of the four most recent survey rounds."""
    rel = spec.SOURCES['ped_counts']['file']
    d = load_json(rel)
    hours = {k: v['hours'] for k, v in d['periods'].items()}
    out = []
    for r in d['rows']:
        rates = [r[7 + i] / hours[c.rsplit('_', 1)[-1][-2:]] for i, c in enumerate(d['cols']) if r[7 + i] and r[7 + i] > 0]
        out.append({'loc': r[0], 'street': r[1], 'from': r[2], 'to': r[3], 'lonlat': (r[5], r[6]),
                    'per_hour': float(np.median(rates)) if rates else np.nan, 'n_periods': len(rates)})
    xy = xy_from_lonlat([o['lonlat'] for o in out])
    return out, xy, qa('ped_counts', rel, len(d['rows']), sum(np.isfinite(o['per_hour']) for o in out), rounds=d['cols'],
                       publisher_rows_updated_at=d.get('publisher_rows_updated_at'), retrieved_via=d.get('retrieved_via'))


def no2():
    rel = spec.SOURCES['dohmh_no2']['file']
    d = load_json(rel)
    vals = {v[0]: {'name': v[1], 'value': v[2], 'unique_id': v[3]} for v in d['values']}
    feats = []
    for cd, typ, coords in d['boundaries']['features']:
        g = shapely.from_geojson(json.dumps({'type': typ, 'coordinates': coords}))
        feats.append((cd, g))
    return d, vals, feats, qa('dohmh_no2', rel, len(d['values']), len(feats), geography=d['geography'], time_period=d['time_period'],
                              units=d['units'], boundaries=d['boundaries']['dataset_id'])


def windows():
    meta = load_json('data/manhattan-streets.json')['metadata']
    return {'noise': f"{meta.get('noise_window_from')} → {meta.get('retrieved_at', '')[:10]} (12 months before retrieval)",
            'collisions': f"{meta.get('collision_window_from')} → {meta.get('retrieved_at', '')[:10]} (3 years before retrieval)",
            'retrieved_at': meta.get('retrieved_at')}
