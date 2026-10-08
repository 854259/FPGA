"""Only new freeze/dispatch/capture checks; no model or EDA."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import prepare
import pilot
import audit


class FreezeEntry(unittest.TestCase):
    def test_complete_modules_import_against_actual_input_plan(self):
        self.assertEqual(len(pilot.metrics.TASKS), 156)
        self.assertEqual(pilot.metrics.ARMS, ['C', 'P'])
        self.assertEqual(prepare.task_groups(prepare.ROOT)['expected_samples'], 312)
        self.assertEqual(pilot.frozen.__module__, 'pilot')

    def test_unsigned_preparation_cannot_launch_worker(self):
        with self.assertRaises((AssertionError, FileNotFoundError)):
            pilot.worker(SimpleNamespace(kit=Path('/not-used'), task='unused', arm='P'))

    def test_approval_boolean_cannot_open_unpinned_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare.save(root/'EXECUTION_AUTHORIZATION.json', {'approved': True})
            with self.assertRaisesRegex(AssertionError, 'No reviewed'):
                prepare.validate_authorization(root, {})
        self.assertIsNone(prepare.EXECUTION_AUTHORIZATION_SHA)

    def test_pinned_authorization_binds_plan_source_limits_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('COMPARISON_INPUT_PLAN.json', 'SOURCE_FACTOR_PROOF.json'):
                prepare.save(root/name, {'synthetic': True})
            auth = dict(schema='table_parent_vector_execution_authorization_v1',
                        approved=True, run_identity='synthetic',
                        authorization_source='SYNTHETIC_TEST_ONLY',
                        actual_resource_allocation='SYNTHETIC_TEST_ONLY',
                        input_plan_sha256=prepare.sha(root/'COMPARISON_INPUT_PLAN.json'),
                        source_factor_proof_sha256=prepare.sha(root/'SOURCE_FACTOR_PROOF.json'),
                        limits=prepare.LIMITS, maximum_submissions=1, resampling=False)
            prepare.save(root/'EXECUTION_AUTHORIZATION.json', auth)
            digest = prepare.sha(root/'EXECUTION_AUTHORIZATION.json')
            spec = dict(identity='synthetic', execution_authorization_sha256=digest, **prepare.LIMITS)
            with patch.object(prepare, 'EXECUTION_AUTHORIZATION_SHA', digest):
                self.assertEqual(prepare.validate_authorization(root, spec), auth)
                for key in prepare.LIMITS:
                    bad = dict(spec); bad[key] += 1
                    with self.assertRaises(AssertionError):
                        prepare.validate_authorization(root, bad)
                bad = dict(spec, identity='different')
                with self.assertRaises(AssertionError):
                    prepare.validate_authorization(root, bad)
                (root/'COMPARISON_INPUT_PLAN.json').write_text('{}')
                with self.assertRaises(AssertionError):
                    prepare.validate_authorization(root, spec)

    def test_dispatch_keeps_pinned_worker_function_and_checks_membership(self):
        spec = {'task_ids':['synthetic'], 'arms':['C','P'], 'dependencies_cloud':'/synthetic'}
        args = SimpleNamespace(kit=Path('/synthetic'), task='synthetic', arm='C')
        calls = []
        implementation = SimpleNamespace(frozen=lambda: spec,
                                         run_worker=lambda a, p: calls.append((a, p)))
        owned = object()
        def load(name, path):
            return implementation if Path(path).name == 'worker.py' else owned
        with patch.object(pilot, 'frozen', return_value=spec), patch.object(pilot, 'load', side_effect=load), patch.object(pilot.ctypes, 'CDLL', return_value=SimpleNamespace(prctl=lambda *a:0)):
            self.assertEqual(pilot.worker(args), 0)
            self.assertEqual(calls, [(args, owned)])
            with self.assertRaises(AssertionError):
                pilot.worker(SimpleNamespace(kit=args.kit, task='other', arm='C'))
            self.assertEqual(len(calls), 1)

    def test_dynamic_capture_inventory_and_every_guard_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'raw_evidence').mkdir()
            folder = root/'results/protected_source_checks'
            folder.mkdir(parents=True)
            groups = {str(i): dict(spec_sha256='FAKE_SPEC_'+str(i),
                       source_hashes={'source.py':'FAKE_SOURCE_'+str(i)}) for i in range(3)}
            capture = dict(groups=groups, source_assets=3)
            prepare.save(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json', capture)
            spec = dict(protected_group_count=3, protected_source_assets=3,
                        protected_groups_capture_sha256=prepare.sha(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'))
            expected = {key:dict(value, source_assets=1) for key,value in groups.items()}
            for index in range(625):
                prepare.save(folder/(str(index).zfill(3)+'.json'),
                             dict(index=index, schema='semantic_edge_protected_source_check_v1',
                                  verified=True, groups=expected, source_assets=3, model_calls=0, eda_calls=0))
            audit.protected_receipts(root, spec)
            path = folder/'624.json'
            row = prepare.read(path); row['groups']['0']['source_hashes']['source.py']='TAMPERED'
            path.write_text(json.dumps(row))
            with self.assertRaises(AssertionError):
                audit.protected_receipts(root, spec)
            self.assertEqual(prepare.sha(root/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),
                             spec['protected_groups_capture_sha256'])


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
