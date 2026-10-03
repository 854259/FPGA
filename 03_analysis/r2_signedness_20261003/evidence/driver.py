from pathlib import Path
import subprocess,sys,json,time
root=Path(__file__).resolve().parent
run=Path((root/'run_path.txt').read_text().strip())
kit=Path('/workspace/team/tasks/autodl-rtl-kit/project')
owner='codex_r2_20261003'
commands=[['python3','-B',str(root/'signedness_repair_pilot.py'),'run','--out',str(run),'--slot-owner',owner],['python3','-B',str(root/'grade_pilot.py'),'--run',str(run),'--kit',str(kit),'--evaluator','/workspace/team/codex_takeover_20261003/official_eval.py','--probes',str(root/'probes/probe_runner.py'),'--slot-owner',owner]]
results=[]
for stage,cmd in zip(['generation','grading'],commands):
 start=time.time();rc=subprocess.call(cmd)
 results.append(dict(stage=stage,rc=rc,started=start,ended=time.time()))
 (root/'driver_status.json').write_text(json.dumps(results,indent=2))
 if rc:sys.exit(rc)
