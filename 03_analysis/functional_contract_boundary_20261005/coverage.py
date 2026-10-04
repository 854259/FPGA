"""Read-only applicability on all 156 immutable public prompts, no execution."""
import hashlib,json,zipfile
from pathlib import Path
import priority_contract,shift_contract
R=Path(__file__).resolve().parent
archive=R.parent/'full156_postflight_20261004/raw_evidence/full312.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
spec=json.loads((R.parent/'functional_fresh_pilot_v3_20261005/INPUT_MANIFEST.json').read_text())
rows=[]
with zipfile.ZipFile(archive) as z:
 for n,h in sorted(spec['input_sha256'].items()):
  if not n.endswith('/prompt.txt'):continue
  raw=z.read('kit/bench/tasks_veval/'+n);assert hashlib.sha256(raw).hexdigest()==h
  p=priority_contract.parse(raw.decode('utf-8'));s=shift_contract.parse(raw.decode('utf-8'))
  rows.append(dict(task=n.split('/')[0],prompt_sha256=h,priority_status=p['status'],shift_status=s['status']))
assert len(rows)==156
report=dict(schema='functional_applicability_156_v1',complete=True,model_calls=0,eda_calls=0,adoption=False,new_score=False,independent_natural_tasks=0,
 source_hashes={n:hashlib.sha256((R/n).read_bytes()).hexdigest() for n in ['priority_contract.py','shift_contract.py','reserved_keywords.py','coverage.py']},
 supported=[r for r in rows if r['priority_status']=='supported' or r['shift_status']=='supported'],rows=rows,
 limitation='Only public prompt applicability, no candidate generation/functional execution or unseen-task proof; known development cohort only.')
(R/'COVERAGE.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='rows'}))
