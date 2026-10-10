"""Portable selected P chain: frozen model loop, prompt-derived checks, owned tools."""
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import deadline_supervisor
import edge_contract
import edge_dispatch
import edge_feedback
import first_system_request
import generation
import phase_context
import phase_feedback
import point_feedback
import prompt_map
import prompt_probe
import shared_budget
import table_feedback

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def integrity():
    manifest = json.loads((ROOT.parent / 'manifest.json').read_text(encoding='utf-8'))
    binding = manifest['selected_candidate']['files']
    for name, digest in binding.items():
        if sha(ROOT.parent / name) != digest:
            raise RuntimeError('Selected candidate source changed: ' + name)
    upstream = json.loads((ROOT.parent / 'upstream.json').read_text(encoding='utf-8'))
    for name, digest in upstream['files'].items():
        if sha(ROOT.parent / name) != digest:
            raise RuntimeError('Official baseline source changed')


def model_idle(budget, opener, *, allow_busy=False):
    """One total HTTP budget; never a separate fresh timeout for each response."""
    base = generation.endpoint()
    if base != 'http://127.0.0.1:8000/v1':
        raise RuntimeError('Selected source requires the admitted local model endpoint')
    with budget.http_deadline():
        def get(url):
            with opener(url, timeout=budget.remaining(5)) as response:
                return json.load(response)
        health = get(base[:-3] + '/health')
        models = get(base + '/models')
        slots = get(base[:-3] + '/slots')
        if health.get('status') != 'ok' or os.environ['MODEL_NAME'] not in [
                item['id'] for item in models['data']]:
            raise RuntimeError('Admitted local model unavailable')
        if not slots or any(type(slot.get('is_processing')) is not bool for slot in slots):
            raise RuntimeError('Invalid local model slot telemetry')
        processing = sum(slot['is_processing'] for slot in slots)
        if processing and not allow_busy:
            raise RuntimeError('Admitted local model is still processing')
    return dict(health_status='ok', model=os.environ['MODEL_NAME'],
                slot_count=len(slots), processing_slots=processing)


def functional_feedback(prompt, code, out, attempt, probe, task, candidate=False):
    parser = edge_dispatch if candidate else prompt_map
    renderer = phase_feedback if candidate else point_feedback
    contract = parser.parse(prompt)
    if contract['status'] != 'supported' or re.search(r'\$[A-Za-z_]|`include', code):
        return ''
    folder = out / ('map_check_' + str(attempt))
    folder.mkdir()
    inputs = folder/'inputs'/task
    inputs.mkdir(parents=True)
    source, tb = folder/'input.sv', inputs/'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(parser.render_tb(contract, task), encoding='utf-8', newline='\n')
    result = probe(dict(task=task, checks=contract['checks'], tb=str(tb.resolve())),
                           source, folder/'probe')
    save(folder/'contract.json', contract)
    if result['status'] == 'pass':
        if candidate and contract.get('family')=='edge':
            rows,bound=phase_context.context((folder/'probe/xsim.log').read_text(),contract,edge_contract)
            assert bound is None
        assert result['mismatches'] == 0
        return ''
    if result['failure_kind'] != 'semantic_mismatch':
        raise RuntimeError('Functional checker failed; no fabricated model feedback')
    point = parser.counterexample((folder/'probe/xsim.log').read_text(), contract)
    save(folder/'counterexample.json', point)
    feedback = renderer.render(contract, result, point)
    save(folder/'feedback.json', dict(text=feedback))
    return feedback



def run(task, out, work, budget):
    """Called only in the CLI or single HTTP server's main thread."""
    if sys.platform != 'linux' or threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Selected candidate requires an owned Linux main thread')
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('Cannot enable owned-child subreaping')
    if (os.environ.get('RTL_REPAIRS', '1') != '1'
            or os.environ.get('RTL_MAX_TOKENS', '8192') != '8192'
            or float(os.environ.get('RTL_TEMPERATURE', '0')) != 0
            or not os.environ.get('MODEL_NAME')):
        raise ValueError('Selected candidate requires one repair, 8192 tokens and temperature zero')
    integrity()
    task, out, work = Path(task).resolve(), Path(out).resolve(), Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    prompt = (task / 'prompt.txt').read_text(encoding='utf-8')
    interface = (task / 'interface.txt').read_text(encoding='utf-8') if (task / 'interface.txt').is_file() else ''
    context = dict(prompt=prompt, interface=interface, arm='P', out=out, receipts=[])
    requests, compiles = [], []
    save(out / 'requests.json', requests)
    original_open, original_run, original_request = urllib.request.urlopen, subprocess.run, urllib.request.Request
    original_feedback = getattr(generation, 'map_feedback', None)
    previous = Path.cwd()
    owned = budget.owned_operation(deadline_supervisor.owned_command)
    task_label = 'CurrentTask'  # An opaque caller task_id never changes generation/check behavior.

    def gate():
        budget.remaining()
        integrity()

    def transport(request, *positional, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if not url.endswith('/chat/completions'):
            return original_open(request, *positional, **kwargs)
        if url != 'http://127.0.0.1:8000/v1/chat/completions' or request.get_method() != 'POST':
            raise RuntimeError('Unexpected model transport')
        gate()
        index = len(requests)
        if index >= 2:
            raise RuntimeError('No additional or implicit retry model request is allowed')
        body = json.loads(request.data)
        skill, repair = generation.skill_texts()
        expected_system = skill + ('\n' + repair if index else '') + (
            first_system_request.SYSTEM_SUFFIX if index == 0 else '')
        assert body['messages'][0] == dict(role='system', content=expected_system)
        assert body['model'] == os.environ['MODEL_NAME'] and body['temperature'] == 0
        assert body['max_tokens'] == 8192 and body['top_p'] == 1
        folder = out / 'requests' / str(index)
        folder.mkdir(parents=True, exist_ok=False)
        save(folder / 'request.json', body)
        entry = dict(index=index, replayed=False, response_received=False, dispatch_started=False,
                     request_sha256=sha(folder / 'request.json'))
        requests.append(entry)
        save(out / 'requests.json', requests)
        tick = time.monotonic()
        model_idle(budget, original_open)
        try:
            bounded_kwargs = budget.http_timeout(positional, kwargs)
            entry['dispatch_started'] = True
            save(out / 'requests.json', requests)
            with budget.http_deadline():
                with original_open(request, *positional, **bounded_kwargs) as response:
                    raw = response.read()
        except Exception as error:
            entry.update(error=type(error).__name__, elapsed_s=time.monotonic() - tick)
            save(out / 'requests.json', requests)
            generation.trace(out, 'llm_unconfirmed', round=index, error=type(error).__name__,
                             server_received_count=None)
            if budget.expired():
                raise shared_budget.BudgetExpired('Shared budget ended with an unconfirmed request') from error
            raise RuntimeError('Actual model request failed; do not resample') from error
        (folder / 'response.json').write_bytes(raw)
        payload = json.loads(raw)
        choice = payload['choices'][0]
        entry.update(response_received=True, response_sha256=sha(folder / 'response.json'),
                     elapsed_s=time.monotonic() - tick, finish_reason=choice.get('finish_reason'),
                     response_id=payload.get('id'), usage=payload.get('usage'))
        save(out / 'requests.json', requests)
        budget.remaining()
        return io.BytesIO(raw)

    def compiler(argv, *positional, **kwargs):
        if not isinstance(argv, list) or '--sv' not in argv or Path(argv[0]).name not in ('xvlog', 'xvlog.bat'):
            return original_run(argv, *positional, **kwargs)
        gate()
        folder = Path(kwargs['cwd'])
        evidence = out / 'compile_receipts' / str(len(compiles))
        evidence.mkdir(parents=True, exist_ok=False)
        (evidence / 'source_before.sv').write_bytes(Path(argv[-1]).read_bytes())
        log = evidence / 'owned_compile.log'
        result = owned(argv, folder, log, 60)
        (evidence / 'source_after.sv').write_bytes(Path(argv[-1]).read_bytes())
        compiles.append(dict(argv=argv, source_sha256=sha(argv[-1]),
            source_before_sha256=sha(evidence / 'source_before.sv'),
            source_after_sha256=sha(evidence / 'source_after.sv'), **result))
        save(out / 'compile_journal.json', compiles)
        if result['launch_error'] or result['remaining_live_group'] or result['timeout']:
            budget.remaining()
            raise RuntimeError('Native compiler supervision failure')
        return subprocess.CompletedProcess(argv, result['returncode'], log.read_text(errors='replace'))

    def stage(name, argv, outdir):
        gate()
        tool = generation.vivado_tool(argv[0])
        if not tool:
            raise RuntimeError('Required candidate checker tool unavailable')
        command = [tool, *argv[1:]]
        generation.trace(out, 'probe_stage_start', stage=name)
        result = dict(name=name, argv=command,
                      **owned(command, outdir, outdir / (name + '.log'), 60))
        generation.trace(out, 'probe_stage', stage=name, rc=result['returncode'],
                         timeout=result['timeout'], log_sha256=result['log_sha256'],
                         elapsed_s=result['elapsed_s'])
        return result

    def probe(config, solution, target):
        return prompt_probe.probe_candidate(config['task'], solution, Path(config['tb']),
                                             target, config['checks'], stage)

    checks = work / 'checks'
    checks.mkdir()
    def feedback(prompt, code, target, attempt):
        gate()
        table_result = table_feedback.check(prompt, code, checks, attempt, probe, task_label)
        if table_result is not None:
            return table_result
        return functional_feedback(prompt, code, checks, attempt, probe, task_label, candidate=True)

    try:
        urllib.request.Request = first_system_request.request_class(original_request, context)
        urllib.request.urlopen, subprocess.run = transport, compiler
        generation.map_feedback = feedback
        os.chdir(work)
        generation.worker(task, out)
        assert 1 <= len(requests) == len(context['receipts']) <= 2
        assert all(row['response_received'] for row in requests)
        budget.remaining()
        for index, receipt in enumerate(context['receipts']):
            folder = out / 'first_system_request_receipts' / str(index)
            original = (folder / 'original_wire.bin').read_bytes()
            forwarded = (folder / 'forwarded_wire.bin').read_bytes()
            expected, expected_receipt = first_system_request.transform(original, prompt, interface, 'P', index)
            assert forwarded == expected and receipt == expected_receipt
            assert json.loads(forwarded) == json.loads((out / 'requests' / str(index) / 'request.json').read_bytes())
        save(out / 'worker_result.json', dict(complete=True, arm='P',
             requests=len(requests), actual_model_requests=len(requests),
             elapsed_s=time.monotonic() - budget.started, solution_sha256=sha(out / 'solution.v')))
    except shared_budget.BudgetExpired:
        save(out / 'SHARED_BUDGET_EXIT.json', budget.exit_receipt(out / 'requests.json', __file__))
        raise
    finally:
        urllib.request.urlopen, subprocess.run, urllib.request.Request = original_open, original_run, original_request
        if original_feedback is None:
            generation.__dict__.pop('map_feedback', None)
        else:
            generation.map_feedback = original_feedback
        os.chdir(previous)
        # Retain compact prompt-derived evidence; native caches stay in local scratch.
        for folder in checks.iterdir():
            if not folder.is_dir():
                continue
            for item in [*folder.glob('*.json'), *folder.glob('*.txt'), *folder.glob('*.sv'),
                         *folder.glob('inputs/*/*.sv'), *folder.glob('probe/*.json'), *folder.glob('probe/*.log')]:
                target = out / 'diagnostics' / item.relative_to(checks)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, target)

