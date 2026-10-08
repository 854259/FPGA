"""New composition controls only; synthetic providers are explicitly fake."""
import copy
import json
from pathlib import Path
from selector import select, digest


def recipe(prompt, interface, emitted):
    contract = dict(all_prompt_consumed=True, fake=True) if emitted else None
    rtl = 'module fake; endmodule\n' if emitted else ''
    return dict(emitted=emitted, prompt_sha256=digest(prompt),
                interface_sha256=digest(interface), rtl=rtl, contract=contract,
                rtl_sha256=digest(rtl) if emitted else None,
                contract_sha256=digest(json.dumps(contract,sort_keys=True,separators=(',', ':'))) if emitted else None,
                actual_model_requests=0, actual_eda_calls=0, external_io_calls=0)


def run():
    cases=[]
    def check(name, providers, route, reason=None):
        result=select('unchanged prompt', 'unchanged interface', providers)
        assert result['route']==route and result['reason']==reason
        cases.append(name)
        return result
    yes=lambda p,i:recipe(p,i,True)
    no=lambda p,i:recipe(p,i,False)
    check('both_abstain',[('onehot',no),('timer',no)],'model','no_complete_contract')
    a=check('unique_first',[('onehot',yes),('timer',no)],'mechanical')
    b=check('unique_second',[('timer',no),('onehot',yes)],'mechanical')
    assert a['recipe']==b['recipe'] and a['selected_provider']==b['selected_provider']=='onehot'
    check('timer_unique',[('onehot',no),('timer',yes)],'mechanical')
    check('collision_even_same_RTL',[('onehot',yes),('timer',yes)],'model','ambiguous_complete_contracts')
    for field,value in [('prompt_sha256','0'*64),('interface_sha256','0'*64),
                        ('rtl_sha256','0'*64),('contract_sha256','0'*64),
                        ('actual_model_requests',1),('actual_eda_calls',1),
                        ('external_io_calls',1),('actual_model_requests',False),
                        ('emitted',1),('rtl','')]:
        def mutant(p,i,field=field,value=value):
            r=yes(p,i);r[field]=value;return r
        check('invalid_'+field+'_'+str(value),[('bad',mutant),('good',yes)],'model','invalid_provider_receipt')
    def incomplete(p,i):
        r=yes(p,i);r['contract']['all_prompt_consumed']=False;return r
    check('incomplete_contract',[('bad',incomplete),('good',yes)],'model','invalid_provider_receipt')
    check('non_dict',[('bad',lambda p,i:None),('good',yes)],'model','invalid_provider_receipt')
    def fake_abstain_RTL(p,i):
        r=no(p,i);r['rtl']='unexpected';return r
    check('abstention_must_not_emit',[('bad',fake_abstain_RTL),('good',yes)],'model','invalid_provider_receipt')
    for providers in [[],[('same',no),('same',yes)]]:
        try:select('p','i',providers)
        except ValueError:cases.append('invalid_provider_registry')
        else:raise AssertionError('Invalid registry accepted')
    observed=[]
    def records(p,i):
        observed.append((p,i));return recipe(p,i,False)
    check('unchanged_provider_inputs',[('first',records),('second',records)],'model','no_complete_contract')
    assert observed==[('unchanged prompt','unchanged interface')]*2
    saved=yes('unchanged prompt','unchanged interface');before=copy.deepcopy(saved)
    result=check('recipe_identity_preserved',[('only',lambda p,i:saved)],'mechanical')
    assert result['recipe'] is saved and saved==before
    return dict(schema='new_history_router_synthetic_controls_v1',passed=True,
                controls=len(cases),cases=cases,providers_fake=True,
                new_model_EDA_FIFO_calls=0,native_or_score_qualification=False)


if __name__=='__main__':
    result=run()
    Path('ACTUAL_SELECTOR_CONTROLS.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
