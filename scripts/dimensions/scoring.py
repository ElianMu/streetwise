"""Percentile normalisation and dimension aggregation (pure numpy; unit-tested in tests/test_dimensions.py)."""
import numpy as np

from . import spec


def percentile(values, invert=False):
    """0–100 percentile rank among the non-NaN values; ties take the lowest rank (rank = # strictly smaller ÷ (n−1)).
    invert → 100 − rank, so for "lower is better" indicators the lowest raw value scores 100. NaN stays NaN."""
    v = np.asarray(values, float)
    out = np.full(v.shape, np.nan)
    ok = np.isfinite(v)
    n = int(ok.sum())
    if n == 0:
        return out
    s = np.sort(v[ok])
    rank = np.searchsorted(s, v[ok], side='left') / max(n - 1, 1) * 100
    out[ok] = np.round(100 - rank if invert else rank, 1)
    return out


def normalise(raw):
    """raw: {key: array} → {key: percentile array} for every scored indicator present."""
    out = {}
    for key, vals in raw.items():
        ind = spec.BY_KEY[key]
        if ind['role'] in spec.SCORED_ROLES:
            out[key] = percentile(vals, invert=ind['role'] == 'down')
    return out


def aggregate(pct, n):
    """Per dimension: equal-weight mean of available indicator percentiles; also how many indicators contributed.
    Returns ({dim: score array (NaN = N/A)}, {dim: count array})."""
    scores, counts = {}, {}
    for dim in spec.DIM_KEYS:
        keys = [x['key'] for x in spec.indicators_of(dim, scored_only=True) if x['key'] in pct]
        if not keys:
            scores[dim], counts[dim] = np.full(n, np.nan), np.zeros(n, int)
            continue
        M = np.vstack([pct[k] for k in keys])
        c = np.isfinite(M).sum(0)
        with np.errstate(invalid='ignore'):
            s = np.nansum(M, 0) / np.where(c > 0, c, 1)
        s[c == 0] = np.nan
        scores[dim], counts[dim] = np.round(s, 1), c
    return scores, counts
