"""AMD-only delta checks: synthetic observations, then one native vector probe."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
KIT = Path('/workspace/team/tasks/autodl-rtl-kit/project')
PROMPT = ('I would like you to implement a module named TopModule with the following\n'
          'interface. All input and output ports are one bit unless otherwise specified.\n'
          '- input x (2 bits)\n- output y\n\n'
          'The module should implement the Karnaugh map below.\n'
          'x[0]\nx[1] 0 1\n0 | 0 | 1 |\n1 | 1 | 0 |\n')
CODE = 'module TopModule(input [1:0] x, output y); assign y=x[0]; endmodule\n'
LOG = ('TABLE_FIRST row=2 expected=1 observed=0\n'
       'TABLE_POINT row=2 expected=1 observed=0\n'
       'TABLE_POINT row=3 expected=0 observed=1\n'
       'TABLE_POINT row=3 expected=0 observed=1\n'
       'TABLE_POINT row=2 expected=1 observed=0\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def frozen():
    for name, digest in json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text()).items():
        assert sha(ROOT / name) == digest, name


def pure():
    import table_feedback as feedback
    parsed = feedback.parse(PROMPT)
    assert parsed['checks'] == 8
    points = feedback.counterexamples(LOG, parsed, 4)
    assert points == [dict(inputs={'x': 2}, output='y', expected=1, observed='0'),
                      dict(inputs={'x': 3}, output='y', expected=0, observed='1')]
    text = feedback.format_feedback(points, parsed, 4)
    assert "x=2'b10" in text and "x=2'b11" in text and '4 mismatches in 8 checks' in text
    assert text.count('inputs x=') == 2
    rejected = []
    for name, log, count in [
            ('missing_observation', LOG, 5),
            ('ambiguous_first', LOG + LOG.splitlines()[0] + '\n', 4),
            ('wrong_first', LOG.replace('TABLE_FIRST row=2', 'TABLE_FIRST row=1'), 4),
            ('wrong_expected', LOG.replace('TABLE_POINT row=2 expected=1', 'TABLE_POINT row=2 expected=0'), 4),
            ('out_of_range', LOG.replace('TABLE_POINT row=3', 'TABLE_POINT row=9'), 4),
            ('malformed', LOG.replace('observed=1', 'observed=2'), 4),
            ('third_visit', LOG + 'TABLE_POINT row=2 expected=1 observed=0\n', 5)]:
        try:
            feedback.counterexamples(log, parsed, count)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError('accepted corrupted observation: ' + name)
    unknown = LOG.replace('observed=0', 'observed=x').replace('observed=1', 'observed=z')
    values = feedback.counterexamples(unknown, parsed, 4)
    assert [p['observed'] for p in values] == ['x', 'z']
    tb = feedback.render_tb(parsed, 'synthetic')
    assert tb.count('$display("TABLE_POINT') == 8 and 'module TopModule' not in tb
    frozen()
    result = dict(passed=True, positive_checks=['distinct_measured_points', 'binary_width',
                  'bidirectional_deduplication', 'unknown_observation', 'probe_logging'],
                  rejected=rejected, model_calls=0, eda_calls=0)
    save(ROOT / 'PURE_RESULT.json', result)
    print(json.dumps(result))


def native(resource):
    import table_feedback as feedback
    import bounded_owned_exec
    assert json.loads((ROOT / 'PURE_RESULT.json').read_text())['passed'] is True
    loader = importlib.util.spec_from_file_location('delta_paired', ROOT / 'dependencies/paired_checkpoint.py')
    paired = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(paired)
    paired.REPO = ROOT
    paired.INHERITED_ORACLE = ROOT / 'dependencies/probe_runner.py'
    commands = []
    (ROOT / 'native_processes').mkdir()

    def owned(argv, cwd, log, cap):
        frozen()
        paired.check_resource(resource, KIT)
        assert len(commands) < 3 and cap == 60
        assert Path(argv[0]).name in ('xvlog', 'xelab', 'xsim')
        out = ROOT / 'native_processes' / str(len(commands))
        rec = bounded_owned_exec.run(argv, cwd, out, cap)
        commands.append(rec)
        Path(log).write_bytes((out / 'stdout.bin').read_bytes())
        assert rec['normal_completion'] and rec['returncode'] == 0
        assert rec['exec_confirmed'] and rec['leader_reaped'] and not rec['remaining_group']
        return dict(returncode=rec['returncode'], timeout=rec['timeout'], launch_error=rec['exec_error'],
                    remaining_live_group=rec['remaining_group'], log=str(log), log_sha256=sha(log),
                    elapsed_s=rec['elapsed_s'])

    paired.owned_command = owned
    failure = None
    try:
        paired.check_resource(resource, KIT, first=True)
        text = feedback.check(PROMPT, CODE, ROOT / 'native', 0, paired, 'synthetic', ROOT)
        assert '4 mismatches in 8 checks' in text
        assert "x=2'b10" in text and "x=2'b11" in text and text.count('inputs x=') == 2
        assert len(commands) == 3
        frozen()
        paired.check_resource(resource, KIT)
    except BaseException as exc:
        failure = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    result = dict(complete=True, passed=failure is None, error=failure, native_commands=commands,
                  model_calls=0, eda_calls=len(commands), accuracy_measured=False)
    save(ROOT / 'NATIVE_RESULT.json', result)
    print(json.dumps(result))
    return 0 if failure is None else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('pure', 'native', 'observe'))
    parser.add_argument('--resource-check', type=Path)
    args = parser.parse_args()
    frozen()
    save(ROOT / (args.mode.upper() + '_INTENT.json'), dict(mode=args.mode, model_max=0,
         eda_max=3 if args.mode != 'pure' else 0, source_manifest_sha256=sha(ROOT / 'SOURCE_MANIFEST.json')))
    if args.mode == 'pure':
        pure()
    elif args.mode == 'native':
        assert args.resource_check is not None
        sys.exit(native(args.resource_check))
    else:
        assert args.resource_check is not None
        import terminal_outer
        result = terminal_outer.run([sys.executable, '-B', str(Path(__file__).resolve()), 'native',
             '--resource-check', str(args.resource_check)], ROOT, ROOT / 'external',
             270, 30, [ROOT / 'NATIVE_RESULT.json'], 2013333)
        print(json.dumps(dict(passed=result['passed'], elapsed_s=result['measured_complete_elapsed_s'], error=result['error'])))
        sys.exit(0 if result['passed'] else 1)
