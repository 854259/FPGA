"""Pure adversarial admission controls. All documents/archives are SYNTHETIC.

Passing these controls neither admits execution nor certifies actual prerequisites.
No model, HTTP, EDA, cloud, FIFO or process launch is performed by this module.
"""
from pathlib import Path, PurePosixPath
import copy
import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.request
import warnings
import zipfile

import runtime
import worker

NATIVE_ORDER = [
    'positive', 'reset_ignored', 'synchronous_reset', 'history_sync_only',
    'clear_rising_only', 'clear_falling_only', 'constant_zero', 'constant_one',
    'swapped_edges', 'two_cycle_pulse', 'one_cycle_late', 'negedge_sample',
    'failure_propagation', 'positive_renamed',
]


def synthetic_documents():
    """Invented complete-shaped documents solely to exercise closed pure gates."""
    binding = dict(prompt_sha256='a' * 64, input_context_sha256={'rtl/helper.sv': 'b' * 64},
                   output_paths=['rtl/main.sv'], user_content_sha256='c' * 64)
    spec = dict(schema='natural_runtime_frozen_v1', integration_factor='natural_runtime_v1',
                base_worker_tools_spec_sha256=runtime.BASE_SPEC_SHA,
                execution_authorized_by_root=True, max_requests=2, max_tokens=8192,
                temperature=0, top_p=1, solve_timeout_s=300, max_native_commands=6,
                endpoint=runtime.ENDPOINT, toolchain={'files': {}},
                runtime_libraries={}, real_tools={'bwrap': {'sha256': 'd' * 64},
                                                 'prlimit': {'sha256': 'e' * 64}},
                limits={'native_as_bytes': 1024 ** 3, 'native_fsize_bytes': 1024 ** 2})
    full = dict(schema='phase_full156_readonly_audit_v1', spec_sha256=runtime.FULL_SPEC_SHA,
                auditor_sha256=runtime.FULL_AUDITOR_SHA, qualification_scope=runtime.FULL_SCOPE,
                evidence_valid=True, full156_evidence_valid=True, screening_eligible=True,
                candidate_qualified_for_independent_validation=True,
                independent_validation_qualified=True, historical_fixture_only=False,
                expected_samples=312, actual_model_requests=330, unconfirmed_attempts=0,
                solve_deadlines=[], regressions=[], unchanged_first_reply_regressions=[],
                matched_native_repair_tasks=['Prob045_edgedetect2', 'Prob054_edgedetect'])
    original = dict(schema='natural_original_harness_admission_audit_v1', evidence_valid=True,
                    public_inputs={binding['user_content_sha256']: dict(
                        qualified=True, original_harness=True, false_acceptances=[],
                        unconfirmed_native_attempts=0, wrong_controls_checked=4,
                        correct_control_passed=True, failure_propagation_confirmed=True,
                        prompt_sha256=binding['prompt_sha256'],
                        input_context_sha256=copy.deepcopy(binding['input_context_sha256']),
                        output_paths=list(binding['output_paths']))})
    isolation = dict(schema='natural_os_include_isolation_readonly_audit_v1', evidence_valid=True,
                     historical_fixture_only=False, real_native_controls=6,
                     unconfirmed_native_attempts=0, network_disabled=True,
                     filesystem_escape_denied=True, include_escape_denied=True,
                     shell_escape_denied=True, resource_limits_verified=True,
                     owned_cleanup_verified=True,
                     escape_controls={name: True for name in runtime.ESCAPE_CONTROLS},
                     sandbox_recipe_sha256=runtime.sha(runtime.canonical(runtime.sandbox_recipe(spec))))
    native = dict(evidence_complete=True, qualified_for_generated_control_discrimination=True,
                  spec_sha256=runtime.NATIVE_SPEC_SHA, native_compile_commands=14,
                  native_simulation_commands=14, global_native_receipts=28,
                  attempted_compile_commands=14, attempted_simulation_commands=14,
                  unconfirmed_native_attempts=0, generated_research_test=True,
                  original_harness=False, controls=[dict(label=name, control_matched=True,
                                                        false_acceptance=False) for name in NATIVE_ORDER],
                  audit_model_calls=0, audit_eda_calls=0, model_calls=0,
                  independent_quality_admitted=0, eligible_for_independent_models=False,
                  adoption=False)
    return [spec, full, original, isolation, native, binding]


class AdmissionBoundaries(unittest.TestCase):
    def setUp(self):
        worker.RAW.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='SYNTHETIC_admission_', dir=worker.RAW)
        self.base = Path(self.temp.name).absolute()
        self.sequence = 0
        self.patches = []
        self.external = []
        for owner, name in [(runtime.socket, 'create_connection'), (runtime.socket, 'socket'),
                            (subprocess, 'Popen'), (urllib.request, 'urlopen')]:
            patch = mock.patch.object(owner, name, side_effect=AssertionError('actual IO forbidden in pure controls'))
            self.patches.append(patch)
            self.external.append(patch.start())
        self.archive_cache = set(runtime._BOUND_ARCHIVES)
        runtime._BOUND_ARCHIVES.clear()

    def tearDown(self):
        try:
            for boundary in self.external:
                boundary.assert_not_called()
            self.assertTrue(self.base.resolve().is_relative_to(worker.RAW.resolve()))
            self.temp.cleanup()
        finally:
            runtime._BOUND_ARCHIVES.clear()
            runtime._BOUND_ARCHIVES.update(self.archive_cache)
            for patch in reversed(self.patches):
                patch.stop()

    def documents(self, documents=None, need_native=True):
        return runtime.evaluate_documents(*(documents or synthetic_documents()), need_native=need_native)

    def check_mutations(self, index, changes):
        for label, mutation in changes:
            with self.subTest(label=label):
                documents = synthetic_documents()
                mutation(documents[index])
                with self.assertRaises((PermissionError, ValueError, KeyError, TypeError)):
                    self.documents(documents)

    def test_complete_shaped_fake_documents_never_admit_real_execution(self):
        for need_native in (True, False):
            with self.subTest(need_native=need_native):
                value = self.documents(need_native=need_native)
                self.assertIs(value['requirements_satisfied'], True)
                self.assertIs(value['real_execution_admitted'], False)
                self.assertIn('pure document checks only', value['scope'])

    def test_runtime_spec_and_numeric_authority_cannot_be_loosened(self):
        self.check_mutations(0, [
            ('missing schema', lambda row: row.pop('schema')),
            ('old factor', lambda row: row.update(integration_factor='qualified_old_P')),
            ('wrong worker freeze', lambda row: row.update(base_worker_tools_spec_sha256='0' * 64)),
            ('no root authorization', lambda row: row.update(execution_authorized_by_root=False)),
            ('truthy authority', lambda row: row.update(execution_authorized_by_root=1)),
            ('third request', lambda row: row.update(max_requests=3)),
            ('different token cap', lambda row: row.update(max_tokens=4096)),
            ('boolean zero temperature', lambda row: row.update(temperature=False)),
            ('boolean top_p', lambda row: row.update(top_p=True)),
            ('longer deadline', lambda row: row.update(solve_timeout_s=301)),
            ('native cap', lambda row: row.update(max_native_commands=7)),
            ('different host', lambda row: row.update(endpoint='http://localhost:8000/v1/chat/completions')),
        ])

    def test_full_identity_scope_and_denominator(self):
        self.check_mutations(1, [
            ('missing schema', lambda row: row.pop('schema')),
            ('different schema', lambda row: row.update(schema='phase_pilot_readonly_audit_v1')),
            ('different full spec', lambda row: row.update(spec_sha256='0' * 64)),
            ('different auditor', lambda row: row.update(auditor_sha256='0' * 64)),
            ('deployment scope', lambda row: row.update(qualification_scope='Permits production deployment.')),
            ('fixture', lambda row: row.update(historical_fixture_only=True)),
            ('partial denominator', lambda row: row.update(expected_samples=310)),
            ('boolean denominator', lambda row: row.update(expected_samples=True)),
            ('too few calls', lambda row: row.update(actual_model_requests=311)),
            ('too many calls', lambda row: row.update(actual_model_requests=625)),
            ('boolean calls', lambda row: row.update(actual_model_requests=True)),
            ('boolean unconfirmed zero', lambda row: row.update(unconfirmed_attempts=False)),
            ('unconfirmed', lambda row: row.update(unconfirmed_attempts=1)),
            ('deadline', lambda row: row.update(solve_deadlines=[{'task': 'Prob070'}])),
            ('regression', lambda row: row.update(regressions=['Prob001'])),
            ('same first regression', lambda row: row.update(unchanged_first_reply_regressions=['Prob001'])),
            ('arbitrary matched tasks', lambda row: row.update(matched_native_repair_tasks=['X', 'Y'])),
            ('duplicate matched task', lambda row: row.update(matched_native_repair_tasks=['Prob045_edgedetect2'] * 2)),
            ('reordered matches', lambda row: row.update(matched_native_repair_tasks=row['matched_native_repair_tasks'][::-1])),
        ])

    def test_each_full_quality_gate_is_required(self):
        for field in ('evidence_valid', 'full156_evidence_valid', 'screening_eligible',
                      'candidate_qualified_for_independent_validation', 'independent_validation_qualified'):
            for replacement in (False, 1, None):
                with self.subTest(field=field, replacement=replacement):
                    documents = synthetic_documents()
                    documents[1][field] = replacement
                    with self.assertRaises(PermissionError):
                        self.documents(documents)

    def test_original_false_acceptance_or_input_drift_stays_excluded(self):
        key = synthetic_documents()[5]['user_content_sha256']
        mutations = [
            ('wrong projection schema', lambda row: row.update(schema='natural_edge_original_harness_readonly_audit_v1')),
            ('missing exact input', lambda row: row['public_inputs'].clear()),
            ('false acceptance', lambda row: row['public_inputs'][key].update(false_acceptances=['reset_ignored'])),
            ('generated substitute', lambda row: row['public_inputs'][key].update(original_harness=False)),
            ('wrong prompt', lambda row: row['public_inputs'][key].update(prompt_sha256='0' * 64)),
            ('missing helper', lambda row: row['public_inputs'][key].update(input_context_sha256={})),
            ('wrong output ABI', lambda row: row['public_inputs'][key].update(output_paths=['TopModule.sv'])),
            ('unconfirmed native', lambda row: row['public_inputs'][key].update(unconfirmed_native_attempts=1)),
            ('insufficient negatives', lambda row: row['public_inputs'][key].update(wrong_controls_checked=2)),
            ('positive failed', lambda row: row['public_inputs'][key].update(correct_control_passed=False)),
            ('sentinel absent', lambda row: row['public_inputs'][key].update(failure_propagation_confirmed=False)),
        ]
        self.check_mutations(2, mutations)

    def test_isolation_requires_exact_recipe_and_all_escape_controls(self):
        self.check_mutations(3, [
            ('fake historical proof', lambda row: row.update(historical_fixture_only=True)),
            ('missing native control', lambda row: row.update(real_native_controls=5)),
            ('unknown attempt', lambda row: row.update(unconfirmed_native_attempts=1)),
            ('other recipe', lambda row: row.update(sandbox_recipe_sha256='0' * 64)),
        ] + [(name, lambda row, field=name: row.update({field: False})) for name in (
            'network_disabled', 'filesystem_escape_denied', 'include_escape_denied',
            'shell_escape_denied', 'resource_limits_verified', 'owned_cleanup_verified')]
          + [(name, lambda row, field=name: row['escape_controls'].pop(field)) for name in runtime.ESCAPE_CONTROLS])

    def test_actual_native14_shape_needs_no_invented_schema_or_auditor(self):
        native = synthetic_documents()[4]
        for missing in ('schema', 'auditor_sha256', 'historical_fixture_only'):
            self.assertNotIn(missing, native)
        self.assertIs(self.documents()['real_execution_admitted'], False)

    def test_native14_counts_labels_and_zero_model_scope_are_strict(self):
        changes = [
            ('wrong native spec', lambda row: row.update(spec_sha256='0' * 64)),
            ('measurement invalid', lambda row: row.update(evidence_complete=False)),
            ('discrimination failed', lambda row: row.update(qualified_for_generated_control_discrimination=False)),
            ('wrong ordered labels', lambda row: row.update(controls=row['controls'][::-1])),
            ('missing label', lambda row: row['controls'].pop()),
            ('unknown label', lambda row: row['controls'][0].update(label='invented_positive')),
            ('false acceptance', lambda row: row['controls'][1].update(false_acceptance=True)),
            ('missing false flag', lambda row: row['controls'][1].pop('false_acceptance')),
            ('control mismatch', lambda row: row['controls'][1].update(control_matched=False)),
            ('original provenance relabel', lambda row: row.update(original_harness=True)),
            ('research missing', lambda row: row.update(generated_research_test=False)),
            ('independent admission', lambda row: row.update(eligible_for_independent_models=True)),
            ('deployment', lambda row: row.update(adoption=True)),
        ]
        for field in ('native_compile_commands', 'native_simulation_commands', 'global_native_receipts',
                      'attempted_compile_commands', 'attempted_simulation_commands', 'unconfirmed_native_attempts',
                      'audit_model_calls', 'audit_eda_calls', 'model_calls', 'independent_quality_admitted'):
            changes.append((field + ' wrong count', lambda row, key=field: row.update({key: row[key] + 1})))
            changes.append((field + ' bool count', lambda row, key=field: row.update({key: False})))
        self.check_mutations(4, changes)

    def archive_fixture(self, variant=None, kind='isolation'):
        """All byte receipts fabricated, named SYNTHETIC and kept in ignored temp."""
        self.sequence += 1
        auditor = b'# SYNTHETIC AUDITOR; never executed\n'
        old_spec = {'schema': 'SYNTHETIC_run_v1', 'source_hashes': {'audit.py': runtime.sha(auditor)}}
        spec_bytes = runtime.canonical(old_spec)
        spec_sha = runtime.sha(spec_bytes)
        auditor_sha = runtime.sha(auditor)
        archive_schema, guard_prefix = 'SYNTHETIC_archive_v1', 'run/guard/'
        if kind == 'full156':
            spec_sha, auditor_sha = runtime.FULL_SPEC_SHA, runtime.FULL_AUDITOR_SHA
            archive_schema, guard_prefix = 'functional_fresh_archive_v1', 'guard/'
        guard = dict(complete=True, passed=True, model_unchanged=True, protected_files_unchanged=True,
                     own_slot_released=True, stage_rc=0, owned_cleanup={'verified': True, 'remaining': []})
        files = {'run/RUN_SPEC.json': spec_bytes, 'run/audit.py': auditor,
                 guard_prefix + 'status.json': runtime.canonical(guard)}
        manifest = dict(schema=archive_schema, run_spec_sha256=spec_sha,
                        files={name: runtime.sha(data) for name, data in files.items()})
        if variant == 'wrong manifest schema':
            manifest['schema'] = 'WRONG'
        elif variant == 'wrong manifest spec':
            manifest['run_spec_sha256'] = '0' * 64
        elif variant == 'wrong member digest':
            manifest['files']['run/audit.py'] = '0' * 64
        elif variant == 'unlisted extra':
            files['SYNTHETIC_unlisted.txt'] = b'unlisted'
        elif variant == 'unsafe path':
            files['../SYNTHETIC_escape.txt'] = b'escape'
            manifest['files']['../SYNTHETIC_escape.txt'] = runtime.sha(b'escape')
        elif variant == 'backslash path':
            files['run\\SYNTHETIC_escape.txt'] = b'escape'
            manifest['files']['run\\SYNTHETIC_escape.txt'] = runtime.sha(b'escape')
        elif variant == 'wrong actual spec':
            manifest['run_spec_sha256'] = '0' * 64
            spec_sha = '0' * 64
        elif variant == 'wrong actual auditor':
            files['run/audit.py'] = b'OTHER SYNTHETIC AUDITOR'
            manifest['files']['run/audit.py'] = runtime.sha(files['run/audit.py'])
        elif variant == 'wrong frozen source':
            old_spec['source_hashes']['SYNTHETIC_helper.py'] = '0' * 64
            files['run/SYNTHETIC_helper.py'] = b'SYNTHETIC helper'
            files['run/RUN_SPEC.json'] = runtime.canonical(old_spec)
            spec_sha = runtime.sha(files['run/RUN_SPEC.json'])
            manifest['run_spec_sha256'] = spec_sha
            manifest['files']['run/RUN_SPEC.json'] = spec_sha
            manifest['files']['run/SYNTHETIC_helper.py'] = runtime.sha(files['run/SYNTHETIC_helper.py'])
        elif variant == 'guard incomplete':
            guard['complete'] = False
            files[guard_prefix + 'status.json'] = runtime.canonical(guard)
            manifest['files'][guard_prefix + 'status.json'] = runtime.sha(files[guard_prefix + 'status.json'])
        elif variant == 'guard descendant live':
            guard['owned_cleanup']['remaining'] = [{'pid': 42}]
            files[guard_prefix + 'status.json'] = runtime.canonical(guard)
            manifest['files'][guard_prefix + 'status.json'] = runtime.sha(files[guard_prefix + 'status.json'])
        archive = self.base / ('SYNTHETIC_archive_' + str(self.sequence) + '.zip')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(archive, 'x') as out:
                for name, data in files.items():
                    out.writestr(name, data)
                if variant == 'duplicate member':
                    out.writestr('run/audit.py', auditor)
                out.writestr('ARCHIVE_MANIFEST.json', runtime.canonical(manifest))
        archive_sha = runtime.file_sha(archive)
        report = dict(SYNTHETIC_fixture_only=True, archive_sha256=archive_sha, spec_sha256=spec_sha,
                      source_evidence={'spec_sha256': spec_sha, 'archive_sha256': archive_sha,
                                       'auditor_sha256': auditor_sha}, real_execution_admitted=False)
        report_path = self.base / ('SYNTHETIC_report_' + str(self.sequence) + '.json')
        report_path.write_bytes(runtime.canonical(report))
        entry = dict(kind=kind, path=str(report_path), sha256=runtime.file_sha(report_path),
                     archive_path=str(archive), archive_sha256=archive_sha, spec_sha256=spec_sha,
                     auditor_sha256=auditor_sha, archive_schema=archive_schema,
                     run_schema='phase_full156_frozen_v1' if kind == 'full156' else old_spec['schema'],
                     guard_prefix=guard_prefix)
        return entry

    def test_fabricated_projection_archive_is_only_byte_binding_not_real_admission(self):
        entry = self.archive_fixture()
        value = runtime._bound_report(entry)
        self.assertIs(value['SYNTHETIC_fixture_only'], True)
        self.assertIs(value['real_execution_admitted'], False)
        self.assertEqual(len(runtime._BOUND_ARCHIVES), 1)

    def test_archive_type_manifest_bytes_source_and_cleanup_are_bound(self):
        for variant in ('wrong manifest schema', 'wrong manifest spec', 'wrong member digest',
                        'unlisted extra', 'unsafe path', 'backslash path', 'duplicate member',
                        'wrong actual spec', 'wrong actual auditor', 'wrong frozen source',
                        'guard incomplete', 'guard descendant live'):
            with self.subTest(variant=variant):
                entry = self.archive_fixture(variant)
                with self.assertRaises((PermissionError, KeyError, ValueError)):
                    runtime._bound_report(entry)

    def test_pinned_full_cannot_be_replaced_by_self_described_fake_archive(self):
        entry = self.archive_fixture(kind='full156')
        with self.assertRaisesRegex(PermissionError, 'actual archived spec/auditor'):
            runtime._bound_report(entry)

    def test_report_archive_digests_and_source_projection_cannot_be_changed(self):
        for variant in ('report bytes', 'archive bytes', 'source evidence', 'kind', 'report spec'):
            with self.subTest(variant=variant):
                entry = self.archive_fixture()
                if variant == 'report bytes':
                    Path(entry['path']).write_bytes(b'{}')
                elif variant == 'archive bytes':
                    with Path(entry['archive_path']).open('ab') as stream:
                        stream.write(b'CHANGED')
                elif variant == 'kind':
                    entry['kind'] = 'invented'
                else:
                    value = runtime.read_json(entry['path'])
                    if variant == 'source evidence':
                        value['source_evidence']['auditor_sha256'] = '0' * 64
                    else:
                        value['spec_sha256'] = '0' * 64
                    Path(entry['path']).write_bytes(runtime.canonical(value))
                    entry['sha256'] = runtime.file_sha(entry['path'])
                with self.assertRaises(PermissionError):
                    runtime._bound_report(entry)

    def test_archive_cache_never_bypasses_current_bytes_or_receipt_checks(self):
        entry = self.archive_fixture()
        runtime._bound_report(entry)
        value = runtime.read_json(entry['path'])
        value['source_evidence']['spec_sha256'] = '0' * 64
        Path(entry['path']).write_bytes(runtime.canonical(value))
        entry['sha256'] = runtime.file_sha(entry['path'])
        with self.assertRaises(PermissionError):
            runtime._bound_report(entry)
        # Even a cached archive's current complete bytes are still digested.
        another = self.archive_fixture()
        runtime._bound_report(another)
        with Path(another['archive_path']).open('ab') as stream:
            stream.write(b'AFTER_CACHE_CHANGE')
        with self.assertRaises(PermissionError):
            runtime._bound_report(another)

    def test_bound_prerequisite_must_stay_in_own_raw_namespace(self):
        with self.assertRaises(PermissionError):
            runtime._own_path(Path(runtime.ROOT) / 'public_proof.json')
        with self.assertRaises(PermissionError):
            runtime._own_path('relative_proof.json')

    def package_fixture(self, files, outputs=None):
        self.sequence += 1
        root = self.base / ('SYNTHETIC_public_' + str(self.sequence))
        root.mkdir()
        outputs = outputs or [name for name in files if name.endswith('/main.sv') or name == 'main.sv']
        binding = dict(output_paths=outputs, input_context_sha256={
            name: runtime.sha(data.encode()) for name, data in files.items() if name not in outputs})
        public = {}
        for name, data in files.items():
            path = root.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.encode())
            public[name] = {'path': str(path), 'sha256': runtime.file_sha(path)}
        includes = []
        import re
        for name, data in files.items():
            for match in re.finditer(r'`include\s+"([^"\n]+)"', data):
                includes.append({'source': name, 'dependency': (PurePosixPath(name).parent / match[1]).as_posix()})
        package = dict(public_hdl=public, output_paths=outputs,
                       source_paths=[name for name in files if PurePosixPath(name).suffix in {'.v', '.sv'}],
                       header_paths=[name for name in files if PurePosixPath(name).suffix not in {'.v', '.sv'}],
                       mode='REAL', resolved_includes=includes,
                       include_isolation='REAL_BOUND_OS_AUDIT' if includes else 'NO_INCLUDE_DIRECTIVE_DETECTED')
        return package, binding

    def test_complete_public_sources_and_headers_are_preserved_without_rename(self):
        files = {'rtl/main.sv': 'module native_main; endmodule\n',
                 'rtl/helper.v': 'module native_helper; endmodule\n',
                 'rtl/defs.svh': '`define PUBLIC_ONLY 1\n'}
        package, binding = self.package_fixture(files)
        materialized = runtime.verify_public_package(package, binding)
        self.assertEqual(materialized, {name: value.encode() for name, value in files.items()})
        argv = runtime.compiler_argv(materialized)
        self.assertIn('/inputs/rtl/main.sv', argv)
        self.assertIn('/inputs/rtl/helper.v', argv)
        self.assertNotIn('/inputs/rtl/defs.svh', argv)
        self.assertFalse(any('TopModule' in item for item in argv))

    def test_candidate_context_input_hash_file_set_and_mode_are_bound(self):
        for variant in ('drop helper', 'extra hidden source', 'wrong physical hash', 'changed helper',
                        'omit source', 'header as source', 'output rename', 'fake mode', 'fake include flag'):
            with self.subTest(variant=variant):
                package, binding = self.package_fixture({'rtl/main.sv': 'module native_main; endmodule\n',
                                                         'rtl/helper.sv': 'module native_helper; endmodule\n',
                                                         'rtl/defs.svh': '`define A 1\n'})
                if variant == 'drop helper':
                    package['public_hdl'].pop('rtl/helper.sv')
                elif variant == 'extra hidden source':
                    package['public_hdl']['hidden_answer.sv'] = dict(package['public_hdl']['rtl/helper.sv'])
                elif variant == 'wrong physical hash':
                    package['public_hdl']['rtl/main.sv']['sha256'] = '0' * 64
                elif variant == 'changed helper':
                    entry = package['public_hdl']['rtl/helper.sv']
                    Path(entry['path']).write_bytes(b'module changed_helper; endmodule\n')
                    entry['sha256'] = runtime.file_sha(entry['path'])
                elif variant == 'omit source':
                    package['source_paths'].pop()
                elif variant == 'header as source':
                    package['source_paths'].append('rtl/defs.svh')
                elif variant == 'output rename':
                    package['output_paths'] = ['TopModule.sv']
                elif variant == 'fake mode':
                    package['mode'] = 'FAKE'
                else:
                    package['include_isolation'] = 'FAKE_CAPABILITY_ONLY'
                with self.assertRaises((ValueError, PermissionError)):
                    runtime.verify_public_package(package, binding)

    def test_literal_and_nested_include_receipts_are_recomputed(self):
        files = {'rtl/main.sv': '`include "first.svh"\nmodule native_main; endmodule\n',
                 'rtl/first.svh': '`include "second.svh"\n', 'rtl/second.svh': '`define A 1\n'}
        package, binding = self.package_fixture(files)
        self.assertEqual(set(runtime.verify_public_package(package, binding)), set(files))
        package['resolved_includes'][1]['dependency'] = 'rtl/first.svh'
        with self.assertRaises(ValueError):
            runtime.verify_public_package(package, binding)

    def test_same_named_different_headers_are_not_silently_misresolved(self):
        package, binding = self.package_fixture({
            'a/defs.svh': '`define A 0\n', 'b/defs.svh': '`define A 1\n',
            'b/main.sv': '`include "defs.svh"\nmodule native_main; endmodule\n'})
        self.assertEqual(package['resolved_includes'], [{'source': 'b/main.sv', 'dependency': 'b/defs.svh'}])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            runtime.verify_public_package(package, binding)

    def test_macro_missing_absolute_parent_include_and_forged_receipt_reject(self):
        for directive in ('`include MACRO_HEADER', '`include "missing.svh"',
                          '`include "/etc/passwd"', '`include "../defs.svh"'):
            with self.subTest(directive=directive):
                package, binding = self.package_fixture({'rtl/main.sv': directive + '\nmodule native_main; endmodule\n',
                                                         'rtl/defs.svh': '`define A 1\n'})
                with self.assertRaises((ValueError, PermissionError)):
                    runtime.verify_public_package(package, binding)
        package, binding = self.package_fixture({'rtl/main.sv': '`include "defs.svh"\nmodule native_main; endmodule\n',
                                                 'rtl/defs.svh': '`define A 1\n'})
        package['resolved_includes'] = []
        with self.assertRaises(ValueError):
            runtime.verify_public_package(package, binding)

    def tree_fixture(self):
        self.sequence += 1
        root = self.base / ('SYNTHETIC_tree_' + str(self.sequence))
        (root / 'nested').mkdir(parents=True)
        (root / 'empty').mkdir()
        (root / 'lib.so').write_bytes(b'SYNTHETIC_LIBRARY_BYTES')
        (root / 'nested' / 'helper.so').write_bytes(b'SYNTHETIC_HELPER_BYTES')
        hashes = {p.relative_to(root).as_posix(): runtime.file_sha(p) for p in root.rglob('*') if p.is_file()}
        return root, hashes, ['empty', 'nested']

    def test_regular_dependency_tree_and_empty_directories_are_exact(self):
        root, hashes, directories = self.tree_fixture()
        runtime._tree_verify(root, hashes, directories)
        for variant in ('extra directory', 'missing directory', 'changed library', 'extra file'):
            with self.subTest(variant=variant):
                root, hashes, directories = self.tree_fixture()
                if variant == 'extra directory':
                    (root / 'extra_empty').mkdir()
                elif variant == 'missing directory':
                    (root / 'empty').rmdir()
                elif variant == 'changed library':
                    (root / 'lib.so').write_bytes(b'CHANGED')
                else:
                    (root / 'unknown.so').write_bytes(b'UNKNOWN')
                with self.assertRaises(PermissionError):
                    runtime._tree_verify(root, hashes, directories)

    def test_tree_checks_root_files_and_directory_link_flags_before_reading(self):
        # Simulated lstat link flags: this is portable pure boundary coverage,
        # not a claim to have created actual symlinks/junctions on this host.
        for selected in ('root', 'file', 'directory', 'empty'):
            with self.subTest(selected=selected):
                root, hashes, directories = self.tree_fixture()
                target = {'root': root, 'file': root / 'lib.so', 'directory': root / 'nested',
                          'empty': root / 'empty'}[selected]
                actual_is_symlink = Path.is_symlink
                def flag(path):
                    return path == target or actual_is_symlink(path)
                with mock.patch.object(Path, 'is_symlink', flag):
                    with self.assertRaisesRegex(ValueError, 'symbolic link or junction'):
                        runtime._tree_verify(root, hashes, directories)

    def test_wrong_paired_dependency_rejects_before_dynamic_import(self):
        for entry in ({'path': str(self.base / 'SYNTHETIC_paired.py'), 'sha256': '0' * 64},
                      {'path': '/workspace/team/runs/fpga_owner/ross_diagnostic_repair_20261004_v1/paired_checkpoint.py',
                       'sha256': '0' * 64}):
            with self.subTest(entry=entry):
                with self.assertRaises(PermissionError):
                    runtime._paired({'paired_dependency': entry})

    def test_missing_frozen_run_spec_cannot_become_real_admission(self):
        missing_root = self.base / 'SYNTHETIC_unfrozen_run'
        missing_root.mkdir()
        with mock.patch.object(runtime, 'ROOT', missing_root), mock.patch.object(runtime.sys, 'platform', 'linux'):
            with self.assertRaises(FileNotFoundError):
                runtime._physical_admission(synthetic_documents()[5], True, True)

    def physical_fixture(self):
        """Mock own frozen/status/process proof only to reach resource rejection.

        It cannot complete admission: reaching dependency checks raises a sentinel.
        No actual shared lock or /proc model process is accessed.
        """
        documents = synthetic_documents()
        spec, full, original, isolation, native, binding = documents
        source_hashes = {name: 'f' * 64 for name in (
            'adapter.py', 'worker.py', 'runtime.py', 'native_reset_contract.py',
            'INPUT_MANIFEST.json', 'supervisor.py', 'solve_child.py', 'guard_wrapper.py')}
        source_hashes['adapter.py'] = runtime.ADAPTER_SHA
        source_hashes['native_reset_contract.py'] = runtime.CONTRACT_SHA
        identity = dict(pid=2013333, starttime='823869819', exe='llama-server',
                        command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')
        spec.update(cloud_root=str(self.base), resource_check=str(self.base / 'guard/resource_check.json'),
                    source_hashes=source_hashes, qualification={'SYNTHETIC_kind': 'full'},
                    original_harness_admission={'SYNTHETIC_kind': 'original'},
                    isolation_admission={'SYNTHETIC_kind': 'isolation'},
                    native_reset_admission={'SYNTHETIC_kind': 'native'},
                    slot_owner='SYNTHETIC_RUNTIME_OWNER', slot_lock_path='/workspace/team/SLOT.lock',
                    model_name='SYNTHETIC_FIXED_MODEL', model_identity=identity,
                    kit='/SYNTHETIC/kit')
        spec['toolchain'].update(prefix='/SYNTHETIC/toolchain')
        inventory = dict(input_sha256={'SYNTHETIC_task_' + str(index): '0' * 64 for index in range(936)},
                         official_sha256={'SYNTHETIC_official_' + str(index): '1' * 64 for index in range(35)})
        lock_bytes = b'SYNTHETIC_RUNTIME_OWNER\nSYNTHETIC_LEASE\n'
        resource = dict(slot_owner=spec['slot_owner'], slot_lock_path=spec['slot_lock_path'],
                        slot_lock_sha256=runtime.sha(lock_bytes), model_name=spec['model_name'],
                        llm_base_url='http://127.0.0.1:8000/v1', model_pid=identity['pid'],
                        model_starttime=identity['starttime'], model_identity=copy.deepcopy(identity),
                        protected={'tasks': copy.deepcopy(inventory['input_sha256']),
                                   'official': copy.deepcopy(inventory['official_sha256'])})
        guard = dict(complete=False, error=None, stage_pid=os.getpid())
        return dict(spec=spec, full=full, original=original, isolation=isolation, native=native,
                    binding=binding, inventory=inventory, resource=resource, guard=guard,
                    lock_bytes=lock_bytes)

    def call_physical_fixture(self, fixture):
        import supervisor
        class ReachedSyntheticResourceBoundary(PermissionError):
            pass
        values = {str(self.base / 'RUN_SPEC.json'): fixture['spec'],
                  str(self.base / 'guard/resource_check.json'): fixture['resource'],
                  str(self.base / 'guard/status.json'): fixture['guard'],
                  str(self.base / 'INPUT_MANIFEST.json'): fixture['inventory']}
        actual_read_bytes = Path.read_bytes
        def fake_bytes(path):
            if path.as_posix() == '/workspace/team/SLOT.lock':
                return fixture['lock_bytes']
            return actual_read_bytes(path)
        stage = dict(pid=os.getpid(), starttime='SYNTHETIC_STAGE_START', ppid=123,
                     pgid=os.getpid(), sid=os.getpid())
        snapshot = dict(root=str(self.base), spec_sha256='f' * 64,
                        resource_sha256='e' * 64, status_sha256='d' * 64, stage=stage,
                        model_pid=fixture['resource']['model_pid'],
                        slot_lock_sha256=fixture['resource']['slot_lock_sha256'],
                        wrapper={'SYNTHETIC': True})
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runtime, 'ROOT', self.base))
            stack.enter_context(mock.patch.object(runtime.sys, 'platform', 'linux'))
            stack.enter_context(mock.patch.object(runtime, 'read_json', side_effect=lambda path: values[str(path)]))
            stack.enter_context(mock.patch.object(runtime, 'file_sha', side_effect=lambda path: fixture['spec']['source_hashes'][Path(path).name]))
            stack.enter_context(mock.patch.object(runtime, '_bound_report', side_effect=lambda entry: fixture[entry['SYNTHETIC_kind']]))
            stack.enter_context(mock.patch.object(supervisor, 'guard_snapshot', return_value=(snapshot, fixture['spec'])))
            stack.enter_context(mock.patch.object(Path, 'read_bytes', fake_bytes))
            tree = stack.enter_context(mock.patch.object(runtime, '_tree_verify', side_effect=ReachedSyntheticResourceBoundary('SYNTHETIC resource gates reached; no real admission')))
            error = None
            try:
                runtime._physical_admission(fixture['binding'], True, True)
            except Exception as exc:
                error = exc
            return error, tree.call_count

    def test_mock_physical_controls_stop_before_dependency_or_actual_io(self):
        error, reached = self.call_physical_fixture(self.physical_fixture())
        self.assertIsInstance(error, PermissionError)
        self.assertIn('SYNTHETIC resource gates reached', str(error))
        self.assertEqual(reached, 1)

    def test_complete_model_identity_is_not_reduced_to_pid_and_start(self):
        mutations = [
            ('same pid/start other executable', lambda row: row['resource']['model_identity'].update(exe='SYNTHETIC_OTHER_MODEL')),
            ('same pid/start other command', lambda row: row['resource']['model_identity'].update(command_sha256='0' * 64)),
            ('extra identity field', lambda row: row['spec']['model_identity'].update(extra='unbound')),
            ('scalar process mismatch', lambda row: row['resource'].update(model_starttime='OTHER')),
            ('missing full identity', lambda row: row['resource'].pop('model_identity')),
        ]
        for label, mutation in mutations:
            with self.subTest(label=label):
                fixture = self.physical_fixture()
                mutation(fixture)
                error, reached = self.call_physical_fixture(fixture)
                self.assertIsInstance(error, PermissionError)
                self.assertIn('model', str(error))
                self.assertEqual(reached, 0)

    def test_lock_path_actual_bytes_digest_and_owner_are_all_bound(self):
        mutations = [
            ('other spec lock', lambda row: row['spec'].update(slot_lock_path='/SYNTHETIC/other.lock')),
            ('other resource lock', lambda row: row['resource'].update(slot_lock_path='/SYNTHETIC/other.lock')),
            ('other resource owner', lambda row: row['resource'].update(slot_owner='OTHER')),
            ('actual changed lock bytes', lambda row: row.update(lock_bytes=b'OTHER_OWNER\nOTHER_LEASE\n')),
            ('self-consistent wrong owner', lambda row: (row.update(lock_bytes=b'OTHER_OWNER\n'), row['resource'].update(slot_lock_sha256=runtime.sha(b'OTHER_OWNER\n')))),
            ('wrong digest receipt', lambda row: row['resource'].update(slot_lock_sha256='0' * 64)),
        ]
        for label, mutation in mutations:
            with self.subTest(label=label):
                fixture = self.physical_fixture()
                mutation(fixture)
                error, reached = self.call_physical_fixture(fixture)
                self.assertIsInstance(error, PermissionError)
                self.assertTrue(any(word in str(error) for word in ('slot', 'lock')))
                self.assertEqual(reached, 0)

    def test_exact936_and35_inventory_cannot_be_replaced_by_resource_self_description(self):
        mutations = [
            ('935 input files', lambda row: row['inventory']['input_sha256'].pop('SYNTHETIC_task_0')),
            ('34 official files', lambda row: row['inventory']['official_sha256'].pop('SYNTHETIC_official_0')),
            ('936 same paths different task hash', lambda row: row['resource']['protected']['tasks'].update(SYNTHETIC_task_0='9' * 64)),
            ('35 same paths different official hash', lambda row: row['resource']['protected']['official'].update(SYNTHETIC_official_0='9' * 64)),
            ('resource omits task', lambda row: row['resource']['protected']['tasks'].pop('SYNTHETIC_task_0')),
            ('frozen inventory source missing', lambda row: row['spec']['source_hashes'].pop('INPUT_MANIFEST.json')),
        ]
        for label, mutation in mutations:
            with self.subTest(label=label):
                fixture = self.physical_fixture()
                mutation(fixture)
                error, reached = self.call_physical_fixture(fixture)
                self.assertIsInstance(error, PermissionError)
                self.assertTrue(any(word in str(error) for word in ('inventory', 'frozen')))
                self.assertEqual(reached, 0)


if __name__ == '__main__':
    unittest.main()
