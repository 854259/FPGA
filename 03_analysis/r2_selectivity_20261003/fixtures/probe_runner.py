"""Validate fixed semantic controls and an offline selector; no model calls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path(os.environ.get('R2_BASE_PROBE_RUNNER', ROOT.parents[1] / 'r2_signedness_20261003/probes/probe_runner.py')).resolve()
BASE_SHA = '954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(selector_path,out):
    selector_path=Path(selector_path).resolve();out=Path(out).resolve()
    manifest=json.loads((ROOT/'manifest.json').read_text())
    if manifest.get('planned_fixture_count') != 12 or len(manifest['cases']) != 12 or len({c['id'] for c in manifest['cases']}) != 12:
        raise ValueError('expected the complete twelve-case fixture set')
    for name,digest in manifest['input_sha256'].items():
        if sha(ROOT/name)!=digest:raise ValueError('fixture changed: '+name)
    if sha(BASE)!=BASE_SHA:raise ValueError('inherited runner changed')
    helper=load('r2b_inherited',BASE);helper.ROOT=ROOT
    helper.TASK_CHECKS={k:v['checks'] for k,v in manifest['families'].items()}
    selector=load('r2b_selector',selector_path)
    paths=[ROOT/name for name in manifest['input_sha256']]+[ROOT/'manifest.json',Path(__file__),selector_path,BASE]
    before={str(p.resolve()):sha(p) for p in paths}
    out.mkdir(parents=True,exist_ok=False)
    report=dict(complete=False,valid=False,controls_valid=False,model_calls=0,
                snapshot_before=before,controls={},cases=[])

    def finish():
        report['snapshot_after']={str(p.resolve()):sha(p) for p in paths}
        report['assets_unchanged']=report['snapshot_after']==before
        report['valid']=report['complete'] and report['controls_valid'] and report['assets_unchanged'] and all(x['passed'] for x in report['cases'])
        helper._write_json(out/'validation.json',report)
        return report

    def one(family,solution,destination):
        if {str(p.resolve()):sha(p) for p in paths}!=before:raise ValueError('assets changed')
        return helper.probe_candidate(family,solution,destination)

    for family in manifest['families']:
        positive=one(family,ROOT/family/'positive.sv',out/'controls'/family/'positive')
        negative=one(family,ROOT/family/'negative.sv',out/'controls'/family/'negative')
        valid=positive['status']=='pass' and negative['status']=='fail' and negative['failure_kind']=='semantic_mismatch'
        report['controls'][family]=dict(positive=positive,negative=negative,valid=valid)
        if not valid:return finish()
    report['controls_valid']=True
    for case in manifest['cases']:
        files=ROOT/'cases'/case['id']
        classification=selector.analyze((files/'prompt.txt').read_text(),(files/'candidate.sv').read_text())
        probe=one(case['family'],files/'candidate.sv',out/'cases'/case['id'])
        wanted=case['expected_decision']
        selected_ok=(classification['decision'] in ('skip','abstain') if wanted=='no_review' else classification['decision']==wanted)
        semantic_ok=probe['status']==case['expected_probe'] and (probe['status']=='pass' or probe['failure_kind']=='semantic_mismatch')
        report['cases'].append(dict(case=case,classification=classification,probe=probe,passed=selected_ok and semantic_ok))
        if probe['status']=='environment_error':return finish()
    report['complete']=True
    return finish()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selector',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();r=run(a.selector,a.out)
    print(json.dumps(dict(complete=r['complete'],valid=r['valid'],controls_valid=r['controls_valid'],cases=[dict(id=x['case']['id'],decision=x['classification']['decision'],probe=x['probe']['status'],mismatches=x['probe']['mismatches'],passed=x['passed']) for x in r['cases']]),indent=2))
    return 0 if r['valid'] else 1

if __name__=='__main__':raise SystemExit(main())
