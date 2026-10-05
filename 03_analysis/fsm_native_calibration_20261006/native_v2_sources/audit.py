"""Offline packet audit, executed/imported only on AMD. No native/model calls.

Rebuild the fixed38-control decision from immutable physical receipts and logs.
The stage's row, inventory and summary flags are compared, never used as proof.
"""
import argparse
import math
import re
import sys
from pathlib import Path

import calibration as c


def check(value, reason):
    c.require(value, "audit: "+reason)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def assert_names(root, basename, expected):
    actual = {p.relative_to(root).as_posix() for p in root.rglob(basename) if p.is_file()}
    check(actual == set(expected), "unexpected/missing/retried "+basename)


def pinned_packet(root, cases, deps):
    spec = c.read(root/"RUN_SPEC.json")
    check(spec["schema"] == "fsm_native_calibration_frozen_v2", "frozen schema")
    check(type(spec["cloud_root"]) is str and spec["cloud_root"].startswith("/")
          and "\\" not in spec["cloud_root"] and ":" not in spec["cloud_root"], "Linux cloud identity")
    check(cases.resolve() == c.contained(root, spec["case_root_relative"]).resolve(), "packet-contained case root")
    check(spec["planned"] == c.PLANNED and spec["model_requests_max"] == 0
          and spec["expected_native_by_tool"] == c.EXPECTED_NATIVE_BY_TOOL, "fixed38/105/2/0model")
    check(type(spec["stage_timeout_s"]) is int and 0 < spec["stage_timeout_s"] <= 3600
          and type(spec["native_command_timeout_s"]) is int and 0 < spec["native_command_timeout_s"] <= 300
          and type(spec["supervisor_probe_timeout_s"]) in (int, float)
          and 0 < spec["supervisor_probe_timeout_s"] < 1, "absolute command/stage caps")
    check(type(spec["source_hashes"]) is dict and bool(spec["source_hashes"]), "frozen source inventory")
    for name, digest in spec["source_hashes"].items():
        check(c.file_sha(c.contained(root, name)) == digest, "frozen source bytes "+name)
    for module in (c, sys.modules[__name__]):
        name = Path(module.__file__).resolve().relative_to(root).as_posix()
        check(name in spec["source_hashes"], "executed audit source omitted")
    check(spec["dependency_hashes"]["paired_checkpoint.py"] == c.PAIRED_SHA
          and spec["dependency_hashes"]["protected_sources.py"] == c.PROTECTED_HELPER_SHA, "runner pins")
    for name, digest in spec["dependency_hashes"].items():
        check(c.file_sha(c.contained(deps, name)) == digest, "dependency bytes "+name)
    binding = c.read(c.contained(cases, "PREPARATION_BINDING.json"))
    stage_name = Path(__file__).with_name("stage.py").resolve().relative_to(root).as_posix()
    required = {stage_name, "CASE_PLAN.json", "raw_evidence/ENVIRONMENT_CAPTURE.json",
                "raw_evidence/PROTECTED_GROUPS_CAPTURE.json", spec["supervisor_probe_relative"]}
    required |= {c.contained(cases, name).relative_to(root).as_posix()
                 for name in list(binding["private_files"])+["PREPARATION_BINDING.json"]}
    check(required <= spec["source_hashes"].keys(), "case/capture/plan freeze boundary")
    items = c.describe_cases(cases)
    check(c.read(root/"CASE_PLAN.json") == c.plan(items), "independent source/expected recipe replay")
    for item in items:
        base = root/"prepared_cases"/item["label"]
        check((base/"candidate.sv").read_bytes() == item["source"].encode()
              and (base/"tb.sv").read_bytes() == item["tb"].encode()
              and c.read(base/"expected_observations.json") == item["expected_observations"], "prepared bytes")
        check(all((base/name).relative_to(root).as_posix() in spec["source_hashes"]
                  for name in ("candidate.sv", "tb.sv", "expected_observations.json")), "prepared assets frozen")
    return spec, items


def expected_guard_sources(binding):
    check(type(binding["schema"]) is str and binding["schema"].startswith("actual_"), "actual source capture")
    check(binding["model_calls"] == binding["eda_calls"] == 0, "read-only capture")
    groups = {identity: dict(spec_sha256=item["spec_sha256"], source_hashes=item["source_hashes"],
                             source_assets=len(item["source_hashes"]))
              for identity, item in binding["groups"].items()}
    check(binding["source_assets"] == sum(g["source_assets"] for g in groups.values()), "protected count")
    return dict(schema="semantic_edge_protected_source_check_v1", verified=True, groups=groups,
                source_assets=binding["source_assets"], model_calls=0, eda_calls=0)


def guards(root, spec):
    binding = c.read(root/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json")
    sources = expected_guard_sources(binding)
    check(len(sources["groups"]) == spec["protected_group_count"]
          and sources["source_assets"] == spec["protected_source_assets"], "dynamic protected counts")
    resource = c.read(root/"guard/resource_check.json")
    check(resource["schema_version"] == 1 and resource["resource_idle"] is True, "actual own guard admission")
    for key in ("model_identity", "protected", "slot_owner", "slot_lock_path", "llm_base_url", "model_name"):
        check(resource[key] == spec[key], "frozen FIFO/protected/model "+key)
    base = root/"results/guard_receipts"
    paths = [base/(str(index).zfill(4)+".json") for index in range(c.EXPECTED_GUARDS)]
    check({p.name for p in base.iterdir()} == {p.name for p in paths}, "exact216 guards")
    for index, path in enumerate(paths):
        expected = dict(schema="fsm_native_guard_receipt_v2", index=index, resource=resource,
                        protected_sources=sources, resource_sha256=c.file_sha(root/"guard/resource_check.json"))
        check(c.read(path) == expected, "guard replay "+str(index))
    return paths


def environment(root, spec):
    capture = c.read(root/"raw_evidence/ENVIRONMENT_CAPTURE.json")
    preflight = c.read(root/"results/ENVIRONMENT_PREFLIGHT.json")
    expected = dict(schema="fsm_native_environment_preflight_v2", verified=True,
                    compiler_tools={name: spec["compiler_tools"][name] for name in (*c.TOOLS, "vivado")},
                    compiler_env=spec["compiler_env"], udev_files=spec["udev_files"],
                    python_runtime=spec["python_runtime"], full_environment_sha256=preflight["full_environment_sha256"])
    check(preflight == expected and re.fullmatch("[0-9a-f]{64}", preflight["full_environment_sha256"]), "environment preflight")
    check(capture["compiler_tools"] == spec["compiler_tools"] and capture["compiler_env"] == spec["compiler_env"]
          and capture["udev_files"] == spec["udev_files"], "reviewed scoped compiler capture")
    for name in (*c.TOOLS, "vivado"):
        tool = spec["compiler_tools"][name]
        check(tool["path"].startswith("/") and re.fullmatch("[0-9a-f]{64}", tool["sha256"]), "physical tool pin")
    return preflight["full_environment_sha256"]


def cleanup_proof(folder, completion, log, spec):
    check(completion.get("probe_evidence_error") is None, "probe evidence collection failed")
    evidence = completion.get("probe_evidence")
    check(c.probe_cleanup_valid(evidence), "actual original parent/child cleanup")
    identity = c.read(folder/"PROBE_IDENTITY.json")
    check(evidence["identity"] == identity and evidence["identity_sha256"] == c.file_sha(folder/"PROBE_IDENTITY.json"), "physical probe identities")
    check(identity["child_argv"] == [spec["python_runtime"]["path"], "-B", "-c", "import time; time.sleep(10)"], "child launcher identity")
    lines = [line for line in log.splitlines() if line.startswith("FSM_SUPERVISOR_IDENTITIES")]
    check(lines == ["FSM_SUPERVISOR_IDENTITIES owner="+str(identity["owner"]["pid"])+" child="+str(identity["child"]["pid"])], "physical probe identity output")
    for key in ("owner", "child"):
        state = evidence["after"][key]
        observed = state["observed"]
        if observed is not None:
            check(type(observed) is dict and set(observed) == {"state", "starttime", "pgid"}
                  and type(observed["starttime"]) is str and observed["starttime"].isdigit()
                  and observed["starttime"] != identity[key]["starttime"]
                  and type(observed["pgid"]) is int and observed["pgid"] > 0
                  and type(observed["state"]) is str and len(observed["state"]) == 1,
                  "only well-formed absent/reused original PID qualifies")
    return evidence


def command_receipt(root, spec, item, number, command, guard_paths, global_index, env_sha, prior_finished_ns):
    base = root/"results"/item["label"]/"native_calls"/(str(number)+"_"+command["tool"])
    attempt, complete = c.read(base/"attempt.json"), c.read(base/"complete.json")
    pair = {} if item["kind"] == "supervisor_probe" else {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]}
    before = guard_paths[2*global_index+1]
    expected = dict(schema="fsm_owned_command_attempt_v2", label=item["label"], sequence=number,
                    tool=command["tool"], argv=command["argv"], cwd=command["cwd"], cap_s=command["cap_s"],
                    command_sha256=c.sha(c.canonical(command).encode()), source_before=pair,
                    spec_sha256=c.file_sha(root/"RUN_SPEC.json"), environment_sha256=env_sha,
                    before_guard=before.relative_to(root/"results").as_posix(), before_guard_sha256=c.file_sha(before),
                    attempted=True, started_ns=attempt["started_ns"])
    check(attempt == expected and type(attempt["started_ns"]) is int and attempt["started_ns"] >= prior_finished_ns, "exact physical attempt/order")
    check(all(complete.get(key) == value for key, value in attempt.items() if key != "schema"), "complete linked to attempt fields")
    check(complete["schema"] == "fsm_owned_command_complete_v2"
          and complete["attempt_sha256"] == c.file_sha(base/"attempt.json")
          and complete["owned_error"] is None and complete["confirmed"] is True and complete["finalized"] is True
          and type(complete["finished_ns"]) is int and complete["finished_ns"] >= attempt["started_ns"], "real completion")
    actual = complete["actual"]
    actual_keys = {"timeout", "launch_error", "returncode", "group_signals", "elapsed_s", "remaining_live_group", "log", "log_sha256", "log_bytes"}
    check(type(actual) is dict and set(actual) == actual_keys and finite(actual["elapsed_s"]), "unaltered owned runner result")
    check(type(actual["timeout"]) is bool and (actual["launch_error"] is None or type(actual["launch_error"]) is str)
          and type(actual["group_signals"]) is list and all(s == "SIGKILL" for s in actual["group_signals"])
          and type(actual["remaining_live_group"]) is list, "physical supervisor fields")
    check(actual["elapsed_s"] <= command["cap_s"]+12.5, "physical deadline/cleanup bound")
    check(actual["elapsed_s"] <= (complete["finished_ns"]-attempt["started_ns"])/1_000_000_000+0.01,
          "owned elapsed exceeds physical attempt/completion interval")
    log_bytes = (base/"stdout.log").read_bytes()
    expected_log = spec["cloud_root"]+"/"+base.relative_to(root).as_posix()+"/stdout.log"
    check(actual["log"] == expected_log and actual["log_sha256"] == c.sha(log_bytes)
          and actual["log_bytes"] == len(log_bytes), "actual physical raw log binding")
    check(complete["stdout"] == dict(path="stdout.log", sha256=c.sha(log_bytes), bytes=len(log_bytes))
          and complete["stream_policy"] == "physical stdout and stderr merged by pinned owned_command", "physical merged stdout/stderr")
    log = log_bytes.decode("utf-8")
    check(not c.ENV_ERROR.search(log), "tool environment failure")
    mutation = item["variant"] == "owned_scratch_source_mutation" and command["tool"] == "xsim"
    after_pair = pair | ({"candidate.sv": c.sha(item["source"].encode()+c.MUTATION_BYTES)} if mutation else {})
    check(complete["source_after"] == after_pair and complete["mutation_applied"] is mutation, "true source before/after")
    after = guard_paths[2*global_index+2]
    check(c.read(base/"after_guard.json") == dict(path=after.relative_to(root/"results").as_posix(), sha256=c.file_sha(after)), "post-tool guard")
    command_result = dict(actual)
    if item["variant"] == "timeout":
        command_result["probe_evidence"] = cleanup_proof(base.parent.parent, complete, log, spec)
    else:
        check("probe_evidence" not in complete and "probe_evidence_error" not in complete, "unplanned probe proof")
    if item["variant"] == "launch_error":
        check(log_bytes == b"" and re.search(r"\[Errno 2\].*No such file or directory", actual["launch_error"] or ""), "real nonexistent launcher")
    return command_result, log, complete["finished_ns"], base.relative_to(root/"results").as_posix()


def clocks(root, spec, env_sha):
    admission_path = root/"results/STAGE_CLOCK_ADMISSION.json"
    admission = c.read(admission_path)
    completion = c.read(root/"results/STAGE_CLOCK_COMPLETION.json")
    check(admission == dict(schema="fsm_native_stage_clock_admission_v2", spec_sha256=c.file_sha(root/"RUN_SPEC.json"),
          environment_sha256=env_sha, monotonic_ns=admission["monotonic_ns"], realtime_ns=admission["realtime_ns"]), "stage clock admission")
    check(completion == dict(schema="fsm_native_stage_clock_completion_v2", admission_sha256=c.file_sha(admission_path),
          monotonic_ns=completion["monotonic_ns"], realtime_ns=completion["realtime_ns"]), "stage clock completion")
    check(all(type(clock[key]) is int and clock[key] > 0 for clock in (admission, completion)
              for key in ("monotonic_ns", "realtime_ns")), "real stage clock integers")
    check(completion["monotonic_ns"] >= admission["monotonic_ns"]
          and completion["realtime_ns"] >= admission["realtime_ns"], "stage clock order")
    return admission, completion


def audit(root, cases, deps):
    root, cases, deps = Path(root).resolve(), Path(cases).resolve(), Path(deps).resolve()
    spec, items = pinned_packet(root, cases, deps)
    guard_paths = guards(root, spec)
    env_sha = environment(root, spec)
    clock_admission, clock_completion = clocks(root, spec, env_sha)
    out = root/"results"
    expected_journals, reconstructed, command_tools = [], [], []
    global_index, prior_finished_ns = 0, clock_admission["realtime_ns"]
    actual_owned_elapsed_s = 0
    for item in items:
        folder = out/item["label"]
        pair = {} if item["kind"] == "supervisor_probe" else {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]}
        if pair:
            check(c.read(folder/"SOURCE_MANIFEST.json") == pair, "physical scratch source admission")
            expected_source = item["source"].encode()+(c.MUTATION_BYTES if item["variant"] == "owned_scratch_source_mutation" else b"")
            check((folder/"candidate.sv").read_bytes() == expected_source and (folder/"tb.sv").read_bytes() == item["tb"].encode(), "actual final scratch bytes")
        commands, paths, log = [], [], ""
        for number, command in enumerate(c.command_plan(item, spec)):
            result, log, prior_finished_ns, path = command_receipt(root, spec, item, number, command, guard_paths,
                                                                  global_index, env_sha, prior_finished_ns)
            commands.append(result); paths.append(path); expected_journals.append(item["label"]+"/native_calls/"+str(number)+"_"+command["tool"])
            command_tools.append(command["tool"]); global_index += 1
            actual_owned_elapsed_s += result["elapsed_s"]
            partial_counts = {name: command_tools.count(name) for name in c.TOOLS}
            expected_progress = dict(schema="fsm_native_progress_v2", label=item["label"],
                attempted_owned_commands=global_index, confirmed_owned_commands=global_index, unconfirmed_owned_attempts=0,
                actual_native_by_tool=partial_counts, actual_native_commands=sum(partial_counts.values()),
                actual_owned_supervisor_commands=command_tools.count("owned_supervisor"), inventory_errors=[],
                completed_rows=item["index"], model_calls=0)
            check(c.read(out/"progress"/(str(global_index-1).zfill(4)+".json")) == expected_progress, "progress recomputed from physical commands")
        after = pair | ({"candidate.sv": c.sha(item["source"].encode()+c.MUTATION_BYTES)} if item["variant"] == "owned_scratch_source_mutation" else {})
        verdict = c.classify(item, commands, log, pair, after)
        row = dict(label=item["label"], index=item["index"], kind=item["kind"], commands=paths, error=None, classification=verdict)
        check(c.read(folder/"ROW.json") == row, "row decision independently replayed")
        reconstructed.append(row)
    for basename in ("attempt.json", "complete.json", "after_guard.json", "stdout.log"):
        assert_names(out, basename, [path+"/"+basename for path in expected_journals])
    assert_names(out, "ROW.json", [i["label"]+"/ROW.json" for i in items])
    check({p.name for p in (out/"progress").iterdir()} == {str(i).zfill(4)+".json" for i in range(global_index)}, "exact fixed progress count")
    native = {name: command_tools.count(name) for name in c.TOOLS}
    check(global_index == 107 and native == c.EXPECTED_NATIVE_BY_TOOL and command_tools.count("owned_supervisor") == 2, "physical105+2 calls")
    summary = c.read(out/"summary.json")
    expected_summary = dict(schema="fsm_native_calibration_measurement_v2", spec_sha256=c.file_sha(root/"RUN_SPEC.json"),
        complete=True, evidence_complete=all(r["classification"]["evidence_complete"] for r in reconstructed),
        native_qualified=all(r["classification"]["evidence_complete"] and r["classification"]["control_matched"] for r in reconstructed),
        error=None, planned=c.PLANNED, rows=reconstructed, model_calls=0, original_harness=False,
        score_gain_measured=False, adoption=False, attempted_owned_commands=global_index,
        confirmed_owned_commands=global_index, unconfirmed_owned_attempts=0, actual_native_by_tool=native,
        actual_native_commands=sum(native.values()), actual_owned_supervisor_commands=2, inventory_errors=[],
        elapsed_s=summary["elapsed_s"], guard_receipts=c.EXPECTED_GUARDS)
    check(summary == expected_summary and finite(summary["elapsed_s"]) and summary["elapsed_s"] < spec["stage_timeout_s"], "terminal summary replay/deadline")
    clock_elapsed = (clock_completion["monotonic_ns"]-clock_admission["monotonic_ns"])/1_000_000_000
    check(summary["elapsed_s"] == clock_elapsed and summary["elapsed_s"]+1e-6 >= actual_owned_elapsed_s
          and prior_finished_ns <= clock_completion["realtime_ns"], "summary elapsed bound to stage clocks and actual command sum")
    first_attempt = c.read(out/expected_journals[0]/"attempt.json")
    check(summary["elapsed_s"]+0.01 >= (prior_finished_ns-first_attempt["started_ns"])/1_000_000_000,
          "summary elapsed below first/last physical command span")
    measurements = [r["classification"]["measurement"] for r in reconstructed if r["classification"]["measurement"] is not None]
    check(sum(m["actual_trace_count"] for m in measurements) == c.PLANNED["full_trace_observations"], "actual3010 observations")
    return dict(schema="fsm_native_calibration_archive_audit_v2", evidence_complete=expected_summary["evidence_complete"],
                native_qualified=expected_summary["native_qualified"], spec_sha256=c.file_sha(root/"RUN_SPEC.json"),
                case_plan_sha256=c.file_sha(root/"CASE_PLAN.json"), summary_sha256=c.file_sha(out/"summary.json"),
                planned=c.PLANNED, actual_native_by_tool=native, actual_native_commands=sum(native.values()),
                actual_owned_supervisor_commands=2, actual_trace_count=sum(m["actual_trace_count"] for m in measurements),
                actual_owned_elapsed_s=actual_owned_elapsed_s,
                guard_receipts=c.EXPECTED_GUARDS, rows=reconstructed, model_calls=0, original_harness=False,
                score_gain_measured=False, adoption=False, legacy_native71_gate_failure_preserved=True,
                legacy_native71_assertion_kind="policy_reference_only_not_reaudit",
                evidence_standard=c.plan(items)["evidence_standard"], audit_errors=[])


def main(args):
    check(sys.platform == "linux", "AMD Linux audit only")
    try:
        result = audit(args.root, args.case_root, args.dependency_root)
    except BaseException as error:
        result = dict(schema="fsm_native_calibration_archive_audit_v2", evidence_complete=False,
                      native_qualified=False, model_calls=0, original_harness=False, score_gain_measured=False,
                      adoption=False, planned=c.PLANNED, audit_errors=[type(error).__name__+": "+str(error)])
    c.save(args.report, result)
    return 0 if result["evidence_complete"] and result["native_qualified"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "case-root", "dependency-root", "report"):
        parser.add_argument("--"+name, type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
