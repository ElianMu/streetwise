"""The router's edge scores are the Explore map's street scores (scripts/transfer_dimension_scores.py).

Run: python3 -m unittest tests.test_transfer_scores
"""
import gzip
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import transfer_dimension_scores as T  # noqa: E402

MANIFEST = json.loads((ROOT / 'data' / 'dimensions' / 'manhattan' / 'manifest.json').read_text())
IND = json.loads((ROOT / 'data' / 'dimensions' / 'manhattan' / 'indicators.json').read_text())
EDGES = json.load(gzip.open(ROOT / 'data' / 'pedestrian' / 'edge-scores.json.gz', 'rt', encoding='utf-8'))
ROLE = {i['key']: i['role'] for i in MANIFEST['indicators']}
COMPUTED = [[(k, ROLE[k]) for k in d['available_indicators'] if ROLE[k] in ('up', 'down')] for d in MANIFEST['dimensions']]
REFERENCE = {k: sorted(v for v in IND['raw'][k] if v is not None) for inds in COMPUTED for k, _ in inds}
NEW_ONLY = {'seat_access_m', 'ramp_coverage', 'waterfront_access_m', 'route_directness', 'crime_k'}
EXTRA = json.load(gzip.open(ROOT / 'data' / 'pedestrian' / 'direct-edge-indicators.json.gz', 'rt', encoding='utf-8'))  # scripts/measure_direct_edges.py


class TransferredScores(unittest.TestCase):
    def test_direct_edges_use_only_what_was_measured_on_them(self):
        direct = [g for g in EDGES['geoms'] if g['src'] == 'direct_osm']
        self.assertTrue(direct)
        for g in direct[::40]:
            self.assertLessEqual(NEW_ONLY & set(g['raw']), set(EXTRA['values']), 'no value may appear for an indicator that was never measured on this edge')
            dims, used = T.direct_scores(g['raw'], COMPUTED, REFERENCE)
            self.assertEqual(dims, g['s'])
            for j, inds in enumerate(COMPUTED):
                measured = [k for k, _ in inds if g['raw'].get(k) is not None]
                self.assertEqual(used[j], len(measured))
                self.assertEqual(g['s'][j] is None, not measured, 'no measured indicator means N/A, never 0')

    def test_percentile_rule_matches_the_map_build(self):
        """A street's own raw value, ranked by the transfer, gives the percentile the map build stored for it."""
        for key, role in (('tree_km', 'up'), ('noise_k', 'down'), ('sub_m', 'down')):
            pct = IND['pct'][key] if 'pct' in IND else None
            if pct is None:
                self.skipTest('indicators.json has no stored percentiles')
            for i in range(0, len(IND['ids']), 500):
                v = IND['raw'][key][i]
                if v is None:
                    continue
                dims, _ = T.direct_scores({key: v}, [[(key, role)]], REFERENCE)
                self.assertAlmostEqual(dims[0], pct[i], delta=0.51, msg=f'{key} segment {IND["ids"][i]}')

    def test_unit_conversion_is_only_for_the_two_share_indicators(self):
        self.assertEqual(T.DIRECT_UNIT, {'park_pct': 0.01, 'sidewalk_pct': 0.01})
        for key in T.DIRECT_UNIT:  # the map build stores them as 0–1 shares, the direct measurements as 0–100 %
            self.assertLessEqual(REFERENCE[key][-1], 1.0)
            self.assertGreater(max(g['raw'][key] for g in EDGES['geoms'] if g['src'] == 'direct_osm' and g['raw'].get(key) is not None), 1.0)

    def test_metadata_reports_the_indicator_basis(self):
        meta = EDGES['metadata']
        self.assertEqual(meta['score_version'], MANIFEST['calculation_version'])
        for d, inds in zip(MANIFEST['dimensions'], COMPUTED):
            basis = meta['indicator_basis'][d['key']]
            self.assertEqual(basis['computed_indicators'], [k for k, _ in inds])
        self.assertEqual(meta['direct_edge_indicators']['not_measured_on_direct_edges'], ['ramp_coverage'])
        self.assertGreater(meta['indicator_basis']['spatial_comfort']['routable_length_with_fewer'], 0, 'the limit must be reported, not hidden')

    def test_direct_edge_measurements_are_the_committed_ones(self):
        """Values measured on the edges themselves: same network, same map build, self-check passed, nothing invented."""
        self.assertEqual(EXTRA['network_version'], EDGES['metadata']['network_version'])
        self.assertEqual(EXTRA['map_build'], MANIFEST['calculation_version'])
        self.assertNotIn('ramp_coverage', EXTRA['values'])
        self.assertIn('ramp_coverage', EXTRA['not_measured'])
        for k, vals in EXTRA['values'].items():
            self.assertIn(k, NEW_ONLY)
            check = EXTRA['self_check_on_street_segments'][k]
            self.assertTrue(check['reproduced']); self.assertGreaterEqual(check['within_tolerance'], 0.99)
            self.assertEqual(len(vals), len(EXTRA['geometry_index']))
        for n in range(0, len(EXTRA['geometry_index']), 97):
            g = EDGES['geoms'][EXTRA['geometry_index'][n]]
            self.assertEqual(g['src'], 'direct_osm')
            for k, vals in EXTRA['values'].items():
                self.assertEqual(g['raw'].get(k), vals[n])


if __name__ == '__main__':
    unittest.main()
