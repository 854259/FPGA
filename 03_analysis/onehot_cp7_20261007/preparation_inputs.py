"""Fixed7 experiment metadata; never imported by producer."""
from pathlib import Path
import hashlib,json
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def task_groups(root):
    root=Path(root);original=json.loads((root/'upstream/RUN_SPEC.json').read_bytes());assert len(original['task_ids'])==156
    by_number={int(t[4:7]):t for t in original['task_ids']};targets=[by_number[n] for n in (143,)];guards=[by_number[n] for n in (45,54,71,115,127,138)];tasks=sorted(targets+guards)
    return dict(task_ids=tasks,target_tasks=targets,guard_tasks=sorted(guards),abstention_tasks=[],expected_samples=14)
def validate_kit(root,kit):
    root,kit=Path(root),Path(kit);groups=task_groups(root);manifest=json.loads((root/'upstream/INPUT_MANIFEST.json').read_bytes())
    for task in groups['task_ids']:
        source=kit/'bench/tasks_veval'/task
        for n in ('prompt.txt','interface.txt'):
            key=task+'/'+n
            if key in manifest['input_sha256']:assert sha(source/n)==manifest['input_sha256'][key]
            else:assert not (source/n).exists()
    return groups
