import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent

ERROR = 'ERROR: [VRFC 10-1280] procedural assignment to a non-register q is not permitted'


class RepairTests(unittest.TestCase):
    def test_direction_feedback_does_not_cross_port_boundaries(self):
        feedback = "Hint: Output 'q' has 2 mismatches"
        for code in [
            'module TopModule(input clk, output reg q); endmodule',
            'module TopModule(input clk,\noutput q); endmodule',
            'module TopModule(input [q:0] data, output q); endmodule',
            'module TopModule(output q); // input q;\nendmodule',
            'module TopModule(output q); /* input q; */ endmodule',
            'module Other(input q); endmodule\nmodule TopModule(output q); endmodule',
            'module TopModule(output q); function f(input q); endfunction endmodule',
            'module TopModule(output q); initial $display("input q;"); endmodule',
            'module TopModule(clk, q); input clk, q; endmodule',
            'module TopModule #(parameter N=1)(input q); endmodule',
        ]:
            with self.subTest(code=code):
                self.assertEqual(agent.repair_feedback(code, feedback), feedback)

    def test_direction_feedback_identifies_simple_real_input_ports(self):
        feedback = "Hint: Output 'q' has 2 mismatches"
        for code in [
            'module TopModule(input q); endmodule',
            'module TopModule(input clk, q, output z); endmodule',
            'module TopModule(input wire signed [7:0] q); endmodule',
        ]:
            with self.subTest(code=code):
                self.assertIn('input', agent.repair_feedback(code, feedback))

    def test_next_repair_uses_best_candidate_after_regression(self):
        codes = ['module TopModule; wire good_base; endmodule',
                 'module TopModule; wire regressed; endmodule',
                 'module TopModule; wire fixed; endmodule']
        initial = dict(passed=False, highest_stage='simulation', feedback='Mismatches: 2 in 100 samples')
        passed = dict(passed=True, highest_stage='synthesis', functional_checked=True)
        for regression in [
            dict(passed=False, highest_stage='compile', feedback='syntax error'),
            dict(passed=False, highest_stage='simulation', feedback='Mismatches: 80 in 100 samples'),
        ]:
            with self.subTest(regression=regression), tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', side_effect=codes) as model, mock.patch.object(agent, 'evaluate_candidate', side_effect=[initial, regression, passed]) as evaluate:
                root = Path(tmp)
                result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, 'tb', 'ref', 2, False, False)
                prompt = model.call_args_list[2].args[0][1]['content']
                self.assertIn(codes[0], prompt)
                self.assertIn(initial['feedback'], prompt)
                self.assertNotIn(codes[1], prompt)
                self.assertEqual([a['repair_from_attempt'] for a in result['attempt_history']], [None, 1, 1])
                self.assertEqual((root/'logs/attempt_2/candidate.sv').read_text().strip(), codes[1])
                self.assertEqual(evaluate.call_count, 3)
                self.assertEqual(result['model_calls'], 3)
                self.assertTrue(result['passed'])

    def test_next_repair_keeps_new_candidate_when_quality_does_not_regress(self):
        codes = ['module TopModule; wire first; endmodule',
                 'module TopModule; wire second; endmodule',
                 'module TopModule; wire third; endmodule']
        for count in (2, 10):
            results = [dict(passed=False, highest_stage='simulation', feedback=f'Mismatches: {n} in 100 samples')
                       for n in (10, count, 1)]
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', side_effect=codes) as model, mock.patch.object(agent, 'evaluate_candidate', side_effect=results):
                root = Path(tmp)
                result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, 'tb', 'ref', 2, False, False)
                self.assertIn(codes[1], model.call_args_list[2].args[0][1]['content'])
                self.assertEqual(result['attempt_history'][2]['repair_from_attempt'], 2)

    def test_output_patch_preserves_width_signedness_and_body(self):
        for decl, expected in [('output q', 'output reg q'),
                               ('output wire signed [7:0] q', 'output reg signed [7:0] q')]:
            code = f'module TopModule(input clk, {decl}); always @(posedge clk) q <= 0; endmodule'
            self.assertEqual(agent.repair_output_declarations(code, ERROR), code.replace(decl, expected))

    def test_patch_declines_ambiguous_or_unrelated_constructs(self):
        for code in ['module TopModule(q); output q; endmodule',
                     'module TopModule(output q, other); endmodule',
                     'module TopModule(output logic q); endmodule',
                     'module TopModule(input q); endmodule',
                     'module TopModule(output x); endmodule',
                     '`define PORT q\nmodule TopModule(output q); endmodule',
                     'module TopModule #(parameter N=1)(output q); endmodule',
                     'module TopModule(output x /* output q */); endmodule']:
            with self.subTest(code=code):
                self.assertIsNone(agent.repair_output_declarations(code, ERROR))

    def test_comment_is_preserved_and_cannot_be_patched(self):
        code = '// output q\nmodule TopModule(output /* note */ q); endmodule'
        self.assertEqual(agent.repair_output_declarations(code, ERROR),
                         '// output q\nmodule TopModule(output reg /* note */ q); endmodule')

    def test_compiler_patch_uses_repair_budget_and_is_evaluated(self):
        code = 'module TopModule(output q); always @* q = 0; endmodule'
        failed = dict(passed=False, highest_stage='compile', feedback=ERROR)
        passed = dict(passed=True, highest_stage='synthesis', functional_checked=True)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', return_value=code) as model, mock.patch.object(agent, 'evaluate_candidate', side_effect=[failed, passed]) as evaluate:
            root = Path(tmp)
            result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, 'tb', 'ref', 1, False, False)
            self.assertTrue(result['passed'])
            self.assertEqual(model.call_count, 1)
            self.assertEqual(evaluate.call_count, 2)
            self.assertEqual(result['selected_attempt'], 2)
            self.assertEqual(result['attempt_history'][1]['source'], 'compiler_declaration_repair')

    def test_identical_compile_failure_is_reused_and_next_prompt_changes(self):
        failed = dict(passed=False, highest_stage='compile', feedback='syntax error', steps=[dict(returncode=1)])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', return_value='module TopModule; endmodule') as model, mock.patch.object(agent, 'evaluate_candidate', return_value=failed) as evaluate:
            root = Path(tmp)
            result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, 'tb', 'ref', 2, False, False)
            self.assertEqual(evaluate.call_count, 1)
            self.assertEqual(result['model_calls'], 3)
            self.assertTrue(result['attempt_history'][1]['evaluation_reused'])
            self.assertIn('完全相同', model.call_args_list[2].args[0][1]['content'])
            self.assertFalse(result['passed'])

    def test_timeout_missing_tool_and_simulation_are_not_cached(self):
        for stage, rc in [('compile', 124), ('compile', 127), ('simulation', 0)]:
            failed = dict(passed=False, highest_stage=stage, feedback='failed', steps=[dict(returncode=rc)])
            with self.subTest(stage=stage, rc=rc), tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', return_value='module TopModule; endmodule'), mock.patch.object(agent, 'evaluate_candidate', return_value=failed) as evaluate:
                root = Path(tmp)
                agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, 'tb', 'ref', 1, False, False)
                self.assertEqual(evaluate.call_count, 2)


if __name__ == '__main__':
    unittest.main()
