"""AMD-only, non-dispatching preparation using the existing A/P/B queue."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

PARENT_SPEC_SHA='b499f6c16fa91868ca7ba60a168929204f02d5b0e164f5ade776a65983aa5c5d'
QUALIFIED_RESULT_SHA='912c54882b82ca5dc69dc9e966c4226a51777269f1843843b70a84e41b507c71'
SCHEMA='unsupported_clocked_semantic_review_model_comparison_v1'
PEER_QUEUE_SHA='4290944199cddd54c6a08a55d1a62f0d81d7946f144ccba6fb98ca14619971e1'
OVERLAY=('semantic_review.py','semantic_feedback.py','worker.py','interface_feedback.py',
         'agent_extract_boundary.py','reserved_keywords.py','INHERITED_SOURCE_BINDING.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2);f.write('\n')


def prepare(args):
    root,parent,qualified,kit=map(Path.resolve,(args.out,args.parent,args.qualified,args.kit))
    own=Path('/workspace/team/runs/fpga_owner').resolve()
    assert not root.exists() and root.is_relative_to(own) and root!=own
    assert all(not root.is_relative_to(p) and not p.is_relative_to(root) for p in (parent,qualified,kit))
    assert sha(parent/'RUN_SPEC.json')==PARENT_SPEC_SHA
    parent_spec=read(parent/'RUN_SPEC.json')
    assert sha(qualified/'results/RESULT.json')==QUALIFIED_RESULT_SHA
    evidence=read(qualified/'results/RESULT.json');receipt=read(qualified/'EXECUTION_RECEIPT.json')
    assert evidence['passed'] and evidence['actual_frozen_worker_mock_flows']==11 and evidence['eligible']==49
    assert evidence['new_model_calls']==evidence['new_eda_calls']==evidence['new_fifo_tickets']==0
    assert receipt['passed'] and receipt['protected_held'] and receipt['result_sha256']==QUALIFIED_RESULT_SHA
    qualified_sources=read(qualified/'SOURCE_MANIFEST.json')
    assert all(sha(qualified/n)==h for n,h in qualified_sources.items())
    intake=read(qualified/'results/PROMPT_INTAKE.json')
    assert len(intake['rows'])==156 and len({r['task'] for r in intake['rows']})==156
    rows={r['task']:r for r in intake['rows']}
    selected=list(args.tasks)
    assert selected and len(set(selected))==len(selected) and len(selected)<=49
    assert all(Path(t).name==t and t not in ('.','..') and rows[t]['fallback_eligible'] for t in selected)
    parent_hashes=dict(parent_spec['source_hashes'])
    assert all(sha(parent/n)==h for n,h in parent_hashes.items())
    assert all(sha(parent/'dependencies'/n)==h for n,h in parent_spec['dependency_hashes'].items())
    for n in OVERLAY:
        assert sha(Path(__file__).parent/n)==qualified_sources[n]
    assert sha(args.reader)==args.reader_sha256
    selected_queue=getattr(args,'queue_source',None)
    if selected_queue is not None:
        selected_queue=Path(selected_queue).resolve()
        assert selected_queue.is_file() and sha(selected_queue)==PEER_QUEUE_SHA
    root.mkdir()
    save(root/'PREPARATION_INTENT.json',dict(model_max=0,eda_max=0,fifo_max=0,execution_authorized=False,
        parent_spec_sha256=PARENT_SPEC_SHA,qualification_result_sha256=QUALIFIED_RESULT_SHA,
        tasks=selected,selection_reason=args.selection_reason))
    sources={}
    for n,h in parent_hashes.items():
        target_name='table_worker_original.py' if n=='worker.py' else n
        target=root/target_name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(parent/n,target);sources[target_name]=h
    for n in OVERLAY:
        shutil.copyfile(Path(__file__).parent/n,root/n);sources[n]=sha(root/n)
    if selected_queue is not None:
        shutil.copyfile(selected_queue,root/'three_arm_queue_20261005.py')
        assert sha(root/'three_arm_queue_20261005.py')==sha(selected_queue)==PEER_QUEUE_SHA
        sources['three_arm_queue_20261005.py']=PEER_QUEUE_SHA
    for name,path in [('prepare_comparison.py',Path(__file__)),('comparison_result.py',args.reader)]:
        assert name not in sources
        shutil.copyfile(path,root/name);sources[name]=sha(root/name)
    spec=dict(parent_spec,schema=SCHEMA,identity=root.name,cloud_root=str(root),
        dependencies_cloud=str(root/'dependencies'),source_hashes=sources,
        parent_complete_table_spec_sha256=PARENT_SPEC_SHA,qualification_result_sha256=QUALIFIED_RESULT_SHA,
        qualification_source_hashes={n:qualified_sources[n] for n in OVERLAY},
        inherited_worker_arms=dict(A='P',P='P'),
        queue_source_binding=dict(parent_sha256=parent_hashes['three_arm_queue_20261005.py'],
            selected_sha256=sources['three_arm_queue_20261005.py'],
            peer_PR=198 if selected_queue is not None else None,
            frozen_parent_unchanged=True,production_worker_unchanged=True),
        factor='One unverified semantic review after first compile-pass and unsupported clocked checks',
        arm_definitions=dict(A='Unchanged132 complete-table P candidate',
            P='Same complete-table candidate plus unsupported-clocked semantic review',B='Untouched official baseline'))
    save(root/'RUN_SPEC.json',spec)
    tasks=[]
    for task in selected:
        source=kit/'bench/tasks_veval'/task;target=root/'inputs'/task
        assert source.is_dir() and not any(p.is_symlink() for p in source.rglob('*'))
        target.mkdir(parents=True);hashes={}
        for name in ('prompt.txt','interface.txt'):
            if not (source/name).is_file():continue
            raw_key='kit/bench/tasks_veval/'+task+'/'+name
            assert sha(source/name)==intake['original_file_hashes'][raw_key]
            assert hashlib.sha256((source/name).read_text(encoding='utf-8').encode()).hexdigest()==rows[task][name.replace('.txt','')+'_sha256']
            shutil.copyfile(source/name,target/name);hashes[name]=sha(target/name)
        assert 'prompt.txt' in hashes
        tasks.append(dict(dataset='verilogeval_seen_development',task=task,family='clocked_contract_family_dependence_unknown',
            use='development',task_dir=str(target),hashes=hashes,evaluator_dir=str(source),
            evaluator_hashes={p.name:sha(p) for p in source.iterdir() if p.is_file()}))
    sys.path.insert(0,str(root))
    loader=importlib.util.spec_from_file_location('semantic_existing_queue',root/'three_arm_queue_20261005.py')
    queue=importlib.util.module_from_spec(loader);loader.loader.exec_module(queue)
    bindings=dict(root=str(root),model_feedback=True,files={
        **{str(root/n):h for n,h in sources.items()},str(root/'RUN_SPEC.json'):sha(root/'RUN_SPEC.json')})
    calls=25*len(tasks)
    plan=queue.build_plan(tasks,5,bindings,root/'official_baseline_arm_20261005.py',kit,calls,670*15*len(tasks))
    plan.update(execution_authorized=False,model_generated_rtl_only=True,full156=False,formal_adoption=False,
        full_goal_complete=False,independent_unseen=0,arm_definitions=spec['arm_definitions'],factor=spec['factor'],
        qualification_result_sha256=QUALIFIED_RESULT_SHA,selection_reason=args.selection_reason,
        data_selection='Fixed tasks selected before any calls; no production task-ID answer routing',
        selection_policy='Official score components; missing constants unknown; costs/regressions diagnostic')
    assert len(plan['rows'])==15*len(tasks) and plan['required_reserved_calls']==calls
    assert (plan['solve_deadline_s'],plan['solve_supervisor_s'],plan['judge_supervisor_s'])==(300,310,360)
    queue.validate(plan)
    save(root/'PLAN.json',plan)
    assert all(sha(root/n)==h for n,h in sources.items())
    assert all(sha(parent/n)==h for n,h in parent_hashes.items())
    assert all(sha(qualified/n)==h for n,h in qualified_sources.items())
    if selected_queue is not None:assert sha(selected_queue)==PEER_QUEUE_SHA
    save(root/'PREPARATION_RESULT.json',dict(complete=True,prepared=True,submitted=False,execution_authorized=False,
        model_calls=0,eda_calls=0,fifo_calls=0,tasks=len(tasks),outputs=len(plan['rows']),max_calls=calls,
        spec_sha256=sha(root/'RUN_SPEC.json'),plan_sha256=sha(root/'PLAN.json'),sources_held=True,
        parent_and_qualification_held=True,admission_and_real_worker_execution_pending=True,
        wall_cap_is_not_ETA=True,qualification_only_selection=bool(args.qualification_only_selection)))


if __name__=='__main__':
    assert sys.platform=='linux' and sys.dont_write_bytecode
    p=argparse.ArgumentParser()
    for n in ('out','parent','qualified','kit','reader'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--reader-sha256',required=True)
    p.add_argument('--queue-source',type=Path,
        help='Optional exact PR198 queue for a new freeze; existing runs stay unchanged.')
    p.add_argument('--tasks',nargs='+',required=True)
    p.add_argument('--selection-reason',required=True)
    p.add_argument('--qualification-only-selection',action='store_true')
    prepare(p.parse_args())
