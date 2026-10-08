"""AMD-only score-selection regression checks on the already frozen production metrics."""
import copy,importlib.util,sys,unittest
from pathlib import Path
ROOT=Path('/workspace/team/runs/fpga_owner/model_generated_fsm8_20261008_v1')
sys.path.insert(0,str(ROOT))
import metrics
s=importlib.util.spec_from_file_location('pinned_official_score','/workspace/team/tasks/autodl-rtl-kit/project/official_reference/selftest/score.py');score=importlib.util.module_from_spec(s);s.loader.exec_module(score)
TASKS=['Synthetic'+str(i) for i in range(8)]
def rows():
 out=[]
 for task,arm in metrics.order(TASKS):
  out.append(dict(task=task,arm=arm,verdict=dict(task_id=task,tool_error=None,level=3,coefficient=1.,elapsed_s=1.),actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=1.,generation_route='model',stage_generation_binding_verified=True,semantic_factor_binding_verified=True,request_proof_sha256='a'*64,first_system_changed=False,first_user_changed=arm=='P',repair_wires_unchanged=True,declaration_enabled=False,first_original_wire_sha256='b'*64,first_forwarded_wire_sha256=('c' if arm=='P' else 'b')*64))
 return out
def level(data,task,arm,n):
 r=next(r for r in data if r['task']==task and r['arm']==arm);r['verdict'].update(level=n,coefficient=metrics.COEFFICIENTS[n]);return r
class Selection(unittest.TestCase):
 def test_positive_total_with_regression_and_extra_request(self):
  data=rows();level(data,TASKS[0],'C',1);level(data,TASKS[1],'C',1);r=level(data,TASKS[2],'P',1);r.update(actual_model_requests=2,received_model_responses=2)
  result=metrics.aggregate(data,TASKS,[TASKS[2]],score)
  self.assertTrue(result['diagnostic_promising']);self.assertEqual(result['regressions'],[TASKS[2]]);self.assertFalse(result['historically_correct_request_cost']);self.assertFalse(result['local_historical_subset_pass']);self.assertFalse(result['goal_achieved'])
 def test_reject_lower_weighted_score_even_if_more_L3(self):
  data=rows();level(data,TASKS[0],'C',2);level(data,TASKS[1],'C',2);level(data,TASKS[2],'P',0)
  result=metrics.aggregate(data,TASKS,[],score);self.assertEqual(result['strict_new_L3_net'],1);self.assertFalse(result['diagnostic_promising'])
 def test_missing_or_nonmodel_or_unconfirmed(self):
  data=rows()
  with self.assertRaises(AssertionError):metrics.aggregate(data[:-1],TASKS,[],score)
  data[0]['generation_route']='mechanical'
  with self.assertRaises(AssertionError):metrics.aggregate(data,TASKS,[],score)
  data=rows();level(data,TASKS[0],'C',1);data[1]['received_model_responses']=0
  self.assertFalse(metrics.aggregate(data,TASKS,[],score)['diagnostic_promising'])
if __name__=='__main__':unittest.main()
