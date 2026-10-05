"""DRAFT prompt-only scalar dual-edge contract and complete observation binding.

No task IDs, context, harness, answers, compiler, framework, or model are inputs.
This bounded grammar abstains on unrecognised prose rather than deleting clauses.
"""
import hashlib
import re


IDENT = r"[A-Za-z_][A-Za-z0-9_$]{0,63}"
KEYWORDS = frozenset(
    "accept_on alias always always_comb always_ff always_latch and assert assign assume automatic before begin bind bins binsof bit break buf bufif0 bufif1 byte case casex casez cell chandle checker class clocking cmos config const constraint context continue cover covergroup coverpoint cross deassign default defparam design disable dist do edge else end endcase endchecker endclass endclocking endconfig endfunction endgenerate endgroup endinterface endmodule endpackage endprimitive endprogram endproperty endsequence endspecify endtable endtask enum event eventually expect export extends extern final first_match for force foreach forever fork forkjoin function generate genvar global highz0 highz1 if iff ifnone ignore_bins illegal_bins implements implies import incdir include initial inout input inside instance int integer interconnect interface intersect join join_any join_none large let liblist library local localparam logic longint macromodule matches medium modport module nand negedge nettype new nexttime nmos nor noshowcancelled not notif0 notif1 null or output package packed parameter pmos posedge primitive priority program property protected pull0 pull1 pulldown pullup pulsestyle_ondetect pulsestyle_onevent pure rand randc randcase randsequence rcmos real realtime ref reg reject_on release repeat restrict return rnmos rpmos rtran rtranif0 rtranif1 s_always s_eventually s_nexttime s_until s_until_with scalared sequence shortint shortreal showcancelled signed small soft solve specify specparam static string strong strong0 strong1 struct super supply0 supply1 sync_accept_on sync_reject_on table tagged task this throughout time timeprecision timeunit tran tranif0 tranif1 tri tri0 tri1 triand trior trireg type typedef union unique unique0 until until_with untyped use uwire var vectored virtual void wait wait_order wand weak weak0 weak1 while wildcard wire with within wone wor xnor xor".split()
)
ROLE_NAMES = ("clock", "reset", "data", "rising", "falling")
SEMANTICS = dict(width=1, clock_edge="rising", reset_kind="asynchronous",
                 reset_active=0, reset_outputs=0, reset_previous_input=0,
                 outputs_active=1, pulse_cycles=1, input_glitch_free=True,
                 input_debounced=True)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(IDENT, value) and value not in KEYWORDS


def _lines(prompt):
    # Only typography/whitespace changes are removed; no behavioral text is dropped.
    text = re.sub(r"(?<![A-Za-z0-9_$])`(" + IDENT + r"|[01])`(?![A-Za-z0-9_$])", r"\1", prompt)
    text = re.sub(r"(?<![A-Za-z0-9_$])\*\*([A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+)*)\*\*(?![A-Za-z0-9_$])", r"\1", text)
    if "`" in text or "**" in text:
        raise ValueError("unpaired or interior contract markup")
    return [" ".join(re.sub(r"^\s*#{1,6}\s*", "", line).split())
            for line in text.splitlines() if line.strip()]


def _module_token(prompt):
    first = next((" ".join(line.split()) for line in prompt.splitlines() if line.strip()), "")
    match = re.match(r"Design a (?:System Verilog|SystemVerilog) module named (\S+) that ", first, re.I)
    if not match:
        return None
    token = match[1]
    # The public source has one opening double quote before a paired code span.
    # Preserve that original spelling and renamed variants; arbitrary broken quotes
    # or unpaired code spans are not silently normalized into a native name.
    wrappers = (("", ""), ("`", "`"), ('"', '"'), ("'", "'"),
                ('"`', '`"'), ("'`", "`'"), ('"`', '`'))
    for opening, closing in wrappers:
        m = re.fullmatch(re.escape(opening) + "(" + IDENT + ")" + re.escape(closing), token)
        if m:
            return m[1]
    return None


def _literal(identifier):
    return "(?-i:" + re.escape(identifier) + ")"


def parse(prompt):
    """Return supported/abstain/skip from complete public input.prompt only."""
    if not isinstance(prompt, str):
        raise TypeError("prompt must be text")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def reject(reason, status="abstain"):
        return dict(status=status, reason=reason, prompt_sha256=digest)

    if not re.search(r"\bedge(?:s)?\b", prompt, re.I):
        return reject("no_edge_description", "skip")
    if len(prompt) > 32768 or "\x00" in prompt:
        return reject("invalid_prompt_size_or_nul")
    try:
        lines = _lines(prompt)
    except ValueError:
        return reject("unpaired_or_interior_markup")
    if len(lines) != 16:
        return reject("incomplete_or_extra_contract_clauses")
    intro = (r'Design a (?:System Verilog|SystemVerilog) module named ["\']?'
             rf'(?P<module>{IDENT})["\']? that detects both positive and negative edges '
             r'on a glitch-free and debounced input signal\. The module should output a '
             r'signal indicating the detection of a positive or negative edge\. Each detection '
             r'signal should be asserted for one clock cycle when an edge is detected\. The '
             r'module should also incorporate asynchronous reset functionality\.')
    match = re.fullmatch(intro, lines[0], re.I)
    if not match or not _identifier(match["module"]) or _module_token(prompt) != match["module"]:
        return reject("unsupported_complete_intro_or_module")
    if [line.casefold() for line in (lines[1], lines[2], lines[6], lines[9], lines[13])] != [
            "input/output specifications", "inputs:", "outputs:",
            "behavioral definition", "reset behavior"]:
        return reject("unsupported_interface_or_behavior_sections")

    roles = {}
    inputs = {
        "clock": rf'- (?P<port>{IDENT}): (?:Single-bit |Scalar |1-bit )?Clock signal \(active on rising edge\)\.',
        "reset": rf'- (?P<port>{IDENT}): (?:Single-bit |Scalar |1-bit )?Asynchronous reset signal \(active low\)\.',
        "data": rf'- (?P<port>{IDENT}): (?:Glitch-free, debounced|Debounced, glitch-free) (?:single-bit |scalar |1-bit )?signal whose edges are to be detected\.',
    }
    for line in lines[3:6]:
        matches = [(role, re.fullmatch(pattern, line, re.I)) for role, pattern in inputs.items()]
        matches = [(role, m) for role, m in matches if m]
        if len(matches) != 1 or matches[0][0] in roles:
            return reject("ambiguous_or_unsupported_input_roles")
        role, m = matches[0]
        roles[role] = m["port"]
    data = _literal(roles["data"])
    for line in lines[7:9]:
        m = re.fullmatch(rf'- (?P<port>{IDENT}): Asserted for one clock cycle when a '
                         rf'(?P<edge>positive|negative) edge is detected on {data}\.', line, re.I)
        if not m:
            return reject("incomplete_or_unsupported_separate_pulse_outputs")
        role = "rising" if m["edge"].casefold() == "positive" else "falling"
        if role in roles:
            return reject("ambiguous_separate_output_roles")
        roles[role] = m["port"]
    if set(roles) != set(ROLE_NAMES) or not all(_identifier(v) for v in roles.values()) or len(set(roles.values())) != 5:
        return reject("invalid_reserved_or_duplicate_ports")
    expected_behaviors = [
        rf'- When the module detects a positive edge \(rising transition\) on {data}, the output {_literal(roles["rising"])} should be asserted high for one clock cycle\.',
        rf'- When the module detects a negative edge \(falling transition\) on {data}, the output {_literal(roles["falling"])} should be asserted high for one clock cycle\.',
    ]
    remaining = list(expected_behaviors)
    for line in lines[10:12]:
        matches = [pattern for pattern in remaining if re.fullmatch(pattern, line, re.I)]
        if len(matches) != 1:
            return reject("conflicting_or_incomplete_edge_behavior")
        remaining.remove(matches[0])
    if not re.fullmatch(rf'- The design assumes that {data} is glitch-free and debounced, so no additional debouncing logic is required\.', lines[12], re.I):
        return reject("unsupported_or_negated_input_assumption")
    if not re.fullmatch(
            rf'- When the asynchronous reset \({_literal(roles["reset"])}\) is active \(low\), all outputs '
            rf'\({_literal(roles["rising"])} and {_literal(roles["falling"])}\) should be reset to 0, '
            r'and internal state should be cleared\.', lines[14], re.I):
        return reject("incomplete_or_conflicting_full_async_reset")
    if not re.fullmatch(r'- When the reset is de-asserted, normal edge detection should resume\.', lines[15], re.I):
        return reject("unknown_reset_release_behavior")
    rows = _schedule()
    return dict(status="supported", family="native_scalar_dual_edge_async_reset",
                prompt_sha256=digest, module=match["module"], roles=roles,
                **SEMANTICS, observations=rows, checks=len(rows),
                scope="bounded complete public prose; zero-release priming, held/changed data, both outputs and low-clock asynchronous reset")


def _schedule():
    """Every scored low-clock, positive-clock, and negative-clock observation."""
    rows = []
    clock, reset_n, data, remembered, rise, fall, time_ns, cycle = 0, 1, 0, 0, 0, 0, 1, 0

    def event(phase, **changes):
        nonlocal clock, reset_n, data, remembered, rise, fall, time_ns, cycle
        old_clock, before = clock, remembered
        clock = changes.get("clock", clock)
        reset_n = changes.get("reset_n", reset_n)
        data = changes.get("input", data)
        if reset_n == 0:
            remembered, rise, fall = 0, 0, 0
        elif old_clock == 0 and clock == 1:
            rise, fall = int(before == 0 and data == 1), int(before == 1 and data == 0)
            remembered = data
            cycle += 1
        time_ns += 1
        rows.append(dict(index=len(rows), phase=phase, time_ns=time_ns, cycle=cycle,
                         clock=clock, reset_n=reset_n, input=data,
                         previous_input=before, remembered_input=remembered,
                         expected_rising=rise, expected_falling=fall,
                         changes=changes))

    def prime(label):
        for n in range(2):
            event(f"{label}_posedge_{n}", clock=1)
            event(f"{label}_negedge_{n}", clock=0)

    def sample(label, value):
        event(label + "_setup", input=value)
        event(label + "_posedge", clock=1)
        event(label + "_negedge", clock=0)

    event("initial_async_reset", reset_n=0)
    event("reset_high_input", input=1)
    event("reset_posedge", clock=1)
    event("reset_negedge", clock=0)
    event("reset_zero_input", input=0)
    event("release_zero", reset_n=1)
    prime("initial_prime")
    sample("rise_before_reset", 1)
    event("async_reset_during_rising_pulse", reset_n=0)
    event("reset_clear_high_memory", input=0)
    event("release_zero_after_high_memory", reset_n=1)
    prime("second_prime")
    for n, value in enumerate((1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 0)):
        sample(f"transition_{n}", value)
    sample("rise_before_falling_reset", 1)
    sample("fall_before_reset", 0)
    event("async_reset_during_falling_pulse", reset_n=0)
    event("reset_recheck_zero", input=0)
    event("release_zero_after_falling", reset_n=1)
    prime("final_prime")
    return rows


def _strict_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(_strict_equal(actual[k], expected[k]) for k in expected)
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_strict_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _validate(c):
    if not isinstance(c, dict) or c.get("status") != "supported":
        raise ValueError("supported contract required")
    roles = c.get("roles")
    if not _identifier(c.get("module")) or not isinstance(roles, dict) or set(roles) != set(ROLE_NAMES):
        raise ValueError("invalid module or roles")
    if not all(_identifier(roles[k]) for k in ROLE_NAMES) or len(set(roles.values())) != 5:
        raise ValueError("invalid or ambiguous native role identifiers")
    if c.get("family") != "native_scalar_dual_edge_async_reset" or any(not _strict_equal(c.get(k), v) for k, v in SEMANTICS.items()):
        raise ValueError("unsupported or mutated semantics")
    if not re.fullmatch(r"[a-f0-9]{64}", c.get("prompt_sha256", "")):
        raise ValueError("invalid public prompt binding")
    rows = _schedule()
    if not _strict_equal(c.get("observations"), rows) or not _strict_equal(c.get("checks"), len(rows)):
        raise ValueError("mutated or incomplete observation plan")


def _run(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32,64}", run_id):
        raise ValueError("explicit 32-64 lowercase hex run binding required")


def _prefix(c, run_id):
    return f'contract={c["prompt_sha256"]} run={run_id}'


def _observation_prefix(row):
    keys = ("index", "phase", "time_ns", "cycle", "clock", "reset_n", "input",
            "previous_input", "remembered_input", "expected_rising", "expected_falling")
    return "NRC_OBS " + " ".join(f"{k}={row[k]}" for k in keys)


def render_tb(c, run_id):
    """Generate a native-name testbench; emits both actual outputs on every row."""
    _validate(c)
    _run(run_id)
    roles, rows = c["roles"], c["observations"]
    probe = "_nrc_probe_" + hashlib.sha256((c["module"] + run_id).encode()).hexdigest()[:16]
    if probe == c["module"]:
        raise ValueError("probe module collision")
    ports = dict(clock="_nrc_clock", reset="_nrc_reset_n", data="_nrc_data",
                 rising="_nrc_rise", falling="_nrc_fall")
    links = ",".join(f".{roles[k]}({ports[k]})" for k in ROLE_NAMES)
    lines = ["`timescale 1ns/1ps", f"module {probe};",
             "reg _nrc_clock, _nrc_reset_n, _nrc_data;",
             "wire _nrc_rise, _nrc_fall;",
             f'{c["module"]} _nrc_dut({links});',
             "integer _nrc_checks=0, _nrc_mismatches=0;", "initial begin",
             "_nrc_clock=0; _nrc_reset_n=1; _nrc_data=0; #1;",
             f'$display("NRC_BEGIN {_prefix(c, run_id)} observations={c["checks"]}");']
    for row in rows:
        assignment = " ".join(f"{ports[{'reset_n':'reset','input':'data'}.get(k,k)]}={v};"
                              for k, v in row["changes"].items())
        lines.extend([assignment + " #1;", "_nrc_checks=_nrc_checks+1;",
                      f'$display("{_observation_prefix(row)} observed_rising=%b observed_falling=%b",_nrc_rise,_nrc_fall);'])
        for role, wire in (("rising", "_nrc_rise"), ("falling", "_nrc_fall")):
            expected = row["expected_" + role]
            lines.extend([f"if({wire} !== 1'b{expected}) begin",
                          f'if(_nrc_mismatches==0) $display("NRC_FIRST index={row["index"]} output={roles[role]} expected={expected} observed=%b",{wire});',
                          "_nrc_mismatches=_nrc_mismatches+1; end"])
    lines.extend([f'$display("NRC_END {_prefix(c, run_id)} observations=%0d mismatches=%0d",_nrc_checks,_nrc_mismatches);',
                  f'if(_nrc_checks!={c["checks"]}) $fatal(1,"CHECK_COUNT_INVALID");',
                  'if(_nrc_mismatches!=0) $fatal(1,"SEMANTIC_MISMATCH");',
                  "$finish; end", 'initial begin #10000; $fatal(1,"WATCHDOG_EXPIRED"); end',
                  "endmodule", ""])
    return "\n".join(lines)


def observations(log, c, run_id):
    """Validate a complete transcript and retain every both-output actual value.

    This validates protocol consistency, not native command/source provenance.
    A caller must separately bind actual compiler argv, code, logs and return code.
    """
    _validate(c)
    _run(run_id)
    if not isinstance(log, str) or len(log) > 1024 * 1024:
        raise ValueError("invalid transcript type or size")
    protocol = [line for line in log.splitlines() if "NRC_" in line]
    begin = f'NRC_BEGIN {_prefix(c, run_id)} observations={c["checks"]}'
    if not protocol or protocol[0] != begin:
        raise ValueError("missing or spoofed begin binding")
    offset, mismatches, first, actual = 1, 0, None, []
    for row in c["observations"]:
        if offset >= len(protocol):
            raise ValueError("truncated observation sequence")
        match = re.fullmatch(re.escape(_observation_prefix(row)) +
                             r" observed_rising=([01xz]) observed_falling=([01xz])", protocol[offset])
        if not match:
            raise ValueError("reordered, incomplete, spoofed or malformed observation")
        offset += 1
        failures = []
        for role, value in zip(("rising", "falling"), match.groups()):
            expected = row["expected_" + role]
            if value != str(expected):
                failures.append(roles_output := c["roles"][role])
                mismatches += 1
                if first is None:
                    first = dict(index=row["index"], output=roles_output,
                                 expected=expected, observed=value)
                    marker = (f'NRC_FIRST index={row["index"]} output={roles_output} '
                              f'expected={expected} observed={value}')
                    if offset >= len(protocol) or protocol[offset] != marker:
                        raise ValueError("missing or spoofed first mismatch marker")
                    offset += 1
        actual.append(dict(**{k: v for k, v in row.items() if k != "changes"},
                           rising_output=c["roles"]["rising"], falling_output=c["roles"]["falling"],
                           observed_rising=match[1], observed_falling=match[2],
                           mismatched_outputs=failures))
    end = f'NRC_END {_prefix(c, run_id)} observations={c["checks"]} mismatches={mismatches}'
    if offset != len(protocol) - 1 or protocol[-1] != end:
        raise ValueError("missing, duplicate, spoofed or inconsistent end/result")
    return dict(status="semantic_pass" if mismatches == 0 else "semantic_mismatch",
                prompt_sha256=c["prompt_sha256"], run_id=run_id,
                transcript_sha256=hashlib.sha256(log.encode("utf-8")).hexdigest(),
                module=c["module"], checks=c["checks"], mismatches=mismatches,
                first=first, observations=actual,
                integrity_scope="complete protocol consistency; native provenance requires external receipts")


def counterexample(log, c, run_id):
    """Derive a factual first mismatch with complete bound observations retained."""
    result = observations(log, c, run_id)
    if result["first"] is None:
        raise ValueError("no actual mismatch in complete transcript")
    row = result["observations"][result["first"]["index"]]
    return dict(**row, first_output=result["first"]["output"],
                first_expected=result["first"]["expected"],
                first_observed=result["first"]["observed"],
                complete_observations=result["observations"],
                checks=result["checks"], mismatches=result["mismatches"],
                prompt_sha256=result["prompt_sha256"], run_id=run_id,
                transcript_sha256=result["transcript_sha256"],
                integrity_scope=result["integrity_scope"])
