"""Lossless sparse rendering of a known binary public-spec simulation witness."""
from decimal import Decimal
import hashlib
import re

PATTERN=re.compile(r"FIRST_MISMATCH time_ps=(\d+) load=([01]) data=([0-9a-fA-F]+) previous_q=([0-9a-fA-F]+) bit=(\d+) expected_q_bit=([01]) observed_q_bit=([01])")
LIMITATION="This self-check is derived from the supplied public specification. It is not an official or hidden test and does not prove correctness beyond its exercised cases."
CONSTRAINTS=("Local constraints derived only from the supplied Rule 90 specification: "
    "On a positive clock edge, load=1 requires next_q=data. When load=0, "
    "next_q[0]=previous_q[1], next_q[511]=previous_q[510], and for 1<=i<=510, "
    "next_q[i]=previous_q[i-1] XOR previous_q[i+1]. Expand the candidate's actual "
    "shift/concatenation expression at i=0,1,510,511 and compare each bit with these "
    "constraints before editing. Treat comments as claims to verify. Preserve the "
    "512-bit interface, load priority, and specified clock edge. Return only the complete module.")


def normalize(line,width=512):
    match=PATTERN.fullmatch(line)
    if match is None:
        raise ValueError("Witness is not a complete known binary trace; preserve raw evidence")
    time_ps,load,data,previous,bit,expected,observed=match.groups()
    bit=int(bit)
    if width!=512 or not 0<=bit<width:
        raise ValueError("This frozen representation supports the 512-bit contract only")
    if len(data)!=width//4 or len(previous)!=width//4:
        raise ValueError("Vector width changed; do not truncate or infer missing zeros")
    values=[int(data,16),int(previous,16)]
    set_bits=[[i for i in range(width) if value&(1<<i)] for value in values]
    for value,bits in zip(values,set_bits):
        if sum(1<<i for i in bits)!=value:
            raise ValueError("Sparse vector did not round-trip")
    ns=format(Decimal(time_ps)/Decimal(1000),"f")
    compact=(f"First observed mismatch at {ns} ns: load={load}; "
        f"data has 1 bits at indices {set_bits[0]}, all its other bits are 0; "
        f"previous_q has 1 bits at indices {set_bits[1]}, all its other bits are 0. "
        f"After the positive clock edge, q[{bit}] must be {expected} according to the "
        f"self-check, but was {observed}.")
    return dict(raw_line=line,raw_line_sha256=hashlib.sha256(line.encode()).hexdigest(),
        width=width,time_ps=int(time_ps),time_ns=ns,load=int(load),data_set_bits=set_bits[0],
        previous_set_bits=set_bits[1],bit=bit,expected=int(expected),observed=int(observed),
        round_trip_verified=True,compact=compact)


def messages(checks,mismatches,first):
    common=f"Public-specification self-check, XSim 2026.1. Completed checks={checks} mismatches={mismatches}.\n"
    if mismatches:
        if first is None:raise ValueError("Missing completed counterexample")
        normalized=normalize(first)
        raw=common+first+"\nTime unit in the diagnostic is ps.\n"+LIMITATION
        compact=common+normalized["compact"]+"\n"+LIMITATION
    else:
        if first is not None:raise ValueError("Unexpected failure witness on pass")
        normalized=None;raw=compact=common+"No mismatch in this bounded self-check.\n"+LIMITATION
    return dict(A=raw,B=compact,C=compact+"\n\n"+CONSTRAINTS,normalized=normalized)
