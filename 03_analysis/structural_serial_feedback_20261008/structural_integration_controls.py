"""AMD-only simulated wiring controls using retained 131 native evidence.

No native/solver/model reruns. Every edited metadata/request copy is explicitly
simulated, never evidence of a model responding to the new structural feedback.
"""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import traceback
from types import SimpleNamespace
import urllib.request
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def forbidden(*args, **kwargs):
    raise AssertionError('Structural wiring qualification forbids model, process and EDA execution')


def run(args):
    root, origin, out = args.source_root.resolve(), args.original_run.resolve(), args.out.resolve()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert not out.exists() and not out.is_relative_to(origin) and not origin.is_relative_to(out)
    assert sha(args.original_result) == args.original_result_sha256
    terminal = read(args.original_result)
    assert terminal['complete'] and terminal['source_root'] == str(origin)
    assert terminal['samples_per_task'] == 5 and terminal['generation_rows'] == 30
    frozen = read(root / 'RUN_SPEC.json')
    sources = {name: sha(root / name) for name in frozen['source_hashes']}
    assert sources == frozen['source_hashes']
    original_spec = read(origin / 'RUN_SPEC.json')
    assert sources['serial_feedback.py'] == original_spec['source_hashes']['serial_feedback.py']
    assert sources['serial_binding.py'] == original_spec['source_hashes']['serial_binding.py']
    out.mkdir(parents=True)
    originals = {str(args.original_result): args.original_result_sha256,
                 str(origin / 'RUN_SPEC.json'): sha(origin / 'RUN_SPEC.json')}
    rewrites, reports = [], []
    sys.path.insert(0, str(root))

    def copy_file(source, target):
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        originals[str(source)] = hashlib.sha256(data).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)

    def clone(name, row, arm, hooks):
        source, case = origin / 'queue' / row / 'solve', out / name
        case.mkdir()
        for name in ('requests.json', 'trace.jsonl', 'worker_result.json', 'solution.v',
                     'prompt_only/prompt.txt'):
            copy_file(source / name, case / name)
        if (source / 'prompt_only/interface.txt').is_file():
            copy_file(source / 'prompt_only/interface.txt', case / 'prompt_only/interface.txt')
        for attempt in (0, 1):
            for name in ('request.json', 'response.json'):
                rel = Path('requests') / str(attempt) / name
                copy_file(source / rel, case / rel)
            old = source / ('serial_check_' + str(attempt))
            new = case / old.name
            for name in ('input.sv', 'contract.json', 'counterexample.json', 'feedback.txt',
                         'probe/dut.sv', 'probe/tb.sv', 'probe/result.json',
                         'probe/adapter_receipt.json', 'probe/xvlog.log',
                         'probe/xelab.log', 'probe/xsim.log'):
                copy_file(old / name, new / name)
            tbs = list((old / 'inputs').glob('*/tb.sv'))
            assert len(tbs) == 1
            copy_file(tbs[0], new / tbs[0].relative_to(old))
            result = read(new / 'probe/result.json')
            original_result = copy.deepcopy(result)
            result['outdir'] = str(new / 'probe')
            for stage in result['stages']:
                stage['log'] = str(new / 'probe' / (stage['name'] + '.log'))
            save(new / 'probe/result.json', result)
            adapter = read(new / 'probe/adapter_receipt.json')
            original_adapter = copy.deepcopy(adapter)
            adapter.update(result)
            adapter['inherited_result_path'] = str(new / 'probe/result.json')
            adapter['inherited_result_sha256'] = sha(new / 'probe/result.json')
            for filename, key in [('probe_runner.py', 'inherited_runner'),
                                  ('paired_checkpoint.py', 'oracle_adapter')]:
                dependency = Path(frozen['dependencies_cloud']) / filename
                assert adapter[key + '_sha256'] == sha(dependency) == frozen['dependency_hashes'][filename]
                adapter[key + '_path'] = str(dependency)
            save(new / 'probe/adapter_receipt.json', adapter)
            rewrites.append(dict(simulated=True, copy=str(new), original=str(old),
                                 result_before=original_result, result_after=result,
                                 adapter_before=original_adapter, adapter_after=adapter))
        status = read(case / 'worker_result.json')
        status['arm'] = 'C' if arm == 'A' else 'P'
        save(case / 'worker_result.json', status)
        if arm == 'P':
            events = [json.loads(line) for line in (case / 'trace.jsonl').read_text().splitlines()]
            for attempt in (0, 1):
                folder = case / ('serial_check_' + str(attempt))
                raw = (folder / 'feedback.txt').read_text(encoding='utf-8')
                code = (folder / 'input.sv').read_text(encoding='utf-8')
                combined = hooks.append_feedback(code, case, attempt, raw, root)
                found = [e for e in events if e.get('tool') == 'map_feedback' and e.get('round') == attempt]
                assert len(found) == 1 and found[0]['excerpt'] == raw
                found[0]['excerpt'] = combined
                if attempt == 0:
                    path = case / 'requests/1/request.json'
                    request = read(path)
                    user = request['messages'][1]['content']
                    assert user.endswith('\nCandidate diagnostics:\n' + raw)
                    request['messages'][1]['content'] = user[:-len(raw)] + combined
                    save(path, request)
                    receipts = read(case / 'requests.json')
                    receipts[1]['request_sha256'] = sha(path)
                    save(case / 'requests.json', receipts)
            (case / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        save(case / 'SIMULATED_CONTROL.json', dict(simulated=True, source=str(source),
             arm_projection=arm, native_evidence_relocated=True, original_model_replies_reused=True,
             not_real_responses_to_new_feedback=True, new_model_calls=0, new_eda_calls=0))
        return case

    error = None
    save(out / 'INTENT.json', dict(simulated=True, original_run=str(origin),
         original_result_sha256=args.original_result_sha256, source_hashes=sources,
         new_model_max=0, new_eda_max=0, old_native_reruns=0))
    try:
        with patch.object(urllib.request, 'urlopen', forbidden), \
             patch.object(subprocess, 'run', forbidden), patch.object(subprocess, 'Popen', forbidden):
            worker = importlib.import_module('worker')
            hooks = importlib.import_module('structural_serial_feedback')
            serial = importlib.import_module('serial_binding')
            structural = importlib.import_module('structural_serial_binding')
            # Retained 131 sample 0 provides actual native failures for both tasks.
            a = clone('A_original_serial', 'row_000001', 'A', hooks)
            worker.bind(a, 'A')
            bound = serial.bind_serial(a, root)
            assert len(bound['actual_checks']) == 2 and bound['counterexamples_consumed'] == 1
            assert not list(a.glob('structural_check_*'))
            reports.append(dict(control='A_uses_original_serial', passed=True, simulated=True))
            for name, row, should_fire in [('P_conflict', 'row_000001', True),
                                           ('P_no_conflict', 'row_000015', False)]:
                case = clone(name, row, 'P', hooks)
                worker.bind(case, 'P')
                bound = structural.bind_serial_structural(case, root)
                assert len(bound['actual_checks']) == 2 and bound['counterexamples_consumed'] == 1
                records = [read(case / ('structural_check_' + str(i)) / 'RESULT.json') for i in (0, 1)]
                assert bool(records[0]['structural_feedback']) == should_fire
                assert bound['actual_checks'][1]['structural_feedback_consumed'] is False
                if not should_fire:
                    for i in (0, 1):
                        assert (case / ('structural_check_' + str(i)) / 'combined_feedback.txt').read_bytes() == (case / ('serial_check_' + str(i)) / 'feedback.txt').read_bytes()
                reports.append(dict(control=name, passed=True, simulated=True))
            # Three hook controls check C bypass removal, P augmentation and empty-pass preservation.
            seed = origin / 'queue/row_000001/solve/serial_check_0'
            code, raw = (seed / 'input.sv').read_text(), (seed / 'feedback.txt').read_text()
            originals[str(seed / 'input.sv')] = sha(seed / 'input.sv')
            originals[str(seed / 'feedback.txt')] = sha(seed / 'feedback.txt')
            for name, arm, measured in [('flow_A_serial', 'C', raw), ('flow_P_append', 'P', raw),
                                        ('flow_P_empty', 'P', '')]:
                case = out / name
                case.mkdir()
                folder = case / 'serial_check_0'
                folder.mkdir()
                (folder / 'input.sv').write_text(code, encoding='utf-8', newline='\n')
                (folder / 'feedback.txt').write_text(raw, encoding='utf-8', newline='\n')
                fallback = lambda *a, **k: 'UNEXPECTED_FALLBACK'
                base = SimpleNamespace(ROOT=root, functional_feedback=fallback)
                opts = SimpleNamespace(arm=arm)
                base.run_worker = lambda args, paired: base.functional_feedback('prompt', code, case, 0, paired, 'Synthetic', candidate=True)
                with patch.object(hooks.serial_feedback, 'check', return_value=measured) as check:
                    text = hooks.run_worker(base, opts, object())
                    assert check.call_count == 1
                assert base.functional_feedback is fallback and opts.arm == arm
                if name == 'flow_P_append':
                    assert text.startswith(raw + hooks.DELIMITER)
                else:
                    assert text == measured and not list(case.glob('structural_check_*'))
                reports.append(dict(control=name, passed=True, simulated=True))
            for mutation in ('missing_record', 'source_hash', 'diagnostic_fact', 'combined_file', 'next_request'):
                case = clone('reject_' + mutation, 'row_000001', 'P', hooks)
                record = case / 'structural_check_0/RESULT.json'
                if mutation == 'missing_record':
                    record.rename(record.with_name('MISSING_RESULT.simulated'))
                elif mutation in ('source_hash', 'diagnostic_fact'):
                    value = read(record)
                    if mutation == 'source_hash':
                        value['source_sha256'] = '0' * 64
                    else:
                        assert value['analysis']['diagnostics']
                        value['analysis']['diagnostics'][0]['variable'] += '_tampered'
                    save(record, value)
                elif mutation == 'combined_file':
                    path = case / 'structural_check_0/combined_feedback.txt'
                    path.write_text(path.read_text() + '\nSIMULATED_EXTRA', encoding='utf-8')
                else:
                    path = case / 'requests/1/request.json'
                    value = read(path)
                    value['messages'][1]['content'] += '\nSIMULATED_EXTRA'
                    save(path, value)
                    receipts = read(case / 'requests.json')
                    receipts[1]['request_sha256'] = sha(path)
                    save(case / 'requests.json', receipts)
                    events = [json.loads(line) for line in (case / 'trace.jsonl').read_text().splitlines()]
                    for event in events:
                        if event.get('tool') == 'map_feedback' and event.get('round') == 0:
                            event['excerpt'] += '\nSIMULATED_EXTRA'
                    (case / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
                worker.bind(case, 'P')  # Rejection below must exercise the new strict layer.
                try:
                    structural.bind_serial_structural(case, root)
                except (AssertionError, RuntimeError, FileNotFoundError) as exc:
                    reports.append(dict(control='reject_' + mutation, passed=True, simulated=True,
                                        rejected_by='structural_serial_binding', error_type=type(exc).__name__))
                else:
                    raise AssertionError('Structural evidence tamper accepted: ' + mutation)
            assert len(reports) == 11
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    sources_unchanged = all(sha(root / n) == h for n, h in sources.items())
    originals_unchanged = all(sha(p) == h for p, h in originals.items())
    if not (sources_unchanged and originals_unchanged) and error is None:
        error = dict(type='EvidenceDrift', message='Source or original evidence changed')
    save(out / 'SIMULATED_PATH_REWRITES.json', rewrites)
    save(out / 'RESULT.json', dict(complete=True, passed=error is None, reports=reports,
         simulated_controls=True, new_model_calls=0, new_eda_calls=0, old_native_reruns=0,
         error=error, sources_unchanged=sources_unchanged, originals_unchanged=originals_unchanged,
         source_sha256=sources, original_evidence_sha256=originals))
    return 0 if error is None else 1


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    for name in ('source-root', 'original-run', 'original-result', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--original-result-sha256', required=True)
    sys.exit(run(parser.parse_args()))
