"""AMD-only metadata admission probe; never imports the downloaded verifier."""
import argparse
import ast
import hashlib
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resource-check", type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    # The external resource guard owns slot/model/process checks; its receipt must exist.
    guard = json.loads(args.resource_check.read_text())
    if not guard:
        raise ValueError("missing resource admission")
    raw = args.source.read_bytes()
    expected = "396da5f709ecd2ec79272f788a089992f1863d2e9b78d6aa103c70f4e44cc4ed"
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("upstream verifier drift")
    tree = ast.parse(raw)
    functions = {"strip_comments", "read_text", "tb_is_self_checking",
                 "sim_failure_lines", "pass_metrics"}
    constants = {"SIM_FAIL_RE", "NEGATED_FAIL_RE", "STRING_LITERAL_RE",
                 "SELF_CHECK_TOKEN_RE"}
    selected = []
    found = set()
    spans = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(node)
            found.add(node.name)
            spans[node.name] = [node.lineno, node.end_lineno]
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in constants:
                selected.append(node)
                found.add(target.id)
                spans[target.id] = [node.lineno, node.end_lineno]
    if found != functions | constants:
        raise ValueError("reviewed function or constant missing")
    # Only the nine reviewed nodes execute: no upstream imports, CLI, subprocess or model code.
    env = {"re": re, "Path": Path, "Sequence": Sequence,
           "CandidateResult": SimpleNamespace}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(args.source), "exec"), env)
    args.out.mkdir(parents=True, exist_ok=False)
    cases = [
        ("literal_no_errors", 'module tb; initial begin $display("No errors"); $finish; end endmodule', True, False),
        ("plain_print", 'module tb; initial begin $display("done"); $finish; end endmodule', False, False),
        ("conditional_mismatch", 'module tb; reg a,b; initial if(a!==b) $display("MISMATCH"); endmodule', True, True),
        ("comment_only", 'module tb; // error mismatch\ninitial $finish; endmodule', False, False),
    ]
    rows = []
    for name, source, expected_classifier, has_comparison in cases:
        path = args.out / (name + ".sv")
        path.write_text(source)
        actual = env["tb_is_self_checking"](path)
        assert actual is expected_classifier, name
        rows.append(dict(control=name, classified_self_checking=actual,
                         has_functional_comparison=has_comparison,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    no_errors = env["sim_failure_lines"]("No errors\n")
    actual_error = env["sim_failure_lines"]("MISMATCH\n")
    assert no_errors == [] and actual_error == ["MISMATCH"]
    bounded = env["pass_metrics"]([SimpleNamespace(
        status="pass", flow="equivalence", proof_type="bounded_seq")])
    assert bounded["function_pass"] == 1 and bounded["equivalence_pass_full"] == 0
    report = dict(
        schema="source_metadata_admission_20261006", complete=True,
        source_commit="3eea482f20c048966d54ed04c418b85e5fd4d498",
        source_sha256=expected, source_spans=spans, controls=rows,
        literal_no_errors_failure_lines=no_errors,
        actual_mismatch_failure_lines=actual_error,
        bounded_row_aggregate=bounded,
        classifier_false_positive_demonstrated=True,
        full_benchmark_false_acceptance_measured=False,
        compiler_calls=0, simulator_calls=0, model_calls=0,
        upstream_imported=False, upstream_cli_executed=False,
        task_prompts_or_reference_bodies_opened=False,
        independent_admitted=0, full_batch_complete=False,
        decision="Do not admit generic function_pass as full-correctness evidence. "
                 "Keep source as a candidate only; no corpus expansion or new generation.",
        elapsed_s=time.monotonic()-started,
    )
    (args.out / "RESULT.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()

