"""Observed mismatches from the supplied contract, with no implementation answer."""
import point_feedback


def render(c, result, p):
    if c.get('family') != 'edge':
        return point_feedback.render(c, result, p)
    assert result['failure_kind'] == 'semantic_mismatch'
    assert 0 < result['mismatches'] <= result['checks'] == c['checks']
    expected_row = [row for row in c['observations']
                    if row['step'] == p['step'] and row['phase'] == p['phase']]
    assert len(expected_row) == 1 and all(p[k] == v for k, v in expected_row[0].items())
    assert p['output'] == c['roles']['output']
    phase = {'stable': 'while the clock is held stable after applying the next input',
             'positive': 'after the specified positive clock edge',
             'cycle': 'after one complete clock cycle'}[p['phase']]
    inputs = ('prior ' + c['roles']['input'] + '=0x' + format(p['previous_input'], 'x')
              + ', current ' + c['roles']['input'] + '=0x' + format(p['input'], 'x'))
    if p['older_input'] is not None:
        inputs += ', earlier ' + c['roles']['input'] + '=0x' + format(p['older_input'], 'x')
    requirement = ('The supplied prompt requests changes in either direction.' if c['kind'] == 'any'
                   else 'The supplied prompt requests only transitions from zero to one.')
    edge = ('The supplied prompt specifies positive clock edges.' if c['clock_edge'] == 'positive'
            else 'No clock-edge polarity omitted by the prompt is asserted by this check.')
    return ('ERROR: Candidate simulation disagrees with the supplied vector edge-detection specification. '
            + 'At sequence step ' + str(p['step']) + ', ' + inputs + ', ' + phase + ', '
            + p['output'] + ' should be 0x' + format(p['expected'], 'x')
            + ', but the candidate produced 0x' + p['observed_hex'] + '. '
            + requirement + ' ' + edge + ' No reset value or initial history is assumed.')
