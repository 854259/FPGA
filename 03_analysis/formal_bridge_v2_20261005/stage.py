"""Queued v2 health integration; requires v1 native parity complete and guarded."""
import argparse,datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
import guard_wrapper as guard
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kit',type=Path,required=True);ap.add_argument('--resource-check',type=Path,required=True);a=ap.parse_args()
    spec=json.loads((ROOT/'RUN_SPEC.json').read_text());specsha=sha(ROOT/'RUN_SPEC.json');check=json.loads(a.resource_check.read_text());manifest=json.loads((ROOT/'INPUT_MANIFEST.json').read_text());start=time.monotonic()
    out=ROOT/'results';out.mkdir(exist_ok=False)
    report={'schema':'formal_bridge_v2_health_integration_v1','complete':False,'passed':False,'run_spec_sha256':specsha,'actual_model_requests':0,'actual_native_probes':0,'actual_compile_commands':0,'actual_synthesis_commands':0,'actual_vivado_version_commands':0,'formal_deployment_changed':False,'quality_score_measured':False,'target_offline_single32gb_verified':False}
    save(out/'summary.json',report)
    def gate(first=False):
        assert sys.platform=='linux' and sha(ROOT/'RUN_SPEC.json')==specsha
        for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
        assert Path(check['slot_lock_path']).read_text().splitlines()[0]==check['slot_owner'] and sha(Path(check['slot_lock_path']))==check['slot_lock_sha256']
        assert guard.identity(spec['model_pid'])==check['model_identity'] and guard.protected(a.kit)==check['protected']
        assert check['protected']['tasks']==manifest['input_sha256'] and check['protected']['official']==manifest['official_sha256']
        if first:
            age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(check['checked_at_utc'])).total_seconds();assert 0<=age<=120
        assert time.monotonic()-start<spec['timeout_s']
    try:
        gate(True)
        prior=Path(spec['prerequisite_cloud'])
        assert sha(prior/'RUN_SPEC.json')==spec['prerequisite_spec_sha256']
        p=json.loads((prior/'RUN_SPEC.json').read_text())
        for n,h in p['source_hashes'].items():assert sha(prior/n)==h
        for n in ['results/summary.json','guard/status.json']:
            p=json.loads((prior/n).read_text());assert p['complete'] and p['passed'],n
        report['prerequisite_v1_native_stage_passed']=True
        for name,argv in [('linux_tests',[sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v']),('live_health',[sys.executable,'-B',str(ROOT/'live_health.py')])]:
            gate()
            if name=='live_health':report['actual_vivado_version_commands']=None;save(out/'summary.json',report)
            with (out/(name+'.log')).open('xb') as stream:
                result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=min(240,spec['timeout_s']-(time.monotonic()-start)))
            report[name]={'returncode':result.returncode,'log_sha256':sha(out/(name+'.log'))};save(out/'summary.json',report)
            assert result.returncode==0,name
            if name=='linux_tests':
                text=(out/(name+'.log')).read_text();assert 'Ran 21 tests' in text and '\nOK\n' in text and 'skipped' not in text
                report['linux_tests_passed']=21;report['fake_protocol_consecutive_requests']=200
        gate();report.update(complete=True,passed=True)
    except BaseException as error:report['error']=type(error).__name__+': '+str(error)
    finally:
        if (out/'live_health/summary.json').exists():
            live=json.loads((out/'live_health/summary.json').read_text());report['actual_vivado_version_commands']=live['actual_vivado_version_commands'];report['live_health_receipt_sha256']=sha(out/'live_health/summary.json')
        report['elapsed_s']=time.monotonic()-start;save(out/'summary.json',report)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
