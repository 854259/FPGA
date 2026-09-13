"""Replay archived model outputs through real Vivado; no new cloud requests."""
import argparse
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('use an empty or new output directory')
    dataset = agent.ROOT/'bench/verilog-eval/dataset_spec-to-rtl'
    cases = []
    for name in ['Prob039_always_if', 'Prob058_alwaysblock2']:
        matches = list(Path(args.source_run).rglob(name+'/logs/candidate_1/attempt_1/candidate.sv'))
        if len(matches) != 1:
            parser.error(f'expected exactly one archived candidate for {name}')
        cases.append((name, matches[0]))
    summary = dict(scope='archived response replay with real Vivado; not a new model benchmark',
                   mock_model=True, complete=False, records=[],
                   agent_sha256=agent.sha256_text(agent.read_text(agent.ROOT/'agent.py')))
    agent.write_json(out/'summary.json', summary)
    for name, source in cases:
        code = agent.read_text(source)
        with mock.patch.object(agent, 'call_model', return_value=code) as model:
            result = agent.generate_agent_sample(agent.read_text(dataset/(name+'_prompt.txt')),
                        out/name/'candidate.sv', out/name/'logs', 1,
                        dataset/(name+'_test.sv'), dataset/(name+'_ref.sv'), 1, False, False)
        agent.write_json(out/name/'result.json', result)
        valid = (result['passed'] and result['highest_stage']=='synthesis'
                 and result['selected_attempt']==2 and model.call_count==1
                 and result['attempt_history'][0]['highest_stage']=='compile'
                 and result['attempt_history'][1]['source']=='compiler_declaration_repair')
        summary['records'].append(dict(problem=name, regression_passed=valid,
                  source=str(source.resolve()), source_sha256=agent.sha256_text(code),
                  model_calls=model.call_count, selected_attempt=result['selected_attempt']))
        agent.write_json(out/'summary.json', summary)
        print(json.dumps(summary['records'][-1]), flush=True)
    summary['complete'] = True
    summary['passed'] = all(r['regression_passed'] for r in summary['records'])
    agent.write_json(out/'summary.json', summary)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
