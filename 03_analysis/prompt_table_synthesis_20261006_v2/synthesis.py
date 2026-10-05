"""Pure, bounded prompt-table to RTL compiler; experimental and not deployed.

No task ID, candidate, reference, testbench, judge, path, model or native tool is
an input. Only explicit combinational tables are supported. The existing sealed
parser is unchanged; its observation-only waveform admission is narrowed here
rather than treated as proof of stateless behavior.
"""
import hashlib
import itertools
import json
import re

import contract
from reserved_keywords import KEYWORDS

SCHEMA = "prompt_only_table_synthesis_draft_v1"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _require(value, reason):
    if not value:
        raise contract.Abstain(reason)


def _ports_and_body(prompt):
    """Retain the original direction/name/width/declaration order exactly."""
    text = prompt.replace("\r\n", "\n")
    match = contract.HEADER.match(text)
    _require(match is not None, "missing_interface")
    lines = text[match.end():].splitlines()
    ports = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        port = contract.PORT.fullmatch(line.strip())
        if port is None:
            return ports, "\n".join(lines[index:]).strip()
        ports.append(dict(direction=port[1], name=port[2], width=int(port[3] or 1)))
    raise contract.Abstain("missing_table_body")


def synthesize(prompt, interface=""):
    """Return generated RTL or an explicit abstention using only input strings.

    A nonempty separate interface is deliberately unsupported: ignoring it could
    hide a contradictory width, extra output or positional-port obligation.
    Unsupported inputs return no RTL and must use the original generation path.
    """
    result = dict(schema=SCHEMA, emitted=False, reason=None, rtl="",
                  actual_model_requests=0, actual_eda_calls=0,
                  external_io_calls=0, formal_qualification=False)
    if isinstance(prompt, str):
        try:
            result["prompt_sha256"] = _sha(prompt)
        except UnicodeEncodeError:
            return result | dict(reason="unsupported_prompt_encoding")
    if not isinstance(interface, str):
        return result | dict(reason="interface_must_be_string")
    try:
        result["interface_sha256"] = _sha(interface)
    except UnicodeEncodeError:
        return result | dict(reason="unsupported_interface_encoding")
    if interface.strip():
        return result | dict(reason="separate_interface_not_supported")
    parsed = contract.parse_prompt(prompt)
    result["parser_admitted"] = parsed["admitted"]
    if "prompt_sha256" in parsed:
        _require(result["prompt_sha256"] == parsed["prompt_sha256"], "prompt_binding_not_exact")
    if not parsed["admitted"]:
        return result | dict(reason="parser_abstained:" + parsed["reason"])
    try:
        _require(parsed["all_prompt_consumed"], "prompt_not_fully_consumed")
        table = parsed["contract"]
        ports, body = _ports_and_body(prompt)
        inputs = [{k: p[k] for k in ("name", "width")}
                  for p in ports if p["direction"] == "input"]
        outputs = [{k: p[k] for k in ("name", "width")}
                   for p in ports if p["direction"] == "output"]
        _require(inputs == table["input_ports"]
                 and outputs == [table["output_port"]], "interface_not_exact")
        _require(len({p["name"] for p in ports}) == len(ports),
                 "duplicate_port_name")
        _require(all(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", p["name"])
                     and p["name"] not in KEYWORDS for p in ports),
                 "invalid_or_reserved_port_name")
        _require(not any(p["name"].lower() in contract.CONTROL_NAMES
                         for p in inputs), "sequential_control_port")
        _require(len(outputs) == 1 and outputs[0]["width"] == 1,
                 "requires_exactly_one_scalar_output")
        _require(all(type(p["width"]) is int and 1 <= p["width"] <= 4
                     for p in inputs), "input_width_out_of_scope")
        expected_bits = [
            b for p in inputs
            for b in ([p["name"]] if p["width"] == 1 else
                      [f'{p["name"]}[{i}]'
                       for i in range(p["width"] - 1, -1, -1)])
        ]
        _require(expected_bits == table["input_bit_order"]
                 and 1 <= len(expected_bits) <= 4, "input_bit_order_not_exact")
        if table["kind"] == "complete_scalar_waveform":
            _require(body.startswith("The module should implement a combinational circuit."),
                     "waveform_has_no_explicit_combinational_contract")
        else:
            _require(table["kind"] == "karnaugh_map", "unsupported_table_kind")
        labels = {"".join(v) for v in itertools.product("01", repeat=len(expected_bits))}
        rows = {}
        for row in table["rows"]:
            _require(set(row["input_bits"]) == set(expected_bits),
                     "row_inputs_not_exact")
            _require(all(type(row["input_bits"][b]) is int
                         and row["input_bits"][b] in (0, 1)
                         for b in expected_bits), "row_input_not_binary")
            label = "".join(str(row["input_bits"][b]) for b in expected_bits)
            _require(label not in rows, "duplicate_input_assignment")
            _require(type(row["care"]) is bool, "invalid_care_flag")
            if row["care"]:
                _require(type(row["expected"]) is int
                         and row["expected"] in (0, 1), "care_output_not_binary")
            else:
                _require(table["kind"] == "karnaugh_map"
                         and table.get("dontcare_declared")
                         and row["expected"] is None, "undeclared_dontcare")
            rows[label] = row
        _require(set(rows) == labels
                 and table["complete_assignment_count"] == len(labels),
                 "input_domain_not_complete")
        care_count = sum(row["care"] for row in rows.values())
        _require(care_count > 0 and care_count == table["care_assignment_count"],
                 "missing_or_inconsistent_care_obligations")

        output = outputs[0]["name"]
        declarations = []
        for port in ports:
            width = "" if port["width"] == 1 else f'[{port["width"] - 1}:0] '
            mode = "output reg" if port["direction"] == "output" else "input"
            declarations.append(f'    {mode} {width}{port["name"]}')
        rtl = "module TopModule (\n" + ",\n".join(declarations) + "\n);\n"
        rtl += f"    always @* begin\n        case ({{{', '.join(expected_bits)}}})\n"
        for label in sorted(rows):
            value = rows[label]["expected"] if rows[label]["care"] else 0
            rtl += f"            {len(expected_bits)}'b{label}: {output} = 1'b{value};\n"
        # X/Z inputs have no binary table obligation. Preserve an explicitly
        # unknown default instead of inventing a zero-valued extension.
        rtl += f"            default: {output} = 1'bx;\n        endcase\n    end\nendmodule\n"
        return result | dict(
            emitted=True, rtl=rtl, rtl_sha256=_sha(rtl),
            contract_sha256=_sha(_json(table)), interface_ports=ports,
            input_bit_order=expected_bits, kind=table["kind"],
            complete_assignment_count=len(labels), care_assignment_count=care_count,
            dontcare_assignment_count=len(labels) - care_count,
            dontcare_selection="zero_only_for_explicit_dontcare_cells",
            nonbinary_input_behavior="default_unknown; no X/Z table obligation proved",
            all_prompt_consumed=True,
            limits=["Draft pure generation only; native/official correctness is unmeasured.",
                    "Only fully consumed explicit combinational table templates are supported.",
                    "No hidden-task or independent generalization claim."])
    except contract.Abstain as error:
        return result | dict(reason=str(error))
