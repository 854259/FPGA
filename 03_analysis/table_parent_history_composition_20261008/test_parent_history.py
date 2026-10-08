"""New parent/extension wiring controls; producers, model and native are fake.

The unchanged selector is used only at the new composition boundary. This does
not rerun old producer algorithms, worker suites, native checks or intake.
"""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

import composition as c
import worker

ROOT = Path(__file__).resolve().parent
PROMPT = 'SYNTHETIC composition boundary\r\n'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def read(path):
    return json.loads(Path(path).read_bytes())


def recipe(prompt, interface, provider, emitted=True):
    contract = dict(fixture='FAKE_NEW_COMPOSITION_INTERFACE', all_prompt_consumed=True,
                    provider=provider)
    result = dict(schema='FAKE_RECEIPT_NOT_NATIVE_QUALIFICATION', emitted=emitted,
                  prompt_sha256=c._sha(prompt.encode()),
                  interface_sha256=c._sha(interface.encode()), actual_model_requests=0,
                  actual_eda_calls=0, external_io_calls=0, rtl='', reason='fake_abstention')
    if emitted:
        rtl = 'module TopModule; // FAKE ' + provider + '\nendmodule\n'
        result.update(rtl=rtl, rtl_sha256=c._sha(rtl.encode()), reason=None,
                      contract_sha256=c._sha(c._json(contract)), all_prompt_consumed=True)
        if provider != 'table':
            result['contract'] = contract
    elif provider != 'table':
        result['contract'] = None
    return result, contract


class Context:
    def __init__(self, name, arm, parent=False, providers=(), requests=1, interface=''):
        self.root = ROOT / 'FAKE_COMPOSITION_CONTEXTS' / name
        self.root.mkdir(parents=True, exist_ok=False)
        self.source = self.root / 'kit/bench/tasks_veval/FAKE_TASK'
        self.source.mkdir(parents=True)
        (self.source / 'prompt.txt').write_bytes(PROMPT.encode())
        if interface:
            (self.source / 'interface.txt').write_bytes(interface.encode())
        self.owned = self.root / 'owned'
        self.owned.mkdir()
        for name in ['composition.py', 'baseline_worker.py']:
            (self.owned / name).write_bytes((ROOT / name).read_bytes())
        save(self.owned / 'RUN_SPEC.json', dict(dependencies_cloud=str(self.root / 'deps')))
        self.args = SimpleNamespace(arm=arm, kit=self.root / 'kit', task='FAKE_TASK',
                                    out=self.root / 'worker', resource_check=self.root / 'FAKE_RESOURCE.json')
        self.calls, self.commands, self.feedback_calls, self.extension_calls = [], [], [], []
        self.returncode, self.requests = 0, requests
        self.parent_recipe, self.contract = recipe(PROMPT, interface, 'table', parent)
        self.extensions = {n: recipe(PROMPT, interface, n, n in providers)[0]
                           for n in ['onehot', 'timer']}
        self.paired = SimpleNamespace(check_resource=lambda *args: None,
                                      owned_command=self.fake_compile)

    def fake_compile(self, argv, cwd, log, seconds):
        self.commands.append((argv, seconds))
        Path(log).write_bytes(b'FAKE COMPILE NO TOOL EXECUTION\n')
        return dict(returncode=self.returncode, timeout=False, launch_error=None,
                    remaining_live_group=[], log_sha256=sha(log), log_bytes=Path(log).stat().st_size,
                    elapsed_s=0.01, fixture='SIMULATED_NO_NATIVE_EXECUTION')

    def fake_load(self, name, path):
        if Path(path).name == 'map_runtime.py':
            return SimpleNamespace(vivado_tool=lambda n: '/FAKE/xvlog')
        if Path(path).name == 'probe_runner.py':
            return SimpleNamespace(ENVIRONMENT_ERROR=re.compile('FAKE_ENVIRONMENT_BROKEN'))
        raise AssertionError('Unexpected module load')

    def fake_feedback(self, *args, **kwargs):
        self.feedback_calls.append((args, kwargs))
        return ''

    def fake_baseline(self, args, paired):
        self.calls.append((args.arm, args.out, paired))
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out / 'prompt_only').mkdir()
        for n, b in worker.raw_inputs(self.source).items():
            (args.out / 'prompt_only' / n).write_bytes(b)
        (args.out / 'solution.v').write_bytes(b'module TopModule; endmodule\n')
        (args.out / 'trace.jsonl').write_bytes(b'')
        save(args.out / 'requests.json', [dict(index=i, fixture='FAKE_NO_HTTP') for i in range(self.requests)])
        save(args.out / 'worker_result.json', dict(complete=True, arm=args.arm, requests=self.requests,
             actual_model_requests=self.requests, received_model_responses=self.requests,
             solution_sha256=sha(args.out / 'solution.v')))

    def provider(self, name):
        def call(prompt, interface):
            self.extension_calls.append(name)
            assert prompt == PROMPT
            return copy.deepcopy(self.extensions[name])
        return call

    def run(self):
        with ExitStack() as stack:
            patches = [patch.object(worker, 'ROOT', self.owned),
                       patch.object(worker.baseline, 'load', side_effect=self.fake_load),
                       patch.object(worker.baseline, 'run_worker', side_effect=self.fake_baseline),
                       patch.object(worker.baseline, 'functional_feedback', side_effect=self.fake_feedback),
                       patch.object(c.table_synthesis, 'synthesize', return_value=copy.deepcopy(self.parent_recipe)),
                       patch.object(c.table_synthesis.contract, 'parse_prompt',
                                    return_value=dict(admitted=True, all_prompt_consumed=True, contract=self.contract)),
                       patch.object(c.onehot_producer, 'synthesize', side_effect=self.provider('onehot')),
                       patch.object(c.timer_producer, 'synthesize', side_effect=self.provider('timer')),
                       patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP allowed')),
                       patch('subprocess.run', side_effect=AssertionError('No real tool allowed'))]
            for item in patches:
                stack.enter_context(item)
            worker.run_worker(self.args, self.paired)
        out = self.args.out
        self.result, self.route, self.receipt = [read(out / n) for n in
                                               ['worker_result.json', 'generation_route.json', 'synthesis_receipt.json']]
        assert self.result['arm'] == self.route['outer_arm'] == self.args.arm
        assert self.route['schema'] == 'table_parent_history_extension_generation_route_v1'
        assert self.route['synthesis_source_sha256'] == sha(ROOT / 'composition.py')
        assert self.route['baseline_worker_sha256'] == sha(ROOT / 'baseline_worker.py')
        assert worker.raw_inputs(out / 'prompt_only') == worker.raw_inputs(self.source)
        assert not (out / 'generation_selection.json').exists()
        return self

    def mechanical(self, provider):
        assert self.result['generation_route'] == self.route['route'] == 'mechanical_' + provider
        assert self.receipt['selected_provider'] == provider
        original = self.parent_recipe if provider == 'table' else self.extensions[provider]
        assert self.receipt['original_recipe'] == original
        assert self.receipt['original_recipe_sha256'] == c._sha(c._json(original))
        assert (self.args.out / 'solution.v').read_bytes() == original['rtl'].encode()
        assert read(self.args.out / 'requests.json') == [] and self.result['actual_model_requests'] == 0
        assert len(self.commands) == 1 and self.commands[0][1] == 60 and self.calls == []
        assert len(self.feedback_calls) == (1 if self.returncode == 0 else 0)
        if self.feedback_calls:
            assert self.feedback_calls[0][1] == dict(candidate=True)
        assert read(self.args.out / 'native_feedback.json')['repair_requested'] is False

    def model(self):
        assert self.route['route'] == self.result['generation_route'] == 'model'
        assert self.receipt['emitted'] is False and self.receipt['rtl'] is None
        assert self.calls == [(self.args.arm, self.args.out, self.paired)] and self.commands == []
        assert len(read(self.args.out / 'requests.json')) == self.requests


def main():
    cases = []
    parents = []
    for arm in ['C', 'P']:
        h = Context('parent_' + arm, arm, parent=True, providers=('onehot', 'timer')).run()
        h.mechanical('table')
        assert h.extension_calls == [] and h.receipt['extension_selection'] is None
        parents.append(h.receipt)
        cases.append('parent_priority_' + arm)
    assert parents[0] == parents[1]
    for provider in ['onehot', 'timer']:
        h = Context('extension_' + provider, 'P', providers=(provider,)).run()
        h.mechanical(provider)
        assert h.extension_calls == ['onehot', 'timer']
        assert h.receipt['parent_recipe'] == h.parent_recipe and not h.parent_recipe['emitted']
        assert h.receipt['extension_selection']['recipe'] == h.extensions[provider]
        cases.append('unique_extension_' + provider)
    for arm, providers, count, label in [('C', ('onehot',), 1, 'C_skips_extensions'),
                                         ('P', (), 2, 'P_both_abstain'),
                                         ('P', ('onehot', 'timer'), 1, 'P_collision')]:
        h = Context(label, arm, providers=providers, requests=count).run()
        h.model()
        assert h.extension_calls == ([] if arm == 'C' else ['onehot', 'timer'])
        cases.append(label)
    h = Context('invalid_extension', 'P', providers=('onehot',))
    h.extensions['onehot']['rtl_sha256'] = '0' * 64
    h.run().model()
    assert h.receipt['extension_selection']['reason'] == 'invalid_provider_receipt'
    cases.append('invalid_extension_abstains')
    for field, value in [('prompt_sha256', '0' * 64), ('rtl_sha256', '0' * 64),
                         ('actual_model_requests', False), ('all_prompt_consumed', False)]:
        h = Context('damaged_parent_' + field, 'P', parent=True, providers=('onehot',))
        h.parent_recipe[field] = value
        try:
            h.run()
        except AssertionError:
            assert h.extension_calls == h.commands == h.calls == []
            cases.append('damaged_parent_' + field + '_fails_closed')
        else:
            raise AssertionError('Damaged parent must fail closed')
    h = Context('damaged_parent_abstention', 'P', providers=('onehot',))
    h.parent_recipe['rtl'] = 'unexpected answer'
    try:
        h.run()
    except AssertionError:
        assert h.extension_calls == h.commands == h.calls == []
        cases.append('damaged_parent_abstention_fails_closed')
    else:
        raise AssertionError('Invalid parent abstention reached extension')
    h = Context('parent_native_failure', 'C', parent=True)
    h.returncode = 1
    h.run().mechanical('table')
    cases.append('C_native_failure_does_not_expand_budget')
    for arm in ['C', 'P']:
        h = Context('raw_fallback_' + arm, arm, interface='input untouched;\r\n', requests=2).run()
        h.model()
        cases.append('raw_input_original_delegate_' + arm)
    try:
        c.score_admission()
    except RuntimeError:
        cases.append('score_CLI_remains_closed')
    else:
        raise AssertionError('Draft score entry opened')
    result = dict(schema='table_parent_history_new_interface_controls_v1', passed=True,
                  cases=cases, contexts=len(cases), producers_model_native_explicitly_mocked=True,
                  unchanged_selector_used_only_at_new_boundary=True,
                  old_controls_or_native_or_intake_rerun=False, actual_model_calls=0,
                  actual_eda_calls=0, real_native_or_score_qualification=False)
    save(ROOT / 'ACTUAL_PARENT_HISTORY_RESULT.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
