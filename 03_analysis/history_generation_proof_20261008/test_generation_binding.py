"""New read-only generation-proof controls; never executes worker/model/EDA."""
import hashlib,importlib.util,json,shutil
from pathlib import Path
from types import SimpleNamespace
import generation_binding as proof
import original_model_replay as replay
import selector,onehot_producer,timer_producer

ROOT=Path(__file__).resolve().parent
providers=[('onehot',onehot_producer),('timer',timer_producer)]
sha=proof.sha;read=proof.read
save=lambda p,j:Path(p).write_bytes((json.dumps(j,indent=2)+'\n').encode())


def rejected(call):
    try:call()
    except (AssertionError,KeyError,ValueError,FileNotFoundError):return True
    raise AssertionError('Malformed generation evidence accepted')


def route(record,arm,prompt,interface,present=True,run=ROOT):
    return proof.bound_route(record,run,arm,prompt,interface,present,selector,providers)


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    assert all(sha(ROOT/n)==h for n,h in read(ROOT/'SOURCE_MANIFEST.json').items())
    fixtures=read(ROOT/'RETAINED_INPUTS_PRIVATE.json')
    results=[];negatives=[];fake_mechanical=[]
    for f in fixtures:
        folder=ROOT/'FAKE_MECHANICAL_METADATA'/f['label'];folder.mkdir(parents=True)
        (folder/'prompt_only').mkdir();(folder/'prompt_only/prompt.txt').write_bytes(f['prompt'].encode());(folder/'prompt_only/interface.txt').write_bytes(f['interface'].encode())
        decision=selector.select(f['prompt'],f['interface'],[(n,m.synthesize) for n,m in providers]);recipe=decision['recipe'];label=f['label']
        expected=dict(schema='history_recipe_generation_route_v1',route='mechanical_'+label,outer_arm='P',prompt_sha256=proof.digest(f['prompt']),interface_sha256=proof.digest(f['interface']),interface_present=True,baseline_worker_sha256=sha(ROOT/'baseline_worker.py'),synthesis_source_sha256=sha(ROOT/(label+'_producer.py')),selector_source_sha256=sha(ROOT/'selector.py'),provider_source_hashes={n:sha(ROOT/(n+'_producer.py')) for n,m in providers},selected_provider=label,selection_sha256=proof.digest(json.dumps(decision,sort_keys=True,separators=(',',':'))),generated_solution_sha256=recipe['rtl_sha256'])
        save(folder/'generation_route.json',expected);save(folder/'generation_selection.json',decision);save(folder/'synthesis_receipt.json',recipe)
        save(folder/'requests.json',[]);(folder/'solution.v').write_bytes(recipe['rtl'].encode());(folder/'emission').mkdir();(folder/'emission/emitted.sv').write_bytes(recipe['rtl'].encode());save(folder/'emission/contract.json',recipe['contract'])
        native=folder/'native_receipts/0';native.mkdir(parents=True);save(native/'command.json',dict(simulated=True,fixture='NEW_FAKE_METADATA_NOT_EXECUTION'))
        r,actual=route(folder,'P',f['prompt'],f['interface']);assert actual==f['receipt'] and r==expected
        results.append('fake_metadata_'+label+'_route_and_original_recipe_bound')
        row=dict(arm='P',selected_provider=label,solve_deadline_reached=False,actual_model_requests=0,received_model_responses=0)
        rejected(lambda:proof.mechanical_provenance(folder,ROOT,'fake',row,recipe,folder,SimpleNamespace(),None,None));negatives.append('fake_'+label+'_native_refused')
        fake_mechanical.append((folder,f,expected,decision))
    folder,f,expected,decision=fake_mechanical[0]
    for key,value in [('outer_arm','C'),('route','mechanical_timer'),('selected_provider','timer'),('selector_source_sha256','0'*64),('synthesis_source_sha256','0'*64),('selection_sha256','0'*64),('generated_solution_sha256','0'*64),('interface_present',False)]:
        copy=ROOT/'MUTANTS'/('route_'+key);shutil.copytree(folder,copy);j=read(copy/'generation_route.json');j[key]=value;save(copy/'generation_route.json',j)
        rejected(lambda:route(copy,'P',f['prompt'],f['interface']));negatives.append('route_'+key)
    for key in ['selected_provider','recipe','observed']:
        copy=ROOT/'MUTANTS'/('selection_'+key);shutil.copytree(folder,copy);j=read(copy/'generation_selection.json');j[key]=None;save(copy/'generation_selection.json',j)
        rejected(lambda:route(copy,'P',f['prompt'],f['interface']));negatives.append('selection_'+key)
    copy=ROOT/'MUTANTS/duplicate_json_key';shutil.copytree(folder,copy);p=copy/'generation_route.json';raw=p.read_bytes();p.write_bytes(b'{"outer_arm":"P",'+raw[1:]);rejected(lambda:route(copy,'P',f['prompt'],f['interface']));negatives.append('duplicate_JSON_key')
    for name in proof.PINNED:
        copy=ROOT/'MUTANT_SOURCES'/name.replace('/','_');copy.mkdir(parents=True)
        for asset in proof.PINNED:
            p=copy/asset;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/asset).read_bytes())
        p=copy/name;p.write_bytes(p.read_bytes()+b'\n')
        rejected(lambda:route(folder,'P',f['prompt'],f['interface'],run=copy));negatives.append('source_'+name)
    baseline=load('proof_original_baseline',ROOT/'package/baseline.py');runtime=load('proof_original_runtime',ROOT/'package/agent/map_runtime.py')
    import edge_dispatch,phase_feedback
    generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text();repair=(ROOT/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
    def probe(*args):raise AssertionError('No probe/model/EDA in evidence controls')
    rows=[]
    for record in sorted((ROOT/'RETAINED_MOCK_RECORDS/ACTUAL_BASELINE_MOCK_OUTPUTS').iterdir()):
        if record.name=='transport_failure':continue
        source=ROOT/'RETAINED_MOCK_RECORDS/SIMULATED_KIT'/record.name/'bench/tasks_veval/generic_input'
        prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode()
        arm='C' if '_C' in record.name else 'P'
        r,recipe=route(record,arm,prompt,interface);assert recipe is None and r['route']=='model'
        journal=read(record/'requests.json');row=dict(task='generic_input',arm=arm,generation_route='model',selected_provider=None,actual_model_requests=len(journal),received_model_responses=len(journal),solve_deadline_reached=False)
        proof.model_requests(record,row,dict(model='SIMULATED-history-router'),generation,repair)
        combined=prompt.replace('\r\n','\n').replace('\r','\n')
        normalized=interface.replace('\r\n','\n').replace('\r','\n')
        if normalized.strip():combined+='\n\nInterface:\n'+normalized
        result=replay.replay(record,combined,arm,edge_dispatch.parse(combined),baseline,runtime,edge_dispatch,phase_feedback,probe,sha,read,False)
        assert result['original_repair_feedback_bound']
        rows.append((record,source,prompt,interface,arm,row,combined))
        rejected(lambda:proof.verify(record,ROOT,source,arm,row,record,dict(model='SIMULATED-history-router'),(selector,providers,replay,baseline,runtime,edge_dispatch,phase_feedback,SimpleNamespace()),probe))
        negatives.append('simulated_native_'+record.name+'_cannot_authorize_real_generation')
    assert len(rows)==6
    results.extend(['retained_original_baseline_mock_record_route_requests_reply_replay']*6)
    record,source,prompt,interface,arm,row,combined=[r for r in rows if r[0].name=='unrelated_P_repair'][0]
    for case in ['model','max_tokens','temperature','top_p','system','first_user','repair_user','reply','usage','response_id','request_index_bool']:
        copy=ROOT/'MUTANTS'/('model_'+case);shutil.copytree(record,copy);journal=read(copy/'requests.json');index=1 if case=='repair_user' else 0;request=copy/'requests'/str(index)/'request.json';response=request.with_name('response.json')
        if case in ['model','max_tokens','temperature','top_p','system','first_user','repair_user']:
            body=read(request)
            if case=='model':body['model']='other-model'
            elif case=='max_tokens':body['max_tokens']=8191
            elif case=='temperature':body['temperature']=.1
            elif case=='top_p':body['top_p']=.5
            elif case=='system':body['messages'][0]['content']+=' changed'
            else:body['messages'][1]['content']+=' changed'
            save(request,body);journal[index]['request_sha256']=sha(request)
        elif case=='request_index_bool':journal[0]['index']=False
        else:
            payload=read(response)
            if case=='reply':payload['choices'][0]['message']['content']='module TopModule; endmodule'
            elif case=='usage':payload['usage']['completion_tokens']=1
            else:payload['id']='other-id'
            save(response,payload);journal[index]['response_sha256']=sha(response)
        save(copy/'requests.json',journal)
        def transcript():
            proof.model_requests(copy,row,dict(model='SIMULATED-history-router'),generation,repair)
            replay.replay(copy,combined,arm,edge_dispatch.parse(combined),baseline,runtime,edge_dispatch,phase_feedback,probe,sha,read,False)
        rejected(transcript);negatives.append('model_'+case)
    failed=ROOT/'RETAINED_MOCK_RECORDS/ACTUAL_BASELINE_MOCK_OUTPUTS/transport_failure';journal=read(failed/'requests.json');assert len(journal)==1 and journal[0]['response_received'] is False and not (failed/'worker_result.json').exists();results.append('old_unconfirmed_failure_retained_no_new_call')
    assert all(sha(ROOT/n)==h for n,h in read(ROOT/'SOURCE_MANIFEST.json').items())
    result=dict(schema='history_generation_new_readonly_proof_controls_v1',passed=True,
        positive_metadata_or_transcript_contexts=len(results),rejection_contexts=len(negatives),
        positives=results,rejections=negatives,mechanical_positive_records_explicitly_fabricated_metadata=True,
        six_model_records_original_new_worker_mocks_readonly=True,
        original_replay_byte_exact=True,new_worker_model_EDA_FIFO_calls=0,
        old_worker_controls_native_intake_or_full_auditor_not_rerun=True,
        actual_new_native_positive_proof_or_whole_archive_audit_executed=False,
        scoring_stage_admission_score_or_adoption=False)
    save(ROOT/'ACTUAL_GENERATION_PROOF_RESULT.json',result);print(json.dumps(result))


if __name__=='__main__':main()
