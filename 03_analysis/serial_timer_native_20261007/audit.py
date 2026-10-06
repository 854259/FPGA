"""Original finite calibration terminal audit; independently re-read every trace."""
import argparse, hashlib, json, re
from pathlib import Path
import stage

def independently_measure(text, expected, negative, witness):
    assert not re.search('FATAL|ERROR|Segmentation fault|failed to load|cannot open shared object|license checkout failed', text, re.I)
    rows = []
    terminal = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == 'TRACE':
            assert len(parts) == 4 and parts[1].isdigit() and re.fullmatch('[01xz]+', parts[2]) and re.fullmatch('[01xz]+', parts[3])
            rows.append((int(parts[1]), parts[2], parts[3]))
        if parts and parts[0] == 'FINISH':
            assert len(parts) == 3 and all((p.isdigit() for p in parts[1:]))
            terminal.append((len(rows), int(parts[1]), int(parts[2])))
    assert len(rows) == len(expected) and [r[0] for r in rows] == list(range(len(expected)))
    assert len(terminal) == 1 and terminal[0][:2] == (len(rows), len(rows))
    wrong = []
    for i, (_, a, b) in enumerate(rows):
        e = expected[i]
        assert len(a) == len(e['next']) and len(b) == len(e['outputs'])
        if a != e['next'] or b != e['outputs']:
            wrong.append(i)
    assert terminal[0][2] == len(wrong)
    if negative:
        assert wrong and witness['index'] in wrong
        j = witness['index']
        field = witness['field']
        offset = witness['offset']
        actual = witness['actual']
        assert expected[j][field][offset] in '01' and expected[j][field][offset] != actual and (rows[j][1 if field == 'next' else 2][offset] == actual)
    else:
        assert not wrong
    return dict(complete=True, observations=len(rows), mismatches=wrong, negative_detected=negative)

def command_check(unit, tool, spec):
    folder = unit / tool
    r = stage.read(folder / 'COMPLETE.json')
    a = stage.read(folder / 'ATTEMPT.json')
    ident = stage.read(folder / 'CHILD_IDENTITY.json')
    assert r['argv'] == a['argv'] == ident['planned_argv'] == stage.argv(tool, spec) and r['cwd'] == a['cwd'] == str(unit)
    assert r['normal_completion'] and r['exec_confirmed'] and (r['exec_error'] is None) and (r['error'] is None) and (not r['timeout']) and (r['returncode'] == 0) and r['leader_reaped'] and (r['remaining_group'] == []) and (r['signals'] == ['SIGCONT_bound_preexec_child'])
    assert r['cap_s'] == a['cap_s'] == 30 and 0 < r['elapsed_s'] <= 35
    stat = (folder / 'birth_stat.bin').read_bytes()
    cmd = (folder / 'birth_cmdline.bin').read_bytes()
    v = stat.decode().rsplit(')', 1)[1].split()
    pid = int(stat.split(b'(', 1)[0])
    identity = dict(pid=pid, state=v[0], starttime=v[19], pgid=int(v[2]), sid=int(v[3]), command_sha256=hashlib.sha256(cmd).hexdigest())
    assert identity == r['child_identity'] == ident['identity'] and identity['state'] == 'T' and (identity['pgid'] == identity['sid'] == pid) and cmd
    assert ident['stat_sha256'] == hashlib.sha256(stat).hexdigest() and ident['cmdline_sha256'] == hashlib.sha256(cmd).hexdigest()
    assert stage.digest(folder / 'stdout.bin') == r['stdout_sha256'] and (folder / 'stdout.bin').stat().st_size == r['stdout_bytes']
    return r

def audit(root):
    root = Path(root).resolve()
    spec, plan = stage.frozen(root)
    out = root / 'results'
    report = stage.read(out / 'summary.json')
    assert report['schema'] == 'serial_timer_binary_event_native_measurement_v1' and report['complete'] and report['passed'] and (report['error'] is None) and (report['actual_model_requests'] == 0)
    assert report['spec_sha256'] == stage.digest(root / 'RUN_SPEC.json') and report['actual_native_commands'] == 36 and (report['actual_observations'] == spec['planned_observations']) and (report['guard_receipts'] == 73)
    assert 0 < report['elapsed_s'] < spec['stage_timeout_s']
    protected = stage.load('serial_timer_audit_protected', root / 'dependencies/protected_sources.py').check(stage.read(root / 'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'))
    resource = stage.read(root / 'guard/resource_check.json')
    for k in ('model_identity', 'protected', 'slot_owner', 'slot_lock_path', 'model_name'):
        assert resource[k] == spec[k]
    assert [r['label'] for r in report['rows']] == [r['label'] for r in plan['rows']] and len(report['rows']) == 12
    expected_dirs = {row['label'] + '/' + tool for row in plan['rows'] for tool in ('xvlog', 'xelab', 'xsim')}
    assert {f.parent.relative_to(out).as_posix() for f in out.rglob('ATTEMPT.json')} == expected_dirs
    assert {f.parent.relative_to(out).as_posix() for f in out.rglob('COMPLETE.json')} == expected_dirs
    assert sorted((f.name for f in (out / 'guard_receipts').glob('*.json'))) == ['%04d.json' % i for i in range(73)]
    for i in range(73):
        g = stage.read(out / 'guard_receipts' / ('%04d.json' % i))
        assert g['index'] == i and g['spec_sha256'] == report['spec_sha256'] and (g['resource_sha256'] == stage.digest(root / 'guard/resource_check.json')) and (g['resource'] == resource) and (g['protected'] == protected) and (len(g['protected']['groups']) == spec['protected_group_count']) and (g['protected']['source_assets'] == spec['protected_source_assets'])
    rows = []
    for row in plan['rows']:
        unit = out / row['label']
        expected = stage.read(root / 'prepared_cases' / row['relative_root'] / 'expected.json')
        for n in ('candidate.v', 'tb.sv'):
            assert stage.digest(unit / n) == row['source_hashes'][n]
        commands = [command_check(unit, t, spec) for t in ('xvlog', 'xelab', 'xsim')]
        m = independently_measure((unit / 'xsim/stdout.bin').read_text(encoding='utf-8'), expected, row['expect_mismatches'], stage.witness(row, expected))
        recorded = stage.read(unit / 'ROW.json')
        assert recorded in report['rows'] and recorded['commands'] == commands and (recorded['measurement'] == m) and recorded['control_matched']
        rows.append(dict(label=row['label'], measurement=m))
    return dict(schema='serial_timer_binary_event_native_original_audit_v1', evidence_valid=True, native_qualified=True, controls=12, positive_cases=8, negative_mutants=4, native_commands=36, guard_receipts=73, observations=spec['planned_observations'], model_calls=0, rows=rows, source_sha256=report['spec_sha256'], full_score_measured=False, goal_qualified=False, adoption=False, qualification_scope=plan['qualification_scope'])
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    stage.save(args.out, audit(args.root))
    print(json.dumps(dict(audited=True, native_qualified=True)))
