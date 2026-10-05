"""One AMD integration stage: frozen native controls and sealed report receipts.

No model requests. Existing A/P/B solving and HTTP controls are not rerun. All
format-control receipts below are deliberately constructed; they never become
candidate observations, official scores, or independent validation evidence.
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

import finite_scoring_20261005 as finite
import reporting_contract_20261005 as reporting
import three_arm_queue_20261005 as queue

arm = queue.official


def main(args):
    assert sys.platform == 'linux'
    here = Path(__file__).resolve().parent
    spec = json.loads((here/'U17_FINITE_INTEGRATION_20261005.json').read_text())
    for name, expected in spec['source_hashes'].items():
        assert arm.sha(here/name) == expected, 'Source drift: '+name
    assert arm.sha(args.inputs) == spec['private_inputs_sha256']
    inputs = json.loads(args.inputs.read_text())
    assert len(inputs['controls']) == 29 and inputs['real_model_calls'] == 0
    for path, expected in inputs['files'].items():
        assert arm.sha(path) == expected, 'Historical control drift'
    contract_path = Path(inputs['contract']); dataset = Path(inputs['dataset'])
    assert arm.sha(contract_path) == finite.CONTRACT_SHA
    contract = json.loads(contract_path.read_text())
    expected = {r['task']+'/'+n: h for r in contract['ledger'] for n,h in r['all_files_sha256'].items()}
    assert {str(p.relative_to(dataset)):arm.sha(p) for p in dataset.rglob('*') if p.is_file()} == expected
    toolbin = Path(os.environ['VIVADO_BIN'])
    resource = arm.resource_module()
    resource.check_resource(args.resource_check, args.kit, first=True)
    out = args.out.resolve(); assert not out.exists(); out.mkdir(parents=True)
    started = time.monotonic(); checks = []; native = []
    def reject(label, fn):
        try:
            fn()
        except (AssertionError, ValueError, RuntimeError, FileNotFoundError):
            checks.append(label)
        else:
            raise AssertionError('Accepted '+label)
    modern = 'ADMISSION_RESULT'
    good = 'ADMISSION_RESULT errors=0 samples=2\nMismatches: 0 in 2 samples\n'
    assert finite.completed_observations(good, modern, 2)['passed']
    # Multiple signals may fail in one observation; errors can exceed samples.
    legacy = 'Mismatches: 5 in 2 samples\nFatal: RTLLM_FAIL\n'
    assert not finite.completed_observations(legacy, 'RTLLM_PASS', 2)['passed']
    checks += ['valid_modern_summary', 'legacy_multiple_signal_mismatches']
    for label, text in [
        ('under_observed', good.replace('samples=2','samples=1').replace('2 samples','1 samples')),
        ('missing_summary', ''), ('duplicate_summary', good+good),
        ('zero_observations', good.replace('samples=2','samples=0').replace('2 samples','0 samples')),
        ('watchdog',good+'ADMISSION_WATCHDOG\n'), ('unexpected_fatal',good+'Fatal: fixture_error\n'),
        ('inconsistent_counts',good.replace('errors=0','errors=1'))]:
        reject(label, lambda text=text: finite.completed_observations(text, modern, 2))
    syntax = 'ERROR: [VRFC 10-4982] syntax error [candidate.sv:1]\n'
    assert finite.candidate_compile_failure('candidate_compile', syntax)
    assert not finite.candidate_compile_failure('fixture_compile', syntax)
    assert not finite.candidate_compile_failure('candidate_compile', syntax+'ERROR: license unavailable\n')
    checks += ['candidate_diagnostic', 'fixture_error_not_model_error', 'mixed_tool_error_not_model_error']

    sources = queue.prepare_sources(out/'sources')
    tasks = []
    for control in inputs['controls']:
        task = dataset/control['task']; ledger = finite.task_contract(contract_path, task)
        prompt = out/'prompt_only'/control['task']; prompt.mkdir(parents=True)
        (prompt/'prompt.txt').write_bytes((task/'prompt.txt').read_bytes())
        tasks.append(dict(dataset='rtllm_finite_development',task=control['task'],
            family='historical_rtllm_independence_unverified',use='development',task_dir=str(prompt),
            hashes={'prompt.txt':ledger['input_sha256']}))
    plan = queue.build_plan(tasks, 5, sources, Path(arm.__file__), args.kit, 725, 435*670)
    plan.update(model_launch_authorized=False, capacity_only_not_approved_budget=True)
    floors = {r['task']:r['minimum_samples'] for r in inputs['controls']}
    finite.bind_plan(plan, contract_path, dataset, toolbin, floors)
    identities = {a:queue.digest(dict(arm=a,source_files=sources['files'] if a!='B' else arm.OFFICIAL,
        entry_sha256=arm.sha(Path(sources['root'])/'worker.py') if a!='B' else arm.sha(arm.__file__),
        model=arm.MODEL,temperature=0,top_p=1,max_tokens=8192,maximum_requests=queue.MAX_CALLS[a]))
        for a in ['A','P','B']}
    bound_contract = reporting.bind_phase_p(contract, identities)
    arm.save(out/'REPORTING_CONTRACT.json', bound_contract)
    run = dict(run_id='U17_FORMAT_CONTROL_NOT_A_MODEL_RUN',
        observation_kind='real_model', model_config_sha256=queue.digest({'model':arm.MODEL,'T':0,'p':1,'tokens':8192}),
        arm_sources=identities)
    plan.update(reporting_contract_sha256=arm.sha(out/'REPORTING_CONTRACT.json'),
        reporting_implementation_sha256=arm.sha(reporting.__file__), reporting_run=run)
    queue.validate(plan)
    queue.save(out/'NON_DISPATCHABLE_PLAN.json',plan)
    assert len(plan['rows']) == 435 and plan['required_reserved_calls'] == 725
    # These are capacity reservations only. No queue.advance or solver call.
    for control in inputs['controls']:
        assert time.monotonic()-started+330 < spec['budget']['stage_timeout_s'], 'Insufficient pair time reserve'
        task = dataset/control['task']
        row = dict(task=control['task'], arms={})
        for label in ['positive','negative']:
            resource.check_resource(args.resource_check,args.kit)
            result = finite.simulate(Path(control[label]),task,out/'native'/control['task']/label,
                                     resource,toolbin,control['minimum_samples'])
            row['arms'][label] = result
            assert result['passed'] == (label=='positive'), (control['task'],label,result)
        native.append(row)
        queue.save(out/'NATIVE_PROGRESS.json',dict(completed_pairs=len(native),rows=native,real_model_calls=0))
    assert len(native) == 29
    broken = out/'broken.sv'; broken.write_text('module TopModule(input a,output y); assign y = ; endmodule\n')
    failed = finite.simulate(broken,dataset/inputs['controls'][0]['task'],out/'candidate_compile_failure',
                             resource,toolbin,inputs['controls'][0]['minimum_samples'])
    assert not failed['passed'] and failed['reason']=='candidate_compile_error'
    reject('missing_tool_is_unscored', lambda: finite.simulate(broken,dataset/inputs['controls'][0]['task'],
        out/'missing_tool',resource,out/'nonexistent_tools',1))
    checks += ['all29_native_positive_and_negative_pairs','real_candidate_compile_failure']

    assert time.monotonic()-started+2070 < spec['budget']['stage_timeout_s'], 'Insufficient three-arm time reserve'
    # Exercise the actual pinned A/P/B children and the new isolated judge in
    # the same acceptance slot. The existing U14 bootstrap redirects POSTs to
    # a local fixed-response server; no call can reach the shared 27B here.
    response_source = Path(inputs['controls'][0]['positive']).read_text()
    expected_prompt = (dataset/inputs['controls'][0]['task']/'prompt.txt').read_text().strip()
    posted = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused): pass
        def send(self,body):
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            assert self.path == '/v1/models'
            self.send(json.dumps({'data':[{'id':arm.MODEL}]}).encode())
        def do_POST(self):
            assert self.path == '/v1/chat/completions'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert (body['model'],body['temperature'],body['top_p'],body['max_tokens']) == (arm.MODEL,0,1,8192)
            user=body['messages'][1]['content'].strip()
            assert user == expected_prompt or user.startswith(expected_prompt+'\nPrevious candidate:\n'), 'Unexpected evaluator input'
            assert len(posted) < 5, 'Synthetic request budget exhausted'
            posted.append(body)
            self.send(json.dumps({'choices':[{'message':{'content':response_source},'finish_reason':'stop'}],
                                  'usage':{'prompt_tokens':1,'completion_tokens':1}}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original_owned=resource.owned_command;original_resource=arm.resource_module
    def controlled_owned(argv,cwd,log,seconds):
        if any(str(x).endswith(('/worker.py','/official_baseline_arm_20261005.py')) for x in argv):
            control=Path(cwd)/'SYNTHETIC_LAUNCH.json'
            queue.save(control,dict(argv=argv,synthetic_endpoint='http://127.0.0.1:'+str(server.server_port)+'/v1',real_model_calls=0))
            argv=['/usr/bin/python3','-B',str(here/'three_arm_execution_preflight_20261005.py'),'--synthetic-child',str(control)]
        return original_owned(argv,cwd,log,seconds)
    resource.owned_command=controlled_owned;arm.resource_module=lambda:resource
    executed=[]
    try:
        folder=Path(sources['root'])/'finite_queue'
        def execute(argv,row,path):
            receipt=queue.execute_row(plan,argv,row,path,args.resource_check)
            receipt.update(synthetic=True,real_model_calls=0)
            return receipt
        for index in range(3):
            queue.advance(plan,folder,args.resource_check,execute)
            row=plan['rows'][index];path=folder/('row_'+str(index).zfill(6))
            receipt=queue.verify_terminal(path,row,queue.digest(plan))
            assert receipt['complete'] and receipt['finite_pass'] and 1<=receipt['actual_calls']<=queue.MAX_CALLS[row['arm']]
            assert {p.name for p in (path/'solve/prompt_only').iterdir()} == {'prompt.txt'}
            reject('actual_synthetic_child_not_model_score_'+row['arm'],
                lambda path=path,row=row:reporting.normalize_queue_row(path,row,plan,bound_contract,run))
            executed.append(row['arm'])
        assert sorted(executed)==['A','B','P'] and 3<=len(posted)<=5
        checks.append('actual_A_P_B_children_to_finite_judge')
    finally:
        resource.owned_command=original_owned;arm.resource_module=original_resource
        server.shutdown();server.server_close();thread.join(2)
        queue.save(out/'SYNTHETIC_HTTP_REQUESTS.json',posted)
    assert not thread.is_alive()

    format_rows = []
    for i,row in enumerate(plan['rows'][:3]):
        folder=out/'format_controls'/str(i);(folder/'judge').mkdir(parents=True)
        queue.save(folder/'STARTED.json',dict(row=row,plan_sha256=queue.digest(plan)))
        control = next(r for r in native if r['task']==row['task'])['arms']['positive']
        verdict=dict(schema='rtllm_finite_verdict_v1',arm=row['arm'],task=row['task'],
            contract_sha256=finite.CONTRACT_SHA,evaluator_sha256=arm.sha(finite.__file__),
            task_files=row['evaluator_hashes'],input_sha256=row['input_hashes']['prompt.txt'],
            judge_sha256=row['evaluator_hashes']['tb.sv'],minimum_observations=row['minimum_observations'],
            client_request_attempts=1,confirmed_model_responses=1,verdict=control)
        queue.save(folder/'judge/BOUND_VERDICT.json',verdict)
        receipt=dict(complete=True,actual_calls=1,unconfirmed_calls=0,finite_pass=True,
            solve_elapsed_s=0,judge_elapsed_s=control['native_elapsed_s'],
            files={str(p.relative_to(folder)):arm.sha(p) for p in folder.rglob('*') if p.is_file()})
        queue.save(folder/'TERMINAL.json',receipt)
        normalize=lambda:reporting.normalize_queue_row(folder,row,plan,bound_contract,run)
        before=normalize();assert before['arm']==row['arm'] and before['passed']
        queue.save(folder/'TERMINAL.json',dict(receipt,synthetic=True,real_model_calls=0))
        reject('synthetic_receipt_rejected_'+row['arm'],normalize)
        queue.save(folder/'TERMINAL.json',receipt)
        queue.seal_row(folder,row,queue.digest(plan))
        (folder/'judge/BOUND_VERDICT.json').unlink()
        assert normalize()==before
        format_rows.append(dict(arm=row['arm'],live_and_sealed_equal=True,constructed_not_model_evidence=True))
    bad_run=copy.deepcopy(run);bad_run['run_id']='different'
    reject('mixed_run_rejected',lambda:reporting.normalize_queue_row(folder,row,plan,bound_contract,bad_run))
    drift=copy.deepcopy(plan);drift['finite_judge']['entry_sha256']='f'*64
    reject('judge_source_drift_before_dispatch',lambda:queue.validate(drift))
    checks += ['A_P_B_live_and_sealed_normalization']
    resource.check_resource(args.resource_check,args.kit)
    for path,expected in inputs['files'].items():assert arm.sha(path)==expected
    result=dict(schema='finite_integration_U17',complete=True,passed=True,real_model_calls=0,
        original_inventory=44,finite_tasks=29,blocked_tasks=15,independent_tasks=0,
        native_control_pairs=29,native_invocations=59,actual_solver_children=3,
        synthetic_http_posts=len(posted),additional_finite_queue_judgements=3,
        native_tool_commands=sum(len(r['arms'][label]['stages']) for r in native for label in ['positive','negative'])+len(failed['stages']),
        format_controls=format_rows,checks=checks,elapsed_s=time.monotonic()-started,
        candidate_scores=0,full_batch=False,model_launch_authorized=False,
        limitation='Actual pinned children use synthetic HTTP, not 27B accuracy. Unclassified elaboration failures stop unscored; no independent/full-batch/32GB claim.')
    queue.save(out/'RESULTS.json',result);print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ['inputs','out','kit','resource-check']:
        parser.add_argument('--'+key,type=Path,required=True)
    main(parser.parse_args())
