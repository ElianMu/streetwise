"""Navigate Urban Data Layers: spatial queries over the real layer datasets in data/layers (standard library only).

Two scopes: Current View (bounding box) and Along Route (features within a display distance of a planned route's
real geometry). Display distance only filters what is drawn; it never touches experience scores.
"""
import gzip, json, math, os, threading

from routing.engine import xy, ROOT

LAYERS = os.path.join(ROOT, 'data', 'layers')
CELL = 250.0  # metres per spatial-index cell
VIEW_CAP = 6000  # features per Current View response; above this the client is asked to zoom in
ROUTE_CAP = 12000
MAX_DISPLAY_M = 1500


class LayerError(ValueError):
    pass


def _parts(geom):
    """Metric vertex lists: points -> [[p]], lines -> [line], polygons -> [ring, ...] (outer rings only matter for distance)."""
    t, c = geom['type'], geom['coordinates']
    if t == 'Point':
        return [[xy(*c)]], 'point'
    if t == 'LineString':
        return [[xy(*p) for p in c]], 'line'
    if t == 'MultiLineString':
        return [[xy(*p) for p in l] for l in c], 'line'
    if t == 'Polygon':
        return [[xy(*p) for p in r] for r in c], 'polygon'
    if t == 'MultiPolygon':
        return [[xy(*p) for p in r] for poly in c for r in poly], 'polygon'
    return [], None


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


class Layer:
    def __init__(self, lid, meta):
        data = json.load(gzip.open(os.path.join(LAYERS, f'{lid}.geojson.gz'), 'rt', encoding='utf-8'))
        self.meta, self.features = meta, data['features']
        self.parts, self.kind, self.boxes, self.grid = [], None, [], {}
        for i, f in enumerate(self.features):
            parts, kind = _parts(f['geometry'])
            self.kind = self.kind or kind
            xs = [p[0] for part in parts for p in part]; ys = [p[1] for part in parts for p in part]
            box = (min(xs), min(ys), max(xs), max(ys))
            self.parts.append(parts); self.boxes.append(box)
            for gx in range(int(box[0] // CELL), int(box[2] // CELL) + 1):
                for gy in range(int(box[1] // CELL), int(box[3] // CELL) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)

    def candidates(self, box):
        seen = set()
        for gx in range(int(box[0] // CELL), int(box[2] // CELL) + 1):
            for gy in range(int(box[1] // CELL), int(box[3] // CELL) + 1):
                for i in self.grid.get((gx, gy), ()):
                    if i not in seen:
                        seen.add(i)
                        b = self.boxes[i]
                        if b[0] <= box[2] and b[2] >= box[0] and b[1] <= box[3] and b[3] >= box[1]:
                            yield i

    def distance_to(self, i, route):
        """Metres between feature i and a metric polyline (0 when a route vertex lies inside a polygon)."""
        parts, best = self.parts[i], math.inf
        if self.kind == 'polygon' and parts and any(_in_ring(p, parts[0]) for p in route[::max(1, len(route) // 50)]):
            return 0.0
        for part in parts:
            if len(part) == 1:
                for a, b in zip(route, route[1:]):
                    best = min(best, _pt_seg(part[0], a, b))
            else:
                for c, d in zip(part, part[1:]):
                    for a, b in zip(route, route[1:]):
                        best = min(best, _seg_seg(c, d, a, b))
                        if best == 0:
                            return 0.0
        return best


class LayerStore:
    def __init__(self):
        self.registry = json.load(open(os.path.join(LAYERS, 'registry.json'), encoding='utf-8'))
        self.loaded, self.lock = {}, threading.Lock()

    def layer(self, lid):
        meta = self.registry['layers'].get(lid)
        if not meta:
            raise LayerError(f'Unknown layer "{lid}"')
        if meta['status'] != 'available':
            raise LayerError(f"{meta['name']} is unavailable: {meta['reason']}")
        with self.lock:
            if lid not in self.loaded:
                self.loaded[lid] = Layer(lid, meta)
            return self.loaded[lid]

    def in_view(self, lid, bbox):
        w, s, e, n = bbox
        if not (w < e and s < n):
            raise LayerError('bbox must be west,south,east,north')
        L = self.layer(lid)
        (x0, y0), (x1, y1) = xy(w, s), xy(e, n)
        ids = list(L.candidates((x0, y0, x1, y1)))
        base = {'layer_id': lid, 'scope': 'current_view', 'count': len(ids), 'bbox': bbox}
        if len(ids) > VIEW_CAP:  # never send a silently truncated subset
            return {**base, 'too_many': True, 'features': [], 'message': f'{len(ids):,} features in view; zoom in to display them.'}
        return {**base, 'too_many': False, 'features': [L.features[i] for i in ids]}

    def along_route(self, lid, coords, distance=None):
        L = self.layer(lid)
        d = float(L.meta['display_distance_m'] if distance is None else distance)
        if not 0 < d <= MAX_DISPLAY_M:
            raise LayerError(f'distance must be 1–{MAX_DISPLAY_M} m')
        route = [xy(*c) for c in coords]
        xs = [p[0] for p in route]; ys = [p[1] for p in route]
        out = []
        for i in L.candidates((min(xs) - d, min(ys) - d, max(xs) + d, max(ys) + d)):
            dist = L.distance_to(i, route)
            if dist <= d:
                f = L.features[i]
                out.append({**f, 'properties': {**f['properties'], 'distance_to_route_m': round(dist, 1)}})
        base = {'layer_id': lid, 'scope': 'along_route', 'display_distance_m': d, 'scoring_distance_m': L.meta.get('scoring_distance_m'), 'count': len(out)}
        if len(out) > ROUTE_CAP:
            return {**base, 'too_many': True, 'features': [], 'message': f'{len(out):,} features along this route; reduce the display distance.'}
        return {**base, 'too_many': False, 'features': out}


_store = None


def reset_store():
    global _store
    _store = None


def get_store():
    global _store
    if _store is None:
        _store = LayerStore()
    return _store
