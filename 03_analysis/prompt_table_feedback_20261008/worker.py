"""AMD-only model worker with optional prompt-table feedback, max one repair."""
import argparse
import ctypes
import json
from pathlib import Path
import sys

import baseline_worker
import table_feedback


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('out', 'kit', 'resource-check'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--arm', choices=('C', 'P'), required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    root = Path(__file__).resolve().parent
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    # A copied worker alone is not an execution admission.
    assert spec.get('model_generated_rtl_only') is True
    assert spec['source_hashes'].get('worker.py') == baseline_worker.sha(__file__)
    assert spec['source_hashes'].get('table_feedback.py') == baseline_worker.sha(root / 'table_feedback.py')
    for name, digest in spec['source_hashes'].items():
        assert baseline_worker.sha(root / name) == digest
    for name, digest in spec['dependency_hashes'].items():
        assert baseline_worker.sha(Path(spec['dependencies_cloud']) / name) == digest
    paired = baseline_worker.load('table_feedback_owned', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    table_feedback.run_worker(baseline_worker, args, paired)
