"""Only the new complete-parent/wave wrapper boundary; all services simulated.

Borrow Context setup helpers without running any previous test entry. The two
model contexts execute exact original baseline/runtime with fake HTTP/compiler.
"""
from contextlib import ExitStack
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import urllib.request
from unittest.mock import patch

import parent_context_fixture as f
import composition
import worker
import baseline_worker
import waveform_worker
import waveform_request
import waveform_facts
import request_proof

ROOT = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_bytes())
save = lambda p, j: Path(p).write_bytes((json.dumps(j, indent=2) + '\n').encode())


def mechanical_controls():
    results = []
    for provider in ['table', 'onehot', 'timer']:
        pair = []
        for arm in ['C', 'P']:
            h = f.Context('wave_bypass_' + provider + '_' + arm, arm,
                          parent=provider == 'table',
                          providers=('onehot', 'timer') if provider == 'table' else (provider,))
            with ExitStack() as stack:
                patches = [patch.object(worker, 'ROOT', h.owned),
                           patch.object(worker.baseline, 'load', side_effect=h.fake_load),
                           patch.object(worker.baseline, 'run_worker', side_effect=AssertionError('Mechanical parent cannot use model')),
                           patch.object(worker.baseline, 'functional_feedback', side_effect=h.fake_feedback),
                           patch.object(composition.table_synthesis, 'synthesize', return_value=copy.deepcopy(h.parent_recipe)),
                           patch.object(composition.table_synthesis.contract, 'parse_prompt',
                                        return_value=dict(admitted=True, all_prompt_consumed=True, contract=h.contract)),
                           patch.object(composition.onehot_producer, 'synthesize', side_effect=h.provider('onehot')),
                           patch.object(composition.timer_producer, 'synthesize', side_effect=h.provider('timer')),
                           patch.object(waveform_worker, 'run_worker', side_effect=AssertionError('Mechanical parent must bypass wave wrapper')),
                           patch('urllib.request.urlopen', side_effect=AssertionError('No real HTTP allowed')),
                           patch('subprocess.run', side_effect=AssertionError('No real tool allowed'))]
                for item in patches:
                    stack.enter_context(item)
                worker.run_worker(h.args, h.paired)
            out = h.args.out
            h.result, h.route, h.receipt = [read(out / n) for n in
                                          ['worker_result.json', 'generation_route.json', 'synthesis_receipt.json']]
            assert h.route['schema'] == 'table_history_wave_generation_route_v1'
            assert h.route['outer_arm'] == h.result['arm'] == arm
            assert not (out / 'waveform_request_receipts').exists()
            h.mechanical(provider)
            pair.append((h.receipt, (out / 'solution.v').read_bytes()))
            results.append(dict(provider=provider, arm=arm, requests=0, wave_wrapper_called=False))
        assert pair[0] == pair[1], 'C/P complete mechanical parent must preserve exact recipes and RTL'
    return results


def common_mock_contexts():
    assert worker.ROOT == baseline_worker.ROOT == waveform_worker.ROOT == ROOT
    assert waveform_worker.baseline_worker is baseline_worker and worker.baseline is baseline_worker
    assert waveform_worker.waveform_request is waveform_request
    assert waveform_request.waveform_facts is waveform_facts
    assert sha(ROOT / 'baseline_worker.py') == '7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742'
    assert sha(ROOT / 'package/agent/map_runtime.py') == '2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    save(ROOT / 'RUN_SPEC.json', dict(dependencies_cloud=str(ROOT), model='SIMULATED-complete-parent-wave',
                                      identity='complete-parent-wave-new-wrapper-controls'))
    os.environ.update(MODEL_NAME='SIMULATED-complete-parent-wave', RTL_REPAIRS='1', RTL_MAX_TOKENS='8192',
                      RTL_TEMPERATURE='0', LLM_BASE_URL='http://127.0.0.1:8000/v1')
    sys.path.insert(0, str(ROOT / 'package'))
    import baseline
    first = baseline.extract('module TopModule(input clk); wire value; always @(posedge clk) value<=1; endmodule', 'rtl')
    fixed = first.replace('wire value', 'reg value')
    error = 'ERROR: explicitly simulated first compiler failure'
    fixture = read(ROOT / 'WAVE_RETAINED_INPUT_PRIVATE.json')
    prompt, interface = fixture['prompt'], fixture['interface']
    expected = request_proof.combined(prompt, interface)
    contract = waveform_facts.parse(prompt)
    advice = waveform_facts.render_advice(contract)
    assert contract['status'] == 'supported' and advice
    # The complete parent's abstention is mocked here; old producers/intake are not rerun.
    abstention = composition._empty(prompt, interface) | dict(reason='FAKE_COMPLETE_PARENT_ABSTENTION')
    old_load, old_open, old_run = baseline_worker.load, urllib.request.urlopen, subprocess.run
    original_request = urllib.request.Request
    runtimes, activity, rows, wires_by_arm = [], [], [], {}

    def load(name, path):
        module = old_load(name, path)
        if str(path).endswith('/agent/map_runtime.py'):
            module.vivado_tool = lambda n: '/SIMULATED/' + n
            runtimes.append(module)
        return module

    class Paired:
        REPO = ROOT
        def check_resource(self, *args):
            return True
        def model_idle(self, *args):
            return True
        def owned_command(self, argv, wd, log, cap):
            assert cap == 60 and argv[:2] == ['/SIMULATED/xvlog', '--sv']
            index = len(compiles)
            compiles.append(Path(argv[-1]).read_text())
            log.write_text(error if index == 0 else '')
            return dict(returncode=1 if index == 0 else 0, timeout=False, launch_error=None,
                        remaining_live_group=[], log_sha256=sha(log), log_bytes=log.stat().st_size,
                        elapsed_s=0, simulated=True)

    fake_activity = types.SimpleNamespace(append=lambda *args: activity.append(dict(simulated=True, event=str(args[2]))))
    with patch.dict(sys.modules, activity=fake_activity), \
            patch.object(baseline_worker, 'load', side_effect=load), \
            patch.object(baseline_worker, 'functional_feedback', return_value=''), \
            patch.object(composition, 'synthesize', return_value=abstention):
        for arm in ['C', 'P']:
            source = ROOT / 'SIMULATED_WAVE_KIT' / arm / 'bench/tasks_veval/generic_input'
            source.mkdir(parents=True)
            (source / 'prompt.txt').write_bytes(prompt.encode())
            (source / 'interface.txt').write_bytes(interface.encode())
            folder = ROOT / 'ACTUAL_BASELINE_WAVE_MOCK_OUTPUTS' / arm
            wires, compiles = [], []

            def transport(request, **kwargs):
                index = len(wires)
                assert index < 2 and kwargs == dict(timeout=300)
                assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
                body = json.loads(request.data)
                generation, repair = runtimes[-1].skill_texts()
                assert body['messages'][0] == dict(role='system', content=generation + ('\n' + repair if index else ''))
                user = expected + ('\nPrevious candidate:\n' + first + '\nCandidate diagnostics:\n' + error if index else '')
                if arm == 'P' and index == 0:
                    user += waveform_request.MARKER + advice
                assert body['messages'][1] == dict(role='user', content=user)
                assert body['max_tokens'] == 8192 and body['temperature'] == 0 and body['top_p'] == 1
                wires.append(request.data)
                return io.BytesIO(json.dumps(dict(id='explicitly-simulated-wave-' + str(index),
                    choices=[dict(message=dict(content=first if index == 0 else fixed), finish_reason='stop')],
                    usage=dict(prompt_tokens=0, completion_tokens=0))).encode())

            args = types.SimpleNamespace(kit=source.parents[2], task='generic_input', arm=arm, out=folder,
                                         resource_check=ROOT / 'SIMULATED_RESOURCE.json')
            with patch('urllib.request.urlopen', side_effect=transport):
                worker.run_worker(args, Paired())
            assert urllib.request.urlopen is old_open and subprocess.run is old_run
            assert urllib.request.Request is original_request
            assert len(wires) == len(compiles) == 2
            assert (folder / 'solution.v').read_text() == fixed
            assert read(folder / 'generation_route.json')['route'] == 'model'
            assert read(folder / 'synthesis_receipt.json') == abstention
            assert not (folder / 'native_receipts').exists()
            generation, repair = runtimes[-1].skill_texts()
            proof = request_proof.verify(folder, prompt, interface, arm, 'SIMULATED-complete-parent-wave', generation, repair)
            assert proof['first_request_advice_changed'] is (arm == 'P')
            assert [r['changed'] for r in proof['rounds']] == [arm == 'P', False]
            save(folder / 'NEW_WRAPPER_WIRE_BINDING.json', request_proof.binding(proof))
            wires_by_arm[arm] = wires
            rows.append(dict(arm=arm, requests=2, first_wave_changed=arm == 'P', repair_changed=False,
                             first_wire_sha256=hashlib.sha256(wires[0]).hexdigest(),
                             repair_wire_sha256=hashlib.sha256(wires[1]).hexdigest()))
        assert wires_by_arm['C'][1] == wires_by_arm['P'][1]
        cbody, pbody = [json.loads(wires_by_arm[a][0]) for a in ['C', 'P']]
        cbody['messages'][1]['content'] += waveform_request.MARKER + advice
        assert cbody == pbody
        source = ROOT / 'SIMULATED_WAVE_KIT/P/bench/tasks_veval/generic_input'
        failed = ROOT / 'ACTUAL_BASELINE_WAVE_MOCK_OUTPUTS/transport_failure'
        args = types.SimpleNamespace(kit=source.parents[2], task='generic_input', arm='P', out=failed,
                                     resource_check=ROOT / 'SIMULATED_RESOURCE.json')
        with patch('urllib.request.urlopen', side_effect=OSError('explicit simulated transport failure')) as transport:
            try:
                worker.run_worker(args, Paired())
            except RuntimeError:
                pass
            else:
                raise AssertionError('Unconfirmed call accepted')
            assert transport.call_count == 1
        assert urllib.request.Request is original_request
        assert len(read(failed / 'requests.json')) == 1
        assert read(failed / 'requests.json')[0]['response_received'] is False
        assert not (failed / 'worker_result.json').exists()
        generation, repair = runtimes[-1].skill_texts()
        proof = request_proof.verify(failed, prompt, interface, 'P', 'SIMULATED-complete-parent-wave',
                                     generation, repair, allow_unconfirmed=True)
        assert proof['first_request_advice_changed'] and not proof['all_responses_confirmed']
    assert urllib.request.urlopen is old_open and subprocess.run is old_run
    assert urllib.request.Request is original_request
    save(ROOT / 'SIMULATED_WAVE_ACTIVITY.json', activity)
    return rows


def main():
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    manifest = read(ROOT / 'SOURCE_MANIFEST.json')
    assert all(sha(ROOT / n) == h for n, h in manifest.items())
    mechanics = mechanical_controls()
    model_rows = common_mock_contexts()
    assert all(sha(ROOT / n) == h for n, h in manifest.items())
    result = dict(schema='scope_B_complete_parent_wave_new_worker_controls_v1', passed=True,
                  mechanical_new_wrapper_contexts=6, mechanical_rows=mechanics,
                  original_baseline_runtime_mock_contexts=2, transport_failure_contexts=1,
                  model_rows=model_rows, C_P_mechanical_recipe_and_RTL_identical=True,
                  P_first_wave_only_and_raw_repairs_identical=True, Request_restored_after_failure=True,
                  production_producers_and_native_HTTP_functional_probe_activity_explicitly_mocked=True,
                  original_wave_request_facts_proof_and_baseline_runtime_executed_at_new_boundary=True,
                  old_test_suites_native_intake_not_rerun=True, real_model_EDA_FIFO_calls=0,
                  real_native_or_score_qualification=False)
    save(ROOT / 'ACTUAL_HISTORY_WAVE_WORKER_RESULT.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
