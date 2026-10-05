"""Bound observed phases only; original non-edge diagnostics unchanged."""
import edge_feedback
import point_feedback
import phase_context
def render(c,result,p):
    if c.get('family')!='edge':return point_feedback.render(c,result,p)
    bound=p['phase_context']
    assert bound['mismatches']==result['mismatches'] and result['checks']==c['checks']
    assert bound['first']=={k:v for k,v in p.items() if k!='phase_context'}
    old=edge_feedback.render(c,result,bound['first'])
    enriched=phase_context.render_feedback(c,bound,edge_feedback)
    assert enriched.startswith(old+' Related observations')
    return enriched
