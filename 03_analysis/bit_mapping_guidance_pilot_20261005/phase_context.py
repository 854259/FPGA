"""AMD-only constructed temporal-context controls; zero model calls, no adoption."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

ORIGINAL_HASHES = {
    "edge_contract.py": "cacb6efa0de8f3bd46acefe789c35bbb53fa007bd4d6476fb97c6251ad0888cd",
    "edge_feedback.py": "2ddb6331ff00ffb44cc4874f176d322b026549069da3036f20bec994d81571b7",
    "point_feedback.py": "34ceaad9d289eafd937e4cb16f0979d8998e93affaccc7c150bca5a552d1573c",
    "reserved_keywords.py": "3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e",
}
PAIRED_SHA = "78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c"
TOOLS_SHA = "b0864aea493587c3fef1ff156b4fa49d52bd2ee712e9f28f94909d9e69252818"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def instrument_tb(original, contract):
    """Add observations without changing any original stimulus/check line."""
    lines, index = [], 0
    for line in original.splitlines(keepends=True):
        lines.append(line)
        if line.strip() == "_edgecheck_checks=_edgecheck_checks+1;":
            row = contract["observations"][index]
            lines.append('$display("EDGE_TRACE step=%d phase=%s expected=%x observed=%%h",%s);\n' %
                         (row["step"], row["phase"], row["expected"], contract["roles"]["output"]))
            index += 1
    assert index == contract["checks"]
    text = "".join(lines)
    assert "".join(x for x in text.splitlines(keepends=True) if not x.startswith('$display("EDGE_TRACE ')) == original
    return text


def context(log, contract, edge):
    """Bind every observed row and first mismatch before selecting one temporal group."""
    pattern = r"^EDGE_TRACE step=(\d+) phase=(stable|positive|cycle) expected=([0-9a-f]+) observed=([0-9a-fxz]+)\s*$"
    matches = re.findall(pattern, log, re.M)
    assert len(matches) == sum(x.startswith("EDGE_TRACE") for x in log.splitlines()) == contract["checks"]
    rows = []
    for item, expected in zip(matches, contract["observations"]):
        step, phase, value, observed = item
        assert (int(step), phase, int(value, 16)) == (expected["step"], expected["phase"], expected["expected"])
        assert len(observed) <= (contract["width"] + 3) // 4
        unknown = bool(re.search("[xz]", observed))
        assert unknown or int(observed, 16) < 2**contract["width"]
        rows.append(dict(**expected, observed_hex=observed,
                         mismatch=unknown or int(observed, 16) != expected["expected"]))
    summary = re.findall(r"^R2_PROBE_RESULT task=[A-Za-z][A-Za-z0-9_]* checks=(\d+) mismatches=(\d+)\s*$", log, re.M)
    assert len(summary) == 1
    assert tuple(map(int, summary[0])) == (len(rows), sum(x["mismatch"] for x in rows))
    mismatches = [x for x in rows if x["mismatch"]]
    if not mismatches:
        assert not any(x.startswith("EDGE_FIRST") for x in log.splitlines())
        return rows, None
    first = edge.counterexample(log, contract)
    observed = mismatches[0]
    assert all(first[k] == observed[k] for k in observed if k != "mismatch")
    group = [x for x in rows if x["step"] == first["step"]]
    return rows, dict(first=first, observations=group, mismatches=len(mismatches))


def render_feedback(contract, bound, original_feedback):
    if bound is None:
        return ""
    result = dict(failure_kind="semantic_mismatch", mismatches=bound["mismatches"], checks=contract["checks"])
    old = original_feedback.render(contract, result, bound["first"])
    labels = dict(stable="before a clock transition, after applying the input",
                  positive="after the specified positive clock edge", cycle="after one complete clock cycle")
    observations = [labels[x["phase"]] + ": expected 0x" + format(x["expected"], "x") +
                    ", observed 0x" + x["observed_hex"] for x in bound["observations"]]
    return old + " Related observations at the same sequence step and input history: " + "; ".join(observations) + "."


def prompt(width, kind, roles):
    clock, signal, output = roles
    interface = ("I would like you to implement a module named TopModule with the following interface. "
                 "All input and output ports are one bit unless otherwise specified.\n"
                 f"- input {clock}\n- input {signal} ({width} bits)\n- output {output} ({width} bits)\n")
    if kind == "any":
        return interface + (f"Implement a module that for each bit in an {width}-bit input vector, detect when the input signal changes "
            f"from one clock cycle to the next (detect any edge). The output bit of {output} should be set to 1 the cycle after "
            "the input bit has 0 to 1 or 1 to 0 transition occurs. Assume all sequential logic is triggered on the positive edge of the clock.")
    return interface + (f"The module should examine each bit in an {width}-bit vector and detect when the input signal changes "
        "from 0 in one clock cycle to 1 the next (similar to positive edge detection). The output bit should be set the cycle after a 0 to 1 transition occurs.")


def design(width, kind, roles, variant):
    clock, signal, output = roles
    registered = variant.startswith("registered_")
    expr = f"({signal} ^ history)" if kind == "any" else f"({signal} & ~history)"
    text = f"module TopModule(input wire {clock}, input wire [{width-1}:0] {signal}, output {'reg' if registered else 'wire'} [{width-1}:0] {output});\n"
    if variant == "zero":
        return text + f"assign {output} = {width}'d0;\nendmodule\n"
    text += f"reg [{width-1}:0] history;\n"
    polarity = "negedge" if variant == "registered_negative" else "posedge"
    text += f"always @({polarity} {clock}) begin\n"
    if registered:
        text += f"{output} <= {expr};\n"
    text += f"history <= {signal};\nend\n"
    if not registered:
        text += f"assign {output} = {expr};\n"
    return text + "endmodule\n"


def run(a):
    assert sys.platform == "linux" and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    assert sha(a.paired) == PAIRED_SHA and sha(a.toolchain_manifest) == TOOLS_SHA
    for name, digest in ORIGINAL_HASHES.items():
        assert sha(a.original_dir / name) == digest
    sys.path.insert(0, str(a.original_dir))
    import edge_contract as edge
    import edge_feedback as original_feedback
    spec = importlib.util.spec_from_file_location("phase_owned", a.paired)
    paired = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paired)
    paired.check_resource(a.resource_check, a.kit, first=True)
    tools = json.loads(a.toolchain_manifest.read_text())
    prefix = Path(tools["prefix"])
    def verify_tools():
        assert {str(p.relative_to(prefix)): sha(p) for p in prefix.rglob("*") if p.is_file()} == tools["files"]
        assert all(sha(a.original_dir / n) == h for n, h in ORIGINAL_HASHES.items())
    verify_tools()
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    report = dict(schema="temporal_phase_context_controls_v1", complete=False, source_commit=a.source_commit,
        model_calls=0, independent_tasks=0, full_batch_complete=False, actual_compile=0, actual_sim=0,
        controls=[], ambiguity_witnesses=[], invalid_trace_rejections=0, error=None)
    def publish(phase):
        report.update(phase=phase, elapsed_s=time.monotonic()-tick)
        save(a.out / "summary.json", report)
        print(json.dumps(dict(phase=phase, controls=len(report["controls"]), elapsed_s=report["elapsed_s"])), flush=True)
    def command(argv, folder, log):
        assert time.monotonic()-tick < 240 and shutil.disk_usage(a.out).free > 2*1024**3
        paired.check_resource(a.resource_check, a.kit)
        receipt = paired.owned_command([str(x) for x in argv], folder, log, 15)
        save(log.with_suffix(".receipt.json"), receipt)
        assert not receipt["timeout"] and not receipt["launch_error"] and receipt["remaining_live_group"] == []
        assert receipt["returncode"] == 0
    try:
        cases = []
        roles_set = [("clk", "din", "q"), ("clock", "Word", "Pulse")]
        variants = ["registered_positive", "registered_negative", "combinational", "zero"]
        for width in [2, 3, 5]:
            for kind in ["rising", "any"]:
                for role_id, roles in enumerate(roles_set):
                    key = f"W{width}_{kind}_R{role_id}"
                    text = prompt(width, kind, roles)
                    c = edge.parse(text)
                    assert c["status"] == "supported" and c["width"] == width and c["kind"] == kind
                    c["family"] = "edge"
                    task = "Constructed_" + key
                    original = edge.render_tb(c, task)
                    tb = instrument_tb(original, c)
                    for variant in variants:
                        folder = a.out / (key + "_" + variant)
                        folder.mkdir()
                        (folder / "prompt.txt").write_text(text)
                        save(folder / "contract.json", c)
                        (folder / "original_tb.sv").write_text(original)
                        (folder / "tb.sv").write_text(tb)
                        (folder / "dut.sv").write_text(design(width, kind, roles, variant))
                        cases.append(dict(key=key, variant=variant, folder=folder, contract=c,
                            expected_pass=variant == "registered_positive" or (variant == "registered_negative" and kind == "rising")))
        assert len(cases) == 48 and sum(x["expected_pass"] for x in cases) == 18
        inputs = {str(p.relative_to(a.out)): sha(p) for p in a.out.rglob("*") if p.is_file()}
        save(a.out / "FROZEN_INPUT_MANIFEST.json", inputs)
        publish("all_48_constructed_sources_frozen")
        outputs = {}
        for case in cases:
            folder, c = case["folder"], case["contract"]
            report["actual_compile"] += 1
            command([prefix/"bin/iverilog", "-g2012", "-s", "R2Probe", "-o", folder/"simulation.vvp", folder/"dut.sv", folder/"tb.sv"], folder, folder/"compile.log")
            report["actual_sim"] += 1
            command([prefix/"bin/vvp", folder/"simulation.vvp"], folder, folder/"simulate.log")
            log = (folder/"simulate.log").read_text()
            observations, bound = context(log, c, edge)
            feedback = render_feedback(c, bound, original_feedback)
            assert (bound is None) == case["expected_pass"]
            assert bool(feedback) == (not case["expected_pass"])
            if bound:
                old = original_feedback.render(c, dict(failure_kind="semantic_mismatch", mismatches=bound["mismatches"], checks=c["checks"]), bound["first"])
                assert feedback.startswith(old + " Related observations")
            save(folder/"observations.json", observations)
            save(folder/"feedback.json", dict(context=bound, text=feedback))
            report["controls"].append(dict(key=case["key"], variant=case["variant"], expected_pass=case["expected_pass"],
                actual_pass=bound is None, checks=len(observations), mismatches=sum(x["mismatch"] for x in observations)))
            outputs[case["key"], case["variant"]] = (observations, bound, log, c)
            publish("measured_" + folder.name)
        for key in sorted({x["key"] for x in cases}):
            correct = outputs[key, "registered_positive"][0]
            zero = outputs[key, "zero"][0]
            _, bound, log, c = outputs[key, "combinational"]
            first = bound["first"]
            original_point = lambda x: x["step"] == first["step"] and x["phase"] == first["phase"]
            cp, zp = [next(x for x in rows if original_point(x)) for rows in [correct, zero]]
            assert not cp["mismatch"] and not zp["mismatch"]
            cg = [x for x in correct if x["step"] == first["step"]]
            zg = [x for x in zero if x["step"] == first["step"]]
            assert len(cg) >= 2 and not any(x["mismatch"] for x in cg) and any(x["mismatch"] for x in zg)
            report["ambiguity_witnesses"].append(dict(key=key, first_phase=first["phase"],
                wrong_zero_matches_single_point=True, wrong_zero_rejected_by_phase_group=True))
            trace = [x for x in log.splitlines() if x.startswith("EDGE_TRACE")]
            first_trace, second_trace = trace[:2]
            bad = [log.replace(first_trace+"\n", "", 1),
                   log.replace(first_trace, first_trace+"\n"+first_trace, 1),
                   log.replace(first_trace, "SWAP_TOKEN", 1).replace(second_trace, first_trace, 1).replace("SWAP_TOKEN", second_trace, 1),
                   log.replace(first_trace, re.sub(r"expected=[0-9a-f]+", "expected=1", first_trace), 1),
                   log.replace(first_trace, re.sub(r"phase=\w+", "phase=alien", first_trace), 1),
                   log.replace(first_trace, re.sub(r"observed=\w+", "observed="+format(2**c["width"], "x"), first_trace), 1),
                   re.sub(r"EDGE_FIRST step=\d+", "EDGE_FIRST step=999", log, count=1),
                   re.sub(r"(R2_PROBE_RESULT .* checks=)\d+", r"\g<1>9999", log, count=1)]
            assert len(bad) == 8 and all(x != log for x in bad)
            for altered in bad:
                try:
                    context(altered, c, edge)
                except (AssertionError, ValueError):
                    report["invalid_trace_rejections"] += 1
                else:
                    raise AssertionError("unbound or corrupt trace accepted")
        assert len(report["ambiguity_witnesses"]) == 12 and report["invalid_trace_rejections"] == 96
        assert all(sha(a.out/n) == h for n, h in inputs.items())
        verify_tools()
        paired.check_resource(a.resource_check, a.kit)
        report.update(complete=True, input_integrity_verified=True, correct_controls=18, negative_controls=30,
            conclusion="Phase-group observations distinguish a wrong constant design that matches a single counterexample point. No model repair benefit or generalization measured.")
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        publish("completed" if report["complete"] else "failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["kit", "out", "resource-check", "original-dir", "paired", "toolchain-manifest"]:
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    run(parser.parse_args())
