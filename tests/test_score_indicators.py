"""data/pedestrian/score-indicators.json must be the router's real indicator definitions, never a stale or edited copy.
Run: python3 -m unittest tests.test_score_indicators
"""
import gzip, importlib.util, json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('build_score_indicators', ROOT / 'scripts' / 'build_score_indicators.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
from routing.engine import DIMENSIONS  # noqa: E402

DOC = json.loads((ROOT / 'data' / 'pedestrian' / 'score-indicators.json').read_text())


class ScoreIndicators(unittest.TestCase):
    def test_file_equals_a_fresh_build(self):
        self.assertEqual(DOC, mod.build(), 'rerun scripts/build_score_indicators.py')

    def test_same_version_as_the_router_scores(self):
        edge = json.load(gzip.open(ROOT / 'data' / 'pedestrian' / 'edge-scores.json.gz'))['metadata']
        self.assertEqual(DOC['score_version'], edge['score_version'])
        self.assertEqual(DOC['data_version'], edge['data_version'])

    def test_the_12_dimensions_keep_their_names_and_order(self):
        self.assertEqual(list(DOC['dimensions']), list(DIMENSIONS))

    def test_every_dimension_has_a_scored_indicator_with_a_known_source(self):
        for name, inds in DOC['dimensions'].items():
            scored = [x for x in inds if x['role'] in ('up', 'down')]
            self.assertTrue(scored, name)
            for x in inds:
                self.assertIn(x['source'], DOC['source_labels'], f"{name}: {x['key']}")
                self.assertTrue(x['label'] and x['method'])


if __name__ == '__main__':
    unittest.main()
