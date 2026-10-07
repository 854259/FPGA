
"""New AMD engineering controls only: simulated HTTP/compiler, zero model/EDA."""
import hashlib,importlib.util,io,json,os,subprocess,sys,urllib.request
from pathlib import Path
import agent_extract_hook
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode
 os.environ.update(MODEL_NAME='engineering-fixture-only',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
 runtime=load('lexical_hook_actual_runtime',ROOT/'package/agent/map_runtime.py')
 import baseline
 original_function=baseline.extract;baseline_sha=sha(ROOT/'package/baseline.py')
 assert baseline_sha=='537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
 # Independent synthetic prompt is deliberately outside every mechanical feedback family.
 task=ROOT/'ENGINEERING_PROMPT';task.mkdir();(task/'prompt.txt').write_text('Implement a self-contained combinational fixture.',encoding='utf-8')
 skill,repair='ENGINEERING SKILL','ENGINEERING REPAIR';runtime.skill_texts=lambda:(skill,repair)
 runtime.vivado_tool=lambda name:'/engineering-fixture/'+name
 runtime.map_feedback=lambda *args:''
 fixture=json.loads((ROOT/'SYNTHETIC_CASES.json').read_bytes())
 changed=fixture['positive_boundary_cases'][1]
 missing=fixture['negative_abstention_cases'][0]['text']
 cases=[dict(name='first_success',replies=[changed['text']],compile_rc=[0]),
        dict(name='repair_success',replies=[changed['text'],changed['text']],compile_rc=[1,0]),
        dict(name='repair_exhausted',replies=[changed['text'],changed['text']],compile_rc=[1,1]),
        dict(name='unsupported_falls_back',replies=[missing,missing],compile_rc=[1,1])]
 rows=[]
 original_open,original_run=urllib.request.urlopen,subprocess.run
 previous=Path.cwd()
 try:
  for case in cases:
   pair={}
   for arm in ('C','P'):
    folder=ROOT/'ENGINEERING_RESULTS'/case['name']/arm;folder.mkdir(parents=True);work=folder/'work';work.mkdir()
    requests=[];compiles=[];receipts=[]
    agent_extract_hook.configure(runtime,arm=='P',receipts.append)
    def transport(request,**kwargs):
     assert request.full_url=='http://127.0.0.1:8000/v1/chat/completions' and kwargs==dict(timeout=300)
     index=len(requests);assert index<len(case['replies']) and index<2
     body=json.loads(request.data);assert body['model']=='engineering-fixture-only' and body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
     assert body['messages'][0]==dict(role='system',content=skill+('\n'+repair if index else ''))
     requests.append(body)
     return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=case['replies'][index]),finish_reason='stop')],usage={})).encode())
    def compiler(argv,**kwargs):
     assert argv[0]=='/engineering-fixture/xvlog' and argv[1]=='--sv'
     index=len(compiles);assert index<len(case['compile_rc'])
     compiles.append(dict(code=Path(argv[-1]).read_text(),cwd=str(kwargs['cwd'])))
     return subprocess.CompletedProcess(argv,case['compile_rc'][index],'' if case['compile_rc'][index]==0 else 'ERROR: independent fixture failure')
    urllib.request.urlopen,subprocess.run=transport,compiler;os.chdir(work)
    runtime.worker(task,folder)
    assert len(requests)==len(case['replies']) and len(compiles)==len(case['compile_rc'])
    assert len(receipts)==(len(requests) if arm=='P' else 0)
    assert runtime.RTL_EXTRACTOR is None if arm=='C' else callable(runtime.RTL_EXTRACTOR)
    for i,text in enumerate(case['replies']):
     expected=original_function(text,'rtl') if arm=='C' or case['name']=='unsupported_falls_back' else changed['expected_code']
     assert compiles[i]['code']==expected
     if i:
      assert requests[i]['messages'][1]['content']==(task/'prompt.txt').read_text()+'\nPrevious candidate:\n'+compiles[i-1]['code']+'\nCandidate diagnostics:\nERROR: independent fixture failure'
    assert baseline.extract is original_function and sha(ROOT/'package/baseline.py')==baseline_sha
    pair[arm]=dict(requests=requests,compiles=compiles,receipts=receipts,passed=True)
   assert pair['C']['requests'][0]==pair['P']['requests'][0]
   for i in range(len(case['replies'])):
    assert pair['C']['requests'][i]['messages'][0]==pair['P']['requests'][i]['messages'][0]
   rows.append(dict(name=case['name'],pair=pair,passed=True))
 finally:
  urllib.request.urlopen,subprocess.run=original_open,original_run;os.chdir(previous)
 result=dict(schema='agent_lexical_hook_actual_engineering8_v1',passed=True,contexts=8,actual_project_runtime_executed=True,transport_and_compiler_simulated=True,real_model_calls=0,real_EDA_calls=0,FIFO=False,official_baseline_unchanged=True,first_request_C_P_byte_equal=True,repair_limit_one=True,max_requests_two=True,max_tokens_8192=True,HTTP_timeout_300=True,native_qualified=False,score_measured=False,rows=rows)
 with (ROOT/'ACTUAL_ENGINEERING_RESULT.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
if __name__=='__main__':main()
