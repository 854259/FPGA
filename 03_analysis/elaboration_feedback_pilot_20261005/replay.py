"""Read-only provenance of original checks, declaration patches and repair messages."""
import hashlib,json,re
from pathlib import PurePosixPath


def replay(work,prompt,arm,contract,baseline,runtime,parser,feedback,probe,sha,read,deadline,elaborate):
    journal=read(work/'requests.json');compiles=read(work/'compile_journal.json') if (work/'compile_journal.json').exists() else []
    trace=[json.loads(s) for s in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e.get('error') for e in trace)
    assert arm in ['C','P'] and not any(e['tool']=='repair_context' for e in trace)
    previous='';diagnostic='';candidates=[''];first=None;patches=0
    elaboration_checks=[];bound_elaboration_repair=False;used_elaboration=set();used_maps=set()
    for i,request in enumerate(journal):
        folder=work/'requests'/str(i);body=read(folder/'request.json')
        copy=previous
        user=prompt if i==0 else prompt+'\nPrevious candidate:\n'+copy+'\nCandidate diagnostics:\n'+diagnostic
        assert body['messages'][1]==dict(role='user',content=user)
        if not request['response_received']:
            assert deadline and i==len(journal)-1;continue
        payload=read(folder/'response.json');choice=payload['choices'][0]
        assert choice.get('finish_reason')==request['finish_reason'] and payload.get('id')==request['response_id']
        previous=baseline.extract(choice['message'].get('content') or '','rtl');candidates.append(previous)
        if not i:first=hashlib.sha256((choice['message'].get('content') or '').encode()).hexdigest()
        rounds=[(n,e) for n,e in enumerate(compiles) if PurePosixPath(e['argv'][-1]).parent.name=='compile-'+str(i)]
        assert len(rounds)<=2
        check=work/('map_check_'+str(i));elab=work/('elaboration_check_'+str(i))
        if re.search(r'`include|\$(?:readmem\w*|fopen|system)\b',previous):
            diagnostic='Return a self-contained module without file access or include directives.';assert not rounds and not check.exists() and not elab.exists()
        elif not re.search(r'\bmodule\s+TopModule\b',previous) or 'endmodule' not in previous:
            diagnostic='Return a complete TopModule ending in endmodule.'
            if choice.get('finish_reason')=='length':diagnostic+=' Output reached the token limit; shorten the implementation.'
            assert not rounds and not check.exists() and not elab.exists()
        else:
            undefined=runtime.undefined_submodules(previous)
            if undefined:
                diagnostic='The design instantiates module(s) that this file never defines: '+', '.join(undefined)+'.'
                assert not rounds and not check.exists() and not elab.exists()
            elif rounds:
                n,entry=rounds[0];evidence=work/'compile_receipts'/str(n)
                assert (evidence/'source_before.sv').read_text(encoding='utf-8')==previous
                log=(evidence/'owned_compile.log').read_text(encoding='utf-8')
                diagnostic='\n'.join(s for s in log.splitlines() if re.search('ERROR|WARNING|FATAL',s))[:2048] or log[-2048:]
                if len(rounds)==2:
                    assert entry['returncode']!=0
                    patched=runtime.repair_ansi_declarations(previous,diagnostic);assert patched
                    pn,pe=rounds[1];assert pe['argv']==entry['argv']
                    assert (work/'compile_receipts'/str(pn)/'source_before.sv').read_text(encoding='utf-8')==patched
                    if pe['returncode']==0:
                        candidates.append(patched);patches+=1;assert i==len(journal)-1 and not check.exists() and not elab.exists()
                if elab.exists():
                    assert arm=='P' and len(rounds)==1 and entry['returncode']==0
                    result=elaborate(elab,previous,i)
                    elaboration_checks.append(result);used_elaboration.add(elab.name)
                    diagnostic=result['feedback']
                    if result['outcome']=='fail':
                        assert diagnostic and not check.exists()
                        events=[e for e in trace if e['tool']=='map_feedback' and e.get('round')==i]
                        assert len(events)==1 and events[0]['excerpt']==diagnostic
                        assert events[0]['repair_available']==(i==0)
                        if i+1<len(journal):bound_elaboration_repair=True
                    else:
                        assert result['outcome']=='pass' and not diagnostic
                elif arm=='P' and entry['returncode']==0:
                    assert deadline,'Missing candidate elaboration after ordinary compile success'
                if check.exists():
                    assert arm in ['C','P'] and entry['returncode']==0 and contract['status']=='supported'
                    assert not elab.exists() or elaboration_checks[-1]['outcome']=='pass'
                    assert not re.search(r'\$[A-Za-z_]|`include',previous)
                    assert read(check/'contract.json')==contract
                    assert (check/'input.sv').read_text(encoding='utf-8')==previous
                    used_maps.add(check.name)
                    result=probe(check,contract)
                    diagnostic=read(check/'feedback.json')['text'] if result['mismatches'] else ''
                    events=[e for e in trace if e['tool']=='map_feedback' and e.get('round')==i]
                    if diagnostic:
                        assert len(events)==1 and events[0]['excerpt']==diagnostic and events[0]['repair_available']==(i==0)
                    else:assert not events
                    if not result['mismatches']:assert i==len(journal)-1
                elif entry['returncode']==0:
                    if not elab.exists() or elaboration_checks[-1]['outcome']!='fail':
                        assert contract['status']!='supported' or re.search(r'\$[A-Za-z_]|`include',previous) or deadline
                        assert i==len(journal)-1
                else:assert not elab.exists() and not check.exists()
            else:assert deadline,'Missing original compilation outside deadline'
        if i+1<len(journal):
            # The next exact payload already binds this independently derived diagnostic.
            assert diagnostic
    for n,e in enumerate(compiles):
        p=work/'compile_receipts'/str(n);log=p/'owned_compile.log'
        assert len(e['argv'])==3 and PurePosixPath(e['argv'][0]).name=='xvlog' and e['argv'][1]=='--sv'
        assert PurePosixPath(e['argv'][-1]).parent.name in {'compile-'+str(i) for i,r in enumerate(journal) if r['response_received']}
        assert not e['launch_error'] and not e['remaining_live_group']
        assert not e['timeout'] or deadline
        assert sha(log)==e['log_sha256'] and log.stat().st_size==e['log_bytes']
        assert e['source_sha256']==e['source_before_sha256']==e['source_after_sha256']==sha(p/'source_before.sv')==sha(p/'source_after.sv')
    assert {p.name for p in work.glob('elaboration_check_*')}==used_elaboration
    assert {p.name for p in work.glob('map_check_*')}==used_maps
    final=(work/'solution.v').read_text(encoding='utf-8')
    if deadline:assert final in candidates
    elif patches:assert final==candidates[-1]
    else:assert final==previous
    return dict(first_reply_sha256=first,declaration_patches=patches,original_repair_feedback_bound=True,
                elaboration_checks=elaboration_checks,elaboration_repair_feedback_bound=bound_elaboration_repair)
