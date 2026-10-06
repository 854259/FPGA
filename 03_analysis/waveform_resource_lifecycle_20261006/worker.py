"""Original phase-P solver; only P round zero may append supplied-waveform facts."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import baseline_worker
import waveform_request

ROOT = Path(__file__).resolve().parent

def run_worker(args, paired):
    assert args.arm in ('C', 'P') and baseline_worker.ROOT == ROOT
    source = args.kit / 'bench/tasks_veval' / args.task
    original = {n: (source / n).read_bytes() for n in ('prompt.txt', 'interface.txt') if (source / n).is_file()}
    assert 'prompt.txt' in original
    context = dict(prompt=original['prompt.txt'].decode(), interface=original.get('interface.txt', b'').decode(),
                   arm=args.arm, out=args.out.resolve(), receipts=[])
    old = baseline_worker.urllib.request.Request
    baseline_worker.urllib.request.Request = waveform_request.request_class(old, context)
    try:
        baseline_worker.run_worker(args, paired)
        assert {n: (source / n).read_bytes() for n in original} == original
        journal = json.loads((args.out / 'requests.json').read_bytes())
        assert 1 <= len(journal) == len(context['receipts']) <= 2
        for index, receipt in enumerate(context['receipts']):
            body = json.loads((args.out / 'requests' / str(index) / 'request.json').read_bytes())
            forwarded = (args.out / 'waveform_request_receipts' / str(index) / 'forwarded_wire.bin').read_bytes()
            assert json.loads(forwarded) == body and receipt['forwarded_wire_sha256'] == waveform_request.digest(forwarded)
    finally:
        baseline_worker.urllib.request.Request = old

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('out', 'kit', 'resource-check'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--arm', choices=('C', 'P'), required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    spec = json.loads((ROOT / 'RUN_SPEC.json').read_bytes())
    paired = baseline_worker.load('waveform_original_resource', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    paired.REPO = ROOT
    paired.INHERITED_ORACLE = Path(spec['dependencies_cloud']) / 'probe_runner.py'
    paired.check_resource(args.resource_check, args.kit)
    run_worker(args, paired)

