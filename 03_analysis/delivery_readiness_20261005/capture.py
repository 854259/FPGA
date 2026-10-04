"""Read-only cloud/process facts; no model/EDA/build request or weight-file scan."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
REMOTE = r'''
import datetime,hashlib,json,pathlib,shutil
out={'schema':'cloud_readonly_delivery_and_progress_v1','observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'model_calls':0,'eda_calls':0,'mutations':0}
def ident(pid):
 try:
  s=pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
  return {'pid':pid,'state':s[0],'starttime':s[19]}
 except FileNotFoundError:return None
out['processes']={str(pid):ident(pid) for pid in [2013333,3390465,3427683]}
out['tickets']=[]
for n in [25,26,27,28]:
 x=json.loads(pathlib.Path(f'/workspace/team/task_fifo/tickets/{n:08}.json').read_text())
 out['tickets'].append({k:x.get(k) for k in ['ticket','task_name','state','accepted_at_utc','started_at_utc','runner','child']})
r=pathlib.Path('/workspace/team/runs/fpga_owner/functional_full156_20261005_v1/results/summary.json')
if r.exists():
 x=json.loads(r.read_text());out['full156_progress']={'rows':len(x['rows']),'complete':x['complete'],'passed':x['passed'],'actual_model_requests':x['actual_model_requests'],'error':x.get('error'),'summary_bytes_sha256':hashlib.sha256(r.read_bytes()).hexdigest(),'score_published':False}
out['container_tools']={n:shutil.which(n) for n in ['docker','podman','unshare']}
out['drm_vram_entries']=[]
for p in sorted(pathlib.Path('/sys/class/drm').glob('card[0-9]*/device/mem_info_vram_total')):
 out['drm_vram_entries'].append({'path':str(p),'total_bytes':int(p.read_text())})
try:
 env=pathlib.Path('/proc/2013333/environ').read_bytes().split(b'\0')
 allowed={'HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES'}
 out['model_device_masks']={a.decode().split('=',1)[0]:a.decode().split('=',1)[1] for a in env if b'=' in a and a.decode().split('=',1)[0] in allowed}
except FileNotFoundError:out['model_device_masks']=None
kit=pathlib.Path('/workspace/team/tasks/autodl-rtl-kit/project')
out['formal_runtime_candidates']={}
for name in ['agent/runtime.py','submission/agent/runtime.py','runtime.py']:
 p=kit/name
 if p.is_file():out['formal_runtime_candidates'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(out,ensure_ascii=True))
'''

def main():
    command = ['ssh', '-i', r'C:\Users\66561\.ssh\amd_shared_20261001', '-p', '33557',
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@36.150.116.206', 'python3 -']
    result = subprocess.run(command, input=REMOTE, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    report['capture_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    p = REPO / '04_project/amd_rtl_agent/submission/Dockerfile'
    body = p.read_text(encoding='utf-8')
    report['local_submission_dockerfile'] = {'path':str(p.relative_to(REPO)),
        'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'base_image_lines':[s for s in body.splitlines() if 'BASE_IMAGE' in s or s.startswith('FROM ')]}
    report['acceptance'] = {'official_image_build_verified':False,'offline_verified':False,
        'single_32gb_target_verified':False,'five_independent_samples_verified':False,
        'candidate_formal_service_promoted':False}
    report['limits'] = ['DRM entries and visibility masks alone do not certify target hardware or allocation.',
        'Container CLI absence does not prove a remote build is impossible.',
        'Local Dockerfile is archived project evidence, not a live official announcement.',
        'Partial sample count is progress only; new score requires complete terminal audit.']
    path = ROOT / 'SNAPSHOT.json'
    assert not path.exists(), 'Keep original snapshots immutable; use a new filename for another capture.'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))

if __name__ == '__main__':
    main()
