"""Conservative, offline review selection; never validates or rewrites RTL.

This is deliberately a small text recognizer, not a SystemVerilog type checker.
Only the documented self-shifting-register subset can produce ``review``.
``skip`` means no demonstrated candidate under this rule, not correct RTL.
"""
import re


ID = r"[A-Za-z_][A-Za-z0-9_$]*"
RANGE = r"\[\s*(\d+)\s*:\s*(\d+)\s*\]"
DECL = re.compile(
    rf"(?:(wire|reg|logic)\s+)?(?:(signed|unsigned)\s+)?"
    rf"(?:{RANGE}\s*)?({ID})")
ASSIGNMENT = re.compile(rf"\b({ID})\s*(<=|(?<![=<>!])=(?!=))\s*(.*?);", re.S)


def _result(decision, reason, findings=None):
    return {"decision": decision, "reasons": [reason], "findings": findings or []}


def _strip_noncode(source):
    """Blank comments/strings while retaining character offsets and newlines."""
    out = list(source)
    index = 0
    while index < len(source):
        start = index
        if source.startswith('//', index):
            end = source.find('\n', index + 2)
            index = len(source) if end < 0 else end
        elif source.startswith('/*', index):
            end = source.find('*/', index + 2)
            if end < 0:
                return '', False
            index = end + 2
        elif source[index] == '"':
            index += 1
            while index < len(source):
                if source[index] == '\\':
                    index += 2
                elif source[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            else:
                return '', False
        else:
            index += 1
            continue
        for pos in range(start, min(index, len(source))):
            if out[pos] != '\n':
                out[pos] = ' '
    return ''.join(out), True


def _declaration(text, default_kind):
    match = DECL.fullmatch(text.strip())
    if not match:
        return None
    kind, sign, high, low, name = match.groups()
    return name, {'kind': kind or default_kind, 'signed': sign == 'signed',
                  'width': abs(int(high) - int(low)) + 1 if high else 1}


def _unparen(text):
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for index, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if depth == 0:
                break
        if index != len(text) - 1:
            break
        text = text[1:-1].strip()
    return text


def analyze(prompt: str, source: str) -> dict:
    """Return ``review``, ``skip`` or ``abstain`` using only the two strings.

    No filesystem, subprocess, model, evaluator or repair action is performed.
    Unsupported contexts intentionally abstain even if a human could type them.
    """
    if not isinstance(prompt, str) or not isinstance(source, str):
        return _result('abstain', 'inputs_must_be_strings')
    code, closed = _strip_noncode(source)
    if not closed:
        return _result('abstain', 'unterminated_comment_or_string')
    if '>>>' not in code:
        return _result('skip', 'no_actual_triple_right_shift')

    # Language recognition is intentionally narrower than keyword matching.
    # A sole output is insufficient when the specification describes mixed or
    # conditional semantics, or a different internal datapath.
    words = prompt.lower().replace('-', ' ').replace('\u2019', "'")
    words = re.sub(r'\ball\s+(?:input\s+and\s+output\s+)?ports\s+are\s+one\s+bit\s+'
                   r'unless\s+otherwise\s+specified\b', '', words)
    if (not re.search(r'\barithmetic\s+shift\s+(?:register|shifter)\b', words)
            or not re.search(r'\barithmetic\s+right\s+shift\b', words)):
        return _result('abstain', 'no_explicit_arithmetic_shift_register_contract')
    ambiguous = (r'\b(?:not|no|never|without|except|unless|excluding|logical|'
                 r'internal|intermediate|pipeline|stage|independent|separate|'
                 r'sometimes|some|optional|optionally|disabled|but|however|'
                 r'unlike|rather|versus)\b|\bzero\s+(?:fill|filled|extension)\b|'
                 r"\b(?:isn|aren|don|doesn|mustn|shouldn|won|can)'t\b")
    if re.search(ambiguous, words):
        return _result('abstain', 'mixed_negated_or_ambiguous_specification')
    if ('`' in code or '\\' in code or
            re.search(r'\b(?:typedef|parameter|localparam|genvar|generate|function|'
                      r'task|integer|int|byte|shortint|longint|struct|union|enum|'
                      r'interface|package|class|fork)\b|\bbegin\s*:', code)):
        return _result('abstain', 'unsupported_macro_type_or_scope')
    if len(re.findall(r'\bmodule\b', code)) != 1 or len(re.findall(r'\bendmodule\b', code)) != 1:
        return _result('abstain', 'requires_one_module')
    module = re.fullmatch(rf'\s*module\s+{ID}\s*\((.*?)\)\s*;(.*?)\bendmodule\s*', code, re.S)
    if not module:
        return _result('abstain', 'requires_simple_ansi_module')
    header, body = module.groups()
    declarations = {}
    outputs = []
    for item in header.split(','):
        port = re.fullmatch(r'\s*(input|output)\s+(.+?)\s*', item, re.S)
        parsed = _declaration(port[2], 'wire') if port else None
        if not parsed or parsed[0] in declarations:
            return _result('abstain', 'unsupported_or_duplicate_port_declaration')
        name, decl = parsed
        declarations[name] = decl
        if port[1] == 'output':
            outputs.append(name)
    if len(outputs) != 1:
        return _result('abstain', 'requires_one_output')

    # Only module-level declarations preceding behavior are recognized. Refuse
    # multiple declarators, aliases, symbolic ranges and later nested shadows.
    rest = body
    while re.match(r'\s*(?:reg|logic|wire)\b', rest):
        first, delimiter, tail = rest.partition(';')
        parsed = _declaration(first, 'wire') if delimiter else None
        if not parsed or parsed[0] in declarations:
            return _result('abstain', 'unsupported_or_duplicate_local_declaration')
        name, decl = parsed
        declarations[name] = decl
        rest = tail
    if re.search(r'\b(?:reg|logic|wire|input|output)\b', rest):
        return _result('abstain', 'declaration_outside_supported_scope')

    output = outputs[0]
    if declarations[output]['kind'] in ('reg', 'logic'):
        register = output
    else:
        direct = list(re.finditer(rf'\bassign\s+{re.escape(output)}\s*=\s*({ID})\s*;', body))
        writes = re.findall(rf'\b{re.escape(output)}\s*(?:\[[^]]*\]\s*)?(?:<=|=(?!=))', body)
        if len(direct) != 1 or len(writes) != 1:
            return _result('abstain', 'output_not_uniquely_connected_to_one_register')
        register = direct[0][1]
    reg_decl = declarations.get(register)
    if not reg_decl or reg_decl['kind'] not in ('reg', 'logic'):
        return _result('abstain', 'output_driver_not_a_known_register')
    if reg_decl['width'] != declarations[output]['width']:
        return _result('abstain', 'output_width_context_not_supported')

    findings = []
    seen = 0
    for match in ASSIGNMENT.finditer(body):
        rhs = _unparen(match[3])
        if '>>>' not in rhs:
            continue
        seen += rhs.count('>>>')
        if match[1] != register:
            return _result('abstain', 'shift_outside_output_register', findings)
        bare = re.fullmatch(rf'({ID})\s*>>>\s*(\d+)', rhs)
        cast = re.fullmatch(rf"(?:\$signed\(\s*({ID})\s*\)|signed'\(\s*({ID})\s*\))\s*>>>\s*(\d+)", rhs)
        operand = bare[1] if bare else (cast[1] or cast[2]) if cast else None
        amount = int(bare[2] if bare else cast[3]) if bare or cast else None
        if operand != register or amount is None:
            return _result('abstain', 'shift_expression_or_operand_not_supported', findings)
        # Same register on both sides removes destination-width propagation and
        # unrelated intermediate-value ambiguity from this narrow risk signal.
        findings.append({'operand': register,
                         'line': code[:module.start(2) + match.start()].count('\n') + 1,
                         'width': reg_decl['width'], 'shift_amount': amount,
                         'evidence': ('explicit_signed_cast' if cast else
                                      'signed_declaration' if reg_decl['signed'] else
                                      'bare_unsigned_register'),
                         'risk': bool(amount and bare and not reg_decl['signed'])})
    if seen != body.count('>>>') or not findings:
        return _result('abstain', 'triple_shift_not_in_supported_assignment', findings)
    if any(row['risk'] for row in findings):
        return _result('review', 'explicit_contract_with_unsigned_self_shift', findings)
    return _result('skip', 'no_demonstrated_bare_unsigned_self_shift_risk', findings)
