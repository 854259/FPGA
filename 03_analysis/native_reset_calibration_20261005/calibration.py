"""Pure helpers for generated research calibration; never execute native tools."""
import hashlib
import json
import re
from pathlib import Path

import native_reset_contract as native

PARSER_SHA = "94bcb3b86b7bf1209c5a2348f9d3da5e9c74136e15f77cbdeeedc838ee5fa43d"
DATASET_SHA = "cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857"
ORIGINAL_PROMPT_SHA = "b55622d75576a72d6a5b321a592cc78c2a554dbc0da9e385d35b519fb6f535dc"
ORDER = ("positive", "reset_ignored", "synchronous_reset", "history_sync_only",
         "clear_rising_only", "clear_falling_only", "constant_zero", "constant_one",
         "swapped_edges", "two_cycle_pulse", "one_cycle_late", "negedge_sample",
         "failure_propagation", "positive_renamed")
SENTINEL = "OWN_NATIVE_RESET_FAILURE_PROPAGATION"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".pending")
    tmp.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    tmp.replace(path)


def contained(root, name):
    if not isinstance(name, str) or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("unsafe relative evidence path")
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("evidence path escapes owned root")
    return path


def planned_tb(contract, control):
    tb = native.render_tb(contract, control["run_id"])
    if control["intent"] == "sentinel":
        if tb.count("$finish; end") != 1:
            raise ValueError("ambiguous sentinel insertion")
        tb = tb.replace("$finish; end", f'$display("{SENTINEL}"); $fatal(1,"{SENTINEL}");\n$finish; end')
    return tb


def validate_control_metadata(control, index):
    intent = "positive" if ORDER[index] in ("positive", "positive_renamed") else "sentinel" if ORDER[index] == "failure_propagation" else "wrong"
    if control["index"] != index or control["label"] != ORDER[index] or control["intent"] != intent or control["generated_research_test"] is not True or control["original_harness"] is not False:
        raise ValueError("fixed control order/intent/provenance changed")
    if type(control["expected_vvp_rc"]) is not int or control["expected_vvp_rc"] != (0 if intent == "positive" else 1) or control["expected_semantic_status"] != ("semantic_mismatch" if intent == "wrong" else "semantic_pass"):
        raise ValueError("fixed control expected outcome changed")


def validate_renamed_prompt(original, renamed, old_contract, new_contract):
    pairs = [(old_contract["module"], new_contract["module"])] + [
        (old_contract["roles"][role], new_contract["roles"][role]) for role in native.ROLE_NAMES]
    if any(old == new for old, new in pairs):
        raise ValueError("module and all five roles must be renamed")
    expected = original.decode("utf-8")
    for old, new in pairs:
        expected = expected.replace(old, new)
    if expected.encode("utf-8") != renamed:
        raise ValueError("renamed prompt changed non-name semantics")


def validate_private(root):
    root = Path(root)
    if sha((root / "native_reset_contract.py").read_bytes()) != PARSER_SHA:
        raise ValueError("delivered parser byte binding changed")
    private = read(root / "raw_evidence/CONTROLS.json")
    if not private.get("generated_research_test") or private.get("original_harness") is not False:
        raise ValueError("generated research provenance required")
    if private.get("dataset_sha256") != DATASET_SHA or private.get("parser_sha256") != PARSER_SHA:
        raise ValueError("public prompt/parser provenance changed")
    controls = private.get("controls", [])
    if tuple(c["label"] for c in controls) != ORDER or len(controls) != 14:
        raise ValueError("all14 fixed controls required")
    if [c["intent"] for c in controls].count("positive") != 2 or [c["intent"] for c in controls].count("wrong") != 11 or [c["intent"] for c in controls].count("sentinel") != 1:
        raise ValueError("control intents changed")
    cases = []
    for index, control in enumerate(controls):
        validate_control_metadata(control, index)
        prompt = contained(root, control["prompt_path"]).read_bytes()
        rtl = contained(root, control["rtl_path"]).read_bytes()
        if sha(prompt) != control["prompt_sha256"] or sha(rtl) != control["rtl_sha256"]:
            raise ValueError("public prompt/control source bytes changed")
        if control["label"] != "positive_renamed" and sha(prompt) != ORIGINAL_PROMPT_SHA:
            raise ValueError("original public input.prompt byte binding changed")
        c = native.parse(prompt.decode("utf-8"))
        if c["status"] != "supported" or c["module"] != control["module"] or c["roles"] != control["roles"] or c["checks"] != 69:
            raise ValueError("complete prompt-native binding required")
        tb = planned_tb(c, control)
        if sha(tb.encode("utf-8")) != control["tb_sha256"] or contained(root, control["tb_path"]).read_bytes() != tb.encode("utf-8"):
            raise ValueError("generated test source changed")
        probe = re.search(r"^module ([A-Za-z_][A-Za-z0-9_$]*);$", tb, re.M)
        if not probe or probe[1] != control["probe_module"]:
            raise ValueError("testbench top changed")
        expected_intent = "positive" if control["label"] in ("positive", "positive_renamed") else "sentinel" if control["label"] == "failure_propagation" else "wrong"
        if control["intent"] != expected_intent or control["expected_vvp_rc"] != (0 if expected_intent == "positive" else 1):
            raise ValueError("control expected outcome changed")
        cases.append((control, c, rtl, tb.encode("utf-8")))
    validate_renamed_prompt(contained(root, controls[0]["prompt_path"]).read_bytes(),
                            contained(root, controls[-1]["prompt_path"]).read_bytes(), cases[0][1], cases[-1][1])
    return private, cases


def classify(control, contract, stdout, stderr, returncode):
    """Complete transcript required; unknown/error outcomes are never retried."""
    if type(returncode) is not int or returncode not in (0, 1):
        raise ValueError("unknown native return code; preserve evidence, never retry")
    parsed = native.observations(stdout, contract, control["run_id"])
    marker_lines = [line for line in stdout.splitlines() if line == SENTINEL]
    intent = control["intent"]
    if intent == "sentinel":
        matched = returncode == 1 and parsed["mismatches"] == 0 and len(marker_lines) == 1
        consistent = returncode == 1 and (parsed["mismatches"] > 0 or len(marker_lines) == 1)
    else:
        consistent = returncode == (1 if parsed["mismatches"] else 0) and not marker_lines
        matched = consistent and (parsed["mismatches"] == 0 if intent == "positive" else parsed["mismatches"] > 0)
    ce = native.counterexample(stdout, contract, control["run_id"]) if parsed["mismatches"] else None
    return dict(control_matched=matched, returncode_consistent=consistent,
                false_acceptance=intent == "wrong" and parsed["mismatches"] == 0 and returncode == 0,
                parsed=parsed, counterexample=ce, sentinel_marker_count=len(marker_lines),
                stdout_sha256=sha(stdout.encode("utf-8")), stderr_sha256=sha(stderr.encode("utf-8")))
