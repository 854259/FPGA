"""Audit-bound descriptive failure/cost inventory. Never loads references or TBs."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import zipfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory(archive, audit_path, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Use fresh inventory output")
    audit_raw = Path(audit_path).read_bytes()
    audit = json.loads(audit_raw)
    assert audit['evidence_valid'] is True
    assert digest(Path(archive).read_bytes()) == audit['archive_sha256']
    records = []
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))
        # The prior auditor verifies the complete archive. This reader additionally
        # binds every byte it consumes; it does not extract or execute archive code.
        members = manifest['files']
        def read(name):
            assert '/reference/' not in name and not name.endswith(('/ref.sv', '/tb.sv'))
            raw = z.read(name)
            expected = members[name]
            assert digest(raw) == (expected['sha256'] if isinstance(expected, dict) else expected)
            return raw
        for row in audit['rows']:
            task, arm = row['task'], row['arm']
            prefix = f'run/samples/{arm}/{task}/worker/'
            prompt = read(f'kit/bench/tasks_veval/{task}/prompt.txt').decode('utf-8')
            journal = json.loads(read(prefix + 'requests.json'))
            calls = []
            for entry in journal:
                if not entry['response_received']:
                    calls.append(dict(round=entry['index'], response_received=False))
                    continue
                response = json.loads(read(prefix + f"requests/{entry['index']}/response.json"))
                text = response['choices'][0]['message'].get('content') or ''
                comments = re.findall(r'//[^\n]*|/\*[\s\S]*?\*/', text)
                # This character fraction describes output; it is neither tokenizer
                # accounting nor a proof of incorrectness. No answer bodies emitted.
                calls.append(dict(round=entry['index'], response_received=True,
                    finish_reason=entry['finish_reason'], elapsed_s=entry['elapsed_s'],
                    completion_tokens=(response.get('usage') or {}).get('completion_tokens'),
                    content_chars=len(text), comment_chars=sum(map(len, comments)),
                    comment_char_fraction=sum(map(len, comments)) / max(1, len(text)),
                    response_sha256=entry['response_sha256']))
            records.append(dict(task=task, arm=arm, level=row['level'],
                failed_stage=({0:'compile',1:'simulate',2:'synth'}.get(row['level'])),
                solution_sha256=row['solution_sha256'], prompt_sha256=digest(prompt.encode()),
                deadline=row['deadline'], request_attempts=row['request_attempts'],
                unconfirmed_attempts=row['unconfirmed_attempts'], solve_s=row['solve_elapsed_s'],
                calls=calls, prompt_review_tags=[tag for tag, expression in (
                    ('sequential', r'(?i)clock|flip.flop|register|state machine'),
                    ('table_or_map', r'(?i)truth table|karnaugh|state table'),
                    ('index_or_selection', r'(?i)multiplex|shift|neighbou?r|index'),
                    ('reset', r'(?i)reset'),
                    ('diagram', r'(?i)diagram|figure|circuit (?:below|shown)')) if re.search(expression,prompt)]))
    totals = {}
    for arm in ('A','C'):
        items = [x for x in records if x['arm']==arm]
        received = [c for x in items for c in x['calls'] if c['response_received']]
        totals[arm] = dict(samples=len(items), levels=dict(collections.Counter(x['level'] for x in items)),
            confirmed_responses=len(received), length_responses=sum(c['finish_reason']=='length' for c in received),
            deadlines=sum(x['deadline'] for x in items),
            long_comment_responses=sum(c['content_chars']>=2000 and c['comment_char_fraction']>.5 for c in received),
            slowest_calls=sorted([dict(task=x['task'], **c) for x in items for c in x['calls'] if c['response_received']],
                                key=lambda c:c['elapsed_s'], reverse=True)[:8])
    result = dict(schema='audit_bound_failure_inventory_v1', source_archive_sha256=audit['archive_sha256'],
        source_audit_sha256=digest(audit_raw), analyzer_sha256=digest(Path(__file__).read_bytes()),
        full_round_complete=audit['full_round_complete'], samples=len(records), totals=totals,
        records=records, model_calls=0, eda_calls=0, runtime_changes=False,
        limitations=['Descriptive tags require manual contract review; they are not causal attribution',
            'Failed stage is pinned official level mapping, not a diagnosis',
            'Comment character fraction is not reasoning token accounting',
            'Prompt SHA binds original UTF-8/CRLF bytes; no reference or TB read',
            'No full score computed by this inventory'])
    output.mkdir(parents=True)
    (output/'RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True,type=Path)
    p.add_argument('--audit',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    r=inventory(a.archive,a.audit,a.out)
    print(json.dumps({k:r[k] for k in ('full_round_complete','samples','totals')},ensure_ascii=False))
