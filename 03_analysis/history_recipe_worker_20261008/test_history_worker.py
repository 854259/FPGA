"""New combined-worker contexts; old test methods/native/intake are not run.

The materialized bundle contains the original fixture harness, renamed
old_worker_fixture.py. HTTP, compiler and common-worker calls here are fake.
"""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import old_worker_fixture as old

worker=old.worker
ROOT=Path(__file__).resolve().parent


def setup(fixture, arm='P', requests=1):
    h=old.WorkerControls(methodName='runTest')
    h.setUp()
    h.args.arm=arm
    h.fallback_request_count=requests
    for name in ['onehot_producer.py','timer_producer.py','selector.py']:
        (h.owned/name).write_bytes((ROOT/name).read_bytes())
    (h.source/'prompt.txt').write_bytes(fixture['prompt'].encode())
    if fixture['interface']:
        (h.source/'interface.txt').write_bytes(fixture['interface'].encode())
    return h


def check_record(h, label, fixture):
    out=h.args.out
    route=old.read(out/'generation_route.json')
    result=old.read(out/'worker_result.json')
    decision=old.read(out/'generation_selection.json')
    assert route['schema']=='history_recipe_generation_route_v1'
    assert route['selected_provider']==decision['selected_provider']==label
    assert route['selection_sha256']==worker.text_sha(json.dumps(decision,sort_keys=True,separators=(',',':')))
    assert route['selector_source_sha256']==old.sha(h.owned/'selector.py')
    assert route['provider_source_hashes']=={name:old.sha(h.owned/(name+'_producer.py')) for name in ['onehot','timer']}
    assert old.read(out/'synthesis_receipt.json')==fixture['receipt']
    assert decision['recipe']==fixture['receipt']
    assert (out/'solution.v').read_bytes()==fixture['receipt']['rtl'].encode()
    assert result['generation_route']=='mechanical_'+label
    assert result['actual_model_requests']==result['received_model_responses']==0
    assert old.read(out/'requests.json')==[] and not (out/'requests').exists()
    assert len(h.paired.commands)==1 and h.paired.commands[0][2]==60
    assert h.fallback_calls==[]
    assert worker.raw_inputs(h.source)==worker.raw_inputs(out/'prompt_only')
    return route


def run():
    fixtures=json.loads((ROOT/'RETAINED_INPUTS_PRIVATE.json').read_bytes())
    cases=[]
    for f in fixtures:
        h=setup(f)
        try:
            worker.run_worker(h.args,h.paired)
            check_record(h,f['label'],f)
            cases.append('retained_'+f['label']+'_P_complete_wrapper_fake_native')
        finally:h.tearDown()
        h=setup(f,arm='C')
        try:
            with patch.object(worker.selector,'select',side_effect=AssertionError('C must not select')):
                worker.run_worker(h.args,h.paired)
            assert h.fallback_calls==[('C',h.args.out)]
            assert not (h.args.out/'generation_selection.json').exists()
            assert old.read(h.args.out/'generation_route.json')['selected_provider'] is None
            assert h.paired.commands==[]
            cases.append('retained_'+f['label']+'_C_original_fallback')
        finally:h.tearDown()
    unsupported=dict(prompt='Unrelated unsupported prompt\r\n',interface='input fake;\r\n')
    for requests in [1,2]:
        h=setup(unsupported,requests=requests)
        original=worker.raw_inputs(h.source)
        try:
            worker.run_worker(h.args,h.paired)
            route=old.read(h.args.out/'generation_route.json')
            assert route['route']=='model' and route['selected_provider'] is None
            assert old.read(h.args.out/'worker_result.json')['actual_model_requests']==requests
            assert h.fallback_calls==[('P',h.args.out)] and h.paired.commands==[]
            assert worker.raw_inputs(h.source)==original
            assert old.read(h.args.out/'generation_selection.json')['reason']=='no_complete_contract'
            cases.append('unsupported_P_same_baseline_'+str(requests)+'_requests')
        finally:h.tearDown()
    f=fixtures[0]
    for reason in ['ambiguous_complete_contracts','invalid_provider_receipt']:
        h=setup(f)
        recipe=copy.deepcopy(f['receipt'])
        if reason=='invalid_provider_receipt':recipe['rtl_sha256']='0'*64
        providers=(('first',lambda p,i:recipe),('second',lambda p,i:f['receipt']))
        try:
            with patch.object(worker,'PROVIDERS',providers):worker.run_worker(h.args,h.paired)
            assert h.fallback_calls==[('P',h.args.out)] and h.paired.commands==[]
            assert old.read(h.args.out/'generation_selection.json')['reason']==reason
            assert not (h.args.out/'synthesis_receipt.json').exists()
            cases.append(reason+'_falls_back_no_compile_or_extra_request')
        finally:h.tearDown()
    h=setup(fixtures[1]);h.paired.returncode=1
    try:
        worker.run_worker(h.args,h.paired)
        check_record(h,'timer',fixtures[1])
        assert h.feedback_calls==[] and old.read(h.args.out/'native_feedback.json')['native_compile_returncode']==1
        cases.append('selected_timer_fake_compile_failure_no_model_escalation')
    finally:h.tearDown()
    h=setup(fixtures[0]);h.feedback_text='FAKE finite mismatch feedback'
    try:
        worker.run_worker(h.args,h.paired)
        check_record(h,'onehot',fixtures[0])
        assert len(h.feedback_calls)==1
        assert old.read(h.args.out/'native_feedback.json')['repair_requested'] is False
        cases.append('selected_onehot_fake_feedback_no_extra_model_request')
    finally:h.tearDown()
    h=setup(fixtures[1]);h.paired.mutate_input=h.source/'prompt.txt'
    try:
        try:worker.run_worker(h.args,h.paired)
        except AssertionError:pass
        else:raise AssertionError('Changed selected input accepted')
        assert not (h.args.out/'worker_result.json').exists()
        cases.append('selected_timer_input_tamper_rejected')
    finally:h.tearDown()
    proof=json.loads((ROOT/'WORKER_ADAPTATION.json').read_bytes())
    body=(ROOT/'worker.py').read_bytes()
    assert hashlib.sha256(body).hexdigest()==proof['adapted_worker_sha256']
    for item in reversed(proof['replacements']):
        assert hashlib.sha256(body).hexdigest()==item['after_sha256']
        before,after=item['before'].encode(),item['after'].encode()
        for pos in reversed(item['after_positions']):
            assert body[pos:pos+len(after)]==after
            body=body[:pos]+before+body[pos+len(after):]
        assert hashlib.sha256(body).hexdigest()==item['before_sha256']
    assert body==(ROOT/'ORIGINAL_ONEHOT_WORKER.bin').read_bytes()
    assert hashlib.sha256(body).hexdigest()==proof['original_worker_sha256']
    cases.append('all_worker_adaptations_reverse_to_original_bytes')
    return dict(schema='history_recipe_new_complete_wrapper_fake_controls_v1',passed=True,
                new_contexts=len(cases),cases=cases,HTTP_compiler_common_worker_mocked=True,
                old_test_methods_native_intake_not_run=True,new_model_EDA_FIFO_calls=0,
                actual_native_or_model_path_verified=False,full_pipeline_score_adoption=False)


if __name__=='__main__':
    result=run()
    (ROOT/'ACTUAL_HISTORY_WORKER_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
