"""Checks of benchmarks/route_benchmark.py on the real engine and data (no mocks).

These test that the benchmark measures and reports correctly. They deliberately do NOT assert that a preference route
beats the shortest route: that is the benchmark's finding, whatever it turns out to be.
Run: python3 -m unittest tests.test_route_benchmark
"""
import importlib.util, json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('route_benchmark', ROOT / 'benchmarks' / 'route_benchmark.py')
rb = importlib.util.module_from_spec(spec); spec.loader.exec_module(rb)
from routing.engine import DIMENSIONS  # noqa: E402

PAIRS = json.loads((ROOT / 'benchmarks' / 'od_pairs.json').read_text())['pairs']
SUBSET = [p for p in PAIRS if p['id'] in ('bryant-rockefeller', 'met-lincoln', 'washington-seaport')]
DIMS = ['Nature', 'Quiet & Relax']


class RouteBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = rb.run(SUBSET, DIMS)

    def test_trip_set_is_valid(self):
        self.assertEqual(len({p['id'] for p in PAIRS}), len(PAIRS), 'trip ids are unique')
        for p in PAIRS:
            for lon, lat in (p['o'], p['d']):
                self.assertTrue(-74.05 < lon < -73.90 and 40.69 < lat < 40.89, f"{p['id']} lies in Manhattan's bounding box")

    def test_presets_use_existing_dimensions(self):
        for dim in rb.PRESETS.values():
            self.assertIn(dim, DIMENSIONS)

    def test_every_run_reports_the_three_routes(self):
        self.assertEqual(len(self.result['runs']), len(SUBSET) * len(DIMS))
        for r in self.result['runs']:
            self.assertNotIn('error', r)
            self.assertEqual(r['shortest']['objective'], 'shortest')
            self.assertEqual(r['shortest']['detour_pct'], 0)
            self.assertEqual(r['shortest']['overlap_with_shortest'], 1)
            self.assertIsNotNone(r['preference'], 'a feasible route exists for these trips')
            self.assertLessEqual(r['preference']['detour_pct'], rb.CONSTRAINTS['max_detour_pct'] + 1e-6)
            self.assertEqual(r['preference']['blocking_issues'], 0)

    def test_gain_is_the_plain_difference_of_engine_scores(self):
        for r in self.result['runs']:
            self.assertEqual(r['gain_points'], round(r['preference']['score'] - r['shortest']['score'], 1))
            if r['same_as_shortest']:
                self.assertEqual(r['gain_points'], 0)
                self.assertEqual(r['preference']['route_signature'], r['shortest']['route_signature'])

    def test_repeatable(self):
        self.assertEqual(rb.run(SUBSET, DIMS)['runs'], self.result['runs'])

    def test_summary_counts_add_up(self):
        s = rb.summary(self.result)
        self.assertEqual(s['all']['runs'], len(self.result['runs']))
        self.assertEqual(sum(x['runs'] for x in s['by_dimension'].values()), s['all']['runs'])
        self.assertEqual(sum(x['runs'] for x in s['by_length'].values()), s['all']['runs'])
        self.assertLessEqual(s['all']['gain_at_least_claim'], s['all']['scored'])

    def test_priority_pills_follow_the_committed_benchmark_order(self):
        """walk-presets.js: three dimensions featured for the lead audience, then the other nine by mean gain in
        benchmarks/route_benchmark.json, strongest first."""
        import re
        src = (ROOT / 'walk-presets.js').read_text()
        names = lambda block: re.findall(r"'([^']+)'", block)
        featured = names(re.search(r'WALK_FEATURED = \[(.*?)\];', src, re.S).group(1))
        rest = names(re.search(r'WALK_PRESET_ORDER = \[\.\.\.WALK_FEATURED,(.*?)\];', src, re.S).group(1))
        self.assertEqual(featured, ['Nature', 'Quiet & Relax', 'Architecture'])
        self.assertEqual(sorted(featured + rest), sorted(DIMENSIONS), 'exactly the 12 registered dimensions, each once')
        by_dim = json.loads((ROOT / 'benchmarks' / 'route_benchmark.json').read_text())['summary']['by_dimension']
        self.assertEqual(rest, sorted((d for d in DIMENSIONS if d not in featured), key=lambda d: -by_dim[d]['mean_gain']),
                         'rerun the benchmark or reorder the pills')
        for block in re.findall(r"dims: \[(.*?)\]", src):
            self.assertTrue(set(names(block)) <= set(DIMENSIONS), 'an activity may only bundle registered dimensions')

    def test_summary_survives_unscored_runs(self):
        self.assertEqual(rb.summarise([{'dimension': 'Nature', 'error': 'x'}]), {'runs': 1, 'scored': 0})


if __name__ == '__main__':
    unittest.main()
