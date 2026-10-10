#!/usr/bin/env python3
"""AMD-only stage wrapper. Uses the existing slot; never manages the model."""
import argparse
import ctypes
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def identity(pid):
    root = Path('/proc') / str(pid)
    fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] in ('Z', 'X'):
        raise RuntimeError('model is not a live process')
    command = (root / 'cmdline').read_bytes()
    exe = Path(os.readlink(root / 'exe')).name
    if 'llama-server' not in exe:
        raise RuntimeError('explicit model PID is not llama-server')
    # Keep command/credentials out of logs; identity includes only its digest.
    return dict(pid=pid, starttime=fields[19], exe=exe,
                command_sha256=hashlib.sha256(command).hexdigest())


def process_record(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, starttime=fields[19], state=fields[0],
                    ppid=int(fields[1]), pgid=int(fields[2]), sid=int(fields[3]))
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(pid):
    found, todo = {}, [pid]
    while todo:
        parent = todo.pop()
        try:
            threads = list((Path('/proc') / str(parent) / 'task').iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        for thread in threads:
            try:
                children = (thread / 'children').read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for child in map(int, children):
                row = process_record(child)
                if row and child not in found:
                    found[child] = row
                    todo.append(child)
    return found


def gpu_sample(owned, model_pid, *, proc_root=Path('/proc'), drm_root=Path('/sys/class/drm')):
    """Read one non-atomic sample; deduplicate shared DRM clients, never infer zero.

    `owned` contains previously bound PID/starttime records. Device-wide values
    include other clients; they are separate from owned-client resident memory.
    Distinct clients can share buffers, so their sum is not unique physical VRAM.
    Fixture roots are used only by AMD data-boundary qualification.
    """
    sample = dict(at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  monotonic=time.monotonic(), clients=[], devices={}, errors=[],
                  complete=False, model_birth_seen=False, model_drm_client_seen=False)
    clients = {}

    def memory_bytes(value):
        if value == '0':
            return 0
        if value is None:
            return None
        words = value.split()
        if len(words) != 2 or words[1] != 'KiB' or not words[0].isdigit():
            return None
        return int(words[0]) * 1024

    for pid, expected in sorted(owned.items()):
        root = proc_root / str(pid)
        birth_seen = False
        try:
            before = (root / 'stat').read_text().rsplit(')', 1)[1].split()
            if before[19] != str(expected['starttime']) or before[0] in ('Z', 'X'):
                if pid == model_pid:
                    sample['errors'].append(dict(pid=pid, reason='model_birth_not_live'))
                continue
            birth_seen = True
            if pid == model_pid:
                sample['model_birth_seen'] = True
            pending = []
            for fd in sorted((root / 'fdinfo').iterdir()):
                try:
                    fields = dict(line.split(':', 1) for line in fd.read_text().splitlines() if ':' in line)
                    fields = {k: v.strip() for k, v in fields.items()}
                    if fields.get('drm-driver') != 'amdgpu':
                        continue
                    node = Path(os.readlink(root / 'fd' / fd.name)).name
                    device = drm_root / node / 'device'
                    pci = fields.get('drm-pdev')
                    client = fields.get('drm-client-id')
                    if (not client or not client.isdigit() or not pci or
                            device.resolve().name != pci or (device / 'vendor').read_text().strip() != '0x1002'):
                        raise ValueError('DRM client/device binding unavailable')
                    resident = memory_bytes(fields.get('drm-resident-vram'))
                    allocated = memory_bytes(fields.get('drm-memory-vram'))
                    if resident is None:
                        raise ValueError('resident VRAM unavailable or unsupported unit')
                    engines = {k: v for k, v in fields.items() if k.startswith('drm-engine-')}
                    pending.append(dict(pci_bdf=pci, client_id=client, resident_vram_bytes=resident,
                                        allocated_vram_bytes=allocated, engine_counters=engines or None,
                                        owners=[dict(pid=pid, starttime=before[19], fd=fd.name)]))
                    if pci not in sample['devices']:
                        values = {k: int((device / k).read_text().strip()) for k in
                                  ('mem_info_vram_total', 'mem_info_vram_used', 'gpu_busy_percent')}
                        if min(values.values()) < 0 or values['gpu_busy_percent'] > 100:
                            raise ValueError('invalid device telemetry')
                        sample['devices'][pci] = dict(render_or_card_node=node, **values)
                except FileNotFoundError:
                    # An owned process can close an FD during the snapshot.
                    sample['errors'].append(dict(pid=pid, fd=fd.name, reason='fd_changed_during_sample'))
                except (OSError, ValueError) as exc:
                    sample['errors'].append(dict(pid=pid, fd=fd.name, reason=str(exc)))
            after = (root / 'stat').read_text().rsplit(')', 1)[1].split()
            if after[19] != before[19] or after[0] in ('Z', 'X'):
                sample['errors'].append(dict(pid=pid, reason='birth_changed_during_sample'))
                continue
            for current in pending:
                key = (current['pci_bdf'], current['client_id'])
                if pid == model_pid:
                    sample['model_drm_client_seen'] = True
                if key not in clients:
                    clients[key] = current
                else:
                    old = clients[key]
                    old['owners'].extend(current['owners'])
                    # Same client may change between FD reads; do not sum it.
                    old['resident_vram_bytes'] = max(old['resident_vram_bytes'], current['resident_vram_bytes'])
                    allocated = [x for x in (old['allocated_vram_bytes'], current['allocated_vram_bytes']) if x is not None]
                    old['allocated_vram_bytes'] = max(allocated) if allocated else None
        except (FileNotFoundError, ProcessLookupError):
            if pid == model_pid:
                sample['errors'].append(dict(pid=pid, reason='model_disappeared'))
            elif birth_seen:
                sample['errors'].append(dict(pid=pid, reason='owned_process_disappeared_during_sample'))
        except (OSError, IndexError, ValueError) as exc:
            sample['errors'].append(dict(pid=pid, reason=str(exc)))
    sample['clients'] = sorted(clients.values(), key=lambda x: (x['pci_bdf'], x['client_id']))
    sample['complete'] = (not sample['errors'] and sample['model_birth_seen'] and sample['model_drm_client_seen'])
    sample['owned_resident_vram_bytes'] = (sum(x['resident_vram_bytes'] for x in clients.values())
                                          if sample['complete'] else None)
    sample['single_owned_device'] = (len({x['pci_bdf'] for x in clients.values()}) == 1
                                     if sample['complete'] else None)
    return sample


def cleanup(proc, tracked, model_pid):
    """TERM stage cooperatively, then reap/kill only verified owned descendants."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + 10
    while True:
        # The wrapper is a subreaper: detached worker sessions become our
        # children when their own parent exits, including fast-parent orphans.
        tracked.update(descendants(os.getpid()))
        active = []
        for pid, recorded in list(tracked.items()):
            if pid in (os.getpid(), model_pid):
                raise RuntimeError('protected PID unexpectedly entered the owned tree')
            current = process_record(pid)
            if not current or current['starttime'] != recorded['starttime']:
                continue
            if current['state'] == 'Z':
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            else:
                active.append(current)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if proc:
            proc.poll()
        # A dying parent can fork after the first snapshot. Refresh adopted
        # children after signals/reaping before declaring that the tree is gone.
        newly_observed = descendants(os.getpid())
        tracked.update(newly_observed)
        remaining = []
        for pid, recorded in tracked.items():
            current = process_record(pid)
            if current and current['starttime'] == recorded['starttime']:
                remaining.append(current)
        if (not remaining and not newly_observed) or time.monotonic() >= deadline:
            return dict(verified=not remaining and not newly_observed, remaining=remaining,
                        recorded=list(tracked.values()), method='owned_tree_all_threads_subreaper')
        time.sleep(.05)


def model_idle(base, model_name, pid):
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password:
        raise RuntimeError('model endpoint must be an HTTP loopback URL without credentials')
    origin = parsed.scheme + '://' + parsed.netloc
    # Verify that the selected PID owns a listening socket on this endpoint.
    inodes = set()
    for fd in (Path('/proc') / str(pid) / 'fd').iterdir():
        try:
            link = os.readlink(fd)
            if link.startswith('socket:['):
                inodes.add(link[8:-1])
        except FileNotFoundError:
            pass
    port = parsed.port or 80
    listening = False
    for table in ('tcp', 'tcp6'):
        for line in (Path('/proc/net') / table).read_text().splitlines()[1:]:
            cells = line.split()
            if cells[3] == '0A' and int(cells[1].split(':')[1], 16) == port and cells[9] in inodes:
                listening = True
    if not listening:
        raise RuntimeError('model PID does not own the requested listening port')
    def get(path):
        with urllib.request.urlopen(origin + path, timeout=5) as response:
            return json.load(response)
    health = get('/health')
    models = get('/v1/models')
    if health.get('status') != 'ok' or model_name not in [x.get('id') for x in models.get('data', [])]:
        raise RuntimeError('model health or served alias mismatch')
    # Refuse unknown or busy rather than restarting a shared server to enable telemetry.
    slots = get('/slots')
    if not isinstance(slots, list) or not slots or any(x.get('is_processing') is not False for x in slots):
        raise RuntimeError('model slots are busy or idle telemetry is unknown')
    return dict(health_status='ok', model_name=model_name, slot_count=len(slots),
                processing_slots=0, model_pid_owns_port=True)


def files_under(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise RuntimeError('missing protected directory: ' + str(directory))
    return {str(p.relative_to(directory)): sha(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def protected(kit):
    package = files_under(kit / 'submission')
    upstream = json.loads((kit / 'submission/upstream.json').read_text())
    expected = {'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
                'run_baseline.sh': '5c46c40d32c0cf4c4e1dc52ae12e60f8396a0deccafaa4e6f69d7316a3482e75'}
    if upstream['files'] != expected or any(package.get(p) != h for p, h in expected.items()):
        raise RuntimeError('official baseline identity mismatch; do not repair it in this wrapper')
    return dict(package=package, official=files_under(kit / 'official_reference'),
                tasks=files_under(kit / 'bench/tasks_veval'), baseline=expected,
                upstream_commit=upstream['commit'])


def require_idle(exclude):
    busy = []
    tool_names = {'xvlog', 'xelab', 'xsim', 'vivado', 'xsimk'}
    job_names = ('official_eval.py', 'five_sample_quality.py', 'signedness_repair_pilot.py',
                 'state_update_repair_pilot.py', 'linux_preflight.py',
                 'paired_checkpoint.py', 'run_runtime728.sh')
    for root in Path('/proc').iterdir():
        if not root.name.isdigit() or int(root.name) in exclude:
            continue
        try:
            state = (root / 'stat').read_text().rsplit(')', 1)[1].split()[0]
            if state in ('Z', 'X'):
                continue
            name = (root / 'comm').read_text().strip()
            command = (root / 'cmdline').read_bytes().split(b'\0')
            arg_names = {Path(a.decode(errors='replace')).name for a in command if a}
            if name in tool_names or arg_names.intersection(job_names):
                busy.append(dict(pid=int(root.name), name=name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise RuntimeError('cannot inspect process ownership; idle is unknown') from exc
    if busy:
        raise RuntimeError('shared evaluation/tools still active: ' + json.dumps(busy))
    return dict(checked_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                observed_busy_processes=busy,
                limit='known evaluator/tool process names plus existing cooperative slot; not an OS exclusivity guarantee')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--model-pid', type=int, required=True)
    parser.add_argument('--model-name', required=True)
    parser.add_argument('--llm-base-url', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--slot-script', type=Path, default=Path('/workspace/team/slot.sh'))
    parser.add_argument('--slot-lock', type=Path, default=Path('/workspace/team/SLOT.lock'))
    parser.add_argument('--owner', required=True)
    parser.add_argument('--guard-out', type=Path, required=True)
    parser.add_argument('--minimum-free-gib', type=float, default=3)
    parser.add_argument('--slot-minutes', type=int, default=60)
    parser.add_argument('--stage-timeout-s', type=float, default=2400)
    parser.add_argument('--sample-gpu-resources', action='store_true',
                        help='Record owned DRM/device observations; not formal resource acceptance')
    parser.add_argument('--gpu-sample-interval-s', type=float, default=1.)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('only run on the authorized AMD Linux server')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a stage command is required')
    if not args.owner or any(char.isspace() for char in args.owner):
        parser.error('owner must be a single nonempty line')
    if not math.isfinite(args.minimum_free_gib) or args.minimum_free_gib <= 0 or args.slot_minutes <= 0:
        parser.error('disk threshold and lease must be positive and finite')
    if not 0 < args.stage_timeout_s < args.slot_minutes * 60 - 60:
        parser.error('stage timeout must leave at least 60 seconds before slot lease expiry')
    if not math.isfinite(args.gpu_sample_interval_s) or args.gpu_sample_interval_s < .25:
        parser.error('GPU sampling interval must be finite and at least .25 seconds')
    args.kit = args.kit.resolve()
    out = args.guard_out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    proc, lock_bytes, before, model_before = None, None, None, None
    acquiring = False
    tracked = {}
    result = dict(schema_version=1, complete=False, passed=False, phase='resource_guard',
                  model_managed=False, instance_managed=False)
    rc = 1
    gpu_stream, gpu_summary, last_gpu_sample = None, None, None

    def record_gpu(phase):
        nonlocal last_gpu_sample
        current_model = process_record(args.model_pid)
        model_children = (descendants(args.model_pid) if current_model and
                          current_model['starttime'] == model_before['starttime'] and
                          current_model['state'] not in ('Z', 'X') else {})
        owned = {**tracked, **model_children, args.model_pid: model_before}
        sample = gpu_sample(owned, args.model_pid)
        sample['phase'] = phase
        gpu_stream.write(json.dumps(sample, sort_keys=True) + '\n')
        gpu_stream.flush()
        gpu_summary['sample_count'] += 1
        gpu_summary['all_samples_complete'] &= sample['complete']
        if last_gpu_sample is not None:
            gpu_summary['max_sample_gap_s'] = max(gpu_summary['max_sample_gap_s'], sample['monotonic'] - last_gpu_sample)
        last_gpu_sample = sample['monotonic']
        if sample['complete']:
            gpu_summary['complete_sample_count'] += 1
            previous_peak = gpu_summary['observed_peak_owned_resident_vram_bytes']
            gpu_summary['observed_peak_owned_resident_vram_bytes'] = max(previous_peak or 0, sample['owned_resident_vram_bytes'])
            single = gpu_summary['all_complete_samples_single_device']
            gpu_summary['all_complete_samples_single_device'] = sample['single_owned_device'] if single is None else single and sample['single_owned_device']

    def cancel(signum, frame):
        raise InterruptedError('stage wrapper received signal ' + str(signum))

    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
            raise RuntimeError('cannot enable owned-orphan subreaper; no stage started')
        if args.slot_lock.exists():
            raise RuntimeError('shared slot occupied; retain it and retry later after its owner releases')
        idle = require_idle({os.getpid(), os.getppid()})
        if shutil.disk_usage(out).free < args.minimum_free_gib * 1024 ** 3:
            raise RuntimeError('insufficient free disk; no stage started')
        model_before = identity(args.model_pid)
        model_telemetry = model_idle(args.llm_base_url, args.model_name, args.model_pid)
        before = protected(args.kit)
        acquiring = True
        acquire_started = time.monotonic()
        subprocess.run([str(args.slot_script), 'acquire', args.owner,
                        str(args.slot_minutes), 'isolated selective runtime verification'],
                       check=True, timeout=15)
        acquired_bytes = args.slot_lock.read_bytes()
        if acquired_bytes.decode().splitlines()[0] != args.owner:
            raise RuntimeError('slot ownership mismatch after acquire')
        lock_bytes = acquired_bytes
        # Recheck cooperative ownership before work; slot.sh is not an OS lock.
        idle = require_idle({os.getpid(), os.getppid()})
        model_telemetry = model_idle(args.llm_base_url, args.model_name, args.model_pid)
        if identity(args.model_pid) != model_before or protected(args.kit) != before:
            raise RuntimeError('protected state changed during admission')
        lease_deadline = acquire_started + args.slot_minutes * 60 - 60
        if time.monotonic() >= lease_deadline:
            raise TimeoutError('slot lease reserve exhausted during admission')
        check = dict(schema_version=1, host=socket.gethostname(), resource_idle=True,
                     **idle, slot_owner=args.owner, slot_lock_path=str(args.slot_lock.resolve()),
                     llm_base_url=args.llm_base_url.rstrip('/'), model_name=args.model_name,
                     slot_lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
                     model_pid=args.model_pid, model_starttime=model_before['starttime'],
                     model_identity=model_before,
                     baseline_hashes={str(args.kit / 'submission' / p): h for p, h in before['baseline'].items()},
                     model_telemetry=model_telemetry,
                     official_hashes={str(args.kit / 'official_reference' / p): h for p, h in before['official'].items()},
                     protected=before,
                     slot_script_sha256=sha(args.slot_script))
        save(out / 'resource_check.json', check)
        if args.sample_gpu_resources:
            gpu_stream = (out / 'gpu_samples.jsonl').open('x', encoding='utf-8')
            gpu_summary = dict(sample_count=0, complete_sample_count=0, interval_s=args.gpu_sample_interval_s, max_sample_gap_s=0.,
                               all_samples_complete=True, all_complete_samples_single_device=None,
                               observed_peak_owned_resident_vram_bytes=None, covers_model_loading=False,
                               formal_resource_acceptance=False,
                               scope='Pre-stage through owned cleanup on an existing model; sampled values, not continuous maxima. Device-wide utilization is not attributable solely to this model.')
            record_gpu('pre_stage')
        if '{resource_check}' not in command:
            raise RuntimeError('stage command must contain the literal {resource_check} argument')
        command = [str(out / 'resource_check.json') if item == '{resource_check}' else item
                   for item in command]
        result['started_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tick = time.monotonic()
        with (out / 'stage.log').open('xb') as stream:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True, cwd=out)
            result['stage_pid'] = proc.pid
            save(out / 'status.json', result)
            deadline = min(time.monotonic() + args.stage_timeout_s, lease_deadline)
            while proc.poll() is None:
                tracked.update(descendants(os.getpid()))
                if time.monotonic() >= deadline:
                    raise TimeoutError('owned stage reached its hard timeout before lease expiry')
                if args.slot_lock.read_bytes() != lock_bytes:
                    raise RuntimeError('shared slot changed while stage was running')
                if identity(args.model_pid) != model_before:
                    raise RuntimeError('shared model identity changed while stage was running')
                if gpu_stream is not None and time.monotonic() - last_gpu_sample >= args.gpu_sample_interval_s:
                    record_gpu('stage')
                time.sleep(.25)
            rc = proc.returncode
        result.update(stage_rc=rc, elapsed_s=time.monotonic() - tick)
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        rc = 1
    finally:
        # Repeated termination signals must not interrupt owned cleanup/release.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            result['owned_cleanup'] = cleanup(proc, tracked, args.model_pid)
            if not result['owned_cleanup']['verified']:
                rc = 1
        except Exception as exc:
            result['wrapper_cleanup_error'] = type(exc).__name__ + ': ' + str(exc)
            rc = 1
        if gpu_stream is not None:
            try:
                record_gpu('post_cleanup')
            except Exception as exc:
                gpu_summary['sampling_error'] = type(exc).__name__ + ': ' + str(exc)
                gpu_summary['all_samples_complete'] = False
            finally:
                gpu_stream.close()
                gpu_summary.update(log_sha256=sha(out / 'gpu_samples.jsonl'),
                                   log_bytes=(out / 'gpu_samples.jsonl').stat().st_size)
                result['gpu_observation'] = gpu_summary
        try:
            result['model_unchanged'] = model_before is not None and identity(args.model_pid) == model_before
            result['protected_files_unchanged'] = before is not None and protected(args.kit) == before
            if model_before is not None:
                result['model_idle_after'] = model_idle(args.llm_base_url, args.model_name, args.model_pid)
            if not result['model_unchanged'] or not result['protected_files_unchanged']:
                rc = 1
        except Exception as exc:
            result['postflight_error'] = type(exc).__name__ + ': ' + str(exc)
            rc = 1
        if lock_bytes is None and acquiring:
            try:
                possible = args.slot_lock.read_bytes()
                if possible.decode().splitlines()[0] == args.owner:
                    lock_bytes = possible
            except (OSError, UnicodeError, IndexError):
                pass
        if lock_bytes is not None:
            try:
                if args.slot_lock.read_bytes() != lock_bytes:
                    raise RuntimeError('slot changed: do not release another owner')
                if (result.get('owned_cleanup', {}).get('verified') is not True
                        or not result.get('model_idle_after')):
                    result.update(own_slot_released=False, slot_retained_for_inspection=True)
                    rc = 1
                else:
                    subprocess.run([str(args.slot_script), 'release', args.owner], check=True, timeout=15)
                    # Another owner may acquire immediately; our exact lock must be gone.
                    result['own_slot_released'] = (not args.slot_lock.exists() or args.slot_lock.read_bytes() != lock_bytes)
                    if not result['own_slot_released']:
                        rc = 1
            except Exception as exc:
                result['slot_release_error'] = type(exc).__name__ + ': ' + str(exc)
                rc = 1
        else:
            result['own_slot_released'] = None
        result.update(complete=True, passed=rc == 0,
                      finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        save(out / 'status.json', result)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps(result))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
