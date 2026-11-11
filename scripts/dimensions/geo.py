"""Vectorised spatial primitives for the dimension pipeline. All inputs are in a metric CRS (EPSG:32618, metres)."""
import numpy as np
import shapely
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra, connected_components


def sample_along(lines, step, with_normals=False):
    """Points every ~`step` m along each line: n = max(1, round(L/step)) points at (k + .5)·L/n.
    Returns (seg_index, xy[, normals]) — at least one point (the midpoint) per line."""
    lines = np.asarray(lines, dtype=object)
    L = shapely.length(lines)
    n = np.maximum(1, np.round(L / step)).astype(int)
    seg = np.repeat(np.arange(len(lines)), n)
    k = np.concatenate([np.arange(m) for m in n]) if len(n) else np.array([], int)
    d = (k + 0.5) * (L[seg] / n[seg])
    pts = shapely.line_interpolate_point(lines[seg], d)
    xy = shapely.get_coordinates(pts)
    if not with_normals:
        return seg, xy
    eps = np.minimum(0.5, L[seg] / 4 + 1e-9)
    a = shapely.get_coordinates(shapely.line_interpolate_point(lines[seg], np.maximum(d - eps, 0)))
    b = shapely.get_coordinates(shapely.line_interpolate_point(lines[seg], np.minimum(d + eps, L[seg])))
    t = b - a
    norm = np.hypot(t[:, 0], t[:, 1])
    norm[norm == 0] = 1
    normals = np.column_stack([-t[:, 1] / norm, t[:, 0] / norm])
    return seg, xy, normals


def midpoints(lines):
    lines = np.asarray(lines, dtype=object)
    return shapely.get_coordinates(shapely.line_interpolate_point(lines, 0.5, normalized=True))


def gaussian_kernel(sample_seg, sample_xy, n_seg, src_xy, sigma, cutoff, chunk=20000):
    """Per segment: mean over its samples of Σ exp(−d²/2σ²) over source points with d ≤ cutoff."""
    per_sample = np.zeros(len(sample_xy))
    if len(src_xy):
        src = cKDTree(src_xy)
        for s in range(0, len(sample_xy), chunk):
            t = cKDTree(sample_xy[s:s + chunk])
            m = t.sparse_distance_matrix(src, cutoff, output_type='coo_matrix')
            # sparse_distance_matrix drops exact-zero distances; add points sitting exactly on a sample.
            w = np.exp(-(m.data ** 2) / (2 * sigma * sigma))
            per_sample[s:s + chunk] += np.bincount(m.row, weights=w, minlength=t.n)
            zero = t.query_ball_tree(src, 1e-9)
            per_sample[s:s + chunk] += np.array([len(z) for z in zero]) - np.bincount(m.row[m.data == 0], minlength=t.n)
    return np.bincount(sample_seg, weights=per_sample, minlength=n_seg) / np.maximum(np.bincount(sample_seg, minlength=n_seg), 1)


def gaussian_kernel_polygons(sample_seg, sample_xy, n_seg, polys, sigma, cutoff):
    """Like gaussian_kernel, but distance is to each polygon (0 inside); each polygon counted once per sample."""
    per_sample = np.zeros(len(sample_xy))
    if len(polys):
        tree = shapely.STRtree(polys)
        pts = shapely.points(sample_xy)
        pi, gi = tree.query(pts, predicate='dwithin', distance=cutoff)
        d = shapely.distance(pts[pi], np.asarray(polys, dtype=object)[gi])
        w = np.exp(-(d ** 2) / (2 * sigma * sigma))
        per_sample = np.bincount(pi, weights=w, minlength=len(sample_xy))
    return np.bincount(sample_seg, weights=per_sample, minlength=n_seg) / np.maximum(np.bincount(sample_seg, minlength=n_seg), 1)


def share_inside(lines, polys, step, offsets):
    """Share of sample points (every `step` m, at perpendicular `offsets`) that fall inside any polygon."""
    seg, xy, nrm = sample_along(lines, step, with_normals=True)
    offs = np.asarray(offsets, float)
    P = (xy[:, None, :] + nrm[:, None, :] * offs[None, :, None]).reshape(-1, 2)
    S = np.repeat(seg, len(offs))
    hit = np.zeros(len(P), bool)
    if len(polys):
        tree = shapely.STRtree(polys)
        pi, _ = tree.query(shapely.points(P), predicate='intersects')
        hit[np.unique(pi)] = True
    n = len(lines)
    return np.bincount(S, weights=hit, minlength=n) / np.maximum(np.bincount(S, minlength=n), 1)


def count_within(points_xy, src_xy, radius):
    if not len(src_xy):
        return np.zeros(len(points_xy), int)
    return np.array([len(x) for x in cKDTree(src_xy).query_ball_point(points_xy, radius)])


def nearest_distance(points_xy, src_xy, cap):
    if not len(src_xy):
        return np.full(len(points_xy), float(cap))
    d, _ = cKDTree(src_xy).query(points_xy, distance_upper_bound=cap)
    return np.minimum(d, cap)


def nearest_line_distance(points_xy, lines, cap):
    if not len(lines):
        return np.full(len(points_xy), float(cap))
    tree = shapely.STRtree(lines)
    pts = shapely.points(points_xy)
    (pi, gi), d = tree.query_nearest(pts, max_distance=cap, return_distance=True, all_matches=False)
    out = np.full(len(points_xy), float(cap))
    out[pi] = np.minimum(d, cap)
    return out


def snap_count_per_line(lines, src_xy, radius, min_length):
    """Each source point is assigned to its single nearest line within `radius` (no double counting at corners);
    returns (count, count / max(L, min_length) in km)."""
    n = len(lines)
    cnt = np.zeros(n, int)
    if len(src_xy):
        tree = shapely.STRtree(lines)
        (pi, gi) = tree.query_nearest(shapely.points(src_xy), max_distance=radius, all_matches=False)
        cnt = np.bincount(gi, minlength=n)
    km = np.maximum(shapely.length(np.asarray(lines, dtype=object)), min_length) / 1000
    return cnt, cnt / km


# --- network -------------------------------------------------------------------------------------------------
class Graph:
    """Undirected weighted graph (metres) on node coordinates, restricted to its largest connected component."""

    def __init__(self, node_xy, u, v, w):
        n = len(node_xy)
        w = np.maximum(np.asarray(w, float), 1e-3)  # csgraph treats 0 as "no edge"
        # keep the minimum weight among parallel edges (a sparse constructor would sum them)
        import pandas as pd
        df = pd.DataFrame({'a': np.r_[u, v], 'b': np.r_[v, u], 'w': np.r_[w, w]}).groupby(['a', 'b'], sort=False)['w'].min().reset_index()
        A = coo_matrix((df.w.values, (df.a.values, df.b.values)), shape=(n, n)).tocsr()
        _, lab = connected_components(A, directed=False)
        big = np.bincount(lab).argmax()
        self.keep = np.flatnonzero(lab == big)
        self.n_dropped = n - len(self.keep)
        idx = -np.ones(n, int)
        idx[self.keep] = np.arange(len(self.keep))
        self.A = A[self.keep][:, self.keep].tocsr()
        self.xy = np.asarray(node_xy)[self.keep]
        self.remap = idx
        self.kd = cKDTree(self.xy)

    def snap(self, points_xy):
        d, i = self.kd.query(points_xy)
        return i, d

    def multi_source(self, src_nodes, src_cost, limit):
        """Distance from the nearest source to every node (sources have an initial cost), via a virtual super-source."""
        import pandas as pd
        n = self.A.shape[0]
        s = pd.DataFrame({'n': src_nodes, 'c': src_cost}).groupby('n')['c'].min()
        A = self.A.tocoo()
        rows = np.r_[A.row, np.full(len(s), n)]
        cols = np.r_[A.col, s.index.values]
        eps = 1e-3  # csgraph drops 0-weight entries: every source edge gets +eps, removed again below
        vals = np.r_[A.data, s.values + eps]
        G = coo_matrix((vals, (rows, cols)), shape=(n + 1, n + 1)).tocsr()
        d = dijkstra(G, directed=True, indices=n, limit=limit + eps)
        return d[:n] - eps

    def from_many(self, origins, limit, batch=200):
        """Yield (batch origin indices, distance rows) for single-source shortest paths from each origin."""
        for s in range(0, len(origins), batch):
            o = origins[s:s + batch]
            yield s, dijkstra(self.A, directed=False, indices=o, limit=limit)
