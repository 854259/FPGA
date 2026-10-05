"""Read-only fresh-call, functional feedback and native official-grade audit."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path,PurePosixPath
import re
import sys
import metrics
import replay
import tempfile


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def audit(archive,out,spec_sha):
    assert sys.version_info[:2]==(3,12)
    assert not out.exists()
    helper=Path(__file__).resolve().parent.parent/'full156_postflight_20261004/audit.py'
    assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('fresh_archive_and_grade_verifier',helper)
    with tempfile.TemporaryDirectory(prefix='fresh-functional-audit-') as tmp:
        root=Path(tmp);manifest=shared.unpack(archive,root);run=root/'run'
        assert sha(run/'RUN_SPEC.json')==spec_sha==manifest['run_spec_sha256']
        spec=read(run/'RUN_SPEC.json');report=read(run/'results/summary.json')
        for name in [__file__,metrics.__file__,replay.__file__]:
            p=Path(name)
            assert sha(p)==spec['source_hashes'][p.name]
        assert len(spec['task_ids'])==8 and spec['schema']=='fsm_feedback_pilot_frozen_v1' and spec['arms']==['C','F']
        assert spec['task_ids']==sorted(metrics.FSMS+metrics.GUARDS+[metrics.UNKNOWN])
        assert spec['max_actual_model_requests']==32 and spec['solve_deadline_s']==spec['judge_timeout_s']==300
        assert spec['max_worker_requests_per_arm']==2 and spec['retries']==0
        assert sha(run/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
        assert not (run/'context.py').exists() and not (run/'package/agent/d_runtime.py').exists()
        assert report['complete'] and report['passed'] and report['spec_sha256']==spec_sha
        assert report['first_generation_replayed'] is False
        environment=read(run/'results/ENVIRONMENT_PREFLIGHT.json')
        assert environment['verified'] and environment['vivado_bin']=='/workspace/AMD/2026.1/Vivado/bin' and environment['udev_stub']=='/workspace/team/udev-stub'
        assert environment['model_calls']==environment['eda_calls']==0
        assert set(environment['tools'])==set(['xvlog','xelab','xsim','vivado'])
        for n,d in environment['tools'].items():assert d['path']=='/workspace/AMD/2026.1/Vivado/bin/'+n and re.fullmatch('[0-9a-f]{64}',d['sha256'])
        for n,h in spec['source_hashes'].items():assert sha(run/n)==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(root/'dependencies'/n)==h,n
        inputs=read(run/'INPUT_MANIFEST.json');resource=read(root/'guard/resource_check.json');guard=read(root/'guard/status.json')
        assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
        assert guard['stage_rc']==0 and not guard['model_managed'] and not guard['instance_managed']
        assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
        assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
        for n,h in inputs['input_sha256'].items():
            if n.split('/')[0] in spec['task_ids']:assert sha(root/'kit/bench/tasks_veval'/n)==h,n
        for n,h in inputs['official_sha256'].items():assert sha(root/'kit/official_reference'/n)==h,n
        sys.path.insert(0,str(run))
        control_parser=load('fresh_control_dispatch',run/'prompt_map.py');control_feedback=load('fresh_control_feedback',run/'point_feedback.py')
        candidate_parser=load('fresh_fsm_dispatch',run/'fsm_dispatch.py');candidate_feedback=load('fresh_fsm_feedback',run/'fsm_feedback.py')
        baseline=load('fresh_extract',run/'package/baseline.py');runtime=load('fresh_original_functions',run/'package/agent/runtime.py')
        runner=load('fresh_native_summary',root/'dependencies/probe_runner.py')
        generation=(run/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
        repair=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
        rows=[];total=0;unconfirmed=0;firsts={};provenance=[]
        assert [(r['task'],r['arm']) for r in report['rows']]==metrics.order(spec['task_ids'])
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
            parser=candidate_parser if arm=='F' else control_parser
            feedback=candidate_feedback if arm=='F' else control_feedback
            c=parser.parse(prompt)
            journal=read(work/'requests.json');assert 1<=len(journal)<=2
            assert row['actual_model_requests']==len(journal);total+=len(journal)
            received=sum(j['response_received'] for j in journal);assert row['received_model_responses']==received
            unconfirmed+=len(journal)-received
            for i,entry in enumerate(journal):
                req=work/'requests'/str(i)/'request.json';assert entry['index']==i and not entry['replayed'] and entry['request_sha256']==sha(req)
                body=read(req);assert body['model']==spec['model'] and body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
                assert body['messages'][0]==dict(role='system',content=generation+('\n'+repair if i else ''))
                if entry['response_received']:
                    resp=work/'requests'/str(i)/'response.json';assert entry['response_sha256']==sha(resp)
                if not i:firsts[(task,arm)]=body
            native_checks=[]
            def verify_probe(check,contract):
                assert (check/'inputs'/task/'tb.sv').read_text(encoding='utf-8')==parser.render_tb(contract,task)
                raw=probe(check,task,contract);native_checks.append(dict(index=check.name,status=raw['status'],checks=raw['checks'],mismatches=raw['mismatches']));return raw
            bound=replay.replay(work,prompt,arm,c,baseline,runtime,parser,feedback,verify_probe,sha,read,command['timeout'])
            bound.update(task=task,arm=arm,contract_status=c['status'],contract_family=c.get('family'),native_checks=native_checks)
            provenance.append(bound)
            if not command['timeout']:
                wr=read(work/'worker_result.json');assert wr['complete'] and wr['actual_model_requests']==len(journal) and wr['solution_sha256']==sha(work/'solution.v')
            rows.append(dict(row))
        assert total==report['actual_model_requests']<=spec['max_actual_model_requests'] and unconfirmed==report['unconfirmed_attempts']
        scorer=load('full_actual_pinned_scorer',root/'kit/official_reference/selftest/score.py')
        aggregate=metrics.aggregate(rows,spec['task_ids'],scorer)
        for key,value in aggregate.items():assert report[key]==value,key
        first_pairs=[]
        for task in spec['task_ids']:
            assert firsts[(task,'C')]==firsts[(task,'F')]
            identities={r['arm']:r['first_reply_sha256'] for r in provenance if r['task']==task}
            first_pairs.append(dict(task=task,first_content_identical=identities['C'] is not None and identities['C']==identities['F']))
        result=dict(schema='fsm_feedback_pilot_readonly_audit_v1',evidence_valid=True,historical_fixture_only=False,
            full156_evidence_valid=False,archive_sha256=sha(archive),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),
            expected_samples=2*len(spec['task_ids']),actual_model_requests=total,
            provenance=provenance,first_pairs=first_pairs,adoption=False,official_baseline_gain_measured=False,five_sample_measured=False,
            audit_model_calls=0,audit_eda_calls=0,limits=spec['limits'],**aggregate)
        result.update(metrics.decision(aggregate,provenance,rows))
    out.mkdir(parents=True);(out/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--spec-sha',required=True);
    a=p.parse_args();r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:r[k] for k in ['evidence_valid','full156_evidence_valid','coefficients','repairs','regressions','actual_model_requests','unconfirmed_attempts','screening_eligible']}))
