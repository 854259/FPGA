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
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
OFFICIAL = ROOT / 'official_reference'

# The pinned judge always runs veval-judge with --quiet. Its outer log can be
# empty even when the real tool logs exist under <work>/w/. Preserve those logs
# without changing pinned scoring. An L2 result is a review signal, not proof of
# an external kill: Prob005's historical trigger was not directly witnessed.
JUDGE_WORK_LOGS = 'judge_work_logs'
COPY_EVIDENCE = (
    'verdict.json',
    'dut.sv',
    'w/judge.log',
    'w/synth/synth.log',
    'w/synth/synth.json',
    'w/synth/vivado.log',
)


def _keep_judge_evidence(work: Path, dst: Path) -> list:
    """Copy bounded tool evidence from our own scratch; surface copy failures."""
    copied = []
    for rel in COPY_EVIDENCE:
        src = work / rel
        if not src.is_file():
            continue
        if not src.resolve().is_relative_to(work.resolve()):
            raise ValueError('judge evidence escapes owned work directory: ' + rel)
        out = dst / rel.replace('/', '_')
        shutil.copyfile(src, out)
        copied.append(out.name)
    return copied


def judge_sample(task: Path, solution: Path, dst: Path, verdict_path: Path,
                 deadline: float) -> dict:
    """Run the pinned judge and preserve evidence before deleting owned scratch.

    judge.py supports SELFTEST_TMP and creates judge_<task>_<pid> below it;
    SELFTEST_JUDGE_WORK_DIR is not a supported variable. Never locate or clean
    shared /tmp entries. Empty answers legitimately create no tool workdir.
    Unexpected adapter failures stop the run rather than becoming an L0 or a
    success. The original official JSON is saved before adding metadata.
    """
    task, solution = Path(task).resolve(), Path(solution).resolve()
    expected_task = json.loads((task / 'task.json').read_text(encoding='utf-8'))['task_id']
    nonempty = bool(solution.read_text(encoding='utf-8').strip())
    if nonempty:
        missing_tools = [name for name in ('xvlog', 'xelab', 'xsim', 'vivado')
                         if shutil.which(name) is None]
        if missing_tools:
            raise RuntimeError('judge environment: executable unavailable on PATH: ' + ', '.join(missing_tools))
    dst, verdict_path = Path(dst).resolve(), Path(verdict_path).resolve()
    if verdict_path.exists():
        raise FileExistsError('refusing to reuse judge verdict: ' + str(verdict_path))
    evidence = dst / JUDGE_WORK_LOGS
    evidence.mkdir(exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix='judge-scratch-', dir=dst)).resolve()
    env = dict(os.environ, SELFTEST_KEEP_WORK='1', SELFTEST_TMP=str(scratch))
    receipt = {'judge_rc': None, 'evidence': {}, 'errors': []}
    work = None
    verdict = None
    archive_ok = True
    try:
        proc = subprocess.run(
            [sys.executable, str(OFFICIAL / 'selftest/judge.py'),
             '--task', str(task), '--solution', str(solution),
             '--outdir', str(dst / 'judge_logs'), '--timeout', str(deadline),
             '--json', str(verdict_path)],
            env=env, capture_output=True, text=True, errors='replace')
        receipt['judge_rc'] = proc.returncode
        (evidence / 'adapter.stdout.log').write_text(proc.stdout or '', encoding='utf-8')
        (evidence / 'adapter.stderr.log').write_text(proc.stderr or '', encoding='utf-8')
    except Exception as exc:
        receipt['errors'].append('judge invocation: ' + repr(exc))
    finally:
        # Only directories within the fresh, unique scratch belong to this call.
        works = list(scratch.glob('judge_*'))
        if len(works) > 1:
            archive_ok = False
            receipt['errors'].append('multiple judge workdirs in owned scratch')
        elif works:
            work = works[0]
            if not work.is_dir() or not work.resolve().is_relative_to(scratch):
                archive_ok = False
                receipt['errors'].append('invalid judge workdir in owned scratch')
            else:
                try:
                    _keep_judge_evidence(work, evidence)
                except (OSError, ValueError) as exc:
                    archive_ok = False
                    receipt['errors'].append('evidence copy: ' + repr(exc))
        try:
            raw = verdict_path.read_bytes()
            (evidence / 'adapter_verdict.json').write_bytes(raw)
            verdict = json.loads(raw)
            if not isinstance(verdict, dict):
                raise ValueError('judge verdict must be an object')
        except (OSError, ValueError) as exc:
            receipt['errors'].append('judge verdict: ' + repr(exc))
            verdict = None

        if receipt['judge_rc'] != 0:
            receipt['errors'].append('judge did not exit successfully')
        if verdict is not None and str(verdict.get('tool_error', '')).startswith('判定超时'):
            # The pinned wrapper times out only its direct veval child; EDA
            # grandchildren can outlive it. Keep their cwd and stop the batch
            # for owned-process inspection instead of deleting active work.
            archive_ok = False
            receipt['errors'].append('judge timeout; inspect owned EDA processes before cleanup')
        # A normal nonempty candidate must have real compiler/simulator logs.
        # Synth logs are required only when that stage was actually attempted.
        if verdict is not None and not verdict.get('tool_error'):
            level = verdict.get('level')
            if (verdict.get('task_id') != expected_task or type(level) is not int
                    or level not in (0, 1, 2, 3)
                    or verdict.get('coefficient') != {0: 0., 1: .2, 2: .7, 3: 1.}[level]):
                receipt['errors'].append('invalid official verdict identity or coefficient')
            if nonempty:
                required = ['verdict.json', 'w_judge.log']
                if (verdict.get('stages') or {}).get('simulate'):
                    required.append('w_synth_synth.log')
                missing = [name for name in required
                           if not (evidence / name).is_file() or (evidence / name).stat().st_size == 0]
                if missing:
                    archive_ok = False
                    receipt['errors'].append('missing tool evidence: ' + ', '.join(missing))
        for path in sorted(evidence.iterdir()):
            if path.is_file():
                raw = path.read_bytes()
                receipt['evidence'][path.name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                if path.name == 'w_judge.log' and re.search(
                        r'^\[[^\]\r\n]+\] 可执行文件不存在[：:]\s*\S+',
                        raw.decode('utf-8', errors='replace'), re.M):
                    receipt['errors'].append('judge environment: tool launch failed in pinned judge')
        if archive_ok:
            try:
                shutil.rmtree(scratch)
            except OSError as exc:
                receipt['errors'].append('owned scratch cleanup: ' + repr(exc))
        receipt['scratch_retained'] = str(scratch) if scratch.exists() else None
        (dst / 'judge_receipt.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if receipt['errors']:
        raise RuntimeError('judge evidence/adapter failure; see ' + str(dst / 'judge_receipt.json'))
    kept = [name for name in receipt['evidence'] if name not in
            ('adapter.stdout.log', 'adapter.stderr.log', 'adapter_verdict.json')]
    verdict['judge_rc'] = receipt['judge_rc']
    verdict['judge_evidence'] = kept
    verdict['judge_log_bytes'] = sum(receipt['evidence'][name]['bytes'] for name in kept if name.endswith('.log'))
    verdict['judge_evidence_complete'] = True
    stages = verdict.get('stages') or {}
    verdict['suspected_silent_degradation'] = bool(
        not verdict.get('tool_error') and stages.get('simulate') and not stages.get('synth'))
    # work_dir in the raw official verdict records the original location; the
    # receipt and this metadata identify the durable copy after scratch cleanup.
    verdict['judge_receipt'] = str(dst / 'judge_receipt.json')
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return verdict



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
    suspects = []
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
                stages = item.get('stages') or {}
                if (not item.get('tool_error') and stages.get('simulate')
                        and not stages.get('synth')):
                    # 无法事后区分"综合确实失败"与"综合被中断"：原始 synth.log 是否
                    # 保留、判定是否记录了非零返回码，决定这条记录能不能当结论用。
                    suspects.append(dict(
                        mode=mode, task=tid, sample=sample,
                        judge_rc=item.get('judge_rc'),
                        judge_log_bytes=item.get('judge_log_bytes'),
                        evidence=item.get('judge_evidence') or []))
                records.append(item)
            by_task[tid] = records
        by_mode[mode] = score.summarize(by_task)
    if {p.name for p in Path(results).glob('*.json')} != expected_files:
        raise ValueError('unexpected results: use a separate experiment directory')
    return {'scoring_source': 'pinned official selftest/score.py summarize()',
            'modes': by_mode, 'samples_requested': samples,
            'five_sample_protocol': samples == 5,
            'diagnostic_note': 'Upstream pass@5 field is best-of-available; only a five-sample run is pass@5 protocol.',
            'silent_degradation_suspects': suspects,
            'silent_degradation_note': (
                'Samples listed here passed simulation but did not pass synthesis with no tool_error. '
                'Review the preserved raw stage verdict and tool logs; L2 alone does not prove '
                'external interruption. judge_rc is the adapter exit code, not the synthesis exit '
                'code. For Prob005, re-judging passed 4/4 and a controlled interruption reproduced '
                'the failure shape; the historical trigger was not directly witnessed.'
                if suspects else 'None: no simulation-pass/synthesis-fail sample without tool_error.'),
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
    runtime = module('submission_runtime', ROOT/'submission/agent/runtime.py')
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
                judge_sample(path.parent, dst / 'solution.v', dst,
                             results / f'{mode}.{tid}.s{sample}.json', args.deadline)
    report = summarize(results, ids, modes, args.samples)
    (out/'graded_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    meta['complete'] = True
    save()


if __name__ == '__main__':
    main()
