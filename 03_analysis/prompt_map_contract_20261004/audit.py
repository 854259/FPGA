"""Offline binding audit for actual calibration evidence; never runs EDA/model."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def audit(archive,out,spec_sha):
    out=Path(out);assert not out.exists(),'Fresh output required'
    helper=Path(__file__).resolve().parent.parent/'full156_postflight_20261004/audit.py'
    assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('map_archive_verifier',helper)
    with tempfile.TemporaryDirectory(prefix='map-evidence-') as temporary:
        root=Path(temporary);manifest=shared.unpack(archive,root);run=root/'run'
        assert sha(run/'RUN_SPEC.json')==spec_sha==manifest['run_spec_sha256']
        spec=read(run/'RUN_SPEC.json')
        for n,h in spec['source_hashes'].items():assert sha(run/n)==h,n
        for n,h in spec['dependency_hashes'].items():assert sha(root/'dependencies'/n)==h,n
        report=read(run/'results/summary.json');assert report['complete'] and report['passed'] and report['model_calls']==0
        assert report['run_spec_sha256']==spec_sha
        guard=read(root/'guard/status.json')
        for flag in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released']:assert guard[flag] is True
        assert guard['stage_rc']==0 and not guard['model_managed'] and not guard['instance_managed']
        assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert guard['model_idle_after']['processing_slots']==0
        resource=read(root/'guard/resource_check.json');inputs=read(run/'INPUT_MANIFEST.json')
        assert resource['protected']['tasks']==inputs['input_sha256']
        assert resource['protected']['official']==inputs['official_sha256']
        assert resource['model_pid']==2013333 and resource['model_starttime']=='823869819'
        parser=load('map_actual_parser',run/'prompt_map.py')
        # Separate representations: parser regenerates TB; compiled controls and
        # logs are checked against the explicit input/output rows below.
        runner=load('map_summary_parser',root/'dependencies/probe_runner.py')
        runner.TASK_CHECKS={c['task']:c['checks'] for c in spec['cases']}
        summary={};probes=0;synths=0
        def probe(folder,task,solution,tb,contract,record):
            nonlocal probes
            probes+=1
            raw=read(folder/'result.json');adapter=read(folder/'adapter_receipt.json')
            assert all(adapter[k]==v for k,v in raw.items())
            assert adapter==record
            assert adapter['inherited_result_sha256']==sha(folder/'result.json')
            assert adapter['inherited_runner_sha256']==sha(root/'dependencies/probe_runner.py')
            assert adapter['oracle_adapter_sha256']==sha(root/'dependencies/paired_checkpoint.py')
            assert raw['solution_sha256']==sha(solution)==sha(folder/'dut.sv')
            assert raw['tb_sha256']==sha(tb)==sha(folder/'tb.sv')
            assert raw['runner_sha256']==sha(root/'dependencies/probe_runner.py') and raw['inputs_unchanged']
            assert raw['task']==task and raw['checks']==contract['checks']
            assert len(raw['stages'])==3
            for stage,name in zip(raw['stages'],['xvlog','xelab','xsim']):
                assert stage['name']==name and PurePosixPath(stage['argv'][0]).name==name
                assert not stage['timeout'] and not stage['launch_error'] and stage['returncode']==0
                assert not stage['remaining_live_group']
                shared.command(stage,folder/(name+'.log'))
                text=(folder/(name+'.log')).read_text(encoding='utf-8',errors='replace')
                assert not runner.ENVIRONMENT_ERROR.search(text)
            text=(folder/'xsim.log').read_text(encoding='utf-8',errors='replace')
            checks,mismatches=runner._parse_summary(text,task)
            assert raw['checks']==checks and raw['mismatches']==mismatches
            assert raw['status']==('pass' if mismatches==0 else 'fail')
            assert raw['failure_kind']==(None if mismatches==0 else 'semantic_mismatch')
            point=parser.counterexample(text,contract) if mismatches else None
            return dict(status=raw['status'],checks=checks,mismatches=mismatches,first=point)
        for case in spec['cases']:
            task=case['task'];folder=run/'raw_evidence/inputs'/task
            contract=parser.parse((folder/'prompt.txt').read_bytes().decode('utf-8'))
            assert contract==read(folder/'contract.json') and contract['status']=='supported'
            assert parser.render_tb(contract,task)==(folder/'tb.sv').read_text(encoding='utf-8')
            row=report['cases'][task];assert row['group']==case['group']
            expected=dict(positive=0,constant_zero=sum(c['expected']==1 for c in contract['cases']),
                constant_one=sum(c['expected']==0 for c in contract['cases']),inverted=contract['checks'])
            evidence={}
            for name,count in expected.items():
                result=probe(run/'results/controls'/task/name,task,folder/(name+'.sv'),folder/'tb.sv',contract,row['controls'][name])
                assert result['mismatches']==count
                if name!='positive':assert row['controls'][name+'_first']==result['first']
                evidence[name]=result
            synth=run/'results/synthesis'/task;synths+=1
            assert sha(synth/'dut.sv')==sha(folder/'positive.sv')
            sr=row['positive_synthesis'];shared.command(sr,synth/'synth.log')
            assert 'MAP_SYNTHESIS_PASS' in (synth/'synth.log').read_text(encoding='utf-8')
            assert [PurePosixPath(sr['argv'][0]).name,*sr['argv'][1:]]==['vivado','-mode','batch','-source','run.tcl','-nolog','-nojournal']
            candidate=None
            if case['archived_candidate']:
                candidate=probe(run/'results/candidates'/task,task,folder/'candidate.sv',folder/'tb.sv',contract,row['candidate'])
                if candidate['first']:assert row['candidate_first']==candidate['first']
            summary[task]=dict(group=case['group'],controls=evidence,candidate=candidate)
        assert probes==report['probe_executions']==36 and synths==report['synth_executions']==8
        hypothesis=all(summary[t]['candidate']['status']==expected for t,expected in spec['expected_natural_candidates'].items())
        assert report['natural_hypothesis_matched']==hypothesis
        result=dict(schema='prompt_map_offline_audit_v1',evidence_valid=True,controls_valid=True,
            archive_sha256=sha(archive),run_spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),cases=summary,
            natural_hypothesis_matched=hypothesis,probe_executions=probes,synth_executions=synths,
            model_calls=0,audit_eda_calls=0,model_changed=False,deployment_changed=False,new_full_score=False,
            limits=['Known public archived replay plus constructed calibration, not independent natural task generalization',
                'Complete scalar textual maps only; partial/diagram/timing/inversion specs abstain',
                'No model repair or production-path cost measured; next equal-budget generation/repair experiment still required',
                'Controls are evaluation artifacts; no deterministic DUT answer generation in agent'])
    out.mkdir(parents=True);(out/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--spec-sha',required=True)
    a=p.parse_args();r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:r[k] for k in ['evidence_valid','controls_valid','natural_hypothesis_matched','probe_executions','synth_executions']}))
