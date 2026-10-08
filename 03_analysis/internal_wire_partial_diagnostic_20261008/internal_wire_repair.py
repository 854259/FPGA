
"""Conservative compiler-named internal wire repair, never a solver or extractor."""
import hashlib
import re
import agent_extract_boundary

NONREG = re.compile(r"ERROR:\s*\[VRFC 10-1280\]\s*procedural assignment to a non-register\s+([A-Za-z_$][A-Za-z0-9_$]*)\s+is not permitted")
PROCEDURES = frozenset(('always', 'always_ff', 'always_comb', 'always_latch', 'initial'))
DECLARATIONS = frozenset(('wire', 'reg', 'logic', 'bit', 'integer', 'time', 'genvar', 'tri', 'wand', 'wor'))
INSTANCE_FORBIDDEN = PROCEDURES | DECLARATIONS | frozenset(('begin','end','if','else','case','casex','casez','endcase','for','while','repeat','return','assign','input','output','inout','module','parameter','localparam'))
UNSUPPORTED = frozenset(('generate', 'endgenerate', 'function', 'endfunction', 'task', 'endtask', 'fork', 'join', 'join_any', 'join_none'))


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def repair(code, feedback):
    """Inputs are candidate text and its compiler feedback only. No external IO."""
    receipt = dict(schema='compiler_named_internal_wire_repair_draft_v1', status='abstain',
        reason=None, original_sha256=digest(code), feedback_sha256=digest(feedback),
        targets=[], compiler_reported_targets=[], inferred_unreported_targets=[], edits=[], model_calls=0, EDA_calls=0, external_io_calls=0,
        compiled=False, score_measured=False)
    def abstain(reason):
        receipt['reason'] = reason
        return None, receipt
    targets = list(dict.fromkeys(NONREG.findall(feedback)))
    receipt['targets'] = targets
    receipt['compiler_reported_targets'] = list(targets)
    if not targets:
        return abstain('no_matching_compiler_nonregister_error')
    for line in feedback.splitlines():
        if 'ERROR:' in line and '[VRFC 10-1280]' not in line and '[VRFC 10-8530]' not in line:
            return abstain('other_compiler_error_present')
    words, error = agent_extract_boundary.tokens(code)
    if error:
        return abstain(error)
    span, error = agent_extract_boundary.module_span(code)
    if error or span is None:
        return abstain(error or 'no_unique_top_module')
    # Keep quoted strings opaque; real punctuation retains its exact token value.
    values = [word if word is not None else (code[start:end] if end-start == 1 else '<opaque>') for word,start,end in words]
    if values.count('module') != 1 or any(v in UNSUPPORTED for v in values):
        return abstain('complex_module_scope_not_supported')
    try:
        module = values.index('module')
        assert values[module+1] == 'TopModule'
        header_end = values.index(';', module+2)
        endmodule = values.index('endmodule', header_end+1)
    except (ValueError, IndexError, AssertionError):
        return abstain('simple_top_header_not_found')
    ports = {v for v in values[module+2:header_end] if re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', v)}
    if any(name in ports for name in targets):
        return abstain('compiler_target_is_a_port_or_header_symbol')
    regions = []
    for index in range(header_end+1, endmodule):
        if values[index] not in PROCEDURES:
            continue
        cursor = index+1
        if cursor < endmodule and values[cursor] == '@':
            cursor += 1
            if cursor < endmodule and values[cursor] == '(':
                level = 1; cursor += 1
                while cursor < endmodule and level:
                    level += (values[cursor] == '(') - (values[cursor] == ')')
                    cursor += 1
                if level:
                    return abstain('unbalanced_sensitivity')
            elif cursor < endmodule and values[cursor] == '*':
                cursor += 1
        if cursor >= endmodule or values[cursor] != 'begin':
            continue  # Any target written outside a recognized block will abstain below.
        begin = cursor; level = 1; cursor += 1
        while cursor < endmodule and level:
            level += (values[cursor] == 'begin') - (values[cursor] == 'end')
            cursor += 1
        if level:
            return abstain('unbalanced_procedural_block')
        regions.append((begin, cursor-1))
    def lhs_after(index):
        cursor = index+1
        if cursor < endmodule and values[cursor] == '[':
            depth = 1; cursor += 1
            while cursor < endmodule and depth:
                depth += (values[cursor] == '[') - (values[cursor] == ']')
                cursor += 1
        return values[cursor:cursor+2] == ['<','='] or (cursor < endmodule and values[cursor] == '=')
    # This deliberately narrow policy also abstains on procedural port writers.
    if any(values[i] in ports and lhs_after(i) and any(a < i < b for a,b in regions) for i in range(header_end+1, endmodule)):
        return abstain('procedural_port_assignment_present')
    # xvlog can stop after the first error. Infer only other simple module nets
    # actually written by recognized processes, then apply every same scope,
    # single-writer, shadowing, and instance guard below to the entire set.
    inferred = []
    for index in range(header_end+1, endmodule):
        if values[index] != 'wire' or any(a < index < b for a,b in regions):
            continue
        cursor = index+1
        if values[cursor:cursor+1] == ['[']:
            shape = values[cursor:cursor+5]
            if len(shape) != 5 or shape[0] != '[' or not shape[1].isdigit() or shape[2] != ':' or not shape[3].isdigit() or shape[4] != ']':
                continue
            cursor += 5
        if cursor+1 >= endmodule or values[cursor+1] != ';':
            continue
        name = values[cursor]
        if name in targets or name in ports or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', name):
            continue
        if any(values[i] == name and lhs_after(i) and any(a < i < b for a,b in regions) for i in range(header_end+1, endmodule)):
            inferred.append(name)
    targets = targets + list(dict.fromkeys(inferred))
    receipt['targets'] = targets
    receipt['inferred_unreported_targets'] = list(dict.fromkeys(inferred))
    receipt['repair_basis'] = 'actual compiler nonregister error plus guarded candidate declarations'
    declarations = {name:[] for name in targets}
    for index in range(header_end+1, endmodule):
        if values[index] != 'wire' or any(a < index < b for a,b in regions):
            continue
        cursor = index+1
        if values[cursor:cursor+1] == ['[']:
            shape = values[cursor:cursor+5]
            if len(shape) != 5 or shape[0] != '[' or not shape[1].isdigit() or shape[2] != ':' or not shape[3].isdigit() or shape[4] != ']':
                continue
            cursor += 5
        if cursor+1 < endmodule and values[cursor] in targets and values[cursor+1] == ';':
            declarations[values[cursor]].append(index)
    if any(len(declarations[name]) != 1 for name in targets):
        return abstain('unique_simple_module_wire_declaration_missing')
    for name in targets:
        declaration = declarations[name][0]
        for index in range(header_end+1, endmodule):
            if values[index] not in DECLARATIONS or index == declaration:
                continue
            cursor = index+1
            while cursor < endmodule and values[cursor] != ';':
                if values[cursor] == name:
                    return abstain('additional_or_shadowing_declaration')
                cursor += 1
        owners = set()
        for index in range(header_end+1, endmodule):
            if values[index] != name or not lhs_after(index):
                continue
            matching = [i for i,(a,b) in enumerate(regions) if a < index < b]
            if len(matching) != 1:
                return abstain('writer_outside_one_supported_procedure')
            owners.add(matching[0])
        if len(owners) != 1:
            return abstain('zero_or_multiple_procedural_writers')
        for index in range(header_end+1, endmodule):
            if values[index] == 'assign':
                cursor = index+1
                while cursor < endmodule and values[cursor] not in ('=', ';'):
                    if values[cursor] == name:
                        return abstain('continuous_driver_present')
                    cursor += 1
            # A module/gate instance with this net in its connection list is ambiguous.
            if index+2 < endmodule and values[index] not in INSTANCE_FORBIDDEN and values[index+2] == '(' and re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',values[index]) and re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',values[index+1]):
                cursor = index+3
                while cursor < endmodule and values[cursor] != ';':
                    if values[cursor] == name:
                        return abstain('instance_connection_present')
                    cursor += 1
    patched = code
    for name in sorted(targets, key=lambda n:words[declarations[n][0]][1], reverse=True):
        index = declarations[name][0];start,end = words[index][1:]
        assert code[start:end] == 'wire'
        patched = patched[:start]+'reg'+patched[end:]
        receipt['edits'].append(dict(name=name, start=start, end=end, old='wire', new='reg'))
    receipt.update(status='compiler_named_internal_wire_changed', reason=None, patched_sha256=digest(patched))
    return patched, receipt
