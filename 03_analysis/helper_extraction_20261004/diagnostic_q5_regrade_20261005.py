"""Score Q5's frozen fourteen outputs after restoring the established EDA environment.

No generation, retry, candidate edit, shared environment edit or original-result overwrite.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(a):
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    sys.dont_write_bytecode = True
    frozen = a.original / 'FROZEN_RECOVERY_INPUTS.json'
    assert sha(frozen) == 'e3a015d69271445e28ac01b2b4f3247ae93e6fb6746dc1a7eee1b902c92afb01'
    binding = json.loads(frozen.read_text())
    assert all(sha(a.original / n) == h for n, h in binding.items())
    source = a.original / 'source'
    paired = load('q5_regrade_supervisor', source / '03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    paired.check_resource(a.resource_check, a.kit, first=True)
    assert sha(a.kit / 'official_eval.py') == '53d1d4ff661ca6c3e27bc1d20a2328815dc39e281abc3a93757099b6e60bf797'
    assert sha(a.compat / 'libudev.so.1') == '3a2d6266ccf18909d3ebccbf21e8125ce985359319fecc6c8172aeabf13ecf87'
    os.environ.update(PATH=str(a.vivado / 'bin') + os.pathsep + os.environ['PATH'],
                      LD_LIBRARY_PATH=str(a.compat), XILINX_VIVADO=str(a.vivado),
                      XILINXD_LICENSE_FILE=str(a.license), PYTHONDONTWRITEBYTECODE='1')
    judge = load('q5_regrade_official', a.kit / 'official_eval.py')
    assert judge.verify_upstream() == 'afd135e7ba5f6ec4c6d77e7c927c894327537801'
    assert sha(a.archive) == '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    report = json.loads((a.original / 'results/summary.json').read_text())
    assert report['actual_attempts'] == report['actual_responses'] == 14
    assert len(report['rows']) == 7 and all(r['paired_requests_verified'] for r in report['rows'])
    report.update(complete=False, valid=False, error=None, generation_stage_elapsed_s=report['elapsed_s'],
                  regrade_new_model_calls=0, regrade_driver_sha256=sha(__file__),
                  frozen_input_manifest_sha256=sha(frozen), original_failure_preserved=True,
                  compatibility_library_sha256=sha(a.compat / 'libudev.so.1'))
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    try:
        with zipfile.ZipFile(a.archive) as z:
            manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
            for row in report['rows']:
                task = a.out / 'judge_tasks' / row['task']; task.mkdir(parents=True)
                prefix = 'kit/bench/tasks_veval/' + row['task'] + '/'
                for name in z.namelist():
                    if not name.startswith(prefix) or name.endswith('/'):
                        continue
                    data = z.read(name); item = manifest[name]
                    assert hashlib.sha256(data).hexdigest() == (item['sha256'] if isinstance(item, dict) else item)
                    rel = Path(name[len(prefix):]); assert '..' not in rel.parts and not rel.is_absolute()
                    target = task / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                for arm in ('A', 'C'):
                    assert time.monotonic() - tick < 1700
                    paired.check_resource(a.resource_check, a.kit)
                    dst = a.out / 'grades' / row['task'] / arm; dst.mkdir(parents=True)
                    solution = a.original / 'results/workers' / row['task'] / arm / 'solution.v'
                    assert sha(solution) == row['arms'][arm]['receipt']['solution_sha256']
                    verdict = judge.judge_sample(task, solution, dst, dst / 'verdict.json', 90)
                    row['arms'][arm]['verdict'] = verdict
                    assert not verdict.get('tool_error') and not verdict.get('suspected_silent_degradation'), 'grading environment/synthesis requires inspection'
                    logs = '\n'.join(p.read_text(errors='replace') for p in dst.rglob('*.log'))
                    assert re.search(r'(?:INFO|ERROR): \[VRFC ', logs)
                    assert not re.search(r'可执行文件不存在|command not found|No such file or directory|license checkout failed|segfault|Abnormal program termination', logs, re.I)
                    if row is report['rows'][0] and arm == 'A':
                        assert verdict['level'] == 3, 'same-byte environment recovery not confirmed'
                print(json.dumps(dict(task=row['task'], levels={k:v['verdict']['level'] for k,v in row['arms'].items()})), flush=True)
                (a.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        repairs = sum(r['arms']['A']['verdict']['level'] < 3 and r['arms']['C']['verdict']['level'] == 3 for r in report['rows'])
        regressions = sum(r['arms']['A']['verdict']['level'] == 3 and r['arms']['C']['verdict']['level'] < 3 for r in report['rows'])
        continuation = {a:sum(r['arms'][a]['receipt']['elapsed_s'] for r in report['rows']) for a in ('A', 'C')}
        initial = sum(r['archived_initial_model_s'] for r in report['rows'])
        reconstructed = {a:initial + continuation[a] for a in ('A', 'C')}
        ratio = reconstructed['C'] / reconstructed['A']
        report.update(complete=True, valid=True, repairs=repairs, regressions=regressions,
                      unchanged_functional=7-repairs-regressions, continuation_worker_s=continuation,
                      archived_initial_model_s=initial, reconstructed_worker_s=reconstructed,
                      reconstructed_cost_ratio=ratio, deployed=False,
                      candidate_eligible_for_further_research=repairs > 0 and regressions == 0 and ratio <= 1.10)
        assert all(sha(a.original / n) == h for n, h in binding.items())
        report['all_frozen_inputs_unchanged'] = True
        paired.check_resource(a.resource_check, a.kit)
        paired.model_idle('http://127.0.0.1:8000/v1', 'Qwen3.6-27B-Q4_K_M')
    except BaseException as exc:
        report.update(complete=False, valid=False, error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        report['grading_recovery_elapsed_s'] = time.monotonic() - tick
        report['combined_stage_elapsed_s'] = report['generation_stage_elapsed_s'] + report['grading_recovery_elapsed_s']
        (a.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k:v for k,v in report.items() if k != 'rows'}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('original', 'archive', 'out', 'resource-check', 'kit', 'compat', 'vivado', 'license'):
        p.add_argument('--' + name, required=True, type=Path)
    run(p.parse_args())
