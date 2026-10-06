"""Read-only original-grade audit with a narrowly proved zero-request route."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile

HELPER_SHA = '6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
ROUTE_SCHEMA = 'onehot_synthesis_generation_route_v1'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def shared_helper():
    here = Path(__file__).resolve().parent
    copy = here / 'dependencies/full156_postflight_audit.py'
    path = copy if copy.exists() else here.parent / 'full156_postflight_20261004/audit.py'
    assert sha(path) == HELPER_SHA
    return load('table_original_archive_and_grade_verifier', path)


def protected_receipts(run, spec):
    groups = read(run/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    external = read(run/'EXTERNAL_SOURCE_MANIFEST.json')
    assert sha(run/'EXTERNAL_SOURCE_MANIFEST.json') == spec['external_inventory_manifest_sha256']
    assert external['legacy_groups'] == 95 and external['legacy_summed_group_source_assets'] == 6286
    assert external['unique_immutable_files'] == len(external['source_hashes']) == 6516
    assert len(groups['groups']) == spec['protected_group_count'] and len(groups['groups']) >= 95
    assert groups['source_assets'] == spec['protected_source_assets'] and groups['source_assets'] >= 6516
    assert sum(len(item['source_hashes']) for item in groups['groups'].values()) == groups['source_assets']
    retained = {}
    for item in groups['groups'].values():
        cloud = PurePosixPath(item['cloud_root'])
        assert cloud.is_absolute() and '..' not in cloud.parts
        for name, digest in item['source_hashes'].items():
            relative = PurePosixPath(name)
            assert not relative.is_absolute() and '..' not in relative.parts
            key = (cloud/relative).relative_to(PurePosixPath(external['cloud_root'])).as_posix()
            assert key not in retained
            retained[key] = digest
    assert all(retained.get(name) == digest for name,digest in external['source_hashes'].items())
    assert len(retained) == groups['source_assets']
    expected_groups = {name: dict(spec_sha256=item['spec_sha256'],
        source_hashes=item['source_hashes'], source_assets=len(item['source_hashes']))
        for name, item in groups['groups'].items()}
    checks = sorted((run/'results/protected_source_checks').glob('*.json'))
    assert spec['expected_samples'] == 14
    assert [p.name for p in checks] == [str(i).zfill(3)+'.json' for i in range(2*spec['expected_samples']+1)]
    for index, path in enumerate(checks):
        assert read(path) == dict(index=index, schema='semantic_edge_protected_source_check_v1',
            verified=True, groups=expected_groups, source_assets=groups['source_assets'],
            model_calls=0, eda_calls=0)


def bound_route(work, run, arm, prompt, interface, interface_present, generator):
    result = generator.synthesize(prompt, interface) if arm == 'P' else None
    emitted = result is not None and result['emitted']
    digest = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()
    expected = dict(schema=ROUTE_SCHEMA, route='mechanical_onehot' if emitted else 'model',
        outer_arm=arm, prompt_sha256=digest(prompt), interface_sha256=digest(interface),
        interface_present=interface_present, baseline_worker_sha256=sha(run/'baseline_worker.py'),
        synthesis_source_sha256=sha(run/'synthesis.py'),
        generated_solution_sha256=result['rtl_sha256'] if emitted else None)
    assert read(work/'generation_route.json') == expected
    if arm == 'P':
        assert read(work/'synthesis_receipt.json') == result
    else:
        assert not (work/'synthesis_receipt.json').exists()
    return expected, result


def model_requests(work, row, spec, generation, repair):
    journal = read(work/'requests.json')
    assert 1 <= len(journal) <= 2
    assert row['actual_model_requests'] == len(journal)
    assert row['received_model_responses'] == sum(e['response_received'] for e in journal)
    expected_files = set()
    trace = [json.loads(line) for line in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert trace and trace[0]['tool'] == 'agent_meta' and trace[0]['repairs'] == 1
    assert trace[0]['skill_sha256'] == hashlib.sha256(generation.encode()).hexdigest()
    assert trace[0]['repair_skill_sha256'] == hashlib.sha256(repair.encode()).hexdigest()
    assert [e['round'] for e in trace if e['tool'] == 'llm_start'] == list(range(len(journal)))
    assert not any(e.get('error') or e.get('tool') == 'onehot_generation' for e in trace)
    first_body = None
    for index, entry in enumerate(journal):
        folder = work/'requests'/str(index); request = folder/'request.json'
        expected_files.add(request)
        assert entry['index'] == index and entry['replayed'] is False
        assert entry['request_sha256'] == sha(request)
        body = read(request)
        assert set(body) == {'model','messages','temperature','top_p','max_tokens'}
        assert body['model'] == spec['model'] and type(body['max_tokens']) is int and body['max_tokens'] == 8192
        assert type(body['temperature']) in (int,float) and body['temperature'] == 0
        assert type(body['top_p']) in (int,float) and body['top_p'] == 1 and len(body['messages']) == 2
        assert body['messages'][0] == dict(role='system',content=generation+('\n'+repair if index else ''))
        if index == 0: first_body = body
        if entry['response_received']:
            response = folder/'response.json'; expected_files.add(response)
            assert entry['response_sha256'] == sha(response)
            payload = read(response); choice = payload['choices'][0]; usage = payload.get('usage') or {}
            assert entry['finish_reason'] == choice.get('finish_reason') and entry['response_id'] == payload.get('id')
            assert entry.get('usage') == payload.get('usage')
            events = [e for e in trace if e['tool'] == 'llm' and e['round'] == index]
            assert len(events) == 1 and events[0]['finish'] == choice.get('finish_reason')
            assert events[0]['tokens_in'] == usage.get('prompt_tokens') and events[0]['tokens_out'] == usage.get('completion_tokens')
    assert {p for p in (work/'requests').rglob('*') if p.is_file()} == expected_files
    assert set(work.rglob('response.json')) == {p for p in expected_files if p.name == 'response.json'}
    return journal, first_body


def mechanical_provenance(work, run, task, row, result, cloud_work, runner, parser, verify_probe):
    assert row['arm'] == 'P' and not row['solve_deadline_reached']
    assert read(work/'requests.json') == [] and row['actual_model_requests'] == row['received_model_responses'] == 0
    assert not (work/'requests').exists() and not list(work.rglob('request.json')) and not list(work.rglob('response.json'))
    assert not (work/'compile_journal.json').exists() and not (work/'compile_receipts').exists()
    code = result['rtl'].encode('utf-8')
    assert (work/'solution.v').read_bytes() == (work/'emission/emitted.sv').read_bytes() == code
    raw_prompt = (work/'prompt_only/prompt.txt').read_bytes().decode('utf-8')
    contract = read(work/'emission/contract.json')
    assert contract == result_contract(run, raw_prompt)
    assert hashlib.sha256(json.dumps(contract,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()).hexdigest() == result['contract_sha256']
    folder = work/'native_receipts/0'; physical = read(folder/'command.json')
    assert {p.name for p in (work/'native_receipts').iterdir()} == {'0'}
    assert {p.name for p in folder.iterdir()} == {'command.json','source_before.sv','source_after.sv','owned_compile.log'}
    for name in ('source_before.sv','source_after.sv'):
        assert (folder/name).read_bytes() == code
    log = folder/'owned_compile.log'; stdout = log.read_text(encoding='utf-8',errors='replace')
    assert physical['source_sha256'] == physical['source_before_sha256'] == physical['source_after_sha256'] == result['rtl_sha256'] == sha(work/'solution.v')
    assert physical['argv'] == ['/workspace/AMD/2026.1/Vivado/bin/xvlog','--sv',str(cloud_work/'work/mechanical_compile-0/candidate.sv')]
    assert (work/'work/mechanical_compile-0/candidate.sv').read_bytes() == code
    assert not physical['timeout'] and not physical['launch_error'] and not physical['remaining_live_group']
    assert type(physical['returncode']) is int and physical['returncode'] >= 0
    assert physical['log_sha256'] == sha(log) and physical['log_bytes'] == log.stat().st_size
    assert not runner.ENVIRONMENT_ERROR.search(stdout)
    # A compiler may legitimately reject source. A zero-return fatal/error log
    # cannot become clean native execution merely through its return code.
    assert physical['returncode'] != 0 or not re.search(r'(?im)^\s*(?:fatal|error)\s*[:\[]',stdout)
    excerpt = '\n'.join(line for line in stdout.splitlines() if re.search('ERROR|WARNING|FATAL',line))[:2048] or stdout[-2048:]
    trace = [json.loads(line) for line in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [event['tool'] for event in trace] == ['onehot_generation','lint_start','lint','native_feedback']
    assert all(event['round'] == 0 and not event.get('error') for event in trace)
    assert trace[0]['route'] == 'mechanical_onehot' and trace[0]['actual_model_requests'] == 0
    assert trace[0]['emitted_sha256'] == result['rtl_sha256'] and trace[0]['contract_sha256'] == result['contract_sha256']
    assert trace[2]['rc'] == physical['returncode'] and trace[2]['excerpt'] == excerpt
    assert trace[2]['receipt_sha256'] == sha(folder/'command.json')
    feedback = read(work/'native_feedback.json')
    assert feedback['repair_requested'] is False and feedback['native_compile_returncode'] == physical['returncode']
    prompt = (work/'prompt_only/prompt.txt').read_text(encoding='utf-8')
    iface = work/'prompt_only/interface.txt'
    if iface.exists() and iface.read_text(encoding='utf-8').strip(): prompt += '\n\nInterface:\n'+iface.read_text(encoding='utf-8')
    common = parser.parse(prompt); check = work/'map_check_0'
    expected = ''
    if physical['returncode'] == 0 and common['status'] == 'supported' and not re.search(r'\$[A-Za-z_]|`include',result['rtl']):
        assert read(check/'contract.json') == common and (check/'input.sv').read_bytes() == code
        raw = verify_probe(check,common)
        if raw['mismatches']: expected = read(check/'feedback.json')['text']
    else: assert not check.exists()
    assert feedback['text'] == expected
    assert trace[3]['text'] == trace[3]['excerpt'] == expected and trace[3]['repair_requested'] is False
    assert trace[1]['generation_route'] == trace[2]['generation_route'] == trace[3]['generation_route'] == 'mechanical_onehot'
    wr = read(work/'worker_result.json')
    assert wr['complete'] and wr['arm'] == 'P' and wr['generation_route'] == 'mechanical_onehot'
    assert wr['requests'] == wr['actual_model_requests'] == wr['received_model_responses'] == 0
    assert wr['solution_sha256'] == sha(work/'solution.v')
    return dict(first_reply_sha256=None,declaration_patches=0,original_repair_feedback_bound=False,
                mechanical_recipe_bound=True,empty_model_artifacts_bound=True,
                first_pair_applicability='not_applicable_mechanical',native_execution_bound=True)


def result_contract(run, prompt):
    module = load('fsm_sealed_producer_contract',run/'synthesis.py')
    parsed = module.synthesize(prompt, '')
    assert parsed['emitted'] and parsed['contract']['all_prompt_consumed'] is True
    return parsed['contract']

def audit(archive,out,spec_sha):
    assert sys.version_info[:2]==(3,12)
    assert not out.exists()
    shared=shared_helper()
    here=Path(__file__).resolve().parent
    replay=load('table_original_replay',here/'upstream/replay.py')
    with tempfile.TemporaryDirectory(prefix='fresh-functional-audit-') as tmp:
        root=Path(tmp);manifest=shared.unpack(archive,root);run=root/'run'
        assert sha(run/'RUN_SPEC.json')==spec_sha==manifest['run_spec_sha256']
        spec=read(run/'RUN_SPEC.json');report=read(run/'results/summary.json')
        for name in ['audit.py','metrics.py','upstream/replay.py']:
            assert sha(here/name)==spec['source_hashes'][name]
        assert spec['schema']=='onehot_synthesis_cp7_frozen_v1' and spec['arms']==['C','P']
        assert len(spec['task_ids'])==7
        assert spec['max_actual_model_requests']==28 and spec['expected_samples']==14
        assert spec['solve_deadline_s']==spec['judge_timeout_s']==300 and spec['judge_supervisor_timeout_s']==360
        assert spec['max_worker_requests_per_arm']==2 and spec['retries']==0
        assert report['complete'] and report['passed'] and report['spec_sha256']==spec_sha
        assert report['first_generation_replayed'] is False
        for n,h in spec['source_hashes'].items():assert sha(run/n)==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(root/'dependencies'/n)==h,n
        assert 'SOURCE_FACTOR_PROOF.json' in spec['source_hashes']
        proof=load('table_sealed_source_proof',run/'factor_proof.py')
        assert read(run/'SOURCE_FACTOR_PROOF.json')==proof.verify(run)
        metrics=load('table_frozen_metrics',run/'metrics.py')
        assert spec['task_ids']==list(metrics.TASKS)
        assert spec['target_tasks']==metrics.TARGETS and spec['guard_tasks']==metrics.GUARDS and spec['abstention_tasks']==metrics.ABSTENTIONS
        environment=read(run/'results/ENVIRONMENT_PREFLIGHT.json')
        assert environment['verified'] and environment['vivado_bin']=='/workspace/AMD/2026.1/Vivado/bin' and environment['udev_stub']=='/workspace/team/udev-stub'
        assert environment['model_calls']==environment['eda_calls']==0
        assert environment['tools']==spec['compiler_tools'] and environment['compiler_env']==spec['compiler_env'] and environment['udev_files']==spec['udev_files']
        assert set(environment['tools'])=={'xvlog','xelab','xsim','vivado'}
        for n,d in environment['tools'].items():assert d['path']=='/workspace/AMD/2026.1/Vivado/bin/'+n and re.fullmatch('[0-9a-f]{64}',d['sha256'])
        inputs=read(run/'INPUT_MANIFEST.json');resource=read(root/'guard/resource_check.json');guard=read(root/'guard/status.json')
        assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
        assert guard['stage_rc']==0 and not guard['model_managed'] and not guard['instance_managed']
        assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
        assert resource['model_identity']['pid']==2013333 and resource['model_identity']['starttime']=='823869819'
        capture=read(run/'raw_evidence/ENVIRONMENT_CAPTURE.json')
        assert resource['model_identity']==capture['model_identity'] and resource['protected']==capture['protected']
        assert capture['model_identity']['command_sha256']=='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'
        assert capture['compiler_tools']==spec['compiler_tools'] and capture['compiler_env']==spec['compiler_env'] and capture['udev_files']==spec['udev_files']
        assert capture['dependency_hashes']==spec['dependency_hashes'] and capture['dependencies_cloud']==spec['dependencies_cloud']
        assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
        assert set(spec['task_ids'])<=set(n.split('/')[0] for n in inputs['input_sha256'])
        for n,h in inputs['input_sha256'].items():
            if n.split('/')[0] in spec['task_ids']:assert sha(root/'kit/bench/tasks_veval'/n)==h,n
        for n,h in inputs['official_sha256'].items():assert sha(root/'kit/official_reference'/n)==h,n
        protected_receipts(run,spec)
        old_path=list(sys.path);sys.path.insert(0,str(run))
        candidate_parser=load('table_common_phaseP_dispatch',run/'edge_dispatch.py')
        candidate_feedback=load('table_common_phaseP_feedback',run/'phase_feedback.py')
        phase_context=load('table_original_phase_context',run/'phase_context.py')
        edge_contract=load('table_original_edge_contract',run/'edge_contract.py')
        baseline=load('table_original_extract',run/'package/baseline.py')
        runtime=load('table_original_runtime',run/'package/agent/runtime.py')
        generator=load('table_sealed_generation',run/'synthesis.py')
        runner=load('table_original_native_summary',root/'dependencies/probe_runner.py')
        generation=(run/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
        repair=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
        rows=[];total=0;unconfirmed=0;firsts={};provenance=[]
        assert [(r['task'],r['arm']) for r in report['rows']]==metrics.order(spec['task_ids'])
        assert {(p.parent.name,p.parent.parent.name) for p in (run/'results/samples').glob('*/*/row.json')}==set(metrics.order(spec['task_ids']))
        def probe(check,task,c):
            raw=read(check/'probe/result.json');adapter=read(check/'probe/adapter_receipt.json')
            assert all(adapter[k]==v for k,v in raw.items()) and adapter['inherited_result_sha256']==sha(check/'probe/result.json')
            assert adapter['inherited_runner_sha256']==sha(root/'dependencies/probe_runner.py')
            assert adapter['oracle_adapter_sha256']==sha(root/'dependencies/paired_checkpoint.py')
            assert raw['runner_sha256']==sha(root/'dependencies/probe_runner.py') and raw['inputs_unchanged']
            assert raw['solution_sha256']==sha(check/'input.sv')==sha(check/'probe/dut.sv')
            assert raw['tb_sha256']==sha(check/'inputs'/task/'tb.sv')==sha(check/'probe/tb.sv')
            assert raw['task']==task and len(raw['stages'])==3
            for stage,name in zip(raw['stages'],['xvlog','xelab','xsim']):
                assert stage['name']==name and PurePosixPath(stage['argv'][0]).name==name
                shared.command(stage,check/'probe'/(name+'.log'))
                assert not runner.ENVIRONMENT_ERROR.search((check/'probe'/(name+'.log')).read_text(encoding='utf-8',errors='replace'))
            runner.TASK_CHECKS[task]=c['checks'];log=(check/'probe/xsim.log').read_text(encoding='utf-8')
            count,mismatches=runner._parse_summary(log,task)
            assert raw['checks']==count==c['checks'] and raw['mismatches']==mismatches
            assert raw['status']==('pass' if mismatches==0 else 'fail') and raw['failure_kind']==(None if mismatches==0 else 'semantic_mismatch')
            if c.get('family')=='edge':
                observed,bound=phase_context.context(log,c,edge_contract)
                assert (bound is None)==(mismatches==0)
            if mismatches:
                point=parser.counterexample(log,c);assert read(check/'counterexample.json')==point
                assert read(check/'feedback.json')['text']==feedback.render(c,adapter,point)
            return raw
        for row in report['rows']:
            task,arm=row['task'],row['arm'];sample=run/'results/samples'/arm/task;work=sample/'worker'
            assert row==read(sample/'row.json')
            command=read(sample/'worker_command.json');shared.command(command,sample/'worker.log',allow_timeout=True)
            assert row['solve_deadline_reached']==command['timeout'] and row['solve_elapsed_s']==command['elapsed_s']
            assert PurePosixPath(command['argv'][2]).name=='worker.py'
            cloud=PurePosixPath(spec['cloud_root'])
            sample_cloud=cloud/'results/samples'/arm/task
            assert command['argv'][1:]==['-B',str(cloud/'worker.py'),'--out',str(sample_cloud/'worker'),
                '--task',task,'--arm',arm,'--kit',spec['kit'],'--resource-check',str(cloud/'guard/resource_check.json')]
            judge_command=read(sample/'judge_command.json')
            assert judge_command['argv'][1:]==['-B',str(cloud/'pilot.py'),'judge','--task',task,
                '--solution',str(sample_cloud/'worker/solution.v'),'--out',str(sample_cloud/'judge'),'--kit',spec['kit']]
            shared.command(read(sample/'judge_command.json'),sample/'judge.log')
            verdict=shared.judge(sample/'judge',work/'solution.v',task)
            assert row['verdict']==verdict and row['verdict_sha256']==sha(sample/'judge/verdict.json') and row['solution_sha256']==sha(work/'solution.v')
            source=root/'kit/bench/tasks_veval'/task;prompt=(source/'prompt.txt').read_text(encoding='utf-8')
            for name in ['prompt.txt','interface.txt']:
                if (source/name).exists():assert (work/'prompt_only'/name).read_bytes()==(source/name).read_bytes()
            assert set(p.name for p in (work/'prompt_only').iterdir())<=set(['prompt.txt','interface.txt'])
            if (source/'interface.txt').exists() and (source/'interface.txt').read_text(encoding='utf-8').strip():prompt+='\n\nInterface:\n'+(source/'interface.txt').read_text(encoding='utf-8')
            parser=candidate_parser
            feedback=candidate_feedback
            c=parser.parse(prompt)
            raw_prompt=(source/'prompt.txt').read_bytes().decode('utf-8')
            raw_interface=(source/'interface.txt').read_bytes().decode('utf-8') if (source/'interface.txt').exists() else ''
            assert {p.name for p in (work/'prompt_only').iterdir()}=={n for n in ['prompt.txt','interface.txt'] if (source/n).exists()}
            route,recipe=bound_route(work,run,arm,raw_prompt,raw_interface,(source/'interface.txt').exists(),generator)
            assert row['generation_route']==route['route'] and row['stage_generation_binding_verified'] is True
            assert row['route_receipt_sha256']==sha(work/'generation_route.json')
            assert row['synthesis_receipt_sha256']==(sha(work/'synthesis_receipt.json') if arm=='P' else None)
            assert row['producer_contract_sha256']==(recipe['contract_sha256'] if route['route']=='mechanical_onehot' else None)
            assert row['emitted_solution_sha256']==route['generated_solution_sha256']
            native_checks=[]
            def verify_probe(check,contract):
                assert (check/'inputs'/task/'tb.sv').read_text(encoding='utf-8')==parser.render_tb(contract,task)
                raw=probe(check,task,contract);native_checks.append(dict(index=check.name,status=raw['status'],checks=raw['checks'],mismatches=raw['mismatches']));return raw
            if route['route']=='mechanical_onehot':
                bound=mechanical_provenance(work,run,task,row,recipe,sample_cloud/'worker',runner,parser,verify_probe)
                journal=[]
            else:
                assert arm=='C' or recipe['emitted'] is False
                assert not (work/'emission').exists() and not (work/'native_receipts').exists()
                journal,first_body=model_requests(work,row,spec,generation,repair)
                firsts[(task,arm)]=first_body
                for item in read(work/'compile_journal.json') if (work/'compile_journal.json').exists() else []:
                    assert item['argv'][0]=='/workspace/AMD/2026.1/Vivado/bin/xvlog'
                    round_dir=PurePosixPath(item['argv'][-1]).parent.name
                    assert round_dir in ['compile-0','compile-1']
                    assert item['argv'][-1]==str(sample_cloud/'worker/work'/round_dir/'candidate.sv')
                bound=replay.replay(work,prompt,arm,c,baseline,runtime,parser,feedback,verify_probe,sha,read,command['timeout'])
                bound.update(original_model_replay_bound=True,synthesis_abstention_bound=arm=='P',native_execution_bound=True)
                if not command['timeout']:
                    wr=read(work/'worker_result.json')
                    assert wr['complete'] and wr['arm']==arm and wr['generation_route']=='model'
                    assert wr['actual_model_requests']==wr['requests']==len(journal) and wr['solution_sha256']==sha(work/'solution.v')
            total+=len(journal);unconfirmed+=len(journal)-sum(j['response_received'] for j in journal)
            bound.update(task=task,arm=arm,contract_status=c['status'],contract_family=c.get('family'),native_checks=native_checks,
                         generation_route=route['route'],generation_route_bound=True,input_bytes_bound=True,
                         source_hashes_bound=True,solution_bytes_bound=True)
            provenance.append(bound);rows.append(dict(row))
        assert total==report['actual_model_requests']<=spec['max_actual_model_requests'] and unconfirmed==report['unconfirmed_attempts']
        scorer=load('full_actual_pinned_scorer',root/'kit/official_reference/selftest/score.py')
        aggregate=metrics.aggregate(rows,spec['task_ids'],scorer)
        for key,value in aggregate.items():assert report[key]==value,key
        first_pairs=[]
        for task in spec['task_ids']:
            identities={r['arm']:r for r in provenance if r['task']==task}
            if identities['P']['generation_route']=='mechanical_onehot':
                assert identities['P']['first_reply_sha256'] is None
                first_pairs.append(dict(task=task,first_content_identical=None,applicability='not_applicable_mechanical'))
            else:
                assert firsts[(task,'C')]==firsts[(task,'P')]
                first_pairs.append(dict(task=task,first_content_identical=identities['C']['first_reply_sha256'] is not None and identities['C']['first_reply_sha256']==identities['P']['first_reply_sha256'],applicability='model_pair'))
        sys.path[:]=old_path
        result=dict(schema='onehot_synthesis_cp7_readonly_audit_v1',evidence_valid=True,historical_fixture_only=False,
            full156_evidence_valid=False,archive_sha256=sha(archive),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),
            expected_samples=2*len(spec['task_ids']),actual_model_requests=total,
            provenance=provenance,first_pairs=first_pairs,adoption=False,official_baseline_gain_measured=False,five_sample_measured=False,
            audit_model_calls=0,audit_eda_calls=0,limits=spec['limits'],**aggregate)
        result.update(metrics.decision(aggregate,provenance,rows))
    out.mkdir(parents=True);(out/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--spec-sha',required=True);
    a=p.parse_args();r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:r[k] for k in ['evidence_valid','qualified_for_new_full_regression','coefficients','repairs','regressions','actual_model_requests','unconfirmed_attempts','screening_eligible']}))
