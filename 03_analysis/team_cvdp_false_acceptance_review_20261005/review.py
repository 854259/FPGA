"""Read original archives and reconstruct counts/harness; execute no archived code."""
import ast,hashlib,io,json,re,sys,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
R=Path(__file__).resolve().parent
ARCHIVE_SHA='296359d8abfec37ea8f545f8630ca564cbd28964975ce9ab62e877e448b9e4bf'
S5_SHA='17b28d710dbe42bc41c4648c222dc195ab7e199bc99b92fb4a27fa402076997e'
def digest(b):return hashlib.sha256(b).hexdigest()
def read(z,n):return json.loads(z.read(n))
def review(archive,s5):
    assert digest(archive.read_bytes())==ARCHIVE_SHA and digest(s5.read_bytes())==S5_SHA
    with zipfile.ZipFile(archive) as z,zipfile.ZipFile(s5) as prior:
        names=z.namelist();manifest=read(z,'EVIDENCE_MANIFEST.json')
        assert manifest['schema']=='S7_private_archive_v1'
        hashes=manifest['files'];assert len(names)==len(set(names)) and set(names)==set(hashes)|{'EVIDENCE_MANIFEST.json'}
        for n,h in hashes.items():
            assert not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n
            assert digest(z.read(n))==h,n
        plan=read(z,'PLAN.json');freeze=read(z,'PRIVATE_FREEZE.json');summary=read(z,'results/summary.json')
        ticket=read(z,'FIFO_TICKET.json');guard=read(z,'guard/status.json');resource=read(z,'guard/resource_check.json')
        assert digest(z.read('PRIVATE_FREEZE.json'))==plan['private_freeze_sha256']==summary['private_freeze_sha256']=='710a97e43c19600c4793659897b7d60d834dc940d025d6ed414d415120c74651'
        source='source/03_analysis/rtllm_contract_audit_20261002/cvdp_false_acceptance_20261005.py'
        assert digest(z.read(source))==plan['driver_sha256']=='a120da36f5228fff08c393a675830e81631bdae07b8eb6cf1c67c852ba535cc5'
        driver=ast.parse(z.read(source).decode()) # Parse only; never execute/import.
        assert digest(z.read('SOURCE_TRANSFER.zip'))==plan['source_zip_sha256']=='dc3b313826bb5099c992bae2c31fb8da14eec02a48f588ace9f74af17510b456'
        with zipfile.ZipFile(io.BytesIO(z.read('SOURCE_TRANSFER.zip'))) as src:
            for n in src.namelist():
                assert not Path(n).is_absolute() and '..' not in Path(n).parts
                if n.endswith('/'):continue
                assert z.read('source/'+n)==src.read(n)
        commit=z.read('source/DELIVERY_COMMIT').decode().strip()
        assert commit==plan['source_commit']==summary['source_commit']=='fe234c9c8d6b7ab3cc710b68e2151b831c002ef9'
        data=prior.read('inputs/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl')
        assert digest(data)==freeze['data_sha256']=='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
        selected=[json.loads(line) for line in data.decode().splitlines() if json.loads(line)['id']==freeze['record_id']]
        assert len(selected)==1;row=selected[0]
        assert digest(json.dumps(row,sort_keys=True).encode())==freeze['record_sha256']=='c44cc5494c80f09613ccb26418af91a623a7c893248f17a2398747cac35de996'
        original=row['harness']['files']
        assert {n:digest(text.encode()) for n,text in original.items()}==freeze['harness_sha256']
        controls_manifest=read(z,'results/CONTROL_MANIFEST.json')
        assert [c['label'] for c in freeze['controls']]==['failure_propagation','constant_zero','constant_one']
        assert freeze['model_requests_max']==plan['model_max']==summary['model_calls']==0
        assert freeze['compiles_max']==freeze['simulations_max']==plan['compile_max']==plan['sim_max']==summary['actual_compile']==summary['actual_sim']==3
        assert summary['complete'] and summary['error'] is None and summary['immutable_inputs_verified']
        assert summary['independent_tasks_admitted']==0 and not summary['full_batch_complete']
        observed=[]
        for control,entry in zip(freeze['controls'],summary['controls']):
            label=control['label'];assert entry['label']==label
            contents=dict(original)
            if control['test_override'] is not None:
                assert label=='failure_propagation'
                # Exact single appended assertion, inserted before next helper.
                original_test=original[freeze['test_path']]
                needle='    await apply_input_sequence(dut, input_seq)\n\nasync def reset_dut'
                assert original_test.count(needle)==1
                assert control['test_override']==original_test.replace(needle,'    await apply_input_sequence(dut, input_seq)\n    raise AssertionError("S7_FAILURE_PROPAGATION")\n\nasync def reset_dut')
                contents[freeze['test_path']]=control['test_override']
            contents[freeze['rtl_path']]=control['rtl']
            expected_hashes={n:digest(text.encode()) for n,text in contents.items()}
            assert controls_manifest[label]==expected_hashes
            for n,text in contents.items():assert z.read('results/'+label+'/'+n)==text.encode(),n
            # Only the declared constant-output control differs; no implementation is substituted.
            bit='1' if label=='constant_one' else '0'
            expected=("module convolutional_encoder(input wire clk, input wire rst, input wire data_in, output wire encoded_bit1, output wire encoded_bit2);\n"
                      +f"assign encoded_bit1 = 1'b{bit};\nassign encoded_bit2 = 1'b{bit};\nendmodule\n")
            assert control['rtl']==expected
            command=entry['command'];log=z.read('results/'+label+'.log')
            assert digest(log)==command['log_sha256'] and len(log)==command['log_bytes']
            assert not command['timeout'] and command['launch_error'] is None and not command['remaining_live_group']
            assert command['returncode']==(1 if label=='failure_propagation' else 0)
            assert command['log'].endswith('/results/'+label+'.log')
            xml=z.read('results/'+label+'/sim_build/test_runner.result.xml');tree=ET.fromstring(xml)
            cases=tree.findall('.//testcase');assert len(cases)==1
            failures=sum(c.find('failure') is not None for c in cases)
            assert failures==(1 if label=='failure_propagation' else 0)
            assert all(c.find('error') is None and c.find('skipped') is None for c in cases)
            assert float(cases[0].attrib['sim_time_ns'])==330.0
            seed=tree.find('.//property');assert seed.attrib=={'name':'random_seed','value':'20261005'}
            suite=dict(path='sim_build/test_runner.result.xml',tests=1,failures=failures,errors=0,skipped=0)
            assert entry['suites']==[suite] and entry['tests']==1 and entry['failures']==failures
            text=log.decode();assert 'Running on Icarus Verilog' in text and 'Initialized cocotb v2.0.1' in text
            assert 'SIM TIME' in text and ('TESTS=1 PASS='+str(1-failures)+' FAIL='+str(failures)+' SKIP=0') in text
            assert 'supplied seed 20261005' in text
            if label=='failure_propagation':
                assert cases[0].find('failure').attrib['error_msg']=='S7_FAILURE_PROPAGATION'
                assert 'S7_FAILURE_PROPAGATION' in text and entry['sentinel_observed'] and entry['simulation_failed']
            else:
                samples=re.findall(r'data_in=([01]), encoded_bit1=([01]), encoded_bit2=([01])',text)
                assert len(samples)==27 and all(a==b==bit for _,a,b in samples)
                assert {x[0] for x in samples}=={'0','1'}
                assert entry['harness_original'] and entry['known_wrong_accepted'] and entry['simulation_passed']
            artifact='results/'+label+'/sim_build/sim.vvp'
            assert entry['compiled_artifacts']==['sim_build/sim.vvp'] and len(z.read(artifact))>1000
            assert z.read(artifact).startswith(b'#!')
            outer=ET.fromstring(z.read('results/'+label+'/pytest.xml'))
            pcases=outer.findall('.//testcase');assert len(pcases)==1
            assert sum(c.find('failure') is not None for c in pcases)==failures
            observed.append(dict(label=label,tests=1,failures=failures,returncode=command['returncode'],
                sim_time_ns=330.0,original_harness=entry['harness_original'],
                log_sha256=digest(log),compiled_blob_sha256=digest(z.read(artifact)),
                known_wrong_accepted=entry.get('known_wrong_accepted',False)))
        original_tree=ast.parse(original[freeze['test_path']])
        assert sum(isinstance(n,ast.Assert) for n in ast.walk(original_tree))==0
        assert sum(isinstance(n,ast.Raise) for n in ast.walk(original_tree))==0
        assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert') for n in ast.walk(original_tree))
        assert summary['false_acceptances']==2 and summary['failure_propagation_verified']
        assert guard['complete'] and guard['passed'] and guard['model_unchanged'] and guard['protected_files_unchanged']
        assert guard['stage_rc']==0 and guard['own_slot_released'] and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
        assert ticket['ticket']==43 and ticket['state']=='completed'
        return dict(schema='cvdp_S7_original_evidence_readonly_review_v1',evidence_archive_valid=True,
            archive_sha256=ARCHIVE_SHA,manifest_files=len(hashes),source_commit=commit,
            driver_sha256=plan['driver_sha256'],private_freeze_sha256=plan['private_freeze_sha256'],
            dataset_sha256=freeze['data_sha256'],record_id=freeze['record_id'],
            record_sha256=freeze['record_sha256'],controls=observed,record_excluded_from_independent_validation=True,
            false_acceptances=2,original_harness_asserts=0,original_harness_raises=0,
            review_model_calls=0,review_eda_calls=0,independent_tasks_admitted=0,adoption=False,
            limits=['Only this record and original harness excluded; no assertion that every CVDP test is invalid.',
                'Original source, dataset, controls, harness bytes, timed cocotb XML/logs and compiled artifacts bound. No archived Python/test/driver code executed by review.',
                'Three recorded build/test executions supported by exact driver, runner, artifacts and timed logs; complete per-native-command argv/return-code receipts are absent, so no claim of independently verified compiler command sequence.',
                'Installed Python/toolchain files outside archive are bound by historical driver/freeze/logs, not independently rehashed or reexecuted here.',
                'Historical guard/model/protected/cleanup observations bound to original records, not fresh hardware/offline32GB certification.',
                'Failure-propagation control deliberately adds one assertion only; never replace original dataset harness or count it as solver quality.'])

if __name__=='__main__':
    result=review(R.parent/'fsm_feedback_pilot_20261005/raw_evidence/team43_evidence.zip',
                  R.parent/'team_cvdp_interface_review_20261005/raw_evidence/S5_EVIDENCE.zip')
    result['reviewer_sha256']=digest(Path(__file__).read_bytes())
    (R/'RESULTS.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({k:result[k] for k in ['evidence_archive_valid','manifest_files','false_acceptances','record_excluded_from_independent_validation','reviewer_sha256','review_model_calls','review_eda_calls']}))
