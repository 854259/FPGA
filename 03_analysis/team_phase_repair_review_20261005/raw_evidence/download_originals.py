from pathlib import Path
import subprocess,json,hashlib,zipfile
raw=Path(__file__).resolve().parent;raw.mkdir(exist_ok=True)
key=r'C:\Users\66561\.ssh\amd_shared_20261001';host='root@36.150.116.206'
source=r'''from pathlib import Path
import json,hashlib
out=[]
for number in [45,46,47]:
 t=json.loads((Path('/workspace/team/task_fifo/tickets')/(str(number).zfill(8)+'.json')).read_text());root=Path(t['cwd']);assert root.is_relative_to('/workspace/team/runs/fpga_teammate') and t['state']=='completed'
 files=[]
 for p in root.glob('*.zip'):files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
 out.append(dict(ticket=t,archives=files))
print(json.dumps(out))
'''
r=subprocess.run(['ssh','-o','ConnectTimeout=15','-i',key,'-p','33557',host,'python3 -'],input=source,capture_output=True,text=True,encoding='utf-8',timeout=45);assert r.returncode==0,r.stderr
data=json.loads(r.stdout);(raw/'ORIGINAL_INVENTORY.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
for entry in data:
 number=entry['ticket']['ticket']
 for item in entry['archives']:
  name=Path(item['path']).name
  if name not in ['EVIDENCE.zip','PREPARATION.zip','SOURCE_TRANSFER.zip']:continue
  target=raw/(str(number)+'_'+name)
  if not target.exists():
   r=subprocess.run(['scp','-o','ConnectTimeout=15','-i',key,'-P','33557',host+':'+item['path'],str(target)],capture_output=True,text=True,timeout=55);assert r.returncode==0,r.stderr
  assert target.stat().st_size==item['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']
  with zipfile.ZipFile(target) as z:
   assert len(z.namelist())==len(set(z.namelist()))
   print(json.dumps(dict(ticket=number,name=name,bytes=item['bytes'],sha256=item['sha256'],files=len(z.namelist()),head=z.namelist()[:18])))
