"""Read-only fresh-call, functional feedback and native official-grade audit."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path,PurePosixPath
import re
import sys
import tempfile


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def audit(archive,out,spec_sha):
    assert not out.exists()
    helper=Path(__file__).resolve().parent.parent/'full156_postflight_20261004/audit.py'
    assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('fresh_archive_and_grade_verifier',helper)
    with tempfile.TemporaryDirectory(prefix='fresh-functional-audit-') as tmp:
        root=Path(tmp);manifest=shared.unpack(archive,root);run=root/'run'
        assert sha(run/'RUN_SPEC.json')==spec_sha==manifest['run_spec_sha256']
        spec=read(run/'RUN_SPEC.json');report=read(run/'results/summary.json')
        assert report['complete'] and report['passed'] and report['spec_sha256']==spec_sha
        assert report['first_generation_replayed'] is False
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
        parser=load('fresh_contract_dispatch',run/'prompt_map.py');feedback=load('fresh_factual_feedback',run/'point_feedback.py')
        baseline=load('fresh_extract',run/'package/baseline.py');runtime=load('fresh_original_functions',run/'package/agent/runtime.py')
        runner=load('fresh_native_summary',root/'dependencies/probe_runner.py')
        generation=(run/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
        repair=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
        rows=[];total=0;unconfirmed=0;firsts={};changes=[]
        order=[(t,a) for i,t in enumerate(spec['task_ids']) for a in (['A','C'] if i%2==0 else ['C','A'])]
        assert [(r['task'],r['arm']) for r in report['rows']]==order
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
            shared.command(read(sample/'judge_command.json'),sample/'judge.log')
            verdict=shared.judge(sample/'judge',work/'solution.v',task)
            assert row['verdict']==verdict and row['verdict_sha256']==sha(sample/'judge/verdict.json') and row['solution_sha256']==sha(work/'solution.v')
            source=root/'kit/bench/tasks_veval'/task;prompt=(source/'prompt.txt').read_text(encoding='utf-8')
            for name in ['prompt.txt','interface.txt']:
                if (source/name).exists():assert (work/'prompt_only'/name).read_bytes()==(source/name).read_bytes()
            assert set(p.name for p in (work/'prompt_only').iterdir())<=set(['prompt.txt','interface.txt'])
            if (source/'interface.txt').exists() and (source/'interface.txt').read_text(encoding='utf-8').strip():prompt+='\n\nInterface:\n'+(source/'interface.txt').read_text(encoding='utf-8')
            c=parser.parse(prompt);assert c['status']=='supported'
            journal=read(work/'requests.json');assert 1<=len(journal)<=2
            assert row['actual_model_requests']==len(journal);total+=len(journal)
            received=sum(j['response_received'] for j in journal);assert row['received_model_responses']==received
            unconfirmed+=len(journal)-received
            codes=[];previous=''
            compiles=read(work/'compile_journal.json')
            for number,entry in enumerate(compiles):
                evidence=work/'compile_receipts'/str(number);log=evidence/'owned_compile.log'
                assert not entry['timeout'] and not entry['launch_error'] and not entry['remaining_live_group']
                assert sha(log)==entry['log_sha256'] and log.stat().st_size==entry['log_bytes']
                assert entry['source_sha256']==entry['source_before_sha256']==entry['source_after_sha256']==sha(evidence/'source_before.sv')==sha(evidence/'source_after.sv')
            for i,entry in enumerate(journal):
                req=work/'requests'/str(i)/'request.json';assert entry['index']==i and not entry['replayed'] and entry['request_sha256']==sha(req)
                body=read(req);assert body['model']==spec['model'] and body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
                assert body['messages'][0]==dict(role='system',content=generation+('\n'+repair if i else ''))
                if not i:assert body['messages'][1]==dict(role='user',content=prompt)
                else:
                    text=body['messages'][1]['content'];prefix=prompt+'\nPrevious candidate:\n'+previous+'\nCandidate diagnostics:\n';assert text.startswith(prefix)
                    check=work/('map_check_'+str(i-1))
                    if check.exists():assert arm=='C' and text==prefix+read(check/'feedback.json')['text']
                    else:
                        lint=[e for e in compiles if PurePosixPath(e['argv'][-1]).parent.name=='compile-'+str(i-1)]
                        if lint:
                            n=compiles.index(lint[0]);log=(work/'compile_receipts'/str(n)/'owned_compile.log').read_text(encoding='utf-8')
                            expected='\n'.join(s for s in log.splitlines() if re.search('ERROR|WARNING|FATAL',s))[:2048] or log[-2048:]
                            assert text==prefix+expected
                        else:raise ValueError('Unexpected source-check repair in frozen compiled cohort; preserve evidence and strengthen readonly audit')
                if entry['response_received']:
                    resp=work/'requests'/str(i)/'response.json';assert entry['response_sha256']==sha(resp)
                    payload=read(resp);previous=baseline.extract(payload['choices'][0]['message'].get('content') or '','rtl');codes.append(previous)
                    if not i:firsts[(task,arm)]=(body,hashlib.sha256(payload['choices'][0]['message'].get('content','').encode()).hexdigest())
            final=(work/'solution.v').read_text(encoding='utf-8')
            if final!=previous:raise ValueError('Unexpected built-in declaration patch in this cohort; preserve and bind with a new readonly audit')
            checks=list(work.glob('map_check_*'))
            for check in checks:
                number=int(check.name.rsplit('_',1)[1]);assert arm=='C' and number<len(codes)
                assert read(check/'contract.json')==c and (check/'input.sv').read_text(encoding='utf-8')==codes[number]
                assert (check/'inputs'/task/'tb.sv').read_text(encoding='utf-8')==parser.render_tb(c,task)
                result=probe(check,task,c)
                if number==0 and result['status']=='pass':assert len(journal)==1 and final==codes[0]
            if arm=='C' and len(codes)>1:changes.append(task)
            if not command['timeout']:
                wr=read(work/'worker_result.json');assert wr['complete'] and wr['actual_model_requests']==len(journal) and wr['solution_sha256']==sha(work/'solution.v')
            rows.append(dict(task=task,arm=arm,level=verdict['level'],coefficient=verdict['coefficient'],actual_model_requests=len(journal),unconfirmed=len(journal)-received,solve_elapsed_s=command['elapsed_s'],judge_elapsed_s=verdict['elapsed_s']))
        assert total==report['actual_model_requests']<=12 and unconfirmed==report['unconfirmed_attempts']
        pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in spec['task_ids']}
        coefficients={arm:sum(p[arm]['coefficient'] for p in pairs.values())/3 for arm in ['A','C']}
        repairs=[t for t,p in pairs.items() if p['A']['level']<3 and p['C']['level']==3]
        regressions=[t for t,p in pairs.items() if p['C']['coefficient']<p['A']['coefficient']]
        qualified=not unconfirmed and not any(r['solve_deadline_reached'] for r in report['rows']) and all(pairs[t]['C']['level']==3 for t in spec['target_tasks']) and all(pairs[spec['correct_guard']][a]['level']==3 for a in ['A','C']) and not regressions and coefficients['C']>coefficients['A']
        assert coefficients==report['coefficients'] and repairs==report['repairs'] and regressions==report['regressions'] and qualified==report['candidate_qualified_for_full_regression']
        same_first=[]
        for t in spec['task_ids']:
            if (t,'A') in firsts and (t,'C') in firsts:
                assert firsts[(t,'A')][0]==firsts[(t,'C')][0];same_first.append(dict(task=t,content_identical=firsts[(t,'A')][1]==firsts[(t,'C')][1]))
        result=dict(schema='functional_fresh_offline_audit_v1',evidence_valid=True,archive_sha256=sha(archive),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),rows=rows,
            coefficients=coefficients,repairs=repairs,regressions=regressions,first_reply_pairs=same_first,actual_model_requests=total,unconfirmed_attempts=unconfirmed,
            C_model_repair_tasks=changes,candidate_qualified_for_full_regression=qualified,first_generation_replayed=False,adoption=False,new_full_score=False,
            audit_model_calls=0,audit_eda_calls=0,limits=spec['limits'])
    out.mkdir(parents=True);(out/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--spec-sha',required=True)
    a=p.parse_args();r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:r[k] for k in ['evidence_valid','coefficients','repairs','regressions','actual_model_requests','unconfirmed_attempts','candidate_qualified_for_full_regression']}))
