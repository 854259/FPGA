"""AMD-only generic resource lifecycle controls; zero model/EDA calls."""
import argparse
import ast
import copy
import ctypes
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest

p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, required=True)
p.add_argument("--old-worker", type=Path, required=True)
p.add_argument("--receipt", type=Path, required=True)
args = p.parse_args()
assert sys.platform == "linux" and sys.dont_write_bytecode
spec = importlib.util.spec_from_file_location("resource_under_test", args.root / "dependencies/paired_checkpoint.py")
paired = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paired)
assert paired.sha(args.root / "dependencies/paired_checkpoint.py") == "78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c"
assert paired.sha(args.root / "pilot.py") == "01b1951e480a84021e16bdc5d83c99ebe08f37c088b14c991848997cd75270eb"

class ResourceLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="resource-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kit = self.root / "kit"
        for name in ("submission", "official_reference", "bench/tasks_veval"):
            d = self.kit / name
            d.mkdir(parents=True)
            (d / "fixture.txt").write_text("generic fixture\n")
        self.lock = self.root / "slot"
        self.lock.write_text("fixture-owner\nunchanged slot\n")
        protected = {k: paired.tree_hashes(self.kit / d) for k, d in
                     (("package", "submission"), ("official", "official_reference"), ("tasks", "bench/tasks_veval"))}
        protected["baseline"] = dict(protected["package"])
        self.record = dict(schema_version=1, host=socket.gethostname(), resource_idle=True,
                           checked_at_utc=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=181)).isoformat(),
                           slot_lock_path=str(self.lock), slot_lock_sha256=paired.sha(self.lock), slot_owner="fixture-owner",
                           model_pid=os.getpid(), model_identity=paired.model_identity(os.getpid()), protected=protected,
                           baseline_hashes={str(self.kit/"submission"/n): h for n, h in protected["baseline"].items()},
                           official_hashes={str(self.kit/"official_reference"/n): h for n, h in protected["official"].items()})
        self.admission = self.root / "resource.json"
        (self.root/"RUN_SPEC.json").write_text(json.dumps(dict(dependencies_cloud=str(args.root/"dependencies"))))

    def save(self):
        self.admission.write_text(json.dumps(self.record))
        return self.admission

    def entry(self, worker):
        # Execute the real CLI boundary, replacing only the solver body.
        # The real resource function still reads files and a real /proc identity.
        tree = ast.parse(worker.read_text())
        boundary = tree.body[-1]
        self.assertIsInstance(boundary, ast.If)
        called = []
        namespace = dict(__name__="__main__", argparse=argparse, ctypes=ctypes, json=json,
                         Path=Path, sys=sys, ROOT=self.root,
                         baseline_worker=types.SimpleNamespace(load=lambda *a: paired),
                         run_worker=lambda *a: called.append(True))
        old = sys.argv
        sys.argv = [str(worker), "--out", str(self.root/"unused"), "--kit", str(self.kit),
                    "--resource-check", str(self.save()), "--task", "Constructed", "--arm", "P"]
        try:
            exec(compile(ast.Module(body=[boundary], type_ignores=[]), str(worker), "exec"), namespace)
        finally:
            sys.argv = old
        return called

    def test_fresh_initial_stage_admission(self):
        self.record["checked_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        paired.check_resource(self.save(), self.kit, first=True)

    def test_stale_initial_stage_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "stale"):
            paired.check_resource(self.save(), self.kit, first=True)

    def test_future_initial_stage_rejected(self):
        self.record["checked_at_utc"] = (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=30)).isoformat()
        with self.assertRaisesRegex(RuntimeError, "stale"):
            paired.check_resource(self.save(), self.kit, first=True)

    def test_later_worker_valid_same_slot_enters_solver(self):
        self.assertEqual(self.entry(args.root/"worker.py"), [True])

    def test_original_later_worker_reproduces_failure(self):
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.entry(args.old_worker)

    def test_later_worker_changed_lock_rejected(self):
        self.lock.write_text("another-owner\n")
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            self.entry(args.root/"worker.py")

    def test_later_worker_changed_model_rejected(self):
        self.record["model_identity"]["starttime"] = "different"
        with self.assertRaisesRegex(RuntimeError, "identity"):
            self.entry(args.root/"worker.py")

    def test_later_worker_changed_protected_files_rejected(self):
        (self.kit/"submission/fixture.txt").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "protected files"):
            self.entry(args.root/"worker.py")

    def test_later_worker_inconsistent_baseline_rejected(self):
        self.record["baseline_hashes"] = {}
        with self.assertRaisesRegex(RuntimeError, "inconsistent"):
            self.entry(args.root/"worker.py")

    def test_later_worker_wrong_host_rejected(self):
        self.record["host"] = "not-this-host"
        with self.assertRaisesRegex(RuntimeError, "idle host"):
            self.entry(args.root/"worker.py")

result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResourceLifecycle))
receipt = dict(schema="resource_lifecycle_generic_controls_v1", passed=result.wasSuccessful(),
               tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
               worker_sha256=paired.sha(args.root/"worker.py"), original_worker_sha256=paired.sha(args.old_worker),
               test_sha256=paired.sha(Path(__file__)), model_calls=0, eda_calls=0,
               scope="Real resource checker and CLI boundary; solver stub only; artificial timestamp, no actual lease renewal")
args.receipt.write_text(json.dumps(receipt, indent=2)+"\n")
raise SystemExit(0 if result.wasSuccessful() else 1)

