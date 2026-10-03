import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / 'bench' / 'audit_judge_chain.py'
spec = importlib.util.spec_from_file_location('judge_chain_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class JudgeChainAuditTests(unittest.TestCase):
    def test_all_five_samples_are_preserved_and_first_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            results = run / 'full' / 'results'
            results.mkdir(parents=True)
            for i in range(5):
                verdict = dict(task_id='ProbA', level=2 if i == 0 else 3,
                               stages=dict(compile=True, simulate=True, synth=i != 0),
                               elapsed_s=10 if i == 0 else 30, tool_error=None)
                (results / ('agent.ProbA.s%d.json' % i)).write_text(json.dumps(verdict))
                log = audit.judge_log_path(run, 'agent', 'ProbA', 's%d' % i)
                log.parent.mkdir(parents=True)
                log.write_text('')
            self.assertEqual(len(audit.load_results(run)), 5)
            out = run / 'audit.json'
            with mock.patch.object(sys, 'argv', ['audit', '--run', str(run), '--json', str(out)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(audit.main(), 0)
            report = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(report['samples'], 5)
            self.assertEqual(report['empty_judge_logs'], 5)
            self.assertEqual(report['suspects']['no_synth_but_sim_pass'][0][:3],
                             ['agent', 'ProbA', 's0'])

    def test_flat_results_layout_resolves_its_own_logs(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            (run / 'results').mkdir()
            (run / 'results' / 'agent.Prob.with.dot.s2.json').write_text(
                json.dumps(dict(task_id='Prob.with.dot', level=0)))
            self.assertIn(('agent', 'Prob.with.dot', 's2'), audit.load_results(run))
            self.assertEqual(audit.judge_log_path(run, 'agent', 'Prob.with.dot', 's2'),
                             run / 'agent' / 'Prob.with.dot' / 's2' / 'judge_logs' / 'Prob.with.dot.judge.log')

    def test_corrupt_result_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            results = run / 'results'
            results.mkdir()
            (results / 'agent.ProbA.s0.json').write_text('{bad')
            with self.assertRaises(ValueError):
                audit.load_results(run)


if __name__ == '__main__':
    unittest.main()
