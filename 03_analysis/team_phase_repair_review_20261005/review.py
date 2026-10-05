"""Read-only T7/T8 archives. Evaluate pinned pure formatting functions only."""
import ast,hashlib,importlib.util,json,re,tempfile,types,zipfile
from pathlib import Path,PurePosixPath
R=Path(__file__).resolve().parent
OWNER=R.parent/'edge_feedback_pilot_20261005'
PINS={45:'ee0110706360286d58587e85a831dca4567f4c45f5203f2377354006b6b91383',46:'b74d09963f9a5e82e9d34a0736194d2bcba74aeda23a8ba49ab6b5208e455a9d',47:'1744eb17b45800fb57d52235d0bb4e4f25c56c866e9c4eb2df0cc327aaf91545'}
def sha(b):return hashlib.sha256(b).hexdigest()
def read(z,n):return json.loads(z.read(n))
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def verified(number):
    p=R/'raw_evidence'/f'{number}_EVIDENCE.zip';assert sha(p.read_bytes())==PINS[number]
    z=zipfile.ZipFile(p);m=read(z,'EVIDENCE_MANIFEST.json')['files']
    assert len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(m)|{'EVIDENCE_MANIFEST.json'}
    for n,h in m.items():
        assert not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n and sha(z.read(n))==h,n
    return z,m
def pure_phase(raw):
    assert sha(raw)=='90b7c71b480a7cdd9d485e7401509feef996520111e76c03666ac519a2d01afa'
    names=['instrument_tb','context','render_feedback','prompt','design'];tree=ast.parse(raw.decode())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names];assert len(functions)==5
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal)) for f in functions for n in ast.walk(f))
    assert not any(isinstance(n,ast.Name) and n.id in ['open','eval','exec','compile','__import__','subprocess','os','Path'] for f in functions for n in ast.walk(f))
    env={'re':re};exec(compile(ast.Module(body=functions,type_ignores=[]),'pinned_pure_phase','exec'),env)
    return types.SimpleNamespace(**{n:env[n] for n in names})
def original_judge(z,prefix,solution,task):
    bound=read(z,prefix+'bound_verdict.json');v=read(z,prefix+'verdict.json');receipt=read(z,prefix+'judge_receipt.json');logs=prefix+'judge_work_logs/'
    assert receipt['judge_rc']==0 and receipt['errors']==[] and receipt['scratch_retained'] is None
    for n,h in receipt['evidence'].items():
        b=z.read(logs+n);assert sha(b)==h['sha256'] and len(b)==h['bytes']
    raw=read(z,logs+'adapter_verdict.json');assert all(v.get(k)==value for k,value in raw.items())
    assert bound['verdict']==v and bound['solution_sha256']==sha(solution)
    level=v['level'];assert type(level) is int and v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[level] and v['task_id']==task and not v.get('tool_error') and v['judge_evidence_complete']
    stages=v['stages'];assert bool(stages.get('compile'))==(level>=1) and bool(stages.get('simulate'))==(level>=2) and bool(stages.get('synth'))==(level>=3)
    assert z.read(logs+'dut.sv')==solution and len(z.read(logs+'w_judge.log'))>0
    kept=[n for n in receipt['evidence'] if n not in ['adapter.stdout.log','adapter.stderr.log','adapter_verdict.json']]
    assert v['judge_evidence']==kept and v['judge_log_bytes']==sum(receipt['evidence'][n]['bytes'] for n in kept if n.endswith('.log'))
    return v
def run():
    import sys;sys.path.insert(0,str(OWNER))
    import edge_contract,edge_feedback,edge_dispatch
    zs={};manifests={}
    for number in [45,46,47]:zs[number],manifests[number]=verified(number)
    z7,z8,za=zs[45],zs[46],zs[47];plan=read(z7,'PLAN.json');spec=read(z8,'RUN_SPEC.json')
    assert sha(z8.read('RUN_SPEC.json'))=='86ac7739c5fa6d6084af42c299fb5625690c08ddc6901c7f132313e260425890'
    for n,h in spec['source_hashes'].items():assert sha(z8.read(n))==h,n
    for n,h in plan['original_hashes'].items():assert sha(z7.read('original/'+n))==h==sha((OWNER/n).read_bytes())
    assert sha(z8.read('phase_context.py'))==plan['driver_sha256']==sha(z7.read('source/03_analysis/helper_extraction_20261004/edge_phase_context_20261005.py'))
    assert sha(z7.read('results/summary.json'))==spec['t7_summary_sha256']
    phase=pure_phase(z8.read('phase_context.py'));s7=read(z7,'results/summary.json');s8=read(z8,'results/summary.json');audit=read(za,'results/summary.json')
    assert s7['complete'] and s7['error'] is None and s7['actual_compile']==s7['actual_sim']==48 and s7['model_calls']==0
    frozen=read(z7,'results/FROZEN_INPUT_MANIFEST.json')
    for n,h in frozen.items():assert sha(z7.read('results/'+n))==h
    native_controls=[]
    for row in s7['controls']:
        folder='results/'+row['key']+'_'+row['variant']+'/'
        c=read(z7,folder+'contract.json');prompt=z7.read(folder+'prompt.txt').decode();parsed=dict(edge_contract.parse(prompt),family='edge');assert c==parsed
        original=edge_contract.render_tb(c,'Constructed_'+row['key']);assert z7.read(folder+'original_tb.sv').decode()==original
        assert z7.read(folder+'tb.sv').decode()==phase.instrument_tb(original,c)
        log=z7.read(folder+'simulate.log').decode();rows,bound=phase.context(log,c,edge_contract)
        assert read(z7,folder+'observations.json')==rows
        assert read(z7,folder+'feedback.json')==dict(context=bound,text=phase.render_feedback(c,bound,edge_feedback))
        assert row['actual_pass']==row['expected_pass']==(bound is None) and row['checks']==len(rows) and row['mismatches']==sum(x['mismatch'] for x in rows)
        for kind in ['compile','simulate']:
            receipt=read(z7,folder+kind+'.receipt.json');b=z7.read(folder+kind+'.log')
            assert receipt['returncode']==0 and not receipt['timeout'] and not receipt['launch_error'] and not receipt['remaining_live_group'] and receipt['log_sha256']==sha(b) and receipt['log_bytes']==len(b)
        native_controls.append(row)
    assert len(native_controls)==48
    for number,z in zs.items():
        g=read(z,'guard/status.json');assert all(g[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released']) and g['stage_rc']==0 and g['owned_cleanup']['verified'] and not g['owned_cleanup']['remaining']
    for n,h in read(za,'results/PROVENANCE_MANIFEST.json').items():assert sha(z8.read(n))==h,n
    assert s8['complete'] and s8['valid'] and not s8['error'] and s8['actual_model_requests']==s8['received_model_responses']==20
    assert spec['first_generation_replayed'] and spec['expected_samples']==20 and spec['solve_deadline_s']==300 and spec['judge_timeout_s']==150
    helper=R.parent/'full156_postflight_20261004/audit.py';assert sha(helper.read_bytes())=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('own_original_judge_binding',helper);baseline=load('own_extract_only',OWNER/'package/baseline.py')
    original=zipfile.ZipFile(OWNER/'raw_evidence/terminal_v1.zip')
    samples=[];counts={t:{a:0 for a in ['S','P']} for t in spec['task_ids']};output_hashes={t:{a:[] for a in ['S','P']} for t in spec['task_ids']}
    with tempfile.TemporaryDirectory(prefix='phase-original-readonly-') as tmp:
        tmp=Path(tmp)
        for n in manifests[46]:p=tmp/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z8.read(n))
        cloud=next(v['ticket']['cwd'] for v in json.loads((R/'raw_evidence/ORIGINAL_INVENTORY.json').read_bytes()) if v['ticket']['ticket']==46)
        def native_command(d):
            log=tmp/PurePosixPath(d['log']).relative_to(PurePosixPath(cloud)).as_posix();shared.command(d,log)
        for t in spec['task_ids']:
            for i in [0,1]:
                for name in ['request.json','response.json']:
                    assert z8.read('replay/'+t+'/'+str(i)+'/'+name)==original.read('run/results/samples/E/'+t+'/worker/requests/'+str(i)+'/'+name)
        for item,stored in zip(spec['order'],s8['rows']):
            t,a,k=item['task'],item['arm'],item['repeat'];folder='results/samples/r'+str(k)+'/'+t+'/'+a+'/';w=folder+'worker/'
            row=read(z8,folder+'row.json');assert row==stored and row['task']==t and row['arm']==a and row['repeat']==k
            for n in ['worker.receipt.json','judge.receipt.json']:native_command(read(z8,folder+n))
            journal=read(z8,w+'requests.json');assert len(journal)==2
            codes=[];requests=[]
            for i,e in enumerate(journal):
                prefix=w+'requests/'+str(i)+'/';q=read(z8,prefix+'request.json');resp=read(z8,prefix+'response.json')
                assert sha(z8.read(prefix+'request.json'))==e['request_sha256'] and sha(z8.read(prefix+'response.json'))==e['response_sha256']
                assert e['response_received'] and e['replayed']==(i==0) and e['actual_post_attempted']==(i==1)
                assert e['finish_reason']==resp['choices'][0]['finish_reason'] and e['usage']==resp.get('usage')
                assert q['model']==spec['model'] and q['temperature']==0 and q['top_p']==1 and q['max_tokens']==8192
                if not i:assert z8.read(prefix+'response.json')==z8.read('replay/'+t+'/0/response.json') and q==read(z8,'replay/'+t+'/0/request.json')
                requests.append(q);codes.append(baseline.extract(resp['choices'][0]['message'].get('content') or '', 'rtl'))
            c=edge_dispatch.parse(requests[0]['messages'][1]['content']);assert c['status']=='supported' and c['family']=='edge'
            original_second=read(z8,'replay/'+t+'/1/request.json');assert requests[1]['messages'][0]==original_second['messages'][0]
            for i in [0,1]:
                f=w+'map_check_'+str(i)+'/'
                assert f+'probe/result.json' in manifests[46]
                native=read(z8,f+'probe/result.json');tb=edge_dispatch.render_tb(c,t)
                if a=='P':tb=phase.instrument_tb(tb,c)
                assert read(z8,f+'contract.json')==c and z8.read(f+'input.sv').decode()==codes[i]
                assert z8.read(f+'inputs/'+t+'/tb.sv').decode()==tb and sha(tb.encode())==native['tb_sha256']==sha(z8.read(f+'probe/tb.sv'))
                assert sha(codes[i].encode())==native['solution_sha256']==sha(z8.read(f+'probe/dut.sv')) and native['inputs_unchanged']
                assert native['runner_sha256']==spec['dependency_hashes']['probe_runner.py']
                assert [v['name'] for v in native['stages']]==['xvlog','xelab','xsim']
                for v in native['stages']:native_command(v)
                log=z8.read(f+'probe/xsim.log').decode();marks=re.findall(r'^R2_PROBE_RESULT task=(\w+) checks=(\d+) mismatches=(\d+)\s*$',log,re.M)
                assert marks==[(t,str(c['checks']),str(native['mismatches']))]
                assert native['status']==('pass' if native['mismatches']==0 else 'fail')
                if native['mismatches']:
                    p=edge_contract.counterexample(log,c);assert read(z8,f+'counterexample.json')==p;text=edge_feedback.render(c,native,p)
                    if a=='P':
                        observations,bound=phase.context(log,c,edge_contract);assert read(z8,f+'phase_context.json')==dict(rows=observations,bound=bound,original_feedback=text)
                        text=phase.render_feedback(c,bound,edge_feedback)
                    assert read(z8,f+'feedback.json')['text']==text
                    if not i:assert requests[1]['messages'][1]['content']==requests[0]['messages'][1]['content']+'\nPrevious candidate:\n'+codes[0]+'\nCandidate diagnostics:\n'+text
            compiles=read(z8,w+'compile_journal.json');assert len(compiles)==2
            for i,d in enumerate(compiles):
                native_command(d);assert d['returncode']==0 and len(d['argv'])==3 and PurePosixPath(d['argv'][0]).name=='xvlog' and d['argv'][1]=='--sv'
                assert sha(z8.read(w+'compile_receipts/'+str(i)+'/source_before.sv'))==d['source_before_sha256']==d['source_after_sha256']==sha(codes[i].encode())
            solution=tmp/w/'solution.v';assert solution.read_bytes()==codes[1].encode() and sha(solution.read_bytes())==row['solution_sha256']
            v=original_judge(z8,folder+'judge/',solution.read_bytes(),t);assert v==row['verdict']
            native=read(z8,w+'map_check_1/probe/result.json');success=native['status']=='pass' and native['mismatches']==0 and v['level']==3
            assert row['native_pass']==(native['mismatches']==0)
            counts[t][a]+=success;output_hashes[t][a].append(row['solution_sha256']);samples.append(dict(task=t,arm=a,repeat=k,level=v['level'],native_and_l3=success))
    assert len(samples)==20 and counts=={t:{a:audit['per_task'][t][a]['native_and_l3'] for a in ['S','P']} for t in spec['task_ids']}
    result=dict(schema='teammate_phase_original_review_v1',evidence_valid=True,archive_sha256={str(k):v for k,v in PINS.items()},manifest_files={str(k):len(v) for k,v in manifests.items()},phase_source_sha256=sha(z8.read('phase_context.py')),source_commit=spec['source_commit'],original_owner_replay_bytes_bound=True,conditional_samples=20,actual_model_requests=20,actual_model_responses=20,first_generation_replayed=True,native_and_official_L3=counts,output_hashes=output_hashes,constructed_controls=48,review_model_calls=0,review_eda_calls=0,signal_supports_fresh_same_budget_pilot=True,qualified_for_full=False,independent_model_tasks=0,adoption=False,limits=['Two known checkpoints, five correlated conditional repairs per arm; not five fresh full solves or independent designs.','T7 command receipts bind logs/rc but omit argv; actual command arguments inferred only from fixed driver, not independently archived native argv.','External installed tools, dependencies and original guard observations are historical evidence; not a fresh hardware or offline certification.','Own old full156, edge and FSM gates remain unchanged. Fresh C/phase16 requires two matched native+official repair chains and all guards/cost conditions.'])
    (R/'RESULTS.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps({k:result[k] for k in ['evidence_valid','conditional_samples','native_and_official_L3','signal_supports_fresh_same_budget_pilot','review_model_calls','review_eda_calls']}))
if __name__=='__main__':run()
