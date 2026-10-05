import tempfile
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import worker
import edge_dispatch
import edge_feedback
from test_edge_integration import material


class Boundaries(unittest.TestCase):
    def check(self, status='fail', kind='semantic_mismatch', log=None, code=None):
        prompt = material()
        c = edge_dispatch.parse(prompt)
        row = next(o for o in c['observations'] if o['expected'])
        line = f"EDGE_FIRST step={row['step']} phase={row['phase']} expected={row['expected']:x} observed=0\n"
        calls = []
        def oracle(test, source, out):
            calls.append(test)
            out.mkdir(parents=True)
            (out/'xsim.log').write_text(line if log is None else log, encoding='utf-8')
            return dict(status=status, failure_kind=kind, checks=c['checks'], mismatches=1)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            paired = types.SimpleNamespace(oracle=oracle)
            with patch.object(worker, 'ROOT', out):
                feedback = worker.functional_feedback(prompt, code or 'module TopModule;endmodule',
                                                      out, 0, paired, 'fixture', candidate=True)
            return feedback, calls

    def test_native_environment_failure_never_fabricates_feedback(self):
        with self.assertRaises(RuntimeError):
            self.check(kind='environment_error')

    def test_missing_or_fabricated_counterexample_rejected(self):
        for line in ['', 'EDGE_FIRST step=0 phase=stable expected=ff observed=0\n',
                     'EDGE_FIRST step=3 phase=positive expected=ff observed=ff\n']:
            with self.assertRaises((ValueError,AssertionError)):
                self.check(log=line)

    def test_file_access_or_include_abstains_before_probe(self):
        for code in ['module TopModule; initial $display("x");endmodule',
                     '`include "x.sv"\nmodule TopModule;endmodule']:
            feedback, calls = self.check(code=code)
            self.assertEqual((feedback, calls), ('', []))

    def test_complete_semantics_and_interface_remain_required(self):
        for prompt in [material()+' Extra reset is required.',
                       material().replace('(8 bits)', '(9 bits)', 1),
                       material().replace('bit of pulse', 'bit of PULSE')]:
            self.assertEqual(edge_dispatch.parse(prompt)['status'], 'abstain')

    def test_feedback_rejects_contract_point_disagreement(self):
        c = edge_dispatch.parse(material())
        row = next(o for o in c['observations'] if o['expected'])
        p = dict(row, output='pulse', observed_hex='0')
        r = dict(failure_kind='semantic_mismatch', checks=c['checks'], mismatches=1)
        text = edge_feedback.render(c, r, p)
        self.assertIn('earlier in=', text)
        self.assertNotIn('assign ', text)
        self.assertNotIn('always ', text)
        p['input'] ^= 1
        with self.assertRaises(AssertionError):
            edge_feedback.render(c, r, p)


if __name__ == '__main__':
    unittest.main()
