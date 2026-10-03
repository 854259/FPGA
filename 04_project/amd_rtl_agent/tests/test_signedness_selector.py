"""Synthetic, task-independent adversarial examples for the offline selector."""
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    'signedness_selector', Path(__file__).resolve().parents[1] / 'bench/signedness_selector.py')
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)
PROMPT = ('Implement an arithmetic shift register with synchronous load. '
          'The right shift is an arithmetic right shift. Output result contains the register.')


def circuit(width=12, name='state', sign='', rhs=None, direct=False):
    rhs = rhs or f'{name} >>> 3'
    port = f'output reg {sign} [{width - 1}:0] {name}' if direct else f'output [{width - 1}:0] result'
    declaration = '' if direct else f'reg {sign} [{width - 1}:0] {name};'
    connection = '' if direct else f'assign result = {name};'
    return f'''module Example(input clk, input load, input [{width - 1}:0] data, {port});
{declaration}
always @(posedge clk) begin
    if(load) {name} <= data;
    else {name} <= {rhs};
end
{connection}
endmodule
'''


class SignednessSelectorTests(unittest.TestCase):
    def check(self, code, expected, prompt=PROMPT):
        result = selector.analyze(prompt, code)
        self.assertEqual(result['decision'], expected, result)
        self.assertEqual(set(result), {'decision', 'reasons', 'findings'})
        self.assertTrue(result['reasons'])
        return result

    def test_bare_unsigned_self_shift_selects_arbitrary_names_widths(self):
        for width, name in [(5, 'acc'), (19, 'X23'), (131, 'buffer_data')]:
            with self.subTest(width=width, name=name):
                result = self.check(circuit(width, name), 'review')
                self.assertEqual(result['findings'][0]['width'], width)
                self.assertEqual(result['findings'][0]['operand'], name)

    def test_unsigned_keyword_and_direct_output(self):
        self.check(circuit(sign='unsigned'), 'review')
        self.check(circuit(name='result', direct=True), 'review')

    def test_standard_interface_preamble_does_not_negate_arithmetic_requirement(self):
        self.check(circuit(), 'review', 'All ports are one bit unless otherwise specified. ' + PROMPT)
        self.check(circuit(), 'review', 'All ports are one bit unless otherwise\nspecified. ' + PROMPT)
        self.check(circuit(), 'abstain', PROMPT + ' Right shift is arithmetic unless otherwise specified.')

    def test_parentheses_around_whole_rhs_are_supported(self):
        self.check(circuit(rhs='((state >>> 3))'), 'review')

    def test_already_signed_declaration_skips(self):
        self.check(circuit(sign='signed'), 'skip')
        self.check(circuit(name='result', sign='signed', direct=True), 'skip')

    def test_explicit_signed_cast_skips(self):
        for rhs in ['$signed(state) >>> 3', "signed'(state) >>> 3"]:
            with self.subTest(rhs=rhs):
                self.check(circuit(rhs=rhs), 'skip')

    def test_zero_shift_has_no_demonstrated_sign_fill_risk(self):
        self.check(circuit(rhs='state >>> 0'), 'skip')

    def test_no_triple_shift_including_sign_fill_concat_skips(self):
        for rhs in ['state >> 3', '{{3{state[11]}}, state[11:3]}', 'data']:
            with self.subTest(rhs=rhs):
                self.check(circuit(rhs=rhs), 'skip')

    def test_comment_string_fake_operator_is_ignored(self):
        code = circuit(rhs='state >> 3')
        for fake in ['// state >>> 3\n', '/* state >>> 3 */',
                     'initial $display("/* >>> \\\" still string //");']:
            with self.subTest(fake=fake):
                self.check(code.replace('endmodule', fake + '\nendmodule'), 'skip')

    def test_comment_between_real_tokens_and_line_reporting(self):
        result = self.check(circuit(rhs='state /* ignore >>> other */ >>> 3'), 'review')
        self.assertEqual(result['findings'][0]['line'], 5)

    def test_negation_mixed_context_and_conditional_semantics_abstain(self):
        phrases = ['Do not use arithmetic right shift.', 'This is not arithmetic right shift.',
                   'Use logical right shift in the other mode.',
                   'Zero fill in one mode.', 'Use it except when load is clear.',
                   "The term arithmetic doesn't require sign extension.",
                   'An independent internal register uses another convention.',
                   'However, the next operation differs.', 'An arithmetic mode is optional.']
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.check(circuit(), 'abstain', PROMPT + ' ' + phrase)

    def test_keyword_without_shift_register_contract_abstains(self):
        self.check(circuit(), 'abstain', 'Arithmetic right shift exists in Verilog.')
        self.check(circuit(), 'abstain', 'Build a logical shift register.')

    def test_enable_hold_and_unspecified_initial_value_do_not_negate_shift_contract(self):
        clauses = ['When disabled, hold the state. Do not assume an initial value.',
                   'The register retains its value when enable is disabled; no reset is required.',
                   'With enable disabled, the output remains unchanged. No initial value is specified.',
                   "The register must hold its value while disabled. Don't assume a power-up value."]
        for clause in clauses:
            with self.subTest(clause=clause):
                prompt = PROMPT + ' ' + clause
                self.check(circuit(), 'review', prompt)
                self.check(circuit(17, 'another_register'), 'review', prompt)
                self.check(circuit(sign='signed'), 'skip', prompt)
                self.check(circuit(rhs='$signed(state) >>> 3'), 'skip', prompt)

    def test_hold_or_initial_words_do_not_hide_real_shift_negation(self):
        clauses = ['When disabled, hold the state using logical right shift.',
                   'Do not assume arithmetic right shift for the initial value.',
                   'The initial value does not receive sign extension.',
                   'No initialization is required, but right shifting is logical.',
                   'When disabled, hold the state except during another mode.']
        for clause in clauses:
            with self.subTest(clause=clause):
                self.check(circuit(), 'abstain', PROMPT + ' ' + clause)

    def test_complex_expression_contexts_abstain(self):
        for rhs in ['(state >>> 3) + 1', 'load ? state >>> 3 : data',
                    'state[11:0] >>> 3', '(state) >>> 3', '-state >>> 3',
                    "unsigned'(state) >>> 3", "12'(state) >>> 3",
                    '$unsigned(state) >>> 3', '{{3{state[11]}}, state} >>> 3',
                    'state >>> load', 'state >>> (1 + 2)', 'state >>> 2 >>> 1']:
            with self.subTest(rhs=rhs):
                self.check(circuit(rhs=rhs), 'abstain')

    def test_slice_of_signed_vector_still_abstains(self):
        self.check(circuit(sign='signed', rhs='state[11:0] >>> 3'), 'abstain')

    def test_cast_on_unrelated_operand_is_not_accepted(self):
        self.check(circuit(rhs='$signed(data) >>> 3'), 'abstain')

    def test_unknown_or_separate_operand_abstains(self):
        self.check(circuit(rhs='data >>> 3'), 'abstain')
        self.check(circuit(rhs='unknown >>> 3'), 'abstain')

    def test_unrelated_internal_shift_abstains_even_with_risky_output_shift(self):
        code = circuit().replace('always @', 'reg [11:0] temp;\nalways @')
        code = code.replace('end\nassign', 'temp <= temp >>> 3;\nend\nassign')
        self.check(code, 'abstain')

    def test_macro_and_type_alias_abstain(self):
        for code in [circuit().replace('state >>> 3', 'state >>> `AMOUNT'),
                     '`define WIDTH 12\n' + circuit(),
                     circuit().replace('reg  [11:0] state;', 'typedef logic [11:0] word_t; word_t state;')]:
            with self.subTest(code=code):
                self.check(code, 'abstain')

    def test_multiple_modules_or_outputs_abstain(self):
        self.check(circuit() + 'module Second; endmodule', 'abstain')
        self.check(circuit().replace('output [11:0] result',
                                    'output [11:0] result, output spare'), 'abstain')
        self.check(circuit().replace('output [11:0] result',
                                    'output [11:0] result, spare'), 'abstain')

    def test_nested_scope_function_and_duplicate_declaration_abstain(self):
        for extra in ['function thing; thing = 1; endfunction',
                      'begin : local_scope reg [11:0] state; end',
                      'reg [11:0] state;']:
            with self.subTest(extra=extra):
                self.check(circuit().replace('always @', extra + '\nalways @'), 'abstain')

    def test_output_connection_and_width_must_be_exact(self):
        for replacement in ['assign result = state + 1;',
                            'assign result = state; assign result = data;',
                            'assign result[0] = state[0];', '']:
            with self.subTest(replacement=replacement):
                self.check(circuit().replace('assign result = state;', replacement), 'abstain')
        self.check(circuit().replace('output [11:0]', 'output [12:0]'), 'abstain')

    def test_multi_declarator_or_symbolic_width_abstains(self):
        self.check(circuit().replace('reg  [11:0] state;', 'reg [11:0] state, spare;'), 'abstain')
        self.check(circuit().replace('[11:0]', '[WIDTH-1:0]'), 'abstain')

    def test_unterminated_lexical_input_is_not_trusted(self):
        self.check(circuit() + '/*', 'abstain')
        self.check(circuit() + '"unterminated', 'abstain')

    def test_malformed_inputs_and_no_mutation(self):
        self.assertEqual(selector.analyze(None, circuit())['decision'], 'abstain')
        source = circuit()
        before = source
        result = selector.analyze(PROMPT, source)
        self.assertEqual(source, before)
        self.assertNotIn('solution', result)


if __name__ == '__main__':
    unittest.main()
