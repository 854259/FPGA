"""R1: frozen lexical admission grid for an existing shift-contract checker.

Development engineering substage. No model, generated DUT, reference or official score.
"""
import argparse
from collections import Counter
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

KEYWORDS = ('bit', 'byte', 'shortint', 'int', 'longint', 'time', 'real',
            'event', 'enum', 'struct', 'union', 'always_comb', 'always_ff', 'always_latch')
SOURCE_HASHES = {
    'shift_contract.py': 'de93b416bd436b7caacc529b4894761131c6fbd108cd11d07679c6b561f35863',
    'test_shift.py': 'f72ce775d7e03cb7ba35e97e125177cd5f37818a1405d0ad859caad17d2f83ef',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def run(a):
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    sys.dont_write_bytecode = True
    assert sha(a.paired.read_bytes()) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    paired = load('r1_supervisor', a.paired)
    paired.check_resource(a.resource_check, a.kit, first=True)
    a.out.mkdir(parents=True, exist_ok=False)
    sources = a.out / 'sources'; sources.mkdir()
    for name, digest in SOURCE_HASHES.items():
        data = (a.source / name).read_bytes(); assert sha(data) == digest
        (sources / name).write_bytes(data)
    parser = load('shift_contract', sources / 'shift_contract.py'); sys.modules['shift_contract'] = parser
    fixture = load('r1_material', sources / 'test_shift.py')
    tick = time.monotonic(); cases = []
    for width in range(8, 65):
        base = fixture.material(width)
        cases.extend([(f'w{width}_plain', 'valid', base, True),
                      (f'w{width}_renamed', 'valid', fixture.material(width, 'clock', 'capture', 'run', 'mode', 'payload', 'state'), True)])
        for role in ('load', 'enable', 'amount', 'data', 'out'):
            for word in KEYWORDS:
                cases.append((f'w{width}_{role}_{word}', 'reserved_word', fixture.material(width, **{role:word}), False))
        for label, text in (
            ('role_only', base.replace('(3) amount:', '(3) AMOUNT:')),
            ('selector_only', base.replace('"amount."', '"AMOUNT."')),
            ('both', base.replace('(3) amount:', '(3) AMOUNT:').replace('"amount."', '"AMOUNT."'))):
            cases.append((f'w{width}_case_{label}', 'case_ambiguity', text, False))
    assert len(cases) == 4275
    # Freeze generated inputs and expectations before querying the parser.
    manifest = [{'id':i, 'group':g, 'prompt_sha256':sha(p.encode()), 'expect_supported':e} for i,g,p,e in cases]
    (a.out / 'INPUT_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    rows = []; counts = Counter(); compile_cases = []
    report = dict(complete=False, admission_passed=False, model_calls=0, eda_calls=0,
                  natural_independent_tasks=0, full_batch_complete=False, rows=rows, compiler_controls=[],
                  source_hashes=SOURCE_HASHES, input_manifest_sha256=sha((a.out / 'INPUT_MANIFEST.json').read_bytes()),
                  driver_sha256=sha(Path(__file__).read_bytes()), error=None)
    try:
        for case_id, group, prompt, expected in cases:
            c = parser.parse(prompt); actual = c['status'] == 'supported'
            counts[group + '/total'] += 1
            if actual != expected: counts['false_accept' if actual else 'false_abstain'] += 1
            rows.append(dict(id=case_id, group=group, expected_supported=expected, actual_supported=actual, status=c['status']))
            if case_id in ['w8_plain', 'w64_renamed'] or case_id.startswith('w8_data_'):
                # Isolated syntax check only. Undefined DUT is acceptable at xvlog analysis.
                # The generated TB's declaration grammar is the property being checked.
                assert actual, 'expected frozen syntax witness no longer accepted; inspect source identity'
                compile_cases.append((case_id, prompt, parser.render_tb(c, 'R1Witness'), expected))
        assert len(compile_cases) == 16
        env = os.environ
        env['LD_LIBRARY_PATH'] = '/workspace/team/udev-stub'
        assert sha(Path(env['LD_LIBRARY_PATH'], 'libudev.so.1').read_bytes()) == '3a2d6266ccf18909d3ebccbf21e8125ce985359319fecc6c8172aeabf13ecf87'
        for case_id, prompt, tb, expected in compile_cases:
            assert time.monotonic() - tick < 150
            paired.check_resource(a.resource_check, a.kit)
            wd = a.out / 'compiler_controls' / case_id; wd.mkdir(parents=True)
            (wd / 'prompt.txt').write_text(prompt); (wd / 'tb.sv').write_text(tb)
            cmd = ['/workspace/AMD/2026.1/Vivado/bin/xvlog', '--sv', str(wd / 'tb.sv')]
            receipt = paired.owned_command(cmd, wd, wd / 'compile.log', 15)
            report['eda_calls'] += 1
            assert not receipt['timeout'] and not receipt['launch_error'] and not receipt['remaining_live_group']
            log = (wd / 'compile.log').read_text(errors='replace')
            assert 'VRFC ' in log and 'No such file or directory' not in log
            matched = (receipt['returncode'] == 0) == expected
            report['compiler_controls'].append(dict(id=case_id, expected_compile=expected, returncode=receipt['returncode'], expectation_matched=matched, supervision=receipt))
            assert matched, 'compiler witness disagrees with frozen language expectation'
        assert all(sha((a.source / n).read_bytes()) == h for n,h in SOURCE_HASHES.items())
        report.update(complete=True, admission_passed=counts['false_accept'] == counts['false_abstain'] == 0,
                      counts=dict(counts), existing_source_unchanged=True)
        paired.check_resource(a.resource_check, a.kit)
    except BaseException as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['elapsed_s'] = time.monotonic() - tick
        (a.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ['rows','compiler_controls']}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('source','out','paired','resource-check','kit'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
