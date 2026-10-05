"""Read-only original 156 prompt applicability and already archived failure exposure."""
import hashlib
import json
from pathlib import Path
import zipfile
import fsm_dispatch
import prompt_map

R = Path(__file__).resolve().parent
ARCHIVE_SHA = 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'


def inventory(archive):
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA
    changed, exposure = [], []
    with zipfile.ZipFile(archive) as z:
        summary = json.loads(z.read('run/results/summary.json'))
        assert summary['complete'] and summary['passed'] and len(summary['rows']) == 312
        tasks = sorted({r['task'] for r in summary['rows']})
        assert len(tasks) == 156
        for task in tasks:
            prefix = 'kit/bench/tasks_veval/' + task + '/'
            prompt = z.read(prefix + 'prompt.txt').decode('utf-8').replace('\r\n', '\n')
            if prefix+'interface.txt' in z.namelist():
                interface = z.read(prefix+'interface.txt').decode('utf-8').replace('\r\n', '\n')
                if interface.strip():
                    prompt += '\n\nInterface:\n' + interface
            c, e = prompt_map.parse(prompt), fsm_dispatch.parse(prompt)
            if c == e:
                continue
            assert c['status'] == 'abstain' and e['status'] == 'supported' and e['family'] in ('full_vector_multistate','partial_scalar_onehot')
            changed.append(task)
            row = next(r for r in summary['rows'] if r['task'] == task and r['arm'] == 'C')
            work = 'run/results/samples/C/' + task + '/worker/'
            trace = [json.loads(s) for s in z.read(work+'trace.jsonl').decode().splitlines()]
            request_bytes = z.read(work+'requests/0/request.json')
            request = json.loads(request_bytes)
            assert request['messages'][1] == dict(role='user', content=prompt)
            assert row['actual_model_requests'] == row['received_model_responses'] == 1
            assert row['verdict']['level'] == 1 and not row['verdict']['tool_error']
            assert not row['solve_deadline_reached']
            assert len([t for t in trace if t['tool'] == 'lint' and t['rc'] == 0]) == 1
            assert not any(t['tool'] in ['declaration_fix', 'map_feedback'] for t in trace)
            exposure.append(dict(task=task, original_C_level=1, original_C_requests=1,
                                 prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                                 first_request_sha256=hashlib.sha256(request_bytes).hexdigest(),
                                 first_reply_sha256=hashlib.sha256(z.read(work+'requests/0/response.json')).hexdigest(),
                                 new_family=e['family'], checks=e['checks']))
    assert changed == ['Prob143_fsm_onehot', 'Prob150_review2015_fsmonehot']
    return dict(schema='fsm_feedback_archived_exposure_v1', archive_sha256=ARCHIVE_SHA,
                original_tasks=156, unchanged_dispatch_tasks=154, newly_supported_tasks=changed,
                exposure=exposure, model_calls=0, eda_calls=0, actual_new_model_repair_measured=False,
                independent_natural_tasks=0, adoption=False)


if __name__ == '__main__':
    archive = R.parent/'functional_full156_20261005/raw_evidence/terminal_v1.zip'
    output = inventory(archive)
    (R/'ARCHIVED_EXPOSURE.json').write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(output))
