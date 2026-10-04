"""Render specification rows and observed errors, never a DUT/expression."""


def render(contract, result, point):
    assert contract['status']=='supported' and result['failure_kind']=='semantic_mismatch'
    assert result['checks']==contract['checks'] and 0<result['mismatches']<=result['checks']
    inputs=', '.join(k+'='+str(v) for k,v in point['inputs'].items())
    rows=['ERROR: Candidate simulation disagrees with the supplied Karnaugh map. '
        'At '+inputs+', '+point['output']+' should be '+str(point['expected'])+
        ', but the candidate produced '+point['observed']+'.',
        'Simulation found '+str(result['mismatches'])+' mismatches in '+str(result['checks'])+' required input combinations.',
        'Re-evaluate the implementation against every required row below. '
        'Do not patch only the reported case. Columns use the listed input order. '
        'Unspecified dont-care rows are omitted.',
        'Required truth table:', ' '.join(contract['inputs'])+' | '+contract['output']]
    for case in contract['cases']:
        if case['expected'] is not None:
            rows.append(' '.join(str(case['inputs'][n]) for n in contract['inputs'])+' | '+str(case['expected']))
    return '\n'.join(rows)
