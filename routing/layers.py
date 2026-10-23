"""Reference implementation of the Navigate urban-data queries over the static tiles in data/layers.

The browser runs the same logic in urban-geo.js; tests use this module to compute expected results independently
(brute force over the tiles) and to validate the tiles themselves. Standard library only.
"""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS = os.path.join(ROOT, 'data', 'layers')


class Catalog:
    def __init__(self):
        self.doc = json.load(open(os.path.join(LAYERS, 'catalog.json'), encoding='utf-8'))
        p = self.doc['projection']
        self.mx, self.my, self.size = p['mx'], p['my'], self.doc['tile_size_m']
        self.datasets = {d['id']: d for d in self.doc['datasets']}

    def xy(self, c):
        return (c[0] * self.mx, c[1] * self.my)

    def tile_keys(self, box):
        return [f'{tx}_{ty}' for tx in range(math.floor(box[0] / self.size), math.floor(box[2] / self.size) + 1)
                for ty in range(math.floor(box[1] / self.size), math.floor(box[3] / self.size) + 1)]

    def features(self, tileset, box=None):
        """All features of a tileset (or of the tiles touching a metric box), de-duplicated by feature_id."""
        tiles = self.doc['tilesets'][tileset]['tiles']
        keys = tiles if box is None else [k for k in self.tile_keys(box) if k in tiles]
        seen, out = set(), []
        for k in keys:
            for f in json.load(open(os.path.join(LAYERS, 'tiles', tileset, f'{k}.json'), encoding='utf-8'))['features']:
                if f['properties']['feature_id'] not in seen:
                    seen.add(f['properties']['feature_id']); out.append(f)
        return out

    def dataset_features(self, did, box=None):
        d = self.datasets[did]
        flt = d.get('filter') or {}
        return [f for f in self.features(d['tileset'], box) if all(f['properties'].get(k) in v for k, v in flt.items())]


def _pt_seg(p, a, b):
    ux, uy = b[0] - a[0], b[1] - a[1]; l2 = ux * ux + uy * uy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / l2)) if l2 else 0.0
    return math.hypot(p[0] - a[0] - t * ux, p[1] - a[1] - t * uy)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _seg_seg(a, b, c, d):
    if _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0:
        return 0.0
    return min(_pt_seg(a, c, d), _pt_seg(b, c, d), _pt_seg(c, a, b), _pt_seg(d, a, b))


def _in_ring(p, ring):
    yes = False; j = len(ring) - 1
    for i in range(len(ring)):
        a, b = ring[i], ring[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            yes = not yes
        j = i
    return yes


def distance_to_line(cat, geom, coords):
    """Metres between a lon/lat geometry and a lon/lat polyline (0 when touching / inside a polygon)."""
    line = [cat.xy(c) for c in coords]
    t, c = geom['type'], geom['coordinates']
    if t in ('Polygon', 'MultiPolygon'):
        polys = [c] if t == 'Polygon' else c
        polys = [[[cat.xy(p) for p in r] for r in poly] for poly in polys]
        if any(_in_ring(p, rings[0]) and not any(_in_ring(p, h) for h in rings[1:]) for p in line for rings in polys):
            return 0.0
        rings = [r for poly in polys for r in poly]
        return min(_seg_seg(r[i - 1], r[i], line[k - 1], line[k]) for r in rings for i in range(1, len(r)) for k in range(1, len(line)))
    if t in ('LineString', 'MultiLineString'):
        lines = [c] if t == 'LineString' else c
        return min(_seg_seg(cat.xy(l[i - 1]), cat.xy(l[i]), line[k - 1], line[k]) for l in lines for i in range(1, len(l)) for k in range(1, len(line)))
    pts = [c] if t == 'Point' else c
    return min(_pt_seg(cat.xy(p), line[k - 1], line[k]) for p in pts for k in range(1, len(line)))


def along_route(cat, did, coords, distance):
    """{feature_id: distance} for every record of a dataset within `distance` m of the polyline (all tiles scanned)."""
    return {f['properties']['feature_id']: round(d, 3) for f in cat.dataset_features(did)
            if (d := distance_to_line(cat, f['geometry'], coords)) <= distance}
