"""Pure complete one-hot graph compilation, with OR semantics for multi-hot inputs.
No task identity, prior answer, reference, candidate, path or service is an input.
Unknown prose, incomplete graph and contradictory interface cause abstention.
"""
import hashlib
import json
import re
from reserved_keywords import KEYWORDS

ID = r"[A-Za-z_][A-Za-z_0-9]*"
SCHEMA = "prompt_only_complete_onehot_graph_v1"

class Abstain(ValueError):
    pass

def require(value, why):
    if not value:
        raise Abstain(why)

def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def safe(name):
    return bool(re.fullmatch(ID, name)) and name not in KEYWORDS

def clean(text):
    require(isinstance(text, str) and len(text) <= 65536 and text.isascii(),
            "unsupported_text")
    text = text.replace("\r\n", "\n")
    require(not any(ord(c) < 32 and c not in "\n\t" for c in text),
            "unsupported_control_character")
    return text

def interface_ports(text, module):
    """Consume an empty-body ANSI interface; no permissive comment stripping."""
    m = re.fullmatch(r"\s*module\s+(" + ID + r")\s*\((.*?)\)\s*;\s*endmodule\s*", text, re.S)
    require(m is not None and m[1] == module, "unsupported_separate_interface")
    ports = []
    for token in m[2].split(","):
        p = re.fullmatch(r"\s*(input|output)\s+(?:wire\s+)?(?:\[([0-9]+)\s*:\s*0\]\s*)?(" + ID + r")\s*", token)
        require(p is not None, "unsupported_interface_port")
        ports.append(dict(direction=p[1], name=p[3], width=int(p[2])+1 if p[2] else 1))
    return ports

def parse(prompt, interface):
    text = clean(prompt)
    clean(interface)
    header = re.match(r"\AI would like you to implement a module named (" + ID +
        r") with the following\s+interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*", text)
    require(header is not None and safe(header[1]), "unsupported_preamble")
    module = header[1]
    lines = text[header.end():].splitlines()
    ports, consumed = [], 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        p = re.fullmatch(r"\s*-\s*(input|output)\s+(" + ID + r")(?:\s+\(([1-9][0-9]*) bits\))?\s*", line)
        if p is None:
            consumed = index
            break
        ports.append(dict(direction=p[1], name=p[2], width=int(p[3] or 1)))
    require(consumed > 0 and 4 <= len(ports) <= 7, "missing_body_or_ports")
    require(len({p["name"] for p in ports}) == len(ports) and
            all(safe(p["name"]) for p in ports), "unsafe_or_duplicate_port")
    inputs = [p for p in ports if p["direction"] == "input"]
    outputs = [p for p in ports if p["direction"] == "output"]
    require(len(inputs) == 2 and len([p for p in inputs if p["width"] == 1]) == 1,
            "one_scalar_and_one_state_required")
    state = next(p for p in inputs if p["width"] > 1)
    inp = next(p for p in inputs if p["width"] == 1)
    n = state["width"]
    require(2 <= n <= 16 and len([p for p in outputs if p["width"] == n]) == 1,
            "state_width_or_next_state")
    nxt = next(p for p in outputs if p["width"] == n)
    scalar = [p for p in outputs if p["width"] == 1]
    require(len(scalar) == len(outputs)-1 and 1 <= len(scalar) <= 4,
            "scalar_outputs_required")
    if interface.strip():
        require(interface_ports(interface, module) == ports, "interface_disagrees")
    body = " ".join("\n".join(lines[consumed:]).split())
    description, sep, suffix = body.partition("Suppose this state machine ")
    require(bool(sep), "missing_encoding_contract")
    g = re.fullmatch(r"Given the (?:follow|following) state machine with 1 input and ([1-4]) outputs \(the outputs are given as \"\((" +
        ID + r"(?:, " + ID + r")*)\)\"\): (.*)", description.strip())
    require(g is not None and int(g[1]) == len(scalar) and
            g[2].split(", ") == [p["name"] for p in scalar], "graph_output_binding")
    rows = []
    remainder = g[3]
    row = re.compile(r"(" + ID + r") \(([01](?:, [01])*)\) --([01])--> (" + ID + r")(?: |$)")
    while remainder:
        m = row.match(remainder)
        require(m is not None, "unconsumed_graph_text")
        bits = tuple(map(int, m[2].split(", ")))
        require(len(bits) == len(scalar), "output_tuple_width")
        rows.append((m[1], bits, int(m[3]), m[4]))
        require(len(rows) <= 2*n, "extra_graph_rows")
        remainder = remainder[m.end():]
    require(len(rows) == 2*n, "incomplete_graph")
    s, t = re.escape(state["name"]), re.escape(nxt["name"])
    prefix = (r"uses one-hot encoding, where " + s + r"\[0\] through " + s +
        r"\[([0-9]+)\] correspond to the states (" + ID + r") (?:though|through) (" +
        ID + r"), respectively\. The outputs are zero unless otherwise specified\. The " +
        t + r"\[0\] through " + t + r"\[([0-9]+)\] correspond to the transition to next states (" +
        ID + r") (?:though|through) (" + ID + r")\. For example, The " + t +
        r"\[([0-9]+)\] is set to 1 when the next state is (" + ID +
        r") , otherwise, it is set to 0\. ")
    m = re.match(prefix, suffix)
    require(m is not None and int(m[1]) == int(m[4]) == n-1 and
            m[2] == m[5] and m[3] == m[6], "invalid_bit_mapping")
    first = re.fullmatch(r"(" + ID + r"?)([0-9]+)", m[2])
    require(first is not None and first[2] == "0", "mapping_must_start_zero")
    labels = [first[1] + str(i) for i in range(n)]
    require(labels[-1] == m[3] and all(safe(x) for x in labels) and
            int(m[7]) < n and labels[int(m[7])] == m[8], "mapping_example_disagrees")
    rest = suffix[m.end():]
    mult = re.match(r"Here, the input " + s + r"\[([0-9]+):0\] can be a (?:combinational|combination) of multiple states, and the " +
        re.escape(module) + r" is expected to response\. For example: When the " + s +
        r"\[([0-9]+):0\] = ([0-9]+)'b([01]+), " + s + r"\[([0-9]+)\] == 1, and " +
        s + r"\[([0-9]+)\] == 1, the states includes (" + ID + r"), and (" + ID + r") states\. ", rest)
    require(mult is not None, "explicit_multihot_contract_required")
    hi, hi2, width, binary, a, b = int(mult[1]), int(mult[2]), int(mult[3]), mult[4], int(mult[5]), int(mult[6])
    require(hi == hi2 == n-1 and width == len(binary) == n and
            0 <= a < n and 0 <= b < n and a != b and
            int(binary, 2) == (1 << a) | (1 << b) and
            mult[7] == labels[a] and mult[8] == labels[b], "multihot_example_disagrees")
    rest = rest[mult.end():]
    count_word = {1:"one", 2:"two", 3:"three", 4:"four"}[len(scalar)]
    tail = ("The module should implement the state transition logic and output logic portions of the state machine (but not the state flip-flops). You are given the current state in " +
            state["name"] + "[" + str(n-1) + ":0] and must implement " + nxt["name"] +
            "[" + str(n-1) + ":0] and the " + count_word + " outputs.")
    require(rest == tail, "unconsumed_or_contradictory_tail")
    transitions, output_masks = {}, {}
    for src, bits, value, dst in rows:
        require(src in labels and dst in labels and (src, value) not in transitions,
                "unknown_or_duplicate_transition")
        require(src not in output_masks or output_masks[src] == bits, "conflicting_state_output")
        transitions[src, value] = labels.index(dst)
        output_masks[src] = bits
    require(set(transitions) == {(label,v) for label in labels for v in (0,1)},
            "transition_coverage")
    return dict(module=module, ports=ports, input=inp["name"], state=state["name"],
        next_state=nxt["name"], outputs=[p["name"] for p in scalar], labels=labels,
        transitions=[[labels.index(src), value, dst] for (src,value), dst in sorted(transitions.items())],
        output_masks=[list(output_masks[label]) for label in labels],
        semantics="bitwise_or_of_all_active_states_no_state_storage", all_prompt_consumed=True)

