"""AMD-only completion of the existing 278-row inventory against all 312 rows."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", required=True, type=Path)
    ap.add_argument("--resource-check", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    assert sys.platform == "linux"
    sys.dont_write_bytecode = True
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    frozen = {
        "failure_inventory.py": "79e97e6d1aaac631a6f053f642b34a3751fd8232893d3840b7fc207f130944a9",
        "full312.zip": "64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616",
        "full312_audit/RESULTS.json": "f6e53edad6357cc8dcaabd86ed40f455c9e8cd45a2e6267da7005bb75911cdcf",
    }
    for name, expected in frozen.items():
        assert sha(args.source_root / name) == expected, name
    resource = json.loads(args.resource_check.read_text())
    assert resource["resource_idle"] is True
    assert sha(Path(resource["slot_lock_path"])) == resource["slot_lock_sha256"]
    args.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    spec = importlib.util.spec_from_file_location("frozen_failure_inventory", args.source_root / "failure_inventory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.inventory(args.source_root / "full312.zip",
                              args.source_root / "full312_audit/RESULTS.json", args.out / "inventory")
    rows = result["records"]
    assert len(rows) == 312 and len({(r["task"], r["arm"]) for r in rows}) == 312
    arms = {}
    for arm in ("A", "C"):
        group = [r for r in rows if r["arm"] == arm]
        assert len(group) == 156
        failed = [r for r in group if r["level"] < 3]
        arms[arm] = dict(samples=156, failures=len(failed),
            failed_levels=dict(Counter(r["level"] for r in failed)),
            failure_tags=dict(Counter(tag for r in failed for tag in r["prompt_review_tags"])),
            failed_with_length_response=sum(any(c.get("finish_reason") == "length" for c in r["calls"]) for r in failed),
            failed_with_deadline=sum(r["deadline"] for r in failed),
            failed_with_unconfirmed=sum(r["unconfirmed_attempts"] > 0 for r in failed))
    for name, expected in frozen.items():
        assert sha(args.source_root / name) == expected, name
    summary = dict(complete=True, passed=True, samples=312, model_calls=0, eda_calls=0,
        elapsed_s=time.monotonic()-tick, arms=arms, input_hashes=frozen,
        driver_sha256=sha(Path(__file__)), full_batch_complete=False,
        independent_natural_tasks=0, runtime_changes=False,
        scope="Complete existing known-regression inventory; tags overlap and do not establish causes")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
