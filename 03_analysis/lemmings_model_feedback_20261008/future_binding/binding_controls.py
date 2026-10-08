"""AMD-only eight binding controls from future ACTUAL exact-DUT native records.

Adapt the retained serial binding-controls copy/projection approach. Every case
is explicitly SIMULATED; native originals remain immutable. No HTTP, worker,
checker, oracle, EDA, scheduler or subprocess is run by this qualifier.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import traceback
import urllib.request
from unittest.mock import patch


CORE_SHA = 'b5608f4d48e68a8c6f1fb40119226dd0685ade946abcdb29ef1e45fa7ae852ad'
CHECKER_SHA = 'e178d62a61bd279bb3dfcf4a17357a90e8a26b4537da83ba0f6e3714ae0a753a'
EXTRACTOR_SHA = '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
CASES = ('positive_bad_then_good', 'reject_trace_log_hash', 'reject_counterexample_event',
         'reject_log_event_semantics', 'reject_next_request_diagnostic', 'reject_missing_trace_binding',
         'reject_native_summary_mismatch', 'reject_feedback_without_successful_lint')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_file(path, boundary):
    path, boundary = Path(path), Path(boundary).resolve()
    assert not path.is_symlink() and path.is_file()
    assert path.resolve().is_relative_to(boundary)
    return path.resolve()


def run(args):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    root, origin, out = (p.resolve() for p in (args.source_root, args.original_packet_root, args.out))
    assert root == Path(__file__).resolve().parent and root != origin
    assert not root.is_relative_to(origin) and not origin.is_relative_to(root)
    assert not out.exists() and out != root and not root.is_relative_to(out)
    assert not out.is_relative_to(origin) and not origin.is_relative_to(out)
    originals, rewrites, mutations, reports = {}, [], [], []

    def remember(path, digest=None):
        path = safe_file(path, origin)
        actual = sha(path)
        assert digest is None or digest == actual, str(path)
        assert str(path) not in originals or originals[str(path)] == actual
        originals[str(path)] = actual
        return path

    spec_path = safe_file(root / 'RUN_SPEC.json', root)
    assert sha(spec_path) == args.run_spec_sha256
    frozen = read(spec_path)
    sources = frozen['source_hashes']
    assert isinstance(sources, dict) and sources
    for name in ('worker.py', 'baseline_worker.py', 'lemmings_binding.py', 'binding_controls.py',
                 'lemmings_feedback.py', 'package/baseline.py', 'package/agent/map_runtime.py'):
        assert name in sources
    for name, digest in sources.items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert sha(safe_file(root / name, root)) == digest
    assert sources['binding_controls.py'] == sha(__file__)
    assert sources['lemmings_feedback.py'] == CHECKER_SHA
    assert sources['package/baseline.py'] == EXTRACTOR_SHA
    dependencies = Path(frozen['dependencies_cloud']).resolve()
    dependency_hashes = {}
    for name in ('paired_checkpoint.py', 'probe_runner.py'):
        dep = safe_file(dependencies / name, dependencies)
        assert sha(dep) == frozen['dependency_hashes'][name]
        dependency_hashes[str(dep)] = sha(dep)

    pure_path = remember(args.pure_flow_result, args.pure_flow_result_sha256)
    pure = read(pure_path)
    assert pure['complete'] is True and pure['passed'] is True and pure['error'] is None
    assert pure['real_model_calls'] == pure['real_eda_commands'] == 0
    assert pure['implementation_manifest_sha256'] == CORE_SHA
    manifest = remember(origin / 'SOURCE_MANIFEST.json', pure['source_manifest_sha256'])
    old_sources = read(manifest)
    for name, digest in old_sources.items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        remember(origin / name, digest)
    assert old_sources['IMPLEMENTATION_MANIFEST.json'] == CORE_SHA
    assert old_sources['lemmings_feedback.py'] == CHECKER_SHA
    assert old_sources['package/baseline.py'] == EXTRACTOR_SHA
    # New worker/binder are allowed; every retained baseline/runtime/skill byte
    # must still be the one used by the original three-flow qualification.
    for name, digest in old_sources.items():
        if name == 'baseline_worker.py' or name.startswith('package/'):
            assert sources[name] == digest
    for name, digest in pure['fixed_control_source_hashes'].items():
        assert old_sources[name] == digest
    flow_path = remember(pure_path.parent / 'flow_results/FLOW_RESULT.json')
    flow = read(flow_path)
    assert flow == pure['reports']['flow']
    assert flow['complete'] and flow['passed'] and flow['simulated']
    assert flow['actual_model_calls'] == flow['actual_eda_calls'] == 0
    assert flow['simulated_http_calls'] == 4 and flow['first_C_P_request_identical'] is True
    seed = flow_path.parent / 'flow/candidate_repairs_once'
    flow_control = read(remember(seed / 'CONTROL_RESULT.json'))
    assert flow_control == flow['reports']['candidate_repairs_once']
    assert flow_control['passed'] and flow_control['simulated']
    assert flow_control['real_model_calls'] == flow_control['real_eda_calls'] == 0
    request_receipts = read(remember(seed / 'requests.json'))
    assert len(request_receipts) == 2
    seed_files = ['requests.json', 'trace.jsonl', 'solution.v', 'worker_result.json', 'prompt_only/prompt.txt']
    if (seed / 'prompt_only/interface.txt').exists():
        seed_files.append('prompt_only/interface.txt')
    for attempt in (0, 1):
        receipt = request_receipts[attempt]
        assert receipt['index'] == attempt and receipt['response_received'] is True
        assert receipt['replayed'] is False
        for name in ('request', 'response'):
            relative = 'requests/' + str(attempt) + '/' + name + '.json'
            remember(seed / relative, receipt[name + '_sha256'])
            seed_files.append(relative)
    for name in seed_files:
        remember(seed / name)

    native_path = remember(args.native_result, args.native_result_sha256)
    inputs_path = remember(args.binding_inputs, args.binding_inputs_sha256)
    assert native_path.name == 'EXACT_DUT_EXTENSION_RESULT.json'
    assert inputs_path == native_path.parent / 'BINDING_INPUTS.json'
    native, inputs = read(native_path), read(inputs_path)
    assert native['schema'] == 'lemmings_exact_flow_dut_native_extension_result_v1'
    assert native['complete'] is True and native['passed'] is True
    assert native['actual_model_calls'] == 0 and native['actual_eda_commands'] == 6
    assert native['extra_cases'] == 2 and native['original_sources_unchanged'] is True
    assert native['original_worker_reexecuted'] is False
    assert native['original_21_native_reexecuted'] is False
    assert native['core_manifest_sha256'] == CORE_SHA
    assert native['official_extractor_sha256'] == EXTRACTOR_SHA
    assert native['pure_flow_result_sha256'] == args.pure_flow_result_sha256
    assert inputs['schema'] == 'synthetic_exact_dut_binding_inputs_v1'
    assert inputs['qualified'] is True and inputs['actual_model_calls'] == 0
    assert inputs['result_sha256'] == args.native_result_sha256
    assert inputs['cases'] == native['records'] and len(native['records']) == 2
    for name, digest in native['original_evidence_sha256'].items():
        remember(name, digest)
    plan = read(remember(origin / 'EXACT_DUT_CASES.json', old_sources['EXACT_DUT_CASES.json']))
    assert plan['schema'] == 'lemmings_exact_flow_dut_native_extension_v1'
    assert plan['core_manifest_sha256'] == CORE_SHA and plan['official_extractor_sha256'] == EXTRACTOR_SHA
    assert len(plan['cases']) == 2
    record_files = []
    for attempt, (record, planned) in enumerate(zip(native['records'], plan['cases'])):
        assert record['name'] == planned['name']
        assert record['original_flow_attempt'] == planned['original_flow_attempt'] == attempt
        assert record['expected'] == planned['expected'] == ('semantic_mismatch' if attempt == 0 else 'pass')
        assert record['passed'] is True and record['synthetic_source'] is True
        assert record['reused_core_native_evidence'] is False and record['actual_model_calls'] == 0
        assert record['actual_native_stages'] == 3
        assert record['retained_flow_feedback_equal_to_native'] == (attempt == 0)
        case_dir = native_path.parent / record['name']
        check = case_dir / 'native/lemmings_check_0'
        assert record['native_check'] == str(check)
        assert record['original_flow_solve'] == str(seed)
        assert record['original_flow_response'] == str(seed / 'requests' / str(attempt) / 'response.json')
        assert record['original_flow_input'] == str(seed / ('lemmings_check_' + str(attempt)) / 'input.sv')
        assert record['original_response_sha256'] == request_receipts[attempt]['response_sha256']
        flow_input = remember(record['original_flow_input'], record['original_flow_input_sha256'])
        exact = record['exact_dut_sha256']
        assert exact == record['native_input_sha256'] == record['native_dut_sha256']
        assert exact == sha(flow_input) == planned['expected_extracted_dut_sha256']
        assert flow_input.stat().st_size == planned['expected_extracted_bytes']
        fixture = remember(origin / planned['flow_fixture'], planned['flow_fixture_sha256'])
        extraction_path = remember(record['extractor_receipt'], record['extractor_receipt_sha256'])
        assert extraction_path == case_dir / 'EXTRACTION_RECEIPT.json'
        extraction = read(extraction_path)
        assert extraction['schema'] == 'official_extractor_to_exact_synthetic_dut_v1'
        assert extraction['executed_on_amd'] is True and extraction['actual_execution_required'] is True
        assert extraction['synthetic_model_response'] is True
        assert extraction['model_generated_competition_design'] is False
        assert extraction['official_extractor_sha256'] == EXTRACTOR_SHA
        assert extraction['official_extractor_path'] == str(origin / 'package/baseline.py')
        assert extraction['original_flow_attempt'] == attempt
        assert extraction['flow_input'] == str(flow_input)
        assert extraction['flow_response'] == record['original_flow_response']
        assert extraction['exact_dut_sha256'] == exact
        assert extraction['exact_dut_bytes'] == flow_input.stat().st_size
        canonical = remember(extraction['official_extracted_fixture'], exact)
        assert canonical == case_dir / 'official_extracted_fixture.sv'
        assert canonical.read_bytes() == flow_input.read_bytes()
        for path, digest in extraction['original_evidence_sha256'].items():
            remember(path, digest)
        assert extraction['original_evidence_sha256'][str(fixture)] == planned['flow_fixture_sha256']
        assert read(remember(case_dir / 'EXACT_DUT_CASE_RESULT.json')) == record
        required = {'input.sv', 'contract.json', 'trace_binding.json', 'probe/adapter_receipt.json',
                    'probe/result.json', 'probe/dut.sv', 'probe/tb.sv',
                    'probe/xvlog.log', 'probe/xelab.log', 'probe/xsim.log'}
        if attempt == 0:
            required |= {'counterexample.json', 'feedback.txt'}
        assert set(record['native_evidence_sha256']) == required
        for name, digest in record['native_evidence_sha256'].items():
            remember(check / name, digest)
        assert (check / 'input.sv').read_bytes() == (check / 'probe/dut.sv').read_bytes() == canonical.read_bytes()
        result, adapter = read(check / 'probe/result.json'), read(check / 'probe/adapter_receipt.json')
        extras = {'inherited_runner_path', 'inherited_runner_sha256', 'oracle_adapter_path',
                  'oracle_adapter_sha256', 'inherited_result_path', 'inherited_result_sha256'}
        assert {k: v for k, v in adapter.items() if k not in extras} == result
        assert result.get('simulated', False) is False and result['inputs_unchanged'] is True
        assert result['outdir'] == str(check / 'probe') and result['task'] == 'SyntheticLemmings'
        assert result['status'] == ('fail' if attempt == 0 else 'pass')
        assert adapter['inherited_result_path'] == str(check / 'probe/result.json')
        assert adapter['inherited_result_sha256'] == sha(check / 'probe/result.json')
        for name, key in (('probe_runner.py', 'inherited_runner'), ('paired_checkpoint.py', 'oracle_adapter')):
            dep = remember(adapter[key + '_path'], adapter[key + '_sha256'])
            assert dep.name == name and adapter[key + '_sha256'] == frozen['dependency_hashes'][name]
        assert [x['name'] for x in result['stages']] == ['xvlog', 'xelab', 'xsim']
        for stage in result['stages']:
            log = check / 'probe' / (stage['name'] + '.log')
            assert stage.get('simulated', False) is False and stage['returncode'] == 0
            assert stage['timeout'] is False and stage['launch_error'] is None
            assert stage['remaining_live_group'] == [] and stage['log'] == str(log)
            assert stage['log_sha256'] == sha(log) and stage['log_bytes'] == log.stat().st_size
        tb = remember(check / 'inputs/SyntheticLemmings/tb.sv', result['tb_sha256'])
        assert tb.read_bytes() == (check / 'probe/tb.sv').read_bytes()
        if attempt == 0:
            for name in ('feedback.txt', 'counterexample.json'):
                old = remember(seed / 'lemmings_check_0' / name)
                if name.endswith('.json'):
                    assert read(old) == read(check / name)
                else:
                    assert old.read_bytes() == (check / name).read_bytes()
        record_files.append(sorted(required | {'inputs/SyntheticLemmings/tb.sv'}))

    out.mkdir(parents=True, exist_ok=False)

    def copy_file(source, dest):
        source = remember(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(source.read_bytes())
        assert sha(dest) == originals[str(source)]

    def native_copy(case, attempt):
        source = Path(native['records'][attempt]['native_check'])
        target = case / ('lemmings_check_' + str(attempt))
        for name in record_files[attempt]:
            copy_file(source / name, target / name)
        before = {name: read(target / name) for name in
                  ('probe/result.json', 'probe/adapter_receipt.json', 'trace_binding.json')}
        result = copy.deepcopy(before['probe/result.json'])
        projections = [dict(file='probe/result.json', field='outdir',
                            original=result['outdir'], projected=str(target / 'probe'))]
        result['outdir'] = str(target / 'probe')
        for index, stage in enumerate(result['stages']):
            new_path = str(target / 'probe' / (stage['name'] + '.log'))
            projections.append(dict(file='probe/result.json', field='stages.' + str(index) + '.log',
                                    original=stage['log'], projected=new_path))
            stage['log'] = new_path
        save(target / 'probe/result.json', result)
        adapter = dict(before['probe/adapter_receipt.json'], **result)
        adapter['inherited_result_path'] = str(target / 'probe/result.json')
        adapter['inherited_result_sha256'] = sha(target / 'probe/result.json')
        for name, key in (('probe_runner.py', 'inherited_runner'), ('paired_checkpoint.py', 'oracle_adapter')):
            adapter[key + '_path'] = str(dependencies / name)
        save(target / 'probe/adapter_receipt.json', adapter)
        trace = dict(before['trace_binding.json'], result_sha256=sha(target / 'probe/result.json'))
        save(target / 'trace_binding.json', trace)
        after = {name: read(target / name) for name in before}
        # Only path projections and the resulting copied-result digest change.
        restored = copy.deepcopy(result)
        restored['outdir'] = before['probe/result.json']['outdir']
        for index, stage in enumerate(restored['stages']):
            stage['log'] = before['probe/result.json']['stages'][index]['log']
        assert restored == before['probe/result.json']
        for name in record_files[attempt]:
            if name not in before:
                assert sha(target / name) == sha(source / name)
        rewrites.append(dict(simulated_path_projection_only=True, original=str(source), copy=str(target),
            native_source_evidence_sha256=native['records'][attempt]['native_evidence_sha256'],
            original_json=before, projected_json=after, result_path_projections=projections,
            adapter_path_fields=['inherited_result_path', 'inherited_runner_path', 'oracle_adapter_path'],
            recomputed_hash_fields=['probe/adapter_receipt.json:inherited_result_sha256',
                                    'trace_binding.json:result_sha256']))

    def make_case(name):
        case = out / name
        case.mkdir()
        for relative in seed_files:
            copy_file(seed / relative, case / relative)
        omit_native = name == 'reject_feedback_without_successful_lint'
        if not omit_native:
            for attempt in (0, 1):
                native_copy(case, attempt)
        save(case / 'SIMULATED_CONTROL.json', dict(simulated=True, not_an_actual_solver_run=True,
            retained_simulated_flow=str(seed), actual_native_result=str(native_path),
            actual_native_result_sha256=args.native_result_sha256,
            binding_inputs_sha256=args.binding_inputs_sha256,
            response_bytes_unchanged=True, omitted_native_copies_for_lint_regression=omit_native,
            new_model_calls=0, new_eda_calls=0,
            worker_reruns=0, native_reruns=0))
        return case

    def forbidden(*a, **k):
        raise RuntimeError('Binding controls forbid HTTP, workers, checker execution and EDA processes')

    save(out / 'INTENT.json', dict(simulated_controls=True, cases=list(CASES), case_count=8,
        original_packet=str(origin), run_spec_sha256=args.run_spec_sha256,
        pure_flow_result_sha256=args.pure_flow_result_sha256,
        actual_native_result_sha256=args.native_result_sha256,
        binding_inputs_sha256=args.binding_inputs_sha256, source_hashes=sources,
        new_model_max=0, new_eda_max=0, new_http_max=0, old_flow_reruns=0, native_reruns=0,
        exact_native_originals_required=True, score_measured=False))
    error = None
    try:
        sys.path.insert(0, str(root))
        with patch.object(urllib.request, 'urlopen', forbidden), \
             patch.object(socket, 'create_connection', forbidden), \
             patch.object(socket.socket, 'connect', forbidden), \
             patch.object(socket.socket, 'connect_ex', forbidden), \
             patch.object(subprocess, 'run', forbidden), patch.object(subprocess, 'Popen', forbidden):
            worker = load('lemmings_controls_model_binding', root / 'worker.py')
            binding = load('lemmings_controls_event_binding', root / 'lemmings_binding.py')
            assert Path(worker.baseline_worker.__file__).resolve() == root / 'baseline_worker.py'
            assert Path(binding.lemmings_feedback.__file__).resolve() == root / 'lemmings_feedback.py'
            # The two bind functions may parse/render/recompute retained events;
            # they must never enter any executable worker or checker hook.
            with patch.object(worker.baseline_worker, 'run_worker', forbidden), \
                 patch.object(binding.lemmings_feedback, 'run_worker', forbidden), \
                 patch.object(binding.lemmings_feedback, 'check', forbidden):
                for name in CASES:
                    case = make_case(name)
                    changed = []
                    if name == 'reject_trace_log_hash':
                        p = case / 'lemmings_check_0/trace_binding.json'
                        value = read(p); value['log_sha256'] = '0' * 64; save(p, value)
                        changed = [str(p.relative_to(case))]
                    elif name == 'reject_counterexample_event':
                        p = case / 'lemmings_check_0/counterexample.json'
                        value = read(p); value['event'] += 1; save(p, value)
                        changed = [str(p.relative_to(case))]
                    elif name in ('reject_log_event_semantics', 'reject_native_summary_mismatch'):
                        folder = case / 'lemmings_check_0'
                        p = folder / 'probe/xsim.log'
                        data = p.read_bytes()
                        if name == 'reject_log_event_semantics':
                            match = re.search(rb'(?m)^LEMMINGS_STEP event=\d+ kind=(async_assert|posedge|hold) clock=[01] ', data)
                            assert match is not None
                            replacement = b'hold' if match.group(1) != b'hold' else b'async_assert'
                        else:
                            matches = list(re.finditer(
                                rb'(?m)^R2_PROBE_RESULT task=\S+ checks=\d+ mismatches=(\d+)\s*$', data))
                            assert len(matches) == 1
                            match = matches[0]
                            replacement = str(int(match.group(1)) + 1).encode('ascii')
                        p.write_bytes(data[:match.start(1)] + replacement + data[match.end(1):])
                        result = read(folder / 'probe/result.json')
                        stage = result['stages'][2]
                        stage['log_sha256'], stage['log_bytes'] = sha(p), p.stat().st_size
                        save(folder / 'probe/result.json', result)
                        adapter = dict(read(folder / 'probe/adapter_receipt.json'), **result)
                        adapter['inherited_result_sha256'] = sha(folder / 'probe/result.json')
                        save(folder / 'probe/adapter_receipt.json', adapter)
                        trace = read(folder / 'trace_binding.json')
                        trace.update(log_sha256=sha(p), result_sha256=sha(folder / 'probe/result.json'))
                        save(folder / 'trace_binding.json', trace)
                        changed = ['lemmings_check_0/' + x for x in
                                   ('probe/xsim.log', 'probe/result.json', 'probe/adapter_receipt.json', 'trace_binding.json')]
                    elif name == 'reject_next_request_diagnostic':
                        marker = '\nSIMULATED_UNSUPPORTED_DIAGNOSTIC'
                        p = case / 'requests/1/request.json'
                        value = read(p); value['messages'][1]['content'] += marker; save(p, value)
                        receipts = read(case / 'requests.json')
                        receipts[1]['request_sha256'] = sha(p); save(case / 'requests.json', receipts)
                        p = case / 'trace.jsonl'
                        events = [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
                        selected = [e for e in events if e.get('tool') == 'map_feedback' and e.get('round') == 0]
                        assert len(selected) == 1
                        selected[0]['excerpt'] += marker
                        p.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
                        changed = ['requests/1/request.json', 'requests.json', 'trace.jsonl']
                    elif name == 'reject_missing_trace_binding':
                        p = case / 'lemmings_check_0/trace_binding.json'
                        assert p.resolve().is_relative_to(out)
                        p.unlink()
                        changed = [str(p.relative_to(case))]
                    elif name == 'reject_feedback_without_successful_lint':
                        p = case / 'trace.jsonl'
                        events = [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
                        for attempt in (0, 1):
                            lint = [e for e in events if e.get('tool') == 'lint' and e.get('round') == attempt]
                            assert len(lint) == 1 and lint[0]['rc'] == 0
                            lint[0]['rc'] = 1
                        assert len([e for e in events if e.get('tool') == 'map_feedback' and e.get('round') == 0]) == 1
                        assert not list(case.glob('lemmings_check_*'))
                        p.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
                        changed = ['trace.jsonl', 'lemmings_check_0 (omitted)', 'lemmings_check_1 (omitted)']
                    if changed:
                        mutations.append(dict(control=name, deliberately_tampered_derived_copy=True,
                            paths=changed, original_native_evidence_modified=False,
                            event_mutation_scope='kind only; event/clock/reset/inputs/outputs unchanged'
                            if name == 'reject_log_event_semantics' else None,
                            added_for_concrete_review_defect=name in CASES[-2:]))
                    # Every negative must pass the inherited model proof. New
                    # binding rejection cannot hide an old request-hash failure.
                    model = worker.bind(case, 'P')
                    assert model['actual_model_responses'] == 2 and not model['declaration_fix']
                    if name == CASES[0]:
                        result = binding.bind_lemmings(case, root)
                        assert result['applicable'] and result['counterexamples_consumed'] == 1
                        assert [r['status'] for r in result['actual_checks']] == ['fail', 'pass']
                        reports.append(dict(control=name, passed=True, simulated=True,
                            inherited_model_proof_passed=True, result=result,
                            generation_evidence_scope='retained synthetic replies only; not a real model run'))
                        continue
                    try:
                        binding.bind_lemmings(case, root)
                    except (AssertionError, RuntimeError, FileNotFoundError) as exc:
                        frames = traceback.extract_tb(exc.__traceback__)
                        site = frames[-1]
                        if name == 'reject_log_event_semantics':
                            assert isinstance(exc, RuntimeError)
                            assert str(exc) == 'Lemmings observations contradict the executed event trace'
                        if name == 'reject_missing_trace_binding':
                            assert isinstance(exc, FileNotFoundError)
                            assert Path(exc.filename) == case / 'lemmings_check_0/trace_binding.json'
                        if name == 'reject_native_summary_mismatch':
                            assert isinstance(exc, AssertionError)
                            assert str(exc) == 'Native summary contradicts retained result'
                        if name == 'reject_feedback_without_successful_lint':
                            assert isinstance(exc, AssertionError)
                            assert Path(site.filename).resolve() == root / 'lemmings_binding.py'
                            assert site.name == 'bind_lemmings' and site.line.strip() == 'assert not events'
                        reports.append(dict(control=name, passed=True, simulated=True,
                            inherited_model_proof_passed=True, rejected_by='lemmings_binding.bind_lemmings',
                            error_type=type(exc).__name__, error_message=str(exc),
                            rejection_site=dict(file=site.filename, line=site.lineno,
                                                function=site.name, source=site.line)))
                    else:
                        raise AssertionError('Tampered derived evidence accepted: ' + name)
        assert len(reports) == 8 and [r['control'] for r in reports] == list(CASES)
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    source_unchanged = (sha(spec_path) == args.run_spec_sha256 and
                        all(sha(root / name) == digest for name, digest in sources.items()) and
                        all(sha(path) == digest for path, digest in dependency_hashes.items()))
    originals_unchanged = all(sha(path) == digest for path, digest in originals.items())
    if not (source_unchanged and originals_unchanged) and error is None:
        error = dict(type='EvidenceDrift', message='Frozen source or original evidence bytes changed')
    save(out / 'SIMULATED_PATH_REWRITES.json', rewrites)
    save(out / 'SIMULATED_TAMPERS.json', mutations)
    save(out / 'RESULT.json', dict(complete=True, passed=error is None, simulated_controls=True,
        reports=reports, error=error, expected_cases=8, completed_cases=len(reports),
        new_model_calls=0, new_eda_calls=0, new_http_calls=0, old_flow_reruns=0, native_reruns=0,
        score_measured=False, actual_model_generation_proven=False,
        source_hashes=sources, dependency_hashes=dependency_hashes,
        original_evidence_sha256=originals, sources_unchanged=source_unchanged,
        originals_unchanged=originals_unchanged,
        pure_flow_result_sha256=args.pure_flow_result_sha256,
        actual_native_result_sha256=args.native_result_sha256,
        binding_inputs_sha256=args.binding_inputs_sha256))
    return 0 if error is None else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'original-packet-root', 'pure-flow-result', 'native-result', 'binding-inputs', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('run-spec-sha256', 'pure-flow-result-sha256', 'native-result-sha256', 'binding-inputs-sha256'):
        parser.add_argument('--' + name, required=True)
    sys.exit(run(parser.parse_args()))
