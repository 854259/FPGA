"""Pure protocol/renderer controls; synthetic stdout is never native evidence."""
import hashlib
import itertools
import json
import re
import unittest
from unittest.mock import patch

from contract import parse_prompt
from render import render_tb, parse_observations, make_feedback

HEADER = '''I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

'''
PROMPT = (HEADER + ' - input a\n - input b\n - input c\n - output out\n\n'
          + 'The module should implement the circuit described by the Karnaugh map\nbelow.\n\n'
          + 'a\nbc 0 1\n00 | 0 | 1 |\n01 | 1 | 1 |\n11 | 1 | 1 |\n10 | 1 | 1 |\n')
VECTOR = (HEADER + ' - input x (4 bits)\n - output f\n\n'
          + 'The module should implement the function f shown in the Karnaugh map\nbelow.\n\n'
          + 'x[0]x[1]\nx[2]x[3] 00 01 11 10\n'
          + '00 | 0 | 1 | 1 | 0 |\n01 | 0 | 1 | 1 | 0 |\n'
          + '11 | 0 | 1 | 1 | 0 |\n10 | 0 | 1 | 1 | 0 |\n')
CASE = 'sample'


def binding(prompt, case=CASE):
    receipt = parse_prompt(prompt)
    assert receipt['admitted']
    contract_sha = hashlib.sha256(json.dumps(receipt['contract'], sort_keys=True,
                                            separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return f"TABLE_BINDING task={case} prompt_sha256={receipt['prompt_sha256']} contract_sha256={contract_sha}"


def synthetic_log(prompt=PROMPT, mismatch_rows=(), vector=False, dontcare=False, case=CASE):
    """Known synthetic OR3 or vector-bit1 table, independent of generated TB."""
    lines = ['xsim startup text', binding(prompt, case)]
    bits = [f'x[{i}]' for i in range(3, -1, -1)] if vector else list('abc')
    checks, mismatches = 0, 0
    for index, values in enumerate(itertools.product((0, 1), repeat=len(bits))):
        if dontcare and index == 0:
            continue
        expected = values[2] if vector else int(any(values))
        observed = expected ^ int(index in mismatch_rows)
        checks += 1
        mismatches += observed != expected
        inputs = ','.join(f'{name}={value}' for name, value in zip(bits, values))
        lines.append(f'TABLE_CARE task={case} row={index} inputs={inputs} expected={expected} observed={observed}')
    lines += [f'R2_PROBE_RESULT task={case} checks={checks} mismatches={mismatches}', '$finish called normally']
    return '\n'.join(lines) + '\n'


def dc_prompt():
    return PROMPT.replace('below.', "below. d is don't-care, which means you may choose to output whatever\nvalue is convenient.") \
        .replace('00 | 0 | 1 |', '00 | d | 1 |')


class NativeTableControls(unittest.TestCase):
    def invalid(self, log, prompt=PROMPT, reason=None):
        with self.assertRaises(ValueError) as error:
            parse_observations(prompt, CASE, log)
        if reason:
            self.assertEqual(str(error.exception), reason)
        for mode in ('first', 'full'):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    make_feedback(prompt, CASE, log, mode)

    def test_render_self_contained_tb_existing_topmodule_interface(self):
        tb = render_tb(PROMPT, CASE)
        self.assertTrue(tb.startswith('`timescale 1ns/1ps\nmodule R2Probe;'))
        self.assertIn('TopModule _pt_dut(.a(_pt_i0),.b(_pt_i1),.c(_pt_i2),.out(_pt_o));', tb)
        self.assertEqual(tb.count('$display("TABLE_CARE '), 8)
        self.assertIn('R2_PROBE_RESULT task=sample checks=%0d mismatches=%0d', tb)
        self.assertNotIn('R2_PROBE_SUMMARY', tb)
        self.assertNotIn('module TopModule', tb)
        self.assertNotIn('ref.sv', tb)
        self.assertIn('WATCHDOG_EXPIRED', tb)

    def test_dynamic_all_input_and_output_display_not_static_inputs(self):
        tb = render_tb(PROMPT, CASE)
        rows = [line for line in tb.splitlines() if line.startswith('$display("TABLE_CARE')]
        self.assertTrue(all('inputs=a=%b,b=%b,c=%b' in line and ',_pt_i0,_pt_i1,_pt_i2,_pt_o);' in line for line in rows))
        self.assertIn("_pt_i0=1'b0;\n_pt_i1=1'b0;\n_pt_i2=1'b1;\n#1;", tb)
        self.assertEqual(tb.count('_pt_checks=_pt_checks+1;'), 8)

    def test_vector_declaration_assignment_subscripts_and_all_bit_labels(self):
        tb = render_tb(VECTOR, CASE)
        self.assertIn('reg [3:0] _pt_i0;', tb)
        self.assertIn('.x(_pt_i0),.f(_pt_o)', tb)
        self.assertEqual(tb.count("_pt_i0[3]=1'b"), 16)
        self.assertEqual(tb.count("_pt_i0[0]=1'b"), 16)
        self.assertIn('inputs=x[3]=%b,x[2]=%b,x[1]=%b,x[0]=%b', tb)
        receipt = parse_observations(VECTOR, CASE, synthetic_log(VECTOR, vector=True))
        self.assertEqual(receipt['checks'], 16)
        self.assertEqual([r['inputs']['x'] for r in receipt['observations']], list(range(16)))
        self.invalid(synthetic_log(VECTOR, vector=True).replace('inputs=x[3]=', 'inputs=x[4]=', 1), VECTOR)

    def test_scalar_declaration_permutation_preserves_ports_and_bit_order(self):
        prompt = PROMPT.replace(' - input a\n - input b\n - input c', ' - input c\n - input a\n - input b')
        tb = render_tb(prompt, CASE)
        self.assertIn('.c(_pt_i0),.a(_pt_i1),.b(_pt_i2)', tb)
        self.assertIn('inputs=c=%b,a=%b,b=%b', tb)

    def test_dontcare_is_omitted_not_checked_as_zero(self):
        prompt = dc_prompt()
        tb = render_tb(prompt, CASE)
        self.assertEqual(tb.count('$display("TABLE_CARE '), 7)
        self.assertNotIn('task=sample row=0 ', tb)
        receipt = parse_observations(prompt, CASE, synthetic_log(prompt, dontcare=True))
        self.assertEqual(receipt['checks'], 7)
        self.assertEqual(receipt['observations'][0]['row'], 1)

    def test_all_dontcare_abstains_as_no_obligation(self):
        prompt = dc_prompt()
        prompt = re.sub(r'\| [01] ', '| d ', prompt)
        with self.assertRaisesRegex(ValueError, 'no_cared_obligations'):
            render_tb(prompt, CASE)

    def test_waveform_is_excluded_even_when_parser_admits(self):
        prompt = (HEADER + ' - input x\n - input y\n - output z\n\n'
                  + 'The module can be described by the following simulation waveform:\n\n'
                  + 'time x y z\n0ns 0 0 1\n5ns 0 1 0\n10ns 1 0 0\n15ns 1 1 1\n')
        self.assertTrue(parse_prompt(prompt)['admitted'])
        with self.assertRaisesRegex(ValueError, 'explicit_kmap_only'):
            render_tb(prompt, CASE)
        self.invalid(synthetic_log(), prompt, 'explicit_kmap_only')

    def test_invalid_case_label_and_partial_prompt_have_no_render(self):
        for case in ['', None, True, 'bad-name', 'bad"; $finish;', 'x' * 65]:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    render_tb(PROMPT, case)
        for prompt in [PROMPT + '\nOutput is registered.', PROMPT.replace('10 | 1 | 1 |\n', ''), {'prompt': PROMPT}]:
            with self.subTest(prompt=prompt):
                with self.assertRaises(ValueError):
                    render_tb(prompt, CASE)

    def test_complete_synthetic_passing_receipt_not_claimed_actual_execution(self):
        log = synthetic_log()
        receipt = parse_observations(PROMPT, CASE, log)
        self.assertEqual((receipt['status'], receipt['checks'], receipt['mismatches']), ('pass', 8, 0))
        self.assertTrue(receipt['evidence_complete'])
        self.assertFalse(receipt['actual_native_execution_confirmed_by_this_pure_function'])
        self.assertEqual(receipt['tb_sha256'], hashlib.sha256(render_tb(PROMPT, CASE).encode()).hexdigest())
        self.assertEqual(receipt['log_sha256'], hashlib.sha256(log.encode()).hexdigest())
        self.assertIsNone(make_feedback(PROMPT, CASE, log, 'first'))
        self.assertIsNone(make_feedback(PROMPT, CASE, log, 'full'))

    def test_same_complete_failure_first_vs_full_representation(self):
        log = synthetic_log(mismatch_rows=(1, 3))
        receipt = parse_observations(PROMPT, CASE, log)
        self.assertEqual((receipt['status'], receipt['checks'], receipt['mismatches']), ('fail', 8, 2))
        first = make_feedback(PROMPT, CASE, log, 'first')
        full = make_feedback(PROMPT, CASE, log, 'full')
        self.assertEqual(first.count('inputs='), 1)
        self.assertEqual(full.count('inputs='), 8)
        self.assertIn('inputs=a=0,b=0,c=1; output=out; expected=1; observed=0', first)
        self.assertEqual(full.count('; MISMATCH'), 2)
        self.assertEqual(full.count('; PASS'), 6)
        self.assertEqual(first.splitlines()[:2], full.splitlines()[:2])
        self.assertEqual(first.splitlines()[-1], full.splitlines()[-1])

    def test_first_feedback_still_requires_every_later_row(self):
        log = synthetic_log(mismatch_rows=(1,))
        log = '\n'.join(line for line in log.splitlines() if 'row=7 ' not in line)
        self.invalid(log, reason='missing_or_duplicate_protocol_rows')

    def test_first_valid_mismatch_does_not_mask_later_unknown_output(self):
        log = synthetic_log(mismatch_rows=(1,))
        self.invalid(log.replace('row=7 inputs=a=1,b=1,c=1 expected=1 observed=1',
                                 'row=7 inputs=a=1,b=1,c=1 expected=1 observed=x'),
                     reason='unknown_output_not_semantic_feedback')

    def test_missing_duplicate_extra_out_of_order_rows_reject(self):
        log = synthetic_log()
        lines = log.splitlines()
        care = [line for line in lines if line.startswith('TABLE_CARE')]
        cases = [log.replace(care[1] + '\n', ''), log + care[0] + '\n',
                 log.replace(care[1], care[0]), log.replace(care[1], 'TABLE_UNKNOWN unknown'),
                 log.replace(care[1], '__SWAP__').replace(care[2], care[1]).replace('__SWAP__', care[2])]
        for case in cases:
            with self.subTest(case=case[-120:]):
                self.invalid(case)

    def test_unknown_x_z_output_or_input_never_feedback(self):
        log = synthetic_log()
        for value in ['x', 'X', 'z', 'Z']:
            with self.subTest(value=value):
                self.invalid(log.replace('row=0 inputs=a=0,b=0,c=0 expected=0 observed=0',
                                         'row=0 inputs=a=0,b=0,c=0 expected=0 observed=' + value))
        self.invalid(log.replace('row=0 inputs=a=0', 'row=0 inputs=a=x'))

    def test_input_name_order_value_coverage_source_binding_reject(self):
        log = synthetic_log()
        for old, new in [('a=0,b=0,c=0', 'a=0,b=0,d=0'), ('a=0,b=0,c=0', 'b=0,a=0,c=0'),
                         ('a=0,b=0,c=0', 'a=0,b=0,c=1'), ('a=0,b=0,c=0', 'a=0,a=0,c=0'),
                         ('a=0,b=0,c=0', 'a=0,b=0'), ('a=0,b=0,c=0', 'a=0,b=0,c=0,d=0')]:
            with self.subTest(new=new):
                self.invalid(log.replace(old, new, 1))

    def test_expected_values_and_summary_recomputed_not_trusted(self):
        log = synthetic_log(mismatch_rows=(1,))
        for old, new in [('row=0 inputs=a=0,b=0,c=0 expected=0', 'row=0 inputs=a=0,b=0,c=0 expected=1'),
                         ('checks=8', 'checks=7'), ('mismatches=1', 'mismatches=0'),
                         ('mismatches=1', 'mismatches=9')]:
            with self.subTest(new=new):
                self.invalid(log.replace(old, new))

    def test_prompt_contract_case_hashes_bound_and_summary_unique(self):
        log = synthetic_log()
        for case in [log.replace('TABLE_BINDING task=sample', 'TABLE_BINDING task=other'),
                     log.replace('TABLE_CARE task=sample', 'TABLE_CARE task=other', 1),
                     log.replace('R2_PROBE_RESULT task=sample', 'R2_PROBE_RESULT task=other'),
                     log.replace(binding(PROMPT), binding(PROMPT).replace('prompt_sha256=', 'prompt_sha256=0')),
                     log.replace(binding(PROMPT), binding(PROMPT).replace('contract_sha256=', 'contract_sha256=0')),
                     log + 'R2_PROBE_RESULT task=sample checks=8 mismatches=0\n',
                     log.replace(binding(PROMPT), binding(PROMPT.replace('bc 0 1', 'bc   0   1')))]:
            with self.subTest(case=case[:150]):
                self.invalid(case)

    def test_valid_whole_log_noise_and_crlf(self):
        log = 'Vivado simulator banner\n' + synthetic_log() + 'Statistics text\n'
        self.assertEqual(parse_observations(PROMPT, CASE, log.replace('\n', '\r\n'))['checks'], 8)

    def test_invalid_log_type_length_controls_and_mode_fail(self):
        for log in [None, False, 'x' * 1048577, synthetic_log() + '\0', synthetic_log() + '\r']:
            with self.subTest(log_type=type(log).__name__):
                self.invalid(log)
        with self.assertRaisesRegex(ValueError, 'unsupported_feedback_mode'):
            make_feedback(PROMPT, CASE, synthetic_log(), 'concise')

    def test_pure_functions_do_not_run_tools_network_or_read_oracle(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')), \
             patch('builtins.open', side_effect=AssertionError('file IO forbidden')):
            render_tb(PROMPT, CASE)
            parse_observations(PROMPT, CASE, synthetic_log())
            make_feedback(PROMPT, CASE, synthetic_log(mismatch_rows=(1,)), 'full')


if __name__ == '__main__':
    unittest.main()
