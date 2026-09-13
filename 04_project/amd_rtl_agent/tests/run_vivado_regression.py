"""Run real Vivado positive/negative fixtures and a deterministic repair loop.

Usage: python tests/run_vivado_regression.py --output-dir outputs/vivado_regression
Set VIVADO_BIN to this machine's installation. No cloud/model request is made.
"""
import argparse
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('use a new or empty output directory to preserve previous evidence')
    fixtures = agent.ROOT / 'tests' / 'fixtures'
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
                        'passed': result['passed'] == expected_pass and result['highest_stage'] == stage
                        and all(not step.get('timed_out') and step['returncode'] != 127
                                for step in result['steps'])})
        print(json.dumps(records[-1]), flush=True)

    # Fail functional simulation first, then repair with the correct fixture.
    responses = [agent.read_text(fixtures / f'{name}.sv') for name in ('sim_fail', 'correct')]
    with mock.patch.object(agent, 'call_model', side_effect=responses):
        result = agent.generate_agent_sample(agent.read_text(fixtures / 'problem.txt'),
            out / 'repair.sv', out / 'repair', 1, fixtures / 'test.sv', fixtures / 'ref.sv',
            1, False, True)
    agent.write_json(out / 'repair' / 'result.json', {**result, 'mock_model': True})
    records.append({'case': 'repair_loop', 'passed': result['passed'] and result['selected_attempt'] == 2
                    and not result['attempt_history'][0]['passed']})
    summary = {'vivado_bin': agent.tool_path('vivado'), 'mock_model_for_repair': True,
               'passed': all(r['passed'] for r in records), 'checks': records}
    agent.write_json(out / 'summary.json', summary)
    print(json.dumps(summary), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
