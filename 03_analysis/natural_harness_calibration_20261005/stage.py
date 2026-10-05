"""Frozen original natural harness controls, zero model requests and no adoption."""
from pathlib import Path
import argparse,ctypes,hashlib,importlib.util,json,os,sys,time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,d):
    p=Path(p);tmp=p.with_name(p.name+'.pending');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def dependencies(spec):
    prefix=Path(spec['toolchain']['prefix']);site=Path(spec['python_site']['path'])
    for entry,base in [(spec['toolchain'],prefix),(spec['python_site'],site)]:
        actual={p.relative_to(base).as_posix():sha(p) for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        assert actual==entry['files'],str(base)
    return prefix,site

def main(args):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=read(ROOT/'RUN_SPEC.json')
    assert spec['model_requests_max']==0 and spec['stage_timeout_s']==1200 and len(spec['record_ids'])==3
    for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
    paired=load('owned_natural_commands',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    for n,h in spec['dependency_hashes'].items():assert sha(Path(spec['dependencies_cloud'])/n)==h,n
    paired.REPO=ROOT;paired.check_resource(args.resource_check,args.kit,first=True)
    prefix,site=dependencies(spec)
    private=read(ROOT/'raw_evidence/CONTROLS.json')
    data=(ROOT/'raw_evidence/ORIGINAL_DATASET.jsonl').read_bytes();assert hashlib.sha256(data).hexdigest()==spec['dataset_sha256']
    dataset={r['id']:r for r in (json.loads(line) for line in data.decode().splitlines())}
    out=ROOT/'results';out.mkdir(exist_ok=False)
    tools=ROOT/'tools/bin';tools.mkdir(parents=True)
    for name in ['iverilog','vvp']:
        target=tools/name;target.write_bytes((ROOT/'tool_journal.py').read_bytes());target.chmod(0o755)
    result=dict(schema='natural_harness_calibration_v1',complete=False,passed=False,error=None,
        run_spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],model_calls=0,adoption=False,
        independent_model_tasks=0,eligible_for_independent_models=False)
    tick=time.monotonic()
    def gate():
        assert time.monotonic()-tick<spec['stage_timeout_s']-60
        paired.check_resource(args.resource_check,args.kit)
    prepared=[]
    try:
        for case in private['cases']:
            row=dataset[case['record_id']]
            assert hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()==case['record_sha256']
            assert row['input']['context']=={} and all(v=='' for v in row['output']['context'].values())
            original=row['harness']['files'];assert {n:hashlib.sha256(s.encode()).hexdigest() for n,s in original.items()}==case['harness_sha256']
            for control in case['controls']:
                folder=out/case['record_id']/control['label'];folder.mkdir(parents=True)
                content=dict(original);content[case['rtl_path']]=control['rtl']
                if control['label']=='failure_propagation':content[case['test_path']]=original[case['test_path']]+'\n    raise AssertionError("OWN_NATURAL_FAILURE_PROPAGATION")\n'
                for name,text in content.items():
                    path=folder/name;assert path.resolve().is_relative_to(folder.resolve());path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(text.encode())
                source_hashes={n:sha(folder/n) for n in content}
                save(folder/'SOURCE_MANIFEST.json',source_hashes)
                prepared.append((case,control,folder,source_hashes))
        save(out/'PREPARED.json',dict(controls=len(prepared),all_materialized_before_execution=True))
        for case,control,folder,source_hashes in prepared:
            gate();label=control['label'];journal=folder/'native_receipts'
            env=dict(PATH=str(tools)+':'+str(prefix/'bin')+':'+os.environ['PATH'],PYTHONPATH=str(site)+':'+str(folder/'src'),
                PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0',COCOTB_RANDOM_SEED='20261005',
                SIM='icarus',TOPLEVEL_LANG='verilog',TOPLEVEL=case['top'],MODULE=case['module'],
                VERILOG_SOURCES=str(folder/case['rtl_path']),OWN_CALIBRATION_ROOT=str(ROOT),OWN_NATIVE_JOURNAL=str(journal))
            argv=['/usr/bin/env',*[k+'='+v for k,v in env.items()],'/usr/bin/python3','-B','-m','pytest','-q','-s','-p','no:cacheprovider','--junitxml='+str(folder/'pytest.xml'),str(folder/'src/test_runner.py')]
            command=paired.owned_command(argv,folder,folder/'outer.log',90)
            assert not command['timeout'] and command['launch_error'] is None and not command['remaining_live_group']
            assert {n:sha(folder/n) for n in source_hashes}==source_hashes
            native=[read(p) for p in sorted(journal.glob('*.json'))]
            compiles=[r for r in native if r['name']=='iverilog' and '-o' in r['argv']]
            sims=[r for r in native if r['name']=='vvp' and any(n.endswith('.vvp') for n in r['source_input_sha256'])]
            assert len(compiles)==len(sims)==case['expected_pytest_tests']
            assert all(r['returncode']==0 for r in compiles)
            suites=[]
            for sim in sims:
                assert len(sim['xmls'])==1
                assert sim['xmls'][0]['mtime_ns']>=sim['started_ns']
                assert sim['xmls'][0]['mtime_ns']!=sim['xmls'][0]['before_mtime_ns']
                xml=ET.parse(journal/sim['xmls'][0]['path']);cases=xml.findall('.//testcase');assert len(cases)==1
                assert not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
                failures=sum(c.find('failure') is not None for c in cases)
                assert sim['returncode'] in ([0,1] if failures else [0])
                suites.append(dict(tests=1,failures=failures,sim_time_ns=float(cases[0].attrib['sim_time_ns'])))
            pytest_cases=ET.parse(folder/'pytest.xml').findall('.//testcase')
            assert len(pytest_cases)==case['expected_pytest_tests']
            assert not any(c.find('error') is not None or c.find('skipped') is not None for c in pytest_cases)
            failures=sum(r['failures'] for r in suites);assert failures==sum(c.find('failure') is not None for c in pytest_cases)
            passed=failures==0 and command['returncode']==0;failed=failures==len(suites) and command['returncode']!=0
            assert passed or failed,'mixed native/pytest outcome; keep as execution failure'
            if control['label']=='positive':assert passed,'Positive specification control rejected'
            if control['label']=='failure_propagation':
                assert failed and all('OWN_NATURAL_FAILURE_PROPAGATION' in (journal/s['stdout']['path']).read_text(encoding='utf-8',errors='replace') for s in sims)
            entry=dict(record_id=case['record_id'],label=label,control_intent=control['intent'],outer_argv=argv,outer_command=command,
                source_manifest_sha256=sha(folder/'SOURCE_MANIFEST.json'),actual_compiles=len(compiles),actual_simulations=len(sims),
                original_harness=label!='failure_propagation',passed=passed,failed=failed,false_acceptance=control['intent']=='wrong' and passed,
                suites=suites)
            result['rows'].append(entry);save(out/'summary.json',result)
        dependencies(spec)
        for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
        eligibility={}
        for name in spec['record_ids']:
            entries=[r for r in result['rows'] if r['record_id']==name]
            eligibility[name]=all(r['failed'] if r['control_intent'] in ('wrong','sentinel') else r['passed'] for r in entries)
        result.update(complete=True,passed=True,actual_compile=sum(r['actual_compiles'] for r in result['rows']),
            actual_sim=sum(r['actual_simulations'] for r in result['rows']),natural_original_harness_calibration=eligibility,
            false_acceptances=[dict(record_id=r['record_id'],label=r['label']) for r in result['rows'] if r['false_acceptance']],
            source_unchanged=True,dependencies_unchanged=True)
        assert result['actual_compile']==result['actual_sim']==50
        return 0
    except BaseException as e:
        result['error']=type(e).__name__+': '+str(e);raise
    finally:
        result['elapsed_s']=time.monotonic()-tick;save(out/'summary.json',result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True);p.add_argument('--resource-check',type=Path,required=True)
    raise SystemExit(main(p.parse_args()))
