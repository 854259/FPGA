"""Frozen priority contract calibration. Owned native tools; zero inference."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import priority_contract as prompt_map

ROOT=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--kit',required=True,type=Path);ap.add_argument('--resource-check',required=True,type=Path)
    args=ap.parse_args();spec=json.loads((ROOT/'RUN_SPEC.json').read_text())
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    deps=Path(spec['dependencies_cloud'])
    for n,h in spec['dependency_hashes'].items():assert sha(deps/n)==h
    s=importlib.util.spec_from_file_location('owned_map_calibration',deps/'paired_checkpoint.py');paired=importlib.util.module_from_spec(s);s.loader.exec_module(paired)
    paired.REPO=ROOT;paired.INHERITED_ORACLE=deps/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    out=ROOT/'results';out.mkdir(exist_ok=False)
    started=time.monotonic();report=dict(schema='priority_contract_calibration_v1',complete=False,passed=False,model_calls=0,
        scope='2 known public archived candidates plus 3 constructed controls; no new generation/full score/independent natural task claim',
        run_spec_sha256=sha(ROOT/'RUN_SPEC.json'),cases={},probe_executions=0,synth_executions=0)
    def gate():
        assert time.monotonic()-started<spec['timeout_s']
        assert sha(ROOT/'RUN_SPEC.json')==report['run_spec_sha256']
        for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(deps/n)==h,n
        paired.check_resource(args.resource_check,args.kit)
    try:
        for case in spec['cases']:
            task=case['task'];folder=ROOT/'raw_evidence/inputs'/task
            contract=prompt_map.parse((folder/'prompt.txt').read_bytes().decode('utf-8'))
            assert contract==json.loads((folder/'contract.json').read_text())
            assert prompt_map.render_tb(contract,task)==(folder/'tb.sv').read_text()
            # Prevent simulator-summary spoofing by a DUT. These are calibration
            # inputs, not general RTL parsing; any system task is outside scope.
            names=['positive','constant_zero','constant_max','msb_priority']+(['candidate'] if case['archived_candidate'] else [])
            for n in names:assert not re.search(r'\$[A-Za-z_]',(folder/(n+'.sv')).read_text())
            test=dict(task=task,checks=contract['checks'],tb='raw_evidence/inputs/'+task+'/tb.sv')
            row=dict(group=case['group'],controls={},candidate=None)
            report['cases'][task]=row
            counts=dict(positive=0,
                constant_zero=sum(c['expected']!=0 for c in contract['cases']),
                constant_max=sum(c['expected']!=contract['input_width']-1 for c in contract['cases']),
                msb_priority=sum(c['expected']!=(0 if c['inputs'][contract['input']]==0 else c['inputs'][contract['input']].bit_length()-1) for c in contract['cases']))
            for name in ('positive','constant_zero','constant_max','msb_priority'):
                gate();result=paired.oracle(test,folder/(name+'.sv'),out/'controls'/task/name)
                report['probe_executions']+=1
                assert result['checks']==contract['checks'] and result['status']==('pass' if name=='positive' else 'fail')
                assert result['mismatches']==counts[name]
                if name!='positive':
                    assert result['failure_kind']=='semantic_mismatch'
                    row['controls'][name+'_first']=prompt_map.counterexample((out/'controls'/task/name/'xsim.log').read_text(),contract)
                row['controls'][name]=result
                save(out/'summary.json',report)
            gate();synth=out/'synthesis'/task;synth.mkdir(parents=True)
            (synth/'dut.sv').write_bytes((folder/'positive.sv').read_bytes())
            (synth/'run.tcl').write_text('if {[catch {read_verilog -sv dut.sv; synth_design -top TopModule -part xczu3eg-sbva484-1-e} err]} {puts "PRIORITY_SYNTHESIS_FAIL: $err"; exit 1}\nputs "PRIORITY_SYNTHESIS_PASS"\nexit 0\n')
            result=paired.owned_command([str(Path(os.environ['VIVADO_BIN'])/'vivado'),'-mode','batch','-source','run.tcl','-nolog','-nojournal'],synth,synth/'synth.log',90)
            report['synth_executions']+=1
            assert result['returncode']==0 and not result['timeout'] and not result['remaining_live_group']
            assert 'PRIORITY_SYNTHESIS_PASS' in (synth/'synth.log').read_text()
            row['positive_synthesis']=result
            if case['archived_candidate']:
                gate();result=paired.oracle(test,folder/'candidate.sv',out/'candidates'/task)
                report['probe_executions']+=1
                assert result['status']!='environment_error'
                row['candidate']=result
                if result['failure_kind']=='semantic_mismatch':row['candidate_first']=prompt_map.counterexample((out/'candidates'/task/'xsim.log').read_text(),contract)
            save(out/'summary.json',report)
            print(json.dumps(dict(task=task,controls_valid=True,candidate=row['candidate']['status'] if row['candidate'] else None)),flush=True)
        gate();report.update(complete=True,passed=True,
            natural_hypothesis_matched=all(report['cases'][task]['candidate']['status']==expected
                for task,expected in spec['expected_natural_candidates'].items()))
    except BaseException as e:report['error']=type(e).__name__+': '+str(e)
    finally:
        report['elapsed_s']=time.monotonic()-started;save(out/'summary.json',report)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
