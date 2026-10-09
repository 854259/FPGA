"""AMD-only delta controls for selecting the already-qualified peer queue."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import types
from unittest.mock import patch

import prepare_comparison as prepare

assert sys.platform=='linux' and sys.dont_write_bytecode
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results';OUT.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
manifest=read(ROOT/'SOURCE_MANIFEST.json')
assert all(sha(ROOT/n)==h for n,h in manifest.items())
qualified=Path('/workspace/team/runs/fpga_owner/semantic_review_pure_20261009_v1')
parent=Path('/workspace/team/runs/fpga_teammate/prompt_table_feedback_full156x5_20261008_v1')
kit=Path('/workspace/team/tasks/autodl-rtl-kit/project')
intake=read(qualified/'results/PROMPT_INTAKE.json')
selected=sorted(r['task'] for r in intake['rows'] if r['fallback_eligible'])[:2]
args=types.SimpleNamespace(out=ROOT/'prepared_delta_qualification_only',parent=parent,
    qualified=qualified,kit=kit,reader=ROOT/'comparison_result.py',
    reader_sha256=sha(ROOT/'comparison_result.py'),tasks=selected,
    selection_reason='New queue selection qualification only; no proposed or admitted experiment.',
    qualification_only_selection=True,queue_source=ROOT/'three_arm_queue_20261005.py')
protected={str(parent/n):sha(parent/n) for n in ('RUN_SPEC.json','PLAN.json','three_arm_queue_20261005.py')}
protected[str(args.queue_source)]=sha(args.queue_source)

def block(*a,**k):raise RuntimeError('No process/network/model/EDA in queue preparation delta')

reports=[]
with patch.object(socket,'socket',block),patch.object(subprocess,'Popen',block):
    prepare.prepare(args)
plan=read(args.out/'PLAN.json');spec=read(args.out/'RUN_SPEC.json')
assert not plan['execution_authorized'] and not plan['formal_adoption']
assert len(plan['rows'])==30 and plan['required_reserved_calls']==50
assert 'finite_judge' not in plan
assert spec['queue_source_binding']==dict(parent_sha256=protected[str(parent/'three_arm_queue_20261005.py')],
    selected_sha256=prepare.PEER_QUEUE_SHA,peer_PR=198,
    frozen_parent_unchanged=True,production_worker_unchanged=True)
assert sha(args.out/'three_arm_queue_20261005.py')==prepare.PEER_QUEUE_SHA
assert sha(args.out/'worker.py')==manifest['worker.py']
assert sha(args.out/'table_worker_original.py')==sha(parent/'worker.py')
assert (plan['solve_deadline_s'],plan['solve_supervisor_s'],plan['judge_supervisor_s'])==(300,310,360)
reports.append(dict(case='new_queue_bound_unadmitted_preparation',passed=True,outputs=30,
                    maximum_reserved_calls=50,model_worker_bytes_unchanged=True))

wrong=types.SimpleNamespace(**vars(args));wrong.out=ROOT/'bad_queue_must_not_exist'
wrong.queue_source=parent/'three_arm_queue_20261005.py'
with patch.object(socket,'socket',block),patch.object(subprocess,'Popen',block):
    try:prepare.prepare(wrong)
    except AssertionError:assert not wrong.out.exists()
    else:raise AssertionError('Unqualified queue accepted')
reports.append(dict(case='wrong_queue_sha_rejected_before_new_root',passed=True))

drift_source=ROOT/'own_drift_queue.py';shutil.copyfile(args.queue_source,drift_source)
drift=types.SimpleNamespace(**vars(args));drift.out=ROOT/'copy_drift_retained';drift.queue_source=drift_source
original_copy=shutil.copyfile

def copy_with_drift(src,dst,*a,**k):
    result=original_copy(src,dst,*a,**k)
    if Path(src)==drift_source:Path(dst).write_bytes(Path(dst).read_bytes()+b'\n# FAKE_COPY_DRIFT\n')
    return result

with patch.object(socket,'socket',block),patch.object(subprocess,'Popen',block),patch.object(shutil,'copyfile',copy_with_drift):
    try:prepare.prepare(drift)
    except AssertionError:
        assert (drift.out/'PREPARATION_INTENT.json').is_file()
        assert not (drift.out/'RUN_SPEC.json').exists() and not (drift.out/'PLAN.json').exists()
    else:raise AssertionError('Queue copy drift accepted')
reports.append(dict(case='copied_queue_drift_rejected_before_plan_and_retained',passed=True))
assert all(sha(p)==h for p,h in protected.items())
result=dict(schema='semantic_queue_preparation_delta_v1',passed=True,reports=reports,
    qualified_peer_queue_sha256=prepare.PEER_QUEUE_SHA,new_model_calls=0,new_eda_calls=0,
    new_fifo_tickets=0,old_protocol_controls_repeated=False,peer_prefix_controls_repeated=False,
    real_queue_execution_or_speed_measured=False,scored_experiment_selected=False,
    current_frozen_132_136_changed=False)
prepare.save(OUT/'RESULT.json',result)
print(json.dumps(result))
