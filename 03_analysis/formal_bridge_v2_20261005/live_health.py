"""FIFO-owned real GET health on shared endpoint; never POST a model request."""
import json,os,sys,threading,urllib.error,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from test_bridge import app
ROOT=Path(__file__).resolve().parent
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    assert sys.platform=='linux'
    out=ROOT/'results/live_health';out.mkdir()
    expected=json.loads((ROOT/'RUN_SPEC.json').read_text())
    app.health_probe.VERSIONS.clear()
    calls=[];real=app.health_probe.subprocess.Popen
    def recorded(argv,*args,**kwargs):
        assert argv==['/workspace/AMD/2026.1/Vivado/bin/vivado','-version']
        proc=real(argv,*args,**kwargs);calls.append({'argv':argv,'pid':proc.pid,'owned_version_command':True});return proc
    server=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    report={'complete':False,'passed':False,'actual_model_requests':0,'actual_vivado_version_commands':None,'target_offline_single32gb_verified':False,'formal_deployment_changed':False}
    save(out/'summary.json',report)
    def get(token):
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/health',headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
    try:
        with patch.dict(os.environ,LLM_BASE_URL='http://127.0.0.1:8000/v1',MODEL_NAME=expected['model'],RTL_PROFILE='submission',FPGACHINA_TOKEN='fifo-owned-local-health-only'),patch.object(app.health_probe.subprocess,'Popen',side_effect=recorded):
            try:get('invalid')
            except urllib.error.HTTPError as error:assert error.code==401
            else:raise AssertionError('Unauthenticated health must not be accepted')
            reply=get('fifo-owned-local-health-only');again=get('fifo-owned-local-health-only')
            observation=app.health_probe.observe(app.core.endpoint())
            report.update(http_reply=reply,second_http_reply=again,observation=observation,actual_version=app.core.vivado_version(app.core.vivado_tool('vivado')))
            assert reply['ready'] and again['ready'] and reply['track']=='rtl' and reply['model']==expected['model']
            assert observation and observation['model_pid']==expected['model_pid'] and observation['model_starttime']=='823869819'
            assert 0<=reply['vram_gb']<=32 and report['actual_version']=='2026.1'
            assert len(calls)==1,'Successful version query must be reused by subsequent health calls'
        report.update(complete=True,passed=True)
    except BaseException as error:report['error']=type(error).__name__+': '+str(error);raise
    finally:
        server.shutdown();server.server_close();thread.join()
        report.update(actual_vivado_version_commands=len(calls),version_calls=calls)
        save(out/'summary.json',report)
    return 0
if __name__=='__main__':raise SystemExit(main())
