"""Agent Runtime tests: tool registry against real local data (no LLM, no mocks — these are the same functions
the deterministic pipeline already uses), and runtime control flow (step budget, deadline, retries) with the
LLM itself stubbed out, so these tests run in CI without an OPENAI_API_KEY and without real API cost.

A real end-to-end run with a real LLM is NOT exercised here — see benchmarks/agent_vs_deterministic.py, which
honestly reports itself blocked when OPENAI_API_KEY is absent rather than faking a result.
"""
import io
import json
import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools import search_places, calculate_route, validate_route, verify_restaurant_menu, get_weather
from agent import runtime as agent_runtime
from langchain_core.messages import AIMessage, HumanMessage


NEAR_TIMES_SQUARE = {'lat': 40.758, 'lon': -73.9855}


class ToolRegistryRealDataTests(unittest.TestCase):
    """Each tool wraps a real routing/* function; these assert against real local data, not fixtures."""

    def test_search_places_finds_real_restaurants(self):
        r = search_places.invoke({'lat': NEAR_TIMES_SQUARE['lat'], 'lon': NEAR_TIMES_SQUARE['lon'],
                                   'categories': 'restaurants', 'radius_m': 500, 'limit': 5})
        self.assertTrue(r['ok'])
        self.assertGreater(r['data']['count'], 0)
        self.assertIn('place_id', r['data']['results'][0])

    def test_search_places_rejects_outside_nyc(self):
        r = search_places.invoke({'lat': 34.0, 'lon': -118.2, 'categories': 'restaurants'})
        self.assertFalse(r['ok'])
        self.assertEqual(r['error']['type'], 'invalid_input')

    def test_calculate_route_returns_a_real_route(self):
        r = calculate_route.invoke({'origin_lat': 40.758, 'origin_lon': -73.9855,
                                     'dest_lat': 40.7620, 'dest_lon': -73.9790, 'max_minutes': 30})
        self.assertTrue(r['ok'])
        self.assertGreater(len(r['data']['routes']), 0)
        self.assertIn('distance_m', r['data']['routes'][0])

    def test_validate_route_flags_a_real_violation(self):
        r = validate_route.invoke({'route_minutes': 25.0, 'max_minutes': 20.0})
        self.assertTrue(r['ok'])
        self.assertFalse(r['data']['satisfies_constraints'])
        self.assertEqual(len(r['data']['violations']), 1)

    def test_validate_route_passes_when_within_limit(self):
        r = validate_route.invoke({'route_minutes': 10.0, 'max_minutes': 20.0})
        self.assertTrue(r['data']['satisfies_constraints'])

    def test_verify_restaurant_menu_against_a_real_place(self):
        found = search_places.invoke({'lat': NEAR_TIMES_SQUARE['lat'], 'lon': NEAR_TIMES_SQUARE['lon'],
                                       'categories': 'restaurants', 'radius_m': 500, 'limit': 1})
        place = found['data']['results'][0]
        r = verify_restaurant_menu.invoke({'place_id': place['place_id'], 'item': 'burger', 'name': place['name']})
        self.assertTrue(r['ok'])
        self.assertIn(r['data']['status'], ('confirmed_menu_match', 'probable_match_review', 'unverified',
                                             'not_found_in_checked_sources'))

    def test_get_weather_real_network_call(self):
        try:
            r = get_weather.invoke({'lat': NEAR_TIMES_SQUARE['lat'], 'lon': NEAR_TIMES_SQUARE['lon'], 'minutes': 30})
        except Exception as e:  # pragma: no cover - environment without outbound network
            self.skipTest(f'no network access in this environment: {e}')
        if not r['ok']:
            self.skipTest(f'Open-Meteo unavailable from this environment: {r["error"]}')
        self.assertIn('data_available', r['data'])


def _state(messages, step_count=0, deadline=None):
    return {'messages': messages, 'run_id': 'test-run', 'status': 'RUNNING', 'step_count': step_count,
            'trace': agent_runtime.tracing.new_trace('test-run'), 'deadline': deadline or time.time() + 30}


class AgentNodeControlFlowTests(unittest.TestCase):
    """The LLM itself is stubbed (no network, no API cost) — these test the Runtime's own bookkeeping."""

    def test_max_steps_exceeded_fails_without_calling_the_llm(self):
        state = _state([HumanMessage('find food')], step_count=agent_runtime.MAX_STEPS)
        with mock.patch.object(agent_runtime, '_llm') as llm:
            result = agent_runtime.agent_node(state)
        llm.assert_not_called()
        self.assertEqual(result['status'], 'FAILED')

    def test_deadline_exceeded_fails_without_calling_the_llm(self):
        state = _state([HumanMessage('find food')], deadline=time.time() - 1)
        with mock.patch.object(agent_runtime, '_llm') as llm:
            result = agent_runtime.agent_node(state)
        llm.assert_not_called()
        self.assertEqual(result['status'], 'FAILED')

    def test_no_tool_calls_completes(self):
        state = _state([HumanMessage('find food')])
        fake = mock.Mock()
        fake.invoke.return_value = AIMessage(content='Here is my recommendation.')
        with mock.patch.object(agent_runtime, '_llm', return_value=fake):
            result = agent_runtime.agent_node(state)
        self.assertEqual(result['status'], 'COMPLETED')

    def test_tool_calls_present_waits_for_tool(self):
        state = _state([HumanMessage('find food')])
        fake = mock.Mock()
        msg = AIMessage(content='', tool_calls=[{'name': 'search_places', 'args': {'lat': 40.758, 'lon': -73.9855}, 'id': '1'}])
        fake.invoke.return_value = msg
        with mock.patch.object(agent_runtime, '_llm', return_value=fake):
            result = agent_runtime.agent_node(state)
        self.assertEqual(result['status'], 'WAITING_FOR_TOOL')


class ToolsNodeRetryTests(unittest.TestCase):
    """A real transient failure (ERR_UPSTREAM) should retry up to MAX_RETRIES, then surface the error to the LLM."""

    def test_retries_then_succeeds(self):
        calls = {'n': 0}

        def flaky(args):
            calls['n'] += 1
            if calls['n'] < 2:
                return {'ok': False, 'error': {'type': 'upstream_unavailable', 'message': 'timeout'}}
            return {'ok': True, 'data': {'count': 1}}

        fake_tool = mock.Mock(name='search_places')
        fake_tool.invoke.side_effect = flaky
        state = _state([AIMessage(content='', tool_calls=[{'name': 'search_places', 'args': {}, 'id': '1'}])])
        with mock.patch.object(agent_runtime, 'TOOLS', [fake_tool]), mock.patch.object(fake_tool, 'name', 'search_places'):
            result = agent_runtime.tools_node(state)
        self.assertEqual(calls['n'], 2)
        retrying_steps = [s for s in state['trace']['steps'] if s['kind'] == 'state' and s['name'] == 'RETRYING']
        self.assertEqual(len(retrying_steps), 1)

    def test_gives_up_after_max_retries(self):
        def always_fails(args):
            return {'ok': False, 'error': {'type': 'upstream_unavailable', 'message': 'down'}}

        fake_tool = mock.Mock(name='search_places')
        fake_tool.invoke.side_effect = always_fails
        state = _state([AIMessage(content='', tool_calls=[{'name': 'search_places', 'args': {}, 'id': '1'}])])
        with mock.patch.object(agent_runtime, 'TOOLS', [fake_tool]), mock.patch.object(fake_tool, 'name', 'search_places'):
            agent_runtime.tools_node(state)
        self.assertEqual(fake_tool.invoke.call_count, agent_runtime.MAX_RETRIES + 1)

    def test_non_transient_error_does_not_retry(self):
        fake_tool = mock.Mock(name='search_places')
        fake_tool.invoke.return_value = {'ok': False, 'error': {'type': 'invalid_input', 'message': 'bad lat'}}
        state = _state([AIMessage(content='', tool_calls=[{'name': 'search_places', 'args': {}, 'id': '1'}])])
        with mock.patch.object(agent_runtime, 'TOOLS', [fake_tool]), mock.patch.object(fake_tool, 'name', 'search_places'):
            agent_runtime.tools_node(state)
        self.assertEqual(fake_tool.invoke.call_count, 1)


class FeatureFlagFallbackTests(unittest.TestCase):
    """The /api/agent/food-stop endpoint, with the LLM path never reached: flag off, and flag on without a key.
    Both must honestly fall back to the existing deterministic recommend_food pipeline — never fabricate an
    agent run that didn't happen.
    """

    def _call(self, body):
        import server
        handler = object.__new__(server.Handler)
        handler.path = '/api/agent/food-stop'
        handler.headers = {'Content-Length': str(len(json.dumps(body)))}
        handler.rfile = io.BytesIO(json.dumps(body).encode())
        captured = {}
        handler.send_json = lambda code, data: captured.update(code=code, data=data)
        handler.post_admitted()
        return captured

    def test_flag_off_falls_back_with_real_deterministic_result(self):
        import server
        with mock.patch.object(server, 'AGENT_ENABLED', False):
            out = self._call({'request': 'find a burger', 'lat': 40.758, 'lon': -73.9855, 'item': 'burger'})
        self.assertEqual(out['code'], 200)
        self.assertEqual(out['data']['served_by'], 'deterministic_fallback')
        self.assertEqual(out['data']['reason'], 'AGENT_ENABLED is off')
        self.assertIn('candidates', out['data']['result'])

    def test_flag_on_without_key_falls_back_with_honest_reason(self):
        import server
        with mock.patch.object(server, 'AGENT_ENABLED', True), mock.patch.object(server, 'KEY', ''):
            out = self._call({'request': 'find a burger', 'lat': 40.758, 'lon': -73.9855, 'item': 'burger'})
        self.assertEqual(out['data']['served_by'], 'deterministic_fallback')
        self.assertIn('llm_unavailable', out['data']['reason'])

    def test_missing_request_text_is_a_400(self):
        import server
        out = self._call({'lat': 40.758, 'lon': -73.9855})
        self.assertEqual(out['code'], 400)


if __name__ == '__main__':
    unittest.main()
