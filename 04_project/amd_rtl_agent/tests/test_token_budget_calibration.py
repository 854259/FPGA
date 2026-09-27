"""Independent arithmetic and experiment-boundary regression checks (no GPU)."""
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calibration', ROOT/'tools/calibrate_token_budget.py')
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)


class CalibrationTests(unittest.TestCase):
    def test_arithmetic_oracles(self):
        for a in range(-32768, 32768):
            want = max(-512, min(511, round(a/8))) & 0xffffffff
            self.assertEqual(cal.expected('rounded_fixed', a, 0, [0,0]), want)
        for a in range(1,251):
            self.assertEqual((a*cal.expected('prime_inverse', a, 0, [0,0])) % 251, 1)
        rng = random.Random(991)
        for _ in range(300):
            x,y,z = [rng.randrange(256) for _ in range(3)]
            mul = lambda a,b: cal.expected('gf_product',a,b,[0,0])
            self.assertEqual(mul(x,y),mul(y,x))
            self.assertEqual(mul(x,y^z),mul(x,y)^mul(x,z))
            self.assertEqual(mul(x,1),x)
        self.assertEqual(cal.expected('complex_product', 0x8080, 0x8080, [0,0]), 0x80000000)
        self.assertEqual(cal.expected('associative_lookup', 0x07070707, 0x0c07, [0,0]), 258)
        self.assertEqual(cal.expected('median_five', sum(v<<(6*i) for i,v in enumerate([2,63,2,0,3])), 0, [0,0]), 2)
        for x in range(65536):
            y = cal.expected('matrix_transpose', x, 0, [0,0])
            self.assertEqual(cal.expected('matrix_transpose', y, 0, [0,0]), x)

    def test_history_clock_contract(self):
        h=[0,0]
        self.assertEqual(cal.expected('history_filter', 5,0,h),15)
        self.assertEqual(cal.expected('history_filter', 7,0,h),46)
        self.assertEqual(cal.expected('history_filter', 255,0,h),22)
        rows=cal.make_vectors('history_filter',20260930)
        for i,row in enumerate(rows):
            if row[0]:
                self.assertEqual(row[-2:],[0,0])
            elif not row[1]:
                self.assertEqual(row[-2],rows[i-1][-2])
                self.assertEqual(row[-1],0)

    def test_private_material_not_in_request(self):
        body=cal.request_body('frozen system','public specification',cal.PROFILES[1],'local')
        self.assertEqual(set(body),{'model','messages','temperature','top_p','max_tokens','thinking_token_budget'})
        self.assertEqual([m['content'] for m in body['messages']],['frozen system','public specification'])
        self.assertNotIn('thinking_token_budget',cal.request_body('s','p',cal.PROFILES[0],'m'))

    def test_preserves_control_when_timing_difference_is_small(self):
        rows=[dict(profile=p['name'],functional_pass=True,blank=False,model_seconds=100-i)
              for i,p in enumerate(cal.PROFILES) for _ in range(4)]
        self.assertEqual(cal.choose(rows)[0],'control')
        for r in rows:
            if r['profile']==cal.PROFILES[1]['name']:
                r['model_seconds']=75
        self.assertEqual(cal.choose(rows)[0],cal.PROFILES[1]['name'])
        rows[4]['functional_pass']=False
        self.assertEqual(cal.choose(rows)[0],'control')
        with self.assertRaises(ValueError):
            cal.choose(rows[:-1])

    def test_fixed_plan_and_no_calls_before_predecessor_completion(self):
        with tempfile.TemporaryDirectory(prefix='rtl-budget-test-') as td:
            root=Path(td); out=root/'experiment'; skill=root/'skill.txt'
            skill.write_text('frozen skill',encoding='utf-8')
            cal.prepare(out,skill)
            self.assertEqual(len(cal.verify_plan(out)['cases']),8)
            prior=root/'prior';(prior/'results').mkdir(parents=True)
            cal.save(prior/'experiment.json',dict(complete=False))
            with patch.object(cal.urllib.request,'urlopen') as request:
                with self.assertRaises(TimeoutError):
                    cal.execute(out,prior,'http://localhost/v1','m',root,-1)
                request.assert_not_called()
            cal.save(prior/'experiment.json',dict(complete=True))
            self.assertFalse(cal.predecessor_ready(prior))
            (prior/'graded_summary.json').write_text('{}')
            for i in range(312):
                (prior/'results'/f'{i}.json').write_text('{}')
            self.assertTrue(cal.predecessor_ready(prior))
            (out/'system.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen input'):
                cal.verify_plan(out)

    def test_extraction_matches_official_helper(self):
        import sys
        sys.path.insert(0,str(ROOT/'submission'))
        try:
            import baseline
            cases=['', '  ', 'module TopModule; endmodule',
                   'explanation\n```sv\nmodule TopModule; endmodule\n```',
                   'module Other; endmodule\nmodule TopModule; endmodule']
            for text in cases:
                self.assertEqual(cal.extract(text),baseline.extract(text,'rtl'))
        finally:
            sys.path.pop(0)

    def test_failure_marker_overrides_late_success_with_zero_exit(self):
        # Actual xsim can continue after $fatal and reach the final PASS marker.
        # Exercise simulate's real verdict path, including successful tool exits.
        with tempfile.TemporaryDirectory(prefix='rtl-budget-test-') as td:
            def replay(args, cwd, timeout, log):
                log.write_text('CALIBRATION_FAIL cycle=2\nCALIBRATION_PASS\n'
                               if log.name=='simulate.log' else 'tool completed\n')
                return 0
            with patch.object(cal,'run_tool',side_effect=replay):
                result=cal.simulate(cal.reference('gf_product'),
                                    cal.make_vectors('gf_product',1),
                                    Path(td)/'replay',Path(td))
            self.assertFalse(result['functional_pass'])


if __name__=='__main__':
    unittest.main()
