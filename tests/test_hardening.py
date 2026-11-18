"""Regression tests for the server/agent hardening: trusted client IP for rate limits, bounded rate table,
non-object JSON bodies, private static files, the agent's caller location and its compact route summary."""
import importlib.util
import io
import json
import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

HAS_AGENT = importlib.util.find_spec('langgraph') is not None


def handler(path='/', body=None, xff=None, peer='203.0.113.9'):
    h = object.__new__(server.Handler)
    h.path, h.client_address, h.directory = path, (peer, 50000), str(ROOT)
    raw = b'' if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    h.headers = {'Content-Length': str(len(raw))}
    if xff is not None:
        h.headers['X-Forwarded-For'] = xff
    h.rfile = io.BytesIO(raw)
    return h


class ClientIpTests(unittest.TestCase):
    def test_header_ignored_without_a_trusted_proxy(self):
        with mock.patch.object(server, 'TRUSTED_PROXY_HOPS', 0):
            self.assertEqual(server.client_ip(handler(xff='1.2.3.4')), '203.0.113.9')

    def test_one_hop_trusts_only_the_proxy_appended_entry(self):
        with mock.patch.object(server, 'TRUSTED_PROXY_HOPS', 1):
            # The client wrote "1.2.3.4"; the proxy appended the address it actually saw.
            self.assertEqual(server.client_ip(handler(xff='1.2.3.4, 198.51.100.7')), '198.51.100.7')
            self.assertEqual(server.client_ip(handler()), '203.0.113.9')

    def test_spoofed_header_cannot_reset_the_limit(self):
        with mock.patch.object(server, 'TRUSTED_PROXY_HOPS', 0), mock.patch.dict(server._rate, clear=True):
            codes = [server.rate_ok(handler(xff=f'10.0.0.{i}'), 'agent') for i in range(6)]
        self.assertEqual(codes, [True, True, True, False, False, False])


class RateTableTests(unittest.TestCase):
    def test_overflow_keeps_active_counters(self):
        now = time.time()
        busy = ('198.51.100.1', 'agent')
        fill = {(f'10.{i // 250}.{i % 250}.1', 'places'): [now - 30] for i in range(server.RATE_MAX_CLIENTS)}
        with mock.patch.object(server, 'TRUSTED_PROXY_HOPS', 0), mock.patch.dict(server._rate, fill, clear=True):
            server._rate[busy] = [now - 1] * server.RATE_LIMITS['agent']
            server.rate_ok(handler(peer='192.0.2.50'), 'places')       # pushes the table over the cap
            self.assertLessEqual(len(server._rate), server.RATE_MAX_CLIENTS)
            self.assertFalse(server.rate_ok(handler(peer=busy[0]), 'agent'))  # still limited, not wiped


class JsonObjectTests(unittest.TestCase):
    def test_read_json_rejects_non_objects(self):
        for body in (b'[]', b'"x"', b'null', b'1'):
            with self.assertRaises(ValueError):
                server.read_json(handler(body=body), 1000)

    def test_endpoints_answer_400_instead_of_dropping_the_connection(self):
        for path in ('/api/agent/food-stop', '/api/menu/verify', '/api/recommend/food', '/api/detours',
                     '/api/itinerary', '/api/routes', '/api/navigation/progress'):
            for body in (b'[]', b'"x"', b'null'):
                h, out = handler(path, body), {}
                h.send_json = lambda code, data: out.update(code=code, data=data)
                h.post_admitted()
                self.assertEqual(out.get('code'), 400, (path, body))


class PrivateStaticTests(unittest.TestCase):
    def test_databases_source_and_dot_paths_are_private(self):
        for rel in ('data/agent_checkpoints.db', 'data/x.sqlite', 'data/x.DB', 'data/x.db-wal', 'server.py',
                    '.agent-state/agent_checkpoints.db', '.github/workflows/production-acceptance.yml'):
            self.assertTrue(server.private_static_path(ROOT / rel), rel)
        self.assertTrue(server.private_static_path(ROOT.parent / 'elsewhere.json'))

    def test_public_assets_stay_public(self):
        for rel in ('index.html', 'app.js', 'data/places/index.json', 'data/urban/crime/complaints.sqlite.gz'):
            self.assertFalse(server.private_static_path(ROOT / rel), rel)

    def test_send_head_refuses_a_checkpoint_database(self):
        h, errors = handler('/data/agent_checkpoints.db'), []
        h.send_error = lambda code, msg=None: errors.append(code)
        self.assertIsNone(h.send_head())
        self.assertEqual(errors, [404])


@unittest.skipUnless(HAS_AGENT, 'agent dependencies (requirements.txt) not installed')
class AgentLocationTests(unittest.TestCase):
    def _call(self, body):
        h, out = handler('/api/agent/food-stop', body), {}
        h.send_json = lambda code, data: out.update(code=code, data=data)
        h.post_admitted()
        return out

    def test_agent_path_requires_a_location(self):
        with mock.patch.object(server, 'AGENT_ENABLED', True), mock.patch.object(server, 'openai_key_problem', return_value=None):
            out = self._call({'request': 'find a burger'})
        self.assertEqual(out['code'], 400)
        self.assertIn('location', out['data']['error'])

    def test_agent_receives_the_callers_location(self):
        from agent import runtime
        with mock.patch.object(server, 'AGENT_ENABLED', True), mock.patch.object(server, 'openai_key_problem', return_value=None), \
             mock.patch.object(runtime, 'run_food_stop_agent', return_value={'status': 'COMPLETED'}) as run:
            out = self._call({'request': 'find a burger', 'lat': 40.758, 'lon': -73.9855})
        self.assertEqual(out['code'], 200)
        run.assert_called_once_with('find a burger', origin={'lat': 40.758, 'lon': -73.9855})

    def test_location_is_stated_in_the_first_message(self):
        from agent.runtime import initial_message
        self.assertIn('lat=40.758000, lon=-73.985500', initial_message('burger', {'lat': 40.758, 'lon': -73.9855}).content)
        self.assertIn('Do not call tools with guessed coordinates', initial_message('burger').content)

    def test_checkpoints_live_outside_the_served_tree(self):
        from agent.runtime import CHECKPOINT_DB
        self.assertTrue(server.private_static_path(CHECKPOINT_DB))

    def test_calculate_route_returns_a_compact_summary(self):
        from agent.tools import calculate_route
        r = calculate_route.invoke({'origin_lat': 40.7536, 'origin_lon': -73.9832, 'dest_lat': 40.7587, 'dest_lon': -73.9787})
        self.assertTrue(r['ok'])
        route = r['data']['routes'][0]
        self.assertGreater(route['distance_m'], 0)
        self.assertNotIn('edges', route)
        self.assertNotIn('geometry', route)
        self.assertLess(len(str(r)), 20000)  # the full planner response is ~165,000 characters



class DetoursUnavailableTests(unittest.TestCase):
    def test_network_unavailable_is_a_503(self):
        h, out = handler('/api/detours', {'route': {}}), {}
        h.send_json = lambda code, data: out.update(code=code, data=data)
        with mock.patch.object(server, 'get_planner', side_effect=RuntimeError('Pedestrian network unavailable')):
            h.post_admitted()
        self.assertEqual(out['code'], 503)


@unittest.skipUnless(HAS_AGENT, 'agent dependencies (requirements.txt) not installed')
class AgentTimeoutTests(unittest.TestCase):
    def test_model_client_has_a_timeout_and_no_sdk_retries(self):
        from agent import runtime
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test-not-a-real-key'}):
            bound = runtime._llm(timeout=7)
        self.assertEqual(bound.bound.request_timeout, 7)
        self.assertEqual(bound.bound.max_retries, 0)

    def test_model_call_never_outlives_the_run_deadline(self):
        from agent import runtime
        from langchain_core.messages import AIMessage, HumanMessage
        state = {'messages': [HumanMessage('food')], 'run_id': 't', 'status': 'RUNNING', 'step_count': 0,
                 'trace': runtime.tracing.new_trace('t'), 'deadline': time.time() + 5}
        fake = mock.Mock()
        fake.invoke.return_value = AIMessage(content='done')
        with mock.patch.object(runtime, '_llm', return_value=fake) as llm:
            runtime.agent_node(state)
        self.assertLessEqual(llm.call_args.kwargs['timeout'], 5)


if __name__ == '__main__':
    unittest.main()
