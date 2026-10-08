"""Only the new complete-parent/CP8 receipt and dependency boundary.

Uses retained original inputs/recipes, without worker, HTTP, EDA, scoring or
old test-suite execution. Native receipts below are explicitly fake rejects.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

import composition
import worker
import reserved_keywords
import generation_binding as proof

ROOT = Path(__file__).resolve().parent
PROVIDERS = [('table', composition.table_synthesis), ('onehot', composition.onehot_producer),
             ('timer', composition.timer_producer), ('serial_framing', composition.serial_framing_producer)]
save = lambda p, j: Path(p).write_bytes((json.dumps(j, indent=2) + '\n').encode())


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_objects():
    return dict(composition=composition, selector=composition.selector,
                table_contract=composition.table_synthesis.contract, worker=worker,
                reserved_keywords=reserved_keywords, baseline_worker=worker.baseline,
                replay=load('cp8_control_original_replay', ROOT / 'original_model_replay.py'),
                baseline=load('cp8_control_original_extract', ROOT / 'package/baseline.py'),
                runtime=load('cp8_control_original_runtime', ROOT / 'package/agent/map_runtime.py'),
                parser=worker.baseline.edge_dispatch, feedback=worker.baseline.phase_feedback,
                runner=load('cp8_control_original_runner', ROOT / 'dependencies/probe_runner.py'),
                providers=PROVIDERS)


def main():
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    manifest = proof.read(ROOT / 'SOURCE_MANIFEST.json')
    assert all(proof.sha(ROOT / n) == h for n, h in manifest.items())
    positives, negatives = [], []

    def rejects(label, call):
        try:
            call()
        except (AssertionError, KeyError, ValueError, FileNotFoundError):
            negatives.append(label)
        else:
            raise AssertionError('Malformed new CP8 context accepted: ' + label)

    def bind(folder, arm, prompt, interface, present):
        return proof.bound_route(folder, ROOT, arm, prompt, interface, present, composition, PROVIDERS)

    def metadata(label, arm, prompt, interface, present):
        folder = ROOT / 'NEW_CP8_ROUTE_METADATA' / label
        (folder / 'prompt_only').mkdir(parents=True)
        (folder / 'prompt_only/prompt.txt').write_bytes(prompt.encode())
        if present:
            (folder / 'prompt_only/interface.txt').write_bytes(interface.encode())
        receipt = (composition.synthesize_with_framing if arm == 'P' else composition.synthesize)(prompt, interface)
        route = dict(schema='table_history_cp8_generation_route_v1',
                     route='mechanical_' + receipt['selected_provider'] if receipt['emitted'] else 'model',
                     outer_arm=arm, prompt_sha256=proof.digest(prompt), interface_sha256=proof.digest(interface),
                     interface_present=present, baseline_worker_sha256=proof.sha(ROOT / 'baseline_worker.py'),
                     synthesis_source_sha256=proof.sha(ROOT / 'composition.py'),
                     generated_solution_sha256=receipt['rtl_sha256'] if receipt['emitted'] else None)
        save(folder / 'generation_route.json', route)
        save(folder / 'synthesis_receipt.json', receipt)
        actual, recipe = bind(folder, arm, prompt, interface, present)
        assert actual == route and recipe == (receipt if receipt['emitted'] else None)
        positives.append(label)
        return folder, receipt

    old = {f['label']: f for f in proof.read(ROOT / 'RETAINED_INPUTS_PRIVATE.json')}
    for provider in ['onehot', 'timer']:
        f = old[provider]
        # Earlier retained producer fixtures contain input strings rather than
        # a filesystem-presence flag; this new metadata context declares it.
        _, receipt = metadata('new_complete_C_' + provider, 'C', f['prompt'], f['interface'], True)
        assert receipt['selected_provider'] == provider and receipt['original_recipe'] == f['receipt']

    fixtures = proof.read(ROOT / 'ORIGINAL113_INPUTS_PRIVATE.json')
    assert fixtures['schema'] == 'cp8_original113_two_input_recipe_private_fixture_v1'
    assert [f['task'] for f in fixtures['cases']] == ['Prob137_fsm_serial', 'Prob146_fsm_serialdata']
    contexts = []
    for f in fixtures['cases']:
        for binding in f['members'].values():
            assert proof.sha(ROOT / binding['local_relative_path']) == binding['sha256']
        prompt = (ROOT / f['members']['prompt.txt']['local_relative_path']).read_bytes().decode()
        original = proof.read(ROOT / f['members']['synthesis_receipt.json']['local_relative_path'])
        code = (ROOT / f['members']['solution.v']['local_relative_path']).read_bytes()
        interface, present = f['interface_text'], f['interface_present']
        _, control = metadata(f['task'] + '_C', 'C', prompt, interface, present)
        folder, candidate = metadata(f['task'] + '_P', 'P', prompt, interface, present)
        assert control['emitted'] is False and control['reason'] == 'no_complete_contract'
        assert candidate['selected_provider'] == 'serial_framing'
        assert candidate['original_recipe'] == original and candidate['rtl'].encode() == code
        assert candidate['parent_recipe'] == control['parent_recipe']
        assert candidate['extension_selection'] == control['extension_selection']
        assert candidate['extension_selection']['reason'] == 'no_complete_contract'
        contexts.append((folder, candidate, prompt, interface, present))

    folder, receipt, prompt, interface, present = contexts[0]
    changes = [('selected_provider', 'timer'), ('original_recipe', None), ('parent_recipe', None),
               ('extension_selection', None), ('rtl', 'module altered; endmodule'),
               ('contract', {'all_prompt_consumed': True, 'changed': True})]
    for field, value in changes:
        target = ROOT / 'NEW_CP8_REJECTS' / field
        shutil.copytree(folder, target)
        record = proof.read(target / 'synthesis_receipt.json')
        record[field] = value
        save(target / 'synthesis_receipt.json', record)
        rejects('serial_' + field + '_tampered', lambda: bind(target, 'P', prompt, interface, present))

    target = ROOT / 'NEW_CP8_REJECTS/C_serial_forgery'
    shutil.copytree(folder, target)
    route = proof.read(target / 'generation_route.json')
    route['outer_arm'] = 'C'
    save(target / 'generation_route.json', route)
    rejects('C_cannot_use_serial', lambda: bind(target, 'C', prompt, interface, present))

    target = ROOT / 'NEW_CP8_REJECTS/wave_receipt'
    shutil.copytree(folder, target)
    (target / 'waveform_request_receipts').mkdir()
    rejects('wave_factor_forbidden', lambda: bind(target, 'P', prompt, interface, present))

    # These records deliberately cannot count as a real native positive.
    target = ROOT / 'NEW_CP8_REJECTS/fake_serial_native'
    shutil.copytree(folder, target)
    save(target / 'requests.json', [])
    (target / 'solution.v').write_bytes(receipt['rtl'].encode())
    (target / 'emission').mkdir()
    (target / 'emission/emitted.sv').write_bytes(receipt['rtl'].encode())
    save(target / 'emission/contract.json', receipt['contract'])
    (target / 'native_receipts/0').mkdir(parents=True)
    save(target / 'native_receipts/0/command.json', dict(simulated=True, fixture='NEW_CP8_NEGATIVE_ONLY'))
    row = dict(arm='P', selected_provider='serial_framing', solve_deadline_reached=False,
               actual_model_requests=0, received_model_responses=0)
    rejects('simulated_serial_native_forbidden', lambda: proof.mechanical_provenance(
        target, ROOT, 'synthetic', row, receipt, target, SimpleNamespace(), None, None))

    modules = module_objects()
    proof.bound_modules(ROOT, modules)
    positives.append('actual_CP8_dependency_objects')
    replaced = dict(modules, providers=PROVIDERS[:-1] + [('serial_framing', SimpleNamespace(
        __file__=composition.serial_framing_producer.__file__))])
    rejects('serial_cached_other_object', lambda: proof.bound_modules(ROOT, replaced))
    with patch.object(composition.serial_framing_producer, 'KEYWORDS', frozenset({'wrong'})):
        rejects('serial_stale_keyword_dependency', lambda: proof.bound_modules(ROOT, modules))
    with patch.object(worker, 'synthesis', SimpleNamespace(__file__=composition.__file__)):
        rejects('worker_stale_composition_object', lambda: proof.bound_modules(ROOT, modules))
    with patch.object(proof, 'PINNED', dict(proof.PINNED, **{'serial_framing_producer.py': '0' * 64})):
        rejects('serial_source_SHA_mismatch', lambda: bind(folder, 'P', prompt, interface, present))

    assert all(proof.sha(ROOT / n) == h for n, h in manifest.items())
    result = dict(schema='table_history_cp8_new_generation_boundary_controls_v1', passed=True,
                  positive_contexts=len(positives), rejection_contexts=len(negatives),
                  positives=positives, rejections=negatives, original_two_recipes_and_RTL_retained=True,
                  old_model_replay_and_native_suites_not_executed=True, real_worker_model_EDA_FIFO_calls=0,
                  metadata_only=True, score_or_native_qualification=False)
    save(ROOT / 'ACTUAL_CP8_GENERATION_RESULT.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
