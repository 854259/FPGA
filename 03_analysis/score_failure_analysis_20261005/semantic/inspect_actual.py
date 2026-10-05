"""Read-only old completed A/C full156 evidence inspection; zero model/EDA calls."""
from pathlib import Path, PurePosixPath
import collections
import hashlib
import io
import json
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
RUN = PROJECT / '03_analysis/functional_full156_20261005'
RAW = ROOT / 'raw_evidence'
ARCHIVE_SHA = 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
SPEC_SHA = '43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
AUDITOR_SHA = 'a4fcd91ac36c54c202be841a476cac256cb56b33a125a3833744b992e9986381'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def text(data):
    return io.StringIO(data.decode('utf-8'), newline=None).read()


def main():
    assert sys.version_info[:3] == (3, 12, 14)
    archive = RUN / 'raw_evidence/terminal_v1.zip'
    audit_path = RUN / 'terminal_audit_local312/RESULTS.json'
    audited = json.loads(audit_path.read_bytes())
    assert sha(archive.read_bytes()) == ARCHIVE_SHA
    assert sha((RUN / 'RUN_SPEC.json').read_bytes()) == SPEC_SHA
    assert sha((RUN / 'audit.py').read_bytes()) == AUDITOR_SHA
    assert audited['archive_sha256'] == ARCHIVE_SHA and audited['spec_sha256'] == SPEC_SHA
    assert audited['auditor_sha256'] == AUDITOR_SHA and audited['evidence_valid'] and audited['full156_evidence_valid']
    assert audited['historical_fixture_only'] is False and audited['expected_samples'] == 312
    assert len(audited['provenance']) == 312 and len(audited['first_pairs']) == 156
    private = []
    public = []
    total_requests = 0
    responses = 0
    no_missing_image_claim = []
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))
        assert len(z.namelist()) == len(set(z.namelist()))
        assert set(z.namelist()) == set(manifest['files']) | {'ARCHIVE_MANIFEST.json'}
        assert manifest['run_spec_sha256'] == SPEC_SHA
        for name, expected in manifest['files'].items():
            assert not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts and '\\' not in name
            assert sha(z.read(name)) == expected, name
        spec = json.loads(z.read('run/RUN_SPEC.json'))
        assert sha(z.read('run/RUN_SPEC.json')) == SPEC_SHA
        for name, expected in spec['source_hashes'].items():
            assert sha(z.read('run/' + name)) == expected == sha((RUN / name).read_bytes()), name
        for name, expected in spec['dependency_hashes'].items():
            assert sha(z.read('dependencies/' + name)) == expected
        report = json.loads(z.read('run/results/summary.json'))
        assert report['complete'] and report['passed'] and len(report['rows']) == 312
        assert report['first_generation_replayed'] is False and report['spec_sha256'] == SPEC_SHA
        for key in ['official_scores', 'coefficients', 'repairs', 'regressions', 'unconfirmed_attempts',
                    'solve_deadlines', 'requests_by_arm', 'solve_seconds_by_arm', 'candidate_qualified_for_independent_validation']:
            assert report[key] == audited[key], key
        assert sorted({row['task'] for row in report['rows']}) == sorted(spec['task_ids']) and len(spec['task_ids']) == 156
        assert collections.Counter(row['arm'] for row in report['rows']) == {'A': 156, 'C': 156}
        provenance = {(row['arm'], row['task']): row for row in audited['provenance']}
        for row in report['rows']:
            task, arm = row['task'], row['arm']
            base = 'run/results/samples/' + arm + '/' + task + '/'
            assert json.loads(z.read(base + 'row.json')) == row
            assert json.loads(z.read(base + 'judge/verdict.json')) == row['verdict']
            assert sha(z.read(base + 'judge/verdict.json')) == row['verdict_sha256']
            assert sha(z.read(base + 'worker/solution.v')) == row['solution_sha256']
            assert z.read(base + 'worker/prompt_only/prompt.txt') == z.read('kit/bench/tasks_veval/' + task + '/prompt.txt')
            journal = json.loads(z.read(base + 'worker/requests.json'))
            assert len(journal) == row['actual_model_requests']
            for index, entry in enumerate(journal):
                assert entry['index'] == index and entry['replayed'] is False
                assert sha(z.read(base + 'worker/requests/' + str(index) + '/request.json')) == entry['request_sha256']
                if entry['response_received']:
                    assert sha(z.read(base + 'worker/requests/' + str(index) + '/response.json')) == entry['response_sha256']
                    responses += 1
            total_requests += len(journal)
            if journal[0]['response_received']:
                first = json.loads(z.read(base + 'worker/requests/0/response.json'))
                content = first['choices'][0]['message']['content']
                assert sha(content.encode()) == provenance[(arm, task)]['first_reply_sha256']
            else:
                first, content = None, None
            if arm != 'C':
                continue
            prompt = text(z.read(base + 'worker/prompt_only/prompt.txt'))
            first_source_name = base + 'worker/compile_receipts/0/source_before.sv'
            source = text(z.read(first_source_name)) if first_source_name in manifest['files'] else None
            if row['verdict']['level'] == 1:
                assert source is not None, task
            final = text(z.read(base + 'worker/solution.v'))
            request = json.loads(z.read(base + 'worker/requests/0/request.json'))
            log = text(z.read(base + 'judge/judge_work_logs/w_judge.log'))
            hints = [line for line in log.splitlines() if line.startswith(('Hint:', 'Mismatches:', 'TIMEOUT', 'Simulation finished'))]
            signals = dict(explicit_image_tag=bool(re.search(r'!\[[^]]*\]\(|<img\b', prompt, re.I)),
                           diagram_mention=bool(re.search(r'\b(diagram|waveform|figure|shown|circuit below)\b', prompt, re.I)),
                           ascii_transition_rows=len(re.findall(r'--[^\n]*-->', prompt)),
                           bar_table_lines=sum('|' in line for line in prompt.splitlines()),
                           user_unicode_replacement_chars=request['messages'][1]['content'].count('\ufffd'),
                           system_unicode_replacement_chars=request['messages'][0]['content'].count('\ufffd'))
            entry = dict(task=task, arm='C', official_level=row['verdict']['level'], mismatches=row['verdict'].get('mismatches'),
                         samples=row['verdict'].get('samples'), sim_timeout=row['verdict'].get('sim_timeout', False),
                         solve_deadline_reached=row['solve_deadline_reached'], requests=row['actual_model_requests'],
                         received_responses=row['received_model_responses'], prompt_sha256=sha(z.read(base + 'worker/prompt_only/prompt.txt')),
                         first_content_sha256=sha(content.encode()) if content else None,
                         first_compile_source_sha256=sha(z.read(first_source_name)) if source is not None else None,
                         final_source_sha256=row['solution_sha256'], judge_log_sha256=sha(z.read(base + 'judge/judge_work_logs/w_judge.log')),
                         first_completion_tokens=first.get('usage', {}).get('completion_tokens') if first else None,
                         first_finish_reason=first['choices'][0].get('finish_reason') if first else None,
                         signals=signals, official_diagnostic=hints)
            public.append(entry)
            if row['verdict']['level'] == 1 or signals['diagram_mention']:
                private.append(dict(**entry, prompt=prompt, first_content=content, first_source=source, final_source=final,
                                    first_source_without_comments_display=re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S) if source is not None else None,
                                    original_ref_review_only=text(z.read('kit/bench/tasks_veval/' + task + '/ref.sv')),
                                    original_tb_review_only=text(z.read('kit/bench/tasks_veval/' + task + '/tb.sv'))))
            if signals['diagram_mention']:
                no_missing_image_claim.append(dict(task=task, explicit_image_tag=signals['explicit_image_tag'],
                    archived_task_files=[name.split('/')[-1] for name in manifest['files'] if name.startswith('kit/bench/tasks_veval/' + task + '/')],
                    status='text-only archived artifact; image omission is not inferred from a diagram word'))
        assert total_requests == report['actual_model_requests'] == audited['actual_model_requests'] == 333
        assert total_requests - responses == report['unconfirmed_attempts'] == 3
        assert len(public) == 156
        failures = [row for row in public if row['official_level'] == 1]
        assert len(failures) == 40 and sum(row['mismatches'] > 0 for row in failures) == 39
        result = dict(schema='old_full156_C_semantic_failure_evidence_inspection_v1', evidence_valid=True,
                      source_archive_sha256=ARCHIVE_SHA, source_archive_bytes=archive.stat().st_size,
                      source_spec_sha256=SPEC_SHA, source_auditor_sha256=AUDITOR_SHA,
                      source_audit_result_sha256=sha(audit_path.read_bytes()), manifest_files=len(manifest['files']),
                      verified_samples=312, verified_task_ids=156, actual_historical_model_requests=333,
                      actual_historical_received_responses=responses, historical_unconfirmed_attempts=3,
                      inspected_C_samples=156, official_level_counts=dict(collections.Counter(row['official_level'] for row in public)),
                      C_L1_samples=40, C_L1_positive_mismatch_samples=39, C_L1_zero_mismatch_sim_timeouts=[row['task'] for row in failures if row['sim_timeout'] and row['mismatches'] == 0],
                      actual_new_model_calls=0, actual_new_eda_calls=0, actual_cloud_calls=0,
                      first_prompt_or_skills_encoding_corruption_observed=any(row['signals']['user_unicode_replacement_chars'] or row['signals']['system_unicode_replacement_chars'] for row in public),
                      diagram_evidence_status=no_missing_image_claim, all_C_samples=public,
                      independent_validation_qualified=False, adoption=False,
                      limits=['This rebinds completed historical raw archive to its original audit; it does not rerun EDA or alter the oracle.',
                              'All prompt/reply/DUT/TB/ref bodies remain private developer-review data; none are passed to a model.',
                              'Old full156 missed 3 deadlines/unconfirmed attempts and was not globally qualified.',
                              'The running FIFO61 partial results are not used; no optimization gain is inferred.'])
    save(RAW / 'REVIEW_INPUTS.json', private)
    save(ROOT / 'EVIDENCE_INSPECTION.json', result)
    print(json.dumps({key: result[key] for key in ['evidence_valid', 'manifest_files', 'verified_samples', 'C_L1_samples',
                                                  'C_L1_positive_mismatch_samples', 'C_L1_zero_mismatch_sim_timeouts',
                                                  'actual_new_model_calls', 'actual_new_eda_calls', 'first_prompt_or_skills_encoding_corruption_observed']}))


if __name__ == '__main__':
    main()
