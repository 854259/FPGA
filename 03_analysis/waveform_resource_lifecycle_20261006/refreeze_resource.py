"""Refreeze the cancelled CP6 after a single resource lifecycle fix. AMD only."""
import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PARENT_SPEC = "9b90acec3379490e4d313d59bceb6fd9833ed713624267f1a0aa05de96cc121c"
OLD_WORKER = "5ea05bec155c64807da1aee9cd94f2dd734abcd2b618f5c6b9601441e9959306"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_bytes())

def save(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")

def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def main():
    a = argparse.ArgumentParser()
    a.add_argument("--parent", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--source-commit", required=True)
    args = a.parse_args()
    assert sys.platform == "linux" and sys.version_info[:2] == (3, 12) and sys.dont_write_bytecode
    assert len(args.source_commit) == 40 and all(c in "0123456789abcdef" for c in args.source_commit)
    source = Path(__file__).resolve().parent
    parent, out = args.parent.resolve(), args.out.resolve()
    assert sha(parent/"RUN_SPEC.json") == PARENT_SPEC
    old = read(parent/"RUN_SPEC.json")
    assert len(old["source_hashes"]) == 89
    assert not (parent/"results").exists(), "Only the unstarted cancelled version is an admissible parent"
    before = (parent/"worker.py").read_bytes()
    after = (source/"worker.py").read_bytes()
    assert sha(parent/"worker.py") == OLD_WORKER
    needle = b"paired.check_resource(args.resource_check, args.kit, first=True)"
    assert before.count(needle) == 1
    assert after == before.replace(needle, b"paired.check_resource(args.resource_check, args.kit)")
    for n, h in old["source_hashes"].items():
        assert (parent/n).resolve().is_relative_to(parent) and sha(parent/n) == h, n
    out.mkdir(parents=True, exist_ok=False)
    for n in old["source_hashes"]:
        target = out/n
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parent/n, target)
    for n in ("worker.py", "test_resource_lifecycle.py", "refreeze_resource.py"):
        shutil.copyfile(source/n, out/n)
    factor = (out/"factor_proof.py").read_text()
    assert factor.count(OLD_WORKER) == 1
    (out/"factor_proof.py").write_text(factor.replace(OLD_WORKER, sha(out/"worker.py")))
    # Existing solver behavior, stage entry admission, judge, budget and score gates remain byte-identical.
    old_tree, new_tree = ast.parse(before), ast.parse(after)
    old_body = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_worker")
    new_body = next(n for n in new_tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_worker")
    assert ast.dump(old_body) == ast.dump(new_body)
    sys.path.insert(0, str(out))
    proof = load("new_resource_factor", out/"factor_proof.py").verify(out)
    save(out/"SOURCE_FACTOR_PROOF.json", proof)
    checks = out/"raw_evidence/resource_lifecycle"
    checks.mkdir(parents=True)
    commands = [
        [sys.executable, "-B", str(out/"test_resource_lifecycle.py"), "--root", str(out),
         "--old-worker", str(parent/"worker.py"), "--receipt", str(checks/"GENERIC_CONTROLS.json")],
        [sys.executable, "-B", "-m", "unittest", "-v", "test_cp6_boundaries", "test_cp6_pipeline"],
    ]
    runs = []
    for index, command in enumerate(commands):
        with (checks/f"{index}.stdout").open("xb") as log:
            completed = subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=90)
        row = dict(returncode=completed.returncode, stdout_sha256=sha(checks/f"{index}.stdout"))
        runs.append(row)
        save(checks/"COMMANDS.json", runs)
        assert completed.returncode == 0, f"Control failure; retain {checks}"
    receipt = read(checks/"GENERIC_CONTROLS.json")
    assert receipt["passed"] and receipt["tests"] == 10
    # Do not call older whole-worker controls a rerun of the changed CLI entry.
    amendment = dict(schema="resource_lifecycle_admission_amendment_v1", parent_spec_sha256=PARENT_SPEC,
                     original_worker_sha256=OLD_WORKER, worker_sha256=sha(out/"worker.py"),
                     source_commit=args.source_commit, solver_body_unchanged=True, stage_and_checker_unchanged=True,
                     generic_controls=receipt, boundary_and_pipeline_commands=runs,
                     previous_controls_scope="Unchanged solver body and prompt factor only; old CLI boundary superseded",
                     original_failed_run_cost_preserved=True, parent_was_unstarted=True,
                     model_calls=0, eda_calls=0, score_measured=False, adoption=False)
    save(out/"RESOURCE_LIFECYCLE_ADMISSION.json", amendment)
    shutil.copyfile(parent/"RUN_SPEC.json", out/"PARENT_RUN_SPEC.json")
    os.environ.update(old["compiler_env"])
    os.environ.update(RTL_MAX_TOKENS="8192", RTL_REPAIRS="1", RTL_TEMPERATURE="0",
                      MODEL_NAME=old["model"], LLM_BASE_URL="http://127.0.0.1:8000/v1")
    pilot = load("new_resource_pilot", out/"pilot.py")
    env = pilot.validate_environment()
    assert env["tools"] == old["compiler_tools"] and env["compiler_env"] == old["compiler_env"] and env["udev_files"] == old["udev_files"]
    paired = load("new_resource_checker", out/"dependencies/paired_checkpoint.py")
    assert paired.model_identity(old["model_pid"]) == old["model_identity"]
    protected = load("new_resource_protected", out/"protected_sources.py")
    protection = read(out/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json")
    assert protected.check(protection)["verified"]
    spec = dict(old)
    spec.update(identity=out.name, cloud_root=str(out), dependencies_cloud=str(out/"dependencies"),
                frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                resource_fix_source_commit=args.source_commit, parent_spec_sha256=PARENT_SPEC,
                source_factor_proof_sha256=sha(out/"SOURCE_FACTOR_PROOF.json"),
                resource_lifecycle_admission_sha256=sha(out/"RESOURCE_LIFECYCLE_ADMISSION.json"),
                qualification="Unchanged prior prompt/solver evidence; 10 new generic resource controls and reexecuted boundary/pipeline controls. No new natural score.")
    names = set(old["source_hashes"]) | {"test_resource_lifecycle.py", "refreeze_resource.py",
             "RESOURCE_LIFECYCLE_ADMISSION.json", "PARENT_RUN_SPEC.json"}
    names |= {p.relative_to(out).as_posix() for p in checks.iterdir() if p.is_file()}
    spec["source_hashes"] = {n: sha(out/n) for n in sorted(names)}
    save(out/"RUN_SPEC.json", spec)
    assert pilot.frozen(Path(old["kit"])) == spec
    for n, h in old["source_hashes"].items():
        assert sha(parent/n) == h, n
    final = dict(schema="resource_lifecycle_cp6_refreeze_v1", complete=True, passed=True,
                 spec_sha256=sha(out/"RUN_SPEC.json"), worker_sha256=sha(out/"worker.py"),
                 parent_spec_sha256=PARENT_SPEC, source_commit=args.source_commit,
                 frozen_sources=len(names), controls=receipt["tests"], model_calls=0, eda_calls=0,
                 tasks=6, expected_samples=12, max_model_requests=24, submitted=False,
                 old_frozen_files_unchanged=True, acceptance_unchanged=spec["acceptance"]==old["acceptance"])
    save(out/"PREPARATION_RECEIPT.json", final)
    print(json.dumps(final))

if __name__ == "__main__":
    main()

