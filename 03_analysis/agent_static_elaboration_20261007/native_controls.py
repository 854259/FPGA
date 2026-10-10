"""AMD-only native candidate-elaboration controls; synthetic replies, no model calls."""
import argparse
import ast
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import types
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
FLOW = Path('/workspace/team/runs/fpga_teammate/static_elaboration_flow12_20261008_v2')
DEST = Path('/workspace/team/runs/fpga_teammate/static_elaboration_strict4_20261008_v2')
ORIGINAL = Path('/workspace/team/runs/fpga_teammate/static_elaboration_native5_20261008_v1')
PRIOR = Path('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1')
KIT = Path('/workspace/team/tasks/autodl-rtl-kit/project')
MODEL = 'SIMULATED_NO_MODEL'
REAL_MODEL = 'Qwen3.6-27B-Q4_K_M'
OWNER = 'codex_teammate_static_elaboration_strict4_20261008_v2'
GUARD_SHA = 'fdd22d547cab6884b071044a7a1f26f847d8937618a55a201838ff10f77ff9d9'
PAIRED_SHA = '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
TOOLS = {n: '/workspace/AMD/2026.1/Vivado/bin/'+n for n in ('xvlog', 'xelab')}
TOOL_SHA = '8894701f101f74c8c1b5fa5debadadfbe73c0e3a587abfe9a6eb69b99183fdf2'
GOOD = 'module TopModule(input clk, input d, output reg q); always @(posedge clk) q <= d; endmodule'
COMB = 'module TopModule(input clk, input d, output reg q); reg next_q; always_comb next_q = d; always_ff @(posedge clk) q <= next_q; endmodule'
MULTI = 'module TopModule(input clk, input d, output reg q); always_comb q = d; always_ff @(posedge clk) q <= ~d; endmodule'
ANSI = GOOD.replace('output reg q', 'output q')
ANSI_MULTI = MULTI.replace('output reg q', 'output q')
PROMPT = 'Sample d into q on each rising edge of clk.'
IFACE = 'module TopModule(input clk, input d, output reg q); endmodule'
CASES = [
    ('strict_separate', COMB, {'P': [1, 1, 1, 1]}),
    ('strict_conflict', MULTI, {'P': [2, 2, 2, 1]}),
    ('ansi_valid', ANSI, {'P': [1, 2, 1, 0]}),
    ('ansi_invalid', ANSI_MULTI, {'P': [2, 3, 2, 1]}),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_check(root):
    for rel, digest in read(root/'SOURCE_MANIFEST.json').items():
        assert sha(root/rel) == digest, rel


def old_sources():
    rejected = Path('/workspace/team/runs/fpga_teammate/static_elaboration_strict4_20261008_v1')
    assert sha(rejected/'SOURCE_MANIFEST.json') == '1edf7a7ca5a526bcb6a7e3e21da282bc985aee5bfbe3a95b8e70cab6a28f2006'
    source_check(rejected)
    assert not any((rejected/n).exists() for n in ('guard', 'OBSERVE_INTENT.json', 'STAGE_INTENT.json', 'results'))
    assert read(Path('/workspace/team/task_fifo/tickets/00000119.json'))['state'] == 'failed_released_after_inspection'
    assert 400 < 415 < 8*60-60
    assert sha(ORIGINAL/'SOURCE_MANIFEST.json') == '8573e063b729a14bfcb97e0228bbb0aec1702ee477b0b9b522c63290645f43ac'
    source_check(ORIGINAL)
    prior = read(ORIGINAL/'results/summary.json')
    assert sha(ORIGINAL/'results/summary.json') == 'ac2f4b60ceaa6d4df45467dcb97628c181a9bd8f07906531e851beaf7f116013'
    assert not prior['passed'] and prior['real_eda_calls'] == 9 and sum(len(r['calls']['http']) for r in prior['rows']) == 6
    assert read(Path('/workspace/team/task_fifo/tickets/00000117.json'))['state'] == 'failed_released_after_inspection'
    assert sha(FLOW/'SOURCE_MANIFEST.json') == 'c9b527b2c3c747c13704e3cbd2cc025f0d68d81ada819e6888c4a65425789d2b'
    source_check(FLOW)
    assert sha(PRIOR/'RUN_SPEC.json') == 'dbce8beb5342fe590078dd8eafb29a4d762575a58db2599cab9942f453331c4b'
    assert all(sha(PRIOR/n) == h for n, h in read(PRIOR/'RUN_SPEC.json')['source_hashes'].items())
    assert sha(PRIOR/'guard_wrapper.py') == GUARD_SHA
    assert sha(PRIOR/'dependencies/paired_checkpoint.py') == PAIRED_SHA
    assert all(sha(p) == TOOL_SHA for p in TOOLS.values())


def prepare():
    assert not DEST.exists()
    old_sources()
    ast.parse(Path(__file__).read_text())
    DEST.mkdir()
    selected = {n: h for n, h in read(FLOW/'SOURCE_MANIFEST.json').items()
                if n not in ('PLAN.json', 'RUN_SPEC.json', 'flow_controls.py')}
    for n, h in selected.items():
        target = DEST/n
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FLOW/n, target)
        assert sha(target) == h
    shutil.copyfile(PRIOR/'guard_wrapper.py', DEST/'guard_wrapper.py')
    shutil.copyfile(PRIOR/'dependencies/paired_checkpoint.py', DEST/'paired_checkpoint.py')
    shutil.copyfile(__file__, DEST/'native_controls.py')
    fixtures = DEST/'SYNTHETIC_KIT/bench/tasks_veval/synthetic'
    fixtures.mkdir(parents=True)
    (fixtures/'prompt.txt').write_text(PROMPT)
    (fixtures/'interface.txt').write_text(IFACE)
    save(DEST/'RUN_SPEC.json', dict(model=MODEL, identity='static_elaboration_strict4_synthetic',
        dependencies_cloud=str(DEST/'UNUSED_NO_ORACLE'), activity_root=str(DEST/'SIMULATED_LEDGER')))
    save(DEST/'PLAN.json', dict(cases=CASES, structures=4, paired_worker_outputs=0, candidate_worker_outputs=4,
        real_model_calls=0, simulated_HTTP_max=6, xvlog_max=8, xelab_max=6, real_tools_max=14,
        prior_117_real_tools=9, prior_117_simulated_HTTP=6, aggregate_real_tools_max=23, aggregate_simulated_HTTP_max=12,
        prior_outer_elapsed_s=15.47378627769649, aggregate_observed_stage_seconds_max=415.4737862776965,
        aggregate_time_scope='Sum of original observed stage interval plus this bounded outer stage; excludes preparation and between-stage gap. Not full wall time.',
        tool_cap_seconds=60, worker_cap_seconds=300, stage_child_cap_seconds=370,
        stage_outer_cap_seconds=400, cleanup_reserve_seconds=30, guard_cap_seconds=415, slot_minutes=8,
        prior119='Argument validation rejected guard430 with slot8 before guard/stage/model/EDA; original files retained. Only guard cap reduced to415 to leave65s lease reserve.',
        generation_max_tokens=8192, generation_max_requests=2, repair=1, retries=0,
        production_sources_unchanged=True, original117_failure_preserved=True,
        reused='Original117 ordinary positive C/P and C bypass;12 simulated-flow controls. This is four P controls, not new C/P pairs.',
        native_qualification='Only strict-SV and ANSI exit compile/elaboration behavior; ordinary-always multi-driver blind spot retained. No behavioral simulation or benchmark score.',
        supervision_scope='Real pinned bounded_owned_exec supplies native command receipts through the existing worker owned_command interface; not a new test of legacy paired_checkpoint.owned_command.',
        failure='Stop on first unexpected tool/control/supervision outcome. Preserve all outputs; no resampling, fixture adjustment or implicit retry.',
        source_origin=str(FLOW), source_origin_manifest_sha256=sha(FLOW/'SOURCE_MANIFEST.json'),
        tool_wrappers={n:dict(path=p,sha256=sha(p)) for n,p in TOOLS.items()}))
    save(DEST/'SOURCE_MANIFEST.json', {str(p.relative_to(DEST)):sha(p) for p in sorted(DEST.rglob('*')) if p.is_file()})
    print(json.dumps(dict(prepared=True, manifest_sha256=sha(DEST/'SOURCE_MANIFEST.json'))))


def frozen():
    assert ROOT == DEST
    source_check(ROOT)
    old_sources()
    assert read(ROOT/'PLAN.json')['cases'] == [[n, code, expect] for n, code, expect in CASES]


def case_run(name, arm, resource):
    frozen()
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    _, initial, expected = next(c for c in CASES if c[0] == name)
    worker = load('native_candidate_worker', ROOT/'baseline_worker.py')
    paired_source = load('native_resource_checks', ROOT/'paired_checkpoint.py')
    import bounded_owned_exec
    resource = Path(resource).resolve()
    paired_source.check_resource(resource, KIT)
    args = types.SimpleNamespace(task='synthetic', arm=arm, kit=ROOT/'SYNTHETIC_KIT',
                                 out=ROOT/'results'/name/arm, resource_check=resource)
    calls = dict(http=[], tools=[], feedback=[])
    original_open = urllib.request.urlopen
    previous = (Path.cwd(), subprocess.run, original_open)
    runtime_load = worker.load
    latest_diagnostic = ''

    def runtime_loader(module, path):
        runtime = runtime_load(module, path)
        runtime.vivado_tool = lambda tool: TOOLS[tool]
        return runtime

    def transport(request, *a, **kw):
        assert isinstance(request, urllib.request.Request) and request.get_method() == 'POST'
        assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
        assert kw == dict(timeout=300) and not a and len(calls['http']) < expected[arm][0]
        body = json.loads(request.data)
        assert body['model'] == MODEL and body['max_tokens'] == 8192 and body['temperature'] == 0 and body['top_p'] == 1
        index = len(calls['http'])
        user = PROMPT+'\n\nInterface:\n'+IFACE
        if index:
            # Original ANSI repair may have changed the current candidate before elaboration.
            prior = MULTI+'\n' if name == 'ansi_invalid' else initial+'\n'
            assert latest_diagnostic
            user += '\nPrevious candidate:\n'+prior+'\nCandidate diagnostics:\n'+latest_diagnostic
        assert body['messages'][1] == dict(role='user', content=user)
        calls['http'].append(body)
        payload = dict(id='SIMULATED', choices=[dict(message=dict(content=GOOD if index else initial), finish_reason='stop')],
                       usage=dict(prompt_tokens=0, completion_tokens=0))
        return io.BytesIO(json.dumps(payload).encode())

    def owned(argv, cwd, log, cap):
        nonlocal latest_diagnostic
        tool = Path(argv[0]).name
        assert tool in TOOLS and argv[0] == TOOLS[tool] and cap == 60 and len(calls['tools']) < 5
        assert Path(cwd).resolve().parent == (args.out/'work').resolve()
        assert argv[1:] == (['--sv', str(Path(cwd)/'candidate.sv')] if tool == 'xvlog'
                            else ['TopModule', '-s', 'candidate_static'])
        if tool == 'xelab':
            assert arm == 'P'
        native_out = args.out/'native_processes'/str(len(calls['tools']))
        native_out.parent.mkdir(exist_ok=True)
        rec = bounded_owned_exec.run(argv, cwd, native_out, cap)
        Path(log).write_bytes((native_out/'stdout.bin').read_bytes())
        calls['tools'].append(dict(tool=tool, process=rec, source_sha256=sha(Path(cwd)/'candidate.sv')))
        save(args.out/('NATIVE_COMMAND_'+str(len(calls['tools']))+'.json'), calls['tools'][-1])
        assert rec['exec_confirmed'] and rec['leader_reaped'] and rec['normal_completion']
        assert not rec['timeout'] and not rec['exec_error'] and not rec['error'] and not rec['remaining_group']
        if tool == 'xelab':
            output = Path(log).read_text(errors='replace')
            lines = [s for s in output.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
            latest_diagnostic = '\n'.join(lines)[:2048] or output[-2048:]
        return dict(returncode=rec['returncode'], timeout=rec['timeout'], launch_error=rec['exec_error'],
                    remaining_live_group=rec['remaining_group'], elapsed_s=rec['elapsed_s'],
                    identity=rec['child_identity'], exec_confirmed=True, reaped=True, native=True)

    def gate(*ignored):
        frozen()
        paired_source.check_resource(resource, KIT)

    def idle(base, model):
        assert base == 'http://127.0.0.1:8000/v1' and model == MODEL
        # Metadata-only GETs use the original transport; never post a real generation request.
        with patch.object(urllib.request, 'urlopen', original_open):
            paired_source.model_idle(base, REAL_MODEL)

    def feedback(*a, **k):
        calls['feedback'].append(dict(code=a[1], attempt=a[3]))
        return ''  # No reference/TB or behavioral oracle enters this control.

    def reject(*a, **k):
        raise AssertionError('Unexpected subprocess.run outside the owned compiler interface')

    activity = types.SimpleNamespace(append=lambda *a, **k: None)
    paired = types.SimpleNamespace(check_resource=gate, model_idle=idle, owned_command=owned)
    failure = None
    try:
        with patch.dict(os.environ, {'MODEL_NAME':MODEL,'RTL_REPAIRS':'1','RTL_MAX_TOKENS':'8192','RTL_TEMPERATURE':'0',
                                     'LLM_BASE_URL':'http://127.0.0.1:8000/v1'}), \
             patch.object(worker,'load',runtime_loader), patch.object(worker,'functional_feedback',feedback), \
             patch.object(urllib.request,'urlopen',transport), patch.object(subprocess,'run',reject), \
             patch.dict(sys.modules,{'activity':activity}):
            worker.run_worker(args, paired)
        assert (Path.cwd(),subprocess.run,urllib.request.urlopen) == previous
        measured = [len(calls['http']),sum(c['tool']=='xvlog' for c in calls['tools']),
                    sum(c['tool']=='xelab' for c in calls['tools']),len(calls['feedback'])]
        assert measured == expected[arm], (name, arm, measured, expected[arm])
        tool_codes = [c['process']['returncode'] for c in calls['tools']]
        expected_codes = {
            'strict_separate':[0,0], 'strict_conflict':[0,1,0,0],
            'ansi_valid':[1,0,0], 'ansi_invalid':[1,0,1,0,0]}[name]
        assert [int(c!=0) for c in tool_codes] == expected_codes, (tool_codes,expected_codes)
        if name in ('strict_conflict', 'ansi_invalid'):
            logs = [args.out/'native_processes'/str(i)/'stdout.bin' for i,c in enumerate(calls['tools']) if c['tool']=='xelab' and c['process']['returncode'] != 0]
            assert len(logs) == 1 and 'VRFC 10-3818' in logs[0].read_text()
        final = (GOOD if name in ('strict_conflict','ansi_invalid') else
                 initial.replace('output q','output reg q') if name.startswith('ansi') else initial)+'\n'
        assert (args.out/'solution.v').read_text() == final
        gate()
    except BaseException as exc:
        failure=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    report=dict(name=name,arm=arm,passed=failure is None,error=failure,expected=expected[arm],calls=calls,
                real_model_calls=0,real_eda_calls=len(calls['tools']),functional_oracle_used=False)
    save(args.out/'NATIVE_CONTROL_RESULT.json',report)
    print(json.dumps(dict(name=name,arm=arm,passed=failure is None,error=failure)))
    return 0 if failure is None else 1


def stage(resource):
    frozen()
    save(ROOT/'STAGE_INTENT.json',dict(manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'),model_calls=0,real_tools_max=14,aggregate_with117_max=23))
    (ROOT/'results').mkdir()
    import bounded_owned_exec
    reports=[];failure=None
    try:
        load('native_stage_resource', ROOT/'paired_checkpoint.py').check_resource(resource, KIT, first=True)
        for name,_,_ in CASES:
            (ROOT/'worker_processes'/name).mkdir(parents=True)
            for arm in ('P',):
                rec=bounded_owned_exec.run([sys.executable,'-B',str(ROOT/'native_controls.py'),'case',
                    '--case',name,'--arm',arm,'--resource-check',str(resource)],
                    ROOT,ROOT/'worker_processes'/name/arm,300)
                report=read(ROOT/'results'/name/arm/'NATIVE_CONTROL_RESULT.json')
                reports.append(report)
                assert rec['normal_completion'] and rec['returncode']==0 and rec['exec_confirmed'] and rec['leader_reaped']
                assert report['passed']
            assert read(ORIGINAL/'results/single/C/requests/0/request.json') == read(ROOT/'results'/name/'P/requests/0/request.json')
        assert sum(r['real_eda_calls'] for r in reports)==14
        assert sum(len(r['calls']['http']) for r in reports)==6
        frozen()
    except BaseException as exc:
        failure=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    summary=dict(complete=True,passed=failure is None and len(reports)==4,error=failure,rows=reports,
                 real_model_calls=0,real_eda_calls=sum(r['real_eda_calls'] for r in reports),
                 native_scope='Four P strict-SV/ANSI controls; prior ordinary C/P evidence reused and117 failure retained.',
                 scoring_qualified=False,accuracy_measured=False)
    save(ROOT/'results/summary.json',summary)
    print(json.dumps(dict(passed=summary['passed'],completed_workers=len(reports),error=failure)))
    return 0 if summary['passed'] else 1


def observe(resource):
    frozen()
    save(ROOT/'OBSERVE_INTENT.json',dict(manifest_sha256=sha(ROOT/'SOURCE_MANIFEST.json'),cap_s=400,prior_elapsed_s=15.47378627769649))
    import terminal_outer
    rec=terminal_outer.run([sys.executable,'-B',str(ROOT/'native_controls.py'),'stage','--resource-check',str(resource)],
        ROOT,ROOT/'external',400,30,[ROOT/'results/summary.json'],2013333)
    print(json.dumps(dict(passed=rec['passed'],elapsed_s=rec['measured_complete_elapsed_s'],error=rec['error'])))
    return 0 if rec['passed'] else 1


if __name__=='__main__':
    assert sys.platform=='linux' and sys.dont_write_bytecode
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','observe','stage','case'])
    parser.add_argument('--resource-check',type=Path)
    parser.add_argument('--case');parser.add_argument('--arm',choices=['C','P'])
    args=parser.parse_args()
    if args.mode=='prepare':prepare()
    else:
        assert args.resource_check
        sys.exit(observe(args.resource_check) if args.mode=='observe' else
                 stage(args.resource_check) if args.mode=='stage' else
                 case_run(args.case,args.arm,args.resource_check))
