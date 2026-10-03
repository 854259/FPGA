"""Contract tests for the small R3 wrapper; these do not run EDA."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("r3_wrapper_tests", ROOT / "run_probe.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class R3WrapperTests(unittest.TestCase):
    def test_helper_is_pinned_and_exact_count_is_enforced(self):
        helper = runner.load_helper(ROOT / "probe_runner.py")
        self.assertEqual(helper.ROOT, ROOT)
        self.assertEqual(helper.TASK_CHECKS, {runner.TASK: 269})
        self.assertEqual(helper._parse_summary(
            "R2_PROBE_RESULT task=Prob086_lfsr5 checks=269 mismatches=0\n",
            runner.TASK), (269, 0))
        with self.assertRaises(ValueError):
            helper._parse_summary(
                "R2_PROBE_RESULT task=Prob086_lfsr5 checks=268 mismatches=0\n",
                runner.TASK)

    def test_modified_helper_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as temp:
            helper = Path(temp) / "helper.py"
            helper.write_text("raise RuntimeError('must not import')\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                runner.load_helper(helper)

    def run_mocked(self, rows):
        calls = []

        def probe(task, solution, outdir):
            calls.append(Path(outdir).name)
            return dict(rows[len(calls) - 1])

        def write_json(path, value):
            Path(path).write_text(json.dumps(value), encoding="utf-8")

        helper = types.SimpleNamespace(probe_candidate=probe, _write_json=write_json)
        with tempfile.TemporaryDirectory() as temp, patch.object(
                runner, "load_helper", return_value=helper):
            result = runner.run_validation(ROOT / "probe_runner.py", Path(temp) / "run")
            self.assertTrue((Path(temp) / "run" / "validation.json").is_file())
        return result, calls

    @staticmethod
    def row(status="pass", kind=None, checks=269, mismatches=0):
        return dict(status=status, failure_kind=kind, checks=checks, mismatches=mismatches)

    def test_valid_controls_allow_exactly_one_archived_probe(self):
        result, calls = self.run_mocked([
            self.row(), self.row("fail", "semantic_mismatch", mismatches=1),
            self.row("fail", "semantic_mismatch", mismatches=2)])
        self.assertEqual(calls, ["positive", "negative", "archived"])
        self.assertTrue(result["valid"])
        self.assertTrue(result["semantic_mismatch_observed"])

    def test_compile_failure_does_not_validate_negative_or_run_archive(self):
        result, calls = self.run_mocked([
            self.row(), self.row("fail", "xvlog_failed", checks=None, mismatches=None)])
        self.assertEqual(calls, ["positive", "negative"])
        self.assertFalse(result["valid"])
        self.assertFalse(result["controls_valid"])

    def test_archived_compile_failure_does_not_support_semantic_hypothesis(self):
        result, _ = self.run_mocked([
            self.row(), self.row("fail", "semantic_mismatch", mismatches=1),
            self.row("fail", "xelab_failed", checks=None, mismatches=None)])
        self.assertFalse(result["valid"])
        self.assertFalse(result["semantic_mismatch_observed"])

    def test_passing_archive_is_valid_negative_finding(self):
        result, _ = self.run_mocked([
            self.row(), self.row("fail", "semantic_mismatch", mismatches=1), self.row()])
        self.assertTrue(result["valid"])
        self.assertFalse(result["semantic_mismatch_observed"])

    def test_whole_state_oracle_has_specified_maximal_period(self):
        state = 1
        visited = []
        for _ in range(31):
            visited.append(state)
            state = (state // 2) ^ (20 if state % 2 else 0)
        self.assertEqual(len(set(visited)), 31)
        self.assertNotIn(0, visited)
        self.assertEqual(state, 1)
        self.assertEqual(visited[:3], [1, 20, 10])


if __name__ == "__main__":
    unittest.main()
