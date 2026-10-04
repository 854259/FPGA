"""FIFO-only actual packaged HTTP five-sample pilot; no deployment or full-score claim."""
import argparse,datetime,hashlib,importlib.util,json,os,shutil,sys,threading,time,urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import guard_wrapper as guard
import measure
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def run(spec,check,kit,out,gate):
    app=load('five_actual_bridge',ROOT/'package/agent/runtime.py');app.verify_package()
    baseline=load('five_pinned_baseline',ROOT/'package/baseline.py')
    evaluator=load('five_outer_judge',ROOT/'official_eval_guarded.py');evaluator.OFFICIAL=kit/'official_reference'
    scorer=load('five_official_score',kit/'official_reference/selftest/score.py')
    token='fifo-owned-five-sample-local';active={}
    def capture(mode,task,work,seconds):
        sample=active['sample'];audit=sample/'request_audit'
        # Audit hooks observe urllib attempts only. No transport, response,
        # model body, parser, compiler, or production package is patched.
        pythonpath=str(ROOT/'request_audit')+(os.pathsep+os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
        try:
            with patch.dict(os.environ,PYTHONPATH=pythonpath,RTL_REQUEST_AUDIT_DIR=str(audit)):
                return app.run_job(mode,task,work,seconds)
        finally:
            if work.exists():shutil.copytree(work,sample/'http_worker')
    server=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True)
    report={'schema':'formal_five_known_pilot_v1','complete':False,'passed':False,'rows':[],'fresh_generation_not_replay':True,'formal_deployment_changed':False,'independent_natural_tasks':0,'full156_five_sample_measured':False,'target_offline_single32gb_verified':False,'adoption':False}
    save(out/'summary.json',report)
    def request(path,payload=None):
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=spec['solve_deadline_s']+30) as response:return json.load(response)
    try:
        with patch.dict(os.environ,LLM_BASE_URL='http://127.0.0.1:8000/v1',MODEL_NAME=spec['model'],RTL_PROFILE='submission',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',FPGACHINA_TOKEN=token),patch.object(app.core,'run_job',side_effect=capture):
            thread.start();gate()
            reply=request('/v1/health');save(out/'health.json',reply)
            assert reply['ready'] and reply['model']==spec['model'] and reply['track']=='rtl'
            # This gate is an instantaneous attributed development-card check,
            # not a peak/capacity/target-R9700/offline certificate.
            assert reply['vram_gb'] is not None and 0<=reply['vram_gb']<=32
            for task,index,mode in measure.order(spec['task_ids']):
                assert not (ROOT/'STOP_AFTER_CURRENT').exists(),'Boundary stop requested'
                gate();sample=out/'samples'/mode/task/str(index);sample.mkdir(parents=True,exist_ok=False);active['sample']=sample
                taskroot=kit/'bench/tasks_veval'/task
                prompt=(taskroot/'prompt.txt').read_text(encoding='utf-8');iface=taskroot/'interface.txt';interface=iface.read_text(encoding='utf-8') if iface.exists() else ''
                payload={'task_id':task,'nonce':f'actual-five-{mode}-{index}','prompt':prompt,'interface':interface,'mode':mode,'deadline_s':spec['solve_deadline_s']}
                save(sample/'http_request.json',payload);started=time.monotonic();reply=request('/v1/solve',payload);solve_s=time.monotonic()-started;save(sample/'http_reply.json',reply)
                assert reply['task_id']==task and isinstance(reply['solution'],str) and isinstance(reply['trace'],str)
                worker=sample/'http_worker';solution=worker/'solution.v'
                assert solution.read_text(encoding='utf-8')==reply['solution'] and (worker/'trace.jsonl').read_text(encoding='utf-8')==reply['trace']
                model=measure.requests(sample/'request_audit',reply['trace'],mode,prompt,interface,spec['model'],app.core.skill_texts(),baseline.SYS['rtl'])
                events=[json.loads(s) for s in reply['trace'].splitlines()]
                if mode=='baseline':
                    meta=next(e for e in events if e['tool']=='baseline_meta');assert meta['script_sha256']==sha(ROOT/'package/baseline.py') and meta['served_model']==spec['model']
                # Judge inputs never enter HTTP payload or model subprocess.
                gate();judgeout=sample/'judge';judgeout.mkdir()
                verdict=evaluator.judge_sample(taskroot,solution,judgeout,judgeout/'verdict.json',spec['judge_timeout_s'])
                assert not verdict['tool_error'] and verdict['task_id']==task and verdict['judge_evidence_complete']
                row={'task':task,'sample_index':index,'mode':mode,'solution_sha256':sha(solution),'http_request_sha256':sha(sample/'http_request.json'),'http_reply_sha256':sha(sample/'http_reply.json'),'solve_elapsed_s':solve_s,'model':model,'verdict':verdict}
                save(sample/'row.json',row);report['rows'].append(row);save(out/'summary.json',report)
            gate();report.update(measure.aggregate(report['rows'],spec['task_ids'],scorer));report.update(complete=True,passed=True)
    except BaseException as e:report['error']=type(e).__name__+': '+str(e)
    finally:
        if thread.is_alive():server.shutdown();thread.join(timeout=5)
        server.server_close();save(out/'summary.json',report)
    return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kit',type=Path,required=True);ap.add_argument('--resource-check',type=Path,required=True);a=ap.parse_args()
    assert sys.platform=='linux'
    spec=json.loads((ROOT/'RUN_SPEC.json').read_text());specsha=sha(ROOT/'RUN_SPEC.json');check=json.loads(a.resource_check.read_text());manifest=json.loads((ROOT/'INPUT_MANIFEST.json').read_text());start=time.monotonic()
    def gate(first=False):
        assert sha(ROOT/'RUN_SPEC.json')==specsha
        for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
        assert guard.identity(spec['model_pid'])==check['model_identity'] and guard.protected(a.kit)==check['protected']
        assert check['protected']['tasks']==manifest['input_sha256'] and check['protected']['official']==manifest['official_sha256']
        assert sha(Path(check['slot_lock_path']))==check['slot_lock_sha256'] and Path(check['slot_lock_path']).read_text().splitlines()[0]==check['slot_owner']
        if first:
            age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(check['checked_at_utc'])).total_seconds();assert 0<=age<=120
        assert time.monotonic()-start<spec['stage_timeout_s']-60
    gate(True)
    # Require prior real bridge/native + health and readonly audits before any POST.
    for entry in spec['prerequisites']:
        root=Path(entry['cloud_root']);assert sha(root/'RUN_SPEC.json')==entry['spec_sha256']
        old=json.loads((root/'RUN_SPEC.json').read_text())
        for n,h in old['source_hashes'].items():assert sha(root/n)==h,n
        for name in ['results/summary.json','guard/status.json']:
            prior=json.loads((root/name).read_text());assert prior['complete'] and prior['passed']
    for entry in spec['required_readonly_audits']:
        p=ROOT/entry['path'];assert sha(p)==entry['sha256'];e=json.loads(p.read_text());assert e['passed'] and e['actual_execution_verified'] and e['evidence_kind']=='completed_cloud_stage'
    full=json.loads((ROOT/'prerequisite_audits/full156.json').read_text())
    decision=json.loads((ROOT/'prerequisite_audits/attribution.json').read_text())
    assert full['full156_evidence_valid'] and full['candidate_qualified_for_independent_validation'] and full['spec_sha256']=='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
    assert decision['actual_full_result_processed'] and decision['qualified_for_independent_validation_after_attribution'] and decision['audit_result_sha256']==sha(ROOT/'prerequisite_audits/full156.json')
    out=ROOT/'results';out.mkdir(exist_ok=False);report=run(spec,check,a.kit,out,gate)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
