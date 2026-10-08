"""Only three newly changed interface groups, each in a fresh bounded process."""
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
groups=[('worker','test_cp8_extension.py','ACTUAL_CP8_EXTENSION_RESULT.json'),('generation','test_cp8_generation_binding.py','ACTUAL_CP8_GENERATION_RESULT.json'),('scoring','test_cp8_score7_interfaces.py','ACTUAL_CP8_SCORE7_INTERFACE_RESULT.json')]
result=dict(schema='table_history_cp8_changed_interface_groups_v1',passed=False,groups={},new_model_EDA_FIFO_calls=0,score_measured=False)
for name,entry,output in groups:
 started=time.monotonic()
 cp=subprocess.run([sys.executable,'-B',str(ROOT/entry)],cwd=ROOT,capture_output=True,timeout=10)
 (ROOT/(name+'_stdout.bin')).write_bytes(cp.stdout);(ROOT/(name+'_stderr.bin')).write_bytes(cp.stderr)
 result['groups'][name]=dict(returncode=cp.returncode,elapsed_s=time.monotonic()-started,result=json.loads((ROOT/output).read_bytes()) if (ROOT/output).exists() else None)
 (ROOT/'CP8_CONTROL_GROUP_PROGRESS.json').write_text(json.dumps(result,indent=2)+'\n')
 assert cp.returncode==0,(name,cp.stderr.decode(errors='replace'))
 assert result['groups'][name]['result']['passed'] is True
result['passed']=True
(ROOT/'ACTUAL_CP8_CONTROLS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
