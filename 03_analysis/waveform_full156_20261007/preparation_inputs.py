"""Complete fixed experimental scope; production never imports this metadata."""
from pathlib import Path
import hashlib,json
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def task_groups(root):
 root=Path(root);original=json.loads((root/'upstream/RUN_SPEC.json').read_bytes());tasks=original['task_ids']
 assert len(tasks)==len(set(tasks))==156 and tasks==sorted(tasks)
 reference=json.loads((root/'FULL_BASELINE_REFERENCE.json').read_bytes())
 assert set(reference['levels'])==set(tasks)
 guards=[t for t in tasks if reference['levels'][t]==3];assert len(guards)==113
 admission=json.loads((root/'PRODUCTION_ADMISSION.json').read_bytes())['full156_prompt_only'];assert set(admission)==set(tasks)
 return dict(task_ids=tasks,target_tasks=[t for t in tasks if t not in guards],guard_tasks=guards,abstention_tasks=[],advice_tasks=[t for t in tasks if admission[t]['advice']],expected_samples=312)
def validate_kit(root,kit):
 root,kit=Path(root),Path(kit);groups=task_groups(root);manifest=json.loads((root/'upstream/INPUT_MANIFEST.json').read_bytes())
 admission=json.loads((root/'PRODUCTION_ADMISSION.json').read_bytes())['full156_prompt_only']
 for task in groups['task_ids']:
  source=kit/'bench/tasks_veval'/task
  for n in ('prompt.txt','interface.txt'):
   key=task+'/'+n
   if key in manifest['input_sha256']:assert sha(source/n)==manifest['input_sha256'][key]
   else:assert not (source/n).exists()
  assert sha(source/'prompt.txt')==admission[task]['prompt_sha256']
 return groups
