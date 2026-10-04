"""FIFO-owned Linux bridge integration, then constructed real native parity."""
import argparse,datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
import guard_wrapper as guard
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kit',type=Path,required=True);ap.add_argument('--resource-check',type=Path,required=True);a=ap.parse_args()
    spec=json.loads((ROOT/'RUN_SPEC.json').read_text());specsha=sha(ROOT/'RUN_SPEC.json')
    check=json.loads(a.resource_check.read_text());start=time.monotonic()
    manifest=json.loads((ROOT/'INPUT_MANIFEST.json').read_text())
    def gate(first=False):
        assert sys.platform=='linux' and sha(ROOT/'RUN_SPEC.json')==specsha
        for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
        assert check['resource_idle'] and Path(check['slot_lock_path']).read_text().splitlines()[0]==check['slot_owner']
        assert sha(Path(check['slot_lock_path']))==check['slot_lock_sha256']
        assert guard.identity(spec['model_pid'])==check['model_identity']
        assert guard.protected(a.kit)==check['protected']
        assert check['protected']['tasks']==manifest['input_sha256'] and check['protected']['official']==manifest['official_sha256']
        if first:
            age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(check['checked_at_utc'])).total_seconds()
            assert 0<=age<=120
        assert time.monotonic()-start<spec['timeout_s']
    gate(True)
    out=ROOT/'results';out.mkdir(exist_ok=False)
    report={'schema':'formal_bridge_linux_integration_v1','complete':False,'passed':False,'run_spec_sha256':specsha,'actual_model_requests':0,'actual_native_probes':0,'actual_compile_commands':0,'actual_synthesis_commands':0,'formal_deployment_changed':False,'quality_score_measured':False,'independent_natural_tasks':0,'target_offline_single32gb_verified':False}
    save(out/'summary.json',report)
    try:
        commands=[('linux_tests',[sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v']),('native_parity',[sys.executable,'-B',str(ROOT/'native_parity.py')])]
        for name,argv in commands:
            gate()
            if name=='native_parity':
                report.update(actual_native_probes=None,actual_compile_commands=None)
                save(out/'summary.json',report)
            with (out/(name+'.log')).open('xb') as stream:
                result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=min(240,spec['timeout_s']-(time.monotonic()-start)))
            report[name]={'returncode':result.returncode,'log_sha256':sha(out/(name+'.log'))}
            save(out/'summary.json',report)
            assert result.returncode==0,name
            if name=='linux_tests':
                text=(out/(name+'.log')).read_text()
                assert 'Ran 14 tests' in text and '\nOK\n' in text and 'skipped' not in text
                report['linux_tests_passed']=14;report['fake_protocol_consecutive_requests']=200
            else:
                native=json.loads((out/'native_parity/summary.json').read_text())
                assert native['passed'] and native['complete']
                for key in ['actual_native_probes','actual_compile_commands','actual_synthesis_commands']:report[key]=native[key]
                report['native_scope']=native['scope']
        gate();report.update(complete=True,passed=True)
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        if (out/'native_parity/summary.json').exists():
            native=json.loads((out/'native_parity/summary.json').read_text())
            report['native_receipt_sha256']=sha(out/'native_parity/summary.json')
            for key in ['actual_native_probes','actual_compile_commands','actual_synthesis_commands','completed_native_receipts_observed']:report[key]=native.get(key)
        report['elapsed_s']=time.monotonic()-start;save(out/'summary.json',report)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
