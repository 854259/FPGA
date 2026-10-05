"""Complete prompt-only FSM dispatch, preserving original unknown/priority/shift paths."""
import fsm_contract
import priority_contract
import shift_contract
import prompt_map

FAMILIES=('full_vector_multistate','partial_scalar_onehot')

def parse(prompt):
    old=prompt_map.parse(prompt)
    fsm=fsm_contract.parse(prompt)
    if (fsm['status']=='supported' and old['status']!='supported'
        and priority_contract.parse(prompt)['status']=='skip'
        and shift_contract.parse(prompt)['status']=='skip'):
        return fsm
    return old

def render_tb(c,task):
    return fsm_contract.render_tb(c,task) if c.get('family') in FAMILIES else prompt_map.render_tb(c,task)

def counterexample(log,c):
    return fsm_contract.counterexample(log,c) if c.get('family') in FAMILIES else prompt_map.counterexample(log,c)
