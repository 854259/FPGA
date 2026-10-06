"""AMD-only negative controls for the separately bound relocation audit."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import audit_relocated_capture as audit

SOURCE = Path(sys.argv.pop(1)).resolve()


class RelocationControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='waveform104-relocation-control-')
        self.root = Path(self.tmp.name)
        self.run = self.root/'run'
        names = ['RUN_SPEC.json', 'PARENT_RUN_SPEC.json', 'RESOURCE_LIFECYCLE_ADMISSION.json',
                 'raw_evidence/ENVIRONMENT_CAPTURE.json', 'worker.py', 'pilot.py', 'refreeze_resource.py',
                 'dependencies/paired_checkpoint.py', 'dependencies/probe_runner.py']
        for name in names:
            target = self.run/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE/name, target)
        shutil.copytree(self.run/'dependencies', self.root/'dependencies')
        self.spec = audit.read(self.run/'RUN_SPEC.json')
        self.capture = audit.read(self.run/'raw_evidence/ENVIRONMENT_CAPTURE.json')

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self):
        return audit.verify_dependency_relocation(self.run, self.spec, self.capture, self.root/'dependencies')

    def test_exact_parent_copy_passes_without_old_live_directory(self):
        self.assertTrue(self.verify()['copies_and_import_source_bound'])

    def test_original_equality_rejection_is_preserved(self):
        with self.assertRaises(AssertionError):
            assert self.capture['dependency_hashes'] == self.spec['dependency_hashes'] and self.capture['dependencies_cloud'] == self.spec['dependencies_cloud']

    def test_wrong_capture_path_rejected(self):
        self.capture['dependencies_cloud'] += '/wrong'
        with self.assertRaises(AssertionError):
            self.verify()

    def test_wrong_final_path_rejected(self):
        self.spec['dependencies_cloud'] += '/wrong'
        with self.assertRaises(AssertionError):
            self.verify()

    def test_changed_dependency_mapping_rejected(self):
        self.spec['dependency_hashes']['probe_runner.py'] = '0'*64
        with self.assertRaises(AssertionError):
            self.verify()

    def test_archived_dependency_drift_rejected(self):
        (self.root/'dependencies/probe_runner.py').write_bytes(b'changed')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_run_dependency_drift_rejected(self):
        (self.run/'dependencies/paired_checkpoint.py').write_bytes(b'changed')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_changed_parent_receipt_rejected(self):
        path = self.run/'PARENT_RUN_SPEC.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_changed_capture_receipt_rejected(self):
        path = self.run/'raw_evidence/ENVIRONMENT_CAPTURE.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(AssertionError):
            self.verify()

    def test_traversal_cloud_path_rejected(self):
        self.spec['cloud_root'] += '/../other'
        self.spec['dependencies_cloud'] = self.spec['cloud_root']+'/dependencies'
        with self.assertRaises(AssertionError):
            self.verify()

    def test_bound_but_wrong_worker_import_rejected(self):
        path = self.run/'worker.py'
        text = path.read_text().replace("Path(spec['dependencies_cloud'])", "Path('/wrong/dependencies')")
        path.write_text(text)
        self.spec['source_hashes']['worker.py'] = audit.sha(path)
        receipt_path = self.run/'RESOURCE_LIFECYCLE_ADMISSION.json'
        receipt = audit.read(receipt_path)
        receipt['worker_sha256'] = audit.sha(path)
        receipt_path.write_text(json.dumps(receipt))
        self.spec['source_hashes']['RESOURCE_LIFECYCLE_ADMISSION.json'] = audit.sha(receipt_path)
        self.spec['resource_lifecycle_admission_sha256'] = audit.sha(receipt_path)
        with self.assertRaises(AssertionError):
            self.verify()

    def test_no_mutation_of_input_or_frozen_sources(self):
        before_spec, before_capture = copy.deepcopy(self.spec), copy.deepcopy(self.capture)
        before_files = {str(p):audit.sha(p) for p in self.root.rglob('*') if p.is_file()}
        self.verify()
        self.assertEqual(self.spec, before_spec)
        self.assertEqual(self.capture, before_capture)
        self.assertEqual(before_files, {str(p):audit.sha(p) for p in self.root.rglob('*') if p.is_file()})

    def test_effective_auditor_is_explicitly_attributed(self):
        namespace, identity = audit.build_auditor(SOURCE)
        self.assertTrue(callable(namespace['audit']))
        self.assertEqual(identity['original_auditor_sha256'], audit.ORIGINAL_AUDITOR_SHA)
        self.assertEqual(identity['wrapper_sha256'], audit.sha(audit.__file__))
        self.assertNotEqual(identity['effective_source_sha256'], audit.ORIGINAL_AUDITOR_SHA)
        self.assertFalse(identity['frozen_source_modified'])


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.version_info[:2] == (3, 12) and sys.dont_write_bytecode
    unittest.main(verbosity=2)
