"""Read original ZIP/XML/native receipts without executing peer stages or auditors."""
from pathlib import Path
import hashlib, importlib.util, json, zipfile, ast
import xml.etree.ElementTree as ET
R=Path(__file__).resolve().parent
OWNER=R.parent/'natural_harness_calibration_20261005'
RECORD='cvdp_copilot_gray_to_binary_0001'
def sha(data):return hashlib.sha256(data).hexdigest()
def checked_archive(path,expected):
    assert sha(path.read_bytes())==expected
    z=zipfile.ZipFile(path);manifest=json.loads(z.read('ARCHIVE_MANIFEST.json'))
    assert len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(manifest['files'])|{'ARCHIVE_MANIFEST.json'}
    for n,h in manifest['files'].items():
        assert not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n and sha(z.read(n))==h,n
    return z,manifest
def review():
    raw=R/'raw_evidence';metadata=json.loads((raw/'ORIGINAL_METADATA.json').read_bytes())
    old,old_manifest=checked_archive(OWNER/'raw_evidence/terminal_v1.zip','b2cee6bfd50e1b12cfd78246c767880b1f11ddd09324d3ca717cc322fe9f9acf')
    z,manifest=checked_archive(raw/'RAW_EVIDENCE.zip','65bc05bf81cbd77c95610487dfdecb6310b4ea6f94f4e158f2eacec67122c9a9')
    def read(n):return json.loads(z.read(n))
    spec=read('run/RUN_SPEC.json');spec_sha=sha(z.read('run/RUN_SPEC.json'))
    assert spec_sha=='5fe49dd3f3bb03ebb92f19fa785b5515ed11d2e6dc1a48f7a906d28519a5e56f'==manifest['run_spec_sha256']
    for n,h in spec['source_hashes'].items():assert sha(z.read('run/'+n))==h,n
    for n,h in spec['dependency_hashes'].items():assert sha(z.read('dependencies/'+n))==h,n
    for n in ['tool_journal.py','collect.py','guard_wrapper.py','INPUT_MANIFEST.json','raw_evidence/DEPENDENCY_BINDINGS.json','raw_evidence/ORIGINAL_DATASET.jsonl']:
        assert z.read('run/'+n)==old.read('run/'+n),n
    own_audit=OWNER/'audit.py';assert sha(own_audit.read_bytes())=='e3992c2791b53dea5ec4b3391e7792c9c2dd7c5f4c71f220f81740bc4379359d'
    loader=importlib.util.spec_from_file_location('owner_original_harness_auditor',own_audit);m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m)
    original_result=m.audit(OWNER/'raw_evidence/terminal_v1.zip','b423bb37761744a33bc5fe91d3ae0d847dc06d29862afe2ab090059c97154a68')
    assert original_result==json.loads((OWNER/'terminal_audit_v1/RESULTS.json').read_bytes())
    peer59=metadata['metadata']['59']['documents']['results/RESULTS.json']['content'];assert peer59==original_result
    old_cases=json.loads(old.read('run/raw_evidence/CONTROLS.json'))['cases']
    case=next(c for c in old_cases if c['record_id']==RECORD)
    assert read('run/raw_evidence/CONTROLS.json')=={'cases':[case]} and len(case['controls'])==6
    data=z.read('run/raw_evidence/ORIGINAL_DATASET.jsonl');assert sha(data)==spec['dataset_sha256']
    dataset={r['id']:r for r in map(json.loads,data.decode().splitlines())};original=dataset[RECORD]
    assert sha(json.dumps(original,sort_keys=True).encode())==case['record_sha256']
    assert {n:sha(s.encode()) for n,s in original['harness']['files'].items()}==case['harness_sha256']
    text=original['harness']['files'][case['test_path']];line='        assert dut.valid.value == 1, "VALID_MUST_BE_HIGH"\n'
    assert text.count('        # Assertions\n')==1 and 'Assert the validity signal' in original['input']['prompt']
    corrected=text.replace('        # Assertions\n','        # Assertions\n'+line)
    assert z.read('run/corrected_test.py')==corrected.encode() and sha(text.encode())==spec['original_test_sha256'] and sha(corrected.encode())==spec['corrected_test_sha256']
    tree=ast.parse(text);attributes=sorted({n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='dut'})
    assert 'valid' not in attributes
    stmt=next(n for n in ast.walk(ast.parse(corrected)) if isinstance(n,ast.Assert) and isinstance(n.msg,ast.Constant) and n.msg.value=='VALID_MUST_BE_HIGH')
    assert isinstance(stmt.test,ast.Compare) and ast.unparse(stmt.test)=='dut.valid.value == 1'
    summary=read('run/results/summary.json');guard=read('run/guard/status.json');resource=read('run/guard/resource_check.json')
    assert summary['run_spec_sha256']==spec_sha and summary['complete'] and summary['passed'] and summary['error'] is None
    assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
    assert guard['stage_rc']==0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
    inputs=read('run/INPUT_MANIFEST.json');assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
    for name in ['iverilog','vvp']:assert sha(z.read('run/tools/bin/'+name))==spec['source_hashes']['tool_journal.py']
    assert [(r['record_id'],r['label']) for r in summary['rows']]==[(RECORD,v['label']) for v in case['controls']]
    parsed=[];configs=[];total=0
    for control,row in zip(case['controls'],summary['rows']):
        base='run/results/'+RECORD+'/'+control['label']+'/'
        contents=dict(original['harness']['files']);contents[case['rtl_path']]=control['rtl'];contents[case['test_path']]=corrected
        if control['label']=='failure_propagation':contents[case['test_path']]+='\n    raise AssertionError("OWN_NATURAL_FAILURE_PROPAGATION")\n'
        hashes={n:sha(s.encode()) for n,s in contents.items()}
        assert read(base+'SOURCE_MANIFEST.json')==hashes and sha(z.read(base+'SOURCE_MANIFEST.json'))==row['source_manifest_sha256']
        for n,s in contents.items():assert z.read(base+n)==s.encode(),n
        command=row['outer_command'];log=z.read(base+'outer.log')
        assert sha(log)==command['log_sha256'] and len(log)==command['log_bytes']
        assert not command['timeout'] and not command['launch_error'] and not command['remaining_live_group']
        assert row['outer_argv'][-2:]==['--junitxml='+spec['cloud_root']+'/results/'+RECORD+'/'+control['label']+'/pytest.xml',spec['cloud_root']+'/results/'+RECORD+'/'+control['label']+'/src/test_runner.py']
        native=[read(n) for n in sorted(manifest['files']) if n.startswith(base+'native_receipts/') and n.endswith('.json')]
        compiles=[];sims=[];blob_hashes=set();suites=[];parameters=[]
        for record in native:
            binding=spec['real_tools'][record['name']]
            assert record['argv'][0]==binding['path'] and record['executable_sha256']==binding['sha256']
            assert Path(record['cwd']).is_relative_to(Path(spec['cloud_root'])/'results'/RECORD/control['label'])
            journal=base+'native_receipts/'
            for key in ['stdout','stderr']:
                b=z.read(journal+record[key]['path']);assert sha(b)==record[key]['sha256'] and len(b)==record[key]['bytes']
            for p,h in record['source_input_sha256'].items():
                if p.endswith(('.sv','.v')):assert h==hashes[case['rtl_path']],p
            if record['name']=='iverilog' and '-o' in record['argv']:
                assert record['returncode']==0 and record['source_input_sha256'][spec['cloud_root']+'/results/'+RECORD+'/'+control['label']+'/'+case['rtl_path']]==hashes[case['rtl_path']]
                artifact=record['artifacts']['compiled'];b=z.read(journal+artifact['path']);assert sha(b)==artifact['sha256'] and b.startswith(b'#!')
                blob_hashes.add(artifact['sha256']);compiles.append(record)
                parameters.append([a for a in record['argv'] if a.startswith('-P')])
            if record['name']=='vvp' and any(p.endswith('.vvp') for p in record['source_input_sha256']):
                assert all(h in blob_hashes for p,h in record['source_input_sha256'].items() if p.endswith('.vvp')) and len(record['xmls'])==1
                x=record['xmls'][0];assert x['mtime_ns']>=record['started_ns'] and x['mtime_ns']!=x['before_mtime_ns']
                xml=z.read(journal+x['path']);assert sha(xml)==x['sha256'];cases=ET.fromstring(xml).findall('.//testcase');assert len(cases)==1
                assert not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
                failures=sum(c.find('failure') is not None for c in cases);assert record['returncode'] in ([0,1] if failures else [0])
                if control['label']=='failure_propagation':assert failures==1 and cases[0].find('failure').attrib['error_msg']=='OWN_NATURAL_FAILURE_PROPAGATION'
                if control['label']=='valid_zero':assert failures==1 and 'VALID_MUST_BE_HIGH' in cases[0].find('failure').attrib['error_msg']
                suites.append(dict(tests=1,failures=failures,sim_time_ns=float(cases[0].attrib['sim_time_ns'])));sims.append(record)
        assert len(compiles)==len(sims)==case['expected_pytest_tests']==row['actual_compiles']==row['actual_simulations']==5
        assert suites==row['suites'];pcases=ET.fromstring(z.read(base+'pytest.xml')).findall('.//testcase');assert len(pcases)==5
        assert not any(c.find('error') is not None or c.find('skipped') is not None for c in pcases)
        failures=sum(c.find('failure') is not None for c in pcases);assert failures==sum(s['failures'] for s in suites)
        passed=failures==0 and command['returncode']==0;failed=failures==5 and command['returncode']!=0
        assert passed if control['intent']=='correct' else failed
        assert row['passed']==passed and row['failed']==failed and not row['original_harness'] and not row['false_acceptance']
        parsed.append(dict(record_id=RECORD,label=control['label'],passed=passed,failed=failed,native_trials=5,original_harness=False,false_acceptance=False))
        if not configs:configs=parameters
        else:assert configs==parameters
        total+=5
    assert total==30==summary['actual_compile']==summary['actual_sim'] and summary['corrected_harness_calibration']=={RECORD:True}
    assert summary['model_calls']==spec['model_requests_max']==0 and not summary['eligible_for_independent_models'] and not summary['adoption'] and not summary['independent_model_tasks']
    with zipfile.ZipFile(raw/'POSTFLIGHT.zip') as post:
        assert sha((raw/'POSTFLIGHT.zip').read_bytes())=='08bca1a51d912f8537489b9a5a258602a03384f54feb1da92b3e5fd2174d5595'
        assert len(post.namelist())==len(set(post.namelist()))
        p=json.loads(post.read('postflight/RESULTS.json'))
        for key,value in [('evidence_valid',True),('archive_sha256',sha((raw/'RAW_EVIDENCE.zip').read_bytes())),('spec_sha256',spec_sha),('manifest_files',len(manifest['files'])),('native_compile_commands',30),('native_simulation_commands',30),('controls',parsed),('corrected_harness_calibration',{RECORD:True})]:assert p[key]==value,key
        assert p==metadata['metadata']['60']['documents']['postflight/RESULTS.json']['content']
    old.close();z.close()
    return dict(schema='owner_natural_valid_peer_readonly_review_v1',evidence_valid=True,review_sha256=sha(Path(__file__).read_bytes()),archive_sha256=sha((raw/'RAW_EVIDENCE.zip').read_bytes()),spec_sha256=spec_sha,peer_auditor_sha256=spec['source_hashes']['audit.py'],manifest_files=len(manifest['files']),original_owner_manifest_files=len(old_manifest['files']),original_owner_result_equal_peer59=True,original_test_sha256=sha(text.encode()),corrected_test_sha256=sha(corrected.encode()),added_assertions=1,original_harness_admitted=False,original_harness_exclusion_preserved=True,corrected_evaluation_only_controls=parsed,native_compile_commands=30,native_simulation_commands=30,parameter_flags_per_control=configs,review_model_calls=0,review_eda_calls=0,peer_model_calls=0,independent_model_tasks=0,eligible_for_independent_models=False,official_score=False,adoption=False,inherited_metadata={'identity':spec['identity'],'frozen_at_utc':spec['frozen_at_utc'],'controls_upper_bound':spec['controls'],'compile_upper_bound':spec['compiles_max']},limits=['A single assertion improves this isolated research test; original dataset/test bytes and exclusion remain unchanged.','Six controls each five runs cover four distinct configurations, including a repeated default; no exhaustive specification or new independent solver evidence.','Peer spec retains owner identity/time and 16/50 conservative bounds; exact current root/spec SHA, actual six controls and 30 compile/simulation receipts disambiguate the new run.','Archive external tool/dependency observations are historical, not fresh offline/R9700/32GB certification.','Peer57 is an original FSM report/diagnosis read-only cross-reference, not another model optimization experiment.'])
if __name__=='__main__':
    result=review();(R/'RESULTS.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps({k:result[k] for k in ['evidence_valid','manifest_files','native_compile_commands','original_harness_admitted','original_harness_exclusion_preserved','review_model_calls','review_eda_calls']}))
