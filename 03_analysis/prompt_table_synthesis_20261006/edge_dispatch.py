"""Complete prompt-only dispatch; original priority/shift paths remain intact."""
import edge_contract
import priority_contract
import shift_contract
import prompt_map
import phase_context


def parse(prompt):
    old = [('priority', priority_contract.parse(prompt)),
           ('shift', shift_contract.parse(prompt))]
    edge = edge_contract.parse(prompt)
    if edge['status'] == 'supported' and all(c['status'] == 'skip' for _, c in old):
        return dict(edge, family='edge')
    if edge['status'] == 'skip':
        return prompt_map.parse(prompt)
    return dict(status='abstain', reason='unknown_or_ambiguous_complete_contract')


def render_tb(c, task):
    return phase_context.instrument_tb(edge_contract.render_tb(c, task),c) if c.get('family') == 'edge' else prompt_map.render_tb(c, task)


def counterexample(log, c):
    if c.get('family') != 'edge':return prompt_map.counterexample(log,c)
    rows,bound=phase_context.context(log,c,edge_contract)
    assert bound is not None
    return dict(bound['first'],phase_context=bound)
