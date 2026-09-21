import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent

ERROR = 'ERROR: [VRFC 10-1280] procedural assignment to a non-register q is not permitted'


class RepairTests(unittest.TestCase):
    def test_candidate_warning_provenance_and_budget(self):
        path = Path('candidate.sv').resolve()
        warning = "WARNING: [VRFC 10-8497] literal value 'b1000 truncated to fit in 3 bits"
        log = '\n'.join([f'{warning} [{path}:4]', f'{warning} [{path.parent / "ref.sv"}:5]',
                         f'{warning} [{path.parent / "test.sv"}:6]', warning])
        selected = agent.candidate_warnings(log, path)
        self.assertEqual(selected, warning + ' [candidate.sv:4]')
        many = '\n'.join(f'{warning} [{path}:{n}]' for n in range(100))
        selected = agent.candidate_warnings(many, path)
        result = agent._failed('simulation', None, 'ERROR ' + 'x' * 6000 + '\nMismatches: 8', selected)
        self.assertLessEqual(len(result['feedback']), 4096)
        self.assertIn('Mismatches: 8', result['feedback'])
        self.assertIn('[candidate.sv:0]', result['feedback'])

    def test_compile_warning_reaches_simulation_repair_prompt(self):
        code = 'module TopModule; endmodule'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def process(command, cwd, timeout, log_path):
                output = ('WARNING: [VRFC 10-8497] literal truncated [' + str(cwd / 'candidate.sv') + ':1]'
                          if '01_' in log_path.name else 'Mismatches: 3 in 4 samples')
                return dict(returncode=0, output=output, timed_out=False)
            with mock.patch.object(agent, 'call_model', return_value=code) as model, mock.patch.object(agent, 'run_process', side_effect=process):
                result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, root/'tb.sv', root/'ref.sv', 1, False, True)
            self.assertIn('[candidate.sv:1]', model.call_args_list[1].args[0][1]['content'])
            self.assertEqual(result['model_calls'], 2)

    def test_response_metadata_allowlist_and_truncation_is_per_call(self):
        payload = {'model': 'returned-model', 'api_key': 'SECRET',
                   'usage': {'prompt_tokens': 3, 'completion_tokens': 9, 'total_tokens': 12,
                             'private_extension': 'SECRET'},
                   'choices': [{'finish_reason': 'length', 'message': {'content': 'module TopModule;'}}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'LLM_MOCK_FILE': ''}), mock.patch.object(agent.urllib.request, 'urlopen') as request:
            stopped = json.loads(json.dumps(payload))
            stopped['choices'][0]['finish_reason'] = 'stop'
            request.return_value.__enter__.return_value.read.side_effect = [json.dumps(p).encode() for p in (payload, stopped)]
            root = Path(tmp)
            result = agent.generate_agent_sample('p', root/'out.sv', root/'logs', 1, None, None, 1, True, True)
            first, second = result['attempt_history']
            self.assertIn('finish_reason=length', first['feedback'])
            self.assertNotIn('finish_reason=length', second['feedback'])
            self.assertTrue(second['evaluation_reused'])
            saved = agent.read_text(root/'logs/attempt_1/response_metadata.json')
            self.assertNotIn('SECRET', saved)
            self.assertEqual(json.loads(saved), {'model': 'returned-model', 'finish_reason': 'length',
                'usage': {'prompt_tokens': 3, 'completion_tokens': 9, 'total_tokens': 12}})
            self.assertEqual(request.call_count, 2)

    def test_baseline_response_metadata_without_prompt_change(self):
        payload = {'model': 'returned-model', 'choices': [{'finish_reason': 'stop',
                   'message': {'content': 'module TopModule; endmodule'}}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'LLM_MOCK_FILE': ''}), mock.patch.object(agent.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            result = agent.baseline_generate('p', Path(tmp)/'out.sv')
            self.assertEqual(result['response_metadata'], {'model': 'returned-model', 'finish_reason': 'stop'})
            self.assertEqual(json.loads(request.call_args.args[0].data)['messages'], [{'role': 'user', 'content': 'p'}])

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
