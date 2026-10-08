"""New checker boundaries only; no old parser/native suites or model calls."""
import unittest

import onehot_feedback as f
from native_material_fixture import fixture


def contract():
    return dict(module='TopModule', input='pin', state='active', next_state='future',
        outputs=['flag0','flag1'], labels=['Node0','Node1','Node2'],
        transitions=[[0,0,1],[0,1,2],[1,0,2],[1,1,0],[2,0,0],[2,1,1]],
        output_masks=[[1,0],[0,1],[1,1]])


def log(rows=(), bad=0, checks=16, task='Synthetic'):
    return '\n'.join([*rows,f'R2_PROBE_RESULT task={task} checks={checks} mismatches={bad}'])+'\n'


class Controls(unittest.TestCase):
    def test_reference_zero_single_and_multihot(self):
        c=contract()
        self.assertEqual(f.expected(c,0,0),'00000')
        self.assertEqual(f.expected(c,1,0),'01010')
        self.assertEqual(f.expected(c,1,1),'10010')
        self.assertEqual(f.expected(c,3,0),'11011')
        self.assertEqual(f.expected(c,3,1),'10111')
        self.assertEqual(f.expected(c,7,0),'11111')
        self.assertEqual(f.expected(c,7,1),'11111')

    def test_combined_runtime_prompt_boundary(self):
        p,i,_=fixture(n=3,module='TopModule')
        self.assertEqual(f.parse(p+'\n\nInterface:\n'+i),f.parse(p))
        self.assertIsNone(f.parse(p+'\n\nInterface:\n'+i+'\n\nInterface:\n'+i))

    def test_unknown_requirement_abstains(self):
        p,_,_=fixture(n=3,module='TopModule')
        self.assertIsNone(f.parse(p+'Additional requirement: use priority for simultaneous states.'))

    def test_compact_exhaustive_tb(self):
        tb=f.render_tb(contract(),'Synthetic')
        self.assertIn('_oh_mask<8',tb)
        self.assertIn('_oh_value<2',tb)
        self.assertIn('!==',tb)
        self.assertIn('if(_oh_state[0] && _oh_pin==1\'b0)',tb)
        self.assertIn('TopModule _oh_dut',tb)
        self.assertNotIn('module TopModule',tb)

    def test_largest_parser_width_tb_is_bounded_text(self):
        p,_,_=fixture(n=16,module='TopModule')
        c=f.parse(p);self.assertIsNotNone(c)
        tb=f.render_tb(c,'Synthetic')
        self.assertIn('_oh_mask<65536',tb)
        self.assertLess(len(tb),10000)

    def test_task_label_is_only_measurement_identity(self):
        self.assertEqual(f.render_tb(contract(),'Other').replace('Other','Synthetic'),
                         f.render_tb(contract(),'Synthetic'))
        with self.assertRaises(ValueError):f.render_tb(contract(),'../escape')

    def test_zero_mismatch_summary(self):
        self.assertEqual(f.measured_points(log(),contract(),'Synthetic',0),[])

    def test_measured_two_points_and_width_explicit_feedback(self):
        rows=['ONEHOT_FIRST input=0 state=000 observed=00001',
              'ONEHOT_FIRST input=1 state=001 observed=10011']
        points=f.measured_points(log(rows,2),contract(),'Synthetic',2)
        self.assertEqual([p['expected'] for p in points],['00000','10010'])
        text=f.feedback_text(contract(),2,points)
        self.assertIn("state=3'b001",text)
        self.assertIn("expected=5'b10010",text)
        self.assertNotIn('assign ',text)

    def test_unknown_measured_output_counts_as_wrong(self):
        point=f.measured_points(log(['ONEHOT_FIRST input=0 state=000 observed=xxXXX'],1),
                                contract(),'Synthetic',1)[0]
        self.assertEqual(point['observed'],'xxxxx')

    def test_summary_counter_count_task_and_duplicate_rejected(self):
        for text,bad in [(log(bad=1),0),(log(checks=15),0),(log(task='Other'),0),
                         (log()+log(),0),(log(bad=17),17),(log(bad=0),True)]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):f.measured_points(text,contract(),'Synthetic',bad)

    def test_wrong_width_and_non_counterexample_rejected(self):
        for row in ['ONEHOT_FIRST input=0 state=000 observed=0001',
                    'ONEHOT_FIRST input=0 state=00x observed=00001',
                    'ONEHOT_FIRST input=0 state=000 observed=00000']:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):f.measured_points(log([row],1),contract(),'Synthetic',1)

    def test_missing_extra_duplicate_and_unordered_points_rejected(self):
        a='ONEHOT_FIRST input=0 state=000 observed=00001'
        b='ONEHOT_FIRST input=1 state=001 observed=10011'
        for rows,bad in [([a],2),([a,b],1),([a,a],2),([b,a],2)]:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):f.measured_points(log(rows,bad),contract(),'Synthetic',bad)

    def test_eight_points_retained_with_larger_mismatch_total(self):
        rows=[f'ONEHOT_FIRST input={j%2} state={j//2:03b} observed=xxxxx' for j in range(8)]
        self.assertEqual(len(f.measured_points(log(rows,10),contract(),'Synthetic',10)),8)
        with self.assertRaises(ValueError):f.measured_points(log(rows[:7],10),contract(),'Synthetic',10)

    def test_out_of_domain_measured_inputs_rejected(self):
        for state,pin in [(-1,0),(8,0),(True,0),(0,2),(0,False)]:
            with self.subTest(state=state,pin=pin):
                with self.assertRaises(ValueError):f.expected(contract(),state,pin)
