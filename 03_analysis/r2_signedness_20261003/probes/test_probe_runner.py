"""Behavior tests with fake stage outputs; real Vivado controls remain required."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("r2_probe_runner_tested", ROOT / "probe_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ProbeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outdir = Path(self.tmp.name) / "new"
        self.task = "Prob115_shift18"
        self.solution = ROOT / self.task / "positive.sv"

    def run_fake(self, summary=None, fail_stage=None, fail_text="ERROR: candidate syntax",
                 timeout_stage=None):
        if summary is None:
            summary = "R2_PROBE_RESULT task=Prob115_shift18 checks=31 mismatches=0\n"

        def stage(name, argv, outdir):
            text = (summary if name == "xsim" else "stage completed\n")
            if name == fail_stage:
                text = fail_text
            log = outdir / (name + ".log")
            log.write_text(text, encoding="utf-8")
            return {"name": name, "argv": argv, "timeout": name == timeout_stage,
                    "returncode": 1 if name == fail_stage else 0,
                    "launch_error": None, "group_signals": [], "elapsed_s": 0.1,
                    "log": str(log), "log_sha256": runner.sha256(log),
                    "log_bytes": log.stat().st_size}

        with patch.object(runner, "IS_POSIX", True), patch.object(runner, "_run_stage", stage):
            return runner.probe_candidate(self.task, self.solution, self.outdir)

    def test_completed_pass_preserves_inputs_and_logs(self):
        result = self.run_fake()
        self.assertEqual(result["status"], "pass")
        self.assertEqual((result["checks"], result["mismatches"]), (31, 0))
        self.assertTrue(result["inputs_unchanged"])
        self.assertEqual(len(result["stages"]), 3)
        self.assertEqual(json.loads((self.outdir / "result.json").read_text()), result)
        self.assertEqual((self.outdir / "dut.sv").read_bytes(), self.solution.read_bytes())

    def test_completed_semantic_failure(self):
        result = self.run_fake("R2_PROBE_RESULT task=Prob115_shift18 checks=31 mismatches=2\n")
        self.assertEqual((result["status"], result["failure_kind"]), ("fail", "semantic_mismatch"))

    def test_compile_failure_is_not_semantic_failure(self):
        result = self.run_fake(fail_stage="xvlog")
        self.assertEqual((result["status"], result["failure_kind"]), ("fail", "xvlog_failed"))
        self.assertIsNone(result["checks"])
        self.assertEqual(len(result["stages"]), 1)

    def test_license_failure_is_environment_error(self):
        result = self.run_fake(fail_stage="xelab", fail_text="ERROR: License checkout failed")
        self.assertEqual(result["status"], "environment_error")

    def test_timeout_is_environment_error(self):
        result = self.run_fake(timeout_stage="xsim")
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("environment_error", "xsim_environment_error"))

    def test_missing_completion_is_not_pass(self):
        result = self.run_fake("simulation stopped before completion\n")
        self.assertEqual((result["status"], result["failure_kind"]),
                         ("environment_error", "probe_protocol_error"))

    def test_duplicate_or_wrong_counts_rejected(self):
        for text in ("R2_PROBE_RESULT task=Prob115_shift18 checks=30 mismatches=0\n",
                     "R2_PROBE_RESULT task=Prob115_shift18 checks=31 mismatches=32\n",
                     "R2_PROBE_RESULT task=Prob115_shift18 checks=31 mismatches=0\n" * 2):
            with self.subTest(text=text), self.assertRaises(ValueError):
                runner._parse_summary(text, self.task)

    def test_existing_directory_is_not_overwritten(self):
        self.outdir.mkdir()
        sentinel = self.outdir / "keep.txt"
        sentinel.write_text("original")
        with self.assertRaises(FileExistsError):
            self.run_fake()
        self.assertEqual(sentinel.read_text(), "original")

    def test_negative_compile_error_cannot_validate_controls(self):
        def fake_probe(task, solution, outdir):
            if Path(solution).name == "positive.sv":
                return {"status": "pass", "failure_kind": None}
            return {"status": "fail", "failure_kind": "xvlog_failed"}
        with patch.object(runner, "probe_candidate", fake_probe):
            result = runner.validate_controls(self.outdir)
        self.assertTrue(result["complete"])
        self.assertFalse(result["valid"])
        self.assertTrue(all(not row["valid"] for row in result["tasks"].values()))


if __name__ == "__main__":
    unittest.main()
