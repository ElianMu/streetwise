"""Provider wire contract tests. No real OpenAI traffic."""
import copy, json, pathlib, sys, unittest
from unittest import mock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from interpretation_contract import WIRE_SCHEMA, JOURNEY, normalize_wire, validate, DIMENSIONS
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
    def test_known_food_plurals_use_menu_identity_without_erasing_modifiers(self):
        r=server.validate_interpretation({'journey':{'food':[{'category':'restaurants','item':'bagels','required':True},{'category':'cafes','item':'vegan cappuccino','required':True}]}})
        self.assertEqual(r['journey']['food'][0]['item'],'bagel')
        self.assertEqual(r['journey']['food'][1]['item'],'vegan cappuccino')
    def test_prompt_example_does_not_create_a_hotel_for_preference_only_requests(self):
        for text in ['I want bagels and cappuccino along the route.','Actually, avoid the waterfront and walk away from the river.']:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Hotel bindings require'):
                server.validate_intent_bindings({'journey':{'origin':'hotel','end_mode':'hotel'}},text)
        server.validate_intent_bindings({'journey':{'origin':'hotel','end_mode':'hotel'}},'Start from my hotel and return there.')
        example=server.count_contract_example()['journey']
        self.assertIsNone(example['origin']);self.assertIsNone(example['end_mode'])

    def test_numbered_placeholder_visits_are_not_named_places(self):
        with self.assertRaisesRegex(ValueError, 'Generic numbered'):
            server.validate_intent_bindings({'journey':{'named_stops':[{'name':'landmark 1'}]}},'Visit two landmarks')

    def test_explicit_total_is_not_incremental_more(self):
        for journey in [{'interests':['famous'],'more':{'famous':2}}, {'interests':['famous'],'counts':{'famous':1}}]:
            with self.assertRaisesRegex(ValueError, 'Explicit total'):
                server.validate_intent_bindings({'journey':journey},'Start from my hotel, visit two landmarks and return to my hotel.')
        server.validate_intent_bindings({'journey':{'interests':['famous'],'counts':{'famous':2}}},'Visit two landmarks')
        server.validate_intent_bindings({'journey':{'interests':['historic'],'counts':{'historic':2}}},'Visit two landmarks')

    def test_counts_must_name_requested_interests(self):
        with self.assertRaisesRegex(ValueError, 'belong to interests'):
            server.validate_intent_bindings({'journey':{'interests':['parks'],'counts':{'famous':2}}},'A walk')

    def test_walking_minutes_cannot_become_a_monetary_budget(self):
        r={'journey':{'requirements':{'restaurant_budget_usd':100}}}
        with self.assertRaisesRegex(ValueError, 'walking minutes'):
            server.validate_intent_bindings(r,'Tiramisu within my walking budget')
        server.validate_intent_bindings(r,'Tiramisu with a $100 budget')
        server.validate_intent_bindings(r,'Tiramisu', [{'role':'user','content':'Restaurant budget is 100 dollars'}])

    def test_search_area_is_not_an_origin_change(self):
        r={'journey':{'origin':'Central Park','requirements':{'search_anchor':'Central Park'}}}
        with self.assertRaisesRegex(ValueError, 'Search proximity'):
            server.validate_intent_bindings(r,'Find a cafe near Central Park')
        server.validate_intent_bindings(r,'Start from Central Park and find a cafe nearby')

    def test_semantic_failure_asks_model_to_repair_without_fake_place(self):
        good=self.fixture();good['journey']=empty(JOURNEY)
        good['journey'].update(interests=['famous'],origin='hotel',end_mode='hotel')
        good['journey']['counts']=empty(JOURNEY['properties']['counts']['anyOf'][0])
        good['journey']['counts']['famous']=2
        bad=copy.deepcopy(good);bad['journey']['named_stops']=[{'name':'landmark 1','required':True,'order':1}]
        with mock.patch.object(server,'KEY','unit-test-only-key'),mock.patch.object(server,'call_llm',side_effect=[bad,good]) as llm:
            code,result=server.interpret({'message':'Start from my hotel, visit two landmarks and return to my hotel.'})
        self.assertEqual(code,200);self.assertEqual(llm.call_count,2)
        self.assertEqual(result['journey']['counts'],{'famous':2});self.assertEqual(result['journey']['named_stops'],[])

    def test_good_bakery_requires_review_evidence(self):
        with self.assertRaisesRegex(ValueError,'ratings_required'):
            server.validate_intent_bindings({'journey':{'food':[{'category':'bakeries'}]}},'Plan a walk with a good bakery')
        server.validate_intent_bindings({'journey':{'requirements':{'ratings_required':True}}},'Plan a walk with a good bakery')

    def test_count_prompt_example_is_valid_wire_and_not_a_fallback(self):
        sample=server.count_contract_example()
        r=server.validate_interpretation(normalize_wire(sample))
        self.assertEqual(r['journey']['counts'],{'famous':2})
        self.assertEqual(r['journey']['more'],{});self.assertEqual(r['journey']['named_stops'],[])
        with mock.patch.object(server,'KEY','unit-test-only-key'),mock.patch.object(server,'call_llm',side_effect=server.LLMFailure('upstream_unreachable')):
            code,result=server.interpret({'message':'Visit two landmarks'})
        self.assertEqual(code,502);self.assertNotIn('journey',result)

    def test_independent_crime_and_waterfront_keep_core_dimensions_unchanged(self):
        d=self.fixture();d['crime']={'mode':'set','direction':'high','weight':90,'from':None,'to':None,'offense_types':['ROBBERY']}
        d['waterfront']={'mode':'set','direction':'low','weight':90}
        result=server.validate_interpretation(normalize_wire(d))
        self.assertEqual(result['crime']['direction'],'high');self.assertEqual(result['waterfront']['direction'],'low')
        self.assertEqual(result['weights'],{'Nature':90});self.assertNotIn('Crime',server.DIMENSIONS)
        # Public response remains revalidatable, with names preserved rather than model-invented offense codes.
        self.assertEqual(server.validate_interpretation(result)['crime'],result['crime'])

    def test_explicit_high_crime_request_is_never_reversed_to_avoidance(self):
        text='I want a route with very high crime rate.'
        with self.assertRaises(ValueError):server.validate_intent_bindings({'crime':{'direction':'low'}},text)
        with self.assertRaises(ValueError):server.validate_intent_bindings({'clarification':'Did you mean to avoid crime instead?'},text)
        server.validate_intent_bindings({'crime':{'direction':'high'}},text)

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
