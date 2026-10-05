from pathlib import Path
import hashlib,json
b=Path(__file__).resolve().parents[3];r=Path(__file__).resolve().parent.parent;review=b/'03_analysis/team_phase_repair_review_20261005/RESULTS.json'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
pre=read(r/'LINUX_PREFLIGHT_RECEIPT.json');assert pre['tests_passed']==36 and pre['source_unchanged'] and pre['model_calls']==pre['eda_calls']==0
spec=read(r/'RUN_SPEC.json');a=read(review)
header='''## 2026-10-05 队友相位证据复核完成，新首稿C/P16冻结并通过双环境检查

原T7/T8/审计三档案3237清单文件逐SHA和原始请求/回复/原生/外判链复核，0新模型/EDA。两已知旧首稿条件修复：045单点S/相位P均5/5原生+官方L3，054 S0/5、P5/5；每臂五份相同输出，不算五次新首稿或独立设计。T7原48构造控制不重复，缺逐命令argv的收据限制保留。

新C/P41资产2539dcbc，本机3.12.14/Linux3.12.3各36检查，真实四工具路径/936+35/源/依赖/模型保持，0预检模型/EDA。新045/054+五正确守卫+未知143×两臂16真实新首稿、一次修复8192/300秒、原外判；同首回复/两道实际失配绑定修复到原生pass+L3及全部守卫/成本门槛保持。对照测整体边沿反馈策略，不能全部归因相位。此时尚未实际FIFO提交，不发新质量分或部署。G3/G4/G5 active，入口03_analysis/phase_feedback_pilot_20261005/README.md。

'''
for n in ['AI_CONTEXT.md','PROJECT_STATUS.md','05_handoff/STATUS_LATEST.md','05_handoff/AUTONOMOUS_GOALS_20261004.md','05_handoff/CHANGELOG.md','03_analysis/EXPERIMENT_REGISTRY.md']:
 p=b/n;p.write_bytes(header.encode()+p.read_bytes())
p=b/'PROJECT_STATE.json';state=read(p);g=state['autonomous_goals_20261004'];g['continuation_status']='phase_original_review_complete;fresh_CP16_frozen_both_hosts_waiting_FIFO';g['G3']='Fresh C/P16 frozen after original teammate phase review; all old full156 three-deadline and edge/FSM one-chain gates preserved. Requires two matched native+L3 repairs, all guards and cost conditions before another full156.'
state['team_phase_repair_review_20261005']=dict(status='original_three_archives_reviewed_signal_only',report='03_analysis/team_phase_repair_review_20261005/README.md',review_sha256=sha(b/'03_analysis/team_phase_repair_review_20261005/review.py'),archive_sha256=a['archive_sha256'],manifest_files=a['manifest_files'],conditional_samples=20,actual_old_repair_requests=20,first_generation_replayed=True,native_and_official_L3=a['native_and_official_L3'],review_model_calls=0,review_eda_calls=0,qualified_for_full=False,adoption=False)
state['phase_feedback_pilot_20261005']=dict(status='frozen_preflight_both_hosts_not_submitted',spec_sha256=sha(r/'RUN_SPEC.json'),archive_sha256=read(r/'PREPARATION_ARCHIVE.json')['archive_sha256'],assets=len(spec['source_hashes']),task_count=8,expected_samples=16,local_checks=36,linux_checks=36,first_generation_replayed=False,model_calls=0,actual_fifo_submitted=False,adoption=False,independent_model_tasks=0,qualified_for_full=False,report='03_analysis/phase_feedback_pilot_20261005/README.md')
save(p,state)
sync=read(b/'03_analysis/natural_harness_calibration_20261005/raw_evidence/TERMINAL_SHARED_SYNC_PROCESS.json');assert sync['rc']==0
save(b/'03_analysis/natural_harness_calibration_20261005/SHARED_SYNC_RECEIPT.json',json.loads(sync['stdout']))
print(json.dumps(dict(docs_updated=True,source_assets=len(spec['source_hashes']),review_files=sum(a['manifest_files'].values()))))
