from pathlib import Path
import json,subprocess
base=Path(__file__).resolve().parents[3];r=Path(__file__).resolve().parent.parent;raw=r/'raw_evidence'
a=json.loads((r/'PREPARATION_ARCHIVE.json').read_bytes());s=(base/'03_analysis/edge_feedback_pilot_20261005/raw_evidence/install.py').read_text(encoding='utf-8')
s=s.replace('edge_feedback_pilot_20261005_v1','phase_feedback_pilot_20261005_v1').replace('bce903e984fd0f1b92bd11759b0ecc3bdf77783f384bca74cde0b9cf09beacf6',a['source_spec_sha256']).replace('f7eda52eab608cfced1239a6002a6ff30d597816605dc6302e49efff0b132681',a['archive_sha256']).replace("'test_environment','-v'","'test_environment','test_phase','-v'").replace('Ran 33 tests','Ran 36 tests').replace('tests_passed=33','tests_passed=36')
s+='\ntickets=[json.loads(p.read_text()) for p in Path("/workspace/team/task_fifo/tickets").glob("*.json")]\nprint(json.dumps(dict(recent_tickets=[dict(ticket=t["ticket"],task=t["task_name"],state=t["state"],cwd=t["cwd"]) for t in sorted(tickets,key=lambda t:t["ticket"])[-8:]])))\n'
compile(s,'phase_install_remote.py','exec');(raw/'install_remote.py').write_bytes(s.encode())
key=r'C:\Users\66561\.ssh\amd_shared_20261001';host='root@36.150.116.206';remote='/workspace/team/runs/fpga_owner/phase_feedback_pilot_20261005_v1_preparation.zip'
x=subprocess.run(['scp','-o','ConnectTimeout=15','-i',key,'-P','33557',str(raw/'preparation_v1.zip'),host+':'+remote],capture_output=True,text=True,timeout=55);assert x.returncode==0,x.stderr
x=subprocess.run(['ssh','-o','ConnectTimeout=15','-i',key,'-p','33557',host,'python3 -'],input=s,capture_output=True,text=True,encoding='utf-8',timeout=60)
(raw/'INSTALL_PROCESS.json').write_bytes((json.dumps(dict(rc=x.returncode,stdout=x.stdout,stderr=x.stderr),ensure_ascii=False,indent=2)+'\n').encode());assert x.returncode==0,x.stderr
parts=x.stdout.splitlines();receipt=json.loads(parts[0]);(r/'LINUX_PREFLIGHT_RECEIPT.json').write_bytes((json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode());(raw/'RECENT_TICKETS.json').write_bytes((parts[1]+'\n').encode());print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','tests_passed','source_unchanged','protected','model_calls','eda_calls']}));print(parts[1])
