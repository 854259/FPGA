"""One original-budget review after unsupported checks, atop the table worker."""
import copy
import hashlib
import json
from pathlib import Path

import semantic_review


def run_worker(base, table, args, paired):
    """C and P both inherit the complete-table candidate; P alone adds review."""
    if args.arm not in ('C', 'P'):
        raise ValueError('semantic review comparison requires C or P')
    inherited = copy.copy(args)
    inherited.arm = 'P'
    def run_inherited():
        result = table.run_worker(base, inherited, paired)
        out = args.out.resolve()
        complete = json.loads((out / 'worker_result.json').read_text(encoding='utf-8'))
        assert complete['complete'] and complete['arm'] == 'P' and 1 <= complete['requests'] <= 2
        base.save(out / 'semantic_factor_run.json', dict(
            outer_arm=args.arm, inherited_worker_arm='P', complete_table_worker_preserved=True,
            max_requests=2, repairs=1, first_request_unchanged=True,
            semantic_feedback_sha256=base.sha(__file__),
            semantic_review_sha256=base.sha(semantic_review.__file__),
            requests=complete['requests'], solution_sha256=complete['solution_sha256']))
        return result
    if args.arm == 'C':
        return run_inherited()
    original = base.functional_feedback

    def feedback(prompt, code, out, attempt, tools, task, candidate=False):
        # This runs only after the inherited complete-table checker abstains.
        # Its exception and existing measured feedback propagate unchanged.
        measured = original(prompt, code, out, attempt, tools, task, candidate=candidate)
        if measured or not candidate:
            return measured
        contract = base.edge_dispatch.parse(prompt)
        status = contract['status']
        if status not in ('supported', 'skip', 'abstain'):
            raise RuntimeError('unrecognized original checker status')
        source = Path(out) / 'prompt_only'
        raw_prompt = (source / 'prompt.txt').read_text(encoding='utf-8')
        interface_path = source / 'interface.txt'
        interface = interface_path.read_text(encoding='utf-8') if interface_path.is_file() else ''
        combined = raw_prompt + ('\n\nInterface:\n' + interface if interface.strip() else '')
        if prompt != combined:
            raise RuntimeError('review source differs from the original worker prompt')
        # The inherited worker calls map_feedback only after actual compile rc0.
        # Do not trust caller intent when no retained successful compile exists.
        journal = Path(out) / 'compile_journal.json'
        compiles = json.loads(journal.read_text(encoding='utf-8'))
        digest = hashlib.sha256(code.encode()).hexdigest()
        if not compiles or compiles[-1]['returncode'] != 0 or any(
                compiles[-1][name] != digest for name in ('source_before_sha256', 'source_after_sha256')):
            raise RuntimeError('review requires a retained compile-pass for this candidate')
        receipt = semantic_review.hint(raw_prompt, interface, status, True, attempt)
        receipt.update(candidate_sha256=digest, original_feedback_empty=True,
                       complete_table_worker_preserved=True, outer_arm='P')
        folder = Path(out) / 'semantic_review_receipts'
        folder.mkdir(exist_ok=True)
        target = folder / (str(attempt) + '.json')
        if target.exists():
            raise RuntimeError('review callback already recorded for this round')
        base.save(target, receipt)
        return receipt['text']

    base.functional_feedback = feedback
    try:
        return run_inherited()
    finally:
        base.functional_feedback = original


def bind(base, inherited_worker, solve, selected_arm):
    """Reuse the original table reply/trace binder for both inherited-P arms."""
    assert selected_arm in ('A', 'P')
    out = Path(solve).resolve()
    bound = inherited_worker.bind(out, 'P')
    record = json.loads((out / 'semantic_factor_run.json').read_text(encoding='utf-8'))
    assert record['outer_arm'] == ('C' if selected_arm == 'A' else 'P')
    assert record['inherited_worker_arm'] == 'P' and record['complete_table_worker_preserved']
    assert record['max_requests'] == 2 and record['repairs'] == 1 and record['first_request_unchanged']
    assert record['requests'] == bound['actual_model_responses']
    assert record['solution_sha256'] == bound['solution_sha256']
    assert record['semantic_feedback_sha256'] == base.sha(__file__)
    assert record['semantic_review_sha256'] == base.sha(semantic_review.__file__)
    receipts = sorted((out / 'semantic_review_receipts').glob('*.json'))
    if selected_arm == 'A':
        assert not receipts
    source = out / 'prompt_only'
    prompt = (source / 'prompt.txt').read_text(encoding='utf-8')
    interface_path = source / 'interface.txt'
    interface = interface_path.read_text(encoding='utf-8') if interface_path.is_file() else ''
    combined = prompt + ('\n\nInterface:\n' + interface if interface.strip() else '')
    status = base.edge_dispatch.parse(combined)['status']
    trace = [json.loads(line) for line in (out / 'trace.jsonl').read_text().splitlines()]
    compiles = json.loads((out / 'compile_journal.json').read_text())
    extract = base.load('semantic_binding_extract', base.ROOT / 'package/baseline.py')
    for path in receipts:
        attempt = int(path.stem)
        assert attempt in (0, 1)
        receipt = json.loads(path.read_text(encoding='utf-8'))
        body = json.loads((out / 'requests' / str(attempt) / 'response.json').read_text())
        code = extract.extract(body['choices'][0]['message'].get('content') or '', 'rtl')
        assert receipt['candidate_sha256'] == hashlib.sha256(code.encode()).hexdigest()
        assert receipt['contract_status'] == status
        assert any(row['returncode'] == 0 and row['source_before_sha256'] == row['source_after_sha256']
                   == receipt['candidate_sha256'] for row in compiles)
        assert any(e.get('tool') == 'lint' and e.get('round') == attempt and e.get('rc') == 0 for e in trace)
        expected = semantic_review.hint(prompt, interface, status, True, attempt)
        assert all(receipt[k] == v for k, v in expected.items())
        assert receipt['original_feedback_empty'] and receipt['complete_table_worker_preserved']
        assert receipt['outer_arm'] == 'P'
        if receipt['status'] == 'review_requested':
            assert attempt == 0 and record['requests'] == 2
            assert any(e.get('tool') == 'map_feedback' and e.get('round') == 0
                       and e.get('excerpt') == receipt['text'] for e in trace)
    for event in trace:
        if event.get('tool') != 'map_feedback':
            continue
        attempt = event['round']
        expected = semantic_review.hint(prompt, interface, status, True, attempt)
        if expected['text'] and event.get('excerpt') == expected['text']:
            assert (out / 'semantic_review_receipts' / (str(attempt) + '.json')).is_file()
    return dict(bound, outer_arm=selected_arm, inherited_complete_table_candidate=True,
                review_requests=sum(json.loads(p.read_text())['status'] == 'review_requested' for p in receipts))
