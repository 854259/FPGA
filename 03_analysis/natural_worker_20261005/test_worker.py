"""Synthetic engineering tests; fake transport/compiler never grade real RTL."""
from pathlib import Path
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import worker

G = '你是 RTL 代码生成器。只输出一个完整、可综合的 Verilog/SystemVerilog `TopModule`，不要输出 Markdown、解释或测试台。\nPreserve all ports and native module names.\n'
REPAIR = 'Return complete TopModule using only actual candidate compiler diagnostics.'
IMMUTABLE_ADAPTER_SHA = '9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9'
LINK_METHODS = []


def synthetic_record():
    return dict(id='PRIVATE_TASK_ID', categories=['PRIVATE_CATEGORY'],
                input=dict(prompt='Design native_main and native_aux with both native output ports.\n合成工程测试。',
                           context={'rtl/native_main.sv': 'module native_main; // public partial\n',
                                    'rtl/helper.sv': 'module helper; endmodule\n',
                                    'rtl/definitions.svh': '`define SYNTHETIC_CONSTANT 1\n',
                                    'docs/spec.md': 'Public helper documentation — exact Unicode.\n'}),
                output=dict(response='', context={'rtl/native_main.sv': '', 'rtl/native_aux.sv': ''}),
                harness={'files': {'src/hidden_test.py': 'PRIVATE_HARNESS', 'rtl/answer.sv': 'PRIVATE_ANSWER'}})


def files_for(record=None):
    record = record or synthetic_record()
    return {name: ('module native_main(input wire a, output wire positive, output wire negative);\n'
                   'assign positive=a; assign negative=~a;\nendmodule\n') if name.endswith('native_main.sv')
            else 'module native_aux; endmodule\r\n' for name in record['output']['context']}


def reply(files=None):
    return json.dumps({'files': files or files_for()}, ensure_ascii=False)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def fake_transport(responses=None, effect=None):
    supplied = list(responses or [dict(confirmed=True, reply=reply(), finish_reason='stop')])
    calls = []

    def call(request, timeout):
        calls.append((copy.deepcopy(request), timeout))
        if effect:
            effect(request, timeout, len(calls))
        response = supplied[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)

    call.io_kind = 'FAKE'
    call.calls = calls
    return call


def fake_compiler(outcomes=None, effect=None, include_verified=False):
    supplied = list(outcomes or ['passed'])
    calls = []

    def call(package, timeout):
        calls.append((copy.deepcopy(package), timeout))
        if effect:
            effect(package, timeout, len(calls))
        result = supplied[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            return result
        return dict(outcome=result, diagnostics='FAKE actual candidate compile diagnostic: missing synthetic token.\n' if result == 'failed' else '',
                    input_sha256=worker.digest(worker.json_bytes(package)))

    call.io_kind = 'FAKE'
    call.include_isolation_verified = include_verified
    call.calls = calls
    return call


def make_directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
        LINK_METHODS.append('physical_symlink')
        return 'physical_symlink'
    except OSError:
        if os.name != 'nt':
            raise
        # Filesystem test setup only. No compiler/model/shell deletion is invoked.
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0 or not link.is_junction():
            raise RuntimeError('physical link setup unavailable: ' + result.stderr)
        LINK_METHODS.append('physical_windows_junction')
        return 'physical_windows_junction'


class WorkerEngineering(unittest.TestCase):
    def setUp(self):
        worker.RAW.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic_test_', dir=worker.RAW)
        self.base = Path(self.temp.name).absolute()
        self.clock = FakeClock()
        self.counter = 0

    def tearDown(self):
        # Verify the recursive cleanup target stays inside the owned private root.
        self.assertTrue(self.base.resolve().is_relative_to(worker.RAW.resolve()))
        self.temp.cleanup()

    def run_worker(self, record=None, transport=None, compiler=None, arm='C', generation=G, clock=None):
        self.counter += 1
        root = self.base / ('run_' + str(self.counter))
        transport = transport or fake_transport()
        compiler = compiler or fake_compiler()
        result = worker.solve(record or synthetic_record(), arm, root, generation, REPAIR,
                              transport, compiler, clock or self.clock)
        self.assertEqual(result, json.loads((root / 'summary.json').read_bytes()))
        self.assertLessEqual(result['transport_invocations'], 2)
        self.assertFalse(result['quality_verified'])
        return result, root, transport, compiler

    def test_immutable_adapter_same_sha_and_original_bytes(self):
        copied = (worker.ROOT / 'adapter.py').read_bytes()
        self.assertEqual(hashlib.sha256(copied).hexdigest(), IMMUTABLE_ADAPTER_SHA)
        self.assertEqual(worker.ADAPTER_SHA, IMMUTABLE_ADAPTER_SHA)

    def test_real_callbacks_are_rejected_before_io(self):
        transport = fake_transport()
        transport.io_kind = 'REAL'
        with self.assertRaises(ValueError):
            worker.solve(synthetic_record(), 'C', self.base / 'rejected', G, REPAIR, transport, fake_compiler(), self.clock)
        self.assertEqual(transport.calls, [])
        self.assertFalse((self.base / 'rejected').exists())

    def test_C_P_share_exact_first_request_and_original_input(self):
        c = self.run_worker(arm='C')[2].calls[0][0]
        p = self.run_worker(arm='P')[2].calls[0][0]
        self.assertEqual(c, p)
        self.assertEqual(json.loads(c['messages'][1]['content']), worker.adapter.task_view(synthetic_record()))

    def test_hidden_harness_answer_id_categories_never_forwarded(self):
        result, root, transport, compiler = self.run_worker()
        self.assertEqual(result['status'], 'fake_candidate_compile_pass')
        for value in [transport.calls[0][0], compiler.calls[0][0], json.loads((root / 'public_input.json').read_bytes())]:
            text = json.dumps(value)
            self.assertNotIn('PRIVATE', text)
            self.assertNotIn('hidden_test', text)
            self.assertNotIn('answer.sv', text)

    def test_frozen_token_sampling_and_whole_budget_arguments(self):
        _, _, transport, compiler = self.run_worker()
        request, timeout = transport.calls[0]
        self.assertEqual({k: request[k] for k in ['max_tokens', 'temperature', 'top_p']}, {'max_tokens': 8192, 'temperature': 0, 'top_p': 1})
        self.assertEqual(timeout, 300)
        self.assertEqual(compiler.calls[0][1], 300)

    def test_second_message_binds_original_input_full_previous_and_actual_diagnostics(self):
        transport = fake_transport([dict(confirmed=True, reply=reply(), finish_reason='stop')] * 2)
        result, root, transport, _ = self.run_worker(transport=transport, compiler=fake_compiler(['failed', 'passed']))
        self.assertEqual(result['transport_invocations'], 2)
        original = worker.adapter.user_content(worker.adapter.task_view(synthetic_record()))
        second = transport.calls[1][0]['messages'][1]['content']
        self.assertTrue(second.startswith(original + '\nPrevious candidate files:\n'))
        first_files = json.loads((root / 'attempt_1/reply.txt').read_bytes())['files']
        self.assertIn(json.dumps(first_files, ensure_ascii=False, separators=(',', ':')), second)
        self.assertTrue(second.endswith((root / 'attempt_1/diagnostics.txt').read_text(encoding='utf-8')))
        self.assertEqual(result['attempts'][0]['input_binding'], result['attempts'][1]['input_binding'])

    def test_changed_public_input_before_repair_abstains_without_second_request(self):
        record = synthetic_record()
        def mutate(package, timeout, number):
            record['input']['prompt'] += ' changed'
        result, _, transport, _ = self.run_worker(record=record, compiler=fake_compiler(['failed'], effect=mutate))
        self.assertEqual(result['status'], 'binding_error')
        self.assertEqual(len(transport.calls), 1)

    def test_all_context_helpers_docs_and_original_partial_materialized(self):
        record = synthetic_record()
        _, root, _, _ = self.run_worker(record=record)
        for name, text in record['input']['context'].items():
            self.assertEqual((root / 'public_context' / name).read_bytes(), text.encode())
            if name not in record['output']['context']:
                self.assertEqual((root / 'attempt_1/files' / name).read_bytes(), text.encode())
        self.assertEqual((root / 'attempt_1/files/rtl/native_main.sv').read_bytes(), files_for()['rtl/native_main.sv'].encode())

    def test_compiler_receives_only_all_public_hdl_and_preserves_native_modules(self):
        _, _, _, compiler = self.run_worker()
        package = compiler.calls[0][0]
        self.assertEqual(set(package['public_hdl']), {'rtl/native_main.sv', 'rtl/native_aux.sv', 'rtl/helper.sv', 'rtl/definitions.svh'})
        self.assertNotIn('docs/spec.md', json.dumps(package))
        self.assertNotIn('prompt', package)
        self.assertEqual(package['output_paths'], list(synthetic_record()['output']['context']))
        for name in package['output_paths']:
            self.assertNotIn('TopModule', Path(package['public_hdl'][name]['path']).read_text())

    def test_three_targets_order_contents_and_CRLF_are_exact(self):
        record = synthetic_record()
        record['output']['context']['rtl/third.sv'] = ''
        contents = files_for(record)
        result, root, _, _ = self.run_worker(record=record, transport=fake_transport([dict(confirmed=True, reply=reply(contents), finish_reason='stop')]))
        self.assertEqual(list(result['attempts'][0]['candidate_files_sha256']), list(contents))
        for name, text in contents.items():
            self.assertEqual((root / 'attempt_1/files' / name).read_bytes(), text.encode())

    def assert_invalid_reply_stops(self, text):
        result, root, transport, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=text, finish_reason='stop')]))
        self.assertEqual(result['status'], 'candidate_error')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(compiler.calls), 0)
        self.assertEqual((root / 'attempt_1/reply.txt').read_bytes(), text.encode())

    def test_missing_file_is_rejected_without_repair_or补写(self):
        self.assert_invalid_reply_stops(reply({'rtl/native_main.sv': 'module native_main; endmodule'}))

    def test_extra_file_is_rejected_without_sampling_again(self):
        files = files_for()
        files['rtl/extra.sv'] = 'module extra; endmodule'
        self.assert_invalid_reply_stops(reply(files))

    def test_duplicate_file_key_is_rejected(self):
        self.assert_invalid_reply_stops('{"files":{"rtl/native_main.sv":"a","rtl/native_main.sv":"b","rtl/native_aux.sv":"c"}}')

    def test_duplicate_files_object_is_rejected(self):
        self.assert_invalid_reply_stops('{"files":{},"files":{}}')

    def test_blank_file_is_rejected(self):
        files = files_for()
        files['rtl/native_aux.sv'] = ' '
        self.assert_invalid_reply_stops(reply(files))

    def test_non_JSON_prose_is_rejected(self):
        self.assert_invalid_reply_stops('Explanation\n' + reply())

    def test_dangerous_and_platform_paths_are_rejected(self):
        for name in ['../bad.sv', '/bad.sv', 'rtl/../bad.sv', 'rtl\\bad.sv', 'C:/bad.sv', 'rtl//bad.sv',
                     'rtl/bad.sv\x00', 'rtl/bad.sv ', 'rtl/bad.', 'rtl/CON.sv', 'rtl/COM1.v', 'rtl/a?.sv', '.']:
            record = synthetic_record()
            record['input']['context'][name] = 'synthetic content'
            with self.subTest(path=name):
                result, _, transport, compiler = self.run_worker(record=record)
                self.assertEqual(result['status'], 'input_error')
                self.assertEqual(transport.calls, [])
                self.assertEqual(compiler.calls, [])

    def test_case_alias_context_target_conflict_is_rejected(self):
        record = synthetic_record()
        record['input']['context']['rtl/NATIVE_MAIN.sv'] = 'alias'
        self.assertEqual(self.run_worker(record=record)[0]['status'], 'input_error')

    def test_file_directory_prefix_conflict_is_rejected(self):
        record = synthetic_record()
        record['input']['context']['rtl'] = 'file at directory path'
        self.assertEqual(self.run_worker(record=record)[0]['status'], 'input_error')

    def test_run_directory_outside_private_root_is_rejected_without_write(self):
        path = worker.ROOT / 'outside_private_disallowed'
        with self.assertRaises(ValueError):
            worker.solve(synthetic_record(), 'C', path, G, REPAIR, fake_transport(), fake_compiler(), self.clock)
        self.assertFalse(path.exists())

    def test_existing_run_directory_never_overwritten_or_resumed(self):
        root = self.base / 'existing'
        root.mkdir()
        (root / 'sentinel').write_text('preserve')
        transport = fake_transport()
        with self.assertRaises(FileExistsError):
            worker.solve(synthetic_record(), 'C', root, G, REPAIR, transport, fake_compiler(), self.clock)
        self.assertEqual((root / 'sentinel').read_text(), 'preserve')
        self.assertEqual(transport.calls, [])

    def test_physical_directory_symlink_or_junction_run_path_is_rejected(self):
        target = self.base / 'target'
        target.mkdir()
        link = self.base / 'link'
        make_directory_link(link, target)
        with self.assertRaises(ValueError):
            worker.solve(synthetic_record(), 'C', link / 'run', G, REPAIR, fake_transport(), fake_compiler(), self.clock)
        self.assertFalse((target / 'run').exists())

    def test_physical_link_added_inside_compiler_tree_is_rejected(self):
        target = self.base / 'target'
        target.mkdir()
        def link_inside(package, timeout, number):
            top = Path(package['public_hdl']['rtl/native_main.sv']['path']).parent.parent
            make_directory_link(top / 'alias', target)
        result, _, transport, _ = self.run_worker(compiler=fake_compiler(['failed'], effect=link_inside))
        self.assertEqual(result['status'], 'compiler_error')
        self.assertEqual(len(transport.calls), 1)

    def test_compiler_mutation_of_public_helper_is_detected_and_retained(self):
        def mutate(package, timeout, number):
            Path(package['public_hdl']['rtl/helper.sv']['path']).write_bytes(b'MUTATED')
        result, root, transport, _ = self.run_worker(compiler=fake_compiler(['failed'], effect=mutate))
        self.assertEqual(result['status'], 'compiler_error')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual((root / 'attempt_1/files/rtl/helper.sv').read_bytes(), b'MUTATED')
        self.assertTrue((root / 'attempt_1/compiler_return.json').is_file())

    def test_transport_timeout_preserves_partial_reply_and_never_retries(self):
        result, root, transport, compiler = self.run_worker(transport=fake_transport([dict(confirmed=False, reply='partial Δ\n', finish_reason='timeout')]))
        self.assertEqual(result['status'], 'transport_timeout')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])
        self.assertEqual((root / 'attempt_1/reply.txt').read_bytes(), 'partial Δ\n'.encode())

    def test_transport_exception_preserves_submitted_request_and_stops(self):
        result, root, transport, compiler = self.run_worker(transport=fake_transport([RuntimeError('FAKE interrupted request')]))
        self.assertEqual(result['status'], 'transport_error')
        self.assertTrue((root / 'attempt_1/request.json').is_file())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])

    def test_unconfirmed_transport_reply_is_preserved_without_compile(self):
        result, root, transport, compiler = self.run_worker(transport=fake_transport([dict(confirmed=False, reply=reply(), finish_reason='stop')]))
        self.assertEqual(result['status'], 'transport_unconfirmed')
        self.assertTrue((root / 'attempt_1/reply.txt').is_file())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])

    def test_length_finish_is_unconfirmed_and_never_resampled(self):
        result, _, transport, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=reply(), finish_reason='length')]))
        self.assertEqual(result['status'], 'transport_unconfirmed')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])

    def test_whole_deadline_exhausted_during_transport_preserves_reply(self):
        result, root, transport, compiler = self.run_worker(transport=fake_transport(effect=lambda *args: self.clock.advance(301)))
        self.assertEqual(result['status'], 'solve_timeout')
        self.assertTrue((root / 'attempt_1/reply.txt').is_file())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])

    def test_whole_deadline_exhausted_during_compile_preserves_receipt(self):
        result, root, transport, _ = self.run_worker(compiler=fake_compiler(['failed'], effect=lambda *args: self.clock.advance(301)))
        self.assertEqual(result['status'], 'solve_timeout')
        self.assertTrue((root / 'attempt_1/compiler_return.json').is_file())
        self.assertEqual(len(transport.calls), 1)

    def test_second_request_uses_remaining_whole_solve_budget(self):
        transport = fake_transport([dict(confirmed=True, reply=reply(), finish_reason='stop')] * 2,
                                   effect=lambda *args: self.clock.advance(50))
        compiler = fake_compiler(['failed', 'passed'], effect=lambda *args: self.clock.advance(25))
        result, _, transport, compiler = self.run_worker(transport=transport, compiler=compiler)
        self.assertEqual([timeout for _, timeout in transport.calls], [300, 225])
        self.assertEqual([timeout for _, timeout in compiler.calls], [250, 175])
        self.assertEqual(result['elapsed_s'], 150)

    def test_compiler_unconfirmed_never_triggers_repair(self):
        result, _, transport, compiler = self.run_worker(compiler=fake_compiler(['unconfirmed']))
        self.assertEqual(result['status'], 'compiler_unconfirmed')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(compiler.calls), 1)

    def test_compiler_timeout_never_triggers_repair(self):
        result, _, transport, _ = self.run_worker(compiler=fake_compiler(['timeout']))
        self.assertEqual(result['status'], 'compiler_timeout')
        self.assertEqual(len(transport.calls), 1)

    def test_failed_compiler_without_diagnostic_is_unconfirmed_and_stops(self):
        def compiler(package, timeout):
            return dict(outcome='failed', diagnostics='', input_sha256=worker.digest(worker.json_bytes(package)))
        compiler.io_kind = 'FAKE'
        result, _, transport, _ = self.run_worker(compiler=compiler)
        self.assertEqual(result['status'], 'compiler_error')
        self.assertEqual(len(transport.calls), 1)

    def test_compiler_diagnostic_input_hash_mismatch_stops(self):
        compiler = fake_compiler([dict(outcome='failed', diagnostics='FAKE real diagnostic', input_sha256='wrong')])
        result, _, transport, _ = self.run_worker(compiler=compiler)
        self.assertEqual(result['status'], 'compiler_error')
        self.assertEqual(len(transport.calls), 1)

    def test_two_confirmed_failures_use_exactly_two_requests_no_resampling(self):
        transport = fake_transport([dict(confirmed=True, reply=reply(), finish_reason='stop')] * 2)
        result, _, transport, compiler = self.run_worker(transport=transport, compiler=fake_compiler(['failed', 'failed']))
        self.assertEqual(result['status'], 'fake_candidate_compile_fail')
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(len(compiler.calls), 2)

    def test_include_unverified_abstains_and_keeps_dependency(self):
        contents = files_for()
        contents['rtl/native_main.sv'] = '`include "definitions.svh"\n' + contents['rtl/native_main.sv']
        result, root, _, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=reply(contents), finish_reason='stop')]))
        self.assertEqual(result['status'], 'compile_abstained')
        self.assertIn('unverified', result['error'])
        self.assertEqual(compiler.calls, [])
        self.assertTrue((root / 'attempt_1/files/rtl/definitions.svh').is_file())

    def test_include_fake_capability_keeps_full_hdl_dependency_binding(self):
        contents = files_for()
        contents['rtl/native_main.sv'] = '`include "definitions.svh"\n' + contents['rtl/native_main.sv']
        result, _, _, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=reply(contents), finish_reason='stop')]), compiler=fake_compiler(include_verified=True))
        self.assertEqual(result['status'], 'fake_candidate_compile_pass')
        self.assertEqual(compiler.calls[0][0]['resolved_includes'], [{'source': 'rtl/native_main.sv', 'dependency': 'rtl/definitions.svh'}])
        self.assertIn('rtl/definitions.svh', compiler.calls[0][0]['public_hdl'])
        self.assertFalse(result['quality_verified'])

    def test_missing_include_dependency_abstains_without_dropping_it(self):
        contents = files_for()
        contents['rtl/native_main.sv'] = '`include "missing.svh"\n' + contents['rtl/native_main.sv']
        result, _, _, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=reply(contents), finish_reason='stop')]), compiler=fake_compiler(include_verified=True))
        self.assertEqual(result['status'], 'compile_abstained')
        self.assertEqual(compiler.calls, [])

    def test_macro_include_operand_abstains(self):
        contents = files_for()
        contents['rtl/native_main.sv'] = '`include SOME_HEADER\n' + contents['rtl/native_main.sv']
        result, _, _, compiler = self.run_worker(transport=fake_transport([dict(confirmed=True, reply=reply(contents), finish_reason='stop')]), compiler=fake_compiler(include_verified=True))
        self.assertEqual(result['status'], 'compile_abstained')
        self.assertEqual(compiler.calls, [])

    def test_input_mutated_during_transport_stops_before_compile(self):
        record = synthetic_record()
        def mutate(*args):
            record['input']['context']['docs/spec.md'] += ' changed'
        result, root, transport, compiler = self.run_worker(record=record, transport=fake_transport(effect=mutate))
        self.assertEqual(result['status'], 'binding_error')
        self.assertTrue((root / 'attempt_1/FILES.json').is_file())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(compiler.calls, [])

    def test_deadline_before_first_request_never_starts_transport(self):
        times = iter([0, 301, 301])
        result, _, transport, compiler = self.run_worker(clock=lambda: next(times, 301))
        self.assertEqual(result['status'], 'solve_timeout')
        self.assertEqual(transport.calls, [])
        self.assertEqual(compiler.calls, [])

    def test_unrecognized_skill_preserves_context_and_stops_before_request(self):
        result, root, transport, compiler = self.run_worker(generation=G.replace('TopModule', 'other'))
        self.assertEqual(result['status'], 'binding_error')
        self.assertTrue((root / 'public_context/docs/spec.md').is_file())
        self.assertEqual(transport.calls, [])
        self.assertEqual(compiler.calls, [])

    def test_request_reply_and_file_hashes_are_exact_bytes(self):
        result, root, _, _ = self.run_worker()
        attempt = result['attempts'][0]
        for name, key in [('request.json', 'request_sha256'), ('reply.txt', 'reply_sha256'),
                          ('FILES.json', 'files_manifest_sha256'), ('compiler_input.json', 'compiler_input_sha256'),
                          ('compiler_return.json', 'compiler_receipt_sha256')]:
            self.assertEqual(worker.digest((root / 'attempt_1' / name).read_bytes()), attempt[key])
        for name, expected in attempt['all_public_files_sha256'].items():
            self.assertEqual(worker.digest((root / 'attempt_1/files' / name).read_bytes()), expected)
        self.assertEqual(result['actual_model_calls'], 0)
        self.assertEqual(result['actual_eda_calls'], 0)
        self.assertFalse(result['eligible_for_independent_models'])

    def assert_callback_mutation(self, actor, effect, raises=False):
        transport = fake_transport(effect=effect) if actor == 'transport' else fake_transport()
        compiler = fake_compiler(['failed'], effect=effect) if actor == 'compiler' else fake_compiler()
        result, root, transport, compiler = self.run_worker(transport=transport, compiler=compiler)
        self.assertEqual(result['status'], 'callback_input_mutated')
        self.assertTrue(result['callback_input_mutation_detected'])
        self.assertFalse(result['external_callback_fidelity_verified'])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(compiler.calls), 1 if actor == 'compiler' else 0)
        binding = result['attempts'][0][actor + '_callback_binding']
        before = root / 'attempt_1' / binding['before_snapshot']
        after = root / 'attempt_1' / binding['after_snapshot']
        self.assertEqual(worker.digest(before.read_bytes()), binding['before_canonical_sha256'])
        self.assertEqual(worker.digest(after.read_bytes()), binding['after_canonical_sha256'])
        self.assertNotEqual(before.read_bytes(), after.read_bytes())
        original_input = json.loads((root / 'attempt_1' / ('request.json' if actor == 'transport' else 'compiler_input.json')).read_bytes())
        self.assertEqual(worker.canonical_bytes(original_input), before.read_bytes())
        self.assertTrue((root / 'attempt_1' / (actor + '_return.json')).is_file())
        if raises:
            self.assertIn('FAKE mutated then raised', binding['callback_exception'])
        elif actor == 'transport':
            self.assertEqual((root / 'attempt_1/reply.txt').read_bytes(), reply().encode())
        else:
            self.assertTrue((root / 'attempt_1/FILES.json').is_file())
            self.assertEqual((root / 'attempt_1/files/rtl/helper.sv').read_bytes(), synthetic_record()['input']['context']['rtl/helper.sv'].encode())

    def test_transport_message_mutation_preserves_both_versions_and_reply(self):
        def mutate(request, timeout, number):
            request['messages'][0]['content'] = 'MUTATED MODEL SYSTEM MESSAGE'
        self.assert_callback_mutation('transport', mutate)

    def test_transport_token_budget_mutation_preserves_both_versions_and_stops(self):
        def mutate(request, timeout, number):
            request['max_tokens'] = 1
        self.assert_callback_mutation('transport', mutate)

    def test_compiler_candidate_file_argument_mutation_preserves_partial_evidence(self):
        def mutate(package, timeout, number):
            package['public_hdl']['rtl/native_main.sv']['path'] = 'MUTATED CANDIDATE PATH'
        self.assert_callback_mutation('compiler', mutate)

    def test_compiler_helper_context_argument_mutation_is_not_forwarded_to_repair(self):
        def mutate(package, timeout, number):
            package['public_hdl']['rtl/helper.sv']['sha256'] = 'MUTATED PUBLIC CONTEXT HASH'
        self.assert_callback_mutation('compiler', mutate)

    def test_transport_mutation_then_exception_is_detected_without_retry(self):
        def mutate(request, timeout, number):
            request['max_tokens'] = 1
            raise RuntimeError('FAKE mutated then raised')
        self.assert_callback_mutation('transport', mutate, raises=True)

    def test_compiler_mutation_then_exception_is_detected_without_retry(self):
        def mutate(package, timeout, number):
            package['public_hdl'].pop('rtl/helper.sv')
            raise RuntimeError('FAKE mutated then raised')
        self.assert_callback_mutation('compiler', mutate, raises=True)

    def test_deadline_exhausted_during_diagnostic_write_downgrades_fake_pass(self):
        original = worker.write_text_new
        def slow_diagnostics(path, content):
            returned = original(path, content)
            if Path(path).name == 'diagnostics.txt':
                self.clock.advance(301)
            return returned
        with mock.patch.object(worker, 'write_text_new', side_effect=slow_diagnostics):
            result, root, transport, compiler = self.run_worker()
        self.assertEqual(result['status'], 'solve_timeout')
        self.assertEqual(result['terminal_status_before_timeout'], 'fake_candidate_compile_pass')
        self.assertGreater(result['elapsed_s'], 300)
        self.assertTrue((root / 'attempt_1/compiler_return.json').is_file())
        self.assertTrue((root / 'attempt_1/diagnostics.txt').is_file())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(compiler.calls), 1)

    def test_deadline_exhausted_during_final_summary_downgrades_fake_pass(self):
        original = worker.save_json
        delayed = []
        def slow_final_summary(path, value):
            returned = original(path, value)
            if Path(path).name == 'summary.json' and value.get('complete') and not delayed:
                delayed.append(True)
                self.clock.advance(301)
            return returned
        with mock.patch.object(worker, 'save_json', side_effect=slow_final_summary):
            result, root, transport, _ = self.run_worker()
        self.assertEqual(result['status'], 'solve_timeout')
        self.assertEqual(result['terminal_status_before_timeout'], 'fake_candidate_compile_pass')
        self.assertGreater(result['elapsed_s'], 300)
        self.assertTrue((root / 'attempt_1/reply.txt').is_file())
        self.assertEqual(len(transport.calls), 1)


if __name__ == '__main__':
    unittest.main()
