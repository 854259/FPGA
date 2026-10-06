"""AMD-only metadata admission probe; never imports the downloaded verifier."""
import argparse
import ast
import hashlib
import json
import re
import time
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

def inventory_metadata(args, started):
    """Inventory Git metadata only; never open a task, reference or result body."""
    if sys.platform != "linux":
        raise ValueError("AMD execution required")
    raw_plan = args.inventory_plan.read_bytes()
    if hashlib.sha256(raw_plan).hexdigest() != args.inventory_plan_sha256:
        raise ValueError("inventory plan drift")
    plan = json.loads(raw_plan)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("inventory source drift")
    raw = args.git_tree.read_bytes()
    if hashlib.sha256(raw).hexdigest() != plan["git_tree_sha256"]:
        raise ValueError("Git metadata drift")
    tree = json.loads(raw)
    if tree.get("truncated") is not False or tree.get("sha") != plan["upstream_commit"]:
        raise ValueError("incomplete or wrong upstream tree")
    paths = [row["path"] for row in tree["tree"]]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate Git paths")
    for row in tree["tree"]:
        if (row["path"].startswith("/") or ".." in row["path"].split("/")
                or not re.fullmatch(r"[0-9a-f]{40}", row["sha"])):
            raise ValueError("invalid Git metadata")
    blobs = [row for row in tree["tree"] if row["type"] == "blob"]
    prompts = [row for row in blobs if row["path"].startswith("Src/")
               and "/des/" in row["path"] and row["path"].endswith("/description.txt")]
    references = [row for row in blobs if row["path"].startswith("Des/")
                  and row["path"].endswith("/description.txt")]
    families = plan["family_roots"]  # Declared repository families, never task-ID exceptions.
    rows = []
    family_counts = {}
    for prompt in sorted(prompts, key=lambda row: row["path"]):
        family = prompt["path"].split("/")[1]
        if family not in families:
            raise ValueError("undeclared source family")
        family_counts[family] = family_counts.get(family, 0) + 1
        # Content-addressed pairing also exposes aliases; do not guess module names.
        matches = [row for row in references
                   if row["path"].split("/")[1] == families[family]
                   and row["sha"] == prompt["sha"] and row["size"] == prompt["size"]]
        assets = []
        if len(matches) == 1:
            directory = matches[0]["path"].rsplit("/", 1)[0] + "/"
            assets = [row for row in blobs if row["path"].startswith(directory)
                      and row["path"].lower().endswith((".v", ".sv", ".vh", ".svh"))]
        upstream = [row for row in blobs if row["path"].startswith("Src/"+family+"/")
                    and "/des/" not in row["path"]]
        asset_rows = [dict(path=a["path"], git_blob=a["sha"], bytes=a["size"],
                           upstream_same_blob_paths=[u["path"] for u in upstream
                                                     if u["sha"] == a["sha"]]) for a in assets]
        rows.append(dict(source_prompt_path=prompt["path"], family=family,
                         prompt_git_blob=prompt["sha"], description_bytes=prompt["size"],
                         matching_reference_prompt_paths=[m["path"] for m in matches],
                         reference_directory_rtl_assets=asset_rows,
                         pairing_unique=len(matches) == 1,
                         declared_license=plan["declared_family_license"][family],
                         contract_verified=False, dependencies_verified=False,
                         reference_trust_verified=False, independent_admitted=False))
    if len(rows) != plan["expected_tasks"] or family_counts != plan["expected_family_counts"]:
        raise ValueError("declared task/family count mismatch")
    report = dict(schema="source_contract_metadata_20261006_v1", complete=True,
                  source_sha256=plan["source_sha256"], upstream_commit=tree["sha"],
                  git_tree_sha256=plan["git_tree_sha256"], tree_entries=len(paths),
                  task_count=len(rows), family_counts=family_counts,
                  reference_description_count=len(references),
                  unique_description_blobs=len({r["prompt_git_blob"] for r in rows}),
                  unique_pairs=sum(r["pairing_unique"] for r in rows),
                  rows_with_no_rtl_assets=sum(not r["reference_directory_rtl_assets"] for r in rows),
                  rtl_assets=sum(len(r["reference_directory_rtl_assets"]) for r in rows),
                  assets_without_same_blob_upstream=sum(not a["upstream_same_blob_paths"]
                      for r in rows for a in r["reference_directory_rtl_assets"]),
                  task_rows=rows, model_calls=0, compiler_calls=0, simulator_calls=0,
                  task_prompts_or_reference_bodies_opened=False,
                  result_bodies_opened=False, upstream_code_executed=False,
                  team_wide_exposure="unknown", training_exposure="unknown",
                  independent_admitted=0, effective_independent_family_n=None,
                  full_batch_complete=False,
                  evidence_limit="Git-declared paths/blob identities only, not body verification or correctness. "
                    "No RTL-versus-testbench distinction, interface inference or dependency completeness from filenames.",
                  decision="Use inventory to freeze evaluation-side contract/source checks. "
                    "Retain every missing/ambiguous record; no model run, task selection or source stubbing.",
                  elapsed_s=time.monotonic()-started)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "RESULT.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: v for k, v in report.items() if k != "task_rows"}))

def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", type=Path)
    source.add_argument("--git-tree", type=Path)
    ap.add_argument("--inventory-plan", type=Path)
    ap.add_argument("--inventory-plan-sha256")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resource-check", type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    # The external resource guard owns slot/model/process checks; its receipt must exist.
    guard = json.loads(args.resource_check.read_text())
    if not guard:
        raise ValueError("missing resource admission")
    if args.git_tree:
        if not args.inventory_plan or not args.inventory_plan_sha256 or not guard.get("resource_idle"):
            raise ValueError("frozen inventory plan and idle resource admission required")
        return inventory_metadata(args, started)
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
