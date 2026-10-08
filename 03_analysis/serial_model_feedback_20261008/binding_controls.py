"""AMD-only binding controls from retained native evidence; no solver/EDA reruns.

Every constructed case is SIMULATED. Original controls and logs stay immutable.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import traceback
import urllib.request
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args):
    root, origin, out = args.source_root.resolve(), args.controls_root.resolve(), args.out.resolve()
    assert not out.exists() and not out.is_relative_to(origin) and not origin.is_relative_to(out)
    assert sha(origin / 'CONTROL_RESULT.json') == args.controls_result_sha256
    control = read(origin / 'CONTROL_RESULT.json')
    assert control['complete'] and control['passed'] and control['real_model_calls'] == 0
    assert control['reports']['native']['positive']['passed']
    assert control['reports']['native']['late_stop_mutant']['passed']
    control_intent = read(origin / 'CONTROL_INTENT.json')
    for name in ('serial_feedback.py', 'reserved_keywords.py'):
        assert control_intent['source_hashes'][name] == sha(root / name)
    seed = origin / 'flow/candidate_repairs_once'
    flow_control = read(seed / 'CONTROL_RESULT.json')
    assert flow_control['passed'] and flow_control['simulated']
    assert flow_control['real_model_calls'] == flow_control['real_eda_calls'] == 0
    frozen = read(root / 'RUN_SPEC.json')
    for name in ('worker.py', 'serial_binding.py', 'serial_feedback.py', 'binding_controls.py'):
        assert frozen['source_hashes'][name] == sha(root / name)
    source_hashes = {name: sha(root / name) for name in frozen['source_hashes']}
    assert source_hashes == frozen['source_hashes']
    out.mkdir(parents=True)
    originals = {str(origin / 'CONTROL_RESULT.json'): args.controls_result_sha256,
                 str(origin / 'CONTROL_INTENT.json'): sha(origin / 'CONTROL_INTENT.json'),
                 str(seed / 'CONTROL_RESULT.json'): sha(seed / 'CONTROL_RESULT.json')}
    rewrites, reports = [], []

    def copy_file(source, dest):
        source, dest = Path(source), Path(dest)
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        originals[str(source)] = hashlib.sha256(data).hexdigest()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(data)

    def native(case, attempt, fixture):
        source = origin / 'native' / fixture / 'serial_check_0'
        target = case / ('serial_check_' + str(attempt))
        names = ['input.sv', 'contract.json', 'inputs/SyntheticSerial/tb.sv', 'probe/dut.sv',
                 'probe/tb.sv', 'probe/result.json', 'probe/adapter_receipt.json',
                 'probe/xvlog.log', 'probe/xelab.log', 'probe/xsim.log']
        if fixture != 'positive':
            names += ['counterexample.json', 'feedback.txt']
        for name in names:
            copy_file(source / name, target / name)
        before = read(target / 'probe/result.json')
        result = copy.deepcopy(before)
        result['outdir'] = str(target / 'probe')
        projections = []
        for stage in result['stages']:
            if 'log_bytes' not in stage:
                # 130's bounded compatibility adapter omits this legacy field.
                # Derive it only in the explicit simulated control copy, from
                # that exact original command's independently bound stdout.
                matches = [row for row in control['native_commands']
                           if row.get('legacy_adapter_result', {}).get('log') == stage['log']]
                assert len(matches) == 1
                command = matches[0]
                record_path = origin / ('NATIVE_COMMAND_' + str(command['index']) + '.json')
                assert read(record_path) == command
                assert command['argv'] == stage['argv']
                assert command['legacy_adapter_result'] == {
                    k: v for k, v in stage.items() if k not in ('name', 'argv')}
                receipt_path = Path(command['bounded_receipt_path'])
                assert receipt_path.is_relative_to(origin)
                assert sha(receipt_path) == command['bounded_receipt_sha256']
                bounded = read(receipt_path)
                assert bounded == command['bounded_receipt']
                stdout = receipt_path.parent / 'stdout.bin'
                original_log = source / 'probe' / (stage['name'] + '.log')
                assert stage['log'] == str(original_log)
                assert bounded['stdout_sha256'] == stage['log_sha256'] == sha(original_log) == sha(stdout)
                assert type(bounded['stdout_bytes']) is int
                assert bounded['stdout_bytes'] == original_log.stat().st_size == stdout.stat().st_size
                for p in (record_path, receipt_path, stdout):
                    originals[str(p)] = sha(p)
                stage['log_bytes'] = bounded['stdout_bytes']
                projections.append(dict(simulated_control_copy_only=True, field='log_bytes',
                    derived_value=stage['log_bytes'], native_command_index=command['index'],
                    original_command_record=str(record_path), original_command_sha256=sha(record_path),
                    original_bounded_receipt=str(receipt_path), bounded_receipt_sha256=sha(receipt_path),
                    original_stdout=str(stdout), stdout_sha256=bounded['stdout_sha256'],
                    original_log=str(original_log), original_log_sha256=sha(original_log)))
            stage['log'] = str(target / 'probe' / (stage['name'] + '.log'))
        save(target / 'probe/result.json', result)
        old_adapter = read(target / 'probe/adapter_receipt.json')
        adapter = dict(old_adapter, **result)
        adapter['inherited_result_path'] = str(target / 'probe/result.json')
        adapter['inherited_result_sha256'] = sha(target / 'probe/result.json')
        for name, key in [('probe_runner.py', 'inherited_runner'),
                          ('paired_checkpoint.py', 'oracle_adapter')]:
            dep = Path(frozen['dependencies_cloud']) / name
            assert old_adapter[key + '_sha256'] == sha(dep) == frozen['dependency_hashes'][name]
            adapter[key + '_path'] = str(dep)
        save(target / 'probe/adapter_receipt.json', adapter)
        rewrites.append(dict(simulated=True, original=str(source), copy=str(target),
                             control_schema_field_projections=projections,
                             result_original=before, result_simulated=result,
                             adapter_original=old_adapter, adapter_simulated=adapter))

    def make_case(name, good_only=False):
        case = out / name
        case.mkdir()
        for name in ('requests.json', 'trace.jsonl', 'solution.v', 'worker_result.json'):
            copy_file(seed / name, case / name)
        for p in (seed / 'prompt_only').iterdir():
            copy_file(p, case / 'prompt_only' / p.name)
        if good_only:
            copy_file(seed / 'requests/0/request.json', case / 'requests/0/request.json')
            copy_file(seed / 'requests/1/response.json', case / 'requests/0/response.json')
            request = copy.deepcopy(read(seed / 'requests.json')[1])
            request.update(index=0, request_sha256=sha(case / 'requests/0/request.json'),
                           response_sha256=sha(case / 'requests/0/response.json'))
            save(case / 'requests.json', [request])
            events = [json.loads(line) for line in (seed / 'trace.jsonl').read_text().splitlines()]
            selected = [dict(e, round=0) if e.get('round') == 1 else e
                        for e in events if e.get('tool') == 'agent_meta' or e.get('round') == 1]
            (case / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in selected))
            result = read(case / 'worker_result.json')
            result.update(requests=1, actual_model_requests=1, elapsed_s=None)
            save(case / 'worker_result.json', result)
            native(case, 0, 'positive')
        else:
            for index in (0, 1):
                for name in ('request.json', 'response.json'):
                    copy_file(seed / 'requests' / str(index) / name, case / 'requests' / str(index) / name)
            native(case, 0, 'late_stop_mutant')
            native(case, 1, 'positive')
            # Preserve the old mock flow's exact repair request; never fabricate
            # an allegedly measured feedback string to make the control pass.
            text = (case / 'serial_check_0/feedback.txt').read_text()
            events = [json.loads(line) for line in (case / 'trace.jsonl').read_text().splitlines()]
            assert [e['excerpt'] for e in events if e.get('tool') == 'map_feedback'] == [text]
        save(case / 'SIMULATED_CONTROL.json', dict(simulated=True, not_an_actual_solver_run=True,
             old_flow=str(seed), good_only_projection=good_only, new_model_calls=0, new_eda_calls=0))
        return case

    def forbidden(*a, **k):
        raise AssertionError('Binding controls cannot call a model, solver or EDA process')

    save(out / 'INTENT.json', dict(simulated=True, original_controls=str(origin),
         controls_result_sha256=args.controls_result_sha256, new_model_max=0, new_eda_max=0,
         old_flow_reruns=0, source_hashes=source_hashes))
    error = None
    try:
        sys.path.insert(0, str(root))
        with patch.object(urllib.request, 'urlopen', forbidden), \
             patch.object(subprocess, 'run', forbidden), patch.object(subprocess, 'Popen', forbidden):
            worker = load('serial_control_model_binding', root / 'worker.py')
            binding = load('serial_control_evidence_binding', root / 'serial_binding.py')
            for name, good in [('correct', True), ('bad_then_good', False)]:
                case = make_case(name, good)
                model = worker.bind(case, 'P')
                result = binding.bind_serial(case, root)
                assert model['actual_model_responses'] == (1 if good else 2)
                assert result['counterexamples_consumed'] == (0 if good else 1)
                assert [r['status'] for r in result['actual_checks']] == (['pass'] if good else ['fail', 'pass'])
                reports.append(dict(control=name, passed=True, simulated=True, result=result))
            for mutation in ('dut', 'log', 'counterexample', 'next_request'):
                case = make_case('reject_' + mutation)
                if mutation == 'dut':
                    p = case / 'serial_check_0/input.sv'
                    p.write_bytes(p.read_bytes() + b'\n// simulated tamper\n')
                elif mutation == 'log':
                    p = case / 'serial_check_0/probe/xsim.log'
                    p.write_bytes(p.read_bytes() + b'\nSIMULATED_TAMPER_WITHOUT_CHANGING_SERIAL_STEPS\n')
                elif mutation == 'counterexample':
                    p = case / 'serial_check_0/counterexample.json'
                    value = read(p); value['observed_done'] = '0'; save(p, value)
                else:
                    p = case / 'requests/1/request.json'
                    value = read(p)
                    value['messages'][1]['content'] += '\nSIMULATED_UNSUPPORTED_DIAGNOSTIC'
                    save(p, value)
                    receipts = read(case / 'requests.json')
                    receipts[1]['request_sha256'] = sha(p); save(case / 'requests.json', receipts)
                    p = case / 'trace.jsonl'
                    events = [json.loads(line) for line in p.read_text().splitlines()]
                    for event in events:
                        if event.get('tool') == 'map_feedback' and event.get('round') == 0:
                            event['excerpt'] += '\nSIMULATED_UNSUPPORTED_DIAGNOSTIC'
                    p.write_text(''.join(json.dumps(event) + '\n' for event in events))
                # The inherited proof must still pass: rejection must exercise
                # the new actual-diagnostic binding, not an old request hash check.
                worker.bind(case, 'P')
                try:
                    binding.bind_serial(case, root)
                except (AssertionError, RuntimeError) as exc:
                    reports.append(dict(control=mutation, passed=True, simulated=True,
                                        rejected_by='serial_binding', error_type=type(exc).__name__))
                else:
                    raise AssertionError('Tampered evidence accepted: ' + mutation)
        assert len(reports) == 6
        assert {name: sha(root / name) for name in source_hashes} == source_hashes
        assert all(sha(path) == expected for path, expected in originals.items())
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    source_unchanged = all(sha(root / name) == expected for name, expected in source_hashes.items())
    originals_unchanged = all(sha(path) == expected for path, expected in originals.items())
    if not (source_unchanged and originals_unchanged) and error is None:
        error = dict(type='EvidenceDrift', message='Original or source bytes changed')
    save(out / 'SIMULATED_PATH_REWRITES.json', rewrites)
    save(out / 'RESULT.json', dict(complete=True, passed=error is None, simulated_controls=True,
         new_model_calls=0, new_eda_calls=0, old_flow_reruns=0, native_reruns=0,
         reports=reports, error=error, source_sha256=source_hashes, original_evidence_sha256=originals,
         sources_unchanged=source_unchanged, originals_unchanged=originals_unchanged))
    return 0 if error is None else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    for name in ('source-root', 'controls-root', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--controls-result-sha256', required=True)
    sys.exit(run(parser.parse_args()))
