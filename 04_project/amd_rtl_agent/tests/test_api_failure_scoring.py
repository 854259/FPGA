"""Pinned API_CONTRACT §4: transport/service failures are L0, never excluded."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('api_failure_quality', ROOT / 'bench/five_sample_quality.py')
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class ApiFailureScoringTests(unittest.TestCase):
    def failure(self, code, detail='service failure'):
        return quality.judge_or_tool_error(code, detail, Path('unused'), Path('unused'), 'unused')

    def test_one_l3_and_four_http_failures_score_point_two_not_one(self):
        with mock.patch.object(quality, 'run_judge') as judge:
            failures = [self.failure(code) for code in (503, 401, None, 200)]
        judge.assert_not_called()
        result = quality.load_official_score().summarize({
            't': [dict(level=3, coefficient=1.0)] + failures})
        self.assertEqual(result['pass@1'], .2)
        self.assertEqual(result['pass@5'], 1.0)
        self.assertEqual(result['tool_errors'], 0)
        self.assertEqual(result['per_task'][0]['scored_samples'], 5)
        self.assertTrue(all(item['solve_error'] for item in failures))

    def test_normal_empty_answer_still_uses_judge_and_is_not_service_failure(self):
        empty = dict(level=0, coefficient=0.0, tool_error=None)
        with mock.patch.object(quality, 'run_judge', return_value=empty) as judge:
            result = quality.judge_or_tool_error(200, None, Path('task'), Path('empty.v'), 'judge')
        judge.assert_called_once()
        self.assertIs(result, empty)
        self.assertNotIn('solve_error', result)

    def test_actual_judge_environment_error_remains_excluded(self):
        error = dict(level=0, coefficient=0.0, tool_error='LICENSE_ERROR')
        with mock.patch.object(quality, 'run_judge', return_value=error):
            result = quality.judge_or_tool_error(200, None, Path('task'), Path('s.v'), 'judge')
        summary = quality.load_official_score().summarize({
            't': [dict(level=3, coefficient=1), result]})
        self.assertEqual(summary['pass@1'], 1)
        self.assertEqual(summary['tool_errors'], 1)

    def test_failures_keep_scores_but_block_valid_quality_protocol_claim(self):
        official = quality.load_official_score()
        summary = {mode: official.summarize({'t': [self.failure(503)] * 5})
                   for mode in ('agent', 'baseline')}
        state = quality.evaluate_state(10, 10, [], summary, ['t'], 5, solve_errors=10)
        self.assertTrue(state['attempts_complete'])
        self.assertEqual(state['scored_coverage'], {'agent': 1.0, 'baseline': 1.0})
        self.assertFalse(state['comparable'])
        self.assertEqual(quality.exit_code_for(state), 3)

    def test_transport_timeout_uses_official_grace_and_never_retries(self):
        with mock.patch.object(quality.urllib.request, 'urlopen', side_effect=TimeoutError) as request:
            code, payload, _ = quality.post_solve(7867, 't', 'p', 'agent', 2)
        self.assertIsNone(code)
        self.assertEqual(payload['error'], 'TimeoutError')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['timeout'], 22)
        self.assertEqual(self.failure(code, payload['error'])['level'], 0)

    def test_malformed_json_keeps_http_status_and_raw_response(self):
        response = mock.Mock(status=200)
        response.read.return_value = b'{not json'
        manager = mock.MagicMock()
        manager.__enter__.return_value = response
        with mock.patch.object(quality.urllib.request, 'urlopen', return_value=manager):
            code, payload, _ = quality.post_solve(7867, 't', 'p', 'agent', 2)
        self.assertEqual(code, 200)
        self.assertEqual(payload['raw_response'], '{not json')
        self.assertEqual(self.failure(code, payload['error'])['level'], 0)

    def test_wrong_task_id_is_a_format_failure_with_original_payload(self):
        raw = json.dumps(dict(task_id='wrong', solution='x', trace='', elapsed_s=0)).encode()
        response = mock.Mock(status=200)
        response.read.return_value = raw
        manager = mock.MagicMock()
        manager.__enter__.return_value = response
        with mock.patch.object(quality.urllib.request, 'urlopen', return_value=manager):
            code, payload, _ = quality.post_solve(7867, 't', 'p', 'agent', 2)
        self.assertEqual(payload['error'], 'InvalidResponse')
        self.assertEqual(json.loads(payload['raw_response'])['task_id'], 'wrong')
        self.assertEqual(self.failure(code, payload['error'])['coefficient'], 0)

    def test_http_error_preserves_its_original_response_body(self):
        error = quality.urllib.error.HTTPError(
            'http://127.0.0.1:7867/v1/solve', 503, 'Unavailable', {},
            io.BytesIO('{"error":"服务异常"}'.encode('utf-8')))
        with mock.patch.object(quality.urllib.request, 'urlopen', side_effect=error):
            code, payload, _ = quality.post_solve(7867, 't', 'p', 'agent', 2)
        self.assertEqual(code, 503)
        self.assertEqual(payload['error'], 'HTTPError')
        self.assertEqual(payload['raw_response'], '{"error":"服务异常"}')
        self.assertNotIn('response_body_error', payload)

    def test_error_body_read_failure_does_not_replace_main_http_error(self):
        stream = mock.Mock()
        stream.read.side_effect = OSError('response read failed')
        error = quality.urllib.error.HTTPError(
            'http://127.0.0.1:7867/v1/solve', 503, 'Unavailable', {}, stream)
        with mock.patch.object(quality.urllib.request, 'urlopen', side_effect=error):
            code, payload, _ = quality.post_solve(7867, 't', 'p', 'agent', 2)
        self.assertEqual(code, 503)
        self.assertEqual(payload['error'], 'HTTPError')
        self.assertIn('Unavailable', payload['detail'])
        self.assertIsNone(payload['raw_response'])
        self.assertIn('response read failed', payload['response_body_error'])


if __name__ == '__main__':
    unittest.main()
