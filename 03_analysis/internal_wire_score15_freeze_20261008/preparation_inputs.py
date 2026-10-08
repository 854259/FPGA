"""Fixed metadata membership; production never imports this file or history."""
from pathlib import Path
import hashlib,json

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def task_groups(root):
    root=Path(root);original=json.loads((root/'upstream/RUN_SPEC.json').read_bytes());all_tasks=original['task_ids']
    assert len(all_tasks)==len(set(all_tasks))==156 and all_tasks==sorted(all_tasks)
    scope=json.loads((root/'FIXED_SCOPE.json').read_bytes());tasks=scope['task_ids']
    assert len(tasks)==len(set(tasks))==15 and tasks==sorted(tasks) and set(tasks)<=set(all_tasks)
    reference=json.loads((root/'FULL_BASELINE_REFERENCE.json').read_bytes())
    assert sha(root/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
    assert sha(root/'FULL_BASELINE_SOURCE_AUDIT.json')==reference['source_audit_sha256']=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
    assert set(reference['levels'])==set(all_tasks) and sum(v==3 for v in reference['levels'].values())==113
    guards=[t for t in tasks if reference['levels'][t]==3];assert len(guards)==8
    declaration_factor_tasks=list(tasks);abstentions=[]
    return dict(task_ids=tasks,target_tasks=[t for t in tasks if t not in guards],guard_tasks=guards,
        abstention_tasks=abstentions,declaration_factor_tasks=declaration_factor_tasks,expected_samples=30)

def validate_kit(root,kit):
    root,kit=Path(root),Path(kit);groups=task_groups(root);manifest=json.loads((root/'upstream/INPUT_MANIFEST.json').read_bytes())
    for task in groups['task_ids']:
        source=kit/'bench/tasks_veval'/task
        for n in ('prompt.txt','interface.txt'):
            key=task+'/'+n
            if key in manifest['input_sha256']:assert sha(source/n)==manifest['input_sha256'][key]
            else:assert not (source/n).exists()
    return groups
