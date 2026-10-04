"""Checks that diagnostic evidence cannot silently turn an invalid check into PASS."""
import hashlib
import unittest

from diagnostics import analyze, calibration, extract_messages, inspect_report


class DiagnosticEvidenceTests(unittest.TestCase):
    def test_zero_fault_controls_disable_clean_claim(self):
        rows = [dict(case=name, configuration="csv", mode="lint", role=role,
                     tool_execution_valid=True, linter_counts=[0])
                for name, role in [("fault_a", "diagnostic_positive"), ("fault_b", "diagnostic_positive"),
                                   ("clean", "diagnostic_negative")]]
        self.assertFalse(calibration(rows, "csv")["verified"])

    def test_missing_positive_control_is_not_verified(self):
        rows = [dict(case="a", configuration="csv", mode="lint", role="diagnostic_positive",
                     tool_execution_valid=True, linter_counts=[2]),
                dict(case="clean", configuration="csv", mode="lint", role="diagnostic_negative",
                     tool_execution_valid=True, linter_counts=[0])]
        self.assertFalse(calibration(rows, "csv")["verified"])

    def test_expected_warning_on_modulo_design_is_not_functional_failure(self):
        source = b"module TopModule;\nendmodule\n"
        log = b"WARNING: [Synth 37-78] arithmetic overflow [/owned/candidate.sv:1]\n"
        row = dict(case="modulo", configuration="csv", mode="lint", tool_execution_valid=True,
                   linter_counts=[1], report_parse_verified=True, source_sha256=hashlib.sha256(source).hexdigest(),
                   log_sha256=hashlib.sha256(log).hexdigest())
        result = analyze(row, log, source, "/owned/candidate.sv", {"configuration": "csv", "verified": True})
        self.assertEqual(result["functional_correctness"], "unknown")
        self.assertFalse(result["automatic_repair_authorized"])

    def test_only_real_exact_source_location_is_bound(self):
        log = "\n".join(["WARNING: [Synth 8-327] latch [/owned/candidate.sv:2]",
                         "WARNING: [Synth 8-327] latch [/other/candidate.sv:2]",
                         "WARNING: [Synth 8-327] latch [/owned/candidate.sv:99]"])
        rows = extract_messages(log, "module TopModule;\nendmodule", "/owned/candidate.sv")
        self.assertEqual([x["source_location_verified"] for x in rows], [True, False, False])
        self.assertIsNone(rows[1]["context"])

    def test_duplicate_messages_keep_both_log_locations(self):
        line = "WARNING: [Synth 8-3848] no driver [/owned/candidate.sv:1]"
        rows = extract_messages(line + "\n" + line, "module TopModule;", "/owned/candidate.sv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["occurrences"], 2)
        self.assertEqual(rows[0]["log_lines"], [1, 2])

    def test_changed_source_or_log_rejected(self):
        source, log = b"module TopModule; endmodule", b""
        row = dict(case="clean", configuration="csv", mode="lint", tool_execution_valid=True,
                   linter_counts=[0], source_sha256=hashlib.sha256(source).hexdigest(),
                   log_sha256=hashlib.sha256(log).hexdigest())
        cap = {"configuration": "csv", "verified": False}
        with self.assertRaises(ValueError):
            analyze(row, log, source + b" ", "/owned/candidate.sv", cap)
        with self.assertRaises(ValueError):
            analyze(row, log + b"changed", source, "/owned/candidate.sv", cap)

    def test_failed_tool_never_becomes_zero_pass(self):
        source, log = b"module TopModule; endmodule", b"ERROR: [Common 17-69] unavailable"
        row = dict(case="clean", configuration="csv", mode="lint", tool_execution_valid=False,
                   linter_counts=[0], source_sha256=hashlib.sha256(source).hexdigest(),
                   log_sha256=hashlib.sha256(log).hexdigest())
        result = analyze(row, log, source, "/owned/candidate.sv", {"configuration": "csv", "verified": False})
        self.assertEqual(result["status"], "tool_failed")

    def test_empty_report_cannot_swallow_nonzero_count(self):
        self.assertTrue(inspect_report("", 0)["verified"])
        self.assertFalse(inspect_report("", 3)["verified"])

    def test_csv_quoted_comma_preserves_seven_columns(self):
        row = 'ASSIGN-2,"signed, unsigned",op,info,TopModule,candidate.sv,5\n'
        result = inspect_report(row, 1)
        self.assertTrue(result["verified"])
        self.assertEqual(result["rows"][0][1], "signed, unsigned")
        self.assertFalse(inspect_report(row, 0)["verified"])

    def test_unrecognized_or_corrupt_report_cannot_mean_zero(self):
        self.assertFalse(inspect_report("report generation failed", 0)["verified"])
        self.assertFalse(inspect_report('{"cols": []}', 0)["verified"])
        self.assertFalse(inspect_report("ASSIGN-2,x,y,extra,comma,TopModule,file,5", 1)["verified"])


if __name__ == "__main__":
    unittest.main()
