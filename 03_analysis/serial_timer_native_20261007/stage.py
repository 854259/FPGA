"""Frozen AMD finite calibration only; every native call requires original FIFO."""
import argparse, hashlib, importlib.util, json, os, shutil, sys, time, traceback
from pathlib import Path
import calibration, measure, owned_exec

def digest(f):
    return hashlib.sha256(Path(f).read_bytes()).hexdigest()

def read(f):
    return json.loads(Path(f).read_bytes())

def save(f, j):
    with Path(f).open('x', encoding='utf-8') as s:
        json.dump(j, s, indent=2)
        s.write('\n')

def contained(root, n):
    p = Path(n)
    assert not p.is_absolute() and '..' not in p.parts and ('\\' not in n) and (':' not in n)
    root = Path(root).resolve()
    f = root / p
    assert f.resolve().is_relative_to(root) and f.is_file() and (not any(((root / Path(*p.parts[:i])).is_symlink() for i in range(1, len(p.parts) + 1))))
    return f

def sources(root, spec):
    for n, h in spec['source_hashes'].items():
        assert digest(contained(root, n)) == h, 'frozen source changed: ' + n
    for name in ('stage.py', 'audit.py', 'owned_exec.py', 'measure.py', 'calibration.py', 'serial_timer.py', 'reserved_keywords.py', 'timer_fixture.py'):
        assert 'sources/' + name in spec['source_hashes']

def witness(row, expected):
    if not row['expect_mismatches']:
        assert row['witness'] is None
        return None
    w = row['witness']
    assert isinstance(w, dict) and set(w) == {'index', 'field', 'offset', 'actual'}
    assert type(w['index']) is int and 0 <= w['index'] < len(expected) and (w['field'] == 'outputs') and (type(w['offset']) is int) and (0 <= w['offset'] < 3) and (w['actual'] in '01')
    assert expected[w['index']]['outputs'][w['offset']] in '01' and expected[w['index']]['outputs'][w['offset']] != w['actual']
    return w

def frozen(root):
    root = Path(root).resolve()
    spec = read(root / 'RUN_SPEC.json')
    assert spec['schema'] == 'serial_timer_binary_event_native_frozen_v1' and spec['cloud_root'] == str(root) and (spec['model_requests_max'] == 0)
    assert spec['planned_native_commands'] == 36 and spec['planned_controls'] == 12 and (spec['planned_guard_receipts'] == 73)
    assert spec['native_command_timeout_s'] == 30 and spec['stage_timeout_s'] == 3600 and (spec['guard_timeout_s'] == 4000) and (spec['slot_minutes'] == 70)
    assert spec['protected_group_count'] >= 103 and spec['protected_source_assets'] >= 7069
    assert spec['production_sha256'] == '9080c49a93c807a4e5291e729d0b3ccb85b8d78c680607510ebcec7192fa26d6'
    assert spec['source_hashes']['sources/serial_timer.py'] == spec['production_sha256']
    sources(root, spec)
    plan = read(root / 'CASE_PLAN.json')
    assert plan['schema'] == 'serial_timer_binary_event_native_plan_v1' and plan['controls'] == 12 and (plan['positive_cases'] == 8) and (plan['negative_mutants'] == 4)
    assert plan['native_calls_planned'] == 36 and plan['guard_receipts_planned'] == 73
    assert plan['trace_observations'] == spec['planned_observations'] and len(plan['rows']) == 12
    capture = read(root / 'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    assert digest(root / 'raw_evidence/PROTECTED_BASE_CAPTURE.json') == 'ecebe107e4a1ab6a16ce9ea11b1272734086719767c32f24dc130ca56b4e961e'
    base = read(root / 'raw_evidence/PROTECTED_BASE_CAPTURE.json')
    assert len(base['groups']) == 103 and base['source_assets'] == 7069
    assert len(capture['groups']) == spec['protected_group_count'] and capture['source_assets'] == spec['protected_source_assets']
    assert sum((len(g['source_hashes']) for g in capture['groups'].values())) == spec['protected_source_assets']
    assert all(capture['groups'].get(n) == g for n, g in base['groups'].items())
    cases = calibration.material()
    assert [c['label'] for c in cases] == [r['label'] for r in plan['rows']]
    for row, case in zip(plan['rows'], cases):
        unit = root / 'prepared_cases' / row['relative_root']
        tb, expected = calibration.testbench(case)
        assert (unit / 'candidate.v').read_bytes() == case['rtl'].encode() and (unit / 'tb.sv').read_bytes() == tb.encode() and (read(unit / 'expected.json') == expected)
        assert (unit / 'prompt.txt').read_bytes() == case['prompt'].encode() and (unit / 'interface.v').read_bytes() == case['interface'].encode()
        assert row['expect_mismatches'] == case['mutant'] and row['observations'] == len(expected)
        assert row['witness'] == calibration.witness(case, expected)
        for n, h in row['source_hashes'].items():
            assert digest(unit / n) == h and spec['source_hashes']['prepared_cases/' + row['relative_root'] + '/' + n] == h
        if row['expect_mismatches']:
            assert witness(row, expected) is not None
    assert sum((r['observations'] for r in plan['rows'])) == plan['trace_observations']
    return (spec, plan)

def environment(spec):
    assert sys.platform == 'linux' and sys.dont_write_bytecode and (sys.version_info[:2] == (3, 12))
    assert digest(sys.executable) == spec['python_runtime']['sha256']
    assert {k: os.environ.get(k) for k in spec['compiler_env']} == spec['compiler_env']
    for n, e in spec['compiler_tools'].items():
        assert shutil.which(n) == e['path'] and os.access(e['path'], os.X_OK) and (digest(e['path']) == e['sha256'])
    stub = Path('/workspace/team/udev-stub')
    assert {f.relative_to(stub).as_posix(): digest(f) for f in stub.rglob('*') if f.is_file()} == spec['udev_files']

def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def argv(tool, spec):
    path = spec['compiler_tools'][tool]['path']
    return {'xvlog': [path, '-sv', '--nolog', 'candidate.v', 'tb.sv'], 'xelab': [path, 'tb', '-s', 'serial_timer_snapshot', '--nolog', '-timescale', '1ns/1ps'], 'xsim': [path, 'serial_timer_snapshot', '-runall', '-nolog']}[tool]

def main(root, resource):
    started = time.monotonic()
    root = Path(root).resolve()
    spec, plan = frozen(root)
    environment(spec)
    paired = load('serial_timer_resource', root / 'dependencies/paired_checkpoint.py')
    protected = load('serial_timer_protected', root / 'dependencies/protected_sources.py')
    capture = read(root / 'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    out = root / 'results'
    out.mkdir(exist_ok=False)
    (out / 'guard_receipts').mkdir()
    report = dict(schema='serial_timer_binary_event_native_measurement_v1', spec_sha256=digest(root / 'RUN_SPEC.json'), complete=False, passed=False, native_qualified=False, error=None, rows=[], actual_native_commands=0, actual_model_requests=0, actual_observations=0, guard_receipts=0, score_gain=False, adoption=False)

    def progress():
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        (root / 'STAGE_STATUS.json').write_text(json.dumps(dict(complete=report['complete'], completed_samples=len(report['rows']), expected_samples=12, actual_model_requests=0, actual_native_commands=report['actual_native_commands'], audit_pending=True, adoption=False), indent=2) + '\n', encoding='utf-8')

    def gate(first=False):
        assert time.monotonic() - started < spec['stage_timeout_s'] - 10, 'absolute native stage deadline'
        sources(root, spec)
        environment(spec)
        r = paired.check_resource(Path(resource), Path(spec['kit']), first=first)
        for k in ('model_identity', 'protected', 'slot_owner', 'slot_lock_path', 'model_name'):
            assert r[k] == spec[k]
        p = protected.check(capture)
        assert len(p['groups']) == spec['protected_group_count'] and p['source_assets'] == spec['protected_source_assets']
        n = report['guard_receipts']
        save(out / 'guard_receipts' / ('%04d.json' % n), dict(index=n, resource_sha256=digest(resource), resource=r, protected=p, spec_sha256=report['spec_sha256']))
        report['guard_receipts'] += 1
    progress()
    try:
        gate(True)
        for row in plan['rows']:
            unit = out / row['label']
            unit.mkdir()
            origin = root / 'prepared_cases' / row['relative_root']
            for n in ('candidate.v', 'tb.sv'):
                (unit / n).write_bytes((origin / n).read_bytes())
            rec = dict(label=row['label'], expect_mismatches=row['expect_mismatches'], commands=[], control_matched=False)
            for tool in ('xvlog', 'xelab', 'xsim'):
                gate()
                cmd = owned_exec.run(argv(tool, spec), unit, unit / tool, spec['native_command_timeout_s'])
                report['actual_native_commands'] += 1
                rec['commands'].append(cmd)
                gate()
                assert cmd['normal_completion'] and cmd['returncode'] == 0, 'native launch/tool/timeout/cleanup failure: ' + tool
            for n in ('candidate.v', 'tb.sv'):
                assert digest(unit / n) == row['source_hashes'][n], 'scratch source mutation'
            expected = read(origin / 'expected.json')
            text = (unit / 'xsim/stdout.bin').read_text(encoding='utf-8')
            measured = measure.measure(text, expected, row['expect_mismatches'], witness(row, expected))
            rec.update(control_matched=True, measurement=measured)
            save(unit / 'ROW.json', rec)
            report['rows'].append(rec)
            report['actual_observations'] += measured['observations']
            progress()
        assert report['actual_native_commands'] == 36 and report['actual_observations'] == spec['planned_observations'] and (report['guard_receipts'] == 73)
        report['passed'] = True
    except BaseException as e:
        report['error'] = type(e).__name__ + ': ' + str(e)
        (out / 'ERROR.stderr').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        report['complete'] = True
        report['elapsed_s'] = time.monotonic() - started
        progress()
    return 0 if report['passed'] else 1
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--resource-check', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.root, args.resource_check))
