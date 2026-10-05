"""Read-only original edge/control receipt audit; never execute archived code/tools."""
from pathlib import Path
import argparse,hashlib,json,zipfile
import xml.etree.ElementTree as ET
def sha(b):return hashlib.sha256(b).hexdigest()
def audit(archive,spec_sha):
    with zipfile.ZipFile(archive) as z:
        def read(n):return json.loads(z.read(n))
        manifest=read('ARCHIVE_MANIFEST.json');assert len(z.namelist())==len(set(z.namelist()))
        assert set(z.namelist())==set(manifest['files'])|{'ARCHIVE_MANIFEST.json'}
        for n,h in manifest['files'].items():
            assert not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n and sha(z.read(n))==h,n
        spec=read('run/RUN_SPEC.json');assert sha(z.read('run/RUN_SPEC.json'))==spec_sha==manifest['run_spec_sha256']
        assert sha(Path(__file__).read_bytes())==spec['source_hashes']['audit.py']
        for n,h in spec['source_hashes'].items():assert sha(z.read('run/'+n))==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(z.read('dependencies/'+n))==h,n
        summary=read('run/results/summary.json');guard=read('run/guard/status.json');resource=read('run/guard/resource_check.json')
        assert summary['run_spec_sha256']==spec_sha and summary['complete'] and summary['passed'] and summary['error'] is None
        assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
        assert guard['stage_rc']==0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert resource['model_identity']==spec['model_identity']
        assert resource['model_pid']==spec['model_identity']['pid'] and resource['model_starttime']==spec['model_identity']['starttime']
        assert resource['slot_owner']==spec['slot_owner'] and resource['slot_lock_path']==spec['slot_lock_path']
        assert resource['llm_base_url']==spec['llm_base_url'] and resource['model_name']==spec['model_name']
        inputs=read('run/INPUT_MANIFEST.json');assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
        for name in ['iverilog','vvp']:assert sha(z.read('run/tools/bin/'+name))==spec['source_hashes']['tool_journal.py']
        private=read('run/raw_evidence/CONTROLS.json');data=z.read('run/raw_evidence/ORIGINAL_DATASET.jsonl');assert sha(data)==spec['dataset_sha256']
        assert private['evaluation_only'] and not private['reference_answer_available']
        assert len(private['cases'])==1 and [c['record_id'] for c in private['cases']]==spec['record_ids']
        assert private['planned_controls']==private['planned_compile_commands']==private['planned_simulation_commands']==7
        assert spec['controls']==spec['compiles_max']==spec['simulations_max']==7
        assert private['dataset']['sha256']==sha(data) and private['dataset']['bytes']==len(data)
        dataset={r['id']:r for r in (json.loads(line) for line in data.decode().splitlines())}
        expected_order=[(c['record_id'],v['label']) for c in private['cases'] for v in c['controls']]
        assert [(r['record_id'],r['label']) for r in summary['rows']]==expected_order
        parsed_rows=[];eligible={};total=0
        for case in private['cases']:
            original=dataset[case['record_id']];assert sha(json.dumps(original,sort_keys=True).encode())==case['record_sha256']
            assert {n:sha(s.encode()) for n,s in original['harness']['files'].items()}==case['harness_sha256']
            assert original['input']['context']=={} and original['output']=={'response':'','context':{case['rtl_path']:''}}
            for key,obj in [('input_sha256',original['input']),('input_context_sha256',original['input']['context']),('output_sha256',original['output']),('output_context_sha256',original['output']['context'])]:
                assert sha(json.dumps(obj,sort_keys=True).encode())==case[key]
            assert sha(original['input']['prompt'].encode())==case['prompt_sha256']
            assert sha(original['harness']['files'][case['test_path']].encode())==case['test_sha256']
            assert sha(original['harness']['files'][case['runner_path']].encode())==case['runner_sha256']
            matching_lines=[line for line in data.decode().splitlines() if json.loads(line)['id']==case['record_id']]
            assert len(matching_lines)==1 and sha(matching_lines[0].encode())==case['original_json_line_sha256']
            assert case['expected_pytest_tests']==case['expected_cocotb_tests_per_simulation']==1
            assert case['control_order']==[c['label'] for c in case['controls']] and len(case['controls'])==7
            outcomes=[]
            for control in case['controls']:
                base='run/results/'+case['record_id']+'/'+control['label']+'/'
                row=next(r for r in summary['rows'] if r['record_id']==case['record_id'] and r['label']==control['label'])
                assert sha(control['rtl'].encode())==control['rtl_sha256']
                contents=dict(original['harness']['files']);contents[case['rtl_path']]=control['rtl']
                if control['label']=='failure_propagation':contents[case['test_path']]+='\n    raise AssertionError("OWN_NATURAL_FAILURE_PROPAGATION")\n'
                hashes={n:sha(s.encode()) for n,s in contents.items()}
                assert read(base+'SOURCE_MANIFEST.json')==hashes and sha(z.read(base+'SOURCE_MANIFEST.json'))==row['source_manifest_sha256']
                for n,s in contents.items():assert z.read(base+n)==s.encode(),n
                command=row['outer_command'];log=z.read(base+'outer.log')
                assert sha(log)==command['log_sha256'] and len(log)==command['log_bytes']
                assert not command['timeout'] and not command['launch_error'] and not command['remaining_live_group']
                folder=spec['cloud_root']+'/results/'+case['record_id']+'/'+control['label']
                env=dict(PATH=spec['cloud_root']+'/tools/bin:'+spec['toolchain']['prefix']+'/bin:'+spec['inherited_path'],
                    PYTHONPATH=spec['python_site']['path']+':'+folder+'/src',
                    PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',PYTHONHASHSEED='0',COCOTB_RANDOM_SEED='20261005',
                    SIM='icarus',TOPLEVEL_LANG='verilog',TOPLEVEL=case['top'],MODULE=case['module'],
                    VERILOG_SOURCES=folder+'/'+case['rtl_path'],OWN_CALIBRATION_ROOT=spec['cloud_root'],OWN_NATIVE_JOURNAL=folder+'/native_receipts')
                assert row['outer_argv']==['/usr/bin/env','-i',*[k+'='+v for k,v in env.items()],'/usr/bin/python3','-B','-m','pytest','-q','-s','-p','no:cacheprovider','--junitxml='+folder+'/pytest.xml',folder+'/src/test_runner.py']
                assert command['log']==folder+'/outer.log'
                native=[]
                for n in sorted(manifest['files']):
                    if n.startswith(base+'native_receipts/') and n.endswith('.json'):
                        native.append(read(n))
                assert len(native)==2
                compiled=folder+'/sim_build/sim.vvp';cmdfile=folder+'/sim_build/cmds.f'
                assert z.read(base+'sim_build/cmds.f')==b'+timescale+1ns/1ps\n'
                compiles=[];sims=[];blob_hashes=set();suites=[]
                for record in native:
                    binding=spec['real_tools'][record['name']]
                    assert record['argv'][0]==binding['path'] and record['executable_sha256']==binding['sha256']
                    assert record['cwd']==folder+'/sim_build'
                    journal=base+'native_receipts/'
                    for key in ['stdout','stderr']:
                        b=z.read(journal+record[key]['path']);assert sha(b)==record[key]['sha256'] and len(b)==record[key]['bytes']
                    for p,h in record['source_input_sha256'].items():
                        relative=Path(p).relative_to(Path(folder)).as_posix();assert '..' not in Path(relative).parts
                        assert sha(z.read(base+relative))==h,p
                        if p.endswith(('.sv','.v')):assert h==hashes[case['rtl_path']],p
                    if record['name']=='iverilog' and '-o' in record['argv']:
                        assert record['argv']==[spec['real_tools']['iverilog']['path'],'-o',compiled,'-s',case['top'],'-g2012','-f',cmdfile,folder+'/'+case['rtl_path']]
                        assert set(record['source_input_sha256'])=={cmdfile,folder+'/'+case['rtl_path']}
                        assert record['returncode']==0 and record['source_input_sha256'][spec['cloud_root']+'/results/'+case['record_id']+'/'+control['label']+'/'+case['rtl_path']]==hashes[case['rtl_path']]
                        artifact=record['artifacts']['compiled'];b=z.read(journal+artifact['path']);assert sha(b)==artifact['sha256'] and b.startswith(b'#!')
                        assert artifact['original_path']==compiled and sha(z.read(base+'sim_build/sim.vvp'))==artifact['sha256']
                        blob_hashes.add(artifact['sha256']);compiles.append(record)
                    if record['name']=='vvp' and any(p.endswith('.vvp') for p in record['source_input_sha256']):
                        assert record['argv']==[spec['real_tools']['vvp']['path'],'-M',spec['python_site']['path']+'/cocotb/libs','-m','libcocotbvpi_icarus',compiled,'-fst']
                        assert set(record['source_input_sha256'])=={compiled}
                        assert all(h in blob_hashes for p,h in record['source_input_sha256'].items() if p.endswith('.vvp'))
                        assert len(record['xmls'])==1
                        x=record['xmls'][0];assert x['mtime_ns']>=record['started_ns'] and x['mtime_ns']!=x['before_mtime_ns']
                        xml=z.read(journal+x['path']);assert sha(xml)==x['sha256'];tree=ET.fromstring(xml);cases=tree.findall('.//testcase');assert len(cases)==1
                        assert cases[0].attrib['name']==spec['native_test_name'] and cases[0].attrib['classname']==case['module'] and cases[0].attrib['file']==folder+'/'+case['test_path']
                        assert not any(c.find('error') is not None or c.find('skipped') is not None for c in cases)
                        failures=sum(c.find('failure') is not None for c in cases);assert record['returncode'] in ([0,1] if failures else [0])
                        if control['label']=='failure_propagation':assert failures==1 and cases[0].find('failure').attrib['error_type']=='AssertionError' and cases[0].find('failure').attrib['error_msg']=='OWN_NATURAL_FAILURE_PROPAGATION'
                        suites.append(dict(tests=1,failures=failures,sim_time_ns=float(cases[0].attrib['sim_time_ns'])));sims.append(record)
                assert len(compiles)==len(sims)==case['expected_pytest_tests']==row['actual_compiles']==row['actual_simulations']
                assert suites==row['suites']
                pcases=ET.fromstring(z.read(base+'pytest.xml')).findall('.//testcase');assert len(pcases)==len(sims)
                assert pcases[0].attrib['classname']=='src.test_runner' and pcases[0].attrib['name']=='test_runner'
                assert not any(c.find('error') is not None or c.find('skipped') is not None for c in pcases)
                failures=sum(c.find('failure') is not None for c in pcases);assert failures==sum(s['failures'] for s in suites)
                passed=failures==0 and command['returncode']==0;failed=failures==len(sims) and command['returncode']==1
                assert passed or failed
                assert row['control_intent']==control['intent']
                if control['label']=='positive':assert passed
                if control['label']=='failure_propagation':assert failed
                assert row['passed']==passed and row['failed']==failed and row['false_acceptance']==(control['intent']=='wrong' and passed)
                outcomes.append(failed if control['intent'] in ('wrong','sentinel') else passed)
                parsed_rows.append(dict(record_id=case['record_id'],label=control['label'],passed=passed,failed=failed,native_trials=len(sims),original_harness=control['label']!='failure_propagation',false_acceptance=row['false_acceptance']))
                total+=len(sims)
            eligible[case['record_id']]=all(outcomes)
        assert total==7==summary['actual_compile']==summary['actual_sim'] and len(summary['rows'])==7
        assert eligible==summary['natural_original_harness_calibration']
        assert summary['false_acceptances']==[dict(record_id=p['record_id'],label=p['label']) for p in parsed_rows if p['false_acceptance']]
        assert all(p['original_harness']==(p['label']!='failure_propagation') for p in summary['rows'])
        assert summary['model_calls']==spec['model_requests_max']==0 and not summary['eligible_for_independent_models']
        assert summary['independent_model_tasks']==0 and summary['adoption'] is False
        assert summary['source_unchanged'] and summary['dependencies_unchanged']
        return dict(schema='natural_edge_original_harness_readonly_audit_v1',evidence_valid=True,
            archive_sha256=sha(archive.read_bytes()),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__).read_bytes()),
            manifest_files=len(manifest['files']),model_calls=0,audit_model_calls=0,audit_eda_calls=0,
            native_compile_commands=total,native_simulation_commands=total,original_harness_calibration=eligible,
            controls=parsed_rows,false_acceptances=[p for p in parsed_rows if p['false_acceptance']],
            independent_model_tasks=0,eligible_for_independent_models=False,adoption=False,
            limits=['Original public natural prompts exposed only for evaluation calibration; not unseen or training-independence certification.',
                'Known specification controls are evaluation artifacts and never model inputs. This is original-harness discrimination, not solver scores or official Vivado L3.',
                'Original harness checks four pulse values after startup reset and does not assert reset behavior at runtime. reset_ignored is retained; any wrong-control pass excludes this original record/harness. No exhaustive specification proof.',
                'Package/toolchain hash verification at original run and guard checks are historical observations; archive lacks all external installed binaries, no fresh offline32GB certification.',
                'Full156 qualification, faithful ABI/model integration and exposure review remain necessary before natural model comparison.'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--spec-sha',required=True);a=p.parse_args();assert not a.out.exists();r=audit(a.archive,a.spec_sha);a.out.mkdir();(a.out/'RESULTS.json').write_bytes((json.dumps(r,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps({k:r[k] for k in ['evidence_valid','native_compile_commands','original_harness_calibration','false_acceptances']}))
