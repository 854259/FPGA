"""Seal a cleaned failed solve for diagnostic traversal, never as a graded success."""
import hashlib
import json
import os
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
    assert command['timeout'] is True and command['launch_error'] is None
    assert type(command['returncode']) is int and command['returncode'] < 0
    assert command['remaining_live_group'] == []
    assert 'SIGKILL' in command['group_signals']
    assert 'solve/requests.json' in files
    requests = json.loads((folder/'solve/requests.json').read_bytes())
    assert isinstance(requests, list) and 1 <= len(requests) <= min(2, row['reserved_calls'])
    assert [r['index'] for r in requests] == list(range(len(requests)))
    assert all(type(r['response_received']) is bool for r in requests)
    log = Path(command['log']).resolve()
    assert log.is_relative_to(folder) and sha(log) == command['log_sha256']
    assert log.stat().st_size == command['log_bytes']
    return receipt, files


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
         public_publish_allowed=False, inspection=inspection))
    assert verify_failed_seal(folder, row, plan_sha256) == receipt
    return inspection
