"""AMD-only controlled flow checks for the isolated static-elaboration patch.

All HTTP, compiler, elaborator, feedback and activity calls below are simulated.
No benchmark input, real model, EDA, FIFO or actual model ledger is used.
"""
import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
BASE = Path('/workspace/team/runs/fpga_owner/first_system_emission_fixed15_20261007_v1')
PRIOR = Path('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1')
HELPERS = Path('/workspace/team/runs/fpga_owner/framing_cp8_113_terminal_monitor_20261007_v1')
PREVIOUS = Path('/workspace/team/runs/fpga_teammate/static_elaboration_flow12_20261008_v1')
PREVIOUS_HASHES = {
    'SOURCE_MANIFEST.json': '88460c4294054109dd626dc751725e64d2c9ceed0b4e85cb8538cad3a253fe4f',
    'RESULTS.json': 'f9590a0fafce25946f1cdba78f95bee998cf240c448c9779f67b3b90a34f80ae',
    'CONTROL_RESULTS/C_success/CONTROL_EXPECTATION.json': 'a968a83b8e7bd5afedf1bc2cadd457c24b2750845ed7c8b688279d38a467ffc1',
}
DEST = Path('/workspace/team/runs/fpga_teammate/static_elaboration_flow12_20261008_v2')
PATCH_SHA = '9b174d44f91d64009e119a09cbe1322a20c6648a8bc533af2bf4d2825f8edac4'
OUTPUTS = {
    'package/agent/map_runtime.py': 'c8d4a369611bd97aca61749ae885e9428cad8c5362d5a7ae8023ddd2a708d40e',
    'baseline_worker.py': 'cdca09cb49e7676a7dcbcc803bff88cf29d2b7aeb7494c4f06d3acb160438876',
}
SUPPORT = [n+'.py' for n in (
    'prompt_map', 'point_feedback', 'edge_dispatch', 'edge_feedback', 'phase_feedback',
    'phase_context', 'edge_contract', 'priority_contract', 'shift_contract', 'reserved_keywords')]
SUPPORT += ['package/baseline.py', 'package/skill/rtl-generation/SKILL.md',
            'package/skill/rtl-feedback-repair/SKILL.md']
HELPER_HASHES = {
    'terminal_outer.py': '569b70a5881ae97267e4035a71a3371d753b3487bbf0efd4f09c3d838bc993b1',
    'bounded_owned_exec.py': '1ba65a00e4493290b3693dbbc8e50ab73dda4b17e57da9cad3c111ac67789b00',
    'owned_tree_cleanup.py': '5dd37bb39db4616b3411a51878124987ce51f0a289174b81dad0d81e34b134ad',
}
MODEL = 'SIMULATED_NO_MODEL'
PROMPT = 'Sample d into q on each rising edge of clk.'
IFACE = 'module TopModule(input clk, input d, output reg q); endmodule'
GOOD = 'module TopModule(input clk, input d, output reg q); always @(posedge clk) q <= d; endmodule'
BAD_DECL = 'module TopModule(input clk, input d, output q); always @(posedge clk) q <= d; endmodule'
ANSI_DIAG = 'ERROR: [VRFC 10-1280] procedural assignment to a non-register q'
ELAB_DIAG = 'ERROR: [SIMULATED_ELAB] incompatible procedural drivers in current candidate'
CASES = [
    ('P_success', 'P', 1, 1, 1, 1, None),
    ('C_ansi_success', 'C', 1, 2, 0, 0, None),
    ('P_ansi_success', 'P', 1, 2, 1, 0, None),
    ('P_elab_repair', 'P', 2, 2, 2, 1, None),
    ('P_ansi_elab_repair', 'P', 2, 3, 2, 1, None),
    ('P_exhausted', 'P', 2, 2, 2, 0, None),
    ('P_missing', 'P', 1, 1, 0, 0, 'RuntimeError'),
    ('P_timeout', 'P', 1, 1, 1, 0, 'RuntimeError'),
    ('P_launch_error', 'P', 1, 1, 1, 0, 'RuntimeError'),
    ('P_survivor', 'P', 1, 1, 1, 0, 'RuntimeError'),
    ('P_source_mutation', 'P', 1, 1, 1, 0, 'AssertionError'),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def originals():
    assert all(sha(PREVIOUS/n) == h for n, h in PREVIOUS_HASHES.items())
    for root, expected_count in [(BASE, 106), (PRIOR, 120)]:
        spec = read(root/'RUN_SPEC.json')
        assert len(spec['source_hashes']) == expected_count
        assert all(sha(root/n) == h for n, h in spec['source_hashes'].items())
    proc = Path('/proc/2013333')
    fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
    assert fields[19] == '823869819' and fields[0] not in ('Z', 'X')
    assert sha(proc/'cmdline') == '2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'


def prepare():
    assert not DEST.exists()
    originals()
    assert sha(ROOT/'static_elaboration.patch') == PATCH_SHA
    source_spec = read(BASE/'RUN_SPEC.json')
    # Apply exact zero-context hunks as pure files, without importing production.
    bodies = {n: (BASE/n).read_text() for n in OUTPUTS}
    offsets = dict.fromkeys(OUTPUTS, 0)
    target = None
    lines = (ROOT/'static_elaboration.patch').read_text().splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if lines[i].startswith('+++ b/'):
            target = lines[i][6:].strip()
        elif lines[i].startswith('@@'):
            m = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', lines[i])
            assert m and target in bodies
            old, new = [], []
            i += 1
            while i < len(lines) and not lines[i].startswith(('@@', 'diff --git')):
                line = lines[i]
                assert line[0] in '+- '
                if line[0] != '+':
                    old.append(line[1:])
                if line[0] != '-':
                    new.append(line[1:])
                i += 1
            data = bodies[target].splitlines(keepends=True)
            pos = int(m[1])-1+offsets[target]
            assert data[pos:pos+len(old)] == old and len(old) == int(m[2]) and len(new) == int(m[4])
            data[pos:pos+len(old)] = new
            offsets[target] += len(new)-len(old)
            bodies[target] = ''.join(data)
            continue
        i += 1
    assert all(hashlib.sha256(bodies[n].encode()).hexdigest() == h for n, h in OUTPUTS.items())
    for body in bodies.values():
        ast.parse(body)
    assert all(sha(BASE/n) == source_spec['source_hashes'][n] for n in SUPPORT+list(OUTPUTS))
    assert all(sha(HELPERS/n) == h for n, h in HELPER_HASHES.items())
    DEST.mkdir()
    for name, body in bodies.items():
        p = DEST/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    for name in SUPPORT:
        p = DEST/name
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BASE/name, p)
    for name in HELPER_HASHES:
        shutil.copyfile(HELPERS/name, DEST/name)
    shutil.copyfile(__file__, DEST/'flow_controls.py')
    shutil.copyfile(ROOT/'static_elaboration.patch', DEST/'static_elaboration.patch')
    save(DEST/'RUN_SPEC.json', dict(model=MODEL, identity='static_elaboration_flow12_synthetic',
        dependencies_cloud=str(DEST/'UNUSED_NO_ORACLE'), activity_root=str(DEST/'SIMULATED_LEDGER')))
    save(DEST/'PLAN.json', dict(kind='controlled flow only; all transports and tools simulated',
        cases=CASES, scenarios=len(CASES), reused_control='C_success from v1', previous_hashes=PREVIOUS_HASHES,
        correction='Exact extracted candidate includes the original baseline trailing LF; production and fixtures unchanged.',
        real_model_calls=0, real_eda_calls=0, fifo_calls=0,
        max_simulated_requests_per_case=2, repair=1, retries=0,
        outer_cap_s=90, cleanup_reserve_s=10, single_observed_execution=True,
        changed_sources=OUTPUTS, original_sources={n: source_spec['source_hashes'][n] for n in SUPPORT+list(OUTPUTS)},
        prior_spec_sha256=sha(PRIOR/'RUN_SPEC.json'), helper_sources=HELPER_HASHES,
        failure='Record original failed control and stop; no silent rerun or fixture change to obtain a pass.'))
    save(DEST/'SOURCE_MANIFEST.json', {str(p.relative_to(DEST)): sha(p) for p in DEST.rglob('*') if p.is_file()})
    print(json.dumps(dict(prepared=True, manifest_sha256=sha(DEST/'SOURCE_MANIFEST.json'))))


def frozen():
    assert ROOT == DEST
    manifest = read(ROOT/'SOURCE_MANIFEST.json')
    assert all(sha(ROOT/n) == h for n, h in manifest.items())
    assert read(ROOT/'PLAN.json')['cases'] == [list(v) for v in CASES]
    originals()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def one(case, worker):
    name, arm, want_http, want_compile, want_elab, want_feedback, want_error = case
    calls = dict(http=[], compile=[], elaborate=[], feedback=[], activity=[], gates=0, idle=0)
    result_root = ROOT/'CONTROL_RESULTS'/name
    args = types.SimpleNamespace(arm=arm, out=result_root, kit=ROOT/'SYNTHETIC_KIT',
                                 task='synthetic', resource_check=ROOT/'SIMULATED_RESOURCE')
    previous = (Path.cwd(), subprocess.run, urllib_request.urlopen)
    runtime_load = worker.load

    def runtime_loader(module, path):
        runtime = runtime_load(module, path)
        runtime.vivado_tool = lambda tool: None if name == 'P_missing' and tool == 'xelab' else '/SIMULATED/'+tool
        return runtime

    def reject(*a, **k):
        raise AssertionError('Unexpected real transport or subprocess')

    def http(request, *a, **kw):
        body = json.loads(request.data)
        assert kw == dict(timeout=300) and not a and len(calls['http']) < want_http
        assert body['model'] == MODEL and body['max_tokens'] == 8192 and body['temperature'] == 0 and body['top_p'] == 1
        index = len(calls['http'])
        expected_user = PROMPT+'\n\nInterface:\n'+IFACE
        if index:
            expected_user += '\nPrevious candidate:\n'+GOOD+'\n\nCandidate diagnostics:\n'+ELAB_DIAG
        assert body['messages'][1] == dict(role='user', content=expected_user)
        calls['http'].append(body)
        code = BAD_DECL if 'ansi' in name and index == 0 else GOOD
        payload = dict(id='SIMULATED', choices=[dict(message=dict(content=code), finish_reason='stop')],
                       usage=dict(prompt_tokens=0, completion_tokens=0))
        return io.BytesIO(json.dumps(payload).encode())

    def owned(argv, cwd, log, cap):
        assert cap == 60
        tool = Path(argv[0]).name
        source = (Path(cwd)/'candidate.sv').read_text()
        rec = dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[], simulated=True)
        diag = ''
        if tool == 'xvlog':
            assert argv[1:] == ['--sv', str(Path(cwd)/'candidate.sv')]
            calls['compile'].append(source)
            if source == BAD_DECL+'\n':
                rec['returncode'], diag = 1, ANSI_DIAG
        else:
            assert tool == 'xelab' and arm == 'P' and argv[1:] == ['TopModule', '-s', 'candidate_static']
            calls['elaborate'].append(source)
            assert source == GOOD+'\n'
            if (name in ('P_elab_repair', 'P_ansi_elab_repair') and len(calls['elaborate']) == 1) or name == 'P_exhausted':
                rec['returncode'], diag = 1, ELAB_DIAG
            elif name == 'P_timeout':
                rec.update(timeout=True, returncode=None)
            elif name == 'P_launch_error':
                rec.update(launch_error='SIMULATED', returncode=None)
            elif name == 'P_survivor':
                rec['remaining_live_group'] = ['SIMULATED']
            elif name == 'P_source_mutation':
                (Path(cwd)/'candidate.sv').write_text(source+'\n// SIMULATED unexpected mutation')
        Path(log).write_text(diag)
        return rec

    def gate(*a):
        calls['gates'] += 1

    def idle(*a):
        calls['idle'] += 1

    def feedback(*a, **k):
        calls['feedback'].append(dict(code=a[1], attempt=a[3]))
        return ''

    activity = types.SimpleNamespace(append=lambda *a, **k: calls['activity'].append([str(v) for v in a[:3]]))
    paired = types.SimpleNamespace(check_resource=gate, model_idle=idle, owned_command=owned)
    failure = None
    with patch.object(worker, 'load', runtime_loader), patch.object(worker, 'functional_feedback', feedback), \
         patch.object(urllib_request, 'urlopen', http), patch.object(subprocess, 'run', reject), \
         patch.object(socket, 'socket', reject), patch.dict(sys.modules, {'activity': activity}):
        try:
            worker.run_worker(args, paired)
        except (RuntimeError, AssertionError) as exc:
            failure = dict(type=type(exc).__name__, message=str(exc))
        assert subprocess.run is reject and urllib_request.urlopen is http and Path.cwd() == previous[0]
    assert subprocess.run is previous[1] and urllib_request.urlopen is previous[2]
    measured = [len(calls[k]) for k in ['http', 'compile', 'elaborate', 'feedback']]
    expected = [want_http, want_compile, want_elab, want_feedback]
    save(result_root/'CONTROL_OBSERVED.json', dict(case=case, measured=measured, failure=failure, calls=calls))
    assert measured == expected, (name, measured, expected)
    assert (failure['type'] if failure else None) == want_error, (name, failure)
    assert calls['gates'] == want_http+want_compile+want_elab+want_feedback
    assert calls['idle'] == want_http and len(calls['activity']) == want_http*2
    assert read(result_root/'requests.json')[-1]['response_received']
    if want_elab:
        journal = read(result_root/'elaboration_journal.json')
        assert len(journal) == want_elab and all(row['simulated'] for row in journal)
        for i, row in enumerate(journal):
            folder = result_root/'elaboration_receipts'/str(i)
            assert sha(folder/'source_before.sv') == row['source_before_sha256']
            assert sha(folder/'source_after.sv') == row['source_after_sha256']
            assert sha(folder/'owned_elaboration.log') == row['log_sha256']
    else:
        assert not (result_root/'elaboration_journal.json').exists()
    save(result_root/'CONTROL_EXPECTATION.json', dict(case=case, measured=measured,
        expected_failure=failure, calls=calls, real_model=0, real_eda=0, real_activity_ledger=0))
    return dict(name=name, passed=True, simulated_http=want_http, simulated_xvlog=want_compile,
                simulated_xelab=want_elab, expected_error=want_error)


def run():
    frozen()  # All source bytes and original frozen inputs checked before project import.
    assert not (ROOT/'CONTROL_INTENT.json').exists()
    save(ROOT/'CONTROL_INTENT.json', dict(manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'), scenarios=len(CASES)))
    fixtures = ROOT/'SYNTHETIC_KIT/bench/tasks_veval/synthetic'
    fixtures.mkdir(parents=True)
    (fixtures/'prompt.txt').write_text(PROMPT)
    (fixtures/'interface.txt').write_text(IFACE)
    (ROOT/'CONTROL_RESULTS').mkdir()
    worker = load('static_elaboration_control_worker', ROOT/'baseline_worker.py')
    rows, failure = [], None
    try:
        with patch.dict(os.environ, {'MODEL_NAME': MODEL, 'RTL_REPAIRS': '1', 'RTL_MAX_TOKENS': '8192',
                                    'RTL_TEMPERATURE': '0', 'LLM_BASE_URL': 'http://127.0.0.1:8000/v1'}):
            for case in CASES:
                rows.append(one(case, worker))
        assert read(PREVIOUS/'CONTROL_RESULTS/C_success/requests/0/request.json') == read(ROOT/'CONTROL_RESULTS/P_success/requests/0/request.json')
        assert read(ROOT/'CONTROL_RESULTS/C_ansi_success/requests/0/request.json') == read(ROOT/'CONTROL_RESULTS/P_ansi_success/requests/0/request.json')
        frozen()
    except BaseException as exc:
        import traceback
        failure = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    save(ROOT/'RESULTS.json', dict(passed=failure is None and len(rows)==len(CASES), rows=rows, error=failure,
        reused_control=dict(name='C_success', root=str(PREVIOUS), bound_hashes=PREVIOUS_HASHES),
        real_model_calls=0, real_eda_calls=0, fifo_calls=0, synthetic_only=True,
        native_qualified=False, scoring_qualified=False))
    print(json.dumps(dict(passed=failure is None, scenarios=len(rows), error=failure)))
    return 0 if failure is None else 1


def observe():
    frozen()
    assert not (ROOT/'OBSERVE_INTENT.json').exists()
    save(ROOT/'OBSERVE_INTENT.json', dict(manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'), cap_s=90))
    import terminal_outer
    rec = terminal_outer.run([sys.executable, '-B', str(ROOT/'flow_controls.py'), 'run'], ROOT,
        ROOT/'external', 90, 10, [ROOT/'RESULTS.json'], 2013333)
    print(json.dumps(dict(passed=rec['passed'], elapsed_s=rec['measured_complete_elapsed_s'], error=rec['error'])))
    return 0 if rec['passed'] else 1


if __name__ == '__main__':
    import urllib.request as urllib_request
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'run', 'observe'])
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare()
    else:
        sys.exit(run() if args.mode == 'run' else observe())
