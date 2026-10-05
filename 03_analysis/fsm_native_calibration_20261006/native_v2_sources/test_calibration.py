"""AMD-only pure FAKE controls; never native execution or RTL ability evidence.

Usage on AMD: python -B test_calibration.py --case-root PACKET_CASES
    --dependency-root PINNED_DEPENDENCIES
Full-chain fixtures simulate receipt metadata only and are clearly marked FAKE.
"""
import argparse
import contextlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit as a
import calibration as c
import stage as s

CASE_ROOT = None
DEPENDENCY_ROOT = None


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=True, indent=2)+"\n", encoding="utf-8")


def fake_log(expected, failures=(), passes=None, fatal=False):
    """Synthetic log only: does not simulate RTL or claim observed outputs."""
    lines = ["FAKE PURE METADATA FIXTURE: NOT A NATIVE TOOL LOG"]
    for row in expected:
        actual = "0"*len(row["expected"]) if row["index"] in failures else row["expected"]
        if row["index"] in failures and actual == row["expected"]:
            actual = "1"*len(row["expected"])
        bits = row["inputs"]
        line = "FSM_TRACE check="+str(row["index"])+" expected="+row["expected"]+" actual="+actual
        line += " "+" ".join(key+"="+str(bits[key]) for key in ("clock", "reset", "bump_left", "bump_right", "ground", "dig"))
        lines.append(line)
        if actual != row["expected"]:
            lines.append("FSM_FAIL check="+str(row["index"])+" expected="+row["expected"]+" actual="+actual)
    lines.append("FSM_DONE checks="+str(len(expected))+" mismatches="+str(len(failures)))
    if passes is None:
        passes = [] if failures else [len(expected)]
    lines += ["FSM_PASS checks="+str(n) for n in passes]
    if fatal:
        lines.append("FSM_TRANSPORT_FATAL_AFTER_PASS")
    return "\n".join(lines)+"\n"


def command(rc=0):
    return dict(returncode=rc, timeout=False, launch_error=None, remaining_live_group=[], group_signals=[])


def cleanup():
    identity = dict(schema="fsm_owned_supervisor_probe_identity_v2",
                    owner=dict(pid=56001, pgid=56001, starttime="900001"),
                    child=dict(pid=56002, pgid=56001, starttime="900002"),
                    child_argv=["/FAKE/python", "-B", "-c", "import time; time.sleep(10)"])
    return dict(identity=identity, identity_sha256="1"*64,
                after={key: dict(original_process_absent=True, observed=None) for key in ("owner", "child")},
                both_original_processes_absent=True)


def fake_packet(root):
    """Build all38 FAKE rows and107 FAKE commands, with real pinned recipe bytes."""
    cases, deps = root/"cases", root/"dependencies"
    shutil.copytree(CASE_ROOT, cases)
    deps.mkdir()
    for name in ("paired_checkpoint.py", "protected_sources.py"):
        shutil.copyfile(DEPENDENCY_ROOT/name, deps/name)
    for module in (c, a, s):
        shutil.copyfile(module.__file__, root/Path(module.__file__).name)
    shutil.copyfile(Path(c.__file__).with_name("supervisor_probe.py"), root/"supervisor_probe.py")
    items = c.describe_cases(cases)
    prepared = root/"prepared_cases"; prepared.mkdir()
    for item in items:
        folder = prepared/item["label"]; folder.mkdir()
        (folder/"candidate.sv").write_bytes(item["source"].encode())
        (folder/"tb.sv").write_bytes(item["tb"].encode())
        write(folder/"expected_observations.json", item["expected_observations"])
    write(root/"CASE_PLAN.json", c.plan(items))
    raw = root/"raw_evidence"; raw.mkdir()
    tools = {name: dict(path="/FAKE/"+name, sha256="2"*64) for name in (*c.TOOLS, "vivado")}
    env = dict(PATH="/FAKE", VIVADO_BIN="/FAKE", LD_LIBRARY_PATH="/FAKE/udev")
    udev = {"libudev.so.1": "3"*64}
    write(raw/"ENVIRONMENT_CAPTURE.json", dict(compiler_tools=tools, compiler_env=env, udev_files=udev))
    groups = {"FAKE_group_"+str(i): dict(cloud_root="/FAKE/group"+str(i), spec_name="RUN_SPEC.json",
                spec_sha256="4"*64, source_hashes={"source.py": "5"*64}) for i in range(8)}
    binding = dict(schema="actual_FAKE_PURE_capture", groups=groups, source_assets=8, model_calls=0, eda_calls=0)
    write(raw/"PROTECTED_GROUPS_CAPTURE.json", binding)
    protected = dict(package={}, official={}, tasks={}, baseline={})
    shared = dict(model_identity={"FAKE": True}, protected=protected, slot_owner="FAKE_PURE_ONLY",
                  slot_lock_path="/FAKE/slot", llm_base_url="http://FAKE.invalid", model_name="FAKE_NO_MODEL")
    resource = dict(schema_version=1, resource_idle=True, **shared)
    (root/"guard").mkdir(); write(root/"guard/resource_check.json", resource)
    frozen = {p.relative_to(root).as_posix(): c.file_sha(p) for p in root.rglob("*")
              if p.is_file() and "dependencies" not in p.relative_to(root).parts and "guard" not in p.relative_to(root).parts}
    spec = dict(schema="fsm_native_calibration_frozen_v2", cloud_root=str(root), kit="/FAKE/kit",
                case_root_relative="cases", dependencies_cloud=str(deps), source_hashes=frozen,
                dependency_hashes={"paired_checkpoint.py": c.PAIRED_SHA, "protected_sources.py": c.PROTECTED_HELPER_SHA},
                planned=c.PLANNED, expected_native_by_tool=c.EXPECTED_NATIVE_BY_TOOL, model_requests_max=0,
                stage_timeout_s=3600, native_command_timeout_s=300, supervisor_probe_timeout_s=0.5,
                compiler_tools=tools, compiler_env=env, udev_files=udev, udev_stub="/FAKE/udev",
                python_runtime=dict(path="/FAKE/python", sha256="6"*64), supervisor_probe_relative="supervisor_probe.py",
                protected_group_count=8, protected_source_assets=8, **shared)
    write(root/"RUN_SPEC.json", spec)
    out = root/"results"; out.mkdir(); (out/"guard_receipts").mkdir(); (out/"progress").mkdir()
    for index in range(c.EXPECTED_GUARDS):
        write(out/"guard_receipts"/(str(index).zfill(4)+".json"), dict(schema="fsm_native_guard_receipt_v2",
            index=index, resource=resource, protected_sources=a.expected_guard_sources(binding),
            resource_sha256=c.file_sha(root/"guard/resource_check.json")))
    env_sha = "7"*64
    write(out/"ENVIRONMENT_PREFLIGHT.json", dict(schema="fsm_native_environment_preflight_v2", verified=True,
          compiler_tools=tools, compiler_env=env, udev_files=udev, python_runtime=spec["python_runtime"], full_environment_sha256=env_sha))
    write(out/"STAGE_CLOCK_ADMISSION.json", dict(schema="fsm_native_stage_clock_admission_v2",
        spec_sha256=c.file_sha(root/"RUN_SPEC.json"), environment_sha256=env_sha, monotonic_ns=5_000_000_000, realtime_ns=1_000_000_000))
    write(out/"STAGE_CLOCK_COMPLETION.json", dict(schema="fsm_native_stage_clock_completion_v2",
        admission_sha256=c.file_sha(out/"STAGE_CLOCK_ADMISSION.json"), monotonic_ns=7_000_000_000, realtime_ns=3_000_000_000))
    rows, sequence_tools, global_index = [], [], 0
    fake_cursor_ns = 1_000_000_000
    for item in items:
        folder = out/item["label"]; folder.mkdir(); (folder/"native_calls").mkdir()
        pair = {} if item["kind"] == "supervisor_probe" else {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]}
        if pair:
            (folder/"candidate.sv").write_bytes(item["source"].encode()); (folder/"tb.sv").write_bytes(item["tb"].encode())
            write(folder/"SOURCE_MANIFEST.json", pair)
        actuals, journals, last_log = [], [], ""
        for number, planned in enumerate(c.command_plan(item, spec)):
            base = folder/"native_calls"/(str(number)+"_"+planned["tool"]); base.mkdir()
            before = out/"guard_receipts"/(str(2*global_index+1).zfill(4)+".json")
            attempt = dict(schema="fsm_owned_command_attempt_v2", label=item["label"], sequence=number,
                tool=planned["tool"], argv=planned["argv"], cwd=planned["cwd"], cap_s=planned["cap_s"],
                command_sha256=c.sha(c.canonical(planned).encode()), source_before=pair,
                spec_sha256=c.file_sha(root/"RUN_SPEC.json"), environment_sha256=env_sha,
                before_guard=before.relative_to(out).as_posix(), before_guard_sha256=c.file_sha(before),
                attempted=True, started_ns=fake_cursor_ns)
            write(base/"attempt.json", attempt)
            result, last_log = command(), "FAKE PURE METADATA TOOL OUTPUT\n"
            if planned["tool"] == "xsim":
                failures = item["required_mismatch_indices"] if item["kind"] == "semantic_negative" else []
                passes = {"finish_without_pass": [], "wrong_pass_count": [len(item["expected_observations"])+1],
                          "duplicate_pass": [len(item["expected_observations"])]*2}.get(item["variant"])
                last_log = fake_log(item["expected_observations"], failures, passes, item["variant"] == "pass_then_fatal")
            elif item["variant"] == "compile_error":
                result["returncode"] = 1; last_log = "FAKE syntax error\n"
            elif item["variant"] == "missing_module" and planned["tool"] == "xelab":
                result["returncode"] = 1; last_log = "FAKE top level fsm_deliberately_missing_module not found\n"
            elif item["variant"] == "timeout":
                result.update(returncode=-9, timeout=True, group_signals=["SIGKILL"])
                proof = cleanup(); write(folder/"PROBE_IDENTITY.json", proof["identity"])
                proof["identity_sha256"] = c.file_sha(folder/"PROBE_IDENTITY.json")
                result["probe_evidence"] = proof
                last_log = "FSM_SUPERVISOR_IDENTITIES owner=56001 child=56002\n"
            elif item["variant"] == "launch_error":
                result.update(returncode=None, launch_error="[Errno 2] No such file or directory: '"+planned["argv"][0]+"'")
                last_log = ""
            (base/"stdout.log").write_bytes(last_log.encode())
            actual = {k: v for k, v in result.items() if k != "probe_evidence"}
            actual.update(elapsed_s=0.6 if item["variant"] == "timeout" else 0.01,
                          log=str(base/"stdout.log"), log_sha256=c.file_sha(base/"stdout.log"), log_bytes=len(last_log.encode()))
            mutation = item["variant"] == "owned_scratch_source_mutation" and planned["tool"] == "xsim"
            after_pair = pair | ({"candidate.sv": c.sha(item["source"].encode()+c.MUTATION_BYTES)} if mutation else {})
            if mutation:
                (folder/"candidate.sv").write_bytes(item["source"].encode()+c.MUTATION_BYTES)
            complete = attempt | dict(schema="fsm_owned_command_complete_v2", attempt_sha256=c.file_sha(base/"attempt.json"),
                actual=actual, owned_error=None, source_after=after_pair, mutation_applied=mutation,
                finished_ns=fake_cursor_ns+int(actual["elapsed_s"]*1_000_000_000), confirmed=True, finalized=True,
                stdout=dict(path="stdout.log", sha256=c.file_sha(base/"stdout.log"), bytes=len(last_log.encode())),
                stream_policy="physical stdout and stderr merged by pinned owned_command")
            if "probe_evidence" in result:
                complete["probe_evidence"] = result["probe_evidence"]
            write(base/"complete.json", complete)
            fake_cursor_ns = complete["finished_ns"]+1_000_000
            after = out/"guard_receipts"/(str(2*global_index+2).zfill(4)+".json")
            write(base/"after_guard.json", dict(path=after.relative_to(out).as_posix(), sha256=c.file_sha(after)))
            actuals.append(actual | ({"probe_evidence": result["probe_evidence"]} if "probe_evidence" in result else {}))
            journals.append(base.relative_to(out).as_posix()); sequence_tools.append(planned["tool"]); global_index += 1
            counts = {name: sequence_tools.count(name) for name in c.TOOLS}
            write(out/"progress"/(str(global_index-1).zfill(4)+".json"), dict(schema="fsm_native_progress_v2", label=item["label"],
                attempted_owned_commands=global_index, confirmed_owned_commands=global_index, unconfirmed_owned_attempts=0,
                actual_native_by_tool=counts, actual_native_commands=sum(counts.values()),
                actual_owned_supervisor_commands=sequence_tools.count("owned_supervisor"), inventory_errors=[], completed_rows=item["index"], model_calls=0))
        after_pair = pair | ({"candidate.sv": c.sha(item["source"].encode()+c.MUTATION_BYTES)} if item["variant"] == "owned_scratch_source_mutation" else {})
        row = dict(label=item["label"], index=item["index"], kind=item["kind"], commands=journals, error=None,
                   classification=c.classify(item, actuals, last_log, pair, after_pair))
        write(folder/"ROW.json", row); rows.append(row)
    write(out/"summary.json", dict(schema="fsm_native_calibration_measurement_v2", spec_sha256=c.file_sha(root/"RUN_SPEC.json"),
        complete=True, evidence_complete=True, native_qualified=True, error=None, planned=c.PLANNED, rows=rows,
        model_calls=0, original_harness=False, score_gain_measured=False, adoption=False,
        attempted_owned_commands=107, confirmed_owned_commands=107, unconfirmed_owned_attempts=0,
        actual_native_by_tool=c.EXPECTED_NATIVE_BY_TOOL, actual_native_commands=105,
        actual_owned_supervisor_commands=2, inventory_errors=[], elapsed_s=2.0, guard_receipts=c.EXPECTED_GUARDS))
    return cases, deps


class PureControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c.require(sys.platform == "linux" and CASE_ROOT is not None and DEPENDENCY_ROOT is not None, "AMD pure test inputs required")
        cls.items = c.describe_cases(CASE_ROOT)
        cls.positive = cls.items[0]
        cls.negative = next(i for i in cls.items if i["variant"] == "retain_direction_on_fall_reset")
        cls.expected = cls.positive["expected_observations"]

    def item(self, variant):
        return next(i for i in self.items if i["variant"] == variant)

    def verdict(self, item, log, rc=0, after=None):
        pair = {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]}
        return c.classify(item, [command(), command(), command(rc)], log, pair, pair if after is None else after)

    @contextlib.contextmanager
    def packet(self):
        with tempfile.TemporaryDirectory(prefix="FAKE_FSM_PURE_") as directory:
            root = Path(directory); cases, deps = fake_packet(root)
            with patch.object(c, "__file__", str(root/"calibration.py")), patch.object(a, "__file__", str(root/"audit.py")), patch.object(s, "__file__", str(root/"stage.py")):
                yield root, cases, deps

    def test_01_fixed_plan_and_reset_obligations(self):
        self.assertEqual((len(self.items), c.PLANNED["native_commands"], c.EXPECTED_GUARDS), (38, 105, 216))
        for case, count, indices in [(c.CASE_NAMES[0], 55, [39, 52]), (c.CASE_NAMES[1], 115, [69, 79, 95, 112])]:
            item = next(i for i in self.items if i["case"] == case)
            self.assertEqual(len(item["expected_observations"]), count)
            for index in indices:
                self.assertEqual(item["expected_observations"][index-1]["phase"], "async_assert_clock_low")

    def test_02_positive_complete_trace(self):
        self.assertTrue(self.verdict(self.positive, fake_log(self.expected))["positive_admission"])

    def test_03_negative_real_counter_log_required(self):
        log = fake_log(self.expected, self.negative["required_mismatch_indices"])
        self.assertTrue(self.verdict(self.negative, log)["control_matched"])
        self.assertFalse(self.verdict(self.negative, fake_log(self.expected))["control_matched"])

    def test_04_partial_retains_actual_count(self):
        log = "\n".join(fake_log(self.expected).splitlines()[:4])
        result = c.measure(log, self.expected)
        self.assertEqual(result["actual_trace_count"], 3)
        self.assertFalse(result["measurement_complete"])

    def test_05_logged_expected_forgery(self):
        log = fake_log(self.expected).replace("expected=100 actual=100", "expected=000 actual=100", 1)
        self.assertIn("logged_expected_not_independent", c.measure(log, self.expected)["errors"])

    def test_06_physical_stimulus_must_match(self):
        log = fake_log(self.expected).replace("clock=0 reset=1", "clock=1 reset=1", 1)
        self.assertIn("physical_stimulus_not_expected", c.measure(log, self.expected)["errors"])

    def test_07_repeated_trace_rejected(self):
        log = fake_log(self.expected); line = next(l for l in log.splitlines() if l.startswith("FSM_TRACE"))
        self.assertFalse(c.measure(line+"\n"+log, self.expected)["measurement_complete"])

    def test_08_fail_position_is_bound(self):
        log = fake_log(self.expected, [52]); lines = log.splitlines(); failure = next(l for l in lines if l.startswith("FSM_FAIL"))
        lines.remove(failure); lines.insert(0, failure)
        self.assertIn("FAIL_not_immediately_after_own_trace", c.measure("\n".join(lines), self.expected)["errors"])

    def test_09_done_count_or_duplicate_rejected(self):
        for log in [fake_log(self.expected).replace("FSM_DONE checks=55", "FSM_DONE checks=54"),
                    fake_log(self.expected)+"FSM_DONE checks=55 mismatches=0\n"]:
            self.assertFalse(c.measure(log, self.expected)["measurement_complete"])

    def test_10_fatal_after_pass_refuses_positive(self):
        log = fake_log(self.expected, fatal=True)
        self.assertFalse(self.verdict(self.positive, log)["positive_admission"])
        self.assertTrue(self.verdict(self.item("pass_then_fatal"), log)["control_matched"])

    def test_11_finish_without_pass(self):
        self.assertTrue(self.verdict(self.item("finish_without_pass"), fake_log(self.expected, passes=[]))["control_matched"])

    def test_12_wrong_pass_count(self):
        self.assertTrue(self.verdict(self.item("wrong_pass_count"), fake_log(self.expected, passes=[56]))["control_matched"])

    def test_13_duplicate_pass(self):
        self.assertTrue(self.verdict(self.item("duplicate_pass"), fake_log(self.expected, passes=[55, 55]))["control_matched"])

    def test_14_exact_post_xsim_mutation(self):
        item = self.item("owned_scratch_source_mutation")
        after = {"candidate.sv": c.sha(item["source"].encode()+c.MUTATION_BYTES), "tb.sv": item["tb_sha256"]}
        self.assertTrue(self.verdict(item, fake_log(self.expected), after=after)["control_matched"])
        after["candidate.sv"] = "0"*64
        self.assertFalse(self.verdict(item, fake_log(self.expected), after=after)["control_matched"])

    def test_15_wrong_pretool_source_fails(self):
        with self.assertRaises(ValueError):
            c.classify(self.positive, [command()]*3, fake_log(self.expected), {}, {})

    def test_16_signal_rc_cannot_be_semantic_negative(self):
        with self.assertRaises(ValueError):
            self.verdict(self.negative, fake_log(self.expected, [52]), rc=-9)

    def test_17_nonzero_xsim_cannot_be_complete_negative(self):
        self.assertFalse(self.verdict(self.negative, fake_log(self.expected, [52]), rc=1)["control_matched"])

    def test_18_compile_failure_cannot_be_semantic_negative(self):
        pair = {"candidate.sv": self.negative["source_sha256"], "tb.sv": self.negative["tb_sha256"]}
        with self.assertRaises(ValueError):
            c.classify(self.negative, [command(1), command(), command()], fake_log(self.expected, [52]), pair, pair)

    def test_19_timeout_without_child_proof_incomplete(self):
        cmd = command(-9) | dict(timeout=True, group_signals=["SIGKILL"])
        self.assertFalse(c.classify(self.item("timeout"), [cmd], "", {}, {})["evidence_complete"])

    def test_20_timeout_with_parent_child_proof(self):
        cmd = command(-9) | dict(timeout=True, group_signals=["SIGKILL"], probe_evidence=cleanup())
        self.assertTrue(c.classify(self.item("timeout"), [cmd], "", {}, {})["control_matched"])

    def test_21_permission_error_is_not_missing_launcher(self):
        cmd = command(None) | dict(launch_error="[Errno 13] Permission denied")
        self.assertFalse(c.classify(self.item("launch_error"), [cmd], "", {}, {})["control_matched"])

    def test_22_fake_complete_archive_reconstruction(self):
        with self.packet() as (root, cases, deps):
            result = a.audit(root, cases, deps)
            self.assertEqual((result["actual_trace_count"], result["actual_native_commands"]), (3010, 105))
            self.assertTrue(result["native_qualified"])  # FAKE receipt gate only, no ability assertion.

    def test_23_raw_completion_binding_tampering(self):
        with self.packet() as (root, cases, deps):
            path = root/"results"/self.positive["label"]/"native_calls/0_xvlog/complete.json"
            value = c.read(path); value["argv"] = ["/FAKE/altered"]; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_24_unknown_attempt_is_not_ignored(self):
        with self.packet() as (root, cases, deps):
            extra = root/"results/FAKE_retry"; extra.mkdir(); write(extra/"attempt.json", {"FAKE": True})
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_25_first_gate_missing_source_freeze(self):
        with self.packet() as (root, cases, deps):
            spec = c.read(root/"RUN_SPEC.json"); del spec["source_hashes"]["CASE_PLAN.json"]; write(root/"RUN_SPEC.json", spec)
            with self.assertRaises(ValueError): s.frozen(root, cases, deps, root/"guard/resource_check.json", Path("/FAKE/kit"))

    def test_26_first_gate_changed_capture_bytes(self):
        with self.packet() as (root, cases, deps):
            (root/"raw_evidence/ENVIRONMENT_CAPTURE.json").write_bytes(b"{}\n")
            with self.assertRaises(ValueError): s.frozen(root, cases, deps, root/"guard/resource_check.json", Path("/FAKE/kit"))

    def test_27_terminal_summary_self_flags_not_proof(self):
        with self.packet() as (root, cases, deps):
            path = root/"results/summary.json"; value = c.read(path); value["model_calls"] = 1; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_28_log_replacement_without_physical_rebinding(self):
        with self.packet() as (root, cases, deps):
            path = root/"results"/self.positive["label"]/"native_calls/2_xsim/stdout.log"
            path.write_text("FSM_PASS checks=55\n", encoding="utf-8")
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_29_guard_sources_must_equal_frozen_capture(self):
        with self.packet() as (root, cases, deps):
            path = root/"results/guard_receipts/0001.json"; value = c.read(path)
            value["protected_sources"]["source_assets"] = 0; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_30_probe_collection_error_keeps_actual_but_refuses(self):
        with self.packet() as (root, cases, deps):
            path = root/"results/supervisor_timeout/native_calls/0_owned_supervisor/complete.json"; value = c.read(path)
            value["probe_evidence_error"] = "FAKE identity collection error"; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)
            self.assertEqual(c.read(path)["actual"]["returncode"], -9)

    def test_31_executed_stage_source_must_be_frozen(self):
        with self.packet() as (root, cases, deps):
            path = root/"RUN_SPEC.json"; value = c.read(path); del value["source_hashes"]["stage.py"]; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_32_elapsed_cannot_be_replaced_by_zero(self):
        with self.packet() as (root, cases, deps):
            path = root/"results/summary.json"; value = c.read(path); value["elapsed_s"] = 0.0; write(path, value)
            with self.assertRaises(ValueError): a.audit(root, cases, deps)

    def test_33_malformed_pid_reuse_proof_refused(self):
        proof = cleanup()
        proof["after"]["owner"]["observed"] = dict(state="S", starttime=None, pgid=56001)
        cmd = command(-9) | dict(timeout=True, group_signals=["SIGKILL"], probe_evidence=proof)
        self.assertFalse(c.classify(self.item("timeout"), [cmd], "", {}, {})["evidence_complete"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-root", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    CASE_ROOT, DEPENDENCY_ROOT = args.case_root.resolve(), args.dependency_root.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
