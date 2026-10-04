"""Read-only local reproduction of teammate O3; no shared resources or tools."""
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parent
SNAPSHOT=ROOT/'raw_evidence/team_snapshot'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes().decode('utf-8'))
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    parser=ROOT/'prompt_map_strict.py';material=SNAPSHOT/'boundary.py'
    assert sha(parser)=='fb5c1c6a951f7f3d492bc2fcc2d512bf1d1f481fdfafd4f71afd582972fb5a0c'
    assert sha(material)=='073c532da2954e3ead3f208e155c322952fed1f36026debd86108ab00b007f15'
    module=load('reconciled_strict_map',parser);factory=load('team_boundary_factory',material)
    calibration=ROOT.parent/'prompt_map_contract_20261004/raw_evidence/inputs'
    started=time.monotonic();records=[]
    for n in (2,3,4):
        for axis in itertools.permutations('pqrs'[:n]):
            for order,rows,ports in itertools.product(range(3),(False,True),(False,True)):
                prompt,names,expected=factory.material(n,axis,order,rows,ports)
                got=module.parse(prompt)
                actual={tuple(c['inputs'][name] for name in names):c['expected'] for c in got.get('cases',[])}
                assert got['status']=='supported' and actual==expected
                records.append(dict(kind='supported',n=n,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
        for extra in factory.EXTRA:
            prompt,_,_=factory.material(n,tuple('pqrs'[:n]),0,False,False,extra)
            got=module.parse(prompt);assert got['status']=='abstain'
            records.append(dict(kind='additional_semantics',n=n,extra=extra,reason=got['reason']))
    regression=[]
    for folder in sorted((SNAPSHOT/'inputs').iterdir()):
        prompt=(folder/'prompt.txt').read_bytes()
        assert prompt==(calibration/folder.name/'prompt.txt').read_bytes()
        expected=read(folder/'contract.json');assert expected==read(calibration/folder.name/'contract.json')
        got=module.parse(prompt.decode('utf-8'));assert got==expected
        normalized=module.parse(prompt.decode('utf-8').replace('\r\n','\n'))
        difference=sorted(k for k in got.keys()|normalized.keys() if got.get(k)!=normalized.get(k))
        assert difference in ([],['prompt_sha256'])
        assert module.render_tb(got,folder.name)==(calibration/folder.name/'tb.sv').read_bytes().decode('utf-8')
        regression.append(dict(case=folder.name,prompt_sha256=sha(folder/'prompt.txt'),
            complete_contract_equal=True,truth_and_testbench_bytes_equal=True,
            newline_normalized_difference_fields=difference))
    assert len(records)==420 and len(regression)==8
    extra=json.loads((ROOT.parent/'prompt_map_feedback_v2_20261004/PARSER_BOUNDARY_REVIEW.json').read_text(encoding='utf-8'))['rows']
    base=(calibration/'Prob050_kmap1/prompt.txt').read_bytes().decode('utf-8')
    for row in extra:assert module.parse(row['extra']+'\n'+base)['status']=='abstain'
    assert sum(bool(x['newline_normalized_difference_fields']) for x in regression)==4
    report=dict(schema='map_boundary_local_reconciliation_v1',complete=True,passed=True,
        parser_sha256=sha(parser),reproducer_sha256=sha(Path(__file__)),
        source_snapshot_sha256=sha(ROOT/'raw_evidence/team_O3_readonly.zip'),
        supported_constructed_cases=384,additional_semantic_abstention_cases=36,
        calibrated_contracts_preserved=8,own_previous_false_accepts_now_abstained=10,
        false_accepts=0,regression=regression,elapsed_s=time.monotonic()-started,
        O2_four_mismatch_reason='CRLF normalization changes prompt_sha256 only; truth rows, interface, care counts and rendered TB unchanged',
        team_O3_original_summary=read(SNAPSHOT/'SUMMARY.json'),
        model_calls=0,eda_calls=0,teammate_sources_changed=False,deployment_changed=False,
        scope='Constructed grammar controls and eight known calibration contracts, not independent natural RTL tasks',
        admission='Strict parser eligible as frozen research dependency; not deployment or unrestricted prose support')
    (ROOT/'RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['regression','team_O3_original_summary']}))


if __name__=='__main__':main()
