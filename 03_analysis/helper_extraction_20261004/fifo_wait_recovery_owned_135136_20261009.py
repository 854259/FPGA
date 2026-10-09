"""AMD-only owner binding to PR199's unchanged, once-only FIFO recovery core."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path('/workspace/team/runs/fpga_owner/fifo_unstarted_wait_recovery135136_20261009_v1')
FIFO = '/workspace/team/tools/task-fifo-20261004/task_fifo.py'
FIFO_SHA = '4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'
CORE_SHA = '692305058c4499ffbe599ada3badb316f866e918da5a78df348e58ac146ca302'
BINDING = '/workspace/team/activity/fpga_owner/artifacts/fifo135136-wait-recovery-bindings-20261009-v1/BINDINGS.json'
BINDING_SHA = '24808da83ad841b0cf6d182226b70eabbfa9c1bb35200aa007c9428eca4ba430'
EXPIRES = 1791554400  # 2026-10-09 22:00 Beijing; no indefinite authorization.
JOBS = {
    135: '/workspace/team/runs/fpga_owner/structural_serial_feedback_comparison2x5_20261008_v1',
    136: '/workspace/team/runs/fpga_owner/lemmings_feedback_controls_20261008_v1',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan, out):
    """Bind scope and every source before loading the shared implementation."""
    out = Path(out).resolve()
    core_path = out / 'fifo_wait_recovery_20261009.py'
    if (sys.platform != 'linux' or out != ROOT
            or plan['schema'] != 'owned_fifo_wait_recovery_135_136_v1'
            or plan['fifo_root'] != '/workspace/team/task_fifo'
            or plan['fifo_source'] != FIFO
            or plan['expires_unix'] != EXPIRES
            or not 0 < EXPIRES - time.time() < 86400
            or [e['queued']['ticket'] for e in plan['entries']] != [135, 136]
            or plan['binding_path'] != BINDING
            or plan['sources'] != {FIFO: FIFO_SHA, str(core_path): CORE_SHA,
                                   str(Path(__file__).resolve()): sha(__file__),
                                   BINDING: BINDING_SHA}):
        raise RuntimeError('owner recovery scope/source/window mismatch')
    for path, digest in plan['sources'].items():
        if sha(path) != digest:
            raise RuntimeError('recovery source changed: ' + path)
    original = json.loads(Path(BINDING).read_bytes())
    if original['schema'] != 'owned135136_wait_recovery_bindings_v1':
        raise RuntimeError('original owner binding schema changed')
    contracts = {c['ticket']: c for c in original['contracts']}
    for entry in plan['entries']:
        number = entry['queued']['ticket']
        binding = contracts[number]
        job = Path(JOBS[number])
        argv = ['/usr/bin/python3', '-B', FIFO, '--root', plan['fifo_root'],
                '_run', '--ticket', str(number)]
        monitor = {k: binding['original_monitor'][k]
                   for k in ('pid', 'starttime', 'command_sha256')}
        old_argv = [x.decode() for x in bytes.fromhex(
            binding['original_monitor_cmdline_hex']).split(b'\0') if x]
        absent = [str(Path(plan['fifo_root']) / ('task_%08d.log' % number)),
                  str(job / 'guard'), str(job / ('queue' if number == 135 else 'native_results'))]
        if (entry['queued'] != binding['original_ticket']
                or entry['queued']['state'] != 'queued'
                or entry['queued']['adopted_process'] is not None
                or entry['queued']['cwd'] != str(job)
                or entry['queued']['completion_json'] != str(job / 'guard/status.json')
                or entry['monitor'] != monitor or entry['monitor_argv'] != argv
                or old_argv != argv or entry['must_be_absent'] != absent):
            raise RuntimeError('original owner ticket binding mismatch')
        frozen = dict(binding['frozen_top_level_hashes'])
        for path, digest in frozen.items():
            if sha(path) != digest:
                raise RuntimeError('original frozen manifest changed')
        if number == 135:
            sources = json.loads((job / 'RUN_SPEC.json').read_bytes())['source_hashes']
        else:
            sources = json.loads((job / 'SOURCE_MANIFEST.json').read_bytes())
        for name, digest in sources.items():
            path = (job / name).resolve()
            if not path.is_relative_to(job) or path == job:
                raise RuntimeError('frozen source outside original job')
            frozen[str(path)] = digest
        if entry['frozen_files'] != frozen:
            raise RuntimeError('incomplete original frozen source binding')
        for path, digest in frozen.items():
            if sha(path) != digest:
                raise RuntimeError('original frozen source changed: ' + path)
    spec = importlib.util.spec_from_file_location('owned_shared_fifo_recovery', core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    if args.plan.resolve() != ROOT / 'PLAN.json' or sha(args.plan) != args.plan_sha256:
        raise RuntimeError('exact frozen owner plan required')
    plan = json.loads(args.plan.read_bytes())
    core = validate_plan(plan, ROOT)
    core.write_new(ROOT / 'WATCH_INTENT.json', dict(plan_sha256=args.plan_sha256,
                   started_unix=time.time(), pid=core.os.getpid()))
    pending, outcomes = list(plan['entries']), {}
    try:
        while pending and time.time() < EXPIRES:
            for entry in list(pending):
                result = core.recover(plan, entry, ROOT)
                if result['outcome'] not in ('waiting_original', 'waiting_original_retirement'):
                    outcomes[str(entry['queued']['ticket'])] = result
                    pending.remove(entry)
            if pending:
                time.sleep(min(30, max(0, EXPIRES - time.time())))
        if pending:
            raise TimeoutError('watch window ended; remaining original tickets untouched')
    except BaseException as exc:
        core.write_new(ROOT / 'WATCH_FAILURE.json', dict(error=type(exc).__name__ + ': ' + str(exc),
                       outcomes=outcomes, pending=[e['queued']['ticket'] for e in pending]))
        raise
    core.write_new(ROOT / 'WATCH_RESULT.json', dict(complete=True, outcomes=outcomes,
                                                  ended_unix=time.time()))


if __name__ == '__main__':
    main()
