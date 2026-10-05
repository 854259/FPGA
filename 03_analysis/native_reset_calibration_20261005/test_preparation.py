"""Pure/synthetic draft preparation tests: 0 model/0 EDA, no RTL qualification."""
import ast
import copy
import io
import json
import platform
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import audit
import calibration as c
import native_reset_contract as n
import stage

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"
SOURCES = ("native_reset_contract.py", "tool_journal.py", "calibration.py", "stage.py", "audit.py", "test_preparation.py")


def j(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def synthetic_log(contract, control, mismatching=False):
    lines = [f'NRC_BEGIN {n._prefix(contract, control["run_id"])} observations=69']
    count = 0
    for row in contract["observations"]:
        values = [str(row["expected_rising"]), str(row["expected_falling"])]
        if mismatching and row["index"] == 11:
            values[0] = str(1 - row["expected_rising"])
        lines.append(n._observation_prefix(row) + f" observed_rising={values[0]} observed_falling={values[1]}")
        for role, value in zip(("rising", "falling"), values):
            if value != str(row["expected_" + role]):
                if count == 0:
                    lines.append(f'NRC_FIRST index={row["index"]} output={contract["roles"][role]} expected={row["expected_" + role]} observed={value}')
                count += 1
    lines.append(f'NRC_END {n._prefix(contract, control["run_id"])} observations=69 mismatches={count}')
    if control["intent"] == "sentinel" and not mismatching:
        lines.append(c.SENTINEL)
    return "\n".join(lines) + "\n"


def fixture_files(wrong_pass=False):
    """Entirely invented receipts/blob/identities; never native evidence."""
    private, cases = c.validate_private(ROOT)
    cloud = "/pure-synthetic/native-reset"
    files = {"run/" + name: (ROOT / name).read_bytes() for name in SOURCES}
    files["run/raw_evidence/CONTROLS.json"] = (RAW / "CONTROLS.json").read_bytes()
    for control, contract, rtl, tb in cases:
        for key in ("prompt_path", "rtl_path", "tb_path"):
            files["run/" + control[key]] = (ROOT / control[key]).read_bytes()
    spec = dict(cloud_root=cloud, inherited_path="/pure/synthetic/bin", toolchain=dict(prefix="/pure/synthetic/tools"),
                real_tools=dict(iverilog=dict(path="/pure/synthetic/iverilog", sha256="c" * 64),
                                vvp=dict(path="/pure/synthetic/vvp", sha256="d" * 64)),
                source_hashes={name[4:]: c.sha(data) for name, data in files.items()},
                dependency_hashes={"paired_checkpoint.py": c.sha(b"PURE_SYNTHETIC_DEPENDENCY\n")},
                model_requests_max=0, controls=14, compiles_max=14, simulations_max=14,
                model_identity=dict(pid=123, starttime=456), slot_owner="pure-synthetic-owner",
                slot_lock_path="/pure/synthetic/lock", llm_base_url="unused-synthetic-address", model_name="unused")
    files["dependencies/paired_checkpoint.py"] = b"PURE_SYNTHETIC_DEPENDENCY\n"
    files["run/RUN_SPEC.json"] = j(spec)
    spec_sha = c.sha(files["run/RUN_SPEC.json"])
    files["run/tools/bin/iverilog"] = files["run/tools/bin/vvp"] = (ROOT / "tool_journal.py").read_bytes()
    files["run/INPUT_MANIFEST.json"] = j(dict(input_sha256={}, official_sha256={}))
    resource = {key: spec[key] for key in ("model_identity", "slot_owner", "slot_lock_path", "llm_base_url", "model_name")}
    resource.update(model_pid=123, model_starttime=456, protected=dict(tasks={}, official={}))
    files["run/guard/resource_check.json"] = j(resource)
    files["run/guard/status.json"] = j(dict(complete=True, passed=True, model_unchanged=True,
         protected_files_unchanged=True, own_slot_released=True, stage_rc=0,
         owned_cleanup=dict(verified=True, remaining=[])))
    rows = []
    for control, contract, rtl, tb in cases:
        label = control["label"]
        base, folder = "run/results/" + label + "/", cloud + "/results/" + label
        hashes = {"candidate.sv": c.sha(rtl), "tb.sv": c.sha(tb)}
        files[base + "candidate.sv"], files[base + "tb.sv"] = rtl, tb
        files[base + "SOURCE_MANIFEST.json"] = j(hashes)
        blob = ("#! PURE_SYNTHETIC_NONEXECUTABLE_PLACEHOLDER " + label + "\n").encode()
        files[base + "compiled.vvp"] = files[base + "native_receipts/build.compiled.vvp"] = blob
        negative = control["intent"] == "wrong" and not (wrong_pass and label == "reset_ignored")
        stdout = synthetic_log(contract, control, negative).encode()
        rc = 1 if negative or control["intent"] == "sentinel" else 0
        build_args = ["-g2012", "-s", control["probe_module"], "-o", folder + "/compiled.vvp", folder + "/candidate.sv", folder + "/tb.sv"]
        sim_args = [folder + "/compiled.vvp"]
        for tool, args, code, output, token, started in (("iverilog", build_args, 0, b"", "build", 100),
                                                       ("vvp", sim_args, rc, stdout, "sim", 200)):
            files[base + "native_receipts/" + token + ".stdout"] = output
            files[base + "native_receipts/" + token + ".stderr"] = b""
            inputs = {folder + "/" + name: digest for name, digest in hashes.items()} if tool == "iverilog" else {folder + "/compiled.vvp": c.sha(blob)}
            artifacts = dict(compiled=dict(path="build.compiled.vvp", sha256=c.sha(blob), original_path=folder + "/compiled.vvp")) if tool == "iverilog" else {}
            receipt = dict(schema="owned_native_journal_v1", name=tool, argv=[spec["real_tools"][tool]["path"], *args], cwd=folder,
                           executable_sha256=spec["real_tools"][tool]["sha256"], returncode=code,
                           source_input_sha256=inputs, artifacts=artifacts, xmls=[], started_ns=started,
                           stdout=dict(path=token + ".stdout", sha256=c.sha(output), bytes=len(output)),
                           stderr=dict(path=token + ".stderr", sha256=c.sha(b""), bytes=0))
            files[base + "native_receipts/" + token + ".json"] = j(receipt)
        files[base + "compile.outer.log"] = b""
        files[base + "simulation.outer.log"] = stdout
        clean_env = dict(PATH=cloud + "/tools/bin:" + spec["toolchain"]["prefix"] + "/bin:" + spec["inherited_path"],
                         PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", OWN_CALIBRATION_ROOT=cloud,
                         OWN_NATIVE_JOURNAL=folder + "/native_receipts")
        clean = ["/usr/bin/env", "-i", *[key + "=" + value for key, value in clean_env.items()]]
        classified = c.classify(control, contract, stdout.decode(), "", rc)
        files[base + "PARSED.json"] = j(classified)

        def outer(logfile, code):
            output = files[base + logfile]
            return dict(log=folder + "/" + logfile, log_sha256=c.sha(output), log_bytes=len(output),
                        timeout=False, launch_error=None, remaining_live_group=False, returncode=code)

        rows.append(dict(index=control["index"], label=label, intent=control["intent"],
                         generated_research_test=True, original_harness=False,
                         compile_outer=outer("compile.outer.log", 0), simulation_outer=outer("simulation.outer.log", rc),
                         compile_outer_argv=clean + [cloud + "/tools/bin/iverilog", *build_args],
                         simulation_outer_argv=clean + [cloud + "/tools/bin/vvp", *sim_args],
                         parsed_sha256=c.sha(files[base + "PARSED.json"]), control_matched=classified["control_matched"],
                         false_acceptance=classified["false_acceptance"], checks=69,
                         mismatches=classified["parsed"]["mismatches"]))
    files["run/results/summary.json"] = j(dict(complete=True, evidence_complete=True, error=None, rows=rows,
         run_spec_sha256=spec_sha, qualified_for_generated_control_discrimination=all(row["control_matched"] for row in rows),
         actual_compile_commands=14, actual_simulation_commands=14, model_calls=0, independent_model_tasks=0,
         attempted_compile_commands=14, attempted_simulation_commands=14, unconfirmed_native_attempts=0,
         independent_quality_admitted=0, eligible_for_independent_models=False, adoption=False,
         generated_research_test=True, original_harness=False, source_unchanged=True, dependencies_unchanged=True))
    return files, spec_sha


def archive_bytes(files, spec_sha):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("ARCHIVE_MANIFEST.json", j(dict(files={name: c.sha(data) for name, data in files.items()}, run_spec_sha256=spec_sha)))
    return payload.getvalue()


class Preparation(unittest.TestCase):
    """All controls/receipts are static or synthetic; no RTL execution."""
    def setUp(self):
        self.private, self.cases = c.validate_private(ROOT)

    def test_byte_exact_delivered_parser_and_transparent_journal(self):
        self.assertEqual(c.sha((ROOT / "native_reset_contract.py").read_bytes()), c.PARSER_SHA)
        self.assertEqual(c.sha((ROOT / "tool_journal.py").read_bytes()), "ec07a0cb78495de1daee9611fb06e906ff319189fd239a91e41e52f58a67c465")

    def test_all_sources_are_python_parseable_without_execution(self):
        for name in SOURCES:
            with self.subTest(source=name):
                ast.parse((ROOT / name).read_text(encoding="utf-8"))

    def test_all14_fixed_controls_original_and_renamed_complete_abi(self):
        self.assertEqual(tuple(case[0]["label"] for case in self.cases), c.ORDER)
        self.assertEqual(len(self.cases), 14)
        for control, contract, rtl, tb in self.cases:
            with self.subTest(label=control["label"]):
                text = rtl.decode()
                self.assertEqual(re.findall(r"\bmodule\s+(\w+)", text), [contract["module"]])
                self.assertEqual(set(re.findall(r"\binput wire (\w+)", text)), {contract["roles"][key] for key in ("clock", "reset", "data")})
                self.assertEqual(set(re.findall(r"\boutput (?:reg|wire) (\w+)", text)), {contract["roles"][key] for key in ("rising", "falling")})
                self.assertNotIn("initial", text)
                self.assertNotIn("$display", text)
                self.assertEqual(tb.decode().count('$display("NRC_OBS '), 69)
                self.assertTrue(control["generated_research_test"])
                self.assertFalse(control["original_harness"])
                parsed = c.classify(control, contract, synthetic_log(contract, control, control["intent"] == "wrong"), "", control["expected_vvp_rc"])
                self.assertTrue(parsed["control_matched"])
                self.assertTrue(parsed["returncode_consistent"])
                self.assertEqual(len(parsed["parsed"]["observations"]), 69)
                self.assertTrue(all("observed_rising" in row and "observed_falling" in row for row in parsed["parsed"]["observations"]))

    def test_renamed_case_all_six_names_differ_and_prompt_reparsed(self):
        old, new = self.cases[0][1], self.cases[-1][1]
        self.assertNotEqual(old["module"], new["module"])
        self.assertTrue(all(old["roles"][role] != new["roles"][role] for role in n.ROLE_NAMES))
        self.assertEqual(old["observations"], new["observations"])

    def test_wrong_control_text_distinctions_static_only(self):
        rtl = {control["label"]: raw.decode() for control, _, raw, _ in self.cases}
        self.assertNotIn("negedge i_rstb", rtl["reset_ignored"])
        self.assertNotIn("if (!i_rstb)", rtl["reset_ignored"])
        self.assertNotIn("negedge i_rstb", rtl["synchronous_reset"])
        self.assertIn("always @(posedge i_clk)", rtl["history_sync_only"])
        self.assertEqual(rtl["clear_rising_only"].count("negedge i_rstb"), 2)
        self.assertEqual(rtl["clear_falling_only"].count("negedge i_rstb"), 2)
        self.assertIn("| _control_rise_delay", rtl["two_cycle_pulse"])
        self.assertIn("o_positive_edge_detected<=_control_rise_delay", rtl["one_cycle_late"])
        self.assertIn("always @(negedge i_clk or negedge i_rstb)", rtl["negedge_sample"])
        self.assertEqual(rtl["positive"], rtl["failure_propagation"])

    def test_sentinel_marker_exact_once_after_complete_result(self):
        control, contract, rtl, tb = self.cases[12]
        text = tb.decode()
        self.assertEqual(text.count('$display("' + c.SENTINEL + '")'), 1)
        self.assertGreater(text.index('$display("' + c.SENTINEL), text.index('$display("NRC_END'))
        passing = synthetic_log(contract, control)
        self.assertTrue(c.classify(control, contract, passing, "", 1)["control_matched"])
        self.assertFalse(c.classify(control, contract, passing.replace(c.SENTINEL + "\n", ""), "", 1)["returncode_consistent"])
        self.assertFalse(c.classify(control, contract, passing + c.SENTINEL + "\n", "", 1)["control_matched"])

    def test_wrong_pass_is_preserved_and_disqualified_not_measurement_loss(self):
        control, contract, _, _ = self.cases[1]
        result = c.classify(control, contract, synthetic_log(contract, control), "", 0)
        self.assertTrue(result["false_acceptance"])
        self.assertTrue(result["returncode_consistent"])
        self.assertFalse(result["control_matched"])

    def test_unknown_rc_or_truncation_rejected_and_mismatch_rc0_inconsistent(self):
        control, contract, _, _ = self.cases[1]
        log = synthetic_log(contract, control, True)
        for code in (2, -9, False, 1.0, "1", None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                c.classify(control, contract, log, "", code)
        with self.assertRaises(ValueError):
            c.classify(control, contract, log[:log.index("NRC_END")], "", 1)
        self.assertFalse(c.classify(control, contract, log, "", 0)["returncode_consistent"])

    def test_full_synthetic_archive_audit_and_false_acceptance_distinct(self):
        for wrong_pass in (False, True):
            with self.subTest(wrong_pass=wrong_pass):
                files, spec_sha = fixture_files(wrong_pass)
                path = RAW / ("PURE_SYNTHETIC_AUDIT_FALSE_ACCEPT.zip" if wrong_pass else "PURE_SYNTHETIC_AUDIT_PASS.zip")
                path.write_bytes(archive_bytes(files, spec_sha))
                result = audit.audit(path, spec_sha)
                self.assertTrue(result["evidence_complete"])
                self.assertEqual(result["qualified_for_generated_control_discrimination"], not wrong_pass)
                self.assertEqual(len(result["controls"]), 14)
                self.assertEqual(result["global_native_receipts"], 28)
                self.assertEqual(result["attempted_compile_commands"], 14)
                self.assertEqual(result["attempted_simulation_commands"], 14)
                self.assertEqual(result["unconfirmed_native_attempts"], 0)
                self.assertEqual(sum(row["false_acceptance"] for row in result["controls"]), int(wrong_pass))
                c.save(RAW / (path.stem + ".json"), dict(pure_synthetic_fixture=True, actual_model_calls=0, actual_eda_calls=0,
                                                       actual_native_commands=0, no_quality_qualification=True, parsed_fixture=result))

    def test_synthetic_archive_receipt_tampering_rejected(self):
        original, spec_sha = fixture_files()
        prefix = "run/results/reset_ignored/"
        mutations = []
        bad = copy.deepcopy(original)
        receipt = json.loads(bad[prefix + "native_receipts/sim.json"])
        receipt["returncode"] = 0
        bad[prefix + "native_receipts/sim.json"] = j(receipt)
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad[prefix + "native_receipts/extra.json"] = bad[prefix + "native_receipts/sim.json"]
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad[prefix + "compiled.vvp"] += b"TAMPER"
        mutations.append(bad)
        bad = copy.deepcopy(original)
        bad[prefix + "candidate.sv"] += b"\n"
        mutations.append(bad)
        bad = copy.deepcopy(original)
        receipt = json.loads(bad[prefix + "native_receipts/build.json"])
        receipt["argv"].append("UNKNOWN_TOOL_OPTION")
        bad[prefix + "native_receipts/build.json"] = j(receipt)
        mutations.append(bad)
        bad = copy.deepcopy(original)
        summary = json.loads(bad["run/results/summary.json"])
        summary["rows"].pop()
        bad["run/results/summary.json"] = j(summary)
        mutations.append(bad)
        bad = copy.deepcopy(original)
        guard = json.loads(bad["run/guard/status.json"])
        guard["own_slot_released"] = False
        bad["run/guard/status.json"] = j(guard)
        mutations.append(bad)
        for index, payload in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                path = RAW / "PURE_SYNTHETIC_AUDIT_TAMPER.zip"
                path.write_bytes(archive_bytes(payload, spec_sha))
                audit.audit(path, spec_sha)

    def test_global_extra_misplaced_or_unknown_native_receipts_rejected(self):
        original, spec_sha = fixture_files()
        receipt_name = "run/results/positive/native_receipts/sim.json"
        extra_paths = ("run/results/unlisted/native_receipts/extra.json",
                       "run/results/unlisted/native_receipts/orphan.stdout",
                       "run/results/positive/nested/native_receipts/extra.json",
                       "run/results/positive/native_receipts/nested/extra.json",
                       "run/results/positive/native_receipts/extra.json",
                       "run/results/unlisted/tool.json", "run/results/extra_native.json")
        mutations = []
        for path in extra_paths:
            bad = copy.deepcopy(original)
            bad[path] = bad[receipt_name]
            mutations.append(bad)
        bad = copy.deepcopy(original)
        bad["run/results/unlisted/moved_sim.json"] = bad.pop(receipt_name)
        mutations.append(bad)
        for tool in ("unknown_tool", "iverilog"):
            bad = copy.deepcopy(original)
            receipt = json.loads(bad[receipt_name])
            receipt["name"] = tool
            bad[receipt_name] = j(receipt)
            mutations.append(bad)
        for index, files in enumerate(mutations):
            with self.subTest(global_mutation=index), self.assertRaises(ValueError):
                path = RAW / "PURE_SYNTHETIC_AUDIT_GLOBAL_RECEIPT_TAMPER.zip"
                path.write_bytes(archive_bytes(files, spec_sha))
                audit.audit(path, spec_sha)

    def test_attempted_unconfirmed_or_count_error_summary_rejected(self):
        original, spec_sha = fixture_files()
        changes = (("attempted_compile_commands", 15), ("attempted_compile_commands", 13),
                   ("attempted_compile_commands", True), ("attempted_compile_commands", 14.0),
                   ("attempted_simulation_commands", 15), ("attempted_simulation_commands", 13),
                   ("actual_compile_commands", 13), ("actual_compile_commands", 14.0),
                   ("actual_simulation_commands", 15), ("actual_simulation_commands", 14.0),
                   ("unconfirmed_native_attempts", 1), ("unconfirmed_native_attempts", -1),
                   ("unconfirmed_native_attempts", False), ("journal_count_error", None),
                   ("journal_count_error", "synthetic count failure"), ("evidence_complete", 1))
        for field, value in changes:
            files = copy.deepcopy(original)
            summary = json.loads(files["run/results/summary.json"])
            summary[field] = value
            files["run/results/summary.json"] = j(summary)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                path = RAW / "PURE_SYNTHETIC_AUDIT_ATTEMPT_TAMPER.zip"
                path.write_bytes(archive_bytes(files, spec_sha))
                audit.audit(path, spec_sha)
        for field in ("attempted_compile_commands", "attempted_simulation_commands", "unconfirmed_native_attempts"):
            files = copy.deepcopy(original)
            summary = json.loads(files["run/results/summary.json"])
            summary.pop(field)
            files["run/results/summary.json"] = j(summary)
            with self.subTest(missing_field=field), self.assertRaises(ValueError):
                path = RAW / "PURE_SYNTHETIC_AUDIT_ATTEMPT_TAMPER.zip"
                path.write_bytes(archive_bytes(files, spec_sha))
                audit.audit(path, spec_sha)

    def test_stage_global_count_confirmation_before_success(self):
        files, _ = fixture_files()
        with tempfile.TemporaryDirectory(dir=RAW, prefix="pure_count_") as directory:
            out = Path(directory).resolve()
            self.assertTrue(out.is_relative_to(RAW.resolve()))
            for name, data in files.items():
                if name.startswith("run/results/") and "/native_receipts/" in name and name.endswith(".json"):
                    path = out / name.removeprefix("run/results/")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            summary = json.loads(files["run/results/summary.json"])
            stage.recount_native(out, summary, require_complete=True)
            self.assertEqual(summary["global_native_receipts"], 28)
            self.assertEqual((summary["actual_compile_commands"], summary["actual_simulation_commands"]), (14, 14))
            self.assertEqual(summary["unconfirmed_native_attempts"], 0)
            stage.final_accounting(out, summary)
            self.assertTrue(summary["complete"])
            self.assertTrue(summary["evidence_complete"])

    def test_stage_final_count_failure_revokes_success_and_overrides_rc0(self):
        files, _ = fixture_files()
        for mutation in ("missing", "duplicate", "unlisted", "unlisted_flat", "unknown", "malformed", "attempt_compile_13",
                         "attempt_sim_15", "attempt_bool", "prior_count_error"):
            with self.subTest(stage_mutation=mutation), tempfile.TemporaryDirectory(dir=RAW, prefix="pure_count_") as directory:
                out = Path(directory).resolve()
                self.assertTrue(out.is_relative_to(RAW.resolve()))
                for name, data in files.items():
                    if name.startswith("run/results/") and "/native_receipts/" in name and name.endswith(".json"):
                        path = out / name.removeprefix("run/results/")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                summary = json.loads(files["run/results/summary.json"])
                target = out / "positive/native_receipts/sim.json"
                if mutation == "missing":
                    target.unlink()
                elif mutation == "duplicate":
                    (target.parent / "extra.json").write_bytes(target.read_bytes())
                elif mutation == "unlisted":
                    extra = out / "unlisted/native_receipts/extra.json"
                    extra.parent.mkdir(parents=True)
                    extra.write_bytes(target.read_bytes())
                elif mutation == "unlisted_flat":
                    extra = out / "unlisted/tool.json"
                    extra.parent.mkdir(parents=True)
                    extra.write_bytes(target.read_bytes())
                elif mutation == "unknown":
                    receipt = json.loads(target.read_bytes())
                    receipt["name"] = "unknown"
                    target.write_bytes(j(receipt))
                elif mutation == "malformed":
                    target.write_bytes(b"[")
                elif mutation == "attempt_compile_13":
                    summary["attempted_compile_commands"] = 13
                elif mutation == "attempt_sim_15":
                    summary["attempted_simulation_commands"] = 15
                elif mutation == "attempt_bool":
                    summary["attempted_compile_commands"] = True
                else:
                    summary["journal_count_error"] = "synthetic prior count failure"

                def pending_success():
                    try:
                        return 0
                    finally:
                        stage.final_accounting(out, summary)

                with self.assertRaises(ValueError):
                    pending_success()
                self.assertFalse(summary["complete"])
                self.assertFalse(summary["evidence_complete"])
                self.assertFalse(summary["qualified_for_generated_control_discrimination"])
                self.assertTrue(summary["error"])
                self.assertIn("journal_count_error", summary)

    def test_stage_partial_unconfirmed_attempt_remains_failed_without_retry(self):
        with tempfile.TemporaryDirectory(dir=RAW, prefix="pure_count_") as directory:
            out = Path(directory).resolve()
            self.assertTrue(out.is_relative_to(RAW.resolve()))
            summary = dict(complete=False, evidence_complete=False, qualified_for_generated_control_discrimination=False,
                           error="synthetic original timeout", attempted_compile_commands=1, attempted_simulation_commands=0)
            stage.final_accounting(out, summary)
            self.assertEqual(summary["unconfirmed_native_attempts"], 1)
            self.assertEqual((summary["actual_compile_commands"], summary["actual_simulation_commands"]), (0, 0))
            self.assertEqual(summary["error"], "synthetic original timeout")
            self.assertFalse(summary["complete"])
            self.assertFalse(summary["evidence_complete"])

    def test_wrong_order_or_intent_and_unsafe_path_rejected(self):
        control = copy.deepcopy(self.cases[1][0])
        for field, value in (("intent", "positive"), ("expected_vvp_rc", 0),
                             ("generated_research_test", False), ("original_harness", True),
                             ("expected_semantic_status", "semantic_pass")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                changed = dict(control)
                changed[field] = value
                c.validate_control_metadata(changed, 1)
        for path in ("../elsewhere", "/absolute", "bad\\path"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                c.contained(ROOT, path)


class CountingResult(unittest.TextTestResult):
    subtests = 0

    def addSubTest(self, test, subtest, outcome):
        self.subtests += 1
        super().addSubTest(test, subtest, outcome)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountingResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Preparation))
    receipt = dict(status="passed" if result.wasSuccessful() else "failed", python=platform.python_version(),
                   tests=result.testsRun, subtests=result.subtests, failures=len(result.failures), errors=len(result.errors),
                   pure_synthetic_only=True, actual_model_calls=0, actual_eda_calls=0, actual_native_commands=0,
                   actual_fifo_submitted=False, generated_research_test=True, original_harness=False,
                   planned_controls=14, planned_compiles=14, planned_simulations=14,
                   independent_quality_admitted=0, qualified_for_generated_control_discrimination=False, adoption=False,
                   source_sha256={name: c.sha((ROOT / name).read_bytes()) for name in SOURCES})
    c.save(ROOT / "LOCAL_CHECKS.json", receipt)
    print(json.dumps(receipt, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
