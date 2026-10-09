"""Prompt-only binary pattern prefix guidance; never emits a DUT or reads an oracle."""
import hashlib
import re
from reserved_keywords import KEYWORDS

SCHEMA = 'explicit_binary_pattern_prefix_guidance_v1'
COUNTS = dict(zip(('two', 'three', 'four', 'five', 'six', 'seven', 'eight',
                   'nine', 'ten', 'eleven', 'twelve'), range(2, 13)))
PATTERN = re.compile(
    r'\bWhen\s+(?P<input>[A-Za-z_][A-Za-z_0-9]*)\s+has\s+produced\s+the\s+values\s+'
    r'(?P<values>[01](?:\s*,\s*[01]){1,11})\s+in\s+'
    r'(?P<count>two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})'
    r'\s+successive\s+clock\s+cycles\b', re.I)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def transitions(pattern):
    """For each proper prefix and bit, retain the longest suffix that is a prefix."""
    assert isinstance(pattern, str) and 2 <= len(pattern) <= 12 and set(pattern) <= {'0', '1'}
    rows = []
    for matched in range(len(pattern)):
        row = {}
        for bit in '01':
            text = pattern[:matched] + bit
            length = next(n for n in range(min(len(text), len(pattern)), -1, -1)
                          if text.endswith(pattern[:n]))
            row[bit] = 'complete' if length == len(pattern) else length
        rows.append(row)
    return rows


def scalar_input(prompt, interface, name):
    if name in KEYWORDS:
        return False
    prompt = prompt.replace('\r\n', '\n').replace('\r', '\n')
    if interface.strip():
        # Deliberately bounded grammar: ANSI scalar declarations only. Other
        # interface spellings abstain rather than guessing vector width/direction.
        clean = re.sub(r'/\*.*?\*/|//[^\r\n]*', '', interface, flags=re.S)
        all_names = re.findall(r'\b(?:input|output|inout)\s+(?:(?:wire|logic)\s+)?'
                               r'(?:\[[^\]]+\]\s*)?([A-Za-z_]\w*)\b', clean)
        scalar = re.findall(r'\binput\s+(?:(?:wire|logic)\s+)?([A-Za-z_]\w*)\s*(?=[,)\;])', clean)
        return all_names.count(name) == 1 and scalar.count(name) == 1
    # The dataset's prompt interface has explicit bullet ports and the stated
    # default width. No task name or path enters this function.
    if not re.search(r'All\s+input\s+and\s+output\s+ports\s+are\s+one\s+bit\s+unless\s+'
                     r'otherwise\s+specified\.', prompt, re.I):
        return False
    names = re.findall(r'(?m)^\s*-\s*(?:input|output|inout)\s+([A-Za-z_]\w*)\b', prompt)
    scalar = re.findall(r'(?m)^[ \t]*-[ \t]*input[ \t]+([A-Za-z_]\w*)[ \t]*$', prompt)
    return names.count(name) == 1 and scalar.count(name) == 1


def extract(prompt, interface=''):
    assert isinstance(prompt, str) and isinstance(interface, str)
    result = dict(schema=SCHEMA, status='abstain', reason='', addendum='',
                  prompt_sha256=digest(prompt), interface_sha256=digest(interface),
                  derives_semantic_prefix_transitions=False, emits_rtl=False,
                  determines_reset_enable_output_timing=False)
    if len(prompt) > 131072 or len(interface) > 16384:
        result['reason'] = 'source_bound_exceeded'
        return result
    if re.search(r'\b(?:non[- ]overlapping|without\s+overlap)\b|'
                 r'\b(?:discard|restart)[^.!?]{0,80}\b(?:partial|mismatch)\b', prompt, re.I):
        result['reason'] = 'explicit_restart_or_nonoverlap_policy_not_supported'
        return result
    matches = list(PATTERN.finditer(prompt))
    mentions = list(re.finditer(r'\bhas\s+produced\s+the\s+values\b', prompt, re.I))
    if len(matches) != 1 or len(mentions) != 1:
        result['reason'] = 'one_unambiguous_explicit_pattern_required'
        return result
    match = matches[0]
    # A negated/quoted example is not a positive behavioral obligation.
    preceding = prompt[max(0, match.start()-100):match.start()].rsplit('.', 1)[-1]
    if re.search(r'\b(?:not|never|example|incorrect|ignore)\b', preceding, re.I):
        result['reason'] = 'negated_or_example_pattern_not_supported'
        return result
    name = match['input']
    bits = ''.join(re.findall('[01]', match['values']))
    count = COUNTS.get(match['count'].lower())
    if count is None:
        count = int(match['count'])
    if count != len(bits) or not scalar_input(prompt, interface, name):
        result['reason'] = 'cycle_count_or_scalar_input_not_bound'
        return result
    rows = transitions(bits)
    text = [
        'Semantic prefix guidance derived from the explicit input pattern in the specification.',
        'Source clause: ' + match.group(),
        'This is an abstract search guide, not RTL or a complete controller.',
        'Apply it only while the original specification actively monitors input ' + name + '.',
        'A partial match is the longest suffix of the samples seen so far that is a prefix of ' + bits + '.',
        'An unsuccessful extension may retain a nonempty prefix; do not discard it merely because that extension failed.',
    ]
    for length, row in enumerate(rows):
        state = 'empty' if length == 0 else bits[:length]
        def label(value):
            return 'pattern complete' if value == 'complete' else ('empty' if value == 0 else bits[:value])
        text.append('Matched prefix ' + state + ': next 0 -> ' + label(row['0']) + '; next 1 -> ' + label(row['1']) + '.')
    text.append('Completion is only the recognition event. Use the original specification for the clock edge, reset, enable, output latency and behavior after recognition; this guide assigns none of them.')
    result.update(status='supported', reason='', input=name, pattern=bits, transitions=rows,
                  source_span=[match.start(),match.end()], source_clause_sha256=digest(match.group()),
                  derives_semantic_prefix_transitions=True, addendum='\n'.join(text))
    return result
