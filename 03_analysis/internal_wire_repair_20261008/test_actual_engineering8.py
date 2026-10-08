
"""Actual AMD runtime workflow; transport/compiler are explicitly simulated."""
import hashlib,importlib.util,io,json,os,subprocess,sys,urllib.request
from pathlib import Path
import internal_wire_hook
ROOT=Path(__file__).parent
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode
 os.environ.update(MODEL_NAME='engineering-fixture-only',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
 runtime=load('internal_wire_actual_runtime',ROOT/'package/agent/map_runtime.py');import baseline
 baseline_bytes=(ROOT/'package/baseline.py').read_bytes();original_extract=baseline.extract
 assert hashlib.sha256(baseline_bytes).hexdigest()=='537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
 task=ROOT/'ENGINEERING_PROMPT';task.mkdir();(task/'prompt.txt').write_text('Implement a self-contained fixture.')
 skill,repair='ENGINEERING SKILL','ENGINEERING REPAIR';runtime.skill_texts=lambda:(skill,repair);runtime.map_feedback=lambda *a:'';runtime.vivado_tool=lambda n:'/engineering-fixture/'+n
 code='module TopModule(input a,output out); wire bucket; always @(*) begin bucket=a; end assign out=bucket; endmodule'
 fixed=code.replace('wire bucket','reg bucket');error='ERROR: [VRFC 10-1280] procedural assignment to a non-register bucket is not permitted, left-hand side should be reg/integer/time/genvar'
 unsupported='module TopModule(input a,output out); wire bucket; always @(*) begin bucket=a; a=0; end assign out=bucket; endmodule'
 ansi='module TopModule(input a,output out); always @(*) begin out=a; end endmodule';ansi_error=error.replace('bucket','out')
 cases=[dict(name='mechanical_success',first=code,second=fixed,error=error,compiler=dict(C=[1,0],P=[1,0]),requests=dict(C=2,P=1),callbacks=dict(C=0,P=1)),
 dict(name='failed_recompile_original_repair',first=code,second=fixed,error=error,compiler=dict(C=[1,0],P=[1,1,0]),requests=dict(C=2,P=2),callbacks=dict(C=0,P=1)),
 dict(name='input_writer_abstains',first=unsupported,second=fixed,error=error,compiler=dict(C=[1,0],P=[1,0]),requests=dict(C=2,P=2),callbacks=dict(C=0,P=1)),
 dict(name='existing_ANSI_precedence',first=ansi,second='',error=ansi_error,compiler=dict(C=[1,0],P=[1,0]),requests=dict(C=1,P=1),callbacks=dict(C=0,P=0))]
 rows=[];old_open,old_run=urllib.request.urlopen,subprocess.run;cwd=Path.cwd()
 try:
  for case in cases:
   pair={}
   for arm in ('C','P'):
    folder=ROOT/'ENGINEERING_RESULTS'/case['name']/arm;work=folder/'work';work.mkdir(parents=True);requests=[];compiles=[];receipts=[]
    internal_wire_hook.configure(runtime,arm=='P',receipts.append)
    def transport(request,**kwargs):
     index=len(requests);assert request.full_url=='http://127.0.0.1:8000/v1/chat/completions' and kwargs==dict(timeout=300) and index<case['requests'][arm]<=2
     body=json.loads(request.data);assert body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1 and body['model']=='engineering-fixture-only'
     assert body['messages'][0]==dict(role='system',content=skill+('\n'+repair if index else ''))
     if index:assert body['messages'][1]['content']==(task/'prompt.txt').read_text()+'\nPrevious candidate:\n'+original_extract(case['first'],'rtl')+'\nCandidate diagnostics:\n'+case['error']
     requests.append(body);reply=case['first'] if index==0 else case['second']
     return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=reply),finish_reason='stop')])).encode())
    def compiler(argv,**kwargs):
     assert argv[:2]==['/engineering-fixture/xvlog','--sv'];index=len(compiles);assert index<len(case['compiler'][arm]);rc=case['compiler'][arm][index]
     compiles.append(dict(source=Path(argv[-1]).read_text(),rc=rc));return subprocess.CompletedProcess(argv,rc,'' if rc==0 else case['error'])
    urllib.request.urlopen,subprocess.run=transport,compiler;os.chdir(work);runtime.worker(task,folder)
    assert len(requests)==case['requests'][arm] and len(compiles)==len(case['compiler'][arm]) and len(receipts)==case['callbacks'][arm]
    assert compiles[0]['source']==original_extract(case['first'],'rtl')
    if case['name'].startswith(('mechanical','failed')) and arm=='P':
     assert compiles[1]['source']==original_extract(fixed,'rtl') and receipts[0]['patched_sha256']==hashlib.sha256(compiles[1]['source'].encode()).hexdigest()
    if case['name']=='input_writer_abstains' and arm=='P':assert receipts[0]['reason']=='procedural_port_assignment_present'
    assert (folder/'solution.v').read_text()==compiles[-1]['source']
    assert baseline.extract is original_extract and (ROOT/'package/baseline.py').read_bytes()==baseline_bytes
    pair[arm]=dict(requests=requests,compiles=compiles,receipts=receipts,passed=True)
   assert pair['C']['requests'][0]==pair['P']['requests'][0]
   if len(pair['P']['requests'])==2:assert pair['C']['requests'][1]==pair['P']['requests'][1]
   rows.append(dict(name=case['name'],pair=pair,passed=True))
 finally:urllib.request.urlopen,subprocess.run=old_open,old_run;os.chdir(cwd)
 result=dict(schema='internal_wire_actual_runtime_engineering8_v1',passed=True,contexts=8,actual_project_runtime_executed=True,transport_and_compiler_simulated=True,real_model_calls=0,real_EDA_calls=0,FIFO=False,original_extractor_unchanged=True,official_baseline_unchanged=True,first_request_byte_equal=True,failed_patch_repair_body_byte_equal=True,original_ANSI_precedence=True,max_requests_two=True,repair_limit_one=True,max_tokens8192=True,HTTP_timeout300=True,native_qualified=False,score_measured=False,rows=rows)
 (ROOT/'ACTUAL_ENGINEERING_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
if __name__=='__main__':main()
