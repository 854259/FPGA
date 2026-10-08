"""AMD-only native qualification of the unchanged Lemmings packet.

Run once under the existing whole-task FIFO and resource guard. Pure and mocked
worker-flow controls must already have passed for this identical source manifest.
This entry runs the original 21 native cases followed by two exact-DUT cases.
The original pure/flow outputs are read and protected, never rerun.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch
import urllib.request

IMPLEMENTATION_SHA = 'b5608f4d48e68a8c6f1fb40119226dd0685ade946abcdb29ef1e45fa7ae852ad'
PAIRED_SHA = '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
ORACLE_SHA = '954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0'
BOUNDED_SHA = '1ba65a00e4493290b3693dbbc8e50ab73dda4b17e57da9cad3c111ac67789b00'
EXTENSION_SHA = 'ff45ab44bd61a7c850d104dfc108fd9127dc9994632cf78702e980c0d5bea63a'
CORE_CASES = 21
CORE_EDA = 63
EXACT_CASES = 2
EXACT_EDA = 6
MAX_CASES = 23
MAX_EDA = 69
NATIVE_CAP = 60
STAGE_CAP = 4500
TAIL_RESERVE = 30


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_network(*args, **kwargs):
    raise RuntimeError('Native qualification makes zero model/network requests')


def stage(args):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    started = time.monotonic()
    root, out = args.root.resolve(), args.out.resolve()
    assert root == Path(__file__).resolve().parent
    assert out != root and out.is_relative_to(root) and not out.exists()
    assert args.stage_cap_s == STAGE_CAP
    manifest = root / 'SOURCE_MANIFEST.json'
    assert sha(manifest) == args.manifest_sha256
    sources = read(manifest)
    assert isinstance(sources, dict) and sources
    assert sources['native_stage.py'] == sha(__file__)
    assert sources['IMPLEMENTATION_MANIFEST.json'] == IMPLEMENTATION_SHA
    implementation = read(root / 'IMPLEMENTATION_MANIFEST.json')
    assert implementation['native_cases'] == CORE_CASES and implementation['max_eda_stages'] == CORE_EDA
    for name, record in implementation['files'].items():
        assert sources[name] == record['sha256']
    assert sources['EXTENSION_MANIFEST.json'] == EXTENSION_SHA
    extension = read(root / 'EXTENSION_MANIFEST.json')
    assert extension['extra_native_cases'] == EXACT_CASES and extension['extra_eda_max'] == EXACT_EDA
    assert extension['per_eda_cap_seconds'] == NATIVE_CAP
    for name, record in extension['files'].items():
        assert sources[name] == record['sha256']
    for path, expected in ((args.paired, PAIRED_SHA), (args.oracle, ORACLE_SHA),
                           (args.bounded, BOUNDED_SHA)):
        target = path.resolve()
        assert target.is_relative_to(root) and not path.is_symlink()
        assert sources[str(target.relative_to(root))] == expected == sha(target)
    pure_path = args.pure_flow_result.resolve()
    assert pure_path.is_relative_to(root) and not args.pure_flow_result.is_symlink()
    pure_out = pure_path.parent
    assert pure_out != root and not out.is_relative_to(pure_out) and not pure_out.is_relative_to(out)
    original_flow_files = {}
    for path in pure_out.rglob('*'):
        assert not path.is_symlink() and path.resolve().is_relative_to(pure_out)
        if path.is_file():
            original_flow_files[str(path.relative_to(pure_out))] = sha(path)

    def frozen():
        assert sha(manifest) == args.manifest_sha256
        for name, digest in sources.items():
            source = root / name
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            assert source.resolve().is_relative_to(root) and not source.is_symlink()
            assert sha(source) == digest, name
        assert sha(pure_path) == args.pure_flow_result_sha256
        current_flow_files = {}
        for path in pure_out.rglob('*'):
            assert not path.is_symlink() and path.resolve().is_relative_to(pure_out)
            if path.is_file():
                current_flow_files[str(path.relative_to(pure_out))] = sha(path)
        assert current_flow_files == original_flow_files, 'Original pure/flow evidence changed'

    frozen()
    pure_flow = read(pure_path)
    assert pure_flow['complete'] is True and pure_flow['passed'] is True
    assert pure_flow['real_model_calls'] == pure_flow['real_eda_commands'] == 0
    assert pure_flow['implementation_manifest_sha256'] == IMPLEMENTATION_SHA
    assert pure_flow['source_manifest_sha256'] == args.manifest_sha256
    assert set(pure_flow['reports']) == {'pure', 'flow'} and pure_flow['error'] is None
    out.mkdir(parents=True, exist_ok=False)
    (out / 'native_processes').mkdir()
    save(out / 'NATIVE_STAGE_INTENT.json', dict(
        real_model_max=0, native_cases=MAX_CASES, core_native_cases=CORE_CASES,
        exact_native_cases=EXACT_CASES, real_eda_max=MAX_EDA,
        native_command_cap_s=NATIVE_CAP, stage_cap_s=STAGE_CAP, retries=0,
        source_manifest_sha256=args.manifest_sha256, source_hashes=sources,
        implementation_manifest_sha256=IMPLEMENTATION_SHA,
        pure_flow_result=str(pure_path), pure_flow_result_sha256=args.pure_flow_result_sha256,
        pure_flow_reexecution=False, original_flow_files=original_flow_files,
        extension_manifest_sha256=EXTENSION_SHA, paired_sha256=PAIRED_SHA,
        oracle_sha256=ORACLE_SHA, bounded_sha256=BOUNDED_SHA))
    sys.path.insert(0, str(root))
    controls = load('lemmings_frozen_native_controls', root / 'controls.py')
    exact = load('lemmings_exact_native_extension', root / 'exact_dut_extension.py')
    paired = load('lemmings_native_paired', args.paired)
    bounded_exec = load('lemmings_native_bounded', args.bounded)
    paired.REPO, paired.INHERITED_ORACLE = root, args.oracle.resolve()
    original_owned = paired.owned_command
    commands, admitted_cases, failure = [], [], None
    reports = {'core21': None, 'exact2': None}
    phase = 'core21'

    def budget(seconds):
        assert time.monotonic() - started + seconds + TAIL_RESERVE < STAGE_CAP

    def before_case(case):
        frozen()
        paired.check_resource(args.resource_check, args.kit)
        assert len(admitted_cases) < MAX_CASES and len(commands) == 3 * len(admitted_cases)
        assert case['name'] not in admitted_cases
        budget(3 * NATIVE_CAP)
        admitted_cases.append(case['name'])

    def owned(argv, cwd, log, cap):
        frozen()
        paired.check_resource(args.resource_check, args.kit)
        assert len(commands) < MAX_EDA and cap == NATIVE_CAP
        assert Path(argv[0]).name in ('xvlog', 'xelab', 'xsim')
        cwd, log = Path(cwd).resolve(), Path(log).resolve()
        assert cwd.is_relative_to(out) and log.is_relative_to(out)
        assert not log.exists()
        budget(cap)
        rec = dict(index=len(commands), argv=[str(item) for item in argv], cap_s=cap,
                   case=admitted_cases[-1], phase=phase, cwd=str(cwd), log=str(log))
        commands.append(rec)
        try:
            prefix = out / 'native_processes' / str(rec['index'])
            bounded = bounded_exec.run(rec['argv'], cwd, prefix, cap)
            rec.update(bounded_receipt=bounded, bounded_receipt_path=str(prefix / 'COMPLETE.json'),
                       bounded_receipt_sha256=sha(prefix / 'COMPLETE.json'))
            stdout = prefix / 'stdout.bin'
            assert sha(stdout) == bounded['stdout_sha256']
            assert stdout.stat().st_size == bounded['stdout_bytes']
            log.write_bytes(stdout.read_bytes())
            assert bounded['normal_completion'] and bounded['exec_confirmed'] and bounded['leader_reaped']
            assert not bounded['timeout'] and not bounded['exec_error'] and not bounded['error']
            assert not bounded['remaining_group']
            result = dict(returncode=bounded['returncode'], timeout=bounded['timeout'],
                          launch_error=bounded['exec_error'], remaining_live_group=bounded['remaining_group'],
                          log=str(log), log_sha256=sha(log), log_bytes=log.stat().st_size,
                          elapsed_s=bounded['elapsed_s'])
            rec['legacy_adapter_result'] = result
            return result
        except BaseException as error:
            rec['error'] = dict(type=type(error).__name__, message=str(error))
            raise
        finally:
            save(out / ('NATIVE_COMMAND_' + str(rec['index']) + '.json'), rec)

    paired.owned_command = owned
    try:
        paired.check_resource(args.resource_check, args.kit, first=True)
        with patch.object(urllib.request, 'urlopen', no_network):
            reports['core21'] = controls.native(paired, root, out / 'native', before_case)
            core_report = reports['core21']
            assert core_report['complete'] and core_report['passed'] and core_report['model_calls'] == 0
            assert core_report['native_cases'] == len(admitted_cases) == CORE_CASES
            assert core_report['eda_calls'] == len(commands) == CORE_EDA
            phase = 'exact2'
            frozen()
            reports['exact2'] = exact.qualify(paired, root, out / 'exact_dut',
                pure_path, args.pure_flow_result_sha256, root, before_case)
            exact_report = reports['exact2']
            assert exact_report['complete'] and exact_report['passed'] and exact_report['actual_model_calls'] == 0
            assert exact_report['extra_cases'] == EXACT_CASES
            assert exact_report['actual_eda_commands'] == EXACT_EDA
        assert len(admitted_cases) == MAX_CASES and len(commands) == MAX_EDA
        paired.check_resource(args.resource_check, args.kit)
        assert time.monotonic() - started < STAGE_CAP
    except BaseException as error:
        failure = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    finally:
        paired.owned_command = original_owned
    source_failure = None
    try:
        frozen()
    except BaseException as error:
        source_failure = dict(type=type(error).__name__, message=str(error))
    summary = dict(complete=True, passed=failure is None and source_failure is None,
                   reports=reports, error=failure, source_error=source_failure,
                   real_model_calls=0, real_eda_commands=len(commands), native_commands=commands,
                   admitted_cases=admitted_cases, simulated_http_calls=0,
                   pure_flow_reexecution=False, source_manifest_sha256=args.manifest_sha256,
                   implementation_manifest_sha256=IMPLEMENTATION_SHA,
                   pure_flow_result_sha256=args.pure_flow_result_sha256,
                   sources_unchanged=source_failure is None, original_flow_unchanged=source_failure is None,
                   original_flow_files=original_flow_files, extension_manifest_sha256=EXTENSION_SHA,
                   native_cases_admitted=len(admitted_cases), core_native_cases=CORE_CASES,
                   exact_native_cases=EXACT_CASES,
                   elapsed_s=time.monotonic() - started, stage_cap_s=STAGE_CAP,
                   scoring_run=False, accuracy_measured=False)
    save(out / 'NATIVE_STAGE_RESULT.json', summary)
    print(json.dumps(dict(passed=summary['passed'], real_eda_commands=len(commands),
                          error=failure, source_error=source_failure)))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'out', 'paired', 'oracle', 'bounded', 'kit', 'resource-check', 'pure-flow-result'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--pure-flow-result-sha256', required=True)
    parser.add_argument('--stage-cap-s', type=int, default=STAGE_CAP)
    sys.exit(stage(parser.parse_args()))
