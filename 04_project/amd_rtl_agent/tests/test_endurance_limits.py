"""HTTP assertions must not certify unattributed AMD/process resource recovery."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('endurance_limits', ROOT / 'bench/http_endurance.py')
endurance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endurance)


class ResourceLimitsTests(unittest.TestCase):
    def test_lower_global_counters_do_not_prove_our_resources_were_reclaimed(self):
        result = endurance.resource_assessment(
            dict(procs=10, temps=2, vram_mb=20000, free_gb=10),
            dict(procs=1, temps=0, vram_mb=1000, free_gb=11))
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['observed_changes']['procs'], -9)
        self.assertTrue(any('PID/starttime' in item for item in result['limitations']))

    def test_missing_nvidia_data_does_not_become_zero_or_amd_pass(self):
        with mock.patch.object(endurance.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertIsNone(endurance.gpu_mem_used_mb())
        result = endurance.resource_assessment(
            dict(procs=0, temps=0, vram_mb=None, free_gb=10),
            dict(procs=0, temps=0, vram_mb=None, free_gb=10))
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['observed_changes']['vram_mb'])
        self.assertTrue(any('AMD' in item for item in result['limitations']))


class HttpScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        tasks = self.root / 'tasks'
        prompt = tasks / 'Prob001_zero/prompt.txt'
        prompt.parent.mkdir(parents=True)
        prompt.write_text('Output zero.')
        self.out = self.root / 'out'
        self.service = mock.Mock()
        self.service.poll.return_value = None
        self.empty_recovery = False
        self.fail_concurrent = False
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(endurance, 'TASKS_DIR', tasks))
        self.stack.enter_context(mock.patch.object(endurance, 'OUT', self.out))
        self.stack.enter_context(mock.patch.object(endurance, 'env', return_value={}))
        self.stack.enter_context(mock.patch.object(endurance.subprocess, 'Popen', return_value=self.service))
        self.stack.enter_context(mock.patch.object(endurance, 'health_state', return_value=(True, {'ready': True})))
        self.stack.enter_context(mock.patch.object(endurance, 'resources', return_value=
            dict(procs=0, temps=0, vram_mb=None, free_gb=11.0)))
        self.stack.enter_context(mock.patch.object(endurance, 'request', side_effect=self.request))

    def request(self, path, data=None, token=endurance.TOKEN, **kwargs):
        if token == 'wrong':
            return 401, b'{}', 0
        if path == '/v1/nope':
            return 404, b'{}', 0
        try:
            obj = json.loads(data)
        except (ValueError, TypeError):
            return 400, b'{}', 0
        if 'task_id' not in obj:
            return 400, b'{}', 0
        if obj.get('deadline_s') == 1:
            return 200, b'{"solution":""}', 0
        if obj['task_id'] == 'c1' and self.fail_concurrent:
            return 500, b'{}', 0
        if obj['task_id'] == 'e1' and self.empty_recovery:
            return 200, b'{"solution":""}', 0
        return 200, b'{"solution":"module TopModule; endmodule"}', 0

    def call(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = endurance.main()
        return result, output.getvalue()

    def test_http_success_is_explicitly_not_overall_acceptance(self):
        result, output = self.call()
        report = json.loads((self.out / 'endurance.json').read_text(encoding='utf-8'))
        self.assertEqual(result, 0)
        self.assertTrue(report['http_assertions_passed'])
        self.assertFalse(report['service_identity_verified'])
        self.assertEqual(report['resource_recovery']['status'], 'unknown')
        self.assertEqual(report['overall_acceptance'], 'unknown')
        self.assertNotIn('验收通过：', output)
        self.assertIn('资源回收结论  : UNKNOWN', output)

    def test_empty_recovery_still_fails_http_assertions(self):
        self.empty_recovery = True
        result, _ = self.call()
        report = json.loads((self.out / 'endurance.json').read_text(encoding='utf-8'))
        self.assertEqual(result, 1)
        self.assertIn('恢复后正常请求', report['failures'])
        self.assertEqual(report['overall_acceptance'], 'failed')

    def test_one_failed_concurrent_response_still_fails(self):
        self.fail_concurrent = True
        result, _ = self.call()
        report = json.loads((self.out / 'endurance.json').read_text(encoding='utf-8'))
        self.assertEqual(result, 1)
        self.assertIn('并发3请求', report['failures'])

    def test_step_readiness_still_participates_in_failure(self):
        states = [(True, {}), (False, {})] + [(True, {})] * 8
        with mock.patch.object(endurance, 'health_state', side_effect=states):
            result, _ = self.call()
        report = json.loads((self.out / 'endurance.json').read_text(encoding='utf-8'))
        self.assertEqual(result, 1)
        self.assertFalse(report['steps'][0]['service_ready'])
        self.assertFalse(report['steps'][0]['passed'])

    def test_dead_child_cannot_claim_another_services_readiness(self):
        self.service.poll.return_value = 1
        result, output = self.call()
        self.assertEqual(result, 1)
        self.assertIn('自启服务已退出', output)
        self.assertFalse((self.out / 'endurance.json').exists())


if __name__ == '__main__':
    unittest.main()
