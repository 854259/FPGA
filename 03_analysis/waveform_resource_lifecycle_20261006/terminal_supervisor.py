"""Run the frozen waveform104 evidence collection/audit once, outside its sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import zipfile

PLAN_SHA = '2bb7a3f485b1bedb77c884e5be6ff712aa9a65339a11b45a9ff625e7fc206fa3'
OWNED_SHA = '9981c3a36183787d559aaed73fcfd34d36e6a7354e5da1874cf5308c6ee476c5'
OLD_CAP = '0<cap_s<=60'
NEW_CAP = '0<cap_s<=180'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def build_owned(path):
    raw = Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OWNED_SHA
    code = raw.decode('utf-8')
    assert code.count(OLD_CAP) == 1
    effective = code.replace(OLD_CAP, NEW_CAP)
    namespace = {'__name__': 'waveform104_terminal_owned', '__file__': str(path)}
    exec(compile(effective, '<waveform104-terminal-owned>', 'exec'), namespace)
    return namespace, dict(original_sha256=OWNED_SHA,
                          effective_sha256=hashlib.sha256(effective.encode()).hexdigest(),
                          substitution='one cap admission literal 60 to 180; lifecycle unchanged')


def identity(pid):
    root = Path('/proc')/str(pid)
    try:
        fields = (root/'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] in ('Z', 'X'):
            return None
        return dict(pid=pid, starttime=fields[19], exe=Path(os.readlink(root/'exe')).name,
                    command_sha256=sha(root/'cmdline'))
    except (FileNotFoundError, ProcessLookupError):
        return None


def source_check(source, plan):
    assert sha(source/'RUN_SPEC.json') == plan['spec_sha256']
    spec = read(source/'RUN_SPEC.json')
    assert len(spec['source_hashes']) == 97
    for name, expected in spec['source_hashes'].items():
        path = source/name
        assert not path.is_symlink() and sha(path) == expected, name
    assert identity(spec['model_pid']) == spec['model_identity']
    return spec


def terminal_gate(source, ticket):
    assert ticket['ticket'] == 104 and Path(ticket['cwd']) == source
    assert ticket['state'] == 'completed' and ticket['returncode'] == 0
    for key in ('runner', 'child'):
        original = ticket[key]
        current = identity(original['pid'])
        assert current is None or current['starttime'] != original['starttime'], key
    for path in (source/'results/summary.json', source/'guard/status.json'):
        result = read(path)
        assert result['complete'] is True and result['passed'] is True
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        if int(path.parent.name) in (os.getpid(), os.getppid()):
            continue
        try:
            args = path.read_bytes().split(b'\0')
        except (FileNotFoundError, ProcessLookupError):
            continue
        assert not any(a == os.fsencode(source) or a.startswith(os.fsencode(source) + b'/') for a in args), path.parent.name
        assert not (b'_run' in args and b'--ticket' in args and args[args.index(b'--ticket')+1] == b'104')


def archive_check(path, plan):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        manifest = json.loads(archive.read('ARCHIVE_MANIFEST.json'))
        assert manifest['run_spec_sha256'] == plan['spec_sha256']
        assert manifest['collector_sha256'] == plan['collector_sha256']
        assert set(names) == set(manifest['files']) | {'ARCHIVE_MANIFEST.json'}
        for name, expected in manifest['files'].items():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected, name
    return sha(path)


def completed_output(out, plan):
    receipt = read(out/'COMPLETE.json')
    assert receipt['plan_sha256'] == PLAN_SHA and receipt['passed'] is True
    assert receipt['supervisor_sha256'] == sha(__file__)
    for name, expected in receipt['files'].items():
        assert not (out/name).is_symlink() and sha(out/name) == expected, name
    assert archive_check(Path(receipt['archive']), plan) == receipt['archive_sha256']
    return receipt


def execute(preparation, ticket_path, existing_archive=None):
    started = time.monotonic()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert sha(preparation/'TERMINAL_PLAN.json') == PLAN_SHA
    plan = read(preparation/'TERMINAL_PLAN.json')
    assert (plan['max_collector_seconds'], plan['max_audit_seconds'], plan['max_total_seconds']) == (60, 180, 300)
    source, out = Path(plan['source_root']), Path(plan['out_root'])
    assert not out.is_relative_to(source)
    if out.exists():
        return completed_output(out, plan)  # Incomplete/failed output refuses a second attempt.
    source_check(source, plan)
    terminal_gate(source, read(ticket_path))
    assert sha(preparation/'RECEIPT.json') == plan['control_receipt_sha256']
    assert sha(preparation/'audit_relocated_capture.py') == plan['replacement_wrapper_sha256']
    assert sha(source/'collect_evidence.py') == plan['collector_sha256']
    owned, execution = build_owned(source/'owned_exec.py')
    if existing_archive is not None:
        archive_check(existing_archive, plan)  # Reuse bound evidence; never recollect it.
    out.mkdir(exist_ok=False)  # Atomic once-only claim, and parent exists before any fork.
    result = dict(schema='waveform104_terminal_supervisor_v1', plan_sha256=PLAN_SHA,
                  supervisor_sha256=sha(__file__), owned_execution=execution,
                  passed=False, error=None, new_model_calls=0, new_eda_calls=0,
                  archive_reused=existing_archive is not None, processes={})
    save(out/'ATTEMPT.json', result)
    save(out/'OWNER.json', identity(os.getpid()))
    def deadline(sig, frame):
        raise TimeoutError('total deadline reserve reached')
    previous = signal.signal(signal.SIGALRM, deadline)
    # owned.run has at most two five-second cleanup windows; leave 12 s reserve.
    assert time.monotonic() - started < 288
    signal.alarm(max(1, int(288 - (time.monotonic() - started))))
    try:
        archive = Path(existing_archive) if existing_archive else out/'EVIDENCE.zip'
        commands = []
        if existing_archive is None:
            commands.append(('collector', [sys.executable, '-B', str(source/'collect_evidence.py'),
                             '--root', str(source), '--guard', str(source/'guard'), '--archive', str(archive)], 60))
        commands.append(('audit', [sys.executable, '-B', str(preparation/'audit_relocated_capture.py'),
                         '--source', str(source), '--archive', str(archive), '--out', str(out/'audit')], 180))
        for name, argv, cap in commands:
            assert time.monotonic() - started + cap + 12 < 300
            record = owned['run'](argv, source, out/(name+'_process'), cap)
            result['processes'][name] = record
            assert record['normal_completion'] and record['returncode'] == 0, name
            if name == 'collector':
                archive_check(archive, plan)
        source_check(source, plan)
        audit = read(out/'audit/RESULTS.json')
        assert audit['evidence_valid'] is True and audit['spec_sha256'] == plan['spec_sha256']
        assert audit['audit_model_calls'] == audit['audit_eda_calls'] == 0
        assert audit['auditor_sha256'] == plan['replacement_wrapper_sha256']
        result.update(archive=str(archive), archive_sha256=archive_check(archive, plan), passed=True)
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        result['files'] = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
        result['elapsed_s'] = time.monotonic() - started
        result['passed'] = result['passed'] and result['elapsed_s'] < 300
        save(out/'COMPLETE.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preparation', required=True, type=Path)
    parser.add_argument('--ticket', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    result = execute(args.preparation, args.ticket, args.archive)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
