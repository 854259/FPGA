"""Fixed6 experiment metadata; never imported by producer."""
from pathlib import Path
import hashlib,json
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def task_groups(root):
    root=Path(root)
    original=json.loads((root/'upstream/RUN_SPEC.json').read_bytes())
    tasks=original['task_ids']
    assert len(tasks)==len(set(tasks))==156 and tasks==sorted(tasks)
    reference=json.loads((root/'FULL_BASELINE_REFERENCE.json').read_bytes())
    assert reference['source_audit_sha256']==sha(root/'FULL_BASELINE_SOURCE_AUDIT.json')=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
    levels=reference['levels'];assert set(levels)==set(tasks)
    admission=json.loads((root/'PRODUCTION_ADMISSION.json').read_bytes())
    assert admission['task_count']==156 and set(admission['tasks'])==set(tasks)
    guards=[t for t in tasks if levels[t]==3]
    assert len(guards)==113
    return dict(task_ids=tasks,target_tasks=[t for t in tasks if t not in guards],
                guard_tasks=guards,abstention_tasks=[t for t in tasks if not admission['tasks'][t]['emitted']],
                expected_samples=312)

def validate_kit(root,kit):
    root,kit=Path(root),Path(kit);groups=task_groups(root);manifest=json.loads((root/'upstream/INPUT_MANIFEST.json').read_bytes())
    for task in groups['task_ids']:
        source=kit/'bench/tasks_veval'/task
        for n in ('prompt.txt','interface.txt'):
            key=task+'/'+n
            if key in manifest['input_sha256']:assert sha(source/n)==manifest['input_sha256'][key]
            else:assert not (source/n).exists()
    return groups
