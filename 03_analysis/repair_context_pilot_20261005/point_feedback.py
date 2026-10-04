"""Factual native counterexample feedback only, never DUT expressions."""
def render(c,result,p):
    assert result['failure_kind']=='semantic_mismatch' and 0<result['mismatches']<=result['checks']==c['checks']
    if c['kind']=='priority':
        return ('ERROR: Candidate simulation disagrees with the supplied priority-encoder specification. '
            'At '+c['input']+'='+str(p['inputs'][c['input']])+', '+p['output']+' should be '+str(p['expected'])+
            ', but the candidate produced '+p['observed']+'. '
            'The prompt requires the least significant set-bit position and zero for an all-zero vector.')
    assert c['kind']=='shift'
    inputs=', '.join(name+'=0x'+format(value,'x') for name,value in p['inputs'].items())
    previous='unknown before first synchronous load' if p['previous'] is None else '0x'+format(p['previous'],'x')
    phase='while the clock is held stable after applying the inputs' if p['phase']=='stable' else 'after one complete clock cycle'
    return ('ERROR: Candidate simulation disagrees with the supplied arithmetic-shifter specification. '
        'At sequence step '+str(p['step'])+', '+inputs+', required prior '+p['output']+'='+previous+', '+phase+', '
        +p['output']+' should be 0x'+format(p['expected'],'x')+', but the candidate produced 0x'+p['observed_hex']+'. '
        'The prompt specifies arithmetic right shifts with sign extension, synchronous load instead of shifting, and disabled shifting holds state. '
        'The check does not assert a clock-edge polarity that the prompt omitted.')
