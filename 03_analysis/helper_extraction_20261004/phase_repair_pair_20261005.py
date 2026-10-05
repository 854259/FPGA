"""AMD-only conditional repair comparison; two known checkpoints, not a full batch.

One frozen original first reply per task; five fixed repetitions of each feedback arm.
Runtime, skills, extraction, compiler and original one-repair limit are unchanged.
Official reference assets are accessed only by separate post-generation judge processes.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
MODEL = 'Qwen3.6-27B-Q4_K_M'
TASKS = ['Prob045_edgedetect2', 'Prob054_edgedetect']
ORIGINAL_SPEC_SHA = 'bce903e984fd0f1b92bd11759b0ecc3bdf77783f384bca74cde0b9cf09beacf6'
T7_SUMMARY_SHA = '66594a1932c19ce89591263fb713e5e40d5637d127446d558116149d45bd62e7'
WORKER_SHA = 'fbb169961519f92dd48b64e9a8e0d3f8c0ae5242eeca55701d35873e7c7b1aa2'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, data):
    p = Path(p)
    pending = p.with_name(p.name + '.pending')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    pending.replace(p)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_worker(original):
    """Mechanical harness edits only; the actual runtime remains byte-identical."""
    def replace(old, new):
        nonlocal original
        assert original.count(old) == 1, old
        original = original.replace(old, new)
    replace('import edge_feedback\n', 'import edge_feedback\nimport phase_context\n')
    replace('    parser = edge_dispatch if candidate else prompt_map\n    renderer = edge_feedback if candidate else point_feedback',
            '    parser = edge_dispatch\n    renderer = edge_feedback')
    replace("    tb.write_text(parser.render_tb(contract, task), encoding='utf-8', newline='\\n')",
            "    original_tb = parser.render_tb(contract, task)\n"
            "    text = phase_context.instrument_tb(original_tb, contract) if candidate and contract.get('family') == 'edge' else original_tb\n"
            "    tb.write_text(text, encoding='utf-8', newline='\\n')")
    replace('    feedback = renderer.render(contract, result, point)',
            "    feedback = renderer.render(contract, result, point)\n"
            "    if candidate and contract.get('family') == 'edge':\n"
            "        import edge_contract\n"
            "        rows, bound = phase_context.context((folder/'probe/xsim.log').read_text(), contract, edge_contract)\n"
            "        enriched = phase_context.render_feedback(contract, bound, edge_feedback)\n"
            "        assert enriched.startswith(feedback + ' Related observations')\n"
            "        save(folder/'phase_context.json', dict(rows=rows, bound=bound, original_feedback=feedback))\n"
            "        feedback = enriched")
    begin = original.index('        entry = dict(index=index, replayed=False,')
    end = original.index('\n    def compiler(', begin)
    original = original[:begin] + '''        replayed = index == 0 or args.replay_all
        entry = dict(index=index, replayed=replayed, response_received=False,
                     request_sha256=sha(folder/'request.json'), actual_post_attempted=False)
        requests.append(entry); save(out/'requests.json', requests)
        expected = json.loads((args.replay_dir/str(index)/'request.json').read_text())
        if index == 0:
            assert body == expected, 'Frozen first request changed'
        else:
            assert body['messages'][0] == expected['messages'][0]
            assert all(body[k] == expected[k] for k in ('model','temperature','top_p','max_tokens'))
            before = expected['messages'][1]['content']
            after = body['messages'][1]['content']
            assert after == before if args.arm == 'S' else after.startswith(before + ' Related observations')
        tick = time.monotonic()
        if replayed:
            raw = (args.replay_dir/str(index)/'response.json').read_bytes()
        else:
            gate(); paired.model_idle('http://127.0.0.1:8000/v1', spec['model'])
            remaining = 300 - (time.monotonic() - started) - 25
            assert remaining > 0, 'No remaining worker budget for request'
            entry.update(actual_post_attempted=True, started_epoch=time.time(), timeout_s=remaining)
            save(out/'requests.json', requests)
            try:
                kwargs['timeout'] = min(float(kwargs.get('timeout',300)), remaining)
                with original_open(request, *positional, **kwargs) as response: raw=response.read()
            except Exception as error:
                entry.update(error=type(error).__name__, elapsed_s=time.monotonic()-tick)
                save(out/'requests.json', requests)
                raise RuntimeError('Actual repair unconfirmed; no retry') from error
        (folder/'response.json').write_bytes(raw)
        payload=json.loads(raw); choice=payload['choices'][0]
        entry.update(response_received=True, response_sha256=sha(folder/'response.json'),
                     elapsed_s=time.monotonic()-tick, finish_reason=choice.get('finish_reason'), usage=payload.get('usage'))
        save(out/'requests.json', requests)
        return io.BytesIO(raw)
''' + original[end:]
    replace("candidate=args.arm == 'E'", "candidate=args.arm == 'P'")
    replace('actual_model_requests=len(requests),',
            "actual_model_requests=sum(r['actual_post_attempted'] for r in requests), first_generation_replayed=True,")
    replace("choices=['A','C','E']", "choices=['S','P']")
    replace('    args = p.parse_args()',
            "    p.add_argument('--replay-dir',type=Path,required=True)\n"
            "    p.add_argument('--replay-all',action='store_true')\n"
            '    args = p.parse_args()')
    return original


def prepare(a):
    assert sys.platform == 'linux'
    original, root = a.original, a.out
    assert sha(original/'RUN_SPEC.json') == ORIGINAL_SPEC_SHA
    assert sha(a.t7/'results/summary.json') == T7_SUMMARY_SHA
    t7 = json.loads((a.t7/'results/summary.json').read_text())
    assert t7['complete'] and t7['invalid_trace_rejections'] == 96
    assert json.loads((a.t7/'guard/status.json').read_text())['passed']
    old = json.loads((original/'RUN_SPEC.json').read_text())
    assert sha(original/'worker.py') == WORKER_SHA
    for name, digest in old['source_hashes'].items(): assert sha(original/name) == digest, name
    root.mkdir(parents=True, exist_ok=False)
    files = ['edge_contract.py','edge_dispatch.py','edge_feedback.py','point_feedback.py',
             'prompt_map.py','priority_contract.py','shift_contract.py','reserved_keywords.py',
             'official_eval_guarded.py','package/agent/map_runtime.py','package/agent/runtime.py',
             'package/baseline.py','package/skill/rtl-generation/SKILL.md',
             'package/skill/rtl-feedback-repair/SKILL.md']
    for name in files:
        dest = root/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original/name, dest)
    shutil.copyfile(Path(__file__), root/'phase_repair_pair_20261005.py')
    phase = HERE/'edge_phase_context_20261005.py'
    t7_phase = a.t7/'source/03_analysis/helper_extraction_20261004/edge_phase_context_20261005.py'
    assert sha(phase) == sha(t7_phase)
    shutil.copyfile(phase, root/'phase_context.py')
    (root/'worker.py').write_text(patched_worker((original/'worker.py').read_text()))
    input_manifest = json.loads((original/'INPUT_MANIFEST.json').read_text())
    save(root/'INPUT_MANIFEST.json', input_manifest)
    for task in TASKS:
        src = original/'results/samples/E'/task/'worker'
        for index in ('0','1'):
            for name in ('request.json','response.json'):
                target = root/'replay'/task/index/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src/'requests'/index/name,target)
        # Bind the original outputs and native evidence for the integration replay audit.
        for name in ('solution.v','map_check_0/feedback.json','map_check_0/probe/result.json'):
            target=root/'replay'/task/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src/name,target)
    order=[]
    for repeat in range(5):
        for index,task in enumerate(TASKS):
            for arm in (['S','P'] if (repeat+index)%2==0 else ['P','S']):
                order.append(dict(task=task,repeat=repeat,arm=arm))
    spec=dict(schema='phase_conditional_repair_v1',identity=root.name,model=MODEL,
        source_commit=a.source_commit,task_ids=TASKS,order=order,expected_samples=20,
        max_actual_model_requests=20,stage_timeout_s=3600,solve_deadline_s=300,
        judge_timeout_s=150,judge_supervisor_timeout_s=180,retries=0,
        dependencies_cloud=old['dependencies_cloud'],dependency_hashes=old['dependency_hashes'],
        original_spec_sha256=ORIGINAL_SPEC_SHA,t7_summary_sha256=T7_SUMMARY_SHA,
        source_hashes={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()},
        first_generation_replayed=True,independent_tasks=0,full_batch_complete=False,
        scope='Two known development checkpoints, five conditional repair repetitions per arm; not five independent full solves.',
        acceptance='All20 complete, no environment/call/binding errors, P native+official L3 at least S for each task, total strictly greater; no adoption or generalization even if met.',
        stop='Stop only on integrity/environment/ownership/time/call budget failure; never stop on intermediate scores or resample.')
    save(root/'RUN_SPEC.json',spec)
    print(json.dumps(dict(prepared=True,root=str(root),spec_sha256=sha(root/'RUN_SPEC.json'),files=len(spec['source_hashes']))))


def frozen(root,kit):
    spec=json.loads((root/'RUN_SPEC.json').read_text())
    for name,digest in spec['source_hashes'].items(): assert sha(root/name)==digest,name
    for name,digest in spec['dependency_hashes'].items(): assert sha(Path(spec['dependencies_cloud'])/name)==digest,name
    manifest=json.loads((root/'INPUT_MANIFEST.json').read_text())
    for name,digest in manifest['input_sha256'].items(): assert sha(kit/'bench/tasks_veval'/name)==digest,name
    for name,digest in manifest['official_sha256'].items(): assert sha(kit/'official_reference'/name)==digest,name
    return spec


def judge(a):
    spec=frozen(HERE,a.kit);a.out.mkdir(parents=True,exist_ok=False)
    evaluator=load('phase_external_judge',HERE/'official_eval_guarded.py')
    evaluator.OFFICIAL=a.kit/'official_reference'
    result=evaluator.judge_sample(a.kit/'bench/tasks_veval'/a.task,a.solution,a.out,a.out/'verdict.json',spec['judge_timeout_s'])
    assert not result.get('tool_error') and result['judge_evidence_complete'] and result['task_id']==a.task
    save(a.out/'bound_verdict.json',dict(solution_sha256=sha(a.solution),verdict=result))


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    root=HERE;spec=frozen(root,a.kit)
    assert spec['expected_samples']==spec['max_actual_model_requests']==20
    tools=Path('/workspace/AMD/2026.1/Vivado/bin')
    stub=Path('/workspace/team/udev-stub')
    assert sha(stub/'libudev.so.1')=='3a2d6266ccf18909d3ebccbf21e8125ce985359319fecc6c8172aeabf13ecf87'
    os.environ.update(MODEL_NAME=MODEL,LLM_BASE_URL='http://127.0.0.1:8000/v1',RTL_REPAIRS='1',
        RTL_TEMPERATURE='0',RTL_MAX_TOKENS='8192',VIVADO_BIN=str(tools),LD_LIBRARY_PATH=str(stub),
        PATH=str(tools)+os.pathsep+os.environ['PATH'],PYTHONDONTWRITEBYTECODE='1')
    for tool in ('xvlog','xelab','xsim','vivado'): assert Path(shutil.which(tool)).resolve()==(tools/tool).resolve()
    paired=load('phase_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.check_resource(a.resource_check,a.kit,first=True)
    out=root/'results';out.mkdir(exist_ok=False);tick=time.monotonic()
    report=dict(complete=False,valid=False,rows=[],controls=[],actual_model_requests=0,received_model_responses=0,
        error=None,independent_tasks=0,full_batch_complete=False,adopted=False,spec_sha256=sha(root/'RUN_SPEC.json'))
    def publish(phase):
        journals=list(out.rglob('requests.json'))
        entries=[r for p in journals for r in json.loads(p.read_text()) if r.get('actual_post_attempted')]
        report.update(phase=phase,elapsed_s=time.monotonic()-tick,actual_model_requests=len(entries),
                      received_model_responses=sum(r['response_received'] for r in entries))
        save(out/'summary.json',report)
        print(json.dumps({k:report[k] for k in ('phase','elapsed_s','actual_model_requests','received_model_responses')},ensure_ascii=False),flush=True)
    def gate():
        frozen(root,a.kit);paired.check_resource(a.resource_check,a.kit)
        assert time.monotonic()-tick < 3540,'Stage time budget exhausted'
    def command(argv,folder,log,limit):
        gate();assert 3600-(time.monotonic()-tick)>limit+30,'Insufficient stage budget for next operation'
        r=paired.owned_command(argv,folder,log,limit);save(log.with_suffix('.receipt.json'),dict(argv=argv,**r))
        assert r['returncode']==0 and not r['timeout'] and not r['launch_error'] and not r['remaining_live_group'],'Owned operation failed; preserve and inspect'
        return r
    def execute(task,arm,folder,replay_all):
        folder.mkdir(parents=True,exist_ok=False)
        argv=[sys.executable,'-B',str(root/'worker.py'),'--task',task,'--arm',arm,'--out',str(folder/'worker'),
              '--kit',str(a.kit),'--resource-check',str(a.resource_check),'--replay-dir',str(root/'replay'/task)]
        if replay_all: argv.append('--replay-all')
        result=command(argv,root,folder/'worker.log',300)
        worker=folder/'worker';journal=json.loads((worker/'requests.json').read_text())
        assert len(journal)==2 and journal[0]['replayed'] and all(r['response_received'] for r in journal)
        assert sum(r['actual_post_attempted'] for r in journal)==(0 if replay_all else 1)
        baseline=json.loads((root/'replay'/task/'map_check_0/probe/result.json').read_text())
        first=json.loads((worker/'map_check_0/probe/result.json').read_text())
        assert (first['checks'],first['mismatches'])==(baseline['checks'],baseline['mismatches'])
        old=json.loads((root/'replay'/task/'map_check_0/feedback.json').read_text())['text']
        new=json.loads((worker/'map_check_0/feedback.json').read_text())['text']
        assert new==old if arm=='S' else new.startswith(old+' Related observations')
        if replay_all: assert sha(worker/'solution.v')==sha(root/'replay'/task/'solution.v')
        # Bind the final native probe, if produced, to the exact final source.
        native=worker/'map_check_1/probe/result.json';native_pass=False
        if native.exists():
            assert sha(worker/'map_check_1/input.sv')==sha(worker/'solution.v')
            nr=json.loads(native.read_text());native_pass=nr['status']=='pass' and nr['mismatches']==0
        paired.model_idle('http://127.0.0.1:8000/v1',MODEL)
        return dict(task=task,arm=arm,solve_elapsed_s=result['elapsed_s'],solution_sha256=sha(worker/'solution.v'),
                    native_pass=native_pass,actual_model_requests=sum(r['actual_post_attempted'] for r in journal))
    try:
        publish('integration_replay')
        for task in TASKS:
            for arm in ('S','P'):
                row=execute(task,arm,out/'controls'/task/arm,True)
                report['controls'].append(row);publish('integration_replay')
        assert len(report['controls'])==4 and report['actual_model_requests']==0
        save(out/'INTEGRATION_GATE.json',dict(passed=True,actual_model_calls=0,controls=report['controls']))
        for item in spec['order']:
            publish('conditional_repair')
            assert report['actual_model_requests']<20
            folder=out/'samples'/('r'+str(item['repeat']))/item['task']/item['arm']
            row=execute(item['task'],item['arm'],folder,False)
            row['repeat']=item['repeat']
            argv=[sys.executable,'-B',str(Path(__file__)),'judge','--task',item['task'],
                  '--solution',str(folder/'worker/solution.v'),'--out',str(folder/'judge'),'--kit',str(a.kit)]
            receipt=command(argv,root,folder/'judge.log',180)
            bound=json.loads((folder/'judge/bound_verdict.json').read_text());assert bound['solution_sha256']==row['solution_sha256']
            row.update(verdict=bound['verdict'],judge_elapsed_s=receipt['elapsed_s'])
            save(folder/'row.json',row);report['rows'].append(row);publish('conditional_repair')
        assert len(report['rows'])==20 and report['actual_model_requests']==report['received_model_responses']==20
        gate();report.update(complete=True,valid=True)
        # Leave quality promotion to a separate raw provenance audit, never a progress score.
        report['next']='Audit all20 request/response/compiler/native/judge chains before reporting repair benefit; no adoption.'
    except BaseException as e:
        report['error']=type(e).__name__+': '+str(e)
    finally:
        publish('completed' if report['complete'] else 'failed')
    return 0 if report['valid'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','judge'])
    for n in ('original','out','t7','kit','resource-check','solution'): p.add_argument('--'+n,type=Path)
    p.add_argument('--source-commit');p.add_argument('--task');a=p.parse_args()
    if a.action=='prepare': prepare(a)
    elif a.action=='judge': judge(a)
    else: raise SystemExit(run(a))
