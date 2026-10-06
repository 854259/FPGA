"""New156 scope controls; no model/EDA and no repeated104 test suite."""
import ast,copy,hashlib,importlib.util,json,math
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import audit,factor_proof,metrics,pilot,preparation_inputs
ROOT=Path(__file__).resolve().parent
PARENT=Path('/workspace/team/runs/fpga_teammate/waveform_first_request_cp6_20261006_v4')
read=lambda p:json.loads(Path(p).read_bytes())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
s=importlib.util.spec_from_file_location('full_scope_original_score',ROOT/'upstream/raw_evidence/test_fixtures/score.py')
score=importlib.util.module_from_spec(s);s.loader.exec_module(score)
FLAGS=('generation_route_bound','input_bytes_bound','source_hashes_bound','solution_bytes_bound','native_execution_bound','original_model_replay_bound','waveform_request_factor_bound')
def material(gains=7):
 rows=[];provenance=[]
 for task,arm in metrics.order(metrics.TASKS):
  level=3 if task in metrics.GUARDS or (arm=='P' and task in metrics.TARGETS[:gains]) else metrics.reference['levels'][task]
  rows.append(dict(task=task,arm=arm,generation_route='model',verdict=dict(task_id=task,level=level,coefficient=metrics.COEFFICIENTS[level],tool_error=None,elapsed_s=1.),actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=10.,stage_generation_binding_verified=True,waveform_request_binding_verified=True,request_proof_sha256='a'*64,first_request_advice_changed=arm=='P' and task in metrics.ADVICE_TASKS))
  provenance.append(dict(task=task,arm=arm,generation_route='model',**{k:True for k in FLAGS}))
 return rows,provenance
def aggregate(rows):return metrics.aggregate(rows,metrics.TASKS,score)
def decide(rows,p):return metrics.decision(aggregate(rows),p,rows)
def row(rows,task,arm):return next(r for r in rows if r['task']==task and r['arm']==arm)
class CompleteWaveformScopeControls(unittest.TestCase):
 def test_actual156_inputs_original113_and_advice_admission_are_bound(self):
  scope=preparation_inputs.validate_kit(ROOT,Path('/workspace/team/tasks/autodl-rtl-kit/project'))
  self.assertEqual(scope['task_ids'],metrics.TASKS);self.assertEqual(scope['guard_tasks'],metrics.GUARDS)
  self.assertEqual(scope['advice_tasks'],metrics.ADVICE_TASKS)
  self.assertEqual(len(metrics.TASKS),156);self.assertEqual(len(metrics.GUARDS),113);self.assertEqual(scope['expected_samples'],312)
  self.assertEqual(len(metrics.ADVICE_TASKS),1)
  self.assertEqual(read(ROOT/'PRODUCTION_ADMISSION.json')['status_counts'],dict(supported=1,abstain=11,skip=144))
  self.assertEqual(len(metrics.order(metrics.TASKS)),312)
  with self.assertRaises(AssertionError):metrics.order(metrics.TASKS[:-1])
 def test_goal_requires120_and80_and_complete_source_provenance(self):
  rows,p=material();r=aggregate(rows)
  self.assertEqual(r['fully_correct_by_arm'],dict(C=113,P=120));self.assertGreaterEqual(r['coefficients']['P'],.8)
  self.assertTrue(decide(rows,p)['qualified_for_goal']);self.assertFalse(decide(rows,p)['adoption'])
  rows,p=material(6);self.assertEqual(aggregate(rows)['fully_correct_by_arm']['P'],119);self.assertFalse(decide(rows,p)['qualified_for_goal'])
  rows,p=material()
  #120 L3 can still have weighted score below .80; preserve denominator.
  for r in rows:
   if r['verdict']['level']!=3:r['verdict'].update(level=0,coefficient=0.)
  self.assertEqual(aggregate(rows)['fully_correct_by_arm']['P'],120);self.assertLess(aggregate(rows)['coefficients']['P'],.8);self.assertFalse(decide(rows,p)['qualified_for_goal'])
  for flag in FLAGS:
   rows,p=material();p[-1][flag]=False;self.assertFalse(decide(rows,p)['qualified_for_goal'])
  rows,p=material();p.pop()
  with self.assertRaises(AssertionError):decide(rows,p)
 def test_historical113_and_paired_grades_cannot_be_hidden_by_other_gains(self):
  rows,p=material(8);t=metrics.GUARDS[0]
  for arm in ('C','P'):row(rows,t,arm)['verdict'].update(level=1,coefficient=.2)
  r=aggregate(rows);self.assertFalse(r['guard_pass']);self.assertEqual(r['regressions'],[]);self.assertFalse(decide(rows,p)['qualified_for_goal'])
  rows,p=material(8);row(rows,t,'P')['verdict'].update(level=2,coefficient=.7)
  self.assertIn(t,aggregate(rows)['regressions']);self.assertFalse(decide(rows,p)['qualified_for_goal'])
 def test_historical_and_unchanged_cost_and_total_cost_are_separate_gates(self):
  for kind in ('historical_improvement','unchanged_grade','total_cost'):
   with self.subTest(kind=kind):
    rows,p=material(8);t=metrics.GUARDS[0] if kind=='historical_improvement' else metrics.TARGETS[-1] if kind=='unchanged_grade' else metrics.TARGETS[0]
    if kind=='historical_improvement':row(rows,t,'C')['verdict'].update(level=1,coefficient=.2)
    row(rows,t,'P').update(actual_model_requests=2,received_model_responses=2)
    if kind!='total_cost':row(rows,metrics.GUARDS[1],'C').update(actual_model_requests=2,received_model_responses=2)
    r=aggregate(rows)
    if kind!='total_cost':self.assertEqual(r['requests_by_arm']['C'],r['requests_by_arm']['P'])
    if kind=='historical_improvement':self.assertFalse(r['historically_correct_request_cost'])
    if kind=='unchanged_grade':self.assertFalse(r['unchanged_task_request_cost'])
    self.assertFalse(decide(rows,p)['qualified_for_goal'])
 def test_deadlines_missing_responses_invalid_budgets_and_routes_rejected(self):
  for key,value,raises in [('solve_elapsed_s',300.0001,True),('solve_elapsed_s',float('nan'),True),('solve_deadline_reached',True,False),('received_model_responses',0,False),('actual_model_requests',0,True),('actual_model_requests',3,True),('generation_route','mechanical_onehot',True),('stage_generation_binding_verified',False,True),('first_request_advice_changed',True,True)]:
   with self.subTest(key=key,value=value):
    rows,p=material();rows[0][key]=value
    if raises:
     with self.assertRaises(AssertionError):decide(rows,p)
    else:self.assertFalse(decide(rows,p)['qualified_for_goal'])
  rows,p=material();rows.pop()
  with self.assertRaises(AssertionError):decide(rows,p)
 def test_production_original_wire_judge_and_resource_lifecycle_unchanged(self):
  parent=read(ROOT/'QUALIFYING_CP6_SPEC.json')
  self.assertEqual(sha(PARENT/'RUN_SPEC.json'),sha(ROOT/'QUALIFYING_CP6_SPEC.json'))
  proof=read(ROOT/'DRAFT_SOURCE_SCOPE_PROOF.json')
  for name,h in proof['immutable_production'].items():self.assertEqual(sha(ROOT/name),h);self.assertEqual(h,parent['source_hashes'][name])
  self.assertEqual(factor_proof.verify(ROOT),read(ROOT/'SOURCE_FACTOR_PROOF.json'))
  functions=lambda f:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(f.read_bytes()).body if isinstance(n,ast.FunctionDef)}
  self.assertEqual(functions(ROOT/'pilot.py')['generation_binding'],functions(PARENT/'pilot.py')['generation_binding'])
  self.assertEqual(functions(ROOT/'audit.py')['model_requests'],functions(PARENT/'audit.py')['model_requests'])
  checks=[n for n in ast.walk(ast.parse((ROOT/'pilot.py').read_bytes())) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='check_resource' and any(k.arg=='first' and isinstance(k.value,ast.Constant) and k.value.value is True for k in n.keywords)]
  self.assertEqual(len(checks),1)
  self.assertNotIn('first=True',(ROOT/'worker.py').read_text())
  qualifying=read(ROOT/'QUALIFYING_CP6_AUDIT.json');self.assertTrue(qualifying['evidence_valid']);self.assertTrue(qualifying['qualified_for_new_full_regression']);self.assertEqual(qualifying['actual_model_requests'],18)
 def test_exact625_inventory_requires_all6516_anchor_paths_with_no_substitution(self):
  base=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json');external=read(ROOT/'EXTERNAL_SOURCE_MANIFEST.json')
  attacks=('valid','extra_bound_root','old_scope','wrong_sum','tampered_gate','missing_gate','changed_anchor','replaced_anchor','bad_external_sha')
  with tempfile.TemporaryDirectory(prefix='owner-wave-full-scope-') as td:
   root=Path(td);folder=root/'results/protected_source_checks';folder.mkdir(parents=True)
   for i in range(625):(folder/(str(i).zfill(3)+'.json')).touch()
   for attack in attacks:
    with self.subTest(attack=attack):
     groups=copy.deepcopy(base)
     if attack=='extra_bound_root':
      groups['groups']['NEW']=dict(cloud_root='/workspace/team/runs/fpga_owner/NEW_SCOPE_ONLY',spec_sha256='c'*64,source_hashes={'fresh.py':'d'*64});groups['source_assets']+=1
     spec=dict(protected_group_count=len(groups['groups']),protected_source_assets=groups['source_assets'],external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),expected_samples=312)
     if attack=='old_scope':spec.update(protected_group_count=80,protected_source_assets=5262)
     if attack in ('wrong_sum','changed_anchor','replaced_anchor'):
      name=next(iter(external['source_hashes']));parts=name.split('/');key='/'.join(parts[:2]);relative='/'.join(parts[2:]);item=groups['groups'][key]['source_hashes']
      if attack=='wrong_sum':item.pop(relative)
      if attack=='changed_anchor':item[relative]='0'*64
      if attack=='replaced_anchor':item['unrelated-same-count']=item.pop(relative)
     if attack=='bad_external_sha':spec['external_inventory_manifest_sha256']='0'*64
     if attack=='missing_gate':(folder/'624.json').unlink()
     expected={name:dict(spec_sha256=g['spec_sha256'],source_hashes=g['source_hashes'],source_assets=len(g['source_hashes'])) for name,g in groups['groups'].items()}
     visited=[]
     def mocked_read(path):
      if path.name=='EXTERNAL_SOURCE_MANIFEST.json':return external
      if path.name=='PROTECTED_GROUPS_CAPTURE.json':return groups
      i=int(path.stem);visited.append(i)
      return dict(index=i,schema='semantic_edge_protected_source_check_v1',verified=True,groups=expected,source_assets=6021 if attack=='tampered_gate' and i==624 else groups['source_assets'],model_calls=0,eda_calls=0)
     with patch.object(audit,'read',side_effect=mocked_read),patch.object(audit,'sha',return_value=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json')):
      if attack in ('valid','extra_bound_root'):
       audit.protected_receipts(root,spec);self.assertEqual(visited,list(range(625)))
      else:
       with self.assertRaises(AssertionError):audit.protected_receipts(root,spec)
     if attack=='missing_gate':(folder/'624.json').touch()
if __name__=='__main__':unittest.main(verbosity=2)
