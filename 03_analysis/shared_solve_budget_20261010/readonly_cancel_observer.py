
import argparse,hashlib,json,os,time,urllib.request
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
root=args.root.resolve();dest=args.out.resolve()
assert root.is_relative_to(Path('/workspace/team/runs/fpga_owner'))
assert dest.is_relative_to(Path('/workspace/team/activity/fpga_owner/artifacts'))

def model_birth():
 p=Path('/proc/2013333');f=(p/'stat').read_text().rsplit(')',1)[1].split()
 return dict(pid=2013333,starttime=f[19],state=f[0],command_sha256=hashlib.sha256((p/'cmdline').read_bytes()).hexdigest())
def read_if(p):
 try:return json.loads(p.read_bytes()) if p.is_file() else None
 except (OSError,ValueError):return None
started=time.monotonic();baseline=model_birth();rows=0;terminal_seen=None
with (dest/'OBSERVATIONS.jsonl').open('x') as out:
 while time.monotonic()-started<2820:
  now=time.monotonic();item=dict(monotonic=now,epoch=time.time(),model=model_birth())
  # Frequent slots responses wake the pinned server's shared result CV,
  # postponing its one-second disconnected-client poll. During budget
  # cancellation the production helper owns telemetry; observe files only.
  pending_budget=any((root/'qualification_queue'/('row_'+str(i).zfill(6))/'solve/SHARED_BUDGET_EXIT.json').is_file() and
   not (root/'qualification_queue'/('row_'+str(i).zfill(6))/'FAILED_SEALED.json').is_file() for i in range(4))
  item['telemetry_suppressed_for_budget_cancel']=pending_budget
  if not pending_budget:
   try:
    with urllib.request.urlopen('http://127.0.0.1:8000/slots',timeout=3) as response:slots=json.load(response)
    item['slots']=[{k:s.get(k) for k in ['id','id_task','is_processing','n_past','n_decoded','state']} for s in slots]
   except Exception as e:item['telemetry_error']=type(e).__name__
  observations=[]
  for index in range(4):
   folder=root/'qualification_queue'/('row_'+str(index).zfill(6))
   started_row=read_if(folder/'STARTED.json')
   if started_row is None:continue
   requests=read_if(folder/'solve/requests.json')
   selected=None if requests is None else [{k:r.get(k) for k in ['index','response_received','dispatch_started','error','elapsed_s','finish_reason','request_sha256','response_sha256']} for r in requests]
   terminal=read_if(folder/'TERMINAL.json');budget=read_if(folder/'solve/SHARED_BUDGET_EXIT.json')
   observations.append(dict(row=index,arm=started_row['row']['arm'],row_key=started_row['row']['key'],
    requests=selected,terminal_complete=None if terminal is None else terminal['complete'],
    terminal_sha256=None if terminal is None else hashlib.sha256((folder/'TERMINAL.json').read_bytes()).hexdigest(),
    budget_exit=None if budget is None else {k:budget.get(k) for k in ['schema','started_monotonic','observed_monotonic','elapsed_s','worker_role']},
    failed_sealed=(folder/'FAILED_SEALED.json').is_file(),succeeded_sealed=(folder/'SEALED.json').is_file()))
  item['rows']=observations
  guard=read_if(root/'guard/status.json');item['guard_complete']=bool(guard and guard.get('complete'))
  out.write(json.dumps(item)+'\n');out.flush();rows+=1
  if item['guard_complete']:
   if terminal_seen is None:terminal_seen=now
   if now-terminal_seen>=2:break
  time.sleep(.5)
result=dict(complete=True,guard_terminal_seen=terminal_seen is not None,observation_rows=rows,
 started_monotonic=started,ended_monotonic=time.monotonic(),model_before=baseline,model_after=model_birth(),
 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 telemetry_suppressed_observations=sum(json.loads(line).get('telemetry_suppressed_for_budget_cancel',False) for line in (dest/'OBSERVATIONS.jsonl').read_text().splitlines()),
 observations_sha256=hashlib.sha256((dest/'OBSERVATIONS.jsonl').read_bytes()).hexdigest(),
 only_read_shared_model=True,new_model_calls=0,new_EDA=0,new_FIFO=0)
(dest/'OBSERVATION_COMPLETE.json').write_text(json.dumps(result,indent=2)+'\n')
