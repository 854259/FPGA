"""Portable checker for a model candidate and a prompt-derived testbench.

Extracted from the frozen probe_runner.py (SHA-256
954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0).
Classification and simulator commands are preserved. The caller supplies the
generated testbench, its expected check count, and the existing deadline-owned
stage function. This module does not discover tasks, load references, launch
processes itself, or implement the outer resource/isolation admission.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

IS_POSIX = os.name == "posix"
ENVIRONMENT_ERROR = re.compile(
    r"(license checkout failed|failed to check out.{0,40}license|"
    r"no valid license|flexnet licensing error|segmentation fault|"
    r"cannot open shared object file|no space left on device)", re.I)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def _parse_summary(text, task, expected_checks):
    matches = re.findall(
        r"^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$",
        text, re.M)
    if len(matches) != 1:
        raise ValueError("expected exactly one completed probe summary")
    found_task, checks, mismatches = matches[0]
    checks, mismatches = int(checks), int(mismatches)
    if found_task != task or checks != expected_checks or not 0 <= mismatches <= checks:
        raise ValueError("probe task/counts disagree with the frozen contract")
    return checks, mismatches


def probe_candidate(task, solution, testbench, outdir, checks, run_stage):
    """Run xvlog/xelab/xsim in a new directory; return and save result.json.

    A semantic failure requires successful simulation and an exact completed
    summary. Compile/elaboration failures are candidate failures, but cannot
    validate a negative control. Launch/timeout/license/protocol failures are
    environment_error and must not be silently treated as semantic failures.
    """
    if not isinstance(task, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,80}", task):
        raise ValueError("unsafe probe label")
    if type(checks) is not int or checks <= 0:
        raise ValueError("positive prompt-derived check count required")
    if not callable(run_stage):
        raise ValueError("owned stage runner required")
    solution, outdir = Path(solution).resolve(), Path(outdir).resolve()
    tb = Path(testbench).resolve()
    original_hashes = {"solution_sha256": sha256(solution),
                       "tb_sha256": sha256(tb),
                       "runner_sha256": sha256(__file__)}
    outdir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(solution, outdir / "dut.sv")
    shutil.copyfile(tb, outdir / "tb.sv")
    result = {"schema_version": 1, "task": task, "outdir": str(outdir),
              "status": "environment_error", "failure_kind": None,
              "checks": None, "mismatches": None, "stages": [],
              **original_hashes}

    def finish(status, kind):
        current = {"solution_sha256": sha256(solution), "tb_sha256": sha256(tb),
                   "runner_sha256": sha256(__file__)}
        result["inputs_unchanged"] = current == original_hashes
        if not result["inputs_unchanged"]:
            status, kind = "environment_error", "input_changed_during_probe"
        result.update(status=status, failure_kind=kind)
        _write_json(outdir / "result.json", result)
        return result

    if not IS_POSIX:
        return finish("environment_error", "linux_required")
    commands = [
        ("xvlog", ["xvlog", "-sv", "--nolog", "dut.sv", "tb.sv"]),
        ("xelab", ["xelab", "R2Probe", "-s", "r2_probe", "--nolog",
                   "-timescale", "1ns/1ps"]),
        ("xsim", ["xsim", "r2_probe", "-runall", "-nolog"]),
    ]
    for name, argv in commands:
        stage = run_stage(name, argv, outdir)
        result["stages"].append(stage)
        text = Path(stage["log"]).read_text(encoding="utf-8", errors="replace")
        if stage["launch_error"] or stage["timeout"] or ENVIRONMENT_ERROR.search(text):
            return finish("environment_error", name + "_environment_error")
        if stage["returncode"] != 0:
            return finish("fail" if name != "xsim" else "environment_error",
                          name + "_failed")
    try:
        result["checks"], result["mismatches"] = _parse_summary(text, task, checks)
    except ValueError as exc:
        result["protocol_error"] = str(exc)
        return finish("environment_error", "probe_protocol_error")
    return finish("pass" if result["mismatches"] == 0 else "fail",
                  None if result["mismatches"] == 0 else "semantic_mismatch")
