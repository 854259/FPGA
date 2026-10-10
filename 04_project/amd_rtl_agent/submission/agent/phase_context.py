"""Prompt-derived phase observations only; development controls are excluded."""
import re

def instrument_tb(original, contract):
    """Add observations without changing any original stimulus/check line."""
    lines, index = ([], 0)
    for line in original.splitlines(keepends=True):
        lines.append(line)
        if line.strip() == '_edgecheck_checks=_edgecheck_checks+1;':
            row = contract['observations'][index]
            lines.append('$display("EDGE_TRACE step=%d phase=%s expected=%x observed=%%h",%s);\n' % (row['step'], row['phase'], row['expected'], contract['roles']['output']))
            index += 1
    assert index == contract['checks']
    text = ''.join(lines)
    assert ''.join((x for x in text.splitlines(keepends=True) if not x.startswith('$display("EDGE_TRACE '))) == original
    return text

def context(log, contract, edge):
    """Bind every observed row and first mismatch before selecting one temporal group."""
    pattern = '^EDGE_TRACE step=(\\d+) phase=(stable|positive|cycle) expected=([0-9a-f]+) observed=([0-9a-fxz]+)\\s*$'
    matches = re.findall(pattern, log, re.M)
    assert len(matches) == sum((x.startswith('EDGE_TRACE') for x in log.splitlines())) == contract['checks']
    rows = []
    for item, expected in zip(matches, contract['observations']):
        step, phase, value, observed = item
        assert (int(step), phase, int(value, 16)) == (expected['step'], expected['phase'], expected['expected'])
        assert len(observed) <= (contract['width'] + 3) // 4
        unknown = bool(re.search('[xz]', observed))
        assert unknown or int(observed, 16) < 2 ** contract['width']
        rows.append(dict(**expected, observed_hex=observed, mismatch=unknown or int(observed, 16) != expected['expected']))
    summary = re.findall('^R2_PROBE_RESULT task=[A-Za-z][A-Za-z0-9_]* checks=(\\d+) mismatches=(\\d+)\\s*$', log, re.M)
    assert len(summary) == 1
    assert tuple(map(int, summary[0])) == (len(rows), sum((x['mismatch'] for x in rows)))
    mismatches = [x for x in rows if x['mismatch']]
    if not mismatches:
        assert not any((x.startswith('EDGE_FIRST') for x in log.splitlines()))
        return (rows, None)
    first = edge.counterexample(log, contract)
    observed = mismatches[0]
    assert all((first[k] == observed[k] for k in observed if k != 'mismatch'))
    group = [x for x in rows if x['step'] == first['step']]
    return (rows, dict(first=first, observations=group, mismatches=len(mismatches)))

def render_feedback(contract, bound, original_feedback):
    if bound is None:
        return ''
    result = dict(failure_kind='semantic_mismatch', mismatches=bound['mismatches'], checks=contract['checks'])
    old = original_feedback.render(contract, result, bound['first'])
    labels = dict(stable='before a clock transition, after applying the input', positive='after the specified positive clock edge', cycle='after one complete clock cycle')
    observations = [labels[x['phase']] + ': expected 0x' + format(x['expected'], 'x') + ', observed 0x' + x['observed_hex'] for x in bound['observations']]
    return old + ' Related observations at the same sequence step and input history: ' + '; '.join(observations) + '.'
