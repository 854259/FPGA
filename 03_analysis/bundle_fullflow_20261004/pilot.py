"""Full original worker flow, paired on three fixed historical initial replies."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, obj):
    p.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    for name in ("root", "kit", "resource-check"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    spec = read(root / "RUN_SPEC.json")
    deps = Path(spec["dependencies_cloud"])
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    paired = load("flow_paired", deps / "paired_checkpoint.py")
    paired.REPO, paired.INHERITED_ORACLE = root, deps / "probe_runner.py"
    paired.check_resource(args.resource_check, args.kit, first=True)
    out = root / "results"
    out.mkdir(exist_ok=False)
    spec_hash, start = sha(root / "RUN_SPEC.json"), time.monotonic()
    report = dict(schema="bundle_fullflow_development_v1", complete=False, verified=False,
                  controls={}, rows=[], actual_model_requests=0, replayed_requests=0,
                  actual_probes=0, run_spec_sha256=spec_hash)

    def gate():
        assert time.monotonic() - start < spec["stage_timeout_s"]
        assert sha(root / "RUN_SPEC.json") == spec_hash
        for n, h in spec["source_hashes"].items():
            assert sha(root / n) == h, n
        for n, h in spec["dependency_hashes"].items():
            assert sha(deps / n) == h, n
        paired.check_resource(args.resource_check, args.kit)

    def probe(task, source, folder):
        gate()
        p = paired.oracle(dict(task=task, checks=spec["checks"][task], tb="inputs/" + task + "/tb.sv"), source, folder)
        report["actual_probes"] += 1
        if p["status"] == "environment_error":
            raise RuntimeError("Functional probe environment error")
        return p

    try:
        for task in spec["checks"]:
            controls = {}
            for label in ("positive", "negative"):
                p = probe(task, root / "inputs" / task / (label + ".sv"), out / "controls" / task / label)
                assert p["checks"] == spec["checks"][task]
                assert p["status"] == ("pass" if label == "positive" else "fail")
                if label == "negative":
                    assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0
                controls[label] = p
            report["controls"][task] = controls
        # No actual experimental candidate is graded until all worker outputs exist.
        for task, arm in spec["order"]:
            gate()
            folder = out / "workers" / task / arm
            folder.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, "-B", str(root / "worker_adapter.py"), "--root", str(root),
                "--task", str(root / "inputs" / task), "--out", str(folder), "--arm", arm,
                "--kit", str(args.kit), "--resource-check", str(args.resource_check)]
            r = paired.owned_command(command, root, folder.parent / (arm + ".supervisor.log"), spec["worker_timeout_s"])
            if r["returncode"] != 0 or r["timeout"] or r["launch_error"] or r["remaining_live_group"]:
                raise RuntimeError("Owned runtime worker failed; no resampling")
            result = read(folder / "worker_result.json")
            assert result["complete"] and result["arm"] == arm
            report["actual_model_requests"] += result["actual_model_requests"]
            report["replayed_requests"] += result["replayed_requests"]
            assert report["actual_model_requests"] <= spec["max_actual_model_requests"]
            report["rows"].append(dict(task=task, arm=arm, worker=result, supervisor=r,
                                       solution_sha256=sha(folder / "solution.v")))
            save(out / "summary.json", report)
            print(json.dumps(dict(phase="worker_complete", task=task, arm=arm,
                actual_requests=result["actual_model_requests"], elapsed_s=result["elapsed_s"])), flush=True)
        save(out / "workers_complete.json", dict(grading_started=False, rows=report["rows"]))
        for row in report["rows"]:
            folder = out / "workers" / row["task"] / row["arm"]
            row["probe"] = probe(row["task"], folder / "solution.v", out / "probes" / row["task"] / row["arm"])
            save(out / "summary.json", report)
        gate()
        report["complete"] = report["verified"] = len(report["rows"]) == 6
    except BaseException as e:
        report["error"] = type(e).__name__ + ": " + str(e)
    finally:
        report["elapsed_s"] = time.monotonic() - start
        save(out / "summary.json", report)
    print(json.dumps({k:report.get(k) for k in ("complete", "verified", "actual_model_requests", "error", "elapsed_s")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    os.environ.update(RTL_PROFILE="development", MODEL_NAME="Qwen3.6-27B-Q4_K_M",
                     LLM_BASE_URL="http://127.0.0.1:8000/v1", RTL_REPAIRS="1",
                     RTL_TEMPERATURE="0", RTL_MAX_TOKENS="8192")
    raise SystemExit(main())
