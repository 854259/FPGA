"""Validation-gate behavior only: no EDA, model, or fixture modification."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fixture_gate_under_test", ROOT / "probe_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


class FixtureGateTests(unittest.TestCase):
    def execute(self, *, control_compile_failure=False, decision_override=None,
                environment_case=None):
        cases = {case["id"]: case for case in MANIFEST["cases"]}

        def fake_probe(family, solution, destination):
            solution, destination = Path(solution), Path(destination)
            if "controls" in destination.parts:
                negative = destination.name == "negative"
                if negative and control_compile_failure:
                    return dict(status="fail", failure_kind="xvlog_failed", checks=None, mismatches=None)
                return dict(status="fail" if negative else "pass",
                            failure_kind="semantic_mismatch" if negative else None,
                            checks=18, mismatches=4 if negative else 0)
            case = cases[solution.parent.name]
            if case["id"] == environment_case:
                return dict(status="environment_error", failure_kind="xsim_environment_error",
                            checks=None, mismatches=None)
            failed = case["expected_probe"] == "fail"
            return dict(status=case["expected_probe"],
                        failure_kind="semantic_mismatch" if failed else None,
                        checks=18, mismatches=4 if failed else 0)

        decisions = []
        for case in MANIFEST["cases"]:
            decision = case["expected_decision"]
            if decision == "no_review":
                decision = "skip"
            if decision_override and case["id"] in decision_override:
                decision = decision_override[case["id"]]
            decisions.append({"decision": decision})
        selector = SimpleNamespace(analyze=Mock(side_effect=decisions))
        helper = SimpleNamespace(probe_candidate=Mock(side_effect=fake_probe),
                                 _write_json=lambda path, obj: Path(path).write_text(json.dumps(obj)))
        # Real manifest, real fixed-file hashes, and real output lifecycle remain
        # active. Only EDA execution and classification outcomes are substituted.
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "fresh"
            with patch.object(runner, "load", side_effect=lambda name, path:
                              helper if name == "r2b_inherited" else selector):
                result = runner.run(ROOT / "probe_runner.py", output)
            self.assertEqual(json.loads((output / "validation.json").read_text()), result)
        return result, helper, selector

    def test_negative_compile_failure_stops_before_candidates(self):
        result, helper, selector = self.execute(control_compile_failure=True)
        self.assertFalse(result["valid"])
        self.assertFalse(result["controls_valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(helper.probe_candidate.call_count, 2)
        selector.analyze.assert_not_called()

    def test_out_of_scope_errors_remain_failed_probes_and_explicit_abstentions(self):
        result, helper, _ = self.execute()
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["cases"]), 12)
        self.assertEqual(helper.probe_candidate.call_count, 18)
        failed = [row for row in result["cases"] if row["probe"]["status"] == "fail"]
        self.assertEqual(len(failed), 5)
        self.assertEqual(sum(row["classification"]["decision"] == "review" for row in failed), 2)
        abstained = [row for row in failed if row["classification"]["decision"] == "abstain"]
        self.assertEqual({row["case"]["id"] for row in abstained},
                         {"signed_part_select8", "macro_unsigned8", "explicit_unsigned_cast8"})
        self.assertTrue(all(row["passed"] for row in abstained))

    def test_missing_in_scope_error_is_not_accepted_as_valid_abstention(self):
        result, _, _ = self.execute(decision_override={"unsigned8": "abstain"})
        self.assertTrue(result["complete"])
        self.assertTrue(result["controls_valid"])
        self.assertFalse(result["valid"])
        first = result["cases"][0]
        self.assertEqual(first["probe"]["status"], "fail")
        self.assertFalse(first["passed"])

    def test_candidate_environment_error_does_not_finish_or_shrink_denominator(self):
        result, helper, _ = self.execute(environment_case="unsigned8")
        self.assertTrue(result["controls_valid"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["valid"])
        self.assertEqual(helper.probe_candidate.call_count, 7)
        self.assertEqual(len(result["cases"]), 1)
        self.assertEqual(result["cases"][0]["probe"]["status"], "environment_error")
        self.assertFalse(result["cases"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
