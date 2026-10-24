"""Provider wire contract tests. No real OpenAI traffic."""
import copy, json, pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from interpretation_contract import WIRE_SCHEMA, normalize_wire, validate, DIMENSIONS
import server


def empty(schema):
    if 'anyOf' in schema:
        return None
    return ({k: empty(v) for k, v in schema['properties'].items()} if schema['type'] == 'object'
            else [] if schema['type'] == 'array' else None)


class ContractTests(unittest.TestCase):
    def fixture(self):
        doc = empty(WIRE_SCHEMA)
        doc['preferences'] = [{'dimension': 'Nature', 'weight': 90, 'direction': 'high'}]
        return doc

    def test_all_objects_are_closed_and_all_wire_keys_required(self):
        def walk(s):
            if s.get('type') == 'object':
                self.assertFalse(s['additionalProperties'])
                self.assertEqual(set(s['properties']), set(s['required']))
                for v in s['properties'].values(): walk(v)
            for v in s.get('anyOf', []): walk(v)
            if 'items' in s: walk(s['items'])
        walk(WIRE_SCHEMA)
        self.assertEqual(list(DIMENSIONS), server.DIMENSIONS)

    def test_normalization_preserves_zero_and_direction(self):
        d = self.fixture()
        d['preferences'] += [{'dimension': 'Urban Vibrancy', 'weight': 0, 'direction': 'low'}]
        result = server.validate_interpretation(normalize_wire(d))
        self.assertEqual(result['weights']['Urban Vibrancy'], 0)
        self.assertEqual(result['directions']['Urban Vibrancy'], 'low')
        self.assertEqual(result['constraints'], {})

    def test_invalid_shapes_are_rejected_without_repair(self):
        mutations = [lambda d: d['preferences'][0].update(dimension='Trees'),
                     lambda d: d['preferences'][0].pop('weight'),
                     lambda d: d['preferences'][0].update(weight=True),
                     lambda d: d['preferences'][0].update(weight=101),
                     lambda d: d.update(unknown=1),
                     lambda d: d['preferences'].append(copy.deepcopy(d['preferences'][0])),
                     lambda d: d.update(weights={'Nature': 90}),
                     lambda d: d.update(preferences={'Nature': 90})]
        for mutation in mutations:
            d = self.fixture(); mutation(d)
            with self.subTest(doc=d), self.assertRaises(ValueError): normalize_wire(d)

    def test_nested_journey_is_not_silently_coerced(self):
        for j in [{'food': 'coffee'}, {'food': [{'category': 'imaginary'}]},
                  {'interests': ['unknown']}, {'hotel': {'name': 'Hotel', 'latitude': 1}},
                  {'walking_minutes': -2}]:
            with self.subTest(journey=j), self.assertRaises(ValueError):
                server.validate_interpretation({'journey': j})

    def test_public_optional_fields_remain_optional(self):
        r = server.validate_interpretation({'weights': {'Nature': 90}})
        self.assertEqual(r['directions'], {'Nature': 'high'})
        self.assertIsNone(r['journey'])

    def test_scoring_really_changes_on_same_real_route(self):
        from routing.engine import get_planner, preference_weights
        p = get_planner()
        a, b = {'lon': -73.9832, 'lat': 40.7536}, {'lon': -73.9787, 'lat': 40.7587}
        base = p.plan(a, b, {}, {'max_minutes': 30})['routes'][0]
        scores = []
        for direction in ['high', 'low']:
            route = copy.deepcopy(base)
            prefs = normalize_wire({**self.fixture(), 'preferences': [
                {'dimension': 'Nature', 'weight': 90, 'direction': direction}]})
            weights, expressed = preference_weights(prefs)
            p.personalize(route, weights, expressed)
            self.assertEqual(route['personalized_score']['components']['Nature']['direction'], direction)
            scores.append(route['personalized_score']['utility'])
        self.assertNotEqual(*scores)

if __name__ == '__main__': unittest.main()
