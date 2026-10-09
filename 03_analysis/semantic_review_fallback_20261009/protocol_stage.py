"""AMD-only preparation, cold binder and unchanged scorer eligibility controls."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import types
from unittest.mock import patch

import comparison_result as reader
import prepare_comparison as prepare
import official_baseline_scoring_20261005 as scoring
import official_baseline_arm_20261005 as official

assert sys.platform=='linux' and sys.dont_write_bytecode
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results';OUT.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
manifest=read(ROOT/'SOURCE_MANIFEST.json')
assert all(sha(ROOT/n)==h for n,h in manifest.items())
qualified=Path('/workspace/team/runs/fpga_owner/semantic_review_pure_20261009_v1')
parent=Path('/workspace/team/runs/fpga_teammate/prompt_table_feedback_full156x5_20261008_v1')
kit=Path('/workspace/team/tasks/autodl-rtl-kit/project')
original_files={}
for name in ('results/RESULT.json','results/PROMPT_INTAKE.json','SOURCE_MANIFEST.json','EXECUTION_RECEIPT.json'):
    original_files[str(qualified/name)]=sha(qualified/name)
original_files[str(parent/'RUN_SPEC.json')]=sha(parent/'RUN_SPEC.json')
def block(*a,**k):raise RuntimeError('No sockets/model/EDA in protocol qualification')

intake=read(qualified/'results/PROMPT_INTAKE.json')
eligible=sorted(r['task'] for r in intake['rows'] if r['fallback_eligible'])
ineligible=next(r['task'] for r in intake['rows'] if not r['fallback_eligible'])
args=types.SimpleNamespace(out=ROOT/'prepared_qualification_only',parent=parent,qualified=qualified,kit=kit,
    reader=ROOT/'comparison_result.py',reader_sha256=sha(ROOT/'comparison_result.py'),tasks=eligible[:2],
    selection_reason='Qualification-only lexically first two eligible prompts; not a proposed scored experiment.',
    qualification_only_selection=True)
reports=[]
with patch.object(socket,'socket',block):
    prepare.prepare(args)
plan=read(args.out/'PLAN.json');spec=read(args.out/'RUN_SPEC.json')
assert not plan['execution_authorized'] and not plan.get('formal_adoption')
assert len(plan['rows'])==30 and plan['required_reserved_calls']==plan['max_calls']==50
assert spec['inherited_worker_arms']==dict(A='P',P='P')
assert sha(args.out/'worker.py')==manifest['worker.py']
assert sha(args.out/'table_worker_original.py')==sha(parent/'worker.py')
reports.append(dict(control='actual_AMD_unadmitted_preparation',passed=True,outputs=30,max_calls=50,
                    scored_experiment_selected=False))

loader=importlib.util.spec_from_file_location('semantic_protocol_existing_queue',args.out/'three_arm_queue_20261005.py')
queue=importlib.util.module_from_spec(loader);loader.loader.exec_module(queue)
try:queue.run_plan(args.out/'PLAN.json',sha(args.out/'PLAN.json'),ROOT/'must_not_dispatch',ROOT/'unused_resource.json')
except AssertionError as error:assert 'Preparation plan cannot dispatch' in str(error)
else:raise AssertionError('unadmitted preparation dispatched')
assert not (ROOT/'must_not_dispatch').exists()
reports.append(dict(control='unadmitted_plan_cannot_dispatch',passed=True))

# New expected-inner-arm rule is qualified separately from unchanged scoring.
assert reader.expected_worker_arm(args.out,'A')==reader.expected_worker_arm(args.out,'P')=='P'
wrong_spec=ROOT/'reader_bad_spec';wrong_spec.mkdir()
for field,value in [('inherited_worker_arms',dict(A='C',P='P')),('parent_complete_table_spec_sha256','0'*64)]:
    bad=dict(spec);bad[field]=value;(wrong_spec/'RUN_SPEC.json').write_text(json.dumps(bad))
    try:reader.expected_worker_arm(wrong_spec,'A')
    except AssertionError:pass
    else:raise AssertionError('invalid inherited-arm metadata accepted')
reports.append(dict(control='reader_new_role_and_two_invalid_metadata_rejections',passed=True))
legacy=ROOT/'reader_old_spec';legacy.mkdir();(legacy/'RUN_SPEC.json').write_text(json.dumps(dict(schema='prompt_table_feedback_model_comparison_v1')))
assert reader.expected_worker_arm(legacy,'A')=='C' and reader.expected_worker_arm(legacy,'P')=='P'
reports.append(dict(control='other_factor_reader_role_unchanged',passed=True))

original_reader=Path('/workspace/team/runs/fpga_owner/structural_feedback_integration_controls_20261008_v1/comparison_result.py')
assert sha(original_reader)=='f270b078e4f96b93dab231d26dec8af24d53bc23a69123ada4679fe6b609ca39'
def function_tree(path,name):
    return ast.dump(next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
assert function_tree(original_reader,'summarize')==function_tree(ROOT/'comparison_result.py','summarize')
reports.append(dict(control='official_summary_score_time_diagnostics_unchanged_AST',passed=True))

rejected=0
for kind in ('duplicate','ineligible','foreign_root','bad_reader_hash'):
    test=types.SimpleNamespace(**vars(args));test.out=ROOT/('rejected_'+kind)
    if kind=='duplicate':test.tasks=[eligible[0],eligible[0]]
    if kind=='ineligible':test.tasks=[ineligible]
    if kind=='foreign_root':test.out=Path('/tmp/semantic_rejected_foreign_owned_root')
    if kind=='bad_reader_hash':test.reader_sha256='0'*64
    assert not test.out.exists()
    try:prepare.prepare(test)
    except AssertionError:rejected+=1
    else:raise AssertionError('bad preparation accepted '+kind)
    assert not test.out.exists()
assert rejected==4
reports.append(dict(control='four_preparation_rejections_before_creating_run',passed=True))

# Reuse original qualification mocks on owned copies. This projection changes
# only the mock model-name field to the real protocol alias and rebinds request
# hashes. Replies remain explicitly synthetic. Never call them actual inference.
bindings=[]
for label,arm in [('unsupported_control','A'),('unsupported_candidate','P'),
                  ('compile_failure_control','A'),('compile_failure_candidate','P')]:
    old=qualified/'results'/label/'worker';case=OUT/('mock_'+label);case.mkdir()
    solve=case/'solve';shutil.copytree(old,solve)
    for p in old.rglob('*'):
        if p.is_file():original_files[str(p)]=sha(p)
    task=case/'task';shutil.copytree(old/'prompt_only',task)
    original_journal=read(solve/'requests.json');requests=[dict(r) for r in original_journal]
    before_after=[]
    for row in requests:
        p=solve/'requests'/str(row['index'])/'request.json';body=read(p);original_hash=sha(p)
        old_model=body['model'];assert old_model=='explicit-mock-model';body['model']=official.MODEL
        p.write_text(json.dumps(body,indent=2)+'\n');row['request_sha256']=sha(p)
        before_after.append(dict(original_mock_request_sha256=original_hash,derived_request_sha256=sha(p),
                                 only_model_parameter_changed=True,old_model=old_model,new_model=official.MODEL))
    (solve/'requests.json').write_text(json.dumps(requests,indent=2)+'\n')
    binding=scoring.eligible(solve,task,arm,model_source=ROOT)
    assert binding['arm']==arm and binding['worker_arm']=='P'
    model=binding['model_binding']
    assert model['outer_arm']==arm and model['inherited_complete_table_candidate'] is True
    assert model['model_generated_rtl_bound'] and model['worker_arm']==reader.expected_worker_arm(args.out,arm)
    assert model['actual_model_responses']==len(requests)==binding['client_request_attempts']
    assert not binding.get('generation_binding')
    flow=dict(label=label,outer_arm=arm,inherited_worker_arm='P',mock_only=True,
              source_mock_projection=before_after,cold_CLI_binder_verified=True,
              unchanged_external_scorer_eligibility_verified=True,bound=binding,
              real_model_calls=0,real_eda_calls=0)
    (case/'MOCK_PROTOCOL_RECEIPT.json').write_text(json.dumps(flow,indent=2)+'\n');bindings.append(flow)
    if arm=='A':
        assert model['worker_arm']!='C'
        try:scoring.eligible(solve,task,'P',model_source=ROOT)
        except subprocess.CalledProcessError:pass
        else:raise AssertionError('wrong outer-arm eligibility accepted')
reports.append(dict(control='four_cold_binders_and_unchanged_scorer_eligibility',passed=True,
                    cold_valid_binders=4,wrong_outer_arm_rejections=2,real_model_calls=0))

assert all(sha(p)==h for p,h in original_files.items())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
result=dict(passed=True,reports=reports,controls=len(reports),original_qualification_sources_held=True,
    current132_source_spec_held=True,public_new_sources_held=True,
    prepared_only_fixture=dict(root=str(args.out),outputs=30,max_calls=50,execution_authorized=False,
                              spec_sha256=sha(args.out/'RUN_SPEC.json'),plan_sha256=sha(args.out/'PLAN.json')),
    derived_mock_bindings=4,cold_CLI_binders=4,wrong_outer_arm_rejections=2,prepare_rejections=4,
    original_mock_files_sha256=original_files,
    original_scorer_and_summary_unchanged=True,full_terminal_audit_not_executed=True,
    selected_scored_experiment=False,new_model_calls=0,new_eda_calls=0,new_fifo_tickets=0,
    real_model_benefit_and_wall_time_pending=True,score_measured=False,adoption=False)
(OUT/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('original_mock_files_sha256','reports')}))
