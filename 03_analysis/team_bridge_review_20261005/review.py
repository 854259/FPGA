"""Readonly reconstruction of completed teammate integration evidence.

Never runs teammate drivers, models, native tools or servers. Fake replies are
constructed controls and cannot become model quality/independent-task scores.
"""
import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path,PurePosixPath
import re
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent
OWNER=ROOT.parent/'formal_bridge_v2_20261005'
ARCHIVES={
    'T5':('137826f9d3099fee84c2b9f89b1931704b49ec009e5cf89b85636418b4a65c80',763,'4190b4ccf0bc6ead8406f5d3491f8bd62988e6e398e151cfaa233693dc02cc76'),
    'T6':('861ffc2e2f85e7617ea09913a331cc4c4bc4896322caf8cff1fcc60f9bd84e16',69,'66e29737f6736f0586eea827f0a894e9f9eca28871ae895f8b167dddf48b73cf')}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def load(name,p):
    spec=importlib.util.spec_from_file_location(name,p);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module


def unpack(label,root):
    archive=ROOT/'raw_evidence'/(label+'.zip');h,count,driver=ARCHIVES[label]
    assert sha(archive)==h
    with zipfile.ZipFile(archive) as z:
        names=z.namelist();assert len(names)==len(set(names))==count+1
        m=json.loads(z.read('ARCHIVE_MANIFEST.json'));assert set(names)==set(m['files'])|{'ARCHIVE_MANIFEST.json'}
        for n,expected in m['files'].items():
            path=PurePosixPath(n)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in n
            data=z.read(n);assert len(data)<50*1024**2 and hashlib.sha256(data).hexdigest()==expected
            p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    spec=read(root/'owner_copy/RUN_SPEC.json')
    assert sha(root/'owner_copy/RUN_SPEC.json')==sha(OWNER/'RUN_SPEC.json')=='b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'
    for n,h in spec['source_hashes'].items():assert sha(root/'owner_copy'/n)==sha(OWNER/n)==h,n
    plan=read(root/'PLAN.json');assert plan['driver_sha256']==driver and plan['owner_spec_sha256']==sha(OWNER/'RUN_SPEC.json')
    drivers=list((root/'source').rglob('*.py'));assert len(drivers)==1 and sha(drivers[0])==driver
    assert sha(root/'SOURCE.zip')==plan['source_zip_sha256']
    guard=read(root/'guard/status.json');resource=read(root/'guard/resource_check.json')
    assert all(guard[k] is True for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
    assert not guard['model_managed'] and not guard['instance_managed'] and guard['stage_rc']==0
    assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    assert guard['model_idle_after']['processing_slots']==0 and guard['model_idle_after']['model_pid_owns_port']
    assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
    inputs=read(root/'owner_copy/INPUT_MANIFEST.json')
    assert resource['protected']['tasks']==inputs['input_sha256'] and len(inputs['input_sha256'])==936
    assert resource['protected']['official']==inputs['official_sha256'] and len(inputs['official_sha256'])==35
    ticket=read(root/'FINAL_TICKET.json');assert ticket['state']=='completed' and ticket['ticket']==(35 if label=='T5' else 36)
    report=read(root/'results/summary.json');assert report['complete'] and report['passed'] and report['actual_model_requests']==0
    assert report['independent_tasks']==0 and not report['full_batch_complete']
    return report,drivers[0],count


def pure_shift_factories(path):
    """Extract only two pinned pure string factories; forbid imports/effects."""
    tree=ast.parse(path.read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['prompt','source']]
    assert len(nodes)==2 and all(not n.decorator_list for n in nodes)
    allowed=(ast.FunctionDef,ast.arguments,ast.arg,ast.Assign,ast.Return,ast.Name,ast.Load,ast.Store,
             ast.Constant,ast.JoinedStr,ast.FormattedValue,ast.BinOp,ast.Add,ast.Sub,ast.IfExp,
             ast.Compare,ast.Eq,ast.Call)
    for node in nodes:
        for part in ast.walk(node):
            assert isinstance(part,allowed),type(part).__name__
            if isinstance(part,ast.Call):assert isinstance(part.func,ast.Name) and part.func.id=='str'
    namespace={'__builtins__':{'str':str}}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['prompt'],namespace['source']


def expected_bad_count(c):
    state=None;count=0;first=None;mask=(1<<c['width'])-1;r=c['roles']
    for i,step in enumerate(c['steps']):
        if step['previous'] is not None and state!=step['previous']:
            count+=1
            if first is None:first=(i,'stable',state)
        inputs=step['inputs']
        if inputs[r['load']]:state=inputs[r['data']]&mask
        elif inputs[r['enable']]:
            assert state is not None
            amount=inputs[r['amount']]
            state=((state<<[1,8][amount]) if amount<2 else state>>[1,8][amount-2])&mask
        if state!=step['expected']:
            count+=1
            if first is None:first=(i,'cycle',state)
    assert count>0 and first is not None
    return count,first


def native(prefix,code,tb,c,count,runner,bridge):
    result=read(prefix/'result.json');assert result['inputs_unchanged']
    assert result['task']=='ContractProbe' and result['checks']==c['checks'] and result['mismatches']==count
    assert result['status']==('fail' if count else 'pass') and result['failure_kind']==('semantic_mismatch' if count else None)
    assert result['solution_sha256']==sha(prefix/'dut.sv')==hashlib.sha256(code.encode()).hexdigest()
    assert result['tb_sha256']==sha(prefix/'tb.sv')==hashlib.sha256(tb.encode()).hexdigest()
    assert result['runner_sha256']==sha(OWNER/'package/agent/probe_runner.py')
    assert len(result['stages'])==3
    tails=[['-sv','--nolog','dut.sv','tb.sv'],['R2Probe','-s','r2_probe','--nolog','-timescale','1ns/1ps'],['r2_probe','-runall','-nolog']]
    for stage,name,tail in zip(result['stages'],['xvlog','xelab','xsim'],tails):
        assert stage['name']==name and stage['argv'][1:]==tail
        assert stage['argv'][0]==('/workspace/AMD/2026.1/Vivado/bin/'+name if bridge else name)
        assert stage['returncode']==0 and not stage['timeout'] and not stage['launch_error']
        assert math.isfinite(stage['elapsed_s']) and stage['elapsed_s']>=0
        log=prefix/(name+'.log');assert sha(log)==stage['log_sha256'] and log.stat().st_size==stage['log_bytes']
        text=log.read_text(encoding='utf-8');assert not runner.ENVIRONMENT_ERROR.search(text) and 'FAKE_TOOL_NO_AMD_EXECUTION' not in text
        if bridge:assert stage['session_policy']=='inherit_supervised_worker_group'
    runner.TASK_CHECKS={'ContractProbe':c['checks']}
    assert runner._parse_summary((prefix/'xsim.log').read_text(encoding='utf-8'),'ContractProbe')==(c['checks'],count)
    return result


def shift(root,report,driver):
    prompt,source=pure_shift_factories(driver)
    agent=OWNER/'package/agent';old=sys.modules.get('reserved_keywords')
    try:
        sys.modules['reserved_keywords']=load('review_reserved',agent/'reserved_keywords.py')
        parser=load('review_shift',agent/'shift_contract.py');formatter=load('review_formatter',agent/'point_feedback.py')
        runner=load('review_native_reader',agent/'probe_runner.py')
        generation=(OWNER/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
        repair=(OWNER/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
        checks=[];requests=[];probe_count=0;compile_count=0
        for width in [8,17,64]:
            text=prompt(width);c=parser.parse(text);c['kind']='shift';assert c['status']=='supported' and c['width']==width
            tb=parser.render_tb(c,'ContractProbe');good=source(width,False);bad=source(width,True);badcount,first=expected_bad_count(c)
            for label,code,count in [('good',good,0),('bad',bad,badcount)]:
                folder=root/'results'/f'w{width}_legacy_{label}'
                assert (folder/'inputs/source.sv').read_text(encoding='utf-8')==code
                assert (folder/'inputs/ContractProbe/tb.sv').read_text(encoding='utf-8')==tb
                assert sha(folder/'inputs/probe_runner.py')==sha(agent/'probe_runner.py')
                native(folder/'probe',code,tb,c,count,runner,False);probe_count+=1
            for case,codes in [('correct',[good]),('repair',[bad,good]),('persistent',[bad,bad])]:
                folder=root/'results'/f'w{width}_{case}';calls=read(folder/'fake_requests.json');reply=read(folder/'http_reply.json')
                assert len(calls)==len(codes) and reply['solution']==codes[-1]
                work=folder/'http_worker';assert (work/'solution.v').read_text(encoding='utf-8')==codes[-1]
                assert (work/'trace.jsonl').read_text(encoding='utf-8')==reply['trace']
                events=[json.loads(s) for s in reply['trace'].splitlines()]
                assert [e['round'] for e in events if e['tool']=='llm']==list(range(len(codes)))
                assert sum(e['tool']=='lint' and e['rc']==0 for e in events)==len(codes)
                facts=[e for e in events if e['tool']=='functional_probe'];assert len(facts)==len(codes)
                feedback=''
                for i,(code,body) in enumerate(zip(codes,calls)):
                    count=badcount if code==bad else 0;check=work/f'map_check_{i}'
                    assert read(check/'contract.json')==c and (check/'input.sv').read_text(encoding='utf-8')==code
                    assert (check/'inputs/ContractProbe/tb.sv').read_text(encoding='utf-8')==tb
                    assert sha(check/'inputs/probe_runner.py')==sha(agent/'probe_runner.py')
                    result=native(check/'probe',code,tb,c,count,runner,True);probe_count+=1
                    assert facts[i]['checks']==c['checks'] and facts[i]['mismatches']==count
                    assert facts[i]['prompt_sha256']==c['prompt_sha256'] and facts[i]['source_sha256']==hashlib.sha256(code.encode()).hexdigest()
                    user=text if i==0 else text+'\nPrevious candidate:\n'+codes[i-1]+'\nCandidate diagnostics:\n'+feedback
                    assert body==dict(model='fake-model',messages=[dict(role='system',content=generation+('\n'+repair if i else '')),dict(role='user',content=user)],temperature=0.0,top_p=1.0,max_tokens=8192)
                    if count:
                        point=parser.counterexample((check/'probe/xsim.log').read_text(encoding='utf-8'),c)
                        assert read(check/'counterexample.json')==point
                        assert (point['step'],point['phase'],int(point['observed_hex'],16))==first
                        feedback=formatter.render(c,result,point);assert read(check/'feedback.json')=={'text':feedback}
                requests+=calls;compile_count+=len(codes)
            checks.append(dict(width=width,checks_per_probe=c['checks'],bad_mismatches=badcount))
        assert read(root/'results/all_fake_requests.json')==requests
        assert probe_count==report['actual_native_probes']==report['completed_native_receipts_observed']==21
        assert compile_count==report['actual_compile_commands']==report['fake_model_requests']==report['fake_model_requests_observed']==15
        assert report['actual_synthesis_commands']==0 and len(report['rows'])==9
        return dict(native_probes=21,compile_commands_observed_in_original_trace=15,
                    independent_compile_argv_receipts_available=False,synthesis_commands=0,
                    fake_model_requests=15,controls=checks)
    finally:
        if old is None:sys.modules.pop('reserved_keywords',None)
        else:sys.modules['reserved_keywords']=old


def transport(root,report,driver):
    constants={}
    for node in ast.walk(ast.parse(driver.read_text(encoding='utf-8'))):
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['GOOD','PARTIAL']:
            constants[node.targets[0].id]=ast.literal_eval(node.value)
    assert set(constants)=={'GOOD','PARTIAL'}
    assert report['actual_eda_commands']==0 and report['fake_model_requests']==7 and len(report['rows'])==3
    generation=(OWNER/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
    repair=(OWNER/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
    prompt='Constructed interface-only transport control.'
    def bind_calls(calls):
        for i,body in enumerate(calls):
            user=prompt if i==0 else prompt+'\nPrevious candidate:\n'+constants['PARTIAL']+'\nCandidate diagnostics:\nReturn a complete TopModule ending in endmodule.'
            assert body==dict(model='fake-model',messages=[dict(role='system',content=generation+('\n'+repair if i else '')),dict(role='user',content=user)],temperature=0.0,top_p=1.0,max_tokens=8192)
    counts=0;rows=[]
    for case in ['first_headers','first_body','repair_headers']:
        folder=root/'results'/case;reply=read(folder/'reply.json');calls=read(folder/'requests.json');processes=read(folder/'processes.json');recovery=read(folder/'recovery.json')
        assert len(calls)==(2 if case=='repair_headers' else 1) and len(processes)==1
        bind_calls(calls);bind_calls(recovery['requests'])
        assert reply['task_id']==recovery['reply']['task_id']=='opaque_transport_control'
        assert 0<=reply['elapsed_s']<4 and 0<=recovery['reply']['elapsed_s']<3
        assert reply['solution']==(constants['PARTIAL'] if case=='repair_headers' else '')
        events=[json.loads(s) for s in reply['trace'].splitlines()]
        assert any(e.get('event')=='deadline' or e.get('tool')=='llm' and e.get('error') for e in events)
        assert not any(e.get('tool') in ['lint_start','xvlog','xelab','xsim'] for e in events)
        if case=='repair_headers':assert constants['PARTIAL'] in calls[1]['messages'][-1]['content']
        assert len(recovery['requests'])==1 and len(recovery['processes'])==1 and recovery['reply']['solution']==constants['GOOD']
        assert (folder/'worker/trace.jsonl').read_text(encoding='utf-8')==reply['trace']
        assert (folder/'worker/solution.v').read_text(encoding='utf-8')==reply['solution']
        row=next(r for r in report['rows'] if r['case']==case)
        assert row['passed'] and row['backend_peer_closed'] and row['owned_worker_gone'] and not row['implicit_retry']
        assert 0<=row['elapsed_s']<4 and 0<=row['recovery_s']<3
        # Recorded live-process/peer-closure observations bind to the pinned driver
        # and terminal guard; old /proc observations cannot be recreated locally.
        assert all(p['pid']>0 and p['starttime'].isdigit() for p in processes+recovery['processes'])
        counts+=len(calls)+len(recovery['requests']);rows.append(dict(case=case,elapsed_s=row['elapsed_s'],recovery_s=row['recovery_s']))
    assert counts==7
    return dict(fake_model_requests=7,native_probes=0,compile_commands=0,transport_controls=rows,
                observation_limit='Historical peer closure/owned-process absence binds to recorded driver observations and terminal guard, not re-execution.')


def main():
    result=dict(schema='team_bridge_readonly_review_v2',stages={},audit_model_calls=0,audit_eda_calls=0,
                actual_model_quality_measured=False,independent_natural_tasks=0,adoption=False)
    for label in ['T5','T6']:
        with tempfile.TemporaryDirectory(prefix='team-bridge-review-') as td:
            root=Path(td);report,driver,count=unpack(label,root)
            details=shift(root,report,driver) if label=='T5' else transport(root,report,driver)
            result['stages'][label]=dict(archive_sha256=ARCHIVES[label][0],files_verified=count,
                driver_sha256=ARCHIVES[label][2],owner_spec_sha256=sha(OWNER/'RUN_SPEC.json'),
                actual_model_requests=0,guard_protected_cleanup_verified=True,**details)
    result['reviewer_sha256']=sha(Path(__file__))
    output=ROOT/'RESULTS_V2.json';assert not output.exists();output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
