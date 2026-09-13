"""Re-run selected agent samples against an archived run; never overwrite it.

Set the same LLM_* and VIVADO_BIN environment as the source experiment.
This is a targeted development check, not a new full benchmark or baseline.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--problems', nargs='+', required=True, help='exact problem names')
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('use a new or empty output directory')
    if len(set(args.problems)) != len(args.problems):
        parser.error('duplicate problem names')
    source = Path(args.source_run).resolve()
    dataset = agent.ROOT / 'bench/verilog-eval/dataset_spec-to-rtl'
    selected = []
    for name in args.problems:
        matches = [p for p in source.rglob('result.json') if p.parent.name == name]
        if len(matches) != 1:
            parser.error(f'expected one archived result for {name}, found {len(matches)}')
        old = json.loads(agent.read_text(matches[0]))
        prompt = dataset / (name + '_prompt.txt')
        problem = agent.read_text(prompt)
        if agent.sha256_text(problem) != old['problem_sha256'] or agent.model_settings() != old['model']:
            parser.error(f'problem or model configuration changed for {name}')
        for suffix in ('_test.sv', '_ref.sv'):
            if not (dataset / (name + suffix)).is_file():
                parser.error(f'missing {name + suffix}')
        selected.append((name, old, problem, matches[0]))
    summary = dict(scope='targeted development retest; selection biased; not full pass@1',
                   source_run=str(source), complete=False, requested_problems=args.problems,
                   model=agent.model_settings(), skill_sha256=agent.sha256_text(agent.skill_text()),
                   repair_skill_sha256=agent.sha256_text(agent.read_text(agent.ROOT / 'skill/RTL_REPAIR_SKILL.md')),
                   agent_sha256=agent.sha256_text(agent.read_text(agent.ROOT / 'agent.py')),
                   evaluation_mode='compile_simulation_synthesis', records=[])
    agent.write_json(out / 'summary.json', summary)
    for name, old, problem, archive in selected:
        first = old['samples'][0]
        result = agent.generate_agent_sample(problem, out/name/'candidate.sv', out/name/'logs',
                    first['seed'], dataset/(name+'_test.sv'), dataset/(name+'_ref.sv'),
                    1, False, False)
        agent.write_json(out/name/'result.json', result)
        record = dict(problem=name, previous_pass=old['pass_at_1'], passed=agent.functional_pass(result),
                      highest_stage=result['highest_stage'], attempts=result['attempts'],
                      seed=first['seed'], repairs=1, elapsed_s=result['elapsed_s'],
                      previous_skill_sha256=old['skill_sha256'], source_result=str(archive))
        summary['records'].append(record)
        agent.write_json(out/'summary.json', summary)
        print(json.dumps(record), flush=True)
    summary['complete'] = True
    summary['previous_passed'] = sum(r['previous_pass'] is True for r in summary['records'])
    summary['passed'] = sum(r['passed'] is True for r in summary['records'])
    agent.write_json(out/'summary.json', summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
