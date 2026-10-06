"""Independent positive/negative archive provenance controls, no model or EDA."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dependency_capture_binding import verify


class CaptureBinding(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run = self.root / 'run'
        (self.run / 'raw_evidence').mkdir(parents=True)
        (self.run / 'dependencies').mkdir()
        (self.root / 'dependencies').mkdir()
        self.sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.read = lambda p: json.loads(p.read_bytes())
        for base in (self.root, self.run):
            (base / 'dependencies/checker.py').write_bytes(b'original checker bytes\n')
        expected = self.sha(self.root / 'dependencies/checker.py')
        self.parent = dict(cloud_root='/frozen/parent', dependencies_cloud='/frozen/parent/dependencies',
                           dependency_hashes={'checker.py': expected})
        self.capture = dict(dependencies_cloud=self.parent['dependencies_cloud'],
                            dependency_hashes=dict(self.parent['dependency_hashes']))
        (self.run / 'CP6_PARENT_SPEC.json').write_text(json.dumps(self.parent))
        (self.run / 'raw_evidence/ENVIRONMENT_CAPTURE.json').write_text(json.dumps(self.capture))
        self.spec = dict(cloud_root='/frozen/child', dependencies_cloud='/frozen/child/dependencies',
                         dependency_hashes=dict(self.parent['dependency_hashes']),
                         environment_capture_sha256=self.sha(self.run / 'raw_evidence/ENVIRONMENT_CAPTURE.json'),
                         source_hashes={'CP6_PARENT_SPEC.json': self.sha(self.run / 'CP6_PARENT_SPEC.json'),
                                        'dependencies/checker.py': expected})

    def check(self):
        return verify(self.run, self.root, self.spec, self.capture, self.sha, self.read)

    def test_frozen_relocation_keeps_both_original_byte_copies(self):
        result = self.check()
        self.assertTrue(result['verified'])
        self.assertEqual(result['captured_dependencies_cloud'], '/frozen/parent/dependencies')
        self.assertEqual(result['executing_dependencies_cloud'], '/frozen/child/dependencies')

    def test_unbound_capture_origin_rejected(self):
        self.capture['dependencies_cloud'] = '/unbound/dependencies'
        with self.assertRaises(AssertionError): self.check()

    def test_execution_path_outside_declared_child_rejected(self):
        self.spec['dependencies_cloud'] = '/unbound/dependencies'
        with self.assertRaises(AssertionError): self.check()

    def test_changed_execution_copy_rejected(self):
        (self.root / 'dependencies/checker.py').write_bytes(b'changed runtime bytes')
        with self.assertRaises(AssertionError): self.check()

    def test_changed_frozen_copy_rejected(self):
        (self.run / 'dependencies/checker.py').write_bytes(b'changed archived source')
        with self.assertRaises(AssertionError): self.check()

    def test_extra_dependency_rejected(self):
        self.spec['dependency_hashes']['extra.py'] = '0' * 64
        with self.assertRaises(AssertionError): self.check()

    def test_changed_parent_record_rejected(self):
        (self.run / 'CP6_PARENT_SPEC.json').write_text(json.dumps(dict(self.parent, cloud_root='/other')))
        with self.assertRaises(AssertionError): self.check()

    def test_changed_capture_record_rejected(self):
        (self.run / 'raw_evidence/ENVIRONMENT_CAPTURE.json').write_text('{}')
        with self.assertRaises(AssertionError): self.check()


if __name__ == '__main__':
    unittest.main(verbosity=2)
