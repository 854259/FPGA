"""AMD-only one-shot FIFO admission of the already frozen output-completion comparison.

Keep this admission entry outside the frozen source root. An ambiguous submit
must be inspected through its existing intent/ticket; this entry never retries.
It neither generates a design nor edits the frozen PLAN or RUN_SPEC.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('/workspace/team/runs/fpga_owner/output_completion_comparison5x5_20261010_v2')
KIT = Path('/workspace/team/tasks/autodl-rtl-kit/project')
FIFO = Path('/workspace/team/tools/task-fifo-20261004/task_fifo.py')
FIFO_SHA = '4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'
GUARD_SHA = 'fdd22d547cab6884b071044a7a1f26f847d8937618a55a201838ff10f77ff9d9'
MODEL_PID = 2013333
MODEL_START = '823869819'
MODEL_COMMAND_SHA = '2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'
MODEL_NAME = 'Qwen3.6-27B-Q4_K_M'
OWNER = 'fpga-owner-output-completion-comparison5x5-20261010-v2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def birth(pid):
    proc = Path('/proc') / str(pid)
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, starttime=fields[19], state=fields[0],
                command_sha256=sha(proc / 'cmdline'))


def submit(args):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ROOT.is_dir() and ROOT.resolve() == ROOT and not ROOT.is_symlink()
    assert not Path(__file__).resolve().is_relative_to(ROOT), 'Keep admission code outside frozen sources'
    paths = {'plan': ROOT / 'PLAN.json', 'spec': ROOT / 'RUN_SPEC.json',
             'preparation': ROOT / 'PREPARATION_RESULT.json'}
    expected = dict(plan=args.plan_sha256, spec=args.spec_sha256,
                    preparation=args.preparation_result_sha256)
    for key, path in paths.items():
        assert len(expected[key]) == 64 and set(expected[key]) <= set('0123456789abcdef')
        assert not path.is_symlink() and sha(path) == expected[key], key
    plan, spec, preparation = (read(paths[key]) for key in ('plan', 'spec', 'preparation'))
    assert preparation['complete'] is True and preparation['prepared'] is True
    assert preparation['submitted'] is False and preparation['sources_held'] is True
    assert (preparation['model_calls'], preparation['eda_calls'], preparation['fifo_calls']) == (0, 0, 0)
    assert (preparation['tasks'], preparation['outputs'], preparation['max_calls']) == (5, 75, 125)
    assert preparation['spec_sha256'] == expected['spec'] and preparation['plan_sha256'] == expected['plan']
    assert preparation['execution_authorized'] is True and plan['execution_authorized'] is True
    assert spec['schema'] == 'output_completion_first_request_model_comparison_v1'
    assert spec['cloud_root'] == str(ROOT) and spec['identity'] == ROOT.name
    assert spec['model_generated_rtl_only'] is True and plan['model_generated_rtl_only'] is True
    assert plan['sources']['root'] == str(ROOT) and plan['sources']['model_feedback'] is True
    assert 'generation_arms' not in plan['sources'] and 'finite_judge' not in plan
    assert plan['model'] == spec['model'] == MODEL_NAME and plan['kit'] == str(KIT)
    assert (plan['samples'], plan['unique_tasks'], len(plan['rows']), plan['max_calls'],
            plan['required_reserved_calls'], plan['wall_seconds'], plan['retries']) == (5, 5, 75, 125, 125, 43200, 0)
    assert (plan['solve_deadline_s'], plan['solve_supervisor_s'], plan['judge_supervisor_s'],
            plan['row_reservation_s']) == (300, 310, 360, 670)
    tasks = {(row['dataset'], row['task']) for row in plan['rows']}
    assert len(tasks) == 5
    assert {(row['dataset'], row['task'], row['sample'], row['arm']) for row in plan['rows']} == {
        (dataset, task, sample, arm) for dataset, task in tasks
        for sample in range(5) for arm in ('A', 'P', 'B')}
    assert all(row['reserved_calls'] == {'A': 2, 'P': 2, 'B': 1}[row['arm']] for row in plan['rows'])
    assert sum(row['reserved_calls'] for row in plan['rows']) == 125
    assert plan['formal_adoption'] is False and plan['full156'] is False and plan['full_goal_complete'] is False
    assert preparation['safety_caps'] == dict(queue_wall_s=43200, proposed_stage_cap_s=43320,
                                            proposed_guard_s=43500, proposed_fifo_slot_minutes=730)
    assert len(spec['source_hashes']) == 29
    assert spec['qualification_archive_sha256'] == 'ca199554d674d427fe23e67eeae3dc9ff855aba9d97b5070fe47d1b2220550b4'
    # Original132 is retained as failed;all already accepted successors must be terminal.
    tickets=Path('/workspace/team/task_fifo/tickets')
    assert read(tickets/'00000132.json')['state']=='failed_released_after_inspection'
    assert all(read(tickets/('%08d.json'%t))['state']=='completed' for t in (133,134,135,136))
    sources = {}
    for name, digest in spec['source_hashes'].items():
        path = ROOT / name
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert path.resolve().is_relative_to(ROOT) and not path.is_symlink()
        assert sha(path) == digest, name
        sources[str(path)] = digest
    sources[str(paths['spec'])] = expected['spec']
    assert plan['sources']['files'] == sources
    assert spec['dependencies_cloud'] == str(ROOT / 'dependencies')
    for name, digest in spec['dependency_hashes'].items():
        assert spec['source_hashes']['dependencies/' + name] == digest
    assert sha(ROOT / 'guard_wrapper.py') == GUARD_SHA
    assert sha(ROOT / 'three_arm_queue_20261005.py') == plan['scheduler_sha256']
    assert plan['official_entry'] == str(ROOT / 'official_baseline_arm_20261005.py')
    assert sha(plan['official_entry']) == plan['entry_sha256']
    for path, digest in plan['execution_files'].items():
        assert sources[path] == digest
    for name, digest in plan['official_files'].items():
        assert sha(KIT / 'submission' / name) == digest
    assert sha(FIFO) == FIFO_SHA
    assert shutil.disk_usage(ROOT).free >= 2 * 1024**3
    assert args.last_read_comment_id > 0
    assert 0 <= time.time() - args.coordination_observed_epoch < 120
    ticket_dir = Path('/workspace/team/task_fifo/tickets')
    for path in ticket_dir.glob('*.json'):
        assert read(path).get('cwd') != str(ROOT), 'Existing same-root ticket: inspect it, never resubmit'
    for name in ('SUBMISSION_INTENT.json', 'SUBMISSION.json', 'guard', 'queue', 'MONITOR_BIRTH.json'):
        assert not (ROOT / name).exists(), 'Existing execution evidence: preserve and inspect'
    model = birth(MODEL_PID)
    assert model['state'] not in ('Z', 'X')
    assert model['starttime'] == MODEL_START and model['command_sha256'] == MODEL_COMMAND_SHA
    argv = ['/usr/bin/python3', '-B', str(FIFO), 'submit',
            '--task-name', 'output_completion_comparison5x5_v2', '--cwd', str(ROOT),
            '--completion-json', str(ROOT / 'guard/status.json'), '--slot-owner-prefix', OWNER, '--',
            '/usr/bin/env',
            'PATH=/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'VIVADO_BIN=/workspace/AMD/2026.1/Vivado/bin', 'LD_LIBRARY_PATH=/workspace/team/udev-stub',
            'PYTHONUTF8=1', '/usr/bin/flock', '-n', '/workspace/team/.gpu.lock',
            '/usr/bin/python3', '-B', str(ROOT / 'guard_wrapper.py'), '--kit', str(KIT),
            '--model-pid', str(MODEL_PID), '--model-name', MODEL_NAME, '--owner', OWNER,
            '--guard-out', str(ROOT / 'guard'), '--minimum-free-gib', '2',
            '--slot-minutes', '730', '--stage-timeout-s', '43500', '--',
            '/usr/bin/python3', '-B', str(ROOT / 'three_arm_queue_20261005.py'),
            '--plan', str(paths['plan']), '--plan-sha256', expected['plan'],
            '--out', str(ROOT / 'queue'), '--resource-check', '{resource_check}']
    intent = dict(at_epoch=time.time(), frozen_sha256=expected, command=argv, model_identity=model,
                  submit_entry=str(Path(__file__).resolve()), submit_entry_sha256=sha(__file__),
                  last_read_comment_id=args.last_read_comment_id,
                  coordination_observed_epoch=args.coordination_observed_epoch, retries=0,
                  meaning='Reviewed whole-task FIFO admission only; no score or completion claim')
    save(ROOT / 'SUBMISSION_INTENT.json', intent)
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        (ROOT / 'SUBMIT.stdout').write_bytes(error.stdout or b'')
        (ROOT / 'SUBMIT.stderr').write_bytes(error.stderr or b'')
        raise RuntimeError('Unknown submission outcome: inspect same root/ticket; do not retry') from error
    (ROOT / 'SUBMIT.stdout').write_bytes(completed.stdout)
    (ROOT / 'SUBMIT.stderr').write_bytes(completed.stderr)
    assert completed.returncode == 0, 'Failed/unknown submission: read existing handle only'
    result = json.loads(completed.stdout)
    result.update(frozen_sha256=expected, control_only=False, outputs=75, max_reserved_model_calls=125,
                  scores_available=False, retry=False, whole_task_fifo=True)
    save(ROOT / 'SUBMISSION.json', result)
    try:
        monitor = birth(result['monitor_pid'])
    except FileNotFoundError:
        monitor = dict(pid=result['monitor_pid'], observed_live=False,
                       instruction='Read ticket/guard; monitor already absent, never resubmit')
    save(ROOT / 'MONITOR_BIRTH.json', monitor)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--spec-sha256', required=True)
    parser.add_argument('--preparation-result-sha256', required=True)
    parser.add_argument('--last-read-comment-id', type=int, required=True)
    parser.add_argument('--coordination-observed-epoch', type=float, required=True)
    submit(parser.parse_args())
