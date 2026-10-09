"""Original-budget semantic review on top of the frozen complete-table worker."""
import argparse
import ctypes
import json
from pathlib import Path
import sys

import baseline_worker
import table_feedback
import table_worker_original
import semantic_feedback


def bind(solve, arm):
    return semantic_feedback.bind(baseline_worker, table_worker_original, solve, arm)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'bind':
        p = argparse.ArgumentParser()
        p.add_argument('--solve', type=Path, required=True)
        p.add_argument('--arm', choices=('A', 'P'), required=True)
        a = p.parse_args(sys.argv[2:])
        print(json.dumps(bind(a.solve, a.arm)))
        sys.exit(0)
    p = argparse.ArgumentParser()
    for name in ('out', 'kit', 'resource-check'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--arm', choices=('C', 'P'), required=True)
    a = p.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    root = Path(__file__).resolve().parent
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    assert spec.get('model_generated_rtl_only') is True
    for name, digest in spec['source_hashes'].items():
        assert baseline_worker.sha(root / name) == digest
    for name, digest in spec['dependency_hashes'].items():
        assert baseline_worker.sha(Path(spec['dependencies_cloud']) / name) == digest
    paired = baseline_worker.load('semantic_feedback_owned', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    semantic_feedback.run_worker(baseline_worker, table_feedback, a, paired)
