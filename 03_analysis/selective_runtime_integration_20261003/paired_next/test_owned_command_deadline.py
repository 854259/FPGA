#!/usr/bin/env python3
"""AMD-only CPU regression: real subprocesses, no model/EDA/network access.

Run once per preserved output directory, with -B, under an external owned guard.
The startup case also accepts the old source, preserving its expected failure.
These short controls do not qualify the production queue or model cancellation.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def identity(pid):
    try:
        p = Path('/proc') / str(pid)
        fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, starttime=fields[19], state=fields[0],
                    pgid=int(fields[2]), sid=int(fields[3]))
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--case', choices=['startup', 'all'], required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    args.out.mkdir(exist_ok=False)

    def deny_network(event, arguments):
        if event in ('socket.connect', 'socket.bind'):
            raise AssertionError('network is prohibited in this CPU qualification')
    sys.addaudithook(deny_network)
    spec = importlib.util.spec_from_file_location('paired_under_test', args.source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_popen = subprocess.Popen
    records = []
    cases = ['startup'] if args.case == 'startup' else [
        'startup', 'expired', 'absolute', 'success', 'parent_exit',
        'timeout_group', 'cancel', 'cancel_launch', 'invalid']
    for name in cases:
        out = args.out / name
        out.mkdir()
        record = dict(case=name, passed=False, launched=[], waits=[])
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        sender = None
        try:
            def launch(*a, **kw):
                if name in ('expired', 'invalid'):
                    raise AssertionError('expired/invalid input must not launch')
                if name == 'startup':
                    time.sleep(.30)  # Real startup cost, not a substituted clock.
                proc = original_popen(*a, **kw)
                record['launched'].append(identity(proc.pid))
                wait = proc.wait

                def observed_wait(timeout=None):
                    record['waits'].append(dict(at=time.monotonic(), timeout=timeout))
                    return wait(timeout=timeout)
                proc.wait = observed_wait
                if name == 'cancel_launch':
                    # The child exists but Popen has not returned to its caller.
                    os.kill(os.getpid(), signal.SIGTERM)
                return proc

            module.subprocess.Popen = launch
            seconds = .45 if name == 'startup' else 2.
            code = 'import time; time.sleep(.30)' if name == 'startup' else 'import time; time.sleep(.05)'
            kwargs = {}
            if name != 'startup':
                kwargs['cleanup_seconds'] = .8
            if name == 'expired':
                kwargs['deadline'] = time.monotonic() - .1
            elif name == 'absolute':
                kwargs['deadline'] = time.monotonic() + .2
                code = 'import time; time.sleep(30)'
            elif name in ('parent_exit', 'timeout_group', 'cancel', 'cancel_launch'):
                code = (
                    "import json,os,subprocess,sys,time\n"
                    "from pathlib import Path\n"
                    "p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'])\n"
                    "f=Path('/proc')/str(p.pid)/'stat'\n"
                    "v=f.read_text().rsplit(')',1)[1].split()\n"
                    "Path('descendant.json').write_text(json.dumps(dict(pid=p.pid,starttime=v[19],pgid=int(v[2]))))\n"
                    + ("time.sleep(.05)\n" if name == 'parent_exit' else "time.sleep(30)\n")
                )
                if name == 'timeout_group':
                    seconds = .3
                elif name == 'cancel':
                    def send_cancel():
                        end = time.monotonic() + 1.5
                        while time.monotonic() < end:
                            if (out / 'descendant.json').exists():
                                os.kill(os.getpid(), signal.SIGTERM)
                                return
                            time.sleep(.005)
                    sender = threading.Thread(target=send_cancel)
                    sender.start()

            started = time.monotonic()
            if name == 'invalid':
                failures = []
                for bad in (0, -1, float('inf'), float('nan'), True):
                    try:
                        module.owned_command([], out, out / 'unused.log', bad)
                    except ValueError:
                        failures.append(repr(bad))
                    else:
                        raise AssertionError('invalid duration accepted: ' + repr(bad))
                record['rejected'] = failures
            else:
                try:
                    result = module.owned_command(
                        [sys.executable, '-B', '-c', code], out, out / 'stdout.bin', seconds, **kwargs)
                    record['result'] = result
                except InterruptedError as exc:
                    record['interrupted'] = str(exc)
                    assert name in ('cancel', 'cancel_launch')
                if name in ('cancel', 'cancel_launch'):
                    assert record.get('interrupted'), 'cancellation was swallowed'
                else:
                    assert result['timeout'] == (name in ('startup', 'expired', 'absolute', 'timeout_group'))
                    assert not result['remaining_live_group']
                    assert result['launch_error'] is None
                    if name in ('success', 'parent_exit'):
                        assert result['returncode'] == 0
                    elif name == 'expired':
                        assert result['returncode'] is None and not record['launched']
                    else:
                        assert result['returncode'] == -signal.SIGKILL
                    if 'deadline_monotonic' in result:
                        cleanup = kwargs.get('cleanup_seconds', 10.)
                        assert result['cleanup_deadline_monotonic'] <= result['deadline_monotonic'] + cleanup + .000001
            record['elapsed_s'] = time.monotonic() - started
            if sender:
                sender.join()
            descendant = out / 'descendant.json'
            if descendant.exists():
                record['descendant'] = json.loads(descendant.read_text())
            births = record['launched'] + ([record['descendant']] if record.get('descendant') else [])
            record['remaining_owned'] = [now for birth in births if birth is not None
                                         for now in [identity(birth['pid'])]
                                         if now and now['starttime'] == birth['starttime']]
            assert not record['remaining_owned'], 'owned processes not reaped'
            assert all(signal.getsignal(sig) == handler for sig, handler in handlers.items())
            record['handlers_restored'] = True
            record['passed'] = True
        except BaseException as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            module.subprocess.Popen = original_popen
            if sender:
                sender.join()
            with (out / 'RESULT.json').open('x') as stream:
                json.dump(record, stream, indent=2)
                stream.write('\n')
            records.append(record)
        if not record['passed']:
            break  # Preserve the first failure; never retry inside this harness.
    summary = dict(schema='owned_deadline_cpu_regression_v1',
                   source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                   test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   passed=len(records) == len(cases) and all(r['passed'] for r in records),
                   cases=records, network='connect_and_bind_denied',
                   limitation='CPU seam only; no production queue/model/EDA qualification')
    with (args.out / 'RESULT.json').open('x') as stream:
        json.dump(summary, stream, indent=2)
        stream.write('\n')
    print(json.dumps(summary))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
