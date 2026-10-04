"""Readonly R1 reproduction and strict identifier fix; no tools/model calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile
import priority_contract
import shift_contract
from reserved_keywords import KEYWORDS

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def main():
    archive=ROOT/'raw_evidence/team_R1.zip';assert sha(archive)=='3afbf0962e4066a81368e5bb2434a61bbd4e0ee7aef7e9f3c0d11bcecb159db8'
    snapshot=ROOT/'raw_evidence/team_snapshot';assert not snapshot.exists();snapshot.mkdir()
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('READONLY_MANIFEST.json'))
        assert set(z.namelist())==set(manifest['files'])|{'READONLY_MANIFEST.json'}
        for n,h in manifest['files'].items():
            assert not Path(n).is_absolute() and '..' not in Path(n).parts
            raw=z.read(n);assert hashlib.sha256(raw).hexdigest()==h
            p=snapshot/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    team=read(snapshot/'results/summary.json');assert team['complete'] and not team['admission_passed'] and team['counts']['false_accept']==4047
    assert sha(snapshot/'audit.py')==team['driver_sha256']=='16cc1f6910de458f95c6b802c6a2076c07cd02722a21801cb361b1ead1178443'
    assert sha(snapshot/'results/sources/shift_contract.py')==team['source_hashes']['shift_contract.py']==sha(ROOT.parent/'shift_contract_20261005/shift_contract.py')
    assert sha(snapshot/'results/sources/test_shift.py')==team['source_hashes']['test_shift.py']
    fixture=load('shift_boundary_material',snapshot/'results/sources/test_shift.py')
    old=load('shift_original_boundary',snapshot/'results/sources/shift_contract.py')
    words=('bit','byte','shortint','int','longint','time','real','event','enum','struct','union','always_comb','always_ff','always_latch')
    rows=[]
    for width in range(8,65):
        base=fixture.material(width)
        rows.extend([(f'w{width}_plain','valid',base,True),(f'w{width}_renamed','valid',fixture.material(width,'clock','capture','run','mode','payload','state'),True)])
        for role in ('load','enable','amount','data','out'):
            for word in words:rows.append((f'w{width}_{role}_{word}','reserved_word',fixture.material(width,**{role:word}),False))
        for label,text in [('role_only',base.replace('(3) amount:','(3) AMOUNT:')),('selector_only',base.replace('"amount."','"AMOUNT."')),('both',base.replace('(3) amount:','(3) AMOUNT:').replace('"amount."','"AMOUNT."'))]:
            rows.append((f'w{width}_case_{label}','case_ambiguity',text,False))
    assert len(rows)==4275
    frozen=[dict(id=i,group=g,prompt_sha256=hashlib.sha256(p.encode()).hexdigest(),expect_supported=e) for i,g,p,e in rows]
    assert frozen==read(snapshot/'results/INPUT_MANIFEST.json')
    for (i,g,p,e),record in zip(rows,team['rows']):
        old_contract=old.parse(p);actual=old_contract['status']=='supported'
        assert dict(id=i,group=g,expected_supported=e,actual_supported=actual,status=old_contract['status'])==record
        new=shift_contract.parse(p);assert (new['status']=='supported') is e,i
        if e:assert new==old_contract and shift_contract.render_tb(new,'R1Witness')==old.render_tb(old_contract,'R1Witness')
    guard=read(snapshot/'guard/status.json')
    assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
    assert guard['stage_rc']==0 and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    for c in team['compiler_controls']:
        r=c['supervision'];log=snapshot/'results/compiler_controls'/c['id']/'compile.log'
        assert sha(log)==r['log_sha256'] and log.stat().st_size==r['log_bytes']
        assert not r['timeout'] and not r['launch_error'] and not r['remaining_live_group']
        assert c['expectation_matched'] and (r['returncode']==0)==c['expected_compile']
        assert 'VRFC ' in log.read_text(encoding='utf-8',errors='replace')
    assert len(team['compiler_controls'])==16
    keyword_cases=0
    for width in [8,64]:
        for role in ['load','enable','amount','data','out']:
            for word in KEYWORDS:
                assert shift_contract.parse(fixture.material(width,**{role:word}))['status']=='abstain'
                assert shift_contract.parse(fixture.material(width,**{role:word.upper()}))['status']=='supported'
                keyword_cases+=2
    priority_fixture=load('priority_boundary_material',ROOT.parent/'priority_contract_20261005/test_priority.py')
    for width in [2,8]:
        for role in ['signal','out']:
            for word in KEYWORDS:
                assert priority_contract.parse(priority_fixture.material(width,**{role:word}))['status']=='abstain'
                assert priority_contract.parse(priority_fixture.material(width,**{role:word.upper()}))['status']=='supported'
                keyword_cases+=2
    preserved=[]
    for folder,parser in [('priority_contract_20261005',priority_contract),('shift_contract_20261005',shift_contract)]:
        for task in sorted((ROOT.parent/folder/'raw_evidence/inputs').iterdir()):
            c=parser.parse((task/'prompt.txt').read_bytes().decode('utf-8'));assert c==read(task/'contract.json')
            assert parser.render_tb(c,task.name)==(task/'tb.sv').read_text(encoding='utf-8')
            preserved.append(task.name)
    assert len(preserved)==8
    result=dict(schema='functional_contract_identifier_boundary_v1',passed=True,team_snapshot_sha256=sha(archive),
        source_commit='38099a60798ef35babd9504c658d5b1b91403bb6',old_false_accepts_reproduced=4047,
        team_cases_reproduced=4275,fixed_grid_false_accepts=0,fixed_grid_false_abstains=0,valid_contracts_and_TB_preserved=114,
        additional_keyword_and_uppercase_cases=keyword_cases,canonical_keyword_count=len(KEYWORDS),calibrated_contracts_preserved=preserved,
        source_hashes={n:sha(ROOT/n) for n in ['priority_contract.py','shift_contract.py','reserved_keywords.py','reconcile.py']},
        native_compiler_witnesses_checked=16,local_model_calls=0,local_eda_calls=0,teammate_mutations=0,
        limits=['Lexical boundary grid and native old syntax witnesses, not independent natural validation or functional repair score',
            'New supported contracts/TBs identical on eight real calibration cases; no new EDA claim',
            'ASCII identifiers and complete bounded prose only; extended/escaped syntax abstains',
            'Keywords identified from primary language-name tables; no external compiler used for evaluation'])
    (ROOT/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
