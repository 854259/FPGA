"""Read-only source, recipe, request/reply and native generation bindings.
This module does not grade or admit a run. Full source/archive/guard/qualification
checks belong to the scoring entry and original complete archive audit.
"""
import hashlib,importlib.util,json,re
from pathlib import Path,PurePosixPath

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
digest=lambda text:hashlib.sha256(text.encode()).hexdigest()

def read(path):
    def unique(pairs):
        result={}
        for key,value in pairs:
            assert key not in result, 'Duplicate JSON key'
            result[key]=value
        return result
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique)

PINNED={
 'baseline_worker.py':'7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742',
 'worker.py':'19f0aaf87f609dcbfee155f3516a8037dd09b67dc277676ac8bdf640521bab91',
 'selector.py':'9ef0c99f24c90e396d7d31a66357ac7bdf3c1f097fcaa321641ed44d20f4d116',
 'onehot_producer.py':'fc1af52cd3d76faf9eed812167eb8179ab40b3c3d32740062e6d444459701007',
 'timer_producer.py':'9080c49a93c807a4e5291e729d0b3ccb85b8d78c680607510ebcec7192fa26d6',
 'reserved_keywords.py':'3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e',
 'package/agent/map_runtime.py':'2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'}

def bound_route(work,run,arm,prompt,interface,interface_present,selection_module,providers):
    work,run=Path(work),Path(run)
    assert arm in ('C','P') and type(interface_present) is bool
    assert type(prompt) is str and type(interface) is str
    assert interface_present or interface==''
    assert all(sha(run/name)==value for name,value in PINNED.items())
    assert Path(selection_module.__file__).resolve()==(run/'selector.py').resolve()
    assert [name for name,module in providers]==['onehot','timer']
    for name,module in providers:
        assert Path(module.__file__).resolve()==(run/(name+'_producer.py')).resolve()
    expected_inputs={'prompt.txt'}|({'interface.txt'} if interface_present else set())
    assert {p.name for p in (work/'prompt_only').iterdir()}==expected_inputs
    assert (work/'prompt_only/prompt.txt').read_bytes()==prompt.encode()
    if interface_present:assert (work/'prompt_only/interface.txt').read_bytes()==interface.encode()
    selection=selection_module.select(prompt,interface,[(name,module.synthesize) for name,module in providers]) if arm=='P' else None
    recipe=selection['recipe'] if selection is not None else None
    selected=selection['selected_provider'] if selection is not None else None
    emitted=recipe is not None
    tag='mechanical_'+selected if emitted else 'model'
    expected=dict(schema='history_recipe_generation_route_v1',route=tag,outer_arm=arm,
        prompt_sha256=digest(prompt),interface_sha256=digest(interface),interface_present=interface_present,
        baseline_worker_sha256=sha(run/'baseline_worker.py'),
        synthesis_source_sha256=sha(run/(selected+'_producer.py')) if emitted else None,
        selector_source_sha256=sha(run/'selector.py'),
        provider_source_hashes={name:sha(run/(name+'_producer.py')) for name,module in providers},
        selected_provider=selected,
        selection_sha256=digest(json.dumps(selection,sort_keys=True,separators=(',',':'))) if selection is not None else None,
        generated_solution_sha256=recipe['rtl_sha256'] if emitted else None)
    assert read(work/'generation_route.json')==expected
    if arm=='P':assert read(work/'generation_selection.json')==selection
    else:assert not (work/'generation_selection.json').exists()
    if emitted:assert read(work/'synthesis_receipt.json')==recipe
    else:assert not (work/'synthesis_receipt.json').exists()
    assert not any((work/n).exists() for n in ['internal_declaration_journal.json','first_request_receipts','waveform_request_receipts'])
    if not emitted:assert not (work/'emission').exists() and not (work/'native_receipts').exists()
    return expected,recipe

def model_requests(work, row, spec, generation, repair):
    journal = read(work/'requests.json')
    assert 1 <= len(journal) <= 2
    assert row['actual_model_requests'] == len(journal)
    assert row['received_model_responses'] == sum(e['response_received'] for e in journal)
    expected_files = set()
    trace = [json.loads(line) for line in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert trace and trace[0]['tool'] == 'agent_meta' and trace[0]['repairs'] == 1
    assert trace[0]['skill_sha256'] == hashlib.sha256(generation.encode()).hexdigest()
    assert trace[0]['repair_skill_sha256'] == hashlib.sha256(repair.encode()).hexdigest()
    assert [e['round'] for e in trace if e['tool'] == 'llm_start'] == list(range(len(journal)))
    assert not any(e.get('error') or e.get('tool') in ('onehot_generation','history_recipe_generation') for e in trace)
    first_body = None
    for index, entry in enumerate(journal):
        folder = work/'requests'/str(index); request = folder/'request.json'
        expected_files.add(request)
        assert type(entry['index']) is int and entry['index'] == index and entry['replayed'] is False
        assert type(entry['response_received']) is bool
        assert entry['request_sha256'] == sha(request)
        body = read(request)
        assert set(body) == {'model','messages','temperature','top_p','max_tokens'}
        assert body['model'] == spec['model'] and type(body['max_tokens']) is int and body['max_tokens'] == 8192
        assert type(body['temperature']) in (int,float) and body['temperature'] == 0
        assert type(body['top_p']) in (int,float) and body['top_p'] == 1 and len(body['messages']) == 2
        assert body['messages'][0] == dict(role='system',content=generation+('\n'+repair if index else ''))
        if index == 0: first_body = body
        if entry['response_received']:
            response = folder/'response.json'; expected_files.add(response)
            assert entry['response_sha256'] == sha(response)
            payload = read(response); choice = payload['choices'][0]; usage = payload.get('usage') or {}
            assert entry['finish_reason'] == choice.get('finish_reason') and entry['response_id'] == payload.get('id')
            assert entry.get('usage') == payload.get('usage')
            events = [e for e in trace if e['tool'] == 'llm' and e['round'] == index]
            assert len(events) == 1 and events[0]['finish'] == choice.get('finish_reason')
            assert events[0]['tokens_in'] == usage.get('prompt_tokens') and events[0]['tokens_out'] == usage.get('completion_tokens')
    assert {p for p in (work/'requests').rglob('*') if p.is_file()} == expected_files
    assert set(work.rglob('response.json')) == {p for p in expected_files if p.name == 'response.json'}
    return journal, first_body


def mechanical_provenance(work, run, task, row, result, cloud_work, runner, parser, verify_probe):
    assert row['arm'] == 'P' and not row['solve_deadline_reached']
    assert read(work/'requests.json') == [] and row['actual_model_requests'] == row['received_model_responses'] == 0
    assert not (work/'requests').exists() and not list(work.rglob('request.json')) and not list(work.rglob('response.json'))
    assert not (work/'compile_journal.json').exists() and not (work/'compile_receipts').exists()
    code = result['rtl'].encode('utf-8')
    assert (work/'solution.v').read_bytes() == (work/'emission/emitted.sv').read_bytes() == code
    raw_prompt = (work/'prompt_only/prompt.txt').read_bytes().decode('utf-8')
    contract = read(work/'emission/contract.json')
    assert contract == result['contract']
    assert hashlib.sha256(json.dumps(contract,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()).hexdigest() == result['contract_sha256']
    folder = work/'native_receipts/0'; physical = read(folder/'command.json')
    assert not any(physical.get(key) for key in ('simulated','fixture','mock','synthetic')), 'Mock native receipt cannot authorize scoring'
    assert {p.name for p in (work/'native_receipts').iterdir()} == {'0'}
    assert {p.name for p in folder.iterdir()} == {'command.json','source_before.sv','source_after.sv','owned_compile.log'}
    for name in ('source_before.sv','source_after.sv'):
        assert (folder/name).read_bytes() == code
    log = folder/'owned_compile.log'; stdout = log.read_text(encoding='utf-8',errors='replace')
    assert physical['source_sha256'] == physical['source_before_sha256'] == physical['source_after_sha256'] == result['rtl_sha256'] == sha(work/'solution.v')
    assert physical['argv'] == ['/workspace/AMD/2026.1/Vivado/bin/xvlog','--sv',str(cloud_work/'work/mechanical_compile-0/candidate.sv')]
    assert (work/'work/mechanical_compile-0/candidate.sv').read_bytes() == code
    assert not physical['timeout'] and not physical['launch_error'] and not physical['remaining_live_group']
    assert type(physical['returncode']) is int and physical['returncode'] >= 0
    assert physical['log_sha256'] == sha(log) and physical['log_bytes'] == log.stat().st_size
    assert not runner.ENVIRONMENT_ERROR.search(stdout)
    # A compiler may legitimately reject source. A zero-return fatal/error log
    # cannot become clean native execution merely through its return code.
    assert physical['returncode'] != 0 or not re.search(r'(?im)^\s*(?:fatal|error)\s*[:\[]',stdout)
    excerpt = '\n'.join(line for line in stdout.splitlines() if re.search('ERROR|WARNING|FATAL',line))[:2048] or stdout[-2048:]
    trace = [json.loads(line) for line in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [event['tool'] for event in trace] == ['history_recipe_generation','lint_start','lint','native_feedback']
    assert all(event['round'] == 0 and not event.get('error') for event in trace)
    assert trace[0]['route'] == 'mechanical_' + row['selected_provider'] and trace[0]['actual_model_requests'] == 0
    assert trace[0]['emitted_sha256'] == result['rtl_sha256'] and trace[0]['contract_sha256'] == result['contract_sha256']
    assert trace[2]['rc'] == physical['returncode'] and trace[2]['excerpt'] == excerpt
    assert trace[2]['receipt_sha256'] == sha(folder/'command.json')
    feedback = read(work/'native_feedback.json')
    assert feedback['repair_requested'] is False and feedback['native_compile_returncode'] == physical['returncode']
    prompt = (work/'prompt_only/prompt.txt').read_text(encoding='utf-8')
    iface = work/'prompt_only/interface.txt'
    if iface.exists() and iface.read_text(encoding='utf-8').strip(): prompt += '\n\nInterface:\n'+iface.read_text(encoding='utf-8')
    common = parser.parse(prompt); check = work/'map_check_0'
    expected = ''
    if physical['returncode'] == 0 and common['status'] == 'supported' and not re.search(r'\$[A-Za-z_]|`include',result['rtl']):
        assert read(check/'contract.json') == common and (check/'input.sv').read_bytes() == code
        raw = verify_probe(check,common)
        if raw['mismatches']: expected = read(check/'feedback.json')['text']
    else: assert not check.exists()
    assert feedback['text'] == expected
    assert trace[3]['text'] == trace[3]['excerpt'] == expected and trace[3]['repair_requested'] is False
    assert trace[1]['generation_route'] == trace[2]['generation_route'] == trace[3]['generation_route'] == 'mechanical_' + row['selected_provider']
    wr = read(work/'worker_result.json')
    assert wr['complete'] and wr['arm'] == 'P' and wr['generation_route'] == 'mechanical_' + row['selected_provider']
    assert wr['requests'] == wr['actual_model_requests'] == wr['received_model_responses'] == 0
    assert wr['solution_sha256'] == sha(work/'solution.v')
    return dict(first_reply_sha256=None,declaration_patches=0,original_repair_feedback_bound=False,
                mechanical_recipe_bound=True,empty_model_artifacts_bound=True,
                first_pair_applicability='not_applicable_mechanical',native_execution_bound=True)


def verify(work,run,source,arm,row,cloud_work,spec,modules,verify_probe):
    """Bind one completed generation; cannot prove complete-run grading/adoption."""
    selection,providers,replay,baseline,runtime,parser,feedback,runner=modules
    work,run,source=Path(work),Path(run),Path(source)
    prompt=(source/'prompt.txt').read_bytes().decode()
    present=(source/'interface.txt').exists()
    interface=(source/'interface.txt').read_bytes().decode() if present else ''
    route,recipe=bound_route(work,run,arm,prompt,interface,present,selection,providers)
    assert row['arm']==arm and row['generation_route']==route['route']
    assert row['selected_provider']==route['selected_provider']
    if recipe is not None:
        proof=mechanical_provenance(work,run,row['task'],row,recipe,Path(cloud_work),runner,parser,verify_probe)
    else:
        generation=(run/'package/skill/rtl-generation/SKILL.md').read_text()
        repair=(run/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
        journal,first=model_requests(work,row,spec,generation,repair)
        combined=prompt.replace('\r\n','\n').replace('\r','\n')
        normalized=interface.replace('\r\n','\n').replace('\r','\n')
        if present and normalized.strip():combined+='\n\nInterface:\n'+normalized
        contract=parser.parse(combined)
        for item in read(work/'compile_journal.json') if (work/'compile_journal.json').exists() else []:
            assert not any(item.get(k) for k in ['simulated','fixture','mock','synthetic'])
            assert item['argv'][0]=='/workspace/AMD/2026.1/Vivado/bin/xvlog'
            parent=PurePosixPath(item['argv'][-1]).parent.name
            assert parent in ['compile-0','compile-1']
            assert item['argv'][-1]==str(PurePosixPath(cloud_work)/'work'/parent/'candidate.sv')
        proof=replay.replay(work,combined,arm,contract,baseline,runtime,parser,feedback,verify_probe,sha,read,row['solve_deadline_reached'])
        if not row['solve_deadline_reached']:
            result=read(work/'worker_result.json')
            assert result['complete'] is True and result['arm']==arm and result['generation_route']=='model'
            assert type(result['requests']) is type(result['actual_model_requests']) is int
            assert result['requests']==result['actual_model_requests']==len(journal)
            assert result['solution_sha256']==sha(work/'solution.v')
        proof.update(original_model_replay_bound=True,native_execution_bound=True)
    proof.update(generation_route_bound=True,input_bytes_bound=True,source_hashes_bound=True,
                 selection_receipt_bound=True,selected_provider=route['selected_provider'],
                 generation_route=route['route'],solution_bytes_bound=True,
                 complete_archive_or_grade_verified=False)
    return proof
