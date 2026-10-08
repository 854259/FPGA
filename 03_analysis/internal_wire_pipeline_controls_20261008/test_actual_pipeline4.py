"""Full production wrapper+worker evidence; simulated HTTP/compiler, AMD execution only."""
import copy,hashlib,importlib.util,io,json,os,subprocess,sys,types,urllib.request
from pathlib import Path
import worker,baseline_worker,request_proof,declaration_replay,core_source_proof,edge_dispatch,phase_feedback
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,v):Path(p).write_text(json.dumps(v,indent=2)+'\n')
def expect_failure(name,fn):
 try:fn()
 except (AssertionError,KeyError,ValueError):return dict(name=name,rejected=True)
 raise AssertionError('Mutation was accepted: '+name)
def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode
 source_proof=core_source_proof.verify(ROOT)
 os.environ.update(MODEL_NAME='pipeline-fixture-only',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
 kit=ROOT/'FIXTURE_KIT';task='engineering_fixture';source=kit/'bench/tasks_veval'/task;source.mkdir(parents=True)
 prompt='Engineering fixture without a recognized functional contract.'
 (source/'prompt.txt').write_text(prompt)
 assert edge_dispatch.parse(prompt)['status']!='supported'
 save(ROOT/'RUN_SPEC.json',dict(dependencies_cloud=str(ROOT),model='pipeline-fixture-only',identity='explicitly-simulated-pipeline-controls'))
 sys.path.insert(0,str(ROOT/'package'));import baseline
 first=baseline.extract('module TopModule(input clk,input a,output out); wire bucket; wire side; always @(posedge clk) begin bucket<=a; end always @(negedge clk) begin side<=a; end assign out=clk?bucket:side; endmodule','rtl')
 fixed=first.replace('wire bucket','reg bucket').replace('wire side','reg side')
 error='ERROR: [VRFC 10-1280] procedural assignment to a non-register bucket is not permitted, left-hand side should be reg/integer/time/genvar'
 second_error='ERROR: simulated recompile rejected the modified source'
 simulated_activity=[];old_activity=sys.modules.get('activity');sys.modules['activity']=types.SimpleNamespace(append=lambda *a:simulated_activity.append(dict(simulated=True,args=[str(x) for x in a[:4]],payload=a[4])))
 old_open,old_load=urllib.request.urlopen,baseline_worker.load
 old_request=urllib.request.Request;old_run=subprocess.run;cwd=Path.cwd();rows=[];mutations=[];runtime_holder=[]
 def load(n,p):
  m=old_load(n,p)
  if str(p).endswith('/agent/map_runtime.py'):
   m.vivado_tool=lambda n:'/simulated-pipeline-tools/'+n;runtime_holder.append(m)
  return m
 baseline_worker.load=load
 try:
  for case in ('mechanical_success','mechanical_failure_original_repair'):
   pair={}
   for arm in ('C','P'):
    folder=ROOT/'PIPELINE_RESULTS'/case/arm;wire_requests=[];compiler_sources=[]
    expected_requests=1 if case=='mechanical_success' and arm=='P' else 2
    compiler_rc=[1,1,0] if case=='mechanical_failure_original_repair' and arm=='P' else [1,0]
    def transport(request,**kwargs):
     i=len(wire_requests);assert kwargs==dict(timeout=300) and i<expected_requests
     assert request.full_url=='http://127.0.0.1:8000/v1/chat/completions'
     body=json.loads(request.data);wire_requests.append(request.data)
     if i:assert body['messages'][1]['content']==prompt+'\nPrevious candidate:\n'+first+'\nCandidate diagnostics:\n'+error
     raw=json.dumps(dict(id='simulated-'+str(i),choices=[dict(message=dict(content=first if not i else fixed),finish_reason='stop')],usage=dict(prompt_tokens=0,completion_tokens=0))).encode()
     return io.BytesIO(raw)
    class Paired:
     REPO=ROOT
     def check_resource(self,*args):return True
     def model_idle(self,*args):return True
     def owned_command(self,argv,wd,log,cap):
      assert cap==60 and argv[:2]==['/simulated-pipeline-tools/xvlog','--sv']
      index=len(compiler_sources);assert index<len(compiler_rc)
      code=Path(argv[-1]).read_text();compiler_sources.append(code);rc=compiler_rc[index]
      log.write_text(error if index==0 else (second_error if rc else ''))
      return dict(returncode=rc,timeout=False,launch_error=None,remaining_live_group=[],log_sha256=sha(log),log_bytes=log.stat().st_size,elapsed_s=0,simulated=True)
    urllib.request.urlopen=transport
    args=types.SimpleNamespace(kit=kit,task=task,arm=arm,out=folder,resource_check=ROOT/'SIMULATED_RESOURCE_ONLY.json')
    worker.run_worker(args,Paired())
    assert urllib.request.Request is old_request and subprocess.run is old_run
    assert len(wire_requests)==expected_requests and len(compiler_sources)==len(compiler_rc)
    assert compiler_sources[0]==first and compiler_sources[-1]==fixed
    assert (folder/'solution.v').read_text()==fixed
    runtime=runtime_holder[-1];import baseline
    generation,repair=runtime.skill_texts()
    def verify():
     p=request_proof.verify(folder,prompt,'',arm,'pipeline-fixture-only',generation,repair)
     r=declaration_replay.replay(folder,prompt,arm,edge_dispatch.parse(prompt),baseline,runtime,edge_dispatch,phase_feedback,lambda *a:(_ for _ in ()).throw(AssertionError('Unexpected functional probe')),sha,read,False)
     assert p['first_system_changed'] is False and r['declaration_factor_bound'] is True
     return p,r
    p,r=verify()
    if arm=='P':
     receipt_file=folder/'internal_declaration_journal.json';original=receipt_file.read_bytes();j=read(receipt_file)
     assert len(j)==1 and j[0]['compiler_reported_targets']==['bucket'] and j[0]['inferred_unreported_targets']==['side']
     for key,value in [('compile_index',99),('response_json_sha256','0'*64),('compiler_reported_targets',['side']),('inferred_unreported_targets',[]),('feedback_sha256','0'*64)]:
      changed=copy.deepcopy(j);changed[0][key]=value;save(receipt_file,changed)
      mutations.append(expect_failure(case+':'+key,verify));receipt_file.write_bytes(original)
     save(receipt_file,[]);mutations.append(expect_failure(case+':missing_callback',verify));receipt_file.write_bytes(original)
     altered=folder/'compile_receipts/1/source_before.sv';original_source=altered.read_bytes();altered.write_bytes(original_source+b'\n// changed')
     mutations.append(expect_failure(case+':modified_second_compile',verify));altered.write_bytes(original_source)
    else:assert not (folder/'internal_declaration_journal.json').exists()
    wire=folder/'identity_request_receipts/0/wire.bin';original_wire=wire.read_bytes();body=json.loads(original_wire);body['messages'][0]['content']+=' changed';wire.write_bytes(json.dumps(body).encode())
    mutations.append(expect_failure(case+':'+arm+':changed_system',verify));wire.write_bytes(original_wire)
    verify()
    pair[arm]=dict(requests=len(wire_requests),compiles=len(compiler_sources),first_wire_sha256=hashlib.sha256(wire_requests[0]).hexdigest(),repair_wire_sha256=hashlib.sha256(wire_requests[1]).hexdigest() if len(wire_requests)>1 else None,request_proof_sha256=p['request_proof_sha256'],replay=r)
   assert pair['C']['first_wire_sha256']==pair['P']['first_wire_sha256']
   if case=='mechanical_failure_original_repair':assert pair['C']['repair_wire_sha256']==pair['P']['repair_wire_sha256']
   rows.append(dict(case=case,pair=pair))
 finally:
  urllib.request.urlopen=old_open;baseline_worker.load=old_load;os.chdir(cwd)
  assert urllib.request.Request is old_request and subprocess.run is old_run
  if old_activity is None:sys.modules.pop('activity',None)
  else:sys.modules['activity']=old_activity
 assert len(simulated_activity)==14 and all(e['simulated'] for e in simulated_activity)
 save(ROOT/'SIMULATED_ACTIVITY.json',simulated_activity)
 result=dict(schema='internal_declaration_full_worker_identity_replay_controls_v1',passed=True,contexts=4,mutation_checks=len(mutations),source_proof=source_proof,rows=rows,mutations=mutations,
  production_wrapper_and_baseline_worker_executed=True,HTTP_and_compiler_simulated=True,activity_intercepted=True,real_model_calls=0,real_EDA_calls=0,FIFO=False,score_measured=False,native_qualified=False,goal_achieved=False)
 save(ROOT/'ACTUAL_PIPELINE_RESULT.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('rows','mutations','source_proof')}))
if __name__=='__main__':main()
