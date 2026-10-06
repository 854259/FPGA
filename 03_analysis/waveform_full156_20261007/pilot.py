"""Fixed312 solver outputs, original judge, strict independently recomputed routes."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import metrics
import request_proof

ROOT = Path(__file__).resolve().parent
UPSTREAM_SPEC_SHA = '3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
ORIGINAL_JUDGE_SHA = '5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen(kit):
    spec = json.loads((ROOT/'RUN_SPEC.json').read_bytes())
    assert spec['schema'] == 'waveform_first_request_full156_frozen_v1'
    for n, h in spec['source_hashes'].items():
        assert sha(ROOT/n) == h, n
    assert sha(ROOT/'upstream/RUN_SPEC.json') == UPSTREAM_SPEC_SHA
    assert sha(ROOT/'upstream/official_eval_guarded.py') == ORIGINAL_JUDGE_SHA
    factor = load('table_exact_source_factor', ROOT/'factor_proof.py')
    assert factor.verify(ROOT) == json.loads((ROOT/'SOURCE_FACTOR_PROOF.json').read_bytes())
    for n, h in spec['dependency_hashes'].items():
        assert sha(Path(spec['dependencies_cloud'])/n) == h, n
    inputs = json.loads((ROOT/'INPUT_MANIFEST.json').read_bytes())
    assert inputs == json.loads((ROOT/'upstream/INPUT_MANIFEST.json').read_bytes())
    preparation = load('table_original_task_membership', ROOT/'preparation_inputs.py')
    groups = preparation.validate_kit(ROOT, kit)
    assert all(spec[key] == value for key, value in groups.items())
    for n, h in inputs['input_sha256'].items():
        assert sha(kit/'bench/tasks_veval'/n) == h, n
    for n, h in inputs['official_sha256'].items():
        assert sha(kit/'official_reference'/n) == h, n
    assert spec['task_ids'] == metrics.TASKS and spec['arms'] == metrics.ARMS
    assert spec['target_tasks'] == metrics.TARGETS
    assert spec['guard_tasks'] == metrics.GUARDS and spec['abstention_tasks'] == metrics.ABSTENTIONS
    assert spec['solve_deadline_s'] == 300 and spec['judge_timeout_s'] == 300
    assert spec['judge_supervisor_timeout_s'] == 360 and spec['stage_timeout_s'] == 43200
    assert spec['expected_samples'] == 312 and spec['max_actual_model_requests'] == 624
    return spec


def judge(args):
    spec = frozen(args.kit)
    args.out.mkdir(parents=True, exist_ok=False)
    evaluator = load('table_original_external_judge', ROOT/'upstream/official_eval_guarded.py')
    evaluator.OFFICIAL = args.kit/'official_reference'
    verdict = evaluator.judge_sample(args.kit/'bench/tasks_veval'/args.task, args.solution,
                                    args.out, args.out/'verdict.json', spec['judge_timeout_s'])
    assert not verdict.get('tool_error') and verdict['task_id'] == args.task and verdict['judge_evidence_complete']
    save(args.out/'bound_verdict.json', dict(solution_sha256=sha(args.solution),
                                           verdict_sha256=sha(args.out/'verdict.json'), verdict=verdict))


def generation_binding(worker, source, arm, journal, spec, deadline=False):
    original={n:(source/n).read_bytes() for n in ('prompt.txt','interface.txt') if (source/n).exists()}
    assert 'prompt.txt' in original
    generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text(encoding='utf-8')
    repair=(ROOT/'package/skill/rtl-feedback-repair/SKILL.md').read_text(encoding='utf-8')
    proof=request_proof.verify(worker,original['prompt.txt'].decode(),original.get('interface.txt',b'').decode(),
        arm,spec['model'],generation,repair,allow_unconfirmed=deadline)
    assert len(journal)==proof['actual_model_requests']
    assert (worker/'prompt_only/interface.txt').exists()==('interface.txt' in original)
    assert not (worker/'emission').exists() and not (worker/'native_receipts').exists()
    if not deadline:
        wr=json.loads((worker/'worker_result.json').read_bytes())
        assert wr['complete'] and wr['arm']==arm and wr['actual_model_requests']==wr['requests']==len(journal)
        assert wr['solution_sha256']==sha(worker/'solution.v') and proof['all_responses_confirmed']
    return request_proof.binding(proof)


def publish(report):
    # Only this experiment's status; shared primary STATUS/SNAPSHOT are untouched.
    save(ROOT/'STAGE_STATUS.json', dict(observed_at_epoch=time.time(), experiment=str(ROOT),
         completed_samples=len(report['rows']), expected_samples=312,
         actual_model_requests=report['actual_model_requests'], complete=report['complete'],
         audit_pending=True, adoption=False, new_full_score=False))


def validate_environment(tools=None, stub=None):
    tools = Path(tools or '/workspace/AMD/2026.1/Vivado/bin').resolve()
    stub = Path(stub or '/workspace/team/udev-stub').resolve()
    assert Path(os.environ.get('VIVADO_BIN', '')).resolve() == tools
    assert str(stub) in os.environ.get('LD_LIBRARY_PATH', '').split(os.pathsep) and stub.is_dir()
    assert int(os.environ.get('RTL_REPAIRS', '1')) == 1
    assert int(os.environ.get('RTL_MAX_TOKENS', '8192')) == 8192
    checked = {}
    for name in ['xvlog', 'xelab', 'xsim', 'vivado']:
        found = shutil.which(name)
        assert found and Path(found).resolve() == (tools/name).resolve() and os.access(found, os.X_OK)
        checked[name] = dict(path=str(Path(found).resolve()), sha256=sha(found))
    return dict(verified=True, tools=checked, vivado_bin=str(tools), udev_stub=str(stub),
                compiler_env={k: os.environ.get(k) for k in ['PATH', 'VIVADO_BIN', 'LD_LIBRARY_PATH']},
                udev_files={p.relative_to(stub).as_posix(): sha(p) for p in stub.rglob('*') if p.is_file()},
                model_calls=0, eda_calls=0)


def verify_protected_sources(out, index):
    protected = load('table_readonly_protected_sources', ROOT/'protected_sources.py')
    binding = json.loads((ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json').read_bytes())
    verified = protected.check(binding)
    folder = out/'protected_source_checks'
    folder.mkdir(exist_ok=True)
    save(folder/(str(index).zfill(3)+'.json'), dict(index=index, **verified))


def main(args):
    assert sys.version_info[:2] == (3, 12) and sys.dont_write_bytecode
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    environment = validate_environment()
    spec = frozen(args.kit)
    assert environment['tools'] == spec['compiler_tools'] and environment['compiler_env'] == spec['compiler_env'] and environment['udev_files'] == spec['udev_files']
    paired = load('table_original_owned', Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO = ROOT
    paired.INHERITED_ORACLE = Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check, args.kit, first=True)
    out = ROOT/'results'
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    save(out/'ENVIRONMENT_PREFLIGHT.json', environment)
    report = dict(schema='waveform_first_request_full156_measurement_v1', complete=False, passed=False,
                  spec_sha256=sha(ROOT/'RUN_SPEC.json'), rows=[], actual_model_requests=0,
                  first_generation_replayed=False, adoption=False, new_full_score=False,
                  scope='156 fixed development tasks, 312 fresh model solver outputs; only supported first user prompt observation; original phase-P/judge/budget; no independent/five/full-score claim')
    save(out/'summary.json', report)
    publish(report)
    protection_index = 0
    def gate():
        nonlocal protection_index
        frozen(args.kit)
        paired.check_resource(args.resource_check, args.kit)
        verify_protected_sources(out, protection_index)
        protection_index += 1
        assert shutil.disk_usage(ROOT).free >= spec['minimum_disk_free_bytes']
        assert time.monotonic()-started < spec['stage_timeout_s']-60
    try:
        for task, arm in metrics.order(spec['task_ids']):
            assert not (ROOT/'STOP_AFTER_CURRENT').exists(), 'Boundary stop requested'
            gate()
            sample = out/'samples'/arm/task
            sample.mkdir(parents=True, exist_ok=False)
            argv = [sys.executable, '-B', str(ROOT/'worker.py'), '--out', str(sample/'worker'),
                    '--task', task, '--arm', arm, '--kit', str(args.kit), '--resource-check', str(args.resource_check)]
            command = paired.owned_command(argv, ROOT, sample/'worker.log', spec['solve_deadline_s'])
            command['argv'] = argv
            save(sample/'worker_command.json', command)
            assert not command['launch_error'] and not command['remaining_live_group']
            assert command['timeout'] or command['returncode'] == 0
            if command['timeout']:
                until = time.monotonic()+120
                while True:
                    try:
                        paired.model_idle('http://127.0.0.1:8000/v1', spec['model'])
                        break
                    except RuntimeError:
                        assert time.monotonic() < until, 'Model request did not drain'
                        time.sleep(2)
            journal = json.loads((sample/'worker/requests.json').read_bytes())
            report['actual_model_requests'] += len(journal)
            assert report['actual_model_requests'] <= spec['max_actual_model_requests']
            # Persist attempts before route validation so an invalid/partial
            # candidate never disappears from the recorded invocation cost.
            save(out/'summary.json', report)
            binding = generation_binding(sample/'worker', args.kit/'bench/tasks_veval'/task, arm, journal, spec, command['timeout'])
            gate()
            argv = [sys.executable, '-B', str(ROOT/'pilot.py'), 'judge', '--task', task,
                    '--solution', str(sample/'worker/solution.v'), '--out', str(sample/'judge'), '--kit', str(args.kit)]
            judged = paired.owned_command(argv, ROOT, sample/'judge.log', 360)
            judged['argv'] = argv
            save(sample/'judge_command.json', judged)
            assert judged['returncode'] == 0 and not judged['timeout'] and not judged['launch_error'] and not judged['remaining_live_group']
            bound = json.loads((sample/'judge/bound_verdict.json').read_bytes())
            row = dict(task=task, arm=arm, solve_deadline_reached=command['timeout'],
                       solve_elapsed_s=command['elapsed_s'], actual_model_requests=len(journal),
                       received_model_responses=sum(r['response_received'] for r in journal),
                       solution_sha256=bound['solution_sha256'], verdict_sha256=bound['verdict_sha256'],
                       verdict=bound['verdict'], **binding)
            save(sample/'row.json', row)
            report['rows'].append(row)
            save(out/'summary.json', report)
            publish(report)
        gate()
        scorer = load('table_original_official_score', args.kit/'official_reference/selftest/score.py')
        report.update(complete=True, passed=True, **metrics.aggregate(report['rows'], spec['task_ids'], scorer))
    except BaseException as error:
        report['error'] = type(error).__name__+': '+str(error)
    finally:
        report['elapsed_s'] = time.monotonic()-started
        save(out/'summary.json', report)
        publish(report)
    sys.path.insert(0, '/workspace/team/tools/task-fifo-20261004')
    import activity
    activity.append(Path('/workspace/team/activity/fpga_owner'), 'conclusions',
                    'waveform-first-request-stage:'+spec['identity'],
                    '波形观察首请求312输出阶段结束；实际模型调用逐条保留；终态原证据审计前不发布提分或全量资格，不部署。',
                    {k: v for k, v in report.items() if k != 'rows'})
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['stage', 'judge'])
    p.add_argument('--kit', required=True, type=Path)
    p.add_argument('--resource-check', type=Path)
    p.add_argument('--task')
    p.add_argument('--solution', type=Path)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    raise SystemExit(main(args) if args.phase == 'stage' else judge(args))
