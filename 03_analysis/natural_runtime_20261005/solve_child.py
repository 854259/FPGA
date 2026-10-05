"""Frozen future child entry. No standalone grant, model or EDA admission."""
from pathlib import Path
import sys

import runtime
import supervisor


def load_public_payload(path, expected_sha):
    path = runtime._own_path(path)
    if runtime.file_sha(path) != expected_sha:
        raise PermissionError('prepared public-task bytes changed')
    payload = runtime.read_json(path)
    if set(payload) != {'schema', 'arm', 'run_root', 'record', 'generation', 'repair'} or payload['schema'] != 'natural_supervised_public_task_v1':
        raise ValueError('unexpected supervised public task schema')
    projected = runtime.supervised_payload(payload['record'], payload['arm'], payload['run_root'], payload['generation'], payload['repair'])
    if projected != payload or set(payload['record']) != {'input', 'output'}:
        raise ValueError('child accepts exact public task projection only')
    return payload


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise ValueError('child needs one owned public task and its exact digest')
    grant = supervisor.child_admission(runtime.ROOT)
    supervisor.verify_child_admission(grant, runtime.ROOT)
    payload = load_public_payload(*args)
    result = runtime.solve_real(payload['record'], payload['arm'], payload['run_root'],
                                payload['generation'], payload['repair'], supervisor_grant=grant)
    # A successful child exit only establishes complete engineering execution.
    # Functional quality remains the separate original runner/judge's decision.
    return 0 if result.get('complete') is True and result.get('accounting_complete') is True and result.get('status') in {'real_candidate_checks_pass', 'real_candidate_checks_fail'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
