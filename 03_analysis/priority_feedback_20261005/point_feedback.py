"""Native, prompt-derived LSB-priority evidence; no DUT answers."""
def render(contract,result,point):
    assert contract['status']=='supported' and result['failure_kind']=='semantic_mismatch'
    assert 0<result['mismatches']<=result['checks']==contract['checks']
    value=point['inputs'][contract['input']]
    assert any(c['inputs']==point['inputs'] and c['expected']==point['expected'] for c in contract['cases'])
    return ('ERROR: Candidate simulation disagrees with the supplied priority-encoder specification. '
        'At '+contract['input']+'='+str(value)+', '+point['output']+' should be '+str(point['expected'])+
        ', but the candidate produced '+point['observed']+'. '
        'The prompt requires the least significant set-bit position and zero for an all-zero vector.')
