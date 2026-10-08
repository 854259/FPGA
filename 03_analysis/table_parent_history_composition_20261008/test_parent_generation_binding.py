"""New parent/extension receipt binding controls; native metadata is simulated.

These do not execute the worker, model, EDA, original test suites or full intake.
"""
import json, shutil
from pathlib import Path
from types import SimpleNamespace
import composition, table_synthesis, onehot_producer, timer_producer
import generation_binding as proof

ROOT=Path(__file__).resolve().parent
providers=[('table',table_synthesis),('onehot',onehot_producer),('timer',timer_producer)]
save=lambda p,j:Path(p).write_bytes((json.dumps(j,indent=2)+'\n').encode())
positives=[]; negatives=[]

def rejects(label,call):
    try:call()
    except (AssertionError,KeyError,ValueError,FileNotFoundError):negatives.append(label);return
    raise AssertionError('Malformed generation record accepted: '+label)

def bind(folder,arm,prompt,interface):
    return proof.bound_route(folder,ROOT,arm,prompt,interface,True,composition,providers)

def metadata(label,arm,prompt,interface):
    folder=ROOT/'FAKE_NEW_ROUTE_METADATA'/label;folder.mkdir(parents=True)
    (folder/'prompt_only').mkdir()
    (folder/'prompt_only/prompt.txt').write_bytes(prompt.encode())
    (folder/'prompt_only/interface.txt').write_bytes(interface.encode())
    receipt=composition.parent(prompt,interface) if arm=='C' else composition.synthesize(prompt,interface)
    expected=dict(schema='table_parent_history_extension_generation_route_v1',
        route='mechanical_'+receipt['selected_provider'] if receipt['emitted'] else 'model',
        outer_arm=arm,prompt_sha256=proof.digest(prompt),interface_sha256=proof.digest(interface),
        interface_present=True,baseline_worker_sha256=proof.sha(ROOT/'baseline_worker.py'),
        synthesis_source_sha256=proof.sha(ROOT/'composition.py'),
        generated_solution_sha256=receipt['rtl_sha256'] if receipt['emitted'] else None)
    save(folder/'generation_route.json',expected);save(folder/'synthesis_receipt.json',receipt)
    route,recipe=bind(folder,arm,prompt,interface)
    assert route==expected and recipe==(receipt if receipt['emitted'] else None)
    positives.append(label)
    return folder,receipt

def main():
    assert all(proof.sha(ROOT/n)==h for n,h in proof.read(ROOT/'SOURCE_MANIFEST.json').items())
    fixtures=proof.read(ROOT/'RETAINED_INPUTS_PRIVATE.json')
    cases={f['label']:f for f in fixtures}
    assert set(cases)=={'table','onehot','timer'}
    contexts={}
    for label,f in cases.items():
        folder,receipt=metadata(label+'_P','P',f['prompt'],f['interface'])
        assert receipt['selected_provider']==label
        assert receipt['original_recipe']==f['receipt']
        contexts[label]=(folder,receipt,f)
    f=cases['table'];c,cr=metadata('table_C','C',f['prompt'],f['interface'])
    assert cr==contexts['table'][1]
    f=cases['onehot'];_,r=metadata('parent_abstain_C','C',f['prompt'],f['interface']);assert not r['emitted']
    _,r=metadata('all_abstain_P','P','Unspecified design.','');assert not r['emitted']
    folder,receipt,f=contexts['table']
    for field,value in [('selected_provider','timer'),('original_recipe',None),('parent_recipe',None),('rtl','module changed; endmodule')]:
        copy=ROOT/'MUTANTS'/field;shutil.copytree(folder,copy)
        j=proof.read(copy/'synthesis_receipt.json');j[field]=value;save(copy/'synthesis_receipt.json',j)
        rejects('parent_'+field,lambda:bind(copy,'P',f['prompt'],f['interface']))
    copy=ROOT/'MUTANTS/C_forged_extension';shutil.copytree(contexts['onehot'][0],copy)
    j=proof.read(copy/'generation_route.json');j['outer_arm']='C';save(copy/'generation_route.json',j)
    of=cases['onehot'];rejects('C_cannot_use_extension',lambda:bind(copy,'C',of['prompt'],of['interface']))
    copy=ROOT/'MUTANTS/duplicate_key';shutil.copytree(folder,copy)
    path=copy/'synthesis_receipt.json';path.write_bytes(b'{"emitted":true,'+path.read_bytes()[1:])
    rejects('duplicate_parent_receipt_key',lambda:bind(copy,'P',f['prompt'],f['interface']))
    # Native acceptance remains real-only even for a newly allowed C mechanical path.
    native=c/'native_receipts/0';native.mkdir(parents=True)
    save(c/'requests.json',[]);(c/'solution.v').write_bytes(cr['rtl'].encode())
    (c/'emission').mkdir();(c/'emission/emitted.sv').write_bytes(cr['rtl'].encode())
    save(c/'emission/contract.json',cr['contract'])
    save(native/'command.json',dict(simulated=True,fixture='NEW_C_METADATA_NOT_NATIVE_EXECUTION'))
    row=dict(arm='C',selected_provider='table',solve_deadline_reached=False,actual_model_requests=0,received_model_responses=0)
    rejects('C_fake_native_not_qualification',lambda:proof.mechanical_provenance(c,ROOT,'fake',row,cr,c,SimpleNamespace(),None,None))
    row=dict(row,selected_provider='onehot')
    rejects('C_extension_native_disallowed',lambda:proof.mechanical_provenance(c,ROOT,'fake',row,cr,c,SimpleNamespace(),None,None))
    source=ROOT/'composition.py';original=source.read_bytes()
    try:
        source.write_bytes(original+b'\n')
        rejects('composition_source_mismatch',lambda:bind(folder,'P',f['prompt'],f['interface']))
    finally:source.write_bytes(original)
    assert all(proof.sha(ROOT/n)==h for n,h in proof.read(ROOT/'SOURCE_MANIFEST.json').items())
    result=dict(passed=True,positive_route_contexts=len(positives),rejection_contexts=len(negatives),
        positives=positives,rejections=negatives,metadata_only_not_native_execution=True,
        new_parent_first_generation_interface_verified=True,old_request_replay_native_test_suites_and_intake_not_rerun=True,
        new_worker_model_EDA_FIFO_calls=0,new_real_native_positive_or_score=False)
    save(ROOT/'ACTUAL_PARENT_GENERATION_RESULT.json',result);print(json.dumps(result))

if __name__=='__main__':main()
