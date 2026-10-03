"""End-to-end package and rollback gates using disposable submission trees."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / 'bench/verify_package.py'
SET_RUNTIME = ROOT / 'bench/set_manifest_runtime.py'
STABLE = ROOT / 'release/runtime.cea6479c.py'
STABLE_SHA = 'cea6479c6364fbfce55ca8129e8cfd7bb4b9afd3b2a4c7ae2e3cd381af2968b1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PackageToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.package = self.base / 'submission'
        (self.package / 'agent').mkdir(parents=True)
        (self.package / 'serve').mkdir()
        self.runtime = self.package / 'agent/runtime.py'
        self.supervisor = self.package / 'serve/serve_all.sh'
        self.runtime.write_bytes(b'candidate-under-test\n')
        self.supervisor.write_bytes(b'#!/bin/bash\nexit 0\n')
        self.manifest_path = self.package / 'manifest.json'
        self.manifest = {
            'runtime': {'path': 'agent/runtime.py', 'sha256': digest(self.runtime.read_bytes())},
            'serving': {
                'supervisor': 'serve/serve_all.sh',
                'supervisor_sha256': digest(self.supervisor.read_bytes()),
            },
            'preserved': {'name': '其他字段', 'items': [1, 2, 3]},
        }
        self.save_manifest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, '-B', str(tool), *map(str, args)],
                              text=True, encoding='utf-8', capture_output=True,
                              env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=15)

    def verify(self, *extra):
        result_path = self.base / 'result.json'
        result = self.run_tool(VERIFY, '--root', self.package, '--json', result_path, *extra)
        self.assertTrue(result_path.is_file(), result.stdout + result.stderr)
        return result, json.loads(result_path.read_text(encoding='utf-8'))

    def test_matching_supervisor_passes(self):
        result, report = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report['problems'], [])

    def test_modified_supervisor_fails_even_when_runtime_matches(self):
        self.supervisor.write_bytes(b'#!/bin/bash\necho modified\n')
        result, report = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any('serve/serve_all.sh' in p for p in report['problems']))

    def test_missing_supervisor_file_or_claim_never_passes(self):
        self.supervisor.unlink()
        result, _ = self.verify()
        self.assertEqual(result.returncode, 1)
        self.supervisor.write_bytes(b'#!/bin/bash\nexit 0\n')
        for field in ('supervisor', 'supervisor_sha256'):
            with self.subTest(field=field):
                value = self.manifest['serving'].pop(field)
                self.save_manifest()
                result, report = self.verify()
                self.assertEqual(result.returncode, 1)
                self.assertTrue(any('serving.' + field in p for p in report['problems']))
                self.manifest['serving'][field] = value

    def test_parent_path_is_not_silently_reinterpreted(self):
        self.manifest['serving']['supervisor'] = '../serve/serve_all.sh'
        self.save_manifest()
        result, _ = self.verify()
        self.assertEqual(result.returncode, 1)

    def test_missing_manifest_and_missing_requested_comparison_fail(self):
        self.manifest_path.unlink()
        result, report = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any('manifest.json' in p for p in report['problems']))
        self.save_manifest()
        result, report = self.verify('--against', self.base / 'missing-comparison')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any('missing-comparison' in p for p in report['problems']))

    def test_unknown_runtime_cannot_be_relabelled_as_stable(self):
        # The old implementation accepted anything except its one known candidate.
        before = self.manifest_path.read_bytes()
        result = self.run_tool(SET_RUNTIME, self.package, 'rollback')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_existing_stable_claim_does_not_bypass_runtime_check(self):
        self.manifest['runtime']['sha256'] = STABLE_SHA
        self.save_manifest()
        before = self.manifest_path.read_bytes()
        result = self.run_tool(SET_RUNTIME, self.package, 'rollback')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_exact_archived_stable_runtime_allows_rollback_metadata(self):
        stable_bytes = STABLE.read_bytes()
        self.assertEqual(digest(stable_bytes), STABLE_SHA, 'archived stable fixture changed')
        self.runtime.write_bytes(stable_bytes)
        result = self.run_tool(SET_RUNTIME, self.package, 'rollback')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        expected = json.loads(json.dumps(self.manifest))
        expected['runtime']['sha256'] = STABLE_SHA
        self.assertEqual(updated, expected)

    def test_adopted_records_actual_bytes_and_preserves_other_fields(self):
        self.manifest['runtime']['sha256'] = 'old'
        self.save_manifest()
        result = self.run_tool(SET_RUNTIME, self.package, 'adopted')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        expected = json.loads(json.dumps(self.manifest))
        expected['runtime']['sha256'] = digest(self.runtime.read_bytes())
        self.assertEqual(updated, expected)


if __name__ == '__main__':
    unittest.main()
