"""Local, read-only audit of checkpoint transport, native probes and decisions."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def audit(archive,out,spec_sha):
    assert not out.exists()
    helper=Path(__file__).resolve().parent.parent/'full156_postflight_20261004/audit.py'
    assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('map_flow_archive',helper)
    with tempfile.TemporaryDirectory(prefix='map-flow-audit-') as temporary:
        root=Path(temporary);manifest=shared.unpack(archive,root);run=root/'run'
        assert sha(run/'RUN_SPEC.json')==spec_sha==manifest['run_spec_sha256']
        spec=read(run/'RUN_SPEC.json');report=read(run/'results/summary.json')
        for n,h in spec['source_hashes'].items():assert sha(run/n)==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(root/'dependencies'/n)==h,n
        guard=read(root/'guard/status.json');resource=read(root/'guard/resource_check.json')
        assert all(guard[k] is True for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
        assert guard['stage_rc']==0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert not guard['model_managed'] and not guard['instance_managed']
        assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
        inputs=read(run/'INPUT_MANIFEST.json')
        assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
        assert report['complete'] and report['passed'] and report['spec_sha256']==spec_sha
        parser=load('map_flow_parser',run/'prompt_map.py');baseline=load('map_flow_extract',run/'package/baseline.py')
        runner=load('map_flow_summary',root/'dependencies/probe_runner.py')
        runner.TASK_CHECKS={t:read(run/'raw_evidence/inputs'/t/'contract.json')['checks'] for t in spec['task_ids']}
        def probe(folder,task,solution,tb,record):
            raw=read(folder/'result.json');adapter=read(folder/'adapter_receipt.json')
            assert all(adapter[k]==v for k,v in raw.items()) and adapter==record
            assert adapter['inherited_result_sha256']==sha(folder/'result.json')
            assert adapter['inherited_runner_sha256']==sha(root/'dependencies/probe_runner.py')
            assert adapter['oracle_adapter_sha256']==sha(root/'dependencies/paired_checkpoint.py')
            assert raw['solution_sha256']==sha(solution)==sha(folder/'dut.sv')
            assert raw['tb_sha256']==sha(tb)==sha(folder/'tb.sv') and raw['inputs_unchanged']
            assert raw['task']==task and len(raw['stages'])==3
            for stage,name in zip(raw['stages'],['xvlog','xelab','xsim']):
                assert stage['name']==name and PurePosixPath(stage['argv'][0]).name==name
                assert stage['returncode']==0 and not stage['timeout'] and not stage['launch_error'] and not stage['remaining_live_group']
                shared.command(stage,folder/(name+'.log'))
                assert not runner.ENVIRONMENT_ERROR.search((folder/(name+'.log')).read_text(errors='replace'))
            log=(folder/'xsim.log').read_text()
            checks,mismatches=runner._parse_summary(log,task)
            assert raw['checks']==checks==runner.TASK_CHECKS[task] and raw['mismatches']==mismatches
            assert raw['status']==('pass' if mismatches==0 else 'fail')
            assert raw['failure_kind']==(None if mismatches==0 else 'semantic_mismatch')
            return parser.counterexample(log,read(run/'raw_evidence/inputs'/task/'contract.json')) if mismatches else None
        total=0;rows=[];order=[(t,a) for i,t in enumerate(spec['task_ids']) for a in (['A','C'] if i%2==0 else ['C','A'])]
        assert [(r['task'],r['arm']) for r in report['rows']]==order
        generation=(run/'package/skill/rtl-generation/SKILL.md').read_text()
        repair=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
        for row in report['rows']:
            task,arm=row['task'],row['arm'];folder=run/'results/workers'/task/arm;source=run/'raw_evidence/inputs'/task
            wr=read(folder/'worker_result.json');assert wr==row['worker'] and wr['complete']
            assert wr['solution_sha256']==sha(folder/'solution.v')
            shared.command(row['supervisor'],run/'results/workers'/task/(arm+'.supervisor.log'))
            assert row['supervisor']['returncode']==0 and not row['supervisor']['timeout'] and not row['supervisor']['remaining_live_group']
            journal=read(folder/'requests.json');assert len(journal)==wr['requests'] and 1<=len(journal)<=2
            assert wr['actual_model_requests']==len(journal)-1;total+=len(journal)-1
            prompt=(source/'prompt.txt').read_text()
            if (source/'interface.txt').exists() and (source/'interface.txt').read_text().strip():prompt+='\n\nInterface:\n'+(source/'interface.txt').read_text()
            previous=''
            for i,entry in enumerate(journal):
                req=folder/'requests'/str(i)/'request.json';resp=folder/'requests'/str(i)/'response.json'
                assert entry['index']==i and entry['replayed']==(i==0) and entry['response_received']
                assert entry['request_sha256']==sha(req) and entry['response_sha256']==sha(resp)
                body=read(req);payload=read(resp)
                assert body['messages'][0]==dict(role='system',content=generation+('\n'+repair if i else ''))
                assert body['model']==spec['model'] and body['temperature']==0 and body['max_tokens']==8192 and body['top_p']==1
                if i==0:
                    assert body==read(source/'initial_request.json') and resp.read_bytes()==(source/'initial_response.json').read_bytes()
                    assert body['messages'][1]==dict(role='user',content=prompt)
                else:
                    # This cohort initially compiles; any repair must be from the actual map counterexample.
                    assert arm=='C'
                    mapfolder=folder/'map_check_0'
                    point=read(mapfolder/'counterexample.json')
                    text='ERROR: Candidate simulation disagrees with the supplied Karnaugh map. At '+', '.join(k+'='+str(v) for k,v in point['inputs'].items())+', '+point['output']+' should be '+str(point['expected'])+', but the candidate produced '+point['observed']+'.'
                    assert body['messages'][1]==dict(role='user',content=prompt+'\nPrevious candidate:\n'+previous+'\nCandidate diagnostics:\n'+text)
                previous=baseline.extract(payload['choices'][0]['message'].get('content') or '', 'rtl')
            assert (folder/'solution.v').read_text()==previous
            if arm=='A':assert (folder/'solution.v').read_text()==(source/'archived_candidate.sv').read_text()
            for entry in read(folder/'compile_journal.json'):
                log=folder/'work'/PurePosixPath(entry['log']).parent.name/'owned_compile.log'
                shared.command(entry,log)
                assert entry['returncode']==0 and not entry['timeout'] and not entry['remaining_live_group']
                assert entry['source_sha256']==sha(log.parent/'candidate.sv')
            for check in folder.glob('map_check_*'):
                assert arm=='C' and read(check/'contract.json')==parser.parse(prompt)
                assert (check/'tb.sv').read_text()==parser.render_tb(parser.parse(prompt),task)
                record=read(check/'probe/adapter_receipt.json')
                point=probe(check/'probe',task,check/'input.sv',check/'tb.sv',record)
                if point:assert read(check/'counterexample.json')==point
            probe(run/'results/final_probes'/task/arm,task,folder/'solution.v',source/'tb.sv',row['probe'])
            rows.append(dict(task=task,arm=arm,status=row['probe']['status'],mismatches=row['probe']['mismatches'],actual_model_requests=wr['actual_model_requests']))
        assert total==report['actual_model_requests']<=8
        pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in spec['task_ids']}
        repairs=[t for t,p in pairs.items() if p['A']['status']=='fail' and p['C']['status']=='pass']
        regressions=[t for t,p in pairs.items() if p['A']['status']=='pass' and p['C']['status']!='pass']
        assert repairs==report['repairs'] and regressions==report['regressions']
        assert report['correct_guard_unchanged'] is True
        assert report['candidate_qualified_for_fresh_generation']==(len(repairs)>=2 and not regressions)
        result=dict(evidence_valid=True,archive_sha256=sha(archive),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),
            rows=rows,repairs=repairs,regressions=regressions,actual_model_requests=total,
            candidate_qualified_for_fresh_generation=report['candidate_qualified_for_fresh_generation'],
            adoption=False,new_full_score=False,first_generation_cost_measured=False,
            audit_model_calls=0,audit_eda_calls=0,limits=spec['limits'])
    out.mkdir(parents=True);(out/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--spec-sha',required=True)
    a=p.parse_args();r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:v for k,v in r.items() if k not in ['rows','limits']}))
