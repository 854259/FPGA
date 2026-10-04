"""Compress only large ordinary whole-line comments in repair prompt copies.

The generated DUT and diagnostics are never changed. This is intentionally
narrow: directives, block comments and malformed lexical units abstain.
"""
import hashlib
import re

DIRECTIVE = re.compile(r'pragma|synopsys|synthesis|verilator|translate_(?:on|off)|'
                       r'full_case|parallel_case|lint_(?:on|off)|coverage_(?:on|off)', re.I)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def comment_spans(code):
    """Identify real // comments, protecting strings and escaped identifiers."""
    spans = []
    i = 0
    while i < len(code):
        if code[i] == '`':
            return None, 'preprocessor'
        if code.startswith('/*', i):
            return None, 'block_comment'
        if code[i] == '"':
            i += 1
            while i < len(code) and code[i] != '"':
                if code[i] in '\r\n':
                    return None, 'incomplete_string'
                if code[i] == '\\':
                    i += 1
                    if i == len(code) or code[i] in '\r\n':
                        return None, 'incomplete_string'
                i += 1
            if i == len(code):
                return None, 'incomplete_string'
            i += 1
        elif code[i] == '\\':
            i += 1
            if i == len(code) or code[i].isspace():
                return None, 'incomplete_escaped_identifier'
            while i < len(code) and not code[i].isspace():
                i += 1
            if i == len(code):
                return None, 'incomplete_escaped_identifier'
        elif code.startswith('//', i):
            end = code.find('\n', i)
            if end == -1:
                end = len(code)
            if end > i and code[end-1] == '\r':
                end -= 1
            body = code[i:end]
            if DIRECTIVE.search(body) or body.rstrip().endswith('\\'):
                return None, 'special_comment'
            spans.append((i, end))
            i = end
        else:
            i += 1
    return spans, None


def projection(code, spans):
    """Exact non-comment characters, including all original whitespace."""
    parts, previous = [], 0
    for begin, end in spans:
        parts.append(code[previous:begin]); previous = end
    parts.append(code[previous:])
    return ''.join(parts)


def compress(code):
    spans, reason = comment_spans(code)
    metadata = dict(changed=False, input_sha256=sha(code), input_chars=len(code),
                    output_chars=len(code), removed_chars=0, removed_lines=0,
                    policy='whole-line ordinary //; >=2048 chars and >=50% of copy')
    if reason:
        return code, dict(metadata, reason=reason, output_sha256=sha(code))
    selected = []
    for begin, end in spans:
        prefix = code[code.rfind('\n', 0, begin)+1:begin]
        if not prefix.strip():
            # Preserve CRLF, and every line position, in the copy.
            if end > begin and code[end-1] == '\r':
                end -= 1
            selected.append((begin, end))
    removed = sum(end-begin for begin, end in selected)
    if removed < 2048 or removed * 2 < len(code):
        return code, dict(metadata, reason='below_threshold', output_sha256=sha(code))
    parts, previous = [], 0
    for begin, end in selected:
        parts.append(code[previous:begin]); previous = end
    parts.append(code[previous:]); result = ''.join(parts)
    after, error = comment_spans(result)
    assert error is None
    assert projection(code, spans) == projection(result, after)
    assert code.count('\n') == result.count('\n')
    metadata.update(changed=True, output_chars=len(result), removed_chars=removed,
                    removed_lines=len(selected), reason='compressed',
                    output_sha256=sha(result), code_projection_sha256=sha(projection(code, spans)))
    return result, metadata
