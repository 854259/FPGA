"""Pure FAKE workflow controls only; no HTTP, model, native tool or cloud run."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import synthesis
def waveform():
    from native_material_fixture import fixture
    return fixture(pattern='101',cycles=2,module='SyntheticAdapter')[0]

spec = importlib.util.spec_from_file_location('table_worker_draft_controls', ROOT / 'worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8', newline='\n')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class FakePaired:
    """Writes explicitly synthetic physical-receipt fixtures, never executes argv."""
    def __init__(self):
        self.returncode = 0
        self.timeout = False
        self.launch_error = None
        self.remaining = []
        self.stdout = 'FAKE UNIT compile stdout\n'
        self.mutate_candidate = False
        self.mutate_input = None
        self.bad_log_hash = False
        self.commands = []
        self.gates = []

    def check_resource(self, resource, kit):
        self.gates.append((resource, kit))

    def owned_command(self, argv, cwd, log, seconds):
        self.commands.append((argv, cwd, seconds))
        Path(log).write_text(self.stdout, encoding='utf-8', newline='\n')
        if self.mutate_candidate:
            Path(argv[-1]).write_text('FAKE mutated candidate\n', encoding='utf-8')
        if self.mutate_input is not None:
            self.mutate_input.write_text('FAKE mutated input\n', encoding='utf-8')
        return dict(timeout=self.timeout, launch_error=self.launch_error,
                    returncode=self.returncode, remaining_live_group=self.remaining,
                    elapsed_s=.01, log=str(log),
                    log_sha256='0' * 64 if self.bad_log_hash else sha(log),
                    log_bytes=Path(log).stat().st_size,
                    fixture='FAKE_UNIT_NO_EDA_EXECUTION')


class WorkerControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fake-table-worker-')
        self.root = Path(self.temporary.name)
        self.kit = self.root / 'kit'
        self.task = 'FAKE_UNIT_TASK'
        self.source = self.kit / 'bench/tasks_veval' / self.task
        self.source.mkdir(parents=True)
        self.prompt = waveform()
        (self.source / 'prompt.txt').write_bytes(self.prompt.encode('utf-8'))
        self.owned = self.root / 'owned'
        self.owned.mkdir()
        # This fixture root intentionally is not a frozen or runnable source bundle.
        (self.owned / 'baseline_worker.py').write_text('FAKE unit source marker\n')
        (self.owned / 'synthesis.py').write_text('FAKE unit source marker\n')
        save(self.owned / 'RUN_SPEC.json', dict(dependencies_cloud=str(self.root / 'dependencies')))
        self.args = SimpleNamespace(arm='P', out=self.root / 'sample' / 'worker',
                                    kit=self.kit, task=self.task,
                                    resource_check=self.root / 'FAKE_resource.json')
        self.paired = FakePaired()
        self.fallback_calls = []
        self.feedback_calls = []
        self.feedback_text = ''
        self.fallback_request_count = 1
        self.fallback_mutates_source = False
        self.original_inputs = worker.raw_inputs(self.source)
        self.patches = [
            patch.object(worker, 'ROOT', self.owned),
            patch.object(worker.baseline, 'load', side_effect=self.fake_load),
            patch.object(worker.baseline, 'run_worker', side_effect=self.fake_baseline),
            patch.object(worker.baseline, 'functional_feedback', side_effect=self.fake_feedback),
            patch('urllib.request.urlopen', side_effect=AssertionError('Unit controls forbid HTTP')),
            patch('subprocess.run', side_effect=AssertionError('Unit controls forbid native execution')),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def fake_load(self, name, path):
        if Path(path).name == 'map_runtime.py':
            return SimpleNamespace(vivado_tool=lambda name: '/FAKE/vivado/xvlog')
        if Path(path).name == 'probe_runner.py':
            return SimpleNamespace(ENVIRONMENT_ERROR=re.compile('FAKE_ENVIRONMENT_BROKEN'))
        raise AssertionError('Unexpected dependency load in FAKE unit path')

    def fake_baseline(self, args, paired):
        self.fallback_calls.append((args.arm, args.out))
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
        (out / 'prompt_only').mkdir()
        for name, content in worker.raw_inputs(self.source).items():
            (out / 'prompt_only' / name).write_bytes(content)
        (out / 'solution.v').write_text('module TopModule; endmodule\n', encoding='utf-8')
        (out / 'trace.jsonl').write_text('', encoding='utf-8')
        # These are structural fake-baseline fixtures, not HTTP requests or eval evidence.
        journal = [dict(index=i, fixture='FAKE_UNIT_NO_HTTP_REQUEST')
                   for i in range(self.fallback_request_count)]
        save(out / 'requests.json', journal)
        save(out / 'worker_result.json',
             dict(complete=True, arm=args.arm, requests=len(journal),
                  actual_model_requests=len(journal), elapsed_s=.125,
                  solution_sha256=sha(out / 'solution.v'),
                  fixture='FAKE_UNIT_NOT_MODEL_EVIDENCE'))
        if self.fallback_mutates_source:
            (self.source / 'prompt.txt').write_text('FAKE tampered original')

    def fake_feedback(self, prompt, code, out, attempt, paired, task, candidate=False):
        self.feedback_calls.append(dict(prompt=prompt, code=code, out=out,
                                       attempt=attempt, task=task, candidate=candidate))
        return self.feedback_text

    def run_worker(self):
        worker.run_worker(self.args, self.paired)

    def test_exact_common_baseline_one_delta(self):
        original_path = ROOT / 'upstream' / 'worker.py'
        original = original_path.read_bytes()
        expected = original.replace(b"candidate=args.arm == 'P'", b'candidate=True')
        self.assertEqual(original.count(b"candidate=args.arm == 'P'"), 1)
        self.assertEqual((ROOT / 'baseline_worker.py').read_bytes(), expected)
        proof = read(ROOT / 'COPY_BASE_WORKER.json')
        self.assertEqual(proof['original_sha256'], sha(original_path))
        self.assertEqual(proof['copied_sha256'], sha(ROOT / 'baseline_worker.py'))
        self.assertEqual(proof['replacement_count'], 1)

    def test_generated_zero_without_HTTP_or_fallback(self):
        self.run_worker()
        out = self.args.out
        result = synthesis.synthesize(self.prompt)
        self.assertEqual(read(out / 'synthesis_receipt.json'), result)
        self.assertEqual((out / 'solution.v').read_bytes(), result['rtl'].encode())
        self.assertEqual(read(out / 'requests.json'), [])
        self.assertFalse((out / 'requests').exists())
        record = read(out / 'worker_result.json')
        self.assertEqual((record['requests'], record['actual_model_requests'],
                          record['received_model_responses']), (0, 0, 0))
        self.assertEqual(record['generation_route'], 'mechanical_serial_timer')
        self.assertEqual(self.fallback_calls, [])
        self.assertEqual(self.paired.commands[0][2], 60)
        self.assertEqual(self.paired.commands[0][0][1], '--sv')
        self.assertEqual(Path(self.paired.commands[0][0][-1]).parent.name, 'mechanical_compile-0')
        events = [json.loads(line) for line in (out / 'trace.jsonl').read_text().splitlines()]
        self.assertEqual([e['tool'] for e in events],
                         ['serial_timer_generation', 'lint_start', 'lint', 'native_feedback'])
        self.assertTrue(all(e['round'] == 0 for e in events))
        self.assertEqual(worker.raw_inputs(self.source), self.original_inputs)

    def test_control_uses_original_actual_arm_without_synthesis(self):
        self.args.arm = 'C'
        with patch.object(worker.synthesis, 'synthesize', side_effect=AssertionError('C must not synthesize')):
            self.run_worker()
        self.assertEqual(self.fallback_calls, [('C', self.args.out)])
        self.assertEqual(read(self.args.out / 'generation_route.json')['outer_arm'], 'C')
        self.assertFalse((self.args.out / 'synthesis_receipt.json').exists())
        self.assertEqual(read(self.args.out / 'worker_result.json')['elapsed_s'], .125)

    def test_abstained_candidate_uses_same_baseline_and_preserves_arm(self):
        prompt = 'Unsupported FAKE plain text prompt\n'
        (self.source / 'prompt.txt').write_bytes(prompt.encode())
        self.run_worker()
        self.assertEqual(self.fallback_calls, [('P', self.args.out)])
        self.assertEqual(read(self.args.out / 'synthesis_receipt.json'), synthesis.synthesize(prompt))
        self.assertEqual(read(self.args.out / 'generation_route.json')['route'], 'model')
        self.assertEqual(read(self.args.out / 'worker_result.json')['actual_model_requests'], 1)
        self.assertFalse((self.args.out / 'native_receipts').exists())

    def test_nonempty_interface_abstains_and_raw_CRLF_is_bound(self):
        prompt = self.prompt.replace('\n', '\r\n')
        interface = 'input q;\r\noutput x;\r\n'
        (self.source / 'prompt.txt').write_bytes(prompt.encode())
        (self.source / 'interface.txt').write_bytes(interface.encode())
        self.run_worker()
        receipt = read(self.args.out / 'synthesis_receipt.json')
        self.assertEqual(receipt, synthesis.synthesize(prompt, interface))
        self.assertFalse(receipt['emitted'])
        self.assertEqual(read(self.args.out / 'generation_route.json')['prompt_sha256'],
                         hashlib.sha256(prompt.encode()).hexdigest())
        self.assertEqual((self.args.out / 'prompt_only/interface.txt').read_bytes(), interface.encode())

    def test_normal_compile_failure_keeps_candidate_without_second_pipeline(self):
        self.paired.returncode = 1
        self.paired.stdout = 'ERROR: FAKE normal compile failure\n'
        self.run_worker()
        self.assertEqual(self.fallback_calls, [])
        self.assertEqual(self.feedback_calls, [])
        self.assertEqual(read(self.args.out / 'native_feedback.json')['native_compile_returncode'], 1)
        self.assertEqual(read(self.args.out / 'worker_result.json')['generation_route'], 'mechanical_serial_timer')
        self.assertEqual((self.args.out / 'solution.v').read_bytes(),
                         synthesis.synthesize(self.prompt)['rtl'].encode())

    def test_native_semantic_mismatch_is_retained_without_repair(self):
        self.feedback_text = 'FAKE UNIT native semantic counterexample'
        self.run_worker()
        self.assertEqual(len(self.feedback_calls), 1)
        self.assertTrue(self.feedback_calls[0]['candidate'])
        self.assertEqual(self.feedback_calls[0]['attempt'], 0)
        self.assertEqual(read(self.args.out / 'native_feedback.json')['text'], self.feedback_text)
        self.assertFalse(read(self.args.out / 'native_feedback.json')['repair_requested'])
        self.assertEqual(self.fallback_calls, [])
        self.assertEqual((self.args.out / 'solution.v').read_bytes(),
                         synthesis.synthesize(self.prompt)['rtl'].encode())

    def test_supervision_failures_raise_and_do_not_claim_completed(self):
        for attribute, value in [('timeout', True), ('launch_error', 'FAKE launch failure'),
                                 ('remaining', [999999])]:
            with self.subTest(attribute=attribute):
                self.args.out = self.root / attribute / 'worker'
                pair = FakePaired()
                setattr(pair, attribute, value)
                with self.assertRaisesRegex(RuntimeError, 'supervision failure'):
                    worker.run_worker(self.args, pair)
                self.assertFalse((self.args.out / 'worker_result.json').exists())
                self.assertTrue((self.args.out / 'native_receipts/0/command.json').exists())
                self.assertEqual(self.fallback_calls, [])

    def test_negative_signal_return_is_not_normal_compile_failure(self):
        self.paired.returncode = -9
        with self.assertRaisesRegex(RuntimeError, 'abnormal return'):
            self.run_worker()
        self.assertFalse((self.args.out / 'worker_result.json').exists())

    def test_native_log_hash_cannot_be_forged(self):
        self.paired.bad_log_hash = True
        with self.assertRaises(AssertionError):
            self.run_worker()
        self.assertTrue((self.args.out / 'native_receipts/0/command.json').exists())
        self.assertFalse((self.args.out / 'worker_result.json').exists())

    def test_native_source_mutation_retains_before_after_and_rejects(self):
        self.paired.mutate_candidate = True
        with self.assertRaises(AssertionError):
            self.run_worker()
        evidence = self.args.out / 'native_receipts/0'
        self.assertNotEqual((evidence / 'source_before.sv').read_bytes(),
                            (evidence / 'source_after.sv').read_bytes())
        self.assertFalse((self.args.out / 'worker_result.json').exists())

    def test_environment_fault_is_not_efficiency_or_score_gain(self):
        self.paired.stdout = 'FAKE_ENVIRONMENT_BROKEN\n'
        with self.assertRaisesRegex(RuntimeError, 'environment failure'):
            self.run_worker()
        self.assertFalse((self.args.out / 'worker_result.json').exists())
        self.assertEqual(self.fallback_calls, [])

    def test_original_input_mutation_is_rejected_after_both_routes(self):
        self.paired.mutate_input = self.source / 'prompt.txt'
        with self.assertRaisesRegex(AssertionError, 'Original prompt/interface changed'):
            self.run_worker()
        self.assertFalse((self.args.out / 'worker_result.json').exists())
        self.args.out = self.root / 'control_mutation' / 'worker'
        self.args.arm = 'C'
        self.fallback_mutates_source = True
        with self.assertRaisesRegex(AssertionError, 'Original prompt/interface changed'):
            self.run_worker()
        self.assertFalse((self.args.out / 'generation_route.json').exists())

    def test_model_route_zero_journal_is_rejected(self):
        self.args.arm = 'C'
        self.fallback_request_count = 0
        with self.assertRaises(AssertionError):
            self.run_worker()
        self.assertFalse((self.args.out / 'generation_route.json').exists())

    def test_missing_freeze_spec_cannot_pass_CLI_gate(self):
        missing = self.root / 'no_frozen_spec'
        missing.mkdir()
        with patch.object(worker, 'ROOT', missing):
            with self.assertRaises(FileNotFoundError):
                worker.frozen()


    def test_matching_interface_and_CRLF_emit_zero_request(self):
        from native_material_fixture import fixture
        prompt,interface,_=fixture(pattern='101',cycles=2,module='SyntheticAdapter')
        prompt=prompt.replace('\n','\r\n');interface=interface.replace('\n','\r\n')
        (self.source/'prompt.txt').write_bytes(prompt.encode())
        (self.source/'interface.txt').write_bytes(interface.encode())
        self.run_worker()
        receipt=read(self.args.out/'synthesis_receipt.json')
        self.assertTrue(receipt['emitted'])
        self.assertTrue(receipt['contract']['all_prompt_consumed'])
        self.assertEqual(self.fallback_calls,[])
        self.assertEqual(read(self.args.out/'requests.json'),[])
        self.assertEqual((self.args.out/'prompt_only/interface.txt').read_bytes(),interface.encode())
        self.assertEqual(self.feedback_calls[0]['prompt'],prompt.replace('\r\n','\n')+'\n\nInterface:\n'+interface.replace('\r\n','\n'))

    def test_preparation_binding_and_original_fallback_source_proof(self):
        import factor_proof
        proof=factor_proof.verify(ROOT)
        self.assertTrue(proof['prompt_only_algorithm'])
        self.assertFalse(proof['new_execution_or_quality_proved'])
        self.assertFalse(proof['native_qualification_bound'])
        self.assertEqual(proof['maximum_model_requests_per_sample'],2)
        self.assertEqual(proof['model_output_token_budget'],8192)
        self.assertEqual(proof['absolute_solver_deadline_s'],300)



    def test_overlong_decimal_abstains_to_original_one_and_two_request_fallback(self):
        from native_material_fixture import fixture
        prompt=fixture(cycles='0'*4300+'1')[0]
        self.assertLess(len(prompt),20000)
        (self.source/'prompt.txt').write_bytes(prompt.encode())
        for count in (1,2):
            self.args.out=self.root/('decimal_'+str(count))/'worker'
            self.fallback_request_count=count
            self.run_worker()
            self.assertFalse(read(self.args.out/'synthesis_receipt.json')['emitted'])
            self.assertEqual(read(self.args.out/'worker_result.json')['actual_model_requests'],count)
            self.assertEqual(self.feedback_calls,[])
            self.assertEqual(self.paired.commands,[])

    def test_forged_emission_hash_or_contract_is_rejected_before_output(self):
        original=synthesis.synthesize(self.prompt)
        for key in ('rtl_sha256','contract_sha256'):
            self.args.out=self.root/key/'worker'
            changed=dict(original);changed[key]='0'*64
            with patch.object(worker.synthesis,'synthesize',return_value=changed):
                with self.assertRaises(AssertionError):self.run_worker()
            self.assertFalse(self.args.out.exists())
            self.assertEqual(self.fallback_calls,[])

    def test_pending_native_qualification_cannot_pass_actual_CLI_freeze(self):
        import factor_proof
        with self.assertRaises(FileNotFoundError):factor_proof.verify(ROOT,require_native=True)
        temporary=self.root/'cli_freeze';temporary.mkdir()
        save(temporary/'RUN_SPEC.json',dict(source_hashes={},dependency_hashes={},dependencies_cloud=str(self.root)))
        with patch.object(worker,'ROOT',temporary),patch.object(factor_proof,'verify',side_effect=FileNotFoundError('native107 qualification pending')) as check:
            with self.assertRaises(FileNotFoundError):worker.frozen()
        check.assert_called_once_with(temporary,require_native=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
