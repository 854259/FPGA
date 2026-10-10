#!/usr/bin/env python3
"""UNRUN checkpoint O/C/D pilot; execute only through the AMD resource guard."""
from __future__ import annotations

import argparse
import ctypes
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PACKAGE = HERE.parent / "package"
MANIFEST = HERE / "inputs_manifest.json"
INHERITED_ORACLE = REPO / "03_analysis/r2_signedness_20261003/probes/probe_runner.py"
BUDGET = {"llm_cap_s": 20, "compile_cap_s": 5, "cleanup_reserve_s": 6, "admission_s": 31}
ORDER = ("O0", "D0", "C0", "C1", "D1", "O1")
MODES = {"O": "off", "C": "control", "D": "checklist"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen():
    manifest = read(MANIFEST)
    for relative, digest in manifest["files"].items():
        if sha(REPO / relative) != digest:
            raise RuntimeError("frozen source mismatch: " + relative)
    return manifest


def model_identity(pid):
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] in ("Z", "X"):
        raise RuntimeError("model process is not alive")
    return {"pid": pid, "starttime": fields[19], "exe": Path(os.readlink(root / "exe")).name,
            "command_sha256": hashlib.sha256((root / "cmdline").read_bytes()).hexdigest()}


def tree_hashes(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def check_resource(path, kit, first=False):
    record = read(path)
    if record.get("schema_version") != 1 or record.get("host") != socket.gethostname() or record.get("resource_idle") is not True:
        raise RuntimeError("resource admission does not match this idle host")
    if first:
        age = (datetime.datetime.now(datetime.timezone.utc) -
               datetime.datetime.fromisoformat(record["checked_at_utc"])).total_seconds()
        if not 0 <= age <= 120:
            raise RuntimeError("resource admission is stale")
    lock = Path(record["slot_lock_path"])
    if sha(lock) != record["slot_lock_sha256"] or lock.read_text().splitlines()[0] != record["slot_owner"]:
        raise RuntimeError("shared slot ownership changed")
    if model_identity(record["model_pid"]) != record["model_identity"]:
        raise RuntimeError("shared model identity changed")
    protected = record["protected"]
    for key, directory in (("package", "submission"), ("official", "official_reference"), ("tasks", "bench/tasks_veval")):
        if tree_hashes(kit / directory) != protected[key]:
            raise RuntimeError("protected files changed: " + key)
    baseline = {str(kit / "submission" / path): digest for path, digest in protected["baseline"].items()}
    official = {str(kit / "official_reference" / path): digest for path, digest in protected["official"].items()}
    if record["baseline_hashes"] != baseline or record["official_hashes"] != official:
        raise RuntimeError("inconsistent protected admission")
    for relative, digest in protected["baseline"].items():
        if sha(kit / "submission" / relative) != digest:
            raise RuntimeError("official baseline changed")
    return record


def model_idle(base, model):
    """Read shared-server telemetry; never restart it or clear its cache."""
    def get(path):
        with urllib.request.urlopen(base[:-3] + path, timeout=5) as response:
            return json.load(response)
    health, models, slots = get("/health"), get("/v1/models"), get("/slots")
    if health.get("status") != "ok" or model not in [item.get("id") for item in models.get("data", [])]:
        raise RuntimeError("shared model health or model alias changed")
    if not isinstance(slots, list) or not slots or any(slot.get("is_processing") is not False for slot in slots):
        raise RuntimeError("shared model slots are busy or idle telemetry is unavailable")
    return {"model": model, "health_status": health["status"], "models": models,
            "slot_count": len(slots), "processing_slots": 0}


def report_gate(engineering_path, forced_path, manifest):
    engineering, forced = read(engineering_path), read(forced_path)
    for report, schema, phase in (
            (engineering, "selective_runtime_linux_preflight_v1", "engineering"),
            (forced, "selective_runtime_forced_correct_v1", "functional")):
        if any(report.get(key) != value for key, value in
               {"schema": schema, "phase": phase, "complete": True, "passed": True, "real_compiler": True}.items()):
            raise RuntimeError("incomplete or incompatible prerequisite report: " + phase)
        if report.get("source_runtime_sha256") != manifest["runtime_sha256"]:
            raise RuntimeError("prerequisite runtime mismatch")
        if report.get("package_files") != manifest["package_files"]:
            raise RuntimeError("prerequisite package mismatch")
        expected_inputs = {path: digest for path, digest in manifest["files"].items()
                           if "/r2_signedness_20261003/input/Prob115_shift18/" in path}
        if report.get("input_files") != expected_inputs:
            raise RuntimeError("prerequisite known checkpoint mismatch")
        if report.get("default_review_budget") != BUDGET:
            raise RuntimeError("prerequisite uses different default budget")
        if report.get("pending_until_execution") is True:
            raise RuntimeError("static prerequisite cannot admit a real experiment")
        if report.get("host") != socket.gethostname():
            raise RuntimeError("prerequisite report came from a different host")
        if report.get("protected_files_unchanged") is not True:
            raise RuntimeError("prerequisite protected files changed")
        configured = os.environ.get("VIVADO_BIN")
        version = report.get("vivado", {})
        if not configured or version.get("rc") != 0 or Path(version.get("bin", "")).resolve() != Path(configured).resolve():
            raise RuntimeError("prerequisite and current real Vivado installation differ")
        if any(not (Path(configured) / name).is_file() for name in ("vivado", "xvlog", "xelab", "xsim")):
            raise RuntimeError("current real Vivado tool is missing")
    if engineering.get("linux") is not True or engineering.get("protected_files_unchanged") is not True or engineering.get("cleanup_verified") is not True:
        raise RuntimeError("Linux engineering protection or cleanup is unverified")
    cases, process_cases = engineering.get("cases"), engineering.get("process_cases")
    if not cases or not process_cases or not all(row.get("passed") is True for row in cases + process_cases):
        raise RuntimeError("engineering cases are missing or failed")
    if not any("parent" in row.get("topology", "") and "exit" in row.get("topology", "") for row in process_cases):
        raise RuntimeError("parent-exits-first cleanup evidence is missing")
    if any(row.get("outer_alive") for row in process_cases):
        raise RuntimeError("engineering process descendants remain alive")
    expected_cases = {"correct_review", "syntax_rejected", "budget_below_31", "budget_exact_31",
                      "review_client_timeout", "declaration_repair_exit", "last_normal_request"}
    if {row.get("case_id") for row in cases} != expected_cases:
        raise RuntimeError("engineering branch coverage is incomplete")
    if {row.get("topology") for row in process_cases} != {"live_parent_child", "parent_fast_exit", "other_thread"}:
        raise RuntimeError("engineering process topology coverage is incomplete")
    if any(not row.get("checks") or not all(value is True for value in row["checks"].values()) for row in cases + process_cases):
        raise RuntimeError("engineering case checks are incomplete")
    if any(not row.get("outer_snapshot") or any(item.get("observed_state") not in ("absent", "identity_reused")
                                                for item in row["outer_snapshot"]) for row in process_cases):
        raise RuntimeError("engineering process cleanup snapshots are unverified")
    if forced.get("real_oracle") is not True or forced.get("fake_model") is not True:
        raise RuntimeError("forced-correct experiment provenance is missing")
    if forced.get("engineering_report_sha256") != sha(engineering_path):
        raise RuntimeError("forced-correct report is bound to another engineering run")
    # A passed forced experiment can reveal a real regression; do not relabel that as protection.
    expected_forced = {"cleanup_verified": True, "oracle_assets_unchanged": True, "expected_outcome_met": True,
                       "status": "functional_regression_detected", "deployment_blocked": True,
                       "regression_protection": False}
    if any(forced.get(key) != value for key, value in expected_forced.items()):
        raise RuntimeError("forced-correct regression evidence is incomplete")
    forced_cases = forced.get("cases", [])
    if ({row.get("case_id") for row in forced_cases} != {"normal_correct_bypass", "forced_correct_review"}
            or any(row.get("passed") is not True or not row.get("checks")
                   or not all(value is True for value in row["checks"].values()) for row in forced_cases)):
        raise RuntimeError("forced-correct experiment conclusion is missing")
    oracle = forced.get("oracle_results", {})
    if (oracle.get("original", {}).get("status") != "pass" or oracle.get("original", {}).get("mismatches") != 0
            or oracle.get("candidate", {}).get("status") != "fail"
            or oracle.get("candidate", {}).get("failure_kind") != "semantic_mismatch"
            or not oracle.get("candidate", {}).get("mismatches", 0)):
        raise RuntimeError("forced-correct original and negative oracle controls are unverified")
    if (oracle.get("final", {}).get("status") != "fail"
            or oracle.get("final", {}).get("failure_kind") != "semantic_mismatch"
            or not oracle.get("final", {}).get("mismatches", 0)
            or any(result.get("inputs_unchanged") is not True for result in oracle.values())):
        raise RuntimeError("forced-correct final regression is unverified")
    forced_commit = next(row["review_commit"] for row in forced_cases if row["case_id"] == "forced_correct_review")
    if forced_commit.get("status") != "accepted":
        raise RuntimeError("forced-correct changed candidate was not accepted")
    # All referenced log/source receipts must still match their observed bytes.
    receipts = 0
    def verify(value):
        nonlocal receipts
        if isinstance(value, list):
            for item in value:
                verify(item)
        elif isinstance(value, dict):
            for key, digest in value.items():
                if key.endswith("_sha256") and isinstance(digest, str):
                    path = value.get(key[:-7] + "_path") or value.get(key[:-7])
                    if isinstance(path, str):
                        if not Path(path).is_file():
                            raise RuntimeError("prerequisite receipt missing: " + path)
                        if sha(path) != digest:
                            raise RuntimeError("prerequisite receipt changed: " + path)
                        receipts += 1
                verify(digest)
    verify(engineering)
    verify(forced)
    if receipts < 4:
        raise RuntimeError("prerequisite reports lack verifiable file receipts")
    return {"engineering_report_sha256": sha(engineering_path), "forced_report_sha256": sha(forced_path),
            "functional_regression_protection": forced["regression_protection"], "verified_receipts": receipts}


def endpoint(value):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.username or parsed.password or parsed.path.rstrip("/") != "/v1" or parsed.query or parsed.fragment:
        raise ValueError("explicit loopback /v1 endpoint is required")
    return value.rstrip("/")


def row_worker(args):
    if sys.platform != "linux":
        raise RuntimeError("Linux required")
    manifest = frozen()
    if args.label not in ORDER or not any(subject["candidate"] == args.candidate and subject["prompt"] == args.prompt
                                         for subject in manifest["subjects"]):
        raise RuntimeError("row inputs are outside the frozen checkpoint set")
    report_gate(args.engineering_report, args.forced_report, manifest)
    admission = check_resource(args.resource_check, args.kit.resolve())
    if admission.get("llm_base_url") != endpoint(args.endpoint) or admission.get("model_name") != args.model:
        raise RuntimeError("row endpoint/model mismatch with owned resource admission")
    os.environ.update(LLM_BASE_URL=endpoint(args.endpoint), MODEL_NAME=args.model,
                      RTL_PROFILE="submission", RTL_REVIEW_MODE=MODES[args.label[0]],
                      RTL_REVIEW_LLM_CAP_S="20", RTL_REVIEW_COMPILE_CAP_S="5",
                      RTL_REVIEW_CLEANUP_RESERVE_S="6", RTL_REVIEW_SOCKET_CAP_S="20",
                      RTL_TEMPERATURE="0", RTL_MAX_TOKENS="8192")
    sys.path.insert(0, str(PACKAGE / "agent"))
    runtime = load_module("paired_frozen_runtime", PACKAGE / "agent/runtime.py")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = (REPO / args.candidate).read_text(encoding="utf-8")
    prompt = (REPO / args.prompt).read_text(encoding="utf-8")
    runtime.write(out / "solution.v", source)
    runtime.write(out / "trace.jsonl", "")
    work = out / "initial_compile"
    work.mkdir()
    runtime.write(work / "candidate.sv", source)
    tool = runtime.vivado_tool("xvlog")
    started = time.monotonic()
    if not tool:
        raise RuntimeError("real xvlog unavailable")
    compiled = runtime._bounded_command([tool, "--sv", str(work / "candidate.sv")],
                                        work, work / "xvlog.log", 5, 6)
    runtime.trace(out, "checkpoint_compile", **compiled, log_sha256=sha(work / "xvlog.log"))
    if compiled["timeout"] or compiled["rc"] != 0:
        save(out / "row.json", {"valid": False, "error": "checkpoint_compile_failed", "compile": compiled})
        return 1
    skill, repair_skill = runtime.skill_texts()
    if args.label[0] != "O":
        model_idle(args.endpoint, args.model)
    finish_start = time.monotonic()
    runtime.finish_compiled(prompt, source, out, 0, 1, args.model, skill, repair_skill,
                            finish_start + 60, 0)
    events = [json.loads(line) for line in (out / "trace.jsonl").read_text().splitlines()]
    select = next((e for e in events if e["tool"] == "review_select"), {})
    budget = next((e for e in events if e["tool"] == "review_budget"), {})
    commit = next((e for e in reversed(events) if e["tool"] == "review_commit"), {})
    response_path = out / "review/response.json"
    response = read(response_path) if response_path.is_file() else {}
    payload = response.get("payload")
    choice = (payload.get("choices") or [{}])[0] if isinstance(payload, dict) else {}
    payload_object = payload if isinstance(payload, dict) else {}
    usage = payload_object.get("usage") or {}
    attempts = sum(e["tool"] == "review_llm_start" for e in events)
    row = {"valid": bool(commit), "label": args.label, "mode": MODES[args.label[0]],
           "selector": select, "budget": budget, "commit": commit,
           "client_attempts": attempts,
           "http_client_request_attempted": response.get("request_attempted", "unknown"),
           "response_received": isinstance(payload, dict),
           "service_request_receipt": "unknown_without_server_log",
           "observed_response_count": int(isinstance(payload, dict)),
           "response_sha256": sha(response_path) if response_path.is_file() else None,
           "actual_response": str(response_path) if response_path.is_file() else None,
           "usage": usage, "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
           "cache": {key: value for key, value in payload_object.items() if "cache" in key.lower() or key == "timings"} or "unknown",
           "finish": choice.get("finish_reason"), "compile": compiled,
           "finish_elapsed_s": time.monotonic() - finish_start,
           "checkpoint_elapsed_s": time.monotonic() - started,
           "first_generation_elapsed_s": "excluded",
           "original_sha256": hashlib.sha256(source.encode()).hexdigest(),
           "final_sha256": sha(out / "solution.v"),
           "candidate_sha256": commit.get("candidate_sha256"),
           "trace_sha256": sha(out / "trace.jsonl")}
    save(out / "row.json", row)
    return 0 if row["valid"] else 1


def owned_command(argv, cwd, log, seconds, *, deadline=None, cleanup_seconds=10.):
    """Charge launch/wait to one monotonic deadline; clean only the owned group.

    Callers with an earlier parent start must pass its absolute deadline. Cleanup
    shares one reserve (at most 10 seconds), never a fresh reserve per operation.
    A delayed OS/Popen call cannot be preempted here: late returns fail closed.
    Linux callers must enable child-subreaping before invoking this function.
    """
    started = time.monotonic()
    for name, value in (("seconds", seconds), ("cleanup_seconds", cleanup_seconds),
                        ("deadline", deadline)):
        if name == "deadline" and value is None:
            continue
        try:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid or (name != "deadline" and value <= 0):
            raise ValueError(name + " must be a finite " + ("number" if name == "deadline" else "positive number"))
    if cleanup_seconds > 10:
        raise ValueError("cleanup_seconds cannot exceed the 10 second total reserve")
    deadline = min(started + seconds, deadline) if deadline is not None else started + seconds
    proc = None
    alive = []
    phase = "run"
    cancel_signal = None
    cleanup_started = None
    cleanup_deadline = None
    result = {"timeout": False, "launch_error": None, "returncode": None, "group_signals": []}

    def cancelled(signum, frame):
        nonlocal cancel_signal
        cancel_signal = signum
        # Defer Python's exception until Popen hands us ownership, and keep a
        # second cancellation from interrupting bounded cleanup. No child mask.
        if phase in ("launch", "cleanup"):
            return
        raise InterruptedError("owned stage cancelled by signal " + str(signum))

    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with Path(log).open("xb") as stream:
            try:
                if time.monotonic() >= deadline:
                    result["timeout"] = True
                else:
                    phase = "launch"
                    try:
                        proc = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL, start_new_session=True)
                    finally:
                        phase = "run"
                    if cancel_signal is not None:
                        raise InterruptedError("owned stage cancelled by signal " + str(cancel_signal))
                    proc.wait(timeout=max(0., deadline - time.monotonic()))
                    result["timeout"] = time.monotonic() >= deadline
            except subprocess.TimeoutExpired:
                result["timeout"] = True
            except InterruptedError:
                raise
            except OSError as exc:
                result["launch_error"] = str(exc)
            finally:
                phase = "cleanup"
                cleanup_started = time.monotonic()
                cleanup_deadline = min(cleanup_started, deadline) + cleanup_seconds
                if proc is not None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                        result["group_signals"].append("SIGKILL")
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=max(0., cleanup_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
                    while True:
                        # Reap the leader through Popen first, then only adopted
                        # children in this exact owned PG, within the SAME end.
                        if proc.poll() is not None:
                            try:
                                while os.waitpid(-proc.pid, os.WNOHANG)[0]:
                                    pass
                            except ChildProcessError:
                                pass
                        alive = []
                        for directory in Path("/proc").glob("[0-9]*"):
                            try:
                                fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
                                if int(fields[2]) == proc.pid:
                                    alive.append(int(directory.name))
                            except (OSError, IndexError, ValueError):
                                continue
                        if not alive and proc.returncode is not None:
                            break
                        remaining = cleanup_deadline - time.monotonic()
                        if remaining <= 0:
                            raise RuntimeError("owned process cleanup deadline exceeded: " + str(alive))
                        time.sleep(min(.025, remaining))
                    result["returncode"] = proc.returncode
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if cancel_signal is not None:
        raise InterruptedError("owned stage cancelled by signal " + str(cancel_signal))
    return {**result, "elapsed_s": time.monotonic() - started, "remaining_live_group": alive,
            "started_monotonic": started, "deadline_monotonic": deadline,
            "cleanup_started_monotonic": cleanup_started, "cleanup_deadline_monotonic": cleanup_deadline,
            "log": str(log), "log_sha256": sha(log), "log_bytes": Path(log).stat().st_size}


def run_owned_row(args, subject, label, out):
    argv = [sys.executable, "-B", str(HERE / "paired_checkpoint.py"), "_row",
            "--candidate", subject["candidate"], "--prompt", subject["prompt"], "--label", label,
            "--endpoint", args.endpoint, "--model", args.model, "--out", str(out),
            "--engineering-report", str(args.engineering_report), "--forced-report", str(args.forced_report),
            "--resource-check", str(args.resource_check), "--kit", str(args.kit)]
    supervision = owned_command(argv, REPO, out.parent / (out.name + ".supervisor.log"), 77)
    result = read(out / "row.json") if (out / "row.json").is_file() else {"valid": False}
    result.update(supervisor=supervision)
    if supervision["returncode"] != 0 or supervision["timeout"] or not result["valid"]:
        raise RuntimeError("row failed; preserve its output and do not resample: " + str(out))
    return result


def oracle_runner(task):
    runner = load_module("paired_offline_oracle", INHERITED_ORACLE)
    runner.ROOT = (REPO / task["tb"]).parent.parent
    runner.TASK_CHECKS = {task["task"]: task["checks"]}
    # The inherited helper couples its task root with its own script identity.
    # Point only that identity read to the file actually imported, including new task roots.
    original_sha = runner.sha256
    identity_alias = runner.ROOT / "probe_runner.py"
    runner.sha256 = lambda path: sha(INHERITED_ORACLE) if Path(path) == identity_alias else original_sha(path)
    def stage(name, argv, outdir):
        command = [str(Path(os.environ["VIVADO_BIN"]) / argv[0]), *argv[1:]]
        return {"name": name, "argv": command, **owned_command(command, outdir, outdir / (name + ".log"), 60)}
    # Keep the frozen parser and testbench; close the old runner's success-exit cleanup gap.
    runner._run_stage = stage
    return runner


def oracle(task, solution, out):
    result = oracle_runner(task).probe_candidate(task["task"], solution, out)
    result.update(inherited_runner_path=str(INHERITED_ORACLE), inherited_runner_sha256=sha(INHERITED_ORACLE),
                  oracle_adapter_path=str(HERE / "paired_checkpoint.py"), oracle_adapter_sha256=sha(HERE / "paired_checkpoint.py"),
                  inherited_result_path=str(out / "result.json"), inherited_result_sha256=sha(out / "result.json"))
    save(out / "adapter_receipt.json", result)
    return result


def run(args):
    if sys.platform != "linux":
        raise RuntimeError("Linux required")
    args.endpoint = endpoint(args.endpoint)
    args.kit = args.kit.resolve()
    manifest = frozen()
    gates = report_gate(args.engineering_report, args.forced_report, manifest)
    resource = check_resource(args.resource_check, args.kit, first=True)
    if resource.get("llm_base_url") != args.endpoint or resource.get("model_name") != args.model:
        raise RuntimeError("endpoint/model mismatch with owned resource admission")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {"schema": "selective_runtime_checkpoint_paired_v1", "complete": False, "verified": False,
               "scope": "constructed mechanism transfer plus known development checkpoints; no initial generation",
               "manifest_sha256": sha(MANIFEST), "endpoint": args.endpoint, "model": args.model,
               "resource_check_sha256": sha(args.resource_check), "model_identity": resource["model_identity"],
               "default_review_budget": BUDGET, "order": ORDER, **gates, "controls": {}, "rows": []}
    summary["real_tools"] = {str(Path(os.environ["VIVADO_BIN"]) / name): sha(Path(os.environ["VIVADO_BIN"]) / name)
                             for name in ("vivado", "xvlog", "xelab", "xsim")}
    save(out / "start.json", summary)
    try:
        # Oracle controls are validated before calling the shared model; no outcomes enter prompts.
        for task in manifest["tasks"]:
            rows = {name: oracle(task, REPO / task[name], out / "controls" / task["task"] / name)
                    for name in ("positive", "negative")}
            rows["valid"] = rows["positive"]["status"] == "pass" and rows["negative"]["failure_kind"] == "semantic_mismatch"
            summary["controls"][task["task"]] = rows
        if not all(row["valid"] for row in summary["controls"].values()):
            raise RuntimeError("oracle controls failed: no model requests admitted")
        check_resource(args.resource_check, args.kit)
        telemetry = model_idle(args.endpoint, args.model)
        save(out / "model_telemetry.json", telemetry)
        for subject in manifest["subjects"]:
            for label in ORDER:
                frozen()
                check_resource(args.resource_check, args.kit)
                model_idle(args.endpoint, args.model)
                row_out = out / "generated" / subject["id"] / label
                row_out.parent.mkdir(parents=True, exist_ok=True)
                row = run_owned_row(args, subject, label, row_out)
                row.update(subject=subject["id"], task=subject["task"], family=subject["family"],
                           solution=str(row_out / "solution.v"))
                summary["rows"].append(row)
        save(out / "generation_complete.json", {"rows": len(summary["rows"]), "model_generation_complete": True,
                                               "actual_subject_grading_started": False})
        # Only after all 60 outputs are frozen do any actual checkpoint outcomes get graded.
        tasks = {task["task"]: task for task in manifest["tasks"]}
        for row in summary["rows"]:
            row["oracle"] = oracle(tasks[row["task"]], Path(row["solution"]),
                                   out / "grades" / row["subject"] / row["label"])
        pairs = []
        checklist_vs_control = []
        for subject in manifest["subjects"]:
            rows = {row["label"]: row for row in summary["rows"] if row["subject"] == subject["id"]}
            for repeat in (0, 1):
                original = rows["O" + str(repeat)]
                for mode in ("C", "D"):
                    reviewed = rows[mode + str(repeat)]
                    statuses = (original["oracle"]["status"], reviewed["oracle"]["status"])
                    valid = all(status in ("pass", "fail") for status in statuses)
                    pairs.append({"subject": subject["id"], "repeat": repeat, "mode": mode,
                                  "valid": valid, "repair": valid and statuses == ("fail", "pass"),
                                  "regression": valid and statuses == ("pass", "fail"),
                                  "statuses": statuses, "extra_client_attempts": reviewed["client_attempts"],
                                  "extra_observed_responses": reviewed["observed_response_count"],
                                  "extra_checkpoint_s": reviewed["checkpoint_elapsed_s"] - original["checkpoint_elapsed_s"],
                                  "extra_finish_s": reviewed["finish_elapsed_s"] - original["finish_elapsed_s"]})
                control, targeted = rows["C" + str(repeat)], rows["D" + str(repeat)]
                checklist_vs_control.append({"subject": subject["id"], "repeat": repeat,
                                             "checkpoint_s_D_minus_C": targeted["checkpoint_elapsed_s"] - control["checkpoint_elapsed_s"],
                                             "finish_s_D_minus_C": targeted["finish_elapsed_s"] - control["finish_elapsed_s"],
                                             "client_attempts_D_minus_C": targeted["client_attempts"] - control["client_attempts"],
                                             "observed_responses_D_minus_C": targeted["observed_response_count"] - control["observed_response_count"]})
        summary["pairs"] = pairs
        summary["checklist_vs_control"] = checklist_vs_control
        summary["totals"] = {mode: {"valid_pairs": sum(p["valid"] for p in pairs if p["mode"] == mode),
                                    "repairs": sum(p["repair"] for p in pairs if p["mode"] == mode),
                                    "regressions": sum(p["regression"] for p in pairs if p["mode"] == mode),
                                    "extra_client_attempts": sum(p["extra_client_attempts"] for p in pairs if p["mode"] == mode),
                                    "extra_observed_responses": sum(p["extra_observed_responses"] for p in pairs if p["mode"] == mode),
                                    "extra_checkpoint_s": sum(p["extra_checkpoint_s"] for p in pairs if p["mode"] == mode),
                                    "extra_finish_s": sum(p["extra_finish_s"] for p in pairs if p["mode"] == mode)}
                             for mode in ("C", "D")}
        summary["totals"]["D_minus_C"] = {key: sum(row[key] for row in checklist_vs_control)
                                                 for key in ("checkpoint_s_D_minus_C", "finish_s_D_minus_C",
                                                             "client_attempts_D_minus_C", "observed_responses_D_minus_C")}
        summary["assets_unchanged"] = frozen()["files"] == manifest["files"]
        check_resource(args.resource_check, args.kit)
        model_idle(args.endpoint, args.model)
        if any(sha(path) != digest for path, digest in summary["real_tools"].items()):
            raise RuntimeError("real Vivado tools changed during the checkpoint run")
        summary.update(complete=True, verified=summary["assets_unchanged"] and all(p["valid"] for p in pairs),
                       full156_gain="unverified", deployment_blocked=True)
    except BaseException as exc:
        summary["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        # Cancellation between stages still leaves a partial summary; protect this final write.
        previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            save(out / "summary.json", summary)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0 if summary["complete"] and summary["verified"] else 1


def main():
    if sys.platform != "linux":
        raise SystemExit("Linux required")
    sys.dont_write_bytecode = True
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise SystemExit("owned-stage child subreaper setup failed")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pilot = sub.add_parser("run")
    for name in ("engineering-report", "forced-report", "resource-check", "kit", "out"):
        pilot.add_argument("--" + name, type=Path, required=True)
    pilot.add_argument("--endpoint", required=True)
    pilot.add_argument("--model", required=True)
    internal = sub.add_parser("_row")
    for name in ("candidate", "prompt", "label", "endpoint", "model"):
        internal.add_argument("--" + name, required=True)
    internal.add_argument("--out", type=Path, required=True)
    for name in ("engineering-report", "forced-report", "resource-check", "kit"):
        internal.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    def cancelled(signum, frame):
        raise InterruptedError("checkpoint harness cancelled by signal " + str(signum))
    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return row_worker(args) if args.command == "_row" else run(args)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
