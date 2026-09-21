"""External-only evaluation driver using the pinned official judge and scorer.

Reference and testbench are never passed to the submission process. This module
is deliberately outside the submission directory and must not be shipped with it.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
OFFICIAL = ROOT / 'official_reference'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify_upstream():
    meta = json.loads((OFFICIAL / 'UPSTREAM.json').read_text(encoding='utf-8'))
    for name, digest in meta['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('official source changed: ' + name)
    return meta['commit']


def summarize(results, expected_tasks, modes, samples):
    """Validate batch completeness before handing official judgements to score.py."""
    if not expected_tasks or len(set(expected_tasks)) != len(expected_tasks):
        raise ValueError('expected tasks must be nonempty and unique')
    score = module('official_score', OFFICIAL / 'selftest/score.py')
    coefficients = {0: 0., 1: .2, 2: .7, 3: 1.}
    by_mode = {}
    expected_files = set()
    for mode in modes:
        by_task = {}
        for tid in expected_tasks:
            records = []
            for sample in range(samples):
                name = f'{mode}.{tid}.s{sample}.json'
                expected_files.add(name)
                item = json.loads((Path(results)/name).read_text(encoding='utf-8'))
                if item.get('task_id') != tid:
                    raise ValueError('task identity mismatch')
                if not item.get('tool_error') and (item.get('level') not in coefficients or
                        item.get('coefficient') != coefficients[item['level']]):
                    raise ValueError('official L0-L3 judgement required; legacy booleans are not scores')
                records.append(item)
            by_task[tid] = records
        by_mode[mode] = score.summarize(by_task)
    if {p.name for p in Path(results).glob('*.json')} != expected_files:
        raise ValueError('unexpected results: use a separate experiment directory')
    return {'scoring_source': 'pinned official selftest/score.py summarize()',
            'modes': by_mode, 'samples_requested': samples,
            'five_sample_protocol': samples == 5,
            'diagnostic_note': 'Upstream pass@5 field is best-of-available; only a five-sample run is pass@5 protocol.',
            'formal_total_score': None,
            'limits': 'Gain threshold, cost baseline, final time budget and engineering score are not established here.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tasks', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--samples', type=int, default=5)
    ap.add_argument('--reference', action='store_true', help='only validate evaluator fixtures; no model calls')
    ap.add_argument('--deadline', type=float, required=True, help='local trial budget, not an official announced limit')
    args = ap.parse_args()
    if os.name != 'posix':
        ap.error('Official judge targets Linux/WSL; do not report native Windows results as official validation')
    if args.samples not in range(1, 6) or args.deadline <= 0:
        ap.error('samples must be 1..5 and deadline positive')
    commit = verify_upstream()
    # Fail before any model call if tools are unavailable or not the required version.
    for name in ('xvlog', 'xelab', 'xsim', 'vivado'):
        if not shutil.which(name):
            ap.error(name + ' missing; source Vivado 2026.1 settings64.sh first')
    with tempfile.TemporaryDirectory(dir=os.environ.get('EDA_TMP')) as td:
        version = subprocess.check_output(['vivado', '-version'], cwd=td, timeout=30, text=True)
    if '2026.1' not in version:
        ap.error('Vivado 2026.1 required')
    tasks = sorted(args.tasks.resolve().glob('*/task.json'))
    if not tasks:
        ap.error('no task.json found')
    ids = [json.loads(p.read_text(encoding='utf-8'))['task_id'] for p in tasks]
    if len(set(ids)) != len(ids) or any(not isinstance(t, str) or not t or
            any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in t) for t in ids):
        ap.error('task IDs must be unique ASCII letters/digits/underscore/hyphen')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = out/'results'
    results.mkdir()
    modes = ['reference'] if args.reference else ['agent', 'baseline']
    meta = dict(upstream_commit=commit, samples=args.samples, task_ids=ids, modes=modes,
                local_deadline_s=args.deadline, complete=False, started_at=time.time(),
                model=os.environ.get('MODEL_NAME'), vivado_version=version.strip(),
                input_sha256={str(p.relative_to(args.tasks.resolve())): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in args.tasks.resolve().rglob('*') if p.is_file()},
                submission_sha256={str(p.relative_to(ROOT/'submission')): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in (ROOT/'submission').rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    def save():
        (out/'experiment.json').write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    save()
    runtime = module('submission_runtime', ROOT/'submission/runtime.py')
    # No service calls for --reference. For actual runs require one explicitly named shared model.
    if not args.reference and (not os.environ.get('MODEL_NAME') or os.environ['MODEL_NAME'] not in runtime.models()):
        raise ValueError('MODEL_NAME must match the shared model service')
    for path, tid in zip(tasks, ids):
        for sample in range(args.samples):
            for mode in modes:
                dst = out/mode/tid/f's{sample}'
                if mode == 'reference':
                    dst.mkdir(parents=True)
                    task_meta = json.loads(path.read_text(encoding='utf-8'))
                    shutil.copyfile(path.parent/task_meta['reference'], dst/'solution.v')
                else:
                    runtime.run_job(mode, path.parent, dst, args.deadline)
                subprocess.run([sys.executable, str(OFFICIAL/'selftest/judge.py'),
                                '--task', str(path.parent), '--solution', str(dst/'solution.v'),
                                '--outdir', str(dst/'judge_logs'), '--timeout', str(args.deadline),
                                '--json', str(results/f'{mode}.{tid}.s{sample}.json')], check=True)
    report = summarize(results, ids, modes, args.samples)
    (out/'graded_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    meta['complete'] = True
    save()


if __name__ == '__main__':
    main()
