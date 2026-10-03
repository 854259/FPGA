#!/usr/bin/env python3
"""R3 three-candidate semantic check using the pinned R2 EDA runner."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK = "Prob086_lfsr5"
CHECKS = 269
HELPER_SHA256 = "954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0"
PROMPT_SHA256 = "161662a2c4c0b507de98adbbf7d186a5f6239342610cc024b4f1cb8c80904860"
CANDIDATE_SHA256 = "e4446e9268ab1f6113e48a39ae8706c2e3263a56e287bac3132c0eb0042b0949"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_helper(path):
    path = Path(path).resolve()
    if sha256(path) != HELPER_SHA256:
        raise ValueError("R2 helper hash does not match preregistered version")
    spec = importlib.util.spec_from_file_location("r3_pinned_r2_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    module.TASK_CHECKS = {TASK: CHECKS}
    return module


def frozen_assets(helper_path):
    paths = [ROOT.parent / "PLAN.md", ROOT / "probe_runner.py", ROOT / "run_probe.py"]
    paths += [ROOT / TASK / name for name in ("tb.sv", "positive.sv", "negative.sv")]
    paths += [ROOT.parent / "input" / name for name in
              ("prompt.txt", "candidate.sv", "provenance.json")]
    result = {p.relative_to(ROOT.parent).as_posix(): sha256(p) for p in paths}
    result["pinned_r2_helper"] = sha256(helper_path)
    if result["pinned_r2_helper"] != HELPER_SHA256:
        raise ValueError("pinned R2 helper changed")
    if result["input/prompt.txt"] != PROMPT_SHA256:
        raise ValueError("raw prompt changed")
    if result["input/candidate.sv"] != CANDIDATE_SHA256:
        raise ValueError("raw archived candidate changed")
    return result


def run_validation(helper_path, outdir):
    helper_path = Path(helper_path).resolve()
    helper = load_helper(helper_path)
    assets = frozen_assets(helper_path)
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "task": TASK, "complete": False,
              "controls_valid": False, "semantic_mismatch_observed": False,
              "helper_sha256": HELPER_SHA256, "frozen_assets": assets,
              "official_inputs_read": False, "model_calls": 0,
              "official_judgments": 0, "candidates": {}}

    def one(label, candidate):
        if frozen_assets(helper_path) != assets:
            raise ValueError("frozen R3 asset changed before " + label)
        row = helper.probe_candidate(TASK, candidate, outdir / label)
        if frozen_assets(helper_path) != assets:
            raise ValueError("frozen R3 asset changed after " + label)
        result["candidates"][label] = row
        return row

    positive = one("positive", ROOT / TASK / "positive.sv")
    negative = one("negative", ROOT / TASK / "negative.sv")
    result["controls_valid"] = (
        positive["status"] == "pass" and positive["checks"] == CHECKS
        and negative["status"] == "fail" and negative["checks"] == CHECKS
        and negative["failure_kind"] == "semantic_mismatch")
    if result["controls_valid"]:
        archived = one("archived", ROOT.parent / "input" / "candidate.sv")
        result["semantic_mismatch_observed"] = (
            archived["status"] == "fail"
            and archived["failure_kind"] == "semantic_mismatch")
        # This count supports the measured semantic mismatch only. Inspect the
        # preserved R3_MISMATCH lines before attributing its precise boundary.
        result["complete"] = archived["status"] in ("pass", "fail")
    result["assets_unchanged"] = frozen_assets(helper_path) == assets
    result["valid"] = (result["controls_valid"] and result["complete"]
                       and result["assets_unchanged"]
                       and result["candidates"]["archived"]["failure_kind"]
                       in (None, "semantic_mismatch"))
    helper._write_json(outdir / "validation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, default=ROOT / "probe_runner.py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run_validation(args.helper, args.out)
    print(json.dumps({"valid": result["valid"],
                      "controls_valid": result["controls_valid"],
                      "semantic_mismatch_observed": result["semantic_mismatch_observed"],
                      "candidates": {label: {key: row[key] for key in
                          ("status", "failure_kind", "checks", "mismatches")}
                          for label, row in result["candidates"].items()}}, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
