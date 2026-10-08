"""Source-bound reuse of actual full-worker controls and finite native121; no replay."""
import hashlib,json,zipfile
from pathlib import Path,PurePosixPath
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
digest=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
PIPELINE_SHA='3d79e4a48b3cd4b0ff425a562a859439d3cace0f58a863778d5c264b2b839bc7'
NATIVE_SHA='3bdb47a5241a5af517193627e03a74f750b9875a4faf8f286841e9a06a5cc1fc'
CORE=['baseline_worker.py','worker.py','package/agent/map_runtime.py','internal_wire_hook.py','internal_wire_repair.py','agent_extract_boundary.py','wire_capture.py','request_proof.py','declaration_replay.py','core_source_proof.py','DECLARATION_SOURCE_DELTAS.json']
def archive(path,expected):
 assert sha(path)==expected
 with zipfile.ZipFile(path) as z:
  names=z.namelist();assert len(names)==len(set(names))
  assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and not n.endswith('/') for n in names)
  raw={n:z.read(n) for n in names}
 manifest=json.loads(raw['ARCHIVE_MANIFEST.json']);assert set(raw)==set(manifest['files'])|{'ARCHIVE_MANIFEST.json'}
 for n,h in manifest['files'].items():assert digest(raw[n])==h,n
 return raw
def process(p,rc=0):
 assert p['returncode']==rc and p['exec_confirmed'] and p['normal_completion'] and p['leader_reaped']
 assert not p['remaining_group'] and not p['timeout'] and not p.get('exec_error') and not p.get('error')
def verify(root,live=False):
 root=Path(root);assert type(live) is bool
 pipeline=archive(root/'QUALIFYING_FACTOR/PIPELINE4.zip',PIPELINE_SHA);assert len(pipeline)==175
 result=json.loads(pipeline['run/ACTUAL_PIPELINE_RESULT.json']);receipt=json.loads(pipeline['admin/ACTUAL_PURE_RECEIPT.json'])
 assert result['passed'] and result['contexts']==4 and result['mutation_checks']==18
 assert result['HTTP_and_compiler_simulated'] and result['activity_intercepted'] and result['real_model_calls']==result['real_EDA_calls']==0
 process(receipt['process']);assert receipt['process']['cap_s']==60
 assert digest(pipeline['admin/ACTUAL_PURE_PROCESS/stdout.bin'])==receipt['process']['stdout_sha256']
 assert digest(pipeline['run/ACTUAL_PIPELINE_RESULT.json'])==receipt['result_sha256']
 assert receipt['passed'] and receipt['source_held'] and receipt['model_unchanged'] and receipt['primary_two_files_unchanged']
 for n in CORE:assert sha(root/n)==digest(pipeline['run/'+n]),n
 native=archive(root/'QUALIFYING_FACTOR/NATIVE121.zip',NATIVE_SHA);assert len(native)==208
 native_spec=json.loads(native['RUN_SPEC.json'])
 assert digest(native['RUN_SPEC.json'])=='8c08c1e8f080c03e3d8adda19ee326cc9e436727c0f7469760475b501ca7d3e9'
 for n,h in native_spec['source_hashes'].items():assert digest(native[n])==h,n
 for n in ('internal_wire_repair.py','internal_wire_hook.py','agent_extract_boundary.py','baseline_worker.py','package/agent/map_runtime.py'):assert sha(root/n)==digest(native[n]),n
 summary=json.loads(native['results/summary.json']);stage=json.loads(native['ACTUAL_STAGE_PROCESS/COMPLETE.json']);guard=json.loads(native['guard/status.json'])
 assert summary['complete'] and summary['passed'] and summary['native_commands']==11 and summary['physical_protection_receipts']==23 and summary['finite_observations']==69
 assert summary['reused_original118_observations']==2053 and summary['prior118_remains_failed'] and summary['model_calls']==summary['scoring_calls']==0
 process(stage);assert stage['cap_s']==360
 assert all(guard[k] for k in ('complete','passed','model_unchanged','protected_files_unchanged','own_slot_released')) and guard['stage_rc']==0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
 for command in summary['commands']:
  process(command['record'],1 if command['label']=='C_compile' else 0)
 return dict(schema='internal_declaration_actual_factor_control_proof_v1',actual_pipeline_contexts=4,actual_mutation_rejections=18,pipeline_archive_sha256=PIPELINE_SHA,native_archive_sha256=NATIVE_SHA,
  native_new_commands=11,native_new_finite_observations=69,old_observations_source_reused=2053,original118_failure_preserved=True,
  qualified_core_source_hashes={n:sha(root/n) for n in CORE},new_tests_run=0,new_model_calls=0,new_eda_calls=0,
  native_scope='Finite authored structures/binary clocks/finite four-state data only; no all-parameter/all-clock proof',new_score=False)
