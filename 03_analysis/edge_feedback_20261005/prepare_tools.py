"""Pure integration source freeze; this is not an actual model experiment."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

R = Path(__file__).resolve().parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    assert not (R/'TOOLS_SPEC.json').exists()
    calibration = json.loads((R/'CALIBRATION_AUDIT.json').read_text(encoding='utf-8'))
    assert calibration['evidence_valid'] and calibration['controls_valid'] and calibration['natural_hypothesis_matched']
    assert calibration['probe_executions'] == 26 and calibration['synth_executions'] == 6
    assert calibration['archive_sha256'] == 'e035cfa3a12c22326ce200ffa65fa6e0dfcf7f36a17119eab9e32b9b07c45724'
    copy = json.loads((R/'COPY_RECEIPT.json').read_text(encoding='utf-8'))
    for n, h in copy['original_copied_sha256'].items():
        if n != 'worker.py':
            assert sha(R/n) == h, n
    assert sha(R/'package/agent/map_runtime.py') == '2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    assert not (R/'package/agent/d_runtime.py').exists() and not (R/'context.py').exists()
    exposure = json.loads((R/'ARCHIVED_EXPOSURE.json').read_text(encoding='utf-8'))
    assert exposure['unchanged_dispatch_tasks'] == 154 and len(exposure['newly_supported_tasks']) == 2
    run = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_fresh', 'test_edge_integration', 'test_boundaries', '-v'],
                         cwd=R, capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 0, run.stdout+run.stderr
    assert 'Ran 20 tests' in run.stderr
    names = [p.relative_to(R).as_posix() for p in R.rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and
             (p.suffix == '.py' or p.is_relative_to(R/'package'))]
    names += ['COPY_RECEIPT.json', 'CALIBRATION_AUDIT.json', 'INPUT_MANIFEST.json',
              'ARCHIVED_EXPOSURE.json', 'UNFROZEN_FAILURES.json',
              'raw_evidence/test_fixtures/priority.txt', 'raw_evidence/test_fixtures/shift.txt']
    # Historical failed test source is evidence, not executable frozen tooling.
    names = sorted(set(n for n in names if not n.startswith('raw_evidence/') or '/test_fixtures/' in n))
    spec = dict(schema='edge_feedback_pure_tools_v1',
                frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                cloud_root='/workspace/team/runs/fpga_owner/edge_feedback_tools_20261005_v1',
                source_hashes={n:sha(R/n) for n in names},
                runtime_both_arms='package/agent/map_runtime.py',
                next_actual_trial_required=True, actual_run_spec_created=False,
                actual_fifo_submitted=False, model_calls=0, eda_calls=0, adoption=False,
                limits=['Fake transport/compiler/probe tests validate integration boundaries, not RTL semantic correctness or model gains.',
                        'Existing native edge calibration remains exact; no new DUT answer, task-ID routing, reference or official TB in generation.',
                        'Only E prompt-only contract/feedback dispatch expands; C runtime, skills, extractor, native compiler and original one-repair limit stay fixed.',
                        'Original successful declaration patch still returns without a new probe; not widened without exposure evidence.',
                        'Real stage requires its own frozen spec, raw-chain auditor and whole-task FIFO. No independent/five/offline32GB/adoption claim.'])
    save(R/'TOOLS_SPEC.json', spec)
    save(R/'PREPARATION_RECEIPT.json', dict(tools_spec_sha256=sha(R/'TOOLS_SPEC.json'),
         assets=len(names), local_python=sys.version.split()[0], tests_passed=20,
         actual_model_calls=0, actual_eda_calls=0, output=run.stdout+run.stderr))
    archive = R/'raw_evidence/preparation.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for n in names+['TOOLS_SPEC.json', 'PREPARATION_RECEIPT.json']:
            z.write(R/n, n)
    save(R/'PREPARATION_ARCHIVE.json', dict(archive_sha256=sha(archive),
         tools_spec_sha256=sha(R/'TOOLS_SPEC.json'), assets=len(names)))
    print(json.dumps(dict(assets=len(names), tests_passed=20, tools_spec_sha256=sha(R/'TOOLS_SPEC.json'),
                         archive_sha256=sha(archive), actual_model_calls=0, actual_eda_calls=0)))
