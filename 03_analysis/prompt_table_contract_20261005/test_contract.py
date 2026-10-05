"""Pure input-path controls: synthetic and verbatim prompt text only, no oracle IO."""
import itertools
import unittest
from unittest.mock import patch

from contract import parse_prompt

PREAMBLE = '''I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

'''
MAP_STATEMENT = 'The module should implement the circuit described by the Karnaugh map\nbelow.\n\n'
WAVE_STATEMENT = 'The module can be described by the following simulation waveform:\n\n'
COMB_STATEMENT = ('The module should implement a combinational circuit. Read the simulation\n'
                  'waveforms to determine what the circuit does, then implement it.\n\n')


def scalar_prompt(names, output, statement, table):
    return (PREAMBLE + ''.join(' - input  ' + n + '\n' for n in names)
            + ' - output ' + output + '\n\n' + statement + table + '\n')


KMAP3 = scalar_prompt('abc', 'out', MAP_STATEMENT,
                     '          a\n   bc   0   1\n   00 | 0 | 1 |\n   01 | 1 | 1 |\n   11 | 1 | 1 |\n   10 | 1 | 1 |\n')
KMAP4 = scalar_prompt('abcd', 'out', MAP_STATEMENT,
                     '              ab\n   cd   00  01  11  10\n'
                     '   00 | 1 | 1 | 0 | 1 |\n   01 | 1 | 0 | 0 | 1 |\n'
                     '   11 | 0 | 1 | 1 | 1 |\n   10 | 1 | 1 | 0 | 0 |\n')
WAVE2 = scalar_prompt('xy', 'z', WAVE_STATEMENT,
                     '  time  x  y  z\n  0ns   0  0  1\n  5ns   1  0  0\n'
                     '  10ns  0  1  0\n  15ns  1  1  1\n  20ns  0  0  1\n')


def by_bits(result):
    return {tuple(sorted(row['input_bits'].items())): row['expected'] for row in result['contract']['rows']}


def map_fixture(input_order, col_axis='ab', row_axis='cd', columns=('00', '01', '11', '10'),
                rows=('00', '01', '11', '10')):
    lines = [col_axis, row_axis + ' ' + ' '.join(columns)]
    for row in rows:
        values = []
        for col in columns:
            bits = dict(zip(row_axis, map(int, row))) | dict(zip(col_axis, map(int, col)))
            values.append(str((bits['a'] & bits['c']) ^ bits['b'] ^ bits['d']))
        lines.append(row + ' | ' + ' | '.join(values) + ' |')
    return scalar_prompt(input_order, 'out', MAP_STATEMENT, '\n'.join(lines))


class CompleteTableControls(unittest.TestCase):
    def admitted(self, prompt):
        result = parse_prompt(prompt)
        self.assertTrue(result['admitted'], result)
        self.assertTrue(result['all_prompt_consumed'])
        self.assertEqual((result['model_calls'], result['eda_calls'], result['external_io_calls']), (0, 0, 0))
        return result

    def abstained(self, prompt, reason=None):
        result = parse_prompt(prompt)
        self.assertFalse(result['admitted'], result)
        self.assertFalse(result['all_prompt_consumed'])
        self.assertNotIn('contract', result)
        if reason:
            self.assertEqual(result['reason'], reason)
        return result

    def test_three_variable_cells_complete_and_counterexample(self):
        result = self.admitted(KMAP3)
        self.assertEqual(result['contract']['complete_assignment_count'], 8)
        for row in result['contract']['rows']:
            a, b, c = (row['inputs'][x] for x in 'abc')
            self.assertEqual(row['expected'], a | b | c)
        row = next(r for r in result['contract']['rows'] if r['inputs'] == {'a': 0, 'b': 0, 'c': 1})
        self.assertEqual(row['expected'], 1)
        self.assertEqual(row['source'], {'row_label': '01', 'column_label': '0'})

    def test_four_variable_gray_order_is_labels_not_numeric_position(self):
        result = self.admitted(KMAP4)
        self.assertEqual(result['contract']['column_labels_as_written'], ['00', '01', '11', '10'])
        self.assertEqual(result['contract']['complete_assignment_count'], 16)
        rows = {tuple(r['inputs'][k] for k in 'abcd'): r['expected'] for r in result['contract']['rows']}
        self.assertEqual(rows[(1, 1, 0, 0)], 0)
        self.assertEqual(rows[(1, 0, 0, 0)], 1)

    def test_input_declaration_permutations_preserve_labeled_function(self):
        expected = by_bits(self.admitted(map_fixture('abcd')))
        for order in itertools.permutations('abcd'):
            with self.subTest(order=order):
                self.assertEqual(by_bits(self.admitted(map_fixture(order))), expected)

    def test_row_and_column_permutations_preserve_every_assignment(self):
        expected = by_bits(self.admitted(map_fixture('abcd')))
        labels = ('00', '01', '11', '10')
        for columns in itertools.permutations(labels):
            for rows in itertools.permutations(labels):
                with self.subTest(columns=columns, rows=rows):
                    self.assertEqual(by_bits(self.admitted(map_fixture('abcd', columns=columns, rows=rows))), expected)

    def test_axis_variable_order_and_axis_exchange(self):
        expected = by_bits(self.admitted(map_fixture('abcd')))
        for col, row in [('ba', 'dc'), ('cd', 'ab'), ('ac', 'bd'), ('da', 'cb')]:
            with self.subTest(col=col, row=row):
                self.assertEqual(by_bits(self.admitted(map_fixture('abcd', col_axis=col, row_axis=row))), expected)

    def test_vector_bit_axes_preserve_declared_numeric_value(self):
        prompt = (PREAMBLE + ' - input x (4 bits)\n - output f\n\n'
                  + 'The module should implement the function f shown in the Karnaugh map\nbelow.\n\n'
                  + 'x[0]x[1]\nx[2]x[3] 00 01 11 10\n'
                  + '00 | 0 | 1 | 1 | 0 |\n01 | 0 | 1 | 1 | 0 |\n'
                  + '11 | 0 | 1 | 1 | 0 |\n10 | 0 | 1 | 1 | 0 |\n')
        result = self.admitted(prompt)
        self.assertEqual(result['contract']['input_bit_order'], ['x[3]', 'x[2]', 'x[1]', 'x[0]'])
        for row in result['contract']['rows']:
            self.assertEqual(row['expected'], (row['inputs']['x'] >> 1) & 1)

    def test_out_of_range_vector_axis_abstains_without_remapping(self):
        prompt = (PREAMBLE + ' - input x (4 bits)\n - output f\n\n'
                  + 'The module should implement the function f shown in the Karnaugh map\nbelow.\n\n'
                  + 'x[1]x[2]\nx[3]x[4] 00 01 11 10\n'
                  + '00 | 0 | 1 | 0 | 1 |\n01 | 0 | 1 | 0 | 1 |\n'
                  + '11 | 0 | 1 | 0 | 1 |\n10 | 0 | 1 | 0 | 1 |\n')
        self.abstained(prompt, 'axis_not_exact_declared_inputs')

    def test_dontcares_remain_unconstrained_not_zero(self):
        prompt = KMAP4.replace('below.', "below. d is don't-care, which means you may choose to output whatever\nvalue is convenient.")
        prompt = prompt.replace('00 | 1 | 1 | 0 | 1 |', '00 | d | 1 | 0 | 1 |')
        result = self.admitted(prompt)
        self.assertEqual(result['contract']['care_assignment_count'], 15)
        row = next(r for r in result['contract']['rows'] if not r['care'])
        self.assertIsNone(row['expected'])
        self.assertEqual(row['inputs'], dict.fromkeys('abcd', 0))

    def test_dontcare_requires_explicit_declaration(self):
        self.abstained(KMAP3.replace('00 | 0 | 1 |', '00 | d | 1 |'), 'undeclared_dontcare')

    def test_nonstandard_column_order_supported(self):
        result = self.admitted(map_fixture('abcd', columns=('01', '00', '10', '11')))
        self.assertEqual(result['contract']['column_labels_as_written'], ['01', '00', '10', '11'])

    def test_missing_or_duplicate_rows_abstain(self):
        self.abstained(KMAP3.replace('   10 | 1 | 1 |\n', ''), 'incomplete_kmap_rows')
        self.abstained(KMAP3.replace('   10 | 1 | 1 |', '   11 | 1 | 1 |'), 'invalid_or_duplicate_row_label')

    def test_missing_duplicate_or_wrong_width_columns_abstain(self):
        for replacement in ['00 01 11', '00 01 11 11', '00 01 11 1', '00 01 11 10 00']:
            with self.subTest(labels=replacement):
                self.abstained(KMAP4.replace('00  01  11  10', replacement), 'incomplete_or_duplicate_column_labels')

    def test_malformed_cells_axis_overlap_and_extra_body_abstain(self):
        for prompt in [KMAP3.replace('00 | 0 | 1 |', '00 | 0 | 1'),
                       KMAP3.replace('00 | 0 | 1 |', '00 | 0 | x |'),
                       KMAP3.replace('bc   0', 'ab   0'),
                       KMAP3 + '\nReset should be synchronous.\n',
                       KMAP3.replace('          a\n', 'Unexpected text\n          a\n')]:
            with self.subTest(prompt=prompt[-100:]):
                self.abstained(prompt)

    def test_every_prefix_suffix_semantic_clause_abstains(self):
        clauses = ['Assume all registers start at zero.', 'Invert the result when enabled.',
                   'This is a sequential circuit.', 'The output is registered.',
                   'Clock is omitted from the table.', 'Ignore the map above.']
        for clause in clauses:
            for prompt in [clause + '\n' + KMAP3, KMAP3 + '\n' + clause,
                           KMAP3.replace(MAP_STATEMENT, clause + '\n' + MAP_STATEMENT)]:
                with self.subTest(clause=clause):
                    self.abstained(prompt)

    def test_partial_output_or_multiple_outputs_abstain(self):
        self.abstained(KMAP3.replace('output out', 'output out (4 bits)'), 'requires_one_scalar_output')
        self.abstained(KMAP3.replace(' - output out', ' - output out\n - output other'), 'requires_one_scalar_output')
        self.abstained(KMAP3.replace(' - input  c', ' - input  c\n - input  unused'), 'axis_not_exact_declared_inputs')

    def test_port_width_and_duplicate_names_abstain(self):
        self.abstained(KMAP3.replace(' - input  a', ' - input  a\n - input  a'), 'missing_or_duplicate_ports')
        self.abstained(KMAP3.replace(' - input  a', ' - input  a (99 bits)'), 'input_width_out_of_scope')
        self.abstained(KMAP3.replace(' - input  a', ' - input  a (' + '9' * 5000 + ' bits)'), 'input_width_out_of_scope')

    def test_complete_repeated_waveform_derives_xnor(self):
        result = self.admitted(WAVE2)
        self.assertEqual(result['contract']['observation_count'], 5)
        self.assertEqual(result['contract']['complete_assignment_count'], 4)
        for row in result['contract']['rows']:
            self.assertEqual(row['expected'], int(row['inputs']['x'] == row['inputs']['y']))
        self.assertEqual(result['contract']['rows'][0]['source']['observation_lines'], [1, 5])

    def test_complete_explicit_combinational_four_input_waveform(self):
        lines = ['time a b c d q']
        for i, bits in enumerate(itertools.product((0, 1), repeat=4)):
            a, b, c, d = bits
            lines.append(f'{i * 5}ns ' + ' '.join(map(str, bits)) + ' ' + str((a | b) & (c | d)))
        result = self.admitted(scalar_prompt('abcd', 'q', COMB_STATEMENT, '\n'.join(lines)))
        self.assertEqual(result['contract']['care_assignment_count'], 16)

    def test_waveform_header_and_declaration_permutations(self):
        baseline = by_bits(self.admitted(WAVE2))
        prompt = scalar_prompt('yx', 'z', WAVE_STATEMENT,
                               'time z y x\n0ns 1 0 0\n5ns 0 0 1\n10ns 0 1 0\n15ns 1 1 1\n')
        self.assertEqual(by_bits(self.admitted(prompt)), baseline)

    def test_waveform_missing_combination_or_conflict_abstains(self):
        self.abstained(WAVE2.replace('  15ns  1  1  1\n', ''), 'incomplete_waveform_input_coverage')
        self.abstained(WAVE2.replace('20ns  0  0  1', '20ns  0  0  0'), 'conflicting_waveform_observations')

    def test_waveform_clock_reset_unknown_output_and_units_abstain(self):
        self.abstained(WAVE2.replace(' x', ' clk'), 'waveform_sequential_control')
        self.abstained(WAVE2.replace('input  y', 'input  reset')
                       .replace('time  x  y  z', 'time  x  reset  z'), 'waveform_sequential_control')
        self.abstained(WAVE2.replace('15ns  1  1  1', '15ns  1  1  x'), 'waveform_nonbinary_value')
        self.abstained(WAVE2.replace('20ns', '20ps'), 'waveform_time_order_or_units')
        self.abstained(WAVE2.replace('20ns', '15ns'), 'waveform_time_order_or_units')
        self.abstained(WAVE2.replace('time  x  y  z', 'time  x  x  z'), 'waveform_header_binding')

    def test_waveform_sequential_prose_or_partial_port_map_abstains(self):
        self.abstained(WAVE2.replace(WAVE_STATEMENT, 'The following sequential waveform specifies a register:\n'))
        self.abstained(WAVE2.replace(' - input  x', ' - input  extra\n - input  x'), 'waveform_header_binding')
        self.abstained(WAVE2 + '\nAssume q holds its previous value.\n')

    def test_whitespace_crlf_equivalent(self):
        baseline = by_bits(self.admitted(KMAP3))
        self.assertEqual(by_bits(self.admitted(KMAP3.replace('\n', '\r\n'))), baseline)
        self.assertEqual(by_bits(self.admitted(KMAP3.replace('   bc', '\tbc').replace(' | ', '\t|\t'))), baseline)

    def test_invalid_type_encoding_size_and_file_path_abstain(self):
        for prompt in [None, False, 1, {'prompt': KMAP3, 'oracle': 'forbidden'}, PathLikeDummy()]:
            self.abstained(prompt, 'prompt_must_be_string')
        for prompt in ['E:/fixture/prompt.txt', '\ud800', '\ufffd' + KMAP3, KMAP3 + '\0', ' ' * 65537]:
            self.abstained(prompt)

    def test_pure_input_path_never_opens_network_process_or_files(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')), \
             patch('builtins.open', side_effect=AssertionError('file input forbidden')):
            self.admitted(KMAP3)
            self.admitted(WAVE2)
            self.abstained('Read hidden ref.sv')


class PathLikeDummy:
    def __fspath__(self):
        raise AssertionError('filename inputs forbidden')


if __name__ == '__main__':
    unittest.main()
