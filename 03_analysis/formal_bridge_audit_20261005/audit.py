"""Read-only shipping evidence audit; fake inference never becomes a score."""
import argparse,ast,hashlib,importlib.util,json,math
from pathlib import Path,PurePosixPath
import re,sys,tempfile

SPECS={'formal_bridge_20261005_v1':'a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','formal_bridge_v2_20261005_v1':'b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'}
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def shared_helper():
    p=ROOT.parent/'full156_postflight_20261004/audit.py'
    assert sha(p)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    return load('bridge_trusted_archive_reader',p)

def common(root,manifest,fixture):
    run=root/'run';spec=read(run/'RUN_SPEC.json');report=read(run/'results/summary.json')
    assert manifest['schema']=='formal_bridge_terminal_archive_v1' and manifest['mode']=='passed'
    assert manifest['synthetic_fixture'] is fixture
    assert sha(run/'RUN_SPEC.json')==SPECS[spec['identity']]==manifest['run_spec_sha256']
    assert report['run_spec_sha256']==manifest['run_spec_sha256'] and report['complete'] and report['passed']
    for n,h in spec['source_hashes'].items():assert sha(run/n)==h,n
    package=run/'package';integrity=read(package/'INTEGRITY.json')
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    assert actual==set(integrity['files'])|{'INTEGRITY.json'},'Unexpected/missing production file'
    for n,h in integrity['files'].items():assert sha(package/n)==h,n
    assert sha(package/'agent/core.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    baseline={'baseline.py':'537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51','run_baseline.sh':'5c46c40d32c0cf4c4e1dc52ae12e60f8396a0deccafaa4e6f69d7316a3482e75'}
    assert read(package/'upstream.json')['files']==baseline
    for n,h in baseline.items():assert sha(package/n)==h
    guard=read(root/'guard/status.json');resource=read(root/'guard/resource_check.json');inputs=read(run/'INPUT_MANIFEST.json')
    assert all(guard[k] is True for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
    assert guard['stage_rc']==0 and not guard['model_managed'] and not guard['instance_managed']
    assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    assert resource['resource_idle'] and resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
    assert resource['model_identity']['pid']==2013333 and resource['model_identity']['starttime']=='823869819'
    assert resource['model_name']==spec['model'] and guard['model_idle_after']['processing_slots']==0 and guard['model_idle_after']['model_pid_owns_port']
    assert resource['protected']['tasks']==inputs['input_sha256'] and len(inputs['input_sha256'])==936
    assert resource['protected']['official']==inputs['official_sha256'] and len(inputs['official_sha256'])==35
    assert report['actual_model_requests']==0 and not report['formal_deployment_changed'] and not report['quality_score_measured'] and not report['target_offline_single32gb_verified']
    tests=14 if spec['identity']=='formal_bridge_20261005_v1' else 21
    log=run/'results/linux_tests.log';text=log.read_text(encoding='utf-8')
    assert f'Ran {tests} tests' in text and '\nOK\n' in text and 'skipped' not in text and '... FAIL' not in text and '... ERROR' not in text
    assert report['linux_tests']['returncode']==0 and sha(log)==report['linux_tests']['log_sha256']
    assert report['linux_tests_passed']==tests and report['fake_protocol_consecutive_requests']==200
    return run,spec,report

def native_v1(run,report):
    out=run/'results/native_parity';summary=read(out/'summary.json')
    assert summary['complete'] and summary['passed'] and summary['actual_model_requests']==0 and summary['fake_model_requests']==2
    assert summary['actual_native_probes']==report['actual_native_probes']==4 and summary['actual_compile_commands']==report['actual_compile_commands']==2
    assert summary['actual_synthesis_commands']==report['actual_synthesis_commands']==0 and summary['completed_native_receipts_observed']==4
    assert sha(out/'summary.json')==report['native_receipt_sha256']
    assert report['native_parity']['returncode']==0 and sha(run/'results/native_parity.log')==report['native_parity']['log_sha256']
    tree=ast.parse((run/'test_bridge.py').read_text(encoding='utf-8'));constants={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['BAD','GOOD']:constants[node.targets[0].id]=ast.literal_eval(node.value)
        if isinstance(node,ast.FunctionDef) and node.name=='prompt':constants['prompt']=ast.literal_eval(node.body[0].value)
    pkg=run/'package';agent=pkg/'agent'
    modules=['reserved_keywords'];before={n:sys.modules.get(n) for n in modules}
    try:
        sys.modules['reserved_keywords']=load('bridge_reserved',agent/'reserved_keywords.py')
        priority=load('bridge_priority',agent/'priority_contract.py');formatter=load('bridge_formatter',agent/'point_feedback.py')
        c=priority.parse(constants['prompt']);c['kind']='priority';assert c['checks']==16
        assert c['cases']==[{'inputs':{'data':v},'expected':(v&-v).bit_length()-1 if v else 0} for v in range(16)]
        runner=load('bridge_native_reader',agent/'probe_runner.py');runner.TASK_CHECKS={'ContractProbe':16}
        expected_bad=sum(1!=((v&-v).bit_length()-1 if v else 0) for v in range(16));assert expected_bad==12
        expected_tb=priority.render_tb(c,'ContractProbe');rows=[]
        for i,code,count in [(0,constants['BAD'],expected_bad),(1,constants['GOOD'],0)]:
            folder=out/'http_worker'/f'map_check_{i}';raw=read(folder/'probe/result.json');legacy=read(out/f'legacy_probe_{i}/result.json')
            assert sha(folder/'inputs/probe_runner.py')==sha(out/f'legacy_inputs_{i}/probe_runner.py')==sha(agent/'probe_runner.py')
            assert (out/f'legacy_inputs_{i}/source.sv').read_text()==code
            assert (out/f'legacy_inputs_{i}/ContractProbe/tb.sv').read_text()==expected_tb
            assert (folder/'input.sv').read_text()==(folder/'probe/dut.sv').read_text()==code
            assert read(folder/'contract.json')==c
            assert (folder/'inputs/ContractProbe/tb.sv').read_text()==(folder/'probe/tb.sv').read_text()==expected_tb
            for result,prefix,bridge in [(raw,folder/'probe',True),(legacy,out/f'legacy_probe_{i}',False)]:
                assert result['inputs_unchanged'] and result['checks']==16 and result['mismatches']==count
                assert result['task']=='ContractProbe' and result['status']==('fail' if count else 'pass') and result['failure_kind']==('semantic_mismatch' if count else None)
                assert result['runner_sha256']==sha(agent/'probe_runner.py')
                assert result['solution_sha256']==sha(prefix/'dut.sv')==hashlib.sha256(code.encode()).hexdigest()
                assert result['tb_sha256']==sha(prefix/'tb.sv')==hashlib.sha256(expected_tb.encode()).hexdigest()
                assert (prefix/'tb.sv').read_text()==expected_tb
                assert len(result['stages'])==3
                tails=[['-sv','--nolog','dut.sv','tb.sv'],['R2Probe','-s','r2_probe','--nolog','-timescale','1ns/1ps'],['r2_probe','-runall','-nolog']]
                for stage,name,tail in zip(result['stages'],['xvlog','xelab','xsim'],tails):
                    assert stage['name']==name and stage['argv'][1:]==tail
                    assert stage['argv'][0]==('/workspace/AMD/2026.1/Vivado/bin/'+name if bridge else name)
                    assert stage['returncode']==0 and not stage['timeout'] and not stage['launch_error']
                    assert math.isfinite(stage['elapsed_s']) and stage['elapsed_s']>=0
                    logfile=prefix/(name+'.log');assert sha(logfile)==stage['log_sha256'] and logfile.stat().st_size==stage['log_bytes']
                    logtext=logfile.read_text(encoding='utf-8');assert not runner.ENVIRONMENT_ERROR.search(logtext) and 'FAKE_TOOL_NO_AMD_EXECUTION' not in logtext
                    if bridge:assert stage['session_policy']=='inherit_supervised_worker_group'
                assert runner._parse_summary((prefix/'xsim.log').read_text(),'ContractProbe')==(16,count)
            if i==0:
                point=priority.counterexample((folder/'probe/xsim.log').read_text(),c)
                assert point=={'inputs':{'data':0},'output':'idx','expected':0,'observed':'1'}
                assert read(folder/'counterexample.json')==point
                text=formatter.render(c,raw,point);assert read(folder/'feedback.json')=={'text':text}
            rows.append({'candidate':'wrong' if i==0 else 'correct','bridge':raw,'legacy':legacy})
        assert summary['rows']==rows
        reply=read(out/'http_reply.json');assert reply['task_id']=='opaque/../构造契约' and reply['solution']==constants['GOOD'] and 0<=reply['elapsed_s']<=120
        assert (out/'http_worker/solution.v').read_text()==constants['GOOD']
        assert (out/'http_worker/trace.jsonl').read_text()==reply['trace']
        events=[json.loads(line) for line in reply['trace'].splitlines()]
        assert [e['round'] for e in events if e['tool']=='llm']==[0,1] and sum(e['tool']=='lint' and e['rc']==0 for e in events)==2
        checks=[e for e in events if e['tool']=='functional_probe'];assert [(e['round'],e['checks'],e['mismatches'],e['status']) for e in checks]==[(0,16,12,'fail'),(1,16,0,'pass')]
        for e,code in zip(checks,[constants['BAD'],constants['GOOD']]):assert e['prompt_sha256']==c['prompt_sha256'] and e['source_sha256']==hashlib.sha256(code.encode()).hexdigest()
        calls=read(out/'fake_model_requests.json');assert len(calls)==2
        generation=(pkg/'skill/rtl-generation/SKILL.md').read_text(encoding='utf-8');repair=(pkg/'skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
        for i,body in enumerate(calls):
            assert body['model']=='fake-model' and body['temperature']==0 and body['top_p']==1.0 and body['max_tokens']==8192
            user=constants['prompt'] if i==0 else constants['prompt']+'\nPrevious candidate:\n'+constants['BAD']+'\nCandidate diagnostics:\n'+text
            assert body['messages']==[{'role':'system','content':generation+('\n'+repair if i else '')},{'role':'user','content':user}]
        return {'native_probes':4,'compile_commands':2,'model_requests':0,'fake_model_requests':2,'native_scope':'one constructed renamed 4-bit priority contract; shift and natural-task parity not measured'}
    finally:
        for n in modules:
            if before[n] is None:sys.modules.pop(n,None)
            else:sys.modules[n]=before[n]

def v2(run,spec,report,prior):
    delta=read(run/'SOURCE_DELTA.json');pkg=run/'package';old=prior/'run/package'
    for field,base in [('original_package_sha256',old),('new_package_sha256',pkg)]:
        values={p.relative_to(base).as_posix():sha(p) for p in base.rglob('*') if p.is_file()};assert values==delta[field]
    assert sorted(delta['changed'])==['INTEGRITY.json','agent/runtime.py'] and delta['added']==['agent/health_probe.py']
    assert not delta['solver_core_changed'] and not delta['native_adapter_changed'] and not delta['parser_skills_baseline_changed'] and not delta['quality_score_transferred']
    for n,h in delta['original_package_sha256'].items():
        if n not in delta['changed']:assert sha(pkg/n)==h
    assert report['prerequisite_v1_native_stage_passed'] and spec['prerequisite_spec_sha256']==SPECS['formal_bridge_20261005_v1']
    assert report['actual_native_probes']==report['actual_compile_commands']==report['actual_synthesis_commands']==0
    live=run/'results/live_health/summary.json';d=read(live)
    assert d['complete'] and d['passed'] and d['actual_model_requests']==0 and not d['formal_deployment_changed'] and not d['target_offline_single32gb_verified']
    assert sha(live)==report['live_health_receipt_sha256'] and report['live_health']['returncode']==0 and sha(run/'results/live_health.log')==report['live_health']['log_sha256']
    assert d['actual_vivado_version_commands']==report['actual_vivado_version_commands']==1 and d['actual_version']=='2026.1'
    assert len(d['version_calls'])==1 and d['version_calls'][0]['argv']==['/workspace/AMD/2026.1/Vivado/bin/vivado','-version'] and d['version_calls'][0]['owned_version_command']
    for response in [d['http_reply'],d['second_http_reply']]:
        assert set(response)=={'ready','track','model','vram_gb'} and response['ready'] is True and response['track']=='rtl' and response['model']==spec['model']
        assert isinstance(response['vram_gb'],(int,float)) and math.isfinite(response['vram_gb']) and 0<=response['vram_gb']<=32
    observed=d['observation'];assert observed['model_pid']==2013333 and observed['model_starttime']=='823869819' and re.fullmatch(r'renderD\d+',observed['render_node'])
    assert 0<=observed['card_vram_used_bytes']<=observed['card_vram_total_bytes'] and observed['vram_gb']==observed['card_vram_used_bytes']/1024**3 and observed['vram_gb']<=32
    return {'live_health_requests':2,'version_commands':1,'model_requests':0,'scope':'current development card instantaneous measurement; not peak, process-exclusive memory, R9700 or 32GB physical capacity certification'}

def audit(archive,fixture=False):
    reader=shared_helper()
    with tempfile.TemporaryDirectory(prefix='bridge-readonly-audit-') as td:
        root=Path(td);manifest=reader.unpack(archive,root);run,spec,report=common(root,manifest,fixture)
        if spec['identity']=='formal_bridge_20261005_v1':details=native_v1(run,report)
        else:
            prior=root/'prior';prior.mkdir();pm=reader.unpack(root/'dependencies/v1.zip',prior);prun,pspec,preport=common(prior,pm,fixture)
            assert pspec['identity']=='formal_bridge_20261005_v1';native_v1(prun,preport);details=v2(run,spec,report,prior)
    return {'schema':'formal_bridge_shipping_evidence_audit_v1','passed':True,'evidence_kind':'synthetic_checker_fixture' if fixture else 'completed_cloud_stage','actual_execution_verified':not fixture,'run_spec_sha256':SPECS[spec['identity']],'archive_sha256':sha(Path(archive)),'source_assets':len(spec['source_hashes']),'details':details,'audit_model_calls':0,'audit_eda_calls':0,'quality_score_measured':False,'independent_natural_tasks':0,'target_offline_single32gb_verified':False,'adoption':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();result=audit(a.archive);a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
