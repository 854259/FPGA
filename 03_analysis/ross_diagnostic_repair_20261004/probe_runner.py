#!/usr/bin/env python3
"""Small, prompt-derived R2 probes. No official testbench or reference inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
TASK_CHECKS = {"Prob115_shift18": 31, "Prob042_vector4": 256,
               "Prob055_conditional": 4096}
STAGE_TIMEOUT_S = 60
IS_POSIX = os.name == "posix"
ENVIRONMENT_ERROR = re.compile(
    r"(license checkout failed|failed to check out.{0,40}license|"
    r"no valid license|flexnet licensing error|segmentation fault|"
    r"cannot open shared object file|no space left on device)", re.I)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_assets():
    """Files which determine the probes and their positive/negative controls."""
    paths = [ROOT / "probe_runner.py"]
    paths += [ROOT / task / name for task in TASK_CHECKS
              for name in ("tb.sv", "positive.sv", "negative.sv")]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in paths}


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def _kill_owned_group(proc, sig):
    # start_new_session=True gave this child its own process group. No process
    # discovery or shared PID selection is used; descendants inherit this group.
    try:
        os.killpg(proc.pid, sig)
        return True
    except ProcessLookupError:
        return False


def _run_stage(name, argv, outdir):
    log = outdir / (name + ".log")
    started = time.monotonic()
    result = {"name": name, "argv": argv, "timeout": False,
              "returncode": None, "launch_error": None, "group_signals": []}
    with log.open("xb") as stream:
        try:
            proc = subprocess.Popen(argv, cwd=outdir, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        except OSError as exc:
            result["launch_error"] = str(exc)
            stream.write((str(exc) + "\n").encode("utf-8", errors="replace"))
        else:
            try:
                proc.wait(timeout=STAGE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                result["timeout"] = True
                if _kill_owned_group(proc, signal.SIGTERM):
                    result["group_signals"].append("SIGTERM")
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                # Kill any remaining children in this owned group, even if the
                # direct child exited on TERM. Never signal the shared model.
                if _kill_owned_group(proc, signal.SIGKILL):
                    result["group_signals"].append("SIGKILL")
                proc.wait(timeout=3)
            result["returncode"] = proc.returncode
    result.update(elapsed_s=round(time.monotonic() - started, 6),
                  log=str(log), log_sha256=sha256(log), log_bytes=log.stat().st_size)
    return result


def _parse_summary(text, task):
    matches = re.findall(
        r"^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$",
        text, re.M)
    if len(matches) != 1:
        raise ValueError("expected exactly one completed probe summary")
    found_task, checks, mismatches = matches[0]
    checks, mismatches = int(checks), int(mismatches)
    if found_task != task or checks != TASK_CHECKS[task] or not 0 <= mismatches <= checks:
        raise ValueError("probe task/counts disagree with the frozen contract")
    return checks, mismatches


def probe_candidate(task, solution, outdir):
    """Run xvlog/xelab/xsim in a new directory; return and save result.json.

    A semantic failure requires successful simulation and an exact completed
    summary. Compile/elaboration failures are candidate failures, but cannot
    validate a negative control. Launch/timeout/license/protocol failures are
    environment_error and must not be silently treated as semantic failures.
    """
    if task not in TASK_CHECKS:
        raise ValueError("unsupported probe task: " + str(task))
    solution, outdir = Path(solution).resolve(), Path(outdir).resolve()
    tb = ROOT / task / "tb.sv"
    original_hashes = {"solution_sha256": sha256(solution),
                       "tb_sha256": sha256(tb),
                       "runner_sha256": sha256(ROOT / "probe_runner.py")}
    outdir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(solution, outdir / "dut.sv")
    shutil.copyfile(tb, outdir / "tb.sv")
    result = {"schema_version": 1, "task": task, "outdir": str(outdir),
              "status": "environment_error", "failure_kind": None,
              "checks": None, "mismatches": None, "stages": [],
              **original_hashes}

    def finish(status, kind):
        current = {"solution_sha256": sha256(solution), "tb_sha256": sha256(tb),
                   "runner_sha256": sha256(ROOT / "probe_runner.py")}
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
        stage = _run_stage(name, argv, outdir)
        result["stages"].append(stage)
        text = Path(stage["log"]).read_text(encoding="utf-8", errors="replace")
        if stage["launch_error"] or stage["timeout"] or ENVIRONMENT_ERROR.search(text):
            return finish("environment_error", name + "_environment_error")
        if stage["returncode"] != 0:
            return finish("fail" if name != "xsim" else "environment_error",
                          name + "_failed")
    try:
        result["checks"], result["mismatches"] = _parse_summary(text, task)
    except ValueError as exc:
        result["protocol_error"] = str(exc)
        return finish("environment_error", "probe_protocol_error")
    return finish("pass" if result["mismatches"] == 0 else "fail",
                  None if result["mismatches"] == 0 else "semantic_mismatch")


def validate_controls(outdir):
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=False)
    assets = frozen_assets()
    result = {"schema_version": 1, "complete": False, "valid": False,
              "probe_files": assets, "tasks": {}}
    for task in TASK_CHECKS:
        positive = probe_candidate(task, ROOT / task / "positive.sv",
                                   outdir / task / "positive")
        negative = probe_candidate(task, ROOT / task / "negative.sv",
                                   outdir / task / "negative")
        valid = (positive["status"] == "pass" and negative["status"] == "fail"
                 and negative["failure_kind"] == "semantic_mismatch")
        result["tasks"][task] = {"positive": positive, "negative": negative,
                                  "valid": valid}
    result["complete"] = True
    result["assets_unchanged"] = assets == frozen_assets()
    result["valid"] = result["assets_unchanged"] and all(
        row["valid"] for row in result["tasks"].values())
    _write_json(outdir / "controls_validation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validation = sub.add_parser("validate-controls")
    validation.add_argument("--out", type=Path, required=True)
    single = sub.add_parser("candidate")
    single.add_argument("--task", choices=TASK_CHECKS, required=True)
    single.add_argument("--solution", type=Path, required=True)
    single.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-controls":
        result = validate_controls(args.out)
        print(json.dumps({"valid": result["valid"], "tasks": {
            task: {"valid": row["valid"],
                   "positive": [row["positive"]["status"], row["positive"]["mismatches"]],
                   "negative": [row["negative"]["status"], row["negative"]["mismatches"]]}
            for task, row in result["tasks"].items()}}, indent=2))
        return 0 if result["valid"] else 1
    result = probe_candidate(args.task, args.solution, args.out)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
