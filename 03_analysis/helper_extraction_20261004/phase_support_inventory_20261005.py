"""AMD-only applicability census on all existing 156+44 solver inputs.

No model, EDA, reference, testbench or candidate-output access. This does not
admit a dataset, measure correctness, or promote any already-seen task to unseen.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def load(name,p):
    spec=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def prepare(a):
    assert sys.platform=='linux'
    t8=json.loads((a.candidate/'RUN_SPEC.json').read_text())
    assert sha(a.candidate/'RUN_SPEC.json')=='86ac7739c5fa6d6084af42c299fb5625690c08ddc6901c7f132313e260425890'
    a.out.mkdir(parents=True,exist_ok=False)
    sources={name:h for name,h in t8['source_hashes'].items() if name in (
        'edge_dispatch.py','edge_contract.py','edge_feedback.py','point_feedback.py',
        'prompt_map.py','priority_contract.py','shift_contract.py','reserved_keywords.py')}
    assert len(sources)==8
    inputs=[]
    for label,root,count in [('VerilogEval156',a.veval,156),('RTLLM44',a.rtllm,44)]:
        prompts=sorted(root.glob('*/prompt.txt'));assert len(prompts)==count
        for p in prompts:
            names=['prompt.txt']+(['interface.txt'] if (p.parent/'interface.txt').is_file() else [])
            inputs.append(dict(dataset=label,task=p.parent.name,root=str(p.parent),
                files={n:sha(p.parent/n) for n in names},exposure='historical_development_regression'))
    spec=dict(source_commit=a.source_commit,driver_sha256=sha(Path(__file__)),candidate=str(a.candidate),source_hashes=sources,
        inputs=inputs,expected_inputs=200,model_calls=0,eda_calls=0,stage_timeout_s=120,
        question='Does the frozen phase feedback have any existing transfer target beyond its two development checkpoints?',
        decision='If no additional edge target exists, do not spend inference budget claiming transfer on non-triggering tasks; retain independent-material gap. No selector changes in this census.')
    save(a.out/'INPUT_SPEC.json',spec)
    print(json.dumps(dict(prepared=True,spec_sha256=sha(a.out/'INPUT_SPEC.json'),inputs=len(inputs))))


def run(a):
    assert sys.platform=='linux'
    assert sha(a.spec)==a.spec_sha256
    spec=json.loads(a.spec.read_text());candidate=Path(spec['candidate'])
    assert sha(Path(__file__))==spec['driver_sha256']
    assert sha(a.paired)=='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    paired=load('inventory_owned',a.paired);paired.check_resource(a.resource_check,a.kit,first=True)
    for name,h in spec['source_hashes'].items():assert sha(candidate/name)==h
    sys.path.insert(0,str(candidate));import edge_dispatch
    a.out.mkdir(parents=True,exist_ok=False);tick=time.monotonic();rows=[]
    for item in spec['inputs']:
        root=Path(item['root'])
        for name,h in item['files'].items():assert sha(root/name)==h
        prompt=(root/'prompt.txt').read_text(encoding='utf-8')
        if 'interface.txt' in item['files'] and (root/'interface.txt').read_text(encoding='utf-8').strip():
            prompt+='\n\nInterface:\n'+(root/'interface.txt').read_text(encoding='utf-8')
        contract=edge_dispatch.parse(prompt)
        family=contract.get('family') if contract.get('status')=='supported' else None
        rows.append(dict(dataset=item['dataset'],task=item['task'],input_hashes=item['files'],
            exposure=item['exposure'],selector_status=contract['status'],supported_family=family,
            phase_feedback_target=family=='edge',reason=contract.get('reason'),
            independent_admission=False))
    assert len(rows)==200
    report=dict(complete=True,source_commit=spec['source_commit'],spec_sha256=a.spec_sha256,
        model_calls=0,eda_calls=0,independent_tasks=0,full_batch_complete=False,elapsed_s=time.monotonic()-tick,
        datasets={name:dict(total=sum(r['dataset']==name for r in rows),
            phase_targets=[r['task'] for r in rows if r['dataset']==name and r['phase_feedback_target']],
            family_counts=dict(Counter(str(r['supported_family']) for r in rows if r['dataset']==name)))
            for name in ('VerilogEval156','RTLLM44')},
        limits='Applicability only. Non-triggering correct samples do not establish safe forced review or repair benefit. Existing inputs remain development/regression; no new data admission.')
    save(a.out/'PRIVATE_INPUT_ROWS.json',rows);save(a.out/'summary.json',report)
    for item in spec['inputs']:
        for name,h in item['files'].items():assert sha(Path(item['root'])/name)==h
    for name,h in spec['source_hashes'].items():assert sha(candidate/name)==h
    paired.check_resource(a.resource_check,a.kit)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run'])
    for n in ('candidate','veval','rtllm','out','spec','paired','kit','resource-check'):p.add_argument('--'+n,type=Path)
    p.add_argument('--source-commit');p.add_argument('--spec-sha256');a=p.parse_args()
    prepare(a) if a.action=='prepare' else run(a)
