"""Pure protocol/budget/mean tests; fake backend and judge, no real inference/EDA."""
import copy,hashlib,json,os,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import measure,stage,bind_run
ROOT=Path(__file__).resolve().parent
TASKS=['Prob112_always_case2','Prob115_shift18','Prob122_kmap4']
class Score:
    def summarize(self,groups):return {'tasks':len(groups),'scored_tasks':len(groups),'samples_per_task':len(next(iter(groups.values()))),'tool_errors':0}
def rows():return [{'task':t,'sample_index':i,'mode':m,'verdict':{'task_id':t,'tool_error':False,'level':3,'coefficient':1},'model':{'unconfirmed_attempts':0,'supervisor_deadline':False,'attempted_model_posts':1}} for t,i,m in measure.order(TASKS)]
def put_requests(root,bodies):
    root.mkdir(exist_ok=True);lines=[]
    for i,b in enumerate(bodies):
        raw=json.dumps(b).encode();(root/(str(i)+'.request.json')).write_bytes(raw);lines.append({'index':i,'body_sha256':hashlib.sha256(raw).hexdigest(),'pid':123})
    (root/'requests.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in lines),encoding='utf-8')
def body(user='prompt',system='skill'):return {'model':'fake-model','max_tokens':8192,'temperature':0,'top_p':1,'messages':[{'role':'system','content':system},{'role':'user','content':user}]}

class Pilot(unittest.TestCase):
    def test_binding_rejects_synthetic_or_rejected_full_before_any_real_run(self):
        bridge=[{'passed':True,'actual_execution_verified':True,'evidence_kind':'completed_cloud_stage','run_spec_sha256':s} for s in ['a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3']]
        full={'full156_evidence_valid':True,'evidence_valid':True,'historical_fixture_only':False,'candidate_qualified_for_independent_validation':True,'spec_sha256':'43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7','archive_sha256':'fixture-identity'}
        decision={'actual_full_result_processed':True,'fixture_only':False,'qualified_for_independent_validation_after_attribution':True,'source_spec_sha256':full['spec_sha256'],'archive_sha256':full['archive_sha256']}
        self.assertEqual(len(bind_run.prerequisites(*bridge,full,decision)),2)
        for kind in ['synthetic','full_reject','no_match','wrong_archive']:
            b,f,d=copy.deepcopy(bridge),copy.deepcopy(full),copy.deepcopy(decision)
            if kind=='synthetic':b[0]['actual_execution_verified']=False
            elif kind=='full_reject':f['candidate_qualified_for_independent_validation']=False
            elif kind=='no_match':d['qualified_for_independent_validation_after_attribution']=False
            else:d['archive_sha256']='other'
            with self.subTest(kind=kind),self.assertRaises(AssertionError):bind_run.prerequisites(*b,f,d)
    def test_five_per_task_mean_not_best_and_paired_order(self):
        r=rows();r[0]['verdict'].update(level=1,coefficient=.2);out=measure.aggregate(r,TASKS,Score());self.assertAlmostEqual(out['task_five_sample_means']['baseline'][TASKS[0]],.84);self.assertAlmostEqual(out['coefficients']['baseline'],(2+.84)/3);self.assertFalse(out['full156_five_sample_measured']);self.assertFalse(out['adoption']);self.assertEqual(len(r),30)
    def test_partial_or_reordered_or_tool_error_rejected(self):
        r=rows()
        for bad in [r[:-1],list(reversed(r))]:
            with self.assertRaises(AssertionError):measure.aggregate(bad,TASKS,Score())
        r[0]['verdict']['tool_error']=True
        with self.assertRaises(AssertionError):measure.aggregate(r,TASKS,Score())
    def test_request_identity_budget_original_skills_and_actual_fact(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);second=body('prompt\nPrevious candidate:\nsource\nCandidate diagnostics:\nactual negative','skill\nrepair');put_requests(root,[body(),second]);trace='\n'.join(json.dumps(e) for e in [{'tool':'llm','round':0},{'tool':'map_feedback','round':0,'repair_available':True,'excerpt':'actual negative'},{'tool':'llm','round':1}]);r=measure.requests(root,trace,'agent','prompt','','fake-model',('skill','repair'),'baseline');self.assertEqual(r['attempted_model_posts'],2)
            for mutate in ['temperature','fact','system','hash']:
                bad=copy.deepcopy(second)
                if mutate=='temperature':bad['temperature']=.2
                elif mutate=='fact':bad['messages'][1]['content']=bad['messages'][1]['content'].replace('actual negative','invented')
                elif mutate=='system':bad['messages'][0]['content']='different'
                put_requests(root,[body(),bad])
                if mutate=='hash':(root/'1.request.json').write_text('{}')
                with self.subTest(mutate=mutate),self.assertRaises(AssertionError):measure.requests(root,trace,'agent','prompt','','fake-model',('skill','repair'),'baseline')
    def test_baseline_one_call_no_tools_and_unconfirmed_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);put_requests(root,[body(system='baseline')]);trace=json.dumps({'tool':'baseline_meta'})+'\n'+json.dumps({'tool':'llm','error':'timeout'})
            out=measure.requests(root,trace,'baseline','prompt','','fake-model',('skill','repair'),'baseline');self.assertEqual(out['unconfirmed_attempts'],1)
            with self.assertRaises(AssertionError):measure.requests(root,trace+'\n'+json.dumps({'tool':'lint'}),'baseline','prompt','','fake-model',('skill','repair'),'baseline')
    def test_audit_hook_preserves_exact_utf8_bytes_and_observes_only_posts(self):
        with tempfile.TemporaryDirectory() as td:
            env=dict(os.environ,PYTHONPATH=str(ROOT/'request_audit'),RTL_REQUEST_AUDIT_DIR=td)
            script="import sys,json;raw=json.dumps({'messages':[{'content':'观察，不改请求'}]},ensure_ascii=False).encode();sys.audit('urllib.Request','http://127.0.0.1:8000/v1/models',None,{},'GET');sys.audit('urllib.Request','http://127.0.0.1:8000/v1/chat/completions',raw,{},'POST');print(raw.hex())"
            p=subprocess.run([sys.executable,'-B','-c',script],env=env,capture_output=True,encoding='utf-8');self.assertEqual(p.returncode,0,p.stderr);self.assertEqual((Path(td)/'0.request.json').read_bytes(),bytes.fromhex(p.stdout.strip()));self.assertEqual(len((Path(td)/'requests.jsonl').read_text().splitlines()),1)
    def test_real_http_package_handler_thirty_fake_solves_copy_outputs_mean_and_no_real_calls(self):
        app=stage.load('test_five_bridge',ROOT/'package/agent/runtime.py');app.verify_package();original_load=stage.load
        def fake_load(name,path):
            if name=='five_actual_bridge':return app
            if name=='five_outer_judge':return types.SimpleNamespace(judge_sample=lambda task,solution,*args:{'task_id':task.name,'tool_error':False,'judge_evidence_complete':True,'level':3,'coefficient':1})
            if name=='five_official_score':return Score()
            return original_load(name,path)
        def fake_job(mode,task,out,seconds):
            out.mkdir();text=(task/'prompt.txt').read_text();iface=(task/'interface.txt').read_text() if (task/'interface.txt').exists() else '';user=text+('\n\nInterface:\n'+iface if iface else '');system=app.core.skill_texts()[0] if mode=='agent' else original_load('fake_baseline',ROOT/'package/baseline.py').SYS['rtl']
            put_requests(Path(os.environ['RTL_REQUEST_AUDIT_DIR']),[body(user,system)])
            events=[{'tool':'llm','round':0}]
            if mode=='baseline':events.insert(0,{'tool':'baseline_meta','script_sha256':stage.sha(ROOT/'package/baseline.py'),'served_model':'fake-model'})
            trace=''.join(json.dumps(e)+'\n' for e in events);code='module TopModule;endmodule\n';(out/'trace.jsonl').write_text(trace);(out/'solution.v').write_text(code);return code,trace
        with tempfile.TemporaryDirectory(prefix='formal-five-fixture-') as td:
            root=Path(td);kit=root/'kit';out=root/'out';out.mkdir()
            for task in TASKS:
                p=kit/'bench/tasks_veval'/task;p.mkdir(parents=True);(p/'prompt.txt').write_text('synthetic test prompt');(p/'interface.txt').write_text('synthetic interface')
            gates=[]
            with patch.object(stage,'load',side_effect=fake_load),patch.object(app,'run_job',side_effect=fake_job),patch.object(app.core,'health',return_value={'ready':True,'model':'fake-model','track':'rtl','vram_gb':1}):
                r=stage.run({'task_ids':TASKS,'model':'fake-model','solve_deadline_s':3,'judge_timeout_s':3},{},kit,out,lambda:gates.append(True))
            self.assertTrue(r['passed'],r.get('error'));self.assertEqual(len(r['rows']),30);self.assertEqual(len(list(out.glob('samples/*/*/*/http_worker/solution.v'))),30);self.assertFalse(r['adoption']);self.assertGreater(len(gates),30)
if __name__=='__main__':unittest.main()
