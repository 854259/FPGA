"""New complete-worker boundary checks; AMD only, HTTP/compiler explicitly simulated."""
import copy,hashlib,io,json,os,subprocess,sys,types,urllib.request
from pathlib import Path
import worker,baseline_worker
import galois_first_request as boundary

ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
save=lambda p,j:Path(p).write_bytes((json.dumps(j,indent=2)+'\n').encode())
PROMPT='''I would like you to implement a module named TopModule with the following interface.
 - input clk
 - input reset
 - output state (6 bits)
A Galois LFSR is one particular arrangement that shifts right, where a bit position with a "tap" is XORed with the LSB output bit (state[0]) to produce its next value, while bit positions without a tap shift right unchanged.
The module should implement a 6-bit Galois LFSR with taps at bit positions 6 and 4.
Reset should be active high synchronous, and should reset the output state to 6'h9.
Assume all sequential logic is triggered on the positive edge of the clock.
'''
INTERFACE='module TopModule(input clk, input reset, output [5:0] state); endmodule'
EXPECTED=('Prompt-derived transition clarification (no extra behavior): '
    'Use the old 6-bit state state for every next-state bit. Right shift means old bit i+1 moves to destination bit i, with zero entering the MSB. '
    'The stated one-based tap positions are 6, 4; XOR the old LSB into each tapped destination after this right shift. '
    'Equivalently next_state = (old_state >> 1) XOR (old_LSB ? tap_mask : 0), where tap_mask sets bit p-1 for each listed position p. '
    'On the positive clock edge, active-high synchronous reset has priority and loads 9; otherwise use that next_state. '
    'This is Galois feedback, not an XOR reduction of the tapped source bits.')

def rejected(fn):
    try:fn()
    except (AssertionError,KeyError,ValueError):return True
    raise AssertionError('Invalid boundary evidence accepted')

def main():
    assert sys.platform=='linux' and sys.dont_write_bytecode
    manifest=read(ROOT/'SOURCE_MANIFEST.json')
    assert all(sha(ROOT/n)==h for n,h in manifest.items())
    original=read(ROOT/'COMMON_PHASE_SOURCE_PROOF.json')
    assert all(sha(ROOT/n)==h for n,h in original['common_phase_sources'].items())
    assert b'internal_wire_hook' not in (ROOT/'baseline_worker.py').read_bytes()
    assert b'internal_wire' not in (ROOT/'package/agent/map_runtime.py').read_bytes()
    assert boundary.clarification(PROMPT,INTERFACE)[0]==EXPECTED
    invalid_interfaces=[INTERFACE.replace('[5:0]','[6:0]'),INTERFACE.replace('input reset','input enable'),INTERFACE.replace('TopModule','Other'),INTERFACE.replace('endmodule','assign state=0; endmodule'),INTERFACE.replace('input reset','input reset, input enable'),INTERFACE.replace('output [5:0]','input [5:0]')]
    for interface in invalid_interfaces:assert boundary.clarification(PROMPT,interface)[0]==''
    assert boundary.clarification(PROMPT,'')[0]==EXPECTED
    os.environ.update(MODEL_NAME='simulated-galois-boundary',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
    save(ROOT/'RUN_SPEC.json',dict(dependencies_cloud=str(ROOT),model='simulated-galois-boundary',identity='galois-new-boundary-controls'))
    sys.path.insert(0,str(ROOT/'package'));import baseline
    first=baseline.extract('module TopModule(input clk,input reset,output [5:0] state); wire bucket; always @(posedge clk) bucket<=reset; assign state=0; endmodule','rtl')
    fixed=first.replace('wire bucket','reg bucket')
    error='ERROR: simulated compiler rejected first fixture'
    activity=[];old_activity=sys.modules.get('activity');sys.modules['activity']=types.SimpleNamespace(append=lambda *a:activity.append(dict(simulated=True,event=str(a[2]))))
    old_open,old_load=urllib.request.urlopen,baseline_worker.load
    old_request,old_run,cwd=urllib.request.Request,subprocess.run,Path.cwd()
    runtimes=[];rows=[];mutation_count=0
    def load(name,path):
        m=old_load(name,path)
        if str(path).endswith('/agent/map_runtime.py'):m.vivado_tool=lambda n:'/simulated-boundary/'+n;runtimes.append(m)
        return m
    baseline_worker.load=load
    try:
        for case in ('supported','interface_abstention'):
            interface=INTERFACE if case=='supported' else invalid_interfaces[0]
            source=ROOT/'FIXTURE_KIT'/case/'bench/tasks_veval'/'generic_input';source.mkdir(parents=True)
            (source/'prompt.txt').write_bytes(PROMPT.encode());(source/'interface.txt').write_bytes(interface.encode())
            pair={}
            for arm in ('C','P'):
                folder=ROOT/'PIPELINE_RESULTS'/case/arm;wires=[];compiles=[]
                def transport(request,**kwargs):
                    index=len(wires);assert index<2 and kwargs==dict(timeout=300)
                    assert request.full_url==boundary.ENDPOINT;body=json.loads(request.data)
                    expected=boundary.combined(PROMPT,interface)
                    if index==0 and arm=='P' and case=='supported':expected+='\n\n'+EXPECTED
                    if index:expected+='\nPrevious candidate:\n'+first+'\nCandidate diagnostics:\n'+error
                    assert body['messages'][1]['content']==expected
                    wires.append(request.data)
                    return io.BytesIO(json.dumps(dict(id='simulated-'+str(index),choices=[dict(message=dict(content=first if index==0 else fixed),finish_reason='stop')],usage=dict(prompt_tokens=0,completion_tokens=0))).encode())
                class Paired:
                    REPO=ROOT
                    def check_resource(self,*args):return True
                    def model_idle(self,*args):return True
                    def owned_command(self,argv,wd,log,cap):
                        assert cap==60 and argv[:2]==['/simulated-boundary/xvlog','--sv']
                        index=len(compiles);assert index<2;compiles.append(Path(argv[-1]).read_text());log.write_text(error if index==0 else '')
                        return dict(returncode=1 if index==0 else 0,timeout=False,launch_error=None,remaining_live_group=[],log_sha256=sha(log),log_bytes=log.stat().st_size,elapsed_s=0,simulated=True)
                urllib.request.urlopen=transport
                args=types.SimpleNamespace(kit=source.parents[2],task='generic_input',arm=arm,out=folder,resource_check=ROOT/'SIMULATED_RESOURCE.json')
                worker.run_worker(args,Paired())
                assert urllib.request.Request is old_request and subprocess.run is old_run
                assert len(wires)==len(compiles)==2 and compiles==[first,fixed] and (folder/'solution.v').read_text()==fixed
                assert not (folder/'internal_declaration_journal.json').exists()
                generation,repair=runtimes[-1].skill_texts()
                for index in range(2):
                    evidence=folder/'first_request_receipts'/str(index)
                    before=(evidence/'original.bin').read_bytes();after=(evidence/'forwarded.bin').read_bytes();receipt=read(evidence/'receipt.json')
                    original_body=json.loads(before);assert original_body['messages'][0]==dict(role='system',content=generation+('\n'+repair if index else ''))
                    assert after==wires[index]
                    proof=boundary.verify(before,after,PROMPT,interface,arm,index,receipt)
                    assert proof['changed']==(case=='supported' and arm=='P' and index==0)
                    for key,value in [('system','changed'),('max_tokens',4096),('top_p',.5),('user','changed')]:
                        altered=json.loads(after)
                        if key=='system':altered['messages'][0]['content']+=value
                        elif key=='user':altered['messages'][1]['content']+=value
                        else:altered[key]=value
                        assert rejected(lambda:boundary.verify(before,json.dumps(altered).encode(),PROMPT,interface,arm,index,receipt));mutation_count+=1
                    changed=copy.deepcopy(receipt);changed['changed']=not changed['changed']
                    assert rejected(lambda:boundary.verify(before,after,PROMPT,interface,arm,index,changed));mutation_count+=1
                pair[arm]=dict(first=digest(wires[0]),repair=digest(wires[1]),requests=2)
            assert pair['C']['repair']==pair['P']['repair']
            assert (pair['C']['first']!=pair['P']['first'])==(case=='supported')
            rows.append(dict(case=case,pair=pair))
        raw=(ROOT/'PIPELINE_RESULTS/supported/C/first_request_receipts/0/original.bin').read_bytes()
        assert rejected(lambda:boundary.transform(raw,PROMPT,INTERFACE,'P',2));mutation_count+=1
        assert rejected(lambda:boundary.transform(raw,PROMPT,INTERFACE,'A',0));mutation_count+=1
        bad=raw[:-1]+b',"max_tokens":8192}'
        assert rejected(lambda:boundary.transform(bad,PROMPT,INTERFACE,'P',0));mutation_count+=1
        # Failure restores the Request constructor and retains the attempted wire.
        source=ROOT/'FIXTURE_KIT/supported/bench/tasks_veval/generic_input';failed=ROOT/'SIMULATED_TRANSPORT_FAILURE'
        def failure(*args,**kwargs):raise OSError('explicit simulated HTTP failure')
        urllib.request.urlopen=failure
        args=types.SimpleNamespace(kit=source.parents[2],task='generic_input',arm='P',out=failed,resource_check=ROOT/'SIMULATED_RESOURCE.json')
        try:worker.run_worker(args,Paired())
        except RuntimeError:pass
        else:raise AssertionError('Simulated transport failure lost')
        assert urllib.request.Request is old_request and subprocess.run is old_run
        assert len(read(failed/'requests.json'))==1 and not read(failed/'requests.json')[0]['response_received']
        assert (failed/'first_request_receipts/0/original.bin').exists() and (failed/'first_request_receipts/0/forwarded.bin').exists()
    finally:
        urllib.request.urlopen=old_open;baseline_worker.load=old_load;os.chdir(cwd)
        assert urllib.request.Request is old_request and subprocess.run is old_run
        if old_activity is None:sys.modules.pop('activity',None)
        else:sys.modules['activity']=old_activity
    save(ROOT/'SIMULATED_ACTIVITY.json',activity)
    result=dict(schema='galois_first_user_full_worker_controls_v1',passed=True,complete_worker_contexts=4,transport_failure_contexts=1,interface_abstentions=6,empty_interface_pass=True,request_and_receipt_rejections=mutation_count,rows=rows,original_common_phase_worker_and_runtime_held=True,declaration_callback_absent=True,production_wrapper_executed=True,HTTP_compiler_activity_simulated=True,original_parser_controls_not_rerun=True,real_model_calls=0,real_EDA_calls=0,FIFO_calls=0,score_measured=False,qualified_for_full156=False,adoption=False)
    save(ROOT/'ACTUAL_RESULT.json',result);print(json.dumps({k:v for k,v in result.items() if k!='rows'}))

digest=lambda b:hashlib.sha256(b).hexdigest()
if __name__=='__main__':main()
