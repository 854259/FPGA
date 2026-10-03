"""Behavioral checks for the small wrapper; these do not substitute for EDA."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("guard_runner_under_test", ROOT / "probe_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GuardValidationTests(unittest.TestCase):
    def fake_candidate(self, task, solution, outdir):
        negative = Path(solution).name == "negative.sv"
        return {"status": "fail" if negative else "pass",
                "failure_kind": "semantic_mismatch" if negative else None,
                "checks": runner.TASK_CHECKS[task],
                "mismatches": 1 if negative else 0}

    def validate(self, fake=None):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runner, "run_candidate", side_effect=fake or self.fake_candidate) as call:
                result = runner.validate_guards(Path(tmp) / "validation")
                saved = json.loads((Path(tmp) / "validation/guards_validation.json").read_text())
            self.assertEqual(saved, result)
            return result, call

    def test_all_fifteen_expected_calls_and_hashes(self):
        result, call = self.validate()
        self.assertTrue(result["valid"])
        self.assertTrue(result["complete"])
        self.assertEqual(call.call_count, 15)
        expected = [(task, name) for task in runner.TASK_CHECKS
                    for name in ("positive.sv", "negative.sv", "candidate.sv")]
        self.assertEqual([(c.args[0], c.args[1].name) for c in call.call_args_list], expected)
        self.assertEqual(result["inherited_runner_sha256"], runner.inherited.sha256(runner.BASE_RUNNER))
        self.assertEqual(result["wrapper_sha256"], runner.inherited.sha256(ROOT / "probe_runner.py"))

    def test_archived_failure_fails_validation_without_modifying_it(self):
        def fake(task, solution, outdir):
            result = self.fake_candidate(task, solution, outdir)
            if task == "Prob009_popcount3" and solution.name == "candidate.sv":
                result.update(status="fail", failure_kind="semantic_mismatch", mismatches=2)
            return result
        before = runner.frozen_assets()
        result, call = self.validate(fake)
        self.assertFalse(result["valid"])
        self.assertEqual(call.call_count, 15)
        self.assertEqual(before, runner.frozen_assets())

    def test_negative_compile_failure_does_not_validate_probe(self):
        def fake(task, solution, outdir):
            result = self.fake_candidate(task, solution, outdir)
            if solution.name == "negative.sv":
                result.update(failure_kind="xvlog_failed", checks=None, mismatches=None)
            return result
        result, _ = self.validate(fake)
        self.assertFalse(result["valid"])

    def test_environment_error_does_not_validate_probe(self):
        def fake(task, solution, outdir):
            return {"status": "environment_error", "failure_kind": "license_error",
                    "checks": None, "mismatches": None}
        result, _ = self.validate(fake)
        self.assertFalse(result["valid"])

    def test_changed_assets_invalidate_completed_validation(self):
        initial = runner.frozen_assets()
        changed = dict(initial, changed="unexpected")
        with patch.object(runner, "frozen_assets", side_effect=[initial, changed]):
            result, _ = self.validate()
        self.assertTrue(result["complete"])
        self.assertFalse(result["valid"])
        self.assertFalse(result["assets_unchanged"])

    def test_existing_directory_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):
                runner.validate_guards(Path(tmp))

    def test_all_completed_check_counts_required(self):
        for task, count in runner.TASK_CHECKS.items():
            self.assertEqual(runner.inherited._parse_summary(
                f"R2_PROBE_RESULT task={task} checks={count} mismatches=0\n", task), (count, 0))
            with self.assertRaises(ValueError):
                runner.inherited._parse_summary(
                    f"R2_PROBE_RESULT task={task} checks={count-1} mismatches=0\n", task)

    def test_provenance_matches_exact_input_bytes(self):
        provenance = json.loads((ROOT / "provenance.json").read_text())
        self.assertEqual(set(provenance["tasks"]), set(runner.TASK_CHECKS))
        for task, files in provenance["tasks"].items():
            for name, record in files.items():
                self.assertEqual(runner.inherited.sha256(ROOT / task / name), record["sha256"])
                self.assertEqual((ROOT / task / name).stat().st_size, record["bytes"])


if __name__ == "__main__":
    unittest.main()
