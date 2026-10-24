"""/api/interpret failure reporting with the OpenAI call mocked (no network, no real key): every failure returns a safe
`reason` (stage, HTTP status, provider error type/code, our validator's message) and the key never appears in the response
or the log. Run: python3 -m unittest tests.test_interpret
"""
import contextlib, io, json, pathlib, sys, unittest
from unittest import mock
from urllib import error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

FAKE_KEY = 'sk-test-SECRET1234567890abcdef'
DOC = {'message': 'I want a greener walk'}


class Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body):
    return error.HTTPError('https://api.openai.com/v1/chat/completions', code, 'err', {}, io.BytesIO(json.dumps(body).encode()))


def completion(content):
    return Resp({'choices': [{'message': {'content': content if isinstance(content, str) else json.dumps(content)}}]})


class InterpretFailures(unittest.TestCase):
    def run_with(self, effect):
        log = io.StringIO()
        with mock.patch.object(server, 'KEY', FAKE_KEY), mock.patch.object(server.request, 'urlopen', **({'side_effect': effect} if isinstance(effect, BaseException) else {'return_value': effect})), contextlib.redirect_stdout(log):
            status, body = server.interpret(dict(DOC))
        text = json.dumps(body) + log.getvalue()
        self.assertNotIn(FAKE_KEY, text, 'the key never leaks')
        self.assertNotIn('SECRET', text)
        return status, body, log.getvalue()

    def test_key_environment_whitespace_is_trimmed(self):
        key = server.normalize_openai_api_key('  \r\nsk-test-clean-token \t\n')
        self.assertEqual(key, 'sk-test-clean-token')
        self.assertIsNone(server.openai_key_problem(key))
        with mock.patch.object(server, 'KEY', key), mock.patch.object(server.request, 'urlopen', return_value=completion({'weights': {}, 'constraints': {}})) as opener:
            status, body = server.interpret(dict(DOC))
        self.assertEqual(status, 200)
        self.assertEqual(body['weights'], {})
        self.assertEqual(opener.call_args.args[0].get_header('Authorization'), 'Bearer sk-test-clean-token')

    def test_key_format_problem_stops_before_http(self):
        for key in ('sk-test-middle\nnewline', 'sk-test-middle space', 'sk-test-middle\x00nul', 'sk-test-middle\u200bnonascii'):
            with self.subTest(key=repr(key)), mock.patch.object(server, 'KEY', key), mock.patch.object(server.request, 'urlopen') as opener:
                log = io.StringIO()
                with contextlib.redirect_stdout(log):
                    status, body = server.interpret(dict(DOC))
                self.assertEqual(status, 503)
                self.assertEqual(body['reason']['stage'], 'invalid_key_format')
                self.assertNotIn(key, json.dumps(body) + log.getvalue())
                opener.assert_not_called()

    def test_blank_environment_value_is_not_configured(self):
        self.assertEqual(server.normalize_openai_api_key(' \r\n '), '')
        self.assertEqual(server.openai_key_problem(''), 'not_configured')

    def test_not_configured(self):
        with mock.patch.object(server, 'KEY', ''):
            status, body = server.interpret(dict(DOC))
        self.assertEqual(status, 503); self.assertEqual(body['reason']['stage'], 'not_configured')

    def test_invalid_key(self):
        status, body, log = self.run_with(http_error(401, {'error': {'message': f'Incorrect API key provided: {FAKE_KEY[:8]}***cdef', 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}))
        self.assertEqual(status, 502)
        self.assertEqual(body['reason'], {'stage': 'upstream_http', 'http_status': 401, 'type': 'invalid_request_error', 'code': 'invalid_api_key', 'detail': None})
        self.assertIn('invalid_api_key', log)
        self.assertNotIn('Incorrect API key', json.dumps(body), 'the provider message (which echoes key fragments) is not passed on')

    def test_no_quota(self):
        status, body, _ = self.run_with(http_error(429, {'error': {'message': 'You exceeded your current quota', 'type': 'insufficient_quota', 'code': 'insufficient_quota'}}))
        self.assertEqual((body['reason']['http_status'], body['reason']['code']), (429, 'insufficient_quota'))

    def test_model_not_available(self):
        status, body, _ = self.run_with(http_error(404, {'error': {'type': 'invalid_request_error', 'code': 'model_not_found'}}))
        self.assertEqual(body['reason']['code'], 'model_not_found')

    def test_unreachable(self):
        status, body, _ = self.run_with(error.URLError(TimeoutError('timed out')))
        self.assertEqual(body['reason']['stage'], 'upstream_unreachable'); self.assertEqual(body['reason']['detail'], 'TimeoutError')

    def test_bad_provider_response(self):
        status, body, _ = self.run_with(Resp({'object': 'error'}))
        self.assertEqual(body['reason']['stage'], 'upstream_bad_response')

    def test_model_output_not_json(self):
        status, body, _ = self.run_with(completion('Sure! Here is your plan: greener streets.'))
        self.assertEqual(body['reason']['stage'], 'model_output_invalid_json')

    def test_model_output_rejected_names_the_problem(self):
        status, body, log = self.run_with(completion({'weights': {'Greenery': 90}, 'directions': {}, 'constraints': {}}))
        r = body['reason']
        self.assertEqual(r['stage'], 'model_output_rejected'); self.assertIn('Invalid dimension name', r['detail']); self.assertIn("keys: ['constraints', 'directions', 'weights']", r['detail'])
        self.assertIn('model_output_rejected', log)

    def test_success_unchanged(self):
        status, body, _ = self.run_with(completion({'weights': {'Nature': 90}, 'directions': {'Nature': 'high'}, 'constraints': {}}))
        self.assertEqual(status, 200); self.assertEqual(body['weights'], {'Nature': 90}); self.assertNotIn('reason', body)

    def test_history_must_be_array(self):
        with mock.patch.object(server, 'KEY', FAKE_KEY):
            status, _ = server.interpret({'message': 'walk', 'history': None})
        self.assertEqual(status, 400)

    def test_unexpected_failure_logs_frames_without_message(self):
        status, body, log = self.run_with(ValueError('SECRET header value'))
        self.assertEqual(status, 500)
        self.assertIn('frames', log)
        self.assertIn('call_llm', log)

    def test_coffee_is_preserved_separately_from_weights(self):
        result = {'weights': {'Scenic & Visual': 90, 'Architecture': 85, 'Nature': 85},
                  'journey': {'interests': ['parks'], 'food': [
                      {'category': 'cafes', 'item': 'coffee', 'required': True}]}}
        status, body, _ = self.run_with(completion(result))
        self.assertEqual(status, 200)
        self.assertEqual(body['journey']['food'][0]['item'], 'coffee')
        self.assertEqual(body['journey']['interests'], ['parks'])
        from routing.engine import get_planner
        routes = get_planner().plan({'lon': -73.9832, 'lat': 40.7536},
                                   {'lon': -73.9787, 'lat': 40.7587}, body,
                                   {'max_minutes': 30, 'max_detour_pct': 25})['routes']
        self.assertTrue(routes)
        self.assertTrue(all(r['distance_m'] > 0 and r['ordered_edge_ids'] for r in routes))
        self.assertEqual(set(routes[0]['dimension_scores']), set(server.DIMENSIONS))
        self.assertIn('food must preserve it', server.SYSTEM)

    def test_scrub(self):
        with mock.patch.object(server, 'KEY', FAKE_KEY):
            self.assertEqual(server.scrub(f'value {FAKE_KEY} and sk-proj-abcdEFGH1234 end'), 'value [key] and [key] end')


if __name__ == '__main__':
    unittest.main()
