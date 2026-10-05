"""Pure source/protocol/accounting controls. All native receipts below are synthetic."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import audit
import controls as c
import stage
from contract import parse_prompt

ROOT = Path(__file__).resolve().parent


def data(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def synthetic_log(prompt, item, override=None):
    receipt = parse_prompt(prompt)
    contract = receipt['contract']
    contract_sha = c.sha(json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())
    lines = [f"TABLE_BINDING task={item['label']} prompt_sha256={receipt['prompt_sha256']} contract_sha256={contract_sha}"]
    mismatches = 0
    for index, row in enumerate(contract['rows']):
        if not row['care']:
            continue
        expected = row['expected']
        observed = (int(item['kind'][-1]) if item['kind'] in ('constant0', 'constant1') else
                    expected ^ int(item['kind'] == 'single_cell' and index == item['single_flip_row']))
        if override is not None:
            observed = override(index, expected, observed)
        mismatches += observed != expected
        inputs = ','.join(bit + '=' + str(row['input_bits'][bit]) for bit in contract['input_bit_order'])
        lines.append(f"TABLE_CARE task={item['label']} row={index} inputs={inputs} expected={expected} observed={observed}")
    lines.append(f"R2_PROBE_RESULT task={item['label']} checks={item['checks']} mismatches={mismatches}")
    if item['kind'] == 'sentinel':
        lines.append(c.SENTINEL + ' task=' + item['label'])
        lines.append('Fatal: OWN_TABLE_SENTINEL (SYNTHETIC, not executed)')
    return '\n'.join(lines) + '\n'


def fixture():
    """Full synthetic75 receipt map, only for exercising the read-only auditor."""
    private, prepared = c.validate_assets(ROOT)
    bindings = c.read(ROOT / 'raw_evidence/DEPENDENCY_BINDINGS.json')
    files = {'run/' + name: c.contained(ROOT, name).read_bytes() for name in c.source_paths(private)}
    files['run/PREPARATION_RECEIPT.json'] = (ROOT / 'PREPARATION_RECEIPT.json').read_bytes()
    env = bindings['environment']
    spec = {'schema': 'prompt_table_generated_calibration_frozen_v1', 'cloud_root': '/SYNTHETIC_NOT_EXECUTED/table',
            'kit': bindings['kit'], 'controls_max': 25, 'commands_per_tool': 25, 'model_requests_max': 0,
            'source_hashes': {n: c.sha(files['run/' + n]) for n in c.source_paths(private)},
            'dependencies_cloud': bindings['dependencies_cloud'], 'dependency_hashes': bindings['dependency_hashes'],
            'compiler_tools': env['tools'], 'vivado_bin': env['vivado_bin'], 'udev_stub': env['udev_stub'],
            'udev_files': {'libudev.so.0': c.sha(b'SYNTHETIC_LIBRARY_NOT_EXECUTED')},
            'compiler_env': {'PATH': '/SYNTHETIC_PATH', 'VIVADO_BIN': env['vivado_bin'], 'LD_LIBRARY_PATH': env['udev_stub']},
            'protected': bindings['protected'], 'model_identity': {'pid': 999999, 'starttime': 'SYNTHETIC', 'command_sha256': '0'*64},
            'slot_owner': 'SYNTHETIC_OWNER', 'slot_lock_path': '/SYNTHETIC_LOCK', 'llm_base_url': 'http://127.0.0.1:1/v1',
            'model_name': 'SYNTHETIC_NOT_CALLED', 'preparation_receipt_sha256': c.sha(files['run/PREPARATION_RECEIPT.json'])}
    dep_root = Path(bindings['dependencies_cloud'])
    if not dep_root.is_dir():
        dep_root = ROOT.parents[1] / '03_analysis/ross_diagnostic_repair_20261004'
    for name, digest in spec['dependency_hashes'].items():
        files['dependencies/' + name] = (dep_root / name).read_bytes()
        assert c.sha(files['dependencies/' + name]) == digest
    spec_bytes = data(spec)
    spec_sha = c.sha(spec_bytes)
    files['run/RUN_SPEC.json'] = spec_bytes
    resource = {'resource_idle': True, 'model_identity': spec['model_identity'], 'model_pid': 999999,
                'model_starttime': 'SYNTHETIC', 'protected': spec['protected']}
    resource.update({key: spec[key] for key in ('slot_owner', 'slot_lock_path', 'llm_base_url', 'model_name')})
    files['guard/resource_check.json'] = data(resource)
    files['guard/status.json'] = data({'complete': True, 'passed': True, 'model_unchanged': True,
                                     'protected_files_unchanged': True, 'own_slot_released': True, 'stage_rc': 0,
                                     'owned_cleanup': {'verified': True, 'remaining': []}})
    environment = {'verified': True, 'tools': spec['compiler_tools'], 'compiler_env': spec['compiler_env'],
                   'udev_files': spec['udev_files'], 'complete_inherited_environment_sha256': 'e'*64, 'model_calls': 0, 'eda_calls': 0}
    files['run/results/ENVIRONMENT_PREFLIGHT.json'] = data(environment)
    rows = []
    tick = 1
    for meta, prompt, item in prepared:
        base = 'run/results/' + meta['label'] + '/'
        files[base + 'candidate.sv'] = item['rtl'].encode()
        files[base + 'tb.sv'] = item['tb'].encode()
        hashes = {'candidate.sv': meta['rtl_sha256'], 'tb.sv': meta['tb_sha256']}
        files[base + 'SOURCE_MANIFEST.json'] = data(hashes)
        command_paths = []
        for sequence, (tool, argv, cwd) in enumerate(c.commands(meta, spec)):
            log = (synthetic_log(prompt.decode(), item) if tool == 'xsim' else 'SYNTHETIC compiler success, never executed\n').encode()
            files[base + tool + '.log'] = log
            rc = 1 if tool == 'xsim' and item['kind'] == 'sentinel' else 0
            name = base + f'native_calls/{sequence:02d}_{tool}.json'
            files[name] = data({'schema': 'owned_table_native_command_v1', 'label': meta['label'], 'tool': tool,
                                'sequence': sequence, 'argv': argv, 'cwd': cwd, 'source_input_sha256': hashes,
                                'compiler_entry_sha256': spec['compiler_tools'][tool]['sha256'], 'environment_sha256': 'e'*64,
                                'resource_check_sha256': c.sha(files['guard/resource_check.json']), 'spec_sha256': spec_sha,
                                'attempted': True, 'confirmed': True, 'finalized': True, 'inputs_unchanged': True,
                                'started_ns': tick, 'finished_ns': tick + 1,
                                'command': {'log': cwd + '/' + tool + '.log', 'log_sha256': c.sha(log), 'log_bytes': len(log),
                                            'timeout': False, 'launch_error': None, 'remaining_live_group': [], 'returncode': rc}})
            tick += 2
            command_paths.append(name.removeprefix('run/results/'))
        parsed = c.classify(prompt.decode(), item, files[base + 'xsim.log'].decode(), rc)
        files[base + 'PARSED.json'] = data(parsed)
        row = {'index': meta['index'], 'label': meta['label'], 'kind': meta['kind'], 'commands': command_paths,
               'error': None, 'evidence_complete': True, 'control_matched': parsed['control_matched'],
               'checks': meta['checks'], 'mismatches': parsed['parsed']['mismatches'],
               'parsed_sha256': c.sha(files[base + 'PARSED.json']), 'generated_research_test': True, 'original_harness': False}
        files[base + 'ROW.json'] = data(row)
        rows.append(row)
    files['run/results/summary.json'] = data({'schema': 'prompt_table_generated_calibration_measurement_v1', 'complete': True, 'passed': True, 'evidence_complete': True,
        'error': None, 'spec_sha256': spec_sha, 'model_calls': 0, 'original_harness': False, 'generated_research_test': True,
        'score_gain_measured': False, 'adoption': False, 'attempted_native_commands': 75, 'actual_native_commands': 75,
        'unconfirmed_native_attempts': 0, 'inventory_errors': [], 'actual_by_tool': dict.fromkeys(c.TOOLS, 25),
        'attempted_commands_by_tool': dict.fromkeys(c.TOOLS, 25), 'qualified_for_generated_control_discrimination': True, 'rows': rows})
    return files, spec_sha, prepared


class CalibrationControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.spec_sha, cls.prepared = fixture()

    def checked(self, files=None):
        files = self.files if files is None else files
        return audit.check_evidence(files.__getitem__, list(files), self.spec_sha)

    def mutate_json(self, files, name, mutation):
        value = json.loads(files[name])
        mutation(value)
        files[name] = data(value)

    def log_changed(self, files, label, change):
        base = 'run/results/' + label + '/'
        log = change(files[base + 'xsim.log'].decode()).encode()
        files[base + 'xsim.log'] = log
        self.mutate_json(files, base + 'native_calls/02_xsim.json',
                         lambda r: r['command'].update(log_sha256=c.sha(log), log_bytes=len(log)))

    def test_generated25_three_commands_each_exact_plans(self):
        self.assertEqual(len(self.prepared), 25)
        plans = [cmd for meta, _, _ in self.prepared for cmd in c.commands(meta, {'cloud_root': '/OWN', 'vivado_bin': '/TOOLS'})]
        self.assertEqual(len(plans), 75)
        self.assertEqual([sum(p[0] == tool for p in plans) for tool in c.TOOLS], [25, 25, 25])
        self.assertEqual([meta['label'] for meta, _, _ in self.prepared], list(c.ORDER))

    def test_positive_and_single_cell_differ_exactly_one_care(self):
        for task in c.TASKS:
            items = [item for meta, _, item in self.prepared if meta['task'] == task]
            p, flip = items[0], items[3]
            pattern = r"([01]+): [A-Za-z_][A-Za-z0-9_]*=1'b([01]);"
            positive = dict(re.findall(pattern, p['rtl']))
            negative = dict(re.findall(pattern, flip['rtl']))
            self.assertEqual(set(positive), set(negative))
            self.assertEqual(sum(positive[k] != negative[k] for k in positive), 1)
            self.assertEqual(flip['expected_mismatches'], 1)
            self.assertNotIn('ref.sv', p['rtl'])

    def test_const_negatives_have_both_care_values_and_semantic_counts(self):
        for meta, prompt, item in self.prepared:
            with self.subTest(label=meta['label']):
                classified = c.classify(prompt.decode(), item, synthetic_log(prompt.decode(), item), 1 if item['kind'] == 'sentinel' else 0)
                self.assertTrue(classified['control_matched'])
                self.assertEqual(classified['parsed']['mismatches'], meta['expected_mismatches'])
                if item['kind'] in ('constant0', 'constant1'):
                    self.assertGreater(meta['expected_mismatches'], 0)

    def test_full_synthetic75_audit_is_only_protocol_test(self):
        result = self.checked()
        self.assertEqual(result['actual_native_commands'], 75)  # Synthetic declared receipts only.
        self.assertTrue(result['qualified_for_generated_control_discrimination'])
        self.assertFalse(result['original_harness'])
        self.assertFalse(result['score_gain_measured'])

    def test_compile_or_elaboration_fail_not_semantic_success(self):
        for number, tool in enumerate(c.TOOLS[:2]):
            with self.subTest(tool=tool):
                files = dict(self.files)
                name = 'run/results/' + c.ORDER[1] + f'/native_calls/{number:02d}_{tool}.json'
                self.mutate_json(files, name, lambda r: r['command'].update(returncode=1))
                with self.assertRaises(ValueError): self.checked(files)

    def test_missing_duplicate_unknown_care_and_x_retained_no_feedback(self):
        label = c.ORDER[0]
        for change in [lambda log: '\n'.join(line for line in log.splitlines() if 'row=1 ' not in line),
                       lambda log: log + next(line for line in log.splitlines() if 'TABLE_CARE ' in line) + '\n',
                       lambda log: log.replace('observed=0', 'observed=x', 1),
                       lambda log: log.replace('inputs=a=', 'inputs=unknown=', 1)]:
            with self.subTest(change=change):
                files = dict(self.files)
                self.log_changed(files, label, change)
                with self.assertRaises(ValueError): self.checked(files)

    def test_true_rc_bool_signal_timeout_environment_binding_reject(self):
        name = 'run/results/' + c.ORDER[0] + '/native_calls/02_xsim.json'
        for mutation in [lambda r: r['command'].update(returncode=False), lambda r: r['command'].update(returncode=-9),
                         lambda r: r['command'].update(timeout=True), lambda r: r.update(environment_sha256='f'*64),
                         lambda r: r.update(argv=['fake_tool']), lambda r: r.update(inputs_unchanged=False)]:
            with self.subTest(mutation=mutation):
                files = dict(self.files); self.mutate_json(files, name, mutation)
                with self.assertRaises(ValueError): self.checked(files)

    def test_extra_unlisted_native_pending_and_missing_receipts_reject(self):
        name = 'run/results/' + c.ORDER[0] + '/native_calls/00_xvlog.json'
        for files in [dict(self.files, **{name + '.pending': b'{partial'}),
                      {k: v for k, v in self.files.items() if k != name},
                      dict(self.files, **{'run/results/UNLISTED/native_calls/00_xvlog.json': self.files[name]})]:
            with self.subTest(count=len(files)):
                with self.assertRaises((ValueError, KeyError)): self.checked(files)

    def test_guard_cleanup_protected_model_release_reject(self):
        for name, mutation in [('guard/status.json', lambda r: r.update(own_slot_released=False)),
                               ('guard/status.json', lambda r: r['owned_cleanup'].update(verified=False)),
                               ('guard/resource_check.json', lambda r: r.update(model_pid=1)),
                               ('guard/resource_check.json', lambda r: r['protected'].update(tasks={}))]:
            with self.subTest(name=name):
                files = dict(self.files); self.mutate_json(files, name, mutation)
                with self.assertRaises(ValueError): self.checked(files)

    def test_source_log_and_summary_numeric_tamper_reject(self):
        cases = [dict(self.files, **{'run/results/' + c.ORDER[0] + '/candidate.sv': b'changed'})]
        for key, value in [('actual_native_commands', 75.0), ('unconfirmed_native_attempts', 1), ('qualified_for_generated_control_discrimination', False)]:
            files = dict(self.files); self.mutate_json(files, 'run/results/summary.json', lambda r: r.update({key: value})); cases.append(files)
        files = dict(self.files); files['run/results/' + c.ORDER[0] + '/xvlog.log'] += b'changed'; cases.append(files)
        for files in cases:
            with self.subTest(count=len(files)):
                with self.assertRaises(ValueError): self.checked(files)

    def test_sentinel_requires_complete_observation_and_actual_failure(self):
        meta, prompt, item = self.prepared[4]
        log = synthetic_log(prompt.decode(), item)
        self.assertTrue(c.classify(prompt.decode(), item, log, 1)['control_matched'])
        self.assertFalse(c.classify(prompt.decode(), item, log, 0)['control_matched'])
        self.assertIn('$fatal(1,"OWN_TABLE_SENTINEL")', item['tb'])
        self.assertLess(item['tb'].index('R2_PROBE_RESULT'), item['tb'].index('$fatal(1,"OWN_TABLE_SENTINEL")'))
        for bad in [log.replace(c.SENTINEL + ' task=' + item['label'], c.SENTINEL + ' task=WRONG'),
                    '\n'.join(line for line in log.splitlines() if 'row=1 ' not in line)]:
            with self.assertRaises(ValueError): c.classify(prompt.decode(), item, bad, 1)

    def test_wrong_false_acceptance_preserved_without_qualification(self):
        meta, prompt, item = self.prepared[1]
        log = synthetic_log(prompt.decode(), item, lambda index, expected, observed: expected)
        parsed = c.classify(prompt.decode(), item, log, 0)
        self.assertTrue(parsed['evidence_complete'])
        self.assertTrue(parsed['false_acceptance'])
        self.assertFalse(parsed['control_matched'])

    def test_complete_failed_discrimination_survives_full_auditor(self):
        for index in (1, 4):
            with self.subTest(kind=self.prepared[index][0]['kind']):
                meta, prompt, item = self.prepared[index]
                files = dict(self.files)
                base = 'run/results/' + meta['label'] + '/'
                log = synthetic_log(prompt.decode(), item, lambda _, expected, observed: expected)
                self.log_changed(files, meta['label'], lambda _: log)
                self.mutate_json(files, base + 'native_calls/02_xsim.json',
                                 lambda receipt: receipt['command'].update(returncode=0))
                parsed = c.classify(prompt.decode(), item, log, 0)
                files[base + 'PARSED.json'] = data(parsed)
                row = json.loads(files[base + 'ROW.json'])
                row.update(control_matched=False, mismatches=0, parsed_sha256=c.sha(files[base + 'PARSED.json']))
                files[base + 'ROW.json'] = data(row)
                summary = json.loads(files['run/results/summary.json'])
                summary['rows'][index] = row
                summary['qualified_for_generated_control_discrimination'] = False
                files['run/results/summary.json'] = data(summary)
                result = self.checked(files)
                self.assertTrue(result['evidence_valid'])
                self.assertFalse(result['qualified_for_generated_control_discrimination'])
                self.assertFalse(result['score_gain_measured'])
                self.assertFalse(result['adoption'])
                self.assertEqual(result['rows'][index]['false_acceptance'], item['kind'] != 'sentinel')

    def test_pending_partial_receipt_conservative_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); folder = out / c.ORDER[0] / 'native_calls'; folder.mkdir(parents=True)
            path = folder / '00_xvlog.json.pending'; path.write_bytes(b'{partial')
            receipt = stage.inventory(out)
            self.assertEqual((receipt['attempted_native_commands'], receipt['actual_native_commands'], receipt['unconfirmed_native_attempts']), (1, 0, 1))
            self.assertTrue(receipt['inventory_errors'])
            (folder / '00_xvlog.json').write_bytes(data({'schema': 'owned_table_native_command_v1', 'label': c.ORDER[0], 'tool': 'xvlog', 'confirmed': True, 'finalized': True}))
            self.assertEqual(stage.inventory(out)['actual_native_commands'], 0)
            (folder / 'junk.pending.pending').write_bytes(b'unknown')
            self.assertTrue(any('unknown' in error for error in stage.inventory(out)['inventory_errors']))

    def test_no_freeze_rejected_before_any_native_or_process_call(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(stage, 'ROOT', Path(temp)), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')), \
             patch('ctypes.CDLL', side_effect=AssertionError('prctl forbidden')), \
             patch('socket.socket', side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(ValueError, 'RUN_SPEC absent'):
                stage.main(SimpleNamespace(kit=Path(temp), resource_check=Path(temp) / 'guard/resource_check.json'))


if __name__ == '__main__':
    unittest.main()
