"""Freeze a new budget-matched experiment, preserving all old failed gates."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import metrics

ROOT=Path(__file__).resolve().parent
FULL=ROOT.parent/'functional_full156_20261005'
TOOLS=ROOT.parent/'repair_context_20261005'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    assert sys.version_info[:2]==(3,12)
    assert not (ROOT/'RUN_SPEC.json').exists()
    full=read(FULL/'RUN_SPEC.json')
    assert sha(FULL/'RUN_SPEC.json')=='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
    audit=read(FULL/'terminal_audit_cloud/RESULTS.json')
    assert audit==read(FULL/'terminal_audit_local312/RESULTS.json') and audit['evidence_valid']
    assert not audit['candidate_qualified_for_independent_validation']
    admission=read(TOOLS/'ARCHIVED_EXPOSURE.json')
    assert admission['archive_sha256']==audit['archive_sha256']
    assert admission['candidate_source_sha256']==sha(ROOT/'context.py')
    assert sorted({r['task'] for r in admission['rows'] if r['changed']})==['Prob070_ece241_2013_q2','Prob153_gshare']
    originals=[]
    for n,h in full['source_hashes'].items():
        if (ROOT/n).is_file() and n not in ['worker.py','audit.py','pilot.py','replay.py','metrics.py','prepare.py']:
            assert sha(ROOT/n)==h,n
            originals.append(n)
    assert sha(ROOT/'package/agent/d_runtime.py')==sha(TOOLS/'package/agent/d_runtime.py')
    result=subprocess.run([sys.executable,'-B','-m','unittest','test_context','test_integration','test_fresh','test_metrics','test_replay','test_stage','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr
    tasks=sorted(metrics.GUARDS+['Prob070_ece241_2013_q2','Prob147_circuit10','Prob153_gshare'])
    spec=dict(schema='repair_context_pilot_frozen_v1',identity='repair_context_pilot_20261005_v1',
              base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              cloud_root='/workspace/team/runs/fpga_owner/repair_context_pilot_20261005_v1',
              kit=full['kit'],model=full['model'],model_pid=full['model_pid'],
              task_ids=tasks,arms=['C','D'],samples_per_arm_per_task=1,expected_samples=16,
              solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,
              stage_timeout_s=14400,slot_minutes=250,max_actual_model_requests=32,
              max_worker_requests_per_arm=2,first_generation_replayed=False,retries=0,
              dependencies_cloud=full['dependencies_cloud'],dependency_hashes=full['dependency_hashes'],
              python_major_minor=[3,12],predecessor_full_spec_sha256=sha(FULL/'RUN_SPEC.json'),
              predecessor_full_archive_sha256=audit['archive_sha256'],
              predecessor_full_gate_failed_preserved=True,preflight_tools_spec_sha256=sha(TOOLS/'TOOLS_SPEC.json'),
              historical_context_exposure_sha256=sha(TOOLS/'ARCHIVED_EXPOSURE.json'),
              original_frozen_assets_unchanged=originals,
              runtime_change='C exact full regression functional agent; D only compresses large ordinary whole-line comments in repair prompt copy, adds metadata trace. Actual DUT/checks/compiler/extract/skill/model/budget untouched.',
              acceptance='All16 real fresh samples and complete source/message/actual DUT/native judge/cleanup audit. Candidate D has no deadlines/unconfirmed, guards058/071/112/115/124 both L3, no coefficient regression or extra requests. At least2 distinct matched-first actual compressed repair contexts; positive mean with matched gain OR equal mean with >=10% matched solve-time reduction. Permits a new full156 experiment only, never independent/five/adoption.',
              limits=[
                  '8 known public development/guard tasks, one actual generation per arm; no full156 score, unseen-task or five-sample claim.',
                  'First prompts and skills identical; fresh first replies may differ despite temperature0, matched subset reported separately.',
                  'Control deadlines/unconfirmed remain in 8-task denominator and costs; candidate must be deadline/unconfirmed-free. This is a predeclared reliability-repair screen, not relaxation/rescoring of prior full gate.',
                  'Tool/environment failure retains failed job; do not resample, replace failures or alter frozen budget.',
                  'Only prompt/interface enter workers; reference/TB/grade live solely in original external judge. No task-ID scripted answers.',
                  'Whole-task FIFO and original inner locks/guard. Never manage shared model, instance, formal deployment or teammate jobs.',
                  'Stage/slot outer limits are safety bounds, not ETA. Hard300s includes generation/compilation/feedback; control timeouts are measured and model request drains without killing the model.',
                  'New frozen auditor binds the exact compressed copy/metadata and independently reconstructs original uncompressed DUT/diagnostics from responses/compile/native receipts.',
                  'No automatic deployment; full same-budget regression, independent validation and formal offline target32GB/five-sample acceptance remain required.'
              ])
    sources=[]
    for p in ROOT.rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts:continue
        n=p.relative_to(ROOT).as_posix()
        if p.suffix=='.py' and not n.startswith('raw_evidence/') or n=='INPUT_MANIFEST.json' or n.startswith('package/skill/') and p.name=='SKILL.md' or n.startswith('raw_evidence/test_fixtures/') and p.suffix in ['.txt','.py']:
            sources.append(n)
    spec['source_hashes']={n:sha(ROOT/n) for n in sorted(sources)}
    save(ROOT/'RUN_SPEC.json',spec)
    save(ROOT/'PREPARATION_RECEIPT.json',dict(spec_sha256=sha(ROOT/'RUN_SPEC.json'),assets=len(sources),tests_passed=27,
         stdout=result.stdout,stderr=result.stderr,model_calls=0,eda_calls=0,old_gate_unchanged=True,
         real_experiment_submitted=False))
    archive=ROOT/'raw_evidence/preparation.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n in [*spec['source_hashes'],'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(ROOT/n,n)
    save(ROOT/'PREPARATION_ARCHIVE.json',dict(sha256=sha(archive),spec_sha256=sha(ROOT/'RUN_SPEC.json'),assets=len(sources)))
    print(json.dumps(dict(assets=len(sources),tests_passed=27,spec_sha256=sha(ROOT/'RUN_SPEC.json'),archive_sha256=sha(archive))))


if __name__=='__main__':main()
