"""Experimental task selection; never imported by the prompt-to-RTL compiler."""
from pathlib import Path
import hashlib,json

TARGET_NUMBERS=(50,57,101,102,113,125)
GUARD_NUMBERS=(45,54,71,90,103,115,122)
ABSTENTION_NUMBERS=(83,)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def task_groups(root):
    root=Path(root)
    upstream=json.loads((root/"upstream/RUN_SPEC.json").read_bytes())
    assert len(upstream["task_ids"])==156
    manifest=json.loads((root/"upstream/INPUT_MANIFEST.json").read_bytes())
    def select(numbers):
        names=[]
        for number in numbers:
            matches=[t for t in upstream["task_ids"] if t.startswith(f"Prob{number:03d}_")]
            assert len(matches)==1,(number,matches)
            task=matches[0]
            assert task+"/prompt.txt" in manifest["input_sha256"],task
            names.append(task)
        return sorted(names)
    targets,guards,abstentions=(select(v) for v in (TARGET_NUMBERS,GUARD_NUMBERS,ABSTENTION_NUMBERS))
    all_tasks=sorted(targets+guards+abstentions)
    assert len(all_tasks)==len(set(all_tasks))==14
    return dict(task_ids=all_tasks,target_tasks=targets,guard_tasks=guards,
                abstention_tasks=abstentions,expected_samples=28)


def validate_kit(root,kit):
    root,kit=Path(root),Path(kit)
    groups=task_groups(root)
    manifest=json.loads((root/"upstream/INPUT_MANIFEST.json").read_bytes())
    for task in groups["task_ids"]:
        source=kit/"bench/tasks_veval"/task
        assert source.is_dir(),task
        assert sha(source/"prompt.txt")==manifest["input_sha256"][task+"/prompt.txt"]
        key=task+"/interface.txt"
        if key in manifest["input_sha256"]:
            assert sha(source/"interface.txt")==manifest["input_sha256"][key]
        else:
            assert not (source/"interface.txt").exists(),task
    return groups
