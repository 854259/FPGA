"""Only prompt-derived interface facts and an observed FSM mismatch; no DUT answers."""
import re
import point_feedback
from fsm_dispatch import FAMILIES

def render(c,result,p):
    if c.get('family') not in FAMILIES:return point_feedback.render(c,result,p)
    assert result['failure_kind']=='semantic_mismatch'
    assert 0<result['mismatches']<=result['checks']==c['checks']
    assert type(p['case']) is int and 0<=p['case']<len(c['observations'])
    expected=c['observations'][p['case']]
    assert p==dict(expected,observed_hex=p['observed_hex'],output_maps=c['output_maps'])
    value=p['observed_hex']
    assert re.fullmatch('[0-9a-fxz]+',value) and len(value)<=(c['output_width']+3)//4
    assert re.search('[xz]',value) or (int(value,16)!=p['expected'] and int(value,16)<1<<c['output_width'])
    active=', '.join(s for i,s in enumerate(c['states']) if p['state']>>i&1) or 'none'
    inputs=', '.join(k+'='+str(v) for k,v in p['inputs'].items())
    outputs=', '.join(m['name'] for m in c['output_maps'])
    domain=('The supplied prompt explicitly admits simultaneous active states.' if c['family']=='full_vector_multistate'
            else 'Only legal one-hot states are checked; no unspecified zero or multi-hot behavior is asserted.')
    return ('ERROR: Candidate simulation disagrees with the supplied complete combinational state-machine table. '
        +'At case '+str(p['case'])+', '+c['state_name']+'=0x'+format(p['state'],'x')
        +' (active states: '+active+'), '+inputs+', the packed outputs in declaration order ['+outputs
        +'] should be 0x'+format(p['expected'],'x')+', but the candidate produced 0x'+value+'. '
        +domain+' The prompt requests combinational transition and output logic only. No state flip-flops, reset signal or unspecified initialization behavior is added.')
