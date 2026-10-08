"""New CP8 composition/worker boundaries only; run on authorized AMD only.

The original helper's main/run suites are not called. Original 113 prompt and
recipe bytes are private fixtures. Native, feedback and model delegation below
are simulated; these controls cannot establish a score or native qualification.
"""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

import composition as c
import worker
import parent_context_fixture as h

ROOT = Path(__file__).resolve().parent


def synthetic_producers(context):
    return [
        patch.object(c.table_synthesis, 'synthesize',
                     return_value=copy.deepcopy(context.parent_recipe)),
        patch.object(c.table_synthesis.contract, 'parse_prompt',
                     return_value=dict(admitted=True, all_prompt_consumed=True,
                                       contract=context.contract)),
        patch.object(c.onehot_producer, 'synthesize', side_effect=context.provider('onehot')),
        patch.object(c.timer_producer, 'synthesize', side_effect=context.provider('timer')),
    ]


def read_originals():
    fixture = h.read(ROOT / 'ORIGINAL113_INPUTS_PRIVATE.json')
    assert fixture['archive_sha256'] == 'a7955870db34dca330ec87aaf9f88a0ca87f07b6530ac3c73ae6ac486bdedc0b'
    cases = []
    for case in fixture['cases']:
        contents = {}
        for name, record in case['members'].items():
            path = ROOT / record['local_relative_path']
            assert h.sha(path) == record['sha256']
            contents[name] = path.read_bytes()
        assert case['interface_present'] is False and case['interface_text'] == ''
        original = json.loads(contents['synthesis_receipt.json'])
        assert original['prompt_sha256'] == c._sha(contents['prompt.txt'])
        assert original['interface_sha256'] == c._sha(b'')
        assert original['rtl'].encode() == contents['solution.v']
        assert original['rtl_sha256'] == c._sha(contents['solution.v'])
        cases.append((case['task'], contents['prompt.txt'], original))
    assert [item[0] for item in cases] == ['Prob137_fsm_serial', 'Prob146_fsm_serialdata']
    return cases


def run_new_worker(context, expected, synthetic=False, forbid_serial=False):
    """Reuse old fake transport helpers, without calling their old test runner."""
    with ExitStack() as stack:
        patches = [
            patch.object(worker, 'ROOT', context.owned),
            patch.object(worker.baseline, 'load', side_effect=context.fake_load),
            patch.object(worker.baseline, 'run_worker', side_effect=context.fake_baseline),
            patch.object(worker.baseline, 'functional_feedback', side_effect=context.fake_feedback),
            patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP allowed')),
            patch('subprocess.run', side_effect=AssertionError('No real tool allowed')),
        ]
        if synthetic:
            patches += synthetic_producers(context)
        if forbid_serial:
            patches += [patch.object(c.serial_framing_producer, 'synthesize',
                                     side_effect=AssertionError('C cannot call serial provider'))]
        for item in patches:
            stack.enter_context(item)
        worker.run_worker(context.args, context.paired)
    out = context.args.out
    result = h.read(out / 'worker_result.json')
    route = h.read(out / 'generation_route.json')
    receipt = h.read(out / 'synthesis_receipt.json')
    assert receipt == expected
    assert route['schema'] == 'table_history_cp8_generation_route_v1'
    assert route['outer_arm'] == result['arm'] == context.args.arm
    assert route['synthesis_source_sha256'] == h.sha(ROOT / 'composition.py')
    assert route['baseline_worker_sha256'] == h.sha(ROOT / 'baseline_worker.py')
    assert worker.raw_inputs(out / 'prompt_only') == worker.raw_inputs(context.source)
    if expected['emitted']:
        assert result['generation_route'] == route['route'] == 'mechanical_' + expected['selected_provider']
        assert (out / 'solution.v').read_bytes() == expected['rtl'].encode()
        assert h.read(out / 'requests.json') == [] and result['actual_model_requests'] == 0
        assert len(context.commands) == 1 and context.commands[0][1] == 60
        assert context.calls == [] and len(context.feedback_calls) == 1
        assert context.feedback_calls[0][1] == dict(candidate=True)
        assert h.read(out / 'native_feedback.json')['repair_requested'] is False
        events = [json.loads(line) for line in (out / 'trace.jsonl').read_text().splitlines()]
        assert [event['tool'] for event in events] == [expected['selected_provider'] + '_generation',
                                                      'lint_start', 'lint', 'native_feedback']
    else:
        assert result['generation_route'] == route['route'] == 'model'
        assert context.calls == [(context.args.arm, context.args.out, context.paired)]
        assert context.commands == context.feedback_calls == []
        assert len(h.read(out / 'requests.json')) == context.requests
    assert not list(out.glob('*wave*'))


def main():
    cases = []
    adaptation = h.read(ROOT / 'ADAPTATION.json')
    for name, field in [('composition.py', 'composition_sha256'), ('worker.py', 'worker_sha256'),
                        ('serial_framing_producer.py', 'serial_framing_producer_sha256')]:
        assert h.sha(ROOT / name) == adaptation[field]

    # Only new parent-preservation behavior is checked, with old producers fake.
    for provider in ['table', 'onehot', 'timer']:
        context = h.Context('cp8_preserve_' + provider, 'P', parent=provider == 'table',
                            providers=() if provider == 'table' else (provider,))
        with ExitStack() as stack:
            for item in synthetic_producers(context):
                stack.enter_context(item)
            serial = stack.enter_context(patch.object(c.serial_framing_producer, 'synthesize',
                                         side_effect=AssertionError('Parent hit must not reach serial')))
            parent = c.synthesize(h.PROMPT)
            extended = c.synthesize_with_framing(h.PROMPT)
            assert c._json(parent) == c._json(extended)
            assert parent['selected_provider'] == provider
            assert parent['rtl'].encode() == extended['rtl'].encode()
            serial.assert_not_called()
        cases.append('complete_parent_' + provider + '_bytes_preserved')
        # The newly expanded C role needs only its newly admitted two providers.
        if provider in ('onehot', 'timer'):
            context.args.arm = 'C'
            run_new_worker(context, parent, synthetic=True, forbid_serial=True)
            cases.append('C_worker_' + provider + '_preserved')

    for name, providers, reason in [
        ('invalid', ('onehot',), 'invalid_provider_receipt'),
        ('ambiguous', ('onehot', 'timer'), 'ambiguous_complete_contracts'),
    ]:
        context = h.Context('cp8_' + name, 'P', providers=providers)
        if name == 'invalid':
            context.extensions['onehot']['rtl_sha256'] = '0' * 64
        with ExitStack() as stack:
            for item in synthetic_producers(context):
                stack.enter_context(item)
            serial = stack.enter_context(patch.object(c.serial_framing_producer, 'synthesize',
                                         side_effect=AssertionError('Unsafe parent abstention reached serial')))
            parent = c.synthesize(h.PROMPT)
            extended = c.synthesize_with_framing(h.PROMPT)
            assert not parent['emitted'] and parent['reason'] == reason
            assert c._json(parent) == c._json(extended)
            serial.assert_not_called()
        cases.append(name + '_parent_abstention_does_not_open_serial')

    context = h.Context('cp8_serial_abstains', 'P')
    with ExitStack() as stack:
        for item in synthetic_producers(context):
            stack.enter_context(item)
        serial = stack.enter_context(patch.object(c.serial_framing_producer, 'synthesize',
                                      return_value=h.recipe(h.PROMPT, '', 'serial_framing', False)[0]))
        parent = c.synthesize(h.PROMPT)
        extended = c.synthesize_with_framing(h.PROMPT)
        assert parent['reason'] == 'no_complete_contract'
        assert c._json(parent) == c._json(extended)
        serial.assert_called_once_with(h.PROMPT, '')
    cases.append('normal_parent_and_serial_abstention_preserves_fallback')

    # These are two checks of the new composition against retained original 113
    # recipes, not a replay of CP8 native/worker/score suites or full intake.
    for index, (task, prompt_bytes, original) in enumerate(read_originals()):
        prompt = prompt_bytes.decode('utf-8')
        parent = c.synthesize(prompt)
        assert not parent['emitted'] and parent['reason'] == 'no_complete_contract'
        extended = c.synthesize_with_framing(prompt)
        assert extended['selected_provider'] == 'serial_framing'
        assert extended['original_recipe'] == original
        assert extended['original_recipe_sha256'] == c._sha(c._json(original))
        assert extended['rtl'] == original['rtl']
        assert extended['parent_recipe'] == parent['parent_recipe']
        assert extended['extension_selection'] == parent['extension_selection']
        cases.append(task + '_new_composition_bound_to_original113_recipe')
        context = h.Context('cp8_original_' + str(index) + '_P', 'P')
        (context.source / 'prompt.txt').write_bytes(prompt_bytes)
        run_new_worker(context, extended)
        cases.append(task + '_new_serial_worker_path_simulated_native')
        if index == 0:
            context = h.Context('cp8_original_C_model', 'C', requests=2)
            (context.source / 'prompt.txt').write_bytes(prompt_bytes)
            run_new_worker(context, parent, forbid_serial=True)
            cases.append('C_original_serial_input_retains_common_model_delegate')

    result = dict(schema='table_history_cp8_new_boundary_controls_v1', passed=True,
                  cases=cases, checks=len(cases), worker_contexts=5,
                  synthetic_parent_boundary_producers_mocked=True,
                  two_original113_recipes_reconstructed_at_new_composition_boundary=True,
                  model_native_and_feedback_explicitly_mocked=True,
                  original_helper_main_or_run_called=False,
                  old_worker_native_intake_or_audit_suites_rerun=False,
                  actual_model_calls=0, actual_eda_calls=0,
                  real_native_or_score_qualification=False)
    h.save(ROOT / 'ACTUAL_CP8_EXTENSION_RESULT.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
