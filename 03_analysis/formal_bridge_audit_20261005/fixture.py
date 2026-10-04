"""Synthetic archive boundary fixtures only. Never model/AMD execution proof."""
import ast,hashlib,importlib.util,json,shutil,sys
from pathlib import Path
import collect
ROOT=Path(__file__).resolve().parent
def write(p,t):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(t,encoding='utf-8',newline='\n')
def save(p,d):write(p,json.dumps(d,indent=2,ensure_ascii=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(n,p):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def base(temp,version):
    source=ROOT.parent/('formal_bridge_20261005' if version==1 else 'formal_bridge_v2_20261005')
    run=temp/('v'+str(version));run.mkdir();spec=json.loads((source/'RUN_SPEC.json').read_text())
    for n in [*spec['source_hashes'],'RUN_SPEC.json','PREPARATION_RECEIPT.json']:
        p=run/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/n,p)
    inputs=json.loads((run/'INPUT_MANIFEST.json').read_text());model=spec['model']
    save(run/'guard/status.json',{'complete':True,'passed':True,'stage_rc':0,'model_unchanged':True,'protected_files_unchanged':True,'own_slot_released':True,'model_managed':False,'instance_managed':False,'owned_cleanup':{'verified':True,'remaining':[],'recorded':[]},'model_idle_after':{'processing_slots':0,'model_pid_owns_port':True}})
    save(run/'guard/resource_check.json',{'resource_idle':True,'model_pid':2013333,'model_starttime':'823869819','model_identity':{'pid':2013333,'starttime':'823869819'},'model_name':model,'protected':{'tasks':inputs['input_sha256'],'official':inputs['official_sha256']}})
    tests=14 if version==1 else 21;write(run/'results/linux_tests.log',f'SYNTHETIC_AUDIT_FIXTURE_NOT_EXECUTION\nRan {tests} tests\n\nOK\n')
    report={'run_spec_sha256':sha(run/'RUN_SPEC.json'),'complete':True,'passed':True,'actual_model_requests':0,'formal_deployment_changed':False,'quality_score_measured':False,'target_offline_single32gb_verified':False,'linux_tests':{'returncode':0,'log_sha256':sha(run/'results/linux_tests.log')},'linux_tests_passed':tests,'fake_protocol_consecutive_requests':200,'actual_native_probes':4 if version==1 else 0,'actual_compile_commands':2 if version==1 else 0,'actual_synthesis_commands':0}
    return run,spec,report

def v1(temp):
    run,spec,report=base(temp,1);out=run/'results/native_parity';agent=run/'package/agent'
    tree=ast.parse((run/'test_bridge.py').read_text(encoding='utf-8'));cst={}
    for n in tree.body:
        if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['BAD','GOOD']:cst[n.targets[0].id]=ast.literal_eval(n.value)
        if isinstance(n,ast.FunctionDef) and n.name=='prompt':cst['prompt']=ast.literal_eval(n.body[0].value)
    previous=sys.modules.get('reserved_keywords');sys.modules['reserved_keywords']=load('fixture_reserved',agent/'reserved_keywords.py')
    try:
        priority=load('fixture_priority',agent/'priority_contract.py');fmt=load('fixture_formatter',agent/'point_feedback.py')
        c=priority.parse(cst['prompt']);c['kind']='priority';tb=priority.render_tb(c,'ContractProbe');rows=[];events=[]
        for i,code in enumerate([cst['BAD'],cst['GOOD']]):
            mismatch=12 if i==0 else 0;folder=out/'http_worker'/f'map_check_{i}'
            write(folder/'input.sv',code);save(folder/'contract.json',c)
            write(folder/'inputs/ContractProbe/tb.sv',tb);write(out/f'legacy_inputs_{i}/ContractProbe/tb.sv',tb);write(out/f'legacy_inputs_{i}/source.sv',code)
            for helper in [folder/'inputs/probe_runner.py',out/f'legacy_inputs_{i}/probe_runner.py']:
                helper.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(agent/'probe_runner.py',helper)
            results=[]
            for prefix,bridge in [(folder/'probe',True),(out/f'legacy_probe_{i}',False)]:
                write(prefix/'dut.sv',code);write(prefix/'tb.sv',tb);stages=[]
                tails=[['-sv','--nolog','dut.sv','tb.sv'],['R2Probe','-s','r2_probe','--nolog','-timescale','1ns/1ps'],['r2_probe','-runall','-nolog']]
                for name,tail in zip(['xvlog','xelab','xsim'],tails):
                    text='SYNTHETIC_AUDIT_FIXTURE_NOT_EDA\n'
                    if name=='xsim':
                        if mismatch:text+='PRIORITY_FIRST value=0 expected=0 observed=1\n'
                        text+=f'R2_PROBE_RESULT task=ContractProbe checks=16 mismatches={mismatch}\n'
                    log=prefix/(name+'.log');write(log,text)
                    s={'name':name,'argv':[('/workspace/AMD/2026.1/Vivado/bin/'+name if bridge else name),*tail],'returncode':0,'timeout':False,'launch_error':None,'elapsed_s':1,'log':str(log),'log_sha256':sha(log),'log_bytes':log.stat().st_size}
                    if bridge:s['session_policy']='inherit_supervised_worker_group'
                    stages.append(s)
                result={'inputs_unchanged':True,'checks':16,'mismatches':mismatch,'task':'ContractProbe','status':'fail' if mismatch else 'pass','failure_kind':'semantic_mismatch' if mismatch else None,'runner_sha256':sha(agent/'probe_runner.py'),'solution_sha256':sha(prefix/'dut.sv'),'tb_sha256':sha(prefix/'tb.sv'),'stages':stages}
                save(prefix/'result.json',result);results.append(result)
            rows.append({'candidate':'wrong' if i==0 else 'correct','bridge':results[0],'legacy':results[1]})
            if i==0:
                point={'inputs':{'data':0},'output':'idx','expected':0,'observed':'1'};feedback=fmt.render(c,results[0],point);save(folder/'counterexample.json',point);save(folder/'feedback.json',{'text':feedback})
            events.extend([{'tool':'llm','round':i},{'tool':'lint','round':i,'rc':0},{'tool':'functional_probe','round':i,'checks':16,'mismatches':mismatch,'status':'fail' if mismatch else 'pass','prompt_sha256':c['prompt_sha256'],'source_sha256':hashlib.sha256(code.encode()).hexdigest()}])
        summary={'complete':True,'passed':True,'actual_model_requests':0,'fake_model_requests':2,'actual_native_probes':4,'actual_compile_commands':2,'actual_synthesis_commands':0,'completed_native_receipts_observed':4,'rows':rows};save(out/'summary.json',summary)
        trace=''.join(json.dumps(e)+'\n' for e in events);write(out/'http_worker/trace.jsonl',trace);write(out/'http_worker/solution.v',cst['GOOD']);save(out/'http_reply.json',{'task_id':'opaque/../构造契约','solution':cst['GOOD'],'trace':trace,'elapsed_s':8})
        gen=(run/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8');rep=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8');calls=[]
        for i in [0,1]:
            user=cst['prompt'] if i==0 else cst['prompt']+'\nPrevious candidate:\n'+cst['BAD']+'\nCandidate diagnostics:\n'+feedback
            calls.append({'model':'fake-model','temperature':0,'top_p':1.0,'max_tokens':8192,'messages':[{'role':'system','content':gen+('\n'+rep if i else '')},{'role':'user','content':user}]})
        save(out/'fake_model_requests.json',calls);write(run/'results/native_parity.log','SYNTHETIC_AUDIT_FIXTURE_NOT_EXECUTION\n')
        report.update(native_receipt_sha256=sha(out/'summary.json'),native_parity={'returncode':0,'log_sha256':sha(run/'results/native_parity.log')});save(run/'results/summary.json',report)
        return run
    finally:
        if previous is None:sys.modules.pop('reserved_keywords',None)
        else:sys.modules['reserved_keywords']=previous

def v2(temp):
    run,spec,report=base(temp,2);out=run/'results/live_health';reply={'ready':True,'track':'rtl','model':spec['model'],'vram_gb':19}
    live={'complete':True,'passed':True,'actual_model_requests':0,'formal_deployment_changed':False,'target_offline_single32gb_verified':False,'actual_vivado_version_commands':1,'actual_version':'2026.1','version_calls':[{'argv':['/workspace/AMD/2026.1/Vivado/bin/vivado','-version'],'pid':999999,'owned_version_command':True}],'http_reply':reply,'second_http_reply':dict(reply),'observation':{'model_pid':2013333,'model_starttime':'823869819','render_node':'renderD133','card_vram_used_bytes':19*1024**3,'card_vram_total_bytes':48*1024**3,'vram_gb':19}}
    save(out/'summary.json',live);write(run/'results/live_health.log','SYNTHETIC_AUDIT_FIXTURE_NOT_EXECUTION\n')
    report.update(actual_vivado_version_commands=1,prerequisite_v1_native_stage_passed=True,live_health_receipt_sha256=sha(out/'summary.json'),live_health={'returncode':0,'log_sha256':sha(run/'results/live_health.log')});save(run/'results/summary.json',report)
    return run

def archive(run,path,prior=None,failure=False):return collect.collect(run,path,prior,failure,fixture=True)
