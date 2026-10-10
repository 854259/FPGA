#!/usr/bin/env python3
"""AMD-only GPU evidence controls, selected explicitly by execution mode.

Default: filesystem boundary cases and one read-only warm-model sample.
--guard-main-only: actual guard main/cleanup with five CPU stages and a private
synthetic lease; admission/model/DRM are fixtures, no shared slot or model access.
Preserve results in a fresh output directory; run -B under an external guard.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def guard_main_cases(module, source, out):
    """Exercise actual main/cleanup with CPU stages and a private synthetic lease.

    Model identity/idle, protected package, global admission and GPU samples are
    explicit fixtures. No shared model, slot, GPU or EDA operation is performed.
    This validates wiring only, not resource admission or complete lifecycle.
    """
    import contextlib
    import io
    import os
    import time
    from unittest.mock import patch

    records = []
    cases = ('enabled', 'disabled', 'partial_sample', 'post_sample_error',
             'stage_timeout', 'invalid_interval')
    own_pid = os.getpid()
    original_process = module.process_record(own_pid)
    assert original_process and original_process['state'] not in ('Z', 'X')
    model = dict(pid=own_pid, starttime=original_process['starttime'],
                 exe='synthetic-model-identity', command_sha256=hashlib.sha256(
                     (Path('/proc') / str(own_pid) / 'cmdline').read_bytes()).hexdigest())
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    for name in cases:
        case = out / name
        case.mkdir()
        lock, guard_out = case / 'SLOT.lock', case / 'guard'
        slot = case / 'slot.py'
        slot.write_text(
            '#!' + sys.executable + '\n'
            'import pathlib,sys\n'
            'lock=pathlib.Path(' + repr(str(lock)) + ')\n'
            'if sys.argv[1]=="acquire":\n'
            ' with lock.open("x") as f:f.write(sys.argv[2]+"\\nfixture lease\\n")\n'
            'elif sys.argv[1]=="release":\n'
            ' assert lock.read_text().splitlines()[0]==sys.argv[2]\n'
            ' lock.unlink()\n'
            'else:raise AssertionError("unexpected lease command")\n',
            encoding='utf-8')
        slot.chmod(0o700)
        stage = case / 'stage.py'
        stage.write_text(
            'import pathlib,json,os,time\n'
            'root=pathlib.Path(__file__).parent\n'
            'p=pathlib.Path("/proc")/str(os.getpid())\n'
            'stat=(p/"stat").read_bytes();cmd=(p/"cmdline").read_bytes()\n'
            '(root/"stage_stat.bin").write_bytes(stat)\n'
            '(root/"stage_cmdline.bin").write_bytes(cmd)\n'
            '(root/"stage_identity.json").write_text(json.dumps(dict(pid=os.getpid(),'
            'starttime=stat.decode().rsplit(")",1)[1].split()[19])))\n'
            'time.sleep(' + ('2' if name == 'stage_timeout' else '.65') + ')\n',
            encoding='utf-8')
        sample_calls = []
        def sample(owned, model_pid):
            assert model_pid == own_pid and owned[own_pid]['starttime'] == model['starttime']
            active = [pid for pid in owned if pid != own_pid and module.process_record(pid)]
            phase = 'pre_stage' if not sample_calls else ('stage' if active else 'post_cleanup')
            sample_calls.append(dict(phase=phase, owned=owned))
            if name == 'post_sample_error' and phase == 'post_cleanup':
                raise OSError('synthetic post-cleanup sampling read failure')
            complete = not (name == 'partial_sample' and len(sample_calls) == 2)
            value = {'pre_stage': 1024, 'stage': 2048, 'post_cleanup': 4096}[phase]
            return dict(monotonic=time.monotonic(), complete=complete,
                        model_birth_seen=True, model_drm_client_seen=complete,
                        owned_resident_vram_bytes=value if complete else None,
                        single_owned_device=True if complete else None,
                        clients=[], devices={},
                        errors=[] if complete else [dict(reason='synthetic missing resident')])
        def identity(pid):
            assert pid == own_pid
            current = module.process_record(pid)
            assert current and current['starttime'] == model['starttime']
            return dict(model)
        protected = dict(package={'fixture.txt': source_hash}, official={},
                         tasks={}, baseline={}, upstream_commit='synthetic-admission-only')
        command = ['resource_guard.py', '--kit', str(case), '--model-pid', str(own_pid),
                   '--model-name', 'synthetic-no-inference', '--slot-script', str(slot),
                   '--slot-lock', str(lock), '--owner', 'cpu-wiring-' + name,
                   '--guard-out', str(guard_out), '--minimum-free-gib', '.001',
                   '--slot-minutes', '2', '--stage-timeout-s',
                   '.55' if name == 'stage_timeout' else '3',
                   '--gpu-sample-interval-s', '.1' if name == 'invalid_interval' else '.25']
        if name != 'disabled':
            command.append('--sample-gpu-resources')
        command += ['--', sys.executable, '-B', str(stage), '{resource_check}']
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', command), \
                patch.object(module, 'identity', identity), \
                patch.object(module, 'model_idle', return_value=dict(processing_slots=0, synthetic=True)), \
                patch.object(module, 'require_idle', return_value=dict(
                    observed_busy_processes=[], limit='synthetic admission;not actual exclusivity')), \
                patch.object(module, 'protected', return_value=protected), \
                patch.object(module, 'gpu_sample', sample), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                rc = module.main()
            except SystemExit as exc:
                rc = exc.code
        (case / 'stdout.txt').write_text(output.getvalue(), encoding='utf-8')
        (case / 'stderr.txt').write_text(errors.getvalue(), encoding='utf-8')
        (case / 'sample_calls.json').write_text(json.dumps(sample_calls, indent=2) + '\n')
        if name == 'invalid_interval':
            assert rc == 2 and not guard_out.exists() and not lock.exists() and not sample_calls
            assert not (case / 'stage_identity.json').exists()
            records.append(dict(case=name, passed=True, returncode=rc, stage_started=False))
            continue
        result = json.loads((guard_out / 'status.json').read_text())
        assert rc == (1 if name == 'stage_timeout' else 0), result
        assert result['passed'] == (rc == 0) and result['complete']
        assert result['owned_cleanup']['verified'] and not result['owned_cleanup']['remaining']
        assert result['own_slot_released'] and not lock.exists()
        assert result['model_unchanged'] and result['protected_files_unchanged']
        birth = json.loads((case / 'stage_identity.json').read_text())
        assert result['stage_pid'] == birth['pid']
        assert module.process_record(birth['pid']) is None
        raw_stat = (case / 'stage_stat.bin').read_text()
        assert raw_stat.rsplit(')', 1)[1].split()[19] == birth['starttime']
        assert (case / 'stage_cmdline.bin').read_bytes().split(b'\0')[:3] == [
            sys.executable.encode(), b'-B', str(stage).encode()]
        if name == 'disabled':
            assert not sample_calls and 'gpu_observation' not in result
            assert not (guard_out / 'gpu_samples.jsonl').exists()
            observation = None
        else:
            observation = result['gpu_observation']
            log = (guard_out / 'gpu_samples.jsonl').read_bytes()
            samples = [json.loads(line) for line in log.splitlines()]
            assert observation['log_sha256'] == hashlib.sha256(log).hexdigest()
            assert observation['log_bytes'] == len(log)
            assert observation['sample_count'] == len(samples) >= 2
            assert samples[0]['phase'] == 'pre_stage' and any(s['phase'] == 'stage' for s in samples)
            assert observation['complete_sample_count'] == sum(s['complete'] for s in samples)
            assert observation['covers_model_loading'] is False
            assert observation['formal_resource_acceptance'] is False
            assert observation['interval_s'] == .25 and observation['max_sample_gap_s'] > 0
            if name == 'post_sample_error':
                assert observation['all_samples_complete'] is False and 'sampling_error' in observation
                assert samples[-1]['phase'] != 'post_cleanup' and result['passed'] is True
            else:
                assert samples[-1]['phase'] == 'post_cleanup'
                assert observation['observed_peak_owned_resident_vram_bytes'] == 4096
                assert observation['all_samples_complete'] == (name != 'partial_sample')
            if name == 'partial_sample':
                incomplete = [s for s in samples if not s['complete']]
                assert len(incomplete) == 1 and incomplete[0]['owned_resident_vram_bytes'] is None
            if name == 'stage_timeout':
                assert result['error'].startswith('TimeoutError:') and result['passed'] is False
        records.append(dict(case=name, passed=True, returncode=rc, stage_started=True,
                            stage_identity=birth, stage_retired=True,
                            sampling_observation=observation))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report = dict(schema='gpu_sampling_main_wiring_CPU_v1', passed=True, cases=records,
                  source_sha256=source_hash,
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  guard_main_executed=True, actual_CPU_stage_processes=5,
                  synthetic_boundaries=['model identity/idle', 'global admission', 'protected package',
                                        'GPU samples', 'private lease protocol'],
                  shared_model_accessed=False, shared_slot_accessed=False,
                  real_GPU_read=False, model_loading_observed=False,
                  complete_lifecycle_observed=False, formal_resource_acceptance=False,
                  old_boundary_controls_rerun=False, network='connect_and_bind_denied',
                  new_model_calls=0, new_EDA=0, new_FIFO=0)
    (out / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--guard-main-only', action='store_true')
    parser.add_argument('--model-pid', type=int)
    parser.add_argument('--model-starttime')
    parser.add_argument('--model-command-sha256')
    args = parser.parse_args()
    if not args.guard_main_only and (args.model_pid is None or not args.model_starttime or not args.model_command_sha256):
        parser.error('warm-model boundary controls require all three model identity arguments')
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    args.out.mkdir(exist_ok=False)

    def deny_network(event, arguments):
        if event in ('socket.connect', 'socket.bind'):
            raise AssertionError('network prohibited in sampling qualification')
    sys.addaudithook(deny_network)
    spec = importlib.util.spec_from_file_location('resource_under_test', args.source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if args.guard_main_only:
        guard_main_cases(module, args.source, args.out)
        return
    source_sha = hashlib.sha256(args.source.read_bytes()).hexdigest()
    records = []
    cases = ['shared_client_dedup', 'shared_client_across_pids', 'missing_resident', 'unsupported_unit',
             'model_pid_reused', 'device_binding_mismatch', 'two_owned_devices',
             'missing_model_client', 'zero_resident_is_known', 'owned_disappears_during_sample']
    for name in cases:
        root = args.out / name
        proc, drm = root / 'proc', root / 'drm'
        root.mkdir()
        owned = {101: dict(pid=101, starttime='100'), 102: dict(pid=102, starttime='101')}
        devices = [('renderD128', '0000:01:00.0'), ('renderD129', '0000:02:00.0')]
        for node, pci in devices:
            device = root / 'devices' / pci
            device.mkdir(parents=True)
            for field, value in [('vendor', '0x1002'), ('mem_info_vram_total', '51522830336'),
                                 ('mem_info_vram_used', '123456'), ('gpu_busy_percent', '37')]:
                (device / field).write_text(value + '\n')
            (drm / node).mkdir(parents=True)
            (drm / node / 'device').symlink_to(device, target_is_directory=True)
        for pid, birth in owned.items():
            folder = proc / str(pid)
            (folder / 'fdinfo').mkdir(parents=True)
            (folder / 'fd').mkdir()
            fields = ['S', '1', str(pid), str(pid)] + ['0'] * 15 + [birth['starttime']]
            (folder / 'stat').write_text(str(pid) + ' (fixture) ' + ' '.join(fields) + '\n')
            for fd in ([3, 4] if pid == 101 else [5]):
                node, pci = devices[1 if name == 'two_owned_devices' and pid == 102 else 0]
                if name == 'device_binding_mismatch' and pid == 101:
                    pci = '0000:ff:00.0'
                resident = '4 KiB' if pid == 101 else '6 KiB'
                if name == 'unsupported_unit' and pid == 101:
                    resident = '4 MiB'
                if name == 'zero_resident_is_known':
                    resident = '0'
                text = ('drm-driver:\tamdgpu\n'
                        'drm-client-id:\t' + ('7' if pid == 101 or name == 'shared_client_across_pids' else '8') + '\n'
                        'drm-pdev:\t' + pci + '\n'
                        'drm-memory-vram:\t9 KiB\n')
                if not (name == 'missing_resident' and pid == 101):
                    text += 'drm-resident-vram:\t' + resident + '\n'
                if name == 'missing_model_client' and pid == 101:
                    text = 'pos:\t0\nflags:\t0100000\n'
                (folder / 'fdinfo' / str(fd)).write_text(text)
                (folder / 'fd' / str(fd)).symlink_to('/dev/dri/' + node)
        if name == 'model_pid_reused':
            owned[101]['starttime'] = '99'
        original_read_text = Path.read_text
        stat_reads = 0
        def controlled_read_text(path, *a, **kw):
            nonlocal stat_reads
            if name == 'owned_disappears_during_sample' and path == proc / '102' / 'stat':
                stat_reads += 1
                if stat_reads == 2:
                    raise FileNotFoundError('simulated retirement after initial birth check')
            return original_read_text(path, *a, **kw)
        Path.read_text = controlled_read_text
        try:
            result = module.gpu_sample(owned, 101, proc_root=proc, drm_root=drm)
        finally:
            Path.read_text = original_read_text
        unknown = name in ('missing_resident', 'unsupported_unit', 'model_pid_reused',
                           'device_binding_mismatch', 'missing_model_client', 'owned_disappears_during_sample')
        assert result['complete'] is not unknown, (name, result)
        if unknown:
            assert result['owned_resident_vram_bytes'] is None and result['single_owned_device'] is None
        else:
            expected_bytes = 0 if name == 'zero_resident_is_known' else (6 if name == 'shared_client_across_pids' else 10) * 1024
            assert result['owned_resident_vram_bytes'] == expected_bytes
            assert len(result['clients']) == (1 if name == 'shared_client_across_pids' else 2)
            assert len(result['clients'][0]['owners']) == (3 if name == 'shared_client_across_pids' else 2)
            assert result['single_owned_device'] == (name != 'two_owned_devices')
            assert all(c['engine_counters'] is None for c in result['clients'])
            assert all(d['mem_info_vram_used'] == 123456 for d in result['devices'].values())
        with (root / 'RESULT.json').open('x') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        records.append(dict(case=name, passed=True, complete=result['complete']))

    bound = dict(pid=args.model_pid, starttime=args.model_starttime,
                 command_sha256=args.model_command_sha256)
    before = module.identity(args.model_pid)
    assert all(before[k] == v for k, v in bound.items())
    live = module.gpu_sample({args.model_pid: before}, args.model_pid)
    assert module.identity(args.model_pid) == before
    assert live['complete'] and live['single_owned_device'] and live['model_drm_client_seen']
    assert live['owned_resident_vram_bytes'] > 0
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == source_sha
    with (args.out / 'LIVE_SAMPLE.json').open('x') as stream:
        json.dump(live, stream, indent=2)
        stream.write('\n')
    report = dict(schema='owned_gpu_sampling_qualification_v1', passed=True,
                  source_sha256=source_sha, test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  cases=records, live_sample=live, model_identity_held=True,
                  guard_loop_executed=False, model_loading_observed=False,
                  complete_lifecycle_observed=False, formal_resource_acceptance=False,
                  network='connect_and_bind_denied', new_model_calls=0, new_EDA=0, new_FIFO=0)
    with (args.out / 'RESULT.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
