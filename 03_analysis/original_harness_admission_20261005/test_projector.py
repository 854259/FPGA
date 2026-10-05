"""Read-only actual-evidence projection and pure rejection controls; no model/EDA."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import projector as p


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projection, cls.receipt, cls.audit = p.build_projection()
        cls.bundle = p.verify_archive(p.SOURCE / 'raw_evidence/terminal_v1.zip',
                                     p.read_pinned(p.SOURCE / 'RUN_SPEC.json', p.SPEC_SHA))
        cls.adapter = p.trusted_module(p.ADAPTER_SOURCE, p.ADAPTER_SHA, 'test_verified_public_adapter')

    def derive(self, records=None, private=None, audit=None):
        return p.derive_rows(records or copy.deepcopy(self.bundle['records']),
                             private or copy.deepcopy(self.bundle['private']),
                             audit or copy.deepcopy(self.audit), self.adapter)

    def test_actual_rebuild_maps_two_finite_qualifications_and_retains_exclusion(self):
        doc = self.projection
        self.assertTrue(doc['evidence_valid'])
        self.assertEqual(doc['qualified_public_input_versions'], 2)
        self.assertEqual(doc['excluded_public_input_versions'], 1)
        by_id = {row['record_id']: row for row in doc['public_inputs'].values()}
        self.assertEqual([by_id[name]['qualified'] for name in p.IDS], [True, True, False])
        self.assertEqual([by_id[name]['wrong_controls_checked'] for name in p.IDS], [3, 3, 4])
        self.assertEqual(doc['exclusions'][0]['false_acceptances'][0]['label'], 'valid_zero')
        self.assertEqual(doc['exclusions'][0]['false_acceptances'][0]['native_trials'], 5)
        self.assertEqual(doc['source_evidence']['global_native_receipts'], 100)
        self.assertFalse(doc['real_execution_admitted'])
        self.assertFalse(doc['eligible_for_independent_models'])

    def test_pure_derivation_is_not_evidence_or_real_io_admission(self):
        doc = self.derive()
        self.assertTrue(doc['pure_projection_only'])
        self.assertFalse(doc['evidence_valid'])
        self.assertFalse(doc['real_execution_admitted'])

    def test_exact_immutable_adapter_public_input_hashes(self):
        for record in self.bundle['records'].values():
            view = self.adapter.task_view(record)
            binding = self.adapter.binding(record, view)
            self.assertEqual(set(view), {'prompt', 'context', 'output_paths'})
            row = self.projection['public_inputs'][binding['user_content_sha256']]
            self.assertEqual(row['prompt_sha256'], binding['prompt_sha256'])
            self.assertEqual(row['input_context_sha256'], binding['input_context_sha256'])
            self.assertEqual(row['output_paths'], binding['output_paths'])
            self.assertFalse(row['hidden_harness_forwarded'])
            self.assertFalse(row['answers_forwarded'])

    def test_wrong_original_record_id_is_rejected(self):
        records = copy.deepcopy(self.bundle['records'])
        records[p.IDS[0]]['id'] = 'a_different_version'
        with self.assertRaises(ValueError): self.derive(records=records)

    def test_changed_prompt_or_public_context_is_rejected(self):
        for mutate in [lambda x: x['input'].__setitem__('prompt', x['input']['prompt'] + '\n'),
                       lambda x: x['input']['context'].__setitem__('rtl/helper.sv', 'module helper;endmodule')]:
            records = copy.deepcopy(self.bundle['records']); mutate(records[p.IDS[0]])
            with self.assertRaises(ValueError): self.derive(records=records)

    def test_changed_output_path_or_nonempty_answer_is_rejected(self):
        for mutate in [lambda x: x['output'].__setitem__('context', {'rtl/renamed.v': ''}),
                       lambda x: x['output'].__setitem__('response', 'answer'),
                       lambda x: x['output']['context'].__setitem__('rtl/reverse_bits.v', 'module answer;endmodule')]:
            records = copy.deepcopy(self.bundle['records']); mutate(records[p.IDS[0]])
            with self.assertRaises(ValueError): self.derive(records=records)

    def test_research_test_edit_cannot_be_laundered_as_original(self):
        records = copy.deepcopy(self.bundle['records'])
        records[p.IDS[0]]['harness']['files']['src/test_reverse_bits.py'] += '\nassert True\n'
        private = copy.deepcopy(self.bundle['private'])
        # Even editing the advertised hashes does not replace the closed source
        # record version. A corrected research harness is a different evidence.
        private['cases'][0]['record_sha256'] = p.sha(json.dumps(records[p.IDS[0]], sort_keys=True).encode())
        private['cases'][0]['harness_sha256']['src/test_reverse_bits.py'] = p.sha(
            records[p.IDS[0]]['harness']['files']['src/test_reverse_bits.py'].encode())
        with self.assertRaises(ValueError): self.derive(records=records, private=private)

    def test_changed_harness_test_runner_or_full_harness_set_rejected(self):
        for path in ['src/test_reverse_bits.py', 'src/test_runner.py', 'docker-compose.yml']:
            records = copy.deepcopy(self.bundle['records'])
            records[p.IDS[0]]['harness']['files'][path] += '\n# research edit\n'
            with self.assertRaises(ValueError): self.derive(records=records)
        records = copy.deepcopy(self.bundle['records']); del records[p.IDS[0]]['harness']['files']['src/.env']
        with self.assertRaises(ValueError): self.derive(records=records)

    def test_wrong_spec_archive_auditor_or_adapter_bytes_rejected(self):
        for path, expected in [(p.SOURCE / 'RUN_SPEC.json', p.SPEC_SHA),
                               (p.SOURCE / 'raw_evidence/terminal_v1.zip', p.ARCHIVE_SHA),
                               (p.SOURCE / 'audit.py', p.AUDITOR_SHA), (p.ADAPTER_SOURCE, p.ADAPTER_SHA)]:
            data = path.read_bytes()
            self.assertEqual(p.pin_bytes(data, expected, 'actual'), data)
            with self.assertRaises(ValueError): p.pin_bytes(data + b'\n', expected, 'changed')

    def test_wrong_audit_source_binding_rejected(self):
        for field in ['spec_sha256', 'archive_sha256', 'auditor_sha256']:
            audit = copy.deepcopy(self.audit); audit[field] = '0' * 64
            with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_foreign_or_nonqualified_audit_schema_rejected(self):
        for mutate in [dict(schema='research_modified_harness_readonly_audit'), dict(evidence_valid=False),
                       dict(adoption=True), dict(eligible_for_independent_models=True), dict(model_calls=1)]:
            audit = copy.deepcopy(self.audit); audit.update(mutate)
            with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_wrong_control_false_pass_prevents_finite_qualification(self):
        audit = copy.deepcopy(self.audit)
        row = audit['controls'][1]; row.update(passed=True, failed=False, false_acceptance=True)
        audit['false_acceptances'] = [x for x in audit['controls'] if x['false_acceptance']]
        audit['original_harness_calibration'][p.IDS[0]] = False
        doc = self.derive(audit=audit)
        derived = next(x for x in doc['public_inputs'].values() if x['record_id'] == p.IDS[0])
        self.assertFalse(derived['qualified'])
        self.assertEqual(derived['false_acceptances'][0]['label'], 'constant_zero')
        self.assertFalse(doc['evidence_valid'])

    def test_missing_wrong_control_or_duplicate_control_rejected(self):
        for mutate in [lambda a: a['controls'].pop(1), lambda a: a['controls'].insert(1, copy.deepcopy(a['controls'][1]))]:
            audit = copy.deepcopy(self.audit); mutate(audit)
            with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_false_acceptance_cannot_be_omitted_or_overruled(self):
        audit = copy.deepcopy(self.audit); audit['false_acceptances'] = []
        with self.assertRaises(ValueError): self.derive(audit=audit)
        audit = copy.deepcopy(self.audit); audit['original_harness_calibration'][p.IDS[2]] = True
        with self.assertRaises(ValueError): self.derive(audit=audit)
        audit = copy.deepcopy(self.audit); audit['controls'][-2]['false_acceptance'] = False
        audit['false_acceptances'] = []
        with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_research_positive_or_wrong_harness_not_original(self):
        for index in [0, 1, 5, 6]:
            audit = copy.deepcopy(self.audit); audit['controls'][index]['original_harness'] = False
            with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_sentinel_remains_modified_and_must_propagate(self):
        audit = copy.deepcopy(self.audit); audit['controls'][4]['original_harness'] = True
        with self.assertRaises(ValueError): self.derive(audit=audit)
        audit = copy.deepcopy(self.audit); audit['controls'][4].update(passed=True, failed=False)
        audit['original_harness_calibration'][p.IDS[0]] = False
        doc = self.derive(audit=audit)
        row = next(x for x in doc['public_inputs'].values() if x['record_id'] == p.IDS[0])
        self.assertFalse(row['failure_propagation_confirmed'])
        self.assertFalse(row['qualified'])

    def test_native_trial_types_counts_and_unconfirmed_scope_rejected(self):
        for value in [True, 0, 2]:
            audit = copy.deepcopy(self.audit); audit['controls'][0]['native_trials'] = value
            with self.assertRaises(ValueError): self.derive(audit=audit)
        for key, value in [('native_compile_commands', 49), ('native_simulation_commands', 51), ('audit_model_calls', True)]:
            audit = copy.deepcopy(self.audit); audit[key] = value
            with self.assertRaises(ValueError): self.derive(audit=audit)

    def test_duplicate_json_and_unsafe_archive_path_rejected(self):
        with self.assertRaises(ValueError): p.decoded(b'{"qualified":true,"qualified":false}')
        for name in ['/outside', '../escape', 'run/../escape', 'run\\escape', 'run:escape', './run/x']:
            with self.assertRaises(ValueError): p.portable(name)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    receipt = dict(schema='original_harness_projection_controls_v1', tests_run=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   python_version=sys.version.split()[0], projector_sha256=p.sha((ROOT / 'projector.py').read_bytes()),
                   test_sha256=p.sha(Path(__file__).read_bytes()), source_spec_sha256=p.SPEC_SHA,
                   source_archive_sha256=p.ARCHIVE_SHA, source_auditor_sha256=p.AUDITOR_SHA,
                   adapter_sha256=p.ADAPTER_SHA, actual_model_calls=0, actual_eda_calls=0,
                   actual_cloud_or_fifo_calls=0, pure_controls_not_new_native_experiments=True)
    print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
