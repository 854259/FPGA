"""Only new five-pair scoring boundaries; all rows are synthetic, no worker/native calls."""
import copy,hashlib,importlib.util,json,types
from pathlib import Path
import metrics
ROOT=Path(__file__).resolve().parent


def entry_dispatch_control():
    """Execute the new pilot.worker function with explicitly fake owned dependencies."""
    spec=importlib.util.spec_from_file_location('score5_new_entry_under_test',ROOT/'pilot.py')
    pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
    events=[]
    paired=types.SimpleNamespace(check_resource=lambda *a:events.append('resource_checked'))
    selected=types.SimpleNamespace(run_worker=lambda args,owned:events.append('run_worker_called') if owned is paired else (_ for _ in ()).throw(AssertionError('Wrong owned context')))
    frozen=lambda kit:(events.append('frozen_entry_checked') or dict(task_ids=metrics.TASKS,arms=['C','P'],dependencies_cloud=str(ROOT/'dependencies')))
    entry=types.SimpleNamespace(modules=lambda root:(events.append('source_objects_checked') or (None,{'worker':selected})))
    def load(name,path):
        assert name=='wave_score5_worker_owned' and Path(path)==ROOT/'dependencies/paired_checkpoint.py'
        events.append('owned_context_loaded');return paired
    pilot.frozen=frozen;pilot.entry_module=entry;pilot.load=load
    args=types.SimpleNamespace(kit=ROOT/'FAKE_KIT',task=metrics.TASKS[0],arm='C',out=ROOT/'FAKE_OUT_NOT_CREATED',resource_check=ROOT/'FAKE_RESOURCE_NOT_OPENED')
    pilot.worker(args)
    assert events==['frozen_entry_checked','source_objects_checked','owned_context_loaded','resource_checked','run_worker_called']
    assert not args.out.exists()
    events.clear();args.task='NotAnAdmittedTask'
    try:pilot.worker(args)
    except AssertionError:assert events==['frozen_entry_checked']
    else:raise AssertionError('Entry accepted a task outside fixed5')
    return dict(actual_new_entry_function_executed=True,run_worker_dispatch_reached_with_fake_owned_dependencies=True,
        standalone_closed_worker_CLI_not_executed=True,outside_scope_rejected_before_dispatch=True,
        actual_generation_model_or_EDA_execution=False)


def main():
    scorer_path=ROOT/'OFFICIAL_SCORER.py'
    manifest=json.loads((ROOT/'INPUT_MANIFEST.json').read_bytes())
    assert hashlib.sha256(scorer_path.read_bytes()).hexdigest()==manifest['official_sha256']['selftest/score.py']
    spec=importlib.util.spec_from_file_location('score5_original_scorer',scorer_path);scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
    plan=json.loads((ROOT/'COMPARISON_INPUT_PLAN.json').read_bytes());rows=[]
    h=lambda x:hashlib.sha256(x.encode()).hexdigest()
    for task,arm in metrics.order(metrics.TASKS):
        expected=plan['tasks'][task][arm];route=expected['route'];mechanical=route in metrics.MECHANICAL
        changed=expected['first_request_advice_changed'];level=1 if task=='Prob145_circuit8' and arm=='C' else 3
        rows.append(dict(task=task,arm=arm,verdict=dict(task_id=task,level=level,coefficient=metrics.COEFFICIENTS[level],tool_error=None,elapsed_s=0),
            actual_model_requests=0 if mechanical else 1,received_model_responses=0 if mechanical else 1,
            solve_deadline_reached=False,solve_elapsed_s=1,stage_generation_binding_verified=True,
            module_source_objects_bound=True,common_mechanical_strategy_bound=True,
            generation_route=route,selected_provider=expected['selected_provider'],parent_route=route,
            parent_recipe_bound=True,parent_preserved_bound=mechanical,parent_abstention_bound=not mechanical,
            parent_output_sha256=h(task+'solution') if mechanical else None,solution_sha256=h(task+'solution'),
            producer_contract_sha256=h(task+'contract') if mechanical else None,
            emitted_solution_sha256=h(task+'solution') if mechanical else None,
            route_receipt_sha256=h(task+'route'),synthesis_receipt_sha256=h(task+'receipt'),
            wave_scope='model_first_user_only',repair_wires_unchanged=True,first_request_advice_changed=changed,
            waveform_request_binding_verified=not mechanical,request_proof_sha256=None if mechanical else h(task+'proof'),
            first_original_wire_sha256=None if mechanical else h(task+'original'),
            first_forwarded_wire_sha256=None if mechanical else h(task+('changed' if changed else 'original'))))
    calculate=lambda rs:metrics.aggregate(rs,metrics.TASKS,metrics.HISTORICAL,scorer)
    baseline=calculate(rows)
    assert baseline['diagnostic_passed'] and baseline['diagnostic_promising'] and baseline['all_five_P_L3']
    assert not any(baseline[k] for k in ['qualified_for_full156','qualified_for_new_full_regression','qualified_for_goal','goal_achieved','adoption'])
    rejected=[];blocked=[]
    def row(rs,t,a):return next(r for r in rs if r['task']==t and r['arm']==a)
    def reject(name,t,a,changes):
        values=copy.deepcopy(rows);row(values,t,a).update(changes)
        try:calculate(values)
        except AssertionError:rejected.append(name)
        else:raise AssertionError('Accepted malformed new score5 boundary: '+name)
    reject('C table cannot become model','Prob057_kmap2','C',dict(generation_route='model'))
    reject('Common mechanical requires zero calls','Prob143_fsm_onehot','C',dict(actual_model_requests=1,received_model_responses=1))
    reject('Model requires a request','Prob001_zero','C',dict(actual_model_requests=0,received_model_responses=0))
    reject('Mechanical pair cannot change RTL','Prob151_review2015_fsm','P',dict(solution_sha256=h('other'),emitted_solution_sha256=h('other'),parent_output_sha256=h('other')))
    reject('Mechanical contract equal in arms','Prob057_kmap2','P',dict(producer_contract_sha256=h('other')))
    reject('Common strategy proof required','Prob143_fsm_onehot','C',dict(common_mechanical_strategy_bound=False))
    reject('Loaded dependency identities required','Prob145_circuit8','P',dict(module_source_objects_bound=False))
    reject('Wave changed only admitted first P target','Prob001_zero','P',dict(first_request_advice_changed=True,first_forwarded_wire_sha256=h('changed')))
    reject('First original C/P wire equal','Prob145_circuit8','P',dict(first_original_wire_sha256=h('wrong')))
    reject('Mechanical wave not applicable','Prob057_kmap2','C',dict(request_proof_sha256=h('fake')))
    reject('Repair wire unchanged','Prob145_circuit8','P',dict(repair_wires_unchanged=False))
    reject('Provider cannot be replaced','Prob151_review2015_fsm','C',dict(selected_provider='onehot'))
    for name,changes in [('historical per-task cost',dict(actual_model_requests=2,received_model_responses=2)),('unconfirmed call',dict(received_model_responses=0)),('deadline',dict(solve_deadline_reached=True)),('original300',dict(solve_elapsed_s=300.1))]:
        values=copy.deepcopy(rows);row(values,'Prob145_circuit8','P').update(changes);result=calculate(values)
        assert not result['diagnostic_passed'] and not result['diagnostic_promising'];blocked.append(name)
    values=copy.deepcopy(rows);r=row(values,'Prob145_circuit8','P');r['verdict'].update(level=2,coefficient=.7);result=calculate(values)
    assert not result['all_five_P_L3'] and not result['diagnostic_passed'];blocked.append('all five P must be L3; L2 remains .7')
    values=copy.deepcopy(rows);r=row(values,'Prob145_circuit8','C');r['verdict'].update(level=3,coefficient=1.);result=calculate(values)
    assert result['diagnostic_passed'] and not result['diagnostic_promising'] and result['strict_new_L3_net']==0
    entry=entry_dispatch_control()
    result=dict(schema='score5_new_interfaces_synthetic_controls_v1',passed=True,positive_contexts=2,
        malformed_metadata_rejected=rejected,score_gate_rejections=blocked,synthetic_rows_only=True,
        new_frozen_entry_dispatch_control=entry,
        original_worker_native_or_full_suites_invoked=False,new_worker_calls=0,model_calls=0,eda_calls=0,new_fifo=False,
        score_measured=False,full156_qualified=False,goal_achieved=False,adoption=False)
    (ROOT/'ACTUAL_SCORE5_INTERFACE_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
