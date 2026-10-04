"""Bind verified actual prerequisite receipts before freezing a real FIFO run."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def prerequisites(v1,v2,full,decision):
    specs=['a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3']
    for e,s in zip([v1,v2],specs):assert e['passed'] and e['actual_execution_verified'] and e['evidence_kind']=='completed_cloud_stage' and e['run_spec_sha256']==s
    assert full['full156_evidence_valid'] and full['evidence_valid'] and not full['historical_fixture_only'] and full['candidate_qualified_for_independent_validation'] and full['spec_sha256']=='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
    assert decision['actual_full_result_processed'] and not decision['fixture_only'] and decision['qualified_for_independent_validation_after_attribution'] and decision['source_spec_sha256']==full['spec_sha256'] and decision['archive_sha256']==full['archive_sha256']
    return specs
def main():
    ap=argparse.ArgumentParser()
    for name in ['v1','v2','full156','attribution']:ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();assert not (ROOT/'RUN_SPEC.json').exists()
    tools=json.loads((ROOT/'TOOLS_SPEC.json').read_text(encoding='utf-8'))
    for n,h in tools['source_hashes'].items():assert sha(ROOT/n)==h,n
    inputs=[a.v1,a.v2,a.full156,a.attribution];values=[json.loads(p.read_text(encoding='utf-8')) for p in inputs];specs=prerequisites(*values)
    assert values[3]['audit_result_sha256']==sha(a.full156)
    target=ROOT/'prerequisite_audits';target.mkdir(exist_ok=False)
    for name,p in zip(['v1','v2','full156','attribution'],inputs):(target/(name+'.json')).write_bytes(p.read_bytes())
    files={**tools['source_hashes'],**{p.relative_to(ROOT).as_posix():sha(p) for p in target.iterdir()}}
    run={'schema':'formal_five_known_pilot_frozen_v1','identity':'formal_five_pilot_20261005_v1','cloud_root':'/workspace/team/runs/fpga_owner/formal_five_pilot_20261005_v1','kit':'/workspace/team/tasks/autodl-rtl-kit/project','model':'Qwen3.6-27B-Q4_K_M','model_pid':2013333,'source_hashes':files,'task_ids':['Prob112_always_case2','Prob115_shift18','Prob122_kmap4'],'samples_per_task_mode':5,'modes':['baseline','agent'],'expected_samples':30,'max_actual_model_requests':45,'solve_deadline_s':300,'judge_timeout_s':300,'stage_timeout_s':19000,'guard_stage_timeout_s':19200,'slot_minutes':325,'prerequisites':[{'cloud_root':'/workspace/team/runs/fpga_owner/'+n,'spec_sha256':s} for n,s in zip(['formal_bridge_20261005_v1','formal_bridge_v2_20261005_v1'],specs)],'required_readonly_audits':[{'path':'prerequisite_audits/'+n+'.json','sha256':sha(target/(n+'.json'))} for n in ['v1','v2']],'limits':tools['limits'],'adoption':False}
    (ROOT/'RUN_SPEC.json').write_text(json.dumps(run,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'run_spec_sha256':sha(ROOT/'RUN_SPEC.json'),'assets':len(files),'model_requests_submitted':0,'fifo_submitted':False}))
if __name__=='__main__':main()
