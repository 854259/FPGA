"""AMD-only lifecycle checks for the separate terminal supervisor, no RTL/model."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import terminal_supervisor as supervisor

SOURCE = Path(sys.argv.pop(1))


class TerminalControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='terminal-control-', dir=Path.cwd())
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def owned(self):
        return supervisor.build_owned(SOURCE/'owned_exec.py')[0]

    def test_180_cap_normal_combined_stream_and_duplicate_refused(self):
        run = self.owned()['run']
        argv = [sys.executable, '-B', '-c', "import sys;print('stdout');print('stderr',file=sys.stderr)"]
        out = self.root/'process'
        result = run(argv, self.root, out, 180)
        self.assertTrue(result['normal_completion'])
        self.assertEqual(result['returncode'], 0)
        self.assertTrue(result['leader_reaped'])
        self.assertEqual(result['remaining_group'], [])
        original = (out/'stdout.bin').read_bytes()
        self.assertIn(b'stdout', original)
        self.assertIn(b'stderr', original)
        with self.assertRaises(FileExistsError):
            run(argv, self.root, out, 180)
        self.assertEqual((out/'stdout.bin').read_bytes(), original)

    def test_timeout_owned_child_and_grandchild_reaped(self):
        code = "import os,time;pid=os.fork();print(pid,flush=True);time.sleep(60)"
        result = self.owned()['run']([sys.executable, '-B', '-c', code], self.root, self.root/'process', .3)
        self.assertTrue(result['timeout'])
        self.assertFalse(result['normal_completion'])
        self.assertTrue(result['leader_reaped'])
        self.assertEqual(result['remaining_group'], [])
        self.assertIn('SIGKILL_bound_unreaped_group', result['signals'])

    def test_cap_above_plan_refused_before_output(self):
        with self.assertRaises(AssertionError):
            self.owned()['run']([sys.executable, '-B', '-c', 'pass'], self.root, self.root/'process', 181)
        self.assertFalse((self.root/'process').exists())

    def test_original_source_drift_refused(self):
        bad = self.root/'owned_exec.py'
        bad.write_bytes((SOURCE/'owned_exec.py').read_bytes() + b'\n')
        with self.assertRaises(AssertionError):
            supervisor.build_owned(bad)

    def test_queued_ticket_refused(self):
        with self.assertRaises(AssertionError):
            supervisor.terminal_gate(self.root, dict(ticket=104, cwd=str(self.root), state='queued'))

    def test_live_original_child_refused(self):
        original = dict(pid=123, starttime='456')
        ticket = dict(ticket=104, cwd=str(self.root), state='completed', returncode=0,
                      runner=original, child=original)
        with patch.object(supervisor, 'identity', return_value=original):
            with self.assertRaises(AssertionError):
                supervisor.terminal_gate(self.root, ticket)

    def test_stage_failure_refused_after_retirement(self):
        (self.root/'results').mkdir()
        supervisor.save(self.root/'results/summary.json', dict(complete=True, passed=False))
        original = dict(pid=123, starttime='456')
        ticket = dict(ticket=104, cwd=str(self.root), state='completed', returncode=0,
                      runner=original, child=original)
        with patch.object(supervisor, 'identity', return_value=None):
            with self.assertRaises(AssertionError):
                supervisor.terminal_gate(self.root, ticket)

    def test_bound_archive_reuse_and_drift_refused(self):
        plan = dict(spec_sha256='spec', collector_sha256='collector')
        manifest = dict(run_spec_sha256='spec', collector_sha256='collector',
                        files={'sample': hashlib.sha256(b'original').hexdigest()})
        for value, filename in ((b'original', 'good.zip'), (b'changed', 'bad.zip')):
            with zipfile.ZipFile(self.root/filename, 'x') as archive:
                archive.writestr('sample', value)
                archive.writestr('ARCHIVE_MANIFEST.json', json.dumps(manifest))
        expected = supervisor.sha(self.root/'good.zip')
        self.assertEqual(supervisor.archive_check(self.root/'good.zip', plan), expected)
        self.assertEqual(supervisor.archive_check(self.root/'good.zip', plan), expected)
        with self.assertRaises(AssertionError):
            supervisor.archive_check(self.root/'bad.zip', plan)


if __name__ == '__main__':
    unittest.main(verbosity=2)
