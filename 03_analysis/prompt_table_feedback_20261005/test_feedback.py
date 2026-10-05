"""FAKE native callback boundaries; never a real tool/model/calibration proof."""
import hashlib
import itertools
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import contract
import feedback

HEADER = ('I would like you to implement a module named TopModule with the following\n'
          'interface. All input and output ports are one bit unless otherwise\n'
          'specified.\n\n')
PROMPT = (HEADER + ' - input a\n - input b\n - input c\n - output out\n\n'
          + 'The module should implement the circuit described by the Karnaugh map\nbelow.\n\n'
          + 'a\nbc 0 1\n00 | 0 | 1 |\n01 | 1 | 1 |\n11 | 1 | 1 |\n10 | 1 | 1 |\n')
CODE = 'module TopModule(input a,b,c,output out); assign out=a|b|c; endmodule\n'


def synthetic_log(prompt, case, wrong=()):
    """Independent OR3 observations; the expected function is a test fixture."""
    parsed = contract.parse_prompt(prompt)
    digest = hashlib.sha256(json.dumps(parsed['contract'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    rows = [f"TABLE_BINDING task={case} prompt_sha256={parsed['prompt_sha256']} contract_sha256={digest}"]
    count = 0
    for index, values in enumerate(itertools.product((0, 1), repeat=3)):
        if parsed['contract']['rows'][index]['care'] is False:
            continue
        expected = int(any(values))
        observed = expected ^ int(index in wrong)
        inputs = ','.join(f'{name}={value}' for name, value in zip('abc', values))
        rows.append(f'TABLE_CARE task={case} row={index} inputs={inputs} expected={expected} observed={observed}')
        count += 1
    rows.append(f'R2_PROBE_RESULT task={case} checks={count} mismatches={len(wrong)}')
    return '\n'.join(rows) + '\n'


class CallbackFixture:
    def __init__(self, root, wrong=(), corrupt=None, advances=0):
        self.out = root / 'sample'; self.out.mkdir()
        tool_dir = root / 'tools'; tool_dir.mkdir()
        self.tools = {}
        for name in ('xvlog', 'xelab', 'xsim'):
            path = tool_dir / name; path.write_bytes(b'FAKE tool file: never executed\n')
            self.tools[name] = path
        self.calls = []; self.wrong = wrong; self.corrupt = corrupt
        self.clock = 100.0; self.advances = advances

    def native(self, argv, cwd, log, seconds):
        name = Path(argv[0]).name
        self.calls.append((name, list(argv), str(cwd), str(log), seconds))
        raw = b'FAKE synthetic normal compiler completion\n'
        if name == 'xsim':
            tb = (cwd / 'tb.sv').read_text()
            case = re.search(r'TABLE_BINDING task=(\S+) prompt_sha256=', tb)[1]
            prompt = (cwd / 'prompt.txt').read_text()
            raw = synthetic_log(prompt, case, self.wrong).encode()
        log.write_bytes(raw)
        receipt = dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[],
                       group_signals=[], elapsed_s=0.0, log=str(log),
                       log_sha256=hashlib.sha256(raw).hexdigest(), log_bytes=len(raw))
        if self.corrupt:
            self.corrupt(name, argv, cwd, log, receipt)
        self.clock += self.advances
        return receipt

    def run(self, prompt=PROMPT, code=CODE, deadline=250.0, attempt=0):
        with patch.object(feedback.time, 'monotonic', lambda: self.clock):
            return feedback.check(prompt, code, self.out, attempt, self.native, self.tools, deadline)

    def receipt(self, attempt=0):
        return json.loads((self.out / f'prompt_table_check_{attempt}' / 'RESULTS.json').read_bytes())


class NativeBoundaryTests(unittest.TestCase):
    def fixture(self, **kwargs):
        temporary = tempfile.TemporaryDirectory(prefix='fake-kmap-boundary-')
        self.addCleanup(temporary.cleanup)
        return CallbackFixture(Path(temporary.name).absolute(), **kwargs)

    def rejects(self, fixture):
        with self.assertRaises(RuntimeError):
            fixture.run()
        receipt = fixture.receipt()
        self.assertFalse(receipt['measurement_valid'])
        self.assertEqual(receipt['outcome'], 'measurement_error')
        self.assertEqual(receipt['feedback'], '')
        return receipt

    def test_sealed_local_bytes_unchanged(self):
        hashes = feedback.implementation_hashes()
        for name, digest in feedback.SEALED.items(): self.assertEqual(hashes[name], digest)

    def test_fake_complete_pass_returns_no_feedback_and_binds_all_three_tools(self):
        fixture = self.fixture()
        self.assertEqual(fixture.run(), '')
        receipt = fixture.receipt()
        self.assertEqual(receipt['outcome'], 'pass')
        self.assertTrue(receipt['measurement_valid'])  # Only validity of this FAKE callback contract.
        self.assertEqual(receipt['parsed']['checks'], 8)
        self.assertEqual([call[0] for call in fixture.calls], ['xvlog', 'xelab', 'xsim'])
        self.assertTrue(receipt['source_unchanged'] and receipt['tools_unchanged'])
        self.assertFalse(receipt['parsed']['actual_native_execution_confirmed_by_this_pure_function'])
        self.assertEqual(fixture.calls[0][1][1:], ['-sv', '--nolog', 'candidate.sv', 'tb.sv'])
        self.assertEqual(fixture.calls[1][1][1:], ['R2Probe', '-s', receipt['snapshot'], '--nolog', '-timescale', '1ns/1ps'])
        self.assertEqual(fixture.calls[2][1][1:], [receipt['snapshot'], '-runall', '-nolog'])
        self.assertNotIn('Prob', receipt['case_id'])

    def test_fake_mismatch_feedback_includes_all_passing_and_failing_care_rows(self):
        fixture = self.fixture(wrong=(0, 7))
        text = fixture.run()
        self.assertIn('checks=8, mismatches=2', text)
        self.assertEqual(text.count('inputs='), 8)
        self.assertEqual(text.count('; MISMATCH'), 2)
        self.assertEqual(text.count('; PASS'), 6)
        self.assertEqual(fixture.receipt()['outcome'], 'fail')
        self.assertEqual(len(fixture.calls), 3)

    def test_dontcare_has_no_observation_or_obligation(self):
        prompt = PROMPT.replace('below.', "below. d is don't-care, which means you may choose to output whatever\nvalue is convenient.").replace('00 | 0 | 1 |', '00 | d | 1 |')
        fixture = self.fixture(wrong=(7,))
        text = fixture.run(prompt=prompt)
        self.assertIn('checks=7, mismatches=1', text)
        self.assertEqual(text.count('inputs='), 7)
        self.assertNotIn('inputs=a=0,b=0,c=0;', text)

    def test_unsupported_or_unconsumed_prompt_abstains_without_files_or_callback(self):
        for prompt in ('unsupported', PROMPT + '\nAn extra unconsumed requirement.'):
            with self.subTest(prompt=prompt):
                fixture = self.fixture()
                self.assertEqual(fixture.run(prompt=prompt), '')
                self.assertEqual(fixture.calls, [])
                self.assertEqual(list(fixture.out.iterdir()), [])

    def test_complete_waveform_abstains_from_kmap_helper(self):
        prompt = HEADER + ' - input a\n - output out\n\nThe module can be described by the following simulation waveform:\ntime a out\n0ns 0 0\n1ns 1 1\n'
        self.assertTrue(contract.parse_prompt(prompt)['admitted'])
        fixture = self.fixture()
        self.assertEqual(fixture.run(prompt=prompt), '')
        self.assertEqual(fixture.calls, [])

    def test_no_cared_obligations_rejected_before_native(self):
        prompt = PROMPT.replace('below.', "below. d is don't-care, which means you may choose to output whatever\nvalue is convenient.")
        prompt = re.sub(r'\| [01] \|', '| d |', prompt)
        prompt = prompt.replace('| 1 |', '| d |')
        fixture = self.fixture()
        with self.assertRaises(ValueError): fixture.run(prompt=prompt)
        self.assertEqual(fixture.calls, [])

    def test_candidate_protocol_or_file_access_cannot_be_simulated(self):
        for body in ('$display("TABLE_BINDING");', '$readmemh("x", mem);', '`include "x"'):
            fixture = self.fixture()
            with self.assertRaises(ValueError): fixture.run(code=CODE + body)
            self.assertEqual(fixture.calls, [])

    def test_uses_only_the_original_shrinking_budget(self):
        fixture = self.fixture(advances=20)
        self.assertEqual(fixture.run(deadline=165), '')
        self.assertEqual([call[-1] for call in fixture.calls], [60, 45, 25])
        self.assertEqual(fixture.receipt()['deadline_monotonic'], 165)

    def test_budget_exhaustion_stops_before_next_tool_and_never_returns_feedback(self):
        fixture = self.fixture(advances=70)
        with self.assertRaises(RuntimeError): fixture.run(deadline=160)
        self.assertEqual(len(fixture.calls), 1)
        self.assertFalse(fixture.receipt()['measurement_valid'])
        self.assertEqual(fixture.receipt()['feedback'], '')

    def test_unknown_nonzero_timeout_launch_cleanup_receipts_are_not_semantics(self):
        variants = [('returncode', None), ('returncode', True), ('returncode', -9), ('returncode', 1),
                    ('timeout', True), ('timeout', None), ('launch_error', 'failed'), ('remaining_live_group', [123])]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                fixture = self.fixture(corrupt=lambda n,a,c,l,r: r.update({key:value}))
                self.rejects(fixture)
                self.assertEqual(len(fixture.calls), 1)

    def test_missing_receipt_field_log_hash_bytes_or_path_are_not_semantics(self):
        corruptions = [lambda r: r.pop('timeout'), lambda r:r.update(log_sha256='0'*64),
                       lambda r:r.update(log_bytes=True), lambda r:r.update(log_bytes=r['log_bytes']+1),
                       lambda r:r.update(log='wrong/path')]
        for corruption in corruptions:
            fixture = self.fixture(corrupt=lambda n,a,c,l,r: corruption(r))
            self.rejects(fixture)

    def test_missing_log_and_native_exception_leave_attempted_failure_receipt(self):
        for mode in ('missing', 'exception'):
            def corrupt(n,a,c,l,r):
                if mode == 'missing': l.unlink()
                else: raise OSError('FAKE native callback interruption')
            fixture = self.fixture(corrupt=corrupt)
            receipt = self.rejects(fixture)
            self.assertTrue(receipt['native_commands'][0]['attempted'])
            self.assertFalse(receipt['native_commands'][0]['confirmed'])

    def test_native_argv_mutation_rejected(self):
        fixture = self.fixture(corrupt=lambda n,a,c,l,r: a.append('--changed'))
        self.rejects(fixture)

    def test_candidate_prompt_tb_or_tool_mutation_rejected(self):
        for name in ('candidate.sv', 'prompt.txt', 'tb.sv', 'tool'):
            def corrupt(n,a,c,l,r):
                path = Path(a[0]) if name == 'tool' else c/name
                path.write_bytes(path.read_bytes() + b'CHANGED')
            fixture = self.fixture(corrupt=corrupt)
            self.rejects(fixture)

    def test_zero_rc_error_or_environment_log_still_rejected(self):
        for text in ('ERROR: candidate error', 'FATAL_ERROR: failure', 'license checkout failed'):
            def corrupt(n,a,c,l,r):
                raw = text.encode(); l.write_bytes(raw)
                r.update(log_sha256=hashlib.sha256(raw).hexdigest(),log_bytes=len(raw))
            fixture = self.fixture(corrupt=corrupt)
            self.rejects(fixture)

    def test_zero_rc_complete_pass_protocol_followed_by_fatal_is_never_pass(self):
        for text in ('Fatal: synthetic sentinel', 'ERROR: synthetic sentinel', 'FATAL_ERROR: synthetic sentinel'):
            def corrupt(n,a,c,l,r):
                if n == 'xsim':
                    raw = l.read_bytes() + (text+'\n').encode()
                    l.write_bytes(raw)
                    r.update(log_sha256=hashlib.sha256(raw).hexdigest(),log_bytes=len(raw))
            fixture = self.fixture(corrupt=corrupt)
            receipt = self.rejects(fixture)
            self.assertEqual(len(fixture.calls), 3)
            self.assertEqual(receipt['native_commands'][-1]['native_command']['returncode'], 0)
            self.assertIn('checks=8 mismatches=0', (fixture.out/'prompt_table_check_0'/'xsim.log').read_text())
            self.assertIsNone(receipt['parsed'])

    def test_complete_summary_does_not_hide_invalid_protocol(self):
        changes = [lambda s: s.replace(' observed=0', ' observed=x', 1),
                   lambda s: s.replace(' prompt_sha256=', ' prompt_sha256=0', 1),
                   lambda s: '\n'.join(line for line in s.splitlines() if ' row=3 ' not in line),
                   lambda s: s+s.splitlines()[1]+'\n',
                   lambda s: s.replace('checks=8 mismatches=0', 'checks=8 mismatches=1')]
        for change in changes:
            def corrupt(n,a,c,l,r):
                if n == 'xsim':
                    raw = change(l.read_text()).encode(); l.write_bytes(raw)
                    r.update(log_sha256=hashlib.sha256(raw).hexdigest(),log_bytes=len(raw))
            fixture = self.fixture(corrupt=corrupt)
            self.rejects(fixture)
            self.assertEqual(len(fixture.calls), 3)

    def test_existing_attempt_directory_is_not_replayed_or_overwritten(self):
        fixture = self.fixture(); fixture.run()
        before = (fixture.out/'prompt_table_check_0'/'RESULTS.json').read_bytes()
        with self.assertRaises(FileExistsError): fixture.run()
        self.assertEqual(len(fixture.calls), 3)
        self.assertEqual((fixture.out/'prompt_table_check_0'/'RESULTS.json').read_bytes(), before)

    def test_absolute_paths_and_original_round_budget_required(self):
        fixture = self.fixture()
        with self.assertRaises(ValueError): fixture.run(attempt=2)
        with self.assertRaises(ValueError): fixture.run(deadline=100)
        with self.assertRaises(ValueError): fixture.run(deadline=float('nan'))
        with self.assertRaises(ValueError): fixture.run(deadline=401)
        with self.assertRaises(ValueError): feedback.no_links(Path('relative'))
        self.assertEqual(fixture.calls, [])


if __name__ == '__main__':
    unittest.main()
