"""Zero-call census of all 156 original-arm pairs across two immutable runs.

Uses request/response identity and existing grades; never generates or regrades RTL.
All data remain development. This diagnoses comparability, not a new quality trial.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for n in ['old', 'new', 'paired', 'kit', 'resource-check', 'out']:
        p.add_argument('--'+n, required=True, type=Path)
    a = p.parse_args()
    assert sys.platform == 'linux'
    assert sha(a.old.read_bytes()) == '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    assert sha(a.new.read_bytes()) == 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
    assert sha(a.paired.read_bytes()) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    spec = importlib.util.spec_from_file_location('census_resource', a.paired)
    resource = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resource)
    resource.check_resource(a.resource_check, a.kit, first=True)
    tick = time.monotonic()
    rows = []
    with zipfile.ZipFile(a.old) as old, zipfile.ZipFile(a.new) as new:
        read = lambda z, n: json.loads(z.read(n))
        tasks = read(new, 'run/RUN_SPEC.json')['task_ids']
        assert len(tasks) == len(set(tasks)) == 156
        controls = {}
        for name in ['package/agent/runtime.py', 'package/baseline.py',
                     'package/skill/rtl-generation/SKILL.md',
                     'package/skill/rtl-feedback-repair/SKILL.md']:
            controls[name] = old.read('run/'+name) == new.read('run/'+name)
        old_inputs = {n:sha(old.read(n)) for n in old.namelist()
                      if n.startswith('kit/bench/tasks_veval/') and not n.endswith('/')}
        new_inputs = {n:sha(new.read(n)) for n in new.namelist()
                      if n.startswith('kit/bench/tasks_veval/') and not n.endswith('/')}
        controls['input_file_map_equal'] = old_inputs == new_inputs
        controls['input_files_old'] = len(old_inputs)
        controls['input_files_new'] = len(new_inputs)
        identities = []
        for z in [old, new]:
            records = [read(z,n) for n in z.namelist() if n.endswith('/resource_check.json')]
            identities.append({json.dumps(r.get('model_identity'),sort_keys=True) for r in records})
        controls['recorded_model_identity_sets_equal'] = identities[0] == identities[1]
        controls['model_identity_distinct_counts'] = [len(v) for v in identities]
        for task in tasks:
            pair = []
            for z, prefix in [(old, 'run/samples/A/'), (new, 'run/results/samples/A/')]:
                base = prefix+task+'/'
                row = read(z,base+'row.json')
                journal = read(z,base+'worker/requests.json')
                first = base+'worker/requests/0/'
                body = read(z,first+'request.json')
                response = read(z,first+'response.json') if journal[0]['response_received'] else None
                content = response['choices'][0]['message'].get('content') if response else None
                pair.append(dict(row=row, journal=journal, body=body, content=content))
            before, after = pair
            one = dict(task=task, old_level=before['row']['verdict']['level'],
                       new_level=after['row']['verdict']['level'],
                       first_request_equal=before['body']==after['body'],
                       first_content_equal=before['content'] is not None and before['content']==after['content'],
                       solution_equal=before['row']['solution_sha256']==after['row']['solution_sha256'],
                       old_solve_s=before['row']['solve_elapsed_s'],new_solve_s=after['row']['solve_elapsed_s'])
            for label, item in [('old',before),('new',after)]:
                one[label+'_deadline'] = item['row']['solve_deadline_reached']
                one[label+'_requests'] = len(item['journal'])
                one[label+'_unconfirmed'] = sum(not j['response_received'] for j in item['journal'])
                one[label+'_length_responses'] = sum(j.get('finish_reason')=='length' for j in item['journal'])
                one[label+'_tool_error'] = item['row']['verdict'].get('tool_error')
            rows.append(one)
        result = dict(complete=True,model_calls=0,eda_calls=0,independent_tasks=0,
            full_batch_complete=False,scope='Historical original-arm comparability census, not a causal algorithm test',
            archive_hashes=[sha(a.old.read_bytes()),sha(a.new.read_bytes())],controls=controls,
            pairs=len(rows),first_request_equal=sum(r['first_request_equal'] for r in rows),
            first_content_equal=sum(r['first_content_equal'] for r in rows),
            solution_equal=sum(r['solution_equal'] for r in rows),
            level_transitions=dict(Counter(str(r['old_level'])+'->'+str(r['new_level']) for r in rows)),
            changed_level_same_solution=[r['task'] for r in rows if r['old_level']!=r['new_level'] and r['solution_equal']],
            elapsed_s=time.monotonic()-tick,rows=rows,
            limits=['No attribution from score differences alone.',
                    'Same process identity is not a fresh weight-file or hardware isolation certificate.',
                    'All viewed outputs remain development; no resampling or prompt change.'])
    resource.check_resource(a.resource_check,a.kit)
    a.out.mkdir(exist_ok=False)
    (a.out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
