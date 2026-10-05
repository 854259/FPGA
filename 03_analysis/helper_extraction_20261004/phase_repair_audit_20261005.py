"""Read-only terminal provenance audit for T8; zero model/EDA operations."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

SPEC_SHA='86ac7739c5fa6d6084af42c299fb5625690c08ddc6901c7f132313e260425890'
PAIRED_SHA='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(name,p):
    spec=importlib.util.spec_from_file_location(name,p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    assert sha(a.paired)==PAIRED_SHA
    paired=load('audit_owned',a.paired);paired.check_resource(a.resource_check,a.kit,first=True)
    root=a.run;assert sha(root/'RUN_SPEC.json')==SPEC_SHA
    a.out.mkdir(parents=True,exist_ok=False);started=time.monotonic();used={}
    def read(p):
        p=Path(p);used[str(p.relative_to(root))]=sha(p);return p.read_text()
    def data(p): return json.loads(read(p))
    def digest(p): read(p);return sha(p)
    spec=data(root/'RUN_SPEC.json');summary=data(root/'results/summary.json');guard=data(root/'guard/status.json')
    assert summary['complete'] and summary['valid'] and not summary['error']
    assert guard['complete'] and guard['passed'] and guard['model_unchanged'] and guard['protected_files_unchanged']
    assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining'] and guard['own_slot_released']
    for name,h in spec['source_hashes'].items(): assert digest(root/name)==h,name
    for name,h in spec['dependency_hashes'].items(): assert sha(Path(spec['dependencies_cloud'])/name)==h,name
    sys.path.insert(0,str(root))
    import edge_dispatch,edge_contract,edge_feedback,phase_context
    baseline=load('phase_audit_baseline',root/'package/baseline.py')
    runtime=load('phase_audit_runtime',root/'package/agent/map_runtime.py')
    stats={task:{arm:dict(l3=0,native_and_l3=0,solve_elapsed_s=0.,judge_elapsed_s=0.,output_hashes=[]) for arm in ('S','P')} for task in spec['task_ids']}
    rows=[]
    for item in spec['order']:
        task,arm,repeat=item['task'],item['arm'],item['repeat']
        folder=root/'results/samples'/('r'+str(repeat))/task/arm;w=folder/'worker'
        for name in ('worker.receipt.json','judge.receipt.json'):
            r=data(folder/name)
            assert r['returncode']==0 and not r['timeout'] and not r['launch_error'] and not r['remaining_live_group']
            assert digest(Path(r['log']))==r['log_sha256']
        journal=data(w/'requests.json');assert len(journal)==2
        replies=[];requests=[]
        for i,r in enumerate(journal):
            req=w/'requests'/str(i)/'request.json';resp=w/'requests'/str(i)/'response.json'
            assert digest(req)==r['request_sha256'] and digest(resp)==r['response_sha256'] and r['response_received']
            assert r['replayed']==(i==0) and r['actual_post_attempted']==(i==1)
            requests.append(data(req));replies.append(baseline.extract(data(resp)['choices'][0]['message'].get('content') or '', 'rtl'))
        assert requests[0]==data(root/'replay'/task/'0/request.json')
        assert digest(w/'requests/0/response.json')==digest(root/'replay'/task/'0/response.json')
        original=data(root/'replay'/task/'1/request.json')
        assert requests[1]['messages'][0]==original['messages'][0]
        assert all(requests[1][k]==original[k] for k in ('model','temperature','top_p','max_tokens'))
        contract=edge_dispatch.parse(requests[0]['messages'][1]['content'])
        assert contract['status']=='supported' and contract['family']=='edge'
        for attempt in (0,1):
            f=w/('map_check_'+str(attempt))
            if not f.exists():
                assert attempt==1
                continue
            assert data(f/'contract.json')==contract
            native=data(f/'probe/result.json')
            assert native['inputs_unchanged'] and native['runner_sha256']==spec['dependency_hashes']['probe_runner.py']
            assert digest(f/'input.sv')==native['solution_sha256']==digest(f/'probe/dut.sv')
            tb=f/'inputs'/task/'tb.sv'
            expected_tb=edge_dispatch.render_tb(contract,task)
            if arm=='P': expected_tb=phase_context.instrument_tb(expected_tb,contract)
            assert read(tb)==expected_tb and digest(tb)==native['tb_sha256']==digest(f/'probe/tb.sv')
            assert read(f/'input.sv')==replies[attempt]
            assert [s['name'] for s in native['stages']]==['xvlog','xelab','xsim']
            for s in native['stages']:
                assert not s['timeout'] and not s['launch_error'] and not s['remaining_live_group'] and s['returncode']==0
                assert digest(Path(s['log']))==s['log_sha256']
            log=read(f/'probe/xsim.log')
            marks=re.findall(r'^R2_PROBE_RESULT task=(\w+) checks=(\d+) mismatches=(\d+)\s*$',log,re.M)
            assert len(marks)==1 and marks[0]==(task,str(native['checks']),str(native['mismatches']))
            assert native['checks']==contract['checks']
            if native['mismatches']:
                point=edge_contract.counterexample(log,contract);old=edge_feedback.render(contract,native,point)
                if arm=='P':
                    observed,bound=phase_context.context(log,contract,edge_contract)
                    text=phase_context.render_feedback(contract,bound,edge_feedback)
                    assert data(f/'phase_context.json')==dict(rows=observed,bound=bound,original_feedback=old)
                else: text=old
                assert data(f/'counterexample.json')==point and data(f/'feedback.json')['text']==text
                if attempt==0:
                    assert requests[1]['messages'][1]['content']==original['messages'][1]['content'].rsplit('\nCandidate diagnostics:\n',1)[0]+'\nCandidate diagnostics:\n'+text
            else:
                assert native['status']=='pass'
        compiles=data(w/'compile_journal.json')
        for i,c in enumerate(compiles):
            assert not c['timeout'] and not c['launch_error'] and not c['remaining_live_group']
            p=w/'compile_receipts'/str(i)
            assert digest(p/'source_before.sv')==c['source_before_sha256']==c['source_after_sha256']==digest(p/'source_after.sv')
            assert digest(p/'owned_compile.log')==c['log_sha256']
        assert read(w/'compile_receipts/0/source_before.sv')==replies[0]
        final=read(w/'solution.v');expected_final=replies[1]
        events=[json.loads(x) for x in read(w/'trace.jsonl').splitlines()]
        if any(x.get('tool')=='declaration_fix' and x.get('round')==1 for x in events):
            previous=compiles[-2];log=read(Path(previous['log']))
            feedback='\n'.join(x for x in log.splitlines() if re.search('ERROR|WARNING|FATAL',x))[:2048] or log[-2048:]
            expected_final=runtime.repair_ansi_declarations(replies[1],feedback)
        assert final==expected_final
        row=data(folder/'row.json');bound=data(folder/'judge/bound_verdict.json');v=bound['verdict']
        assert digest(w/'solution.v')==row['solution_sha256']==bound['solution_sha256']
        receipt=data(folder/'judge/judge_receipt.json')
        assert not receipt['errors'] and receipt['judge_rc']==0 and receipt['scratch_retained'] is None
        for name,entry in receipt['evidence'].items():
            p=folder/'judge/judge_work_logs'/name
            assert digest(p)==entry['sha256'] and p.stat().st_size==entry['bytes']
        assert digest(folder/'judge/judge_work_logs/dut.sv')==row['solution_sha256']
        assert v==row['verdict']==data(folder/'judge/verdict.json')
        assert v['task_id']==task and v['judge_evidence_complete'] and not v['tool_error']
        assert v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[v['level']]
        native=w/'map_check_1/probe/result.json'
        native_pass=native.exists() and data(native)['status']=='pass' and data(native)['mismatches']==0
        assert row['native_pass']==native_pass
        if native.exists():assert data(native)['solution_sha256']==row['solution_sha256']
        entry=stats[task][arm];entry['l3']+=v['level']==3;entry['native_and_l3']+=native_pass and v['level']==3
        entry['solve_elapsed_s']+=row['solve_elapsed_s'];entry['judge_elapsed_s']+=row['judge_elapsed_s']
        entry['output_hashes'].append(row['solution_sha256'])
        rows.append(dict(task=task,arm=arm,repeat=repeat,level=v['level'],success=native_pass and v['level']==3))
    assert len(rows)==20 and len(summary['rows'])==20 and summary['actual_model_requests']==summary['received_model_responses']==20
    assert [data(root/'results/samples'/('r'+str(i['repeat']))/i['task']/i['arm']/'row.json') for i in spec['order']]==summary['rows']
    fixed=harmed=unchanged=0
    for task in spec['task_ids']:
        for repeat in range(5):
            pair={r['arm']:r for r in rows if r['task']==task and r['repeat']==repeat}
            fixed+=not pair['S']['success'] and pair['P']['success']
            harmed+=pair['S']['success'] and not pair['P']['success']
            unchanged+=pair['S']['success']==pair['P']['success']
    signal=all(s['P']['native_and_l3']>=s['S']['native_and_l3'] for s in stats.values()) and fixed>harmed
    result=dict(complete=True,valid=True,source_commit=spec['source_commit'],spec_sha256=SPEC_SHA,model_calls=0,eda_calls=0,
        audited_samples=20,actual_model_calls=20,confirmed_responses=20,first_generation_replayed=True,
        descriptive_paired_repairs=fixed,descriptive_paired_regressions=harmed,descriptive_paired_unchanged=unchanged,
        per_task=stats,mechanism_signal_gate_passed=signal,adopted=False,full_batch_complete=False,independent_tasks=0,
        scope='Two already-seen checkpoints, correlated conditional repeats; not ten independent designs or official five-sample full solves.',
        generation_stage_elapsed_s=summary['elapsed_s'],generation_guard_elapsed_s=guard['elapsed_s'],audit_elapsed_s=time.monotonic()-started,
        decision='Signal only; independent admission still required.' if signal else 'Reject expanding this feedback version; no proven conditional benefit.',
        provenance_files=len(used))
    paired.check_resource(a.resource_check,a.kit)
    for name,h in used.items():assert sha(root/name)==h,name
    (a.out/'PROVENANCE_MANIFEST.json').write_text(json.dumps(used,indent=2)+'\n')
    (a.out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('run','paired','resource-check','kit','out'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
