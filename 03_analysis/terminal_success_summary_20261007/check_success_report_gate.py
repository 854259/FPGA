"""AMD-only exact report assert predicates; no original supervisor/auditor execution."""
import ast,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(Path(f).read_bytes()).hexdigest()
rows=[]
for role,original,outputs,spec_sha in [
 ('wave105','waveform_first_request_full156_20261007_v1',312,'d3b4b69f85e358c749954c12509908172a74663a83c4739a57d0c26cec5f5c5e'),
 ('onehot106','onehot_synthesis_cp7_20261007_v1',14,'d4cc6b511450e4cbc19e95105f2479d11c5bdd7166c6782043b9da7decda70d2')]:
 unit=Path('/workspace/team/runs/fpga_owner')/original;assert sha(unit/'RUN_SPEC.json')==spec_sha
 report=json.loads((unit/'results/summary.json').read_bytes());guard=json.loads((unit/'guard/status.json').read_bytes());spec=json.loads((unit/'RUN_SPEC.json').read_bytes())
 assert report['complete'] and report['passed'] and len(report['rows'])==outputs and not (unit/'ORIGINAL_TERMINAL_AUDIT_INTENT.json').exists()
 source=(ROOT/role/'terminal_supervisor.py').read_bytes();tree=ast.parse(source)
 # Extract the production assertions containing the report itself. Preserve
 # complete/passed/schema/spec/row/request checks exactly, including guard
 # predicates that occur in the same assertion. No rewritten surrogate gate.
 nodes=[n for n in ast.walk(tree) if isinstance(n,ast.Assert) and any(isinstance(x,ast.Name) and x.id=='report' for x in ast.walk(n)) and not any(isinstance(x,ast.Name) and x.id=='audited' for x in ast.walk(n))]
 assert len(nodes)==2
 executable=compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ROOT/role/'terminal_supervisor.py')+':exact_report_asserts','exec')
 cases=[('actual-complete-original',True,None),('explicit-none-error',True,lambda j:j.update(error=None)),('explicit-error-reject',False,lambda j:j.update(error='synthetic_failure')),('failed-reject',False,lambda j:j.update(passed=False)),('incomplete-reject',False,lambda j:j.update(complete=False)),('wrong-count-reject',False,lambda j:j.update(rows=j['rows'][:-1])),('wrong-spec-reject',False,lambda j:j.update(spec_sha256='0'*64)),('excess-requests-reject',False,lambda j:j.update(actual_model_requests=spec['max_actual_model_requests']+1))]
 for name,expected,mutate in cases:
  candidate=copy.deepcopy(report)
  if mutate:mutate(candidate)
  try:
   exec(executable,dict(report=candidate,guard=guard,spec=spec,ORIGINAL=unit,sha=sha));accepted=True
  except (AssertionError,KeyError):accepted=False
  assert accepted==expected,(role,name)
  rows.append(dict(role=role,case=name,assertions_passed=True,accepted=accepted,actual_original_report=name=='actual-complete-original',source_sha256=hashlib.sha256(source).hexdigest(),summary_sha256=sha(unit/'results/summary.json'),error_field_present='error' in report))
with (ROOT/'REPORT_GATE_RESULTS.json').open('x',encoding='utf-8') as f:
 json.dump(dict(passed=True,controls=len(rows),records=rows,original_supervisors_executed=0,original_auditors_executed=0,model_calls=0,eda_calls=0,old_controls_replayed=0),f,indent=2);f.write('\n')
print(json.dumps(dict(passed=True,controls=len(rows))))
