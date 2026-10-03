"""Quality-driver lifecycle tests use fake HTTP/model/judge calls only."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quality_safety', ROOT / 'bench/five_sample_quality.py')
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class QualitySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kit = self.root / 'kit'
        self.tasks = self.kit / 'bench/tasks_veval'
        task = self.tasks / 'ProbTest'
        task.mkdir(parents=True)
        (task / 'prompt.txt').write_text('Write a constant zero module.')
        (task / 'task.json').write_text('{"task_id":"ProbTest"}')
        for name in ('official_eval.py', 'submission/agent/runtime.py', 'submission/baseline.py',
                     'submission/manifest.json', 'submission/skill/rtl-generation/SKILL.md',
                     'submission/skill/rtl-feedback-repair/SKILL.md',
                     'official_reference/selftest/judge/veval-judge',
                     'official_reference/selftest/judge/l3_synth.tcl', 'official_reference/UPSTREAM.json'):
            path = self.kit / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixed fixture')
        self.out = self.root / 'run'
        self.service = mock.Mock(pid=4321)
        self.service.poll.return_value = None
        self.adapter = mock.Mock()
        self.adapter.judge_sample.side_effect = self.judge
        self.response = {'task_id': 'ProbTest', 'solution': 'module TopModule; endmodule',
                         'trace': ' ' * 25000, 'elapsed_s': 1.0}
        self.post = mock.Mock(return_value=(200, self.response, 1.0))
        self.popen = mock.Mock(side_effect=self.start_service)
        self.tokens = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (('KIT', self.kit), ('TASKS_DIR', self.tasks)):
            self.stack.enter_context(mock.patch.object(quality, name, value))
        self.stack.enter_context(mock.patch.object(quality, 'load_evaluation', return_value=self.adapter))
        self.stack.enter_context(mock.patch.object(quality, 'require_free_port'))
        self.stack.enter_context(mock.patch.object(quality, 'wait_ready', return_value=(True, {'ready': True})))
        self.stack.enter_context(mock.patch.object(quality, 'owns_listener', return_value=True))
        self.stack.enter_context(mock.patch.object(quality, 'post_solve', self.post))
        self.stack.enter_context(mock.patch.object(quality.subprocess, 'Popen', self.popen))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'MODEL_NAME': 'fake-model', 'LLM_BASE_URL': 'http://127.0.0.1:8000/v1',
            'RTL_PROFILE': 'development', 'RTL_REPAIRS': '1',
            'RTL_TEMPERATURE': '0', 'RTL_MAX_TOKENS': '8192'}))

    def judge(self, task, solution, dst, verdict, deadline):
        value = dict(task_id='ProbTest', level=3, coefficient=1.0, elapsed_s=2.0,
                     stages={'compile': True, 'simulate': True, 'synth': True})
        verdict.write_text(json.dumps(value))
        return value

    def start_service(self, command, **kwargs):
        # The version snapshot must exist before a process can load the runtime.
        self.assertTrue((self.out / 'run_manifest.json').is_file())
        self.tokens.append(kwargs['env']['FPGACHINA_TOKEN'])
        return self.service

    def run_main(self):
        argv = ['five_sample_quality.py', '--tasks', 'ProbTest', '--samples', '1',
                '--deadline', '10', '--out', str(self.out)]
        with mock.patch.object(quality.sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            return quality.main()

    def test_full_response_and_shared_judgements_are_preserved(self):
        self.assertEqual(self.run_main(), 0)
        response = self.out / 'ProbTest/agent/s0/response.json'
        self.assertGreater(response.stat().st_size, 20000)
        self.assertEqual(json.loads(response.read_text()), self.response)
        self.assertEqual(self.adapter.judge_sample.call_count, 2)
        self.assertEqual(json.loads((self.out / 'quality_official.json').read_text())['summary']['agent']['set_score'], 1)
        status = json.loads((self.out / 'run_status.json').read_text())
        self.assertTrue(status['complete'])
        self.assertTrue(status['comparable'])
        self.assertEqual(status['final_version_changes'], [])
        self.service.terminate.assert_called_once()

    def test_existing_run_is_rejected_without_overwriting_or_starting(self):
        self.out.mkdir()
        sentinel = self.out / 'by_task.json'
        sentinel.write_text('old evidence')
        with self.assertRaises(FileExistsError):
            self.run_main()
        self.assertEqual(sentinel.read_text(), 'old evidence')
        self.popen.assert_not_called()
        self.post.assert_not_called()

    def test_final_version_change_blocks_comparison(self):
        def response(*args, **kwargs):
            if self.post.call_count == 2:
                (self.kit / 'submission/agent/runtime.py').write_text('changed during final request')
            return 200, self.response, 1.0
        self.post.side_effect = response
        self.assertEqual(self.run_main(), 3)
        summary = json.loads((self.out / 'quality_official.json').read_text())
        self.assertFalse(summary['comparable'])
        self.assertTrue(any('runtime' in e for e in summary['incomparable_reasons']))

    def test_mid_run_change_stops_before_another_request(self):
        def response(*args, **kwargs):
            (self.kit / 'submission/agent/runtime.py').write_text('changed after first request')
            return 200, self.response, 1.0
        self.post.side_effect = response
        with self.assertRaisesRegex(RuntimeError, 'version changed'):
            self.run_main()
        self.assertEqual(self.post.call_count, 1)
        status = json.loads((self.out / 'run_status.json').read_text())
        self.assertFalse(status['complete'])
        self.assertTrue(status['final_version_changes'])

    def test_judge_failure_stops_and_keeps_run_invalid(self):
        self.adapter.judge_sample.side_effect = RuntimeError('missing actual tool logs')
        with self.assertRaisesRegex(RuntimeError, 'missing actual'):
            self.run_main()
        self.assertEqual(self.post.call_count, 1)
        self.assertTrue((self.out / 'ProbTest/agent/s0/response.json').is_file())
        self.assertFalse((self.out / 'quality_official.json').exists())
        status = json.loads((self.out / 'run_status.json').read_text())
        self.assertFalse(status['complete'])
        self.assertFalse(status['comparable'])
        self.service.terminate.assert_called_once()

    def test_random_service_token_is_unique_per_run(self):
        self.run_main()
        self.out = self.root / 'second_run'
        self.run_main()
        self.assertEqual(len(set(self.tokens)), 2)
        self.assertTrue(all(len(token) >= 32 for token in self.tokens))

    def test_status_write_failure_still_stops_owned_service(self):
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == 'run_status.json':
                raise OSError('disk full')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'write_text', write):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.run_main()
        self.service.terminate.assert_called_once()
        self.post.assert_not_called()

    def test_http_failure_counts_l0_and_is_not_a_judge_environment_error(self):
        self.post.side_effect = [(503, {'error': 'HTTPError'}, 1.0),
                                 (200, self.response, 1.0)]
        self.assertEqual(self.run_main(), 3)
        report = json.loads((self.out / 'quality_official.json').read_text(encoding='utf-8'))
        self.assertEqual(report['summary']['agent']['set_score'], 0)
        self.assertEqual(report['summary']['agent']['scored_tasks'], 1)
        self.assertEqual(report['summary']['agent']['tool_errors'], 0)
        self.assertEqual(report['ledger']['solve_error'], 1)
        self.assertEqual(report['ledger']['tool_error'], 0)
        self.assertEqual(report['ledger']['empty'], 0)
        self.assertEqual(report['ledger']['graded'], 2)
        self.assertFalse(report['comparable'])
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.adapter.judge_sample.call_count, 1)


class OwnedServiceTests(unittest.TestCase):
    def test_dead_child_cannot_be_replaced_by_old_ready_service(self):
        proc = mock.Mock(returncode=1)
        proc.poll.return_value = 1
        with mock.patch.object(quality.urllib.request, 'urlopen') as request:
            ready, detail = quality.wait_ready(7867, process=proc)
        self.assertFalse(ready)
        self.assertEqual(detail['returncode'], 1)
        request.assert_not_called()

    def test_ready_response_without_owned_listener_is_rejected(self):
        proc = mock.Mock(pid=123)
        proc.poll.return_value = None
        response = mock.Mock(status=200)
        response.read.return_value = b'{"ready":true}'
        manager = mock.MagicMock()
        manager.__enter__.return_value = response
        with mock.patch.object(quality.urllib.request, 'urlopen', return_value=manager), \
                mock.patch.object(quality, 'owns_listener', return_value=False), \
                mock.patch.object(quality.time, 'time', side_effect=[0, 0, 2]), \
                mock.patch.object(quality.time, 'sleep'):
            ready, _ = quality.wait_ready(7867, timeout=1, process=proc)
        self.assertFalse(ready)

    def test_linux_socket_inode_must_belong_to_the_exact_pid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'net').mkdir()
            (root / 'net/tcp').write_text(
                'header\n0: 0100007F:1EBB 00000000:0000 0A 0:0 00:0000 0000 1000 0 456\n')
            fd = root / '123/fd'
            fd.mkdir(parents=True)
            (fd / '7').write_text('fd placeholder')
            with mock.patch.object(quality.os, 'readlink', return_value='socket:[456]'):
                self.assertTrue(quality.owns_listener(123, 7867, root))
                self.assertFalse(quality.owns_listener(999, 7867, root))


if __name__ == '__main__':
    unittest.main()
