"""Conservative, task-independent register ownership diagnostics.

This detects a structural issue, not a functional verdict. Unsupported scopes
abstain. Existing public-contract feedback retains priority; no request is made
here and no candidate is rewritten. This draft is not part of running142.
"""
import hashlib
import json
import re
from pathlib import Path

SCHEMA = 'register_ownership_feedback_draft_v1'
_WORDS = re.compile(r"[A-Za-z_]\w*|\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|<=|>=|==|!=|&&|\|\||[^\s]")


def inspect_source(code):
    """Prove mixed combinational/clocked writes for simple whole registers only."""
    if not isinstance(code, str):
        raise TypeError('candidate source must be text')
    result = dict(schema=SCHEMA, source_sha256=hashlib.sha256(code.encode()).hexdigest(),
                  status='unsupported', reason=None, registers=[], processes=[], findings=[],
                  functional_verdict=None, candidate_rewritten=False,
                  reference_or_testbench_used=False)
    # Strip lexical distractions, but retain strings as inert tokens.
    scrubbed = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                      lambda m: ' ' if not m.group().startswith('"') else '""', code, flags=re.S)
    if re.search(r'`|\\|\b(?:generate|endgenerate|function|endfunction|task|endtask|initial|force|release)\b', scrubbed):
        result['reason'] = 'conditional, local, initialization or nonprocedural scopes unsupported'
        return result
    tokens = _WORDS.findall(scrubbed)
    if tokens.count('module') != 1 or tokens.count('endmodule') != 1:
        result['reason'] = 'requires exactly one module'
        return result
    # Single-name non-array reg/logic declarations; other names are not inferred.
    names = set(re.findall(r'\b(?:reg|logic)\s*(?:\[[^\[\]]+\]\s*)?([A-Za-z_]\w*)\s*;', scrubbed))
    result['registers'] = sorted(names)
    owners = {name: {'combinational': [], 'clocked': []} for name in names}
    i = 0
    while i < len(tokens):
        if tokens[i] not in ('always', 'always_comb', 'always_ff', 'always_latch'):
            i += 1
            continue
        start = i
        kind = tokens[i]
        i += 1
        if kind in ('always', 'always_ff'):
            if i >= len(tokens) or tokens[i] != '@':
                result['reason'] = 'unsupported process event control'
                return result
            i += 1
            if i < len(tokens) and tokens[i] == '*':
                event = ['*']; i += 1
            elif i < len(tokens) and tokens[i] == '(':
                depth = 1; i += 1; event = []
                while i < len(tokens) and depth:
                    t = tokens[i]; depth += (t == '(') - (t == ')')
                    if depth: event.append(t)
                    i += 1
                if depth:
                    result['reason'] = 'unclosed event control'
                    return result
            else:
                result['reason'] = 'unsupported process event control'
                return result
            if any(t in ('posedge', 'negedge') for t in event):
                phase = 'clocked'
            elif event == ['*']:
                phase = 'combinational'
            else:
                result['reason'] = 'explicit non-edge sensitivity is outside this draft'
                return result
        elif kind == 'always_comb':
            phase = 'combinational'
        else:
            result['reason'] = 'latch processes outside this draft'
            return result
        if i >= len(tokens) or tokens[i] != 'begin':
            result['reason'] = 'single-statement processes outside this draft'
            return result
        depth = 1; i += 1; body = []
        while i < len(tokens) and depth:
            t = tokens[i]; depth += (t == 'begin') - (t == 'end')
            if depth: body.append(t)
            i += 1
        if depth or any(t in ('reg', 'logic', 'integer', 'int', 'automatic', 'static') for t in body):
            result['reason'] = 'unclosed block or local declarations unsupported'
            return result
        writes = set(); parens = brackets = 0
        for index, t in enumerate(body):
            if t in names and parens == brackets == 0 and index + 1 < len(body) and body[index + 1] in ('=', '<='):
                writes.add(t)
            parens += (t == '(') - (t == ')')
            brackets += (t == '[') - (t == ']')
            if parens < 0 or brackets < 0:
                result['reason'] = 'unbalanced expression'
                return result
        if parens or brackets:
            result['reason'] = 'unbalanced expression'
            return result
        identity = len(result['processes'])
        result['processes'].append(dict(index=identity, token_offset=start,
                                        phase=phase, whole_register_writes=sorted(writes)))
        for name in writes: owners[name][phase].append(identity)
    result['findings'] = [dict(register=name, **owners[name]) for name in sorted(names)
                          if owners[name]['combinational'] and owners[name]['clocked']]
    result['status'] = 'mixed_procedural_owners' if result['findings'] else 'no_proven_mixed_owners'
    result['reason'] = None
    return result


def format_feedback(report):
    if report['status'] != 'mixed_procedural_owners':
        return None
    names = ', '.join(f['register'] for f in report['findings'])
    return (f'Static RTL ownership check: {names} has whole-register assignments '
            'in both a combinational process and a clocked process. Give each '
            'register one procedural owner; separate combinational next values '
            'from stored values where needed. Recheck the prompt behavior after '
            'repairing this structure. This is not a functional verdict and uses '
            'no reference design or private testbench.')


def run_worker(base, args, paired, table_feedback):
    """Draft hook: preserve original C and all supported table/phase checks."""
    if args.arm != 'P':
        return table_feedback.run_worker(base, args, paired)
    original = base.functional_feedback

    def fallback(prompt, code, out, attempt, tools, task, candidate=False):
        existing = original(prompt, code, out, attempt, tools, task, candidate=candidate)
        if existing is not None:
            return existing
        report = inspect_source(code)
        report.update(attempt=attempt, public_contract_feedback_abstained=True,
                      requests_made=0, repair_budget_changed=False)
        dest = Path(out) / ('register_ownership_' + str(attempt) + '.json')
        with dest.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2); stream.write('\n')
        return format_feedback(report)

    base.functional_feedback = fallback
    try:
        return table_feedback.run_worker(base, args, paired)
    finally:
        base.functional_feedback = original
