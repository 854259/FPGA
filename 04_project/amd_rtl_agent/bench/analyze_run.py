"""Summarize archived per-problem results without calling a model or reading references."""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def analyze(source):
    records = []
    for path in sorted(source.rglob('result.json')):
        result = json.loads(agent.read_text(path))
        if 'samples' not in result:
            continue
        first = result['samples'][0]
        attempts = first['attempt_history']
        identical = 0
        previous = None
        for attempt in attempts:
            code_path = path.parent / f"logs/candidate_1/attempt_{attempt['attempt']}/candidate.sv"
            code = agent.read_text(code_path)
            identical += previous == code
            previous = code
        records.append(dict(problem=path.parent.name, baseline_pass=result['baseline_pass'],
                            agent_pass=result['pass_at_1'], stage=first['highest_stage'],
                            initially_passed=attempts[0]['passed'], attempts=len(attempts),
                            identical_repairs=identical, result_path=str(path.resolve())))
    functional = [r for r in records if r['baseline_pass'] is not None and r['agent_pass'] is not None]
    failures = [r for r in functional if not r['agent_pass']]
    return dict(source_run=str(source.resolve()), completed=len(records),
                functional_problems=len(functional),
                baseline_passed=sum(r['baseline_pass'] for r in functional),
                agent_passed=sum(r['agent_pass'] for r in functional),
                initially_passed=sum(r['initially_passed'] for r in functional),
                repaired=sum(not r['initially_passed'] and r['agent_pass'] for r in functional),
                improved=sum(not r['baseline_pass'] and r['agent_pass'] for r in functional),
                regressed=sum(r['baseline_pass'] and not r['agent_pass'] for r in functional),
                repair_attempts=sum(r['attempts']-1 for r in functional),
                identical_repairs=sum(r['identical_repairs'] for r in functional),
                failure_stages=dict(collections.Counter(r['stage'] for r in failures)),
                failures=failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    summary = analyze(Path(args.source_run))
    if not summary['completed']:
        parser.error('no per-problem results found')
    agent.write_json(Path(args.output), summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'failures'}, indent=2))


if __name__ == '__main__':
    main()
