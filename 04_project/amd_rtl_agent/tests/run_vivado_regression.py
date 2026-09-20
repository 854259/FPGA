"""Run real Vivado positive/negative fixtures and a deterministic repair loop.

Usage: python tests/run_vivado_regression.py --output-dir outputs/vivado_regression
Set VIVADO_BIN to this machine's installation. No cloud/model request is made.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def fixture_passed(name, result):
    if any(step.get('timed_out') or step['returncode'] == 127 for step in result['steps']):
        return False
    if name == 'correct':
        return result['passed'] and result['highest_stage'] == 'synthesis'
    stage, diagnostic = {
        'compile_fail': ('compile', r'ERROR:.*\[VRFC [\d-]+\].*syntax error'),
        'sim_fail': ('simulation', r'^\s*Mismatches:\s*[1-9]\d*\b'),
        'synth_fail': ('synthesis', r'ERROR:.*\[Synth 8-91\].*ambiguous clock'),
    }[name]
    return (not result['passed'] and result['highest_stage'] == stage and
            re.search(diagnostic, result.get('feedback', ''), re.MULTILINE) is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--repair-backtrack-only', action='store_true',
                        help='check repair regression recovery with real compile/simulation, without synthesis')
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('use a new or empty output directory to preserve previous evidence')
    fixtures = agent.ROOT / 'tests' / 'fixtures'
    if args.repair_backtrack_only:
        responses = [agent.read_text(fixtures / f'{name}.sv')
                     for name in ('sim_fail', 'compile_fail', 'correct')]
        with mock.patch.object(agent, 'call_model', side_effect=responses) as model:
            result = agent.generate_agent_sample(agent.read_text(fixtures / 'problem.txt'),
                out / 'repair.sv', out / 'repair', 1, fixtures / 'test.sv', fixtures / 'ref.sv',
                2, False, True)
        prompt = model.call_args_list[2].args[0][1]['content'] if model.call_count == 3 else ''
        history = result['attempt_history']
        checks = {
            'initial_simulation_failure': fixture_passed('sim_fail', {**history[0], 'steps': []}),
            'regressed_compile_failure': len(history) >= 2 and fixture_passed(
                'compile_fail', {**history[1], 'steps': []}),
            'repair_restored_best_code_and_feedback': responses[0].strip() in prompt
                and responses[1].strip() not in prompt and history[0]['feedback'] in prompt,
            'repair_lineage_and_budget': [a.get('repair_from_attempt') for a in history] == [None, 1, 1]
                and model.call_count == 3,
            'repaired_simulation_passed': result['passed'] and result['functional_checked']
                and result['highest_stage'] == 'simulation' and result['selected_attempt'] == 3,
        }
        agent.write_json(out / 'repair' / 'result.json', {
            **result, 'mock_model': True, 'final_repair_user_message': prompt})
        summary = {'vivado_bin': agent.tool_path('vivado'), 'mock_model_for_repair': True,
                   'repair_synthesis_checked': False, 'passed': all(checks.values()), 'checks': checks}
        agent.write_json(out / 'summary.json', summary)
        print(json.dumps(summary), flush=True)
        return 0 if summary['passed'] else 1
    records = []
    for name, expected_pass, stage, with_tb in [
        ('correct', True, 'synthesis', True),
        ('compile_fail', False, 'compile', True),
        ('sim_fail', False, 'simulation', True),
        ('synth_fail', False, 'synthesis', False),
    ]:
        result = agent.evaluate_candidate(fixtures / f'{name}.sv', out / name,
            fixtures / 'test.sv' if with_tb else None,
            fixtures / 'ref.sv' if with_tb else None)
        agent.write_json(out / name / 'evaluation.json', result)
        records.append({'case': name, 'expected_pass': expected_pass, 'expected_stage': stage,
                        'passed': fixture_passed(name, result)})
        print(json.dumps(records[-1]), flush=True)

    # Fail functional simulation first, then repair with the correct fixture.
    responses = [agent.read_text(fixtures / f'{name}.sv') for name in ('sim_fail', 'correct')]
    with mock.patch.object(agent, 'call_model', side_effect=responses):
        result = agent.generate_agent_sample(agent.read_text(fixtures / 'problem.txt'),
            out / 'repair.sv', out / 'repair', 1, fixtures / 'test.sv', fixtures / 'ref.sv',
            1, False, False)
    agent.write_json(out / 'repair' / 'result.json', {**result, 'mock_model': True})
    records.append({'case': 'repair_loop', 'passed': result['passed'] and result['selected_attempt'] == 2
                    and result['highest_stage'] == 'synthesis'
                    and fixture_passed('sim_fail', {**result['attempt_history'][0], 'steps': []})})
    summary = {'vivado_bin': agent.tool_path('vivado'), 'mock_model_for_repair': True,
               'repair_synthesis_checked': True,
               'passed': all(r['passed'] for r in records), 'checks': records}
    agent.write_json(out / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
