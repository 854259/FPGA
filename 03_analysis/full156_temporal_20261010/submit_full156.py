"""AMD-only single FIFO admission; keep this entry outside the frozen run root."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path('/workspace/team/runs/fpga_owner/temporal_first_system_full156_20261010_v2')
KIT=Path('/workspace/team/tasks/autodl-rtl-kit/project')
FIFO=Path('/workspace/team/tools/task-fifo-20261004/task_fifo.py')
OWNER='fpga-owner-temporal-original-C-full156-20261010-v2'
PLAN_SHA='3f6a6030622e2093cd671efda8563d14ad222620e48e90fc769d85d8c6a25bd7'
SPEC_SHA='a4be0260210cbe895def87c734674c52c2cfaf03741d7ba85c56c9bdf0b8fdf7'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(Path(p).parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def birth(pid):
 d=Path('/proc')/str(pid);s=(d/'stat').read_text().rsplit(')',1)[1].split()
 return dict(pid=pid,starttime=s[19],state=s[0],ppid=int(s[1]),pgid=int(s[2]),sid=int(s[3]),command_sha256=sha(d/'cmdline'))

def main(args):
 assert sys.platform=='linux' and sys.dont_write_bytecode
 assert args.policy_resolved, 'Unresolved comparison/goal policy: preserve prepared roots; do not submit'
 assert ROOT.resolve()==ROOT and not ROOT.is_symlink() and not Path(__file__).resolve().is_relative_to(ROOT)
 assert 0<=time.time()-args.coordination_epoch<120 and args.last_comment_id>0
 assert sha(ROOT/'PLAN.json')==PLAN_SHA and sha(ROOT/'RUN_SPEC.json')==SPEC_SHA
 prep=read(ROOT/'PREPARATION_RESULT.json');spec=read(ROOT/'RUN_SPEC.json');plan=read(ROOT/'PLAN.json')
 assert prep['complete'] and prep['prepared'] and not prep['submitted'] and prep['execution_authorized']
 assert prep['plan_sha256']==PLAN_SHA and prep['spec_sha256']==SPEC_SHA
 assert spec['source_hashes']==prep['source_hashes'] and spec['execution_authorized']
 assert all(sha(ROOT/n)==h for n,h in spec['source_hashes'].items()) and len(spec['source_hashes'])==33
 assert prep['control_CPU_scope']['passed'] and not prep['control_CPU_scope']['new_real_C_solve_qualified']
 assert prep['candidate_P_same_as_preparation'] and prep['immutable_preparation_held']
 assert (prep['model_calls'],prep['eda_calls'],prep['fifo_calls'])==(0,0,0)
 assert plan['execution_authorized'] and not plan['qualification_only'] and plan['full156']
 assert 'engineering_prefix' not in plan and not plan['formal_adoption'] and not plan['full_goal_complete']
 assert (plan['samples'],plan['unique_tasks'],len(plan['rows']),plan['max_calls'],plan['required_reserved_calls'],plan['wall_seconds'],plan['retries'])==(5,156,2340,3900,3900,172800,0)
 assert (plan['solve_deadline_s'],plan['solve_supervisor_s'],plan['judge_supervisor_s'],plan['row_reservation_s'])==(300,310,360,670)
 assert plan['original_goal_canonical_sample']==0 and plan['no_best_sample_goal_selection']
 assert plan['original_goal_cost_gate_spec_sha256']=='0b9c1c07ed275eff5ba81d9281c86575db7f89b729d7951491dcafea73df6702'
 assert plan['sources']['root']==str(ROOT) and plan['sources']['model_feedback'] and 'generation_arms' not in plan['sources']
 assert plan['sources']['files']=={**{str(ROOT/n):h for n,h in spec['source_hashes'].items()},str(ROOT/'RUN_SPEC.json'):SPEC_SHA}
 assert sha(ROOT/'guard_wrapper.py')=='fdd22d547cab6884b071044a7a1f26f847d8937618a55a201838ff10f77ff9d9'
 assert sha(FIFO)=='4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'
 sys.path.insert(0,str(ROOT));import three_arm_queue_20261005 as queue
 queue.validate(plan)
 tickets=[read(p) for p in Path('/workspace/team/task_fifo/tickets').glob('*.json')]
 assert next(t for t in tickets if t['ticket']==141)['state']=='completed'
 assert all(next(t for t in tickets if t['ticket']==i)['state']=='failed_released_after_inspection' for i in (132,139,140))
 assert not any(t.get('cwd')==str(ROOT) for t in tickets),'Existing handle: read only; never submit again'
 assert not any((ROOT/n).exists() for n in ('SUBMISSION_INTENT.json','SUBMISSION.json','MONITOR_BIRTH.json','guard','queue'))
 assert shutil.disk_usage(ROOT).free>=2*1024**3
 model=birth(2013333)
 assert model['state'] not in ('Z','X') and model['starttime']=='823869819'
 assert model['command_sha256']=='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'
 argv=['/usr/bin/python3','-B',str(FIFO),'submit','--task-name','temporal_original_C_full156x5_v2',
  '--cwd',str(ROOT),'--completion-json',str(ROOT/'guard/status.json'),'--slot-owner-prefix',OWNER,'--',
  '/usr/bin/env','PATH=/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  'VIVADO_BIN=/workspace/AMD/2026.1/Vivado/bin','LD_LIBRARY_PATH=/workspace/team/udev-stub','PYTHONUTF8=1',
  '/usr/bin/flock','-n','/workspace/team/.gpu.lock','/usr/bin/python3','-B',str(ROOT/'guard_wrapper.py'),
  '--kit',str(KIT),'--model-pid','2013333','--model-name',plan['model'],'--owner',OWNER,
  '--guard-out',str(ROOT/'guard'),'--minimum-free-gib','2','--slot-minutes','2890','--stage-timeout-s','173100','--',
  '/usr/bin/python3','-B',str(ROOT/'three_arm_queue_20261005.py'),'--plan',str(ROOT/'PLAN.json'),
  '--plan-sha256',PLAN_SHA,'--out',str(ROOT/'queue'),'--resource-check','{resource_check}']
 save(ROOT/'SUBMISSION_INTENT.json',dict(saved_epoch=time.time(),argv=argv,last_comment_id=args.last_comment_id,
  coordination_epoch=args.coordination_epoch,source_entry_sha256=sha(__file__),model=model,
  full_scope=dict(tasks=156,samples=5,rows=2340,max_calls=3900),
  no_retry=True,unknown_outcome='Inspect this same intent/root/ticket; never resubmit'))
 try:cp=subprocess.run(argv,capture_output=True,timeout=30)
 except subprocess.TimeoutExpired as e:
  (ROOT/'SUBMIT.stdout').write_bytes(e.stdout or b'');(ROOT/'SUBMIT.stderr').write_bytes(e.stderr or b'')
  raise RuntimeError('Unknown FIFO outcome; inspect same handle only') from e
 (ROOT/'SUBMIT.stdout').write_bytes(cp.stdout);(ROOT/'SUBMIT.stderr').write_bytes(cp.stderr)
 assert cp.returncode==0,'Failed/unknown submission: same handle read only'
 result=json.loads(cp.stdout);result.update(root=str(ROOT),plan_sha256=PLAN_SHA,spec_sha256=SPEC_SHA,
  tasks=156,samples=5,outputs=2340,max_reserved_model_calls=3900,whole_task_FIFO=True,
  score_available=False,full_goal_complete=False,adoption=False,no_retry=True)
 save(ROOT/'SUBMISSION.json',result)
 try:monitor=birth(result['monitor_pid'])
 except FileNotFoundError:monitor=dict(pid=result['monitor_pid'],exists=False,read_existing_ticket_only=True)
 if monitor.get('exists') is not False:assert monitor['sid']!=os.getsid(0),'Monitor must be detached from local SSH'
 save(ROOT/'MONITOR_BIRTH.json',monitor)
 print(json.dumps(dict(admission=result,monitor=monitor,independent_of_local_SSH=monitor.get('sid')!=os.getsid(0))))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--policy-resolved',action='store_true');p.add_argument('--last-comment-id',type=int,required=True);p.add_argument('--coordination-epoch',type=float,required=True)
 main(p.parse_args())
