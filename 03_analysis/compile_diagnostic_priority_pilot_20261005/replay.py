"""Rebuild exact original phaseP checks and native stdout→repair provenance."""
import hashlib,json,re
from pathlib import PurePosixPath
import diagnostic_policy


def replay(work,prompt,arm,contract,baseline,runtime,parser,feedback,probe,sha,read,deadline):
    journal=read(work/'requests.json')
    compiles=read(work/'compile_journal.json') if (work/'compile_journal.json').exists() else []
    trace=[json.loads(s) for s in (work/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(e.get('error') for e in trace)
    assert arm in ('C','P') and not any(e['tool']=='repair_context' for e in trace)
    assert not list(work.glob('elaboration_check_*'))
    delivered={}
    for n,e in enumerate(compiles):
        p=work/'compile_receipts'/str(n);source=p/'source_before.sv'
        assert len(e['argv'])==3 and PurePosixPath(e['argv'][0]).name=='xvlog' and e['argv'][1]=='--sv'
        assert PurePosixPath(e['argv'][-1]).is_absolute()
        assert PurePosixPath(e['argv'][-1]).parent.name in {'compile-'+str(i) for i,r in enumerate(journal) if r['response_received']}
        diagnostic_policy.normal_return(e)
        assert source.read_bytes()==(p/'source_after.sv').read_bytes()
        assert e['source_sha256']==e['source_before_sha256']==e['source_after_sha256']==sha(source)==sha(p/'source_after.sv')
        raw,stdout,proof=diagnostic_policy.verify(arm,e,p,sha,read)
        normalize=lambda text:text.replace(e['argv'][-1],'<owned_candidate.sv>')
        delivered[n]=dict(stdout=stdout,selected=diagnostic_policy.feedback(stdout),proof=proof,
            fact_sha256=diagnostic_policy.text_sha(normalize(raw)),
            feedback_sha256=diagnostic_policy.text_sha(normalize(diagnostic_policy.feedback(stdout))))
    previous='';diagnostic='';candidates=[''];first=None;patches=0;used_maps=set();native_chain=None
    for i,request in enumerate(journal):
        folder=work/'requests'/str(i);body=read(folder/'request.json')
        user=prompt if i==0 else prompt+'\nPrevious candidate:\n'+previous+'\nCandidate diagnostics:\n'+diagnostic
        assert body['messages'][1]==dict(role='user',content=user)
        if not request['response_received']:
            assert deadline and i==len(journal)-1;continue
        payload=read(folder/'response.json');choice=payload['choices'][0]
        assert choice.get('finish_reason')==request['finish_reason'] and payload.get('id')==request['response_id']
        previous=baseline.extract(choice['message'].get('content') or '','rtl');candidates.append(previous)
        if i==0:first=hashlib.sha256((choice['message'].get('content') or '').encode()).hexdigest()
        rounds=[(n,e) for n,e in enumerate(compiles) if PurePosixPath(e['argv'][-1]).parent.name=='compile-'+str(i)]
        assert len(rounds)<=2
        check=work/('map_check_'+str(i))
        if re.search(r'`include|\$(?:readmem\w*|fopen|system)\b',previous):
            diagnostic='Return a self-contained module without file access or include directives.'
            assert not rounds and not check.exists()
        elif not re.search(r'\bmodule\s+TopModule\b',previous) or 'endmodule' not in previous:
            diagnostic='Return a complete TopModule ending in endmodule.'
            if choice.get('finish_reason')=='length':diagnostic+=' Output reached the token limit; shorten the implementation.'
            assert not rounds and not check.exists()
        else:
            undefined=runtime.undefined_submodules(previous)
            if undefined:
                diagnostic='The design instantiates module(s) that this file never defines: '+', '.join(undefined)+'.'
                assert not rounds and not check.exists()
            elif rounds:
                n,entry=rounds[0];evidence=work/'compile_receipts'/str(n)
                assert (evidence/'source_before.sv').read_text(encoding='utf-8')==previous
                diagnostic=delivered[n]['selected']
                lint=[e for e in trace if e['tool']=='lint' and e.get('round')==i]
                assert len(lint)==1 and lint[0]['rc']==entry['returncode'] and lint[0]['excerpt']==diagnostic
                if i==0 and entry['returncode']>0 and len(journal)==2:
                    native_chain=dict(repair_request_index=1,initial_compile_index=n,
                        initial_code_sha256=sha(evidence/'source_before.sv'),initial_returncode=entry['returncode'],
                        initial_native_fact_sha256=delivered[n]['fact_sha256'],
                        normalized_feedback_sha256=delivered[n]['feedback_sha256'],
                        priority_invoked=delivered[n]['proof']['priority_invoked'],
                        policy_effect_feedback_changed=delivered[n]['proof']['feedback_changed'],
                        feedback_bound=False,complete=False,repaired_compile_returncode=None,
                        repaired_compile_direct=False,mechanical_failed_recompiles=len(rounds)-1)
                if len(rounds)==2:
                    assert entry['returncode']>0
                    patched=runtime.repair_ansi_declarations(previous,diagnostic);assert patched
                    pn,pe=rounds[1];assert pe['argv']==entry['argv']
                    assert (work/'compile_receipts'/str(pn)/'source_before.sv').read_text(encoding='utf-8')==patched
                    if pe['returncode']==0:
                        candidates.append(patched);patches+=1
                        assert i==len(journal)-1 and not check.exists()
                    # The unchanged runtime keeps FIRST feedback after a failed mechanical recompile.
                if i==1 and native_chain:
                    native_chain.update(feedback_bound=True,complete=True,
                        repaired_compile_returncode=entry['returncode'],repaired_compile_direct=len(rounds)==1,
                        repaired_code_sha256=sha(evidence/'source_before.sv'))
                if check.exists():
                    assert entry['returncode']==0 and len(rounds)==1 and contract['status']=='supported'
                    assert not re.search(r'\$[A-Za-z_]|`include',previous)
                    assert read(check/'contract.json')==contract
                    assert (check/'input.sv').read_text(encoding='utf-8')==previous
                    used_maps.add(check.name);result=probe(check,contract)
                    diagnostic=read(check/'feedback.json')['text'] if result['mismatches'] else ''
                    events=[e for e in trace if e['tool']=='map_feedback' and e.get('round')==i]
                    if diagnostic:assert len(events)==1 and events[0]['excerpt']==diagnostic and events[0]['repair_available']==(i==0)
                    else:assert not events
                    if not result['mismatches']:assert i==len(journal)-1
                elif entry['returncode']==0:
                    assert contract['status']!='supported' or re.search(r'\$[A-Za-z_]|`include',previous) or deadline
                    assert i==len(journal)-1
            else:assert deadline,'Missing original compilation outside deadline'
        if i+1<len(journal):assert diagnostic
    assert {p.name for p in work.glob('map_check_*')}==used_maps
    final=(work/'solution.v').read_text(encoding='utf-8')
    if deadline:assert final in candidates
    elif patches:assert final==candidates[-1]
    else:assert final==previous
    return dict(first_reply_sha256=first,declaration_patches=patches,
        original_repair_feedback_bound=True,native_compile_repair=native_chain)
