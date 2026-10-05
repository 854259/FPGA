"""AMD-only real native stage. Missing root freeze fails before any owned process.

All38 controls run once; expected refusal cases have separate classification.
No model call, EDA resampling, shared-model mutation or canonical-source mutation.
"""
import argparse
import ctypes
import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path

import calibration as c


def validate_sources(root, spec):
    c.require(type(spec["source_hashes"]) is dict and spec["source_hashes"], "frozen source inventory")
    for name, digest in spec["source_hashes"].items():
        c.require(c.file_sha(c.contained(root, name)) == digest, "frozen source changed: "+name)
    for module in (c, sys.modules[__name__]):
        rel = Path(module.__file__).resolve().relative_to(root).as_posix()
        c.require(rel in spec["source_hashes"], "executed source omitted from freeze")


def frozen(root, case_root, dependency_root, resource_check, kit):
    root = Path(root).resolve()
    path = root/"RUN_SPEC.json"
    c.require(path.is_file(), "RUN_SPEC absent; native execution forbidden")
    spec = c.read(path)
    c.require(spec["schema"] == "fsm_native_calibration_frozen_v2", "wrong frozen schema")
    c.require(spec["cloud_root"] == str(root) and spec["kit"] == str(Path(kit).resolve()),
              "actual packet/kit identity")
    c.require(Path(case_root).resolve() == c.contained(root, spec["case_root_relative"]).resolve(),
              "case root must be frozen packet path")
    c.require(Path(dependency_root).resolve() == Path(spec["dependencies_cloud"]).resolve(),
              "dependency root must match frozen path")
    c.require(Path(resource_check).resolve() == (root/"guard/resource_check.json").resolve(),
              "own guard resource only")
    c.require(spec["planned"] == c.PLANNED and spec["model_requests_max"] == 0
              and spec["expected_native_by_tool"] == c.EXPECTED_NATIVE_BY_TOOL,
              "fixed38/105/2/0model plan")
    c.require(type(spec["stage_timeout_s"]) is int and 0 < spec["stage_timeout_s"] <= 3600,
              "frozen stage cap")
    c.require(type(spec["native_command_timeout_s"]) is int and 0 < spec["native_command_timeout_s"] <= 300
              and 0 < spec["supervisor_probe_timeout_s"] < 1, "owned command caps")
    validate_sources(root, spec)
    required_assets = {"CASE_PLAN.json", "raw_evidence/ENVIRONMENT_CAPTURE.json",
                       "raw_evidence/PROTECTED_GROUPS_CAPTURE.json", spec["supervisor_probe_relative"]}
    case_binding = c.read(c.contained(case_root, "PREPARATION_BINDING.json"))
    required_assets |= {c.contained(case_root, name).relative_to(root).as_posix()
                        for name in list(case_binding["private_files"])+["PREPARATION_BINDING.json"]}
    c.require(required_assets <= spec["source_hashes"].keys(), "case/capture/plan asset omitted from freeze")
    for name, digest in spec["dependency_hashes"].items():
        c.require(c.file_sha(c.contained(dependency_root, name)) == digest, "pinned dependency changed")
    c.require(spec["dependency_hashes"]["paired_checkpoint.py"] == c.PAIRED_SHA
              and spec["dependency_hashes"]["protected_sources.py"] == c.PROTECTED_HELPER_SHA,
              "owned command and protected helper pins")
    items = c.describe_cases(case_root)
    actual_plan = c.plan(items)
    c.require(c.read(root/"CASE_PLAN.json") == actual_plan, "replayed complete case plan differs")
    for item in items:
        folder = root/"prepared_cases"/item["label"]
        c.require(c.file_sha(folder/"candidate.sv") == item["source_sha256"]
                  and c.file_sha(folder/"tb.sv") == item["tb_sha256"]
                  and c.read(folder/"expected_observations.json") == item["expected_observations"],
                  "new prepared source/independent observation binding")
        for name in ("candidate.sv", "tb.sv", "expected_observations.json"):
            c.require((folder/name).relative_to(root).as_posix() in spec["source_hashes"],
                      "prepared asset omitted from source freeze")
    return spec, items


def environment_sha():
    return c.sha(c.canonical(dict(os.environ)).encode())


def validate_environment(root, spec):
    capture = c.read(root/"raw_evidence/ENVIRONMENT_CAPTURE.json")
    c.require(capture["compiler_tools"] == spec["compiler_tools"]
              and capture["compiler_env"] == spec["compiler_env"]
              and capture["udev_files"] == spec["udev_files"], "reviewed environment capture")
    current = {key: os.environ.get(key) for key in ("PATH", "VIVADO_BIN", "LD_LIBRARY_PATH")}
    c.require(current == spec["compiler_env"], "actual compiler environment changed")
    checked = {}
    for name in (*c.TOOLS, "vivado"):
        expected = spec["compiler_tools"][name]
        found = shutil.which(name)
        c.require(found is not None and Path(found).resolve() == Path(expected["path"]).resolve()
                  and os.access(found, os.X_OK) and c.file_sha(found) == expected["sha256"],
                  "wrong/missing/non-executable native entry: "+name)
        checked[name] = expected
    stub = Path(spec["udev_stub"]).resolve()
    c.require(str(stub) in current["LD_LIBRARY_PATH"].split(os.pathsep) and stub.is_dir(),
              "scoped udev binding")
    actual_stub = {p.relative_to(stub).as_posix(): c.file_sha(p) for p in stub.rglob("*") if p.is_file()}
    c.require(actual_stub == spec["udev_files"] and actual_stub, "actual stub bytes")
    python = spec["python_runtime"]
    c.require(Path(python["path"]).resolve() == Path(sys.executable).resolve()
              and os.access(python["path"], os.X_OK) and c.file_sha(python["path"]) == python["sha256"],
              "real pinned supervisor Python image")
    c.require(spec["supervisor_probe_relative"] in spec["source_hashes"], "owned probe source freeze")
    return dict(schema="fsm_native_environment_preflight_v2", verified=True,
                compiler_tools=checked, compiler_env=current, udev_files=actual_stub,
                python_runtime=python, full_environment_sha256=environment_sha())


def load_module(name, path):
    loader = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def source_pair(folder):
    return {name: c.file_sha(folder/name) for name in ("candidate.sv", "tb.sv")}


def probe_evidence(folder):
    path = folder/"PROBE_IDENTITY.json"
    identity = c.read(path)
    c.require(c.probe_identity_valid(identity), "real owned probe identities")
    owner, child = identity["owner"], identity["child"]
    states = {}
    for key, value in (("owner", owner), ("child", child)):
        proc = Path("/proc")/str(value["pid"])/"stat"
        if not proc.exists():
            states[key] = dict(original_process_absent=True, observed=None)
        else:
            fields = proc.read_text().rsplit(")", 1)[1].split()
            states[key] = dict(original_process_absent=fields[19] != value["starttime"],
                               observed=dict(state=fields[0], starttime=fields[19], pgid=int(fields[2])))
    return dict(identity=identity, identity_sha256=c.file_sha(path), after=states,
                both_original_processes_absent=all(v["original_process_absent"] for v in states.values()))


def inventory(out, items):
    expected = {}
    for item in items:
        names = item["expected_native_tools"] or ["owned_supervisor"]
        for number, tool in enumerate(names):
            expected[item["label"]+"/native_calls/"+str(number)+"_"+tool] = tool
    attempted, confirmed, errors = [], [], []
    for path in out.rglob("attempt.json"):
        base = path.parent.relative_to(out).as_posix()
        if base not in expected:
            errors.append("unknown/repeated owned command directory: "+base)
        attempted.append(base)
    for path in out.rglob("complete.json"):
        base = path.parent.relative_to(out).as_posix()
        if base not in expected:
            errors.append("unknown command completion: "+base)
        value = c.read(path)
        if value.get("confirmed") is True and value.get("finalized") is True:
            confirmed.append(base)
    if len(set(attempted)) != len(attempted) or len(set(confirmed)) != len(confirmed):
        errors.append("duplicate command evidence")
    native = {tool: sum(expected.get(name) == tool for name in confirmed) for tool in c.TOOLS}
    probes = sum(expected.get(name) == "owned_supervisor" for name in confirmed)
    return dict(attempted_owned_commands=len(attempted), confirmed_owned_commands=len(confirmed),
                unconfirmed_owned_attempts=len(attempted)-len(confirmed),
                actual_native_by_tool=native, actual_native_commands=sum(native.values()),
                actual_owned_supervisor_commands=probes, inventory_errors=errors)


def main(args):
    root, cases, deps, resource, kit = (x.resolve() for x in
        (args.root, args.case_root, args.dependency_root, args.resource_check, args.kit))
    spec, items = frozen(root, cases, deps, resource, kit)
    c.require(sys.platform == "linux" and sys.version_info[:2] == (3, 12), "AMD Linux Python3.12 only")
    c.require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, "owned-process subreaper")
    paired = load_module("fsm_owned_paired", c.contained(deps, "paired_checkpoint.py"))
    protected = load_module("fsm_protected_sources", c.contained(deps, "protected_sources.py"))
    paired.REPO = root
    environment = validate_environment(root, spec)
    env_sha = environment["full_environment_sha256"]
    binding = c.read(root/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json")
    started_monotonic_ns = time.monotonic_ns()
    started = started_monotonic_ns/1_000_000_000
    out = root/"results"
    out.mkdir(exist_ok=False)
    (out/"guard_receipts").mkdir(); (out/"progress").mkdir()
    c.save(out/"STAGE_CLOCK_ADMISSION.json", dict(schema="fsm_native_stage_clock_admission_v2",
        spec_sha256=c.file_sha(root/"RUN_SPEC.json"), environment_sha256=env_sha,
        monotonic_ns=started_monotonic_ns, realtime_ns=time.time_ns()))
    guard_number = 0
    def gate(first=False):
        nonlocal guard_number
        c.require(time.monotonic()-started < spec["stage_timeout_s"]-15, "absolute stage deadline; no retry")
        validate_sources(root, spec)
        c.require(environment_sha() == env_sha, "inherited native environment mutation")
        record = paired.check_resource(resource, kit, first=first)
        for key in ("model_identity", "protected", "slot_owner", "slot_lock_path", "llm_base_url", "model_name"):
            c.require(record[key] == spec[key], "owned FIFO/protected resource changed: "+key)
        source_check = protected.check(binding)
        c.require(source_check["source_assets"] == spec["protected_source_assets"]
                  and len(source_check["groups"]) == spec["protected_group_count"],
                  "all captured protected groups/assets")
        receipt = dict(schema="fsm_native_guard_receipt_v2", index=guard_number, resource=record,
                       protected_sources=source_check, resource_sha256=c.file_sha(resource))
        path = out/"guard_receipts"/(str(guard_number).zfill(4)+".json")
        c.save(path, receipt); guard_number += 1
        return path.relative_to(out).as_posix(), c.file_sha(path)
    rows = []
    summary = dict(schema="fsm_native_calibration_measurement_v2", spec_sha256=c.file_sha(root/"RUN_SPEC.json"),
                   complete=False, evidence_complete=False, native_qualified=False, error=None,
                   planned=c.PLANNED, rows=rows, model_calls=0, original_harness=False,
                   score_gain_measured=False, adoption=False)
    try:
        gate(first=True)
        c.save(out/"ENVIRONMENT_PREFLIGHT.json", environment)
        # Every variant is materialized before the first native invocation.
        for item in items:
            folder = out/item["label"]
            folder.mkdir(); (folder/"native_calls").mkdir()
            if item["kind"] != "supervisor_probe":
                (folder/"candidate.sv").write_bytes(item["source"].encode())
                (folder/"tb.sv").write_bytes(item["tb"].encode())
                c.save(folder/"SOURCE_MANIFEST.json", source_pair(folder))
        for item in items:
            folder = out/item["label"]
            commands = []
            row = dict(label=item["label"], index=item["index"], kind=item["kind"],
                       commands=[], error=None, classification=None)
            try:
                for number, command in enumerate(c.command_plan(item, spec)):
                    before_guard, before_guard_sha = gate()
                    pair_before = source_pair(folder) if item["kind"] != "supervisor_probe" else {}
                    if pair_before:
                        c.require(pair_before == {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]},
                                  "actual pre-tool scratch source changed")
                    c.require(command["cwd"] == str(folder), "physical cwd binding")
                    if item["variant"] == "launch_error":
                        c.require(not Path(command["argv"][0]).exists(), "launcher probe must actually be absent")
                    journal = folder/"native_calls"/(str(number)+"_"+command["tool"])
                    journal.mkdir()
                    receipt = dict(schema="fsm_owned_command_attempt_v2", label=item["label"], sequence=number,
                                   tool=command["tool"], argv=command["argv"], cwd=command["cwd"],
                                   cap_s=command["cap_s"], command_sha256=c.sha(c.canonical(command).encode()),
                                   source_before=pair_before, spec_sha256=summary["spec_sha256"],
                                   environment_sha256=env_sha, before_guard=before_guard,
                                   before_guard_sha256=before_guard_sha, attempted=True, started_ns=time.time_ns())
                    c.save(journal/"attempt.json", receipt)
                    actual = None; owned_error = None
                    try:
                        remaining = spec["stage_timeout_s"]-(time.monotonic()-started)-10
                        c.require(remaining >= command["cap_s"], "whole-stage cap before launch")
                        actual = paired.owned_command(command["argv"], folder, journal/"stdout.log", command["cap_s"])
                    except BaseException as error:
                        owned_error = type(error).__name__+": "+str(error)
                    # Deliberately mutate only the owned scratch DUT, after actual xsim exit.
                    mutation_applied = (actual is not None and command["tool"] == "xsim"
                                        and item["variant"] == "owned_scratch_source_mutation")
                    if mutation_applied:
                        with (folder/"candidate.sv").open("ab") as stream:
                            stream.write(c.MUTATION_BYTES)
                    pair_after = source_pair(folder) if pair_before else {}
                    completion = receipt | dict(schema="fsm_owned_command_complete_v2",
                        attempt_sha256=c.file_sha(journal/"attempt.json"), actual=actual, owned_error=owned_error,
                        source_after=pair_after, mutation_applied=mutation_applied, finished_ns=time.time_ns(),
                        confirmed=actual is not None, finalized=True,
                        stream_policy="physical stdout and stderr merged by pinned owned_command")
                    if (journal/"stdout.log").is_file():
                        completion["stdout"] = dict(path="stdout.log", sha256=c.file_sha(journal/"stdout.log"),
                                                    bytes=(journal/"stdout.log").stat().st_size)
                    if actual is not None and item["variant"] == "timeout":
                        try:
                            completion["probe_evidence"] = probe_evidence(folder)
                        except BaseException as error:
                            completion["probe_evidence_error"] = type(error).__name__+": "+str(error)
                    c.save(journal/"complete.json", completion)
                    c.require(owned_error is None and actual is not None, "owned tool supervision exception")
                    c.require(completion.get("probe_evidence_error") is None, "owned descendant evidence failure")
                    after_guard, after_guard_sha = gate()
                    c.save(journal/"after_guard.json", dict(path=after_guard, sha256=after_guard_sha))
                    commands.append(actual | ({"probe_evidence": completion["probe_evidence"]}
                                               if "probe_evidence" in completion else {}))
                    row["commands"].append(journal.relative_to(out).as_posix())
                    c.save(out/"progress"/(str(len(list((out/"progress").glob("*.json")))).zfill(4)+".json"),
                           dict(schema="fsm_native_progress_v2", label=item["label"], **inventory(out, items),
                                completed_rows=len(rows), model_calls=0))
                    c.require(actual["timeout"] is False and actual["launch_error"] is None
                              and actual["remaining_live_group"] == [] or item["kind"] == "supervisor_probe",
                              "unexpected native supervision failure")
                    c.require(not c.ENV_ERROR.search((journal/"stdout.log").read_bytes().decode("utf-8")),
                              "actual tool environment failure")
                    if item["kind"] not in ("eda_failure", "supervisor_probe") and command["tool"] in ("xvlog", "xelab"):
                        c.require(actual["returncode"] == 0, "unexpected compile/elaboration failure")
                log_tool = item["expected_native_tools"][-1] if item["expected_native_tools"] else "owned_supervisor"
                log_folder = folder/"native_calls"/(str(len(commands)-1)+"_"+log_tool)
                log = (log_folder/"stdout.log").read_bytes().decode("utf-8")
                before = {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]} if item["kind"] != "supervisor_probe" else {}
                after = source_pair(folder) if before else {}
                row["classification"] = c.classify(item, commands, log, before, after)
            except BaseException as error:
                row["error"] = type(error).__name__+": "+str(error)
                xsim = folder/"native_calls/2_xsim/stdout.log"
                if xsim.is_file() and item["expected_observations"]:
                    row["partial_measurement"] = c.measure(xsim.read_bytes().decode("utf-8"), item["expected_observations"])
            c.save(folder/"ROW.json", row)
            rows.append(row)
            if row["error"] is not None:
                raise ValueError(row["error"])
        gate()
        c.require(validate_environment(root, spec) == environment, "end-of-stage compiler environment")
        summary.update(complete=True, evidence_complete=all(r["classification"]["evidence_complete"] for r in rows),
                       native_qualified=all(r["classification"]["control_matched"] for r in rows))
    except BaseException as error:
        summary["error"] = type(error).__name__+": "+str(error)
    finally:
        finished_monotonic_ns = time.monotonic_ns()
        c.save(out/"STAGE_CLOCK_COMPLETION.json", dict(schema="fsm_native_stage_clock_completion_v2",
            admission_sha256=c.file_sha(out/"STAGE_CLOCK_ADMISSION.json"),
            monotonic_ns=finished_monotonic_ns, realtime_ns=time.time_ns()))
        summary.update(inventory(out, items), elapsed_s=(finished_monotonic_ns-started_monotonic_ns)/1_000_000_000,
                       guard_receipts=guard_number)
        exact = (summary["actual_native_by_tool"] == c.EXPECTED_NATIVE_BY_TOOL
                 and summary["actual_owned_supervisor_commands"] == 2
                 and summary["unconfirmed_owned_attempts"] == 0 and not summary["inventory_errors"]
                 and len(rows) == c.PLANNED["total_controls"] and summary["error"] is None
                 and guard_number == c.EXPECTED_GUARDS)
        if not exact:
            summary.update(complete=False, evidence_complete=False, native_qualified=False)
        summary["native_qualified"] = summary["native_qualified"] and summary["evidence_complete"]
        c.save(out/"summary.json", summary)
    return 0 if summary["native_qualified"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "case-root", "dependency-root", "resource-check", "kit"):
        parser.add_argument("--"+name, type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
