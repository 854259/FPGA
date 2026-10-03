#!/usr/bin/env python3
"""Prompt-only guard validation, reusing the unchanged R2 bounded EDA runner."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_RUNNER = Path(os.environ.get(
    "R2_BASE_PROBE_RUNNER",
    ROOT.parents[1] / "r2_signedness_20261003" / "probes" / "probe_runner.py",
)).resolve()
TASK_CHECKS = {"Prob033_ece241_2014_q1c": 65536,
               "Prob016_m2014_q4j": 256,
               "Prob009_popcount3": 8,
               "Prob085_shift4": 209,
               "Prob123_bugs_addsubz": 131072}
spec = importlib.util.spec_from_file_location("r2_guard_inherited_runner", BASE_RUNNER)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load original R2 probe runner")
inherited = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inherited)
# The wrapper is also called probe_runner.py: inherited per-run runner_sha256
# records this wrapper, and frozen_assets additionally pins the real EDA runner.
inherited.ROOT = ROOT
inherited.TASK_CHECKS = TASK_CHECKS


def frozen_assets():
    paths = [ROOT / "probe_runner.py", ROOT / "provenance.json"]
    paths += [ROOT / task / name for task in TASK_CHECKS for name in
              ("prompt.txt", "candidate.sv", "tb.sv", "positive.sv", "negative.sv")]
    result = {path.relative_to(ROOT).as_posix(): inherited.sha256(path) for path in paths}
    result["inherited_r2/probe_runner.py"] = inherited.sha256(BASE_RUNNER)
    return result


def run_candidate(task, solution, outdir):
    """Return the existing R2 result schema, without retries or verdict input."""
    base_hash = inherited.sha256(BASE_RUNNER)
    result = inherited.probe_candidate(task, solution, outdir)
    if inherited.sha256(BASE_RUNNER) != base_hash:
        raise RuntimeError("inherited R2 runner changed during probe")
    return result


probe_candidate = run_candidate


def validate_guards(outdir):
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=False)
    assets = frozen_assets()
    result = {"schema_version": 1, "complete": False, "valid": False,
              "probe_files": assets, "tasks": {},
              "inherited_runner_sha256": inherited.sha256(BASE_RUNNER),
              "wrapper_sha256": inherited.sha256(ROOT / "probe_runner.py"),
              "task_checks": TASK_CHECKS,
              "scope": "prompt-derived controls and unchanged archived candidates only"}
    for task in TASK_CHECKS:
        rows = {name: run_candidate(task, ROOT / task / filename,
                                    outdir / task / name)
                for name, filename in (("positive", "positive.sv"),
                                       ("negative", "negative.sv"),
                                       ("archived", "candidate.sv"))}
        rows["valid"] = (
            rows["positive"]["status"] == "pass"
            and rows["negative"]["status"] == "fail"
            and rows["negative"]["failure_kind"] == "semantic_mismatch"
            and rows["archived"]["status"] == "pass")
        result["tasks"][task] = rows
    result["complete"] = True
    result["assets_unchanged"] = assets == frozen_assets()
    result["valid"] = result["assets_unchanged"] and all(
        row["valid"] for row in result["tasks"].values())
    inherited._write_json(outdir / "guards_validation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validation = sub.add_parser("validate-guards")
    validation.add_argument("--out", type=Path, required=True)
    single = sub.add_parser("candidate")
    single.add_argument("--task", choices=TASK_CHECKS, required=True)
    single.add_argument("--solution", type=Path, required=True)
    single.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-guards":
        result = validate_guards(args.out)
        print(json.dumps({"valid": result["valid"], "tasks": {
            task: {name: [row[name]["status"], row[name]["checks"], row[name]["mismatches"]]
                   for name in ("positive", "negative", "archived")}
            for task, row in result["tasks"].items()}}, indent=2))
        return 0 if result["valid"] else 1
    result = run_candidate(args.task, args.solution, args.out)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
