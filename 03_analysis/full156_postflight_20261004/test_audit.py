"""Adversarial integrity checks on a real partial snapshot; no model/EDA."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import audit

SNAPSHOT = None


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(SNAPSHOT) as bundle:
            cls.raw = {name: bundle.read(name) for name in bundle.namelist()}
        cls.sample = "run/samples/A/Prob001_zero/"

    def mutated(self, root, changes):
        data = dict(self.raw)
        for name, raw in changes.items():
            data[name] = raw
        manifest = json.loads(data["ARCHIVE_MANIFEST.json"])
        manifest["files"] = {name: audit.digest(raw) for name, raw in data.items() if name != "ARCHIVE_MANIFEST.json"}
        data["ARCHIVE_MANIFEST.json"] = json.dumps(manifest).encode()
        path = root / "modified.zip"
        with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as bundle:
            for name, raw in data.items():
                bundle.writestr(name, raw)
        return path

    def run_snapshot(self, path, output):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected HTTP")), \
             patch("subprocess.run", side_effect=AssertionError("Unexpected external command")), \
             patch("subprocess.Popen", side_effect=AssertionError("Unexpected subprocess")):
            return audit.audit_archive(path, output)

    def test_real_partial_evidence_passes_without_network_tools_or_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_snapshot(SNAPSHOT, Path(temporary) / "out")
            self.assertTrue(result["evidence_valid"])
            self.assertFalse(result["full_round_complete"])
            self.assertIsNone(result["scores"])
            self.assertEqual(result["decision"], "incomplete_no_full_score_or_adoption")
            self.assertEqual(result["snapshot_samples"], 83)

    def test_repacked_changed_solution_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.mutated(root, {self.sample + "worker/solution.v": b"module TopModule; endmodule\n"})
            with self.assertRaisesRegex(ValueError, "Final source mismatch"):
                self.run_snapshot(path, root / "out")

    def test_repacked_rebound_request_with_extra_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = self.sample + "worker/requests/0/request.json"
            payload = json.loads(self.raw[name])
            payload["messages"][1]["content"] += "\nEXTRA_PRIVATE_INPUT"
            raw = json.dumps(payload).encode()
            entries_name = self.sample + "worker/requests.json"
            entries = json.loads(self.raw[entries_name])
            entries[0]["request_sha256"] = audit.digest(raw)
            path = self.mutated(root, {name: raw, entries_name: json.dumps(entries).encode()})
            with self.assertRaisesRegex(ValueError, "Model message/input"):
                self.run_snapshot(path, root / "out")

    def test_repacked_rebound_failed_guard_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row_name = self.sample + "accepted_row.json"
            row = json.loads(self.raw[row_name])
            manifest = json.loads(self.raw["ARCHIVE_MANIFEST.json"])
            relative = row["guard_directory"].removeprefix(manifest["run_root"] + "/")
            guard_name = "run/" + relative + "/status.json"
            guard = json.loads(self.raw[guard_name])
            guard["passed"] = False
            raw = json.dumps(guard).encode()
            row["guard_status_sha256"] = audit.digest(raw)
            path = self.mutated(root, {guard_name: raw, row_name: json.dumps(row).encode()})
            with self.assertRaisesRegex(ValueError, "Guard check: passed"):
                self.run_snapshot(path, root / "out")

    def test_repacked_changed_verdict_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = self.sample + "judge/verdict.json"
            verdict = json.loads(self.raw[name])
            verdict["level"] = 0
            path = self.mutated(root, {name: json.dumps(verdict).encode()})
            with self.assertRaises(ValueError):
                self.run_snapshot(path, root / "out")

    def test_premature_complete_flag_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status_name = "run/queue_status.json"
            status = json.loads(self.raw[status_name])
            status.update(complete=True, state="complete")
            path = self.mutated(root, {status_name: json.dumps(status).encode()})
            with self.assertRaisesRegex(ValueError, "Snapshot completion flag"):
                self.run_snapshot(path, root / "out")

    def test_path_traversal_is_rejected_before_extracting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.mutated(root, {"../escape.txt": b"outside"})
            with self.assertRaisesRegex(ValueError, "Unsafe archive name"):
                self.run_snapshot(path, root / "out")
            self.assertFalse((root / "escape.txt").exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            output.mkdir()
            sentinel = output / "kept.txt"
            sentinel.write_text("preserve")
            with self.assertRaisesRegex(ValueError, "fresh audit output"):
                self.run_snapshot(SNAPSHOT, output)
            self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    SNAPSHOT = args.snapshot
    unittest.main(argv=["test_audit.py"] + remaining)
