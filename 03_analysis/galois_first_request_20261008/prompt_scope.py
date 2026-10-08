"""Accept only a completely consumed explicit Galois statement; unknown prose abstains."""
import re

def complete(prompt,c):
    if not isinstance(prompt,str) or c.get('status')!='supported':return False
    # The qualified parser has already checked every bullet port and its binding.
    text=' '.join(line.strip() for line in prompt.splitlines() if not line.lstrip().startswith('-'))
    text=re.sub(r'\s+',' ',text).strip()
    module=re.escape(c['module']);out=re.escape(c['output']);width=str(c['width'])
    header=rf'I would like you to implement a module named {module} with the following interface\.'
    defaults=r'(?: All input and output ports are one bit unless otherwise specified\.)?'
    intro=r'(?: A linear feedback shift register is a shift register usually with a few XOR gates to produce the next state of the shift register\.)?'
    definition=(r' A Galois LFSR is one particular arrangement that shifts right, where a bit position with '
        r'a ["\u201c]?tap["\u201d]? is XORed with the LSB output bit\s*\(\s*'+out+
        r'\[0\]\s*\) to produce its next value, while bit positions without a tap shift right unchanged\.')
    length_note=(r'(?: If the taps? positions are carefully chosen, the LFSR can be made to be ["\u201c]maximum-length["\u201d]\. '
        r'A maximum-length LFSR of n bits cycles through 2\*\*n-1 states before repeating \(the all-zero state is never reached\)\.)?')
    taps=rf' The module should implement (?:a|an) {width}-bit (?:maximal-length |maximum-length )?Galois LFSR with taps at bit positions [\d,\s]+(?:and\s+\d+)?\.'
    seed=r"(?:\d+'[hHbBdD][0-9a-fA-F_]+|\d+)"
    target=rf'(?:the output {out}|the LFSR output(?: {out})?)'
    reset=(r' (?:Reset should be (?:active[- ]high synchronous|synchronous active[- ]high), and should reset '
        rf'{target} to {seed}\.|The active[- ]high synchronous reset should reset {target} to {seed}\.)')
    clock=r' Assume all sequential logic is triggered on the positive edge of the clock\.'
    return re.fullmatch(header+defaults+intro+definition+length_note+taps+reset+clock,text,re.I) is not None
