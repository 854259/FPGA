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

    def test_collection_audit_pipeline_and_completed_reuse(self):
        preparation, source, out = self.root/'preparation', self.root/'source', self.root/'terminal'
        preparation.mkdir()
        source.mkdir()
        (source/'owned_exec.py').write_bytes((SOURCE/'owned_exec.py').read_bytes())
        collector = '''import argparse,json,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root');p.add_argument('--guard');p.add_argument('--archive');a=p.parse_args()
plan=json.loads((Path(a.root)/'plan.json').read_bytes())
manifest=dict(run_spec_sha256=plan['spec_sha256'],collector_sha256=plan['collector_sha256'],files={})
with zipfile.ZipFile(a.archive,'x') as z:z.writestr('ARCHIVE_MANIFEST.json',json.dumps(manifest))
'''
        auditor = '''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source');p.add_argument('--archive');p.add_argument('--out');a=p.parse_args()
out=Path(a.out);assert not out.exists(), 'process logs must not pre-create audit output'
assert Path(a.archive).is_file();plan=json.loads((Path(a.source)/'plan.json').read_bytes());out.mkdir()
(out/'RESULTS.json').write_text(json.dumps(dict(evidence_valid=True,spec_sha256=plan['spec_sha256'],audit_model_calls=0,audit_eda_calls=0,auditor_sha256=plan['replacement_wrapper_sha256'],adoption=False)))
'''
        (source/'collect_evidence.py').write_text(collector)
        (preparation/'audit_relocated_capture.py').write_text(auditor)
        supervisor.save(preparation/'RECEIPT.json', {})
        plan = dict(source_root=str(source), out_root=str(out), spec_sha256='fixture',
                    max_collector_seconds=60, max_audit_seconds=180, max_total_seconds=300,
                    collector_sha256=supervisor.sha(source/'collect_evidence.py'),
                    replacement_wrapper_sha256=supervisor.sha(preparation/'audit_relocated_capture.py'),
                    control_receipt_sha256=supervisor.sha(preparation/'RECEIPT.json'))
        supervisor.save(preparation/'TERMINAL_PLAN.json', plan)
        supervisor.save(source/'plan.json', plan)
        supervisor.save(self.root/'ticket.json', {})
        with patch.object(supervisor, 'PLAN_SHA', supervisor.sha(preparation/'TERMINAL_PLAN.json')), \
             patch.object(supervisor, 'source_check'), patch.object(supervisor, 'terminal_gate'):
            result = supervisor.execute(preparation, self.root/'ticket.json')
            self.assertTrue(result['passed'], result['error'])
            self.assertEqual(set(result['processes']), {'collector', 'audit'})
            self.assertFalse(supervisor.read(out/'audit/RESULTS.json')['adoption'])
            before = {p.relative_to(out).as_posix(): supervisor.sha(p) for p in out.rglob('*') if p.is_file()}
            again = supervisor.execute(preparation, self.root/'ticket.json')
            self.assertEqual(again, result)
            self.assertEqual(before, {p.relative_to(out).as_posix(): supervisor.sha(p) for p in out.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main(verbosity=2)
