"""Integrity of data/manhattan-streets.json: every segment carries an ID, name, length and 12 scores that follow
from its own sub-indicators. Run: python3 -m unittest tests.test_street_data"""
import json, unittest
from pathlib import Path

DATA = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'manhattan-streets.json').read_text())


class StreetDataTest(unittest.TestCase):
    def test_segments_have_identity_and_scores(self):
        props = [f['properties'] for f in DATA['features']]
        self.assertGreater(len(props), 10000)
        self.assertEqual(len({p['id'] for p in props}), len(props), 'segment IDs must be unique')
        for p in props:
            self.assertTrue(p['id'].startswith('MN-'))
            self.assertIsInstance(p['name'], str)
            self.assertGreater(p['length_m'], 0)
            for i in range(12):
                v = p[f'd{i}']
                self.assertTrue(v is None or 0 <= v <= 100)

    def test_overall_is_mean_of_available_dimensions(self):
        for f in DATA['features']:
            p = f['properties']
            have = [p[f'd{i}'] for i in range(12) if p[f'd{i}'] is not None]
            self.assertEqual(p['coverage'], len(have))
            self.assertEqual(p['overall'], round(sum(have) / len(have)) if have else None)

    def test_missing_sub_indicators_stay_missing(self):
        ind = DATA['metadata']['indicators']
        keys = DATA['metadata']['keys']
        self.assertEqual(len(keys), 12)
        for f in DATA['features']:
            p = f['properties']
            for i, k in enumerate(keys):
                scored = [x['key'] for x in ind[k] if x['role'] != 'context']
                if all(p[x] is None for x in scored):
                    self.assertIsNone(p[f'd{i}'], 'no measurable sub-indicator must give N/A, not a score')
        self.assertTrue(any(f['properties']['d4'] is None for f in DATA['features']))

    def test_every_indicator_documented(self):
        meta = DATA['metadata']
        for dim in meta['indicators'].values():
            for x in dim:
                self.assertTrue(x['label'] and x['unit'] and x['method'])
                self.assertIn(x['source'], meta['source_labels'])
                self.assertIn(x['key'], DATA['features'][0]['properties'])


if __name__ == '__main__':
    unittest.main()
