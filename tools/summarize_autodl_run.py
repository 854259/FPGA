"""Build a public, credential-free audit from the downloaded run evidence."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def summarize(root):
    run = root / 'project/outputs/full156_20260927_131610_dc69ee'
    reference = root / 'project/outputs/reference156_20260927_123714_ecabcb'
    exp = read(run / 'experiment.json')
    assert exp['complete'] and exp['samples'] == 1 and len(set(exp['task_ids'])) == 156
    records, hashes, summaries = {}, {}, {}
    for mode in ('agent', 'baseline'):
        records[mode] = []
        for task in exp['task_ids']:
            result_file = run / 'results' / f'{mode}.{task}.s0.json'
            result = read(result_file)
            assert result['task_id'] == task and result['tool_error'] is None
            trace_file = run / mode / task / 's0/trace.jsonl'
            events = [json.loads(line) for line in trace_file.read_text().splitlines() if line.strip()]
            calls = [{k: event[k] for k in ('round', 'tokens_in', 'tokens_out', 'finish', 'empty_content', 'sec') if k in event}
                     for event in events if event.get('tool') == 'llm']
            lint = [{k: event[k] for k in ('round', 'rc') if k in event}
                    for event in events if event.get('tool') in ('lint', 'check_source')]
            records[mode].append(dict(result=result, calls=calls, checks=lint))
            for file in (result_file, trace_file):
                hashes[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
        rows = records[mode]
        calls = [c for row in rows for c in row['calls']]
        summaries[mode] = {
            'tasks': len(rows),
            'levels': dict(Counter(str(row['result']['level']) for row in rows)),
            'l3_passed': sum(row['result']['level'] == 3 for row in rows),
            'model_calls': len(calls),
            'length_limited_calls': sum(c.get('finish') == 'length' for c in calls),
            'tasks_with_length_limit': sum(any(c.get('finish') == 'length' for c in row['calls']) for row in rows),
            'l0_last_call_length': sum(row['result']['level'] == 0 and row['calls'][-1].get('finish') == 'length' for row in rows),
            'repair_attempted_tasks': sum(any(c.get('round', 0) > 0 for c in row['calls']) for row in rows),
            'l3_after_repair': sum(row['result']['level'] == 3 and any(c.get('round', 0) > 0 for c in row['calls']) for row in rows),
        }
    pairs = list(zip(records['agent'], records['baseline']))
    improved = [a['result']['task_id'] for a, b in pairs if a['result']['level'] == 3 and b['result']['level'] != 3]
    regressed = [a['result']['task_id'] for a, b in pairs if a['result']['level'] != 3 and b['result']['level'] == 3]
    ref = read(reference / 'graded_summary.json')['modes']['reference']
    flagged = [x['task_id'] for x in ref['per_task'] if x['levels'] != [3]]
    source_hashes = {}
    for path, expected in exp['submission_sha256'].items():
        f = root / 'project/submission' / path
        if f.exists():
            actual = hashlib.sha256(f.read_bytes()).hexdigest()
            assert actual == expected, f'source mismatch: {path}'
            source_hashes[path] = actual
    tz = timezone(timedelta(hours=8))
    return dict(
        schema_version=1, run_id=run.name, complete=True, samples_per_mode_per_task=1,
        started_at=datetime.fromtimestamp(exp['started_at'], tz).isoformat(),
        finished_at=datetime.fromtimestamp(exp['finished_at'], tz).isoformat(),
        elapsed_seconds=exp['finished_at']-exp['started_at'],
        model_repository=read(root/'model-lock.json')['repository'],
        model_revision=read(root/'model-lock.json')['revision'],
        upstream_commit=exp['upstream_commit'], vivado_version=exp['vivado_version'],
        deadline_seconds=exp['local_deadline_s'], summaries=summaries,
        improved_tasks=improved, regressed_tasks=regressed,
        reference_non_l3_tasks=flagged, raw_results_excluded=[],
        diagnostic_reference_l3_subset={m: {'tasks':156-len(flagged), 'l3_passed':sum(row['result']['level']==3 for row in rows if row['result']['task_id'] not in flagged)} for m,rows in records.items()},
        graded_scores={m: d['set_score'] for m,d in read(run/'graded_summary.json')['modes'].items()},
        limitations=['Single sample per task; not pass@5.',
                      'Development run on NVIDIA; not AMD ROCm or final isolated acceptance.',
                      'Paired system comparison, not an ablation of individual optimizations.',
                      'Reference anomalies retained in raw 156-task result.',
                      'Source model-lock contains preparation-era status flags; those are not current runtime status.'],
        submission_sha256=exp['submission_sha256'], downloaded_submission_hashes_verified=source_hashes,
        records=records, evidence_sha256=hashes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('extracted_backup', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = summarize(args.extracted_backup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','evidence_sha256','submission_sha256','downloaded_submission_hashes_verified')}, ensure_ascii=False, indent=2))
