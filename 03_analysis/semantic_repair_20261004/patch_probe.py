"""Frozen, isolated signed-cast mechanism study; makes zero model requests."""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError("cannot enable owned descendant reaping")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.source.resolve(), args.out.resolve()
    paired = load("patch_paired_oracle", repo / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    manifest = paired.frozen()
    selector_path = paired.PACKAGE / "agent/signedness_selector.py"
    if paired.sha(selector_path) != "a13fbdb8528a9e1a7309364aa6d145f959d8bcbf94bb383a635510cb7a81547b":
        raise RuntimeError("selector identity changed")
    selector = load("patch_frozen_selector", selector_path)
    patcher = load("deterministic_signed_patch", Path(__file__).with_name("signed_shift_patch.py"))
    paired.check_resource(args.resource_check, args.kit, first=True)
    fixture_root = args.fixtures.resolve()
    fixtures = paired.read(fixture_root / "manifest.json")
    for rel, digest in fixtures["input_sha256"].items():
        if paired.sha(fixture_root / rel) != digest:
            raise RuntimeError("fixture changed: " + rel)
    assets = [repo / rel for rel in manifest["files"]]
    assets += [fixture_root / rel for rel in fixtures["input_sha256"]]
    assets += [fixture_root / "manifest.json", selector_path, Path(__file__), Path(patcher.__file__)]
    before = {str(p): paired.sha(p) for p in assets}
    tasks = {task["task"]: task for task in manifest["tasks"]}
    cases = [dict(subject, supported_error=subject["id"] in
                  ("Known115Wrong", "Arithmetic11BoundaryWrong", "Arithmetic17BoundaryWrong"),
                  expected_original="fail" if subject["id"].endswith("Wrong") else "pass")
             for subject in manifest["subjects"]]
    for case in fixtures["cases"]:
        task = case["family"]
        tasks[task] = dict(task=task, checks=fixtures["families"][task]["checks"],
                           tb=str(fixture_root / task / "tb.sv"))
        cases.append(dict(id="R2b_" + case["id"], task=task,
                          family="constructed_boundary_case",
                          prompt=str(fixture_root / "cases" / case["id"] / "prompt.txt"),
                          candidate=str(fixture_root / "cases" / case["id"] / "candidate.sv"),
                          supported_error=case["expected_decision"] == "review",
                          expected_original=case["expected_probe"]))
    if len(cases) != 22:
        raise RuntimeError("expected all 22 preregistered cases")
    out.mkdir(parents=True, exist_ok=False)
    report = dict(schema="deterministic_signed_cast_study_v1", complete=False, verified=False,
                  model_calls=0, runtime_integrated=False, deployment_approved=False,
                  snapshot_before=before, rows=[], limits=[
                      "one known natural development error; other error targets are constructed",
                      "no independent full-set or release claim"])
    try:
        # All transformations are frozen before any new outcome is observed.
        for case in cases:
            prompt = (repo / case["prompt"]).read_bytes().decode("utf-8")
            original = (repo / case["candidate"]).read_bytes().decode("utf-8")
            updated, record = patcher.patch(prompt, original, selector)
            generated = out / "generated" / case["id"] / "solution.sv"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(updated.encode("utf-8"))
            row = dict(case, transformation=record, solution=str(generated),
                       byte_identical=updated == original)
            report["rows"].append(row)
        paired.save(out / "transformations_frozen.json", report)
        for row in report["rows"]:
            if {str(p): paired.sha(p) for p in assets} != before:
                raise RuntimeError("input snapshot changed")
            task = tasks[row["task"]]
            if row["transformation"]["changed"]:
                row["before"] = paired.oracle(task, repo / row["candidate"], out / "oracles" / row["id"] / "before")
                if row["before"]["status"] != "fail" or row["before"]["failure_kind"] != "semantic_mismatch":
                    raise RuntimeError("supported original error was not reproduced: " + row["id"])
            row["after"] = paired.oracle(task, Path(row["solution"]), out / "oracles" / row["id"] / "after")
            if row["after"]["status"] == "environment_error":
                raise RuntimeError("environment failure: " + row["id"])
            expected = "pass" if row["supported_error"] else row["expected_original"]
            row["accepted"] = (row["transformation"]["changed"] == row["supported_error"]
                               and row["after"]["status"] == expected
                               and (row["supported_error"] or row["byte_identical"])
                               and (expected == "pass" or row["after"]["failure_kind"] == "semantic_mismatch"))
        report["complete"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    report["snapshot_after"] = {str(p): paired.sha(p) for p in assets}
    report["inputs_unchanged"] = before == report["snapshot_after"]
    report["verified"] = report["complete"] and report["inputs_unchanged"] and all(row.get("accepted") for row in report["rows"])
    report["counts"] = dict(cases=len(report["rows"]), changed=sum(row["transformation"]["changed"] for row in report["rows"]),
                            passed=sum(row.get("after", {}).get("status") == "pass" for row in report["rows"]),
                            preserved=sum(row["byte_identical"] for row in report["rows"]))
    paired.save(out / "summary.json", report)
    print(json.dumps({key: report.get(key) for key in ("complete", "verified", "counts", "error")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
