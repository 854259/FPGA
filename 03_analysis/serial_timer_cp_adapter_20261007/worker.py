"""Draft bounded table route; original phase-P model fallback stays unchanged."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import baseline_worker as baseline
import synthesis
import factor_proof

ROOT = Path(__file__).resolve().parent
ROUTE_SCHEMA = 'serial_timer_synthesis_generation_route_v1'


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def raw_inputs(source):
    return {name: (source / name).read_bytes()
            for name in ('prompt.txt', 'interface.txt') if (source / name).exists()}


def trace(out, tool, **fields):
    with (out / 'trace.jsonl').open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(dict(ts=time.time(), tool=tool, **fields),
                                ensure_ascii=False) + '\n')


def run_worker(args, paired):
    assert args.arm in ('C', 'P')
    started = time.monotonic()
    spec = json.loads((ROOT / 'RUN_SPEC.json').read_text(encoding='utf-8'))
    source = args.kit / 'bench/tasks_veval' / args.task
    original = raw_inputs(source)
    assert 'prompt.txt' in original
    prompt = original['prompt.txt'].decode('utf-8')
    interface = original.get('interface.txt', b'').decode('utf-8')
    result = synthesis.synthesize(prompt, interface) if args.arm == 'P' else None
    if result is not None:
        assert type(result) is dict and type(result['emitted']) is bool
        assert result['prompt_sha256'] == text_sha(prompt)
        assert result['interface_sha256'] == text_sha(interface)
        assert result['actual_model_requests'] == result['actual_eda_calls'] == result['external_io_calls'] == 0
    emitted = result is not None and result['emitted']
    out = args.out.resolve()
    route = dict(schema=ROUTE_SCHEMA, route='mechanical_serial_timer' if emitted else 'model',
                 outer_arm=args.arm, prompt_sha256=text_sha(prompt),
                 interface_sha256=text_sha(interface),
                 interface_present='interface.txt' in original,
                 baseline_worker_sha256=baseline.sha(ROOT / 'baseline_worker.py'),
                 synthesis_source_sha256=baseline.sha(ROOT / 'synthesis.py'),
                 generated_solution_sha256=result['rtl_sha256'] if emitted else None)
    if not emitted:
        # Do not create out before the original worker's exist_ok=False ownership.
        baseline.run_worker(args, paired)
        assert raw_inputs(source) == original, 'Original prompt/interface changed'
        journal = json.loads((out / 'requests.json').read_text(encoding='utf-8'))
        assert 1 <= len(journal) <= 2
        worker_result = json.loads((out / 'worker_result.json').read_text(encoding='utf-8'))
        assert worker_result['actual_model_requests'] == len(journal)
        worker_result['generation_route'] = 'model'
        baseline.save(out / 'worker_result.json', worker_result)
        baseline.save(out / 'generation_route.json', route)
        if result is not None:
            assert result['rtl'] == '' and isinstance(result['reason'], str)
            baseline.save(out / 'synthesis_receipt.json', result)
        return

    assert args.arm == 'P'
    rtl = result['rtl']
    assert isinstance(rtl, str) and rtl and text_sha(rtl) == result['rtl_sha256']
    contract = result['contract']
    assert contract['all_prompt_consumed'] is True
    canonical = json.dumps(contract, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    assert text_sha(canonical) == result['contract_sha256']
    paired.REPO = ROOT
    paired.INHERITED_ORACLE = Path(spec['dependencies_cloud']) / 'probe_runner.py'
    out.mkdir(parents=True, exist_ok=False)
    work, prompt_only = out / 'work', out / 'prompt_only'
    work.mkdir()
    prompt_only.mkdir()
    for name, content in original.items():
        (prompt_only / name).write_bytes(content)
    (out / 'solution.v').write_bytes(rtl.encode('utf-8'))
    (out / 'trace.jsonl').write_text('', encoding='utf-8')
    baseline.save(out / 'requests.json', [])
    baseline.save(out / 'generation_route.json', route)
    baseline.save(out / 'synthesis_receipt.json', result)
    emission = out / 'emission'
    emission.mkdir()
    baseline.save(emission / 'contract.json', contract)
    (emission / 'emitted.sv').write_bytes(rtl.encode('utf-8'))
    trace(out, 'serial_timer_generation', route='mechanical_serial_timer', round=0,
          actual_model_requests=0, emitted_sha256=result['rtl_sha256'],
          contract_sha256=result['contract_sha256'])

    def gate():
        paired.check_resource(args.resource_check, args.kit)
        assert raw_inputs(source) == original, 'Original prompt/interface changed'
        assert raw_inputs(prompt_only) == original, 'Copied prompt/interface changed'
        assert {path.name for path in prompt_only.iterdir()} == set(original)
        assert (out / 'solution.v').read_bytes() == rtl.encode('utf-8')

    gate()
    runtime = baseline.load('table_original_runtime', ROOT / 'package/agent/map_runtime.py')
    runner = baseline.load('table_original_native_summary', paired.INHERITED_ORACLE)
    tool = runtime.vivado_tool('xvlog')
    if not tool:
        raise RuntimeError('Original pinned xvlog unavailable')
    compile_dir = work / 'mechanical_compile-0'
    compile_dir.mkdir()
    candidate = compile_dir / 'candidate.sv'
    candidate.write_bytes(rtl.encode('utf-8'))
    evidence = out / 'native_receipts' / '0'
    evidence.mkdir(parents=True)
    (evidence / 'source_before.sv').write_bytes(candidate.read_bytes())
    log = evidence / 'owned_compile.log'
    argv = [tool, '--sv', str(candidate)]
    trace(out, 'lint_start', round=0, generation_route='mechanical_serial_timer')
    physical = paired.owned_command(argv, compile_dir, log, 60)
    (evidence / 'source_after.sv').write_bytes(candidate.read_bytes())
    command = dict(physical, argv=argv,
                   source_sha256=baseline.sha(candidate),
                   source_before_sha256=baseline.sha(evidence / 'source_before.sv'),
                   source_after_sha256=baseline.sha(evidence / 'source_after.sv'))
    baseline.save(evidence / 'command.json', command)
    assert baseline.sha(log) == physical['log_sha256']
    assert log.stat().st_size == physical['log_bytes']
    assert command['source_sha256'] == command['source_before_sha256'] == command['source_after_sha256'] == result['rtl_sha256']
    if physical['timeout'] or physical['launch_error'] or physical['remaining_live_group']:
        raise RuntimeError('Emitted native compiler supervision failure')
    if type(physical['returncode']) is not int or physical['returncode'] < 0:
        raise RuntimeError('Emitted native compiler abnormal return')
    stdout = log.read_text(encoding='utf-8', errors='replace')
    if runner.ENVIRONMENT_ERROR.search(stdout):
        raise RuntimeError('Emitted native compiler environment failure')
    excerpt = '\n'.join(line for line in stdout.splitlines()
                        if re.search('ERROR|WARNING|FATAL', line))[:2048] or stdout[-2048:]
    trace(out, 'lint', round=0, rc=physical['returncode'], excerpt=excerpt,
          generation_route='mechanical_serial_timer',
          receipt_sha256=baseline.sha(evidence / 'command.json'))
    gate()
    feedback = ''
    if physical['returncode'] == 0:
        # Exactly the already admitted phase-P check, without another model call.
        common_prompt = (prompt_only / 'prompt.txt').read_text(encoding='utf-8')
        if 'interface.txt' in original and interface.strip():
            common_prompt += '\n\nInterface:\n' + (prompt_only / 'interface.txt').read_text(encoding='utf-8')
        feedback = baseline.functional_feedback(common_prompt, rtl, out, 0,
                                                paired, args.task, candidate=True)
        assert isinstance(feedback, str)
    baseline.save(out / 'native_feedback.json',
                  dict(text=feedback, repair_requested=False,
                       native_compile_returncode=physical['returncode']))
    trace(out, 'native_feedback', round=0, text=feedback, excerpt=feedback,
          repair_requested=False,
          generation_route='mechanical_serial_timer')
    gate()
    baseline.save(out / 'worker_result.json',
                  dict(complete=True, arm=args.arm, requests=0,
                       actual_model_requests=0, received_model_responses=0,
                       generation_route='mechanical_serial_timer',
                       elapsed_s=time.monotonic() - started,
                       solution_sha256=baseline.sha(out / 'solution.v')))


def frozen():
    spec = json.loads((ROOT / 'RUN_SPEC.json').read_text(encoding='utf-8'))
    for name, digest in spec['source_hashes'].items():
        assert baseline.sha(ROOT / name) == digest, name
    for name, digest in spec['dependency_hashes'].items():
        assert baseline.sha(Path(spec['dependencies_cloud']) / name) == digest, name
    factor_proof.verify(ROOT, require_native=True)
    return spec


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('out', 'kit', 'resource-check'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--arm', choices=['C', 'P'], required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    spec = frozen()
    paired = baseline.load('table_owned', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    run_worker(args, paired)
