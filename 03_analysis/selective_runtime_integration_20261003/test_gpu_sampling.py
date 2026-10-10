#!/usr/bin/env python3
"""AMD-only filesystem boundary controls and one read-only warm-model sample.

No model request, EDA, slot acquisition or process signalling. Preserves fixture
and result files in a fresh output directory. Run -B under an external guard.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model-pid', type=int, required=True)
    parser.add_argument('--model-starttime', required=True)
    parser.add_argument('--model-command-sha256', required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    args.out.mkdir(exist_ok=False)

    def deny_network(event, arguments):
        if event in ('socket.connect', 'socket.bind'):
            raise AssertionError('network prohibited in sampling qualification')
    sys.addaudithook(deny_network)
    spec = importlib.util.spec_from_file_location('resource_under_test', args.source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
