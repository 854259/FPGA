"""Pure invented collector gates, never real calibration evidence."""
import json
import platform
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import collect

ROOT = Path(__file__).resolve().parent


class CollectorGates(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / "invented-run"
        root.mkdir()
        (root / "results").mkdir()
        (root / "guard").mkdir()
        (root / "tools").mkdir()
        collector = Path(collect.__file__).read_bytes()
        (root / "collect.py").write_bytes(collector)
        spec = dict(source_hashes={"collect.py": collect.sha(collector)},
                    dependency_hashes={}, dependencies_cloud=str(root))
        self.save(root / "RUN_SPEC.json", spec)
        self.save(root / "PREPARATION_RECEIPT.json", {"pure_synthetic_only": True})
        summary = dict(complete=True, evidence_complete=True, error=None,
                       run_spec_sha256=collect.sha((root / "RUN_SPEC.json").read_bytes()),
                       generated_research_test=True, original_harness=False, model_calls=0,
                       actual_compile_commands=14, actual_simulation_commands=14,
                       attempted_compile_commands=14, attempted_simulation_commands=14,
                       global_native_receipts=28, unconfirmed_native_attempts=0,
                       rows=[{"invented": True}] * 14,
                       qualified_for_generated_control_discrimination=False)
        guard = dict(complete=True, passed=True, model_unchanged=True,
                     protected_files_unchanged=True, own_slot_released=True, stage_rc=0,
                     owned_cleanup=dict(verified=True, remaining=[]))
        self.save(root / "results/summary.json", summary)
        self.save(root / "guard/status.json", guard)
        return root, Path(directory) / "invented.zip", summary, guard

    @staticmethod
    def save(path, data):
        path.write_bytes((json.dumps(data, indent=2) + "\n").encode())

    def test_complete_measurement_with_false_discrimination_is_archived(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "raw_evidence") as directory:
            root, archive, _, _ = self.fixture(directory)
            result = collect.collect(root, archive)
            self.assertTrue(result["evidence_complete"])
            self.assertFalse(result["qualified_for_generated_control_discrimination"])
            with zipfile.ZipFile(archive) as out:
                manifest = json.loads(out.read("ARCHIVE_MANIFEST.json"))
                self.assertEqual(manifest["schema"], "native_reset_generated_research_archive_v1")
                self.assertFalse(manifest["original_harness"])

    def test_incomplete_unconfirmed_and_count_error_refuse(self):
        for key, value in (("evidence_complete", False), ("error", "invented failure"),
                           ("unconfirmed_native_attempts", 1), ("actual_compile_commands", 13),
                           ("attempted_compile_commands", True), ("journal_count_error", "invented extra")):
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT / "raw_evidence") as directory:
                root, archive, summary, _ = self.fixture(directory)
                summary[key] = value
                self.save(root / "results/summary.json", summary)
                with self.assertRaises(ValueError):
                    collect.collect(root, archive)
                self.assertFalse(archive.exists())

    def test_guard_failure_cleanup_or_release_refuse(self):
        for key, value in (("passed", False), ("stage_rc", 1), ("own_slot_released", False),
                           ("model_unchanged", False), ("owned_cleanup", dict(verified=True, remaining=[999]))):
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT / "raw_evidence") as directory:
                root, archive, _, guard = self.fixture(directory)
                guard[key] = value
                self.save(root / "guard/status.json", guard)
                with self.assertRaises(ValueError):
                    collect.collect(root, archive)
                self.assertFalse(archive.exists())

    def test_changed_source_and_unsafe_path_refuse(self):
        for mutation in ("source", "unsafe"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=ROOT / "raw_evidence") as directory:
                root, archive, summary, _ = self.fixture(directory)
                if mutation == "source":
                    (root / "collect.py").write_bytes(b"invented changed source")
                else:
                    spec = json.loads((root / "RUN_SPEC.json").read_bytes())
                    spec["source_hashes"]["../outside"] = "a" * 64
                    self.save(root / "RUN_SPEC.json", spec)
                    summary["run_spec_sha256"] = collect.sha((root / "RUN_SPEC.json").read_bytes())
                    self.save(root / "results/summary.json", summary)
                with self.assertRaises(ValueError):
                    collect.collect(root, archive)


class CountingResult(unittest.TextTestResult):
    subchecks = 0

    def addSubTest(self, test, subtest, outcome):
        self.subchecks += 1
        super().addSubTest(test, subtest, outcome)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountingResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CollectorGates))
    receipt = dict(status="passed" if result.wasSuccessful() else "failed",
                   python=platform.python_version(), methods=result.testsRun, subchecks=result.subchecks,
                   failures=len(result.failures), errors=len(result.errors), pure_synthetic_only=True,
                   actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False,
                   source_hashes={name: collect.sha((ROOT / name).read_bytes())
                                  for name in ("collect.py", "test_collect.py")})
    CollectorGates.save(ROOT / "COLLECT_CHECKS.json", receipt)
    print(json.dumps(receipt))
    sys.exit(0 if result.wasSuccessful() else 1)
