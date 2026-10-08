"""Only new dependency-identity/path controls; no old suite re-execution."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import composition,table_synthesis,onehot_producer,timer_producer
import generation_binding as proof
ROOT=Path(__file__).parent
providers=[('table',table_synthesis),('onehot',onehot_producer),('timer',timer_producer)]
f=[v for v in proof.read(ROOT/'RETAINED_INPUTS_PRIVATE.json') if v['label']=='table'][0]
w=ROOT/'NEW_DEPENDENCY_METADATA';(w/'prompt_only').mkdir(parents=True)
(w/'prompt_only/prompt.txt').write_bytes(f['prompt'].encode());(w/'prompt_only/interface.txt').write_bytes(f['interface'].encode())
r=composition.parent(f['prompt'],f['interface'])
route=dict(schema='table_parent_history_extension_generation_route_v1',route='mechanical_table',outer_arm='C',prompt_sha256=proof.digest(f['prompt']),interface_sha256=proof.digest(f['interface']),interface_present=True,baseline_worker_sha256=proof.sha(ROOT/'baseline_worker.py'),synthesis_source_sha256=proof.sha(ROOT/'composition.py'),generated_solution_sha256=r['rtl_sha256'])
for n,j in [('generation_route.json',route),('synthesis_receipt.json',r)]: (w/n).write_text(json.dumps(j))
def bind():return proof.bound_route(w,ROOT,'C',f['prompt'],f['interface'],True,composition,providers)
assert bind()==(route,r)
rejected=[]
for name in ['table_synthesis','onehot_producer','timer_producer']:
 real=getattr(composition,name)
 with patch.object(composition,name,SimpleNamespace(__file__=real.__file__)):
  try:bind()
  except AssertionError:rejected.append(name+'_object')
  else:raise AssertionError('Detached provider accepted')
for obj,name in [(composition.selector,'selector'),(table_synthesis.contract,'contract')]:
 with patch.object(obj,'__file__',str(ROOT/'OLD_DIRECTORY'/Path(obj.__file__).name)):
  try:bind()
  except AssertionError:rejected.append(name+'_foreign_path')
  else:raise AssertionError('Foreign imported dependency accepted')
assert len(rejected)==5
assert all(proof.sha(ROOT/n)==h for n,h in proof.read(ROOT/'SOURCE_MANIFEST.json').items())
result=dict(passed=True,positive_contexts=1,rejection_contexts=5,rejections=rejected,only_new_module_identity_guard_tested=True,old_17_worker_6_route_9_rejection_results_reused_not_rerun=True,new_worker_model_EDA_FIFO_calls=0,new_score_or_native_qualification=False)
(ROOT/'ACTUAL_DEPENDENCY_GUARD_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
