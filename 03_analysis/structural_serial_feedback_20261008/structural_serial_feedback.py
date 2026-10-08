"""Add candidate-derived scalar-driver facts to measured serial failures only."""
import hashlib
import json
from pathlib import Path

import baseline_worker
import serial_feedback
import structural_driver_feedback

SCHEMA = 'candidate_scalar_driver_append_v1'
DELIMITER = '\n\nCandidate source structure diagnostics:\n'


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def expected_record(code, serial_text, analyzer_sha256):
    """Pure reconstruction: no model, EDA, source edit or historical-task lookup."""
    assert isinstance(code, str) and isinstance(serial_text, str) and serial_text
    analysis = structural_driver_feedback.analyze(code)
    assert analysis['status'] in ('abstain', 'supported_no_conflict', 'source_conflict_needs_review')
    assert analysis['source_sha256'] == text_sha(code)
    assert analysis['compile_failure_proven'] is False and analysis['semantic_edits'] == 0
    diagnostics = analysis['diagnostics']
    assert isinstance(diagnostics, list)
    structural_text = structural_driver_feedback.render_feedback(analysis)
    assert isinstance(structural_text, str)
    if analysis['status'] == 'source_conflict_needs_review':
        assert diagnostics and structural_text
    else:
        assert not diagnostics and not structural_text
    combined = serial_text + DELIMITER + structural_text if structural_text else serial_text
    record = dict(schema=SCHEMA, source_sha256=text_sha(code),
                  analyzer_sha256=analyzer_sha256, analysis=analysis,
                  structural_feedback=structural_text,
                  structural_feedback_sha256=text_sha(structural_text),
                  serial_feedback_sha256=text_sha(serial_text),
                  combined_feedback_sha256=text_sha(combined),
                  candidate_edited=False, extra_model_calls=0, extra_eda_calls=0)
    return record, combined


def append_feedback(code, out, attempt, serial_text, root):
    assert type(attempt) is int and attempt in (0, 1)
    root, out = Path(root).resolve(), Path(out).resolve()
    # Every attachment belongs to the identical source checked by serial.check.
    serial_folder = out / ('serial_check_' + str(attempt))
    assert (serial_folder / 'input.sv').read_text(encoding='utf-8') == code
    assert (serial_folder / 'feedback.txt').read_text(encoding='utf-8') == serial_text
    analyzer = root / 'structural_driver_feedback.py'
    spec = json.loads((root / 'RUN_SPEC.json').read_text(encoding='utf-8'))
    analyzer_sha = baseline_worker.sha(analyzer)
    assert spec['source_hashes']['structural_driver_feedback.py'] == analyzer_sha
    record, combined = expected_record(code, serial_text, analyzer_sha)
    folder = out / ('structural_check_' + str(attempt))
    folder.mkdir(exist_ok=False)
    baseline_worker.save(folder / 'RESULT.json', record)
    (folder / 'combined_feedback.txt').write_text(combined, encoding='utf-8', newline='\n')
    return combined


def run_worker(base, args, paired):
    """A/C and P share the original serial check; only P appends source facts."""
    if args.arm not in ('C', 'P'):
        raise ValueError('structural comparison requires original serial C/P control')
    original = base.functional_feedback

    def feedback(prompt, code, out, attempt, tools, task, candidate=False):
        measured = serial_feedback.check(prompt, code, out, attempt, tools, task, base.ROOT)
        if measured is None:
            return original(prompt, code, out, attempt, tools, task, candidate=candidate)
        if args.arm == 'P' and measured:
            return append_feedback(code, out, attempt, measured, base.ROOT)
        return measured

    base.functional_feedback = feedback
    try:
        return base.run_worker(args, paired)
    finally:
        base.functional_feedback = original
