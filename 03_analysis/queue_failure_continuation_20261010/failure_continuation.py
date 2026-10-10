"""Seal a cleaned failed solve for diagnostic traversal, never as a graded success."""
import hashlib
import json
import os
import math
from pathlib import Path
import zipfile

SCHEMA = 'inspected_failed_solver_row_v1'
RESERVED = {'TERMINAL.json', 'STARTED.json', 'FAILED_EVIDENCE.zip', 'FAILED_SEALED.json',
            'FAILED_EVIDENCE.zip.pending', 'FAILED_SEALED.json.pending', 'SEALED.json', 'EVIDENCE.zip'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original_files(folder, row, plan_sha256):
    folder = Path(folder).resolve()
    started, terminal = folder/'STARTED.json', folder/'TERMINAL.json'
    assert started.is_file() and terminal.is_file()
    assert not started.is_symlink() and not terminal.is_symlink()
    start = json.loads(started.read_bytes())
    receipt = json.loads(terminal.read_bytes())
    assert start['row'] == row and start['plan_sha256'] == plan_sha256
    assert receipt['complete'] is False and receipt.get('error') == 'Solver supervision failure'
    assert receipt['actual_calls'] is None and receipt['unconfirmed_calls'] is None
    assert receipt.get('level') is None and receipt.get('coefficient') is None
    assert receipt['files'] and not set(receipt['files']) & (RESERVED - {'STARTED.json'})
    files = dict(receipt['files'])
    if 'STARTED.json' in files:
        assert files['STARTED.json'] == sha(started)
    files.update({'STARTED.json': sha(started), 'TERMINAL.json': sha(terminal)})
    for name, digest in files.items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts and str(relative) == name
        path = folder/name
        assert path.resolve().is_relative_to(folder) and not path.is_symlink()
        assert path.is_file() and sha(path) == digest
    assert 'SOLVE_COMMAND.json' in files
    command = json.loads((folder/'SOLVE_COMMAND.json').read_bytes())
    # The original owned supervisor returns only after wait/reap and exact-group cleanup.
    # This narrowly handles the actual132 timeout class; launch/judge/manifest faults stay closed.
    assert command['launch_error'] is None
    assert type(command['returncode']) is int
    assert command['remaining_live_group'] == []
    if command['timeout'] is True:
        assert command['returncode'] < 0 and 'SIGKILL' in command['group_signals']
    else:
        assert command['timeout'] is False and command['returncode'] == 1
        assert 'solve/SHARED_BUDGET_EXIT.json' in files
        budget = json.loads((folder/'solve/SHARED_BUDGET_EXIT.json').read_bytes())
        assert budget['schema'] in ('shared_worker_budget_expired_v1', 'shared_worker_budget_expired_v2') and budget['budget_s'] == 300
        assert type(budget['elapsed_s']) in (int, float) and math.isfinite(budget['elapsed_s'])
        if budget['schema'] == 'shared_worker_budget_expired_v2':
            # Child bootstrap is part of the parent's budget but can precede
            # the supervisor's own stopwatch. Compare the bound parent clock,
            # rather than incorrectly requiring the shorter command >=300.
            assert 'SOLVE_CLOCK.json' in files
            clock = json.loads((folder/'SOLVE_CLOCK.json').read_bytes())
            assert clock['schema'] == 'parent_solve_clock_v1' and clock['budget_s'] == 300
            assert clock['command_sha256'] == files['SOLVE_COMMAND.json']
            for key in ('started_monotonic', 'returned_monotonic', 'elapsed_s'):
                assert type(clock[key]) in (int, float) and math.isfinite(clock[key])
            origin, end = clock['started_monotonic'], clock['returned_monotonic']
            assert 0 <= origin <= end and clock['elapsed_s'] == end-origin
            assert budget['started_monotonic'] == origin
            observed = budget['observed_monotonic']
            assert type(observed) in (int, float) and math.isfinite(observed)
            assert origin <= observed <= end and budget['elapsed_s'] == observed-origin
            assert 300 <= budget['elapsed_s'] <= clock['elapsed_s']
        else:
            assert 'SOLVE_CLOCK.json' not in files
            assert 300 <= budget['elapsed_s'] <= command['elapsed_s']
        assert budget['requests_sha256'] == files['solve/requests.json']
        assert budget['complete'] is False and budget['score_eligible'] is False
        assert budget['grade'] is None and budget['actual_calls'] is None and budget['unconfirmed_calls'] is None
        if 'solve/compile_journal.json' in files:
            compiles = json.loads((folder/'solve/compile_journal.json').read_bytes())
            assert isinstance(compiles, list)
            assert all(c['launch_error'] is None and not c['remaining_live_group'] for c in compiles)
    assert 'solve/requests.json' in files
    requests = json.loads((folder/'solve/requests.json').read_bytes())
    # With the parent's clock, child bootstrap can exhaust the budget before
    # any dispatch. A bound budget-exit receipt is required for this zero case;
    # an external timeout without requests remains outside this narrow route.
    minimum_requests = 0 if command['timeout'] is False else 1
    assert isinstance(requests, list) and minimum_requests <= len(requests) <= min(2, row['reserved_calls'])
    assert [r['index'] for r in requests] == list(range(len(requests)))
    assert all(type(r['response_received']) is bool for r in requests)
    log = Path(command['log']).resolve()
    assert log.is_relative_to(folder) and sha(log) == command['log_sha256']
    assert log.stat().st_size == command['log_bytes']
    return receipt, files


def failure_basis(folder):
    command = json.loads((Path(folder)/'SOLVE_COMMAND.json').read_bytes())
    return 'owned_solver_timeout' if command['timeout'] else 'owned_worker_budget_expired'


def verify_failed_seal(folder, row, plan_sha256):
    folder = Path(folder).resolve()
    receipt, files = original_files(folder, row, plan_sha256)
    marker, archive = folder/'FAILED_SEALED.json', folder/'FAILED_EVIDENCE.zip'
    assert not marker.is_symlink() and not archive.is_symlink()
    assert not (folder/'FAILED_EVIDENCE.zip.pending').exists()
    assert not (folder/'FAILED_SEALED.json.pending').exists()
    seal = json.loads(marker.read_bytes())
    assert seal['schema'] == SCHEMA and seal['row_key'] == row['key']
    assert seal['plan_sha256'] == plan_sha256 and seal['terminal_sha256'] == files['TERMINAL.json']
    assert seal['reserved_calls'] == row['reserved_calls']
    assert seal['grade'] is None and seal['actual_calls'] is None and seal['score_eligible'] is False
    assert seal['inspection']['owned_solver_reaped_and_group_clear'] is True
    assert seal['inspection']['processing_slots'] == 0
    assert seal['inspection']['health_status'] == 'ok'
    assert seal.get('failure_basis', 'owned_solver_timeout') == failure_basis(folder)
    assert sha(archive) == seal['archive_sha256']
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert len(names) == len(set(names)) and set(names) == set(files)
        for name, digest in files.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest
    return receipt


def seal_failed_row(folder, row, plan, plan_sha256, resource_check, resource, save):
    assert plan.get('allow_inspected_solver_failure') is True
    assert plan['sources']['root'] and Path(folder).resolve().is_relative_to(Path(plan['sources']['root']).resolve())
    folder = Path(folder).resolve()
    assert not (folder/'SEALED.json').exists() and not (folder/'EVIDENCE.zip').exists()
    assert not (folder/'FAILED_SEALED.json').exists() and not (folder/'FAILED_EVIDENCE.zip').exists()
    receipt, files = original_files(folder, row, plan_sha256)
    basis = failure_basis(folder)
    if basis == 'owned_worker_budget_expired':
        assert plan.get('allow_shared_budget_failure') is True
        root = Path(plan['sources']['root']).resolve()
        budget = json.loads((folder/'solve/SHARED_BUDGET_EXIT.json').read_bytes())
        for name, key in [('shared_budget.py', 'budget_source_sha256'), ('baseline_worker.py', 'worker_source_sha256')]:
            source = root/name
            assert sha(source) == budget[key] == plan['sources']['files'][str(source)]
        if budget['schema'] == 'shared_worker_budget_expired_v2':
            clock = json.loads((folder/'SOLVE_CLOCK.json').read_bytes())
            assert clock['scheduler_sha256'] == plan['scheduler_sha256']
    # check_resource binds the original model/resource admission; telemetry is read-only.
    admission = resource.check_resource(resource_check, Path(plan['kit']))
    assert admission['llm_base_url'] == 'http://127.0.0.1:8000/v1'
    idle = resource.model_idle(admission['llm_base_url'], admission['model_name'])
    assert idle['model'] == admission['model_name'] and idle['health_status'] == 'ok'
    assert idle['processing_slots'] == 0 and idle['slot_count'] >= 1
    assert original_files(folder, row, plan_sha256) == (receipt, files)
    pending, archive = folder/'FAILED_EVIDENCE.zip.pending', folder/'FAILED_EVIDENCE.zip'
    with pending.open('xb') as handle:
        with zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in sorted(files):
                z.write(folder/name, name)
        handle.flush()
        os.fsync(handle.fileno())
    pending.replace(archive)
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    inspection = dict(owned_solver_reaped_and_group_clear=True, health_status=idle['health_status'],
                      processing_slots=idle['processing_slots'], slot_count=idle['slot_count'], model=idle['model'])
    save(folder/'FAILED_SEALED.json', dict(schema=SCHEMA, row_key=row['key'], plan_sha256=plan_sha256,
         terminal_sha256=files['TERMINAL.json'], archive_sha256=sha(archive), reserved_calls=row['reserved_calls'],
         grade=None, actual_calls=None, unconfirmed_calls=None, score_eligible=False,
         public_publish_allowed=False, inspection=inspection, failure_basis=basis))
    assert verify_failed_seal(folder, row, plan_sha256) == receipt
    return inspection
