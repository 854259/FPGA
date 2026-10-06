"""Frozen AMD observer; never independently retries an original terminal audit."""
import argparse,hashlib,importlib.util,json,os,sys,time,traceback
from pathlib import Path
import terminal_outer
ROOT=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(Path(f).read_bytes()).hexdigest()
read=lambda f:json.loads(Path(f).read_bytes())
def save(f,j):
    with Path(f).open('x',encoding='utf-8') as o:json.dump(j,o,indent=2);o.write('\n')
def model():
    d=Path('/proc/2013333');v=(d/'stat').read_text().rsplit(')',1)[1].split()
    assert v[0] not in ('Z','X') and v[19]=='823869819' and sha(d/'cmdline')=='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'
    return v[19],sha(d/'cmdline')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--role',choices=('wave105','onehot106','serial107'),required=True);a=parser.parse_args()
    assert sys.platform=='linux' and sys.dont_write_bytecode and sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
    manifest=read(ROOT/'SOURCE_MANIFEST.json');assert {n:sha(ROOT/n) for n in manifest}==manifest
    cfg=read(ROOT/'MONITOR_CONFIG.json')[a.role];child=Path(cfg['child_root']);observer=Path(cfg['observer_root'])
    assert not observer.exists(),'Unknown result: read same physical observer only'
    assert sha(child/'SOURCE_MANIFEST.json')==cfg['child_manifest_sha256'] and read(child/'SOURCE_MANIFEST.json')==cfg['child_sources']
    assert {n:sha(child/n) for n in cfg['child_sources']}==cfg['child_sources']
    original=Path(cfg['original_root']);assert not (original/cfg['original_once_intent']).exists(),'Original intent already exists: do not retry'
    capture=read(ROOT/'PROTECTED_GROUPS_CAPTURE.json')
    s=importlib.util.spec_from_file_location('monitor_original_protection',ROOT/'dependencies/protected_sources.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    before=m.check(capture);model_before=model()
    observer.mkdir();pid=os.getpid();d=Path('/proc')/str(pid);v=(d/'stat').read_text().rsplit(')',1)[1].split()
    save(observer/'OBSERVER_IDENTITY.json',dict(pid=pid,starttime=v[19],command_sha256=sha(d/'cmdline'),role=a.role))
    result=dict(complete=False,passed=False,error=None,source_manifest=manifest,role=a.role,terminal_subject=str(child/'terminal_supervisor.py'),original_audit_retries=0,model_calls=0,eda_calls=0,new_fifo=False)
    started=time.monotonic()
    try:
        external=terminal_outer.run([sys.executable,'-B',str(child/'terminal_supervisor.py')],child,observer/'external',cfg['total_cap_s'],20,[child/n for n in cfg['required_final_files']],2013333)
        result['external_process']=external
        assert external['passed'] and not external['fake_cleanup_injection_used']
        terminal=read(child/'TERMINAL_REVIEW_RECEIPT.json');assert terminal['complete'] and terminal['passed'] and terminal['error'] is None
        assert terminal['outer_budget']['total_cap_s']==cfg['total_cap_s'] and not terminal['outer_budget']['working_deadline_expired']
        assert m.check(capture)==before and model()==model_before
        assert {n:sha(ROOT/n) for n in manifest}==manifest and {n:sha(child/n) for n in cfg['child_sources']}==cfg['child_sources']
        result.update(passed=True,terminal_receipt_sha256=sha(child/'TERMINAL_REVIEW_RECEIPT.json'),original_archive_sha256=sha(child/cfg['archive_name']),protected_unchanged=True,model_unchanged=True)
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc);(observer/'FAILURE_TRACEBACK.txt').write_text(traceback.format_exc())
    finally:
        result.update(complete=True,observer_elapsed_s=time.monotonic()-started,observer_exit_verified_by_this_receipt=False)
        save(observer/'MONITOR_RESULT.json',result)
    print(json.dumps(dict(complete=True,passed=result['passed'],error=result['error'])))
    return 0 if result['passed'] else 1
if __name__=='__main__':sys.exit(main())
