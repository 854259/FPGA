"""Research-only append preservation and candidate-only compilation gate.

No testbench, task name, grade, repair or model request enters this decision.
Unexpected tool/environment failures stop execution rather than become fallback.
"""
import hashlib
from pathlib import Path
import re

from extract_bundle import extract_bundle


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def proposal(text, baseline, strip_noncode):
    a = baseline.extract(text, "rtl")
    b, raw = extract_bundle(text, baseline, strip_noncode)
    receipt = dict(raw=raw, original_sha256=sha(a), proposed_sha256=sha(b),
                   final_sha256=sha(a), compile_required=False, decision="unchanged")
    if a == b:
        return a, receipt
    code, closed = strip_noncode(a)
    # Preserve the exact originally selected top body, including its comments.
    # This is deliberately append-only when baseline contains a real TopModule.
    if re.search(r"\bmodule\s+TopModule\b", code) and not b.startswith(a + "\n"):
        receipt["decision"] = "original_top_not_prefix"
        return a, receipt
    receipt.update(compile_required=True, decision="candidate_pending")
    return b, receipt


def decide(text, baseline, strip_noncode, paired, out, tool_bin):
    proposed, receipt = proposal(text, baseline, strip_noncode)
    if not receipt["compile_required"]:
        return proposed, receipt
    a = baseline.extract(text, "rtl")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / "dut.sv").write_text(proposed, encoding="utf-8")
    receipt["stages"] = []
    for name, argv in (
        ("xvlog", ["xvlog", "-sv", "--nolog", "dut.sv"]),
        ("xelab", ["xelab", "TopModule", "-s", "bundle_gate", "--nolog", "-timescale", "1ns/1ps"]),
    ):
        command = [str(Path(tool_bin) / argv[0]), *argv[1:]]
        result = paired.owned_command(command, out, out / (name + ".log"), 60)
        result.update(name=name, argv=command)
        receipt["stages"].append(result)
        log = (out / (name + ".log")).read_text(encoding="utf-8")
        if result["timeout"] or result["launch_error"] or result["remaining_live_group"]:
            raise RuntimeError("Candidate gate supervision/environment failure")
        if re.search(r"(?i)(license.*(?:fail|error|checkout)|segmentation fault|internal error)", log):
            raise RuntimeError("Candidate gate license/internal failure")
        if result["returncode"] != 0:
            # Require a real source diagnostic; arbitrary nonzero is not proof.
            if not re.search(r"^ERROR: \[VRFC \d+-\d+\]", log, re.M):
                raise RuntimeError("Unclassified candidate gate tool failure")
            receipt.update(decision="candidate_source_error", final_sha256=sha(a))
            return a, receipt
        bounds = re.findall(r"^WARNING: \[VRFC 10-3705\].*$", log, re.M)
        if bounds:
            receipt.update(decision="candidate_bounds_warning", bounds_warnings=bounds,
                           final_sha256=sha(a))
            return a, receipt
    receipt.update(decision="candidate_accepted", final_sha256=sha(proposed))
    return proposed, receipt
