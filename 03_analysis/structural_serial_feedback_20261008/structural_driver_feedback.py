"""Conservative, bounded source-location evidence for scalar procedural writes.

This is not an HDL compiler or proof of synthesis failure. Unsupported complete
syntax abstains, and no DUT text is rewritten. No I/O, model or EDA calls.
"""
import bisect
import hashlib
import re

from agent_extract_boundary import tokens as lexical_tokens
from reserved_keywords import KEYWORDS

MAX_CHARS = 65536
MAX_BYTES = 131072
MAX_TOKENS = 16000
MAX_DEPTH = 48
MAX_PROCESSES = 64
MAX_ASSIGNMENTS = 2048
MAX_SYMBOLS = 512
MAX_FEEDBACK_CHARS = 4096
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_$]*\Z')
NUMBER = re.compile(r"(?:[0-9][0-9_]*'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]|[0-9][0-9_]*)")
OPERATORS = ('===', '!==', '<<<', '>>>', '==', '!=', '<=', '>=', '&&', '||',
             '<<', '>>', '~&', '~|', '^~', '~^', '**', '+:', '-:')
BINARY = {'||': 1, '&&': 2, '|': 3, '^': 4, '^~': 4, '~^': 4, '&': 5,
          '==': 6, '!=': 6, '===': 6, '!==': 6, '<': 7, '<=': 7, '>': 7,
          '>=': 7, '<<': 8, '>>': 8, '<<<': 8, '>>>': 8, '+': 9, '-': 9,
          '*': 10, '/': 10, '%': 10, '**': 11}
UNARY = {'+', '-', '!', '~', '&', '~&', '|', '~|', '^', '^~', '~^'}


class Unsupported(Exception):
    pass


def scan(text):
    """Reuse the repository scanner's opaque comment/string boundaries."""
    raw, error = lexical_tokens(text)
    if error:
        raise Unsupported(error)
    if len(raw) > MAX_TOKENS:
        raise Unsupported('token_limit')
    result, index = [], 0
    while index < len(raw):
        word, start, end = raw[index]
        value, kind, finish = text[start:end], 'symbol', end
        if value.startswith('\\'):
            raise Unsupported('escaped_identifier_not_supported')
        if value.startswith('"'):
            kind = 'literal'  # Entire string is opaque, never a keyword/write.
        else:
            number = NUMBER.match(text, start)
            if number and (value[0].isdigit() or value[0] == "'"):
                finish, value, kind = number.end(), number[0], 'literal'
            elif word is not None:
                kind = 'word'
            else:
                for operator in OPERATORS:
                    if text.startswith(operator, start):
                        value, finish = operator, start + len(operator)
                        break
        # The assembled operator/number must finish on real token boundaries.
        tail = index
        while tail < len(raw) and raw[tail][1] < finish:
            if raw[tail][2] > finish:
                raise Unsupported('numeric_or_operator_lexeme_not_supported')
            tail += 1
        if tail == index or raw[tail - 1][2] != finish:
            raise Unsupported('numeric_or_operator_boundary')
        result.append((value, kind, start, finish))
        index = tail
    return result


class SimpleModule:
    """Complete tiny grammar; no recovery or partial-module diagnostics."""
    def __init__(self, text, stream):
        self.text, self.stream, self.i = text, stream, 0
        self.symbols, self.reads, self.processes, self.writes = {}, set(), [], []
        self.lines = [-1] + [m.start() for m in re.finditer('\n', text)]

    def loc(self, token):
        offset = token[2]
        line = bisect.bisect_left(self.lines, offset)
        return dict(line=line, column=offset - self.lines[line - 1], offset=offset)

    def peek(self):
        return self.stream[self.i][0] if self.i < len(self.stream) else None

    def take(self, value=None):
        if self.i >= len(self.stream):
            raise Unsupported('incomplete_module_or_statement')
        token = self.stream[self.i]
        if value is not None and token[0] != value:
            raise Unsupported('expected_' + value)
        self.i += 1
        return token

    def identifier(self):
        token = self.take()
        if token[1] != 'word' or len(token[0]) > 128 or IDENT.fullmatch(token[0]) is None or token[0] in KEYWORDS:
            raise Unsupported('simple_identifier_required')
        return token

    def depth(self, value):
        if value > MAX_DEPTH:
            raise Unsupported('nesting_limit')

    def expr(self, minimum=0, depth=0):
        self.depth(depth)
        token = self.peek()
        if token in UNARY:
            self.take()
            self.expr(12, depth + 1)
        elif token == '(':
            self.take('(')
            self.expr(0, depth + 1)
            self.take(')')
        elif self.i < len(self.stream) and self.stream[self.i][1] == 'literal':
            self.take()
        else:
            identifier = self.identifier()[0]
            self.reads.add(identifier)
            # Selects in expressions are reads, never procedural writes.
            if self.peek() == '[':
                self.take('[')
                self.expr(0, depth + 1)
                if self.peek() in (':', '+:', '-:'):
                    self.take()
                    self.expr(0, depth + 1)
                self.take(']')
        while self.peek() in BINARY and BINARY[self.peek()] >= minimum:
            operator = self.take()[0]
            self.expr(BINARY[operator] + (operator != '**'), depth + 1)
        if minimum == 0 and self.peek() == '?':
            self.take('?')
            self.expr(0, depth + 1)
            self.take(':')
            self.expr(0, depth + 1)

    def packed(self):
        packed = False
        if self.peek() in ('signed', 'unsigned'):
            self.take()
        if self.peek() == '[':
            packed = True
            self.take('[')
            self.expr()
            self.take(':')
            self.expr()
            self.take(']')
        return packed

    def declare(self, token, storage, direction, packed):
        name = token[0]
        if name in self.symbols:
            raise Unsupported('duplicate_or_redeclared_symbol')
        if len(self.symbols) >= MAX_SYMBOLS:
            raise Unsupported('symbol_limit')
        if self.peek() in ('[', '='):
            raise Unsupported('array_or_declaration_initializer_not_supported')
        self.symbols[name] = dict(name=name, storage=storage, direction=direction,
                                  packed=packed, declaration=self.loc(token))

    def ports(self):
        self.take('(')
        if self.peek() != ')':
            direction = storage = None
            packed = False
            while True:
                if self.peek() in ('input', 'output'):
                    direction = self.take()[0]
                    storage = self.take()[0] if self.peek() in ('reg', 'logic', 'wire') else 'wire'
                    packed = self.packed()
                elif direction is None:
                    raise Unsupported('ANSI_scalar_or_packed_ports_required')
                self.declare(self.identifier(), storage, direction, packed)
                if self.peek() != ',':
                    break
                self.take(',')
        self.take(')')
        self.take(';')

    def declaration(self):
        storage = self.take()[0]
        packed = self.packed()
        while True:
            self.declare(self.identifier(), storage, None, packed)
            if self.peek() != ',':
                break
            self.take(',')
        self.take(';')

    def parameter(self):
        self.take()
        if self.peek() in ('integer', 'int', 'logic', 'reg'):
            self.take()
        packed = self.packed()
        while True:
            token = self.identifier()
            # Parameters are constants, not procedural candidate variables.
            self.take('=')
            self.expr()
            self.declare(token, 'parameter', None, packed)
            if self.peek() != ',':
                break
            self.take(',')
        self.take(';')

    def assignment(self, process, continuous=False):
        target = self.identifier()
        if self.peek() == '[':
            raise Unsupported('selected_or_array_LHS_not_supported')
        operator = self.take()
        if operator[0] not in (('=',) if continuous else ('=', '<=')):
            raise Unsupported('simple_direct_assignment_required')
        self.expr()
        end = self.take(';')
        if len(self.writes) >= MAX_ASSIGNMENTS:
            raise Unsupported('assignment_limit')
        self.writes.append(dict(variable=target[0], process=process, operator=operator[0],
                                assignment=self.loc(target), operator_location=self.loc(operator),
                                statement_end=self.loc(end), continuous=continuous))

    def statement(self, process, depth=0):
        self.depth(depth)
        token = self.peek()
        if token == ';':
            self.take()
        elif token == 'begin':
            self.take()
            if self.peek() == ':':
                raise Unsupported('named_or_local_scope_not_supported')
            while self.peek() != 'end':
                self.statement(process, depth + 1)
            self.take('end')
            if self.peek() == ':':
                raise Unsupported('named_or_local_scope_not_supported')
        elif token == 'if':
            self.take('if')
            self.take('(')
            self.expr()
            self.take(')')
            self.statement(process, depth + 1)
            if self.peek() == 'else':
                self.take('else')
                self.statement(process, depth + 1)
        elif token in ('case', 'casez', 'casex'):
            self.take()
            self.take('(')
            self.expr()
            self.take(')')
            default_seen = False
            while self.peek() != 'endcase':
                if self.peek() == 'default':
                    if default_seen:
                        raise Unsupported('repeated_default')
                    default_seen = True
                    self.take()
                else:
                    self.expr()
                    while self.peek() == ',':
                        self.take(',')
                        self.expr()
                self.take(':')
                self.statement(process, depth + 1)
            self.take('endcase')
        else:
            # Local declarations, function/task calls, loops, named scopes,
            # delays, event controls, concatenated/selected LHS all abstain.
            self.assignment(process)

    def process(self):
        token = self.take()
        if len(self.processes) >= MAX_PROCESSES:
            raise Unsupported('process_limit')
        clocked, events = False, []
        if token[0] != 'always_comb':
            self.take('@')
            if self.peek() == '*':
                self.take('*')
            else:
                self.take('(')
                if self.peek() == '*':
                    self.take('*')
                else:
                    edges = []
                    while True:
                        edge = self.take()[0] if self.peek() in ('posedge', 'negedge') else None
                        signal = self.identifier()[0]
                        self.reads.add(signal)
                        edges.append(edge)
                        events.append(dict(edge=edge, signal=signal))
                        if self.peek() not in ('or', ','):
                            break
                        self.take()
                    if any(edges) and not all(edges):
                        raise Unsupported('mixed_edge_and_level_event_control')
                    clocked = bool(edges and all(edges))
                self.take(')')
        if token[0] == 'always_ff' and not clocked:
            raise Unsupported('always_ff_without_supported_clock')
        process = len(self.processes)
        self.processes.append(dict(index=process, kind=token[0], clocked=clocked,
                                   start=self.loc(token), events=events))
        self.statement(process)
        self.processes[-1]['end'] = self.loc(self.stream[self.i - 1])

    def parse(self):
        self.take('module')
        module = self.identifier()[0]
        self.ports()
        while self.peek() != 'endmodule':
            token = self.peek()
            if token in ('reg', 'logic', 'wire'):
                self.declaration()
            elif token in ('parameter', 'localparam'):
                self.parameter()
            elif token in ('always', 'always_comb', 'always_ff'):
                self.process()
            elif token == 'assign':
                self.take('assign')
                self.assignment(None, continuous=True)
            else:
                raise Unsupported('unsupported_module_item_' + str(token))
        self.take('endmodule')
        if self.i != len(self.stream):
            raise Unsupported('unconsumed_text_or_multiple_modules')
        for identifier in self.reads:
            if identifier not in self.symbols:
                raise Unsupported('undeclared_expression_identifier')
        for write in self.writes:
            symbol = self.symbols.get(write['variable'])
            if symbol is None or symbol['storage'] == 'parameter' or symbol['direction'] == 'input':
                raise Unsupported('unresolved_or_unsupported_assignment_target')
            if not write['continuous'] and symbol['storage'] not in ('reg', 'logic'):
                raise Unsupported('procedural_write_to_nonvariable')
        return module


def analyze(code):
    """Return abstain / supported_no_conflict / source_conflict_needs_review."""
    if not isinstance(code, str):
        return dict(status='abstain', reason='source_is_not_text', diagnostics=[], source_sha256=None,
                    complete_supported_syntax=False, compile_failure_proven=False, semantic_edits=0)
    try:
        encoded = code.encode('utf-8')
        source_sha = hashlib.sha256(encoded).hexdigest()
        if len(code) > MAX_CHARS:
            return dict(status='abstain', reason='source_size_limit', diagnostics=[], source_sha256=source_sha,
                        complete_supported_syntax=False, compile_failure_proven=False, semantic_edits=0)
        if len(encoded) > MAX_BYTES:
            return dict(status='abstain', reason='source_byte_limit', diagnostics=[], source_sha256=source_sha,
                        complete_supported_syntax=False, compile_failure_proven=False, semantic_edits=0)
    except UnicodeEncodeError:
        return dict(status='abstain', reason='source_encoding', diagnostics=[], source_sha256=None,
                    complete_supported_syntax=False, compile_failure_proven=False, semantic_edits=0)
    try:
        parsed = SimpleModule(code, scan(code))
        module = parsed.parse()
        findings = []
        for symbol in parsed.symbols.values():
            if symbol['storage'] not in ('reg', 'logic') or symbol['packed'] or symbol['direction'] == 'input':
                continue
            writes = [w for w in parsed.writes if not w['continuous'] and w['variable'] == symbol['name']]
            owners = sorted({w['process'] for w in writes})
            if len(owners) > 1 and any(parsed.processes[i]['clocked'] for i in owners):
                findings.append(dict(variable=symbol['name'], declaration=symbol['declaration'],
                    processes=[parsed.processes[i] for i in owners], assignments=writes,
                    explanation='The same module-scope scalar variable is assigned by distinct always processes, including an edge-triggered process. Review ownership of this variable; source locations alone do not establish a synthesis failure.'))
        return dict(status='source_conflict_needs_review' if findings else 'supported_no_conflict',
                    reason=None, source_sha256=source_sha, module=module, diagnostics=findings,
                    complete_supported_syntax=True, processes=len(parsed.processes),
                    procedural_assignments=sum(not w['continuous'] for w in parsed.writes),
                    compile_failure_proven=False, semantic_edits=0)
    except (Unsupported, RecursionError) as error:
        return dict(status='abstain', reason=str(error) if isinstance(error, Unsupported) else 'nesting_limit',
                    source_sha256=source_sha, diagnostics=[], complete_supported_syntax=False,
                    compile_failure_proven=False, semantic_edits=0)


def render_feedback(result):
    """Bounded factual source-location feedback, never a rewrite or verdict."""
    if result.get('status') != 'source_conflict_needs_review':
        return ''
    parts = ['Source review found assignments to a module-scope scalar variable in separate always processes.']
    shown = 0
    for finding in result['diagnostics']:
        owners = ', '.join(f"{p['kind']} at line {p['start']['line']}, column {p['start']['column']}"
                           + (' (edge-triggered)' if p['clocked'] else '') for p in finding['processes'][:4])
        writes = ', '.join(f"line {w['assignment']['line']}, column {w['assignment']['column']}"
                           for w in finding['assignments'][:8])
        text = f"Variable {finding['variable']}: {owners}; assignments at {writes}."
        if len(finding['processes']) > 4 or len(finding['assignments']) > 8:
            text += ' Additional source locations are retained in the diagnostic record.'
        if len(' '.join(parts)) + len(text) + 300 > MAX_FEEDBACK_CHARS:
            break
        parts.append(text)
        shown += 1
    if shown < len(result['diagnostics']):
        parts.append(f"{len(result['diagnostics']) - shown} additional scalar-variable diagnostics are retained in the source record.")
    parts.append('Review which process should own each variable. This is source-location evidence, not proof of a synthesis failure.')
    return ' '.join(parts)
