"""Readonly prompt/interface compatibility inventory, no harness/model/EDA execution."""
import hashlib,json,pathlib,sys,time
root=pathlib.Path('/workspace/team/runs/fpga_owner/functional_full156_20261005_v1')
p=pathlib.Path('/workspace/team/runs/fpga_teammate/cvdp_rng_S1_20261005_74b74f3/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(p)=='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
spec=json.loads((root/'RUN_SPEC.json').read_text())
for n in ['prompt_map.py','priority_contract.py','shift_contract.py']:assert sha(root/n)==spec['source_hashes'][n],n
sys.path.insert(0,str(root));import prompt_map
rows=[]
for line in p.read_text().splitlines():
    if not line.strip():continue
    row=json.loads(line);prompt=row['input']['prompt'];c=prompt_map.parse(prompt)
    rows.append({'id':row['id'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'prompt_chars':len(prompt),'input_context_file_count':len(row['input']['context']),'TopModule_mentioned':bool('TopModule' in prompt),'functional_contract_status':c['status'],'functional_contract_kind':c.get('kind')})
assert len(rows)==len({r['id'] for r in rows})==302
s2=pathlib.Path('/workspace/team/runs/fpga_teammate/cvdp_rng_S2_20261005_8a62e2f/PREPARATION.json');plan=json.loads(s2.read_text())
print(json.dumps({'schema':'independent_public_prompt_admission_inventory_v1','at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'inventory_source_sha256':sha(pathlib.Path(__file__)),'dataset_sha256':sha(p),'frozen_full_spec_sha256':sha(root/'RUN_SPEC.json'),'records':302,'functional_supported':sum(r['functional_contract_status']=='supported' for r in rows),'TopModule_mentioned':sum(r['TopModule_mentioned'] for r in rows),'input_context_required':sum(bool(r['input_context_file_count']) for r in rows),'rows':rows,'teammate_S2_plan':{'preparation_sha256':sha(s2),'source_sha256':plan['source_file_sha256'],'model_calls':plan['model_calls'],'eda_calls':plan['eda_calls'],'scope':'runner replay with simulator stub, no cocotb tests, RTL or grading loaded'},'model_calls':0,'eda_calls':0,'independent_tasks_admitted':0,'runtime_candidate_modified':False,'limits':['Compatibility screening only, not model solving, judge positive/negative calibration, independent score or dataset native coverage.','TopModule mention is lexical evidence, not complete interface compatibility; original module/context/test runner adaptation remains unverified.','S2 plan is observed readonly scope, not a completed result; do not execute or modify teammate code.','Only input.prompt parsed, context file count measured; original harness not imported/executed or forwarded to any model.']}))
